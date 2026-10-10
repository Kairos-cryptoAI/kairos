"""Separate retrospective market-only experiment; never a production admission."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SYSTEM = """You are a cautious market-only reviewer of an existing crypto-futures candidate.
Use ONLY the supplied completed price/volume bars and candidate geometry. This is not
the full Kairos NEWS/MACRO system. News and external macro are unavailable, NOT known
empty; do not invent them, use tools, recognize or recall historical events. Dates,
asset names and absolute prices are intentionally masked. Values are normalized to
the last completed one-minute close=100; volume is relative to the supplied frame mean.
ALLOW if the supplied structure supports the unchanged candidate after stated costs;
VETO if supplied evidence contradicts it; DEFER if price evidence is insufficient.
Missing news alone is not an automatic VETO in this expressly market-only ablation.
Do not optimize parameters or suggest another trade. Never alter stop, target, expiry,
risk, size or leverage. Return only the required decision and a brief reason grounded
in supplied evidence. A signal strength is NOT a calibrated probability."""


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(
            json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )


def now() -> str:
    return datetime.now(UTC).isoformat()


def frames(rows: Any, minutes: int, cut: int, count: int = 12) -> list[dict[str, Any]]:
    """Only complete UTC-aligned groups; a future bar is rejected, not discarded."""
    if not rows or any(row.close_time_ms > cut for row in rows):
        raise ValueError("price prefix contains future or missing bars")
    width = minutes * 60_000
    grouped: dict[int, list[Any]] = {}
    for row in rows:
        grouped.setdefault(row.open_time_ms // width * width, []).append(row)
    complete = [
        group
        for ts, group in sorted(grouped.items())
        if len(group) == minutes
        and group[0].open_time_ms == ts
        and group[-1].close_time_ms == ts + width - 1
        and all(b.open_time_ms == ts + i * 60_000 for i, b in enumerate(group))
    ]
    if len(complete) < count:
        raise ValueError("insufficient complete context frames")
    selected = complete[-count:]
    base = rows[-1].close
    volumes = [sum(row.volume for row in group) for group in selected]
    mean_volume = sum(volumes) / len(volumes)
    return [
        {
            "age_seconds": (cut - group[-1].close_time_ms) // 1000,
            "ohlc": [
                round(value / base * 100, 6)
                for value in (
                    group[0].open,
                    max(b.high for b in group),
                    min(b.low for b in group),
                    group[-1].close,
                )
            ],
            "relative_volume": round(volume / mean_volume, 6) if mean_volume else 0.0,
        }
        for group, volume in zip(selected, volumes, strict=True)
    ]


def prompt_context(
    inputs: Any, intent: Any, regime: str, plan: dict[str, Any]
) -> dict[str, Any]:
    cut = intent.decision_ts_ms
    rows = tuple(row for row in inputs.bars[intent.symbol] if row.close_time_ms <= cut)
    market = tuple(row for row in inputs.bars["BTCUSDT"] if row.close_time_ms <= cut)
    if not rows or rows[-1].close_time_ms != cut:
        raise ValueError("candidate cut has no completed one-minute bar")
    reference = intent.reference_price
    return {
        "scope": "RETROSPECTIVE_MARKET_ONLY_REVIEW_NOT_FULL_KAIROS",
        "news": plan["news_status"],
        "external_macro": plan["macro_status"],
        "candidate": {
            "side": intent.side.value,
            "regime": regime,
            "pattern": dict(intent.metadata).get("pattern"),
            "stop_distance_bps": abs(intent.exit_plan.stop_price / reference - 1)
            * 10_000,
            "target_distance_bps": abs(intent.exit_plan.target_price / reference - 1)
            * 10_000,
            "original_entry_lifetime_ms": intent.entry_expires_ts_ms
            - intent.decision_ts_ms,
            "max_holding_ms": intent.exit_plan.max_holding_ms,
            "planning_round_trip_cost_bps": 20,
            "stress_round_trip_cost_bps": 33,
            "risk_fraction": 0.0025,
            "aggregate_risk_fraction": 0.01,
            "gross_leverage_limit": 1,
        },
        "asset_complete_bars": {
            f"{m}m": frames(rows, m, cut, plan["complete_bars_per_timeframe"])
            for m in plan["prompt_timeframes_minutes"]
        },
        "market_proxy_complete_1h_bars": frames(
            market, 60, cut, plan["complete_bars_per_timeframe"]
        ),
    }


def load_experiment(args: Any) -> tuple[dict, dict, dict]:
    from adaptive_replay.runner import load_plan

    plan = read_json(args.plan)
    original_plan = load_plan(args.strategy_plan)
    if file_sha(args.reference / "result.json") != plan["reference_result_sha256"]:
        raise ValueError("immutable reference result hash mismatch")
    reference = read_json(args.reference / "result.json")
    if (
        reference["state"] != "COMPLETED"
        or digest(original_plan) != reference["sources"]["plan_sha256"]
    ):
        raise ValueError("selected strategy reference not complete or changed")
    return plan, original_plan, reference


def source_identity(original_plan: dict, reference: dict) -> dict:
    from importlib.metadata import distribution

    from adaptive_replay import engine, inputs
    from kairos_backtest import cost_risk, data, factor_data, validation
    from kairos_strategy.adaptive import logic
    from kairos_strategy.adaptive.provenance import adaptive_source_identity

    actual = asdict(adaptive_source_identity())
    if actual != reference["sources"]["adaptive_identity"]:
        raise ValueError("selected native strategy identity changed")
    installed = {}
    for package, sha in original_plan["source_revisions"].items():
        info = json.loads(distribution(package).read_text("direct_url.json") or "{}")
        if info.get("vcs_info", {}).get("commit_id") != sha or info.get(
            "dir_info", {}
        ).get("editable"):
            raise ValueError(f"native dependency mismatch: {package}")
        installed[package] = sha
    backtest = {
        module.__name__: file_sha(Path(module.__file__))
        for module in (cost_risk, data, factor_data, validation)
    }
    if backtest != reference["sources"]["reused_backtest_modules_sha256"]:
        raise ValueError("reference archive/cost-risk parsing changed")
    if (
        file_sha(Path(inputs.__file__))
        != reference["sources"]["replay_modules_sha256"]["inputs.py"]
    ):
        raise ValueError("original cache validation changed")
    return {
        "native_strategy": actual,
        "installed_native_revisions": installed,
        "backtest_modules_sha256": backtest,
        "replay_engine_sha256": file_sha(Path(engine.__file__)),
        "input_loader_sha256": file_sha(Path(inputs.__file__)),
        "strategy_logic_sha256": file_sha(Path(logic.__file__)),
        "experiment_scripts_sha256": {
            p.name: file_sha(p) for p in sorted(Path(__file__).parent.glob("*.py"))
        },
        "original_reference_engine_sha256": reference["sources"][
            "replay_modules_sha256"
        ]["engine.py"],
        "engine_projection": "CURRENT_TRACKED_COST_AND_COMPLETION_ENGINE_WITH_UNCHANGED_NATIVE_CANDIDATES",
    }


def validated_window(
    args: Any, window: dict, reference_window: dict, original_plan: dict
) -> tuple[Any, dict, list]:
    from adaptive_replay.inputs import load_window
    from kairos_strategy.adaptive.config import DEFAULT_CONFIG, UNIVERSE
    from kairos_strategy.adaptive.logic import evaluate_adaptive

    inputs = load_window(
        args.bar_cache,
        args.factor_cache,
        window,
        original_plan["warmup_hours"],
        original_plan["exit_tail_hours"],
    )
    if inputs.evidence != read_json(args.reference / window["id"] / "inputs.json"):
        raise ValueError("validated source data differs from original receipt")
    tape_path = args.reference / window["id"] / "decisions.jsonl"
    if file_sha(tape_path) != reference_window["counts"]["tape_sha256"]:
        raise ValueError("immutable all-slot tape mismatch")
    rows = [
        json.loads(line) for line in tape_path.read_text(encoding="utf-8").splitlines()
    ]
    expected = {
        (s, ts - 1)
        for s in UNIVERSE
        for ts in range(inputs.start_ms, inputs.end_ms, 300_000)
    }
    if (
        len(rows) != len(expected)
        or {(r["symbol"], r["logical_decision_ms"]) for r in rows} != expected
    ):
        raise ValueError("all-slot roster is incomplete or duplicated")
    tape: dict[int, list] = {}
    candidates = []
    for row in rows:
        if row["context_cut_ms"] != row["logical_decision_ms"] or row[
            "slot_id"
        ] != digest(
            {
                k: row[k]
                for k in ("symbol", "logical_decision_ms", "input_window_sha256")
            }
        ):
            raise ValueError("causal tape identity mismatch")
        if row["intent"] is None:
            continue
        end = (row["logical_decision_ms"] + 1 - inputs.data_start_ms) // 60_000
        decision = evaluate_adaptive(
            inputs.bars[row["symbol"]][end - DEFAULT_CONFIG.history_bars : end]
        )
        if (
            decision.intent is None
            or canonical(asdict(decision.intent)) != canonical(row["intent"])
            or decision.input_window_sha256 != row["input_window_sha256"]
        ):
            raise ValueError("native candidate cannot be reproduced from causal prefix")
        tape.setdefault(row["logical_decision_ms"] + 1, []).append(decision.intent)
        candidates.append((row, decision.intent))
    if len(candidates) != reference_window["counts"]["candidates"]:
        raise ValueError("candidate coverage differs from reference")
    return inputs, tape, candidates


def prepare(args: Any) -> None:
    plan, original_plan, reference = load_experiment(args)
    sources = source_identity(original_plan, reference)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "sealed-plan.json", plan)
    write_json(
        args.output / "before.json",
        {
            "started_utc": now(),
            "source_identity": sources,
            "system_prompt_sha256": digest(SYSTEM),
            "strategy_plan": original_plan,
        },
    )
    requests = []
    for window, original in zip(
        original_plan["windows"], reference["windows"], strict=True
    ):
        print(f"phase=validate_available_data window={window['id']}", flush=True)
        inputs, _, candidates = validated_window(args, window, original, original_plan)
        write_json(
            args.output / f"{window['id']}-input-integrity.json", inputs.evidence
        )
        for row, intent in candidates:
            context = prompt_context(inputs, intent, row["regime"], plan)
            requests.append(
                {
                    "candidate_id": intent.intent_id,
                    "window_id": window["id"],
                    "slot_id": row["slot_id"],
                    "historical_cut_ms": intent.decision_ts_ms,
                    "system": SYSTEM,
                    "user": canonical(context).decode(),
                    "prompt_sha256": digest({"system": SYSTEM, "user": context}),
                }
            )
    requests.sort(key=lambda r: (r["historical_cut_ms"], r["candidate_id"]))
    if len(requests) != plan["expected_candidates"] or len(
        {r["candidate_id"] for r in requests}
    ) != len(requests):
        raise ValueError("exact predeclared candidate set required")
    write_json(args.output / "requests.json", requests)
    write_json(
        args.output / "seal.json",
        {
            "sealed_utc": now(),
            "plan_sha256": file_sha(args.output / "sealed-plan.json"),
            "requests_sha256": file_sha(args.output / "requests.json"),
            "before_sha256": file_sha(args.output / "before.json"),
            "expected_candidates": len(requests),
        },
    )
    print(f"phase=sealed all_native_candidates={len(requests)}", flush=True)


def validate_reviews(requests: list, reviews: list) -> dict:
    expected = {row["candidate_id"]: row for row in requests}
    if len(reviews) != len(expected) or {r["candidate_id"] for r in reviews} != set(
        expected
    ):
        raise ValueError("exact unique matched review coverage required")
    indexed = {}
    for row in reviews:
        request = expected[row["candidate_id"]]
        if row["prompt_sha256"] != request["prompt_sha256"] or row["decision"] not in {
            "ALLOW",
            "VETO",
            "DEFER",
        }:
            raise ValueError("review identity or policy mismatch")
        if (
            row["state"] != "OBSERVED_COMMITTED"
            or row["model"] != "gpt-6-luna"
            or row["effort"] != "medium"
        ):
            raise ValueError("unknown request/cost prevents complete economics")
        if type(row["actual_microusd"]) is not int or row["actual_microusd"] < 0:
            raise ValueError("unknown or invalid model economics")
        if (
            type(row["measured_pipeline_duration_ms"]) is not int
            or row["measured_pipeline_duration_ms"] <= 0
        ):
            raise ValueError("measured pipeline latency required")
        if (
            not row["modern_attempt_started_ms"]
            <= row["modern_response_observed_ms"]
            <= row["modern_adapter_finished_ms"]
        ):
            raise ValueError("actual observation clocks invalid")
        indexed[row["candidate_id"]] = row
    return indexed


def finish(args: Any) -> None:
    from adaptive_replay.engine import AccountCost, CostScenario, replay_tape

    _plan, original_plan, reference = load_experiment(args)
    seal = read_json(args.output / "seal.json")
    before = read_json(args.output / "before.json")
    if source_identity(original_plan, reference) != before["source_identity"]:
        raise ValueError("experiment sources changed after seal")
    if any(
        file_sha(args.output / name) != seal[key]
        for name, key in (
            ("requests.json", "requests_sha256"),
            ("sealed-plan.json", "plan_sha256"),
            ("before.json", "before_sha256"),
        )
    ):
        raise ValueError("experiment seal changed")
    requests = read_json(args.output / "requests.json")
    reviews = [
        json.loads(line)
        for line in (args.output / "reviews.jsonl").read_text().splitlines()
    ]
    observations = validate_reviews(requests, reviews)
    results = []
    for window, original in zip(
        original_plan["windows"], reference["windows"], strict=True
    ):
        inputs, tape, candidates = validated_window(
            args, window, original, original_plan
        )
        completions = {
            intent.intent_id: intent.decision_ts_ms
            + original_plan["pipeline_latency_ms_assumed"]
            + observations[intent.intent_id]["measured_pipeline_duration_ms"]
            for _, intent in candidates
        }
        accepted = {
            ts: [i for i in values if observations[i.intent_id]["decision"] == "ALLOW"]
            for ts, values in tape.items()
        }
        accepted = {ts: values for ts, values in accepted.items() if values}
        accepted_completions = {
            i.intent_id: completions[i.intent_id]
            for values in accepted.values()
            for i in values
        }
        costs = tuple(
            AccountCost(
                i.intent_id,
                completions[i.intent_id],
                observations[i.intent_id]["actual_microusd"] / 1_000_000,
                "MODEL",
            )
            for _, i in candidates
        )
        for mode in original_plan["entry_modes"]:
            for specification in original_plan["cost_scenarios"]:
                scenario = CostScenario(**specification)
                for arm, arm_tape, clocks, service_costs in (
                    ("strategy_only", tape, None, ()),
                    ("latency_cost_control", tape, completions, costs),
                    ("market_llm_review", accepted, accepted_completions, costs),
                ):
                    report, account = replay_tape(
                        inputs,
                        arm_tape,
                        scenario,
                        mode,
                        original_plan["pipeline_latency_ms_assumed"],
                        original_plan["exit_tail_hours"],
                        completion_times_ms=clocks,
                        service_costs=service_costs,
                    )
                    result = {
                        "window": window,
                        "arm": arm,
                        "report": report,
                        "scope": "CANDLE_APPROXIMATION_MARKET_ONLY_NOT_FULL_KAIROS",
                        "known_model_cost_usd": sum(
                            c.amount_usd for c in service_costs
                        ),
                        "model_calls_observed": len(costs)
                        if arm != "strategy_only"
                        else 0,
                    }
                    label = f"{window['id']}-{mode.lower()}-{scenario.id}-{arm}"
                    write_json(
                        args.output / f"{label}-ledger.json",
                        {"events": account.events, "trades": account.trades},
                    )
                    if arm == "strategy_only":
                        old = next(
                            r
                            for r in original["economic_results"]
                            if r["entry_mode"] == mode
                            and r["cost_scenario"]["id"] == scenario.id
                        )
                        if report["closed_trades"] != old[
                            "closed_trades"
                        ] or not math.isclose(
                            report["final_equity_usd"],
                            old["final_equity_usd"],
                            abs_tol=1e-8,
                        ):
                            raise ValueError(
                                "control replay differs from immutable original baseline"
                            )
                    results.append(result)
        print(f"phase=paired_replay_complete window={window['id']}", flush=True)
    summary = {
        "schema": "kairos.market-only-review.result.v1",
        "state": "COMPLETED",
        "finished_utc": now(),
        "plan_sha256": seal["plan_sha256"],
        "sources": before["source_identity"],
        "candidates": len(requests),
        "real_model_calls": len(reviews),
        "decisions": dict(Counter(r["decision"] for r in reviews)),
        "actual_model_cost_microusd": sum(r["actual_microusd"] for r in reviews),
        "results": results,
        "readiness": original_plan["readiness"],
        "full_news_macro_system_tested": False,
        "blind_campaign_days_added": 0,
        "compound_return_across_disjoint_windows": None,
        "limitations": [
            "12 candidates over four fixed development windows (12 calendar days), not out-of-sample alpha proof.",
            "Modern trained model may know historical patterns despite calendar/price masking; this is not a genuine historical live model.",
            "News and external macro unavailable/not tested; missing is not known empty.",
            "Review only of native candidates: no LLM-generated proposals or evaluation on NO_INTENT slots.",
            "Measured modern request duration plus 100ms baseline is mapped into historical clocks, not backdated evidence.",
            "Minute OHLC proxy is not an observed post-review quote; strict minute-open diagnosis is reported separately.",
            "Fees/spread/slippage are declared assumptions; archived funding uses candle-open entitlement proxy.",
            "API costs include veto/defer requests, but historical feed acquisition and infrastructure costs are unknown/excluded.",
            "No qualification or trading permission; independent $10000 simulated accounts per disjoint window.",
        ],
    }
    write_json(args.output / "result.json", summary)
    print(
        f"state=COMPLETED real_model_calls={len(reviews)} decisions={summary['decisions']}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "finish"))
    for name in (
        "plan",
        "strategy-plan",
        "reference",
        "bar-cache",
        "factor-cache",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    (prepare if args.phase == "prepare" else finish)(args)


if __name__ == "__main__":
    main()
