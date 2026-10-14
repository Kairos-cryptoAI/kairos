"""Bounded storage fixtures, not historical financial replay qualification."""

import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import asdict, replace

import pytest

from adaptive_replay import compact_four_arm_driver_journal_v3 as module
from adaptive_replay.continuous_four_arm_v3 import ARMS
from adaptive_replay.historical_context import digest
from adaptive_replay.sim_delta_journal_v3 import SimDeltaJournalV3
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

IDENTITY = JournalIdentity("compact-fixture", "original-fixture", "unchanged-risk", "compact-profile")
LIMITS = module.CompactDriverLimitsV3(256, 128, 65536, 131072, 8192, 16, 4 * 1024 * 1024)


def genesis():
    accounts = {
        arm: asdict(FinancialCheckpointV3("a" * 64, "owner", arm, 0, "b" * 64, "c" * 64, 0, 0, 0, "d" * 64))
        for arm in ARMS
    }
    return {
        "identity": "e" * 64,
        "cursor": 0,
        "pending": None,
        "routes": {},
        "cells": {},
        "costs": {},
        "finished": False,
        "account_config": {arm: {"sealed": arm} for arm in ARMS},
        "account_identity": {arm: {"sealed": arm} for arm in ARMS},
        "account_checkpoints": accounts,
        "report": None,
    }


def create(path, limits=LIMITS):
    return module.CompactFourArmDriverJournalV3.create(
        path, identity=IDENTITY, initial_state=genesis(), limits=limits
    )


def reopen(path, checkpoint, limits=LIMITS):
    return module.CompactFourArmDriverJournalV3.open(
        path, identity=IDENTITY, limits=limits, expected_checkpoint=checkpoint
    )


def pending(journal, kind="CELL", at=1, effects=None):
    return {
        "operation": {"kind": kind, "at": at, "original": {"status": "UNKNOWN", "amount": None}},
        "before": journal.snapshot().state["account_checkpoints"],
        "effects": dict.fromkeys(ARMS) if effects is None else effects,
    }


def intent(journal, kind="CELL", at=1, effects=None):
    value = pending(journal, kind, at, effects)
    before = journal.checkpoint()
    journal.record_intent(value, at_ms=at, expected_checkpoint=before)
    return value, before, journal.checkpoint()


def commit(journal, value, checkpoint, records=(), accounts=None, report=None):
    return journal.commit_operation(
        operation=value["operation"],
        pending_sha256=digest(value),
        account_checkpoints=value["before"] if accounts is None else accounts,
        cold_records=records,
        at_ms=value["operation"]["at"],
        expected_checkpoint=checkpoint,
        report=report,
    )


def cell(journal, key, at=1, value=None):
    value = {"status": "UNKNOWN", "amount": None} if value is None else value
    request, _, cp = intent(journal, at=at)
    record = module.ColdHistoryRecordV3("cells", key, value)
    commit(journal, request, cp, (record,))
    return record


def recovery_plan(journal, request, checkpoint, records):
    """Retain plan BEFORE effects; never read new DB head to form expectations."""
    state = journal.snapshot().state
    refs, cold, staged = state["history_refs"], [], {}
    for record in records:
        old = journal.lookup_history(record.collection, record.key, expected_checkpoint=checkpoint)
        key = record.collection, record.key
        if old is not None or key in staged:
            assert (old.value if old is not None else staged[key]) == record.value
            continue
        ref = refs[record.collection]
        row = {
            "ordinal": sum(value["count"] for value in refs.values()) + 1,
            "collection": record.collection,
            "collection_ordinal": ref["count"] + 1,
            "key": record.key,
            "content_hash": _hash(_canonical(record.value)),
            "previous_hash": ref["head"],
            "outer_version": checkpoint.version + 1,
            "within_outer": len(cold) + 1,
        }
        row["record_hash"] = module._cold_hash(row)
        cold.append(row)
        staged[key] = record.value
        refs[record.collection] = {"count": row["collection_ordinal"], "head": row["record_hash"]}
    state.update(pending=None, cursor=state["cursor"] + 1)
    return {
        "expected_before": checkpoint,
        "expected_event_id": f"operation:{state['cursor'] - 1}:commit",
        "expected_payload": {
            "operation": request["operation"],
            "pending_sha256": digest(request),
            "account_checkpoints": request["before"],
            "cold_records": [asdict(record) for record in records],
            "report": None,
        },
        "expected_at_ms": request["operation"]["at"],
        "expected_outcome": {"status": "COMMITTED", "operation_cursor": state["cursor"]},
        "expected_hot_state": state,
        "expected_cold_records": records,
    }


def recover(path, plan, **overrides):
    return module.CompactFourArmDriverJournalV3.open_after_known_commit(
        path, identity=IDENTITY, limits=LIMITS, **dict(plan, **overrides)
    )


def raw(path, statement, parameters=()):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(statement, parameters)


def test_small_hot_state_every_original_and_exact_restart(tmp_path):
    path = tmp_path / "compact.sqlite"
    with create(path) as journal:
        start_size = len(_canonical(journal.snapshot().state))
        originals = [
            cell(journal, f"cell-{i:03}", i + 1, {"status": "UNKNOWN", "amount": None, "i": i})
            for i in range(40)
        ]
        state = journal.snapshot().state
        assert not set(module.COLLECTIONS).intersection(state)
        assert state["history_refs"]["cells"]["count"] == 40
        assert len(_canonical(state)) < start_size + 20
        assert journal.snapshot().state_hash == _hash(_canonical(state))
        cp = journal.checkpoint()
        pages, after = [], None
        while True:
            page = journal.page_history("cells", expected_checkpoint=cp, after_key=after, limit=7)
            pages.extend(page.records)
            after = page.next_key
            if after is None:
                break
        assert pages == originals
        assert journal.audit() == journal.snapshot()
    with reopen(path, cp) as journal:
        assert journal.checkpoint() == cp
        assert journal.lookup_history("cells", "cell-000", expected_checkpoint=cp) == originals[0]
    with pytest.raises(OptimisticConflict):
        reopen(path, replace(cp, version=0))


def test_pending_crash_recovery_and_unknown_financial_prefix(tmp_path):
    path = tmp_path / "compact.sqlite"
    with create(path) as journal:
        request, _, cp = intent(
            journal,
            "SOURCE",
            effects={
                arm: {"event_id": "source:1", "payload": {"kind": "SOURCE_BATCH", "first": 1, "last": 3}}
                for arm in ARMS
            },
        )
    with reopen(path, cp) as journal:
        assert journal.snapshot().state["pending"] == request
        accounts = {
            arm: asdict(
                replace(
                    FinancialCheckpointV3(**doc),
                    version=1,
                    last_clock_ms=1,
                    source_cursor=3,
                    native_count=3,
                    native_head="f" * 64,
                    state_hash="1" * 64,
                    head_hash="2" * 64,
                )
            )
            for arm, doc in request["before"].items()
        }
        broken = dict(accounts)
        broken[ARMS[0]] = dict(accounts[ARMS[0]], source_cursor=4)
        with pytest.raises(JournalError):
            commit(journal, request, cp, accounts=broken)
        assert journal.checkpoint() == cp
        commit(journal, request, cp, accounts=accounts)
        assert journal.snapshot().state["account_checkpoints"] == accounts


def test_duplicates_exact_original_bytes_and_conflicts(tmp_path):
    with create(tmp_path / "compact.sqlite") as journal:
        request, before, cp = intent(journal)
        assert journal.record_intent(request, at_ms=1, expected_checkpoint=before).replayed
        record = module.ColdHistoryRecordV3("cells", "id", {"value": True, "amount": None})
        commit(journal, request, cp, (record,))
        assert commit(journal, request, cp, (record,)).replayed
        with pytest.raises(EventConflict):
            commit(journal, request, cp, (replace(record, value={"value": 1, "amount": None}),))
        request2, _, cp2 = intent(journal, at=2)
        commit(journal, request2, cp2, (record,))
        assert journal.snapshot().state["history_refs"]["cells"]["count"] == 1
        request3, _, cp3 = intent(journal, at=3)
        with pytest.raises(EventConflict):
            commit(journal, request3, cp3, (replace(record, value={"value": 1}),))
        assert journal.checkpoint() == cp3


@pytest.mark.parametrize("fault", ["fold", "insert", "head", "precommit"])
def test_atomic_rollback_and_expired_capability(tmp_path, monkeypatch, fault):
    with create(tmp_path / "compact.sqlite") as journal:
        request, _, cp = intent(journal)
        record = module.ColdHistoryRecordV3("cells", "id", {"status": "UNKNOWN", "amount": None})
        original_insert = journal._insert_cold
        if fault == "insert":

            def fail(row):
                original_insert(row)
                raise RuntimeError("insert crash")

            monkeypatch.setattr(journal, "_insert_cold", fail)
        elif fault == "precommit":
            monkeypatch.setattr(
                journal, "_before_commit", lambda: (_ for _ in ()).throw(RuntimeError("crash"))
            )
        elif fault == "head":
            journal._connection.execute(
                "CREATE TEMP TRIGGER fail_head BEFORE UPDATE ON head BEGIN SELECT RAISE(ABORT,'crash'); END"
            )
        if fault == "fold":
            held = []

            def fold(state, cold):
                held.append(cold)
                cold.append(record)
                raise RuntimeError("fold crash")

            with pytest.raises(RuntimeError):
                journal.transition(
                    event_id="operation:0:commit", payload={}, at_ms=1, expected_checkpoint=cp, fold=fold
                )
            with pytest.raises(JournalError):
                held[0].lookup("cells", "id")
        else:
            with pytest.raises((RuntimeError, sqlite3.Error)):
                commit(journal, request, cp, (record,))
        assert journal.checkpoint() == cp
        assert journal.lookup_history("cells", "id", expected_checkpoint=cp) is None
        assert journal.snapshot().state["pending"] == request


def test_pinned_paging_byte_budget_and_external_unknown_head(tmp_path):
    path = tmp_path / "compact.sqlite"
    with create(path) as journal:
        for i in range(3):
            cell(journal, str(i), i + 1, {"original": "x" * 50})
        cp = journal.checkpoint()
        page = journal.page_history("cells", expected_checkpoint=cp, max_bytes=80)
        assert len(page.records) == 1 and page.next_key == "0"
        with pytest.raises(JournalFull):
            journal.page_history("cells", expected_checkpoint=cp, max_bytes=2)
        with reopen(path, cp) as writer:
            intent(writer, at=4)
        for action in (journal.snapshot, lambda: journal.page_history("cells", expected_checkpoint=cp)):
            with pytest.raises(OptimisticConflict):
                action()


@pytest.mark.parametrize("target", ["cold", "outer"])
def test_external_rehashed_middle_tamper_is_audited_before_lookup(tmp_path, target):
    path = tmp_path / "compact.sqlite"
    with create(path) as journal:
        for i in range(3):
            cell(journal, str(i), i + 1)
        cp = journal.checkpoint()
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.row_factory = sqlite3.Row
            if target == "cold":
                row = dict(connection.execute("SELECT * FROM cold_records WHERE ordinal=1").fetchone())
                row["value_json"] = _canonical({"status": "MUTATED"})
                row["content_hash"] = _hash(row["value_json"])
                row["record_hash"] = module._cold_hash(row)
                connection.execute(
                    "UPDATE cold_records SET value_json=?,content_hash=?,record_hash=? WHERE ordinal=1",
                    (row["value_json"], row["content_hash"], row["record_hash"]),
                )
            else:
                row = dict(connection.execute("SELECT * FROM events WHERE version=1").fetchone())
                payload = json.loads(row["payload_json"])
                payload["pending"]["operation"]["original"]["status"] = "MUTATED"
                row["payload_json"] = _canonical(payload)
                row["payload_hash"] = _hash(row["payload_json"])
                row["event_hash"] = module._event_hash(row)
                connection.execute(
                    "UPDATE events SET payload_json=?,payload_hash=?,event_hash=? WHERE version=1",
                    (row["payload_json"], row["payload_hash"], row["event_hash"]),
                )
        with pytest.raises(JournalError):
            journal.lookup_history("cells", "0", expected_checkpoint=cp)
    with pytest.raises(JournalError):
        reopen(path, cp)


def test_own_hot_path_no_count_history_or_full_audit(tmp_path):
    with create(tmp_path / "compact.sqlite") as journal:
        for i in range(5):
            cell(journal, str(i), i + 1)
        statements = []
        journal._connection.set_trace_callback(statements.append)
        cell(journal, "new", 6)
        journal.checkpoint()
        journal._connection.set_trace_callback(None)
        assert not any(
            "COUNT(" in statement.upper() or "INTEGRITY_CHECK" in statement.upper()
            for statement in statements
        )
        assert not any(
            "FROM EVENTS ORDER BY VERSION" in statement.upper() and "LIMIT" not in statement.upper()
            for statement in statements
        )
        assert not any("FROM COLD_RECORDS WHERE ORDINAL>" in statement.upper() for statement in statements)


def test_benign_external_commit_audits_once_not_rebases(tmp_path, monkeypatch):
    path = tmp_path / "compact.sqlite"
    with create(path) as journal:
        cell(journal, "id")
        held = journal.checkpoint()
        audits, original = [], journal._audit

        def counted():
            audits.append(True)
            return original()

        monkeypatch.setattr(journal, "_audit", counted)
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("UPDATE head SET last_clock_ms=last_clock_ms+1 WHERE singleton=1")
            connection.execute("UPDATE head SET last_clock_ms=last_clock_ms-1 WHERE singleton=1")
        assert journal.checkpoint() == held
        assert journal.checkpoint() == held
        assert len(audits) == 1


@pytest.mark.parametrize("bound", ["max_cold_rows", "max_record_bytes", "max_event_rows", "max_hot_bytes"])
def test_capacity_fail_closed_no_eviction(tmp_path, bound):
    limits = replace(
        LIMITS,
        **{
            bound: {"max_cold_rows": 1, "max_record_bytes": 2, "max_event_rows": 1, "max_hot_bytes": 5000}[
                bound
            ]
        },
    )
    if bound == "max_hot_bytes":
        limits = replace(limits, max_hot_bytes=1)
        with pytest.raises(JournalFull):
            create(tmp_path / "compact.sqlite", limits)
        return
    with create(tmp_path / "compact.sqlite", limits) as journal:
        if bound == "max_cold_rows":
            cell(journal, "first")
        request, _, cp = intent(journal, at=2)
        with pytest.raises(JournalFull):
            commit(journal, request, cp, (module.ColdHistoryRecordV3("cells", "next", {"original": True}),))
        assert journal.checkpoint() == cp
        assert journal.lookup_history("cells", "next", expected_checkpoint=cp) is None


def test_unknown_cost_and_terminal_report_not_zero(tmp_path):
    with create(tmp_path / "compact.sqlite") as journal:
        request, _, cp = intent(journal, "ATTEMPT")
        unknown = module.ColdHistoryRecordV3("costs", "paid-unknown", {"status": "UNKNOWN", "amount": None})
        commit(journal, request, cp, (unknown,))
        request, _, cp = intent(journal, "FINISH", 2)
        report = {"status": "UNKNOWN", "paid_total": None, "economic_winner": None}
        commit(journal, request, cp, report=report)
        assert journal.snapshot().state["report"] == report
        assert (
            journal.lookup_history("costs", unknown.key, expected_checkpoint=journal.checkpoint()) == unknown
        )
        with pytest.raises(JournalError):
            intent(journal, at=3)


def test_wrong_profile_and_nonempty_genesis_refused(tmp_path):
    path = tmp_path / "old.sqlite"
    with SimDeltaJournalV3.create(
        path, identity=IDENTITY, initial_state=genesis(), initial_clock_ms=0
    ) as old:
        cp = old.checkpoint()
    original = path.read_bytes()
    with pytest.raises(JournalError):
        reopen(path, cp)
    assert path.read_bytes() == original
    state = genesis()
    state["cells"]["old"] = {"status": "UNKNOWN"}
    with pytest.raises(JournalError):
        module.CompactFourArmDriverJournalV3.create(
            tmp_path / "new.sqlite", identity=IDENTITY, initial_state=state, limits=LIMITS
        )


def test_unrequested_cold_stage_and_nested_operation_refused(tmp_path):
    with create(tmp_path / "compact.sqlite") as journal:
        request, _, cp = intent(journal, "SOURCE")
        payload = {
            "operation": request["operation"],
            "pending_sha256": digest(request),
            "account_checkpoints": request["before"],
            "cold_records": [],
            "report": None,
        }

        def fold(state, cold):
            cold.append(module.ColdHistoryRecordV3("slots", "invented", {"value": "not licensed"}))
            with pytest.raises(JournalError):
                journal.snapshot()
            state.update(pending=None, cursor=1)
            return {}

        with pytest.raises(JournalError, match="absent"):
            journal.transition(
                event_id="operation:0:commit", payload=payload, at_ms=1, expected_checkpoint=cp, fold=fold
            )
        assert journal.checkpoint() == cp


def test_semantic_differential_to_full_delta_history(tmp_path):
    with (
        create(tmp_path / "compact.sqlite") as compact,
        SimDeltaJournalV3.create(
            tmp_path / "full.sqlite", identity=IDENTITY, initial_state=genesis(), initial_clock_ms=0
        ) as full,
    ):
        for i in range(6):
            request, _, cp = intent(compact, at=i + 1)
            before = full.snapshot()
            state = before.state
            state.update(pending=request)
            full.append(
                event_id=f"operation:{i}:intent",
                payload={"pending": request},
                at_ms=i + 1,
                expected_version=before.version,
                expected_state_hash=before.state_hash,
                expected_head_sha256=before.head_hash,
                state=state,
                outcome={"status": "INTENT"},
            )
            record = module.ColdHistoryRecordV3("cells", str(i), {"status": "UNKNOWN", "i": i})
            commit(compact, request, cp, (record,))

            before = full.snapshot()
            state = before.state
            state["cells"][record.key] = record.value
            state.update(pending=None, cursor=state["cursor"] + 1)
            full.append(
                event_id=f"operation:{i}:commit",
                payload={"original": asdict(record)},
                at_ms=i + 1,
                expected_version=before.version,
                expected_state_hash=before.state_hash,
                expected_head_sha256=before.head_hash,
                state=state,
                outcome={"status": "COMMITTED"},
            )
        hot, historical = compact.snapshot().state, full.snapshot().state
        assert {key: value for key, value in hot.items() if key not in {"profile", "history_refs"}} == {
            key: value for key, value in historical.items() if key not in module.COLLECTIONS
        }
        for key, value in historical["cells"].items():
            assert (
                compact.lookup_history("cells", key, expected_checkpoint=compact.checkpoint()).value == value
            )
        assert compact.snapshot().state_hash != full.snapshot().state_hash


@pytest.mark.parametrize("committed", [False, True])
def test_process_exit_boundary_exact_pending_or_committed(tmp_path, committed):
    path = tmp_path / "crash.sqlite"
    with create(path) as journal:
        request, _, cp = intent(journal)
        records = (module.ColdHistoryRecordV3("cells", "original", {"status": "UNKNOWN", "amount": None}),)
        plan = recovery_plan(journal, request, cp, records)
    code = """
import json, os, sys
from dataclasses import asdict
from adaptive_replay.compact_four_arm_driver_journal_v3 import (
    CompactFourArmDriverJournalV3, CompactDriverLimitsV3, ColdHistoryRecordV3)
from adaptive_replay.sim_delta_journal_v3 import DeltaCheckpointV3
from adaptive_replay.sim_state_journal import JournalIdentity
from adaptive_replay.historical_context import digest
path, document = sys.argv[1], json.loads(sys.argv[2])
j = CompactFourArmDriverJournalV3.open(path,
    identity=JournalIdentity(**document['identity']), limits=CompactDriverLimitsV3(**document['limits']),
    expected_checkpoint=DeltaCheckpointV3(**document['checkpoint']))
if not document['committed']:
    j._before_commit = lambda: os._exit(61)
p = document['pending']
j.commit_operation(operation=p['operation'], pending_sha256=digest(p), account_checkpoints=p['before'],
    cold_records=(ColdHistoryRecordV3('cells', 'original', {'status':'UNKNOWN','amount':None}),),
    at_ms=1, expected_checkpoint=DeltaCheckpointV3(**document['checkpoint']))
os._exit(62)
"""
    document = {
        "identity": asdict(IDENTITY),
        "limits": asdict(LIMITS),
        "checkpoint": asdict(cp),
        "pending": request,
        "committed": committed,
    }
    result = subprocess.run(
        [sys.executable, "-I", "-W", "error", "-c", code, str(path), json.dumps(document)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == (62 if committed else 61), result.stderr
    if committed:
        # A newer committed head is NOT adopted using the old caller anchor.
        with pytest.raises(OptimisticConflict):
            reopen(path, cp)
        with recover(path, plan) as journal:
            assert journal.snapshot().state == plan["expected_hot_state"]
            assert (
                journal.lookup_history("cells", "original", expected_checkpoint=journal.checkpoint())
                == records[0]
            )
        with pytest.raises(EventConflict):
            recover(path, plan, expected_outcome={"status": "UNKNOWN"})
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute("SELECT version FROM head").fetchone() == (2,)
            original = connection.execute("SELECT value_json FROM cold_records").fetchone()[0]
            assert json.loads(original) == {"status": "UNKNOWN", "amount": None}
    else:
        with pytest.raises(OptimisticConflict):
            recover(path, plan)
        with reopen(path, cp) as journal:
            assert journal.snapshot().state["pending"] == request
            assert journal.lookup_history("cells", "original", expected_checkpoint=cp) is None


def test_checkpoint_closed_type_owner_and_read_prefix(tmp_path):
    path = tmp_path / "compact.sqlite"
    with create(path) as journal:
        before = journal.checkpoint()
        with pytest.raises(JournalError):
            journal.page_history("cells", expected_checkpoint=asdict(before))
        cell(journal, "new")
        with pytest.raises(OptimisticConflict):
            journal.page_history("cells", expected_checkpoint=before)
        request, _, cp = intent(journal, at=2)
        foreign = dict(request["before"])
        foreign[ARMS[0]] = dict(foreign[ARMS[0]], owner_id="foreign")
        with pytest.raises(JournalError):
            commit(journal, request, cp, (module.ColdHistoryRecordV3("cells", "next", {}),), accounts=foreign)
        assert journal.checkpoint() == cp


@pytest.mark.parametrize("kind,collection", [("ROUTE", "routes"), ("ATTEMPT", "costs"), ("EXPENSE", "costs")])
def test_all_indexed_cold_collections_exact_original_and_shadow_slot(tmp_path, kind, collection):
    with create(tmp_path / "compact.sqlite") as journal:
        request, _, cp = intent(journal, kind)
        originals = (
            module.ColdHistoryRecordV3(collection, "receipt", {"status": "UNKNOWN", "amount": None}),
            module.ColdHistoryRecordV3("slots", "shadow:1", {"source": "original", "risk": "unchanged"}),
        )
        commit(journal, request, cp, originals)
        for record in originals:
            assert (
                journal.lookup_history(
                    record.collection, record.key, expected_checkpoint=journal.checkpoint()
                )
                == record
            )
        assert journal.audit() == journal.snapshot()


def test_original_request_count_bound_includes_duplicate_rows(tmp_path):
    with create(tmp_path / "compact.sqlite", replace(LIMITS, max_records_per_commit=1)) as journal:
        request, _, cp = intent(journal)
        record = module.ColdHistoryRecordV3("cells", "same", {"status": "UNKNOWN"})
        with pytest.raises(JournalFull, match="roster"):
            commit(journal, request, cp, (record, record))
        assert journal.checkpoint() == cp
        assert journal.lookup_history("cells", "same", expected_checkpoint=cp) is None


@pytest.mark.parametrize("changed", ["id", "payload", "clock", "outcome", "hot", "cold", "before", "two"])
def test_known_commit_recovery_refuses_any_unknown_expectation(tmp_path, changed):
    path = tmp_path / "compact.sqlite"
    with create(path) as journal:
        cell(journal, "prior")
        request, _, cp = intent(journal, at=2)
        records = (module.ColdHistoryRecordV3("cells", "new", {"status": "UNKNOWN", "amount": None}),)
        plan = recovery_plan(journal, request, cp, records)
        commit(journal, request, cp, records)
        if changed == "two":
            intent(journal, at=3)
    overrides = {}
    if changed == "id":
        overrides["expected_event_id"] = "operation:999:commit"
    elif changed == "payload":
        overrides["expected_payload"] = dict(plan["expected_payload"], pending_sha256="0" * 64)
    elif changed == "clock":
        overrides["expected_at_ms"] = 3
    elif changed == "outcome":
        overrides["expected_outcome"] = {"status": "COMMITTED", "operation_cursor": 999}
    elif changed == "hot":
        overrides["expected_hot_state"] = dict(plan["expected_hot_state"], cursor=999)
    elif changed == "cold":
        overrides["expected_cold_records"] = (replace(records[0], value={"amount": "0"}),)
    elif changed == "before":
        overrides["expected_before"] = replace(cp, state_hash="0" * 64)
    original = path.read_bytes()
    with pytest.raises(JournalError):
        recover(path, plan, **overrides)
    assert path.read_bytes() == original


def test_known_commit_recovery_old_and_staged_exact_duplicates(tmp_path):
    path = tmp_path / "compact.sqlite"
    with create(path) as journal:
        prior = cell(journal, "old")
        request, _, cp = intent(journal, at=2)
        records = (prior, module.ColdHistoryRecordV3("slots", "new", {"original": "same"}))
        records += (records[1],)
        plan = recovery_plan(journal, request, cp, records)
        commit(journal, request, cp, records)
        expected = journal.checkpoint()
    with recover(path, plan) as journal:
        assert journal.checkpoint() == expected
        assert journal.snapshot().state["history_refs"]["cells"]["count"] == 1
        assert journal.snapshot().state["history_refs"]["slots"]["count"] == 1


def test_known_commit_recovery_rejects_tampered_cold_and_foreign_profile(tmp_path):
    path = tmp_path / "compact.sqlite"
    with create(path) as journal:
        request, _, cp = intent(journal)
        records = (module.ColdHistoryRecordV3("cells", "id", {"status": "UNKNOWN"}),)
        plan = recovery_plan(journal, request, cp, records)
        commit(journal, request, cp, records)
    with pytest.raises(JournalError):
        module.CompactFourArmDriverJournalV3.open_after_known_commit(
            path, identity=replace(IDENTITY, campaign_id="foreign"), limits=LIMITS, **plan
        )
    raw(path, "UPDATE cold_records SET value_json=? WHERE ordinal=1", (_canonical({"status": "MUTATED"}),))
    with pytest.raises(JournalError):
        recover(path, plan)


def test_known_commit_recovery_refuses_extra_self_hashed_cold_original(tmp_path):
    path = tmp_path / "compact.sqlite"
    with create(path) as journal:
        request, _, cp = intent(journal)
        records = (module.ColdHistoryRecordV3("cells", "id", {"status": "UNKNOWN"}),)
        plan = recovery_plan(journal, request, cp, records)
        commit(journal, request, cp, records)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.row_factory = sqlite3.Row
        row = dict(connection.execute("SELECT * FROM cold_records WHERE ordinal=1").fetchone())
        row.update(
            ordinal=2,
            collection_ordinal=2,
            key="unknown-extra",
            within_outer=2,
            previous_hash=row["record_hash"],
        )
        row["record_hash"] = module._cold_hash(row)
        columns = tuple(row)
        connection.execute(
            f"INSERT INTO cold_records({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
            tuple(row.values()),
        )
    with pytest.raises(JournalError):
        recover(path, plan)
