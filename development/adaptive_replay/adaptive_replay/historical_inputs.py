"""Strict caller-owned validation for complete bounded replay input windows."""

from __future__ import annotations

import math
import time

from kairos_backtest.factor_data import FundingObservation
from kairos_strategy.candles import Candle

from .inputs import FUNDING_INTERVAL_MS, UNIVERSE, WindowInputs

MINUTE_MS = 60_000
EXIT_TAIL_MS = 3 * 60 * 60 * 1_000
MAX_BARS_PER_SYMBOL = 50_000
_CHECK_EVERY = 256


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("historical replay input validation deadline reached")


def _clock(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be an exact non-negative integer millisecond clock")
    if value % MINUTE_MS:
        raise ValueError(f"{name} must align to a UTC minute boundary")
    return value


def _revalidate_candle(row: Candle) -> None:
    if not isinstance(row, Candle):
        raise ValueError("bar input contains a non-Candle row")
    Candle(
        symbol=row.symbol,
        timeframe=row.timeframe,
        open_time_ms=row.open_time_ms,
        close_time_ms=row.close_time_ms,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=row.volume,
        quote_volume=row.quote_volume,
        taker_buy_volume=row.taker_buy_volume,
        taker_buy_quote_volume=row.taker_buy_quote_volume,
    )


def validate_replay_inputs(inputs: WindowInputs, *, fixture_only: bool, deadline: float) -> None:
    """Validate the entire bar horizon and funding clocks without mutating inputs.

    ``fixture_only`` permits an explicitly empty funding tuple for each symbol;
    it does not relax validation of any supplied observation. Non-fixture input
    must contain one native 8-hour funding observation per expected bucket.
    """
    if not isinstance(inputs, WindowInputs):
        raise ValueError("WindowInputs instance required")
    if type(fixture_only) is not bool:
        raise ValueError("explicit fixture/non-fixture validation mode required")
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
        raise ValueError("finite monotonic validation deadline required")
    _check_deadline(float(deadline))

    start_ms = _clock(inputs.start_ms, "start_ms")
    end_ms = _clock(inputs.end_ms, "end_ms")
    data_start_ms = _clock(inputs.data_start_ms, "data_start_ms")
    data_end_ms = _clock(inputs.data_end_ms, "data_end_ms")
    if not data_start_ms < start_ms < end_ms:
        raise ValueError("data horizon must begin before a non-empty replay episode")
    if data_end_ms < end_ms + EXIT_TAIL_MS:
        raise ValueError("bar/funding horizon must include the complete three-hour exit tail")
    expected_count = (data_end_ms - data_start_ms) // MINUTE_MS
    if expected_count <= 0 or (data_end_ms - data_start_ms) % MINUTE_MS:
        raise ValueError("data horizon must be a positive whole-minute interval")
    if expected_count > MAX_BARS_PER_SYMBOL:
        raise ValueError("bar horizon exceeds the per-symbol 50,000-row bound")

    if not isinstance(inputs.bars, dict) or set(inputs.bars) != set(UNIVERSE):
        raise ValueError("exact fixed five-symbol bar universe required")
    if not isinstance(inputs.funding, dict) or set(inputs.funding) != set(UNIVERSE):
        raise ValueError("exact fixed five-symbol funding universe required")

    for symbol in UNIVERSE:
        _check_deadline(float(deadline))
        rows = inputs.bars[symbol]
        if not isinstance(rows, tuple) or len(rows) != expected_count or len(rows) > MAX_BARS_PER_SYMBOL:
            raise ValueError(f"{symbol} bars must be an exact bounded tuple covering the complete horizon")
        previous_open: int | None = None
        for index, row in enumerate(rows):
            if index % _CHECK_EVERY == 0:
                _check_deadline(float(deadline))
            _revalidate_candle(row)
            if row.symbol != symbol or row.timeframe != "1m":
                raise ValueError(f"{symbol} bar has a mismatched symbol or timeframe")
            if row.open_time_ms % MINUTE_MS or row.close_time_ms != row.open_time_ms + MINUTE_MS - 1:
                raise ValueError(f"{symbol} bar does not have exact minute-open/close clocks")
            if previous_open is not None and row.open_time_ms != previous_open + MINUTE_MS:
                raise ValueError(f"{symbol} bars contain a gap, duplicate or unordered timestamp")
            previous_open = row.open_time_ms
        if rows[0].open_time_ms != data_start_ms or rows[-1].close_time_ms != data_end_ms - 1:
            raise ValueError(f"{symbol} bars do not match the exact full-horizon anchors")

        observations = inputs.funding[symbol]
        if not isinstance(observations, tuple):
            raise ValueError(f"{symbol} funding observations must be an immutable tuple")
        first_bucket = (
            (data_start_ms + FUNDING_INTERVAL_MS - 1) // FUNDING_INTERVAL_MS
        ) * FUNDING_INTERVAL_MS
        expected_buckets = set(range(first_bucket, data_end_ms, FUNDING_INTERVAL_MS))
        if not fixture_only and expected_buckets and not observations:
            raise ValueError(f"{symbol} native funding observations cannot be empty")
        previous_timestamp: int | None = None
        seen_buckets: set[int] = set()
        for index, observation in enumerate(observations):
            if index % _CHECK_EVERY == 0:
                _check_deadline(float(deadline))
            if not isinstance(observation, FundingObservation):
                raise ValueError(f"{symbol} funding row has an invalid type")
            if observation.symbol != symbol:
                raise ValueError(f"{symbol} funding row has a mismatched symbol")
            timestamp = observation.timestamp_ms
            if type(timestamp) is not int or timestamp < data_start_ms or timestamp >= data_end_ms:
                raise ValueError(f"{symbol} funding timestamp is not an exact in-horizon integer clock")
            if type(observation.interval_hours) is not int or observation.interval_hours != 8:
                raise ValueError(f"{symbol} funding interval must be exactly eight hours")
            if isinstance(observation.rate, bool) or not isinstance(observation.rate, (int, float)):
                raise ValueError(f"{symbol} funding rate must be a finite signed number")
            if not math.isfinite(observation.rate):
                raise ValueError(f"{symbol} funding rate must be finite")
            if previous_timestamp is not None and timestamp <= previous_timestamp:
                raise ValueError(f"{symbol} funding rows must be unique and strictly ordered")
            previous_timestamp = timestamp

            bucket = timestamp - timestamp % FUNDING_INTERVAL_MS
            if bucket < data_start_ms or bucket >= data_end_ms or timestamp - bucket >= MINUTE_MS:
                raise ValueError(f"{symbol} funding timestamp is outside its native bucket tolerance")
            if bucket in seen_buckets:
                raise ValueError(f"{symbol} has duplicate funding settlement buckets")
            seen_buckets.add(bucket)

        if not fixture_only:
            if seen_buckets != expected_buckets:
                raise ValueError(f"{symbol} funding does not cover every native eight-hour bucket")
    _check_deadline(float(deadline))
