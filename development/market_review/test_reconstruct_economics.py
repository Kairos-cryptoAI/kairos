"""Small offline tests for the finite publication-proxy economics adapter."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "reconstruct_economics", Path(__file__).with_name("reconstruct_economics.py")
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        ("ALLOW", "KEEP_ORIGINAL_CANDIDATE"),
        ("VETO", "FILTER_CANDIDATE"),
        ("DEFER", "FILTER_CANDIDATE"),
    ],
)
def test_observed_review_is_candidate_filter_only(decision, expected):
    assert MODULE._filter_decision(decision, MODULE.REVIEWED) == expected


def test_missing_proxy_context_is_abstention_not_veto():
    assert MODULE._filter_decision(None, MODULE.NO_CALL) == "ABSTAIN"
    with pytest.raises(ValueError, match="no-call"):
        MODULE._filter_decision("VETO", MODULE.NO_CALL)


@pytest.mark.parametrize(
    "plan",
    [
        {"prior_provider_attempts": 1, "prior_local_held_microusd": 5035},
        {"prior_provider_attempts": 2, "prior_local_held_microusd": None},
        {"prior_provider_attempts": 2, "prior_local_held_microusd": -1},
    ],
)
def test_prior_held_cost_must_be_explicit_and_is_not_zeroed(plan):
    with pytest.raises(ValueError, match="prior failed-attempt/held-cost"):
        MODULE._known_prior_hold(plan)


def test_prior_hold_is_reported_separately_from_known_spend():
    report = MODULE._known_prior_hold(
        {"prior_provider_attempts": 2, "prior_local_held_microusd": 5035}
    )
    assert report["unresolved_held_cost_microusd"] == 5035
    assert "separately" in report["treatment"]
    assert report["conservative_cost_bound_microusd"] == 5035


def test_all_defer_keeps_all_observed_costs_but_no_entry_completion_times():
    candidates = [
        ({}, SimpleNamespace(intent_id=f"id-{index}", decision_ts_ms=1000 + index))
        for index in range(9)
    ]
    observations = {
        f"id-{index}": {
            "decision": "DEFER",
            "measured_pipeline_duration_ms": 50,
            "actual_microusd": 100 + index,
        }
        for index in range(9)
    }
    tape, completion_times, costs = MODULE._economic_inputs(
        candidates, observations, 100
    )
    assert tape == {}
    assert completion_times == {}
    assert len(costs) == 9
    assert sum(row[2] for row in costs) == sum(range(100, 109))
    assert {row[0] for row in costs} == set(observations)


def test_allow_has_exact_matching_entry_completion_and_still_charges_all_reviews():
    candidates = [
        ({}, SimpleNamespace(intent_id=f"id-{index}", decision_ts_ms=1000 + index))
        for index in range(9)
    ]
    observations = {
        f"id-{index}": {
            "decision": "ALLOW" if index == 2 else "DEFER",
            "measured_pipeline_duration_ms": 50 + index,
            "actual_microusd": 200 + index,
        }
        for index in range(9)
    }
    tape, completion_times, costs = MODULE._economic_inputs(
        candidates, observations, 100
    )
    assert set(completion_times) == {"id-2"}
    assert {intent.intent_id for values in tape.values() for intent in values} == set(
        completion_times
    )
    assert completion_times["id-2"] == 1000 + 2 + 100 + 52
    assert len(costs) == 9


def test_no_call_has_no_completion_or_service_cost():
    candidates = [
        ({}, SimpleNamespace(intent_id="called", decision_ts_ms=1000)),
        ({}, SimpleNamespace(intent_id="missing", decision_ts_ms=2000)),
    ]
    observations = {
        "called": {
            "decision": "DEFER",
            "measured_pipeline_duration_ms": 50,
            "actual_microusd": 500,
        }
    }
    tape, completion_times, costs = MODULE._economic_inputs(
        candidates, observations, 100
    )
    assert tape == {}
    assert completion_times == {}
    assert [row[0] for row in costs] == ["called"]


def test_completion_roster_rejects_duplicate_candidate_ids():
    duplicate = [({}, SimpleNamespace(intent_id="same", decision_ts_ms=1))] * 2
    with pytest.raises(ValueError, match="duplicate candidate"):
        MODULE._economic_inputs(duplicate, {}, 100)


def test_cached_result_roster_rejects_duplicate_id_even_with_twelve_rows():
    ids = {f"id-{index}" for index in range(12)}
    rows = [{"candidate_id": f"id-{index}"} for index in range(12)]
    rows[-1]["candidate_id"] = "id-0"
    with pytest.raises(ValueError, match="duplicate or missing"):
        MODULE._index_candidate_results(rows, ids)


def test_native_admission_geometry_is_distinct_from_normalized_prompt_geometry():
    request = {
        "baseline_candidate_geometry_sha256": "normalized-prompt-geometry",
        "admission_original_candidate_geometry_sha256": "absolute-native-geometry",
    }
    admission = {"original_candidate_geometry_sha256": "absolute-native-geometry"}
    MODULE._validate_admission_geometry(request, admission)
    request["admission_original_candidate_geometry_sha256"] = (
        "normalized-prompt-geometry"
    )
    with pytest.raises(ValueError, match="admission geometry"):
        MODULE._validate_admission_geometry(request, admission)


def test_review_receipts_for_other_windows_are_not_economic_inputs():
    candidates = [({}, SimpleNamespace(intent_id="this-window", decision_ts_ms=1))]
    with pytest.raises(ValueError, match="outside economic candidate roster"):
        MODULE._economic_inputs(candidates, {"other-window": {}}, 100)


def _source_row(record_id, kind, published, payload):
    return {
        "id": record_id,
        "kind": kind,
        "url": f"https://example.test/{record_id}",
        "published_upper_ms": published,
        "captured_ms": published,
        "raw_sha256": "a" * 64,
        "payload_json": MODULE.proxy_context._canonical_json_text(payload),
    }


def _proxy_request_fixture(kinds=("NEWS", "MACRO")):
    cut = 1_650_000_000_000
    sources = []
    if "NEWS" in kinds:
        sources.append(
            _source_row("news", "NEWS", cut - 1_000, {"headline": "h", "body": "b"})
        )
    if "MACRO" in kinds:
        sources.append(
            _source_row(
                "macro",
                "MACRO",
                cut - 1_000,
                {"metric": "m", "value": "1", "unit": "x"},
            )
        )
    bundle = {"sources": sources}
    selected = MODULE.proxy_context._select_sources(bundle, cut)
    source_view = {
        "NEWS": MODULE.proxy_context._source_view(selected["NEWS"]),
        "MACRO": MODULE.proxy_context._source_view(selected["MACRO"]),
    }
    geometry = {"side": "LONG", "stop": 99, "target": 102}
    news = (
        "PARTIAL_PUBLICATION_ONLY_PROXY"
        if selected["NEWS"]
        else "UNAVAILABLE_NOT_TESTED_NOT_KNOWN_EMPTY"
    )
    macro = (
        "PARTIAL_PUBLICATION_ONLY_PROXY"
        if selected["MACRO"]
        else "UNAVAILABLE_NOT_KNOWN_EMPTY"
    )
    user = {
        "candidate": geometry,
        "news": news,
        "external_macro": macro,
        "publication_time_proxy_context": {
            "sources": source_view,
            "news_status": news,
            "macro_status": macro,
        },
    }
    old = {
        "candidate_id": "candidate-1",
        "window_id": "window-1",
        "slot_id": "slot-1",
        "historical_cut_ms": cut,
        "prompt_sha256": "old-prompt",
        "user": MODULE.proxy_context._canonical_json_text({"candidate": geometry}),
    }
    eligible = bool(selected["NEWS"] and selected["MACRO"])
    request = {
        "candidate_id": old["candidate_id"],
        "window_id": old["window_id"],
        "slot_id": old["slot_id"],
        "historical_cut_ms": cut,
        "baseline_prompt_sha256": old["prompt_sha256"],
        "baseline_candidate_geometry": geometry,
        "baseline_candidate_geometry_sha256": MODULE.experiment.digest(geometry),
        "system": MODULE.proxy_context.SYSTEM,
        "user": MODULE.proxy_context._canonical_json_text(user),
        "dispatch_eligible": eligible,
        "no_call_reason": None if eligible else "MISSING_PUBLICATION_PROXY_CONTEXT",
    }
    request["prompt_sha256"] = MODULE.experiment.digest(
        {"system": request["system"], "user": user}
    )
    return request, old, bundle


def test_proxy_request_recomputes_prompt_geometry_and_selected_source_view():
    request, old, bundle = _proxy_request_fixture()
    assert MODULE._validate_proxy_request(request, old, bundle) is True


@pytest.mark.parametrize("mutation", ["prompt", "source", "geometry", "bars"])
def test_proxy_request_rejects_prompt_source_or_geometry_tampering(mutation):
    request, old, bundle = _proxy_request_fixture()
    if mutation == "prompt":
        request["prompt_sha256"] = "0" * 64
    elif mutation == "source":
        request_user = json.loads(request["user"])
        request_user["publication_time_proxy_context"]["sources"]["NEWS"] = []
        request["user"] = MODULE.proxy_context._canonical_json_text(request_user)
        request["prompt_sha256"] = MODULE.experiment.digest(
            {"system": request["system"], "user": request_user}
        )
    elif mutation == "geometry":
        request_user = json.loads(request["user"])
        request_user["candidate"]["stop"] = 98
        request["user"] = MODULE.proxy_context._canonical_json_text(request_user)
        request["prompt_sha256"] = MODULE.experiment.digest(
            {"system": request["system"], "user": request_user}
        )
    else:
        request_user = json.loads(request["user"])
        request_user["asset_complete_bars"] = {"1m": [{"ohlc": [1, 2, 1, 2]}]}
        request["user"] = MODULE.proxy_context._canonical_json_text(request_user)
        request["prompt_sha256"] = MODULE.experiment.digest(
            {"system": request["system"], "user": request_user}
        )
    with pytest.raises(ValueError, match="prompt|source|geometry|market context"):
        MODULE._validate_proxy_request(request, old, bundle)


def test_proxy_no_call_policy_must_match_missing_source_presence():
    request, old, bundle = _proxy_request_fixture(kinds=("NEWS",))
    assert MODULE._validate_proxy_request(request, old, bundle) is False
    request["no_call_reason"] = None
    with pytest.raises(ValueError, match="eligibility/no-call"):
        MODULE._validate_proxy_request(request, old, bundle)


def test_cached_response_clock_receipt_must_be_ordered():
    request = {"candidate_id": "candidate-1", "prompt_sha256": "p"}
    review = {
        "candidate_id": "candidate-1",
        "prompt_sha256": "p",
        "state": "OBSERVED_COMMITTED",
        "decision": "ALLOW",
        "model": "gpt-6-luna",
        "effort": "medium",
        "actual_microusd": 1,
        "measured_pipeline_duration_ms": 10,
        "modern_attempt_started_ms": 100,
        "modern_response_observed_ms": 150,
        "modern_adapter_finished_ms": 160,
    }
    assert (
        MODULE.experiment.validate_reviews([request], [review])["candidate-1"] == review
    )
    review["modern_response_observed_ms"] = 170
    with pytest.raises(ValueError, match="clocks invalid"):
        MODULE.experiment.validate_reviews([request], [review])


def test_raw_capture_signature_is_bound_to_worker_start_receipt(monkeypatch, tmp_path):
    signature = {"manifest": "m", "projection": "p", "source": "r"}
    worker = SimpleNamespace(capture_signature=lambda manifest, sources: signature)
    monkeypatch.setattr(MODULE.importlib, "import_module", lambda _name: worker)
    monkeypatch.setattr(
        MODULE.experiment,
        "read_json",
        lambda _path: {"raw_input_signature": signature},
    )
    args = SimpleNamespace(
        capture_manifest=tmp_path / "manifest.json",
        sources=tmp_path / "sources.json",
        proxy_run=tmp_path,
    )
    assert MODULE._validate_capture_signature(args) == signature
    monkeypatch.setattr(
        MODULE.experiment,
        "read_json",
        lambda _path: {"raw_input_signature": {"manifest": "changed"}},
    )
    with pytest.raises(ValueError, match="raw publication capture"):
        MODULE._validate_capture_signature(args)


def test_failure_receipt_is_create_only_and_sanitized(tmp_path):
    MODULE._write_failure_receipt(tmp_path, ValueError("sensitive path and details"))
    path = tmp_path / "failure.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["state"] == "FAILED_CLOSED"
    assert receipt["error_type"] == "ValueError"
    assert set(receipt) == {"state", "error_type", "finished_utc"}
    original = path.read_bytes()
    MODULE._write_failure_receipt(tmp_path, RuntimeError("changed"))
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_identity", {"source": "changed"}),
        ("baseline_hashes", {"result.json": "changed"}),
    ],
)
def test_before_snapshot_must_match_current_source_and_baseline(field, value):
    before = {
        "source_identity": {"source": "original"},
        "baseline_hashes": {"result.json": "original"},
        "filter_policy": MODULE.FILTER_POLICY,
        "adapter_sha256": "adapter",
    }
    before[field] = value
    with pytest.raises(ValueError, match="pre-replay"):
        MODULE._validate_before(
            before,
            {"source": "original"},
            {"result.json": "original"},
            "adapter",
        )


@pytest.mark.parametrize("seconds", [0, -1, 901, True, 1.5])
def test_deadline_is_bounded(seconds):
    # Exercise the exact validation used by run() without touching any input files.
    if type(seconds) is not int or not 1 <= seconds <= 900:
        with pytest.raises(ValueError, match="deadline"):
            MODULE.run(type("Args", (), {"deadline_seconds": seconds})())
