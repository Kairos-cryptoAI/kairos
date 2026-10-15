from __future__ import annotations

import asyncio
import importlib.util
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "capture_sim_tape.py"
SPEC = importlib.util.spec_from_file_location("capture_sim_tape", TOOL)
assert SPEC is not None and SPEC.loader is not None
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


class Frame:
    def __init__(self, continuity="ADMITTED"):
        self.frame_sha256 = "frame-hash"
        self.continuity = continuity


class Recorder:
    def __init__(self, frames):
        self.frames = list(frames)
        self.acked = []

    def pending_frames(self):
        return tuple(self.frames)

    def acknowledge(self, frame_hash):
        assert frame_hash == self.frames[0].frame_sha256
        self.acked.append(frame_hash)
        self.frames.pop(0)


class Repository:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.persisted = []

    async def record_book_frame(self, frame):
        if self.fail:
            raise RuntimeError("storage failure")
        self.persisted.append(frame)


class BarCollector:
    def __init__(self, candle, *, safe=True):
        self.candle = candle
        self.safe = safe
        self.acknowledged = []

    def pending_closed_klines(self, _symbol):
        return (self.candle,) if self.candle is not None else ()

    def is_kline_stream_safe(self, _symbol):
        return self.safe

    def acknowledge_closed_klines(self, symbol, count):
        self.acknowledged.append((symbol, count))


class BarRepository:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.persisted = []

    async def record_closed_bar(self, _tape_id, bar):
        if self.fail:
            raise ValueError("closed bars must be a contiguous prefix")
        self.persisted.append(bar)


class FinalizeCollector:
    def __init__(self, candle=None):
        self.candle = candle
        self.acknowledged = []

    def pending_closed_klines(self, symbol):
        return (self.candle,) if self.candle is not None and symbol == self.candle.symbol else ()

    def acknowledge_closed_klines(self, symbol, count):
        self.acknowledged.append((symbol, count))

    def is_kline_stream_safe(self, _symbol):
        return True

    def is_book_fresh(self, _symbol, _max_age):
        return True


class FinalizeRecorder(Recorder):
    def __init__(self, *, planned_stop_barrier=True, frames=()):
        super().__init__(frames)
        self._planned_stop_barrier = planned_stop_barrier
        self.planned_stop_requested = False
        self.planned_stop_barrier_seen = False
        self.status = SimpleNamespace(blocked_reason=None)
        self.evidence_bytes = 0

    def request_planned_stop(self):
        self.planned_stop_requested = True

    def add_evidence_bytes(self, size):
        self.evidence_bytes += size


class FinalizeRepository:
    def __init__(self, *, producer_tasks=()):
        self.sealed = False
        self.producer_tasks = producer_tasks
        self.producers_stopped_at_seal = False
        self.bars = []
        self.books = []

    async def record_closed_bar(self, _tape_id, bar):
        self.bars.append(bar)

    async def record_book_frame(self, frame):
        self.books.append(frame)

    async def seal_tape(self, tape_id, *, sealed_at_ms, source):
        self.sealed = True
        self.producers_stopped_at_seal = all(task.done() for task in self.producer_tasks)
        return SimpleNamespace(tape_id=tape_id, sealed_at_ms=sealed_at_ms, tape_sha256="seal-hash")

    async def verify_tape(self, _tape_id):
        return True


class RecorderBaseFake:
    def __init__(self, *, tape_id, symbols, source, max_pending_frames):
        self.tape_id = tape_id
        self.symbols = symbols
        self.source = source
        self.max_pending_frames = max_pending_frames
        self.status = SimpleNamespace(state="IDLE", blocked_reason=None)
        self.frames = []

    def begin_public_stream(self, *, connected_at_ms):
        self.status.state = "RECORDING"
        self.connected_at_ms = connected_at_ms

    def record_source_barrier(self, *, continuity, at_ms, reason):
        self.status.state = "BLOCKED"
        self.status.blocked_reason = reason
        frame = SimpleNamespace(continuity=continuity, at_ms=at_ms, reason=reason)
        self.frames.append(frame)
        return (frame,)

    def pending_frames(self):
        return tuple(self.frames)


def test_book_queue_is_persisted_before_acknowledgement():
    frame = Frame()
    recorder = Recorder([frame])
    repository = Repository()
    asyncio.run(capture.persist_pending_books(recorder, repository))
    assert repository.persisted == [frame]
    assert recorder.acked == [frame.frame_sha256]


def test_book_storage_failure_does_not_acknowledge_queue_head():
    frame = Frame()
    recorder = Recorder([frame])
    with pytest.raises(RuntimeError, match="storage failure"):
        asyncio.run(capture.persist_pending_books(recorder, Repository(fail=True)))
    assert recorder.acked == []
    assert recorder.pending_frames() == (frame,)


def test_barrier_is_durable_then_refuses_capture():
    frame = Frame(continuity="GAP")
    recorder = Recorder([frame])
    repository = Repository()
    with pytest.raises(capture.CaptureRefused, match="PUBLIC_BOOK_SOURCE_BARRIER"):
        asyncio.run(capture.persist_pending_books(recorder, repository))
    assert repository.persisted == [frame]
    assert recorder.acked == [frame.frame_sha256]


def test_closed_bar_gap_or_staleness_is_refused_without_ack():
    candle = SimpleNamespace(
        symbol="btcusdt",
        open_time_ms=60_000,
        close_time_ms=119_999,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        base_volume=2.0,
        quote_volume=200.0,
        taker_buy_base_volume=1.0,
        taker_buy_quote_volume=100.0,
    )
    collector = BarCollector(candle, safe=False)
    with pytest.raises(capture.CaptureRefused, match="CLOSED_BAR_STREAM_GAP"):
        asyncio.run(
            capture.persist_pending_bars(
                collector,
                BarRepository(),
                "tape",
                started_at_ms=0,
                now_ms=120_000,
                captured_symbols=set(),
                latest_bar_close_time_ms={},
                add_evidence_bytes=lambda _size: None,
            )
        )
    assert collector.acknowledged == []

    collector = BarCollector(candle)
    with pytest.raises(capture.CaptureRefused, match="CLOSED_BAR_STALE_OR_FUTURE"):
        asyncio.run(
            capture.persist_pending_bars(
                collector,
                BarRepository(),
                "tape",
                started_at_ms=0,
                now_ms=300_000,
                captured_symbols=set(),
                latest_bar_close_time_ms={},
                add_evidence_bytes=lambda _size: None,
            )
        )
    assert collector.acknowledged == []


def test_closed_bar_repository_gap_does_not_acknowledge():
    candle = SimpleNamespace(
        symbol="btcusdt",
        open_time_ms=60_000,
        close_time_ms=119_999,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        base_volume=2.0,
        quote_volume=200.0,
        taker_buy_base_volume=1.0,
        taker_buy_quote_volume=100.0,
    )
    collector = BarCollector(candle)
    with pytest.raises(ValueError, match="contiguous prefix"):
        asyncio.run(
            capture.persist_pending_bars(
                collector,
                BarRepository(fail=True),
                "tape",
                started_at_ms=0,
                now_ms=120_000,
                captured_symbols=set(),
                latest_bar_close_time_ms={},
                add_evidence_bytes=lambda _size: None,
            )
        )
    assert collector.acknowledged == []


def test_five_symbol_coverage_rejects_missing_gap_or_stale_inputs():
    symbols = capture.SYMBOLS
    times = {symbol: 99_000 for symbol in symbols}
    capture.require_complete_coverage(
        expected_symbols=symbols,
        captured_bar_symbols=set(symbols),
        latest_bar_close_time_ms={symbol: 99_000 for symbol in symbols},
        latest_book_received_at_ms=times,
        now_ms=100_000,
    )
    with pytest.raises(capture.CaptureRefused, match="FRESH_BAR"):
        capture.require_complete_coverage(
            expected_symbols=symbols,
            captured_bar_symbols=set(symbols[:-1]),
            latest_bar_close_time_ms={symbol: 99_000 for symbol in symbols},
            latest_book_received_at_ms=times,
            now_ms=100_000,
        )
    stale = dict(times)
    stale[symbols[0]] = 90_000
    with pytest.raises(capture.CaptureRefused, match="FRESH_BOOK"):
        capture.require_complete_coverage(
            expected_symbols=symbols,
            captured_bar_symbols=set(symbols),
            latest_bar_close_time_ms={symbol: 99_000 for symbol in symbols},
            latest_book_received_at_ms=stale,
            now_ms=100_000,
        )

    with pytest.raises(capture.CaptureRefused, match="FRESH_CLOSED_BAR"):
        capture.require_complete_coverage(
            expected_symbols=symbols,
            captured_bar_symbols=set(symbols),
            latest_bar_close_time_ms={symbol: 1_000 for symbol in symbols},
            latest_book_received_at_ms=times,
            now_ms=100_000,
        )


def test_book_byte_cap_terminates_with_a_barrier():
    recorder = capture.make_bounded_book_recorder(
        tape_id="capture-test",
        symbols=capture.SYMBOLS,
        source="test",
        max_pending_frames=4,
        byte_limit=4,
        recorder_base=RecorderBaseFake,
    )
    recorder.begin_public_stream(connected_at_ms=100)
    with pytest.raises(capture.CaptureRefused, match="EVIDENCE_BYTE_LIMIT"):
        recorder.capture_depth(
            raw_payload="12345",
            symbol="BTCUSDT",
            exchange_update_id=1,
            exchange_at_ms=100,
            received_at_ms=100,
            bids=[(100.0, 1.0)],
            asks=[(101.0, 1.0)],
        )
    assert recorder.status.state == "BLOCKED"
    assert recorder.pending_frames()[0].continuity == "UNKNOWN"


def test_capture_coordinator_stops_producers_before_final_drain_and_seal():
    async def run():
        now_ms = int(time.time() * 1_000)
        close_time_ms = (now_ms // 60_000) * 60_000 - 1
        candle = SimpleNamespace(
            symbol="btcusdt",
            open_time_ms=close_time_ms - 59_999,
            close_time_ms=close_time_ms,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            base_volume=2.0,
            quote_volume=200.0,
            taker_buy_base_volume=1.0,
            taker_buy_quote_volume=100.0,
        )
        collector = FinalizeCollector(candle)
        book_frame = Frame()
        book_frame.symbol = "BTCUSDT"
        book_frame.received_at_ms = now_ms - 1_000
        recorder = FinalizeRecorder(frames=(book_frame,))
        producer_stopped = asyncio.Event()

        async def producer(*, marks_close=False):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                if marks_close and recorder.planned_stop_requested:
                    recorder.planned_stop_barrier_seen = True
                producer_stopped.set()
                raise

        collector_task = asyncio.create_task(producer(marks_close=True), name="fake-collector")
        reconcile_task = asyncio.create_task(producer(), name="fake-reconcile")
        await asyncio.sleep(0)
        repository = FinalizeRepository(producer_tasks=(collector_task, reconcile_task))
        symbols = set(capture.SYMBOLS)
        latest_bars = {symbol: now_ms - 10_000 for symbol in symbols}
        latest_books = {symbol: now_ms - 1_000 for symbol in symbols}
        seal, bars, books = await capture.finalize_capture(
            collector=collector,
            recorder=recorder,
            repository=repository,
            collector_task=collector_task,
            reconciliation_task=reconcile_task,
            tape_id="capture-test",
            started_at_ms=0,
            captured_bar_symbols=symbols,
            latest_bar_close_time_ms=latest_bars,
            latest_persisted_book_received_at_ms=latest_books,
        )
        assert producer_stopped.is_set()
        assert collector_task.done() and reconcile_task.done()
        assert repository.sealed
        assert repository.producers_stopped_at_seal
        assert seal.tape_sha256 == "seal-hash"
        assert bars == 1 and books == 1
        assert len(repository.bars) == 1 and len(repository.books) == 1
        assert dict(collector.acknowledged)["btcusdt"] == 1
        assert all(count == 0 for symbol, count in collector.acknowledged if symbol != "btcusdt")
        assert recorder.acked == [book_frame.frame_sha256]

    asyncio.run(run())


def test_capture_cancellation_without_expected_close_never_seals():
    async def run():
        recorder = FinalizeRecorder()
        recorder._planned_stop_barrier = False
        stopped = asyncio.Event()
        collector = FinalizeCollector()

        async def producer(*, marks_close=False):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                if marks_close and recorder.planned_stop_requested and recorder._planned_stop_barrier:
                    recorder.planned_stop_barrier_seen = True
                stopped.set()
                raise

        collector_task = asyncio.create_task(producer(), name="fake-collector")
        reconcile_task = asyncio.create_task(producer(), name="fake-reconcile")
        await asyncio.sleep(0)
        repository = FinalizeRepository()
        now_ms = int(time.time() * 1_000)
        symbols = set(capture.SYMBOLS)
        with pytest.raises(capture.CaptureRefused, match="CLOSE_NOT_CONFIRMED"):
            await capture.finalize_capture(
                collector=collector,
                recorder=recorder,
                repository=repository,
                collector_task=collector_task,
                reconciliation_task=reconcile_task,
                tape_id="capture-test",
                started_at_ms=0,
                captured_bar_symbols=symbols,
                latest_bar_close_time_ms={symbol: now_ms - 10_000 for symbol in symbols},
                latest_persisted_book_received_at_ms={symbol: now_ms - 1_000 for symbol in symbols},
            )
        assert stopped.is_set()
        assert collector_task.done() and reconcile_task.done()
        assert not repository.sealed

    asyncio.run(run())


def test_cli_total_timeout_cancels_operation_and_reports_no_seal(monkeypatch):
    cleaned = asyncio.Event()

    async def fake_bounded_operation(_args, *, cleanup_budget_s):
        assert cleanup_budget_s > 0
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaned.set()
            raise

    monkeypatch.setattr(capture, "_execute_bounded", fake_bounded_operation)
    args = SimpleNamespace(seconds=0.2)
    with pytest.raises(capture.CaptureRefused, match="CAPTURE_TOTAL_DEADLINE_NO_SEAL"):
        asyncio.run(capture._execute(args))
    assert cleaned.is_set()
