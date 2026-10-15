"""No-network checks of the one-shot proxy worker's pre-provider boundary."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parent
worker = load("proxy_worker_under_test", ROOT / "tools/proxy_worker.py")
fixture = load(
    "reconstruction_fixture_for_worker", ROOT / "test_reconstruct_context.py"
)


def inputs(tmp_path):
    baseline, sources, admission, _, _ = fixture._fixture(tmp_path)
    output = tmp_path / "sealed"
    worker.reconstruction.prepare(fixture._args(baseline, sources, admission, output))
    return output, sources, baseline


def test_worker_checks_roster_without_constructing_provider(tmp_path, monkeypatch):
    output, sources, baseline = inputs(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("provider construction forbidden in offline validation")

    monkeypatch.setattr(worker.existing, "LLMGateway", forbidden)
    plan, rows = worker.checked_requests(output, sources, baseline)
    assert plan["max_attempts"] == 12
    assert len(rows) == 12
    assert sum(row["dispatch_eligible"] for row in rows) == 9


def test_source_mutation_rejected_before_provider(tmp_path):
    output, sources, baseline = inputs(tmp_path)
    sources.write_bytes(sources.read_bytes() + b" ")
    with pytest.raises(ValueError, match="identity"):
        worker.checked_requests(output, sources, baseline)


def test_exact_twelve_candidates_enforced(tmp_path):
    output, sources, baseline = inputs(tmp_path)
    rows = json.loads((output / "requests.json").read_text())
    rows.append(rows[0])
    fixture._write_json(output / "requests.json", rows)
    seal = json.loads((output / "seal.json").read_text())
    seal["requests_sha256"] = worker.existing.sha(output / "requests.json")
    fixture._write_json(output / "seal.json", seal)
    with pytest.raises(ValueError, match="twelve"):
        worker.checked_requests(output, sources, baseline)


def test_raw_bytes_and_projection_are_both_checked(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    original = b"retained public excerpt"
    (raw / "source.txt").write_bytes(original)
    row = {
        "id": "source",
        "raw_file": "raw\\source.txt",
        "raw_sha256": hashlib.sha256(original).hexdigest(),
        "payload_json": "{}",
        "published_upper_ms": 1,
        "captured_ms": 2,
        "url": "https://example.org/news",
        "kind": "NEWS",
    }
    manifest = tmp_path / "manifest.json"
    projected = tmp_path / "projection.json"
    fixture._write_json(manifest, {"sources": [row]})
    fixture._write_json(
        projected, {"sources": [{k: v for k, v in row.items() if k != "raw_file"}]}
    )
    assert worker.capture_signature(manifest, projected)["source"] == row["raw_sha256"]
    (raw / "source.txt").write_bytes(b"changed")
    with pytest.raises(ValueError, match="digest"):
        worker.capture_signature(manifest, projected)


def test_correction_retains_prior_failed_reservations_and_cannot_chain(tmp_path):
    root = tmp_path / "prior"
    root.mkdir()
    fixture._write_json(
        root / "sealed-plan.json",
        {
            "experiment_id": worker.reconstruction.EXPERIMENT_ID,
            "source_bundle_sha256": "source-hash",
        },
    )
    fixture._write_json(
        root / "worker-result.json",
        {
            "state": "INCOMPLETE_FAIL_CLOSED",
            "local_budgeted_microusd": 5035,
        },
    )
    fixture._write_jsonl(
        root / "reviews.jsonl",
        [
            {
                "state": "FAILED_CLOSED_COST_UNKNOWN_HELD",
                "error_type": "AuthenticationError",
            },
            {
                "state": "FAILED_CLOSED_COST_UNKNOWN_HELD",
                "error_type": "AuthenticationError",
            },
            {"state": "NOT_CALLED_AFTER_FAILURE_LIMIT"},
        ],
    )
    fixture._write_jsonl(
        root / "local-budget.jsonl",
        [
            {"state": "LOCAL_HOLD_BEFORE_SHARED", "reserved_microusd": 2521},
            {"state": "LOCAL_HOLD_BEFORE_SHARED", "reserved_microusd": 2514},
        ],
    )
    info = worker.reconstruction.approved_correction(root, "source-hash")
    assert info["prior_provider_attempts"] == 2
    assert info["prior_local_held_microusd"] == 5035
    plan = json.loads((root / "sealed-plan.json").read_text())
    plan["owner_approved_credential_correction"] = True
    fixture._write_json(root / "sealed-plan.json", plan)
    with pytest.raises(ValueError, match="retained"):
        worker.reconstruction.approved_correction(root, "source-hash")
