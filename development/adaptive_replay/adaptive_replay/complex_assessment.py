"""Strict receipts and fail-closed arbitration for joint directional review.

This module parses evidence only. It does not call models or project costs.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Literal

from kairos_core.enums import Side
from kairos_strategy.models import SleeveIntent
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .historical_context import _clock, _name, _sha, canonical

ReviewDecision = Literal["ALLOW", "VETO", "DEFER"]
Proposal = Literal["NONE", "LONG", "SHORT"]


class DirectionalAssessment(BaseModel):
    """Exact model response; no prices, size, confidence, or extra fields."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    long_review: ReviewDecision
    short_review: ReviewDecision
    proposal: Proposal
    evidence_ids: list[str] = Field(max_length=64)

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("evidence_ids must be unique")
        for value in values:
            _sha(value)
        return values

    @model_validator(mode="after")
    def proposal_requires_directional_allow(self) -> DirectionalAssessment:
        if self.proposal == "LONG" and self.long_review != "ALLOW":
            raise ValueError("LONG proposal requires long_review ALLOW")
        if self.proposal == "SHORT" and self.short_review != "ALLOW":
            raise ValueError("SHORT proposal requires short_review ALLOW")
        return self


@dataclass(frozen=True)
class RetrospectiveAssessment:
    frame_id: str
    prompt_sha256: str
    attempt_id: str
    model: str
    model_config_sha256: str
    actual_requested_ms: int
    actual_observed_ms: int
    actual_cost_observed_ms: int
    recorded_cost_usd: float | None
    status: str
    response_json: str | None
    raw_response_sha256: str | None
    no_call_reason: str | None = None
    evidence_kind: str = "MODERN_RETROSPECTIVE"
    provider: str = "OPENAI"

    def validate(self) -> None:
        for value in (self.frame_id, self.prompt_sha256, self.model_config_sha256):
            _sha(value)
        _name(self.attempt_id)
        _name(self.model)
        if self.provider != "OPENAI":
            raise ValueError("OpenAI-only retrospective assessment required")
        for value in (self.actual_requested_ms, self.actual_observed_ms, self.actual_cost_observed_ms):
            _clock(value)
        if not self.actual_requested_ms <= self.actual_observed_ms <= self.actual_cost_observed_ms:
            raise ValueError("actual response and cost clocks must be ordered")
        if self.evidence_kind not in {"MODERN_RETROSPECTIVE", "TEST_FIXTURE"}:
            raise ValueError("wrong retrospective evidence kind")
        if self.recorded_cost_usd is not None and (
            type(self.recorded_cost_usd) not in {int, float}
            or not math.isfinite(self.recorded_cost_usd)
            or self.recorded_cost_usd < 0
        ):
            raise ValueError("known nonnegative actual cost or explicit unknown required")
        if self.status == "COMPLETE":
            _sha(self.raw_response_sha256)
            if type(self.response_json) is not str or len(self.response_json.encode()) > 4_096:
                raise ValueError("bounded canonical assessment response required")
            parsed = _parse_response(self.response_json)
            if canonical(parsed.model_dump(mode="json")) != self.response_json:
                raise ValueError("canonical response JSON required")
            if self.no_call_reason is not None:
                raise ValueError("complete assessment cannot carry a no-call reason")
        elif self.status in {"ERROR", "NOT_CALLED"}:
            if self.response_json is not None:
                raise ValueError("failed/no-call receipt cannot contain a decision")
            if self.raw_response_sha256 is not None:
                _sha(self.raw_response_sha256)
            if self.status == "NOT_CALLED":
                valid_no_call_reasons = {
                    "BUDGET_DENIED",
                    "REQUIRED_SOURCE_UNAVAILABLE",
                    "SCHEDULED_POLICY_ABSTAIN",
                }
                if (
                    self.recorded_cost_usd != 0
                    or self.no_call_reason not in valid_no_call_reasons
                    or self.raw_response_sha256 is not None
                ):
                    raise ValueError("no-call requires explicit reason, zero cost and no raw response")
            elif self.no_call_reason is not None:
                raise ValueError("ERROR cannot claim a no-call reason")
        else:
            raise ValueError("explicit assessment status required")


def _parse_response(response_json: str) -> DirectionalAssessment:
    try:
        raw = json.loads(response_json, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
        return DirectionalAssessment.model_validate(raw)
    except (ValueError, TypeError, ValidationError, RecursionError):
        raise ValueError("invalid strict directional assessment response") from None


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("non-finite JSON value")


def read_assessment(
    receipt: RetrospectiveAssessment,
    *,
    expected_frame_id: str,
    expected_prompt_sha256: str,
    permitted_evidence_ids: frozenset[str],
    fixture_only: bool,
    not_before_ms: int,
) -> DirectionalAssessment | None:
    """Validate receipt identity, temporal/evidence binding, and fixture mode.

    Returns ``None`` for an ERROR or NOT_CALLED receipt; callers must not infer
    an assessment or impute unknown model cost from those dispositions.
    """
    if type(receipt) is not RetrospectiveAssessment:
        raise ValueError("exact typed retrospective assessment receipt required")
    receipt.validate()
    _sha(expected_frame_id)
    _sha(expected_prompt_sha256)
    _clock(not_before_ms)
    if (receipt.frame_id, receipt.prompt_sha256) != (expected_frame_id, expected_prompt_sha256):
        raise ValueError("assessment receipt is not bound to expected frame and prompt")
    if type(fixture_only) is not bool or (receipt.evidence_kind == "TEST_FIXTURE") != fixture_only:
        raise ValueError("assessment and requested fixture modes differ")
    if receipt.actual_requested_ms < not_before_ms:
        raise ValueError("assessment cannot predate its materialized frame")
    if type(permitted_evidence_ids) is not frozenset:
        raise ValueError("immutable permitted evidence-id set required")
    for evidence_id in permitted_evidence_ids:
        _sha(evidence_id)
    if receipt.status != "COMPLETE":
        return None
    parsed = _parse_response(receipt.response_json)  # validated above
    if any(value not in permitted_evidence_ids for value in parsed.evidence_ids):
        raise ValueError("assessment cites duplicate, future, or unpermitted evidence")
    return parsed


def directional_review(assessment: DirectionalAssessment | None, baseline_side: Side | None) -> str:
    """Return the review disposition for a baseline direction, fail closed."""
    if baseline_side is None or baseline_side is Side.FLAT:
        return "DEFER"
    if not isinstance(baseline_side, Side):
        raise ValueError("baseline side must be a Side or None")
    if type(assessment) is not DirectionalAssessment:
        return "DEFER"
    try:
        checked = DirectionalAssessment.model_validate(assessment.model_dump())
    except (ValidationError, ValueError, TypeError):
        return "DEFER"
    return checked.long_review if baseline_side is Side.LONG else checked.short_review


def arbitrate_combined(
    baseline: SleeveIntent | None,
    mapped_proposal: SleeveIntent | None,
    assessment: DirectionalAssessment | None,
) -> tuple[SleeveIntent | None, str]:
    """Select only an original candidate; do not manufacture or resurrect one."""
    if baseline is not None and type(baseline) is not SleeveIntent:
        raise ValueError("baseline must be the exact original SleeveIntent")
    if mapped_proposal is not None and type(mapped_proposal) is not SleeveIntent:
        raise ValueError("mapped proposal must be the exact original SleeveIntent")
    if assessment is not None and type(assessment) is not DirectionalAssessment:
        raise ValueError("strict parsed assessment required")
    if assessment is not None:
        try:
            assessment = DirectionalAssessment.model_validate(assessment.model_dump())
        except (ValidationError, ValueError, TypeError):
            return None, "INVALID_ASSESSMENT"

    if (baseline is not None and baseline.side is Side.FLAT) or (
        mapped_proposal is not None and mapped_proposal.side is Side.FLAT
    ):
        return None, "FLAT_SIDE_UNSUPPORTED"

    if baseline is not None:
        review = directional_review(assessment, baseline.side)
        if review != "ALLOW":
            return None, f"BASELINE_{review}"
        if assessment is not None and assessment.proposal != "NONE":
            proposal_side = Side.LONG if assessment.proposal == "LONG" else Side.SHORT
            if mapped_proposal is None:
                return None, "PROPOSAL_MAPPING_UNAVAILABLE"
            if mapped_proposal.side is not proposal_side:
                return None, "PROPOSAL_MAPPING_MISMATCH"
        elif mapped_proposal is not None:
            return None, "PROPOSAL_MAPPING_MISMATCH"
        if mapped_proposal is None or mapped_proposal.side is baseline.side:
            return baseline, "BASELINE_ALLOWED"
        return None, "OPPOSITE_PROPOSAL_ABSTAIN"

    if mapped_proposal is None:
        if assessment is not None and assessment.proposal != "NONE":
            return None, "PROPOSAL_MAPPING_UNAVAILABLE"
        return None, "NO_CANDIDATE"
    if assessment is not None and assessment.proposal != "NONE":
        proposal_side = Side.LONG if assessment.proposal == "LONG" else Side.SHORT
        if mapped_proposal.side is not proposal_side:
            return None, "PROPOSAL_MAPPING_MISMATCH"
    review = directional_review(assessment, mapped_proposal.side)
    proposal_word = "LONG" if mapped_proposal.side is Side.LONG else "SHORT"
    if assessment is not None and assessment.proposal == proposal_word and review == "ALLOW":
        return mapped_proposal, "QUIET_PROPOSAL_ALLOWED"
    return None, "QUIET_PROPOSAL_NOT_ALLOWED"
