from kairos_native_campaign.current_acceptance import assess


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
