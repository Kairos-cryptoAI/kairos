from __future__ import annotations

import copy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from adaptive_replay import price_calendar, price_inputs

ROOT = Path(__file__).parents[1]
ACCEPTANCE = ROOT / "evidence/source-qualification-2026-10-07/price-source-acceptance.json.gz"


def test_exact_separate_protocol_preserves_original_calendar_economics() -> None:
    plan, base = price_calendar.load_protocol(ROOT / "price-reference-plan.json")
    original, original_base = price_calendar.calendar.load_protocol(ROOT / "calendar-pair-plan.json")
    assert base == original_base
    for key in original.keys() - {"schema", "purpose"}:
        assert plan[key] == original[key]
    assert plan["field_profile"] == "PRICE_ONLY"
    assert plan["replaced_rejected_rows"] == 0
    assert plan["no_second_economic_attempt"] is True


@pytest.mark.parametrize(
    "key,value",
    [
        ("field_profile", "FULL_KLINE"),
        ("replaced_rejected_rows", 1),
        ("quarantined_optional_rows", 0),
        ("source_acceptance_sha256", "0" * 64),
        ("max_wall_seconds", 2400),
        ("allowed_consumers", ["adaptive_v1"]),
        ("no_second_economic_attempt", False),
        ("optional_fields", "MEASURED_ZERO"),
        ("uniform_projection_all_bars", False),
    ],
)
def test_protocol_amendment_cannot_silently_expand_or_weaken(
    key: str,
    value: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = ROOT / "price-reference-plan.json"
    expected, base = price_calendar.expected_plan(path)
    monkeypatch.setattr(price_calendar, "expected_plan", lambda _path: (copy.deepcopy(expected), base))
    changed = {**expected, key: value}
    target = tmp_path / "mutated.json"
    target.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="exact separately preregistered"):
        price_calendar.load_protocol(target)


def test_retained_acceptance_compression_is_byte_bound_and_scoped() -> None:
    compressed = ACCEPTANCE.read_bytes()
    assert (
        hashlib.sha256(compressed).hexdigest()
        == "13b287e0a9f33a57b034aaed0c9e297f4bb84a3fde36274c22410b18e2fd6a44"
    )
    assert hashlib.sha256(gzip.decompress(compressed)).hexdigest() == price_calendar.ACCEPTANCE_SHA
    receipt = price_inputs.read_acceptance(ACCEPTANCE, price_calendar.ACCEPTANCE_SHA)
    assert len(receipt["bars"]) == len(receipt["funding"]) == 255
    assert len(receipt["daily"]) == 19 and len(receipt["adjacent_controls"]) == 8
    assert receipt["expected_monthly_rows_all_symbols"] == 11181600
    assert receipt["economic_cells"] == receipt["replaced_rejected_rows"] == 0
    assert receipt["allowed_consumers"] == price_inputs.CONSUMERS


def test_changed_acceptance_is_rejected_before_cache_access(tmp_path: Path) -> None:
    payload = gzip.decompress(ACCEPTANCE.read_bytes())
    target = tmp_path / "acceptance.json"
    target.write_bytes(payload + b"\n")
    with pytest.raises(ValueError, match="acceptance bytes changed"):
        price_inputs.read_acceptance(target, price_calendar.ACCEPTANCE_SHA)


def test_accepted_file_cannot_change_zip_or_sidecar(tmp_path: Path) -> None:
    target = tmp_path / "synthetic.zip"
    target.write_bytes(b"synthetic")
    checksum = target.with_name(target.name + ".CHECKSUM")
    checksum.write_text(hashlib.sha256(b"synthetic").hexdigest() + "  synthetic.zip\n", encoding="ascii")
    binding = price_inputs.file_binding(target)[1]
    record = {"filename": target.name, **binding}
    assert price_inputs.bound_payload(target, record) == b"synthetic"
    checksum.write_text(hashlib.sha256(b"synthetic").hexdigest() + " *synthetic.zip\n", encoding="ascii")
    with pytest.raises(ValueError, match="raw source or sidecar changed"):
        price_inputs.bound_payload(target, record)


def test_all_source_verification_precedes_any_native_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = price_inputs.read_acceptance(ACCEPTANCE, price_calendar.ACCEPTANCE_SHA)
    monkeypatch.setattr(price_calendar, "sources", lambda *_args: {})
    monkeypatch.setattr(price_calendar, "read_acceptance", lambda *_args: receipt)

    def reject_sources(*_args: object) -> None:
        raise ValueError("synthetic accepted source changed")

    def forbidden(*_args: object) -> None:
        pytest.fail("generation/input load cannot precede complete source verification")

    monkeypatch.setattr(price_calendar, "verify_sources", reject_sources)
    monkeypatch.setattr(price_calendar, "load_window", forbidden)
    monkeypatch.setattr(price_calendar.calendar, "generate_calendar_pair", forbidden)
    output = tmp_path / "attempt"
    with pytest.raises(ValueError, match="synthetic accepted source changed"):
        price_calendar.run(
            ROOT / "price-reference-plan.json",
            tmp_path / "bars",
            tmp_path / "factors",
            tmp_path / "daily",
            tmp_path / "receipt.json",
            output,
        )
    failure = json.loads((output / "failure.json").read_bytes())
    assert failure["completed_windows"] == [] and failure["economic_reference_nominee"] is None
