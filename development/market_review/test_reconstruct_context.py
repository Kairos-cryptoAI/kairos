"""Offline tests for publication-time proxy diagnostic preparation/finish."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "reconstruct_context", Path(__file__).with_name("tools") / "reconstruct_context.py"
)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

BASE = 1_650_000_000_000


def _write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_jsonl(path: Path, rows) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _fixture(tmp_path: Path):
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    candidates = []
    for index in range(12):
        window = "may_2022" if index < 6 else "june_2022"
        cut = (
            BASE
            if index < 3
            else BASE + index * 60_000
            if index < 9
            else BASE + 2 * 24 * 60 * 60 * 1_000 + index * 60_000
        )
        candidate = {
            "side": "LONG",
            "pattern": "FIXTURE",
            "original_entry_lifetime_ms": 60_000,
        }
        user = {
            "scope": "RETROSPECTIVE_MARKET_ONLY_REVIEW_NOT_FULL_KAIROS",
            "news": "UNAVAILABLE_NOT_TESTED_NOT_KNOWN_EMPTY",
            "external_macro": "UNAVAILABLE_NOT_TESTED",
            "candidate": candidate,
            "asset_complete_bars": {
                "1m": [{"age_seconds": 0, "ohlc": [100, 101, 99, 100]}]
            },
        }
        user_text = module._canonical_json_text(user)
        request = {
            "candidate_id": hashlib.sha256(f"candidate-{index}".encode()).hexdigest(),
            "window_id": window,
            "slot_id": hashlib.sha256(f"slot-{index}".encode()).hexdigest(),
            "historical_cut_ms": cut,
            "system": "old market-only system",
            "user": user_text,
            "prompt_sha256": module.experiment.digest(
                {"system": "old market-only system", "user": user}
            ),
        }
        candidates.append(request)
    plan = {
        "schema": "kairos.market-only-review.plan.v1",
        "experiment_id": "market-only-review-20261010",
        "expected_candidates": 12,
        "model": "gpt-6-luna",
        "effort": "medium",
        "max_attempts": 12,
        "max_local_reserved_microusd": 1_000_000,
        "shared_openai_cap_microusd": 12_000_000,
        "shared_campaign": "kairos-dev-qualification-v1",
        "historical_cost_microusd": 1984,
        "historical_budget_evidence_sha256": "a" * 64,
        "gateway_image": "sha256:" + "b" * 64,
        "request_timeout_seconds": 45,
    }
    _write_json(baseline / "sealed-plan.json", plan)
    _write_json(baseline / "before.json", {"source_identity": {"fixture": True}})
    _write_json(baseline / "requests.json", candidates)
    old_reviews = []
    for index, request in enumerate(candidates):
        old_reviews.append(
            {
                "candidate_id": request["candidate_id"],
                "prompt_sha256": request["prompt_sha256"],
                "state": "OBSERVED_COMMITTED",
                "decision": "ALLOW" if index % 2 == 0 else "DEFER",
                "model": "gpt-6-luna",
                "effort": "medium",
                "actual_microusd": 100,
                "measured_pipeline_duration_ms": 50,
                "modern_attempt_started_ms": 1_000 + index,
                "modern_response_observed_ms": 1_050 + index,
                "modern_adapter_finished_ms": 1_055 + index,
            }
        )
    _write_jsonl(baseline / "reviews.jsonl", old_reviews)
    _write_json(
        baseline / "result.json",
        {
            "state": "COMPLETED",
            "candidates": 12,
            "real_model_calls": 12,
            "full_news_macro_system_tested": False,
        },
    )
    seal = {
        "plan_sha256": module._file_sha(baseline / "sealed-plan.json"),
        "before_sha256": module._file_sha(baseline / "before.json"),
        "requests_sha256": module._file_sha(baseline / "requests.json"),
        "expected_candidates": 12,
    }
    _write_json(baseline / "seal.json", seal)

    admission_path = tmp_path / "admission" / "result.json"
    admission_path.parent.mkdir()
    contexts = []
    for index, request in enumerate(candidates):
        geom = hashlib.sha256(f"geometry-{index}".encode()).hexdigest()
        contexts.append(
            {
                "window_id": request["window_id"],
                "historical_cut_ms": request["historical_cut_ms"],
                "original_intent_id": request["candidate_id"],
                "slot_id": request["slot_id"],
                "original_candidate_geometry_sha256": geom,
                "current_candidate_geometry_sha256": geom,
                "original_semantic_geometry_sha256": geom,
                "strict_semantic_geometry_sha256": geom,
                "review_decision": "DEFER",
                "gateway_calls": 0,
            }
        )
    contexts.reverse()
    _write_jsonl(admission_path.with_name("candidate-contexts.jsonl"), contexts)
    _write_json(
        admission_path,
        {
            "schema": "kairos.real-market-input-admission-check.v1",
            "state": "REAL_MARKET_INPUT_ADMISSION_BLOCKED_MISSING_CONTEXT",
            "candidates": 12,
            "all_candidates_deferred": True,
            "provider_calls": 0,
            "risk_or_execution_invoked": False,
            "complete_system_test_executed": False,
            "input_signature_before": {"fixture": "same"},
            "input_signature_after": {"fixture": "same"},
        },
    )
    source_path = tmp_path / "sources.json"
    capture_ms = int(datetime.now(UTC).timestamp() * 1000)

    def source(record_id, kind, published, payload, raw_kind="ORIGINAL_CAPTURE"):
        payload_json = module._canonical_json_text(payload)
        row = {
            "id": record_id,
            "kind": kind,
            "url": f"https://example.test/{record_id}",
            "published_upper_ms": published,
            "captured_ms": capture_ms,
            "raw_sha256": hashlib.sha256(("raw-" + record_id).encode()).hexdigest(),
            "payload_json": payload_json,
        }
        if raw_kind != "ORIGINAL_CAPTURE":
            row["raw_kind"] = raw_kind
        return row

    sources = [
        source("news-current", "NEWS", BASE, {"headline": "News", "body": "Excerpt"}),
        source(
            "macro-old",
            "MACRO",
            BASE - 3 * 24 * 60 * 60 * 1_000,
            {"metric": "CPI", "value": "8.3", "unit": "percent"},
        ),
        source(
            "macro-new",
            "MACRO",
            BASE - 24 * 60 * 60 * 1_000,
            {"metric": "CPI", "value": "8.5", "unit": "percent"},
            "WEB_TOOL_EXCERPT_NOT_ORIGINAL_HTML",
        ),
    ]
    _write_json(
        source_path,
        {
            "schema": "kairos.publication-proxy.sources.v1",
            "strict_causal_admission": False,
            "coverage": "UNKNOWN",
            "historical_receive_clock_proven": False,
            "sources": sources,
        },
    )
    return baseline, source_path, admission_path, candidates, old_reviews


def _args(baseline: Path, sources: Path, admission: Path, output: Path) -> Namespace:
    return Namespace(
        baseline=baseline, sources=sources, admission_result=admission, output=output
    )


def test_prepare_seals_exact_geometry_and_skips_missing_or_stale_news(tmp_path):
    baseline, sources, admission, old_requests, _old_reviews = _fixture(tmp_path)
    original_hashes = module._baseline_signature(baseline)
    output = tmp_path / "proxy"
    module.prepare(_args(baseline, sources, admission, output))

    requests = json.loads((output / "requests.json").read_text(encoding="utf-8"))
    assert len(requests) == 12
    assert {row["candidate_id"] for row in requests} == {
        row["candidate_id"] for row in old_requests
    }
    assert sum(row["dispatch_eligible"] for row in requests) == 9
    assert all(
        row["no_call_reason"] is None for row in requests if row["dispatch_eligible"]
    )
    assert all(
        row["no_call_reason"] == "MISSING_PUBLICATION_PROXY_CONTEXT"
        for row in requests
        if not row["dispatch_eligible"]
    )
    first = json.loads(requests[0]["user"])
    assert first["candidate"] == json.loads(old_requests[0]["user"])["candidate"]
    assert first["news"] == "PARTIAL_PUBLICATION_ONLY_PROXY"
    assert first["external_macro"] == "PARTIAL_PUBLICATION_ONLY_PROXY"
    macro = first["publication_time_proxy_context"]["sources"]["MACRO"]
    assert [row["payload"]["value"] for row in macro] == ["8.5"]
    assert macro[0]["raw_kind"] == "WEB_TOOL_EXCERPT_NOT_ORIGINAL_HTML"
    assert module._baseline_signature(baseline) == original_hashes
    plan = json.loads((output / "sealed-plan.json").read_text(encoding="utf-8"))
    assert plan["max_attempts"] == 12
    assert plan["max_local_reserved_microusd"] == 1_000_000
    assert plan["strict_causal_admission"] is False
    assert plan["coverage"] == "UNKNOWN"
    contexts = [
        json.loads(line)
        for line in admission.with_name("candidate-contexts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    geometry_by_id = {
        row["original_intent_id"]: row["original_candidate_geometry_sha256"]
        for row in contexts
    }
    assert all(
        row["admission_original_candidate_geometry_sha256"]
        == geometry_by_id[row["candidate_id"]]
        for row in requests
    )


def test_admission_binding_rejects_duplicate_or_cross_candidate_identity(tmp_path):
    _baseline, _sources, admission, requests, _old_reviews = _fixture(tmp_path)
    contexts_path = admission.with_name("candidate-contexts.jsonl")
    contexts = [json.loads(line) for line in contexts_path.read_text().splitlines()]
    contexts[1]["original_intent_id"] = contexts[0]["original_intent_id"]
    for field in ("window_id", "historical_cut_ms", "slot_id"):
        contexts[1][field] = contexts[0][field]
    _write_jsonl(contexts_path, contexts)
    with pytest.raises(ValueError, match="duplicate original candidate"):
        module._validate_admission(admission, requests)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update(raw_sha256="not-a-sha"),
        lambda row: row.update(payload_json='{"body":"bad","headline":"x" }'),
    ],
)
def test_source_validation_and_selection_fail_closed(tmp_path, mutation):
    _baseline, sources, _admission, _requests, _old = _fixture(tmp_path)
    bundle = json.loads(sources.read_text(encoding="utf-8"))
    mutation(bundle["sources"][0])
    _write_json(sources, bundle)
    with pytest.raises((ValueError, json.JSONDecodeError)):
        module._validate_sources(sources)


def test_future_and_stale_publications_are_not_selected(tmp_path):
    _baseline, sources, _admission, _requests, _old = _fixture(tmp_path)
    bundle = json.loads(sources.read_text(encoding="utf-8"))
    future = dict(bundle["sources"][0], id="future-news", published_upper_ms=BASE + 1)
    stale = dict(
        bundle["sources"][0],
        id="stale-news",
        published_upper_ms=BASE - module.NEWS_MAX_AGE_MS - 1,
    )
    selected = module._select_sources({"sources": [future, stale]}, BASE)
    assert selected["NEWS"] == []


def test_bundle_flags_cannot_claim_complete_historical_coverage(tmp_path):
    _baseline, sources, _admission, _requests, _old = _fixture(tmp_path)
    bundle = json.loads(sources.read_text(encoding="utf-8"))
    bundle["coverage"] = "COMPLETE"
    _write_json(sources, bundle)
    with pytest.raises(ValueError, match="unknown coverage"):
        module._validate_sources(sources)


def test_finish_validates_only_eligible_replies_and_keeps_actual_clocks(tmp_path):
    baseline, sources, admission, _old_requests, _old_reviews = _fixture(tmp_path)
    output = tmp_path / "proxy"
    module.prepare(_args(baseline, sources, admission, output))
    requests = json.loads((output / "requests.json").read_text(encoding="utf-8"))
    reviews = []
    for index, request in enumerate(
        row for row in requests if row["dispatch_eligible"]
    ):
        reviews.append(
            {
                "candidate_id": request["candidate_id"],
                "prompt_sha256": request["prompt_sha256"],
                "state": "OBSERVED_COMMITTED",
                "decision": "ALLOW" if index % 2 == 0 else "VETO",
                "reason": "diagnostic fixture",
                "model": "gpt-6-luna",
                "effort": "medium",
                "actual_microusd": 100,
                "measured_pipeline_duration_ms": 50,
                "modern_attempt_started_ms": 2_000 + index,
                "modern_response_observed_ms": 2_050 + index,
                "modern_adapter_finished_ms": 2_055 + index,
                "request_id": f"resp-{index}",
                "budget_reservation_id": f"reservation-{index}",
            }
        )
    no_calls = []
    for request in (row for row in requests if not row["dispatch_eligible"]):
        no_calls.append(
            {
                "candidate_id": request["candidate_id"],
                "window_id": request["window_id"],
                "prompt_sha256": request["prompt_sha256"],
                "state": "NOT_CALLED_MISSING_PROXY_CONTEXT",
                "decision": "DEFER",
                "actual_microusd": 0,
            }
        )
    _write_jsonl(output / "reviews.jsonl", reviews)
    _write_jsonl(output / "no-calls.jsonl", no_calls)
    module.finish(_args(baseline, sources, admission, output))
    result = json.loads(
        (output / "proxy-diagnostic-result.json").read_text(encoding="utf-8")
    )
    assert result["candidate_count"] == 12
    assert result["modern_model_calls"] == 9
    assert result["actual_model_cost_microusd"] == 900
    assert result["not_called_missing_proxy_context"] == 3
    assert result["comparison_is_matched_or_causal"] is False
    assert result["native_candidate_review_service_invoked"] is False
    assert result["native_sim_risk_or_execution_invoked"] is False
    assert result["readiness"]["strategy_policy"] == "REJECT_ALL"
    no_call = [
        row
        for row in result["candidate_results"]
        if row["dispatch_state"] == "NOT_CALLED_MISSING_PROXY_CONTEXT"
    ]
    assert len(no_call) == 3
    assert all(
        row["modern_response_observed_ms"] is None and row["actual_microusd"] == 0
        for row in no_call
    )
    assert all(
        row["modern_response_observed_ms"] >= 2_050
        for row in result["candidate_results"]
        if row["dispatch_state"] == "OBSERVED_COMMITTED"
    )


def test_finish_rejects_baseline_or_source_mutation(tmp_path):
    baseline, sources, admission, _old_requests, _old_reviews = _fixture(tmp_path)
    output = tmp_path / "proxy"
    module.prepare(_args(baseline, sources, admission, output))
    (baseline / "result.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="baseline"):
        module.finish(_args(baseline, sources, admission, output))


def test_finish_does_not_overwrite_existing_result(tmp_path):
    baseline, sources, admission, _old_requests, _old_reviews = _fixture(tmp_path)
    output = tmp_path / "proxy"
    module.prepare(_args(baseline, sources, admission, output))
    requests = json.loads((output / "requests.json").read_text(encoding="utf-8"))
    reviews = []
    for index, request in enumerate(
        row for row in requests if row["dispatch_eligible"]
    ):
        reviews.append(
            {
                "candidate_id": request["candidate_id"],
                "prompt_sha256": request["prompt_sha256"],
                "state": "OBSERVED_COMMITTED",
                "decision": "DEFER",
                "model": "gpt-6-luna",
                "effort": "medium",
                "actual_microusd": 100,
                "measured_pipeline_duration_ms": 50,
                "modern_attempt_started_ms": 3_000 + index,
                "modern_response_observed_ms": 3_050 + index,
                "modern_adapter_finished_ms": 3_055 + index,
                "request_id": f"resp-{index}",
                "budget_reservation_id": f"reservation-{index}",
            }
        )
    no_calls = []
    for request in (row for row in requests if not row["dispatch_eligible"]):
        no_calls.append(
            {
                "candidate_id": request["candidate_id"],
                "window_id": request["window_id"],
                "prompt_sha256": request["prompt_sha256"],
                "state": "NOT_CALLED_MISSING_PROXY_CONTEXT",
                "decision": "DEFER",
                "actual_microusd": 0,
            }
        )
    _write_jsonl(output / "reviews.jsonl", reviews)
    _write_jsonl(output / "no-calls.jsonl", no_calls)
    (output / "proxy-diagnostic-result.json").write_text("preserve\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        module.finish(_args(baseline, sources, admission, output))
    assert (output / "proxy-diagnostic-result.json").read_text(
        encoding="utf-8"
    ) == "preserve\n"
