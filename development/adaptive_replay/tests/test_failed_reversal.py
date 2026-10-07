from dataclasses import replace

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.timeframes import aggregate

from adaptive_replay.failed_reversal import (
    FIVE_MINUTES_MS,
    HISTORY_BARS,
    MINUTE_MS,
    POLICY_SHA256,
    STRATEGY_ID,
    fixed_reversal_policy,
    frozen_float_text,
    frozen_reversal_features_from_bars,
    generate_failed_reversal,
)

ORIGIN = 0
WARMUP_FIVE = HISTORY_BARS // 5


def _bar(opened=100.0, high=100.4, low=99.6, close=100.0):
    return opened, high, low, close


def _tape(events=None, *, count=WARMUP_FIVE + 8):
    events = events or {}
    rows = []
    for index in range(count):
        opened, high, low, close = events.get(index, _bar())
        for minute in range(5):
            o = opened if minute == 0 else close if minute == 4 else opened
            c = close if minute == 4 else o
            h = high if minute == 0 else max(o, c)
            lo = low if minute == 0 else min(o, c)
            ts = index * FIVE_MINUTES_MS + minute * MINUTE_MS
            rows.append(Candle("BTCUSDT", "1m", ts, ts + MINUTE_MS - 1, o, h, lo, c, 1))
    return tuple(rows)


def _single_return(side=Side.LONG, *, event_index=WARMUP_FIVE):
    events = {}
    if side is Side.LONG:
        events[event_index] = _bar(100.0, 100.3, 99.5, 100.1)
    else:
        events[event_index] = _bar(100.0, 100.5, 99.7, 99.9)
    return events


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
@pytest.mark.parametrize("event_index", [WARMUP_FIVE - 1, WARMUP_FIVE, WARMUP_FIVE + 1, WARMUP_FIVE + 2])
def test_mirrored_raw_candidate_and_every_cut_after_warmup(side, event_index):
    result = generate_failed_reversal(_tape(_single_return(side, event_index=event_index)), origin_ms=ORIGIN)
    assert len(result) == 9
    decision = result[event_index - WARMUP_FIVE + 1]
    candidate = decision.candidate
    assert decision.reason == "STRUCTURAL_CANDIDATE"
    assert decision.state == "WAIT_RESET" and decision.consumed
    assert candidate is not None and candidate.sleeve_id == STRATEGY_ID and candidate.side is side
    assert candidate.decision_ts_ms == decision.cut_ms - 1
    assert candidate.entry_eligible_ts_ms == decision.cut_ms
    assert candidate.entry_expires_ts_ms == decision.cut_ms + FIVE_MINUTES_MS - 1
    assert candidate.exit_plan.max_holding_ms == 120 * MINUTE_MS
    assert candidate.exit_plan.target_price == pytest.approx(100.4 if side is Side.LONG else 99.6)
    metadata = dict(candidate.metadata)
    assert set(metadata) == {
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
    assert metadata["policy_sha256"] == POLICY_SHA256
    assert metadata["event_id"] == decision.event_id
    assert int(metadata["excursion_open_ms"]) == event_index * FIVE_MINUTES_MS
    assert int(metadata["confirmation_cut_ms"]) == decision.cut_ms
    assert decision.frozen_channel_lower == pytest.approx(99.6)
    assert decision.frozen_channel_upper == pytest.approx(100.4)
    assert decision.prior_history_sha256 is not None
    assert result[event_index - WARMUP_FIVE + 2].state == "IDLE"
    candles = _tape(_single_return(side, event_index=event_index))
    prior15 = tuple(aggregate(list(candles[: event_index * 5]), "15m")[-20:])
    event5 = tuple(aggregate(list(candles[event_index * 5 : event_index * 5 + 5]), "5m"))
    features = frozen_reversal_features_from_bars(
        prior15, event5, excursion_open_ms=event_index * FIVE_MINUTES_MS
    )
    assert features.channel_lower == decision.frozen_channel_lower
    assert features.channel_upper == decision.frozen_channel_upper
    assert features.atr15 == decision.frozen_atr15
    assert features.event_low == pytest.approx(event5[0].low)
    assert features.event_high == pytest.approx(event5[0].high)
    assert frozen_float_text(features.atr15) == metadata["frozen_atr15"]


@pytest.mark.parametrize(
    "event,reason",
    [
        (_bar(100, 100.5, 99.5, 100.0), "CONFLICTING_EXCURSION"),
        (_bar(100, 100.4, 99.5, 100.1), "SAME_BAR_OPPOSITE_TARGET_CONFLICT"),
    ],
)
def test_both_edges_or_same_bar_target_touch_consumes_without_candidate(event, reason):
    result = generate_failed_reversal(_tape({WARMUP_FIVE: event}), origin_ms=ORIGIN)
    assert result[1].reason == reason
    assert result[1].candidate is None and result[1].consumed
    assert result[1].state == "WAIT_RESET"


def test_pending_event_confirms_only_on_next_bar_and_freezes_event_geometry():
    events = _single_return()
    events[WARMUP_FIVE] = _bar(100, 100.3, 99.5, 99.4)
    events[WARMUP_FIVE + 1] = _bar(99.4, 100.2, 99.3, 100.1)
    result = generate_failed_reversal(_tape(events), origin_ms=ORIGIN)
    pending, confirmation = result[1:3]
    assert pending.state == "PENDING" and pending.reason == "AWAITING_ONE_BAR_RETURN"
    assert confirmation.state == "WAIT_RESET" and confirmation.reason == "STRUCTURAL_CANDIDATE"
    assert confirmation.candidate is not None
    assert confirmation.frozen_atr15 is not None
    assert confirmation.candidate.exit_plan.stop_price == pytest.approx(
        99.3 - 0.25 * confirmation.frozen_atr15
    )


def test_second_outside_bar_expires_and_reset_uses_fresh_channel_not_old_boundary():
    events = _single_return()
    events[WARMUP_FIVE] = _bar(100, 100.3, 99.5, 99.4)
    events[WARMUP_FIVE + 1] = _bar(99.4, 100.2, 99.3, 99.5)
    # Lift the later tape into a new range. Once the 20x15m channel has rolled,
    # this close is inside the new channel but outside the event's old channel.
    for index in range(WARMUP_FIVE + 2, WARMUP_FIVE + 2 + 200):
        events[index] = _bar(102, 102.4, 101.6, 102)
    result = generate_failed_reversal(_tape(events, count=WARMUP_FIVE + 210), origin_ms=ORIGIN)
    assert result[2].reason == "EVENT_EXPIRED" and result[2].consumed
    reset = next(item for item in result[3:] if item.reason == "RESET_TO_IDLE")
    assert reset.cut_ms > result[2].cut_ms
    assert reset.reset_channel_upper is not None and reset.reset_channel_upper > 100.4
    assert reset.reset_channel_lower < 102 < reset.reset_channel_upper
    assert reset.candidate is None


def test_next_bar_target_traversal_consumes_without_candidate():
    events = _single_return()
    events[WARMUP_FIVE] = _bar(100, 100.3, 99.5, 99.4)
    events[WARMUP_FIVE + 1] = _bar(99.4, 100.4, 99.3, 100.1)
    result = generate_failed_reversal(_tape(events), origin_ms=ORIGIN)
    assert result[2].reason == "TARGET_ALREADY_TRAVERSED"
    assert result[2].candidate is None and result[2].consumed


def test_prefix_causality_and_deterministic_identity():
    prefix = _tape(_single_return(), count=WARMUP_FIVE + 3)
    short = generate_failed_reversal(prefix, origin_ms=ORIGIN)
    long = generate_failed_reversal(_tape(_single_return(), count=WARMUP_FIVE + 8), origin_ms=ORIGIN)
    assert short == long[: len(short)]
    assert short[1].candidate is not None
    assert short[1].candidate.intent_id == long[1].candidate.intent_id
    assert POLICY_SHA256 == __import__("adaptive_replay.historical_context", fromlist=["digest"]).digest(
        fixed_reversal_policy()
    )


def test_first_exact_warmup_cut_can_emit_from_3235_bar_pre_excursion_hash_prefix():
    event_index = WARMUP_FIVE - 1
    prefix = _tape(_single_return(event_index=event_index), count=WARMUP_FIVE + 1)
    result = generate_failed_reversal(prefix, origin_ms=ORIGIN)
    decision = result[0]
    assert decision.cut_ms == HISTORY_BARS * MINUTE_MS
    assert decision.excursion_open_ms == HISTORY_BARS * MINUTE_MS - FIVE_MINUTES_MS
    assert decision.prior_history_sha256 is not None
    assert decision.candidate is not None


@pytest.mark.parametrize("mutation", ["gap", "reorder", "symbol", "timeframe", "forged"])
def test_invalid_prefix_is_rejected(mutation):
    rows = list(_tape())
    if mutation == "gap":
        rows[100] = replace(
            rows[100],
            open_time_ms=rows[100].open_time_ms + MINUTE_MS,
            close_time_ms=rows[100].close_time_ms + MINUTE_MS,
        )
    elif mutation == "reorder":
        rows[100], rows[101] = rows[101], rows[100]
    elif mutation == "symbol":
        rows[100] = replace(rows[100], symbol="ETHUSDT")
    elif mutation == "timeframe":
        rows[100] = replace(rows[100], timeframe="5m")
    else:
        object.__setattr__(rows[100], "high", rows[100].low - 1)
    with pytest.raises(ValueError):
        generate_failed_reversal(tuple(rows), origin_ms=ORIGIN)


def test_deadline_and_exact_tuple_type_validation():
    rows = _tape()
    with pytest.raises(ValueError, match="finite monotonic"):
        generate_failed_reversal(rows, origin_ms=ORIGIN, deadline=float("nan"))
    with pytest.raises(TimeoutError, match="deadline"):
        generate_failed_reversal(rows, origin_ms=ORIGIN, deadline=0)
    with pytest.raises(ValueError):
        generate_failed_reversal(list(rows), origin_ms=ORIGIN)  # type: ignore[arg-type]


def test_native_crash_cancels_pending_event_and_idle_cooldown_abstains():
    events = _single_return()
    events[WARMUP_FIVE] = _bar(100, 100.3, 99.5, 99.4)
    events[WARMUP_FIVE + 1] = _bar(100, 100, 89, 90)
    result = generate_failed_reversal(_tape(events, count=WARMUP_FIVE + 20), origin_ms=ORIGIN)
    assert result[1].state == "PENDING"
    assert result[2].defense == "CRASH"
    assert result[2].reason == "NATIVE_DEFENSE_CANCELLED_EVENT"
    assert result[2].state == "WAIT_RESET" and result[2].consumed

    cooldown_events = {WARMUP_FIVE + 11: _bar(100, 100, 89, 90)}
    cooldown = generate_failed_reversal(_tape(cooldown_events, count=WARMUP_FIVE + 24), origin_ms=ORIGIN)
    assert any(item.defense == "POST_SHOCK_COOLDOWN" for item in cooldown)
