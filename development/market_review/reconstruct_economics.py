"""Bounded offline economics for the October 15 publication-proxy reconstruction.

This is a candidate filter over the frozen October 10 native tape, not a full
Kairos NEWS/MACRO policy or a historical point-in-time experiment. It makes no
provider calls and writes only a new, create-only output directory.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
import time
from collections import Counter
from contextlib import suppress
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

experiment = importlib.import_module("run_comparison")
proxy_context = importlib.import_module("tools.reconstruct_context")


RESULT_SCHEMA = "kairos.publication-proxy-reconstruction-economics.v1"
RESULT_STATE = "COMPLETED_CONDITIONAL_RECONSTRUCTION_NOT_FULL_SYSTEM"
RECONCILE_SCHEMA = "kairos.cached-market-proxy-reconciliation.v1"
RECONCILE_STATE = "COMPLETED_CACHED_MARKET_PROXY_RECONCILIATION_NOT_CAUSAL"
PRIOR_RECONSTRUCTION_SHA256 = (
    "9f2a3ce3f3083fb5ad14622e1c650a0b9e515d2491274dd7026c4ccf6b4fcee5"
)
NO_CALL = "NOT_CALLED_MISSING_PROXY_CONTEXT"
REVIEWED = "OBSERVED_COMMITTED"
FILTER_POLICY = "FIXED_EXPLORATORY_KEEP_ONLY_EXPLICIT_ALLOW_V1"
PROXY_FILES = (
    "sealed-plan.json",
    "seal.json",
    "before.json",
    "requests.json",
    "reviews.jsonl",
    "no-calls.jsonl",
    "proxy-diagnostic-result.json",
    "worker-start.json",
)
RECONCILIATION_ARMS = (
    "strategy_only",
    "cash_only",
    "market_latency_cost_control",
    "market_llm_review",
    "proxy_source_eligibility_control",
    "proxy_latency_cost_control",
    "proxy_review",
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if type(row) is not dict:
                raise ValueError("JSONL receipts must be objects")
            rows.append(row)
    return rows


def _proxy_file_hashes(root: Path) -> dict[str, str]:
    if any(not (root / name).is_file() for name in PROXY_FILES):
        raise ValueError("cached proxy reconstruction artifact set incomplete")
    return {name: experiment.file_sha(root / name) for name in PROXY_FILES}


def _validate_capture_signature(args: Any) -> dict[str, str]:
    worker = importlib.import_module("tools.proxy_worker")
    signature = worker.capture_signature(args.capture_manifest, args.sources)
    worker_start = experiment.read_json(args.proxy_run / "worker-start.json")
    if signature != worker_start.get("raw_input_signature"):
        raise ValueError("raw publication capture differs from worker receipt")
    return signature


def _validate_proxy_request(request: dict, old: dict, source_bundle: dict) -> bool:
    original_user = json.loads(old["user"])
    original_geometry = original_user["candidate"]
    user = json.loads(request["user"])
    if (
        request.get("system") != proxy_context.SYSTEM
        or user.get("candidate") != original_geometry
        or request.get("baseline_candidate_geometry") != original_geometry
        or request.get("baseline_candidate_geometry_sha256")
        != experiment.digest(original_geometry)
        or request.get("baseline_prompt_sha256") != old["prompt_sha256"]
        or request.get("historical_cut_ms") != old["historical_cut_ms"]
        or request.get("window_id") != old["window_id"]
        or request.get("slot_id") != old["slot_id"]
        or experiment.digest({"system": request["system"], "user": user})
        != request.get("prompt_sha256")
    ):
        raise ValueError("proxy prompt or original candidate binding mismatch")
    if any(
        user.get(field) != original_user.get(field)
        for field in ("asset_complete_bars", "market_proxy_complete_1h_bars")
    ):
        raise ValueError("proxy market context differs from original completed bars")
    selected = proxy_context._select_sources(
        source_bundle, request["historical_cut_ms"]
    )
    expected_view = {
        "NEWS": proxy_context._source_view(selected["NEWS"]),
        "MACRO": proxy_context._source_view(selected["MACRO"]),
    }
    context = user.get("publication_time_proxy_context")
    if type(context) is not dict or context.get("sources") != expected_view:
        raise ValueError(
            "proxy request source view differs from validated publication proxies"
        )
    eligible = bool(selected["NEWS"] and selected["MACRO"])
    expected_news = (
        "PARTIAL_PUBLICATION_ONLY_PROXY"
        if selected["NEWS"]
        else "UNAVAILABLE_NOT_KNOWN_EMPTY"
    )
    expected_macro = (
        "PARTIAL_PUBLICATION_ONLY_PROXY"
        if selected["MACRO"]
        else "UNAVAILABLE_NOT_KNOWN_EMPTY"
    )
    if (
        request.get("dispatch_eligible") is not eligible
        or request.get("no_call_reason")
        != (None if eligible else "MISSING_PUBLICATION_PROXY_CONTEXT")
        or user.get("news") != expected_news
        or user.get("external_macro") != expected_macro
        or context.get("news_status") != expected_news
        or context.get("macro_status") != expected_macro
    ):
        raise ValueError(
            "proxy eligibility/no-call reason disagrees with source presence"
        )
    return eligible


def _validate_admission_geometry(request: dict, admission_row: dict) -> None:
    # Admission seals the native absolute geometry; the masked prompt has a
    # separate normalized geometry hash. Compare like evidence, never the two.
    if request.get("admission_original_candidate_geometry_sha256") != admission_row.get(
        "original_candidate_geometry_sha256"
    ) or not admission_row.get("original_candidate_geometry_sha256"):
        raise ValueError("proxy original admission geometry binding mismatch")


def _proxy_receipts(
    args: Any, baseline: dict, baseline_requests: list
) -> tuple[dict, dict]:
    """Validate the already-finished cached publication-proxy response set."""
    root = args.proxy_run
    proxy_hashes = _proxy_file_hashes(root)
    plan = experiment.read_json(root / "sealed-plan.json")
    seal = experiment.read_json(root / "seal.json")
    before = experiment.read_json(root / "before.json")
    result = experiment.read_json(root / "proxy-diagnostic-result.json")
    requests = experiment.read_json(root / "requests.json")
    source_bundle, source_sha = proxy_context._validate_sources(args.sources)
    if (
        plan.get("schema") != proxy_context.PLAN_SCHEMA
        or plan.get("experiment_id") != proxy_context.EXPERIMENT_ID
        or plan.get("experiment_mode")
        != "PUBLICATION_TIME_PROXY_RECONSTRUCTION_DIAGNOSTIC"
        or plan.get("coverage") != "UNKNOWN"
        or plan.get("strict_causal_admission") is not False
        or plan.get("historical_receive_clock_proven") is not False
        or before.get("baseline_identity") != baseline["hashes"]
        or before.get("baseline_experiment_id") != baseline["plan"]["experiment_id"]
        or source_sha != plan.get("source_bundle_sha256")
        or source_sha != before.get("source_bundle_sha256")
    ):
        raise ValueError("cached proxy experiment scope or baseline binding mismatch")
    for filename, seal_key in (
        ("sealed-plan.json", "plan_sha256"),
        ("before.json", "before_sha256"),
        ("requests.json", "requests_sha256"),
    ):
        if experiment.file_sha(root / filename) != seal.get(seal_key):
            raise ValueError("cached proxy preparation seal mismatch")
    if len(requests) != 12 or {r.get("candidate_id") for r in requests} != {
        r["candidate_id"] for r in baseline_requests
    }:
        raise ValueError("cached proxy candidate roster mismatch")
    base_by_id = {r["candidate_id"]: r for r in baseline_requests}
    _, admission_rows = proxy_context._validate_admission(
        args.admission_result, baseline_requests
    )
    for request in requests:
        old = base_by_id[request["candidate_id"]]
        eligible_by_sources = _validate_proxy_request(request, old, source_bundle)
        _validate_admission_geometry(request, admission_rows[request["candidate_id"]])
        if eligible_by_sources != (request.get("dispatch_eligible") is True):
            raise ValueError(
                "proxy request changed original candidate identity/geometry"
            )

    review_rows = _read_jsonl(root / "reviews.jsonl")
    no_call_rows = _read_jsonl(root / "no-calls.jsonl")
    eligible = [r for r in requests if r.get("dispatch_eligible") is True]
    no_call_requests = [r for r in requests if r.get("dispatch_eligible") is False]
    if len(eligible) != 9 or len(no_call_requests) != 3:
        raise ValueError(
            "expected exactly nine observed reviews and three explicit no-calls"
        )
    observations = experiment.validate_reviews(eligible, review_rows)
    if Counter(r["decision"] for r in observations.values()) != {"DEFER": 9}:
        raise ValueError(
            "this finite reconstruction expects the sealed nine-DEFER cache"
        )
    expected_no_calls = {r["candidate_id"]: r for r in no_call_requests}
    if len(no_call_rows) != 3 or {r.get("candidate_id") for r in no_call_rows} != set(
        expected_no_calls
    ):
        raise ValueError("no-call receipts do not cover exactly three candidates")
    for receipt in no_call_rows:
        request = expected_no_calls[receipt["candidate_id"]]
        if (
            receipt.get("state") != NO_CALL
            or receipt.get("prompt_sha256") != request.get("prompt_sha256")
            or receipt.get("decision") != "DEFER"
            or receipt.get("actual_microusd") != 0
            or any(
                receipt.get(k) is not None
                for k in (
                    "modern_attempt_started_ms",
                    "modern_response_observed_ms",
                    "modern_adapter_finished_ms",
                    "request_id",
                    "budget_reservation_id",
                )
            )
        ):
            raise ValueError(
                "invalid no-call receipt; unknown dispatch/cost is fail-closed"
            )
    if (
        result.get("schema") != proxy_context.RESULT_SCHEMA
        or result.get("state") != "COMPLETED_PUBLICATION_TIME_PROXY_DIAGNOSTIC"
        or result.get("candidate_count") != 12
        or result.get("modern_model_calls") != 9
        or result.get("not_called_missing_proxy_context") != 3
        or result.get("coverage") != "UNKNOWN"
        or result.get("baseline_market_only_result_sha256")
        != baseline["hashes"]["result.json"]
        or result.get("source_bundle_sha256") != plan.get("source_bundle_sha256")
        or result.get("admission_result_sha256") != plan.get("admission_result_sha256")
        or result.get("actual_model_cost_microusd")
        != sum(r["actual_microusd"] for r in observations.values())
        or result.get("prior_failed_provider_attempts")
        != plan.get("prior_provider_attempts")
        or result.get("prior_unresolved_hold_microusd")
        != plan.get("prior_local_held_microusd")
        or result.get("full_news_macro_system_tested") is not False
    ):
        raise ValueError("cached proxy completion receipt does not reconcile")
    candidate_results = _index_candidate_results(
        result.get("candidate_results"), {r["candidate_id"] for r in requests}
    )
    for candidate_id, request in ((r["candidate_id"], r) for r in requests):
        row = candidate_results[candidate_id]
        review = observations.get(candidate_id)
        if review is None:
            if (
                row.get("dispatch_state") != NO_CALL
                or row.get("proxy_diagnostic_decision") is not None
                or row.get("actual_microusd") != 0
                or row.get("window_id") != request.get("window_id")
                or row.get("slot_id") != request.get("slot_id")
            ):
                raise ValueError(
                    "no-call must remain explicit abstention, never a veto"
                )
        elif (
            row.get("dispatch_state") != REVIEWED
            or row.get("proxy_diagnostic_decision") != review["decision"]
            or row.get("actual_microusd") != review["actual_microusd"]
            or row.get("proxy_prompt_sha256") != request["prompt_sha256"]
            or row.get("candidate_geometry_sha256")
            != request["baseline_candidate_geometry_sha256"]
            or row.get("window_id") != request.get("window_id")
            or row.get("slot_id") != request.get("slot_id")
        ):
            raise ValueError("cached proxy result disagrees with its receipt")
    if _proxy_file_hashes(root) != proxy_hashes:
        raise ValueError("cached proxy artifacts changed during receipt validation")
    return observations, {r["candidate_id"]: r for r in requests}


def _known_prior_hold(plan: dict) -> dict:
    attempts = plan.get("prior_provider_attempts")
    held = plan.get("prior_local_held_microusd")
    if type(attempts) is not int or attempts != 2 or type(held) is not int or held < 0:
        raise ValueError("prior failed-attempt/held-cost evidence unknown")
    return {
        "prior_failed_attempts": attempts,
        "unresolved_held_cost_microusd": held,
        "treatment": "reported separately; excluded from known actual spend and not mutated",
        "conservative_cost_bound_microusd": held,
    }


def _filter_decision(decision: str | None, dispatch_state: str) -> str:
    """Return the fixed candidate-filter action; absent evidence always abstains."""
    if dispatch_state == NO_CALL:
        if decision is not None:
            raise ValueError("no-call cannot carry a model decision")
        return "ABSTAIN"
    if dispatch_state != REVIEWED or decision not in {"ALLOW", "VETO", "DEFER"}:
        raise ValueError("unknown review state or policy decision")
    return "KEEP_ORIGINAL_CANDIDATE" if decision == "ALLOW" else "FILTER_CANDIDATE"


def _economic_inputs(
    candidates: list[tuple[dict, Any]],
    observations: dict[str, dict],
    assumed_latency_ms: int,
) -> tuple[dict[int, list], dict[str, int], list[tuple[str, int, int]]]:
    """Separate entry completion clocks from costs charged for every observation."""
    candidate_ids = [intent.intent_id for _, intent in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("duplicate candidate in economic tape")
    if not set(observations).issubset(candidate_ids):
        raise ValueError("review receipt outside economic candidate roster")
    filtered_tape: dict[int, list] = {}
    entry_completion_times: dict[str, int] = {}
    service_costs: list[tuple[str, int, int]] = []
    for _, intent in candidates:
        review = observations.get(intent.intent_id)
        if review is None:
            _filter_decision(None, NO_CALL)
            continue
        action = _filter_decision(review["decision"], REVIEWED)
        modeled_at = (
            intent.decision_ts_ms
            + assumed_latency_ms
            + review["measured_pipeline_duration_ms"]
        )
        service_costs.append((intent.intent_id, modeled_at, review["actual_microusd"]))
        if action == "KEEP_ORIGINAL_CANDIDATE":
            entry_completion_times[intent.intent_id] = modeled_at
            filtered_tape.setdefault(intent.decision_ts_ms + 1, []).append(intent)
    if set(entry_completion_times) != {
        intent.intent_id for values in filtered_tape.values() for intent in values
    }:
        raise ValueError("entry completion roster must exactly match filtered tape")
    return filtered_tape, entry_completion_times, service_costs


def _recorded_review_inputs(
    candidates: list[tuple[dict, Any]],
    observations: dict[str, dict],
    assumed_latency_ms: int,
) -> tuple[dict[str, int], tuple[Any, ...]]:
    """Bind every real review clock/debit, including DEFER, but never NO_CALL."""
    from adaptive_replay.engine import AccountCost

    ids = {intent.intent_id for _, intent in candidates}
    if len(ids) != len(candidates) or not set(observations).issubset(ids):
        raise ValueError("review completion roster differs from candidate roster")
    completions = {}
    costs = []
    for _, intent in candidates:
        review = observations.get(intent.intent_id)
        if review is None:
            continue
        duration = review.get("measured_pipeline_duration_ms")
        amount = review.get("actual_microusd")
        if type(duration) is not int or duration <= 0:
            raise ValueError("observed review duration must be positive integer ms")
        if type(amount) is not int or amount < 0:
            raise ValueError(
                "observed review cost must be nonnegative integer microUSD"
            )
        completed = intent.decision_ts_ms + assumed_latency_ms + duration
        completions[intent.intent_id] = completed
        costs.append(
            AccountCost(intent.intent_id, completed, amount / 1_000_000, "MODEL")
        )
    if set(completions) != set(observations) or len({c.cost_id for c in costs}) != len(
        costs
    ):
        raise ValueError("review clock/cost roster is incomplete or duplicated")
    return completions, tuple(costs)


def _reconciliation_arm_inputs(
    arm: str,
    candidates: list[tuple[dict, Any]],
    native_tape: dict[int, list],
    market_reviews: dict[str, dict],
    proxy_reviews: dict[str, dict],
    proxy_eligible_ids: set[str],
    assumed_latency_ms: int,
) -> tuple[dict[int, list], dict[str, int] | None, tuple[Any, ...]]:
    """Compose the seven frozen arms without manufacturing calls or clocks."""
    from adaptive_replay.engine import AccountCost

    by_id = {intent.intent_id: (row, intent) for row, intent in candidates}
    if len(by_id) != len(candidates):
        raise ValueError("duplicate candidate identity in reconciliation roster")
    all_ids = set(by_id)
    if not set(market_reviews) == all_ids or not proxy_eligible_ids <= all_ids:
        raise ValueError("market or source-eligible review roster mismatch")
    if not set(proxy_reviews) == proxy_eligible_ids:
        raise ValueError("proxy review roster must equal dispatch-eligible candidates")

    def subset(ids: set[str]) -> dict[int, list]:
        return {
            ts: [intent for intent in intents if intent.intent_id in ids]
            for ts, intents in native_tape.items()
            if any(intent.intent_id in ids for intent in intents)
        }

    if arm == "strategy_only":
        return native_tape, None, ()
    if arm == "cash_only":
        return {}, None, ()
    if arm == "market_latency_cost_control":
        clocks, costs = _recorded_review_inputs(
            candidates, market_reviews, assumed_latency_ms
        )
        return native_tape, clocks, costs
    if arm == "market_llm_review":
        accepted, clocks, costs = _economic_inputs(
            candidates, market_reviews, assumed_latency_ms
        )
        return (
            accepted,
            clocks,
            tuple(
                AccountCost(candidate_id, at_ms, amount / 1_000_000, "MODEL")
                for candidate_id, at_ms, amount in costs
            ),
        )
    eligible_candidates = [
        by_id[candidate_id] for candidate_id in sorted(proxy_eligible_ids)
    ]
    if arm == "proxy_source_eligibility_control":
        # No review was performed in this control: retain source-eligible native
        # parents, use only the already-declared baseline latency and charge zero.
        return subset(proxy_eligible_ids), None, ()
    if arm == "proxy_latency_cost_control":
        clocks, costs = _recorded_review_inputs(
            eligible_candidates, proxy_reviews, assumed_latency_ms
        )
        return subset(proxy_eligible_ids), clocks, costs
    if arm == "proxy_review":
        accepted, clocks, costs = _economic_inputs(
            eligible_candidates, proxy_reviews, assumed_latency_ms
        )
        return (
            accepted,
            clocks,
            tuple(
                AccountCost(candidate_id, at_ms, amount / 1_000_000, "MODEL")
                for candidate_id, at_ms, amount in costs
            ),
        )
    raise ValueError("unknown reconciliation arm")


def _account_key(row: dict) -> tuple[str, str, str, str]:
    window = row["window"]
    window_id = window["id"] if type(window) is dict else window
    report = row.get("report", row.get("economic_report", {}))
    entry_mode = row.get("entry_mode", report.get("entry_mode"))
    cost_scenario = row.get("cost_scenario", report.get("cost_scenario"))
    return (
        window_id,
        entry_mode,
        cost_scenario["id"] if type(cost_scenario) is dict else cost_scenario,
        row["arm"],
    )


def _index_accounts(rows: Any, expected_arms: set[str], label: str) -> dict:
    if type(rows) is not list or not rows or any(type(row) is not dict for row in rows):
        raise ValueError(f"{label} account roster must be a nonempty list")
    indexed = {}
    for row in rows:
        key = _account_key(row)
        if key[3] not in expected_arms or key in indexed:
            raise ValueError(
                f"{label} account roster has duplicate or unexpected account"
            )
        report = row.get("report", row.get("economic_report"))
        if type(report) is not dict:
            raise ValueError(f"{label} account report is missing")
        equity, trades = report.get("final_equity_usd"), report.get("closed_trades")
        if (
            type(equity) not in (float, int)
            or not math.isfinite(equity)
            or type(trades) is not int
            or trades < 0
        ):
            raise ValueError(f"{label} account result is nonfinite or malformed")
        indexed[key] = report
    return indexed


def _reconcile_accounts(actual: list[dict], expected: list[dict], label: str) -> None:
    actual_index = _index_accounts(actual, {row["arm"] for row in actual}, label)
    expected_index = _index_accounts(
        expected, {row["arm"] for row in expected}, f"expected {label}"
    )
    if actual_index.keys() != expected_index.keys():
        raise ValueError(f"{label} account completion roster mismatch")
    for key, report in actual_index.items():
        original = expected_index[key]
        if report["closed_trades"] != original["closed_trades"] or not math.isclose(
            report["final_equity_usd"],
            original["final_equity_usd"],
            rel_tol=0,
            abs_tol=1e-8,
        ):
            raise ValueError(f"{label} cached account reproduction mismatch")


def _account_deltas(results: list[dict]) -> list[dict]:
    index = {_account_key(row): row["report"] for row in results}
    if len(index) != len(results):
        raise ValueError("duplicate account key in reconciliation results")
    comparisons = (
        (
            "market_review_increment_vs_latency_cost_control",
            "market_llm_review",
            "market_latency_cost_control",
        ),
        (
            "proxy_source_eligibility_vs_strategy",
            "proxy_source_eligibility_control",
            "strategy_only",
        ),
        (
            "proxy_timing_cost_vs_source_eligibility",
            "proxy_latency_cost_control",
            "proxy_source_eligibility_control",
        ),
        (
            "proxy_review_increment_vs_latency_cost_control",
            "proxy_review",
            "proxy_latency_cost_control",
        ),
    )
    deltas = []
    for key in sorted({k[:3] for k in index}):
        cash = index[(*key, "cash_only")]
        for row in results:
            if _account_key(row)[:3] != key:
                continue
            arm = row["arm"]
            report = row["report"]
            deltas.append(
                {
                    "window": key[0],
                    "entry_mode": key[1],
                    "cost_scenario": key[2],
                    "arm": arm,
                    "vs_cash_final_equity_usd": report["final_equity_usd"]
                    - cash["final_equity_usd"],
                    "vs_cash_closed_trades": report["closed_trades"]
                    - cash["closed_trades"],
                }
            )
        for label, left, right in comparisons:
            first = index[(*key, left)]
            second = index[(*key, right)]
            deltas.append(
                {
                    "window": key[0],
                    "entry_mode": key[1],
                    "cost_scenario": key[2],
                    "comparison": label,
                    "equity_delta_usd": first["final_equity_usd"]
                    - second["final_equity_usd"],
                    "closed_trade_delta": first["closed_trades"]
                    - second["closed_trades"],
                }
            )
    return deltas


def _remap_account_arms(rows: list[dict], mapping: dict[str, str]) -> list[dict]:
    remapped = []
    for original in rows:
        row = dict(original)
        row["arm"] = mapping.get(row["arm"], row["arm"])
        remapped.append(row)
    return remapped


def _candidate_audit(
    candidates: list[tuple[dict, Any]], market: dict, proxy: dict, requests: dict
) -> list[dict]:
    audit = []

    def candidate_key(item):
        row, intent = item
        request = requests[intent.intent_id]
        if (
            request.get("candidate_id") != intent.intent_id
            or request.get("slot_id") != row.get("slot_id")
            or request.get("historical_cut_ms") != intent.decision_ts_ms
        ):
            raise ValueError("candidate audit differs from original bound request")
        return request["window_id"], row["slot_id"]

    for row, intent in sorted(candidates, key=candidate_key):
        proxy_request = requests[intent.intent_id]
        eligible = proxy_request["dispatch_eligible"] is True
        market_review = market[intent.intent_id]
        proxy_review = proxy.get(intent.intent_id)
        audit.append(
            {
                "candidate_id": intent.intent_id,
                "window_id": proxy_request["window_id"],
                "slot_id": row["slot_id"],
                "decision_ts_ms": intent.decision_ts_ms,
                "native_side": intent.side.value,
                "market_review": {
                    "state": market_review["state"],
                    "decision": market_review["decision"],
                    "actual_microusd": market_review["actual_microusd"],
                    "duration_ms": market_review["measured_pipeline_duration_ms"],
                },
                "proxy_source_eligible": eligible,
                "proxy_review": (
                    {
                        "state": proxy_review["state"],
                        "decision": proxy_review["decision"],
                        "actual_microusd": proxy_review["actual_microusd"],
                        "duration_ms": proxy_review["measured_pipeline_duration_ms"],
                    }
                    if proxy_review is not None
                    else {
                        "state": NO_CALL,
                        "decision": "ABSTAIN",
                        "actual_microusd": 0,
                        "duration_ms": None,
                    }
                ),
            }
        )
    if len(audit) != 12 or len({row["candidate_id"] for row in audit}) != 12:
        raise ValueError("candidate audit must bind exactly twelve original candidates")
    return audit


def _reconciliation_preflight(args: Any) -> dict:
    if type(args.deadline_seconds) is not int or not 1 <= args.deadline_seconds <= 900:
        raise ValueError("deadline must be an integer from 1 to 900 seconds")
    if args.reconstruction_result is None:
        raise ValueError("--reconstruction-result is required for --reconcile-caches")
    if experiment.file_sha(args.reconstruction_result) != PRIOR_RECONSTRUCTION_SHA256:
        raise ValueError("prior reconstruction result does not match its accepted seal")
    if experiment.read_json(args.reconstruction_result).get("state") != RESULT_STATE:
        raise ValueError("prior reconstruction result is not completed")
    _plan, original_plan, reference = experiment.load_experiment(args)
    baseline, baseline_requests, _ = proxy_context._baseline(args.baseline)
    if (
        baseline["hashes"].get("result.json")
        != "a4b217693172e0d7af2d5db062b646fca7476c9974bb271157fdceb1c8ef83e8"
    ):
        raise ValueError(
            "market-review cache differs from the accepted October 10 result"
        )
    proxy_context._validate_admission(args.admission_result, baseline_requests)
    _source_bundle, source_sha = proxy_context._validate_sources(args.sources)
    proxy_hashes = _proxy_file_hashes(args.proxy_run)
    capture_signature = _validate_capture_signature(args)
    proxy_reviews, proxy_requests = _proxy_receipts(args, baseline, baseline_requests)
    sealed_proxy_plan = experiment.read_json(args.proxy_run / "sealed-plan.json")
    prior_hold = _known_prior_hold(sealed_proxy_plan)
    if (
        len(baseline_requests) != 12
        or len(baseline["result"].get("results", [])) != 48
        or len(proxy_reviews) != 9
        or sum(1 for request in proxy_requests.values() if request["dispatch_eligible"])
        != 9
        or source_sha != sealed_proxy_plan.get("source_bundle_sha256")
        or len(original_plan["windows"]) != 4
        or len(reference["windows"]) != 4
    ):
        raise ValueError(
            "cached review/source/window completion rosters differ from the fixed protocol"
        )
    _source_identity = experiment.source_identity(original_plan, reference)
    return {
        "source_identity": _source_identity,
        "baseline_hashes": baseline["hashes"],
        "proxy_file_hashes": proxy_hashes,
        "source_bundle_sha256": source_sha,
        "raw_capture_signature": capture_signature,
        "proxy_plan_sha256": experiment.file_sha(args.proxy_run / "sealed-plan.json"),
        "admission_result_sha256": experiment.file_sha(args.admission_result),
        "admission_contexts_sha256": experiment.file_sha(
            args.admission_result.with_name("candidate-contexts.jsonl")
        ),
        "prior_reconstruction_sha256": PRIOR_RECONSTRUCTION_SHA256,
        "unresolved_prior_hold_microusd": prior_hold["unresolved_held_cost_microusd"],
        "adapter_sha256": experiment.file_sha(Path(__file__)),
        "created_utc": experiment.now(),
    }


def _cached_reconciliation(args: Any, before: dict) -> dict:
    """Run one bounded seven-arm comparison from already-cached source receipts."""
    if type(args.deadline_seconds) is not int or not 1 <= args.deadline_seconds <= 900:
        raise ValueError("deadline must be an integer from 1 to 900 seconds")
    if experiment.file_sha(args.reconstruction_result) != PRIOR_RECONSTRUCTION_SHA256:
        raise ValueError("prior reconstruction result does not match its accepted seal")
    prior_reconstruction = experiment.read_json(args.reconstruction_result)
    if prior_reconstruction.get("state") != RESULT_STATE:
        raise ValueError("prior reconstruction result is not completed")

    deadline = time.monotonic() + args.deadline_seconds
    before_sha = experiment.file_sha(args.output / "before.json")
    _plan, original_plan, reference = experiment.load_experiment(args)
    baseline, baseline_requests, market_reviews = proxy_context._baseline(args.baseline)
    if (
        baseline["hashes"].get("result.json")
        != "a4b217693172e0d7af2d5db062b646fca7476c9974bb271157fdceb1c8ef83e8"
    ):
        raise ValueError(
            "market-review cache differs from the accepted October 10 result"
        )
    proxy_context._validate_admission(args.admission_result, baseline_requests)
    _source_bundle, source_sha = proxy_context._validate_sources(args.sources)
    proxy_hashes = _proxy_file_hashes(args.proxy_run)
    capture_signature = _validate_capture_signature(args)
    proxy_reviews, proxy_requests = _proxy_receipts(args, baseline, baseline_requests)
    prior_hold = _known_prior_hold(
        experiment.read_json(args.proxy_run / "sealed-plan.json")
    )
    if (
        len(market_reviews) != 12
        or len(proxy_reviews) != 9
        or sum(1 for request in proxy_requests.values() if request["dispatch_eligible"])
        != 9
        or source_sha
        != experiment.read_json(args.proxy_run / "sealed-plan.json").get(
            "source_bundle_sha256"
        )
    ):
        raise ValueError(
            "cached review/source completion rosters differ from the fixed protocol"
        )
    source_identity = experiment.source_identity(original_plan, reference)
    baseline_hashes = baseline["hashes"]
    proxy_plan_hash = experiment.file_sha(args.proxy_run / "sealed-plan.json")
    admission_hashes = {
        "result": experiment.file_sha(args.admission_result),
        "contexts": experiment.file_sha(
            args.admission_result.with_name("candidate-contexts.jsonl")
        ),
    }
    cache_snapshot = {
        "baseline": baseline_hashes,
        "proxy": proxy_hashes,
        "source_bundle_sha256": source_sha,
        "raw_capture_signature": capture_signature,
        "proxy_plan_sha256": proxy_plan_hash,
        "admission_sha256": admission_hashes,
        "prior_reconstruction_sha256": PRIOR_RECONSTRUCTION_SHA256,
        "adapter_sha256": experiment.file_sha(Path(__file__)),
    }
    if (
        source_identity != before["source_identity"]
        or baseline_hashes != before["baseline_hashes"]
        or proxy_hashes != before["proxy_file_hashes"]
        or source_sha != before["source_bundle_sha256"]
        or capture_signature != before["raw_capture_signature"]
        or proxy_plan_hash != before["proxy_plan_sha256"]
        or admission_hashes
        != {
            "result": before["admission_result_sha256"],
            "contexts": before["admission_contexts_sha256"],
        }
        or cache_snapshot["adapter_sha256"] != before["adapter_sha256"]
    ):
        raise ValueError("pre-replay cache/source snapshot changed")

    from adaptive_replay.engine import CostScenario, replay_tape

    results = []
    candidates_all = []
    input_evidence = {}
    window_denominators = {}
    for window, original in zip(
        original_plan["windows"], reference["windows"], strict=True
    ):
        if time.monotonic() > deadline:
            raise TimeoutError("bounded cached reconciliation deadline exceeded")
        inputs, native_tape, candidates = experiment.validated_window(
            args, window, original, original_plan
        )
        candidate_ids = {intent.intent_id for _, intent in candidates}
        window_id = window["id"]
        if len(candidate_ids) != original["counts"]["candidates"]:
            raise ValueError(
                "native candidate denominator differs from sealed reference"
            )
        candidates_all.extend(candidates)
        input_evidence[window_id] = experiment.digest(inputs.evidence)
        decision_path = args.reference / window_id / "decisions.jsonl"
        decision_rows = [
            json.loads(line)
            for line in decision_path.read_text(encoding="utf-8").splitlines()
        ]
        no_intent = sum(1 for slot in decision_rows if slot.get("intent") is None)
        expected_slots = original["counts"].get("scheduled_slots")
        if (
            type(expected_slots) is not int
            or expected_slots != 4_320
            or len(decision_rows) != expected_slots
        ):
            raise ValueError(
                "full scheduled-slot denominator differs from frozen reference"
            )
        slot_statuses = Counter(row.get("status") for row in decision_rows)
        if slot_statuses != Counter(original["counts"].get("statuses", {})):
            raise ValueError("full slot-state counts differ from frozen reference")
        if (
            len(
                {
                    (row.get("symbol"), row.get("logical_decision_ms"))
                    for row in decision_rows
                }
            )
            != expected_slots
        ):
            raise ValueError("duplicate full slot identity")
        window_denominators[window_id] = {
            "slots": len(decision_rows),
            "candidates": len(candidates),
            "no_intent": no_intent,
            "tape_sha256": original["counts"]["tape_sha256"],
        }
        win_market = {
            candidate_id: market_reviews[candidate_id] for candidate_id in candidate_ids
        }
        win_proxy = {
            candidate_id: proxy_reviews[candidate_id]
            for candidate_id in candidate_ids
            if candidate_id in proxy_reviews
        }
        win_eligible = {
            candidate_id
            for candidate_id in candidate_ids
            if proxy_requests[candidate_id]["dispatch_eligible"] is True
        }
        for mode in original_plan["entry_modes"]:
            for specification in original_plan["cost_scenarios"]:
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        "bounded cached reconciliation deadline exceeded"
                    )
                scenario = CostScenario(**specification)
                for arm in RECONCILIATION_ARMS:
                    tape, clocks, service_costs = _reconciliation_arm_inputs(
                        arm,
                        candidates,
                        native_tape,
                        win_market,
                        win_proxy,
                        win_eligible,
                        original_plan["pipeline_latency_ms_assumed"],
                    )
                    report, account = replay_tape(
                        inputs,
                        tape,
                        scenario,
                        mode,
                        original_plan["pipeline_latency_ms_assumed"],
                        original_plan["exit_tail_hours"],
                        completion_times_ms=clocks,
                        service_costs=service_costs,
                        deadline=deadline,
                    )
                    if (
                        not math.isfinite(report.get("final_equity_usd", float("nan")))
                        or abs(
                            report.get("ledger_reconciliation_error_usd", float("inf"))
                        )
                        >= 1e-8
                        or report.get("terminal_unresolved_positions") != []
                        or report.get("forced_settlements") != 0
                        or report.get("risk_ceiling_mark_overrun") != 0
                        or report.get("gross_ceiling_mark_overrun") != 0
                        or report.get("realized_loss_over_reservation_count") != 0
                    ):
                        raise ValueError(
                            "account failed finite ledger/exit/risk reconciliation"
                        )
                    if arm == "cash_only" and (
                        report["final_equity_usd"] != 10_000
                        or report["closed_trades"] != 0
                        or report["model_calls"] != 0
                        or report["model_cost_usd"] is not None
                        or account.events
                    ):
                        raise ValueError(
                            "cash-only anchor must remain exactly $10000 with no events"
                        )
                    results.append(
                        {
                            "window": window_id,
                            "entry_mode": mode,
                            "cost_scenario": scenario.id,
                            "arm": arm,
                            "report": report,
                            "known_model_cost_microusd": sum(
                                round(cost.amount_usd * 1_000_000)
                                for cost in service_costs
                            ),
                            "model_calls_observed": len(service_costs),
                            "ledger": {
                                "events": account.events,
                                "trades": account.trades,
                            },
                        }
                    )
    if len(candidates_all) != 12 or len(results) != 112:
        raise ValueError("candidate/account result roster is incomplete")
    keys = [_account_key(row) for row in results]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate account in seven-arm roster")
    for row in results:
        report = row["report"]
        if not math.isfinite(report.get("final_equity_usd", float("nan"))):
            raise ValueError("reconciliation produced nonfinite account equity")

    # Reproduce all three original market-review arms (48 accounts), and both
    # arms from the already-sealed proxy result (32 accounts), without changing them.
    market_actual = [
        row
        for row in results
        if row["arm"]
        in {"strategy_only", "market_latency_cost_control", "market_llm_review"}
    ]
    market_actual = _remap_account_arms(
        market_actual, {"market_latency_cost_control": "latency_cost_control"}
    )
    _reconcile_accounts(market_actual, baseline["result"]["results"], "market baseline")
    proxy_actual = [
        row for row in results if row["arm"] in {"strategy_only", "proxy_review"}
    ]
    proxy_actual = _remap_account_arms(
        proxy_actual, {"proxy_review": "publication_news_macro_review_reconstruction"}
    )
    _reconcile_accounts(
        proxy_actual, prior_reconstruction["results"], "prior publication-proxy"
    )

    if time.monotonic() > deadline:
        raise TimeoutError("bounded cached reconciliation deadline exceeded")
    # Re-open every input and receipt after economic replay; changes fail closed.
    for window, original in zip(
        original_plan["windows"], reference["windows"], strict=True
    ):
        inputs, _tape, _candidates = experiment.validated_window(
            args, window, original, original_plan
        )
        if experiment.digest(inputs.evidence) != input_evidence[window["id"]]:
            raise ValueError(
                "market/factor evidence changed during cached reconciliation"
            )
    baseline_after, baseline_requests_after, _ = proxy_context._baseline(args.baseline)
    proxy_context._validate_admission(args.admission_result, baseline_requests)
    _sources_after, source_sha_after = proxy_context._validate_sources(args.sources)
    if (
        experiment.source_identity(original_plan, reference) != source_identity
        or baseline_after["hashes"] != baseline_hashes
        or baseline_requests_after != baseline_requests
        or source_sha_after != source_sha
        or _proxy_file_hashes(args.proxy_run) != proxy_hashes
        or _validate_capture_signature(args) != capture_signature
        or experiment.file_sha(args.admission_result) != admission_hashes["result"]
        or experiment.file_sha(
            args.admission_result.with_name("candidate-contexts.jsonl")
        )
        != admission_hashes["contexts"]
        or experiment.file_sha(args.reconstruction_result)
        != PRIOR_RECONSTRUCTION_SHA256
        or experiment.file_sha(Path(__file__)) != cache_snapshot["adapter_sha256"]
        or experiment.file_sha(args.output / "before.json") != before_sha
    ):
        raise ValueError("source/capture/cache identity changed during reconciliation")
    if time.monotonic() > deadline:
        raise TimeoutError("bounded cached reconciliation deadline exceeded")

    audit = _candidate_audit(
        candidates_all, market_reviews, proxy_reviews, proxy_requests
    )
    expected_costs = {
        "market_microusd": 8_804,
        "proxy_microusd": 5_411,
        "physically_unique_microusd": 14_215,
    }
    market_cost = sum(row["actual_microusd"] for row in market_reviews.values())
    proxy_cost = sum(row["actual_microusd"] for row in proxy_reviews.values())
    if (market_cost, proxy_cost) != (8_804, 5_411):
        raise ValueError("cached call-cost totals differ from exact retained responses")
    return {
        "schema": RECONCILE_SCHEMA,
        "state": RECONCILE_STATE,
        "created_utc": experiment.now(),
        "candidate_count": 12,
        "new_provider_calls": 0,
        "blind_days_added": 0,
        "naturally_closed_campaign_trades_added": 0,
        "readiness": original_plan["readiness"],
        "windows": window_denominators,
        "account_count": len(results),
        "arm_account_roster": {
            arm: sum(row["arm"] == arm for row in results)
            for arm in RECONCILIATION_ARMS
        },
        "candidate_audit": audit,
        "cached_call_costs_microusd": {
            **expected_costs,
            "market": market_cost,
            "proxy": proxy_cost,
        },
        "alternative_replays_are_not_additional_physical_spend": True,
        "prior_unresolved_cost": prior_hold,
        "delta_rows": _account_deltas(results),
        "results": results,
        "source_identity": source_identity,
        "cache_snapshot": cache_snapshot,
        "attribution": {
            "market_review": "market-only cached assessment; not NEWS/Macro effect",
            "proxy_review": "publication-time proxy; source eligibility is not historical availability",
            "matched_or_causal": False,
            "current_catalyst_or_full_system": False,
            "provider_calls": 0,
            "database_or_network_calls": 0,
            "trading_or_readiness_authority": False,
        },
        "limitations": [
            "Seven arms are separate offline replays of fixed native candidates, not a matched causal NEWS/Macro experiment.",
            "The market cache has NEWS and Macro unavailable; the proxy cache has unknown coverage and unproven historical availability/receipt time.",
            "Three proxy NO_CALL candidates remain ABSTAIN in every proxy arm; no response duration or fee is invented.",
            "This does not evaluate the current event-origin Catalyst policy or establish strict-native, full-system, alpha, or LIVE evidence.",
        ],
    }


def _index_candidate_results(
    candidate_results: Any, expected_ids: set[str]
) -> dict[str, dict]:
    if (
        type(candidate_results) is not list
        or len(candidate_results) != len(expected_ids)
        or any(type(row) is not dict for row in candidate_results)
    ):
        raise ValueError("cached proxy completion result roster incomplete")
    ids = [row.get("candidate_id") for row in candidate_results]
    if len(set(ids)) != len(ids) or set(ids) != expected_ids:
        raise ValueError(
            "cached proxy completion result has duplicate or missing candidates"
        )
    return {row["candidate_id"]: row for row in candidate_results}


def _write_failure_receipt(output: Path, exc: Exception) -> None:
    """Write a create-only, sanitized marker for a failed new output directory."""
    failure_path = output / "failure.json"
    if output.is_dir() and not failure_path.exists():
        experiment.write_json(
            failure_path,
            {
                "state": "FAILED_CLOSED",
                "error_type": type(exc).__name__,
                "finished_utc": experiment.now(),
            },
        )


def _validate_before(
    before: dict,
    source_identity: dict,
    baseline_hashes: dict,
    adapter_sha: str,
) -> None:
    if before.get("source_identity") != source_identity:
        raise ValueError("pre-replay source identity does not match current inputs")
    if before.get("baseline_hashes") != baseline_hashes:
        raise ValueError("pre-replay baseline hashes do not match frozen baseline")
    if (
        before.get("filter_policy") != FILTER_POLICY
        or before.get("adapter_sha256") != adapter_sha
    ):
        raise ValueError("filter inference/policy not sealed before replay")


def run(args: Any) -> dict:
    if type(args.deadline_seconds) is not int or not 1 <= args.deadline_seconds <= 900:
        raise ValueError("deadline must be an integer from 1 to 900 seconds")
    deadline = time.monotonic() + args.deadline_seconds
    before = experiment.read_json(args.output / "before.json")
    before_sha = experiment.file_sha(args.output / "before.json")
    adapter_sha = experiment.file_sha(Path(__file__))
    _plan, original_plan, reference = experiment.load_experiment(args)
    baseline, baseline_requests, _ = proxy_context._baseline(args.baseline)
    current_source_identity = experiment.source_identity(original_plan, reference)
    _validate_before(before, current_source_identity, baseline["hashes"], adapter_sha)
    _admission, _ = proxy_context._validate_admission(
        args.admission_result, baseline_requests
    )
    _source_bundle, source_sha = proxy_context._validate_sources(args.sources)
    proxy_plan = experiment.read_json(args.proxy_run / "sealed-plan.json")
    proxy_before = experiment.read_json(args.proxy_run / "before.json")
    proxy_hashes_before = _proxy_file_hashes(args.proxy_run)
    capture_signature_before = _validate_capture_signature(args)
    if (
        source_sha != proxy_plan.get("source_bundle_sha256")
        or source_sha != proxy_before.get("source_bundle_sha256")
        or before.get("source_bundle_sha256") != source_sha
        or before.get("admission_result_sha256")
        != experiment.file_sha(args.admission_result)
        or before.get("admission_contexts_sha256")
        != experiment.file_sha(
            args.admission_result.with_name("candidate-contexts.jsonl")
        )
        or before.get("proxy_file_hashes") != proxy_hashes_before
        or before.get("raw_input_signature") != capture_signature_before
        or experiment.file_sha(args.admission_result)
        != proxy_plan.get("admission_result_sha256")
        or experiment.file_sha(
            args.admission_result.with_name("candidate-contexts.jsonl")
        )
        != proxy_before.get("admission_contexts_sha256")
    ):
        raise ValueError(
            "source/admission input differs from sealed proxy reconstruction"
        )
    observations, proxy_requests = _proxy_receipts(args, baseline, baseline_requests)
    prior_hold = _known_prior_hold(proxy_plan)
    sources_before = current_source_identity

    from adaptive_replay.engine import AccountCost, CostScenario, replay_tape

    results = []
    candidate_decisions = []
    input_evidence = {}
    per_window_cost = Counter()
    for candidate_id, review in observations.items():
        per_window_cost[proxy_requests[candidate_id]["window_id"]] += review[
            "actual_microusd"
        ]

    for window, original in zip(
        original_plan["windows"], reference["windows"], strict=True
    ):
        if time.monotonic() > deadline:
            raise TimeoutError("bounded reconstruction deadline exceeded")
        inputs, native_tape, candidates = experiment.validated_window(
            args, window, original, original_plan
        )
        if time.monotonic() > deadline:
            raise TimeoutError("bounded reconstruction deadline exceeded")
        input_evidence[window["id"]] = experiment.digest(inputs.evidence)
        identities = {intent.intent_id for _, intent in candidates}
        if identities != {
            r["candidate_id"]
            for r in proxy_requests.values()
            if r["window_id"] == window["id"]
        }:
            raise ValueError(
                "reconstructed native tape differs from proxy candidate roster"
            )
        filtered_tape, completion_times, service_cost_records = _economic_inputs(
            candidates,
            {
                identity: observations[identity]
                for identity in identities
                if identity in observations
            },
            original_plan["pipeline_latency_ms_assumed"],
        )
        window_costs = [
            AccountCost(
                candidate_id,
                modeled_at,
                amount_microusd / 1_000_000,
                "MODEL",
            )
            for candidate_id, modeled_at, amount_microusd in service_cost_records
        ]
        modeled_times = {
            candidate_id: modeled_at
            for candidate_id, modeled_at, _ in service_cost_records
        }
        for _, intent in candidates:
            review = observations.get(intent.intent_id)
            request = proxy_requests[intent.intent_id]
            if review is None:
                candidate_decisions.append(
                    {
                        "candidate_id": intent.intent_id,
                        "window_id": window["id"],
                        "status": NO_CALL,
                        "decision": "ABSTAIN",
                        "source_status": request["no_call_reason"],
                        "actual_microusd": 0,
                    }
                )
                continue
            completed_at = modeled_times[intent.intent_id]
            candidate_decisions.append(
                {
                    "candidate_id": intent.intent_id,
                    "window_id": window["id"],
                    "status": REVIEWED,
                    "decision": review["decision"],
                    "actual_microusd": review["actual_microusd"],
                    "modern_response_observed_ms": review[
                        "modern_response_observed_ms"
                    ],
                    "measured_pipeline_duration_ms": review[
                        "measured_pipeline_duration_ms"
                    ],
                    "modeled_historical_completion_ms": completed_at,
                }
            )
        if (
            sum(round(c.amount_usd * 1_000_000) for c in window_costs)
            != per_window_cost[window["id"]]
        ):
            raise ValueError("per-window known cost reconciliation failed")
        for mode in original_plan["entry_modes"]:
            for specification in original_plan["cost_scenarios"]:
                if time.monotonic() > deadline:
                    raise TimeoutError("bounded reconstruction deadline exceeded")
                scenario = CostScenario(**specification)
                for arm, tape, clocks, costs in (
                    ("strategy_only", native_tape, None, ()),
                    (
                        "publication_news_macro_review_reconstruction",
                        filtered_tape,
                        completion_times,
                        tuple(window_costs),
                    ),
                ):
                    report, account = replay_tape(
                        inputs,
                        tape,
                        scenario,
                        mode,
                        original_plan["pipeline_latency_ms_assumed"],
                        original_plan["exit_tail_hours"],
                        completion_times_ms=clocks,
                        service_costs=costs,
                        deadline=deadline,
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
                                "unchanged native baseline reproduction mismatch"
                            )
                    results.append(
                        {
                            "window": window["id"],
                            "entry_mode": mode,
                            "cost_scenario": scenario.id,
                            "arm": arm,
                            "report": report,
                            "known_model_cost_microusd": per_window_cost[window["id"]]
                            if arm != "strategy_only"
                            else 0,
                            "ledger": {
                                "events": account.events,
                                "trades": account.trades,
                            },
                        }
                    )
    if time.monotonic() > deadline:
        raise TimeoutError("bounded reconstruction deadline exceeded")
    for window, original in zip(
        original_plan["windows"], reference["windows"], strict=True
    ):
        if time.monotonic() > deadline:
            raise TimeoutError("bounded reconstruction deadline exceeded")
        reloaded, _tape, _candidates = experiment.validated_window(
            args, window, original, original_plan
        )
        if experiment.digest(reloaded.evidence) != input_evidence[window["id"]]:
            raise ValueError("bar/factor input evidence changed during replay")
    if experiment.source_identity(original_plan, reference) != sources_before:
        raise ValueError("experiment source identity changed during reconstruction")
    if experiment.file_sha(Path(__file__)) != adapter_sha:
        raise ValueError("adapter/policy source changed during reconstruction")
    baseline_after, _requests_after, _reviews_after = proxy_context._baseline(
        args.baseline
    )
    proxy_context._validate_admission(args.admission_result, baseline_requests)
    if baseline_after["hashes"] != baseline["hashes"]:
        raise ValueError("frozen baseline changed during reconstruction")
    _source_bundle_after, source_sha_after = proxy_context._validate_sources(
        args.sources
    )
    if source_sha_after != source_sha:
        raise ValueError("source bundle changed during reconstruction")
    if (
        experiment.file_sha(args.admission_result)
        != proxy_plan["admission_result_sha256"]
        or experiment.file_sha(
            args.admission_result.with_name("candidate-contexts.jsonl")
        )
        != proxy_before["admission_contexts_sha256"]
    ):
        raise ValueError("admission evidence changed during reconstruction")
    _proxy_receipts(args, baseline, baseline_requests)
    if _proxy_file_hashes(args.proxy_run) != proxy_hashes_before:
        raise ValueError("cached proxy artifacts changed during reconstruction")
    if _validate_capture_signature(args) != capture_signature_before:
        raise ValueError("raw publication captures changed during reconstruction")
    if experiment.file_sha(args.output / "before.json") != before_sha:
        raise ValueError("pre-replay policy/source seal changed during reconstruction")
    if (
        experiment.file_sha(args.admission_result)
        != proxy_plan["admission_result_sha256"]
    ):
        raise ValueError("admission evidence changed during reconstruction")

    return {
        "schema": RESULT_SCHEMA,
        "state": RESULT_STATE,
        "candidate_count": 12,
        "windows": 4,
        "cached_model_observations": 9,
        "missing_proxy_context_no_calls": 3,
        "new_provider_calls": 0,
        "known_model_cost_microusd": sum(per_window_cost.values()),
        "prior_unresolved_cost": prior_hold,
        "coverage": "UNKNOWN",
        "full_system_proof": False,
        "full_news_macro_system_tested": False,
        "comparison_is_matched_or_causal": False,
        "candidate_filtering_only": True,
        "filter_policy": FILTER_POLICY,
        "declared_inference": "Only an observed explicit ALLOW keeps an unchanged candidate; VETO/DEFER filter it; missing context abstains. This exploratory choice was sealed before replay.",
        "observed_reviews_all_defer": True,
        "independent_proposals_tested": False,
        "uses_current_catalyst_policy": False,
        "no_intent_or_event_origin_or_countertrend_tests": True,
        "paid_budget_mutation": False,
        "blind_days_added": 0,
        "readiness": {
            "technical_paper_ready": False,
            "paper_qualified": False,
            "alpha_ready": False,
            "live_ready": False,
            "strategy_policy": "REJECT_ALL",
        },
        "baseline_result_sha256": baseline["hashes"]["result.json"],
        "proxy_result_sha256": experiment.file_sha(
            args.proxy_run / "proxy-diagnostic-result.json"
        ),
        "source_identity": sources_before,
        "decision_counts": dict(
            Counter(row["decision"] for row in candidate_decisions)
        ),
        "candidate_decisions": candidate_decisions,
        "results": results,
        "limitations": [
            "This is an approximate reconstruction, not strict-native or full current catalyst policy.",
            "Three missing-context candidates abstain; they are not labeled VETO.",
            "Modern observed response durations plus the frozen 100ms baseline are mapped into historical clocks.",
            "Unknown source coverage/authenticity and noncontemporaneous responses prevent causal or alpha claims.",
            "Accounts start independently at $10000 per disjoint window; no cross-window compounding or risk changes.",
            "Strict minute and intrabar-open modes are sensitivities over the same fixed tape.",
            "Known review costs include every observed response, including DEFER; prior holds remain separately uncertain.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "strategy-plan",
        "reference",
        "bar-cache",
        "factor-cache",
        "baseline",
        "sources",
        "capture-manifest",
        "admission-result",
        "proxy-run",
        "output",
    ):
        parser.add_argument(
            f"--{name}", dest=name.replace("-", "_"), type=Path, required=True
        )
    parser.add_argument("--deadline-seconds", type=int, default=900)
    parser.add_argument(
        "--reconcile-caches",
        action="store_true",
        help="run the separate seven-arm cached-only reconciliation; never calls providers",
    )
    parser.add_argument("--reconstruction-result", type=Path)
    args = parser.parse_args(argv)
    args.plan = Path(__file__).with_name("plan.json")
    created_output = False
    try:
        if args.reconcile_caches:
            if args.output.exists():
                raise FileExistsError(
                    "output must be a new directory; no resume/overwrite"
                )
            before = _reconciliation_preflight(args)
            args.output.mkdir(parents=True, exist_ok=False)
            created_output = True
            experiment.write_json(args.output / "before.json", before)
            result = _cached_reconciliation(args, before)
            result["finished_utc"] = experiment.now()
            experiment.write_json(args.output / "result.json", result)
            experiment.write_json(
                args.output / "seal.json",
                {
                    "before_sha256": experiment.file_sha(args.output / "before.json"),
                    "result_sha256": experiment.file_sha(args.output / "result.json"),
                    "sealed_utc": experiment.now(),
                },
            )
            print(
                f"state={RECONCILE_STATE} candidates=12 accounts=112 provider_calls=0"
            )
            return 0
        # Validate all immutable cached inputs before creating the new output.
        _plan, original_plan, reference = experiment.load_experiment(args)
        baseline, requests, _ = proxy_context._baseline(args.baseline)
        proxy_context._validate_admission(args.admission_result, requests)
        _source_bundle, source_sha = proxy_context._validate_sources(args.sources)
        proxy_hashes = _proxy_file_hashes(args.proxy_run)
        capture_signature = _validate_capture_signature(args)
        _proxy_receipts(args, baseline, requests)
        if (
            _proxy_file_hashes(args.proxy_run) != proxy_hashes
            or _validate_capture_signature(args) != capture_signature
        ):
            raise ValueError("cached proxy artifacts changed during preflight")
        admission_sha = experiment.file_sha(args.admission_result)
        admission_contexts_sha = experiment.file_sha(
            args.admission_result.with_name("candidate-contexts.jsonl")
        )
        if args.output.exists():
            raise FileExistsError("output must be a new directory; no resume/overwrite")
        args.output.mkdir(parents=True, exist_ok=False)
        created_output = True
        source_identity = experiment.source_identity(original_plan, reference)
        experiment.write_json(
            args.output / "before.json",
            {
                "source_identity": source_identity,
                "baseline_hashes": baseline["hashes"],
                "source_bundle_sha256": source_sha,
                "admission_result_sha256": admission_sha,
                "admission_contexts_sha256": admission_contexts_sha,
                "proxy_file_hashes": proxy_hashes,
                "raw_input_signature": capture_signature,
                "filter_policy": FILTER_POLICY,
                "adapter_sha256": experiment.file_sha(Path(__file__)),
                "created_utc": experiment.now(),
            },
        )
        result = run(args)
        result["finished_utc"] = experiment.now()
        experiment.write_json(args.output / "result.json", result)
        experiment.write_json(
            args.output / "seal.json",
            {
                "result_sha256": experiment.file_sha(args.output / "result.json"),
                "before_sha256": experiment.file_sha(args.output / "before.json"),
                "sealed_utc": experiment.now(),
            },
        )
        print(f"state={RESULT_STATE} candidates=12 windows=4 provider_calls=0")
        return 0
    except Exception as exc:  # noqa: BLE001 - fail closed without exposing paths
        if created_output:
            with suppress(Exception):
                _write_failure_receipt(args.output, exc)
        print(f"state=FAILED_CLOSED error={type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
