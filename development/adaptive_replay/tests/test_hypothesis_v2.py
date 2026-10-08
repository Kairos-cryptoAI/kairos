"""Synthetic new-policy mechanics; no historical quotes, alpha or venue proof."""

from dataclasses import asdict, replace

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay.engine import COMMON_COST_RISK, CostScenario, Portfolio, entry_time
from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_v2 import (
    POLICY_ID,
    EntryQuote,
    HypothesisObservation,
    HypothesisPlan,
    HypothesisPolicy,
    evaluate_hypothesis,
)
from adaptive_replay.scenarios import ScenarioEvidence, ScenarioObservation, ScenarioReview

START = 86_400_000
MINUTE = 60_000
SYMBOL = "BTCUSDT"


def bar(open_ms, close=100.0, *, low=99.0, high=101.0):
    return Candle(
        SYMBOL, "1m", open_ms, open_ms + MINUTE - 1, 100, max(high, close), min(low, close), close, 10
    )


def source(candle, *, source_id="bars", payload=None, ttl=600_000):
    return ScenarioEvidence(
        source_id,
        "MARKET",
        SYMBOL,
        payload or digest(candle_payload(candle)),
        candle.close_time_ms,
        candle.close_time_ms + 1,
        candle.close_time_ms + 1,
        ttl,
    )


def plan(*, side=Side.LONG, trailing=True, review=False, lifetime=5 * MINUTE, parent_ttl=MINUTE):
    sign = 1 if side is Side.LONG else -1
    anchor = bar(START - MINUTE)
    parent = SleeveIntent(
        "trend_breakout_v1",
        SYMBOL,
        side,
        START - 1,
        START,
        START + parent_ttl - 1,
        100,
        0.7,
        500,
        ExitPlan(
            100 - 2 * sign,
            100 + 5 * sign,
            5 * MINUTE,
            100 + 3 * sign if trailing else None,
            1 if trailing else None,
        ),
        (("native_marker", "unchanged"),),
    )
    policy = HypothesisPolicy(START - 1, lifetime, "quotes", 5_000, "TEST_FIXTURE", review)
    return HypothesisPlan(
        parent,
        "TECHNICAL",
        "BULL" if side is Side.LONG else "BEAR",
        START,
        "a" * 64,
        "b" * 64,
        (source(anchor),),
        anchor,
        (("MARKET", "bars"),),
        policy,
    )


def observation(open_ms=START, *, side=Side.LONG, confirming=True, quote=True, observed=None):
    close = 100.5 if side is Side.LONG else 99.5
    candle = bar(open_ms, close if confirming else 100)
    cut = candle.close_time_ms + 1
    observed = cut + 20 if observed is None else observed
    market = ScenarioObservation(candle, observed, (source(candle),))
    prices = (100.49, 100.5) if side is Side.LONG else (99.5, 99.51)
    q = EntryQuote("quotes", SYMBOL, *prices, cut + 10, cut + 11, cut + 12, 5_000, "TEST_FIXTURE")
    return HypothesisObservation(market, q if quote else None)


def reviewed(p, obs, *, disposition="ALLOW", completed=None):
    review = ScenarioReview(
        p.scenario_id,
        p.template.side,
        disposition,
        obs.context_sha256,
        obs.market.observed_ms if completed is None else completed,
        "c" * 64,
    )
    return replace(obs, market=replace(obs.market, review=review))


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_new_hypothesis_outlives_old_parent_without_renewing_it_and_preserves_full_protection(side):
    p = plan(side=side)
    before = asdict(p.template)
    quiet = observation(confirming=False, side=side)
    trigger = observation(START + MINUTE, side=side)
    result = evaluate_hypothesis(p, (quiet, trigger))
    candidate = result[-1].candidate
    assert result[-1].state == "CONSUMED" and candidate is not None
    assert trigger.market.observed_ms > p.template.entry_expires_ts_ms
    assert asdict(p.template) == before
    assert candidate.intent_id != p.template.intent_id
    assert candidate.sleeve_id == POLICY_ID
    assert candidate.exit_plan is p.template.exit_plan
    assert candidate.signal_strength == p.template.signal_strength
    assert candidate.reference_price == (trigger.quote.ask if side is Side.LONG else trigger.quote.bid)
    assert candidate.decision_ts_ms == candidate.entry_eligible_ts_ms == trigger.market.observed_ms
    assert candidate.gross_reward_bps == pytest.approx(
        abs(candidate.exit_plan.target_price - candidate.reference_price) / candidate.reference_price * 10_000
    )
    metadata = dict(candidate.metadata)
    assert metadata["parent_intent_id"] == p.template.intent_id
    assert metadata["parent_snapshot_sha256"] == digest(before)
    assert metadata["protection_sha256"] == p.protection_sha256
    assert metadata["entry_quote_sha256"] == trigger.quote.sha256
    assert metadata["hypothesis_id"] == p.scenario_id and metadata["native_marker"] == "unchanged"
    assert p.parent_entry_lifetime_ms == MINUTE
    assert candidate.entry_expires_ts_ms == trigger.quote.event_ms + 5_000
    assert entry_time(candidate, candidate.entry_expires_ts_ms, "INTRABAR_OPEN_PROXY") is not None
    assert entry_time(candidate, candidate.entry_expires_ts_ms + 1, "INTRABAR_OPEN_PROXY") is None


def test_review_mode_is_frozen_into_policy_and_hypothesis_identity():
    p = plan(review=True)
    control = replace(p, policy=replace(p.policy, require_review=False))
    assert p.scenario_id != control.scenario_id and p.policy.sha256 != control.policy.sha256
    trigger = observation()
    assert evaluate_hypothesis(p, (trigger,))[-1].reason == "REVIEW_MISSING_DEFER"
    assert evaluate_hypothesis(control, (trigger,))[-1].candidate is not None


def test_real_family_assumed_cost_metadata_is_preserved_and_conflicting_authority_rejected():
    p = plan()
    parent = replace(
        p.template,
        metadata=p.template.metadata + (("planning_cost_authority", "ASSUMPTION_NOT_VENUE_MEASUREMENT"),),
    )
    actual = replace(p, template=parent)
    candidate = evaluate_hypothesis(actual, (observation(),))[-1].candidate
    assert (
        dict(candidate.metadata)["planning_cost_authority"]
        == dict(parent.metadata)["planning_cost_authority"]
    )
    with pytest.raises(ValueError, match="provenance"):
        replace(p, template=replace(p.template, metadata=(("planning_cost_authority", "VENUE_QUALIFIED"),)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("sealed_ms", START + 1),
        ("hypothesis_lifetime_ms", 0),
        ("hypothesis_lifetime_ms", 61 * MINUTE),
        ("maximum_quote_age_ms", 5_001),
        ("maximum_quote_age_ms", True),
        ("evidence_kind", "MODERN_RETROSPECTIVE"),
    ],
)
def test_precreation_policy_cannot_be_resealed_or_malformed(field, value):
    p = plan()
    with pytest.raises(ValueError):
        replace(p, policy=replace(p.policy, **{field: value}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("bid", True),
        ("ask", float("nan")),
        ("bid", float("inf")),
        ("ask", 0),
        ("bid", 101),
        ("received_ms", START - 1),
        ("ttl_ms", 0),
    ],
)
def test_quote_contract_rejects_nonfinite_coercion_crossed_or_noncausal_input(field, value):
    with pytest.raises(ValueError):
        replace(observation().quote, **{field: value})


@pytest.mark.parametrize(
    "change", ["missing", "stale", "future", "preclose", "wrong_symbol", "wrong_source", "wrong_kind"]
)
def test_bad_quote_consumes_first_trigger_and_cannot_be_retried(change):
    p, obs = plan(), observation()
    q = obs.quote
    if change == "missing":
        q = None
    elif change == "stale":
        q = replace(q, ttl_ms=1)
    elif change == "future":
        q = replace(q, captured_ms=obs.market.observed_ms + 1)
    elif change == "preclose":
        q = replace(q, event_ms=obs.market.candle.close_time_ms)
    elif change == "wrong_symbol":
        q = replace(q, symbol="ETHUSDT")
    elif change == "wrong_source":
        q = replace(q, source_id="other-quotes")
    elif change == "wrong_kind":
        q = replace(q, evidence_kind="CALLER_ATTESTED_POINT_IN_TIME")
    result = evaluate_hypothesis(p, (replace(obs, quote=q), observation(START + MINUTE)))
    assert result[-2].state == "CONSUMED" and result[-2].coverage == "UNAVAILABLE"
    assert result[-2].candidate is None and result[-1].candidate is None
    assert result[-1].reason == "TERMINAL_NO_RESURRECTION"


@pytest.mark.parametrize(
    "case", ["v1_digest", "before_quote", "wrong_side", "wrong_plan", "late", "different_quote"]
)
def test_review_binds_exact_quote_and_source_capture_not_old_candle_only_context(case):
    p, obs = plan(review=True), observation()
    good = reviewed(p, obs)
    assert evaluate_hypothesis(p, (good,))[-1].candidate is not None
    r = good.market.review
    if case == "v1_digest":
        r = replace(r, context_sha256=obs.market.context_sha256)
    elif case == "before_quote":
        r = replace(r, completed_ms=obs.quote.captured_ms - 1)
    elif case == "wrong_side":
        r = replace(r, side=Side.SHORT)
    elif case == "wrong_plan":
        r = replace(r, scenario_id="d" * 64)
    elif case == "late":
        r = replace(r, completed_ms=obs.market.observed_ms + 1)
    else:
        good = replace(good, quote=replace(good.quote, bid=100.48))
    rejected = evaluate_hypothesis(p, (replace(good, market=replace(good.market, review=r)),))[-1]
    assert rejected.reason == "REVIEW_IDENTITY_OR_CLOCK_CONFLICT" and rejected.candidate is None


@pytest.mark.parametrize("disposition", ["VETO", "DEFER"])
def test_veto_and_defer_are_consumed_not_opportunities_for_a_later_allow(disposition):
    p = plan(review=True)
    first = reviewed(p, observation(), disposition=disposition)
    later = reviewed(p, observation(START + MINUTE))
    result = evaluate_hypothesis(p, (first, later))
    assert result[-2].reason == "REVIEW_" + disposition
    assert result[-1].reason == "TERMINAL_NO_RESURRECTION" and result[-1].candidate is None


@pytest.mark.parametrize(
    "side,price",
    [
        (Side.LONG, 103),
        (Side.LONG, 103.1),
        (Side.SHORT, 97),
        (Side.SHORT, 96.9),
    ],
)
def test_trailing_activation_equal_or_already_passed_cannot_be_recentered(side, price):
    p, obs = plan(side=side), observation(side=side)
    exits = p.template.exit_plan
    q = replace(obs.quote, bid=price, ask=price)
    result = evaluate_hypothesis(p, (replace(obs, quote=q),))[-1]
    assert result.reason == "UNCHANGED_TRAILING_ACTIVATION_ALREADY_PASSED" and result.candidate is None
    assert p.template.exit_plan is exits


@pytest.mark.parametrize("side,bid,ask", [(Side.LONG, 98, 100.5), (Side.SHORT, 99.5, 102)])
def test_stop_already_breached_on_exit_side_of_quote_is_not_safe_entry_geometry(side, bid, ask):
    p, obs = plan(side=side), observation(side=side)
    result = evaluate_hypothesis(p, (replace(obs, quote=replace(obs.quote, bid=bid, ask=ask)),))[-1]
    assert result.reason == "QUOTE_EXIT_SIDE_ALREADY_BREACHES_STOP" and result.candidate is None


@pytest.mark.parametrize("side,price", [(Side.LONG, 100), (Side.SHORT, 100)])
def test_closed_confirmation_must_still_hold_at_fresh_entry_reference(side, price):
    p, obs = plan(side=side), observation(side=side)
    result = evaluate_hypothesis(p, (replace(obs, quote=replace(obs.quote, bid=price, ask=price)),))[-1]
    assert result.reason == "CLOSED_CONFIRMATION_NOT_HELD_AT_QUOTE" and result.candidate is None


def test_wide_actual_quote_is_not_hidden_by_the_unchanged_planning_spread_assumption():
    p, obs = plan(), observation()
    obs = replace(obs, quote=replace(obs.quote, bid=100.45))
    result = evaluate_hypothesis(p, (obs,))[-1]
    assert result.reason == "QUOTE_SPREAD_EXCEEDS_FIXED_PLANNING_ASSUMPTION" and result.candidate is None


@pytest.mark.parametrize("side,price", [(Side.LONG, 105), (Side.SHORT, 95)])
def test_unchanged_target_equality_is_not_an_entry_even_when_trailing_is_absent(side, price):
    p, obs = plan(side=side, trailing=False), observation(side=side)
    result = evaluate_hypothesis(p, (replace(obs, quote=replace(obs.quote, bid=price, ask=price)),))[-1]
    assert result.reason == "UNCHANGED_BARRIERS_NOT_EXECUTABLE" and result.candidate is None


@pytest.mark.parametrize(
    "atr,reason",
    [
        ("bad", "INVALID_FROZEN_VOLATILITY"),
        ("0.1", "STOP_OUTSIDE_FROZEN_ATR_BOUNDS"),
    ],
)
def test_original_frozen_volatility_metadata_is_not_dropped_at_later_entry(atr, reason):
    p = plan()
    p = replace(p, template=replace(p.template, metadata=p.template.metadata + (("frozen_atr15", atr),)))
    result = evaluate_hypothesis(p, (observation(),))[-1]
    assert result.reason == reason and result.candidate is None


def test_required_context_source_expiry_is_consumed_unavailable_not_a_healthy_no_trade():
    p, obs = plan(), observation()
    news = ScenarioEvidence("news", "NEWS", SYMBOL, "e" * 64, START - 1, START, START, 5 * MINUTE)
    p = replace(
        p,
        creation_evidence=p.creation_evidence + (news,),
        required_sources=p.required_sources + (("NEWS", "news"),),
    )
    stale_news = replace(news, ttl_ms=MINUTE)
    obs = replace(obs, market=replace(obs.market, sources=obs.market.sources + (stale_news,)))
    result = evaluate_hypothesis(p, (obs,))[-1]
    assert result.reason == "REQUIRED_CONTEXT_UNAVAILABLE" and result.coverage == "UNAVAILABLE"


def test_caller_attested_quotes_do_not_mix_with_fixture_clock_domains():
    p, obs = plan(), observation()
    actual = replace(p, policy=replace(p.policy, evidence_kind="CALLER_ATTESTED_POINT_IN_TIME"))
    assert actual.policy.clock_domain != p.policy.clock_domain and actual.scenario_id != p.scenario_id
    assert evaluate_hypothesis(actual, (obs,))[-1].candidate is None
    obs = replace(obs, quote=replace(obs.quote, evidence_kind="CALLER_ATTESTED_POINT_IN_TIME"))
    candidate = evaluate_hypothesis(actual, (obs,))[-1].candidate
    assert dict(candidate.metadata)["evidence_kind"] == "CALLER_ATTESTED_POINT_IN_TIME"


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_closed_bar_stop_invalidation_wins_ambiguous_confirmation(side):
    p, obs = plan(side=side), observation(side=side)
    candle = replace(obs.market.candle, low=98 if side is Side.LONG else 99, high=102)
    obs = replace(obs, market=replace(obs.market, candle=candle, sources=(source(candle),)))
    result = evaluate_hypothesis(p, (obs,))[-1]
    assert result.state == "INVALIDATED" and result.candidate is None


def test_unknown_intermediate_minute_or_missing_prefix_blocks_even_fresh_quote():
    p = plan()
    late = observation(observed=START + 2 * MINUTE)
    late = replace(
        late,
        quote=replace(
            late.quote,
            event_ms=late.market.observed_ms,
            received_ms=late.market.observed_ms,
            captured_ms=late.market.observed_ms,
        ),
    )
    for obs in (late, observation(START + MINUTE)):
        result = evaluate_hypothesis(p, (obs,))[-1]
        assert result.state == "BLOCKED" and result.coverage == "UNAVAILABLE"


def test_exact_required_market_identity_cannot_be_substituted_with_an_extra_publisher():
    p, obs = plan(), observation()
    receipts = (
        source(obs.market.candle, payload="d" * 64),
        source(obs.market.candle, source_id="other-bars"),
    )
    result = evaluate_hypothesis(p, (replace(obs, market=replace(obs.market, sources=receipts)),))[-1]
    assert result.state == "BLOCKED" and result.candidate is None


def test_dedicated_quote_source_cannot_be_mixed_into_context_receipts():
    p, obs = plan(), observation()
    receipts = obs.market.sources + (source(obs.market.candle, source_id="quotes"),)
    result = evaluate_hypothesis(p, (replace(obs, market=replace(obs.market, sources=receipts)),))[-1]
    assert result.reason == "ENTRY_QUOTE_IDENTITY_CLOCK_OR_FRESHNESS_CONFLICT"


def test_native_inclusive_ttl_hypothesis_and_required_context_each_cap_new_deadline():
    obs = observation()
    p = plan(parent_ttl=1_000)
    candidate = evaluate_hypothesis(p, (obs,))[-1].candidate
    assert candidate.entry_expires_ts_ms == obs.market.observed_ms + 999
    p = plan(lifetime=MINUTE + 100)
    candidate = evaluate_hypothesis(p, (obs,))[-1].candidate
    assert candidate.entry_expires_ts_ms == p.valid_until_ms == START + MINUTE + 99
    market = replace(obs.market, sources=(source(obs.market.candle, ttl=100),))
    candidate = evaluate_hypothesis(plan(), (replace(obs, market=market),))[-1].candidate
    assert candidate.entry_expires_ts_ms == obs.market.candle.close_time_ms + 100
    expired = replace(obs, market=replace(obs.market, observed_ms=p.valid_until_ms + 1))
    assert evaluate_hypothesis(p, (expired,))[-1].state == "EXPIRED"


def test_same_receipt_collapses_conflicts_fail_and_later_context_does_not_mutate_prefix():
    p, obs = plan(), observation(confirming=False)
    before = evaluate_hypothesis(p, (obs,))
    later = observation(START + MINUTE)
    result = evaluate_hypothesis(p, (obs, later))
    assert result[: len(before)] == before
    assert evaluate_hypothesis(p, (obs, obs, later)) == result
    with pytest.raises(ValueError, match="conflicting redelivery"):
        evaluate_hypothesis(p, (obs, replace(obs, quote=replace(obs.quote, bid=100.48))))
    assert all(b.previous_sha256 == a.sha256 for a, b in zip(result, result[1:], strict=False))


def test_native_trailing_begins_at_actual_entry_and_only_updates_after_completed_close():
    p, obs = plan(), observation()
    candidate = evaluate_hypothesis(p, (obs,))[-1].candidate
    free = CostScenario("TEST_FIXTURE_ZERO_COST", 0, 0, 0, 0, 0, 0)
    portfolio = Portfolio(10_000, free, "INTRABAR_OPEN_PROXY", COMMON_COST_RISK)
    entry_bar = Candle(SYMBOL, "1m", START + MINUTE, START + 2 * MINUTE - 1, 100.5, 103.3, 99, 103.2, 10)
    assert portfolio.admit(candidate, candidate.entry_eligible_ts_ms, entry_bar, {SYMBOL: 100.5})
    position = portfolio.positions[SYMBOL]
    assert position.stop == 98 and not position.trailing_activated
    portfolio.exit_intrabar(entry_bar)
    assert SYMBOL in portfolio.positions  # No retrospective trailing stop on this candle's earlier low.
    portfolio.update_trailing_at_close(entry_bar)
    assert position.trailing_activated and position.stop == pytest.approx(102.2)
    next_bar = Candle(SYMBOL, "1m", START + 2 * MINUTE, START + 3 * MINUTE - 1, 103, 103.1, 102, 102.5, 10)
    portfolio.exit_intrabar(next_bar)
    assert portfolio.trades[-1]["reason"] == "TRAILING_STOP"
