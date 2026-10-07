"""Bounded, read-only reference selection from official daily aggTrades ZIPs.

This module records transaction-time witnesses only.  It does not estimate
local receive time, fills, quote availability, capacity, or trading returns.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from kairos_backtest.aggtrades import (
    AggTrade,
    _canonical_trade_line,
    _is_header,
    _parse_row,
)

_CHUNK = 1024 * 1024
_DEFAULT_COMPRESSED = 96 * 1024 * 1024
_DEFAULT_UNCOMPRESSED = 768 * 1024 * 1024
_DEFAULT_ROWS = 5_000_000
_SYMBOL = re.compile(r"^[A-Z0-9]{2,30}USDT$")


@dataclass(frozen=True, slots=True)
class EntryRequest:
    symbol: str
    intent_id: str
    decision_ts_ms: int
    entry_eligible_ts_ms: int
    expires_ts_ms: int
    completion_ts_ms: int
    transport_delay_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not _SYMBOL.fullmatch(self.symbol):
            raise ValueError("symbol must be an uppercase USDT symbol")
        if not isinstance(self.intent_id, str) or not self.intent_id.strip():
            raise ValueError("intent_id must be nonempty")
        for name in (
            "decision_ts_ms",
            "entry_eligible_ts_ms",
            "expires_ts_ms",
            "completion_ts_ms",
            "transport_delay_ms",
        ):
            if type(getattr(self, name)) is not int:
                raise TypeError(f"{name} must be an integer clock")
        if self.decision_ts_ms < 0:
            raise ValueError("decision clock cannot be negative")
        if self.entry_eligible_ts_ms != self.decision_ts_ms + 1:
            raise ValueError("entry eligibility must be decision + 1 ms")
        if self.expires_ts_ms != self.decision_ts_ms + 60_000:
            raise ValueError("entry expiry must be decision + 60 seconds")
        if self.completion_ts_ms < self.decision_ts_ms:
            raise ValueError("completion cannot precede decision")
        if self.transport_delay_ms < 0:
            raise ValueError("transport delay cannot be negative")

    @property
    def arrival_ts_ms(self) -> int:
        return max(self.entry_eligible_ts_ms, self.completion_ts_ms) + self.transport_delay_ms


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("daily aggTrades scan deadline exceeded")


def _sha256(path: Path, deadline: float) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK):
            _check_deadline(deadline)
            digest.update(chunk)
    return digest.hexdigest()


def _stat_signature(path: Path) -> tuple[int, int, int]:
    info = path.stat()
    return info.st_size, info.st_mtime_ns, getattr(info, "st_ino", 0)


def _event(trade: AggTrade) -> dict[str, Any]:
    return {
        "aggregate_trade_id": trade.aggregate_trade_id,
        "price": str(trade.price),
        "quantity": str(trade.quantity),
        "first_trade_id": trade.first_trade_id,
        "last_trade_id": trade.last_trade_id,
        "transact_time_ms": trade.transact_time_ms,
        "buyer_is_maker": trade.buyer_is_maker,
    }


def _validate_limits(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def scan_daily_archive(
    path: str | Path,
    checksum_path: str | Path,
    symbol: str,
    day: date,
    requests: list[EntryRequest],
    deadline: float,
    max_compressed_bytes: int = _DEFAULT_COMPRESSED,
    max_uncompressed_bytes: int = _DEFAULT_UNCOMPRESSED,
    max_rows: int = _DEFAULT_ROWS,
) -> dict[str, Any]:
    """Verify and stream one cached Binance daily archive against requests.

    The checksum is consistency evidence for the supplied official sidecar;
    this function does not fetch or independently authenticate a publisher.
    """

    _validate_limits(max_compressed_bytes, "max_compressed_bytes")
    _validate_limits(max_uncompressed_bytes, "max_uncompressed_bytes")
    _validate_limits(max_rows, "max_rows")
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
        raise ValueError("deadline must be a finite monotonic timestamp")
    if not isinstance(day, date) or isinstance(day, datetime):
        raise TypeError("day must be a date")
    if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
        raise ValueError("symbol must be an uppercase USDT symbol")
    if not isinstance(requests, list) or any(not isinstance(req, EntryRequest) for req in requests):
        raise TypeError("requests must be a list of EntryRequest values")
    identifiers: set[str] = set()
    for req in requests:
        if req.symbol != symbol:
            raise ValueError("request symbol does not match archive")
        if req.intent_id in identifiers:
            raise ValueError("intent IDs must be unique")
        identifiers.add(req.intent_id)

    archive = Path(path)
    sidecar = Path(checksum_path)
    filename = f"{symbol}-aggTrades-{day.isoformat()}.zip"
    if archive.name != filename:
        raise ValueError("archive filename does not match symbol/day")
    expected_member = f"{symbol}-aggTrades-{day.isoformat()}.csv"
    start_ms = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)
    end_ms = start_ms + 86_400_000
    if any(not start_ms <= req.entry_eligible_ts_ms < end_ms for req in requests):
        raise ValueError("request eligibility must be inside the archive UTC day")
    _check_deadline(float(deadline))
    archive_before = _stat_signature(archive)
    sidecar_before = _stat_signature(sidecar)
    if archive_before[0] > max_compressed_bytes:
        raise ValueError("compressed archive exceeds configured byte limit")
    if sidecar_before[0] > 512:
        raise ValueError("checksum sidecar exceeds bounded size")

    sidecar_bytes = sidecar.read_bytes()
    _check_deadline(float(deadline))
    if len(sidecar_bytes) > 512:
        raise ValueError("checksum sidecar exceeds bounded size")
    try:
        fields = sidecar_bytes.decode("ascii").strip().split()
    except UnicodeDecodeError as exc:
        raise ValueError("checksum sidecar is not ASCII") from exc
    if len(fields) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", fields[0]):
        raise ValueError("checksum sidecar must contain SHA256 and filename")
    if fields[1].removeprefix("*") != filename:
        raise ValueError("checksum filename does not match archive")
    archive_sha = _sha256(archive, float(deadline))
    if archive_sha.lower() != fields[0].lower():
        raise ValueError("archive SHA256 does not match sidecar")
    sidecar_sha = hashlib.sha256(sidecar_bytes).hexdigest()

    states: list[dict[str, Any]] = []
    for req in requests:
        states.append(
            {
                "request": req,
                "arrival": req.arrival_ts_ms,
                "expiry": req.expires_ts_ms,
                "reference": None,
                "reference_predecessor": None,
                "strict_predecessor": None,
                "strict_successor": None,
                "gap_tainted": False,
            }
        )

    digest = hashlib.sha256()
    previous: AggTrade | None = None
    first: AggTrade | None = None
    rows = 0
    uncompressed_bytes = 0
    aggregate_gap_count = aggregate_gap_missing = 0
    raw_gap_count = raw_gap_missing = 0
    with archive.open("rb") as raw_archive:
        with zipfile.ZipFile(raw_archive, "r") as zf:
            members = zf.infolist()
            if len(members) != 1 or members[0].filename != expected_member:
                raise ValueError("ZIP must contain exactly the expected daily CSV member")
            info = members[0]
            if info.is_dir() or info.flag_bits & 1 or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("ZIP member cannot be a directory or encrypted")
            if info.file_size > max_uncompressed_bytes:
                raise ValueError("uncompressed member exceeds configured byte limit")

            with zf.open(info, "r") as member:
                text = io.TextIOWrapper(member, encoding="utf-8", newline="")

                def bounded_lines():
                    nonlocal uncompressed_bytes
                    while True:
                        _check_deadline(float(deadline))
                        line = text.readline(513)
                        if not line:
                            return
                        encoded_size = len(line.encode("utf-8"))
                        uncompressed_bytes += encoded_size
                        if len(line.rstrip("\r\n")) > 512:
                            raise ValueError("CSV physical line exceeds 512 characters")
                        if uncompressed_bytes > max_uncompressed_bytes:
                            raise ValueError("uncompressed member exceeds configured byte limit")
                        yield line

                reader = csv.reader(bounded_lines(), strict=True)
                header_checked = False
                for row_number, row in enumerate(reader, start=1):
                    _check_deadline(float(deadline))
                    if not header_checked:
                        header_checked = True
                        if _is_header(row):
                            continue
                    if rows >= max_rows:
                        raise ValueError("row count exceeds configured limit")
                    trade = _parse_row(row, row_number=row_number, start_ms=start_ms, end_ms=end_ms)
                    if previous is not None:
                        if trade.aggregate_trade_id <= previous.aggregate_trade_id:
                            raise ValueError("aggregate trade IDs are not strictly increasing")
                        if trade.transact_time_ms < previous.transact_time_ms:
                            raise ValueError("transaction timestamps are decreasing")
                        if trade.first_trade_id <= previous.last_trade_id:
                            raise ValueError("raw trade ID ranges overlap or are not increasing")
                        agg_missing = trade.aggregate_trade_id - previous.aggregate_trade_id - 1
                        if agg_missing:
                            aggregate_gap_count += 1
                            aggregate_gap_missing += agg_missing
                        raw_missing = trade.first_trade_id - previous.last_trade_id - 1
                        if raw_missing:
                            raw_gap_count += 1
                            raw_gap_missing += raw_missing
                    else:
                        first = trade

                    for request_index, state in enumerate(states):
                        if request_index % 256 == 0:
                            _check_deadline(float(deadline))
                        if trade.transact_time_ms < state["arrival"]:
                            state["strict_predecessor"] = _event(trade)
                        if trade.transact_time_ms > state["expiry"] and state["strict_successor"] is None:
                            state["strict_successor"] = _event(trade)
                        if (
                            state["reference"] is None
                            and state["arrival"] <= trade.transact_time_ms <= state["expiry"]
                        ):
                            state["reference"] = _event(trade)
                            state["reference_predecessor"] = (
                                _event(previous) if previous is not None else None
                            )
                        if (
                            previous is not None
                            and trade.aggregate_trade_id > previous.aggregate_trade_id + 1
                        ):
                            if (
                                previous.transact_time_ms <= state["expiry"]
                                and trade.transact_time_ms >= state["arrival"]
                            ):
                                state["gap_tainted"] = True
                    digest.update(_canonical_trade_line(trade))
                    previous = trade
                    rows += 1
                text.detach()
            # Reading to EOF above causes zipfile to validate the member CRC.
    _check_deadline(float(deadline))
    if rows == 0 or first is None or previous is None:
        raise ValueError("daily aggregate-trade archive contains no rows")
    if _stat_signature(archive) != archive_before or _stat_signature(sidecar) != sidecar_before:
        raise RuntimeError("archive or checksum changed during scan")
    if _sha256(archive, float(deadline)) != archive_sha:
        raise RuntimeError("archive bytes changed during scan")
    if hashlib.sha256(sidecar.read_bytes()).hexdigest() != sidecar_sha:
        raise RuntimeError("checksum sidecar bytes changed during scan")

    resolved: list[dict[str, Any]] = []
    for state in states:
        req: EntryRequest = state["request"]
        if state["arrival"] > state["expiry"]:
            status = "EXPIRED_BEFORE_ARRIVAL"
        elif state["strict_predecessor"] is None or state["strict_successor"] is None:
            status = "BOUNDARY_UNPROVEN"
        elif state["gap_tainted"]:
            status = "GAP_TAINTED"
        elif state["reference"] is not None:
            status = "RECORDED_PRINT_REFERENCE"
        else:
            status = "NO_RECORDED_PRINT_IN_ASSUMED_WINDOW"
        reference = state["reference"]
        resolved.append(
            {
                "intent_id": req.intent_id,
                "decision_ts_ms": req.decision_ts_ms,
                "entry_eligible_ts_ms": req.entry_eligible_ts_ms,
                "expires_ts_ms": req.expires_ts_ms,
                "completion_ts_ms_assumed": req.completion_ts_ms,
                "transport_delay_ms_assumed": req.transport_delay_ms,
                "arrival_ts_ms_assumed": state["arrival"],
                "status": status,
                "first_reference": reference,
                "immediate_predecessor": state["reference_predecessor"],
                "strict_pre_window_predecessor": state["strict_predecessor"],
                "strict_post_window_successor": state["strict_successor"],
                "wait_ms": reference["transact_time_ms"] - state["arrival"] if reference else None,
                "aggregate_gap_intersects_window": state["gap_tainted"],
            }
        )

    return {
        "schema": "kairos.intraday-reference-scan.v1",
        "symbol": symbol,
        "day": day.isoformat(),
        "archive_filename": filename,
        "archive_sha256": archive_sha,
        "checksum_sidecar_sha256": sidecar_sha,
        "archive_bytes": archive_before[0],
        "member_filename": expected_member,
        "rows": rows,
        "uncompressed_bytes": uncompressed_bytes,
        "normalized_rows_sha256": digest.hexdigest(),
        "first_transact_time_ms": first.transact_time_ms,
        "last_transact_time_ms": previous.transact_time_ms,
        "first_aggregate_trade_id": first.aggregate_trade_id,
        "last_aggregate_trade_id": previous.aggregate_trade_id,
        "aggregate_id_gap_count": aggregate_gap_count,
        "missing_aggregate_ids_observed": aggregate_gap_missing,
        "raw_id_gap_count": raw_gap_count,
        "missing_raw_ids_observed": raw_gap_missing,
        "raw_gap_semantics": "unknown_and_excluded; not evidence of missing market trades",
        "time_authority": "HISTORICAL_TRANSACTION_TIME_NOT_LOCAL_RECEIVE",
        "quote_observed": False,
        "fill_qualified": False,
        "capacity_qualified": False,
        "economics_computed": False,
        "requests": resolved,
    }
