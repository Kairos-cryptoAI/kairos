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


def test_outer_bootstrap_only_failure_returns_sanitized_fail_closed_assessment(tmp_path):
    bootstrap = tmp_path / "bootstrap-failure.json"
    body = b'{"state":"FAILED_CLOSED","reason":"SOURCE_ERROR"}\n'
    bootstrap.write_bytes(body)

    result = assess_directory(tmp_path)

    assert result["state"] == "FAILED_CLOSED_OUTER_BOOTSTRAP"
    assert result["checks"]["outer_bootstrap_failure_absent"] is False
    assert result["checks"]["inner_acceptance_inputs_available_or_valid"] is False
    assert result["full_trade_lifecycle_verified"] is False
    assert result["input_file_presence"]["before.json"] is False
    assert result["input_file_presence"]["current-chain-result.json"] is False
    assert result["input_file_presence"]["bootstrap-failure.json"] is True
    assert result["input_sha256s"]["bootstrap-failure.json"] == hashlib.sha256(body).hexdigest()


def test_plan_reviewed_certificate_requires_actual_call_join_and_deterministic_final_review():
    """Engineering proof-join fixture only, not a real-source acceptance result."""
    from dataclasses import replace

    from test_current_plan import authorize, setup_plan

    from kairos_native_campaign.current_acceptance import _plan_reviewed_entries_bound
    from kairos_native_campaign.current_plan import PLAN_REVIEW_SYSTEM, plan_review_prompt
    from kairos_native_campaign.current_runner import _canonical_sha

    plan, original_review, observations, bars = setup_plan()
    directional_content = json.dumps(
        {
            "long_review": "ALLOW",
            "short_review": "DEFER",
            "proposal": "LONG",
            "evidence_ids": [],
        }
    )
    creation = replace(
        plan.creation_assessment,
        response_sha256=hashlib.sha256(directional_content.encode()).hexdigest(),
    )
    plan = replace(plan, creation_assessment=creation)
    content = '{"decision":"ALLOW","priority":1,"reason_codes":["ENGINEERING_ONLY"]}'
    provenance = original_review.model_provenance.model_copy(
        update={
            "response_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "prompt_sha256": _canonical_sha({"system": PLAN_REVIEW_SYSTEM, "user": plan_review_prompt(plan)}),
        }
    )
    plan_review = replace(
        original_review,
        model_provenance=provenance,
        plan_sha256=plan.sha256,
        reason_codes=("ENGINEERING_ONLY",),
    )
    authorization = authorize(plan, plan_review, observations, bars)
    certificate = authorization.payload()
    request = {
        "sequence": 1,
        "entry_authorization": certificate,
        "entry_authorization_sha256": authorization.sha256,
        "review": authorization.native_review.model_dump(mode="json"),
        "intent": authorization.intent.model_dump(mode="json"),
        "quote": {"entry_quote_sha256": authorization.quote_sha256},
        "observed_request_ms": authorization.authorized_at_ms + 1,
    }
    actual = [
        {
            "budget_reservation_id": provenance.budget_reservation_id,
            "request_id": provenance.request_id,
            "provider": provenance.provider,
            "resolved_model": provenance.model,
            "workload": "aggregator_normal",
            "content": content,
            "attempt_started_at_ts_ms": plan_review.requested_at_ms,
            "response_observed_at_ts_ms": plan_review.response_observed_at_ms,
        },
        {
            "budget_reservation_id": "directional-engineering-only",
            "request_id": "directional-engineering-only",
            "provider": "openai",
            "resolved_model": "engineering-fixture",
            "workload": "aggregator_normal",
            "content": directional_content,
            "attempt_started_at_ts_ms": creation.actual_requested_ms,
            "response_observed_at_ts_ms": creation.actual_completed_ms,
        },
    ]
    planning = {
        "complete": True,
        "objects": {
            plan.sha256: plan.payload(),
            plan_review.sha256: plan_review.payload(),
            authorization.sha256: certificate,
        },
        "provider_requests": {
            provenance.budget_reservation_id: {
                "system": PLAN_REVIEW_SYSTEM,
                "user": plan_review_prompt(plan),
            },
            "directional-engineering-only": {"user": plan.creation_input_json},
        },
    }
    # The acceptance reader receives JSON artifacts, not in-memory tuples and
    # enums from the typed engineering helper.
    planning = json.loads(json.dumps(planning))
    replay = [
        {
            "observed_request_sequence": 1,
            "entry_authorization_sha256": authorization.sha256,
            "entry_review_semantics": "DETERMINISTIC_AFTER_RETAINED_PLAN_MODEL_REVIEW",
        }
    ]
    assert _plan_reviewed_entries_bound(
        {"plan_reviews": ["engineering-only"]}, actual, [request], replay, planning
    )
    assert not _plan_reviewed_entries_bound({"plan_reviews": []}, actual, [request], replay, planning)
    actual[0]["request_id"] = "not-the-model-call"
    assert not _plan_reviewed_entries_bound(
        {"plan_reviews": ["engineering-only"]}, actual, [request], replay, planning
    )


def _native_source_join_fixture():
    """Synthetic semantic-contract fixture, never a real acceptance receipt."""
    from kairos_core.contracts import StrategicAllocation
    from kairos_core.contracts.base import datetime_from_unix_ms
    from kairos_macro.prompts import allocation_system_prompt
    from kairos_macro.strategist import AllocationOutput
    from kairos_text.models import NewsItem
    from kairos_text.prompts import SENTIMENT_SYSTEM
    from kairos_text.sentiment import SentimentExtractor
    from test_current_chain import START

    from kairos_native_campaign.current_acceptance import _actual_text_signals, _macro_news_item
    from kairos_native_campaign.current_plan import STRATEGY_ID

    item = NewsItem(
        title="Bitcoin ETF approval rally",
        body="Bitcoin market news",
        url="https://example.test/bitcoin",
        source="coindesk_rss",
        source_kind="rss",
        published_at=datetime_from_unix_ms(START - 1_000),
        timestamp_is_estimated=False,
        provenance=("https://example.test/bitcoin",),
    )
    receipt = {"persisted_ms": START - 100, "received_ms": START - 200, "raw_sha256": "1" * 64}
    rss = {"receipt": receipt, "items": (item,), "snapshot_sha256": "2" * 64}
    text_request = {
        "system": SENTIMENT_SYSTEM,
        "user": SentimentExtractor(None)._format_batch([item]),
        "requested_ms": START,
    }
    text_result = {
        "budget_reservation_id": "text-fixture-only",
        "workload": "text_scouts",
        "attempt_started_at_ts_ms": START,
        "response_observed_at_ts_ms": START + 500,
        "content": json.dumps(
            {
                "signals": [
                    {
                        "topic": "BTCUSDT",
                        "sentiment": 0.8,
                        "impact": "bullish",
                        "confidence": 0.9,
                        "summary": "Fixture only",
                        "item_ids": [1],
                    }
                ]
            }
        ),
    }
    signal = _actual_text_signals(text_result, text_request, rss, {})[0]
    macro_output = AllocationOutput.model_validate(
        {
            "regime": "CHOP",
            "stable_reserve_pct": 0.2,
            "strategy_weights": [{"strategy_name": STRATEGY_ID, "weight": 0.8}],
            "max_gross_leverage": 1.0,
            "rationale": "Fixture only",
        }
    )
    allocation = StrategicAllocation(
        source="kairos-current-plan-macro",
        produced_at=datetime_from_unix_ms(START + 1_000),
        regime=macro_output.regime,
        stable_reserve_pct=macro_output.stable_reserve_pct,
        strategy_weights=macro_output.strategy_weight_map((STRATEGY_ID,)),
        max_gross_leverage=1.0,
        triggered_by="schedule",
        rationale=macro_output.rationale,
    )
    official = {"captured_ms": START - 2_000, "status": "partial", "fixture_only": True}
    macro_request = {
        "system": allocation_system_prompt((STRATEGY_ID,)),
        "requested_ms": START + 600,
        "user": json.dumps(
            {
                "as_of_ms": START - 50,
                "macro_factors": official,
                "news": {
                    "raw_sha256": receipt["raw_sha256"],
                    "received_ms": receipt["received_ms"],
                    "items": [_macro_news_item(item)],
                },
            }
        ),
    }
    macro_result = {
        "budget_reservation_id": "macro-fixture-only",
        "workload": "macro_strategist",
        "attempt_started_at_ts_ms": START + 600,
        "response_observed_at_ts_ms": START + 900,
        "content": macro_output.model_dump_json(),
    }
    context = [
        {
            "kind": "MACRO",
            "payloads_json": json.dumps([allocation.model_dump(mode="json")]),
            "event_ms": START + 1_000,
            "received_ms": START + 1_010,
            "persisted_ms": START + 1_010,
        },
        {
            "kind": "TEXT",
            "payloads_json": json.dumps([signal.model_dump(mode="json")]),
            "event_ms": START - 1_000,
            "received_ms": START + 550,
            "persisted_ms": START + 550,
        },
    ]
    run = {
        "macro_allocation": allocation.model_dump(mode="json"),
        "text_snapshot_sha256": rss["snapshot_sha256"],
        "macro_provider_reservation_ids": ["macro-fixture-only"],
    }
    planning = {
        "actual_sources": {"complete": True, "rss": [rss], "official_macro": official},
        "objects": {"plan-fixture": {"plan": {"created_at_ms": START + 2_000, "context": context}}},
        "provider_requests": {"text-fixture-only": text_request, "macro-fixture-only": macro_request},
    }
    requests = [{"entry_authorization": {"plan_sha256": "plan-fixture"}}]
    return run, [text_result, macro_result], requests, planning


def test_v3_text_macro_semantics_join_actual_outputs_and_original_request_sources():
    from kairos_native_campaign.current_acceptance import _native_model_sources_bound

    run, actual, requests, planning = _native_source_join_fixture()
    assert _native_model_sources_bound(run, actual, requests, planning)
    # An unrelated successful call no longer grants source/producer credit.
    actual[0]["content"] = '{"signals":[]}'
    assert not _native_model_sources_bound(run, actual, requests, planning)


def test_v3_macro_allocation_fields_and_official_inputs_cannot_be_substituted():
    from kairos_native_campaign.current_acceptance import _native_model_sources_bound

    run, actual, requests, planning = _native_source_join_fixture()
    run["macro_allocation"]["rationale"] = "Not the actual model output"
    assert not _native_model_sources_bound(run, actual, requests, planning)
    run, actual, requests, planning = _native_source_join_fixture()
    request = planning["provider_requests"]["macro-fixture-only"]
    payload = json.loads(request["user"])
    payload["macro_factors"]["captured_ms"] += 1
    request["user"] = json.dumps(payload)
    assert not _native_model_sources_bound(run, actual, requests, planning)


def test_v3_text_confidence_envelope_and_raw_rss_request_cannot_be_forged():
    from kairos_native_campaign.current_acceptance import _native_model_sources_bound

    run, actual, requests, planning = _native_source_join_fixture()
    text = planning["objects"]["plan-fixture"]["plan"]["context"][1]
    signal = json.loads(text["payloads_json"])[0]
    signal["confidence"] = 0.9  # Native cap with one source is exactly 0.65.
    text["payloads_json"] = json.dumps([signal])
    assert not _native_model_sources_bound(run, actual, requests, planning)
    run, actual, requests, planning = _native_source_join_fixture()
    request = planning["provider_requests"]["text-fixture-only"]
    payload = json.loads(request["user"])
    payload["items"][0]["body"] = "Not present in captured RSS"
    request["user"] = json.dumps(payload)
    assert not _native_model_sources_bound(run, actual, requests, planning)


def test_v3_missing_original_sources_or_future_native_wrapping_is_fail_closed():
    from kairos_native_campaign.current_acceptance import _native_model_sources_bound

    run, actual, requests, planning = _native_source_join_fixture()
    planning["actual_sources"]["complete"] = False
    assert not _native_model_sources_bound(run, actual, requests, planning)
    run, actual, requests, planning = _native_source_join_fixture()
    planning["objects"]["plan-fixture"]["plan"]["context"][1]["received_ms"] = 0
    assert not _native_model_sources_bound(run, actual, requests, planning)


def test_outer_bootstrap_directory_path_is_present_and_disqualifying(tmp_path):
    (tmp_path / "bootstrap-failure.json").mkdir()

    result = assess_directory(tmp_path)

    assert result["state"] == "FAILED_CLOSED_OUTER_BOOTSTRAP"
    assert result["outer_bootstrap_failure_parse_status"] == "NON_REGULAR"
    assert result["checks"]["outer_bootstrap_failure_absent"] is False
    assert result["input_file_presence"]["bootstrap-failure.json"] is True
    assert result["input_sha256s"]["bootstrap-failure.json"] is None


def test_malformed_inner_run_with_outer_bootstrap_failure_is_sanitized(tmp_path):
    bootstrap_body = b'{"state":"FAILED_CLOSED"}\n'
    inner_body = b"{not-json"
    (tmp_path / "bootstrap-failure.json").write_bytes(bootstrap_body)
    (tmp_path / "before.json").write_text('{"plan":{}}', encoding="utf-8")
    (tmp_path / "current-chain-result.json").write_bytes(inner_body)

    result = assess_directory(tmp_path)

    assert result["state"] == "FAILED_CLOSED_OUTER_BOOTSTRAP"
    assert result["checks"]["outer_bootstrap_failure_absent"] is False
    assert result["full_trade_lifecycle_verified"] is False
    assert result["input_sha256s"]["bootstrap-failure.json"] == hashlib.sha256(bootstrap_body).hexdigest()
    assert result["input_sha256s"]["current-chain-result.json"] == hashlib.sha256(inner_body).hexdigest()


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
        "incomplete_lifecycles": [
            {"observed_request_sequence": 1, "trade_id": None, "execution_state": "ACTIVE"}
        ],
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
    assert result["checks"]["outer_bootstrap_failure_absent"] is True
    assert result["state"] == "OBSERVED_DECISIONS_WITH_LATER_NATIVE_SIM_ENTRY_VERIFIED"

    bootstrap_path = tmp_path / "bootstrap-failure.json"
    bootstrap_body = b'{"state":"FAILED_CLOSED","reason":"SOURCE_ERROR"}\n'
    bootstrap_path.write_bytes(bootstrap_body)
    outer_failure = assess_directory(tmp_path)
    assert outer_failure["state"] == "PARTIAL_REQUIRED_STAGES_NOT_EXERCISED"
    assert outer_failure["prior_acceptance_state"] == (
        "OBSERVED_DECISIONS_WITH_LATER_NATIVE_SIM_ENTRY_VERIFIED"
    )
    assert outer_failure["checks"]["outer_bootstrap_failure_absent"] is False
    assert "outer_bootstrap_failure_absent" in outer_failure["missing_required_evidence"]
    assert outer_failure["full_trade_lifecycle_verified"] is False
    assert outer_failure["input_file_presence"]["bootstrap-failure.json"] is True
    assert (
        outer_failure["input_sha256s"]["bootstrap-failure.json"] == hashlib.sha256(bootstrap_body).hexdigest()
    )

    for malformed_body, expected_status in ((b"", "EMPTY"), (b"{broken", "INVALID_JSON")):
        bootstrap_path.write_bytes(malformed_body)
        malformed = assess_directory(tmp_path)
        assert malformed["state"] == "PARTIAL_REQUIRED_STAGES_NOT_EXERCISED"
        assert malformed["checks"]["outer_bootstrap_failure_absent"] is False
        assert "outer_bootstrap_failure_absent" in malformed["missing_required_evidence"]
        assert malformed["full_trade_lifecycle_verified"] is False
        assert malformed["outer_bootstrap_failure_parse_status"] == expected_status
        assert (
            malformed["input_sha256s"]["bootstrap-failure.json"] == hashlib.sha256(malformed_body).hexdigest()
        )
    bootstrap_path.unlink()

    replay["incomplete_lifecycles"] = []
    write_json(deferred / "native-replay-result.json", replay)
    missing_unresolved = assess_directory(tmp_path)
    assert not missing_unresolved["checks"]["later_native_sim_replay_bound"]

    replay["incomplete_lifecycles"] = [
        {"observed_request_sequence": 1, "trade_id": None, "execution_state": "ACTIVE"}
    ]
    write_json(deferred / "native-replay-result.json", replay)
    tape_verification_path = tmp_path / "native-tape-verification.json"
    tape_verification = json.loads(tape_verification_path.read_text(encoding="utf-8"))
    tape_verification["plan_sha256"] = source_tape["plan_sha256"]
    write_json(tape_verification_path, tape_verification)
    wrong_plan_binding = assess_directory(tmp_path)
    assert not wrong_plan_binding["checks"]["sealed_native_tape_verified"]
