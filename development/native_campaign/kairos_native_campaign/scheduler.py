"""Source-bound native campaign review/Risk seam, engineering-only.

The real causal scheduler owns claims, START fences, costs, three outcomes and
the denominator. This separate policy uses the real CandidateReviewBrain and
SIM Risk, saves their exact typed result before continuing, and replays that
result without another model request after a persistence interruption.

Only an explicitly disposable PostgreSQL campaign database and the finite
no-network transport are accepted here. No enrollment, DDL, execution, venue,
outbox publisher, secrets, alpha freeze or trading service is constructed.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from typing import cast

from kairos_aggregator.candidate_review import (
    CAUSAL_CANDIDATE_REVIEW_SYSTEM,
    CandidateReviewBrain,
    CandidateReviewOutput,
    compile_decision_context,
)
from kairos_core import CandidateRouteV1, EvidenceReferenceV1, canonical_sha256
from kairos_core.contracts import DecisionContextV1, SimulationSessionV1
from kairos_core.contracts.base import canonical_json_bytes
from kairos_core.contracts.decision_context import DecisionContextReceiptV1, DecisionContextSourceV1
from kairos_core.enums import CandidateReviewTier, ReasoningEffort
from kairos_core.topics import Topics
from kairos_llm.budget import BudgetedLLMGateway
from kairos_llm.campaign import _IndependentBudgetObserver
from kairos_llm.causal_campaign import (
    CausalAdaptiveCampaignScheduler,
    _module_sha256,
    causal_campaign_scheduler_sha256,
)
from kairos_llm.gateway import LLMGateway
from kairos_llm.models import LLMWorkload
from kairos_llm.proposals import proposal_evidence_id
from kairos_llm.research import ResearchEvidenceError, _AttemptBudget, _ObservedGateway
from kairos_persistence.campaign_inputs import decode_campaign_macro, decode_campaign_news
from kairos_persistence.causal_campaign import CampaignMarketContextV1
from kairos_persistence.research_campaign import ResearchReviewOutputV1, ResearchReviewReceiptV1
from kairos_persistence.research_evidence import ResearchLLMAttemptStartV1
from kairos_persistence.simulation_repository import SimulationRepository
from kairos_risk.simulation import SimulationRiskPolicy

from .contracts import NativeReviewRiskReceiptV1, native_review_risk_composition_sha256
from .storage import (
    NativeReviewRiskJournal,
    ReadOnlySealedBarWindowResolver,
    require_disposable_campaign_database,
    require_prepared_native_target,
)
from .transport import NoNetworkResponsesTransport

CONTEXT_RENDERER = "native-decision-context.v1"
MAXIMUM_CLOSED_BARS = 16


@dataclass(frozen=True, slots=True)
class FrozenSimSizing:
    """Hypothetical snapshot, not a venue account or a portfolio reservation."""

    equity_usd: str
    existing_open_risk_usd: str

    def __post_init__(self):
        for value in (self.equity_usd, self.existing_open_risk_usd):
            if type(value) is not str or not Decimal(value).is_finite():
                raise ValueError("explicit finite decimal SIM sizing strings required")
        if Decimal(self.equity_usd) <= 0 or Decimal(self.existing_open_risk_usd) < 0:
            raise ValueError("SIM equity must be positive and existing open risk nonnegative")

    @property
    def artifact_sha256(self):
        return canonical_sha256(self.identity_payload())

    def identity_payload(self):
        return {
            "version": "native-hypothetical-stop-sizing.v1",
            **asdict(self),
            "maximum_trade_risk_fraction": "0.0025",
            "maximum_open_risk_fraction": "0.01",
            "authority": "SIM_FIXTURE_ONLY_NOT_ACCOUNT_ADMISSION",
        }

    def quantity(self, intent, session, frame):
        if frame is None:
            return 0.0
        equity = Decimal(self.equity_usd)
        remaining = max(Decimal(0), equity * Decimal("0.01") - Decimal(self.existing_open_risk_usd))
        risk = min(equity * Decimal("0.0025"), remaining)
        # Include the SIM policy's adverse price cap and one outward tick.
        top = frame.asks[0].price if intent.side.value == "LONG" else frame.bids[0].price
        distance = (
            abs(Decimal(str(top)) - Decimal(str(intent.exit_plan.stop_price)))
            + Decimal(str(top)) * Decimal(str(session.assumptions.adverse_slippage_bps)) / 10_000
            + Decimal(str(session.assumptions.price_tick))
        )
        return float(risk / distance) if distance > 0 else 0.0


@dataclass(frozen=True, slots=True)
class NativeSimPolicy:
    sizing: FrozenSimSizing
    sessions: tuple[tuple[str, SimulationSessionV1], ...]

    def __post_init__(self):
        if type(self.sizing) is not FrozenSimSizing or type(self.sessions) is not tuple or not self.sessions:
            raise ValueError("explicit bounded native SIM policy required")
        keys = tuple(key for key, _ in self.sessions)
        if keys != tuple(sorted(set(keys))) or len(keys) > 64:
            raise ValueError("native SIM sessions must have a distinct sorted bounded sample roster")
        for key, session in self.sessions:
            if not key or type(session) is not SimulationSessionV1:
                raise ValueError("typed sample-bound SIM sessions required")
            if SimulationSessionV1.model_validate(session.model_dump(mode="json")) != session:
                raise ValueError("noncanonical native SIM session")

    @property
    def artifact_sha256(self):
        self.__post_init__()
        return canonical_sha256(
            {
                "version": "native-sim-policy.v1",
                "sizing_sha256": self.sizing.artifact_sha256,
                "sessions": [(key, value.model_dump(mode="json")) for key, value in self.sessions],
                "execution": "NO_ADMISSION_NO_COMMAND_NO_ORDER",
            }
        )


def native_review_artifact_sha256(projector):
    projector.assert_frozen()
    return canonical_sha256(
        {
            "version": CONTEXT_RENDERER,
            "projector": projector.artifact_sha256,
            "system": CAUSAL_CANDIDATE_REVIEW_SYSTEM,
            "provider_output_schema": canonical_sha256(CandidateReviewOutput.model_json_schema()),
            "normalized_receipt_schema": canonical_sha256(ResearchReviewOutputV1.model_json_schema()),
            "context_schema": canonical_sha256(DecisionContextV1.model_json_schema()),
            "maximum_closed_bars": MAXIMUM_CLOSED_BARS,
            "sources": {
                name: _module_sha256(name)
                for name in (
                    "kairos_native_campaign.scheduler",
                    "kairos_native_campaign.contracts",
                    "kairos_native_campaign.storage",
                    "kairos_native_campaign.transport",
                    "kairos_aggregator.candidate_review",
                    "kairos_risk.simulation",
                )
            },
            "mapping": "exact-candidate-action-and-reason-codes-to-research-receipt.v1",
            "clock": "actual-route-and-context-clock-frozen-source-cut-no-backdating",
        }
    )


def native_scheduler_sha256(projector, policy):
    return canonical_sha256(
        {
            "version": "native-candidate-review-sim-campaign.v1",
            "causal_scheduler": causal_campaign_scheduler_sha256(projector),
            "native_review": native_review_artifact_sha256(projector),
            "sim_policy": policy.artifact_sha256,
            "mode": "OFFLINE_ENGINEERING_FIXTURE",
            "network": "NONE",
        }
    )


class _BoundAttemptGateway:
    def __init__(self, gateway, budget, observed):
        self.gateway, self.budget, self.observed = gateway, budget, observed

    async def complete(self, **kwargs):
        result = await self.gateway.complete(**kwargs)
        if self.budget.start is None:
            raise ResearchEvidenceError("native review has no durable START")
        # The budget adapter remaps the temporary gateway UUID to the durable
        # attempt ID. Provenance must record that same ID, not the temporary one.
        return replace(result, budget_reservation_id=self.budget.start.budget_reservation_id)


class NativeCandidateReviewScheduler(CausalAdaptiveCampaignScheduler):
    def __init__(self, *, database, sim_policy: NativeSimPolicy, **kwargs):
        require_disposable_campaign_database(database)
        self.database, self.sim_policy = database, sim_policy
        self.sim_repository = SimulationRepository(database.pool)
        self.native_journal = NativeReviewRiskJournal(database)
        self.risk_policy = SimulationRiskPolicy()
        super().__init__(**kwargs)

    def _scheduler_artifact(self, projector):
        return native_scheduler_sha256(projector, self.sim_policy)

    def _review_output_schema(self):
        return CandidateReviewOutput

    def _input_feature_sha256(self, arm_id):
        if arm_id == "strategy-review":
            return native_review_artifact_sha256(self.projector)
        return super()._input_feature_sha256(arm_id)

    def _assert_causal(self):
        super()._assert_causal()
        require_disposable_campaign_database(self.database)
        provider = self.gateway.gateway
        if (
            type(provider) is not LLMGateway
            or type(provider._injected_client) is not NoNetworkResponsesTransport
            or provider.settings.openai_api_key
            or provider.settings.deepseek_api_key
            or self.gateway.budget.repository.pool is not self.database.pool
            or type(self.evaluator._resolver) is not ReadOnlySealedBarWindowResolver
        ):
            raise ResearchEvidenceError(
                "native engineering requires exact no-network and actual isolated I/O"
            )

    async def _validate(self, campaign_id):
        await require_prepared_native_target(self.database)
        plan, schedule, protocol = await super()._validate(campaign_id)
        if (
            plan.recording_mode != "OFFLINE_ENGINEERING_FIXTURE"
            or plan.maximum_windows_per_tick != 1
            or self.review_prompt.system != CAUSAL_CANDIDATE_REVIEW_SYSTEM
            or self.review_prompt.user_prefix != CONTEXT_RENDERER
            or set(dict(self.sim_policy.sessions)) != {w.sample_id for w in schedule.windows}
            or any(
                arm.cost_model_sha256 != self.sim_policy.sizing.artifact_sha256
                or arm.hypothetical_exit_sha256 != self.sim_policy.artifact_sha256
                for arm in protocol.arms
            )
        ):
            raise ResearchEvidenceError(
                "native plan/prompt/session/sizing differs from frozen engineering policy"
            )
        # Adoption must already exist. There is no reset, copy or register path.
        await self.gateway.budget.repository.campaign_usage("openai")
        return plan, schedule, protocol

    async def _context(self, evaluation, sources, window, plan):
        advisory = self.projector.project(evaluation, sources, window)
        market_source = next(x for x in sources if x.source_kind == "MARKET_SNAPSHOT")
        market = CampaignMarketContextV1.model_validate(market_source.content)
        bars = await self.evaluator._resolver.load(market.bar_window_reference)
        now = self.clock()
        tier = CandidateReviewTier(advisory["tier"])
        workload = (
            LLMWorkload.AGGREGATOR_CONFLICT
            if tier is CandidateReviewTier.CONFLICT
            else LLMWorkload.AGGREGATOR_NORMAL
        )
        if workload is not self.review_prompt.workload:
            raise ResearchEvidenceError("native observed tier cannot escalate its preregistered model route")
        deadline = min(window.paired_at_ts_ms, evaluation.intent.entry_expires_ts_ms)
        route = CandidateRouteV1(
            source="native-campaign-router",
            intent=evaluation.intent,
            review_tier=tier,
            requested_reasoning_effort=ReasoningEffort.HIGH
            if tier is CandidateReviewTier.CONFLICT
            else ReasoningEffort.MEDIUM,
            routed_at_ms=now,
            review_deadline_ms=deadline,
            evidence_ids=tuple(advisory["text"]["message_ids"]),
            conflict_rationale="FROZEN_CAUSAL_TEXT_OPPOSES_INTENT"
            if tier is CandidateReviewTier.CONFLICT
            else None,
        )
        requirements = {(x.source_kind, x.source_name): x.maximum_age_ms for x in plan.required_sources}
        decoded = {
            "market": (
                (
                    market.market_snapshot,
                    market_source.observed_at_ts_ms,
                    requirements[(market_source.source_kind, market_source.source_name)],
                ),
            ),
            "closed_bars": tuple(
                (bar, market_source.observed_at_ts_ms, 1_380_000) for bar in bars[-MAXIMUM_CLOSED_BARS:]
            ),
            "text": tuple(
                (
                    decode_campaign_news(x.content),
                    x.observed_at_ts_ms,
                    requirements[(x.source_kind, x.source_name)],
                )
                for x in sources
                if x.source_kind == "NEWS" and x.reference in route.evidence_ids
            ),
            "macro": tuple(
                (
                    decode_campaign_macro(x.content),
                    x.observed_at_ts_ms,
                    requirements[(x.source_kind, x.source_name)],
                )
                for x in sources
                if x.source_kind == "MACRO"
            ),
        }
        topics = {
            "market": Topics.MARKET_SNAPSHOT,
            "closed_bars": Topics.CLOSED_BAR,
            "text": Topics.SENTIMENT_SIGNAL,
            "macro": Topics.STRATEGIC_ALLOCATION,
        }
        slots = []
        for kind, items in decoded.items():
            receipts = []
            for message, received, ttl in items:
                produced = int(message.produced_at.timestamp() * 1000)
                receipts.append(
                    DecisionContextReceiptV1(
                        message_id=message.message_id,
                        source=message.source,
                        topic=topics[kind],
                        content_sha256=canonical_sha256(message),
                        produced_at_ms=produced,
                        event_at_ms=message.close_time_ms if kind == "closed_bars" else produced,
                        received_at_ms=received,
                        ttl_ms=ttl,
                    )
                )
            slots.append(
                DecisionContextSourceV1(
                    kind=kind,
                    availability="AVAILABLE",
                    receipts=tuple(receipts),
                    payloads_json=canonical_json_bytes(
                        {"items": [m.model_dump(mode="json") for m, _, _ in items]}
                    ).decode(),
                )
            )
        context = DecisionContextV1(
            source="native-campaign-context",
            route_id=route.route_id,
            intent_id=route.intent.intent_id,
            route_identity_json=canonical_json_bytes(route.identity_payload()).decode(),
            intent_identity_json=route.intent.canonical_intent_bytes().decode(),
            symbol=route.intent.symbol,
            event_as_of_ms=now,
            knowledge_cutoff_ms=now,
            captured_at_ms=now,
            review_deadline_ms=deadline,
            maximum_closed_bars=MAXIMUM_CLOSED_BARS,
            required_sources=("market", "closed_bars", "text", "macro"),
            sources=tuple(slots),
        )
        return route, context

    async def _persist_saved(self, receipt):
        if await self.native_journal.load(receipt.campaign_id, receipt.sample_id) != receipt:
            raise ResearchEvidenceError("native replay requires the exact independently saved binding")
        plan, _, _ = await self.repository.load_campaign(receipt.campaign_id)
        state = await self.repository.window_state(receipt.campaign_id, receipt.sample_id)
        evaluation = state.get(("evaluation", "all", "one"))
        bundle = state.get(("bundle", "all", "one"))
        if (
            receipt.scheduler_sha256 != self.scheduler_sha256
            or receipt.plan_receipt_sha256 != plan.receipt_sha256
            or evaluation is None
            or bundle is None
            or receipt.evaluation_receipt_sha256 != evaluation.receipt_sha256
            or receipt.bundle_receipt_sha256 != bundle.receipt_sha256
            or receipt.candidate_review.intent != evaluation.intent
            or receipt.sim_risk_decision.session != dict(self.sim_policy.sessions)[receipt.sample_id]
            or receipt.sizing_sha256 != self.sim_policy.sizing.artifact_sha256
        ):
            raise ResearchEvidenceError(
                "saved native review/Risk binding conflicts with independent campaign facts"
            )
        if receipt.start is not None:
            found = await self.repository.find_attempt(receipt.start.attempt_id)
            if found is None or found[0] != receipt.start:
                raise ResearchEvidenceError("saved native receipt lacks its independently persisted START")
        await self._validate_saved_context(receipt, state)
        await self.sim_repository.record_risk_decision(receipt.sim_risk_decision)
        if receipt.normalized_review is not None:
            await self.repository.record_review(receipt.normalized_review)

    async def _validate_saved_context(self, receipt, state):
        """Verify exact saved context against independent bundle sources, no model replay."""
        plan, schedule, _ = await self.repository.load_campaign(receipt.campaign_id)
        window = next(w for w in schedule.windows if w.sample_id == receipt.sample_id)
        sources = await self.repository.resolve_causal_sources(
            campaign_id=receipt.campaign_id,
            sample_id=receipt.sample_id,
            source_receipt_sha256s=state[("bundle", "all", "one")].source_receipt_sha256s,
        )
        evaluation = state[("evaluation", "all", "one")]
        advisory = self.projector.project(evaluation, sources, window)
        route, context = receipt.candidate_review.route, receipt.decision_context
        if (
            context.captured_at_ms != route.routed_at_ms
            or context.knowledge_cutoff_ms != route.routed_at_ms
            or context.event_as_of_ms != route.routed_at_ms
            or route.routed_at_ms < window.market_as_of_ts_ms
            or route.review_deadline_ms != min(window.paired_at_ts_ms, evaluation.intent.entry_expires_ts_ms)
            or route.review_tier.value != advisory["tier"]
            or route.evidence_ids != tuple(sorted(advisory["text"]["message_ids"]))
        ):
            raise ResearchEvidenceError("saved native context/route differs from frozen campaign scope")
        market_source = next(x for x in sources if x.source_kind == "MARKET_SNAPSHOT")
        market = CampaignMarketContextV1.model_validate(market_source.content)
        expected = {
            "market": ((market.market_snapshot, market_source),),
            "text": tuple(
                (decode_campaign_news(x.content), x)
                for x in sources
                if x.source_kind == "NEWS" and x.reference in route.evidence_ids
            ),
            "macro": tuple(
                (decode_campaign_macro(x.content), x) for x in sources if x.source_kind == "MACRO"
            ),
        }
        requirements = {(x.source_kind, x.source_name): x.maximum_age_ms for x in plan.required_sources}
        for kind, values in expected.items():
            slot = next(x for x in context.sources if x.kind == kind)
            if slot.payloads() != tuple(message.model_dump(mode="json") for message, _ in values):
                raise ResearchEvidenceError("saved native context changed captured source content")
            for observed, (message, original) in zip(slot.receipts, values, strict=True):
                if (
                    original.observed_at_ts_ms > window.market_as_of_ts_ms
                    or observed.received_at_ms != original.observed_at_ts_ms
                    or observed.ttl_ms != requirements[(original.source_kind, original.source_name)]
                    or observed.content_sha256 != canonical_sha256(message)
                ):
                    raise ResearchEvidenceError("saved native source availability differs from frozen cutoff")
        closed = next(x for x in context.sources if x.kind == "closed_bars")
        # Replay requires the same registered window and full bar/global-book
        # chain audit as first execution, not merely valid selected bar rows.
        originals = (await self.evaluator._resolver.load(market.bar_window_reference))[-MAXIMUM_CLOSED_BARS:]
        if closed.payloads() != tuple(bar.model_dump(mode="json") for bar in originals) or any(
            x.received_at_ms != market_source.observed_at_ts_ms or x.ttl_ms != 1_380_000
            for x in closed.receipts
        ):
            raise ResearchEvidenceError("saved native context changed its independently sealed bar tail")
        provenance = receipt.candidate_review.model_provenance
        if provenance is not None and provenance.prompt_sha256 != canonical_sha256(
            {
                "system": self.review_prompt.system,
                "user": compile_decision_context(route, context),
            }
        ):
            raise ResearchEvidenceError("saved native model request differs from the actual compiled context")

    async def reconcile(self, campaign_id):
        await self._validate(campaign_id)
        for claim in await self.repository.pending_claims(campaign_id, limit=1):
            saved = await self.native_journal.load(campaign_id, claim.sample_id)
            if saved is not None:
                await self._persist_saved(saved)
        return await super().reconcile(campaign_id)

    async def _review(self, claim, bundle, evaluation, sources, plan, schedule, protocol):
        saved = await self.native_journal.load(claim.campaign_id, claim.sample_id)
        if saved is not None:
            await self._persist_saved(saved)
            return
        window = next(w for w in schedule.windows if w.sample_id == claim.sample_id)
        route, context = await self._context(evaluation, sources, window, plan)
        arm = protocol.arms[1]
        attempt_id = "kairos-native-review:" + canonical_sha256(
            {
                "plan": plan.receipt_sha256,
                "sample": claim.sample_id,
                "bundle": bundle.receipt_sha256,
                "evaluation": evaluation.receipt_sha256,
            }
        )
        if await self.repository.find_attempt(attempt_id) is not None:
            return  # Permanent no-resend fence, even without a saved response.

        def make_start(at):
            return ResearchLLMAttemptStartV1(
                attempt_id=attempt_id,
                budget_reservation_id=attempt_id,
                campaign_id=claim.campaign_id,
                sample_id=claim.sample_id,
                arm_id="strategy-review",
                schedule_digest=schedule.schedule_digest,
                candidate_protocol_digest=protocol.protocol_digest,
                arm_protocol_digest=protocol.arm_digest("strategy-review"),
                symbol=window.symbol,
                timeframe=window.timeframe,
                market_as_of_ts_ms=window.market_as_of_ts_ms,
                market_snapshot_sha256=bundle.market_snapshot_sha256,
                sample_deadline_ts_ms=window.sample_deadline_ts_ms,
                provider=arm.provider,
                requested_model=arm.model,
                prompt_sha256=self.review_prompt.prompt_sha256,
                attempt_started_at_ts_ms=at,
            )

        budget = _AttemptBudget(
            _IndependentBudgetObserver(self.gateway.budget, self.repository, claim, "strategy-review"),
            self.repository,
            make_start,
            self.clock,
        )
        observed = _ObservedGateway(self.gateway.gateway, self.clock)
        guarded = BudgetedLLMGateway(
            cast(LLMGateway, observed),
            budget,
            prices=self.gateway.prices,
            monthly_budgets_microusd=self.gateway.monthly_budgets_microusd,
        )
        bound = _BoundAttemptGateway(guarded, budget, observed)
        brain = CandidateReviewBrain(bound, source="native-campaign-review", clock_ms=self.clock)
        async with asyncio.timeout(plan.maximum_call_seconds):
            review = await brain.review_with_context(route, context)
        normalized = None
        provenance = review.model_provenance
        if provenance is not None:
            if (
                provenance.provider != arm.provider
                or provenance.model != arm.model
                or budget.start is None
                or observed.response is None
                or provenance.prompt_sha256
                != canonical_sha256(
                    {"system": self.review_prompt.system, "user": compile_decision_context(route, context)}
                )
            ):
                raise ResearchEvidenceError(
                    "native response differs from the exact frozen request/model/START"
                )
            refs = tuple(
                EvidenceReferenceV1(
                    kind=x.source_kind,
                    reference=x.reference,
                    content_sha256=x.content_sha256,
                    observed_at_ms=x.observed_at_ts_ms,
                )
                for x in sources
            )
            normalized = ResearchReviewReceiptV1(
                campaign_id=claim.campaign_id,
                sample_id=claim.sample_id,
                attempt_id=attempt_id,
                start_receipt_sha256=budget.start.receipt_sha256,
                bundle_receipt_sha256=bundle.receipt_sha256,
                evaluation_receipt_sha256=evaluation.receipt_sha256,
                output=ResearchReviewOutputV1(
                    action=review.decision.value,
                    rationale="|".join(review.reason_codes),
                    evidence_ids=tuple(sorted(proposal_evidence_id(x) for x in refs)),
                ),
                response_sha256=provenance.response_sha256,
                requested_model=arm.model,
                resolved_model=provenance.model,
                request_id=provenance.request_id,
                prompt_sha256=self.review_prompt.prompt_sha256,
                observed_at_ts_ms=observed.observed_at_ts_ms,
            )
        at = self.clock()
        session = dict(self.sim_policy.sessions)[claim.sample_id]
        frame = await self.sim_repository.load_latest_book_frame(
            session.tape_id, review.intent.symbol, as_of_ms=at
        )
        decision = self.risk_policy.evaluate(
            session=session,
            review=review,
            selected_book_frame=frame,
            decided_at_ms=at,
            requested_quantity=self.sim_policy.sizing.quantity(review.intent, session, frame),
        )
        composition = native_review_risk_composition_sha256(
            campaign_id=claim.campaign_id,
            sample_id=claim.sample_id,
            plan_receipt_sha256=plan.receipt_sha256,
            bundle_receipt_sha256=bundle.receipt_sha256,
            evaluation_receipt_sha256=evaluation.receipt_sha256,
            start=budget.start,
            decision_context=context,
            candidate_review=review,
            sim_risk_decision=decision,
            normalized_review=normalized,
            scheduler_sha256=self.scheduler_sha256,
            sizing_sha256=self.sim_policy.sizing.artifact_sha256,
        )
        receipt = NativeReviewRiskReceiptV1(
            source="native-campaign-composition",
            campaign_id=claim.campaign_id,
            sample_id=claim.sample_id,
            plan_receipt_sha256=plan.receipt_sha256,
            bundle_receipt_sha256=bundle.receipt_sha256,
            evaluation_receipt_sha256=evaluation.receipt_sha256,
            start=budget.start,
            decision_context=context,
            candidate_review=review,
            sim_risk_decision=decision,
            normalized_review=normalized,
            composition_sha256=composition,
            scheduler_sha256=self.scheduler_sha256,
            sizing_sha256=self.sim_policy.sizing.artifact_sha256,
            sizing_snapshot=self.sim_policy.sizing.identity_payload(),
            observed_at_ts_ms=self.clock(),
        )
        await self.native_journal.save(receipt)
        await self._persist_saved(receipt)
