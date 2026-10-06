"""Offline, preregistered small comparison of native baselines, union and adaptive.

No strategies, frozen source, protected campaigns, real funds or services change.
Seen calendar diagnostics cannot select a qualified champion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from kairos_core.enums import Side
from kairos_strategy.adaptive.config import DEFAULT_CONFIG, STRATEGY_ID
from kairos_strategy.adaptive.provenance import adaptive_window_sha256
from kairos_strategy.models import ExitPlan, SleeveIntent

from .baselines import BASELINE_IDS, baseline_identities, combine_tapes, generate_baseline_tapes
from .engine import COMMON_COST_RISK, CostScenario, replay_tape
from .inputs import UNIVERSE, WindowInputs, load_window
from .runner import canonical, digest, load_plan, source_receipt, utc_now, write_json

UNION_ID = "fixed_breakout_range_union_v1"
ARMS = (*BASELINE_IDS, UNION_ID, STRATEGY_ID)
COMMON_ADMISSION = {
    "policy": COMMON_COST_RISK,
    "minimum_stop_distance_bps": 10,
    "maximum_stop_distance_bps": 300,
    "minimum_net_reward_to_risk": 1.25,
    "maximum_cost_stop_fraction": 0.5,
    "adaptive_atr15_fill_filter": False,
}
BASE_PLAN_SHA = "ad07e992a1440f459acb7b8cdb621a54c70ad1119ee9af7f37aceb6966d69f0c"
ADAPTIVE_RESULT_SHA = "f73c246d6a2fdd17538ed10911223b386e1a3da07d1e0a1365153d9f21f0ce0c"
SHA256 = re.compile(r"[0-9a-f]{64}")


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_comparison_plan(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    base = load_plan(path.parent / "plan.json")
    if plan.get("schema") != "kairos.strategy.comparison-plan.v1" or plan.get("arms") != list(ARMS):
        raise ValueError("fixed small comparison identity required")
    if plan.get("base_development_plan_sha256") != BASE_PLAN_SHA or digest(base) != BASE_PLAN_SHA:
        raise ValueError("unchanged source/data/cost/risk base protocol required")
    if plan.get("adaptive_evidence_result_sha256") != ADAPTIVE_RESULT_SHA:
        raise ValueError("original adaptive decision evidence identity required")
    if plan.get("common_admission") != COMMON_ADMISSION:
        raise ValueError("common admission cannot be selectively weakened")
    if plan.get("workers") != 1 or plan.get("max_wall_seconds") != 1800:
        raise ValueError("fixed bounded single worker required")
    for field in (
        "native_entry_lifetimes",
        "native_close_updated_trailing",
        "no_downloads",
        "no_paid_calls",
        "no_parameter_search",
        "no_blind_campaign_credit",
    ):
        if plan.get(field) is not True:
            raise ValueError(f"comparison restriction missing: {field}")
    if plan.get("readiness") != base["readiness"]:
        raise ValueError("comparison cannot promote readiness or trading policy")
    identities = baseline_identities()
    if plan.get("baseline_config_fingerprints") != {s: i["fingerprint"] for s, i in identities.items()}:
        raise ValueError("native baseline configuration changed")
    if plan.get("baseline_source_fingerprints") != {
        s: i["installed_source_tree_sha256"] for s, i in identities.items()
    }:
        raise ValueError("native baseline installed source changed")
    return plan, base


def comparison_sources(path: Path, plan: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    return {
        "base_sources": source_receipt(base, path.parent / "plan.json"),
        "baseline_identities": baseline_identities(),
        "comparison_plan_sha256": digest(plan),
        "common_admission": COMMON_ADMISSION,
        "economics_reused": False,
    }


def decode_intent(raw: dict[str, Any]) -> SleeveIntent:
    values = dict(raw)
    recorded_id = values.pop("intent_id")
    values["side"] = Side(values["side"])
    values["exit_plan"] = ExitPlan(**values["exit_plan"])
    values["metadata"] = tuple(tuple(pair) for pair in values["metadata"])
    intent = SleeveIntent(**values)
    if intent.intent_id != recorded_id or intent.sleeve_id != STRATEGY_ID:
        raise ValueError("adaptive native candidate identity changed")
    return intent


def require_ready_adaptive_slot(item: dict[str, Any]) -> None:
    # An unavailable/warmup/error slot must never become an ordinary quiet
    # observation simply because it has no candidate. This comparator accepts
    # only the independently byte-bound fully ready original tapes.
    if item["status"] not in {"INTENT", "NO_INTENT"}:
        raise ValueError("adaptive unavailable/warmup/error slot cannot become trading silence")
    if (item["status"] == "INTENT") != (item["intent"] is not None):
        raise ValueError("adaptive slot status and candidate disagree")


def adaptive_tape(
    root: Path, inputs: WindowInputs, window: dict[str, Any], base: dict[str, Any], deadline: float
) -> tuple[dict[int, list[SleeveIntent]], dict[str, Any]]:
    result_path = root / "result.json"
    if file_sha(result_path) != ADAPTIVE_RESULT_SHA:
        raise ValueError("adaptive original result does not match published byte identity")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result["state"] != "COMPLETED" or result["sources"]["plan_sha256"] != digest(base):
        raise ValueError("completed original adaptive evidence required")
    identity = result["sources"]["adaptive_identity"]
    if (
        identity["strategy_code_sha256"] != base["strategy_code_sha256"]
        or identity["config_sha256"] != base["strategy_config_sha256"]
    ):
        raise ValueError("adaptive source/config evidence drift")
    original = next(w for w in result["windows"] if w["window"] == window)
    directory = root / window["id"]
    original_inputs = json.loads((directory / "inputs.json").read_text(encoding="utf-8"))
    if original_inputs != inputs.evidence:
        raise ValueError("common verified input differs from original adaptive tape")
    tape: dict[int, list[SleeveIntent]] = {}
    counts: Counter[str] = Counter()
    fingerprint = hashlib.sha256()
    candidate_count = 0
    expected = [(s, ts) for s in UNIVERSE for ts in range(inputs.start_ms, inputs.end_ms, 300_000)]
    position = 0
    with (directory / "decisions.jsonl").open("rb") as stream:
        for encoded in stream:
            if time.monotonic() > deadline:
                raise TimeoutError("bounded adaptive tape verification deadline reached")
            if position >= len(expected):
                raise ValueError("adaptive tape has additional slots")
            item = json.loads(encoded)
            require_ready_adaptive_slot(item)
            symbol, ts = expected[position]
            if (
                item["symbol"] != symbol
                or item["logical_decision_ms"] != ts - 1
                or item["context_cut_ms"] != ts - 1
                or not SHA256.fullmatch(item["input_window_sha256"])
                or item["source_clock_authority"] != "HISTORICAL_EVENT_TIME_NOT_LIVE_RECEIPT"
            ):
                raise ValueError("adaptive tape causal slot changed")
            if canonical(item) + b"\n" != encoded:
                raise ValueError("adaptive tape must preserve original canonical bytes")
            fingerprint.update(encoded)
            counts[item["status"]] += 1
            if item["intent"] is not None:
                intent = decode_intent(item["intent"])
                end = (ts - inputs.data_start_ms) // 60_000
                actual_window = inputs.bars[symbol][end - DEFAULT_CONFIG.history_bars : end]
                if adaptive_window_sha256(actual_window) != item["input_window_sha256"]:
                    raise ValueError("adaptive candidate closed-history hash changed")
                if intent.symbol != symbol or intent.decision_ts_ms != ts - 1:
                    raise ValueError("adaptive candidate escaped its causal slot")
                tape.setdefault(ts, []).append(intent)
                candidate_count += 1
            position += 1
    original_counts = original["counts"]
    if (
        position != len(expected)
        or fingerprint.hexdigest() != original_counts["tape_sha256"]
        or dict(sorted(counts.items())) != original_counts["statuses"]
        or candidate_count != original_counts["candidates"]
    ):
        raise ValueError("adaptive complete tape checksum/counts changed")
    return tape, {
        **original_counts,
        "source": "BYTE_BOUND_ORIGINAL_DECISION_TAPE_WITH_REVERIFIED_IDENTICAL_INPUT",
        "original_result_sha256": ADAPTIVE_RESULT_SHA,
        "original_economic_results_reused": False,
    }


def write_tape(
    path: Path,
    tape: dict[int, list[SleeveIntent]],
    inputs: WindowInputs,
    *,
    complete_source_outcomes: bool = False,
) -> dict[str, Any]:
    fingerprint = hashlib.sha256()
    common_input_hash = digest(inputs.evidence)
    slots = candidates = quiet = 0
    by_slot = {(ts, intent.symbol): intent for ts, intents in tape.items() for intent in intents}
    if len(by_slot) != sum(len(v) for v in tape.values()):
        raise ValueError("duplicate same-symbol candidate escaped tape arbitration")
    with path.open("xb") as stream:
        for symbol in UNIVERSE:
            for ts in range(inputs.start_ms, inputs.end_ms, 300_000):
                intent = by_slot.get((ts, symbol))
                item = {
                    "symbol": symbol,
                    "context_cut_ms": ts - 1,
                    "common_window_evidence_sha256": common_input_hash,
                    "status": "CANDIDATE"
                    if intent
                    else "NO_INTENT"
                    if complete_source_outcomes
                    else "NO_CANDIDATE_REPORTED",
                    "intent": asdict(intent) if intent else None,
                    "clock_authority": "HISTORICAL_EVENT_TIME_NOT_LIVE_RECEIPT",
                }
                encoded = canonical(item) + b"\n"
                fingerprint.update(encoded)
                stream.write(encoded)
                slots += 1
                candidates += intent is not None
                quiet += intent is None
    return {
        "scheduled_slots": slots,
        "verified_input_ready_slots": slots,
        "source_ready_slots": slots if complete_source_outcomes else None,
        "source_unavailable_slots": 0 if complete_source_outcomes else None,
        "source_availability_status": "FULLY_READY_ORIGINAL_OUTCOMES_VERIFIED"
        if complete_source_outcomes
        else "NATIVE_GENERATOR_DOES_NOT_EXPOSE_COMPLETE_SLOT_OUTCOMES",
        "raw_candidates": candidates,
        "quiet_slots": quiet,
        "tape_sha256": fingerprint.hexdigest(),
    }


def run(plan_path: Path, bar_cache: Path, factor_cache: Path, adaptive_root: Path, output: Path) -> int:
    plan, base = load_comparison_plan(plan_path)
    sources = comparison_sources(plan_path, plan, base)
    for protected in (bar_cache, factor_cache, adaptive_root, plan_path.parent):
        if output == protected or output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("output must be isolated from source/cache/original evidence")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + plan["max_wall_seconds"]
    write_json(output / "sealed-comparison-plan.json", plan)
    write_json(output / "before.json", {"started_utc": utc_now(), "sources": sources, "state": "RUNNING"})
    windows = []
    try:
        for window in base["windows"]:
            directory = output / window["id"]
            directory.mkdir()
            print(f"phase=common_offline_integrity window={window['id']}", flush=True)
            inputs = load_window(
                bar_cache, factor_cache, window, base["warmup_hours"], base["exit_tail_hours"]
            )
            write_json(directory / "inputs.json", inputs.evidence)
            native_tapes, native_evidence = generate_baseline_tapes(inputs, deadline)
            current_tape, current_evidence = adaptive_tape(adaptive_root, inputs, window, base, deadline)
            union, arbitration = combine_tapes(native_tapes)
            tapes = {**native_tapes, UNION_ID: union, STRATEGY_ID: current_tape}
            write_json(directory / "native-baseline-evidence.json", native_evidence)
            write_json(directory / "adaptive-tape-evidence.json", current_evidence)
            write_json(directory / "union-arbitration.json", arbitration)
            arm_results = []
            for arm_id in ARMS:
                arm_dir = directory / arm_id
                arm_dir.mkdir()
                counts = write_tape(
                    arm_dir / "decisions.jsonl",
                    tapes[arm_id],
                    inputs,
                    complete_source_outcomes=arm_id == STRATEGY_ID,
                )
                write_json(arm_dir / "tape-receipt.json", counts)
                results = []
                for mode in base["entry_modes"]:
                    for cost in base["cost_scenarios"]:
                        report, account = replay_tape(
                            inputs,
                            tapes[arm_id],
                            CostScenario(**cost),
                            mode,
                            base["pipeline_latency_ms_assumed"],
                            base["exit_tail_hours"],
                            admission_policy=COMMON_COST_RISK,
                            deadline=deadline,
                        )
                        label = f"{mode.lower()}-{cost['id']}"
                        write_json(arm_dir / f"{label}.json", report)
                        write_json(
                            arm_dir / f"{label}-ledger.json",
                            {"events": account.events, "trades": account.trades},
                        )
                        results.append(report)
                arm_results.append({"arm_id": arm_id, "counts": counts, "economic_results": results})
                print(f"phase=arm_completed window={window['id']} arm={arm_id}", flush=True)
            windows.append({"window": window, "arms": arm_results, "union_arbitration": arbitration})
        if comparison_sources(plan_path, plan, base) != sources or load_comparison_plan(plan_path) != (
            plan,
            base,
        ):
            raise ValueError("comparison plan/source changed during the run")
        write_json(
            output / "result.json",
            {
                "schema": "kairos.strategy.comparison-result.v1",
                "state": "COMPLETED",
                "finished_utc": utc_now(),
                "elapsed_seconds": time.monotonic() - started,
                "sources": sources,
                "windows": windows,
                "readiness": plan["readiness"],
                "qualified_winner": None,
                "strategy_selected_for_live": None,
                "compound_return_across_windows": None,
                "authority": "SEEN_DIAGNOSTIC_CONDITIONAL_COMPARISON_NOT_ALPHA_OR_VENUE_QUALIFICATION",
                "blind_results_read": False,
                "blind_campaign_days_added": 0,
                "paid_calls": 0,
            },
        )
        return 0
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
    parser.add_argument("--adaptive-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return run(
        *(
            getattr(args, field).resolve()
            for field in (
                "plan",
                "bar_cache",
                "factor_cache",
                "adaptive_evidence",
                "output",
            )
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
