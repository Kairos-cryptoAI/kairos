"""Read-only geometry audit of already published native development tapes.

No generators, price replay, parameter search, model calls or trading authority.
Reference feasibility is not a fill, expected value or a strategy qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kairos_backtest import cost_risk
from kairos_backtest.cost_risk import RiskLimits, size_and_admit
from kairos_core.enums import Side
from kairos_strategy.models import ExitPlan, SleeveIntent

from .baselines import baseline_identities
from .compare import STRATEGY_ID, load_comparison_plan
from .engine import CostScenario, entry_time
from .inputs import UNIVERSE
from .runner import canonical, digest, source_receipt

COMPARISON_SHA = "895b7aee5d8741cd0869cf2fad5eaa9a311f85edabe5ff4a8b800c4c9435a56c"
AUDITED_ARMS = ("trend_breakout_v1", "range_mean_reversion_v1", STRATEGY_ID)
MAX_SECONDS = 60


def decode_candidate(raw: dict[str, Any], family: str) -> SleeveIntent:
    values = dict(raw)
    recorded_id = values.pop("intent_id")
    values["side"] = Side(values["side"])
    values["exit_plan"] = ExitPlan(**values["exit_plan"])
    values["metadata"] = tuple(tuple(pair) for pair in values["metadata"])
    candidate = SleeveIntent(**values)
    if candidate.intent_id != recorded_id or candidate.sleeve_id != family:
        raise ValueError("published native candidate identity changed")
    return candidate


def reference_geometry(intent: SleeveIntent, scenario: CostScenario) -> dict[str, Any]:
    """Inspect the fixed reference price, never assume an actual fill there."""
    stop_distance = abs(intent.reference_price - intent.exit_plan.stop_price)
    decision = size_and_admit(
        side=intent.side,
        entry_price=intent.reference_price,
        stop_price=intent.exit_plan.stop_price,
        target_price=intent.exit_plan.target_price,
        equity_usd=10_000,
        costs=scenario.costs,
        limits=RiskLimits(maximum_stop_distance_bps=300),
    )
    headroom = scenario.costs.estimated_round_trip_bps <= 0.5 * decision.stop_distance_bps
    return {
        "gross_reward_to_risk": abs(intent.exit_plan.target_price - intent.reference_price) / stop_distance,
        "net_reward_to_risk": decision.net_reward_to_risk,
        "reference_feasible": decision.accepted and headroom,
        "reason": str(decision.reason) if headroom else "insufficient_cost_headroom",
    }


def audit_tape(
    path: Path,
    family: str,
    counts: dict[str, Any],
    start_ms: int,
    end_ms: int,
    input_sha: str,
    scenarios: list[CostScenario],
    deadline: float,
) -> dict[str, Any]:
    """Recheck canonical bytes, full slot order, intent IDs and native clocks."""
    if family not in AUDITED_ARMS or not scenarios or len({s.id for s in scenarios}) != len(scenarios):
        raise ValueError("known family and distinct cost scenarios required")
    if end_ms <= start_ms or start_ms % 300_000 or end_ms % 300_000:
        raise ValueError("complete five-minute schedule required")
    expected = [(s, ts) for s in UNIVERSE for ts in range(start_ms, end_ms, 300_000)]
    if len(expected) != counts["scheduled_slots"] or path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("bounded published tape schedule required")
    fingerprint = hashlib.sha256()
    ids: set[str] = set()
    per_day = {datetime.fromtimestamp(ts / 1000, UTC).date().isoformat(): 0 for _, ts in expected}
    gross: list[float] = []
    nets: dict[str, list[float]] = {s.id: [] for s in scenarios}
    reasons: dict[str, Counter[str]] = {s.id: Counter() for s in scenarios}
    patterns: Counter[str] = Counter()
    no_strict_quote = position = quiet = 0
    with path.open("rb") as stream:
        for encoded in stream:
            if time.monotonic() >= deadline:
                raise TimeoutError("bounded read-only tape audit deadline reached")
            if position >= len(expected) or len(encoded) > 131_072:
                raise ValueError("additional or oversized tape slot")
            item = json.loads(encoded)
            if canonical(item) + b"\n" != encoded:
                raise ValueError("original canonical tape bytes required")
            symbol, ts = expected[position]
            position += 1
            fingerprint.update(encoded)
            if (
                item["symbol"] != symbol
                or item["context_cut_ms"] != ts - 1
                or item["common_window_evidence_sha256"] != input_sha
                or item["clock_authority"] != "HISTORICAL_EVENT_TIME_NOT_LIVE_RECEIPT"
            ):
                raise ValueError("published slot order, input or clock binding changed")
            raw = item["intent"]
            if raw is None:
                expected_status = "NO_INTENT" if family == STRATEGY_ID else "NO_CANDIDATE_REPORTED"
                if item["status"] != expected_status:
                    raise ValueError("unknown outcome must not become quiet")
                quiet += 1
                continue
            intent = decode_candidate(raw, family)
            native_ttl = 60_000 if family == STRATEGY_ID else 300_000
            if (
                item["status"] != "CANDIDATE"
                or intent.symbol != symbol
                or intent.decision_ts_ms != ts - 1
                or intent.entry_eligible_ts_ms != ts
                or intent.entry_expires_ts_ms != ts - 1 + native_ttl
                or intent.intent_id in ids
            ):
                raise ValueError("native candidate, lifetime or duplicate identity changed")
            ids.add(intent.intent_id)
            patterns[dict(intent.metadata).get("pattern", "NOT_EXPOSED_BY_NATIVE_CANDIDATE")] += 1
            per_day[datetime.fromtimestamp(ts / 1000, UTC).date().isoformat()] += 1
            no_strict_quote += entry_time(intent, intent.decision_ts_ms + 100, "STRICT_MINUTE_OPEN") is None
            for scenario in scenarios:
                geometry = reference_geometry(intent, scenario)
                if scenario is scenarios[0]:
                    gross.append(geometry["gross_reward_to_risk"])
                nets[scenario.id].append(geometry["net_reward_to_risk"])
                reasons[scenario.id][geometry["reason"]] += 1
    if (
        position != len(expected)
        or len(ids) != counts["raw_candidates"]
        or quiet != counts["quiet_slots"]
        or fingerprint.hexdigest() != counts["tape_sha256"]
    ):
        raise ValueError("published tape hash or complete counts changed")
    return {
        "scheduled_slots": position,
        "raw_candidates": len(ids),
        "candidate_counts_each_utc_day": per_day,
        "candidate_patterns": dict(sorted(patterns.items())),
        "source_ready_slots": counts["source_ready_slots"],
        "source_unavailable_slots": counts["source_unavailable_slots"],
        "tape_sha256": fingerprint.hexdigest(),
        "gross_reward_to_risk_min": min(gross, default=None),
        "gross_reward_to_risk_max": max(gross, default=None),
        "no_strict_minute_quote_at_assumed_100ms_completion": no_strict_quote,
        "reference_scenarios": {
            s.id: {
                "planning_round_trip_bps": s.costs.estimated_round_trip_bps,
                "reference_feasible_candidates": reasons[s.id]["accepted"],
                "reference_reasons": dict(sorted(reasons[s.id].items())),
                "net_reward_to_risk_max": max(nets[s.id], default=None),
            }
            for s in scenarios
        },
    }


def inspect_comparison(root: Path, plan_path: Path) -> dict[str, Any]:
    encoded = (root / "result.json").read_bytes()
    if hashlib.sha256(encoded).hexdigest() != COMPARISON_SHA:
        raise ValueError("exact published completed comparison required")
    result = json.loads(encoded)
    plan, base = load_comparison_plan(plan_path)
    sources = source_receipt(base, plan_path.parent / "plan.json")
    cost_sha = hashlib.sha256(Path(cost_risk.__file__).read_bytes()).hexdigest()
    if (
        result["state"] != "COMPLETED"
        or result["readiness"] != plan["readiness"]
        or result["sources"]["comparison_plan_sha256"] != digest(plan)
        or result["sources"]["baseline_identities"] != baseline_identities()
        or result["sources"]["base_sources"]["reused_backtest_modules_sha256"]["kairos_backtest.cost_risk"]
        != cost_sha
        or [w["window"] for w in result["windows"]] != base["windows"]
    ):
        raise ValueError("unchanged source, schedule and common cost/risk evidence required")
    deadline = time.monotonic() + MAX_SECONDS
    scenarios = [CostScenario(**c) for c in base["cost_scenarios"]]
    windows = []
    for window in result["windows"]:
        specification = window["window"]
        directory = root / specification["id"]
        inputs = json.loads((directory / "inputs.json").read_bytes())
        start = int(datetime.fromisoformat(specification["start"]).replace(tzinfo=UTC).timestamp() * 1000)
        end = int(
            datetime.fromisoformat(specification["end_exclusive"]).replace(tzinfo=UTC).timestamp() * 1000
        )
        arms = {arm["arm_id"]: arm for arm in window["arms"]}
        windows.append(
            {
                "window": specification,
                "arms": {
                    family: audit_tape(
                        directory / family / "decisions.jsonl",
                        family,
                        arms[family]["counts"],
                        start,
                        end,
                        digest(inputs),
                        scenarios,
                        deadline,
                    )
                    for family in AUDITED_ARMS
                },
            }
        )
    return {
        "schema": "kairos.strategy.selection-geometry-audit.v1",
        "authority": "REFERENCE_GEOMETRY_ONLY_NOT_EXPECTANCY_OR_ACTUAL_FILL",
        "comparison_result_sha256": COMPARISON_SHA,
        "analysis_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cost_risk_source_sha256": cost_sha,
        "native_baseline_identities": result["sources"]["baseline_identities"],
        "adaptive_identity": sources["adaptive_identity"],
        "risk_limits": asdict(RiskLimits(maximum_stop_distance_bps=300)),
        "maximum_cost_stop_fraction": 0.5,
        "pipeline_latency_ms_assumed": 100,
        "windows": windows,
        "new_price_or_pnl_replay": False,
        "strategy_selected_for_live": None,
        "readiness": plan["readiness"],
        "blind_results_read": False,
        "blind_campaign_days_added": 0,
        "paid_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            inspect_comparison(args.comparison_root, args.plan), indent=2, sort_keys=True, allow_nan=False
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
