"""Read-only assessment of real CURRENT run receipts, separate from traversal.

A completed no-signal run is legitimate, but is not evidence that real models,
Risk and SIM fills all occurred. Offline fixtures never satisfy these checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .current_runner import write_create_only


def assess(before: dict, run: dict, responses: list[dict], budget: list[dict]) -> dict:
    committed = {
        row["reservation_id"]: row
        for row in budget
        if row.get("event") == "SHARED_COMMITTED" and row.get("state") == "COMMITTED"
    }
    actual = [
        row["result"]
        for row in responses
        if row.get("state") == "ACTUAL_RESPONSE"
        and row.get("result", {}).get("provider") == "openai"
        and row["result"].get("cached") is False
        and row["result"].get("request_id")
        and not any(
            word in row["result"].get("model", "").lower() for word in ("synthetic", "fixture", "dummy")
        )
        and row["result"].get("budget_reservation_id") in committed
    ]
    reservations = [row["budget_reservation_id"] for row in actual]
    if len(set(reservations)) != len(reservations):
        raise ValueError("duplicate physical provider reservation in real-path receipts")
    workloads = [row["workload"] for row in actual]
    stages = {row["name"] for row in run.get("stages", []) if row.get("status") == "COMPLETED"}
    text = run.get("text_poll", {})
    slots = run.get("slot_results", [])
    simulated = run.get("sim_outcomes", [])
    checks = {
        "traversal_completed": run.get("result") == "COMPLETED",
        "prospective_current_not_fixture": before.get("plan", {}).get("mode")
        == "CURRENT_PROSPECTIVE_ENGINEERING_SIM_ONLY",
        "five_symbol_real_bar_capture": len(run.get("history_bar_counts", {})) == 5
        and all(count == 3240 for count in run.get("history_bar_counts", {}).values()),
        "fresh_news_with_actual_text_model": text.get("captured_item_count", 0) > 0
        and "text_scouts" in workloads,
        "actual_macro_model_output": run.get("macro_allocation_origin") == "MODEL_OUTPUT"
        and "macro_strategist" in workloads,
        "current_catalyst_plan_materialized": any(row.get("plan_ids") for row in slots),
        "actual_native_router_and_model_review": any(name.startswith("native_brain_") for name in stages)
        and any(name in {"aggregator_normal", "aggregator_conflict"} for name in workloads),
        "native_sim_risk_persisted": any(name.startswith("persist_sim_risk_decision:") for name in stages),
        "actual_sim_execution_receipt": any(name.startswith("simulation_submit_entry:") for name in stages)
        and any(row.get("fill_receipt") is not None for row in simulated),
    }
    missing = [name for name, passed in checks.items() if not passed]
    full_lifecycle = any(
        row.get("execution_state") == "FLAT" and row.get("closing_receipt") is not None for row in simulated
    )
    return {
        "schema": "kairos.current-real-path-acceptance.v1",
        "state": "REAL_ENTRY_PATH_VERIFIED" if not missing else "PARTIAL_REQUIRED_STAGES_NOT_EXERCISED",
        "traversal_result": run.get("result"),
        "checks": checks,
        "missing_required_evidence": missing,
        "actual_committed_provider_calls": len(actual),
        "committed_workloads": workloads,
        "actual_cost_microusd": sum(row.get("actual_microusd", 0) for row in committed.values()),
        "cost_basis": "EXISTING_REGISTERED_PRICES_NOT_PROVIDER_INVOICE",
        "full_trade_lifecycle_verified": full_lifecycle,
        "offline_fixture_credit": False,
        "profitability_claim": False,
        "historical_or_blind_credit": False,
        "readiness_promotion": False,
        "trading_authority": "NONE",
    }


def _read(path: Path) -> bytes:
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("bounded current receipt required")
    return path.read_bytes()


def assess_directory(root: Path) -> dict:
    names = ("before.json", "current-chain-result.json", "provider-results.jsonl", "budget.jsonl")
    bodies = {name: _read(root / name) if (root / name).exists() else b"" for name in names}
    result = assess(
        json.loads(bodies["before.json"]),
        json.loads(bodies["current-chain-result.json"]),
        [json.loads(line) for line in bodies["provider-results.jsonl"].splitlines() if line],
        [json.loads(line) for line in bodies["budget.jsonl"].splitlines() if line],
    )
    result["input_sha256s"] = {name: hashlib.sha256(body).hexdigest() for name, body in bodies.items()}
    result["input_file_presence"] = {name: (root / name).is_file() for name in names}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    args = parser.parse_args()
    root = args.run_directory
    result = assess_directory(root)
    write_create_only(root / "verification-acceptance.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
