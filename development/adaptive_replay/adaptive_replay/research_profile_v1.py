"""One opt-in preparation profile: no dispatcher, campaign or trading authority.

The adaptive generator and ATR mapper are unchanged. The contextual epoch latch
is a NEW, bounded research hypothesis, not an already-qualified native pattern.
Retained pure state proves consistency within one declared session, not durable
global exactly-once, authentic inputs or compatibility with the V3 economist.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from kairos_strategy.adaptive.config import STRATEGY_ID
from kairos_strategy.adaptive.logic import AdaptiveDecision, evaluate_adaptive
from kairos_strategy.adaptive.provenance import adaptive_source_identity
from kairos_strategy.candles import Candle
from kairos_strategy.models import SleeveIntent
from kairos_strategy.provenance import candle_payload
from kairos_strategy.timeframes import aggregate

from .complex_strategy import (
    HISTORY_BARS,
    MAPPER_ID,
    MAPPER_POLICY,
    _history,
    crash_defense,
    map_context_proposal,
)
from .historical_context import _clock, _name, _sha, digest
from .historical_replay import _validate_candidate
from .hypothesis_v3 import CreationAssessment, HypothesisPlan, HypothesisPolicy, creation_input_sha256
from .inputs import UNIVERSE
from .scenarios import CAPABILITIES, MINUTE, ScenarioEvidence, _evidence

PROFILE_ID = "adaptive-context-epochs.research.v1"
PERIOD_MS = 5 * MINUTE
HYPOTHESIS_LIFETIME_MS = 15 * MINUTE
MAXIMUM_QUOTE_AGE_MS = 2_000
MAX_SESSION_MS = 5 * 86_400_000
ADAPTIVE_CODE_SHA256 = "836391ab708d4dc9bd4957c68f00724683569b7d5584debb1c368016d57ff0d5"
ADAPTIVE_CONFIG_SHA256 = "51781e00bee3664f260ff826c821234073b7a40deb1b7239e39f517be885901b"
COMBINED_ID = "V3_BOTH_ORIGINS_REVIEW_CONFLICT_ABSTAIN_TECHNICAL_FIRST_NO_LATE_ARBITRATION"
ARM_ORIGINS = {
    "strategy_only": {"TECHNICAL"},
    "context_review": {"TECHNICAL"},
    "independent_proposals": {"CONTEXT_PROPOSAL"},
    "combined": {"TECHNICAL", "CONTEXT_PROPOSAL"},
}
REVIEW_ARMS = {"context_review", "independent_proposals", "combined"}


def profile_definition() -> dict:
    """Explicit candidate choices, never production defaults or launch rights."""
    return {
        "id": PROFILE_ID,
        "classification": "RESEARCH_PREPARATION_ONLY",
        "technical_family": STRATEGY_ID,
        "adaptive_code_sha256": ADAPTIVE_CODE_SHA256,
        "adaptive_config_sha256": ADAPTIVE_CONFIG_SHA256,
        "preparation_source_files": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in (
                "research_profile_v1.py",
                "complex_strategy.py",
                "hypothesis_v3.py",
                "historical_context.py",
                "historical_replay.py",
                "scenarios.py",
            )
        },
        "context_geometry": dict(MAPPER_POLICY),
        "capabilities": {k: sorted(s.value for s in v) for k, v in CAPABILITIES.items()},
        "decision_period_ms": PERIOD_MS,
        "hypothesis_lifetime_ms": HYPOTHESIS_LIFETIME_MS,
        "maximum_quote_age_ms": MAXIMUM_QUOTE_AGE_MS,
        "creation_clock": "ACTUAL_V3_BEFORE_FIRST_POST_ANCHOR_MINUTE_CLOSE",
        "reset": "FROZEN_MEAN_OR_RANGE_CENTER_THEN_DISTINCT_LATER_PRICE_EVENT",
        "initial_epoch": "ONE_SYMBOL_LEVEL_FIRST_DECLARED_SLOT_BOTH_RANGE_SIDES_CONSUMED",
        "consideration": "CONSUME_ON_ELIGIBLE_OR_NO_CALL_NO_RETRY_AFTER_NONE_OR_FAILURE",
        "regime_change_or_price_gap": "SYMBOL_TERMINAL_FOR_DECLARED_SESSION",
        "planning_order": "CUT_THEN_LEXICAL_SYMBOL",
        "entry_order": "ACTUAL_ISSUE_THEN_LEXICAL_SYMBOL_THEN_ORIGIN_CUT_THEN_PARENT",
        "combined_reference": COMBINED_ID,
        "arm_origins": {arm: sorted(origins) for arm, origins in ARM_ORIGINS.items()},
        "review_arms": sorted(REVIEW_ARMS),
        "combined_integration": "NOT_SUPPLIED_SPARSE_NO_CALL_AND_PROPOSAL_REVIEW_REQUIRE_NEW_ADMISSION",
        "risk_per_trade": "0.0025_UNCHANGED_DOWNSTREAM_NOT_A_NEW_ADMISSION",
        "aggregate_open_risk": "0.01_UNCHANGED_DOWNSTREAM_NOT_A_NEW_ADMISSION",
        "daily_trade_quota": None,
        "provider_dispatch": False,
        "campaign_enrollment": False,
        "trading_authority": False,
    }


@dataclass(frozen=True)
class ResearchProfile:
    """Caller-declared bounded session; a SHA is not proof of preregistration."""

    declared_ms: int
    start_ms: int
    end_ms: int
    source_set_sha256: str
    model_config_sha256: str
    quote_source_id: str
    required_sources: tuple[tuple[str, str], ...]
    evidence_kind: str

    def __post_init__(self) -> None:
        for clock in (self.declared_ms, self.start_ms, self.end_ms):
            _clock(clock)
        for value in (self.source_set_sha256, self.model_config_sha256):
            _sha(value)
        _name(self.quote_source_id)
        if (
            not self.declared_ms <= self.start_ms < self.end_ms
            or self.start_ms < HISTORY_BARS * MINUTE
            or self.start_ms % PERIOD_MS
            or self.end_ms % PERIOD_MS
            or self.end_ms - self.start_ms > MAX_SESSION_MS
            or self.evidence_kind not in {"TEST_FIXTURE", "CALLER_ATTESTED_POINT_IN_TIME"}
            or type(self.required_sources) is not tuple
            or len(self.required_sources) != 3
            or any(
                type(row) is not tuple or len(row) != 2 or any(type(v) is not str for v in row)
                for row in self.required_sources
            )
            or {row[0] for row in self.required_sources} != {"MARKET", "NEWS", "MACRO"}
            or tuple(sorted(set(self.required_sources))) != self.required_sources
        ):
            raise ValueError("exact predeclared session and one explicit source of each kind required")
        for _, source_id in self.required_sources:
            _name(source_id)
        if self.quote_source_id in {source_id for _, source_id in self.required_sources}:
            raise ValueError("dedicated quote source cannot impersonate context")

    @property
    def sha256(self) -> str:
        return digest({"definition": profile_definition(), "session": asdict(self)})

    def hypothesis_policy(self, *, arm_id: str) -> HypothesisPolicy:
        if arm_id not in ARM_ORIGINS:
            raise ValueError("exact predefined research arm required")
        return HypothesisPolicy(
            self.declared_ms,
            HYPOTHESIS_LIFETIME_MS,
            self.quote_source_id,
            MAXIMUM_QUOTE_AGE_MS,
            self.evidence_kind,
            arm_id in REVIEW_ARMS,
        )


@dataclass(frozen=True)
class PriceCell:
    cut_ms: int
    observed_ms: int
    symbol: str
    rows: tuple[Candle, ...] | None
    sources: tuple[ScenarioEvidence, ...]
    budget_state: str

    def __post_init__(self) -> None:
        _clock(self.cut_ms)
        _clock(self.observed_ms)
        if (
            self.symbol not in UNIVERSE
            or self.cut_ms % PERIOD_MS
            or self.observed_ms < self.cut_ms
            or self.budget_state not in {"AVAILABLE", "BLOCKED", "UNKNOWN"}
        ):
            raise ValueError("exact five-minute cell, actual later observation and budget state required")
        _evidence(self.sources, self.symbol)
        if self.rows is not None:
            if type(self.rows) is not tuple or len(self.rows) != HISTORY_BARS:
                raise ValueError("exact immutable rolling 54-hour history required")
            _history(self.rows, self.cut_ms, self.cut_ms - HISTORY_BARS * MINUTE)
            if self.rows[-1].symbol != self.symbol:
                raise ValueError("cell and candle symbol conflict")


@dataclass(frozen=True)
class Geometry:
    family: str
    frozen_before_ms: int
    lower: float
    upper: float

    def __post_init__(self) -> None:
        _clock(self.frozen_before_ms)
        if (
            self.family not in {"CONTEXT_FROZEN_MEAN_RECLAIM", "CONTEXT_FROZEN_RANGE_EXCURSION"}
            or any(
                type(v) not in {int, float} or not math.isfinite(v) or v <= 0
                for v in (self.lower, self.upper)
            )
            or self.lower > self.upper
            or (self.family == "CONTEXT_FROZEN_MEAN_RECLAIM" and self.lower != self.upper)
            or (self.family == "CONTEXT_FROZEN_RANGE_EXCURSION" and self.lower == self.upper)
        ):
            raise ValueError("exact finite contextual reset geometry required")


@dataclass(frozen=True)
class SymbolLatch:
    symbol: str
    regime: str | None = None
    geometry: Geometry | None = None
    consumed_observed_ms: int | None = None
    reset_cut_ms: int | None = None
    overlap_sha256: str | None = None
    terminal: str | None = None

    def __post_init__(self) -> None:
        if self.symbol not in UNIVERSE or (self.regime is not None and self.regime not in CAPABILITIES):
            raise ValueError("exact symbol and original latch capability required")
        if self.geometry is not None:
            if type(self.geometry) is not Geometry:
                raise ValueError("typed frozen geometry required")
            self.geometry.__post_init__()
            if self.regime is None or self.consumed_observed_ms is None:
                raise ValueError("initialized geometry must retain original regime and consumption clock")
        for clock in (self.consumed_observed_ms, self.reset_cut_ms):
            if clock is not None:
                _clock(clock)
        if self.reset_cut_ms is not None and (
            self.geometry is None
            or self.reset_cut_ms % PERIOD_MS
            or self.reset_cut_ms - 1 <= self.consumed_observed_ms
        ):
            raise ValueError("reset must postdate actual consumption on a completed later slot")
        if self.overlap_sha256 is not None:
            _sha(self.overlap_sha256)
        if self.terminal is not None:
            _name(self.terminal)


@dataclass(frozen=True)
class SessionState:
    profile_sha256: str
    last_cut_ms: int
    symbols: tuple[SymbolLatch, ...]
    previous_head_sha256: str
    receipts_sha256: str
    head_sha256: str

    def __post_init__(self) -> None:
        for value in (self.profile_sha256, self.previous_head_sha256, self.receipts_sha256, self.head_sha256):
            _sha(value)
        _clock(self.last_cut_ms)
        if type(self.symbols) is not tuple or any(type(latch) is not SymbolLatch for latch in self.symbols):
            raise ValueError("immutable typed retained symbol latches required")
        for latch in self.symbols:
            latch.__post_init__()
        if self.head_sha256 != _state_head(
            self.profile_sha256,
            self.last_cut_ms,
            self.symbols,
            self.previous_head_sha256,
            self.receipts_sha256,
        ):
            raise ValueError("retained state changed under its checkpoint hash")


def _state_head(profile_sha256, last_cut_ms, symbols, previous_head_sha256, receipts_sha256):
    return digest(
        {
            "schema": "kairos.research.profile-preparation-state.v1",
            "profile": profile_sha256,
            "cut": last_cut_ms,
            "latches": [asdict(latch) for latch in symbols],
            "previous": previous_head_sha256,
            "receipts": receipts_sha256,
        }
    )


def _state(profile_sha256, cut, symbols, previous, receipts):
    return SessionState(
        profile_sha256,
        cut,
        symbols,
        previous,
        receipts,
        _state_head(profile_sha256, cut, symbols, previous, receipts),
    )


@dataclass(frozen=True)
class SlotPreparation:
    profile_sha256: str
    cell: PriceCell
    technical: AdaptiveDecision | None
    regime: str | None
    price_state: str
    context_state: str
    reason: str
    allowed_directions: tuple[str, ...]
    epoch_sha256: str | None
    context_sha256: str
    creation_input_sha256: str | None

    @property
    def sha256(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class PreparedCut:
    checkpoint: SessionState
    slots: tuple[SlotPreparation, ...]

    def __post_init__(self) -> None:
        if type(self.checkpoint) is not SessionState or type(self.slots) is not tuple:
            raise ValueError("typed retained checkpoint and immutable preparation receipts required")
        self.checkpoint.__post_init__()
        if (
            len(self.slots) != len(UNIVERSE)
            or any(type(slot) is not SlotPreparation for slot in self.slots)
            or tuple(slot.cell.symbol for slot in self.slots) != tuple(sorted(UNIVERSE))
            or any(
                slot.profile_sha256 != self.checkpoint.profile_sha256
                or slot.cell.cut_ms != self.checkpoint.last_cut_ms
                for slot in self.slots
            )
            or digest([slot.sha256 for slot in self.slots]) != self.checkpoint.receipts_sha256
        ):
            raise ValueError("preparation receipts changed under retained checkpoint")


@dataclass(frozen=True)
class CreationOutcome:
    """One original caller-retained outcome; NONE/failure/unknown cannot be retried."""

    status: str
    original_sha256: str
    actual_created_ms: int
    assessment: CreationAssessment | None = None

    def __post_init__(self) -> None:
        _sha(self.original_sha256)
        _clock(self.actual_created_ms)
        if self.status not in {"NATIVE", "DIRECTION", "NONE", "FAILED", "UNKNOWN"}:
            raise ValueError("explicit one-shot context outcome required")
        if self.status == "DIRECTION":
            if type(self.assessment) is not CreationAssessment:
                raise ValueError("directional outcome requires the original actual assessment")
            self.assessment.__post_init__()
            if self.original_sha256 != self.assessment.response_sha256:
                raise ValueError("directional outcome must bind the original provider response")
            if self.assessment.actual_captured_ms > self.actual_created_ms:
                raise ValueError("outcome creation cannot predate actual completion/capture")
        elif self.assessment is not None:
            raise ValueError("no-result outcome cannot masquerade as a directional assessment")


@dataclass(frozen=True)
class CreationBinding:
    key: str
    original_sha256: str
    slot_sha256: str
    outcome_sha256: str


@dataclass(frozen=True)
class MaterializationState:
    profile_sha256: str
    bindings: tuple[CreationBinding, ...]
    head_sha256: str

    def __post_init__(self) -> None:
        _sha(self.profile_sha256)
        _sha(self.head_sha256)
        if (
            type(self.bindings) is not tuple
            or len(self.bindings) > 2 * len(UNIVERSE) * MAX_SESSION_MS // PERIOD_MS
            or any(type(binding) is not CreationBinding for binding in self.bindings)
            or tuple(sorted({binding.key for binding in self.bindings}))
            != tuple(binding.key for binding in self.bindings)
        ):
            raise ValueError("bounded canonical immutable creation bindings required")
        for binding in self.bindings:
            for value in asdict(binding).values():
                _sha(value)
        if self.head_sha256 != digest(
            {"profile": self.profile_sha256, "bindings": [asdict(binding) for binding in self.bindings]}
        ):
            raise ValueError("creation bindings changed under retained checkpoint")


def initial_materializations(profile: ResearchProfile) -> MaterializationState:
    _recheck_profile(profile)
    return _materializations(profile.sha256, ())


def _materializations(profile_sha256, bindings):
    return MaterializationState(
        profile_sha256,
        bindings,
        digest({"profile": profile_sha256, "bindings": [asdict(binding) for binding in bindings]}),
    )


def initial_state(profile: ResearchProfile) -> SessionState:
    _recheck_profile(profile)
    return _state(
        profile.sha256,
        profile.start_ms - PERIOD_MS,
        tuple(SymbolLatch(symbol) for symbol in UNIVERSE),
        "0" * 64,
        digest([]),
    )


def _recheck_profile(profile: ResearchProfile) -> None:
    if type(profile) is not ResearchProfile:
        raise ValueError("typed research preparation profile required")
    ResearchProfile(**asdict(profile))
    identity = adaptive_source_identity()
    if (
        identity.strategy_code_sha256 != ADAPTIVE_CODE_SHA256
        or identity.config_sha256 != ADAPTIVE_CONFIG_SHA256
    ):
        raise ValueError("unchanged exact adaptive source/config identity required")


def _geometry(rows: tuple[Candle, ...], regime: str) -> Geometry:
    # The latest 5m event is never used to establish its own new reset bounds.
    before = rows[-1].close_time_ms + 1 - PERIOD_MS
    prior = [row for row in aggregate(list(rows), "15m") if row.close_time_ms < before]
    if regime in {"BULL", "BEAR"}:
        if len(prior) < 20:
            raise ValueError("complete pre-event finite mean required")
        level = math.fsum(row.close for row in prior[-20:]) / 20
        geometry = Geometry("CONTEXT_FROZEN_MEAN_RECLAIM", before, level, level)
    else:
        if regime != "RANGE" or len(prior) < 16:
            raise ValueError("complete pre-event range required")
        lower = min(row.low for row in prior[-16:])
        upper = max(row.high for row in prior[-16:])
        if lower >= upper:
            raise ValueError("positive frozen range width required")
        geometry = Geometry("CONTEXT_FROZEN_RANGE_EXCURSION", before, lower, upper)
    if not all(math.isfinite(v) and v > 0 for v in (geometry.lower, geometry.upper)):
        raise ValueError("positive finite frozen reset geometry required")
    return geometry


def _reset(latch: SymbolLatch, price: float) -> bool:
    g = latch.geometry
    assert g is not None
    if latch.regime == "BULL":
        return price <= g.lower
    if latch.regime == "BEAR":
        return price >= g.upper
    width = g.upper - g.lower
    return g.lower + width * 0.25 <= price <= g.upper - width * 0.25


def _event_directions(latch: SymbolLatch, price: float) -> tuple[str, ...]:
    g = latch.geometry
    assert g is not None
    if latch.regime == "BULL":
        return ("LONG",) if price > g.lower else ()
    if latch.regime == "BEAR":
        return ("SHORT",) if price < g.upper else ()
    width = g.upper - g.lower
    if g.lower <= price < g.lower + width * 0.25:
        return ("LONG",)
    if g.upper - width * 0.25 < price <= g.upper:
        return ("SHORT",)
    return ()


def _sources_ready(profile: ResearchProfile, cell: PriceCell) -> bool:
    supplied = {(source.kind, source.source_id): source for source in cell.sources}
    return (
        all(key in supplied and supplied[key].ready_at(cell.observed_ms) for key in profile.required_sources)
        and all(source.ready_at(cell.observed_ms) for source in cell.sources)
        and (
            cell.rows is not None
            and any(
                source.kind == "MARKET"
                and (source.kind, source.source_id) in profile.required_sources
                and source.event_ms == cell.rows[-1].close_time_ms
                and source.payload_sha256 == digest(candle_payload(cell.rows[-1]))
                for source in cell.sources
            )
        )
    )


def _step_symbol(profile, latch, cell):
    decision, regime, directions, epoch = None, latch.regime, (), None
    reason, terminal = "WAITING_STRUCTURAL_RESET", latch.terminal
    context = digest({"profile": profile.sha256, "cell": asdict(cell)})
    if terminal is not None:
        reason = terminal
    elif cell.rows is None or cell.observed_ms >= cell.cut_ms + MINUTE:
        reason = terminal = "PRICE_UNAVAILABLE_OR_LATE_TERMINAL"
    else:
        overlap = digest([candle_payload(row) for row in cell.rows[: HISTORY_BARS - 5]])
        if latch.overlap_sha256 is not None and overlap != latch.overlap_sha256:
            reason = terminal = "PRICE_OVERLAP_INTEGRITY_CONFLICT"
        else:
            decision = evaluate_adaptive(cell.rows)
            regime = decision.regime.value
            if decision.status not in {"INTENT", "NO_INTENT"}:
                reason = terminal = "NATIVE_PRICE_UNAVAILABLE_TERMINAL"
            elif regime not in CAPABILITIES or crash_defense(decision, cell.rows) != "NORMAL":
                reason = terminal = "UNSUPPORTED_REGIME_OR_DEFENSE_TERMINAL"
            elif latch.regime is not None and regime != latch.regime:
                reason = terminal = "REGIME_CHANGED_TERMINAL"
            else:
                if latch.geometry is None:
                    # Only the predeclared first slot can seed a symbol.
                    if cell.cut_ms != profile.start_ms:
                        raise ValueError("late or restarted initial epoch cannot be seeded")
                    latch = replace(
                        latch,
                        regime=regime,
                        geometry=_geometry(cell.rows, regime),
                        consumed_observed_ms=cell.observed_ms,
                    )
                    directions = tuple(sorted(side.value for side in CAPABILITIES[regime]))
                    reason = "INITIAL_DECLARED_EPOCH"
                elif latch.reset_cut_ms is None:
                    if cell.cut_ms - 1 > latch.consumed_observed_ms and _reset(latch, cell.rows[-1].close):
                        latch = replace(latch, reset_cut_ms=cell.cut_ms)
                        reason = "RESET_WITNESS_WAIT_DISTINCT_LATER_EVENT"
                else:
                    directions = _event_directions(latch, cell.rows[-1].close)
                    if directions:
                        reason = "FROZEN_GEOMETRY_NEW_PRICE_EVENT"
                if directions:
                    epoch = digest(
                        {
                            "profile": profile.sha256,
                            "symbol": cell.symbol,
                            "geometry": asdict(latch.geometry),
                            "reset_cut_ms": latch.reset_cut_ms,
                            "event_cut_ms": cell.cut_ms,
                            "directions": directions,
                        }
                    )
                    # ALL admitted branches are consumed on consideration, not response.
                    latch = replace(
                        latch,
                        geometry=_geometry(cell.rows, regime),
                        consumed_observed_ms=cell.observed_ms,
                        reset_cut_ms=None,
                    )
                    if not _sources_ready(profile, cell):
                        reason = "CONTEXT_UNAVAILABLE_EPOCH_CONSUMED_NO_CALL"
                    elif cell.budget_state != "AVAILABLE":
                        reason = "BUDGET_UNAVAILABLE_EPOCH_CONSUMED_NO_CALL"
                latch = replace(
                    latch,
                    overlap_sha256=digest([candle_payload(row) for row in cell.rows[5:]]),
                )
    ready = epoch is not None and _sources_ready(profile, cell) and cell.budget_state == "AVAILABLE"
    latch = replace(latch, terminal=terminal)
    creation_input = (
        creation_input_sha256(profile.source_set_sha256, context, cell.rows[-1], cell.sources)
        if ready
        else None
    )
    return latch, SlotPreparation(
        profile.sha256,
        cell,
        decision,
        regime,
        "UNAVAILABLE" if terminal is not None else "AVAILABLE",
        "ELIGIBLE" if ready else "NO_CALL",
        reason,
        directions,
        epoch,
        context,
        creation_input,
    )


def prepare_next_cut(
    profile: ResearchProfile, state: SessionState, cells: tuple[PriceCell, ...]
) -> tuple[SessionState, tuple[SlotPreparation, ...]]:
    """Complete five-symbol denominator; output is permission to prepare, not call."""
    _recheck_profile(profile)
    if type(state) is not SessionState or type(cells) is not tuple:
        raise ValueError("typed retained session and immutable full cut required")
    state.__post_init__()
    _clock(state.last_cut_ms)
    if any(type(latch) is not SymbolLatch for latch in state.symbols):
        raise ValueError("typed retained symbol latches required")
    for latch in state.symbols:
        latch.__post_init__()
        if latch.geometry is not None and (
            latch.geometry.frozen_before_ms > state.last_cut_ms
            or latch.consumed_observed_ms >= state.last_cut_ms + MINUTE
            or (latch.reset_cut_ms is not None and latch.reset_cut_ms > state.last_cut_ms)
        ):
            raise ValueError("latch contains a future geometry or witness")
    if (
        state.profile_sha256 != profile.sha256
        or state.last_cut_ms < profile.start_ms - PERIOD_MS
        or state.last_cut_ms % PERIOD_MS
        or tuple(latch.symbol for latch in state.symbols) != UNIVERSE
        or len(cells) != len(UNIVERSE)
        or any(type(cell) is not PriceCell for cell in cells)
        or {cell.symbol for cell in cells} != set(UNIVERSE)
    ):
        raise ValueError("retained exact session state and full five-symbol cut required")
    if state.last_cut_ms > profile.start_ms - PERIOD_MS and any(
        latch.geometry is None and latch.terminal is None for latch in state.symbols
    ):
        raise ValueError("lost latch cannot be recreated after the initial declared slot")
    _sha(state.head_sha256)
    cut = state.last_cut_ms + PERIOD_MS
    if cut >= profile.end_ms:
        raise ValueError("declared preparation horizon exhausted")
    by_symbol = {}
    for cell in cells:
        if type(cell) is not PriceCell:
            raise ValueError("typed price cell required")
        cell.__post_init__()
        if cell.cut_ms != cut:
            raise ValueError("contiguous original cuts only; no gap, catch-up or backdating")
        by_symbol[cell.symbol] = cell
    new_latches, receipts = [], []
    for latch in state.symbols:
        new_latch, receipt = _step_symbol(profile, latch, by_symbol[latch.symbol])
        new_latches.append(new_latch)
        receipts.append(receipt)
    ordered = tuple(sorted(receipts, key=lambda receipt: (receipt.cell.cut_ms, receipt.cell.symbol)))
    receipts_hash = digest([receipt.sha256 for receipt in ordered])
    return _state(profile.sha256, cut, tuple(new_latches), state.head_sha256, receipts_hash), ordered


def _prepare_hypothesis(
    profile: ResearchProfile,
    slot: SlotPreparation,
    *,
    arm_id: str,
    origin: str,
    actual_created_ms: int,
    assessment: CreationAssessment | None = None,
) -> HypothesisPlan | None:
    """Wrap exact native evidence with V3 actual clocks; no late-frame rescue."""
    _recheck_profile(profile)
    _clock(actual_created_ms)
    if (
        type(slot) is not SlotPreparation
        or slot.profile_sha256 != profile.sha256
        or slot.cell.rows is None
        or slot.price_state != "AVAILABLE"
        or slot.regime not in CAPABILITIES
        or actual_created_ms < slot.cell.observed_ms
        or actual_created_ms >= slot.cell.cut_ms + MINUTE
        or origin not in {"TECHNICAL", "CONTEXT_PROPOSAL"}
        or arm_id not in ARM_ORIGINS
        or origin not in ARM_ORIGINS[arm_id]
    ):
        raise ValueError("profile-bound supported slot and actual creation before first minute required")
    slot.cell.__post_init__()
    native = evaluate_adaptive(slot.cell.rows)
    expected_context = digest({"profile": profile.sha256, "cell": asdict(slot.cell)})
    if (
        native != slot.technical
        or native.regime.value != slot.regime
        or crash_defense(native, slot.cell.rows) != "NORMAL"
        or expected_context != slot.context_sha256
        or not profile.start_ms <= slot.cell.cut_ms < profile.end_ms
    ):
        raise ValueError("slot native outcome, defense or causal input bytes changed")
    if origin == "TECHNICAL":
        if assessment is not None:
            raise ValueError("technical origin cannot adopt a model assessment")
        candidate = None if slot.technical is None else slot.technical.intent
        if candidate is None:
            return None
        if candidate.sleeve_id != STRATEGY_ID:
            raise ValueError("only the unchanged adaptive technical family is admitted")
        sources = tuple(source for source in slot.cell.sources if source.kind == "MARKET")
        required = tuple(key for key in profile.required_sources if key[0] == "MARKET")
    else:
        if slot.context_state != "ELIGIBLE" or type(assessment) is not CreationAssessment:
            raise ValueError("one eligible contextual epoch and actual assessment required")
        if (
            assessment.direction not in slot.allowed_directions
            or assessment.model_config_sha256 != profile.model_config_sha256
            or assessment.input_sha256 != slot.creation_input_sha256
            or assessment.evidence_kind != profile.evidence_kind
            or assessment.actual_requested_ms < slot.cell.observed_ms
            or assessment.actual_captured_ms > actual_created_ms
            or not all(source.ready_at(actual_created_ms) for source in slot.cell.sources)
        ):
            raise ValueError("context assessment direction/config/input/evidence/actual clock conflict")
        mapping = map_context_proposal(
            assessment.direction,
            slot.cell.rows,
            cut_ms=slot.cell.cut_ms,
            assessment_sha256=assessment.sha256,
        )
        candidate = mapping.candidate
        if candidate is None:
            return None
        if candidate.sleeve_id != MAPPER_ID:
            raise ValueError("context mapper cannot adopt a crash or technical parent")
        sources, required = slot.cell.sources, profile.required_sources
    return HypothesisPlan(
        candidate,
        origin,
        slot.regime,
        slot.cell.cut_ms,
        actual_created_ms,
        profile.source_set_sha256,
        slot.context_sha256,
        sources,
        slot.cell.rows[-1],
        required,
        profile.hypothesis_policy(arm_id=arm_id),
        assessment,
    )


def materialize_hypothesis(
    profile: ResearchProfile,
    prepared: PreparedCut,
    state: MaterializationState,
    *,
    symbol: str,
    arm_id: str,
    origin: str,
    outcome: CreationOutcome,
) -> tuple[MaterializationState, HypothesisPlan | None]:
    """Validated reducer receipt plus one original outcome, within retained fold.

    Equal redelivery returns the same plan. A different answer, direction, clock
    or no-result status under the same epoch fails; sharing ONE physical outcome
    across the predefined arms does not create another provider request.
    This is not a durable publisher, budget reservation or external-effect API.
    """
    _recheck_profile(profile)
    if type(prepared) is not PreparedCut or type(state) is not MaterializationState:
        raise ValueError("typed retained preparation and materialization checkpoints required")
    prepared.__post_init__()
    state.__post_init__()
    if (
        state.profile_sha256 != profile.sha256
        or prepared.checkpoint.profile_sha256 != profile.sha256
        or symbol not in UNIVERSE
        or arm_id not in ARM_ORIGINS
        or origin not in ARM_ORIGINS[arm_id]
        or type(outcome) is not CreationOutcome
    ):
        raise ValueError("profile/arm/origin/outcome binding conflict")
    outcome.__post_init__()
    slot = next(slot for slot in prepared.slots if slot.cell.symbol == symbol)
    if (
        slot.price_state != "AVAILABLE"
        or slot.cell.rows is None
        or outcome.actual_created_ms < slot.cell.observed_ms
    ):
        raise ValueError("unavailable slot or backdated original materialization")
    if origin == "CONTEXT_PROPOSAL":
        if slot.context_state != "ELIGIBLE" or slot.epoch_sha256 is None:
            raise ValueError("no contextual preparation epoch admitted for this slot")
        if outcome.status == "NATIVE":
            raise ValueError("context origin cannot impersonate a native evaluator")
        key = digest({"origin": origin, "epoch": slot.epoch_sha256})
    else:
        if slot.technical is None or slot.technical.intent is None:
            if outcome.status != "NONE":
                raise ValueError("quiet technical slot cannot manufacture a candidate")
        elif outcome.status != "NATIVE":
            raise ValueError("technical parent requires its exact original materialization")
        if outcome.assessment is not None:
            raise ValueError("technical origin cannot adopt a model assessment")
        if (
            outcome.original_sha256 != digest(asdict(slot.technical))
            or outcome.actual_created_ms != slot.cell.observed_ms
        ):
            raise ValueError("technical original outcome bytes or evaluation clock changed")
        key = digest({"origin": origin, "symbol": symbol, "cut": slot.cell.cut_ms})
    binding = CreationBinding(key, outcome.original_sha256, slot.sha256, digest(asdict(outcome)))
    existing = next((saved for saved in state.bindings if saved.key == key), None)
    if existing is not None and existing != binding:
        raise ValueError("one epoch cannot adopt a different outcome, direction or clock")
    if outcome.status not in {"DIRECTION", "NATIVE"}:
        plan = None
    else:
        plan = _prepare_hypothesis(
            profile,
            slot,
            arm_id=arm_id,
            origin=origin,
            actual_created_ms=outcome.actual_created_ms,
            assessment=outcome.assessment,
        )
    if existing is not None:
        return state, plan
    bindings = tuple(sorted((*state.bindings, binding), key=lambda item: item.key))
    return _materializations(profile.sha256, bindings), plan


def order_entry_batch(
    candidates: tuple[SleeveIntent, ...], *, actual_issue_ms: int
) -> tuple[SleeveIntent, ...]:
    """One already-issued batch only, no waiting/requote, selection or sizing."""
    _clock(actual_issue_ms)
    if type(candidates) is not tuple or len(candidates) > len(UNIVERSE):
        raise ValueError("bounded immutable candidate batch required")
    for candidate in candidates:
        _validate_candidate(candidate)
        if candidate.symbol not in UNIVERSE or candidate.entry_eligible_ts_ms != actual_issue_ms:
            raise ValueError("only same actual-issue candidates can share a batch")
        metadata = dict(candidate.metadata)
        cut = metadata.get("hypothesis_origin_cut_ms", "")
        if not cut.isdecimal() or str(int(cut)) != cut or int(cut) > actual_issue_ms:
            raise ValueError("exact original V3 cut required for entry ordering")
        _name(metadata.get("parent_intent_id", ""))
    if len({candidate.symbol for candidate in candidates}) != len(candidates):
        raise ValueError("one candidate per symbol after origin arbitration required")
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                actual_issue_ms,
                candidate.symbol,
                int(dict(candidate.metadata)["hypothesis_origin_cut_ms"]),
                dict(candidate.metadata)["parent_intent_id"],
            ),
        )
    )
