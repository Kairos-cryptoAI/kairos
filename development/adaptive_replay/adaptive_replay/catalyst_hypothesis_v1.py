"""Bounded catalyst countertrend research, never V3 admission or trading authority.

Only independently sourced context proposals gain both directions in a NORMAL
BULL/BEAR/RANGE. The true regime survives. Event eligibility, durable retention,
fresh defense admission, Risk and execution belong to the enclosing policy.
The unchanged V3 quote/economics function is an explicitly hash-bound kernel,
not permission to relabel this new capability as the frozen V3 experiment.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from kairos_core.enums import Side
from kairos_strategy.adaptive.config import STRATEGY_ID
from kairos_strategy.candles import Candle
from kairos_strategy.models import SleeveIntent
from kairos_strategy.provenance import candle_payload

from . import hypothesis_v3 as v3
from .complex_strategy import MAPPER_ID
from .historical_context import _clock, _sha, digest
from .historical_replay import _validate_candidate
from .inputs import UNIVERSE
from .scenarios import CAPABILITIES, MAX_OBSERVATIONS, MINUTE, TERMINAL, ScenarioEvidence, _bar, _evidence

POLICY_ID = "closed-catalyst-hypothesis.research.v1"
ENTRY_KERNEL_ID = v3.POLICY_ID + ":_entry"
ENTRY_KERNEL_SOURCE_SHA256 = hashlib.sha256(Path(v3.__file__).read_bytes()).hexdigest()
METADATA_KEYS = v3.METADATA_KEYS | {
    "entry_kernel_id",
    "entry_kernel_source_sha256",
    "entry_parameter_policy_sha256",
    "observed_regime",
    "observed_defense",
}
MECHANICS = {
    "id": POLICY_ID,
    "technical_capabilities": {k: sorted(s.value for s in sides) for k, sides in CAPABILITIES.items()},
    "context_capabilities": {k: ["LONG", "SHORT"] for k in CAPABILITIES},
    "defense": "NORMAL_ONLY_AT_CREATION_FRESH_ADMISSION_REQUIRED_DOWNSTREAM",
    "confirmation": "FIRST_CONTIGUOUS_CLOSED_CLOSE_BEYOND_FROZEN_REFERENCE",
    "invalidation": "CLOSED_BAR_FROZEN_STOP_BEFORE_CONFIRMATION_NOT_TICK_COVERAGE",
    "clock": "V3_ACTUAL_CREATION_NO_RETIMING_NO_RENEWAL",
    "consumption": "FIRST_TRIGGER_INCLUDING_VETO_DEFER_QUOTE_COST_AND_RISK_REFUSAL",
    "entry_kernel_id": ENTRY_KERNEL_ID,
    "entry_kernel_source_sha256": ENTRY_KERNEL_SOURCE_SHA256,
    "qualification": "UNQUALIFIED_RESEARCH_NO_ECONOMIC_OR_TRADING_ADMISSION",
}


@dataclass(frozen=True)
class CatalystPlan:
    template: SleeveIntent
    origin: str
    regime: str
    defense: str
    origin_cut_ms: int
    created_ms: int
    source_set_sha256: str
    context_sha256: str
    creation_evidence: tuple[ScenarioEvidence, ...]
    anchor: Candle
    required_sources: tuple[tuple[str, str], ...]
    policy: v3.HypothesisPolicy
    creation_assessment: v3.CreationAssessment | None = None

    def __post_init__(self) -> None:
        _validate_candidate(self.template)
        _clock(self.origin_cut_ms)
        _clock(self.created_ms)
        _sha(self.source_set_sha256)
        _sha(self.context_sha256)
        if type(self.policy) is not v3.HypothesisPolicy:
            raise ValueError("explicit typed V3 timing parameters required")
        v3.HypothesisPolicy(**asdict(self.policy))
        if self.policy.sealed_ms > self.origin_cut_ms:
            raise ValueError("parameters must be sealed by original cut")
        if self.origin not in {"TECHNICAL", "CONTEXT_PROPOSAL"}:
            raise ValueError("explicit technical or context origin required")
        if self.template.sleeve_id != (STRATEGY_ID if self.origin == "TECHNICAL" else MAPPER_ID):
            raise ValueError("exact unchanged native or context mapper template required")
        if self.defense != "NORMAL" or self.regime not in CAPABILITIES:
            raise ValueError("NORMAL BULL/BEAR/RANGE required; no crash or uncertainty permission")
        if self.origin == "TECHNICAL" and self.template.side not in CAPABILITIES[self.regime]:
            raise ValueError("technical direction outside unchanged native capability")
        if self.origin == "CONTEXT_PROPOSAL" and not self.policy.require_review:
            raise ValueError("independent catalyst always requires separate review")
        if (
            self.template.symbol not in UNIVERSE
            or self.origin_cut_ms != self.template.entry_eligible_ts_ms
            or self.template.decision_ts_ms != self.origin_cut_ms - 1
            or self.origin_cut_ms % MINUTE
            or not 0 < self.parent_entry_lifetime_ms <= MAX_OBSERVATIONS * MINUTE
            or METADATA_KEYS & dict(self.template.metadata).keys()
            or dict(self.template.metadata).get("planning_cost_authority", "ASSUMPTION_NOT_VENUE_MEASUREMENT")
            != "ASSUMPTION_NOT_VENUE_MEASUREMENT"
        ):
            raise ValueError("exact original parent/cut/lifetime and unoccupied provenance required")
        if not self.origin_cut_ms <= self.created_ms <= self.valid_until_ms:
            raise ValueError("actual creation cannot predate origin or renew expired validity")
        if self.created_ms >= self.origin_cut_ms + MINUTE:
            raise ValueError("late creation cannot skip first already completed post-anchor minute")
        _bar(self.anchor)
        if (
            self.anchor.symbol != self.template.symbol
            or self.anchor.timeframe != "1m"
            or self.anchor.open_time_ms != self.origin_cut_ms - MINUTE
            or self.anchor.close_time_ms != self.origin_cut_ms - 1
            or self.anchor.close != self.template.reference_price
        ):
            raise ValueError("exact original closed anchor and unchanged reference required")
        _evidence(self.creation_evidence, self.template.symbol)
        if (
            type(self.required_sources) is not tuple
            or not self.required_sources
            or any(
                type(k) is not tuple or len(k) != 2 or any(type(v) is not str for v in k)
                for k in self.required_sources
            )
            or tuple(sorted(set(self.required_sources))) != self.required_sources
        ):
            raise ValueError("canonical exact required source identities required")
        supplied = {(e.kind, e.source_id): e for e in self.creation_evidence}
        if set(supplied) != set(self.required_sources):
            raise ValueError("exact source roster required; no missing or additional creation source")
        kinds = {kind for kind, _ in self.required_sources}
        if "MARKET" not in kinds or self.origin == "CONTEXT_PROPOSAL" and not {"NEWS", "MACRO"} <= kinds:
            raise ValueError("market required and catalyst requires explicit NEWS/MACRO")
        if self.policy.quote_source_id in {e.source_id for e in self.creation_evidence}:
            raise ValueError("dedicated quote source cannot impersonate creation context")
        if not all(e.ready_at(self.created_ms) for e in self.creation_evidence):
            raise ValueError("all creation sources must be causally available and fresh")
        if not any(
            e.kind == "MARKET"
            and e.event_ms == self.anchor.close_time_ms
            and e.payload_sha256 == digest(candle_payload(self.anchor))
            for e in self.creation_evidence
        ):
            raise ValueError("creation market receipt must bind exact anchor bytes")
        assessment = self.creation_assessment
        if self.origin == "TECHNICAL":
            if assessment is not None:
                raise ValueError("technical cannot impersonate independent model creation")
        else:
            if type(assessment) is not v3.CreationAssessment:
                raise ValueError("typed actual catalyst creation assessment required")
            v3.CreationAssessment(**asdict(assessment))
            if (
                assessment.evidence_kind != self.policy.evidence_kind
                or assessment.direction != self.template.side.value
                or assessment.input_sha256 != self.creation_input_sha256
                or not max(self.origin_cut_ms, *(e.captured_ms for e in self.creation_evidence))
                <= assessment.actual_requested_ms
                <= assessment.actual_completed_ms
                <= assessment.actual_captured_ms
                <= self.created_ms
            ):
                raise ValueError("catalyst input/direction or actual completion clock conflict")

    @property
    def creation_input_sha256(self) -> str:
        return v3.creation_input_sha256(
            self.source_set_sha256, self.context_sha256, self.anchor, self.creation_evidence
        )

    @property
    def parent_entry_lifetime_ms(self) -> int:
        return self.template.entry_expires_ts_ms - self.template.entry_eligible_ts_ms + 1

    @property
    def valid_until_ms(self) -> int:
        return self.origin_cut_ms + self.policy.hypothesis_lifetime_ms - 1

    @property
    def policy_sha256(self) -> str:
        return digest({"mechanics": MECHANICS, "timing_parameters_sha256": self.policy.sha256})

    @property
    def scenario_id(self) -> str:
        return digest({"policy": self.policy_sha256, "plan": asdict(self)})

    @property
    def protection_sha256(self) -> str:
        return digest(asdict(self.template.exit_plan))


@dataclass(frozen=True)
class CatalystEvaluation:
    scenario_id: str
    observation_id: str | None
    previous_sha256: str | None
    state: str
    reason: str
    coverage: str
    observed_ms: int
    candidate: SleeveIntent | None = None

    @property
    def sha256(self) -> str:
        return digest({"policy": POLICY_ID, "kernel": ENTRY_KERNEL_SOURCE_SHA256, "evaluation": asdict(self)})


def _entry(plan: CatalystPlan, observation: v3.HypothesisObservation) -> tuple[SleeveIntent | None, str]:
    candidate, reason = v3._entry(plan, observation)
    if candidate is None:
        return None, reason
    metadata = {
        **dict(candidate.metadata),
        "hypothesis_policy_sha256": plan.policy_sha256,
        "entry_parameter_policy_sha256": plan.policy.sha256,
        "entry_kernel_id": ENTRY_KERNEL_ID,
        "entry_kernel_source_sha256": ENTRY_KERNEL_SOURCE_SHA256,
        "observed_regime": plan.regime,
        "observed_defense": plan.defense,
    }
    return replace(candidate, sleeve_id=POLICY_ID, metadata=tuple(sorted(metadata.items()))), reason


def evaluate_hypothesis(
    plan: CatalystPlan, observations: tuple[v3.HypothesisObservation, ...]
) -> tuple[CatalystEvaluation, ...]:
    """Own typed first-trigger fold; V3 input transports are not V3 admission.

    The enclosing whole-system policy must check freshly observed NORMAL defense
    before admission. This function has closed-minute stop evidence, not complete
    tick coverage, a provider publisher, order permission or a portfolio account.
    """
    if type(plan) is not CatalystPlan:
        raise ValueError("typed separate catalyst plan required")
    CatalystPlan(**{name: getattr(plan, name) for name in plan.__dataclass_fields__})
    if type(observations) is not tuple or len(observations) > MAX_OBSERVATIONS:
        raise ValueError("bounded immutable observations required")
    results = [
        CatalystEvaluation(
            plan.scenario_id, None, None, "WAITING_TRIGGER", "HYPOTHESIS_ONLY", "AVAILABLE", plan.created_ms
        )
    ]
    seen: dict[int, str] = {}
    expected_open, last_clock = plan.origin_cut_ms, plan.created_ms
    for observation in observations:
        if type(observation) is not v3.HypothesisObservation:
            raise ValueError("typed V3 transport observation required")
        v3.HypothesisObservation(observation.market, observation.quote)
        market = observation.market
        bar, identity = market.candle, observation.observation_id
        if bar.symbol != plan.template.symbol:
            raise ValueError("observation symbol conflict")
        if bar.open_time_ms in seen:
            if seen[bar.open_time_ms] != identity:
                raise ValueError("conflicting redelivery: preserve original quote/review receipt")
            continue
        if market.observed_ms < last_clock or bar.open_time_ms < expected_open:
            raise ValueError("observations cannot go backwards or predate actual creation")
        prior, candidate, coverage = results[-1], None, "AVAILABLE"
        if prior.state in TERMINAL:
            state, reason, coverage = prior.state, "TERMINAL_NO_RESURRECTION", prior.coverage
        elif market.observed_ms > plan.valid_until_ms:
            state, reason = "EXPIRED", "HYPOTHESIS_VALIDITY_ELAPSED"
        elif (
            bar.open_time_ms != expected_open
            or market.observed_ms >= bar.open_time_ms + 2 * MINUTE
            or not any(
                e.kind == "MARKET"
                and (e.kind, e.source_id) in plan.required_sources
                and e.event_ms == bar.close_time_ms
                and e.payload_sha256 == digest(candle_payload(bar))
                and e.ready_at(market.observed_ms)
                for e in market.sources
            )
        ):
            state, reason, coverage = "BLOCKED", "MARKET_GAP_OR_UNAVAILABLE", "UNAVAILABLE"
        elif (
            bar.low <= plan.template.exit_plan.stop_price
            if plan.template.side is Side.LONG
            else bar.high >= plan.template.exit_plan.stop_price
        ):
            state, reason = "INVALIDATED", "FROZEN_CLOSED_BAR_STOP_BREACHED"
        elif (
            bar.close > plan.template.reference_price
            if plan.template.side is Side.LONG
            else bar.close < plan.template.reference_price
        ):
            state = "CONSUMED"
            supplied = {(e.kind, e.source_id): e for e in market.sources}
            review = market.review
            if not all(
                k in supplied and supplied[k].ready_at(market.observed_ms) for k in plan.required_sources
            ) or not all(e.ready_at(market.observed_ms) for e in market.sources):
                reason, coverage = "REQUIRED_CONTEXT_UNAVAILABLE", "UNAVAILABLE"
            elif plan.policy.require_review and review is None:
                reason, coverage = "REVIEW_MISSING_DEFER", "UNAVAILABLE"
            elif plan.policy.require_review and (
                review.scenario_id != plan.scenario_id
                or review.side is not plan.template.side
                or review.context_sha256 != observation.context_sha256
                or not max(
                    max(e.captured_ms for e in market.sources),
                    observation.quote.captured_ms if observation.quote is not None else 0,
                )
                <= review.completed_ms
                <= market.observed_ms
            ):
                reason, coverage = "REVIEW_IDENTITY_OR_CLOCK_CONFLICT", "UNAVAILABLE"
            elif plan.policy.require_review and review.disposition != "ALLOW":
                reason = "REVIEW_" + review.disposition
            else:
                candidate, reason = _entry(plan, observation)
                if reason in {
                    "FRESH_ENTRY_QUOTE_UNAVAILABLE",
                    "ENTRY_QUOTE_IDENTITY_CLOCK_OR_FRESHNESS_CONFLICT",
                }:
                    coverage = "UNAVAILABLE"
        else:
            state, reason = "WAITING_TRIGGER", "NO_CLOSED_PRICE_CONFIRMATION"
        results.append(
            CatalystEvaluation(
                plan.scenario_id,
                identity,
                prior.sha256,
                state,
                reason,
                coverage,
                market.observed_ms,
                candidate,
            )
        )
        seen[bar.open_time_ms] = identity
        expected_open, last_clock = bar.open_time_ms + MINUTE, market.observed_ms
    return tuple(results)
