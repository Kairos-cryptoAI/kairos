"""Offline, read-only adapter for typed operations-alert source events.

This module does not read source files, own a polling loop, write a journal, or
send notifications. A future controller may map verified source receipts to
the closed enums below, but admission to the pinned R6 send-once journal still
requires a separately reviewed source binding. In particular, an UNKNOWN
dispatch outcome remains latched at its producer; this adapter never retries.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000


class Source(StrEnum):
    VENUE_OBSERVATION = "venue_observation"
    CAMPAIGN = "campaign"
    RISK = "risk"
    CANDIDATE = "candidate"
    BACKUP_RESTORE = "backup_restore"


class State(StrEnum):
    VENUE_UNKNOWN = "venue_unknown_outcome"
    VENUE_MISSED = "venue_missed_slot"
    CAMPAIGN_STALE = "campaign_stale"
    CAMPAIGN_BUDGET_BLOCKED = "campaign_budget_blocked"
    CAMPAIGN_UNKNOWN = "campaign_unknown"
    RISK_REJECTED = "risk_rejected"
    CANDIDATE_VETO = "candidate_veto"
    CANDIDATE_DEFER = "candidate_defer"
    BACKUP_RESTORE_FAILED = "backup_restore_failed"
    BACKUP_RESTORE_SUCCEEDED = "backup_restore_succeeded"


class Severity(StrEnum):
    WARNING = "warning"
    CRITICAL = "critical"
    INFO = "info"


_BUSINESS_SOURCES = frozenset({Source.CAMPAIGN, Source.RISK, Source.CANDIDATE})
_DEFAULT_ENABLED = frozenset({Source.VENUE_OBSERVATION, Source.BACKUP_RESTORE})


@dataclass(frozen=True, slots=True)
class SourceEvent:
    """Small verified projection; raw source payloads are deliberately absent."""

    source: Source
    source_state: str
    source_key_sha256: str
    observed_at_ms: int
    recovery_kind: str | None = None


@dataclass(frozen=True, slots=True)
class AlertCandidate:
    event_id: str
    transition: str
    source: Source
    state: State
    severity: Severity
    observed_at_ms: int
    message: str
    enabled: bool
    automatic_resend: bool = False
    dispatch_state: str = "NOT_DISPATCHED"


class FeedError(ValueError):
    """Invalid or unsupported typed source projection."""


# Source values are intentionally the exact finite states present in the
# accepted observer, campaign outcome, risk, candidate-review, and recovery
# contracts. No free-form status, reason, symbol, or payload is forwarded.
_MAPPING: dict[tuple[Source, str], tuple[State, Severity, str]] = {
    (Source.VENUE_OBSERVATION, "UNKNOWN_OUTCOME"): (
        State.VENUE_UNKNOWN,
        Severity.CRITICAL,
        "Public venue observation has an unresolved request outcome.",
    ),
    (Source.VENUE_OBSERVATION, "MISSED_RUN_DEADLINE"): (
        State.VENUE_MISSED,
        Severity.WARNING,
        "Public venue observation missed its bounded slot deadline.",
    ),
    (Source.CAMPAIGN, "STALE"): (
        State.CAMPAIGN_STALE,
        Severity.WARNING,
        "Research campaign source receipt is stale.",
    ),
    (Source.CAMPAIGN, "BUDGET_BLOCKED"): (
        State.CAMPAIGN_BUDGET_BLOCKED,
        Severity.WARNING,
        "Research campaign arm was blocked by its configured budget.",
    ),
    (Source.CAMPAIGN, "UNKNOWN"): (
        State.CAMPAIGN_UNKNOWN,
        Severity.CRITICAL,
        "Research campaign outcome remains unknown; no retry is authorized.",
    ),
    (Source.RISK, "REJECTED"): (
        State.RISK_REJECTED,
        Severity.WARNING,
        "Risk Manager rejected a validated-order request.",
    ),
    (Source.CANDIDATE, "VETO"): (
        State.CANDIDATE_VETO,
        Severity.INFO,
        "Research candidate review recorded a veto.",
    ),
    (Source.CANDIDATE, "DEFER"): (
        State.CANDIDATE_DEFER,
        Severity.INFO,
        "Research candidate review deferred a decision.",
    ),
    (Source.BACKUP_RESTORE, "FAILED_CLOSED"): (
        State.BACKUP_RESTORE_FAILED,
        Severity.CRITICAL,
        "Isolated backup/restore workflow failed closed.",
    ),
    (Source.BACKUP_RESTORE, "PASS_FRESH_BACKUP_TWO_ISOLATED_RESTORES"): (
        State.BACKUP_RESTORE_SUCCEEDED,
        Severity.INFO,
        "Fresh isolated backup and restore acceptance completed.",
    ),
    (Source.BACKUP_RESTORE, "PASS_NEW_NONTRADING_GENERATION"): (
        State.BACKUP_RESTORE_SUCCEEDED,
        Severity.INFO,
        "New non-trading recovery generation completed.",
    ),
}

_SOURCE_STATES = {
    Source.VENUE_OBSERVATION: frozenset({"UNKNOWN_OUTCOME", "MISSED_RUN_DEADLINE"}),
    # ResearchArmOutcomeV1.status. STALE is derived only when a caller supplies
    # an explicit freshness bound; its scheduler must provide that policy.
    Source.CAMPAIGN: frozenset(
        {
            "BASELINE",
            "NO_INTENT",
            "ALLOW",
            "VETO",
            "DEFER",
            "PROPOSAL",
            "CALL_FAILED",
            "SOURCE_MISSING",
            "EVALUATOR_FAILED",
            "MISSED",
            "LATE",
            "UNKNOWN",
            "BUDGET_BLOCKED",
            "STALE",
        }
    ),
    Source.RISK: frozenset({"REJECTED"}),
    # adaptive-review-output.v1 action; deliberately business-muted by default.
    Source.CANDIDATE: frozenset({"ALLOW", "VETO", "DEFER"}),
    Source.BACKUP_RESTORE: frozenset(
        {
            "FAILED_CLOSED",
            "PASS_FRESH_BACKUP_TWO_ISOLATED_RESTORES",
            "PASS_NEW_NONTRADING_GENERATION",
        }
    ),
}


def normalize_event(
    event: SourceEvent,
    *,
    now_ms: int,
    freshness_bound_ms: int,
    enabled_sources: frozenset[Source] = _DEFAULT_ENABLED,
) -> AlertCandidate | None:
    """Return a fixed, redacted alert candidate or ``None`` for non-alerts.

    Staleness is derived from the caller's bound, never from an implicit
    scheduler assumption. Business categories remain muted unless explicitly
    enabled. This function does not persist, reserve, or dispatch candidates.
    """
    if not isinstance(event, SourceEvent) or not isinstance(event.source, Source):
        raise FeedError("SOURCE_EVENT_TYPE_INVALID")
    if type(event.source_state) is not str:
        raise FeedError("SOURCE_STATE_UNSUPPORTED")
    if event.source_state not in _SOURCE_STATES[event.source]:
        raise FeedError("SOURCE_STATE_UNSUPPORTED")
    # The shared result name needs an exact recovery-kind binding.
    if (
        event.source is Source.BACKUP_RESTORE
        and event.source_state == "PASS_NEW_NONTRADING_GENERATION"
        and event.recovery_kind != "R7_REDIS_TRANSPORT_RECOVERY"
    ):
        raise FeedError("RECOVERY_KIND_UNSUPPORTED")
    if not isinstance(event.source_key_sha256, str) or not _SHA256.fullmatch(event.source_key_sha256):
        raise FeedError("SOURCE_KEY_INVALID")
    if any(type(value) is not int or value < 0 for value in (event.observed_at_ms, now_ms)):
        raise FeedError("TIMESTAMP_INVALID")
    if event.observed_at_ms > now_ms:
        raise FeedError("SOURCE_TIME_IN_FUTURE")
    if type(freshness_bound_ms) is not int or not 1 <= freshness_bound_ms <= _MAX_AGE_MS:
        raise FeedError("FRESHNESS_BOUND_INVALID")
    if type(enabled_sources) is not frozenset or any(
        not isinstance(source, Source) for source in enabled_sources
    ):
        raise FeedError("SOURCE_ENABLEMENT_INVALID")

    state_name = event.source_state
    age_ms = now_ms - event.observed_at_ms
    if age_ms > freshness_bound_ms and event.source is Source.CAMPAIGN:
        state_name = "STALE"
    elif age_ms > freshness_bound_ms:
        # Do not turn stale technical/restore evidence into a false recovery
        # or failure. A separately bound monitor owns source-age alerting.
        return None

    mapped = _MAPPING.get((event.source, state_name))
    if mapped is None:
        return None
    state, severity, message = mapped
    enabled = event.source in enabled_sources
    if event.source in _BUSINESS_SOURCES and event.source not in enabled_sources:
        enabled = False
    event_id = hashlib.sha256(
        f"ops-feed-v1|{event.source.value}|{event.source_key_sha256}|{state.value}".encode("ascii")
    ).hexdigest()
    return AlertCandidate(
        event_id=event_id,
        transition="firing",
        source=event.source,
        state=state,
        severity=severity,
        observed_at_ms=event.observed_at_ms,
        message=message,
        enabled=enabled,
    )


def source_admission_boundary() -> dict[str, object]:
    """Machine-readable declaration of what is and is not runtime-wired."""
    return {
        "mode": "OFFLINE_TYPED_FEED_ONLY",
        "reads_sources": False,
        "writes_journal": False,
        "dispatches": False,
        "existing_r6_notifier_modified": False,
        "source_binding_required": True,
        "campaign_risk_candidate_enabled_by_default": False,
        "automatic_resend": False,
        "unknown_outcome_policy": "PRESERVE_PRODUCER_LATCH_NO_RETRY",
    }
