from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from adaptive_replay.hypothesis_v3 import EntryQuote
from kairos_native_campaign.current_capture import BAR_COUNT, BAR_MS, FreshQuoteSnapshot
from kairos_native_campaign.current_inputs import (
    CapturedClosedBar,
    CurrentInputRefused,
    CurrentObservationSource,
    QuantMeasurement,
    QuantMeasurements,
    build_market_snapshot,
)
from kairos_strategy.candles import Candle

NOW = 1_800_000_000_000


def _measurement(
    value: float,
    scope: str,
    *,
    event_ms: int = NOW,
    received_ms: int = NOW + 1,
    captured_ms: int = NOW + 2,
    start: int | None = None,
    end: int | None = None,
    complete: bool = True,
) -> QuantMeasurement:
    return QuantMeasurement(
        value,
        "binance_public_rest",
        event_ms,
        received_ms,
        captured_ms,
        "a" * 64,
        scope,
        start,
        end,
        complete,
    )


def _metrics(symbol: str = "BTCUSDT") -> QuantMeasurements:
    return QuantMeasurements(
        symbol,
        _measurement(0.0001, "LATEST_PUBLIC_FUNDING_RATE"),
        _measurement(123_456.0, "LATEST_OPEN_INTEREST_VALUE"),
        _measurement(
            1.5,
            "COMPLETE_13_CONSECUTIVE_5M_OPEN_INTEREST_POINTS",
            start=NOW - 60 * 60_000,
            end=NOW + 2,
        ),
        _measurement(
            100.0,
            "CONTINUOUS_FORCE_ORDER_CAPTURE_WINDOW",
            event_ms=NOW - 60_000,
            start=NOW - 60_000,
            end=NOW + 2,
        ),
        _measurement(
            0.0,
            "CONTINUOUS_FORCE_ORDER_CAPTURE_WINDOW",
            event_ms=NOW - 60_000,
            start=NOW - 60_000,
            end=NOW + 2,
        ),
    )


def _quote(symbol: str = "BTCUSDT") -> FreshQuoteSnapshot:
    body = json.dumps(
        {
            "lastUpdateId": 1,
            "E": NOW,
            "T": NOW,
            "bids": [["100.0", "2.0"], ["99.0", "3.0"]],
            "asks": [["100.1", "4.0"], ["101.0", "5.0"]],
        },
        separators=(",", ":"),
    ).encode()
    return FreshQuoteSnapshot(
        symbol,
        EntryQuote(
            "binance_um_rest_depth_snapshot",
            symbol,
            100.0,
            100.1,
            NOW,
            NOW + 1,
            NOW + 2,
            5_000,
            "CALLER_ATTESTED_POINT_IN_TIME",
        ),
        body,
        hashlib.sha256(body).hexdigest(),
        NOW,
        NOW + 1,
        NOW + 2,
        5.0,
        9.0,
        Path("depth.raw"),
    )


def test_quant_metrics_reject_unproven_liquidation_zero():
    valid = _metrics()
    with pytest.raises(CurrentInputRefused, match="FORCE_ORDER_WINDOW_NOT_PROVEN_COMPLETE"):
        QuantMeasurements(
            valid.symbol,
            valid.funding_rate,
            valid.open_interest,
            valid.oi_change_pct_1h,
            valid.long_liquidations_usd,
            _measurement(
                0.0,
                "CONTINUOUS_FORCE_ORDER_CAPTURE_WINDOW",
                start=NOW - 60_000,
                end=NOW + 2,
                complete=False,
            ),
        )


def test_quant_snapshot_uses_existing_builder_and_actual_metric_bundle():
    symbol = "BTCUSDT"
    bars = tuple(
        Candle(symbol, "1m", opened, opened + BAR_MS - 1, 100.0, 101.0, 99.0, 100.5, 5.0, 500.0, 2.0, 200.0)
        for opened in range(NOW - BAR_COUNT * BAR_MS, NOW, BAR_MS)
    )
    captured = build_market_snapshot(symbol, bars, _quote(symbol), _metrics(symbol))
    assert captured.snapshot.derivatives.funding_rate == pytest.approx(0.0001)
    assert captured.snapshot.derivatives.open_interest == pytest.approx(123_456.0)
    assert captured.snapshot.derivatives.oi_change_pct_1h == pytest.approx(1.5)
    assert captured.snapshot.derivatives.long_liquidations_usd == pytest.approx(100.0)
    assert captured.snapshot.derivatives.short_liquidations_usd == pytest.approx(0.0)
    assert dict(captured.coverage)["BOOK"] == "ONE_SHOT_REST_DEPTH_SNAPSHOT"


def test_captured_post_plan_bar_requires_exact_original_bytes_and_clocks():
    candle = Candle("BTCUSDT", "1m", NOW, NOW + BAR_MS - 1, 100.0, 101.0, 99.0, 100.5, 5.0)
    raw = b'{"source":"actual-receipt"}'
    bar = CapturedClosedBar(
        candle,
        raw,
        "binance_um_ws_closed_kline",
        candle.close_time_ms,
        NOW + BAR_MS,
        NOW + BAR_MS + 1,
        hashlib.sha256(raw).hexdigest(),
    )
    assert bar.raw_payload == raw
    with pytest.raises(CurrentInputRefused, match="CLOSED_BAR_RAW_SOURCE_CLOCK_OR_HASH_INVALID"):
        CapturedClosedBar(
            candle,
            raw,
            "binance_um_ws_closed_kline",
            candle.close_time_ms,
            NOW + BAR_MS,
            NOW + BAR_MS + 1,
            "0" * 64,
        )


@pytest.mark.asyncio
async def test_observation_source_shares_bar_receipt_without_consuming_it():
    candle = Candle("BTCUSDT", "1m", NOW, NOW + BAR_MS - 1, 100.0, 101.0, 99.0, 100.5, 5.0)
    raw = b"immutable-source-receipt"
    bar = CapturedClosedBar(
        candle,
        raw,
        "binance_um_ws_closed_kline",
        candle.close_time_ms,
        NOW + BAR_MS,
        NOW + BAR_MS + 1,
        hashlib.sha256(raw).hexdigest(),
    )

    class Bars:
        calls = 0

        async def wait_closed_bar(self, symbol, after_close_ms, *, timeout_s):
            assert symbol == "BTCUSDT" and after_close_ms == NOW - 1
            assert 0 < timeout_s <= 60
            self.calls += 1
            return bar

    class Quotes:
        async def fresh_quote(self, symbol):
            raise AssertionError("pure cache test must not enter an observation plan")

    source = CurrentObservationSource(Bars(), Quotes(), clock_ms=lambda: NOW)
    first = await source._next_closed_bar("BTCUSDT", NOW - 1, timeout_s=1)
    second = await source._next_closed_bar("BTCUSDT", NOW - 1, timeout_s=1)
    assert first is second is bar
    assert source.bar_source.calls == 1
