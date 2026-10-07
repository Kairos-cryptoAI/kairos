"""Synthetic fixtures below exercise parser guards; only the pinned test checks production bytes."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from adaptive_replay import historical_macro_archive as hma

ROOT = Path(__file__).resolve().parents[1] / "evidence" / "historical-macro-2026-10-07"


def test_retained_artifact_has_only_two_scoped_observations() -> None:
    archive = hma.extract(ROOT / "alfred-cpiaucsl-vintages.raw", ROOT / "request.json", ROOT / "receipt.json")
    assert archive.metric_scope == ("CPIAUCSL",)
    assert [(x.observation_date, x.value, x.vintage_date) for x in archive.observations] == [
        ("2021-04-01", "266.832", "2021-05-18"),
        ("2023-11-01", "307.917", "2024-01-08"),
    ]
    assert archive.observations[0].release_date == "2021-05-12"
    assert archive.observations[1].release_date == "2023-12-12"
    assert archive.required_sources_ready is False and archive.news_accepted is False
    assert archive.full_macro_coverage_guaranteed is False and archive.source_authenticity_verified is False


def test_production_raw_digest_is_pinned_separately() -> None:
    raw = (ROOT / "alfred-cpiaucsl-vintages.raw").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == hma.RAW_SHA256


def test_synthetic_capture_backdating_rejected() -> None:
    request = {"actual_requested_ms": 20}
    receipt = {"actual_requested_ms": 20, "actual_captured_ms": 19}
    assert receipt["actual_captured_ms"] < request["actual_requested_ms"]  # fixture boundary
    with pytest.raises(ValueError):
        hma._check_capture_order(request, receipt)  # synthetic fixture, not production receipt


def test_synthetic_zip_traversal_rejected() -> None:
    fixture = io.BytesIO()
    with zipfile.ZipFile(fixture, "w") as zf:
        zf.writestr("../evil.csv", "x")
        zf.writestr("README.txt", "x")
    with pytest.raises(ValueError):
        hma._safe_members(fixture.getvalue())  # synthetic traversal fixture


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "0", "01.2"])
def test_synthetic_noncanonical_numeric_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        hma._decimal(bad)  # synthetic numeric fixture


def test_synthetic_duplicate_json_key_rejected() -> None:
    with pytest.raises(ValueError):
        hma._canonical_json(b'{"a":1,"a":2}')  # synthetic receipt fixture
