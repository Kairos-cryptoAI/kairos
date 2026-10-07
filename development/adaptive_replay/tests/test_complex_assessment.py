from dataclasses import replace

import pytest
from kairos_core.enums import Side
from kairos_strategy.models import ExitPlan, SleeveIntent
from pydantic import ValidationError

from adaptive_replay.complex_assessment import (
    DirectionalAssessment,
    RetrospectiveAssessment,
    arbitrate_combined,
    directional_review,
    read_assessment,
)
from adaptive_replay.historical_context import canonical

FRAME = "a" * 64
PROMPT = "b" * 64
CONFIG = "c" * 64
RAW = "d" * 64
EVIDENCE = "e" * 64
NOW = 1_800_000_000_000


def intent(side: Side, name: str = "trend_breakout_v1") -> SleeveIntent:
    return SleeveIntent(
        name,
        "BTCUSDT",
        side,
        100_000,
        100_001,
        160_000,
        100,
        1,
        200,
        ExitPlan(99, 102, 120_000) if side is Side.LONG else ExitPlan(101, 98, 120_000),
    )


def payload(**overrides):
    result = {
        "long_review": "ALLOW",
        "short_review": "DEFER",
        "proposal": "LONG",
        "evidence_ids": [EVIDENCE],
    }
    result.update(overrides)
    return result


def receipt(response=None, **overrides):
    fields = dict(
        frame_id=FRAME,
        prompt_sha256=PROMPT,
        attempt_id="assessment-1",
        model="fixture-model",
        model_config_sha256=CONFIG,
        actual_requested_ms=NOW,
        actual_observed_ms=NOW + 100,
        actual_cost_observed_ms=NOW + 200,
        recorded_cost_usd=0.01,
        status="COMPLETE",
        response_json=canonical(payload() if response is None else response),
        raw_response_sha256=RAW,
        evidence_kind="TEST_FIXTURE",
    )
    fields.update(overrides)
    return RetrospectiveAssessment(**fields)


def read(value=None, **overrides):
    args = dict(
        expected_frame_id=FRAME,
        expected_prompt_sha256=PROMPT,
        permitted_evidence_ids=frozenset({EVIDENCE}),
        fixture_only=True,
        not_before_ms=NOW,
    )
    args.update(overrides)
    return read_assessment(receipt() if value is None else value, **args)


def test_schema_is_strict_and_rejects_contradictory_proposal():
    assert DirectionalAssessment.model_validate(payload()).proposal == "LONG"
    with pytest.raises(ValidationError):
        DirectionalAssessment.model_validate(payload(extra="not permitted"))
    with pytest.raises(ValidationError):
        DirectionalAssessment.model_validate(payload(confidence=0.99))
    with pytest.raises(ValidationError):
        DirectionalAssessment.model_validate(payload(long_review="VETO"))
    with pytest.raises(ValidationError):
        DirectionalAssessment.model_validate(payload(evidence_ids=[EVIDENCE, EVIDENCE]))
    with pytest.raises(ValidationError):
        DirectionalAssessment.model_validate(payload(evidence_ids=["not-a-sha"]))


def test_reader_binds_exact_receipt_frame_prompt_source_and_fixture_mode():
    assert read().evidence_ids == [EVIDENCE]
    with pytest.raises(ValueError, match="bound"):
        read(expected_frame_id="f" * 64)
    with pytest.raises(ValueError, match="bound"):
        read(expected_prompt_sha256="f" * 64)
    with pytest.raises(ValueError, match="fixture"):
        read(fixture_only=False)
    with pytest.raises(ValueError, match="predate"):
        read(not_before_ms=NOW + 1)
    with pytest.raises(ValueError, match="unpermitted"):
        read(receipt(payload(evidence_ids=["f" * 64])))


@pytest.mark.parametrize(
    "changes",
    [
        {"provider": "OTHER"},
        {"evidence_kind": "OBSERVED_POINT_IN_TIME"},
        {"actual_observed_ms": NOW - 1},
        {"actual_cost_observed_ms": NOW + 99},
        {"recorded_cost_usd": -0.1},
    ],
)
def test_receipt_rejects_wrong_kind_provider_bad_clocks_and_invalid_cost(changes):
    with pytest.raises(ValueError):
        receipt(**changes).validate()


def test_unknown_cost_is_preserved_and_error_or_no_call_has_no_assessment():
    value = receipt(recorded_cost_usd=None)
    value.validate()
    failed = receipt(status="ERROR", response_json=None, raw_response_sha256=RAW, recorded_cost_usd=None)
    assert read(failed) is None
    no_call = receipt(
        status="NOT_CALLED",
        response_json=None,
        raw_response_sha256=None,
        recorded_cost_usd=0,
        no_call_reason="BUDGET_DENIED",
    )
    assert read(no_call) is None
    with pytest.raises(ValueError):
        receipt(
            status="NOT_CALLED",
            response_json=None,
            raw_response_sha256=None,
            recorded_cost_usd=None,
            no_call_reason="BUDGET_DENIED",
        ).validate()


def test_forged_dataclass_and_noncanonical_duplicate_json_fail_closed():
    forged = object.__new__(RetrospectiveAssessment)
    with pytest.raises((AttributeError, ValueError)):
        read(forged)
    duplicate = (
        '{"evidence_ids":[],"long_review":"ALLOW","long_review":"VETO",'
        '"proposal":"NONE","short_review":"ALLOW"}'
    )
    with pytest.raises(ValueError):
        receipt_json = receipt(response=payload())
        read(replace(receipt_json, response_json=duplicate))


def test_directional_review_is_per_side_and_missing_response_defers():
    assessment = DirectionalAssessment.model_validate(
        payload(long_review="ALLOW", short_review="VETO", proposal="NONE")
    )
    assert directional_review(assessment, Side.LONG) == "ALLOW"
    assert directional_review(assessment, Side.SHORT) == "VETO"
    assert directional_review(None, Side.LONG) == "DEFER"


@pytest.mark.parametrize("decision", ["VETO", "DEFER"])
def test_baseline_veto_or_defer_blocks_combined_even_if_opposite_proposal_allowed(decision):
    assessment = DirectionalAssessment.model_validate(
        payload(long_review=decision, short_review="ALLOW", proposal="SHORT")
    )
    selected, reason = arbitrate_combined(intent(Side.LONG), intent(Side.SHORT), assessment)
    assert selected is None
    assert reason == f"BASELINE_{decision}"


def test_same_side_proposal_keeps_original_baseline_exactly_once():
    baseline = intent(Side.LONG)
    assessment = DirectionalAssessment.model_validate(payload(proposal="LONG"))
    selected, reason = arbitrate_combined(baseline, intent(Side.LONG, "other"), assessment)
    assert selected is baseline
    assert reason == "BASELINE_ALLOWED"


def test_opposite_allowed_proposal_abstains_and_quiet_proposal_requires_matching_allow():
    assessment = DirectionalAssessment.model_validate(
        payload(long_review="ALLOW", short_review="ALLOW", proposal="SHORT")
    )
    selected, reason = arbitrate_combined(intent(Side.LONG), intent(Side.SHORT), assessment)
    assert selected is None and reason == "OPPOSITE_PROPOSAL_ABSTAIN"
    selected, reason = arbitrate_combined(None, intent(Side.SHORT), assessment)
    assert selected is not None and selected.side is Side.SHORT
    assert reason == "QUIET_PROPOSAL_ALLOWED"


def test_quiet_proposal_not_matching_proposal_or_allow_is_dropped_without_resurrection():
    assessment = DirectionalAssessment.model_validate(
        payload(long_review="ALLOW", short_review="DEFER", proposal="LONG")
    )
    selected, reason = arbitrate_combined(None, intent(Side.SHORT), assessment)
    assert selected is None and reason == "PROPOSAL_MAPPING_MISMATCH"
    selected, reason = arbitrate_combined(None, None, assessment)
    assert selected is None and reason == "PROPOSAL_MAPPING_UNAVAILABLE"
