"""Journal-issued archive ENTRY in a separate retrospective research namespace.

No production admission, synthetic receive clocks, raw-response ORDER bypass,
or conversion to the old fixture entry type. Every financial effect uses the
shared Q5/native fold. Original packets are a NEW bounded capture contract,
not evidence that an historical model request has already been performed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from pathlib import Path

from kairos_core.enums import Side

from . import archive_hypothesis_journal_v3 as producer_module
from . import archive_hypothesis_v3 as hypothesis
from . import archive_portfolio_financial_consumer_v3 as base
from .archive_hypothesis_journal_v3 import (
    ArchiveHypothesisJournalCheckpointV3,
    ArchiveHypothesisJournalV3,
)
from .archive_portfolio_stream_v3 import (
    ArchivePortfolioBoundaryV3,
    ArchivePortfolioLimitsV3,
    ArchivePortfolioSealV3,
)
from .bookticker_archive_stream_v3 import _canonical, _open_regular, _regular_nofollow
from .historical_context import _name, _sha

SCHEMA = "kairos.research.archive-portfolio-financial.v4"
PACKET_SCHEMA = "kairos.research.actual-wall-model-original-packet.v4"
MAX_PACKET_BYTES = 2 * 1024 * 1024
MAX_PACKETS = producer_module.MAX_EVENTS + producer_module.MAX_PARENTS
ARM_ORIGINS = {
    "strategy_only": ("TECHNICAL",),
    "context_review": ("TECHNICAL",),
    "independent_proposals": ("CONTEXT_PROPOSAL",),
    "combined": ("CONTEXT_PROPOSAL", "TECHNICAL"),
}


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _plain_json(raw, *, canonical=True):
    if type(raw) is not bytes or len(raw) > MAX_PACKET_BYTES:
        raise ValueError("bounded exact original bytes required")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate original JSON field")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("nonfinite original JSON value")

    parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
    if canonical and _canonical(parsed) != raw:
        raise ValueError("exact canonical original capture document required")
    return parsed


def _read_original(path, expected_sha256, expected_bytes):
    _sha(expected_sha256)
    if type(expected_bytes) is not int or not 1 <= expected_bytes <= MAX_PACKET_BYTES:
        raise ValueError("explicit original byte cap required")
    target = Path(path)
    if not target.is_absolute():
        raise ValueError("absolute retained original path required")
    before = _regular_nofollow(target)
    reader, opened = _open_regular(target)
    with reader:
        raw = reader.read(expected_bytes + 1)
    after = _regular_nofollow(target)
    if (
        len(raw) != expected_bytes
        or _digest(raw) != expected_sha256
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise ValueError("original packet identity/hash/size changed during bounded read")
    return raw


def _at_path(document, path):
    if type(path) is not list or not 1 <= len(path) <= 8:
        raise ValueError("bounded explicit original context/model/decision extraction path required")
    value = document
    for key in path:
        if type(key) is str and 0 < len(key) <= 128 and type(value) is dict:
            if key not in value:
                raise ValueError("original JSON path absent")
            value = value[key]
        elif type(key) is int and 0 <= key <= 1024 and type(value) is list:
            if key >= len(value):
                raise ValueError("original JSON path absent")
            value = value[key]
        else:
            raise ValueError("original JSON path type conflict")
    return value


@dataclass(frozen=True)
class ArchiveModelOriginalPacketV4:
    """Exact request BODY only (no headers/secrets), context/config and receipt.

    Wall/expense documents below are an explicit future capture schema. Their
    authored existence is not provider/source authentication or trading power.
    Error raw responses may be retained without promoting them to COMPLETE.
    """

    evidence_kind: str
    request_body: bytes | None
    context_body: bytes
    config_body: bytes
    raw_response: bytes | None
    wall_receipt: bytes
    expense_record: bytes

    def __post_init__(self):
        if self.evidence_kind not in {"TEST_FIXTURE", "OBSERVED_POINT_IN_TIME"}:
            raise ValueError("explicit original packet provenance required")
        values = (
            self.request_body,
            self.context_body,
            self.config_body,
            self.raw_response,
            self.wall_receipt,
            self.expense_record,
        )
        if (
            any(v is not None and type(v) is not bytes for v in values)
            or any(
                v is None
                for v in (self.context_body, self.config_body, self.wall_receipt, self.expense_record)
            )
            or sum(len(v) for v in values if v is not None) > MAX_PACKET_BYTES
        ):
            raise ValueError("bounded complete original packet, no clipping")
        _plain_json(self.wall_receipt)
        _plain_json(self.expense_record)

    @property
    def bytes(self):
        raw = _canonical(
            {
                "schema": PACKET_SCHEMA,
                "evidence_kind": self.evidence_kind,
                **{
                    name: None if getattr(self, name) is None else getattr(self, name).hex()
                    for name in (
                        "request_body",
                        "context_body",
                        "config_body",
                        "raw_response",
                        "wall_receipt",
                        "expense_record",
                    )
                },
            }
        )
        if len(raw) > MAX_PACKET_BYTES:
            raise ValueError("full encoded original packet exceeds pinned cap")
        return raw

    @classmethod
    def decode(cls, raw):
        document = _plain_json(raw)
        names = {
            "request_body",
            "context_body",
            "config_body",
            "raw_response",
            "wall_receipt",
            "expense_record",
        }
        if (
            type(document) is not dict
            or set(document) != names | {"schema", "evidence_kind"}
            or document["schema"] != PACKET_SCHEMA
        ):
            raise ValueError("exact new original packet schema required")
        values = {}
        for name in names:
            value = document[name]
            if value is not None and (
                type(value) is not str or len(value) % 2 or any(c not in "0123456789abcdef" for c in value)
            ):
                raise ValueError("exact unrounded original byte encoding required")
            values[name] = None if value is None else bytes.fromhex(value)
        result = cls(document["evidence_kind"], **values)
        if result.bytes != raw:
            raise ValueError("original packet roundtrip conflict")
        return result

    def verify(self, completion):
        hypothesis._recheck(completion, hypothesis.ArchiveModelCompletionV3)
        attempt = completion.attempt
        _plain_json(self.expense_record)
        expected_expense = {
            "attempt_id": attempt.attempt_id,
            "captured_wall_ms": completion.captured_wall_ms,
            "currency": "USD",
            "status": attempt.status,
            "evidence_kind": attempt.evidence_kind,
            "cost_usd": None if attempt.cost_usd is None else str(Decimal(str(attempt.cost_usd))),
        }
        if self.expense_record != _canonical(expected_expense):
            raise ValueError("original expense/status/wall record differs from typed completion")
        _plain_json(self.wall_receipt)
        expected_wall = {
            "schema": PACKET_SCHEMA,
            "clock_domain": "ACTUAL_WALL_UTC",
            "provider": completion.provider,
            "attempt_id": attempt.attempt_id,
            "requested_wall_ms": attempt.requested_ms,
            "response_wall_ms": completion.response_wall_ms,
            "completed_wall_ms": completion.completed_wall_ms,
            "captured_wall_ms": completion.captured_wall_ms,
            "status": attempt.status,
            "role": completion.role,
            "decision": completion.decision,
            "evidence_kind": attempt.evidence_kind,
            "no_call_reason": attempt.no_call_reason,
            "context_sha256": _digest(self.context_body),
            "config_sha256": _digest(self.config_body),
            "request_body_sha256": None if self.request_body is None else _digest(self.request_body),
            "raw_response_sha256": None if self.raw_response is None else _digest(self.raw_response),
            "expense_record_sha256": _digest(self.expense_record),
        }
        if (
            self.wall_receipt != _canonical(expected_wall)
            or self.evidence_kind != attempt.evidence_kind
            or _digest(self.wall_receipt) != completion.original_receipt_sha256
            or _digest(self.context_body) != completion.input_sha256
            or _digest(self.config_body) != completion.model_config_sha256
            or (attempt.status != "NOT_CALLED" and self.request_body is None)
            or (
                attempt.status == "NOT_CALLED"
                and (self.request_body is not None or self.raw_response is not None)
            )
            or (
                attempt.status == "COMPLETE"
                and (self.raw_response is None or _digest(self.raw_response) != completion.response_sha256)
            )
        ):
            raise ValueError(
                "independently retained original request/context/config/response/wall hash conflict"
            )
        config = _plain_json(self.config_body)
        if (
            type(config) is not dict
            or set(config)
            != {
                "provider",
                "model",
                "model_path",
                "context_path",
                "context_prefix",
                "context_suffix",
                "decision_path",
                "decision_json_key",
                "parser",
            }
            or config["provider"] != "OPENAI"
            or config["parser"] != "BOUNDED_JSON_PATH_V4"
            or (
                type(config["model"]) is not str
                or not 0 < len(config["model"]) <= 256
                or any(
                    type(config[k]) is not str or len(config[k].encode("utf-8")) > MAX_PACKET_BYTES
                    for k in ("context_prefix", "context_suffix")
                )
            )
        ):
            raise ValueError("exact independently frozen original input/config/parser contract required")
        if self.request_body is not None:
            request = _plain_json(self.request_body, canonical=False)
            if (
                _at_path(request, config["model_path"]) != config["model"]
                or _at_path(request, config["context_path"])
                != config["context_prefix"] + self.context_body.decode("utf-8") + config["context_suffix"]
            ):
                raise ValueError("actual original request model/context rendering conflict")
        if attempt.status == "COMPLETE":
            decision = _at_path(_plain_json(self.raw_response, canonical=False), config["decision_path"])
            key = config["decision_json_key"]
            if key is not None:
                if type(key) is not str or not 0 < len(key) <= 128 or type(decision) is not str:
                    raise ValueError("explicit original decision text JSON key required")
                parsed = _plain_json(decision.encode("utf-8"), canonical=False)
                if type(parsed) is not dict:
                    raise ValueError("original normalized decision is not a JSON object")
                decision = parsed[key]
            if type(decision) is not str or decision != completion.decision:
                raise ValueError("original raw model disposition differs from typed S5 completion")
        return None if attempt.cost_usd is None else Decimal(str(attempt.cost_usd))


@dataclass(frozen=True)
class ArchivePacketReferenceV4:
    attempt_id: str
    path: str
    sha256: str
    byte_count: int

    def __post_init__(self):
        _name(self.attempt_id)
        _sha(self.sha256)
        if (
            type(self.path) is not str
            or not Path(self.path).is_absolute()
            or type(self.byte_count) is not int
            or not 1 <= self.byte_count <= MAX_PACKET_BYTES
        ):
            raise ValueError("bounded independently retained original packet reference required")

    def load(self, completion):
        if completion.attempt.attempt_id != self.attempt_id:
            raise ValueError("original packet attempt identity conflict")
        packet = ArchiveModelOriginalPacketV4.decode(_read_original(self.path, self.sha256, self.byte_count))
        return packet, packet.verify(completion)


@dataclass(frozen=True)
class ArchiveProducerReferenceV4:
    path: str
    store_checkpoint: ArchiveHypothesisJournalCheckpointV3
    market_seal: ArchivePortfolioSealV3

    def __post_init__(self):
        if type(self.path) is not str or not Path(self.path).is_absolute():
            raise ValueError("absolute independently retained producer journal required")
        hypothesis._recheck(self.store_checkpoint, ArchiveHypothesisJournalCheckpointV3)
        producer_module.market_descriptor(self.market_seal)

    @property
    def document(self):
        return {
            "path": self.path,
            "store_checkpoint": producer_module._document(self.store_checkpoint),
            "market": producer_module._document(producer_module.market_descriptor(self.market_seal)),
            "limits": asdict(self.market_seal.limits),
            "tie_rule": self.market_seal.tie_rule,
            "boundary_tie_order": list(self.market_seal.boundary_tie_order),
        }

    @classmethod
    def restore(cls, document, financial_seal):
        if set(document) != {
            "path",
            "store_checkpoint",
            "market",
            "limits",
            "tie_rule",
            "boundary_tie_order",
        }:
            raise ValueError("exact independently sealed producer reference required")
        market = producer_module._load(document["market"])
        seal = ArchivePortfolioSealV3(
            financial_seal.sources,
            market["symbols"],
            market["days"],
            (),
            document["tie_rule"],
            tuple(document["boundary_tie_order"]),
            ArchivePortfolioLimitsV3(**document["limits"]),
            market["entry_days"],
        )
        if producer_module.market_descriptor(seal) != market:
            raise ValueError("producer and financial original source/index/clock roster differ")
        return cls(document["path"], producer_module._load(document["store_checkpoint"]), seal)

    def open(self):
        return ArchiveHypothesisJournalV3.open(
            self.path, market_seal=self.market_seal, expected_checkpoint=self.store_checkpoint
        )


@dataclass(frozen=True)
class ArchiveIssuedReferenceV4:
    parent_id: str
    issued_version: int
    issued_checkpoint: ArchiveHypothesisJournalCheckpointV3
    prefix_sha256: str
    candidate_sha256: str

    def __post_init__(self):
        for value in (self.parent_id, self.prefix_sha256, self.candidate_sha256):
            _sha(value)
        hypothesis._recheck(self.issued_checkpoint, ArchiveHypothesisJournalCheckpointV3)
        if (
            type(self.issued_version) is not int
            or self.issued_version != self.issued_checkpoint.version
            or self.issued_version <= 0
        ):
            raise ValueError("exact independently retained original issuance required")

    @property
    def document(self):
        return {
            "parent_id": self.parent_id,
            "issued_version": self.issued_version,
            "issued_checkpoint": producer_module._document(self.issued_checkpoint),
            "prefix_sha256": self.prefix_sha256,
            "candidate_sha256": self.candidate_sha256,
        }


@dataclass(frozen=True)
class ArchiveJournalEntryV4:
    selected: ArchiveIssuedReferenceV4
    peers: tuple[ArchiveIssuedReferenceV4, ...] = ()

    def __post_init__(self):
        hypothesis._recheck(self.selected, ArchiveIssuedReferenceV4)
        if type(self.peers) is not tuple or len(self.peers) > producer_module.MAX_PARENTS:
            raise ValueError("full bounded original peer roster required")
        for peer in self.peers:
            hypothesis._recheck(peer, ArchiveIssuedReferenceV4)
        keys = tuple(p.parent_id for p in self.peers)
        if keys != tuple(sorted(set(keys))) or self.selected.parent_id in keys:
            raise ValueError("canonical distinct exact peer reference roster required")


@dataclass(frozen=True)
class ArchiveJournalEntryActionV4:
    boundary_id: str
    at_ms: int
    source_sha256: str
    parameters: ArchiveJournalEntryV4

    def __post_init__(self):
        _name(self.boundary_id)
        base._ms(self.at_ms)
        _sha(self.source_sha256)
        hypothesis._recheck(self.parameters, ArchiveJournalEntryV4)
        if self.source_sha256 != self.parameters.selected.prefix_sha256:
            raise ValueError("boundary must retain exact original first-trigger prefix commitment")

    @property
    def kind(self):
        return "CONTROL"

    @property
    def document(self):
        return {
            "namespace": SCHEMA,
            "boundary_id": self.boundary_id,
            "at_ms": self.at_ms,
            "source_sha256": self.source_sha256,
            "clock_evidence": "MODELED_REFERENCE",
            "parameter_type": "ArchiveJournalEntryV4",
            "selected": self.parameters.selected.document,
            "peers": [p.document for p in self.parameters.peers],
        }

    @property
    def boundary(self):
        return ArchivePortfolioBoundaryV3(
            self.boundary_id, self.kind, self.at_ms, _canonical(self.document), self.source_sha256
        )


@dataclass(frozen=True)
class ArchiveResearchProfileV4:
    arm_id: str
    sealed_wall_ms: int
    financial_replay_started_wall_ms: int
    evidence_kind: str
    cost_conversion: str
    producer: ArchiveProducerReferenceV4
    packets: tuple[ArchivePacketReferenceV4, ...]

    def __post_init__(self):
        base._ms(self.sealed_wall_ms)
        base._ms(self.financial_replay_started_wall_ms)
        hypothesis._recheck(self.producer, ArchiveProducerReferenceV4)
        if (
            self.arm_id not in ARM_ORIGINS
            or self.sealed_wall_ms > self.financial_replay_started_wall_ms
            or self.evidence_kind not in {"TEST_FIXTURE", "RETAINED_WALL_MODEL_OUTPUT"}
            or self.cost_conversion != "USD_ACCOUNT_UNIT_EQUIVALENCE_MODELED_1_TO_1"
            or type(self.packets) is not tuple
            or len(self.packets) > MAX_PACKETS
        ):
            raise ValueError("explicit sealed retrospective research/cost profile required")
        for packet in self.packets:
            hypothesis._recheck(packet, ArchivePacketReferenceV4)
        keys = tuple(p.attempt_id for p in self.packets)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("canonical complete original attempt packet roster required")

    @property
    def document(self):
        return {
            "schema": SCHEMA,
            "mode": "RETROSPECTIVE_RESEARCH_SIM",
            "source_admission": False,
            "trading_authority": "NONE",
            "arm_id": self.arm_id,
            "sealed_wall_ms": self.sealed_wall_ms,
            "financial_replay_started_wall_ms": self.financial_replay_started_wall_ms,
            "evidence_kind": self.evidence_kind,
            "cost_conversion": self.cost_conversion,
            "producer": self.producer.document,
            "packets": [asdict(p) for p in self.packets],
            "combined_arbitration": "FULL_KNOWN_PEERS_CONFLICT_REFUSAL_TECHNICAL_PRIORITY_NO_RESULT_FALLBACK",
            "unproved_origin_absence": "UNAVAILABLE_NO_ENTRY",
        }

    @classmethod
    def restore(cls, document, seal):
        result = cls(
            document["arm_id"],
            document["sealed_wall_ms"],
            document["financial_replay_started_wall_ms"],
            document["evidence_kind"],
            document["cost_conversion"],
            ArchiveProducerReferenceV4.restore(document["producer"], seal),
            tuple(ArchivePacketReferenceV4(**p) for p in document["packets"]),
        )
        if result.document != document:
            raise ValueError("exact research profile and no-authority namespace required")
        return result


@dataclass(frozen=True)
class _ValidatedEntryExecutionV4:
    intent_id: str
    symbol: str
    side: str
    stop_price: Decimal
    target_price: Decimal
    price_cap: Decimal
    eligible_at_ms: int
    expires_at_ms: int
    max_holding_ms: int
    trailing_activation_price: Decimal | None
    trailing_distance: Decimal | None
    original_parent_id: str
    producer_seal_sha256: str
    original_parent_sha256: str
    original_candidate_sha256: str
    original_first_trigger_prefix_sha256: str
    proof_kind: str = "ARCHIVE_JOURNAL_ISSUED_RETROSPECTIVE_RESEARCH_ONLY"


def _completions(snapshot):
    """Original attempt catalog with modeled request/completion availability."""
    result = {}
    for _, parent in snapshot[1]:
        plan = parent.plan
        values = [] if plan.proposal is None else [(plan.proposal, plan.input_ready_history_ms)]
        values.extend(
            (o.review.completion, o.input_ready_history_ms)
            for o in parent.observations
            if o.review is not None
        )
        for completion, ready in values:
            item = (
                completion,
                ready + plan.policy.model_queue_delay_ms,
                completion.available_at(ready, plan.policy),
            )
            key = completion.attempt.attempt_id
            if key in result and result[key] != item:
                raise ValueError("original attempt reused across conflicting context/clock/cost domains")
            result[key] = item
    return result


def _catalog(profile):
    journal = profile.producer.open()
    try:
        if journal.config["arm_id"] != profile.arm_id:
            raise ValueError("producer/financial arm identity differs")
        snapshot = journal.snapshot()
    finally:
        journal.close()
    catalog = _completions(snapshot)
    packets = {p.attempt_id: p for p in profile.packets}
    if set(packets) != set(catalog):
        raise ValueError("complete exact original model packet roster required; no first-N capture")
    for _, parent in snapshot[1]:
        plan = parent.plan
        if (
            plan.policy.evidence_kind != profile.evidence_kind
            or plan.policy.sealed_wall_ms > profile.sealed_wall_ms
            or plan.policy.replay_started_wall_ms > profile.sealed_wall_ms
            or plan.origin not in ARM_ORIGINS[profile.arm_id]
            or plan.policy.require_review != (profile.arm_id in {"context_review", "combined"})
        ):
            raise ValueError("original origin/review policy/actual wall research seal conflict")
    for key, (completion, _, _) in catalog.items():
        if completion.captured_wall_ms > profile.sealed_wall_ms:
            raise ValueError("financial action roster was sealed before original model capture")
        packets[key].load(completion)
    return snapshot, catalog


def _bundle(profile, reference):
    hypothesis._recheck(reference, ArchiveIssuedReferenceV4)
    journal = profile.producer.open()
    try:
        result = journal.issued_prefix(
            reference.parent_id,
            reference.issued_version,
            expected_store_checkpoint=profile.producer.store_checkpoint,
            expected_issued_checkpoint=reference.issued_checkpoint,
        )
    finally:
        journal.close()
    if (
        producer_module._hash_document(result) != reference.prefix_sha256
        or producer_module._hash_document(result.issued.receipt.evaluation.candidate)
        != reference.candidate_sha256
    ):
        raise ValueError("original first-trigger/candidate prefix commitment conflict")
    return result


def issued_reference_v4(profile, *, parent_id, issued_checkpoint):
    """Caller supplies both independently retained store/issuance heads."""
    hypothesis._recheck(profile, ArchiveResearchProfileV4)
    journal = profile.producer.open()
    try:
        bundle = journal.issued_prefix(
            parent_id,
            issued_checkpoint.version,
            expected_store_checkpoint=profile.producer.store_checkpoint,
            expected_issued_checkpoint=issued_checkpoint,
        )
    finally:
        journal.close()
    return ArchiveIssuedReferenceV4(
        parent_id,
        bundle.issued.journal_version,
        issued_checkpoint,
        producer_module._hash_document(bundle),
        producer_module._hash_document(bundle.issued.receipt.evaluation.candidate),
    )


def model_expense_actions_v4(profile):
    """Known/error/unknown expenses all keep the original explicit boundary."""
    _, catalog = _catalog(profile)
    packets = {p.attempt_id: p for p in profile.packets}
    result = []
    for key, (completion, _, available) in catalog.items():
        packet, amount = packets[key].load(completion)
        result.append(
            base.ArchivePortfolioActionV3(
                "0-cost:" + _digest(key.encode("utf-8"))[:32],
                available,
                _digest(packet.expense_record),
                base.ArchiveServiceCostV3(key, amount),
            )
        )
    return tuple(sorted(result, key=lambda a: (a.at_ms, a.boundary_id)))


def journal_entry_action_v4(profile, selected, *, peers=()):
    """The R2 evaluator, not raw provider output, is the only intent authority."""
    bundle = _bundle(profile, selected)
    evaluation = bundle.issued.receipt.evaluation
    if evaluation.candidate is None or evaluation.coverage != "AVAILABLE":
        raise ValueError("first trigger has no usable research candidate; no later rescue")
    return ArchiveJournalEntryActionV4(
        "1-entry:" + evaluation.candidate.intent_id,
        evaluation.decision_history_ms,
        selected.prefix_sha256,
        ArchiveJournalEntryV4(selected, peers),
    )


def _execution_view(profile, action, models):
    hypothesis._recheck(action, ArchiveJournalEntryActionV4)
    bundle = _bundle(profile, action.parameters.selected)
    plan, observation = bundle.plan, bundle.observations[-1]
    evaluation = bundle.issued.receipt.evaluation
    candidate = evaluation.candidate
    if (
        candidate is None
        or type(candidate.side) is not Side
        or evaluation.coverage != "AVAILABLE"
        or evaluation.reason != "MODELED_RESEARCH_CANDIDATE_NOT_ADMISSION"
        or action.at_ms != observation.decision_history_ms
        or action.at_ms != evaluation.decision_history_ms
        or action.at_ms != candidate.decision_ts_ms
        or action.at_ms != candidate.entry_eligible_ts_ms
        or plan.origin not in ARM_ORIGINS[profile.arm_id]
        or plan.policy.require_review != (profile.arm_id in {"context_review", "combined"})
        or candidate.exit_plan != plan.template.exit_plan
    ):
        raise ValueError("original first trigger/origin/actual modeled slot/protection conflict")
    if profile.arm_id == "combined":
        journal = profile.producer.open()
        try:
            same_slot = {
                p.template.intent_id: p
                for p in journal.config["plans"]
                if p.template.symbol == plan.template.symbol
                and p.origin_cut_history_ms == plan.origin_cut_history_ms
            }
        finally:
            journal.close()
        peers = action.parameters.peers
        if {p.parent_id for p in peers} != set(same_slot) - {plan.template.intent_id}:
            raise ValueError("combined original peer roster incomplete; no result-based fallback")
        peer_bundles = [_bundle(profile, p) for p in peers]
        original = [bundle, *peer_bundles]
        by_origin = {b.plan.origin: b for b in original}
        if len(by_origin) != len(original) or set(by_origin) != {"TECHNICAL", "CONTEXT_PROPOSAL"}:
            raise ValueError("combined origin absence unproved; UNKNOWN rather than implicit quiet")
        if any(b.issued.receipt.evaluation.decision_history_ms > action.at_ms for b in original):
            raise ValueError("combined peer outcome not known at original decision")
        if plan.origin != "TECHNICAL":
            raise ValueError("TECHNICAL_PRIORITY_NO_AFTER_RESULT_FALLBACK")
        technical, proposal = (
            by_origin[k].issued.receipt.evaluation for k in ("TECHNICAL", "CONTEXT_PROPOSAL")
        )
        if (
            technical.candidate is None
            or proposal.candidate is None
            or any(e.coverage != "AVAILABLE" for e in (technical, proposal))
        ):
            raise ValueError("combined peer unusable or vetoed; no proposal/technical fallback")
        if technical.candidate.side is not proposal.candidate.side:
            raise ValueError("ARBITRATION_CONFLICT_NO_ENTRY")
    elif action.parameters.peers:
        raise ValueError("inactive peer cannot silently influence another arm")
    model = next((m for m in models if m.symbol == candidate.symbol), None)
    if model is None:
        raise ValueError("candidate symbol absent from exact execution model roster")
    quote = observation.quote.quote
    reference = quote.ask_price if candidate.side is Side.LONG else quote.bid_price
    if Decimal(str(candidate.reference_price)) != reference:
        raise ValueError("exact original Decimal execution reference differs from native geometry")
    with localcontext(base.ARITHMETIC):
        tick = model.assumptions.price_tick
        cap = (reference / tick).to_integral_value(
            rounding=ROUND_FLOOR if candidate.side is Side.LONG else ROUND_CEILING
        ) * tick
    exits = candidate.exit_plan
    return bundle, _ValidatedEntryExecutionV4(
        candidate.intent_id,
        candidate.symbol,
        candidate.side.value,
        Decimal(str(exits.stop_price)),
        Decimal(str(exits.target_price)),
        cap,
        candidate.entry_eligible_ts_ms,
        candidate.entry_expires_ts_ms,
        exits.max_holding_ms,
        None if exits.trailing_activation_price is None else Decimal(str(exits.trailing_activation_price)),
        None if exits.trailing_distance is None else Decimal(str(exits.trailing_distance)),
        plan.template.intent_id,
        action.parameters.selected.issued_checkpoint.seal_sha256,
        producer_module._hash_document(plan.template),
        producer_module._hash_document(candidate),
        action.parameters.selected.prefix_sha256,
    )


class ArchivePortfolioFinancialConsumerV4(base.ArchivePortfolioFinancialConsumerV3):
    """One non-resetting research account, S5 proof and shared financial fold."""

    @classmethod
    def _implementation_id(cls):
        return base._hash(
            [
                super()._implementation_id(),
                [
                    [str(p.absolute()), _digest(p.read_bytes())]
                    for p in (
                        Path(__file__),
                        Path(producer_module.__file__),
                        Path(hypothesis.__file__),
                    )
                ],
            ]
        )

    @classmethod
    def _profile_config(cls, profile, *, actions, seal, fixture, models, expected_cost_ids):
        hypothesis._recheck(profile, ArchiveResearchProfileV4)
        source_kinds = {
            base._read_json(
                source.index.source_root / "manifest.json",
                base.MAX_MANIFEST_BYTES,
                source.index.source_manifest_sha256,
            )[0]["evidence_kind"]
            for source in seal.sources
        }
        if "TEST_FIXTURE" in source_kinds and source_kinds != {"TEST_FIXTURE"}:
            raise ValueError("mixed fixture and retained original source roster cannot be promoted")
        if (profile.evidence_kind == "TEST_FIXTURE") != fixture:
            raise ValueError(
                "fixture engineering cannot be promoted to retained actual model/source evidence"
            )
        restored = ArchiveProducerReferenceV4.restore(profile.producer.document, seal)
        if restored != profile.producer:
            raise ValueError("producer and financial source roster identity differs")
        _, catalog = _catalog(profile)
        if tuple(sorted(catalog)) != expected_cost_ids:
            raise ValueError("every original model expense must be in the exact sealed expected roster")
        actual_costs = [
            a
            for a in actions
            if type(a) is base.ArchivePortfolioActionV3 and type(a.parameters) is base.ArchiveServiceCostV3
        ]
        if len(actual_costs) != len(catalog):
            raise ValueError("every original model cost requires exactly one boundary")
        expected_actions = {a.parameters.cost_id: a for a in model_expense_actions_v4(profile)}
        for action in actual_costs:
            expected = expected_actions.get(action.parameters.cost_id)
            if (
                expected is None
                or action.boundary_id != expected.boundary_id
                or action.at_ms != expected.at_ms
                or action.parameters != expected.parameters
                or action.source_sha256 != expected.source_sha256
            ):
                raise ValueError(
                    "caller expense amount/clock differs from original independently retained packet"
                )
        return {
            "schema": SCHEMA,
            "archive_research_profile": profile.document,
            "execution_scope": "JOURNAL_ISSUED_MODELED_REFERENCE_NATIVE_REDUCERS_NOT_ADMISSION",
            "source_admission": False,
            "trading_authority": "NONE",
            "mode": "RETROSPECTIVE_RESEARCH_SIM",
        }

    @classmethod
    def _action_entries(cls, actions, *, seal, fixture, models, profile):
        if (
            type(actions) is not tuple
            or any(
                type(a) not in {ArchiveJournalEntryActionV4, base.ArchivePortfolioActionV3} for a in actions
            )
            or tuple(a.boundary for a in actions) != seal.boundaries
        ):
            raise ValueError("full exact typed research financial boundary roster required")
        entries = []
        parent_ids = []
        for action in actions:
            if type(action) is ArchiveJournalEntryActionV4:
                _, view = _execution_view(profile, action, models)
                entries.append((action, view))
                parent_ids.append(view.original_parent_id)
            elif type(action.parameters) is base.ArchiveFixtureEntryV3:
                raise ValueError("V4 never converts or accepts old FixtureEntry")
        if len(parent_ids) != len(set(parent_ids)):
            raise ValueError("original parent cannot be consumed under another entry boundary")
        return entries

    def __init__(self, journal, seal, models, calendars, actions, config):
        self.profile = ArchiveResearchProfileV4.restore(config["archive_research_profile"], seal)
        self._profile_document = self.profile.document
        _, self._attempt_catalog = _catalog(self.profile)
        self._catalog_hash = producer_module._hash_document(tuple(sorted(self._attempt_catalog.items())))
        self._bridge_functions = self._current_bridge_functions()
        super().__init__(journal, seal, models, calendars, actions, config)

    def _current_bridge_functions(self):
        return (
            self._entry_view.__func__,
            self._apply_entry.__func__,
            self._boundary.__func__,
            _bundle,
            _execution_view,
            _catalog,
            _completions,
            ArchiveModelOriginalPacketV4.verify,
            ArchivePacketReferenceV4.load,
            _at_path,
        )

    def _guard(self):
        super()._guard()
        if (
            self.profile.document != self._profile_document
            or self._current_bridge_functions() != self._bridge_functions
            or producer_module._hash_document(tuple(sorted(self._attempt_catalog.items())))
            != self._catalog_hash
            or self.config["archive_research_profile"] != self._profile_document
            or self._implementation_id() != self._implementation_sha
            or self.config.get("mode") != "RETROSPECTIVE_RESEARCH_SIM"
            or self.config.get("source_admission") is not False
            or self.config.get("trading_authority") != "NONE"
        ):
            raise ValueError("sealed no-authority research/producer/implementation profile changed")

    def _entry_view(self, state, action):
        if type(action) is not ArchiveJournalEntryActionV4:
            if type(action.parameters) is base.ArchiveFixtureEntryV3:
                raise ValueError("no FixtureEntry promotion in V4")
            return None
        bundle, view = _execution_view(self.profile, action, self.models)
        financial_prefix = base._checkpoint(state["portfolio_checkpoint"])
        producer_module.verify_source_vector_mapping(
            market_checkpoint=bundle.issued.decision_market_checkpoint,
            financial_checkpoint=financial_prefix,
            market_seal=self.profile.producer.market_seal,
            financial_seal=self.seal,
        )
        # Actual originals are re-read before handoff. Captured later packets
        # do not make their modeled decision/expense availability earlier.
        packet_map = {p.attempt_id: p for p in self.profile.packets}
        for key, (completion, requested, available) in self._attempt_catalog.items():
            if requested > action.at_ms:
                continue
            if available > action.at_ms:
                raise ValueError("UNRESOLVED_ACTIVE_PROVIDER_LIABILITY_NO_ENTRY")
            _, cost = packet_map[key].load(completion)
            if cost is None or state["service_costs"].get(key) != str(cost):
                raise ValueError("UNRESOLVED_OR_UNDEBITED_ORIGINAL_MODEL_EXPENSE_NO_ENTRY")
        consumed = state.setdefault("archive_consumed_parents", {})
        if view.original_parent_id in consumed:
            raise ValueError("original first trigger already consumed; no renewal or new ID")
        consumed[view.original_parent_id] = {
            "candidate": view.intent_id,
            "issued_version": bundle.issued.journal_version,
            "issued_checkpoint": producer_module._document(bundle.issued_checkpoint),
            "original_prefix_sha256": action.parameters.selected.prefix_sha256,
            "original_quote_input_prefix_sha256": hypothesis.digest(
                bundle.observations[-1].quote.source_prefix
            ),
            "decision_market_prefix_sha256": hypothesis.digest(bundle.issued.decision_market_checkpoint),
            "clock_domain": "MODELED_REFERENCE",
            "source_admission": False,
        }
        return view
