"""Bounded live-only public market receipts for the opt-in CURRENT chain.

Nothing is started on import. ``capture_initial`` is a one-shot explicit call,
limited to 120 seconds, fixed Binance USD-M symbols, finite REST requests and
one non-reconnecting market WebSocket. It grants neither risk authority nor
continuous market coverage beyond the exact observed window.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import ssl
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .current_capture import (
    MAX_CAPTURE_BYTES,
    MAX_QUOTE_BYTES,
    UNIVERSE,
    CaptureRefused,
    CurrentPublicCapture,
    FreshQuoteSnapshot,
    _canonical_bytes,
    _write_receipt,
)
from .current_inputs import CapturedClosedBar, QuantMeasurement, QuantMeasurements

MAX_LIVE_SECONDS = 120
MAX_LIVE_MARKET_BYTES = 16 * 1024 * 1024
MAX_RETAINED_QUOTE_COUNT = 40
MAX_RETAINED_QUOTE_BYTES = 32 * 1024 * 1024
MARKET_GAP_LIMIT_SECONDS = 10.0
MARKET_WS_BASE = "wss://fstream.binance.com"
REST_BASE = "https://fapi.binance.com"


class CurrentLiveRefused(RuntimeError):
    """The bounded public live capture cannot establish the requested facts."""


@dataclass(frozen=True, slots=True)
class CurrentLiveCaptureResult:
    quant_measurements_by_symbol: tuple[tuple[str, QuantMeasurements], ...]
    frames: tuple[Any, ...]
    receipt: dict[str, Any]
    tape_id: str
    market_receipt_path: Path
    closed_bars: tuple[tuple[str, tuple[CapturedClosedBar, ...]], ...]


class CurrentLiveCapture:
    """Injected-source wrapper; it never starts until ``capture_initial``.

    ``capture`` must be a fresh ``CurrentPublicCapture`` with its own bounded
    root/budget. The public depth recorder writes an independent V2 bundle. The
    market stream is one fixed-universe existing Quant route, with no reconnect;
    force-order values are only scoped to that observed connected interval.
    """

    def __init__(
        self,
        output_root: Path,
        *,
        capture: CurrentPublicCapture,
        tape_id: str,
        max_seconds: int = MAX_LIVE_SECONDS,
        observation_seconds: int = 300,
        quote_capture_factory: Callable[[], CurrentPublicCapture] | None = None,
    ) -> None:
        if not isinstance(output_root, Path) or not output_root.is_absolute():
            raise ValueError("absolute output root required")
        if type(capture) is not CurrentPublicCapture:
            raise ValueError("fresh bounded CurrentPublicCapture required")
        if type(tape_id) is not str or not tape_id.strip() or len(tape_id) > 128:
            raise ValueError("explicit normalized simulation tape id required")
        if type(max_seconds) is not int or not 1 <= max_seconds <= MAX_LIVE_SECONDS:
            raise ValueError("live capture must be bounded to 1..120 seconds")
        if type(observation_seconds) is not int or not max_seconds <= observation_seconds <= 900:
            raise ValueError("closed-bar observation window must be bounded to <=900 seconds")
        self.output_root = output_root
        self.capture = capture
        self.requested_tape_id = tape_id
        self.max_seconds = max_seconds
        self.observation_seconds = observation_seconds
        self.quote_capture_factory = quote_capture_factory
        self._result: CurrentLiveCaptureResult | None = None
        self._bars: dict[str, dict[int, CapturedClosedBar]] = defaultdict(dict)
        self._conditions: dict[str, asyncio.Condition] = {symbol: asyncio.Condition() for symbol in UNIVERSE}
        self._latest_frames: dict[str, Any] = {}
        self._live_started = False
        self._market_task: asyncio.Task | None = None
        self._market_initial: asyncio.Future | None = None
        self._quote_capture_lock = asyncio.Lock()
        self._quote_snapshots_by_identity: dict[tuple[str, str], FreshQuoteSnapshot] = {}
        self._quote_capture_count = 0
        self._quote_capture_bytes = 0

    async def __aenter__(self) -> CurrentLiveCapture:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._stop_market_task()

    async def _stop_market_task(self) -> None:
        if self._market_task is not None:
            if not self._market_task.done():
                self._market_task.cancel()
            await asyncio.gather(self._market_task, return_exceptions=True)

    async def capture_initial(self) -> CurrentLiveCaptureResult:
        if self._result is not None or self._live_started:
            raise CurrentLiveRefused("ONE_SHOT_LIVE_CAPTURE_ONLY")
        self._live_started = True
        if self.capture.requests or self.capture.bytes_used:
            raise CurrentLiveRefused("LIVE_METRIC_CAPTURE_REQUIRES_FRESH_PUBLIC_CAPTURE_BUDGET")
        metrics = await self._capture_rest_metrics()
        book_dir = self._book_output_path()

        self._market_initial = asyncio.get_running_loop().create_future()
        self._market_task = asyncio.create_task(
            self._capture_market_stream(), name="kairos-current-market-capture"
        )
        book_task = asyncio.create_task(
            _capture_v2_window(book_dir, seconds=self.max_seconds),
            name="kairos-current-v2-book-capture",
        )
        book_results = await asyncio.gather(book_task, return_exceptions=True)
        if isinstance(book_results[0], BaseException):
            await self._stop_market_task()
            raise CurrentLiveRefused(f"V2_BOOK_CAPTURE_FAILED:{type(book_results[0]).__name__}")
        book_receipt = book_results[0]
        if type(book_receipt) is not dict:
            await self._stop_market_task()
            raise CurrentLiveRefused("V2_BOOK_CAPTURE_RECEIPT_INVALID")
        if book_receipt.get("state") != "CAPTURED":
            # A failed source-book receipt is terminal evidence. Do not wait for
            # the independent Quant window future after this source has failed.
            await self._stop_market_task()
            reason = book_receipt.get("reason", "UNKNOWN")
            raise CurrentLiveRefused(f"V2_BOOK_CAPTURE_NOT_COMPLETE:{reason}")
        if self._market_initial is None or self._market_task is None:
            await self._stop_market_task()
            raise CurrentLiveRefused("MARKET_INITIAL_CAPTURE_NOT_STARTED")
        done, _pending = await asyncio.wait(
            {self._market_initial, self._market_task},
            timeout=self.max_seconds + MARKET_GAP_LIMIT_SECONDS + 1.0,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            await self._stop_market_task()
            raise CurrentLiveRefused("MARKET_INITIAL_CAPTURE_TIMEOUT")
        if self._market_task in done and not self._market_initial.done():
            try:
                self._market_task.result()
            except Exception as exc:
                await self._stop_market_task()
                raise CurrentLiveRefused(f"MARKET_STREAM_CAPTURE_FAILED:{type(exc).__name__}") from None
            await self._stop_market_task()
            raise CurrentLiveRefused("MARKET_STREAM_ENDED_BEFORE_INITIAL_CAPTURE")
        try:
            market_result = self._market_initial.result()
        except Exception as exc:
            await self._stop_market_task()
            raise CurrentLiveRefused(f"MARKET_STREAM_CAPTURE_FAILED:{type(exc).__name__}") from None
        frames = self._read_v2_frames(book_dir, book_receipt)
        receipt_path = self._persist_market_receipt(market_result)
        completed_metrics = self._attach_force_order_metrics(metrics, market_result)
        # PublicBookRecorder generates its own actual capture identity; don't
        # rewrite immutable frame IDs to the requested caller label.
        actual_tape_id = book_receipt["capture_id"]
        self._latest_frames = {
            symbol: next((frame for frame in reversed(frames) if frame.symbol == symbol), None)
            for symbol in UNIVERSE
        }
        self._result = CurrentLiveCaptureResult(
            completed_metrics,
            frames,
            book_receipt,
            actual_tape_id,
            receipt_path,
            tuple(
                (symbol, tuple(sorted(self._bars[symbol].values(), key=lambda bar: bar.event_ms)))
                for symbol in sorted(UNIVERSE)
            ),
        )
        return self._result

    async def fresh_quote(self, symbol: str) -> FreshQuoteSnapshot:
        if self.quote_capture_factory is None:
            raise CurrentLiveRefused("FRESH_SEPARATE_QUOTE_CAPTURE_FACTORY_REQUIRED")
        if symbol not in UNIVERSE:
            raise CurrentLiveRefused("QUOTE_SYMBOL_OUTSIDE_FIXED_UNIVERSE")
        async with self._quote_capture_lock:
            if self._quote_capture_count >= MAX_RETAINED_QUOTE_COUNT:
                raise CurrentLiveRefused("LIVE_QUOTE_CAPTURE_COUNT_LIMIT")
            fresh_capture = self.quote_capture_factory()
            if (
                type(fresh_capture) is not CurrentPublicCapture
                or fresh_capture.requests
                or fresh_capture.bytes_used
            ):
                raise CurrentLiveRefused("QUOTE_CAPTURE_FACTORY_MUST_RETURN_FRESH_CAPTURE")
            # Count attempted network captures, including malformed/failed
            # responses, so repeated failures cannot escape the finite cap.
            self._quote_capture_count += 1
            try:
                snapshot = await fresh_capture.fresh_quote(symbol)
            except Exception:
                self._quote_capture_bytes += fresh_capture.bytes_used
                if self._quote_capture_bytes > MAX_RETAINED_QUOTE_BYTES:
                    raise CurrentLiveRefused("LIVE_QUOTE_CAPTURE_BYTE_LIMIT") from None
                raise
            body_bytes = len(snapshot.raw_body)
            if body_bytes <= 0 or self._quote_capture_bytes + body_bytes > MAX_RETAINED_QUOTE_BYTES:
                raise CurrentLiveRefused("LIVE_QUOTE_CAPTURE_BYTE_LIMIT")
            quote = snapshot.entry_quote
            identity = (snapshot.symbol, quote.sha256)
            if quote.symbol != symbol or snapshot.symbol != symbol:
                raise CurrentLiveRefused("LIVE_QUOTE_CAPTURE_IDENTITY_MISMATCH")
            existing = self._quote_snapshots_by_identity.get(identity)
            if existing is not None and existing != snapshot:
                raise CurrentLiveRefused("LIVE_QUOTE_HASH_COLLISION")
            self._quote_snapshots_by_identity[identity] = snapshot
            self._quote_capture_bytes += body_bytes
            return snapshot

    def quote_snapshot_for(self, entry_quote: Any) -> FreshQuoteSnapshot | None:
        """Return the retained exact REST capture that produced this quote, if any.

        This is a read-only identity lookup; it never performs I/O, refreshes a
        timestamp, or turns a previously captured quote into a fresh one.
        """

        try:
            symbol = entry_quote.symbol
            quote_sha = entry_quote.sha256
        except (AttributeError, TypeError, ValueError):
            return None
        if symbol not in UNIVERSE or type(quote_sha) is not str:
            return None
        retained = self._quote_snapshots_by_identity.get((symbol, quote_sha))
        if retained is None or retained.entry_quote != entry_quote:
            return None
        return retained

    async def wait_closed_bar(
        self, symbol: str, after_close_ms: int, *, timeout_s: float
    ) -> CapturedClosedBar | None:
        if symbol not in UNIVERSE or type(after_close_ms) is not int:
            raise CurrentLiveRefused("CLOSED_BAR_REQUEST_INVALID")
        if type(timeout_s) not in {int, float} or not math.isfinite(timeout_s) or not 0 < timeout_s <= 300:
            raise CurrentLiveRefused("CLOSED_BAR_WAIT_EXCEEDS_FIVE_MINUTES")
        cache = self._bars[symbol]
        available = [close for close in cache if close > after_close_ms]
        if available:
            return cache[min(available)]
        condition = self._conditions[symbol]
        try:
            async with condition:
                await asyncio.wait_for(
                    condition.wait_for(lambda: any(close > after_close_ms for close in cache)),
                    timeout=timeout_s,
                )
        except TimeoutError:
            return None
        available = [close for close in cache if close > after_close_ms]
        return cache[min(available)] if available else None

    async def latest(self, symbol: str) -> Any | None:
        if symbol not in UNIVERSE:
            return None
        return self._latest_frames.get(symbol)

    async def _capture_rest_metrics(self) -> tuple[tuple[str, _RESTQuantBase], ...]:
        result: list[tuple[str, _RESTQuantBase]] = []
        try:
            for symbol in UNIVERSE:
                prefix = symbol.lower()
                funding = await self._rest_json(
                    f"{REST_BASE}/fapi/v1/premiumIndex?{urlencode({'symbol': symbol})}",
                    f"{prefix}.funding.raw",
                    MAX_QUOTE_BYTES,
                )
                oi = await self._rest_json(
                    f"{REST_BASE}/fapi/v1/openInterest?{urlencode({'symbol': symbol})}",
                    f"{prefix}.open-interest.raw",
                    MAX_QUOTE_BYTES,
                )
                history_query = urlencode({"symbol": symbol, "period": "5m", "limit": "13"})
                history = await self._rest_json(
                    f"{REST_BASE}/futures/data/openInterestHist?{history_query}",
                    f"{prefix}.open-interest-history.raw",
                    MAX_QUOTE_BYTES,
                )
                funding_value = _number(funding.value.get("lastFundingRate"))
                funding_event = _integer(funding.value.get("time"))
                oi_value = _number(oi.value.get("openInterest"))
                oi_event = _integer(oi.value.get("time"))
                rows = history.value
                points = []
                if type(rows) is list:
                    for row in rows:
                        if type(row) is not dict:
                            continue
                        points.append(
                            (_integer(row.get("timestamp")), _number(row.get("sumOpenInterestValue")))
                        )
                if (
                    funding_value is None
                    or funding_event is None
                    or oi_value is None
                    or oi_value <= 0
                    or oi_event is None
                    or len(points) != 13
                    or any(ts is None or value is None or value <= 0 for ts, value in points)
                ):
                    raise CurrentLiveRefused("QUANT_REST_RESPONSE_FIELDS_MISSING")
                ordered = sorted(points)
                timestamps = [point[0] for point in ordered]
                values = [point[1] for point in ordered]
                if (
                    len(set(timestamps)) != 13
                    or any(b - a != 300_000 for a, b in zip(timestamps, timestamps[1:], strict=False))
                    or timestamps[-1] - timestamps[0] != 3_600_000
                    or self.capture.wall_ms_fn() - timestamps[-1] not in range(0, 600_001)
                ):
                    raise CurrentLiveRefused("OPEN_INTEREST_HISTORY_NOT_FRESH_COMPLETE_13_POINT_WINDOW")
                oi_change = (values[-1] - values[0]) / values[0] * 100.0
                result.append(
                    (
                        symbol,
                        _RESTQuantBase(
                            _measurement(
                                funding_value,
                                "binance_public_funding_rest",
                                funding_event,
                                funding,
                                scope="LATEST_PUBLIC_FUNDING_RATE",
                            ),
                            _measurement(
                                oi_value,
                                "binance_public_open_interest_rest",
                                oi_event,
                                oi,
                                scope="LATEST_OPEN_INTEREST_VALUE",
                            ),
                            _measurement(
                                oi_change,
                                "binance_public_open_interest_history_rest",
                                timestamps[-1],
                                history,
                                scope="COMPLETE_13_CONSECUTIVE_5M_OPEN_INTEREST_POINTS",
                                start=timestamps[0],
                                end=timestamps[-1],
                            ),
                        ),
                    )
                )
        except (CaptureRefused, CurrentLiveRefused):
            raise
        except Exception as exc:
            raise CurrentLiveRefused(f"QUANT_REST_CAPTURE_FAILED:{type(exc).__name__}") from None
        return tuple(result)

    async def _rest_json(self, url: str, filename: str, byte_limit: int) -> _RESTCapture:
        response, requested_ms, received_ms = await self.capture._request(url, max_response_bytes=byte_limit)
        try:
            value = json.loads(response.body.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError, RecursionError):
            raise CurrentLiveRefused("QUANT_REST_JSON_INVALID") from None
        if type(value) not in {dict, list}:
            raise CurrentLiveRefused("QUANT_REST_JSON_SCHEMA_INVALID")
        path, persisted_ms, sha = self.capture._persist(filename, response.body, received_ms=received_ms)
        return _RESTCapture(value, response.body, sha, requested_ms, received_ms, persisted_ms, path)

    async def _capture_market_stream(self) -> dict[str, Any]:
        import aiohttp

        # Reuse the existing Quant collector's fixed market-route subscription
        # definition, but consume one socket directly so reconnect means failure.
        from kairos_quant.collectors.binance_ws import BinanceFuturesCollector

        collector = BinanceFuturesCollector(
            [symbol.lower() for symbol in UNIVERSE],
            MARKET_WS_BASE,
            REST_BASE,
            kline_finality_delay_s=0,
        )
        endpoint = collector._stream_urls()["market"]
        allowed_streams = set(collector._subscriptions["market"])
        path = self.capture.capture_dir / "market-websocket.raw.jsonl"
        stream_hash = hashlib.sha256()
        stream_bytes = 0
        market_window_start = 0
        last_receive = 0
        force_values: dict[str, list[float]] = {symbol: [0.0, 0.0] for symbol in UNIVERSE}
        force_last_event: dict[str, int] = {}
        marks: set[str] = set()
        ssl_context = ssl.create_default_context()
        if not ssl_context.check_hostname or ssl_context.verify_mode != ssl.CERT_REQUIRED:
            raise CurrentLiveRefused("DEFAULT_TLS_VALIDATION_UNAVAILABLE")
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=10)
        try:
            with path.open("xb") as raw_file:
                async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                    async with session.ws_connect(
                        endpoint,
                        ssl=ssl_context,
                        proxy=None,
                        autoping=True,
                        heartbeat=None,
                        max_msg_size=MAX_QUOTE_BYTES,
                    ) as socket:
                        market_window_start = time.time_ns() // 1_000_000
                        last_receive = market_window_start
                        window_start_mono = time.monotonic()
                        initial_deadline = window_start_mono + self.max_seconds
                        observation_deadline = window_start_mono + self.observation_seconds
                        window_end_ms = market_window_start + self.max_seconds * 1_000
                        message_count = 0
                        while time.monotonic() < observation_deadline:
                            remaining = observation_deadline - time.monotonic()
                            try:
                                message = await asyncio.wait_for(
                                    socket.receive(), min(MARKET_GAP_LIMIT_SECONDS, remaining)
                                )
                            except TimeoutError:
                                raise CurrentLiveRefused("MARKET_STREAM_RECEIVE_GAP") from None
                            received_ms = time.time_ns() // 1_000_000
                            if (
                                self._market_initial is not None
                                and not self._market_initial.done()
                                and time.monotonic() >= initial_deadline
                            ):
                                if len(marks) != len(UNIVERSE):
                                    raise CurrentLiveRefused("INITIAL_MARKET_FIVE_SYMBOL_LIVENESS_MISSING")
                                self._market_initial.set_result(
                                    {
                                        "window_start_ms": market_window_start,
                                        "window_end_ms": window_end_ms,
                                        "last_receive_ms": last_receive,
                                        "force_values": {
                                            key: list(value) for key, value in force_values.items()
                                        },
                                        "force_last_event": dict(force_last_event),
                                        "raw_sha256": stream_hash.copy().hexdigest(),
                                        "raw_bytes": stream_bytes,
                                        "raw_path": str(path),
                                        "rows": message_count,
                                    }
                                )
                            if message.type is not aiohttp.WSMsgType.TEXT or type(message.data) is not str:
                                raise CurrentLiveRefused("MARKET_STREAM_CLOSED_OR_NON_TEXT")
                            payload_bytes = message.data.encode("utf-8", errors="strict")
                            if not payload_bytes or stream_bytes + len(payload_bytes) > MAX_LIVE_MARKET_BYTES:
                                raise CurrentLiveRefused("MARKET_STREAM_RAW_BYTE_BOUND_EXCEEDED")
                            wire = _strict_json(message.data)
                            stream = wire.get("stream")
                            data = wire.get("data")
                            if (
                                type(stream) is not str
                                or stream not in allowed_streams
                                or type(data) is not dict
                            ):
                                raise CurrentLiveRefused("MARKET_STREAM_SCOPE_INVALID")
                            symbol = stream.partition("@")[0].upper()
                            if symbol not in UNIVERSE:
                                raise CurrentLiveRefused("MARKET_STREAM_SYMBOL_INVALID")
                            row = (
                                _canonical_bytes(
                                    {
                                        "sequence": stream_bytes + 1,
                                        "requested_ms": market_window_start,
                                        "received_ms": received_ms,
                                        "raw_payload": message.data,
                                        "raw_payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
                                    }
                                )
                                + b"\n"
                            )
                            if self.capture.bytes_used + stream_bytes + len(row) > MAX_CAPTURE_BYTES:
                                raise CurrentLiveRefused("SHARED_CAPTURE_BYTE_BOUND_EXCEEDED")
                            if raw_file.write(row) != len(row):
                                raise OSError("incomplete websocket record write")
                            raw_file.flush()
                            os.fsync(raw_file.fileno())
                            persisted_ms = time.time_ns() // 1_000_000
                            stream_hash.update(row)
                            stream_bytes += len(row)
                            message_count += 1
                            last_receive = received_ms
                            event_ms = _integer(data.get("E"))
                            if event_ms is not None and event_ms > received_ms:
                                raise CurrentLiveRefused("MARKET_EXCHANGE_CLOCK_AFTER_LOCAL_RECEIPT")
                            if "@markprice" in stream:
                                if event_ms is None:
                                    raise CurrentLiveRefused("MARK_PRICE_EVENT_CLOCK_MISSING")
                                marks.add(symbol)
                            if "@forceorder" in stream:
                                order = data.get("o")
                                if type(order) is not dict:
                                    raise CurrentLiveRefused("FORCE_ORDER_SCHEMA_INVALID")
                                price = _number(order.get("ap")) or _number(order.get("p"))
                                quantity = _number(order.get("z")) or _number(order.get("q"))
                                side = order.get("S")
                                order_event = event_ms or _integer(order.get("T"))
                                if (
                                    price is None
                                    or quantity is None
                                    or price <= 0
                                    or quantity <= 0
                                    or side not in {"BUY", "SELL"}
                                    or order_event is None
                                    or order_event > received_ms
                                ):
                                    raise CurrentLiveRefused("FORCE_ORDER_MEASUREMENT_INVALID")
                                index = 0 if side == "SELL" else 1
                                force_values[symbol][index] += price * quantity
                                force_last_event[symbol] = order_event
                            if "@kline_1m" in stream:
                                self._capture_closed_bar(
                                    symbol, data, message.data, received_ms, persisted_ms
                                )
                ended_ms = time.time_ns() // 1_000_000
        except (CurrentLiveRefused, asyncio.CancelledError):
            raise
        except Exception as exc:
            raise CurrentLiveRefused(f"MARKET_STREAM_CAPTURE_FAILED:{type(exc).__name__}") from None
        if self._market_initial is not None and not self._market_initial.done():
            if len(marks) != len(UNIVERSE):
                raise CurrentLiveRefused("MARKET_STREAM_FIVE_SYMBOL_LIVENESS_NOT_OBSERVED")
            self._market_initial.set_result(
                {
                    "window_start_ms": market_window_start,
                    "window_end_ms": min(ended_ms, window_end_ms),
                    "last_receive_ms": last_receive,
                    "force_values": {key: list(value) for key, value in force_values.items()},
                    "force_last_event": dict(force_last_event),
                    "raw_sha256": stream_hash.hexdigest(),
                    "raw_bytes": stream_bytes,
                    "raw_path": str(path),
                    "rows": message_count,
                }
            )
        return {"terminal_ms": ended_ms, "raw_sha256": stream_hash.hexdigest(), "raw_bytes": stream_bytes}

    def _capture_closed_bar(
        self, symbol: str, data: dict[str, Any], raw: str, received_ms: int, persisted_ms: int
    ) -> None:
        kline = data.get("k")
        if type(kline) is not dict or kline.get("x") is not True:
            return
        try:
            open_ms = _integer(kline.get("t"))
            close_ms = _integer(kline.get("T"))
            candle = __import__("kairos_strategy.candles", fromlist=["Candle"]).Candle(
                symbol,
                "1m",
                open_ms,
                close_ms,
                _number(kline.get("o")),
                _number(kline.get("h")),
                _number(kline.get("l")),
                _number(kline.get("c")),
                _number(kline.get("v")),
                _number(kline.get("q")),
                _number(kline.get("V")),
                _number(kline.get("Q")),
            )
            receipt = CapturedClosedBar(
                candle,
                raw.encode("utf-8"),
                "binance_um_market_ws_closed_kline",
                close_ms,
                received_ms,
                persisted_ms,
                hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            )
        except Exception:
            raise CurrentLiveRefused("CLOSED_KLINE_RECEIPT_INVALID") from None
        prior = self._bars[symbol].get(close_ms)
        if prior is not None and prior != receipt:
            raise CurrentLiveRefused("CONFLICTING_CLOSED_KLINE_RECEIPT")
        self._bars[symbol][close_ms] = receipt
        condition = self._conditions[symbol]
        asyncio.create_task(self._notify(condition))

    @staticmethod
    async def _notify(condition: asyncio.Condition) -> None:
        async with condition:
            condition.notify_all()

    async def _attach_force_order_metrics(
        self,
        metrics: tuple[tuple[str, _RESTQuantBase], ...],
        market: dict[str, Any],
    ) -> tuple[tuple[str, QuantMeasurements], ...]:
        start = market["window_start_ms"]
        end = market["window_end_ms"]
        received = market["last_receive_ms"]
        captured = time.time_ns() // 1_000_000
        if end < start or captured < received or end - start < (self.max_seconds - 1) * 1_000:
            raise CurrentLiveRefused("FORCE_ORDER_WINDOW_NOT_FULLY_OBSERVED")
        result = []
        for symbol, base in metrics:
            long_usd, short_usd = market["force_values"][symbol]
            # For a no-event interval, the event clock is the local completed
            # window boundary and scope explicitly identifies the interval sum.
            long_event = market["force_last_event"].get(symbol, end)
            short_event = long_event
            long_metric = QuantMeasurement(
                long_usd,
                "binance_um_force_order_stream",
                long_event,
                received,
                captured,
                market["raw_sha256"],
                "CONTINUOUS_FORCE_ORDER_CAPTURE_WINDOW",
                start,
                end,
                True,
            )
            short_metric = QuantMeasurement(
                short_usd,
                "binance_um_force_order_stream",
                short_event,
                received,
                captured,
                market["raw_sha256"],
                "CONTINUOUS_FORCE_ORDER_CAPTURE_WINDOW",
                start,
                end,
                True,
            )
            result.append(
                (
                    symbol,
                    QuantMeasurements(
                        symbol,
                        base.funding_rate,
                        base.open_interest,
                        base.oi_change_pct_1h,
                        long_metric,
                        short_metric,
                    ),
                )
            )
        return tuple(result)

    def _read_v2_frames(self, output: Path, receipt: dict[str, Any]) -> tuple[Any, ...]:
        from adaptive_replay.book_bundle import (
            BookBundleSeal,
            RetentionReceipt,
            open_book_bundle,
        )
        from adaptive_replay.native_book_capture import NativeBookPolicy

        frames = []
        for segment in receipt.get("segments", []):
            seal_obj = dict(segment["seal"])
            policy_obj = NativeBookPolicy(**seal_obj["policy"])
            seal = BookBundleSeal(**{**seal_obj, "policy": policy_obj})
            retention = RetentionReceipt(**segment["retention"])
            retained = open_book_bundle(output / segment["name"], seal, retention)
            frames.extend(binding.frame for binding in retained.bindings)
        if len(frames) != receipt.get("admitted_frames") or not frames:
            raise CurrentLiveRefused("SEALED_V2_FRAME_ROSTER_INVALID")
        return tuple(frames)

    def _persist_market_receipt(self, result: dict[str, Any]) -> Path:
        receipt = {
            "schema": "kairos.current-public-market-window.v1",
            "source": "existing_kairos_quant_binance_market_route",
            "symbols": list(UNIVERSE),
            "window_start_ms": result["window_start_ms"],
            "window_end_ms": result["window_end_ms"],
            "last_receive_ms": result["last_receive_ms"],
            "rows": result["rows"],
            "raw_bytes": result["raw_bytes"],
            "raw_sha256": result["raw_sha256"],
            "raw_file": Path(result["raw_path"]).name,
            "force_order_scope": "CONNECTED_FIXED_FIVE_SYMBOL_MARKET_WS_WINDOW_ONLY",
            "feed_gap_free_claim": False,
            "exchange_source_completeness": "UNKNOWN",
            "continuity_evidence": "SINGLE_SOCKET_NO_RECONNECT_WITHIN_CAPTURE_WINDOW",
            "risk_authority": "NONE",
        }
        return _write_receipt(self.capture.capture_dir, "market-websocket.receipt.json", receipt)

    def _book_output_path(self) -> Path:
        from datetime import UTC, datetime

        now = datetime.fromtimestamp(time.time(), tz=UTC)
        suffix = uuid.uuid4().hex[:12]
        return self.output_root / f"public-book-capture-{now:%Y%m%d}-{suffix}"


@dataclass(frozen=True, slots=True)
class _RESTCapture:
    value: Any
    body: bytes
    raw_sha256: str
    requested_ms: int
    received_ms: int
    persisted_ms: int
    path: Path


async def _capture_v2_window(
    output: Path,
    *,
    seconds: int,
    wall_clock: Callable[[], int] | None = None,
    monotonic_clock: Callable[[], int] | None = None,
) -> dict[str, Any]:
    """Record the existing V2 policy window starting after verified WS setup.

    The recorder's source clocks and five-second admission rules are untouched;
    only pre-capture DNS/TLS/WebSocket setup is outside that observed-data
    denominator. Optional clocks are an offline test seam.
    """

    import aiohttp
    from adaptive_replay.public_book_capture import (
        ENDPOINT,
        MAX_RAW_BYTES,
        CaptureOwner,
        PublicBookRecorder,
        wall_ms,
    )

    clock = wall_clock or wall_ms
    mono = monotonic_clock or time.monotonic_ns

    async def reject_redirect(*_args: Any) -> None:
        raise ValueError("public capture redirects are forbidden")

    trace = aiohttp.TraceConfig()
    trace.on_request_redirect.append(reject_redirect)
    ssl_context = ssl.create_default_context()
    if not ssl_context.check_hostname or ssl_context.verify_mode != ssl.CERT_REQUIRED:
        raise CurrentLiveRefused("DEFAULT_TLS_VALIDATION_UNAVAILABLE")

    recorder = None
    handshake_completed_ms: int | None = None
    state, reason = "FAILED", "NO_CONNECTION"
    transport: dict[str, Any] = {
        "endpoint": ENDPOINT,
        "attempts": 0,
        "retries": 0,
        "redirects": 0,
        "tls_default_validation": True,
        "handshake_completed": False,
    }
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=10)
    with CaptureOwner(output.parent):
        try:
            async with asyncio.timeout(seconds + 15):
                async with aiohttp.ClientSession(
                    timeout=timeout, trust_env=False, trace_configs=[trace]
                ) as session:
                    transport["attempts"] = 1
                    async with session.ws_connect(
                        ENDPOINT,
                        ssl=ssl_context,
                        proxy=None,
                        autoping=True,
                        heartbeat=None,
                        max_msg_size=MAX_RAW_BYTES,
                    ) as socket:
                        if str(socket._response.url) != ENDPOINT:
                            raise ValueError("unexpected public capture response URL")
                        transport["handshake_completed"] = True
                        handshake_completed_ms = clock()
                        # This instant, after TLS and the verified WS upgrade,
                        # starts both the admission TTL and bounded capture.
                        recorder = PublicBookRecorder(output, seconds=seconds, clock=clock, monotonic=mono)
                        deadline = time.monotonic() + seconds
                        while time.monotonic() < deadline:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                break
                            try:
                                message = await asyncio.wait_for(socket.receive(), min(5.0, remaining))
                            except TimeoutError:
                                if time.monotonic() >= deadline:
                                    break
                                raise ValueError("public stream receive gap") from None
                            received_ms, received_ns = clock(), mono()
                            if message.type is not aiohttp.WSMsgType.TEXT:
                                raise ValueError("public stream closed or returned non-text")
                            recorder.accept(message.data, received_ms=received_ms, received_ns=received_ns)
                        state, reason = "CAPTURED", "SEALED_DURATION_COMPLETE"
        except (Exception, asyncio.CancelledError) as exc:
            state, reason = "FAILED", type(exc).__name__
        finally:
            # Match the existing capture's bounded aiohttp TLS-close drain.
            await asyncio.sleep(0.250)
        if recorder is None:
            raise CurrentLiveRefused(f"V2_BOOK_HANDSHAKE_FAILED:{reason}") from None
        receipt = recorder.finish(state=state, reason=reason, transport=transport)
        if handshake_completed_ms is None:
            raise CurrentLiveRefused("V2_BOOK_HANDSHAKE_CLOCK_MISSING")
        _write_receipt(
            output,
            "handshake-provenance.receipt.json",
            {
                "schema": "kairos.current-live-public-book-handshake.v1",
                "capture_id": receipt["capture_id"],
                "endpoint": ENDPOINT,
                "transport_attempts": transport["attempts"],
                "handshake_completed": transport["handshake_completed"],
                "handshake_completed_ms": handshake_completed_ms,
                "recorder_started_ms": recorder.started_ms,
                "recorder_started_monotonic_ns": recorder.started_ns,
                "capture_seconds_from_recorder_start": seconds,
                "source_receipt_sha256": hashlib.sha256(_canonical_bytes(receipt)).hexdigest(),
                "risk_authority": "NONE",
            },
        )
        return receipt


@dataclass(frozen=True, slots=True)
class _RESTQuantBase:
    funding_rate: QuantMeasurement
    open_interest: QuantMeasurement
    oi_change_pct_1h: QuantMeasurement


def _measurement(
    value: float,
    source_id: str,
    event_ms: int,
    raw: _RESTCapture,
    *,
    scope: str = "",
    start: int | None = None,
    end: int | None = None,
) -> QuantMeasurement:
    if not raw.requested_ms <= raw.received_ms <= raw.persisted_ms:
        raise CurrentLiveRefused("REST_SOURCE_CLOCK_ORDER_INVALID")
    return QuantMeasurement(
        value,
        source_id,
        event_ms,
        raw.received_ms,
        raw.persisted_ms,
        raw.raw_sha256,
        scope or source_id.upper(),
        start,
        end,
        True,
    )


def _strict_json(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (TypeError, ValueError, json.JSONDecodeError, RecursionError):
        raise CurrentLiveRefused("MARKET_WS_JSON_INVALID") from None
    if type(parsed) is not dict:
        raise CurrentLiveRefused("MARKET_WS_ROOT_NOT_OBJECT")
    return parsed


def _integer(value: Any) -> int | None:
    if type(value) is int and value >= 0:
        return value
    if type(value) is str and value.isdecimal():
        return int(value)
    return None


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None
