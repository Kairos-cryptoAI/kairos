"""Offline admission check of retained market inputs against current review gates.

This is not a replay of historical NEWS/MACRO delivery and never calls a provider.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_comparison as experiment

LOCK_PATH = Path(r"D:\Kairos\kairos-deploy\tests\current_release_gate\source-lock.json")
OLD_REQUESTS = Path(__file__).resolve().parents[1] / "evidence/2026-10-10/requests.json"
OLD_REVIEWS = Path(__file__).resolve().parents[1] / "evidence/2026-10-10/reviews.jsonl"
MAX_SECONDS = 175


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_id(value: Any) -> str:
    return str(getattr(value, "message_id", getattr(value, "route_id", "")))


class CaptureBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, Any]] = []

    async def publish(self, topic: str, message: Any) -> str:
        self.published.append((topic, message))
        return safe_id(message)


class ForbiddenGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, **_kwargs: Any) -> Any:
        self.calls += 1
        raise RuntimeError("provider gateway is forbidden in this offline checker")


def current_sources(lock: dict[str, Any]) -> dict[str, Any]:
    from importlib.metadata import distribution, distributions

    from adaptive_replay import inputs
    from kairos_aggregator import candidate_review, candidate_service
    from kairos_aggregator import config as aggregator_config
    from kairos_backtest import cost_risk, data, factor_data, validation
    from kairos_core import canonical_sha256
    from kairos_router import aggregation, candidate
    from kairos_strategy import candles, runtime
    from kairos_strategy.adaptive import adapter, logic
    from kairos_strategy.adaptive.provenance import adaptive_source_identity

    for package, entry in lock["dependencies"].items():
        info = json.loads(distribution(package).read_text("direct_url.json") or "{}")
        if info.get("vcs_info", {}).get("commit_id") != entry["revision"]:
            raise ValueError(f"installed pinned revision mismatch: {package}")
        if info.get("dir_info", {}).get("editable"):
            raise ValueError(f"editable dependency rejected: {package}")
    modules = (
        candidate_service,
        candidate_review,
        aggregator_config,
        aggregation,
        candidate,
        candles,
        runtime,
        logic,
        adapter,
    )
    return {
        "engineering_manifest_identity_sha256": canonical_sha256(lock),
        "modules_sha256": {
            module.__name__: sha_file(Path(module.__file__)) for module in modules
        },
        "adaptive_identity": asdict(adaptive_source_identity()),
        "input_loader_sha256": sha_file(Path(inputs.__file__)),
        "reused_backtest_modules_sha256": {
            module.__name__: sha_file(Path(module.__file__))
            for module in (cost_risk, data, factor_data, validation)
        },
        "installed_versions": {
            package.metadata["Name"]: package.version for package in distributions()
        },
    }


def signature(
    args: Any, windows: list[dict[str, Any]], ref_windows: list[dict[str, Any]]
) -> dict:
    snapshot: dict[str, Any] = {
        "plan": sha_file(args.plan),
        "strategy_plan": sha_file(args.strategy_plan),
        "reference_result": sha_file(args.reference / "result.json"),
        "source_lock": sha_file(LOCK_PATH),
        "checker": sha_file(Path(__file__)),
        "comparison_loader": sha_file(Path(experiment.__file__)),
        "saved_requests": sha_file(OLD_REQUESTS),
        "saved_reviews": sha_file(OLD_REVIEWS),
        "windows": {},
    }
    for window, reference_window in zip(windows, ref_windows, strict=True):
        tape = args.reference / window["id"] / "decisions.jsonl"
        receipt = args.reference / window["id"] / "inputs.json"
        snapshot["windows"][window["id"]] = {
            "tape_sha256": sha_file(tape),
            "receipt_sha256": sha_file(receipt),
            "expected_tape_sha256": reference_window["counts"]["tape_sha256"],
        }
    return snapshot


async def review_one(
    inputs: Any,
    original_row: dict,
    original_intent: Any,
    window_id: str,
    source_sha256: str,
) -> dict:
    from kairos_aggregator.candidate_service import CandidateReviewService
    from kairos_aggregator.config import AggregatorSettings
    from kairos_core import Topics
    from kairos_core.bus.base import BusEnvelope
    from kairos_router.aggregation import TextAggregate
    from kairos_router.candidate import CandidateRouterPolicy
    from kairos_strategy.adaptive import evaluate_adaptive_closed_bars
    from kairos_strategy.adaptive.config import DEFAULT_CONFIG
    from kairos_strategy.runtime import candle_to_closed_bar

    actual_started_utc = utc_now()
    cut_ms = original_intent.decision_ts_ms
    rows = tuple(
        row
        for row in inputs.bars[original_intent.symbol]
        if row.close_time_ms <= cut_ms
    )
    if not rows or rows[-1].close_time_ms != cut_ms:
        raise ValueError("candidate cutoff lacks its closed market candle")
    end = (cut_ms + 1 - inputs.data_start_ms) // 60_000
    prefix = tuple(
        candle_to_closed_bar(row)
        for row in inputs.bars[original_intent.symbol][
            end - DEFAULT_CONFIG.history_bars : end
        ]
    )
    if len(prefix) != DEFAULT_CONFIG.history_bars:
        raise ValueError("current evaluator prefix is incomplete")
    current = evaluate_adaptive_closed_bars(
        prefix, observed_at_ms=cut_ms + 1, source_set_sha256=source_sha256
    )
    if current.decision.intent is None or current.intent is None:
        raise ValueError("current strict evaluator produced no candidate")
    original_geometry = asdict(original_intent)
    current_geometry = asdict(current.decision.intent)
    if experiment.canonical(original_geometry) != experiment.canonical(
        current_geometry
    ):
        raise ValueError("current pure candidate geometry differs from original")
    geometry_fields = (
        "symbol",
        "side",
        "decision_ts_ms",
        "entry_eligible_ts_ms",
        "entry_expires_ts_ms",
        "reference_price",
        "signal_strength",
        "gross_reward_bps",
        "metadata",
    )
    original_semantics = {
        field: getattr(original_intent, field) for field in geometry_fields
    }
    strict_semantics = {
        field: getattr(current.intent, field) for field in geometry_fields
    }
    original_semantics["strategy_id"] = original_intent.sleeve_id
    strict_semantics["strategy_id"] = current.intent.strategy_id
    for field in ("stop_price", "target_price", "max_holding_ms"):
        original_semantics[field] = getattr(original_intent.exit_plan, field)
        strict_semantics[field] = getattr(current.intent.exit_plan, field)
    if experiment.canonical(original_semantics) != experiment.canonical(
        strict_semantics
    ):
        raise ValueError("strict routed intent changed immutable original geometry")
    strict_bytes = current.intent.canonical_intent_bytes()

    route = CandidateRouterPolicy(source="historical-current-context-check").build(
        current.intent, TextAggregate()
    )
    capture = CaptureBus()
    gateway = ForbiddenGateway()
    settings = AggregatorSettings(
        _env_file=None,
        bus_backend="memory",
        service_name="historical-current-context-admission-check",
        candidate_require_text_context=True,
        candidate_require_macro_context=True,
        candidate_context_max_bars=16,
    )
    clock_value = cut_ms
    service = CandidateReviewService(
        settings, gateway=gateway, bus=capture, clock_ms=lambda: clock_value
    )
    bars = tuple(candle_to_closed_bar(row) for row in rows[-16:])
    for bar in bars:
        await service._handle_closed_bar(
            BusEnvelope(
                id=f"offline-context:{bar.message_id}",
                topic=Topics.CLOSED_BAR,
                payload=bar.to_payload(),
            )
        )
    clock_value = cut_ms + 1
    await service._handle_route(
        BusEnvelope(
            id=f"offline-route:{route.route_id}",
            topic=Topics.STRATEGY_ROUTE,
            payload=route.to_payload(),
        )
    )
    reviews = [m for topic, m in capture.published if topic == Topics.CANDIDATE_REVIEW]
    contexts = [m for topic, m in capture.published if topic == Topics.DECISION_CONTEXT]
    if len(reviews) != 1 or len(contexts) != 1:
        raise ValueError("service did not emit exactly one context and review")
    review, context = reviews[0], contexts[0]
    if review.decision.value != "DEFER" or review.reviewer != "DETERMINISTIC":
        raise ValueError("missing context did not produce deterministic DEFER")
    if gateway.calls != 0:
        raise ValueError("forbidden review gateway was called")
    if route.intent.canonical_intent_bytes() != strict_bytes:
        raise ValueError("review changed routed intent")
    availability = {source.kind: source.availability for source in context.sources}
    if availability != {
        "closed_bars": "AVAILABLE",
        "market": "UNAVAILABLE",
        "text": "UNAVAILABLE",
        "macro": "UNAVAILABLE",
    }:
        raise ValueError("real bars or unavailable context was misrepresented")
    return {
        "window_id": window_id,
        "slot_id": original_row["slot_id"],
        "historical_cut_ms": cut_ms,
        "clock_authority": "PROJECTED_STRATEGY_OBSERVATION_AND_CONTEXT_RECEIVE_NOT_OBSERVED_HISTORY",
        "projected_strategy_observed_at_ms": cut_ms + 1,
        "projected_context_received_at_ms": cut_ms,
        "historical_strategy_or_source_observation_proven": False,
        "actual_review_started_utc": actual_started_utc,
        "actual_review_finished_utc": utc_now(),
        "original_intent_id": original_intent.intent_id,
        "strict_current_intent_id": current.intent.intent_id,
        "route_id": route.route_id,
        "context_id": safe_id(context),
        "review_id": safe_id(review),
        "review_decision": review.decision.value,
        "reviewer": review.reviewer,
        "reason_codes": list(review.reason_codes),
        "context_sources": [
            {"kind": str(source.kind), "availability": str(source.availability)}
            for source in context.sources
        ],
        "news_source_status": "UNAVAILABLE",
        "news_source_detail": "NOT_PROVIDED_NOT_KNOWN_EMPTY",
        "macro_source_status": "UNAVAILABLE",
        "macro_source_detail": "NOT_PROVIDED",
        "gateway_calls": gateway.calls,
        "original_candidate_geometry_sha256": experiment.digest(original_geometry),
        "current_candidate_geometry_sha256": experiment.digest(current_geometry),
        "strict_semantic_geometry_sha256": experiment.digest(strict_semantics),
        "original_semantic_geometry_sha256": experiment.digest(original_semantics),
    }


async def run(args: Any) -> None:
    started = time.monotonic()
    actual_started_utc = utc_now()
    plan, original_plan, reference = experiment.load_experiment(args)
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    sources = current_sources(lock)
    before_signature = signature(args, original_plan["windows"], reference["windows"])
    if sources["adaptive_identity"] != reference["sources"]["adaptive_identity"]:
        raise ValueError("original adaptive code/config identity changed")
    if (
        sources["input_loader_sha256"]
        != reference["sources"]["replay_modules_sha256"]["inputs.py"]
    ):
        raise ValueError("original input loader changed")
    if (
        sources["reused_backtest_modules_sha256"]
        != reference["sources"]["reused_backtest_modules_sha256"]
    ):
        raise ValueError("original archive/cost parsers changed")
    originals = []
    input_evidence_by_window = {}
    from kairos_strategy.adaptive.config import UNIVERSE

    for window, ref_window in zip(
        original_plan["windows"], reference["windows"], strict=True
    ):
        _inputs, _tape, candidates = experiment.validated_window(
            args, window, ref_window, original_plan
        )
        slot_count = len(UNIVERSE) * ((_inputs.end_ms - _inputs.start_ms) // 300_000)
        if slot_count != 4_320:
            raise ValueError(
                "original window does not validate its full 4,320-slot roster"
            )
        input_evidence_by_window[window["id"]] = experiment.digest(_inputs.evidence)
        originals.extend(
            (window["id"], row, intent, _inputs) for row, intent in candidates
        )
    if len(originals) != plan["expected_candidates"]:
        raise ValueError(
            "validated native roster differs from predeclared 12 candidates"
        )

    # Historical model artifacts are coverage-checked only, never supplied to current review.
    old_requests = experiment.read_json(OLD_REQUESTS)
    old_reviews = [
        json.loads(line)
        for line in OLD_REVIEWS.read_text(encoding="utf-8").splitlines()
    ]
    old_coverage = experiment.validate_reviews(old_requests, old_reviews)
    if len(old_coverage) != plan["expected_candidates"]:
        raise ValueError("saved market-only response coverage is incomplete")

    decisions = []
    for window_id, row, intent, inputs in originals:
        decisions.append(
            await review_one(
                inputs,
                row,
                intent,
                window_id,
                sources["engineering_manifest_identity_sha256"],
            )
        )
        if time.monotonic() - started > MAX_SECONDS:
            raise TimeoutError("offline admission check exceeded its 175-second bound")

    after_signature = signature(args, original_plan["windows"], reference["windows"])
    for window, ref_window in zip(
        original_plan["windows"], reference["windows"], strict=True
    ):
        reloaded, _tape, _candidates = experiment.validated_window(
            args, window, ref_window, original_plan
        )
        if (
            experiment.digest(reloaded.evidence)
            != input_evidence_by_window[window["id"]]
        ):
            raise ValueError("market input evidence changed during check")
    after_sources = current_sources(lock)
    if before_signature != after_signature or sources != after_sources:
        raise ValueError("source or input identity changed during check")
    if any(
        row["review_decision"] != "DEFER" or row["gateway_calls"] != 0
        for row in decisions
    ):
        raise ValueError("candidate admission did not fail closed for every row")
    if time.monotonic() - started > MAX_SECONDS:
        raise TimeoutError("offline admission check exceeded its 175-second bound")

    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "candidate-contexts.jsonl").open(
        "x", encoding="utf-8", newline="\n"
    ) as stream:
        for row in decisions:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    experiment.write_json(
        args.output / "result.json",
        {
            "schema": "kairos.real-market-input-admission-check.v1",
            "state": "REAL_MARKET_INPUT_ADMISSION_BLOCKED_MISSING_CONTEXT",
            "readiness": {
                "technical_paper_ready": False,
                "paper_qualified": False,
                "alpha_ready": False,
                "live_ready": False,
                "strategy_policy": "REJECT_ALL",
            },
            "started_utc": actual_started_utc,
            "finished_utc": utc_now(),
            "candidates": len(decisions),
            "validated_original_roster_slots_per_window": 4_320,
            "validated_original_roster_slots_total": 17_280,
            "validated_windows": [window["id"] for window in original_plan["windows"]],
            "source_identity": sources,
            "source_identity_scope": "ENGINEERING_MANIFEST_IDENTITY_NOT_DATA_OR_SOURCE_ADMISSION",
            "original_reference_strategy_revisions": original_plan["source_revisions"],
            "input_signature_before": before_signature,
            "input_signature_after": after_signature,
            "saved_market_only_response_coverage": len(old_coverage),
            "saved_market_only_responses_fed_to_current_review": False,
            "actual_observation_start_utc": actual_started_utc,
            "actual_observation_end_utc": utc_now(),
            "historical_news_status": "UNAVAILABLE",
            "historical_news_detail": "NOT_PROVIDED_NOT_KNOWN_EMPTY",
            "historical_macro_status": "UNAVAILABLE",
            "historical_macro_detail": "NOT_PROVIDED",
            "all_candidates_deferred": True,
            "provider_calls": 0,
            "new_provider_cost_usd": 0,
            "complete_system_test_executed": False,
            "risk_or_execution_invoked": False,
            "limitations": [
                "Retained inputs contain market candles only; no admitted historical NEWS or Macro source was supplied to this check.",
                "Strategy observed_at_ms and service receive timestamps are projected historical clocks, not evidence of historical observation or delivery.",
                "No risk sizing, fee-inclusive admission, SIM command, live order, or full-system completion is claimed.",
            ],
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
    try:
        asyncio.run(run(args))
    except Exception as exc:  # noqa: BLE001 - retain safe error class, never a success receipt
        print(f"state=FAILED_CLOSED error={type(exc).__name__}", file=sys.stderr)
        return 2
    print(
        "state=REAL_MARKET_INPUT_ADMISSION_BLOCKED_MISSING_CONTEXT candidates=12 provider_calls=0"
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
