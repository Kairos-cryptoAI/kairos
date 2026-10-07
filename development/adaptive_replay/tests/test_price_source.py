from __future__ import annotations

import io
import zipfile
from dataclasses import replace

import pytest

from adaptive_replay import source_composition as source


def _zip(rows: list[tuple[str, ...]]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("synthetic.csv", "".join(",".join(row) + "\n" for row in rows))
    return stream.getvalue()


def _rows(start: int, count: int) -> list[tuple[str, ...]]:
    return [
        (str(slot), "10", "11", "9", "10", "1", str(slot + 59_999), "10", "1", "0", "0", "0")
        for slot in range(start, start + count * source.MINUTE, source.MINUTE)
    ]


def test_known_row_price_and_clock_retained_but_full_kline_remains_rejected() -> None:
    payload = _zip([*_rows(source.REJECTED_XRP_SLOT - source.MINUTE, 1), source.REJECTED_XRP_FIELDS])
    with pytest.raises(ValueError, match="unexpected FULL_KLINE"):
        source.parse_archive(payload, "XRPUSDT")
    parsed = source.parse_price_archive(payload, "XRPUSDT")
    row = parsed.candles[source.REJECTED_XRP_SLOT]
    assert (row.open, row.high, row.low, row.close) == (0.6038, 0.6038, 0.6034, 0.6036)
    assert row.close_time_ms == 1701347759999
    assert (row.volume, row.quote_volume, row.taker_buy_volume, row.taker_buy_quote_volume) == (0, 0, 0, 0)
    assert parsed.rejected_fields == {source.REJECTED_XRP_SLOT: source.REJECTED_XRP_FIELDS}


@pytest.mark.parametrize("field,value", [(7, "1000"), (2, "0.5"), (6, "1"), (5, "NaN"), (8, "471")])
def test_price_contract_does_not_accept_unknown_defects(field: int, value: str) -> None:
    fields = list(source.REJECTED_XRP_FIELDS)
    fields[field] = value
    with pytest.raises(ValueError):
        source.parse_price_archive(_zip([tuple(fields)]), "XRPUSDT")


def test_price_projection_is_uniform_for_valid_rows_as_well() -> None:
    payload = _zip(_rows(source.midnight_ms("2022-01-01"), 3))
    parsed = source.parse_price_archive(payload, "BTCUSDT")
    assert not parsed.rejected_fields
    assert all(
        (c.volume, c.quote_volume, c.taker_buy_volume, c.taker_buy_quote_volume) == (0, 0, 0, 0)
        for c in parsed.candles.values()
    )


def test_price_composition_retains_known_row_and_compares_all_1440_raw_rows() -> None:
    rows = _rows(source.midnight_ms("2023-11-01"), 30 * 1440)
    index = (source.REJECTED_XRP_SLOT - source.midnight_ms("2023-11-01")) // source.MINUTE
    rows[index] = source.REJECTED_XRP_FIELDS
    monthly = source.parse_price_archive(_zip(rows), "XRPUSDT")
    daily = source.parse_price_archive(_zip(rows[-1440:]), "XRPUSDT")
    chosen, evidence = source.compose_price_month(monthly, "2023-11", {"2023-11-30": daily})
    assert len(chosen) == 43200
    assert evidence["replaced_rejected_rows"] == evidence["added_rows"] == 0
    assert evidence["quarantined_optional_rows"] == 1
    assert evidence["valid_overlap_rows_compared"] == 1440
    assert chosen[index] == monthly.candles[source.REJECTED_XRP_SLOT]
    fields = dict(daily.fields)
    fields[source.REJECTED_XRP_SLOT] = (
        *source.REJECTED_XRP_FIELDS[:8],
        "471",
        *source.REJECTED_XRP_FIELDS[9:],
    )
    with pytest.raises(ValueError, match="twelve-field conflict"):
        source.compose_price_month(monthly, "2023-11", {"2023-11-30": replace(daily, fields=fields)})


def test_price_composition_adds_only_fixed_absent_days() -> None:
    start = source.midnight_ms("2022-04-01")
    rows = _rows(start, 30 * 1440)
    monthly = source.parse_price_archive(_zip(rows[2880:]), "SOLUSDT")
    dailies = {
        day: source.parse_price_archive(_zip(rows[offset : offset + 1440]), "SOLUSDT")
        for day, offset in (("2022-04-01", 0), ("2022-04-02", 1440))
    }
    chosen, receipt = source.compose_price_month(monthly, "2022-04", dailies)
    assert len(chosen) == 43200 and receipt["added_rows"] == 2880
    assert receipt["replaced_rejected_rows"] == 0
    with pytest.raises(ValueError, match="exact known PRICE_ONLY"):
        source.compose_price_month(
            replace(monthly, fields=dict(list(monthly.fields.items())[1:])), "2022-04", dailies
        )
