"""Offline scenario lifecycle: a hypothesis is not an executable trade.

Additive research version. Native generators, old mapper/evaluators and runtime
admission are untouched. Caller-supplied receipts establish consistency, not
source authenticity. No provider, venue, bus, database or risk approval exists
here; an emitted SleeveIntent still needs independent review/risk/execution.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from kairos_core.enums import Side
from kairos_strategy.adaptive.config import DEFAULT_CONFIG
from kairos_strategy.adaptive.logic import _planning_economics
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from .historical_context import _clock, _name, _sha, digest
from .historical_replay import _validate_candidate
from .inputs import UNIVERSE

POLICY_ID = "closed-confirmation-scenario.v1"
MINUTE = 60_000
MAX_OBSERVATIONS = 60
TERMINAL = {"CONSUMED", "INVALIDATED", "EXPIRED", "BLOCKED"}
CAPABILITIES = {"BULL": {Side.LONG}, "BEAR": {Side.SHORT}, "RANGE": {Side.LONG, Side.SHORT}}


@dataclass(frozen=True)
class ScenarioEvidence:
    """Trusted local clocks supplied by an external source resolver, not a fetch."""

    source_id: str
    kind: str
    symbol: str
    payload_sha256: str
    event_ms: int
    received_ms: int
    captured_ms: int
    ttl_ms: int

    def __post_init__(self) -> None:
        _name(self.source_id)
        _sha(self.payload_sha256)
        if self.kind not in {"MARKET", "NEWS", "MACRO"} or self.symbol not in UNIVERSE:
            raise ValueError("exact source kind and five-symbol scope required")
        for clock in (self.event_ms, self.received_ms, self.captured_ms, self.ttl_ms):
            _clock(clock)
        if not self.event_ms <= self.received_ms <= self.captured_ms or self.ttl_ms == 0:
            raise ValueError("ordered local source clocks and positive TTL required")

    def ready_at(self, cut_ms: int) -> bool:
        return self.captured_ms <= cut_ms and cut_ms - self.event_ms <= self.ttl_ms


def _evidence(items: tuple[ScenarioEvidence, ...], symbol: str) -> None:
    if type(items) is not tuple or len(items) > 32:
        raise ValueError("bounded immutable evidence required")
    for item in items:
        if type(item) is not ScenarioEvidence or item.symbol != symbol:
            raise ValueError("source symbol conflict or invalid evidence type")
        ScenarioEvidence(**asdict(item))
    if len({(item.kind, item.source_id) for item in items}) != len(items):
        raise ValueError("duplicate source identity")
    if tuple(sorted(items, key=lambda item: (item.kind, item.source_id))) != items:
        raise ValueError("evidence must use canonical source order")


def _bar(bar: Candle) -> None:
    if type(bar) is not Candle:
        raise ValueError("typed closed candle required")
    Candle(**asdict(bar))
    if any(
        type(value) not in {int, float}
        for value in (
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bar.quote_volume,
            bar.taker_buy_volume,
            bar.taker_buy_quote_volume,
        )
    ):
        raise ValueError("candle numbers cannot be booleans or implicit coercions")


@dataclass(frozen=True)
class ScenarioPlan:
    """Frozen structural hypothesis. No LLM prices, confidence or sizing fields."""

    template: SleeveIntent
    origin: str
    regime: str
    created_ms: int
    source_set_sha256: str
    context_sha256: str
    creation_evidence: tuple[ScenarioEvidence, ...]
    anchor: Candle
    required_sources: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _validate_candidate(self.template)
        _clock(self.created_ms)
        _sha(self.source_set_sha256)
        _sha(self.context_sha256)
        if self.origin not in {"TECHNICAL", "CONTEXT_PROPOSAL"}:
            raise ValueError("explicit technical or independent context origin required")
        if self.template.exit_plan.trailing_activation_price is not None:
            raise ValueError("trailing exits are unsupported: never silently discard parent rules")
        if self.regime not in CAPABILITIES or self.template.side not in CAPABILITIES[self.regime]:
            raise ValueError("unsupported regime/direction: no implicit countertrend or crash entry")
        if (
            self.template.symbol not in UNIVERSE
            or self.created_ms != self.template.entry_eligible_ts_ms
            or self.template.decision_ts_ms != self.created_ms - 1
            or self.created_ms % MINUTE
            or self.template.entry_expires_ts_ms <= self.created_ms
            or self.template.entry_expires_ts_ms - self.created_ms > MAX_OBSERVATIONS * MINUTE
        ):
            raise ValueError("exact candidate cut and bounded original lifetime required")
        _bar(self.anchor)
        if (
            self.anchor.symbol != self.template.symbol
            or self.anchor.timeframe != "1m"
            or self.anchor.close_time_ms != self.created_ms - 1
            or self.anchor.open_time_ms != self.created_ms - MINUTE
            or self.anchor.close != self.template.reference_price
        ):
            raise ValueError("exact causal anchor and unchanged reference required")
        _evidence(self.creation_evidence, self.template.symbol)
        if (
            type(self.required_sources) is not tuple
            or not self.required_sources
            or tuple(sorted(set(self.required_sources))) != self.required_sources
        ):
            raise ValueError("canonical nonempty required source identities required")
        supplied = {(e.kind, e.source_id): e for e in self.creation_evidence}
        if not any(kind == "MARKET" for kind, _ in self.required_sources):
            raise ValueError("market evidence is always mandatory")
        if self.origin == "CONTEXT_PROPOSAL" and not {"NEWS", "MACRO"} <= {
            kind for kind, _ in self.required_sources
        }:
            raise ValueError("context proposal requires explicit news and macro sources")
        if any(key not in supplied for key in self.required_sources) or not all(
            e.ready_at(self.created_ms) for e in self.creation_evidence
        ):
            raise ValueError("creation context must be causally available and fresh")
        if not any(
            e.kind == "MARKET"
            and e.event_ms == self.anchor.close_time_ms
            and e.payload_sha256 == digest(candle_payload(self.anchor))
            for e in self.creation_evidence
        ):
            raise ValueError("creation market receipt must bind actual anchor bytes")

    @property
    def scenario_id(self) -> str:
        return digest({"policy": POLICY_ID, "plan": asdict(self)})


@dataclass(frozen=True)
class ScenarioReview:
    scenario_id: str
    side: Side
    disposition: str
    context_sha256: str
    completed_ms: int
    response_sha256: str

    def __post_init__(self) -> None:
        for value in (self.scenario_id, self.context_sha256, self.response_sha256):
            _sha(value)
        _clock(self.completed_ms)
        if (
            type(self.side) is not Side
            or self.side not in {Side.LONG, Side.SHORT}
            or self.disposition not in {"ALLOW", "VETO", "DEFER"}
        ):
            raise ValueError("direction-bound ALLOW/VETO/DEFER required")


@dataclass(frozen=True)
class ScenarioObservation:
    candle: Candle
    observed_ms: int
    sources: tuple[ScenarioEvidence, ...]
    review: ScenarioReview | None = None

    def __post_init__(self) -> None:
        _bar(self.candle)
        _clock(self.observed_ms)
        if (
            self.candle.timeframe != "1m"
            or self.candle.open_time_ms % MINUTE
            or self.candle.close_time_ms != self.candle.open_time_ms + MINUTE - 1
            or self.observed_ms <= self.candle.close_time_ms
        ):
            raise ValueError("complete closed minute and actual later observation clock required")
        _evidence(self.sources, self.candle.symbol)
        if self.review is not None:
            if type(self.review) is not ScenarioReview:
                raise ValueError("typed scenario review required")
            ScenarioReview(**asdict(self.review))

    @property
    def context_sha256(self) -> str:
        return digest([asdict(e) for e in self.sources])

    @property
    def observation_id(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class ScenarioEvaluation:
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
        return digest(asdict(self))


def _market_ready(observation: ScenarioObservation) -> bool:
    bar = observation.candle
    return any(
        e.kind == "MARKET"
        and e.event_ms == bar.close_time_ms
        and e.payload_sha256 == digest(candle_payload(bar))
        and e.ready_at(observation.observed_ms)
        for e in observation.sources
    )


def _invalidated(plan: ScenarioPlan, bar: Candle) -> bool:
    stop = plan.template.exit_plan.stop_price
    return bar.low <= stop if plan.template.side is Side.LONG else bar.high >= stop


def _confirmed(plan: ScenarioPlan, bar: Candle) -> bool:
    level = plan.template.reference_price
    return bar.close > level if plan.template.side is Side.LONG else bar.close < level


def _entry(plan: ScenarioPlan, observation: ScenarioObservation) -> tuple[SleeveIntent | None, str]:
    template, bar = plan.template, observation.candle
    reference = bar.close
    stop, target = template.exit_plan.stop_price, template.exit_plan.target_price
    if not (stop < reference < target if template.side is Side.LONG else target < reference < stop):
        return None, "UNCHANGED_BARRIERS_NOT_EXECUTABLE"
    # Existing common planning assumptions, not an observed quote/fill/invoice.
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
    if observation.observed_ms > template.entry_expires_ts_ms:
        return None, "ORIGINAL_ENTRY_LIFETIME_ELAPSED"
    candidate = SleeveIntent(
        sleeve_id=POLICY_ID,
        symbol=template.symbol,
        side=template.side,
        decision_ts_ms=observation.observed_ms,
        entry_eligible_ts_ms=observation.observed_ms,
        entry_expires_ts_ms=template.entry_expires_ts_ms,
        reference_price=reference,
        signal_strength=1.0,
        gross_reward_bps=reward_bps,
        exit_plan=ExitPlan(stop, target, template.exit_plan.max_holding_ms),
        metadata=tuple(
            sorted(
                {
                    "scenario_id": plan.scenario_id,
                    "parent_intent_id": template.intent_id,
                    "confirmation_observation_id": observation.observation_id,
                    "source_set_sha256": plan.source_set_sha256,
                    "origin": plan.origin,
                    "planning_cost_authority": "ASSUMPTION_NOT_VENUE_MEASUREMENT",
                }.items()
            )
        ),
    )
    return candidate, "CONFIRMED_RESEARCH_CANDIDATE_NOT_RISK_APPROVAL"


def evaluate_scenario(
    plan: ScenarioPlan,
    observations: tuple[ScenarioObservation, ...],
    *,
    require_review: bool = True,
) -> tuple[ScenarioEvaluation, ...]:
    """Bounded deterministic fold, immutable hash chain, one structural attempt.

    Duplicate delivery is collapsed only when exact bytes agree. A missing or
    unknowable minute blocks the scenario; it cannot silently skip a possible
    earlier trigger. First confirmed structure consumes even rejected attempts.
    `require_review=False` is an explicit offline strategy-only A/B control.
    No future outcome is passed to an earlier evaluation.
    """
    if type(plan) is not ScenarioPlan or type(require_review) is not bool:
        raise ValueError("typed scenario and explicit review mode required")
    ScenarioPlan(**asdict_plan(plan))
    if type(observations) is not tuple or len(observations) > MAX_OBSERVATIONS:
        raise ValueError("bounded immutable observations required")
    results = [
        ScenarioEvaluation(
            plan.scenario_id, None, None, "WAITING_TRIGGER", "HYPOTHESIS_ONLY", "AVAILABLE", plan.created_ms
        )
    ]
    seen: dict[int, str] = {}
    expected_open, last_clock = plan.created_ms, plan.created_ms
    for observation in observations:
        if type(observation) is not ScenarioObservation:
            raise ValueError("typed scenario observation required")
        ScenarioObservation(
            observation.candle, observation.observed_ms, observation.sources, observation.review
        )
        if observation.candle.symbol != plan.template.symbol:
            raise ValueError("scenario observation symbol conflict")
        bar, identity = observation.candle, observation.observation_id
        if bar.open_time_ms in seen:
            if seen[bar.open_time_ms] != identity:
                raise ValueError("conflicting retry: original receipt/review must survive")
            continue
        if observation.observed_ms < last_clock:
            raise ValueError("observation clocks cannot go backwards")
        if bar.open_time_ms < expected_open:
            raise ValueError("out-of-order scenario observation")
        prior = results[-1]
        candidate = None
        coverage = "AVAILABLE"
        if prior.state in TERMINAL:
            state, reason = prior.state, "TERMINAL_NO_RESURRECTION"
            coverage = prior.coverage
        elif observation.observed_ms > plan.template.entry_expires_ts_ms:
            state, reason = "EXPIRED", "ORIGINAL_ENTRY_LIFETIME_ELAPSED"
        elif bar.open_time_ms != expected_open or not _market_ready(observation):
            state, reason, coverage = "BLOCKED", "MARKET_GAP_OR_UNAVAILABLE", "UNAVAILABLE"
        elif _invalidated(plan, bar):
            # Conservative ordering: invalidation wins an ambiguous candle.
            state, reason = "INVALIDATED", "FROZEN_STOP_LEVEL_BREACHED"
        elif _confirmed(plan, bar):
            state = "CONSUMED"
            required = {(e.kind, e.source_id): e for e in observation.sources}
            if not all(
                key in required and required[key].ready_at(observation.observed_ms)
                for key in plan.required_sources
            ) or not all(e.ready_at(observation.observed_ms) for e in observation.sources):
                reason, coverage = "REQUIRED_CONTEXT_UNAVAILABLE", "UNAVAILABLE"
            elif require_review and observation.review is None:
                reason, coverage = "REVIEW_MISSING_DEFER", "UNAVAILABLE"
            elif require_review and (
                observation.review.scenario_id != plan.scenario_id
                or observation.review.side is not plan.template.side
                or observation.review.context_sha256 != observation.context_sha256
                or not max(e.captured_ms for e in observation.sources)
                <= observation.review.completed_ms
                <= observation.observed_ms
            ):
                reason, coverage = "REVIEW_IDENTITY_OR_CLOCK_CONFLICT", "UNAVAILABLE"
            elif require_review and observation.review.disposition != "ALLOW":
                reason = "REVIEW_" + observation.review.disposition
            else:
                candidate, reason = _entry(plan, observation)
        else:
            state, reason = "WAITING_TRIGGER", "NO_CLOSED_PRICE_CONFIRMATION"
        results.append(
            ScenarioEvaluation(
                plan.scenario_id,
                identity,
                prior.sha256,
                state,
                reason,
                coverage,
                observation.observed_ms,
                candidate,
            )
        )
        seen[bar.open_time_ms] = identity
        expected_open, last_clock = bar.open_time_ms + MINUTE, observation.observed_ms
    return tuple(results)


def asdict_plan(plan: ScenarioPlan) -> dict:
    """Revalidate nested contracts while preserving their strict typed objects."""
    return {name: getattr(plan, name) for name in plan.__dataclass_fields__}
