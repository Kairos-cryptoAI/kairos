"""Independent create-only, indexed ledger of exact compact driver COMMIT plans.

persist returns a receipt, NEVER a durability ACK for the financial driver.
External durable recovery-bundle publication is still required and is NOT
implemented here. No callable sink, adoption of latest, migration, deletion,
repair, economic mutation or authorization to start a historical replay.

SQLite DELETE/FULL commits preserve all original canonical plan bytes. Owned
appends use a small indexed head/tail, not COUNT or historical replay. Open and
audit verify the complete ledger; external SQLite commits trigger full audit
before any lookup/duplicate response. Hashes provide local consistency, not
hostile-file authentication or hardware/power-loss durability guarantees.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import asdict, dataclass
from functools import wraps

from .compact_four_arm_driver_journal_v3 import COLLECTIONS, HOT_FIELDS, _accounts
from .compact_four_arm_driver_journal_v3 import SCHEMA as DRIVER_SCHEMA
from .continuous_four_arm_v3 import (
    ARMS,
    CompactCommitPlanV3,
    compact_commit_plan_document,
    compact_commit_plan_from_document,
)
from .sim_delta_journal_v3 import _load, _sha
from .sim_state_journal import (
    EventConflict,
    JournalError,
    JournalFull,
    OptimisticConflict,
    _canonical,
    _clock,
    _configure,
    _existing_uri,
    _file_identity,
    _hash,
    _identifier,
    _normalize_sql,
    _positive_bound,
    _safe_path,
    _set_database_bound,
    _verify_database_file_size,
    _verify_database_pages,
)

SCHEMA = "kairos.research.compact-commit-plan-store.v3"
SCHEMA_VERSION = 51
MAX_ROWS = (2**63 - 1) // 2  # Two compact driver versions per original operation.
_DDL = {
    "metadata": "CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)",
    "plans": (
        "CREATE TABLE plans(ordinal INTEGER PRIMARY KEY,driver_before_version INTEGER NOT NULL UNIQUE,"
        "event_id TEXT NOT NULL UNIQUE,plan_json TEXT NOT NULL,plan_sha256 TEXT NOT NULL,"
        "plan_bytes INTEGER NOT NULL,previous_hash TEXT NOT NULL,record_hash TEXT NOT NULL)"
    ),
    "head": (
        "CREATE TABLE head(singleton INTEGER PRIMARY KEY CHECK(singleton=1),count INTEGER NOT NULL,"
        "head_hash TEXT NOT NULL,last_plan_sha256 TEXT)"
    ),
}


def _integer(value, name, maximum=2**63 - 1):
    if type(value) is not int or not 0 <= value <= maximum:
        raise JournalError(f"exact bounded nonnegative {name} required")
    return value


def _serialized(function):
    @wraps(function)
    def guarded(self, *args, **kwargs):
        with self._lock:
            if self._active:
                raise JournalError("nested plan-store operation forbidden")
            self._active = True
            try:
                return function(self, *args, **kwargs)
            finally:
                self._active = False

    return guarded


@dataclass(frozen=True)
class CompactCommitPlanStoreIdentityV3:
    campaign_id: str
    driver_identity_sha256: str
    driver_checkpoint_identity_sha256: str
    account_identity_sha256: tuple[tuple[str, str], ...]

    def __post_init__(self):
        _identifier(self.campaign_id, "campaign ID")
        _sha(self.driver_identity_sha256)
        _sha(self.driver_checkpoint_identity_sha256)
        if (
            type(self.account_identity_sha256) is not tuple
            or len(self.account_identity_sha256) != len(ARMS)
            or any(type(pair) is not tuple or len(pair) != 2 for pair in self.account_identity_sha256)
            or tuple(pair[0] for pair in self.account_identity_sha256) != ARMS
        ):
            raise JournalError("exact ordered four-arm identity roster required")
        for _, value in self.account_identity_sha256:
            _sha(value)


@dataclass(frozen=True)
class CompactCommitPlanStoreLimitsV3:
    max_plan_rows: int
    max_plan_bytes: int
    max_database_bytes: int

    def __post_init__(self):
        for name, maximum in zip(
            self.__dataclass_fields__, (MAX_ROWS, 16 * 1024 * 1024, 1024**4), strict=True
        ):
            _positive_bound(getattr(self, name), name, maximum=maximum)
        if self.max_database_bytes < 32 * 1024:
            raise JournalError("plan-store SQLite byte bound must be at least 32768")


@dataclass(frozen=True)
class PlanStoreAnchorV3:
    identity_sha256: str
    count: int
    head_hash: str
    last_plan_sha256: str | None

    def __post_init__(self):
        _sha(self.identity_sha256)
        _sha(self.head_hash)
        _integer(self.count, "plan count", MAX_ROWS)
        if self.count == 0:
            if self.last_plan_sha256 is not None:
                raise JournalError("empty plan prefix cannot name a plan")
        else:
            _sha(self.last_plan_sha256)


@dataclass(frozen=True)
class PlanStoreReceiptV3:
    before_anchor: PlanStoreAnchorV3
    anchor: PlanStoreAnchorV3
    ordinal: int
    plan_sha256: str
    event_id: str
    replayed: bool

    def __post_init__(self):
        _anchor(self.before_anchor)
        _anchor(self.anchor)
        _integer(self.ordinal, "original plan ordinal", MAX_ROWS)
        _sha(self.plan_sha256)
        _identifier(self.event_id, "original plan event ID")
        if (
            type(self.replayed) is not bool
            or self.ordinal == 0
            or self.anchor.identity_sha256 != self.before_anchor.identity_sha256
            or (self.replayed and (self.anchor != self.before_anchor or self.ordinal > self.anchor.count))
            or (
                not self.replayed
                and (
                    self.anchor.count != self.before_anchor.count + 1
                    or self.ordinal != self.anchor.count
                    or self.anchor.last_plan_sha256 != self.plan_sha256
                )
            )
        ):
            raise JournalError("receipt differs from exact own append or original indexed duplicate")

    @property
    def ack_eligible(self):
        return False

    def __bool__(self):
        raise JournalError("plan receipt is not ACK; external durable recovery bundle is absent")


def _anchor(value):
    if type(value) is not PlanStoreAnchorV3:
        raise JournalError("independent typed plan-store anchor required")
    return PlanStoreAnchorV3(**asdict(value))


class CompactCommitPlanStoreV3:
    """Single serialized connection; exact retained anchors on every read/write.

    New ledgers start at compact operation zero. Every completed operation must
    retain its plan in order. Duplicate delivery preserves the ORIGINAL bytes;
    a receipt cannot be used as the required driver's True sink ACK.
    """

    def __init__(self, connection, path, identity, limits):
        if (
            type(identity) is not CompactCommitPlanStoreIdentityV3
            or type(limits) is not CompactCommitPlanStoreLimitsV3
        ):
            raise JournalError("typed plan-store identity and explicit limits required")
        CompactCommitPlanStoreIdentityV3(**asdict(identity))
        CompactCommitPlanStoreLimitsV3(**asdict(limits))
        self._connection, self.path, self.identity, self.limits = connection, path, identity, limits
        self._physical = _file_identity(path)
        self._lock, self._active = threading.RLock(), False
        self._retained, self._observed = None, None
        self._sealed = self._configuration()
        self._identity_sha256 = _hash(_canonical(self._sealed))

    def _configuration(self):
        return {
            "schema": SCHEMA,
            "driver_schema": DRIVER_SCHEMA,
            "identity_json": _canonical(asdict(self.identity)),
            "limits_json": _canonical(asdict(self.limits)),
        }

    def _genesis(self):
        return PlanStoreAnchorV3(
            self._identity_sha256, 0, _hash(_canonical([SCHEMA, "GENESIS", self._sealed])), None
        )

    @classmethod
    def create(cls, path, *, identity, limits):
        if (
            type(identity) is not CompactCommitPlanStoreIdentityV3
            or type(limits) is not CompactCommitPlanStoreLimitsV3
        ):
            raise JournalError("typed plan-store identity and explicit limits required")
        CompactCommitPlanStoreIdentityV3(**asdict(identity))
        CompactCommitPlanStoreLimitsV3(**asdict(limits))
        destination = _safe_path(path, must_exist=False)
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
        connection = None
        try:
            connection = sqlite3.connect(
                str(destination), timeout=0, isolation_level=None, check_same_thread=False
            )
            connection.row_factory = sqlite3.Row
            _configure(connection)
            connection.execute("PRAGMA busy_timeout=0")
            _set_database_bound(connection, limits.max_database_bytes)
            journal = cls(connection, destination, identity, limits)
            connection.execute("BEGIN IMMEDIATE")
            for ddl in _DDL.values():
                connection.execute(ddl)
            genesis = journal._genesis()
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.executemany(
                "INSERT INTO metadata VALUES(?,?)",
                {**journal._sealed, "genesis_hash": genesis.head_hash}.items(),
            )
            connection.execute("INSERT INTO head VALUES(1,0,?,NULL)", (genesis.head_hash,))
            journal._audit()
            observed = journal._data_version()
            connection.commit()
            journal._retained, journal._observed = genesis, observed
            return journal
        except BaseException:
            if connection is not None:
                if connection.in_transaction:
                    connection.rollback()
                connection.close()
            raise  # Create-only orphan is retained; never delete/truncate to retry.

    @classmethod
    def open(cls, path, *, identity, limits, expected_anchor):
        return cls._open(path, identity, limits, _anchor(expected_anchor), None)

    @classmethod
    def open_after_known_persist(cls, path, *, identity, limits, expected_before_anchor, expected_plan):
        """Exactly +1 retained plan only, supplied independently of this DB head.

        This recovers a storage receipt, NOT bundle publication or a driver ACK.
        Zero/two new rows, different originals, changed prefix and unknown head
        refuse. For pre-COMMIT crash use ordinary exact open and re-persist.
        """
        if type(expected_plan) is not CompactCommitPlanV3:
            raise JournalError(
                "independently retained typed known plan required; no optional latest recovery"
            )
        return cls._open(path, identity, limits, _anchor(expected_before_anchor), expected_plan)

    @classmethod
    def _open(cls, path, identity, limits, before, known_plan):
        path = _safe_path(path, must_exist=True)
        connection = sqlite3.connect(
            _existing_uri(path), uri=True, timeout=0, isolation_level=None, check_same_thread=False
        )
        connection.row_factory = sqlite3.Row
        try:
            journal = cls(connection, path, identity, limits)
            known = None if known_plan is None else journal._plan_json(known_plan)
            if before.identity_sha256 != journal._identity_sha256:
                raise OptimisticConflict("caller plan-store identity/limits differ")
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            authorized = journal._verify_open(before, known)
            connection.commit()
            connection.execute("PRAGMA query_only=OFF")
            _configure(connection)
            _set_database_bound(connection, limits.max_database_bytes)
            connection.execute("PRAGMA busy_timeout=0")
            connection.execute("BEGIN IMMEDIATE")
            if journal._verify_open(before, known) != authorized:
                raise OptimisticConflict("plan store changed before writable open")
            observed = journal._data_version()
            connection.commit()
            journal._retained, journal._observed = authorized, observed
            return journal
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
            raise

    def _verify_open(self, before, known):
        current = self._audit()
        if known is None:
            if current != before:
                raise OptimisticConflict("exact retained plan-store anchor differs; no latest adoption")
            return current
        if current.count != before.count + 1:
            raise OptimisticConflict("known persist recovery requires exactly one new plan")
        if self._prefix_anchor(before.count) != before:
            raise OptimisticConflict("audited original prefix differs from independently retained anchor")
        row = self._connection.execute("SELECT * FROM plans WHERE ordinal=?", (current.count,)).fetchone()
        if row["previous_hash"] != before.head_hash or row["plan_json"] != known:
            raise EventConflict("persisted plan differs from exact independently retained original")
        return current

    def _plan_json(self, plan):
        try:
            encoded = _canonical(compact_commit_plan_document(plan))
            value = compact_commit_plan_from_document(_load(encoded))
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise JournalError("exact closed typed compact COMMIT plan required") from error
        if len(encoded.encode("utf-8")) > self.limits.max_plan_bytes:
            raise JournalFull("original plan byte ceiling exceeded; never truncate")
        before, payload, hot, outcome = (
            value.expected_before,
            value.expected_payload,
            value.expected_hot_state,
            value.expected_outcome,
        )
        _integer(before.version, "driver before version")
        _clock(before.last_clock_ms)
        if (
            value.identity_sha256 != self.identity.driver_identity_sha256
            or before.identity_sha256 != self.identity.driver_checkpoint_identity_sha256
            or type(hot) is not dict
            or set(hot) != HOT_FIELDS
            or hot["profile"] != DRIVER_SCHEMA
            or hot["identity"] != value.identity_sha256
            or hot["pending"] is not None
            or type(payload) is not dict
            or set(payload)
            != {"operation", "pending_sha256", "account_checkpoints", "cold_records", "report"}
            or type(outcome) is not dict
            or set(outcome) != {"status", "operation_cursor"}
        ):
            raise JournalError("plan profile/identity/closed commit schema mismatch")
        cursor = _integer(hot["cursor"], "operation cursor", MAX_ROWS)
        operation = payload["operation"]
        if (
            cursor == 0
            or before.version != cursor * 2 - 1
            or value.expected_event_id != f"operation:{cursor - 1}:commit"
            or type(operation) is not dict
            or operation.get("kind") not in {"SOURCE", "ATTEMPT", "EXPENSE", "ROUTE", "CELL", "FINISH"}
            or operation.get("at") != value.expected_at_ms
            or value.expected_at_ms < before.last_clock_ms
            or outcome != {"status": "COMMITTED", "operation_cursor": cursor}
            or type(outcome["operation_cursor"]) is not int
            or _canonical(payload["cold_records"])
            != _canonical([asdict(r) for r in value.expected_cold_records])
        ):
            raise JournalError("plan exact operation/version/clock/outcome/cold original roster mismatch")
        _clock(operation["at"])
        _sha(payload["pending_sha256"])
        accounts = _accounts(payload["account_checkpoints"])
        if _canonical(hot["account_checkpoints"]) != _canonical(payload["account_checkpoints"]):
            raise JournalError("hot account checkpoints differ from original plan payload")
        for arm, cp in accounts.items():
            if (
                cp.owner_id != self.identity.campaign_id
                or cp.identity_sha256 != dict(self.identity.account_identity_sha256)[arm]
            ):
                raise JournalError("plan financial owner/account identity changed")
        for field in ("account_config", "account_identity"):
            if type(hot[field]) is not dict or set(hot[field]) != set(ARMS):
                raise JournalError("plan exact four-arm immutable configuration roster required")
        refs = hot["history_refs"]
        if type(refs) is not dict or set(refs) != set(COLLECTIONS):
            raise JournalError("plan exact cold prefix reference roster required")
        for ref in refs.values():
            if type(ref) is not dict or set(ref) != {"count", "head"}:
                raise JournalError("plan closed cold prefix required")
            _integer(ref["count"], "cold count")
            _sha(ref["head"])
        if (
            type(hot["finished"]) is not bool
            or hot["finished"] != (operation["kind"] == "FINISH")
            or hot["report"] != payload["report"]
            or (hot["finished"] and type(hot["report"]) is not dict)
            or (not hot["finished"] and hot["report"] is not None)
        ):
            raise JournalError("plan terminal/UNKNOWN report must remain exact, never infer completion")
        return encoded

    def _data_version(self):
        return self._connection.execute("PRAGMA data_version").fetchone()[0]

    def _check_storage(self):
        if self._configuration() != self._sealed or _file_identity(self.path) != self._physical:
            raise JournalError("owned plan-store configuration/file identity changed")
        _verify_database_file_size(self.path, self.limits.max_database_bytes, self._connection)
        _verify_database_pages(self._connection, self.limits.max_database_bytes)
        if (
            self._connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
            or self._connection.execute("PRAGMA synchronous").fetchone()[0] != 2
            or self._connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete"
        ):
            raise JournalError("exact plan-store schema/DELETE/FULL durability profile required")
        actual = {
            row["name"]: _normalize_sql(row["sql"])
            for row in self._connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            )
        }
        if actual != {key: _normalize_sql(sql) for key, sql in _DDL.items()}:
            raise JournalError("plan-store exact SQLite schema whitelist differs")
        metadata = dict(self._connection.execute("SELECT key,value FROM metadata"))
        if metadata != {**self._sealed, "genesis_hash": self._genesis().head_hash}:
            raise JournalError("plan-store sealed identity/limits/genesis mismatch")

    def _row_hash(self, row):
        return _hash(
            _canonical(
                [
                    SCHEMA,
                    self._identity_sha256,
                    row["previous_hash"],
                    row["ordinal"],
                    row["driver_before_version"],
                    row["event_id"],
                    row["plan_sha256"],
                    row["plan_bytes"],
                ]
            )
        )

    def _validate_row(self, row):
        encoded = row["plan_json"]
        try:
            plan = compact_commit_plan_from_document(_load(encoded))
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise JournalError("stored plan exact closed schema differs") from error
        if (
            row["ordinal"] < 1
            or row["ordinal"] > self.limits.max_plan_rows
            or row["driver_before_version"] != row["ordinal"] * 2 - 1
            or row["event_id"] != plan.expected_event_id
            or row["driver_before_version"] != plan.expected_before.version
            or row["plan_bytes"] != len(encoded.encode("utf-8"))
            or row["plan_sha256"] != _hash(encoded)
            or row["record_hash"] != self._row_hash(row)
            or self._plan_json(plan) != encoded
        ):
            raise JournalError("plan original bytes/order/content/chain commitment differs")
        _sha(row["previous_hash"])
        return plan

    def _prefix_anchor(self, count):
        if count == 0:
            return self._genesis()
        row = self._connection.execute("SELECT * FROM plans WHERE ordinal=?", (count,)).fetchone()
        if row is None:
            raise JournalError("indexed plan prefix missing")
        self._validate_row(row)
        return PlanStoreAnchorV3(self._identity_sha256, count, row["record_hash"], row["plan_sha256"])

    def _current(self):
        head = self._connection.execute("SELECT * FROM head WHERE singleton=1").fetchone()
        if head is None:
            raise JournalError("small indexed plan head missing")
        current = PlanStoreAnchorV3(
            self._identity_sha256, head["count"], head["head_hash"], head["last_plan_sha256"]
        )
        if current.count > self.limits.max_plan_rows or self._prefix_anchor(current.count) != current:
            raise JournalError("indexed head/tail differ")
        if self._connection.execute(
            "SELECT ordinal FROM plans WHERE ordinal>? LIMIT 1", (current.count,)
        ).fetchone():
            raise JournalError("unprojected extra plan row")
        return current

    @staticmethod
    def _continuity(previous, plan):
        if previous is None:
            return
        before, after = previous.expected_hot_state, plan.expected_hot_state
        if before["finished"] or plan.expected_at_ms < previous.expected_at_ms:
            raise JournalError("plan cannot continue after FINISH or regress its exact clock")
        for field in ("identity", "profile", "account_config", "account_identity"):
            if _canonical(before[field]) != _canonical(after[field]):
                raise JournalError("immutable four-arm configuration changed between retained plans")
        for arm in ARMS:
            old, new = before["account_checkpoints"][arm], after["account_checkpoints"][arm]
            if new["version"] not in {old["version"], old["version"] + 1}:
                raise JournalError("plan account prefix skipped or regressed")
            if new["version"] == old["version"] and _canonical(old) != _canonical(new):
                raise JournalError("unchanged account version cannot change exact retained checkpoint")
            if new["source_cursor"] < old["source_cursor"] or new["native_count"] < old["native_count"]:
                raise JournalError("plan source/native original prefix regressed")
            if new["native_count"] == old["native_count"] and new["native_head"] != old["native_head"]:
                raise JournalError("unchanged native prefix cannot change its exact head")
        for kind in COLLECTIONS:
            old, new = before["history_refs"][kind], after["history_refs"][kind]
            if new["count"] < old["count"] or (new["count"] == old["count"] and new != old):
                raise JournalError("cold original prefix regressed or same count changed head")

    def _audit(self):
        self._check_storage()
        if self._connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise JournalError("plan-store full SQLite integrity check failed")
        current, previous = self._genesis(), None
        for row in self._connection.execute("SELECT * FROM plans ORDER BY ordinal"):
            plan = self._validate_row(row)
            if row["ordinal"] != current.count + 1 or row["previous_hash"] != current.head_hash:
                raise JournalError("complete plan original chain/order differs")
            self._continuity(previous, plan)
            current = PlanStoreAnchorV3(
                self._identity_sha256, row["ordinal"], row["record_hash"], row["plan_sha256"]
            )
            previous = plan
        if self._current() != current:
            raise JournalError("complete plan history differs from bounded head projection")
        return current

    def _guard(self, expected):
        expected = _anchor(expected)
        self._check_storage()  # Pin SQL read before observing external commits.
        observed = self._data_version()
        if observed != self._observed:
            self._audit()
        current = self._current()
        if expected != self._retained or current != self._retained:
            raise OptimisticConflict("plan-store changed outside its exact own retained anchor")
        return current, observed

    def _rollback(self):
        if self._connection.in_transaction:
            self._connection.rollback()

    def _commit(self):
        self._connection.commit()

    @_serialized
    def anchor(self):
        self._connection.execute("BEGIN")
        try:
            current, observed = self._guard(self._retained)
            self._connection.commit()
            self._observed = observed
            return current
        except BaseException:
            self._rollback()
            raise

    @_serialized
    def audit(self, *, expected_anchor):
        self._connection.execute("BEGIN")
        try:
            current, observed = self._guard(expected_anchor)
            if self._audit() != current:
                raise JournalError("audited plan prefix changed")
            self._connection.commit()
            self._observed = observed
            return current
        except BaseException:
            self._rollback()
            raise

    @_serialized
    def lookup(self, *, before_version, event_id, expected_anchor):
        _integer(before_version, "driver before version")
        _identifier(event_id, "exact plan event ID")
        self._connection.execute("BEGIN")
        try:
            _, observed = self._guard(expected_anchor)
            row = self._connection.execute(
                "SELECT * FROM plans WHERE driver_before_version=? AND event_id=?", (before_version, event_id)
            ).fetchone()
            plan = None if row is None else self._validate_row(row)
            self._connection.commit()
            self._observed = observed
            return plan
        except BaseException:
            self._rollback()
            raise

    @_serialized
    def persist(self, plan, *, expected_anchor):
        encoded = self._plan_json(plan)  # Freeze original bytes before any transaction.
        frozen = compact_commit_plan_from_document(_load(encoded))
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            before, observed = self._guard(expected_anchor)
            old = self._connection.execute(
                "SELECT * FROM plans WHERE driver_before_version=? OR event_id=?",
                (frozen.expected_before.version, frozen.expected_event_id),
            ).fetchall()
            if old:
                if len(old) != 1 or old[0]["plan_json"] != encoded:
                    raise EventConflict("plan ID/version reused with conflicting exact original bytes")
                self._validate_row(old[0])
                self._connection.commit()
                self._observed = observed
                return PlanStoreReceiptV3(
                    before, before, old[0]["ordinal"], old[0]["plan_sha256"], frozen.expected_event_id, True
                )
            ordinal = before.count + 1
            if ordinal > self.limits.max_plan_rows:
                raise JournalFull("plan row ceiling reached; no original evicted")
            if frozen.expected_before.version != ordinal * 2 - 1:
                raise JournalError("new plan must follow complete original operation sequence")
            if before.count:
                previous = self._connection.execute(
                    "SELECT * FROM plans WHERE ordinal=?", (before.count,)
                ).fetchone()
                self._continuity(self._validate_row(previous), frozen)
            row = {
                "ordinal": ordinal,
                "driver_before_version": frozen.expected_before.version,
                "event_id": frozen.expected_event_id,
                "plan_json": encoded,
                "plan_sha256": _hash(encoded),
                "plan_bytes": len(encoded.encode("utf-8")),
                "previous_hash": before.head_hash,
            }
            row["record_hash"] = self._row_hash(row)
            self._connection.execute("INSERT INTO plans VALUES(?,?,?,?,?,?,?,?)", tuple(row.values()))
            after = PlanStoreAnchorV3(self._identity_sha256, ordinal, row["record_hash"], row["plan_sha256"])
            self._connection.execute(
                "UPDATE head SET count=?,head_hash=?,last_plan_sha256=? WHERE singleton=1",
                (after.count, after.head_hash, after.last_plan_sha256),
            )
            if self._current() != after:
                raise JournalError("new original plan and head projection differ before COMMIT")
            _verify_database_pages(self._connection, self.limits.max_database_bytes)
            self._commit()  # SQLite DELETE/FULL; still NO external-bundle ACK.
            self._retained, self._observed = after, observed
            return PlanStoreReceiptV3(
                before, after, ordinal, row["plan_sha256"], frozen.expected_event_id, False
            )
        except BaseException as error:
            self._rollback()
            if isinstance(error, sqlite3.DatabaseError) and "full" in str(error).casefold():
                raise JournalFull("plan-store SQLite byte ceiling reached; append rolled back") from error
            raise

    def close(self):
        with self._lock:
            if self._active:
                raise JournalError("cannot close during active plan-store operation")
            self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
