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
