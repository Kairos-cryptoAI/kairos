"""Successor R7 poll policy with one narrowly scoped stale-to-failed escalation."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import runtime_status_r7_notifier as _r7

__all__ = ["poll_once"]


def poll_once(
    *,
    source_admitter: Callable[[], dict[str, Any]] = _r7.admit_r7,
    observer: Callable[[Path, dict[str, Any]], str] | None = None,
    sender: Callable[[dict[str, Any]], bool] | None = None,
    root: Path | None = None,
    journal_factory: Callable[..., Any] = _r7.R7Journal,
) -> dict[str, Any]:
    """Poll once, escalating one accepted stale alert to failed-closed once.

    R7 reuses the R5 send guard, whose transition contract permits only
    ``firing`` and ``resolved``. Escalation therefore remains a firing event;
    its accepted state in the journal records that the higher alert was sent.
    """
    source = source_admitter()
    helpers, continuation, delivery = (
        source["helpers"],
        source["continuation"],
        source["delivery"],
    )
    root = _r7._profile_root(source, root)
    delivery._no_reparse(root)
    delivery._private_acl(root)
    journal = journal_factory(
        root / "events.jsonl", continuation, delivery, helpers, source["binding_sha256"]
    )
    with journal.locked():
        rows = journal.read()
        if not rows or rows[0].get("binding_sha256") != source["binding_sha256"]:
            raise _r7.R7Error("R7_BASELINE_REQUIRED_OR_BINDING_CHANGED")
        observed_state = (
            observer(_r7._status_path(source["binding"]), source)
            if observer
            else _r7.read_status(_r7._status_path(source["binding"]), source=source)
        )
        current = rows[0]["state"]
        active_state: str | None = None
        for row in rows[1:]:
            if row["kind"] == "observe":
                current = row["state"]
            elif row["kind"] == "send_outcome":
                if row["transition"] == "firing":
                    active_state = row["state"]
                elif row["transition"] == "resolved":
                    active_state = None

        active = active_state is not None
        escalation = (
            active_state == "running_stale" and observed_state == "failed_closed"
        )
        transition = None
        if escalation or (
            observed_state in _r7._ALERT_STATES
            and not active
            and current not in _r7._ALERT_STATES
        ):
            transition = "firing"
        elif observed_state == "running_fresh" and active:
            transition = "resolved"

        if transition and sender is None:
            sender = _r7._monitor_sender(source, root)
        if observed_state != current:
            journal._append(
                {
                    "schema_version": 1,
                    "seq": len(rows),
                    "kind": "observe",
                    "state": observed_state,
                }
            )
            rows = journal.read()
        if transition is None:
            return {
                "status": "quiet_or_unchanged",
                "state": observed_state,
                "send_attempts": 0,
            }

        event_id = hashlib.sha256(
            f"{source['binding_sha256']}|{len(rows)}|{transition}|{observed_state}".encode()
        ).hexdigest()
        event = {
            "event_id": event_id,
            "transition": transition,
            "state": observed_state,
            "text": (
                f"Kairos R7 technical status escalation: {observed_state}. "
                if escalation
                else f"Kairos R7 technical status: {observed_state}. "
            )
            + "Non-trading shadow runtime; technical monitoring only.",
        }
        journal._append(
            {
                "schema_version": 1,
                "seq": len(rows),
                "kind": "send_reserved",
                "event_id": event_id,
                "transition": transition,
                "state": observed_state,
            }
        )
        try:
            accepted = bool(sender(event)) if sender else False
        except Exception:  # noqa: BLE001 - ambiguous sends are never replayed.
            accepted = False
        journal._append(
            {
                "schema_version": 1,
                "seq": len(journal.read(allow_pending=True)),
                "kind": "send_outcome",
                "event_id": event_id,
                "transition": transition,
                "state": observed_state,
                "result": "accepted" if accepted else "unknown",
            }
        )
        if not accepted:
            raise _r7.R7Error("R7_SEND_OUTCOME_UNKNOWN")
        return {"status": "alert_accepted", "state": observed_state, "send_attempts": 1}
