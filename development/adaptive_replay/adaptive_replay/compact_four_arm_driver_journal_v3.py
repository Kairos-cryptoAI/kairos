"""Separate create-only compact four-arm driver profile, not an old journal adapter.

Hot state contains exact cold count/head references, NOT routes/cells/costs/
slots history. state_hash is SHA256 of that bounded hot document, not SHA256
of the old fully materialized historical state. Every original cold value and
outer request is append-only and indexed. Intent and completed driver commit
are separate atomic SQL transactions; account effects remain independently
audited/distributed transactions licensed by the external checkpoint WAL.

Full open/audit replays all retained history. Ordinary own operations have no
COUNT/history scan. SQLite external commits invalidate the audited prefix;
changed history is audited before lookup, and unknown newer heads are refused.
This is local consistency, not hostile raw-file authentication or proof of
financial/source/provider correctness. No migration/adoption/repair/eviction.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
from dataclasses import asdict, dataclass
from functools import wraps

from .continuous_four_arm_v3 import ARMS
from .historical_context import digest
from .sim_delta_journal_v3 import DeltaCheckpointV3, _load, _sha, apply_delta, make_delta
from .sim_financial_journal_v3 import FinancialCheckpointV3
from .sim_state_journal import (
    AppendResult,
    EventConflict,
    JournalError,
    JournalFull,
    JournalIdentity,
    JournalSnapshot,
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

SCHEMA = "kairos.research.compact-four-arm-driver-journal.v3"
SCHEMA_VERSION = 41
COLLECTIONS = ("cells", "costs", "routes", "slots")
HOT_FIELDS = {
    "identity",
    "cursor",
    "pending",
    "finished",
    "account_config",
    "account_identity",
    "account_checkpoints",
    "report",
    "profile",
    "history_refs",
}
MAX_ROWS = 2**63 - 1
_DDL = {
    "metadata": "CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "events": (
        "CREATE TABLE events(version INTEGER PRIMARY KEY,event_id TEXT NOT NULL UNIQUE,"
        "payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL,outcome_json TEXT NOT NULL,"
        "outcome_hash TEXT NOT NULL,delta_json TEXT NOT NULL,delta_hash TEXT NOT NULL,"
        "cold_json TEXT NOT NULL,cold_hash TEXT NOT NULL,state_hash TEXT NOT NULL,"
        "previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL,clock_ms INTEGER NOT NULL)"
    ),
    "cold_records": (
        "CREATE TABLE cold_records(ordinal INTEGER PRIMARY KEY,collection TEXT NOT NULL,"
        "collection_ordinal INTEGER NOT NULL,key TEXT NOT NULL,value_json TEXT NOT NULL,"
        "content_hash TEXT NOT NULL,previous_hash TEXT NOT NULL,record_hash TEXT NOT NULL,"
        "outer_version INTEGER NOT NULL,within_outer INTEGER NOT NULL,UNIQUE(collection,key))"
    ),
    "cold_ordinal": "CREATE UNIQUE INDEX cold_ordinal ON cold_records(collection,collection_ordinal)",
    "head": (
        "CREATE TABLE head(singleton INTEGER PRIMARY KEY CHECK(singleton=1),version INTEGER NOT NULL,"
        "state_json TEXT NOT NULL,state_hash TEXT NOT NULL,head_hash TEXT NOT NULL,"
        "last_clock_ms INTEGER NOT NULL,state_bytes INTEGER NOT NULL)"
    ),
}


def _integer(value, name):
    if type(value) is not int or not 0 <= value <= MAX_ROWS:
        raise JournalError(f"exact bounded nonnegative {name} required")
    return value


def _owner():
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return threading.get_ident(), task


def _serialized(function):
    @wraps(function)
    def guarded(self, *args, **kwargs):
        with self._lock:
            if self._stage is not None:
                raise JournalError("nested compact journal operation forbidden")
            return function(self, *args, **kwargs)

    return guarded


def _key(collection, key):
    if (
        type(collection) is not str
        or collection not in COLLECTIONS
        or type(key) is not str
        or (not key or len(key.encode("utf-8")) > 512 or "\x00" in key)
    ):
        raise JournalError("exact bounded cold collection/key required")


def _copy(value):
    return _load(_canonical(value))


def _check_checkpoint(value):
    if type(value) is not DeltaCheckpointV3:
        raise JournalError("independent exact DeltaCheckpointV3 required for compact profile")
    DeltaCheckpointV3(**asdict(value))
    for name in ("version", "last_clock_ms"):
        _integer(getattr(value, name), name)


def _financial(value, arm):
    if type(value) is FinancialCheckpointV3:
        value = asdict(value)
    if type(value) is not dict or set(value) != set(FinancialCheckpointV3.__dataclass_fields__):
        raise JournalError("closed exact financial checkpoint document required")
    result = FinancialCheckpointV3(**value)
    if result.account_id != arm:
        raise JournalError("financial account ID differs from four-arm owner")
    return result


def _accounts(value):
    if type(value) is not dict or set(value) != set(ARMS):
        raise JournalError("exact four-arm financial checkpoint roster required")
    result = {arm: _financial(value[arm], arm) for arm in ARMS}
    if len({cp.owner_id for cp in result.values()}) != 1:
        raise JournalError("four-arm financial owner mismatch")
    return result


@dataclass(frozen=True)
class CompactDriverLimitsV3:
    """All budgets explicitly supplied; no dense-capacity claim from defaults."""

    max_event_rows: int
    max_cold_rows: int
    max_hot_bytes: int
    max_event_bytes: int
    max_record_bytes: int
    max_records_per_commit: int
    max_database_bytes: int

    def __post_init__(self):
        maxima = (MAX_ROWS, MAX_ROWS, 8 * 1024 * 1024, 16 * 1024 * 1024, 2 * 1024 * 1024, 10_000, 1024**4)
        for name, maximum in zip(self.__dataclass_fields__, maxima, strict=True):
            _positive_bound(getattr(self, name), name, maximum=maximum)
        if self.max_database_bytes < 32 * 1024 or self.max_record_bytes > self.max_event_bytes:
            raise JournalError("bounded SQLite/record/event budget inconsistent")


@dataclass(frozen=True)
class ColdHistoryRecordV3:
    collection: str
    key: str
    value: dict

    def __post_init__(self):
        _key(self.collection, self.key)
        if type(self.value) is not dict:
            raise JournalError("plain exact cold original document required")
        _canonical(self.value)


@dataclass(frozen=True)
class ColdHistoryPageV3:
    checkpoint: DeltaCheckpointV3
    records: tuple[ColdHistoryRecordV3, ...]
    next_key: str | None


def _cold_reference(row):
    return {
        key: row[key]
        for key in (
            "ordinal",
            "collection",
            "collection_ordinal",
            "key",
            "content_hash",
            "previous_hash",
            "record_hash",
            "outer_version",
            "within_outer",
        )
    }


def _cold_hash(row):
    return _hash(
        _canonical(
            [
                SCHEMA,
                "COLD",
                *[
                    row[key]
                    for key in (
                        "ordinal",
                        "collection",
                        "collection_ordinal",
                        "key",
                        "content_hash",
                        "previous_hash",
                        "outer_version",
                        "within_outer",
                    )
                ],
            ]
        )
    )


def _event_hash(row):
    return _hash(
        _canonical(
            [
                SCHEMA,
                "OUTER",
                *[
                    row[key]
                    for key in (
                        "previous_hash",
                        "version",
                        "event_id",
                        "payload_hash",
                        "outcome_hash",
                        "delta_hash",
                        "cold_hash",
                        "state_hash",
                        "clock_ms",
                    )
                ],
            ]
        )
    )


class _ColdTransaction:
    """Owned transaction capability, invalid immediately after fold/failure."""

    def __init__(self, journal, state, version):
        self.journal, self.version = journal, version
        self.refs = _copy(state["history_refs"])
        self.rows, self.index = [], {}
        self.byte_count = 0
        self.execution = _owner()
        self.active = True

    def _require(self):
        if (
            not self.active
            or self.journal._stage is not self
            or not self.journal._connection.in_transaction
            or (self.execution != _owner())
        ):
            raise JournalError("owned active cold transaction required")

    def lookup(self, collection, key):
        self._require()
        _key(collection, key)
        row = self.index.get((collection, key))
        if row is None:
            row = self.journal._connection.execute(
                "SELECT * FROM cold_records WHERE collection=? AND key=?", (collection, key)
            ).fetchone()
        return None if row is None else self.journal._validate_cold(row)

    def append(self, record):
        self._require()
        if type(record) is not ColdHistoryRecordV3:
            raise JournalError("exact typed cold record required")
        encoded = _canonical(record.value)
        old = self.lookup(record.collection, record.key)
        if old is not None:
            if _canonical(old.value) != encoded:
                raise EventConflict("cold ID reused with conflicting exact original bytes")
            return False
        size = len(encoded.encode("utf-8"))
        limits = self.journal.limits
        if (
            size > limits.max_record_bytes
            or len(self.rows) >= limits.max_records_per_commit
            or (self.byte_count + size > limits.max_event_bytes)
        ):
            raise JournalFull("cold transaction record/byte bound exceeded; nothing evicted")
        ordinal = sum(ref["count"] for ref in self.refs.values()) + 1
        if ordinal > limits.max_cold_rows:
            raise JournalFull("cold history row bound reached; nothing evicted")
        ref = self.refs[record.collection]
        row = {
            "ordinal": ordinal,
            "collection": record.collection,
            "collection_ordinal": ref["count"] + 1,
            "key": record.key,
            "value_json": encoded,
            "content_hash": _hash(encoded),
            "previous_hash": ref["head"],
            "outer_version": self.version,
            "within_outer": len(self.rows) + 1,
        }
        row["record_hash"] = _cold_hash(row)
        self.rows.append(row)
        self.index[record.collection, record.key] = row
        self.refs[record.collection] = {"count": row["collection_ordinal"], "head": row["record_hash"]}
        self.byte_count += size
        return True


class CompactFourArmDriverJournalV3:
    """Only the new compact schema; checkpoint uses existing Delta carrier type.

    The carrier identity/head commit this schema, bounded hot state and cold
    refs. Existing ROOT/segmented WAL can retain it without claiming the old
    full-state hash or transparently opening any legacy journal.
    """

    def __init__(self, connection, path, identity, limits):
        if type(identity) is not JournalIdentity or type(limits) is not CompactDriverLimitsV3:
            raise JournalError("typed compact identity/explicit resource profile required")
        JournalIdentity(**asdict(identity))
        CompactDriverLimitsV3(**asdict(limits))
        self._connection, self.path, self.identity, self.limits = connection, path, identity, limits
        self._physical = _file_identity(path)
        self._lock = threading.RLock()
        self._stage = None
        self._retained = None
        self._observed = None
        self._sealed_configuration = self._configuration()

    def _configuration(self):
        return {
            "schema": SCHEMA,
            "identity_json": _canonical(asdict(self.identity)),
            "limits_json": _canonical(asdict(self.limits)),
        }

    def _empty_refs(self):
        return {
            kind: {
                "count": 0,
                "head": _hash(_canonical([SCHEMA, "GENESIS_COLD", asdict(self.identity), kind])),
            }
            for kind in COLLECTIONS
        }

    def _hot_json(self, state):
        if type(state) is not dict or set(state) != HOT_FIELDS or state["profile"] != SCHEMA:
            raise JournalError("closed compact hot schema required; no historical maps in snapshot")
        _sha(state["identity"])
        _integer(state["cursor"], "operation cursor")
        if type(state["finished"]) is not bool or state["finished"] != (state["report"] is not None):
            raise JournalError("exact terminal report/finished state required")
        if state["report"] is not None and type(state["report"]) is not dict:
            raise JournalError("plain exact terminal report required")
        for key in ("account_config", "account_identity"):
            if type(state[key]) is not dict or set(state[key]) != set(ARMS):
                raise JournalError("sealed four-arm configuration/identity roster required")
        _accounts(state["account_checkpoints"])
        refs = state["history_refs"]
        if type(refs) is not dict or set(refs) != set(COLLECTIONS):
            raise JournalError("closed four-collection cold refs required")
        for ref in refs.values():
            if type(ref) is not dict or set(ref) != {"count", "head"}:
                raise JournalError("exact cold count/head reference required")
            _integer(ref["count"], "cold count")
            _sha(ref["head"])
        if sum(ref["count"] for ref in refs.values()) > self.limits.max_cold_rows:
            raise JournalFull("hot reference exceeds cold capacity")
        if state["pending"] is not None:
            self._pending(state["pending"])
            if state["finished"]:
                raise JournalError("terminal state cannot retain pending operation")
        encoded = _canonical(state)
        if len(encoded.encode("utf-8")) > self.limits.max_hot_bytes:
            raise JournalFull("bounded hot state byte capacity exceeded")
        return encoded

    def _pending(self, pending):
        if (
            type(pending) is not dict
            or set(pending) != {"operation", "before", "effects"}
            or (
                type(pending["operation"]) is not dict
                or type(pending["effects"]) is not dict
                or set(pending["effects"]) != set(ARMS)
            )
        ):
            raise JournalError("whole exact four-arm pending intent required")
        operation = pending["operation"]
        if operation.get("kind") not in {"SOURCE", "ATTEMPT", "EXPENSE", "ROUTE", "CELL", "FINISH"}:
            raise JournalError("known driver operation kind required")
        _clock(operation.get("at"))
        _accounts(pending["before"])
        for effect in pending["effects"].values():
            if effect is not None:
                if (
                    type(effect) is not dict
                    or set(effect) != {"event_id", "payload"}
                    or type(effect["payload"]) is not dict
                ):
                    raise JournalError("exact owned expected account event required")
                _identifier(effect["event_id"], "account effect ID")
                _canonical(effect["payload"])

    @classmethod
    def create(cls, path, *, identity, initial_state, limits, initial_clock_ms=0):
        _clock(initial_clock_ms)
        if type(identity) is not JournalIdentity or type(limits) is not CompactDriverLimitsV3:
            raise JournalError("typed compact identity/explicit limits required")
        destination = _safe_path(path, must_exist=False)
        state = _copy(initial_state)
        for kind in COLLECTIONS:
            if state.pop(kind, {}) != {}:
                raise JournalError("new compact genesis cannot adopt existing historical maps")
        if (
            set(state) != HOT_FIELDS - {"profile", "history_refs"}
            or state.get("cursor") != 0
            or (
                state.get("pending") is not None
                or state.get("finished") is not False
                or state.get("report") is not None
            )
        ):
            raise JournalError("fresh exact driver genesis required")
        if any(
            cp.version or cp.native_count or cp.source_cursor
            for cp in _accounts(state["account_checkpoints"]).values()
        ):
            raise JournalError("new driver requires unadvanced financial accounts")
        validator = object.__new__(cls)
        validator.identity, validator.limits = identity, limits
        state["profile"], state["history_refs"] = SCHEMA, validator._empty_refs()
        encoded = validator._hot_json(state)
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(descriptor)
        connection = sqlite3.connect(
            str(destination), timeout=0, isolation_level=None, check_same_thread=False
        )
        connection.row_factory = sqlite3.Row
        try:
            journal = cls(connection, destination, identity, limits)
            _configure(connection)
            connection.execute("PRAGMA busy_timeout=0")
            _set_database_bound(connection, limits.max_database_bytes)
            connection.execute("BEGIN IMMEDIATE")
            for ddl in _DDL.values():
                connection.execute(ddl)
            state_hash = _hash(encoded)
            genesis = _hash(_canonical([SCHEMA, journal._configuration(), state_hash, initial_clock_ms]))
            metadata = {
                **journal._configuration(),
                "initial_hot_json": encoded,
                "initial_clock_ms": str(initial_clock_ms),
                "initial_hot_hash": state_hash,
                "genesis_hash": genesis,
            }
            connection.executemany("INSERT INTO metadata VALUES(?,?)", metadata.items())
            connection.execute(
                "INSERT INTO head VALUES(1,0,?,?,?,?,?)",
                (encoded, state_hash, genesis, initial_clock_ms, len(encoded.encode("utf-8"))),
            )
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            snapshot = journal._audit()
            _verify_database_pages(connection, limits.max_database_bytes)
            observed = journal._data_version()
            connection.commit()
            journal._retained, journal._observed = journal._checkpoint(snapshot), observed
            return journal
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
            raise

    @classmethod
    def open(cls, path, *, identity, limits, expected_checkpoint):
        _check_checkpoint(expected_checkpoint)
        path = _safe_path(path, must_exist=True)
        connection = sqlite3.connect(
            _existing_uri(path), uri=True, timeout=0, isolation_level=None, check_same_thread=False
        )
        connection.row_factory = sqlite3.Row
        try:
            journal = cls(connection, path, identity, limits)
            # Audit original schema/settings BEFORE applying any writable PRAGMA.
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            snapshot = journal._audit()
            if journal._checkpoint(snapshot) != expected_checkpoint:
                raise OptimisticConflict("independent exact compact checkpoint differs; no latest adoption")
            connection.commit()
            connection.execute("PRAGMA query_only=OFF")
            _configure(connection)
            _set_database_bound(connection, limits.max_database_bytes)
            connection.execute("PRAGMA busy_timeout=0")
            connection.execute("BEGIN IMMEDIATE")
            snapshot = journal._audit()
            if journal._checkpoint(snapshot) != expected_checkpoint:
                raise OptimisticConflict("compact checkpoint changed before writable open")
            observed = journal._data_version()
            connection.commit()
            journal._retained, journal._observed = expected_checkpoint, observed
            return journal
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
            raise

    @classmethod
    def open_after_known_commit(
        cls,
        path,
        *,
        identity,
        limits,
        expected_before,
        expected_event_id,
        expected_payload,
        expected_at_ms,
        expected_outcome,
        expected_hot_state,
        expected_cold_records,
    ):
        """Recover exactly one externally authorized COMMIT, never adopt latest.

        Every expected value must come from caller-retained intent/receipts,
        not the current DB head. expected_cold_records is the exact original
        request tuple, including duplicates. This verifies local consistency;
        it does not authenticate the caller or license account effects.
        """
        _check_checkpoint(expected_before)
        _identifier(expected_event_id, "known commit ID")
        _clock(expected_at_ms)
        if type(expected_payload) is not dict or type(expected_hot_state) is not dict:
            raise JournalError("exact caller-retained commit payload/hot document required")
        if type(expected_cold_records) is not tuple:
            raise JournalError("exact caller-retained cold request tuple required")
        if type(limits) is not CompactDriverLimitsV3:
            raise JournalError("typed sealed compact limits required")
        if len(expected_cold_records) > limits.max_records_per_commit:
            raise JournalFull("known original cold request exceeds sealed capacity")
        if any(type(record) is not ColdHistoryRecordV3 for record in expected_cold_records):
            raise JournalError("exact typed caller-retained cold originals required")
        payload_json = _canonical(expected_payload)
        outcome_json = _canonical(expected_outcome)
        hot_json = _canonical(expected_hot_state)
        cold_json = _canonical([asdict(record) for record in expected_cold_records])
        if _canonical(expected_payload.get("cold_records")) != cold_json:
            raise JournalError("known payload differs from retained original cold roster")
        path = _safe_path(path, must_exist=True)
        connection = sqlite3.connect(
            _existing_uri(path), uri=True, timeout=0, isolation_level=None, check_same_thread=False
        )
        connection.row_factory = sqlite3.Row
        try:
            journal = cls(connection, path, identity, limits)
            journal._hot_json(_load(hot_json))
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            snapshot = journal._verify_known_commit(
                expected_before,
                expected_event_id,
                payload_json,
                expected_at_ms,
                outcome_json,
                hot_json,
                cold_json,
            )
            authorized = journal._checkpoint(snapshot)
            connection.commit()
            connection.execute("PRAGMA query_only=OFF")
            _configure(connection)
            _set_database_bound(connection, limits.max_database_bytes)
            connection.execute("PRAGMA busy_timeout=0")
            connection.execute("BEGIN IMMEDIATE")
            snapshot = journal._verify_known_commit(
                expected_before,
                expected_event_id,
                payload_json,
                expected_at_ms,
                outcome_json,
                hot_json,
                cold_json,
            )
            if journal._checkpoint(snapshot) != authorized:
                raise OptimisticConflict("known compact commit changed before writable open")
            observed = journal._data_version()
            connection.commit()
            journal._retained, journal._observed = authorized, observed
            return journal
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
            raise

    def _verify_known_commit(self, before, event_id, payload_json, at_ms, outcome_json, hot_json, cold_json):
        current = self._audit()
        if current.version != before.version + 1:
            raise OptimisticConflict("recovery requires exactly one known COMMIT after retained prefix")
        metadata = self._check_storage()
        state = _load(metadata["initial_hot_json"])
        prefix = JournalSnapshot(
            0,
            state,
            metadata["initial_hot_hash"],
            metadata["genesis_hash"],
            int(metadata["initial_clock_ms"]),
        )
        # Full audit above validates every row; replay only this exact prefix
        # within the SAME pinned SQL transaction, using bounded hot documents.
        for row in self._connection.execute(
            "SELECT * FROM events WHERE version<=? ORDER BY version", (before.version,)
        ):
            state = apply_delta(state, _load(row["delta_json"]))
            prefix = JournalSnapshot(
                row["version"], state, row["state_hash"], row["event_hash"], row["clock_ms"]
            )
        if self._checkpoint(prefix) != before:
            raise OptimisticConflict("audited prefix differs from independently retained checkpoint")
        if prefix.state["pending"] is None or event_id != f"operation:{prefix.state['cursor']}:commit":
            raise JournalError("only exact retained pending COMMIT can be recovered")
        row = self._connection.execute(
            "SELECT * FROM events WHERE version=?", (before.version + 1,)
        ).fetchone()
        if (
            row["previous_hash"] != before.head_hash
            or row["event_id"] != event_id
            or row["clock_ms"] != at_ms
            or row["payload_json"] != payload_json
            or row["outcome_json"] != outcome_json
            or _canonical(current.state) != hot_json
        ):
            raise EventConflict("new compact head differs from caller-retained exact known COMMIT")
        refs, expected_rows, staged = _copy(prefix.state["history_refs"]), [], {}
        for request in _load(cold_json):
            key = request["collection"], request["key"]
            encoded = _canonical(request["value"])
            old = self._connection.execute(
                "SELECT * FROM cold_records WHERE collection=? AND key=? AND outer_version<=?",
                (*key, before.version),
            ).fetchone()
            old_bytes = old["value_json"] if old is not None else staged.get(key)
            if old_bytes is not None:
                if old_bytes != encoded:
                    raise EventConflict("known cold duplicate differs from exact retained prefix")
                continue
            ref = refs[key[0]]
            original = {
                "ordinal": sum(value["count"] for value in refs.values()) + 1,
                "collection": key[0],
                "collection_ordinal": ref["count"] + 1,
                "key": key[1],
                "value_json": encoded,
                "content_hash": _hash(encoded),
                "previous_hash": ref["head"],
                "outer_version": before.version + 1,
                "within_outer": len(expected_rows) + 1,
            }
            original["record_hash"] = _cold_hash(original)
            expected_rows.append(_cold_reference(original))
            staged[key] = encoded
            refs[key[0]] = {"count": original["collection_ordinal"], "head": original["record_hash"]}
        if row["cold_json"] != _canonical(expected_rows) or current.state["history_refs"] != refs:
            raise EventConflict("new cold rows/order/heads differ from exactly authorized originals")
        return current

    def _check_storage(self):
        if self._configuration() != self._sealed_configuration or _file_identity(self.path) != self._physical:
            raise JournalError("compact identity/configuration/file drift")
        _verify_database_file_size(self.path, self.limits.max_database_bytes, self._connection)
        objects = self._connection.execute("SELECT type,name,sql FROM sqlite_master").fetchall()
        expected = {
            name: ("index" if name == "cold_ordinal" else "table", _normalize_sql(sql))
            for name, sql in _DDL.items()
        }
        expected.update(
            {
                name: ("index", None)
                for name in (
                    "sqlite_autoindex_metadata_1",
                    "sqlite_autoindex_events_1",
                    "sqlite_autoindex_cold_records_1",
                )
            }
        )
        actual = {
            row["name"]: (row["type"], _normalize_sql(row["sql"]) if row["sql"] is not None else None)
            for row in objects
        }
        if (
            actual != expected
            or self._connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
            or (self._connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete")
        ):
            raise JournalError("exact separate compact schema required; no legacy interpretation")
        metadata = dict(self._connection.execute("SELECT key,value FROM metadata").fetchall())
        if set(metadata) != set(self._configuration()) | {
            "initial_hot_json",
            "initial_hot_hash",
            "initial_clock_ms",
            "genesis_hash",
        }:
            raise JournalError("closed compact metadata schema required")
        if any(metadata[key] != value for key, value in self._configuration().items()):
            raise JournalError("compact pinned identity/resource profile differs")
        return metadata

    def _validate_cold(self, row):
        _key(row["collection"], row["key"])
        for key in ("ordinal", "collection_ordinal", "outer_version", "within_outer"):
            if _integer(row[key], key) == 0:
                raise JournalError("positive exact cold order required")
        for key in ("content_hash", "previous_hash", "record_hash"):
            _sha(row[key])
        encoded = row["value_json"]
        if type(encoded) is not str or len(encoded.encode("utf-8")) > self.limits.max_record_bytes:
            raise JournalFull("stored cold original bytes exceed pinned cap")
        value = _load(encoded)
        record = ColdHistoryRecordV3(row["collection"], row["key"], value)
        if (
            _canonical(record.value) != encoded
            or _hash(encoded) != row["content_hash"]
            or _cold_hash(row) != row["record_hash"]
        ):
            raise JournalError("cold exact original/order hash conflict")
        return record

    def _validate_event(self, row):
        _identifier(row["event_id"], "stored event ID")
        if _integer(row["version"], "version") == 0:
            raise JournalError("positive compact version required")
        _clock(row["clock_ms"])
        for key in ("payload", "outcome", "delta", "cold"):
            encoded = row[f"{key}_json"]
            if (
                type(encoded) is not str
                or _canonical(_load(encoded)) != encoded
                or _hash(encoded) != _sha(row[f"{key}_hash"])
            ):
                raise JournalError("compact canonical event bytes/hash conflict")
        for key in ("state_hash", "previous_hash", "event_hash"):
            _sha(row[key])
        if _event_hash(row) != row["event_hash"]:
            raise JournalError("compact outer commitment conflict")
        return (
            _load(row["payload_json"]),
            _load(row["outcome_json"]),
            _load(row["delta_json"]),
            _load(row["cold_json"]),
        )

    def _current(self):
        metadata = self._check_storage()
        rows = self._connection.execute("SELECT * FROM head").fetchmany(2)
        if len(rows) != 1 or rows[0]["singleton"] != 1:
            raise JournalError("exact compact hot head required")
        head = rows[0]
        version = _integer(head["version"], "version")
        if version > self.limits.max_event_rows:
            raise JournalFull("compact outer row cap exceeded")
        state = _load(head["state_json"])
        encoded = self._hot_json(state)
        if (
            encoded != head["state_json"]
            or _hash(encoded) != head["state_hash"]
            or (len(encoded.encode("utf-8")) != head["state_bytes"])
        ):
            raise JournalError("bounded hot document/hash/byte commitment differs")
        _clock(head["last_clock_ms"])
        tail = self._connection.execute("SELECT * FROM events ORDER BY version DESC LIMIT 1").fetchone()
        if (tail is None) != (version == 0) or tail is not None and tail["version"] != version:
            raise JournalError("compact outer tail/version conflict")
        if tail is not None:
            self._validate_event(tail)
            if (tail["state_hash"], tail["event_hash"], tail["clock_ms"]) != (
                head["state_hash"],
                head["head_hash"],
                head["last_clock_ms"],
            ):
                raise JournalError("compact event/hot head conflict")
        elif (encoded, head["state_hash"], head["head_hash"], str(head["last_clock_ms"])) != (
            metadata["initial_hot_json"],
            metadata["initial_hot_hash"],
            metadata["genesis_hash"],
            metadata["initial_clock_ms"],
        ):
            raise JournalError("compact genesis/head conflict")
        for kind, ref in state["history_refs"].items():
            cold = self._connection.execute(
                "SELECT * FROM cold_records WHERE collection=? ORDER BY collection_ordinal DESC LIMIT 1",
                (kind,),
            ).fetchone()
            if (cold is None) != (ref["count"] == 0):
                raise JournalError("cold collection count/tail conflict")
            if cold is not None:
                self._validate_cold(cold)
                if (cold["collection_ordinal"], cold["record_hash"]) != (ref["count"], ref["head"]):
                    raise JournalError("cold tail differs from hot reference")
            elif ref != self._empty_refs()[kind]:
                raise JournalError("empty cold collection differs from sealed genesis")
        cold_tail = self._connection.execute(
            "SELECT ordinal FROM cold_records ORDER BY ordinal DESC LIMIT 1"
        ).fetchone()
        count = sum(ref["count"] for ref in state["history_refs"].values())
        if (cold_tail is None) != (count == 0) or cold_tail is not None and cold_tail[0] != count:
            raise JournalError("global cold ordinal/count conflict")
        return JournalSnapshot(version, state, head["state_hash"], head["head_hash"], head["last_clock_ms"])

    def _checkpoint(self, snapshot):
        return DeltaCheckpointV3(
            _hash(_canonical(asdict(self.identity))),
            snapshot.version,
            snapshot.state_hash,
            snapshot.head_hash,
            snapshot.last_clock_ms,
        )

    def _data_version(self):
        return self._connection.execute("PRAGMA data_version").fetchone()[0]

    def _verified_current(self):
        # DELETE mode + pinned SQL read prevents a later SQLite writer COMMIT
        # between this prefix audit and our recorded data_version.
        self._connection.execute("SELECT singleton FROM head").fetchone()
        observed = self._data_version()
        current = self._audit() if observed != self._observed else self._current()
        if self._retained is not None and self._checkpoint(current) != self._retained:
            raise OptimisticConflict("compact head advanced outside exact retained own checkpoint")
        self._observed = observed
        return current

    def _boundary(self, before, after, event_id, payload, at_ms):
        for key in ("identity", "profile", "account_config", "account_identity"):
            if _canonical(before[key]) != _canonical(after[key]):
                raise JournalError("sealed driver identity/configuration changed")
        if before["finished"]:
            raise JournalError("terminal compact driver")
        cursor = before["cursor"]
        if before["pending"] is None:
            if (
                event_id != f"operation:{cursor}:intent"
                or type(payload) is not dict
                or set(payload) != {"pending"}
            ):
                raise JournalError("exact driver intent ID/envelope required")
            pending = payload["pending"]
            self._pending(pending)
            if pending["operation"]["at"] != at_ms or _canonical(pending["before"]) != _canonical(
                before["account_checkpoints"]
            ):
                raise JournalError("intent clock/independent financial before heads differ")
            expected = _copy(before)
            expected["pending"] = pending
            if _canonical(expected) != _canonical(after):
                raise JournalError("intent cannot contain account/cold/operation effects")
            return
        pending = before["pending"]
        if (
            event_id != f"operation:{cursor}:commit"
            or type(payload) is not dict
            or set(payload)
            != {"operation", "pending_sha256", "account_checkpoints", "cold_records", "report"}
            or payload["pending_sha256"] != digest(pending)
            or (
                _canonical(payload["operation"]) != _canonical(pending["operation"])
                or pending["operation"]["at"] != at_ms
            )
        ):
            raise JournalError("commit differs from whole retained pending operation")
        old_accounts, new_accounts = _accounts(pending["before"]), _accounts(payload["account_checkpoints"])
        for arm in ARMS:
            old, new, effect = old_accounts[arm], new_accounts[arm], pending["effects"][arm]
            if (old.identity_sha256, old.owner_id, old.account_id) != (
                new.identity_sha256,
                new.owner_id,
                new.account_id,
            ):
                raise JournalError("financial commit owner/identity changed")
            if effect is None:
                if old != new:
                    raise JournalError("unlicensed financial account effect")
                continue
            if (
                new.version != old.version + 1
                or new.last_clock_ms != at_ms
                or new.native_count < old.native_count
            ):
                raise JournalError("completed commit requires exact one financial effect/clock/native prefix")
            if new.native_count == old.native_count and new.native_head != old.native_head:
                raise JournalError("same native count cannot change native head")
            effect_payload = effect["payload"]
            expected_cursor = old.source_cursor
            if effect_payload.get("kind") == "SOURCE_BATCH":
                if _integer(effect_payload.get("first"), "source first cursor") != old.source_cursor + 1:
                    raise JournalError("source effect cannot skip original input prefix")
                expected_cursor = _integer(effect_payload.get("last"), "source after cursor")
                if expected_cursor < old.source_cursor + 1:
                    raise JournalError("source effect empty/regressing prefix")
            if new.source_cursor != expected_cursor:
                raise JournalError("account source cursor differs from exact licensed source effect")
        records = payload["cold_records"]
        if type(records) is not list or len(records) > self.limits.max_records_per_commit:
            raise JournalFull("bounded exact requested cold record roster required")
        requested = []
        for record in records:
            if type(record) is not dict or set(record) != {"collection", "key", "value"}:
                raise JournalError("closed cold request document required")
            requested.append(ColdHistoryRecordV3(**record))
        required = {"CELL": "cells", "ROUTE": "routes", "ATTEMPT": "costs", "EXPENSE": "costs"}.get(
            pending["operation"]["kind"]
        )
        if required is not None and sum(record.collection == required for record in requested) != 1:
            raise JournalError("driver operation must retain its one exact cold receipt")
        if required is None and requested:
            raise JournalError("source/finish cannot manufacture cold driver receipts")
        if required is not None and any(record.collection not in {required, "slots"} for record in requested):
            raise JournalError("cold record collection unrelated to operation")
        expected = _copy(before)
        expected.update(
            {
                "pending": None,
                "cursor": cursor + 1,
                "account_checkpoints": payload["account_checkpoints"],
                "history_refs": after["history_refs"],
            }
        )
        if pending["operation"]["kind"] == "FINISH":
            if type(payload["report"]) is not dict:
                raise JournalError("finish requires explicit complete/UNKNOWN report")
            expected.update(finished=True, report=payload["report"])
        elif payload["report"] is not None:
            raise JournalError("only finish may publish a terminal report")
        if _canonical(expected) != _canonical(after):
            raise JournalError("commit hot state differs from exact pending/accounts/cold refs")

    def _audit(self):
        metadata = self._check_storage()
        if self._connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise JournalError("compact SQLite integrity check failed")
        state = _load(metadata["initial_hot_json"])
        encoded = self._hot_json(state)
        clock = int(metadata["initial_clock_ms"])
        if (
            encoded != metadata["initial_hot_json"]
            or _hash(encoded) != metadata["initial_hot_hash"]
            or str(clock) != metadata["initial_clock_ms"]
        ):
            raise JournalError("compact initial hot commitment conflict")
        previous = _hash(_canonical([SCHEMA, self._configuration(), _hash(encoded), clock]))
        if previous != metadata["genesis_hash"] or state["history_refs"] != self._empty_refs():
            raise JournalError("compact outer/cold genesis conflict")
        version, cold_count = 0, 0
        for row in self._connection.execute("SELECT * FROM events ORDER BY version"):
            version += 1
            payload, _, delta, cold_refs = self._validate_event(row)
            if (
                row["version"] != version
                or row["previous_hash"] != previous
                or row["clock_ms"] < clock
                or version > self.limits.max_event_rows
            ):
                raise JournalError("compact complete outer chain/order conflict")
            after = apply_delta(state, delta)
            refs = _copy(state["history_refs"])
            if type(cold_refs) is not list or len(cold_refs) > self.limits.max_records_per_commit:
                raise JournalError("bounded exact event cold prefix required")
            native_size = 0
            inserted_keys = []
            for within, cold in enumerate(
                self._connection.execute(
                    "SELECT * FROM cold_records WHERE ordinal>? AND ordinal<=? ORDER BY ordinal",
                    (cold_count, cold_count + len(cold_refs)),
                ),
                1,
            ):
                self._validate_cold(cold)
                cold_count += 1
                ref = refs[cold["collection"]]
                if (
                    cold["ordinal"] != cold_count
                    or cold["collection_ordinal"] != ref["count"] + 1
                    or (
                        cold["previous_hash"] != ref["head"]
                        or cold["outer_version"] != version
                        or cold["within_outer"] != within
                        or _cold_reference(cold) != cold_refs[within - 1]
                    )
                ):
                    raise JournalError("cold original ownership/order/committed prefix conflict")
                refs[cold["collection"]] = {"count": cold["collection_ordinal"], "head": cold["record_hash"]}
                native_size += len(cold["value_json"].encode("utf-8"))
                inserted_keys.append((cold["collection"], cold["key"]))
            if (
                sum(ref["count"] for ref in refs.values()) != cold_count
                or after["history_refs"] != refs
                or (
                    sum(ref["count"] for ref in refs.values())
                    - sum(ref["count"] for ref in state["history_refs"].values())
                    != len(cold_refs)
                )
            ):
                raise JournalError("cold prefix rows missing or different from hot refs")
            self._boundary(state, after, row["event_id"], payload, row["clock_ms"])
            requested_keys = {
                (record["collection"], record["key"]) for record in payload.get("cold_records", [])
            }
            if any(key not in requested_keys for key in inserted_keys):
                raise JournalError("cold insertion is absent from exact original request")
            if state["pending"] is not None:
                for requested in payload["cold_records"]:
                    original = self._connection.execute(
                        "SELECT * FROM cold_records WHERE collection=? AND key=?",
                        (requested["collection"], requested["key"]),
                    ).fetchone()
                    if (
                        original is None
                        or original["ordinal"] > cold_count
                        or _canonical(requested["value"]) != original["value_json"]
                    ):
                        raise JournalError("original requested cold payload not in exact committed prefix")
            encoded = self._hot_json(after)
            if (
                _hash(encoded) != row["state_hash"]
                or _canonical(make_delta(state, after)) != row["delta_json"]
            ):
                raise JournalError("bounded hot delta/state hash differs")
            size = (
                sum(
                    len(row[key].encode("utf-8"))
                    for key in ("event_id", "payload_json", "outcome_json", "delta_json", "cold_json")
                )
                + native_size
            )
            if size > self.limits.max_event_bytes:
                raise JournalFull("stored atomic compact event exceeds byte cap")
            state, previous, clock = after, row["event_hash"], row["clock_ms"]
        current = self._current()
        if (current.version, current.head_hash, current.last_clock_ms, _canonical(current.state)) != (
            version,
            previous,
            clock,
            _canonical(state),
        ):
            raise JournalError("full compact replay differs from hot head")
        return current

    def _read(self, operation, expected_checkpoint=None):
        if expected_checkpoint is not None:
            _check_checkpoint(expected_checkpoint)
        try:
            self._connection.execute("BEGIN")
            current = self._verified_current()
            if expected_checkpoint is not None and self._checkpoint(current) != expected_checkpoint:
                raise OptimisticConflict("read is not at caller's exact pinned compact checkpoint")
            result = operation(current)
            self._connection.commit()
            return result
        except BaseException:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    @_serialized
    def snapshot(self):
        return self._read(lambda current: current)

    @_serialized
    def checkpoint(self):
        return self._read(self._checkpoint)

    @_serialized
    def audit(self):
        return self._read(lambda current: self._audit())

    @_serialized
    def lookup(self, *, event_id, payload, at_ms, expected_checkpoint):
        _identifier(event_id, "event ID")
        _clock(at_ms)
        encoded = _canonical(payload)

        def operation(current):
            row = self._connection.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                return None
            _, outcome, _, _ = self._validate_event(row)
            if row["payload_json"] != encoded or row["clock_ms"] != at_ms:
                raise EventConflict("outer ID reused with conflicting exact request/clock")
            return AppendResult(current, outcome, True)

        return self._read(operation, expected_checkpoint)

    @_serialized
    def page_history(
        self, collection, *, expected_checkpoint, after_key=None, limit=500, max_bytes=2 * 1024 * 1024
    ):
        _key(collection, "key")
        if after_key is not None:
            _key(collection, after_key)
        _positive_bound(limit, "page limit", maximum=1000)
        _positive_bound(max_bytes, "page byte limit", maximum=8 * 1024 * 1024)

        def operation(current):
            rows = self._connection.execute(
                "SELECT * FROM cold_records WHERE collection=? AND key>? ORDER BY key LIMIT ?",
                (collection, "" if after_key is None else after_key, limit),
            )
            records, used, byte_stopped = [], 0, False
            for row in rows:
                size = len(row["key"].encode("utf-8")) + len(row["value_json"].encode("utf-8"))
                if used + size > max_bytes:
                    if not records:
                        raise JournalFull("first indexed history record exceeds caller page byte limit")
                    byte_stopped = True
                    break
                records.append(self._validate_cold(row))
                used += size
            records = tuple(records)
            return ColdHistoryPageV3(
                self._checkpoint(current),
                records,
                records[-1].key if records and (len(records) == limit or byte_stopped) else None,
            )

        return self._read(operation, expected_checkpoint)

    @_serialized
    def lookup_history(self, collection, key, *, expected_checkpoint):
        _key(collection, key)

        def operation(current):
            row = self._connection.execute(
                "SELECT * FROM cold_records WHERE collection=? AND key=?", (collection, key)
            ).fetchone()
            return None if row is None else self._validate_cold(row)

        return self._read(operation, expected_checkpoint)

    def _insert_cold(self, row):
        self._connection.execute(
            "INSERT INTO cold_records VALUES(?,?,?,?,?,?,?,?,?,?)",
            tuple(
                row[key]
                for key in (
                    "ordinal",
                    "collection",
                    "collection_ordinal",
                    "key",
                    "value_json",
                    "content_hash",
                    "previous_hash",
                    "record_hash",
                    "outer_version",
                    "within_outer",
                )
            ),
        )

    def _before_commit(self):
        """Fault seam only; not external transaction authority."""

    @_serialized
    def transition(self, *, event_id, payload, at_ms, expected_checkpoint, fold):
        _identifier(event_id, "event ID")
        _clock(at_ms)
        _check_checkpoint(expected_checkpoint)
        if type(payload) is not dict or not callable(fold):
            raise JournalError("plain exact envelope and owned driver fold required")
        payload_json = _canonical(payload)
        connection = self._connection
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self._verified_current()
            prior = connection.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            if prior is not None:
                _, outcome, _, _ = self._validate_event(prior)
                if prior["payload_json"] != payload_json or prior["clock_ms"] != at_ms:
                    raise EventConflict("outer ID reused with conflicting original request/clock")
                connection.commit()
                return AppendResult(current, outcome, True)
            if self._checkpoint(current) != expected_checkpoint:
                raise OptimisticConflict("exact version/state/head/clock fence differs")
            if at_ms < current.last_clock_ms or current.version >= self.limits.max_event_rows:
                raise JournalFull("driver clock/event capacity boundary refused")
            state = _copy(current.state)
            stage = _ColdTransaction(self, state, current.version + 1)
            self._stage = stage
            outcome = fold(state, stage)
            state["history_refs"] = stage.refs
            state_json = self._hot_json(state)
            self._boundary(current.state, state, event_id, _load(payload_json), at_ms)
            requested_keys = {
                (record["collection"], record["key"])
                for record in _load(payload_json).get("cold_records", [])
            }
            if any((row["collection"], row["key"]) not in requested_keys for row in stage.rows):
                raise JournalError("cold insertion is absent from exact original request")
            cold_json = _canonical([_cold_reference(row) for row in stage.rows])
            outcome_json, delta_json = _canonical(outcome), _canonical(make_delta(current.state, state))
            size = (
                len(event_id.encode("utf-8"))
                + sum(
                    len(value.encode("utf-8"))
                    for value in (payload_json, outcome_json, delta_json, cold_json)
                )
                + stage.byte_count
            )
            if size > self.limits.max_event_bytes:
                raise JournalFull("atomic compact event/native original byte cap exceeded")
            # Every requested original must be staged or already durable, never
            # merely claimed by the pending envelope.
            if current.state["pending"] is not None:
                for requested in _load(payload_json)["cold_records"]:
                    actual = stage.lookup(requested["collection"], requested["key"])
                    if actual is None or _canonical(actual.value) != _canonical(requested["value"]):
                        raise JournalError("requested original absent from exact cold prefix")
            row = {
                "version": current.version + 1,
                "event_id": event_id,
                "payload_json": payload_json,
                "payload_hash": _hash(payload_json),
                "outcome_json": outcome_json,
                "outcome_hash": _hash(outcome_json),
                "delta_json": delta_json,
                "delta_hash": _hash(delta_json),
                "cold_json": cold_json,
                "cold_hash": _hash(cold_json),
                "state_hash": _hash(state_json),
                "previous_hash": current.head_hash,
                "clock_ms": at_ms,
            }
            row["event_hash"] = _event_hash(row)
            for original in stage.rows:
                self._insert_cold(original)
            columns = tuple(row)
            connection.execute(
                f"INSERT INTO events({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                tuple(row.values()),
            )
            connection.execute(
                "UPDATE head SET version=?,state_json=?,state_hash=?,head_hash=?,"
                "last_clock_ms=?,state_bytes=? WHERE singleton=1",
                (
                    row["version"],
                    state_json,
                    row["state_hash"],
                    row["event_hash"],
                    at_ms,
                    len(state_json.encode("utf-8")),
                ),
            )
            _verify_database_pages(connection, self.limits.max_database_bytes)
            verified = self._current()
            if (verified.state_hash, verified.head_hash) != (row["state_hash"], row["event_hash"]):
                raise JournalError("hot/cold projection verification failed before commit")
            self._before_commit()
            connection.commit()
            result = JournalSnapshot(row["version"], state, row["state_hash"], row["event_hash"], at_ms)
            self._retained = self._checkpoint(result)
            return AppendResult(result, _load(outcome_json), False)
        except BaseException as error:
            if connection.in_transaction:
                connection.rollback()
            if isinstance(error, sqlite3.DatabaseError) and "full" in str(error).casefold():
                raise JournalFull("pinned SQLite capacity reached; compact commit rolled back") from error
            raise
        finally:
            if self._stage is not None:
                self._stage.active = False
                self._stage.rows.clear()
                self._stage.index.clear()
            self._stage = None

    def record_intent(self, pending, *, at_ms, expected_checkpoint):
        frozen = _copy(pending)

        def fold(state, cold):
            state["pending"] = frozen
            return {"status": "INTENT_RECORDED"}

        return self.transition(
            event_id=f"operation:{expected_checkpoint.version // 2}:intent",
            payload={"pending": frozen},
            at_ms=at_ms,
            expected_checkpoint=expected_checkpoint,
            fold=fold,
        )

    def commit_operation(
        self,
        *,
        operation,
        pending_sha256,
        account_checkpoints,
        cold_records,
        at_ms,
        expected_checkpoint,
        report=None,
    ):
        if type(cold_records) is not tuple or any(
            type(record) is not ColdHistoryRecordV3 for record in cold_records
        ):
            raise JournalError("bounded exact typed cold record tuple required")
        if len(cold_records) > self.limits.max_records_per_commit:
            raise JournalFull("original cold request roster exceeds pinned bound")
        accounts = {arm: asdict(cp) for arm, cp in _accounts(account_checkpoints).items()}
        payload = _copy(
            {
                "operation": operation,
                "pending_sha256": pending_sha256,
                "account_checkpoints": accounts,
                "cold_records": [asdict(record) for record in cold_records],
                "report": report,
            }
        )

        def fold(state, cold):
            for requested in payload["cold_records"]:
                cold.append(ColdHistoryRecordV3(**requested))
            state.update(pending=None, cursor=state["cursor"] + 1, account_checkpoints=accounts)
            if operation.get("kind") == "FINISH":
                state.update(finished=True, report=payload["report"])
            return {"status": "COMMITTED", "operation_cursor": state["cursor"]}

        return self.transition(
            event_id=f"operation:{(expected_checkpoint.version - 1) // 2}:commit",
            payload=payload,
            at_ms=at_ms,
            expected_checkpoint=expected_checkpoint,
            fold=fold,
        )

    def close(self):
        with self._lock:
            if self._stage is not None:
                raise JournalError("cannot close active compact transaction")
            self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
