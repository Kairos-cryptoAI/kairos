from __future__ import annotations

import hashlib
import zipfile
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from adaptive_replay import archive_funding_rate_v3 as module
from adaptive_replay.archive_funding_rate_v3 import (
    FundingArchiveLimitsV3,
    FundingEntitlementV3,
    load_original_funding_archive_v3,
)

START = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1_000)
HOURS = 3_600_000
ROSTER = tuple(FundingEntitlementV3(START + 8 * HOURS * i, 8) for i in range(93))


def _archive(tmp_path, *, payload=None, extra_member=False):
    if payload is None:
        rows = []
        for index, item in enumerate(ROSTER):
            rate = "-0.000000000000000000009" if index == 1 else "0.00010000"
            rows.append(f"{item.due_at_ms + (index % 2)},8,{rate}\r\n".encode())
        payload = module.HEADER + b"\r\n" + b"".join(rows)
    path = tmp_path / "BTCUSDT-fundingRate-2024-01.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("BTCUSDT-fundingRate-2024-01.csv", payload)
        if extra_member:
            archive.writestr("extra.csv", b"unplanned")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum = path.with_name(path.name + ".CHECKSUM")
    checksum.write_bytes(f"{sha}  {path.name}\n".encode())
    return (
        path,
        {
            "symbol": "BTCUSDT",
            "month": "2024-01",
            "expected_archive_sha256": sha,
            "expected_checksum_sha256": hashlib.sha256(checksum.read_bytes()).hexdigest(),
            "entitlements": ROSTER,
            "maximum_calc_time_offset_ms": 1,
        },
        payload,
    )


def test_full_original_month_exact_decimal_raw_clocks_and_no_settlement_claim(tmp_path):
    path, kwargs, raw = _archive(tmp_path)
    result = load_original_funding_archive_v3(path, **kwargs)
    assert len(result.records) == 93
    assert result.csv_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.csv_bytes == len(raw)
    assert result.maximum_observed_offset_ms == 1
    assert result.records[1].rate == Decimal("-0.000000000000000000009")
    assert str(result.records[0].rate) == "0.00010000"
    assert result.records[1].exchange_calc_time_ms == START + 8 * HOURS + 1
    assert result.records[1].due_at_ms == START + 8 * HOURS
    assert result.records[1].raw_record in raw
    assert result.records[1].raw_record_sha256 == hashlib.sha256(result.records[1].raw_record).hexdigest()
    assert (
        result.records[1].modeled_available_at(feed_delay_ms=3, processing_delay_ms=7)
        == START + 8 * HOURS + 11
    )
    assert result.window(START, START + 24 * HOURS) == result.records[:3]
    assert result.historical_received_at_ms is None
    assert result.settlement_price is None
    assert result.funding_for_entry_decisions is False
    assert result.evidence_kind == "ARCHIVE_CALC_TIME_ENTITLEMENT_PROXY_NOT_SOURCE_ADMISSION"


@pytest.mark.parametrize("which", ["archive", "checksum"])
def test_independent_pin_and_sidecar_binding_fail_closed(tmp_path, which):
    path, kwargs, _ = _archive(tmp_path)
    kwargs[f"expected_{which}_sha256"] = "f" * 64
    message = (
        "official funding checksum identity mismatch" if which == "archive" else "checksum file mismatch"
    )
    with pytest.raises(ValueError, match=message):
        load_original_funding_archive_v3(path, **kwargs)


def test_archive_bytes_must_match_pin_even_if_sidecar_agrees_with_it(tmp_path):
    path, kwargs, _ = _archive(tmp_path)
    kwargs["expected_archive_sha256"] = "f" * 64
    sidecar = path.with_name(path.name + ".CHECKSUM")
    sidecar.write_bytes(f"{kwargs['expected_archive_sha256']}  {path.name}\n".encode())
    kwargs["expected_checksum_sha256"] = hashlib.sha256(sidecar.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="archive hash mismatch"):
        load_original_funding_archive_v3(path, **kwargs)


@pytest.mark.parametrize(
    "change",
    ["missing", "extra", "duplicate", "bad-header", "future-offset", "wrong-interval", "nan", "invalid-exp"],
)
def test_full_row_and_calendar_reconciliation_rejects_unplanned_records(tmp_path, change):
    header = module.HEADER + b"\n"
    rows = [f"{item.due_at_ms},8,0.0001\n".encode() for item in ROSTER]
    if change == "missing":
        rows.pop(15)
    elif change == "extra":
        rows.append(rows[-1])
    elif change == "duplicate":
        rows[15] = rows[14]
    elif change == "bad-header":
        header = b"funding_time,interval,rate\n"
    elif change == "future-offset":
        rows[15] = f"{ROSTER[15].due_at_ms + 2},8,0.0001\n".encode()
    elif change == "wrong-interval":
        rows[15] = f"{ROSTER[15].due_at_ms},4,0.0001\n".encode()
    elif change == "nan":
        rows[15] = f"{ROSTER[15].due_at_ms},8,NaN\n".encode()
    elif change == "invalid-exp":
        rows[15] = f"{ROSTER[15].due_at_ms},8,1e--4\n".encode()
    path, kwargs, _ = _archive(tmp_path, payload=header + b"".join(rows))
    with pytest.raises(ValueError):
        load_original_funding_archive_v3(path, **kwargs)


@pytest.mark.parametrize("rate", ["0E-8", "1e-4", "-1.234567890123456789e-08"])
def test_original_scientific_decimal_preserved_without_float_conversion(tmp_path, rate):
    # Retained original BNB May-2021 archive includes 0E-8, not 0.00000000.
    payload = module.HEADER + b"\n" + b"".join(f"{item.due_at_ms},8,{rate}\n".encode() for item in ROSTER)
    path, kwargs, _ = _archive(tmp_path, payload=payload)
    event = load_original_funding_archive_v3(path, **kwargs).records[0]
    assert event.rate == Decimal(rate)
    assert event.rate.as_tuple() == Decimal(rate).as_tuple()
    assert event.raw_record.endswith(f",{rate}\n".encode())


def test_csv_crc_error_cannot_be_acknowledged(tmp_path):
    path, kwargs, _ = _archive(tmp_path)
    data = bytearray(path.read_bytes())
    offset = data.index(b"PK\x01\x02")
    data[offset + 16] ^= 1  # central-directory CRC, not source row editing
    path.write_bytes(data)
    kwargs["expected_archive_sha256"] = hashlib.sha256(data).hexdigest()
    sidecar = path.with_name(path.name + ".CHECKSUM")
    sidecar.write_bytes(f"{kwargs['expected_archive_sha256']}  {path.name}\n".encode())
    kwargs["expected_checksum_sha256"] = hashlib.sha256(sidecar.read_bytes()).hexdigest()
    with pytest.raises(zipfile.BadZipFile, match="CRC"):
        load_original_funding_archive_v3(path, **kwargs)


@pytest.mark.parametrize("bound", ["max_archive_bytes", "max_csv_bytes", "max_rows", "max_line_bytes"])
def test_explicit_resource_bound_cannot_silently_trim_source(tmp_path, bound):
    path, kwargs, _ = _archive(tmp_path)
    kwargs["limits"] = FundingArchiveLimitsV3(**{bound: 1})
    with pytest.raises(ValueError):
        load_original_funding_archive_v3(path, **kwargs)


def test_duplicate_calendar_or_extra_zip_member_refused(tmp_path):
    path, kwargs, _ = _archive(tmp_path, extra_member=True)
    with pytest.raises(ValueError, match="single original"):
        load_original_funding_archive_v3(path, **kwargs)
    kwargs["entitlements"] = (*ROSTER, ROSTER[-1])
    with pytest.raises(ValueError, match="unique ordered"):
        load_original_funding_archive_v3(path, **kwargs)


def test_deadline_does_not_return_success_after_last_checks(tmp_path, monkeypatch):
    path, kwargs, _ = _archive(tmp_path)
    count = 0

    def clock():
        nonlocal count
        count += 1
        return 0 if count < 97 else 60

    monkeypatch.setattr(module.time, "monotonic", clock)
    with pytest.raises(TimeoutError):
        load_original_funding_archive_v3(path, **kwargs)


def test_mutation_during_final_archive_audit_refused(tmp_path, monkeypatch):
    path, kwargs, _ = _archive(tmp_path)
    original = module._regular_nofollow

    def inspect(item):
        if item == path:
            with path.open("ab") as stream:
                stream.write(b"after-scan")
        return original(item)

    monkeypatch.setattr(module, "_regular_nofollow", inspect)
    with pytest.raises(ValueError, match="changed during"):
        load_original_funding_archive_v3(path, **kwargs)


@pytest.mark.parametrize("value", [True, -1, 86_400_001])
def test_model_clock_rejects_implicit_or_unbounded_delay(tmp_path, value):
    path, kwargs, _ = _archive(tmp_path)
    event = load_original_funding_archive_v3(path, **kwargs).records[0]
    with pytest.raises(ValueError):
        event.modeled_available_at(feed_delay_ms=value, processing_delay_ms=0)
