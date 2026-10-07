"""First-arrival geometry diagnostic, not venue, risk, or trading admission.

The caller supplies only a closed prefix and the next minute's OPEN, not that
minute's future high/low/close. Frozen barriers are never moved to admit entry.
Hash equality binds supplied history; it does not authenticate a provider.
"""

from __future__ import annotations

import math
import re

from kairos_backtest.cost_risk import RiskLimits, size_and_admit
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import SleeveIntent
from kairos_strategy.provenance import candle_payload

from .engine import CostScenario, entry_time, fill_price
from .frozen_retest import POLICY_SHA256, STRATEGY_ID, native_defense
from .historical_context import digest
from .historical_replay import _validate_candidate

HASH = re.compile(r"^[0-9a-f]{64}$")
META_KEYS = {
    "policy_sha256",
    "explicit_origin_ms",
    "setup_id",
    "breakout_cut_ms",
    "frozen_level",
    "frozen_atr5",
    "frozen_channel_lower",
    "frozen_channel_upper",
    "frozen_target",
    "frozen_history_sha256",
    "stop_buffer_atr",
    "planning_cost_bps",
    "planning_authority",
}


def _number(metadata: dict[str, str], key: str) -> float:
    value = float(metadata[key])
    if not math.isfinite(value) or value <= 0:
        raise ValueError("positive finite frozen geometry required")
    return value


def inspect_first_arrival(
    candidate: SleeveIntent,
    closed_prefix: tuple[Candle, ...],
    *,
    completion_ms: int,
    quote_ms: int,
    quote_open: float,
    scenario: CostScenario,
) -> dict:
    """Inspect exactly the first strict minute-open, with no later retry.

    `geometry_feasible` is conditional on declared costs and a 10000-dollar
    reference sizing account. No allocation, source admission, or fill occurs.
    The generator's candidate is a research input, never a signed live order.
    """
    _validate_candidate(candidate)
    if candidate.sleeve_id != STRATEGY_ID:
        raise ValueError("new frozen-retest identity required; native candidates are unchanged")
    if type(completion_ms) is not int or completion_ms < candidate.decision_ts_ms:
        raise ValueError("completion must be an integer not earlier than decision")
    if type(quote_ms) is not int or quote_ms < 0 or quote_ms % 60_000:
        raise ValueError("exact UTC minute-open clock required")
    if type(quote_open) not in (int, float) or not math.isfinite(quote_open) or quote_open <= 0:
        raise ValueError("positive finite minute-open price required")
    if type(scenario) is not CostScenario:
        raise ValueError("typed fixed cost scenario required")
    # Reconstruction detects unchecked alteration of frozen dataclass fields.
    CostScenario(**scenario.__dict__)
    metadata = dict(candidate.metadata)
    if set(metadata) != META_KEYS or metadata["policy_sha256"] != POLICY_SHA256:
        raise ValueError("complete exact frozen policy metadata required")
    if (
        metadata["stop_buffer_atr"] != "0.25"
        or metadata["planning_cost_bps"] != "20"
        or metadata["planning_authority"] != "ASSUMPTION_NOT_VENUE_MEASUREMENT"
    ):
        raise ValueError("original planning assumptions cannot be changed at arrival")
    if any(not HASH.fullmatch(metadata[k]) for k in ("setup_id", "frozen_history_sha256")):
        raise ValueError("complete frozen setup and history hashes required")
    for key in ("explicit_origin_ms", "breakout_cut_ms"):
        if not metadata[key].isdigit() or str(int(metadata[key])) != metadata[key]:
            raise ValueError("canonical frozen integer clock required")
    origin, breakout = int(metadata["explicit_origin_ms"]), int(metadata["breakout_cut_ms"])
    if not origin < breakout < candidate.entry_eligible_ts_ms or breakout % 300_000:
        raise ValueError("breakout must strictly precede distinct reclaim")
    if (
        candidate.entry_eligible_ts_ms != candidate.decision_ts_ms + 1
        or candidate.entry_eligible_ts_ms % 300_000
        or candidate.entry_expires_ts_ms != candidate.decision_ts_ms + 300_000
        or candidate.exit_plan.max_holding_ms != 120 * 60_000
    ):
        raise ValueError("new intent clocks/barriers cannot alter native or frozen lifetimes")
    if quote_ms <= candidate.decision_ts_ms:
        raise ValueError("arrival cannot precede the decision")
    defense = native_defense(closed_prefix, origin_ms=origin, cut_ms=quote_ms)
    if closed_prefix[0].symbol != candidate.symbol:
        raise ValueError("candidate and closed prefix symbol differ")
    frozen_history = [candle_payload(row) for row in closed_prefix if row.close_time_ms < breakout]
    history_sha = digest(frozen_history)
    if (
        history_sha != metadata["frozen_history_sha256"]
        or digest(
            {
                "policy_sha256": POLICY_SHA256,
                "origin_ms": origin,
                "symbol": candidate.symbol,
                "breakout_cut_ms": breakout,
                "history_sha256": history_sha,
            }
        )
        != metadata["setup_id"]
    ):
        raise ValueError("breakout source prefix or deterministic setup identity changed")
    level, atr = _number(metadata, "frozen_level"), _number(metadata, "frozen_atr5")
    lower, upper = _number(metadata, "frozen_channel_lower"), _number(metadata, "frozen_channel_upper")
    target = _number(metadata, "frozen_target")
    if lower >= upper or level != (upper if candidate.side is Side.LONG else lower):
        raise ValueError("broken boundary must be the original frozen channel boundary")
    if target != candidate.exit_plan.target_price:
        raise ValueError("target cannot be extended or replaced at arrival")
    expected_quote = entry_time(candidate, completion_ms, "STRICT_MINUTE_OPEN")
    entry = fill_price(float(quote_open), candidate.side, True, scenario)
    decision = size_and_admit(
        side=candidate.side,
        entry_price=entry,
        stop_price=candidate.exit_plan.stop_price,
        target_price=target,
        equity_usd=10_000,
        costs=scenario.costs,
        limits=RiskLimits(maximum_stop_distance_bps=300),
    )
    stop_atr = abs(entry - candidate.exit_plan.stop_price) / atr
    elapsed = tuple(row for row in closed_prefix if row.open_time_ms > candidate.decision_ts_ms)
    stop, touched_target = candidate.exit_plan.stop_price, target
    crossed = any(
        (row.low <= stop or row.high >= touched_target)
        if candidate.side is Side.LONG
        else (row.high >= stop or row.low <= touched_target)
        for row in elapsed
    )
    level_lost = quote_open <= level if candidate.side is Side.LONG else quote_open >= level
    if expected_quote is None:
        reason = "LIFETIME_EXPIRED_BEFORE_FIRST_MINUTE_OPEN"
    elif quote_ms != expected_quote:
        raise ValueError("only the first strict quote is eligible; no retry or backdating")
    elif defense != "NORMAL":
        reason = defense
    elif crossed:
        reason = "FROZEN_BARRIER_TOUCHED_BEFORE_ARRIVAL"
    elif level_lost:
        reason = "FROZEN_LEVEL_LOST_AT_ARRIVAL"
    elif not 0.5 <= stop_atr <= 2.0:
        reason = "STOP_OUTSIDE_FROZEN_ATR_BOUNDS"
    elif not decision.accepted:
        reason = str(decision.reason)
    elif scenario.costs.estimated_round_trip_bps > 0.5 * decision.stop_distance_bps:
        reason = "INSUFFICIENT_COST_HEADROOM"
    else:
        reason = "GEOMETRY_FEASIBLE_ONLY"
    return {
        "intent_id": candidate.intent_id,
        "setup_id": metadata["setup_id"],
        "quote_ms": quote_ms,
        "completion_ms": completion_ms,
        "minute_open_price": quote_open,
        "modeled_entry_price": entry,
        "scenario": scenario.id,
        "planning_round_trip_bps": scenario.costs.estimated_round_trip_bps,
        "native_defense": defense,
        "original_stop_price": stop,
        "original_target_price": target,
        "stop_distance_atr5": stop_atr,
        "stop_distance_bps": decision.stop_distance_bps,
        "net_reward_to_risk": decision.net_reward_to_risk,
        "geometry_feasible": reason == "GEOMETRY_FEASIBLE_ONLY",
        "reason": reason,
        "source_authenticity_admitted": False,
        "observed_bbo_or_fill": False,
        "trading_admitted": False,
    }
