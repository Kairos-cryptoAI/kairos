from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from kairos_native_campaign.current_capture import (
    BAR_COUNT,
    BAR_MS,
    MAX_CAPTURE_BYTES,
    UNIVERSE,
    CaptureRefused,
    CurrentPublicCapture,
    HTTPResponse,
    _parse_candle_row,
    _strict_rss_items,
)

BASE_MS = 1_800_000_000_000


def _rss(*, dates: tuple[datetime, ...] | None = None, links: tuple[str, ...] | None = None) -> bytes:
    dates = dates or (datetime.fromtimestamp((BASE_MS - 60_000) / 1000, UTC),)
    links = links or tuple(
        f"https://cointelegraph.com/news/current-bitcoin-story-{index}" for index in range(len(dates))
    )
    items = []
    for index, published in enumerate(dates):
        items.append(
            "<item>"
            f"<title>Current story {index}</title>"
            f"<link>{links[index]}</link>"
            f"<guid>{links[index]}</guid>"
            f"<pubDate>{format_datetime(published)}</pubDate>"
            f"<description>Real public feed item {index}</description>"
            "</item>"
        )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<rss version='2.0'><channel><title>Cointelegraph</title>" + "".join(items) + "</channel></rss>"
    ).encode()


def _depth(symbol: str = "BTCUSDT", *, event_ms: int = BASE_MS) -> bytes:
    del symbol
    return json.dumps(
        {
            "lastUpdateId": 123456,
            "E": event_ms,
            "T": event_ms,
            "bids": [["100.0", "1.25"], ["99.9", "2"]],
            "asks": [["100.1", "1.5"], ["100.2", "3"]],
        },
        separators=(",", ":"),
    ).encode()


class FakeClock:
    def __init__(self, start_ms: int, *, monotonic: float = 0.0):
        self.now_ms = start_ms
        self.monotonic = monotonic

    def wall(self) -> int:
        self.now_ms += 1
        return self.now_ms

    def mono(self) -> float:
        return self.monotonic


class FakeTransport:
    def __init__(self, rss: bytes):
        self.rss = rss
        self.urls: list[str] = []

    async def __call__(self, url: str, *, timeout_s: float, byte_limit: int) -> HTTPResponse:
        assert 0 < timeout_s <= 15
        self.urls.append(url)
        if url == "https://cointelegraph.com/rss":
            body = self.rss
        elif "/fapi/v1/depth?" in url:
            body = _depth()
        else:
            query = parse_qs(urlsplit(url).query)
            start = int(query["startTime"][0])
            limit = int(query["limit"][0])
            rows = []
            for index in range(limit):
                opened = start + index * BAR_MS
                rows.append(
                    [
                        str(opened),
                        "100",
                        "101",
                        "99",
                        "100.5",
                        "5",
                        str(opened + BAR_MS - 1),
                        "502",
                        "12",
                        "2",
                        "200.5",
                        "0",
                    ]
                )
            body = json.dumps(rows, separators=(",", ":")).encode()
        assert len(body) <= byte_limit
        return HTTPResponse(url, 200, body, len(body), "identity")


def _capture(tmp_path: Path, transport, *, clock: FakeClock | None = None) -> CurrentPublicCapture:
    clock = clock or FakeClock(BASE_MS)
    return CurrentPublicCapture(
        tmp_path,
        wall_ms_fn=clock.wall,
        monotonic_fn=clock.mono,
        transport=transport,
    )


@pytest.mark.asyncio
async def test_text_capture_retains_raw_snapshot_and_builds_only_fresh_local_events(tmp_path):
    fresh = datetime.fromtimestamp((BASE_MS - 60_000) / 1000, UTC)
    stale = fresh - timedelta(minutes=31)
    raw = _rss(dates=(fresh, stale))
    transport = FakeTransport(raw)
    snapshot = await _capture(tmp_path, transport).capture_text()

    assert snapshot.raw_body == raw
    assert snapshot.raw_sha256 == hashlib.sha256(raw).hexdigest()
    assert snapshot.coverage_scope == "ALL_ITEMS_IN_THIS_CAPTURED_RSS_SNAPSHOT"
    assert len(snapshot.item_ids) == 2  # stale rows remain in the exact snapshot roster
    assert len(snapshot.news_items) == 1
    assert len(snapshot.events) == 1
    event = snapshot.events[0]
    assert event.version.proof_kind == "CONTEMPORANEOUS_LOCAL"
    assert event.first_received_ms == snapshot.received_ms
    assert event.version.captured_ms == snapshot.persisted_ms
    assert event.version.published_upper_ms <= event.first_received_ms <= event.version.captured_ms
    assert snapshot.receipt_path.is_file()
    receipt = json.loads(snapshot.receipt_path.read_text(encoding="utf-8"))
    assert receipt["coverage_status"] == "KNOWN_WITHIN_ONE_COMPLETE_CAPTURED_RSS_SNAPSHOT_ONLY"
    assert receipt["interval_coverage"] is False
    assert receipt["all_world_news_complete"] is False
    assert receipt["publisher_authenticity_verified"] is False
    assert len(await snapshot.text_source.fetch()) == 1
    assert len(transport.urls) == 1  # TextScoutsService receives retained items, not a second GET.


def test_text_parser_rejects_missing_timezone_and_duplicate_canonical_events():
    no_timezone = (
        b"<rss version='2.0'><channel><item><title>x</title>"
        b"<link>https://cointelegraph.com/news/x</link>"
        b"<pubDate>Wed, 21 Oct 2026 07:28:00</pubDate></item></channel></rss>"
    )
    with pytest.raises(CaptureRefused, match="TIMEZONE"):
        _strict_rss_items(no_timezone, received_ms=BASE_MS)

    duplicate = _rss(
        dates=(datetime.fromtimestamp((BASE_MS - 60_000) / 1000, UTC),) * 2,
        links=(
            "https://cointelegraph.com/news/x?utm_source=a",
            "https://cointelegraph.com/news/x?utm_source=b",
        ),
    )
    with pytest.raises(CaptureRefused, match="DUPLICATE"):
        _strict_rss_items(duplicate, received_ms=BASE_MS)


@pytest.mark.asyncio
async def test_history_fetches_exact_54h_five_symbol_gap_free_closed_bars_with_raw_pages(tmp_path):
    cut_ms = BASE_MS
    clock = FakeClock(BASE_MS + 30_000)
    transport = FakeTransport(_rss())
    capture = _capture(tmp_path, transport, clock=clock)

    result = await capture.fetch_history(cut_ms)

    assert tuple(result.bars_by_symbol) == UNIVERSE
    assert all(len(result.bars_by_symbol[symbol]) == BAR_COUNT for symbol in UNIVERSE)
    assert len(result.page_receipts) == 15
    assert sum(page.row_count for page in result.page_receipts) == BAR_COUNT * len(UNIVERSE)
    assert all(page.receipt_path.is_file() for page in result.page_receipts)
    for symbol in UNIVERSE:
        rows = result.bars_by_symbol[symbol]
        assert rows[0].open_time_ms + (BAR_COUNT - 1) * BAR_MS == rows[-1].open_time_ms
        assert rows[-1].close_time_ms < cut_ms


@pytest.mark.asyncio
async def test_quote_is_a_rest_snapshot_with_server_and_local_clocks_not_a_continuous_book(tmp_path):
    capture = _capture(tmp_path, FakeTransport(_rss()), clock=FakeClock(BASE_MS + 20))

    quote = await capture.fresh_quote("BTCUSDT")

    assert quote.entry_quote.source_id == "binance_um_rest_depth_snapshot"
    assert quote.entry_quote.evidence_kind == "CALLER_ATTESTED_POINT_IN_TIME"
    assert quote.entry_quote.event_ms <= quote.received_ms <= quote.captured_ms
    assert quote.entry_quote.bid == 100.0
    assert quote.entry_quote.ask == 100.1
    receipt = json.loads(quote.receipt_path.read_text(encoding="utf-8"))
    assert receipt["book_type"] == "ONE_SHOT_REST_DEPTH_SNAPSHOT"
    assert receipt["continuous_coverage_claimed"] is False


def test_closed_bar_parser_rejects_a_gap_and_nonfinite_ohlcv():
    row = ["60000", "100", "101", "99", "100.5", "5", "119999", "502", "12", "2", "200.5", "0"]
    assert _parse_candle_row("BTCUSDT", row, expected_open=60_000).close_time_ms == 119_999
    with pytest.raises(CaptureRefused, match="KLINE_TIME_OR_NUMBER"):
        _parse_candle_row("BTCUSDT", row, expected_open=120_000)
    bad = [*row]
    bad[1] = "NaN"
    with pytest.raises(CaptureRefused):
        _parse_candle_row("BTCUSDT", bad, expected_open=60_000)


def test_constructor_enforces_finite_upper_bounds(tmp_path):
    with pytest.raises(ValueError):
        CurrentPublicCapture(tmp_path, deadline_seconds=120.001)
    with pytest.raises(ValueError):
        CurrentPublicCapture(tmp_path, byte_limit=MAX_CAPTURE_BYTES + 1)
