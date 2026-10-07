from __future__ import annotations

import io
import zipfile
from dataclasses import replace

import pytest
from kairos_strategy.candles import Candle

from adaptive_replay import source_composition as source


def _archive(
    symbol: str, start: int, count: int, *, excluded: set[int] | None = None
) -> source.ParsedArchive:
    fields, candles = {}, {}
    for slot in range(start, start + count * source.MINUTE, source.MINUTE):
        if slot in (excluded or set()):
            continue
        fields[slot] = (str(slot), "10", "11", "9", "10", "1", str(slot + 59_999), "10", "1", "0", "0", "0")
        candles[slot] = Candle(symbol, "1m", slot, slot + 59_999, 10, 11, 9, 10, 1, 10, 0, 0)
    return source.ParsedArchive(symbol, "0" * 64, fields, candles, {})


def _zip(rows: list[tuple[str, ...]]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        text = ",".join(source.BINANCE_KLINE_COLUMNS) + "\n"
        text += "".join(",".join(row) + "\n" for row in rows)
        archive.writestr("synthetic.csv", text)
    return stream.getvalue()


def test_source_field_comparison_is_exact_not_float_or_tolerance() -> None:
    assert source.canonical_fields(("1.00", "0.000", "1e3")) == ("1", "0", "1000")
    assert source.canonical_fields(("1.000000000000000000000000000001",)) != ("1",)


@pytest.mark.parametrize("defect", ["duplicate", "reverse", "close-time", "domain"])
def test_strict_raw_archive_rejects_unplanned_source_defects(defect: str) -> None:
    original = _archive("BTCUSDT", source.midnight_ms("2022-01-01"), 2)
    rows = list(original.fields.values())
    if defect == "duplicate":
        rows.append(rows[-1])
    elif defect == "reverse":
        rows.reverse()
    else:
        mutated = list(rows[0])
        mutated[6 if defect == "close-time" else 7] = "1" if defect == "close-time" else "1000"
        rows[0] = tuple(mutated)
    with pytest.raises(ValueError):
        source.parse_archive(_zip(rows), "BTCUSDT")


def test_overlap_checks_every_field_and_every_row() -> None:
    start = source.midnight_ms("2022-03-01")
    monthly = _archive("SOLUSDT", start, 1_440)
    daily = _archive("SOLUSDT", start, 1_440)
    assert source.check_overlap(monthly, daily, "2022-03-01") == 1_440
    changed = dict(daily.fields)
    tail = list(changed[start + 1_439 * source.MINUTE])
    tail[8] = "2"  # trade count is not in Candle: still cannot change silently.
    changed[start + 1_439 * source.MINUTE] = tuple(tail)
    with pytest.raises(ValueError, match="twelve-field conflict"):
        source.check_overlap(monthly, replace(daily, fields=changed), "2022-03-01")


def test_cross_symbol_and_incomplete_day_fail_closed() -> None:
    start = source.midnight_ms("2022-03-01")
    monthly = _archive("SOLUSDT", start, 1_440)
    with pytest.raises(ValueError, match="same futures instrument"):
        source.check_overlap(monthly, _archive("XRPUSDT", start, 1_440), "2022-03-01")
    with pytest.raises(ValueError, match="1440-minute"):
        source.check_overlap(monthly, _archive("SOLUSDT", start, 1_439), "2022-03-01")


@pytest.mark.parametrize("symbol", ["SOLUSDT", "XRPUSDT"])
@pytest.mark.parametrize("month,days", [("2022-02", 28), ("2022-04", 30)])
def test_only_exact_predeclared_absent_slots_are_composed(symbol: str, month: str, days: int) -> None:
    fixed_days = [day for day in source.MISSING_DAYS if day.startswith(month)]
    missing = {
        slot
        for day in fixed_days
        for slot in range(source.midnight_ms(day), source.midnight_ms(day) + source.DAY, source.MINUTE)
    }
    monthly = _archive(symbol, source.midnight_ms(month + "-01"), days * 1_440, excluded=missing)
    dailies = {day: _archive(symbol, source.midnight_ms(day), 1_440) for day in fixed_days}
    rows, receipt = source.compose_month(monthly, month, dailies)
    assert len(rows) == days * 1_440
    assert receipt["added_rows"] == len(missing)
    assert receipt["replaced_rejected_rows"] == 0
    assert receipt["monthly_valid_rows_changed"] == 0
    assert len(receipt["changes"]) == len(missing)
    assert receipt["valid_overlap_rows_compared"] == 0  # adjacent controls are separate requirements.
    with pytest.raises(ValueError, match="exact fixed daily composition"):
        source.compose_month(monthly, month, {})
    one_more_missing = set(missing) | {min(monthly.fields)}
    wrong_monthly = replace(
        monthly, fields={k: v for k, v in monthly.fields.items() if k not in one_more_missing}
    )
    with pytest.raises(ValueError, match="exact known monthly gap"):
        source.compose_month(wrong_monthly, month, dailies)


def test_only_known_rejected_xrp_source_row_can_be_retained_for_replacement() -> None:
    valid = _archive("XRPUSDT", source.REJECTED_XRP_SLOT - source.MINUTE, 1)
    rows = [*valid.fields.values(), source.REJECTED_XRP_FIELDS]
    payload = _zip(rows)
    with pytest.raises(ValueError, match="unexpected FULL_KLINE"):
        source.parse_archive(payload, "XRPUSDT")
    parsed = source.parse_archive(payload, "XRPUSDT", allow_known_xrp_rejection=True)
    assert parsed.rejected_fields == {source.REJECTED_XRP_SLOT: source.REJECTED_XRP_FIELDS}
    assert source.REJECTED_XRP_SLOT not in parsed.candles
    modified = list(source.REJECTED_XRP_FIELDS)
    modified[8] = "471"
    with pytest.raises(ValueError, match="unexpected FULL_KLINE"):
        source.parse_archive(
            _zip([*valid.fields.values(), tuple(modified)]), "XRPUSDT", allow_known_xrp_rejection=True
        )


def test_rejected_row_replacement_is_explicit_and_preserves_1439_valid_overlap_rows() -> None:
    start = source.midnight_ms("2023-11-01")
    original = _archive("XRPUSDT", start, 30 * 1_440)
    fields = dict(original.fields)
    fields[source.REJECTED_XRP_SLOT] = source.REJECTED_XRP_FIELDS
    monthly = replace(
        original,
        fields=fields,
        candles={slot: row for slot, row in original.candles.items() if slot != source.REJECTED_XRP_SLOT},
        rejected_fields={source.REJECTED_XRP_SLOT: source.REJECTED_XRP_FIELDS},
    )
    daily = _archive("XRPUSDT", source.midnight_ms("2023-11-30"), 1_440)
    rows, receipt = source.compose_month(monthly, "2023-11", {"2023-11-30": daily})
    assert len(rows) == 43_200
    assert receipt["valid_overlap_rows_compared"] == 1_439
    assert receipt["added_rows"] == 0
    assert receipt["replaced_rejected_rows"] == 1
    assert receipt["changes"][0]["old_fields"] == source.REJECTED_XRP_FIELDS
    rejected_daily = replace(daily, rejected_fields={source.REJECTED_XRP_SLOT: source.REJECTED_XRP_FIELDS})
    with pytest.raises(ValueError, match="1440-minute"):
        source.compose_month(monthly, "2023-11", {"2023-11-30": rejected_daily})


def test_complete_regular_month_does_not_acquire_a_daily_fallback() -> None:
    monthly = _archive("BTCUSDT", source.midnight_ms("2022-02-01"), 28 * 1_440)
    rows, receipt = source.compose_month(monthly, "2022-02", {})
    assert len(rows) == 40_320
    assert receipt["changes"] == []
    with pytest.raises(ValueError, match="exact fixed daily composition"):
        source.compose_month(
            monthly, "2022-02", {"2022-02-26": _archive("BTCUSDT", source.midnight_ms("2022-02-26"), 1_440)}
        )
