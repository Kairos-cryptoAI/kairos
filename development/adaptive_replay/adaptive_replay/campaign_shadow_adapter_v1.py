"""Fail-closed planning adapter for the three-arm research campaign protocol.

This module is deliberately an offline contract, not a runner. It translates a
claimed, frozen campaign window into bounded arm intents. It does not call a
provider, database, venue, or the campaign repository. A caller must wire the
ports only after the Persistence revision is pinned and the campaign identity,
source admission, and runtime acceptance gates have been established.

The proposal arm is an isolated record-only lane: its generated candidate is
never supplied to risk evaluation. All intents are shadow-only and have no
trading or venue authority.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

ACCEPTED_PERSISTENCE_REVISION = "ea0c73395352f71da196270fe16659f1f0298a52"
LOCKED_PERSISTENCE_REVISION = "fd2966761e84b32688c9aee73e00604965f5d7f2"
MAX_OBSERVATIONS = 1
MAX_WINDOW_SECONDS = 60


class Arm(StrEnum):
    STRATEGY_ONLY = "strategy-only"
    STRATEGY_REVIEW = "strategy-review"
    LLM_PROPOSAL_RESEARCH = "llm-proposal-research"


class PlanStatus(StrEnum):
    PLAN_ONLY = "PLAN_ONLY"
    BLOCKED = "BLOCKED"
    READY_FOR_OWNER_WIRING = "READY_FOR_OWNER_WIRING"


@dataclass(frozen=True)
class CampaignBinding:
    """Exact durable identities produced by schedule/claim/freeze/evaluation."""

    campaign_id: str
    schedule_id: str
    claim_id: str
    window_id: str
    bundle_id: str
    evaluation_id: str


@dataclass(frozen=True)
class Readiness:
    """Observed integration facts; these are not runtime credentials."""

    persistence_revision: str | None = None
    lock_projection_revision: str | None = None
    immutable_binding: CampaignBinding | None = None
    causal_sources_admitted: bool = False
    typed_composition_accepted: bool = False
    owner_enabled_shadow_wiring: bool = False
    plan_only: bool = True


@dataclass(frozen=True)
class ArmIntent:
    arm: Arm
    required_steps: tuple[str, ...]
    uses_model: bool
    risk_shadow_only: bool
    candidate_isolated: bool
    venue_calls_allowed: bool = False
    trading_allowed: bool = False


@dataclass(frozen=True)
class CampaignPlan:
    status: PlanStatus
    binding: CampaignBinding | None
    max_observations: int
    max_window_seconds: int
    arms: tuple[ArmIntent, ...]
    blockers: tuple[str, ...]
    retry_policy: str = "NEVER_RESEND_AMBIGUOUS_OR_UNKNOWN_ATTEMPT"
    denominator_policy: str = "RECORD_EVERY_SCHEDULED_WINDOW_AND_ALL_THREE_ARMS"


class SchedulePort(Protocol):
    """Structural boundary matching the durable schedule repository."""

    async def claim_next(self, campaign_id: str) -> object | None: ...


class CampaignRecorderPort(Protocol):
    """Structural boundary for bundle/evaluation/attempt/cost/denominator APIs.

    Implementations should delegate to the pinned Persistence repository's
    claim, freeze, evaluation, record_cost, start_attempt, finish_attempt,
    record_review, and seal_denominator operations. The offline-only
    coordinator invokes the same method names against explicit test doubles;
    structural compatibility does not establish source authenticity or
    runtime readiness.
    """

    async def load_campaign(self, campaign_id: str) -> tuple[object, object, object]: ...

    async def claim_next(self, campaign_id: str) -> object | None: ...

    async def capture_source(
        self,
        *,
        campaign_id: str,
        sample_id: str,
        source_kind: str,
        source_name: str,
        reference: str,
        source_as_of_ts_ms: int,
        content: dict[str, object],
    ) -> object: ...

    async def freeze_bundle(self, claim: object) -> object: ...

    async def resolve_causal_sources(
        self, *, campaign_id: str, sample_id: str, source_receipt_sha256s: tuple[str, ...]
    ) -> tuple[object, ...]: ...

    async def record_causal_evaluation(self, *, claim: object, bundle: object, result: object) -> object: ...

    async def evaluation_recorded_at(
        self, *, campaign_id: str, sample_id: str, evaluation_receipt_sha256: str
    ) -> int: ...

    async def decision_recorded_at(
        self, *, campaign_id: str, sample_id: str, arm_id: str, attempt_id: str
    ) -> int: ...

    async def start_attempt(self, attempt: object) -> bool: ...

    async def record_cost(self, receipt: object) -> bool: ...

    async def finish_attempt(self, terminal: object) -> bool: ...

    async def record_review(self, receipt: object) -> bool: ...

    async def find_attempt(self, attempt_id: str) -> tuple[object, object | None] | None: ...

    async def find_review(self, attempt_id: str) -> object | None: ...

    async def record_outcome(self, outcome: object) -> bool: ...

    async def outcomes(self, campaign_id: str, sample_id: str) -> tuple[object, ...]: ...

    async def pending_claims(self, campaign_id: str, *, limit: int = 64) -> tuple[object, ...]: ...

    async def window_state(self, campaign_id: str, sample_id: str) -> dict[tuple[str, str, str], object]: ...

    async def seal_denominator(self, campaign_id: str) -> object: ...


class TypedCompositionPort(Protocol):
    """Boundary for the accepted Text/Macro/Router/CandidateReview/Risk graph."""

    async def review_shadow(
        self,
        *,
        campaign_context: object,
        bundle: object,
        evaluation: object,
        source_receipts: tuple[object, ...],
        start: object,
    ) -> ReviewCompletion: ...

    async def propose_shadow(
        self,
        *,
        campaign_context: object,
        bundle: object,
        evaluation: object,
        source_receipts: tuple[object, ...],
        start: object,
    ) -> ProposalCompletion: ...


class EvaluatorPort(Protocol):
    async def evaluate(
        self, *, campaign_context: object, claim: object, bundle: object, sources: tuple[object, ...]
    ) -> object: ...


class ReceiptFactoryPort(Protocol):
    """Build exact accepted Persistence model instances from observed facts.

    Factories must return the actual typed models expected by the accepted
    repository revision, not dicts or caller-supplied authority flags.
    """

    def cost(self, **fields: object) -> object: ...

    def start(self, **fields: object) -> object: ...

    def unresolved_terminal(self, **fields: object) -> object: ...

    def failed_terminal(self, **fields: object) -> object: ...

    def proposal_terminal(self, **fields: object) -> object: ...

    def review(self, **fields: object) -> object: ...

    def outcome(self, **fields: object) -> object: ...


@dataclass(frozen=True)
class TimedSource:
    source_kind: str
    source_name: str
    reference: str
    source_as_of_ts_ms: int
    content: dict[str, object]


@dataclass(frozen=True)
class CaptureReport:
    campaign_id: str
    sample_id: str
    market_cutoff_ts_ms: int
    receipts: tuple[object, ...]
    missing_source_keys: tuple[tuple[str, str], ...]
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class BudgetReservation:
    approved: bool
    reserved_microusd: int
    observed_at_ts_ms: int


@dataclass(frozen=True)
class BudgetCommit:
    actual_microusd: int
    observed_at_ts_ms: int


class BudgetPort(Protocol):
    async def reserve(self, *, attempt_id: str, arm_id: Arm, maximum_microusd: int) -> BudgetReservation: ...

    async def commit(self, *, attempt_id: str, arm_id: Arm, actual_microusd: int) -> BudgetCommit: ...


class MillisecondClock(Protocol):
    def now_ms(self) -> int: ...


@dataclass(frozen=True)
class ReviewCompletion:
    action: str
    rationale: str
    evidence_ids: tuple[str, ...]
    response_sha256: str
    requested_model: str
    resolved_model: str
    request_id: str
    prompt_sha256: str
    observed_at_ts_ms: int
    gateway_observed_cost_microusd: int
    # Diagnostic-only Risk result; the persistence API has no field for this.
    # The adapter never forwards it to a venue or to the proposal arm.
    risk_shadow_result: object


@dataclass(frozen=True)
class ProposalCompletion:
    proposal: object
    completion: object
    observed_at_ts_ms: int
    gateway_observed_cost_microusd: int


class AmbiguousCall(Exception):
    """The injected call may have reached its remote endpoint; never retry it."""


class KnownCallFailure(Exception):
    """A caller-observed terminal failure with a typed Persistence failure receipt."""

    def __init__(self, failure: object, *, observed_at_ts_ms: int, gateway_observed_cost_microusd: int = 0):
        super().__init__("injected research call failed with a known terminal receipt")
        self.failure = failure
        self.observed_at_ts_ms = observed_at_ts_ms
        self.gateway_observed_cost_microusd = gateway_observed_cost_microusd


@dataclass(frozen=True)
class BridgeResult:
    claim: object | None
    bundle: object | None
    evaluation: object | None
    outcomes: tuple[object, ...]
    risk_shadow_results: tuple[object, ...]
    denominator_receipt: object | None = None
    stopped_reason: str | None = None
    durability_blockers: tuple[str, ...] = ()


class OfflineCampaignOrchestrator:
    """One-observation async choreography for offline protocol tests only.

    This intentionally cannot be used as a native runner. Ports are injected,
    source payloads must already exist in memory, and ``offline_test_mode`` must
    be explicitly true. Production composition remains blocked until the
    accepted Persistence HEAD is in the actual lock projection and the owner
    supplies real source admission and immutable campaign identities.
    """

    def __init__(
        self,
        *,
        repository: CampaignRecorderPort,
        evaluator: EvaluatorPort,
        composition: TypedCompositionPort,
        budget: BudgetPort,
        receipts: ReceiptFactoryPort,
        clock: MillisecondClock,
        attempt_id: Callable[[object, Arm], str],
        persistence_revision: str,
        lock_projection_revision: str,
        offline_test_mode: bool = False,
        maximum_arm_cost_microusd: int = 250_000,
    ) -> None:
        if not offline_test_mode:
            raise RuntimeError("NATIVE_EXECUTION_DISABLED: this adapter is offline-test-only")
        if persistence_revision != ACCEPTED_PERSISTENCE_REVISION:
            raise RuntimeError("PERSISTENCE_API_REVISION_NOT_ACCEPTED_HEAD")
        # This class is unconditionally offline-only. The caller-supplied lock
        # revision is retained as audit context but never promoted to runtime
        # readiness; the real lock is currently stale.
        self._lock_projection_revision = lock_projection_revision
        if type(maximum_arm_cost_microusd) is not int or not 0 <= maximum_arm_cost_microusd <= 12_000_000:
            raise ValueError("arm cost cap must fit the Persistence receipt bound")
        self._repository = repository
        self._evaluator = evaluator
        self._composition = composition
        self._budget = budget
        self._receipts = receipts
        self._clock = clock
        self._attempt_id = attempt_id
        self._maximum_arm_cost_microusd = maximum_arm_cost_microusd
        self._capture_reports: dict[tuple[str, str], CaptureReport] = {}
        self._capture_attempted: set[tuple[str, str]] = set()

    async def capture_before_cutoff(
        self,
        *,
        campaign_id: str,
        sample_id: str,
        provided_sources: tuple[TimedSource, ...],
    ) -> CaptureReport:
        """Capture caller-provided bytes before the scheduled market cutoff.

        Persistence stamps each receipt with its own database clock. This phase
        refuses to invoke capture_source at or after the cutoff and never takes
        an observed timestamp from the caller.
        """
        key = (campaign_id, sample_id)
        if key in self._capture_attempted:
            raise RuntimeError("SOURCE_CAPTURE_PHASE_ALREADY_ATTEMPTED_NO_RETRY")
        self._capture_attempted.add(key)
        context = await self._repository.load_campaign(campaign_id)
        plan, schedule, _protocol = context
        window = self._scheduled_window(schedule, sample_id)
        cutoff = int(window.market_as_of_ts_ms)
        required = tuple(plan.required_sources)
        required_by_key = {(s.source_kind, s.source_name): s for s in required}
        sources_by_key = {(s.source_kind, s.source_name): s for s in provided_sources}
        if len(sources_by_key) != len(provided_sources) or set(sources_by_key) - set(required_by_key):
            raise ValueError("provided source batch must be unique and limited to the preregistered roster")

        receipts: list[object] = []
        blockers: list[str] = []
        if self._clock.now_ms() >= cutoff:
            blockers.append("CAPTURE_STARTED_AT_OR_AFTER_MARKET_CUTOFF")
        else:
            for item in provided_sources:
                try:
                    receipt = await self._repository.capture_source(
                        campaign_id=campaign_id,
                        sample_id=sample_id,
                        source_kind=item.source_kind,
                        source_name=item.source_name,
                        reference=item.reference,
                        source_as_of_ts_ms=item.source_as_of_ts_ms,
                        content=item.content,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Do not retry an ambiguous capture write. A later bounded
                    # run records the incomplete scheduled sample in its denominator.
                    blockers.append("SOURCE_CAPTURE_WRITE_UNRESOLVED_NO_RETRY")
                    break
                observed = getattr(receipt, "observed_at_ts_ms", None)
                source_as_of = getattr(receipt, "source_as_of_ts_ms", None)
                maximum_age = int(required_by_key[(item.source_kind, item.source_name)].maximum_age_ms)
                if (
                    type(observed) is not int
                    or type(source_as_of) is not int
                    or not cutoff - maximum_age <= source_as_of <= observed <= cutoff
                ):
                    blockers.append("DB_STAMPED_SOURCE_RECEIPT_OUTSIDE_CAUSAL_CUTOFF")
                    # The database may have crossed the cutoff during this
                    # phase. Do not submit another source payload after that
                    # receipt demonstrates lateness.
                    break
                else:
                    receipts.append(receipt)
        captured_keys = {(r.source_kind, r.source_name) for r in receipts}
        report = CaptureReport(
            campaign_id,
            sample_id,
            cutoff,
            tuple(receipts),
            tuple(sorted(set(required_by_key) - captured_keys)),
            tuple(blockers),
        )
        self._capture_reports[key] = report
        return report

    async def run_bounded(
        self,
        *,
        campaign_id: str,
        max_observations: int = MAX_OBSERVATIONS,
        max_window_seconds: int = MAX_WINDOW_SECONDS,
    ) -> tuple[BridgeResult, ...]:
        """Claim and process at most one scheduled observation; never poll or retry."""

        if max_observations != MAX_OBSERVATIONS:
            raise ValueError("offline bridge cap is exactly one observation")
        if not 1 <= max_window_seconds <= MAX_WINDOW_SECONDS:
            raise ValueError("offline bridge time cap must be from 1 through 60 seconds")
        if not campaign_id or campaign_id != campaign_id.strip():
            raise ValueError("campaign_id must be normalized and non-empty")
        # No network/source clients exist here: the caller hands us frozen bytes.
        try:
            result = await asyncio.wait_for(
                self._run_one(
                    campaign_id=campaign_id,
                    max_window_seconds=max_window_seconds,
                ),
                timeout=max_window_seconds,
            )
        except TimeoutError:
            # The durable claim/START/outcome receipts are the recovery source.
            # Do not call claim_next again or infer which timed-out operation
            # reached Persistence; the owner may invoke reconcile_pending.
            return (
                BridgeResult(
                    None,
                    None,
                    None,
                    (),
                    (),
                    stopped_reason="OBSERVATION_TIME_BUDGET_EXHAUSTED_RECONCILE_REQUIRED",
                ),
            )
        return (result,)

    async def reconcile_pending(self, *, campaign_id: str) -> tuple[BridgeResult, ...]:
        """Resolve at most one already-claimed window after restart, without dispatch.

        A durable START without review/terminal becomes UNKNOWN. This path never
        calls the evaluator, composition, provider, budget reserve, or venue.
        Incomplete pre-deadline arms remain pending rather than receiving an
        invented status; once the frozen paired cutoff passes they may be MISSED.
        """

        context = await self._repository.load_campaign(campaign_id)
        _plan, schedule, _protocol = context
        claims = await self._repository.pending_claims(campaign_id, limit=1)
        results: list[BridgeResult] = []
        for claim in claims:
            sample_id = claim.sample_id
            deadline = self._paired_deadline(schedule, sample_id)
            state = await self._repository.window_state(campaign_id, sample_id)
            saved_outcomes = {
                receipt.arm_id: receipt for (kind, _arm, _slot), receipt in state.items() if kind == "outcome"
            }
            evaluation = state.get(("evaluation", "all", "one"))
            bundle = state.get(("bundle", "all", "one"))
            new_outcomes: list[object] = []
            for arm in Arm:
                if arm.value in saved_outcomes:
                    continue
                if arm is Arm.STRATEGY_ONLY:
                    if evaluation is not None:
                        recorded_at = await self._repository.evaluation_recorded_at(
                            campaign_id=campaign_id,
                            sample_id=sample_id,
                            evaluation_receipt_sha256=evaluation.receipt_sha256,
                        )
                        status = (
                            "LATE"
                            if max(recorded_at, evaluation.evaluated_at_ts_ms) > deadline
                            else ("BASELINE" if evaluation.intent is not None else "NO_INTENT")
                        )
                    elif self._clock.now_ms() >= deadline:
                        status = "MISSED"
                    else:
                        continue
                    new_outcomes.append(
                        await self._record_outcome(
                            claim=claim,
                            bundle=bundle,
                            evaluation=evaluation,
                            arm=arm,
                            status=status,
                        )
                    )
                    continue

                starts = [
                    (slot, receipt)
                    for (kind, arm_id, slot), receipt in state.items()
                    if kind == "start" and arm_id == arm.value
                ]
                start_slot, start = starts[0] if starts else (None, None)
                terminal = state.get(("terminal", arm.value, start_slot)) if start_slot else None
                review = state.get(("review", arm.value, start_slot)) if start_slot else None
                if review is not None or terminal is not None:
                    decision = review if review is not None else terminal
                    recorded_at = await self._repository.decision_recorded_at(
                        campaign_id=campaign_id,
                        sample_id=sample_id,
                        arm_id=arm.value,
                        attempt_id=start.attempt_id,
                    )
                    status = self._decision_status(arm, decision, terminal, deadline)
                    if max(recorded_at, getattr(decision, "observed_at_ts_ms", 0)) > deadline:
                        status = "LATE"
                    new_outcomes.append(
                        await self._record_outcome(
                            claim=claim,
                            bundle=bundle,
                            evaluation=evaluation,
                            arm=arm,
                            status=status,
                            attempt_id=start.attempt_id,
                            decision_receipt_sha256=getattr(decision, "receipt_sha256", None),
                        )
                    )
                elif start is not None:
                    # START is the durable no-resend fence. No provider call here.
                    new_outcomes.append(
                        await self._record_outcome(
                            claim=claim,
                            bundle=bundle,
                            evaluation=evaluation,
                            arm=arm,
                            status="UNKNOWN",
                            attempt_id=start.attempt_id,
                        )
                    )
                elif evaluation is not None and arm is Arm.STRATEGY_REVIEW and evaluation.intent is None:
                    new_outcomes.append(
                        await self._record_outcome(
                            claim=claim,
                            bundle=bundle,
                            evaluation=evaluation,
                            arm=arm,
                            status="NO_INTENT",
                        )
                    )
                elif self._clock.now_ms() >= deadline:
                    new_outcomes.append(
                        await self._record_outcome(
                            claim=claim,
                            bundle=bundle,
                            evaluation=evaluation,
                            arm=arm,
                            status="MISSED",
                        )
                    )

            all_outcomes = tuple(await self._repository.outcomes(campaign_id, sample_id))
            denominator = None
            if len(schedule.windows) == 1 and len(all_outcomes) == len(Arm):
                denominator = await self._repository.seal_denominator(campaign_id)
            results.append(
                BridgeResult(
                    claim,
                    bundle,
                    evaluation,
                    all_outcomes,
                    (),
                    denominator,
                    stopped_reason="RESTART_RECONCILIATION_NO_DISPATCH",
                    durability_blockers=(
                        ("RISK_SHADOW_RESULT_NOT_REPRESENTABLE_IN_ACCEPTED_CAMPAIGN_RECEIPTS",)
                        if any(row.arm_id == Arm.STRATEGY_REVIEW.value for row in all_outcomes)
                        else ()
                    ),
                )
            )
        return tuple(results)

    async def _run_one(
        self,
        *,
        campaign_id: str,
        max_window_seconds: int,
    ) -> BridgeResult:
        context = await self._repository.load_campaign(campaign_id)
        if len(context) != 3:
            raise RuntimeError(
                "accepted load_campaign API must return plan, schedule, and candidate protocol"
            )
        plan, schedule, _protocol = context
        if getattr(plan, "recording_mode", None) != "CAUSAL_OBSERVATION":
            raise RuntimeError("campaign coordinator requires the preregistered causal observation mode")
        if len(schedule.windows) != 1:
            raise RuntimeError("offline bridge is bounded to exactly one scheduled window")
        window = schedule.windows[0]
        if self._clock.now_ms() < int(window.market_as_of_ts_ms):
            return BridgeResult(None, None, None, (), (), stopped_reason="WINDOW_CUTOFF_NOT_REACHED")

        claim = await self._repository.claim_next(campaign_id)
        if claim is None:
            return BridgeResult(None, None, None, (), (), stopped_reason="NO_DUE_UNCLAIMED_SCHEDULED_WINDOW")
        sample_id = claim.sample_id
        capture = self._capture_reports.get((campaign_id, sample_id))
        if capture is None or capture.blockers or capture.missing_source_keys:
            outcomes = await self._record_all_outcomes(
                claim=claim,
                bundle=None,
                evaluation=None,
                statuses={arm: "SOURCE_MISSING" for arm in Arm},
                decisions={},
            )
            denominator = await self._seal_single_window(campaign_id, schedule)
            return BridgeResult(
                claim, None, None, outcomes, (), denominator, "PREREGISTERED_SOURCE_SET_INCOMPLETE"
            )

        bundle = await self._repository.freeze_bundle(claim)
        captured = await self._repository.resolve_causal_sources(
            campaign_id=campaign_id,
            sample_id=sample_id,
            source_receipt_sha256s=tuple(bundle.source_receipt_sha256s),
        )
        cutoff = int(window.market_as_of_ts_ms)
        expected_keys = {(s.source_kind, s.source_name) for s in plan.required_sources}
        actual_keys = {(s.source_kind, s.source_name) for s in captured}
        if actual_keys != expected_keys or any(
            s.source_as_of_ts_ms > s.observed_at_ts_ms or s.observed_at_ts_ms > cutoff for s in captured
        ):
            raise RuntimeError("PERSISTED_SOURCE_RECEIPTS_FAILED_CAUSAL_RELOAD_VALIDATION")
        try:
            result = await self._evaluator.evaluate(
                campaign_context=context, claim=claim, bundle=bundle, sources=tuple(captured)
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            outcomes = await self._record_all_outcomes(
                claim=claim,
                bundle=bundle,
                evaluation=None,
                statuses={arm: "EVALUATOR_FAILED" for arm in Arm},
                decisions={},
            )
            denominator = await self._seal_single_window(campaign_id, schedule)
            return BridgeResult(claim, bundle, None, outcomes, (), denominator, "CAUSAL_EVALUATOR_FAILED")
        # Do not turn an ambiguous persistence error into EVALUATOR_FAILED:
        # the evaluation receipt may already be durable; restart reconciliation
        # will read window_state before assigning any outcome.
        evaluation = await self._repository.record_causal_evaluation(
            claim=claim, bundle=bundle, result=result
        )

        deadline = self._paired_deadline(schedule, sample_id)
        eval_recorded_at = await self._repository.evaluation_recorded_at(
            campaign_id=campaign_id,
            sample_id=sample_id,
            evaluation_receipt_sha256=evaluation.receipt_sha256,
        )
        late_eval = eval_recorded_at > deadline
        baseline_status = (
            "LATE" if late_eval else ("BASELINE" if evaluation.intent is not None else "NO_INTENT")
        )
        outcomes: list[object] = [
            await self._record_outcome(
                claim=claim,
                bundle=bundle,
                evaluation=evaluation,
                arm=Arm.STRATEGY_ONLY,
                status=baseline_status,
            )
        ]
        risks: list[object] = []
        intent = evaluation.intent
        for arm in (Arm.STRATEGY_REVIEW, Arm.LLM_PROPOSAL_RESEARCH):
            if self._clock.now_ms() >= deadline:
                outcomes.append(
                    await self._record_outcome(
                        claim=claim, bundle=bundle, evaluation=evaluation, arm=arm, status="MISSED"
                    )
                )
                continue
            if arm is Arm.STRATEGY_REVIEW and intent is None:
                outcomes.append(
                    await self._record_outcome(
                        claim=claim, bundle=bundle, evaluation=evaluation, arm=arm, status="NO_INTENT"
                    )
                )
                continue
            outcome, risk = await self._run_model_arm(
                context=context,
                claim=claim,
                bundle=bundle,
                evaluation=evaluation,
                arm=arm,
                source_receipts=tuple(captured),
                deadline=deadline,
                call_seconds=max(
                    0.01,
                    min(float(plan.maximum_call_seconds), max_window_seconds / 2),
                ),
            )
            outcomes.append(outcome)
            if risk is not None:
                risks.append(risk)
        denominator = await self._seal_single_window(campaign_id, schedule)
        return BridgeResult(
            claim,
            bundle,
            evaluation,
            tuple(outcomes),
            tuple(risks),
            denominator,
            durability_blockers=(
                ("RISK_SHADOW_RESULT_NOT_REPRESENTABLE_IN_ACCEPTED_CAMPAIGN_RECEIPTS",) if risks else ()
            ),
        )

    async def _run_model_arm(
        self,
        *,
        context: object,
        claim: object,
        bundle: object,
        evaluation: object,
        arm: Arm,
        source_receipts: tuple[object, ...],
        deadline: int,
        call_seconds: float,
    ) -> tuple[object, object | None]:
        campaign_id = claim.campaign_id
        sample_id = claim.sample_id
        attempt_id = self._attempt_id(claim, arm)
        now = self._clock.now_ms()
        await self._repository.record_cost(
            self._receipts.cost(
                campaign_id=campaign_id,
                sample_id=sample_id,
                arm_id=arm.value,
                attempt_id=attempt_id,
                stage="RESERVATION_REQUESTED",
                amount_microusd=self._maximum_arm_cost_microusd,
                observed_at_ts_ms=now,
            )
        )
        try:
            reservation = await self._budget.reserve(
                attempt_id=attempt_id,
                arm_id=arm,
                maximum_microusd=self._maximum_arm_cost_microusd,
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                self._record_outcome(
                    claim=claim,
                    bundle=bundle,
                    evaluation=evaluation,
                    arm=arm,
                    status="UNKNOWN",
                    attempt_id=None,
                )
            )
            raise
        except Exception:
            outcome = await self._record_outcome(
                claim=claim, bundle=bundle, evaluation=evaluation, arm=arm, status="UNKNOWN", attempt_id=None
            )
            return outcome, None

        if not reservation.approved:
            await self._repository.record_cost(
                self._receipts.cost(
                    campaign_id=campaign_id,
                    sample_id=sample_id,
                    arm_id=arm.value,
                    attempt_id=attempt_id,
                    stage="RESERVATION_DENIED",
                    amount_microusd=0,
                    observed_at_ts_ms=reservation.observed_at_ts_ms,
                )
            )
            status = "MISSED" if self._clock.now_ms() >= deadline else "BUDGET_BLOCKED"
            return (
                await self._record_outcome(
                    claim=claim, bundle=bundle, evaluation=evaluation, arm=arm, status=status
                ),
                None,
            )
        if not 0 <= reservation.reserved_microusd <= self._maximum_arm_cost_microusd:
            raise ValueError("budget adapter returned a reservation outside its durable request bound")
        await self._repository.record_cost(
            self._receipts.cost(
                campaign_id=campaign_id,
                sample_id=sample_id,
                arm_id=arm.value,
                attempt_id=attempt_id,
                stage="RESERVED",
                amount_microusd=reservation.reserved_microusd,
                observed_at_ts_ms=reservation.observed_at_ts_ms,
            )
        )
        start = self._receipts.start(
            campaign_context=context,
            claim=claim,
            bundle=bundle,
            arm_id=arm.value,
            attempt_id=attempt_id,
            budget_reservation_id=attempt_id,
            attempt_started_at_ts_ms=self._clock.now_ms(),
        )
        if not await self._repository.start_attempt(start):
            found = await self._repository.find_attempt(attempt_id)
            if found is None:
                raise RuntimeError("start_attempt returned duplicate but find_attempt found no durable START")
            old_start, terminal = found
            review = await self._repository.find_review(attempt_id)
            if terminal is None and review is None:
                return (
                    await self._record_outcome(
                        claim=claim,
                        bundle=bundle,
                        evaluation=evaluation,
                        arm=arm,
                        status="UNKNOWN",
                        attempt_id=old_start.attempt_id,
                    ),
                    None,
                )
            decision = review if review is not None else terminal
            status = self._decision_status(arm, decision, terminal, deadline)
            return (
                await self._record_outcome(
                    claim=claim,
                    bundle=bundle,
                    evaluation=evaluation,
                    arm=arm,
                    status=status,
                    attempt_id=attempt_id,
                    decision_receipt_sha256=getattr(decision, "receipt_sha256", None),
                ),
                None,
            )

        call = (
            self._composition.review_shadow(
                campaign_context=context,
                bundle=bundle,
                evaluation=evaluation,
                source_receipts=source_receipts,
                start=start,
            )
            if arm is Arm.STRATEGY_REVIEW
            else self._composition.propose_shadow(
                campaign_context=context,
                bundle=bundle,
                evaluation=evaluation,
                source_receipts=source_receipts,
                start=start,
            )
        )
        try:
            completion = await asyncio.wait_for(call, timeout=max(1, min(call_seconds, MAX_WINDOW_SECONDS)))
        except asyncio.CancelledError:
            await asyncio.shield(self._persist_unknown(claim, bundle, evaluation, arm, start))
            raise
        except (TimeoutError, AmbiguousCall):
            return await self._persist_unknown(claim, bundle, evaluation, arm, start), None
        except KnownCallFailure as failure:
            terminal = self._receipts.failed_terminal(
                start=start,
                failure=failure.failure,
                observed_at_ts_ms=failure.observed_at_ts_ms,
            )
            await self._repository.finish_attempt(terminal)
            await self._commit_cost(
                campaign_id=campaign_id,
                sample_id=sample_id,
                arm=arm,
                attempt_id=attempt_id,
                actual_microusd=failure.gateway_observed_cost_microusd,
                reservation_limit_microusd=reservation.reserved_microusd,
            )
            recorded_at = await self._repository.decision_recorded_at(
                campaign_id=campaign_id, sample_id=sample_id, arm_id=arm.value, attempt_id=attempt_id
            )
            status = "LATE" if max(failure.observed_at_ts_ms, recorded_at) > deadline else "CALL_FAILED"
            return (
                await self._record_outcome(
                    claim=claim,
                    bundle=bundle,
                    evaluation=evaluation,
                    arm=arm,
                    status=status,
                    attempt_id=attempt_id,
                    decision_receipt_sha256=getattr(terminal, "receipt_sha256", None),
                ),
                None,
            )

        if arm is Arm.STRATEGY_REVIEW:
            review = self._receipts.review(
                campaign_context=context,
                claim=claim,
                bundle=bundle,
                evaluation=evaluation,
                start=start,
                completion=completion,
            )
            await self._repository.record_review(review)
            await self._commit_cost(
                campaign_id=campaign_id,
                sample_id=sample_id,
                arm=arm,
                attempt_id=attempt_id,
                actual_microusd=completion.gateway_observed_cost_microusd,
                reservation_limit_microusd=reservation.reserved_microusd,
            )
            recorded_at = await self._repository.decision_recorded_at(
                campaign_id=campaign_id, sample_id=sample_id, arm_id=arm.value, attempt_id=attempt_id
            )
            status = (
                "LATE" if max(completion.observed_at_ts_ms, recorded_at) > deadline else completion.action
            )
            return (
                await self._record_outcome(
                    claim=claim,
                    bundle=bundle,
                    evaluation=evaluation,
                    arm=arm,
                    status=status,
                    attempt_id=attempt_id,
                    decision_receipt_sha256=getattr(review, "receipt_sha256", None),
                ),
                completion.risk_shadow_result,
            )

        terminal = self._receipts.proposal_terminal(
            start=start,
            proposal=completion.proposal,
            completion=completion.completion,
            observed_at_ts_ms=completion.observed_at_ts_ms,
        )
        await self._repository.finish_attempt(terminal)
        await self._commit_cost(
            campaign_id=campaign_id,
            sample_id=sample_id,
            arm=arm,
            attempt_id=attempt_id,
            actual_microusd=completion.gateway_observed_cost_microusd,
            reservation_limit_microusd=reservation.reserved_microusd,
        )
        recorded_at = await self._repository.decision_recorded_at(
            campaign_id=campaign_id, sample_id=sample_id, arm_id=arm.value, attempt_id=attempt_id
        )
        status = "LATE" if max(completion.observed_at_ts_ms, recorded_at) > deadline else "PROPOSAL"
        return (
            await self._record_outcome(
                claim=claim,
                bundle=bundle,
                evaluation=evaluation,
                arm=arm,
                status=status,
                attempt_id=attempt_id,
                decision_receipt_sha256=getattr(terminal, "receipt_sha256", None),
            ),
            None,
        )

    async def _persist_unknown(
        self, claim: object, bundle: object, evaluation: object, arm: Arm, start: object
    ) -> object:
        terminal = self._receipts.unresolved_terminal(start=start, observed_at_ts_ms=self._clock.now_ms())
        await self._repository.finish_attempt(terminal)
        return await self._record_outcome(
            claim=claim,
            bundle=bundle,
            evaluation=evaluation,
            arm=arm,
            status="UNKNOWN",
            attempt_id=start.attempt_id,
            decision_receipt_sha256=getattr(terminal, "receipt_sha256", None),
        )

    async def _commit_cost(
        self,
        *,
        campaign_id: str,
        sample_id: str,
        arm: Arm,
        attempt_id: str,
        actual_microusd: int,
        reservation_limit_microusd: int,
    ) -> None:
        if (
            type(actual_microusd) is not int
            or not 0 <= actual_microusd <= reservation_limit_microusd
            or actual_microusd > self._maximum_arm_cost_microusd
        ):
            # Keep the admitted reservation as outstanding; never widen it.
            return
        await self._repository.record_cost(
            self._receipts.cost(
                campaign_id=campaign_id,
                sample_id=sample_id,
                arm_id=arm.value,
                attempt_id=attempt_id,
                stage="COMMIT_REQUESTED",
                amount_microusd=actual_microusd,
                observed_at_ts_ms=self._clock.now_ms(),
            )
        )
        try:
            committed = await self._budget.commit(
                attempt_id=attempt_id, arm_id=arm, actual_microusd=actual_microusd
            )
        except Exception:
            # The durable COMMIT_REQUESTED fence records uncertainty. No retry.
            return
        if committed.actual_microusd != actual_microusd:
            # Do not invent a different committed amount; retain the request fence.
            return
        await self._repository.record_cost(
            self._receipts.cost(
                campaign_id=campaign_id,
                sample_id=sample_id,
                arm_id=arm.value,
                attempt_id=attempt_id,
                stage="COMMITTED",
                amount_microusd=committed.actual_microusd,
                observed_at_ts_ms=committed.observed_at_ts_ms,
            )
        )

    async def _record_all_outcomes(
        self,
        *,
        claim: object,
        bundle: object | None,
        evaluation: object | None,
        statuses: dict[Arm, str],
        decisions: dict[Arm, tuple[str | None, str | None]],
    ) -> tuple[object, ...]:
        result = []
        for arm in Arm:
            attempt_id, decision_sha = decisions.get(arm, (None, None))
            result.append(
                await self._record_outcome(
                    claim=claim,
                    bundle=bundle,
                    evaluation=evaluation,
                    arm=arm,
                    status=statuses[arm],
                    attempt_id=attempt_id,
                    decision_receipt_sha256=decision_sha,
                )
            )
        return tuple(result)

    async def _record_outcome(
        self,
        *,
        claim: object,
        bundle: object | None,
        evaluation: object | None,
        arm: Arm,
        status: str,
        attempt_id: str | None = None,
        decision_receipt_sha256: str | None = None,
    ) -> object:
        outcome = self._receipts.outcome(
            campaign_id=claim.campaign_id,
            sample_id=claim.sample_id,
            arm_id=arm.value,
            claim_id=claim.claim_id,
            status=status,
            bundle_receipt_sha256=getattr(bundle, "receipt_sha256", None),
            evaluation_receipt_sha256=getattr(evaluation, "receipt_sha256", None),
            attempt_id=attempt_id,
            decision_receipt_sha256=decision_receipt_sha256,
            observed_at_ts_ms=self._clock.now_ms(),
        )
        await self._repository.record_outcome(outcome)
        return outcome

    async def _seal_single_window(self, campaign_id: str, schedule: object) -> object | None:
        # The repository verifies every preregistered window and all three arms.
        # Only invoke the seal when the frozen schedule itself has one window.
        if len(schedule.windows) != 1:
            return None
        return await self._repository.seal_denominator(campaign_id)

    @staticmethod
    def _scheduled_window(schedule: object, sample_id: str) -> object:
        return next(w for w in schedule.windows if w.sample_id == sample_id)

    @staticmethod
    def _paired_deadline(schedule: object, sample_id: str) -> int:
        window = OfflineCampaignOrchestrator._scheduled_window(schedule, sample_id)
        return int(window.paired_at_ts_ms)

    @staticmethod
    def _decision_status(arm: Arm, decision: object, terminal: object | None, deadline: int) -> str:
        if terminal is not None and getattr(terminal, "terminal_status", None) == "UNRESOLVED":
            return "UNKNOWN"
        if getattr(decision, "observed_at_ts_ms", 0) > deadline:
            return "LATE"
        if arm is Arm.STRATEGY_REVIEW:
            return getattr(getattr(decision, "output", None), "action", "UNKNOWN")
        if terminal is not None:
            if getattr(terminal, "terminal_status", None) == "FAILED":
                return "CALL_FAILED"
        return "PROPOSAL"


def _intents() -> tuple[ArmIntent, ...]:
    return (
        ArmIntent(
            arm=Arm.STRATEGY_ONLY,
            required_steps=("strategy_evaluation", "terminal_attempt_receipt"),
            uses_model=False,
            risk_shadow_only=False,
            candidate_isolated=True,
        ),
        ArmIntent(
            arm=Arm.STRATEGY_REVIEW,
            required_steps=(
                "strategy_evaluation",
                "cost_reservation",
                "durable_start_fence",
                "candidate_review",
                "risk_shadow_decision",
                "review_receipt",
                "terminal_attempt_receipt",
            ),
            uses_model=True,
            risk_shadow_only=True,
            candidate_isolated=True,
        ),
        ArmIntent(
            arm=Arm.LLM_PROPOSAL_RESEARCH,
            required_steps=(
                "cost_reservation",
                "durable_start_fence",
                "proposal_generation",
                "proposal_receipt",
                "terminal_attempt_receipt",
            ),
            uses_model=True,
            risk_shadow_only=False,
            candidate_isolated=True,
        ),
    )


def build_campaign_plan(
    readiness: Readiness,
    *,
    max_observations: int = MAX_OBSERVATIONS,
    max_window_seconds: int = MAX_WINDOW_SECONDS,
) -> CampaignPlan:
    """Build a finite, no-side-effect plan; default inputs are fail-closed."""

    blockers: list[str] = []
    binding = readiness.immutable_binding
    if binding is None or not all(
        (
            binding.campaign_id,
            binding.schedule_id,
            binding.claim_id,
            binding.window_id,
            binding.bundle_id,
            binding.evaluation_id,
        )
    ):
        blockers.append("MISSING_IMMUTABLE_CAMPAIGN_WINDOW_BUNDLE_EVALUATION_IDENTITY")
    if readiness.persistence_revision != ACCEPTED_PERSISTENCE_REVISION:
        blockers.append("PERSISTENCE_API_REVISION_NOT_ACCEPTED_HEAD")
    if readiness.lock_projection_revision != ACCEPTED_PERSISTENCE_REVISION:
        blockers.append("LOCK_PROJECTION_DOES_NOT_PIN_ACCEPTED_PERSISTENCE_HEAD")
    if not readiness.causal_sources_admitted:
        blockers.append("CAUSAL_MARKET_NEWS_MACRO_SOURCE_ADMISSION_NOT_ESTABLISHED")
    if not readiness.typed_composition_accepted:
        blockers.append("TYPED_COMPOSITION_NOT_ACCEPTED_FOR_CAUSAL_CAMPAIGN")
    if max_observations != MAX_OBSERVATIONS:
        blockers.append("OBSERVATION_BOUND_MUST_BE_EXACTLY_ONE")
    if not 1 <= max_window_seconds <= MAX_WINDOW_SECONDS:
        blockers.append("WINDOW_BOUND_OUTSIDE_ALLOWED_FINITE_LIMIT")
    if readiness.plan_only:
        blockers.append("PLAN_ONLY_DEFAULT_NO_RUNTIME_EXECUTION")
    if not readiness.owner_enabled_shadow_wiring:
        blockers.append("OWNER_HAS_NOT_ENABLED_BOUNDED_SHADOW_WIRING")

    status = PlanStatus.BLOCKED if blockers else PlanStatus.READY_FOR_OWNER_WIRING
    # The adapter never promotes a plan into a runner. Even a fully populated
    # readiness snapshot only describes the contract for owner-controlled wiring.
    if not blockers:
        status = PlanStatus.READY_FOR_OWNER_WIRING
    return CampaignPlan(
        status=status,
        binding=binding,
        max_observations=min(max_observations, MAX_OBSERVATIONS),
        max_window_seconds=min(max_window_seconds, MAX_WINDOW_SECONDS),
        arms=_intents(),
        blockers=tuple(blockers),
    )


def assert_non_trading_plan(plan: CampaignPlan) -> None:
    """Raise if a mutated/foreign plan attempts to widen its authority."""

    if len(plan.arms) != 3 or {intent.arm for intent in plan.arms} != set(Arm):
        raise ValueError("campaign protocol must contain exactly the three registered arms")
    if plan.max_observations != 1 or not 1 <= plan.max_window_seconds <= MAX_WINDOW_SECONDS:
        raise ValueError("campaign plan exceeds finite observation/time bounds")
    for intent in plan.arms:
        if intent.venue_calls_allowed or intent.trading_allowed:
            raise ValueError("shadow campaign cannot call a venue or trade")
    proposal = next(i for i in plan.arms if i.arm is Arm.LLM_PROPOSAL_RESEARCH)
    if proposal.risk_shadow_only or "risk_shadow_decision" in proposal.required_steps:
        raise ValueError("LLM proposal lane must remain isolated from risk evaluation")
    review = next(i for i in plan.arms if i.arm is Arm.STRATEGY_REVIEW)
    if not review.risk_shadow_only:
        raise ValueError("review risk decision must remain shadow-only")
