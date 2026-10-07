from dataclasses import replace

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle

from adaptive_replay.engine import CostScenario
from adaptive_replay.frozen_retest import HISTORY_BARS, generate_frozen_retest
from adaptive_replay.frozen_retest_entry import inspect_first_arrival

BASE = CostScenario("base", 4.5, 2, 1, 2, 2, 3)
STRESS = CostScenario("stress", 9, 4, 2, 2, 2, 3)


def fixture(side=Side.LONG):
    """Synthetic typed causality fixture, not a market or source proof."""
    events = {
        620: (100, 103, 99.6, 100),
        648: (100, 104, 99.9, 100.8),
        649: (100.8, 101, 100.1, 100.2),
        650: (100.2, 101.1, 100, 100.8),
    }
    rows = []
    for index in range(HISTORY_BARS // 5 + 3):
        o, h, lo, c = events.get(index, (100, 100.4, 99.6, 100))
        for minute in range(5):
            opened = o if minute < 4 else c
            close = c if minute == 4 else opened
            high = h if minute == 0 else max(opened, close)
            low = lo if minute == 0 else min(opened, close)
            if side is Side.SHORT:
                opened, high, low, close = 200 - opened, 200 - low, 200 - high, 200 - close
            timestamp = len(rows) * 60_000
            rows.append(Candle("BTCUSDT", "1m", timestamp, timestamp + 59_999, opened, high, low, close, 1))
    candidate = generate_frozen_retest(tuple(rows), origin_ms=0)[-1].candidate
    assert candidate is not None
    price = candidate.reference_price
    cut = candidate.entry_eligible_ts_ms
    rows.append(Candle("BTCUSDT", "1m", cut, cut + 59_999, price, price + 0.1, price - 0.1, price, 1))
    return candidate, tuple(rows), cut + 60_000


def inspect(candidate, rows, quote, *, scenario=BASE, price=None, completion=None):
    return inspect_first_arrival(
        candidate,
        rows,
        completion_ms=completion or candidate.decision_ts_ms + 100,
        quote_ms=quote,
        quote_open=price or candidate.reference_price,
        scenario=scenario,
    )


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_first_strict_arrival_preserves_barriers_and_not_trading_authority(side):
    candidate, rows, quote = fixture(side)
    result = inspect(candidate, rows, quote)
    assert result["geometry_feasible"]
    assert result["original_stop_price"] == candidate.exit_plan.stop_price
    assert result["original_target_price"] == candidate.exit_plan.target_price
    assert not result["trading_admitted"] and not result["observed_bbo_or_fill"]
    assert not result["source_authenticity_admitted"]
    assert result["quote_ms"] > candidate.entry_eligible_ts_ms


def test_stress_is_retained_even_when_higher_cost_rejects():
    candidate, rows, quote = fixture()
    assert inspect(candidate, rows, quote, price=100.9)["geometry_feasible"]
    result = inspect(candidate, rows, quote, scenario=STRESS, price=100.9)
    assert result["planning_round_trip_bps"] == 33
    assert result["reason"] == "reward_risk_too_low" and not result["geometry_feasible"]


@pytest.mark.parametrize("barrier", ["stop", "target"])
def test_crossed_original_barrier_before_arrival_is_not_later_retried(barrier):
    candidate, rows, quote = fixture()
    last = rows[-1]
    altered = (
        replace(last, low=candidate.exit_plan.stop_price)
        if barrier == "stop"
        else (replace(last, high=candidate.exit_plan.target_price))
    )
    result = inspect(candidate, (*rows[:-1], altered), quote)
    assert result["reason"] == "FROZEN_BARRIER_TOUCHED_BEFORE_ARRIVAL"
    assert not result["geometry_feasible"]


def test_no_backdated_or_later_retry_quote():
    candidate, rows, quote = fixture()
    future = (*rows, replace(rows[-1], open_time_ms=quote, close_time_ms=quote + 59_999))
    with pytest.raises(ValueError, match="first strict quote"):
        inspect(candidate, future, quote + 60_000)
    with pytest.raises(ValueError):
        inspect(candidate, rows[:-1], quote - 60_000)


def test_expiry_is_not_extended_by_delayed_computation():
    candidate, rows, quote = fixture()
    result = inspect(candidate, rows, quote, completion=candidate.entry_expires_ts_ms + 1)
    assert result["reason"] == "LIFETIME_EXPIRED_BEFORE_FIRST_MINUTE_OPEN"
    assert not result["geometry_feasible"]


def test_lost_level_and_far_entry_cannot_retarget():
    candidate, rows, quote = fixture()
    level = float(dict(candidate.metadata)["frozen_level"])
    assert inspect(candidate, rows, quote, price=level)["reason"] == "FROZEN_LEVEL_LOST_AT_ARRIVAL"
    assert not inspect(candidate, rows, quote, price=104)["geometry_feasible"]


def test_prefix_binding_and_complete_closed_history_are_required():
    candidate, rows, quote = fixture()
    changed = (*rows[:20], replace(rows[20], volume=2), *rows[21:])
    with pytest.raises(ValueError, match="source prefix"):
        inspect(candidate, changed, quote)
    with pytest.raises(ValueError):
        inspect(candidate, rows[:-1], quote)
    with pytest.raises(ValueError):
        inspect(candidate, (*rows[:20], *rows[21:]), quote)


def test_wrong_strategy_changed_target_and_unchecked_identity_rejected():
    candidate, rows, quote = fixture()
    with pytest.raises(ValueError, match="new frozen-retest"):
        inspect(replace(candidate, sleeve_id="adaptive_pullback_range_v1"), rows, quote)
    mutated = replace(candidate)
    object.__setattr__(mutated, "intent_id", "a" * 64)
    with pytest.raises(ValueError, match="unchecked"):
        inspect(mutated, rows, quote)
    metadata = dict(candidate.metadata)
    metadata["frozen_target"] = "104"
    with pytest.raises(ValueError, match="target cannot"):
        inspect(replace(candidate, metadata=tuple(sorted(metadata.items()))), rows, quote)


@pytest.mark.parametrize("field,value", [("completion", True), ("price", float("nan"))])
def test_invalid_clocks_and_prices_fail_closed(field, value):
    candidate, rows, quote = fixture()
    with pytest.raises(ValueError):
        inspect(candidate, rows, quote, **{field: value})


def test_arrival_native_defense_failure_is_not_permission(monkeypatch):
    candidate, rows, quote = fixture()
    monkeypatch.setattr("adaptive_replay.frozen_retest_entry.native_defense", lambda *args, **kwargs: "CRASH")
    result = inspect(candidate, rows, quote)
    assert result["reason"] == "CRASH" and not result["geometry_feasible"]
