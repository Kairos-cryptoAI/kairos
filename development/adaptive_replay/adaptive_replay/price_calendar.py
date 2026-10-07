"""Separate preregistered PRICE_ONLY full-year slow-reference comparison.

Never retries the old FULL_KLINE attempt, changes native logic or qualifies
adaptive/volume consumers, alpha or trading. One create-only bounded attempt.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import time
from importlib import import_module
from pathlib import Path
from typing import Any

from . import calendar_pair as calendar
from . import right_tail as pair
from .engine import COMMON_COST_RISK, CostScenario, replay_tape
from .price_inputs import CONSUMERS, load_window, read_acceptance, verify_sources
from .runner import canonical, utc_now, write_json
from .source_set import PRIOR_AUDIT_SHA, RETRIEVAL_RECEIPT_SHA

ACCEPTANCE_SHA = "130935ccfa310d656b22135c0e18ead69f20d00250d39066eabbb5ff283e961e"
OLD_FAILED_PLAN_SHA = "75a68d977519f3fdce3a494dbf6761887e89cfbca1c912f30be26df11c4d2fdd"
OLD_FAILURE_SHA = "63192f49e18a542ff0e52ea2ffb3eb3565257cde2a2e8c407dc9916dd549f6f1"


def expected_plan(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    old, base = calendar.load_protocol(path.parent / "calendar-pair-plan.json")
    return {
        **old,
        "schema": "kairos.strategy.price-reference-calendar-plan.v1",
        "purpose": "EXPOSED_DEVELOPMENT_FIELD_SCOPE_AMENDMENT_NOT_FULL_KLINE_REPAIR",
        "source_acceptance_sha256": ACCEPTANCE_SHA,
        "prior_audit_sha256": PRIOR_AUDIT_SHA,
        "official_retrieval_receipt_sha256": RETRIEVAL_RECEIPT_SHA,
        "old_failed_plan_sha256": OLD_FAILED_PLAN_SHA,
        "old_failure_sha256": OLD_FAILURE_SHA,
        "field_profile": "PRICE_ONLY",
        "allowed_consumers": CONSUMERS,
        "optional_fields": "NOT_EXPOSED_PLACEHOLDER_NOT_OBSERVED_ZERO",
        "source_policy": "MONTHLY_PRICES_AND_CLOCKS_UNCHANGED_EXACT_ABSENT_DAILY_ROWS_ONLY",
        "quarantined_optional_rows": 1,
        "added_symbol_minutes": 14400,
        "replaced_rejected_rows": 0,
        "all_source_acceptance_before_generation": True,
        "uniform_projection_all_bars": True,
        "no_new_strategy_or_volume_qualification": True,
        "no_second_economic_attempt": True,
    }, base


def load_protocol(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    expected, base = expected_plan(path)
    plan = json.loads(path.read_bytes())
    if canonical(plan) != canonical(expected):
        raise ValueError("exact separately preregistered price-reference protocol required")
    return plan, base


def sources(plan: dict[str, Any], base: dict[str, Any], path: Path) -> dict[str, Any]:
    modules = [
        import_module("kairos_strategy." + name)
        for name in (
            "candles",
            "validation",
            "timeframes",
            "models",
            "registry",
            "provenance",
            "sleeves.right_tail_trend",
            "sleeves.regime_aligned_right_tail",
        )
    ]
    return {
        **pair.sources(plan, base, path),
        "price_consumer_transitive_modules_sha256": {
            module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in modules
        },
        "source_acceptance_sha256": ACCEPTANCE_SHA,
    }


def run(plan_path: Path, bars: Path, factors: Path, daily: Path, acceptance_path: Path, output: Path) -> int:
    plan, base = load_protocol(plan_path)
    acceptance = read_acceptance(acceptance_path, ACCEPTANCE_SHA)
    before = sources(plan, base, plan_path)
    for protected in (bars, factors, daily, acceptance_path, plan_path.parent):
        if output == protected or output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("price-reference output cannot overlap any source")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + plan["max_wall_seconds"]
    write_json(output / "sealed-price-reference-plan.json", plan)
    write_json(output / "before.json", {"state": "RUNNING", "started_utc": utc_now(), "sources": before})
    windows = []
    try:
        print("phase=verify_all_accepted_sources_before_generation", flush=True)
        verify_sources(acceptance, bars, factors, daily, deadline)
        for window in plan["windows"]:
            directory = output / window["id"]
            directory.mkdir()
            print(f"phase=price_calendar_integrity window={window['id']}", flush=True)
            inputs = load_window(bars, factors, daily, window, acceptance, deadline)
            write_json(directory / "inputs.json", inputs.evidence)
            tapes, generation = calendar.generate_calendar_pair(inputs, deadline)
            write_json(directory / "native-pair-evidence.json", generation)
            arms = []
            for arm in pair.ARMS:
                arm_dir = directory / arm
                arm_dir.mkdir()
                counts = pair.write_daily_tape(arm_dir / "decisions.jsonl", tapes[arm], inputs)
                reports = []
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
                    reports.append(report)
                    print(
                        f"phase=price_calendar_cell_completed window={window['id']} "
                        f"arm={arm} cost={cost['id']}",
                        flush=True,
                    )
                arms.append({"arm_id": arm, "counts": counts, "economic_results": reports})
            windows.append({"window": window, "arms": arms})
            del inputs, tapes, account
            gc.collect()
        verify_sources(acceptance, bars, factors, daily, deadline)
        if (
            read_acceptance(acceptance_path, ACCEPTANCE_SHA) != acceptance
            or load_protocol(plan_path) != (plan, base)
            or sources(plan, base, plan_path) != before
        ):
            raise ValueError("price-reference protocol/source drift")
        write_json(
            output / "result.json",
            {
                "schema": "kairos.strategy.price-reference-calendar-result.v1",
                "state": "COMPLETED",
                "sources": before,
                "windows": windows,
                "reference_decision": calendar.select_reference(windows),
                "finished_utc": utc_now(),
                "elapsed_seconds": time.monotonic() - started,
                "readiness": plan["readiness"],
                "qualified_winner": None,
                "strategy_selected_for_live": None,
                "compound_return_across_windows": None,
                "blind_results_read": False,
                "blind_campaign_days_added": 0,
                "paid_calls": 0,
                "authority": "PRICE_ONLY_EXPOSED_DEVELOPMENT_NOT_FULL_KLINE_OR_ALPHA_QUALIFICATION",
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
    for name in ("plan", "bar-cache", "factor-cache", "daily-cache", "source-acceptance", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    return run(
        *(
            getattr(args, name).resolve()
            for name in ("plan", "bar_cache", "factor_cache", "daily_cache", "source_acceptance", "output")
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
