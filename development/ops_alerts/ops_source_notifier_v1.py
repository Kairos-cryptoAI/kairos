"""Bounded, signed source alerts with a separate create-only send-once journal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__:
    from . import ops_source_feed as feed
else:
    import ops_source_feed as feed

META_ROOT = Path("D:/Kairos/kairos")
DEPLOY_ROOT = Path("D:/Kairos/kairos-deploy")
PRIVATE_ROOT = Path("D:/Kairos/runtime/alert-delivery-20261012/ops-source-notifier-v1")
VENUE_ROOT = Path("D:/Kairos/runtime/evedex-venue-observer")
BACKUP_ROOT = Path("D:/Kairos/runtime/runtime-incident-20261013")
JOURNAL_ROOT = PRIVATE_ROOT / "journals"
BINDING_ROOT = PRIVATE_ROOT / "bindings"
SIGNER = "40AF365C6682B73D056A6A274DBFF6B65BE9F827"
MAX_BINDING_BYTES = 16 * 1024
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_SIGNATURE_BYTES = 1024
MAX_JOURNAL_BYTES = 1024 * 1024
MAX_JOURNAL_RECORDS = 2048
MAX_RECORD_BYTES = 2048
MAX_FRESHNESS_MS = 24 * 60 * 60 * 1000
OPERATIONAL_CHAT_ID = -1004475802889
_META_EXECUTED_SOURCES = (
    "development/ops_alerts/ops_source_notifier_v1.py",
    "development/ops_alerts/ops_source_feed.py",
    "development/ops_alerts/runtime_status_r6_notifier.py",
    "development/ops_alerts/runtime_status_r5_notifier.py",
    "development/ops_alerts/telegram_continuation.py",
    "development/ops_alerts/telegram_handoff.py",
    "development/ops_alerts/notification-routing-20261012.json",
    "development/ops_alerts/evedex_venue_observer.py",
)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_VENUE_LOCATOR = re.compile(
    r"run-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/report\.json\Z"
)
_BACKUP_LOCATOR = re.compile(
    r"read-recovery-r7-[0-9a-f]{32}/(?:receipt|failure)\.json\Z"
)
_NAMESPACES = {
    feed.Source.VENUE_OBSERVATION: "ops-source-venue-v1",
    feed.Source.CAMPAIGN: "ops-source-campaign-v1",
    feed.Source.RISK: "ops-source-risk-v1",
    feed.Source.CANDIDATE: "ops-source-candidate-v1",
    feed.Source.BACKUP_RESTORE: "ops-source-backup-v1",
}
_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "source",
        "namespace",
        "receipt_locator",
        "receipt_sha256",
        "source_key_sha256",
        "source_state",
        "observed_at_ms",
        "recovery_kind",
        "producer_fingerprint",
        "meta_revision",
        "notifier_sha256",
    }
)
_JOURNAL_SCHEMA_SHA256 = hashlib.sha256(
    b"kairos.ops-source-send-once-journal.v1|reserved|accepted|unknown|no-retry"
).hexdigest()


class NotifierError(RuntimeError):
    """Fixed diagnostic category; never include filesystem or transport details."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


@dataclass(frozen=True, slots=True)
class DispatchIntent:
    event_id: str
    source: feed.Source
    source_state: str
    state: feed.State
    severity: feed.Severity
    namespace: str
    binding_sha256: str
    source_receipt_sha256: str
    text: str
    observed_at_ms: int
    automatic_retry: bool = False


def _json(raw: bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _module_sha256() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        raise NotifierError("NOTIFIER_SOURCE_UNAVAILABLE") from None


def project_event(
    event: feed.SourceEvent,
    *,
    now_ms: int,
    freshness_bound_ms: int = MAX_FRESHNESS_MS,
) -> feed.AlertCandidate | None:
    try:
        return feed.normalize_event(
            event,
            now_ms=now_ms,
            freshness_bound_ms=freshness_bound_ms,
        )
    except feed.FeedError as error:
        raise NotifierError(str(error)) from None


def _timestamp_ms(value: Any) -> int:
    if not isinstance(value, str) or len(value) > 64:
        raise NotifierError("SOURCE_RECEIPT_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise NotifierError("SOURCE_RECEIPT_INVALID") from None
    if parsed.tzinfo is None:
        raise NotifierError("SOURCE_RECEIPT_INVALID")
    return int(parsed.astimezone(UTC).timestamp() * 1000)


def _expected_venue_symbols() -> frozenset[str]:
    try:
        if __package__:
            from . import evedex_venue_observer as observer
        else:
            import evedex_venue_observer as observer

        return frozenset(symbol for symbol, _venue_symbol in observer.INSTRUMENTS)
    except (ImportError, AttributeError):
        raise NotifierError("VENUE_CONTRACT_UNAVAILABLE") from None


def _receipt_event(source: feed.Source, raw: bytes) -> tuple[feed.SourceEvent, str]:
    try:
        value = _json(raw)
    except (UnicodeDecodeError, ValueError):
        raise NotifierError("SOURCE_RECEIPT_INVALID") from None
    receipt_hash = hashlib.sha256(raw).hexdigest()
    if source is feed.Source.VENUE_OBSERVATION:
        if (
            not isinstance(value, dict)
            or value.get("schema") != "kairos-evedex-public-observer-report-v1"
            or value.get("status") != "OBSERVATION_RECORDED"
            or value.get("qualification_status")
            != "NOT_QUALIFIED_OWNER_REVIEW_REQUIRED"
            or value.get("authenticated") is not False
            or value.get("orders_enabled") is not False
            or value.get("database_or_redis") is not False
            or value.get("readiness_changed") is not False
            or value.get("sample_is_24h_evidence") is not False
            or value.get("account_prerequisites_attested") is not False
            or value.get("automatic_retry") is not False
            or value.get("resume_supported") is not False
            or type(value.get("unknown_outcomes")) is not int
            or value["unknown_outcomes"] < 0
            or type(value.get("missed_slots")) is not int
            or value["missed_slots"] < 0
            or type(value.get("planned_slots")) is not int
            or type(value.get("completed_slots")) is not int
            or type(value.get("requests_reserved")) is not int
            or type(value.get("requests_attempted")) is not int
            or type(value.get("requests_completed")) is not int
            or type(value.get("requests_not_sent")) is not int
            or not isinstance(value.get("symbols"), dict)
            or set(value["symbols"]) != _expected_venue_symbols()
            or not isinstance(value.get("observer_source_sha256"), str)
            or not _HEX64.fullmatch(value["observer_source_sha256"])
        ):
            raise NotifierError("SOURCE_RECEIPT_INVALID")
        try:
            started = _timestamp_ms(value.get("started_at_utc"))
            finished = _timestamp_ms(value.get("finished_at_utc"))
        except NotifierError:
            raise NotifierError("SOURCE_RECEIPT_INVALID") from None
        if (
            finished < started
            or value["planned_slots"] < 1
            or value["completed_slots"] < 0
            or value["completed_slots"] > value["planned_slots"]
            or value["missed_slots"]
            != value["planned_slots"] - value["completed_slots"]
            or any(
                value[key] < 0
                for key in (
                    "unknown_outcomes",
                    "requests_reserved",
                    "requests_attempted",
                    "requests_completed",
                    "requests_not_sent",
                )
            )
        ):
            raise NotifierError("SOURCE_RECEIPT_INVALID")
        state = (
            "UNKNOWN_OUTCOME"
            if value["unknown_outcomes"] > 0
            else ("MISSED_RUN_DEADLINE" if value["missed_slots"] > 0 else None)
        )
        if state is None:
            raise NotifierError("NO_ALERTABLE_SOURCE_STATE")
        event = feed.SourceEvent(
            source=source,
            source_state=state,
            source_key_sha256=receipt_hash,
            observed_at_ms=_timestamp_ms(value.get("finished_at_utc")),
        )
        return event, value["observer_source_sha256"]
    if source is feed.Source.BACKUP_RESTORE:
        if not isinstance(value, dict):
            raise NotifierError("SOURCE_RECEIPT_INVALID")
        result = value.get("result")
        if result == "PASS_NEW_NONTRADING_GENERATION":
            if (
                value.get("recovery_kind") != "R7_REDIS_TRANSPORT_RECOVERY"
                or value.get("owner") != "69893dc7b7c647f49967387e7efca9fb"
                or not isinstance(value.get("generation"), dict)
                or value["generation"].get("name")
                != "kairos-epoch-69893dc7b7c6-serve-r7"
                or value["generation"].get("graceful_restart_proven") is not True
                or not isinstance(value.get("completed_at_utc"), str)
                or value.get("trading_started") is not False
                or any(
                    value.get(flag) is not False
                    for flag in ("PAPER_QUALIFIED", "ALPHA_READY", "LIVE_READY")
                )
                or value.get("STRATEGY_POLICY") != "REJECT_ALL"
            ):
                raise NotifierError("SOURCE_RECEIPT_INVALID")
            state = result
            observed_at = _timestamp_ms(value.get("completed_at_utc"))
            recovery_kind = value["recovery_kind"]
        elif result == "FAILED_CLOSED":
            if (
                value.get("automatic_retry") is not False
                or value.get("trading_started") is not False
            ):
                raise NotifierError("SOURCE_RECEIPT_INVALID")
            state = result
            # Failure documents have no producer timestamp; the signed owner
            # binding supplies the reviewed observation time. Historic R7
            # failure files without a producer revision remain inadmissible;
            # caller-provided binding metadata cannot supply provenance.
            observed_at = None
            recovery_kind = None
        else:
            raise NotifierError("SOURCE_RECEIPT_INVALID")
        producer = value.get("source_revision")
        if not isinstance(producer, str) or not _HEX40.fullmatch(producer):
            raise NotifierError(
                "SOURCE_FAILURE_REVISION_REQUIRED"
                if result == "FAILED_CLOSED"
                else "SOURCE_RECEIPT_INVALID"
            )
        return (
            feed.SourceEvent(
                source=source,
                source_state=state,
                source_key_sha256=receipt_hash,
                observed_at_ms=observed_at if observed_at is not None else 0,
                recovery_kind=recovery_kind,
            ),
            producer,
        )
    raise NotifierError("SOURCE_NOT_ADMITTED")


def _binding_event(
    binding_bytes: bytes,
    receipt_bytes: bytes,
    *,
    binding_sha256: str,
    meta_revision: str,
    verify_binding: Callable[[bytes, bytes], bool],
    binding_signature: bytes,
) -> DispatchIntent | None:
    if (
        not _HEX64.fullmatch(binding_sha256)
        or hashlib.sha256(binding_bytes).hexdigest() != binding_sha256
        or not 0 < len(binding_bytes) <= MAX_BINDING_BYTES
        or not 0 < len(receipt_bytes) <= MAX_RECEIPT_BYTES
        or not 0 < len(binding_signature) <= MAX_SIGNATURE_BYTES
        or not callable(verify_binding)
        or not _HEX40.fullmatch(meta_revision)
    ):
        raise NotifierError("SIGNED_SOURCE_BINDING_REQUIRED")
    try:
        binding = _json(binding_bytes)
    except (UnicodeDecodeError, ValueError):
        raise NotifierError("SOURCE_BINDING_INVALID") from None
    if (
        not isinstance(binding, dict)
        or set(binding) != _BINDING_FIELDS
        or type(binding.get("schema_version")) is not int
        or binding.get("schema_version") != 1
        or binding.get("kind") != "kairos.ops-source-notifier-binding.v1"
        or binding.get("source")
        not in {feed.Source.VENUE_OBSERVATION.value, feed.Source.BACKUP_RESTORE.value}
        or not isinstance(binding.get("receipt_locator"), str)
        or binding.get("meta_revision") != meta_revision
        or binding.get("notifier_sha256") != _module_sha256()
        or not _HEX64.fullmatch(binding.get("receipt_sha256", ""))
        or not _HEX64.fullmatch(binding.get("source_key_sha256", ""))
    ):
        raise NotifierError("SOURCE_BINDING_MISMATCH")
    source = feed.Source(binding["source"])
    namespace = _NAMESPACES[source]
    receipt_hash = hashlib.sha256(receipt_bytes).hexdigest()
    if (
        binding.get("namespace") != namespace
        or binding.get("receipt_sha256") != receipt_hash
        or binding.get("source_key_sha256") != receipt_hash
        or verify_binding(binding_bytes, binding_signature) is not True
    ):
        raise NotifierError("SOURCE_BINDING_MISMATCH")
    event, producer = _receipt_event(source, receipt_bytes)
    expected_time = binding.get("observed_at_ms")
    if event.observed_at_ms == 0 and source is feed.Source.BACKUP_RESTORE:
        if type(expected_time) is not int or expected_time < 0:
            raise NotifierError("SOURCE_BINDING_MISMATCH")
        event = feed.SourceEvent(
            source=event.source,
            source_state=event.source_state,
            source_key_sha256=event.source_key_sha256,
            observed_at_ms=expected_time,
            recovery_kind=event.recovery_kind,
        )
    producer_fingerprint = binding.get("producer_fingerprint")
    producer_matches = (
        producer == producer_fingerprint
        if producer is not None
        else isinstance(producer_fingerprint, str)
        and bool(_HEX40.fullmatch(producer_fingerprint))
    )
    if (
        binding.get("source_state") != event.source_state
        or binding.get("observed_at_ms") != event.observed_at_ms
        or binding.get("recovery_kind") != event.recovery_kind
        or not producer_matches
    ):
        raise NotifierError("SOURCE_BINDING_MISMATCH")
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    try:
        candidate = feed.normalize_event(
            event,
            now_ms=now_ms,
            freshness_bound_ms=MAX_FRESHNESS_MS,
        )
    except feed.FeedError as error:
        raise NotifierError(str(error)) from None
    if candidate is None or not candidate.enabled:
        return None
    text = (
        f"[Kairos {candidate.source.value}/{candidate.severity.value}] "
        f"{candidate.message} Trading remains disabled."
    )
    if len(text.encode("utf-8")) > 512:
        raise NotifierError("NOTICE_LIMIT")
    event_id = hashlib.sha256(
        f"ops-source-notifier-v1|{namespace}|{candidate.event_id}".encode("ascii")
    ).hexdigest()
    return DispatchIntent(
        event_id=event_id,
        source=candidate.source,
        source_state=event.source_state,
        state=candidate.state,
        severity=candidate.severity,
        namespace=namespace,
        binding_sha256=binding_sha256,
        source_receipt_sha256=receipt_hash,
        text=text,
        observed_at_ms=candidate.observed_at_ms,
    )


class SourceJournal:
    """Per-source create-only journal using pinned R5 filesystem primitives."""

    def __init__(self, path: Path, namespace: str, helpers: Any, c: Any, delivery: Any):
        if namespace not in set(_NAMESPACES.values()):
            raise NotifierError("JOURNAL_NAMESPACE_INVALID")
        self.path = path
        self.namespace = namespace
        self.helpers = helpers
        self.c = c
        self.delivery = delivery
        self.lease_path = path.with_name(path.name + ".lock")
        self._error = helpers.R5Error
        self._base = helpers.R5Journal

    def _verify(self, path: Path) -> bytes:
        self.delivery._no_reparse(path)
        self.delivery._private_acl(path)
        try:
            return self.helpers._read(path, MAX_JOURNAL_BYTES)
        except self._error as error:
            raise NotifierError("JOURNAL_INVALID") from error

    @contextmanager
    def locked(self):
        try:
            with self._base.locked(self):
                yield
        except self._error as error:
            raise NotifierError("JOURNAL_LOCKED_OR_INVALID") from error

    def read(self, *, allow_pending: bool = False) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        raw = self._verify(self.path)
        if not raw or not raw.endswith(b"\n") or len(raw) > MAX_JOURNAL_BYTES:
            raise NotifierError("JOURNAL_INVALID")
        try:
            rows = [_json(line) for line in raw.splitlines()]
            if (
                not rows
                or len(rows) > MAX_JOURNAL_RECORDS
                or any(
                    not isinstance(row, dict)
                    or type(row.get("seq")) is not int
                    or row["seq"] != index
                    for index, row in enumerate(rows)
                )
            ):
                raise ValueError("sequence")
            baseline = rows[0]
            if set(baseline) != {
                "schema_version",
                "seq",
                "kind",
                "namespace",
                "schema_sha256",
            } or baseline != {
                "schema_version": 1,
                "seq": 0,
                "kind": "baseline",
                "namespace": self.namespace,
                "schema_sha256": _JOURNAL_SCHEMA_SHA256,
            }:
                raise ValueError("baseline")
            pending: dict[str, Any] | None = None
            seen: set[str] = set()
            for row in rows[1:]:
                row_source = None
                if isinstance(row.get("source"), str):
                    try:
                        row_source = feed.Source(row["source"])
                    except ValueError:
                        pass
                expected_event_id = None
                if (
                    row_source is not None
                    and isinstance(row.get("source_receipt_sha256"), str)
                    and isinstance(row.get("state"), str)
                ):
                    feed_event_id = hashlib.sha256(
                        (
                            f"ops-feed-v1|{row_source.value}|{row['source_receipt_sha256']}|{row['state']}"
                        ).encode("ascii")
                    ).hexdigest()
                    expected_event_id = hashlib.sha256(
                        f"ops-source-notifier-v1|{_NAMESPACES[row_source]}|{feed_event_id}".encode(
                            "ascii"
                        )
                    ).hexdigest()
                if (
                    set(row)
                    == {
                        "schema_version",
                        "seq",
                        "kind",
                        "event_id",
                        "namespace",
                        "source",
                        "source_state",
                        "state",
                        "binding_sha256",
                        "source_receipt_sha256",
                        "observed_at_ms",
                    }
                    and row.get("schema_version") == 1
                    and row.get("kind") == "send_reserved"
                    and _HEX64.fullmatch(row.get("event_id", ""))
                    and _HEX64.fullmatch(row.get("binding_sha256", ""))
                    and _HEX64.fullmatch(row.get("source_receipt_sha256", ""))
                    and row_source is not None
                    and row.get("namespace")
                    == _NAMESPACES[row_source]
                    == self.namespace
                    and row.get("source_state") in feed._SOURCE_STATES[row_source]
                    and row.get("state") in {state.value for state in feed.State}
                    and row.get("event_id") == expected_event_id
                    and type(row.get("observed_at_ms")) is int
                    and pending is None
                    and row["event_id"] not in seen
                ):
                    pending = row
                    seen.add(row["event_id"])
                elif (
                    pending is not None
                    and set(row)
                    == {
                        "schema_version",
                        "seq",
                        "kind",
                        "event_id",
                        "result",
                        "message_id",
                    }
                    and row.get("schema_version") == 1
                    and row.get("kind") == "send_outcome"
                    and row.get("event_id") == pending["event_id"]
                    and row.get("result") in {"accepted", "unknown"}
                    and (
                        (
                            row.get("result") == "accepted"
                            and type(row.get("message_id")) is int
                            and row["message_id"] > 0
                        )
                        or (
                            row.get("result") == "unknown"
                            and row.get("message_id") is None
                        )
                    )
                ):
                    pending = None
                else:
                    raise ValueError("event")
            if pending is not None and not allow_pending:
                raise NotifierError("SEND_OUTCOME_UNKNOWN")
            return rows
        except NotifierError:
            raise
        except Exception:  # noqa: BLE001 -- hostile journal bytes/errors collapse to one safe category.
            raise NotifierError("JOURNAL_INVALID") from None

    def _append(self, record: dict[str, Any]) -> None:
        encoded = _canonical(record) + b"\n"
        if len(encoded) > MAX_RECORD_BYTES:
            raise NotifierError("JOURNAL_RECORD_LIMIT")
        try:
            exists = self.path.exists()
            if exists:
                current = self._verify(self.path)
                if len(current) + len(encoded) > MAX_JOURNAL_BYTES:
                    raise NotifierError("JOURNAL_BYTE_LIMIT")
                rows = self.read(allow_pending=record.get("kind") == "send_outcome")
                if len(rows) >= MAX_JOURNAL_RECORDS:
                    raise NotifierError("JOURNAL_RECORD_LIMIT")
            elif len(encoded) > MAX_JOURNAL_BYTES:
                raise NotifierError("JOURNAL_BYTE_LIMIT")
            if record.get("kind") == "send_reserved":
                guard = self.path.with_name(
                    self.path.name + "." + record["event_id"] + ".guard"
                )
                self.helpers._write_new(
                    guard,
                    _canonical(
                        {"event_id": record["event_id"], "namespace": self.namespace}
                    ),
                    self.c,
                    self.delivery,
                )
            if exists:
                descriptor = os.open(
                    self.path,
                    os.O_WRONLY
                    | os.O_APPEND
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_BINARY", 0),
                )
            else:
                descriptor = os.open(
                    self.path,
                    os.O_CREAT
                    | os.O_EXCL
                    | os.O_WRONLY
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_BINARY", 0),
                    0o600,
                )
            with os.fdopen(descriptor, "ab") as stream:
                if stream.write(encoded) != len(encoded):
                    raise NotifierError("JOURNAL_WRITE_FAILED")
                stream.flush()
                os.fsync(stream.fileno())
            if not exists:
                self.c._set_exact_file_acl(self.path)
            self.delivery._no_reparse(self.path)
            self.delivery._private_acl(self.path)
        except NotifierError:
            raise
        except Exception:  # noqa: BLE001 -- filesystem failures are intentionally sanitized at the journal boundary.
            raise NotifierError("JOURNAL_WRITE_FAILED") from None

    def reserve(self, intent: DispatchIntent) -> None:
        rows = self.read(allow_pending=True) if self.path.exists() else []
        if not rows:
            self._append(
                {
                    "schema_version": 1,
                    "seq": 0,
                    "kind": "baseline",
                    "namespace": self.namespace,
                    "schema_sha256": _JOURNAL_SCHEMA_SHA256,
                }
            )
            rows = self.read()
        if (
            rows[0].get("namespace") != intent.namespace
            or self.namespace != intent.namespace
        ):
            raise NotifierError("JOURNAL_NAMESPACE_MISMATCH")
        if any(row.get("event_id") == intent.event_id for row in rows[1:]):
            raise NotifierError("EVENT_ALREADY_CLAIMED_NO_RESEND")
        guard = self.path.with_name(self.path.name + "." + intent.event_id + ".guard")
        if guard.exists() or guard.is_symlink():
            raise NotifierError("UNKNOWN_RESERVATION_NO_RESEND")
        self._append(
            {
                "schema_version": 1,
                "seq": len(rows),
                "kind": "send_reserved",
                "event_id": intent.event_id,
                "namespace": intent.namespace,
                "source": intent.source.value,
                "source_state": intent.source_state,
                "state": intent.state.value,
                "binding_sha256": intent.binding_sha256,
                "source_receipt_sha256": intent.source_receipt_sha256,
                "observed_at_ms": intent.observed_at_ms,
            }
        )

    def finish(
        self, intent: DispatchIntent, *, result: str, message_id: int | None
    ) -> None:
        rows = self.read(allow_pending=True)
        if (
            not rows
            or rows[-1].get("kind") != "send_reserved"
            or rows[-1].get("event_id") != intent.event_id
        ):
            raise NotifierError("JOURNAL_PENDING_EVENT_MISMATCH")
        self._append(
            {
                "schema_version": 1,
                "seq": len(rows),
                "kind": "send_outcome",
                "event_id": intent.event_id,
                "result": result,
                "message_id": message_id,
            }
        )


def dispatch_once(
    intent: DispatchIntent,
    *,
    journal: SourceJournal,
    prepare_transport: Callable[[], Any],
    chat_id: int = OPERATIONAL_CHAT_ID,
) -> dict[str, Any]:
    """Preflight sender, durably reserve, then make at most one protected send."""
    if intent.source not in {feed.Source.VENUE_OBSERVATION, feed.Source.BACKUP_RESTORE}:
        raise NotifierError("BUSINESS_SOURCE_MUTED")
    if (
        not intent.text
        or len(intent.text.encode("utf-8")) > 512
        or chat_id != OPERATIONAL_CHAT_ID
    ):
        raise NotifierError("FIXED_NOTICE_AND_ROUTE_REQUIRED")
    with journal.locked():
        rows = journal.read(allow_pending=True) if journal.path.exists() else []
        if rows and rows[-1].get("kind") == "send_reserved":
            raise NotifierError("SEND_OUTCOME_UNKNOWN")
        if any(row.get("event_id") == intent.event_id for row in rows[1:]):
            raise NotifierError("EVENT_ALREADY_CLAIMED_NO_RESEND")
        try:
            transport = prepare_transport()
        except Exception:  # noqa: BLE001 -- protected-sender preflight errors are sanitized before any reservation.
            raise NotifierError("SENDER_PREFLIGHT_FAILED_NO_SEND") from None
        journal.reserve(intent)
        message_id = None
        result = "unknown"
        try:
            response = transport.call(
                "sendMessage",
                {
                    "chat_id": OPERATIONAL_CHAT_ID,
                    "text": intent.text,
                    "protect_content": True,
                },
            )
            if (
                isinstance(response, dict)
                and type(response.get("message_id")) is int
                and response["message_id"] > 0
                and isinstance(response.get("chat"), dict)
                and type(response["chat"].get("id")) is int
                and response["chat"]["id"] == OPERATIONAL_CHAT_ID
            ):
                result, message_id = "accepted", response["message_id"]
        except Exception:  # noqa: BLE001 -- response uncertainty must be latched without logging transport details.
            result, message_id = "unknown", None
        try:
            journal.finish(intent, result=result, message_id=message_id)
        except NotifierError:
            return {
                "status": "SEND_OUTCOME_UNKNOWN",
                "event_id": intent.event_id,
                "send_attempts": 1,
            }
        return {
            "status": "TRANSPORT_ACCEPTED"
            if result == "accepted"
            else "SEND_OUTCOME_UNKNOWN",
            "event_id": intent.event_id,
            "send_attempts": 1,
            "message_id": message_id,
            "trading_authority": False,
        }


def _git(repo: Path, *args: str) -> str:
    executable = Path("C:/Program Files/Git/cmd/git.exe")
    try:
        result = subprocess.run(
            [str(executable), "-C", str(repo), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        raise NotifierError("SIGNED_SOURCE_ADMISSION_FAILED") from None
    if result.returncode:
        raise NotifierError("SIGNED_SOURCE_ADMISSION_FAILED")
    return result.stdout.decode("ascii", "strict").strip()


def _git_blob(repo: Path, relative_path: str) -> bytes:
    executable = Path("C:/Program Files/Git/cmd/git.exe")
    try:
        result = subprocess.run(
            [str(executable), "-C", str(repo), "show", f"HEAD:{relative_path}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise NotifierError("SIGNED_SOURCE_ADMISSION_FAILED") from None
    if result.returncode:
        raise NotifierError("SIGNED_SOURCE_ADMISSION_FAILED")
    return result.stdout


def _verify_signed_main(repo: Path) -> str:
    branch = _git(repo, "branch", "--show-current")
    fields = _git(repo, "show", "-s", "--format=%H %G? %GF", "HEAD").split()
    origin = _git(repo, "rev-parse", "origin/main")
    is_meta = repo.resolve(strict=True) == META_ROOT.resolve(strict=True)
    if is_meta:
        dirty = _git(
            repo,
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            *_META_EXECUTED_SOURCES,
        )
    else:
        dirty = _git(repo, "status", "--porcelain", "--untracked-files=all")
    if (
        branch != "main"
        or len(fields) != 3
        or fields[1:] != ["G", SIGNER]
        or origin != fields[0]
        or dirty
        or not _HEX40.fullmatch(fields[0])
    ):
        raise NotifierError("SIGNED_CLEAN_MAIN_REQUIRED")
    if is_meta:
        for relative_path in _META_EXECUTED_SOURCES:
            try:
                working = (repo / Path(*relative_path.split("/"))).read_bytes()
            except OSError:
                raise NotifierError("SIGNED_SOURCE_ADMISSION_FAILED") from None
            if working != _git_blob(repo, relative_path):
                raise NotifierError("SIGNED_SOURCE_ADMISSION_FAILED")
    return fields[0]


def _trusted_helpers() -> tuple[Any, Any, Any, Any]:
    for relative in ("development/__init__.py", "development/ops_alerts/__init__.py"):
        namespace_init = META_ROOT / Path(*relative.split("/"))
        if namespace_init.exists() or namespace_init.is_symlink():
            raise NotifierError("META_NAMESPACE_PACKAGE_BLOCKED")
    if str(META_ROOT) not in sys.path:
        sys.path.insert(0, str(META_ROOT))
    if str(DEPLOY_ROOT) not in sys.path:
        sys.path.insert(0, str(DEPLOY_ROOT))
    try:
        from development.ops_alerts import runtime_status_r6_notifier as r6

        expected = META_ROOT / "development/ops_alerts/runtime_status_r6_notifier.py"
        if Path(r6.__file__).resolve(strict=True) != expected.resolve(strict=True):
            raise NotifierError("SIGNED_SOURCE_ADMISSION_FAILED")
        helpers = r6._r5_helpers()
        c, delivery = helpers._continuation()
        return r6, helpers, c, delivery
    except NotifierError:
        raise
    except Exception:  # noqa: BLE001 -- imported signed-helper failures are redacted at this boundary.
        raise NotifierError("SIGNED_HELPERS_UNAVAILABLE") from None


def _receipt_path(source: feed.Source, locator: str) -> Path:
    if source is feed.Source.VENUE_OBSERVATION and _VENUE_LOCATOR.fullmatch(locator):
        return VENUE_ROOT / Path(*locator.split("/"))
    if source is feed.Source.BACKUP_RESTORE and _BACKUP_LOCATOR.fullmatch(locator):
        return BACKUP_ROOT / Path(*locator.split("/"))
    raise NotifierError("SOURCE_RECEIPT_PATH_NOT_ALLOWLISTED")


def _verify_producer(
    source: feed.Source, producer: str | None, deploy_revision: str
) -> None:
    if source is feed.Source.VENUE_OBSERVATION:
        observer_path = META_ROOT / "development/ops_alerts/evedex_venue_observer.py"
        try:
            raw = observer_path.read_bytes()
        except OSError:
            raise NotifierError("PRODUCER_SOURCE_UNAVAILABLE") from None
        if not isinstance(producer, str) or hashlib.sha256(raw).hexdigest() != producer:
            raise NotifierError("PRODUCER_SOURCE_MISMATCH")
        return
    if not isinstance(producer, str) or not _HEX40.fullmatch(producer):
        raise NotifierError("PRODUCER_REVISION_UNTRUSTED")
    fields = _git(DEPLOY_ROOT, "show", "-s", "--format=%H %G? %GF", producer).split()
    if fields != [producer, "G", SIGNER]:
        raise NotifierError("PRODUCER_REVISION_UNTRUSTED")
    _git(DEPLOY_ROOT, "merge-base", "--is-ancestor", producer, deploy_revision)


def _admit_files(
    binding_path: Path,
    expected_sha256: str,
    meta_revision: str,
    deploy_revision: str,
    helpers: Any,
    c: Any,
    delivery: Any,
) -> DispatchIntent | None:
    if (
        binding_path.parent != BINDING_ROOT
        or binding_path.suffix != ".json"
        or binding_path.stem != expected_sha256
    ):
        raise NotifierError("EXACT_BINDING_PATH_REQUIRED")
    delivery._no_reparse(PRIVATE_ROOT)
    delivery._private_acl(PRIVATE_ROOT)
    delivery._no_reparse(BINDING_ROOT)
    delivery._private_acl(BINDING_ROOT)
    raw = helpers._read_private(
        binding_path, maximum=MAX_BINDING_BYTES, delivery=delivery
    )
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise NotifierError("SOURCE_BINDING_HASH_MISMATCH")
    signature = helpers._read_private(
        binding_path.with_suffix(".json.asc"),
        maximum=MAX_SIGNATURE_BYTES,
        delivery=delivery,
    )
    signature_path = binding_path.with_suffix(".json.asc")
    # Authenticate the bounded binding before it can select even an allowlisted
    # receipt path.  The later callback repeats this check and verifies that
    # neither file changed between admission and event construction.
    helpers._verify_signature(binding_path, signature_path)
    if (
        helpers._read_private(
            binding_path, maximum=MAX_BINDING_BYTES, delivery=delivery
        )
        != raw
        or helpers._read_private(
            signature_path, maximum=MAX_SIGNATURE_BYTES, delivery=delivery
        )
        != signature
    ):
        raise NotifierError("SOURCE_BINDING_CHANGED")
    binding = _json(raw)
    if not isinstance(binding, dict) or set(binding) != _BINDING_FIELDS:
        raise NotifierError("SOURCE_BINDING_INVALID")
    source_value = binding.get("source")
    if source_value not in {
        feed.Source.VENUE_OBSERVATION.value,
        feed.Source.BACKUP_RESTORE.value,
    }:
        raise NotifierError("SOURCE_NOT_ADMITTED")
    source = feed.Source(source_value)
    receipt_path = _receipt_path(source, binding.get("receipt_locator", ""))
    delivery._no_reparse(receipt_path)
    delivery._private_acl(receipt_path)
    receipt_raw = helpers._read_private(
        receipt_path, maximum=MAX_RECEIPT_BYTES, delivery=delivery
    )
    if (
        helpers._read_private(
            receipt_path, maximum=MAX_RECEIPT_BYTES, delivery=delivery
        )
        != receipt_raw
    ):
        raise NotifierError("SOURCE_RECEIPT_CHANGED")
    event, producer = _receipt_event(source, receipt_raw)
    _verify_producer(source, producer, deploy_revision)
    if binding.get("source_key_sha256") != event.source_key_sha256:
        raise NotifierError("SOURCE_BINDING_MISMATCH")

    def verify_signed_binding(payload: bytes, signature: bytes) -> bool:
        if payload != raw or signature != helpers._read_private(
            signature_path, maximum=MAX_SIGNATURE_BYTES, delivery=delivery
        ):
            return False
        helpers._verify_signature(binding_path, signature_path)
        return (
            helpers._read_private(
                binding_path, maximum=MAX_BINDING_BYTES, delivery=delivery
            )
            == raw
            and helpers._read_private(
                signature_path, maximum=MAX_SIGNATURE_BYTES, delivery=delivery
            )
            == signature
        )

    return _binding_event(
        raw,
        receipt_raw,
        binding_sha256=expected_sha256,
        meta_revision=meta_revision,
        verify_binding=verify_signed_binding,
        binding_signature=signature,
    )


def _execute_once(binding_path: Path, binding_sha256: str) -> dict[str, Any]:
    meta_revision = _verify_signed_main(META_ROOT)
    deploy_revision = _verify_signed_main(DEPLOY_ROOT)
    r6, helpers, c, delivery = _trusted_helpers()
    binding_path = Path(binding_path)
    if binding_path != BINDING_ROOT / f"{binding_sha256}.json":
        raise NotifierError("EXACT_BINDING_PATH_REQUIRED")
    intent = _admit_files(
        binding_path,
        binding_sha256,
        meta_revision,
        deploy_revision,
        helpers,
        c,
        delivery,
    )
    if intent is None:
        return {
            "status": "MUTED_OR_NO_ALERT",
            "send_attempts": 0,
            "trading_authority": False,
        }
    namespace_root = JOURNAL_ROOT / intent.namespace
    delivery._no_reparse(JOURNAL_ROOT)
    namespace_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    delivery._no_reparse(namespace_root)
    delivery._private_acl(namespace_root)
    journal = SourceJournal(
        namespace_root / "events.jsonl", intent.namespace, helpers, c, delivery
    )
    return dispatch_once(
        intent,
        journal=journal,
        prepare_transport=lambda: helpers._prepare_transport(c, delivery),
        chat_id=r6.GROUP_ID,
    )


def plan() -> dict[str, object]:
    return {
        "status": "PLAN_ONLY",
        "network_calls": 0,
        "journal_writes": 0,
        "source_reads": 0,
        "business_categories_enabled": False,
        "automatic_retry": False,
        "trading_authority": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-once", action="store_true")
    parser.add_argument("--armed", action="store_true")
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--binding-sha256")
    args = parser.parse_args(argv)
    if not args.execute_once:
        print(json.dumps(plan(), sort_keys=True))
        return 0
    if (
        not args.armed
        or args.binding is None
        or not isinstance(args.binding_sha256, str)
    ):
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "error_category": "EXPLICIT_SIGNED_BINDING_AND_ARM_REQUIRED",
                }
            )
        )
        return 2
    try:
        result = _execute_once(args.binding, args.binding_sha256)
    except NotifierError as error:
        result = {
            "status": "BLOCKED",
            "error_category": error.category,
            "send_attempts": 0,
        }
    except Exception:  # noqa: BLE001 -- CLI boundary emits only a fixed category, never exception details.
        result = {
            "status": "BLOCKED",
            "error_category": "LOCAL_VALIDATION_FAILED",
            "send_attempts": 0,
        }
    print(json.dumps(result, sort_keys=True))
    return (
        0 if result.get("status") in {"TRANSPORT_ACCEPTED", "MUTED_OR_NO_ALERT"} else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
