"""Selection diagnostics cannot become fills, quiet outcomes or trading authority."""

import hashlib
import json
import time
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from kairos_backtest.cost_risk import RiskLimits, size_and_admit
from kairos_core.enums import Side
from kairos_strategy.models import ExitPlan, SleeveIntent

from adaptive_replay import compare, selection
from adaptive_replay.engine import CostScenario

from .test_engine import START, inputs_fixture

ROOT = Path(__file__).parents[1]
BASE = CostScenario("base", 4.5, 2, 1, 2, 2, 3)
STRESS = CostScenario("stress", 9, 4, 2, 2, 2, 3)


def native(family="range_mean_reversion_v1", side=Side.LONG, atr=1.0):
    sign = 1 if side is Side.LONG else -1
    ttl = 60_000 if family == compare.STRATEGY_ID else 300_000
    return SleeveIntent(
        family,
        "BTCUSDT",
        side,
        START - 1,
        START,
        START - 1 + ttl,
        100,
        0.5,
        1.25 * atr / 100 * 10_000,
        ExitPlan(100 - sign * atr, 100 + sign * 1.25 * atr, 3_600_000),
    )


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
@pytest.mark.parametrize("atr", [0.5, 1.0, 2.0, 3.0])
@pytest.mark.parametrize("scenario", [BASE, STRESS])
def test_native_default_range_reference_bound_cannot_clear_positive_costs(side, atr, scenario):
    # The native band caps gross R/R at 1.25. Even this best-edge reference
    # fails the unchanged net >=1.25 hurdle, in both directions.
    candidate = native(side=side, atr=atr)
    geometry = selection.reference_geometry(candidate, scenario)
    assert geometry["gross_reward_to_risk"] == 1.25
    assert geometry["net_reward_to_risk"] < 1.25
    assert geometry["reference_feasible"] is False
    assert "quantity" not in geometry


def test_reference_rejection_does_not_prove_favorable_later_fill_impossible():
    candidate = native()
    assert selection.reference_geometry(candidate, BASE)["reference_feasible"] is False
    favorable = size_and_admit(
        side=candidate.side,
        entry_price=99.75,
        stop_price=candidate.exit_plan.stop_price,
        target_price=candidate.exit_plan.target_price,
        equity_usd=10_000,
        costs=BASE.costs,
        limits=RiskLimits(maximum_stop_distance_bps=300),
    )
    assert favorable.accepted
    assert favorable.net_reward_to_risk > 1.25
    assert candidate.reference_price == 100  # Original intent is not rewritten.


def test_reference_cost_headroom_is_not_removed_when_other_hurdles_pass():
    candidate = native()
    candidate = replace(
        candidate,
        exit_plan=ExitPlan(99.7, 102, 3_600_000),
        gross_reward_bps=200,
    )
    geometry = selection.reference_geometry(candidate, BASE)
    assert geometry["net_reward_to_risk"] > 1.25
    assert geometry["reference_feasible"] is False
    assert geometry["reason"] == "insufficient_cost_headroom"


def fixture_tape(tmp_path, family="range_mean_reversion_v1"):
    inputs = inputs_fixture()
    inputs.evidence = {"kind": "synthetic_not_market_evidence"}
    inputs.end_ms = START + 300_000
    path = tmp_path / "decisions.jsonl"
    counts = compare.write_tape(
        path, {START: [native(family=family)]}, inputs, complete_source_outcomes=family == compare.STRATEGY_ID
    )
    return path, counts, compare.digest(inputs.evidence)


def audit(path, counts, input_sha, family="range_mean_reversion_v1", deadline=None):
    return selection.audit_tape(
        path,
        family,
        counts,
        START,
        START + 300_000,
        input_sha,
        [BASE, STRESS],
        deadline or time.monotonic() + 10,
    )


@pytest.mark.parametrize("family", ["range_mean_reversion_v1", compare.STRATEGY_ID])
def test_tape_audit_preserves_native_lifetime_and_unknown_source_availability(tmp_path, family):
    path, counts, input_sha = fixture_tape(tmp_path, family)
    result = audit(path, counts, input_sha, family)
    assert result["raw_candidates"] == 1
    assert result["scheduled_slots"] == 5
    assert result["no_strict_minute_quote_at_assumed_100ms_completion"] == (family == compare.STRATEGY_ID)
    assert result["source_ready_slots"] == (5 if family == compare.STRATEGY_ID else None)
    assert result["source_unavailable_slots"] == (0 if family == compare.STRATEGY_ID else None)
    assert sum(result["candidate_counts_each_utc_day"].values()) == 1
    assert result["reference_scenarios"]["base"]["reference_feasible_candidates"] == 0


def test_candidate_decode_rejects_identity_change_without_recomputing_it():
    raw = json.loads(compare.canonical(asdict(native())))
    assert selection.decode_candidate(raw, "range_mean_reversion_v1") == native()
    raw["signal_strength"] = 0.7
    with pytest.raises(ValueError, match="identity"):
        selection.decode_candidate(raw, "range_mean_reversion_v1")


@pytest.mark.parametrize("change", ["input", "order", "unknown_quiet", "truncate", "noncanonical", "ttl"])
def test_tape_binding_and_native_semantics_cannot_be_silently_reclassified(tmp_path, change):
    path, counts, input_sha = fixture_tape(tmp_path)
    rows = [json.loads(row) for row in path.read_bytes().splitlines()]
    if change == "input":
        rows[0]["common_window_evidence_sha256"] = "0" * 64
    elif change == "order":
        rows[0], rows[1] = rows[1], rows[0]
    elif change == "unknown_quiet":
        rows[1]["status"] = "UNAVAILABLE"
    elif change == "truncate":
        rows.pop()
    elif change == "ttl":
        changed = replace(native(), entry_expires_ts_ms=START + 600_000)
        rows[0]["intent"] = asdict(changed)
    encoded = b"".join(compare.canonical(row) + b"\n" for row in rows)
    if change == "noncanonical":
        encoded = encoded.replace(b'"clock_authority":', b'"clock_authority": ', 1)
    path.write_bytes(encoded)
    # Even a recomputed hash cannot hide wrong semantics. Truncation cannot
    # become a smaller denominator; the published schedule remains fixed.
    counts["tape_sha256"] = hashlib.sha256(encoded).hexdigest()
    with pytest.raises(ValueError):
        audit(path, counts, input_sha)


def test_tape_hash_and_counts_and_resource_deadline_are_required(tmp_path):
    path, counts, input_sha = fixture_tape(tmp_path)
    with pytest.raises(TimeoutError, match="deadline"):
        audit(path, counts, input_sha, deadline=time.monotonic() - 1)
    for field, value in (("raw_candidates", 2), ("quiet_slots", 0), ("tape_sha256", "0" * 64)):
        altered = {**counts, field: value}
        with pytest.raises(ValueError, match="hash or complete counts"):
            audit(path, altered, input_sha)


def test_only_exact_published_result_can_be_inspected(tmp_path):
    (tmp_path / "result.json").write_text("{}")
    with pytest.raises(ValueError, match="exact published"):
        selection.inspect_comparison(tmp_path, ROOT / "comparison-plan.json")


def test_retained_read_only_audit_matches_published_candidate_and_tape_denominators():
    result = json.loads((ROOT / "evidence/selection-2026-10-06/geometry.json").read_bytes())
    published = json.loads((ROOT / "evidence/comparison-2026-10-06/result.json").read_bytes())
    assert result["comparison_result_sha256"] == selection.COMPARISON_SHA
    assert result["authority"] == "REFERENCE_GEOMETRY_ONLY_NOT_EXPECTANCY_OR_ACTUAL_FILL"
    assert result["new_price_or_pnl_replay"] is False
    assert result["strategy_selected_for_live"] is None
    assert result["blind_results_read"] is False
    assert result["paid_calls"] == result["blind_campaign_days_added"] == 0
    assert result["readiness"] == published["readiness"]
    assert result["risk_limits"] == asdict(RiskLimits(maximum_stop_distance_bps=300))
    assert result["maximum_cost_stop_fraction"] == 0.5
    totals = {family: [0, 0, 0, 0] for family in selection.AUDITED_ARMS}
    for window, prior in zip(result["windows"], published["windows"], strict=True):
        assert window["window"] == prior["window"]
        for family, report in window["arms"].items():
            counts = next(arm["counts"] for arm in prior["arms"] if arm["arm_id"] == family)
            for field in ("raw_candidates", "scheduled_slots", "tape_sha256", "source_ready_slots"):
                assert report[field] == counts[field]
            n = report["raw_candidates"]
            assert sum(report["candidate_counts_each_utc_day"].values()) == n
            assert sum(report["candidate_patterns"].values()) == n
            for scenario in report["reference_scenarios"].values():
                assert sum(scenario["reference_reasons"].values()) == n
                assert scenario["reference_feasible_candidates"] == scenario["reference_reasons"].get(
                    "accepted", 0
                )
            totals[family] = [
                a + b
                for a, b in zip(
                    totals[family],
                    [
                        n,
                        report["reference_scenarios"]["base"]["reference_feasible_candidates"],
                        report["reference_scenarios"]["stress"]["reference_feasible_candidates"],
                        report["no_strict_minute_quote_at_assumed_100ms_completion"],
                    ],
                    strict=True,
                )
            ]
    assert totals == {
        "trend_breakout_v1": [583, 102, 10, 0],
        "range_mean_reversion_v1": [140, 0, 0, 0],
        compare.STRATEGY_ID: [12, 12, 11, 12],
    }
