"""Offline synthetic tests for the opt-in public depth capture boundary.

Every message here is fabricated test input. These checks establish recorder
behavior, not Binance provenance, authenticated clocks, or market coverage.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from adaptive_replay import public_book_capture as capture
from adaptive_replay.book_bundle import BookBundleSeal, RetentionReceipt, open_book_bundle
from adaptive_replay.historical_context import canonical
from adaptive_replay.native_book_capture import NativeBookPolicy

START_MS = 1_791_400_000_000
START_NS = 9_000_000_000_000
SYNTHETIC_TRANSPORT = {
    "endpoint": capture.ENDPOINT,
    "attempts": 1,
    "retries": 0,
    "redirects": 0,
    "tls_default_validation": True,
    "handshake_completed": True,
}


class FakeClock:
    def __init__(self, ms: int = START_MS, ns: int = START_NS):
        self.ms = ms
        self.ns = ns

    def wall(self) -> int:
        return self.ms

    def mono(self) -> int:
        return self.ns


def _wire(symbol: str, update: int, event_ms: int | None = None, *, bids=None, asks=None) -> str:
    event = START_MS + 1 if event_ms is None else event_ms
    body = {
        "e": "depthUpdate",
        "E": event,
        "T": event - 1,
        "s": symbol,
        "U": update - 1,
        "u": update,
        "pu": update - 2,
        "b": bids if bids is not None else [["100", "1.25"]],
        "a": asks if asks is not None else [["101", "2.5"]],
        "st": 1,
        "ps": symbol,
    }
    return json.dumps({"stream": f"{symbol.lower()}@depth10@100ms", "data": body}, separators=(",", ":"))


def _recorder(
    tmp_path: Path, *, seconds: int = 1, clock: FakeClock | None = None
) -> tuple[capture.PublicBookRecorder, FakeClock]:
    clock = clock or FakeClock()
    output = tmp_path / "public-book-capture-20261009-test"
    return capture.PublicBookRecorder(output, seconds=seconds, clock=clock.wall, monotonic=clock.mono), clock


def _accept(
    rec: capture.PublicBookRecorder,
    symbol: str,
    update: int,
    offset_ms: int,
    *,
    ns_offset: int | None = None,
    event_ms: int | None = None,
    text: str | None = None,
):
    ns_offset = offset_ms if ns_offset is None else ns_offset
    fake_clock = getattr(rec.clock, "__self__", None)
    if fake_clock is not None:
        # Persistence follows the message; retain the previous wall time when
        # deliberately simulating a receive-clock regression.
        fake_clock.ms = max(fake_clock.ms, START_MS + offset_ms)
    return rec.accept(
        text if text is not None else _wire(symbol, update, event_ms),
        received_ms=START_MS + offset_ms,
        received_ns=START_NS + ns_offset * 1_000_000,
    )


def _finish_failed(rec: capture.PublicBookRecorder, clock: FakeClock) -> dict:
    clock.ms = max(clock.ms, rec.last_persisted, rec.last_received)
    clock.ns = max(clock.ns, rec.last_monotonic)
    return rec.finish(state="FAILED", reason="TEST_FAILURE", transport={"test_fixture": True})


def _complete_capture(tmp_path: Path, monkeypatch, *, segment_frames: int = 2):
    monkeypatch.setattr(capture, "SEGMENT_FRAMES", segment_frames)
    rec, clock = _recorder(tmp_path, seconds=1)
    for index, symbol in enumerate(capture.SYMBOLS):
        _accept(rec, symbol, 100 + index, 100 + index * 100)
    clock.ms = START_MS + 1_000
    clock.ns = START_NS + 1_000_000_000
    # Fabricated structure only; these fixture messages came from no socket.
    receipt = rec.finish(
        state="CAPTURED", reason="SEALED_DURATION_COMPLETE", transport=dict(SYNTHETIC_TRANSPORT)
    )
    receipt_bytes = (rec.output / "receipt.json").read_bytes()
    return rec, clock, receipt, hashlib.sha256(receipt_bytes).hexdigest()


def test_original_text_is_fsynced_before_v2_construction_and_segments_reopen(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "SEGMENT_FRAMES", 2)
    rec, clock = _recorder(tmp_path)
    raw_fd = rec.raw.fileno()
    real_fsync = capture.os.fsync
    fsynced = []

    def fsync_spy(fd):
        real_fsync(fd)
        fsynced.append(fd)

    monkeypatch.setattr(capture.os, "fsync", fsync_spy)
    original_factory = capture.RecordedTopNBookFrameV2

    def checking_factory(**kwargs):
        assert raw_fd in fsynced
        raw_lines = (rec.output / "received.raw.jsonl").read_text(encoding="utf-8").splitlines()
        assert json.loads(raw_lines[-1])["raw_payload"] == kwargs["raw_payload"]
        return original_factory(**kwargs)

    monkeypatch.setattr(capture, "RecordedTopNBookFrameV2", checking_factory)
    symbols = capture.SYMBOLS
    frames = []
    for index, symbol in enumerate(symbols):
        frames.append(_accept(rec, symbol, 100 + index, 100 + index * 40))
        frames.append(_accept(rec, symbol, 200 + index, 120 + index * 40))
    clock.ms = START_MS + 1_000
    clock.ns = START_NS + 1_000_000_000
    # Fabricated structure only; these fixture messages came from no socket.
    result = rec.finish(
        state="CAPTURED", reason="TEST_DURATION_COMPLETE", transport=dict(SYNTHETIC_TRANSPORT)
    )

    assert all(type(frame) is original_factory for frame in frames)
    assert result["state"] == "CAPTURED"
    assert result["observed_messages"] == result["admitted_frames"] == 10
    assert result["raw_payload_bytes"] == sum(len(frame.raw_payload.encode("utf-8")) for frame in frames)
    assert result["symbol_counts"] == dict.fromkeys(symbols, 2)
    assert len(result["segments"]) == 5
    assert all(
        segment["observed_prefix_head_at_flush_sha256"] == segment["raw_prefix_head_sha256"]
        for segment in result["segments"]
    )
    assert result["source_set_admitted"] is False
    assert result["risk_authority"] == "NONE"

    for segment in result["segments"]:
        value = json.loads((rec.output / segment["name"]).read_text(encoding="utf-8"))
        assert (
            value["records"][0]["frame"]["raw_payload"]
            != value["records"][0]["derived_capture"]["raw_payload_utf8"]
        )
        seal = BookBundleSeal(
            bundle_id=segment["seal"]["bundle_id"],
            tape_id=segment["seal"]["tape_id"],
            stream_epoch=segment["seal"]["stream_epoch"],
            policy=NativeBookPolicy(**segment["seal"]["policy"]),
            frame_count=segment["seal"]["frame_count"],
            native_head_sha256=segment["seal"]["native_head_sha256"],
            records_sha256=segment["seal"]["records_sha256"],
            implementation_sha256=segment["seal"]["implementation_sha256"],
        )
        retention = RetentionReceipt(**segment["retention"])
        reopened = open_book_bundle(rec.output / segment["name"], seal, retention)
        assert len(reopened.bindings) == segment["global_last"] - segment["global_first"] + 1


def test_missing_symbol_and_end_gap_turn_capture_into_failed_receipt(tmp_path):
    rec, clock = _recorder(tmp_path)
    _accept(rec, capture.SYMBOLS[0], 10, 100)
    clock.ms = START_MS + 1_000
    clock.ns = START_NS + 1_000_000_000
    result = rec.finish(state="CAPTURED", reason="requested", transport={})
    assert result["state"] == "FAILED"
    assert result["reason"] == "OBSERVED_COVERAGE_OR_CLOCK_BOUNDARY_CONFLICT"
    assert result["symbol_counts"][capture.SYMBOLS[0]] == 1
    assert all(result["symbol_counts"][symbol] == 0 for symbol in capture.SYMBOLS[1:])
    assert result["terminal_gap_ms"][capture.SYMBOLS[0]] == 900
    assert all(result["terminal_gap_ms"][symbol] is None for symbol in capture.SYMBOLS[1:])


@pytest.mark.parametrize("bad_text", ["{not-json", '{"data":{},"data":{}}'])
def test_invalid_or_duplicate_json_is_retained_then_capture_fails_closed(tmp_path, bad_text):
    rec, clock = _recorder(tmp_path)
    with pytest.raises(ValueError):
        _accept(rec, capture.SYMBOLS[0], 1, 10, text=bad_text)
    line = (rec.output / "received.raw.jsonl").read_text(encoding="utf-8").splitlines()[0]
    record = json.loads(line)
    assert record["raw_payload"] == bad_text
    assert record["raw_payload_sha256"] == hashlib.sha256(bad_text.encode()).hexdigest()
    assert rec.failed and rec.observed == 1 and rec.admitted == 0
    with pytest.raises(ValueError, match="terminal capture"):
        _accept(rec, capture.SYMBOLS[0], 2, 20)
    _finish_failed(rec, clock)


@pytest.mark.parametrize(
    "levels",
    [
        ([["99", "1"], ["100", "2"]], [["101", "1"]]),
        ([["100", "0"]], [["101", "1"]]),
        ([["NaN", "1"]], [["101", "1"]]),
    ],
)
def test_malformed_or_noncanonical_raw_quantities_are_retained_then_rejected(tmp_path, levels):
    rec, clock = _recorder(tmp_path)
    raw = _wire(capture.SYMBOLS[0], 10, bids=levels[0], asks=levels[1])
    with pytest.raises(ValueError, match="exact V2 validation"):
        _accept(rec, capture.SYMBOLS[0], 10, 10, text=raw)
    stored = json.loads((rec.output / "received.raw.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert stored["raw_payload"] == raw
    assert rec.failed and rec.admitted == 0
    _finish_failed(rec, clock)


@pytest.mark.parametrize("wall_offset,mono_offset,event_offset", [(1_101, 100, 1_100), (100, 1_101, 100)])
def test_wall_monotonic_elapsed_disagreement_is_terminal_and_raw_is_preserved(
    tmp_path, wall_offset, mono_offset, event_offset
):
    rec, clock = _recorder(tmp_path, seconds=2)
    with pytest.raises(ValueError, match="elapsed clocks disagree"):
        _accept(
            rec, capture.SYMBOLS[0], 1, wall_offset, ns_offset=mono_offset, event_ms=START_MS + event_offset
        )
    assert rec.failed and rec.observed == 1 and rec.admitted == 0
    assert len((rec.output / "received.raw.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    _finish_failed(rec, clock)


@pytest.mark.parametrize("kind", ["wall", "monotonic", "event", "future"])
def test_clock_regressions_and_future_exchange_events_fail_after_raw_retention(tmp_path, kind):
    rec, clock = _recorder(tmp_path)
    _accept(rec, capture.SYMBOLS[0], 10, 100)
    if kind == "wall":
        args = dict(offset_ms=99, ns_offset=101)
    elif kind == "monotonic":
        args = dict(offset_ms=101, ns_offset=99)
    elif kind == "event":
        args = dict(offset_ms=200, ns_offset=200, event_ms=START_MS)
    else:
        args = dict(offset_ms=100, ns_offset=100, event_ms=START_MS + 101)
    with pytest.raises(ValueError):
        _accept(rec, capture.SYMBOLS[0], 11, **args)
    assert rec.failed and rec.observed == 2 and rec.admitted == 1
    stored = (rec.output / "received.raw.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(stored) == 2
    _finish_failed(rec, clock)


def test_exchange_clock_ahead_preserves_exact_raw_event_and_admits_zero(tmp_path):
    rec, clock = _recorder(tmp_path)
    raw = _wire(capture.SYMBOLS[0], 10, event_ms=START_MS + 101)
    with pytest.raises(capture.ExchangeClockAhead):
        _accept(rec, capture.SYMBOLS[0], 10, 100, text=raw)

    stored = json.loads((rec.output / "received.raw.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert stored["raw_payload"] == raw
    assert stored["raw_payload_sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert rec.observed == 1
    assert rec.admitted == 0
    assert rec.failed
    receipt = _finish_failed(rec, clock)
    assert receipt["observed_messages"] == 1
    assert receipt["admitted_frames"] == 0


def test_update_ids_remain_monotone_across_segment_rotation(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "SEGMENT_FRAMES", 2)
    rec, clock = _recorder(tmp_path)
    symbol = capture.SYMBOLS[0]
    _accept(rec, symbol, 20, 100)
    _accept(rec, capture.SYMBOLS[1], 50, 120)
    with pytest.raises(ValueError, match="update or exchange clock regression"):
        _accept(rec, symbol, 19, 140)
    assert len(rec.segments) == 1
    assert rec.failed and rec.observed == 3 and rec.admitted == 2
    assert len((rec.output / "received.raw.jsonl").read_text(encoding="utf-8").splitlines()) == 3
    _finish_failed(rec, clock)


def test_full_audit_is_read_only_and_accepts_only_exact_reopened_capture(tmp_path, monkeypatch):
    rec, _, receipt, receipt_sha = _complete_capture(tmp_path, monkeypatch)
    before = {p.name: p.read_bytes() for p in rec.output.iterdir() if p.is_file()}
    result = capture.audit_public_capture(rec.output, expected_receipt_sha256=receipt_sha)
    after = {p.name: p.read_bytes() for p in rec.output.iterdir() if p.is_file()}
    assert result["state"] == "PASS_OBSERVED_SOURCE_CONSISTENCY_ONLY"
    assert result["observed_messages"] == receipt["observed_messages"] == 5
    assert result["symbol_counts"] == receipt["symbol_counts"]
    assert result["source_set_admitted"] is False
    assert before == after


def test_full_audit_rejects_caller_receipt_hash_mismatch(tmp_path, monkeypatch):
    rec, _, _, receipt_sha = _complete_capture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="independent expected hash"):
        capture.audit_public_capture(rec.output, expected_receipt_sha256="0" * 64)
    assert (rec.output / "receipt.json").exists()
    assert receipt_sha != "0" * 64


@pytest.mark.parametrize("target", ["raw", "bundle", "segment_receipt"])
def test_full_audit_rejects_tampered_raw_bundle_or_segment_receipt(tmp_path, monkeypatch, target):
    rec, _, _, receipt_sha = _complete_capture(tmp_path, monkeypatch)
    if target == "raw":
        path = rec.output / "received.raw.jsonl"
        rows = path.read_text(encoding="utf-8").splitlines()
        value = json.loads(rows[0])
        value["raw_payload"] = "tampered original"
        rows[0] = canonical(value)
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    elif target == "bundle":
        (rec.output / "segment-0001.native-book.research.json").write_bytes(b"tampered bundle")
    else:
        path = rec.output / "segment-0001.receipt.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["global_last"] += 1
        path.write_text(canonical(value), encoding="utf-8")
    with pytest.raises(ValueError):
        capture.audit_public_capture(rec.output, expected_receipt_sha256=receipt_sha)


@pytest.mark.parametrize("change", ["counts", "gaps", "source_plan"])
def test_rehashed_terminal_receipt_does_not_authorize_changed_counts_gaps_or_plan(
    tmp_path, monkeypatch, change
):
    rec, _, _, _ = _complete_capture(tmp_path, monkeypatch)
    receipt_path = rec.output / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if change == "counts":
        receipt["symbol_counts"][capture.SYMBOLS[0]] += 1
    elif change == "gaps":
        receipt["maximum_observed_gap_ms"][capture.SYMBOLS[0]] += 1
    else:
        plan_path = rec.output / "plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["endpoint"] = "wss://untrusted.invalid/changed"
        plan_bytes = canonical(plan).encode("utf-8")
        plan_path.write_bytes(plan_bytes)
        receipt["plan_sha256"] = hashlib.sha256(plan_bytes).hexdigest()
    receipt_bytes = canonical(receipt).encode("utf-8")
    receipt_path.write_bytes(receipt_bytes)
    rehashed_pin = hashlib.sha256(receipt_bytes).hexdigest()
    with pytest.raises(ValueError):
        capture.audit_public_capture(rec.output, expected_receipt_sha256=rehashed_pin)


@pytest.mark.parametrize(
    "field,value",
    [
        ("endpoint", "wss://wrong.invalid/stream"),
        ("attempts", True),
        ("retries", 1),
        ("tls_default_validation", False),
        ("handshake_completed", False),
    ],
)
def test_rehashed_terminal_receipt_rejects_contradictory_transport_claims(
    tmp_path, monkeypatch, field, value
):
    rec, _, _, _ = _complete_capture(tmp_path, monkeypatch)
    receipt_path = rec.output / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["transport"][field] = value
    receipt_bytes = canonical(receipt).encode("utf-8")
    receipt_path.write_bytes(receipt_bytes)
    with pytest.raises(ValueError, match="source, plan or authority"):
        capture.audit_public_capture(
            rec.output, expected_receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest()
        )


def test_rehashed_terminal_receipt_cannot_end_before_last_persisted_frame(tmp_path, monkeypatch):
    rec, _, _, _ = _complete_capture(tmp_path, monkeypatch)
    receipt_path = rec.output / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["ended_ms"] = START_MS + 499  # Last synthetic persistence is at +500 ms.
    receipt_bytes = canonical(receipt).encode("utf-8")
    receipt_path.write_bytes(receipt_bytes)
    with pytest.raises(ValueError):
        capture.audit_public_capture(
            rec.output, expected_receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest()
        )


def test_rehashed_segment_receipt_cannot_claim_different_valid_observed_prefix(tmp_path, monkeypatch):
    rec, _, _, _ = _complete_capture(tmp_path, monkeypatch)
    receipt_path = rec.output / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    segment = receipt["segments"][-1]
    segment["observed_prefix_head_at_flush_sha256"] = "0" * 64
    separate_path = rec.output / segment["name"].replace(".native-book.research.json", ".receipt.json")
    separate_path.write_text(canonical(segment), encoding="utf-8")
    receipt_bytes = canonical(receipt).encode("utf-8")
    receipt_path.write_bytes(receipt_bytes)
    with pytest.raises(ValueError, match="segment chain/count/epoch"):
        capture.audit_public_capture(
            rec.output, expected_receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest()
        )


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_full_audit_rejects_missing_or_extra_original_rows(tmp_path, monkeypatch, mutation):
    rec, _, _, receipt_sha = _complete_capture(tmp_path, monkeypatch)
    path = rec.output / "received.raw.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    if mutation == "missing":
        rows.pop()
    else:
        rows.append(rows[-1])
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        capture.audit_public_capture(rec.output, expected_receipt_sha256=receipt_sha)


def test_early_finish_cannot_be_marked_captured(tmp_path):
    rec, clock = _recorder(tmp_path, seconds=1)
    for index, symbol in enumerate(capture.SYMBOLS):
        _accept(rec, symbol, 100 + index, 100 + index * 100)
    clock.ms = START_MS + 999
    clock.ns = START_NS + 999_000_000
    receipt = rec.finish(state="CAPTURED", reason="too_early", transport={})
    assert receipt["state"] == "FAILED"
    assert receipt["observed_stream_check"] == "FAIL"
    assert receipt["elapsed_monotonic_ms"] == 999
    assert rec.raw.closed


def test_flush_failure_preserves_raw_and_writes_failed_receipt(tmp_path, monkeypatch):
    rec, clock = _recorder(tmp_path)
    _accept(rec, capture.SYMBOLS[0], 10, 100)

    def fail_retention(*args, **kwargs):
        raise OSError("synthetic segment retention failure")

    monkeypatch.setattr(capture, "retain_book_bundle", fail_retention)
    receipt = rec.finish(state="CAPTURED", reason="requested", transport={})
    assert receipt["state"] == "FAILED"
    assert receipt["reason"] == "SEGMENT_RETENTION_OSError"
    assert rec.raw.closed
    assert len((rec.output / "received.raw.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    assert (rec.output / "receipt.json").exists()


def test_failed_suffix_distinguishes_admitted_and_observed_heads_at_flush(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "SEGMENT_FRAMES", 3)
    rec, clock = _recorder(tmp_path)
    _accept(rec, capture.SYMBOLS[0], 10, 100)
    _accept(rec, capture.SYMBOLS[1], 20, 200)
    with pytest.raises(ValueError):
        _accept(rec, capture.SYMBOLS[2], 30, 300, text='{"data":{},"data":{}}')
    receipt = _finish_failed(rec, clock)
    segment = receipt["segments"][0]
    assert segment["raw_prefix_head_sha256"] == rec.admitted_raw_head
    assert segment["observed_prefix_head_at_flush_sha256"] == rec.raw_head
    assert segment["raw_prefix_head_sha256"] != segment["observed_prefix_head_at_flush_sha256"]


def test_full_audit_rejects_changed_installed_source_bytes(tmp_path, monkeypatch):
    rec, _, _, receipt_sha = _complete_capture(tmp_path, monkeypatch)
    fake_source = tmp_path / "altered_public_book_capture.py"
    fake_source.write_bytes(Path(capture.__file__).read_bytes() + b"\n# altered test source\n")
    monkeypatch.setattr(capture, "__file__", str(fake_source))
    with pytest.raises(ValueError, match="source, plan or authority"):
        capture.audit_public_capture(rec.output, expected_receipt_sha256=receipt_sha)


@pytest.mark.parametrize("failure", ["redirect", "closed_socket"])
def test_injected_transport_redirect_or_closed_socket_is_single_attempt_no_retry(
    tmp_path, monkeypatch, failure
):
    class FakeTraceConfig:
        def __init__(self):
            self.on_request_redirect = []

    class FakeSocket:
        _response = SimpleNamespace(url=capture.ENDPOINT)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def receive(self):
            return SimpleNamespace(type=2)

    class FakeRequestContext:
        def __init__(self, session):
            self.session = session
            self.socket = None

        async def __aenter__(self):
            self.socket = await self.session._connect()
            return self.socket

        async def __aexit__(self, *_):
            return None

    sessions = []

    class FakeSession:
        def __init__(self, **kwargs):
            self.traces = kwargs["trace_configs"]
            self.calls = 0
            sessions.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def ws_connect(self, *args, **kwargs):
            return FakeRequestContext(self)

        async def _connect(self):
            self.calls += 1
            if failure == "redirect":
                for callback in self.traces[0].on_request_redirect:
                    await callback(None, None, None)
            return FakeSocket()

    fake_aiohttp = SimpleNamespace(
        TraceConfig=FakeTraceConfig,
        ClientTimeout=lambda **kwargs: SimpleNamespace(**kwargs),
        ClientSession=FakeSession,
        WSMsgType=SimpleNamespace(TEXT=1),
    )
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)
    output = tmp_path / f"public-book-capture-20261009-{failure.replace('_', '-')}"
    result = capture.asyncio.run(capture.capture_public_book(output, seconds=1))
    assert result["state"] == "FAILED"
    assert result["transport"]["attempts"] == 1
    assert result["transport"]["retries"] == 0
    assert sessions[0].calls == 1
    assert result["observed_messages"] == 0
    assert (output / "receipt.json").exists()


def test_tls_session_teardown_is_drained_after_close_without_reconnect(tmp_path, monkeypatch):
    events = []

    class FakeTraceConfig:
        def __init__(self):
            self.on_request_redirect = []

    class FakeSocket:
        _response = SimpleNamespace(url=capture.ENDPOINT)

        async def __aenter__(self):
            events.append("socket_open")
            return self

        async def __aexit__(self, *_):
            events.append("socket_close")

        async def receive(self):
            return SimpleNamespace(type=2)

    class FakeRequestContext:
        async def __aenter__(self):
            return await self.session._connect()

        async def __aexit__(self, *_):
            return None

        def __init__(self, session):
            self.session = session

    sessions = []

    class FakeSession:
        def __init__(self, **kwargs):
            self.calls = 0
            sessions.append(self)

        async def __aenter__(self):
            events.append("session_open")
            return self

        async def __aexit__(self, *_):
            events.append("session_close")

        def ws_connect(self, *args, **kwargs):
            return FakeRequestContext(self)

        async def _connect(self):
            self.calls += 1
            return FakeSocket()

    fake_aiohttp = SimpleNamespace(
        TraceConfig=FakeTraceConfig,
        ClientTimeout=lambda **kwargs: SimpleNamespace(**kwargs),
        ClientSession=FakeSession,
        WSMsgType=SimpleNamespace(TEXT=1),
    )
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)
    original_sleep = capture.asyncio.sleep

    async def record_drain(delay, *args, **kwargs):
        if delay == 0.250:
            events.append("tls_drain")
        return await original_sleep(delay, *args, **kwargs)

    monkeypatch.setattr(capture.asyncio, "sleep", record_drain)
    output = tmp_path / "public-book-capture-20261009-tls-drain"
    result = capture.asyncio.run(capture.capture_public_book(output, seconds=1))

    assert result["state"] == "FAILED"
    assert result["transport"]["attempts"] == 1
    assert result["transport"]["retries"] == 0
    assert result["transport"]["redirects"] == 0
    assert sessions[0].calls == 1
    assert events.index("session_close") < events.index("tls_drain")
    assert events.count("tls_drain") == 1


def test_existing_output_is_never_overwritten_or_resumed(tmp_path):
    output = tmp_path / "public-book-capture-20261009-test"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("untouched", encoding="utf-8")
    with pytest.raises(FileExistsError):
        capture.PublicBookRecorder(output, seconds=1, clock=lambda: START_MS, monotonic=lambda: START_NS)
    assert marker.read_text(encoding="utf-8") == "untouched"


def test_default_cli_is_noop_without_network_or_output(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("default CLI must not start capture")

    monkeypatch.setattr(capture.asyncio, "run", forbidden)
    monkeypatch.setattr(capture, "capture_public_book", forbidden)
    output = tmp_path / "public-book-capture-20261009-cli"
    assert capture.main(["--workspace-root", str(tmp_path), "--output-root", str(output)]) == 0
    assert "NOT_STARTED" in capsys.readouterr().out
    assert not output.exists()


def test_capture_owner_excludes_simultaneous_owner_and_releases_for_new_capture(tmp_path):
    with capture.CaptureOwner(tmp_path):
        with pytest.raises((OSError, BlockingIOError)):
            with capture.CaptureOwner(tmp_path):
                pass
    with capture.CaptureOwner(tmp_path):
        pass


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink creation is unavailable")
def test_capture_owner_refuses_symlinked_runtime_when_platform_allows(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "alias"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("platform does not grant symlink fixture creation")
    with pytest.raises(ValueError, match="symlinks"):
        capture.CaptureOwner(link)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink creation is unavailable")
def test_capture_safe_path_refuses_symlinked_file_when_platform_allows(tmp_path):
    target = tmp_path / "real.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "alias.json"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("platform does not grant symlink fixture creation")
    with pytest.raises(ValueError, match="symlinks"):
        capture._safe_existing(link, directory=False)
