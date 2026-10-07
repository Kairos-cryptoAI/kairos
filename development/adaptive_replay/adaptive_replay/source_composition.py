"""Explicit input-only monthly/daily reconciliation, never a trading authority.

No download, cache write, source repair or economic evaluation occurs here.
Original failed-calendar inputs and their FULL_KLINE validator are unchanged.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal

from kairos_backtest.data import BINANCE_KLINE_COLUMNS, ArchiveFieldProfile, _parse_csv
from kairos_strategy.candles import Candle

MINUTE = 60_000
DAY = 1_440 * MINUTE
MISSING_DAYS = ("2022-02-26", "2022-02-27", "2022-02-28", "2022-04-01", "2022-04-02")
CONTROL_DAYS = ("2022-02-25", "2022-03-01", "2022-03-31", "2022-04-03")
REJECTED_XRP_SLOT = 1_701_347_700_000
REJECTED_XRP_FIELDS = (
    "1701347700000",
    "0.6038",
    "0.6038",
    "0.6034",
    "0.6036",
    "91695.7",
    "1701347759999",
    "200298.79368",
    "470",
    "132462.5",
    "79957.28937",
    "0",
)
REJECTED_XRP_REASON = "quote volume is inconsistent with OHLC and base volume"


def midnight_ms(value: str) -> int:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("canonical UTC calendar date required")
    return int(datetime.combine(parsed, time.min, UTC).timestamp() * 1_000)


def next_month(value: str) -> str:
    parsed = date.fromisoformat(value + "-01")
    return date(parsed.year + (parsed.month == 12), parsed.month % 12 + 1, 1).isoformat()


def canonical_fields(fields: tuple[str, ...]) -> tuple[str, ...]:
    """Representation normalization only; Decimal equality has no tolerance."""
    result = []
    for field in fields:
        number = Decimal(field)
        if not number.is_finite():
            raise ValueError("finite source field required")
        text = format(number, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        result.append("0" if number == 0 else text)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class ParsedArchive:
    symbol: str
    raw_sha256: str
    fields: dict[int, tuple[str, ...]]
    candles: dict[int, Candle]
    rejected_fields: dict[int, tuple[str, ...]]


def parse_archive(payload: bytes, symbol: str, *, allow_known_xrp_rejection: bool = False) -> ParsedArchive:
    """Rejection allowance retains the old row; it never makes it valid."""
    issues: list[tuple[int, str]] = []
    candles = _parse_csv(
        payload, symbol, "1m", field_profile=ArchiveFieldProfile.FULL_KLINE, domain_issues=issues
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        text = archive.read(names[0]).decode("utf-8")
    raw: dict[int, tuple[str, ...]] = {}
    lines: dict[int, int] = {}
    previous = -1
    for line, fields in enumerate(csv.reader(io.StringIO(text, newline=""), strict=True), 1):
        if line == 1 and tuple(fields) == BINANCE_KLINE_COLUMNS:
            continue
        slot = int(fields[0])
        if slot <= previous or slot % MINUTE or int(fields[6]) != slot + MINUTE - 1:
            raise ValueError("strictly increasing exact minute source clocks required")
        previous = slot
        raw[slot] = tuple(fields)
        lines[line] = slot
    rejected = {lines[line]: raw[lines[line]] for line, _ in issues}
    if issues:
        if (
            not allow_known_xrp_rejection
            or symbol != "XRPUSDT"
            or len(issues) != 1
            or issues[0][1] != REJECTED_XRP_REASON
            or rejected != {REJECTED_XRP_SLOT: REJECTED_XRP_FIELDS}
        ):
            raise ValueError("unexpected FULL_KLINE source rejection")
    valid = {row.open_time_ms: row for row in candles}
    if len(valid) != len(candles) or valid.keys() != raw.keys() - rejected.keys():
        raise ValueError("source row and strict parser membership disagree")
    return ParsedArchive(symbol, hashlib.sha256(payload).hexdigest(), raw, valid, rejected)


def check_daily(archive: ParsedArchive, day: str) -> None:
    start = midnight_ms(day)
    if archive.rejected_fields or list(archive.fields) != list(range(start, start + DAY, MINUTE)):
        raise ValueError("complete strict 1440-minute UTC daily archive required")


def check_overlap(monthly: ParsedArchive, daily: ParsedArchive, day: str) -> int:
    """All twelve source fields, every overlapping valid row, not a sample."""
    if monthly.symbol != daily.symbol:
        raise ValueError("same futures instrument required")
    check_daily(daily, day)
    matched = 0
    for slot, fields in daily.fields.items():
        if slot not in monthly.candles:
            continue
        if canonical_fields(fields) != canonical_fields(monthly.fields[slot]):
            raise ValueError(f"valid monthly/daily twelve-field conflict at {slot}")
        matched += 1
    return matched


def compose_month(
    monthly: ParsedArchive, month: str, daily_archives: dict[str, ParsedArchive]
) -> tuple[tuple[Candle, ...], dict[str, object]]:
    """Valid monthly wins; only the fixed known missing/rejected slots can change."""
    start, end = midnight_ms(month + "-01"), midnight_ms(next_month(month))
    if any(not start <= slot < end for slot in monthly.fields):
        raise ValueError("source timestamp outside its monthly partition")
    expected = set(range(start, end, MINUTE))
    missing = expected - monthly.fields.keys()
    allowed_missing = {
        slot
        for day in MISSING_DAYS
        if day.startswith(month) and monthly.symbol in ("SOLUSDT", "XRPUSDT")
        for slot in range(midnight_ms(day), midnight_ms(day) + DAY, MINUTE)
    }
    expected_rejection = {REJECTED_XRP_SLOT} if monthly.symbol == "XRPUSDT" and month == "2023-11" else set()
    if missing != allowed_missing or set(monthly.rejected_fields) != expected_rejection:
        raise ValueError("exact known monthly gap/rejection membership required")
    required_days = {day for day in MISSING_DAYS if day.startswith(month) and allowed_missing}
    if expected_rejection:
        required_days.add("2023-11-30")
    if set(daily_archives) != required_days:
        raise ValueError("exact fixed daily composition files required")
    selected = dict(monthly.candles)
    changed = []
    overlap = 0
    for day, daily in sorted(daily_archives.items()):
        overlap += check_overlap(monthly, daily, day)
        for slot, row in daily.candles.items():
            if slot in selected:
                continue
            if slot not in allowed_missing | expected_rejection:
                raise ValueError("daily source attempted an unplanned substitution")
            selected[slot] = row
            changed.append(
                {
                    "open_time_ms": slot,
                    "kind": "REJECTED_ROW_REPLACEMENT" if slot in expected_rejection else "ABSENT_ROW",
                    "daily_date": day,
                    "daily_raw_sha256": daily.raw_sha256,
                    "old_fields": monthly.rejected_fields.get(slot),
                    "new_fields": daily.fields[slot],
                }
            )
    if set(selected) != expected or len(changed) != len(allowed_missing) + len(expected_rejection):
        raise ValueError("complete exact composed monthly grid required")
    ordered = tuple(selected[slot] for slot in sorted(expected))
    fingerprint = hashlib.sha256()
    changed_by_slot = {item["open_time_ms"]: item for item in changed}
    for row in ordered:
        changed_row = changed_by_slot.get(row.open_time_ms)
        fields = changed_row["new_fields"] if changed_row else monthly.fields[row.open_time_ms]
        fingerprint.update(json.dumps(canonical_fields(fields), separators=(",", ":")).encode() + b"\n")
    return ordered, {
        "symbol": monthly.symbol,
        "month": month,
        "rows": len(ordered),
        "gaps": 0,
        "monthly_raw_sha256": monthly.raw_sha256,
        "normalized_twelve_field_rows_sha256": fingerprint.hexdigest(),
        "valid_overlap_rows_compared": overlap,
        "added_rows": len(allowed_missing),
        "replaced_rejected_rows": len(expected_rejection),
        "changes": changed,
        "monthly_valid_rows_changed": 0,
        "monthly_and_daily_not_independent_market_sources": True,
        "actual_historical_receive_clock_proven": False,
    }


def parse_price_archive(payload: bytes, symbol: str) -> ParsedArchive:
    """Uniform pinned PRICE_ONLY projection after exact FULL_KLINE defect check.

    The single known optional-field defect is retained, not repaired. All other
    full-field defects still fail closed. Zero optional fields are unavailable
    placeholders, not observations of zero market volume.
    """
    strict = parse_archive(payload, symbol, allow_known_xrp_rejection=True)
    quarantined: list[tuple[int, str]] = []
    prices = _parse_csv(
        payload,
        symbol,
        "1m",
        field_profile=ArchiveFieldProfile.PRICE_ONLY,
        quarantined_issues=quarantined,
    )
    selected = {row.open_time_ms: row for row in prices}
    if selected.keys() != strict.fields.keys() or len(selected) != len(prices):
        raise ValueError("exact PRICE_ONLY/raw membership required")
    if len(quarantined) != len(strict.rejected_fields):
        raise ValueError("exact known optional-field quarantine required")
    if any(
        (row.volume, row.quote_volume, row.taker_buy_volume, row.taker_buy_quote_volume) != (0, 0, 0, 0)
        for row in prices
    ):
        raise ValueError("uniform NOT_EXPOSED_PLACEHOLDER projection required")
    return ParsedArchive(symbol, strict.raw_sha256, strict.fields, selected, strict.rejected_fields)


def check_price_daily(archive: ParsedArchive, day: str) -> None:
    start = midnight_ms(day)
    if list(archive.fields) != list(range(start, start + DAY, MINUTE)):
        raise ValueError("complete exact PRICE_ONLY daily minute grid required")
    expected = (
        {REJECTED_XRP_SLOT: REJECTED_XRP_FIELDS}
        if archive.symbol == "XRPUSDT" and day == "2023-11-30"
        else {}
    )
    if archive.rejected_fields != expected or archive.candles.keys() != archive.fields.keys():
        raise ValueError("exact raw-bound optional-field quarantine required")


def check_price_overlap(monthly: ParsedArchive, daily: ParsedArchive, day: str) -> int:
    """Even the quarantined raw row must match all twelve fields exactly."""
    if monthly.symbol != daily.symbol:
        raise ValueError("same futures instrument required")
    check_price_daily(daily, day)
    matched = 0
    for slot, fields in daily.fields.items():
        if slot not in monthly.fields:
            continue
        if canonical_fields(fields) != canonical_fields(monthly.fields[slot]):
            raise ValueError(f"monthly/daily twelve-field conflict at {slot}")
        matched += 1
    return matched


def compose_price_month(
    monthly: ParsedArchive, month: str, daily_archives: dict[str, ParsedArchive]
) -> tuple[tuple[Candle, ...], dict[str, object]]:
    """Retain every monthly price/clock; add only fixed absent daily rows."""
    start, end = midnight_ms(month + "-01"), midnight_ms(next_month(month))
    expected = set(range(start, end, MINUTE))
    missing = expected - monthly.fields.keys()
    allowed_missing = {
        slot
        for day in MISSING_DAYS
        if day.startswith(month) and monthly.symbol in ("SOLUSDT", "XRPUSDT")
        for slot in range(midnight_ms(day), midnight_ms(day) + DAY, MINUTE)
    }
    rejection = (
        {REJECTED_XRP_SLOT: REJECTED_XRP_FIELDS} if monthly.symbol == "XRPUSDT" and month == "2023-11" else {}
    )
    if (
        any(not start <= slot < end for slot in monthly.fields)
        or missing != allowed_missing
        or monthly.rejected_fields != rejection
        or monthly.candles.keys() != monthly.fields.keys()
    ):
        raise ValueError("exact known PRICE_ONLY monthly membership required")
    required_days = {day for day in MISSING_DAYS if day.startswith(month) and allowed_missing}
    if rejection:
        required_days.add("2023-11-30")
    if set(daily_archives) != required_days:
        raise ValueError("exact fixed daily PRICE_ONLY composition files required")
    selected = dict(monthly.candles)
    raw = dict(monthly.fields)
    added, overlap = [], 0
    for day, daily in sorted(daily_archives.items()):
        overlap += check_price_overlap(monthly, daily, day)
        for slot, row in daily.candles.items():
            if slot in selected:
                continue
            if slot not in allowed_missing:
                raise ValueError("no PRICE_ONLY rejected-row replacement permitted")
            selected[slot], raw[slot] = row, daily.fields[slot]
            added.append(
                {
                    "open_time_ms": slot,
                    "kind": "ABSENT_ROW",
                    "daily_date": day,
                    "daily_raw_sha256": daily.raw_sha256,
                    "new_fields": daily.fields[slot],
                }
            )
    if set(selected) != expected or len(added) != len(allowed_missing):
        raise ValueError("complete exact composed PRICE_ONLY grid required")
    ordered = tuple(selected[slot] for slot in sorted(expected))
    fingerprint = hashlib.sha256()
    for slot in sorted(expected):
        fingerprint.update(json.dumps(canonical_fields(raw[slot]), separators=(",", ":")).encode() + b"\n")
    return ordered, {
        "symbol": monthly.symbol,
        "month": month,
        "rows": len(ordered),
        "gaps": 0,
        "monthly_raw_sha256": monthly.raw_sha256,
        "normalized_twelve_field_rows_sha256": fingerprint.hexdigest(),
        "valid_overlap_rows_compared": overlap,
        "added_rows": len(added),
        "replaced_rejected_rows": 0,
        "quarantined_optional_rows": len(rejection),
        "quarantine": [
            {
                "open_time_ms": slot,
                "raw_fields": fields,
                "reason": REJECTED_XRP_REASON,
                "price_and_clock_retained": True,
            }
            for slot, fields in rejection.items()
        ],
        "changes": added,
        "monthly_valid_rows_changed": 0,
        "optional_fields": "NOT_EXPOSED_PLACEHOLDER_NOT_OBSERVED_ZERO",
        "monthly_and_daily_not_independent_market_sources": True,
        "actual_historical_receive_clock_proven": False,
    }
