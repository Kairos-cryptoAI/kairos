"""Read-only assessment of real CURRENT run receipts, separate from traversal.

A completed no-signal run is legitimate, but is not evidence that real models,
Risk and SIM fills all occurred. Offline fixtures never satisfy these checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from .current_runner import write_create_only

_OBSERVED_MODE = "CURRENT_OBSERVED_DECISIONS_THEN_SEALED_NATIVE_SIM_REPLAY"
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
            "execution_state": row.get("execution_state"),
        }
        for row in replay_outcomes
        if isinstance(row, dict)
        and row.get("replay_risk_approved") is True
        and row.get("execution_state")
        in {None, "ACTIVE", "PENDING_ENTRY", "NOT_SUBMITTED_ARRIVAL_OUTSIDE_ORIGINAL_WINDOW"}
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
        "observed_decisions_then_native_replay_mode": before.get("plan", {}).get("mode") == _OBSERVED_MODE,
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
            in {None, "ACTIVE", "PENDING_ENTRY", "NOT_SUBMITTED_ARRIVAL_OUTSIDE_ORIGINAL_WINDOW"}
            for row in replay_outcomes
            if isinstance(row, dict)
        )
        and replay.get("window_completion") == "NO_UNRESOLVED_REPLAY_TRADES"
        and replay.get("full_trade_lifecycle_verified") is True
    )
    return {
        "schema": "kairos.current-real-path-acceptance.v1",
        "state": "OBSERVED_DECISIONS_WITH_LATER_NATIVE_SIM_ENTRY_VERIFIED"
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
    }


def _read(path: Path) -> bytes:
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("bounded current receipt required")
    return path.read_bytes()


def assess_directory(root: Path) -> dict:
    names = ("before.json", "current-chain-result.json", "provider-results.jsonl", "budget.jsonl")
    bodies = {name: _read(root / name) if (root / name).exists() else b"" for name in names}
    before = json.loads(bodies["before.json"])
    run = json.loads(bodies["current-chain-result.json"])
    responses = [json.loads(line) for line in bodies["provider-results.jsonl"].splitlines() if line]
    budget = [json.loads(line) for line in bodies["budget.jsonl"].splitlines() if line]
    input_hashes = {name: hashlib.sha256(body).hexdigest() for name, body in bodies.items()}
    input_presence = {name: (root / name).is_file() for name in names}

    if before.get("plan", {}).get("mode") != _OBSERVED_MODE:
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
        result = _deferred_acceptance(before, run, responses, budget, evidence)
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
