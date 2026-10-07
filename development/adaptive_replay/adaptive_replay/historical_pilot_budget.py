"""Local durable one-shot cap for the frozen historical pilot; not a dispatcher."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = "kairos.development.historical-pilot-local-cap.v1"
CEILING_MICRO_USD = 1_000_000
MAX_ATTEMPTS = 20
FROZEN_PLAN_SHA256 = "d9347eeca568f6b8fc98a75645ffe484e27df2ce3cd84415b97f8b554d12e497"
REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_EPISODES = (
    ("episode_a", ("2021-05-19T00:00:00Z", "2021-05-19T08:00:00Z")),
    ("episode_d", ("2024-01-09T21:15:00Z", "2024-01-09T21:30:00Z")),
)
_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
ALLOWED_SLOT_IDS = tuple(
    f"{episode_id}|{cut}|{symbol}" for episode_id, cuts in _EPISODES for cut in cuts for symbol in _SYMBOLS
)


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _validate_uuid(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("ledger UUID must be supplied as canonical text")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise ValueError("ledger UUID must be canonical UUID text") from None
    if str(parsed) != value:
        raise ValueError("ledger UUID must be canonical lowercase UUID text")
    return value


def _validate_sha256(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError("pilot plan identity must be a lowercase SHA-256 hex digest")
    if value != FROZEN_PLAN_SHA256:
        raise ValueError("pilot plan identity does not match the frozen approved draft")
    return value


def _validate_slots(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)) or any(not isinstance(item, str) for item in values):
        raise ValueError("the exact allowed pilot slot roster must be supplied")
    slots = tuple(values)
    if len(slots) != MAX_ATTEMPTS or len(set(slots)) != MAX_ATTEMPTS or slots != ALLOWED_SLOT_IDS:
        raise ValueError("slot roster must exactly match the 20 frozen episode/cut/symbol slots")
    return slots


def _validate_path(path: Path, plan_sha256: str, *, create: bool) -> tuple[Path, Path]:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError("ledger path must be an absolute Path")
    path = path.absolute()
    workspace = path.parent.parent
    for component in (*reversed(workspace.parents), workspace, path.parent, path):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        if component.is_symlink() or getattr(metadata, "st_file_attributes", 0) & REPARSE_POINT:
            raise ValueError("ledger path must not contain symlinks or junctions")
    runtime = workspace / "runtime"
    repo = workspace / "kairos"
    draft = repo / "development" / "adaptive_replay" / "historical-episodes-draft.json"
    if (
        path.parent != runtime
        or not runtime.is_dir()
        or runtime.resolve(strict=True).parent != workspace.resolve(strict=True)
        or not repo.is_dir()
        or not draft.is_file()
    ):
        raise ValueError("ledger must be a direct runtime child beside the frozen Kairos pilot draft")
    if hashlib.sha256(draft.read_bytes()).hexdigest() != plan_sha256:
        raise ValueError("on-disk pilot draft does not match the frozen plan identity")
    if create and path.exists():
        raise FileExistsError("ledger initialization is create-new only")
    if not create and not path.is_file():
        raise FileNotFoundError("existing ledger is required; missing ledgers are never initialized")
    return path, workspace


@contextmanager
def _transaction(path: Path, *, create: bool = False) -> Iterator[sqlite3.Connection]:
    if create:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(descriptor)
        connection = sqlite3.connect(path, timeout=15.0, isolation_level=None)
    else:
        # mode=rw prevents sqlite3 from silently creating a missing ledger.
        connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=15.0, isolation_level=None)
    try:
        connection.execute("PRAGMA busy_timeout=15000")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    finally:
        connection.close()


def _schema(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute(
        "CREATE TABLE allowed_slots (slot_id TEXT PRIMARY KEY, ordinal INTEGER NOT NULL UNIQUE)"
    )
    connection.execute(
        "CREATE TABLE attempts (slot_id TEXT PRIMARY KEY REFERENCES allowed_slots(slot_id), "
        "reserved_micro_usd INTEGER NOT NULL CHECK(reserved_micro_usd > 0), "
        "actual_micro_usd TEXT, "
        "state TEXT NOT NULL CHECK(state IN ('HELD','SETTLED','OVERRUN')))"
    )


def _metadata(connection: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = connection.execute("SELECT key, value FROM metadata").fetchall()
    except sqlite3.DatabaseError:
        raise ValueError("ledger schema is invalid or unreadable") from None
    if any(type(key) is not str or type(value) is not str for key, value in rows):
        raise ValueError("ledger metadata contains invalid value types")
    if len({key for key, _value in rows}) != len(rows):
        raise ValueError("ledger metadata contains duplicate keys")
    return dict(rows)


@dataclass(frozen=True)
class PilotBudget:
    path: Path
    ledger_uuid: str
    plan_sha256: str
    slot_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not self.path.is_absolute():
            raise ValueError("ledger path must be an absolute Path")
        _validate_uuid(self.ledger_uuid)
        _validate_sha256(self.plan_sha256)
        if type(self.slot_ids) is not tuple or _validate_slots(self.slot_ids) != self.slot_ids:
            raise ValueError("budget object requires the exact immutable tuple of allowed slots")

    def _identity(self, connection: sqlite3.Connection) -> None:
        expected = {
            "schema": SCHEMA,
            "ledger_uuid": self.ledger_uuid,
            "pilot_plan_sha256": self.plan_sha256,
            "ceiling_micro_usd": str(CEILING_MICRO_USD),
            "max_attempts": str(MAX_ATTEMPTS),
            "sealed": "0",
            "seal_reason": "",
        }
        metadata = _metadata(connection)
        if set(metadata) != set(expected):
            raise ValueError("ledger metadata keys do not match the fixed schema")
        # Seal fields are mutable only as a result of a durably checked overrun.
        for key in ("schema", "ledger_uuid", "pilot_plan_sha256", "ceiling_micro_usd", "max_attempts"):
            if metadata.get(key) != expected[key]:
                raise ValueError("ledger identity does not match supplied UUID, frozen plan, or cap")
        try:
            slot_rows = connection.execute(
                "SELECT slot_id, ordinal FROM allowed_slots ORDER BY ordinal"
            ).fetchall()
        except sqlite3.DatabaseError:
            raise ValueError("ledger accepted slot roster is unreadable") from None
        if len(slot_rows) != MAX_ATTEMPTS or any(
            type(slot_id) is not str or type(ordinal) is not int or ordinal != index
            for index, (slot_id, ordinal) in enumerate(slot_rows)
        ):
            raise ValueError("ledger roster ordinals or types are invalid")
        if tuple(slot_id for slot_id, _ordinal in slot_rows) != self.slot_ids:
            raise ValueError("ledger accepted slot roster does not match the supplied frozen roster")

    def _state(self, connection: sqlite3.Connection) -> dict[str, Any]:
        self._identity(connection)
        metadata = _metadata(connection)
        try:
            rows = connection.execute(
                "SELECT slot_id, reserved_micro_usd, actual_micro_usd, state FROM attempts"
            ).fetchall()
            foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        except sqlite3.DatabaseError:
            raise ValueError("ledger attempts or foreign keys are invalid") from None
        if foreign_key_errors:
            raise ValueError("ledger contains a broken slot foreign key")
        if len(rows) > MAX_ATTEMPTS:
            raise ValueError("ledger attempt count exceeds fixed one-shot cap")
        seen_slots: set[str] = set()
        committed = 0
        held = 0
        overruns: list[str] = []
        for slot_id, reserved, actual, state in rows:
            if type(slot_id) is not str or slot_id not in self.slot_ids or slot_id in seen_slots:
                raise ValueError("ledger contains an unknown or duplicate slot attempt")
            seen_slots.add(slot_id)
            if type(reserved) is not int or not 0 < reserved <= CEILING_MICRO_USD:
                raise ValueError("ledger reservation has an invalid type or range")
            if state not in ("HELD", "SETTLED", "OVERRUN"):
                raise ValueError("ledger attempt state is invalid")
            if state == "HELD":
                if actual is not None:
                    raise ValueError("held attempt must not carry a known actual cost")
                held += reserved
                continue
            if type(actual) is not str or not actual.isascii() or not actual.isdigit():
                raise ValueError("settled actual cost must be canonical decimal text")
            if actual != "0" and actual.startswith("0"):
                raise ValueError("settled actual cost is not canonical decimal text")
            actual_cost = int(actual)
            if state == "SETTLED":
                if actual_cost > reserved:
                    raise ValueError("settled actual cost exceeds its reservation")
            else:
                if actual_cost <= reserved:
                    raise ValueError("overrun state must exceed its reservation")
                overruns.append(slot_id)
            committed += actual_cost
        sealed = metadata["sealed"]
        reason = metadata["seal_reason"]
        if sealed not in ("0", "1"):
            raise ValueError("ledger sealed metadata is invalid")
        if sealed == "0":
            if reason != "" or overruns:
                raise ValueError("unsealed ledger has inconsistent overrun metadata")
        elif not overruns or reason not in {f"observed_cost_overrun:{slot}" for slot in overruns}:
            raise ValueError("sealed ledger lacks a matching durable overrun")
        if committed + held > CEILING_MICRO_USD and sealed != "1":
            raise ValueError("unsealed ledger commitments exceed the approved ceiling")
        return {
            "schema": SCHEMA,
            "ledger_uuid": self.ledger_uuid,
            "pilot_plan_sha256": self.plan_sha256,
            "ceiling_micro_usd": CEILING_MICRO_USD,
            "max_attempts": MAX_ATTEMPTS,
            "slot_admissions": len(rows),
            "committed_micro_usd": committed,
            "held_reservation_micro_usd": held,
            "committed_plus_held_micro_usd": committed + held,
            "sealed": sealed == "1",
            "seal_reason": reason or None,
            "paid_dispatch_ready": False,
        }

    def snapshot(self) -> dict[str, Any]:
        path, _ = _validate_path(self.path, self.plan_sha256, create=False)
        with _transaction(path) as connection:
            return self._state(connection)

    def reserve_attempt(self, slot_id: str, reservation_micro_usd: int) -> dict[str, Any]:
        if not isinstance(slot_id, str) or slot_id not in self.slot_ids:
            raise ValueError("attempt slot is outside the immutable allowed roster")
        reservation = _positive_int(reservation_micro_usd, "reservation_micro_usd")
        if reservation > CEILING_MICRO_USD:
            raise ValueError("reservation exceeds the approved pilot ceiling")
        path, _ = _validate_path(self.path, self.plan_sha256, create=False)
        with _transaction(path) as connection:
            state = self._state(connection)
            if state["sealed"]:
                raise ValueError("ledger is sealed; no further admission is allowed")
            if connection.execute("SELECT 1 FROM attempts WHERE slot_id=?", (slot_id,)).fetchone():
                raise ValueError("slot has already consumed its one-shot attempt")
            if state["slot_admissions"] >= MAX_ATTEMPTS:
                raise ValueError("one-shot pilot attempt cap is exhausted")
            if state["committed_plus_held_micro_usd"] + reservation > CEILING_MICRO_USD:
                raise ValueError("reservation would exceed the cumulative pilot ceiling")
            connection.execute(
                "INSERT INTO attempts(slot_id,reserved_micro_usd,actual_micro_usd,state) "
                "VALUES(?,?,NULL,'HELD')",
                (slot_id, reservation),
            )
            return self._state(connection)

    def settle_known_cost(self, slot_id: str, actual_micro_usd: int) -> dict[str, Any]:
        if not isinstance(slot_id, str) or slot_id not in self.slot_ids:
            raise ValueError("settlement slot is outside the immutable allowed roster")
        if type(actual_micro_usd) is not int or actual_micro_usd < 0:
            raise ValueError("actual_micro_usd must be a nonnegative strict integer")
        path, _ = _validate_path(self.path, self.plan_sha256, create=False)
        with _transaction(path) as connection:
            state = self._state(connection)
            row = connection.execute(
                "SELECT reserved_micro_usd, actual_micro_usd, state FROM attempts WHERE slot_id=?", (slot_id,)
            ).fetchone()
            if row is None:
                raise ValueError("cannot settle a slot without an admitted attempt")
            reserved, previous_actual, previous_state = row
            if previous_actual is not None:
                if int(previous_actual) != actual_micro_usd:
                    raise ValueError("settlement conflicts with the durable actual cost")
                return self._state(connection)
            overrun = actual_micro_usd > reserved
            connection.execute(
                "UPDATE attempts SET actual_micro_usd=?,state=? WHERE slot_id=? AND actual_micro_usd IS NULL",
                (str(actual_micro_usd), "OVERRUN" if overrun else "SETTLED", slot_id),
            )
            if overrun and not state["sealed"]:
                reason = f"observed_cost_overrun:{slot_id}"
                connection.execute("UPDATE metadata SET value='1' WHERE key='sealed'")
                connection.execute("UPDATE metadata SET value=? WHERE key='seal_reason'", (reason,))
            result = self._state(connection)
            if previous_state != "HELD":
                raise ValueError("attempt state is invalid")
            return result


def create_new_ledger(
    path: Path, *, ledger_uuid: str, plan_sha256: str, slot_ids: tuple[str, ...] | list[str]
) -> PilotBudget:
    identity = _validate_uuid(ledger_uuid)
    plan = _validate_sha256(plan_sha256)
    slots = _validate_slots(slot_ids)
    target, _ = _validate_path(path, plan, create=True)
    with _transaction(target, create=True) as connection:
        _schema(connection)
        metadata = {
            "schema": SCHEMA,
            "ledger_uuid": identity,
            "pilot_plan_sha256": plan,
            "ceiling_micro_usd": str(CEILING_MICRO_USD),
            "max_attempts": str(MAX_ATTEMPTS),
            "sealed": "0",
            "seal_reason": "",
        }
        connection.executemany("INSERT INTO metadata(key,value) VALUES(?,?)", metadata.items())
        connection.executemany(
            "INSERT INTO allowed_slots(slot_id,ordinal) VALUES(?,?)",
            ((slot, index) for index, slot in enumerate(slots)),
        )
    return PilotBudget(target, identity, plan, slots)


def open_existing_ledger(
    path: Path, *, ledger_uuid: str, plan_sha256: str, slot_ids: tuple[str, ...] | list[str]
) -> PilotBudget:
    identity = _validate_uuid(ledger_uuid)
    plan = _validate_sha256(plan_sha256)
    slots = _validate_slots(slot_ids)
    target, _ = _validate_path(path, plan, create=False)
    budget = PilotBudget(target, identity, plan, slots)
    with _transaction(target) as connection:
        budget._state(connection)
    return budget
