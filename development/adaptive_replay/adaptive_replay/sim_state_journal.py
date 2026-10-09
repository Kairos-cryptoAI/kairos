"""Create-only SQLite journal for isolated SIM reducer state.

This module stores caller-supplied events and complete state projections. It has
no provider, trading, primary-database, or strategy authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote

SCHEMA_VERSION = 1
MAX_EVENT_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_DATABASE_BYTES = 64 * 1024 * 1024
MAX_DATABASE_BYTES = 512 * 1024 * 1024
MAX_EVENT_ROWS = 10_000
MAX_METADATA_VALUE_BYTES = 2 * 1024 * 1024
_GENESIS = "0" * 64


class JournalError(RuntimeError):
    """Base error for integrity, schema, or persistence failures."""


class IdentityMismatch(JournalError):
    """Stored campaign/source/policy/implementation identity differs."""


class OptimisticConflict(JournalError):
    """The caller's prior state version/hash is no longer current."""


class EventConflict(JournalError):
    """An event identifier was reused with different content."""


class JournalFull(JournalError):
    """The configured append-only event row limit was reached."""


@dataclass(frozen=True)
class JournalIdentity:
    campaign_id: str
    source_id: str
    policy_id: str
    implementation_id: str

    def __post_init__(self) -> None:
        for name in ("campaign_id", "source_id", "policy_id", "implementation_id"):
            _identifier(getattr(self, name), name)


@dataclass(frozen=True)
class JournalSnapshot:
    version: int
    state: dict[str, Any]
    state_hash: str
    head_hash: str
    last_clock_ms: int


@dataclass(frozen=True)
class AppendResult:
    snapshot: JournalSnapshot
    outcome: Any
    replayed: bool


def _identifier(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > 128:
        raise ValueError(f"{name} must be a normalized nonempty identifier (max 128 chars)")
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise ValueError(f"{name} must use printable canonical ASCII")
    return value


def _clock(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("clock must be a nonnegative integer millisecond value")
    return value


def _json_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 64:
        raise ValueError("JSON document exceeds maximum nesting depth")
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is Decimal:
        if not value.is_finite():
            raise ValueError("non-finite Decimal cannot be journaled")
        return str(value)
    if type(value) is float:
        raise ValueError("float values are forbidden in deterministic SIM JSON")
    if type(value) is list or type(value) is tuple:
        return [_json_value(item, depth=depth + 1) for item in value]
    if type(value) is dict:
        result: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("JSON object keys must be strings")
            result[key] = _json_value(item, depth=depth + 1)
        return result
    raise ValueError(f"unsupported JSON value type: {type(value).__name__}")


def _canonical(value: Any) -> str:
    normalized = _json_value(value)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest_event(
    *,
    previous_hash: str,
    version: int,
    event_id: str,
    payload_hash: str,
    outcome_hash: str,
    state_hash: str,
    clock_ms: int,
) -> str:
    canonical = _canonical(
        [
            "SIM_STATE_EVENT_V1",
            previous_hash,
            version,
            event_id,
            payload_hash,
            outcome_hash,
            state_hash,
            clock_ms,
        ]
    )
    return _hash(canonical)


def _snapshot_from_row(row: tuple[Any, ...]) -> JournalSnapshot:
    version, state_json, state_hash, head_hash, clock_ms = row
    return JournalSnapshot(version, json.loads(state_json), state_hash, head_hash, clock_ms)


class SimStateJournal:
    """Append-only event/state journal with optimistic, atomic transitions.

    `max_event_rows`, `max_event_bytes`, and `max_database_bytes` are
    caller-pinned storage bounds. Hashes detect accidental inconsistency only;
    they do not prevent a malicious owner from rewriting the database and
    recomputing its chain, or prove that a reducer was replayed correctly.
    Event bytes cover UTF-8 event id, canonical payload, outcome and complete
    state projection. `max_event_bytes` may not exceed 2 MiB.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        identity: JournalIdentity,
        *,
        max_event_rows: int,
        max_event_bytes: int,
        max_database_bytes: int = DEFAULT_MAX_DATABASE_BYTES,
    ) -> None:
        self._connection = connection
        self.identity = identity
        self.max_event_rows = _positive_bound(max_event_rows, "max_event_rows")
        if self.max_event_rows > MAX_EVENT_ROWS:
            raise ValueError(f"max_event_rows must be <= {MAX_EVENT_ROWS}")
        self.max_event_bytes = _positive_bound(max_event_bytes, "max_event_bytes", maximum=MAX_EVENT_BYTES)
        self.max_database_bytes = _positive_bound(
            max_database_bytes, "max_database_bytes", maximum=MAX_DATABASE_BYTES
        )

    @classmethod
    def create(
        cls,
        path: str | Path,
        *,
        identity: JournalIdentity,
        initial_state: dict[str, Any],
        initial_clock_ms: int,
        max_event_rows: int,
        max_event_bytes: int = MAX_EVENT_BYTES,
        max_database_bytes: int = DEFAULT_MAX_DATABASE_BYTES,
    ) -> SimStateJournal:
        destination = _safe_path(path, must_exist=False)
        if not isinstance(identity, JournalIdentity):
            raise TypeError("identity must be a JournalIdentity")
        initial_clock_ms = _clock(initial_clock_ms)
        _require_state(initial_state)
        row_limit = _positive_bound(max_event_rows, "max_event_rows")
        if row_limit > MAX_EVENT_ROWS:
            raise ValueError(f"max_event_rows must be <= {MAX_EVENT_ROWS}")
        byte_limit = _positive_bound(max_event_bytes, "max_event_bytes", maximum=MAX_EVENT_BYTES)
        database_limit = _positive_bound(max_database_bytes, "max_database_bytes", maximum=MAX_DATABASE_BYTES)
        if database_limit < 32 * 1024:
            raise ValueError("max_database_bytes must be at least 32768")
        state_json = _canonical(initial_state)
        if len(state_json.encode("utf-8")) > byte_limit:
            raise JournalError("initial state exceeds max_event_bytes")
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(str(destination), timeout=5.0, isolation_level=None)
            _configure(connection)
            _set_database_bound(connection, database_limit)
            connection.executescript(_SCHEMA)
            connection.execute("BEGIN IMMEDIATE")
            state_hash = _hash(state_json)
            identity_json = _canonical(identity.__dict__)
            genesis_hash = _hash(
                _canonical(["SIM_STATE_GENESIS_V1", identity_json, state_hash, initial_clock_ms])
            )
            metadata = {
                "schema_version": SCHEMA_VERSION,
                "identity": identity_json,
                "max_event_rows": row_limit,
                "max_event_bytes": byte_limit,
                "max_database_bytes": database_limit,
                "initial_state_json": state_json,
                "initial_state_hash": state_hash,
                "initial_clock_ms": initial_clock_ms,
                "genesis_hash": genesis_hash,
            }
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES(?, ?)",
                [(key, str(value)) for key, value in metadata.items()],
            )
            connection.execute(
                "INSERT INTO head(singleton, version, state_json, state_hash, head_hash, last_clock_ms) "
                "VALUES(1, 0, ?, ?, ?, ?)",
                (state_json, state_hash, genesis_hash, initial_clock_ms),
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
            _verify_database_file_size(destination, database_limit, connection)
            return cls(
                connection,
                identity,
                max_event_rows=row_limit,
                max_event_bytes=byte_limit,
                max_database_bytes=database_limit,
            )
        except BaseException:
            if connection is not None:
                try:
                    connection.rollback()
                    connection.close()
                except sqlite3.Error:
                    pass
            raise

    @classmethod
    def open(
        cls,
        path: str | Path,
        *,
        identity: JournalIdentity,
        max_event_rows: int,
        max_event_bytes: int = MAX_EVENT_BYTES,
        max_database_bytes: int = DEFAULT_MAX_DATABASE_BYTES,
    ) -> SimStateJournal:
        source = _safe_path(path, must_exist=True)
        if not isinstance(identity, JournalIdentity):
            raise TypeError("identity must be a JournalIdentity")
        row_limit = _positive_bound(max_event_rows, "max_event_rows")
        if row_limit > MAX_EVENT_ROWS:
            raise ValueError(f"max_event_rows must be <= {MAX_EVENT_ROWS}")
        byte_limit = _positive_bound(max_event_bytes, "max_event_bytes", maximum=MAX_EVENT_BYTES)
        database_limit = _positive_bound(max_database_bytes, "max_database_bytes", maximum=MAX_DATABASE_BYTES)
        if database_limit < 32 * 1024:
            raise ValueError("max_database_bytes must be at least 32768")
        _verify_database_file_size(source, database_limit)
        pinned_file_identity = _file_identity(source)
        connection = sqlite3.connect(_existing_uri(source, readonly=True), uri=True, timeout=5.0)
        try:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            _validate_schema(connection)
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            if journal_mode != "delete":
                raise JournalError("journal must use the pinned DELETE journal mode")
            if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise JournalError("unknown SQLite schema version")
            journal = cls(
                connection,
                identity,
                max_event_rows=row_limit,
                max_event_bytes=byte_limit,
                max_database_bytes=database_limit,
            )
            journal._validate_configuration()
            journal._validate_chain()
            _verify_database_file_size(source, database_limit, connection)
            connection.commit()
            connection.close()
        except BaseException:
            connection.close()
            raise
        _verify_database_file_size(source, database_limit)
        if _file_identity(source) != pinned_file_identity:
            raise JournalError("journal file identity changed during read-only validation")
        connection = sqlite3.connect(_existing_uri(source), uri=True, timeout=5.0, isolation_level=None)
        try:
            if _file_identity(source) != pinned_file_identity:
                raise JournalError("journal file identity changed before writable open")
            _configure(connection)
            _set_database_bound(connection, database_limit)
            _validate_schema(connection)
            journal = cls(
                connection,
                identity,
                max_event_rows=row_limit,
                max_event_bytes=byte_limit,
                max_database_bytes=database_limit,
            )
            journal._validate_configuration()
            journal._validate_chain()
            _verify_database_file_size(source, database_limit, connection)
            return journal
        except BaseException:
            connection.close()
            raise

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SimStateJournal:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def snapshot(self) -> JournalSnapshot:
        self._validate_chain()
        return _snapshot_from_row(
            self._connection.execute(
                "SELECT version, state_json, state_hash, head_hash, last_clock_ms FROM head WHERE singleton=1"
            ).fetchone()
        )

    def lookup(self, *, event_id: str, payload: dict[str, Any]) -> AppendResult | None:
        """Read existing event outcome/head before a caller runs its reducer.

        A missing event returns None. A matching duplicate returns its original
        outcome and the latest persisted state projection. Callers must still
        use optimistic `append` after reducing a new event to close races.
        """
        _identifier(event_id, "event_id")
        _require_state(payload, name="payload")
        payload_hash = _hash(_canonical(payload))
        connection = self._connection
        try:
            connection.execute("BEGIN")
            self._validate_chain()
            duplicate = connection.execute(
                "SELECT payload_hash, outcome_json FROM events WHERE event_id=?", (event_id,)
            ).fetchone()
            if duplicate is None:
                connection.commit()
                return None
            if duplicate[0] != payload_hash:
                raise EventConflict("event ID reused with conflicting payload")
            result = AppendResult(self._snapshot_without_validation(), json.loads(duplicate[1]), True)
            connection.commit()
            return result
        except BaseException as error:
            if connection.in_transaction:
                connection.rollback()
            if isinstance(error, sqlite3.DatabaseError) and "full" in str(error).casefold():
                raise JournalFull("caller-pinned SQLite database byte bound reached") from error
            raise

    def append(
        self,
        *,
        event_id: str,
        payload: dict[str, Any],
        outcome: Any,
        state: dict[str, Any],
        expected_version: int,
        expected_state_hash: str,
        at_ms: int,
    ) -> AppendResult:
        _identifier(event_id, "event_id")
        _require_state(payload, name="payload")
        _require_state(state, name="state")
        _clock(at_ms)
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError("expected_version must be a nonnegative integer")
        if type(expected_state_hash) is not str or len(expected_state_hash) != 64:
            raise ValueError("expected_state_hash must be a SHA-256 hex digest")
        try:
            int(expected_state_hash, 16)
        except ValueError as error:
            raise ValueError("expected_state_hash must be a SHA-256 hex digest") from error

        payload_json = _canonical(payload)
        payload_hash = _hash(payload_json)
        outcome_json = _canonical(outcome)
        state_json = _canonical(state)
        state_hash = _hash(state_json)
        event_bytes = len(event_id.encode("utf-8")) + len(payload_json.encode("utf-8"))
        event_bytes += len(outcome_json.encode("utf-8")) + len(state_json.encode("utf-8"))
        if event_bytes > self.max_event_bytes:
            raise JournalError("canonical event plus complete state exceeds max_event_bytes")

        connection = self._connection
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._validate_chain()
            duplicate = connection.execute(
                "SELECT payload_hash, outcome_json FROM events WHERE event_id=?", (event_id,)
            ).fetchone()
            if duplicate is not None:
                connection.commit()
                if duplicate[0] != payload_hash:
                    raise EventConflict("event ID reused with conflicting payload")
                return AppendResult(self._snapshot_without_validation(), json.loads(duplicate[1]), True)

            head = connection.execute(
                "SELECT version, state_json, state_hash, head_hash, last_clock_ms FROM head WHERE singleton=1"
            ).fetchone()
            current = _snapshot_from_row(head)
            if current.version != expected_version or current.state_hash != expected_state_hash:
                raise OptimisticConflict("prior version/state hash no longer matches current journal head")
            if at_ms < current.last_clock_ms:
                raise JournalError("event clock regressed")
            count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            if count >= self.max_event_rows:
                raise JournalFull("configured append-only event row limit reached; no rows are evicted")

            version = current.version + 1
            event_hash = _digest_event(
                previous_hash=current.head_hash,
                version=version,
                event_id=event_id,
                payload_hash=payload_hash,
                outcome_hash=_hash(outcome_json),
                state_hash=state_hash,
                clock_ms=at_ms,
            )
            connection.execute(
                "INSERT INTO events(version, event_id, payload_json, payload_hash, outcome_json, state_json, "
                "state_hash, previous_hash, event_hash, clock_ms) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    version,
                    event_id,
                    payload_json,
                    payload_hash,
                    outcome_json,
                    state_json,
                    state_hash,
                    current.head_hash,
                    event_hash,
                    at_ms,
                ),
            )
            connection.execute(
                "UPDATE head SET version=?, state_json=?, state_hash=?, head_hash=?, "
                "last_clock_ms=? WHERE singleton=1",
                (version, state_json, state_hash, event_hash, at_ms),
            )
            _verify_database_pages(connection, self.max_database_bytes)
            connection.commit()
            _verify_database_pages(connection, self.max_database_bytes)
            return AppendResult(
                JournalSnapshot(version, json.loads(state_json), state_hash, event_hash, at_ms),
                json.loads(outcome_json),
                False,
            )
        except BaseException as error:
            if connection.in_transaction:
                connection.rollback()
            if isinstance(error, sqlite3.DatabaseError) and "full" in str(error).casefold():
                raise JournalFull("caller-pinned SQLite database byte bound reached") from error
            raise

    def _snapshot_without_validation(self) -> JournalSnapshot:
        row = self._connection.execute(
            "SELECT version, state_json, state_hash, head_hash, last_clock_ms FROM head WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise JournalError("current head row is missing")
        return _snapshot_from_row(row)

    def _validate_configuration(self) -> None:
        oversized = self._connection.execute(
            "SELECT 1 FROM metadata WHERE length(CAST(value AS BLOB)) > ? LIMIT 1",
            (MAX_METADATA_VALUE_BYTES,),
        ).fetchone()
        if oversized is not None:
            raise JournalError("journal metadata value exceeds its byte bound")
        rows = self._connection.execute("SELECT key, value FROM metadata").fetchmany(10)
        if len(rows) != 9:
            raise JournalError("journal metadata missing or contains unknown keys")
        metadata = dict(rows)
        expected = {
            "schema_version": str(SCHEMA_VERSION),
            "identity": _canonical(self.identity.__dict__),
            "max_event_rows": str(self.max_event_rows),
            "max_event_bytes": str(self.max_event_bytes),
            "max_database_bytes": str(self.max_database_bytes),
        }
        for key, value in expected.items():
            if metadata.get(key) != value:
                if key == "identity":
                    raise IdentityMismatch("caller-pinned journal identity does not match stored identity")
                raise JournalError(f"stored journal configuration mismatch: {key}")
        if any(
            type(key) is not str
            or type(value) is not str
            or len(key) > 64
            or len(value.encode("utf-8")) > MAX_METADATA_VALUE_BYTES
            for key, value in rows
        ):
            raise JournalError("journal metadata contains invalid or oversized values")

    def _validate_chain(self) -> None:
        _validate_schema(self._connection)
        self._validate_configuration()
        _verify_database_pages(self._connection, self.max_database_bytes)
        try:
            integrity = self._connection.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.Error as error:
            raise JournalError("SQLite integrity check failed") from error
        if integrity != "ok":
            raise JournalError(f"SQLite integrity check failed: {integrity}")
        metadata = dict(self._connection.execute("SELECT key, value FROM metadata").fetchall())
        initial_json = metadata["initial_state_json"]
        if len(initial_json.encode("utf-8")) > self.max_event_bytes:
            raise JournalError("stored initial state exceeds configured byte limit")
        _verify_object_json(initial_json, "initial state")
        if _hash(initial_json) != metadata["initial_state_hash"]:
            raise JournalError("initial state hash mismatch")
        initial_clock = int(metadata["initial_clock_ms"])
        if initial_clock < 0:
            raise JournalError("invalid initial clock")
        expected_previous = metadata["genesis_hash"]
        expected_genesis = _hash(
            _canonical(
                ["SIM_STATE_GENESIS_V1", metadata["identity"], metadata["initial_state_hash"], initial_clock]
            )
        )
        if expected_previous != expected_genesis:
            raise JournalError("genesis hash mismatch")
        expected_state_json = initial_json
        expected_state_hash = metadata["initial_state_hash"]
        expected_clock = initial_clock
        count = self._connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if type(count) is not int or count > self.max_event_rows:
            raise JournalError("stored event count exceeds configured row limit")
        total_bytes = self._connection.execute(
            "SELECT COALESCE(SUM(length(CAST(event_id AS BLOB)) + length(CAST(payload_json AS BLOB)) + "
            "length(CAST(outcome_json AS BLOB)) + length(CAST(state_json AS BLOB))), 0) FROM events"
        ).fetchone()[0]
        if type(total_bytes) is not int or total_bytes > count * self.max_event_bytes:
            raise JournalError("stored event bytes exceed configured bounded total")
        events = self._connection.execute(
            "SELECT version, event_id, payload_json, payload_hash, outcome_json, state_json, state_hash, "
            "previous_hash, event_hash, clock_ms FROM events ORDER BY version"
        )
        for expected_version, row in enumerate(events, start=1):
            (
                version,
                event_id,
                payload_json,
                payload_hash,
                outcome_json,
                state_json,
                state_hash,
                prior,
                digest,
                clock,
            ) = row
            _identifier(event_id, "stored event_id")
            if version != expected_version or prior != expected_previous:
                raise JournalError("event sequence or previous hash discontinuity")
            if any(type(value) is not str for value in (payload_json, outcome_json, state_json)):
                raise JournalError("stored event JSON fields must be text")
            event_size = (
                len(event_id.encode("utf-8"))
                + len(payload_json.encode("utf-8"))
                + len(outcome_json.encode("utf-8"))
                + len(state_json.encode("utf-8"))
            )
            if event_size > self.max_event_bytes:
                raise JournalError("stored event exceeds configured byte limit")
            _verify_object_json(payload_json, "event payload")
            _verify_canonical(outcome_json, "event outcome")
            _verify_object_json(state_json, "event state")
            if _hash(payload_json) != payload_hash or _hash(state_json) != state_hash:
                raise JournalError("event payload/state hash mismatch")
            if type(clock) is not int or clock < expected_clock:
                raise JournalError("event clock regressed or is malformed")
            expected_digest = _digest_event(
                previous_hash=prior,
                version=version,
                event_id=event_id,
                payload_hash=payload_hash,
                outcome_hash=_hash(outcome_json),
                state_hash=state_hash,
                clock_ms=clock,
            )
            if digest != expected_digest:
                raise JournalError("event hash-chain digest mismatch")
            expected_previous = digest
            expected_state_json = state_json
            expected_state_hash = state_hash
            expected_clock = clock

        head = self._connection.execute(
            "SELECT version, state_json, state_hash, head_hash, last_clock_ms FROM head WHERE singleton=1"
        ).fetchone()
        if head is None:
            raise JournalError("current head row is missing")
        version, state_json, state_hash, head_hash, last_clock = head
        if (
            version != count
            or state_json != expected_state_json
            or state_hash != expected_state_hash
            or head_hash != expected_previous
            or last_clock != expected_clock
            or _hash(state_json) != state_hash
        ):
            raise JournalError("current projection/head does not match the verified event chain")


def _positive_bound(value: object, name: str, *, maximum: int | None = None) -> int:
    if type(value) is not int or value <= 0 or (maximum is not None and value > maximum):
        suffix = f" and <= {maximum}" if maximum is not None else ""
        raise ValueError(f"{name} must be a positive integer{suffix}")
    return value


def _require_state(value: object, *, name: str = "state") -> None:
    if type(value) is not dict:
        raise ValueError(f"{name} must be a plain dict")
    _canonical(value)


def _verify_canonical(document: str, name: str) -> None:
    try:
        value = json.loads(document)
        normalized = _canonical(value)
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise JournalError(f"stored {name} is invalid JSON") from error
    if normalized != document:
        raise JournalError(f"stored {name} is not canonical JSON")


def _verify_object_json(document: str, name: str) -> None:
    _verify_canonical(document, name)
    if type(json.loads(document)) is not dict:
        raise JournalError(f"stored {name} must be a JSON object")


def _safe_path(path: str | Path, *, must_exist: bool) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path)))
    for parent in reversed(absolute.parents):
        info = parent.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
            or not stat.S_ISDIR(info.st_mode)
        ):
            raise JournalError("journal path cannot traverse symlink/reparse or non-directory parent")
    try:
        info = absolute.lstat()
    except FileNotFoundError:
        if must_exist:
            raise
        return absolute
    if (
        stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & 0x400
        or not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
    ):
        raise JournalError("journal file must be an unaliased regular file, not a path alias")
    if absolute.resolve(strict=True) != absolute:
        raise JournalError("journal path resolution differs from caller-pinned absolute path")
    return absolute


def _file_identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    if (
        stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & 0x400
        or not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
    ):
        raise JournalError("journal file identity is aliased")
    return info.st_dev, info.st_ino


def _verify_database_pages(connection: sqlite3.Connection, maximum: int) -> None:
    page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    page_count = connection.execute("PRAGMA page_count").fetchone()[0]
    if (
        type(page_size) is not int
        or type(page_count) is not int
        or page_size <= 0
        or page_count < 0
        or page_size * page_count > maximum
    ):
        raise JournalFull("SQLite database page bound exceeded")


def _verify_database_file_size(
    path: Path,
    maximum: int,
    connection: sqlite3.Connection | None = None,
) -> None:
    source = _safe_path(path, must_exist=True)
    if source.stat().st_size > maximum:
        raise JournalFull("SQLite database file exceeds caller-pinned byte bound")
    if connection is not None:
        _verify_database_pages(connection, maximum)


def _set_database_bound(connection: sqlite3.Connection, maximum: int) -> None:
    page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    page_limit = maximum // page_size
    if page_limit <= 0:
        raise ValueError("database byte bound is below one SQLite page")
    effective = connection.execute(f"PRAGMA max_page_count = {page_limit}").fetchone()[0]
    if type(effective) is not int or effective > page_limit:
        raise JournalFull("SQLite cannot honor caller-pinned max_page_count")
    _verify_database_pages(connection, maximum)


def _normalize_sql(value: str | None) -> str | None:
    return None if value is None else " ".join(value.split()).casefold()


def _validate_schema(connection: sqlite3.Connection) -> None:
    expected = {
        ("table", "metadata", "metadata", "create table metadata(key text primary key, value text not null)"),
        (
            "index",
            "sqlite_autoindex_metadata_1",
            "metadata",
            None,
        ),
        (
            "table",
            "events",
            "events",
            "create table events( version integer primary key, event_id text not null unique, "
            "payload_json text not null, payload_hash text not null, outcome_json text not null, "
            "state_json text not null, state_hash text not null, previous_hash text not null, "
            "event_hash text not null, clock_ms integer not null )",
        ),
        ("index", "sqlite_autoindex_events_1", "events", None),
        (
            "table",
            "head",
            "head",
            "create table head( singleton integer primary key check(singleton=1), version integer not null, "
            "state_json text not null, state_hash text not null, head_hash text not null, "
            "last_clock_ms integer not null )",
        ),
    }
    rows = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' OR type='index' ORDER BY type, name"
    ).fetchmany(len(expected) + 1)
    if len(rows) != len(expected):
        raise JournalError("SQLite schema objects differ from the exact journal whitelist")
    actual = {(kind, name, table, _normalize_sql(sql)) for kind, name, table, sql in rows}
    if actual != expected:
        raise JournalError("SQLite schema objects differ from the exact journal whitelist")


def _configure(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute("PRAGMA journal_mode = DELETE")
    connection.execute("PRAGMA busy_timeout = 5000")


def _existing_uri(path: Path, *, readonly: bool = False) -> str:
    mode = "ro" if readonly else "rw"
    return f"file:{quote(path.as_posix(), safe='/:')}?mode={mode}"


_SCHEMA = """
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE events(
  version INTEGER PRIMARY KEY,
  event_id TEXT NOT NULL UNIQUE,
  payload_json TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  outcome_json TEXT NOT NULL,
  state_json TEXT NOT NULL,
  state_hash TEXT NOT NULL,
  previous_hash TEXT NOT NULL,
  event_hash TEXT NOT NULL,
  clock_ms INTEGER NOT NULL
);
CREATE TABLE head(
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  version INTEGER NOT NULL,
  state_json TEXT NOT NULL,
  state_hash TEXT NOT NULL,
  head_hash TEXT NOT NULL,
  last_clock_ms INTEGER NOT NULL
);
"""
