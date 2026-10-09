"""Additive, create-only delta persistence for a bounded research SIM.

Events retain canonical recursive map/list changes, not complete historical
state copies. The current projection is an indexed tree: only changed nodes
are written. Full canonical state SHA256 remains compatible with the old SIM
journal, so hashing and returning a complete snapshot still cost O(state).
This is storage infrastructure, not a five-day portfolio or source admission.

The default row budget is explicit: 36,000 candle events, 36,000 denominator
events, 432,000 five-symbol BBO events at a DECLARED five-second cadence over
five days, and 8,192 control/admission events. It is not 100ms or indefinite
coverage. Independent state/event/database bounds can refuse this roster if
its actual bytes are too large; no rows, failures or account history are evicted.

Open and audit replay every delta. Append checks the current projection, tail
and retained checkpoint before an optimistic transition, not the entire old
history on every write. Call audit for historical validation. Hashes are local
consistency evidence, not hostile-owner authentication or reducer correctness.
No old adoption, repair, migration, retry, provider or primary DB authority.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from functools import wraps
from typing import Any

from .sim_state_journal import (
    AppendResult,
    EventConflict,
    IdentityMismatch,
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

SCHEMA_VERSION = 3
SCHEMA_ID = "kairos.research.sim-delta-journal.v3"
FIVE_DAY_MINUTES = 5 * 24 * 60
FIVE_SYMBOL_CELLS = FIVE_DAY_MINUTES * 5
DECLARED_BBO_CADENCE_MS = 5_000
DEFAULT_MAX_EVENT_ROWS = 2 * FIVE_SYMBOL_CELLS + 5 * (5 * 86_400_000 // DECLARED_BBO_CADENCE_MS) + 8_192
MAX_EVENT_ROWS = 1_000_000
MAX_EVENT_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_STATE_BYTES = 32 * 1024 * 1024
MAX_STATE_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_DATABASE_BYTES = 512 * 1024 * 1024
MAX_DATABASE_BYTES = 4 * 1024 * 1024 * 1024
MAX_PROJECTION_NODES = 1_000_000
MAX_DELTA_OPERATIONS = 100_000
MAX_PATH_BYTES = 8_192

_DDL = {
    "metadata": "CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "events": (
        "CREATE TABLE events(version INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, "
        "payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, outcome_json TEXT NOT NULL, "
        "outcome_hash TEXT NOT NULL, delta_json TEXT NOT NULL, delta_hash TEXT NOT NULL, "
        "state_hash TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL, "
        "clock_ms INTEGER NOT NULL)"
    ),
    "projection": (
        "CREATE TABLE projection(path TEXT PRIMARY KEY, kind TEXT NOT NULL, value_json TEXT NOT NULL)"
    ),
    "head": (
        "CREATE TABLE head(singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL, "
        "state_hash TEXT NOT NULL, head_hash TEXT NOT NULL, last_clock_ms INTEGER NOT NULL, "
        "state_bytes INTEGER NOT NULL, node_count INTEGER NOT NULL)"
    ),
}


def _sha(value: Any) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise JournalError("exact lowercase SHA256 required")
    return value


def _object_json(value: Any) -> tuple[dict[str, Any], str]:
    if type(value) is not dict:
        raise ValueError("plain dict state/payload required")
    encoded = _canonical(value)
    return json.loads(encoded), encoded


def _load(encoded: Any) -> Any:
    if type(encoded) is not str:
        raise JournalError("stored canonical JSON must be text")
    try:
        value = json.loads(encoded)
        if _canonical(value) != encoded:
            raise ValueError("not canonical")
    except (ValueError, TypeError, RecursionError) as error:
        raise JournalError("invalid or noncanonical stored JSON") from error
    return value


def _path(path: Any) -> str:
    if (
        type(path) is not list
        or len(path) > 64
        or any(type(x) is not str and not (type(x) is int and x >= 0) for x in path)
    ):
        raise JournalError("bounded exact map/list path required")
    encoded = _canonical(path)
    if len(encoded.encode("utf-8")) > MAX_PATH_BYTES:
        raise JournalFull("projection path byte bound exceeded")
    return encoded


def _node_at(state: Any, path: list[Any]) -> Any:
    current = state
    for part in path:
        if type(current) is dict and type(part) is str and part in current:
            current = current[part]
        elif type(current) is list and type(part) is int and 0 <= part < len(current):
            current = current[part]
        else:
            raise JournalError("delta path does not address an exact existing node")
    return current


def make_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Unique deterministic recursive changes, including append-only histories."""
    old, _ = _object_json(before)
    new, _ = _object_json(after)
    operations: list[dict[str, Any]] = []

    def walk(a, b, path):
        if type(a) is dict and type(b) is dict:
            for key in sorted(a.keys() - b.keys()):
                operations.append({"op": "REMOVE", "path": [*path, key]})
            for key in sorted(a.keys() & b.keys()):
                walk(a[key], b[key], [*path, key])
            for key in sorted(b.keys() - a.keys()):
                operations.append({"op": "SET", "path": [*path, key], "value": b[key]})
        elif type(a) is list and type(b) is list:
            common = min(len(a), len(b))
            for index in range(common):
                walk(a[index], b[index], [*path, index])
            if len(b) < len(a):
                operations.append({"op": "TRUNCATE", "path": path, "length": len(b)})
            elif len(b) > len(a):
                operations.append({"op": "APPEND", "path": path, "values": b[common:]})
        elif type(a) is not type(b) or a != b:
            operations.append({"op": "SET", "path": path, "value": b})

    walk(old, new, [])
    if len(operations) > MAX_DELTA_OPERATIONS:
        raise JournalFull("delta operation count bound exceeded")
    for operation in operations:
        _path(operation["path"])
    return {"operations": operations}


def apply_delta(before: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    """Apply only the exact closed-schema delta; never coerce path types."""
    state, _ = _object_json(before)
    if type(delta) is not dict or set(delta) != {"operations"} or type(delta["operations"]) is not list:
        raise JournalError("exact delta document required")
    if len(delta["operations"]) > MAX_DELTA_OPERATIONS:
        raise JournalFull("delta operation count bound exceeded")
    for operation in delta["operations"]:
        if type(operation) is not dict:
            raise JournalError("exact delta operation required")
        op, path = operation.get("op"), operation.get("path")
        _path(path)
        fields = {
            "SET": {"op", "path", "value"},
            "REMOVE": {"op", "path"},
            "APPEND": {"op", "path", "values"},
            "TRUNCATE": {"op", "path", "length"},
        }
        if type(op) is not str or op not in fields or set(operation) != fields[op]:
            raise JournalError("unknown or noncanonical delta operation fields")
        if op == "SET":
            value = json.loads(_canonical(operation["value"]))
            if not path:
                if type(value) is not dict:
                    raise JournalError("delta root must remain a dict")
                state = value
            else:
                parent = _node_at(state, path[:-1])
                key = path[-1]
                if type(parent) is dict and type(key) is str:
                    parent[key] = value
                elif type(parent) is list and type(key) is int and key < len(parent):
                    parent[key] = value
                else:
                    raise JournalError("invalid SET parent/path")
        elif op == "REMOVE":
            if not path:
                raise JournalError("cannot remove root")
            parent = _node_at(state, path[:-1])
            key = path[-1]
            if type(parent) is not dict or type(key) is not str or key not in parent:
                raise JournalError("REMOVE requires an existing map key")
            del parent[key]
        else:
            target = _node_at(state, path)
            if type(target) is not list:
                raise JournalError("list delta requires an existing list")
            if op == "APPEND":
                if type(operation["values"]) is not list or not operation["values"]:
                    raise JournalError("APPEND requires a nonempty exact list")
                target.extend(json.loads(_canonical(operation["values"])))
            else:
                length = operation["length"]
                if type(length) is not int or not 0 <= length < len(target):
                    raise JournalError("TRUNCATE requires a strictly smaller exact length")
                del target[length:]
    return state


@dataclass(frozen=True)
class DeltaCheckpointV3:
    identity_sha256: str
    version: int
    state_hash: str
    head_hash: str
    last_clock_ms: int

    def __post_init__(self):
        for value in (self.identity_sha256, self.state_hash, self.head_hash):
            _sha(value)
        if type(self.version) is not int or self.version < 0:
            raise ValueError("exact nonnegative checkpoint version required")
        _clock(self.last_clock_ms)


def _event_hash(row):
    return _hash(
        _canonical(
            [
                SCHEMA_ID,
                row["previous_hash"],
                row["version"],
                row["event_id"],
                row["payload_hash"],
                row["outcome_hash"],
                row["delta_hash"],
                row["state_hash"],
                row["clock_ms"],
            ]
        )
    )


def _serialized(function):
    @wraps(function)
    def guarded(self, *args, **kwargs):
        with self._operation_lock:
            return function(self, *args, **kwargs)

    return guarded


def _count_nodes(state):
    pending, count = [state], 0
    while pending:
        node = pending.pop()
        count += 1
        if count > MAX_PROJECTION_NODES:
            raise JournalFull("projection node bound exceeded before write")
        if type(node) is dict:
            pending.extend(node.values())
        elif type(node) is list:
            pending.extend(node)
    return count


class SimDeltaJournalV3:
    """Indexed atomic projection plus append-only deltas; no daily reset."""

    def __init__(
        self,
        connection,
        path,
        identity,
        *,
        max_event_rows,
        max_event_bytes,
        max_state_bytes,
        max_database_bytes,
    ):
        self._connection, self.path, self.identity = connection, path, identity
        self.max_event_rows = _positive_bound(max_event_rows, "max_event_rows", maximum=MAX_EVENT_ROWS)
        self.max_event_bytes = _positive_bound(max_event_bytes, "max_event_bytes", maximum=MAX_EVENT_BYTES)
        self.max_state_bytes = _positive_bound(max_state_bytes, "max_state_bytes", maximum=MAX_STATE_BYTES)
        self.max_database_bytes = _positive_bound(
            max_database_bytes, "max_database_bytes", maximum=MAX_DATABASE_BYTES
        )
        if self.max_database_bytes < 32 * 1024:
            raise ValueError("database byte bound must be at least 32768")
        self._file_identity = _file_identity(path)
        self._retained_checkpoint = None
        self._operation_lock = threading.RLock()

    @classmethod
    def create(
        cls,
        path,
        *,
        identity,
        initial_state,
        initial_clock_ms,
        max_event_rows=DEFAULT_MAX_EVENT_ROWS,
        max_event_bytes=MAX_EVENT_BYTES,
        max_state_bytes=DEFAULT_MAX_STATE_BYTES,
        max_database_bytes=DEFAULT_MAX_DATABASE_BYTES,
    ):
        destination = _safe_path(path, must_exist=False)
        if type(identity) is not JournalIdentity:
            raise TypeError("exact JournalIdentity required")
        _clock(initial_clock_ms)
        state, encoded = _object_json(initial_state)
        # Validate all caller bounds before reserving a file.
        for value, name, maximum in (
            (max_event_rows, "max_event_rows", MAX_EVENT_ROWS),
            (max_event_bytes, "max_event_bytes", MAX_EVENT_BYTES),
            (max_state_bytes, "max_state_bytes", MAX_STATE_BYTES),
            (max_database_bytes, "max_database_bytes", MAX_DATABASE_BYTES),
        ):
            _positive_bound(value, name, maximum=maximum)
        if max_database_bytes < 32 * 1024:
            raise ValueError("database byte bound must be at least 32768")
        if len(encoded.encode("utf-8")) > max_state_bytes:
            raise JournalFull("initial canonical state exceeds state byte bound")
        _count_nodes(state)
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
        connection = sqlite3.connect(
            str(destination), timeout=0, isolation_level=None, check_same_thread=False
        )
        connection.row_factory = sqlite3.Row
        try:
            _configure(connection)
            connection.execute("PRAGMA busy_timeout=0")
            _set_database_bound(connection, max_database_bytes)
            for ddl in _DDL.values():
                connection.execute(ddl)
            connection.execute("BEGIN IMMEDIATE")
            journal = cls(
                connection,
                destination,
                identity,
                max_event_rows=max_event_rows,
                max_event_bytes=max_event_bytes,
                max_state_bytes=max_state_bytes,
                max_database_bytes=max_database_bytes,
            )
            identity_json = _canonical(identity.__dict__)
            state_hash = _hash(encoded)
            genesis = _hash(_canonical([SCHEMA_ID, identity_json, state_hash, initial_clock_ms]))
            metadata = {
                **journal._configuration(),
                "initial_state_json": encoded,
                "initial_state_hash": state_hash,
                "initial_clock_ms": str(initial_clock_ms),
                "genesis_hash": genesis,
            }
            connection.executemany("INSERT INTO metadata VALUES(?,?)", metadata.items())
            journal._insert_tree([], state)
            nodes = connection.execute("SELECT COUNT(*) FROM projection").fetchone()[0]
            connection.execute(
                "INSERT INTO head VALUES(1,0,?,?,?,?,?)",
                (state_hash, genesis, initial_clock_ms, len(encoded.encode("utf-8")), nodes),
            )
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            journal._audit()
            _verify_database_pages(connection, max_database_bytes)
            connection.commit()
            journal._retained_checkpoint = journal._checkpoint(journal._current())
            return journal
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
            raise  # preserve interrupted/partial creates; never delete or adopt them

    @classmethod
    def open(
        cls,
        path,
        *,
        identity,
        expected_checkpoint,
        max_event_rows=DEFAULT_MAX_EVENT_ROWS,
        max_event_bytes=MAX_EVENT_BYTES,
        max_state_bytes=DEFAULT_MAX_STATE_BYTES,
        max_database_bytes=DEFAULT_MAX_DATABASE_BYTES,
    ):
        source = _safe_path(path, must_exist=True)
        if type(identity) is not JournalIdentity or type(expected_checkpoint) is not DeltaCheckpointV3:
            raise TypeError("independent typed identity and exact V3 checkpoint required")
        DeltaCheckpointV3(**expected_checkpoint.__dict__)
        _verify_database_file_size(source, max_database_bytes)
        file_identity = _file_identity(source)
        connection = sqlite3.connect(_existing_uri(source, readonly=True), uri=True, timeout=0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            journal = cls(
                connection,
                source,
                identity,
                max_event_rows=max_event_rows,
                max_event_bytes=max_event_bytes,
                max_state_bytes=max_state_bytes,
                max_database_bytes=max_database_bytes,
            )
            snapshot = journal._audit()
            if journal._checkpoint(snapshot) != expected_checkpoint:
                raise JournalError("independent exact restart checkpoint differs from current head")
            connection.commit()
        finally:
            connection.close()
        if _file_identity(source) != file_identity:
            raise JournalError("file identity changed after read-only audit")
        connection = sqlite3.connect(
            _existing_uri(source), uri=True, timeout=0, isolation_level=None, check_same_thread=False
        )
        connection.row_factory = sqlite3.Row
        try:
            if _file_identity(source) != file_identity:
                raise JournalError("file identity changed before writable open")
            _configure(connection)
            connection.execute("PRAGMA busy_timeout=0")
            _set_database_bound(connection, max_database_bytes)
            journal = cls(
                connection,
                source,
                identity,
                max_event_rows=max_event_rows,
                max_event_bytes=max_event_bytes,
                max_state_bytes=max_state_bytes,
                max_database_bytes=max_database_bytes,
            )
            connection.execute("BEGIN IMMEDIATE")
            snapshot = journal._audit()
            if journal._checkpoint(snapshot) != expected_checkpoint:
                raise JournalError("restart checkpoint changed before writable open")
            connection.commit()
            journal._retained_checkpoint = expected_checkpoint
            return journal
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
            raise

    def _configuration(self):
        return {
            "schema": SCHEMA_ID,
            "identity": _canonical(self.identity.__dict__),
            "max_event_rows": str(self.max_event_rows),
            "max_event_bytes": str(self.max_event_bytes),
            "max_state_bytes": str(self.max_state_bytes),
            "max_database_bytes": str(self.max_database_bytes),
        }

    def _check_storage(self):
        if _file_identity(self.path) != self._file_identity:
            raise JournalError("journal path/file identity changed")
        _verify_database_file_size(self.path, self.max_database_bytes, self._connection)
        objects = self._connection.execute("SELECT type,name,sql FROM sqlite_master").fetchall()
        expected = {name: ("table", _normalize_sql(ddl)) for name, ddl in _DDL.items()}
        expected.update(
            {f"sqlite_autoindex_{name}_1": ("index", None) for name in ("metadata", "events", "projection")}
        )
        if {r["name"]: (r["type"], _normalize_sql(r["sql"])) for r in objects} != expected:
            raise JournalError("exact additive V3 schema whitelist required")
        if self._connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise JournalError("V3 schema version conflict; no migration")
        if self._connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
            raise JournalError("pinned DELETE journal mode required")
        metadata = dict(self._connection.execute("SELECT key,value FROM metadata").fetchall())
        expected_keys = set(self._configuration()) | {
            "initial_state_json",
            "initial_state_hash",
            "initial_clock_ms",
            "genesis_hash",
        }
        if set(metadata) != expected_keys:
            raise JournalError("exact bounded V3 metadata keys required")
        for key, value in self._configuration().items():
            if metadata[key] != value:
                if key == "identity":
                    raise IdentityMismatch("caller-pinned V3 identity differs")
                raise JournalError(f"caller-pinned V3 configuration differs: {key}")
        if len(metadata["initial_state_json"].encode("utf-8")) > self.max_state_bytes or any(
            len(value.encode("utf-8")) > 8192
            for key, value in metadata.items()
            if key != "initial_state_json"
        ):
            raise JournalError("stored metadata byte bound exceeded")
        return metadata

    def _insert_tree(self, path, value):
        kind = "MAP" if type(value) is dict else "LIST" if type(value) is list else "SCALAR"
        stored = None if kind == "MAP" else len(value) if kind == "LIST" else value
        self._connection.execute(
            "INSERT INTO projection VALUES(?,?,?)", (_path(path), kind, _canonical(stored))
        )
        if kind == "MAP":
            for key in sorted(value):
                self._insert_tree([*path, key], value[key])
        elif kind == "LIST":
            for index, child in enumerate(value):
                self._insert_tree([*path, index], child)

    def _delete_tree(self, path):
        encoded = _path(path)
        if not path:
            self._connection.execute("DELETE FROM projection")
        else:
            prefix = encoded[:-1] + ","
            self._connection.execute(
                "DELETE FROM projection WHERE path=? OR (path>=? AND path<?)",
                (encoded, prefix, prefix + "\uffff"),
            )

    def _update_projection(self, delta):
        for op in delta["operations"]:
            path = op["path"]
            if op["op"] in {"SET", "REMOVE"}:
                self._delete_tree(path)
                if op["op"] == "SET":
                    self._insert_tree(path, op["value"])
            else:
                encoded = _path(path)
                row = self._connection.execute(
                    "SELECT kind,value_json FROM projection WHERE path=?", (encoded,)
                ).fetchone()
                if row is None or row["kind"] != "LIST":
                    raise JournalError("projection list target missing")
                length = _load(row["value_json"])
                if op["op"] == "APPEND":
                    for index, value in enumerate(op["values"], length):
                        self._insert_tree([*path, index], value)
                    new_length = length + len(op["values"])
                else:
                    new_length = op["length"]
                    for index in range(new_length, length):
                        self._delete_tree([*path, index])
                self._connection.execute(
                    "UPDATE projection SET value_json=? WHERE path=?", (_canonical(new_length), encoded)
                )

    def _read_projection(self):
        rows = self._connection.execute(
            "SELECT path,kind,value_json FROM projection ORDER BY length(path),path"
        ).fetchmany(MAX_PROJECTION_NODES + 1)
        if not rows or len(rows) > MAX_PROJECTION_NODES:
            raise JournalFull("projection node bound exceeded")
        state = None
        lists = []
        sentinel = object()
        for row in rows:
            path = _load(row["path"])
            if _path(path) != row["path"]:
                raise JournalError("noncanonical projection path")
            stored = _load(row["value_json"])
            if row["kind"] == "MAP" and stored is None:
                value = {}
            elif row["kind"] == "LIST" and type(stored) is int and 0 <= stored <= MAX_PROJECTION_NODES:
                value = [sentinel] * stored
                lists.append(value)
            elif row["kind"] == "SCALAR" and type(stored) not in {dict, list}:
                value = stored
            else:
                raise JournalError("invalid exact projection node kind/value")
            if not path:
                if state is not None or type(value) is not dict:
                    raise JournalError("exact single map projection root required")
                state = value
                continue
            parent = _node_at(state, path[:-1])
            key = path[-1]
            if type(parent) is dict and type(key) is str and key not in parent:
                parent[key] = value
            elif type(parent) is list and type(key) is int and key < len(parent) and parent[key] is sentinel:
                parent[key] = value
            else:
                raise JournalError("projection orphan/duplicate child/path conflict")
        if any(any(child is sentinel for child in value) for value in lists):
            raise JournalError("projection list lost a retained child")
        return state, len(rows)

    def _validate_event(self, row):
        _identifier(row["event_id"], "stored event_id")
        if type(row["version"]) is not int or row["version"] < 1:
            raise JournalError("exact positive event version required")
        _clock(row["clock_ms"])
        for key in (
            "payload_hash",
            "outcome_hash",
            "delta_hash",
            "state_hash",
            "previous_hash",
            "event_hash",
        ):
            _sha(row[key])
        size = len(row["event_id"].encode("utf-8")) + sum(
            len(row[key].encode("utf-8")) for key in ("payload_json", "outcome_json", "delta_json")
        )
        if size > self.max_event_bytes:
            raise JournalFull("stored canonical event exceeds byte bound")
        payload, outcome, delta = (_load(row[key]) for key in ("payload_json", "outcome_json", "delta_json"))
        if type(payload) is not dict:
            raise JournalError("stored event payload must remain a map")
        for text, sha in (
            ("payload_json", "payload_hash"),
            ("outcome_json", "outcome_hash"),
            ("delta_json", "delta_hash"),
        ):
            if _hash(row[text]) != row[sha]:
                raise JournalError("event canonical bytes/hash conflict")
        if _event_hash(row) != row["event_hash"]:
            raise JournalError("event commitment conflict")
        return payload, outcome, delta

    def _current(self):
        metadata = self._check_storage()
        rows = self._connection.execute("SELECT * FROM head").fetchall()
        if len(rows) != 1 or rows[0]["singleton"] != 1:
            raise JournalError("exact single projection head required")
        head = rows[0]
        if type(head["version"]) is not int or not 0 <= head["version"] <= self.max_event_rows:
            raise JournalError("head version bound conflict")
        _sha(head["state_hash"])
        _sha(head["head_hash"])
        _clock(head["last_clock_ms"])
        if self._connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] != head["version"]:
            raise JournalError("event count/head truncation conflict")
        state, nodes = self._read_projection()
        encoded = _canonical(state)
        state_bytes = len(encoded.encode("utf-8"))
        if state_bytes > self.max_state_bytes:
            raise JournalFull("current canonical state byte bound exceeded")
        if (
            head["state_bytes"] != state_bytes
            or head["node_count"] != nodes
            or _hash(encoded) != head["state_hash"]
        ):
            raise JournalError("indexed projection differs from its committed state")
        if head["version"]:
            tail = self._connection.execute(
                "SELECT * FROM events WHERE version=?", (head["version"],)
            ).fetchone()
            if tail is None:
                raise JournalError("current event tail missing")
            self._validate_event(tail)
            if (tail["event_hash"], tail["state_hash"], tail["clock_ms"]) != (
                head["head_hash"],
                head["state_hash"],
                head["last_clock_ms"],
            ):
                raise JournalError("event tail/current projection conflict")
        elif (head["head_hash"], head["state_hash"], str(head["last_clock_ms"])) != (
            metadata["genesis_hash"],
            metadata["initial_state_hash"],
            metadata["initial_clock_ms"],
        ):
            raise JournalError("empty current head differs from genesis")
        snapshot = JournalSnapshot(
            head["version"], state, head["state_hash"], head["head_hash"], head["last_clock_ms"]
        )
        prior = self._retained_checkpoint
        if prior is not None:
            if snapshot.version < prior.version:
                raise JournalError("journal rolled back behind retained checkpoint")
            retained = (
                self._connection.execute(
                    "SELECT event_hash FROM events WHERE version=?", (prior.version,)
                ).fetchone()
                if prior.version
                else None
            )
            actual = (
                retained[0]
                if retained is not None
                else self._check_storage()["genesis_hash"]
                if prior.version == 0
                else None
            )
            if actual != prior.head_hash:
                raise JournalError("retained checkpoint prefix diverged")
        return snapshot

    def _audit(self):
        metadata = self._check_storage()
        if self._connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise JournalError("SQLite integrity check failed")
        state = _load(metadata["initial_state_json"])
        if type(state) is not dict or _hash(metadata["initial_state_json"]) != _sha(
            metadata["initial_state_hash"]
        ):
            raise JournalError("initial state commitment conflict")
        try:
            clock = int(metadata["initial_clock_ms"])
        except ValueError as error:
            raise JournalError("initial clock invalid") from error
        _clock(clock)
        if str(clock) != metadata["initial_clock_ms"]:
            raise JournalError("initial clock is not canonical")
        previous = _hash(_canonical([SCHEMA_ID, metadata["identity"], metadata["initial_state_hash"], clock]))
        if previous != metadata["genesis_hash"]:
            raise JournalError("genesis commitment conflict")
        count = 0
        for row in self._connection.execute("SELECT * FROM events ORDER BY version"):
            count += 1
            if (
                count > self.max_event_rows
                or row["version"] != count
                or row["previous_hash"] != previous
                or row["clock_ms"] < clock
            ):
                raise JournalError("event sequence/clock/hash prefix conflict")
            _, _, delta = self._validate_event(row)
            after = apply_delta(state, delta)
            encoded = _canonical(after)
            if len(encoded.encode("utf-8")) > self.max_state_bytes:
                raise JournalFull("replayed state byte bound exceeded")
            if (
                _canonical(make_delta(state, after)) != row["delta_json"]
                or _hash(encoded) != row["state_hash"]
            ):
                raise JournalError("delta is not exact canonical recursive replay/state")
            state, previous, clock = after, row["event_hash"], row["clock_ms"]
        current = self._current()
        if (current.version, current.head_hash, current.last_clock_ms, _canonical(current.state)) != (
            count,
            previous,
            clock,
            _canonical(state),
        ):
            raise JournalError("delta replay differs from indexed current projection")
        return current

    def _checkpoint(self, snapshot):
        return DeltaCheckpointV3(
            _hash(_canonical(self.identity.__dict__)),
            snapshot.version,
            snapshot.state_hash,
            snapshot.head_hash,
            snapshot.last_clock_ms,
        )

    @_serialized
    def audit(self):
        """Full historical replay, not just current projection consistency."""
        connection = self._connection
        try:
            connection.execute("BEGIN")
            snapshot = self._audit()
            connection.commit()
            self._retained_checkpoint = self._checkpoint(snapshot)
            return snapshot
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise

    @_serialized
    def snapshot(self):
        """Validate current projection/tail and retained prefix, not old history."""
        connection = self._connection
        try:
            connection.execute("BEGIN")
            snapshot = self._current()
            connection.commit()
            self._retained_checkpoint = self._checkpoint(snapshot)
            return snapshot
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise

    @_serialized
    def checkpoint(self):
        """Caller must retain this outside the journal before a restart."""
        return self._checkpoint(self.snapshot())

    @_serialized
    def lookup(self, *, event_id, payload):
        _identifier(event_id, "event_id")
        _, encoded = _object_json(payload)
        connection = self._connection
        try:
            connection.execute("BEGIN")
            current = self._current()
            row = connection.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                connection.commit()
                return None
            _, outcome, _ = self._validate_event(row)
            if row["payload_hash"] != _hash(encoded):
                raise EventConflict("event ID reused with conflicting payload")
            connection.commit()
            self._retained_checkpoint = self._checkpoint(current)
            return AppendResult(current, outcome, True)
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise

    @_serialized
    def append(
        self,
        *,
        event_id,
        payload,
        outcome,
        state,
        expected_version,
        expected_state_hash,
        expected_head_sha256,
        at_ms,
    ):
        _identifier(event_id, "event_id")
        _clock(at_ms)
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError("exact nonnegative expected version required")
        _sha(expected_state_hash)
        _sha(expected_head_sha256)
        _, payload_json = _object_json(payload)
        after, state_json = _object_json(state)
        outcome_json = _canonical(outcome)
        if len(state_json.encode("utf-8")) > self.max_state_bytes:
            raise JournalFull("canonical next state exceeds state byte bound")
        _count_nodes(after)
        connection = self._connection
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self._current()
            prior = connection.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            if prior is not None:
                _, old_outcome, _ = self._validate_event(prior)
                if prior["payload_hash"] != _hash(payload_json):
                    raise EventConflict("event ID reused with conflicting payload")
                connection.commit()
                self._retained_checkpoint = self._checkpoint(current)
                return AppendResult(current, old_outcome, True)
            if (current.version, current.state_hash, current.head_hash) != (
                expected_version,
                expected_state_hash,
                expected_head_sha256,
            ):
                raise OptimisticConflict("prior version/state/head fence no longer matches")
            if at_ms < current.last_clock_ms:
                raise JournalError("event clock regressed")
            if current.version >= self.max_event_rows:
                raise JournalFull("append-only event row bound reached; nothing evicted")
            delta = make_delta(current.state, after)
            delta_json = _canonical(delta)
            size = len(event_id.encode("utf-8")) + sum(
                len(x.encode("utf-8")) for x in (payload_json, outcome_json, delta_json)
            )
            if size > self.max_event_bytes:
                raise JournalFull("canonical event/delta byte bound exceeded")
            row = {
                "version": current.version + 1,
                "event_id": event_id,
                "payload_json": payload_json,
                "payload_hash": _hash(payload_json),
                "outcome_json": outcome_json,
                "outcome_hash": _hash(outcome_json),
                "delta_json": delta_json,
                "delta_hash": _hash(delta_json),
                "state_hash": _hash(state_json),
                "previous_hash": current.head_hash,
                "clock_ms": at_ms,
            }
            row["event_hash"] = _event_hash(row)
            columns = tuple(row)
            connection.execute(
                f"INSERT INTO events({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                tuple(row.values()),
            )
            self._update_projection(delta)
            nodes = connection.execute("SELECT COUNT(*) FROM projection").fetchone()[0]
            if nodes > MAX_PROJECTION_NODES:
                raise JournalFull("projection node bound exceeded")
            connection.execute(
                "UPDATE head SET version=?,state_hash=?,head_hash=?,last_clock_ms=?,state_bytes=?,"
                "node_count=? "
                "WHERE singleton=1",
                (
                    row["version"],
                    row["state_hash"],
                    row["event_hash"],
                    at_ms,
                    len(state_json.encode("utf-8")),
                    nodes,
                ),
            )
            _verify_database_pages(connection, self.max_database_bytes)
            connection.commit()
            snapshot = JournalSnapshot(row["version"], after, row["state_hash"], row["event_hash"], at_ms)
            self._retained_checkpoint = self._checkpoint(snapshot)
            return AppendResult(snapshot, json.loads(outcome_json), False)
        except BaseException as error:
            if connection.in_transaction:
                connection.rollback()
            if isinstance(error, sqlite3.DatabaseError) and "full" in str(error).casefold():
                raise JournalFull("caller-pinned SQLite byte bound reached; append rolled back") from error
            raise

    @_serialized
    def close(self):
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
