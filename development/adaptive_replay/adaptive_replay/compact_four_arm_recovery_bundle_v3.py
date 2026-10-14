"""Independent exact recovery bundles for the explicit compact financial driver.

Only this binder's successfully published DELETE/FULL SQLite bundle licenses
its True sink ACK, AFTER the owned checkpoint WAL fsync or exact plan persist.
All original publications/receipts remain indexed and append-only. A typed
receipt alone, an observed database head, or an unknown/lost response is not
an ACK. Known recovery accepts exactly one caller-retained original operation.

This is retrospective RESEARCH_ONLY with trading/source authority NONE. It
does not admit the historical corpus, change reducers/caps, authenticate a
hostile filesystem, guarantee Windows directory/power-loss durability, repair
torn WALs, or create a distributed transaction across the four accounts.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import asdict, dataclass, replace
from functools import wraps

from . import compact_commit_plan_store_v3 as plans
from . import four_arm_checkpoint_wal_v3 as root_wal
from . import segmented_four_arm_wal_v3 as segments
from .compact_four_arm_driver_journal_v3 import CompactFourArmDriverJournalV3
from .continuous_four_arm_v3 import (
    COMPACT_FINANCIAL_PROFILE,
    CompactFourArmDriverV3,
    compact_commit_plan_document,
    compact_commit_plan_from_document,
)
from .sim_delta_journal_v3 import DeltaCheckpointV3, _load, _sha
from .sim_state_journal import (
    EventConflict,
    JournalError,
    JournalFull,
    OptimisticConflict,
    _canonical,
    _configure,
    _existing_uri,
    _file_identity,
    _hash,
    _normalize_sql,
    _positive_bound,
    _safe_path,
    _set_database_bound,
    _verify_database_file_size,
    _verify_database_pages,
)

SCHEMA = "kairos.research.compact-four-arm-recovery-bundle.v3"
SCHEMA_VERSION = 61
OPERATION_RECORD_RESERVE = 8  # Prepared, intent, up to four partial checkpoints, plan, completed.
MAX_ROWS = 2**63 - 1
_FIELDS = {
    "kind",
    "checkpoint",
    "wal_before",
    "wal_after",
    "wal_segment_sha256",
    "plan_before",
    "plan_after",
    "plan",
    "plan_receipt",
    "driver_receipt",
}
_DDL = {
    "metadata": "CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)",
    "publications": (
        "CREATE TABLE publications(ordinal INTEGER PRIMARY KEY,publication_id TEXT NOT NULL UNIQUE,"
        "original_json TEXT NOT NULL,original_sha256 TEXT NOT NULL,original_bytes INTEGER NOT NULL,"
        "previous_hash TEXT NOT NULL,record_hash TEXT NOT NULL)"
    ),
    "head": (
        "CREATE TABLE head(singleton INTEGER PRIMARY KEY CHECK(singleton=1),count INTEGER NOT NULL,"
        "head_hash TEXT NOT NULL,last_original_sha256 TEXT,state_json TEXT NOT NULL)"
    ),
}


def _integer(value, name):
    if type(value) is not int or not 0 <= value <= MAX_ROWS:
        raise JournalError(f"exact bounded nonnegative {name} required")
    return value


def _serialized(function):
    @wraps(function)
    def guarded(self, *args, **kwargs):
        with self._lock:
            if self._active:
                raise JournalError("nested recovery-bundle operation forbidden")
            self._active = True
            try:
                return function(self, *args, **kwargs)
            finally:
                self._active = False

    return guarded


def _wal_limits(profile, values):
    cls = {
        root_wal.SCHEMA: root_wal.CheckpointWalLimitsV3,
        segments.SCHEMA: segments.SegmentedWalLimitsV3,
    }.get(profile)
    if cls is None or type(values) is not dict or set(values) != set(cls.__dataclass_fields__):
        raise JournalError("explicit exact ROOT or SEGMENTED WAL profile required")
    return cls(**values)


def _wal_anchor(profile, document):
    cls = {
        root_wal.SCHEMA: root_wal.CheckpointWalAnchorV3,
        segments.SCHEMA: segments.SegmentedWalAnchorV3,
    }.get(profile)
    if cls is None or type(document) is not dict or set(document) != set(cls.__dataclass_fields__):
        raise JournalError("closed typed WAL anchor required")
    return cls(**document)


def _next_wal(profile, limits, before, old_checkpoint, checkpoint, segment_sha256=None):
    """Predict from the held prefix, never from a newly observed WAL head."""
    root_wal._progress(old_checkpoint, checkpoint)
    document = root_wal.checkpoint_document(checkpoint)
    if root_wal.checkpoint_document(old_checkpoint) == document:
        return before
    frames = before.frame_count if profile == root_wal.SCHEMA else before.global_frames
    previous = before.head_sha256 if profile == root_wal.SCHEMA else before.global_head_sha256
    data, head = root_wal._frame(
        {
            "schema": root_wal.SCHEMA,
            "kind": "CHECKPOINT",
            "sequence": frames,
            "previous_sha256": previous,
            "checkpoint": document,
        },
        limits if profile == root_wal.SCHEMA else limits.framing(),
    )
    if profile == root_wal.SCHEMA:
        size = before.durable_bytes + len(data)
        if before.frame_count >= limits.max_frames or size > limits.max_file_bytes:
            raise JournalFull("checkpoint WAL budget exhausted before publication")
        return root_wal.CheckpointWalAnchorV3(before.identity_sha256, before.frame_count + 1, head, size)
    anchor = before
    if old_checkpoint.pending_operation is None:
        reserve = segments.OPERATION_FRAME_RESERVE * (limits.max_frame_bytes + segments.FRAME_OVERHEAD)
        if (
            anchor.global_frames + segments.OPERATION_FRAME_RESERVE > limits.max_global_frames
            or anchor.total_bytes + reserve > limits.max_total_bytes
        ):
            raise JournalFull("segmented WAL complete-operation budget exhausted")
        if (
            anchor.segment_frames + segments.OPERATION_FRAME_RESERVE > limits.max_segment_frames
            or anchor.segment_bytes + reserve > limits.max_segment_bytes
        ):
            _sha(segment_sha256)
            number = anchor.segment_number + 1
            if number >= limits.max_segments:
                raise JournalFull("segmented WAL rotation bound reached")
            seal_data, seal_head = root_wal._frame(
                {
                    "schema": segments.SCHEMA,
                    "kind": "SEAL",
                    "segment_number": anchor.segment_number,
                    "segment_header_sha256": anchor.segment_header_sha256,
                    "segment_frames": anchor.segment_frames,
                    "segment_bytes": anchor.segment_bytes,
                    "segment_sha256": segment_sha256,
                    "global_frames": anchor.global_frames,
                    "global_head_sha256": anchor.global_head_sha256,
                    "checkpoint": segments._closed_checkpoint(old_checkpoint),
                },
                limits.framing(),
            )
            seal_data = segments.SEAL_MAGIC + seal_data
            header_data, header_head = root_wal._frame(
                segments._header(
                    anchor.identity_sha256,
                    limits,
                    number,
                    old_checkpoint,
                    anchor.global_frames,
                    anchor.global_head_sha256,
                    anchor.catalog_head_sha256,
                    seal_head,
                ),
                limits.framing(),
            )
            header_data = segments.MAGIC + header_data
            catalog_data, catalog_head = root_wal._frame(
                {
                    "schema": segments.SCHEMA,
                    "kind": "ROTATE",
                    "sequence": anchor.catalog_count,
                    "previous_sha256": anchor.catalog_head_sha256,
                    "seal_sha256": seal_head,
                    "segment_header_sha256": header_head,
                },
                limits.framing(),
            )
            total = anchor.total_bytes + len(seal_data) + len(header_data) + len(catalog_data)
            if (
                anchor.catalog_bytes + len(catalog_data) > limits.max_catalog_bytes
                or total + reserve > limits.max_total_bytes
            ):
                raise JournalFull("segmented WAL catalog/global rotation bound reached")
            anchor = replace(
                anchor,
                catalog_count=anchor.catalog_count + 1,
                catalog_head_sha256=catalog_head,
                catalog_bytes=anchor.catalog_bytes + len(catalog_data),
                segment_number=number,
                segment_header_sha256=header_head,
                segment_frames=1,
                segment_head_sha256=header_head,
                segment_bytes=len(header_data),
                total_bytes=total,
            )
    if (
        anchor.segment_frames + 1 > limits.max_segment_frames
        or anchor.segment_bytes + len(data) > limits.max_segment_bytes
        or anchor.global_frames + 1 > limits.max_global_frames
        or anchor.total_bytes + len(data) > limits.max_total_bytes
    ):
        raise JournalFull("segmented WAL frame bound reached before publication")
    return replace(
        anchor,
        segment_frames=anchor.segment_frames + 1,
        segment_head_sha256=head,
        segment_bytes=anchor.segment_bytes + len(data),
        global_frames=anchor.global_frames + 1,
        global_head_sha256=head,
        total_bytes=anchor.total_bytes + len(data),
        checkpoint_sha256=segments._hash(document),
    )


@dataclass(frozen=True)
class RecoveryBundleIdentityV3:
    financial: plans.CompactCommitPlanStoreIdentityV3
    plan_store_identity_sha256: str
    checkpoint_wal_schema: str
    checkpoint_wal_limits_json: str

    def __post_init__(self):
        if type(self.financial) is not plans.CompactCommitPlanStoreIdentityV3:
            raise JournalError("exact sealed financial/driver/arm identity required")
        plans.CompactCommitPlanStoreIdentityV3(**asdict(self.financial))
        _sha(self.plan_store_identity_sha256)
        _wal_limits(self.checkpoint_wal_schema, _load(self.checkpoint_wal_limits_json))


@dataclass(frozen=True)
class RecoveryBundleLimitsV3:
    max_bundle_rows: int
    max_record_bytes: int
    max_database_bytes: int

    def __post_init__(self):
        for name, maximum in zip(
            self.__dataclass_fields__, (MAX_ROWS, 32 * 1024 * 1024, 1024**4), strict=True
        ):
            _positive_bound(getattr(self, name), name, maximum=maximum)
        if self.max_database_bytes < 32768:
            raise JournalError("bundle SQLite byte bound must be at least 32768")


@dataclass(frozen=True)
class RecoveryBundleAnchorV3:
    identity_sha256: str
    count: int
    head_hash: str
    last_original_sha256: str | None

    def __post_init__(self):
        _sha(self.identity_sha256)
        _sha(self.head_hash)
        _integer(self.count, "bundle count")
        if self.count == 0:
            if self.last_original_sha256 is not None:
                raise JournalError("empty bundle prefix cannot name a publication")
        else:
            _sha(self.last_original_sha256)


def _anchor(value):
    if type(value) is not RecoveryBundleAnchorV3:
        raise JournalError("independent exact recovery-bundle anchor required")
    return RecoveryBundleAnchorV3(**asdict(value))


@dataclass(frozen=True)
class RecoveryPublicationV3:
    original_json: str

    def __post_init__(self):
        value = _load(self.original_json)
        if type(value) is not dict or set(value) != _FIELDS or value["kind"] not in {"CHECKPOINT", "PLAN"}:
            raise JournalError("closed exact original bundle publication required")

    def document(self):
        return _load(self.original_json)


@dataclass(frozen=True)
class RecoveryBundleReceiptV3:
    before_anchor: RecoveryBundleAnchorV3
    anchor: RecoveryBundleAnchorV3
    publication_id: str
    replayed: bool

    def __bool__(self):
        raise JournalError("bundle receipt is not a sink callback ACK; use the exact bound binder")


@dataclass(frozen=True)
class RecoveryBundleSnapshotV3:
    anchor: RecoveryBundleAnchorV3
    checkpoint: object
    wal_anchor: object
    plan_anchor: plans.PlanStoreAnchorV3
    active_plan: object | None


def _plan_receipt(before, plan):
    """Original first-persist receipt predicted from known bytes/prefix only."""
    encoded = _canonical(compact_commit_plan_document(plan))
    row = {
        "ordinal": before.count + 1,
        "driver_before_version": plan.expected_before.version,
        "event_id": plan.expected_event_id,
        "plan_sha256": _hash(encoded),
        "plan_bytes": len(encoded.encode("utf-8")),
        "previous_hash": before.head_hash,
    }
    head = _hash(
        _canonical(
            [
                plans.SCHEMA,
                before.identity_sha256,
                row["previous_hash"],
                row["ordinal"],
                row["driver_before_version"],
                row["event_id"],
                row["plan_sha256"],
                row["plan_bytes"],
            ]
        )
    )
    after = plans.PlanStoreAnchorV3(before.identity_sha256, row["ordinal"], head, row["plan_sha256"])
    return plans.PlanStoreReceiptV3(
        before, after, row["ordinal"], row["plan_sha256"], plan.expected_event_id, False
    )


def _publication_id(record):
    if record["kind"] == "PLAN":
        return f"PLAN:{record['plan']['expected_event_id']}"
    return f"CHECKPOINT:{_hash(_canonical(record['checkpoint']))}"


class RecoveryBundleStoreV3:
    """Original indexed publications; never a generic latest-head recovery API."""

    def __init__(self, connection, path, identity, limits):
        if type(identity) is not RecoveryBundleIdentityV3 or type(limits) is not RecoveryBundleLimitsV3:
            raise JournalError("typed recovery identity and explicit bundle limits required")
        identity.__post_init__()
        limits.__post_init__()
        self._connection, self.path, self.identity, self.limits = connection, path, identity, limits
        self._physical = _file_identity(path)
        self._lock, self._active = threading.RLock(), False
        self._retained, self._observed = None, None
        self._sealed = self._configuration()
        self._identity_sha256 = _hash(_canonical(self._sealed))

    def _configuration(self):
        return {
            "schema": SCHEMA,
            "identity_json": _canonical(asdict(self.identity)),
            "limits_json": _canonical(asdict(self.limits)),
            "authority": "RESEARCH_ONLY_NONE",
        }

    def _checkpoint(self, document):
        checkpoint = root_wal.checkpoint_from_document(document)
        identity = self.identity.financial
        if (
            checkpoint.identity_sha256 != identity.driver_identity_sha256
            or checkpoint.driver_checkpoint.identity_sha256 != identity.driver_checkpoint_identity_sha256
        ):
            raise JournalError("bundle driver/experiment identity changed")
        accounts = dict(identity.account_identity_sha256)
        for arm, cp in checkpoint.arm_checkpoints:
            if cp.owner_id != identity.campaign_id or cp.identity_sha256 != accounts[arm]:
                raise JournalError("bundle exact financial owner/account identity changed")
        return checkpoint

    def _initial(self, checkpoint, wal_anchor, plan_anchor):
        document = root_wal.checkpoint_document(checkpoint)
        self._checkpoint(document)
        if (
            checkpoint.operation_cursor
            or checkpoint.pending_operation is not None
            or checkpoint.driver_checkpoint.version
            or any(cp.version or cp.native_count or cp.source_cursor for _, cp in checkpoint.arm_checkpoints)
        ):
            raise JournalError("new bundle cannot adopt already advanced accounts/driver")
        wal = _wal_anchor(self.identity.checkpoint_wal_schema, asdict(wal_anchor))
        plan = plans._anchor(plan_anchor)
        if (
            wal.identity_sha256 != checkpoint.identity_sha256
            or plan.count
            or plan.identity_sha256 != self.identity.plan_store_identity_sha256
        ):
            raise JournalError("new bundle needs exact independently retained empty dependency prefixes")
        if self.identity.checkpoint_wal_schema == root_wal.SCHEMA:
            if wal.frame_count != 1:
                raise JournalError("new ROOT bundle requires WAL bootstrap only")
        elif (
            wal.global_frames != 1
            or wal.segment_number != 0
            or wal.checkpoint_sha256 != segments._hash(document)
        ):
            raise JournalError("new segmented bundle requires exact initial catalog/segment/checkpoint")
        return {
            "checkpoint": document,
            "wal_anchor": asdict(wal),
            "plan_anchor": asdict(plan),
            "active_plan": None,
        }

    def _genesis(self, initial_json):
        return RecoveryBundleAnchorV3(
            self._identity_sha256,
            0,
            _hash(_canonical([SCHEMA, "GENESIS", self._sealed, _hash(initial_json)])),
            None,
        )

    @classmethod
    def create(cls, path, *, identity, limits, initial_checkpoint, initial_wal_anchor, initial_plan_anchor):
        if type(identity) is not RecoveryBundleIdentityV3 or type(limits) is not RecoveryBundleLimitsV3:
            raise JournalError("typed recovery identity/limits required")
        identity.__post_init__()
        limits.__post_init__()
        path = _safe_path(path, must_exist=False)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
        connection = None
        try:
            connection = sqlite3.connect(str(path), timeout=0, isolation_level=None, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            _configure(connection)
            _set_database_bound(connection, limits.max_database_bytes)
            connection.execute("PRAGMA busy_timeout=0")
            store = cls(connection, path, identity, limits)
            state = store._initial(initial_checkpoint, initial_wal_anchor, initial_plan_anchor)
            initial = _canonical(state)
            if len(initial.encode("utf-8")) > limits.max_record_bytes:
                raise JournalFull("bundle original genesis byte bound exceeded")
            genesis = store._genesis(initial)
            connection.execute("BEGIN IMMEDIATE")
            for ddl in _DDL.values():
                connection.execute(ddl)
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.executemany(
                "INSERT INTO metadata VALUES(?,?)",
                {**store._sealed, "initial_json": initial, "genesis_hash": genesis.head_hash}.items(),
            )
            connection.execute("INSERT INTO head VALUES(1,0,?,NULL,?)", (genesis.head_hash, initial))
            store._audit()
            observed = store._data_version()
            connection.commit()
            store._retained, store._observed = genesis, observed
            return store
        except BaseException:
            if connection is not None:
                if connection.in_transaction:
                    connection.rollback()
                connection.close()
            raise  # Failed create-only files are retained; no truncate/delete/retry adoption.

    @classmethod
    def open(cls, path, *, identity, limits, expected_anchor):
        return cls._open(path, identity, limits, _anchor(expected_anchor), None)

    @classmethod
    def open_after_known_publish(
        cls, path, *, identity, limits, expected_before_anchor, expected_publication
    ):
        if type(expected_publication) is not RecoveryPublicationV3:
            raise JournalError("independently retained exact original publication required")
        return cls._open(path, identity, limits, _anchor(expected_before_anchor), expected_publication)

    @classmethod
    def _open(cls, path, identity, limits, before, known):
        path = _safe_path(path, must_exist=True)
        connection = sqlite3.connect(
            _existing_uri(path), uri=True, timeout=0, isolation_level=None, check_same_thread=False
        )
        connection.row_factory = sqlite3.Row
        try:
            store = cls(connection, path, identity, limits)
            if before.identity_sha256 != store._identity_sha256:
                raise OptimisticConflict("independent bundle identity/limits mismatch")
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            authorized = store._verify_open(before, known)
            connection.commit()
            connection.execute("PRAGMA query_only=OFF")
            _configure(connection)
            _set_database_bound(connection, limits.max_database_bytes)
            connection.execute("PRAGMA busy_timeout=0")
            connection.execute("BEGIN IMMEDIATE")
            if store._verify_open(before, known) != authorized:
                raise OptimisticConflict("bundle changed before writable recovery open")
            observed = store._data_version()
            connection.commit()
            store._retained, store._observed = authorized, observed
            return store
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
            raise

    def _verify_open(self, before, known):
        current, _ = self._audit()
        if known is None:
            if current != before:
                raise OptimisticConflict("bundle differs from exact held anchor; no latest adoption")
            return current
        if current.count != before.count + 1 or self._prefix(before.count) != before:
            raise OptimisticConflict("known publication needs exactly +1 after unchanged retained prefix")
        row = self._connection.execute(
            "SELECT * FROM publications WHERE ordinal=?", (current.count,)
        ).fetchone()
        if row["original_json"] != known.original_json or row["previous_hash"] != before.head_hash:
            raise EventConflict("new bundle is not the exact caller-retained attempted original")
        return current

    def _plan_matches(self, checkpoint, document):
        plan = compact_commit_plan_from_document(document)
        pending = checkpoint.pending_operation
        if (
            pending is None
            or checkpoint.checkpoint_phase != "INTENT_COMMITTED"
            or plan.identity_sha256 != checkpoint.identity_sha256
            or plan.expected_before != checkpoint.driver_checkpoint
            or plan.expected_payload.get("pending_sha256") != checkpoint.pending_operation_sha256
            or _canonical(plan.expected_payload.get("operation")) != _canonical(pending["operation"])
            or plan.expected_hot_state.get("cursor") != checkpoint.operation_cursor + 1
            or plan.expected_event_id != f"operation:{checkpoint.operation_cursor}:commit"
            or plan.expected_at_ms != pending["operation"]["at"]
        ):
            raise JournalError("plan is not bound to the whole independently retained committed intent")
        for arm, cp in checkpoint.arm_checkpoints:
            original = root_wal.FinancialCheckpointV3(**pending["before"][arm])
            after = root_wal.FinancialCheckpointV3(**plan.expected_payload["account_checkpoints"][arm])
            effect = pending["effects"][arm]
            if (
                (after.identity_sha256, after.owner_id, after.account_id)
                != (original.identity_sha256, original.owner_id, original.account_id)
                or after.version != original.version + (effect is not None)
                or (effect is None and after != original)
                or cp.version not in {original.version, after.version}
                or (cp.version == after.version and cp != after)
            ):
                raise JournalError("plan account receipt differs from its exact licensed native effect")
            if effect is not None and (
                after.last_clock_ms != plan.expected_at_ms or after.native_count < original.native_count
            ):
                raise JournalError("plan financial clock/native prefix does not contain its owned effect")
            if effect is not None and effect["payload"].get("kind") == "SOURCE_BATCH":
                if effect["payload"].get(
                    "first"
                ) != original.source_cursor + 1 or after.source_cursor != effect["payload"].get("last"):
                    raise JournalError("plan source receipt skips the original licensed prefix")
            elif after.source_cursor != original.source_cursor:
                raise JournalError("non-source plan cannot advance original source cursor")
        return plan

    def _completed(self, checkpoint, plan, receipt):
        if type(receipt) is not dict or set(receipt) != {
            "checkpoint",
            "event_id",
            "payload",
            "outcome",
            "hot_state",
        }:
            raise JournalError("completed bundle requires exact owned compact COMMIT receipt")
        before, after = plan.expected_before, checkpoint.driver_checkpoint
        if (
            after.version != before.version + 1
            or after.identity_sha256 != before.identity_sha256
            or after.last_clock_ms != plan.expected_at_ms
            or after.state_hash != _hash(_canonical(plan.expected_hot_state))
            or _canonical(receipt["checkpoint"]) != _canonical(asdict(after))
            or receipt["event_id"] != plan.expected_event_id
            or _canonical(receipt["payload"]) != _canonical(plan.expected_payload)
            or _canonical(receipt["outcome"]) != _canonical(plan.expected_outcome)
            or _canonical(receipt["hot_state"]) != _canonical(plan.expected_hot_state)
            or _canonical(dict((arm, asdict(cp)) for arm, cp in checkpoint.arm_checkpoints))
            != _canonical(plan.expected_payload["account_checkpoints"])
            or checkpoint.operation_cursor != plan.expected_hot_state["cursor"]
        ):
            raise JournalError(
                "completed checkpoint differs from retained plan and exact owned driver receipt"
            )

    def _apply(self, previous, record):
        old = self._checkpoint(previous["checkpoint"])
        checkpoint = self._checkpoint(record["checkpoint"])
        profile = self.identity.checkpoint_wal_schema
        old_wal = _wal_anchor(profile, previous["wal_anchor"])
        old_plan = plans.PlanStoreAnchorV3(**previous["plan_anchor"])
        if record["wal_before"] != previous["wal_anchor"] or record["plan_before"] != previous["plan_anchor"]:
            raise JournalError("publication dependency prefix differs from retained original bundle")
        state = _load(_canonical(previous))
        if record["kind"] == "PLAN":
            if (
                record["checkpoint"] != previous["checkpoint"]
                or record["wal_after"] != previous["wal_anchor"]
                or record["wal_segment_sha256"] is not None
                or record["driver_receipt"] is not None
                or previous["active_plan"] is not None
            ):
                raise JournalError("plan cannot rewrite a checkpoint/WAL or replace an active original")
            plan = self._plan_matches(checkpoint, record["plan"])
            receipt = _plan_receipt(old_plan, plan)
            if (
                old_plan.count != checkpoint.operation_cursor
                or record["plan_after"] != asdict(receipt.anchor)
                or record["plan_receipt"] != asdict(receipt)
            ):
                raise JournalError("plan original receipt/count/head is not the exact owned +1 prefix")
            state.update(plan_anchor=record["plan_after"], active_plan=record["plan"])
        else:
            if (
                record["plan_after"] != previous["plan_anchor"]
                or record["plan"] is not None
                or record["plan_receipt"] is not None
            ):
                raise JournalError("checkpoint publication cannot manufacture plan-store progress")
            if profile == root_wal.SCHEMA and record["wal_segment_sha256"] is not None:
                raise JournalError("ROOT WAL cannot carry a segmented prefix digest")
            expected = _next_wal(
                profile,
                _wal_limits(profile, _load(self.identity.checkpoint_wal_limits_json)),
                old_wal,
                old,
                checkpoint,
                record["wal_segment_sha256"],
            )
            if record["wal_after"] != asdict(expected):
                raise JournalError("WAL publication is not the exact original known append/rotation")
            if old.pending_operation is not None and checkpoint.pending_operation is None:
                if previous["active_plan"] is None:
                    raise JournalError("completed ACK lacks a previously durable original commit plan")
                plan = self._plan_matches(old, previous["active_plan"])
                self._completed(checkpoint, plan, record["driver_receipt"])
                state["active_plan"] = None
            elif record["driver_receipt"] is not None:
                raise JournalError("only completed checkpoint may retain a driver COMMIT receipt")
            state.update(checkpoint=record["checkpoint"], wal_anchor=record["wal_after"])
        if len(_canonical(state).encode("utf-8")) > self.limits.max_record_bytes * 2:
            raise JournalFull("bounded current bundle projection exceeded")
        return state

    def _original(self, publication):
        if type(publication) is not RecoveryPublicationV3:
            raise JournalError("exact typed original publication required")
        encoded = publication.original_json
        if len(encoded.encode("utf-8")) > self.limits.max_record_bytes:
            raise JournalFull("original bundle record byte bound exceeded; never omit originals")
        return publication.document(), encoded

    def _check_storage(self):
        if self._configuration() != self._sealed or _file_identity(self.path) != self._physical:
            raise JournalError("owned bundle configuration/file identity changed")
        _verify_database_file_size(self.path, self.limits.max_database_bytes, self._connection)
        _verify_database_pages(self._connection, self.limits.max_database_bytes)
        if (
            self._connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
            or self._connection.execute("PRAGMA synchronous").fetchone()[0] != 2
            or self._connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete"
        ):
            raise JournalError("exact recovery-bundle schema/DELETE/FULL required")
        actual = {
            row["name"]: _normalize_sql(row["sql"])
            for row in self._connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            )
        }
        if actual != {name: _normalize_sql(sql) for name, sql in _DDL.items()}:
            raise JournalError("exact bundle SQLite schema whitelist differs")
        metadata = dict(self._connection.execute("SELECT key,value FROM metadata"))
        if set(metadata) != set(self._sealed) | {"initial_json", "genesis_hash"} or any(
            metadata.get(k) != v for k, v in self._sealed.items()
        ):
            raise JournalError("sealed bundle identity/limits metadata differ")
        initial = _load(metadata["initial_json"])
        if type(initial) is not dict or set(initial) != {
            "checkpoint",
            "wal_anchor",
            "plan_anchor",
            "active_plan",
        }:
            raise JournalError("closed original bundle genesis required")
        rebuilt = self._initial(
            self._checkpoint(initial["checkpoint"]),
            _wal_anchor(self.identity.checkpoint_wal_schema, initial["wal_anchor"]),
            plans.PlanStoreAnchorV3(**initial["plan_anchor"]),
        )
        if (
            initial != rebuilt
            or len(metadata["initial_json"].encode("utf-8")) > self.limits.max_record_bytes
            or metadata["genesis_hash"] != self._genesis(metadata["initial_json"]).head_hash
        ):
            raise JournalError("original bundle genesis/configuration commitment differs")
        return metadata

    def _row_hash(self, row):
        return _hash(
            _canonical(
                [
                    SCHEMA,
                    self._identity_sha256,
                    row["previous_hash"],
                    row["ordinal"],
                    row["publication_id"],
                    row["original_sha256"],
                    row["original_bytes"],
                ]
            )
        )

    def _row(self, row):
        publication = RecoveryPublicationV3(row["original_json"])
        record, encoded = self._original(publication)
        if (
            row["ordinal"] < 1
            or row["ordinal"] > self.limits.max_bundle_rows
            or row["publication_id"] != _publication_id(record)
            or row["original_sha256"] != _hash(encoded)
            or row["original_bytes"] != len(encoded.encode("utf-8"))
            or row["record_hash"] != self._row_hash(row)
        ):
            raise JournalError("original publication bytes/order/hash differ")
        _sha(row["previous_hash"])
        return publication

    def _prefix(self, count):
        if count == 0:
            metadata = self._check_storage()
            return self._genesis(metadata["initial_json"])
        row = self._connection.execute("SELECT * FROM publications WHERE ordinal=?", (count,)).fetchone()
        if row is None:
            raise JournalError("original publication prefix missing")
        self._row(row)
        return RecoveryBundleAnchorV3(
            self._identity_sha256, count, row["record_hash"], row["original_sha256"]
        )

    def _current(self):
        row = self._connection.execute("SELECT * FROM head WHERE singleton=1").fetchone()
        if row is None:
            raise JournalError("bounded bundle head missing")
        current = RecoveryBundleAnchorV3(
            self._identity_sha256, row["count"], row["head_hash"], row["last_original_sha256"]
        )
        if (
            current.count > self.limits.max_bundle_rows
            or self._prefix(current.count) != current
            or self._connection.execute(
                "SELECT ordinal FROM publications WHERE ordinal>? LIMIT 1", (current.count,)
            ).fetchone()
        ):
            raise JournalError("bundle indexed head/tail/unprojected rows differ")
        state = _load(row["state_json"])
        if (
            type(state) is not dict
            or set(state) != {"checkpoint", "wal_anchor", "plan_anchor", "active_plan"}
            or len(row["state_json"].encode("utf-8")) > self.limits.max_record_bytes * 2
        ):
            raise JournalError("bounded bundle projection schema/bytes differ")
        return current, state

    def _data_version(self):
        return self._connection.execute("PRAGMA data_version").fetchone()[0]

    def _audit(self):
        metadata = self._check_storage()
        if self._connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise JournalError("bundle full SQLite integrity check failed")
        current, state = self._genesis(metadata["initial_json"]), _load(metadata["initial_json"])
        for row in self._connection.execute("SELECT * FROM publications ORDER BY ordinal"):
            original = self._row(row)
            if row["ordinal"] != current.count + 1 or row["previous_hash"] != current.head_hash:
                raise JournalError("complete original publication chain/order differs")
            state = self._apply(state, original.document())
            current = RecoveryBundleAnchorV3(
                self._identity_sha256, row["ordinal"], row["record_hash"], row["original_sha256"]
            )
        indexed, projection = self._current()
        if current != indexed or _canonical(state) != _canonical(projection):
            raise JournalError("full original bundle chain differs from hot projection")
        return current, state

    def _guard(self, expected):
        expected = _anchor(expected)
        self._check_storage()
        observed = self._data_version()
        if observed != self._observed:
            self._audit()
        current, state = self._current()
        if expected != self._retained or current != self._retained:
            raise OptimisticConflict("bundle changed outside exact caller-retained own prefix")
        return current, state, observed

    def _rollback(self):
        if self._connection.in_transaction:
            self._connection.rollback()

    def _commit(self):
        self._connection.commit()

    def _snapshot(self, anchor, state):
        return RecoveryBundleSnapshotV3(
            anchor,
            self._checkpoint(state["checkpoint"]),
            _wal_anchor(self.identity.checkpoint_wal_schema, state["wal_anchor"]),
            plans.PlanStoreAnchorV3(**state["plan_anchor"]),
            None if state["active_plan"] is None else compact_commit_plan_from_document(state["active_plan"]),
        )

    @_serialized
    def snapshot(self, *, expected_anchor):
        self._connection.execute("BEGIN")
        try:
            anchor, state, observed = self._guard(expected_anchor)
            result = self._snapshot(anchor, state)
            self._connection.commit()
            self._observed = observed
            return result
        except BaseException:
            self._rollback()
            raise

    @_serialized
    def audit(self, *, expected_anchor):
        self._connection.execute("BEGIN")
        try:
            anchor, _, observed = self._guard(expected_anchor)
            audited, state = self._audit()
            if audited != anchor:
                raise JournalError("bundle changed during complete pinned audit")
            self._connection.commit()
            self._observed = observed
            return self._snapshot(anchor, state)
        except BaseException:
            self._rollback()
            raise

    @_serialized
    def lookup(self, publication_id, *, expected_anchor):
        if type(publication_id) is not str or not publication_id or len(publication_id.encode("utf-8")) > 512:
            raise JournalError("exact bounded publication ID required")
        self._connection.execute("BEGIN")
        try:
            _, _, observed = self._guard(expected_anchor)
            row = self._connection.execute(
                "SELECT * FROM publications WHERE publication_id=?", (publication_id,)
            ).fetchone()
            result = None if row is None else self._row(row)
            self._connection.commit()
            self._observed = observed
            return result
        except BaseException:
            self._rollback()
            raise

    @_serialized
    def publish(self, publication, *, expected_anchor):
        record, encoded = self._original(publication)
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            before, state, observed = self._guard(expected_anchor)
            key = _publication_id(record)
            old = self._connection.execute(
                "SELECT * FROM publications WHERE publication_id=?", (key,)
            ).fetchone()
            if old is not None:
                self._row(old)
                if old["original_json"] != encoded:
                    raise EventConflict("publication ID conflicts with preserved original bytes")
                self._connection.commit()
                self._observed = observed
                return RecoveryBundleReceiptV3(before, before, key, True)
            if before.count >= self.limits.max_bundle_rows:
                raise JournalFull("bundle row budget reached; no original pruned")
            if (
                record["kind"] == "CHECKPOINT"
                and record["checkpoint"]["checkpoint_phase"] == "PREPARED_INTENT"
                and before.count + OPERATION_RECORD_RESERVE > self.limits.max_bundle_rows
            ):
                raise JournalFull("bundle must reserve complete operation rows BEFORE any new effects")
            after_state = self._apply(state, record)
            row = {
                "ordinal": before.count + 1,
                "publication_id": key,
                "original_json": encoded,
                "original_sha256": _hash(encoded),
                "original_bytes": len(encoded.encode("utf-8")),
                "previous_hash": before.head_hash,
            }
            row["record_hash"] = self._row_hash(row)
            self._connection.execute("INSERT INTO publications VALUES(?,?,?,?,?,?,?)", tuple(row.values()))
            after = RecoveryBundleAnchorV3(
                self._identity_sha256, row["ordinal"], row["record_hash"], row["original_sha256"]
            )
            self._connection.execute(
                "UPDATE head SET count=?,head_hash=?,last_original_sha256=?,state_json=? WHERE singleton=1",
                (after.count, after.head_hash, after.last_original_sha256, _canonical(after_state)),
            )
            if self._current() != (after, after_state):
                raise JournalError("original bundle and head projection differ before publication")
            _verify_database_pages(self._connection, self.limits.max_database_bytes)
            self._commit()
            self._retained, self._observed = after, observed
            return RecoveryBundleReceiptV3(before, after, key, False)
        except BaseException as error:
            self._rollback()
            if isinstance(error, sqlite3.DatabaseError) and "full" in str(error).casefold():
                raise JournalFull("bundle SQLite byte budget exhausted; publication rolled back") from error
            raise

    def close(self):
        with self._lock:
            if self._active:
                raise JournalError("cannot close during active bundle operation")
            self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def open_checkpoint_wal_after_known_publication(
    path, *, identity, expected_before_checkpoint, expected_before_wal_anchor, expected_publication
):
    """Full WAL open at a DERIVED exact known append/rotation, never observed latest.

    For zero new frames use ordinary exact WAL open. Partial/torn rotation is
    retained and refused by the frozen segmented implementation; no repair.
    """
    if (
        type(identity) is not RecoveryBundleIdentityV3
        or type(expected_publication) is not RecoveryPublicationV3
    ):
        raise JournalError("typed independently retained known checkpoint publication required")
    record = expected_publication.document()
    if record["kind"] != "CHECKPOINT" or record["wal_before"] != asdict(expected_before_wal_anchor):
        raise JournalError("known WAL publication differs from exact retained original prefix")
    profile = identity.checkpoint_wal_schema
    after = _next_wal(
        profile,
        _wal_limits(profile, _load(identity.checkpoint_wal_limits_json)),
        expected_before_wal_anchor,
        expected_before_checkpoint,
        root_wal.checkpoint_from_document(record["checkpoint"]),
        record["wal_segment_sha256"],
    )
    if after == expected_before_wal_anchor or asdict(after) != record["wal_after"]:
        raise JournalError("known WAL recovery requires exactly its derived original append")
    cls = (
        root_wal.FourArmCheckpointWalV3
        if profile == root_wal.SCHEMA
        else segments.SegmentedFourArmCheckpointWalV3
    )
    wal = cls.open(path, expected_anchor=after)
    try:
        if root_wal.checkpoint_document(wal.snapshot().checkpoint) != record["checkpoint"]:
            raise JournalError("known checkpoint WAL original differs")
        return wal
    except BaseException:
        wal.close()
        raise


class CompactFourArmRecoveryBinderV3:
    """Two real sink callbacks, only ACK after exact external bundle publication.

    Caller owns driver/WAL/plan-store lifecycle; close only closes the owned
    bundle connection. Independent restart uses store.snapshot(expected_anchor)
    then opens each dependency at THAT exact prefix. A lost publication response
    needs the exact attempted last_attempt retained/reconstructed by the caller,
    never a plan or future financial checkpoint read from an observed DB head.
    """

    def __init__(
        self, store, *, driver, checkpoint_wal, plan_store, expected_anchor, expected_publication=None
    ):
        if (
            type(store) is not RecoveryBundleStoreV3
            or type(driver) is not CompactFourArmDriverV3
            or type(driver.journal) is not CompactFourArmDriverJournalV3
            or type(plan_store) is not plans.CompactCommitPlanStoreV3
            or type(checkpoint_wal)
            not in {root_wal.FourArmCheckpointWalV3, segments.SegmentedFourArmCheckpointWalV3}
        ):
            raise JournalError(
                "actual explicit compact driver, owned WAL and independent plan store required"
            )
        self.store, self.driver, self.wal, self.plan_store = store, driver, checkpoint_wal, plan_store
        self._driver_journal, self._wal, self._plan_store = driver.journal, checkpoint_wal, plan_store
        self._anchor = _anchor(expected_anchor)
        self._lock, self._active, self._poisoned = threading.RLock(), False, False
        self.last_attempt = None
        if (
            driver.prepared.account_profile != COMPACT_FINANCIAL_PROFILE
            or driver.prepared.identity_sha256 != store.identity.financial.driver_identity_sha256
            or plan_store.identity != store.identity.financial
            or plan_store.anchor().identity_sha256 != store.identity.plan_store_identity_sha256
        ):
            raise JournalError("sealed financial driver/plan-store identity conflict")
        wal = checkpoint_wal.snapshot()
        profile = (
            root_wal.SCHEMA if type(checkpoint_wal) is root_wal.FourArmCheckpointWalV3 else segments.SCHEMA
        )
        if (
            profile != store.identity.checkpoint_wal_schema
            or _canonical(asdict(wal.limits)) != store.identity.checkpoint_wal_limits_json
        ):
            raise JournalError("explicit WAL profile/limits differ from bundle identity")
        state = self.snapshot()
        if expected_publication is not None:
            store._original(expected_publication)
            store._apply(self._state(state), expected_publication.document())
            self.last_attempt = expected_publication
        self._dependencies(state, expected_publication)
        self._driver_compatible(state, expected_publication)

    @classmethod
    def create(cls, path, *, driver, checkpoint_wal, plan_store, limits):
        if (
            type(driver) is not CompactFourArmDriverV3
            or type(plan_store) is not plans.CompactCommitPlanStoreV3
        ):
            raise JournalError("actual compact financial driver and plan store required")
        inspection = checkpoint_wal.snapshot()
        profile = (
            root_wal.SCHEMA if type(checkpoint_wal) is root_wal.FourArmCheckpointWalV3 else segments.SCHEMA
        )
        identity = RecoveryBundleIdentityV3(
            plan_store.identity,
            plan_store.anchor().identity_sha256,
            profile,
            _canonical(asdict(inspection.limits)),
        )
        checkpoint = driver.checkpoint()
        if root_wal.checkpoint_document(inspection.checkpoint) != root_wal.checkpoint_document(checkpoint):
            raise JournalError("initial WAL does not retain exact original driver checkpoint")
        store = RecoveryBundleStoreV3.create(
            path,
            identity=identity,
            limits=limits,
            initial_checkpoint=checkpoint,
            initial_wal_anchor=inspection.anchor,
            initial_plan_anchor=plan_store.anchor(),
        )
        try:
            return cls(
                store,
                driver=driver,
                checkpoint_wal=checkpoint_wal,
                plan_store=plan_store,
                expected_anchor=store._retained,
            )
        except BaseException:
            store.close()
            raise

    def _state(self, snapshot):
        return {
            "checkpoint": root_wal.checkpoint_document(snapshot.checkpoint),
            "wal_anchor": asdict(snapshot.wal_anchor),
            "plan_anchor": asdict(snapshot.plan_anchor),
            "active_plan": None
            if snapshot.active_plan is None
            else compact_commit_plan_document(snapshot.active_plan),
        }

    def snapshot(self):
        return self.store.snapshot(expected_anchor=self._anchor)

    def _dependencies(self, state, publication=None):
        if (
            self.driver.journal is not self._driver_journal
            or self.wal is not self._wal
            or self.plan_store is not self._plan_store
        ):
            raise JournalError("binder owned dependency object changed")
        wal = self.wal.snapshot()
        expected_wal, expected_checkpoint, expected_plan = (
            state.wal_anchor,
            state.checkpoint,
            state.plan_anchor,
        )
        if publication is not None:
            record = publication.document()
            expected_wal = _wal_anchor(self.store.identity.checkpoint_wal_schema, record["wal_after"])
            expected_checkpoint = root_wal.checkpoint_from_document(record["checkpoint"])
            expected_plan = plans.PlanStoreAnchorV3(**record["plan_after"])
        if (
            wal.anchor != expected_wal
            or root_wal.checkpoint_document(wal.checkpoint)
            != root_wal.checkpoint_document(expected_checkpoint)
            or self.plan_store.anchor() != expected_plan
        ):
            raise OptimisticConflict(
                "WAL/plan store advanced outside exact retained bundle or known publication"
            )
        if publication is not None and publication.document()["kind"] == "PLAN":
            record = publication.document()
            plan = compact_commit_plan_from_document(record["plan"])
            actual = self.plan_store.lookup(
                before_version=plan.expected_before.version,
                event_id=plan.expected_event_id,
                expected_anchor=expected_plan,
            )
            if actual is None or _canonical(compact_commit_plan_document(actual)) != _canonical(
                record["plan"]
            ):
                raise JournalError("known plan dependency lacks its exact original retained bytes")
        elif state.active_plan is not None:
            plan = state.active_plan
            actual = self.plan_store.lookup(
                before_version=plan.expected_before.version,
                event_id=plan.expected_event_id,
                expected_anchor=expected_plan,
            )
            if actual != plan:
                raise JournalError("active durable bundle plan differs from pinned original plan ledger")

    def _driver_receipt(self, checkpoint, plan):
        result = self.driver.journal.lookup(
            event_id=plan.expected_event_id,
            payload=plan.expected_payload,
            at_ms=plan.expected_at_ms,
            expected_checkpoint=checkpoint.driver_checkpoint,
        )
        if result is None:
            raise JournalError("actual owned driver lacks the exact planned COMMIT")
        value = result.snapshot
        actual = DeltaCheckpointV3(
            checkpoint.driver_checkpoint.identity_sha256,
            value.version,
            value.state_hash,
            value.head_hash,
            value.last_clock_ms,
        )
        if (
            actual != checkpoint.driver_checkpoint
            or _canonical(value.state) != _canonical(plan.expected_hot_state)
            or result.outcome != plan.expected_outcome
        ):
            raise JournalError("owned indexed driver COMMIT differs from retained original plan")
        receipt = {
            "checkpoint": asdict(actual),
            "event_id": plan.expected_event_id,
            "payload": plan.expected_payload,
            "outcome": result.outcome,
            "hot_state": value.state,
        }
        self.store._completed(checkpoint, plan, receipt)
        return receipt

    def _driver_compatible(self, state, publication=None):
        self.driver._assert_driver_head()
        current = self.driver.checkpoint()
        expected = (
            state.checkpoint
            if publication is None
            else root_wal.checkpoint_from_document(publication.document()["checkpoint"])
        )
        if current.driver_checkpoint == expected.driver_checkpoint:
            if expected.pending_operation is None and current != expected:
                raise JournalError("owned completed driver checkpoint differs from exact bundle")
            if expected.pending_operation is not None:
                self.driver._verify_effects(expected.pending_operation)
            return
        if state.active_plan is not None and current.pending_operation is None:
            self._driver_receipt(current, state.active_plan)
            return
        raise OptimisticConflict("driver advanced outside exact retained checkpoint/known planned COMMIT")

    def _preflight(self, state, publication):
        record, _ = self.store._original(publication)
        self.store._apply(self._state(state), record)
        if state.anchor.count >= self.store.limits.max_bundle_rows:
            raise JournalFull("bundle row budget exhausted before dependency writes")
        if (
            record["kind"] == "CHECKPOINT"
            and record["checkpoint"]["checkpoint_phase"] == "PREPARED_INTENT"
            and state.anchor.count + OPERATION_RECORD_RESERVE > self.store.limits.max_bundle_rows
        ):
            raise JournalFull("complete operation bundle reserve absent before financial effects")

    def _own_publication(self, publication):
        before = self._anchor
        receipt = self.store.publish(publication, expected_anchor=before)
        if receipt.replayed or receipt.before_anchor != before or receipt.anchor.count != before.count + 1:
            raise JournalError("binder can advance only by its exact fresh owned publication receipt")
        self._anchor = receipt.anchor
        return receipt

    def checkpoint_sink(self, checkpoint):
        with self._lock:
            if self._active or self._poisoned:
                raise JournalError("active/unknown binder response requires explicit exact recovery")
            self._active = True
            try:
                state = self.snapshot()
                self._dependencies(state)
                self.driver._assert_driver_head()
                if checkpoint.driver_checkpoint != self.driver._driver_checkpoint:
                    raise JournalError("checkpoint is not the owned returned driver head")
                for arm, value in checkpoint.arm_checkpoints:
                    if self.driver.accounts[arm].journal.checkpoint() != value:
                        raise JournalError("checkpoint native receipt is not the exact owned account head")
                if root_wal.checkpoint_document(checkpoint) == root_wal.checkpoint_document(state.checkpoint):
                    self._driver_compatible(state)
                    return True  # Already published original, not an unknown response.
                wal = self.wal.snapshot()
                digest = (
                    self.wal._segment_digest.hexdigest()
                    if type(self.wal) is segments.SegmentedFourArmCheckpointWalV3
                    else None
                )
                after = _next_wal(
                    self.store.identity.checkpoint_wal_schema,
                    wal.limits,
                    state.wal_anchor,
                    state.checkpoint,
                    checkpoint,
                    digest,
                )
                driver_receipt = None
                if state.checkpoint.pending_operation is not None and checkpoint.pending_operation is None:
                    if state.active_plan is None:
                        raise JournalError("COMPLETED requires a previously published exact original plan")
                    driver_receipt = self._driver_receipt(checkpoint, state.active_plan)
                publication = RecoveryPublicationV3(
                    _canonical(
                        {
                            "kind": "CHECKPOINT",
                            "checkpoint": root_wal.checkpoint_document(checkpoint),
                            "wal_before": asdict(state.wal_anchor),
                            "wal_after": asdict(after),
                            "wal_segment_sha256": digest,
                            "plan_before": asdict(state.plan_anchor),
                            "plan_after": asdict(state.plan_anchor),
                            "plan": None,
                            "plan_receipt": None,
                            "driver_receipt": driver_receipt,
                        }
                    )
                )
                self._preflight(state, publication)
                self.last_attempt = publication  # Exact attempt from caller/owned prefix, BEFORE WAL writes.
                if self.wal(checkpoint) is not True:
                    raise JournalError("unknown checkpoint WAL response cannot license bundle/financial ACK")
                self._dependencies(state, publication)
                self._own_publication(publication)
                self._dependencies(self.snapshot())
                self.driver._assert_driver_head()
                self.last_attempt = None
                return True  # ONLY after owned WAL fsync AND successful SQL bundle publication.
            except BaseException:
                self._poisoned = True
                raise
            finally:
                self._active = False

    def commit_plan_sink(self, plan):
        with self._lock:
            if self._active or self._poisoned:
                raise JournalError("active/unknown binder response requires explicit exact recovery")
            self._active = True
            try:
                state = self.snapshot()
                self._dependencies(state)
                self._driver_compatible(state)
                frozen = compact_commit_plan_from_document(compact_commit_plan_document(plan))
                self.store._plan_matches(state.checkpoint, compact_commit_plan_document(frozen))
                for arm, document in frozen.expected_payload["account_checkpoints"].items():
                    if asdict(self.driver.accounts[arm].journal.checkpoint()) != document:
                        raise JournalError(
                            "plan future account receipt is not its exact current owned effect"
                        )
                if state.active_plan is not None:
                    if compact_commit_plan_document(state.active_plan) != compact_commit_plan_document(
                        frozen
                    ):
                        raise EventConflict("active original plan cannot be replaced after a lost response")
                    return True  # Redelivery of ALREADY published exact original.
                receipt = _plan_receipt(state.plan_anchor, frozen)
                publication = RecoveryPublicationV3(
                    _canonical(
                        {
                            "kind": "PLAN",
                            "checkpoint": root_wal.checkpoint_document(state.checkpoint),
                            "wal_before": asdict(state.wal_anchor),
                            "wal_after": asdict(state.wal_anchor),
                            "wal_segment_sha256": None,
                            "plan_before": asdict(state.plan_anchor),
                            "plan_after": asdict(receipt.anchor),
                            "plan": compact_commit_plan_document(frozen),
                            "plan_receipt": asdict(receipt),
                            "driver_receipt": None,
                        }
                    )
                )
                self._preflight(state, publication)
                self.last_attempt = publication
                actual = self.plan_store.persist(frozen, expected_anchor=state.plan_anchor)
                if type(actual) is not plans.PlanStoreReceiptV3 or asdict(actual) != asdict(receipt):
                    raise JournalError("unknown/mismatched plan-store receipt cannot license bundle ACK")
                self._dependencies(state, publication)
                self._own_publication(publication)
                self._dependencies(self.snapshot())
                self.driver._assert_driver_head()
                self.last_attempt = None
                return True  # NOT the plan receipt; own external bundle publication completed.
            except BaseException:
                self._poisoned = True
                raise
            finally:
                self._active = False

    def resume_publication(self, *, expected_publication):
        """Explicit caller-retained dependency-complete publication, NOT a True ACK.

        Reopen dependencies at known derived anchors first. This resumes only
        publication, never account effects/COMMIT or a new financial operation.
        """
        with self._lock:
            if self._active or type(expected_publication) is not RecoveryPublicationV3:
                raise JournalError("explicit independently retained original publication required")
            if self.last_attempt is not None and self.last_attempt != expected_publication:
                raise EventConflict("resume differs from retained owned original attempt")
            state = self.snapshot()
            self._preflight(state, expected_publication)
            self._dependencies(state, expected_publication)
            self._driver_compatible(state, expected_publication)
            receipt = self._own_publication(expected_publication)
            self._dependencies(self.snapshot())
            self.last_attempt, self._poisoned = None, False
            return receipt  # Never itself a sink True; driver redelivers its independently held phase.

    def close(self):
        self.store.close()
