"""Synthetic offline tests for ContinuousNativeTape; no live-source claims."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import kairos_native_campaign.current_tape as current_tape_module
from kairos_native_campaign.current_tape import ContinuousNativeTape, run_capture

BASE_MS = 1_800_000_000_000
SYMBOLS = ("BTCUSDT", "BNBUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")


class _Clocks:
    def __init__(self, start: int = BASE_MS) -> None:
        self.ms = start
        self.ns = start * 1_000_000

    def wall(self) -> int:
        return self.ms

    def mono(self) -> int:
        return self.ns

    def tick(self, delta_ms: int = 1) -> tuple[int, int]:
        self.ms += delta_ms
        self.ns += delta_ms * 1_000_000
        return self.ms, self.ns


def _wire(symbol: str, update: int, event_ms: int) -> str:
    body = {
        "e": "depthUpdate",
        "E": event_ms,
        "T": event_ms,
        "s": symbol,
        "U": update,
        "u": update,
        "pu": update - 1,
        "b": [[f"{100 - i}.0", "1.0"] for i in range(10)],
        "a": [[f"{101 + i}.0", "2.0"] for i in range(10)],
        "st": 1,
        "ps": symbol,
    }
    return json.dumps(
        {"stream": f"{symbol.lower()}@depth10@100ms", "data": body},
        separators=(",", ":"),
    )


def _start(tmp_path: Path, clocks: _Clocks, **limits: int) -> ContinuousNativeTape:
    tape = ContinuousNativeTape(
        tmp_path / "synthetic-tape",
        "synthetic-offline-tape",
        wall_clock=clocks.wall,
        monotonic_clock=clocks.mono,
        **limits,
    )
    tape.begin(clocks.ms, clocks.ns)
    return tape


def _accept(tape: ContinuousNativeTape, clocks: _Clocks, symbol: str, update: int, event_ms: int):
    received_ms, received_ns = clocks.tick()
    text = _wire(symbol, update, event_ms)
    tape.record_delivery(text, received_ms, received_ns)
    return tape.accept(text, received_ms, received_ns)


def _seed_all(tape: ContinuousNativeTape, clocks: _Clocks) -> None:
    for symbol in SYMBOLS:
        _accept(tape, clocks, symbol, 1, clocks.ms + 1)


def test_continuous_global_v2_sequence_and_migrated_native_binding(tmp_path: Path) -> None:
    clocks = _Clocks()
    tape = _start(tmp_path, clocks)
    # Synthetic fixture intentionally crosses the 512-frame consumer queue size.
    for index in range(520):
        symbol = SYMBOLS[index % len(SYMBOLS)]
        event_ms = clocks.ms + 1
        frame = _accept(tape, clocks, symbol, index // len(SYMBOLS) + 1, event_ms)
        assert frame.tape_sequence == index + 1
        assert frame.source == "kairos-current-continuous-native"
        assert frame.stream_epoch == tape.epoch
        assert frame.raw_payload == _wire(symbol, index // len(SYMBOLS) + 1, event_ms)
        assert frame.received_at_ms == event_ms
    assert [frame.tape_sequence for frame in tape.frames] == list(range(1, 521))
    assert tape.frames[0].previous_frame_sha256 is None
    assert tape.frames[512].previous_frame_sha256 == tape.frames[511].frame_sha256
    assert tape.latest("BTCUSDT", as_of_ms=clocks.ms) == tape.frames[515]
    assert tape.latest("BTCUSDT", as_of_ms=tape.frames[515].persisted_at_ms - 1) is tape.frames[510]

    receipt = tape.finish()
    assert receipt["state"] == "CAPTURED"
    assert receipt["frame_count"] == 520
    assert receipt["text_delivery_count"] == receipt["frame_count"]
    assert receipt["text_delivery_bytes"] == receipt["admitted_raw_payload_bytes"]
    assert tape.closed
    raw_lines = (tape.output / "received.raw.jsonl").read_text(encoding="utf-8").splitlines()
    frame_path = tape.output / "frames.jsonl"
    frame_lines = frame_path.read_text(encoding="utf-8").splitlines()
    assert len(raw_lines) == len(frame_lines) == 520
    first_raw = json.loads(raw_lines[0])
    first_line = json.loads(frame_lines[0])
    assert first_raw["raw_payload"] == first_line["raw_payload"] == tape.frames[0].raw_payload
    assert first_raw["received_monotonic_ns"] == tape.frames[0].received_at_ms * 1_000_000
    assert first_line["persisted_ms"] == tape.frames[0].persisted_at_ms
    assert first_line["frame"]["source"] == "kairos-current-continuous-native"
    assert first_line["frame_sha256"] == tape.frames[0].frame_sha256
    assert hashlib.sha256(first_raw["raw_payload"].encode()).hexdigest() == first_raw["raw_payload_sha256"]
    delivery_path = tape.output / "transport-delivery.raw.jsonl"
    assert len(delivery_path.read_text(encoding="utf-8").splitlines()) == 520
    assert hashlib.sha256(frame_path.read_bytes()).hexdigest() == receipt["frames_jsonl_sha256"]
    assert (
        hashlib.sha256(delivery_path.read_bytes()).hexdigest() == receipt["transport_delivery_jsonl_sha256"]
    )
    assert json.loads((tape.output / "plan.json").read_text(encoding="utf-8"))["native_policy_sha256"]
    assert json.loads((tape.output / "receipt.json").read_text(encoding="utf-8")) == receipt
    assert receipt["source_qualification"] == "NONE"


def test_snapshot_clock_and_latest_frame_are_atomic_and_not_backdated(tmp_path: Path) -> None:
    clocks = _Clocks()
    tape = _start(tmp_path, clocks)
    _seed_all(tape, clocks)
    snapshot_ms, frame = tape.snapshot("BTCUSDT")
    assert snapshot_ms == clocks.ms
    assert frame is tape.latest("BTCUSDT", as_of_ms=snapshot_ms)
    assert frame is not None and frame.persisted_at_ms <= snapshot_ms
    clocks.ms = frame.persisted_at_ms - 1
    assert tape.latest("BTCUSDT") is None
    assert tape.snapshot("BTCUSDT") == (clocks.ms, None)
    clocks.ms = BASE_MS + 10
    assert tape.finish()["state"] == "CAPTURED"


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        ("future", "FUTURE_OR_INVALID_EVENT_CLOCK"),
        ("update", "SYMBOL_UPDATE_REGRESSION"),
        ("gap", "SOURCE_GAP"),
    ],
)
def test_invalid_future_update_and_source_gap_poison_tape(tmp_path: Path, mutate: str, expected: str) -> None:
    clocks = _Clocks()
    tape = _start(tmp_path, clocks)
    _seed_all(tape, clocks)
    received_ms, received_ns = clocks.tick()
    if mutate == "future":
        body = _wire("BTCUSDT", 2, received_ms + 1)
    elif mutate == "update":
        body = _wire("BTCUSDT", 1, received_ms)
    else:
        clocks.ms += 5_001
        clocks.ns += 5_001_000_000
        received_ms, received_ns = clocks.ms, clocks.ns
        body = _wire("BTCUSDT", 2, received_ms)
    with pytest.raises(ValueError):
        tape.accept(body, received_ms, received_ns)
    assert tape.failure == expected
    assert tape.frames and len(tape.frames) == len(SYMBOLS)
    with pytest.raises(ValueError):
        tape.snapshot("BTCUSDT")
    assert tape.finish()["state"] == "FAILED"


@pytest.mark.asyncio
async def test_capture_queue_overflow_fails_closed_with_every_delivery_receipted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import aiohttp

    clocks = _Clocks()
    tape = ContinuousNativeTape(
        tmp_path / "synthetic-tape",
        "synthetic-offline-tape",
        wall_clock=clocks.wall,
        monotonic_clock=clocks.mono,
    )
    monkeypatch.setattr(current_tape_module, "DELIVERY_QUEUE_SIZE", 1)

    class _Socket:
        _response = SimpleNamespace(url=current_tape_module.ENDPOINT)

        def __init__(self) -> None:
            self.index = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def receive(self):
            self.index += 1
            received_ms, _ = clocks.tick()
            return SimpleNamespace(
                type=aiohttp.WSMsgType.TEXT,
                data=_wire(SYMBOLS[(self.index - 1) % len(SYMBOLS)], self.index, received_ms),
            )

    class _Session:
        def __init__(self, **_kwargs):
            self.socket = _Socket()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def ws_connect(self, *_args, **_kwargs):
            return self.socket

    original_to_thread = asyncio.to_thread

    async def slow_to_thread(fn, *args, **kwargs):
        await asyncio.sleep(0.05)
        return await original_to_thread(fn, *args, **kwargs)

    monkeypatch.setattr(aiohttp, "ClientSession", _Session)
    monkeypatch.setattr(asyncio, "to_thread", slow_to_thread)
    ready, stop = asyncio.Event(), asyncio.Event()
    receipt = await asyncio.wait_for(run_capture(tape, ready, stop), timeout=5)
    deliveries = [
        json.loads(line)
        for line in (tape.output / "transport-delivery.raw.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert receipt["state"] == "FAILED"
    assert receipt["failure"] == "DELIVERY_QUEUE_OVERFLOW", (
        tape.failure,
        receipt["failure"],
        len(deliveries),
        len(tape.frames),
    )
    assert len(deliveries) == receipt["delivery_count"] == 3
    assert all(record["body_retained"] for record in deliveries)
    assert len(tape.frames) <= 1
    assert not ready.is_set()


def test_terminal_gap_fails_closed_and_records_failed_receipt(tmp_path: Path) -> None:
    clocks = _Clocks()
    tape = _start(tmp_path, clocks)
    _seed_all(tape, clocks)
    clocks.ms += 5_001
    clocks.ns += 5_001_000_000
    receipt = tape.finish()
    assert receipt["state"] == "FAILED"
    assert receipt["failure"] == "TERMINAL_SYMBOL_STALE"


def test_unmatched_retained_text_suffix_cannot_seal_as_captured(tmp_path: Path) -> None:
    clocks = _Clocks()
    tape = _start(tmp_path, clocks)
    _seed_all(tape, clocks)
    received_ms, received_ns = clocks.tick()
    extra = _wire("BTCUSDT", 2, received_ms)
    tape.record_delivery(extra, received_ms, received_ns)

    receipt = tape.finish()

    assert receipt["state"] == "FAILED"
    assert receipt["failure"] == "UNMATCHED_TEXT_DELIVERIES"
    assert receipt["text_delivery_count"] == 6
    assert receipt["frame_count"] == 5


def test_control_ping_delivery_is_accounted_separately_from_text_denominator(tmp_path: Path) -> None:
    clocks = _Clocks()
    tape = _start(tmp_path, clocks)
    _seed_all(tape, clocks)
    received_ms, received_ns = clocks.tick()
    tape.record_delivery(b"ping-control", received_ms, received_ns, message_type="PING")

    receipt = tape.finish()

    assert receipt["state"] == "CAPTURED"
    assert receipt["text_delivery_count"] == receipt["frame_count"] == 5
    assert receipt["control_delivery_count"] == 1
    assert receipt["control_body_bytes"] == len(b"ping-control")


def test_initial_symbol_gap_fails_before_admission(tmp_path: Path) -> None:
    clocks = _Clocks()
    tape = _start(tmp_path, clocks)
    clocks.tick(5_001)
    received_ms, received_ns = clocks.tick()
    with pytest.raises(ValueError, match="unavailable at capture start"):
        tape.accept(_wire("BTCUSDT", 1, received_ms), received_ms, received_ns)
    assert tape.failure == "INITIAL_SYMBOL_GAP"
    assert tape.frames == ()
    assert tape.finish()["state"] == "FAILED"


def test_liveness_detects_source_silence_without_waiting_for_finish(tmp_path: Path) -> None:
    clocks = _Clocks()
    tape = _start(tmp_path, clocks)
    _seed_all(tape, clocks)
    with pytest.raises(ValueError, match="silence"):
        tape.check_liveness(BASE_MS + 5_006, clocks.ns + 5_001_000_000)
    assert tape.failure == "SOURCE_GAP"
    assert tape.finish()["state"] == "FAILED"


def test_resource_overflow_never_drops_a_frame_or_retries(tmp_path: Path) -> None:
    clocks = _Clocks()
    tape = _start(tmp_path, clocks, maximum_frames=5)
    _seed_all(tape, clocks)
    received_ms, received_ns = clocks.tick()
    with pytest.raises(ValueError, match="resource bound"):
        tape.accept(_wire("BTCUSDT", 2, received_ms), received_ms, received_ns)
    assert len(tape.frames) == 5
    assert tape.failure == "RESOURCE_BOUND_REACHED"
    assert tape.finish()["state"] == "FAILED"


def test_existing_output_directory_is_not_reused_or_rerooted(tmp_path: Path) -> None:
    output = tmp_path / "already-exists"
    output.mkdir()
    (output / "sentinel").write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        ContinuousNativeTape(output, "synthetic-tape")
    assert (output / "sentinel").read_text(encoding="utf-8") == "preserve"
