"""Durability/identity contract tests for the isolated V3 research journal."""

import sqlite3
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
    _load,
)
from adaptive_replay.hypothesis_v3 import (
    CreationAssessment,
    EntryQuote,
    HypothesisObservation,
    HypothesisPlan,
    HypothesisPolicy,
    creation_input_sha256,
)
from adaptive_replay.scenarios import MINUTE, ScenarioEvidence, ScenarioObservation

CUT = 86_400_000
SYMBOL = "BTCUSDT"


def _source(candle):
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


def _plan(*, policy=None, side=Side.LONG):
    sign = 1 if side is Side.LONG else -1
    anchor = Candle(SYMBOL, "1m", CUT - MINUTE, CUT - 1, 100, 101, 99, 100, 10)
    parent = SleeveIntent(
        "trend_breakout_v1",
        SYMBOL,
        side,
        CUT - 1,
        CUT,
        CUT + MINUTE - 1,
        100,
        0.7,
        500,
        ExitPlan(100 - 2 * sign, 100 + 5 * sign, 5 * MINUTE, 100 + 3 * sign, 1),
        (("native_marker", "unchanged"),),
    )
    policy = policy or HypothesisPolicy(CUT - 1, 5 * MINUTE, "quotes", 5_000, "TEST_FIXTURE", True)
    evidence = (_source(anchor),)
    return HypothesisPlan(
        parent,
        "TECHNICAL",
        "BULL" if side is Side.LONG else "BEAR",
        CUT,
        CUT + 10_001,
        "a" * 64,
        "b" * 64,
        evidence,
        anchor,
        (("MARKET", "bars"),),
        policy,
    )


def _observation(*, side=Side.LONG, open_ms=CUT, close=None):
    sign = 1 if side is Side.LONG else -1
    close = (100 + 0.5 * sign) if close is None else close
    candle = Candle(
        SYMBOL, "1m", open_ms, open_ms + MINUTE - 1, 100, max(101, close), min(99, close), close, 10
    )
    observed = open_ms + MINUTE + 10_020
    quote = EntryQuote(
        "quotes",
        SYMBOL,
        100.49 if sign > 0 else 99.5,
        100.5 if sign > 0 else 99.51,
        observed - 8,
        observed - 7,
        observed - 6,
        5_000,
        "TEST_FIXTURE",
    )
    return HypothesisObservation(ScenarioObservation(candle, observed, (_source(candle),)), quote)


def _context_plan(policy):
    base = _plan(policy=policy)
    extra = tuple(
        sorted(
            tuple(base.creation_evidence)
            + tuple(
                ScenarioEvidence(name, kind, SYMBOL, "d" * 64, CUT - 1, CUT, CUT, 5 * MINUTE)
                for name, kind in (("macro", "MACRO"), ("news", "NEWS"))
            ),
            key=lambda evidence: (evidence.kind, evidence.source_id),
        )
    )
    context = creation_input_sha256(base.source_set_sha256, base.context_sha256, base.anchor, extra)
    assessment = CreationAssessment(
        context,
        "c" * 64,
        "e" * 64,
        base.template.side.value,
        CUT + 10_002,
        CUT + 10_004,
        CUT + 10_005,
        "TEST_FIXTURE",
    )
    return HypothesisPlan(
        base.template,
        "CONTEXT_PROPOSAL",
        base.regime,
        base.origin_cut_ms,
        CUT + 10_005,
        base.source_set_sha256,
        base.context_sha256,
        extra,
        base.anchor,
        tuple((item.kind, item.source_id) for item in extra),
        policy,
        assessment,
    )


def _seal(*, arms=None, maximum_parents=4):
    arms = arms or (
        JournalArmV3(
            "control", HypothesisPolicy(CUT - 1, 5 * MINUTE, "quotes", 5_000, "TEST_FIXTURE", True), "e" * 64
        ),
        JournalArmV3(
            "treatment", HypothesisPolicy(CUT - 1, 5 * MINUTE, "quotes", 5_000, "TEST_FIXTURE", False)
        ),
    )
    return JournalSealV3("v3-journal-test", CUT - 1, "a" * 64, arms, maximum_parents)


def _path(tmp_path):
    return tmp_path / "hypothesis.research.sqlite3"


def _batch(observation, seal):
    return MatchedObservationV3(
        observation,
        tuple(
            ArmReviewReceiptV3(arm.arm_id, observation.market.observed_ms, observation.market.observed_ms)
            for arm in seal.arms
        ),
    )


def _reopen(path, seal, journal):
    return HypothesisJournalV3.open(path, seal, minimum_checkpoint=journal.snapshot().checkpoint)


def test_pre_cut_seal_allows_actual_post_cut_candidate_without_backdating(tmp_path):
    seal = _seal()
    path = _path(tmp_path)
    journal = HypothesisJournalV3.create(path, seal)
    first, second = _plan(policy=seal.arms[0].policy), _plan(policy=seal.arms[1].policy)
    assert first.created_ms > first.origin_cut_ms > seal.sealed_ms
    assert journal.register("control", first).new_event
    assert journal.register("treatment", second).new_event
    receipt = journal.append(first.template.intent_id, _batch(_observation(), seal))
    # First trigger and full receipts survive reopening; V3's exact fold replays.
    reopened = _reopen(path, seal, journal)
    snapshot = reopened.snapshot()
    assert snapshot.event_count == 4
    assert snapshot.hypotheses[0].observations == (_observation(),)
    assert snapshot.hypotheses[1].observations == (_observation(),)
    assert all(
        item.new_event is False
        for item in reopened.append(first.template.intent_id, _batch(_observation(), seal))
    )
    assert all(item.evaluation.state == "CONSUMED" for item in receipt)
    assert receipt[0].evaluation.reason == "REVIEW_MISSING_DEFER"
    assert receipt[0].evaluation.coverage == "UNAVAILABLE"
    assert receipt[0].evaluation.candidate is None
    assert receipt[1].evaluation.coverage == "AVAILABLE"
    assert receipt[1].evaluation.candidate is not None


def test_late_arm_or_changed_plan_cannot_be_added_after_first_observation(tmp_path):
    seal = _seal()
    journal = HypothesisJournalV3.create(_path(tmp_path), seal)
    control = _plan(policy=seal.arms[0].policy)
    treatment = _plan(policy=seal.arms[1].policy)
    journal.register("control", control)
    journal.register("treatment", treatment)
    journal.append(control.template.intent_id, _batch(_observation(), seal))
    changed_parent = replace(treatment, context_sha256="d" * 64)
    with pytest.raises(ValueError, match="cannot be resealed"):
        journal.register("treatment", changed_parent)
    with pytest.raises(ValueError):
        journal.register("unknown", control)


def test_exact_duplicate_is_idempotent_but_conflicting_quote_receipt_fails(tmp_path):
    seal = _seal()
    journal = HypothesisJournalV3.create(_path(tmp_path), seal)
    plans = [_plan(policy=arm.policy) for arm in seal.arms]
    for arm, plan in zip(seal.arms, plans, strict=True):
        journal.register(arm.arm_id, plan)
    obs = _observation()
    first = journal.append(plans[0].template.intent_id, _batch(obs, seal))
    redelivery = journal.append(plans[0].template.intent_id, _batch(obs, seal))
    assert [(item.sequence, item.new_event) for item in redelivery] == [
        (item.sequence, False) for item in first
    ]
    conflict = replace(obs, quote=replace(obs.quote, bid=obs.quote.bid - 0.01))
    with pytest.raises(ValueError, match="conflicting V3 redelivery"):
        journal.append(plans[0].template.intent_id, _batch(conflict, seal))


def test_typed_context_creation_assessment_and_original_exit_plan_round_trip(tmp_path):
    seal = _seal()
    journal = HypothesisJournalV3.create(_path(tmp_path), seal)
    plans = [_context_plan(arm.policy) for arm in seal.arms]
    for arm, plan in zip(seal.arms, plans, strict=True):
        journal.register(arm.arm_id, plan)
    reopened = _reopen(_path(tmp_path), seal, journal).snapshot()
    for item in reopened.hypotheses:
        assert type(item.plan.creation_assessment) is CreationAssessment
        assert item.plan.creation_assessment.input_sha256 == item.plan.creation_input_sha256
        assert item.plan.template.exit_plan == plans[0].template.exit_plan


def test_missing_caller_attested_market_receipt_is_durable_unavailable_not_imputed(tmp_path):
    seal = _seal()
    journal = HypothesisJournalV3.create(_path(tmp_path), seal)
    plans = [_plan(policy=arm.policy) for arm in seal.arms]
    for arm, plan in zip(seal.arms, plans, strict=True):
        journal.register(arm.arm_id, plan)
    observation = _observation()
    missing = replace(observation, market=replace(observation.market, sources=()))
    receipts = journal.append(plans[0].template.intent_id, _batch(missing, seal))
    assert all(item.evaluation.coverage == "UNAVAILABLE" for item in receipts)
    assert all(item.evaluation.candidate is None for item in receipts)
    reopened = _reopen(_path(tmp_path), seal, journal).snapshot()
    assert all(item.observations == (missing,) for item in reopened.hypotheses)


def test_v3_seal_rejects_policy_created_after_seal_and_non_v3_policy(tmp_path):
    seal = _seal()
    HypothesisJournalV3.create(_path(tmp_path), seal)
    with pytest.raises(ValueError, match="typed frozen V3"):
        JournalArmV3("wrong", object())
    too_late = JournalArmV3(
        "late", HypothesisPolicy(CUT, 5 * MINUTE, "quotes", 5_000, "TEST_FIXTURE"), "e" * 64
    )
    with pytest.raises(ValueError, match="pre-cut seal"):
        replace(seal, arms=(too_late,))


def test_unknown_seal_and_corrupt_database_are_not_repaired_or_migrated(tmp_path):
    seal = _seal()
    path = _path(tmp_path)
    journal = HypothesisJournalV3.create(path, seal)
    checkpoint = journal.snapshot().checkpoint
    wrong = replace(seal, source_set_sha256="c" * 64)
    with pytest.raises(ValueError, match="frozen V3"):
        HypothesisJournalV3.open(path, wrong, minimum_checkpoint=checkpoint)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("UPDATE meta SET head_sha256=? WHERE id=1", ("f" * 64,))
    with pytest.raises(ValueError, match="head or truncation"):
        HypothesisJournalV3.open(path, seal, minimum_checkpoint=checkpoint)


def test_duplicate_json_keys_and_noncanonical_bytes_are_rejected():
    with pytest.raises(ValueError):
        _load('{"policy":"one","policy":"two"}')
    with pytest.raises(ValueError):
        _load('{ "policy":"one" }')
