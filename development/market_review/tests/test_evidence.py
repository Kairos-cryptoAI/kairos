"""Audit saved real receipts without ever repeating paid requests."""

import hashlib
import json
from pathlib import Path

import pytest

EVIDENCE = Path(__file__).parents[1] / "evidence" / "2026-10-10"


def load(name):
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def test_public_receipt_bytes_and_sealed_sources_are_unchanged():
    for name, expected in load("public-receipt-files.json")["files_sha256"].items():
        assert hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest() == expected
    for name, expected in load("result.json")["sources"][
        "experiment_scripts_sha256"
    ].items():
        assert (
            hashlib.sha256(
                (EVIDENCE / "sealed-sources" / f"{name}.txt").read_bytes()
            ).hexdigest()
            == expected
        )


def test_exact_native_candidate_review_coverage_and_costs():
    requests = load("requests.json")
    reviews = [
        json.loads(line)
        for line in (EVIDENCE / "reviews.jsonl").read_text().splitlines()
    ]
    assert len(requests) == len(reviews) == 12
    assert {r["candidate_id"] for r in reviews} == {r["candidate_id"] for r in requests}
    assert len({r["candidate_id"] for r in reviews}) == 12
    assert all(r["state"] == "OBSERVED_COMMITTED" for r in reviews)
    assert all(r["model"] == "gpt-6-luna" and r["effort"] == "medium" for r in reviews)
    assert sum(r["actual_microusd"] for r in reviews) == 8804
    assert load("worker-result.json")["local_budgeted_microusd"] == 8804


def test_prior_cumulative_budget_not_reset_and_unknown_holds_not_released():
    before = load("gateway-source.json")["cumulative_budget_before"]
    after = load("worker-result.json")["cumulative_budget_after"]
    assert (
        before["campaign_id"] == after["campaign_id"] == "kairos-dev-qualification-v1"
    )
    assert before["budget_microusd"] == after["budget_microusd"] == 12_000_000
    assert (
        before["historical_cost_microusd"] == after["historical_cost_microusd"] == 1984
    )
    assert before["reserved_cost_microusd"] == after["reserved_cost_microusd"] == 154624
    assert after["committed_cost_microusd"] - before["committed_cost_microusd"] == 8804


def test_all_three_arms_all_windows_both_cost_and_timing_modes_retained():
    result = load("result.json")
    rows = result["results"]
    identities = {
        (
            r["window"]["id"],
            r["arm"],
            r["report"]["entry_mode"],
            r["report"]["cost_scenario"]["id"],
        )
        for r in rows
    }
    assert len(rows) == len(identities) == 48
    assert result["blind_campaign_days_added"] == 0
    assert result["full_news_macro_system_tested"] is False
    assert result["readiness"]["STRATEGY_POLICY"] == "REJECT_ALL"
    assert not any(
        value for key, value in result["readiness"].items() if key != "STRATEGY_POLICY"
    )
    assert (
        max(abs(r["report"]["ledger_reconciliation_error_usd"]) for r in rows) < 1e-11
    )
    assert all(r["report"]["terminal_unresolved_positions"] == [] for r in rows)
    assert not any(r["report"]["risk_ceiling_mark_overrun"] for r in rows)
    assert all(
        r["report"]["closed_trades"] == 0
        for r in rows
        if r["report"]["entry_mode"] == "STRICT_MINUTE_OPEN"
    )
    for window in ("may_2022", "june_2022"):
        review = next(
            r
            for r in rows
            if r["window"]["id"] == window
            and r["arm"] == "market_llm_review"
            and r["report"]["entry_mode"] == "INTRABAR_OPEN_PROXY"
            and r["report"]["cost_scenario"]["id"] == "base"
        )
        assert review["known_model_cost_usd"] > 0
        assert review["report"]["recorded_service_cost_usd"] == pytest.approx(
            review["known_model_cost_usd"]
        )
