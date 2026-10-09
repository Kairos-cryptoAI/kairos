"""Fault and concurrency tests for the V3 matched research journal."""

from __future__ import annotations

import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_journal_v3 import (
    ArmReviewReceiptV3,
    HypothesisJournalV3,
    JournalArmV3,
    JournalSealV3,
    MatchedObservationV3,
)
from adaptive_replay.hypothesis_v3 import (
    EntryQuote,
    HypothesisObservation,
    HypothesisPlan,
    HypothesisPolicy,
)
from adaptive_replay.scenarios import MINUTE, ScenarioEvidence, ScenarioObservation, ScenarioReview

ORIGIN = 86_400_000
SYMBOL = "BTCUSDT"
MODEL_CONFIG_A = "1" * 64
MODEL_CONFIG_B = "2" * 64


def _source(candle: Candle) -> ScenarioEvidence:
    return ScenarioEvidence(
        "bars",
        "MARKET",
        SYMBOL,
        digest(candle_payload(candle)),
        candle.close_time_ms,
        candle.close_time_ms + 10_001,
        candle.close_time_ms + 10_001,
        600_000,
    )


def _policy(*, require_review: bool, maximum_quote_age_ms: int = 5_000) -> HypothesisPolicy:
    return HypothesisPolicy(
        ORIGIN - 1,
        5 * MINUTE,
        "quotes",
        maximum_quote_age_ms,
        "TEST_FIXTURE",
        require_review,
    )


def _plan(policy: HypothesisPolicy, *, side: Side = Side.LONG) -> HypothesisPlan:
    sign = 1 if side is Side.LONG else -1
    anchor = Candle(SYMBOL, "1m", ORIGIN - MINUTE, ORIGIN - 1, 100, 101, 99, 100, 10)
    parent = SleeveIntent(
        "trend_breakout_v1",
        SYMBOL,
        side,
        ORIGIN - 1,
        ORIGIN,
        ORIGIN + MINUTE - 1,
        100,
        0.7,
        500,
        ExitPlan(100 - 2 * sign, 100 + 5 * sign, 5 * MINUTE, 100 + 3 * sign, 1),
        (("native_marker", "unchanged"),),
    )
    return HypothesisPlan(
        parent,
        "TECHNICAL",
        "BULL" if side is Side.LONG else "BEAR",
        ORIGIN,
        ORIGIN + 10_001,
        "a" * 64,
        "b" * 64,
        (_source(anchor),),
        anchor,
        (("MARKET", "bars"),),
        policy,
    )


def _seal(arms: tuple[JournalArmV3, ...], *, maximum_parents: int = 4) -> JournalSealV3:
    return JournalSealV3("v3-journal-fault-test", ORIGIN - 1, "a" * 64, arms, maximum_parents)


def _shared_observation(*, ttl_ms: int = 5_000) -> HypothesisObservation:
    candle = Candle(SYMBOL, "1m", ORIGIN, ORIGIN + MINUTE - 1, 100, 101, 99, 100.5, 10)
    shared_ms = candle.close_time_ms + 10_020
    quote = EntryQuote(
        "quotes", SYMBOL, 100.49, 100.5, shared_ms - 8, shared_ms - 7, shared_ms - 6, ttl_ms, "TEST_FIXTURE"
    )
    return HypothesisObservation(ScenarioObservation(candle, shared_ms, (_source(candle),)), quote)


def _review(
    plan: HypothesisPlan,
    observation: HypothesisObservation,
    completed_ms: int,
    tag: str,
) -> ScenarioReview:
    return ScenarioReview(
        plan.scenario_id,
        plan.template.side,
        "ALLOW",
        observation.context_sha256,
        completed_ms,
        tag * 64,
    )


def _reviewed_receipt(
    arm_id: str,
    plan: HypothesisPlan,
    observation: HypothesisObservation,
    *,
    delay_ms: int,
    model_config_sha256: str,
    tag: str,
) -> ArmReviewReceiptV3:
    shared_ms = observation.market.observed_ms
    requested_ms = shared_ms + 10
    completed_ms = shared_ms + delay_ms
    captured_ms = completed_ms + 5
    decision_ms = captured_ms + 5
    return ArmReviewReceiptV3(
        arm_id,
        decision_ms,
        shared_ms,
        _review(plan, observation, completed_ms, tag),
        model_config_sha256,
        requested_ms,
        captured_ms,
    )


def _enroll(
    journal: HypothesisJournalV3,
    seal: JournalSealV3,
    plans: dict[str, HypothesisPlan],
) -> str:
    for arm in seal.arms:
        journal.register(arm.arm_id, plans[arm.arm_id])
    return plans[seal.arms[0].arm_id].template.intent_id


def test_distinct_reviewed_policies_keep_arm_bound_scenario_and_config_identity(tmp_path):
    arms = (
        JournalArmV3("review-a", _policy(require_review=True), MODEL_CONFIG_A),
        JournalArmV3(
            "review-b",
            _policy(require_review=True, maximum_quote_age_ms=4_000),
            MODEL_CONFIG_B,
        ),
    )
    seal = _seal(arms)
    plans = {arm.arm_id: _plan(arm.policy) for arm in arms}
    journal = HypothesisJournalV3.create(tmp_path / "distinct.research.sqlite3", seal)
    parent_id = _enroll(journal, seal, plans)
    shared = _shared_observation()
    receipts = (
        _reviewed_receipt(
            "review-a", plans["review-a"], shared, delay_ms=50, model_config_sha256=MODEL_CONFIG_A, tag="3"
        ),
        _reviewed_receipt(
            "review-b", plans["review-b"], shared, delay_ms=75, model_config_sha256=MODEL_CONFIG_B, tag="4"
        ),
    )

    appended = journal.append(parent_id, MatchedObservationV3(shared, receipts))
    snapshot = journal.snapshot()
    by_arm = {item.arm_id: item for item in snapshot.hypotheses}

    assert plans["review-a"].policy.sha256 != plans["review-b"].policy.sha256
    assert plans["review-a"].scenario_id != plans["review-b"].scenario_id
    assert [item.arm_id for item in appended] == ["review-a", "review-b"]
    assert by_arm["review-a"].review_receipts[0].model_config_sha256 == MODEL_CONFIG_A
    assert by_arm["review-b"].review_receipts[0].model_config_sha256 == MODEL_CONFIG_B
    assert by_arm["review-a"].observations[0].market.review.scenario_id == plans["review-a"].scenario_id
    assert by_arm["review-b"].observations[0].market.review.scenario_id == plans["review-b"].scenario_id
    assert by_arm["review-a"].observations[0].market.observed_ms == receipts[0].observed_ms
    assert by_arm["review-b"].observations[0].market.observed_ms == receipts[1].observed_ms
    assert all(item.evaluation.coverage == "AVAILABLE" for item in appended)
    assert all(item.evaluation.candidate is not None for item in appended)


def test_quote_ttl_uses_actual_review_clock_and_preserves_fast_baseline_candidate(tmp_path):
    arms = (
        JournalArmV3("baseline", _policy(require_review=False)),
        JournalArmV3("review-fast", _policy(require_review=True), MODEL_CONFIG_A),
        JournalArmV3(
            "review-slow",
            _policy(require_review=True, maximum_quote_age_ms=4_000),
            MODEL_CONFIG_B,
        ),
    )
    seal = _seal(arms)
    plans = {arm.arm_id: _plan(arm.policy) for arm in arms}
    journal = HypothesisJournalV3.create(tmp_path / "latency.research.sqlite3", seal)
    parent_id = _enroll(journal, seal, plans)
    shared = _shared_observation(ttl_ms=1_000)
    baseline = ArmReviewReceiptV3("baseline", shared.market.observed_ms, shared.market.observed_ms)
    fast = _reviewed_receipt(
        "review-fast", plans["review-fast"], shared, delay_ms=100, model_config_sha256=MODEL_CONFIG_A, tag="5"
    )
    slow = _reviewed_receipt(
        "review-slow",
        plans["review-slow"],
        shared,
        delay_ms=2_000,
        model_config_sha256=MODEL_CONFIG_B,
        tag="6",
    )
    journal.append(parent_id, MatchedObservationV3(shared, (baseline, fast, slow)))
    by_arm = {item.arm_id: item for item in journal.snapshot().hypotheses}
    evaluations = {arm: item.receipts[-1].evaluation for arm, item in by_arm.items()}

    assert baseline.observed_ms == shared.market.observed_ms
    assert len(by_arm["baseline"].review_receipts) == 1
    assert by_arm["baseline"].review_receipts[0].review is None
    assert evaluations["baseline"].candidate is not None
    assert evaluations["review-fast"].candidate is not None
    assert evaluations["review-slow"].candidate is None
    assert evaluations["review-slow"].reason == "ENTRY_QUOTE_IDENTITY_CLOCK_OR_FRESHNESS_CONFLICT"
    assert evaluations["review-slow"].coverage == "UNAVAILABLE"
    assert slow.observed_ms > shared.quote.event_ms + shared.quote.ttl_ms


def test_missing_review_is_a_durable_completion_and_cannot_be_late_merged(tmp_path):
    arms = (
        JournalArmV3("review-a", _policy(require_review=True), MODEL_CONFIG_A),
        JournalArmV3("review-b", _policy(require_review=True), MODEL_CONFIG_B),
    )
    seal = _seal(arms)
    plans = {arm.arm_id: _plan(arm.policy) for arm in arms}
    journal = HypothesisJournalV3.create(tmp_path / "missing-review.research.sqlite3", seal)
    parent_id = _enroll(journal, seal, plans)
    shared = _shared_observation()
    missing = ArmReviewReceiptV3("review-b", shared.market.observed_ms + 10, shared.market.observed_ms)
    first_batch = MatchedObservationV3(
        shared,
        (
            _reviewed_receipt(
                "review-a",
                plans["review-a"],
                shared,
                delay_ms=50,
                model_config_sha256=MODEL_CONFIG_A,
                tag="7",
            ),
            missing,
        ),
    )
    journal.append(parent_id, first_batch)
    late_review = _reviewed_receipt(
        "review-b", plans["review-b"], shared, delay_ms=100, model_config_sha256=MODEL_CONFIG_B, tag="8"
    )

    with pytest.raises(ValueError, match="conflicting V3 redelivery"):
        journal.append(parent_id, MatchedObservationV3(shared, (first_batch.arms[0], late_review)))

    reopened = HypothesisJournalV3.open(journal.path, seal, minimum_checkpoint=journal.snapshot().checkpoint)
    stored = {item.arm_id: item for item in reopened.snapshot().hypotheses}
    assert stored["review-b"].review_receipts[0].review is None
    assert stored["review-b"].observations[0].market.review is None


def test_failure_after_first_arm_row_rolls_back_entire_matched_append(tmp_path, monkeypatch):
    arms = (
        JournalArmV3("baseline", _policy(require_review=False)),
        JournalArmV3("review", _policy(require_review=True), MODEL_CONFIG_A),
    )
    seal = _seal(arms)
    plans = {arm.arm_id: _plan(arm.policy) for arm in arms}
    journal = HypothesisJournalV3.create(tmp_path / "rollback.research.sqlite3", seal)
    parent_id = _enroll(journal, seal, plans)
    before = journal.snapshot()
    shared = _shared_observation()
    batch = MatchedObservationV3(
        shared,
        (
            ArmReviewReceiptV3("baseline", shared.market.observed_ms, shared.market.observed_ms),
            _reviewed_receipt(
                "review", plans["review"], shared, delay_ms=50, model_config_sha256=MODEL_CONFIG_A, tag="9"
            ),
        ),
    )
    original = journal._append_event
    inserted = []

    def fail_after_first(connection, snapshot, arm_id, plan, observation, evaluation, review_receipt=None):
        result = original(connection, snapshot, arm_id, plan, observation, evaluation, review_receipt)
        inserted.append(arm_id)
        if len(inserted) == 1:
            raise RuntimeError("injected failure after first arm row")
        return result

    monkeypatch.setattr(journal, "_append_event", fail_after_first)
    with pytest.raises(RuntimeError, match="injected failure"):
        journal.append(parent_id, batch)

    after = journal.snapshot()
    with closing(sqlite3.connect(journal.path)) as connection:
        observation_rows = connection.execute(
            "SELECT COUNT(*) FROM events WHERE observation_json IS NOT NULL"
        ).fetchone()[0]
    assert inserted == ["baseline"]
    assert observation_rows == 0
    assert after.event_count == before.event_count
    assert after.checkpoint == before.checkpoint


@pytest.mark.parametrize("same_instance", [False, True])
def test_sqlite_writers_serialize_exact_duplicate_atomically(tmp_path, same_instance):
    arms = (
        JournalArmV3("baseline", _policy(require_review=False)),
        JournalArmV3("review", _policy(require_review=True), MODEL_CONFIG_A),
    )
    seal = _seal(arms)
    plans = {arm.arm_id: _plan(arm.policy) for arm in arms}
    path = tmp_path / "concurrent.research.sqlite3"
    first = HypothesisJournalV3.create(path, seal)
    parent_id = _enroll(first, seal, plans)
    second = (
        first
        if same_instance
        else HypothesisJournalV3.open(path, seal, minimum_checkpoint=first.snapshot().checkpoint)
    )
    shared = _shared_observation()
    batch = MatchedObservationV3(
        shared,
        (
            ArmReviewReceiptV3("baseline", shared.market.observed_ms, shared.market.observed_ms),
            _reviewed_receipt(
                "review", plans["review"], shared, delay_ms=50, model_config_sha256=MODEL_CONFIG_A, tag="a"
            ),
        ),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda writer: writer.append(parent_id, batch), (first, second)))

    assert sorted(tuple(item.new_event for item in outcome) for outcome in outcomes) == [
        (False, False),
        (True, True),
    ]
    snapshot = first.snapshot()
    assert snapshot.event_count == len(arms) * 2
    assert all(len(item.observations) == 1 for item in snapshot.hypotheses)
    appended_sequences = [receipt.sequence for item in snapshot.hypotheses for receipt in item.receipts[1:]]
    assert sorted(appended_sequences) == [3, 4]
    assert first._minimum_checkpoint == snapshot.checkpoint


def test_lost_response_reopen_and_exact_redelivery_returns_original_receipts(tmp_path):
    arms = (
        JournalArmV3("baseline", _policy(require_review=False)),
        JournalArmV3("review", _policy(require_review=True), MODEL_CONFIG_A),
    )
    seal = _seal(arms)
    plans = {arm.arm_id: _plan(arm.policy) for arm in arms}
    path = tmp_path / "lost-response.research.sqlite3"
    journal = HypothesisJournalV3.create(path, seal)
    parent_id = _enroll(journal, seal, plans)
    shared = _shared_observation()
    batch = MatchedObservationV3(
        shared,
        (
            ArmReviewReceiptV3("baseline", shared.market.observed_ms, shared.market.observed_ms),
            _reviewed_receipt(
                "review", plans["review"], shared, delay_ms=50, model_config_sha256=MODEL_CONFIG_A, tag="b"
            ),
        ),
    )
    original_receipts = journal.append(parent_id, batch)  # simulate response loss after commit
    checkpoint = journal.snapshot().checkpoint
    reopened = HypothesisJournalV3.open(path, seal, minimum_checkpoint=checkpoint)

    redelivery = reopened.append(parent_id, batch)

    assert [(r.sequence, r.chain_sha256, r.new_event) for r in redelivery] == [
        (r.sequence, r.chain_sha256, False) for r in original_receipts
    ]
    assert reopened.snapshot().checkpoint == checkpoint


def test_reopen_rejects_wrong_checkpoint_and_tail_rollback(tmp_path):
    arms = (
        JournalArmV3("baseline", _policy(require_review=False)),
        JournalArmV3("review", _policy(require_review=True), MODEL_CONFIG_A),
    )
    seal = _seal(arms)
    plans = {arm.arm_id: _plan(arm.policy) for arm in arms}
    path = tmp_path / "checkpoint.research.sqlite3"
    journal = HypothesisJournalV3.create(path, seal)
    parent_id = _enroll(journal, seal, plans)
    before_append = journal.snapshot().checkpoint
    shared = _shared_observation()
    batch = MatchedObservationV3(
        shared,
        (
            ArmReviewReceiptV3("baseline", shared.market.observed_ms, shared.market.observed_ms),
            _reviewed_receipt(
                "review", plans["review"], shared, delay_ms=50, model_config_sha256=MODEL_CONFIG_A, tag="c"
            ),
        ),
    )
    before_path = tmp_path / "before-tail.research.sqlite3"
    shutil.copy2(path, before_path)
    journal.append(parent_id, batch)
    after_append = journal.snapshot().checkpoint

    wrong_checkpoint = replace(after_append, head_sha256="f" * 64)
    with pytest.raises(ValueError, match="rolled back or diverged"):
        HypothesisJournalV3.open(path, seal, minimum_checkpoint=wrong_checkpoint)
    with pytest.raises(ValueError, match="rolled back or diverged"):
        HypothesisJournalV3.open(before_path, seal, minimum_checkpoint=after_append)
    # An older checkpoint can validate a longer intact suffix; the external
    # caller is responsible for retaining the strongest checkpoint it has.
    reopened_from_prior = HypothesisJournalV3.open(path, seal, minimum_checkpoint=before_append)
    assert reopened_from_prior.snapshot().event_count > before_append.sequence


def test_peer_plan_protection_and_parent_capacity_are_enforced(tmp_path):
    arms = (
        JournalArmV3("baseline", _policy(require_review=False)),
        JournalArmV3("review", _policy(require_review=True), MODEL_CONFIG_A),
    )
    seal = _seal(arms, maximum_parents=4)
    plans = {arm.arm_id: _plan(arm.policy) for arm in arms}
    journal = HypothesisJournalV3.create(tmp_path / "structure.research.sqlite3", seal)
    journal.register("baseline", plans["baseline"])

    changed_peer = replace(plans["review"], context_sha256="d" * 64)
    with pytest.raises(ValueError, match="exact plan|full ExitPlan"):
        journal.register("review", changed_peer)
    journal.register("review", plans["review"])

    capacity_seal = _seal(arms, maximum_parents=1)
    capacity_journal = HypothesisJournalV3.create(tmp_path / "capacity.research.sqlite3", capacity_seal)
    capacity_journal.register("baseline", plans["baseline"])
    capacity_journal.register("review", plans["review"])
    other = _plan(arms[0].policy, side=Side.SHORT)
    with pytest.raises(ValueError, match="capacity"):
        capacity_journal.register("baseline", other)


@pytest.mark.parametrize("defect", ["model", "baseline-delay", "baseline-review", "roster"])
def test_matched_batch_cannot_change_sealed_roles_or_model_identity(tmp_path, defect):
    arms = (
        JournalArmV3("baseline", _policy(require_review=False)),
        JournalArmV3("review", _policy(require_review=True), MODEL_CONFIG_A),
    )
    seal = _seal(arms)
    plans = {arm.arm_id: _plan(arm.policy) for arm in arms}
    journal = HypothesisJournalV3.create(tmp_path / "bad-batch.research.sqlite3", seal)
    parent_id = _enroll(journal, seal, plans)
    shared = _shared_observation()
    baseline = ArmReviewReceiptV3("baseline", shared.market.observed_ms, shared.market.observed_ms)
    reviewed = _reviewed_receipt(
        "review", plans["review"], shared, delay_ms=50, model_config_sha256=MODEL_CONFIG_A, tag="d"
    )
    if defect == "model":
        reviewed = replace(reviewed, model_config_sha256=MODEL_CONFIG_B)
    elif defect == "baseline-delay":
        baseline = replace(baseline, observed_ms=baseline.observed_ms + 1)
    elif defect == "baseline-review":
        baseline = replace(reviewed, arm_id="baseline")
    completions = (baseline,) if defect == "roster" else (baseline, reviewed)
    before = journal.snapshot().checkpoint
    with pytest.raises(ValueError, match="configuration|no-review|roster"):
        journal.append(parent_id, MatchedObservationV3(shared, completions))
    assert journal.snapshot().checkpoint == before


def test_later_shared_source_or_quote_and_pre_input_request_are_rejected():
    shared = _shared_observation()
    baseline = ArmReviewReceiptV3("baseline", shared.market.observed_ms, shared.market.observed_ms)
    source = replace(shared.market.sources[0], captured_ms=shared.market.observed_ms + 1)
    with pytest.raises(ValueError, match="later captured"):
        MatchedObservationV3(replace(shared, market=replace(shared.market, sources=(source,))), (baseline,))
    quote = replace(shared.quote, captured_ms=shared.market.observed_ms + 1)
    with pytest.raises(ValueError, match="after shared availability"):
        MatchedObservationV3(replace(shared, quote=quote), (baseline,))
    reviewed = _reviewed_receipt(
        "review",
        _plan(_policy(require_review=True)),
        shared,
        delay_ms=50,
        model_config_sha256=MODEL_CONFIG_A,
        tag="e",
    )
    reviewed = replace(reviewed, actual_requested_ms=shared.market.observed_ms - 1)
    with pytest.raises(ValueError, match="request cannot predate"):
        MatchedObservationV3(shared, (reviewed,))
