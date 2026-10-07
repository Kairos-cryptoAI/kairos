"""Input-only acceptance of one byte-bound, explicitly composed archive set.

Reuses the complete prior monthly audit only after proving exact raw-byte
membership. No old cache/receipt is changed and no generator is imported.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from kairos_backtest.data import month_starts
from kairos_backtest.factor_data import parse_funding

from .calendar_inputs import SOL_EXCEPTION_SHA, check_funding
from .inputs import UNIVERSE, _monthly_file_evidence, _sha
from .source_composition import (
    CONTROL_DAYS,
    MISSING_DAYS,
    check_overlap,
    check_price_overlap,
    compose_month,
    compose_price_month,
    midnight_ms,
    next_month,
    parse_archive,
    parse_price_archive,
)

PRIOR_AUDIT_SHA = "28b5bd74c983ed2761c1f6542566898ae7b5dd29a2edf645fbbcaac415b93db2"
RETRIEVAL_RECEIPT_SHA = "ea2ac4ab1229541f9adcbce9e18c4a180b84b8e49edfbf80d226f0ef27909217"
MONTHLY_PROBLEMS = {
    ("SOLUSDT", "2022-02"): "cc76e9bf78f5b9d6f23d5f4b9d95f37544e47ee0511717c16d8a4cc39e68ff8c",
    ("SOLUSDT", "2022-04"): "d7dd9e46951e917a5cb805a0d90d6bc45e597235da03f5984d9267af09858819",
    ("XRPUSDT", "2022-02"): "c2427ac93c91a589c62f10193b9672cd3e7cca23e219e444bc12c945d6a245e7",
    ("XRPUSDT", "2022-04"): "28a9f6c9cc7bcf6cadc5acc1cacf297f7a83193fd1e13858ebc5dc927cb3df7b",
    ("XRPUSDT", "2023-11"): "b817ca0a6478d73cfd50dfc224aab84ec7f15ed0129795c3df2c39e6ce08cc99",
}
DAILY_KEYS = tuple(
    sorted(
        [(symbol, day) for symbol in ("SOLUSDT", "XRPUSDT") for day in (*MISSING_DAYS, *CONTROL_DAYS)]
        + [("XRPUSDT", "2023-11-30")]
    )
)


def digest(value: Any) -> str:
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def file_binding(path: Path) -> tuple[bytes, dict[str, str]]:
    payload, receipt = _monthly_file_evidence(path)
    return payload, {key: value for key, value in receipt.items() if key != "path"}


def check_prior_archive(filename: str, payload: bytes, prior: dict[str, Any]) -> None:
    fingerprint = hashlib.sha256(filename.encode("ascii") + b"\0" + hashlib.sha256(payload).digest())
    if prior["status"] != "AUDITED" or fingerprint.hexdigest() != prior["inventory_sha256"]:
        raise ValueError("monthly bytes differ from the retained complete prior audit")


def check_official_retrieval(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    payload = path.read_bytes()
    if _sha(payload) != RETRIEVAL_RECEIPT_SHA:
        raise ValueError("exact retained official source-only retrieval receipt required")
    receipt = json.loads(payload)
    if receipt["state"] != "COMPLETED_SOURCE_ONLY" or not receipt["all_local_monthly_zips_unchanged"]:
        raise ValueError("complete retrieval and unchanged original monthly bytes required")
    records = receipt["daily_datasets"]
    if sorted((row["symbol"], row["date"]) for row in records) != list(DAILY_KEYS):
        raise ValueError("exact nineteen-file official retrieval roster required")
    result = {}
    for row in records:
        name = f"{row['symbol']}-1m-{row['date']}.zip"
        url = f"https://data.binance.vision/data/futures/um/daily/klines/{row['symbol']}/1m/{name}"
        if row["filename"] != name or row["zip_url"] != url or row["checksum_url"] != url + ".CHECKSUM":
            raise ValueError("fixed official futures/um source URL required")
        for field, expected_url in (("zip_response", url), ("checksum_response", url + ".CHECKSUM")):
            response = row[field]
            if (
                response["status"] != 200
                or response["url"] != expected_url
                or response["final_url"] != expected_url
            ):
                raise ValueError("official HTTPS retrieval escaped the fixed source")
        if row["declared_sha256"] != row["downloaded_zip_sha256"] or not row["checksum_matches"]:
            raise ValueError("retrieved source and official SHA disagree")
        result[row["symbol"], row["date"]] = row
    return result


def accept_source_set(
    audit_path: Path,
    bar_cache: Path,
    factor_cache: Path,
    daily_cache: Path,
    retrieval_path: Path,
    deadline: float,
    *,
    price_reference_only: bool = False,
) -> dict[str, Any]:
    prior_bytes = audit_path.read_bytes()
    if _sha(prior_bytes) != PRIOR_AUDIT_SHA:
        raise ValueError("exact immutable prior 255-file audit required")
    retrieved = check_official_retrieval(retrieval_path)
    audit = json.loads(prior_bytes)
    months = tuple(value.strftime("%Y-%m") for value in month_starts(date(2021, 11, 1), date(2026, 2, 1)))
    expected_keys = [(symbol, month) for symbol in UNIVERSE for month in months]
    prior_rows = audit["files"]
    if [(row["symbol"], row["month"]) for row in prior_rows] != expected_keys:
        raise ValueError("complete exact five-symbol 51-month prior roster required")
    prior = {(row["symbol"], row["month"]): row for row in prior_rows}

    def bounded() -> None:
        if time.monotonic() >= deadline:
            raise TimeoutError("input-only source acceptance deadline")

    daily, daily_files = {}, []
    for symbol, day in DAILY_KEYS:
        bounded()
        name = f"{symbol}-1m-{day}.zip"
        payload, binding = file_binding(daily_cache / symbol / "1m" / name)
        official = retrieved[symbol, day]
        if (
            binding["raw_sha256"] != official["downloaded_zip_sha256"]
            or binding["checksum_file_sha256"] != official["checksum_sidecar_sha256"]
        ):
            raise ValueError("daily input differs from the byte-bound official download receipt")
        parsed = (
            parse_price_archive(payload, symbol) if price_reference_only else parse_archive(payload, symbol)
        )
        # parse_archive is strict; check_daily is also enforced by every use below.
        daily[symbol, day] = parsed
        daily_files.append({"symbol": symbol, "date": day, "filename": name, **binding})
    bar_files, compositions, controls = [], [], []
    for symbol, month in expected_keys:
        bounded()
        name = f"{symbol}-1m-{month}.zip"
        payload, binding = file_binding(bar_cache / symbol / "1m" / name)
        row = prior[symbol, month]
        check_prior_archive(name, payload, row)
        lo, hi = midnight_ms(month + "-01"), midnight_ms(next_month(month))
        expected_rows = (hi - lo) // 60_000
        known_problem = (symbol, month) in MONTHLY_PROBLEMS
        if known_problem:
            if binding["raw_sha256"] != MONTHLY_PROBLEMS[symbol, month]:
                raise ValueError("fixed problematic monthly identity changed")
            parsed = (
                parse_price_archive(payload, symbol)
                if price_reference_only
                else parse_archive(payload, symbol, allow_known_xrp_rejection=month == "2023-11")
            )
            chosen = {day: daily[symbol, day] for day in MISSING_DAYS if day.startswith(month)}
            if symbol == "XRPUSDT" and month == "2023-11":
                chosen = {"2023-11-30": daily[symbol, "2023-11-30"]}
            _, composed = (compose_price_month if price_reference_only else compose_month)(
                parsed, month, chosen
            )
            compositions.append(composed)
        elif row["rows"] != expected_rows or row["gaps"] or row["invalid_rows"] or row["missing_minutes"]:
            raise ValueError("unexpected unresolved prior monthly coverage defect")
        relevant_controls = [day for day in CONTROL_DAYS if day.startswith(month)]
        if symbol in ("SOLUSDT", "XRPUSDT") and relevant_controls:
            parsed = (
                parse_price_archive(payload, symbol)
                if price_reference_only
                else parse_archive(payload, symbol)
            )
            for day in relevant_controls:
                matched = (check_price_overlap if price_reference_only else check_overlap)(
                    parsed, daily[symbol, day], day
                )
                if matched != 1_440:
                    raise ValueError("complete adjacent-day overlap required")
                controls.append({"symbol": symbol, "date": day, "matched_twelve_field_rows": matched})
        bar_files.append(
            {"symbol": symbol, "month": month, "filename": name, "rows": expected_rows, **binding}
        )
    if len(compositions) != 5 or len(controls) != 8:
        raise ValueError("complete fixed composition and adjacent-control roster required")
    if sum(row["added_rows"] for row in compositions) != 14_400:
        raise ValueError("exact known 14400 missing symbol-minute membership required")
    if sum(row["replaced_rejected_rows"] for row in compositions) != (0 if price_reference_only else 1):
        raise ValueError("exact profile-specific XRP row policy required")
    if price_reference_only and sum(row["quarantined_optional_rows"] for row in compositions) != 1:
        raise ValueError("exact single raw-bound optional-field quarantine required")

    funding_files = []
    for symbol, month in expected_keys:
        bounded()
        name = f"{symbol}-fundingRate-{month}.zip"
        payload, binding = file_binding(factor_cache / "fundingRate" / symbol / name)
        if symbol == "SOLUSDT" and month == "2022-11" and binding["raw_sha256"] != SOL_EXCEPTION_SHA:
            raise ValueError("unchanged exceptional funding archive required")
        lo, hi = midnight_ms(month + "-01"), midnight_ms(next_month(month))
        observations = list(parse_funding(payload, symbol, name))
        if any(not lo <= event.timestamp_ms < hi for event in observations):
            raise ValueError("funding event outside its monthly partition")
        selected, offset = check_funding(symbol, observations, lo, hi)
        funding_files.append(
            {
                "symbol": symbol,
                "month": month,
                "filename": name,
                "rows": len(selected),
                "max_event_offset_ms": offset,
                **binding,
            }
        )

    # Recheck every accepted source byte and sidecar after the input-only checks.
    for root, files, folder in (
        (bar_cache, bar_files, "bars"),
        (factor_cache, funding_files, "funding"),
        (daily_cache, daily_files, "daily"),
    ):
        for record in files:
            bounded()
            parent = (
                root / "fundingRate" / record["symbol"]
                if folder == "funding"
                else root / record["symbol"] / "1m"
            )
            _, current = file_binding(parent / record["filename"])
            if any(current[key] != record[key] for key in ("raw_sha256", "checksum_file_sha256")):
                raise ValueError("accepted source changed during input-only qualification")
    identity = {"bars": bar_files, "funding": funding_files, "daily": daily_files}
    return {
        "schema": (
            "kairos.strategy.price-reference-source-set.v1"
            if price_reference_only
            else "kairos.strategy.composed-source-set.v1"
        ),
        "state": "INPUT_ONLY_ACCEPTED",
        "prior_audit_sha256": PRIOR_AUDIT_SHA,
        "official_retrieval_receipt_sha256": RETRIEVAL_RECEIPT_SHA,
        "source_files_sha256": digest(identity),
        **identity,
        "compositions": compositions,
        "adjacent_controls": controls,
        "valid_monthly_rows_changed": 0,
        "added_symbol_minutes": 14_400,
        "replaced_rejected_rows": 0 if price_reference_only else 1,
        "field_profile": "PRICE_ONLY" if price_reference_only else "FULL_KLINE",
        "quarantined_optional_rows": 1 if price_reference_only else 0,
        "optional_fields": "NOT_EXPOSED_PLACEHOLDER_NOT_OBSERVED_ZERO"
        if price_reference_only
        else "FULL_KLINE",
        "allowed_consumers": (
            ["right_tail_trend_v1", "regime_aligned_right_tail_v1", "COMMON_COST_RISK"]
            if price_reference_only
            else []
        ),
        "expected_monthly_rows_all_symbols": sum(row["rows"] for row in bar_files),
        "source_policy": (
            "MONTHLY_PRICES_AND_CLOCKS_UNCHANGED_EXACT_ABSENT_DAILY_ROWS_ONLY"
            if price_reference_only
            else "VALID_MONTHLY_WINS_EXACT_FIXED_ABSENT_OR_REJECTED_SLOTS_ONLY"
        ),
        "market_source_independence": False,
        "economic_cells": 0,
        "historical_receive_clock_proven": False,
        "historical_prices_independently_authenticated": False,
        "funding_pre_correction_inventory_equality_proven": False,
        "trading_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prior-audit", "bar-cache", "factor-cache", "daily-cache", "retrieval-receipt", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument(
        "--price-reference-only",
        action="store_true",
        help="separate two-reference PRICE_ONLY contract; never FULL_KLINE acceptance",
    )
    args = parser.parse_args()
    paths = [
        getattr(args, name).resolve()
        for name in ("prior_audit", "bar_cache", "factor_cache", "daily_cache", "retrieval_receipt")
    ]
    output = args.output.resolve()
    for protected in paths:
        if output == protected or output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("source acceptance output cannot overlap any retained input")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    write_json(
        output / "before.json", {"state": "INPUT_ONLY", "started_utc": utc_now(), "max_wall_seconds": 180}
    )
    try:
        result = accept_source_set(
            *paths, deadline=started + 180, price_reference_only=args.price_reference_only
        )
        write_json(
            output / "source-set.json",
            {**result, "finished_utc": utc_now(), "elapsed_seconds": time.monotonic() - started},
        )
        return 0
    except Exception as exc:
        write_json(
            output / "failure.json",
            {
                "state": "FAILED_CLOSED",
                "error_type": type(exc).__name__,
                "reason": str(exc),
                "economic_cells": 0,
            },
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
