"""Create-only atomic native-audit/core journal for isolated V3 research.

Every financial fold executes inside BEGIN IMMEDIATE with an explicit native
event context. Native audit rows, recursive state deltas, source cursor and
both commitment heads commit together. No source admission, migration, latest
head adoption, network, or trading authority. Audit validates storage replay,
not independent correctness of an arbitrary caller-supplied financial fold.
An external SQLite commit invalidates the audited-history cache via data_version:
full audit precedes any subsequent duplicate acknowledgement or financial fold.
This is local SQLite consistency, not authentication against hostile raw-file IO.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from decimal import Context, Decimal, localcontext
from functools import wraps

from .account_event_context_v3 import (
    NativeEventContext,
    canonical_native_event,
    current_native_event_context,
    decode_native_event,
)
from .sim_account_core_codec_v3 import AccountLedgerRefV3, decode_account_core, encode_account_core
from .sim_delta_journal_v3 import SimDeltaJournalV3, _count_nodes, _load, _sha, apply_delta, make_delta
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

SCHEMA_ID = "kairos.research.sim-financial-journal.v3"
SCHEMA_VERSION = 31
MAX_ROWS = 2**63 - 1
MAX_DATABASE_BYTES = 1024**4
MAX_STATE_BYTES = 64 * 1024 * 1024
MAX_EVENT_BYTES = 32 * 1024 * 1024
DEFAULT_LIMITS = {
    "max_event_rows": 1_000_000,
    "max_native_event_rows": 1_000_000,
    "max_event_bytes": 2 * 1024 * 1024,
    "max_state_bytes": 32 * 1024 * 1024,
    "max_database_bytes": 512 * 1024 * 1024,
}
_DDL = {
    "metadata": "CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "events": (
        "CREATE TABLE events(version INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, "
        "payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, outcome_json TEXT NOT NULL, "
        "outcome_hash TEXT NOT NULL, delta_json TEXT NOT NULL, delta_hash TEXT NOT NULL, "
        "state_hash TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL, "
        "clock_ms INTEGER NOT NULL, source_cursor INTEGER NOT NULL, native_count INTEGER NOT NULL, "
        "native_head TEXT NOT NULL)"
    ),
    "native_events": (
        "CREATE TABLE native_events(ordinal INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, "
        "outer_version INTEGER NOT NULL, within_outer INTEGER NOT NULL, event_json TEXT NOT NULL, "
        "content_hash TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL)"
    ),
    "projection": (
        "CREATE TABLE projection(path TEXT PRIMARY KEY, kind TEXT NOT NULL, value_json TEXT NOT NULL)"
    ),
    "head": (
        "CREATE TABLE head(singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL, "
        "state_hash TEXT NOT NULL, head_hash TEXT NOT NULL, last_clock_ms INTEGER NOT NULL, "
        "source_cursor INTEGER NOT NULL, native_count INTEGER NOT NULL, native_head TEXT NOT NULL, "
        "state_bytes INTEGER NOT NULL, node_count INTEGER NOT NULL)"
    ),
}


def native_genesis(identity: JournalIdentity, *, owner_id: str, account_id: str) -> str:
    if type(identity) is not JournalIdentity:
        raise TypeError("exact JournalIdentity required")
    JournalIdentity(**identity.__dict__)
    _identifier(owner_id, "owner_id")
    _identifier(account_id, "account_id")
    return _hash(_canonical([SCHEMA_ID, "NATIVE_GENESIS", identity.__dict__, owner_id, account_id]))


def initial_ledger_reference(identity: JournalIdentity, *, owner_id: str, account_id: str):
    return AccountLedgerRefV3(
        owner_id, account_id, 0, native_genesis(identity, owner_id=owner_id, account_id=account_id)
    )


def _integer(value, name):
    if type(value) is not int or not 0 <= value <= MAX_ROWS:
        raise JournalError(f"exact bounded nonnegative {name} required")
    return value


def _native_hash(row):
    return _hash(
        _canonical(
            [
                SCHEMA_ID,
                "NATIVE",
                *[
                    row[key]
                    for key in (
                        "previous_hash",
                        "ordinal",
                        "event_id",
                        "outer_version",
                        "within_outer",
                        "content_hash",
                    )
                ],
            ]
        )
    )


def _outer_hash(row):
    return _hash(
        _canonical(
            [
                SCHEMA_ID,
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
                        "state_hash",
                        "clock_ms",
                        "source_cursor",
                        "native_count",
                        "native_head",
                    )
                ],
            ]
        )
    )


def _serialized(function):
    @wraps(function)
    def guarded(self, *args, **kwargs):
        with self._operation_lock:
            return function(self, *args, **kwargs)

    return guarded


@dataclass(frozen=True)
class FinancialCheckpointV3:
    identity_sha256: str
    owner_id: str
    account_id: str
    version: int
    state_hash: str
    head_hash: str
    last_clock_ms: int
    source_cursor: int
    native_count: int
    native_head: str

    def __post_init__(self):
        for key in ("identity_sha256", "state_hash", "head_hash", "native_head"):
            _sha(getattr(self, key))
        _identifier(self.owner_id, "owner_id")
        _identifier(self.account_id, "account_id")
        for key in ("version", "last_clock_ms", "source_cursor", "native_count"):
            _integer(getattr(self, key), key)


class SimFinancialJournalV3:
    """Separate schema and exact external checkpoint; never adopts an old DB."""

    _insert_tree = SimDeltaJournalV3._insert_tree
    _delete_tree = SimDeltaJournalV3._delete_tree
    _update_projection = SimDeltaJournalV3._update_projection
    _read_projection = SimDeltaJournalV3._read_projection

    def __init__(self, connection, path, identity, *, owner_id, account_id, allowed_quantity_steps, **limits):
        if type(identity) is not JournalIdentity:
            raise TypeError("exact JournalIdentity required")
        JournalIdentity(**identity.__dict__)
        _identifier(owner_id, "owner_id")
        _identifier(account_id, "account_id")
        if (
            type(allowed_quantity_steps) is not tuple
            or not 1 <= len(allowed_quantity_steps) <= 5
            or any(type(x) is not Decimal or not x.is_finite() or x <= 0 for x in allowed_quantity_steps)
            or tuple(sorted(set(allowed_quantity_steps))) != allowed_quantity_steps
        ):
            raise JournalError("exact sealed positive quantity-step roster required")
        if set(limits) != set(DEFAULT_LIMITS):
            raise JournalError("exact explicit financial journal bounds required")
        for key, maximum in (
            ("max_event_rows", MAX_ROWS),
            ("max_native_event_rows", MAX_ROWS),
            ("max_event_bytes", MAX_EVENT_BYTES),
            ("max_state_bytes", MAX_STATE_BYTES),
            ("max_database_bytes", MAX_DATABASE_BYTES),
        ):
            setattr(self, key, _positive_bound(limits[key], key, maximum=maximum))
        if self.max_database_bytes < 32 * 1024:
            raise JournalError("database byte bound must be at least 32768")
        self._connection, self.path, self.identity = connection, path, identity
        self.owner_id, self.account_id = owner_id, account_id
        self.allowed_quantity_steps = allowed_quantity_steps
        self._file_identity = _file_identity(path)
        self._operation_lock = threading.RLock()
        self._retained_checkpoint = None
        self._fold_context = None
        self._fold_base_ref = None
        self._fold_version = None
        self._fold_native_rows = []
        self._observed_data_version = None

    def _configuration(self):
        return {
            "schema": SCHEMA_ID,
            "identity": _canonical(self.identity.__dict__),
            "owner_id": self.owner_id,
            "account_id": self.account_id,
            "allowed_quantity_steps": _canonical([str(x) for x in self.allowed_quantity_steps]),
            **{key: str(getattr(self, key)) for key in DEFAULT_LIMITS},
        }

    @classmethod
    def create(
        cls,
        path,
        *,
        identity,
        owner_id,
        account_id,
        initial_state,
        allowed_quantity_steps,
        initial_clock_ms=0,
        **limits,
    ):
        destination = _safe_path(path, must_exist=False)
        _clock(initial_clock_ms)
        limits = {**DEFAULT_LIMITS, **limits}
        # Validate configuration before reserving the create-only destination.
        validator = object.__new__(cls)
        validator.identity, validator.owner_id, validator.account_id = identity, owner_id, account_id
        if set(limits) != set(DEFAULT_LIMITS):
            raise JournalError("exact financial journal bounds required")
        for key, maximum in (
            ("max_event_rows", MAX_ROWS),
            ("max_native_event_rows", MAX_ROWS),
            ("max_event_bytes", MAX_EVENT_BYTES),
            ("max_state_bytes", MAX_STATE_BYTES),
            ("max_database_bytes", MAX_DATABASE_BYTES),
        ):
            setattr(validator, key, _positive_bound(limits[key], key, maximum=maximum))
        if validator.max_database_bytes < 32 * 1024:
            raise JournalError("database byte bound must be at least 32768")
        if type(initial_state) is not dict:
            raise JournalError("plain initial state required")
        state = _load(_canonical(initial_state))
        account, ref = decode_account_core(state.get("account"))
        expected = initial_ledger_reference(identity, owner_id=owner_id, account_id=account_id)
        if ref != expected:
            raise JournalError("initial ledger must be exact empty owned genesis")
        state["clock"] = initial_clock_ms
        state.setdefault("last_outcome", None)
        _integer(state.get("cursor"), "source cursor")
        NativeEventContext(
            owner_id=owner_id,
            account_id=account_id,
            account=account,
            lookup_exact=lambda _: None,
            allowed_quantity_steps=allowed_quantity_steps,
        )
        validator._state_json(state)
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
        connection = sqlite3.connect(
            str(destination), timeout=0, isolation_level=None, check_same_thread=False
        )
        connection.row_factory = sqlite3.Row
        try:
            journal = cls(
                connection,
                destination,
                identity,
                owner_id=owner_id,
                account_id=account_id,
                allowed_quantity_steps=allowed_quantity_steps,
                **limits,
            )
            NativeEventContext(
                owner_id=owner_id,
                account_id=account_id,
                account=account,
                lookup_exact=lambda _: None,
                allowed_quantity_steps=allowed_quantity_steps,
            )
            encoded = journal._state_json(state)
            _configure(connection)
            connection.execute("PRAGMA busy_timeout=0")
            _set_database_bound(connection, journal.max_database_bytes)
            connection.execute("BEGIN IMMEDIATE")
            for ddl in _DDL.values():
                connection.execute(ddl)
            state_hash = _hash(encoded)
            genesis = _hash(_canonical([SCHEMA_ID, journal._configuration(), state_hash, initial_clock_ms]))
            metadata = {
                **journal._configuration(),
                "initial_state_json": encoded,
                "initial_state_hash": state_hash,
                "initial_clock_ms": str(initial_clock_ms),
                "genesis_hash": genesis,
            }
            connection.executemany("INSERT INTO metadata VALUES(?,?)", metadata.items())
            journal._insert_tree([], state)
            connection.execute(
                "INSERT INTO head VALUES(1,0,?,?,?,?,?,?,?,?)",
                (
                    state_hash,
                    genesis,
                    initial_clock_ms,
                    state["cursor"],
                    0,
                    ref.head_sha256,
                    len(encoded.encode("utf-8")),
                    _count_nodes(state),
                ),
            )
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            snapshot = journal._audit()
            _verify_database_pages(connection, journal.max_database_bytes)
            observed_version = journal._data_version()
            connection.commit()
            journal._observed_data_version = observed_version
            journal._retained_checkpoint = journal._checkpoint(snapshot)
            return journal
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
            raise  # Preserve partial create; never adopt, remove or migrate it.

    @classmethod
    def open(
        cls, path, *, identity, owner_id, account_id, allowed_quantity_steps, expected_checkpoint, **limits
    ):
        if type(expected_checkpoint) is not FinancialCheckpointV3:
            raise TypeError("independent exact FinancialCheckpointV3 required")
        FinancialCheckpointV3(**expected_checkpoint.__dict__)
        source = _safe_path(path, must_exist=True)
        limits = {**DEFAULT_LIMITS, **limits}
        connection = sqlite3.connect(_existing_uri(source, readonly=True), uri=True, timeout=0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            journal = cls(
                connection,
                source,
                identity,
                owner_id=owner_id,
                account_id=account_id,
                allowed_quantity_steps=allowed_quantity_steps,
                **limits,
            )
            snapshot = journal._audit()
            if journal._checkpoint(snapshot) != expected_checkpoint:
                raise JournalError("independent exact financial checkpoint differs; no adoption")
            physical = journal._file_identity
            connection.commit()
        finally:
            connection.close()
        if _file_identity(source) != physical:
            raise JournalError("file identity changed after read-only financial audit")
        connection = sqlite3.connect(
            _existing_uri(source), uri=True, timeout=0, isolation_level=None, check_same_thread=False
        )
        connection.row_factory = sqlite3.Row
        try:
            journal = cls(
                connection,
                source,
                identity,
                owner_id=owner_id,
                account_id=account_id,
                allowed_quantity_steps=allowed_quantity_steps,
                **limits,
            )
            if journal._file_identity != physical:
                raise JournalError("file identity changed before writable open")
            _configure(connection)
            connection.execute("PRAGMA busy_timeout=0")
            _set_database_bound(connection, journal.max_database_bytes)
            connection.execute("BEGIN IMMEDIATE")
            snapshot = journal._audit()
            if journal._checkpoint(snapshot) != expected_checkpoint:
                raise JournalError("financial checkpoint changed before writable open")
            observed_version = journal._data_version()
            connection.commit()
            journal._observed_data_version = observed_version
            journal._retained_checkpoint = expected_checkpoint
            return journal
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
            raise

    def _check_storage(self):
        if _file_identity(self.path) != self._file_identity:
            raise JournalError("financial journal file identity changed")
        _verify_database_file_size(self.path, self.max_database_bytes, self._connection)
        expected = {name: ("table", _normalize_sql(ddl)) for name, ddl in _DDL.items()}
        expected.update(
            {
                f"sqlite_autoindex_{name}_1": ("index", None)
                for name in ("metadata", "events", "native_events", "projection")
            }
        )
        actual = {
            r["name"]: (r["type"], _normalize_sql(r["sql"]))
            for r in self._connection.execute("SELECT name,type,sql FROM sqlite_master")
        }
        if (
            actual != expected
            or self._connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
        ):
            raise JournalError("exact create-only financial schema required; no migration")
        if self._connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
            raise JournalError("pinned DELETE journal mode required")
        metadata = dict(self._connection.execute("SELECT key,value FROM metadata"))
        if set(metadata) != set(self._configuration()) | {
            "initial_state_json",
            "initial_state_hash",
            "initial_clock_ms",
            "genesis_hash",
        }:
            raise JournalError("exact financial metadata fields required")
        for key, value in self._configuration().items():
            if metadata[key] != value:
                if key in {"identity", "owner_id", "account_id"}:
                    raise IdentityMismatch("caller-pinned financial owner/identity differs")
                raise JournalError(f"caller-pinned financial configuration differs: {key}")
        if any(
            type(value) is not str
            or len(value.encode("utf-8")) > (self.max_state_bytes if key == "initial_state_json" else 8192)
            for key, value in metadata.items()
        ):
            raise JournalError("financial metadata byte bound exceeded")
        return metadata

    def _state_json(self, state):
        if type(state) is not dict:
            raise JournalError("plain financial state required")
        _integer(state.get("cursor"), "source cursor")
        _clock(state.get("clock"))
        account, ref = decode_account_core(state.get("account"))
        if (ref.owner_id, ref.account_id) != (self.owner_id, self.account_id):
            raise IdentityMismatch("core ledger owner/account differs")
        encoded = _canonical(state)
        if len(encoded.encode("utf-8")) > self.max_state_bytes:
            raise JournalFull("financial current state byte bound exceeded")
        _count_nodes(state)
        return encoded

    def _validate_native(self, row):
        for key in ("ordinal", "outer_version", "within_outer"):
            if _integer(row[key], key) == 0:
                raise JournalError("positive native sequence fields required")
        for key in ("content_hash", "previous_hash", "event_hash"):
            _sha(row[key])
        try:
            event = decode_native_event(row["event_json"])
        except ValueError as error:
            raise JournalError("native event canonical decoding conflict") from error
        if (
            event.event_id != row["event_id"]
            or _hash(row["event_json"]) != row["content_hash"]
            or _native_hash(row) != row["event_hash"]
        ):
            raise JournalError("native event content/commitment conflict")
        return event

    def _validate_outer(self, row):
        _identifier(row["event_id"], "stored event_id")
        if _integer(row["version"], "version") == 0:
            raise JournalError("positive outer version required")
        for key in ("clock_ms", "source_cursor", "native_count"):
            _integer(row[key], key)
        for key in (
            "payload_hash",
            "outcome_hash",
            "delta_hash",
            "state_hash",
            "previous_hash",
            "event_hash",
            "native_head",
        ):
            _sha(row[key])
        texts = [row[key] for key in ("payload_json", "outcome_json", "delta_json")]
        if (
            len(row["event_id"].encode("utf-8")) + sum(len(x.encode("utf-8")) for x in texts)
            > self.max_event_bytes
        ):
            raise JournalFull("outer event byte bound exceeded")
        payload, outcome, delta = (_load(x) for x in texts)
        if type(payload) is not dict:
            raise JournalError("outer payload must be a map")
        if (
            any(
                _hash(row[text]) != row[sha]
                for text, sha in (
                    ("payload_json", "payload_hash"),
                    ("outcome_json", "outcome_hash"),
                    ("delta_json", "delta_hash"),
                )
            )
            or _outer_hash(row) != row["event_hash"]
        ):
            raise JournalError("outer content/commitment conflict")
        return payload, outcome, delta

    def _current(self):
        metadata = self._check_storage()
        rows = self._connection.execute("SELECT * FROM head").fetchmany(2)
        if len(rows) != 1 or rows[0]["singleton"] != 1:
            raise JournalError("exact single financial head required")
        head = rows[0]
        for key in ("version", "source_cursor", "native_count", "last_clock_ms"):
            _integer(head[key], key)
        if head["version"] > self.max_event_rows or head["native_count"] > self.max_native_event_rows:
            raise JournalFull("financial row bounds exceeded")
        state, nodes = self._read_projection()
        encoded = self._state_json(state)
        account, ref = decode_account_core(state["account"])
        initial = _load(metadata["initial_state_json"])
        initial_account, _ = decode_account_core(initial["account"])
        NativeEventContext(
            owner_id=self.owner_id,
            account_id=self.account_id,
            account=initial_account,
            lookup_exact=lambda _: None,
            allowed_quantity_steps=self.allowed_quantity_steps,
        ).validate_account(account)
        if (
            nodes != head["node_count"]
            or len(encoded.encode("utf-8")) != head["state_bytes"]
            or _hash(encoded) != head["state_hash"]
            or state["clock"] != head["last_clock_ms"]
            or state["cursor"] != head["source_cursor"]
            or (ref.event_count, ref.head_sha256) != (head["native_count"], head["native_head"])
        ):
            raise JournalError("financial projection/head/native reference conflict")
        for table, key, count in (
            ("events", "version", head["version"]),
            ("native_events", "ordinal", head["native_count"]),
        ):
            tail = self._connection.execute(f"SELECT * FROM {table} ORDER BY {key} DESC LIMIT 1").fetchone()
            if (tail is None) != (count == 0) or tail is not None and tail[key] != count:
                raise JournalError("financial committed tail count conflict")
            if tail is not None:
                if table == "events":
                    self._validate_outer(tail)
                    if tuple(
                        tail[x]
                        for x in (
                            "event_hash",
                            "state_hash",
                            "clock_ms",
                            "source_cursor",
                            "native_count",
                            "native_head",
                        )
                    ) != tuple(
                        head[x]
                        for x in (
                            "head_hash",
                            "state_hash",
                            "last_clock_ms",
                            "source_cursor",
                            "native_count",
                            "native_head",
                        )
                    ):
                        raise JournalError("outer tail/head conflict")
                else:
                    self._validate_native(tail)
                    if tail["event_hash"] != head["native_head"] or tail["outer_version"] > head["version"]:
                        raise JournalError("native tail/head conflict")
        if not head["version"] and (
            head["head_hash"] != metadata["genesis_hash"] or encoded != metadata["initial_state_json"]
        ):
            raise JournalError("empty financial head/genesis conflict")
        if not head["native_count"] and head["native_head"] != native_genesis(
            self.identity, owner_id=self.owner_id, account_id=self.account_id
        ):
            raise JournalError("empty native head/genesis conflict")
        snapshot = JournalSnapshot(
            head["version"], state, head["state_hash"], head["head_hash"], head["last_clock_ms"]
        )
        prior = self._retained_checkpoint
        if prior is not None:
            if snapshot.version < prior.version:
                raise JournalError("journal rolled back behind independent retained checkpoint")
            retained = self._connection.execute(
                "SELECT event_hash FROM events WHERE version=?", (prior.version,)
            ).fetchone()
            actual = metadata["genesis_hash"] if prior.version == 0 else retained[0] if retained else None
            if actual != prior.head_hash:
                raise JournalError("retained financial prefix diverged")
        return snapshot

    def _data_version(self):
        return self._connection.execute("PRAGMA data_version").fetchone()[0]

    def _verified_current(self):
        # Pin the read transaction before observing data_version. On DELETE
        # journaling an external writer cannot commit behind this shared lock;
        # BEGIN IMMEDIATE already fences writers for financial transitions.
        self._connection.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
        observed = self._data_version()
        if self._observed_data_version != observed:
            snapshot = self._audit()  # _audit calls _current, never this guard.
            self._observed_data_version = observed
            return snapshot
        return self._current()

    def _audit(self):
        metadata = self._check_storage()
        if self._connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise JournalError("financial SQLite integrity check failed")
        state = _load(metadata["initial_state_json"])
        if self._state_json(state) != metadata["initial_state_json"] or _hash(
            metadata["initial_state_json"]
        ) != _sha(metadata["initial_state_hash"]):
            raise JournalError("financial initial state commitment conflict")
        clock = int(metadata["initial_clock_ms"])
        if str(clock) != metadata["initial_clock_ms"] or state["clock"] != clock:
            raise JournalError("financial initial clock conflict")
        previous = _hash(
            _canonical([SCHEMA_ID, self._configuration(), metadata["initial_state_hash"], clock])
        )
        if previous != metadata["genesis_hash"]:
            raise JournalError("financial genesis commitment conflict")
        expected_ref = initial_ledger_reference(
            self.identity, owner_id=self.owner_id, account_id=self.account_id
        )
        if decode_account_core(state["account"])[1] != expected_ref:
            raise JournalError("financial native genesis reference conflict")
        version, native_count, native_head, cursor = 0, 0, expected_ref.head_sha256, state["cursor"]
        for row in self._connection.execute("SELECT * FROM events ORDER BY version"):
            version += 1
            _, _, delta = self._validate_outer(row)
            if (
                version > self.max_event_rows
                or row["version"] != version
                or row["previous_hash"] != previous
                or row["clock_ms"] < clock
                or row["source_cursor"] < cursor
                or row["native_count"] < native_count
                or row["native_count"] > self.max_native_event_rows
            ):
                raise JournalError("outer sequence/clock/cursor/native prefix conflict")
            within = 0
            native_bytes = 0
            for native in self._connection.execute(
                "SELECT * FROM native_events WHERE ordinal>? AND ordinal<=? ORDER BY ordinal",
                (native_count, row["native_count"]),
            ):
                within += 1
                self._validate_native(native)
                native_bytes += len(native["event_json"].encode("utf-8"))
                native_count += 1
                if (
                    native["ordinal"] != native_count
                    or native["outer_version"] != version
                    or native["within_outer"] != within
                    or native["previous_hash"] != native_head
                ):
                    raise JournalError("native exact order/outer ownership/prefix conflict")
                native_head = native["event_hash"]
            if (native_count, native_head) != (row["native_count"], row["native_head"]):
                raise JournalError("native chain incomplete or different from outer commitment")
            outer_bytes = len(row["event_id"].encode("utf-8")) + sum(
                len(row[key].encode("utf-8")) for key in ("payload_json", "outcome_json", "delta_json")
            )
            if native_bytes + outer_bytes > self.max_event_bytes:
                raise JournalFull("stored atomic financial event byte bound exceeded")
            after = apply_delta(state, delta)
            encoded = self._state_json(after)
            _, ref = decode_account_core(after["account"])
            if (
                _canonical(make_delta(state, after)) != row["delta_json"]
                or _hash(encoded) != row["state_hash"]
                or after["clock"] != row["clock_ms"]
                or after["cursor"] != row["source_cursor"]
                or ref != AccountLedgerRefV3(self.owner_id, self.account_id, native_count, native_head)
            ):
                raise JournalError("financial delta/core/cursor/native commitment conflict")
            state, previous, clock, cursor = after, row["event_hash"], row["clock_ms"], row["source_cursor"]
        current = self._current()
        if (current.version, current.head_hash, _canonical(current.state)) != (
            version,
            previous,
            _canonical(state),
        ):
            raise JournalError("financial full replay differs from projection")
        return current

    def _checkpoint(self, snapshot):
        _, ref = decode_account_core(snapshot.state["account"])
        return FinancialCheckpointV3(
            _hash(_canonical(self.identity.__dict__)),
            self.owner_id,
            self.account_id,
            snapshot.version,
            snapshot.state_hash,
            snapshot.head_hash,
            snapshot.last_clock_ms,
            snapshot.state["cursor"],
            ref.event_count,
            ref.head_sha256,
        )

    @_serialized
    def snapshot(self):
        return self._read_operation(self._verified_current)

    @_serialized
    def audit(self):
        return self._read_operation(self._audit)

    def _read_operation(self, operation):
        if self._fold_context is not None:
            raise JournalError("nested journal operation during financial fold forbidden")
        try:
            self._connection.execute("BEGIN")
            snapshot = operation()
            observed_version = self._data_version()
            self._connection.commit()
            self._observed_data_version = observed_version
            self._retained_checkpoint = self._checkpoint(snapshot)
            return snapshot
        except BaseException:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    @_serialized
    def checkpoint(self):
        """Caller must independently retain this exact checkpoint before restart."""
        return self._checkpoint(self.snapshot())

    @_serialized
    def lookup(self, *, event_id, payload):
        _identifier(event_id, "event_id")
        payload_json = _canonical(payload)
        if type(payload) is not dict:
            raise JournalError("plain outer payload required")

        def operation():
            snapshot = self._verified_current()
            row = self._connection.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                return snapshot, None
            _, outcome, _ = self._validate_outer(row)
            if row["payload_json"] != payload_json:
                raise EventConflict("outer event ID reused with conflicting exact payload")
            return snapshot, AppendResult(snapshot, outcome, True)

        if self._fold_context is not None:
            raise JournalError("nested lookup during financial fold forbidden")
        try:
            self._connection.execute("BEGIN")
            snapshot, result = operation()
            self._connection.commit()
            self._retained_checkpoint = self._checkpoint(snapshot)
            return result
        except BaseException:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def _native_lookup(self, event_id):
        row = self._connection.execute("SELECT * FROM native_events WHERE event_id=?", (event_id,)).fetchone()
        return None if row is None else self._validate_native(row)

    def lookup_native_event(self, event_id):
        """Exact owned native lookup for in-fold audit gates, including staged costs."""
        _identifier(event_id, "native event_id")
        self._staged_native_rows()  # Require the same live transactional context.
        staged = self._fold_context.lookup_staged_event(event_id)
        return staged if staged is not None else self._native_lookup(event_id)

    def _staged_native_rows(self):
        context = current_native_event_context()
        if context is None or context is not self._fold_context or not self._connection.in_transaction:
            raise JournalError("owned financial transaction context required")
        rows = self._fold_native_rows
        if context.staged_event_count < len(rows):
            raise JournalError("native stage lost its retained transaction prefix")
        count = rows[-1]["ordinal"] if rows else self._fold_base_ref.event_count
        previous = rows[-1]["event_hash"] if rows else self._fold_base_ref.head_sha256
        for within, event in enumerate(context.staged_suffix(len(rows)), len(rows) + 1):
            count += 1
            encoded = canonical_native_event(event)
            row = {
                "ordinal": count,
                "event_id": event.event_id,
                "outer_version": self._fold_version,
                "within_outer": within,
                "event_json": encoded,
                "content_hash": _hash(encoded),
                "previous_hash": previous,
            }
            row["event_hash"] = _native_hash(row)
            rows.append(row)
            previous = row["event_hash"]
        return rows

    def ledger_reference(self):
        rows = self._staged_native_rows()
        return (
            self._fold_base_ref
            if not rows
            else AccountLedgerRefV3(
                self.owner_id, self.account_id, rows[-1]["ordinal"], rows[-1]["event_hash"]
            )
        )

    def validate_ledger_reference(self, reference):
        if type(reference) is not AccountLedgerRefV3:
            raise JournalError("exact account ledger reference required")
        rows = self._staged_native_rows()
        offset = reference.event_count - self._fold_base_ref.event_count
        expected = (
            self._fold_base_ref
            if offset == 0
            else AccountLedgerRefV3(
                self.owner_id, self.account_id, rows[offset - 1]["ordinal"], rows[offset - 1]["event_hash"]
            )
            if 0 < offset <= len(rows)
            else None
        )
        if reference != expected:
            raise JournalError("core ledger reference is not an exact owned transaction prefix")

    def _insert_native(self, row):
        self._connection.execute("INSERT INTO native_events VALUES(?,?,?,?,?,?,?,?)", tuple(row.values()))

    def _before_commit(self):
        """Fault-injection seam; never an external commit callback."""

    @_serialized
    def transition(
        self, *, event_id, payload, at_ms, expected_version, expected_state_hash, expected_head_sha256, fold
    ):
        if self._fold_context is not None:
            raise JournalError("nested financial transition forbidden")
        _identifier(event_id, "event_id")
        _clock(at_ms)
        _integer(expected_version, "expected version")
        _sha(expected_state_hash)
        _sha(expected_head_sha256)
        if type(payload) is not dict or not callable(fold):
            raise JournalError("plain outer envelope and callable financial fold required")
        payload_json = _canonical(payload)
        connection = self._connection
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self._verified_current()
            prior = connection.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            if prior is not None:
                _, outcome, _ = self._validate_outer(prior)
                if prior["payload_json"] != payload_json or prior["clock_ms"] != at_ms:
                    raise EventConflict("outer event ID reused with conflicting exact payload")
                connection.commit()
                self._retained_checkpoint = self._checkpoint(current)
                return AppendResult(current, outcome, True)
            if (current.version, current.state_hash, current.head_hash) != (
                expected_version,
                expected_state_hash,
                expected_head_sha256,
            ):
                raise OptimisticConflict("financial version/state/head fence no longer matches")
            if at_ms < current.last_clock_ms:
                raise JournalError("financial event clock regressed")
            if current.version >= self.max_event_rows:
                raise JournalFull("financial outer row bound reached; nothing evicted")
            state = _load(_canonical(current.state))
            account, ref = decode_account_core(state["account"])
            context = NativeEventContext(
                owner_id=self.owner_id,
                account_id=self.account_id,
                account=account,
                lookup_exact=self._native_lookup,
                allowed_quantity_steps=self.allowed_quantity_steps,
            )
            self._fold_context, self._fold_base_ref, self._fold_version = context, ref, current.version + 1
            with (
                context.scope(owner_id=self.owner_id, account_id=self.account_id),
                localcontext(Context(prec=96)),
            ):
                outcome = fold(state)
                native_rows = self._staged_native_rows()
                final_ref = self.ledger_reference()
                if final_ref.event_count > self.max_native_event_rows:
                    raise JournalFull("financial native row bound reached; nothing evicted")
                account, supplied_ref = decode_account_core(state["account"])
                self.validate_ledger_reference(supplied_ref)
                context.validate_account(account)
                state["account"] = encode_account_core(account, final_ref)
                state["clock"], state["last_outcome"] = at_ms, outcome
                if _integer(state.get("cursor"), "source cursor") < current.state["cursor"]:
                    raise JournalError("financial source cursor regressed")
                state_json = self._state_json(state)
                outcome_json, delta_json = _canonical(outcome), _canonical(make_delta(current.state, state))
                size = len(event_id.encode("utf-8")) + sum(
                    len(x.encode("utf-8")) for x in (payload_json, outcome_json, delta_json)
                )
                size += sum(len(row["event_json"].encode("utf-8")) for row in native_rows)
                if size > self.max_event_bytes:
                    raise JournalFull("atomic financial envelope/native/delta byte bound exceeded")
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
                    "source_cursor": state["cursor"],
                    "native_count": final_ref.event_count,
                    "native_head": final_ref.head_sha256,
                }
                row["event_hash"] = _outer_hash(row)
                for native in native_rows:
                    self._insert_native(native)
                columns = tuple(row)
                connection.execute(
                    f"INSERT INTO events({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                    tuple(row.values()),
                )
                self._update_projection(_load(delta_json))
                connection.execute(
                    "UPDATE head SET version=?,state_hash=?,head_hash=?,last_clock_ms=?,"
                    "source_cursor=?,native_count=?,native_head=?,state_bytes=?,node_count=? "
                    "WHERE singleton=1",
                    (
                        row["version"],
                        row["state_hash"],
                        row["event_hash"],
                        at_ms,
                        state["cursor"],
                        final_ref.event_count,
                        final_ref.head_sha256,
                        len(state_json.encode("utf-8")),
                        _count_nodes(state),
                    ),
                )
                _verify_database_pages(connection, self.max_database_bytes)
                verified = self._current()
                if (verified.state_hash, verified.head_hash) != (row["state_hash"], row["event_hash"]):
                    raise JournalError("financial projection verification failed before commit")
                self._before_commit()
                connection.commit()
            snapshot = JournalSnapshot(row["version"], state, row["state_hash"], row["event_hash"], at_ms)
            self._retained_checkpoint = self._checkpoint(snapshot)
            return AppendResult(snapshot, _load(outcome_json), False)
        except BaseException as error:
            if connection.in_transaction:
                connection.rollback()
            if isinstance(error, sqlite3.DatabaseError) and "full" in str(error).casefold():
                raise JournalFull("financial SQLite byte bound reached; all writes rolled back") from error
            raise
        finally:
            self._fold_context = self._fold_base_ref = self._fold_version = None
            self._fold_native_rows = []

    @_serialized
    def native_events(self):
        """Export a pinned read-only snapshot; caller must consume/close iterator."""
        checkpoint = self._checkpoint(self.audit())
        physical = self._file_identity

        def iterate():
            connection = sqlite3.connect(_existing_uri(self.path, readonly=True), uri=True, timeout=0)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA query_only=ON")
                connection.execute("BEGIN")
                if _file_identity(self.path) != physical:
                    raise JournalError("financial export file identity changed")
                reader = type(self)(
                    connection,
                    self.path,
                    self.identity,
                    owner_id=self.owner_id,
                    account_id=self.account_id,
                    allowed_quantity_steps=self.allowed_quantity_steps,
                    **{key: getattr(self, key) for key in DEFAULT_LIMITS},
                )
                if reader._checkpoint(reader._audit()) != checkpoint:
                    raise JournalError("financial export changed before pinned snapshot opened")
                for row in connection.execute("SELECT * FROM native_events ORDER BY ordinal"):
                    yield self._validate_native(row)
            finally:
                connection.close()

        return iterate()

    @_serialized
    def close(self):
        if self._fold_context is not None:
            raise JournalError("cannot close during financial fold")
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
