"""Audit the single published attempt's bytes/ledgers; never replay historical prices."""

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from kairos_core.enums import Side
from kairos_strategy.models import ExitPlan, SleeveIntent

from adaptive_replay.historical_context import digest
from adaptive_replay.inputs import UNIVERSE
from adaptive_replay.scenario_compare import END_MS, START_MS, matching_audit

ROOT = Path(__file__).parents[1] / "evidence" / "scenario-comparison-2026-10-08"
RESULT_SHA = "e03238519765b9d2368c1c3da9408b9eaf0e94811a5d9059bdec12be55fbf697"


def read(name):
    return json.loads((ROOT / name).read_bytes())


def jsonl(name):
    return [json.loads(line) for line in (ROOT / name).read_bytes().splitlines()]


def test_original_attempt_inventory_is_exact_and_complete_not_partial():
    result = read("result.json")
    assert hashlib.sha256((ROOT / "result.json").read_bytes()).hexdigest() == RESULT_SHA
    assert result["state"] == "COMPLETED_PRICE_ONLY_DIAGNOSTIC_NOT_QUALIFICATION"
    assert len(result["files_sha256"]) == 15
    assert {p.name for p in ROOT.iterdir()} == set(result["files_sha256"]) | {"result.json"}
    for name, expected in result["files_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    assert not (ROOT / "failure.json").exists() and not (ROOT / "hard-timeout.json").exists()


def test_source_closure_policy_clocks_and_unavailable_full_system_are_retained():
    result, protocol = read("result.json"), read("protocol.json")
    assert read("before.json")["sources"] == read("after.json")["sources"]
    assert read("after.json")["source_receipt_unchanged"] is True
    assert result["protocol_sha256"] == digest(protocol)
    assert protocol["start_ms"] == START_MS and protocol["end_exclusive_ms"] == END_MS
    assert protocol["required_sources"] == [["MARKET", "archive-bars-1m"]]
    assert protocol["scenario_requires_review"] is False
    assert result["provider_calls"] == 0 and result["blind_campaign_credit"] is False
    assert result["complete_system_economics"] is None and result["model_feed_costs"] is None
    assert result["llm_arms"] == "UNAVAILABLE_NOT_EXECUTED_NOT_ZERO_PNL"
    for field, value in result["readiness"].items():
        assert value == "REJECT_ALL" if field == "STRATEGY_POLICY" else value is False


def test_full_roster_unsupported_subgroups_and_unchanged_native_candidates():
    pairs, denominator = jsonl("pairs.jsonl"), jsonl("denominator.jsonl")
    expected = {(cut, symbol) for cut in range(START_MS, END_MS, 300_000) for symbol in UNIVERSE}
    assert len(pairs) == 360 and {(r["cut_ms"], r["symbol"]) for r in pairs} == expected
    assert len(denominator) == 1800
    assert {(r["cut_ms"], r["symbol"]) for r in denominator} == {
        (cut, symbol) for cut in range(START_MS, END_MS, 60_000) for symbol in UNIVERSE
    }
    assert Counter(r["state"] for r in denominator) == {
        "NOT_SCHEDULED_NATIVE_CADENCE": 1440,
        "QUIET": 324,
        "CANDIDATE": 36,
    }
    assert (ROOT / "scenarios.jsonl").read_bytes() == b""
    assert all(r["scenario_outcome"] is None and not r["scenario_supported"] for r in pairs)
    assert all(r["scenario_candidate_id"] is None and r["preparation"]["plan"] is None for r in pairs)
    subgroups = Counter()
    identities = set()
    for row in pairs:
        raw = row["decision"]["candidate"]
        if raw is None:
            assert row["decision"]["state"] == "QUIET"
            continue
        values = dict(raw)
        expected_id = values.pop("intent_id")
        values["side"] = Side(values["side"])
        values["exit_plan"] = ExitPlan(**values["exit_plan"])
        values["metadata"] = tuple(tuple(p) for p in values["metadata"])
        native = SleeveIntent(**values)
        assert native.intent_id == expected_id and expected_id not in identities
        identities.add(expected_id)
        assert native.sleeve_id == "trend_breakout_v1" and native.symbol == row["symbol"]
        assert native.decision_ts_ms == row["cut_ms"] - 1
        assert native.entry_eligible_ts_ms == row["cut_ms"]
        assert native.entry_expires_ts_ms == row["cut_ms"] + 299_999
        assert native.exit_plan.trailing_activation_price is not None
        subgroups[(row["decision"]["regime"], row["preparation"]["reason"])] += 1
    assert subgroups == {
        ("UNCERTAIN", "SCENARIO_V1_UNSUPPORTED_REGIME"): 25,
        ("BEAR", "SCENARIO_V1_UNSUPPORTED_TRAILING"): 11,
    }
    assert read("result.json")["counts"]["supported_scenarios"] == 0


def test_all_eight_accounts_and_matched_outcomes_reconcile_without_new_replay():
    result, pairs = read("result.json"), jsonl("pairs.jsonl")
    expected_closes = {
        "base-strict_minute_open": 14,
        "base-intrabar_open_proxy": 4,
        "stress-strict_minute_open": 7,
        "stress-intrabar_open_proxy": 0,
    }
    assert set(result["conditional_trading_net_comparison"]) == set(expected_closes)
    for name, expected_count in expected_closes.items():
        arms = read(f"{name}-accounts.json")
        recorded = read(f"{name}-matched.json")
        assert matching_audit(pairs, arms) == recorded
        assert arms["immediate"]["economic_results"]["closed_trades"] == expected_count
        for arm, data in arms.items():
            report, trades, events = data["economic_results"], data["trades"], data["events"]
            assert report == result["conditional_trading_net_comparison"][name]["accounts"][arm]
            assert report["closed_trades"] == len(trades)
            entries = [e for e in events if e["kind"] == "ENTRY"]
            rejected = [e for e in events if e["kind"] == "REJECT"]
            assert len(entries) == len(trades)
            assert len(entries) + len(rejected) == (36 if arm == "immediate" else 0)
            assert not report["terminal_unresolved_positions"] and report["forced_settlements"] == 0
            net = math.fsum(t["net_pnl_usd"] for t in trades)
            assert math.isclose(net, report["closed_trade_net_usd"], abs_tol=1e-9)
            assert math.isclose(10_000 + net, report["final_equity_usd"], abs_tol=1e-9)
            assert abs(report["ledger_reconciliation_error_usd"]) < 1e-7
            assert report["model_cost_usd"] is None and report["market_feed_cost_usd"] is None
            assert report["complete_all_in_net_economics"] is False
        assert (
            recorded["primary_account_delta_usd"]
            == result["conditional_trading_net_comparison"][name]["primary_account_delta_usd"]
        )
        assert recorded["complete_system_net_delta_usd"] is None
