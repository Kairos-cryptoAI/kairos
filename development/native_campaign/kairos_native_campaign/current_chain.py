"""Bounded CURRENT Catalyst/native SIM adapters; no transport, I/O or authority.

The caller retains every returned checkpoint and exact input, supplies actual
clocks and source receipts, and owns budget reservations and durable effects.
Hypothesis-preview review and final issued-candidate review are distinct facts.
Neither a fresh Risk book nor this adapter renews the original quote deadline.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from adaptive_replay import catalyst_policy_v1 as catalyst
from adaptive_replay.catalyst_hypothesis_v1 import CatalystPlan, _entry, evaluate_hypothesis
from adaptive_replay.hypothesis_v3 import HypothesisObservation
from adaptive_replay.scenarios import ScenarioObservation, ScenarioReview
from kairos_aggregator.candidate_review import CandidateReviewBrain
from kairos_aggregator.config import AggregatorSettings
from kairos_aggregator.decision_context import CandidateContextStore
from kairos_core.contracts import (
    CandidateReviewV1,
    CandidateRouteV1,
    ClosedBarEventV1,
    DecisionContextV1,
    ObservedSimStrategyIntentV2,
    SimulationAdmissionV2,
    SimulationRiskDecisionV1,
    StrategyIntentV1,
    StrategyProvenanceV1,
)
from kairos_core.contracts.base import canonical_sha256, datetime_from_unix_ms
from kairos_risk.simulation import SimulationRiskPolicy
from kairos_router.candidate import CandidateRouterPolicy
from kairos_strategy.models import SleeveIntent
from kairos_strategy.provenance import features_sha256
from kairos_strategy.runtime import _bar_hashes, _runtime_exit_plan, _window_sha256, canonical_closed_bars

ADAPTER_ID = "current-catalyst-native-sim-bridge.v1"


@dataclass(frozen=True)
class CurrentCatalystChain:
    """Immutable fold wrapper, not a durable store or exactly-once dispatcher."""

    policy: catalyst.CatalystPolicy
    state: catalyst.EventState
    creation_ledger: catalyst.CreationLedger
    decision_ledger: catalyst.DecisionLedger

    def __post_init__(self):
        self.policy.__post_init__()
        for value, expected in (
            (self.state, catalyst.EventState),
            (self.creation_ledger, catalyst.CreationLedger),
            (self.decision_ledger, catalyst.DecisionLedger),
        ):
            if type(value) is not expected or value.policy_sha256 != self.policy.sha256:
                raise ValueError("exact retained CURRENT policy checkpoints required")
            value.__post_init__()

    @classmethod
    def start(cls, policy):
        return cls(
            policy,
            catalyst.initial_state(policy),
            catalyst.CreationLedger(policy.sha256),
            catalyst.DecisionLedger(policy.sha256),
        )

    def prepare(self, cells):
        prepared = catalyst.prepare_cut(self.policy, self.state, cells)
        return replace(self, state=prepared.checkpoint), prepared

    def materialize(self, prepared, *, symbol, origin, outcome):
        ledger, plans = catalyst.materialize(
            self.policy, prepared, self.creation_ledger, symbol=symbol, origin=origin, outcome=outcome
        )
        return replace(self, creation_ledger=ledger), plans

    def resolve(self, prepared, *, symbol, arm_id, issued_ms, runs, **admission):
        ledger, decision = catalyst.resolve_arm(
            self.policy,
            prepared,
            self.creation_ledger,
            decisions=self.decision_ledger,
            symbol=symbol,
            arm_id=arm_id,
            issued_ms=issued_ms,
            runs=runs,
            **admission,
        )
        return replace(self, decision_ledger=ledger), decision


def native_intent(
    raw: SleeveIntent,
    *,
    input_bars: tuple[ClosedBarEventV1, ...],
    strategy_revision: str,
    code_sha256: str,
    config_sha256: str,
) -> StrategyIntentV1:
    """Preserve raw clocks/geometry; assign the separate native contract identity.

    SleeveIntent and StrategyIntentV1 have different identity schemas. Their IDs
    are deliberately not made equal. Existing strict conversion refuses any
    unsupported trailing plan instead of silently discarding its protection.
    """
    if type(raw) is not SleeveIntent or type(input_bars) is not tuple or not input_bars:
        raise ValueError("exact raw candidate and immutable closed-bar prefix required")
    raw.__post_init__()
    bars = tuple(ClosedBarEventV1.model_validate(b.model_dump(mode="json")) for b in input_bars)
    if canonical_closed_bars(bars) != bars:
        raise ValueError("original ordered prefix required; no silent sorting")
    if bars[-1].symbol != raw.symbol or bars[-1].close_time_ms >= raw.decision_ts_ms:
        raise ValueError("native provenance must precede actual candidate issue")
    metadata = dict(raw.metadata)
    if "confirmation_bar_close_ms" in metadata:
        raise ValueError("native confirmation clock metadata must not replace an original field")
    metadata["confirmation_bar_close_ms"] = str(bars[-1].close_time_ms)
    intent = ObservedSimStrategyIntentV2(
        source=ADAPTER_ID,
        produced_at=datetime_from_unix_ms(raw.decision_ts_ms),
        strategy_id=raw.sleeve_id,
        strategy_revision=strategy_revision,
        symbol=raw.symbol,
        side=raw.side,
        decision_ts_ms=raw.decision_ts_ms,
        entry_eligible_ts_ms=raw.entry_eligible_ts_ms,
        entry_expires_ts_ms=raw.entry_expires_ts_ms,
        reference_price=raw.reference_price,
        signal_strength=raw.signal_strength,
        gross_reward_bps=raw.gross_reward_bps,
        exit_plan=_runtime_exit_plan(raw),
        provenance=StrategyProvenanceV1(
            strategy_code_sha256=code_sha256,
            config_sha256=config_sha256,
            input_window_sha256=_window_sha256(bars),
            features_sha256=features_sha256(metadata),
            input_bar_sha256s=_bar_hashes(bars),
        ),
        metadata=tuple(sorted(metadata.items())),
    )
    if (
        intent.decision_ts_ms != raw.decision_ts_ms
        or intent.entry_eligible_ts_ms != raw.entry_eligible_ts_ms
        or intent.entry_expires_ts_ms != raw.entry_expires_ts_ms
        or intent.exit_plan.stop_price != raw.exit_plan.stop_price
        or intent.exit_plan.target_price != raw.exit_plan.target_price
        or intent.exit_plan.max_holding_ms != raw.exit_plan.max_holding_ms
    ):
        raise ValueError("native bridge changed immutable clock or protection")
    return intent


@dataclass(frozen=True)
class HypothesisPreview:
    """Review target only; never the later issued candidate's authorization."""

    plan: CatalystPlan
    observations: tuple[HypothesisObservation, ...]
    intent: StrategyIntentV1

    @property
    def observation(self):
        return self.observations[-1]


def build_hypothesis_preview(plan, observations, **native_arguments) -> HypothesisPreview:
    """Expose the pure first-trigger preview without committing a missing review.

    Only the final observation may subsequently acquire its original review.
    Earlier retained observations, original sources and the quote stay unchanged.
    """
    if type(observations) is not tuple or not observations or observations[-1].market.review is not None:
        raise ValueError("original first-trigger prefix without a replacement review required")
    evaluations = evaluate_hypothesis(plan, observations)
    last = evaluations[-1]
    if last.state != "CONSUMED" or last.reason != "REVIEW_MISSING_DEFER":
        raise ValueError("preview requires the first otherwise eligible reviewed trigger")
    raw, reason = _entry(plan, observations[-1])
    if raw is None:
        raise ValueError("first-trigger preview has no executable original quote: " + reason)
    return HypothesisPreview(plan, observations, native_intent(raw, **native_arguments))


def _exact_review(intent, review):
    if (
        type(intent) not in {StrategyIntentV1, ObservedSimStrategyIntentV2}
        or type(review) is not CandidateReviewV1
    ):
        raise ValueError("typed immutable native intent and review required")
    intent = StrategyIntentV1.model_validate(intent.model_dump(mode="json"))
    checked = CandidateReviewV1.model_validate(review.model_dump(mode="json"))
    expected = intent.canonical_intent_bytes()
    if checked.intent.canonical_intent_bytes() != expected or (
        checked.route.intent.canonical_intent_bytes() != expected
    ):
        raise ValueError("review belongs to another immutable preview/final candidate")
    return checked


def bind_scenario_review(
    preview: HypothesisPreview,
    native_review: CandidateReviewV1,
    *,
    actual_completed_ms: int,
) -> HypothesisObservation:
    """Bind the preview review to CURRENT scenario/source/quote, never to final ID."""
    if type(preview) is not HypothesisPreview:
        raise ValueError("exact retained hypothesis preview required")
    review = _exact_review(preview.intent, native_review)
    original = preview.observation
    if (
        type(actual_completed_ms) is not int
        or actual_completed_ms < review.reviewed_at_ms
        or review.reviewed_at_ms < original.market.observed_ms
    ):
        raise ValueError("hypothesis review cannot predate original observation")
    # Reconstruct the expected preview from retained bytes, catching replaced
    # plan/source/quote/observation objects as well as replaced native intents.
    raw, _ = _entry(preview.plan, original)
    retained_metadata = dict(preview.intent.metadata)
    close = retained_metadata.pop("confirmation_bar_close_ms", None)
    if (
        raw is None
        or retained_metadata != dict(raw.metadata)
        or close != str(original.market.candle.close_time_ms)
    ):
        raise ValueError("preview source/quote/scenario binding conflict")
    if (
        preview.intent.side is not preview.plan.template.side
        or preview.intent.reference_price != raw.reference_price
        or preview.intent.decision_ts_ms != raw.decision_ts_ms
        or preview.intent.entry_expires_ts_ms != raw.entry_expires_ts_ms
        or preview.intent.entry_eligible_ts_ms != raw.entry_eligible_ts_ms
        or preview.intent.strategy_id != raw.sleeve_id
        or preview.intent.signal_strength != raw.signal_strength
        or preview.intent.gross_reward_bps != raw.gross_reward_bps
        or preview.intent.exit_plan.stop_price != raw.exit_plan.stop_price
        or preview.intent.exit_plan.target_price != raw.exit_plan.target_price
        or preview.intent.exit_plan.max_holding_ms != raw.exit_plan.max_holding_ms
    ):
        raise ValueError("preview changed scenario direction, geometry or clock")
    scenario_review = ScenarioReview(
        preview.plan.scenario_id,
        preview.plan.template.side,
        review.decision.value,
        original.context_sha256,
        actual_completed_ms,
        canonical_sha256(review.model_dump(mode="json")),
    )
    return HypothesisObservation(
        ScenarioObservation(
            original.market.candle,
            actual_completed_ms,
            original.market.sources,
            scenario_review,
        ),
        original.quote,
    )


def build_final_route(intent, text, *, source="current-chain-router") -> CandidateRouteV1:
    """Use existing native classification without altering candidate or expiry."""
    intent = StrategyIntentV1.model_validate(intent.model_dump(mode="json"))
    return CandidateRouterPolicy(source=source).build(intent, text)


def build_native_context(route, receipts, *, cutoff_ms, captured_at_ms) -> DecisionContextV1:
    """Build current native context from explicit original local receipt clocks.

    ``receipts`` is a bounded tuple of (kind, typed_message, received_at_ms).
    This store is per-call and not durable. Replaying with fabricated old receipt
    clocks is forbidden; callers must retain the originals independently.
    """
    if type(receipts) is not tuple or len(receipts) > 4096:
        raise ValueError("bounded immutable native source receipt roster required")
    store = CandidateContextStore(
        AggregatorSettings(
            _env_file=None,
            bus_backend="memory",
            candidate_require_text_context=True,
            candidate_require_macro_context=True,
        )
    )
    for kind, message, received_at_ms in receipts:
        store.ingest(kind, message.model_dump(mode="json"), received_at_ms=received_at_ms)
    return store.build(route, cutoff_ms=cutoff_ms, captured_at_ms=captured_at_ms)


async def review_native(
    brain: CandidateReviewBrain, route: CandidateRouteV1, context: DecisionContextV1 | None
) -> CandidateReviewV1:
    """Actual existing Brain seam; caller owns real gateway/budget and context."""
    route = CandidateRouteV1.model_validate(route.model_dump(mode="json"))
    review = await brain.review_with_context(route, context)
    review = _exact_review(route.intent, review)
    if review.route != route:
        raise ValueError("native review changed original route")
    return review


def decide_sim(
    *,
    session,
    final_intent: StrategyIntentV1,
    final_review: CandidateReviewV1,
    selected_book_frame,
    decided_at_ms: int,
    requested_quantity: float,
) -> tuple[SimulationRiskDecisionV1, SimulationAdmissionV2 | None]:
    """Existing independent Risk decides; rejected/expired creates no admission.

    Quantity must already be sized against the caller's retained account/open
    risk budget. SimulationRiskPolicy additionally caps visible-book capacity;
    it is not account sizing. This pure function writes no decisions or orders.
    """
    review = _exact_review(final_intent, final_review)
    decision = SimulationRiskPolicy(source=ADAPTER_ID).evaluate(
        session=session,
        review=review,
        selected_book_frame=selected_book_frame,
        decided_at_ms=decided_at_ms,
        requested_quantity=requested_quantity,
    )
    admission = (
        SimulationAdmissionV2(source=ADAPTER_ID, decision=decision, admitted_at_ms=decided_at_ms)
        if decision.approved
        else None
    )
    return decision, admission
