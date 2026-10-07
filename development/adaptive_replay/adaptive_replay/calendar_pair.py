"""One fixed 2022--2025 development reference comparison, never qualification."""

from __future__ import annotations

import argparse
import gc
import json
import math
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kairos_strategy.models import SleeveIntent
from kairos_strategy.registry import generate_sleeve_intents
from kairos_strategy.sleeves.regime_aligned_right_tail import RegimeAlignedRightTailConfig
from kairos_strategy.sleeves.right_tail_trend import RightTailTrendConfig

from . import right_tail as pair
from .calendar_inputs import SOL_EXCEPTION_SHA, load_calendar_window
from .engine import COMMON_COST_RISK, CostScenario, replay_tape
from .inputs import UNIVERSE, WindowInputs
from .runner import canonical, utc_now, write_json

YEARS = (2022, 2023, 2024, 2025)
WINDOWS = tuple(
    {"id": f"calendar_{year}", "start": f"{year}-01-01", "end_exclusive": f"{year + 1}-01-01"}
    for year in YEARS
)
RULE = {
    "primary_cost": "stress",
    "minimum_total_closes_each_arm": 100,
    "minimum_year_closes_each_arm": 20,
    "score": "EQUAL_YEAR_MEAN_RETURN_NOT_CAGR",
    "require_positive_nominee_score": True,
    "require_all_year_pareto_return_and_closed_minute_dd": True,
    "require_nominee_no_observed_risk_or_gross_mark_overrun": True,
    "numeric_tolerance_percentage_points": 1e-8,
    "mechanical_base_control_never_replaced": True,
    "authority": "REFERENCE_NOMINATION_ONLY_NOT_SELECTED_STRATEGY_OR_ALPHA",
}


def load_protocol(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    native, base = pair.load_protocol(path.parent / "right-tail-plan.json")
    expected = {
        **native,
        "schema": "kairos.strategy.calendar-pair-plan.v1",
        "purpose": "FULL_YEAR_DEVELOPMENT_PRIOR_EXPOSURE_NOT_EXCLUDED",
        "windows": list(WINDOWS),
        "prefix_cuts": "JAN_APR_JUL_OCT_01_0100_UTC_PLUS_END",
        "reference_rule": RULE,
        "funding_schedule": "DEFAULT_8H_WITH_BYTE_BOUND_SOL_NOV2022_4H_2H_EXCEPTION",
        "sol_exception_archive_sha256": SOL_EXCEPTION_SHA,
        "no_second_economic_attempt": True,
    }
    plan = json.loads(path.read_text(encoding="utf-8"))
    if canonical(plan) != canonical(expected):
        raise ValueError("unchanged full-calendar reference protocol required")
    return plan, base


def prefix_cuts(start_ms: int, end_ms: int) -> tuple[int, ...]:
    year = datetime.fromtimestamp(start_ms / 1000, UTC).year
    return tuple(
        sorted(
            {
                int(datetime(year, month, 1, 1, tzinfo=UTC).timestamp() * 1000)
                for month in (1, 4, 7, 10)
                if start_ms < int(datetime(year, month, 1, 1, tzinfo=UTC).timestamp() * 1000) < end_ms
            }
            | {end_ms}
        )
    )


def generate_calendar_pair(
    inputs: WindowInputs, deadline: float
) -> tuple[dict[str, dict[int, list[SleeveIntent]]], dict[str, Any]]:
    origin = inputs.start_ms - pair.WARMUP
    cuts = prefix_cuts(inputs.start_ms, inputs.end_ms)
    tapes: dict[str, dict[int, list[SleeveIntent]]] = {arm: {} for arm in pair.ARMS}
    evidence: dict[str, Any] = {
        "prefix_start_ms": origin,
        "exit_tail_used": False,
        "prefix_check_scope": "FIXED_QUARTERLY_CUTS_NOT_EVERY_DAILY_FUNCTION_PROOF",
        "symbols": {},
    }
    configs = (RightTailTrendConfig(), RegimeAlignedRightTailConfig())
    for symbol in UNIVERSE:
        prefix = [row for row in inputs.bars[symbol] if origin <= row.open_time_ms < inputs.end_ms]
        if (
            len(prefix) != (inputs.end_ms - origin) // pair.MINUTE
            or prefix[0].open_time_ms != origin
            or prefix[-1].close_time_ms != inputs.end_ms - 1
            or any(
                a.open_time_ms + pair.MINUTE != b.open_time_ms
                for a, b in zip(prefix, prefix[1:], strict=False)
            )
        ):
            raise ValueError("complete exact causal calendar prefix required")
        generated, symbol_evidence = {}, {}
        for arm, config in zip(pair.ARMS, configs, strict=True):
            if time.monotonic() >= deadline:
                raise TimeoutError("calendar generation resource bound")
            full = generate_sleeve_intents(arm, prefix, config)
            for cut in cuts:
                if time.monotonic() >= deadline:
                    raise TimeoutError("calendar prefix-check resource bound")
                truncated = generate_sleeve_intents(
                    arm, [row for row in prefix if row.open_time_ms < cut], config
                )
                if [asdict(i) for i in full if i.decision_ts_ms < cut] != [asdict(i) for i in truncated]:
                    raise ValueError("calendar same-origin prefix mutation")
            generated[arm] = full
            scoring = 0
            for intent in full:
                eligible = intent.entry_eligible_ts_ms
                if (
                    intent.sleeve_id != arm
                    or intent.symbol != symbol
                    or intent.decision_ts_ms != eligible - 1
                    or eligible % pair.DAY != pair.HOUR
                    or intent.entry_expires_ts_ms != eligible + pair.HOUR - 1
                    or intent.exit_plan.max_holding_ms != 72 * pair.HOUR
                    or intent.exit_plan.trailing_activation_price is not None
                    or dict(intent.metadata).get("config_sha256") != config.fingerprint
                ):
                    raise ValueError("native clock/lifecycle/config drift")
                if inputs.start_ms <= eligible < inputs.end_ms:
                    tapes[arm].setdefault(eligible, []).append(intent)
                    scoring += 1
            symbol_evidence[arm] = {"full_prefix_candidates": len(full), "scoring_candidates": scoring}
        pair.check_pair(generated[pair.ARMS[0]], generated[pair.ARMS[1]])
        pair.check_regime_selection(generated[pair.ARMS[0]], generated[pair.ARMS[1]], prefix)
        evidence["symbols"][symbol] = {
            "prefix_bars": len(prefix),
            "prefix_checks_ms": list(cuts),
            **symbol_evidence,
        }
        print(f"phase=native_checks_completed symbol={symbol}", flush=True)
    for tape in tapes.values():
        for intents in tape.values():
            intents.sort(key=lambda intent: (UNIVERSE.index(intent.symbol), intent.intent_id))
    return tapes, evidence


def select_reference(windows: list[dict[str, Any]]) -> dict[str, Any]:
    """Prespecified Pareto nomination; no optimized return/DD weights or alpha."""
    if [window["window"] for window in windows] != list(WINDOWS):
        raise ValueError("all four exact years required before reference decision")
    reports: dict[str, list[dict[str, Any]]] = {arm: [] for arm in pair.ARMS}
    for window in windows:
        if {arm["arm_id"] for arm in window["arms"]} != set(pair.ARMS) or len(window["arms"]) != 2:
            raise ValueError("both native arms required")
        for arm in window["arms"]:
            cells = arm["economic_results"]
            if len(cells) != 2 or {cell["cost_scenario"]["id"] for cell in cells} != {"base", "stress"}:
                raise ValueError("both cost cells required, never select on completed subset")
            for cell in cells:
                for field in ("net_return_pct", "closed_minute_mtm_drawdown_pct"):
                    if isinstance(cell[field], bool) or not math.isfinite(cell[field]):
                        raise ValueError("finite reference metric required")
                if cell["terminal_unresolved_positions"] or cell["forced_settlements"]:
                    raise ValueError("natural complete exits required")
            reports[arm["arm_id"]].append(
                next(cell for cell in cells if cell["cost_scenario"]["id"] == "stress")
            )
    activity = all(
        sum(cell["closed_trades"] for cell in cells) >= RULE["minimum_total_closes_each_arm"]
        and all(cell["closed_trades"] >= RULE["minimum_year_closes_each_arm"] for cell in cells)
        for cells in reports.values()
    )
    means = {arm: math.fsum(cell["net_return_pct"] for cell in cells) / 4 for arm, cells in reports.items()}
    nominees = []
    epsilon = RULE["numeric_tolerance_percentage_points"]
    if activity:
        for arm in pair.ARMS:
            other = next(value for value in pair.ARMS if value != arm)
            mine, theirs = reports[arm], reports[other]
            if means[arm] <= 0 or any(
                cell["risk_ceiling_mark_overrun"] or cell["gross_ceiling_mark_overrun"] for cell in mine
            ):
                continue
            weak = all(
                a["net_return_pct"] >= b["net_return_pct"] - epsilon
                and a["closed_minute_mtm_drawdown_pct"] <= b["closed_minute_mtm_drawdown_pct"] + epsilon
                for a, b in zip(mine, theirs, strict=True)
            )
            strict = any(
                a["net_return_pct"] > b["net_return_pct"] + epsilon
                or a["closed_minute_mtm_drawdown_pct"] < b["closed_minute_mtm_drawdown_pct"] - epsilon
                for a, b in zip(mine, theirs, strict=True)
            )
            if weak and strict:
                nominees.append(arm)
    if len(nominees) > 1:
        raise ValueError("inconsistent strict Pareto nomination")
    return {
        "state": "REFERENCE_NOMINATED"
        if nominees
        else "NO_ECONOMIC_REFERENCE_WINNER"
        if activity
        else "INSUFFICIENT_REFERENCE_ACTIVITY",
        "economic_reference_nominee": nominees[0] if nominees else None,
        "mechanical_control": pair.ARMS[0],
        "equal_year_mean_stress_return_pct_not_cagr": means,
        "stress_closes_each_arm": {
            arm: sum(cell["closed_trades"] for cell in cells) for arm, cells in reports.items()
        },
        "activity_threshold_not_statistical_power": True,
        "authority": RULE["authority"],
        "qualified_winner": None,
        "strategy_selected_for_live": None,
    }


def run(plan_path: Path, bar_cache: Path, factor_cache: Path, output: Path) -> int:
    plan, base = load_protocol(plan_path)
    before = pair.sources(plan, base, plan_path)
    for protected in (bar_cache, factor_cache, plan_path.parent):
        if output == protected or output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("calendar output must not overlap source or cache")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + plan["max_wall_seconds"]
    write_json(output / "sealed-calendar-plan.json", plan)
    write_json(output / "before.json", {"state": "RUNNING", "started_utc": utc_now(), "sources": before})
    windows = []
    try:
        for window in plan["windows"]:
            if time.monotonic() >= deadline:
                raise TimeoutError("calendar input resource bound")
            directory = output / window["id"]
            directory.mkdir()
            print(f"phase=calendar_integrity window={window['id']}", flush=True)
            inputs = load_calendar_window(bar_cache, factor_cache, window)
            write_json(directory / "inputs.json", inputs.evidence)
            tapes, generation = generate_calendar_pair(inputs, deadline)
            write_json(directory / "native-pair-evidence.json", generation)
            arms = []
            for arm in pair.ARMS:
                arm_dir = directory / arm
                arm_dir.mkdir()
                counts = pair.write_daily_tape(arm_dir / "decisions.jsonl", tapes[arm], inputs)
                results = []
                for cost in base["cost_scenarios"]:
                    report, account = replay_tape(
                        inputs,
                        tapes[arm],
                        CostScenario(**cost),
                        "STRICT_MINUTE_OPEN",
                        base["pipeline_latency_ms_assumed"],
                        72,
                        admission_policy=COMMON_COST_RISK,
                        deadline=deadline,
                    )
                    write_json(arm_dir / f"{cost['id']}.json", report)
                    write_json(
                        arm_dir / f"{cost['id']}-ledger.json",
                        {"events": account.events, "trades": account.trades},
                    )
                    results.append(report)
                    print(
                        f"phase=calendar_cell_completed window={window['id']} arm={arm} cost={cost['id']}",
                        flush=True,
                    )
                arms.append({"arm_id": arm, "counts": counts, "economic_results": results})
            windows.append({"window": window, "arms": arms})
            del inputs, tapes, account
            gc.collect()
        if load_protocol(plan_path) != (plan, base) or pair.sources(plan, base, plan_path) != before:
            raise ValueError("calendar protocol/source drift")
        write_json(
            output / "result.json",
            {
                "schema": "kairos.strategy.calendar-pair-result.v1",
                "state": "COMPLETED",
                "sources": before,
                "windows": windows,
                "reference_decision": select_reference(windows),
                "finished_utc": utc_now(),
                "elapsed_seconds": time.monotonic() - started,
                "readiness": plan["readiness"],
                "qualified_winner": None,
                "strategy_selected_for_live": None,
                "compound_return_across_windows": None,
                "blind_results_read": False,
                "blind_campaign_days_added": 0,
                "paid_calls": 0,
                "authority": "FULL_YEAR_DEVELOPMENT_NOT_INDEPENDENT_OOS_OR_ALPHA_QUALIFICATION",
            },
        )
        return 0
    except Exception as exc:
        write_json(
            output / "failure.json",
            {
                "state": "INCOMPLETE_RESOURCE_BOUND" if isinstance(exc, TimeoutError) else "FAILED_CLOSED",
                "error_type": type(exc).__name__,
                "reason": str(exc),
                "completed_windows": windows,
                "economic_reference_nominee": None,
                "elapsed_seconds": time.monotonic() - started,
            },
        )
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "bar-cache", "factor-cache", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    return run(*(getattr(args, name).resolve() for name in ("plan", "bar_cache", "factor_cache", "output")))


if __name__ == "__main__":
    raise SystemExit(main())
