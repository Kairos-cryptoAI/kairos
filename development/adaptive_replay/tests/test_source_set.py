from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest

from adaptive_replay import source_set


def test_prior_audit_reuse_is_bound_to_raw_zip_bytes_not_local_claims() -> None:
    name, payload = "BTCUSDT-1m-2022-01.zip", b"synthetic immutable bytes"
    expected = hashlib.sha256(name.encode() + b"\0" + hashlib.sha256(payload).digest()).hexdigest()
    record = {"status": "AUDITED", "inventory_sha256": expected}
    source_set.check_prior_archive(name, payload, record)
    with pytest.raises(ValueError, match="monthly bytes differ"):
        source_set.check_prior_archive(name, payload + b"changed", record)
    with pytest.raises(ValueError, match="monthly bytes differ"):
        source_set.check_prior_archive(name.replace("BTC", "ETH"), payload, record)
    with pytest.raises(ValueError, match="monthly bytes differ"):
        source_set.check_prior_archive(name, payload, {**record, "status": "ERROR"})


def test_daily_allowlist_has_exact_missing_adjacent_and_replacement_partitions() -> None:
    keys = set(source_set.DAILY_KEYS)
    assert len(keys) == len(source_set.DAILY_KEYS) == 19
    assert {day for symbol, day in keys if symbol == "SOLUSDT"} == {
        "2022-02-25",
        "2022-02-26",
        "2022-02-27",
        "2022-02-28",
        "2022-03-01",
        "2022-03-31",
        "2022-04-01",
        "2022-04-02",
        "2022-04-03",
    }
    assert {day for symbol, day in keys if symbol == "XRPUSDT"} == {
        day for symbol, day in keys if symbol == "SOLUSDT"
    } | {"2023-11-30"}


def test_unknown_prior_audit_is_rejected_before_any_cache_read(tmp_path: Path) -> None:
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"state": "COMPLETED"}), encoding="utf-8")
    with pytest.raises(ValueError, match="exact immutable prior"):
        source_set.accept_source_set(
            audit,
            tmp_path / "bars",
            tmp_path / "funding",
            tmp_path / "daily",
            tmp_path / "retrieval.json",
            time.monotonic() + 1,
        )


def test_source_binding_does_not_include_local_absolute_paths(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.zip"
    payload = b"synthetic source bytes"
    path.write_bytes(payload)
    path.with_name(path.name + ".CHECKSUM").write_text(
        hashlib.sha256(payload).hexdigest() + "  " + path.name + "\n", encoding="ascii"
    )
    retained, binding = source_set.file_binding(path)
    assert retained == payload
    assert set(binding) == {"raw_sha256", "checksum_file_sha256"}


def test_official_retrieval_is_exactly_byte_bound_and_has_nineteen_verified_downloads(tmp_path: Path) -> None:
    retained = Path(__file__).parents[1] / "evidence/source-qualification-2026-10-07/official-retrieval.json"
    result = source_set.check_official_retrieval(retained)
    assert sorted(result) == list(source_set.DAILY_KEYS)
    assert all(row["checksum_matches"] for row in result.values())
    changed = tmp_path / "changed.json"
    changed.write_bytes(retained.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="exact retained official"):
        source_set.check_official_retrieval(changed)


def test_retrieval_helper_and_rest_observation_are_retained_as_source_only_evidence() -> None:
    root = Path(__file__).parents[1] / "evidence/source-qualification-2026-10-07"
    assert hashlib.sha256((root / "retrieval-helper.py.txt").read_bytes()).hexdigest() == (
        "874fbb751199651616e896b0a520ea6e3997dee24f59e7207b7fdb7470384144"
    )
    rest = json.loads((root / "rest-point-observation.json").read_bytes())
    assert rest["economic_cells"] == 0 and rest["full_kline_acceptance"] is False
    assert rest["response_rows"][1][0] == 1701347700000
    assert rest["sample_rows"] == 3
