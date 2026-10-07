"""Read-only annual inputs with an explicit, byte-bound funding schedule.

The exception below is archive-derived consistency, not independent venue
schedule authentication. Old fixed-eight-hour loaders/receipts are unchanged.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from kairos_backtest.data import ArchiveFieldProfile, BinanceArchiveLoader, month_starts
from kairos_backtest.factor_data import FundingObservation, parse_funding

from .inputs import UNIVERSE, WindowInputs, _monthly_file_evidence, _sha, _utc_midnight

HOUR = 3_600_000
SOL_EXCEPTION_SHA = "73fbada102584d8e19cb9594f04471f589ff37404b0cf64c0bd7cb4ac4d4a157"
SOL_4H_START = int(datetime(2022, 11, 9, 20, tzinfo=UTC).timestamp() * 1000)
SOL_2H_START = int(datetime(2022, 11, 10, 4, tzinfo=UTC).timestamp() * 1000)
SOL_8H_RETURN = int(datetime(2022, 11, 18, 16, tzinfo=UTC).timestamp() * 1000)


def funding_slots(symbol: str, start_ms: int, end_ms: int) -> dict[int, int]:
    """Expected hourly anchors; actual archive milliseconds remain untouched."""
    result = {}
    for slot in range(start_ms, end_ms, HOUR):
        interval = 8
        if symbol == "SOLUSDT":
            if SOL_4H_START <= slot < SOL_2H_START:
                interval = 4
            elif SOL_2H_START <= slot < SOL_8H_RETURN:
                interval = 2
                # The final 2h event is Nov 18 08:00, then 8h resumes at 16:00.
                if slot > SOL_8H_RETURN - 8 * HOUR:
                    continue
        if slot % (interval * HOUR) == 0:
            result[slot] = interval
    return result


def check_funding(
    symbol: str, observations: list[FundingObservation], start_ms: int, end_ms: int
) -> tuple[tuple[FundingObservation, ...], int]:
    expected = funding_slots(symbol, start_ms, end_ms)
    selected = {}
    maximum_offset = 0
    for event in observations:
        if not start_ms <= event.timestamp_ms < end_ms:
            continue
        slot = event.timestamp_ms - event.timestamp_ms % HOUR
        offset = event.timestamp_ms - slot
        if slot not in expected or event.interval_hours != expected[slot] or offset >= 60_000:
            raise ValueError(f"unplanned funding event or interval for {symbol} at {event.timestamp_ms}")
        if slot in selected:
            raise ValueError(f"duplicate funding slot for {symbol} at {slot}")
        selected[slot] = event
        maximum_offset = max(maximum_offset, offset)
    missing = expected.keys() - selected.keys()
    if missing:
        raise ValueError(f"missing exact funding slot for {symbol} at {min(missing)}")
    return tuple(selected[slot] for slot in sorted(expected)), maximum_offset


def load_calendar_window(bar_cache: Path, factor_cache: Path, window: dict[str, str]) -> WindowInputs:
    start = _utc_midnight(window["start"], "start")
    end = _utc_midnight(window["end_exclusive"], "end_exclusive")
    if end <= start:
        raise ValueError("calendar end must follow start")
    data_start, data_end = start - timedelta(days=35), end + timedelta(days=3)
    start_ms, end_ms, data_start_ms, data_end_ms = (
        int(value.timestamp() * 1000) for value in (start, end, data_start, data_end)
    )
    bars, funding, bar_evidence, funding_evidence = {}, {}, {}, {}
    for symbol in UNIVERSE:
        archives = []
        for month in month_starts(data_start.date(), data_end.date()):
            name = f"{symbol}-1m-{month:%Y-%m}.zip"
            _, receipt = _monthly_file_evidence(bar_cache / symbol / "1m" / name)
            archives.append(receipt)
        candles, manifest = BinanceArchiveLoader(
            bar_cache, allow_download=False, field_profile=ArchiveFieldProfile.FULL_KLINE
        ).load(symbol, data_start.date(), data_end.date())
        expected_rows = (data_end_ms - data_start_ms) // 60_000
        if (
            len(candles) != expected_rows
            or manifest.rows != expected_rows
            or manifest.actual_start_ms != data_start_ms
            or manifest.actual_end_ms != data_end_ms - 1
            or manifest.gaps != 0
            or manifest.expected_files != len(archives)
            or manifest.checksum_files_verified != len(archives)
            or manifest.checksum_status != "official_sha256_verified"
            or manifest.field_profile != ArchiveFieldProfile.FULL_KLINE.value
            or manifest.quarantined_optional_rows != 0
        ):
            raise ValueError(f"incomplete verified FULL_KLINE span for {symbol}")
        bars[symbol] = tuple(candles)
        bar_evidence[symbol] = {
            "rows": manifest.rows,
            "gaps": manifest.gaps,
            "normalized_rows_sha256": manifest.sha256,
            "archives": archives,
        }
        observations, archives = [], []
        for month in month_starts(data_start.date(), data_end.date()):
            name = f"{symbol}-fundingRate-{month:%Y-%m}.zip"
            payload, receipt = _monthly_file_evidence(factor_cache / "fundingRate" / symbol / name)
            if symbol == "SOLUSDT" and month.isoformat() == "2022-11-01":
                if receipt["raw_sha256"] != SOL_EXCEPTION_SHA:
                    raise ValueError("fixed SOL exceptional archive identity changed")
            parsed = parse_funding(payload, symbol, name)
            next_month = month.replace(year=month.year + (month.month == 12), month=month.month % 12 + 1)
            lo, hi = (
                int(datetime.combine(value, time.min, UTC).timestamp() * 1000)
                for value in (month, next_month)
            )
            if any(not lo <= event.timestamp_ms < hi for event in parsed):
                raise ValueError(f"funding timestamp outside month: {name}")
            # Verify each entire archive before trimming prefix/score/tail.
            check_funding(symbol, list(parsed), lo, hi)
            observations.extend(parsed)
            archives.append(receipt)
        if len({event.timestamp_ms for event in observations}) != len(observations):
            raise ValueError(f"duplicate funding timestamp for {symbol}")
        selected, max_offset = check_funding(symbol, observations, data_start_ms, data_end_ms)
        funding[symbol] = selected
        funding_evidence[symbol] = {
            "rows": len(selected),
            "normalized_rows_sha256": _sha(json.dumps([asdict(event) for event in selected]).encode()),
            "interval_counts": dict(sorted(Counter(event.interval_hours for event in selected).items())),
            "max_event_offset_ms": max_offset,
            "timestamps_rounded": False,
            "schedule_authority": "FIXED_ARCHIVE_SCHEDULE_CONSISTENCY_NOT_EXTERNAL_AUTHENTICATION",
            "clock_authority": "ARCHIVE_CALC_TIME_ENTITLEMENT_PROXY",
            "archives": archives,
        }
    return WindowInputs(
        bars=bars,
        funding=funding,
        evidence={
            "window_id": window["id"],
            "bar_start_ms": data_start_ms,
            "bar_end_ms": data_end_ms,
            "bars": bar_evidence,
            "funding": funding_evidence,
            "funding_for_entry_decisions": False,
        },
        start_ms=start_ms,
        end_ms=end_ms,
        data_start_ms=data_start_ms,
        data_end_ms=data_end_ms,
    )
