"""One fixed, cache-only scenario/instant-entry abstention-consequence diagnostic.

Seen prices, conditional accounting and assumed clocks are not model, source,
venue or alpha qualification. No provider, credentials, DB or campaign paths.
"""

from __future__ import annotations

import argparse
import hashlib
import multiprocessing
import re
import time
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from kairos_strategy.provenance import candle_payload

from .baselines import baseline_identities
from .complex_strategy import HISTORY_BARS, fixed_complex_policy
from .engine import COMMON_COST_RISK, CostScenario, replay_tape
from .historical_inputs import validate_replay_inputs
from .historical_pilot_preflight import _utc_ms, validate_paths
from .inputs import UNIVERSE, WindowInputs, load_window
from .runner import canonical, digest, load_plan, source_receipt, utc_now, write_json
from .scenario_bridge import technical_scenario
from .scenarios import (
    MAX_OBSERVATIONS,
    MINUTE,
    POLICY_ID,
    TERMINAL,
    ScenarioEvidence,
    ScenarioObservation,
    evaluate_scenario,
)

SCHEMA = "kairos.scenario.price-comparison.v1"
START_MS = _utc_ms("2022-06-13T00:00:00Z")
END_MS = _utc_ms("2022-06-13T06:00:00Z")
MAX_WALL_SECONDS = 600
LATENCY_MS = 100
MARKET_SOURCE = "archive-bars-1m"
OUTPUT_NAME = re.compile(r"^scenario-comparison-[0-9]{8}-[a-z0-9-]+$")


def _check(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("600-second scenario comparison deadline reached")


def fixed_protocol(source_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "purpose": "SEEN_PRICE_ONLY_ABSTENTION_CONSEQUENCE_NOT_CONFIRMATION_ALPHA",
        "scenario_policy": POLICY_ID,
        "complex_policy": fixed_complex_policy(),
        "source_plan_sha256": digest(source_plan),
        "start_ms": START_MS,
        "end_exclusive_ms": END_MS,
        "roster_selection": "FIRST_SIX_UTC_HOURS_OF_ALREADY_SEEN_JUNE_13_NOT_PNL_SELECTION",
        "universe": list(UNIVERSE),
        "scheduled_5m_slots": 360,
        "full_1m_cells": 1800,
        "warmup_hours": 54,
        "exit_tail_hours": 3,
        "arms": ["immediate", "scenario"],
        "required_sources": [["MARKET", MARKET_SOURCE]],
        "scenario_requires_review": False,
        "receipt_clock_authority": "ARCHIVE_EVENT_TIME_PLUS_ASSUMPTIONS_NOT_LOCAL_HISTORICAL_RECEIPT",
        "creation_market_capture_ms": "CUT",
        "immediate_completion_ms": "CUT+100",
        "observation_ms": "CLOSED_MINUTE_END+1+100",
        "scenario_execution_completion_ms": "OBSERVATION+100",
        "native_expiry_and_exits_unchanged": True,
        "unsupported_trailing": "EXPLICIT_POLICY_ABSTENTION_PARENT_RETAINED_IN_A",
        "scenario_reset": "ONE_ATTEMPT_PER_DISTINCT_UNCHANGED_NATIVE_PARENT_NO_RETRY",
        "entry_modes": list(source_plan["entry_modes"]),
        "cost_scenarios": list(source_plan["cost_scenarios"]),
        "risk_policy": dict(source_plan["risk_policy"]),
        "admission_policy": COMMON_COST_RISK,
        "initial_equity_usd_each_arm": 10_000,
        "primary_statistic": "FULL_ACCOUNT_B_MINUS_A_END_EQUITY_NOT_SUM_OF_FILTERED_TRADES",
        "model_and_feed_costs": None,
        "complete_system_economics": None,
        "review_and_context_proposal_arms": "UNAVAILABLE_NOT_CALLED_NOT_ZERO_RETURN",
        "readiness": dict(source_plan["readiness"]),
        "workers": 1,
        "max_wall_seconds": MAX_WALL_SECONDS,
        "no_downloads": True,
        "no_paid_calls": True,
        "no_parameter_search": True,
        "no_blind_campaign_credit": True,
    }


def _market(bar: Any, captured_ms: int) -> ScenarioEvidence:
    return ScenarioEvidence(
        MARKET_SOURCE,
        "MARKET",
        bar.symbol,
        digest(candle_payload(bar)),
        bar.close_time_ms,
        captured_ms,
        captured_ms,
        MINUTE,
    )


def build_pairs(
    inputs: WindowInputs, directory: Path, source_sha256: str, deadline: float
) -> tuple[dict, dict, list[dict], dict]:
    """One actual native evaluation per slot; complete outcomes, never a winner subset."""
    tapes: dict[str, dict[int, list]] = {"immediate": {}, "scenario": {}}
    completions: dict[str, dict[str, int]] = {"immediate": {}, "scenario": {}}
    rows: list[dict] = []
    seen_parents: set[str] = set()
    states, reasons = Counter(), Counter()
    prefix_start = inputs.start_ms - HISTORY_BARS * MINUTE
    prefix_offset = (prefix_start - inputs.data_start_ms) // MINUTE
    if prefix_offset < 0 or inputs.start_ms % 300_000 or inputs.end_ms % 300_000:
        raise ValueError("exact 54h prefix and full five-minute schedule required")
    with (
        (directory / "pairs.jsonl").open("xb") as pairs,
        (directory / "scenarios.jsonl").open("xb") as journal,
    ):
        for cut in range(inputs.start_ms, inputs.end_ms, 300_000):
            for symbol in UNIVERSE:
                _check(deadline)
                end = (cut - inputs.data_start_ms) // MINUTE
                prefix = inputs.bars[symbol][prefix_offset:end]
                creation = (_market(prefix[-1], cut),)
                decision, preparation = technical_scenario(
                    prefix,
                    prefix_start_ms=prefix_start,
                    cut_ms=cut,
                    source_set_sha256=source_sha256,
                    context_sha256=digest([asdict(e) for e in creation]),
                    sources=creation,
                    required_sources=(("MARKET", MARKET_SOURCE),),
                )
                parent = decision.candidate
                if decision.symbol != symbol or decision.cut_ms != cut:
                    raise ValueError("native decision escaped the original scheduled cell")
                if parent is not None:
                    if parent.intent_id in seen_parents:
                        raise ValueError("same native parent cannot create another scenario attempt")
                    if parent.symbol != symbol or parent.entry_eligible_ts_ms != cut:
                        raise ValueError("native candidate escaped its original identity")
                    seen_parents.add(parent.intent_id)
                    tapes["immediate"].setdefault(cut, []).append(parent)
                    completions["immediate"][parent.intent_id] = cut + LATENCY_MS
                elif preparation.plan is not None:
                    raise ValueError("quiet native slot cannot manufacture a scenario")
                slot_id = digest(
                    {"cut_ms": cut, "symbol": symbol, "prefix": decision.expanding_prefix_sha256}
                )
                outcome, emitted, admitted = None, None, None
                if preparation.plan is not None:
                    plan = preparation.plan
                    if plan.template is not parent:
                        raise ValueError("scenario must retain the exact unchanged native parent")
                    observations: list[ScenarioObservation] = []
                    evaluations = evaluate_scenario(plan, (), require_review=False)
                    for offset in range(MAX_OBSERVATIONS):
                        _check(deadline)
                        index = end + offset
                        if index >= len(inputs.bars[symbol]):
                            raise ValueError("missing future scenario observation is not a quiet slot")
                        bar = inputs.bars[symbol][index]
                        observed = bar.close_time_ms + 1 + LATENCY_MS
                        observation = ScenarioObservation(bar, observed, (_market(bar, observed),))
                        observations.append(observation)
                        evaluations = evaluate_scenario(plan, tuple(observations), require_review=False)
                        if evaluations[-1].state in TERMINAL:
                            break
                    if evaluations[-1].state not in TERMINAL:
                        raise ValueError("bounded scenario did not reach a declared terminal outcome")
                    outcome = asdict(evaluations[-1])
                    emitted = evaluations[-1].candidate
                    if (
                        emitted is not None
                        and inputs.start_ms <= emitted.entry_eligible_ts_ms < inputs.end_ms
                    ):
                        admitted = emitted
                        tapes["scenario"].setdefault(admitted.entry_eligible_ts_ms, []).append(admitted)
                        completions["scenario"][admitted.intent_id] = evaluations[-1].observed_ms + LATENCY_MS
                    journal.write(
                        canonical(
                            {
                                "slot_id": slot_id,
                                "scenario_id": plan.scenario_id,
                                "plan": asdict(plan),
                                "observations": [asdict(o) for o in observations],
                                "evaluations": [dict(asdict(e), sha256=e.sha256) for e in evaluations],
                            }
                        )
                        + b"\n"
                    )
                row = {
                    "slot_id": slot_id,
                    "cut_ms": cut,
                    "symbol": symbol,
                    "decision": asdict(decision),
                    "preparation": asdict(preparation),
                    "scenario_supported": preparation.plan is not None,
                    "scenario_outcome": outcome,
                    "scenario_candidate_id": admitted.intent_id if admitted else None,
                    "scenario_emitted_candidate_id": emitted.intent_id if emitted else None,
                    "outside_entry_window": emitted is not None and admitted is None,
                    "model_review": "NOT_CALLED_UNAVAILABLE",
                    "complete_system_economics": None,
                }
                rows.append(row)
                states[decision.state] += 1
                reasons[outcome["reason"] if outcome else preparation.reason] += 1
                pairs.write(canonical(row) + b"\n")
                if len(rows) % 30 == 0:
                    print(f"phase=paired_native_slots slots={len(rows)}", flush=True)
    by_cell = {(r["cut_ms"], r["symbol"]): r for r in rows}
    expected = {(t, s) for t in range(inputs.start_ms, inputs.end_ms, 300_000) for s in UNIVERSE}
    if len(rows) != len(expected) or by_cell.keys() != expected:
        raise ValueError("complete scheduled denominator required")
    with (directory / "denominator.jsonl").open("xb") as stream:
        for cut in range(inputs.start_ms, inputs.end_ms, MINUTE):
            _check(deadline)
            for symbol in UNIVERSE:
                row = by_cell.get((cut, symbol))
                stream.write(
                    canonical(
                        {
                            "cut_ms": cut,
                            "symbol": symbol,
                            "slot_id": row["slot_id"] if row else None,
                            "state": row["decision"]["state"] if row else "NOT_SCHEDULED_NATIVE_CADENCE",
                            "review": "NOT_CALLED_UNAVAILABLE",
                            "model_economics": None,
                        }
                    )
                    + b"\n"
                )
    counts = {
        "scheduled_slots": len(rows),
        "full_minute_cells": (inputs.end_ms - inputs.start_ms) // MINUTE * len(UNIVERSE),
        "original_candidates": len(seen_parents),
        "supported_scenarios": sum(r["scenario_supported"] for r in rows),
        "scenario_candidates": len(completions["scenario"]),
        "outside_entry_window": sum(r["outside_entry_window"] for r in rows),
        "unavailable_slots": sum(
            r["decision"]["state"] == "UNAVAILABLE"
            or (r["scenario_outcome"] is not None and r["scenario_outcome"]["coverage"] == "UNAVAILABLE")
            for r in rows
        ),
        "native_states": dict(sorted(states.items())),
        "scenario_reasons": dict(sorted(reasons.items())),
    }
    return tapes, completions, rows, counts


def _index(rows: list[dict], key: str) -> dict[str, dict]:
    result = {r[key]: r for r in rows}
    if len(result) != len(rows):
        raise ValueError("duplicate economic identity")
    return result


def matching_audit(rows: list[dict], arms: dict[str, dict]) -> dict:
    """Account delta is primary; foregone-trade descriptions are not additive attribution."""
    a, b = arms["immediate"], arms["scenario"]
    complete = a["economic_results"] is not None and b["economic_results"] is not None
    a_entries = _index([e for e in a["events"] if e["kind"] == "ENTRY"], "intent_id")
    a_rejects = _index([e for e in a["events"] if e["kind"] == "REJECT"], "intent_id")
    a_trades = _index(a["trades"], "intent_id")
    b_entries = _index([e for e in b["events"] if e["kind"] == "ENTRY"], "intent_id")
    if set(a_entries) & set(a_rejects) or set(a_trades) - set(a_entries):
        raise ValueError("baseline execution identity conflict")
    parents = [r["decision"]["candidate"]["intent_id"] for r in rows if r["decision"]["candidate"]]
    if len(parents) != len(set(parents)):
        raise ValueError("duplicate matched parent")
    descriptions, counts = [], Counter()
    for row in rows:
        parent = row["decision"]["candidate"]
        if parent is None:
            continue
        identity = parent["intent_id"]
        trade = a_trades.get(identity)
        outcome = row["scenario_outcome"]
        available = row["decision"]["state"] != "UNAVAILABLE" and (
            outcome is None or outcome["coverage"] == "AVAILABLE"
        )
        excluded = row["scenario_candidate_id"] is None
        classification = (
            "UNKNOWN"
            if not complete or not available
            else "BASELINE_REJECTED"
            if identity in a_rejects
            else "BASELINE_NOT_FILLED"
            if identity not in a_entries
            else "BASELINE_OPEN_OR_UNRESOLVED"
            if trade is None
            else "MISSED_BASELINE_WINNER"
            if excluded and trade["net_pnl_usd"] > 0
            else "AVOIDED_BASELINE_LOSS"
            if excluded and trade["net_pnl_usd"] < 0
            else "OMITTED_BASELINE_FLAT"
            if excluded
            else "B_ENTERED"
            if row["scenario_candidate_id"] in b_entries
            else "B_CANDIDATE_NOT_EXECUTED"
        )
        subgroup = "SUPPORTED" if row["scenario_supported"] else "UNSUPPORTED_POLICY"
        counts[classification] += 1
        descriptions.append(
            {
                "slot_id": row["slot_id"],
                "parent_intent_id": identity,
                "scenario_candidate_id": row["scenario_candidate_id"],
                "subgroup": subgroup,
                "classification": classification,
                "baseline_closed_net_usd": trade["net_pnl_usd"] if trade else None,
                "scenario_reason": outcome["reason"] if outcome else row["preparation"]["reason"],
                "outside_entry_window": row["outside_entry_window"],
            }
        )
    return {
        "rows": descriptions,
        "counts": dict(sorted(counts.items())),
        "primary_account_delta_usd": b["economic_results"]["final_equity_usd"]
        - a["economic_results"]["final_equity_usd"]
        if complete
        else None,
        "complete_system_net_delta_usd": None,
        "attribution": "DESCRIPTIVE_MATCHED_A_OUTCOMES_NOT_SUMMABLE_CAUSAL_ACCOUNT_ATTRIBUTION",
    }


def run(workspace_root: Path, output_root: Path) -> dict:
    if not OUTPUT_NAME.fullmatch(output_root.name):
        raise ValueError("specifically named new scenario-comparison runtime child required")
    workspace, _, source_path = validate_paths(workspace_root, output_root)
    plan = load_plan(source_path)
    before = source_receipt(plan, source_path)
    checkout_modules = source_path.parent / "adaptive_replay"
    checkout_hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(checkout_modules.glob("*.py"))
    }
    if before["replay_modules_sha256"] != checkout_hashes:
        raise ValueError("non-editable installed replay wheel must match the exact checkout bytes")
    identities = baseline_identities()
    protocol = fixed_protocol(plan)
    started, actual_started = time.monotonic(), utc_now()
    deadline = started + MAX_WALL_SECONDS
    output_root.mkdir(exist_ok=False)
    write_json(output_root / "protocol.json", protocol)
    write_json(
        output_root / "before.json",
        {"sources": before, "native_identities": identities, "actual_started_utc": actual_started},
    )
    try:
        bars = workspace / "kairos-backtest" / "data" / "historical"
        factors = workspace / "kairos-backtest" / "data" / "historical-factors"
        window = {"id": "scenario_june13_six_hours", "start": "2022-06-13", "end_exclusive": "2022-06-14"}
        print("phase=offline_full_kline_integrity", flush=True)
        loaded = load_window(bars, factors, window)
        inputs = replace(loaded, start_ms=START_MS, end_ms=END_MS)
        validate_replay_inputs(inputs, fixture_only=False, deadline=deadline)
        write_json(
            output_root / "inputs.json",
            {"loaded_evidence": loaded.evidence, "scoring_start_ms": START_MS, "scoring_end_ms": END_MS},
        )
        tapes, completions, rows, counts = build_pairs(inputs, output_root, digest(before), deadline)
        if counts["scheduled_slots"] != 360 or counts["full_minute_cells"] != 1800:
            raise ValueError("all fixed source/scheduled cells must be retained")
        if counts["unavailable_slots"]:
            raise ValueError("unavailable causal slots prohibit complete account economics")
        economics = {}
        for cost_raw in protocol["cost_scenarios"]:
            scenario = CostScenario(**cost_raw)
            for mode in protocol["entry_modes"]:
                arms = {}
                for arm, tape in tapes.items():
                    _check(deadline)
                    print(f"phase=common_account arm={arm} cost={scenario.id} mode={mode}", flush=True)
                    report, account = replay_tape(
                        inputs,
                        tape,
                        scenario,
                        mode,
                        LATENCY_MS,
                        3,
                        admission_policy=COMMON_COST_RISK,
                        deadline=deadline,
                        completion_times_ms=completions[arm],
                    )
                    attempted = len(completions[arm])
                    entries = sum(e["kind"] == "ENTRY" for e in account.events)
                    rejects = sum(e["kind"] == "REJECT" for e in account.events)
                    if attempted != entries + rejects:
                        raise ValueError("all emitted attempts must reconcile with entry or rejection")
                    arms[arm] = {
                        "economic_results": report,
                        "events": account.events,
                        "trades": account.trades,
                    }
                name = f"{scenario.id}-{mode.lower()}"
                audit = matching_audit(rows, arms)
                write_json(output_root / f"{name}-accounts.json", arms)
                write_json(output_root / f"{name}-matched.json", audit)
                economics[name] = {
                    "accounts": {a: v["economic_results"] for a, v in arms.items()},
                    "matched_counts": audit["counts"],
                    "primary_account_delta_usd": audit["primary_account_delta_usd"],
                }
        _check(deadline)
        if load_window(bars, factors, window).evidence != loaded.evidence:
            raise ValueError("original archive bytes or normalized inputs changed during comparison")
        after = source_receipt(load_plan(source_path), source_path)
        if (
            before != after
            or identities != baseline_identities()
            or protocol != fixed_protocol(load_plan(source_path))
        ):
            raise ValueError("source, configuration, policy or dependency identity changed")
        _check(deadline)
        write_json(
            output_root / "after.json",
            {"sources": after, "actual_finished_utc": utc_now(), "source_receipt_unchanged": True},
        )
        file_hashes = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output_root.iterdir())
            if p.is_file()
        }
        result = {
            "schema": SCHEMA,
            "state": "COMPLETED_PRICE_ONLY_DIAGNOSTIC_NOT_QUALIFICATION",
            "actual_started_utc": actual_started,
            "actual_finished_utc": utc_now(),
            "elapsed_seconds": time.monotonic() - started,
            "protocol_sha256": digest(protocol),
            "files_sha256": file_hashes,
            "counts": counts,
            "conditional_trading_net_comparison": economics,
            "complete_system_economics": None,
            "llm_arms": "UNAVAILABLE_NOT_EXECUTED_NOT_ZERO_PNL",
            "model_feed_costs": None,
            "provider_calls": 0,
            "source_receipt_unchanged": True,
            "blind_campaign_credit": False,
            "readiness": protocol["readiness"],
        }
        _check(deadline)
        write_json(output_root / "result.json", result)
        return result
    except Exception as exc:
        write_json(
            output_root / "failure.json",
            {
                "state": "FAILED_CLOSED_ATTEMPT_RETAINED",
                "error_type": type(exc).__name__,
                "actual_finished_utc": utc_now(),
                "economic_results": None,
                "readiness": protocol["readiness"],
            },
        )
        raise


def _worker(workspace: Path, output: Path) -> None:
    result = run(workspace, output)
    print(f"state={result['state']} slots={result['counts']['scheduled_slots']} provider_calls=0", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if not OUTPUT_NAME.fullmatch(args.output_root.name):
        parser.error("specifically named new scenario-comparison runtime child required")
    validate_paths(args.workspace_root, args.output_root)
    # One child does all computation; this parent only enforces cancellation.
    process = multiprocessing.get_context("spawn").Process(
        target=_worker, args=(args.workspace_root, args.output_root)
    )
    process.start()
    limit = time.monotonic() + MAX_WALL_SECONDS
    while process.is_alive() and time.monotonic() < limit:
        process.join(timeout=1)
    if process.is_alive():
        process.terminate()
        process.join(timeout=10)
        if process.is_alive():
            process.kill()
            process.join(timeout=10)
        if process.is_alive():
            raise RuntimeError("own comparison worker cancellation unverified; evidence is not accepted")
        if args.output_root.is_dir():
            write_json(
                args.output_root / "hard-timeout.json",
                {"state": "FAILED_CLOSED_HARD_TIMEOUT_ATTEMPT_RETAINED", "economic_results": None},
            )
        raise SystemExit(1)
    raise SystemExit(process.exitcode or 0)


if __name__ == "__main__":
    main()
