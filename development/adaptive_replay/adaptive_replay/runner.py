"""Bounded offline CLI, exclusive append-only result directory, pinned source guards."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import distribution
from pathlib import Path
from typing import Any

from kairos_backtest import cost_risk, data, factor_data, validation
from kairos_strategy.adaptive.config import DEFAULT_CONFIG, STRATEGY_ID, UNIVERSE
from kairos_strategy.adaptive.logic import evaluate_adaptive
from kairos_strategy.adaptive.provenance import adaptive_source_identity

from .engine import CostScenario, replay_tape
from .inputs import load_window
from .matched import preparation_report


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def load_plan(path: Path) -> dict[str, Any]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan["schema"] != "kairos.adaptive.development-plan.v1" or plan["strategy_id"] != STRATEGY_ID:
        raise ValueError("wrong development plan/strategy identity")
    if tuple(plan["universe"]) != UNIVERSE or plan["warmup_hours"] != 54 or plan["exit_tail_hours"] != 3:
        raise ValueError("fixed universe/warmup/bounded tail required")
    expected = [
        ("late_2021", "2021-11-07", "2021-11-10"),
        ("early_2022", "2022-02-05", "2022-02-08"),
        ("may_2022", "2022-05-09", "2022-05-12"),
        ("june_2022", "2022-06-13", "2022-06-16"),
    ]
    if [(w["id"], w["start"], w["end_exclusive"]) for w in plan["windows"]] != expected:
        raise ValueError("this runner accepts only its preregistered calendar development slices")
    if plan["initial_equity_usd_each_window"] != 10_000 or plan["pipeline_latency_ms_assumed"] != 100:
        raise ValueError("fixed account and declared latency assumption required")
    if plan["workers"] != 1 or not 1 <= plan["max_wall_seconds"] <= 3600:
        raise ValueError("bounded single-worker resource limit required")
    if plan["entry_modes"] != ["STRICT_MINUTE_OPEN", "INTRABAR_OPEN_PROXY"]:
        raise ValueError("strict timing diagnosis cannot be removed")
    fixed_costs = [
        {
            "id": "base",
            "fee_bps_per_side": 4.5,
            "spread_bps": 2,
            "slippage_bps_per_side": 1,
            "latency_bps_round_trip": 2,
            "uncertainty_bps": 2,
            "admission_adverse_carry_bps": 3,
        },
        {
            "id": "stress",
            "fee_bps_per_side": 9,
            "spread_bps": 4,
            "slippage_bps_per_side": 2,
            "latency_bps_round_trip": 2,
            "uncertainty_bps": 2,
            "admission_adverse_carry_bps": 3,
        },
    ]
    if plan["cost_scenarios"] != fixed_costs:
        raise ValueError("fixed base/stress assumptions; no fee scenario selection")
    if plan["risk_policy"] != {
        "per_trade_fraction": 0.0025,
        "aggregate_open_fraction": 0.01,
        "max_notional_fraction_per_symbol": 0.25,
        "gross_leverage": 1,
    }:
        raise ValueError("risk cannot be weakened for development")
    if any(v for k, v in plan["readiness"].items() if k != "STRATEGY_POLICY"):
        raise ValueError("development never promotes readiness")
    if plan["readiness"]["STRATEGY_POLICY"] != "REJECT_ALL":
        raise ValueError("no trading authority")
    if not all(plan[k] is True for k in ("no_downloads", "no_parameter_search", "no_blind_campaign_credit")):
        raise ValueError("offline/no-search/non-enrollment restrictions required")
    return plan


def source_receipt(plan: dict[str, Any], plan_path: Path) -> dict[str, Any]:
    identity = asdict(adaptive_source_identity())
    if identity["strategy_code_sha256"] != plan["strategy_code_sha256"]:
        raise ValueError("selected strategy source changed")
    if identity["config_sha256"] != plan["strategy_config_sha256"]:
        raise ValueError("selected strategy configuration changed")
    installed: dict[str, Any] = {}
    for package, revision in plan["source_revisions"].items():
        dist = distribution(package)
        raw = dist.read_text("direct_url.json")
        info = json.loads(raw or "{}")
        if info.get("vcs_info", {}).get("commit_id") != revision or info.get("dir_info", {}).get("editable"):
            raise ValueError(f"immutable installed dependency mismatch: {package}")
        installed[package] = {"version": dist.version, "revision": revision}
    modules = sorted(Path(__file__).parent.glob("*.py"))
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in modules}
    lock = plan_path.parent / "uv.lock"
    return {
        "adaptive_identity": identity,
        "installed_dependencies": installed,
        "reused_backtest_modules_sha256": {
            module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (cost_risk, data, factor_data, validation)
        },
        "replay_modules_sha256": files,
        "plan_sha256": digest(plan),
        "uv_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "dependency_projection": "EXPLICIT_DEVELOPMENT_OVERRIDES_NOT_FROZEN_CAMPAIGN_ENVIRONMENT",
    }


def build_tape(inputs: Any, directory: Path, deadline: float) -> tuple[dict[int, list[Any]], dict[str, Any]]:
    tape: dict[int, list[Any]] = {}
    statuses: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    regimes: Counter[str] = Counter()
    fingerprint = hashlib.sha256()
    slots = candidates = 0
    with (directory / "decisions.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
        for symbol in UNIVERSE:
            rows = inputs.bars[symbol]
            for ts in range(inputs.start_ms, inputs.end_ms, 300_000):
                if time.monotonic() > deadline:
                    raise TimeoutError("bounded development wall-time limit reached")
                end = (ts - inputs.data_start_ms) // 60_000
                decision = evaluate_adaptive(rows[end - DEFAULT_CONFIG.history_bars : end])
                if decision.decision_ts_ms != ts - 1 or decision.input_window_sha256 is None:
                    raise ValueError("complete causal historical slot required")
                status = str(decision.status)
                statuses[status] += 1
                reasons[decision.reason] += 1
                regimes[decision.regime.value] += 1
                item = {
                    "symbol": symbol,
                    "logical_decision_ms": ts - 1,
                    "context_cut_ms": ts - 1,
                    "input_window_sha256": decision.input_window_sha256,
                    "status": status,
                    "reason": decision.reason,
                    "regime": decision.regime.value,
                    "intent": asdict(decision.intent) if decision.intent is not None else None,
                    "source_clock_authority": "HISTORICAL_EVENT_TIME_NOT_LIVE_RECEIPT",
                }
                item["slot_id"] = digest(
                    {k: item[k] for k in ("symbol", "logical_decision_ms", "input_window_sha256")}
                )
                encoded = canonical(item)
                fingerprint.update(encoded + b"\n")
                stream.write(encoded.decode() + "\n")
                slots += 1
                if decision.intent is not None:
                    tape.setdefault(ts, []).append(decision.intent)
                    candidates += 1
                if slots % 432 == 0:
                    print(f"phase=causal_tape symbol={symbol} slots={slots}", flush=True)
    return tape, {
        "scheduled_slots": slots,
        "candidates": candidates,
        "statuses": dict(sorted(statuses.items())),
        "reasons": dict(sorted(reasons.items())),
        "causal_detected_regimes": dict(sorted(regimes.items())),
        "tape_sha256": fingerprint.hexdigest(),
        "decisions_in_exit_tail": 0,
        "warmup_slots": statuses["WARMUP"],
    }


def run(plan_path: Path, bar_cache: Path, factor_cache: Path, output: Path) -> int:
    plan = load_plan(plan_path)
    sources = source_receipt(plan, plan_path)
    # Never reuse/resume/overwrite an old output: preserves failed attempts too.
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + plan["max_wall_seconds"]
    write_json(output / "sealed-development-plan.json", plan)
    write_json(
        output / "before.json",
        {"started_utc": utc_now(), "sources": sources, "scope": "DEVELOPMENT_ONLY", "state": "RUNNING"},
    )
    windows: list[dict[str, Any]] = []
    failed = False
    try:
        for window in plan["windows"]:
            if time.monotonic() > deadline:
                raise TimeoutError("bounded development wall-time limit reached")
            directory = output / window["id"]
            directory.mkdir()
            print(f"phase=offline_integrity window={window['id']}", flush=True)
            try:
                inputs = load_window(
                    bar_cache,
                    factor_cache,
                    window,
                    warmup_hours=plan["warmup_hours"],
                    exit_tail_hours=plan["exit_tail_hours"],
                )
            except (ValueError, FileNotFoundError) as exc:
                blocked = {
                    "window": window,
                    "state": "BLOCKED_INPUT_INTEGRITY",
                    "reason": str(exc),
                    "economic_results": None,
                }
                write_json(directory / "blocked.json", blocked)
                windows.append(blocked)
                failed = True
                print(f"phase=blocked_input window={window['id']}", flush=True)
                continue
            write_json(directory / "inputs.json", inputs.evidence)
            tape, counts = build_tape(inputs, directory, deadline)
            write_json(directory / "tape-receipt.json", counts)
            write_json(
                directory / "matched-preparation.json",
                preparation_report(
                    counts["tape_sha256"],
                    counts["scheduled_slots"],
                    counts["candidates"],
                    counts["statuses"].get("NO_INTENT", 0),
                ),
            )
            results = []
            for mode in plan["entry_modes"]:
                for specification in plan["cost_scenarios"]:
                    if time.monotonic() > deadline:
                        raise TimeoutError("bounded development wall-time limit reached")
                    scenario = CostScenario(**specification)
                    report, account = replay_tape(
                        inputs,
                        tape,
                        scenario,
                        mode,
                        plan["pipeline_latency_ms_assumed"],
                        plan["exit_tail_hours"],
                    )
                    label = f"{mode.lower()}-{scenario.id}"
                    write_json(directory / f"{label}.json", report)
                    write_json(
                        directory / f"{label}-ledger.json",
                        {"events": account.events, "trades": account.trades},
                    )
                    results.append(report)
            windows.append(
                {
                    "window": window,
                    "state": "CONDITIONAL_DEVELOPMENT_COMPLETED",
                    "counts": counts,
                    "economic_results": results,
                }
            )
            print(f"phase=window_complete window={window['id']}", flush=True)
        if source_receipt(plan, plan_path) != sources or load_plan(plan_path) != plan:
            raise ValueError("source/plan changed during the run")
        result = {
            "schema": "kairos.adaptive.development-result.v1",
            "state": "COMPLETED_WITH_BLOCKED_INPUTS" if failed else "COMPLETED",
            "finished_utc": utc_now(),
            "elapsed_seconds": time.monotonic() - started,
            "sources": sources,
            "windows": windows,
            "compound_return_across_windows": None,
            "economic_authority": "CONDITIONAL_CANDLE_APPROXIMATION_NOT_ALPHA_OR_VENUE_QUALIFICATION",
            "blind_results_read": False,
            "blind_campaign_days_added": 0,
            "llm_matched_ab_executed": False,
            "readiness": plan["readiness"],
        }
        write_json(output / "result.json", result)
        return 2 if failed else 0
    except Exception as exc:
        write_json(
            output / "failure.json",
            {
                "state": "FAILED_CLOSED",
                "error_type": type(exc).__name__,
                "reason": str(exc),
                "retained_windows": windows,
                "elapsed_seconds": time.monotonic() - started,
            },
        )
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--bar-cache", type=Path, required=True)
    parser.add_argument("--factor-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return run(
        args.plan.resolve(), args.bar_cache.resolve(), args.factor_cache.resolve(), args.output.resolve()
    )


if __name__ == "__main__":
    raise SystemExit(main())
