"""Completed four-year reference evidence cannot become trading qualification."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path

from adaptive_replay import calendar_pair, price_calendar

ROOT = Path(__file__).parents[1] / "evidence/price-calendar-2026-10-07"


def read(name: str) -> dict:
    return json.loads(gzip.decompress((ROOT / (name + ".gz")).read_bytes()))


def test_all_fifty_four_original_artifacts_are_losslessly_byte_bound() -> None:
    index = json.loads((ROOT / "checksums.json").read_bytes())
    assert index["source_commit"] == "28891bbfa4bc17436e248508c84ae47e6cb67a42"
    assert index["economic_attempts"] == 1 and index["old_attempt_rewritten"] is False
    records = index["files"]
    assert len(records) == len({r["file"] for r in records}) == 54
    assert {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()} == {
        "checksums.json",
        *(r["file"] for r in records),
    }
    for row in records:
        assert "\\" not in row["file"] and ".." not in Path(row["file"]).parts
        compressed = (ROOT / row["file"]).read_bytes()
        payload = gzip.decompress(compressed)
        assert hashlib.sha256(compressed).hexdigest() == row["compressed_sha256"]
        assert hashlib.sha256(payload).hexdigest() == row["original_sha256"]
        assert len(compressed) == row["compressed_bytes"] and len(payload) == row["original_bytes"]
    assert hashlib.sha256(gzip.decompress((ROOT / "result.json.gz").read_bytes())).hexdigest() == (
        "5d007bba857c91a6321030da812367403f873062872691e9784b9eaf532ee403"
    )


def test_full_run_source_and_native_accounts_remain_scoped_and_complete() -> None:
    result, before, plan = read("result.json"), read("before.json"), read("sealed-price-reference-plan.json")
    assert result["state"] == "COMPLETED" and result["elapsed_seconds"] == 654.25
    assert before["sources"] == result["sources"]
    assert result["sources"]["source_acceptance_sha256"] == price_calendar.ACCEPTANCE_SHA
    assert len(result["sources"]["price_consumer_transitive_modules_sha256"]) == 8
    assert plan["field_profile"] == "PRICE_ONLY" and plan["replaced_rejected_rows"] == 0
    assert plan["no_second_economic_attempt"] is True
    assert result["qualified_winner"] is result["strategy_selected_for_live"] is None
    assert result["compound_return_across_windows"] is None
    assert result["blind_campaign_days_added"] == result["paid_calls"] == 0
    assert result["blind_results_read"] is False
    assert result["readiness"]["STRATEGY_POLICY"] == "REJECT_ALL"
    assert all(v is False for k, v in result["readiness"].items() if k != "STRATEGY_POLICY")
    cells = []
    for window in result["windows"]:
        assert {arm["arm_id"] for arm in window["arms"]} == set(calendar_pair.pair.ARMS)
        for arm in window["arms"]:
            assert {c["cost_scenario"]["id"] for c in arm["economic_results"]} == {"base", "stress"}
            for cell in arm["economic_results"]:
                assert cell["forced_settlements"] == 0 and cell["terminal_unresolved_positions"] == []
                assert cell["model_calls"] == 0 and cell["model_cost_usd"] is None
                assert cell["market_feed_cost_usd"] is None and cell["complete_all_in_net_economics"] is False
                assert cell["admission_policy"] == "COMMON_COST_RISK_V1"
                assert cell["entry_mode"] == "STRICT_MINUTE_OPEN"
                cells.append(cell)
    assert len(cells) == 16


def test_original_stress_rule_retains_no_winner_despite_higher_aligned_returns() -> None:
    result = read("result.json")
    decision = calendar_pair.select_reference(result["windows"])
    assert decision == result["reference_decision"]
    assert decision["state"] == "NO_ECONOMIC_REFERENCE_WINNER"
    assert decision["economic_reference_nominee"] is None
    assert decision["stress_closes_each_arm"] == {
        "right_tail_trend_v1": 1411,
        "regime_aligned_right_tail_v1": 976,
    }
    primary = []
    for window in result["windows"]:
        cells = {
            arm["arm_id"]: next(c for c in arm["economic_results"] if c["cost_scenario"]["id"] == "stress")
            for arm in window["arms"]
        }
        base, aligned = (cells[arm] for arm in calendar_pair.pair.ARMS)
        assert aligned["net_return_pct"] > base["net_return_pct"]
        assert base["risk_ceiling_mark_overrun"] and aligned["risk_ceiling_mark_overrun"]
        if window["window"]["id"] == "calendar_2023":
            assert aligned["closed_minute_mtm_drawdown_pct"] > base["closed_minute_mtm_drawdown_pct"]
            assert aligned["net_return_pct"] < 0
        primary.append(cells)
    for arm, value in (
        (calendar_pair.pair.ARMS[0], -0.3851246923689402),
        (calendar_pair.pair.ARMS[1], 3.5945834537984664),
    ):
        assert math.isclose(math.fsum(c[arm]["net_return_pct"] for c in primary) / 4, value, abs_tol=1e-10)


def test_independent_arithmetic_receipt_is_bound_to_actual_result_and_calculator() -> None:
    audit = read("independent-ledger-audit.json")
    calculator = gzip.decompress((ROOT / "independent-calculator.ps1.gz").read_bytes())
    assert audit["state"] == "PASSED_SCOPED_ARITHMETIC" and len(audit["cells"]) == 16
    assert audit["result_sha256"] == "5d007bba857c91a6321030da812367403f873062872691e9784b9eaf532ee403"
    assert audit["calculator_sha256"] == hashlib.sha256(calculator).hexdigest()
    assert audit["complete_venue_or_alpha_validation"] is False
    for cell in audit["cells"]:
        root = f"{cell['year']}/{cell['arm']}"
        payload = gzip.decompress((ROOT / f"{root}/{cell['cost']}-ledger.json.gz").read_bytes())
        assert cell["ledger_sha256"] == hashlib.sha256(payload).hexdigest()
        ledger = json.loads(payload)
        assert cell["closed"] == len(ledger["trades"])
        assert all(t["reason"] in {"SL", "TP", "TIMEOUT"} for t in ledger["trades"])
        assert all(
            t["holding_ms"] <= 72 * 3600000 and t["entry_ms"] % 86400000 == 3660000 for t in ledger["trades"]
        )
