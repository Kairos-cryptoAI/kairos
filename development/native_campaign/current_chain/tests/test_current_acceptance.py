import hashlib
import json

from kairos_native_campaign.current_acceptance import assess, assess_directory


def test_completed_real_macro_and_quiet_market_are_not_a_full_path_pass():
    before = {"plan": {"mode": "CURRENT_PROSPECTIVE_ENGINEERING_SIM_ONLY"}}
    run = {
        "result": "COMPLETED",
        "history_bar_counts": dict.fromkeys(("BTC", "ETH", "SOL", "BNB", "XRP"), 3240),
        "text_poll": {"captured_item_count": 0},
        "macro_allocation_origin": "MODEL_OUTPUT",
    }
    budget = [
        {
            "event": "SHARED_COMMITTED",
            "state": "COMMITTED",
            "reservation_id": "real-1",
            "actual_microusd": 100,
        }
    ]
    response = [
        {
            "state": "ACTUAL_RESPONSE",
            "result": {
                "provider": "openai",
                "request_id": "resp-real",
                "model": "gpt-6.1-sol",
                "cached": False,
                "budget_reservation_id": "real-1",
                "workload": "macro_strategist",
            },
        }
    ]
    result = assess(before, run, response, budget)
    assert result["state"] == "PARTIAL_REQUIRED_STAGES_NOT_EXERCISED"
    assert result["checks"]["actual_macro_model_output"]
    assert not result["checks"]["actual_sim_execution_receipt"]
    assert "fresh_news_with_actual_text_model" in result["missing_required_evidence"]
    assert result["actual_cost_microusd"] == 100


def test_fixture_transport_or_uncommitted_call_cannot_satisfy_real_model_evidence():
    responses = [
        {
            "state": "ACTUAL_RESPONSE",
            "result": {
                "provider": "openai",
                "request_id": "fake",
                "model": "synthetic-no-provider",
                "budget_reservation_id": "fake-1",
                "workload": "macro_strategist",
            },
        }
    ]
    result = assess({}, {"macro_allocation_origin": "MODEL_OUTPUT"}, responses, [])
    assert result["actual_committed_provider_calls"] == 0
    assert not result["checks"]["actual_macro_model_output"]
    assert not result["offline_fixture_credit"]


def test_old_cached_response_is_not_a_new_physical_model_call():
    responses = [
        {
            "state": "ACTUAL_RESPONSE",
            "result": {
                "provider": "openai",
                "request_id": "resp-cached",
                "model": "gpt-6.1-sol",
                "cached": True,
                "budget_reservation_id": "cache-1",
                "workload": "macro_strategist",
            },
        }
    ]
    budget = [
        {"event": "SHARED_COMMITTED", "state": "COMMITTED", "reservation_id": "cache-1", "actual_microusd": 0}
    ]
    result = assess({}, {"macro_allocation_origin": "MODEL_OUTPUT"}, responses, budget)
    assert result["actual_committed_provider_calls"] == 0
    assert not result["checks"]["actual_macro_model_output"]


def test_absent_cache_field_is_not_proof_of_a_physical_model_call():
    response = {
        "state": "ACTUAL_RESPONSE",
        "result": {
            "provider": "openai",
            "request_id": "resp-unknown-cache",
            "model": "gpt-6.1-sol",
            "budget_reservation_id": "unknown-cache",
            "workload": "macro_strategist",
        },
    }
    budget = [
        {
            "event": "SHARED_COMMITTED",
            "state": "COMMITTED",
            "reservation_id": "unknown-cache",
            "actual_microusd": 0,
        }
    ]
    result = assess({}, {"result": "FAILED_CLOSED"}, [response], budget)
    assert result["actual_committed_provider_calls"] == 0
    assert not result["checks"]["traversal_completed"]


def test_synthetic_new_mode_receipts_are_labeled_and_never_gain_entry_credit(tmp_path):
    """Synthetic unit receipts exercise fail-closed handling, not real evidence."""
    (tmp_path / "before.json").write_text(
        json.dumps(
            {
                "plan": {
                    "mode": "CURRENT_OBSERVED_DECISIONS_THEN_SEALED_NATIVE_SIM_REPLAY",
                    "actual_live_risk_or_execution": False,
                },
                "sources": {},
                "model_routes": {},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "current-chain-result.json").write_text(
        json.dumps({"result": "COMPLETED", "sim_outcomes": []}), encoding="utf-8"
    )
    (tmp_path / "provider-results.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "budget.jsonl").write_text("", encoding="utf-8")
    deferred = tmp_path / "deferred-sim-requests"
    deferred.mkdir()
    synthetic_plan = {"mode": "OFFLINE_NATIVE_SIM_REPLAY_FROM_OBSERVED_DECISIONS"}
    plan_path = deferred / "plan.json"
    plan_path.write_text(json.dumps(synthetic_plan), encoding="utf-8")

    result = assess_directory(tmp_path)

    assert result["state"] == "PARTIAL_REQUIRED_STAGES_NOT_EXERCISED"
    assert result["checks"]["observed_decisions_then_native_replay_mode"]
    assert not result["checks"]["original_requests_match_pending_outcomes"]
    assert not result["checks"]["later_native_sim_replay_bound"]
    assert result["actual_committed_provider_calls"] == 0
    assert result["full_trade_lifecycle_verified"] is False
    assert result["offline_fixture_credit"] is False
    assert (
        result["input_sha256s"]["deferred-sim-requests/plan.json"]
        == hashlib.sha256(plan_path.read_bytes()).hexdigest()
    )


def test_synthetic_positive_deferred_receipt_contract_only(tmp_path):
    """Synthetic contract fixture validates fields only; it is not real-path evidence."""

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

    def write_json(path, value):
        path.write_bytes(canonical(value) + b"\n")

    def digest(value):
        return hashlib.sha256(canonical(value)).hexdigest()

    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
    sources, model_routes = {"test": "source"}, {"test": "model"}
    source_sha, model_sha = digest(sources), digest(model_routes)
    before = {
        "plan": {
            "mode": "CURRENT_OBSERVED_DECISIONS_THEN_SEALED_NATIVE_SIM_REPLAY",
            "actual_live_risk_or_execution": False,
        },
        "sources": sources,
        "model_routes": model_routes,
    }
    (tmp_path / "before.json").write_bytes(canonical(before))
    intent_id = "synthetic-intent-1"
    plan = {
        "mode": "OFFLINE_NATIVE_SIM_REPLAY_FROM_OBSERVED_DECISIONS",
        "tape_id": "current-native-" + "a" * 32,
        "assumptions": {"synthetic": True},
        "strategy_allowlist": [{"strategy_id": "synthetic", "strategy_revision": "test"}],
        "started_at_ms": 100,
        "ends_at_ms": 200,
        "source_set_sha256": source_sha,
        "model_config_sha256": model_sha,
        "actual_live_risk_or_execution": False,
    }
    plan["plan_sha256"] = digest(plan)
    request = {
        "schema": "kairos.current-observed-sim-request.v1",
        "mode": plan["mode"],
        "sequence": 1,
        "plan_sha256": plan["plan_sha256"],
        "observed_request_ms": 150,
        "intent": {
            "intent_id": intent_id,
            "symbol": "BTCUSDT",
            "provenance": {"strategy_code_sha256": source_sha, "config_sha256": model_sha},
        },
        "frame": {
            "tape_id": plan["tape_id"],
            "symbol": "BTCUSDT",
            "tape_sequence": 1,
        },
        "selected_frame_sequence_watermark": 1,
        "risk_evaluated_live": False,
        "actual_venue_order": False,
    }
    request_body = canonical(request) + b"\n"
    deferred = tmp_path / "deferred-sim-requests"
    deferred.mkdir()
    (deferred / "plan.json").write_bytes(canonical(plan) + b"\n")
    (deferred / "request-01.json").write_bytes(request_body)
    write_json(
        deferred / "request-01.durable.json",
        {"request_sha256": hashlib.sha256(request_body).hexdigest(), "journal_durable_ms": 151},
    )
    replay = {
        "schema": "kairos.current-observed-native-replay.v1",
        "mode": plan["mode"],
        "plan_sha256": plan["plan_sha256"],
        "session_id": "synthetic-session",
        "tape_sha256": "b" * 64,
        "actual_replay_started_ms": 300,
        "actual_replay_completed_ms": 301,
        "request_count": 1,
        "sim_outcomes": [
            {
                "observed_request_sequence": 1,
                "replay_risk_approved": True,
                "admission_id": "synthetic-admission",
                "execution_state": "ACTIVE",
                "fill_receipt": {"receipt_id": "synthetic-fill"},
                "closing_receipt": None,
            }
        ],
        "source_end_watermark": {"original_frame_count": 5},
        "incomplete_lifecycles": [{"observed_request_sequence": 1, "execution_state": "ACTIVE"}],
        "window_completion": "INSUFFICIENT_FUTURE_OBSERVATION",
        "full_trade_lifecycle_verified": False,
        "actual_live_risk_or_execution": False,
    }
    write_json(deferred / "native-replay-result.json", replay)
    source_tape = {
        "schema": "kairos.current-continuous-native-tape.v1",
        "state": "CAPTURED",
        "tape_id": plan["tape_id"],
        "plan_sha256": "c" * 64,
        "frame_count": 5,
        "text_delivery_count": 5,
        "text_delivery_bytes": 100,
        "admitted_raw_payload_bytes": 100,
        "delivery_count": 5,
        "delivered_body_bytes": 100,
        "symbol_counts": dict.fromkeys(symbols, 1),
    }
    source_tape["receipt_sha256"] = digest(source_tape)
    write_json(tmp_path / "continuous-source-receipt.json", source_tape)
    write_json(
        tmp_path / "native-tape-verification.json",
        {
            "state": "PASS_RECORDED_NATIVE_SOURCE_TAPE_ONLY",
            "tape_sha256": replay["tape_sha256"],
            "tape_id": plan["tape_id"],
            "plan_sha256": plan["plan_sha256"],
            "session_id": replay["session_id"],
            "full_closed_bar_counts": dict.fromkeys(symbols, 3240),
            "original_v2_frame_count": 5,
            "observed_request_count": 1,
            "capture_only_no_models": False,
            "replay_mode": plan["mode"],
        },
    )
    run = {
        "result": "COMPLETED",
        "source_set_sha256": source_sha,
        "model_config_sha256": model_sha,
        "history_bar_counts": dict.fromkeys(symbols, 3240),
        "text_poll": {"captured_item_count": 1},
        "macro_allocation_origin": "MODEL_OUTPUT",
        "slot_results": [{"plan_ids": ["synthetic-catalyst"]}],
        "stages": [{"name": "native_brain_review", "status": "COMPLETED"}],
        "sim_outcomes": [
            {
                "state": "OBSERVED_REQUEST_PENDING_LATER_NATIVE_SIM_REPLAY",
                "intent_sha256": intent_id,
                "observed_request_sequence": 1,
                "actual_live_risk_or_execution": False,
            },
            {"state": "OTHER_LEGITIMATE_NON_PENDING_OUTCOME"},
        ],
    }
    (tmp_path / "current-chain-result.json").write_bytes(canonical(run))
    workloads = ("text_scouts", "macro_strategist", "aggregator_normal")
    budget, responses = [], []
    for index, workload in enumerate(workloads, 1):
        reservation = f"synthetic-reservation-{index}"
        budget.append(
            {
                "event": "SHARED_COMMITTED",
                "state": "COMMITTED",
                "reservation_id": reservation,
                "actual_microusd": 1,
            }
        )
        responses.append(
            {
                "state": "ACTUAL_RESPONSE",
                "result": {
                    "provider": "openai",
                    "request_id": f"synthetic-request-{index}",
                    "model": "gpt-6.1-sol",
                    "cached": False,
                    "budget_reservation_id": reservation,
                    "workload": workload,
                },
            }
        )
    (tmp_path / "provider-results.jsonl").write_bytes(b"".join(canonical(row) + b"\n" for row in responses))
    (tmp_path / "budget.jsonl").write_bytes(b"".join(canonical(row) + b"\n" for row in budget))

    result = assess_directory(tmp_path)

    assert result["state"] == "OBSERVED_DECISIONS_WITH_LATER_NATIVE_SIM_ENTRY_VERIFIED"
    assert result["checks"]["original_requests_match_pending_outcomes"]
    assert result["checks"]["sealed_native_tape_verified"]
    assert result["checks"]["later_native_sim_replay_bound"]
    assert result["full_trade_lifecycle_verified"] is False
    assert result["risk_and_controller_classification"] == "LATER_NATIVE_SIM_REPLAY_NOT_ACTUAL_LIVE_EXECUTION"

    replay["incomplete_lifecycles"] = []
    write_json(deferred / "native-replay-result.json", replay)
    missing_unresolved = assess_directory(tmp_path)
    assert not missing_unresolved["checks"]["later_native_sim_replay_bound"]

    replay["incomplete_lifecycles"] = [{"observed_request_sequence": 1, "execution_state": "ACTIVE"}]
    write_json(deferred / "native-replay-result.json", replay)
    tape_verification_path = tmp_path / "native-tape-verification.json"
    tape_verification = json.loads(tape_verification_path.read_text(encoding="utf-8"))
    tape_verification["plan_sha256"] = source_tape["plan_sha256"]
    write_json(tape_verification_path, tape_verification)
    wrong_plan_binding = assess_directory(tmp_path)
    assert not wrong_plan_binding["checks"]["sealed_native_tape_verified"]
