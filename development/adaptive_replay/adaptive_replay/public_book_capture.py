"""Opt-in, bounded public-book capture; no account, provider or trading access.

Each received text is durably retained BEFORE validation/normalization. Closed
segments reuse the unchanged V2 binder and book bundle. A single connection is
never retried/resumed; failures preserve raw bytes and explicit terminal state.
Transport observation is not an exchange signature or historical clock proof.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import ssl
import stat
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from kairos_core.contracts.simulation import RecordedBookLevelV1, RecordedTopNBookFrameV2

from .book_bundle import (
    BookBundleSeal,
    RetentionReceipt,
    open_book_bundle,
    prepare_book_bundle,
    retain_book_bundle,
)
from .historical_context import _clock, _json, _sha, canonical, digest
from .inputs import UNIVERSE
from .native_book_capture import MAX_RAW_BYTES, MIGRATED_PROFILE, NativeBookCapture, NativeBookPolicy

SCHEMA = "kairos.development.public-book-capture.v1"
SYMBOLS = tuple(sorted(UNIVERSE))
ENDPOINT = "wss://fstream.binance.com/public/stream?streams=" + "/".join(
    f"{symbol.lower()}@depth10@100ms" for symbol in SYMBOLS
)
SEGMENT_FRAMES = 256
MAX_FRAMES = 6_000
MAX_RAW_TOTAL = 16 * 1024 * 1024
MAX_SECONDS = 120
MAX_GAP_MS = 5_000
POLICY = NativeBookPolicy(
    MIGRATED_PROFILE, "binance-um-public-depth10-100ms", MAX_GAP_MS, "CALLER_ATTESTED_POINT_IN_TIME"
)
LIMITATIONS = (
    "FORWARD_LOCAL_OBSERVATION_NOT_HISTORICAL_AVAILABILITY",
    "SAMPLED_TOP_TEN_NOT_EVERY_MARKET_TICK_OR_FULL_DEPTH",
    "LOCAL_UTC_NOT_INDEPENDENT_CLOCK_ATTESTATION",
    "TLS_TRANSPORT_NOT_EXCHANGE_SIGNED_SOURCE",
    "NO_NEWS_MACRO_BAR_SOURCE_SET_OR_EXECUTION_ADMISSION",
    "NO_RISK_TRADING_OR_READINESS_AUTHORITY",
    "BOUNDED_APPLICATION_TEXT_DELIVERY_NOT_ALL_WIRE_FRAMES",
)


class ExchangeClockAhead(ValueError):
    """Preserved vendor event is later than actual local delivery; no clock repair."""


def wall_ms() -> int:
    return time.time_ns() // 1_000_000


def _transport_observed(value: dict[str, Any]) -> bool:
    return (
        type(value) is dict
        and set(value)
        == {"endpoint", "attempts", "retries", "redirects", "tls_default_validation", "handshake_completed"}
        and value["endpoint"] == ENDPOINT
        and all(type(value[name]) is int for name in ("attempts", "retries", "redirects"))
        and (value["attempts"], value["retries"], value["redirects"]) == (1, 0, 0)
        and value["tls_default_validation"] is True
        and value["handshake_completed"] is True
    )


def _safe_existing(path: Path, *, directory: bool) -> Path:
    path = Path(path).absolute()
    for entry in (*reversed(path.parents), path):
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("capture paths cannot traverse symlinks or reparse points")
        want_directory = directory if entry == path else True
        if want_directory and not stat.S_ISDIR(info.st_mode):
            raise ValueError("existing capture parent directory required")
        if not want_directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ValueError("unaliased regular capture file required")
    return path


def _exclusive_json(path: Path, value: Any) -> str:
    raw = canonical(value).encode("utf-8")
    with path.open("xb") as stream:
        if stream.write(raw) != len(raw):
            raise OSError("incomplete capture evidence write")
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


class CaptureOwner:
    """OS-owned exclusion across output directories; stale metadata is not ownership.

    The lock file survives. A process crash releases the kernel lock, not any
    prior failed capture. A subsequent NEW capture can acquire the lock but
    cannot reopen, repair or resume the failed output.
    """

    def __init__(self, runtime: Path):
        self.runtime = _safe_existing(runtime, directory=True)
        self.stream = None

    def __enter__(self):
        path = self.runtime / ".public-book-capture.owner.lock"
        if path.exists():
            _safe_existing(path, directory=False)
        self.stream = path.open("a+b")
        try:
            _safe_existing(path, directory=False)
            if os.fstat(self.stream.fileno()).st_size == 0:
                self.stream.write(b"0")
                self.stream.flush()
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.stream.close()
            self.stream = None
            raise
        return self

    def __exit__(self, *_):
        assert self.stream is not None
        try:
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        finally:
            self.stream.close()
            self.stream = None


class PublicBookRecorder:
    """Single new output, one epoch, complete observed-message denominator.

    No in-memory dropping/sampling, reconnect, update sorting, clock clamping,
    old V1 adoption, or deletion on error. Bundles are separate bounded prefixes;
    the manifest binds their exact order and the global raw-record hash chain.
    """

    def __init__(
        self,
        output: Path,
        *,
        seconds: int,
        clock: Callable[[], int] = wall_ms,
        monotonic: Callable[[], int] = time.monotonic_ns,
    ):
        if type(seconds) is not int or not 1 <= seconds <= MAX_SECONDS:
            raise ValueError("capture duration must be 1..120 seconds")
        output = Path(output).absolute()
        runtime = _safe_existing(output.parent, directory=True)
        if re.fullmatch(r"public-book-capture-[0-9]{8}-[a-z0-9-]{1,48}", output.name) is None:
            raise ValueError("new direct public-book-capture-YYYYMMDD-suffix output required")
        # No exist_ok: neither previous captures nor partial outputs can be adopted.
        output.mkdir()
        self.output = _safe_existing(output, directory=True)
        self.runtime = runtime
        self.clock, self.monotonic = clock, monotonic
        self.started_ms = clock()
        self.started_ns = monotonic()
        _clock(self.started_ms)
        _clock(self.started_ns)
        self.seconds = seconds
        self.capture_id = str(uuid.uuid4())
        self.epoch = str(uuid.uuid4())
        self.source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.plan_sha256 = _exclusive_json(
            self.output / "plan.json",
            {
                "schema": SCHEMA,
                "capture_id": self.capture_id,
                "epoch": self.epoch,
                "endpoint": ENDPOINT,
                "symbols": SYMBOLS,
                "policy": asdict(POLICY),
                "seconds": seconds,
                "maximum_frames": MAX_FRAMES,
                "maximum_raw_bytes": MAX_RAW_TOTAL,
                "segment_frames": SEGMENT_FRAMES,
                "maximum_gap_ms": MAX_GAP_MS,
                "started_ms": self.started_ms,
                "started_monotonic_ns": self.started_ns,
                "source_sha256": self.source_sha256,
                "limitations": LIMITATIONS,
            },
        )
        self.raw = (self.output / "received.raw.jsonl").open("xb")
        self.raw_hash = hashlib.sha256()
        self.raw_bytes = 0
        self.raw_head = None
        self.admitted_raw_head = None
        self.observed = 0
        self.admitted = 0
        self.frames: list[RecordedTopNBookFrameV2] = []
        self.segments: list[dict[str, Any]] = []
        self.last_by_symbol: dict[str, tuple[int, int, int]] = {}
        self.counts = {symbol: 0 for symbol in SYMBOLS}
        self.maximum_gaps = {symbol: 0 for symbol in SYMBOLS}
        self.first_received = {symbol: None for symbol in SYMBOLS}
        self.last_received = self.started_ms
        self.last_persisted = self.started_ms
        self.last_monotonic = self.started_ns
        self.closed = False
        self.failed = False

    def accept(self, text: str, *, received_ms: int, received_ns: int) -> RecordedTopNBookFrameV2:
        if self.closed or self.failed:
            raise ValueError("terminal capture cannot accept another message")
        try:
            return self._accept(text, received_ms=received_ms, received_ns=received_ns)
        except BaseException:
            self.failed = True
            raise

    def _accept(self, text: str, *, received_ms: int, received_ns: int) -> RecordedTopNBookFrameV2:
        _clock(received_ms)
        _clock(received_ns)
        if type(text) is not str:
            raise ValueError("original WebSocket text required")
        original = text.encode("utf-8", errors="strict")
        if not 0 < len(original) <= MAX_RAW_BYTES:
            raise ValueError("original text exceeds native byte bound")
        if self.observed >= MAX_FRAMES or self.raw_bytes + len(original) > MAX_RAW_TOTAL:
            raise ValueError("capture resource bound reached; never drop a message")
        record = {
            "sequence": self.observed + 1,
            "previous_record_sha256": self.raw_head,
            "received_ms": received_ms,
            "received_monotonic_ns": received_ns,
            "raw_payload": text,
            "raw_payload_sha256": hashlib.sha256(original).hexdigest(),
        }
        record_sha = digest(record)
        line = (canonical({**record, "record_sha256": record_sha}) + "\n").encode("utf-8")
        if self.raw.write(line) != len(line):
            raise OSError("incomplete original message write")
        self.raw.flush()
        os.fsync(self.raw.fileno())
        persisted_ms = self.clock()  # The original bytes have actually been fsynced now.
        self.raw_hash.update(line)
        self.raw_bytes += len(original)
        self.raw_head = record_sha
        self.observed += 1
        if received_ms < self.last_received or received_ns < self.last_monotonic:
            raise ValueError("local receive clock regression")
        if received_ns - self.started_ns > self.seconds * 1_000_000_000:
            raise ValueError("message received beyond sealed capture duration")
        if persisted_ms < received_ms or persisted_ms < self.last_persisted:
            raise ValueError("persistence clock regression")
        # Do not silently map backward/forward wall-clock steps into causal evidence.
        elapsed_wall = received_ms - self.started_ms
        elapsed_mono = (received_ns - self.started_ns) // 1_000_000
        if abs(elapsed_wall - elapsed_mono) > 1_000:
            raise ValueError("UTC and monotonic elapsed clocks disagree")
        wire = _json(text)
        if type(wire) is not dict or type(wire.get("data")) is not dict:
            raise ValueError("native combined-stream object required")
        body = wire["data"]
        # ALL remaining fields and raw/native equality are rechecked by the native binder.
        symbol = body.get("s")
        if type(symbol) is not str or symbol not in SYMBOLS:
            raise ValueError("unexpected public-book symbol")
        if type(body.get("E")) is int and body["E"] > received_ms:
            raise ExchangeClockAhead("exchange event is ahead of local delivery clock")
        try:
            frame = RecordedTopNBookFrameV2(
                source="kairos-research-public-book-capture",
                tape_id=f"{self.capture_id}:{len(self.segments) + 1:04d}",
                stream_epoch=self.epoch,
                symbol=symbol,
                tape_sequence=len(self.frames) + 1,
                exchange_update_id=body["u"],
                exchange_at_ms=body["E"],
                received_at_ms=received_ms,
                persisted_at_ms=persisted_ms,
                raw_payload=text,
                raw_payload_sha256=record["raw_payload_sha256"],
                previous_frame_sha256=None if not self.frames else self.frames[-1].frame_sha256,
                continuity="ADMITTED",
                source_reason="OBSERVED_PUBLIC_TLS_TEXT_NOT_SOURCE_QUALIFICATION",
                bids=tuple(RecordedBookLevelV1(price=float(p), quantity=float(q)) for p, q in body["b"]),
                asks=tuple(RecordedBookLevelV1(price=float(p), quantity=float(q)) for p, q in body["a"]),
            )
            NativeBookCapture(frame, POLICY)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("native public message failed exact V2 validation") from exc
        previous = self.last_by_symbol.get(symbol)
        if received_ms - frame.exchange_at_ms > MAX_GAP_MS:
            raise ValueError("received exchange event is already stale")
        if previous is not None:
            update, event, received = previous
            if frame.exchange_update_id <= update or frame.exchange_at_ms < event:
                raise ValueError("per-symbol update or exchange clock regression")
            gap = max(frame.exchange_at_ms - event, received_ms - received)
            self.maximum_gaps[symbol] = max(self.maximum_gaps[symbol], gap)
            if gap > MAX_GAP_MS:
                raise ValueError("observed per-symbol gap exceeds source freshness bound")
        elif received_ms - self.started_ms > MAX_GAP_MS:
            raise ValueError("required symbol unavailable at capture start")
        self.last_by_symbol[symbol] = (frame.exchange_update_id, frame.exchange_at_ms, received_ms)
        if self.first_received[symbol] is None:
            self.first_received[symbol] = received_ms
        self.counts[symbol] += 1
        self.last_received, self.last_monotonic = received_ms, received_ns
        self.last_persisted = persisted_ms
        self.admitted_raw_head = record_sha
        self.frames.append(frame)
        self.admitted += 1
        if len(self.frames) == SEGMENT_FRAMES:
            self._flush_segment()
        return frame

    def _flush_segment(self) -> None:
        if not self.frames:
            return
        frames = tuple(self.frames)
        ordinal = len(self.segments) + 1
        name = f"segment-{ordinal:04d}.native-book.research.json"
        seal = prepare_book_bundle(f"{self.capture_id}:{ordinal:04d}", frames, POLICY)
        retention = retain_book_bundle(self.output / name, seal, frames)
        open_book_bundle(self.output / name, seal, retention)
        value = {
            "ordinal": ordinal,
            "name": name,
            "global_first": self.admitted - len(frames) + 1,
            "global_last": self.admitted,
            "previous_segment_sha256": None if not self.segments else digest(self.segments[-1]),
            "raw_prefix_head_sha256": self.admitted_raw_head,
            "observed_prefix_head_at_flush_sha256": self.raw_head,
            "seal": asdict(seal),
            "retention": asdict(retention),
        }
        _exclusive_json(self.output / f"segment-{ordinal:04d}.receipt.json", value)
        self.segments.append(value)
        self.frames.clear()

    def finish(self, *, state: str, reason: str, transport: dict[str, Any]) -> dict[str, Any]:
        if self.closed:
            raise ValueError("capture already terminal; no rewritten receipt")
        if state not in {"CAPTURED", "FAILED"}:
            raise ValueError("explicit terminal capture state required")
        self.closed = True
        try:
            self._flush_segment()
        except Exception as exc:
            state, reason = "FAILED", f"SEGMENT_RETENTION_{type(exc).__name__}"
            self.failed = True
        finally:
            self.raw.close()
        ended_ms = self.clock()
        ended_ns = self.monotonic()
        boundary_gaps = {
            symbol: None if symbol not in self.last_by_symbol else ended_ms - self.last_by_symbol[symbol][2]
            for symbol in SYMBOLS
        }
        complete_observation = (
            state == "CAPTURED"
            and not self.failed
            and _transport_observed(transport)
            and self.observed == self.admitted
            and all(self.counts.values())
            and all(gap is not None and 0 <= gap <= MAX_GAP_MS for gap in boundary_gaps.values())
            and self.seconds * 1_000_000_000
            <= ended_ns - self.started_ns
            <= (self.seconds + 15) * 1_000_000_000
            and ended_ms >= self.last_persisted
            and abs((ended_ms - self.started_ms) - (ended_ns - self.started_ns) // 1_000_000) <= 1_000
        )
        if state == "CAPTURED" and not complete_observation:
            state, reason = "FAILED", "OBSERVED_COVERAGE_OR_CLOCK_BOUNDARY_CONFLICT"
        result = {
            "schema": SCHEMA,
            "capture_id": self.capture_id,
            "epoch": self.epoch,
            "plan_sha256": self.plan_sha256,
            "source_sha256": self.source_sha256,
            "state": state,
            "reason": reason,
            "started_ms": self.started_ms,
            "ended_ms": ended_ms,
            "elapsed_monotonic_ms": (ended_ns - self.started_ns) // 1_000_000,
            "observed_messages": self.observed,
            "admitted_frames": self.admitted,
            "raw_payload_bytes": self.raw_bytes,
            "raw_file_sha256": self.raw_hash.hexdigest(),
            "raw_head_sha256": self.raw_head,
            "symbol_counts": self.counts,
            "first_received_ms": self.first_received,
            "maximum_observed_gap_ms": self.maximum_gaps,
            "terminal_gap_ms": boundary_gaps,
            "segments": self.segments,
            "transport": transport,
            "observed_stream_check": "PASS" if complete_observation else "FAIL",
            "market_tick_completeness": "UNKNOWN_NOT_CLAIMED",
            "source_set_admitted": False,
            "risk_authority": "NONE",
            "limitations": LIMITATIONS,
        }
        _exclusive_json(self.output / "receipt.json", result)
        return result


def audit_public_capture(output: Path, *, expected_receipt_sha256: str) -> dict[str, Any]:
    """Full read-only audit under an independently held terminal-byte commitment.

    Reconcile every raw received message with every native segment, including
    clocks/order across local segment roots. Never infer a receipt from the
    bundle itself, rewrite files, reclassify failed attempts, or grant admission.
    """
    _sha(expected_receipt_sha256)
    output = _safe_existing(output, directory=True)

    def read_json(name: str, maximum: int = 1024 * 1024) -> tuple[dict[str, Any], str]:
        path = _safe_existing(output / name, directory=False)
        if path.stat().st_size > maximum:
            raise ValueError("capture evidence file exceeds byte bound")
        raw = path.read_bytes()
        value = _json(raw)
        if type(value) is not dict or canonical(value).encode("utf-8") != raw:
            raise ValueError("canonical capture evidence object required")
        return value, hashlib.sha256(raw).hexdigest()

    receipt, receipt_sha = read_json("receipt.json")
    if receipt_sha != expected_receipt_sha256:
        raise ValueError("capture terminal bytes differ from independent expected hash")
    plan, plan_sha = read_json("plan.json")
    source_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if (
        receipt.get("schema") != SCHEMA
        or plan.get("schema") != SCHEMA
        or receipt.get("plan_sha256") != plan_sha
        or receipt.get("source_sha256") != source_sha
        or plan.get("source_sha256") != source_sha
        or plan.get("capture_id") != receipt.get("capture_id")
        or plan.get("epoch") != receipt.get("epoch")
        or plan.get("endpoint") != ENDPOINT
        or plan.get("symbols") != list(SYMBOLS)
        or plan.get("policy") != asdict(POLICY)
        or plan.get("maximum_frames") != MAX_FRAMES
        or plan.get("maximum_raw_bytes") != MAX_RAW_TOTAL
        or plan.get("segment_frames") != SEGMENT_FRAMES
        or plan.get("maximum_gap_ms") != MAX_GAP_MS
        or receipt.get("risk_authority") != "NONE"
        or receipt.get("source_set_admitted") is not False
        or receipt.get("market_tick_completeness") != "UNKNOWN_NOT_CLAIMED"
        or not _transport_observed(receipt.get("transport"))
        or receipt.get("limitations") != list(LIMITATIONS)
        or plan.get("limitations") != list(LIMITATIONS)
    ):
        raise ValueError("capture source, plan or authority commitment conflict")
    if type(plan.get("seconds")) is not int or not 1 <= plan["seconds"] <= MAX_SECONDS:
        raise ValueError("sealed capture duration bound conflict")
    if receipt.get("state") != "CAPTURED" or receipt.get("observed_stream_check") != "PASS":
        raise ValueError("failed/partial capture is preserved, never admitted by audit")
    for name in ("started_ms", "ended_ms", "elapsed_monotonic_ms", "observed_messages", "admitted_frames"):
        _clock(receipt.get(name))
    elapsed = receipt["elapsed_monotonic_ms"]
    if (
        plan["started_ms"] != receipt["started_ms"]
        or not plan["seconds"] * 1_000 <= elapsed <= (plan["seconds"] + 15) * 1_000
        or abs(receipt["ended_ms"] - receipt["started_ms"] - elapsed) > 1_000
        or not 1 <= receipt["observed_messages"] == receipt["admitted_frames"] <= MAX_FRAMES
    ):
        raise ValueError("capture terminal duration/count/clock conflict")
    segments = receipt.get("segments")
    if (
        type(segments) is not list
        or not 1 <= len(segments) <= (MAX_FRAMES + SEGMENT_FRAMES - 1) // SEGMENT_FRAMES
    ):
        raise ValueError("bounded complete segment manifest required")
    frames = []
    raw_heads = {}
    previous_segment = None
    for ordinal, segment in enumerate(segments, start=1):
        if type(segment) is not dict:
            raise ValueError("exact segment record required")
        name = f"segment-{ordinal:04d}.native-book.research.json"
        separate, _ = read_json(f"segment-{ordinal:04d}.receipt.json")
        seal_data = dict(segment["seal"])
        seal_data["policy"] = NativeBookPolicy(**seal_data["policy"])
        seal = BookBundleSeal(**seal_data)
        retention = RetentionReceipt(**segment["retention"])
        if (
            segment != separate
            or segment["ordinal"] != ordinal
            or segment["name"] != name
            or segment["global_first"] != len(frames) + 1
            or segment["global_last"] != len(frames) + seal.frame_count
            or segment["previous_segment_sha256"] != previous_segment
            or segment["observed_prefix_head_at_flush_sha256"] != segment["raw_prefix_head_sha256"]
            or seal.bundle_id != f"{receipt['capture_id']}:{ordinal:04d}"
            or seal.tape_id != seal.bundle_id
            or seal.stream_epoch != receipt["epoch"]
            or seal.policy != POLICY
            or seal.frame_count > SEGMENT_FRAMES
            or (ordinal != len(segments) and seal.frame_count != SEGMENT_FRAMES)
        ):
            raise ValueError("global capture segment chain/count/epoch conflict")
        retained = open_book_bundle(output / name, seal, retention)
        frames.extend(binding.frame for binding in retained.bindings)
        raw_heads[len(frames)] = segment["raw_prefix_head_sha256"]
        previous_segment = digest(segment)
    if len(frames) != receipt["admitted_frames"]:
        raise ValueError("native segment denominator differs from all admitted frames")
    raw_path = _safe_existing(output / "received.raw.jsonl", directory=False)
    if raw_path.stat().st_size > MAX_RAW_TOTAL * 3:
        raise ValueError("capture raw file exceeds complete-record bound")
    hasher = hashlib.sha256()
    head = None
    payload_bytes = 0
    counts = {symbol: 0 for symbol in SYMBOLS}
    first = {symbol: None for symbol in SYMBOLS}
    gaps = {symbol: 0 for symbol in SYMBOLS}
    last = {}
    previous_received = receipt["started_ms"]
    previous_persisted = receipt["started_ms"]
    previous_mono = None
    count = 0
    with raw_path.open("rb") as stream:
        for frame in frames:
            line = stream.readline(MAX_RAW_BYTES * 3 + 4096)
            count += 1
            row = _json(line)
            if type(row) is not dict or (canonical(row) + "\n").encode("utf-8") != line:
                raise ValueError("canonical complete original received record required")
            fields = dict(row)
            recorded_sha = fields.pop("record_sha256")
            _clock(row["received_ms"])
            _clock(row["received_monotonic_ns"])
            elapsed_mono = (row["received_monotonic_ns"] - plan["started_monotonic_ns"]) // 1_000_000
            if (
                row["sequence"] != count
                or row["previous_record_sha256"] != head
                or digest(fields) != recorded_sha
                or row["raw_payload"] != frame.raw_payload
                or row["raw_payload_sha256"] != frame.raw_payload_sha256
                or row["received_ms"] != frame.received_at_ms
                or row["received_ms"] < previous_received
                or frame.persisted_at_ms < previous_persisted
                or not 0 <= elapsed_mono <= plan["seconds"] * 1_000
                or abs((row["received_ms"] - receipt["started_ms"]) - elapsed_mono) > 1_000
                or (previous_mono is not None and row["received_monotonic_ns"] < previous_mono)
            ):
                raise ValueError("original/global native source chain or clock conflict")
            if count in raw_heads and raw_heads[count] != recorded_sha:
                raise ValueError("segment ends at a different original raw-prefix head")
            raw = row["raw_payload"].encode("utf-8", errors="strict")
            if (
                not 0 < len(raw) <= MAX_RAW_BYTES
                or hashlib.sha256(raw).hexdigest() != row["raw_payload_sha256"]
            ):
                raise ValueError("original payload-byte identity conflict")
            payload_bytes += len(raw)
            if payload_bytes > MAX_RAW_TOTAL or frame.received_at_ms - frame.exchange_at_ms > MAX_GAP_MS:
                raise ValueError("raw source byte/freshness bound conflict")
            symbol = frame.symbol
            if symbol in last:
                update, event, received = last[symbol]
                gap = max(frame.exchange_at_ms - event, frame.received_at_ms - received)
                if frame.exchange_update_id <= update or frame.exchange_at_ms < event or gap > MAX_GAP_MS:
                    raise ValueError("per-symbol source continuity conflict across segment roots")
                gaps[symbol] = max(gaps[symbol], gap)
            else:
                first[symbol] = frame.received_at_ms
                if first[symbol] - receipt["started_ms"] > MAX_GAP_MS:
                    raise ValueError("required symbol missing from capture start")
            last[symbol] = (frame.exchange_update_id, frame.exchange_at_ms, frame.received_at_ms)
            counts[symbol] += 1
            hasher.update(line)
            head = recorded_sha
            previous_received = row["received_ms"]
            previous_persisted = frame.persisted_at_ms
            previous_mono = row["received_monotonic_ns"]
        if stream.read(1):
            raise ValueError("extra received originals outside admitted denominator")
    tails = {
        symbol: None if symbol not in last else receipt["ended_ms"] - last[symbol][2] for symbol in SYMBOLS
    }
    if (
        count != receipt["observed_messages"]
        or hasher.hexdigest() != receipt["raw_file_sha256"]
        or head != receipt["raw_head_sha256"]
        or payload_bytes != receipt["raw_payload_bytes"]
        or counts != receipt["symbol_counts"]
        or first != receipt["first_received_ms"]
        or gaps != receipt["maximum_observed_gap_ms"]
        or tails != receipt["terminal_gap_ms"]
        or not all(counts.values())
        or receipt["ended_ms"] < previous_persisted
        or any(gap is None or not 0 <= gap <= MAX_GAP_MS for gap in tails.values())
    ):
        raise ValueError("terminal capture/source coverage reconciliation conflict")
    return {
        "state": "PASS_OBSERVED_SOURCE_CONSISTENCY_ONLY",
        "receipt_sha256": receipt_sha,
        "observed_messages": count,
        "symbol_counts": counts,
        "segments": len(segments),
        "market_tick_completeness": "UNKNOWN_NOT_CLAIMED",
        "source_set_admitted": False,
        "risk_authority": "NONE",
    }


async def capture_public_book(output: Path, *, seconds: int) -> dict[str, Any]:
    """Exactly one credential-free TLS WebSocket; no retries/redirects/reconnects."""
    import aiohttp

    async def reject_redirect(*_):
        raise ValueError("public capture redirects are forbidden")

    trace = aiohttp.TraceConfig()
    trace.on_request_redirect.append(reject_redirect)
    context = ssl.create_default_context()
    if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
        raise ValueError("verified TLS hostname and certificate required")
    with CaptureOwner(output.parent):
        recorder = PublicBookRecorder(output, seconds=seconds)
        state, reason = "FAILED", "NO_CONNECTION"
        transport: dict[str, Any] = {
            "endpoint": ENDPOINT,
            "attempts": 0,
            "retries": 0,
            "redirects": 0,
            "tls_default_validation": True,
            "handshake_completed": False,
        }
        try:
            async with asyncio.timeout(seconds + 15):
                timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=10)
                async with aiohttp.ClientSession(
                    timeout=timeout, trust_env=False, trace_configs=[trace]
                ) as session:
                    transport["attempts"] = 1
                    async with session.ws_connect(
                        ENDPOINT,
                        ssl=context,
                        proxy=None,
                        max_msg_size=MAX_RAW_BYTES,
                        autoping=True,
                        heartbeat=None,
                    ) as socket:
                        if str(socket._response.url) != ENDPOINT:
                            raise ValueError("unexpected public capture response URL")
                        transport["handshake_completed"] = True
                        deadline = recorder.started_ns + seconds * 1_000_000_000
                        while time.monotonic_ns() < deadline:
                            remaining = (deadline - time.monotonic_ns()) / 1_000_000_000
                            if remaining <= 0:
                                break
                            try:
                                message = await asyncio.wait_for(socket.receive(), min(5.0, remaining))
                            except TimeoutError:
                                if time.monotonic_ns() >= deadline:
                                    break
                                raise ValueError("public stream receive gap") from None
                            received_ms, received_ns = wall_ms(), time.monotonic_ns()
                            if message.type is not aiohttp.WSMsgType.TEXT:
                                raise ValueError("public stream closed or returned non-text")
                            recorder.accept(message.data, received_ms=received_ms, received_ns=received_ns)
                            if recorder.observed == MAX_FRAMES:
                                raise ValueError("sealed frame bound reached before duration")
                        state, reason = "CAPTURED", "SEALED_DURATION_COMPLETE"
        except (Exception, asyncio.CancelledError) as exc:
            state, reason = "FAILED", type(exc).__name__
        finally:
            # aiohttp SSL transports finish closing asynchronously even after
            # ClientSession.__aexit__. Drain before asyncio.run closes its loop;
            # this is bounded cleanup, never another connection or retry.
            await asyncio.sleep(0.250)
        return recorder.finish(state=state, reason=reason, transport=transport)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--workspace-root", type=Path, default=Path(r"D:\Kairos"))
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args(argv)
    if not args.capture:
        print("NOT_STARTED: --capture required; no network or output")
        return 0
    runtime = _safe_existing(args.workspace_root / "runtime", directory=True)
    if args.output_root is None or args.output_root.absolute().parent != runtime:
        parser.error("new direct runtime child required")
    receipt = asyncio.run(capture_public_book(args.output_root.absolute(), seconds=args.seconds))
    print(
        canonical(
            {
                "state": receipt["state"],
                "reason": receipt["reason"],
                "observed_messages": receipt["observed_messages"],
                "admitted_frames": receipt["admitted_frames"],
                "symbol_counts": receipt["symbol_counts"],
                "segments": len(receipt["segments"]),
                "risk_authority": "NONE",
            }
        )
    )
    return 0 if receipt["state"] == "CAPTURED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
