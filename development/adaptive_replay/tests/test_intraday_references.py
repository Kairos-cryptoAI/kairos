from __future__ import annotations

import hashlib
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from adaptive_replay.intraday_references import EntryRequest, scan_daily_archive

SYMBOL = "BTCUSDT"
DAY = date(2022, 1, 2)
START = int(datetime(2022, 1, 2, tzinfo=UTC).timestamp() * 1000)
HEADER = "aggTradeId,price,quantity,firstTradeId,lastTradeId,transactTime,isBuyerMaker\n"


def row(agg: int, timestamp: int, raw_first: int | None = None, raw_last: int | None = None) -> str:
    first = agg * 10 if raw_first is None else raw_first
    last = first if raw_last is None else raw_last
    return f"{agg},10.25,0.5,{first},{last},{timestamp},false\n"


def archive(
    tmp_path: Path,
    rows: list[str],
    *,
    symbol: str = SYMBOL,
    day: date = DAY,
    member_name: str | None = None,
) -> tuple[Path, Path]:
    name = f"{symbol}-aggTrades-{day.isoformat()}.zip"
    member = member_name or f"{symbol}-aggTrades-{day.isoformat()}.csv"
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member, HEADER + "".join(rows))
    checksum = tmp_path / f"{name}.CHECKSUM"
    checksum.write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}\n", encoding="ascii")
    return path, checksum


def request(
    *, offset: int = 10_000, completion: int | None = None, transport: int = 0, intent: str = "i-1"
) -> EntryRequest:
    decision = START + offset
    return EntryRequest(
        symbol=SYMBOL,
        intent_id=intent,
        decision_ts_ms=decision,
        entry_eligible_ts_ms=decision + 1,
        expires_ts_ms=decision + 60_000,
        completion_ts_ms=decision if completion is None else completion,
        transport_delay_ms=transport,
    )


def run(tmp_path: Path, rows: list[str], reqs: list[EntryRequest], **limits):
    path, checksum = archive(tmp_path, rows)
    return scan_daily_archive(path, checksum, SYMBOL, DAY, reqs, deadline=10**12, **limits)


def bracket_rows(req: EntryRequest, *, ref_offset: int = 5, post_offset: int = 1) -> list[str]:
    arrival = req.arrival_ts_ms
    return [
        row(1, arrival - 1),
        row(2, arrival + ref_offset),
        row(3, req.expires_ts_ms + post_offset),
    ]


def test_reference_witnesses_strict_boundaries_and_nonmutation(tmp_path: Path) -> None:
    req = request()
    rows = bracket_rows(req)
    path, checksum = archive(tmp_path, rows)
    before = (path.read_bytes(), checksum.read_bytes())

    result = scan_daily_archive(path, checksum, SYMBOL, DAY, [req], deadline=10**12)

    item = result["requests"][0]
    assert item["status"] == "RECORDED_PRINT_REFERENCE"
    assert item["first_reference"]["aggregate_trade_id"] == 2
    assert item["immediate_predecessor"]["aggregate_trade_id"] == 1
    assert item["strict_pre_window_predecessor"]["transact_time_ms"] < item["arrival_ts_ms_assumed"]
    assert item["strict_post_window_successor"]["transact_time_ms"] > req.expires_ts_ms
    assert item["wait_ms"] == 5
    assert result["time_authority"] == "HISTORICAL_TRANSACTION_TIME_NOT_LOCAL_RECEIVE"
    assert result["quote_observed"] is result["fill_qualified"] is result["capacity_qualified"] is False
    assert result["economics_computed"] is False
    assert (path.read_bytes(), checksum.read_bytes()) == before


def test_arrival_uses_later_completion_plus_transport_and_order_is_preserved(tmp_path: Path) -> None:
    req_a = request(completion=START + 10_100, transport=100, intent="late")
    req_b = request(completion=START + 10_000, transport=0, intent="early")
    assert req_a.arrival_ts_ms == req_a.entry_eligible_ts_ms + 199
    assert req_b.arrival_ts_ms == req_b.entry_eligible_ts_ms
    rows = [
        row(1, req_b.arrival_ts_ms - 1),
        row(2, req_b.arrival_ts_ms + 250),
        row(3, req_a.expires_ts_ms + 1),
    ]
    result = run(tmp_path, rows, [req_a, req_b])
    assert [item["intent_id"] for item in result["requests"]] == ["late", "early"]
    assert [item["status"] for item in result["requests"]] == ["RECORDED_PRINT_REFERENCE"] * 2


def test_native_100ms_arrival_is_eligible_plus_99ms(tmp_path: Path) -> None:
    req = request(completion=START + 10_100)
    assert req.arrival_ts_ms == req.entry_eligible_ts_ms + 99
    result = run(tmp_path, bracket_rows(req), [req])
    assert result["requests"][0]["arrival_ts_ms_assumed"] == req.entry_eligible_ts_ms + 99


def test_same_millisecond_reference_retains_immediate_predecessor(tmp_path: Path) -> None:
    req = request()
    arrival = req.arrival_ts_ms
    result = run(
        tmp_path,
        [row(1, arrival - 1), row(2, arrival), row(3, arrival), row(4, req.expires_ts_ms + 1)],
        [req],
    )
    item = result["requests"][0]
    assert item["status"] == "RECORDED_PRINT_REFERENCE"
    assert item["first_reference"]["aggregate_trade_id"] == 2
    assert item["immediate_predecessor"]["aggregate_trade_id"] == 1


def test_inclusive_aggregate_gap_envelope_taints_lifetime(tmp_path: Path) -> None:
    req = request()
    arrival = req.arrival_ts_ms
    result = run(tmp_path, [row(1, arrival - 1), row(4, arrival + 20), row(5, req.expires_ts_ms + 1)], [req])
    item = result["requests"][0]
    assert item["status"] == "GAP_TAINTED"
    assert item["aggregate_gap_intersects_window"] is True
    assert result["aggregate_id_gap_count"] == 1
    assert result["missing_aggregate_ids_observed"] == 2


def test_gap_after_found_reference_and_ending_after_expiry_still_taints(tmp_path: Path) -> None:
    req = request()
    result = run(
        tmp_path,
        [row(1, req.arrival_ts_ms - 1), row(2, req.arrival_ts_ms + 1), row(4, req.expires_ts_ms + 1)],
        [req],
    )
    assert result["requests"][0]["first_reference"] is not None
    assert result["requests"][0]["status"] == "GAP_TAINTED"


def test_oversized_sidecar_and_repeated_checksum_marker_rejected(tmp_path: Path) -> None:
    req = request()
    path, checksum = archive(tmp_path, bracket_rows(req))
    original = checksum.read_bytes()
    checksum.write_bytes(original + b" " * 513)
    with pytest.raises(ValueError, match="bounded size"):
        scan_daily_archive(path, checksum, SYMBOL, DAY, [req], deadline=10**12)
    checksum.write_bytes(original.replace(b"  BTC", b"  **BTC"))
    with pytest.raises(ValueError, match="filename"):
        scan_daily_archive(path, checksum, SYMBOL, DAY, [req], deadline=10**12)


def test_raw_id_gap_is_reported_but_not_misclassified_as_missing_market_print(tmp_path: Path) -> None:
    req = request()
    arrival = req.arrival_ts_ms
    rows = [row(1, arrival - 1, 10, 10), row(2, arrival + 5, 13, 13), row(3, req.expires_ts_ms + 1, 14, 14)]
    result = run(tmp_path, rows, [req])
    assert result["requests"][0]["status"] == "RECORDED_PRINT_REFERENCE"
    assert result["raw_id_gap_count"] == 1
    assert result["missing_raw_ids_observed"] == 2
    assert "not evidence of missing market trades" in result["raw_gap_semantics"]


def test_empty_lifetime_and_strict_source_boundaries(tmp_path: Path) -> None:
    req = request()
    arrival = req.arrival_ts_ms
    no_print = run(tmp_path, [row(1, arrival - 1), row(2, req.expires_ts_ms + 1)], [req])
    assert no_print["requests"][0]["status"] == "NO_RECORDED_PRINT_IN_ASSUMED_WINDOW"
    unbracketed = run(tmp_path, [row(1, arrival), row(2, req.expires_ts_ms + 1)], [req])
    assert unbracketed["requests"][0]["status"] == "BOUNDARY_UNPROVEN"
    no_successor = run(tmp_path, [row(1, arrival - 1), row(2, req.expires_ts_ms)], [req])
    assert no_successor["requests"][0]["status"] == "BOUNDARY_UNPROVEN"


def test_expired_before_arrival_is_not_confused_with_boundary_failure(tmp_path: Path) -> None:
    req = request(completion=START + 71_000)
    result = run(tmp_path, [row(1, START + 1), row(2, START + 80_000)], [req])
    assert result["requests"][0]["status"] == "EXPIRED_BEFORE_ARRIVAL"


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("decision_ts_ms", True, TypeError),
        ("entry_eligible_ts_ms", 10.5, TypeError),
        ("expires_ts_ms", False, TypeError),
        ("completion_ts_ms", True, TypeError),
        ("transport_delay_ms", False, TypeError),
    ],
)
def test_request_clocks_are_typed_integers_not_bool_or_float(field, value, error) -> None:
    values = dict(
        symbol=SYMBOL,
        intent_id="x",
        decision_ts_ms=START + 100,
        entry_eligible_ts_ms=START + 101,
        expires_ts_ms=START + 60_100,
        completion_ts_ms=START + 100,
        transport_delay_ms=0,
    )
    values[field] = value
    with pytest.raises(error):
        EntryRequest(**values)


def test_request_geometry_and_negative_delay_fail_closed() -> None:
    base = dict(
        symbol=SYMBOL,
        intent_id="x",
        decision_ts_ms=START + 100,
        entry_eligible_ts_ms=START + 101,
        expires_ts_ms=START + 60_100,
        completion_ts_ms=START + 100,
        transport_delay_ms=0,
    )
    for key, value in (
        ("entry_eligible_ts_ms", START + 102),
        ("expires_ts_ms", START + 60_101),
        ("transport_delay_ms", -1),
    ):
        bad = dict(base, **{key: value})
        with pytest.raises(ValueError):
            EntryRequest(**bad)
    with pytest.raises(ValueError, match="completion"):
        EntryRequest(**dict(base, completion_ts_ms=START + 99))


def test_bad_request_set_and_archive_identity_fail_closed(tmp_path: Path) -> None:
    req = request()
    path, checksum = archive(tmp_path, bracket_rows(req))
    with pytest.raises(ValueError, match="unique"):
        scan_daily_archive(path, checksum, SYMBOL, DAY, [req, req], deadline=10**12)
    other = EntryRequest(
        "ETHUSDT",
        "eth",
        req.decision_ts_ms,
        req.entry_eligible_ts_ms,
        req.expires_ts_ms,
        req.completion_ts_ms,
        0,
    )
    with pytest.raises(ValueError, match="symbol"):
        scan_daily_archive(path, checksum, SYMBOL, DAY, [other], deadline=10**12)
    with pytest.raises(ValueError, match="filename"):
        scan_daily_archive(path, checksum, SYMBOL, date(2022, 1, 3), [req], deadline=10**12)


def test_checksum_mismatch_and_wrong_member_rejected(tmp_path: Path) -> None:
    req = request()
    path, checksum = archive(tmp_path, bracket_rows(req))
    checksum.write_text("0" * 64 + "  " + path.name + "\n", encoding="ascii")
    with pytest.raises(ValueError, match="SHA256"):
        scan_daily_archive(path, checksum, SYMBOL, DAY, [req], deadline=10**12)
    path2, checksum2 = archive(tmp_path / "wrong", bracket_rows(req), member_name="../escape.csv")
    with pytest.raises(ValueError, match="exactly"):
        scan_daily_archive(path2, checksum2, SYMBOL, DAY, [req], deadline=10**12)


def test_crc_is_checked_after_matching_archive_sha(tmp_path: Path) -> None:
    req = request()
    path, checksum = archive(tmp_path, bracket_rows(req))
    data = bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as zf:
        info = zf.infolist()[0]
        offset = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    data[offset + 4] ^= 0x01
    path.write_bytes(data)
    checksum.write_text(f"{hashlib.sha256(data).hexdigest()}  {path.name}\n", encoding="ascii")
    import zlib

    with pytest.raises((zipfile.BadZipFile, RuntimeError, ValueError, zlib.error)):
        scan_daily_archive(path, checksum, SYMBOL, DAY, [req], deadline=10**12)


@pytest.mark.parametrize(
    "rows,match",
    [
        (["1,10,1,10,10,1,false,extra\n"], "seven"),
        ([row(1, START + 2), row(1, START + 3)], "strictly increasing"),
        ([row(1, START + 3), row(2, START + 2)], "decreasing"),
        ([row(1, START + 1, 10, 12), row(2, START + 2, 12, 13)], "overlap"),
        ([row(1, START - 1)], "outside"),
    ],
)
def test_invalid_schema_order_ranges_and_day_are_rejected(
    tmp_path: Path, rows: list[str], match: str
) -> None:
    req = request()
    path, checksum = archive(tmp_path, rows)
    with pytest.raises((ValueError, RuntimeError), match=match):
        scan_daily_archive(path, checksum, SYMBOL, DAY, [req], deadline=10**12)


def test_line_byte_row_and_deadline_bounds(tmp_path: Path) -> None:
    req = request()
    path, checksum = archive(tmp_path, [row(1, req.arrival_ts_ms - 1), row(2, req.expires_ts_ms + 1)])
    with pytest.raises(ValueError, match="compressed archive"):
        scan_daily_archive(path, checksum, SYMBOL, DAY, [req], deadline=10**12, max_compressed_bytes=1)
    with pytest.raises(ValueError, match="uncompressed"):
        scan_daily_archive(path, checksum, SYMBOL, DAY, [req], deadline=10**12, max_uncompressed_bytes=10)
    with pytest.raises(ValueError, match="row count"):
        scan_daily_archive(path, checksum, SYMBOL, DAY, [req], deadline=10**12, max_rows=1)
    with pytest.raises(TimeoutError):
        scan_daily_archive(path, checksum, SYMBOL, DAY, [req], deadline=0)

    long_path, long_checksum = archive(tmp_path / "long", [row(1, req.arrival_ts_ms - 1) + "x" * 520])
    with pytest.raises(ValueError, match="512"):
        scan_daily_archive(long_path, long_checksum, SYMBOL, DAY, [req], deadline=10**12)


@pytest.mark.parametrize(
    "name,value", [("max_rows", True), ("max_compressed_bytes", 0), ("max_uncompressed_bytes", -1)]
)
def test_limits_reject_nonpositive_or_bool(name: str, value: int, tmp_path: Path) -> None:
    req = request()
    path, checksum = archive(tmp_path, bracket_rows(req))
    with pytest.raises(ValueError):
        scan_daily_archive(path, checksum, SYMBOL, DAY, [req], deadline=10**12, **{name: value})
