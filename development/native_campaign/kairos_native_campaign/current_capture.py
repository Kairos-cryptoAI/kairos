"""Finite, read-only public inputs for a single present-time research chain.

This adapter retains exact HTTP bodies and local request/receive/persist clocks.
It does not start Kairos services, write a database, call a model, or submit orders.
Its source claims are intentionally narrow: one captured RSS document set, public
Binance USD-M REST snapshots, and the exact bars returned for one current window.
None of these receipts establish publisher authenticity or historical availability.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

UNIVERSE = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
TEXT_FEED = "https://cointelegraph.com/rss"  # existing Text Scouts RSS configuration
TEXT_SOURCE_ID = "cointelegraph_rss"
TEXT_FEEDS = {
    TEXT_FEED: (TEXT_SOURCE_ID, "cointelegraph.com", "cointelegraph-rss", "ct"),
    "https://www.coindesk.com/arc/outboundfeeds/rss/": (
        "coindesk_rss",
        "www.coindesk.com",
        "coindesk-rss",
        "cd",
    ),
    # Exact canonical path observed in the configured endpoint's 308 response.
    # Other redirects, endpoints and hosts are not followed.
    "https://www.coindesk.com/arc/outboundfeeds/rss": (
        "coindesk_rss",
        "www.coindesk.com",
        "coindesk-rss",
        "cd",
    ),
}
TEXT_TTL_MS = 30 * 60 * 1_000
TEXT_COVERAGE_SCOPE = "ALL_ITEMS_IN_THIS_CAPTURED_RSS_SNAPSHOT"
MARKET_SOURCE_ID = "binance_um_rest_depth_snapshot"
MARKET_TTL_MS = 5_000
BAR_COUNT = 54 * 60
BAR_MS = 60_000
PAGE_LIMIT = 1_500
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_QUOTE_BYTES = 64 * 1024
MAX_CAPTURE_BYTES = 32 * 1024 * 1024
MAX_CAPTURE_SECONDS = 120.0
REQUEST_TIMEOUT_SECONDS = 15.0
MAX_RSS_ITEMS = 500
MAX_REQUESTS = 40
PARSER_VERSION = "current-rss-source-v1"


class CaptureRefused(ValueError):
    """A bounded current-source capture failed closed."""


@dataclass(frozen=True, slots=True)
class HTTPResponse:
    """One complete bounded response from the transport boundary."""

    url: str
    status: int
    body: bytes
    content_length: int | None = None
    content_encoding: str | None = None


@dataclass(frozen=True, slots=True)
class CapturedTextSnapshot:
    source_name: str
    raw_body: bytes
    raw_sha256: str
    requested_ms: int
    received_ms: int
    persisted_ms: int
    news_items: tuple[Any, ...]
    events: tuple[Any, ...]
    item_ids: tuple[str, ...]
    coverage_scope: str
    receipt_path: Path

    @property
    def text_source(self) -> CapturedRSSSource:
        """Adapter that gives TextScoutsService only this retained, already-fetched set."""

        return CapturedRSSSource(self.news_items)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            _canonical_bytes(
                {
                    "source_name": self.source_name,
                    "raw_sha256": self.raw_sha256,
                    "requested_ms": self.requested_ms,
                    "received_ms": self.received_ms,
                    "persisted_ms": self.persisted_ms,
                    "item_ids": list(self.item_ids),
                    "coverage_scope": self.coverage_scope,
                }
            )
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class CapturedRSSSource:
    """No-network Text Scouts source bound to an actual retained RSS snapshot."""

    items: tuple[Any, ...]
    name: str = "captured-rss"
    enabled: bool = True

    async def fetch(self) -> list[Any]:
        return list(self.items)


@dataclass(frozen=True, slots=True)
class RawPageReceipt:
    source_id: str
    symbol: str
    page: int
    url: str
    raw_body: bytes
    raw_sha256: str
    requested_ms: int
    received_ms: int
    persisted_ms: int
    row_count: int
    receipt_path: Path


@dataclass(frozen=True, slots=True)
class FreshQuoteSnapshot:
    symbol: str
    entry_quote: Any
    raw_body: bytes
    raw_sha256: str
    requested_ms: int
    received_ms: int
    captured_ms: int
    bid_quantity: float
    ask_quantity: float
    receipt_path: Path

    @property
    def persisted_ms(self) -> int:
        return self.captured_ms


@dataclass(frozen=True, slots=True)
class CurrentHistorySnapshot:
    cut_ms: int
    captured_ms: int
    bars_by_symbol: dict[str, tuple[Any, ...]]
    page_receipts: tuple[RawPageReceipt, ...]
    coverage_scope: str


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _ensure_source_packages() -> None:
    """Expose the two sibling source packages without installing or modifying them."""

    repo_root = Path(__file__).resolve().parents[3]
    package_roots = (
        repo_root / "development" / "adaptive_replay",
        repo_root.parent / "kairos-text-scouts",
    )
    for package_root in package_roots:
        if package_root.is_dir() and str(package_root) not in sys.path:
            sys.path.insert(0, str(package_root))


def _ms_datetime(value: datetime) -> int:
    if value.tzinfo is None:
        raise CaptureRefused("RSS_PUBLICATION_TIMEZONE_REQUIRED")
    return int(value.astimezone(UTC).timestamp() * 1_000)


def _strict_rss_items(
    body: bytes, *, received_ms: int, text_feed: str = TEXT_FEED
) -> tuple[tuple[Any, ...], tuple[str, ...]]:
    """Use the configured Text Scouts RSS parser, then require complete item identity."""

    _ensure_source_packages()
    from defusedxml import ElementTree as SafeET
    from defusedxml.common import DefusedXmlException
    from kairos_text.models import canonical_url
    from kairos_text.sources.rss import RSSSource

    try:
        xml = body.decode("utf-8", errors="strict")
        root = SafeET.fromstring(xml)
    except (UnicodeError, SafeET.ParseError, DefusedXmlException, RecursionError):
        raise CaptureRefused("RSS_XML_INVALID") from None

    def local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].casefold()

    if local_name(root.tag) != "rss" or root.attrib.get("version") != "2.0":
        raise CaptureRefused("RSS_ROOT_NOT_RSS20")
    channels = [node for node in root if local_name(node.tag) == "channel"]
    if len(channels) != 1:
        raise CaptureRefused("RSS_CHANNEL_ROSTER_INVALID")
    raw_items = [node for node in channels[0] if local_name(node.tag) == "item"]
    if len(raw_items) > MAX_RSS_ITEMS:
        raise CaptureRefused("RSS_ITEM_LIMIT_EXCEEDED")
    if text_feed not in TEXT_FEEDS:
        raise CaptureRefused("RSS_FEED_OUTSIDE_EXISTING_CONFIGURATION")
    source_id, host, _stem, _prefix = TEXT_FEEDS[text_feed]
    parsed = RSSSource._parse(xml, text_feed)
    if len(parsed) != len(raw_items):
        raise CaptureRefused("RSS_ITEM_PARSE_INCOMPLETE")

    item_ids: list[str] = []
    for raw_item, item in zip(raw_items, parsed, strict=True):
        fields: dict[str, list[str]] = {}
        for child in raw_item:
            fields.setdefault(local_name(child.tag), []).append("".join(child.itertext()).strip())
        if any(len(fields.get(key, ())) != 1 for key in ("title", "link", "pubdate")):
            raise CaptureRefused("RSS_ITEM_IDENTITY_INVALID")
        link = fields["link"][0]
        parsed_link = urlsplit(link)
        if (
            parsed_link.scheme != "https"
            or parsed_link.hostname != host
            or parsed_link.username is not None
            or parsed_link.password is not None
            or parsed_link.fragment
            or len(link) > 2_048
        ):
            raise CaptureRefused("RSS_ITEM_LINK_OUTSIDE_ALLOWLIST")
        try:
            published = parsedate_to_datetime(fields["pubdate"][0])
        except (TypeError, ValueError, OverflowError):
            published = None
        if published is None or published.tzinfo is None:
            raise CaptureRefused("RSS_PUBLICATION_TIMEZONE_REQUIRED")
        published_ms = _ms_datetime(published)
        if published_ms > received_ms:
            raise CaptureRefused("RSS_PUBLICATION_AFTER_LOCAL_RECEIPT")
        canonical_identity = canonical_url(link)
        if not canonical_identity or item.url != link or item.title != fields["title"][0]:
            raise CaptureRefused("RSS_SOURCE_PARSER_IDENTITY_MISMATCH")
        item.provenance = (canonical_identity,)
        item_id = hashlib.sha256((source_id + "\0" + canonical_identity).encode()).hexdigest()
        item_ids.append(item_id)
    if len(set(item_ids)) != len(item_ids):
        raise CaptureRefused("RSS_DUPLICATE_CANONICAL_EVENT")
    return tuple(parsed), tuple(item_ids)


def _new_capture_dir(output_root: Path) -> tuple[Path, str]:
    root = Path(output_root).absolute()
    for component in (*reversed(root.parents), root):
        try:
            info = component.lstat()
        except OSError:
            raise CaptureRefused("OUTPUT_ROOT_MUST_EXIST") from None
        if component.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise CaptureRefused("OUTPUT_ROOT_CANNOT_TRAVERSE_LINKS")
    if not root.is_dir():
        raise CaptureRefused("OUTPUT_ROOT_MUST_BE_A_REAL_DIRECTORY")
    capture_id = str(uuid.uuid4())
    path = root / f"current-public-capture-{capture_id}"
    try:
        path.mkdir()
    except OSError:
        raise CaptureRefused("CAPTURE_DIRECTORY_MUST_BE_NEW") from None
    return path, capture_id


def _write_raw(
    directory: Path,
    name: str,
    body: bytes,
    *,
    persisted_clock: Callable[[], int] | None = None,
) -> tuple[Path, int]:
    if Path(name).name != name or not body:
        raise CaptureRefused("RAW_MEMBER_NAME_OR_BODY_INVALID")
    path = directory / name
    try:
        with path.open("xb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise CaptureRefused("RAW_MEMBER_CREATE_ONLY_WRITE_FAILED") from None
    return path, (persisted_clock or (lambda: time.time_ns() // 1_000_000))()


def _write_receipt(directory: Path, name: str, value: dict[str, Any]) -> Path:
    path = directory / name
    payload = _canonical_bytes(value) + b"\n"
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise CaptureRefused("RECEIPT_CREATE_ONLY_WRITE_FAILED") from None
    return path


async def _bounded_https_get(url: str, *, timeout_s: float, byte_limit: int) -> HTTPResponse:
    """Default no-redirect/no-proxy HTTPS GET transport; no credentials or retries."""

    import aiohttp

    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in {
        "cointelegraph.com",
        "www.coindesk.com",
        "fapi.binance.com",
    }:
        raise CaptureRefused("URL_OUTSIDE_FIXED_HTTPS_ALLOWLIST")
    timeout = aiohttp.ClientTimeout(total=timeout_s, connect=min(timeout_s, 5.0), sock_read=timeout_s)
    async with aiohttp.ClientSession(
        timeout=timeout,
        trust_env=False,
        auto_decompress=False,
        headers={"User-Agent": "Kairos-current-public-capture/1.0", "Accept-Encoding": "identity"},
    ) as session:
        async with session.get(
            url,
            allow_redirects=False,
            proxy=None,
            headers={"Accept-Encoding": "identity"},
        ) as response:
            final_url = str(response.url)
            declared_raw = response.headers.get("Content-Length")
            declared = int(declared_raw) if declared_raw is not None and declared_raw.isdecimal() else None
            if declared_raw is not None and declared is None:
                raise CaptureRefused("HTTP_CONTENT_LENGTH_INVALID")
            if declared is not None and declared > byte_limit:
                raise CaptureRefused("HTTP_BODY_LIMIT_EXCEEDED")
            encoding = response.headers.get("Content-Encoding", "identity").casefold()
            if encoding not in {"", "identity"}:
                raise CaptureRefused("HTTP_CONTENT_ENCODING_UNSUPPORTED")
            body = bytearray()
            async for chunk in response.content.iter_chunked(64 * 1024):
                if len(body) + len(chunk) > byte_limit:
                    raise CaptureRefused("HTTP_BODY_LIMIT_EXCEEDED")
                body.extend(chunk)
            if declared is not None and len(body) != declared:
                raise CaptureRefused("HTTP_BODY_LENGTH_MISMATCH")
            return HTTPResponse(final_url, int(response.status), bytes(body), declared, encoding)


class CurrentPublicCapture:
    """One shared 32 MiB / 120 s capture budget for the approved public endpoints."""

    def __init__(
        self,
        output_root: Path,
        *,
        deadline_seconds: float = MAX_CAPTURE_SECONDS,
        byte_limit: int = MAX_CAPTURE_BYTES,
        wall_ms_fn: Callable[[], int] | None = None,
        monotonic_fn: Callable[[], float] = time.monotonic,
        transport: Callable[..., Any] | None = None,
        text_feed: str = TEXT_FEED,
    ) -> None:
        if type(deadline_seconds) not in {int, float} or not 0 < deadline_seconds <= MAX_CAPTURE_SECONDS:
            raise ValueError("deadline must be in (0, 120] seconds")
        if type(byte_limit) is not int or not 1 <= byte_limit <= MAX_CAPTURE_BYTES:
            raise ValueError("capture byte limit must be in [1, 32 MiB]")
        if text_feed not in TEXT_FEEDS:
            raise ValueError("only existing configured RSS feeds are allowed")
        self.text_feed = text_feed
        self.text_source_id, self.text_host, self.text_stem, self.text_prefix = TEXT_FEEDS[text_feed]
        self.capture_dir, self.capture_id = _new_capture_dir(Path(output_root))
        self.deadline_seconds = float(deadline_seconds)
        self.byte_limit = byte_limit
        self.wall_ms_fn = wall_ms_fn or (lambda: time.time_ns() // 1_000_000)
        self.monotonic_fn = monotonic_fn
        self.transport = transport or _bounded_https_get
        self.started_monotonic = monotonic_fn()
        self.started_ms = self.wall_ms_fn()
        self.bytes_used = 0
        self.requests = 0
        self._text: CapturedTextSnapshot | None = None
        self._history: dict[int, CurrentHistorySnapshot] = {}
        self._quote_counts: dict[str, int] = {}

    def _remaining(self) -> float:
        remaining = self.deadline_seconds - (self.monotonic_fn() - self.started_monotonic)
        if remaining <= 0:
            raise CaptureRefused("CAPTURE_DEADLINE_EXCEEDED")
        return remaining

    async def _request(self, url: str, *, max_response_bytes: int) -> tuple[HTTPResponse, int, int]:
        remaining = self._remaining()
        remaining_bytes = self.byte_limit - self.bytes_used
        if remaining_bytes <= 0:
            raise CaptureRefused("CAPTURE_BYTE_LIMIT_EXCEEDED")
        request_ms = self.wall_ms_fn()
        self.requests += 1
        if self.requests > MAX_REQUESTS:
            raise CaptureRefused("REQUEST_COUNT_LIMIT_EXCEEDED")
        try:
            async with asyncio.timeout(min(REQUEST_TIMEOUT_SECONDS, remaining)):
                response = await self.transport(
                    url,
                    timeout_s=min(REQUEST_TIMEOUT_SECONDS, remaining),
                    byte_limit=min(max_response_bytes, remaining_bytes),
                )
        except TimeoutError:
            raise CaptureRefused("HTTP_REQUEST_TIMEOUT") from None
        self._remaining()
        if type(response) is not HTTPResponse or type(response.body) is not bytes:
            raise CaptureRefused("HTTP_TRANSPORT_RESPONSE_INVALID")
        if response.url != url or response.status != 200 or not response.body:
            raise CaptureRefused("HTTP_STATUS_OR_REDIRECT_REJECTED")
        if len(response.body) > max_response_bytes or len(response.body) > remaining_bytes:
            raise CaptureRefused("HTTP_BODY_LIMIT_EXCEEDED")
        if response.content_length is not None and response.content_length != len(response.body):
            raise CaptureRefused("HTTP_BODY_LENGTH_MISMATCH")
        if response.content_encoding not in (None, "", "identity"):
            raise CaptureRefused("HTTP_CONTENT_ENCODING_UNSUPPORTED")
        self.bytes_used += len(response.body)
        if self.bytes_used > self.byte_limit:
            raise CaptureRefused("CAPTURE_BYTE_LIMIT_EXCEEDED")
        received_ms = self.wall_ms_fn()
        if received_ms < request_ms:
            raise CaptureRefused("LOCAL_WALL_CLOCK_REGRESSION")
        return response, request_ms, received_ms

    def _persist(self, name: str, body: bytes, *, received_ms: int) -> tuple[Path, int, str]:
        path, persisted_ms = _write_raw(self.capture_dir, name, body, persisted_clock=self.wall_ms_fn)
        if persisted_ms < received_ms:
            raise CaptureRefused("LOCAL_WALL_CLOCK_REGRESSION")
        return path, persisted_ms, hashlib.sha256(body).hexdigest()

    async def capture_text(self) -> CapturedTextSnapshot:
        """Capture one complete existing configured RSS snapshot and fresh items only."""

        if self._text is not None:
            return self._text
        response, requested_ms, received_ms = await self._request(
            self.text_feed, max_response_bytes=MAX_TEXT_BYTES
        )
        items, item_ids = _strict_rss_items(response.body, received_ms=received_ms, text_feed=self.text_feed)
        raw_path, persisted_ms, raw_sha = self._persist(
            self.text_stem + ".raw", response.body, received_ms=received_ms
        )
        freshness_floor = received_ms - TEXT_TTL_MS
        fresh_pairs = tuple(
            (item, item_id)
            for item, item_id in zip(items, item_ids, strict=True)
            if freshness_floor <= int(item.published_at.astimezone(UTC).timestamp() * 1_000) <= received_ms
        )
        _ensure_source_packages()
        from adaptive_replay.catalyst_policy_v1 import CatalystEvent
        from adaptive_replay.historical_context import HistoricalVersion, canonical, digest

        parser_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        events = []
        for item, item_id in fresh_pairs:
            published_ms = int(item.published_at.astimezone(UTC).timestamp() * 1_000)
            payload_json = canonical({"headline": item.title, "body": item.body})
            version_digest = hashlib.sha256(
                (self.text_source_id + "\0" + item_id + "\0" + raw_sha + "\0" + payload_json).encode()
            ).hexdigest()
            version = HistoricalVersion(
                record_id=f"{self.text_prefix}-{version_digest[:32]}",
                document_id=f"{self.text_prefix}-{item_id[:32]}",
                source_name=self.text_source_id,
                kind="NEWS",
                symbols=tuple(sorted(UNIVERSE)),
                url=item.url,
                payload_json=payload_json,
                raw_content_sha256=raw_sha,
                extraction_policy_sha256=digest(
                    {"parser_version": PARSER_VERSION, "parser_sha256": parser_sha}
                ),
                published_lower_ms=published_ms,
                published_upper_ms=published_ms,
                version_available_ms=persisted_ms,
                captured_ms=persisted_ms,
                proof_kind="CONTEMPORANEOUS_LOCAL",
                proof_sha256=digest(
                    {
                        "capture_id": self.capture_id,
                        "raw_sha256": raw_sha,
                        "item_id": item_id,
                        "requested_ms": requested_ms,
                        "received_ms": received_ms,
                        "persisted_ms": persisted_ms,
                        "coverage_scope": TEXT_COVERAGE_SCOPE,
                    }
                ),
            )
            events.append(
                CatalystEvent(
                    self.text_source_id,
                    f"{self.text_prefix}-event-{item_id[:32]}",
                    version,
                    received_ms,
                    TEXT_TTL_MS,
                )
            )
        receipt = {
            "schema": "kairos.current-public-rss-capture.v1",
            "capture_id": self.capture_id,
            "capture_started_ms": self.started_ms,
            "source_id": self.text_source_id,
            "url": self.text_feed,
            "raw_file": raw_path.name,
            "raw_sha256": raw_sha,
            "bytes": len(response.body),
            "requested_ms": requested_ms,
            "received_ms": received_ms,
            "persisted_ms": persisted_ms,
            "parser_version": PARSER_VERSION,
            "parser_sha256": parser_sha,
            "raw_item_count": len(items),
            "fresh_item_count": len(fresh_pairs),
            "item_ids": list(item_ids),
            "coverage_scope": TEXT_COVERAGE_SCOPE,
            "coverage_status": "KNOWN_WITHIN_ONE_COMPLETE_CAPTURED_RSS_SNAPSHOT_ONLY",
            "first_receipt_scope": "FIRST_LOCAL_RECEIPT_IN_THIS_CAPTURE_ONLY",
            "interval_coverage": False,
            "all_world_news_complete": False,
            "historical_availability_proven": False,
            "publisher_authenticity_verified": False,
            "paid_api_calls": 0,
            "request_count": self.requests,
            "cumulative_ingress_bytes": self.bytes_used,
        }
        receipt_path = _write_receipt(self.capture_dir, self.text_stem + ".receipt.json", receipt)
        self._text = CapturedTextSnapshot(
            self.text_source_id,
            response.body,
            raw_sha,
            requested_ms,
            received_ms,
            persisted_ms,
            tuple(item for item, _ in fresh_pairs),
            tuple(events),
            item_ids,
            TEXT_COVERAGE_SCOPE,
            receipt_path,
        )
        return self._text

    async def fetch_history(self, cut_ms: int) -> CurrentHistorySnapshot:
        """Fetch exactly 54 hours of closed 1m bars per fixed symbol, retaining pages.

        The supplied cut is only an upper bound on price event time. To use local
        as-of evidence, the caller must select a decision cut no earlier than the
        final returned capture clock; this function does not backdate receipt.
        """

        if type(cut_ms) is not int or cut_ms < 0:
            raise ValueError("cut_ms must be a nonnegative integer")
        if cut_ms < BAR_COUNT * BAR_MS:
            raise ValueError("cut_ms is too early for a nonnegative 54-hour 1m window")
        if cut_ms in self._history:
            return self._history[cut_ms]
        if self._history:
            raise CaptureRefused("ONE_HISTORY_WINDOW_PER_CAPTURE")
        _ensure_source_packages()

        last_open = (cut_ms // BAR_MS) * BAR_MS - BAR_MS
        first_open = last_open - (BAR_COUNT - 1) * BAR_MS
        expected_opens = tuple(first_open + index * BAR_MS for index in range(BAR_COUNT))
        pages: list[RawPageReceipt] = []
        bars_by_symbol: dict[str, tuple[Any, ...]] = {}
        capture_clock = self.wall_ms_fn()
        for symbol in UNIVERSE:
            rows_by_open: dict[int, Any] = {}
            page_number = 0
            offset = 0
            while offset < BAR_COUNT:
                count = min(PAGE_LIMIT, BAR_COUNT - offset)
                page_start = first_open + offset * BAR_MS
                page_end = page_start + count * BAR_MS - 1
                query = urlencode(
                    {
                        "symbol": symbol,
                        "interval": "1m",
                        "startTime": str(page_start),
                        "endTime": str(page_end),
                        "limit": str(count),
                    }
                )
                url = f"https://fapi.binance.com/fapi/v1/klines?{query}"
                response, requested_ms, received_ms = await self._request(
                    url, max_response_bytes=MAX_PAGE_BYTES
                )
                try:
                    decoded = json.loads(response.body.decode("utf-8", errors="strict"))
                except (UnicodeError, json.JSONDecodeError, RecursionError):
                    raise CaptureRefused("KLINE_JSON_INVALID") from None
                if type(decoded) is not list or len(decoded) != count:
                    raise CaptureRefused("KLINE_PAGE_ROW_COUNT_MISMATCH")
                for index, raw_row in enumerate(decoded):
                    expected_open = page_start + index * BAR_MS
                    candle = _parse_candle_row(symbol, raw_row, expected_open=expected_open)
                    if candle.close_time_ms >= cut_ms or candle.open_time_ms in rows_by_open:
                        raise CaptureRefused("KLINE_FUTURE_OR_DUPLICATE_ROW")
                    rows_by_open[candle.open_time_ms] = candle
                page_number += 1
                file_name = f"bars-{symbol.lower()}-page-{page_number:02d}.raw"
                raw_path, persisted_ms, raw_sha = self._persist(
                    file_name, response.body, received_ms=received_ms
                )
                page_receipt = {
                    "schema": "kairos.current-public-market-page.v1",
                    "capture_id": self.capture_id,
                    "capture_started_ms": self.started_ms,
                    "source_id": "binance_um_klines_rest",
                    "symbol": symbol,
                    "interval": "1m",
                    "url": url,
                    "raw_file": raw_path.name,
                    "raw_sha256": raw_sha,
                    "bytes": len(response.body),
                    "row_count": len(decoded),
                    "requested_ms": requested_ms,
                    "received_ms": received_ms,
                    "persisted_ms": persisted_ms,
                    "cut_ms": cut_ms,
                    "coverage_scope": "EXACT_54H_REQUESTED_WINDOW_ONLY",
                    "gap_free": True,
                    "request_count": self.requests,
                    "cumulative_ingress_bytes": self.bytes_used,
                }
                receipt_path = _write_receipt(
                    self.capture_dir,
                    f"bars-{symbol.lower()}-page-{page_number:02d}.receipt.json",
                    page_receipt,
                )
                pages.append(
                    RawPageReceipt(
                        "binance_um_klines_rest",
                        symbol,
                        page_number,
                        url,
                        response.body,
                        raw_sha,
                        requested_ms,
                        received_ms,
                        persisted_ms,
                        len(decoded),
                        receipt_path,
                    )
                )
                capture_clock = max(capture_clock, persisted_ms)
                offset += count
            if tuple(sorted(rows_by_open)) != expected_opens:
                raise CaptureRefused("KLINE_COVERAGE_NOT_CONTIGUOUS")
            candles = tuple(rows_by_open[open_ms] for open_ms in expected_opens)
            if len(candles) != BAR_COUNT:
                raise CaptureRefused("KLINE_COVERAGE_ROW_COUNT_MISMATCH")
            bars_by_symbol[symbol] = candles
        current_ms = self.wall_ms_fn()
        latest_close = last_open + BAR_MS - 1
        if latest_close > cut_ms or current_ms < latest_close or current_ms - latest_close > 90_000:
            raise CaptureRefused("KLINE_LAST_CLOSED_BAR_NOT_CURRENT")
        snapshot = CurrentHistorySnapshot(
            cut_ms,
            capture_clock,
            bars_by_symbol,
            tuple(pages),
            "FIVE_SYMBOLS_EXACT_54H_CLOSED_1M_BARS_AT_CAPTURE_ONLY",
        )
        self._history[cut_ms] = snapshot
        return snapshot

    async def fresh_quote(self, symbol: str) -> FreshQuoteSnapshot:
        """Capture one public REST depth snapshot; never claim websocket continuity."""

        if symbol not in UNIVERSE:
            raise ValueError("symbol must belong to the fixed five-symbol universe")
        sequence = self._quote_counts.get(symbol, 0) + 1
        self._quote_counts[symbol] = sequence
        query = urlencode({"symbol": symbol, "limit": "5"})
        url = f"https://fapi.binance.com/fapi/v1/depth?{query}"
        response, requested_ms, received_ms = await self._request(url, max_response_bytes=MAX_QUOTE_BYTES)
        try:
            value = json.loads(response.body.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError, RecursionError):
            raise CaptureRefused("DEPTH_JSON_INVALID") from None
        if (
            type(value) is not dict
            or type(value.get("E")) is not int
            or type(value.get("T")) is not int
            or type(value.get("bids")) is not list
            or type(value.get("asks")) is not list
            or not value["bids"]
            or not value["asks"]
        ):
            raise CaptureRefused("DEPTH_SCHEMA_INVALID")
        event_ms = value["E"]
        transaction_ms = value["T"]
        if (
            not 0 <= event_ms <= received_ms
            or not 0 <= transaction_ms <= received_ms
            or received_ms - event_ms > MARKET_TTL_MS
        ):
            raise CaptureRefused("DEPTH_SERVER_EVENT_STALE_OR_FUTURE")
        bid, bid_qty = _positive_decimal_pair(value["bids"][0])
        ask, ask_qty = _positive_decimal_pair(value["asks"][0])
        if bid >= ask:
            raise CaptureRefused("DEPTH_SNAPSHOT_CROSSED")
        raw_path, captured_ms, raw_sha = self._persist(
            f"depth-{symbol.lower()}-{sequence:02d}.raw", response.body, received_ms=received_ms
        )
        _ensure_source_packages()
        from adaptive_replay.quote_capture import PAYLOAD_SCHEMA, BboCapture

        normalized = _canonical_bytes(
            {
                "schema_id": PAYLOAD_SCHEMA,
                "timestamp_unit": "ms",
                "source_id": MARKET_SOURCE_ID,
                "symbol": symbol,
                "event_ms": event_ms,
                "bid": bid,
                "ask": ask,
                "bid_quantity": bid_qty,
                "ask_quantity": ask_qty,
            }
        )
        bbo = BboCapture(
            normalized,
            hashlib.sha256(normalized).hexdigest(),
            received_ms,
            captured_ms,
            MARKET_TTL_MS,
            "CALLER_ATTESTED_POINT_IN_TIME",
        )
        receipt = {
            "schema": "kairos.current-public-depth-capture.v1",
            "capture_id": self.capture_id,
            "capture_started_ms": self.started_ms,
            "source_id": MARKET_SOURCE_ID,
            "symbol": symbol,
            "url": url,
            "raw_file": raw_path.name,
            "raw_sha256": raw_sha,
            "bytes": len(response.body),
            "requested_ms": requested_ms,
            "exchange_event_ms": event_ms,
            "exchange_transaction_ms": transaction_ms,
            "received_ms": received_ms,
            "captured_ms": captured_ms,
            "persisted_ms": captured_ms,
            "best_bid": bid,
            "best_ask": ask,
            "book_type": "ONE_SHOT_REST_DEPTH_SNAPSHOT",
            "continuous_coverage_claimed": False,
            "publisher_authenticity_verified": False,
            "request_count": self.requests,
            "cumulative_ingress_bytes": self.bytes_used,
        }
        receipt_path = _write_receipt(
            self.capture_dir, f"depth-{symbol.lower()}-{sequence:02d}.receipt.json", receipt
        )
        return FreshQuoteSnapshot(
            symbol,
            bbo.quote,
            response.body,
            raw_sha,
            requested_ms,
            received_ms,
            captured_ms,
            bid_qty,
            ask_qty,
            receipt_path,
        )


def _parse_candle_row(symbol: str, row: Any, *, expected_open: int):
    _ensure_source_packages()
    from kairos_strategy.candles import Candle

    if type(row) is not list or len(row) != 12:
        raise CaptureRefused("KLINE_ROW_SCHEMA_INVALID")
    if type(row[0]) not in {str, int} or type(row[6]) not in {str, int}:
        raise CaptureRefused("KLINE_TIMESTAMP_TYPE_INVALID")
    if any(type(row[index]) is not str for index in (1, 2, 3, 4, 5, 7, 9, 10, 11)):
        raise CaptureRefused("KLINE_NUMERIC_TYPE_INVALID")
    try:
        open_ms, close_ms = int(row[0]), int(row[6])
        trade_count = int(row[8])
        numeric = [
            float(Decimal(value))
            for value in (row[1], row[2], row[3], row[4], row[5], row[7], row[9], row[10])
        ]
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        raise CaptureRefused("KLINE_NUMERIC_INVALID") from None
    if (
        open_ms != expected_open
        or close_ms != expected_open + BAR_MS - 1
        or type(row[8]) not in {str, int}
        or trade_count < 0
        or type(row[11]) is not str
        or any(not math.isfinite(number) for number in numeric)
    ):
        raise CaptureRefused("KLINE_TIME_OR_NUMBER_INVALID")
    try:
        return Candle(
            symbol,
            "1m",
            open_ms,
            close_ms,
            numeric[0],
            numeric[1],
            numeric[2],
            numeric[3],
            numeric[4],
            numeric[5],
            numeric[6],
            numeric[7],
        )
    except ValueError:
        raise CaptureRefused("KLINE_OHLCV_INVALID") from None


def _positive_decimal_pair(row: Any) -> tuple[float, float]:
    if type(row) is not list or len(row) != 2 or any(type(value) is not str for value in row):
        raise CaptureRefused("DEPTH_LEVEL_INVALID")
    try:
        price, quantity = float(Decimal(row[0])), float(Decimal(row[1]))
    except (InvalidOperation, ValueError, OverflowError):
        raise CaptureRefused("DEPTH_LEVEL_INVALID") from None
    if not math.isfinite(price) or not math.isfinite(quantity) or price <= 0 or quantity <= 0:
        raise CaptureRefused("DEPTH_LEVEL_INVALID")
    return price, quantity
