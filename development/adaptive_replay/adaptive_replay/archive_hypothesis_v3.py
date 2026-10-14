"""Explicit dual-clock archive hypotheses; pure producer, never source admission.

Wall receipts describe a retained model run, not a model that ran historically.
Historical decision availability is an explicitly sealed model derived from
input readiness and measured wall elapsed. No native V3 clock/receipt is forged.
This bounded in-memory fold is connectable to a durable producer, not one itself.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, fields, is_dataclass
from decimal import Context, Decimal, localcontext
from enum import Enum
from pathlib import Path

from kairos_core.enums import Side
from kairos_strategy.adaptive.config import DEFAULT_CONFIG
from kairos_strategy.adaptive.logic import _planning_economics
from kairos_strategy.candles import Candle
from kairos_strategy.models import SleeveIntent
from kairos_strategy.provenance import candle_payload

from . import archive_market_clock_v3, hypothesis_v3
from .archive_market_clock_v3 import MAX_CLOCK_MS, ArchiveBBOQuoteV3, ArchiveMarketClockV3, archive_quote_v3
from .archive_portfolio_stream_v3 import ArchivePortfolioCheckpointV3
from .bookticker_archive_stream_v3 import BookTickerArchiveRowV3, _canonical
from .historical_context import _name, _sha
from .historical_replay import _validate_candidate
from .inputs import UNIVERSE
from .scenarios import CAPABILITIES, MAX_OBSERVATIONS, MINUTE, TERMINAL, _bar
from .system import AttemptReceipt

SCHEMA = "kairos.research.archive-hypothesis-modeled.v3"
POLICY_ID = "closed-hypothesis-archive-dual-clock.v3"
MAX_SOURCE_RECORDS = 32
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
ARITHMETIC = Context(prec=96)


def _plain(value):
    if is_dataclass(value):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value) if f.init}
    if isinstance(value, Enum):
        return value.value
    if type(value) is Decimal:
        return str(value)
    if type(value) is bytes:
        return {"exact_bytes_hex": value.hex()}
    if type(value) in {tuple, list}:
        return [_plain(v) for v in value]
    if type(value) is dict:
        return {k: _plain(v) for k, v in value.items()}
    return value


def digest(value):
    raw = _canonical(_plain(value))
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("bounded archive producer document exceeded; no truncation")
    return hashlib.sha256(raw).hexdigest()


def _ms(value):
    if type(value) is not int or not 0 <= value <= MAX_CLOCK_MS:
        raise ValueError("exact bounded clock required, never a boolean")


def _recheck(value, cls):
    if type(value) is not cls:
        raise ValueError(f"exact separate {cls.__name__} required")
    rebuilt = cls(**{f.name: getattr(value, f.name) for f in fields(cls) if f.init})
    if rebuilt != value:
        raise ValueError("unchecked computed-field mutation differs from exact reconstruction")


def _implementation():
    paths = (
        Path(__file__),
        Path(hypothesis_v3.__file__),
        Path(archive_market_clock_v3.__file__),
        Path(_planning_economics.__code__.co_filename),
        Path(_validate_candidate.__code__.co_filename),
        Path(_bar.__code__.co_filename),
    )
    # AttemptReceipt is validated directly; its actual file is independently pinned.
    from . import system

    return digest(
        [
            [str(p.absolute()), hashlib.sha256(p.read_bytes()).hexdigest()]
            for p in (*paths, Path(system.__file__))
        ]
    )


@dataclass(frozen=True)
class ArchiveHypothesisPolicyV3:
    sealed_wall_ms: int
    replay_started_wall_ms: int
    hypothesis_lifetime_ms: int
    maximum_quote_age_ms: int
    quote_source_id: str
    quote_clock: ArchiveMarketClockV3
    model_queue_delay_ms: int
    model_processing_delay_ms: int
    evidence_kind: str
    require_review: bool

    def __post_init__(self):
        for value in (
            self.sealed_wall_ms,
            self.replay_started_wall_ms,
            self.hypothesis_lifetime_ms,
            self.maximum_quote_age_ms,
            self.model_queue_delay_ms,
            self.model_processing_delay_ms,
        ):
            _ms(value)
        _name(self.quote_source_id)
        _recheck(self.quote_clock, ArchiveMarketClockV3)
        if not (
            self.sealed_wall_ms <= self.replay_started_wall_ms
            and 0 < self.hypothesis_lifetime_ms <= MAX_OBSERVATIONS * MINUTE
            and 0 < self.maximum_quote_age_ms <= 5000
            and self.model_queue_delay_ms <= MINUTE
            and self.model_processing_delay_ms <= MINUTE
            and self.quote_clock.event_basis == "EVENT_E"
            and self.evidence_kind in {"TEST_FIXTURE", "RETAINED_WALL_MODEL_OUTPUT"}
            and type(self.require_review) is bool
        ):
            raise ValueError("explicit wall-presealed replay, E modeled clock, bounded delays required")

    @property
    def sha256(self):
        return digest(
            {
                "schema": SCHEMA,
                "policy": self,
                "planning_config": asdict(DEFAULT_CONFIG),
                "clock_rule": "INPUT_READY_PLUS_QUEUE_PLUS_WALL_CAPTURE_MINUS_REQUEST_PLUS_PROCESSING",
                "quote_rule": "MODEL_AVAILABILITY_FROM_E_PLUS_EXPLICIT_DELAY",
                "source_admitted": False,
                "prospective_blind_authority": False,
            }
        )


@dataclass(frozen=True)
class ArchiveSourceEvidenceV3:
    source_id: str
    kind: str
    symbol: str
    payload_sha256: str | None
    source_original_sha256: str
    event_history_ms: int
    modeled_available_history_ms: int | None
    ttl_ms: int
    status: str
    availability_model_sha256: str

    def __post_init__(self):
        _name(self.source_id)
        for value in (self.source_original_sha256, self.availability_model_sha256):
            _sha(value)
        if self.payload_sha256 is not None:
            _sha(self.payload_sha256)
        for value in (self.event_history_ms, self.ttl_ms):
            _ms(value)
        if self.modeled_available_history_ms is not None:
            _ms(self.modeled_available_history_ms)
        if (
            self.kind not in {"MARKET", "NEWS", "MACRO"}
            or self.symbol not in CAP_SYMBOLS
            or self.status not in {"AVAILABLE", "UNAVAILABLE"}
            or not self.ttl_ms
            or (self.status == "AVAILABLE")
            != (self.payload_sha256 is not None and self.modeled_available_history_ms is not None)
            or (
                self.modeled_available_history_ms is not None
                and self.modeled_available_history_ms < self.event_history_ms
            )
        ):
            raise ValueError("explicit modeled source availability or unresolved original required")

    def ready_at(self, history_ms):
        return (
            self.status == "AVAILABLE"
            and self.modeled_available_history_ms <= history_ms <= self.event_history_ms + self.ttl_ms
        )


CAP_SYMBOLS = frozenset(UNIVERSE)


def _sources(values, symbol):
    if type(values) is not tuple or len(values) > MAX_SOURCE_RECORDS:
        raise ValueError("bounded immutable full source tuple required")
    for value in values:
        _recheck(value, ArchiveSourceEvidenceV3)
        if value.symbol != symbol:
            raise ValueError("source symbol conflict")
    keys = tuple((v.kind, v.source_id) for v in values)
    if keys != tuple(sorted(set(keys))):
        raise ValueError("canonical unique source identities required")


@dataclass(frozen=True)
class ArchiveModelCompletionV3:
    attempt: AttemptReceipt
    response_wall_ms: int
    completed_wall_ms: int
    captured_wall_ms: int
    original_receipt_sha256: str
    input_sha256: str
    response_sha256: str | None
    model_config_sha256: str
    role: str
    decision: str | None
    provider: str = "OPENAI"

    def __post_init__(self):
        _recheck(self.attempt, AttemptReceipt)
        for value in (self.response_wall_ms, self.completed_wall_ms, self.captured_wall_ms):
            _ms(value)
        for value in (self.original_receipt_sha256, self.input_sha256, self.model_config_sha256):
            _sha(value)
        if self.response_sha256 is not None:
            _sha(self.response_sha256)
        _ms(self.attempt.requested_ms)
        _ms(self.attempt.observed_ms)
        choices = {"PROPOSAL": {"LONG", "SHORT"}, "REVIEW": {"ALLOW", "VETO", "DEFER"}}
        if (
            self.provider != "OPENAI"
            or self.role not in choices
            or not self.attempt.requested_ms
            <= self.response_wall_ms
            <= self.completed_wall_ms
            <= self.captured_wall_ms
            or self.captured_wall_ms != self.attempt.observed_ms
            or self.attempt.context_sha256 != self.input_sha256
            or (self.attempt.status == "COMPLETE")
            != (self.decision in choices[self.role] and self.response_sha256 is not None)
            or (
                self.attempt.status != "COMPLETE"
                and (self.decision is not None or self.response_sha256 is not None)
            )
        ):
            raise ValueError("unchanged actual wall attempt/response/completion/capture/expense required")

    def available_at(self, input_ready_history_ms, policy):
        _ms(input_ready_history_ms)
        _recheck(policy, ArchiveHypothesisPolicyV3)
        _recheck(self, ArchiveModelCompletionV3)
        expected_kind = "TEST_FIXTURE" if policy.evidence_kind == "TEST_FIXTURE" else "OBSERVED_POINT_IN_TIME"
        if (
            self.attempt.requested_ms < policy.replay_started_wall_ms
            or self.attempt.evidence_kind != expected_kind
        ):
            raise ValueError("original model wall request predates sealed replay or evidence domain differs")
        value = (
            input_ready_history_ms
            + policy.model_queue_delay_ms
            + (self.captured_wall_ms - self.attempt.requested_ms)
            + policy.model_processing_delay_ms
        )
        _ms(value)
        return value

    @property
    def sha256(self):
        return digest({"schema": SCHEMA, "clock_domain": "ACTUAL_WALL_UTC", "receipt": self})


@dataclass(frozen=True)
class ArchiveQuoteProofV3:
    source_id: str
    original: BookTickerArchiveRowV3
    quote: ArchiveBBOQuoteV3
    index_manifest_sha256: str
    clock: ArchiveMarketClockV3
    source_prefix: ArchivePortfolioCheckpointV3

    def __post_init__(self):
        _name(self.source_id)
        _sha(self.index_manifest_sha256)
        _recheck(self.clock, ArchiveMarketClockV3)
        _recheck(self.source_prefix, ArchivePortfolioCheckpointV3)
        if type(self.quote) is not ArchiveBBOQuoteV3 or self.clock.event_basis != "EVENT_E":
            raise ValueError("exact E-based modeled archive quote, not native EntryQuote required")
        actual = archive_quote_v3(
            self.original, clock=self.clock, source_manifest_sha256=self.quote.source_manifest_sha256
        )
        if actual != self.quote:
            raise ValueError("quote differs from complete original raw row/Decimal/model clock")
        key = f"{self.quote.symbol}:{self.quote.transaction_day}"
        matches = [v for v in self.source_prefix.source_vector if v.source_key == key]
        if len(matches) != 1 or (
            matches[0].cursor.index_manifest_sha256 != self.index_manifest_sha256
            or matches[0].cursor.source_manifest_sha256 != self.quote.source_manifest_sha256
            or matches[0].cursor.clock_policy_sha256 != self.clock.sha256
            or matches[0].cursor.next_row <= self.quote.row_index
            or self.source_prefix.last_clock_ms < self.quote.modeled_available_at_ms
        ):
            raise ValueError("quote absent from independently retained exact source-vector prefix")

    @property
    def sha256(self):
        return digest({"schema": SCHEMA, "quote_proof": self})


def _creation_input(template, anchor, sources, source_set_sha256, context_sha256):
    return digest(
        {
            "schema": SCHEMA,
            "original_parent": template,
            "anchor": candle_payload(anchor),
            "sources": sources,
            "source_set": source_set_sha256,
            "context": context_sha256,
        }
    )


@dataclass(frozen=True)
class ArchiveHypothesisPlanV3:
    template: SleeveIntent
    origin: str
    regime: str
    origin_cut_history_ms: int
    source_set_sha256: str
    context_sha256: str
    anchor: Candle
    creation_sources: tuple[ArchiveSourceEvidenceV3, ...]
    required_sources: tuple[tuple[str, str], ...]
    policy: ArchiveHypothesisPolicyV3
    proposal: ArchiveModelCompletionV3 | None = None

    def __post_init__(self):
        if type(self.template) is not SleeveIntent or type(self.template.side) is not Side:
            raise ValueError("exact original native parent/Side required")
        _validate_candidate(self.template)
        _bar(self.anchor)
        _ms(self.origin_cut_history_ms)
        _recheck(self.policy, ArchiveHypothesisPolicyV3)
        _sources(self.creation_sources, self.template.symbol)
        for value in (self.source_set_sha256, self.context_sha256):
            _sha(value)
        if (
            self.origin not in {"TECHNICAL", "CONTEXT_PROPOSAL"}
            or self.regime not in CAPABILITIES
            or self.template.side not in CAPABILITIES[self.regime]
            or self.template.entry_eligible_ts_ms != self.origin_cut_history_ms
            or self.template.decision_ts_ms != self.origin_cut_history_ms - 1
            or self.origin_cut_history_ms % MINUTE
            or not 0 < self.parent_entry_lifetime_ms <= MAX_OBSERVATIONS * MINUTE
            or self.anchor.symbol != self.template.symbol
            or self.anchor.timeframe != "1m"
            or self.anchor.open_time_ms != self.origin_cut_history_ms - MINUTE
            or self.anchor.close_time_ms != self.origin_cut_history_ms - 1
            or self.anchor.close != self.template.reference_price
            or any(
                k.startswith("archive_hypothesis_") or k in hypothesis_v3.METADATA_KEYS
                for k, _ in self.template.metadata
            )
            or dict(self.template.metadata).get("planning_cost_authority", "ASSUMPTION_NOT_VENUE_MEASUREMENT")
            != "ASSUMPTION_NOT_VENUE_MEASUREMENT"
        ):
            raise ValueError("unchanged native cut/anchor/protection/capability/metadata required")
        if (
            type(self.required_sources) is not tuple
            or not self.required_sources
            or any(
                type(k) is not tuple or len(k) != 2 or any(type(v) is not str for v in k)
                for k in self.required_sources
            )
            or self.required_sources != tuple(sorted(set(self.required_sources)))
        ):
            raise ValueError("canonical nonempty required source roster required")
        if not any(k == "MARKET" for k, _ in self.required_sources) or self.policy.quote_source_id in {
            e.source_id for e in self.creation_sources
        }:
            raise ValueError("mandatory MARKET and separate quote identity required")
        if self.origin == "CONTEXT_PROPOSAL":
            if not {"NEWS", "MACRO"} <= {k for k, _ in self.required_sources}:
                raise ValueError("proposal requires explicit NEWS/MACRO obligations")
            _recheck(self.proposal, ArchiveModelCompletionV3)
            if (
                self.proposal.role != "PROPOSAL"
                or self.proposal.input_sha256 != self.creation_input_sha256
                or (self.proposal.decision is not None and self.proposal.decision != self.template.side.value)
            ):
                raise ValueError("exact proposal input/direction required")
        elif self.proposal is not None:
            raise ValueError("technical parent cannot impersonate model proposal")
        _ms(self.valid_until_history_ms)
        if (
            self.created_history_ms > self.valid_until_history_ms
            or self.created_history_ms >= self.origin_cut_history_ms + MINUTE
        ):
            raise ValueError("late creation cannot renew TTL or skip first completed minute")
        digest(self)

    @property
    def creation_input_sha256(self):
        return _creation_input(
            self.template, self.anchor, self.creation_sources, self.source_set_sha256, self.context_sha256
        )

    @property
    def input_ready_history_ms(self):
        return max(
            (
                self.origin_cut_history_ms,
                *(e.modeled_available_history_ms or 0 for e in self.creation_sources),
            )
        )

    @property
    def created_history_ms(self):
        return (
            self.input_ready_history_ms
            if self.proposal is None
            else self.proposal.available_at(self.input_ready_history_ms, self.policy)
        )

    @property
    def creation_available(self):
        supplied = {(e.kind, e.source_id): e for e in self.creation_sources}
        return (
            all(
                k in supplied and supplied[k].ready_at(self.created_history_ms) for k in self.required_sources
            )
            and all(e.ready_at(self.created_history_ms) for e in self.creation_sources)
            and any(
                e.kind == "MARKET"
                and (e.kind, e.source_id) in self.required_sources
                and e.event_history_ms == self.anchor.close_time_ms
                and e.payload_sha256 == hypothesis_v3.digest(candle_payload(self.anchor))
                for e in self.creation_sources
            )
            and (
                self.proposal is None
                or self.proposal.attempt.status == "COMPLETE"
                and self.proposal.attempt.cost_usd is not None
            )
        )

    @property
    def parent_entry_lifetime_ms(self):
        return self.template.entry_expires_ts_ms - self.template.entry_eligible_ts_ms + 1

    @property
    def valid_until_history_ms(self):
        return self.origin_cut_history_ms + self.policy.hypothesis_lifetime_ms - 1

    @property
    def scenario_id(self):
        return digest({"schema": SCHEMA, "policy_sha256": self.policy.sha256, "plan": self})

    @property
    def protection_sha256(self):
        return hypothesis_v3.digest(asdict(self.template.exit_plan))


@dataclass(frozen=True)
class ArchiveReviewV3:
    scenario_id: str
    side: Side
    context_sha256: str
    completion: ArchiveModelCompletionV3

    def __post_init__(self):
        _sha(self.scenario_id)
        _sha(self.context_sha256)
        _recheck(self.completion, ArchiveModelCompletionV3)
        if (
            type(self.side) is not Side
            or self.completion.role != "REVIEW"
            or self.completion.input_sha256 != self.context_sha256
        ):
            raise ValueError("direction/input-bound separate archive review required")


@dataclass(frozen=True)
class ArchiveHypothesisObservationV3:
    candle: Candle
    decision_history_ms: int
    sources: tuple[ArchiveSourceEvidenceV3, ...]
    quote: ArchiveQuoteProofV3 | None = None
    review: ArchiveReviewV3 | None = None

    def __post_init__(self):
        _bar(self.candle)
        _ms(self.decision_history_ms)
        _sources(self.sources, self.candle.symbol)
        if self.decision_history_ms <= self.candle.close_time_ms:
            raise ValueError("decision cannot precede completed original candle")
        if self.quote is not None:
            _recheck(self.quote, ArchiveQuoteProofV3)
        if self.review is not None:
            _recheck(self.review, ArchiveReviewV3)

    @property
    def context_sha256(self):
        return digest(
            {
                "schema": SCHEMA,
                "candle": candle_payload(self.candle),
                "sources": self.sources,
                "quote": self.quote,
            }
        )

    @property
    def input_ready_history_ms(self):
        return max(
            self.candle.close_time_ms + 1,
            *(e.modeled_available_history_ms or 0 for e in self.sources),
            self.quote.quote.modeled_available_at_ms if self.quote is not None else 0,
        )

    @property
    def observation_id(self):
        return digest({"schema": SCHEMA, "observation": self})


@dataclass(frozen=True)
class ArchiveHypothesisEvaluationV3:
    scenario_id: str
    observation_id: str | None
    previous_sha256: str | None
    state: str
    reason: str
    coverage: str
    decision_history_ms: int
    candidate: SleeveIntent | None = None

    @property
    def sha256(self):
        return digest({"schema": SCHEMA, "evaluation": self})


def _entry(plan, observation):
    proof = observation.quote
    if proof is None:
        return None, "MODELED_ENTRY_QUOTE_UNAVAILABLE", "UNAVAILABLE"
    quote, now = proof.quote, observation.decision_history_ms
    if (
        proof.source_id != plan.policy.quote_source_id
        or proof.clock != plan.policy.quote_clock
        or proof.source_id in {e.source_id for e in observation.sources}
        or quote.symbol != plan.template.symbol
        or quote.event_at_ms < observation.candle.close_time_ms + 1
        or quote.modeled_available_at_ms > now
        or proof.source_prefix.last_clock_ms > now
        or now - quote.event_at_ms > plan.policy.maximum_quote_age_ms
    ):
        return None, "MODELED_QUOTE_IDENTITY_CLOCK_OR_FRESHNESS_CONFLICT", "UNAVAILABLE"
    parent, exits = plan.template, plan.template.exit_plan
    reference = quote.ask_price if parent.side is Side.LONG else quote.bid_price
    stop, target = Decimal(str(exits.stop_price)), Decimal(str(exits.target_price))
    activation = (
        None if exits.trailing_activation_price is None else Decimal(str(exits.trailing_activation_price))
    )
    if quote.bid_price <= stop if parent.side is Side.LONG else quote.ask_price >= stop:
        return None, "QUOTE_EXIT_SIDE_ALREADY_BREACHES_STOP", "AVAILABLE"
    if not (
        reference > Decimal(str(parent.reference_price))
        if parent.side is Side.LONG
        else reference < Decimal(str(parent.reference_price))
    ):
        return None, "CLOSED_CONFIRMATION_NOT_HELD_AT_QUOTE", "AVAILABLE"
    if not (stop < reference < target if parent.side is Side.LONG else target < reference < stop):
        return None, "UNCHANGED_BARRIERS_NOT_EXECUTABLE", "AVAILABLE"
    if activation is not None and not (
        reference < activation < target if parent.side is Side.LONG else target < activation < reference
    ):
        return None, "UNCHANGED_TRAILING_ACTIVATION_ALREADY_PASSED", "AVAILABLE"
    with localcontext(ARITHMETIC):
        spread = (quote.ask_price - quote.bid_price) / reference * 10000
    if spread > Decimal(str(DEFAULT_CONFIG.spread_bps)):
        return None, "QUOTE_SPREAD_EXCEEDS_FIXED_PLANNING_ASSUMPTION", "AVAILABLE"
    # Native float planning is an unchanged assumption only. Executable quote
    # stays exact Decimal; do not round a source price to create permission.
    native_reference = float(reference)
    if not math.isfinite(native_reference) or Decimal(str(native_reference)) != reference:
        return None, "NATIVE_PLANNING_PRICE_NOT_EXACTLY_REPRESENTABLE", "UNAVAILABLE"
    risk, reward, cost, net_rr = _planning_economics(
        native_reference, exits.stop_price, exits.target_price, DEFAULT_CONFIG
    )
    atr = dict(parent.metadata).get("frozen_atr15")
    if atr is not None:
        try:
            atr = float(atr)
        except ValueError:
            return None, "INVALID_FROZEN_VOLATILITY", "AVAILABLE"
        if not math.isfinite(atr) or atr <= 0:
            return None, "INVALID_FROZEN_VOLATILITY", "AVAILABLE"
        if (
            not DEFAULT_CONFIG.minimum_stop_atr * atr
            <= abs(native_reference - exits.stop_price)
            <= DEFAULT_CONFIG.maximum_stop_atr * atr
        ):
            return None, "STOP_OUTSIDE_FROZEN_ATR_BOUNDS", "AVAILABLE"
    if risk > DEFAULT_CONFIG.maximum_stop_bps:
        return None, "STOP_DISTANCE_TOO_WIDE", "AVAILABLE"
    if (
        cost > DEFAULT_CONFIG.maximum_cost_stop_fraction * risk
        or net_rr < DEFAULT_CONFIG.minimum_net_reward_risk
    ):
        return None, "INSUFFICIENT_COST_HEADROOM", "AVAILABLE"
    expiry = min(
        plan.valid_until_history_ms,
        now + plan.parent_entry_lifetime_ms - 1,
        quote.event_at_ms + plan.policy.maximum_quote_age_ms,
        *(e.event_history_ms + e.ttl_ms for e in observation.sources),
    )
    if expiry < now:
        return None, "FRESH_ENTRY_DEADLINE_ELAPSED", "UNAVAILABLE"
    metadata = {
        "archive_hypothesis_id": plan.scenario_id,
        "archive_hypothesis_policy_sha256": plan.policy.sha256,
        "parent_intent_id": parent.intent_id,
        "parent_snapshot_sha256": hypothesis_v3.digest(asdict(parent)),
        "protection_sha256": plan.protection_sha256,
        "archive_confirmation_observation_id": observation.observation_id,
        "archive_quote_proof_sha256": proof.sha256,
        "archive_source_prefix_sha256": digest(proof.source_prefix),
        "archive_hypothesis_origin": plan.origin,
        "archive_hypothesis_origin_cut_ms": str(plan.origin_cut_history_ms),
        "archive_hypothesis_created_history_ms": str(plan.created_history_ms),
        "archive_hypothesis_wall_policy_sealed_ms": str(plan.policy.sealed_wall_ms),
        "archive_hypothesis_model_completion_sha256": "NONE"
        if plan.proposal is None
        else plan.proposal.sha256,
        "archive_hypothesis_review_sha256": "NONE"
        if observation.review is None
        else digest(observation.review),
        "evidence_kind": "ARCHIVE_MODELED_REFERENCE",
        "planning_cost_authority": "ASSUMPTION_NOT_VENUE_MEASUREMENT",
    }
    return (
        SleeveIntent(
            POLICY_ID,
            parent.symbol,
            parent.side,
            now,
            now,
            expiry,
            native_reference,
            parent.signal_strength,
            reward,
            exits,
            tuple(sorted({**dict(parent.metadata), **metadata}.items())),
        ),
        "MODELED_RESEARCH_CANDIDATE_NOT_ADMISSION",
        "AVAILABLE",
    )


def evaluate_archive_hypothesis_v3(plan, observations):
    if str(ARITHMETIC) != str(Context(prec=96)):
        raise ValueError("frozen exact Decimal96 arithmetic changed")
    _recheck(plan, ArchiveHypothesisPlanV3)
    if type(observations) is not tuple or len(observations) > MAX_OBSERVATIONS:
        raise ValueError("bounded immutable archive observations required")
    results = [
        ArchiveHypothesisEvaluationV3(
            plan.scenario_id,
            None,
            None,
            "WAITING_TRIGGER" if plan.creation_available else "BLOCKED",
            "MODELED_HYPOTHESIS_ONLY" if plan.creation_available else "CREATION_INPUT_OR_MODEL_UNAVAILABLE",
            "AVAILABLE" if plan.creation_available else "UNAVAILABLE",
            plan.created_history_ms,
        )
    ]
    seen, expected_open, last_clock = {}, plan.origin_cut_history_ms, plan.created_history_ms
    attempts = {} if plan.proposal is None else {plan.proposal.attempt.attempt_id: plan.proposal.sha256}
    for observation in observations:
        _recheck(observation, ArchiveHypothesisObservationV3)
        bar, now, identity = observation.candle, observation.decision_history_ms, observation.observation_id
        if bar.symbol != plan.template.symbol:
            raise ValueError("original observation symbol conflict")
        if bar.open_time_ms in seen:
            if seen[bar.open_time_ms] != identity:
                raise ValueError("conflicting exact original redelivery")
            continue
        if now < last_clock or bar.open_time_ms < expected_open:
            raise ValueError("archive observations cannot regress or predate modeled creation")
        if observation.review is not None:
            proof = observation.review.completion
            previous = attempts.get(proof.attempt.attempt_id)
            if previous is not None and previous != proof.sha256:
                raise ValueError("original attempt ID reused with conflicting input/response/expense")
            attempts[proof.attempt.attempt_id] = proof.sha256
        prior, candidate, coverage = results[-1], None, "AVAILABLE"
        if prior.state in TERMINAL:
            state, reason, coverage = prior.state, "TERMINAL_NO_RESURRECTION", prior.coverage
        elif now > plan.valid_until_history_ms:
            state, reason = "EXPIRED", "ORIGIN_CUT_VALIDITY_ELAPSED"
        elif (
            bar.open_time_ms != expected_open
            or now >= bar.open_time_ms + 2 * MINUTE
            or not any(
                e.kind == "MARKET"
                and (e.kind, e.source_id) in plan.required_sources
                and e.event_history_ms == bar.close_time_ms
                and e.payload_sha256 == hypothesis_v3.digest(candle_payload(bar))
                and e.ready_at(now)
                for e in observation.sources
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
            supplied = {(e.kind, e.source_id): e for e in observation.sources}
            review = observation.review
            if not all(k in supplied and supplied[k].ready_at(now) for k in plan.required_sources) or not all(
                e.ready_at(now) for e in observation.sources
            ):
                reason, coverage = "REQUIRED_CONTEXT_UNAVAILABLE", "UNAVAILABLE"
            elif plan.policy.require_review and review is None:
                reason, coverage = "REVIEW_MISSING_DEFER", "UNAVAILABLE"
            elif plan.policy.require_review and (
                review.scenario_id != plan.scenario_id
                or review.side is not plan.template.side
                or review.context_sha256 != observation.context_sha256
                or review.completion.available_at(observation.input_ready_history_ms, plan.policy) != now
            ):
                reason, coverage = "REVIEW_IDENTITY_OR_DUAL_CLOCK_CONFLICT", "UNAVAILABLE"
            elif plan.policy.require_review and (
                review.completion.attempt.status != "COMPLETE" or review.completion.attempt.cost_usd is None
            ):
                reason, coverage = "REVIEW_MODEL_OR_EXPENSE_UNAVAILABLE", "UNAVAILABLE"
            elif plan.policy.require_review and review.completion.decision != "ALLOW":
                reason = "REVIEW_" + review.completion.decision
            else:
                candidate, reason, coverage = _entry(plan, observation)
        else:
            state, reason = "WAITING_TRIGGER", "NO_CLOSED_PRICE_CONFIRMATION"
        results.append(
            ArchiveHypothesisEvaluationV3(
                plan.scenario_id, identity, prior.sha256, state, reason, coverage, now, candidate
            )
        )
        seen[bar.open_time_ms] = identity
        expected_open, last_clock = bar.open_time_ms + MINUTE, now
    return tuple(results)


@dataclass(frozen=True)
class ArchiveProducerCheckpointV3:
    plan_sha256: str
    sequence: int
    head_sha256: str

    def __post_init__(self):
        _sha(self.plan_sha256)
        _sha(self.head_sha256)
        if type(self.sequence) is not int or not 0 <= self.sequence <= MAX_OBSERVATIONS:
            raise ValueError("bounded independent archive producer checkpoint required")


@dataclass(frozen=True)
class ArchiveProducerReceiptV3:
    sequence: int
    previous_head_sha256: str
    head_sha256: str
    observation_sha256: str
    evaluation: ArchiveHypothesisEvaluationV3


@dataclass(frozen=True)
class ArchiveProducerSnapshotV3:
    plan: ArchiveHypothesisPlanV3
    implementation_sha256: str
    observations: tuple[ArchiveHypothesisObservationV3, ...]
    receipts: tuple[ArchiveProducerReceiptV3, ...]
    checkpoint: ArchiveProducerCheckpointV3


class ArchiveHypothesisProducerV3:
    """Single-parent bounded pure producer. Persistence/ownership is external.

    Full originals and receipts can be saved atomically by a future separate
    store. Restore requires an independent exact checkpoint, never latest.
    """

    def __init__(self, plan):
        _recheck(plan, ArchiveHypothesisPlanV3)
        self.plan, self._plan_hash, self._implementation_hash = plan, plan.scenario_id, _implementation()
        self._observations, self._receipts = (), ()
        self._head = digest(
            {
                "schema": SCHEMA,
                "plan": self._plan_hash,
                "implementation": self._implementation_hash,
                "genesis": True,
            }
        )

    def checkpoint(self):
        return ArchiveProducerCheckpointV3(self._plan_hash, len(self._receipts), self._head)

    def append(self, observation, *, expected_checkpoint):
        if self.plan.scenario_id != self._plan_hash or _implementation() != self._implementation_hash:
            raise ValueError("sealed producer source/parent changed")
        _recheck(expected_checkpoint, ArchiveProducerCheckpointV3)
        _recheck(observation, ArchiveHypothesisObservationV3)
        if expected_checkpoint != self.checkpoint():
            raise ValueError("independent archive producer head fence mismatch")
        for existing, receipt in zip(self._observations, self._receipts, strict=True):
            if existing.candle.open_time_ms == observation.candle.open_time_ms:
                if existing != observation:
                    raise ValueError("conflicting exact original redelivery")
                return receipt
        observations = (*self._observations, observation)
        evaluation = evaluate_archive_hypothesis_v3(self.plan, observations)[-1]
        sequence = len(observations)
        head = digest(
            {
                "schema": SCHEMA,
                "sequence": sequence,
                "previous_head": self._head,
                "observation": observation.observation_id,
                "evaluation": evaluation.sha256,
            }
        )
        receipt = ArchiveProducerReceiptV3(sequence, self._head, head, observation.observation_id, evaluation)
        snapshot = ArchiveProducerSnapshotV3(
            self.plan,
            self._implementation_hash,
            observations,
            (*self._receipts, receipt),
            ArchiveProducerCheckpointV3(self._plan_hash, sequence, head),
        )
        digest(snapshot)  # preflight complete state bytes before any mutation
        self._observations, self._receipts, self._head = observations, snapshot.receipts, head
        return receipt

    def snapshot(self):
        return ArchiveProducerSnapshotV3(
            self.plan, self._implementation_hash, self._observations, self._receipts, self.checkpoint()
        )

    @classmethod
    def restore(cls, snapshot, *, expected_checkpoint):
        _recheck(expected_checkpoint, ArchiveProducerCheckpointV3)
        if type(snapshot) is not ArchiveProducerSnapshotV3 or snapshot.checkpoint != expected_checkpoint:
            raise ValueError("independently retained exact snapshot/checkpoint required")
        if (
            type(snapshot.observations) is not tuple
            or type(snapshot.receipts) is not tuple
            or len(snapshot.observations) != len(snapshot.receipts)
        ):
            raise ValueError("complete immutable original producer prefix required")
        producer = cls(snapshot.plan)
        if snapshot.implementation_sha256 != producer._implementation_hash:
            raise ValueError("producer implementation differs")
        for observation, receipt in zip(snapshot.observations, snapshot.receipts, strict=True):
            if type(receipt) is not ArchiveProducerReceiptV3:
                raise ValueError("exact separate archive producer receipt required")
            if producer.append(observation, expected_checkpoint=producer.checkpoint()) != receipt:
                raise ValueError("original producer chain/evaluation tampered")
        if producer.checkpoint() != expected_checkpoint:
            raise ValueError("producer rollback/truncation/head mismatch")
        return producer
