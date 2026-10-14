"""Small source-focused storage evidence, not historical financial execution."""

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import asdict, replace

import pytest

from adaptive_replay import compact_commit_plan_store_v3 as module
from adaptive_replay import compact_four_arm_driver_journal_v3 as compact
from adaptive_replay.continuous_four_arm_v3 import (
    ARMS,
    CompactCommitPlanV3,
    compact_commit_plan_document,
    compact_commit_plan_from_document,
)
from adaptive_replay.historical_context import digest
from adaptive_replay.sim_financial_journal_v3 import FinancialCheckpointV3
from adaptive_replay.sim_state_journal import (
    EventConflict,
    JournalError,
    JournalFull,
    JournalIdentity,
    OptimisticConflict,
    _canonical,
    _hash,
)

LIMITS = module.CompactCommitPlanStoreLimitsV3(128, 512 * 1024, 4 * 1024 * 1024)
DRIVER_LIMITS = compact.CompactDriverLimitsV3(256, 128, 65536, 1024 * 1024, 256 * 1024, 16, 4 * 1024 * 1024)
DRIVER_IDENTITY = JournalIdentity("owner", "retained-originals", "unchanged-risk", "explicit-compact")


def _genesis():
    accounts = {
        arm: asdict(FinancialCheckpointV3("a" * 64, "owner", arm, 0, "b" * 64, "c" * 64, 0, 0, 0, "d" * 64))
        for arm in ARMS
    }
    return {
        "identity": "e" * 64,
        "cursor": 0,
        "pending": None,
        "finished": False,
        "account_config": {arm: {"owner": "owner", "arm": arm} for arm in ARMS},
        "account_identity": {arm: {"arm": arm} for arm in ARMS},
        "account_checkpoints": accounts,
        "report": None,
    }


def _plans(directory, count=3, value=None):
    """Build retained BEFORE-COMMIT plans and compare with the real compact fold."""
    with compact.CompactFourArmDriverJournalV3.create(
        directory / "actual-driver.sqlite",
        identity=DRIVER_IDENTITY,
        initial_state=_genesis(),
        limits=DRIVER_LIMITS,
    ) as driver:
        identity = module.CompactCommitPlanStoreIdentityV3(
            "owner", "e" * 64, driver.checkpoint().identity_sha256, tuple((arm, "a" * 64) for arm in ARMS)
        )
        plans = []
        for index in range(count):
            operation = {"kind": "CELL", "at": index + 1, "original": "полный оригинал"}
            pending = {
                "operation": operation,
                "before": driver.snapshot().state["account_checkpoints"],
                "effects": dict.fromkeys(ARMS),
            }
            driver.record_intent(pending, at_ms=index + 1, expected_checkpoint=driver.checkpoint())
            before, hot = driver.checkpoint(), driver.snapshot().state
            record = compact.ColdHistoryRecordV3(
                "cells",
                f"cell-{index:03}",
                {"status": "UNKNOWN", "amount": None, "original": index} if value is None else value,
            )
            refs = hot["history_refs"]
            row = {
                "ordinal": index + 1,
                "collection": "cells",
                "collection_ordinal": index + 1,
                "key": record.key,
                "content_hash": _hash(_canonical(record.value)),
                "previous_hash": refs["cells"]["head"],
                "outer_version": before.version + 1,
                "within_outer": 1,
            }
            refs["cells"] = {"count": index + 1, "head": compact._cold_hash(row)}
            hot.update(pending=None, cursor=index + 1)
            plan = compact_commit_plan_from_document(
                compact_commit_plan_document(
                    CompactCommitPlanV3(
                        "e" * 64,
                        before,
                        f"operation:{index}:commit",
                        {
                            "operation": operation,
                            "pending_sha256": digest(pending),
                            "account_checkpoints": pending["before"],
                            "cold_records": [asdict(record)],
                            "report": None,
                        },
                        index + 1,
                        {"status": "COMMITTED", "operation_cursor": index + 1},
                        hot,
                        (record,),
                    )
                )
            )
            plans.append(plan)  # Independently retained before changing the driver head.
            result = driver.commit_operation(
                operation=operation,
                pending_sha256=digest(pending),
                account_checkpoints=pending["before"],
                cold_records=(record,),
                at_ms=index + 1,
                expected_checkpoint=before,
            )
            assert (
                result.snapshot.state == plan.expected_hot_state and result.outcome == plan.expected_outcome
            )
    return identity, plans


def _create(path, identity, limits=LIMITS):
    return module.CompactCommitPlanStoreV3.create(path, identity=identity, limits=limits)


def _open(path, identity, anchor, limits=LIMITS):
    return module.CompactCommitPlanStoreV3.open(
        path, identity=identity, limits=limits, expected_anchor=anchor
    )


def _known(path, identity, before, plan, limits=LIMITS):
    return module.CompactCommitPlanStoreV3.open_after_known_persist(
        path, identity=identity, limits=limits, expected_before_anchor=before, expected_plan=plan
    )


def _lookup(store, plan, anchor):
    return store.lookup(
        before_version=plan.expected_before.version, event_id=plan.expected_event_id, expected_anchor=anchor
    )


def _raw(path, sql, parameters=()):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(sql, parameters)


def test_original_plans_real_compact_differential_exact_restart_and_no_ack(tmp_path):
    identity, plans = _plans(tmp_path, 12)
    path = tmp_path / "plans.sqlite"
    with _create(path, identity) as store:
        start = store.anchor()
        for ordinal, plan in enumerate(plans, 1):
            receipt = store.persist(plan, expected_anchor=store.anchor())
            assert receipt.ordinal == ordinal and receipt.replayed is False and receipt.ack_eligible is False
            assert receipt.anchor == store.anchor()
            with pytest.raises(JournalError, match="not ACK"):
                bool(receipt)
            assert receipt is not True and not callable(store)
        held = store.anchor()
        assert held.count == 12 and held != start and store.audit(expected_anchor=held) == held
        for plan in plans:
            assert _lookup(store, plan, held) == plan
            replay = store.persist(plan, expected_anchor=held)
            assert replay.replayed and replay.anchor == held
        with closing(sqlite3.connect(path)) as connection:
            original = connection.execute("SELECT plan_json FROM plans ORDER BY ordinal").fetchall()
        assert [row[0] for row in original] == [
            _canonical(compact_commit_plan_document(plan)) for plan in plans
        ]
    with _open(path, identity, held) as store:
        assert store.anchor() == held and _lookup(store, plans[0], held) == plans[0]
    with pytest.raises(OptimisticConflict):
        _open(path, identity, start)


def test_hot_append_duplicate_and_lookup_use_indexes_not_history(tmp_path):
    identity, plans = _plans(tmp_path, 4)
    with _create(tmp_path / "plans.sqlite", identity) as store:
        store.persist(plans[0], expected_anchor=store.anchor())
        statements = []
        store._connection.set_trace_callback(statements.append)
        for plan in plans[1:]:
            store.persist(plan, expected_anchor=store.anchor())
        store.persist(plans[0], expected_anchor=store.anchor())
        _lookup(store, plans[0], store.anchor())
        sql = "\n".join(statements).upper()
        assert "COUNT(" not in sql and "INTEGRITY_CHECK" not in sql and "ORDER BY ORDINAL" not in sql
        assert "SELECT * FROM PLANS WHERE ORDINAL=" in sql
        assert "SELECT * FROM PLANS WHERE DRIVER_BEFORE_VERSION=" in sql


def test_conflicting_duplicate_and_stale_lookup_keep_original_bytes(tmp_path):
    identity, plans = _plans(tmp_path)
    with _create(tmp_path / "plans.sqlite", identity) as store:
        start = store.anchor()
        held = store.persist(plans[0], expected_anchor=start).anchor
        changed = replace(plans[0], expected_before=replace(plans[0].expected_before, head_hash="f" * 64))
        with pytest.raises(EventConflict):
            store.persist(changed, expected_anchor=held)
        with pytest.raises(OptimisticConflict):
            _lookup(store, plans[0], start)
        assert _lookup(store, plans[0], held) == plans[0] and store.anchor() == held
        assert store.lookup(before_version=99, event_id="unknown", expected_anchor=held) is None


def test_original_object_mutation_during_commit_cannot_rewrite_frozen_plan(tmp_path, monkeypatch):
    identity, plans = _plans(tmp_path)
    original_bytes = _canonical(compact_commit_plan_document(plans[0]))
    with _create(tmp_path / "plans.sqlite", identity) as store:

        def mutate():
            plans[0].expected_cold_records[0].value["amount"] = "0"
            store._connection.commit()

        monkeypatch.setattr(store, "_commit", mutate)
        receipt = store.persist(plans[0], expected_anchor=store.anchor())
        retained = _lookup(store, plans[0], receipt.anchor)
        assert _canonical(compact_commit_plan_document(retained)) == original_bytes
        assert retained.expected_cold_records[0].value["amount"] is None


def test_nested_callback_operation_refused_and_transaction_rolled_back(tmp_path, monkeypatch):
    identity, plans = _plans(tmp_path)
    with _create(tmp_path / "plans.sqlite", identity) as store:
        before = store.anchor()
        monkeypatch.setattr(store, "_commit", lambda: store.anchor())
        with pytest.raises(JournalError, match="nested"):
            store.persist(plans[0], expected_anchor=before)
        assert store.anchor() == before and _lookup(store, plans[0], before) is None


class _ConnectionFault:
    def __init__(self, connection, prefix):
        self.connection, self.prefix = connection, prefix

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, sql, parameters=()):
        if sql.startswith(self.prefix):
            raise RuntimeError("injected SQL failure")
        return self.connection.execute(sql, parameters)


@pytest.mark.parametrize("boundary", ["insert", "projection", "precommit"])
def test_every_write_exception_rolls_back_plan_and_projection(tmp_path, boundary, monkeypatch):
    identity, plans = _plans(tmp_path)
    path = tmp_path / "plans.sqlite"
    with _create(path, identity) as store:
        before = store.anchor()
        if boundary == "precommit":
            original = store._commit

            def fail():
                raise RuntimeError("injected precommit failure")

            monkeypatch.setattr(store, "_commit", fail)
        else:
            original = store._connection
            store._connection = _ConnectionFault(
                original, "INSERT INTO plans" if boundary == "insert" else "UPDATE head"
            )
        with pytest.raises(RuntimeError):
            store.persist(plans[0], expected_anchor=before)
        if boundary == "precommit":
            monkeypatch.setattr(store, "_commit", original)
        else:
            store._connection = original
        assert store.anchor() == before and _lookup(store, plans[0], before) is None
    with _open(path, identity, before) as store:
        assert store.audit(expected_anchor=before) == before


def test_sql_commit_lost_response_requires_retained_known_original_not_latest(tmp_path, monkeypatch):
    identity, plans = _plans(tmp_path)
    path = tmp_path / "plans.sqlite"
    with _create(path, identity) as store:
        before = store.anchor()

        def lost():
            store._connection.commit()
            raise RuntimeError("COMMIT response lost; no bundle ACK")

        monkeypatch.setattr(store, "_commit", lost)
        with pytest.raises(RuntimeError):
            store.persist(plans[0], expected_anchor=before)
        assert store._retained == before
        with pytest.raises(OptimisticConflict):
            store.anchor()
    with pytest.raises(OptimisticConflict):
        _open(path, identity, before)
    changed = replace(plans[0], expected_before=replace(plans[0].expected_before, state_hash="f" * 64))
    with pytest.raises(EventConflict):
        _known(path, identity, before, changed)
    with pytest.raises(OptimisticConflict):
        _known(path, identity, replace(before, head_hash="f" * 64), plans[0])
    with _known(path, identity, before, plans[0]) as recovered:
        held = recovered.anchor()
        assert held.count == 1 and _lookup(recovered, plans[0], held) == plans[0]
        assert recovered.persist(plans[0], expected_anchor=held).ack_eligible is False


@pytest.mark.parametrize("new_count", [0, 2])
def test_known_recovery_refuses_zero_or_two_new_plans(tmp_path, new_count):
    identity, plans = _plans(tmp_path)
    path = tmp_path / "plans.sqlite"
    with _create(path, identity) as store:
        before = store.anchor()
        for plan in plans[:new_count]:
            store.persist(plan, expected_anchor=store.anchor())
    with pytest.raises(OptimisticConflict):
        _known(path, identity, before, plans[0])


@pytest.mark.parametrize("reader", ["lookup", "duplicate", "anchor"])
def test_external_middle_rehash_is_audited_before_indexed_response(tmp_path, reader):
    identity, plans = _plans(tmp_path)
    path = tmp_path / "plans.sqlite"
    with _create(path, identity) as store:
        for plan in plans:
            store.persist(plan, expected_anchor=store.anchor())
        held = store.anchor()
        row = dict(store._connection.execute("SELECT * FROM plans WHERE ordinal=1").fetchone())
        mutated = replace(plans[0], expected_before=replace(plans[0].expected_before, state_hash="f" * 64))
        row["plan_json"] = _canonical(compact_commit_plan_document(mutated))
        row["plan_sha256"] = _hash(row["plan_json"])
        row["plan_bytes"] = len(row["plan_json"].encode("utf-8"))
        row["record_hash"] = store._row_hash(row)
        _raw(
            path,
            "UPDATE plans SET plan_json=?,plan_sha256=?,plan_bytes=?,record_hash=? WHERE ordinal=1",
            (row["plan_json"], row["plan_sha256"], row["plan_bytes"], row["record_hash"]),
        )
        with pytest.raises(JournalError):
            if reader == "lookup":
                _lookup(store, plans[0], held)
            elif reader == "duplicate":
                store.persist(plans[0], expected_anchor=held)
            else:
                store.anchor()


def test_external_benign_write_audits_once_unknown_writer_never_rebases(tmp_path):
    identity, plans = _plans(tmp_path)
    path = tmp_path / "plans.sqlite"
    with _create(path, identity) as store:
        held = store.persist(plans[0], expected_anchor=store.anchor()).anchor
        _raw(path, "PRAGMA application_id=73")  # Actual benign external header write, not optimized no-op.
        statements = []
        store._connection.set_trace_callback(statements.append)
        assert _lookup(store, plans[0], held) == plans[0]
        assert sum("ORDER BY ordinal" in sql for sql in statements) == 1
        statements.clear()
        assert _lookup(store, plans[0], held) == plans[0]
        assert not any("ORDER BY ordinal" in sql for sql in statements)
        with _open(path, identity, held) as writer:
            after = writer.persist(plans[1], expected_anchor=held).anchor
        with pytest.raises(OptimisticConflict):
            store.persist(plans[0], expected_anchor=held)
        assert store._retained == held and after != held


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE metadata SET value='changed' WHERE key='schema'",
        "UPDATE head SET count=0,last_plan_sha256=NULL WHERE singleton=1",
        "DELETE FROM plans WHERE ordinal=1",
        "CREATE TABLE old_driver_history(fake TEXT)",
        "PRAGMA user_version=3",
    ],
)
def test_open_full_audit_refuses_tampered_schema_projection_history(tmp_path, sql):
    identity, plans = _plans(tmp_path)
    path = tmp_path / "plans.sqlite"
    with _create(path, identity) as store:
        held = store.persist(plans[0], expected_anchor=store.anchor()).anchor
    _raw(path, sql)
    with pytest.raises(JournalError):
        _open(path, identity, held)


def test_explicit_typed_anchors_identity_and_limits_are_sealed(tmp_path):
    identity, plans = _plans(tmp_path)
    path = tmp_path / "plans.sqlite"
    with _create(path, identity) as store:
        held = store.anchor()
        with pytest.raises(JournalError):
            store.persist(plans[0], expected_anchor=asdict(held))
    with pytest.raises(JournalError):
        _open(path, identity, asdict(held))
    with pytest.raises(OptimisticConflict):
        _open(path, identity, held, replace(LIMITS, max_plan_rows=127))
    with pytest.raises(OptimisticConflict):
        _open(path, replace(identity, campaign_id="other"), held)
    with pytest.raises(FileExistsError):
        _create(path, identity)
    with pytest.raises(JournalError):
        _known(path, identity, held, None)
    with pytest.raises(JournalError):
        _open(tmp_path / "actual-driver.sqlite", identity, held)  # Never reinterpret compact driver schema.


@pytest.mark.parametrize("change", ["owner", "account_identity", "profile", "cold", "unknown_field", "gap"])
def test_closed_plan_cross_owner_profile_and_original_roster_refuse(tmp_path, change):
    identity, plans = _plans(tmp_path)
    document = compact_commit_plan_document(plans[0])
    if change == "owner":
        for field in (
            document["expected_payload"]["account_checkpoints"],
            document["expected_hot_state"]["account_checkpoints"],
        ):
            field[ARMS[0]]["owner_id"] = "other"
    elif change == "account_identity":
        for field in (
            document["expected_payload"]["account_checkpoints"],
            document["expected_hot_state"]["account_checkpoints"],
        ):
            field[ARMS[0]]["identity_sha256"] = "f" * 64
    elif change == "profile":
        document["expected_hot_state"]["profile"] = "FINANCIAL_V3"
    elif change == "cold":
        document["expected_payload"]["cold_records"][0]["value"]["amount"] = "0"
    elif change == "unknown_field":
        document["expected_hot_state"]["new_unknown"] = "never ignore"
    else:
        document = compact_commit_plan_document(plans[1])
    with _create(tmp_path / "plans.sqlite", identity) as store:
        before = store.anchor()
        with pytest.raises(JournalError):
            store.persist(compact_commit_plan_from_document(document), expected_anchor=before)
        assert store.anchor() == before


def test_row_byte_and_sqlite_bounds_are_atomic_no_original_eviction(tmp_path):
    identity, plans = _plans(tmp_path)
    with _create(tmp_path / "row.sqlite", identity, replace(LIMITS, max_plan_rows=1)) as store:
        held = store.persist(plans[0], expected_anchor=store.anchor()).anchor
        with pytest.raises(JournalFull):
            store.persist(plans[1], expected_anchor=held)
        assert _lookup(store, plans[0], held) == plans[0] and store.anchor() == held
    size = len(_canonical(compact_commit_plan_document(plans[0])).encode("utf-8"))
    with _create(tmp_path / "byte.sqlite", identity, replace(LIMITS, max_plan_bytes=size - 1)) as store:
        before = store.anchor()
        with pytest.raises(JournalFull):
            store.persist(plans[0], expected_anchor=before)
        assert store.anchor() == before
    large = tmp_path / "large"
    large.mkdir()
    large_identity, large_plans = _plans(
        large, 1, {"status": "UNKNOWN", "amount": None, "original": "x" * 100000}
    )
    with _create(tmp_path / "db.sqlite", large_identity, replace(LIMITS, max_database_bytes=32768)) as store:
        before = store.anchor()
        with pytest.raises(JournalFull):
            store.persist(large_plans[0], expected_anchor=before)
        assert store.anchor() == before and _lookup(store, large_plans[0], before) is None


def _fsync_original(path, value):
    with path.open("xb") as stream:
        stream.write(_canonical(value).encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


@pytest.mark.parametrize("boundary", ["precommit", "postcommit"])
def test_actual_process_crash_original_retained_plan_and_strict_anchor(tmp_path, boundary):
    identity, plans = _plans(tmp_path)
    path = tmp_path / "plans.sqlite"
    with _create(path, identity) as store:
        store.persist(plans[0], expected_anchor=store.anchor())
        before = store.anchor()
    retained = {
        "identity": asdict(identity),
        "limits": asdict(LIMITS),
        "anchor": asdict(before),
        "plan": compact_commit_plan_document(plans[1]),
    }
    _fsync_original(tmp_path / "caller-retained.json", retained)
    script = """
import json, os, sys
from pathlib import Path
from adaptive_replay import compact_commit_plan_store_v3 as module
from adaptive_replay.continuous_four_arm_v3 import compact_commit_plan_from_document
root, boundary = Path(sys.argv[1]), sys.argv[2]
retained = json.loads((root/'caller-retained.json').read_text(encoding='utf-8'))
values = retained['identity']
values['account_identity_sha256'] = tuple(tuple(pair) for pair in values['account_identity_sha256'])
identity = module.CompactCommitPlanStoreIdentityV3(**values)
limits = module.CompactCommitPlanStoreLimitsV3(**retained['limits'])
before = module.PlanStoreAnchorV3(**retained['anchor'])
store = module.CompactCommitPlanStoreV3.open(
    root/'plans.sqlite', identity=identity, limits=limits, expected_anchor=before)
def crash():
    if boundary == 'postcommit':
        store._connection.commit()
    os._exit(81 if boundary == 'precommit' else 82)
store._commit = crash
store.persist(compact_commit_plan_from_document(retained['plan']), expected_anchor=before)
os._exit(99)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-W", "error", "-c", script, str(tmp_path), boundary],
        check=False,
        capture_output=True,
        timeout=180,
    )
    assert result.returncode == (81 if boundary == "precommit" else 82), result.stderr.decode()
    caller = json.loads((tmp_path / "caller-retained.json").read_text(encoding="utf-8"))
    original = compact_commit_plan_from_document(caller["plan"])
    assert original == plans[1] and module.PlanStoreAnchorV3(**caller["anchor"]) == before
    if boundary == "precommit":
        with _open(path, identity, before) as store:
            assert _lookup(store, original, before) is None and store.anchor() == before
            receipt = store.persist(original, expected_anchor=before)
            assert receipt.ack_eligible is False
    else:
        with pytest.raises(OptimisticConflict):
            _open(path, identity, before)
        with pytest.raises(EventConflict):
            _known(
                path,
                identity,
                before,
                replace(original, expected_before=replace(original.expected_before, head_hash="f" * 64)),
            )
        with _known(path, identity, before, original) as store:
            held = store.anchor()
            assert held.count == before.count + 1 and _lookup(store, original, held) == original
            assert store.persist(original, expected_anchor=held).replayed
        with pytest.raises(OptimisticConflict):
            _known(path, identity, replace(before, head_hash="f" * 64), original)
