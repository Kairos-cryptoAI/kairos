from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from kairos_strategy.candles import Candle

from adaptive_replay import historical_bars

START = 1_700_000_040_000


@pytest.mark.parametrize("provenance", ["TEST_FIXTURE", "HISTORICAL_ARCHIVE"])
def test_capture_must_follow_realized_bars_even_for_archives(provenance):
    rows = _candles(1)
    with pytest.raises(ValueError, match="captured before"):
        historical_bars.resolve_closed_history(
            candles=rows,
            expected_payload_sha256=_digest(rows),
            expected_symbol="BTCUSDT",
            expected_timeframe="1m",
            expected_count=1,
            expected_first_open_ms=START,
            expected_last_closed_ms=rows[0].close_time_ms,
            cutoff_ms=rows[0].close_time_ms,
            provenance=provenance,
            captured_at_ms=0,
            source_artifact_sha256="a" * 64,
        )


def _candles(count: int = 4) -> tuple[Candle, ...]:
    return tuple(
        Candle(
            "BTCUSDT",
            "1m",
            START + i * 60_000,
            START + i * 60_000 + 59_999,
            100.0,
            101.0,
            99.0,
            100.5,
            3.0,
            300.0,
            1.0,
            100.0,
        )
        for i in range(count)
    )


def _digest(rows: tuple[Candle, ...]) -> str:
    return hashlib.sha256(historical_bars._payload_bytes(rows)).hexdigest()


def _resolve(
    rows: tuple[Candle, ...], *, cutoff: int | None = None, provenance: str = "HISTORICAL_ARCHIVE"
) -> historical_bars.ClosedHistoryPayload:
    anchor = (
        rows[-1].close_time_ms
        if cutoff is None
        else max(row.close_time_ms for row in rows if row.close_time_ms <= cutoff)
    )
    return historical_bars.resolve_closed_history(
        candles=rows,
        expected_payload_sha256=_digest(rows),
        expected_symbol="BTCUSDT",
        expected_timeframe="1m",
        expected_count=len(rows),
        expected_first_open_ms=rows[0].open_time_ms,
        expected_last_closed_ms=anchor,
        cutoff_ms=(
            rows[-1].close_time_ms + 500 if provenance == "CONTEMPORANEOUS_LOCAL" else rows[-1].close_time_ms
        )
        if cutoff is None
        else cutoff,
        provenance=provenance,  # type: ignore[arg-type]
        captured_at_ms=(
            rows[-1].close_time_ms if provenance == "CONTEMPORANEOUS_LOCAL" else 1_800_000_000_000
        ),
        source_artifact_sha256="a" * 64,
    )


def test_returns_only_closed_prefix_and_records_source_capture_separately() -> None:
    rows = _candles()
    cutoff = rows[1].close_time_ms
    result = _resolve(rows, cutoff=cutoff)

    assert result.candles == rows[:2]
    assert result.last_closed_ms == cutoff
    assert result.payload_sha256 == _digest(rows[:2])
    assert result.source_artifact_sha256 == "a" * 64
    assert result.captured_at_ms == 1_800_000_000_000
    assert result.provenance == "HISTORICAL_ARCHIVE"
    assert result.prompt_payload() == tuple(
        {
            "symbol": candle.symbol,
            "timeframe": candle.timeframe,
            "open_time_ms": candle.open_time_ms,
            "close_time_ms": candle.close_time_ms,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
        }
        for candle in rows[:2]
    )
    result.validate()


def test_all_supported_provenance_labels_are_explicit() -> None:
    rows = _candles(1)
    for provenance in ("HISTORICAL_ARCHIVE", "CONTEMPORANEOUS_LOCAL", "TEST_FIXTURE"):
        assert _resolve(rows, provenance=provenance).provenance == provenance


def test_contemporaneous_local_capture_must_be_between_closed_bar_and_cutoff() -> None:
    rows = _candles(1)
    common = {
        "candles": rows,
        "expected_payload_sha256": _digest(rows),
        "expected_symbol": "BTCUSDT",
        "expected_timeframe": "1m",
        "expected_count": 1,
        "expected_first_open_ms": rows[0].open_time_ms,
        "expected_last_closed_ms": rows[0].close_time_ms,
        "cutoff_ms": rows[0].close_time_ms + 500,
        "provenance": "CONTEMPORANEOUS_LOCAL",
        "source_artifact_sha256": "a" * 64,
    }
    with pytest.raises(ValueError, match="capture clock|captured before"):
        historical_bars.resolve_closed_history(**common, captured_at_ms=rows[0].close_time_ms - 1)
    result = historical_bars.resolve_closed_history(**common, captured_at_ms=rows[0].close_time_ms + 250)
    assert result.captured_at_ms == rows[0].close_time_ms + 250


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_count": 3},
        {"expected_count": 4.0},
        {"expected_first_open_ms": START + 60_000},
        {"expected_last_closed_ms": START + 60_000},
        {"expected_payload_sha256": "0" * 64},
    ],
)
def test_expected_identity_and_anchor_mismatches_fail_closed(changes: dict[str, object]) -> None:
    rows = _candles()
    args: dict[str, object] = {
        "candles": rows,
        "expected_payload_sha256": _digest(rows),
        "expected_symbol": "BTCUSDT",
        "expected_timeframe": "1m",
        "expected_count": len(rows),
        "expected_first_open_ms": rows[0].open_time_ms,
        "expected_last_closed_ms": rows[-1].close_time_ms,
        "cutoff_ms": rows[-1].close_time_ms,
        "provenance": "HISTORICAL_ARCHIVE",
        "captured_at_ms": 1_800_000_000_000,
    }
    args.update(changes)
    with pytest.raises(ValueError):
        historical_bars.resolve_closed_history(**args)  # type: ignore[arg-type]


def test_gap_duplicate_or_wrong_market_is_rejected_even_if_payload_hash_matches() -> None:
    base = _candles()
    bad_gap = (
        base[0],
        replace(
            base[1], open_time_ms=base[1].open_time_ms + 60_000, close_time_ms=base[1].close_time_ms + 60_000
        ),
        *base[2:],
    )
    with pytest.raises(ValueError, match="contiguous"):
        _resolve(bad_gap)

    duplicate = (base[0], base[0], *base[2:])
    with pytest.raises(ValueError, match="contiguous"):
        _resolve(duplicate)

    foreign = (replace(base[0], symbol="ETHUSDT"), *base[1:])
    with pytest.raises(ValueError, match="symbol/timeframe"):
        _resolve(foreign)


def test_unclosed_cutoff_or_missing_anchor_fails_closed() -> None:
    rows = _candles()
    with pytest.raises(ValueError, match="latest bar"):
        historical_bars.resolve_closed_history(
            candles=rows,
            expected_payload_sha256=_digest(rows),
            expected_symbol="BTCUSDT",
            expected_timeframe="1m",
            expected_count=len(rows),
            expected_first_open_ms=rows[0].open_time_ms,
            expected_last_closed_ms=rows[-1].close_time_ms,
            cutoff_ms=rows[-1].open_time_ms,
            provenance="HISTORICAL_ARCHIVE",
            captured_at_ms=1_800_000_000_000,
        )


def test_non_fixture_source_artifact_hash_is_mandatory() -> None:
    rows = _candles(1)
    with pytest.raises(ValueError, match="pinned source artifact"):
        historical_bars.resolve_closed_history(
            candles=rows,
            expected_payload_sha256=_digest(rows),
            expected_symbol="BTCUSDT",
            expected_timeframe="1m",
            expected_count=1,
            expected_first_open_ms=rows[0].open_time_ms,
            expected_last_closed_ms=rows[0].close_time_ms,
            cutoff_ms=rows[0].close_time_ms,
            provenance="HISTORICAL_ARCHIVE",
            captured_at_ms=1_800_000_000_000,
        )


def test_mutated_frozen_payload_is_revalidated_at_consumption() -> None:
    result = _resolve(_candles())
    forged = object.__new__(historical_bars.ClosedHistoryPayload)
    for field in result.__dataclass_fields__:
        object.__setattr__(forged, field, getattr(result, field))
    object.__setattr__(forged, "candles", (replace(result.candles[0], close=100.75), *result.candles[1:]))
    with pytest.raises(ValueError, match="hash"):
        forged.validate()


def test_bounds_source_tuple_to_five_thousand_rows() -> None:
    rows = _candles(historical_bars.MAX_BARS + 1)
    with pytest.raises(ValueError, match="bounded"):
        _resolve(rows)
