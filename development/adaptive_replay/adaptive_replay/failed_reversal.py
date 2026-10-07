"""Fixed failed-breakout channel-reversal hypothesis; research only."""

from __future__ import annotations

import math
import time
from bisect import bisect_left
from dataclasses import asdict, dataclass

from kairos_core.enums import Side
from kairos_strategy.adaptive.config import UNIVERSE
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload
from kairos_strategy.timeframes import aggregate

from .frozen_retest import _native_defense_from_bars
from .historical_context import digest

STRATEGY_ID = "failed_breakout_reversal_v1"
MINUTE_MS = 60_000
FIVE_MINUTES_MS = 5 * MINUTE_MS
FIFTEEN_MINUTES_MS = 15 * MINUTE_MS
HISTORY_BARS = 54 * 60
MAX_PREFIX_BARS = 50_000


def fixed_reversal_policy() -> dict[str, object]:
    """Return the complete fixed policy; it has no runtime tuning knobs."""
    return {
        "id": STRATEGY_ID,
        "input": "CONTIGUOUS_CLOSED_1M_EXPLICIT_ORIGIN_EXPANDING_PREFIX",
        "warmup_ms": HISTORY_BARS * MINUTE_MS,
        "decision_cadence_ms": FIVE_MINUTES_MS,
        "channel": "PRIOR_20_COMPLETE_15M_HIGH_LOW_STRICTLY_BEFORE_EXCURSION_OPEN",
        "atr": "MEAN_14_15M_TRUE_RANGES_WITH_PRIOR_CLOSE_STRICTLY_BEFORE_EXCURSION_OPEN",
        "precursor": "PREVIOUS_COMPLETE_5M_CLOSE_STRICTLY_INSIDE_FROZEN_CHANNEL",
        "event": "LOWER_ONLY_STRICT_WICK_LONG_OR_UPPER_ONLY_STRICT_WICK_SHORT",
        "confirmation": "STRICT_RETURN_CLOSE_ON_EXCURSION_OR_EXACTLY_NEXT_5M_BAR",
        "conflict": "BOTH_BOUNDARY_WICKS_OR_SAME_BAR_OPPOSITE_TARGET_TOUCH_ABSTAIN_CONSUME",
        "target": "OPPOSITE_FROZEN_CHANNEL_BOUNDARY",
        "stop": "EXTREME_OF_ALL_EVENT_BARS_PLUS_OR_MINUS_0_25_FROZEN_ATR15",
        "entry_lifetime_ms": FIVE_MINUTES_MS,
        "maximum_holding_ms": 120 * MINUTE_MS,
        "defense": "PINNED_NATIVE_CRASH_AND_POST_SHOCK_COOLDOWN_CANCEL_OR_ABSTAIN",
        "crash_short_exception": False,
        "reset": "LATER_CLOSE_STRICTLY_INSIDE_CURRENT_PREBAR_20X15M_CHANNEL_RESET_ONLY",
        "candidate_status": "RESEARCH_ONLY_NOT_PRODUCTION_REGISTERED",
    }


POLICY_SHA256 = digest(fixed_reversal_policy())


@dataclass(frozen=True, slots=True)
class ReversalDecision:
    symbol: str
    cut_ms: int
    state: str
    reason: str
    defense: str
    event_id: str | None
    candidate: SleeveIntent | None
    transition: str
    excursion_open_ms: int | None
    confirmation_cut_ms: int | None
    frozen_channel_lower: float | None
    frozen_channel_upper: float | None
    frozen_atr15: float | None
    prior_history_sha256: str | None
    reset_channel_lower: float | None
    reset_channel_upper: float | None
    consumed: bool


@dataclass(frozen=True, slots=True)
class FrozenReversalFeatures:
    channel_lower: float
    channel_upper: float
    atr15: float
    event_low: float
    event_high: float


@dataclass(frozen=True, slots=True)
class _Event:
    event_id: str
    excursion_open_ms: int
    side: Side | None
    lower: float
    upper: float
    atr: float
    history_sha: str
    confirmation_cut_ms: int | None = None
    event_low: float = math.inf
    event_high: float = 0.0


def _check_prefix(candles: tuple[Candle, ...], origin_ms: int) -> str:
    if type(candles) is not tuple or not HISTORY_BARS <= len(candles) <= MAX_PREFIX_BARS:
        raise ValueError("bounded immutable 54h-or-longer candle tuple required")
    if type(origin_ms) is not int or origin_ms < 0 or origin_ms % FIVE_MINUTES_MS:
        raise ValueError("UTC five-minute-aligned explicit origin required")
    if type(candles[0]) is not Candle or candles[0].open_time_ms != origin_ms:
        raise ValueError("typed candle at explicit origin required; reordered prefix rejected")
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
            raise ValueError("mixed, forged, unclosed, reordered or discontinuous one-minute prefix")
    return symbol


def _prior_channel_atr(
    rows15: tuple[Candle, ...], close_times: tuple[int, ...], excursion_open_ms: int
) -> tuple[float, float, float] | None:
    stop = bisect_left(close_times, excursion_open_ms)
    if stop < 20:
        return None
    sample = rows15[stop - 15 : stop]
    expected_close = (excursion_open_ms // FIFTEEN_MINUTES_MS) * FIFTEEN_MINUTES_MS - 1
    if sample[-1].close_time_ms != expected_close or any(
        right.open_time_ms - left.open_time_ms != FIFTEEN_MINUTES_MS
        for left, right in zip(sample, sample[1:], strict=False)
    ):
        return None
    channel = rows15[stop - 20 : stop]
    if len(channel) != 20 or any(
        right.open_time_ms - left.open_time_ms != FIFTEEN_MINUTES_MS
        for left, right in zip(channel, channel[1:], strict=False)
    ):
        return None
    # ATR requires 14 true ranges and the immediately preceding close.
    atr_rows = sample
    ranges = [
        max(bar.high - bar.low, abs(bar.high - prev.close), abs(bar.low - prev.close))
        for prev, bar in zip(atr_rows, atr_rows[1:], strict=False)
    ]
    atr = math.fsum(ranges) / 14
    if not math.isfinite(atr) or atr <= 0:
        return None
    return min(row.low for row in channel), max(row.high for row in channel), atr


def frozen_float_text(value: float) -> str:
    """Canonical metadata spelling for a finite frozen numeric feature."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite frozen feature required")
    return format(float(value), ".17g")


def frozen_reversal_features_from_bars(
    prior15_bars: tuple[Candle, ...],
    event_bars: tuple[Candle, ...],
    *,
    excursion_open_ms: int,
) -> FrozenReversalFeatures:
    """Rebind frozen channel/ATR and event extremes from bounded native bars.

    Pass the final 20 completed 15m bars strictly before the excursion plus the
    aggregated excursion and (when applicable) confirmation 5m bar. This keeps
    arrival validation bounded; callers bind the independent 1m history digest
    separately using all origin-to-excursion-minus-one source rows.
    """
    if type(prior15_bars) is not tuple or len(prior15_bars) != 20:
        raise ValueError("exact final 20 prior 15m bars required")
    if type(event_bars) is not tuple or len(event_bars) not in {1, 2}:
        raise ValueError("one or two event 5m bars required")
    if type(excursion_open_ms) is not int or excursion_open_ms < 0 or excursion_open_ms % FIVE_MINUTES_MS:
        raise ValueError("five-minute-aligned excursion open required")
    if type(prior15_bars[0]) is not Candle:
        raise ValueError("typed immutable prior 15m bars required")
    symbol = prior15_bars[0].symbol
    for index, row in enumerate(prior15_bars):
        if type(row) is not Candle:
            raise ValueError("typed immutable prior 15m bars required")
        Candle(**asdict(row))
        if (
            row.symbol != symbol
            or row.timeframe != "15m"
            or row.open_time_ms % FIFTEEN_MINUTES_MS
            or (index and row.open_time_ms - prior15_bars[index - 1].open_time_ms != FIFTEEN_MINUTES_MS)
        ):
            raise ValueError("ordered, contiguous native 15m bars required")
    expected_close = (excursion_open_ms // FIFTEEN_MINUTES_MS) * FIFTEEN_MINUTES_MS - 1
    if prior15_bars[-1].close_time_ms != expected_close:
        raise ValueError("prior 15m rows must end at the latest completed bar before excursion")
    event_low, event_high = math.inf, 0.0
    for index, row in enumerate(event_bars):
        if type(row) is not Candle:
            raise ValueError("typed immutable event 5m bars required")
        Candle(**asdict(row))
        if (
            row.symbol != symbol
            or row.timeframe != "5m"
            or row.open_time_ms != excursion_open_ms + index * FIVE_MINUTES_MS
            or row.close_time_ms != row.open_time_ms + FIVE_MINUTES_MS - 1
        ):
            raise ValueError("event bars must be contiguous from the excursion open")
        event_low = min(event_low, row.low)
        event_high = max(event_high, row.high)
    values = _prior_channel_atr(
        prior15_bars,
        tuple(row.close_time_ms for row in prior15_bars),
        excursion_open_ms,
    )
    if values is None:
        raise ValueError("complete prior 15m channel and ATR context required")
    return FrozenReversalFeatures(*values, event_low, event_high)


def _decision(
    symbol: str,
    cut_ms: int,
    state: str,
    reason: str,
    defense: str,
    event: _Event | None,
    transition: str,
    *,
    candidate: SleeveIntent | None = None,
    confirmation_cut_ms: int | None = None,
    reset_channel: tuple[float, float] | None = None,
    consumed: bool = False,
) -> ReversalDecision:
    return ReversalDecision(
        symbol=symbol,
        cut_ms=cut_ms,
        state=state,
        reason=reason,
        defense=defense,
        event_id=None if event is None else event.event_id,
        candidate=candidate,
        transition=transition,
        excursion_open_ms=None if event is None else event.excursion_open_ms,
        confirmation_cut_ms=confirmation_cut_ms,
        frozen_channel_lower=None if event is None else event.lower,
        frozen_channel_upper=None if event is None else event.upper,
        frozen_atr15=None if event is None else event.atr,
        prior_history_sha256=None if event is None else event.history_sha,
        reset_channel_lower=None if reset_channel is None else reset_channel[0],
        reset_channel_upper=None if reset_channel is None else reset_channel[1],
        consumed=consumed,
    )


def _emit_candidate(
    event: _Event,
    *,
    origin_ms: int,
    bar: Candle,
    cut_ms: int,
) -> tuple[SleeveIntent | None, str]:
    assert event.side is not None
    if event.side is Side.LONG:
        stop = event.event_low - 0.25 * event.atr
        target = event.upper
    else:
        stop = event.event_high + 0.25 * event.atr
        target = event.lower
    reference = bar.close
    if not all(math.isfinite(value) and value > 0 for value in (stop, target, reference)):
        return None, "NON_EXECUTABLE_GEOMETRY"
    if event.side is Side.LONG and not stop < reference < target:
        return None, "NON_EXECUTABLE_GEOMETRY"
    if event.side is Side.SHORT and not target < reference < stop:
        return None, "NON_EXECUTABLE_GEOMETRY"
    metadata = tuple(
        sorted(
            {
                "policy_sha256": POLICY_SHA256,
                "explicit_origin_ms": str(origin_ms),
                "event_id": event.event_id,
                "excursion_open_ms": str(event.excursion_open_ms),
                "confirmation_cut_ms": str(cut_ms),
                "frozen_channel_lower": frozen_float_text(event.lower),
                "frozen_channel_upper": frozen_float_text(event.upper),
                "frozen_atr15": frozen_float_text(event.atr),
                "prior_history_sha256": event.history_sha,
            }.items()
        )
    )
    reward_bps = abs(target - reference) / reference * 10_000
    intent = SleeveIntent(
        sleeve_id=STRATEGY_ID,
        symbol=bar.symbol,
        side=event.side,
        decision_ts_ms=cut_ms - 1,
        entry_eligible_ts_ms=cut_ms,
        entry_expires_ts_ms=cut_ms - 1 + FIVE_MINUTES_MS,
        reference_price=reference,
        signal_strength=1.0,
        gross_reward_bps=reward_bps,
        exit_plan=ExitPlan(stop_price=stop, target_price=target, max_holding_ms=120 * MINUTE_MS),
        metadata=metadata,
    )
    return intent, "STRUCTURAL_CANDIDATE"


def generate_failed_reversal(
    candles: tuple[Candle, ...], *, origin_ms: int, deadline: float | None = None
) -> tuple[ReversalDecision, ...]:
    """Generate every post-warmup complete UTC 5m cut from one immutable prefix."""
    symbol = _check_prefix(candles, origin_ms)
    if deadline is not None and (
        isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline)
    ):
        raise ValueError("finite monotonic deadline or None required")

    def check_deadline() -> None:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("failed reversal generation deadline reached")

    check_deadline()
    five_all = aggregate(list(candles), "5m")
    fifteen_all = aggregate(list(candles), "15m")
    hour_all = aggregate(list(candles), "1h")
    if len(five_all) != len(candles) // 5:
        raise ValueError("complete UTC five-minute aggregation required")
    five, fifteen, hours = tuple(five_all), tuple(fifteen_all), tuple(hour_all)
    five_opens = tuple(row.open_time_ms for row in five)
    five_closes = tuple(row.close_time_ms for row in five)
    candle_opens = tuple(row.open_time_ms for row in candles)
    fifteen_closes = tuple(row.close_time_ms for row in fifteen)
    hour_opens = tuple(row.open_time_ms for row in hours)
    hour_closes = tuple(row.close_time_ms for row in hours)
    warmup_cut = origin_ms + HISTORY_BARS * MINUTE_MS
    decisions: list[ReversalDecision] = []
    state = "IDLE"
    event: _Event | None = None

    for index, bar in enumerate(five):
        cut_ms = bar.close_time_ms + 1
        if cut_ms < warmup_cut:
            continue
        check_deadline()
        # The guard sees only complete native bars in the latest 54h.
        rows5_end = bisect_left(five_closes, cut_ms)
        rows5_start = bisect_left(five_opens, cut_ms - HISTORY_BARS * MINUTE_MS)
        hour_start = bisect_left(hour_opens, cut_ms - HISTORY_BARS * MINUTE_MS)
        hour_end = bisect_left(hour_closes, cut_ms)
        defense = _native_defense_from_bars(
            list(five[rows5_start:rows5_end]), list(hours[hour_start:hour_end]), cut_ms
        )

        if state == "WAIT_RESET":
            prior = _prior_channel_atr(fifteen, fifteen_closes, bar.open_time_ms)
            if prior is not None and prior[0] < bar.close < prior[1]:
                decisions.append(
                    _decision(
                        symbol,
                        cut_ms,
                        "IDLE",
                        "RESET_TO_IDLE",
                        defense,
                        event,
                        "WAIT_RESET_TO_IDLE_RESET_ONLY",
                        confirmation_cut_ms=None if event is None else event.confirmation_cut_ms,
                        reset_channel=(prior[0], prior[1]),
                        consumed=True,
                    )
                )
                state, event = "IDLE", None
            else:
                decisions.append(
                    _decision(
                        symbol,
                        cut_ms,
                        "WAIT_RESET",
                        "WAITING_FOR_FRESH_CHANNEL_RESET",
                        defense,
                        event,
                        "WAIT_RESET_HOLD",
                        confirmation_cut_ms=None if event is None else event.confirmation_cut_ms,
                        reset_channel=None if prior is None else (prior[0], prior[1]),
                        consumed=True,
                    )
                )
            continue

        if defense != "NORMAL":
            if state == "PENDING":
                decisions.append(
                    _decision(
                        symbol,
                        cut_ms,
                        "WAIT_RESET",
                        "NATIVE_DEFENSE_CANCELLED_EVENT",
                        defense,
                        event,
                        "PENDING_CANCELLED_BY_NATIVE_DEFENSE",
                        consumed=True,
                    )
                )
                state = "WAIT_RESET"
            else:
                decisions.append(
                    _decision(
                        symbol,
                        cut_ms,
                        "IDLE",
                        defense,
                        defense,
                        None,
                        "IDLE_DEFENSE_ABSTAIN",
                    )
                )
            continue

        if state == "PENDING":
            assert event is not None and event.side is not None
            if event.side is Side.LONG:
                target_touched = bar.high >= event.upper
                returned = event.lower < bar.close < event.upper
                low, high = min(event.event_low, bar.low), max(event.event_high, bar.high)
            else:
                target_touched = bar.low <= event.lower
                returned = event.lower < bar.close < event.upper
                low, high = min(event.event_low, bar.low), max(event.event_high, bar.high)
            updated = _Event(
                event.event_id,
                event.excursion_open_ms,
                event.side,
                event.lower,
                event.upper,
                event.atr,
                event.history_sha,
                cut_ms if returned else None,
                low,
                high,
            )
            if target_touched:
                decisions.append(
                    _decision(
                        symbol,
                        cut_ms,
                        "WAIT_RESET",
                        "TARGET_ALREADY_TRAVERSED",
                        defense,
                        updated,
                        "PENDING_CONSUMED_TARGET_TRAVERSED",
                        confirmation_cut_ms=cut_ms,
                        consumed=True,
                    )
                )
                state, event = "WAIT_RESET", updated
            elif returned:
                candidate, reason = _emit_candidate(
                    updated,
                    origin_ms=origin_ms,
                    bar=bar,
                    cut_ms=cut_ms,
                )
                decisions.append(
                    _decision(
                        symbol,
                        cut_ms,
                        "WAIT_RESET",
                        reason,
                        defense,
                        updated,
                        "PENDING_CONSUMED_ON_RETURN",
                        candidate=candidate,
                        confirmation_cut_ms=cut_ms,
                        consumed=True,
                    )
                )
                state, event = "WAIT_RESET", updated
            else:
                decisions.append(
                    _decision(
                        symbol,
                        cut_ms,
                        "WAIT_RESET",
                        "EVENT_EXPIRED",
                        defense,
                        updated,
                        "PENDING_EXPIRED_CONSUMED",
                        consumed=True,
                    )
                )
                state, event = "WAIT_RESET", updated
            continue

        prior = _prior_channel_atr(fifteen, fifteen_closes, bar.open_time_ms)
        if prior is None or index == 0:
            decisions.append(
                _decision(symbol, cut_ms, "IDLE", "INSUFFICIENT_PRIOR_CONTEXT", defense, None, "IDLE_HOLD")
            )
            continue
        lower, upper, atr = prior
        previous_close = five[index - 1].close
        if not lower < previous_close < upper:
            decisions.append(
                _decision(
                    symbol,
                    cut_ms,
                    "IDLE",
                    "PREVIOUS_CLOSE_OUTSIDE_CHANNEL",
                    defense,
                    None,
                    "IDLE_HOLD",
                )
            )
            continue
        lower_excursion = bar.low < lower
        upper_excursion = bar.high > upper
        if not lower_excursion and not upper_excursion:
            decisions.append(_decision(symbol, cut_ms, "IDLE", "NO_EXCURSION", defense, None, "IDLE_HOLD"))
            continue

        prior_rows_count = bisect_left(candle_opens, bar.open_time_ms)
        history_sha = digest([candle_payload(row) for row in candles[:prior_rows_count]])
        event_id = digest(
            {
                "policy_sha256": POLICY_SHA256,
                "origin_ms": origin_ms,
                "symbol": symbol,
                "excursion_open_ms": bar.open_time_ms,
                "prior_history_sha256": history_sha,
            }
        )
        side = (
            Side.LONG
            if lower_excursion and not upper_excursion
            else Side.SHORT
            if upper_excursion and not lower_excursion
            else None
        )
        target_hit_same_bar = (side is Side.LONG and bar.high >= upper) or (
            side is Side.SHORT and bar.low <= lower
        )
        if side is None or target_hit_same_bar:
            conflict = _Event(
                event_id,
                bar.open_time_ms,
                None,
                lower,
                upper,
                atr,
                history_sha,
                cut_ms,
                bar.low,
                bar.high,
            )
            decisions.append(
                _decision(
                    symbol,
                    cut_ms,
                    "WAIT_RESET",
                    "CONFLICTING_EXCURSION" if side is None else "SAME_BAR_OPPOSITE_TARGET_CONFLICT",
                    defense,
                    conflict,
                    "EXCURSION_CONFLICT_CONSUMED",
                    confirmation_cut_ms=cut_ms,
                    consumed=True,
                )
            )
            state, event = "WAIT_RESET", conflict
            continue

        event = _Event(
            event_id,
            bar.open_time_ms,
            side,
            lower,
            upper,
            atr,
            history_sha,
            None,
            bar.low,
            bar.high,
        )
        if lower < bar.close < upper:
            candidate, reason = _emit_candidate(
                event,
                origin_ms=origin_ms,
                bar=bar,
                cut_ms=cut_ms,
            )
            event = _Event(
                event.event_id,
                event.excursion_open_ms,
                event.side,
                lower,
                upper,
                atr,
                history_sha,
                cut_ms,
                bar.low,
                bar.high,
            )
            decisions.append(
                _decision(
                    symbol,
                    cut_ms,
                    "WAIT_RESET",
                    reason,
                    defense,
                    event,
                    "EXCURSION_RETURN_CONSUMED",
                    candidate=candidate,
                    confirmation_cut_ms=cut_ms,
                    consumed=True,
                )
            )
            state = "WAIT_RESET"
        else:
            decisions.append(
                _decision(
                    symbol,
                    cut_ms,
                    "PENDING",
                    "AWAITING_ONE_BAR_RETURN",
                    defense,
                    event,
                    "IDLE_TO_PENDING",
                )
            )
            state = "PENDING"
    check_deadline()
    return tuple(decisions)
