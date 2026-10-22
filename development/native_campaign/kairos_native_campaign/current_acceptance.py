"""Read-only assessment of real CURRENT run receipts, separate from traversal.

A completed no-signal run is legitimate, but is not evidence that real models,
Risk and SIM fills all occurred. Offline fixtures never satisfy these checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from uuid import UUID

from .current_runner import write_create_only

_OBSERVED_MODE = "CURRENT_OBSERVED_DECISIONS_THEN_SEALED_NATIVE_SIM_REPLAY"
_PLAN_REVIEWED_MODE = "CURRENT_PLAN_REVIEW_THEN_FRESH_QUOTE_NATIVE_SIM_V3"
_REPLAY_MODE = "OFFLINE_NATIVE_SIM_REPLAY_FROM_OBSERVED_DECISIONS"
_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _is_real_provider_call(row: dict, committed: dict) -> bool:
    result = row.get("result", {})
    return (
        row.get("state") == "ACTUAL_RESPONSE"
        and result.get("provider") == "openai"
        and result.get("cached") is False
        and bool(result.get("request_id"))
        and not any(word in result.get("model", "").lower() for word in ("synthetic", "fixture", "dummy"))
        and result.get("budget_reservation_id") in committed
    )


def assess(before: dict, run: dict, responses: list[dict], budget: list[dict]) -> dict:
    committed = {
        row["reservation_id"]: row
        for row in budget
        if row.get("event") == "SHARED_COMMITTED" and row.get("state") == "COMMITTED"
    }
    actual = [row["result"] for row in responses if _is_real_provider_call(row, committed)]
    reservations = [row["budget_reservation_id"] for row in actual]
    if len(set(reservations)) != len(reservations):
        raise ValueError("duplicate physical provider reservation in real-path receipts")
    workloads = [row["workload"] for row in actual]
    stages = {row["name"] for row in run.get("stages", []) if row.get("status") == "COMPLETED"}
    text = run.get("text_poll", {})
    slots = run.get("slot_results", [])
    simulated = run.get("sim_outcomes", [])
    checks = {
        "traversal_completed": run.get("result") == "COMPLETED",
        "prospective_current_not_fixture": before.get("plan", {}).get("mode")
        == "CURRENT_PROSPECTIVE_ENGINEERING_SIM_ONLY",
        "five_symbol_real_bar_capture": len(run.get("history_bar_counts", {})) == 5
        and all(count == 3240 for count in run.get("history_bar_counts", {}).values()),
        "fresh_news_with_actual_text_model": text.get("captured_item_count", 0) > 0
        and "text_scouts" in workloads,
        "actual_macro_model_output": run.get("macro_allocation_origin") == "MODEL_OUTPUT"
        and "macro_strategist" in workloads,
        "current_catalyst_plan_materialized": any(row.get("plan_ids") for row in slots),
        "actual_native_router_and_model_review": any(name.startswith("native_brain_") for name in stages)
        and any(name in {"aggregator_normal", "aggregator_conflict"} for name in workloads),
        "native_sim_risk_persisted": any(name.startswith("persist_sim_risk_decision:") for name in stages),
        "actual_sim_execution_receipt": any(name.startswith("simulation_submit_entry:") for name in stages)
        and any(row.get("fill_receipt") is not None for row in simulated),
    }
    missing = [name for name, passed in checks.items() if not passed]
    full_lifecycle = any(
        row.get("execution_state") == "FLAT" and row.get("closing_receipt") is not None for row in simulated
    )
    return {
        "schema": "kairos.current-real-path-acceptance.v1",
        "state": "REAL_ENTRY_PATH_VERIFIED" if not missing else "PARTIAL_REQUIRED_STAGES_NOT_EXERCISED",
        "traversal_result": run.get("result"),
        "checks": checks,
        "missing_required_evidence": missing,
        "actual_committed_provider_calls": len(actual),
        "committed_workloads": workloads,
        "actual_cost_microusd": sum(row.get("actual_microusd", 0) for row in committed.values()),
        "cost_basis": "EXISTING_REGISTERED_PRICES_NOT_PROVIDER_INVOICE",
        "full_trade_lifecycle_verified": full_lifecycle,
        "offline_fixture_credit": False,
        "profitability_claim": False,
        "historical_or_blind_credit": False,
        "readiness_promotion": False,
        "trading_authority": "NONE",
    }


def _deferred_acceptance(
    before: dict, run: dict, responses: list[dict], budget: list[dict], evidence: dict
) -> dict:
    """Assess observed decisions and later native SIM replay as distinct phases."""
    committed = {
        row["reservation_id"]: row
        for row in budget
        if row.get("event") == "SHARED_COMMITTED" and row.get("state") == "COMMITTED"
    }
    actual = [row["result"] for row in responses if _is_real_provider_call(row, committed)]
    reservations = [row["budget_reservation_id"] for row in actual]
    if len(set(reservations)) != len(reservations):
        raise ValueError("duplicate physical provider reservation in real-path receipts")
    workloads = [row["workload"] for row in actual]
    stages = {row["name"] for row in run.get("stages", []) if row.get("status") == "COMPLETED"}
    text = run.get("text_poll", {})
    slots = run.get("slot_results", [])
    plan_reviewed = before.get("plan", {}).get("mode") == _PLAN_REVIEWED_MODE

    plan = evidence.get("deferred-plan", {})
    replay = evidence.get("native-replay-result", {})
    tape_check = evidence.get("native-tape-verification", {})
    source_tape = evidence.get("continuous-source-receipt", {})
    requests = evidence.get("requests", [])
    durable = evidence.get("durable", {})

    plan_core = {key: value for key, value in plan.items() if key != "plan_sha256"}
    plan_sha = _sha256(_canonical(plan_core)) if plan_core else None
    request_by_sequence = {row.get("sequence"): row for row in requests if isinstance(row, dict)}
    pending = [
        row
        for row in run.get("sim_outcomes", [])
        if row.get("state") == "OBSERVED_REQUEST_PENDING_LATER_NATIVE_SIM_REPLAY"
    ]
    pending_by_sequence = {row.get("observed_request_sequence"): row for row in pending}

    request_bindings_ok = (
        bool(requests)
        and len(requests) == len(request_by_sequence) == len(pending)
        and not evidence.get("unexpected_request_files")
        and evidence.get("inputs_within_byte_limit") is True
    )
    if request_bindings_ok:
        request_bindings_ok = set(request_by_sequence) == set(range(1, len(requests) + 1))
    if request_bindings_ok:
        request_bindings_ok = set(pending_by_sequence) == set(request_by_sequence)
    for sequence, request in request_by_sequence.items():
        intent = request.get("intent", {})
        outcome = pending_by_sequence.get(sequence, {})
        provenance = intent.get("provenance", {}) if isinstance(intent, dict) else {}
        frame = request.get("frame")
        durable_row = durable.get(sequence, {})
        request_body = evidence.get("request_bodies", {}).get(f"request-{sequence:02d}.json")
        if not (
            request.get("schema") == "kairos.current-observed-sim-request.v1"
            and request.get("mode") == _REPLAY_MODE
            and request.get("sequence") == sequence
            and request.get("plan_sha256") == plan.get("plan_sha256")
            and request.get("risk_evaluated_live") is False
            and request.get("actual_venue_order") is False
            and isinstance(intent, dict)
            and intent.get("intent_id") == outcome.get("intent_sha256")
            and outcome.get("actual_live_risk_or_execution") is False
            and provenance.get("strategy_code_sha256") == plan.get("source_set_sha256")
            and provenance.get("config_sha256") == plan.get("model_config_sha256")
            and request_body == _canonical(request) + b"\n"
            and durable_row.get("request_sha256") == _sha256(request_body or b"")
            and type(durable_row.get("journal_durable_ms")) is int
            and durable_row.get("journal_durable_ms", 0) >= request.get("observed_request_ms", 1)
        ):
            request_bindings_ok = False
        if frame is None:
            if request.get("selected_frame_sequence_watermark") is not None:
                request_bindings_ok = False
        elif not isinstance(frame, dict) or not (
            frame.get("tape_id") == plan.get("tape_id")
            and isinstance(intent, dict)
            and frame.get("symbol") == intent.get("symbol")
            and frame.get("tape_sequence") == request.get("selected_frame_sequence_watermark")
        ):
            request_bindings_ok = False

    run_source_sha = run.get("source_set_sha256")
    run_model_sha = run.get("model_config_sha256")
    before_source_sha = (
        _sha256(_canonical(before.get("sources"))) if isinstance(before.get("sources"), dict) else None
    )
    before_model_sha = (
        _sha256(_canonical(before.get("model_routes")))
        if isinstance(before.get("model_routes"), dict)
        else None
    )
    replay_outcomes = replay.get("sim_outcomes", [])
    replay_sequences = [
        row.get("observed_request_sequence") for row in replay_outcomes if isinstance(row, dict)
    ]
    replay_entry_verified = any(
        row.get("replay_risk_approved") is True
        and bool(row.get("admission_id"))
        and isinstance(row.get("fill_receipt"), dict)
        and bool(row.get("fill_receipt"))
        and row.get("execution_state") in {"ACTIVE", "FLAT"}
        and type(row.get("observed_request_sequence")) is int
        and 1 <= row.get("observed_request_sequence", 0) <= len(requests)
        for row in replay_outcomes
        if isinstance(row, dict)
    )
    expected_incomplete = [
        {
            "observed_request_sequence": row.get("observed_request_sequence"),
            "trade_id": row.get("trade_id"),
            "execution_state": row.get("execution_state"),
        }
        for row in replay_outcomes
        if isinstance(row, dict)
        and row.get("replay_risk_approved") is True
        and row.get("execution_state")
        in {None, "ACTIVE", "PENDING", "UNRESOLVED", "NOT_SUBMITTED_ARRIVAL_OUTSIDE_ORIGINAL_WINDOW"}
    ]
    replay_completion_consistent = replay.get("incomplete_lifecycles") == expected_incomplete and replay.get(
        "window_completion"
    ) == ("INSUFFICIENT_FUTURE_OBSERVATION" if expected_incomplete else "NO_UNRESOLVED_REPLAY_TRADES")
    replay_bound = (
        replay.get("schema") == "kairos.current-observed-native-replay.v1"
        and replay.get("mode") == _REPLAY_MODE
        and replay.get("actual_live_risk_or_execution") is False
        and replay.get("plan_sha256") == plan.get("plan_sha256") == plan_sha
        and replay.get("request_count") == len(requests)
        and replay_sequences == list(range(1, len(requests) + 1))
        and replay.get("tape_sha256") == tape_check.get("tape_sha256")
        and replay.get("session_id") == tape_check.get("session_id")
        and replay_entry_verified
        and replay_completion_consistent
        and type(replay.get("actual_replay_started_ms")) is int
        and type(replay.get("actual_replay_completed_ms")) is int
        and replay.get("actual_replay_started_ms") <= replay.get("actual_replay_completed_ms")
    )
    checks = {
        "traversal_completed": run.get("result") == "COMPLETED",
        "observed_decisions_then_native_replay_mode": before.get("plan", {}).get("mode")
        in {_OBSERVED_MODE, _PLAN_REVIEWED_MODE},
        "five_symbol_real_bar_capture": set(run.get("history_bar_counts", {})) == set(_SYMBOLS)
        and all(run.get("history_bar_counts", {}).get(symbol) == 3240 for symbol in _SYMBOLS),
        "fresh_news_with_actual_text_model": text.get("captured_item_count", 0) > 0
        and "text_scouts" in workloads,
        "actual_macro_model_output": run.get("macro_allocation_origin") == "MODEL_OUTPUT"
        and "macro_strategist" in workloads,
        "current_catalyst_plan_materialized": any(row.get("plan_ids") for row in slots),
        "actual_native_router_and_model_review": any(name.startswith("native_brain_") for name in stages)
        and any(name in {"aggregator_normal", "aggregator_conflict"} for name in workloads),
        "deferred_plan_and_source_identity_bound": (
            plan.get("mode") == _REPLAY_MODE
            and plan.get("actual_live_risk_or_execution") is False
            and _is_sha256(plan.get("source_set_sha256"))
            and _is_sha256(plan.get("model_config_sha256"))
            and run_source_sha == plan.get("source_set_sha256") == before_source_sha
            and run_model_sha == plan.get("model_config_sha256") == before_model_sha
            and re.fullmatch(r"current-native-[0-9a-f]{32}", str(plan.get("tape_id", ""))) is not None
            and _is_sha256(plan.get("plan_sha256"))
            and plan_sha == plan.get("plan_sha256")
        ),
        "original_requests_match_pending_outcomes": request_bindings_ok,
        "sealed_native_tape_verified": (
            tape_check.get("state") == "PASS_RECORDED_NATIVE_SOURCE_TAPE_ONLY"
            and before.get("plan", {}).get("actual_live_risk_or_execution") is False
            and tape_check.get("capture_only_no_models") is False
            and tape_check.get("replay_mode") == _REPLAY_MODE
            and tape_check.get("tape_sha256") == replay.get("tape_sha256")
            and tape_check.get("tape_id") == plan.get("tape_id")
            and tape_check.get("plan_sha256") == plan.get("plan_sha256")
            and tape_check.get("session_id") == replay.get("session_id")
            and tape_check.get("observed_request_count") == len(requests)
            and isinstance(tape_check.get("full_closed_bar_counts"), dict)
            and set(tape_check.get("full_closed_bar_counts", {})) == set(_SYMBOLS)
            and all(tape_check["full_closed_bar_counts"].get(symbol, 0) >= 3240 for symbol in _SYMBOLS)
            and source_tape.get("state") == "CAPTURED"
            and source_tape.get("tape_id") == plan.get("tape_id")
            and _is_sha256(source_tape.get("plan_sha256"))
            and _is_sha256(source_tape.get("receipt_sha256"))
            and source_tape.get("receipt_sha256")
            == _sha256(
                _canonical({key: value for key, value in source_tape.items() if key != "receipt_sha256"})
            )
            and type(tape_check.get("original_v2_frame_count")) is int
            and tape_check.get("original_v2_frame_count", 0) > 0
            and tape_check.get("original_v2_frame_count", 0) == source_tape.get("frame_count")
            and replay.get("source_end_watermark", {}).get("original_frame_count")
            == source_tape.get("frame_count")
            and type(source_tape.get("frame_count")) is int
            and source_tape.get("frame_count", 0) > 0
            and source_tape.get("text_delivery_count") == source_tape.get("frame_count")
            and type(source_tape.get("text_delivery_bytes")) is int
            and source_tape.get("text_delivery_bytes", 0) > 0
            and source_tape.get("text_delivery_bytes") == source_tape.get("admitted_raw_payload_bytes")
            and type(source_tape.get("symbol_counts")) is dict
            and set(source_tape.get("symbol_counts", {})) == set(_SYMBOLS)
            and all(type(source_tape["symbol_counts"].get(symbol)) is int for symbol in _SYMBOLS)
            and all(source_tape["symbol_counts"].get(symbol, 0) > 0 for symbol in _SYMBOLS)
            and sum(source_tape["symbol_counts"].values()) == source_tape.get("frame_count")
        ),
        "later_native_sim_replay_bound": replay_bound,
    }
    if plan_reviewed:
        # New explicit binding: real plan-level model output followed by a
        # separately proved deterministic entry, NOT final-intent LLM review.
        del checks["actual_native_router_and_model_review"]
        checks["current_catalyst_plan_materialized"] = any(
            _is_sha256(row.get("plan_sha256")) for row in slots
        )
        checks["actual_plan_model_and_deterministic_entry_bound"] = _plan_reviewed_entries_bound(
            run, actual, requests, replay_outcomes, evidence.get("planning", {})
        )
        checks["actual_native_text_macro_outputs_and_sources_bound"] = _native_model_sources_bound(
            run, actual, requests, evidence.get("planning", {})
        )
        checks["new_plan_profile_not_frozen_campaign"] = (
            run.get("schema_version") == "kairos.current-plan-run.v3"
            and before.get("plan", {}).get("frozen_campaign_mutation") is False
            and before.get("plan", {}).get("review_binding")
            == "REAL_MODEL_PLAN_THEN_DETERMINISTIC_EXACT_ENTRY"
        )
    missing = [name for name, passed in checks.items() if not passed]
    replay_unresolved = replay.get("incomplete_lifecycles")
    full_lifecycle = (
        isinstance(replay_outcomes, list)
        and any(
            row.get("execution_state") == "FLAT"
            and isinstance(row.get("closing_receipt"), dict)
            and bool(row.get("closing_receipt"))
            for row in replay_outcomes
            if isinstance(row, dict)
        )
        and replay_unresolved == []
        and not any(
            row.get("replay_risk_approved") is True
            and row.get("execution_state")
            in {None, "ACTIVE", "PENDING", "UNRESOLVED", "NOT_SUBMITTED_ARRIVAL_OUTSIDE_ORIGINAL_WINDOW"}
            for row in replay_outcomes
            if isinstance(row, dict)
        )
        and replay.get("window_completion") == "NO_UNRESOLVED_REPLAY_TRADES"
        and replay.get("full_trade_lifecycle_verified") is True
    )
    return {
        "schema": "kairos.current-real-path-acceptance.v1",
        "state": (
            "PLAN_REVIEWED_FRESH_ENTRY_WITH_NATIVE_SIM_VERIFIED"
            if plan_reviewed
            else "OBSERVED_DECISIONS_WITH_LATER_NATIVE_SIM_ENTRY_VERIFIED"
        )
        if not missing
        else "PARTIAL_REQUIRED_STAGES_NOT_EXERCISED",
        "traversal_result": run.get("result"),
        "checks": checks,
        "missing_required_evidence": missing,
        "actual_committed_provider_calls": len(actual),
        "committed_workloads": workloads,
        "actual_cost_microusd": sum(row.get("actual_microusd", 0) for row in committed.values()),
        "cost_basis": "EXISTING_REGISTERED_PRICES_NOT_PROVIDER_INVOICE",
        "full_trade_lifecycle_verified": full_lifecycle,
        "offline_fixture_credit": False,
        "profitability_claim": False,
        "historical_or_blind_credit": False,
        "readiness_promotion": False,
        "trading_authority": "NONE",
        "risk_and_controller_classification": "LATER_NATIVE_SIM_REPLAY_NOT_ACTUAL_LIVE_EXECUTION",
        "entry_review_semantics": "DETERMINISTIC_AFTER_REAL_PLAN_MODEL_REVIEW"
        if plan_reviewed
        else "EXACT_FINAL_INTENT_MODEL_REVIEW",
    }


def _plan_reviewed_entries_bound(run, actual, requests, replay_outcomes, planning) -> bool:
    from kairos_aggregator.candidate_review import CandidateReviewOutput

    from .current_plan import POLICY_ID, STRATEGY_ID, STRATEGY_REVISION

    objects = planning.get("objects", {})
    provider_requests = planning.get("provider_requests", {})
    if not requests or planning.get("complete") is not True:
        return False
    results = {row.get("budget_reservation_id"): row for row in actual}
    for request in requests:
        certificate = request.get("entry_authorization", {})
        review = request.get("review", {})
        intent = request.get("intent", {})
        plan_document = objects.get(certificate.get("plan_sha256"), {})
        review_document = objects.get(certificate.get("plan_review_sha256"), {})
        plan = plan_document.get("plan", {})
        plan_review = review_document.get("plan_review", {})
        provenance = plan_review.get("model_provenance", {})
        result = results.get(provenance.get("budget_reservation_id"), {})
        provider_request = provider_requests.get(provenance.get("budget_reservation_id"), {})
        try:
            prompt = json.loads(provider_request.get("user", ""))
            output = CandidateReviewOutput.model_validate_json(result.get("content", ""))
        except (ValueError, TypeError):
            return False
        payload_sha = _sha256(_canonical(certificate))
        matches_replay = any(
            row.get("observed_request_sequence") == request.get("sequence")
            and row.get("entry_authorization_sha256") == payload_sha
            and row.get("entry_review_semantics") == "DETERMINISTIC_AFTER_RETAINED_PLAN_MODEL_REVIEW"
            for row in replay_outcomes
        )
        if not (
            certificate.get("schema") == "kairos.current-plan-entry-authorization.v1"
            and certificate.get("policy")
            == plan_document.get("policy")
            == review_document.get("policy")
            == POLICY_ID
            and objects.get(payload_sha) == certificate
            and request.get("entry_authorization_sha256") == payload_sha
            and certificate.get("native_review") == review
            and review.get("intent") == intent
            and certificate.get("quote_sha256") == request.get("quote", {}).get("entry_quote_sha256")
            and dict(intent.get("metadata", ())).get("entry_quote_sha256") == certificate.get("quote_sha256")
            and dict(intent.get("metadata", ())).get("current_plan_sha256") == certificate.get("plan_sha256")
            and dict(intent.get("metadata", ())).get("current_plan_review_sha256")
            == certificate.get("plan_review_sha256")
            and review.get("reviewer") == "DETERMINISTIC"
            and review.get("model_provenance") is None
            and review.get("decision") == plan_review.get("decision") == "ALLOW"
            and output.decision.value == "ALLOW"
            and output.priority == plan_review.get("priority")
            and tuple(output.reason_codes) == tuple(plan_review.get("reason_codes", ()))
            and intent.get("strategy_id") == STRATEGY_ID
            and intent.get("strategy_revision") == STRATEGY_REVISION
            and plan_review.get("plan_sha256") == certificate.get("plan_sha256")
            and plan_review.get("context_sha256") == certificate.get("context_sha256")
            and result.get("request_id") == provenance.get("request_id")
            and (result.get("resolved_model") or result.get("model")) == provenance.get("model")
            and result.get("provider") == provenance.get("provider") == "openai"
            and result.get("workload") in {"aggregator_normal", "aggregator_conflict"}
            and provenance.get("response_sha256") == _sha256(str(result.get("content", "")).encode("utf-8"))
            and provenance.get("prompt_sha256")
            == _sha256(_canonical({key: provider_request.get(key) for key in ("system", "user")}))
            and prompt.get("plan_sha256") == certificate.get("plan_sha256")
            and prompt.get("plan") == plan
            and prompt.get("authority") == "PLANNING_ONLY_NO_EXECUTABLE_QUOTE_OR_ORDER"
            and prompt.get("planning_route", {}).get("workload") == result.get("workload")
            and all(
                type(value) is int
                for value in (
                    plan.get("created_at_ms"),
                    plan_review.get("requested_at_ms"),
                    plan_review.get("response_observed_at_ms"),
                    plan_review.get("completed_at_ms"),
                    certificate.get("authorized_at_ms"),
                    request.get("observed_request_ms"),
                    intent.get("entry_expires_ts_ms"),
                )
            )
            and plan["created_at_ms"]
            <= plan_review["requested_at_ms"]
            <= plan_review["response_observed_at_ms"]
            <= plan_review["completed_at_ms"]
            <= certificate["authorized_at_ms"]
            <= request["observed_request_ms"]
            <= intent["entry_expires_ts_ms"]
            and result.get("attempt_started_at_ts_ms") == plan_review.get("requested_at_ms")
            and result.get("response_observed_at_ts_ms") == plan_review.get("response_observed_at_ms")
            and matches_replay
            and _actual_directional_creation_bound(plan, actual, provider_requests)
        ):
            return False
    return bool(run.get("plan_reviews"))


def _actual_directional_creation_bound(plan, actual, provider_requests) -> bool:
    if plan.get("origin") == "TECHNICAL":
        return plan.get("creation_assessment") is None
    if plan.get("origin") != "CONTEXT_PROPOSAL":
        return False
    from adaptive_replay.complex_assessment import DirectionalAssessment

    assessment = plan.get("creation_assessment") or {}
    matches = []
    for result in actual:
        request = provider_requests.get(result.get("budget_reservation_id"), {})
        if (
            request.get("user") != plan.get("creation_input_json")
            or result.get("workload") != "aggregator_normal"
            or _sha256(str(result.get("content", "")).encode("utf-8")) != assessment.get("response_sha256")
            or result.get("attempt_started_at_ts_ms") != assessment.get("actual_requested_ms")
            or result.get("response_observed_at_ts_ms") != assessment.get("actual_completed_ms")
        ):
            continue
        try:
            parsed = DirectionalAssessment.model_validate_json(result["content"])
        except (ValueError, TypeError):
            continue
        if parsed.proposal == assessment.get("direction") == plan.get("template", {}).get("side"):
            matches.append(result)
    return len(matches) == 1


def _native_model_sources_bound(run, actual, requests, planning) -> bool:
    """V3-only semantic join, not credit for unrelated successful model calls."""
    from kairos_core.contracts import StrategicAllocation
    from kairos_macro.prompts import allocation_system_prompt
    from kairos_macro.strategist import AllocationOutput

    from .current_plan import STRATEGY_ID

    sources = planning.get("actual_sources", {})
    provider_requests = planning.get("provider_requests", {})
    if sources.get("complete") is not True or not requests:
        return False
    try:
        rss = next(
            item for item in sources["rss"] if item["snapshot_sha256"] == run.get("text_snapshot_sha256")
        )
        allocation = StrategicAllocation.model_validate(run.get("macro_allocation", {}))
        if (
            allocation.source != "kairos-current-plan-macro"
            or allocation.triggered_by.value != "schedule"
            or allocation.correlation_id is not None
            or allocation.causation_id is not None
            or UUID(allocation.message_id).version != 4
        ):
            return False
        macro_matches = []
        reconstructed_signals = {}
        signal_completed = {}
        for result in actual:
            request = provider_requests.get(result.get("budget_reservation_id"), {})
            if result.get("workload") == "text_scouts":
                for signal in _actual_text_signals(result, request, rss, run):
                    body = signal.model_dump(mode="json")
                    if (
                        signal.message_id in reconstructed_signals
                        and reconstructed_signals[signal.message_id] != body
                    ):
                        return False
                    reconstructed_signals[signal.message_id] = body
                    signal_completed[signal.message_id] = result["response_observed_at_ts_ms"]
            if result.get("workload") != "macro_strategist":
                continue
            payload = json.loads(request.get("user", ""))
            output = AllocationOutput.model_validate_json(result.get("content", ""))
            expected = {
                "regime": output.regime.value,
                "stable_reserve_pct": output.stable_reserve_pct,
                "strategy_weights": output.strategy_weight_map((STRATEGY_ID,)),
                "max_gross_leverage": output.max_gross_leverage,
                "rationale": output.rationale,
            }
            allocation_body = allocation.model_dump(mode="json")
            news = payload.get("news", {})
            if (
                result.get("budget_reservation_id") not in run.get("macro_provider_reservation_ids", ())
                or request.get("system") != allocation_system_prompt((STRATEGY_ID,))
                or any(allocation_body[key] != value for key, value in expected.items())
                or payload.get("macro_factors") != sources["official_macro"]
                or news.get("raw_sha256") != rss["receipt"]["raw_sha256"]
                or news.get("received_ms") != rss["receipt"]["received_ms"]
                or news.get("items") != [_macro_news_item(item) for item in rss["items"]]
                or not _actual_call_clock(result, request, rss["receipt"]["persisted_ms"])
                or not sources["official_macro"]["captured_ms"]
                <= payload["as_of_ms"]
                <= request["requested_ms"]
            ):
                continue
            macro_matches.append(result)
        if len(macro_matches) != 1 or not reconstructed_signals:
            return False
        macro_result = macro_matches[0]
        produced_ms = int(allocation.produced_at.timestamp() * 1_000)
        if produced_ms < macro_result["response_observed_at_ts_ms"]:
            return False
        for request in requests:
            certificate = request.get("entry_authorization", {})
            plan = planning["objects"][certificate["plan_sha256"]]["plan"]
            context = {source["kind"]: source for source in plan["context"]}
            macro_source = context["MACRO"]
            if (
                json.loads(macro_source["payloads_json"]) != [allocation.model_dump(mode="json")]
                or macro_source["event_ms"] != produced_ms
                or not produced_ms
                <= macro_source["received_ms"]
                <= macro_source["persisted_ms"]
                <= plan["created_at_ms"]
            ):
                return False
            text_source = context["TEXT"]
            text = json.loads(text_source["payloads_json"])
            if not text or any(
                reconstructed_signals.get(signal.get("message_id")) != signal for signal in text
            ):
                return False
            if (
                text_source["event_ms"]
                != min(
                    int(datetime.fromisoformat(s["produced_at"].replace("Z", "+00:00")).timestamp() * 1_000)
                    for s in text
                )
                or not max(signal_completed[s["message_id"]] for s in text)
                <= text_source["received_ms"]
                <= text_source["persisted_ms"]
                <= plan["created_at_ms"]
            ):
                return False
        return True
    except (ValueError, TypeError, KeyError, StopIteration, AttributeError):
        return False


def _actual_call_clock(result, request, source_persisted_ms):
    values = (
        source_persisted_ms,
        request.get("requested_ms"),
        result.get("attempt_started_at_ts_ms"),
        result.get("response_observed_at_ts_ms"),
    )
    return all(type(value) is int for value in values) and tuple(sorted(values)) == values


def _macro_news_item(item):
    return {
        "title": item.title,
        "body": item.body,
        "url": item.url,
        "published_at": item.published_at.isoformat(),
    }


def _actual_text_signals(result, request, rss, run):
    """Reconstruct native stable envelopes and confidence calibration without a gateway."""
    from kairos_core.contracts.base import datetime_from_unix_ms
    from kairos_text.config import TextSettings
    from kairos_text.dedup import EventDeduplicator
    from kairos_text.filter import LocalRelevanceFilter
    from kairos_text.freshness import EventFreshnessFilter
    from kairos_text.normalize import EventNormalizer
    from kairos_text.prompts import SENTIMENT_SYSTEM
    from kairos_text.schemas import SentimentBatch
    from kairos_text.sentiment import _MIN_DIRECTIONAL_SENTIMENT, _MIN_MODEL_CONFIDENCE, _confidence_cap
    from kairos_text.signals import build_signal

    if request.get("system") != SENTIMENT_SYSTEM or not _actual_call_clock(
        result, request, rss["receipt"]["persisted_ms"]
    ):
        return []
    settings = TextSettings(_env_file=None, service_name="kairos-current-plan-text", bus_backend="memory")
    started = next(
        (
            stage["started_ms"]
            for stage in run.get("stages", ())
            if stage.get("name") == "text_scouts_poll_once"
        ),
        request["requested_ms"],
    )
    if not rss["receipt"]["persisted_ms"] <= started <= request["requested_ms"]:
        return []
    timely = EventFreshnessFilter(
        settings.max_event_age_s,
        settings.max_future_skew_s,
        allow_estimated_timestamps=settings.allow_estimated_timestamps,
        clock=lambda: datetime_from_unix_ms(started),
    ).select(EventNormalizer().normalize(rss["items"]))
    relevant = LocalRelevanceFilter(settings.relevance_threshold, settings.top_k).select(
        EventDeduplicator(settings.dedup_window_s).collapse_batch(timely)
    )
    expected_items = [
        {"id": index, "source": item.source, "source_kind": item.source_kind, **_macro_news_item(item)}
        for index, item in enumerate(relevant, 1)
    ]
    if json.loads(request.get("user", "")).get("items") != expected_items:
        return []
    batch = SentimentBatch.model_validate_json(result.get("content", ""))
    signals = []
    for output in batch.signals:
        ids = output.item_ids
        if len(ids) != len(set(ids)) or any(type(i) is not int or not 1 <= i <= len(relevant) for i in ids):
            continue
        evidence = [relevant[i - 1] for i in ids]
        refs = sorted({ref for item in evidence for ref in item.provenance_refs}, key=str.casefold)
        if (
            not refs
            or output.confidence < _MIN_MODEL_CONFIDENCE
            or (output.sentiment > 0 and output.impact.value != "bullish")
            or (output.sentiment < 0 and output.impact.value != "bearish")
            or abs(output.sentiment) < _MIN_DIRECTIONAL_SENTIMENT
            or output.impact.value == "neutral"
        ):
            continue
        signals.append(
            build_signal(
                source="kairos-current-plan-text",
                topic=output.topic,
                sentiment=output.sentiment,
                impact=output.impact,
                confidence=min(output.confidence, _confidence_cap(len(refs))),
                sources=refs,
                summary=output.summary,
                evidence=evidence,
            )
        )
    return signals


def _load_planning_evidence(root, responses, input_hashes, input_presence) -> dict:
    """Join bounded create-only planning artifacts to recorded physical calls."""
    folder = root / "plan-reviews"
    files = sorted(folder.glob("*.json")) if folder.is_dir() else []
    complete = bool(files) and len(files) <= 32
    objects, provider_requests = {}, {}
    total_bytes = 0
    try:
        if not complete:
            return {"complete": False, "objects": {}, "provider_requests": {}}
        for path in files:
            body = _read(path)
            total_bytes += len(body)
            if total_bytes > 32 * 1024 * 1024:
                raise ValueError("bounded planning proof required")
            name = path.relative_to(root).as_posix()
            input_hashes[name] = _sha256(body)
            input_presence[name] = True
            value = json.loads(body)
            if not isinstance(value, dict):
                raise ValueError("typed planning proof object required")
            objects[_sha256(_canonical(value))] = value
        for response in responses:
            index = response.get("index")
            if type(index) is not int or not 1 <= index <= 24:
                raise ValueError("bounded actual provider index required")
            path = root / f"provider-{index:02d}.request.json"
            body = _read(path)
            request = json.loads(body)
            # The recorder hashes canonical request bytes before appending its
            # final newline. Preserve exact bytes, not a recomposed prompt.
            if body != _canonical(request) + b"\n" or _sha256(body[:-1]) != response.get("request_sha256"):
                raise ValueError("actual planning provider request changed")
            input_hashes[path.name] = _sha256(body)
            input_presence[path.name] = True
            reservation = response.get("result", {}).get("budget_reservation_id")
            if reservation:
                provider_requests[reservation] = request
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        complete = False
    sources = (
        _load_actual_model_sources(root, input_hashes, input_presence) if complete else {"complete": False}
    )
    return {
        "complete": complete,
        "objects": objects,
        "provider_requests": provider_requests,
        "actual_sources": sources,
    }


def _load_actual_model_sources(root, input_hashes, input_presence):
    """Reparse retained RSS and audit original official capture, without network or writes."""
    from adaptive_replay.historical_context import import_archive
    from adaptive_replay.official_context_capture import audit_official_context_capture

    from .current_capture import TEXT_TTL_MS, _strict_rss_items
    from .current_macro import describe_official_context

    used = 0

    def retain(path):
        nonlocal used
        if path.is_symlink() or not path.is_file():
            raise ValueError("regular retained source file required")
        body = _read(path)
        used += len(body)
        if used > 32 * 1024 * 1024:
            raise ValueError("bounded retained model sources required")
        name = path.relative_to(root).as_posix()
        input_hashes[name], input_presence[name] = _sha256(body), True
        return body

    try:
        receipt_paths = sorted(root.glob("current-public-capture-*/?*-rss.receipt.json"))
        if not 1 <= len(receipt_paths) <= 4:
            raise ValueError("bounded original RSS capture required")
        rss = []
        for path in receipt_paths:
            receipt = json.loads(retain(path))
            if receipt.get("schema") != "kairos.current-public-rss-capture.v1":
                raise ValueError("original RSS source receipt required")
            raw_name = receipt["raw_file"]
            if type(raw_name) is not str or Path(raw_name).name != raw_name:
                raise ValueError("local original RSS raw file required")
            raw = retain(path.parent / raw_name)
            if _sha256(raw) != receipt["raw_sha256"] or len(raw) != receipt["bytes"]:
                raise ValueError("original RSS body hash mismatch")
            items, ids = _strict_rss_items(raw, received_ms=receipt["received_ms"], text_feed=receipt["url"])
            if list(ids) != receipt["item_ids"]:
                raise ValueError("original RSS item identity mismatch")
            fresh = tuple(
                item
                for item in items
                if receipt["received_ms"] - TEXT_TTL_MS
                <= (int(item.published_at.timestamp() * 1_000))
                <= receipt["received_ms"]
            )
            if len(items) != receipt["raw_item_count"] or len(fresh) != receipt["fresh_item_count"]:
                raise ValueError("original RSS count mismatch")
            identity = {
                "source_name": receipt["source_id"],
                "raw_sha256": receipt["raw_sha256"],
                **{
                    key: receipt[key]
                    for key in ("requested_ms", "received_ms", "persisted_ms", "item_ids", "coverage_scope")
                },
            }
            rss.append({"receipt": receipt, "items": fresh, "snapshot_sha256": _sha256(_canonical(identity))})
        official = json.loads(retain(root / "official-macro-context.json"))
        candidates = sorted(root.glob("official-context-*/receipt.json"))
        if not 1 <= len(candidates) <= 4:
            raise ValueError("bounded original official capture required")
        matched = []
        for path in candidates:
            body = retain(path)
            if _sha256(body) != official["receipt_sha256"]:
                continue
            audit_official_context_capture(path.parent, official["receipt_sha256"])
            receipt = json.loads(body)
            files = sorted(p for p in path.parent.iterdir() if p.is_file())
            if len(files) > 12:
                raise ValueError("bounded official source roster required")
            for source in files:
                retain(source)
            archive = import_archive(
                (path.parent / "historical-context.json").read_bytes(), receipt["archive_sha256"]
            )
            reconstructed = describe_official_context(
                receipt, archive, receipt_sha256=official["receipt_sha256"]
            )
            if reconstructed != official:
                raise ValueError("official context does not match audited original sources")
            matched.append(official)
        if len(matched) != 1:
            raise ValueError("unique original official capture required")
        return {"complete": True, "rss": rss, "official_macro": official}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {"complete": False}


def _read(path: Path) -> bytes:
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("bounded current receipt required")
    return path.read_bytes()


def _bootstrap_failure_input(path: Path) -> tuple[bool, str, str | None]:
    """Return bounded, sanitized metadata and the exact input hash.

    Presence is itself disqualifying: this artifact records an outer bootstrap
    failure that can supersede an inner traversal/replay completion marker.
    Never include its contents or parser exception in an acceptance receipt.
    """
    if not path.exists():
        return False, "ABSENT", _sha256(b"")
    if not path.is_file():
        return True, "NON_REGULAR", None
    try:
        size = path.stat().st_size
        if size > 8 * 1024 * 1024:
            return True, "OVERSIZED_HASH_UNAVAILABLE", None
        body = path.read_bytes()
    except OSError:
        return True, "UNREADABLE_HASH_UNAVAILABLE", None
    if not body:
        return True, "EMPTY", _sha256(body)
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return True, "INVALID_JSON", _sha256(body)
    return True, "VALID_JSON_OBJECT" if isinstance(value, dict) else "VALID_JSON_NON_OBJECT", _sha256(body)


def _apply_bootstrap_failure_guard(result: dict, *, present: bool, parse_status: str) -> None:
    result["checks"]["outer_bootstrap_failure_absent"] = not present
    result["outer_bootstrap_failure_parse_status"] = parse_status
    if not present:
        return
    result["prior_acceptance_state"] = result["state"]
    result["prior_full_trade_lifecycle_verified"] = result["full_trade_lifecycle_verified"]
    result["state"] = "PARTIAL_REQUIRED_STAGES_NOT_EXERCISED"
    result["full_trade_lifecycle_verified"] = False
    if "outer_bootstrap_failure_absent" not in result["missing_required_evidence"]:
        result["missing_required_evidence"].append("outer_bootstrap_failure_absent")


def _outer_bootstrap_only_failure(
    root: Path,
    bodies: dict[str, bytes],
    *,
    bootstrap_status: str,
    bootstrap_sha: str | None,
) -> dict:
    names = ("before.json", "current-chain-result.json", "provider-results.jsonl", "budget.jsonl")
    input_hashes = {name: _sha256(bodies.get(name, b"")) for name in names}
    input_hashes["bootstrap-failure.json"] = bootstrap_sha
    presence = {name: (root / name).is_file() for name in names}
    presence["bootstrap-failure.json"] = True
    return {
        "schema": "kairos.current-real-path-acceptance.v1",
        "state": "FAILED_CLOSED_OUTER_BOOTSTRAP",
        "traversal_result": None,
        "checks": {
            "outer_bootstrap_failure_absent": False,
            "inner_acceptance_inputs_available_or_valid": False,
        },
        "missing_required_evidence": [
            "outer_bootstrap_failure_absent",
            "inner_acceptance_inputs_available_or_valid",
        ],
        "outer_bootstrap_failure_parse_status": bootstrap_status,
        "full_trade_lifecycle_verified": False,
        "offline_fixture_credit": False,
        "profitability_claim": False,
        "historical_or_blind_credit": False,
        "readiness_promotion": False,
        "trading_authority": "NONE",
        "input_sha256s": input_hashes,
        "input_file_presence": presence,
    }


def assess_directory(root: Path) -> dict:
    names = ("before.json", "current-chain-result.json", "provider-results.jsonl", "budget.jsonl")
    bootstrap_present, bootstrap_status, bootstrap_sha = _bootstrap_failure_input(
        root / "bootstrap-failure.json"
    )
    bodies = {}
    try:
        for name in names:
            path = root / name
            bodies[name] = _read(path) if path.exists() else b""
    except (OSError, ValueError):
        if not bootstrap_present:
            raise
        return _outer_bootstrap_only_failure(
            root,
            bodies,
            bootstrap_status=bootstrap_status,
            bootstrap_sha=bootstrap_sha,
        )
    if bootstrap_present:
        try:
            before_value = json.loads(bodies["before.json"]) if bodies["before.json"] else None
            run_value = json.loads(bodies["current-chain-result.json"])
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _outer_bootstrap_only_failure(
                root,
                bodies,
                bootstrap_status=bootstrap_status,
                bootstrap_sha=bootstrap_sha,
            )
        if not isinstance(before_value, dict) or not isinstance(run_value, dict):
            return _outer_bootstrap_only_failure(
                root,
                bodies,
                bootstrap_status=bootstrap_status,
                bootstrap_sha=bootstrap_sha,
            )
    before = json.loads(bodies["before.json"])
    run = json.loads(bodies["current-chain-result.json"])
    responses = [json.loads(line) for line in bodies["provider-results.jsonl"].splitlines() if line]
    budget = [json.loads(line) for line in bodies["budget.jsonl"].splitlines() if line]
    input_hashes = {name: hashlib.sha256(body).hexdigest() for name, body in bodies.items()}
    input_hashes["bootstrap-failure.json"] = bootstrap_sha
    input_presence = {name: (root / name).is_file() for name in names}
    input_presence["bootstrap-failure.json"] = bootstrap_present

    if before.get("plan", {}).get("mode") not in {_OBSERVED_MODE, _PLAN_REVIEWED_MODE}:
        result = assess(before, run, responses, budget)
    else:
        request_root = root / "deferred-sim-requests"
        deferred_paths = {
            "deferred-plan": request_root / "plan.json",
            "native-replay-result": request_root / "native-replay-result.json",
            "native-tape-verification": root / "native-tape-verification.json",
            "continuous-source-receipt": root / "continuous-source-receipt.json",
        }
        deferred_bodies = {
            key: _read(path) if path.is_file() else b"" for key, path in deferred_paths.items()
        }
        input_hashes.update(
            {
                path.relative_to(root).as_posix(): _sha256(deferred_bodies[key])
                for key, path in deferred_paths.items()
            }
        )
        input_presence.update(
            {path.relative_to(root).as_posix(): path.is_file() for path in deferred_paths.values()}
        )
        request_files = (
            sorted(
                path
                for path in request_root.glob("*")
                if re.fullmatch(r"request-\d{2}(?:\.durable)?\.json", path.name)
            )
            if request_root.is_dir()
            else []
        )
        deferred_bytes = sum(path.stat().st_size for path in request_files)
        deferred_bytes += sum(len(body) for body in deferred_bodies.values())
        deferred_inputs_within_byte_limit = len(request_files) <= 10 and deferred_bytes <= 32 * 1024 * 1024
        allowed_request_names = {"plan.json", "native-replay-result.json"} | {
            path.name for path in request_files
        }
        actual_request_names = (
            {path.name for path in request_root.iterdir()} if request_root.is_dir() else set()
        )
        unexpected_request_files = sorted(actual_request_names - allowed_request_names)
        request_bodies = {}
        for path in request_files:
            request_bodies[path.name] = _read(path)
            input_hashes[path.relative_to(root).as_posix()] = _sha256(request_bodies[path.name])
            input_presence[path.relative_to(root).as_posix()] = True
        requests = []
        durable = {}
        for path in request_files:
            match = re.fullmatch(r"request-(\d{2})(\.durable)?\.json", path.name)
            sequence = int(match.group(1))
            if match.group(2):
                durable[sequence] = json.loads(request_bodies[path.name])
            else:
                requests.append(json.loads(request_bodies[path.name]))
                input_presence[path.relative_to(root).as_posix()] = True
        evidence = {
            **{key: json.loads(body) for key, body in deferred_bodies.items() if body},
            "requests": requests,
            "durable": durable,
            "request_bodies": request_bodies,
            "unexpected_request_files": unexpected_request_files,
            "inputs_within_byte_limit": deferred_inputs_within_byte_limit,
        }
        if before.get("plan", {}).get("mode") == _PLAN_REVIEWED_MODE:
            evidence["planning"] = _load_planning_evidence(root, responses, input_hashes, input_presence)
        result = _deferred_acceptance(before, run, responses, budget, evidence)
    _apply_bootstrap_failure_guard(result, present=bootstrap_present, parse_status=bootstrap_status)
    result["input_sha256s"] = input_hashes
    result["input_file_presence"] = input_presence
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    args = parser.parse_args()
    root = args.run_directory
    result = assess_directory(root)
    write_create_only(root / "verification-acceptance.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
