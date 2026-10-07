from dataclasses import replace

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle

from adaptive_replay.engine import CostScenario
from adaptive_replay.failed_reversal import HISTORY_BARS, generate_failed_reversal
from adaptive_replay.failed_reversal_entry import inspect_first_arrivals

BASE = CostScenario("base", 4.5, 2, 1, 2, 2, 3)
STRESS = CostScenario("stress", 9, 4, 2, 2, 2, 3)


def fixture(side=Side.LONG, *, two_bars=False, event_offset=0):
    """Typed artificial geometry fixture, never market/profitability evidence."""
    event_index = HISTORY_BARS // 5 - 1 + event_offset
    events = {event_index - 48: (100, 104, 99.6, 100)}
    events[event_index] = (100, 100.3, 99.5, 99.5 if two_bars else 99.8)
    if two_bars:
        events[event_index + 1] = (99.5, 100.2, 99.4, 99.8)
    rows = []
    for index in range(event_index + 1 + int(two_bars)):
        o, h, lo, c = events.get(index, (100, 100.4, 99.6, 100))
        for minute in range(5):
            opened = o if minute < 4 else c
            close = c if minute == 4 else opened
            high = h if minute == 0 else max(opened, close)
            low = lo if minute == 0 else min(opened, close)
            if side is Side.SHORT:
                opened, high, low, close = 200 - opened, 200 - low, 200 - high, 200 - close
            ts = len(rows) * 60_000
            rows.append(Candle("BTCUSDT", "1m", ts, ts + 59_999, opened, high, low, close, 1))
    decision = generate_failed_reversal(tuple(rows), origin_ms=0)[-1]
    candidate = decision.candidate
    assert candidate is not None
    cut = candidate.entry_eligible_ts_ms
    price = candidate.reference_price
    rows.append(Candle("BTCUSDT", "1m", cut, cut + 59_999, price, price + 0.05, price - 0.05, price, 1))
    return candidate, tuple(rows), cut + 60_000


def inspect(candidate, rows, quote, *, price=None, completion=None, scenarios=(BASE, STRESS), deadline=None):
    return inspect_first_arrivals(
        candidate,
        rows,
        completion_ms=candidate.decision_ts_ms + 100 if completion is None else completion,
        quote_ms=quote,
        quote_open=candidate.reference_price if price is None else price,
        scenarios=scenarios,
        deadline=deadline,
    )


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
@pytest.mark.parametrize("two_bars", [False, True])
@pytest.mark.parametrize("event_offset", [0, 1, 2, 3])
def test_source_bound_first_quote_preserves_actual_event_extremes(side, two_bars, event_offset):
    candidate, rows, quote = fixture(side, two_bars=two_bars, event_offset=event_offset)
    result = inspect(candidate, rows, quote)
    base = result["base"]
    assert base["geometry_feasible"]
    assert base["original_stop_price"] == candidate.exit_plan.stop_price
    assert base["original_target_price"] == candidate.exit_plan.target_price
    assert not base["trading_admitted"] and not base["source_authenticity_admitted"]
    assert not base["observed_bbo_or_fill"]
    assert base["quote_ms"] > candidate.entry_eligible_ts_ms
    assert result["stress"]["planning_round_trip_bps"] == 33


@pytest.mark.parametrize("barrier", ["stop", "target"])
def test_intermediate_original_barrier_touch_cancels_both_cost_arms(barrier):
    candidate, rows, quote = fixture()
    last = rows[-1]
    changed = (
        replace(last, low=candidate.exit_plan.stop_price)
        if barrier == "stop"
        else replace(last, high=candidate.exit_plan.target_price)
    )
    result = inspect(candidate, (*rows[:-1], changed), quote)
    assert all(item["reason"] == "FROZEN_BARRIER_TOUCHED_BEFORE_ARRIVAL" for item in result.values())


def test_no_retry_backdate_or_lifetime_extension():
    candidate, rows, quote = fixture()
    later = (*rows, replace(rows[-1], open_time_ms=quote, close_time_ms=quote + 59_999))
    with pytest.raises(ValueError, match="first strict minute"):
        inspect(candidate, later, quote + 60_000)
    with pytest.raises(ValueError):
        inspect(candidate, rows[:-1], quote - 60_000)
    expired = inspect(candidate, rows, quote, completion=candidate.entry_expires_ts_ms + 1)
    assert all(item["reason"] == "LIFETIME_EXPIRED_BEFORE_FIRST_MINUTE_OPEN" for item in expired.values())


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_price_at_frozen_channel_edge_cannot_retarget(side):
    candidate, rows, quote = fixture(side)
    upper = float(dict(candidate.metadata)["frozen_channel_upper"])
    assert all(
        item["reason"] == "QUOTE_OUTSIDE_FROZEN_CHANNEL"
        for item in inspect(candidate, rows, quote, price=upper).values()
    )


def test_modified_history_or_frozen_geometry_is_not_same_source_bound_event():
    candidate, rows, quote = fixture()
    changed = (*rows[:20], replace(rows[20], volume=2), *rows[21:])
    with pytest.raises(ValueError, match="source prefix"):
        inspect(candidate, changed, quote)
    with pytest.raises(ValueError):
        inspect(candidate, (*rows[:20], *rows[21:]), quote)
    metadata = dict(candidate.metadata)
    metadata["frozen_channel_upper"] = "105"
    altered = replace(candidate, metadata=tuple(sorted(metadata.items())))
    with pytest.raises(ValueError, match="numeric geometry"):
        inspect(altered, rows, quote)


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_excursion_target_equality_is_consumed_even_if_next_bar_returns(side):
    candidate, rows, quote = fixture(side, two_bars=True)
    metadata = dict(candidate.metadata)
    excursion = int(metadata["excursion_open_ms"])
    index = excursion // 60_000
    changed = list(rows)
    changed[index] = (
        replace(rows[index], high=float(metadata["frozen_channel_upper"]))
        if side is Side.LONG
        else replace(rows[index], low=float(metadata["frozen_channel_lower"]))
    )
    # First-event source bars are post prior_history_sha256, so this change
    # would not be caught by the pre-event hash alone. The event contract must.
    with pytest.raises(ValueError, match="first-return event contract"):
        inspect(candidate, tuple(changed), quote)
    closed = tuple(row for row in changed if row.open_time_ms < candidate.entry_eligible_ts_ms)
    assert not any(row.candidate for row in generate_failed_reversal(closed, origin_ms=0))


def test_valid_intent_id_does_not_authorize_stop_rewrite():
    candidate, rows, quote = fixture()
    changed = replace(candidate, exit_plan=replace(candidate.exit_plan, stop_price=99.2))
    with pytest.raises(ValueError, match="original stop"):
        inspect(changed, rows, quote)
    unchecked = replace(candidate)
    object.__setattr__(unchecked, "intent_id", "a" * 64)
    with pytest.raises(ValueError, match="unchecked"):
        inspect(unchecked, rows, quote)


@pytest.mark.parametrize("field,value", [("price", float("nan")), ("price", True), ("completion", True)])
def test_invalid_price_and_clocks_fail_closed(field, value):
    candidate, rows, quote = fixture()
    with pytest.raises(ValueError):
        inspect(candidate, rows, quote, **{field: value})


def test_expired_deadline_and_duplicate_scenarios_fail_closed():
    candidate, rows, quote = fixture()
    with pytest.raises(TimeoutError):
        inspect(candidate, rows, quote, deadline=0)
    with pytest.raises(ValueError):
        inspect(candidate, rows, quote, scenarios=(BASE, BASE))


@pytest.mark.parametrize("defense", ["CRASH", "POST_SHOCK_COOLDOWN"])
def test_arrival_native_defense_is_not_llm_permission(monkeypatch, defense):
    candidate, rows, quote = fixture()
    from adaptive_replay.failed_reversal_entry import native_defense

    def verified(*args, **kwargs):
        native_defense(*args, **kwargs)
        return defense

    monkeypatch.setattr("adaptive_replay.failed_reversal_entry.native_defense", verified)
    assert all(item["reason"] == defense for item in inspect(candidate, rows, quote).values())
