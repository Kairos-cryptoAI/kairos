"""Plan-only, status-file-only notification state machine for the R4 epoch.

This module contains no polling loop or network client.  Callers may inject a
read-only observer, an append-only journal, and a sender.  The command-line
entry point only prints a static plan; it never reads status or sends alerts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

R4_STATUS_PATH = Path(
    r"D:\Kairos\runtime\runtime-incident-20261012\clean-recovery-r4-97469e3b772b4d00b0b531282ba01b55\output-serve\status.json"
)
R4_OWNER = "69893dc7b7c647f49967387e7efca9fb"
MAX_JOURNAL_BYTES = 65_536
MAX_JOURNAL_RECORDS = 256
MAX_RECORD_BYTES = 1_024
_ALERTING_STATES = frozenset(
    {"failed_closed", "missing", "invalid", "unknown_owner", "running_stale"}
)
_STATES = _ALERTING_STATES | {"running_fresh"}
_OWNER_RE = re.compile(r"[0-9a-f]{32}\Z")
_EVENT_RE = re.compile(r"[0-9a-f]{64}\Z")


class AlertJournalError(RuntimeError):
    """A sanitized fail-closed journal or exclusive-lease error."""


@dataclass(frozen=True, slots=True)
class SanitizedAlert:
    """The only data passed to the injected sender; contains no raw status."""

    event_id: str
    transition: str
    state: str
    message: str


@dataclass(frozen=True, slots=True)
class PollResult:
    status: str
    state: str | None
    send_attempts: int
    event_id: str | None = None


class Observer(Protocol):
    def __call__(self, path: Path, *, expected_owner: str) -> Any: ...


class Sender(Protocol):
    def __call__(self, alert: SanitizedAlert, /) -> bool: ...


class Journal(Protocol):
    def locked(self) -> Any: ...

    def read_records(self) -> list[dict[str, Any]]: ...

    def append(self, record: Mapping[str, Any]) -> None: ...


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _observer(path: Path, *, expected_owner: str) -> Any:
    """Import Persistence lazily; calling it invokes only its pure file reader."""

    from kairos_persistence.metrics_exporter import observe_runtime_epoch_serve_status

    return observe_runtime_epoch_serve_status(path, expected_owner=expected_owner)


def _classify(observation: Any) -> str:
    state = getattr(observation, "state", None)
    stale = getattr(observation, "stale", None)
    if state == "running":
        if type(stale) is not bool:
            return "invalid"
        return "running_stale" if stale is True else "running_fresh"
    if state == "stale":
        return "running_stale"
    if state in _ALERTING_STATES - {"running_stale"}:
        return state
    return "invalid"


def _validate_journal(records: list[dict[str, Any]]) -> dict[str, Any]:
    if len(records) > MAX_JOURNAL_RECORDS:
        raise AlertJournalError("JOURNAL_RECORD_LIMIT")
    current: str | None = None
    active = False
    poisoned = False
    pending: tuple[str, str, str] | None = None
    for sequence, record in enumerate(records):
        if not isinstance(record, dict) or type(record.get("seq")) is not int:
            raise AlertJournalError("JOURNAL_INVALID")
        if record["seq"] != sequence:
            raise AlertJournalError("JOURNAL_INVALID")
        kind = record.get("kind")
        if kind == "observe":
            if set(record) != {"schema_version", "seq", "kind", "state"}:
                raise AlertJournalError("JOURNAL_INVALID")
            state = record.get("state")
            if record.get("schema_version") != 1 or state not in _STATES or pending:
                raise AlertJournalError("JOURNAL_INVALID")
            if current == state:
                raise AlertJournalError("JOURNAL_INVALID")
            current = state
        elif kind == "send_reserved":
            if set(record) != {
                "schema_version",
                "seq",
                "kind",
                "event_id",
                "transition",
                "state",
            }:
                raise AlertJournalError("JOURNAL_INVALID")
            event_id = record.get("event_id")
            transition = record.get("transition")
            state = record.get("state")
            valid_transition = (
                transition == "firing" and state in _ALERTING_STATES and not active
            ) or (transition == "resolved" and state == "running_fresh" and active)
            if (
                record.get("schema_version") != 1
                or not isinstance(event_id, str)
                or _EVENT_RE.fullmatch(event_id) is None
                or not valid_transition
                or state != current
                or pending
            ):
                raise AlertJournalError("JOURNAL_INVALID")
            pending = (event_id, transition, state)
        elif kind == "send_outcome":
            if set(record) != {
                "schema_version",
                "seq",
                "kind",
                "event_id",
                "result",
                "state",
            }:
                raise AlertJournalError("JOURNAL_INVALID")
            if (
                record.get("schema_version") != 1
                or pending is None
                or record.get("event_id") != pending[0]
                or record.get("state") != pending[2]
                or record.get("result") not in {"accepted", "unknown"}
            ):
                raise AlertJournalError("JOURNAL_INVALID")
            if record["result"] == "unknown":
                poisoned = True
            else:
                active = pending[1] == "firing"
            pending = None
        else:
            raise AlertJournalError("JOURNAL_INVALID")
    if pending is not None:
        poisoned = True
    return {"current": current, "active": active, "poisoned": poisoned}


class FileJournal:
    """Append-only O_EXCL/fsync journal; its parent must be pre-provisioned."""

    def __init__(
        self,
        path: str | Path,
        *,
        secure_new_file: Callable[[Path], None] | None = None,
        verify_private_file: Callable[[Path], None] | None = None,
    ) -> None:
        self.path = Path(path)
        self.lease_path = self.path.with_name(self.path.name + ".lock")
        self.secure_new_file = secure_new_file
        self.verify_private_file = verify_private_file

    def _privacy(self, path: Path, *, new: bool = False) -> None:
        try:
            if new and self.secure_new_file is not None:
                self.secure_new_file(path)
            if self.verify_private_file is not None:
                self.verify_private_file(path)
        except Exception:  # noqa: BLE001 - no raw filesystem/ACL errors escape.
            raise AlertJournalError("PROTECTED_FILE_REQUIRED") from None

    @contextmanager
    def locked(self) -> Iterator[None]:
        self._check_parent()
        token = uuid.uuid4().hex.encode("ascii")
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.lease_path, flags, 0o600)
        except FileExistsError as error:
            raise AlertJournalError(
                "JOURNAL_BUSY_OR_PRIOR_LEASE_REQUIRES_REVIEW"
            ) from error
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(token)
                stream.flush()
                os.fsync(stream.fileno())
            self._privacy(self.lease_path, new=True)
            yield
        finally:
            try:
                info = self.lease_path.lstat()
                if (
                    self.lease_path.is_symlink()
                    or getattr(info, "st_file_attributes", 0) & 0x400
                    or not stat.S_ISREG(info.st_mode)
                    or self.lease_path.read_bytes() != token
                ):
                    raise AlertJournalError("JOURNAL_LEASE_CHANGED")
                self.lease_path.unlink()
            except FileNotFoundError as error:
                raise AlertJournalError("JOURNAL_LEASE_LOST") from error

    def _check_parent(self) -> None:
        parent = self.path.parent
        try:
            info = parent.lstat()
        except OSError as error:
            raise AlertJournalError("JOURNAL_PARENT_UNAVAILABLE") from error
        if (
            parent.is_symlink()
            or getattr(info, "st_file_attributes", 0) & 0x400
            or not stat.S_ISDIR(info.st_mode)
        ):
            raise AlertJournalError("JOURNAL_PARENT_INVALID")

    def read_records(self) -> list[dict[str, Any]]:
        self._check_parent()
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return []
        except OSError as error:
            raise AlertJournalError("JOURNAL_UNREADABLE") from error
        if (
            self.path.is_symlink()
            or getattr(info, "st_file_attributes", 0) & 0x400
            or not stat.S_ISREG(info.st_mode)
            or info.st_size > MAX_JOURNAL_BYTES
        ):
            raise AlertJournalError("JOURNAL_INVALID")
        self._privacy(self.path)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, flags)
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    raise AlertJournalError("JOURNAL_CHANGED_DURING_READ")
                raw = stream.read(MAX_JOURNAL_BYTES + 1)
        except AlertJournalError:
            raise
        except OSError as error:
            raise AlertJournalError("JOURNAL_UNREADABLE") from error
        if len(raw) > MAX_JOURNAL_BYTES:
            raise AlertJournalError("JOURNAL_INVALID")
        if not raw:
            raise AlertJournalError("JOURNAL_INVALID")
        lines = raw.splitlines()
        if any(not line or len(line) > MAX_RECORD_BYTES for line in lines):
            raise AlertJournalError("JOURNAL_INVALID")
        try:
            records = [
                json.loads(line, object_pairs_hook=_duplicate_rejecting_object)
                for line in lines
            ]
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
            TypeError,
        ) as error:
            raise AlertJournalError("JOURNAL_INVALID") from error
        if any(not isinstance(record, dict) for record in records):
            raise AlertJournalError("JOURNAL_INVALID")
        _validate_journal(records)
        return records

    def append(self, record: Mapping[str, Any]) -> None:
        self._check_parent()
        records = self.read_records()
        if len(records) >= MAX_JOURNAL_RECORDS:
            raise AlertJournalError("JOURNAL_RECORD_LIMIT")
        candidate = dict(record)
        _validate_journal(records + [candidate])
        encoded = (
            json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode("utf-8")
            + b"\n"
        )
        if len(encoded) > MAX_RECORD_BYTES:
            raise AlertJournalError("JOURNAL_RECORD_LIMIT")
        if candidate.get("kind") == "send_reserved":
            self._create_send_guard(candidate)
        exists = self.path.exists()
        flags = (
            os.O_WRONLY
            | os.O_APPEND
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        if not exists:
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
        try:
            descriptor = os.open(self.path, flags, 0o600)
            with os.fdopen(descriptor, "ab") as stream:
                written = stream.write(encoded)
                if written != len(encoded):
                    raise AlertJournalError("JOURNAL_SHORT_WRITE")
                stream.flush()
                os.fsync(stream.fileno())
            self._privacy(self.path, new=not exists)
        except AlertJournalError:
            raise
        except OSError as error:
            raise AlertJournalError("JOURNAL_WRITE_FAILED") from error

    def _create_send_guard(self, record: Mapping[str, Any]) -> None:
        guard = self.path.with_name(
            self.path.name + "." + str(record["event_id"]) + ".guard"
        )
        payload = json.dumps(
            {
                "schema_version": 1,
                "event_id": record["event_id"],
                "transition": record["transition"],
                "state": record["state"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(guard, flags, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            self._privacy(guard, new=True)
        except FileExistsError as error:
            raise AlertJournalError("SEND_GUARD_ALREADY_EXISTS") from error
        except OSError as error:
            raise AlertJournalError("SEND_GUARD_CREATE_FAILED") from error


class RuntimeStatusAlertPlanner:
    """One-shot transition planner, bound to the one approved R4 status file."""

    def __init__(
        self,
        *,
        journal: Journal,
        sender: Sender,
        observer: Observer = _observer,
    ) -> None:
        self.journal = journal
        self.sender = sender
        self.observer = observer

    def poll_once(self) -> PollResult:
        try:
            with self.journal.locked():
                records = self.journal.read_records()
                state_data = _validate_journal(records)
                if state_data["poisoned"]:
                    return PollResult(
                        "send_outcome_unknown_or_unresolved", state_data["current"], 0
                    )
                try:
                    state = _classify(
                        self.observer(R4_STATUS_PATH, expected_owner=R4_OWNER)
                    )
                except Exception:  # noqa: BLE001 - sanitize arbitrary observer failures.
                    state = "invalid"
                if state not in _STATES:
                    state = "invalid"

                if state_data["current"] != state:
                    self._append(records, "observe", state=state)
                    records = self.journal.read_records()
                    state_data = _validate_journal(records)

                if state == "running_fresh":
                    if not state_data["active"]:
                        return PollResult("quiet_healthy", state, 0)
                    return self._send(records, transition="resolved", state=state)
                if state_data["active"]:
                    return PollResult("quiet_incident_active", state, 0)
                return self._send(records, transition="firing", state=state)
        except AlertJournalError:
            return PollResult("journal_blocked", None, 0)

    def _append(self, records: list[dict[str, Any]], kind: str, **fields: Any) -> None:
        self.journal.append(
            {"schema_version": 1, "seq": len(records), "kind": kind, **fields}
        )

    def _send(
        self, records: list[dict[str, Any]], *, transition: str, state: str
    ) -> PollResult:
        sequence = len(records)
        event_id = hashlib.sha256(
            f"{R4_OWNER}|{sequence}|{transition}|{state}".encode("ascii")
        ).hexdigest()
        self._append(
            records,
            "send_reserved",
            event_id=event_id,
            transition=transition,
            state=state,
        )
        message = (
            "[Kairos R4] Runtime status is unhealthy. Trading remains disabled."
            if transition == "firing"
            else "[Kairos R4] Runtime status returned to fresh RUNNING_NONTRADING. Trading remains disabled."
        )
        alert = SanitizedAlert(event_id, transition, state, message)
        try:
            accepted = self.sender(alert) is True
        except Exception:  # noqa: BLE001 - a transport failure is an unknown outcome.
            accepted = False
        outcome = "accepted" if accepted else "unknown"
        try:
            refreshed = self.journal.read_records()
            self._append(
                refreshed,
                "send_outcome",
                event_id=event_id,
                result=outcome,
                state=state,
            )
        except AlertJournalError:
            # The retained reservation suppresses re-entry, even if delivery
            # succeeded but recording its outcome failed.
            return PollResult(
                "send_outcome_unknown_or_journal_failed", state, 1, event_id
            )
        if not accepted:
            return PollResult("send_outcome_unknown", state, 1, event_id)
        return PollResult(f"{transition}_accepted", state, 1, event_id)


def plan() -> dict[str, Any]:
    return {
        "status": "PLAN_ONLY",
        "scope": "one fixed R4 serve status file and approved owner",
        "automatic_execution": False,
        "status_file_read": False,
        "network_calls": False,
        "business_services": False,
        "database_or_redis": False,
        "financial_mutations": False,
        "telegram_delivery_qualified": False,
        "trading_authority": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    print(json.dumps(plan(), sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - the CLI is deliberately plan-only.
    raise SystemExit(main())
