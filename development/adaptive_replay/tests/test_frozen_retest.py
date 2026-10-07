import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle

from adaptive_replay.frozen_retest import (
    HISTORY_BARS,
    MINUTE_MS,
    STRATEGY_ID,
    fixed_retest_policy,
    generate_frozen_retest,
    native_defense,
)

ORIGIN = 0
WARMUP_FIVE = HISTORY_BARS // 5


def five_bar(opened=100.0, high=100.4, low=99.6, close=100.0):
    return (opened, high, low, close)


def tape(events=None, *, count=WARMUP_FIVE + 8, symbol="BTCUSDT"):
    """Build exact OHLC 5m bars from valid contiguous 1m candles."""
    events = events or {}
    result = []
    for index in range(count):
        opened, high, low, close = events.get(index, five_bar())
        for minute in range(5):
            o = opened if minute == 0 else close if minute == 4 else opened
            c = close if minute == 4 else o
            h = high if minute == 0 else max(o, c)
            lo = low if minute == 0 else min(o, c)
            timestamp = index * 5 * MINUTE_MS + minute * MINUTE_MS
            result.append(Candle(symbol, "1m", timestamp, timestamp + MINUTE_MS - 1, o, h, lo, c, 1))
    return tuple(result)


def successful_events(side=Side.LONG, *, breakout_index=WARMUP_FIVE):
    events = {breakout_index - 28: five_bar(100, 103, 99.6, 100)}
    if side is Side.LONG:
        events[breakout_index] = five_bar(100, 104, 99.9, 100.8)
        events[breakout_index + 1] = five_bar(100.8, 101.0, 100.1, 100.2)
        events[breakout_index + 2] = five_bar(100.2, 101.1, 100.0, 100.8)
    else:
        events[breakout_index - 28] = five_bar(100, 100.4, 97, 100)
        events[breakout_index] = five_bar(100, 100.1, 96, 99.2)
        events[breakout_index + 1] = five_bar(99.2, 99.9, 99.0, 99.8)
        events[breakout_index + 2] = five_bar(99.8, 100.0, 99.0, 99.2)
    return events


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_mirrored_breakout_first_retest_reclaim_and_identity(side):
    decisions = generate_frozen_retest(tape(successful_events(side)), origin_ms=ORIGIN)
    breakout_index = WARMUP_FIVE
    arm, retest, reclaim = decisions[1:4]
    assert arm.state == "ARMED" and arm.reason == "BREAKOUT_ARMED"
    assert retest.state == "RETESTED" and retest.reason == "FIRST_RETEST_RECORDED"
    assert reclaim.state == "BLOCKED" and reclaim.reason == "CANDIDATE_ACCEPTED"
    assert reclaim.consumed and reclaim.candidate is not None
    candidate = reclaim.candidate
    assert candidate.sleeve_id == STRATEGY_ID and candidate.side is side
    assert candidate.decision_ts_ms == reclaim.cut_ms - 1
    assert candidate.entry_eligible_ts_ms == reclaim.cut_ms
    assert candidate.entry_expires_ts_ms == reclaim.cut_ms + 299_999
    assert candidate.exit_plan.max_holding_ms == 120 * MINUTE_MS
    metadata = dict(candidate.metadata)
    assert (
        set(
            (
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
            )
        )
        <= metadata.keys()
    )
    assert metadata["explicit_origin_ms"] == str(ORIGIN)
    assert metadata["setup_id"] == reclaim.setup_id == arm.setup_id == retest.setup_id
    assert int(metadata["breakout_cut_ms"]) == reclaim.breakout_cut_ms
    assert reclaim.age_bars == 2
    assert reclaim.transition == "RECLAIM_CONSUMED_NO_RETRY"
    assert decisions[4].reason == "RESET_TO_IDLE"
    assert breakout_index == WARMUP_FIVE


def test_arming_uses_prior20_channel_and_strictly_prior_atr():
    events = successful_events()
    events[WARMUP_FIVE] = five_bar(100, 104, 99.9, 100.8)
    result = generate_frozen_retest(tape(events), origin_ms=ORIGIN)
    arm = result[1]
    assert arm.state == "ARMED"
    assert arm.frozen_channel_upper == pytest.approx(100.4)
    assert arm.frozen_channel_lower == pytest.approx(99.6)
    assert arm.frozen_atr5 == pytest.approx(0.8)
    assert arm.frozen_target == pytest.approx(103.0)


@pytest.mark.parametrize("side,expected", [(Side.LONG, 104.0), (Side.SHORT, 96.0)])
def test_prior48_target_cap_requires_strictly_external_extreme(side, expected):
    breakout = WARMUP_FIVE
    events = successful_events(side)
    events.pop(breakout - 28)
    arm = generate_frozen_retest(tape(events), origin_ms=ORIGIN)[1]
    assert arm.state == "ARMED"
    assert arm.frozen_target == pytest.approx(expected)


@pytest.mark.parametrize("retest_age", [1, 5])
def test_first_retest_at_age_one_or_five_and_distinct_reclaim(retest_age):
    breakout = WARMUP_FIVE
    events = successful_events()
    events.pop(breakout + 1)
    events.pop(breakout + 2)
    for age in range(1, retest_age):
        events[breakout + age] = five_bar(100.8, 101.0, 100.5, 100.6)
    events[breakout + retest_age] = five_bar(100.8, 101.0, 100.1, 100.2)
    events[breakout + retest_age + 1] = five_bar(100.2, 101.1, 100.0, 100.8)
    decisions = generate_frozen_retest(tape(events, count=WARMUP_FIVE + retest_age + 4), origin_ms=ORIGIN)
    retest, reclaim = decisions[1 + retest_age : 3 + retest_age]
    assert retest.age_bars == retest_age and retest.reason == "FIRST_RETEST_RECORDED"
    assert reclaim.cut_ms > retest.cut_ms and reclaim.reason == "CANDIDATE_ACCEPTED"


def test_age_six_without_reclaim_expires_and_cannot_reuse_event():
    breakout = WARMUP_FIVE
    events = successful_events()
    events.pop(breakout + 2)
    for age in range(1, 6):
        events[breakout + age] = five_bar(100.8, 101.0, 100.5, 100.6)
    events[breakout + 6] = five_bar(100.2, 100.3, 100.0, 100.2)
    decisions = generate_frozen_retest(tape(events, count=WARMUP_FIVE + 9), origin_ms=ORIGIN)
    expiry = decisions[7]
    assert expiry.age_bars == 6 and expiry.reason == "SETUP_TIMEOUT" and expiry.consumed
    assert decisions[8].reason == "RESET_TO_IDLE"
    assert decisions[8].state == "IDLE"


def test_invalidation_blocks_and_reset_candle_does_not_arm():
    breakout = WARMUP_FIVE
    events = successful_events()
    events[breakout + 1] = five_bar(100.8, 101.0, 99.7, 99.9)
    events[breakout + 2] = five_bar()
    decisions = generate_frozen_retest(tape(events), origin_ms=ORIGIN)
    invalid = decisions[2]
    assert invalid.reason == "ADVERSE_INVALIDATION" and invalid.state == "BLOCKED"
    # The next close is back inside the original channel; it only resets.
    assert decisions[3].reason == "RESET_TO_IDLE" and decisions[3].state == "IDLE"
    assert decisions[4].reason == "NO_CHANNEL_CROSS"


def test_exact_half_atr_invalidation_boundary_is_not_adverse():
    breakout = WARMUP_FIVE
    events = successful_events()
    events[breakout + 1] = five_bar(100.8, 101.0, 99.9, 100.0)
    decisions = generate_frozen_retest(tape(events), origin_ms=ORIGIN)
    assert decisions[2].frozen_atr5 == pytest.approx(0.8)
    assert decisions[2].frozen_level == pytest.approx(100.4)
    assert decisions[2].reason == "FIRST_RETEST_RECORDED"
    assert decisions[2].state == "RETESTED"


def test_cost_or_geometry_failure_consumes_reclaim_without_retry():
    breakout = WARMUP_FIVE
    events = successful_events()
    events[breakout + 1] = five_bar(100.8, 101.0, 98.0, 100.2)
    decisions = generate_frozen_retest(tape(events), origin_ms=ORIGIN)
    reject = decisions[3]
    assert reject.state == "BLOCKED" and reject.consumed
    assert reject.reason in {"STOP_OUTSIDE_ATR_BOUNDS", "INSUFFICIENT_COST_HEADROOM"}
    assert reject.candidate is None and reject.stop_price is not None
    assert decisions[4].reason == "RESET_TO_IDLE"
    assert decisions[5].reason == "NO_CHANNEL_CROSS"


def test_stop_uses_extreme_from_first_retest_through_later_reclaim():
    breakout = WARMUP_FIVE
    events = successful_events()
    events[breakout + 2] = five_bar(100.2, 101.0, 99.95, 100.3)
    events[breakout + 3] = five_bar(100.3, 101.1, 100.0, 100.8)
    decisions = generate_frozen_retest(tape(events), origin_ms=ORIGIN)
    reclaim = decisions[4]
    assert reclaim.age_bars == 3 and reclaim.reason == "CANDIDATE_ACCEPTED"
    assert reclaim.stop_price == pytest.approx(99.75)


def test_prefix_rerun_is_future_invariant_and_setup_hash_binds_only_breakout_prefix():
    events = successful_events()
    short = tape(events, count=WARMUP_FIVE + 5)
    extended = tape(events, count=WARMUP_FIVE + 10)
    a = generate_frozen_retest(short, origin_ms=ORIGIN)
    b = generate_frozen_retest(extended, origin_ms=ORIGIN)
    assert a == b[: len(a)]
    assert a[1].frozen_history_sha256 == b[1].frozen_history_sha256


def test_native_crash_and_postshock_guard_abstain_and_cancel_setup():
    breakout = WARMUP_FIVE
    events = successful_events()
    events[breakout + 1] = five_bar(100.8, 101, 90, 90)
    decisions = generate_frozen_retest(tape(events), origin_ms=ORIGIN)
    assert decisions[2].defense == "CRASH"
    assert decisions[2].reason == "CRASH_GUARD"
    assert decisions[2].state == "BLOCKED" and decisions[2].candidate is None


@pytest.mark.parametrize(
    "bad,origin,match",
    [
        (list(tape()), ORIGIN, "tuple"),
        ((object(),) + tape()[1:], ORIGIN, "typed"),
        (tape()[1:], ORIGIN, "origin"),
        (tape()[:100] + tape()[101:], ORIGIN, "discontinuous"),
        (tuple(reversed(tape())), ORIGIN, "origin"),
        (tape(symbol="DOGEUSDT"), ORIGIN, "universe"),
        (tape(), True, "origin"),
        (tape(), 1, "origin"),
    ],
)
def test_rejects_invalid_or_forged_prefixes(bad, origin, match):
    with pytest.raises(ValueError, match=match):
        generate_frozen_retest(bad, origin_ms=origin)


def test_revalidates_forged_frozen_candle_and_checks_deadline():
    rows = list(tape())
    object.__setattr__(rows[0], "high", 1.0)
    with pytest.raises(ValueError, match="OHLC"):
        generate_frozen_retest(tuple(rows), origin_ms=ORIGIN)
    with pytest.raises(TimeoutError, match="deadline"):
        generate_frozen_retest(tape(), origin_ms=ORIGIN, deadline=0.0)


def test_fixed_policy_is_unparameterized_and_deterministic():
    assert fixed_retest_policy()["id"] == STRATEGY_ID
    assert fixed_retest_policy() == fixed_retest_policy()


def test_public_native_defense_matches_generator_and_accepts_minute_cut():
    rows = tape()
    cut_ms = rows[-1].close_time_ms + 1
    generated = generate_frozen_retest(rows, origin_ms=ORIGIN)
    assert native_defense(rows, origin_ms=ORIGIN, cut_ms=cut_ms) == generated[-1].defense
    minute_cut_rows = rows[:-1]
    minute_cut = minute_cut_rows[-1].close_time_ms + 1
    assert minute_cut % (5 * MINUTE_MS) != 0
    assert native_defense(minute_cut_rows, origin_ms=ORIGIN, cut_ms=minute_cut) == "NORMAL"


def test_public_native_defense_returns_crash_and_postshock_cooldown():
    count = WARMUP_FIVE + 12
    cooldown_rows = tape({count - 13: five_bar(100, 100.4, 90, 90)}, count=count)
    cooldown_cut = cooldown_rows[-1].close_time_ms + 1
    cooldown_generation = generate_frozen_retest(cooldown_rows, origin_ms=ORIGIN)
    assert cooldown_generation[-1].defense == "POST_SHOCK_COOLDOWN"
    assert native_defense(cooldown_rows, origin_ms=ORIGIN, cut_ms=cooldown_cut) == (
        cooldown_generation[-1].defense
    )
    crash_rows = tape({count - 1: five_bar(100, 100.4, 90, 90)}, count=count)
    crash_cut = crash_rows[-1].close_time_ms + 1
    crash_generation = generate_frozen_retest(crash_rows, origin_ms=ORIGIN)
    assert crash_generation[-1].defense == "CRASH"
    assert native_defense(crash_rows, origin_ms=ORIGIN, cut_ms=crash_cut) == crash_generation[-1].defense
    arrival_rows = crash_rows + (
        Candle("BTCUSDT", "1m", crash_cut, crash_cut + MINUTE_MS - 1, 90, 90.1, 89.9, 90, 1),
    )
    assert native_defense(arrival_rows, origin_ms=ORIGIN, cut_ms=crash_cut + MINUTE_MS) == "CRASH"
    cooldown_arrival_rows = cooldown_rows + (
        Candle("BTCUSDT", "1m", cooldown_cut, cooldown_cut + MINUTE_MS - 1, 100, 100.1, 99.9, 100, 1),
    )
    assert (
        native_defense(cooldown_arrival_rows, origin_ms=ORIGIN, cut_ms=cooldown_cut + MINUTE_MS)
        == "POST_SHOCK_COOLDOWN"
    )


def test_public_native_defense_requires_exact_validated_cut():
    rows = tape()
    with pytest.raises(ValueError, match="exact final closed cut"):
        native_defense(rows, origin_ms=ORIGIN, cut_ms=rows[-1].close_time_ms + 1 + MINUTE_MS)
    with pytest.raises(ValueError, match="discontinuous"):
        native_defense(rows[:100] + rows[101:], origin_ms=ORIGIN, cut_ms=rows[-1].close_time_ms + 1)
