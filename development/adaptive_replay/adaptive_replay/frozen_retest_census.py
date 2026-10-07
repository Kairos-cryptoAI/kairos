"""One bounded cached-data candidate census; no PnL, providers, or orders."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import re
import stat
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .complex_protocol import EPISODES, READINESS
from .engine import CostScenario, entry_time
from .frozen_retest import HISTORY_BARS, fixed_retest_policy, generate_frozen_retest
from .frozen_retest_entry import inspect_first_arrival
from .historical_context import canonical, digest
from .historical_inputs import validate_replay_inputs
from .historical_pilot_preflight import _input_roots, _market_summary
from .historical_pilot_sim import installed_sources
from .inputs import UNIVERSE, WindowInputs, load_window
from .runner import load_plan, utc_now, write_json
from .selection import reference_geometry

MAX_SECONDS = 300
OUTPUT_NAME = re.compile(r"^frozen-retest-census-[0-9]{8}-[a-z0-9-]+$")
REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def fixed_census_protocol() -> dict:
    return {
        "schema": "kairos.development.frozen-retest-census.v1",
        "purpose": "ALREADY_SEEN_CALENDAR_CANDIDATE_AND_GEOMETRY_DIAGNOSTIC_NOT_ALPHA",
        "strategy": fixed_retest_policy(),
        "episodes": [{"id": eid, "start": start, "end_exclusive": end} for eid, start, end, *_ in EPISODES],
        "universe": list(UNIVERSE),
        "roster": "EVERY_UTC_5M_CUT_IN_HALF_OPEN_WINDOWS_NOT_ONLY_TWENTY_PILOT_CELLS",
        "state_origin": "EXACT_WINDOW_START_MINUS_54H_ONE_EXPANDING_PREFIX_NO_ROLLING_RESET",
        "entry": "FIRST_STRICT_MINUTE_OPEN_AFTER_ASSUMED_100MS_COMPLETION_NO_RETRY",
        "assumed_completion_delay_ms": 100,
        "entry_lifetime_ms_new_identity_only": 300_000,
        "cost_scenarios": [
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
        ],
        "risk": {
            "per_trade_fraction": 0.0025,
            "aggregate_open_fraction": 0.01,
            "maximum_symbol_notional_fraction": 0.25,
            "maximum_leverage": 1,
        },
        "sizing": "10000_USD_REFERENCE_ONLY_NO_ACCOUNT_ALLOCATION_OR_SIMULATED_POSITIONS",
        "geometry_is_not": [
            "REAL_FILL",
            "EXPECTED_VALUE",
            "CLOSED_TRADE",
            "SOURCE_AUTHENTICITY",
            "ALPHA_PASS",
        ],
        "provider_calls": 0,
        "economics_executed": False,
        "required_news_macro_ready": False,
        "source_authenticity_admitted": False,
        "fresh_owner_confirmation_for_model_test": False,
        "native_compact_trial15_v5_plans_changed": False,
        "blind_campaign_credit": False,
        "parameter_search": False,
        "new_downloads": False,
        "max_wall_seconds": MAX_SECONDS,
        "workers": 1,
        "readiness": dict(READINESS),
    }


def validate_paths(workspace_root: Path, output_root: Path) -> Path:
    if not workspace_root.is_absolute() or not output_root.is_absolute():
        raise ValueError("absolute workspace/output paths required")
    workspace = workspace_root.resolve(strict=True)
    if output_root.parent != workspace / "runtime" or not OUTPUT_NAME.fullmatch(output_root.name):
        raise ValueError("specifically named direct runtime child required")
    for path in (*reversed(output_root.parents), output_root, workspace_root):
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            continue
        if path.is_symlink() or getattr(metadata, "st_file_attributes", 0) & REPARSE:
            raise ValueError("symlink/junction output forbidden")
    if output_root.exists():
        raise FileExistsError("old attempts and receipts are immutable; no overwrite/retry")
    if not (workspace / "kairos" / "development" / "adaptive_replay" / "plan.json").is_file():
        raise ValueError("Kairos immutable dependency plan required")
    return workspace


def _check(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("bounded frozen-retest census deadline reached")


def diagnose_symbol(
    inputs: WindowInputs, symbol: str, scenarios: tuple[CostScenario, ...], deadline: float
) -> tuple[list[dict], dict]:
    """Count complete five-minute outcomes; never simulate exits or select returns."""
    _check(deadline)
    if symbol not in UNIVERSE or not scenarios or len({s.id for s in scenarios}) != len(scenarios):
        raise ValueError("fixed universe and distinct geometry scenarios required")
    origin = inputs.start_ms - HISTORY_BARS * 60_000
    source = inputs.bars[symbol]
    prefix = tuple(row for row in source if origin <= row.open_time_ms < inputs.end_ms)
    generated = generate_frozen_retest(prefix, origin_ms=origin, deadline=deadline)
    decisions = tuple(row for row in generated if inputs.start_ms <= row.cut_ms < inputs.end_ms)
    expected = tuple(range(inputs.start_ms, inputs.end_ms, 300_000))
    if tuple(row.cut_ms for row in decisions) != expected:
        raise ValueError("complete ordered five-minute roster required; no sparse-cell inference")
    opens = {row.open_time_ms: row.open for row in source}
    days = {datetime.fromtimestamp(cut / 1000, UTC).date().isoformat(): 0 for cut in expected}
    records, reference, arrival = (
        [],
        {s.id: Counter() for s in scenarios},
        {s.id: Counter() for s in scenarios},
    )
    arrival_days = {s.id: dict(days) for s in scenarios}
    no_quote = 0
    seen_ids: set[str] = set()
    for row in decisions:
        _check(deadline)
        geometries = {}
        if row.candidate is not None:
            candidate = row.candidate
            if candidate.intent_id in seen_ids:
                raise ValueError("same-event candidate duplicate forbidden")
            seen_ids.add(candidate.intent_id)
            day = datetime.fromtimestamp(row.cut_ms / 1000, UTC).date().isoformat()
            days[day] += 1
            completion = candidate.decision_ts_ms + 100
            quote = entry_time(candidate, completion, "STRICT_MINUTE_OPEN")
            if quote is None or quote not in opens:
                no_quote += 1
            for scenario in scenarios:
                ref = reference_geometry(candidate, scenario)
                reference[scenario.id][ref["reason"]] += 1
                entry = None
                if quote is not None and quote in opens:
                    closed = tuple(c for c in source if origin <= c.open_time_ms < quote)
                    entry = inspect_first_arrival(
                        candidate,
                        closed,
                        completion_ms=completion,
                        quote_ms=quote,
                        quote_open=opens[quote],
                        scenario=scenario,
                    )
                    arrival[scenario.id][entry["reason"]] += 1
                    if entry["geometry_feasible"]:
                        arrival_days[scenario.id][day] += 1
                else:
                    arrival[scenario.id]["FIRST_QUOTE_UNAVAILABLE"] += 1
                geometries[scenario.id] = {"reference": ref, "first_arrival": entry}
        records.append({"technical": asdict(row), "geometries": geometries})
    counts = {
        "scheduled_slots": len(records),
        "state_counts": dict(sorted(Counter(row.state for row in decisions).items())),
        "reason_counts": dict(sorted(Counter(row.reason for row in decisions).items())),
        "transition_counts": dict(sorted(Counter(row.transition for row in decisions).items())),
        "defense_counts": dict(sorted(Counter(row.defense for row in decisions).items())),
        "breakouts_armed": sum(row.transition == "IDLE_TO_ARMED" for row in decisions),
        "structural_reclaims_consumed": sum(
            row.transition == "RECLAIM_CONSUMED_NO_RETRY" for row in decisions
        ),
        "raw_candidates_after_fixed_base_hurdle": len(seen_ids),
        "candidates_each_utc_day": days,
        "no_first_quote_at_assumed_100ms": no_quote,
        "scenarios": {
            s.id: {
                "planning_round_trip_bps": s.costs.estimated_round_trip_bps,
                "reference_geometry_reasons": dict(sorted(reference[s.id].items())),
                "reference_geometry_feasible": reference[s.id]["accepted"],
                "first_arrival_reasons": dict(sorted(arrival[s.id].items())),
                "first_arrival_geometry_feasible": arrival[s.id]["GEOMETRY_FEASIBLE_ONLY"],
                "first_arrival_feasible_each_utc_day": arrival_days[s.id],
            }
            for s in scenarios
        },
    }
    return records, counts


def census(workspace_root: Path, output_root: Path) -> dict:
    workspace = validate_paths(workspace_root, output_root)
    started, actual_started = time.monotonic(), utc_now()
    deadline = started + MAX_SECONDS
    source_path = workspace / "kairos" / "development" / "adaptive_replay" / "plan.json"
    base_plan = load_plan(source_path)
    before = installed_sources(base_plan, source_path)
    protocol = fixed_census_protocol()
    if base_plan["cost_scenarios"] != protocol["cost_scenarios"]:
        raise ValueError("fixed base/stress assumptions cannot change")
    scenarios = tuple(CostScenario(**value) for value in protocol["cost_scenarios"])
    output_root.mkdir(exist_ok=False)
    write_json(output_root / "protocol.json", protocol)
    write_json(
        output_root / "before.json",
        {"sources": before, "actual_started_utc": actual_started, "protocol_sha256": digest(protocol)},
    )
    total_slots, tape_sha, counts = 0, hashlib.sha256(), {}
    try:
        with (output_root / "decisions.jsonl.gz").open("xb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as stream:
                for eid, start, end, _, cache_kind in EPISODES:
                    _check(deadline)
                    bars, factors = _input_roots(workspace, cache_kind)
                    window = {"id": eid, "start": start, "end_exclusive": end}
                    inputs = load_window(bars, factors, window)
                    validate_replay_inputs(inputs, fixture_only=False, deadline=deadline)
                    market = _market_summary(inputs)
                    write_json(
                        output_root / f"{eid}-inputs.json", {"market": market, "evidence": inputs.evidence}
                    )
                    counts[eid] = {}
                    for symbol in UNIVERSE:
                        records, count = diagnose_symbol(inputs, symbol, scenarios, deadline)
                        counts[eid][symbol] = count
                        for record in records:
                            _check(deadline)
                            encoded = (
                                canonical({"episode": eid, "symbol": symbol, **record}) + "\n"
                            ).encode()
                            tape_sha.update(encoded)
                            stream.write(encoded)
                            total_slots += 1
                        print(
                            f"phase=symbol_complete episode={eid} symbol={symbol} "
                            f"slots={count['scheduled_slots']} "
                            f"candidates={count['raw_candidates_after_fixed_base_hurdle']}",
                            flush=True,
                        )
                    if load_window(bars, factors, window).evidence != inputs.evidence:
                        raise ValueError("original archive checksums/normalized market inputs changed")
        after = installed_sources(load_plan(source_path), source_path)
        if before != after or fixed_census_protocol() != protocol:
            raise ValueError("source modules, locks, native identities or fixed protocol changed")
        _check(deadline)
        write_json(
            output_root / "after.json",
            {"sources": after, "source_receipt_unchanged": True, "actual_finished_utc": utc_now()},
        )
        result = {
            "schema": protocol["schema"],
            "state": "OFFLINE_CANDIDATE_GEOMETRY_DIAGNOSTIC_COMPLETED_NOT_QUALIFICATION",
            "actual_started_utc": actual_started,
            "actual_finished_utc": utc_now(),
            "elapsed_seconds": time.monotonic() - started,
            "protocol_sha256": digest(protocol),
            "source_receipt_unchanged": True,
            "complete_scheduled_slots": total_slots,
            "decisions_canonical_jsonl_sha256": tape_sha.hexdigest(),
            "decisions_gzip_sha256": hashlib.sha256(
                (output_root / "decisions.jsonl.gz").read_bytes()
            ).hexdigest(),
            "episodes": counts,
            "provider_calls": 0,
            "provider_cost_usd": 0,
            "required_news_macro_ready": False,
            "source_authenticity_admitted": False,
            "model_execution_admitted": False,
            "economics_executed": False,
            "economic_result": None,
            "blind_campaign_credit": False,
            "readiness": dict(READINESS),
        }
        write_json(output_root / "result.json", result)
        return result
    except Exception as exc:
        write_json(
            output_root / "failure.json",
            {
                "state": "FAILED_CLOSED_ATTEMPT_RETAINED",
                "error_type": type(exc).__name__,
                "actual_finished_utc": utc_now(),
                "provider_calls": 0,
                "readiness": dict(READINESS),
            },
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    result = census(args.workspace_root, args.output_root)
    print(f"state={result['state']} slots={result['complete_scheduled_slots']} provider_calls=0", flush=True)


if __name__ == "__main__":
    main()
