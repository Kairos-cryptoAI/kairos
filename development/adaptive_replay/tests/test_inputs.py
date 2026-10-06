from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest

from adaptive_replay.inputs import FUNDING_INTERVAL_MS, UNIVERSE, load_window

MONTH = date(2022, 1, 1)
WINDOW = {"id": "fixture", "start": "2022-01-05", "end_exclusive": "2022-01-06"}
KLINE_HEADER = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
)
FUNDING_HEADER = ("calc_time", "funding_interval_hours", "last_funding_rate")


def _zip_csv(name: str, rows: list[tuple[object, ...]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    if "-1m-" in name:
        writer.writerow(KLINE_HEADER)
    else:
        writer.writerow(FUNDING_HEADER)
    writer.writerows(rows)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, buffer.getvalue().encode("utf-8"))
    return output.getvalue()


def _write_archive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.with_name(path.name + ".CHECKSUM").write_text(
        f"{hashlib.sha256(payload).hexdigest()} *{path.name}\n", encoding="ascii"
    )


@pytest.fixture
def caches(tmp_path: Path) -> tuple[Path, Path]:
    bars, factors = tmp_path / "bars", tmp_path / "factors"
    start = datetime.combine(MONTH, time.min, UTC)
    day_count = 31
    for symbol in UNIVERSE:
        rows = []
        for minute in range(day_count * 24 * 60):
            open_ms = int((start + timedelta(minutes=minute)).timestamp() * 1_000)
            rows.append(
                (open_ms, "100", "101", "99", "100", "1", open_ms + 59_999, "100", "1", "0.5", "50", "0")
            )
        bar_name = f"{symbol}-1m-2022-01.zip"
        _write_archive(bars / symbol / "1m" / bar_name, _zip_csv(bar_name[:-4] + ".csv", rows))

        funding_rows = []
        month_end = start + timedelta(days=day_count)
        event = start
        while event < month_end:
            funding_rows.append((int(event.timestamp() * 1_000), 8, "0.0001"))
            event += timedelta(hours=8)
        factor_name = f"{symbol}-fundingRate-2022-01.zip"
        _write_archive(
            factors / "fundingRate" / symbol / factor_name,
            _zip_csv(factor_name[:-4] + ".csv", funding_rows),
        )
    return bars, factors


def test_load_window_verifies_full_utc_inputs_and_evidence(caches: tuple[Path, Path]) -> None:
    bars, factors = caches
    result = load_window(bars, factors, WINDOW)
    assert set(result.bars) == set(UNIVERSE)
    assert set(result.funding) == set(UNIVERSE)
    assert all(len(items) == 5 * 24 * 60 for items in result.bars.values())
    assert all(len(items) == 15 for items in result.funding.values())
    assert result.start_ms == int(datetime(2022, 1, 5, tzinfo=UTC).timestamp() * 1_000)
    assert result.end_ms - result.start_ms == 24 * 60 * 60 * 1_000
    assert result.data_start_ms == int(datetime(2022, 1, 2, tzinfo=UTC).timestamp() * 1_000)
    assert result.data_end_ms == int(datetime(2022, 1, 7, tzinfo=UTC).timestamp() * 1_000)
    assert result.evidence["funding_for_entry_decisions"] is False
    btc = result.evidence["bars"]["BTCUSDT"]
    assert len(btc["archives"][0]["raw_sha256"]) == 64
    assert len(btc["normalized_rows_sha256"]) == 64


@pytest.mark.parametrize(
    "window",
    [
        {"id": "bad", "start": "2022-01-05T00:00:00Z", "end_exclusive": "2022-01-06"},
        {"id": "bad", "start": "2022-01-06", "end_exclusive": "2022-01-05"},
    ],
)
def test_rejects_invalid_window_clock(window: dict[str, object], caches: tuple[Path, Path]) -> None:
    with pytest.raises(ValueError):
        load_window(*caches, window)


def test_missing_bar_checksum_fails_closed(caches: tuple[Path, Path]) -> None:
    bars, factors = caches
    (bars / "BTCUSDT" / "1m" / "BTCUSDT-1m-2022-01.zip.CHECKSUM").unlink()
    with pytest.raises(FileNotFoundError, match="checksum"):
        load_window(bars, factors, WINDOW)


def test_bar_sha_mismatch_fails_closed(caches: tuple[Path, Path]) -> None:
    bars, factors = caches
    archive = bars / "BTCUSDT" / "1m" / "BTCUSDT-1m-2022-01.zip"
    archive.write_bytes(archive.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_window(bars, factors, WINDOW)


def test_bar_zip_crc_fails_even_with_matching_outer_checksum(caches: tuple[Path, Path]) -> None:
    bars, factors = caches
    archive = bars / "BTCUSDT" / "1m" / "BTCUSDT-1m-2022-01.zip"
    damaged = bytearray(archive.read_bytes())
    with zipfile.ZipFile(archive) as zipped:
        member = zipped.infolist()[0]
        compressed_start = member.header_offset + 30 + len(member.filename.encode()) + len(member.extra)
        damaged[compressed_start + member.compress_size // 2] ^= 0x01
    _write_archive(archive, bytes(damaged))
    with pytest.raises(ValueError, match="CRC"):
        load_window(bars, factors, WINDOW)


def test_bad_full_kline_domain_is_rejected(caches: tuple[Path, Path]) -> None:
    bars, factors = caches
    archive = bars / "BTCUSDT" / "1m" / "BTCUSDT-1m-2022-01.zip"
    rows = []
    start = datetime.combine(MONTH, time.min, UTC)
    for minute in range(31 * 24 * 60):
        open_ms = int((start + timedelta(minutes=minute)).timestamp() * 1_000)
        high = "99" if minute == 2_000 else "101"
        rows.append((open_ms, "100", high, "99", "100", "1", open_ms + 59_999, "100", "1", "0.5", "50", "0"))
    _write_archive(archive, _zip_csv("BTCUSDT-1m-2022-01.csv", rows))
    with pytest.raises(ValueError, match="OHLC bounds"):
        load_window(bars, factors, WINDOW)


def test_missing_funding_settlement_fails_closed(caches: tuple[Path, Path]) -> None:
    bars, factors = caches
    archive = factors / "fundingRate" / "BTCUSDT" / "BTCUSDT-fundingRate-2022-01.zip"
    rows = []
    start = datetime.combine(MONTH, time.min, UTC)
    event = start
    omitted = int(datetime(2022, 1, 3, 8, tzinfo=UTC).timestamp() * 1_000)
    while event < start + timedelta(days=31):
        stamp = int(event.timestamp() * 1_000)
        if stamp != omitted:
            rows.append((stamp, 8, "0.0001"))
        event += timedelta(hours=8)
    _write_archive(archive, _zip_csv("BTCUSDT-fundingRate-2022-01.csv", rows))
    with pytest.raises(ValueError, match="missing 8-hour funding settlement"):
        load_window(bars, factors, WINDOW)


def test_extra_off_grid_funding_stamp_in_loaded_slice_fails(caches: tuple[Path, Path]) -> None:
    bars, factors = caches
    archive = factors / "fundingRate" / "BTCUSDT" / "BTCUSDT-fundingRate-2022-01.zip"
    rows = []
    start = datetime.combine(MONTH, time.min, UTC)
    event = start
    injected = int(datetime(2022, 1, 3, 8, tzinfo=UTC).timestamp() * 1_000) + 1
    while event < start + timedelta(days=31):
        rows.append((int(event.timestamp() * 1_000), 8, "0.0001"))
        event += timedelta(hours=8)
    rows.append((injected, 8, "0.0001"))
    _write_archive(archive, _zip_csv("BTCUSDT-fundingRate-2022-01.csv", rows))
    with pytest.raises(ValueError, match="duplicate funding settlement bucket"):
        load_window(bars, factors, WINDOW)


@pytest.mark.parametrize("offset", [5, 59_999, 60_000])
def test_funding_first_minute_offsets_are_preserved_not_rounded(
    caches: tuple[Path, Path], offset: int
) -> None:
    bars, factors = caches
    archive = factors / "fundingRate" / "BTCUSDT" / "BTCUSDT-fundingRate-2022-01.zip"
    rows = []
    start = datetime.combine(MONTH, time.min, UTC)
    event = start
    while event < start + timedelta(days=31):
        rows.append((int(event.timestamp() * 1_000) + offset, 8, "0.0001"))
        event += timedelta(hours=8)
    _write_archive(archive, _zip_csv("BTCUSDT-fundingRate-2022-01.csv", rows))
    if offset >= 60_000:
        with pytest.raises(ValueError, match="unexpected funding settlement cadence"):
            load_window(bars, factors, WINDOW)
        return
    result = load_window(bars, factors, WINDOW)
    stamps = [item.timestamp_ms for item in result.funding["BTCUSDT"]]
    evidence = result.evidence["funding"]["BTCUSDT"]
    assert all(stamp % FUNDING_INTERVAL_MS == offset for stamp in stamps)
    assert evidence["max_event_offset_ms"] == offset
    assert evidence["timestamps_rounded"] is False
    assert evidence["clock_authority"] == "ARCHIVE_CALC_TIME_ENTITLEMENT_PROXY"


def test_wrong_funding_interval_in_required_slice_fails(caches: tuple[Path, Path]) -> None:
    bars, factors = caches
    archive = factors / "fundingRate" / "BTCUSDT" / "BTCUSDT-fundingRate-2022-01.zip"
    rows = []
    start = datetime.combine(MONTH, time.min, UTC)
    event = start
    target = int(datetime(2022, 1, 3, 8, tzinfo=UTC).timestamp() * 1_000)
    while event < start + timedelta(days=31):
        stamp = int(event.timestamp() * 1_000)
        rows.append((stamp, 4 if stamp == target else 8, "0.0001"))
        event += timedelta(hours=8)
    _write_archive(archive, _zip_csv("BTCUSDT-fundingRate-2022-01.csv", rows))
    with pytest.raises(ValueError, match="interval is not 8 hours"):
        load_window(bars, factors, WINDOW)


def test_missing_funding_checksum_fails_closed(caches: tuple[Path, Path]) -> None:
    bars, factors = caches
    (factors / "fundingRate" / "BTCUSDT" / "BTCUSDT-fundingRate-2022-01.zip.CHECKSUM").unlink()
    with pytest.raises(FileNotFoundError, match="checksum"):
        load_window(bars, factors, WINDOW)


def test_loader_never_downloads(monkeypatch: pytest.MonkeyPatch, caches: tuple[Path, Path]) -> None:
    from kairos_backtest import data

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(data, "urlopen", forbidden)
    load_window(*caches, WINDOW)


def test_funding_rates_are_eight_hourly_and_explicitly_separate_from_decisions(
    caches: tuple[Path, Path],
) -> None:
    bars, factors = caches
    result = load_window(bars, factors, WINDOW)
    timestamps = [item.timestamp_ms for item in result.funding["BTCUSDT"]]
    assert all(value % FUNDING_INTERVAL_MS == 0 for value in timestamps)
    assert result.evidence["funding_for_entry_decisions"] is False
