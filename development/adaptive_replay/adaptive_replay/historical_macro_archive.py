"""Offline, fixed-scope CPI semantics from the retained ALFRED artifact.

This is not source authentication, full macro coverage, NEWS readiness, or a
historical local-receipt claim. ZIP members are read in memory only.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

RAW_SHA256 = "a8ebaf703c3db79ed0997f083b4a488f3d7302db46afed666ede82e41e8835a4"
REQUEST_SHA256 = "7627d8a1292b6843ee94e6de48cfe88992e4e52a7ee2b3922a257e2f58c8d3d5"
RECEIPT_SHA256 = "6f2aff0b2f8742b62eaf05292b6f464bc9c7d6b0b535448d3ebf77f3ed13418a"
PLAN_SHA256 = "d9347eeca568f6b8fc98a75645ffe484e27df2ce3cd84415b97f8b554d12e497"
SOURCE_URL = "https://alfred.stlouisfed.org/series/downloaddata?seid=CPIAUCSL"
CSV_NAME = "vintages_starting_2021-05-18.csv"
README_SHA256 = "dc393de0cbb07585fc56dd983b9f754753e563f4fcf32ecd7483abd6cc595938"
CSV_SHA256 = "a66a2035c33d36e51a64a47da9200cb6c4d48c2e8aa9d0da1999a27f7b94b034"
PROFILE_SHA256 = "9cd67575623f616e12dae4f27989022a27e14d489cf307d926f050629c786421"
MAX_RAW = 1_048_576
MAX_EXPANDED = 2_097_152
START, END = date(2021, 4, 1), date(2023, 11, 1)
RELEASES = {"2021-05-18": "2021-05-12", "2024-01-08": "2023-12-12"}


@dataclass(frozen=True)
class MacroObservation:
    metric: str
    value: str
    unit: str
    observation_date: str
    vintage_date: str
    release_date: str
    available_upper_utc: str
    availability_basis: str = "DAY_BEFORE_CUT_END_OF_DAY_UPPER_BOUND_NOT_INTRADAY_RECEIPT"


@dataclass(frozen=True)
class HistoricalMacroArchive:
    source_url: str
    source_profile_sha256: str
    plan_sha256: str
    raw_sha256: str
    request_sha256: str
    receipt_sha256: str
    metric_scope: tuple[str, ...]
    observations: tuple[MacroObservation, ...]
    semantic_validation_only: bool = True
    source_authenticity_verified: bool = False
    full_macro_coverage_guaranteed: bool = False
    historical_receive_clock_proven: bool = False
    news_accepted: bool = False
    required_sources_ready: bool = False


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(raw: bytes) -> dict:
    obj = json.loads(
        raw.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite"))
    )
    if type(obj) is not dict or json.dumps(obj, sort_keys=True, separators=(",", ":")).encode() != raw:
        raise ValueError("noncanonical capture receipt")
    return obj


def _check_capture_order(request: dict, receipt: dict) -> None:
    if receipt.get("actual_captured_ms", 0) < request.get("actual_requested_ms", 0):
        raise ValueError("capture cannot predate request")


def _safe_members(raw: bytes) -> dict[str, bytes]:
    if not raw or len(raw) > MAX_RAW:
        raise ValueError("bounded ZIP bytes required")
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        infos = zf.infolist()
        if (
            len(infos) != 2
            or {i.filename for i in infos} != {"README.txt", CSV_NAME}
            or sum(i.file_size for i in infos) > MAX_EXPANDED
        ):
            raise ValueError("unexpected ZIP inventory")
        if any(
            i.is_dir() or "/" in i.filename or "\\" in i.filename or ":" in i.filename or i.flag_bits & 1
            for i in infos
        ):
            raise ValueError("unsafe ZIP member")
        result = {i.filename: zf.read(i) for i in infos}
        if any(len(result[i.filename]) != i.file_size for i in infos):
            raise ValueError("truncated ZIP member")
        return result


def _decimal(cell: str) -> str:
    if re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", cell) is None:
        raise ValueError("noncanonical/nonpositive macro value")
    try:
        number = Decimal(cell)
    except InvalidOperation:
        raise ValueError("invalid decimal macro value") from None
    if not number.is_finite() or number <= 0:
        raise ValueError("nonfinite/nonpositive macro value")
    return cell


def extract(raw_path: Path, request_path: Path, receipt_path: Path) -> HistoricalMacroArchive:
    """Validate only the known captured artifact; never fetch, extract-to-disk, or fallback."""
    raw, req_bytes, rec_bytes = raw_path.read_bytes(), request_path.read_bytes(), receipt_path.read_bytes()
    if (
        len(raw) > MAX_RAW
        or _sha(raw) != RAW_SHA256
        or _sha(req_bytes) != REQUEST_SHA256
        or _sha(rec_bytes) != RECEIPT_SHA256
    ):
        raise ValueError("retained artifact digest mismatch")
    req, rec = _canonical_json(req_bytes), _canonical_json(rec_bytes)
    expected_fields = {
        "form[units]": "lin",
        "form[obs_start_date]": "2021-04-01",
        "form[obs_end_date]": "2023-11-01",
        "form[entered_vintage_dates]": "2021-05-18 2024-01-08",
        "form[file_type]": "2",
        "form[file_format]": "csv",
        "form[download_data]": "",
    }
    if (
        req.get("fields") != expected_fields
        or rec.get("fields") != expected_fields
        or req.get("url") != SOURCE_URL
        or rec.get("url") != SOURCE_URL
        or req.get("pilot_plan_sha256") != PLAN_SHA256
        or rec.get("pilot_plan_sha256") != PLAN_SHA256
        or rec.get("state") != "RAW_VINTAGE_DOWNLOAD_CAPTURED_UNADMITTED"
        or rec.get("coverage") != "UNKNOWN"
        or rec.get("admitted_to_prompt") is not False
        or rec.get("historical_receive_clock_proven") is not False
        or rec.get("raw_sha256") != RAW_SHA256
        or rec.get("raw_file") != "alfred-cpiaucsl-vintages.raw"
    ):
        raise ValueError("capture scope or timing receipt mismatch")
    _check_capture_order(req, rec)
    source_profile = hashlib.sha256(
        (SOURCE_URL + "\nCPIAUCSL\nlin\nmonthly\nSA\n1982-1984=100\n").encode()
    ).hexdigest()
    if source_profile != PROFILE_SHA256:
        raise ValueError("fixed source profile mismatch")
    members = _safe_members(raw)
    if _sha(members["README.txt"]) != README_SHA256 or _sha(members[CSV_NAME]) != CSV_SHA256:
        raise ValueError("ZIP member digest mismatch")
    readme = members["README.txt"].decode("utf-8", errors="strict")
    if not all(
        s in readme.lower() for s in ("2021-05-18", "2024-01-08", "bls", "monthly", "seasonally adjusted")
    ) or not re.search(r"1982\s*[-–]\s*1984\s*=\s*100", readme):
        raise ValueError("README series metadata mismatch")
    rows = list(csv.reader(io.StringIO(members[CSV_NAME].decode("utf-8-sig", errors="strict"), newline="")))
    if (
        not rows
        or rows[0] != ["observation_date", "CPIAUCSL_20210518", "CPIAUCSL_20240108"]
        or len(rows) != 33
    ):
        raise ValueError("unexpected CSV shape/columns")
    parsed, expected_dates = [], []
    y, m = START.year, START.month
    while (y, m) <= (END.year, END.month):
        expected_dates.append(date(y, m, 1).isoformat())
        m += 1
        if m == 13:
            y, m = y + 1, 1
    seen = set()
    for row, expected in zip(rows[1:], expected_dates, strict=True):
        if len(row) != 3 or row[0] != expected or row[0] in seen:
            raise ValueError("duplicate, extra, or noncontiguous observation")
        seen.add(row[0])
        vals = []
        for cell in row[1:]:
            if cell == "":
                vals.append(None)
            else:
                vals.append(_decimal(cell))
        parsed.append((row[0], vals))
    if len(seen) != 32:
        raise ValueError("observation count mismatch")
    by_date = {d: vals for d, vals in parsed}
    if by_date["2021-04-01"] != ["266.832", "266.670"] or by_date["2023-11-01"][1] != "307.917":
        raise ValueError("fixed-vintage sentinel mismatch")
    # The early vintage contains April only; do not forward-fill later months.
    if any(a is not None for d, (a, _) in parsed if d > "2021-04-01"):
        raise ValueError("future observations present in early vintage")

    # Conservative upper bounds: end of vintage day preceding each cut.
    a = MacroObservation(
        "CPIAUCSL",
        "266.832",
        "index 1982-1984=100, seasonally adjusted",
        "2021-04-01",
        "2021-05-18",
        RELEASES["2021-05-18"],
        "2021-05-18T23:59:59.999Z",
    )
    d = MacroObservation(
        "CPIAUCSL",
        "307.917",
        "index 1982-1984=100, seasonally adjusted",
        "2023-11-01",
        "2024-01-08",
        RELEASES["2024-01-08"],
        "2024-01-08T23:59:59.999Z",
    )
    # Release dates audited independently from first-party BLS release calendar.
    return HistoricalMacroArchive(
        SOURCE_URL,
        source_profile,
        PLAN_SHA256,
        RAW_SHA256,
        REQUEST_SHA256,
        RECEIPT_SHA256,
        ("CPIAUCSL",),
        (a, d),
    )
