"""Fixed causal-source control, without outcomes, tuning, models or trading authority.

This deliberately tests source/clock selection, not a directional alpha filter.
Receipt hashes cannot establish the truth of missing news or macro payloads.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .engine import entry_time

if TYPE_CHECKING:
    from .system import SystemSlot

FILTER_POLICY = "CAUSAL_REQUIRED_SOURCES_V1"
FILTER_POLICY_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "policy": FILTER_POLICY,
            "candidate": "UNCHANGED",
            "source_rule": "ALL_REQUIRED_AND_SUPPLIED_AVAILABLE_FRESH_AT_OBSERVATION_AND_QUOTE",
            "missing_rule": "DEFER",
            "outcome_input": "NONE",
            "quota": "NONE",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()


@dataclass(frozen=True)
class CausalFilterObservation:
    """Caller-attested filter timing; never a model response or DB authenticity proof."""

    slot_id: str
    candidate_id: str
    context_sha256: str
    requested_ms: int
    observed_ms: int
    evidence_kind: str
    policy_sha256: str = FILTER_POLICY_SHA256

    def __post_init__(self) -> None:
        for identity in (self.slot_id, self.candidate_id, self.context_sha256, self.policy_sha256):
            if type(identity) is not str or re.fullmatch("[0-9a-f]{64}", identity) is None:
                raise ValueError("canonical filter identity required")
        if self.policy_sha256 != FILTER_POLICY_SHA256:
            raise ValueError("exact fixed causal filter policy required")
        if (
            type(self.requested_ms) is not int
            or type(self.observed_ms) is not int
            or self.requested_ms < 0
            or self.observed_ms < self.requested_ms
        ):
            raise ValueError("ordered nonnegative filter clocks required")
        if self.evidence_kind not in {"TEST_FIXTURE", "OBSERVED_POINT_IN_TIME"}:
            raise ValueError("explicit filter evidence kind required")


def causal_filter_decision(
    slot: SystemSlot, observation: CausalFilterObservation, mode: str, *, fixture_only: bool
) -> dict[str, Any]:
    """Derive ALLOW/DEFER only from unchanged identity and causal source clocks.

    No future bars, trade ledger, standalone PnL, daily quota, inferred Macro
    direction or caller-supplied profitability score enters this function.
    """
    if type(fixture_only) is not bool or not isinstance(observation, CausalFilterObservation):
        raise ValueError("explicit filter observation/mode required")
    # Frozen dataclasses are not a trust boundary against unchecked construction.
    # Revalidate before using clocks or claiming this exact fixed policy.
    observation.__post_init__()
    if (observation.evidence_kind == "TEST_FIXTURE") != fixture_only:
        raise ValueError("filter fixture and observation evidence cannot be mixed or relabelled")
    if (
        slot.state != "CANDIDATE"
        or slot.candidate is None
        or observation.slot_id != slot.matched.slot_id
        or observation.candidate_id != slot.candidate.intent_id
        or observation.context_sha256 != slot.context_sha256
        or observation.requested_ms < slot.matched.context_cut_ms
    ):
        raise ValueError("filter must bind exact candidate, slot and causal context")
    candidate = slot.candidate
    quote_ms = entry_time(candidate, observation.observed_ms, mode)
    reason = "CAUSAL_CONTEXT_READY"
    if any(s.required and s.availability == "UNAVAILABLE" for s in slot.sources):
        reason = "REQUIRED_SOURCE_UNAVAILABLE"
    elif not slot.context_ready_at(observation.observed_ms):
        reason = "STALE_CONTEXT_AT_FILTER_OBSERVATION"
    elif quote_ms is None:
        reason = "NO_ELIGIBLE_QUOTE_WITHIN_ORIGINAL_LIFETIME"
    elif not slot.context_ready_at(quote_ms):
        reason = "STALE_CONTEXT_AT_QUOTE"
    return {
        "slot_id": slot.matched.slot_id,
        "candidate_id": candidate.intent_id,
        "context_sha256": slot.context_sha256,
        "policy": FILTER_POLICY,
        "policy_sha256": FILTER_POLICY_SHA256,
        "requested_ms": observation.requested_ms,
        "observed_ms": observation.observed_ms,
        "quote_ms": quote_ms,
        "disposition": "ALLOW" if reason == "CAUSAL_CONTEXT_READY" else "DEFER",
        "reason": reason,
        "evidence_kind": observation.evidence_kind,
        "scope": "CAUSAL_SOURCE_CONTROL_NOT_DIRECTIONAL_ALPHA_OR_PRODUCTION_DETECTION",
        "model_calls": 0,
    }
