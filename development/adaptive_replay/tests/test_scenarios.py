"""Synthetic offline lifecycle tests for closed-confirmation scenarios."""

from dataclasses import replace

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay.historical_context import digest
from adaptive_replay.inputs import UNIVERSE
from adaptive_replay.scenarios import (
    MINUTE,
    ScenarioEvidence,
    ScenarioObservation,
    ScenarioPlan,
    ScenarioReview,
    evaluate_scenario,
)

START = 86_400_000
SYMBOL = UNIVERSE[0]
SOURCE_SET = "a" * 64
CONTEXT = "b" * 64


def bar(open_ms, *, close=100.0, low=99.0, high=101.0, symbol=SYMBOL):
    high = max(high, 100.0, close)
    low = min(low, 100.0, close)
    return Candle(symbol, "1m", open_ms, open_ms + MINUTE - 1, 100.0, high, low, close, 10.0)


def evidence(
    kind, source_id, candle, *, event_ms=None, payload=None, received=None, captured=None, ttl=600_000
):
    event_ms = candle.close_time_ms if event_ms is None else event_ms
    payload = digest(candle_payload(candle)) if payload is None else payload
    return ScenarioEvidence(
        source_id,
        kind,
        SYMBOL,
        payload,
        event_ms,
        event_ms if received is None else received,
        event_ms if captured is None else captured,
        ttl,
    )


def ordered(*items):
    return tuple(sorted(items, key=lambda item: (item.kind, item.source_id)))


def plan(*, origin="TECHNICAL", required=None):
    anchor = bar(START - MINUTE)
    created = START
    template = SleeveIntent(
        "adaptive_pullback_range_v1",
        SYMBOL,
        Side.LONG,
        created - 1,
        created,
        created + 5 * MINUTE,
        100.0,
        1.0,
        500.0,
        ExitPlan(98.0, 105.0, 5 * MINUTE),
    )
    market = evidence("MARKET", "market-1", anchor)
    extra = ()
    if origin == "CONTEXT_PROPOSAL":
        news = evidence("NEWS", "news-1", anchor)
        macro = evidence("MACRO", "macro-1", anchor)
        extra = (news, macro)
    evidence_items = ordered(market, *extra)
    required = required or tuple((item.kind, item.source_id) for item in evidence_items)
    return ScenarioPlan(
        template,
        origin,
        "BULL",
        created,
        SOURCE_SET,
        CONTEXT,
        evidence_items,
        anchor,
        tuple(sorted(required)),
    )


def observation(
    open_ms,
    *,
    close=100.0,
    low=99.0,
    high=101.0,
    observed=None,
    review=None,
    source_id="market-1",
    payload=None,
):
    candle = bar(open_ms, close=close, low=low, high=high)
    receipt = evidence("MARKET", source_id, candle, payload=payload)
    observed = candle.close_time_ms + 1 if observed is None else observed
    return ScenarioObservation(candle, observed, (receipt,), review)


def review_for(p, obs, disposition="ALLOW", *, side=Side.LONG, context=None, completed=None):
    return ScenarioReview(
        p.scenario_id,
        side,
        disposition,
        obs.context_sha256 if context is None else context,
        obs.observed_ms if completed is None else completed,
        "c" * 64,
    )


def test_waiting_then_next_closed_minute_confirms_once_and_candidate_is_bound():
    p = plan()
    first = observation(START, close=100.0)
    second = observation(START + MINUTE, close=100.5)
    reviewed = replace(second, review=review_for(p, second))
    result = evaluate_scenario(p, (first, reviewed))
    assert [item.state for item in result] == ["WAITING_TRIGGER", "WAITING_TRIGGER", "CONSUMED"]
    candidate = result[-1].candidate
    assert candidate is not None
    assert candidate.side is Side.LONG
    assert candidate.reference_price == 100.5
    assert candidate.exit_plan == p.template.exit_plan
    assert candidate.entry_expires_ts_ms == p.template.entry_expires_ts_ms
    assert dict(candidate.metadata)["scenario_id"] == p.scenario_id
    assert dict(candidate.metadata)["confirmation_observation_id"] == reviewed.observation_id
    assert evaluate_scenario(p, (first, reviewed)) == result


@pytest.mark.parametrize("disposition", ["VETO", "DEFER"])
def test_veto_and_defer_consume_first_trigger_without_candidate(disposition):
    p = plan()
    trigger = observation(START, close=100.5)
    trigger = replace(trigger, review=review_for(p, trigger, disposition))
    result = evaluate_scenario(p, (trigger, observation(START + MINUTE, close=101.0)))
    assert result[-1].state == "CONSUMED"
    assert result[-2].reason == f"REVIEW_{disposition}"
    assert result[-2].candidate is None
    assert result[-1].candidate is None
    assert result[-1].reason == "TERMINAL_NO_RESURRECTION"
    assert result[-1].previous_sha256 == result[-2].sha256


@pytest.mark.parametrize("field,value", [("side", Side.SHORT), ("disposition", "VETO")])
def test_review_must_allow_exact_scenario_side_context_and_clock(field, value):
    p = plan()
    trigger = observation(START, close=100.5)
    review = review_for(p, trigger)
    review = replace(review, **{field: value})
    result = evaluate_scenario(p, (replace(trigger, review=review),))[-1]
    assert result.candidate is None
    assert result.state == "CONSUMED"


def test_missing_review_defers_but_explicit_offline_control_is_strategy_only():
    p = plan()
    trigger = observation(START, close=100.5)
    reviewed = evaluate_scenario(p, (trigger,))[-1]
    assert reviewed.reason == "REVIEW_MISSING_DEFER"
    assert reviewed.candidate is None
    control = evaluate_scenario(p, (trigger,), require_review=False)[-1]
    assert control.candidate is not None


def test_context_proposal_requires_news_macro_and_later_fresh_required_evidence():
    anchor = bar(START - MINUTE)
    items = ordered(evidence("MARKET", "market-1", anchor))
    with pytest.raises(ValueError, match="news and macro"):
        p = plan(origin="CONTEXT_PROPOSAL", required=(("MARKET", "market-1"),))
        replace(p, creation_evidence=items)
    p = plan(origin="CONTEXT_PROPOSAL")
    trigger = observation(START, close=100.5)
    trigger = replace(trigger, review=review_for(p, trigger))
    blocked = evaluate_scenario(p, (trigger,))[-1]
    assert blocked.state == "CONSUMED"
    assert blocked.reason == "REQUIRED_CONTEXT_UNAVAILABLE"
    assert blocked.coverage == "UNAVAILABLE"


def test_creation_evidence_binds_actual_anchor_payload_and_strict_clocks():
    p = plan()
    wrong_payload = evidence("MARKET", "market-1", p.anchor, payload="d" * 64)
    with pytest.raises(ValueError, match="bind actual anchor"):
        replace(p, creation_evidence=(wrong_payload,))
    with pytest.raises(ValueError, match="ordered local source clocks"):
        replace(evidence("MARKET", "market-1", p.anchor), received_ms=START + 2, captured_ms=START + 1)
    with pytest.raises(ValueError, match="positive TTL"):
        replace(evidence("MARKET", "market-1", p.anchor), ttl_ms=0)


def test_source_identity_symbol_kind_and_canonical_order_are_enforced():
    p = plan()
    duplicate = evidence("MARKET", "market-1", p.anchor)
    with pytest.raises(ValueError, match="duplicate source identity"):
        replace(p, creation_evidence=ordered(*p.creation_evidence, duplicate))
    alien = replace(evidence("MARKET", "market-2", p.anchor), symbol=UNIVERSE[1])
    with pytest.raises(ValueError, match="source symbol conflict"):
        replace(p, creation_evidence=ordered(*p.creation_evidence, alien))
    context_plan = plan(origin="CONTEXT_PROPOSAL")
    with pytest.raises(ValueError, match="canonical source order"):
        replace(context_plan, creation_evidence=tuple(reversed(context_plan.creation_evidence)))


def test_first_trigger_consumed_when_economics_reject_and_never_resurrects():
    p = plan()
    too_wide = observation(START, close=100.5)
    changed_template = replace(p.template, exit_plan=ExitPlan(96.0, 105.0, 5 * MINUTE))
    p = replace(p, template=changed_template)
    too_wide = replace(too_wide, review=review_for(p, too_wide))
    first = evaluate_scenario(p, (too_wide, observation(START + MINUTE, close=102.0)))[-2:]
    assert first[0].state == "CONSUMED"
    assert first[0].reason == "STOP_DISTANCE_TOO_WIDE"
    assert first[0].candidate is None
    assert first[1].reason == "TERMINAL_NO_RESURRECTION"


def test_stop_invalidation_wins_same_candle_as_confirmation():
    p = plan()
    trigger = observation(START, close=100.5, low=97.9)
    trigger = replace(trigger, review=review_for(p, trigger))
    result = evaluate_scenario(p, (trigger,))[-1]
    assert result.state == "INVALIDATED"
    assert result.reason == "FROZEN_STOP_LEVEL_BREACHED"
    assert result.candidate is None


def test_original_expiry_is_not_extended_and_delayed_observation_is_not_backdated():
    p = plan()
    late = observation(START, close=100.5, observed=p.template.entry_expires_ts_ms + 1)
    result = evaluate_scenario(p, (late,))[-1]
    assert result.state == "EXPIRED"
    assert result.candidate is None
    assert result.observed_ms == late.observed_ms


def test_duplicate_delivery_collapses_exact_bytes_and_conflicting_retry_is_rejected():
    p = plan()
    one = observation(START, close=100.5)
    one = replace(one, review=review_for(p, one))
    assert evaluate_scenario(p, (one, one)) == evaluate_scenario(p, (one,))
    conflicting = replace(one, observed_ms=one.observed_ms + 1)
    with pytest.raises(ValueError, match="conflicting retry"):
        evaluate_scenario(p, (one, conflicting))


def test_future_or_backwards_source_clock_and_gap_are_blocked_unavailable():
    p = plan()
    candle = bar(START)
    future = evidence("MARKET", "market-1", candle, ttl=1)
    future_obs = ScenarioObservation(candle, candle.close_time_ms + 20, (future,))
    result = evaluate_scenario(p, (future_obs,))[-1]
    assert result.state == "BLOCKED" and result.coverage == "UNAVAILABLE"
    gap = observation(START + 2 * MINUTE, close=100.0)
    result = evaluate_scenario(p, (gap,))[-1]
    assert result.state == "BLOCKED" and result.coverage == "UNAVAILABLE"
    slow_first = observation(START, close=100.0, observed=START + 3 * MINUTE)
    faster_second = observation(START + MINUTE, observed=START + 2 * MINUTE)
    with pytest.raises(ValueError, match="cannot go backwards"):
        evaluate_scenario(p, (slow_first, faster_second))


def test_trailing_template_and_nonpositive_original_lifetime_are_rejected():
    p = plan()
    with pytest.raises(ValueError, match="trailing exits are unsupported"):
        replace(p, template=replace(p.template, exit_plan=ExitPlan(98.0, 105.0, 5 * MINUTE, 101.0, 1.0)))
    with pytest.raises(ValueError, match="bounded original lifetime"):
        replace(p, template=replace(p.template, entry_expires_ts_ms=START))


def test_allow_cannot_predate_latest_observation_source_capture():
    p = plan()
    candle = bar(START, close=100.5)
    trigger = observation(START, close=100.5, observed=candle.close_time_ms + 10)
    later_capture = evidence(
        "MARKET",
        "market-1",
        trigger.candle,
        received=trigger.candle.close_time_ms + 5,
        captured=trigger.candle.close_time_ms + 5,
    )
    trigger = replace(trigger, sources=(later_capture,))
    review = review_for(p, trigger, completed=trigger.observed_ms - 10)
    result = evaluate_scenario(p, (replace(trigger, review=review),))[-1]
    assert result.state == "CONSUMED"
    assert result.reason == "REVIEW_IDENTITY_OR_CLOCK_CONFLICT"
    assert result.candidate is None


def test_template_and_existing_native_inputs_remain_unchanged():
    p = plan()
    before = p.template
    observations = (observation(START, close=100.5),)
    evaluate_scenario(p, observations, require_review=False)
    assert p.template == before
    assert p.template.side is Side.LONG
    assert p.template.exit_plan == ExitPlan(98.0, 105.0, 5 * MINUTE)


def test_short_confirmation_is_symmetric_and_cannot_emit_a_long():
    p = plan()
    parent = replace(p.template, side=Side.SHORT, exit_plan=ExitPlan(102, 95, 5 * MINUTE))
    p = replace(p, template=parent, regime="BEAR")
    trigger = observation(START, close=99.5)
    trigger = replace(trigger, review=review_for(p, trigger, side=Side.SHORT))
    result = evaluate_scenario(p, (trigger,))[-1]
    assert result.candidate.side is Side.SHORT
    assert result.candidate.exit_plan == parent.exit_plan


@pytest.mark.parametrize("regime", ["UNCERTAIN", "CRASH", "CHOP"])
def test_unknown_or_unimplemented_regime_never_acquires_entry_permission(regime):
    with pytest.raises(ValueError, match="unsupported regime"):
        replace(plan(), regime=regime)


def test_market_receipt_arriving_after_cut_cannot_be_backdated():
    p = plan()
    trigger = observation(START, close=100.5)
    source = replace(
        trigger.sources[0], received_ms=trigger.observed_ms + 1, captured_ms=trigger.observed_ms + 1
    )
    result = evaluate_scenario(p, (replace(trigger, sources=(source,)),), require_review=False)[-1]
    assert result.state == "BLOCKED" and result.coverage == "UNAVAILABLE"
    assert result.candidate is None


def test_review_wrong_context_digest_and_late_completion_cannot_allow():
    p = plan()
    trigger = observation(START, close=100.5)
    for review in (
        review_for(p, trigger, context="e" * 64),
        review_for(p, trigger, completed=trigger.observed_ms + 1),
    ):
        result = evaluate_scenario(p, (replace(trigger, review=review),))[-1]
        assert result.reason == "REVIEW_IDENTITY_OR_CLOCK_CONFLICT" and result.candidate is None


def test_inclusive_expiry_boundary_uses_actual_observation_time():
    p = plan()
    trigger = observation(START, close=100.5, observed=p.template.entry_expires_ts_ms)
    result = evaluate_scenario(p, (trigger,), require_review=False)[-1]
    assert result.candidate is not None
    assert result.candidate.entry_eligible_ts_ms == p.template.entry_expires_ts_ms
    assert result.candidate.entry_expires_ts_ms == p.template.entry_expires_ts_ms


@pytest.mark.parametrize("atr", ["broken", "nan", "0", "0.1"])
def test_frozen_atr_is_not_ignored_or_changed_to_rescue_confirmation(atr):
    p = plan()
    p = replace(p, template=replace(p.template, metadata=(("frozen_atr15", atr),)))
    result = evaluate_scenario(p, (observation(START, close=100.5),), require_review=False)[-1]
    assert result.state == "CONSUMED" and result.candidate is None
    assert result.reason in {"INVALID_FROZEN_VOLATILITY", "STOP_OUTSIDE_FROZEN_ATR_BOUNDS"}


def test_prefix_evaluation_never_changes_when_later_outcomes_are_added():
    p = plan()
    first = observation(START, close=100.0)
    trigger = observation(START + MINUTE, close=100.5)
    trigger = replace(trigger, review=review_for(p, trigger))
    prefix = evaluate_scenario(p, (first, trigger))
    longer = evaluate_scenario(p, (first, trigger, observation(START + 2 * MINUTE, close=104.0)))
    assert longer[: len(prefix)] == prefix
    assert sum(result.candidate is not None for result in longer) == 1


def test_short_native_expiry_is_retained_even_when_confirmation_cannot_fit():
    p = plan()
    p = replace(p, template=replace(p.template, entry_expires_ts_ms=START + MINUTE - 1))
    result = evaluate_scenario(p, (observation(START, close=100.5),), require_review=False)[-1]
    assert result.state == "EXPIRED" and result.candidate is None
    assert p.template.entry_expires_ts_ms == START + MINUTE - 1


def test_terminal_missing_evidence_does_not_turn_into_available_evaluation():
    p = plan()
    trigger = observation(START, close=100.5)
    results = evaluate_scenario(p, (trigger, observation(START + MINUTE, close=101)))
    assert results[-2].coverage == "UNAVAILABLE"
    assert results[-1].coverage == "UNAVAILABLE"
    assert results[-1].state == "CONSUMED" and results[-1].candidate is None
