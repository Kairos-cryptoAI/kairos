"""One offline event-origin policy, not a provider/portfolio/production driver.

The old price-epoch profile and V3 economist are untouched. Retained folds prove
local consistency only: the caller must retain originals, authenticate sources,
reserve budgets and enforce independent Risk/account/venue/operator gates.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from kairos_strategy.adaptive.logic import AdaptiveDecision, evaluate_adaptive
from kairos_strategy.models import SleeveIntent
from kairos_strategy.provenance import candle_payload

from . import research_profile_v1 as control
from .catalyst_hypothesis_v1 import CatalystPlan, evaluate_hypothesis
from .complex_strategy import MAPPER_ID, crash_defense, map_context_proposal
from .historical_context import HistoricalVersion, _clock, _name, _sha, digest
from .hypothesis_v3 import HypothesisObservation, creation_input_sha256
from .inputs import UNIVERSE
from .scenarios import MINUTE

POLICY_ID = "adaptive-catalyst-whole-system.research.v1"
ARMS = tuple(sorted(control.ARM_ORIGINS))
CONTEXT_ARMS = ("combined", "independent_proposals")
PERIOD = control.PERIOD_MS
MAX_EVENTS = 2_000


@dataclass(frozen=True)
class CatalystPolicy:
    """Reuse explicit timing/source parameters, NOT the old epoch capability policy."""

    session: control.ResearchProfile

    def __post_init__(self):
        control._recheck_profile(self.session)

    @property
    def sha256(self):
        return digest(
            {
                "policy": POLICY_ID,
                "parameters": asdict(self.session),
                "source_files": {
                    name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                    for name in (
                        "catalyst_policy_v1.py",
                        "catalyst_hypothesis_v1.py",
                        "research_profile_v1.py",
                        "complex_strategy.py",
                        "hypothesis_v3.py",
                        "historical_context.py",
                        "scenarios.py",
                    )
                },
            }
        )


@dataclass(frozen=True)
class CatalystEvent:
    """Publisher-canonical economic event, not an LLM-assigned novelty score.

    One publisher event may contain several documents. Aliases across publishers
    need external resolution; hashes alone cannot discover semantic duplicates.
    Publication-only/reconstructed receive clocks never qualify here.
    """

    source_id: str
    event_id: str
    version: HistoricalVersion
    first_received_ms: int
    ttl_ms: int

    def __post_init__(self):
        _name(self.source_id)
        _name(self.event_id)
        _clock(self.first_received_ms)
        _clock(self.ttl_ms)
        if type(self.version) is not HistoricalVersion:
            raise ValueError("typed exact original event version required")
        self.version.__post_init__()
        if (
            self.ttl_ms == 0
            or self.version.source_name != self.source_id
            or self.version.proof_kind not in {"TEST_FIXTURE", "CONTEMPORANEOUS_LOCAL"}
            or not self.version.version_available_ms <= self.first_received_ms <= self.version.captured_ms
        ):
            raise ValueError("actual first receipt and local exact-version proof required")

    @property
    def due_ms(self):
        return ((self.version.captured_ms + PERIOD - 1) // PERIOD) * PERIOD

    @property
    def sha256(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class CatalystCell:
    price: control.PriceCell
    event_coverage: str
    events: tuple[CatalystEvent, ...] = ()
    active_arms: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.price) is not control.PriceCell:
            raise ValueError("typed original price cell required")
        self.price.__post_init__()
        if (
            self.event_coverage not in {"KNOWN", "UNKNOWN"}
            or type(self.events) is not tuple
            or len(self.events) > 32
            or any(type(e) is not CatalystEvent for e in self.events)
            or tuple(sorted(set(e.sha256 for e in self.events))) != tuple(e.sha256 for e in self.events)
            or type(self.active_arms) is not tuple
            or self.active_arms != tuple(sorted(set(self.active_arms)))
            or not set(self.active_arms) <= set(ARMS)
        ):
            raise ValueError("explicit coverage, canonical event batch and isolated active arms required")
        for event in self.events:
            event.__post_init__()
            if self.price.symbol not in event.version.symbols or event.due_ms > self.price.cut_ms:
                raise ValueError("event symbol conflict or future first eligible cut")


@dataclass(frozen=True)
class EventStamp:
    symbol: str
    source_id: str
    event_id: str
    document_id: str
    content_sha256: str


@dataclass(frozen=True)
class EventState:
    policy_sha256: str
    last_cut_ms: int
    stamps: tuple[EventStamp, ...]
    overlaps: tuple[tuple[str, str], ...]
    blocked_symbols: tuple[str, ...]
    previous_head: str
    head: str

    def __post_init__(self):
        _sha(self.policy_sha256)
        _clock(self.last_cut_ms)
        _sha(self.previous_head)
        if (
            type(self.stamps) is not tuple
            or len(self.stamps) > MAX_EVENTS
            or any(type(s) is not EventStamp for s in self.stamps)
            or self.stamps != tuple(sorted(set(self.stamps), key=lambda s: tuple(asdict(s).values())))
            or self.blocked_symbols != tuple(sorted(set(self.blocked_symbols)))
            or not set(self.blocked_symbols) <= set(UNIVERSE)
            or tuple(s for s, _ in self.overlaps) != tuple(sorted(UNIVERSE))
        ):
            raise ValueError("bounded retained canonical event state required")
        for stamp in self.stamps:
            if stamp.symbol not in UNIVERSE:
                raise ValueError("event stamp outside universe")
            for value in (stamp.source_id, stamp.event_id, stamp.document_id):
                _name(value)
            _sha(stamp.content_sha256)
        for _, value in self.overlaps:
            _sha(value)
        body = {key: value for key, value in asdict(self).items() if key != "head"}
        if self.head != digest(body):
            raise ValueError("retained event state changed")


def _state(policy, cut, stamps, overlaps, blocked, predecessor):
    body = dict(
        policy_sha256=policy.sha256,
        last_cut_ms=cut,
        stamps=tuple(sorted(set(stamps), key=lambda s: tuple(asdict(s).values()))),
        overlaps=tuple(sorted(overlaps)),
        blocked_symbols=tuple(sorted(blocked)),
        previous_head=predecessor,
    )
    return EventState(**body, head=digest({**body, "stamps": [asdict(s) for s in body["stamps"]]}))


def initial_state(policy: CatalystPolicy) -> EventState:
    policy.__post_init__()
    return _state(
        policy, policy.session.start_ms - PERIOD, (), ((s, "0" * 64) for s in UNIVERSE), (), "0" * 64
    )


@dataclass(frozen=True)
class CatalystSlot:
    policy_sha256: str
    cell: CatalystCell
    technical_state: str
    technical: AdaptiveDecision | None
    regime: str
    defense: str
    context_state: str
    reason: str
    context_sha256: str
    creation_input_sha256: str | None
    consumer_arms: tuple[str, ...]
    event_batch: tuple[str, ...]

    @property
    def sha256(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class PreparedCut:
    previous: EventState
    checkpoint: EventState
    slots: tuple[CatalystSlot, ...]
    sha256: str

    def __post_init__(self):
        self.previous.__post_init__()
        self.checkpoint.__post_init__()
        if (
            self.previous.head != self.checkpoint.previous_head
            or self.previous.last_cut_ms + PERIOD != self.checkpoint.last_cut_ms
            or self.previous.policy_sha256 != self.checkpoint.policy_sha256
            or type(self.slots) is not tuple
            or len(self.slots) != len(UNIVERSE)
            or any(type(s) is not CatalystSlot for s in self.slots)
            or tuple(s.cell.price.symbol for s in self.slots) != tuple(sorted(UNIVERSE))
            or any(
                s.policy_sha256 != self.checkpoint.policy_sha256
                or s.cell.price.cut_ms != self.checkpoint.last_cut_ms
                for s in self.slots
            )
            or self.sha256 != digest({"state": self.checkpoint.head, "slots": [s.sha256 for s in self.slots]})
        ):
            raise ValueError("original full-universe preparation receipts required")


def prepare_cut(policy: CatalystPolicy, state: EventState, cells: tuple[CatalystCell, ...]) -> PreparedCut:
    """Consume all new events once, even if no call can be made. No catch-up."""
    policy.__post_init__()
    state.__post_init__()
    session, cut = policy.session, state.last_cut_ms + PERIOD
    if (
        state.policy_sha256 != policy.sha256
        or not session.start_ms <= cut < session.end_ms
        or type(cells) is not tuple
        or len(cells) != len(UNIVERSE)
        or any(type(c) is not CatalystCell for c in cells)
        or tuple(c.price.symbol for c in cells) != tuple(sorted(UNIVERSE))
        or any(c.price.cut_ms != cut for c in cells)
    ):
        raise ValueError("contiguous full five-symbol original cut and retained policy required")
    stamps, overlaps, blocked, slots = list(state.stamps), [], set(state.blocked_symbols), []
    for cell in cells:
        cell.__post_init__()
        price, new_events, conflict = cell.price, [], False
        old_roots = {(s.source_id, s.event_id) for s in state.stamps if s.symbol == price.symbol}
        for event in cell.events:
            if (event.version.kind, event.source_id) not in session.required_sources or (
                session.evidence_kind != "TEST_FIXTURE" and event.version.proof_kind == "TEST_FIXTURE"
            ):
                raise ValueError("event source/proof outside declared source set")
            stamp = EventStamp(
                price.symbol,
                event.source_id,
                event.event_id,
                event.version.document_id,
                event.version.raw_content_sha256,
            )
            related = [s for s in stamps if s.symbol == stamp.symbol and s.source_id == stamp.source_id]
            same_document = [s for s in related if s.document_id == stamp.document_id]
            if any(s != stamp for s in same_document) or any(
                s.content_sha256 == stamp.content_sha256 and s.event_id != stamp.event_id for s in related
            ):
                conflict = True
            elif stamp not in stamps:
                # All documents of a root NEW at this cut belong to the batch.
                # Novelty is measured against pre-cut state, not this loop's appends.
                if (stamp.source_id, stamp.event_id) not in old_roots:
                    new_events.append(event)
                stamps.append(stamp)
        rows = price.rows
        overlap = "0" * 64 if rows is None else digest([candle_payload(r) for r in rows[5:]])
        overlaps.append((price.symbol, overlap))
        if rows is not None and state.last_cut_ms >= session.start_ms:
            if dict(state.overlaps)[price.symbol] != digest([candle_payload(r) for r in rows[:-5]]):
                conflict = True
        if conflict or rows is None:
            blocked.add(price.symbol)
        native = None if rows is None else evaluate_adaptive(rows)
        regime = "UNAVAILABLE" if native is None else native.regime.value
        defense = "SOURCE_UNAVAILABLE" if native is None else crash_defense(native, rows)
        technical_state = (
            "UNAVAILABLE"
            if native is None or native.status not in {"INTENT", "NO_INTENT"}
            else "QUIET"
            if native.intent is None
            else "PARENT"
        )
        consumers = tuple(a for a in CONTEXT_ARMS if a not in cell.active_arms)
        reason = "NEW_CANONICAL_EVENT_BATCH"
        if price.symbol in blocked:
            reason = "INTEGRITY_OR_PRICE_GAP_BLOCKED_SESSION"
        elif price.observed_ms >= cut + MINUTE:
            reason = "LATE_SLOT_NO_CATCH_UP"
        elif cell.event_coverage == "UNKNOWN":
            reason = "EVENT_COVERAGE_UNKNOWN"
        elif not control._sources_ready(session, price):
            reason = "CONTEXT_UNAVAILABLE"
        elif regime not in {"BULL", "BEAR", "RANGE"} or defense != "NORMAL":
            reason = "UNSUPPORTED_REGIME_OR_DEFENSE"
        elif not new_events:
            reason = "NO_NEW_EVENT"
        elif any(e.due_ms != cut or price.observed_ms - e.version.captured_ms > e.ttl_ms for e in new_events):
            reason = "MISSED_OR_STALE_EVENT_NO_CATCH_UP"
        elif not consumers:
            reason = "NO_CALL_ACTIVE_ALL_CONTEXT_ARMS"
        elif price.budget_state != "AVAILABLE":
            reason = "BUDGET_UNAVAILABLE_EVENT_CONSUMED"
        context = digest({"policy": policy.sha256, "cell": asdict(cell)})
        eligible = reason == "NEW_CANONICAL_EVENT_BATCH"
        creation = (
            None
            if not eligible
            else creation_input_sha256(session.source_set_sha256, context, rows[-1], price.sources)
        )
        slots.append(
            CatalystSlot(
                policy.sha256,
                cell,
                technical_state,
                native,
                regime,
                defense,
                "ELIGIBLE" if eligible else "NO_CALL",
                reason,
                context,
                creation,
                consumers if eligible else (),
                tuple(e.sha256 for e in new_events),
            )
        )
    next_state = _state(policy, cut, stamps, overlaps, blocked, state.head)
    slots = tuple(slots)
    return PreparedCut(
        state, next_state, slots, digest({"state": next_state.head, "slots": [s.sha256 for s in slots]})
    )


def _check_prepared(policy, prepared):
    if type(prepared) is not PreparedCut:
        raise ValueError("typed original preparation required")
    prepared.__post_init__()
    recomputed = prepare_cut(policy, prepared.previous, tuple(s.cell for s in prepared.slots))
    if recomputed != prepared:
        raise ValueError("preparation differs from original native/event reducer")


@dataclass(frozen=True)
class CreationRecord:
    slot_sha256: str
    origin: str
    outcome: control.CreationOutcome


@dataclass(frozen=True)
class CreationLedger:
    policy_sha256: str
    records: tuple[CreationRecord, ...] = ()

    def __post_init__(self):
        _sha(self.policy_sha256)
        if type(self.records) is not tuple or len(self.records) > 2 * len(UNIVERSE) * 1440:
            raise ValueError("bounded retained creation ledger required")
        keys = []
        for record in self.records:
            if type(record) is not CreationRecord or record.origin not in {"TECHNICAL", "CONTEXT_PROPOSAL"}:
                raise ValueError("typed original creation record required")
            _sha(record.slot_sha256)
            if type(record.outcome) is not control.CreationOutcome:
                raise ValueError("typed original outcome required")
            record.outcome.__post_init__()
            keys.append((record.slot_sha256, record.origin))
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate original creation record")

    @property
    def sha256(self):
        return digest(asdict(self))


def _plans(policy, slot, origin, outcome):
    session, cell = policy.session, slot.cell.price
    if outcome.actual_created_ms < cell.observed_ms:
        raise ValueError("backdated original outcome")
    if origin == "TECHNICAL":
        if (
            slot.technical_state != "PARENT"
            or outcome.status != "NATIVE"
            or (outcome.original_sha256 != digest(asdict(slot.technical)))
        ):
            raise ValueError("exact native original outcome required")
        candidate = slot.technical.intent
        sources = tuple(e for e in cell.sources if e.kind == "MARKET")
        required = tuple(k for k in session.required_sources if k[0] == "MARKET")
        arms = tuple(a for a in ARMS if origin in control.ARM_ORIGINS[a] and a not in slot.cell.active_arms)
    else:
        if slot.context_state != "ELIGIBLE" or outcome.status == "NATIVE":
            raise ValueError("one eligible event batch required")
        if outcome.status != "DIRECTION":
            return ()
        if any(
            outcome.actual_created_ms - event.version.captured_ms > event.ttl_ms
            for event in slot.cell.events
            if event.sha256 in slot.event_batch
        ):
            raise ValueError("event expired before actual proposal creation")
        assessment = outcome.assessment
        if (
            assessment.model_config_sha256 != session.model_config_sha256
            or assessment.evidence_kind != session.evidence_kind
            or assessment.input_sha256 != slot.creation_input_sha256
            or assessment.actual_requested_ms < cell.observed_ms
        ):
            raise ValueError("original proposal model/input/evidence/clock conflict")
        candidate = map_context_proposal(
            assessment.direction, cell.rows, cut_ms=cell.cut_ms, assessment_sha256=assessment.sha256
        ).candidate
        if candidate is None:
            return ()
        if candidate.sleeve_id != MAPPER_ID:
            raise ValueError("independent event cannot adopt a technical/crash parent")
        sources, required, arms = cell.sources, session.required_sources, slot.consumer_arms
    return tuple(
        (
            arm,
            CatalystPlan(
                template=candidate,
                origin=origin,
                regime=slot.regime,
                defense=slot.defense,
                origin_cut_ms=cell.cut_ms,
                created_ms=outcome.actual_created_ms,
                source_set_sha256=session.source_set_sha256,
                context_sha256=slot.context_sha256,
                creation_evidence=sources if arm == "strategy_only" else cell.sources,
                anchor=cell.rows[-1],
                required_sources=required if arm == "strategy_only" else session.required_sources,
                policy=session.hypothesis_policy(arm_id=arm),
                creation_assessment=outcome.assessment,
            ),
        )
        for arm in arms
    )


def materialize(policy, prepared, ledger, *, symbol, origin, outcome):
    """One original response shared across declared arms; no per-arm resampling."""
    policy.__post_init__()
    _check_prepared(policy, prepared)
    ledger.__post_init__()
    if (
        prepared.checkpoint.policy_sha256 != policy.sha256
        or ledger.policy_sha256 != policy.sha256
        or symbol not in UNIVERSE
        or origin not in {"TECHNICAL", "CONTEXT_PROPOSAL"}
        or type(outcome) is not control.CreationOutcome
    ):
        raise ValueError("retained policy/origin/outcome binding conflict")
    outcome.__post_init__()
    slot = next(s for s in prepared.slots if s.cell.price.symbol == symbol)
    if slot.cell.price.symbol in prepared.checkpoint.blocked_symbols or (
        slot.regime not in {"BULL", "BEAR", "RANGE"} or slot.defense != "NORMAL"
    ):
        raise ValueError("unavailable/unsupported original slot")
    record = CreationRecord(slot.sha256, origin, outcome)
    previous = next((r for r in ledger.records if (r.slot_sha256, r.origin) == (slot.sha256, origin)), None)
    if previous is not None and previous != record:
        raise ValueError("original response already consumed; no resampling or clock renewal")
    plans = _plans(policy, slot, origin, outcome)
    return (ledger if previous is not None else replace(ledger, records=ledger.records + (record,)), plans)


@dataclass(frozen=True)
class OriginRun:
    plan: CatalystPlan
    observations: tuple[HypothesisObservation, ...]


@dataclass(frozen=True)
class ArmDecision:
    arm_id: str
    symbol: str
    issued_ms: int
    reason: str
    candidate: SleeveIntent | None = None


def _resolve_arm(
    policy,
    prepared,
    ledger,
    *,
    symbol,
    arm_id,
    issued_ms,
    runs,
    shared_gate="UNKNOWN",
    current_prepared=None,
    context_chain=(),
):
    """Decision-only four-arm compositor, NOT four-arm fills/PnL/cost accounting.

    Candidate-specific veto is not a global ban; shared uncertainty is. Every
    candidate must be issued NOW, not saved/requoted while waiting for its peer.
    This result is never a RiskTradeDecision or an order.
    """
    policy.__post_init__()
    _check_prepared(policy, prepared)
    ledger.__post_init__()
    _clock(issued_ms)
    if (
        prepared.checkpoint.policy_sha256 != policy.sha256
        or ledger.policy_sha256 != policy.sha256
        or arm_id not in ARMS
        or symbol not in UNIVERSE
        or shared_gate not in {"PASS", "BLOCKED", "UNKNOWN"}
        or type(runs) is not tuple
        or any(type(r) is not OriginRun for r in runs)
    ):
        raise ValueError("original preparation, arm and explicit shared gate required")
    slot = next(s for s in prepared.slots if s.cell.price.symbol == symbol)

    def result(reason, candidate=None):
        return ArmDecision(arm_id, symbol, issued_ms, reason, candidate)

    if issued_ms < slot.cell.price.observed_ms:
        raise ValueError("arbitration cannot predate the original slot")
    if shared_gate != "PASS" or symbol in prepared.checkpoint.blocked_symbols:
        return result("SHARED_GATE_BLOCKED_OR_UNKNOWN")
    if current_prepared is None:
        return result("CURRENT_ADMISSION_CONTEXT_MISSING")
    _check_prepared(policy, current_prepared)
    if (
        current_prepared.checkpoint.policy_sha256 != policy.sha256
        or current_prepared.checkpoint.last_cut_ms != (issued_ms // PERIOD) * PERIOD
        or current_prepared.checkpoint.last_cut_ms < prepared.checkpoint.last_cut_ms
    ):
        return result("CURRENT_ADMISSION_CONTEXT_STALE_OR_CONFLICTING")
    if type(context_chain) is not tuple or len(context_chain) > 3:
        raise ValueError("bounded retained current-context chain required")
    predecessor = prepared
    for item in context_chain:
        _check_prepared(policy, item)
        if item.previous != predecessor.checkpoint:
            raise ValueError("current context is not a descendant of original preparation")
        predecessor = item
    if predecessor != current_prepared:
        raise ValueError("same-cut substitution or incomplete retained context chain")
    current_slot = next(s for s in current_prepared.slots if s.cell.price.symbol == symbol)
    if symbol in current_prepared.checkpoint.blocked_symbols:
        return result("CURRENT_INTEGRITY_BLOCKED_NO_PENDING_RESCUE")
    if issued_ms < current_slot.cell.price.observed_ms:
        raise ValueError("arbitration cannot predate current context capture")
    if current_slot.cell.price.observed_ms >= current_slot.cell.price.cut_ms + MINUTE or (
        arm_id != "strategy_only"
        and (
            current_slot.cell.event_coverage != "KNOWN"
            or not control._sources_ready(policy.session, current_slot.cell.price)
        )
    ):
        return result("CURRENT_CONTEXT_UNAVAILABLE_OR_LATE")
    if arm_id in set(slot.cell.active_arms) | set(current_slot.cell.active_arms):
        return result("ACTIVE_PLAN_OR_POSITION_NO_NEW_ENTRY")
    if (
        current_slot.defense != "NORMAL"
        or current_slot.regime not in {"BULL", "BEAR", "RANGE"}
        or slot.defense != "NORMAL"
        or slot.regime not in {"BULL", "BEAR", "RANGE"}
    ):
        return result("UNSUPPORTED_REGIME_OR_DEFENSE")
    expected, quiet, unknown = {}, set(), set()
    for origin in sorted(control.ARM_ORIGINS[arm_id]):
        record = next(
            (r for r in ledger.records if r.slot_sha256 == slot.sha256 and r.origin == origin), None
        )
        if origin == "TECHNICAL" and slot.technical_state == "QUIET":
            quiet.add(origin)
        elif origin == "CONTEXT_PROPOSAL" and slot.reason in {
            "NO_NEW_EVENT",
            "NO_CALL_ACTIVE_ALL_CONTEXT_ARMS",
        }:
            quiet.add(origin)
        elif record is None:
            unknown.add(origin)
        else:
            if record.outcome.status in {"FAILED", "UNKNOWN"}:
                unknown.add(origin)
                continue
            plan = dict(_plans(policy, slot, origin, record.outcome)).get(arm_id)
            if plan is None:
                quiet.add(origin)
            else:
                expected[origin] = plan
    by_origin = {}
    for run in runs:
        if (
            type(run.plan) is not CatalystPlan
            or run.plan.origin in by_origin
            or (expected.get(run.plan.origin) != run.plan)
        ):
            raise ValueError("run must use the exact original arm plan; no changed protection/review")
        by_origin[run.plan.origin] = run
    candidates = []
    for origin, plan in expected.items():
        run = by_origin.get(origin)
        if run is None:
            unknown.add(origin)
            continue
        evaluation = evaluate_hypothesis(plan, run.observations)[-1]
        if evaluation.candidate is not None:
            if evaluation.observed_ms != issued_ms:
                raise ValueError("no delayed arbitration, requote or backdated candidate")
            candidates.append((origin, evaluation.candidate))
        elif evaluation.state == "WAITING_TRIGGER" or evaluation.coverage != "AVAILABLE":
            unknown.add(origin)
        else:
            quiet.add(origin)
    if unknown:
        return result("REQUIRED_PEER_UNAVAILABLE_NO_LATE_FALLBACK")
    if not candidates:
        return result("NO_ADMITTED_CANDIDATE")
    if len({c.side for _, c in candidates}) > 1:
        return result("OPPOSITE_CONFIRMED_ORIGINS_ABSTAIN")
    origin, candidate = min(candidates, key=lambda row: row[0] != "TECHNICAL")
    return result("TECHNICAL_PRIORITY_ON_SAME_SIDE" if len(candidates) > 1 else origin, candidate)


@dataclass(frozen=True)
class ObservationPrefix:
    arm_id: str
    plan_id: str
    observation_ids: tuple[str, ...]


@dataclass(frozen=True)
class ResolutionRecord:
    slot_sha256: str
    arm_id: str
    inputs_sha256: str
    decision: ArmDecision


@dataclass(frozen=True)
class DecisionLedger:
    """Retain this independently. A caller-created empty ledger is not a restart proof."""

    policy_sha256: str
    prefixes: tuple[ObservationPrefix, ...] = ()
    resolutions: tuple[ResolutionRecord, ...] = ()

    def __post_init__(self):
        _sha(self.policy_sha256)
        if (
            type(self.prefixes) is not tuple
            or type(self.resolutions) is not tuple
            or len(self.prefixes) > 8 * len(UNIVERSE) * 1440
            or len(self.resolutions) > 4 * len(UNIVERSE) * 1440
        ):
            raise ValueError("bounded original arbitration ledger required")
        prefix_keys, resolution_keys = [], []
        for prefix in self.prefixes:
            if type(prefix) is not ObservationPrefix or prefix.arm_id not in ARMS:
                raise ValueError("typed original arm observation prefix required")
            _sha(prefix.plan_id)
            if type(prefix.observation_ids) is not tuple or len(prefix.observation_ids) > 60:
                raise ValueError("bounded immutable original observations required")
            for identity in prefix.observation_ids:
                _sha(identity)
            prefix_keys.append((prefix.arm_id, prefix.plan_id))
        for record in self.resolutions:
            if type(record) is not ResolutionRecord or record.arm_id not in ARMS:
                raise ValueError("typed original arm arbitration required")
            _sha(record.slot_sha256)
            _sha(record.inputs_sha256)
            if type(record.decision) is not ArmDecision or record.decision.arm_id != record.arm_id:
                raise ValueError("arbitration arm identity conflict")
            resolution_keys.append((record.slot_sha256, record.arm_id))
        if len(prefix_keys) != len(set(prefix_keys)) or len(resolution_keys) != len(set(resolution_keys)):
            raise ValueError("duplicate retained arbitration identity")

    @property
    def sha256(self):
        return digest(asdict(self))


def resolve_arm(policy, prepared, ledger, *, decisions, symbol, arm_id, issued_ms, runs, **admission):
    """Retained first-candidate arbitration, no unknown-peer or late winner rescue.

    Keep every original per-arm observation prefix, including VETO/missing review.
    A later observation must extend that prefix, not replace its review or quote.
    The first origin that could emit a candidate consumes this arm's cohort,
    including shared-gate/peer failure. Prior candidate-scoped VETO alone does
    not consume an independent later opportunity. No fills or finances exist here.
    """
    if type(decisions) is not DecisionLedger or decisions.policy_sha256 != policy.sha256:
        raise ValueError("independently retained policy arbitration checkpoint required")
    decisions.__post_init__()
    _check_prepared(policy, prepared)
    ledger.__post_init__()
    _clock(issued_ms)
    if arm_id not in ARMS or symbol not in UNIVERSE or ledger.policy_sha256 != policy.sha256:
        raise ValueError("original preparation, arm and creation ledger required")
    if type(runs) is not tuple or any(type(r) is not OriginRun for r in runs):
        raise ValueError("immutable original arm runs required")
    slot = next(s for s in prepared.slots if s.cell.price.symbol == symbol)
    relevant = tuple(
        r for r in ledger.records if r.slot_sha256 == slot.sha256 and r.origin in control.ARM_ORIGINS[arm_id]
    )
    if any(r.outcome.actual_created_ms > issued_ms for r in relevant):
        raise ValueError("future creation outcome cannot inform earlier arbitration")
    prefixes, first_candidate, shared_bars = list(decisions.prefixes), None, {}
    for run in runs:
        if run.plan.created_ms > issued_ms or any(o.market.observed_ms > issued_ms for o in run.observations):
            raise ValueError("future peer observation cannot inform earlier arbitration")
        for observation in run.observations:
            bar = observation.market.candle
            payload = digest(candle_payload(bar))
            key = (bar.symbol, bar.open_time_ms)
            if key in shared_bars and shared_bars[key] != payload:
                raise ValueError("conflicting shared closed-market history across origins")
            shared_bars[key] = payload
        evaluations = evaluate_hypothesis(run.plan, run.observations)
        prefix = ObservationPrefix(
            arm_id, run.plan.scenario_id, tuple(o.observation_id for o in run.observations)
        )
        previous = next((p for p in prefixes if (p.arm_id, p.plan_id) == (arm_id, prefix.plan_id)), None)
        if previous is not None:
            if prefix.observation_ids[: len(previous.observation_ids)] != previous.observation_ids:
                raise ValueError("original review/quote prefix cannot be changed or discarded")
            prefixes.remove(previous)
        prefixes.append(prefix)
        for evaluation in evaluations:
            if evaluation.candidate is not None:
                first_candidate = min(first_candidate or evaluation.observed_ms, evaluation.observed_ms)
    inputs = digest(
        {
            "policy": policy.sha256,
            "prepared": prepared.sha256,
            "arm": arm_id,
            "issued_ms": issued_ms,
            "runs": [asdict(r) for r in runs],
            "creation": [asdict(r) for r in relevant],
            "admission": {
                key: (
                    [p.sha256 for p in value]
                    if key == "context_chain"
                    else value.sha256
                    if key == "current_prepared" and value is not None
                    else value
                )
                for key, value in admission.items()
            },
        }
    )
    prior = next(
        (r for r in decisions.resolutions if (r.slot_sha256, r.arm_id) == (slot.sha256, arm_id)), None
    )
    if prior is not None:
        if prior.inputs_sha256 == inputs:
            return decisions, prior.decision
        # A new observation can be retained, but never turn a spent cohort into an entry.
        return replace(decisions, prefixes=tuple(prefixes)), ArmDecision(
            arm_id, symbol, issued_ms, "OPPORTUNITY_ALREADY_CONSUMED_NO_RESURRECTION"
        )
    result = _resolve_arm(
        policy, prepared, ledger, symbol=symbol, arm_id=arm_id, issued_ms=issued_ms, runs=runs, **admission
    )
    if first_candidate is not None and first_candidate != issued_ms:
        result = ArmDecision(arm_id, symbol, issued_ms, "FIRST_CANDIDATE_ARBITRATION_MISSED_NO_LATE_RESCUE")
    records = decisions.resolutions
    if first_candidate is not None:
        records += (ResolutionRecord(slot.sha256, arm_id, inputs, result),)
    return replace(decisions, prefixes=tuple(prefixes), resolutions=records), result
