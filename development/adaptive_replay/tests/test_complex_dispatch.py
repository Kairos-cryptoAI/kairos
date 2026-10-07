import asyncio
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from kairos_llm.config import LLMSettings
from kairos_llm.gateway import LLMGateway
from kairos_llm.models import LLMWorkload
from kairos_llm.schemas import LLMResult, TokenUsage
from kairos_strategy.candles import Candle

from adaptive_replay.complex_assessment import DirectionalAssessment, RetrospectiveAssessment
from adaptive_replay.complex_dispatch import ComplexAssessmentDispatcher
from adaptive_replay.complex_frame import ContextAssessmentFrame
from adaptive_replay.complex_protocol import model_config_sha256, protocol_sha256, requirements
from adaptive_replay.historical_bars import _payload_bytes, resolve_closed_history
from adaptive_replay.historical_context import HistoricalArchive, HistoricalCoverage
from adaptive_replay.historical_pilot_budget import (
    ALLOWED_SLOT_IDS,
    FROZEN_PLAN_SHA256,
    PilotBudget,
)
from adaptive_replay.historical_pilot_dispatch import NATIVE_OPENAI_CEILING_MICROUSD

SLOT = ALLOWED_SLOT_IDS[0]


class FakePilotBudget(PilotBudget):
    def __post_init__(self):
        super().__post_init__()
        object.__setattr__(self, "reservations", [])

    def reserve_attempt(self, slot_id: str, reservation_micro_usd: int):
        self.reservations.append((slot_id, reservation_micro_usd))

    def settle_known_cost(self, slot_id: str, actual_micro_usd: int):
        object.__setattr__(self, "settlement", (slot_id, actual_micro_usd))


class FakeSharedBudget:
    def __init__(self):
        self.reservations = []
        self.commits = []

    async def reserve(self, **kwargs):
        self.reservations.append(kwargs)

    async def commit(self, **kwargs):
        self.commits.append(kwargs)


class FakeResponses:
    def __init__(self, assessment, *, fail=False):
        self.assessment = assessment
        self.fail = fail
        self.calls = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("fixture refusal/transport output")
        output_text = (
            self.assessment.model_dump_json()
            if isinstance(self.assessment, DirectionalAssessment)
            else json.dumps(self.assessment, separators=(",", ":"))
        )
        return SimpleNamespace(
            status="completed",
            output_parsed=self.assessment,
            output_text=output_text,
            model="gpt-6-luna",
            id="fixture-response",
            usage=SimpleNamespace(
                input_tokens=100,
                output_tokens=100,
                input_tokens_details=SimpleNamespace(cached_tokens=0, cache_write_tokens=100),
            ),
        )


class FakeClient:
    def __init__(self, assessment, *, fail=False):
        self.responses = FakeResponses(assessment, fail=fail)


def make_frame(*, future_capture: bool = False):
    cut = 100 * 86_400_000 + 5 * 60_000
    captured_at = time.time_ns() // 1_000_000 + 60_000 if future_capture else cut + 1_000
    bars = tuple(
        Candle(
            "BTCUSDT",
            "1m",
            opened,
            opened + 59_999,
            100,
            100.2,
            99.8,
            100.1,
            1,
        )
        for opened in range(cut - 3_240 * 60_000, cut, 60_000)
    )
    hist = resolve_closed_history(
        candles=bars,
        expected_payload_sha256=hashlib.sha256(_payload_bytes(bars)).hexdigest(),
        expected_symbol="BTCUSDT",
        expected_timeframe="1m",
        expected_count=3_240,
        expected_first_open_ms=bars[0].open_time_ms,
        expected_last_closed_ms=cut - 1,
        cutoff_ms=cut,
        provenance="TEST_FIXTURE",
        captured_at_ms=captured_at,
    )
    archive = HistoricalArchive(
        (),
        tuple(
            HistoricalCoverage(
                req.source_name,
                req.kind,
                "BTCUSDT",
                0,
                cut + 1,
                (),
                "COMPLETE",
                "TEST_FIXTURE",
                "a" * 64,
                captured_at,
            )
            for req in requirements()
        ),
    )
    return ContextAssessmentFrame(hist, archive, requirements(), cut, protocol_sha256())


def assessment():
    return DirectionalAssessment.model_validate(
        {
            "long_review": "ALLOW",
            "short_review": "DEFER",
            "proposal": "LONG",
            "evidence_ids": [],
        }
    )


def make_dispatcher(*, fake_assessment=None, fail=False, gates=False):
    client = FakeClient(assessment() if fake_assessment is None else fake_assessment, fail=fail)
    settings = LLMSettings.model_construct(max_retries=0, max_output_tokens=2_048, openai_api_key=None)
    gateway = LLMGateway(settings=settings, client=client)
    local = FakePilotBudget(
        Path("C:/fixture/unused-ledger.sqlite"),
        "00000000-0000-4000-8000-000000000001",
        FROZEN_PLAN_SHA256,
        ALLOWED_SLOT_IDS,
    )
    shared = FakeSharedBudget()
    yes = (lambda *_: True) if gates else None
    dispatcher = ComplexAssessmentDispatcher(
        gateway,
        local,
        shared,
        SLOT,
        shared_budget_identity_gate=yes,
        source_admission_gate=yes,
        predecessor_admission_gate=yes,
        human_confirmation_gate=yes,
        fixture_only=True,
    )
    return dispatcher, client, local, shared


def test_missing_human_and_cumulative_admission_gates_default_deny_without_native_call():
    dispatcher, client, local, shared = make_dispatcher()
    result = asyncio.run(dispatcher.dispatch(make_frame()))
    assert isinstance(result, RetrospectiveAssessment)
    assert result.status == "NOT_CALLED"
    assert result.no_call_reason == "SCHEDULED_POLICY_ABSTAIN"
    assert result.recorded_cost_usd == 0
    assert client.responses.calls == []
    assert local.reservations == []
    assert shared.reservations == []


def test_future_materialized_source_is_not_called_or_reserved_even_with_all_gates():
    dispatcher, client, local, shared = make_dispatcher(gates=True)
    result = asyncio.run(dispatcher.dispatch(make_frame(future_capture=True)))
    assert result.status == "NOT_CALLED"
    assert result.no_call_reason == "REQUIRED_SOURCE_UNAVAILABLE"
    assert client.responses.calls == []
    assert local.reservations == []
    assert shared.reservations == []


def test_explicit_fixture_gates_use_fixed_native_budget_gateway_and_modern_receipt():
    dispatcher, client, local, shared = make_dispatcher(gates=True)
    result = asyncio.run(dispatcher.dispatch(make_frame()))
    assert result.status == "COMPLETE"
    assert result.evidence_kind == "TEST_FIXTURE"
    assert result.provider == "OPENAI"
    assert result.model == "gpt-6-luna"
    assert result.model_config_sha256 == model_config_sha256()
    assert result.actual_requested_ms <= result.actual_observed_ms <= result.actual_cost_observed_ms
    assert result.recorded_cost_usd is not None and result.recorded_cost_usd > 0
    assert result.raw_response_sha256 is not None
    assert len(client.responses.calls) == 1
    call = client.responses.calls[0]
    assert call["model"] == "gpt-6-luna"
    assert call["reasoning"] == {"effort": "medium"}
    assert call["max_output_tokens"] == 2_048
    assert call["store"] is False
    assert local.reservations[0][0] == SLOT
    assert local.reservations[0][1] <= 1_000_000
    assert shared.reservations[0]["monthly_budget_microusd"] == NATIVE_OPENAI_CEILING_MICROUSD
    assert len(shared.commits) == 1


def test_invalid_or_contradictory_parsed_assessment_is_error_not_salvaged():
    contradiction = {
        "long_review": "VETO",
        "short_review": "ALLOW",
        "proposal": "LONG",
        "evidence_ids": [],
    }
    dispatcher, client, _local, _shared = make_dispatcher(fake_assessment=contradiction, gates=True)
    result = asyncio.run(dispatcher.dispatch(make_frame()))
    assert result.status == "ERROR"
    assert result.response_json is None
    assert result.raw_response_sha256 is not None
    assert result.recorded_cost_usd is not None
    assert result.actual_requested_ms <= result.actual_observed_ms <= result.actual_cost_observed_ms
    assert len(client.responses.calls) == 1


def test_unpermitted_source_reference_is_error_after_native_response_not_complete():
    cited = DirectionalAssessment.model_validate(
        {
            "long_review": "ALLOW",
            "short_review": "DEFER",
            "proposal": "LONG",
            "evidence_ids": ["f" * 64],
        }
    )
    dispatcher, _client, _local, _shared = make_dispatcher(fake_assessment=cited, gates=True)
    result = asyncio.run(dispatcher.dispatch(make_frame()))
    assert result.status == "ERROR"
    assert result.response_json is None
    assert result.raw_response_sha256 is not None
    assert result.recorded_cost_usd is not None


def test_native_refusal_or_schema_exception_is_error_with_unknown_not_imputed_cost():
    dispatcher, client, _local, shared = make_dispatcher(fail=True, gates=True)
    result = asyncio.run(dispatcher.dispatch(make_frame()))
    assert result.status == "ERROR"
    assert result.recorded_cost_usd is None
    assert result.raw_response_sha256 is None
    assert result.response_json is None
    assert result.actual_requested_ms <= result.actual_observed_ms <= result.actual_cost_observed_ms
    assert len(client.responses.calls) == 1
    # Reservation is retained, not reset or silently refunded after ambiguity.
    assert len(shared.reservations) == 1


@pytest.mark.parametrize("offset_ms", [-1_000, 86_400_000])
def test_invalid_native_clocks_become_error_using_adapter_owned_modern_clocks(offset_ms):
    dispatcher, _client, _local, _shared = make_dispatcher(gates=True)
    future_or_past = time.time_ns() // 1_000_000 + offset_ms
    reservation = "kairos-llm-v1:openai:00000000000040008000000000000001"
    dispatcher.paired_budget.reservation_id = reservation
    dispatcher.paired_budget.shared_reserved = True
    returned = []

    async def invalid_clock_result(**_kwargs):
        value = LLMResult(
            content=assessment().model_dump_json(),
            parsed=assessment(),
            model="gpt-6-luna",
            effort="medium",
            usage=TokenUsage(input_tokens=100, output_tokens=100, cache_write_tokens=100),
            cost_usd=0.01,
            workload=LLMWorkload.AGGREGATOR_NORMAL.value,
            provider="openai",
            budget_reservation_id=reservation,
            attempt_started_at_ts_ms=future_or_past,
            response_observed_at_ts_ms=future_or_past + 1,
        )
        returned.append(value)
        return value

    dispatcher.native_gateway.complete = invalid_clock_result
    before = time.time_ns() // 1_000_000
    result = asyncio.run(dispatcher.dispatch(make_frame()))
    after = time.time_ns() // 1_000_000
    assert result.status == "ERROR"
    assert returned and type(returned[0]) is LLMResult
    assert returned[0].provider == "openai" and returned[0].model == "gpt-6-luna"
    assert type(returned[0].cost_usd) is float and returned[0].cost_usd == 0.01
    assert result.recorded_cost_usd == 0.01
    assert result.raw_response_sha256 is not None
    assert (
        before
        <= result.actual_requested_ms
        <= result.actual_observed_ms
        <= result.actual_cost_observed_ms
        <= after
    )
    if offset_ms > 0:
        assert result.actual_observed_ms < future_or_past
    else:
        assert future_or_past < result.actual_requested_ms
    assert result.actual_requested_ms <= result.actual_observed_ms <= result.actual_cost_observed_ms


def test_dispatcher_does_not_require_a_strategy_candidate_for_quiet_frame():
    dispatcher, client, _local, _shared = make_dispatcher(gates=True)
    result = asyncio.run(dispatcher.dispatch(make_frame()))
    assert result.status == "COMPLETE"
    assert client.responses.calls


def test_complete_request_clock_includes_slow_preprovider_reservation_wait():
    dispatcher, _client, _local, _shared = make_dispatcher(gates=True)
    reservation = "kairos-llm-v1:openai:00000000000040008000000000000002"
    dispatcher.paired_budget.reservation_id = reservation
    dispatcher.paired_budget.shared_reserved = True
    native_started = []

    async def slow_reserve_then_result(**_kwargs):
        await asyncio.sleep(0.02)
        started = time.time_ns() // 1_000_000
        native_started.append(started)
        return LLMResult(
            content=assessment().model_dump_json(),
            parsed=assessment(),
            model="gpt-6-luna",
            effort="medium",
            usage=TokenUsage(input_tokens=100, output_tokens=100, cache_write_tokens=100),
            cost_usd=0.01,
            workload=LLMWorkload.AGGREGATOR_NORMAL.value,
            provider="openai",
            budget_reservation_id=reservation,
            attempt_started_at_ts_ms=started,
            response_observed_at_ts_ms=started,
        )

    dispatcher.native_gateway.complete = slow_reserve_then_result
    result = asyncio.run(dispatcher.dispatch(make_frame()))
    assert result.status == "COMPLETE"
    assert native_started
    assert result.actual_requested_ms < native_started[0]
    assert result.actual_requested_ms <= result.actual_observed_ms <= result.actual_cost_observed_ms
