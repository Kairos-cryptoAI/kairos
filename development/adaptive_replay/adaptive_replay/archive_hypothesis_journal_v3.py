"""Create-only durable archive producer; separate market and financial seals.

Every original typed observation and first-trigger receipt survives restart.
The market-only input/decision prefixes are independently retained anchors,
not historical receive clocks or source/trading admission. Bounded producer
history is audited on ordinary operations; no dense-feed capacity is claimed.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from pathlib import Path

from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent

from . import archive_hypothesis_v3 as hypothesis
from . import archive_portfolio_stream_v3 as stream_module
from .archive_batch_cursor_v3 import ArchiveCursorCheckpointV3
from .archive_market_clock_v3 import ArchiveBBOQuoteV3, ArchiveMarketClockV3
from .archive_portfolio_stream_v3 import (
    ArchivePortfolioCheckpointV3,
    ArchivePortfolioSourceCheckpointV3,
    ArchivePortfolioStreamV3,
)
from .bookticker_archive_stream_v3 import BookTickerArchiveRowV3, _canonical, _regular_nofollow
from .historical_context import _name, _sha
from .sim_state_journal import EventConflict, JournalFull, OptimisticConflict
from .system import AttemptReceipt

SCHEMA = "kairos.research.archive-hypothesis-journal.v3"
MAX_PARENTS = 128
MAX_EVENTS = MAX_PARENTS * hypothesis.MAX_OBSERVATIONS
MAX_BYTES = 2 * 1024 * 1024
MAX_DATABASE_BYTES = 512 * 1024 * 1024
APPLICATION_ID = 0x4B414833


@dataclass(frozen=True)
class ArchiveHypothesisJournalCheckpointV3:
    seal_sha256: str
    version: int
    head_sha256: str
    state_sha256: str
    parents: tuple[tuple[str, hypothesis.ArchiveProducerCheckpointV3], ...]
    decision_market_checkpoint: ArchivePortfolioCheckpointV3 | None

    def __post_init__(self):
        for value in (self.seal_sha256, self.head_sha256, self.state_sha256):
            _sha(value)
        if (
            type(self.version) is not int
            or not 0 <= self.version <= MAX_EVENTS
            or type(self.parents) is not tuple
            or len(self.parents) > MAX_PARENTS
        ):
            raise ValueError("bounded exact journal checkpoint required")
        keys = []
        for item in self.parents:
            if type(item) is not tuple or len(item) != 2:
                raise ValueError("typed complete parent checkpoint vector required")
            _sha(item[0])
            hypothesis._recheck(item[1], hypothesis.ArchiveProducerCheckpointV3)
            keys.append(item[0])
        if keys != sorted(set(keys)):
            raise ValueError("canonical unique parent checkpoint vector required")
        if self.decision_market_checkpoint is not None:
            hypothesis._recheck(self.decision_market_checkpoint, ArchivePortfolioCheckpointV3)


@dataclass(frozen=True)
class ArchiveIssuedReceiptV3:
    event_id: str
    parent_id: str
    journal_version: int
    payload_sha256: str
    receipt: hypothesis.ArchiveProducerReceiptV3
    decision_market_checkpoint: ArchivePortfolioCheckpointV3


@dataclass(frozen=True)
class ArchivePreparedAppendV3:
    before: ArchiveHypothesisJournalCheckpointV3
    after: ArchiveHypothesisJournalCheckpointV3
    issued: ArchiveIssuedReceiptV3


@dataclass(frozen=True)
class ArchiveIssuedPrefixV3:
    """Original selected first-trigger prefix, never a later producer snapshot.

    Construction checks the native pure fold, not archive admission. Only the
    journal export additionally authenticates source originals and membership
    at independently retained store and issuance checkpoints.
    """

    issued_checkpoint: ArchiveHypothesisJournalCheckpointV3
    plan: hypothesis.ArchiveHypothesisPlanV3
    observations: tuple[hypothesis.ArchiveHypothesisObservationV3, ...]
    receipts: tuple[hypothesis.ArchiveProducerReceiptV3, ...]
    issued: ArchiveIssuedReceiptV3

    def __post_init__(self):
        hypothesis._recheck(self.issued_checkpoint, ArchiveHypothesisJournalCheckpointV3)
        hypothesis._recheck(self.plan, hypothesis.ArchiveHypothesisPlanV3)
        hypothesis._recheck(self.issued, ArchiveIssuedReceiptV3)
        if (
            type(self.observations) is not tuple
            or type(self.receipts) is not tuple
            or not 1 <= len(self.observations) <= hypothesis.MAX_OBSERVATIONS
            or len(self.observations) != len(self.receipts)
            or self.issued.parent_id != self.plan.template.intent_id
            or self.issued.journal_version != self.issued_checkpoint.version
            or self.issued.decision_market_checkpoint != self.issued_checkpoint.decision_market_checkpoint
        ):
            raise ValueError("exact selected issuance and original bounded parent prefix required")
        _name(self.issued.event_id)
        _sha(self.issued.payload_sha256)
        parent_cp = dict(self.issued_checkpoint.parents).get(self.issued.parent_id)
        if parent_cp is None:
            raise ValueError("original parent absent at independently retained issuance head")
        restored = hypothesis.ArchiveHypothesisProducerV3.restore(
            hypothesis.ArchiveProducerSnapshotV3(
                self.plan, hypothesis._implementation(), self.observations, self.receipts, parent_cp
            ),
            expected_checkpoint=parent_cp,
        )
        first = next((r for r in self.receipts if r.evaluation.state == "CONSUMED"), None)
        if first is None or first != self.issued.receipt or self.receipts[-1] != first:
            raise ValueError("only the original first-trigger prefix may be exported")
        if self.issued.payload_sha256 != _hash_document(
            {
                "observation": restored.snapshot().observations[-1],
                "decision_market_checkpoint": self.issued.decision_market_checkpoint,
            }
        ):
            raise ValueError("original selected payload commitment conflict")


_TYPES = {
    c.__name__: c
    for c in (
        Candle,
        ExitPlan,
        SleeveIntent,
        AttemptReceipt,
        BookTickerArchiveRowV3,
        ArchiveMarketClockV3,
        ArchiveBBOQuoteV3,
        ArchiveCursorCheckpointV3,
        ArchivePortfolioSourceCheckpointV3,
        ArchivePortfolioCheckpointV3,
        hypothesis.ArchiveHypothesisPolicyV3,
        hypothesis.ArchiveSourceEvidenceV3,
        hypothesis.ArchiveModelCompletionV3,
        hypothesis.ArchiveQuoteProofV3,
        hypothesis.ArchiveHypothesisPlanV3,
        hypothesis.ArchiveReviewV3,
        hypothesis.ArchiveHypothesisObservationV3,
        hypothesis.ArchiveHypothesisEvaluationV3,
        hypothesis.ArchiveProducerCheckpointV3,
        hypothesis.ArchiveProducerReceiptV3,
        hypothesis.ArchiveProducerSnapshotV3,
        ArchiveHypothesisJournalCheckpointV3,
        ArchiveIssuedReceiptV3,
        ArchivePreparedAppendV3,
        ArchiveIssuedPrefixV3,
    )
}


def _encode(value):
    if type(value) in {str, int, bool} or value is None:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("nonfinite native float prohibited")
        return {"$float": value.hex()}
    if type(value) is Decimal:
        if not value.is_finite():
            raise ValueError("nonfinite exact Decimal prohibited")
        return {"$decimal": str(value)}
    if type(value) is bytes:
        return {"$bytes": value.hex()}
    if type(value) is Side:
        return {"$side": value.value}
    if type(value) is tuple:
        return {"$tuple": [_encode(v) for v in value]}
    if type(value) is dict and all(type(k) is str and not k.startswith("$") for k in value):
        return {k: _encode(v) for k, v in value.items()}
    if is_dataclass(value) and _TYPES.get(type(value).__name__) is type(value):
        return {
            "$type": type(value).__name__,
            "fields": {f.name: _encode(getattr(value, f.name)) for f in fields(value)},
        }
    raise ValueError("exact registered archive/native type required; no implicit normalization")


def _decode(value):
    if type(value) in {str, int, bool} or value is None:
        return value
    if type(value) is not dict:
        raise ValueError("strict tagged archive document required")
    keys = set(value)
    if keys == {"$float"}:
        result = float.fromhex(value["$float"])
        if not math.isfinite(result) or result.hex() != value["$float"]:
            raise ValueError("exact finite native float encoding required")
        return result
    if keys == {"$decimal"}:
        result = Decimal(value["$decimal"])
        if not result.is_finite() or str(result) != value["$decimal"]:
            raise ValueError("exact finite Decimal spelling required")
        return result
    if keys == {"$bytes"}:
        result = bytes.fromhex(value["$bytes"])
        if result.hex() != value["$bytes"]:
            raise ValueError("exact raw byte encoding required")
        return result
    if keys == {"$side"}:
        return Side(value["$side"])
    if keys == {"$tuple"} and type(value["$tuple"]) is list:
        return tuple(_decode(v) for v in value["$tuple"])
    if keys == {"$type", "fields"}:
        cls = _TYPES.get(value["$type"])
        if (
            cls is None
            or type(value["fields"]) is not dict
            or set(value["fields"]) != {f.name for f in fields(cls)}
        ):
            raise ValueError("exact registered type fields required")
        decoded = {k: _decode(v) for k, v in value["fields"].items()}
        result = cls(**{f.name: decoded[f.name] for f in fields(cls) if f.init})
        if any(getattr(result, f.name) != decoded[f.name] for f in fields(cls)):
            raise ValueError("computed native identity/cached SHA cannot be discarded")
        return result
    if any(k.startswith("$") for k in keys):
        raise ValueError("unknown/ambiguous typed encoding prohibited")
    return {k: _decode(v) for k, v in value.items()}


def _document(value, limit=MAX_BYTES):
    raw = _canonical(_encode(value)).decode("utf-8")
    if len(raw.encode("utf-8")) > limit:
        raise JournalFull("complete typed document exceeds frozen byte cap")
    return raw


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key prohibited")
        result[key] = value
    return result


def _load(raw, limit=MAX_BYTES):
    if type(raw) is not str or len(raw.encode("utf-8")) > limit:
        raise ValueError("bounded exact document required")
    parsed = json.loads(
        raw,
        object_pairs_hook=_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
    )
    decoded = _decode(parsed)
    if _document(decoded, limit) != raw:
        raise ValueError("canonical exact typed bytes required")
    return decoded


def _hash_document(value):
    return hashlib.sha256(_document(value).encode("utf-8")).hexdigest()


def _implementation():
    return _hash_document(
        {
            "schema": SCHEMA,
            "hypothesis": hypothesis._implementation(),
            "journal_source": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "stream_source": hashlib.sha256(Path(stream_module.__file__).read_bytes()).hexdigest(),
        }
    )


def market_descriptor(seal):
    hypothesis._recheck(seal, stream_module.ArchivePortfolioSealV3)
    if seal.boundaries:
        raise ValueError("independent market-only producer stream cannot contain financial actions")
    return {
        "seal_sha256": seal.sha256,
        "days": seal.days,
        "entry_days": seal.entry_days,
        "symbols": seal.symbols,
        "sources": tuple(
            (
                s.source_key,
                str(s.index.root.absolute()),
                str(s.index.source_root.absolute()),
                s.index.manifest_sha256,
                s.index.source_manifest_sha256,
                s.clock,
            )
            for s in seal.sources
        ),
    }


def _vector(cp):
    return {v.source_key: v.cursor for v in cp.source_vector}


def _source_prefix_leq(before, after):
    old, new = _vector(before), _vector(after)
    if set(old) != set(new):
        raise ValueError("complete source identity vector differs")
    for key, a in old.items():
        b = new[key]
        if (
            (a.index_manifest_sha256, a.source_manifest_sha256, a.clock_policy_sha256)
            != (b.index_manifest_sha256, b.source_manifest_sha256, b.clock_policy_sha256)
            or a.next_row > b.next_row
            or (a.next_row == b.next_row and a.prefix_sha256 != b.prefix_sha256)
        ):
            raise ValueError("original source prefix regressed/changed identity")


def verify_source_vector_mapping(*, market_checkpoint, financial_checkpoint, market_seal, financial_seal):
    """Exact source mapping between unrelated seals; never relabel global hashes."""
    left, right = market_descriptor(market_seal), market_descriptor(replace_market_only(financial_seal))
    if (
        left["sources"] != right["sources"]
        or left["days"] != right["days"]
        or left["symbols"] != right["symbols"]
    ):
        raise ValueError("financial and producer source rosters differ")
    if (
        market_checkpoint.seal_sha256 != market_seal.sha256
        or financial_checkpoint.seal_sha256 != financial_seal.sha256
    ):
        raise ValueError("independent exact stream seals required")
    if (
        market_checkpoint.source_vector != financial_checkpoint.source_vector
        or market_checkpoint.global_row_count != financial_checkpoint.global_row_count
    ):
        raise ValueError("source-before-decision requires complete equal original vector/raw count")


def replace_market_only(seal):
    from dataclasses import replace

    return replace(seal, boundaries=())


class ArchiveHypothesisJournalV3:
    def __init__(self, path, connection, config, market_seal, checkpoint):
        self.path, self._db, self.config, self.market_seal = path, connection, config, market_seal
        self._retained, self._lock = checkpoint, threading.RLock()

    @classmethod
    def create(
        cls,
        path,
        *,
        producer_id,
        arm_id,
        plans,
        market_seal,
        max_events=MAX_EVENTS,
        max_event_bytes=MAX_BYTES,
        max_database_bytes=MAX_DATABASE_BYTES,
    ):
        _name(producer_id)
        if arm_id not in {"strategy_only", "context_review", "independent_proposals", "combined"}:
            raise ValueError("explicit existing four-arm identity required")
        descriptor = market_descriptor(market_seal)
        if (
            type(plans) is not tuple
            or not 1 <= len(plans) <= MAX_PARENTS
            or any(type(p) is not hypothesis.ArchiveHypothesisPlanV3 for p in plans)
        ):
            raise ValueError("full bounded original parent roster required")
        keys = tuple(p.template.intent_id for p in plans)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("canonical unique original parent IDs required")
        for p in plans:
            hypothesis._recheck(p, hypothesis.ArchiveHypothesisPlanV3)
            if p.template.symbol not in market_seal.symbols or p.policy.quote_clock != next(
                s.clock for s in market_seal.sources if s.index.symbol == p.template.symbol
            ):
                raise ValueError("original parent and market model source disagree")
        for value, cap in (
            (max_events, MAX_EVENTS),
            (max_event_bytes, MAX_BYTES),
            (max_database_bytes, MAX_DATABASE_BYTES),
        ):
            if type(value) is not int or not 1 <= value <= cap:
                raise ValueError("honest frozen journal resource cap required")
        config = {
            "schema": SCHEMA,
            "producer_id": producer_id,
            "arm_id": arm_id,
            "plans": plans,
            "market": descriptor,
            "implementation": _implementation(),
            "max_events": max_events,
            "max_event_bytes": max_event_bytes,
            "max_database_bytes": max_database_bytes,
            "source_admitted": False,
            "economics_qualified": False,
        }
        config_doc, seal_sha = _document(config), _hash_document(config)
        producers = {p.template.intent_id: hypothesis.ArchiveHypothesisProducerV3(p) for p in plans}
        state_hash = _hash_document(
            tuple((k, _hash_document(v.snapshot())) for k, v in sorted(producers.items()))
        )
        checkpoint = ArchiveHypothesisJournalCheckpointV3(
            seal_sha,
            0,
            _hash_document({"schema": SCHEMA, "seal": seal_sha, "genesis": True}),
            state_hash,
            tuple((k, v.checkpoint()) for k, v in sorted(producers.items())),
            None,
        )
        path = Path(path).absolute()
        descriptor_fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor_fd)
        db = sqlite3.connect(path, isolation_level=None, timeout=5)
        try:
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            db.execute(
                f"PRAGMA max_page_count={max_database_bytes // db.execute('PRAGMA page_size').fetchone()[0]}"
            )
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE meta(id INTEGER PRIMARY KEY CHECK(id=1),"
                "config TEXT NOT NULL,checkpoint TEXT NOT NULL)"
            )
            db.execute("CREATE TABLE parents(parent_id TEXT PRIMARY KEY,projection TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE events(version INTEGER PRIMARY KEY,event_id TEXT UNIQUE NOT NULL,"
                "parent_id TEXT NOT NULL,payload TEXT NOT NULL,issued TEXT NOT NULL,"
                "before_cp TEXT NOT NULL,after_cp TEXT NOT NULL)"
            )
            db.execute("INSERT INTO meta VALUES(1,?,?)", (config_doc, _document(checkpoint)))
            db.executemany(
                "INSERT INTO parents VALUES(?,?)",
                [(k, _document(v.snapshot())) for k, v in producers.items()],
            )
            db.execute("COMMIT")
            result = cls(path, db, config, market_seal, checkpoint)
            result.audit()
            return result
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            db.close()
            raise

    @classmethod
    def open(cls, path, *, market_seal, expected_checkpoint):
        hypothesis._recheck(expected_checkpoint, ArchiveHypothesisJournalCheckpointV3)
        path = Path(path).absolute()
        _regular_nofollow(path)
        db = sqlite3.connect(f"{path.as_uri()}?mode=rw", uri=True, isolation_level=None, timeout=5)
        try:
            if db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                raise ValueError("separate archive journal, no legacy adoption/migration")
            db.execute("PRAGMA synchronous=FULL")
            config = _load(db.execute("SELECT config FROM meta WHERE id=1").fetchone()[0])
            result = cls(path, db, config, market_seal, expected_checkpoint)
            result.audit()
            return result
        except BaseException:
            db.close()
            raise

    def _guard(self):
        if self.config["implementation"] != _implementation() or self.config["market"] != market_descriptor(
            self.market_seal
        ):
            raise ValueError("frozen producer source/market identity changed")
        if _hash_document(self.config) != self._retained.seal_sha256:
            raise ValueError("producer configuration differs from independent seal")
        if self.path.stat().st_size > self.config["max_database_bytes"]:
            raise JournalFull("frozen database byte capacity exceeded")

    def _validate_market(self, observation, cp, previous_cp):
        hypothesis._recheck(cp, ArchivePortfolioCheckpointV3)
        if cp.seal_sha256 != self.market_seal.sha256 or cp.boundary_cursor:
            raise ValueError("independently retained market-only decision checkpoint required")
        if previous_cp is not None:
            _source_prefix_leq(previous_cp, cp)
            if cp.last_clock_ms < previous_cp.last_clock_ms:
                raise ValueError("global market decision prefix regressed")
        current = ArchivePortfolioStreamV3(
            self.market_seal, expected_seal_sha256=self.market_seal.sha256, expected_checkpoint=cp
        )
        if cp.last_clock_ms > observation.decision_history_ms:
            raise ValueError("future market prefix at original decision")
        next_op = current.prepare_next()
        if (
            next_op is not None
            and next_op.rows[0].quote.modeled_available_at_ms <= observation.decision_history_ms
        ):
            raise ValueError("unprocessed original source head <= decision across full roster")
        proof = observation.quote
        if proof is not None:
            if (
                proof.source_prefix.seal_sha256 != self.market_seal.sha256
                or proof.source_prefix.boundary_cursor
            ):
                raise ValueError("quote input prefix belongs to another/non-market producer seal")
            _source_prefix_leq(proof.source_prefix, cp)
            input_stream = ArchivePortfolioStreamV3(
                self.market_seal,
                expected_seal_sha256=self.market_seal.sha256,
                expected_checkpoint=proof.source_prefix,
            )
            key = f"{proof.quote.symbol}:{proof.quote.transaction_day}"
            if input_stream._readers[key].lookup_row(proof.quote.row_index) != proof.original:
                raise ValueError("original quote bytes absent from sealed index")
            if proof.source_prefix.last_clock_ms > observation.input_ready_history_ms:
                raise ValueError("hashed quote input prefix is future to measured model input baseline")

    def _audit(self, expected_checkpoint=None):
        self._guard()
        meta = self._db.execute("SELECT config,checkpoint FROM meta WHERE id=1").fetchone()
        if _load(meta[0]) != self.config:
            raise ValueError("durable config projection corrupted")
        projections = {
            p.template.intent_id: hypothesis.ArchiveHypothesisProducerV3(p) for p in self.config["plans"]
        }
        parents = tuple((k, p.checkpoint()) for k, p in sorted(projections.items()))
        state_hash = _hash_document(
            tuple((k, _hash_document(p.snapshot())) for k, p in sorted(projections.items()))
        )
        cp = ArchiveHypothesisJournalCheckpointV3(
            self._retained.seal_sha256,
            0,
            _hash_document({"schema": SCHEMA, "seal": self._retained.seal_sha256, "genesis": True}),
            state_hash,
            parents,
            None,
        )
        events = []
        for row in self._db.execute(
            "SELECT version,event_id,parent_id,payload,issued,before_cp,after_cp FROM events ORDER BY version"
        ):
            version, event_id, parent_id, payload_doc, issued_doc, before_doc, after_doc = row
            if version != cp.version + 1 or version > self.config["max_events"] or _load(before_doc) != cp:
                raise ValueError("producer event chain order/truncation corrupted")
            payload = _load(payload_doc, self.config["max_event_bytes"])
            if set(payload) != {"observation", "decision_market_checkpoint"} or parent_id not in projections:
                raise ValueError("exact original producer payload schema required")
            observation, market = payload["observation"], payload["decision_market_checkpoint"]
            self._validate_market(observation, market, cp.decision_market_checkpoint)
            issued, after = self._derive(cp, projections, event_id, parent_id, payload)
            if _load(issued_doc) != issued or _load(after_doc) != after:
                raise ValueError("original first-trigger receipt/head tampered")
            cp = after
            events.append(issued)
        durable = {
            key: _load(doc) for key, doc in self._db.execute("SELECT parent_id,projection FROM parents")
        }
        if durable != {k: p.snapshot() for k, p in projections.items()}:
            raise ValueError("current parent projection corrupted")
        if _load(meta[1]) != cp or cp != (
            self._retained if expected_checkpoint is None else expected_checkpoint
        ):
            raise OptimisticConflict("independent exact archive checkpoint mismatch; no latest adoption")
        return cp, projections, tuple(events)

    def _derive(self, before, producers, event_id, parent_id, payload):
        producer = producers[parent_id]
        receipt = producer.append(payload["observation"], expected_checkpoint=producer.checkpoint())
        state_hash = _hash_document(
            tuple((k, _hash_document(p.snapshot())) for k, p in sorted(producers.items()))
        )
        issued = ArchiveIssuedReceiptV3(
            event_id,
            parent_id,
            before.version + 1,
            _hash_document(payload),
            receipt,
            payload["decision_market_checkpoint"],
        )
        after = ArchiveHypothesisJournalCheckpointV3(
            before.seal_sha256,
            before.version + 1,
            _hash_document({"schema": SCHEMA, "before": before, "issued": issued, "state": state_hash}),
            state_hash,
            tuple((k, p.checkpoint()) for k, p in sorted(producers.items())),
            payload["decision_market_checkpoint"],
        )
        return issued, after

    def audit(self):
        with self._lock:
            self._db.execute("BEGIN")
            try:
                result = self._audit()
                self._db.execute("COMMIT")
                return result[0]
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def checkpoint(self):
        return self.audit()

    def snapshot(self):
        with self._lock:
            self._db.execute("BEGIN")
            try:
                cp, producers, issued = self._audit()
                self._db.execute("COMMIT")
                return cp, tuple((k, p.snapshot()) for k, p in sorted(producers.items())), issued
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def prepare_append(
        self, *, event_id, parent_id, observation, decision_market_checkpoint, expected_checkpoint
    ):
        with self._lock:
            _name(event_id)
            _sha(parent_id)
            hypothesis._recheck(expected_checkpoint, ArchiveHypothesisJournalCheckpointV3)
            hypothesis._recheck(observation, hypothesis.ArchiveHypothesisObservationV3)
            if self.checkpoint() != expected_checkpoint:
                raise OptimisticConflict("exact retained head required before prepare")
            self._db.execute("BEGIN")
            try:
                before, producers, events = self._audit()
                if before.version >= self.config["max_events"]:
                    raise JournalFull("full original event roster cannot fit; no pending over-cap anchor")
                if parent_id not in producers:
                    raise ValueError("original parent outside presealed full roster")
                payload = {
                    "observation": observation,
                    "decision_market_checkpoint": decision_market_checkpoint,
                }
                _document(payload, self.config["max_event_bytes"])
                if self._db.execute("SELECT 1 FROM events WHERE event_id=?", (event_id,)).fetchone():
                    raise EventConflict("prepare is fresh-only; exact duplicate uses append without new head")
                if any(
                    e.parent_id == parent_id
                    and e.receipt.evaluation.observation_id == observation.observation_id
                    for e in events
                ):
                    raise EventConflict("same original observation cannot prepare a new event/head")
                self._validate_market(
                    observation, decision_market_checkpoint, before.decision_market_checkpoint
                )
                issued, after = self._derive(before, producers, event_id, parent_id, payload)
                self._db.execute("COMMIT")
                return ArchivePreparedAppendV3(before, after, issued)
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def _before_commit(self):
        """Fault/crash test hook, no production retry authority."""

    def _after_commit(self):
        """Fault/crash test hook, no implicit checkpoint publication."""

    def append(self, *, event_id, parent_id, observation, decision_market_checkpoint, expected_checkpoint):
        with self._lock:
            hypothesis._recheck(expected_checkpoint, ArchiveHypothesisJournalCheckpointV3)
            self._db.execute("BEGIN IMMEDIATE")
            try:
                before, producers, events = self._audit()
                if before != expected_checkpoint:
                    raise OptimisticConflict("exact retained head required before append")
                _name(event_id)
                _sha(parent_id)
                hypothesis._recheck(observation, hypothesis.ArchiveHypothesisObservationV3)
                payload = {
                    "observation": observation,
                    "decision_market_checkpoint": decision_market_checkpoint,
                }
                payload_doc = _document(payload, self.config["max_event_bytes"])
                existing = self._db.execute(
                    "SELECT payload,issued,parent_id FROM events WHERE event_id=?", (event_id,)
                ).fetchone()
                if existing:
                    if existing[0] != payload_doc or existing[2] != parent_id:
                        raise EventConflict("exact event ID redelivery changed original payload")
                    self._db.execute("COMMIT")
                    return _load(existing[1])
                if before.version >= self.config["max_events"]:
                    raise JournalFull("full original event roster cannot fit; no first-N replay")
                if parent_id not in producers:
                    raise ValueError("parent not presealed")
                if any(
                    p.receipt.evaluation.observation_id == observation.observation_id
                    for p in events
                    if p.parent_id == parent_id
                ):
                    raise EventConflict("same original observation cannot create a new event/head")
                self._validate_market(
                    observation, decision_market_checkpoint, before.decision_market_checkpoint
                )
                issued, after = self._derive(before, producers, event_id, parent_id, payload)
                self._db.execute(
                    "INSERT INTO events VALUES(?,?,?,?,?,?,?)",
                    (
                        after.version,
                        event_id,
                        parent_id,
                        payload_doc,
                        _document(issued),
                        _document(before),
                        _document(after),
                    ),
                )
                self._db.execute(
                    "UPDATE parents SET projection=? WHERE parent_id=?",
                    (_document(producers[parent_id].snapshot()), parent_id),
                )
                self._db.execute("UPDATE meta SET checkpoint=? WHERE id=1", (_document(after),))
                if (
                    self._db.execute("PRAGMA page_count").fetchone()[0]
                    * self._db.execute("PRAGMA page_size").fetchone()[0]
                    > self.config["max_database_bytes"]
                ):
                    raise JournalFull("database capacity exhausted; append rolled back")
                self._before_commit()
                self._audit(expected_checkpoint=after)
                self._db.execute("COMMIT")
                self._retained = after
            except BaseException:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
            self._after_commit()
            return issued

    def first_consumed(self, parent_id, *, expected_checkpoint):
        hypothesis._recheck(expected_checkpoint, ArchiveHypothesisJournalCheckpointV3)
        _sha(parent_id)
        cp, _, events = self.snapshot()
        if cp != expected_checkpoint:
            raise OptimisticConflict("exact producer checkpoint required for first-trigger bridge")
        return next(
            (e for e in events if e.parent_id == parent_id and e.receipt.evaluation.state == "CONSUMED"), None
        )

    def issued_prefix(
        self, parent_id, issued_version, *, expected_store_checkpoint, expected_issued_checkpoint
    ):
        """Read-only exact prefix export; caller anchors both heads independently.

        A later current head is allowed ONLY if already independently retained.
        Its later observations/attempts are audited but never included in the
        selected bundle. This is not permission to discover or adopt latest.
        """
        _sha(parent_id)
        hypothesis._recheck(expected_store_checkpoint, ArchiveHypothesisJournalCheckpointV3)
        hypothesis._recheck(expected_issued_checkpoint, ArchiveHypothesisJournalCheckpointV3)
        if type(issued_version) is not int or not 1 <= issued_version <= MAX_EVENTS:
            raise ValueError("exact original positive issuance version required")
        with self._lock:
            self._db.execute("BEGIN")
            try:
                current, producers, events = self._audit()
                if current != expected_store_checkpoint:
                    raise OptimisticConflict("exact independently retained current store checkpoint required")
                selected = next((e for e in events if e.journal_version == issued_version), None)
                if selected is None or selected.parent_id != parent_id:
                    raise ValueError("selected original issuance absent or belongs to another parent")
                first = next(
                    (
                        e
                        for e in events
                        if e.parent_id == parent_id and e.receipt.evaluation.state == "CONSUMED"
                    ),
                    None,
                )
                if selected != first:
                    raise ValueError("selected issuance is not the original first-trigger receipt")
                original_cp = _load(
                    self._db.execute(
                        "SELECT after_cp FROM events WHERE version=?", (issued_version,)
                    ).fetchone()[0]
                )
                if original_cp != expected_issued_checkpoint:
                    raise OptimisticConflict(
                        "exact independently retained original issued checkpoint required"
                    )
                snapshot = producers[parent_id].snapshot()
                count = selected.receipt.sequence
                bundle = ArchiveIssuedPrefixV3(
                    original_cp,
                    snapshot.plan,
                    snapshot.observations[:count],
                    snapshot.receipts[:count],
                    selected,
                )
                _document(bundle)  # bounded exact handoff, without later parent originals
                self._db.execute("COMMIT")
                return bundle
            except BaseException:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise

    def close(self):
        with self._lock:
            self._db.close()
