"""Byte-bound PRICE_ONLY inputs for two fixed slow reference consumers only.

No downloads, raw rewrites, native strategy changes or trading authority.
Optional zero fields are unavailable placeholders, never measured volume.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from kairos_backtest.data import ArchiveFieldProfile, _parse_csv, month_starts
from kairos_backtest.factor_data import parse_funding

from .calendar_inputs import check_funding
from .inputs import UNIVERSE, WindowInputs
from .source_composition import (
    MISSING_DAYS,
    compose_price_month,
    midnight_ms,
    next_month,
    parse_price_archive,
)
from .source_set import MONTHLY_PROBLEMS, PRIOR_AUDIT_SHA, RETRIEVAL_RECEIPT_SHA, digest, file_binding

CONSUMERS = ["right_tail_trend_v1", "regime_aligned_right_tail_v1", "COMMON_COST_RISK"]


def read_acceptance(path: Path, expected_sha256: str) -> dict[str, Any]:
    payload = path.read_bytes()
    if path.suffix == ".gz":
        payload = gzip.decompress(payload)
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("signed price-reference source acceptance bytes changed")
    receipt = json.loads(payload)
    if (
        receipt["schema"] != "kairos.strategy.price-reference-source-set.v1"
        or receipt["state"] != "INPUT_ONLY_ACCEPTED"
        or receipt["field_profile"] != "PRICE_ONLY"
        or receipt["prior_audit_sha256"] != PRIOR_AUDIT_SHA
        or receipt["official_retrieval_receipt_sha256"] != RETRIEVAL_RECEIPT_SHA
        or receipt["added_symbol_minutes"] != 14400
        or receipt["replaced_rejected_rows"] != 0
        or receipt["quarantined_optional_rows"] != 1
        or receipt["economic_cells"] != 0
        or receipt["trading_authority"] is not False
        or receipt["allowed_consumers"] != CONSUMERS
        or receipt["optional_fields"] != "NOT_EXPOSED_PLACEHOLDER_NOT_OBSERVED_ZERO"
    ):
        raise ValueError("exact two-reference PRICE_ONLY acceptance required")
    months = [m.strftime("%Y-%m") for m in month_starts(date(2021, 11, 1), date(2026, 2, 1))]
    keys = [(s, m) for s in UNIVERSE for m in months]
    for kind in ("bars", "funding"):
        if [(r["symbol"], r["month"]) for r in receipt[kind]] != keys:
            raise ValueError("complete accepted source roster required")
    identity = {kind: receipt[kind] for kind in ("bars", "funding", "daily")}
    if digest(identity) != receipt["source_files_sha256"]:
        raise ValueError("accepted source inventory identity changed")
    return receipt


def bound_payload(path: Path, record: dict[str, Any]) -> bytes:
    payload, binding = file_binding(path)
    if path.name != record["filename"] or any(binding[k] != record[k] for k in binding):
        raise ValueError("accepted raw source or sidecar changed")
    return payload


def verify_sources(receipt: dict[str, Any], bars: Path, factors: Path, daily: Path, deadline: float) -> None:
    for kind, root in (("bars", bars), ("funding", factors), ("daily", daily)):
        for record in receipt[kind]:
            if time.monotonic() >= deadline:
                raise TimeoutError("price-reference source verification bound")
            parent = (
                root / "fundingRate" / record["symbol"]
                if kind == "funding"
                else root / record["symbol"] / "1m"
            )
            bound_payload(parent / record["filename"], record)


def load_window(
    bars_root: Path,
    factors_root: Path,
    daily_root: Path,
    window: dict[str, str],
    acceptance: dict[str, Any],
    deadline: float,
) -> WindowInputs:
    start, end = midnight_ms(window["start"]), midnight_ms(window["end_exclusive"])
    lo, hi = start - 35 * 86400000, end + 3 * 86400000
    months = [
        m.strftime("%Y-%m")
        for m in month_starts(
            datetime.fromtimestamp(lo / 1000, UTC).date(), datetime.fromtimestamp(hi / 1000, UTC).date()
        )
    ]
    records = {
        kind: {(r["symbol"], r["date"] if kind == "daily" else r["month"]): r for r in acceptance[kind]}
        for kind in ("bars", "funding", "daily")
    }
    bars, funding, bar_evidence, funding_evidence = {}, {}, {}, {}
    for symbol in UNIVERSE:
        selected, archives = [], []
        quarantine = 0
        for month in months:
            if time.monotonic() >= deadline:
                raise TimeoutError("PRICE_ONLY calendar input bound")
            record = records["bars"][symbol, month]
            payload = bound_payload(bars_root / symbol / "1m" / record["filename"], record)
            if (symbol, month) in MONTHLY_PROBLEMS:
                parsed = parse_price_archive(payload, symbol)
                days = [d for d in MISSING_DAYS if d.startswith(month)]
                if symbol == "XRPUSDT" and month == "2023-11":
                    days = ["2023-11-30"]
                dailies = {}
                for day in days:
                    daily_record = records["daily"][symbol, day]
                    raw = bound_payload(daily_root / symbol / "1m" / daily_record["filename"], daily_record)
                    dailies[day] = parse_price_archive(raw, symbol)
                rows, composition = compose_price_month(parsed, month, dailies)
                quarantine += composition["quarantined_optional_rows"]
            else:
                issues: list[tuple[int, str]] = []
                rows = tuple(
                    _parse_csv(
                        payload,
                        symbol,
                        "1m",
                        field_profile=ArchiveFieldProfile.PRICE_ONLY,
                        quarantined_issues=issues,
                    )
                )
                if issues:
                    raise ValueError("unexpected optional-field quarantine")
            month_lo, month_hi = midnight_ms(month + "-01"), midnight_ms(next_month(month))
            if len(rows) != (month_hi - month_lo) // 60000 or any(
                c.open_time_ms != month_lo + i * 60000 or c.close_time_ms != c.open_time_ms + 59999
                for i, c in enumerate(rows)
            ):
                raise ValueError("complete exact price month grid required")
            selected.extend(c for c in rows if lo <= c.open_time_ms < hi)
            archives.append(record)
        if len(selected) != (hi - lo) // 60000 or any(
            c.open_time_ms != lo + i * 60000
            or c.close_time_ms != c.open_time_ms + 59999
            or (c.volume, c.quote_volume, c.taker_buy_volume, c.taker_buy_quote_volume) != (0, 0, 0, 0)
            for i, c in enumerate(selected)
        ):
            raise ValueError("complete uniform price prefix/year/tail required")
        bars[symbol] = tuple(selected)
        fingerprint = hashlib.sha256()
        for c in selected:
            fingerprint.update(
                json.dumps(
                    [c.open_time_ms, c.close_time_ms, c.open, c.high, c.low, c.close], separators=(",", ":")
                ).encode()
                + b"\n"
            )
        bar_evidence[symbol] = {
            "rows": len(selected),
            "gaps": 0,
            "field_profile": "PRICE_ONLY",
            "quarantined_optional_rows": quarantine,
            "price_rows_sha256": fingerprint.hexdigest(),
            "optional_fields": "NOT_EXPOSED_PLACEHOLDER_NOT_OBSERVED_ZERO",
            "archives": archives,
        }
        observations, archives = [], []
        for month in months:
            if time.monotonic() >= deadline:
                raise TimeoutError("PRICE_ONLY funding input bound")
            record = records["funding"][symbol, month]
            payload = bound_payload(factors_root / "fundingRate" / symbol / record["filename"], record)
            parsed_funding = parse_funding(payload, symbol, record["filename"])
            month_lo, month_hi = midnight_ms(month + "-01"), midnight_ms(next_month(month))
            if any(not month_lo <= e.timestamp_ms < month_hi for e in parsed_funding):
                raise ValueError("funding event outside accepted month")
            check_funding(symbol, list(parsed_funding), month_lo, month_hi)
            observations.extend(parsed_funding)
            archives.append(record)
        chosen, offset = check_funding(symbol, observations, lo, hi)
        funding[symbol] = chosen
        funding_evidence[symbol] = {
            "rows": len(chosen),
            "normalized_rows_sha256": digest([asdict(e) for e in chosen]),
            "interval_counts": dict(sorted(Counter(e.interval_hours for e in chosen).items())),
            "max_event_offset_ms": offset,
            "timestamps_rounded": False,
            "archives": archives,
            "schedule_authority": "FIXED_ARCHIVE_SCHEDULE_CONSISTENCY_NOT_EXTERNAL_AUTHENTICATION",
            "clock_authority": "ARCHIVE_CALC_TIME_ENTITLEMENT_PROXY",
        }
        print(f"phase=price_inputs_checked symbol={symbol}", flush=True)
    return WindowInputs(
        bars,
        funding,
        {
            "window_id": window["id"],
            "bar_start_ms": lo,
            "bar_end_ms": hi,
            "bars": bar_evidence,
            "funding": funding_evidence,
            "funding_for_entry_decisions": False,
        },
        start,
        end,
        lo,
        hi,
    )
