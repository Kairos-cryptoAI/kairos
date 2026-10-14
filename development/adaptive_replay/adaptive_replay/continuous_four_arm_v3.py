"""Fixed four-arm, offline prospective-V3 replay orchestration.

The driver consumes originals, not model calls. It owns a durable write-ahead
operation ledger and four separate fixed-horizon accounts. Its inputs are local
commitments, not historical source/provider/funding authentication. Neither
fixture completion nor caller-attested nonfixture inputs select an economic
winner, change REJECT_ALL, or grant runtime routing permission.

Combined semantics are explicitly V3 arm-wide review of BOTH origins, with
conflict abstention, technical priority and veto/no-fallback. They are NOT the
static five-minute system evaluator's combined policy. An already issued native
receipt is never delayed to learn a peer decision and then backdated/requoted.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from kairos_execution.simulation.models import AcceptedBookFrame

from .continuous_sim import MAX_PARENTS, UNIVERSE, SimInputError, _available, _id, _input_doc, _sha
from .continuous_sim_v3_horizon import (
    MAX_BATCH,
    ContinuousSimV3Horizon,
    FiveDayHorizonV3,
    HorizonCandleOriginalsV3,
    HorizonTapeBindingV3,
    NoRouteDecisionV3,
)
from .historical_context import digest
from .hypothesis_journal_v3 import HypothesisJournalV3, JournalCheckpointV3, JournalReceiptV3
from .sim_account_core_codec_v3 import decode_account_core
from .sim_delta_journal_v3 import DeltaCheckpointV3, SimDeltaJournalV3
from .sim_financial_journal_v3 import DEFAULT_LIMITS, FinancialCheckpointV3, SimFinancialJournalV3
from .sim_financial_journal_v3 import MAX_DATABASE_BYTES as FINANCIAL_MAX_DATABASE_BYTES
from .sim_financial_journal_v3 import MAX_EVENT_BYTES as FINANCIAL_MAX_EVENT_BYTES
from .sim_financial_journal_v3 import MAX_ROWS as FINANCIAL_MAX_ROWS
from .sim_financial_journal_v3 import MAX_STATE_BYTES as FINANCIAL_MAX_STATE_BYTES
from .sim_state_journal import JournalIdentity, OptimisticConflict, _canonical, _hash, _safe_path
from .system import AttemptReceipt

SCHEMA = "kairos.research.continuous-four-arm.v3"
ARMS = ("combined", "context_review", "independent_proposals", "strategy_only")
ORIGINS = {
    "strategy_only": ("TECHNICAL",),
    "context_review": ("TECHNICAL",),
    "independent_proposals": ("CONTEXT_PROPOSAL",),
    "combined": ("CONTEXT_PROPOSAL", "TECHNICAL"),
}
COMBINED = "V3_BOTH_ORIGINS_REVIEW_CONFLICT_ABSTAIN_TECHNICAL_FIRST_NO_LATE_ARBITRATION"
NO_CALL = "PRESEALED_POLICY_ABSTAIN_POSITIVE_PARENT_ABSENCE_ONLY"
MINUTE = 60_000
CADENCE = 300_000
LEGACY_PROFILE = "LEGACY_V3"
FINANCIAL_PROFILE = "FINANCIAL_V3"
COMPACT_FINANCIAL_PROFILE = "COMPACT_FINANCIAL_V3"


def _consumer(profile):
    if profile == LEGACY_PROFILE:
        return ContinuousSimV3Horizon
    if profile in {FINANCIAL_PROFILE, COMPACT_FINANCIAL_PROFILE}:
        from .continuous_sim_financial_v3_horizon import ContinuousSimFinancialV3Horizon

        return ContinuousSimFinancialV3Horizon
    raise SimInputError("explicit known account profile required")


def _clock(value):
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise SimInputError("exact nonnegative clock required")


def _money(value, *, optional=False):
    if optional and value is None:
        return
    if type(value) is not Decimal or not value.is_finite() or value < 0:
        raise SimInputError("exact finite nonnegative Decimal required")


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        return _plain(asdict(value))
    return value


@dataclass(frozen=True)
class ProducerInputV3:
    producer_id: str
    journal: HypothesisJournalV3
    checkpoint: JournalCheckpointV3

    def __post_init__(self):
        _id(self.producer_id)
        if type(self.journal) is not HypothesisJournalV3 or type(self.checkpoint) is not JournalCheckpointV3:
            raise SimInputError("original native V3 producer and independent checkpoint required")


@dataclass(frozen=True)
class NativeRouteInputV3:
    producer_id: str
    receipt: JournalReceiptV3

    @property
    def key(self):
        return f"{self.producer_id}:{self.receipt.arm_id}:{self.receipt.parent_id}"


@dataclass(frozen=True)
class OriginSlotV3:
    """Complete unchanged five-minute technical/proposal scheduling roster.

    QUIET is a positively retained no-parent outcome. UNAVAILABLE is not quiet.
    Parent IDs refer to originals enrolled identically across all four arms.
    """

    symbol: str
    cut_ms: int
    observed_ms: int
    technical_state: str
    technical_parent_id: str | None
    proposal_state: str
    proposal_parent_id: str | None
    source_sha256: str

    def __post_init__(self):
        _clock(self.cut_ms)
        _clock(self.observed_ms)
        _sha(self.source_sha256)
        if self.symbol not in UNIVERSE or self.observed_ms < self.cut_ms:
            raise SimInputError("causal fixed-universe original slot required")
        for state, parent in (
            (self.technical_state, self.technical_parent_id),
            (self.proposal_state, self.proposal_parent_id),
        ):
            if state not in {"PARENT", "QUIET", "UNAVAILABLE"} or (state == "PARENT") != (parent is not None):
                raise SimInputError("explicit original parent/quiet/unavailable state required")
            if parent is not None:
                _sha(parent)

    @property
    def key(self):
        return f"{self.symbol}:{self.cut_ms}"


@dataclass(frozen=True)
class MinuteCellV3:
    symbol: str
    minute_ms: int
    available_ms: int
    coverage: str
    source_sha256: str

    def __post_init__(self):
        _clock(self.minute_ms)
        _clock(self.available_ms)
        _sha(self.source_sha256)
        if (
            self.symbol not in UNIVERSE
            or self.minute_ms % MINUTE
            or self.available_ms < self.minute_ms + MINUTE
            or self.coverage not in {"AVAILABLE", "UNAVAILABLE"}
        ):
            raise SimInputError("explicit causal minute denominator required")

    @property
    def key(self):
        return f"{self.symbol}:{self.minute_ms}"


@dataclass(frozen=True)
class ScheduledAttemptV3:
    """Frozen physical attempt plus exact original target consumers.

    REVIEW target tuples are (producer, arm, parent, observation ID). CREATION
    tuples use the creation-input SHA instead of observation ID. A shared call
    must actually contain every original target; this contract never clones a
    review or turns a creation response into a review. Missing evidence stays
    absent, rather than fabricating NOT_CALLED.
    """

    schedule_key: str
    origin_slot_key: str
    role: str
    requested_ms: int
    disposition_ms: int
    consumer_arms: tuple[str, ...]
    targets: tuple[tuple[str, str, str, str], ...]
    attempt: AttemptReceipt | None
    original_response_sha256: str | None
    model_config_sha256: str | None = None

    def __post_init__(self):
        _id(self.schedule_key)
        _id(self.origin_slot_key)
        _clock(self.requested_ms)
        _clock(self.disposition_ms)
        if (
            self.role not in {"CREATION", "REVIEW"}
            or self.disposition_ms < self.requested_ms
            or type(self.consumer_arms) is not tuple
            or not self.consumer_arms
            or self.consumer_arms != tuple(sorted(set(self.consumer_arms)))
            or not set(self.consumer_arms) <= set(ARMS)
            or type(self.targets) is not tuple
            or self.targets != tuple(sorted(set(self.targets)))
        ):
            raise SimInputError("canonical frozen attempt schedule/consumer/target roster required")
        for producer, arm, parent, context in self.targets:
            _id(producer)
            _sha(parent)
            _sha(context)
            if arm not in self.consumer_arms:
                raise SimInputError("attempt target outside its charged consumers")
        if self.role == "CREATION" and not set(self.consumer_arms) <= {"independent_proposals", "combined"}:
            raise SimInputError("creation expenses cannot enter technical-only arms")
        if self.role == "REVIEW" and not set(self.consumer_arms) <= {"context_review", "combined"}:
            raise SimInputError("review expenses cannot enter no-review arms")
        if self.attempt is not None:
            if type(self.attempt) is not AttemptReceipt:
                raise SimInputError("native exact typed attempt required")
            AttemptReceipt(**asdict(self.attempt))
            if (
                self.attempt.requested_ms != self.requested_ms
                or self.attempt.observed_ms != self.disposition_ms
            ):
                raise SimInputError("scheduled attempt clock differs from original receipt")
            if self.attempt.status == "COMPLETE":
                _sha(self.original_response_sha256)
                _sha(self.model_config_sha256)
            elif self.original_response_sha256 is not None:
                raise SimInputError("error/no-call cannot invent an original response")
        elif self.original_response_sha256 is not None:
            raise SimInputError("missing attempt cannot invent response evidence")
        if self.model_config_sha256 is not None:
            _sha(self.model_config_sha256)

    @property
    def cost_id(self):
        return f"attempt:{self.schedule_key}"


@dataclass(frozen=True)
class SharedExpenseV3:
    cost_id: str
    at_ms: int
    amount_usd: Decimal | None
    source_sha256: str
    consumer_arms: tuple[str, ...] = ARMS

    def __post_init__(self):
        _id(self.cost_id)
        _clock(self.at_ms)
        _money(self.amount_usd, optional=True)
        _sha(self.source_sha256)
        if (
            type(self.consumer_arms) is not tuple
            or not self.consumer_arms
            or self.consumer_arms != tuple(sorted(set(self.consumer_arms)))
            or not set(self.consumer_arms) <= set(ARMS)
        ):
            raise SimInputError("explicit canonical shared expense attribution required")


@dataclass(frozen=True)
class FourArmSealV3:
    experiment_id: str
    sealed_ms: int
    horizon: FiveDayHorizonV3
    slots_sha256: str
    cells_sha256: str
    native_roster_sha256: str
    attempt_schedule_sha256: str
    shared_expenses_sha256: str
    # A known modeled budget is not provider invoice/authentication evidence.
    budgets_usd: tuple[tuple[str, Decimal | None], ...]
    budget_evidence_sha256: str
    combined_semantics: str = COMBINED
    no_call_semantics: str = NO_CALL

    def __post_init__(self):
        _id(self.experiment_id)
        _clock(self.sealed_ms)
        if type(self.horizon) is not FiveDayHorizonV3 or self.sealed_ms > self.horizon.entry_start_ms:
            raise SimInputError("fixed pre-cut five-day horizon required")
        for sha in (
            self.slots_sha256,
            self.cells_sha256,
            self.native_roster_sha256,
            self.attempt_schedule_sha256,
            self.shared_expenses_sha256,
            self.budget_evidence_sha256,
        ):
            _sha(sha)
        if (
            self.combined_semantics != COMBINED
            or self.no_call_semantics != NO_CALL
            or type(self.budgets_usd) is not tuple
            or tuple(a for a, _ in self.budgets_usd) != ARMS
        ):
            raise SimInputError("exact fixed four-arm budgets and explicit V3 combined semantics required")
        for _, amount in self.budgets_usd:
            _money(amount, optional=True)


@dataclass(frozen=True)
class FourArmInputsV3:
    binding: HorizonTapeBindingV3
    candle_originals: HorizonCandleOriginalsV3
    models: dict
    rules: dict
    funding_schedule: Any
    initial_equity: Decimal
    producers: tuple[ProducerInputV3, ...]
    native_routes: tuple[NativeRouteInputV3, ...]
    origin_slots: tuple[OriginSlotV3, ...]
    minute_cells: tuple[MinuteCellV3, ...]
    attempts: tuple[ScheduledAttemptV3, ...]
    shared_expenses: tuple[SharedExpenseV3, ...]


def roster_hashes(inputs):
    """Canonical commitments; these are NOT source/budget admission proofs."""
    return {
        "slots_sha256": digest(_plain(inputs.origin_slots)),
        "cells_sha256": digest(_plain(inputs.minute_cells)),
        "native_roster_sha256": digest(
            [
                {"producer": x.producer_id, "receipt": _plain(replace(x.receipt, new_event=False))}
                for x in inputs.native_routes
            ]
        ),
        "attempt_schedule_sha256": digest(_plain(inputs.attempts)),
        "shared_expenses_sha256": digest(_plain(inputs.shared_expenses)),
    }


@dataclass(frozen=True)
class PreparedFourArmV3:
    seal: FourArmSealV3
    inputs: FourArmInputsV3
    identity_sha256: str
    producer_snapshots: dict
    groups: dict
    routing: tuple[dict, ...]
    operations: tuple[dict, ...]
    expected_parents: dict
    budget_blocked: tuple[str, ...]
    cell_facts: dict
    account_profile: str = LEGACY_PROFILE
    account_storage: tuple[tuple[str, int], ...] = ()
    compact_storage: tuple[tuple[str, int], ...] = ()
    compact_config_hashes: tuple[tuple[str, str], ...] = ()


def _exact_receipt(native, snapshots):
    if type(native) is not NativeRouteInputV3 or type(native.receipt) is not JournalReceiptV3:
        raise SimInputError("exact original native route required")
    snapshot = snapshots.get(native.producer_id)
    if snapshot is None:
        raise SimInputError("unknown native producer")
    group = next(
        (
            g
            for g in snapshot.hypotheses
            if g.arm_id == native.receipt.arm_id and g.plan.template.intent_id == native.receipt.parent_id
        ),
        None,
    )
    first = (
        None if group is None else next((r for r in group.receipts if r.evaluation.state == "CONSUMED"), None)
    )
    if first is None or replace(native.receipt, new_event=False) != first:
        raise SimInputError("exact first CONSUMED receipt, not terminal redelivery, required")
    return group


def _validate_attempt_targets(attempts, groups, fixture):
    covered = set()
    ids = set()
    for scheduled in attempts:
        ScheduledAttemptV3(**asdict(scheduled) | {"attempt": scheduled.attempt})
        attempt = scheduled.attempt
        if attempt is not None:
            if (attempt.evidence_kind == "TEST_FIXTURE") != fixture or attempt.attempt_id in ids:
                raise SimInputError("unique physical attempt IDs and unmixed evidence required")
            ids.add(attempt.attempt_id)
        for target in scheduled.targets:
            if target in covered:
                raise SimInputError("duplicate physical outcome for one native target")
            covered.add(target)
            producer, arm, parent, context = target
            group = groups.get((producer, arm, parent))
            if group is None:
                raise SimInputError("provider attempt cites unknown original target")
            if scheduled.role == "CREATION":
                assessment = group.plan.creation_assessment
                if (
                    assessment is None
                    or context != group.plan.creation_input_sha256
                    or attempt is None
                    or attempt.status != "COMPLETE"
                    or assessment.actual_requested_ms != attempt.requested_ms
                    or assessment.actual_captured_ms != attempt.observed_ms
                    or attempt.context_sha256 != assessment.input_sha256
                    or scheduled.original_response_sha256 != assessment.response_sha256
                    or scheduled.model_config_sha256 != assessment.model_config_sha256
                ):
                    raise SimInputError("creation expense must link original creation assessment")
            else:
                pair = next(
                    (
                        (o, r)
                        for o, r in zip(group.observations, group.review_receipts, strict=True)
                        if o.observation_id == context
                    ),
                    None,
                )
                if pair is None:
                    raise SimInputError("review target absent from native original observations")
                observation, review = pair
                if review.review is not None:
                    if (
                        attempt is None
                        or attempt.status != "COMPLETE"
                        or attempt.requested_ms != review.actual_requested_ms
                        or attempt.observed_ms != review.actual_captured_ms
                        or attempt.context_sha256 != observation.context_sha256
                        or scheduled.original_response_sha256 != review.review.response_sha256
                        or scheduled.model_config_sha256 != review.model_config_sha256
                    ):
                        raise SimInputError("expense/review original request input or completion mismatch")
                elif attempt is not None and attempt.status == "COMPLETE":
                    raise SimInputError("completed review attempt lacks native original review")
    # Every actual native creation/review requires a physical ledger link.
    for (producer, arm, parent), group in groups.items():
        if group.plan.origin == "CONTEXT_PROPOSAL" and arm in {"independent_proposals", "combined"}:
            if (producer, arm, parent, group.plan.creation_input_sha256) not in covered:
                raise SimInputError("native creation has no admitted physical expense target")
        if group.plan.policy.require_review:
            for observation, review in zip(group.observations, group.review_receipts, strict=True):
                if (
                    review.review is not None
                    and (producer, arm, parent, observation.observation_id) not in covered
                ):
                    raise SimInputError("native review has no physical expense target")


def _route_decisions(inputs, seal, groups, budget_blocked):
    slots = {(s.symbol, s.cut_ms): s for s in inputs.origin_slots}
    issued = {(n.producer_id, n.receipt.arm_id, n.receipt.parent_id): n for n in inputs.native_routes}
    # Parent IDs are globally unique across original producers, never adopted twice.
    by_parent = {g.plan.template.intent_id: p for (p, _, _), g in groups.items()}
    decisions = []
    for native in inputs.native_routes:
        r = native.receipt
        group = groups[native.producer_id, r.arm_id, r.parent_id]
        plan, at = group.plan, r.evaluation.observed_ms
        slot = slots[plan.template.symbol, plan.origin_cut_ms]
        reason, disposition = "ORIGIN_ALLOWED", "ROUTE"
        coverage = r.evaluation.coverage
        if plan.origin not in ORIGINS[r.arm_id]:
            disposition, reason, coverage = "NO_ROUTE", "INACTIVE_ORIGIN", "AVAILABLE"
        elif not seal.horizon.entry_start_ms <= at < seal.horizon.entry_end_ms:
            disposition, reason = "NO_ROUTE", "OUTSIDE_ACTUAL_ADMISSION_HORIZON"
        elif r.arm_id in budget_blocked:
            disposition, reason, coverage = "UNAVAILABLE", "BUDGET_OR_COST_UNRESOLVED", "UNAVAILABLE"
        elif any(
            r.arm_id in a.consumer_arms
            and a.requested_ms <= at
            and (a.attempt is None or a.attempt.cost_usd is None or a.disposition_ms > at)
            for a in inputs.attempts
        ):
            disposition, reason, coverage = (
                "UNAVAILABLE",
                "ACTIVE_PROVIDER_LIABILITY_UNRESOLVED",
                "UNAVAILABLE",
            )
        elif any(
            r.arm_id in c.consumer_arms and c.at_ms <= at and c.amount_usd is None
            for c in inputs.shared_expenses
        ):
            disposition, reason, coverage = "UNAVAILABLE", "ACTIVE_SHARED_LIABILITY_UNRESOLVED", "UNAVAILABLE"
        elif r.arm_id == "combined":
            if (
                slot.observed_ms > at
                or slot.technical_state == "UNAVAILABLE"
                or slot.proposal_state == "UNAVAILABLE"
            ):
                disposition, reason, coverage = (
                    "UNAVAILABLE",
                    "PEER_SLOT_UNKNOWN_AT_NATIVE_ISSUE",
                    "UNAVAILABLE",
                )
            elif slot.technical_state == "PARENT":
                technical = issued.get(
                    (by_parent[slot.technical_parent_id], "combined", slot.technical_parent_id)
                )
                proposal = (
                    None
                    if slot.proposal_parent_id is None
                    else issued.get((by_parent[slot.proposal_parent_id], "combined", slot.proposal_parent_id))
                )
                if plan.origin == "CONTEXT_PROPOSAL":
                    disposition, reason = "NO_ROUTE", "TECHNICAL_FIRST_NO_PROPOSAL_FALLBACK"
                elif slot.proposal_state == "QUIET" and not any(
                    a.role == "CREATION"
                    and a.origin_slot_key == slot.key
                    and a.attempt is not None
                    and a.attempt.status == "COMPLETE"
                    and a.disposition_ms <= at
                    for a in inputs.attempts
                ):
                    disposition, reason, coverage = (
                        "UNAVAILABLE",
                        "PROPOSAL_NOT_COMPLETED_AT_NATIVE_ISSUE",
                        "UNAVAILABLE",
                    )
                elif technical is None or (
                    slot.proposal_state == "PARENT"
                    and (proposal is None or proposal.receipt.evaluation.observed_ms > at)
                ):
                    disposition, reason, coverage = (
                        "UNAVAILABLE",
                        "PEER_ARBITRATION_NOT_KNOWN_AT_NATIVE_ISSUE",
                        "UNAVAILABLE",
                    )
                elif proposal is not None:
                    tc, pc = technical.receipt.evaluation.candidate, proposal.receipt.evaluation.candidate
                    if tc is not None and pc is not None and tc.side is not pc.side:
                        disposition, reason = "NO_ROUTE", "DIRECTION_CONFLICT"
                    elif tc is not None and pc is None:
                        disposition, reason, coverage = (
                            "UNAVAILABLE",
                            "PROPOSAL_UNUSABLE_NO_FALLBACK",
                            "UNAVAILABLE",
                        )
        decisions.append(
            {
                "native_key": native.key,
                "producer": native.producer_id,
                "arm": r.arm_id,
                "parent": r.parent_id,
                "origin": plan.origin,
                "plan": digest(_plain(plan)),
                "producer_head": next(
                    p.checkpoint.head_sha256 for p in inputs.producers if p.producer_id == native.producer_id
                ),
                "producer_seal": next(
                    p.checkpoint.seal_sha256 for p in inputs.producers if p.producer_id == native.producer_id
                ),
                "receipt": r.chain_sha256,
                "receipt_sequence": r.sequence,
                "native_receipt_sha256": digest(_plain(replace(r, new_event=False))),
                "native_reason": r.evaluation.reason,
                "at": at,
                "symbol": plan.template.symbol,
                "minute": at // MINUTE * MINUTE,
                "origin_cut": plan.origin_cut_ms,
                "slot": slot.key,
                "disposition": disposition,
                "reason": reason,
                "coverage": coverage,
            }
        )
    return tuple(decisions)


def _operations(inputs, seal, routing):
    """Batches only persistence, never cadence sampling or crossed decisions."""
    controls = []
    for index, attempt in enumerate(inputs.attempts):
        controls.append({"kind": "ATTEMPT", "at": attempt.disposition_ms, "index": index})
    for index, expense in enumerate(inputs.shared_expenses):
        controls.append({"kind": "EXPENSE", "at": expense.at_ms, "index": index})
    for index, route in enumerate(routing):
        # Tail originals are retained in the ledger without touching accounts.
        controls.append({"kind": "ROUTE", "at": route["at"], "index": index})
    slot_clocks = {(s.symbol, s.cut_ms): s.observed_ms for s in inputs.origin_slots}
    for index, cell in enumerate(inputs.minute_cells):
        known_at = max(cell.available_ms, slot_clocks.get((cell.symbol, cell.minute_ms), 0))
        controls.append({"kind": "CELL", "at": known_at, "index": index})
    controls.append({"kind": "FINISH", "at": seal.horizon.retained_end_ms})
    priority = {"ATTEMPT": 1, "EXPENSE": 1, "ROUTE": 2, "CELL": 3, "FINISH": 4}
    controls.sort(
        key=lambda o: (
            o["at"],
            priority[o["kind"]],
            routing[o["index"]]["native_key"] if o["kind"] == "ROUTE" else o.get("index", -1),
        )
    )
    operations, cursor = [], 0
    for control in controls:
        first = cursor + 1
        while (
            cursor < len(inputs.binding.inputs)
            and _available(inputs.binding.inputs[cursor].value) <= control["at"]
        ):
            cursor += 1
            if cursor - first + 1 == MAX_BATCH:
                operations.append(
                    {
                        "kind": "SOURCE",
                        "first": first,
                        "last": cursor,
                        "at": _available(inputs.binding.inputs[cursor - 1].value),
                    }
                )
                first = cursor + 1
        if first <= cursor:
            operations.append(
                {
                    "kind": "SOURCE",
                    "first": first,
                    "last": cursor,
                    "at": _available(inputs.binding.inputs[cursor - 1].value),
                }
            )
        operations.append(control)
    if cursor != len(inputs.binding.inputs):
        raise SimInputError("source item outside complete retained operation horizon")
    return tuple(operations)


def preflight_four_arm_v3(
    inputs: FourArmInputsV3,
    seal: FourArmSealV3,
    *,
    account_profile=LEGACY_PROFILE,
    account_storage=None,
    compact_storage=None,
) -> PreparedFourArmV3:
    """Read/audit the COMPLETE native roster before any economic account exists."""
    consumer = _consumer(account_profile)
    compact = account_profile == COMPACT_FINANCIAL_PROFILE
    if compact:
        from .compact_four_arm_driver_journal_v3 import SCHEMA as compact_schema
        from .compact_four_arm_driver_journal_v3 import CompactDriverLimitsV3

        if type(compact_storage) is not CompactDriverLimitsV3:
            raise SimInputError("explicit typed compact driver budgets required")
        compact_config = {
            "driver_schema": compact_schema,
            "driver_limits": asdict(compact_storage),
            "driver_implementation": digest(
                Path(__file__).with_name("compact_four_arm_driver_journal_v3.py").read_text(encoding="utf-8")
            ),
        }
    elif compact_storage is not None:
        raise SimInputError("compact budgets require explicit compact financial profile")
    if account_profile == LEGACY_PROFILE:
        if account_storage is not None:
            raise SimInputError("legacy storage profile is fixed")
        storage = {
            "max_event_rows": 520_192,
            "max_event_bytes": 2 * 1024 * 1024,
            "max_state_bytes": 64 * 1024 * 1024,
            "max_database_bytes": 512 * 1024 * 1024,
        }
    else:
        storage = {**DEFAULT_LIMITS, **(account_storage or {})}
        if set(storage) != set(DEFAULT_LIMITS) or any(type(v) is not int or v <= 0 for v in storage.values()):
            raise SimInputError("exact positive financial storage bounds required")
        maxima = {
            "max_event_rows": FINANCIAL_MAX_ROWS,
            "max_native_event_rows": FINANCIAL_MAX_ROWS,
            "max_event_bytes": FINANCIAL_MAX_EVENT_BYTES,
            "max_state_bytes": FINANCIAL_MAX_STATE_BYTES,
            "max_database_bytes": FINANCIAL_MAX_DATABASE_BYTES,
        }
        if any(storage[key] > maxima[key] for key in maxima) or storage["max_database_bytes"] < 32768:
            raise SimInputError("financial storage bounds outside supported limits")
    if type(inputs) is not FourArmInputsV3 or type(seal) is not FourArmSealV3:
        raise SimInputError("separate typed fixed four-arm inputs and seal required")
    FourArmSealV3(**asdict(seal) | {"horizon": seal.horizon})
    if (
        type(inputs.binding) is not HorizonTapeBindingV3
        or type(inputs.candle_originals) is not HorizonCandleOriginalsV3
    ):
        raise SimInputError("full fixed-horizon original source types required")
    for name in ("producers", "native_routes", "origin_slots", "minute_cells", "attempts", "shared_expenses"):
        if type(getattr(inputs, name)) is not tuple:
            raise SimInputError("immutable complete tuple rosters required")
    for slot in inputs.origin_slots:
        if type(slot) is not OriginSlotV3:
            raise SimInputError("typed exact original scheduling cell required")
        OriginSlotV3(**asdict(slot))
        if slot.observed_ms > seal.horizon.retained_end_ms:
            raise SimInputError("original slot outcome outside retained episode")
    for cell in inputs.minute_cells:
        if type(cell) is not MinuteCellV3 or cell.available_ms > seal.horizon.retained_end_ms:
            raise SimInputError("typed denominator availability inside retained episode required")
    if roster_hashes(inputs) != {k: getattr(seal, k) for k in roster_hashes(inputs)}:
        raise SimInputError("frozen schedule, originals or expense roster changed")
    if len(inputs.origin_slots) != 7200 or {(s.symbol, s.cut_ms) for s in inputs.origin_slots} != {
        (s, t)
        for s in UNIVERSE
        for t in range(seal.horizon.entry_start_ms, seal.horizon.entry_end_ms, CADENCE)
    }:
        raise SimInputError("complete fixed five-minute five-symbol original decision roster required")
    if len(inputs.minute_cells) != 36_000 or {(c.symbol, c.minute_ms) for c in inputs.minute_cells} != {
        (s, t) for s in UNIVERSE for t in seal.horizon.minutes
    }:
        raise SimInputError("complete exact 36,000 minute-cell denominator required")
    if len({p.producer_id for p in inputs.producers}) != len(inputs.producers) or not inputs.producers:
        raise SimInputError("unique independently checkpointed original producer roster required")
    snapshots, groups = {}, {}
    for producer in inputs.producers:
        ProducerInputV3(producer.producer_id, producer.journal, producer.checkpoint)
        snapshot = producer.journal.snapshot()
        if snapshot.checkpoint != producer.checkpoint:
            raise SimInputError("producer differs from independently retained exact head")
        if tuple(a.arm_id for a in producer.journal._seal.arms) != ARMS:
            raise SimInputError("native producer must enroll the exact four-arm peer roster")
        for arm in producer.journal._seal.arms:
            if arm.policy.require_review != (arm.arm_id in {"context_review", "combined"}):
                raise SimInputError("arm-wide native review differs from sealed V3 semantics")
        snapshots[producer.producer_id] = snapshot
        for group in snapshot.hypotheses:
            groups[producer.producer_id, group.arm_id, group.plan.template.intent_id] = group
    parents = {(p, parent) for p, _, parent in groups}
    if len(parents) > MAX_PARENTS:
        raise SimInputError(
            "complete registered roster exceeds unchanged 128-parent capacity; never truncate"
        )
    if len({parent for _, parent in parents}) != len(parents):
        raise SimInputError("parent identity reused across original producers")
    planned = {s.technical_parent_id for s in inputs.origin_slots if s.technical_parent_id is not None}
    planned |= {s.proposal_parent_id for s in inputs.origin_slots if s.proposal_parent_id is not None}
    if planned != {parent for _, parent in parents}:
        raise SimInputError("complete original-slot to enrolled-parent linkage required")
    source_cells = {(r.candle.symbol, r.candle.open_time_ms): r for r in inputs.candle_originals.records}
    for cell in inputs.minute_cells:
        MinuteCellV3(**asdict(cell))
        original = source_cells.get((cell.symbol, cell.minute_ms))
        if cell.coverage == "AVAILABLE" and (
            original is None or original.available_at_ms > cell.available_ms
        ):
            raise SimInputError("available denominator lacks its causal retained original")
    slots = {(s.symbol, s.cut_ms): s for s in inputs.origin_slots}
    for (_, _, parent), group in groups.items():
        slot = slots.get((group.plan.template.symbol, group.plan.origin_cut_ms))
        linked = (
            None
            if slot is None
            else (slot.technical_parent_id if group.plan.origin == "TECHNICAL" else slot.proposal_parent_id)
        )
        if linked != parent:
            raise SimInputError("native plan moved outside its unchanged original scheduling slot")
    expected_native = {
        (p, arm, parent)
        for (p, arm, parent), group in groups.items()
        if any(r.evaluation.state == "CONSUMED" for r in group.receipts)
    }
    actual_native = set()
    for native in inputs.native_routes:
        _exact_receipt(native, snapshots)
        if (
            not seal.horizon.data_start_ms
            <= native.receipt.evaluation.observed_ms
            <= seal.horizon.retained_end_ms
        ):
            raise SimInputError("native receipt outside retained episode cannot be silently omitted")
        key = (native.producer_id, native.receipt.arm_id, native.receipt.parent_id)
        if key in actual_native:
            raise SimInputError("duplicate native receipt intake manifest")
        actual_native.add(key)
    if actual_native != expected_native:
        raise SimInputError(
            "full native first-CONSUMED roster required, including vetoes and inactive origins"
        )
    if len({a.schedule_key for a in inputs.attempts}) != len(inputs.attempts):
        raise SimInputError("duplicate frozen attempt obligation")
    creation = [a for a in inputs.attempts if a.role == "CREATION"]
    if (
        len(creation) != len(inputs.origin_slots)
        or {a.origin_slot_key for a in creation} != {s.key for s in inputs.origin_slots}
        or any(a.consumer_arms != ("combined", "independent_proposals") for a in creation)
    ):
        raise SimInputError(
            "one retained proposal attempt/no-call obligation per fixed original slot required"
        )
    slots_by_key = {s.key: s for s in inputs.origin_slots}
    for attempt in inputs.attempts:
        slot = slots_by_key.get(attempt.origin_slot_key)
        if slot is None or attempt.requested_ms < slot.cut_ms:
            raise SimInputError("attempt moved outside its frozen original source slot")
    expense_ids = {a.cost_id for a in inputs.attempts} | {c.cost_id for c in inputs.shared_expenses}
    if len(expense_ids) != len(inputs.attempts) + len(inputs.shared_expenses):
        raise SimInputError("distinct complete service liability IDs required")
    _validate_attempt_targets(inputs.attempts, groups, inputs.binding.evidence_kind == "TEST_FIXTURE")
    for value in (*inputs.attempts, *inputs.shared_expenses):
        at = value.disposition_ms if type(value) is ScheduledAttemptV3 else value.at_ms
        if not seal.horizon.data_start_ms <= at <= seal.horizon.retained_end_ms:
            raise SimInputError("out-of-horizon expense liability cannot be dropped")
    budgets = dict(seal.budgets_usd)
    budget_blocked = tuple(
        arm
        for arm in ARMS
        if budgets[arm] is None
        or any(
            arm in a.consumer_arms and (a.attempt is None or a.attempt.cost_usd is None)
            for a in inputs.attempts
        )
        or any(arm in c.consumer_arms and c.amount_usd is None for c in inputs.shared_expenses)
        or sum(
            Decimal(str(a.attempt.cost_usd))
            for a in inputs.attempts
            if arm in a.consumer_arms and a.attempt is not None and a.attempt.cost_usd is not None
        )
        > budgets[arm]
    )
    routing = _route_decisions(inputs, seal, groups, budget_blocked)
    expected_parents = {
        arm: tuple(sorted(d["parent"] for d in routing if d["arm"] == arm and d["disposition"] == "ROUTE"))
        for arm in ARMS
    }
    if any(len(ids) > MAX_PARENTS for ids in expected_parents.values()):
        raise SimInputError("complete routed CONSUMED roster exceeds 128; no first-128 replay")
    # Configuration/original/expense validation happens before any create call.
    seals = {s.seal_sha256 for s in snapshots.values()}
    if len(seals) != 1:
        raise SimInputError("one exact native seal required by existing horizon account contract")
    financial_configs = {}
    for arm in ARMS:
        config_builder = (
            consumer._horizon_config if account_profile == LEGACY_PROFILE else consumer._financial_config
        )
        financial_configs[arm] = config_builder(
            **(
                {}
                if account_profile == LEGACY_PROFILE
                else {"owner_id": seal.experiment_id, "account_id": arm}
            ),
            binding=inputs.binding,
            models=inputs.models,
            rules=inputs.rules,
            funding=inputs.funding_schedule,
            arm_id=arm,
            horizon=seal.horizon,
            initial_equity=inputs.initial_equity,
            hypothesis_seal_sha256=next(iter(seals)),
            candle_originals=inputs.candle_originals,
            allowed_origins=ORIGINS[arm],
            maximum_exit_attempts=3,
            expected_cost_ids=tuple(
                sorted(
                    [a.cost_id for a in inputs.attempts if arm in a.consumer_arms]
                    + [c.cost_id for c in inputs.shared_expenses if arm in c.consumer_arms]
                )
            ),
            storage=storage,
            no_route_driver_seal_sha256=None,
        )
    # Reuse exact native original-validation code BEFORE any account exists.
    validator = object.__new__(ContinuousSimV3Horizon)
    validator.binding, validator.candle_originals = inputs.binding, inputs.candle_originals
    validator.config = {
        "candle_originals_sha256": inputs.candle_originals.sha256,
        "allowed_origins": ["TECHNICAL", "CONTEXT_PROPOSAL"],
    }
    book_originals = {
        (v.symbol, v.exchange_at_ms, v.received_at_ms, v.persisted_at_ms, v.bids[0].price, v.asks[0].price)
        for item in inputs.binding.inputs
        if type(v := item.value) is AcceptedBookFrame
    }
    for native in inputs.native_routes:
        group = groups[native.producer_id, native.receipt.arm_id, native.receipt.parent_id]
        receipt = native.receipt
        index = next(
            i
            for i, o in enumerate(group.observations)
            if o.observation_id == receipt.evaluation.observation_id
        )
        prefix = tuple(zip(group.observations[: index + 1], group.review_receipts[: index + 1], strict=True))
        if (
            group.plan.policy.evidence_kind != inputs.binding.evidence_kind
            or group.plan.policy.quote_source_id != inputs.binding.quote_source_id
        ):
            raise SimInputError("native evidence/quote policy conflicts with exact financial source roster")
        for observation, _ in prefix:
            quote = observation.quote
            if quote is not None and (
                quote.source_id != inputs.binding.quote_source_id
                or quote.evidence_kind != inputs.binding.evidence_kind
                or (
                    quote.symbol,
                    quote.event_ms,
                    quote.received_ms,
                    quote.captured_ms,
                    Decimal(str(quote.bid)),
                    Decimal(str(quote.ask)),
                )
                not in book_originals
            ):
                raise SimInputError("full native observation prefix quote absent from pinned original BBO")
        validator._validate_v3_originals(group.plan, receipt, prefix, receipt.evaluation.candidate)
    identity = digest(
        {
            **(
                {}
                if account_profile == LEGACY_PROFILE
                else {"account_profile": account_profile, "account_storage": storage}
            ),
            "schema": SCHEMA,
            **({"compact_driver": compact_config} if compact else {}),
            "seal": _plain(seal),
            "binding": inputs.binding.mapping_sha256,
            "originals": inputs.candle_originals.sha256,
            "financial_configs": financial_configs,
            "producers": {p.producer_id: _plain(p.checkpoint) for p in inputs.producers},
            "implementation": digest(Path(__file__).read_text(encoding="utf-8")),
            "routing": routing,
        }
    )
    facts = {
        c.key: {"unavailable": set(), "no_route": set(), "routes": {a: [] for a in ARMS}}
        for c in inputs.minute_cells
    }
    for route in routing:
        key = f"{route['symbol']}:{route['minute']}"
        if key in facts:
            facts[key]["routes"][route["arm"]].append(route)
    for slot in inputs.origin_slots:
        key = f"{slot.symbol}:{slot.cut_ms}"
        for arm in ARMS:
            if (
                arm in {"strategy_only", "context_review", "combined"}
                and slot.technical_state == "UNAVAILABLE"
            ) or (arm in {"independent_proposals", "combined"} and slot.proposal_state == "UNAVAILABLE"):
                facts[key]["unavailable"].add(arm)
    for (_, arm, _), group in groups.items():
        last = group.receipts[-1].evaluation
        if group.plan.origin in ORIGINS[arm] and (
            last.state not in {"CONSUMED", "INVALIDATED", "EXPIRED"} or last.coverage != "AVAILABLE"
        ):
            key = f"{group.plan.template.symbol}:{group.plan.origin_cut_ms}"
            facts[key]["unavailable"].add(arm)
    for attempt in inputs.attempts:
        slot = slots_by_key[attempt.origin_slot_key]
        clock = (
            attempt.requested_ms
            if attempt.attempt is None or attempt.attempt.cost_usd is None
            else attempt.disposition_ms
        )
        key = f"{slot.symbol}:{clock // MINUTE * MINUTE}"
        if key in facts:
            if attempt.attempt is None or attempt.attempt.cost_usd is None:
                facts[key]["unavailable"].update(attempt.consumer_arms)
            elif (
                attempt.attempt.status == "ERROR"
                or attempt.attempt.status == "NOT_CALLED"
                and attempt.attempt.no_call_reason != "SCHEDULED_POLICY_ABSTAIN"
            ):
                facts[key]["unavailable"].update(attempt.consumer_arms)
    return PreparedFourArmV3(
        seal,
        inputs,
        identity,
        snapshots,
        groups,
        routing,
        _operations(inputs, seal, routing),
        expected_parents,
        budget_blocked,
        facts,
        account_profile,
        () if account_profile == LEGACY_PROFILE else tuple(sorted(storage.items())),
        () if not compact else tuple(sorted(asdict(compact_storage).items())),
        ()
        if not compact
        else tuple(
            (a, digest(financial_configs[a] | {"no_route_driver_seal_sha256": identity})) for a in ARMS
        ),
    )


@dataclass(frozen=True)
class FourArmCheckpointV3:
    identity_sha256: str
    driver_checkpoint: Any
    arm_checkpoints: tuple[tuple[str, Any], ...]
    producer_checkpoints: tuple[tuple[str, JournalCheckpointV3], ...]
    operation_cursor: int
    pending_operation_sha256: str | None
    pending_operation: dict | None = None
    checkpoint_phase: str = "INTENT_COMMITTED"


def _anchored_checkpoint(path, before, expected_event):
    """Read only ONE exact allowed post-checkpoint event, never adopt latest.

    Opening the derived checkpoint subsequently performs the delta journal's
    complete identity/schema/hash/delta replay audit. The externally retained
    before head plus complete expected event ID/payload are mandatory anchors.
    """
    if type(before) is not DeltaCheckpointV3:
        raise SimInputError("independent typed delta checkpoint required")
    path = _safe_path(path, must_exist=True)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        head = connection.execute("SELECT * FROM head WHERE singleton=1").fetchone()
        if head is None:
            raise SimInputError("missing account head")
        current = DeltaCheckpointV3(
            before.identity_sha256,
            head["version"],
            head["state_hash"],
            head["head_hash"],
            head["last_clock_ms"],
        )
        if current == before:
            return before
        if expected_event is None or current.version != before.version + 1:
            raise SimInputError("journal advanced outside one independently anchored pending event")
        row = connection.execute("SELECT * FROM events WHERE version=?", (current.version,)).fetchone()
        if (
            row is None
            or row["previous_hash"] != before.head_hash
            or row["event_hash"] != current.head_hash
            or row["state_hash"] != current.state_hash
            or row["clock_ms"] != current.last_clock_ms
            or row["event_id"] != expected_event["event_id"]
            or row["payload_json"] != _canonical(expected_event["payload"])
            or ("at_ms" in expected_event and row["clock_ms"] != expected_event["at_ms"])
        ):
            raise SimInputError("newer event is not the EXACT recorded pending account operation")
    return current


def _anchored_financial_checkpoint(path, before, expected_event, *, identity, config, trusted_current=None):
    """Pinned, owned native/outer prefix plus at most one exact known operation.

    Restart always performs the complete audit. Live verification may supply a
    checkpoint from the owned journal's data-version guarded snapshot; this
    avoids replaying the entire history on every ordinary driver operation.
    This is local consistency, not source or filesystem authentication.
    """
    if type(before) is not FinancialCheckpointV3:
        raise SimInputError("independent typed financial checkpoint required")
    path = _safe_path(path, must_exist=True)
    owner = config["financial_account"]
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        reader = SimFinancialJournalV3(
            connection,
            path,
            identity,
            owner_id=owner["owner_id"],
            account_id=owner["account_id"],
            allowed_quantity_steps=tuple(Decimal(s) for s in owner["allowed_quantity_steps"]),
            **config["storage"],
        )
        current = reader._checkpoint(reader._audit() if trusted_current is None else reader._current())
        if trusted_current is not None and current != trusted_current:
            raise SimInputError("financial head changed after owned guarded snapshot")
        if (before.identity_sha256, before.owner_id, before.account_id) != (
            current.identity_sha256,
            current.owner_id,
            current.account_id,
        ):
            raise SimInputError("financial checkpoint identity/owner conflict")
        if before.version:
            row = connection.execute("SELECT * FROM events WHERE version=?", (before.version,)).fetchone()
            prefix = (
                None
                if row is None
                else FinancialCheckpointV3(
                    current.identity_sha256,
                    current.owner_id,
                    current.account_id,
                    row["version"],
                    row["state_hash"],
                    row["event_hash"],
                    row["clock_ms"],
                    row["source_cursor"],
                    row["native_count"],
                    row["native_head"],
                )
            )
        else:
            metadata = reader._check_storage()
            initial = json.loads(metadata["initial_state_json"])
            ref = decode_account_core(initial["account"])[1]
            prefix = FinancialCheckpointV3(
                current.identity_sha256,
                current.owner_id,
                current.account_id,
                0,
                metadata["initial_state_hash"],
                metadata["genesis_hash"],
                int(metadata["initial_clock_ms"]),
                initial["cursor"],
                ref.event_count,
                ref.head_sha256,
            )
        if prefix != before:
            raise SimInputError("financial independently held before prefix differs")
        if current == before:
            return before
        if expected_event is None or current.version != before.version + 1:
            raise SimInputError("financial journal advanced outside one independently anchored pending event")
        row = connection.execute("SELECT * FROM events WHERE version=?", (current.version,)).fetchone()
        payload = expected_event["payload"]
        cursor = before.source_cursor
        if payload.get("kind") == "SOURCE_BATCH":
            if (
                type(payload.get("first")) is not int
                or type(payload.get("last")) is not int
                or payload["first"] != cursor + 1
            ):
                raise SimInputError("financial pending source prefix differs")
            cursor = payload["last"]
        if (
            row is None
            or row["previous_hash"] != before.head_hash
            or row["event_hash"] != current.head_hash
            or row["state_hash"] != current.state_hash
            or row["clock_ms"] != current.last_clock_ms
            or row["clock_ms"] != payload["at"]
            or row["event_id"] != expected_event["event_id"]
            or row["payload_json"] != _canonical(payload)
            or current.source_cursor != cursor
            or row["native_count"] != current.native_count
            or row["native_head"] != current.native_head
        ):
            raise SimInputError("newer financial event is not the EXACT recorded pending operation")
        return current


class FourArmDriverV3:
    def __init__(self, directory, prepared, journal, accounts, *, driver_checkpoint=None):
        self.directory = Path(directory)
        self.prepared, self.journal, self.accounts = prepared, journal, accounts
        self._prepared_pending = None
        # Own append results, not later snapshots, advance this local fence.
        self._driver_checkpoint = driver_checkpoint or journal._retained_checkpoint
        if self.financial:
            self._assert_driver_head()

    @staticmethod
    def _refresh(prepared):
        refreshed = preflight_four_arm_v3(
            prepared.inputs,
            prepared.seal,
            account_profile=prepared.account_profile,
            account_storage=None
            if prepared.account_profile == LEGACY_PROFILE
            else dict(prepared.account_storage),
            **(
                {"compact_storage": _compact_limits(prepared)}
                if prepared.account_profile == COMPACT_FINANCIAL_PROFILE
                else {}
            ),
        )
        if prepared.account_profile in {FINANCIAL_PROFILE, COMPACT_FINANCIAL_PROFILE} and (
            _canonical(prepared.operations) != _canonical(refreshed.operations)
            or _canonical(prepared.routing) != _canonical(refreshed.routing)
            or prepared.compact_config_hashes != refreshed.compact_config_hashes
        ):
            raise SimInputError("prepared financial schedule/routing drift")
        return refreshed

    @property
    def financial(self):
        return self.prepared.account_profile in {FINANCIAL_PROFILE, COMPACT_FINANCIAL_PROFILE}

    @staticmethod
    def _identity(prepared):
        return JournalIdentity(
            prepared.seal.experiment_id, "four-arm-driver", prepared.identity_sha256, prepared.identity_sha256
        )

    @classmethod
    def create(cls, directory, prepared):
        if cls is FourArmDriverV3 and prepared.account_profile == COMPACT_FINANCIAL_PROFILE:
            return CompactFourArmDriverV3.create(directory, prepared)
        # Revalidate mutable external producer/model containers before writes.
        refreshed = cls._refresh(prepared)
        if refreshed.identity_sha256 != prepared.identity_sha256:
            raise SimInputError("prepared identity drift")
        directory = Path(directory).resolve()
        if directory.exists():
            raise SimInputError("create-only new output directory required; no old account adoption")
        directory.mkdir(parents=False)
        accounts = {}
        journal = None
        try:
            inputs = prepared.inputs
            seal_sha = next(iter(prepared.producer_snapshots.values())).seal_sha256
            for arm in ARMS:
                accounts[arm] = _consumer(prepared.account_profile).create(
                    directory / f"{arm}.sqlite3",
                    **(
                        {}
                        if prepared.account_profile == LEGACY_PROFILE
                        else {
                            "owner_id": prepared.seal.experiment_id,
                            "account_id": arm,
                            **dict(prepared.account_storage),
                        }
                    ),
                    campaign_id=prepared.seal.experiment_id,
                    arm_id=arm,
                    binding=inputs.binding,
                    models=inputs.models,
                    rules=inputs.rules,
                    funding_schedule=inputs.funding_schedule,
                    horizon=prepared.seal.horizon,
                    initial_equity=inputs.initial_equity,
                    hypothesis_seal_sha256=seal_sha,
                    candle_originals=inputs.candle_originals,
                    allowed_origins=ORIGINS[arm],
                    no_route_driver_seal_sha256=prepared.identity_sha256,
                    expected_cost_ids=tuple(
                        sorted(
                            [a.cost_id for a in inputs.attempts if arm in a.consumer_arms]
                            + [c.cost_id for c in inputs.shared_expenses if arm in c.consumer_arms]
                        )
                    ),
                )
            state = {
                "identity": prepared.identity_sha256,
                "cursor": 0,
                "pending": None,
                "routes": {},
                "cells": {},
                "costs": {},
                "finished": False,
                "account_config": {a: p.config for a, p in accounts.items()},
                "account_identity": {a: _plain(p.journal.identity) for a, p in accounts.items()},
                "account_checkpoints": {a: _plain(p.journal.checkpoint()) for a, p in accounts.items()},
                "report": None,
            }
            journal = cls._new_driver_journal(
                directory / "driver.sqlite3",
                prepared=prepared,
                identity=cls._identity(prepared),
                initial_state=state,
                initial_clock_ms=prepared.seal.horizon.data_start_ms,
            )
            return cls(directory, prepared, journal, accounts)
        except BaseException:
            for account in accounts.values():
                account.close()
            if journal is not None:
                journal.close()
            # Deliberately retain partial output; never repair/adopt/delete it.
            raise

    @classmethod
    def _new_driver_journal(cls, path, *, prepared, **kwargs):
        return SimDeltaJournalV3.create(path, **kwargs)

    @classmethod
    def open(cls, directory, prepared, expected_checkpoint, *, expected_commit_plan=None):
        if prepared.account_profile == COMPACT_FINANCIAL_PROFILE:
            return CompactFourArmDriverV3.open(
                directory, prepared, expected_checkpoint, expected_commit_plan=expected_commit_plan
            )
        if expected_commit_plan is not None:
            raise SimInputError("compact commit plan cannot open an old driver profile")
        refreshed = cls._refresh(prepared)
        if (
            type(expected_checkpoint) is not FourArmCheckpointV3
            or refreshed.identity_sha256 != expected_checkpoint.identity_sha256
            or prepared.identity_sha256 != refreshed.identity_sha256
            or tuple((p.producer_id, p.checkpoint) for p in prepared.inputs.producers)
            != expected_checkpoint.producer_checkpoints
            or tuple(a for a, _ in expected_checkpoint.arm_checkpoints) != ARMS
        ):
            raise SimInputError("independent driver/producer checkpoint or immutable inputs changed")
        directory = Path(directory).resolve()
        pending = expected_checkpoint.pending_operation
        financial = prepared.account_profile == FINANCIAL_PROFILE
        if financial:
            _clock(expected_checkpoint.operation_cursor)
            if expected_checkpoint.operation_cursor > len(prepared.operations):
                raise SimInputError("independent operation cursor outside sealed schedule")
            pending = None if pending is None else json.loads(_canonical(pending))
        phase = expected_checkpoint.checkpoint_phase
        if phase not in ({"PREPARED_INTENT", "INTENT_COMMITTED"} if financial else {"INTENT_COMMITTED"}):
            raise SimInputError("unknown independent checkpoint phase")
        prepared_intent = financial and phase == "PREPARED_INTENT"
        if prepared_intent and pending is None:
            raise SimInputError("prepared intent requires exact pending operation")
        if (
            None if pending is None else digest(pending if financial else pending["operation"])
        ) != expected_checkpoint.pending_operation_sha256:
            raise SimInputError("independent pending operation commitment changed")
        if financial and pending is not None:
            if (
                expected_checkpoint.operation_cursor >= len(prepared.operations)
                or set(pending) != {"operation", "before", "effects"}
                or set(pending["before"]) != set(ARMS)
                or set(pending["effects"]) != set(ARMS)
                or _canonical(pending["operation"])
                != _canonical(prepared.operations[expected_checkpoint.operation_cursor])
            ):
                raise SimInputError("independent financial pending WAL differs from sealed schedule")
        expected_commit = (
            None
            if pending is None
            else {
                "event_id": (
                    f"operation:{expected_checkpoint.operation_cursor}:"
                    f"{'intent' if prepared_intent else 'commit'}"
                ),
                "payload": (
                    {"pending": pending}
                    if prepared_intent
                    else {
                        "operation": pending["operation"],
                        **({"pending_sha256": digest(pending)} if financial else {}),
                    }
                ),
                **({"at_ms": pending["operation"]["at"]} if financial else {}),
            }
        )
        driver_checkpoint = _anchored_checkpoint(
            directory / "driver.sqlite3", expected_checkpoint.driver_checkpoint, expected_commit
        )
        journal = SimDeltaJournalV3.open(
            directory / "driver.sqlite3",
            identity=cls._identity(prepared),
            expected_checkpoint=driver_checkpoint,
        )
        state = journal.snapshot().state
        committed_pending = driver_checkpoint != expected_checkpoint.driver_checkpoint
        if prepared_intent:
            valid_state = state["cursor"] == expected_checkpoint.operation_cursor and _canonical(
                state["pending"]
            ) == _canonical(pending if committed_pending else None)
        else:
            valid_state = not (
                (
                    not committed_pending
                    and (
                        state["cursor"] != expected_checkpoint.operation_cursor or state["pending"] != pending
                    )
                )
                or (
                    committed_pending
                    and (
                        state["cursor"] != expected_checkpoint.operation_cursor + 1
                        or state["pending"] is not None
                    )
                )
            )
        if not valid_state:
            journal.close()
            raise SimInputError("resume requires exact independent driver pending-operation checkpoint")
        accounts = {}
        try:
            for arm, checkpoint in expected_checkpoint.arm_checkpoints:
                anchor = _anchored_financial_checkpoint if financial else _anchored_checkpoint
                arguments = (
                    {}
                    if not financial
                    else {
                        "identity": JournalIdentity(**state["account_identity"][arm]),
                        "config": state["account_config"][arm],
                    }
                )
                effect = None if pending is None or prepared_intent else pending["effects"].get(arm)
                current_checkpoint = anchor(
                    directory / f"{arm}.sqlite3",
                    checkpoint,
                    effect,
                    **arguments,
                )
                if pending is not None:
                    anchored = anchor(
                        directory / f"{arm}.sqlite3",
                        (FinancialCheckpointV3 if financial else DeltaCheckpointV3)(**pending["before"][arm]),
                        effect,
                        **arguments,
                    )
                    if anchored != current_checkpoint:
                        raise SimInputError(
                            "external account head is not the pending operation's exact transition"
                        )
                accounts[arm] = _consumer(prepared.account_profile).open(
                    directory / f"{arm}.sqlite3",
                    identity=JournalIdentity(**state["account_identity"][arm]),
                    expected_checkpoint=current_checkpoint,
                    binding=prepared.inputs.binding,
                    models=prepared.inputs.models,
                    rules=prepared.inputs.rules,
                    funding_schedule=prepared.inputs.funding_schedule,
                    config=state["account_config"][arm],
                    candle_originals=prepared.inputs.candle_originals,
                )
                current = _plain(accounts[arm].journal.checkpoint())
                if committed_pending and not prepared_intent and current != state["account_checkpoints"][arm]:
                    raise SimInputError("recorded driver commit differs from anchored account event")
                if (prepared_intent or not committed_pending and pending is None) and current != state[
                    "account_checkpoints"
                ][arm]:
                    raise SimInputError("account advanced outside recorded driver operation")
            result = cls(directory, prepared, journal, accounts, driver_checkpoint=driver_checkpoint)
            if prepared_intent and not committed_pending:
                result._prepared_pending = pending
            return result
        except BaseException:
            for account in accounts.values():
                account.close()
            journal.close()
            raise

    def close(self):
        for account in self.accounts.values():
            account.close()
        self.journal.close()

    def checkpoint(self):
        if self.financial:
            self._assert_driver_head()
        state = self.journal.snapshot().state
        self._assert_account_heads(state)
        pending = state["pending"] if self._prepared_pending is None else self._prepared_pending
        checkpoint = FourArmCheckpointV3(
            self.prepared.identity_sha256,
            self._driver_checkpoint if self.financial else self.journal.checkpoint(),
            tuple((a, p.journal.checkpoint()) for a, p in sorted(self.accounts.items())),
            tuple((p.producer_id, p.checkpoint) for p in self.prepared.inputs.producers),
            state["cursor"],
            None if pending is None else digest(pending if self.financial else pending["operation"]),
            pending,
            "PREPARED_INTENT" if self._prepared_pending is not None else "INTENT_COMMITTED",
        )
        if self.financial:
            self._assert_driver_head()
        return checkpoint

    def _append(self, event_id, payload, state, at):
        if self.financial:
            self._assert_driver_head()
        snapshot = self.journal.snapshot()
        if self.financial:
            self._assert_account_heads(snapshot.state)
        fence = self._driver_checkpoint if self.financial else snapshot
        result = self.journal.append(
            event_id=event_id,
            payload=payload,
            outcome={"status": "RECORDED"},
            state=state,
            expected_version=fence.version,
            expected_state_hash=fence.state_hash,
            expected_head_sha256=fence.head_hash,
            at_ms=at,
        )
        if self.financial:
            if result.replayed or result.snapshot.version != fence.version + 1:
                raise SimInputError("driver append was not an exact fresh owned transition")
            own = result.snapshot
            self._driver_checkpoint = DeltaCheckpointV3(
                self._driver_checkpoint.identity_sha256,
                own.version,
                own.state_hash,
                own.head_hash,
                own.last_clock_ms,
            )
        return result

    def _assert_driver_head(self):
        if (
            type(self._driver_checkpoint) is not DeltaCheckpointV3
            or self.journal.checkpoint() != self._driver_checkpoint
        ):
            raise SimInputError("driver advanced outside its exact retained own-commit checkpoint")

    def _assert_producers(self):
        for producer in self.prepared.inputs.producers:
            if producer.journal.snapshot().checkpoint != producer.checkpoint:
                raise SimInputError("independently frozen producer changed during replay")

    def _assert_account_heads(self, state):
        """Fence the independently committed heads BEFORE scheduling mutations.

        A live object is not permission to adopt an account advanced outside
        this driver. While an intent is pending, only its exact single effect
        may have committed; the same anchor is checked before and after replay.
        """
        if set(self.accounts) != set(ARMS) or set(state["account_checkpoints"]) != set(ARMS):
            raise SimInputError("exact enrolled account checkpoint roster required")
        if state["pending"] is not None:
            self._verify_effects(state["pending"])
            return
        for arm, account in self.accounts.items():
            if _plain(account.journal.checkpoint()) != state["account_checkpoints"][arm]:
                raise SimInputError("account advanced outside recorded driver operation")

    def _cell_receipt(self, cell, arm, at):
        facts = self.prepared.cell_facts[cell.key]
        related = facts["routes"][arm]
        status = (
            "UNAVAILABLE"
            if cell.coverage == "UNAVAILABLE"
            or arm in facts["unavailable"]
            or any(r["coverage"] == "UNAVAILABLE" for r in related)
            else "CANDIDATE"
            if any(r["disposition"] == "ROUTE" for r in related)
            else "NO_ROUTE"
            if related
            else "QUIET"
        )
        return {
            "status": status,
            "source": cell.source_sha256,
            "native_routes": [r["native_key"] for r in related],
            "at": at,
        }

    def _no_route_records(self, cell, arm):
        reasons = {
            "INACTIVE_ORIGIN": "ORIGIN_NOT_ROUTED",
            "DIRECTION_CONFLICT": "ARBITRATION_CONFLICT",
            "TECHNICAL_FIRST_NO_PROPOSAL_FALLBACK": "TECHNICAL_PRIORITY",
        }
        return tuple(
            sorted(
                (
                    NoRouteDecisionV3(
                        r["parent"],
                        r["symbol"],
                        r["origin"],
                        r["at"],
                        r["producer_seal"],
                        r["producer_head"],
                        r["receipt_sequence"],
                        r["receipt"],
                        r["native_receipt_sha256"],
                        r["plan"],
                        r["native_reason"],
                        reasons[r["reason"]],
                        self.prepared.identity_sha256,
                    )
                    for r in self.prepared.cell_facts[cell.key]["routes"][arm]
                ),
                key=lambda r: r.parent_id,
            )
        )

    def _effects(self, operation):
        """Full expected account events are committed BEFORE touching accounts."""
        inputs, kind, at = self.prepared.inputs, operation["kind"], operation["at"]
        effects = {a: None for a in ARMS}
        if kind == "SOURCE":
            payload = {
                "kind": "SOURCE_BATCH",
                "first": operation["first"],
                "last": operation["last"],
                "original_prefix": digest(
                    [_input_doc(i) for i in inputs.binding.inputs[operation["first"] - 1 : operation["last"]]]
                ),
                "at": at,
            }
            effect = {
                "event_id": f"source-batch:{operation['first']}:{operation['last']}",
                "payload": payload,
            }
            return {a: effect for a in ARMS}
        if kind in {"ATTEMPT", "EXPENSE"}:
            value = (
                inputs.attempts[operation["index"]]
                if kind == "ATTEMPT"
                else inputs.shared_expenses[operation["index"]]
            )
            amount = (
                (
                    None
                    if value.attempt is None or value.attempt.cost_usd is None
                    else Decimal(str(value.attempt.cost_usd))
                )
                if kind == "ATTEMPT"
                else value.amount_usd
            )
            source = digest(_plain(value)) if kind == "ATTEMPT" else value.source_sha256
            effect = (
                {
                    "event_id": f"unknown-service:{value.cost_id}",
                    "payload": {"cost": value.cost_id, "source": source, "at": at},
                }
                if amount is None
                else {"event_id": f"cost:{value.cost_id}", "payload": {"amount": str(amount), "at": at}}
            )
            effects.update({a: effect for a in value.consumer_arms})
        elif kind == "ROUTE":
            route = self.prepared.routing[operation["index"]]
            if route["disposition"] == "ROUTE":
                native = inputs.native_routes[operation["index"]]
                group = self.prepared.groups[
                    native.producer_id, native.receipt.arm_id, native.receipt.parent_id
                ]
                from .continuous_sim import _candidate

                candidate = native.receipt.evaluation.candidate
                effects[route["arm"]] = {
                    "event_id": f"v3-intake:{route['parent']}",
                    "payload": {
                        "parent": route["parent"],
                        "candidate": None
                        if candidate is None
                        else _candidate(candidate)["exact_original_sha256"],
                        "evaluation": native.receipt.evaluation.sha256,
                        "issue": route["receipt"],
                        "head": route["producer_head"],
                        "at": at,
                        "producer_contract": "V3",
                        "producer_seal": route["producer_seal"],
                        "receipt_sequence": route["receipt_sequence"],
                        "parent_plan": digest(asdict(group.plan)),
                    },
                }
        elif kind == "CELL":
            cell = inputs.minute_cells[operation["index"]]
            for arm, account in self.accounts.items():
                receipt = self._cell_receipt(cell, arm, at)
                if receipt["status"] == "NO_ROUTE":
                    event_id, payload = account.no_route_event(
                        cells=((cell.symbol, cell.minute_ms),),
                        decisions=self._no_route_records(cell, arm),
                        source_sha256=digest(receipt),
                        at_ms=at,
                    )
                    effects[arm] = {"event_id": event_id, "payload": _plain(payload)}
                elif receipt["status"] != "CANDIDATE" and cell.key not in account.snapshot().state["slots"]:
                    cells = ((cell.symbol, cell.minute_ms, receipt["status"]),)
                    effects[arm] = {
                        "event_id": f"slots-batch:{digest(cells)}",
                        "payload": _plain(
                            {"kind": "DENOMINATOR_BATCH", "cells": cells, "source": digest(receipt), "at": at}
                        ),
                    }
        elif kind == "FINISH":
            effects = {
                a: {"event_id": "four-arm:finish", "payload": {"kind": "FINISH", "at": at}} for a in ARMS
            }
        return effects

    def _verify_effects(self, pending, *, completed=False):
        for arm, account in self.accounts.items():
            checkpoint = account.journal.checkpoint()
            before = (FinancialCheckpointV3 if self.financial else DeltaCheckpointV3)(
                **pending["before"][arm]
            )
            if self.financial:
                current = _anchored_financial_checkpoint(
                    account.path,
                    before,
                    pending["effects"][arm],
                    identity=account.journal.identity,
                    config=account.config,
                    trusted_current=checkpoint,
                )
            else:
                current = _anchored_checkpoint(account.path, before, pending["effects"][arm])
            if current != checkpoint:
                raise SimInputError("account does not match exact independently anchored pending effect")
            if (
                self.financial
                and completed
                and current.version != (before.version + (pending["effects"][arm] is not None))
            ):
                raise SimInputError("missing exact completed financial account effect")

    def _execute(self, operation, state):
        inputs, at = self.prepared.inputs, operation["at"]
        kind = operation["kind"]
        if kind == "SOURCE":
            for account in self.accounts.values():
                account.ingest_batch(first_sequence=operation["first"], last_sequence=operation["last"])
        elif kind in {"ATTEMPT", "EXPENSE"}:
            if kind == "ATTEMPT":
                value = inputs.attempts[operation["index"]]
                amount = (
                    None
                    if value.attempt is None or value.attempt.cost_usd is None
                    else Decimal(str(value.attempt.cost_usd))
                )
                cost_id, consumers, source = value.cost_id, value.consumer_arms, digest(_plain(value))
            else:
                value = inputs.shared_expenses[operation["index"]]
                amount, cost_id, consumers, source = (
                    value.amount_usd,
                    value.cost_id,
                    value.consumer_arms,
                    value.source_sha256,
                )
            for arm in consumers:
                if amount is None:
                    self.accounts[arm].record_unknown_service(cost_id=cost_id, source_sha256=source, at_ms=at)
                else:
                    self.accounts[arm].debit_service(cost_id=cost_id, amount=amount, at_ms=at)
            state["costs"][cost_id] = {
                "at": at,
                "amount": None if amount is None else str(amount),
                "consumers": list(consumers),
                "source": source,
                "attempt_status": (
                    None
                    if kind == "EXPENSE"
                    else "MISSING"
                    if value.attempt is None
                    else value.attempt.status
                ),
                "no_call_reason": None
                if kind == "EXPENSE" or value.attempt is None
                else value.attempt.no_call_reason,
            }
        elif kind == "ROUTE":
            route = self.prepared.routing[operation["index"]]
            if route["disposition"] == "ROUTE":
                native = inputs.native_routes[operation["index"]]
                producer = next(p for p in inputs.producers if p.producer_id == native.producer_id)
                result = self.accounts[route["arm"]].intake_v3(
                    hypothesis_journal=producer.journal,
                    receipt=native.receipt,
                    expected_hypothesis_head_sha256=producer.checkpoint.head_sha256,
                    at_ms=at,
                )
                state["routes"][route["native_key"]] = route | {"account_outcome": result.outcome}
            else:
                # Explicit native provenance survives even for inactive/tail
                # origins. No synthetic intake and no false QUIET substitution.
                state["routes"][route["native_key"]] = route
        elif kind == "CELL":
            cell = inputs.minute_cells[operation["index"]]
            statuses = {}
            for arm, account in self.accounts.items():
                receipt = self._cell_receipt(cell, arm, at)
                status = receipt["status"]
                if status == "CANDIDATE":
                    actual = account.snapshot().state["slots"].get(cell.key)
                    if actual is None or actual["status"] != "CANDIDATE":
                        raise SimInputError("denominator candidate has no exact durable native intake")
                elif status == "NO_ROUTE":
                    account.record_no_route_cells(
                        cells=((cell.symbol, cell.minute_ms),),
                        decisions=self._no_route_records(cell, arm),
                        source_sha256=digest(receipt),
                        at_ms=at,
                    )
                else:
                    actual = account.snapshot().state["slots"].get(cell.key)
                    if actual is None:
                        account.record_slots_batch(
                            cells=((cell.symbol, cell.minute_ms, status),),
                            source_sha256=digest(receipt),
                            at_ms=at,
                        )
                    else:
                        expected_recorded = {
                            "status": status,
                            "source": digest(receipt),
                            "parents": [],
                        }
                        if actual == expected_recorded:
                            pass
                        elif status == "UNAVAILABLE":
                            # A native intake may have committed before its
                            # unavailable evaluation became the denominator.
                            # Adopt only the exact candidate record derivable
                            # from this driver's already-committed ROUTE rows.
                            routes = sorted(
                                (
                                    route
                                    for route in state["routes"].values()
                                    if route["arm"] == arm
                                    and route["slot"] == cell.key
                                    and route["disposition"] == "ROUTE"
                                ),
                                key=lambda route: (route["at"], route["native_key"]),
                            )
                            expected_candidate = None
                            if routes:
                                expected_candidate = {
                                    "status": "CANDIDATE",
                                    "source": routes[0]["producer_head"],
                                    "parents": [route["parent"] for route in routes],
                                    "coverage": (
                                        "UNAVAILABLE"
                                        if any(route["coverage"] != "AVAILABLE" for route in routes)
                                        else "AVAILABLE"
                                    ),
                                }
                            if actual != expected_candidate:
                                raise SimInputError("driver denominator conflicts with existing native cell")
                        else:
                            raise SimInputError("driver denominator conflicts with existing native cell")
                statuses[arm] = status
            state["cells"][cell.key] = {"source": cell.source_sha256, "at": at, "arms": statuses}
        elif kind == "FINISH":
            results = {}
            for arm, account in self.accounts.items():
                actual = account.snapshot().state
                if (
                    actual["cursor"] != len(inputs.binding.inputs)
                    or tuple(sorted(actual["parents"])) != self.prepared.expected_parents[arm]
                ):
                    raise SimInputError("full source/routed-parent reconciliation failed")
                results[arm] = account.finish(now_ms=at, event_id="four-arm:finish").outcome
            expected_cells = {c.key for c in inputs.minute_cells}
            if set(state["cells"]) != expected_cells:
                raise SimInputError("complete matched four-arm 36,000-cell coverage required")
            fixture = inputs.binding.evidence_kind == "TEST_FIXTURE"
            for arm in ARMS:
                if arm in self.prepared.budget_blocked or any(
                    c["arms"][arm] == "UNAVAILABLE" for c in state["cells"].values()
                ):
                    results[arm] = results[arm] | {
                        "status": "UNRESOLVED",
                        "net_return": None,
                        "driver_evidence_unavailable": True,
                    }
            complete = all(r["status"] == "COMPLETE" for r in results.values())
            # No typed accepted originals/funding/provider admission exists in
            # this driver yet. Never upgrade hashes or fixture outcomes.
            state["report"] = {
                "schema": SCHEMA,
                "status": "FIXTURE_MECHANICS_COMPLETE" if fixture and complete else "UNRESOLVED",
                "arms": results,
                "denominator_cells_per_arm": 36_000,
                "source_items_per_arm": len(inputs.binding.inputs),
                "physical_known_spend_usd": str(
                    sum(Decimal(c["amount"]) for c in state["costs"].values() if c["amount"] is not None)
                ),
                "physical_unknown_expenses": sorted(
                    k for k, c in state["costs"].items() if c["amount"] is None
                ),
                "modeled_arm_expenses_usd": {
                    a: str(
                        sum(
                            Decimal(c["amount"])
                            for c in state["costs"].values()
                            if a in c["consumers"] and c["amount"] is not None
                        )
                    )
                    for a in ARMS
                },
                "route_dispositions": {
                    a: {
                        s: sum(r["arm"] == a and r["disposition"] == s for r in state["routes"].values())
                        for s in ("ROUTE", "NO_ROUTE", "UNAVAILABLE")
                    }
                    for a in ARMS
                },
                "all_in_net": {a: None for a in ARMS},
                "paired_net_deltas": None,
                "winner": None,
                "selection": "REFUSED_FIXTURE_NOT_ECONOMIC_EVIDENCE"
                if fixture
                else "REFUSED_SOURCE_FUNDING_PROVIDER_ADMISSION_MISSING",
                "combined_semantics": COMBINED,
                "static_combined_equivalent": False,
                "accepted_historical_inputs": False,
                "funding_admission": False,
                "source_authentication": False,
                "execution_qualified": False,
                "full_five_day_execution_verified": complete,
                "strategy_policy": "REJECT_ALL",
                "trading_authority": "NONE",
            }
            state["finished"] = True
        else:
            raise SimInputError("unknown fixed driver operation")

    def step(self, *, maximum_operations=1, checkpoint_sink=None):
        """Advance the sealed schedule.

        FINANCIAL_V3 requires a trusted durable checkpoint sink returning True
        exactly. The ACK is a caller durability contract, not proof of fsync or
        authentication. PREPARED_INTENT licenses only one exact driver intent;
        INTENT_COMMITTED licenses its recorded account effects and commit.
        A sink exception/False/None before either boundary stops all effects.
        """
        if type(maximum_operations) is not int or not 1 <= maximum_operations <= 1000:
            raise SimInputError("bounded explicit operation count required")
        if self.financial and not callable(checkpoint_sink):
            raise SimInputError("financial mode requires a trusted durable checkpoint sink ACK")

        def acknowledge(checkpoint):
            if self.financial:
                # Keep the exact planned WAL independent of mutable sink code.
                retained = replace(
                    checkpoint,
                    pending_operation=None
                    if checkpoint.pending_operation is None
                    else json.loads(_canonical(checkpoint.pending_operation)),
                )
                if checkpoint_sink(retained) is not True:
                    raise SimInputError("durable checkpoint sink must ACK True exactly")
            elif checkpoint_sink is not None:
                checkpoint_sink(checkpoint)

        self._assert_producers()
        for _ in range(maximum_operations):
            if self.financial:
                self._assert_driver_head()
            state = json.loads(json.dumps(self.journal.snapshot().state))
            self._assert_account_heads(state)
            if state["finished"]:
                break
            index = state["cursor"]
            operation = self.prepared.operations[index]
            event_key = f"operation:{index}"
            if state["pending"] is None:
                pending = {
                    "operation": operation,
                    "before": {a: _plain(p.journal.checkpoint()) for a, p in self.accounts.items()},
                    "effects": self._effects(operation),
                }
                if self.financial:
                    pending = json.loads(_canonical(pending))
                    if self._prepared_pending is not None and _canonical(
                        self._prepared_pending
                    ) != _canonical(pending):
                        raise SimInputError("recovered prepared intent differs from exact planned WAL")
                    planned = replace(
                        self.checkpoint(),
                        pending_operation=pending,
                        pending_operation_sha256=digest(pending),
                        checkpoint_phase="PREPARED_INTENT",
                    )
                    acknowledge(planned)  # BEFORE any driver/account mutation.
                state["pending"] = pending
                self._append(
                    f"{event_key}:intent",
                    {"pending": pending} if self.financial else {"operation": operation},
                    state,
                    operation["at"],
                )
                self._prepared_pending = None
                state = json.loads(json.dumps(self.journal.snapshot().state))
                acknowledge(self.checkpoint())
            elif state["pending"]["operation"] != operation:
                raise SimInputError("immutable pending operation differs from fixed schedule")
            elif self.financial:
                acknowledge(self.checkpoint())  # Re-authorize effects after an earlier sink failure.
            if self.financial:
                # The sink is external code and may have advanced either
                # journal after the INTENT checkpoint was acknowledged.
                self._assert_driver_head()
                self._assert_account_heads(state)
            self._execute(operation, state)
            self._verify_effects(state["pending"], completed=self.financial)
            state["cursor"] += 1
            pending_hash = digest(state["pending"])
            state["pending"] = None
            state["account_checkpoints"] = {
                a: _plain(p.journal.checkpoint()) for a, p in self.accounts.items()
            }
            self._append(
                f"{event_key}:commit",
                {"operation": operation, **({"pending_sha256": pending_hash} if self.financial else {})},
                state,
                operation["at"],
            )
            acknowledge(self.checkpoint())
        return self.checkpoint()

    def finish(self):
        state = self.journal.snapshot().state
        if not state["finished"]:
            raise SimInputError("complete the chronological fixed operation schedule before reporting")
        return state["report"]


def _compact_limits(prepared):
    from .compact_four_arm_driver_journal_v3 import CompactDriverLimitsV3

    values = dict(prepared.compact_storage)
    if tuple(sorted(values.items())) != prepared.compact_storage:
        raise SimInputError("exact sealed compact storage roster required")
    try:
        return CompactDriverLimitsV3(**values)
    except TypeError as error:
        raise SimInputError("closed compact driver resource profile required") from error


@dataclass(frozen=True)
class CompactCommitPlanV3:
    """Separate caller-retained plan; NOT embedded in the old closed WAL codec."""

    identity_sha256: str
    expected_before: DeltaCheckpointV3
    expected_event_id: str
    expected_payload: dict
    expected_at_ms: int
    expected_outcome: dict
    expected_hot_state: dict
    expected_cold_records: tuple

    def arguments(self):
        document = _plain(self)
        document.pop("identity_sha256")
        document["expected_before"] = DeltaCheckpointV3(**document["expected_before"])
        from .compact_four_arm_driver_journal_v3 import ColdHistoryRecordV3

        document["expected_cold_records"] = tuple(
            ColdHistoryRecordV3(**value) for value in document["expected_cold_records"]
        )
        return document


def compact_commit_plan_document(plan):
    if type(plan) is not CompactCommitPlanV3 or type(plan.expected_before) is not DeltaCheckpointV3:
        raise SimInputError("independent typed compact COMMIT plan required")
    _sha(plan.identity_sha256)
    _clock(plan.expected_at_ms)
    document = _plain(plan)
    _canonical(document)
    return document


def compact_commit_plan_from_document(document):
    from .compact_four_arm_driver_journal_v3 import ColdHistoryRecordV3

    if type(document) is not dict or set(document) != set(CompactCommitPlanV3.__dataclass_fields__):
        raise SimInputError("closed externally retained compact plan document required")
    values = json.loads(_canonical(document))
    values["expected_before"] = DeltaCheckpointV3(**values["expected_before"])
    values["expected_cold_records"] = tuple(ColdHistoryRecordV3(**r) for r in values["expected_cold_records"])
    plan = CompactCommitPlanV3(**values)
    if compact_commit_plan_document(plan) != document:
        raise SimInputError("compact plan changed during exact decode")
    return plan


class CompactFourArmDriverV3(FourArmDriverV3):
    """Explicit indexed driver only; financial reducer and denominator unchanged.

    checkpoint_sink retains the original four-arm WAL phases. In addition,
    commit_plan_sink must durably ACK the exact completed receipts BEFORE the
    driver COMMIT. True is a trusted caller durability contract, not proof of
    fsync/source authentication. Lost/False/None responses never license COMMIT.
    """

    def __init__(self, directory, prepared, journal, accounts, *, driver_checkpoint=None):
        if prepared.account_profile != COMPACT_FINANCIAL_PROFILE:
            raise SimInputError("explicit compact financial profile required")
        self._sealed_driver_journal = journal
        super().__init__(
            directory,
            prepared,
            journal,
            accounts,
            driver_checkpoint=driver_checkpoint or journal.checkpoint(),
        )
        self._recovery_plan = None
        self._needs_completed_ack = False
        state = journal.snapshot().state
        for arm, account in accounts.items():
            if self._config_reference(account.config) != state["account_config"][arm]:
                raise SimInputError("compact live account config differs from immutable genesis reference")

    @staticmethod
    def _identity(prepared):
        return JournalIdentity(
            prepared.seal.experiment_id,
            "compact-four-arm-driver",
            prepared.identity_sha256,
            prepared.identity_sha256,
        )

    @classmethod
    def _new_driver_journal(cls, path, *, prepared, **kwargs):
        from .compact_four_arm_driver_journal_v3 import CompactFourArmDriverJournalV3

        expected_hashes = dict(prepared.compact_config_hashes)
        if tuple(expected_hashes) != ARMS:
            raise SimInputError("sealed four-arm expected genesis config hashes required")
        state = kwargs["initial_state"]
        for arm, config in state["account_config"].items():
            if digest(config) != expected_hashes[arm]:
                raise SimInputError("created financial config differs from exact preflight config")
            state["account_config"][arm] = cls._config_reference(config)
        return CompactFourArmDriverJournalV3.create(path, limits=_compact_limits(prepared), **kwargs)

    @staticmethod
    def _config_reference(config):
        return {
            "schema": "IMMUTABLE_FINANCIAL_CONFIG_REFERENCE_V3",
            "config_sha256": digest(config),
            "financial_account": json.loads(_canonical(config["financial_account"])),
            "storage": json.loads(_canonical(config["storage"])),
        }

    @classmethod
    def _genesis_config(cls, path, descriptor, *, prepared, arm):
        if (
            type(descriptor) is not dict
            or set(descriptor) != {"schema", "config_sha256", "financial_account", "storage"}
            or descriptor["schema"] != "IMMUTABLE_FINANCIAL_CONFIG_REFERENCE_V3"
            or descriptor["config_sha256"] != dict(prepared.compact_config_hashes).get(arm)
            or type(descriptor["financial_account"]) is not dict
            or set(descriptor["financial_account"]) != {"owner_id", "account_id", "allowed_quantity_steps"}
            or descriptor["financial_account"].get("owner_id") != prepared.seal.experiment_id
            or descriptor["financial_account"].get("account_id") != arm
            or descriptor["storage"] != dict(prepared.account_storage)
        ):
            raise SimInputError(
                "compact immutable config reference differs from exact prepared financial profile"
            )
        path = _safe_path(path, must_exist=True)
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0)) as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            row = connection.execute("SELECT value FROM metadata WHERE key='initial_state_json'").fetchone()
            if row is None:
                raise SimInputError("original financial genesis config missing")
            initial = json.loads(row[0])
            config = initial.get("config")
            if type(config) is not dict or cls._config_reference(config) != descriptor:
                raise SimInputError("original financial genesis config bytes/reference conflict")
        return config

    @classmethod
    def create(cls, directory, prepared):
        if prepared.account_profile != COMPACT_FINANCIAL_PROFILE:
            raise SimInputError("compact driver cannot adopt an old prepared profile")
        return super().create(directory, prepared)

    @classmethod
    def _open_prepared_intent(cls, path, prepared, before, pending):
        from .compact_four_arm_driver_journal_v3 import CompactFourArmDriverJournalV3

        path = _safe_path(path, must_exist=True)
        limits, identity = _compact_limits(prepared), cls._identity(prepared)
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            reader = CompactFourArmDriverJournalV3(connection, path, identity, limits)
            current = reader._audit()
            authorized = reader._checkpoint(current)
            if authorized != before:
                if current.version != before.version + 1:
                    raise SimInputError("compact preintent advanced outside exactly one known intent")
                metadata = reader._check_storage()
                state = json.loads(metadata["initial_hot_json"])
                from .sim_delta_journal_v3 import apply_delta
                from .sim_state_journal import JournalSnapshot

                prefix = JournalSnapshot(
                    0,
                    state,
                    metadata["initial_hot_hash"],
                    metadata["genesis_hash"],
                    int(metadata["initial_clock_ms"]),
                )
                for row in connection.execute(
                    "SELECT * FROM events WHERE version<=? ORDER BY version", (before.version,)
                ):
                    state = apply_delta(state, json.loads(row["delta_json"]))
                    prefix = JournalSnapshot(
                        row["version"], state, row["state_hash"], row["event_hash"], row["clock_ms"]
                    )
                if reader._checkpoint(prefix) != before or state["pending"] is not None:
                    raise SimInputError("compact retained preintent prefix differs")
                row = connection.execute(
                    "SELECT * FROM events WHERE version=?", (current.version,)
                ).fetchone()
                expected = json.loads(_canonical(state))
                expected["pending"] = pending
                if (
                    row["previous_hash"] != before.head_hash
                    or row["event_id"] != f"operation:{state['cursor']}:intent"
                    or row["payload_json"] != _canonical({"pending": pending})
                    or row["outcome_json"] != _canonical({"status": "INTENT_RECORDED"})
                    or row["clock_ms"] != pending["operation"]["at"]
                    or _canonical(current.state) != _canonical(expected)
                ):
                    raise SimInputError("compact newer intent is not the exact retained preintent")
        return CompactFourArmDriverJournalV3.open(
            path, identity=identity, limits=limits, expected_checkpoint=authorized
        )

    @classmethod
    def open(cls, directory, prepared, expected_checkpoint, *, expected_commit_plan=None):
        from .compact_four_arm_driver_journal_v3 import CompactFourArmDriverJournalV3

        if prepared.account_profile != COMPACT_FINANCIAL_PROFILE:
            raise SimInputError("explicit compact profile required; no old journal adoption")
        refreshed = cls._refresh(prepared)
        if (
            type(expected_checkpoint) is not FourArmCheckpointV3
            or refreshed.identity_sha256 != prepared.identity_sha256
            or expected_checkpoint.identity_sha256 != prepared.identity_sha256
            or expected_checkpoint.producer_checkpoints
            != tuple((p.producer_id, p.checkpoint) for p in prepared.inputs.producers)
            or tuple(a for a, _ in expected_checkpoint.arm_checkpoints) != ARMS
        ):
            raise SimInputError("independent compact experiment/producer/account checkpoint changed")
        cursor = expected_checkpoint.operation_cursor
        _clock(cursor)
        if cursor > len(prepared.operations):
            raise SimInputError("compact cursor outside sealed operation schedule")
        pending = expected_checkpoint.pending_operation
        pending = None if pending is None else json.loads(_canonical(pending))
        phase = expected_checkpoint.checkpoint_phase
        if phase not in {"PREPARED_INTENT", "INTENT_COMMITTED"}:
            raise SimInputError("unknown compact WAL phase")
        if (None if pending is None else digest(pending)) != expected_checkpoint.pending_operation_sha256:
            raise SimInputError("compact whole pending commitment differs")
        if pending is not None and (
            cursor >= len(prepared.operations)
            or set(pending) != {"operation", "before", "effects"}
            or set(pending["before"]) != set(ARMS)
            or set(pending["effects"]) != set(ARMS)
            or _canonical(pending["operation"]) != _canonical(prepared.operations[cursor])
        ):
            raise SimInputError("compact retained intent differs from sealed schedule")
        if phase == "PREPARED_INTENT" and pending is None:
            raise SimInputError("compact preintent requires an exact pending operation")
        if expected_commit_plan is not None:
            expected_commit_plan = compact_commit_plan_from_document(
                compact_commit_plan_document(expected_commit_plan)
            )
            if (
                phase != "INTENT_COMMITTED"
                or pending is None
                or expected_commit_plan.identity_sha256 != prepared.identity_sha256
                or expected_commit_plan.expected_before != expected_checkpoint.driver_checkpoint
                or expected_commit_plan.expected_payload.get("pending_sha256") != digest(pending)
                or _canonical(expected_commit_plan.expected_payload.get("operation"))
                != _canonical(pending["operation"])
            ):
                raise SimInputError("externally retained compact plan differs from its exact pending WAL")
        directory = Path(directory).resolve()
        path = directory / "driver.sqlite3"
        if phase == "PREPARED_INTENT":
            journal = cls._open_prepared_intent(
                path, prepared, expected_checkpoint.driver_checkpoint, pending
            )
        else:
            try:
                journal = CompactFourArmDriverJournalV3.open(
                    path,
                    identity=cls._identity(prepared),
                    limits=_compact_limits(prepared),
                    expected_checkpoint=expected_checkpoint.driver_checkpoint,
                )
            except OptimisticConflict:
                if expected_commit_plan is None:
                    raise SimInputError(
                        "new compact COMMIT needs independently retained exact plan"
                    ) from None
                journal = CompactFourArmDriverJournalV3.open_after_known_commit(
                    path,
                    identity=cls._identity(prepared),
                    limits=_compact_limits(prepared),
                    **expected_commit_plan.arguments(),
                )
        accounts = {}
        try:
            state, driver_cp = journal.snapshot().state, journal.checkpoint()
            advanced = driver_cp != expected_checkpoint.driver_checkpoint
            expected_cursor = cursor + (advanced and phase == "INTENT_COMMITTED")
            expected_pending = (
                pending
                if phase == "INTENT_COMMITTED" and not advanced
                else (pending if phase == "PREPARED_INTENT" and advanced else None)
            )
            if state["cursor"] != expected_cursor or _canonical(state["pending"]) != _canonical(
                expected_pending
            ):
                raise SimInputError("compact driver state differs from independent retained phase")
            for arm, before in expected_checkpoint.arm_checkpoints:
                if type(before) is not FinancialCheckpointV3:
                    raise SimInputError("typed owned financial account checkpoints required")
                effect = None if pending is None or phase == "PREPARED_INTENT" else pending["effects"][arm]
                args = {
                    "identity": JournalIdentity(**state["account_identity"][arm]),
                    "config": cls._genesis_config(
                        directory / f"{arm}.sqlite3", state["account_config"][arm], prepared=prepared, arm=arm
                    ),
                }
                current = _anchored_financial_checkpoint(directory / f"{arm}.sqlite3", before, effect, **args)
                if pending is not None:
                    original = FinancialCheckpointV3(**pending["before"][arm])
                    if (
                        _anchored_financial_checkpoint(directory / f"{arm}.sqlite3", original, effect, **args)
                        != current
                    ):
                        raise SimInputError("compact account is outside exact retained pending effect")
                accounts[arm] = _consumer(prepared.account_profile).open(
                    directory / f"{arm}.sqlite3",
                    identity=args["identity"],
                    expected_checkpoint=current,
                    binding=prepared.inputs.binding,
                    models=prepared.inputs.models,
                    rules=prepared.inputs.rules,
                    funding_schedule=prepared.inputs.funding_schedule,
                    config=args["config"],
                    candle_originals=prepared.inputs.candle_originals,
                )
                if (pending is None or phase == "PREPARED_INTENT" or advanced) and _plain(current) != state[
                    "account_checkpoints"
                ][arm]:
                    raise SimInputError("compact stored account checkpoint differs from exact owned effect")
            result = cls(directory, prepared, journal, accounts, driver_checkpoint=driver_cp)
            if phase == "PREPARED_INTENT" and not advanced:
                result._prepared_pending = pending
            if not advanced:
                result._recovery_plan = expected_commit_plan
            result._needs_completed_ack = advanced and phase == "INTENT_COMMITTED"
            return result
        except BaseException:
            for account in accounts.values():
                account.close()
            journal.close()
            raise

    def _own_result(self, result, before):
        if result.replayed or result.snapshot.version != before.version + 1:
            raise SimInputError("compact driver commit must be an exact fresh owned transition")
        self._driver_checkpoint = self.journal._checkpoint(result.snapshot)

    def _assert_driver_head(self):
        if (
            self.journal is not self._sealed_driver_journal
            or self.prepared.account_profile != COMPACT_FINANCIAL_PROFILE
            or self.prepared.identity_sha256 != self.journal.identity.policy_id
            or _compact_limits(self.prepared) != self.journal.limits
        ):
            raise SimInputError("compact sealed profile/journal/resource identity drift")
        super()._assert_driver_head()

    def _cold_pages(self, collection, checkpoint):
        after = None
        while True:
            page = self.journal.page_history(collection, expected_checkpoint=checkpoint, after_key=after)
            yield from page.records
            if page.next_key is None:
                return
            after = page.next_key

    def _compact_records(self, operation, state):
        from .compact_four_arm_driver_journal_v3 import ColdHistoryRecordV3

        overlay = {**state, "routes": {}, "cells": {}, "costs": {}}
        if operation["kind"] == "FINISH":
            state["report"] = self._finish_indexed(operation)
            state["finished"] = True
        elif operation["kind"] == "CELL":
            cell, statuses = self.prepared.inputs.minute_cells[operation["index"]], {}
            pending = state["pending"]
            for arm, account in self.accounts.items():
                receipt = self._cell_receipt(cell, arm, operation["at"])
                statuses[arm] = receipt["status"]
                before = FinancialCheckpointV3(**pending["before"][arm])
                effect = pending["effects"][arm]
                if effect is not None and account.journal.checkpoint().version == before.version:
                    if receipt["status"] == "NO_ROUTE":
                        account.record_no_route_cells(
                            cells=((cell.symbol, cell.minute_ms),),
                            decisions=self._no_route_records(cell, arm),
                            source_sha256=digest(receipt),
                            at_ms=operation["at"],
                        )
                    else:
                        account.record_slots_batch(
                            cells=((cell.symbol, cell.minute_ms, receipt["status"]),),
                            source_sha256=digest(receipt),
                            at_ms=operation["at"],
                        )
                actual = account.snapshot().state["slots"].get(cell.key)
                if actual is None or not (
                    actual["status"] == receipt["status"]
                    or receipt["status"] == "UNAVAILABLE"
                    and actual["status"] == "CANDIDATE"
                ):
                    raise SimInputError("compact denominator differs from exact owned native cell")
            overlay["cells"][cell.key] = {
                "source": cell.source_sha256,
                "at": operation["at"],
                "arms": statuses,
            }
        else:
            FourArmDriverV3._execute(self, operation, overlay)
        return tuple(
            ColdHistoryRecordV3(collection, key, value)
            for collection in ("routes", "cells", "costs")
            for key, value in overlay[collection].items()
        )

    def _finish_indexed(self, operation):
        checkpoint = self._driver_checkpoint
        inputs = self.prepared.inputs
        expected_cells = {c.key: c for c in inputs.minute_cells}
        cell_clocks = {
            inputs.minute_cells[op["index"]].key: op["at"]
            for op in self.prepared.operations
            if op["kind"] == "CELL"
        }
        unavailable = set(self.prepared.budget_blocked)
        for record in self._cold_pages("cells", checkpoint):
            if record.key not in expected_cells or set(record.value["arms"]) != set(ARMS):
                raise SimInputError("indexed denominator differs from exact original complete cell roster")
            original = expected_cells.pop(record.key)
            expected_value = {
                "source": original.source_sha256,
                "at": cell_clocks[record.key],
                "arms": {a: self._cell_receipt(original, a, cell_clocks[record.key])["status"] for a in ARMS},
            }
            if _canonical(record.value) != _canonical(expected_value):
                raise SimInputError(
                    "indexed cell original/status attribution differs from sealed denominator"
                )
            unavailable.update(a for a in ARMS if record.value["arms"][a] == "UNAVAILABLE")
        if expected_cells:
            raise SimInputError("indexed denominator has missing original cells")
        known, unknown, modeled = Decimal(0), [], dict.fromkeys(ARMS, Decimal(0))
        expected_costs = {a.cost_id for a in inputs.attempts} | {c.cost_id for c in inputs.shared_expenses}
        for record in self._cold_pages("costs", checkpoint):
            if record.key not in expected_costs:
                raise SimInputError("indexed physical cost absent from sealed schedule")
            expected_costs.remove(record.key)
            cost = record.value
            if cost["amount"] is None:
                unknown.append(record.key)
            else:
                amount = Decimal(cost["amount"])
                known += amount
                for arm in cost["consumers"]:
                    modeled[arm] += amount
        if expected_costs:
            raise SimInputError("indexed physical cost originals missing from complete attribution")
        dispositions = {a: dict.fromkeys(("ROUTE", "NO_ROUTE", "UNAVAILABLE"), 0) for a in ARMS}
        expected_routes = {r["native_key"]: r for r in self.prepared.routing}
        for record in self._cold_pages("routes", checkpoint):
            route = record.value
            original = expected_routes.pop(record.key, None)
            if original is None or any(
                _canonical(route.get(k)) != _canonical(v) for k, v in original.items()
            ):
                raise SimInputError("indexed route disposition differs from sealed original native route")
            dispositions[route["arm"]][route["disposition"]] += 1
        if expected_routes:
            raise SimInputError("indexed native route originals missing from complete reconciliation")
        # This driver currently emits no shadow-slot collection. Never treat
        # unexpected retained slot originals as ignorable finish evidence.
        if any(True for _ in self._cold_pages("slots", checkpoint)):
            raise SimInputError("unexpected indexed shadow-slot receipt requires explicit reconciliation")
        self._assert_driver_head()
        results = {}
        for arm, account in self.accounts.items():
            actual = account.snapshot().state
            if (
                actual["cursor"] != len(inputs.binding.inputs)
                or tuple(sorted(actual["parents"])) != self.prepared.expected_parents[arm]
            ):
                raise SimInputError("full source/routed-parent reconciliation failed")
            result = account.finish(now_ms=operation["at"], event_id="four-arm:finish").outcome
            if arm in unavailable:
                result = result | {
                    "status": "UNRESOLVED",
                    "net_return": None,
                    "driver_evidence_unavailable": True,
                }
            results[arm] = result
        fixture = inputs.binding.evidence_kind == "TEST_FIXTURE"
        complete = all(r["status"] == "COMPLETE" for r in results.values())
        return {
            "schema": SCHEMA,
            "status": "FIXTURE_MECHANICS_COMPLETE" if fixture and complete else "UNRESOLVED",
            "arms": results,
            "denominator_cells_per_arm": 36_000,
            "source_items_per_arm": len(inputs.binding.inputs),
            "physical_known_spend_usd": str(known),
            "physical_unknown_expenses": sorted(unknown),
            "modeled_arm_expenses_usd": {a: str(modeled[a]) for a in ARMS},
            "route_dispositions": dispositions,
            "all_in_net": dict.fromkeys(ARMS),
            "paired_net_deltas": None,
            "winner": None,
            "selection": "REFUSED_FIXTURE_NOT_ECONOMIC_EVIDENCE"
            if fixture
            else "REFUSED_SOURCE_FUNDING_PROVIDER_ADMISSION_MISSING",
            "combined_semantics": COMBINED,
            "static_combined_equivalent": False,
            "accepted_historical_inputs": False,
            "funding_admission": False,
            "source_authentication": False,
            "execution_qualified": False,
            "full_five_day_execution_verified": complete,
            "strategy_policy": "REJECT_ALL",
            "trading_authority": "NONE",
        }

    def _commit_plan(self, pending, records, state):
        from .compact_four_arm_driver_journal_v3 import _cold_hash

        before = self._driver_checkpoint
        refs, staged, within = state["history_refs"], {}, 0
        for record in records:
            key = record.collection, record.key
            old = self.journal.lookup_history(*key, expected_checkpoint=before)
            encoded = _canonical(record.value)
            if old is not None or key in staged:
                if encoded != (_canonical(old.value) if old is not None else staged[key]):
                    raise SimInputError(
                        "compact original cold ID conflicts with independently retained prefix"
                    )
                continue
            within += 1
            ref = refs[key[0]]
            row = {
                "ordinal": sum(r["count"] for r in refs.values()) + 1,
                "collection": key[0],
                "collection_ordinal": ref["count"] + 1,
                "key": key[1],
                "content_hash": _hash(encoded),
                "previous_hash": ref["head"],
                "outer_version": before.version + 1,
                "within_outer": within,
            }
            row["record_hash"] = _cold_hash(row)
            refs[key[0]] = {"count": row["collection_ordinal"], "head": row["record_hash"]}
            staged[key] = encoded
        state.update(
            pending=None,
            cursor=state["cursor"] + 1,
            account_checkpoints={a: _plain(p.journal.checkpoint()) for a, p in self.accounts.items()},
        )
        payload = {
            "operation": pending["operation"],
            "pending_sha256": digest(pending),
            "account_checkpoints": state["account_checkpoints"],
            "cold_records": _plain(records),
            "report": state["report"],
        }
        return compact_commit_plan_from_document(
            compact_commit_plan_document(
                CompactCommitPlanV3(
                    self.prepared.identity_sha256,
                    before,
                    f"operation:{state['cursor'] - 1}:commit",
                    payload,
                    pending["operation"]["at"],
                    {"status": "COMMITTED", "operation_cursor": state["cursor"]},
                    state,
                    records,
                )
            )
        )

    def _commit_known_plan(self, plan):
        self._assert_driver_head()
        state = self.journal.snapshot().state
        self._assert_account_heads(state)
        if self._driver_checkpoint != plan.expected_before:
            raise SimInputError("compact driver changed during commit-plan durability ACK")
        for arm, account in self.accounts.items():
            if _plain(account.journal.checkpoint()) != plan.expected_payload["account_checkpoints"][arm]:
                raise SimInputError("account changed during compact commit-plan durability ACK")
        result = self.journal.commit_operation(
            operation=plan.expected_payload["operation"],
            pending_sha256=plan.expected_payload["pending_sha256"],
            account_checkpoints=plan.expected_payload["account_checkpoints"],
            cold_records=plan.expected_cold_records,
            at_ms=plan.expected_at_ms,
            expected_checkpoint=plan.expected_before,
            report=plan.expected_payload["report"],
        )
        if _canonical(result.snapshot.state) != _canonical(plan.expected_hot_state) or _canonical(
            result.outcome
        ) != _canonical(plan.expected_outcome):
            raise SimInputError("owned compact COMMIT differs from externally retained exact plan")
        self._own_result(result, plan.expected_before)

    def step(self, *, maximum_operations=1, checkpoint_sink=None, commit_plan_sink=None):
        if (
            type(maximum_operations) is not int
            or not 1 <= maximum_operations <= 1000
            or not callable(checkpoint_sink)
            or not callable(commit_plan_sink)
        ):
            raise SimInputError(
                "compact financial mode requires bounded operations and both durable sink ACKs"
            )

        def acknowledge(checkpoint):
            retained = replace(
                checkpoint,
                pending_operation=None
                if checkpoint.pending_operation is None
                else json.loads(_canonical(checkpoint.pending_operation)),
            )
            if checkpoint_sink(retained) is not True:
                raise SimInputError("durable checkpoint sink must ACK True exactly")

        self._assert_producers()
        if self._needs_completed_ack:
            acknowledge(self.checkpoint())
            self._assert_driver_head()
            self._needs_completed_ack = False
        for _ in range(maximum_operations):
            self._assert_driver_head()
            state = self.journal.snapshot().state
            self._assert_account_heads(state)
            if state["finished"]:
                break
            operation = self.prepared.operations[state["cursor"]]
            if state["pending"] is None:
                pending = {
                    "operation": operation,
                    "before": {a: _plain(p.journal.checkpoint()) for a, p in self.accounts.items()},
                    "effects": self._effects(operation),
                }
                pending = json.loads(_canonical(pending))
                if self._prepared_pending is not None and _canonical(self._prepared_pending) != _canonical(
                    pending
                ):
                    raise SimInputError("compact recovered preintent differs from its immutable operation")
                acknowledge(
                    replace(
                        self.checkpoint(),
                        pending_operation=pending,
                        pending_operation_sha256=digest(pending),
                        checkpoint_phase="PREPARED_INTENT",
                    )
                )
                self._assert_driver_head()
                self._assert_account_heads(state)
                before = self._driver_checkpoint
                result = self.journal.record_intent(
                    pending, at_ms=operation["at"], expected_checkpoint=before
                )
                self._own_result(result, before)
                self._prepared_pending = None
                state = self.journal.snapshot().state
                acknowledge(self.checkpoint())
            else:
                if _canonical(state["pending"]["operation"]) != _canonical(operation):
                    raise SimInputError("compact pending differs from sealed schedule")
                acknowledge(self.checkpoint())
            self._assert_driver_head()
            self._assert_account_heads(state)
            pending = state["pending"]
            records = self._compact_records(operation, state)
            self._verify_effects(pending, completed=True)
            plan = self._commit_plan(pending, records, state)
            if self._recovery_plan is not None and compact_commit_plan_document(
                plan
            ) != compact_commit_plan_document(self._recovery_plan):
                raise SimInputError(
                    "reconstructed compact COMMIT differs from caller-retained lost-response plan"
                )
            retained_plan = compact_commit_plan_from_document(compact_commit_plan_document(plan))
            if commit_plan_sink(retained_plan) is not True:
                raise SimInputError("compact commit-plan sink must ACK True exactly before COMMIT")
            self._commit_known_plan(plan)
            self._recovery_plan = None
            acknowledge(self.checkpoint())
        return self.checkpoint()
