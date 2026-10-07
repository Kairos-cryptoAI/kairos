from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from kairos_backtest.factor_data import FundingObservation

from adaptive_replay import calendar_inputs

HOUR = 3_600_000


def _ms(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(datetime(year, month, day, hour, tzinfo=UTC).timestamp() * 1_000)


def _event(symbol: str, timestamp_ms: int, interval: int = 8) -> FundingObservation:
    return FundingObservation(symbol, timestamp_ms, interval, 0.0001)


def test_sol_november_schedule_has_exact_exception_counts_and_no_fake_slots() -> None:
    slots = calendar_inputs.funding_slots("SOLUSDT", _ms(2022, 11, 1), _ms(2022, 12, 1))

    assert len(slots) == 165
    assert Counter(slots.values()) == {8: 64, 4: 2, 2: 99}
    for forbidden in (
        _ms(2022, 11, 10, 2),
        _ms(2022, 11, 18, 10),
        _ms(2022, 11, 18, 12),
        _ms(2022, 11, 18, 14),
    ):
        assert forbidden not in slots


def test_actual_funding_offsets_and_two_hour_intervals_are_not_rewritten() -> None:
    start, end = _ms(2022, 11, 10), _ms(2022, 11, 10, 8)
    slots = calendar_inputs.funding_slots("SOLUSDT", start, end)
    observations = [_event("SOLUSDT", slot + 59_999, interval) for slot, interval in slots.items()]

    selected, max_offset = calendar_inputs.check_funding("SOLUSDT", observations, start, end)

    assert [event.interval_hours for event in selected] == [4, 2, 2]
    assert [event.timestamp_ms for event in selected] == [slot + 59_999 for slot in slots]
    assert max_offset == 59_999


@pytest.mark.parametrize(
    "case",
    ["missing", "duplicate", "wrong-interval", "unplanned-slot"],
)
def test_funding_schedule_mismatches_fail_closed(case: str) -> None:
    start, end = _ms(2022, 1, 1), _ms(2022, 1, 2)
    slots = calendar_inputs.funding_slots("BTCUSDT", start, end)
    observations = [_event("BTCUSDT", slot, interval) for slot, interval in slots.items()]
    if case == "missing":
        observations.pop()
        expected = "missing exact funding slot"
    elif case == "duplicate":
        observations.append(_event("BTCUSDT", observations[0].timestamp_ms + 1))
        expected = "duplicate funding slot"
    elif case == "wrong-interval":
        observations[0] = _event("BTCUSDT", observations[0].timestamp_ms, interval=4)
        expected = "unplanned funding event or interval"
    else:
        observations = [_event("BTCUSDT", start + 4 * HOUR)]
        expected = "unplanned funding event or interval"

    with pytest.raises(ValueError, match=expected):
        calendar_inputs.check_funding("BTCUSDT", observations, start, end)


def test_archive_event_outside_its_month_fails_before_funding_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def one_month(*_args: Any) -> list[date]:
        return [date(2021, 11, 1)]

    monkeypatch.setattr(calendar_inputs, "month_starts", one_month)
    monkeypatch.setattr(
        calendar_inputs,
        "_monthly_file_evidence",
        lambda path: (
            b"synthetic",
            {"path": str(path), "raw_sha256": "0" * 64, "checksum_file_sha256": "1" * 64},
        ),
    )

    def fake_load(_loader: Any, _symbol: str, start_date: date, end_date: date) -> tuple[list[None], Any]:
        start_ms = int(datetime.combine(start_date, time.min, UTC).timestamp() * 1_000)
        end_ms = int(datetime.combine(end_date, time.min, UTC).timestamp() * 1_000)
        rows = (end_ms - start_ms) // 60_000
        manifest = SimpleNamespace(
            rows=rows,
            actual_start_ms=start_ms,
            actual_end_ms=end_ms - 1,
            gaps=0,
            expected_files=1,
            checksum_files_verified=1,
            checksum_status="official_sha256_verified",
            field_profile=calendar_inputs.ArchiveFieldProfile.FULL_KLINE.value,
            quarantined_optional_rows=0,
            sha256="2" * 64,
        )
        return [None] * rows, manifest

    monkeypatch.setattr(calendar_inputs.BinanceArchiveLoader, "load", fake_load)
    outside_month = _ms(2021, 12, 1)
    monkeypatch.setattr(
        calendar_inputs,
        "parse_funding",
        lambda _payload, _symbol, _name: (_event("BTCUSDT", outside_month),),
    )

    with pytest.raises(ValueError, match="funding timestamp outside month"):
        calendar_inputs.load_calendar_window(
            Path("synthetic-bars"),
            Path("synthetic-factors"),
            {"id": "synthetic", "start": "2022-01-01", "end_exclusive": "2022-01-02"},
        )
