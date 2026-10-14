"""Short offline driver checks. NOT a full five-day/four-account run."""

import json
import os
import pickle
import subprocess
import sys
from dataclasses import asdict, dataclass, replace
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import pytest
from kairos_execution.simulation.models import FillAssumptions
from kairos_strategy.candles import Candle
from kairos_strategy.provenance import candle_payload

from adaptive_replay import adaptive_sim_account as account_api
from adaptive_replay import continuous_four_arm_v3 as driver_module
from adaptive_replay import four_arm_checkpoint_wal_v3 as checkpoint_wal_module
from adaptive_replay.candle_originals_v3 import RetainedCandleV3
from adaptive_replay.compact_four_arm_driver_journal_v3 import CompactDriverLimitsV3
from adaptive_replay.continuous_four_arm_v3 import (
    ARMS,
    COMBINED,
    COMPACT_FINANCIAL_PROFILE,
    FINANCIAL_PROFILE,
    CompactFourArmDriverV3,
    FourArmDriverV3,
    FourArmInputsV3,
    FourArmSealV3,
    MinuteCellV3,
    NativeRouteInputV3,
    OriginSlotV3,
    ProducerInputV3,
    ScheduledAttemptV3,
    SharedExpenseV3,
    _anchored_checkpoint,
    _anchored_financial_checkpoint,
    _route_decisions,
    compact_commit_plan_document,
    compact_commit_plan_from_document,
    preflight_four_arm_v3,
    roster_hashes,
)
from adaptive_replay.continuous_sim import (
    UNIVERSE,
    ClosedCandleInput,
    FundingSchedule,
    SimInputError,
    SymbolRules,
    TapeInput,
)
from adaptive_replay.continuous_sim_v3_horizon import (
    FIVE_DAYS,
    FiveDayHorizonV3,
    HorizonCandleOriginalsV3,
    HorizonTapeBindingV3,
)
from adaptive_replay.four_arm_checkpoint_wal_v3 import FourArmCheckpointWalV3, inspect_checkpoint_wal_v3
from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_journal_v3 import (
    HypothesisJournalV3,
    JournalArmV3,
    JournalReceiptV3,
    JournalSealV3,
)
from adaptive_replay.hypothesis_v3 import HypothesisEvaluation, HypothesisPolicy
from adaptive_replay.scenarios import ScenarioEvidence
from adaptive_replay.sim_account_codec import decode_account
from adaptive_replay.sim_account_core_codec_v3 import decode_account_core, encode_account_core
from adaptive_replay.sim_delta_journal_v3 import SimDeltaJournalV3
from adaptive_replay.sim_financial_journal_v3 import (
    DEFAULT_LIMITS,
    FinancialCheckpointV3,
    SimFinancialJournalV3,
    initial_ledger_reference,
)
from adaptive_replay.sim_state_journal import JournalIdentity
from adaptive_replay.system import AttemptReceipt

START, MINUTE, SHA = 86_400_000, 60_000, "a" * 64


@pytest.fixture(scope="module")
def inputs(tmp_path_factory):
    directory = tmp_path_factory.mktemp("four-arm-inputs")
    records = []
    for minute in range(START, START + FIVE_DAYS, MINUTE):
        for symbol in UNIVERSE:
            candle = Candle(symbol, "1m", minute, minute + MINUTE - 1, 100.0, 101.5, 99.5, 100.0, 10.0)
            evidence = ScenarioEvidence(
                "bars",
                "MARKET",
                symbol,
                digest(candle_payload(candle)),
                candle.close_time_ms,
                minute + MINUTE,
                minute + MINUTE,
                600_000,
            )
            records.append(RetainedCandleV3(candle, evidence, minute + MINUTE, "TEST_FIXTURE"))
    originals = HorizonCandleOriginalsV3(
        tuple(sorted(records, key=lambda r: (r.candle.symbol, r.candle.open_time_ms)))
    )
    binding = HorizonTapeBindingV3(
        "source",
        "tape",
        "epoch",
        "quotes",
        "TEST_FIXTURE",
        tuple(
            TapeInput(
                i,
                ClosedCandleInput(
                    r.candle.symbol,
                    r.candle.open_time_ms,
                    r.candle.close_time_ms,
                    r.available_at_ms,
                    D(str(r.candle.close)),
                    "bars",
                    "TEST_FIXTURE",
                    r.evidence.payload_sha256,
                ),
            )
            for i, r in enumerate(records, 1)
        ),
    )
    models = {
        s: FillAssumptions(
            latency_ms=2,
            maximum_book_age_ms=60_000,
            maximum_frame_latency_ms=5000,
            depth_participation_fraction=D(1),
            adverse_slippage_bps=D(0),
            taker_fee_bps=D(10),
            price_tick=D("0.01"),
            quantity_step=D("0.001"),
        )
        for s in UNIVERSE
    }
    arms = tuple(
        JournalArmV3(
            a,
            HypothesisPolicy(
                START - 1, 5 * MINUTE, "quotes", 5000, "TEST_FIXTURE", a in {"combined", "context_review"}
            ),
            SHA if a in {"combined", "context_review"} else None,
        )
        for a in ARMS
    )
    producer = HypothesisJournalV3.create(
        directory / "producer.research.sqlite3", JournalSealV3("originals", START - 1, SHA, arms, 128)
    )
    slots = tuple(
        OriginSlotV3(s, t, t, "QUIET", None, "QUIET", None, SHA)
        for t in range(START, START + FIVE_DAYS, 300_000)
        for s in UNIVERSE
    )
    cells = tuple(
        MinuteCellV3(r.candle.symbol, r.candle.open_time_ms, r.available_at_ms, "AVAILABLE", SHA)
        for r in records
    )
    attempts = tuple(
        ScheduledAttemptV3(
            f"creation:{i}",
            s.key,
            "CREATION",
            s.cut_ms,
            s.cut_ms,
            ("combined", "independent_proposals"),
            (),
            AttemptReceipt(
                f"physical:{i}",
                s.cut_ms,
                s.cut_ms,
                0,
                "NOT_CALLED",
                "TEST_FIXTURE",
                SHA,
                "SCHEDULED_POLICY_ABSTAIN",
            ),
            None,
        )
        for i, s in enumerate(slots)
    )
    return FourArmInputsV3(
        binding,
        originals,
        models,
        {s: SymbolRules(s, D("0.01"), D("0.001"), D(100000)) for s in UNIVERSE},
        FundingSchedule("funding", "TEST_FIXTURE", (), SHA),
        D(1000),
        (ProducerInputV3("native", producer, producer.snapshot().checkpoint),),
        (),
        slots,
        cells,
        attempts,
        (SharedExpenseV3("feed", START, D(1), SHA),),
    )


def sealed(inputs):
    return FourArmSealV3(
        "four-arm-test",
        START - 1,
        FiveDayHorizonV3(START, START + FIVE_DAYS + 3 * 3_600_000, START),
        **roster_hashes(inputs),
        budgets_usd=tuple((a, D(0)) for a in ARMS),
        budget_evidence_sha256=SHA,
    )


@pytest.fixture(scope="module")
def prepared(inputs):
    return preflight_four_arm_v3(inputs, sealed(inputs))


def test_complete_roster_and_explicit_arm_wide_semantics(prepared):
    assert len(prepared.inputs.minute_cells) == 36_000
    assert len(prepared.inputs.origin_slots) == 7200
    assert len(prepared.inputs.attempts) == 7200
    assert prepared.seal.combined_semantics == COMBINED
    assert not prepared.routing
    assert prepared.expected_parents == {a: () for a in ARMS}


def test_missing_cell_or_frozen_attempt_obligation_is_not_quiet(inputs):
    bad = replace(inputs, minute_cells=inputs.minute_cells[:-1])
    with pytest.raises(SimInputError, match="36,000"):
        preflight_four_arm_v3(bad, sealed(bad))
    bad = replace(inputs, attempts=inputs.attempts[:-1])
    with pytest.raises(SimInputError, match="one retained proposal attempt"):
        preflight_four_arm_v3(bad, sealed(bad))


def test_known_error_unknown_cost_and_missing_attempt_poison_coverage(inputs):
    first = inputs.attempts[0]
    for receipt in (
        None,
        replace(first.attempt, status="ERROR", cost_usd=None, no_call_reason=None),
        replace(first.attempt, status="ERROR", cost_usd=0.25, no_call_reason=None),
    ):
        bad_attempt = replace(first, attempt=receipt)
        bad = replace(inputs, attempts=(bad_attempt, *inputs.attempts[1:]))
        result = preflight_four_arm_v3(bad, sealed(bad))
        key = f"{inputs.origin_slots[0].symbol}:{START}"
        assert {"combined", "independent_proposals"} <= result.cell_facts[key]["unavailable"]
        if receipt is not None and receipt.cost_usd == 0.25:
            assert result.budget_blocked == ("combined", "independent_proposals")


def test_sources_are_exact_prefix_before_cost_decisions_and_cells(prepared):
    operations = prepared.operations
    cursor = 0
    seen_control = False
    for operation in operations:
        if operation["kind"] == "SOURCE":
            assert operation["first"] == cursor + 1
            assert operation["last"] - operation["first"] < 500
            cursor = operation["last"]
        else:
            while cursor < len(prepared.inputs.binding.inputs):
                next_value = prepared.inputs.binding.inputs[cursor].value
                assert next_value.available_at_ms > operation["at"]
                break
            seen_control = True
    assert cursor == len(prepared.inputs.binding.inputs) == 36_000
    assert seen_control
    assert all(a["at"] <= b["at"] for a, b in zip(operations, operations[1:], strict=False))


def test_exact_pending_event_anchor_refuses_latest_adoption(tmp_path):
    identity = JournalIdentity("anchor", "source", SHA, SHA)
    journal = SimDeltaJournalV3.create(
        tmp_path / "account.sqlite3", identity=identity, initial_state={"value": 0}, initial_clock_ms=START
    )
    before = journal.checkpoint()
    try:
        snap = journal.snapshot()
        journal.append(
            event_id="expected",
            payload={"amount": "1", "at": START},
            outcome={},
            state={"value": 1},
            expected_version=snap.version,
            expected_state_hash=snap.state_hash,
            expected_head_sha256=snap.head_hash,
            at_ms=START,
        )
        expected = {"event_id": "expected", "payload": {"amount": "1", "at": START}}
        assert _anchored_checkpoint(journal.path, before, expected) == journal.checkpoint()
        with pytest.raises(SimInputError, match="EXACT"):
            _anchored_checkpoint(journal.path, before, {"event_id": "alien", "payload": expected["payload"]})
        with pytest.raises(SimInputError, match="outside one"):
            _anchored_checkpoint(journal.path, before, None)
    finally:
        journal.close()


@pytest.mark.parametrize("last", [1, 2])
def test_financial_anchor_exact_flat_native_chain_owner_clock_cursor(tmp_path, last):
    """Tiny native transaction, not original-source or dense capacity proof."""
    identity = JournalIdentity("financial-anchor", "source", SHA, SHA)
    owner, arm = "owner", "combined"
    policy = account_api.AccountPolicy(D("0.1"), D("5"), D("5"), D("2"), 10_000, "ENTRY_STOP_RESERVED")
    native = account_api.new_account(D(1000), policy)
    journal = SimFinancialJournalV3.create(
        tmp_path / "native.sqlite3",
        identity=identity,
        owner_id=owner,
        account_id=arm,
        allowed_quantity_steps=(D("0.1"),),
        initial_state={
            "account": encode_account_core(
                native, initial_ledger_reference(identity, owner_id=owner, account_id=arm)
            ),
            "cursor": 0,
        },
    )
    config = {
        "financial_account": {"owner_id": owner, "account_id": arm, "allowed_quantity_steps": ["0.1"]},
        "storage": DEFAULT_LIMITS,
    }
    before = journal.checkpoint()
    kwargs = {"mark_id": "every-flat-mark", "marks": (("BTCUSDT", D(100), 10),), "as_of_ms": 10}
    native, _ = account_api.mark_account(native, **kwargs)
    payload = {"kind": "SOURCE_BATCH", "first": 1, "last": last, "at": 10}
    event = {"event_id": "exact-source", "payload": payload}

    def fold(state):
        account, reference = decode_account_core(state["account"])
        journal.validate_ledger_reference(reference)
        account, _ = account_api.mark_account(account, **kwargs)
        state["account"] = encode_account_core(account, journal.ledger_reference())
        state["cursor"] = 1
        return {}

    try:
        journal.transition(
            event_id=event["event_id"],
            payload=payload,
            at_ms=10,
            expected_version=before.version,
            expected_state_hash=before.state_hash,
            expected_head_sha256=before.head_hash,
            fold=fold,
        )
        assert tuple(journal.native_events()) == native.events
        assert journal.checkpoint().native_count == 1
        if last == 2:
            with pytest.raises(SimInputError, match="EXACT"):
                _anchored_financial_checkpoint(journal.path, before, event, identity=identity, config=config)
            return
        assert (
            _anchored_financial_checkpoint(journal.path, before, event, identity=identity, config=config)
            == journal.checkpoint()
        )
        with pytest.raises(SimInputError, match="identity/owner"):
            _anchored_financial_checkpoint(
                journal.path, replace(before, owner_id="alien"), event, identity=identity, config=config
            )
        with pytest.raises(SimInputError, match="before prefix"):
            _anchored_financial_checkpoint(
                journal.path, replace(before, native_count=1), event, identity=identity, config=config
            )
        with pytest.raises(SimInputError, match="source prefix"):
            _anchored_financial_checkpoint(
                journal.path,
                before,
                {**event, "payload": {**payload, "last": True}},
                identity=identity,
                config=config,
            )
        with pytest.raises(SimInputError, match="EXACT"):
            _anchored_financial_checkpoint(
                journal.path,
                before,
                {**event, "payload": {**payload, "at": 11}},
                identity=identity,
                config=config,
            )
        with pytest.raises(SimInputError, match="outside one"):
            _anchored_financial_checkpoint(journal.path, before, None, identity=identity, config=config)
    finally:
        journal.close()


def test_actual_four_durable_accounts_partial_commit_crash_and_restart(tmp_path, prepared, monkeypatch):
    """Only one real financial operation, not a five-day x four replay."""
    directory = tmp_path / "run"
    driver = FourArmDriverV3.create(directory, prepared)
    saved = []
    original = driver.accounts["combined"].debit_service

    def crash_after_one_account(**kwargs):
        original(**kwargs)
        raise RuntimeError("simulated crash after one durable arm")

    monkeypatch.setattr(driver.accounts["combined"], "debit_service", crash_after_one_account)
    with pytest.raises(RuntimeError, match="simulated crash"):
        driver.step(checkpoint_sink=saved.append)
    assert saved[-1].pending_operation_sha256 is not None
    assert driver.accounts["combined"].snapshot().version == 1
    assert driver.accounts["independent_proposals"].snapshot().version == 0
    driver.close()
    driver = FourArmDriverV3.open(directory, prepared, saved[-1])
    try:
        driver.step()
        assert driver.accounts["combined"].snapshot().version == 1
        assert driver.accounts["independent_proposals"].snapshot().version == 1
        assert driver.accounts["strategy_only"].snapshot().version == 0
        assert driver.accounts["context_review"].snapshot().version == 0
        assert driver.journal.snapshot().state["cursor"] == 1
        assert driver.journal.snapshot().state["pending"] is None
        assert len({p.path for p in driver.accounts.values()}) == 4
        assert all(
            decode_account(p.snapshot().state["account"]).cash == D(1000) for p in driver.accounts.values()
        )
        checkpoint = driver.checkpoint()
    finally:
        driver.close()
    driver = FourArmDriverV3.open(directory, prepared, checkpoint)
    try:
        assert driver.checkpoint() == checkpoint
        with pytest.raises(SimInputError, match="complete the chronological"):
            driver.finish()
        # A separate account writer cannot be adopted as the next WAL-before
        # head, even when it leaves the economic projection unchanged.
        alien = driver.accounts["strategy_only"].journal
        snap = alien.snapshot()
        alien.append(
            event_id="outside-driver",
            payload={"outside": True},
            outcome={},
            state=snap.state,
            expected_version=snap.version,
            expected_state_hash=snap.state_hash,
            expected_head_sha256=snap.head_hash,
            at_ms=START,
        )
        before_driver = driver.journal.checkpoint()
        with pytest.raises(SimInputError, match="outside recorded driver"):
            driver.step()
        with pytest.raises(SimInputError, match="outside recorded driver"):
            driver.checkpoint()
        assert driver.journal.checkpoint() == before_driver
    finally:
        driver.close()


@pytest.fixture(scope="module")
def financial_prepared(inputs):
    return preflight_four_arm_v3(inputs, sealed(inputs), account_profile=FINANCIAL_PROFILE)


def test_financial_preintent_requires_exact_durable_ack_before_any_write(tmp_path, financial_prepared):
    driver = FourArmDriverV3.create(tmp_path / "financial", financial_prepared)
    try:
        before = driver.checkpoint()
        with pytest.raises(SimInputError, match="durable checkpoint sink"):
            driver.step()
        for ack in (None, False, 1):
            with pytest.raises(SimInputError, match="ACK True exactly"):
                driver.step(checkpoint_sink=lambda checkpoint, value=ack: value)
            assert driver.checkpoint() == before

        def fail(checkpoint):
            raise RuntimeError("sink unavailable")

        with pytest.raises(RuntimeError, match="sink unavailable"):
            driver.step(checkpoint_sink=fail)
        assert driver.checkpoint() == before

        # Even a callback ACK cannot rebase an unplanned driver writer into
        # the next intent. The held own-commit fence remains version zero.
        def inject_unplanned_driver_head(checkpoint):
            snap = driver.journal.snapshot()
            driver.journal.append(
                event_id="unplanned-driver",
                payload={"unplanned": True},
                outcome={},
                state=snap.state,
                expected_version=snap.version,
                expected_state_hash=snap.state_hash,
                expected_head_sha256=snap.head_hash,
                at_ms=START,
            )
            return True

        with pytest.raises(SimInputError, match="driver advanced outside"):
            driver.step(checkpoint_sink=inject_unplanned_driver_head)
        assert driver.journal.checkpoint().version == 1
        assert all(a.journal.checkpoint().version == 0 for a in driver.accounts.values())
        with pytest.raises(SimInputError, match="driver advanced outside"):
            driver.checkpoint()
    finally:
        driver.close()


def test_financial_intent_ack_failure_never_runs_accounts(tmp_path, financial_prepared, monkeypatch):
    driver = FourArmDriverV3.create(tmp_path / "financial", financial_prepared)
    saved = []

    def sink(checkpoint):
        saved.append(checkpoint)
        return checkpoint.checkpoint_phase == "PREPARED_INTENT"

    try:
        with pytest.raises(SimInputError, match="ACK True exactly"):
            driver.step(checkpoint_sink=sink)
        assert driver.journal.checkpoint().version == 1
        assert all(a.journal.checkpoint().version == 0 for a in driver.accounts.values())
        retained = saved[0]
        assert retained.checkpoint_phase == "PREPARED_INTENT"
    finally:
        driver.close()
    driver = FourArmDriverV3.open(tmp_path / "financial", financial_prepared, retained)
    try:
        assert all(a.journal.checkpoint().version == 0 for a in driver.accounts.values())
        with pytest.raises(SimInputError, match="ACK True exactly"):
            driver.step(checkpoint_sink=lambda checkpoint: False)
        assert all(a.journal.checkpoint().version == 0 for a in driver.accounts.values())
        execute = driver._execute
        monkeypatch.setattr(driver, "_execute", lambda operation, state: None)
        with pytest.raises(SimInputError, match="missing exact completed"):
            driver.step(checkpoint_sink=lambda checkpoint: True)
        assert driver.journal.snapshot().state["cursor"] == 0
        assert all(a.journal.checkpoint().version == 0 for a in driver.accounts.values())
        monkeypatch.setattr(driver, "_execute", execute)
        driver.step(checkpoint_sink=lambda checkpoint: True)
        assert driver.journal.snapshot().state["cursor"] == 1
    finally:
        driver.close()


def test_financial_actual_checkpoint_wal_partial_arm_restart_unknown_and_torn_head(
    tmp_path, financial_prepared, monkeypatch
):
    """One actual SERVICE operation x four, not full five-day capacity proof.

    ACKs use actual file write/flush/fsync, not a list or synthetic checkpoint.
    This tests process-crash consistency, not hardware/power-loss durability.
    """
    directory = tmp_path / "financial"
    wal_path = tmp_path / "independent-checkpoints.wal"
    driver = FourArmDriverV3.create(directory, financial_prepared)
    fsync_calls = []
    fsync = checkpoint_wal_module.os.fsync

    def real_fsync(fd):
        result = fsync(fd)
        fsync_calls.append(fd)
        return result

    monkeypatch.setattr(checkpoint_wal_module.os, "fsync", real_fsync)

    original = driver.accounts["combined"].debit_service

    def crash(**kwargs):
        original(**kwargs)
        raise RuntimeError("after first financial arm")

    monkeypatch.setattr(driver.accounts["combined"], "debit_service", crash)
    try:
        with FourArmCheckpointWalV3.create(wal_path, driver.checkpoint()) as wal:
            with pytest.raises(RuntimeError, match="first financial arm"):
                driver.step(checkpoint_sink=wal)
            retained = wal.snapshot()
            assert retained.anchor.frame_count == 3 and len(fsync_calls) == 3
            assert retained.checkpoint.checkpoint_phase == "INTENT_COMMITTED"
            assert all(type(c) is FinancialCheckpointV3 for _, c in retained.checkpoint.arm_checkpoints)
            assert retained.checkpoint.pending_operation_sha256 == digest(
                retained.checkpoint.pending_operation
            )
            exact = tuple(driver.accounts["combined"].journal.native_events())
            assert len(exact) == 1 and exact[0].payload[0] == "SERVICE"
    finally:
        driver.close()
    assert inspect_checkpoint_wal_v3(wal_path, identity_sha256=financial_prepared.identity_sha256) == retained
    driver = FourArmDriverV3.open(directory, financial_prepared, retained.checkpoint)
    try:
        with FourArmCheckpointWalV3.open(wal_path, expected_anchor=retained.anchor) as wal:
            driver.step(checkpoint_sink=wal)
            assert tuple(driver.accounts["combined"].journal.native_events()) == exact
            assert len(tuple(driver.accounts["independent_proposals"].journal.native_events())) == 1
            assert all(
                decode_account_core(a.snapshot().state["account"])[0].cash == D(1000)
                for a in driver.accounts.values()
            )
            committed = wal.snapshot()
            assert committed.checkpoint == driver.checkpoint()
            assert committed.anchor.frame_count == len(fsync_calls) == 5
            checkpoint = committed.checkpoint
    finally:
        driver.close()
    with pytest.raises(ValueError, match="independent exact anchor"):
        FourArmCheckpointWalV3.open(wal_path, expected_anchor=retained.anchor)
    driver = FourArmDriverV3.open(directory, financial_prepared, checkpoint)
    try:
        assert driver.checkpoint() == checkpoint
        account = driver.accounts["strategy_only"]
        snap = account.journal.snapshot()
        account.journal.transition(
            event_id="unplanned",
            payload={"at": START},
            at_ms=START,
            expected_version=snap.version,
            expected_state_hash=snap.state_hash,
            expected_head_sha256=snap.head_hash,
            fold=lambda state: {},
        )
        before = driver.journal.checkpoint()
        with FourArmCheckpointWalV3.open(wal_path, expected_anchor=committed.anchor) as wal:
            with pytest.raises(SimInputError, match="outside recorded driver"):
                driver.step(checkpoint_sink=wal)
            assert wal.snapshot().anchor == committed.anchor
        assert driver.journal.checkpoint() == before
    finally:
        driver.close()
    with pytest.raises(SimInputError, match="outside one"):
        FourArmDriverV3.open(directory, financial_prepared, checkpoint)
    tail = b"\x00" * 7
    with wal_path.open("ab") as target:
        target.write(tail)
    inspected = inspect_checkpoint_wal_v3(wal_path, identity_sha256=financial_prepared.identity_sha256)
    assert inspected.anchor == committed.anchor and inspected.checkpoint == checkpoint
    assert inspected.torn_tail_bytes == len(tail)
    with pytest.raises(ValueError, match="torn tail"):
        FourArmCheckpointWalV3.open(wal_path, expected_anchor=committed.anchor)
    assert wal_path.read_bytes().endswith(tail)  # No repair/truncation/adoption.


@pytest.mark.parametrize("boundary", ["intent", "commit"])
def test_financial_postcommit_precheckpoint_recovers_only_known_wal(
    tmp_path, financial_prepared, monkeypatch, boundary
):
    directory = tmp_path / "financial"
    driver = FourArmDriverV3.create(directory, financial_prepared)
    saved = []

    def sink(checkpoint):
        saved.append(checkpoint)
        return True

    original = driver._append

    def crash(event_id, *args):
        result = original(event_id, *args)
        if event_id.endswith(":" + boundary):
            raise RuntimeError("after durable driver " + boundary)
        return result

    monkeypatch.setattr(driver, "_append", crash)
    with pytest.raises(RuntimeError, match="durable driver"):
        driver.step(checkpoint_sink=sink)
    retained = saved[-1]
    assert retained.checkpoint_phase == ("PREPARED_INTENT" if boundary == "intent" else "INTENT_COMMITTED")
    driver.close()
    driver = FourArmDriverV3.open(directory, financial_prepared, retained)
    try:
        if boundary == "intent":
            assert all(a.journal.checkpoint().version == 0 for a in driver.accounts.values())
            driver.step(checkpoint_sink=sink)
        assert driver.journal.snapshot().state["cursor"] == 1
        assert driver.journal.snapshot().state["pending"] is None
        assert len(tuple(driver.accounts["combined"].journal.native_events())) == 1
    finally:
        driver.close()


def test_capacity_refused_before_any_account_creation(inputs, monkeypatch):
    producer = inputs.producers[0]
    original_snapshot = producer.journal.snapshot()
    groups = tuple(
        SimpleNamespace(arm_id=a, plan=SimpleNamespace(template=SimpleNamespace(intent_id=digest(i))))
        for i in range(129)
        for a in ARMS
    )
    monkeypatch.setattr(
        producer.journal,
        "snapshot",
        lambda: SimpleNamespace(checkpoint=original_snapshot.checkpoint, hypotheses=groups),
    )
    with pytest.raises(SimInputError, match="128-parent capacity"):
        preflight_four_arm_v3(inputs, sealed(inputs))


def test_unknown_budget_is_not_admission_permission(inputs):
    seal = replace(sealed(inputs), budgets_usd=tuple((a, None if a == "combined" else D(0)) for a in ARMS))
    result = preflight_four_arm_v3(inputs, seal)
    assert result.budget_blocked == ("combined",)


def test_abstention_is_explicit_and_not_relabelled_missing(inputs):
    first = inputs.attempts[0]
    assert first.attempt.status == "NOT_CALLED"
    assert first.attempt.cost_usd == 0
    assert first.attempt.no_call_reason == "SCHEDULED_POLICY_ABSTAIN"
    with pytest.raises(ValueError, match="zero call cost"):
        replace(first.attempt, cost_usd=None)
    with pytest.raises(SimInputError, match="error/no-call"):
        replace(first, original_response_sha256=SHA)


@dataclass(frozen=True)
class RouterUnitTemplate:
    symbol: str
    intent_id: str


@dataclass(frozen=True)
class RouterUnitPlan:
    template: RouterUnitTemplate
    origin: str
    origin_cut_ms: int


@dataclass(frozen=True)
class RouterUnitCandidate:
    side: str


def router_unit_inputs(inputs, *, technical=True, proposal=True, proposal_delay=0, conflict=False):
    """Synthetic branch inputs ONLY; native preflight does not admit these."""
    symbol, at = UNIVERSE[0], START + MINUTE + 200
    technical_id, proposal_id = digest("technical"), digest("proposal")
    slot = OriginSlotV3(
        symbol,
        START,
        START,
        "PARENT" if technical else "QUIET",
        technical_id if technical else None,
        "PARENT" if proposal else "QUIET",
        proposal_id if proposal else None,
        SHA,
    )
    groups, routes = {}, []
    for origin, parent, enabled in (
        ("TECHNICAL", technical_id, technical),
        ("CONTEXT_PROPOSAL", proposal_id, proposal),
    ):
        if not enabled:
            continue
        for arm in ARMS:
            plan = RouterUnitPlan(RouterUnitTemplate(symbol, parent), origin, START)
            clock = at + (proposal_delay if origin == "CONTEXT_PROPOSAL" else 0)
            candidate = RouterUnitCandidate("SHORT" if conflict and origin == "CONTEXT_PROPOSAL" else "LONG")
            evaluation = HypothesisEvaluation(
                SHA, SHA, None, "CONSUMED", "UNIT_ONLY", "AVAILABLE", clock, candidate
            )
            native = NativeRouteInputV3("native", JournalReceiptV3(False, 1, SHA, arm, parent, evaluation))
            groups["native", arm, parent] = SimpleNamespace(plan=plan)
            routes.append(native)
    return replace(inputs, native_routes=tuple(routes), origin_slots=(slot,)), groups


def test_router_unit_origin_acl_and_conflict_do_not_grant_enrollment_permission(inputs):
    synthetic, groups = router_unit_inputs(inputs, conflict=True)
    decisions = _route_decisions(synthetic, sealed(inputs), groups, ())
    indexed = {(r["arm"], r["origin"]): r for r in decisions}
    assert indexed["strategy_only", "TECHNICAL"]["disposition"] == "ROUTE"
    assert indexed["context_review", "CONTEXT_PROPOSAL"]["reason"] == "INACTIVE_ORIGIN"
    assert indexed["strategy_only", "CONTEXT_PROPOSAL"]["disposition"] == "NO_ROUTE"
    assert indexed["independent_proposals", "TECHNICAL"]["disposition"] == "NO_ROUTE"
    assert indexed["combined", "TECHNICAL"]["reason"] == "DIRECTION_CONFLICT"
    assert indexed["combined", "CONTEXT_PROPOSAL"]["reason"] == "TECHNICAL_FIRST_NO_PROPOSAL_FALLBACK"


def test_router_unit_late_peer_is_unavailable_not_backdated(inputs):
    synthetic, groups = router_unit_inputs(inputs, proposal_delay=100)
    decisions = _route_decisions(synthetic, sealed(inputs), groups, ())
    technical = next(r for r in decisions if r["arm"] == "combined" and r["origin"] == "TECHNICAL")
    assert technical["disposition"] == "UNAVAILABLE"
    assert technical["coverage"] == "UNAVAILABLE"
    assert technical["reason"] == "PEER_ARBITRATION_NOT_KNOWN_AT_NATIVE_ISSUE"
    assert technical["at"] == START + MINUTE + 200


def test_router_unit_unknown_budget_blocks_active_origins_but_retains_no_route(inputs):
    synthetic, groups = router_unit_inputs(inputs, technical=False)
    decisions = _route_decisions(synthetic, sealed(inputs), groups, ("combined", "independent_proposals"))
    assert all(
        r["disposition"] == "UNAVAILABLE"
        for r in decisions
        if r["arm"] in {"combined", "independent_proposals"}
    )

    assert all(
        r["disposition"] == "NO_ROUTE" for r in decisions if r["arm"] in {"strategy_only", "context_review"}
    )


COMPACT_TEST_LIMITS = CompactDriverLimitsV3(128, 64, 65536, 131072, 8192, 16, 4 * 1024 * 1024)


class _ShortNativeAccount:
    """Bounded driver contract harness: real SQL/native reducers, not source admission."""

    def __init__(self, journal, config, path, binding):
        self.journal, self.config, self.path, self.binding = journal, config, Path(path), binding

    @classmethod
    def create(cls, path, **arguments):
        arm, owner = arguments["account_id"], arguments["owner_id"]
        config = {
            "financial_account": {"owner_id": owner, "account_id": arm, "allowed_quantity_steps": ["0.1"]},
            "storage": DEFAULT_LIMITS,
            "expected_cost_ids": list(arguments["expected_cost_ids"]),
        }
        identity = JournalIdentity(owner, "short-contract-source", SHA, SHA)
        account = account_api.new_account(
            D(1000), account_api.AccountPolicy(D("0.1"), D(5), D(5), D(2), 10000, "ENTRY_STOP_RESERVED")
        )
        journal = SimFinancialJournalV3.create(
            path,
            identity=identity,
            owner_id=owner,
            account_id=arm,
            allowed_quantity_steps=(D("0.1"),),
            initial_state={
                "config": config,
                "account": encode_account_core(
                    account, initial_ledger_reference(identity, owner_id=owner, account_id=arm)
                ),
                "cursor": 0,
                "parents": {},
                "slots": {},
                "service_liabilities": {},
            },
        )
        return cls(journal, config, path, arguments["binding"])

    @classmethod
    def open(cls, path, **arguments):
        config = arguments["config"]
        financial = config["financial_account"]
        journal = SimFinancialJournalV3.open(
            path,
            identity=arguments["identity"],
            owner_id=financial["owner_id"],
            account_id=financial["account_id"],
            allowed_quantity_steps=(D("0.1"),),
            expected_checkpoint=arguments["expected_checkpoint"],
        )
        return cls(journal, config, path, arguments["binding"])

    def snapshot(self):
        return self.journal.snapshot()

    def close(self):
        self.journal.close()

    def _event(self, event_id, payload, at, fold):
        old = self.journal.lookup(event_id=event_id, payload=payload)
        if old is not None:
            return old
        before = self.journal.snapshot()
        return self.journal.transition(
            event_id=event_id,
            payload=payload,
            at_ms=at,
            expected_version=before.version,
            expected_state_hash=before.state_hash,
            expected_head_sha256=before.head_hash,
            fold=fold,
        )

    def debit_service(self, *, cost_id, amount, at_ms):
        def fold(state):
            account, reference = decode_account_core(state["account"])
            self.journal.validate_ledger_reference(reference)
            account = account_api.debit_cost(
                account, cost_id=cost_id, amount=amount, at_ms=at_ms, kind="SERVICE"
            )
            state["account"] = encode_account_core(account, self.journal.ledger_reference())
            state["service_liabilities"][cost_id] = {"status": "SETTLED", "amount": str(amount), "at": at_ms}
            return {"status": "DEBITED"}

        return self._event(f"cost:{cost_id}", {"amount": str(amount), "at": at_ms}, at_ms, fold)

    def record_unknown_service(self, *, cost_id, source_sha256, at_ms):
        def fold(state):
            state["service_liabilities"][cost_id] = {
                "status": "UNAVAILABLE",
                "source": source_sha256,
                "at": at_ms,
            }
            return {"status": "UNAVAILABLE"}

        return self._event(
            f"unknown-service:{cost_id}", {"cost": cost_id, "source": source_sha256, "at": at_ms}, at_ms, fold
        )

    def record_slots_batch(self, *, cells, source_sha256, at_ms):
        def fold(state):
            for symbol, minute, status in cells:
                assert f"{symbol}:{minute}" not in state["slots"]
                state["slots"][f"{symbol}:{minute}"] = {
                    "status": status,
                    "source": source_sha256,
                    "parents": [],
                }
            return {"status": "RECORDED", "cells": len(cells)}

        payload = {"kind": "DENOMINATOR_BATCH", "cells": cells, "source": source_sha256, "at": at_ms}
        return self._event(f"slots-batch:{digest(cells)}", payload, at_ms, fold)

    def finish(self, *, now_ms, event_id):
        return self._event(
            event_id,
            {"kind": "FINISH", "at": now_ms},
            now_ms,
            lambda state: {"status": "UNRESOLVED", "net_return": None},
        )


def _short_compact_prepared(directory, profile=COMPACT_FINANCIAL_PROFILE, existing=False):
    """Explicit SHORT contract, bypasses full roster preflight ONLY in this harness."""
    directory = Path(directory)
    directory.mkdir(exist_ok=True)
    arms = tuple(
        JournalArmV3(a, HypothesisPolicy(0, 300000, "quotes", 5000, "TEST_FIXTURE", False)) for a in ARMS
    )
    seal = JournalSealV3("short-originals", 0, SHA, arms, 128)
    producer_path = directory / "producer.research.sqlite3"
    if existing:
        checkpoint = pickle.loads((directory / "producer-caller-checkpoint").read_bytes())
        producer = HypothesisJournalV3.open(producer_path, seal, minimum_checkpoint=checkpoint)
    else:
        producer = HypothesisJournalV3.create(producer_path, seal)
        checkpoint = producer.snapshot().checkpoint
        with (directory / "producer-caller-checkpoint").open("xb") as stream:
            pickle.dump(checkpoint, stream)
    cells = (MinuteCellV3("BTCUSDT", 60000, 120000, "AVAILABLE", SHA),)
    inputs = SimpleNamespace(
        binding=SimpleNamespace(inputs=(), evidence_kind="TEST_FIXTURE"),
        models={},
        rules={},
        funding_schedule=None,
        initial_equity=D(1000),
        candle_originals=None,
        producers=(ProducerInputV3("native", producer, checkpoint),),
        native_routes=(),
        attempts=(),
        shared_expenses=(SharedExpenseV3("feed", 1, D(1), SHA), SharedExpenseV3("unknown", 2, None, SHA)),
        minute_cells=cells,
    )
    operations = (
        {"kind": "EXPENSE", "at": 1, "index": 0},
        {"kind": "EXPENSE", "at": 2, "index": 1},
        {"kind": "CELL", "at": 120000, "index": 0},
        {"kind": "FINISH", "at": 120001},
    )
    return SimpleNamespace(
        account_profile=profile,
        compact_storage=tuple(sorted(asdict(COMPACT_TEST_LIMITS).items()))
        if profile == COMPACT_FINANCIAL_PROFILE
        else (),
        compact_config_hashes=tuple(
            (
                arm,
                digest(
                    {
                        "financial_account": {
                            "owner_id": "short-driver",
                            "account_id": arm,
                            "allowed_quantity_steps": ["0.1"],
                        },
                        "storage": DEFAULT_LIMITS,
                        "expected_cost_ids": ["feed", "unknown"],
                    }
                ),
            )
            for arm in ARMS
        )
        if profile == COMPACT_FINANCIAL_PROFILE
        else (),
        account_storage=tuple(sorted(DEFAULT_LIMITS.items())),
        seal=SimpleNamespace(experiment_id="short-driver", horizon=SimpleNamespace(data_start_ms=0)),
        inputs=inputs,
        identity_sha256=digest(["SHORT_CONTRACT_NOT_HISTORICAL", profile]),
        operations=operations,
        routing=(),
        producer_snapshots={"native": SimpleNamespace(seal_sha256=checkpoint.seal_sha256)},
        expected_parents=dict.fromkeys(ARMS, ()),
        cell_facts={cells[0].key: {"unavailable": set(), "no_route": set(), "routes": {a: [] for a in ARMS}}},
        budget_blocked=(),
    )


def _short_driver_harness(monkeypatch):
    monkeypatch.setattr(FourArmDriverV3, "_refresh", staticmethod(lambda prepared: prepared))
    monkeypatch.setattr(driver_module, "_consumer", lambda profile: _ShortNativeAccount)


def test_compact_short_differential_cost_unknown_denominator_and_restart(tmp_path, monkeypatch):
    _short_driver_harness(monkeypatch)
    prepared = _short_compact_prepared(tmp_path / "originals")
    old = SimpleNamespace(**vars(prepared))
    old.account_profile = FINANCIAL_PROFILE
    old.identity_sha256 = digest(["SHORT_CONTRACT_NOT_HISTORICAL", FINANCIAL_PROFILE])
    old.compact_storage = ()
    with_driver = FourArmDriverV3.create(tmp_path / "compact", prepared)
    assert type(with_driver) is CompactFourArmDriverV3
    conventional = FourArmDriverV3.create(tmp_path / "old-financial", old)
    saved, plans = [], []

    def sink(checkpoint):
        saved.append(checkpoint)
        return True

    def retain(plan):
        plans.append(plan)
        return True

    try:
        with_driver.step(maximum_operations=4, checkpoint_sink=sink, commit_plan_sink=retain)
        conventional.step(maximum_operations=4, checkpoint_sink=lambda checkpoint: True)
        assert with_driver.finish() == conventional.finish()
        assert with_driver.finish()["physical_unknown_expenses"] == ["unknown"]
        assert with_driver.finish()["physical_known_spend_usd"] == "1"
        assert with_driver.finish()["winner"] is None
        hot = with_driver.journal.snapshot().state
        assert not {"routes", "cells", "costs", "slots"}.intersection(hot)
        cp = with_driver.journal.checkpoint()
        for kind in ("costs", "cells"):
            originals = {r.key: r.value for r in with_driver._cold_pages(kind, cp)}
            assert originals == conventional.journal.snapshot().state[kind]
        for arm in ARMS:
            assert tuple(with_driver.accounts[arm].journal.native_events()) == tuple(
                conventional.accounts[arm].journal.native_events()
            )
            assert (
                decode_account_core(with_driver.accounts[arm].snapshot().state["account"])[0]
                == decode_account_core(conventional.accounts[arm].snapshot().state["account"])[0]
            )
        checkpoint = saved[-1]
    finally:
        with_driver.close()
        conventional.close()
    restarted = FourArmDriverV3.open(tmp_path / "compact", prepared, checkpoint)
    try:
        assert restarted.finish()["status"] == "UNRESOLVED"
        assert compact_commit_plan_from_document(compact_commit_plan_document(plans[0])) == plans[0]
    finally:
        restarted.close()


def test_compact_short_plan_sink_lost_response_replays_exact_effects_only(tmp_path, monkeypatch):
    _short_driver_harness(monkeypatch)
    prepared = _short_compact_prepared(tmp_path / "originals")
    driver = FourArmDriverV3.create(tmp_path / "compact", prepared)
    saved, plans = [], []

    def checkpoint_sink(value):
        saved.append(value)
        return True

    def lost(plan):
        plans.append(compact_commit_plan_document(plan))
        raise RuntimeError("durable plan ACK lost")

    try:
        before = driver.checkpoint()
        with pytest.raises(SimInputError):
            driver.step(checkpoint_sink=checkpoint_sink)
        assert driver.checkpoint() == before
        with pytest.raises(RuntimeError, match="ACK lost"):
            driver.step(checkpoint_sink=checkpoint_sink, commit_plan_sink=lost)
        assert driver.journal.snapshot().version == 1
        assert all(a.journal.checkpoint().version == 1 for a in driver.accounts.values())
        retained, plan = saved[-1], compact_commit_plan_from_document(plans[-1])
    finally:
        driver.close()
    restarted = FourArmDriverV3.open(tmp_path / "compact", prepared, retained, expected_commit_plan=plan)
    try:
        restarted.step(checkpoint_sink=checkpoint_sink, commit_plan_sink=lambda p: True)
        assert restarted.journal.snapshot().state["cursor"] == 1
        assert all(len(tuple(a.journal.native_events())) == 1 for a in restarted.accounts.values())
    finally:
        restarted.close()


def _fsync_compact_plan(path, plan):
    """Test-only durable sink: fresh file or exact already-retained duplicate."""
    encoded = json.dumps(compact_commit_plan_document(plan), sort_keys=True, separators=(",", ":")).encode()
    path = Path(path)
    if path.exists():
        if path.read_bytes() != encoded:
            raise RuntimeError("durable compact plan conflict")
        return True
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    return True


@pytest.mark.parametrize("boundary", ["partial_arm", "driver_commit"])
def test_compact_actual_subprocess_crash_native_sql_wal_and_known_plan(tmp_path, monkeypatch, boundary):
    """Actual driver/native SQLite/WAL, SHORT contract; no full-source admission."""
    from ._isolated_fixture import FIXTURE_BOOTSTRAP

    _short_driver_harness(monkeypatch)
    prepared = _short_compact_prepared(tmp_path / "originals")
    directory = tmp_path / "compact"
    driver = FourArmDriverV3.create(directory, prepared)
    initial = driver.checkpoint()
    driver.close()
    wal_path = tmp_path / "checkpoint.wal"
    with FourArmCheckpointWalV3.create(wal_path, initial) as wal:
        anchor = wal.snapshot().anchor
    payload_path = tmp_path / "trusted-bootstrap"
    with payload_path.open("xb") as stream:
        pickle.dump((initial, anchor), stream)
    code = (
        FIXTURE_BOOTSTRAP
        + """
import os, pickle, sys
from pathlib import Path
from adaptive_replay import continuous_four_arm_v3 as d
from adaptive_replay.four_arm_checkpoint_wal_v3 import FourArmCheckpointWalV3
helpers = vars(load_isolated_fixture_module(sys.argv[1]))
root, boundary = Path(sys.argv[2]), sys.argv[3]
d.FourArmDriverV3._refresh = staticmethod(lambda p: p)
d._consumer = lambda profile: helpers['_ShortNativeAccount']
p = helpers['_short_compact_prepared'](root/'originals', existing=True)
cp, anchor = pickle.loads((root/'trusted-bootstrap').read_bytes())
driver = d.FourArmDriverV3.open(root/'compact', p, cp)
wal = FourArmCheckpointWalV3.open(root/'checkpoint.wal', expected_anchor=anchor)
def checkpoint_sink(value):
    if wal(value) is not True:
        raise RuntimeError('unacknowledged WAL')
    name = root/('trusted-' + value.checkpoint_phase)
    with name.open('xb') as stream:
        pickle.dump((value, wal.snapshot().anchor), stream)
        stream.flush()
        os.fsync(stream.fileno())
    return True
if boundary == 'partial_arm':
    original = driver.accounts['combined'].debit_service
    def crash(**kw):
        original(**kw)
        os._exit(81)
    driver.accounts['combined'].debit_service = crash
else:
    original = driver._commit_known_plan
    def crash(plan):
        original(plan)
        os._exit(82)
    driver._commit_known_plan = crash
driver.step(checkpoint_sink=checkpoint_sink,
    commit_plan_sink=lambda plan: helpers['_fsync_compact_plan'](root/'trusted-plan', plan))
os._exit(99)
"""
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-W",
            "error",
            "-c",
            code,
            str(Path(__file__).resolve()),
            str(tmp_path),
            boundary,
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == (81 if boundary == "partial_arm" else 82), result.stderr
    retained, anchor = pickle.loads((tmp_path / "trusted-INTENT_COMMITTED").read_bytes())
    plan = (
        None
        if boundary == "partial_arm"
        else compact_commit_plan_from_document(json.loads((tmp_path / "trusted-plan").read_text()))
    )
    if plan is not None:
        with pytest.raises(SimInputError, match="independently retained"):
            FourArmDriverV3.open(directory, prepared, retained)
    restarted = FourArmDriverV3.open(directory, prepared, retained, expected_commit_plan=plan)
    try:
        with FourArmCheckpointWalV3.open(wal_path, expected_anchor=anchor) as wal:
            if boundary == "partial_arm":
                restarted.step(
                    checkpoint_sink=wal,
                    commit_plan_sink=lambda value: _fsync_compact_plan(tmp_path / "trusted-plan", value),
                )
            else:
                # Explicit completed ACK before any next operation.
                assert wal(restarted.checkpoint()) is True
            assert restarted.journal.snapshot().state["cursor"] == 1
            assert all(len(tuple(a.journal.native_events())) == 1 for a in restarted.accounts.values())
            checkpoint = restarted.checkpoint()
            assert wal.snapshot().checkpoint == checkpoint
        # No new operation may be inferred from an unanchored later head.
        request = {
            "operation": prepared.operations[1],
            "before": {a: asdict(p.journal.checkpoint()) for a, p in restarted.accounts.items()},
            "effects": restarted._effects(prepared.operations[1]),
        }
        restarted.journal.record_intent(request, at_ms=2, expected_checkpoint=restarted.journal.checkpoint())
    finally:
        restarted.close()
    with pytest.raises((SimInputError, driver_module.OptimisticConflict)):
        FourArmDriverV3.open(directory, prepared, checkpoint)


def test_compact_actual_preflight_profile_and_real_financial_consumers(tmp_path, inputs):
    """One original scheduled cost, not dense source or five-day financial replay."""
    prepared = preflight_four_arm_v3(
        inputs, sealed(inputs), account_profile=COMPACT_FINANCIAL_PROFILE, compact_storage=COMPACT_TEST_LIMITS
    )
    driver = FourArmDriverV3.create(tmp_path / "actual-compact", prepared)
    try:
        plans = []

        def retain(plan):
            plans.append(plan)
            return _fsync_compact_plan(tmp_path / "actual-plan", plan)

        with FourArmCheckpointWalV3.create(tmp_path / "actual.wal", driver.checkpoint()) as wal:
            driver.step(checkpoint_sink=wal, commit_plan_sink=retain)
            checkpoint = driver.checkpoint()
            assert wal.snapshot().checkpoint == checkpoint
        assert type(driver) is CompactFourArmDriverV3
        assert len(plans) == 1
        assert driver.journal.snapshot().state["history_refs"]["costs"]["count"] == 1
        operation = prepared.operations[0]
        assert operation["kind"] == "ATTEMPT"
        original = inputs.attempts[operation["index"]]
        amount = D(str(original.attempt.cost_usd))
        cold = driver.journal.lookup_history(
            "costs", original.cost_id, expected_checkpoint=driver.journal.checkpoint()
        )
        assert cold.value["amount"] == str(amount)
        for arm, account in driver.accounts.items():
            events = tuple(account.journal.native_events())
            if arm in original.consumer_arms:
                assert len(events) == 1 and events[0].payload == ("SERVICE", amount, operation["at"])
            else:
                assert events == ()
            assert decode_account_core(account.snapshot().state["account"])[
                0
            ].cash == inputs.initial_equity - (amount if arm in original.consumer_arms else D(0))
    finally:
        driver.close()


@pytest.mark.parametrize("ack", [False, None, 1])
def test_compact_short_plan_sink_non_ack_never_commits_driver(tmp_path, monkeypatch, ack):
    _short_driver_harness(monkeypatch)
    prepared = _short_compact_prepared(tmp_path / "originals")
    driver = FourArmDriverV3.create(tmp_path / "compact", prepared)
    try:
        with pytest.raises(SimInputError, match="ACK True"):
            driver.step(checkpoint_sink=lambda cp: True, commit_plan_sink=lambda plan: ack)
        assert driver.journal.snapshot().version == 1
        assert driver.journal.snapshot().state["pending"] is not None
        assert driver.journal.snapshot().state["history_refs"]["costs"]["count"] == 0
        assert all(a.journal.checkpoint().version == 1 for a in driver.accounts.values())
    finally:
        driver.close()


def test_compact_short_partial_quiet_cell_restart_no_duplicate_effect(tmp_path, monkeypatch):
    _short_driver_harness(monkeypatch)
    prepared = _short_compact_prepared(tmp_path / "originals")
    directory = tmp_path / "compact"
    driver = FourArmDriverV3.create(directory, prepared)
    saved = []

    def sink(cp):
        saved.append(cp)
        return True

    try:
        driver.step(maximum_operations=2, checkpoint_sink=sink, commit_plan_sink=lambda plan: True)
        original = driver.accounts["combined"].record_slots_batch

        def crash(**kwargs):
            original(**kwargs)
            raise RuntimeError("after owned native quiet cell")

        monkeypatch.setattr(driver.accounts["combined"], "record_slots_batch", crash)
        with pytest.raises(RuntimeError, match="quiet cell"):
            driver.step(checkpoint_sink=sink, commit_plan_sink=lambda plan: True)
        retained = saved[-1]
    finally:
        driver.close()
    driver = FourArmDriverV3.open(directory, prepared, retained)
    try:
        driver.step(checkpoint_sink=sink, commit_plan_sink=lambda plan: True)
        assert driver.journal.snapshot().state["history_refs"]["cells"]["count"] == 1
        assert all(a.journal.checkpoint().version == 3 for a in driver.accounts.values())
    finally:
        driver.close()


@pytest.mark.parametrize("status", ["QUIET", "UNAVAILABLE"])
def test_financial_short_partial_denominator_restart_no_duplicate_effect(tmp_path, monkeypatch, status):
    _short_driver_harness(monkeypatch)
    prepared = _short_compact_prepared(tmp_path / "originals")
    old = SimpleNamespace(**vars(prepared))
    old.account_profile = FINANCIAL_PROFILE
    old.identity_sha256 = digest(["SHORT_CONTRACT_NOT_HISTORICAL", FINANCIAL_PROFILE])
    old.compact_storage = ()
    if status == "UNAVAILABLE":
        old.cell_facts = {
            key: {
                **facts,
                "unavailable": set(ARMS)
                if key == prepared.inputs.minute_cells[0].key
                else set(facts["unavailable"]),
            }
            for key, facts in prepared.cell_facts.items()
        }

    directory = tmp_path / "financial"
    driver = FourArmDriverV3.create(directory, old)
    saved = []

    def sink(cp):
        saved.append(cp)
        return True

    try:
        driver.step(maximum_operations=2, checkpoint_sink=sink)
        original = driver.accounts["combined"].record_slots_batch

        def crash(**kwargs):
            original(**kwargs)
            raise RuntimeError(f"after owned native {status.lower()} cell")

        monkeypatch.setattr(driver.accounts["combined"], "record_slots_batch", crash)
        with pytest.raises(RuntimeError, match="owned native"):
            driver.step(checkpoint_sink=sink)
        retained = saved[-1]
    finally:
        driver.close()

    driver = FourArmDriverV3.open(directory, old, retained)
    try:
        driver.step(checkpoint_sink=sink)
        assert driver.journal.snapshot().state["cells"]["BTCUSDT:60000"]["arms"] == dict.fromkeys(
            ARMS, status
        )
        assert all(a.journal.checkpoint().version == 3 for a in driver.accounts.values())
    finally:
        driver.close()


def test_financial_sink_foreign_account_payload_is_refused_before_other_effects(tmp_path, monkeypatch):
    _short_driver_harness(monkeypatch)
    prepared = _short_compact_prepared(tmp_path / "originals")
    old = SimpleNamespace(**vars(prepared))
    old.account_profile = FINANCIAL_PROFILE
    old.identity_sha256 = digest(["SHORT_CONTRACT_NOT_HISTORICAL", FINANCIAL_PROFILE])
    old.compact_storage = ()
    driver = FourArmDriverV3.create(tmp_path / "financial", old)
    injected = False

    def sink(cp):
        nonlocal injected
        if cp.checkpoint_phase == "INTENT_COMMITTED" and cp.operation_cursor == 2 and not injected:
            injected = True
            driver.accounts["combined"].record_slots_batch(
                cells=(("BTCUSDT", 60000, "QUIET"),), source_sha256="b" * 64, at_ms=120000
            )
        return True

    try:
        driver.step(maximum_operations=2, checkpoint_sink=lambda cp: True)
        with pytest.raises(SimInputError, match="EXACT recorded pending operation"):
            driver.step(checkpoint_sink=sink)
        assert injected
        assert all(
            account.journal.checkpoint().version == (3 if arm == "combined" else 2)
            for arm, account in driver.accounts.items()
        )
    finally:
        driver.close()


def test_financial_sink_external_driver_advance_is_refused_before_account_effects(tmp_path, monkeypatch):
    _short_driver_harness(monkeypatch)
    prepared = _short_compact_prepared(tmp_path / "originals")
    old = SimpleNamespace(**vars(prepared))
    old.account_profile = FINANCIAL_PROFILE
    old.identity_sha256 = digest(["SHORT_CONTRACT_NOT_HISTORICAL", FINANCIAL_PROFILE])
    old.compact_storage = ()
    driver = FourArmDriverV3.create(tmp_path / "financial", old)
    advanced = False

    def sink(cp):
        nonlocal advanced
        if cp.checkpoint_phase == "INTENT_COMMITTED" and not advanced:
            advanced = True
            external = SimDeltaJournalV3.open(
                driver.journal.path,
                identity=driver.journal.identity,
                expected_checkpoint=driver.journal.checkpoint(),
            )
            try:
                snapshot = external.snapshot()
                external.append(
                    event_id="external-driver-advance",
                    payload={"kind": "FOREIGN_ADVANCE"},
                    outcome={"status": "RECORDED"},
                    state=snapshot.state,
                    expected_version=snapshot.version,
                    expected_state_hash=snapshot.state_hash,
                    expected_head_sha256=snapshot.head_hash,
                    at_ms=snapshot.last_clock_ms,
                )
            finally:
                external.close()
        return True

    try:
        with pytest.raises(SimInputError, match="driver advanced outside"):
            driver.step(checkpoint_sink=sink)
        assert advanced
        assert all(account.journal.checkpoint().version == 0 for account in driver.accounts.values())
    finally:
        driver.close()


def test_compact_short_missing_denominator_refuses_finish_before_account_effects(tmp_path, monkeypatch):
    _short_driver_harness(monkeypatch)
    prepared = _short_compact_prepared(tmp_path / "originals")
    prepared.operations = ({"kind": "FINISH", "at": 120001},)
    driver = FourArmDriverV3.create(tmp_path / "compact", prepared)
    try:
        with pytest.raises(SimInputError, match="missing original cells"):
            driver.step(checkpoint_sink=lambda cp: True, commit_plan_sink=lambda plan: True)
        assert all(a.journal.checkpoint().version == 0 for a in driver.accounts.values())
        assert driver.journal.snapshot().state["report"] is None
    finally:
        driver.close()


def test_compact_short_original_config_reference_unknown_fields_and_rehashed_mutation(tmp_path, monkeypatch):
    import sqlite3
    from contextlib import closing

    from adaptive_replay.sim_state_journal import _canonical, _hash

    _short_driver_harness(monkeypatch)
    prepared = _short_compact_prepared(tmp_path / "originals")
    directory = tmp_path / "compact"
    driver = FourArmDriverV3.create(directory, prepared)
    try:
        checkpoint = driver.checkpoint()
        descriptor = driver.journal.snapshot().state["account_config"]["combined"]
        with pytest.raises(SimInputError):
            driver._genesis_config(
                directory / "combined.sqlite3",
                descriptor | {"unknown": True},
                prepared=prepared,
                arm="combined",
            )
    finally:
        driver.close()
    path = directory / "combined.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        initial = json.loads(
            connection.execute("SELECT value FROM metadata WHERE key='initial_state_json'").fetchone()[0]
        )
        initial["config"]["expected_cost_ids"].append("fabricated")
        encoded = _canonical(initial)
        connection.execute("UPDATE metadata SET value=? WHERE key='initial_state_json'", (encoded,))
        connection.execute("UPDATE metadata SET value=? WHERE key='initial_state_hash'", (_hash(encoded),))
    with pytest.raises(SimInputError, match="genesis config"):
        FourArmDriverV3.open(directory, prepared, checkpoint)


def test_compact_profile_requires_explicit_resource_object_old_profile_refuses_it():
    with pytest.raises(SimInputError, match="typed compact"):
        preflight_four_arm_v3(None, None, account_profile=COMPACT_FINANCIAL_PROFILE)
    with pytest.raises(SimInputError, match="explicit compact"):
        preflight_four_arm_v3(
            None, None, account_profile=FINANCIAL_PROFILE, compact_storage=COMPACT_TEST_LIMITS
        )


def test_compact_short_preintent_lost_response_recovers_only_exact_intent(tmp_path, monkeypatch):
    _short_driver_harness(monkeypatch)
    prepared = _short_compact_prepared(tmp_path / "originals")
    directory = tmp_path / "compact"
    driver = FourArmDriverV3.create(directory, prepared)
    saved = []

    def sink(cp):
        saved.append(cp)
        return True

    original = driver.journal.record_intent

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("durable intent response lost")

    monkeypatch.setattr(driver.journal, "record_intent", crash)
    try:
        with pytest.raises(RuntimeError, match="intent response lost"):
            driver.step(checkpoint_sink=sink, commit_plan_sink=lambda plan: True)
        retained = saved[-1]
        assert retained.checkpoint_phase == "PREPARED_INTENT"
        assert all(a.journal.checkpoint().version == 0 for a in driver.accounts.values())
    finally:
        driver.close()
    driver = FourArmDriverV3.open(directory, prepared, retained)
    try:
        driver.step(checkpoint_sink=sink, commit_plan_sink=lambda plan: True)
        assert driver.journal.snapshot().state["cursor"] == 1
        assert all(len(tuple(a.journal.native_events())) == 1 for a in driver.accounts.values())
    finally:
        driver.close()


def test_compact_short_plan_callback_unknown_writer_never_rebases_live_head(tmp_path, monkeypatch):
    from adaptive_replay.compact_four_arm_driver_journal_v3 import CompactFourArmDriverJournalV3

    _short_driver_harness(monkeypatch)
    prepared = _short_compact_prepared(tmp_path / "originals")
    driver = FourArmDriverV3.create(tmp_path / "compact", prepared)
    held = []

    def foreign(plan):
        held.append(plan.expected_before)
        with CompactFourArmDriverJournalV3.open(
            driver.journal.path,
            identity=driver.journal.identity,
            limits=driver.journal.limits,
            expected_checkpoint=plan.expected_before,
        ) as writer:
            writer.commit_operation(
                operation=plan.expected_payload["operation"],
                pending_sha256=plan.expected_payload["pending_sha256"],
                account_checkpoints=plan.expected_payload["account_checkpoints"],
                cold_records=plan.expected_cold_records,
                at_ms=plan.expected_at_ms,
                expected_checkpoint=plan.expected_before,
            )
        return True

    try:
        with pytest.raises((SimInputError, driver_module.OptimisticConflict)):
            driver.step(checkpoint_sink=lambda cp: True, commit_plan_sink=foreign)
        assert driver._driver_checkpoint == held[-1]
    finally:
        driver.close()
