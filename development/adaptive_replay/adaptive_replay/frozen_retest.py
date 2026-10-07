"""Fixed, causal breakout/retest research hypothesis; no execution authority."""

from __future__ import annotations

import math
import time
from bisect import bisect_left
from dataclasses import asdict, dataclass

from kairos_core.contracts.regime_capability import CapabilityRegime
from kairos_core.enums import Side
from kairos_strategy.adaptive.config import DEFAULT_CONFIG, UNIVERSE
from kairos_strategy.adaptive.logic import _regime_at
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload
from kairos_strategy.timeframes import aggregate

from .historical_context import digest

STRATEGY_ID = "frozen_breakout_retest_v1"
MINUTE_MS = 60_000
FIVE_MINUTES_MS = 5 * MINUTE_MS
HISTORY_BARS = 54 * 60
MAX_PREFIX_BARS = 50_000


def fixed_retest_policy() -> dict:
    """Return the complete immutable-by-convention policy identity."""
    return {
        "id": STRATEGY_ID,
        "input": "CONTIGUOUS_CLOSED_1M_EXPLICIT_ORIGIN_EXPANDING_PREFIX",
        "warmup_ms": HISTORY_BARS * MINUTE_MS,
        "decision_cadence_ms": FIVE_MINUTES_MS,
        "channel_prior_5m_bars": 20,
        "breakout": "STRICT_CURRENT_CLOSE_CROSSES_PRIOR_20_HIGH_OR_LOW_FROM_INSIDE_OR_ON",
        "atr": "FINITE_TRUE_RANGE_MEAN_14_COMPLETED_5M_BARS_STRICTLY_BEFORE_BREAKOUT",
        "prior_extreme_bars": 48,
        "retest": "FIRST_DISTINCT_LATER_BAR_AGE_1_TO_5_TOUCH_AND_CLOSE_ON_ORIGINAL_LEVEL_SIDE",
        "reclaim": "NEXT_DISTINCT_BAR_CLOSE_BACK_ACROSS_LEVEL_BY_AGE_6",
        "adverse_invalidation_atr": 0.5,
        "setup_timeout_bars": 6,
        "stop_buffer_atr": 0.25,
        "stop_distance_atr": [0.5, 2.0],
        "stop_distance_bps": [10.0, 300.0],
        "planning_round_trip_bps": 20.0,
        "minimum_net_reward_risk": 1.25,
        "maximum_cost_stop_fraction": 0.5,
        "entry_lifetime_ms": FIVE_MINUTES_MS,
        "maximum_holding_ms": 120 * MINUTE_MS,
        "defense": "PINNED_NATIVE_REGIME_AT_EACH_CUT_CRASH_AND_TWO_COMPLETED_POST_SHOCK_HOURS_ABSTAIN",
        "crash_short_exception": False,
        "reset": "BLOCKED_SETUP_REQUIRES_LATER_CLOSE_INSIDE_ORIGINAL_CHANNEL; RESET_CANDLE_CANNOT_ARM",
        "target": "FROZEN_BREAKOUT_BAR_EXTREME_CAPPED_AT_CLOSER_PRIOR_48_BAR_EXTREME",
        "candidate_status": "RESEARCH_ONLY_NOT_PRODUCTION_REGISTERED",
    }


POLICY_SHA256 = digest(fixed_retest_policy())


@dataclass(frozen=True, slots=True)
class RetestDecision:
    symbol: str
    cut_ms: int
    state: str
    reason: str
    defense: str
    setup_id: str | None
    candidate: SleeveIntent | None
    breakout_cut_ms: int | None
    age_bars: int | None
    retest_cut_ms: int | None
    frozen_level: float | None
    frozen_atr5: float | None
    frozen_channel_lower: float | None
    frozen_channel_upper: float | None
    frozen_target: float | None
    frozen_history_sha256: str | None
    stop_price: float | None
    reference_price: float | None
    net_reward_to_risk: float | None
    transition: str
    consumed: bool


@dataclass(slots=True)
class _Setup:
    side: Side
    breakout_index: int
    breakout_cut_ms: int
    level: float
    atr: float
    channel_lower: float
    channel_upper: float
    target: float
    history_sha: str
    setup_id: str
    retest_index: int | None = None
    retest_cut_ms: int | None = None
    retest_low: float | None = None
    retest_high: float | None = None


def _check_prefix(candles: tuple[Candle, ...], origin_ms: int) -> str:
    if type(candles) is not tuple or not HISTORY_BARS <= len(candles) <= MAX_PREFIX_BARS:
        raise ValueError("bounded immutable 54h-or-longer candle tuple required")
    if type(origin_ms) is not int or origin_ms < 0 or origin_ms % FIVE_MINUTES_MS:
        raise ValueError("UTC five-minute-aligned explicit origin required")
    if type(candles[0]) is not Candle:
        raise ValueError("typed immutable candle required at explicit origin")
    if candles[0].open_time_ms != origin_ms:
        raise ValueError("explicit origin must equal the first candle open; reordered prefix rejected")
    symbol = candles[0].symbol
    if symbol not in UNIVERSE:
        raise ValueError("fixed five-symbol universe required")
    for index, row in enumerate(candles):
        if type(row) is not Candle:
            raise ValueError("typed immutable candle required")
        Candle(**asdict(row))
        if (
            row.symbol != symbol
            or row.timeframe != "1m"
            or row.open_time_ms != origin_ms + index * MINUTE_MS
            or row.close_time_ms != row.open_time_ms + MINUTE_MS - 1
        ):
            raise ValueError("mixed, unclosed, reordered or discontinuous one-minute prefix")
    return symbol


def _atr5_before(rows: tuple[Candle, ...], breakout_index: int) -> float:
    """Mean of the last 14 true ranges, all strictly before breakout bar."""
    if breakout_index < 15:
        return 0.0
    sample = rows[breakout_index - 14 : breakout_index]
    prior = rows[breakout_index - 15 : breakout_index - 1]
    if len(sample) != 14 or len(prior) != 14:
        return 0.0
    values = [
        max(bar.high - bar.low, abs(bar.high - prev.close), abs(bar.low - prev.close))
        for prev, bar in zip(prior, sample, strict=True)
    ]
    value = math.fsum(values) / 14
    return value if math.isfinite(value) and value > 0 else 0.0


def _native_defense_from_bars(rows5: list[Candle], hours: list[Candle], cut_ms: int) -> str:
    regime, last_shock = _regime_at(rows5, hours, cut_ms - 1, DEFAULT_CONFIG)
    if regime is CapabilityRegime.CRASH:
        return "CRASH"
    if last_shock is not None and (
        len(hours) < 2 or hours[-2].close_time_ms <= rows5[last_shock].close_time_ms
    ):
        return "POST_SHOCK_COOLDOWN"
    return "NORMAL"


def native_defense(candles: tuple[Candle, ...], *, origin_ms: int, cut_ms: int) -> str:
    """Return the pinned native crash/cooldown classification at an exact cut.

    ``candles`` must end at ``cut_ms - 1``. The helper uses only the latest
    complete 54h of validated one-minute history; incomplete UTC 5m/hour bars
    are omitted by the same pinned aggregator used by this module.
    """
    if type(candles) is not tuple or not HISTORY_BARS <= len(candles) <= MAX_PREFIX_BARS:
        raise ValueError("bounded immutable complete 54h candle tuple required")
    if (
        type(origin_ms) is not int
        or origin_ms < 0
        or origin_ms % MINUTE_MS
        or type(cut_ms) is not int
        or cut_ms <= origin_ms
        or cut_ms % MINUTE_MS
    ):
        raise ValueError("minute-aligned explicit origin and cut required")
    if type(candles[0]) is not Candle:
        raise ValueError("typed immutable candle required at explicit origin")
    if candles[0].open_time_ms != origin_ms or candles[-1].close_time_ms != cut_ms - 1:
        raise ValueError("prefix origin or exact final closed cut mismatch")
    symbol = candles[0].symbol
    if symbol not in UNIVERSE:
        raise ValueError("fixed five-symbol universe required")
    for index, row in enumerate(candles):
        if type(row) is not Candle:
            raise ValueError("typed immutable candle required")
        Candle(**asdict(row))
        if (
            row.symbol != symbol
            or row.timeframe != "1m"
            or row.open_time_ms != origin_ms + index * MINUTE_MS
            or row.close_time_ms != row.open_time_ms + MINUTE_MS - 1
        ):
            raise ValueError("mixed, unclosed, reordered or discontinuous one-minute prefix")
    rolling = candles[-HISTORY_BARS:]
    rows5 = aggregate(list(rolling), "5m")
    hours = aggregate(list(rolling), "1h")
    if len(rows5) < 600 or len(hours) < DEFAULT_CONFIG.slow_hours + 1:
        raise ValueError("54h prefix lacks complete native 5m/hour defense context")
    return _native_defense_from_bars(rows5, hours, cut_ms)


def _number(value: float) -> str:
    return format(value, ".17g")


def _decision(
    *,
    symbol: str,
    cut_ms: int,
    state: str,
    reason: str,
    defense: str,
    setup: _Setup | None,
    age: int | None,
    transition: str,
    consumed: bool = False,
    candidate: SleeveIntent | None = None,
    stop: float | None = None,
    reference: float | None = None,
    net_rr: float | None = None,
) -> RetestDecision:
    return RetestDecision(
        symbol=symbol,
        cut_ms=cut_ms,
        state=state,
        reason=reason,
        defense=defense,
        setup_id=None if setup is None else setup.setup_id,
        candidate=candidate,
        breakout_cut_ms=None if setup is None else setup.breakout_cut_ms,
        age_bars=age,
        retest_cut_ms=None if setup is None else setup.retest_cut_ms,
        frozen_level=None if setup is None else setup.level,
        frozen_atr5=None if setup is None else setup.atr,
        frozen_channel_lower=None if setup is None else setup.channel_lower,
        frozen_channel_upper=None if setup is None else setup.channel_upper,
        frozen_target=None if setup is None else setup.target,
        frozen_history_sha256=None if setup is None else setup.history_sha,
        stop_price=stop,
        reference_price=reference,
        net_reward_to_risk=net_rr,
        transition=transition,
        consumed=consumed,
    )


def _build_candidate(
    setup: _Setup, rows: tuple[Candle, ...], reclaim_index: int, cut_ms: int
) -> tuple[SleeveIntent | None, str, float, float, float]:
    reclaim = rows[reclaim_index]
    assert setup.retest_low is not None and setup.retest_high is not None
    if setup.side is Side.LONG:
        stop = min(setup.retest_low, reclaim.low) - 0.25 * setup.atr
        reward = setup.target - reclaim.close
    else:
        stop = max(setup.retest_high, reclaim.high) + 0.25 * setup.atr
        reward = reclaim.close - setup.target
    risk = abs(reclaim.close - stop)
    if not all(math.isfinite(v) and v > 0 for v in (stop, reclaim.close, setup.target, risk)):
        return None, "NON_EXECUTABLE_BARRIERS", stop, reclaim.close, 0.0
    risk_atr = risk / setup.atr
    risk_bps = risk / reclaim.close * 10_000
    reward_bps = max(0.0, reward) / reclaim.close * 10_000
    cost = 20.0
    stop_cost = cost * max(1.0, stop / reclaim.close)
    reward_cost = cost * max(1.0, setup.target / reclaim.close)
    net_rr = max(0.0, reward_bps - reward_cost) / (risk_bps + stop_cost)
    if reward <= 0:
        reason = "TARGET_NOT_BEYOND_RECLAIM"
    elif not 0.5 <= risk_atr <= 2.0:
        reason = "STOP_OUTSIDE_ATR_BOUNDS"
    elif not 10.0 <= risk_bps <= 300.0:
        reason = "STOP_OUTSIDE_BPS_BOUNDS"
    elif cost > 0.5 * risk_bps:
        reason = "INSUFFICIENT_COST_HEADROOM"
    elif net_rr < 1.25:
        reason = "NET_REWARD_RISK_TOO_LOW"
    else:
        reason = "CANDIDATE_ACCEPTED"
    if reason != "CANDIDATE_ACCEPTED":
        return None, reason, stop, reclaim.close, net_rr
    metadata = tuple(
        sorted(
            {
                "policy_sha256": POLICY_SHA256,
                "explicit_origin_ms": str(rows[0].open_time_ms),
                "setup_id": setup.setup_id,
                "breakout_cut_ms": str(setup.breakout_cut_ms),
                "frozen_level": _number(setup.level),
                "frozen_atr5": _number(setup.atr),
                "frozen_channel_lower": _number(setup.channel_lower),
                "frozen_channel_upper": _number(setup.channel_upper),
                "frozen_target": _number(setup.target),
                "frozen_history_sha256": setup.history_sha,
                "stop_buffer_atr": "0.25",
                "planning_cost_bps": "20",
                "planning_authority": "ASSUMPTION_NOT_VENUE_MEASUREMENT",
            }.items()
        )
    )
    intent = SleeveIntent(
        sleeve_id=STRATEGY_ID,
        symbol=reclaim.symbol,
        side=setup.side,
        decision_ts_ms=cut_ms - 1,
        entry_eligible_ts_ms=cut_ms,
        entry_expires_ts_ms=cut_ms - 1 + FIVE_MINUTES_MS,
        reference_price=reclaim.close,
        signal_strength=1.0,
        gross_reward_bps=max(0.0, reward_bps),
        exit_plan=ExitPlan(stop_price=stop, target_price=setup.target, max_holding_ms=120 * MINUTE_MS),
        metadata=metadata,
    )
    return intent, reason, stop, reclaim.close, net_rr


def generate_frozen_retest(
    candles: tuple[Candle, ...], *, origin_ms: int, deadline: float | None = None
) -> tuple[RetestDecision, ...]:
    """Generate every post-warmup UTC five-minute decision from one explicit origin.

    The generator is deterministic and pure with respect to its input prefix. It
    performs no provider, filesystem, economic replay, or production registration
    work. Passing a longer prefix preserves all prior outcomes byte-for-byte.
    """
    symbol = _check_prefix(candles, origin_ms)
    if deadline is not None and (
        isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline)
    ):
        raise ValueError("finite monotonic deadline or None required")
    policy_sha = POLICY_SHA256
    # Aggregate once; all cut windows below are indexed views, never rebuilt from
    # one-minute history per cut.
    five_all = aggregate(list(candles), "5m")
    hour_all = aggregate(list(candles), "1h")
    if len(five_all) != len(candles) // 5:
        raise ValueError("complete UTC five-minute aggregation required")
    five = tuple(five_all)
    hours = tuple(hour_all)
    hour_closes = tuple(hour.close_time_ms for hour in hours)
    hour_opens = tuple(hour.open_time_ms for hour in hours)
    warmup_cut = origin_ms + HISTORY_BARS * MINUTE_MS
    decisions: list[RetestDecision] = []
    setup: _Setup | None = None
    blocked_channel: tuple[float, float] | None = None
    state = "IDLE"

    for index, bar in enumerate(five):
        cut_ms = bar.close_time_ms + 1
        if cut_ms < warmup_cut or cut_ms % FIVE_MINUTES_MS:
            continue
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("frozen retest generation deadline reached")
        start5 = max(0, index - 647)
        rows5 = list(five[start5 : index + 1])
        # Native guard gets only complete hour candles known at this decision.
        hour_end = bisect_left(hour_closes, cut_ms)
        rolling_hour_start = bisect_left(hour_opens, cut_ms - HISTORY_BARS * MINUTE_MS)
        hour_rows = list(hours[rolling_hour_start:hour_end])
        defense = _native_defense_from_bars(rows5, hour_rows, cut_ms)
        age = None if setup is None else index - setup.breakout_index

        if state == "BLOCKED":
            assert blocked_channel is not None
            if blocked_channel[0] <= bar.close <= blocked_channel[1]:
                state, setup, blocked_channel = "IDLE", None, None
                decisions.append(
                    _decision(
                        symbol=symbol,
                        cut_ms=cut_ms,
                        state="IDLE",
                        reason="RESET_TO_IDLE",
                        defense=defense,
                        setup=None,
                        age=None,
                        transition="BLOCKED_TO_IDLE_RESET",
                    )
                )
            else:
                decisions.append(
                    _decision(
                        symbol=symbol,
                        cut_ms=cut_ms,
                        state="BLOCKED",
                        reason="WAITING_FOR_CHANNEL_RESET",
                        defense=defense,
                        setup=setup,
                        age=age,
                        transition="BLOCKED_HOLD",
                        consumed=True,
                    )
                )
            continue

        if defense != "NORMAL":
            if setup is not None:
                blocked_channel = (setup.channel_lower, setup.channel_upper)
                state = "BLOCKED"
                reason = "CRASH_GUARD" if defense == "CRASH" else "POST_SHOCK_COOLDOWN"
                decisions.append(
                    _decision(
                        symbol=symbol,
                        cut_ms=cut_ms,
                        state="BLOCKED",
                        reason=reason,
                        defense=defense,
                        setup=setup,
                        age=age,
                        transition="SETUP_CANCELLED_BY_NATIVE_DEFENSE",
                        consumed=True,
                    )
                )
            else:
                decisions.append(
                    _decision(
                        symbol=symbol,
                        cut_ms=cut_ms,
                        state="IDLE",
                        reason=defense,
                        defense=defense,
                        setup=None,
                        age=None,
                        transition="IDLE_DEFENSE_ABSTAIN",
                    )
                )
            continue

        if setup is None:
            if index < 48:
                decisions.append(
                    _decision(
                        symbol=symbol,
                        cut_ms=cut_ms,
                        state="IDLE",
                        reason="INSUFFICIENT_PRIOR_BARS",
                        defense=defense,
                        setup=None,
                        age=None,
                        transition="IDLE_HOLD",
                    )
                )
                continue
            prior20 = five[index - 20 : index]
            prior48 = five[index - 48 : index]
            lower = min(row.low for row in prior20)
            upper = max(row.high for row in prior20)
            prev_close = five[index - 1].close
            direction: Side | None = None
            if prev_close <= upper and bar.close > upper:
                direction = Side.LONG
            elif prev_close >= lower and bar.close < lower:
                direction = Side.SHORT
            if direction is None:
                decisions.append(
                    _decision(
                        symbol=symbol,
                        cut_ms=cut_ms,
                        state="IDLE",
                        reason="NO_CHANNEL_CROSS",
                        defense=defense,
                        setup=None,
                        age=None,
                        transition="IDLE_HOLD",
                    )
                )
                continue
            atr = _atr5_before(five, index)
            if atr <= 0:
                decisions.append(
                    _decision(
                        symbol=symbol,
                        cut_ms=cut_ms,
                        state="IDLE",
                        reason="INVALID_PRIOR_ATR",
                        defense=defense,
                        setup=None,
                        age=None,
                        transition="BREAKOUT_REJECTED_BEFORE_ARM",
                    )
                )
                continue
            level = upper if direction is Side.LONG else lower
            breakout_extreme = bar.high if direction is Side.LONG else bar.low
            prior_extreme = (
                max(row.high for row in prior48)
                if direction is Side.LONG
                else min(row.low for row in prior48)
            )
            target = (
                min(breakout_extreme, prior_extreme)
                if direction is Side.LONG and prior_extreme > level
                else max(breakout_extreme, prior_extreme)
                if direction is Side.SHORT and prior_extreme < level
                else breakout_extreme
            )
            history_sha = digest([candle_payload(row) for row in candles[: (index + 1) * 5]])
            setup_id = digest(
                {
                    "policy_sha256": policy_sha,
                    "origin_ms": origin_ms,
                    "symbol": symbol,
                    "breakout_cut_ms": cut_ms,
                    "history_sha256": history_sha,
                }
            )
            setup = _Setup(
                side=direction,
                breakout_index=index,
                breakout_cut_ms=cut_ms,
                level=level,
                atr=atr,
                channel_lower=lower,
                channel_upper=upper,
                target=target,
                history_sha=history_sha,
                setup_id=setup_id,
            )
            state = "ARMED"
            decisions.append(
                _decision(
                    symbol=symbol,
                    cut_ms=cut_ms,
                    state=state,
                    reason="BREAKOUT_ARMED",
                    defense=defense,
                    setup=setup,
                    age=0,
                    transition="IDLE_TO_ARMED",
                )
            )
            continue

        assert age is not None
        adverse = (
            bar.close < setup.level - 0.5 * setup.atr
            if setup.side is Side.LONG
            else (bar.close > setup.level + 0.5 * setup.atr)
        )
        if adverse:
            blocked_channel = (setup.channel_lower, setup.channel_upper)
            state = "BLOCKED"
            decisions.append(
                _decision(
                    symbol=symbol,
                    cut_ms=cut_ms,
                    state=state,
                    reason="ADVERSE_INVALIDATION",
                    defense=defense,
                    setup=setup,
                    age=age,
                    transition="SETUP_TO_BLOCKED_INVALIDATED",
                    consumed=True,
                )
            )
            continue

        if setup.retest_index is None and 1 <= age <= 5:
            touched = (
                bar.low <= setup.level and bar.close <= setup.level
                if setup.side is Side.LONG
                else (bar.high >= setup.level and bar.close >= setup.level)
            )
            if touched:
                setup.retest_index = index
                setup.retest_cut_ms = cut_ms
                setup.retest_low = bar.low
                setup.retest_high = bar.high
                state = "RETESTED"
                decisions.append(
                    _decision(
                        symbol=symbol,
                        cut_ms=cut_ms,
                        state=state,
                        reason="FIRST_RETEST_RECORDED",
                        defense=defense,
                        setup=setup,
                        age=age,
                        transition="ARMED_TO_RETESTED_FIRST_TOUCH",
                    )
                )
                continue
        if setup.retest_index is not None and index > setup.retest_index:
            assert setup.retest_low is not None and setup.retest_high is not None
            setup.retest_low = min(setup.retest_low, bar.low)
            setup.retest_high = max(setup.retest_high, bar.high)
        if setup.retest_index is not None and index > setup.retest_index and age <= 6:
            reclaimed = bar.close > setup.level if setup.side is Side.LONG else bar.close < setup.level
            if reclaimed:
                candidate, reason, stop, reference, net_rr = _build_candidate(setup, five, index, cut_ms)
                blocked_channel = (setup.channel_lower, setup.channel_upper)
                state = "BLOCKED"
                decisions.append(
                    _decision(
                        symbol=symbol,
                        cut_ms=cut_ms,
                        state=state,
                        reason=reason,
                        defense=defense,
                        setup=setup,
                        age=age,
                        transition="RECLAIM_CONSUMED_NO_RETRY",
                        consumed=True,
                        candidate=candidate,
                        stop=stop,
                        reference=reference,
                        net_rr=net_rr,
                    )
                )
                continue

        if age >= 6:
            blocked_channel = (setup.channel_lower, setup.channel_upper)
            state = "BLOCKED"
            decisions.append(
                _decision(
                    symbol=symbol,
                    cut_ms=cut_ms,
                    state=state,
                    reason="SETUP_TIMEOUT",
                    defense=defense,
                    setup=setup,
                    age=age,
                    transition="SETUP_TO_BLOCKED_EXPIRED",
                    consumed=True,
                )
            )
            continue
        state = "ARMED" if setup.retest_index is None else "RETESTED"
        decisions.append(
            _decision(
                symbol=symbol,
                cut_ms=cut_ms,
                state=state,
                reason="WAITING_FOR_FIRST_RETEST" if setup.retest_index is None else "WAITING_FOR_RECLAIM",
                defense=defense,
                setup=setup,
                age=age,
                transition="SETUP_HOLD",
            )
        )
    return tuple(decisions)
