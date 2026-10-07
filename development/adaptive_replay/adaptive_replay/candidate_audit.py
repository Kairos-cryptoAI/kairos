"""Post-replay candidate diagnostics; never a selector or attributable alpha claim."""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .system import SystemSlot


def _unique(rows: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = row.get(key)
        if not isinstance(identity, str) or not identity or identity in indexed:
            raise ValueError(f"missing or duplicate {label} identity")
        indexed[identity] = row
    return indexed


def _path_index(
    arm: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    events = arm.get("events", [])
    trades = arm.get("trades", [])
    economics = arm.get("economic_results")
    if not isinstance(events, list) or not isinstance(trades, list):
        raise ValueError("arm events and trades must be lists")
    entry_rows = [row for row in events if row.get("kind") == "ENTRY"]
    reject_rows = [row for row in events if row.get("kind") == "REJECT"]
    entries = _unique(entry_rows, "intent_id", "entry intent")
    rejects = _unique(reject_rows, "intent_id", "rejection intent")
    if set(entries) & set(rejects):
        raise ValueError("intent cannot be both entered and rejected")
    closed = _unique(trades, "intent_id", "closed trade")
    unresolved_rows = (
        economics.get("terminal_unresolved_positions", []) if isinstance(economics, dict) else []
    )
    if not isinstance(unresolved_rows, list):
        raise ValueError("unresolved positions must be a list")
    unresolved = _unique(unresolved_rows, "intent_id", "unresolved position")
    if set(closed) & set(unresolved):
        raise ValueError("conflicting execution identities")
    if set(closed) - set(entries) or set(unresolved) - set(entries):
        raise ValueError("closed and unresolved positions must have entry events")
    for trade in closed.values():
        net = trade.get("net_pnl_usd")
        if isinstance(net, bool) or not isinstance(net, (int, float)) or not math.isfinite(net):
            raise ValueError("closed trade requires finite net PnL")
    return entries, rejects, {**closed, **unresolved}


def _selection(decision: dict[str, Any] | None, decision_ms: int) -> dict[str, Any]:
    if decision is None:
        return {
            "disposition": "MISSING_DECISION",
            "retained_for_replay": None,
            "observed_ms": None,
            "delay_ms": None,
            "cost_usd": None,
            "no_call_reason": None,
        }
    disposition = decision.get("disposition")
    retained = decision.get("retained_for_replay")
    observed = decision.get("observed_ms")
    cost = decision.get("cost_usd")
    if not isinstance(disposition, str) or type(retained) is not bool:
        raise ValueError("decision disposition and retained flag required")
    if observed is not None and (type(observed) is not int or observed < decision_ms):
        raise ValueError("decision observation clock predates candidate")
    if cost is not None and (
        isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0
    ):
        raise ValueError("finite nonnegative decision cost or null required")
    return {
        "disposition": disposition,
        "retained_for_replay": retained,
        "observed_ms": observed,
        "delay_ms": observed - decision_ms if observed is not None else None,
        "cost_usd": cost,
        "no_call_reason": decision.get("no_call_reason"),
    }


def build_candidate_audit(
    slots: tuple[SystemSlot, ...],
    arms: dict[str, dict[str, Any]],
    decisions: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Compare candidate-level selection with baseline outcomes after replay.

    Baseline trade labels are diagnostics only. Independent-account PnL remains
    the sole economic comparison; this function does not select or gate trades.
    """
    if not isinstance(slots, tuple) or not isinstance(arms, dict) or not isinstance(decisions, dict):
        raise ValueError("immutable slots and explicit arm/decision mappings required")
    slot_ids = [slot.matched.slot_id for slot in slots]
    if len(set(slot_ids)) != len(slot_ids):
        raise ValueError("duplicate slot identity")
    baseline = arms.get("strategy_only")
    if not isinstance(baseline, dict):
        raise ValueError("strategy_only arm required")
    candidate_slots = [slot for slot in slots if slot.state == "CANDIDATE"]
    candidate_ids = [slot.candidate.intent_id for slot in candidate_slots]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("duplicate baseline candidate identity")
    sources: dict[str, dict[str, int]] = {}
    for slot in slots:
        for source in slot.sources:
            bucket = sources.setdefault(
                source.kind,
                {"AVAILABLE": 0, "UNAVAILABLE": 0, "STALE_AT_DECISION": 0, "unavailable_reasons": {}},
            )
            bucket[source.availability] += 1
            if source.availability == "AVAILABLE" and not source.ready_at(slot.matched.decision_ms):
                bucket["STALE_AT_DECISION"] += 1
            elif source.availability == "UNAVAILABLE":
                why = source.reason or "UNSPECIFIED"
                bucket["unavailable_reasons"][why] = bucket["unavailable_reasons"].get(why, 0) + 1

    baseline_entries, baseline_rejects, baseline_open_or_closed = _path_index(baseline)
    base_economics = baseline.get("economic_results")
    baseline_complete = isinstance(base_economics, dict)
    path_names = [
        name for name in ("context_review", "deterministic_filter", "review_timing_control") if name in arms
    ]
    path_indexes = {name: _path_index(arms[name]) for name in path_names}
    for name in path_names:
        if name not in decisions or not isinstance(decisions[name], dict):
            raise ValueError(f"decisions required for {name}")
        candidate_slot_ids = {slot.matched.slot_id for slot in candidate_slots}
        if set(decisions[name]) - candidate_slot_ids:
            raise ValueError(f"decision does not reference a baseline candidate in {name}")

    rows: list[dict[str, Any]] = []
    counts: dict[str, Counter[str]] = {name: Counter() for name in path_names}
    for slot in candidate_slots:
        intent = slot.candidate
        assert intent is not None
        trade = baseline_open_or_closed.get(intent.intent_id)
        if not baseline_complete:
            baseline_status, baseline_net = "UNKNOWN", None
        elif intent.intent_id in baseline_rejects:
            baseline_status, baseline_net = "REJECTED", None
        elif intent.intent_id in baseline_entries:
            if trade is not None and "net_pnl_usd" in trade:
                baseline_status, baseline_net = "CLOSED", trade["net_pnl_usd"]
            elif trade is not None:
                baseline_status, baseline_net = "OPEN", None
            else:
                baseline_status, baseline_net = "UNKNOWN", None
        else:
            baseline_status, baseline_net = "NOT_FILLED", None
        path_rows = {}
        for name in path_names:
            arm = arms[name]
            entries, rejects, positions = path_indexes[name]
            selection = _selection(decisions[name].get(slot.matched.slot_id), slot.matched.decision_ms)
            if arm.get("economic_results") is None:
                status, reason = "UNKNOWN", "ARM_ECONOMICS_INCOMPLETE"
            elif selection["disposition"] == "MISSING_DECISION":
                status, reason = "UNKNOWN", "DECISION_OBSERVATION_MISSING"
            elif intent.intent_id in rejects:
                status, reason = "REJECTED", rejects[intent.intent_id].get("reason")
            elif intent.intent_id in entries:
                if intent.intent_id in positions and "net_pnl_usd" in positions[intent.intent_id]:
                    status, reason = "CLOSED", None
                elif intent.intent_id in positions:
                    status, reason = "OPEN", "TERMINAL_UNRESOLVED_POSITION"
                else:
                    status, reason = "UNKNOWN", "ENTRY_WITHOUT_CLOSE_OR_UNRESOLVED_RECORD"
            elif not selection["retained_for_replay"]:
                status, reason = "NOT_SELECTED", selection["disposition"]
            else:
                status, reason = "NOT_EXECUTED", "RETAINED_BUT_NO_ENTRY_OR_REJECTION"
            if status == "UNKNOWN":
                classification = "UNKNOWN"
            elif status == "NOT_SELECTED" and baseline_status == "CLOSED":
                if baseline_net > 0:
                    classification = "MISSED_BASELINE_WINNER"
                elif baseline_net < 0:
                    classification = "AVOIDED_BASELINE_LOSS"
                else:
                    classification = "OMITTED_BASELINE_FLAT"
            elif (
                status in {"REJECTED", "NOT_EXECUTED"}
                and selection["retained_for_replay"]
                and baseline_status == "CLOSED"
            ):
                classification = (
                    "NOT_FILLED_BASELINE_WINNER"
                    if baseline_net > 0
                    else "NOT_FILLED_BASELINE_LOSS"
                    if baseline_net < 0
                    else "NOT_FILLED_BASELINE_FLAT"
                )
            elif baseline_status != "CLOSED":
                classification = "NO_CLOSED_BASELINE_OUTCOME"
            else:
                classification = status
            counts[name][classification] += 1
            path_rows[name] = {
                **selection,
                "execution_status": status,
                "execution_reason": reason,
                "baseline_closed_net_usd": baseline_net,
                "classification": classification,
            }
        rows.append(
            {
                "candidate_id": intent.intent_id,
                "slot_id": slot.matched.slot_id,
                "symbol": slot.symbol,
                "decision_ms": slot.matched.decision_ms,
                "baseline_execution_status": baseline_status,
                "baseline_closed_net_usd": baseline_net,
                "paths": path_rows,
            }
        )
    return {
        "schema": "kairos.development.candidate-audit.v1",
        "scope": "DIAGNOSTIC_ONLY_NOT_SELECTOR",
        "evidence_status": "CONDITIONAL_POST_REPLAY_DIAGNOSTIC_NOT_ALPHA",
        "schedule_denominator": len(slots),
        "slot_states": dict(Counter(slot.state for slot in slots)),
        "baseline_candidate_denominator": len(candidate_slots),
        "source_coverage": sources,
        "candidates": rows,
        "classification_counts": {name: dict(counts[name]) for name in path_names},
        "entries_each_utc_day": {
            name: arms[name]["economic_results"].get("entries_each_utc_day")
            if isinstance(arms[name].get("economic_results"), dict)
            else None
            for name in ("strategy_only", *path_names)
        },
        "economic_attribution": "BASELINE_LABELS_ARE_DIAGNOSTIC; USE_INDEPENDENT_ARM_ECONOMICS",
    }
