"""Preparation boundary: absent model observations never become ALLOW/profit.

This is not a replacement for the existing Adaptive/LLM campaign evaluator.
It binds future recorded review receipts to the same causal development slot.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MatchedSlot:
    slot_id: str
    decision_ms: int
    context_cut_ms: int
    input_window_sha256: str
    candidate_id: str | None
    tape_sha256: str

    def __post_init__(self) -> None:
        if self.context_cut_ms != self.decision_ms or self.decision_ms < 0:
            raise ValueError("a matched context must stop at its decision, never future bars")
        for value in (self.slot_id, self.input_window_sha256, self.tape_sha256):
            if re.fullmatch("[0-9a-f]{64}", value) is None:
                raise ValueError("canonical matched SHA256 identity required")
        if self.candidate_id is not None and re.fullmatch("[0-9a-f]{64}", self.candidate_id) is None:
            raise ValueError("immutable candidate identity required")


@dataclass(frozen=True)
class ReviewReceipt:
    slot: MatchedSlot
    candidate_id: str
    requested_ms: int
    completed_ms: int
    captured_ms: int
    result: str
    provider: str
    model: str
    cost_usd: float
    evidence_kind: str
    point_in_time_news_sha256: str
    raw_response_sha256: str

    def __post_init__(self) -> None:
        if self.slot.candidate_id is None or self.candidate_id != self.slot.candidate_id:
            raise ValueError("review cannot invent or modify the matched candidate")
        if not self.slot.decision_ms <= self.requested_ms <= self.completed_ms <= self.captured_ms:
            raise ValueError("review clock cannot be backdated to force equal fills")
        if self.result not in {"ALLOW", "VETO", "DEFER"}:
            raise ValueError("invalid review disposition")
        if self.provider != "OPENAI" or not self.model.strip():
            raise ValueError("only an explicit approved OpenAI model observation")
        if not math.isfinite(self.cost_usd) or self.cost_usd < 0:
            raise ValueError("actual finite nonnegative cost required")
        if self.evidence_kind not in {"TEST_FIXTURE", "OBSERVED_POINT_IN_TIME"}:
            raise ValueError("explicit observed-versus-fixture provenance required")
        for value in (self.point_in_time_news_sha256, self.raw_response_sha256):
            if re.fullmatch("[0-9a-f]{64}", value) is None:
                raise ValueError("source/response receipt identity required")

    def execution_completion(self) -> int | None:
        if self.evidence_kind == "TEST_FIXTURE":
            raise ValueError("fixtures cannot become observed economic arm results")
        return self.completed_ms if self.result == "ALLOW" else None


def preparation_report(
    tape_sha256: str, scheduled_slots: int, candidate_count: int, valid_no_intent_slots: int | None = None
) -> dict[str, Any]:
    if min(scheduled_slots, candidate_count) < 0 or candidate_count > scheduled_slots:
        raise ValueError("invalid scheduled/candidate counts")
    if (
        valid_no_intent_slots is not None
        and not 0 <= valid_no_intent_slots <= scheduled_slots - candidate_count
    ):
        raise ValueError("quiet slots cannot absorb unavailable/error slots")
    reason = (
        "Absent point-in-time news, observed provider responses, completion clocks and costs; "
        "historical pretrained-model event knowledge is not causal historical evidence"
    )
    absent = {
        "status": "NOT_CALLED",
        "economic_results": None,
        "cost_usd": None,
        "reason": reason,
        "paired_to_baseline": False,
    }
    return {
        "schema": "kairos.development.matched-preparation.v1",
        "tape_sha256": tape_sha256,
        "scheduled_slots": scheduled_slots,
        "baseline_candidates": candidate_count,
        "quiet_slots_included": valid_no_intent_slots,
        "unavailable_or_nondecision_slots": (
            scheduled_slots - candidate_count - valid_no_intent_slots
            if valid_no_intent_slots is not None
            else None
        ),
        "arms": {
            "strategy_only": {"status": "CONDITIONAL_CANDLE_DEVELOPMENT_ONLY"},
            "review": dict(absent),
            "proposals": dict(absent),
        },
        "matched_ab_executed": False,
        "blind_campaign_enrolled": False,
        "allowed_next_input": (
            "Source-bound point-in-time observed receipts; quiet slots also need proposal coverage"
        ),
        "existing_campaign_evaluator_changed": False,
    }
