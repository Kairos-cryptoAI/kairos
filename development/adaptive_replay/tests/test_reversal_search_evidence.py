"""Audit sealed original bytes and conditional arithmetic without market replay."""

import gzip
import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from adaptive_replay.failed_reversal import POLICY_SHA256, STRATEGY_ID
from adaptive_replay.historical_context import canonical, digest
from adaptive_replay.reversal_search import ARMS, WINDOWS, fixed_search_protocol
from adaptive_replay.selection import decode_candidate

ROOT = Path(__file__).parents[1] / "evidence/reversal-search-2026-10-07"


def read(name):
    return json.loads((ROOT / name).read_bytes())


def clock(date):
    return int(datetime.fromisoformat(date).replace(tzinfo=UTC).timestamp() * 1000)


def day(timestamp):
    return datetime.fromtimestamp(timestamp / 1000, UTC).date().isoformat()


def close(actual, expected):
    assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-8)


@cache
def audit_tape():
    """Stream the complete denominator; retain candidates/counters, not 63k rows."""
    protocol, result = read("protocol.json"), read("result.json")
    counters, candidates, arrivals, identities = {}, {}, {}, set()
    tape_sha = hashlib.sha256()
    total = 0
    with gzip.open(ROOT / "decisions.jsonl.gz", "rb") as stream:
        for wid, start, end, _ in WINDOWS:
            start_ms, end_ms = clock(start), clock(end)
            days = {day(ts): 0 for ts in range(start_ms, end_ms, 86_400_000)}
            for symbol in protocol["universe"]:
                for arm in ARMS:
                    counter = {
                        "raw": 0,
                        "days": Counter(days),
                        "consumed": 0,
                        **{field: Counter() for field in ("state", "reason", "transition", "defense")},
                        "costs": {
                            cost: {
                                "ref": Counter(),
                                "arrival": Counter(),
                                "days": Counter(days),
                                "feasible": 0,
                            }
                            for cost in ("base", "stress")
                        },
                    }
                    counters[wid, symbol, arm] = counter
                    for cut in range(start_ms, end_ms, 300_000):
                        line = next(stream)
                        row = json.loads(line)
                        assert (canonical(row) + "\n").encode() == line
                        tape_sha.update(line)
                        total += 1
                        assert (row["window"], row["symbol"], row["arm"], row["cut_ms"]) == (
                            wid,
                            symbol,
                            arm,
                            cut,
                        )
                        technical = row["technical"]
                        raw = technical["candidate" if arm == STRATEGY_ID else "intent"]
                        if arm == STRATEGY_ID:
                            assert technical["cut_ms"] == cut and technical["symbol"] == symbol
                            for field in ("state", "reason", "transition", "defense"):
                                counter[field][technical[field]] += 1
                            counter["consumed"] += technical["consumed"] and technical["transition"] not in {
                                "WAIT_RESET_HOLD",
                                "WAIT_RESET_TO_IDLE_RESET_ONLY",
                            }
                        if raw is None:
                            assert row["geometries"] == {}
                            continue
                        candidate = decode_candidate(raw, arm)
                        assert candidate.intent_id not in identities
                        identities.add(candidate.intent_id)
                        assert candidate.symbol == symbol and candidate.entry_eligible_ts_ms == cut
                        assert candidate.decision_ts_ms == cut - 1
                        candidates[wid, arm, candidate.intent_id] = candidate
                        counter["raw"] += 1
                        counter["days"][day(cut)] += 1
                        if arm == STRATEGY_ID:
                            assert technical["consumed"] and technical["state"] == "WAIT_RESET"
                            assert dict(candidate.metadata)["policy_sha256"] == POLICY_SHA256
                            assert candidate.exit_plan.trailing_distance is None
                        assert set(row["geometries"]) == {"base", "stress"}
                        for cost, geometry in row["geometries"].items():
                            ref, arrival = geometry["reference"], geometry["first_arrival"]
                            costs = counter["costs"][cost]
                            costs["ref"][ref["reason"]] += 1
                            costs["feasible"] += ref["reference_feasible"]
                            reason = (
                                "FIRST_QUOTE_UNAVAILABLE_OR_EXPIRED" if arrival is None else arrival["reason"]
                            )
                            costs["arrival"][reason] += 1
                            if arrival is None:
                                continue
                            assert arrival["intent_id"] == candidate.intent_id
                            assert arrival["completion_ms"] == candidate.decision_ts_ms + 100
                            assert arrival["quote_ms"] == cut + 60_000
                            assert arrival["original_stop_price"] == candidate.exit_plan.stop_price
                            assert arrival["original_target_price"] == candidate.exit_plan.target_price
                            assert arrival["trading_admitted"] is arrival["observed_bbo_or_fill"] is False
                            assert arrival["source_authenticity_admitted"] is False
                            assert arrival["geometry_feasible"] == (reason == "GEOMETRY_FEASIBLE_ONLY")
                            if arrival["geometry_feasible"]:
                                assert 10 <= arrival["stop_distance_bps"] <= 300
                                assert arrival["net_reward_to_risk"] >= 1.25
                                assert (
                                    arrival["planning_round_trip_bps"] <= 0.5 * arrival["stop_distance_bps"]
                                )
                                costs["days"][day(cut)] += 1
                                arrivals[wid, arm, cost, candidate.intent_id] = arrival
        assert next(stream, None) is None
    assert total == result["complete_scheduled_slots"] == 63_360
    assert tape_sha.hexdigest() == result["decisions_canonical_jsonl_sha256"]
    return counters, candidates, arrivals


def test_all_original_pipeline_and_log_bytes_are_bound_across_platforms():
    receipt = read("checksums.json")
    assert receipt["scope"] == "SHA256_OF_ORIGINAL_PIPELINE_AND_LOG_BYTES_NOT_SOURCE_AUTHENTICITY"
    assert receipt["source_seal_commit"] == "f6ddf7ba7366bb80a0711e955d2ce8eb052a5081"
    assert receipt["original_file_count"] == len(receipt["files"]) == 19
    assert {p.name for p in ROOT.iterdir()} == {"checksums.json", *receipt["files"]}
    for name, sha in receipt["files"].items():
        assert Path(name).name == name and "\\" not in name and ".." not in Path(name).parts
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha
    assert receipt["files"]["decisions.jsonl.gz"] == read("result.json")["decisions_gzip_sha256"]
    assert (ROOT / "stderr.log").read_bytes() == b""
    assert (ROOT / "stdout.log").read_text().count("phase=window_complete") == 6
    supervision = receipt["external_supervision"]
    assert supervision["exit_code"] == 0 and supervision["retry_performed"] is False
    assert 0 < supervision["elapsed_ms"] == 207808 < supervision["hard_wall_ms"] == 600000


def test_fixed_protocol_source_seal_clocks_and_complete_inputs_remain_bound():
    protocol, result, before, after = (
        read(name) for name in ("protocol.json", "result.json", "before.json", "after.json")
    )
    assert protocol == fixed_search_protocol()
    assert digest(protocol) == result["protocol_sha256"] == before["protocol_sha256"]
    assert before["sources"] == after["sources"]
    assert result["source_receipt_unchanged"] and after["source_receipt_unchanged"]
    assert {"failed_reversal.py", "failed_reversal_entry.py", "reversal_search.py"} <= (
        before["sources"]["replay_modules_sha256"].keys()
    )
    assert before["native_control_identity"]["config"] == protocol["control"]["config"]
    assert before["actual_started_utc"] == result["actual_started_utc"]
    started, finished = (
        datetime.fromisoformat(result[k]) for k in ("actual_started_utc", "actual_finished_utc")
    )
    supervision = read("checksums.json")["external_supervision"]
    assert (
        datetime.fromisoformat(supervision["started_utc"])
        <= started
        < datetime.fromisoformat(after["actual_finished_utc"])
        <= finished
        <= datetime.fromisoformat(supervision["finished_utc"])
    )
    assert 0 < result["elapsed_seconds"] < 600
    for wid, start, end, _ in WINDOWS:
        receipt = read(f"{wid}-inputs.json")
        expected_rows = ((clock(end) - clock(start)) // 86_400_000 + 4) * 1440
        assert expected_rows in {10080, 12960}
        evidence = receipt["evidence"]
        assert evidence["bar_end_ms"] - evidence["bar_start_ms"] == expected_rows * 60_000
        assert evidence["funding_start_ms"] == evidence["bar_start_ms"]
        assert evidence["funding_end_ms"] == evidence["bar_end_ms"]
        assert evidence["bar_field_profile"] == "full_kline"
        for symbol, market in receipt["market"].items():
            assert market["gaps"] == 0 and market["bars"] == expected_rows
            assert market["funding"] == expected_rows // 480
            assert market["bar_rows_sha256"] == evidence["bars"][symbol]["normalized_rows_sha256"]
            assert market["funding_rows_sha256"] == evidence["funding"][symbol]["normalized_rows_sha256"]


def test_streamed_complete_roster_candidates_and_all_refusals_reconcile():
    counters, _, _ = audit_tape()
    result = read("result.json")
    totals = {arm: Counter() for arm in ARMS}
    for (wid, symbol, arm), counter in counters.items():
        report = result["windows"][wid][symbol][arm]
        window = next(w for w in WINDOWS if w[0] == wid)
        assert counter["raw"] == report["raw_candidates"]
        assert dict(counter["days"]) == report["candidates_each_utc_day"]
        assert report["scheduled_slots"] == (clock(window[2]) - clock(window[1])) // 300_000
        assert report["no_candidate_slots"] + counter["raw"] == report["scheduled_slots"]
        totals[arm]["raw"] += counter["raw"]
        if arm == STRATEGY_ID:
            for field in ("state", "reason", "transition", "defense"):
                assert dict(counter[field]) == report[f"{field}_counts"]
            assert counter["consumed"] == report["consumed_event_slots"]
        for cost, costs in counter["costs"].items():
            summary = report["scenarios"][cost]
            assert dict(costs["ref"]) == summary["reference_geometry_reasons"]
            assert sum(costs["ref"].values()) == counter["raw"]
            assert dict(costs["arrival"]) == summary["first_arrival_reasons"]
            assert sum(costs["arrival"].values()) == counter["raw"]
            assert costs["feasible"] == summary["reference_geometry_feasible"]
            assert costs["arrival"]["GEOMETRY_FEASIBLE_ONLY"] == summary["first_arrival_geometry_feasible"]
            assert dict(costs["days"]) == summary["first_arrival_feasible_each_utc_day"]
            totals[arm][f"ref_{cost}"] += costs["feasible"]
            totals[arm][f"arrival_{cost}"] += costs["arrival"]["GEOMETRY_FEASIBLE_ONLY"]
    assert totals == {
        STRATEGY_ID: {
            "raw": 799,
            "ref_base": 593,
            "ref_stress": 429,
            "arrival_base": 504,
            "arrival_stress": 388,
        },
        ARMS[1]: {"raw": 1057, "ref_base": 264, "ref_stress": 52, "arrival_base": 309, "arrival_stress": 172},
    }


def test_all_24_accounts_independently_reconcile_without_forced_trades_or_risk_rounding():
    _, candidates, arrivals = audit_tape()
    result = read("result.json")
    totals, overrun, accounts = Counter(), Counter(), 0
    for wid, _, _, _ in WINDOWS:
        for arm, costs in read(f"{wid}-ledgers.json").items():
            for cost, ledger in costs.items():
                accounts += 1
                report, trades, events = (ledger[key] for key in ("report", "trades", "events"))
                assert report == result["conditional_ohlc_trading_net_reference"][wid][arm][cost]
                entries = {e["intent_id"]: e for e in events if e["kind"] == "ENTRY"}
                rejected = Counter(e["reason"] for e in events if e["kind"] == "REJECT")
                assert len(entries) == report["closed_trades"] == len(trades)
                assert report["forced_settlements"] == 0 and report["terminal_unresolved_positions"] == []
                assert dict(rejected) == report["admission_rejections"]
                assert len(entries) + sum(rejected.values()) == report["preportfolio_first_arrival_feasible"]
                assert (
                    report["raw_candidates"]
                    == report["preportfolio_refused"] + report["preportfolio_first_arrival_feasible"]
                )
                daily = Counter({day: 0 for day in report["entries_each_utc_day"]})
                for intent_id, entry in entries.items():
                    candidate = candidates[wid, arm, intent_id]
                    arrival = arrivals[wid, arm, cost, intent_id]
                    assert entry["timestamp_ms"] == arrival["quote_ms"] <= candidate.entry_expires_ts_ms
                    close(entry["price"], arrival["modeled_entry_price"])
                    assert entry["reserved_risk_usd"] <= 0.0025 * entry["post_entry_equity_usd"] + 1e-8
                    assert entry["quantity"] * entry["price"] <= 0.25 * entry["post_entry_equity_usd"] + 1e-8
                    daily[day(entry["timestamp_ms"])] += 1
                assert dict(daily) == report["entries_each_utc_day"]
                assert report["zero_entry_days"] == sum(n == 0 for n in daily.values())
                assert dict(Counter(t["reason"] for t in trades)) == report["natural_exit_counts"]
                for trade in trades:
                    candidate = candidates[wid, arm, trade["intent_id"]]
                    assert trade["entry_ms"] == entries[trade["intent_id"]]["timestamp_ms"]
                    assert trade["holding_ms"] == trade["exit_ms"] - trade["entry_ms"]
                    assert 0 <= trade["holding_ms"] <= candidate.exit_plan.max_holding_ms
                    assert trade["reason"] in {"SL", "TP", "TIMEOUT", "TRAILING_STOP"}
                    direction = 1 if trade["side"] == "LONG" else -1
                    close(
                        trade["gross_pnl_usd"],
                        direction * trade["quantity"] * (trade["exit_price"] - trade["entry_price"]),
                    )
                    close(
                        trade["net_pnl_usd"],
                        trade["gross_pnl_usd"]
                        - trade["entry_fee_usd"]
                        - trade["exit_fee_usd"]
                        - trade["signed_funding_cost_usd"],
                    )
                    for phase in ("entry", "exit"):
                        close(
                            trade[f"{phase}_fee_usd"],
                            trade["quantity"]
                            * trade[f"{phase}_price"]
                            * report["cost_scenario"]["fee_bps_per_side"]
                            / 10_000,
                        )
                net = math.fsum(t["net_pnl_usd"] for t in trades)
                close(report["closed_trade_net_usd"], net)
                close(report["final_equity_usd"], 10_000 + net)
                close(report["net_return_pct"], net / 100)
                close(report["ledger_reconciliation_error_usd"], 0)
                for field, target in (
                    ("entry_fee_usd", "total_entry_fees_usd"),
                    ("exit_fee_usd", "total_exit_fees_usd"),
                    ("signed_funding_cost_usd", "signed_funding_cost_usd"),
                ):
                    close(report[target], math.fsum(t[field] for t in trades))
                close(
                    report["signed_funding_cost_usd"],
                    math.fsum(e["signed_cost_usd"] for e in events if e["kind"] == "FUNDING"),
                )
                profits = math.fsum(max(t["net_pnl_usd"], 0) for t in trades)
                losses = math.fsum(max(-t["net_pnl_usd"], 0) for t in trades)
                if losses:
                    close(report["profit_factor"], profits / losses)
                    assert report["profit_factor_status"] == "FINITE"
                else:
                    assert not trades and report["profit_factor"] is None
                    assert report["profit_factor_status"] == "NO_TRADES"
                assert report["realized_loss_over_reservation_count"] == sum(
                    t["realized_loss_exceeds_reservation"] for t in trades
                )
                assert report["risk_ceiling_mark_overrun"] == (
                    report["max_observed_mark_open_risk_fraction"] > 0.01 + 1e-9
                )
                assert report["gross_ceiling_mark_overrun"] == (
                    report["max_observed_mark_gross_leverage"] > 1 + 1e-9
                )
                assert report["adverse_envelope_bound_pct"] + 1e-8 >= report["closed_minute_mtm_drawdown_pct"]
                assert report["gross_ceiling_mark_overrun"] is False
                overrun[arm, cost] += report["risk_ceiling_mark_overrun"]
                totals[arm, cost] += len(trades)
    assert accounts == 24
    assert totals == {
        (STRATEGY_ID, "base"): 415,
        (STRATEGY_ID, "stress"): 318,
        (ARMS[1], "base"): 221,
        (ARMS[1], "stress"): 128,
    }
    assert overrun == {
        (STRATEGY_ID, "base"): 4,
        (STRATEGY_ID, "stress"): 4,
        (ARMS[1], "base"): 2,
        (ARMS[1], "stress"): 1,
    }


def test_conditional_price_results_do_not_grant_model_alpha_or_trading_authority():
    protocol, result = read("protocol.json"), read("result.json")
    assert result["state"] == "OFFLINE_PRICE_ONLY_DIAGNOSTIC_COMPLETED_NOT_QUALIFICATION"
    assert protocol["natural_frequency_quota"] is None and protocol["parameter_search"] is False
    assert result["complete_system_economic_result"] is None
    assert result["provider_calls"] == result["provider_cost_usd"] == 0
    for key in (
        "required_news_macro_ready",
        "source_authenticity_admitted",
        "model_execution_admitted",
        "blind_campaign_credit",
    ):
        assert result[key] is False
    assert protocol["news_macro_context"] == "UNAVAILABLE_NOT_SYNTHESIZED"
    assert protocol["fresh_owner_confirmation_for_model_test"] is False
    assert result["readiness"]["STRATEGY_POLICY"] == "REJECT_ALL"
    assert all(v is False for k, v in result["readiness"].items() if k != "STRATEGY_POLICY")
    for arms in result["conditional_ohlc_trading_net_reference"].values():
        for costs in arms.values():
            for report in costs.values():
                assert report["admission_policy"] == "COMMON_COST_RISK_V1"
                assert report["entry_mode"] == "STRICT_MINUTE_OPEN"
                assert report["model_calls"] == 0 and report["model_cost_usd"] is None
                assert report["model_cost_status"] == "NOT_CALLED_NOT_FREE_SERVICE"
                assert report["market_feed_cost_usd"] is None
                assert report["strategy_qualified"] is report["execution_qualification"] is False
                assert report["complete_all_in_net_economics"] is report["complete_system_economics"] is False
