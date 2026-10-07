"""Bounded, immutable, as-of resolver for closed historical candle payloads.

This module verifies caller-supplied data only. It never fetches, reconstructs,
interpolates, or executes a replay. In particular, archive provenance does not
prove that a bar was locally available at its historical decision time.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Literal

from kairos_strategy.candles import Candle

MAX_BARS = 5_000
MINUTE_MS = 60_000
Provenance = Literal["HISTORICAL_ARCHIVE", "CONTEMPORANEOUS_LOCAL", "TEST_FIXTURE"]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROVENANCE = {"HISTORICAL_ARCHIVE", "CONTEMPORANEOUS_LOCAL", "TEST_FIXTURE"}


def _clock(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer millisecond clock")


def _sha(value: str, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _payload_bytes(candles: tuple[Candle, ...]) -> bytes:
    rows = [
        [
            c.symbol,
            c.timeframe,
            c.open_time_ms,
            c.close_time_ms,
            c.open,
            c.high,
            c.low,
            c.close,
            c.volume,
            c.quote_volume,
            c.taker_buy_volume,
            c.taker_buy_quote_volume,
        ]
        for c in candles
    ]
    return json.dumps(rows, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def _validate_candle(candle: Candle) -> None:
    if not isinstance(candle, Candle):
        raise ValueError("source payload contains a non-Candle row")
    # Reconstruct to re-run Candle's pure OHLCV/clock contract, including for
    # source rows later than the as-of cutoff.
    Candle(
        symbol=candle.symbol,
        timeframe=candle.timeframe,
        open_time_ms=candle.open_time_ms,
        close_time_ms=candle.close_time_ms,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        volume=candle.volume,
        quote_volume=candle.quote_volume,
        taker_buy_volume=candle.taker_buy_volume,
        taker_buy_quote_volume=candle.taker_buy_quote_volume,
    )


@dataclass(frozen=True, slots=True)
class ClosedHistoryPayload:
    """Verified, cutoff-bounded closed bars, safe to supply as historical context."""

    candles: tuple[Candle, ...]
    symbol: str
    timeframe: str
    cutoff_ms: int
    first_open_ms: int
    last_closed_ms: int
    payload_sha256: str
    source_artifact_sha256: str | None
    provenance: Provenance
    captured_at_ms: int

    def validate(self) -> None:
        """Recheck the immutable payload at each consumer boundary."""
        if not isinstance(self.candles, tuple) or not 1 <= len(self.candles) <= MAX_BARS:
            raise ValueError("closed history must contain a bounded non-empty tuple")
        if not self.symbol.strip() or self.timeframe != "1m":
            raise ValueError("supported closed history requires a symbol and 1m timeframe")
        for value, name in (
            (self.cutoff_ms, "cutoff_ms"),
            (self.first_open_ms, "first_open_ms"),
            (self.last_closed_ms, "last_closed_ms"),
            (self.captured_at_ms, "captured_at_ms"),
        ):
            _clock(value, name)
        _sha(self.payload_sha256, "payload_sha256")
        if self.source_artifact_sha256 is not None:
            _sha(self.source_artifact_sha256, "source_artifact_sha256")
        if self.provenance not in _PROVENANCE:
            raise ValueError("explicit historical source provenance required")
        if self.provenance != "TEST_FIXTURE" and self.source_artifact_sha256 is None:
            raise ValueError("non-fixture history requires a pinned source artifact hash")
        if self.captured_at_ms < self.last_closed_ms:
            raise ValueError("historical capture cannot precede realized closed bars")
        if self.provenance == "CONTEMPORANEOUS_LOCAL" and not (
            self.last_closed_ms <= self.captured_at_ms <= self.cutoff_ms
        ):
            raise ValueError("contemporaneous capture clock must fall between last close and cutoff")

        previous_open: int | None = None
        for candle in self.candles:
            _validate_candle(candle)
            if candle.symbol != self.symbol or candle.timeframe != self.timeframe:
                raise ValueError("closed history row differs from its declared market")
            if candle.open_time_ms % MINUTE_MS or candle.close_time_ms != candle.open_time_ms + MINUTE_MS - 1:
                raise ValueError("closed history requires exact 1m close timestamps")
            if previous_open is not None and candle.open_time_ms != previous_open + MINUTE_MS:
                raise ValueError("closed history must have an exact contiguous 1m cadence")
            if candle.close_time_ms > self.cutoff_ms:
                raise ValueError("future or unclosed bar cannot enter causal history")
            previous_open = candle.open_time_ms

        if (
            self.candles[0].open_time_ms != self.first_open_ms
            or self.candles[-1].close_time_ms != self.last_closed_ms
            or self.last_closed_ms > self.cutoff_ms
            or hashlib.sha256(_payload_bytes(self.candles)).hexdigest() != self.payload_sha256
        ):
            raise ValueError("closed history anchors or canonical payload hash differ")

    def prompt_payload(self) -> tuple[dict[str, str | int | float], ...]:
        """Return only causal closed bars, with no source/future metadata."""
        self.validate()
        return tuple(
            {
                key: value
                for key, value in asdict(candle).items()
                if key
                in {"symbol", "timeframe", "open_time_ms", "close_time_ms", "open", "high", "low", "close"}
            }
            for candle in self.candles
        )


def resolve_closed_history(
    *,
    candles: tuple[Candle, ...],
    expected_payload_sha256: str,
    expected_symbol: str,
    expected_timeframe: str,
    expected_count: int,
    expected_first_open_ms: int,
    expected_last_closed_ms: int,
    cutoff_ms: int,
    provenance: Provenance,
    captured_at_ms: int,
    source_artifact_sha256: str | None = None,
) -> ClosedHistoryPayload:
    """Verify an exact caller-supplied tuple and return only its causal prefix.

    The expected full-payload checksum is checked before as-of slicing so that
    the caller pins its exact source. Only rows closed by ``cutoff_ms`` are
    present in the returned object; its digest is over that safe prefix.
    """
    if not isinstance(candles, tuple) or not 1 <= len(candles) <= MAX_BARS:
        raise ValueError("caller must supply a bounded non-empty Candle tuple")
    if type(expected_count) is not int or expected_count != len(candles):
        raise ValueError("caller-supplied row count differs from expected count")
    if not isinstance(expected_symbol, str) or not expected_symbol.strip():
        raise ValueError("expected symbol required")
    if expected_timeframe != "1m":
        raise ValueError("historical causal resolver currently accepts 1m bars only")
    _sha(expected_payload_sha256, "expected_payload_sha256")
    _clock(expected_first_open_ms, "expected_first_open_ms")
    _clock(expected_last_closed_ms, "expected_last_closed_ms")
    if expected_first_open_ms % MINUTE_MS or (expected_last_closed_ms + 1) % MINUTE_MS:
        raise ValueError("expected anchors must align to exact UTC minute boundaries")
    _clock(cutoff_ms, "cutoff_ms")
    _clock(captured_at_ms, "captured_at_ms")
    if provenance not in _PROVENANCE:
        raise ValueError("explicit historical source provenance required")
    if source_artifact_sha256 is not None:
        _sha(source_artifact_sha256, "source_artifact_sha256")

    # Validate source membership/cadence before hashing or selecting a prefix.
    previous_open: int | None = None
    for candle in candles:
        _validate_candle(candle)
        if candle.symbol != expected_symbol or candle.timeframe != expected_timeframe:
            raise ValueError("source bar differs from expected symbol/timeframe")
        if candle.open_time_ms % MINUTE_MS or candle.close_time_ms != candle.open_time_ms + MINUTE_MS - 1:
            raise ValueError("source requires exact 1m bar close timestamps")
        if previous_open is not None and candle.open_time_ms != previous_open + MINUTE_MS:
            raise ValueError("source bars must have exact contiguous 1m cadence")
        previous_open = candle.open_time_ms
    if candles[0].open_time_ms != expected_first_open_ms:
        raise ValueError("source first-open anchor differs")
    if hashlib.sha256(_payload_bytes(candles)).hexdigest() != expected_payload_sha256:
        raise ValueError("canonical full-payload SHA-256 mismatch")
    if captured_at_ms < candles[-1].close_time_ms:
        raise ValueError("full source artifact cannot be captured before its latest realized bar")

    closed = tuple(c for c in candles if c.close_time_ms <= cutoff_ms)
    if not closed or closed[-1].close_time_ms != expected_last_closed_ms:
        raise ValueError("expected last-closed anchor is not the latest bar available at cutoff")
    if any(c.close_time_ms > cutoff_ms for c in closed):
        raise ValueError("future or unclosed bar cannot enter causal history")

    result = ClosedHistoryPayload(
        candles=closed,
        symbol=expected_symbol,
        timeframe=expected_timeframe,
        cutoff_ms=cutoff_ms,
        first_open_ms=closed[0].open_time_ms,
        last_closed_ms=closed[-1].close_time_ms,
        payload_sha256=hashlib.sha256(_payload_bytes(closed)).hexdigest(),
        source_artifact_sha256=source_artifact_sha256,
        provenance=provenance,
        captured_at_ms=captured_at_ms,
    )
    result.validate()
    return result
