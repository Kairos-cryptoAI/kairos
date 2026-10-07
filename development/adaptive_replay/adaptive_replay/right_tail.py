"""One fixed cache-only native pair; no tuning, enrollment or integration.

Reuses the four already-seen diagnostic slices, not an unseen alpha test. The
35-day prefix gives the unchanged slow regime its full 200 completed 4h bars.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from kairos_strategy.models import SleeveIntent
from kairos_strategy.provenance import installed_source_tree_sha256
from kairos_strategy.registry import generate_sleeve_intents, get_strategy
from kairos_strategy.sleeves.regime_aligned_right_tail import RegimeAlignedRightTailConfig
from kairos_strategy.sleeves.right_tail_trend import RightTailTrendConfig

from .compare import BASE_PLAN_SHA, COMMON_ADMISSION
from .engine import COMMON_COST_RISK, CostScenario, replay_tape
from .inputs import UNIVERSE, WindowInputs, load_window
from .runner import canonical, digest, load_plan, source_receipt, utc_now, write_json

ARMS = ("right_tail_trend_v1", "regime_aligned_right_tail_v1")
MINUTE = 60_000
HOUR = 60 * MINUTE
DAY = 24 * HOUR
WARMUP = 35 * DAY


def identities() -> dict[str, Any]:
    configs = (RightTailTrendConfig(), RegimeAlignedRightTailConfig())
    return {
        arm: {
            "config": asdict(config),
            "fingerprint": config.fingerprint,
            "registry_source_sha256": installed_source_tree_sha256(get_strategy(arm).source_files),
            "registry_status": get_strategy(arm).status.value,
            "revision": get_strategy(arm).revision,
        }
        for arm, config in zip(ARMS, configs, strict=True)
    }


def load_protocol(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    base = load_plan(path.parent / "plan.json")
    expected = {
        "schema": "kairos.strategy.right-tail-pair-plan.v1",
        "purpose": "SEEN_HISTORICAL_COMPATIBILITY_NOT_STRATEGY_SELECTION_OR_QUALIFICATION",
        "base_development_plan_sha256": BASE_PLAN_SHA,
        "arms": list(ARMS),
        "common_admission": COMMON_ADMISSION,
        "warmup_hours": 840,
        "exit_tail_hours": 72,
        "entry_modes": ["STRICT_MINUTE_OPEN"],
        "workers": 1,
        "max_wall_seconds": 1200,
        "readiness": base["readiness"],
    }
    for field in (
        "unchanged_native_defaults",
        "transitive_base_source_binding",
        "no_downloads",
        "no_paid_calls",
        "no_parameter_search",
        "no_blind_campaign_credit",
    ):
        expected[field] = True
    actual = identities()
    expected["config_fingerprints"] = {arm: actual[arm]["fingerprint"] for arm in ARMS}
    expected["registry_source_fingerprints"] = {arm: actual[arm]["registry_source_sha256"] for arm in ARMS}
    if canonical(plan) != canonical(expected) or digest(base) != BASE_PLAN_SHA:
        raise ValueError("unchanged fixed right-tail compatibility protocol required")
    return plan, base


def sources(plan: dict[str, Any], base: dict[str, Any], path: Path) -> dict[str, Any]:
    # The base receipt also seals installed parser/risk modules, dependency VCS
    # revisions and every replay module. Its adaptive identity is dependency
    # context only: this runner never calls or loads adaptive economic tapes.
    binding = identities()
    if plan["registry_source_fingerprints"] != {
        arm: binding[arm]["registry_source_sha256"] for arm in ARMS
    } or plan["config_fingerprints"] != {arm: binding[arm]["fingerprint"] for arm in ARMS}:
        raise ValueError("native source/configuration changed")
    return {
        "installed_replay_context": source_receipt(base, path),
        "native_pair": binding,
        # Aligned registry source_files omits its imported base sleeve. The
        # separately sealed base tree closes that specific transitive gap.
        "aligned_transitive_base_source_sha256": binding[ARMS[0]]["registry_source_sha256"],
        "pair_plan_sha256": digest(plan),
        "plan_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def check_pair(base: list[SleeveIntent], aligned: list[SleeveIntent]) -> None:
    original = {intent.intent_id: intent for intent in base}
    if len(original) != len(base) or len({i.intent_id for i in aligned}) != len(aligned):
        raise ValueError("duplicate native intent")
    for intent in aligned:
        metadata = dict(intent.metadata)
        parent = original.get(metadata.get("base_intent_id", ""))
        if parent is None:
            raise ValueError("aligned candidate lacks its exact native base")
        for field in (
            "symbol",
            "side",
            "decision_ts_ms",
            "entry_eligible_ts_ms",
            "entry_expires_ts_ms",
            "reference_price",
            "signal_strength",
            "gross_reward_bps",
            "exit_plan",
        ):
            if getattr(intent, field) != getattr(parent, field):
                raise ValueError(f"aligned candidate changed base economics: {field}")
        if metadata.get("base_feature_hash") != dict(parent.metadata).get("feature_hash"):
            raise ValueError("aligned base feature binding changed")
        if metadata.get("base_config_sha256") != RightTailTrendConfig().fingerprint:
            raise ValueError("aligned base configuration binding changed")
        regime_ts = int(metadata["regime_close_ts_ms"])
        if regime_ts % (4 * HOUR) != 4 * HOUR - 1 or not 0 <= intent.decision_ts_ms - regime_ts < 4 * HOUR:
            raise ValueError("regime must be the last complete causal 4h state")


def check_regime_selection(
    base: list[SleeveIntent],
    aligned: list[SleeveIntent],
    prefix: list[Any],
) -> None:
    """Independent minute-endpoint SMA calculation, not the strategy helper."""
    closes = {row.close_time_ms: row.close for row in prefix}
    expected = set()
    actual = {dict(intent.metadata)["base_intent_id"]: intent for intent in aligned}
    for parent in base:
        last = ((parent.decision_ts_ms + 1) // (4 * HOUR)) * (4 * HOUR) - 1
        clocks = [last - offset * 4 * HOUR for offset in range(199, -1, -1)]
        if any(clock not in closes for clock in clocks):
            continue  # Known incomplete warmup, never counted as a scoring outcome.
        average = math.fsum(closes[clock] for clock in clocks) / 200
        close = closes[last]
        allowed = close > average if parent.side.value == "LONG" else close < average
        if not allowed:
            continue
        expected.add(parent.intent_id)
        if parent.intent_id in actual:
            metadata = dict(actual[parent.intent_id].metadata)
            if (
                int(metadata["regime_close_ts_ms"]) != last
                or float(metadata["regime_close"]) != close
                or float(metadata["regime_sma"]) != average
            ):
                raise ValueError("regime metadata disagrees with causal minute endpoints")
    if set(actual) != expected:
        raise ValueError("aligned candidates differ from the exact causal SMA predicate")


def generate_pair(
    inputs: WindowInputs,
    deadline: float,
) -> tuple[dict[str, dict[int, list[SleeveIntent]]], dict[str, Any]]:
    prefix_start = inputs.start_ms - WARMUP
    cuts = tuple(
        sorted(
            {
                inputs.start_ms + HOUR,
                inputs.start_ms + DAY,
                inputs.start_ms + DAY + HOUR,
                inputs.start_ms + 2 * DAY,
                inputs.start_ms + 2 * DAY + HOUR,
                inputs.end_ms,
            }
        )
    )
    tapes: dict[str, dict[int, list[SleeveIntent]]] = {arm: {} for arm in ARMS}
    evidence: dict[str, Any] = {"prefix_start_ms": prefix_start, "exit_tail_used": False, "symbols": {}}
    configs = (RightTailTrendConfig(), RegimeAlignedRightTailConfig())
    for symbol in UNIVERSE:
        prefix = [row for row in inputs.bars[symbol] if prefix_start <= row.open_time_ms < inputs.end_ms]
        if (
            len(prefix) != (inputs.end_ms - prefix_start) // MINUTE
            or prefix[0].open_time_ms != prefix_start
            or prefix[-1].close_time_ms != inputs.end_ms - 1
            or any(
                a.open_time_ms + MINUTE != b.open_time_ms for a, b in zip(prefix, prefix[1:], strict=False)
            )
        ):
            raise ValueError("complete exact 35-day prefix and scoring span required")
        generated: dict[str, list[SleeveIntent]] = {}
        per_symbol = {}
        for arm, config in zip(ARMS, configs, strict=True):
            if time.monotonic() >= deadline:
                raise TimeoutError("bounded native generation deadline")
            full = generate_sleeve_intents(arm, prefix, config)
            for cut in cuts:
                if time.monotonic() >= deadline:
                    raise TimeoutError("bounded prefix-check deadline")
                truncated = generate_sleeve_intents(
                    arm, [row for row in prefix if row.open_time_ms < cut], config
                )
                if [asdict(i) for i in full if i.decision_ts_ms < cut] != [asdict(i) for i in truncated]:
                    raise ValueError("native expanding-prefix mutation detected")
            generated[arm] = full
            scoring = []
            for intent in full:
                eligible = intent.entry_eligible_ts_ms
                if (
                    intent.sleeve_id != arm
                    or intent.symbol != symbol
                    or intent.decision_ts_ms != eligible - 1
                    or eligible % DAY != HOUR
                    or intent.entry_expires_ts_ms != eligible + HOUR - 1
                    or intent.exit_plan.max_holding_ms != 72 * HOUR
                    or intent.exit_plan.trailing_activation_price is not None
                    or dict(intent.metadata).get("config_sha256") != config.fingerprint
                ):
                    raise ValueError("native daily clock/lifecycle/identity changed")
                if inputs.start_ms <= eligible < inputs.end_ms:
                    tapes[arm].setdefault(eligible, []).append(intent)
                    scoring.append(intent.intent_id)
            per_symbol[arm] = {"full_prefix_candidates": len(full), "scoring_candidates": len(scoring)}
        check_pair(generated[ARMS[0]], generated[ARMS[1]])
        check_regime_selection(generated[ARMS[0]], generated[ARMS[1]], prefix)
        evidence["symbols"][symbol] = {
            "prefix_bars": len(prefix),
            "prefix_checks_ms": list(cuts),
            **per_symbol,
        }
    for tape in tapes.values():
        for intents in tape.values():
            intents.sort(key=lambda i: (UNIVERSE.index(i.symbol), i.intent_id))
    return tapes, evidence


def write_daily_tape(path: Path, tape: dict[int, list[SleeveIntent]], inputs: WindowInputs) -> dict[str, Any]:
    encoded_rows = []
    for eligible in range(inputs.start_ms + HOUR, inputs.end_ms, DAY):
        for symbol in UNIVERSE:
            matched = [i for i in tape.get(eligible, []) if i.symbol == symbol]
            if len(matched) > 1:
                raise ValueError("duplicate symbol/daily decision")
            encoded_rows.append(
                canonical(
                    {
                        "symbol": symbol,
                        "decision_ts_ms": eligible - 1,
                        "entry_eligible_ts_ms": eligible,
                        "status": "NATIVE_CANDIDATE" if matched else "NO_NATIVE_CANDIDATE_REASON_UNAVAILABLE",
                        "intent": asdict(matched[0]) if matched else None,
                        "source_outcome_reason": None,
                        "context": "COMPLETE_ARCHIVE_PREFIX_NOT_OBSERVED_LIVE_RECEIVE_CLOCK",
                    }
                )
                + b"\n"
            )
    payload = b"".join(encoded_rows)
    with path.open("xb") as stream:
        stream.write(payload)
    return {
        "native_daily_slots": len(encoded_rows),
        "candidates": sum(map(len, tape.values())),
        "tape_sha256": hashlib.sha256(payload).hexdigest(),
        "complete_source_outcomes": False,
        "decisions_in_exit_tail": 0,
    }


def run(plan_path: Path, bar_cache: Path, factor_cache: Path, output: Path) -> int:
    plan, base = load_protocol(plan_path)
    before = sources(plan, base, plan_path)
    for protected in (bar_cache, factor_cache, plan_path.parent):
        if output == protected or output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("output must not overlap source or caches")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + plan["max_wall_seconds"]
    write_json(output / "sealed-pair-plan.json", plan)
    write_json(output / "before.json", {"state": "RUNNING", "started_utc": utc_now(), "sources": before})
    windows = []
    try:
        for window in base["windows"]:
            if time.monotonic() >= deadline:
                raise TimeoutError("bounded pair replay deadline")
            directory = output / window["id"]
            directory.mkdir()
            print(f"phase=offline_integrity window={window['id']}", flush=True)
            inputs = load_window(
                bar_cache, factor_cache, window, plan["warmup_hours"], plan["exit_tail_hours"]
            )
            write_json(directory / "inputs.json", inputs.evidence)
            tapes, generation = generate_pair(inputs, deadline)
            write_json(directory / "native-pair-evidence.json", generation)
            arms = []
            for arm in ARMS:
                arm_dir = directory / arm
                arm_dir.mkdir()
                counts = write_daily_tape(arm_dir / "decisions.jsonl", tapes[arm], inputs)
                results = []
                for cost in base["cost_scenarios"]:
                    report, account = replay_tape(
                        inputs,
                        tapes[arm],
                        CostScenario(**cost),
                        "STRICT_MINUTE_OPEN",
                        base["pipeline_latency_ms_assumed"],
                        plan["exit_tail_hours"],
                        admission_policy=COMMON_COST_RISK,
                        deadline=deadline,
                    )
                    write_json(arm_dir / f"{cost['id']}.json", report)
                    write_json(
                        arm_dir / f"{cost['id']}-ledger.json",
                        {"events": account.events, "trades": account.trades},
                    )
                    results.append(report)
                arms.append({"arm_id": arm, "counts": counts, "economic_results": results})
                print(f"phase=arm_completed window={window['id']} arm={arm}", flush=True)
            windows.append({"window": window, "arms": arms})
            del inputs, tapes
        if load_protocol(plan_path) != (plan, base) or sources(plan, base, plan_path) != before:
            raise ValueError("protocol/source drift during replay")
        write_json(
            output / "result.json",
            {
                "schema": "kairos.strategy.right-tail-pair-result.v1",
                "state": "COMPLETED",
                "sources": before,
                "windows": windows,
                "finished_utc": utc_now(),
                "elapsed_seconds": time.monotonic() - started,
                "readiness": plan["readiness"],
                "qualified_winner": None,
                "strategy_selected_for_live": None,
                "compound_return_across_windows": None,
                "blind_results_read": False,
                "blind_campaign_days_added": 0,
                "paid_calls": 0,
                "authority": "SEEN_COMPATIBILITY_ONLY_NOT_ALPHA_OR_FULL_SYSTEM_QUALIFICATION",
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
                "completed_windows": windows,
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
