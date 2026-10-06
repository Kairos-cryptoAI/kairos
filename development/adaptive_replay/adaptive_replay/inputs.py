"""Strict, offline historical inputs for the bounded adaptive development replay."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from kairos_backtest.data import ArchiveFieldProfile, BinanceArchiveLoader, month_starts
from kairos_backtest.factor_data import FundingObservation, parse_funding
from kairos_strategy.candles import Candle

UNIVERSE = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
FUNDING_INTERVAL_MS = 8 * 60 * 60 * 1_000
_WINDOW_ID = re.compile(r"^[a-z0-9_]+$")


@dataclass(frozen=True, slots=True)
class WindowInputs:
    bars: dict[str, tuple[Candle, ...]]
    funding: dict[str, tuple[FundingObservation, ...]]
    evidence: dict[str, object]
    start_ms: int
    end_ms: int
    data_start_ms: int
    data_end_ms: int


def _utc_midnight(value: str, name: str) -> datetime:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"window {name} must be an ISO calendar date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"window {name} must be an ISO calendar date")
    return datetime.combine(parsed, time.min, UTC)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _verify_checksum(payload: bytes, checksum: bytes, filename: str) -> str:
    try:
        fields = checksum.decode("ascii").strip().split()
    except UnicodeDecodeError as exc:
        raise ValueError(f"checksum for {filename} is not ASCII") from exc
    if (
        len(fields) != 2
        or len(fields[0]) != 64
        or not re.fullmatch(r"[0-9a-fA-F]{64}", fields[0])
        or fields[1].removeprefix("*") != filename
    ):
        raise ValueError(f"malformed checksum for {filename}")
    digest = _sha(payload)
    if digest != fields[0].lower():
        raise ValueError(f"official Binance SHA-256 mismatch for {filename}")
    return digest


def _monthly_file_evidence(path: Path) -> tuple[bytes, dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"missing cached archive: {path}")
    checksum_path = path.with_name(f"{path.name}.CHECKSUM")
    if not checksum_path.is_file():
        raise FileNotFoundError(f"missing cached archive checksum: {checksum_path}")
    payload = path.read_bytes()
    sidecar = checksum_path.read_bytes()
    return payload, {
        "path": path.as_posix(),
        "raw_sha256": _verify_checksum(payload, sidecar, path.name),
        "checksum_file_sha256": _sha(sidecar),
    }


def load_window(
    bar_cache: Path,
    factor_cache: Path,
    window: dict[str, object],
    warmup_hours: int = 54,
    exit_tail_hours: int = 3,
) -> WindowInputs:
    """Load a complete, checksum-verified UTC window without network access."""
    if not isinstance(warmup_hours, int) or isinstance(warmup_hours, bool) or warmup_hours < 0:
        raise ValueError("warmup_hours must be a non-negative integer")
    if not isinstance(exit_tail_hours, int) or isinstance(exit_tail_hours, bool) or exit_tail_hours < 0:
        raise ValueError("exit_tail_hours must be a non-negative integer")
    if not isinstance(window, dict):
        raise ValueError("window must be an object")
    window_id = window.get("id")
    if not isinstance(window_id, str) or not _WINDOW_ID.fullmatch(window_id):
        raise ValueError("window id is invalid")
    start = _utc_midnight(window.get("start"), "start")  # type: ignore[arg-type]
    end = _utc_midnight(window.get("end_exclusive"), "end_exclusive")  # type: ignore[arg-type]
    if end <= start:
        raise ValueError("window end_exclusive must be after start")

    warm_start = start - timedelta(hours=warmup_hours)
    data_start = datetime.combine(warm_start.date(), time.min, UTC)
    tail_end = end + timedelta(hours=exit_tail_hours)
    data_end = datetime.combine(tail_end.date(), time.min, UTC)
    if tail_end > data_end:
        data_end += timedelta(days=1)
    start_ms = int(start.timestamp() * 1_000)
    end_ms = int(end.timestamp() * 1_000)
    data_start_ms = int(data_start.timestamp() * 1_000)
    data_end_ms = int(data_end.timestamp() * 1_000)

    bars: dict[str, tuple[Candle, ...]] = {}
    funding: dict[str, tuple[FundingObservation, ...]] = {}
    bar_evidence: dict[str, object] = {}
    funding_evidence: dict[str, object] = {}
    for symbol in UNIVERSE:
        bar_archives: list[dict[str, str]] = []
        for month in month_starts(data_start.date(), data_end.date()):
            name = f"{symbol}-1m-{month:%Y-%m}.zip"
            _, file_evidence = _monthly_file_evidence(Path(bar_cache) / symbol / "1m" / name)
            bar_archives.append(file_evidence)
        candles, manifest = BinanceArchiveLoader(
            Path(bar_cache), allow_download=False, field_profile=ArchiveFieldProfile.FULL_KLINE
        ).load(symbol, data_start.date(), data_end.date())
        expected_rows = (data_end_ms - data_start_ms) // 60_000
        if (
            len(candles) != expected_rows
            or manifest.rows != expected_rows
            or manifest.actual_start_ms != data_start_ms
            or manifest.actual_end_ms != data_end_ms - 1
            or manifest.gaps != 0
            or manifest.expected_files != len(month_starts(data_start.date(), data_end.date()))
            or manifest.checksum_files_verified != manifest.expected_files
            or manifest.checksum_status != "official_sha256_verified"
            or manifest.field_profile != ArchiveFieldProfile.FULL_KLINE.value
            or manifest.quarantined_optional_rows != 0
        ):
            raise ValueError(f"incomplete or unverified FULL_KLINE data for {symbol}")
        bars[symbol] = tuple(candles)
        bar_evidence[symbol] = {
            "normalized_rows_sha256": manifest.sha256,
            "rows": manifest.rows,
            "gaps": manifest.gaps,
            "archives": bar_archives,
        }

        observations: list[FundingObservation] = []
        funding_archives: list[dict[str, str]] = []
        for month in month_starts(data_start.date(), data_end.date()):
            name = f"{symbol}-fundingRate-{month:%Y-%m}.zip"
            path = Path(factor_cache) / "fundingRate" / symbol / name
            payload, file_evidence = _monthly_file_evidence(path)
            parsed = parse_funding(payload, symbol, name)
            first_month = datetime.combine(month, time.min, UTC)
            next_month = datetime.combine(
                date(month.year + (month.month == 12), month.month % 12 + 1, 1), time.min, UTC
            )
            lo, hi = int(first_month.timestamp() * 1_000), int(next_month.timestamp() * 1_000)
            if any(not lo <= item.timestamp_ms < hi for item in parsed):
                raise ValueError(f"funding timestamp outside archive month in {name}")
            observations.extend(parsed)
            funding_archives.append(file_evidence)
        observations.sort(key=lambda item: item.timestamp_ms)
        timestamps = [item.timestamp_ms for item in observations]
        if len(timestamps) != len(set(timestamps)):
            raise ValueError(f"duplicate funding timestamp for {symbol}")
        selected: list[FundingObservation] = []
        expected_times = range(data_start_ms, data_end_ms, FUNDING_INTERVAL_MS)
        expected_set = set(expected_times)
        available = {item.timestamp_ms: item for item in observations}
        observed_in_range = {timestamp for timestamp in available if data_start_ms <= timestamp < data_end_ms}
        if observed_in_range != expected_set:
            extras = sorted(observed_in_range - expected_set)
            missing = sorted(expected_set - observed_in_range)
            raise ValueError(
                f"unexpected funding settlement stamp set for {symbol}: "
                f"extra={extras[:3]} missing={missing[:3]}"
            )
        for timestamp in sorted(expected_set):
            item = available.get(timestamp)
            if item is None:
                raise ValueError(f"missing 8-hour funding settlement for {symbol} at {timestamp}")
            if item.interval_hours != 8:
                raise ValueError(f"funding interval is not 8 hours for {symbol} at {timestamp}")
            selected.append(item)
        funding[symbol] = tuple(selected)
        normalized = json.dumps([asdict(item) for item in selected], separators=(",", ":")).encode()
        funding_evidence[symbol] = {
            "normalized_rows_sha256": _sha(normalized),
            "rows": len(selected),
            "archives": funding_archives,
        }

    return WindowInputs(
        bars=bars,
        funding=funding,
        evidence={
            "window_id": window_id,
            "bar_field_profile": ArchiveFieldProfile.FULL_KLINE.value,
            "bar_start_ms": data_start_ms,
            "bar_end_ms": data_end_ms,
            "bars": bar_evidence,
            "funding_start_ms": data_start_ms,
            "funding_end_ms": data_end_ms,
            "funding": funding_evidence,
            "funding_for_entry_decisions": False,
        },
        start_ms=start_ms,
        end_ms=end_ms,
        data_start_ms=data_start_ms,
        data_end_ms=data_end_ms,
    )
