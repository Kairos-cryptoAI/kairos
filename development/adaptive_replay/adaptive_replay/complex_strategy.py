"""One compact research complex; immutable native sleeves, no trading authority.

Breakout retains its expanding prefix and adaptive retains its rolling 54h
window. Context proposals are direction-only; this module owns their geometry.
No providers, quotas, production registration, parameter search or execution.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from kairos_core.enums import Side
from kairos_strategy.adaptive.config import DEFAULT_CONFIG, STRATEGY_ID, UNIVERSE
from kairos_strategy.adaptive.logic import AdaptiveDecision, evaluate_adaptive
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload
from kairos_strategy.registry import generate_sleeve_intents
from kairos_strategy.sleeves import TrendBreakoutConfig
from kairos_strategy.timeframes import aggregate

from .historical_context import _clock, _sha, digest
from .historical_replay import _validate_candidate

COMPLEX_ID = "compact_context_complex_v1"
BREAKOUT_ID = "trend_breakout_v1"
MAPPER_ID = "context_atr_proposal_v1"
MINUTE = 60_000
HISTORY_BARS = 3_240
MAX_PREFIX_BARS = 50_000
MAPPER_POLICY = {
    "id": MAPPER_ID,
    "atr": "FINITE_TRUE_RANGE_MEAN_14_COMPLETED_15M",
    "stop_atr": 1.25,
    "minimum_stop_atr": 0.5,
    "maximum_stop_atr": 2.0,
    "maximum_stop_bps": 300.0,
    "target_r": 2.0,
    "minimum_net_reward_risk": 1.25,
    "planning_round_trip_bps": 20.0,
    "maximum_cost_stop_fraction": 0.5,
    "entry_lifetime_ms": 300_000,
    "trend_holding_ms": 7_200_000,
    "range_holding_ms": 3_600_000,
    "crash": "ONLY_UNCHANGED_ADAPTIVE_CONTROLLED_RETEST_SHORT",
    "post_shock_cooldown": "ABSTAIN",
    "sizing": "COMMON_COST_RISK_V1_NO_MODEL_CONFIDENCE_UPLIFT",
}


def _history(rows: tuple[Candle, ...], cut_ms: int, prefix_start_ms: int) -> None:
    _clock(cut_ms)
    _clock(prefix_start_ms)
    if cut_ms % (5 * MINUTE) or prefix_start_ms % MINUTE:
        raise ValueError("exact closed five-minute cut and minute prefix origin required")
    if type(rows) is not tuple or not HISTORY_BARS <= len(rows) <= MAX_PREFIX_BARS:
        raise ValueError("bounded complete 54h-or-longer immutable prefix required")
    if rows[0].open_time_ms != prefix_start_ms or rows[-1].close_time_ms != cut_ms - 1:
        raise ValueError("exact expanding prefix origin and closed cut required")
    symbol = rows[-1].symbol
    if symbol not in UNIVERSE:
        raise ValueError("fixed five-symbol universe required")
    for index, row in enumerate(rows):
        if type(row) is not Candle:
            raise ValueError("typed closed candle required")
        Candle(**asdict(row))  # recheck even a forged frozen dataclass
        if (
            row.symbol != symbol
            or row.timeframe != "1m"
            or row.open_time_ms != prefix_start_ms + index * MINUTE
            or row.close_time_ms != row.open_time_ms + MINUTE - 1
        ):
            raise ValueError("mixed, future, unclosed or discontinuous prefix")


def crash_defense(decision: AdaptiveDecision, rows: tuple[Candle, ...]) -> str:
    """Reuse the exact native shock and two-completed-hour recovery condition."""
    if decision.status not in {"INTENT", "NO_INTENT"}:
        return "SOURCE_UNAVAILABLE"
    if decision.regime.value == "CRASH":
        return "CRASH"
    shock = dict(decision.features).get("last_shock_ms", "NONE")
    if shock != "NONE":
        hours = aggregate(list(rows[-HISTORY_BARS:]), "1h")
        if len(hours) < 2 or hours[-2].close_time_ms <= int(shock):
            return "POST_SHOCK_COOLDOWN"
    return "NORMAL"


@dataclass(frozen=True)
class ComplexDecision:
    symbol: str
    cut_ms: int
    state: str
    reason: str
    regime: str
    defense: str
    candidate: SleeveIntent | None
    candidate_ids: tuple[str, ...]
    dropped_ids: tuple[str, ...]
    expanding_prefix_sha256: str
    rolling_history_sha256: str


def select_technical(
    candidates: tuple[SleeveIntent, ...],
) -> tuple[SleeveIntent | None, str, tuple[str, ...]]:
    """Opposite sides abstain; same side keeps adaptive first, exactly once."""
    if not candidates:
        return None, "NO_TECHNICAL_CANDIDATE", ()
    for candidate in candidates:
        _validate_candidate(candidate)
        if candidate.sleeve_id not in {STRATEGY_ID, BREAKOUT_ID}:
            raise ValueError("only the two fixed native families belong to this complex")
    if len({(c.symbol, c.decision_ts_ms, c.entry_eligible_ts_ms) for c in candidates}) != 1:
        raise ValueError("technical candidates must belong to one original symbol/cut")
    if len({c.intent_id for c in candidates}) != len(candidates):
        raise ValueError("duplicate native candidate identity")
    ordered = sorted(candidates, key=lambda c: (c.sleeve_id != STRATEGY_ID, c.intent_id))
    if len({c.side for c in ordered}) > 1:
        return None, "OPPOSITE_TECHNICAL_ABSTAIN", tuple(c.intent_id for c in ordered)
    return ordered[0], "TECHNICAL_SELECTED", tuple(c.intent_id for c in ordered[1:])


def evaluate_complex(prefix: tuple[Candle, ...], *, prefix_start_ms: int, cut_ms: int) -> ComplexDecision:
    """Evaluate one fixed cut without future bars or reinitializing native EMA/ATR."""
    _history(prefix, cut_ms, prefix_start_ms)
    rolling = prefix[-HISTORY_BARS:]
    adaptive = evaluate_adaptive(rolling)
    defense = crash_defense(adaptive, rolling)
    candidates: list[SleeveIntent] = []
    dropped: list[str] = []
    if adaptive.intent is not None:
        _validate_candidate(adaptive.intent)
        candidates.append(adaptive.intent)
    # This must be the expanding prefix, not adaptive's rolling lookback.
    native = generate_sleeve_intents(BREAKOUT_ID, list(prefix), TrendBreakoutConfig())
    for intent in native:
        if intent.decision_ts_ms != cut_ms - 1:
            continue
        _validate_candidate(intent)
        if intent.symbol != prefix[-1].symbol or intent.entry_eligible_ts_ms != cut_ms:
            raise ValueError("native breakout changed its original decision identity")
        if defense != "NORMAL":
            dropped.append(intent.intent_id)
        else:
            candidates.append(intent)
    if defense == "SOURCE_UNAVAILABLE":
        candidate, reason, collision_drops = None, "ADAPTIVE_CONTEXT_UNAVAILABLE", ()
        dropped.extend(c.intent_id for c in candidates)
    else:
        candidate, reason, collision_drops = select_technical(tuple(candidates))
    dropped.extend(collision_drops)
    return ComplexDecision(
        symbol=prefix[-1].symbol,
        cut_ms=cut_ms,
        state="UNAVAILABLE"
        if defense == "SOURCE_UNAVAILABLE"
        else "CONFLICT"
        if reason == "OPPOSITE_TECHNICAL_ABSTAIN"
        else "QUIET"
        if candidate is None
        else "CANDIDATE",
        reason=reason,
        regime=adaptive.regime.value,
        defense=defense,
        candidate=candidate,
        candidate_ids=tuple(c.intent_id for c in candidates),
        dropped_ids=tuple(sorted(dropped)),
        expanding_prefix_sha256=digest([candle_payload(row) for row in prefix]),
        rolling_history_sha256=digest([candle_payload(row) for row in rolling]),
    )


@dataclass(frozen=True)
class MappedProposal:
    proposal: str
    state: str
    reason: str
    candidate: SleeveIntent | None
    history_sha256: str
    assessment_sha256: str
    policy_sha256: str

    @property
    def mapping_id(self) -> str:
        return digest(asdict(self))


def map_context_proposal(
    proposal: str,
    rows: tuple[Candle, ...],
    *,
    cut_ms: int,
    assessment_sha256: str,
) -> MappedProposal:
    """Map a model direction into a single hash-bound price/risk template.

    No technical entry pattern is required in an ordinary quiet slot. This is
    intentionally a new, unqualified hypothesis. Crash protection still applies.
    It does not accept model prices, targets, confidence, quantity or leverage.
    """
    _sha(assessment_sha256)
    if proposal not in {"NONE", "LONG", "SHORT"}:
        raise ValueError("strict model direction required")
    if len(rows) != HISTORY_BARS:
        raise ValueError("proposal mapper requires the exact rolling 54h history")
    _history(rows, cut_ms, cut_ms - HISTORY_BARS * MINUTE)
    history_sha = digest([candle_payload(row) for row in rows])
    policy_sha = digest(MAPPER_POLICY)

    def result(reason: str, candidate: SleeveIntent | None = None) -> MappedProposal:
        return MappedProposal(
            proposal,
            "MAPPED" if candidate is not None else "ABSTAIN",
            reason,
            candidate,
            history_sha,
            assessment_sha256,
            policy_sha,
        )

    if proposal == "NONE":
        return result("MODEL_PROPOSED_NONE")
    adaptive = evaluate_adaptive(rows)
    defense = crash_defense(adaptive, rows)
    if defense == "SOURCE_UNAVAILABLE":
        return result("CAUSAL_PRICE_CONTEXT_UNAVAILABLE")
    if defense == "POST_SHOCK_COOLDOWN":
        return result("POST_SHOCK_COOLDOWN")
    if defense == "CRASH":
        if proposal == "SHORT" and adaptive.intent is not None and adaptive.intent.side is Side.SHORT:
            return result("UNCHANGED_CONTROLLED_RETEST_SHORT", adaptive.intent)
        return result("CRASH_NO_CONTROLLED_RETEST")
    rows15 = aggregate(list(rows), "15m")
    tail = rows15[-15:]
    if len(tail) != 15:
        return result("COMPLETE_VOLATILITY_CONTEXT_REQUIRED")
    atr = (
        math.fsum(
            max(row.high - row.low, abs(row.high - prior.close), abs(row.low - prior.close))
            for prior, row in zip(tail, tail[1:], strict=False)
        )
        / 14
    )
    reference = rows[-1].close
    risk = MAPPER_POLICY["stop_atr"] * atr
    sign = 1 if proposal == "LONG" else -1
    stop, target = reference - sign * risk, reference + sign * MAPPER_POLICY["target_r"] * risk
    if not all(math.isfinite(v) and v > 0 for v in (atr, risk, stop, target)):
        return result("NON_EXECUTABLE_BARRIERS")
    risk_bps = risk / reference * 10_000
    reward_bps = abs(target - reference) / reference * 10_000
    cost = MAPPER_POLICY["planning_round_trip_bps"]
    net_rr = max(0.0, reward_bps - cost * max(1.0, target / reference)) / (
        risk_bps + cost * max(1.0, stop / reference)
    )
    if not MAPPER_POLICY["minimum_stop_atr"] * atr <= risk <= MAPPER_POLICY["maximum_stop_atr"] * atr:
        return result("STOP_OUTSIDE_ATR_BOUNDS")
    if risk_bps > MAPPER_POLICY["maximum_stop_bps"]:
        return result("STOP_DISTANCE_TOO_WIDE")
    if (
        cost > MAPPER_POLICY["maximum_cost_stop_fraction"] * risk_bps
        or net_rr < MAPPER_POLICY["minimum_net_reward_risk"]
    ):
        return result("INSUFFICIENT_COST_HEADROOM")
    intent = SleeveIntent(
        sleeve_id=MAPPER_ID,
        symbol=rows[-1].symbol,
        side=Side.LONG if proposal == "LONG" else Side.SHORT,
        decision_ts_ms=cut_ms - 1,
        entry_eligible_ts_ms=cut_ms,
        entry_expires_ts_ms=cut_ms - 1 + MAPPER_POLICY["entry_lifetime_ms"],
        reference_price=reference,
        signal_strength=1.0,  # rule marker, never a model-confidence sizing input
        gross_reward_bps=reward_bps,
        exit_plan=ExitPlan(
            stop_price=stop,
            target_price=target,
            max_holding_ms=MAPPER_POLICY["range_holding_ms"]
            if adaptive.regime.value == "RANGE"
            else MAPPER_POLICY["trend_holding_ms"],
        ),
        metadata=tuple(
            sorted(
                {
                    "mapper_policy_sha256": policy_sha,
                    "assessment_sha256": assessment_sha256,
                    "causal_history_sha256": history_sha,
                    "frozen_atr15": format(atr, ".17g"),
                    "planning_cost_authority": "ASSUMPTION_NOT_VENUE_MEASUREMENT",
                    "planning_net_reward_risk": format(net_rr, ".17g"),
                }.items()
            )
        ),
    )
    return result("FIXED_CAUSAL_ATR_TEMPLATE", intent)


def fixed_complex_policy() -> dict:
    """New protocol values; old native configurations/evaluators stay untouched."""
    return {
        "id": COMPLEX_ID,
        "families": [BREAKOUT_ID, STRATEGY_ID],
        "breakout_config": asdict(TrendBreakoutConfig()),
        "adaptive_config": asdict(DEFAULT_CONFIG),
        "native_history": "EXACT_54H_ORIGIN_EXPANDING_PREFIX",
        "adaptive_history": "EXACT_ROLLING_3240_CLOSED_1M",
        "decision_cadence_ms": 300_000,
        "same_side_priority": [STRATEGY_ID, BREAKOUT_ID],
        "opposite_side": "ABSTAIN_NO_RESURRECTION",
        "crash_defense": "NATIVE_CRASH_AND_TWO_COMPLETED_POST_SHOCK_HOURS",
        "proposal_mapper": dict(MAPPER_POLICY),
        "daily_trade_quota": None,
        "fixed_income_target": None,
        "right_tail_role": "REFERENCE_ONLY_NOT_INTRADAY_ENTRY",
        "production_registration": False,
    }
