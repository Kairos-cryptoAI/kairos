"""Causal first-arrival inspection of the fixed reversal research candidate.

Only a completed prefix and the next minute OPEN enter this boundary.  Neither
hash agreement nor conditional geometry proves source admission, venue fills,
portfolio allocation, expected value, or permission to trade.
"""

from __future__ import annotations

import math
import re
import time

from kairos_backtest.cost_risk import RiskLimits, size_and_admit
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import SleeveIntent
from kairos_strategy.provenance import candle_payload
from kairos_strategy.timeframes import aggregate

from .engine import CostScenario, entry_time, fill_price
from .failed_reversal import (
    POLICY_SHA256,
    STRATEGY_ID,
    frozen_float_text,
    frozen_reversal_features_from_bars,
)
from .frozen_retest import native_defense
from .historical_context import digest
from .historical_replay import _validate_candidate

HASH = re.compile(r"^[0-9a-f]{64}$")
META_KEYS = {
    "policy_sha256",
    "explicit_origin_ms",
    "event_id",
    "excursion_open_ms",
    "confirmation_cut_ms",
    "frozen_channel_lower",
    "frozen_channel_upper",
    "frozen_atr15",
    "prior_history_sha256",
}


def _check(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("bounded reversal arrival deadline reached")


def _integer(metadata: dict[str, str], key: str) -> int:
    value = metadata[key]
    if not value.isdigit() or str(int(value)) != value:
        raise ValueError("canonical integer metadata clock required")
    return int(value)


def inspect_first_arrivals(
    candidate: SleeveIntent,
    closed_prefix: tuple[Candle, ...],
    *,
    completion_ms: int,
    quote_ms: int,
    quote_open: float,
    scenarios: tuple[CostScenario, ...],
    deadline: float | None = None,
) -> dict[str, dict]:
    """Inspect two fixed cost assumptions on the SAME first observed OPEN.

    Metadata is independently bound to completed pre-event features and the
    observed event extremes. Source authentication and state-machine admission
    remain separate; callers may not rewrite or retry a consumed event.
    """
    _check(deadline)
    _validate_candidate(candidate)
    if candidate.sleeve_id != STRATEGY_ID:
        raise ValueError("new reversal identity required; native candidates remain unchanged")
    if type(completion_ms) is not int or completion_ms < candidate.decision_ts_ms:
        raise ValueError("integer completion not earlier than decision required")
    if type(quote_ms) is not int or quote_ms < 0 or quote_ms % 60_000:
        raise ValueError("exact integer UTC minute-open quote required")
    if type(quote_open) not in (int, float) or not math.isfinite(quote_open) or quote_open <= 0:
        raise ValueError("positive finite minute-open price required")
    if (
        type(scenarios) is not tuple
        or not scenarios
        or any(type(s) is not CostScenario for s in scenarios)
        or len({s.id for s in scenarios}) != len(scenarios)
    ):
        raise ValueError("distinct typed fixed cost scenarios required")
    for scenario in scenarios:
        CostScenario(**scenario.__dict__)
    metadata = dict(candidate.metadata)
    if set(metadata) != META_KEYS or metadata["policy_sha256"] != POLICY_SHA256:
        raise ValueError("complete exact reversal policy metadata required")
    if any(not HASH.fullmatch(metadata[k]) for k in ("event_id", "prior_history_sha256")):
        raise ValueError("exact frozen event and source-prefix hashes required")
    origin = _integer(metadata, "explicit_origin_ms")
    excursion = _integer(metadata, "excursion_open_ms")
    confirmation = _integer(metadata, "confirmation_cut_ms")
    if (
        not origin < excursion < confirmation
        or excursion % 300_000
        or confirmation % 300_000
        or confirmation - excursion not in (300_000, 600_000)
        or candidate.entry_eligible_ts_ms != confirmation
        or candidate.decision_ts_ms != confirmation - 1
        or candidate.entry_expires_ts_ms != candidate.decision_ts_ms + 300_000
        or candidate.exit_plan.max_holding_ms != 120 * 60_000
        or candidate.exit_plan.trailing_activation_price is not None
        or candidate.exit_plan.trailing_distance is not None
        or candidate.signal_strength != 1.0
    ):
        raise ValueError("fixed event, first-return clocks, lifetime and barriers required")
    if quote_ms <= candidate.decision_ts_ms:
        raise ValueError("arrival cannot precede the decision")
    # This public native boundary validates the entire immutable typed prefix,
    # including every minute and the exact last close at quote_ms - 1.
    defense = native_defense(closed_prefix, origin_ms=origin, cut_ms=quote_ms)
    if closed_prefix[0].symbol != candidate.symbol:
        raise ValueError("candidate and source prefix symbol differ")
    _check(deadline)
    prior = tuple(row for row in closed_prefix if row.close_time_ms < excursion)
    if not prior or prior[-1].close_time_ms != excursion - 1:
        raise ValueError("complete frozen pre-excursion prefix required")
    history_sha = digest([candle_payload(row) for row in prior])
    expected_event = digest(
        {
            "policy_sha256": POLICY_SHA256,
            "origin_ms": origin,
            "symbol": candidate.symbol,
            "excursion_open_ms": excursion,
            "prior_history_sha256": history_sha,
        }
    )
    if history_sha != metadata["prior_history_sha256"] or expected_event != metadata["event_id"]:
        raise ValueError("frozen source prefix or event identity changed")
    # Select only the final complete 20 pre-event quarters plus the event's
    # one/two completed 5m bars. No future quote-minute extremes are supplied.
    last_quarter_end = excursion // 900_000 * 900_000
    feature_start = last_quarter_end - 20 * 900_000
    quarters = tuple(aggregate([row for row in prior if row.open_time_ms >= feature_start], "15m"))
    event_bars = tuple(
        aggregate([row for row in closed_prefix if excursion <= row.open_time_ms < confirmation], "5m")
    )
    features = frozen_reversal_features_from_bars(quarters, event_bars, excursion_open_ms=excursion)
    lower, upper, atr = features.channel_lower, features.channel_upper, features.atr15
    for key, value in (
        ("frozen_channel_lower", lower),
        ("frozen_channel_upper", upper),
        ("frozen_atr15", atr),
    ):
        if metadata[key] != frozen_float_text(value):
            raise ValueError("frozen numeric geometry differs from the pre-event source")
    previous_close = prior[-1].close
    first, returned = event_bars[0], event_bars[-1]
    lower_wick, upper_wick = first.low < lower, first.high > upper
    expected_side = Side.LONG if lower_wick else Side.SHORT
    if (
        not lower < previous_close < upper
        or lower_wick == upper_wick
        or candidate.side is not expected_side
        or not lower < returned.close < upper
        or candidate.reference_price != returned.close
        or (len(event_bars) == 2 and lower < first.close < upper)
        or any(bar.high >= upper if candidate.side is Side.LONG else bar.low <= lower for bar in event_bars)
    ):
        raise ValueError("original first-return event contract cannot be rewritten")
    stop = (
        features.event_low - 0.25 * atr if candidate.side is Side.LONG else features.event_high + 0.25 * atr
    )
    target = upper if candidate.side is Side.LONG else lower
    if (
        candidate.exit_plan.stop_price != stop
        or candidate.exit_plan.target_price != target
        or candidate.gross_reward_bps != abs(target - returned.close) / returned.close * 10_000
    ):
        raise ValueError("source-bound original stop, target and reward cannot change at arrival")
    expected_quote = entry_time(candidate, completion_ms, "STRICT_MINUTE_OPEN")
    if expected_quote is not None and quote_ms != expected_quote:
        raise ValueError("only the first strict minute quote is eligible; no later retry")
    elapsed = tuple(row for row in closed_prefix if row.open_time_ms >= confirmation)
    crossed = any(
        (row.low <= stop or row.high >= target)
        if candidate.side is Side.LONG
        else (row.high >= stop or row.low <= target)
        for row in elapsed
    )
    results = {}
    for scenario in scenarios:
        entry = fill_price(float(quote_open), candidate.side, True, scenario)
        sized = size_and_admit(
            side=candidate.side,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            equity_usd=10_000,
            costs=scenario.costs,
            limits=RiskLimits(maximum_stop_distance_bps=300),
        )
        if expected_quote is None:
            reason = "LIFETIME_EXPIRED_BEFORE_FIRST_MINUTE_OPEN"
        elif defense != "NORMAL":
            reason = defense
        elif crossed:
            reason = "FROZEN_BARRIER_TOUCHED_BEFORE_ARRIVAL"
        elif not lower < quote_open < upper:
            reason = "QUOTE_OUTSIDE_FROZEN_CHANNEL"
        elif not sized.accepted:
            reason = str(sized.reason)
        elif scenario.costs.estimated_round_trip_bps > 0.5 * sized.stop_distance_bps:
            reason = "INSUFFICIENT_COST_HEADROOM"
        else:
            reason = "GEOMETRY_FEASIBLE_ONLY"
        results[scenario.id] = {
            "intent_id": candidate.intent_id,
            "event_id": expected_event,
            "quote_ms": quote_ms,
            "completion_ms": completion_ms,
            "minute_open_price": quote_open,
            "modeled_entry_price": entry,
            "scenario": scenario.id,
            "planning_round_trip_bps": scenario.costs.estimated_round_trip_bps,
            "native_defense": defense,
            "original_stop_price": stop,
            "original_target_price": target,
            "stop_distance_bps": sized.stop_distance_bps,
            "net_reward_to_risk": sized.net_reward_to_risk,
            "geometry_feasible": reason == "GEOMETRY_FEASIBLE_ONLY",
            "reason": reason,
            "source_authenticity_admitted": False,
            "observed_bbo_or_fill": False,
            "trading_admitted": False,
        }
    _check(deadline)
    return results
