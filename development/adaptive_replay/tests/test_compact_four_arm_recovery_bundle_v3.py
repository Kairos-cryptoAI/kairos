"""Bounded real persistence/financial-prefix checks, never full historical results."""

import json
import os
import pickle
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import asdict, fields, replace
from pathlib import Path

import pytest

from adaptive_replay import compact_four_arm_recovery_bundle_v3 as module
from adaptive_replay import four_arm_checkpoint_wal_v3 as root_wal
from adaptive_replay import segmented_four_arm_wal_v3 as segments
from adaptive_replay.compact_commit_plan_store_v3 import (
    CompactCommitPlanStoreIdentityV3,
    CompactCommitPlanStoreLimitsV3,
    CompactCommitPlanStoreV3,
)
from adaptive_replay.compact_four_arm_driver_journal_v3 import CompactFourArmDriverJournalV3
from adaptive_replay.continuous_four_arm_v3 import (
    ARMS,
    COMPACT_FINANCIAL_PROFILE,
    FourArmCheckpointV3,
    FourArmDriverV3,
    FourArmInputsV3,
    ProducerInputV3,
    compact_commit_plan_document,
    compact_commit_plan_from_document,
    preflight_four_arm_v3,
)
from adaptive_replay.continuous_sim_financial_v3_horizon import ContinuousSimFinancialV3Horizon
from adaptive_replay.continuous_sim_v3_horizon import HorizonCandleOriginalsV3
from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_journal_v3 import HypothesisJournalV3, JournalCheckpointV3
from adaptive_replay.sim_account_core_codec_v3 import decode_account_core
from adaptive_replay.sim_delta_journal_v3 import DeltaCheckpointV3
from adaptive_replay.sim_financial_journal_v3 import FinancialCheckpointV3
from adaptive_replay.sim_state_journal import (
    EventConflict,
    JournalError,
    JournalFull,
    OptimisticConflict,
    _canonical,
    _hash,
)

from . import test_compact_commit_plan_store_v3 as plan_fixture
from . import test_continuous_four_arm_v3 as driver_fixture
from ._isolated_fixture import FIXTURE_BOOTSTRAP

LIMITS = module.RecoveryBundleLimitsV3(512, 1024 * 1024, 32 * 1024 * 1024)
PLAN_LIMITS = CompactCommitPlanStoreLimitsV3(128, 512 * 1024, 16 * 1024 * 1024)
ROOT_LIMITS = root_wal.CheckpointWalLimitsV3(256 * 1024, 512, 64 * 1024 * 1024)
SEGMENT_LIMITS = segments.SegmentedWalLimitsV3(
    256 * 1024, 8, 4 * 1024 * 1024, 32, 512, 128 * 1024 * 1024, 1024 * 1024
)
inputs = driver_fixture.inputs


def _fsync(path, value, *, create_only=False):
    with path.open("xb" if create_only else "wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _raw(path, sql, parameters=()):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(sql, parameters)


def _plan_identity(checkpoint, campaign):
    return CompactCommitPlanStoreIdentityV3(
        campaign,
        checkpoint.identity_sha256,
        checkpoint.driver_checkpoint.identity_sha256,
        tuple((arm, cp.identity_sha256) for arm, cp in checkpoint.arm_checkpoints),
    )


def _small(tmp_path, profile=root_wal.SCHEMA, limits=LIMITS):
    """Actual compact/plan/WAL stores; synthetic no-effect checkpoint carriers ONLY."""
    identity, originals = plan_fixture._plans(tmp_path)
    with CompactFourArmDriverJournalV3.create(
        tmp_path / "seed.sqlite",
        identity=plan_fixture.DRIVER_IDENTITY,
        initial_state=plan_fixture._genesis(),
        limits=plan_fixture.DRIVER_LIMITS,
    ) as seed:
        checkpoint = FourArmCheckpointV3(
            identity.driver_identity_sha256,
            seed.checkpoint(),
            tuple(
                (arm, FinancialCheckpointV3(**doc))
                for arm, doc in seed.snapshot().state["account_checkpoints"].items()
            ),
            (("fixture", JournalCheckpointV3("f" * 64, 0, "f" * 64)),),
            0,
            None,
        )
    plan_store = CompactCommitPlanStoreV3.create(
        tmp_path / "plans.sqlite", identity=identity, limits=PLAN_LIMITS
    )
    wal = (
        root_wal.FourArmCheckpointWalV3.create(tmp_path / "checkpoints.wal", checkpoint, limits=ROOT_LIMITS)
        if profile == root_wal.SCHEMA
        else segments.SegmentedFourArmCheckpointWalV3.create(
            tmp_path / "segments", checkpoint, limits=SEGMENT_LIMITS
        )
    )
    bundle_identity = module.RecoveryBundleIdentityV3(
        identity, plan_store.anchor().identity_sha256, profile, _canonical(asdict(wal.snapshot().limits))
    )
    store = module.RecoveryBundleStoreV3.create(
        tmp_path / "bundle.sqlite",
        identity=bundle_identity,
        limits=limits,
        initial_checkpoint=checkpoint,
        initial_wal_anchor=wal.snapshot().anchor,
        initial_plan_anchor=plan_store.anchor(),
    )
    return store, wal, plan_store, originals, tmp_path / "actual-driver.sqlite"


def _snapshot(store):
    return store.snapshot(expected_anchor=store._retained)


def _checkpoint_publication(store, wal, checkpoint, receipt=None):
    snapshot = _snapshot(store)
    inspection = wal.snapshot()
    segment_sha = (
        wal._segment_digest.hexdigest() if type(wal) is segments.SegmentedFourArmCheckpointWalV3 else None
    )
    after = module._next_wal(
        store.identity.checkpoint_wal_schema,
        inspection.limits,
        snapshot.wal_anchor,
        snapshot.checkpoint,
        checkpoint,
        segment_sha,
    )
    publication = module.RecoveryPublicationV3(
        _canonical(
            {
                "kind": "CHECKPOINT",
                "checkpoint": root_wal.checkpoint_document(checkpoint),
                "wal_before": asdict(snapshot.wal_anchor),
                "wal_after": asdict(after),
                "wal_segment_sha256": segment_sha,
                "plan_before": asdict(snapshot.plan_anchor),
                "plan_after": asdict(snapshot.plan_anchor),
                "plan": None,
                "plan_receipt": None,
                "driver_receipt": receipt,
            }
        )
    )
    assert wal(checkpoint) is True and wal.snapshot().anchor == after
    return publication


def _publish(store, original):
    return store.publish(original, expected_anchor=store._retained)


def _cycle(store, wal, plan_store, plan, driver_path):
    held = _snapshot(store)
    pending = {
        "operation": plan.expected_payload["operation"],
        "before": {arm: asdict(cp) for arm, cp in held.checkpoint.arm_checkpoints},
        "effects": dict.fromkeys(ARMS),
    }
    prepared = replace(
        held.checkpoint,
        pending_operation=pending,
        pending_operation_sha256=digest(pending),
        checkpoint_phase="PREPARED_INTENT",
    )
    original_prepared = _checkpoint_publication(store, wal, prepared)
    _publish(store, original_prepared)
    intent = replace(prepared, driver_checkpoint=plan.expected_before, checkpoint_phase="INTENT_COMMITTED")
    original_intent = _checkpoint_publication(store, wal, intent)
    _publish(store, original_intent)
    state = _snapshot(store)
    predicted = module._plan_receipt(state.plan_anchor, plan)
    actual = plan_store.persist(plan, expected_anchor=state.plan_anchor)
    assert actual == predicted
    original_plan = module.RecoveryPublicationV3(
        _canonical(
            {
                "kind": "PLAN",
                "checkpoint": root_wal.checkpoint_document(intent),
                "wal_before": asdict(state.wal_anchor),
                "wal_after": asdict(state.wal_anchor),
                "wal_segment_sha256": None,
                "plan_before": asdict(state.plan_anchor),
                "plan_after": asdict(actual.anchor),
                "plan": compact_commit_plan_document(plan),
                "plan_receipt": asdict(actual),
                "driver_receipt": None,
            }
        )
    )
    _publish(store, original_plan)
    with closing(sqlite3.connect(driver_path)) as connection:
        row = connection.execute(
            "SELECT version,state_hash,event_hash,clock_ms FROM events WHERE version=?",
            (plan.expected_before.version + 1,),
        ).fetchone()
    completed = replace(
        intent,
        driver_checkpoint=DeltaCheckpointV3(plan.expected_before.identity_sha256, *row),
        operation_cursor=plan.expected_hot_state["cursor"],
        pending_operation=None,
        pending_operation_sha256=None,
    )
    receipt = {
        "checkpoint": asdict(completed.driver_checkpoint),
        "event_id": plan.expected_event_id,
        "payload": plan.expected_payload,
        "outcome": plan.expected_outcome,
        "hot_state": plan.expected_hot_state,
    }
    original_completed = _checkpoint_publication(store, wal, completed, receipt)
    _publish(store, original_completed)
    return original_prepared, original_intent, original_plan, original_completed


@pytest.mark.parametrize("profile", [root_wal.SCHEMA, segments.SCHEMA])
def test_bundle_every_original_receipt_full_audit_exact_reopen_and_rotation(tmp_path, profile):
    store, wal, plan_store, originals, driver_path = _small(tmp_path, profile)
    try:
        publications = []
        for plan in originals:
            publications.extend(_cycle(store, wal, plan_store, plan, driver_path))
        held = _snapshot(store)
        assert held.anchor.count == 12 and held.plan_anchor.count == 3 and held.active_plan is None
        assert store.audit(expected_anchor=held.anchor) == held
        if profile == segments.SCHEMA:
            assert held.wal_anchor.segment_number == 2
        for original in publications:
            key = module._publication_id(original.document())
            assert store.lookup(key, expected_anchor=held.anchor) == original
            assert _publish(store, original).replayed is True
        with closing(sqlite3.connect(store.path)) as connection:
            retained = connection.execute(
                "SELECT original_json FROM publications ORDER BY ordinal"
            ).fetchall()
        assert [row[0] for row in retained] == [value.original_json for value in publications]
        identity = store.identity
    finally:
        store.close()
        wal.close()
        plan_store.close()
    with module.RecoveryBundleStoreV3.open(
        tmp_path / "bundle.sqlite", identity=identity, limits=LIMITS, expected_anchor=held.anchor
    ) as reopened:
        assert reopened.snapshot(expected_anchor=held.anchor) == held


def test_owned_hot_publish_lookup_duplicate_no_count_or_history_replay(tmp_path):
    store, wal, plan_store, originals, driver_path = _small(tmp_path)
    try:
        statements = []
        store._connection.set_trace_callback(statements.append)
        publications = _cycle(store, wal, plan_store, originals[0], driver_path)
        held = _snapshot(store).anchor
        assert (
            store.lookup(module._publication_id(publications[0].document()), expected_anchor=held)
            == publications[0]
        )
        assert _publish(store, publications[0]).replayed
        sql = "\n".join(statements).upper()
        assert "COUNT(" not in sql and "ORDER BY ORDINAL" not in sql and "INTEGRITY_CHECK" not in sql
    finally:
        store.close()
        wal.close()
        plan_store.close()


@pytest.mark.parametrize("fault", ["insert", "projection", "precommit"])
def test_bundle_sql_failures_roll_back_original_and_projection(tmp_path, fault, monkeypatch):
    store, wal, plan_store, originals, _ = _small(tmp_path)
    try:
        before = _snapshot(store)
        plan = originals[0]
        pending = {
            "operation": plan.expected_payload["operation"],
            "before": {arm: asdict(cp) for arm, cp in before.checkpoint.arm_checkpoints},
            "effects": dict.fromkeys(ARMS),
        }
        prepared = replace(
            before.checkpoint,
            pending_operation=pending,
            pending_operation_sha256=digest(pending),
            checkpoint_phase="PREPARED_INTENT",
        )
        original = _checkpoint_publication(store, wal, prepared)
        connection = store._connection
        if fault == "precommit":

            def fail():
                raise OSError("SQL publication failure")

            monkeypatch.setattr(store, "_commit", fail)
        else:
            store._connection = plan_fixture._ConnectionFault(
                connection, "INSERT INTO publications" if fault == "insert" else "UPDATE head"
            )
        with pytest.raises((RuntimeError, OSError)):
            _publish(store, original)
        store._connection = connection
        assert (
            _snapshot(store) == before
            and store.lookup(module._publication_id(original.document()), expected_anchor=before.anchor)
            is None
        )
    finally:
        store.close()
        wal.close()
        plan_store.close()


def test_lost_publication_response_requires_exact_original_and_independent_prefix(tmp_path, monkeypatch):
    store, wal, plan_store, originals, _ = _small(tmp_path)
    before = _snapshot(store)
    pending = {
        "operation": originals[0].expected_payload["operation"],
        "before": {arm: asdict(cp) for arm, cp in before.checkpoint.arm_checkpoints},
        "effects": dict.fromkeys(ARMS),
    }
    prepared = replace(
        before.checkpoint,
        pending_operation=pending,
        pending_operation_sha256=digest(pending),
        checkpoint_phase="PREPARED_INTENT",
    )
    original = _checkpoint_publication(store, wal, prepared)
    identity = store.identity

    def lost():
        store._connection.commit()
        raise RuntimeError("bundle response lost; no ACK")

    monkeypatch.setattr(store, "_commit", lost)
    try:
        with pytest.raises(RuntimeError):
            _publish(store, original)
        with pytest.raises(OptimisticConflict):
            _snapshot(store)
    finally:
        store.close()
        wal.close()
        plan_store.close()
    with pytest.raises(OptimisticConflict):
        module.RecoveryBundleStoreV3.open(
            tmp_path / "bundle.sqlite", identity=identity, limits=LIMITS, expected_anchor=before.anchor
        )
    changed = original.document()
    changed["checkpoint"]["pending_operation"]["operation"]["unknown_original"] = True
    with pytest.raises(EventConflict):
        module.RecoveryBundleStoreV3.open_after_known_publish(
            tmp_path / "bundle.sqlite",
            identity=identity,
            limits=LIMITS,
            expected_before_anchor=before.anchor,
            expected_publication=module.RecoveryPublicationV3(_canonical(changed)),
        )
    with module.RecoveryBundleStoreV3.open_after_known_publish(
        tmp_path / "bundle.sqlite",
        identity=identity,
        limits=LIMITS,
        expected_before_anchor=before.anchor,
        expected_publication=original,
    ) as recovered:
        assert _snapshot(recovered).anchor.count == 1 and _snapshot(recovered).checkpoint == prepared


@pytest.mark.parametrize("profile", [root_wal.SCHEMA, segments.SCHEMA])
def test_known_wal_append_or_rotation_derived_not_adopted_from_latest(tmp_path, profile):
    store, wal, plan_store, originals, driver_path = _small(tmp_path, profile)
    try:
        _cycle(store, wal, plan_store, originals[0], driver_path)
        before = _snapshot(store)
        pending = {
            "operation": originals[1].expected_payload["operation"],
            "before": {arm: asdict(cp) for arm, cp in before.checkpoint.arm_checkpoints},
            "effects": dict.fromkeys(ARMS),
        }
        prepared = replace(
            before.checkpoint,
            pending_operation=pending,
            pending_operation_sha256=digest(pending),
            checkpoint_phase="PREPARED_INTENT",
        )
        original = _checkpoint_publication(store, wal, prepared)
        identity = store.identity
        path = wal._path if profile == root_wal.SCHEMA else wal.directory
    finally:
        store.close()
        wal.close()
        plan_store.close()
    cls = (
        root_wal.FourArmCheckpointWalV3
        if profile == root_wal.SCHEMA
        else segments.SegmentedFourArmCheckpointWalV3
    )
    with pytest.raises(ValueError):
        cls.open(path, expected_anchor=before.wal_anchor)
    with module.open_checkpoint_wal_after_known_publication(
        path,
        identity=identity,
        expected_before_checkpoint=before.checkpoint,
        expected_before_wal_anchor=before.wal_anchor,
        expected_publication=original,
    ) as recovered:
        assert recovered.snapshot().checkpoint == prepared
    if profile == root_wal.SCHEMA:
        with path.open("ab") as stream:
            stream.write(b"torn")
            stream.flush()
            os.fsync(stream.fileno())
    else:
        _fsync(path / "orphan", b"unknown", create_only=True)
    with pytest.raises(ValueError):
        module.open_checkpoint_wal_after_known_publication(
            path,
            identity=identity,
            expected_before_checkpoint=before.checkpoint,
            expected_before_wal_anchor=before.wal_anchor,
            expected_publication=original,
        )


def test_external_middle_rehash_or_unknown_writer_never_gets_indexed_ack(tmp_path):
    store, wal, plan_store, originals, driver_path = _small(tmp_path)
    try:
        publications = _cycle(store, wal, plan_store, originals[0], driver_path)
        held = _snapshot(store).anchor
        row = dict(store._connection.execute("SELECT * FROM publications WHERE ordinal=1").fetchone())
        value = _load_document = json.loads(row["original_json"])
        value["checkpoint"]["producer_checkpoints"][0][1]["head_sha256"] = "1" * 64
        row["original_json"] = _canonical(_load_document)
        row["original_sha256"] = _hash(row["original_json"])
        row["original_bytes"] = len(row["original_json"].encode("utf-8"))
        row["record_hash"] = store._row_hash(row)
        _raw(
            store.path,
            "UPDATE publications SET original_json=?,original_sha256=?,original_bytes=?,record_hash=? "
            "WHERE ordinal=1",
            (row["original_json"], row["original_sha256"], row["original_bytes"], row["record_hash"]),
        )
        with pytest.raises((ValueError, JournalError)):
            store.lookup(module._publication_id(publications[0].document()), expected_anchor=held)
        assert store._retained == held
    finally:
        store.close()
        wal.close()
        plan_store.close()


@pytest.mark.parametrize("count", [0, 2])
def test_known_bundle_publication_refuses_zero_or_multiple_new_originals(tmp_path, count):
    store, wal, plan_store, originals, _ = _small(tmp_path)
    before = _snapshot(store)
    plan = originals[0]
    pending = {
        "operation": plan.expected_payload["operation"],
        "before": {arm: asdict(cp) for arm, cp in before.checkpoint.arm_checkpoints},
        "effects": dict.fromkeys(ARMS),
    }
    prepared = replace(
        before.checkpoint,
        pending_operation=pending,
        pending_operation_sha256=digest(pending),
        checkpoint_phase="PREPARED_INTENT",
    )
    first = _checkpoint_publication(store, wal, prepared)
    try:
        if count:
            _publish(store, first)
            intent = replace(
                prepared, driver_checkpoint=plan.expected_before, checkpoint_phase="INTENT_COMMITTED"
            )
            _publish(store, _checkpoint_publication(store, wal, intent))
        identity = store.identity
    finally:
        store.close()
        wal.close()
        plan_store.close()
    with pytest.raises(OptimisticConflict):
        module.RecoveryBundleStoreV3.open_after_known_publish(
            tmp_path / "bundle.sqlite",
            identity=identity,
            limits=LIMITS,
            expected_before_anchor=before.anchor,
            expected_publication=first,
        )


def test_sealed_bundle_budgets_typed_anchor_and_fail_before_original_pruning(tmp_path):
    store, wal, plan_store, originals, _ = _small(tmp_path, limits=replace(LIMITS, max_bundle_rows=1))
    try:
        before = _snapshot(store)
        pending = {
            "operation": originals[0].expected_payload["operation"],
            "before": {arm: asdict(cp) for arm, cp in before.checkpoint.arm_checkpoints},
            "effects": dict.fromkeys(ARMS),
        }
        prepared = replace(
            before.checkpoint,
            pending_operation=pending,
            pending_operation_sha256=digest(pending),
            checkpoint_phase="PREPARED_INTENT",
        )
        original = _checkpoint_publication(store, wal, prepared)
        with pytest.raises(JournalFull, match="reserve"):
            _publish(store, original)
        assert _snapshot(store) == before
        with pytest.raises(JournalError):
            store.snapshot(expected_anchor=asdict(before.anchor))
        identity = store.identity
    finally:
        store.close()
        wal.close()
        plan_store.close()
    with pytest.raises(OptimisticConflict):
        module.RecoveryBundleStoreV3.open(
            tmp_path / "bundle.sqlite", identity=identity, limits=LIMITS, expected_anchor=before.anchor
        )


@pytest.mark.parametrize("boundary", ["precommit", "postcommit"])
def test_actual_bundle_process_exit_after_wal_before_ack_and_exact_original_recovery(tmp_path, boundary):
    store, wal, plan_store, originals, driver_path = _small(tmp_path)
    try:
        _cycle(store, wal, plan_store, originals[0], driver_path)
        before = _snapshot(store)
        pending = {
            "operation": originals[1].expected_payload["operation"],
            "before": {arm: asdict(cp) for arm, cp in before.checkpoint.arm_checkpoints},
            "effects": dict.fromkeys(ARMS),
        }
        prepared = replace(
            before.checkpoint,
            pending_operation=pending,
            pending_operation_sha256=digest(pending),
            checkpoint_phase="PREPARED_INTENT",
        )
        original = _checkpoint_publication(store, wal, prepared)
        caller = (store.identity, before.anchor, original)
        _fsync(
            tmp_path / "caller.pkl", pickle.dumps(caller, protocol=pickle.HIGHEST_PROTOCOL), create_only=True
        )
    finally:
        store.close()
        wal.close()
        plan_store.close()
    script = """
import os, pickle, sys
from pathlib import Path
from adaptive_replay import compact_four_arm_recovery_bundle_v3 as module
root, boundary = Path(sys.argv[1]), sys.argv[2]
identity, before, original = pickle.loads((root/'caller.pkl').read_bytes())
limits = module.RecoveryBundleLimitsV3(512,1024*1024,32*1024*1024)
store = module.RecoveryBundleStoreV3.open(
    root/'bundle.sqlite',identity=identity,limits=limits,expected_anchor=before)
def crash():
    if boundary == 'postcommit':
        store._connection.commit()
    os._exit(85 if boundary == 'precommit' else 86)
store._commit = crash
store.publish(original,expected_anchor=before)
os._exit(99)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-W", "error", "-c", script, str(tmp_path), boundary],
        capture_output=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == (85 if boundary == "precommit" else 86), result.stderr.decode()
    identity, held, retained = pickle.loads((tmp_path / "caller.pkl").read_bytes())
    assert held == before.anchor and retained == original
    if boundary == "postcommit":
        with pytest.raises(OptimisticConflict):
            module.RecoveryBundleStoreV3.open(
                tmp_path / "bundle.sqlite", identity=identity, limits=LIMITS, expected_anchor=held
            )
        store = module.RecoveryBundleStoreV3.open_after_known_publish(
            tmp_path / "bundle.sqlite",
            identity=identity,
            limits=LIMITS,
            expected_before_anchor=held,
            expected_publication=retained,
        )
    else:
        store = module.RecoveryBundleStoreV3.open(
            tmp_path / "bundle.sqlite", identity=identity, limits=LIMITS, expected_anchor=held
        )
        receipt = store.publish(retained, expected_anchor=held)
        assert receipt is not True
    with store:
        current = _snapshot(store)
        assert current.anchor.count == held.count + 1 and current.checkpoint == prepared
        with pytest.raises(OptimisticConflict):
            store.lookup(module._publication_id(retained.document()), expected_anchor=held)


def _retain_inputs(inputs):
    values = {
        field.name: getattr(inputs, field.name)
        for field in fields(FourArmInputsV3)
        if field.name not in {"candle_originals", "producers"}
    }
    values["candle_records"] = inputs.candle_originals.records
    values["producers"] = tuple(
        (p.producer_id, p.journal.path, p.journal._seal, p.checkpoint) for p in inputs.producers
    )
    return pickle.dumps(values, protocol=pickle.HIGHEST_PROTOCOL)


def _restore_inputs(path):
    values = pickle.loads(path.read_bytes())  # Trusted test fixture only, never an untrusted artifact.
    values["candle_originals"] = HorizonCandleOriginalsV3(values.pop("candle_records"))
    values["producers"] = tuple(
        ProducerInputV3(
            name, HypothesisJournalV3.open(producer_path, seal, minimum_checkpoint=checkpoint), checkpoint
        )
        for name, producer_path, seal, checkpoint in values["producers"]
    )
    return FourArmInputsV3(**values)


def _retain_caller(binder, path):
    _fsync(path, pickle.dumps(binder.snapshot(), protocol=pickle.HIGHEST_PROTOCOL))


@pytest.fixture(scope="module")
def actual_financial_base(tmp_path_factory, inputs):
    """One full sealed fixture roster; execute ONLY the first original zero-cost call."""
    directory = tmp_path_factory.mktemp("actual-bundle-prefix") / "accounts"
    prepared = preflight_four_arm_v3(
        inputs,
        driver_fixture.sealed(inputs),
        account_profile=COMPACT_FINANCIAL_PROFILE,
        compact_storage=driver_fixture.COMPACT_TEST_LIMITS,
    )
    driver = FourArmDriverV3.create(directory, prepared)
    cp = driver.checkpoint()
    plan_store = CompactCommitPlanStoreV3.create(
        directory / "plan-store.sqlite",
        identity=_plan_identity(cp, prepared.seal.experiment_id),
        limits=PLAN_LIMITS,
    )
    wal = root_wal.FourArmCheckpointWalV3.create(directory / "checkpoints.wal", cp, limits=ROOT_LIMITS)
    binder = module.CompactFourArmRecoveryBinderV3.create(
        directory / "bundle.sqlite", driver=driver, checkpoint_wal=wal, plan_store=plan_store, limits=LIMITS
    )
    try:
        _fsync(directory / "retained-inputs.pkl", _retain_inputs(inputs), create_only=True)
        _retain_caller(binder, directory / "caller-bundle.pkl")

        def checkpoint_sink(checkpoint):
            answer = binder.checkpoint_sink(checkpoint)
            if answer is True:
                _retain_caller(binder, directory / "caller-bundle.pkl")
            return answer

        def plan_sink(plan):
            answer = binder.commit_plan_sink(plan)
            if answer is True:
                _retain_caller(binder, directory / "caller-bundle.pkl")
            return answer

        driver.step(maximum_operations=1, checkpoint_sink=checkpoint_sink, commit_plan_sink=plan_sink)
        assert prepared.operations[1]["kind"] == "EXPENSE"
        assert inputs.shared_expenses[prepared.operations[1]["index"]].amount_usd == driver_fixture.D(1)
        assert all(type(account) is ContinuousSimFinancialV3Horizon for account in driver.accounts.values())
        assert binder.snapshot().checkpoint.operation_cursor == 1 and binder.snapshot().plan_anchor.count == 1
        identity = binder.store.identity
        for account in driver.accounts.values():
            assert decode_account_core(account.snapshot().state["account"])[0].cash == inputs.initial_equity
    finally:
        binder.close()
        wal.close()
        plan_store.close()
        driver.close()
    return directory, identity


def _open_actual(directory, identity, publication=None, *, bundle_committed=False, plan_committed=False):
    held = pickle.loads((directory / "caller-bundle.pkl").read_bytes())
    fixture_inputs = _restore_inputs(directory / "retained-inputs.pkl")
    prepared = preflight_four_arm_v3(
        fixture_inputs,
        driver_fixture.sealed(fixture_inputs),
        account_profile=COMPACT_FINANCIAL_PROFILE,
        compact_storage=driver_fixture.COMPACT_TEST_LIMITS,
    )
    store, wal, plan_store, driver = None, None, None, None
    try:
        if bundle_committed:
            store = module.RecoveryBundleStoreV3.open_after_known_publish(
                directory / "bundle.sqlite",
                identity=identity,
                limits=LIMITS,
                expected_before_anchor=held.anchor,
                expected_publication=publication,
            )
            state = _snapshot(store)
        else:
            store = module.RecoveryBundleStoreV3.open(
                directory / "bundle.sqlite", identity=identity, limits=LIMITS, expected_anchor=held.anchor
            )
            state = held
        record = None if publication is None else publication.document()
        checkpoint = (
            state.checkpoint if record is None else root_wal.checkpoint_from_document(record["checkpoint"])
        )
        if record is not None and record["kind"] == "CHECKPOINT":
            wal = module.open_checkpoint_wal_after_known_publication(
                directory / "checkpoints.wal",
                identity=identity,
                expected_before_checkpoint=held.checkpoint,
                expected_before_wal_anchor=held.wal_anchor,
                expected_publication=publication,
            )
        else:
            wal = root_wal.FourArmCheckpointWalV3.open(
                directory / "checkpoints.wal", expected_anchor=state.wal_anchor
            )
        plan = (
            state.active_plan
            if record is None
            else (None if record["plan"] is None else compact_commit_plan_from_document(record["plan"]))
        )
        if record is not None and record["kind"] == "PLAN" and plan_committed and not bundle_committed:
            plan_store = CompactCommitPlanStoreV3.open_after_known_persist(
                directory / "plan-store.sqlite",
                identity=identity.financial,
                limits=PLAN_LIMITS,
                expected_before_anchor=held.plan_anchor,
                expected_plan=plan,
            )
        else:
            plan_store = CompactCommitPlanStoreV3.open(
                directory / "plan-store.sqlite",
                identity=identity.financial,
                limits=PLAN_LIMITS,
                expected_anchor=state.plan_anchor,
            )
            if record is not None and record["kind"] == "PLAN" and not plan_committed:
                receipt = plan_store.persist(plan, expected_anchor=held.plan_anchor)
                assert asdict(receipt) == record["plan_receipt"]
        driver = FourArmDriverV3.open(directory, prepared, checkpoint, expected_commit_plan=plan)
        binder = module.CompactFourArmRecoveryBinderV3(
            store,
            driver=driver,
            checkpoint_wal=wal,
            plan_store=plan_store,
            expected_anchor=store._retained,
            expected_publication=None if bundle_committed else publication,
        )
        if publication is not None and not bundle_committed:
            receipt = binder.resume_publication(expected_publication=publication)
            assert receipt is not True
            _retain_caller(binder, directory / "caller-bundle.pkl")
        return binder, driver, wal, plan_store
    except BaseException:
        if driver is not None:
            driver.close()
        if wal is not None:
            wal.close()
        if plan_store is not None:
            plan_store.close()
        if store is not None:
            store.close()
        raise


def _close_actual(binder, driver, wal, plan_store):
    binder.close()
    driver.close()
    wal.close()
    plan_store.close()


def test_actual_four_financial_accounts_positive_cost_real_bundle_ack(tmp_path, actual_financial_base):
    base, identity = actual_financial_base
    directory = tmp_path / "actual"
    shutil.copytree(base, directory)  # Closed offline fixtures; every original database/receipt is copied.
    binder, driver, wal, plan_store = _open_actual(directory, identity)
    try:
        statements = []
        binder.store._connection.set_trace_callback(statements.append)
        driver.step(checkpoint_sink=binder.checkpoint_sink, commit_plan_sink=binder.commit_plan_sink)
        held = binder.snapshot()
        assert held.checkpoint == driver.checkpoint() and held.checkpoint.operation_cursor == 2
        assert held.plan_anchor.count == 2 and held.active_plan is None
        assert wal.snapshot().checkpoint == held.checkpoint
        for account in driver.accounts.values():
            assert type(account) is ContinuousSimFinancialV3Horizon
            core = decode_account_core(account.snapshot().state["account"])[0]
            assert core.cash == driver_fixture.D(999)
            paid = [
                event
                for event in account.journal.native_events()
                if event.payload[0] == "SERVICE" and event.payload[1] == driver_fixture.D(1)
            ]
            assert len(paid) == 1 and paid[0].event_id == "feed"
        plan_publication = binder.store.lookup("PLAN:operation:1:commit", expected_anchor=held.anchor)
        assert plan_publication.document()["plan_receipt"]["anchor"] == asdict(held.plan_anchor)
        assert (
            plan_publication.document()["checkpoint"]["pending_operation"]["operation"]["kind"] == "EXPENSE"
        )
        sql = "\n".join(statements).upper()
        assert "COUNT(" not in sql and "ORDER BY ORDINAL" not in sql and "INTEGRITY_CHECK" not in sql
        assert binder.store.audit(expected_anchor=held.anchor) == held
    finally:
        _close_actual(binder, driver, wal, plan_store)


@pytest.mark.parametrize("unknown_answer", [False, None])
def test_actual_wal_non_ack_prevents_account_effects(
    tmp_path, actual_financial_base, monkeypatch, unknown_answer
):
    base, identity = actual_financial_base
    directory = tmp_path / "wal-non-ack"
    shutil.copytree(base, directory)
    binder, driver, wal, plan_store = _open_actual(directory, identity)
    try:
        before = binder.snapshot()
        driver_before = driver.journal.checkpoint()
        monkeypatch.setattr(type(wal), "__call__", lambda self, checkpoint: unknown_answer)
        with pytest.raises(JournalError, match="unknown checkpoint WAL response"):
            driver.step(checkpoint_sink=binder.checkpoint_sink, commit_plan_sink=binder.commit_plan_sink)
        assert binder.snapshot() == before
        assert driver.journal.checkpoint() == driver_before
        assert plan_store.anchor() == before.plan_anchor
        for account in driver.accounts.values():
            assert decode_account_core(account.snapshot().state["account"])[0].cash == driver_fixture.D(1000)
        with pytest.raises(JournalError, match="unknown binder response"):
            binder.checkpoint_sink(driver.checkpoint())
    finally:
        _close_actual(binder, driver, wal, plan_store)


@pytest.mark.parametrize("unknown_answer", [False, None])
def test_actual_unknown_plan_receipt_cannot_license_driver_commit(
    tmp_path, actual_financial_base, monkeypatch, unknown_answer
):
    base, identity = actual_financial_base
    directory = tmp_path / "plan-non-ack"
    shutil.copytree(base, directory)
    binder, driver, wal, plan_store = _open_actual(directory, identity)
    try:
        plan_before = plan_store.anchor()
        driver_before = driver.journal.checkpoint()
        monkeypatch.setattr(plan_store, "persist", lambda *args, **kwargs: unknown_answer)
        with pytest.raises(JournalError, match="unknown/mismatched plan-store receipt"):
            driver.step(checkpoint_sink=binder.checkpoint_sink, commit_plan_sink=binder.commit_plan_sink)
        held = binder.snapshot()
        assert held.checkpoint.checkpoint_phase == "INTENT_COMMITTED" and held.active_plan is None
        assert held.plan_anchor == plan_before and plan_store.anchor() == plan_before
        assert driver.journal.checkpoint().version == driver_before.version + 1
        # Effects were licensed by the original durable INTENT, not by the failed plan ACK.
        for account in driver.accounts.values():
            assert decode_account_core(account.snapshot().state["account"])[0].cash == driver_fixture.D(999)
        assert binder.last_attempt.document()["kind"] == "PLAN"
        with pytest.raises(JournalError, match="unknown binder response"):
            binder.commit_plan_sink(compact_commit_plan_from_document(binder.last_attempt.document()["plan"]))
    finally:
        _close_actual(binder, driver, wal, plan_store)


def test_actual_unbundled_plan_head_is_not_adopted(tmp_path, actual_financial_base):
    base, identity = actual_financial_base
    directory = tmp_path / "unknown-plan-head"
    shutil.copytree(base, directory)
    binder, driver, wal, plan_store = _open_actual(directory, identity)
    try:
        before = binder.snapshot()
        driver_before = driver.journal.checkpoint()

        def outside_owned_bundle(plan):
            receipt = plan_store.persist(plan, expected_anchor=before.plan_anchor)
            assert receipt.anchor.count == before.plan_anchor.count + 1
            return binder.commit_plan_sink(plan)

        with pytest.raises(OptimisticConflict, match="advanced outside exact retained bundle"):
            driver.step(checkpoint_sink=binder.checkpoint_sink, commit_plan_sink=outside_owned_bundle)
        held = binder.snapshot()
        assert held.plan_anchor == before.plan_anchor and held.active_plan is None
        assert plan_store.anchor().count == before.plan_anchor.count + 1
        assert driver.journal.checkpoint().version == driver_before.version + 1
        assert held.checkpoint.checkpoint_phase == "INTENT_COMMITTED"
    finally:
        _close_actual(binder, driver, wal, plan_store)


@pytest.mark.parametrize(
    "boundary", ["pre_plan_commit", "post_plan_commit", "post_bundle_commit", "post_driver_commit"]
)
def test_actual_subprocess_four_financial_accounts_exact_recovery_no_double_cost(
    tmp_path, actual_financial_base, boundary
):
    base, identity = actual_financial_base
    directory = tmp_path / "crash"
    shutil.copytree(base, directory)
    script = (
        FIXTURE_BOOTSTRAP
        + """
import os, pickle, sys
from pathlib import Path
root, boundary, helper_path = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
helpers = vars(load_isolated_fixture_module(helper_path))
identity = pickle.loads((root/'caller-identity.pkl').read_bytes())
binder, driver, wal, plan_store = helpers['_open_actual'](root, identity)
def retain_attempt():
    original = binder.last_attempt
    assert original is not None
    helpers['_fsync'](root/'caller-attempt.json', original.original_json.encode('utf-8'), create_only=True)
if boundary in {'pre_plan_commit','post_plan_commit'}:
    def plan_crash():
        retain_attempt()
        if boundary == 'post_plan_commit':
            plan_store._connection.commit()
        os._exit(81 if boundary == 'pre_plan_commit' else 82)
    plan_store._commit = plan_crash
elif boundary == 'post_bundle_commit':
    original_commit = binder.store._commit
    def bundle_crash():
        original_commit()
        if binder.last_attempt.document()['kind'] == 'PLAN':
            retain_attempt()
            os._exit(83)
    binder.store._commit = bundle_crash
else:
    original_driver_commit = driver._commit_known_plan
    def driver_crash(plan):
        original_driver_commit(plan)
        os._exit(84)
    driver._commit_known_plan = driver_crash
def checkpoint_sink(checkpoint):
    answer = binder.checkpoint_sink(checkpoint)
    if answer is True:
        helpers['_retain_caller'](binder, root/'caller-bundle.pkl')
    return answer
def plan_sink(plan):
    answer = binder.commit_plan_sink(plan)
    if answer is True:
        helpers['_retain_caller'](binder, root/'caller-bundle.pkl')
    return answer
driver.step(checkpoint_sink=checkpoint_sink, commit_plan_sink=plan_sink)
os._exit(99)
"""
    )
    _fsync(
        directory / "caller-identity.pkl",
        pickle.dumps(identity, protocol=pickle.HIGHEST_PROTOCOL),
        create_only=True,
    )
    result = subprocess.run(
        [sys.executable, "-I", "-W", "error", "-c", script, str(directory), boundary, str(Path(__file__))],
        capture_output=True,
        check=False,
        timeout=180,
    )
    expected = {
        "pre_plan_commit": 81,
        "post_plan_commit": 82,
        "post_bundle_commit": 83,
        "post_driver_commit": 84,
    }[boundary]
    assert result.returncode == expected, result.stderr.decode()
    publication = (
        None
        if boundary == "post_driver_commit"
        else module.RecoveryPublicationV3((directory / "caller-attempt.json").read_text(encoding="utf-8"))
    )
    held = pickle.loads((directory / "caller-bundle.pkl").read_bytes())
    if boundary == "post_bundle_commit":
        with pytest.raises(OptimisticConflict):
            module.RecoveryBundleStoreV3.open(
                directory / "bundle.sqlite", identity=identity, limits=LIMITS, expected_anchor=held.anchor
            )
    if boundary == "post_plan_commit":
        with pytest.raises(OptimisticConflict):
            CompactCommitPlanStoreV3.open(
                directory / "plan-store.sqlite",
                identity=identity.financial,
                limits=PLAN_LIMITS,
                expected_anchor=held.plan_anchor,
            )
    binder, driver, wal, plan_store = _open_actual(
        directory,
        identity,
        publication,
        bundle_committed=boundary == "post_bundle_commit",
        plan_committed=boundary in {"post_plan_commit", "post_bundle_commit"},
    )
    try:
        if boundary == "post_driver_commit":
            assert driver._needs_completed_ack is True
            assert (
                binder.checkpoint_sink(driver.checkpoint()) is True
            )  # Actual owned recovery ACK, no next operation.
        else:
            driver.step(checkpoint_sink=binder.checkpoint_sink, commit_plan_sink=binder.commit_plan_sink)
        current = binder.snapshot()
        assert current.checkpoint == driver.checkpoint() and current.checkpoint.operation_cursor == 2
        assert current.active_plan is None and current.plan_anchor.count == 2
        for account in driver.accounts.values():
            assert decode_account_core(account.snapshot().state["account"])[0].cash == driver_fixture.D(999)
            assert (
                sum(
                    event.payload[:2] == ("SERVICE", driver_fixture.D(1))
                    for event in account.journal.native_events()
                )
                == 1
            )
        assert binder.store.audit(expected_anchor=current.anchor) == current
    finally:
        _close_actual(binder, driver, wal, plan_store)
