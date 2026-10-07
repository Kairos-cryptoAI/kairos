"""One predeclared cached-data reversal/control OHLC diagnostic, never alpha.

All windows, symbols, quiet slots, rejected candidates and both cost assumptions
are retained. No model, feed, exchange, order, production DB or campaign API is
available on this path. Failures and partial attempts are immutable evidence.
"""

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

from kairos_backtest.cost_risk import RiskLimits, size_and_admit
from kairos_core.enums import Side
from kairos_strategy.models import SleeveIntent
from kairos_strategy.sleeves import TrendBreakoutConfig

from .baselines import _ids_through, _invoke, _validate_candidate, baseline_identities
from .complex_protocol import READINESS
from .engine import COMMON_COST_RISK, CostScenario, entry_time, fill_price, replay_tape
from .failed_reversal import HISTORY_BARS, STRATEGY_ID, fixed_reversal_policy, generate_failed_reversal
from .failed_reversal_entry import inspect_first_arrivals
from .historical_context import canonical, digest
from .historical_inputs import validate_replay_inputs
from .historical_pilot_preflight import _input_roots
from .historical_pilot_sim import installed_sources
from .historical_replay import _validate_candidate as validate_intent
from .inputs import FUNDING_INTERVAL_MS, UNIVERSE, WindowInputs, load_window
from .runner import load_plan, utc_now, write_json
from .selection import reference_geometry

CONTROL_ID = "trend_breakout_v1"
ARMS = (STRATEGY_ID, CONTROL_ID)
MAX_SECONDS = 600
OUTPUT_NAME = re.compile(r"^reversal-search-[0-9]{8}-[a-z0-9-]+$")
REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
MAX_UNCOMPRESSED_TAPE_BYTES = 128 * 1024 * 1024
WINDOWS = (
    ("late_2021", "2021-11-07", "2021-11-10", "original"),
    ("early_2022", "2022-02-05", "2022-02-08", "original"),
    ("may_2022", "2022-05-09", "2022-05-12", "original"),
    ("june_2022", "2022-06-13", "2022-06-16", "original"),
    ("episode_a", "2021-05-17", "2021-05-22", "may"),
    ("episode_d", "2024-01-08", "2024-01-13", "original"),
)


def fixed_search_protocol() -> dict:
    return {
        "schema": "kairos.development.failed-reversal-search.v1",
        "purpose": "ALREADY_SEEN_CALENDAR_OHLC_DIAGNOSTIC_NOT_ALPHA_OR_CHAMPION_SELECTION",
        "challenger": fixed_reversal_policy(),
        "control": {"id": CONTROL_ID, "config": asdict(TrendBreakoutConfig()), "modified": False},
        "windows": [
            {"id": wid, "start": start, "end_exclusive": end, "cache_kind": cache}
            for wid, start, end, cache in WINDOWS
        ],
        "universe": list(UNIVERSE),
        "roster": "EVERY_UTC_5M_CUT_AND_SYMBOL_IN_ALL_HALF_OPEN_WINDOWS_BOTH_ARMS",
        "expected_slots_each_arm": 31_680,
        "state_origin": "EXACT_WINDOW_START_MINUS_54H_EXPANDING_PREFIX_NO_ROLLING_RESET",
        "causal_prefix_check": "BOTH_ARMS_FULL_VS_EXACT_24H_PREFIX_ALL_SYMBOLS_ALL_PRIOR_CUTS",
        "entry_mode": "STRICT_MINUTE_OPEN",
        "assumed_completion_delay_ms": 100,
        "entry": "FIRST_STRICT_MINUTE_OPEN_AFTER_COMPLETION_NEVER_RETRY_OR_MOVE_ORIGINAL_BARRIERS",
        "common_prearrival_cancellation": "CLOSED_INTERMEDIATE_1M_STOP_OR_TARGET_TOUCH_CANCELS",
        "challenger_arrival": "SOURCE_BOUND_EVENT_GEOMETRY_NATIVE_CRASH_GUARD_PRICE_INSIDE_CHANNEL",
        "control_arrival": "NATIVE_INTENT_UNCHANGED_NO_NEW_REVERSAL_CHANNEL_OR_ATR_FILTER",
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
        "geometry": {
            "minimum_net_reward_risk": 1.25,
            "minimum_stop_bps": 10,
            "maximum_stop_bps": 300,
            "cost_not_above_gross_stop_fraction": 0.5,
            "reference_geometry_account_usd": 10_000,
            "atr_multiple_filter_on_independent_or_native_candidate": False,
        },
        "risk": {
            "per_trade_fraction": 0.0025,
            "aggregate_open_fraction": 0.01,
            "maximum_symbol_notional_fraction": 0.25,
            "maximum_leverage": 1,
        },
        "accounts": "SEPARATE_SHARED_FIVE_SYMBOL_10000_USD_ACCOUNTS_EACH_ARM_WINDOW_COST_NO_COMPOUND",
        "simultaneous_order": "FIXED_UNIVERSE_ORDER_NO_LONG_SHORT_RISK_NETTING",
        "exit_tail_hours": 3,
        "ohlc_execution": "CONDITIONAL_FULL_FILL_SL_FIRST_AMBIGUITY_ADVERSE_STOP_GAPS_NO_TICK_PATH",
        "funding": "ARCHIVE_CALC_TIME_ENTITLEMENT_AND_CANDLE_OPEN_PROXY_NOT_VENUE_SETTLEMENT",
        "mark_overrun": "REPORT_ACTUAL_MARK_RISK_GROSS_OVERRUN_AND_LOSS_OVER_RESERVATION_NEVER_CLAMP",
        "no_forced_settlement": True,
        "standalone_positive_pnl_is_not": "NECESSARY_OR_SUFFICIENT_FOR_FUTURE_MATCHED_LLM_REVIEW_VALUE",
        "predeclared_interpretation": [
            "ZERO_GEOMETRY_FEASIBLE_CANDIDATES_CANNOT_TEST_REVIEW_VALUE",
            "NONZERO_GEOMETRY_ONLY_ESTABLISHES_TESTABLE_CANDIDATES_NOT_ALPHA",
            "NEGATIVE_REFERENCE_RETURN_IS_REPORTED_NOT_HIDDEN_OR_AUTOMATICALLY_RESCUED_BY_LLM",
            "NO_RETUNING_AFTER_THIS_RUN_NO_AUTOMATIC_WINNER_OR_STACK_INTEGRATION",
        ],
        "natural_frequency_quota": None,
        "parameter_search": False,
        "new_downloads": False,
        "workers": 1,
        "max_wall_seconds": MAX_SECONDS,
        "provider_calls": 0,
        "news_macro_context": "UNAVAILABLE_NOT_SYNTHESIZED",
        "complete_system_economics": False,
        "source_authenticity_admitted": False,
        "fresh_owner_confirmation_for_model_test": False,
        "blind_campaign_credit": False,
        "native_compact_trial15_v5_plans_changed": False,
        "readiness": dict(READINESS),
    }


def _check(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("bounded fixed reversal search deadline reached")


def _market_summary(inputs: WindowInputs) -> dict:
    """Post-validation coverage receipt derived from THIS exact full horizon.

    Unlike the immutable old five-day pilot reporter, this path has both three-
    and five-day score windows. The loader and validate_replay_inputs still
    enforce every original archive checksum, typed row, anchor and 8h bucket.
    """
    expected_bars = (inputs.data_end_ms - inputs.data_start_ms) // 60_000
    first_funding = (
        (inputs.data_start_ms + FUNDING_INTERVAL_MS - 1) // FUNDING_INTERVAL_MS
    ) * FUNDING_INTERVAL_MS
    expected_funding = len(range(first_funding, inputs.data_end_ms, FUNDING_INTERVAL_MS))
    if expected_bars <= 0 or (inputs.data_end_ms - inputs.data_start_ms) % 60_000:
        raise ValueError("complete positive minute data horizon required")
    summary = {
        symbol: {
            "bars": len(inputs.bars[symbol]),
            "funding": len(inputs.funding[symbol]),
            "gaps": inputs.evidence["bars"][symbol]["gaps"],
            "bar_rows_sha256": inputs.evidence["bars"][symbol]["normalized_rows_sha256"],
            "funding_rows_sha256": inputs.evidence["funding"][symbol]["normalized_rows_sha256"],
        }
        for symbol in UNIVERSE
    }
    if any(
        item["bars"] != expected_bars or item["funding"] != expected_funding or item["gaps"] != 0
        for item in summary.values()
    ):
        raise ValueError("exact complete bar/funding horizon required, never sparse pilot inputs")
    return summary


def validate_paths(workspace_root: Path, output_root: Path) -> Path:
    if not workspace_root.is_absolute() or not output_root.is_absolute():
        raise ValueError("absolute workspace/output paths required")
    workspace = workspace_root.resolve(strict=True)
    if output_root.parent != workspace / "runtime" or not OUTPUT_NAME.fullmatch(output_root.name):
        raise ValueError("specifically named direct runtime child required")
    for path in (*reversed(output_root.parents), output_root, workspace_root):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if path.is_symlink() or getattr(info, "st_file_attributes", 0) & REPARSE:
            raise ValueError("symlink/junction output forbidden")
    if output_root.exists():
        raise FileExistsError("attempts are immutable: no overwrite or automatic retry")
    if not (workspace / "kairos" / "development" / "adaptive_replay" / "plan.json").is_file():
        raise ValueError("immutable Kairos dependency plan required")
    return workspace


def _control(prefix, inputs: WindowInputs, symbol: str, deadline: float) -> dict[int, SleeveIntent]:
    config = TrendBreakoutConfig()
    full = _invoke(CONTROL_ID, list(prefix), config, deadline, symbol, "full_prefix")
    cut = inputs.start_ms + 86_400_000
    at_cut = _invoke(
        CONTROL_ID,
        [row for row in prefix if row.open_time_ms < cut],
        config,
        deadline,
        symbol,
        "exact_24h_prefix",
    )
    if _ids_through(full, cut) != _ids_through(at_cut, cut):
        raise ValueError("unchanged control prefix causality violation")
    result = {}
    for intent in full:
        validate_intent(intent)
        if intent.symbol != symbol:
            raise ValueError("control symbol/input mismatch")
        if not _validate_candidate(intent, CONTROL_ID, inputs.start_ms, inputs.end_ms):
            continue
        if intent.entry_eligible_ts_ms in result:
            raise ValueError("control duplicates a symbol/cut slot")
        result[intent.entry_eligible_ts_ms] = intent
    return result


def _control_arrivals(candidate, closed, completion, quote, price, scenarios) -> dict[str, dict]:
    """Unmodified native candidate, common first-quote barriers/costs only."""
    if quote != entry_time(candidate, completion, "STRICT_MINUTE_OPEN"):
        raise ValueError("control must use its first strict quote, not a later retry")
    stop, target = candidate.exit_plan.stop_price, candidate.exit_plan.target_price
    crossed = any(
        (row.low <= stop or row.high >= target)
        if candidate.side is Side.LONG
        else (row.high >= stop or row.low <= target)
        for row in closed
        if row.open_time_ms > candidate.decision_ts_ms
    )
    results = {}
    for scenario in scenarios:
        entry = fill_price(price, candidate.side, True, scenario)
        decision = size_and_admit(
            side=candidate.side,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            equity_usd=10_000,
            costs=scenario.costs,
            limits=RiskLimits(maximum_stop_distance_bps=300),
        )
        if crossed:
            reason = "FROZEN_BARRIER_TOUCHED_BEFORE_ARRIVAL"
        elif not decision.accepted:
            reason = str(decision.reason)
        elif scenario.costs.estimated_round_trip_bps > 0.5 * decision.stop_distance_bps:
            reason = "INSUFFICIENT_COST_HEADROOM"
        else:
            reason = "GEOMETRY_FEASIBLE_ONLY"
        results[scenario.id] = {
            "intent_id": candidate.intent_id,
            "quote_ms": quote,
            "completion_ms": completion,
            "minute_open_price": price,
            "modeled_entry_price": entry,
            "scenario": scenario.id,
            "planning_round_trip_bps": scenario.costs.estimated_round_trip_bps,
            "original_stop_price": stop,
            "original_target_price": target,
            "stop_distance_bps": decision.stop_distance_bps,
            "net_reward_to_risk": decision.net_reward_to_risk,
            "geometry_feasible": reason == "GEOMETRY_FEASIBLE_ONLY",
            "reason": reason,
            "source_authenticity_admitted": False,
            "observed_bbo_or_fill": False,
            "trading_admitted": False,
        }
    return results


def diagnose_symbol(inputs: WindowInputs, symbol: str, scenarios: tuple[CostScenario, ...], deadline: float):
    """Generate all raw states once; independently retain reference and arrival refusals."""
    _check(deadline)
    if symbol not in UNIVERSE:
        raise ValueError("fixed universe symbol required")
    origin = inputs.start_ms - HISTORY_BARS * 60_000
    source = inputs.bars[symbol]
    prefix = tuple(row for row in source if origin <= row.open_time_ms < inputs.end_ms)
    if not prefix or prefix[0].open_time_ms != origin or prefix[-1].close_time_ms != inputs.end_ms - 1:
        raise ValueError("exact contiguous expanding input prefix required")
    generated = generate_failed_reversal(prefix, origin_ms=origin, deadline=deadline)
    check_cut = inputs.start_ms + 86_400_000
    at_cut = generate_failed_reversal(
        tuple(row for row in prefix if row.open_time_ms < check_cut), origin_ms=origin, deadline=deadline
    )
    if tuple(row for row in generated if row.cut_ms <= check_cut) != at_cut:
        raise ValueError("challenger full state/history prefix causality violation")
    decisions = {row.cut_ms: row for row in generated if inputs.start_ms <= row.cut_ms < inputs.end_ms}
    expected = tuple(range(inputs.start_ms, inputs.end_ms, 300_000))
    if tuple(decisions) != expected:
        raise ValueError("complete ordered five-minute challenger roster required")
    control = _control(prefix, inputs, symbol, deadline)
    opens = {row.open_time_ms: row.open for row in source}
    days = {datetime.fromtimestamp(cut / 1000, UTC).date().isoformat(): 0 for cut in expected}
    records, counts = [], {}
    tapes = {arm: {s.id: {} for s in scenarios} for arm in ARMS}
    for arm in ARMS:
        reference = {s.id: Counter() for s in scenarios}
        arrival = {s.id: Counter() for s in scenarios}
        feasible_reference = Counter()
        candidate_days, arrival_days = dict(days), {s.id: dict(days) for s in scenarios}
        seen_ids = set()
        for cut in expected:
            _check(deadline)
            candidate = decisions[cut].candidate if arm == STRATEGY_ID else control.get(cut)
            geometries = {}
            if candidate is not None:
                if candidate.intent_id in seen_ids:
                    raise ValueError("consumed-event duplicate candidate forbidden")
                seen_ids.add(candidate.intent_id)
                day = datetime.fromtimestamp(cut / 1000, UTC).date().isoformat()
                candidate_days[day] += 1
                completion = candidate.decision_ts_ms + 100
                quote = entry_time(candidate, completion, "STRICT_MINUTE_OPEN")
                entries = {}
                if quote is not None and quote in opens:
                    closed = tuple(row for row in source if origin <= row.open_time_ms < quote)
                    entries = (
                        inspect_first_arrivals(
                            candidate,
                            closed,
                            completion_ms=completion,
                            quote_ms=quote,
                            quote_open=opens[quote],
                            scenarios=scenarios,
                            deadline=deadline,
                        )
                        if arm == STRATEGY_ID
                        else _control_arrivals(candidate, closed, completion, quote, opens[quote], scenarios)
                    )
                for scenario in scenarios:
                    ref = reference_geometry(candidate, scenario)
                    reference[scenario.id][ref["reason"]] += 1
                    feasible_reference[scenario.id] += ref["reference_feasible"]
                    entry = entries.get(scenario.id)
                    reason = "FIRST_QUOTE_UNAVAILABLE_OR_EXPIRED" if entry is None else entry["reason"]
                    arrival[scenario.id][reason] += 1
                    if entry is not None and entry["geometry_feasible"]:
                        arrival_days[scenario.id][day] += 1
                        tapes[arm][scenario.id].setdefault(cut, []).append(candidate)
                    geometries[scenario.id] = {"reference": ref, "first_arrival": entry}
            records.append(
                {
                    "arm": arm,
                    "symbol": symbol,
                    "cut_ms": cut,
                    "technical": asdict(decisions[cut])
                    if arm == STRATEGY_ID
                    else {
                        "status": "CANDIDATE" if candidate is not None else "NO_CANDIDATE_REPORTED",
                        "intent": None if candidate is None else asdict(candidate),
                        "native_quiet_reason": "NOT_EXPOSED_BY_REGISTERED_GENERATOR",
                    },
                    "geometries": geometries,
                }
            )
        counts[arm] = {
            "scheduled_slots": len(expected),
            "raw_candidates": len(seen_ids),
            "no_candidate_slots": len(expected) - len(seen_ids),
            "candidates_each_utc_day": candidate_days,
            "verified_prefix_cut_ms": check_cut,
            "scenarios": {
                s.id: {
                    "planning_round_trip_bps": s.costs.estimated_round_trip_bps,
                    "reference_geometry_reasons": dict(sorted(reference[s.id].items())),
                    "reference_geometry_feasible": feasible_reference[s.id],
                    "first_arrival_reasons": dict(sorted(arrival[s.id].items())),
                    "first_arrival_geometry_feasible": arrival[s.id]["GEOMETRY_FEASIBLE_ONLY"],
                    "first_arrival_feasible_each_utc_day": arrival_days[s.id],
                }
                for s in scenarios
            },
        }
        if arm == STRATEGY_ID:
            states = tuple(decisions.values())
            counts[arm].update(
                {
                    "state_counts": dict(sorted(Counter(row.state for row in states).items())),
                    "reason_counts": dict(sorted(Counter(row.reason for row in states).items())),
                    "transition_counts": dict(sorted(Counter(row.transition for row in states).items())),
                    "defense_counts": dict(sorted(Counter(row.defense for row in states).items())),
                    "consumed_event_slots": sum(
                        row.consumed
                        and row.transition != "WAIT_RESET_HOLD"
                        and row.transition != "WAIT_RESET_TO_IDLE_RESET_ONLY"
                        for row in states
                    ),
                }
            )
    return records, counts, tapes


def search(workspace_root: Path, output_root: Path) -> dict:
    workspace = validate_paths(workspace_root, output_root)
    started, actual_started = time.monotonic(), utc_now()
    deadline = started + MAX_SECONDS
    source_path = workspace / "kairos" / "development" / "adaptive_replay" / "plan.json"
    base = load_plan(source_path)
    before = installed_sources(base, source_path)
    protocol, identities = fixed_search_protocol(), baseline_identities()
    if base["cost_scenarios"] != protocol["cost_scenarios"]:
        raise ValueError("frozen common base/stress assumptions changed")
    scenarios = tuple(CostScenario(**row) for row in protocol["cost_scenarios"])
    output_root.mkdir(exist_ok=False)
    write_json(output_root / "protocol.json", protocol)
    write_json(
        output_root / "before.json",
        {
            "sources": before,
            "native_control_identity": identities[CONTROL_ID],
            "actual_started_utc": actual_started,
            "protocol_sha256": digest(protocol),
        },
    )
    counts, economics = {}, {}
    slots, encoded_bytes, tape_sha = 0, 0, hashlib.sha256()
    try:
        with (output_root / "decisions.jsonl.gz").open("xb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as stream:
                for wid, start, end, cache_kind in WINDOWS:
                    _check(deadline)
                    bars, factors = _input_roots(workspace, cache_kind)
                    window = {"id": wid, "start": start, "end_exclusive": end}
                    inputs = load_window(bars, factors, window)
                    validate_replay_inputs(inputs, fixture_only=False, deadline=deadline)
                    write_json(
                        output_root / f"{wid}-inputs.json",
                        {"market": _market_summary(inputs), "evidence": inputs.evidence},
                    )
                    counts[wid] = {}
                    tapes = {arm: {s.id: {} for s in scenarios} for arm in ARMS}
                    for symbol in UNIVERSE:
                        records, count, per_symbol = diagnose_symbol(inputs, symbol, scenarios, deadline)
                        counts[wid][symbol] = count
                        for record in records:
                            encoded = (canonical({"window": wid, **record}) + "\n").encode()
                            encoded_bytes += len(encoded)
                            if encoded_bytes > MAX_UNCOMPRESSED_TAPE_BYTES:
                                raise ValueError("bounded complete tape exceeded storage ceiling")
                            tape_sha.update(encoded)
                            stream.write(encoded)
                            slots += 1
                        for arm in ARMS:
                            for scenario in scenarios:
                                for cut, candidates in per_symbol[arm][scenario.id].items():
                                    tapes[arm][scenario.id].setdefault(cut, []).extend(candidates)
                        print(
                            f"phase=symbol_complete window={wid} symbol={symbol} "
                            f"challenger={count[STRATEGY_ID]['raw_candidates']} "
                            f"control={count[CONTROL_ID]['raw_candidates']}",
                            flush=True,
                        )
                    economics[wid], ledgers = {}, {}
                    for arm in ARMS:
                        economics[wid][arm], ledgers[arm] = {}, {}
                        for scenario in scenarios:
                            _check(deadline)
                            tape = tapes[arm][scenario.id]
                            for candidates in tape.values():
                                candidates.sort(key=lambda i: (UNIVERSE.index(i.symbol), i.intent_id))
                            report, account = replay_tape(
                                inputs,
                                tape,
                                scenario,
                                "STRICT_MINUTE_OPEN",
                                100,
                                3,
                                admission_policy=COMMON_COST_RISK,
                                deadline=deadline,
                            )
                            total_raw = sum(counts[wid][s][arm]["raw_candidates"] for s in UNIVERSE)
                            total_geometric = sum(
                                counts[wid][s][arm]["scenarios"][scenario.id][
                                    "first_arrival_geometry_feasible"
                                ]
                                for s in UNIVERSE
                            )
                            entries = sum(report["entries_each_utc_day"].values())
                            if total_geometric != entries + sum(account.rejections.values()):
                                raise ValueError(
                                    "all preportfolio candidates must reconcile with entries/refusals"
                                )
                            report.update(
                                {
                                    "raw_candidates": total_raw,
                                    "preportfolio_first_arrival_feasible": total_geometric,
                                    "preportfolio_refused": total_raw - total_geometric,
                                    "complete_system_economics": False,
                                    "strategy_qualified": False,
                                }
                            )
                            economics[wid][arm][scenario.id] = report
                            ledgers[arm][scenario.id] = {
                                "report": report,
                                "trades": account.trades,
                                "events": account.events,
                            }
                    write_json(output_root / f"{wid}-ledgers.json", ledgers)
                    if load_window(bars, factors, window).evidence != inputs.evidence:
                        raise ValueError(
                            "original archive checksums/normalized inputs changed during diagnostic"
                        )
                    print(f"phase=window_complete window={wid}", flush=True)
        after = installed_sources(load_plan(source_path), source_path)
        if before != after or baseline_identities() != identities or fixed_search_protocol() != protocol:
            raise ValueError("source, dependency locks, native identities or sealed policy changed")
        if slots != 2 * protocol["expected_slots_each_arm"]:
            raise ValueError("all predeclared arm/window/symbol slots required")
        _check(deadline)
        write_json(
            output_root / "after.json",
            {"sources": after, "source_receipt_unchanged": True, "actual_finished_utc": utc_now()},
        )
        result = {
            "schema": protocol["schema"],
            "state": "OFFLINE_PRICE_ONLY_DIAGNOSTIC_COMPLETED_NOT_QUALIFICATION",
            "actual_started_utc": actual_started,
            "actual_finished_utc": utc_now(),
            "elapsed_seconds": time.monotonic() - started,
            "protocol_sha256": digest(protocol),
            "source_receipt_unchanged": True,
            "complete_scheduled_slots": slots,
            "decisions_canonical_jsonl_sha256": tape_sha.hexdigest(),
            "decisions_gzip_sha256": hashlib.sha256(
                (output_root / "decisions.jsonl.gz").read_bytes()
            ).hexdigest(),
            "windows": counts,
            "conditional_ohlc_trading_net_reference": economics,
            "complete_system_economic_result": None,
            "provider_calls": 0,
            "provider_cost_usd": 0,
            "required_news_macro_ready": False,
            "source_authenticity_admitted": False,
            "model_execution_admitted": False,
            "blind_campaign_credit": False,
            "readiness": dict(READINESS),
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
    result = search(args.workspace_root, args.output_root)
    print(f"state={result['state']} slots={result['complete_scheduled_slots']} provider_calls=0", flush=True)


if __name__ == "__main__":
    main()
