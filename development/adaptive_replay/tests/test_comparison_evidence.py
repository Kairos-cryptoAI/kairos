"""Verify published diagnostic artifacts without market downloads or reruns."""

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from adaptive_replay import compare

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "evidence" / "comparison-2026-10-06"


def read(relative):
    return json.loads((EVIDENCE / relative).read_text(encoding="utf-8"))


def test_retained_comparison_files_preserve_both_attempts_exact_bytes():
    manifest = read("checksums.json")
    paths = set()
    for item in manifest["files"]:
        path = EVIDENCE / item["path"]
        assert path.is_relative_to(EVIDENCE)
        assert item["path"] not in paths
        paths.add(item["path"])
        encoded = path.read_bytes()
        assert len(encoded) == item["bytes"]
        assert hashlib.sha256(encoded).hexdigest() == item["sha256"]
    assert len(paths) == 61
    assert paths | {"checksums.json"} == {
        p.relative_to(EVIDENCE).as_posix() for p in EVIDENCE.rglob("*") if p.is_file()
    }
    assert not any(path.endswith("decisions.jsonl") for path in paths)
    assert read("initial-failure.json")["state"] == "FAILED_CLOSED"
    assert read("result.json")["state"] == "COMPLETED"
    assert hashlib.sha256((EVIDENCE / "result.json").read_bytes()).hexdigest() == (
        "895b7aee5d8741cd0869cf2fad5eaa9a311f85edabe5ff4a8b800c4c9435a56c"
    )


def test_all_64_comparison_accounts_reconcile_with_retained_natural_ledgers():
    result = read("result.json")
    account_count = ledger_count = 0
    for window in result["windows"]:
        for arm in window["arms"]:
            root = f"{window['window']['id']}/{arm['arm_id']}"
            for report in arm["economic_results"]:
                account_count += 1
                entries = sum(report["entries_each_utc_day"].values())
                assert entries == report["closed_trades"]
                assert (
                    entries + sum(report["admission_rejections"].values()) == arm["counts"]["raw_candidates"]
                )
                assert report["terminal_unresolved_positions"] == []
                assert report["forced_settlements"] == 0
                assert abs(report["ledger_reconciliation_error_usd"]) < 1e-7
                assert math.isclose(
                    report["final_equity_usd"],
                    10_000 + report["closed_trade_net_usd"],
                    abs_tol=1e-7,
                )
                if not entries:
                    assert report["profit_factor"] is None
                    assert report["profit_factor_status"] == "NO_TRADES"
                    continue
                ledger_count += 1
                label = f"{report['entry_mode'].lower()}-{report['cost_scenario']['id']}"
                ledger = read(f"{root}/{label}-ledger.json")
                trades = ledger["trades"]
                admitted = [e for e in ledger["events"] if e["kind"] == "ENTRY"]
                assert len(trades) == len(admitted) == entries
                assert Counter(t["intent_id"] for t in trades) == Counter(e["intent_id"] for e in admitted)
                assert all(n == 1 for n in Counter(t["intent_id"] for t in trades).values())
                assert Counter(t["sleeve_id"] for t in trades) == report["closed_trades_by_family"]
                assert Counter(t["reason"] for t in trades) == report["natural_exit_counts"]
                for trade in trades:
                    assert trade["exit_ms"] >= trade["entry_ms"]
                    assert trade["holding_ms"] == trade["exit_ms"] - trade["entry_ms"]
                    assert trade["entry_fee_usd"] >= 0 and trade["exit_fee_usd"] >= 0
                    direction = 1 if trade["side"] == "LONG" else -1
                    gross = direction * trade["quantity"] * (trade["exit_price"] - trade["entry_price"])
                    net = (
                        gross
                        - trade["entry_fee_usd"]
                        - trade["exit_fee_usd"]
                        - trade["signed_funding_cost_usd"]
                    )
                    assert math.isclose(gross, trade["gross_pnl_usd"], abs_tol=1e-7)
                    assert math.isclose(net, trade["net_pnl_usd"], abs_tol=1e-7)
                assert math.isclose(
                    math.fsum(t["net_pnl_usd"] for t in trades),
                    report["closed_trade_net_usd"],
                    abs_tol=1e-7,
                )
                for field, key in (
                    ("total_entry_fees_usd", "entry_fee_usd"),
                    ("total_exit_fees_usd", "exit_fee_usd"),
                    ("signed_funding_cost_usd", "signed_funding_cost_usd"),
                ):
                    assert math.isclose(math.fsum(t[key] for t in trades), report[field], abs_tol=1e-7)
    assert account_count == 64
    assert ledger_count == 23


def test_published_source_availability_and_native_prefix_evidence_are_not_invented():
    result = read("result.json")
    plan, _ = compare.load_comparison_plan(ROOT / "comparison-plan.json")
    assert read("sealed-comparison-plan.json") == plan
    assert result["sources"]["comparison_plan_sha256"] == compare.digest(plan)
    assert read("before.json")["sources"] == result["sources"]
    candidates = Counter()
    for window in result["windows"]:
        window_id = window["window"]["id"]
        native = read(f"{window_id}/native-baseline-evidence.json")
        assert native["identities"] == result["sources"]["baseline_identities"]
        assert native["warmup_hours"] == 54
        assert native["exit_tail_used"] is False
        for family in native["baselines"].values():
            assert len(family["symbols"]) == 5
            assert all(len(v["verified_prefix_cuts_ms"]) == 3 for v in family["symbols"].values())
        adaptive = read(f"{window_id}/adaptive-tape-evidence.json")
        assert adaptive["original_result_sha256"] == compare.ADAPTIVE_RESULT_SHA
        assert adaptive["original_economic_results_reused"] is False
        assert adaptive["scheduled_slots"] == 4320
        assert set(adaptive["statuses"]) <= {"INTENT", "NO_INTENT"}
        for arm in window["arms"]:
            counts = arm["counts"]
            candidates[arm["arm_id"]] += counts["raw_candidates"]
            assert counts == read(f"{window_id}/{arm['arm_id']}/tape-receipt.json")
            assert counts["scheduled_slots"] == counts["verified_input_ready_slots"] == 4320
            assert counts["quiet_slots"] + counts["raw_candidates"] == 4320
            if arm["arm_id"] == compare.STRATEGY_ID:
                assert counts["source_ready_slots"] == 4320
                assert counts["source_unavailable_slots"] == 0
            else:
                assert counts["source_ready_slots"] is None
                assert counts["source_unavailable_slots"] is None
    assert candidates == {
        "trend_breakout_v1": 583,
        "range_mean_reversion_v1": 140,
        "fixed_breakout_range_union_v1": 723,
        "adaptive_pullback_range_v1": 12,
    }


def test_comparison_does_not_create_authority_or_hide_mark_time_risk_overrun():
    result = read("result.json")
    assert result["qualified_winner"] is None
    assert result["strategy_selected_for_live"] is None
    assert result["compound_return_across_windows"] is None
    assert result["blind_results_read"] is False
    assert result["blind_campaign_days_added"] == result["paid_calls"] == 0
    assert result["readiness"]["STRATEGY_POLICY"] == "REJECT_ALL"
    assert not any(v for k, v in result["readiness"].items() if k != "STRATEGY_POLICY")
    overruns = []
    for window in result["windows"]:
        for arm in window["arms"]:
            for report in arm["economic_results"]:
                assert report["execution_qualification"] is False
                assert report["complete_all_in_net_economics"] is False
                assert report["model_calls"] == 0 and report["model_cost_usd"] is None
                if report["risk_ceiling_mark_overrun"]:
                    overruns.append((window["window"]["id"], arm["arm_id"], report["entry_mode"]))
                    assert report["max_observed_mark_open_risk_fraction"] > 0.01
    assert overruns == [
        ("june_2022", "trend_breakout_v1", "STRICT_MINUTE_OPEN"),
        ("june_2022", "fixed_breakout_range_union_v1", "STRICT_MINUTE_OPEN"),
    ]
