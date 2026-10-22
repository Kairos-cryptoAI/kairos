from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kairos_native_campaign.current_capture import CurrentPublicCapture, HTTPResponse
from kairos_native_campaign.current_live import CurrentLiveCapture


class _Clock:
    def __init__(self, start_ms: int) -> None:
        self.now_ms = start_ms

    def wall(self) -> int:
        self.now_ms += 1
        return self.now_ms

    @staticmethod
    def mono() -> float:
        return 0.0


class _DepthTransport:
    def __init__(self, event_ms: int) -> None:
        self.event_ms = event_ms

    async def __call__(self, url: str, *, timeout_s: float, byte_limit: int) -> HTTPResponse:
        assert "/fapi/v1/depth?" in url
        assert 0 < timeout_s <= 15
        body = json.dumps(
            {
                "lastUpdateId": self.event_ms,
                "E": self.event_ms,
                "T": self.event_ms,
                "bids": [["100.0", "2.0"]],
                "asks": [["100.1", "3.0"]],
            },
            separators=(",", ":"),
        ).encode()
        assert len(body) <= byte_limit
        return HTTPResponse(url, 200, body, len(body), "identity")


@pytest.mark.asyncio
async def test_trigger_quote_lookup_returns_its_exact_retained_snapshot_not_stale_prefetch(
    tmp_path: Path,
):
    starts = iter((1_800_000_000_000, 1_800_000_060_000, 1_800_000_120_000))
    captures: list[CurrentPublicCapture] = []

    def factory() -> CurrentPublicCapture:
        start_ms = next(starts)
        clock = _Clock(start_ms)
        capture = CurrentPublicCapture(
            tmp_path,
            wall_ms_fn=clock.wall,
            monotonic_fn=clock.mono,
            transport=_DepthTransport(start_ms + 2),
        )
        captures.append(capture)
        return capture

    live = CurrentLiveCapture(
        tmp_path,
        capture=factory(),
        tape_id="current-live-test",
        quote_capture_factory=factory,
    )
    initial = await live.fresh_quote("BTCUSDT")
    trigger = await live.fresh_quote("BTCUSDT")

    decision_ms = trigger.captured_ms
    assert decision_ms - initial.entry_quote.event_ms > initial.entry_quote.ttl_ms
    assert decision_ms - trigger.entry_quote.event_ms <= trigger.entry_quote.ttl_ms
    assert live.quote_snapshot_for(trigger.entry_quote) is trigger
    assert live.quote_snapshot_for(initial.entry_quote) is initial
    assert live.quote_snapshot_for(None) is None
    assert (
        trigger.raw_body
        == json.dumps(
            {
                "lastUpdateId": 1_800_000_120_002,
                "E": 1_800_000_120_002,
                "T": 1_800_000_120_002,
                "bids": [["100.0", "2.0"]],
                "asks": [["100.1", "3.0"]],
            },
            separators=(",", ":"),
        ).encode()
    )
    assert trigger.raw_sha256
    assert len(captures) == 3  # initial budget object plus two captured fixture responses


@pytest.mark.asyncio
async def test_failed_book_receipt_short_circuits_unresolved_market_initial_future(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import kairos_native_campaign.current_live as current_live_module

    capture = CurrentPublicCapture(tmp_path, transport=_DepthTransport(1_800_000_000_002))
    live = CurrentLiveCapture(tmp_path, capture=capture, tape_id="failed-book-test", max_seconds=1)

    async def no_metrics():
        return ()

    async def unresolved_market_stream():
        await asyncio.Event().wait()

    async def failed_book(*_args, **_kwargs):
        return {"state": "FAILED", "reason": "ValueError"}

    live._capture_rest_metrics = no_metrics
    live._capture_market_stream = unresolved_market_stream
    monkeypatch.setattr(current_live_module, "_capture_v2_window", failed_book)

    with pytest.raises(RuntimeError, match="V2_BOOK_CAPTURE_NOT_COMPLETE:ValueError"):
        async with asyncio.timeout(1):
            await live.capture_initial()
    assert live._market_task is not None and live._market_task.done()


@pytest.mark.asyncio
async def test_v2_recorder_window_starts_after_verified_websocket_handshake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import aiohttp
    from adaptive_replay.public_book_capture import ENDPOINT, MAX_GAP_MS

    from kairos_native_campaign.current_live import _capture_v2_window

    invocation_ms = 1_800_000_000_000
    state = {"ms": invocation_ms, "handshake_ms": None}
    started_ns = 5_000_000_000

    def wall_clock() -> int:
        state["ms"] += 100
        return state["ms"]

    def monotonic_clock() -> int:
        return started_ns + (state["ms"] - invocation_ms) * 1_000_000

    class FakeSocket:
        _response = SimpleNamespace(url=ENDPOINT)

        async def __aenter__(self):
            state["ms"] = invocation_ms + 5_200  # DNS/TLS/upgrade startup is outside the V2 window.
            state["handshake_ms"] = state["ms"]
            return self

        async def __aexit__(self, *_args):
            return None

        async def receive(self):
            if not hasattr(self, "symbols"):
                self.symbols = iter(("BNBUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"))
            try:
                symbol = next(self.symbols)
            except StopIteration:
                return SimpleNamespace(type=aiohttp.WSMsgType.CLOSED, data="")
            event_ms = state["ms"]
            payload = {
                "stream": symbol.lower() + "@depth10@100ms",
                "data": {
                    "e": "depthUpdate",
                    "E": event_ms,
                    "T": event_ms,
                    "s": symbol,
                    "ps": symbol,
                    "U": 100,
                    "u": 101,
                    "pu": 99,
                    "b": [["100.0", "2.0"]],
                    "a": [["100.1", "3.0"]],
                    "st": 1,
                },
            }
            return SimpleNamespace(
                type=aiohttp.WSMsgType.TEXT,
                data=json.dumps(payload, separators=(",", ":")),
            )

    class FakeSession:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def ws_connect(self, *_args, **_kwargs):
            return FakeSocket()

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    output = tmp_path / "public-book-capture-20261022-handshake-test"
    receipt = await _capture_v2_window(
        output, seconds=1, wall_clock=wall_clock, monotonic_clock=monotonic_clock
    )

    plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
    handshake = json.loads((output / "handshake-provenance.receipt.json").read_text(encoding="utf-8"))
    raw_rows = [
        json.loads(line) for line in (output / "received.raw.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    bnb_first = next(row for row in raw_rows if json.loads(row["raw_payload"])["data"]["s"] == "BNBUSDT")
    assert plan["started_ms"] >= state["handshake_ms"]
    assert handshake["handshake_completed_ms"] <= handshake["recorder_started_ms"]
    assert handshake["source_receipt_sha256"]
    assert plan["started_ms"] - invocation_ms > MAX_GAP_MS
    assert bnb_first["received_ms"] - plan["started_ms"] <= MAX_GAP_MS
    assert receipt["transport"]["handshake_completed"] is True
    assert receipt["observed_messages"] == receipt["admitted_frames"] == 5
    assert receipt["state"] == "FAILED"  # fake socket then closes before the one-second window seals


def test_completed_quant_metrics_are_facts_not_a_coroutine_and_have_canonical_five_symbol_order(
    tmp_path, monkeypatch
):
    from test_current_inputs import NOW, _metrics

    import kairos_native_campaign.current_live as module

    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
    ended = NOW + 70_000
    monkeypatch.setattr(module.time, "time_ns", lambda: (ended + 2) * 1_000_000)
    live = CurrentLiveCapture(
        tmp_path, capture=CurrentPublicCapture(tmp_path), tape_id="quant-only", max_seconds=70
    )
    completed = live._attach_force_order_metrics(
        tuple((symbol, _metrics(symbol)) for symbol in symbols),
        {
            "window_start_ms": NOW,
            "window_end_ms": ended,
            "last_receive_ms": ended,
            "force_values": {symbol: [0.0, 0.0] for symbol in symbols},
            "force_last_event": {},
            "raw_sha256": "e" * 64,
        },
    )
    assert type(completed) is tuple
    assert tuple(symbol for symbol, _ in completed) == tuple(sorted(symbols))
    assert all(metrics.long_liquidations_usd.window_end_ms == ended for _, metrics in completed)
    assert all(metrics.long_liquidations_usd.complete for _, metrics in completed)


def test_native_segments_keep_original_ids_hashes_and_sequence_roots():
    from kairos_native_campaign.current_live import _latest_complete_native_segment

    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
    original = tuple(
        SimpleNamespace(tape_id="original:0001", symbol=symbol, tape_sequence=index + 1)
        for index, symbol in enumerate(symbols)
    )
    trailing = (SimpleNamespace(tape_id="original:0002", symbol="BTCUSDT", tape_sequence=1),)
    selected = _latest_complete_native_segment(original + trailing)
    assert len(selected) == 5
    assert all(left is right for left, right in zip(selected, original, strict=True))
    with pytest.raises(RuntimeError, match="NO_SINGLE_ORIGINAL_FIVE_SYMBOL_NATIVE_SEGMENT"):
        _latest_complete_native_segment(trailing)


@pytest.mark.asyncio
async def test_actual_market_route_closes_after_retained_boundary_message_and_camel_case_events(
    tmp_path, monkeypatch
):
    import aiohttp

    import kairos_native_campaign.current_live as module

    now = 1_800_000_000_000
    seconds = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: seconds[0])
    monkeypatch.setattr(module.time, "time_ns", lambda: (now + int(seconds[0] * 1000)) * 1_000_000)
    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
    messages = [
        {"stream": symbol.lower() + "@markPrice@1s", "data": {"E": now, "s": symbol}} for symbol in symbols
    ]
    messages.append(
        {
            "stream": "btcusdt@forceOrder",
            "data": {"E": now + 1200, "o": {"ap": "100", "z": "3", "S": "SELL"}},
        }
    )

    class Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def receive(self):
            if not messages:
                return SimpleNamespace(type=aiohttp.WSMsgType.CLOSED, data="")
            seconds[0] += 0.1 if len(messages) > 1 else 0.7
            return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(messages.pop(0)))

    class Session:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def ws_connect(self, *_args, **_kwargs):
            return Socket()

    monkeypatch.setattr(aiohttp, "ClientSession", Session)
    capture = CurrentPublicCapture(tmp_path)
    live = CurrentLiveCapture(
        tmp_path, capture=capture, tape_id="market-window", max_seconds=1, observation_seconds=2
    )
    live._market_initial = asyncio.get_running_loop().create_future()
    with pytest.raises(RuntimeError, match="MARKET_STREAM_CLOSED_OR_NON_TEXT"):
        await live._capture_market_stream()
    result = live._market_initial.result()
    assert result["rows"] == 6
    assert result["window_end_ms"] == result["last_receive_ms"] == now + 1200
    assert result["force_values"]["BTCUSDT"] == [300.0, 0.0]
    assert result["force_last_event"]["BTCUSDT"] == now + 1200
    rows = [json.loads(row) for row in Path(result["raw_path"]).read_text().splitlines()]
    assert [row["sequence"] for row in rows] == list(range(1, 7))
