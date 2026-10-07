"""Create-only, bounded price-only SIM for the approved A/D historical pilot.

No archive search, provider, database, key, venue, or campaign operations. The
native strategy is evaluated at its frozen 5m cadence; every original 1m cell
is retained, including unscheduled cells and zero-trade days. This is not the
source-blocked paid matched A/B, and model arms are never imputed as zero PnL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from dataclasses import asdict
from importlib.metadata import distribution
from pathlib import Path
from typing import Any

from .engine import COMMON_COST_RISK, CostScenario, replay_tape
from .historical_inputs import validate_replay_inputs
from .historical_macro_archive import extract
from .historical_pilot_budget import FROZEN_PLAN_SHA256
from .historical_pilot_preflight import (
    EPISODES,
    _input_roots,
    _market_summary,
    _utc_ms,
    validate_paths,
    validate_pilot_plan,
)
from .inputs import UNIVERSE, WindowInputs, load_window
from .runner import build_tape, canonical, digest, load_plan, source_receipt, utc_now, write_json

SCHEMA = "kairos.development.historical-pilot-price-sim.v1"
LLM_REVISION = "f1e25893f9078a467eba584e233ac9129e9ff9b1"
MAX_WALL_SECONDS = 900


def _check_time(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("bounded historical price SIM deadline reached")


def sealed_protocol(source_plan: dict[str, Any]) -> dict[str, Any]:
    """One fixed diagnostic, created before candidate generation or economics."""
    return {
        "schema": SCHEMA,
        "purpose": "PRICE_ONLY_ENGINEERING_DIAGNOSTIC_NOT_PAID_MATCHED_AB_OR_ALPHA",
        "pilot_draft_raw_sha256": FROZEN_PLAN_SHA256,
        "strategy_id": source_plan["strategy_id"],
        "strategy_code_sha256": source_plan["strategy_code_sha256"],
        "strategy_config_sha256": source_plan["strategy_config_sha256"],
        "candidate_authority": "PINNED_EXISTING_PROTOTYPE_NOT_SELECTED_CHAMPION_OR_LIVE_STRATEGY",
        "universe": list(UNIVERSE),
        "episodes": [
            {"id": episode, "start": start, "end_exclusive": end, "review_cuts": [a, b]}
            for episode, start, end, a, b, _ in EPISODES
        ],
        "strategy_cadence_ms": 300_000,
        "denominator_cadence_ms": 60_000,
        "warmup_hours": 54,
        "exit_tail_hours": 3,
        "baseline_latency_ms": 100,
        "entry_modes": list(source_plan["entry_modes"]),
        "cost_scenarios": list(source_plan["cost_scenarios"]),
        "risk_policy": source_plan["risk_policy"],
        "admission_policy": COMMON_COST_RISK,
        "readiness": source_plan["readiness"],
        "required_news_ready": False,
        "review_arms": "UNAVAILABLE_NOT_EXECUTED_NOT_ZERO_RETURN",
        "macro_scope": "OFFLINE_CPI_SEMANTICS_ONLY_NOT_FULL_MACRO_OR_RECEIPT_PROOF",
        "provider_calls": 0,
        "workers": 1,
        "max_wall_seconds": MAX_WALL_SECONDS,
        "parameter_search": False,
        "new_data_downloads": False,
        "blind_campaign_credit": False,
    }


def installed_sources(source_plan: dict[str, Any], source_plan_path: Path) -> dict[str, Any]:
    sources = source_receipt(source_plan, source_plan_path)
    dist = distribution("kairos-llm")
    url = json.loads(dist.read_text("direct_url.json") or "{}")
    if url.get("vcs_info", {}).get("commit_id") != LLM_REVISION or url.get("dir_info", {}).get("editable"):
        raise ValueError("immutable installed native LLM dependency required")
    sources["native_llm_dependency"] = {"revision": LLM_REVISION, "version": dist.version}
    return sources


def emit_denominator(
    inputs: WindowInputs, directory: Path, cuts: tuple[str, str], deadline: float
) -> dict[str, Any]:
    """Bind the full 1m roster to the actually emitted native strategy tape."""
    decisions: dict[tuple[int, str], dict[str, Any]] = {}
    stream_sha = hashlib.sha256()
    with (directory / "decisions.jsonl").open("rb") as stream:
        for line in stream:
            _check_time(deadline)
            stream_sha.update(line)
            row = json.loads(line)
            key = (row["logical_decision_ms"] + 1, row["symbol"])
            if (
                key in decisions
                or key[1] not in UNIVERSE
                or not inputs.start_ms <= key[0] < inputs.end_ms
                or (key[0] - inputs.start_ms) % 300_000
            ):
                raise ValueError("invalid or duplicate native decision cell")
            intent = row["intent"]
            if intent is not None and (intent["symbol"] != key[1] or intent["decision_ts_ms"] != key[0] - 1):
                raise ValueError("native candidate identity differs from original cell")
            decisions[key] = row
    expected = {
        (cut, symbol) for cut in range(inputs.start_ms, inputs.end_ms, 300_000) for symbol in UNIVERSE
    }
    if decisions.keys() != expected:
        raise ValueError("complete native 5m decision roster required")
    schedule = {_utc_ms(cut) for cut in cuts}
    if len(schedule) != 2 or any(not inputs.start_ms <= t < inputs.end_ms for t in schedule):
        raise ValueError("exact two in-window review cuts required")
    states: Counter[str] = Counter()
    no_calls: Counter[str] = Counter()
    scheduled_candidates = []
    scheduled_states: Counter[str] = Counter()
    fingerprint = hashlib.sha256()
    count = 0
    with (directory / "denominator.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
        for cut in range(inputs.start_ms, inputs.end_ms, 60_000):
            _check_time(deadline)
            for symbol in UNIVERSE:
                native = decisions.get((cut, symbol))
                candidate = None if native is None else native["intent"]
                state = (
                    "NOT_SCHEDULED_NATIVE_CADENCE"
                    if native is None
                    else "CANDIDATE"
                    if candidate is not None
                    else "QUIET"
                    if native["status"] == "NO_INTENT"
                    else "UNAVAILABLE"
                )
                scheduled = cut in schedule
                no_call = "REQUIRED_SOURCE_UNAVAILABLE" if scheduled else "SCHEDULED_POLICY_ABSTAIN"
                row = {
                    "cut_ms": cut,
                    "closed_anchor_ms": cut - 1,
                    "symbol": symbol,
                    "strategy_state": state,
                    "candidate_id": None if candidate is None else candidate["intent_id"],
                    "native_slot_id": None if native is None else native["slot_id"],
                    "review_scheduled": scheduled,
                    "call_status": "NOT_CALLED",
                    "no_call_reason": no_call,
                    "model_decision": None,
                    "model_arm_economics": None,
                }
                encoded = canonical(row)
                fingerprint.update(encoded + b"\n")
                stream.write(encoded.decode() + "\n")
                count += 1
                states[state] += 1
                no_calls[no_call] += 1
                if scheduled:
                    scheduled_states[state] += 1
                    if candidate is not None:
                        scheduled_candidates.append(candidate["intent_id"])
    return {
        "rows": count,
        "native_decisions": len(decisions),
        "native_tape_sha256": stream_sha.hexdigest(),
        "denominator_sha256": fingerprint.hexdigest(),
        "states": dict(states),
        "no_call_reasons": dict(no_calls),
        "scheduled_states": dict(scheduled_states),
        "scheduled_candidates": scheduled_candidates,
        "required_sources_ready": False,
    }


def run_sim(workspace_root: Path, output_root: Path) -> dict[str, Any]:
    workspace, draft_path, source_plan_path = validate_paths(workspace_root, output_root)
    validate_pilot_plan(draft_path)
    draft_sha = hashlib.sha256(draft_path.read_bytes()).hexdigest()
    if draft_sha != FROZEN_PLAN_SHA256:
        raise ValueError("exact immutable pilot draft bytes required")
    source_plan = load_plan(source_plan_path)
    sources = installed_sources(source_plan, source_plan_path)
    protocol = sealed_protocol(source_plan)
    started = time.monotonic()
    deadline = started + MAX_WALL_SECONDS
    output_root.mkdir(exist_ok=False)
    write_json(output_root / "sealed-sim-plan.json", protocol)
    write_json(output_root / "before.json", {"actual_started_utc": utc_now(), "sources": sources})
    windows: dict[str, Any] = {}
    try:
        macro_root = workspace / "runtime" / "historical-macro-raw-20261007-a"
        macro = extract(
            macro_root / "alfred-cpiaucsl-vintages.raw",
            macro_root / "request.json",
            macro_root / "receipt.json",
        )
        write_json(output_root / "macro-semantics.json", asdict(macro))
        for episode, start, end, cut1, cut2, cache in EPISODES:
            _check_time(deadline)
            directory = output_root / episode
            directory.mkdir()
            bar_root, factor_root = _input_roots(workspace, cache)
            window = {"id": episode, "start": start, "end_exclusive": end}
            inputs = load_window(bar_root, factor_root, window)
            validate_replay_inputs(inputs, fixture_only=False, deadline=deadline)
            _market_summary(inputs)
            write_json(directory / "inputs.json", inputs.evidence)
            print(f"phase=native_strategy episode={episode}", flush=True)
            tape, counts = build_tape(inputs, directory, deadline)
            denominator = emit_denominator(inputs, directory, (cut1, cut2), deadline)
            if denominator["native_tape_sha256"] != counts["tape_sha256"]:
                raise ValueError("native tape/denominator fingerprint mismatch")
            if denominator["states"].get("UNAVAILABLE", 0):
                raise ValueError("unavailable native strategy cells forbid complete baseline economics")
            write_json(directory / "denominator-receipt.json", denominator)
            results = []
            for mode in protocol["entry_modes"]:
                for specification in protocol["cost_scenarios"]:
                    _check_time(deadline)
                    report, account = replay_tape(
                        inputs,
                        tape,
                        CostScenario(**specification),
                        mode,
                        protocol["baseline_latency_ms"],
                        admission_policy=COMMON_COST_RISK,
                        deadline=deadline,
                    )
                    label = f"{mode.lower()}-{specification['id']}"
                    write_json(directory / f"{label}.json", report)
                    write_json(
                        directory / f"{label}-ledger.json",
                        {"events": account.events, "trades": account.trades},
                    )
                    results.append(report)
            # Verify raw archives/checksums and normalized rows again, not only a caller digest.
            if load_window(bar_root, factor_root, window).evidence != inputs.evidence:
                raise ValueError("cached input source changed during SIM")
            windows[episode] = {"counts": counts, "denominator": denominator, "strategy_only": results}
            print(f"phase=episode_complete episode={episode}", flush=True)
        _check_time(deadline)
        if (
            hashlib.sha256(draft_path.read_bytes()).hexdigest() != draft_sha
            or installed_sources(load_plan(source_plan_path), source_plan_path) != sources
            or sealed_protocol(load_plan(source_plan_path)) != protocol
        ):
            raise ValueError("installed source or sealed protocol changed during SIM")
        result = {
            "schema": SCHEMA,
            "state": "PRICE_SIM_COMPLETED_PAID_MATCHED_AB_BLOCKED",
            "actual_finished_utc": utc_now(),
            "elapsed_seconds": time.monotonic() - started,
            "sealed_protocol_sha256": digest(protocol),
            "sources": sources,
            "episodes": windows,
            "denominator_rows": sum(w["denominator"]["rows"] for w in windows.values()),
            "review_arms": None,
            "review_blocker": "REQUIRED_NEWS_VERSIONS_AND_COVERAGE_UNADMITTED",
            "provider_calls": 0,
            "actual_provider_spend_usd": 0,
            "database_calls": 0,
            "network_calls": 0,
            "paid_matched_ab_executed": False,
            "source_authenticity_verified": False,
            "training_contamination_excluded": False,
            "complete_all_in_economics": False,
            "blind_campaign_credit": False,
            "readiness": protocol["readiness"],
        }
        write_json(output_root / "result.json", result)
        return result
    except BaseException as exc:
        write_json(
            output_root / "failure.json",
            {
                "schema": SCHEMA,
                "state": "FAILED_CLOSED",
                "error_type": type(exc).__name__,
                "completed_episodes": list(windows),
                "provider_calls": 0,
                "elapsed_seconds": time.monotonic() - started,
            },
        )
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_sim(args.workspace_root, args.output_root)
    print(
        json.dumps({k: result[k] for k in ("state", "elapsed_seconds", "denominator_rows", "provider_calls")})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
