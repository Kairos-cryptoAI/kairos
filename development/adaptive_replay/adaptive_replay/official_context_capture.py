"""Opt-in bounded prospective capture of two official public context sources.

The capture records exact response-body bytes and their local observation clock.
It does not establish when a particular version first became available, historical
availability, full news coverage, or trading authority.
"""

from __future__ import annotations

import argparse
import asyncio
import email.utils
import hashlib
import os
import re
import ssl
import stat
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import UTC, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .historical_context import (
    MAX_BYTES as MAX_ARCHIVE_BYTES,
)
from .historical_context import (
    HistoricalArchive,
    HistoricalVersion,
    _json,
    canonical,
    digest,
    import_archive,
)
from .inputs import UNIVERSE

SCHEMA = "kairos.development.official-context-capture.v1"
MAX_BODY_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
MAX_SOURCE_COUNT = 2
MAX_PLAN_BYTES = 64 * 1024
MAX_RECEIPT_BYTES = 256 * 1024
BLS_URL = "https://www.bls.gov/news.release/cpi.htm"
FED_URL = "https://www.federalreserve.gov/feeds/press_monetary.xml"
SOURCES = (
    {
        "source_name": "BLS_CPI_RELEASE",
        "kind": "NEWS_AND_MACRO",
        "url": BLS_URL,
        "hostname": "www.bls.gov",
        "file": "bls-cpi.html",
    },
    {
        "source_name": "FED_MONETARY_RSS",
        "kind": "NEWS",
        "url": FED_URL,
        "hostname": "www.federalreserve.gov",
        "file": "fed-monetary.xml",
    },
)
SYMBOLS = tuple(sorted(UNIVERSE))
PARSER_VERSION = "official-context-parser-v1"
_BLS_REFERENCE = re.compile(
    r"CONSUMER PRICE INDEX\s*[-–]\s*(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
_BLS_LEAD = re.compile(
    r"Consumer Price Index for All Urban Consumers \(CPI-U\) increased "
    r"(?P<mm>-?\d+(?:\.\d+)?) percent on a seasonally adjusted basis in "
    r"(?P<month>[A-Za-z]+) after .*? Over the last 12 months, the all items index "
    r"increased (?P<yy>-?\d+(?:\.\d+)?) percent before seasonal adjustment\.",
    re.IGNORECASE,
)
_BLS_EMBARGO = re.compile(
    r"Transmission of material in this release is embargoed until\s+"
    r"(?P<hour>\d{1,2}:\d{2}\s*[ap]\.m\.)\s*\(ET\)\s+"
    r"(?P<weekday>[A-Za-z]+),\s+(?P<date>[A-Za-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)


def wall_ms() -> int:
    return time.time_ns() // 1_000_000


def _safe_existing(path: Path, *, directory: bool) -> Path:
    path = Path(path).absolute()
    for entry in (*reversed(path.parents), path):
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("capture paths cannot traverse symlinks or reparse points")
        is_target = entry == path
        if (directory if is_target else True) and not stat.S_ISDIR(info.st_mode):
            raise ValueError("existing capture parent directory required")
        if is_target and not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ValueError("unaliased regular capture file required")
    return path


class CaptureOwner:
    """Kernel-owned single-capture lock; the persistent lock file is not ownership."""

    def __init__(self, parent: Path):
        self.parent = _safe_existing(parent, directory=True)
        self.stream = None

    def __enter__(self):
        path = self.parent / ".official-context-capture.owner.lock"
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


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() in {"script", "style"}:
            self.skip_tags.append(tag.casefold())

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.skip_tags:
            index = len(self.skip_tags) - 1 - self.skip_tags[::-1].index(tag)
            del self.skip_tags[index:]

    def handle_data(self, data: str) -> None:
        if not self.skip_tags and data.strip():
            self.parts.append(data.strip())


def _plain_html(value: str) -> str:
    parser = _Text()
    parser.feed(value)
    parser.close()
    return " ".join(" ".join(parser.parts).split())


def _bls_metadata(body: bytes) -> tuple[str, int, int, int, int, str, str, int]:
    text = _plain_html(body.decode("utf-8", errors="strict"))
    lead = _BLS_LEAD.search(text)
    embargo = _BLS_EMBARGO.search(text)
    reference_matches = list(_BLS_REFERENCE.finditer(text))
    if not lead or not embargo or len(reference_matches) != 1:
        raise ValueError("BLS required CPI lead/reference/embargo format not found exactly")
    reference = reference_matches[0]
    month = datetime.strptime(reference.group("month"), "%B").month
    year = int(reference.group("year"))
    if datetime.strptime(lead.group("month"), "%B").month != month:
        raise ValueError("BLS CPI reference month differs between headline and lead")
    embargo_hour = re.sub(r"\.", "", embargo.group("hour")).upper()
    stamp = datetime.strptime(
        f"{embargo.group('date')} {embargo_hour}",
        "%B %d, %Y %I:%M %p",
    )
    if stamp.strftime("%A").casefold() != embargo.group("weekday").casefold():
        raise ValueError("BLS release weekday does not match its date")
    march_first = datetime(stamp.year, 3, 1)
    second_sunday_march = 1 + (6 - march_first.weekday()) % 7 + 7
    november_first = datetime(stamp.year, 11, 1)
    first_sunday_november = 1 + (6 - november_first.weekday()) % 7
    dst = (stamp.month > 3 or (stamp.month == 3 and stamp.day >= second_sunday_march)) and (
        stamp.month < 11 or (stamp.month == 11 and stamp.day < first_sunday_november)
    )
    stamp = stamp.replace(tzinfo=timezone(timedelta(hours=-4 if dst else -5)))
    publication_lower_ms = int(stamp.timestamp() * 1000)
    publication_upper_ms = publication_lower_ms + 59_999
    next_period = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=UTC)
    realized_ms = int(next_period.timestamp() * 1000) - 1
    if realized_ms >= publication_lower_ms:
        raise ValueError("CPI measurement period must end before its publication interval")
    if not 1 <= month <= 12 or not 1900 <= year <= 2100:
        raise ValueError("invalid CPI reference period")
    return (
        text,
        publication_lower_ms,
        publication_upper_ms,
        month,
        year,
        lead.group("mm"),
        lead.group("yy"),
        realized_ms,
    )


def _local_item_time(value: str) -> int:
    parsed = email.utils.parsedate_to_datetime(value)
    if parsed is None or parsed.tzinfo is None:
        raise ValueError("RSS item publication timestamp needs an explicit timezone")
    return int(parsed.astimezone(UTC).timestamp() * 1000)


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].casefold()


def _rss_items(body: bytes) -> list[dict[str, str | int]]:
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", body, re.IGNORECASE):
        raise ValueError("RSS DTD/entity declarations are unsupported")
    root = ET.fromstring(body)
    if _tag(root) != "rss" or root.attrib != {"version": "2.0"} or len(root) != 1:
        raise ValueError("exact RSS 2.0 root/channel required")
    channel = root[0]
    if _tag(channel) != "channel":
        raise ValueError("RSS direct channel child required")
    channel_fields = [_tag(child) for child in channel]
    singleton_channel = {
        "title",
        "link",
        "description",
        "language",
        "copyright",
        "managingeditor",
        "webmaster",
        "pubdate",
        "lastbuilddate",
        "generator",
        "docs",
        "cloud",
        "ttl",
        "image",
        "textinput",
        "skiphours",
        "skipdays",
    }
    if not all(channel_fields.count(name) == 1 for name in ("title", "link", "description")):
        raise ValueError("RSS channel must contain unique title/link/description")
    if any(channel_fields.count(name) > 1 for name in singleton_channel):
        raise ValueError("duplicate singleton RSS channel field")
    allowed_channel = singleton_channel | {"category", "item"}
    if any(name not in allowed_channel for name in channel_fields):
        raise ValueError("unsupported RSS channel element")
    items = []
    seen_identities: set[tuple[str, str]] = set()
    item_nodes = [child for child in channel if _tag(child) == "item"]
    for item in item_nodes:
        field_nodes: dict[str, ET.Element] = {}
        field_names = [_tag(child) for child in item]
        required = {"title", "link", "description", "pubdate", "guid"}
        if not required.issubset(field_names):
            raise ValueError("RSS item missing required version metadata")
        if any(field_names.count(name) != 1 for name in required):
            raise ValueError("duplicate RSS item identity/publication field")
        allowed_item = required | {"author", "category", "comments", "enclosure", "source"}
        if any(name not in allowed_item for name in field_names):
            raise ValueError("unsupported RSS item element")
        if any(name not in {"category"} and field_names.count(name) > 1 for name in field_names):
            raise ValueError("duplicate singleton RSS item field")
        for child in item:
            name = _tag(child)
            if name in field_nodes:
                continue
            if len(child):
                raise ValueError("RSS item fields must be leaf text")
            field_nodes[name] = child
        values = {name: (node.text or "").strip() for name, node in field_nodes.items()}
        title = values.get("title", "").strip()
        link = values.get("link", "").strip()
        guid = values.get("guid", "").strip()
        description = _plain_html(values.get("description", ""))
        published_ms = _local_item_time(values.get("pubdate", ""))
        url = link
        parsed = urlsplit(url)
        if (
            not title
            or not description
            or not guid
            or not url
            or parsed.scheme != "https"
            or parsed.hostname != "www.federalreserve.gov"
            or parsed.netloc.casefold() != "www.federalreserve.gov"
            or len(title) > 24_000
            or len(description) > 24_000
            or len(guid) > 24_000
        ):
            raise ValueError("RSS item omitted required official publication fields")
        if len(url) > 2_048:
            raise ValueError("RSS item identity/body exceeds contract bounds")
        identity = (guid, url)
        if identity in seen_identities:
            raise ValueError("duplicate official RSS guid/url identity")
        seen_identities.add(identity)
        document_id = f"fed-{hashlib.sha256(canonical(identity).encode()).hexdigest()}"
        items.append(
            {
                "headline": title,
                "body": description,
                "url": url,
                "document_id": document_id,
                "published_ms": published_ms,
            }
        )
        if len(items) > 500:
            raise ValueError("RSS bounded item count exceeded")
    return items


def _version(
    *,
    source_name: str,
    kind: str,
    url: str,
    document_id: str,
    payload: dict[str, str],
    published_lower_ms: int,
    published_upper_ms: int,
    captured_ms: int,
    raw_sha256: str,
    receipt_proof_sha256: str,
    realized_ms: int | None = None,
) -> HistoricalVersion:
    identity = "\0".join((source_name, document_id, raw_sha256, canonical(payload)))
    record_id = f"ctx-{hashlib.sha256(identity.encode()).hexdigest()[:32]}"
    if (
        not document_id
        or len(document_id) > 128
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", document_id) is None
    ):
        raise ValueError("document identity exceeds exact archive contract")
    return HistoricalVersion(
        record_id=record_id,
        document_id=document_id,
        source_name=source_name,
        kind=kind,
        symbols=SYMBOLS,
        url=url,
        payload_json=canonical(payload),
        raw_content_sha256=raw_sha256,
        extraction_policy_sha256=digest(
            {"parser": PARSER_VERSION, "parser_sha256": _parser_sha256(), "source": source_name}
        ),
        published_lower_ms=published_lower_ms,
        published_upper_ms=published_upper_ms,
        version_available_ms=captured_ms,
        captured_ms=captured_ms,
        proof_kind="CONTEMPORANEOUS_LOCAL",
        proof_sha256=receipt_proof_sha256,
        realized_ms=realized_ms,
    )


def _extract(
    source_name: str,
    body: bytes,
    *,
    captured_ms: int,
    raw_sha256: str,
    proof_sha256: str,
) -> list[HistoricalVersion]:
    if source_name == "BLS_CPI_RELEASE":
        text, publication_lower_ms, publication_upper_ms, month, year, mm, yy, realized_ms = _bls_metadata(
            body
        )
        headline = f"Consumer Price Index - {datetime(year, month, 1).strftime('%B %Y')} CPI-U release"
        lead = _BLS_LEAD.search(text)
        assert lead is not None
        news_body = lead.group(0)
        versions = [
            _version(
                source_name=source_name,
                kind="NEWS",
                url=BLS_URL,
                document_id=f"bls-cpi-release-{year}-{month:02d}",
                payload={"headline": headline, "body": news_body},
                published_lower_ms=publication_lower_ms,
                published_upper_ms=publication_upper_ms,
                captured_ms=captured_ms,
                raw_sha256=raw_sha256,
                receipt_proof_sha256=proof_sha256,
            )
        ]
        period_label = f"({year:04d}-{month:02d})"
        for suffix, metric, value in (
            ("mom-sa", f"CPI-U all items month-over-month seasonally adjusted {period_label}", mm),
            ("yoy-nsa", f"CPI-U all items year-over-year not seasonally adjusted {period_label}", yy),
        ):
            versions.append(
                _version(
                    source_name=source_name,
                    kind="MACRO",
                    url=BLS_URL,
                    document_id=f"bls-cpi-{year}-{month:02d}-{suffix}",
                    payload={"metric": metric, "value": value, "unit": "percent"},
                    published_lower_ms=publication_lower_ms,
                    published_upper_ms=publication_upper_ms,
                    captured_ms=captured_ms,
                    raw_sha256=raw_sha256,
                    receipt_proof_sha256=proof_sha256,
                    realized_ms=realized_ms,
                )
            )
        return versions
    if source_name != "FED_MONETARY_RSS":
        raise ValueError("unregistered source identity")
    versions = []
    for item in _rss_items(body):
        published_ms = int(item["published_ms"])
        if published_ms > captured_ms:
            raise ValueError("RSS publication time is later than local capture")
        versions.append(
            _version(
                source_name=source_name,
                kind="NEWS",
                url=str(item["url"]),
                document_id=str(item["document_id"]),
                payload={"headline": str(item["headline"]), "body": str(item["body"])},
                published_lower_ms=published_ms,
                published_upper_ms=published_ms,
                captured_ms=captured_ms,
                raw_sha256=raw_sha256,
                receipt_proof_sha256=proof_sha256,
            )
        )
    return versions


async def _read_limited(response: Any, limit: int) -> tuple[bytes, bool, str | None]:
    body = bytearray()
    try:
        async for chunk in response.content.iter_chunked(64 * 1024):
            room = limit - len(body)
            body.extend(chunk[:room])
            if len(chunk) > room:
                return bytes(body), False, "BODY_LIMIT_EXCEEDED_PREFIX_RETAINED"
    except asyncio.CancelledError:
        return bytes(body), False, "CANCELLED_PREFIX_RETAINED"
    except Exception as exc:
        return bytes(body), False, f"{type(exc).__name__}_PREFIX_RETAINED"
    return bytes(body), True, None


def _write_raw(path: Path, body: bytes) -> str:
    with path.open("xb") as stream:
        if stream.write(body) != len(body):
            raise OSError("incomplete original response write")
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(body).hexdigest()


def _write_json(path: Path, value: Any, limit: int) -> str:
    encoded = canonical(value).encode("utf-8")
    if len(encoded) > limit:
        raise ValueError("capture metadata byte bound exceeded")
    with path.open("xb") as stream:
        if stream.write(encoded) != len(encoded):
            raise OSError("incomplete capture metadata write")
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(encoded).hexdigest()


def _read_bounded(path: Path, limit: int) -> bytes:
    _safe_existing(path, directory=False)
    with path.open("rb") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError("capture artifact exceeds read bound")
    return value


def _parser_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _plan(capture_id: str, started_ms: int, parser_sha256: str) -> dict[str, Any]:
    return {
        "schema": f"{SCHEMA}.plan.v1",
        "capture_id": capture_id,
        "started_ms": started_ms,
        "parser_version": PARSER_VERSION,
        "parser_sha256": parser_sha256,
        "source_roster": [dict(source) for source in SOURCES],
        "limits": {
            "requests_max": MAX_SOURCE_COUNT,
            "retries": 0,
            "redirects": 0,
            "timeout_seconds": REQUEST_TIMEOUT_SECONDS,
            "body_bytes_each_max": MAX_BODY_BYTES,
            "rss_items_max": 500,
        },
        "transport": {"proxy": "DISABLED", "tls": "DEFAULT_VALIDATION_REQUIRED", "encoding": "identity"},
        "coverage_status": "UNKNOWN",
    }


async def capture_official_context(output: Path) -> dict[str, Any]:
    """Fetch each fixed official URL once; no redirect, credentials, or retry."""
    import aiohttp

    output = Path(output).absolute()
    parent = _safe_existing(output.parent, directory=True)
    if re.fullmatch(r"official-context-[0-9]{8}-[a-z0-9-]{1,48}", output.name) is None:
        raise ValueError("new direct official-context-YYYYMMDD-suffix output required")
    context = ssl.create_default_context()
    if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
        raise ValueError("verified TLS hostname and certificate required")
    with CaptureOwner(parent):
        output.mkdir()
        _safe_existing(output, directory=True)
        capture_id = str(uuid.uuid4())
        started_ms = wall_ms()
        parser_sha_start = _parser_sha256()
        plan = _plan(capture_id, started_ms, parser_sha_start)
        plan_sha = _write_json(output / "plan.json", plan, MAX_PLAN_BYTES)
        results: list[dict[str, Any]] = []
        versions: list[HistoricalVersion] = []
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS, connect=10, sock_read=10)
        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                trust_env=False,
                auto_decompress=False,
                headers={
                    "User-Agent": "Kairos-OfficialContext/1.0",
                    "Accept-Encoding": "identity",
                },
            ) as session:
                for source in SOURCES:
                    endpoint = source["url"]
                    if urlsplit(endpoint).hostname != source["hostname"]:
                        raise ValueError("configured source host outside exact allowlist")
                    result: dict[str, Any] = {
                        "source_name": source["source_name"],
                        "kind": source["kind"],
                        "url": endpoint,
                        "raw_file": source["file"],
                        "attempts": 0,
                        "redirects": 0,
                        "status": None,
                        "received_ms": None,
                        "persisted_ms": None,
                        "body_complete": False,
                        "raw_bytes": 0,
                        "raw_sha256": None,
                        "parse_status": "UNAVAILABLE",
                        "error": None,
                        "version_record_ids": [],
                    }
                    body = b""
                    received_ms = None
                    status = None
                    try:
                        async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                            result["attempts"] = 1
                            async with session.get(
                                endpoint,
                                allow_redirects=False,
                                ssl=context,
                                proxy=None,
                            ) as response:
                                status = int(response.status)
                                result["status"] = status
                                result["redirects"] = 1 if 300 <= status < 400 else 0
                                if (
                                    str(response.url) != endpoint
                                    or urlsplit(str(response.url)).hostname != source["hostname"]
                                ):
                                    raise ValueError("response URL escaped exact HTTPS host allowlist")
                                body, complete, read_error = await _read_limited(response, MAX_BODY_BYTES)
                                received_ms = wall_ms()
                                result["received_ms"] = received_ms
                                result["body_complete"] = complete
                                if read_error:
                                    result["error"] = read_error
                    except Exception as exc:
                        result["error"] = type(exc).__name__
                    raw_sha = _write_raw(output / str(source["file"]), body)
                    persisted_ms = wall_ms()
                    result["persisted_ms"] = persisted_ms
                    result["raw_bytes"] = len(body)
                    result["raw_sha256"] = raw_sha
                    if received_ms is not None and persisted_ms < received_ms:
                        result["error"] = "LOCAL_WALL_CLOCK_REGRESSION"
                    elif status == 200 and result["body_complete"] and not result["error"]:
                        proof = digest(
                            {
                                "capture_id": capture_id,
                                "source_name": source["source_name"],
                                "url": endpoint,
                                "raw_file": source["file"],
                                "raw_sha256": raw_sha,
                                "received_ms": received_ms,
                                "persisted_ms": persisted_ms,
                            }
                        )
                        try:
                            found = _extract(
                                str(source["source_name"]),
                                body,
                                captured_ms=persisted_ms,
                                raw_sha256=raw_sha,
                                proof_sha256=proof,
                            )
                            versions.extend(found)
                            result["version_record_ids"] = [version.record_id for version in found]
                            result["parse_status"] = "EMPTY_FEED" if not found else "PARSED"
                        except (ValueError, UnicodeError, ET.ParseError, RecursionError) as exc:
                            result["parse_status"] = "UNPARSEABLE"
                            result["error"] = type(exc).__name__
                    elif not result["error"]:
                        result["error"] = "HTTP_STATUS_NOT_SUCCESS"
                    results.append(result)
        except Exception as exc:
            for source in SOURCES[len(results) :]:
                empty_sha = _write_raw(output / str(source["file"]), b"")
                persisted_ms = wall_ms()
                results.append(
                    {
                        "source_name": source["source_name"],
                        "kind": source["kind"],
                        "url": source["url"],
                        "raw_file": source["file"],
                        "attempts": 0,
                        "redirects": 0,
                        "status": None,
                        "received_ms": None,
                        "persisted_ms": persisted_ms,
                        "body_complete": False,
                        "raw_bytes": 0,
                        "raw_sha256": empty_sha,
                        "parse_status": "UNAVAILABLE",
                        "error": f"SESSION_{type(exc).__name__}",
                        "version_record_ids": [],
                    }
                )
        finally:
            # Let the TLS/session connector finish graceful shutdown after ClientSession exits.
            await asyncio.sleep(0.250)
        parser_sha_end = _parser_sha256()
        if parser_sha_start != parser_sha_end:
            versions = []
            results = [
                {
                    **row,
                    "version_record_ids": [],
                    "parse_status": "UNAVAILABLE",
                    "error": "SOURCE_FINGERPRINT_CHANGED",
                }
                for row in results
            ]
        archive = HistoricalArchive(tuple(versions), ())
        archive.validate()
        archive_bytes = archive.to_json().encode("utf-8")
        archive_sha = hashlib.sha256(archive_bytes).hexdigest()
        with (output / "historical-context.json").open("xb") as stream:
            stream.write(archive_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        ended_ms = wall_ms()
        receipt = {
            "schema": SCHEMA,
            "capture_id": capture_id,
            "started_ms": started_ms,
            "ended_ms": ended_ms,
            "parser_version": PARSER_VERSION,
            "parser_sha256": parser_sha_start,
            "parser_sha256_final": parser_sha_end,
            "source_fingerprint_stable": parser_sha_start == parser_sha_end,
            "plan_file": "plan.json",
            "plan_sha256": plan_sha,
            "source_roster": [dict(source) for source in SOURCES],
            "get_count": sum(row["attempts"] for row in results),
            "retry_count": 0,
            "redirect_policy": "FORBIDDEN",
            "proxy_policy": "DISABLED",
            "tls_policy": "DEFAULT_VALIDATION_REQUIRED",
            "source_results": results,
            "archive_file": "historical-context.json",
            "archive_sha256": archive_sha,
            "version_count": len(versions),
            "coverage_status": "UNKNOWN",
            "all_world_news_complete": False,
            "historical_availability_proven": False,
            "historical_receive_clock_proven": False,
            "provenance_authenticity_verified": False,
            "trading_authority": False,
        }
        _write_json(output / "receipt.json", receipt, MAX_RECEIPT_BYTES)
        return receipt


def audit_official_context_capture(output: Path, expected_receipt_sha256: str) -> dict[str, Any]:
    """Read-only bounded verification against a caller-pinned capture receipt digest."""
    if (
        type(expected_receipt_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", expected_receipt_sha256) is None
    ):
        raise ValueError("caller-pinned receipt SHA256 required")
    output = _safe_existing(Path(output), directory=True)
    receipt_bytes = _read_bounded(output / "receipt.json", MAX_RECEIPT_BYTES)
    if hashlib.sha256(receipt_bytes).hexdigest() != expected_receipt_sha256:
        raise ValueError("receipt differs from caller pin")
    receipt = _json(receipt_bytes)
    if type(receipt) is not dict or canonical(receipt).encode() != receipt_bytes:
        raise ValueError("canonical capture receipt required")
    receipt_fields = {
        "schema",
        "capture_id",
        "started_ms",
        "ended_ms",
        "parser_version",
        "parser_sha256",
        "parser_sha256_final",
        "source_fingerprint_stable",
        "plan_file",
        "plan_sha256",
        "source_roster",
        "get_count",
        "retry_count",
        "redirect_policy",
        "proxy_policy",
        "tls_policy",
        "source_results",
        "archive_file",
        "archive_sha256",
        "version_count",
        "coverage_status",
        "all_world_news_complete",
        "historical_availability_proven",
        "historical_receive_clock_proven",
        "provenance_authenticity_verified",
        "trading_authority",
    }
    if set(receipt) != receipt_fields:
        raise ValueError("capture receipt schema differs")
    plan_bytes = _read_bounded(output / "plan.json", MAX_PLAN_BYTES)
    if hashlib.sha256(plan_bytes).hexdigest() != receipt.get("plan_sha256"):
        raise ValueError("capture plan digest differs")
    plan = _json(plan_bytes)
    expected_plan = _plan(receipt["capture_id"], receipt["started_ms"], receipt["parser_sha256"])
    if plan != expected_plan or canonical(plan).encode() != plan_bytes:
        raise ValueError("fixed create-only source plan differs")
    if (
        receipt.get("schema") != SCHEMA
        or receipt.get("source_roster") != [dict(source) for source in SOURCES]
        or receipt.get("coverage_status") != "UNKNOWN"
        or any(
            receipt.get(field) is not False
            for field in (
                "all_world_news_complete",
                "historical_availability_proven",
                "historical_receive_clock_proven",
                "provenance_authenticity_verified",
                "trading_authority",
            )
        )
        or receipt.get("source_fingerprint_stable") is not True
        or receipt.get("parser_sha256") != receipt.get("parser_sha256_final")
        or receipt.get("parser_sha256") != _parser_sha256()
        or receipt.get("ended_ms", -1) < receipt.get("started_ms", 0)
        or receipt.get("parser_version") != PARSER_VERSION
        or receipt.get("plan_file") != "plan.json"
        or receipt.get("archive_file") != "historical-context.json"
        or receipt.get("redirect_policy") != "FORBIDDEN"
        or receipt.get("proxy_policy") != "DISABLED"
        or receipt.get("tls_policy") != "DEFAULT_VALIDATION_REQUIRED"
        or type(receipt.get("retry_count")) is not int
        or receipt["retry_count"] != 0
    ):
        raise ValueError("capture receipt invariant failed")
    archive_bytes = _read_bounded(output / "historical-context.json", MAX_ARCHIVE_BYTES)
    archive = import_archive(archive_bytes, receipt.get("archive_sha256"))
    if archive.coverage != () or len(archive.versions) != receipt.get("version_count"):
        raise ValueError("archive count/coverage differs from receipt")
    all_versions: list[HistoricalVersion] = []
    rows = receipt.get("source_results")
    if type(rows) is not list or len(rows) != len(SOURCES):
        raise ValueError("exact source result roster required")
    for source, row in zip(SOURCES, rows, strict=True):
        row_fields = {
            "source_name",
            "kind",
            "url",
            "raw_file",
            "attempts",
            "redirects",
            "status",
            "received_ms",
            "persisted_ms",
            "body_complete",
            "raw_bytes",
            "raw_sha256",
            "parse_status",
            "error",
            "version_record_ids",
        }
        if type(row) is not dict or set(row) != row_fields:
            raise ValueError("exact source result schema required")
        if type(row) is not dict or any(
            row.get(key) != (source["file"] if key == "raw_file" else source[key])
            for key in ("source_name", "kind", "url", "raw_file")
        ):
            raise ValueError("source result identity differs from fixed roster")
        raw = _read_bounded(output / source["file"], MAX_BODY_BYTES)
        raw_sha = hashlib.sha256(raw).hexdigest()
        if row.get("raw_sha256") != raw_sha or row.get("raw_bytes") != len(raw):
            raise ValueError("raw source bytes/hash differs")
        if (
            type(row.get("attempts")) is not int
            or row["attempts"] not in {0, 1}
            or type(row.get("redirects")) is not int
            or row["redirects"] not in {0, 1}
            or type(row.get("body_complete")) is not bool
            or (
                row["status"] is not None
                and (type(row["status"]) is not int or not 100 <= row["status"] <= 599)
            )
            or type(row.get("version_record_ids")) is not list
            or row.get("parse_status") not in {"UNAVAILABLE", "UNPARSEABLE", "PARSED", "EMPTY_FEED"}
        ):
            raise ValueError("source result transport/parse claim malformed")
        persisted = row.get("persisted_ms")
        received = row.get("received_ms")
        if type(persisted) is not int or persisted > receipt["ended_ms"] or persisted < receipt["started_ms"]:
            raise ValueError("source persisted clock outside capture")
        if received is not None and (
            type(received) is not int or received < receipt["started_ms"] or received > persisted
        ):
            raise ValueError("source receive clock ordering invalid")
        if row.get("status") == 200 and row.get("body_complete") is True:
            proof = digest(
                {
                    "capture_id": receipt["capture_id"],
                    "source_name": source["source_name"],
                    "url": source["url"],
                    "raw_file": source["file"],
                    "raw_sha256": raw_sha,
                    "received_ms": received,
                    "persisted_ms": persisted,
                }
            )
            try:
                parsed = _extract(
                    source["source_name"], raw, captured_ms=persisted, raw_sha256=raw_sha, proof_sha256=proof
                )
            except (ValueError, UnicodeError, ET.ParseError, RecursionError) as exc:
                parsed = []
                if row.get("parse_status") != "UNPARSEABLE" or row.get("error") != type(exc).__name__:
                    raise ValueError("receipt falsely claims parse success") from None
            else:
                expected_status = "EMPTY_FEED" if not parsed else "PARSED"
                if row.get("parse_status") != expected_status or row.get("error") is not None:
                    raise ValueError("successful source parse status/error differs")
            if row.get("version_record_ids") != [version.record_id for version in parsed]:
                raise ValueError("source record identities differ from independent parse")
            all_versions.extend(parsed)
        elif row.get("version_record_ids"):
            raise ValueError("unavailable source claims extracted versions")
    if (
        type(receipt.get("get_count")) is not int
        or receipt["get_count"] != sum(row["attempts"] for row in rows)
        or not 0 <= receipt["get_count"] <= MAX_SOURCE_COUNT
    ):
        raise ValueError("bounded one-attempt source roster differs")
    if [asdict(version) for version in all_versions] != [asdict(version) for version in archive.versions]:
        raise ValueError("exported versions differ from independent raw-source parse")
    return {
        "valid": True,
        "receipt_sha256": expected_receipt_sha256,
        "archive_sha256": receipt["archive_sha256"],
        "versions": len(archive.versions),
        "coverage_status": "UNKNOWN",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--workspace-root", type=Path, default=Path(r"D:\Kairos"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.capture:
        print(canonical({"status": "NOT_STARTED", "network": False, "writes": False}))
        return 0
    runtime = _safe_existing(args.workspace_root / "runtime", directory=True)
    if args.output is None or args.output.absolute().parent != runtime:
        parser.error("new direct workspace runtime child required")
    receipt = asyncio.run(capture_official_context(args.output.absolute()))
    healthy = all(
        row["status"] == 200 and row["parse_status"] in {"PARSED", "EMPTY_FEED"} and row["error"] is None
        for row in receipt["source_results"]
    )
    print(
        canonical(
            {
                "status": "CAPTURED" if healthy else "CAPTURE_ATTEMPT_RETAINED",
                "sources": len(receipt["source_results"]),
                "versions": receipt["version_count"],
                "coverage_status": "UNKNOWN",
            }
        )
    )
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
