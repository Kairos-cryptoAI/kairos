"""Synthetic V3 clock-contract tests, not source/model/economic completion."""

from dataclasses import asdict, replace

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_v2 import HypothesisPlan as V2Plan
from adaptive_replay.hypothesis_v2 import HypothesisPolicy as V2Policy
from adaptive_replay.hypothesis_v2 import evaluate_hypothesis as evaluate_v2
from adaptive_replay.hypothesis_v3 import (
    POLICY_ID,
    CreationAssessment,
    EntryQuote,
    HypothesisEvaluation,
    HypothesisObservation,
    HypothesisPlan,
    HypothesisPolicy,
    creation_input_sha256,
    evaluate_hypothesis,
)
from adaptive_replay.scenarios import MINUTE, ScenarioEvidence, ScenarioObservation, ScenarioReview

CUT = 86_400_000
SYMBOL = "BTCUSDT"


def bar(open_ms, close=100.0, *, low=99.0, high=101.0):
    return Candle(
        SYMBOL, "1m", open_ms, open_ms + MINUTE - 1, 100, max(high, close), min(low, close), close, 10
    )


def source(candle, *, source_id="bars", capture_delay=10_000, ttl=600_000):
    return ScenarioEvidence(
        source_id,
        "MARKET",
        SYMBOL,
        digest(candle_payload(candle)),
        candle.close_time_ms,
        candle.close_time_ms + 1 + capture_delay,
        candle.close_time_ms + 1 + capture_delay,
        ttl,
    )


def plan(*, side=Side.LONG, review=False, lifetime=5 * MINUTE, created=CUT + 10_000, origin="TECHNICAL"):
    sign = 1 if side is Side.LONG else -1
    anchor = bar(CUT - MINUTE)
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
    policy = HypothesisPolicy(CUT - 1, lifetime, "quotes", 5_000, "TEST_FIXTURE", review)
    evidence = (source(anchor),)
    assessment = None
    if origin == "CONTEXT_PROPOSAL":
        evidence = tuple(
            sorted(
                evidence
                + tuple(
                    ScenarioEvidence(name, kind, SYMBOL, "d" * 64, CUT - 1, CUT, CUT, 5 * MINUTE)
                    for name, kind in (("macro", "MACRO"), ("news", "NEWS"))
                ),
                key=lambda e: (e.kind, e.source_id),
            )
        )
        assessment = CreationAssessment(
            creation_input_sha256("a" * 64, "b" * 64, anchor, evidence),
            "c" * 64,
            "e" * 64,
            side.value,
            CUT + 10_000,
            CUT + 12_000,
            CUT + 12_001,
            "TEST_FIXTURE",
        )
        created = max(created, assessment.actual_captured_ms)
    return HypothesisPlan(
        parent,
        origin,
        "BULL" if side is Side.LONG else "BEAR",
        CUT,
        created,
        "a" * 64,
        "b" * 64,
        evidence,
        anchor,
        tuple((e.kind, e.source_id) for e in evidence),
        policy,
        assessment,
    )


def observation(open_ms=CUT, *, side=Side.LONG, confirming=True, quote=True, observed=None):
    close = 100.5 if side is Side.LONG else 99.5
    candle = bar(open_ms, close if confirming else 100)
    arrival = open_ms + MINUTE + 10_000
    observed = arrival + 20 if observed is None else observed
    market = ScenarioObservation(candle, observed, (source(candle),))
    prices = (100.49, 100.5) if side is Side.LONG else (99.5, 99.51)
    q = EntryQuote("quotes", SYMBOL, *prices, arrival + 10, arrival + 11, arrival + 12, 5_000, "TEST_FIXTURE")
    return HypothesisObservation(market, q if quote else None)


def reviewed(p, obs, *, disposition="ALLOW", completed=None):
    review = ScenarioReview(
        p.scenario_id,
        p.template.side,
        disposition,
        obs.context_sha256,
        obs.market.observed_ms if completed is None else completed,
        "f" * 64,
    )
    return replace(obs, market=replace(obs.market, review=review))


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_postcut_actual_creation_preserves_parent_cut_anchor_and_full_protection(side):
    p = plan(side=side)
    before = asdict(p.template)
    assert p.created_ms > p.origin_cut_ms
    assert p.creation_evidence[0].captured_ms == p.created_ms
    assert p.anchor.close_time_ms == p.origin_cut_ms - 1
    assert p.valid_until_ms == CUT + 5 * MINUTE - 1
    result = evaluate_hypothesis(p, (observation(side=side),))
    candidate = result[-1].candidate
    assert type(result[-1]) is HypothesisEvaluation
    assert result[0].observed_ms == p.created_ms
    assert result[-1].state == "CONSUMED" and candidate is not None
    assert asdict(p.template) == before
    assert candidate.exit_plan is p.template.exit_plan
    assert candidate.signal_strength == p.template.signal_strength
    assert candidate.sleeve_id == POLICY_ID
    assert candidate.intent_id != p.template.intent_id
    assert candidate.entry_eligible_ts_ms > p.template.entry_expires_ts_ms
    assert candidate.entry_expires_ts_ms == observation(side=side).quote.event_ms + 5_000
    meta = dict(candidate.metadata)
    assert meta["hypothesis_origin_cut_ms"] == str(CUT)
    assert meta["hypothesis_actual_created_ms"] == str(p.created_ms)
    assert meta["parent_snapshot_sha256"] == digest(before)
    assert meta["protection_sha256"] == digest(asdict(p.template.exit_plan))
    assert meta["evidence_kind"] == "TEST_FIXTURE"
    assert meta["planning_cost_authority"] == "ASSUMPTION_NOT_VENUE_MEASUREMENT"


def test_v3_does_not_construct_a_backdated_v2_plan_or_retime_original_candidate():
    p = plan()
    old_policy = V2Policy(**asdict(p.policy))
    with pytest.raises(ValueError, match="creation sources"):
        V2Plan(
            p.template,
            p.origin,
            p.regime,
            p.origin_cut_ms,
            p.source_set_sha256,
            p.context_sha256,
            p.creation_evidence,
            p.anchor,
            p.required_sources,
            old_policy,
        )
    assert old_policy.sha256 != p.policy.sha256
    with pytest.raises(ValueError, match="separate hypothesis"):
        evaluate_v2(p, ())
    with pytest.raises(ValueError, match="original parent/cut"):
        replace(p, origin_cut_ms=p.created_ms)


@pytest.mark.parametrize("created", [CUT + MINUTE, CUT + MINUTE + 1, CUT + 2 * MINUTE])
def test_late_birth_rejects_instead_of_starting_observations_at_creation_floor(created):
    with pytest.raises(ValueError, match="first already completed"):
        plan(created=created)


def test_creation_just_before_first_complete_minute_is_allowed_but_never_skips_first_bar():
    p = plan(created=CUT + MINUTE - 1)
    result = evaluate_hypothesis(p, (observation(CUT + MINUTE),))[-1]
    assert result.state == "BLOCKED" and result.reason == "MARKET_GAP_OR_UNAVAILABLE"
    assert result.coverage == "UNAVAILABLE" and result.candidate is None


def test_original_validity_not_extended_by_ten_second_materialization_delay():
    p = plan(lifetime=MINUTE + 100)
    assert p.valid_until_ms == CUT + MINUTE + 99
    expired = evaluate_hypothesis(p, (observation(),))[-1]
    assert expired.state == "EXPIRED" and expired.candidate is None
    with pytest.raises(ValueError, match="born expired"):
        plan(lifetime=10_000)
    with pytest.raises(ValueError, match="original cut"):
        replace(p, policy=replace(p.policy, sealed_ms=CUT + 1))


@pytest.mark.parametrize("change", ["future_capture", "expired", "missing", "wrong_anchor", "extra_future"])
def test_creation_all_supplied_sources_need_real_availability_not_only_required_receipts(change):
    p = plan()
    receipts = p.creation_evidence
    if change == "future_capture":
        receipts = (replace(receipts[0], captured_ms=p.created_ms + 1),)
    elif change == "expired":
        receipts = (replace(receipts[0], ttl_ms=10_000),)
    elif change == "missing":
        receipts = ()
    elif change == "wrong_anchor":
        receipts = (replace(receipts[0], payload_sha256="f" * 64),)
    else:
        receipts += (replace(receipts[0], source_id="other-bars", captured_ms=p.created_ms + 1),)
    with pytest.raises(ValueError):
        replace(p, creation_evidence=receipts)


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_proposal_requires_bound_real_completion_after_all_creation_inputs(side):
    p = plan(origin="CONTEXT_PROPOSAL", side=side)
    a = p.creation_assessment
    assert a.actual_requested_ms >= max(e.captured_ms for e in p.creation_evidence)
    assert a.actual_completed_ms <= a.actual_captured_ms <= p.created_ms
    assert a.input_sha256 == p.creation_input_sha256
    assert a.direction == p.template.side.value
    assert p.valid_until_ms == CUT + 5 * MINUTE - 1
    with pytest.raises(ValueError, match="typed actual"):
        replace(p, creation_assessment=None)
    with pytest.raises(ValueError, match="impersonate"):
        replace(plan(), creation_assessment=a)


@pytest.mark.parametrize(
    "change", ["early_request", "late_completion", "late_capture", "input", "side", "kind"]
)
def test_proposal_bad_actual_clocks_or_identity_fail_without_projecting_elapsed_to_cut(change):
    p = plan(origin="CONTEXT_PROPOSAL")
    a = p.creation_assessment
    values = {
        "early_request": {"actual_requested_ms": CUT + 9_999},
        "late_completion": {"actual_completed_ms": p.created_ms + 1, "actual_captured_ms": p.created_ms + 1},
        "late_capture": {"actual_captured_ms": p.created_ms + 1},
        "input": {"input_sha256": "f" * 64},
        "side": {"direction": "SHORT"},
        "kind": {"evidence_kind": "CALLER_ATTESTED_POINT_IN_TIME"},
    }
    with pytest.raises(ValueError, match="actual completion clock"):
        replace(p, creation_assessment=replace(a, **values[change]))


@pytest.mark.parametrize(
    "field,value",
    [
        ("actual_requested_ms", True),
        ("actual_completed_ms", CUT - 1),
        ("provider", "DEEPSEEK"),
        ("evidence_kind", "MODERN_RETROSPECTIVE"),
        ("response_sha256", "missing"),
        ("direction", "NONE"),
    ],
)
def test_creation_assessment_strict_actual_clock_and_response_contract(field, value):
    with pytest.raises(ValueError):
        replace(plan(origin="CONTEXT_PROPOSAL").creation_assessment, **{field: value})


def test_creation_receipt_rechecks_nested_objects_even_when_forged_frozen_instance():
    p = plan(origin="CONTEXT_PROPOSAL")
    object.__setattr__(p.creation_assessment, "actual_requested_ms", True)
    with pytest.raises(ValueError):
        evaluate_hypothesis(p, ())


@pytest.mark.parametrize("change", ["future", "wrong_market", "late", "skip", "missing"])
def test_observation_cannot_precede_actual_receipt_or_discard_earlier_completed_minute(change):
    p, obs = plan(), observation()
    if change == "future":
        receipt = replace(obs.market.sources[0], captured_ms=obs.market.observed_ms + 1)
        obs = replace(obs, market=replace(obs.market, sources=(receipt,)))
    elif change == "wrong_market":
        receipt = replace(obs.market.sources[0], payload_sha256="f" * 64)
        obs = replace(obs, market=replace(obs.market, sources=(receipt,)))
    elif change == "late":
        obs = replace(obs, market=replace(obs.market, observed_ms=CUT + 2 * MINUTE))
    elif change == "skip":
        obs = observation(CUT + MINUTE)
    else:
        obs = replace(obs, market=replace(obs.market, sources=()))
    result = evaluate_hypothesis(p, (obs,))[-1]
    assert result.state == "BLOCKED" and result.coverage == "UNAVAILABLE"
    assert result.candidate is None


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_first_origin_minute_stop_wins_confirmation_after_postcut_creation(side):
    p, obs = plan(side=side), observation(side=side)
    candle = replace(obs.market.candle, low=98 if side is Side.LONG else 99, high=102)
    obs = replace(obs, market=replace(obs.market, candle=candle, sources=(source(candle),)))
    result = evaluate_hypothesis(p, (obs, observation(CUT + MINUTE, side=side)))
    assert result[-2].state == "INVALIDATED" and result[-2].candidate is None
    assert result[-1].reason == "TERMINAL_NO_RESURRECTION" and result[-1].candidate is None


@pytest.mark.parametrize("change", ["missing", "stale", "future", "preclose", "wrong_source", "wrong_kind"])
def test_bad_first_quote_is_consumed_and_no_later_quote_can_rescue_it(change):
    p, obs = plan(), observation()
    values = {
        "stale": {"ttl_ms": 1},
        "future": {"captured_ms": obs.market.observed_ms + 1},
        "preclose": {"event_ms": obs.market.candle.close_time_ms},
        "wrong_source": {"source_id": "other-quotes"},
        "wrong_kind": {"evidence_kind": "CALLER_ATTESTED_POINT_IN_TIME"},
    }
    q = None if change == "missing" else replace(obs.quote, **values[change])
    result = evaluate_hypothesis(p, (replace(obs, quote=q), observation(CUT + MINUTE)))
    assert result[-2].state == "CONSUMED" and result[-2].candidate is None
    assert result[-2].coverage == "UNAVAILABLE"
    assert result[-1].reason == "TERMINAL_NO_RESURRECTION" and result[-1].candidate is None


@pytest.mark.parametrize("change", ["before_quote", "late", "wrong_context", "wrong_side", "wrong_plan"])
def test_review_requires_exact_v3_context_and_original_actual_completion(change):
    p, obs = plan(review=True), observation()
    obs = reviewed(p, obs)
    assert evaluate_hypothesis(p, (obs,))[-1].candidate is not None
    values = {
        "before_quote": {"completed_ms": obs.quote.captured_ms - 1},
        "late": {"completed_ms": obs.market.observed_ms + 1},
        "wrong_context": {"context_sha256": obs.market.context_sha256},
        "wrong_side": {"side": Side.SHORT},
        "wrong_plan": {"scenario_id": "a" * 64},
    }
    obs = replace(obs, market=replace(obs.market, review=replace(obs.market.review, **values[change])))
    result = evaluate_hypothesis(p, (obs,))[-1]
    assert result.reason == "REVIEW_IDENTITY_OR_CLOCK_CONFLICT" and result.candidate is None


@pytest.mark.parametrize("disposition", ["VETO", "DEFER"])
def test_review_refusal_consumes_first_structure_not_a_new_attempt(disposition):
    p = plan(review=True)
    first = reviewed(p, observation(), disposition=disposition)
    later = reviewed(p, observation(CUT + MINUTE))
    result = evaluate_hypothesis(p, (first, later))
    assert result[-2].reason == "REVIEW_" + disposition
    assert result[-1].reason == "TERMINAL_NO_RESURRECTION" and result[-1].candidate is None


def test_pure_fold_exact_redelivery_and_no_future_mutation_hash_chain():
    p, first = plan(), observation(confirming=False)
    prefix = evaluate_hypothesis(p, (first,))
    later = observation(CUT + MINUTE)
    result = evaluate_hypothesis(p, (first, later))
    assert result[: len(prefix)] == prefix
    assert evaluate_hypothesis(p, (first, first, later)) == result
    assert all(b.previous_sha256 == a.sha256 for a, b in zip(result, result[1:], strict=False))
    with pytest.raises(ValueError, match="conflicting redelivery"):
        evaluate_hypothesis(p, (first, replace(first, quote=replace(first.quote, bid=100.48))))


@pytest.mark.parametrize("side,price", [(Side.LONG, 103), (Side.SHORT, 97)])
def test_original_trailing_activation_equality_does_not_recenter_geometry(side, price):
    p, obs = plan(side=side), observation(side=side)
    result = evaluate_hypothesis(p, (replace(obs, quote=replace(obs.quote, bid=price, ask=price)),))[-1]
    assert result.reason == "UNCHANGED_TRAILING_ACTIVATION_ALREADY_PASSED" and result.candidate is None


def test_preserved_parent_inclusive_ttl_caps_fresh_entry_not_creation_delay():
    p, obs = plan(), observation()
    original = replace(p.template, entry_expires_ts_ms=CUT + 999)
    p = replace(p, template=original)
    candidate = evaluate_hypothesis(p, (obs,))[-1].candidate
    assert candidate.entry_expires_ts_ms == obs.market.observed_ms + 999
    assert p.parent_entry_lifetime_ms == 1_000
    assert p.template.entry_expires_ts_ms == CUT + 999


def test_source_attestation_stays_explicit_and_does_not_promote_to_authentication():
    p, obs = plan(), observation()
    p = replace(p, policy=replace(p.policy, evidence_kind="CALLER_ATTESTED_POINT_IN_TIME"))
    assert p.policy.clock_domain == "CALLER_ATTESTED_UTC"
    assert evaluate_hypothesis(p, (obs,))[-1].candidate is None
    obs = replace(obs, quote=replace(obs.quote, evidence_kind="CALLER_ATTESTED_POINT_IN_TIME"))
    candidate = evaluate_hypothesis(p, (obs,))[-1].candidate
    assert dict(candidate.metadata)["evidence_kind"] == "CALLER_ATTESTED_POINT_IN_TIME"
    assert "authentication" not in dict(candidate.metadata)
    assert "source_admitted" not in dict(candidate.metadata)
