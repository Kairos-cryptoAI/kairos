"""Bounded read-only original funding rates for modeled research accounting.

Every monthly CSV row is retained with exact Decimal economics and original
calc_time. A separately supplied, frozen entitlement calendar must reconcile
the whole month. Neither archive checksums nor this calendar establish venue
settlement prices, historical receive clocks, source admission or entry data.
"""

from __future__ import annotations

import hashlib
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from .bookticker_archive_stream_v3 import (
    _canonical,
    _identity,
    _open_regular,
    _regular_nofollow,
    _safe_path,
    _sha,
)

HEADER = b"calc_time,funding_interval_hours,last_funding_rate"
SCHEMA = "kairos.research.original-funding-rate.v3"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
_MONTH = re.compile(r"20\d{2}-(?:0[1-9]|1[0-2])\Z")
_INTEGER = re.compile(rb"(?:0|[1-9][0-9]{0,15})\Z")
_RATE = re.compile(rb"-?(?:0|[1-9][0-9]{0,31})(?:\.[0-9]{1,64})?(?:[eE][+-]?[0-9]{1,2})?\Z")


@dataclass(frozen=True, slots=True)
class FundingArchiveLimitsV3:
    max_archive_bytes: int = 1_048_576
    max_csv_bytes: int = 1_048_576
    max_rows: int = 1_000
    max_line_bytes: int = 512
    timeout_seconds: int = 30

    def __post_init__(self):
        for field, ceiling in (
            ("max_archive_bytes", 16_777_216),
            ("max_csv_bytes", 16_777_216),
            ("max_rows", 10_000),
            ("max_line_bytes", 4_096),
            ("timeout_seconds", 300),
        ):
            if type(getattr(self, field)) is not int or not 1 <= getattr(self, field) <= ceiling:
                raise ValueError(f"explicit bounded {field} required")


DEFAULT_LIMITS = FundingArchiveLimitsV3()


def _content(raw: bytes) -> bytes:
    result = raw[:-2] if raw.endswith(b"\r\n") else raw[:-1] if raw.endswith(b"\n") else raw
    if b"\r" in result or b"\n" in result:
        raise ValueError("unambiguous original CSV line ending required")
    return result


@dataclass(frozen=True, slots=True)
class FundingEntitlementV3:
    due_at_ms: int
    interval_hours: int

    def __post_init__(self):
        if (
            type(self.due_at_ms) is not int
            or not 0 <= self.due_at_ms <= 9_999_999_999_999
            or type(self.interval_hours) is not int
            or not 1 <= self.interval_hours <= 24
        ):
            raise ValueError("exact funding entitlement and interval required")


@dataclass(frozen=True, slots=True)
class OriginalFundingRateV3:
    symbol: str
    due_at_ms: int
    exchange_calc_time_ms: int
    interval_hours: int
    rate: Decimal
    raw_record: bytes
    raw_record_sha256: str

    def modeled_available_at(self, *, feed_delay_ms: int, processing_delay_ms: int) -> int:
        for value in (feed_delay_ms, processing_delay_ms):
            if type(value) is not int or not 0 <= value <= 86_400_000:
                raise ValueError("explicit bounded modeled delay required")
        # Never relabel archive retrieval time as a historical local clock.
        return max(self.due_at_ms, self.exchange_calc_time_ms) + feed_delay_ms + processing_delay_ms


@dataclass(frozen=True, slots=True)
class OriginalFundingArchiveV3:
    symbol: str
    month: str
    archive_sha256: str
    checksum_sha256: str
    csv_sha256: str
    csv_bytes: int
    calendar_sha256: str
    maximum_observed_offset_ms: int
    records: tuple[OriginalFundingRateV3, ...]
    evidence_kind: str = "ARCHIVE_CALC_TIME_ENTITLEMENT_PROXY_NOT_SOURCE_ADMISSION"
    historical_received_at_ms: None = None
    settlement_price: None = None
    funding_for_entry_decisions: bool = False

    def window(self, start_ms: int, end_ms: int) -> tuple[OriginalFundingRateV3, ...]:
        if type(start_ms) is not int or type(end_ms) is not int or end_ms <= start_ms:
            raise ValueError("exact half-open funding entitlement window required")
        # Select by explicitly declared entitlement, not rounded calc_time.
        return tuple(item for item in self.records if start_ms <= item.due_at_ms < end_ms)


def load_original_funding_archive_v3(
    path: Path,
    *,
    symbol: str,
    month: str,
    expected_archive_sha256: str,
    expected_checksum_sha256: str,
    entitlements: tuple[FundingEntitlementV3, ...],
    maximum_calc_time_offset_ms: int,
    limits: FundingArchiveLimitsV3 = DEFAULT_LIMITS,
) -> OriginalFundingArchiveV3:
    """Full CRC/hash/schema/calendar scan; rejects omissions, duplicates/drift.

    Pins must come from independently retained acquisition evidence. The
    explicit calendar remains a research entitlement hypothesis, never an
    independently authenticated exchange settlement schedule.
    """
    started = time.monotonic()
    if type(limits) is not FundingArchiveLimitsV3:
        raise ValueError("exact funding bounds required")
    deadline = started + limits.timeout_seconds

    def check_time():
        if time.monotonic() > deadline:
            raise TimeoutError("original funding verification time budget exceeded")

    if symbol not in SYMBOLS or type(month) is not str or _MONTH.fullmatch(month) is None:
        raise ValueError("fixed funding symbol and month required")
    _sha(expected_archive_sha256, "independent funding archive SHA256")
    _sha(expected_checksum_sha256, "independent funding checksum SHA256")
    if type(maximum_calc_time_offset_ms) is not int or not 0 <= maximum_calc_time_offset_ms <= 60_000:
        raise ValueError("explicit bounded original calc_time offset required")
    year, month_number = map(int, month.split("-"))
    lo = int(datetime(year, month_number, 1, tzinfo=UTC).timestamp() * 1_000)
    hi = int(datetime(year + (month_number == 12), month_number % 12 + 1, 1, tzinfo=UTC).timestamp() * 1_000)
    if (
        type(entitlements) is not tuple
        or not 1 <= len(entitlements) <= limits.max_rows
        or any(
            type(item) is not FundingEntitlementV3 or not lo <= item.due_at_ms < hi for item in entitlements
        )
        or tuple(sorted({item.due_at_ms for item in entitlements}))
        != tuple(item.due_at_ms for item in entitlements)
    ):
        raise ValueError("complete unique ordered monthly entitlement roster required")
    name = f"{symbol}-fundingRate-{month}.zip"
    path = _safe_path(Path(path))
    if path.name != name:
        raise ValueError("funding archive name disagrees with frozen identity")
    checksum_path = _safe_path(path.with_name(name + ".CHECKSUM"))
    checksum_stream, checksum_identity = _open_regular(checksum_path)
    with checksum_stream:
        sidecar = checksum_stream.read(513)
    if (
        len(sidecar) > 512
        or hashlib.sha256(sidecar).hexdigest() != expected_checksum_sha256
        or _identity(_regular_nofollow(checksum_path)) != _identity(checksum_identity)
    ):
        raise ValueError("independent funding checksum file mismatch")
    if _content(sidecar) != f"{expected_archive_sha256}  {name}".encode("ascii"):
        raise ValueError("official funding checksum identity mismatch")
    stream, file_identity = _open_regular(path)
    records = []
    csv_hash = hashlib.sha256()
    csv_bytes = 0
    maximum_offset = 0
    previous_calc = -1
    with stream:
        if file_identity.st_size > limits.max_archive_bytes:
            raise ValueError("funding archive byte budget exceeded")
        archive_hash = hashlib.sha256()
        for block in iter(lambda: stream.read(65_536), b""):
            check_time()
            archive_hash.update(block)
        if archive_hash.hexdigest() != expected_archive_sha256:
            raise ValueError("independently retained funding archive hash mismatch")
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            members = archive.infolist()
            if len(members) != 1:
                raise ValueError("exact single original funding CSV required")
            member = members[0]
            if (
                member.filename != name[:-4] + ".csv"
                or member.is_dir()
                or member.flag_bits & 1
                or member.file_size > limits.max_csv_bytes
            ):
                raise ValueError("funding ZIP member identity or byte budget mismatch")
            with archive.open(member) as csv_stream:
                header = csv_stream.readline(limits.max_line_bytes + 1)
                if len(header) > limits.max_line_bytes or _content(header) != HEADER:
                    raise ValueError("original funding CSV header mismatch")
                csv_hash.update(header)
                csv_bytes += len(header)
                for expected in entitlements:
                    check_time()
                    raw = csv_stream.readline(limits.max_line_bytes + 1)
                    if not raw or len(raw) > limits.max_line_bytes:
                        raise ValueError("missing original funding row or line budget exceeded")
                    fields = _content(raw).split(b",")
                    if (
                        len(fields) != 3
                        or _INTEGER.fullmatch(fields[0]) is None
                        or _INTEGER.fullmatch(fields[1]) is None
                        or _RATE.fullmatch(fields[2]) is None
                    ):
                        raise ValueError("strict original funding row schema required")
                    calc, interval = int(fields[0]), int(fields[1])
                    offset = calc - expected.due_at_ms
                    if (
                        not lo <= calc < hi
                        or calc <= previous_calc
                        or not 0 <= offset <= maximum_calc_time_offset_ms
                        or interval != expected.interval_hours
                    ):
                        raise ValueError("original funding clock, order or entitlement mismatch")
                    previous_calc = calc
                    maximum_offset = max(maximum_offset, offset)
                    csv_hash.update(raw)
                    csv_bytes += len(raw)
                    if csv_bytes > limits.max_csv_bytes:
                        raise ValueError("funding CSV byte budget exceeded")
                    records.append(
                        OriginalFundingRateV3(
                            symbol,
                            expected.due_at_ms,
                            calc,
                            interval,
                            Decimal(fields[2].decode("ascii")),
                            raw,
                            hashlib.sha256(raw).hexdigest(),
                        )
                    )
                # EOF both establishes complete roster coverage and performs
                # the zipfile CRC check. No sampling or trailing-row omission.
                if csv_stream.read(1):
                    raise ValueError("unplanned extra original funding row")
            if csv_bytes != member.file_size:
                raise ValueError("original funding CSV length mismatch")
        check_time()
        stream.seek(0)
        after_hash = hashlib.sha256()
        for block in iter(lambda: stream.read(65_536), b""):
            check_time()
            after_hash.update(block)
        if after_hash.hexdigest() != expected_archive_sha256 or _identity(
            _regular_nofollow(path)
        ) != _identity(file_identity):
            raise ValueError("original funding archive changed during verification")
    final_checksum_stream, final_checksum_identity = _open_regular(checksum_path)
    with final_checksum_stream:
        final_sidecar = final_checksum_stream.read(513)
    if (
        final_sidecar != sidecar
        or _identity(final_checksum_identity) != _identity(checksum_identity)
        or _identity(_regular_nofollow(checksum_path)) != _identity(checksum_identity)
    ):
        raise ValueError("funding checksum changed during verification")
    check_time()
    calendar_hash = hashlib.sha256(
        _canonical([[item.due_at_ms, item.interval_hours] for item in entitlements])
    ).hexdigest()
    return OriginalFundingArchiveV3(
        symbol,
        month,
        expected_archive_sha256,
        expected_checksum_sha256,
        csv_hash.hexdigest(),
        csv_bytes,
        calendar_hash,
        maximum_offset,
        tuple(records),
    )
