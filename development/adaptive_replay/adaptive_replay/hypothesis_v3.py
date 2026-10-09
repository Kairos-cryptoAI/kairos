"""Additive prospective clocks for an unchanged closed-price hypothesis.

The price-origin cut is not the actual creation clock. Caller-retained evidence
checks consistency, not source authenticity. This pure bounded contract neither
fetches nor calls a model, journals, trades, retimes V2, or qualifies economics.
Late creation after the first post-anchor minute is rejected rather than silently
discarding a possible earlier stop/trigger. The separate prompt/frame resolver,
durable producer and portfolio integrations are deliberately not supplied here.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from kairos_core.enums import Side
from kairos_strategy.adaptive.config import DEFAULT_CONFIG
from kairos_strategy.adaptive.logic import _planning_economics
from kairos_strategy.candles import Candle
from kairos_strategy.models import SleeveIntent
from kairos_strategy.provenance import candle_payload

from .historical_context import _clock, _name, _sha, digest
from .historical_replay import _validate_candidate
from .inputs import UNIVERSE
from .scenarios import (
    CAPABILITIES,
    MAX_OBSERVATIONS,
    MINUTE,
    TERMINAL,
    ScenarioEvidence,
    ScenarioObservation,
    _bar,
    _evidence,
)

POLICY_ID = "closed-hypothesis-actual-creation.v3"
EVIDENCE_KINDS = {"TEST_FIXTURE", "CALLER_ATTESTED_POINT_IN_TIME"}
MECHANICS = {
    "capabilities": {k: sorted(s.value for s in sides) for k, sides in CAPABILITIES.items()},
    "creation": "ACTUAL_AFTER_ALL_INPUTS_AND_PROPOSAL_COMPLETION_BEFORE_FIRST_POST_ANCHOR_CLOSE",
    "validity": "ORIGIN_CUT_PLUS_PRESEALED_LIFETIME_NEVER_ACTUAL_CREATION_PLUS_LIFETIME",
    "invalidation": "CLOSED_BAR_FROZEN_STOP_NOT_CONTINUOUS_TICK_COVERAGE",
    "confirmation": "FIRST_LATER_CLOSED_CLOSE_BEYOND_ORIGINAL_REFERENCE",
    "expiry": "MIN_PARENT_INCLUSIVE_TTL_HYPOTHESIS_QUOTE_AND_CONTEXT_DEADLINES",
    "quote_reference": "ASK_LONG_BID_SHORT_NO_FILL_AUTHORITY",
    "quoted_spread": "NO_WIDER_THAN_UNCHANGED_FIXED_PLANNING_ASSUMPTION",
    "quote_feasibility": "EXIT_SIDE_STOP_NOT_BREACHED_AND_ENTRY_SIDE_CONFIRMATION_STILL_HELD",
    "observation_coverage": "CONTIGUOUS_FROM_ORIGIN_CUT_BEFORE_NEXT_UNOBSERVED_COMPLETED_MINUTE",
    "source_authority": "CALLER_ATTESTATION_NOT_AUTHENTICATION_OR_ADMISSION",
}
METADATA_KEYS = {
    "hypothesis_id",
    "hypothesis_policy_sha256",
    "parent_intent_id",
    "parent_snapshot_sha256",
    "protection_sha256",
    "confirmation_observation_id",
    "entry_quote_sha256",
    "source_set_sha256",
    "hypothesis_origin",
    "evidence_kind",
    "hypothesis_origin_cut_ms",
    "hypothesis_actual_created_ms",
    "creation_assessment_sha256",
}


@dataclass(frozen=True)
class HypothesisPolicy:
    sealed_ms: int
    hypothesis_lifetime_ms: int
    quote_source_id: str
    maximum_quote_age_ms: int
    evidence_kind: str
    require_review: bool = True

    def __post_init__(self) -> None:
        for value in (self.sealed_ms, self.hypothesis_lifetime_ms, self.maximum_quote_age_ms):
            _clock(value)
        _name(self.quote_source_id)
        _name(self.evidence_kind)
        if (
            not 0 < self.hypothesis_lifetime_ms <= MAX_OBSERVATIONS * MINUTE
            or not 0 < self.maximum_quote_age_ms <= 5_000
            or self.evidence_kind not in EVIDENCE_KINDS
            or type(self.require_review) is not bool
        ):
            raise ValueError("explicit bounded validity, quote freshness, evidence kind and review required")

    @property
    def sha256(self) -> str:
        return digest(
            {
                "policy": POLICY_ID,
                "parameters": asdict(self),
                "mechanics": MECHANICS,
                "planning_config": asdict(DEFAULT_CONFIG),
            }
        )

    @property
    def clock_domain(self) -> str:
        return "TEST_SYNTHETIC" if self.evidence_kind == "TEST_FIXTURE" else "CALLER_ATTESTED_UTC"


@dataclass(frozen=True)
class CreationAssessment:
    """Caller-retained actual proposal completion, never a projected elapsed clock.

    Hash bindings do not verify that the model ran or authenticate its response.
    Input identity binds the supplied price/context receipts, not strategy geometry.
    The source resolver must independently retain/authenticate the full originals.
    """

    input_sha256: str
    response_sha256: str
    model_config_sha256: str
    direction: str
    actual_requested_ms: int
    actual_completed_ms: int
    actual_captured_ms: int
    evidence_kind: str
    provider: str = "OPENAI"

    def __post_init__(self) -> None:
        for value in (self.input_sha256, self.response_sha256, self.model_config_sha256):
            _sha(value)
        for value in (self.actual_requested_ms, self.actual_completed_ms, self.actual_captured_ms):
            _clock(value)
        if (
            self.direction not in {"LONG", "SHORT"}
            or self.provider != "OPENAI"
            or self.evidence_kind not in EVIDENCE_KINDS
            or not self.actual_requested_ms <= self.actual_completed_ms <= self.actual_captured_ms
        ):
            raise ValueError("explicit direction, OpenAI evidence and ordered actual completion required")

    @property
    def sha256(self) -> str:
        return digest(asdict(self))


def creation_input_sha256(
    source_set_sha256: str,
    context_sha256: str,
    anchor: Candle,
    sources: tuple[ScenarioEvidence, ...],
) -> str:
    """Pure input binding; no claim that all source originals were supplied."""
    _sha(source_set_sha256)
    _sha(context_sha256)
    _bar(anchor)
    _evidence(sources, anchor.symbol)
    return digest(
        {
            "policy": POLICY_ID,
            "source_set_sha256": source_set_sha256,
            "context_sha256": context_sha256,
            "anchor": candle_payload(anchor),
            "sources": [asdict(e) for e in sources],
        }
    )


@dataclass(frozen=True)
class EntryQuote:
    """A quote is not continuous coverage, a fill, or venue acceptance."""

    source_id: str
    symbol: str
    bid: float
    ask: float
    event_ms: int
    received_ms: int
    captured_ms: int
    ttl_ms: int
    evidence_kind: str

    def __post_init__(self) -> None:
        _name(self.source_id)
        _name(self.evidence_kind)
        for value in (self.event_ms, self.received_ms, self.captured_ms, self.ttl_ms):
            _clock(value)
        if (
            self.symbol not in UNIVERSE
            or self.evidence_kind not in EVIDENCE_KINDS
            or not self.event_ms <= self.received_ms <= self.captured_ms
            or self.ttl_ms == 0
            or any(
                type(p) not in {int, float} or not math.isfinite(p) or p <= 0 for p in (self.bid, self.ask)
            )
            or self.bid > self.ask
        ):
            raise ValueError("positive uncrossed quote, causal local clocks and explicit evidence required")

    @property
    def sha256(self) -> str:
        return digest({"policy": POLICY_ID, "quote": asdict(self)})


@dataclass(frozen=True)
class HypothesisPlan:
    template: SleeveIntent
    origin: str
    regime: str
    origin_cut_ms: int
    created_ms: int
    source_set_sha256: str
    context_sha256: str
    creation_evidence: tuple[ScenarioEvidence, ...]
    anchor: Candle
    required_sources: tuple[tuple[str, str], ...]
    policy: HypothesisPolicy
    creation_assessment: CreationAssessment | None = None

    def __post_init__(self) -> None:
        _validate_candidate(self.template)
        _clock(self.origin_cut_ms)
        _clock(self.created_ms)
        _sha(self.source_set_sha256)
        _sha(self.context_sha256)
        if type(self.policy) is not HypothesisPolicy:
            raise ValueError("separate typed V3 policy required")
        HypothesisPolicy(**asdict(self.policy))
        if self.policy.sealed_ms > self.origin_cut_ms:
            raise ValueError("hypothesis policy must be sealed by the original cut")
        if self.origin not in {"TECHNICAL", "CONTEXT_PROPOSAL"}:
            raise ValueError("explicit technical or independent context origin required")
        if self.regime not in CAPABILITIES or self.template.side not in CAPABILITIES[self.regime]:
            raise ValueError("unsupported regime/direction: no new uncertainty or crash permission")
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
            raise ValueError("exact original parent/cut/lifetime and non-conflicting provenance required")
        if self.created_ms < self.origin_cut_ms:
            raise ValueError("actual creation cannot predate the original cut")
        if self.created_ms > self.valid_until_ms:
            raise ValueError("hypothesis cannot be born expired or renew validity from actual creation")
        if self.created_ms >= self.origin_cut_ms + MINUTE:
            raise ValueError("late creation cannot skip the first already completed post-anchor minute")
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
            raise ValueError("canonical nonempty required source identities required")
        supplied = {(e.kind, e.source_id): e for e in self.creation_evidence}
        if not any(kind == "MARKET" for kind, _ in self.required_sources):
            raise ValueError("closed-market evidence is mandatory")
        if self.policy.quote_source_id in {e.source_id for e in self.creation_evidence}:
            raise ValueError("dedicated quote source cannot impersonate creation context")
        if self.origin == "CONTEXT_PROPOSAL" and not {"NEWS", "MACRO"} <= {
            kind for kind, _ in self.required_sources
        }:
            raise ValueError("context proposal requires explicit news and macro sources")
        if any(k not in supplied for k in self.required_sources) or not all(
            e.ready_at(self.created_ms) for e in self.creation_evidence
        ):
            raise ValueError("creation sources must be causally available and fresh at actual creation")
        if not any(
            e.kind == "MARKET"
            and (e.kind, e.source_id) in self.required_sources
            and e.event_ms == self.anchor.close_time_ms
            and e.payload_sha256 == digest(candle_payload(self.anchor))
            for e in self.creation_evidence
        ):
            raise ValueError("creation market receipt must bind actual anchor bytes")
        assessment = self.creation_assessment
        if self.origin == "TECHNICAL":
            if assessment is not None:
                raise ValueError("technical hypothesis cannot impersonate a model proposal")
        else:
            if type(assessment) is not CreationAssessment:
                raise ValueError("context proposal requires a typed actual creation assessment")
            CreationAssessment(**asdict(assessment))
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
                raise ValueError("proposal input identity/direction or actual completion clock conflict")

    @property
    def creation_input_sha256(self) -> str:
        return creation_input_sha256(
            self.source_set_sha256, self.context_sha256, self.anchor, self.creation_evidence
        )

    @property
    def parent_entry_lifetime_ms(self) -> int:
        return self.template.entry_expires_ts_ms - self.template.entry_eligible_ts_ms + 1

    @property
    def valid_until_ms(self) -> int:
        return self.origin_cut_ms + self.policy.hypothesis_lifetime_ms - 1

    @property
    def scenario_id(self) -> str:
        return digest({"policy": POLICY_ID, "policy_sha256": self.policy.sha256, "plan": asdict(self)})

    @property
    def protection_sha256(self) -> str:
        return digest(asdict(self.template.exit_plan))


@dataclass(frozen=True)
class HypothesisObservation:
    market: ScenarioObservation
    quote: EntryQuote | None = None

    def __post_init__(self) -> None:
        if type(self.market) is not ScenarioObservation:
            raise ValueError("typed closed market observation required")
        ScenarioObservation(
            self.market.candle, self.market.observed_ms, self.market.sources, self.market.review
        )
        if self.quote is not None:
            if type(self.quote) is not EntryQuote:
                raise ValueError("typed V3 quote required")
            EntryQuote(**asdict(self.quote))

    @property
    def context_sha256(self) -> str:
        return digest(
            {
                "policy": POLICY_ID,
                "sources": [asdict(e) for e in self.market.sources],
                "quote": None if self.quote is None else asdict(self.quote),
            }
        )

    @property
    def observation_id(self) -> str:
        return digest({"policy": POLICY_ID, "observation": asdict(self)})


@dataclass(frozen=True)
class HypothesisEvaluation:
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
        return digest({"policy": POLICY_ID, "evaluation": asdict(self)})


def _entry(plan: HypothesisPlan, observation: HypothesisObservation) -> tuple[SleeveIntent | None, str]:
    market, quote = observation.market, observation.quote
    if quote is None:
        return None, "FRESH_ENTRY_QUOTE_UNAVAILABLE"
    if (
        quote.source_id != plan.policy.quote_source_id
        or quote.source_id in {e.source_id for e in market.sources}
        or quote.symbol != plan.template.symbol
        or quote.evidence_kind != plan.policy.evidence_kind
        or quote.event_ms < market.candle.close_time_ms + 1
        or quote.captured_ms > market.observed_ms
        or market.observed_ms - quote.event_ms > min(quote.ttl_ms, plan.policy.maximum_quote_age_ms)
    ):
        return None, "ENTRY_QUOTE_IDENTITY_CLOCK_OR_FRESHNESS_CONFLICT"
    template = plan.template
    reference = quote.ask if template.side is Side.LONG else quote.bid
    exits = template.exit_plan
    stop, target, activation = exits.stop_price, exits.target_price, exits.trailing_activation_price
    if quote.bid <= stop if template.side is Side.LONG else quote.ask >= stop:
        return None, "QUOTE_EXIT_SIDE_ALREADY_BREACHES_STOP"
    if not (
        reference > template.reference_price
        if template.side is Side.LONG
        else reference < template.reference_price
    ):
        return None, "CLOSED_CONFIRMATION_NOT_HELD_AT_QUOTE"
    if not (stop < reference < target if template.side is Side.LONG else target < reference < stop):
        return None, "UNCHANGED_BARRIERS_NOT_EXECUTABLE"
    if activation is not None and not (
        reference < activation < target if template.side is Side.LONG else target < activation < reference
    ):
        return None, "UNCHANGED_TRAILING_ACTIVATION_ALREADY_PASSED"
    quoted_spread_bps = (quote.ask - quote.bid) / reference * 10_000
    if not math.isfinite(quoted_spread_bps) or quoted_spread_bps > DEFAULT_CONFIG.spread_bps:
        return None, "QUOTE_SPREAD_EXCEEDS_FIXED_PLANNING_ASSUMPTION"
    risk_bps, reward_bps, cost, net_rr = _planning_economics(reference, stop, target, DEFAULT_CONFIG)
    frozen_atr = dict(template.metadata).get("frozen_atr15")
    if frozen_atr is not None:
        try:
            atr = float(frozen_atr)
        except ValueError:
            return None, "INVALID_FROZEN_VOLATILITY"
        if not math.isfinite(atr) or atr <= 0:
            return None, "INVALID_FROZEN_VOLATILITY"
        if (
            not DEFAULT_CONFIG.minimum_stop_atr * atr
            <= abs(reference - stop)
            <= (DEFAULT_CONFIG.maximum_stop_atr * atr)
        ):
            return None, "STOP_OUTSIDE_FROZEN_ATR_BOUNDS"
    if risk_bps > DEFAULT_CONFIG.maximum_stop_bps:
        return None, "STOP_DISTANCE_TOO_WIDE"
    if cost > DEFAULT_CONFIG.maximum_cost_stop_fraction * risk_bps or net_rr < (
        DEFAULT_CONFIG.minimum_net_reward_risk
    ):
        return None, "INSUFFICIENT_COST_HEADROOM"
    expiry = min(
        plan.valid_until_ms,
        market.observed_ms + plan.parent_entry_lifetime_ms - 1,
        quote.event_ms + min(quote.ttl_ms, plan.policy.maximum_quote_age_ms),
        *(e.event_ms + e.ttl_ms for e in market.sources),
    )
    if expiry < market.observed_ms:
        return None, "FRESH_ENTRY_DEADLINE_ELAPSED"
    provenance = {
        "hypothesis_id": plan.scenario_id,
        "hypothesis_policy_sha256": plan.policy.sha256,
        "parent_intent_id": template.intent_id,
        "parent_snapshot_sha256": digest(asdict(template)),
        "protection_sha256": plan.protection_sha256,
        "confirmation_observation_id": observation.observation_id,
        "entry_quote_sha256": quote.sha256,
        "source_set_sha256": plan.source_set_sha256,
        "hypothesis_origin": plan.origin,
        "evidence_kind": plan.policy.evidence_kind,
        "hypothesis_origin_cut_ms": str(plan.origin_cut_ms),
        "hypothesis_actual_created_ms": str(plan.created_ms),
        "creation_assessment_sha256": "NONE"
        if plan.creation_assessment is None
        else plan.creation_assessment.sha256,
        "planning_cost_authority": "ASSUMPTION_NOT_VENUE_MEASUREMENT",
    }
    return SleeveIntent(
        POLICY_ID,
        template.symbol,
        template.side,
        market.observed_ms,
        market.observed_ms,
        expiry,
        reference,
        template.signal_strength,
        reward_bps,
        exits,
        tuple(sorted({**dict(template.metadata), **provenance}.items())),
    ), "FRESH_RESEARCH_CANDIDATE_NOT_RISK_APPROVAL"


def evaluate_hypothesis(
    plan: HypothesisPlan, observations: tuple[HypothesisObservation, ...]
) -> tuple[HypothesisEvaluation, ...]:
    """V3-only first-trigger fold, no V2 surrogate or renewable attempt.

    Every post-anchor minute must survive in order from the original price cut.
    Observed clocks cannot precede actual creation/receipts/review; slow source or
    review delivery cannot skip a completed minute or renew origin-cut validity.
    """
    if type(plan) is not HypothesisPlan:
        raise ValueError("typed separate V3 hypothesis required")
    HypothesisPlan(**{name: getattr(plan, name) for name in plan.__dataclass_fields__})
    if type(observations) is not tuple or len(observations) > MAX_OBSERVATIONS:
        raise ValueError("bounded immutable observations required")
    results = [
        HypothesisEvaluation(
            plan.scenario_id, None, None, "WAITING_TRIGGER", "HYPOTHESIS_ONLY", "AVAILABLE", plan.created_ms
        )
    ]
    seen: dict[int, str] = {}
    expected_open, last_clock = plan.origin_cut_ms, plan.created_ms
    for observation in observations:
        if type(observation) is not HypothesisObservation:
            raise ValueError("typed V3 observation required")
        HypothesisObservation(observation.market, observation.quote)
        market = observation.market
        bar, identity = market.candle, observation.observation_id
        if bar.symbol != plan.template.symbol:
            raise ValueError("hypothesis observation symbol conflict")
        if bar.open_time_ms in seen:
            if seen[bar.open_time_ms] != identity:
                raise ValueError("conflicting redelivery: original quote/review receipt must survive")
            continue
        if market.observed_ms < last_clock or bar.open_time_ms < expected_open:
            raise ValueError("hypothesis observations cannot go backwards or predate actual creation")
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
            else (bar.high >= plan.template.exit_plan.stop_price)
        ):
            state, reason = "INVALIDATED", "FROZEN_CLOSED_BAR_STOP_BREACHED"
        elif (
            bar.close > plan.template.reference_price
            if plan.template.side is Side.LONG
            else (bar.close < plan.template.reference_price)
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
            HypothesisEvaluation(
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
