"""Bounded, continuous native top-ten book capture.

This records the public WebSocket text and a globally ordered V2 frame tape.
The resulting consistency receipts are not source qualification, market
coverage, readiness, or trading authority.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import ssl
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from adaptive_replay.historical_context import canonical, digest
from adaptive_replay.native_book_capture import MAX_RAW_BYTES as NATIVE_MAX_RAW_BYTES
from adaptive_replay.native_book_capture import NativeBookCapture
from adaptive_replay.public_book_capture import ENDPOINT, MAX_GAP_MS, POLICY, SYMBOLS
from kairos_core.contracts.simulation import RecordedBookLevelV1, RecordedTopNBookFrameV2

DEFAULT_MAXIMUM_SECONDS = 900
DEFAULT_MAXIMUM_FRAMES = 60_000
DEFAULT_MAXIMUM_RAW_BYTES = 128 * 1024 * 1024
MAXIMUM_OUTPUT_BYTES = 500 * 1024 * 1024
DELIVERY_QUEUE_SIZE = 512
MAX_DRAIN_SECONDS = 15
SOURCE = "kairos-current-continuous-native"
SCHEMA = "kairos.current-continuous-native-tape.v1"


def _wall_ms() -> int:
    return time.time_ns() // 1_000_000


class ContinuousNativeTape:
    """Persist validated public-book text and continuous globally chained V2 frames."""

    def __init__(
        self,
        output: Path,
        tape_id: str,
        maximum_seconds: int = DEFAULT_MAXIMUM_SECONDS,
        maximum_frames: int = DEFAULT_MAXIMUM_FRAMES,
        maximum_raw_bytes: int = DEFAULT_MAXIMUM_RAW_BYTES,
        *,
        wall_clock: Callable[[], int] | None = None,
        monotonic_clock: Callable[[], int] | None = None,
    ) -> None:
        if type(tape_id) is not str or not tape_id or len(tape_id) > 128:
            raise ValueError("bounded tape_id required")
        if type(maximum_seconds) is not int or not 1 <= maximum_seconds <= DEFAULT_MAXIMUM_SECONDS:
            raise ValueError("maximum_seconds must be 1..900")
        if type(maximum_frames) is not int or not 1 <= maximum_frames <= DEFAULT_MAXIMUM_FRAMES:
            raise ValueError("maximum_frames must be 1..60000")
        if type(maximum_raw_bytes) is not int or not 1 <= maximum_raw_bytes <= DEFAULT_MAXIMUM_RAW_BYTES:
            raise ValueError("maximum_raw_bytes must be 1..128 MiB")
        self.output = Path(output)
        self.tape_id = tape_id
        self.maximum_seconds = maximum_seconds
        self.maximum_frames = maximum_frames
        self.maximum_raw_bytes = maximum_raw_bytes
        self._wall = wall_clock or _wall_ms
        self._mono = monotonic_clock or time.monotonic_ns
        self.epoch = str(uuid.uuid4())
        self._lock = threading.RLock()
        self._frames: list[RecordedTopNBookFrameV2] = []
        self._latest: dict[str, RecordedTopNBookFrameV2] = {}
        self._by_symbol: dict[str, list[RecordedTopNBookFrameV2]] = {symbol: [] for symbol in SYMBOLS}
        self._last_by_symbol: dict[str, tuple[int, int, int]] = {}
        self._counts = {symbol: 0 for symbol in SYMBOLS}
        self._first_received: dict[str, int] = {}
        self._maximum_gaps = {symbol: 0 for symbol in SYMBOLS}
        self._raw_bytes = 0
        self._admitted_raw_bytes = 0
        self._raw_hash = hashlib.sha256()
        self._delivery_bytes = 0
        self._delivery_count = 0
        self._text_delivery_count = 0
        self._text_delivery_bytes = 0
        self._control_delivery_count = 0
        self._control_body_bytes = 0
        self._delivery_hash = hashlib.sha256()
        self._delivered_first: dict[str, tuple[int, int]] = {}
        self._delivered_latest: dict[str, tuple[int, int]] = {}
        self._tape_hash = hashlib.sha256()
        self._output_bytes = 0
        self._started_ms: int | None = None
        self._started_ns: int | None = None
        self._last_received_ms: int | None = None
        self._last_received_ns: int | None = None
        self._last_delivery_ms: int | None = None
        self._last_delivery_ns: int | None = None
        self._last_persisted_ms: int | None = None
        self._poisoned = False
        self._closed = False
        self._failure: str | None = None
        self._transport: dict[str, Any] = {
            "endpoint": ENDPOINT,
            "attempts": 0,
            "retries": 0,
            "redirects": 0,
            "tls_default_validation": True,
            "trust_env": False,
            "proxy": None,
            "redirects_forbidden": True,
            "reconnects": 0,
            "handshake_completed": False,
        }
        # A fresh output claim prevents accidental append/re-rooting of old frames.
        self.output.mkdir(parents=False, exist_ok=False)
        self._plan = {
            "schema": SCHEMA,
            "tape_id": self.tape_id,
            "stream_epoch": self.epoch,
            "endpoint": ENDPOINT,
            "symbols": SYMBOLS,
            "native_policy": asdict(POLICY),
            "native_policy_sha256": POLICY.sha256,
            "maximum_seconds": self.maximum_seconds,
            "maximum_frames": self.maximum_frames,
            "maximum_raw_bytes": self.maximum_raw_bytes,
            "maximum_output_bytes": MAXIMUM_OUTPUT_BYTES,
            "delivery_queue_size": DELIVERY_QUEUE_SIZE,
            "transport_policy": {
                "tls_default_validation": True,
                "trust_env": False,
                "proxy": None,
                "redirects_forbidden": True,
                "reconnects": 0,
                "capture_start": "AFTER_VERIFIED_WEBSOCKET_HANDSHAKE",
            },
            "source_qualification": "NONE",
            "coverage_authority": "NONE",
            "risk_authority": "NONE",
        }
        self._plan_sha256 = digest(self._plan)
        self._plan_path = self.output / "plan.json"
        self._write_exclusive(
            self._plan_path, canonical({**self._plan, "plan_sha256": self._plan_sha256}) + "\n"
        )
        self._output_bytes = self._plan_path.stat().st_size
        self._raw = (self.output / "received.raw.jsonl").open("xb")
        self._delivery = (self.output / "transport-delivery.raw.jsonl").open("xb")
        self._tape = (self.output / "frames.jsonl").open("xb")

    @property
    def frames(self) -> tuple[RecordedTopNBookFrameV2, ...]:
        with self._lock:
            return tuple(self._frames)

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def failure(self) -> str | None:
        with self._lock:
            return self._failure

    @property
    def capture_started_ms(self) -> int | None:
        with self._lock:
            return self._started_ms

    def begin(self, connected_ms: int, connected_ns: int) -> None:
        with self._lock:
            if self._closed or self._started_ms is not None:
                raise ValueError("tape begin is single-use")
            if (
                type(connected_ms) is not int
                or connected_ms < 0
                or type(connected_ns) is not int
                or connected_ns < 0
            ):
                self._fail("INVALID_CONNECTION_CLOCK")
                raise ValueError(self._failure)
            self._started_ms, self._started_ns = connected_ms, connected_ns
            self._last_received_ms, self._last_received_ns = connected_ms, connected_ns
            self._last_delivery_ms, self._last_delivery_ns = connected_ms, connected_ns
            self._last_persisted_ms = connected_ms

    def note_transport(self, **fields: Any) -> None:
        with self._lock:
            allowed = {"attempts", "handshake_completed", "handshake_completed_ms"}
            if set(fields) - allowed:
                raise ValueError("unsupported transport receipt field")
            self._transport.update(fields)

    def record_delivery(
        self,
        body: str | bytes,
        received_ms: int,
        received_ns: int,
        *,
        message_type: str = "TEXT",
    ) -> None:
        """Fsync each delivered body before it can enter the bounded queue."""
        with self._lock:
            if self._closed or self._poisoned:
                raise ValueError("terminal or poisoned tape cannot retain delivery")
            if self._started_ms is None or self._started_ns is None:
                raise ValueError("verified handshake required before delivery")
            if type(message_type) is not str or type(received_ms) is not int or type(received_ns) is not int:
                raise ValueError("message type and integer delivery clocks required")
            if type(body) is str:
                original = body.encode("utf-8", errors="strict")
                content: dict[str, Any] = {"body": body, "body_encoding": "utf-8"}
            elif type(body) is bytes:
                original = body
                content = {"body_b64": base64.b64encode(body).decode("ascii"), "body_encoding": "base64"}
            else:
                original = canonical({"type": type(body).__name__, "value": repr(body)}).encode("utf-8")
                content = {"body": original.decode("utf-8"), "body_encoding": "canonical-metadata"}
            before_connection = received_ms < self._started_ms or received_ns < self._started_ns
            clock_regression = received_ms < self._last_delivery_ms or received_ns < self._last_delivery_ns
            elapsed_wall = received_ms - self._started_ms
            elapsed_mono = (received_ns - self._started_ns) // 1_000_000
            clock_disagreement = abs(elapsed_wall - elapsed_mono) > 1_000
            late_delivery = received_ns - self._started_ns > self.maximum_seconds * 1_000_000_000
            body_sha = hashlib.sha256(original).hexdigest()
            sequence = self._delivery_count + 1
            retained = self._delivery_bytes + len(original) <= self.maximum_raw_bytes
            record = {
                "delivery_sequence": sequence,
                "received_ms": received_ms,
                "received_monotonic_ns": received_ns,
                "message_type": message_type,
                "body_bytes": len(original),
                "body_sha256": body_sha,
                "body_retained": retained,
                **(content if retained else {}),
            }
            line = (canonical(record) + "\n").encode("utf-8")
            reserve = 128 * 1024
            if self._output_bytes + len(line) + reserve > MAXIMUM_OUTPUT_BYTES:
                retained = False
                record = {
                    "delivery_sequence": sequence,
                    "received_ms": received_ms,
                    "received_monotonic_ns": received_ns,
                    "message_type": message_type,
                    "body_bytes": len(original),
                    "body_sha256": body_sha,
                    "body_retained": False,
                    "failure": "OUTPUT_BOUND_REACHED",
                }
                line = (canonical(record) + "\n").encode("utf-8")
                if self._output_bytes + len(line) > MAXIMUM_OUTPUT_BYTES:
                    self._fail("OUTPUT_BOUND_REACHED")
                    raise ValueError("capture output byte bound reached before delivery receipt")
            self._write_fsync(self._delivery, line)
            self._delivery_hash.update(line)
            self._delivery_count += 1
            self._output_bytes += len(line)
            if retained:
                self._delivery_bytes += len(original)
                if message_type == "TEXT":
                    self._text_delivery_count += 1
                    self._text_delivery_bytes += len(original)
                else:
                    self._control_delivery_count += 1
                    self._control_body_bytes += len(original)
            else:
                self._fail(
                    "RESOURCE_BOUND_REACHED"
                    if self._delivery_bytes + len(original) > self.maximum_raw_bytes
                    else "OUTPUT_BOUND_REACHED"
                )
                raise ValueError("delivery body bound reached; body hash durably receipted")
            if before_connection or clock_regression or clock_disagreement:
                reason = (
                    "DELIVERY_BEFORE_CONNECTION"
                    if before_connection
                    else "RECEIVE_CLOCK_REGRESSION"
                    if clock_regression
                    else "CLOCK_DISAGREEMENT"
                )
                self._fail(reason)
                raise ValueError("delivery clocks failed validation after durable receipt")
            self._last_delivery_ms, self._last_delivery_ns = received_ms, received_ns
            if late_delivery:
                self._fail("CAPTURE_DEADLINE_EXCEEDED")
                raise ValueError("delivery received beyond capture deadline")
            if type(body) is str:
                try:
                    wire = json.loads(body)
                    symbol = wire.get("data", {}).get("s") if type(wire) is dict else None
                except (ValueError, TypeError, RecursionError):
                    symbol = None
                if symbol in SYMBOLS:
                    self._delivered_first.setdefault(symbol, (received_ms, received_ns))
                    self._delivered_latest[symbol] = (received_ms, received_ns)

    def check_liveness(self, now_ms: int, now_ns: int) -> None:
        with self._lock:
            if self._started_ms is None or self._started_ns is None or self._poisoned:
                if self._poisoned:
                    raise ValueError(self._failure or "capture failed")
                return
            if abs((now_ms - self._started_ms) - (now_ns - self._started_ns) // 1_000_000) > 1_000:
                self._fail("CLOCK_DISAGREEMENT")
                raise ValueError("UTC and monotonic elapsed clocks disagree")
            if now_ns - self._started_ns > self.maximum_seconds * 1_000_000_000:
                self._fail("CAPTURE_DEADLINE_EXCEEDED")
                raise ValueError("capture deadline reached")
            missing = set(SYMBOLS) - set(self._delivered_first)
            if missing and now_ns - self._started_ns > MAX_GAP_MS * 1_000_000:
                self._fail("INITIAL_SYMBOL_GAP")
                raise ValueError("initial symbol availability exceeded five seconds")
            if any(
                now_ns - received_ns > MAX_GAP_MS * 1_000_000
                for _, received_ns in self._delivered_latest.values()
            ):
                self._fail("SOURCE_GAP")
                raise ValueError("source delivery silence exceeds five seconds")

    def accept(self, text: str, received_ms: int, received_ns: int) -> RecordedTopNBookFrameV2:
        """Synchronously retain exact text, fsync it, then construct and persist its frame."""
        with self._lock:
            try:
                return self._accept_locked(text, received_ms, received_ns)
            except BaseException as exc:
                self._fail(self._sanitize(exc))
                raise

    def _accept_locked(self, text: str, received_ms: int, received_ns: int) -> RecordedTopNBookFrameV2:
        if self._closed or self._poisoned:
            raise ValueError("terminal or poisoned tape cannot accept messages")
        if self._started_ms is None or self._started_ns is None:
            raise ValueError("begin must follow the verified WebSocket handshake")
        if type(text) is not str or type(received_ms) is not int or type(received_ns) is not int:
            raise ValueError("exact text and integer receive clocks required")
        original = text.encode("utf-8", errors="strict")
        if not 0 < len(original) <= NATIVE_MAX_RAW_BYTES:
            raise ValueError("source message exceeds native payload bound")
        if (
            len(self._frames) >= self.maximum_frames
            or self._raw_bytes + len(original) > self.maximum_raw_bytes
        ):
            raise ValueError("capture resource bound reached")
        if received_ms < self._started_ms or received_ns < self._started_ns:
            raise ValueError("receive clock precedes verified connection")
        if received_ms < self._last_received_ms or received_ns < self._last_received_ns:
            raise ValueError("receive clock regression")
        if received_ns - self._started_ns > self.maximum_seconds * 1_000_000_000:
            raise ValueError("message received beyond capture deadline")
        elapsed_wall = received_ms - self._started_ms
        elapsed_mono = (received_ns - self._started_ns) // 1_000_000
        if abs(elapsed_wall - elapsed_mono) > 1_000:
            raise ValueError("UTC and monotonic elapsed clocks disagree")

        raw_sha = hashlib.sha256(original).hexdigest()
        raw_record = {
            "sequence": len(self._frames) + 1,
            "received_ms": received_ms,
            "received_monotonic_ns": received_ns,
            "raw_payload": text,
            "raw_payload_sha256": raw_sha,
        }
        raw_line = (canonical(raw_record) + "\n").encode("utf-8")
        # Reserve room for the corresponding complete frame record before
        # durably adding raw bytes; the latter duplicates text in V2.
        if self._output_bytes + len(raw_line) + 128 * 1024 > MAXIMUM_OUTPUT_BYTES:
            raise ValueError("capture output byte bound reached")
        self._write_fsync(self._raw, raw_line)
        self._raw_bytes += len(original)
        self._raw_hash.update(raw_line)
        self._output_bytes += len(raw_line)
        persisted_ms = self._wall()
        if persisted_ms < received_ms or persisted_ms < self._last_persisted_ms:
            raise ValueError("persistence clock regression")

        wire = json.loads(text)
        if type(wire) is not dict or type(wire.get("data")) is not dict:
            raise ValueError("combined native depth stream object required")
        body = wire["data"]
        symbol = body.get("s")
        if symbol not in SYMBOLS or type(symbol) is not str:
            raise ValueError("unexpected public-book symbol")
        event_ms = body.get("E")
        if type(event_ms) is not int or event_ms > received_ms:
            raise ValueError("invalid or future exchange event clock")
        if received_ms - event_ms > MAX_GAP_MS:
            raise ValueError("received exchange event is already stale")
        previous = self._last_by_symbol.get(symbol)
        if previous is None:
            if received_ms - self._started_ms > MAX_GAP_MS:
                raise ValueError("required symbol unavailable at capture start")
        else:
            old_update, old_event, old_received = previous
            if type(body.get("u")) is not int or body["u"] <= old_update or event_ms < old_event:
                raise ValueError("per-symbol exchange update or event clock regression")
            gap = max(event_ms - old_event, received_ms - old_received)
            if gap > MAX_GAP_MS:
                raise ValueError("observed per-symbol source gap exceeds five seconds")
            self._maximum_gaps[symbol] = max(self._maximum_gaps[symbol], gap)

        frame = RecordedTopNBookFrameV2(
            source=SOURCE,
            tape_id=self.tape_id,
            stream_epoch=self.epoch,
            symbol=symbol,
            tape_sequence=len(self._frames) + 1,
            exchange_update_id=body["u"],
            exchange_at_ms=event_ms,
            received_at_ms=received_ms,
            persisted_at_ms=persisted_ms,
            raw_payload=text,
            raw_payload_sha256=raw_sha,
            previous_frame_sha256=None if not self._frames else self._frames[-1].frame_sha256,
            continuity="ADMITTED",
            source_reason="CONTINUOUS_PUBLIC_TEXT_NOT_SOURCE_QUALIFICATION",
            bids=tuple(
                RecordedBookLevelV1(price=float(level[0]), quantity=float(level[1])) for level in body["b"]
            ),
            asks=tuple(
                RecordedBookLevelV1(price=float(level[0]), quantity=float(level[1])) for level in body["a"]
            ),
        )
        NativeBookCapture(frame, POLICY)
        tape_record = {
            "sequence": frame.tape_sequence,
            "received_ms": received_ms,
            "received_monotonic_ns": received_ns,
            "persisted_ms": persisted_ms,
            "raw_payload": text,
            "raw_payload_sha256": raw_sha,
            "frame": frame.model_dump(mode="json"),
            "frame_sha256": frame.frame_sha256,
        }
        tape_line = (canonical(tape_record) + "\n").encode("utf-8")
        if self._output_bytes + len(tape_line) + 128 * 1024 > MAXIMUM_OUTPUT_BYTES:
            raise ValueError("capture output byte bound reached")
        self._write_fsync(self._tape, tape_line)

        self._frames.append(frame)
        self._admitted_raw_bytes += len(original)
        self._latest[symbol] = frame
        self._by_symbol[symbol].append(frame)
        self._last_by_symbol[symbol] = (frame.exchange_update_id, event_ms, received_ms)
        self._counts[symbol] += 1
        self._first_received.setdefault(symbol, received_ms)
        self._tape_hash.update(tape_line)
        self._output_bytes += len(tape_line)
        self._last_received_ms, self._last_received_ns = received_ms, received_ns
        self._last_persisted_ms = persisted_ms
        return frame

    def latest(self, symbol: str, as_of_ms: int | None = None) -> RecordedTopNBookFrameV2 | None:
        with self._lock:
            as_of = self._wall() if as_of_ms is None else as_of_ms
            if type(as_of) is not int or as_of < 0:
                raise ValueError("as_of_ms must be a nonnegative integer")
            return next(
                (
                    frame
                    for frame in reversed(self._by_symbol.get(symbol, ()))
                    if frame.persisted_at_ms <= as_of
                ),
                None,
            )

    def snapshot(self, symbol: str) -> tuple[int, RecordedTopNBookFrameV2 | None]:
        """Return actual wall clock and its latest durable frame atomically."""
        with self._lock:
            if self._poisoned:
                raise ValueError(self._failure or "capture failed")
            now = self._wall()
            frame = next(
                (
                    candidate
                    for candidate in reversed(self._by_symbol.get(symbol, ()))
                    if candidate.persisted_at_ms <= now
                ),
                None,
            )
            return now, frame

    def finish(self) -> dict[str, Any]:
        with self._lock:
            if self._closed:
                raise ValueError("terminal tape is already closed")
            state = "CAPTURED"
            try:
                if self._poisoned:
                    raise ValueError(self._failure or "capture previously failed")
                if self._started_ms is None or self._started_ns is None:
                    raise ValueError("capture handshake was not completed")
                ended_ms, ended_ns = self._wall(), self._mono()
                elapsed_wall = ended_ms - self._started_ms
                elapsed_mono = (ended_ns - self._started_ns) // 1_000_000
                if elapsed_wall < 0 or elapsed_mono < 0 or abs(elapsed_wall - elapsed_mono) > 1_000:
                    raise ValueError("terminal wall and monotonic clocks disagree")
                if elapsed_mono > (self.maximum_seconds + MAX_DRAIN_SECONDS) * 1_000:
                    raise ValueError("capture shutdown exceeded bounded drain interval")
                if set(self._first_received) != set(SYMBOLS):
                    raise ValueError("not all five symbols were observed")
                if (
                    self._text_delivery_count != len(self._frames)
                    or self._text_delivery_bytes != self._admitted_raw_bytes
                ):
                    raise ValueError("unmatched retained text deliveries")
                if any(first - self._started_ms > MAX_GAP_MS for first in self._first_received.values()):
                    raise ValueError("initial symbol availability exceeded five seconds")
                if any(ended_ms - frame.received_at_ms > MAX_GAP_MS for frame in self._latest.values()):
                    raise ValueError("terminal symbol freshness exceeded five seconds")
                if max(self._maximum_gaps.values(), default=0) > MAX_GAP_MS:
                    raise ValueError("source gap exceeded five seconds")
            except BaseException as exc:
                state = "FAILED"
                if self._failure is None:
                    self._failure = self._sanitize(exc)
            self._close_files()
            try:
                raw_file_sha256 = self._file_sha256(self.output / "received.raw.jsonl")
                delivery_file_sha256 = self._file_sha256(self.output / "transport-delivery.raw.jsonl")
                frames_file_sha256 = self._file_sha256(self.output / "frames.jsonl")
                actual_output_bytes = sum(
                    (self.output / filename).stat().st_size
                    for filename in (
                        "plan.json",
                        "received.raw.jsonl",
                        "transport-delivery.raw.jsonl",
                        "frames.jsonl",
                    )
                )
            except OSError as exc:
                self._closed = True
                raise OSError("durable tape files could not be hashed") from exc
            if (
                raw_file_sha256 != self._raw_hash.hexdigest()
                or delivery_file_sha256 != self._delivery_hash.hexdigest()
                or frames_file_sha256 != self._tape_hash.hexdigest()
            ):
                state = "FAILED"
                self._failure = self._failure or "DURABLE_FILE_HASH_MISMATCH"
            self._output_bytes = actual_output_bytes
            receipt: dict[str, Any] = {
                "schema": SCHEMA,
                "tape_id": self.tape_id,
                "stream_epoch": self.epoch,
                "plan_sha256": self._plan_sha256,
                "native_policy_sha256": POLICY.sha256,
                "state": state,
                "failure": self._failure,
                "connected_ms": self._started_ms,
                "ended_ms": self._wall(),
                "frame_count": len(self._frames),
                "raw_payload_bytes": self._raw_bytes,
                "admitted_raw_payload_bytes": self._admitted_raw_bytes,
                "delivered_body_bytes": self._delivery_bytes,
                "delivery_count": self._delivery_count,
                "text_delivery_count": self._text_delivery_count,
                "text_delivery_bytes": self._text_delivery_bytes,
                "control_delivery_count": self._control_delivery_count,
                "control_body_bytes": self._control_body_bytes,
                "output_bytes": self._output_bytes,
                "raw_jsonl_sha256": raw_file_sha256,
                "transport_delivery_jsonl_sha256": delivery_file_sha256,
                "frames_jsonl_sha256": frames_file_sha256,
                "symbol_counts": self._counts,
                "maximum_gap_ms": self._maximum_gaps,
                "transport": self._transport,
                "source_qualification": "NONE",
                "coverage_authority": "NONE",
                "risk_authority": "NONE",
            }
            receipt["receipt_sha256"] = digest(receipt)
            try:
                receipt_text = canonical(receipt) + "\n"
                receipt_bytes = receipt_text.encode("utf-8")
                if self._output_bytes + len(receipt_bytes) > MAXIMUM_OUTPUT_BYTES:
                    raise ValueError("capture output byte bound reached")
                self._write_exclusive(self.output / "receipt.json", receipt_text)
            except BaseException as exc:
                self._close_files()
                self._closed = True
                raise OSError("terminal tape receipt could not be durably written") from exc
            self._closed = True
            return receipt

    @staticmethod
    def _write_exclusive(path: Path, text: str) -> None:
        payload = text.encode("utf-8")
        with path.open("xb") as handle:
            if handle.write(payload) != len(payload):
                raise OSError("incomplete exclusive file write")
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _file_sha256(path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def _write_fsync(file, payload: bytes) -> None:
        if file.write(payload) != len(payload):
            raise OSError("incomplete durable tape write")
        file.flush()
        os.fsync(file.fileno())

    def _close_files(self) -> None:
        for handle in (self._raw, self._delivery, self._tape):
            try:
                if not handle.closed:
                    handle.close()
            except OSError:
                pass

    def _fail(self, reason: str) -> None:
        if not self._poisoned:
            self._poisoned = True
            self._failure = reason

    @staticmethod
    def _sanitize(exc: BaseException) -> str:
        value = str(exc)
        allowed = {
            "receive clock regression": "RECEIVE_CLOCK_REGRESSION",
            "persistence clock regression": "PERSISTENCE_CLOCK_REGRESSION",
            "UTC and monotonic elapsed clocks disagree": "CLOCK_DISAGREEMENT",
            "invalid or future exchange event clock": "FUTURE_OR_INVALID_EVENT_CLOCK",
            "received exchange event is already stale": "STALE_EXCHANGE_EVENT",
            "required symbol unavailable at capture start": "INITIAL_SYMBOL_GAP",
            "observed per-symbol source gap exceeds five seconds": "SOURCE_GAP",
            "capture resource bound reached": "RESOURCE_BOUND_REACHED",
            "capture output byte bound reached": "OUTPUT_BOUND_REACHED",
            "message received beyond capture deadline": "CAPTURE_DEADLINE_EXCEEDED",
            "per-symbol exchange update or event clock regression": "SYMBOL_UPDATE_REGRESSION",
            "terminal symbol freshness exceeded five seconds": "TERMINAL_SYMBOL_STALE",
            "capture handshake was not completed": "NO_CAPTURE_HANDSHAKE",
            "not all five symbols were observed": "INCOMPLETE_SYMBOL_SET",
            "initial symbol availability exceeded five seconds": "INITIAL_SYMBOL_GAP",
            "terminal wall and monotonic clocks disagree": "TERMINAL_CLOCK_DISAGREEMENT",
            "capture exceeded maximum duration": "CAPTURE_DEADLINE_EXCEEDED",
            "unmatched retained text deliveries": "UNMATCHED_TEXT_DELIVERIES",
        }
        return allowed.get(value, type(exc).__name__.upper())[:96]


async def run_capture(
    tape: ContinuousNativeTape,
    ready: asyncio.Event,
    stop: asyncio.Event,
) -> dict[str, Any]:
    """Capture one verified public WebSocket session; reconnects are forbidden."""
    import aiohttp

    async def reject_redirect(*_args: Any) -> None:
        raise ValueError("redirect forbidden")

    trace = aiohttp.TraceConfig()
    trace.on_request_redirect.append(reject_redirect)
    ssl_context = ssl.create_default_context()
    if not ssl_context.check_hostname or ssl_context.verify_mode != ssl.CERT_REQUIRED:
        tape._fail("DEFAULT_TLS_VALIDATION_UNAVAILABLE")
        return tape.finish()
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=10)
    consumer: asyncio.Task | None = None
    queue: asyncio.Queue = asyncio.Queue(maxsize=DELIVERY_QUEUE_SIZE)
    failure: str | None = None

    async def drain_and_stop(active_consumer: asyncio.Task) -> None:
        if active_consumer.done():
            active_consumer.result()
            return
        drained = asyncio.create_task(queue.join())
        done, _ = await asyncio.wait((drained, active_consumer), return_when=asyncio.FIRST_COMPLETED)
        if active_consumer in done:
            drained.cancel()
            await asyncio.gather(drained, return_exceptions=True)
            active_consumer.result()
            return
        await drained
        if active_consumer.done():
            active_consumer.result()
            return
        queue.put_nowait(None)
        await active_consumer

    try:
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False, trace_configs=[trace]) as session:
            tape.note_transport(attempts=1)
            async with session.ws_connect(
                ENDPOINT,
                ssl=ssl_context,
                proxy=None,
                autoping=True,
                heartbeat=None,
                max_msg_size=NATIVE_MAX_RAW_BYTES,
            ) as socket:
                if str(socket._response.url) != ENDPOINT:
                    raise ValueError("unexpected public capture response URL")
                tape.begin(tape._wall(), tape._mono())
                tape.note_transport(
                    handshake_completed=True,
                    handshake_completed_ms=tape.capture_started_ms,
                )
                deadline = asyncio.get_running_loop().time() + tape.maximum_seconds

                async def consume() -> None:
                    while True:
                        item = await queue.get()
                        try:
                            if item is None:
                                return
                            text, received_ms, received_ns = item
                            job = asyncio.create_task(
                                asyncio.to_thread(tape.accept, text, received_ms, received_ns)
                            )
                            try:
                                await asyncio.shield(job)
                            except asyncio.CancelledError:
                                await job
                                raise
                            if set(tape._first_received) == set(SYMBOLS) and not ready.is_set():
                                ready.set()
                        finally:
                            queue.task_done()

                consumer = asyncio.create_task(consume(), name="kairos-continuous-native-writer")
                while not stop.is_set() and asyncio.get_running_loop().time() < deadline:
                    if consumer.done():
                        consumer.result()
                        raise ValueError("ordered writer ended unexpectedly")
                    tape.check_liveness(tape._wall(), tape._mono())
                    remaining = deadline - asyncio.get_running_loop().time()
                    try:
                        message = await asyncio.wait_for(socket.receive(), min(0.25, max(0.001, remaining)))
                    except TimeoutError:
                        tape.check_liveness(tape._wall(), tape._mono())
                        continue
                    received_ms, received_ns = tape._wall(), tape._mono()
                    message_type = getattr(message.type, "name", str(message.type))
                    tape.record_delivery(message.data, received_ms, received_ns, message_type=message_type)
                    if message.type in {aiohttp.WSMsgType.PING, aiohttp.WSMsgType.PONG}:
                        continue
                    if message.type is not aiohttp.WSMsgType.TEXT:
                        raise ValueError("public stream closed or returned non-text")
                    try:
                        queue.put_nowait((message.data, received_ms, received_ns))
                    except asyncio.QueueFull:
                        tape._fail("DELIVERY_QUEUE_OVERFLOW")
                        raise ValueError("public delivery queue bound reached") from None
                await drain_and_stop(consumer)
    except asyncio.CancelledError:
        failure = "CANCELLED"
        tape._fail(failure)
        if consumer is not None:
            if not consumer.done():
                consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)
        tape.finish()
        raise
    except BaseException as exc:
        failure = tape.failure or tape._sanitize(exc)
        tape._fail(failure)
        if consumer is not None:
            if not consumer.done():
                try:
                    await drain_and_stop(consumer)
                except BaseException:
                    pass
            # Always retrieve the terminal task result, including the race
            # where a worker fails while receive() is itself unwinding.
            try:
                await consumer
            except BaseException:
                pass
    if failure is not None:
        tape._fail(failure)
    return tape.finish()
