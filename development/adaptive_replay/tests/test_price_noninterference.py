from __future__ import annotations

import math
from dataclasses import asdict, replace

from kairos_backtest.data import ArchiveFieldProfile, _row_domain_issue
from kairos_backtest.factor_data import FundingObservation
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import SleeveIntent
from kairos_strategy.sleeves.regime_aligned_right_tail import generate_regime_aligned_right_tail_intents
from kairos_strategy.sleeves.right_tail_trend import generate_right_tail_trend_intents

from adaptive_replay.engine import COMMON_COST_RISK, CostScenario, replay_tape
from adaptive_replay.inputs import WindowInputs
from adaptive_replay.right_tail import check_pair, check_regime_selection

MINUTE = 60_000
HOUR = 60 * MINUTE
DAY = 24 * HOUR
SCORING_START = 35 * DAY
SCORING_END = 40 * DAY
REPLAY_END = SCORING_START + DAY + 72 * HOUR
OPTIONAL_FIELDS = ("volume", "quote_volume", "taker_buy_volume", "taker_buy_quote_volume")


def _hour_step(hour: int) -> float:
    if hour < 30 * 24:
        return 0.0
    if hour < 35 * 24:
        return 0.004
    if hour < 39 * 24:
        return -0.012
    return 0.015


def _btc_prices(volume: float, taker_volume: float) -> tuple[Candle, ...]:
    rows: list[Candle] = []
    previous = 100.0
    for hour in range(43 * 24):
        step = _hour_step(hour)
        minute_factor = math.exp(step / 60)
        target = previous * math.exp(step)
        for minute in range(60):
            opened = previous
            closed = target if minute == 59 else opened * minute_factor
            mid = (opened + closed) / 2
            rows.append(
                Candle(
                    "BTCUSDT",
                    "1m",
                    hour * HOUR + minute * MINUTE,
                    hour * HOUR + (minute + 1) * MINUTE - 1,
                    opened,
                    max(opened, closed) * 1.002,
                    min(opened, closed) * 0.998,
                    closed,
                    volume,
                    volume * mid,
                    taker_volume,
                    taker_volume * mid,
                )
            )
            previous = closed
    return tuple(rows)


def _flat_other_symbol(symbol: str, volume: float, taker_volume: float) -> tuple[Candle, ...]:
    return tuple(
        Candle(
            symbol,
            "1m",
            ts,
            ts + MINUTE - 1,
            100,
            100.2,
            99.8,
            100,
            volume,
            volume * 100,
            taker_volume,
            taker_volume * 100,
        )
        for ts in range(SCORING_START, REPLAY_END, MINUTE)
    )


def _zero_optional(rows: tuple[Candle, ...]) -> tuple[Candle, ...]:
    return tuple(
        replace(row, volume=0, quote_volume=0, taker_buy_volume=0, taker_buy_quote_volume=0) for row in rows
    )


def _intent_tape(intents: list[SleeveIntent]) -> dict[int, list[SleeveIntent]]:
    scoring = [intent for intent in intents if SCORING_START <= intent.entry_eligible_ts_ms < SCORING_END]
    return {intent.entry_eligible_ts_ms: [intent] for intent in scoring[:1]}


def test_default_right_tail_arms_are_noninterfering_with_optional_fields() -> None:
    first = _btc_prices(10.0, 4.0)
    second = _btc_prices(20.0, 16.0)
    first_zero = _zero_optional(first)
    second_zero = _zero_optional(second)

    assert len(first) >= 35 * 24 * 60
    assert first[0].open_time_ms == 0 and first[-1].close_time_ms + 1 == 43 * DAY
    for rows in (first, second):
        for row in rows:
            assert (
                _row_domain_issue(
                    (
                        row.open,
                        row.high,
                        row.low,
                        row.close,
                        row.volume,
                        row.quote_volume,
                        row.taker_buy_volume,
                        row.taker_buy_quote_volume,
                        0,
                    ),
                    0,
                    ArchiveFieldProfile.FULL_KLINE,
                )
                is None
            )
    assert {row.volume for row in first} == {10.0}
    assert {row.volume for row in second} == {20.0}
    assert all(
        tuple(getattr(row, name) for name in OPTIONAL_FIELDS) == (0, 0, 0, 0)
        for rows in (first_zero, second_zero)
        for row in rows
    )

    generations = []
    for rows in (first, second, first_zero, second_zero):
        base = generate_right_tail_trend_intents(list(rows))
        aligned = generate_regime_aligned_right_tail_intents(list(rows))
        check_pair(base, aligned)
        check_regime_selection(base, aligned, list(rows))
        base_scoring = [i for i in base if SCORING_START <= i.entry_eligible_ts_ms < SCORING_END]
        aligned_scoring = [i for i in aligned if SCORING_START <= i.entry_eligible_ts_ms < SCORING_END]
        assert base_scoring and aligned_scoring
        assert {i.side for i in base_scoring} == {Side.LONG, Side.SHORT}
        assert len(aligned_scoring) < len(base_scoring)
        generations.append((base, aligned))

    reference = generations[0]
    for pair in generations[1:]:
        assert [asdict(intent) for intent in pair[0]] == [asdict(intent) for intent in reference[0]]
        assert [asdict(intent) for intent in pair[1]] == [asdict(intent) for intent in reference[1]]
        assert [intent.intent_id for intent in pair[0]] == [intent.intent_id for intent in reference[0]]
        assert [intent.intent_id for intent in pair[1]] == [intent.intent_id for intent in reference[1]]


def test_common_cost_risk_replay_is_noninterfering_and_exercises_funding_and_exit() -> None:
    full_first = _btc_prices(10.0, 4.0)
    full_second = _btc_prices(20.0, 16.0)
    full_zero = _zero_optional(full_first)
    first_intents = generate_right_tail_trend_intents(list(full_first))
    second_intents = generate_right_tail_trend_intents(list(full_second))
    assert [asdict(intent) for intent in first_intents] == [asdict(intent) for intent in second_intents]
    tape = _intent_tape(first_intents)
    assert tape and len(next(iter(tape.values()))) == 1

    scenario = CostScenario("synthetic_common_cost", 4.5, 2, 1, 2, 2, 3)
    outputs = []
    for btc_rows in (full_first, full_second, full_zero):
        volume_profile = (20.0, 16.0) if btc_rows is full_second else (10.0, 4.0)
        if btc_rows is full_zero:
            volume_profile = (0.0, 0.0)
        bars = {
            "BTCUSDT": tuple(row for row in btc_rows if SCORING_START <= row.open_time_ms < REPLAY_END),
            **{
                symbol: _flat_other_symbol(symbol, *volume_profile)
                for symbol in ("ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
            },
        }
        inputs = WindowInputs(
            bars=bars,
            funding={
                symbol: (
                    (
                        FundingObservation(
                            symbol="BTCUSDT",
                            timestamp_ms=SCORING_START + 2 * HOUR,
                            interval_hours=8,
                            rate=0.001,
                        ),
                    )
                    if symbol == "BTCUSDT"
                    else ()
                )
                for symbol in bars
            },
            evidence={"fixture": "synthetic_price_only_noninterference"},
            start_ms=SCORING_START,
            end_ms=SCORING_START + DAY,
            data_start_ms=SCORING_START,
            data_end_ms=REPLAY_END,
        )
        report, account = replay_tape(
            inputs,
            tape,
            scenario,
            "STRICT_MINUTE_OPEN",
            100,
            72,
            admission_policy=COMMON_COST_RISK,
        )
        outputs.append((report, account.events, account.trades))

    assert outputs[0] == outputs[1] == outputs[2]
    report, events, trades = outputs[0]
    assert report["closed_trades"] == 1
    assert [event["kind"] for event in events].count("ENTRY") == 1
    assert [event["kind"] for event in events].count("FUNDING") == 1
    assert len(trades) == 1 and trades[0]["reason"] in {"SL", "TP"}
    assert trades[0]["signed_funding_cost_usd"] > 0
