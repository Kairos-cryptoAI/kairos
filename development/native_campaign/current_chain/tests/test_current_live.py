from __future__ import annotations

import json
from pathlib import Path

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
