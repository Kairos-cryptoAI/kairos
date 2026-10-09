from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

import adaptive_replay.bookticker_archive_stream_v3 as stream_module
from adaptive_replay.bookticker_archive_stream_v3 import (
    HEADER,
    StreamLimitsV3,
    build_bookticker_archive_stream_v3,
    open_bookticker_archive_stream_v3,
)

MEMBER = "BTCUSDT-bookTicker-2024-01-08.csv"
ROWS = [
    b"10,100.00,1.250,100.10,2.00,1704672000006,1704672000012\r\n",
    b"11,100.01,1.5,100.11,2.5,1704672000010,1704672000016\r\n",
    b"12,100.02,1.75,100.12,2.75,1704672000020,1704672000025\r\n",
    b"13,100.03,1.875,100.13,3.00,1704758399998,1704758400005\r\n",
]


def _fixture(tmp_path: Path, rows: list[bytes] | None = None) -> tuple[Path, bytes]:
    payload = HEADER + b"\r\n" + b"".join(ROWS if rows is None else rows)
    archive = tmp_path / f"{MEMBER.removesuffix('.csv')}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(MEMBER, payload)
    return archive, payload


def _build(archive: Path, payload: bytes, output: Path, **overrides):
    archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    return build_bookticker_archive_stream_v3(
        archive,
        output,
        symbol="BTCUSDT",
        transaction_day="2024-01-08",
        expected_archive_sha256=overrides.pop("expected_archive_sha256", archive_sha),
        expected_rows=overrides.pop("expected_rows", len(ROWS)),
        expected_uncompressed_bytes=overrides.pop("expected_uncompressed_bytes", len(payload)),
        expected_uncompressed_sha256=overrides.pop(
            "expected_uncompressed_sha256", hashlib.sha256(payload).hexdigest()
        ),
        limits=overrides.pop(
            "limits",
            StreamLimitsV3(
                max_archive_bytes=1_000_000,
                max_uncompressed_bytes=10_000,
                max_rows=20,
                segment_bytes=300,
                index_stride=2,
                max_line_bytes=256,
                max_segments=20,
            ),
        ),
        evidence_kind="TEST_FIXTURE",
        **overrides,
    )


def _open(directory: Path):
    manifest_path = directory / "manifest.json"
    return open_bookticker_archive_stream_v3(
        directory, expected_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    )


def test_lossless_segmented_originals_sparse_seek_and_half_open_clock_range(tmp_path: Path) -> None:
    archive, payload = _fixture(tmp_path)
    archive_before = archive.read_bytes()
    stream = _build(archive, payload, tmp_path / "accepted")

    assert stream.row_count == 4
    assert stream.manifest["evidence_kind"] == "TEST_FIXTURE"
    assert stream.manifest["clock_semantics"]["historical_local_receive_clock"] == "UNKNOWN"
    assert stream.manifest["trading_authority"] == "NONE"
    assert stream.manifest["csv"]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert len(stream.manifest["segments"]) > 1
    stored = b"".join((stream.root / item["name"]).read_bytes() for item in stream.manifest["segments"])
    assert stored == payload  # Header, original decimal spelling, CRLF, and cross-day E all retained.
    assert [row.row_index for row in stream.iter_rows(1, 3)] == [1, 2]
    assert stream.row_at(1).best_bid_price_text == "100.01"
    assert stream.row_at(0).best_bid_qty_text == "1.250"
    assert stream.row_at(3).event_time_ms == 1_704_758_400_005
    assert [row.row_index for row in stream.iter_range(1_704_672_000_010, 1_704_672_000_020)] == [1]
    assert archive.read_bytes() == archive_before


def test_stream_is_create_only_and_reopen_verifies_all_segment_bytes(tmp_path: Path) -> None:
    archive, payload = _fixture(tmp_path)
    output = tmp_path / "accepted"
    stream = _build(archive, payload, output)
    assert (output / "manifest.json").is_file()
    assert not (output / "manifest.json.tmp").exists()
    with pytest.raises(FileExistsError):
        _build(archive, payload, output)

    segment = stream.root / stream.manifest["segments"][0]["name"]
    segment.write_bytes(segment.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="segment changed since acceptance"):
        stream.row_at(0)
    with pytest.raises(ValueError, match="segment exact byte count mismatch"):
        _open(output)


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"expected_archive_sha256": "0" * 64}, "archive checksum"),
        ({"expected_uncompressed_sha256": "0" * 64}, "full uncompressed CSV SHA256"),
        ({"expected_rows": len(ROWS) - 1}, "more rows"),
        ({"expected_uncompressed_bytes": 1000}, "member size"),
    ],
)
def test_wrong_profile_never_publishes_accepted_manifest(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    archive, payload = _fixture(tmp_path)
    output = tmp_path / "partial"
    with pytest.raises(ValueError, match=message):
        _build(archive, payload, output, **overrides)
    if output.exists():
        assert not (output / "manifest.json").exists()
        with pytest.raises(ValueError, match="unavailable"):
            open_bookticker_archive_stream_v3(output, expected_manifest_sha256="0" * 64)


@pytest.mark.parametrize(
    "rows",
    [
        ROWS[:-1] + [ROWS[-1][:-2]],  # truncated final line
        [ROWS[0], ROWS[0], *ROWS[2:]],  # duplicate update ID
        [ROWS[0], ROWS[1].replace(b"1704672000010", b"1704672000000"), *ROWS[2:]],
        [ROWS[0].replace(b"100.00", b"+100.00"), *ROWS[1:]],
        [ROWS[0].replace(b"100.00", b"1_00.00"), *ROWS[1:]],
        [ROWS[0].replace(b"100.00", b" 100.00"), *ROWS[1:]],
    ],
)
def test_invalid_row_stream_fails_without_acceptance(tmp_path: Path, rows: list[bytes]) -> None:
    archive, payload = _fixture(tmp_path, rows)
    output = tmp_path / "partial"
    with pytest.raises(ValueError):
        _build(archive, payload, output, expected_rows=len(rows))
    assert not (output / "manifest.json").exists()


def test_zip_crc_failure_is_not_accepted(tmp_path: Path) -> None:
    archive, payload = _fixture(tmp_path)
    compressed = bytearray(archive.read_bytes())
    # Flip a byte in the central-directory CRC commitment. ZIP EOF then fails CRC.
    central = compressed.rfind(b"PK\x01\x02")
    assert central >= 0
    crc_offset = central + 16
    compressed[crc_offset] ^= 0x01
    archive.write_bytes(compressed)
    output = tmp_path / "partial"
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        _build(
            archive,
            payload,
            output,
            expected_archive_sha256=hashlib.sha256(compressed).hexdigest(),
        )
    assert not (output / "manifest.json").exists()


def test_equal_transaction_times_across_three_anchors_are_not_skipped(tmp_path: Path) -> None:
    equal_rows = [
        ROWS[0].replace(b"1704672000006", b"1704672000010"),
        ROWS[1],
        ROWS[2].replace(b"1704672000020", b"1704672000010"),
        ROWS[3],
    ]
    archive, payload = _fixture(tmp_path, equal_rows)
    limits = StreamLimitsV3(
        max_archive_bytes=1_000_000,
        max_uncompressed_bytes=10_000,
        max_rows=20,
        segment_bytes=300,
        index_stride=1,
        max_line_bytes=256,
        max_segments=20,
    )
    stream = _build(archive, payload, tmp_path / "equal-time", limits=limits)
    assert [row.row_index for row in stream.iter_range(1_704_672_000_010, 1_704_672_000_011)] == [0, 1, 2]


@pytest.mark.parametrize("mutation", ["extra-key", "duplicate-key", "segment-row-count", "index-capacity"])
def test_rehashed_manifest_still_requires_closed_unique_schema(tmp_path: Path, mutation: str) -> None:
    archive, payload = _fixture(tmp_path)
    stream = _build(archive, payload, tmp_path / "accepted")
    manifest_path = stream.root / "manifest.json"
    original = manifest_path.read_bytes()
    if mutation == "extra-key":
        manifest = json.loads(original)
        manifest["unexpected"] = True
        changed = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        expected_error = "manifest schema"
    else:
        if mutation == "duplicate-key":
            changed = original.replace(b'"schema":', b'"schema":"other","schema":', 1)
            expected_error = "duplicate"
        else:
            manifest = json.loads(original)
            if mutation == "segment-row-count":
                manifest["segments"][0]["rows"] += 1
                expected_error = "per-segment row count"
            else:
                manifest["sparse_index"]["bytes"] = 16 * 1024 * 1024 + 1
                expected_error = "bounded profile"
            changed = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    manifest_path.write_bytes(changed)
    expected = hashlib.sha256(changed).hexdigest()
    with pytest.raises(ValueError, match=expected_error):
        open_bookticker_archive_stream_v3(stream.root, expected_manifest_sha256=expected)


def test_stream_view_manifest_is_a_copy_and_identity_hash_is_pinned(tmp_path: Path) -> None:
    archive, payload = _fixture(tmp_path)
    stream = _build(archive, payload, tmp_path / "accepted")
    original_symbol = stream.symbol
    copied = stream.manifest
    copied["symbol"] = "ETHUSDT"
    assert stream.symbol == original_symbol
    assert stream.row_at(0).symbol == original_symbol
    with pytest.raises(AttributeError):
        stream.symbol = "ETHUSDT"
    with pytest.raises(ValueError, match="independent expected manifest SHA256"):
        open_bookticker_archive_stream_v3(stream.root, expected_manifest_sha256="0" * 64)


def test_rehashed_duplicate_key_in_index_is_rejected(tmp_path: Path) -> None:
    archive, payload = _fixture(tmp_path)
    stream = _build(archive, payload, tmp_path / "accepted")
    index_path = stream.root / "sparse-index.jsonl"
    index = index_path.read_bytes().replace(b'"row_index":0', b'"row_index":0,"row_index":0', 1)
    index_path.write_bytes(index)
    manifest = stream.manifest
    manifest["sparse_index"]["bytes"] = len(index)
    manifest["sparse_index"]["sha256"] = hashlib.sha256(index).hexdigest()
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    manifest_path = stream.root / "manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    expected = hashlib.sha256(manifest_bytes).hexdigest()
    with pytest.raises(ValueError, match="invalid or noncanonical sparse index anchor"):
        open_bookticker_archive_stream_v3(stream.root, expected_manifest_sha256=expected)


def test_failed_staged_audit_never_publishes_final_manifest(tmp_path: Path, monkeypatch) -> None:
    archive, payload = _fixture(tmp_path)
    output = tmp_path / "audit-timeout"

    def fail_audit(*args, **kwargs):
        assert kwargs["_staged_candidate"] is True
        raise TimeoutError("forced candidate audit timeout")

    monkeypatch.setattr(stream_module, "open_bookticker_archive_stream_v3", fail_audit)
    with pytest.raises(TimeoutError, match="forced candidate audit timeout"):
        _build(archive, payload, output)
    assert (output / "manifest.json.tmp").is_file()
    assert not (output / "manifest.json").exists()
