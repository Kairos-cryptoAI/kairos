"""Bounded native campaign transport, not a conversion into economic replay.

An injected window reader is caller-owned and must be SELECT-only. This module
constructs no database/repository, fetches no bar reference and has no model,
budget, seal or trading writer. Native identities and distinct clocks survive.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from kairos_core import (
    EvidenceReferenceV1,
    ResearchObservationWindowV1,
    canonical_json_bytes,
    canonical_sha256,
)
from kairos_persistence.causal_campaign import (
    CampaignMarketContextV1,
    ResearchCausalPairReceiptV1,
    ResearchCausalStrategyEvaluationReceiptV1,
)
from kairos_persistence.research_campaign import (
    ResearchArmOutcomeV1,
    ResearchCampaignPlanV1,
    ResearchCausalBundleV1,
    ResearchCostReceiptV1,
    ResearchReviewReceiptV1,
)
from kairos_persistence.research_evidence import (
    ResearchLLMAttemptStartV1,
    ResearchLLMAttemptTerminalV1,
    ResearchSourceReceiptV1,
)

SCHEMA = "kairos.development.native-window-observations.v1"
MAX_BYTES = 32 * 1024 * 1024
MAX_RECEIPT_BYTES = 262_144
MAX_ROWS = 64
_MODELS = {
    "source": ResearchSourceReceiptV1,
    "bundle": ResearchCausalBundleV1,
    "evaluation": ResearchCausalStrategyEvaluationReceiptV1,
    "start": ResearchLLMAttemptStartV1,
    "terminal": ResearchLLMAttemptTerminalV1,
    "review": ResearchReviewReceiptV1,
    "cost": ResearchCostReceiptV1,
    "outcome": ResearchArmOutcomeV1,
    "sample": ResearchCausalPairReceiptV1,
}
_ARMS = ("strategy-only", "strategy-review", "llm-proposal-research")


def _claim_id(plan: Any, window: Any) -> str:
    return canonical_sha256({"plan_receipt_sha256": plan.receipt_sha256, "sample_id": window.sample_id})


class WindowReader(Protocol):
    """Caller-owned narrow read facade; not a writable repository constructor."""

    async def window_state(self, campaign_id: str, sample_id: str) -> Mapping[tuple[str, str, str], Any]: ...


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate observation JSON field")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise ValueError("nonfinite observation JSON number")


def _json(encoded: bytes | str) -> Any:
    try:
        return json.loads(encoded, object_pairs_hook=_object, parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("invalid bounded observation JSON") from None


def _native(raw: Any, model: type) -> Any:
    # JSON revalidation catches model_copy/construct and mutable nested payload
    # bypasses. Exact bytes prohibit ignored extras, omitted identities/defaults
    # and coercion that would silently reinterpret original receipts.
    try:
        encoded = canonical_json_bytes(raw)
        if len(encoded) > MAX_RECEIPT_BYTES:
            raise ValueError
        parsed = model.model_validate_json(encoded)
        if canonical_json_bytes(parsed.model_dump(mode="json")) != encoded:
            raise ValueError
        return parsed
    except (TypeError, ValueError, RecursionError, OverflowError):
        raise ValueError("noncanonical or incompatible native observation contract") from None


def _key(raw: Any) -> tuple[str, str, str]:
    if (
        type(raw) is not list
        or len(raw) != 3
        or any(type(x) is not str or not x or len(x) > 300 or x != x.strip() for x in raw)
    ):
        raise ValueError("explicit bounded native receipt key required")
    return tuple(raw)


def _check_links(plan: Any, window: Any, rows: dict[tuple[str, str, str], Any]) -> None:
    sources = {r.receipt_sha256: r for (kind, _, _), r in rows.items() if kind == "source"}
    bundle = rows.get(("bundle", "all", "one"))
    evaluation = rows.get(("evaluation", "all", "one"))
    starts = {r.attempt_id: r for (kind, _, _), r in rows.items() if kind == "start"}
    if len({s.arm_id for s in starts.values()}) != len(starts):
        raise ValueError("native arm has more than one immutable START fence")
    decisions: dict[str, Any] = {}
    costs: dict[tuple[str, str], dict[str, Any]] = {}
    attempt_arms: dict[str, str] = {}
    requirements = {(r.source_kind, r.source_name): r for r in plan.required_sources}
    for (kind, arm, slot), receipt in rows.items():
        for name, expected in (
            ("campaign_id", plan.campaign_id),
            ("sample_id", window.sample_id),
            ("schedule_digest", plan.schedule_digest),
            ("candidate_protocol_digest", plan.candidate_protocol_digest),
        ):
            if hasattr(receipt, name) and getattr(receipt, name) != expected:
                raise ValueError("native observation differs from explicit import scope")
        if kind == "source":
            pair = (receipt.source_kind, receipt.source_name)
            if arm != "all" or slot != ":".join(pair) or pair not in requirements:
                raise ValueError("native source key differs from the declared capture policy")
        elif kind in {"bundle", "evaluation"}:
            if (arm, slot) != ("all", "one"):
                raise ValueError("native singleton receipt stored under a different key")
        elif kind == "cost":
            if arm != receipt.arm_id or slot != f"{receipt.stage}:{receipt.attempt_id}":
                raise ValueError("native budget stage/attempt key differs")
            costs.setdefault((arm, receipt.attempt_id), {})[receipt.stage] = receipt
        elif kind in {"start", "terminal", "review"}:
            if arm not in _ARMS[1:] or slot != receipt.attempt_id:
                raise ValueError("native attempt key differs from its receipt")
            if kind == "start":
                if receipt.arm_id != arm:
                    raise ValueError("native START arm differs")
                if (
                    receipt.symbol != window.symbol
                    or receipt.timeframe != window.timeframe
                    or receipt.market_as_of_ts_ms != window.market_as_of_ts_ms
                    or receipt.sample_deadline_ts_ms != window.sample_deadline_ts_ms
                ):
                    raise ValueError("native START differs from the selected window")
            else:
                start = starts.get(receipt.attempt_id)
                if (
                    start is None
                    or start.arm_id != arm
                    or receipt.start_receipt_sha256 != start.receipt_sha256
                ):
                    raise ValueError("native completion has no exact scoped START")
                if (
                    receipt.attempt_id in decisions
                    or receipt.observed_at_ts_ms < start.attempt_started_at_ts_ms
                ):
                    raise ValueError("conflicting or backdated native completion")
                decisions[receipt.attempt_id] = receipt
                if kind == "review":
                    if (
                        arm != "strategy-review"
                        or bundle is None
                        or evaluation is None
                        or evaluation.intent is None
                        or receipt.bundle_receipt_sha256 != bundle.receipt_sha256
                        or receipt.evaluation_receipt_sha256 != evaluation.receipt_sha256
                        or receipt.requested_model != start.requested_model
                        or receipt.resolved_model != start.requested_model
                        or receipt.prompt_sha256 != start.prompt_sha256
                    ):
                        raise ValueError("native review has no exact matched evaluation/bundle/provenance")
                    allowed = {canonical_sha256(_reference(s)) for s in sources.values()}
                    if set(receipt.output.evidence_ids) - allowed:
                        raise ValueError("native review cites evidence outside the source roster")
                else:
                    if arm == "strategy-review" and receipt.terminal_status == "COMPLETED":
                        raise ValueError("native review cannot complete as an independent proposal")
                    for completed in (receipt.completion, receipt.failure):
                        if completed is not None and any(
                            getattr(completed, name) != getattr(start, name)
                            for name in (
                                "campaign_id",
                                "sample_id",
                                "arm_id",
                                "symbol",
                                "timeframe",
                                "market_as_of_ts_ms",
                                "market_snapshot_sha256",
                                "sample_deadline_ts_ms",
                                "attempt_started_at_ts_ms",
                            )
                        ):
                            raise ValueError("native terminal changes the admitted attempt scope")
                    failure = receipt.failure
                    if failure is not None and (
                        failure.provider.casefold() != start.provider
                        or failure.requested_model != start.requested_model
                        or failure.prompt_sha256 != start.prompt_sha256
                        or failure.budget_reservation_id != start.budget_reservation_id
                    ):
                        raise ValueError("native failure changes the admitted model provenance")
                    if receipt.proposal is not None:
                        provenance = receipt.proposal.model_provenance
                        if (
                            provenance.requested_model != start.requested_model
                            or provenance.resolved_model != start.requested_model
                            or provenance.prompt_sha256 != start.prompt_sha256
                            or provenance.budget_reservation_id != start.budget_reservation_id
                            or provenance.provider.casefold() != start.provider
                        ):
                            raise ValueError("native proposal changes the admitted model provenance")
                        allowed = {canonical_json_bytes(_reference(s)) for s in sources.values()}
                        if any(canonical_json_bytes(e) not in allowed for e in receipt.proposal.evidence):
                            raise ValueError("native proposal cites evidence outside the source roster")
        elif kind in {"outcome", "sample"}:
            if arm != receipt.arm_id or arm not in _ARMS or slot != "one":
                raise ValueError("native outcome/pair key differs from its arm")
            if kind == "sample" or receipt.bundle_receipt_sha256 is not None:
                if bundle is None or receipt.bundle_receipt_sha256 != bundle.receipt_sha256:
                    raise ValueError("native outcome/pair refers to an absent bundle")
            if kind == "sample" or receipt.evaluation_receipt_sha256 is not None:
                if evaluation is None or receipt.evaluation_receipt_sha256 != evaluation.receipt_sha256:
                    raise ValueError("native outcome/pair refers to an absent evaluation")
        if kind in {"start", "cost"}:
            prior_arm = attempt_arms.setdefault(receipt.attempt_id, arm)
            if prior_arm != arm:
                raise ValueError("native budget/START identity reused across arms")
    context = None
    market = next((s for s in sources.values() if s.source_kind == "MARKET_SNAPSHOT"), None)
    if market is not None:
        context = _native(market.content, CampaignMarketContextV1)
        if (
            context.anchor_bar.symbol != window.symbol
            or context.anchor_bar.timeframe != window.timeframe
            or context.market_snapshot.message_id != market.reference
            or int(context.market_snapshot.produced_at.timestamp() * 1000) != market.source_as_of_ts_ms
        ):
            raise ValueError("native market producer identity or clock differs from its source")
    if bundle is not None:
        if (
            bundle.claim_id != _claim_id(plan, window)
            or set(bundle.source_receipt_sha256s) != set(sources)
            or len(sources) != len(requirements)
        ):
            raise ValueError("native bundle differs from its complete source roster")
        for source in sources.values():
            rule = requirements[source.source_kind, source.source_name]
            if (
                not window.market_as_of_ts_ms - rule.maximum_age_ms
                <= source.source_as_of_ts_ms
                <= source.observed_at_ts_ms
                <= window.market_as_of_ts_ms
            ):
                raise ValueError("native frozen bundle uses late/future/stale source evidence")
        if (
            market is None
            or context is None
            or not context.anchor_bar.close_time_ms <= market.source_as_of_ts_ms < window.market_as_of_ts_ms
            or context.anchor_bar.close_time_ms >= window.market_as_of_ts_ms
            or bundle.market_snapshot_sha256 != market.content_sha256
            or window.market_snapshot_sha256 is not None
            and window.market_snapshot_sha256 != market.content_sha256
            or bundle.frozen_at_ts_ms < window.market_as_of_ts_ms
        ):
            raise ValueError("native bundle market or freeze clock differs")
    if evaluation is not None:
        if (
            bundle is None
            or evaluation.source_receipt_sha256s != bundle.source_receipt_sha256s
            or evaluation.market_snapshot_sha256 != bundle.market_snapshot_sha256
            or evaluation.evidence_as_of_ts_ms != window.market_as_of_ts_ms
            or evaluation.symbol != window.symbol
            or evaluation.timeframe != window.timeframe
            or market is None
            or context is None
            or evaluation.context_source_receipt_sha256 != market.receipt_sha256
            or evaluation.anchor_bar_sha256 != context.anchor_bar.bar_sha256
            or evaluation.anchor_bar_close_ts_ms != context.anchor_bar.close_time_ms
            or evaluation.bar_window_sha256 != context.bar_window_sha256
            or evaluation.bar_count != context.bar_count
        ):
            raise ValueError("native causal evaluation differs from the saved bundle/window")
    for start in starts.values():
        if (
            bundle is None
            or evaluation is None
            or start.market_snapshot_sha256 != bundle.market_snapshot_sha256
        ):
            raise ValueError("native START lacks its independent baseline/source bundle")
    for (arm, attempt_id), stages in costs.items():
        requested, reserved, denied, committing, committed = (
            stages.get(stage)
            for stage in (
                "RESERVATION_REQUESTED",
                "RESERVED",
                "RESERVATION_DENIED",
                "COMMIT_REQUESTED",
                "COMMITTED",
            )
        )
        if reserved is not None and denied is not None or denied is not None and attempt_id in starts:
            raise ValueError("native reservation cannot be denied and dispatched")
        for later, earlier, equal in (
            (reserved, requested, True),
            (denied, requested, False),
            (committing, reserved, False),
            (committed, committing, True),
        ):
            if later is not None and (
                earlier is None
                or later.observed_at_ts_ms < earlier.observed_at_ts_ms
                or equal
                and later.amount_microusd != earlier.amount_microusd
                or later is committing
                and later.amount_microusd > earlier.amount_microusd
                or later is denied
                and later.amount_microusd != 0
            ):
                raise ValueError("native cost stage lacks its exact monotonic operation fence")
        if attempt_id in starts and starts[attempt_id].arm_id != arm:
            raise ValueError("native budget stages differ from their START arm")
    _check_pairs(window, rows, bundle, evaluation, starts, decisions)
    _check_outcomes(plan, window, rows, bundle, evaluation, starts, decisions, costs)


def _check_pairs(window: Any, rows: Any, bundle: Any, evaluation: Any, starts: Any, decisions: Any) -> None:
    for (kind, arm, _), pair in rows.items():
        if kind != "sample":
            continue
        start = starts.get(pair.attempt_id)
        terminal = decisions.get(pair.attempt_id)
        if (
            arm != "llm-proposal-research"
            or start is None
            or start.arm_id != arm
            or terminal is None
            or getattr(terminal, "terminal_status", None) != "COMPLETED"
            or terminal.proposal is None
            or terminal.completion is None
        ):
            raise ValueError("native pair has no exact completed proposal START history")
        proposal, completion = terminal.proposal, terminal.completion
        intent = evaluation.intent
        if (
            pair.arm_protocol_digest != start.arm_protocol_digest
            or pair.source_receipt_sha256s != bundle.source_receipt_sha256s
            or pair.market_snapshot_sha256 != bundle.market_snapshot_sha256
            or pair.market_as_of_ts_ms != window.market_as_of_ts_ms
            or pair.anchor_bar_sha256 != evaluation.anchor_bar_sha256
            or pair.bar_window_sha256 != evaluation.bar_window_sha256
            or pair.bar_count != evaluation.bar_count
            or pair.start_receipt_sha256 != start.receipt_sha256
            or pair.terminal_receipt_sha256 != terminal.receipt_sha256
            or pair.completion_receipt_id != completion.completion_receipt_id
            or pair.proposal_id != proposal.proposal_id
            or pair.strategy_outcome != (intent.side.value if intent else "NO_INTENT")
            or pair.strategy_intent_id != (intent.intent_id if intent else None)
            or pair.llm_outcome != proposal.action.value
            or not (
                window.market_as_of_ts_ms
                <= start.attempt_started_at_ts_ms
                <= completion.response_observed_at_ts_ms
                <= pair.paired_at_ts_ms
                <= window.paired_at_ts_ms
                < window.sample_deadline_ts_ms
            )
            or evaluation.evaluated_at_ts_ms > pair.paired_at_ts_ms
            or proposal.action.value in {"LONG_BIAS", "SHORT_BIAS", "VOLATILITY_ALERT"}
            and proposal.expires_at_ts_ms <= pair.paired_at_ts_ms
            or intent is not None
            and intent.entry_expires_ts_ms <= pair.paired_at_ts_ms
        ):
            raise ValueError("native pair changes original identity/action/window or causal clocks")


def _check_outcomes(
    plan: Any, window: Any, rows: Any, bundle: Any, evaluation: Any, starts: Any, decisions: Any, costs: Any
) -> None:
    by_arm = {s.arm_id: s for s in starts.values()}
    for (kind, arm, _), outcome in rows.items():
        if kind != "outcome":
            continue
        # Outcomes are immutable as-of records, not projections of the latest
        # row set. Native writers may append bundle/evaluation/START/terminal
        # later without rewriting a sealed UNKNOWN/no-call outcome. Missing DB
        # capture clocks prohibit inferring capture order from provider clocks.
        actual_start = by_arm.get(arm)
        actual_decision = decisions.get(actual_start.attempt_id) if actual_start else None
        if (
            outcome.claim_id != _claim_id(plan, window)
            or outcome.bundle_receipt_sha256 is not None
            and (bundle is None or outcome.bundle_receipt_sha256 != bundle.receipt_sha256)
            or outcome.evaluation_receipt_sha256 is not None
            and (evaluation is None or outcome.evaluation_receipt_sha256 != evaluation.receipt_sha256)
            or outcome.attempt_id is not None
            and (actual_start is None or outcome.attempt_id != actual_start.attempt_id)
            or outcome.decision_receipt_sha256 is not None
            and (
                outcome.attempt_id is None
                or actual_decision is None
                or outcome.decision_receipt_sha256 != actual_decision.receipt_sha256
            )
        ):
            raise ValueError("native outcome invents an independent receipt link")
        saved_bundle = bundle if outcome.bundle_receipt_sha256 is not None else None
        saved_evaluation = evaluation if outcome.evaluation_receipt_sha256 is not None else None
        start = actual_start if outcome.attempt_id is not None else None
        decision = actual_decision if outcome.decision_receipt_sha256 is not None else None
        if (
            saved_evaluation is not None
            and saved_bundle is None
            or start is not None
            and (saved_bundle is None or saved_evaluation is None)
        ):
            raise ValueError("native outcome omits inputs already required by its linked attempt/evaluation")
        pair = rows.get(("sample", arm, "one"))
        if outcome.causal_sample_receipt_sha256 is not None and (
            pair is None
            or outcome.causal_sample_receipt_sha256 != pair.receipt_sha256
            or outcome.status != "PROPOSAL"
            or outcome.bundle_receipt_sha256 != pair.bundle_receipt_sha256
            or outcome.evaluation_receipt_sha256 != pair.evaluation_receipt_sha256
            or outcome.attempt_id != pair.attempt_id
            or outcome.decision_receipt_sha256 != pair.terminal_receipt_sha256
        ):
            raise ValueError("native outcome invents an independent causal pair")
        # A stored LATE status can be caused by the unavailable DB capture clock.
        # Preserve it, but never certify on-time recording from response clocks.
        allowed: set[str]
        if start is not None:
            if decision is None or getattr(decision, "terminal_status", None) == "UNRESOLVED":
                allowed = {"UNKNOWN"}
            elif decision.observed_at_ts_ms > window.paired_at_ts_ms:
                allowed = {"LATE"}
            else:
                status = (
                    decision.output.action
                    if isinstance(decision, ResearchReviewReceiptV1)
                    else "CALL_FAILED"
                    if decision.terminal_status == "FAILED"
                    else "PROPOSAL"
                )
                allowed = {status, "LATE"}
        elif saved_evaluation is not None and saved_evaluation.evaluated_at_ts_ms > window.paired_at_ts_ms:
            allowed = {"LATE"}
        elif saved_evaluation is not None and arm == "strategy-only":
            allowed = {"BASELINE" if saved_evaluation.intent else "NO_INTENT", "LATE"}
        elif saved_evaluation is not None and arm == "strategy-review" and saved_evaluation.intent is None:
            allowed = {"NO_INTENT", "LATE"}
        else:
            allowed = {"SOURCE_MISSING", "EVALUATOR_FAILED", "MISSED", "BUDGET_BLOCKED"}
            arm_stages = {
                stage for (cost_arm, _), stages in costs.items() if cost_arm == arm for stage in stages
            }
            # A later denial/commit must not rewrite an earlier sealed unknown
            # budget operation. The request is durable; capture order is not.
            if "RESERVATION_REQUESTED" in arm_stages:
                allowed.add("UNKNOWN")
            if saved_evaluation is not None:
                allowed.add("LATE")
        if (
            outcome.status not in allowed
            or outcome.status == "SOURCE_MISSING"
            and saved_bundle is not None
            or outcome.status == "BUDGET_BLOCKED"
            and saved_evaluation is None
        ):
            raise ValueError("native outcome action differs from its independent attempt/evaluation")


def _reference(source: Any) -> EvidenceReferenceV1:
    return EvidenceReferenceV1(
        kind=source.source_kind,
        reference=source.reference,
        content_sha256=source.content_sha256,
        observed_at_ms=source.observed_at_ts_ms,
    )


def _decode(document: Any, *, fixture_only: bool) -> tuple[Any, Any, dict[tuple[str, str, str], Any]]:
    if (
        type(fixture_only) is not bool
        or type(document) is not dict
        or set(document) != {"schema", "plan", "window", "receipts"}
        or document["schema"] != SCHEMA
    ):
        raise ValueError("explicit native observation transport/version required")
    plan = _native(document["plan"], ResearchCampaignPlanV1)
    window = _native(document["window"], ResearchObservationWindowV1)
    if (plan.recording_mode == "OFFLINE_ENGINEERING_FIXTURE") != fixture_only or window.timeframe != "1m":
        raise ValueError("native causal clock family or fixture/observation mode differs")
    raw_rows = document["receipts"]
    if type(raw_rows) is not list or len(raw_rows) > MAX_ROWS:
        raise ValueError("native observation roster exceeds its 64-receipt boundary")
    rows: dict[tuple[str, str, str], Any] = {}
    digests: set[str] = set()
    for item in raw_rows:
        if type(item) is not dict or set(item) != {"key", "payload"}:
            raise ValueError("exact native receipt/key envelope required")
        key = _key(item["key"])
        if key in rows or key[0] not in _MODELS:
            raise ValueError("duplicate or unsupported native receipt slot")
        receipt = _native(item["payload"], _MODELS[key[0]])
        if receipt.receipt_sha256 in digests:
            raise ValueError("native receipt identity reused under another key")
        rows[key] = receipt
        digests.add(receipt.receipt_sha256)
    if list(rows) != sorted(rows):
        raise ValueError("native observation keys must retain deterministic ordering")
    if len({r.attempt_id for (k, _, _), r in rows.items() if k == "start"}) != sum(
        k == "start" for k, _, _ in rows
    ):
        raise ValueError("native attempt identity reused across arms")
    _check_links(plan, window, rows)
    return plan, window, rows


@dataclass(frozen=True)
class NativeWindowSnapshot:
    """Deeply immutable canonical transport; parsed models are always fresh copies."""

    canonical_json: str
    fixture_only: bool

    def __post_init__(self) -> None:
        if type(self.canonical_json) is not str or len(self.canonical_json.encode("utf-8")) > MAX_BYTES:
            raise ValueError("native observation transport exceeds its bounded bytes")
        document = _json(self.canonical_json)
        if canonical_json_bytes(document).decode("utf-8") != self.canonical_json:
            raise ValueError("native observation transport must retain exact canonical bytes")
        _decode(document, fixture_only=self.fixture_only)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()

    def decoded(self) -> tuple[Any, Any, dict[tuple[str, str, str], Any]]:
        return _decode(_json(self.canonical_json), fixture_only=self.fixture_only)

    def inspection(self) -> dict[str, Any]:
        plan, window, rows = self.decoded()
        evaluation = rows.get(("evaluation", "all", "one"))
        starts = {r.attempt_id: r for (k, _, _), r in rows.items() if k == "start"}
        stages: dict[str, dict[str, Any]] = {}
        for (kind, _, _), receipt in rows.items():
            if kind == "cost":
                stages.setdefault(receipt.attempt_id, {})[receipt.stage] = receipt
        attempts = set(starts) | set(stages)
        committed = {a: s["COMMITTED"] for a, s in stages.items() if "COMMITTED" in s}
        denied = {a for a, s in stages.items() if "RESERVATION_DENIED" in s}
        unknown = attempts - set(committed) - denied
        missing_outcomes = [a for a in _ARMS if ("outcome", a, "one") not in rows]
        no_call_statuses = {
            "NO_INTENT",
            "SOURCE_MISSING",
            "EVALUATOR_FAILED",
            "MISSED",
            "BUDGET_BLOCKED",
            "LATE",
        }
        incomplete_cost_arms = []
        for arm in _ARMS[1:]:
            outcome = rows.get(("outcome", arm, "one"))
            arm_starts = [s for s in starts.values() if s.arm_id == arm]
            cost_attempts = {r.attempt_id for (k, a, _), r in rows.items() if k == "cost" and a == arm}
            if (
                outcome is None
                or cost_attempts & unknown
                or arm_starts
                and (
                    arm_starts[0].attempt_id not in committed
                    or outcome.attempt_id != arm_starts[0].attempt_id
                    or outcome.decision_receipt_sha256 is None
                    or outcome.status == "UNKNOWN"
                    or bool((cost_attempts & set(committed)) - {arm_starts[0].attempt_id})
                )
                or not arm_starts
                and (outcome.status not in no_call_statuses or bool(cost_attempts & set(committed)))
            ):
                incomplete_cost_arms.append(arm)
        complete_cost_coverage = not (unknown or missing_outcomes or incomplete_cost_arms)
        blockers = [
            "NATIVE_CLOCK_CADENCE_IDENTITY_ADAPTER_MISSING",
            "DB_CAPTURE_CLOCK_UNAVAILABLE",
            "BAR_WINDOW_RESOLVER_NOT_CONNECTED",
            "DETERMINISTIC_PROPOSAL_MAPPER_UNAVAILABLE",
            "COST_COMMIT_CLOCK_ADAPTER_MISSING",
            "FEED_COST_UNAVAILABLE",
            "FROZEN_SCHEDULE_PROTOCOL_NOT_SUPPLIED",
            "SOURCE_PRODUCER_AUTHENTICITY_UNQUALIFIED",
        ]
        if evaluation is None:
            blockers.append("BASELINE_EVALUATION_UNAVAILABLE")
        if unknown:
            blockers.append("MODEL_COST_UNRESOLVED")
        if not complete_cost_coverage:
            blockers.append("MODEL_COST_COVERAGE_INCOMPLETE")
        unlinked: Counter[str] = Counter()
        by_arm = {s.arm_id: s for s in starts.values()}
        for (kind, arm, _), outcome in rows.items():
            if kind != "outcome":
                continue
            for field, current in (
                ("bundle_receipt_sha256", rows.get(("bundle", "all", "one"))),
                ("evaluation_receipt_sha256", evaluation),
                ("attempt_id", by_arm.get(arm)),
                (
                    "decision_receipt_sha256",
                    rows.get(("review", arm, by_arm[arm].attempt_id))
                    or rows.get(("terminal", arm, by_arm[arm].attempt_id))
                    if arm in by_arm
                    else None,
                ),
                ("causal_sample_receipt_sha256", rows.get(("sample", arm, "one"))),
            ):
                if getattr(outcome, field) is None and current is not None:
                    unlinked[field] += 1
        if unlinked:
            blockers.append("OUTCOME_HAS_UNLINKED_APPEND_FACTS")
        return {
            "schema": "kairos.development.native-window-inspection.v1",
            "snapshot_sha256": self.sha256,
            "recording_mode": plan.recording_mode,
            "fixture_only": self.fixture_only,
            "campaign_id": plan.campaign_id,
            "sample_id": window.sample_id,
            "receipt_counts": dict(sorted(Counter(k for k, _, _ in rows).items())),
            "baseline_state": "UNAVAILABLE"
            if evaluation is None
            else "QUIET"
            if evaluation.intent is None
            else "CANDIDATE",
            "original_strategy_intent_id": evaluation.intent.intent_id
            if evaluation and evaluation.intent
            else None,
            "anchor_bar_close_ts_ms": evaluation.anchor_bar_close_ts_ms if evaluation else None,
            "context_cut_ts_ms": window.market_as_of_ts_ms,
            "evaluated_at_ts_ms": evaluation.evaluated_at_ts_ms if evaluation else None,
            "db_capture_clock": None,
            "known_committed_model_cost_microusd": sum(r.amount_microusd for r in committed.values()),
            "total_model_cost_microusd": None
            if not complete_cost_coverage
            else sum(r.amount_microusd for r in committed.values()),
            "model_cost_coverage_complete": complete_cost_coverage,
            "incomplete_model_cost_arms": incomplete_cost_arms,
            "unresolved_cost_attempt_count": len(unknown),
            "outstanding_reserved_microusd": sum(
                s["RESERVED"].amount_microusd for a, s in stages.items() if a in unknown and "RESERVED" in s
            ),
            "denied_reservation_count": len(denied),
            "retained_terminal_statuses": dict(
                sorted(Counter(r.terminal_status for (k, _, _), r in rows.items() if k == "terminal").items())
            ),
            "retained_outcome_statuses": dict(
                sorted(Counter(r.status for (k, _, _), r in rows.items() if k == "outcome").items())
            ),
            "missing_scheduled_arm_outcomes": missing_outcomes,
            "outcome_unlinked_current_fact_counts": dict(sorted(unlinked.items())),
            "outcome_capture_order_qualified": False,
            "economics_ready": False,
            "economic_results": None,
            "economic_blockers": blockers,
            "database_origin_qualified": False,
            "full_schedule_denominator_qualified": False,
            "provider_invoice_qualified": False,
            "scope": "CALLER_SELECTED_NATIVE_WINDOW_NOT_FULL_CAMPAIGN_OR_DATABASE_ATTESTATION",
            "technical_paper_ready": False,
            "paper_qualified": False,
            "alpha_ready": False,
            "live_ready": False,
            "strategy_policy": "REJECT_ALL",
        }


def snapshot_window(
    plan: Any, window: Any, state: Mapping[tuple[str, str, str], Any], *, fixture_only: bool = False
) -> NativeWindowSnapshot:
    if not isinstance(state, Mapping) or len(state) > MAX_ROWS:
        raise ValueError("bounded native window mapping required")
    # Freeze before any await/I/O: native source.content includes mutable dicts.
    document = {
        "schema": SCHEMA,
        "plan": plan.model_dump(mode="json"),
        "window": window.model_dump(mode="json"),
        "receipts": [
            {"key": list(key), "payload": receipt.model_dump(mode="json")}
            for key, receipt in sorted(state.items())
        ],
    }
    return NativeWindowSnapshot(canonical_json_bytes(document).decode("utf-8"), fixture_only)


async def capture_window(
    reader: WindowReader, *, plan: Any, window: Any, fixture_only: bool = False, timeout_seconds: float = 10
) -> NativeWindowSnapshot:
    # Validate and deep-copy scope before the sole SELECT-shaped operation.
    empty = snapshot_window(plan, window, {}, fixture_only=fixture_only)
    saved_plan, saved_window, _ = empty.decoded()
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not 0 < timeout_seconds <= 30
    ):
        raise ValueError("bounded observation read timeout required")
    state = await asyncio.wait_for(
        reader.window_state(saved_plan.campaign_id, saved_window.sample_id), timeout_seconds
    )
    return snapshot_window(saved_plan, saved_window, state, fixture_only=fixture_only)


def write_snapshot(path: Path, snapshot: NativeWindowSnapshot) -> str:
    encoded = snapshot.canonical_json.encode("utf-8")
    with path.open("xb") as stream:
        stream.write(encoded)
    return snapshot.sha256


def read_snapshot(path: Path, *, expected_sha256: str, fixture_only: bool = False) -> NativeWindowSnapshot:
    if type(expected_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ValueError("independently supplied native snapshot SHA256 required")
    with path.open("rb") as stream:
        encoded = stream.read(MAX_BYTES + 1)
    if len(encoded) > MAX_BYTES or hashlib.sha256(encoded).hexdigest() != expected_sha256:
        raise ValueError("native snapshot byte bound or expected checksum differs")
    try:
        decoded = encoded.decode("utf-8")
    except UnicodeError:
        raise ValueError("native snapshot must contain exact UTF8 JSON") from None
    return NativeWindowSnapshot(decoded, fixture_only)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--fixture-only", action="store_true")
    args = parser.parse_args()
    try:
        snapshot = read_snapshot(
            args.input, expected_sha256=args.expected_sha256, fixture_only=args.fixture_only
        )
    except (OSError, ValueError, TypeError, RecursionError):
        # Never print native payloads, validation input or local credentials.
        print(json.dumps({"status": "REJECTED", "reason": "NATIVE_OBSERVATION_IMPORT_INVALID"}))
        return 2
    print(json.dumps(snapshot.inspection(), sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
