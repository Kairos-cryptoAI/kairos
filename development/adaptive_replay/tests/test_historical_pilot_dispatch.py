from __future__ import annotations

import asyncio
import hashlib
import json
import runpy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from kairos_core.enums import ReasoningEffort
from kairos_llm.budget import BudgetedLLMGateway
from kairos_llm.config import LLMSettings
from kairos_llm.errors import LLMBudgetError
from kairos_llm.gateway import LLMGateway
from kairos_llm.models import LLMWorkload, ModelRouter, Provider
from pydantic import ValidationError

from adaptive_replay.historical_pilot_budget import PilotBudget
from adaptive_replay.historical_pilot_dispatch import (
    LOCAL_RESERVATION_MICROUSD,
    NATIVE_OPENAI_CEILING_MICROUSD,
    HistoricalPilotDispatcher,
    PairedPilotUsageBudget,
    PilotDecision,
    SourceAdmission,
    _valid_observed_clocks,
    make_native_gateway,
)

_REPLAY_TEST_HELPERS = runpy.run_path(str(Path(__file__).with_name("test_historical_replay.py")))
REPLAY_SCENARIO = _REPLAY_TEST_HELPERS["SCENARIO"]
replay_fixture = _REPLAY_TEST_HELPERS["fixture"]
_PILOT_BUDGET_TEST_HELPERS = runpy.run_path(str(Path(__file__).with_name("test_historical_pilot_budget.py")))

RESERVATION_ID = "kairos-llm-v1:openai:00000000000000000000000000000001"


class Shared:
    def __init__(self, *, fail_reserve=False, fail_commit=False, on_reserve=None):
        self.events = []
        self.fail_reserve, self.fail_commit = fail_reserve, fail_commit
        self.on_reserve = on_reserve

    async def reserve(self, **kwargs):
        self.events.append(("reserve", kwargs))
        if self.on_reserve is not None:
            self.on_reserve()
        if self.fail_reserve:
            raise LLMBudgetError("shared deny")

    async def commit(self, **kwargs):
        self.events.append(("commit", kwargs))
        if self.fail_commit:
            raise LLMBudgetError("commit uncertain")


def local_budget():
    value = object.__new__(PilotBudget)
    object.__setattr__(value, "slot_ids", ("slot-1",))
    object.__setattr__(value, "reserve_attempt", Mock(return_value={}))
    object.__setattr__(value, "settle_known_cost", Mock(return_value={}))
    object.__setattr__(value, "snapshot", Mock(return_value={"held_reservation_micro_usd": 500_000}))
    return value


def run(coro):
    return asyncio.run(coro)


class InjectedResponses:
    def __init__(self, *, parsed=None, output_text=None, usage=True, cancel=False):
        self.responses = self
        self.parsed = {"decision": "ALLOW"} if parsed is None else parsed
        self.output_text = output_text or json.dumps(self.parsed, separators=(",", ":"))
        self.usage = (
            SimpleNamespace(
                input_tokens=1_000, output_tokens=80, input_tokens_details=SimpleNamespace(cached_tokens=0)
            )
            if usage
            else None
        )
        self.cancel = cancel
        self.calls = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.cancel:
            raise asyncio.CancelledError()
        return SimpleNamespace(
            status="completed",
            output_parsed=self.parsed,
            output_text=self.output_text,
            usage=self.usage,
            model="gpt-6-luna",
            id="resp_test",
        )


def fixture_dispatcher(*, parsed=None, usage=True, cancel=False):
    local, shared = local_budget(), Shared()
    paired = PairedPilotUsageBudget(local, shared, "slot-1")
    sdk = InjectedResponses(parsed=parsed, usage=usage, cancel=cancel)
    raw = LLMGateway(settings=LLMSettings(max_retries=0), client=sdk)
    native = make_native_gateway(raw, paired)
    dispatcher = HistoricalPilotDispatcher(native, local, shared, "slot-1", lambda: True, fixture_only=True)
    admission = SourceAdmission(True, True, False, "a" * 64, fixture_only=True)
    return dispatcher, admission, local, shared, sdk


def real_ledger(tmp_path):
    workspace = _PILOT_BUDGET_TEST_HELPERS["_workspace"](tmp_path)
    ledger = _PILOT_BUDGET_TEST_HELPERS["_create"](workspace)
    slot = _PILOT_BUDGET_TEST_HELPERS["budget"].ALLOWED_SLOT_IDS[0]
    return ledger, slot


def real_fixture_dispatcher(tmp_path, *, shared=None, parsed=None, cancel=False):
    local, slot = real_ledger(tmp_path)
    shared = shared or Shared()
    sdk = InjectedResponses(parsed=parsed, cancel=cancel)
    paired = PairedPilotUsageBudget(local, shared, slot)
    native = make_native_gateway(LLMGateway(settings=LLMSettings(max_retries=0), client=sdk), paired)
    dispatcher = HistoricalPilotDispatcher(native, local, shared, slot, lambda: True, fixture_only=True)
    admission = SourceAdmission(True, True, False, "a" * 64, fixture_only=True)
    return dispatcher, admission, local, slot, shared, sdk


def test_fixed_route_and_native_budgeted_gateway_configuration():
    local, shared = local_budget(), Shared()
    paired = PairedPilotUsageBudget(local, shared, "slot-1")
    raw = LLMGateway(settings=LLMSettings(max_retries=0), client=object())
    gateway = make_native_gateway(raw, paired)
    assert isinstance(gateway, BudgetedLLMGateway)
    assert gateway.budget is paired
    assert gateway.monthly_budgets_microusd[Provider.OPENAI] == NATIVE_OPENAI_CEILING_MICROUSD


def test_reserve_local_first_then_authoritative_shared_and_duplicate_denied():
    local, shared = local_budget(), Shared()
    paired = PairedPilotUsageBudget(local, shared, "slot-1")
    run(
        paired.reserve(
            provider="openai",
            reservation_id=RESERVATION_ID,
            reserved_microusd=500_000,
            monthly_budget_microusd=NATIVE_OPENAI_CEILING_MICROUSD,
        )
    )
    local.reserve_attempt.assert_called_once_with("slot-1", 500_000)
    assert shared.events[0][0] == "reserve"
    with pytest.raises(LLMBudgetError):
        run(
            paired.reserve(
                provider="openai",
                reservation_id="kairos-llm-v1:openai:00000000000000000000000000000002",
                reserved_microusd=500_000,
                monthly_budget_microusd=NATIVE_OPENAI_CEILING_MICROUSD,
            )
        )


def test_shared_denial_keeps_local_held_no_release():
    local, shared = local_budget(), Shared(fail_reserve=True)
    paired = PairedPilotUsageBudget(local, shared, "slot-1")
    with pytest.raises(LLMBudgetError, match="shared deny"):
        run(
            paired.reserve(
                provider="openai",
                reservation_id=RESERVATION_ID,
                reserved_microusd=500_000,
                monthly_budget_microusd=NATIVE_OPENAI_CEILING_MICROUSD,
            )
        )
    local.reserve_attempt.assert_called_once()
    local.settle_known_cost.assert_not_called()


def test_shared_commit_failure_never_settles_local_hold():
    local, shared = local_budget(), Shared(fail_commit=True)
    paired = PairedPilotUsageBudget(local, shared, "slot-1")

    async def exercise():
        await paired.reserve(
            provider="openai",
            reservation_id=RESERVATION_ID,
            reserved_microusd=500_000,
            monthly_budget_microusd=NATIVE_OPENAI_CEILING_MICROUSD,
        )
        await paired.commit(provider="openai", reservation_id=RESERVATION_ID, actual_microusd=12)

    with pytest.raises(LLMBudgetError, match="commit uncertain"):
        run(exercise())
    local.settle_known_cost.assert_not_called()


def test_decision_schema_is_strict_and_closed():
    assert PilotDecision.model_validate({"decision": "DEFER"}).decision == "DEFER"
    for payload in ({"decision": "BUY"}, {"decision": "ALLOW", "extra": 1}):
        with pytest.raises(ValidationError):
            PilotDecision.model_validate(payload)


def test_source_admission_requires_candidate_ready_production_and_nonfixture():
    digest = "a" * 64
    base = dict(
        required_sources_ready=True,
        candidate_present=True,
        production_source_admitted=True,
        source_identity_sha256=digest,
    )
    assert SourceAdmission(**base).allows_dispatch()
    assert not SourceAdmission(**{**base, "fixture_only": True}).allows_dispatch()
    assert not SourceAdmission(**{**base, "candidate_present": False}).allows_dispatch()
    assert not SourceAdmission(**{**base, "required_sources_ready": False}).allows_dispatch()
    assert not SourceAdmission(**{**base, "production_source_admitted": False}).allows_dispatch()
    assert not SourceAdmission(**{**base, "source_identity_sha256": "not-a-digest"}).allows_dispatch()


def test_gateway_route_is_explicit_workload_and_native_retry_policy():
    router = ModelRouter()
    route = router.resolve(workload=LLMWorkload.AGGREGATOR_NORMAL)
    assert (route.choice.provider, route.choice.model, route.effort, route.max_output_tokens) == (
        Provider.OPENAI,
        "gpt-6-luna",
        ReasoningEffort.MEDIUM,
        2_048,
    )
    with pytest.raises(TypeError):
        make_native_gateway(LLMGateway(settings=LLMSettings(max_retries=1), client=object()), object())


def test_native_local_reservation_limit_is_not_monthly_shared_ceiling():
    assert LOCAL_RESERVATION_MICROUSD < NATIVE_OPENAI_CEILING_MICROUSD
    assert _valid_observed_clocks(100, 110, 120, 130)
    assert not _valid_observed_clocks(100, 110, 120, 119)
    assert not _valid_observed_clocks(100, 99, 120, 130)
    assert not _valid_observed_clocks(True, 110, 120, 130)


def test_dispatch_source_and_identity_gates_fail_before_paid_gateway_call():
    local, shared = local_budget(), Shared()
    paired = PairedPilotUsageBudget(local, shared, "slot-1")
    native = make_native_gateway(LLMGateway(settings=LLMSettings(max_retries=0), client=object()), paired)
    called = []

    async def forbidden(**kwargs):
        called.append(kwargs)
        raise AssertionError("must not reach gateway")

    native.complete = forbidden
    dispatcher = HistoricalPilotDispatcher(native, local, shared, "slot-1", lambda: False, fixture_only=True)
    admission = SourceAdmission(True, True, False, "a" * 64, fixture_only=True)
    with pytest.raises(LLMBudgetError, match="identity"):
        run(dispatcher.dispatch(system="x", user="y", admission=admission))
    assert called == []
    dispatcher = HistoricalPilotDispatcher(native, local, shared, "slot-1", lambda: True, fixture_only=True)
    with pytest.raises(LLMBudgetError, match="sources/candidate"):
        run(dispatcher.dispatch(system="x", user="y", admission=None))
    assert called == []


def test_actual_native_gateway_with_injected_sdk_client_commits_and_emits_review_fields():
    dispatcher, admission, local, shared, sdk = fixture_dispatcher()
    result = run(
        dispatcher.dispatch(system="system prompt", user="review this candidate", admission=admission)
    )
    assert len(sdk.calls) == 1
    assert sdk.calls[0]["model"] == "gpt-6-luna"
    assert sdk.calls[0]["reasoning"] == {"effort": "medium"}
    assert sdk.calls[0]["max_output_tokens"] == 2_048
    assert sdk.calls[0]["store"] is False
    assert result["response_json"] == '{"decision":"ALLOW"}'
    assert result["status"] == "COMPLETE" and result["fixture_only"] is True
    assert result["actual_requested_ms"] <= result["actual_observed_ms"] <= result["actual_cost_observed_ms"]
    assert result["recorded_cost_usd"] > 0
    assert result["raw_response_sha256"] == hashlib.sha256(b'{"decision":"ALLOW"}').hexdigest()
    assert [event for event, _ in shared.events] == ["reserve", "commit"]
    local.settle_known_cost.assert_called_once()
    assert result["provider"] == "OPENAI" and result["attempt_id"] == result["reservation_id"]
    with pytest.raises(LLMBudgetError, match="duplicate delivery"):
        run(dispatcher.dispatch(system="repeat", user="repeat", admission=admission))
    assert len(sdk.calls) == 1


def test_native_sdk_cancellation_leaves_both_budgets_held():
    dispatcher, admission, local, shared, sdk = fixture_dispatcher(cancel=True)
    with pytest.raises(asyncio.CancelledError):
        run(dispatcher.dispatch(system="s", user="u", admission=admission))
    assert len(sdk.calls) == 1
    assert [event for event, _ in shared.events] == ["reserve"]
    local.reserve_attempt.assert_called_once()
    local.settle_known_cost.assert_not_called()


def test_native_sdk_unknown_usage_keeps_reservations_held():
    from kairos_llm.errors import LLMServerError

    dispatcher, admission, local, shared, sdk = fixture_dispatcher(usage=False)
    with pytest.raises(LLMServerError):
        run(dispatcher.dispatch(system="s", user="u", admission=admission))
    assert [event for event, _ in shared.events] == ["reserve"]
    local.settle_known_cost.assert_not_called()


def test_native_sdk_invalid_decision_is_rejected_after_cost_is_committed():
    from pydantic import ValidationError

    dispatcher, admission, local, shared, _sdk = fixture_dispatcher(parsed={"decision": "BUY"})
    with pytest.raises(ValidationError):
        run(dispatcher.dispatch(system="s", user="u", admission=admission))
    assert [event for event, _ in shared.events] == ["reserve", "commit"]
    local.settle_known_cost.assert_called_once()


def test_real_sqlite_paired_success_settles_local_and_shared_cost(tmp_path):
    dispatcher, admission, local, slot, shared, sdk = real_fixture_dispatcher(tmp_path)
    result = run(dispatcher.dispatch(system="s", user="u", admission=admission))
    reopened = _PILOT_BUDGET_TEST_HELPERS["_reopen"](local.path)
    state = reopened.snapshot()
    assert len(sdk.calls) == 1
    assert state["slot_admissions"] == 1
    assert state["held_reservation_micro_usd"] == 0
    assert state["committed_micro_usd"] > 0
    assert [event for event, _ in shared.events] == ["reserve", "commit"]
    assert result["recorded_cost_usd"] > 0
    assert slot in local.slot_ids


def test_real_sqlite_cancel_and_shared_commit_failure_remain_held_after_reopen(tmp_path):
    dispatcher, admission, local, _slot, shared, sdk = real_fixture_dispatcher(
        tmp_path / "cancel", cancel=True
    )
    with pytest.raises(asyncio.CancelledError):
        run(dispatcher.dispatch(system="s", user="u", admission=admission))
    cancel_state = _PILOT_BUDGET_TEST_HELPERS["_reopen"](local.path).snapshot()
    assert len(sdk.calls) == 1
    assert cancel_state["slot_admissions"] == 1
    assert cancel_state["held_reservation_micro_usd"] > 0
    assert cancel_state["committed_micro_usd"] == 0
    assert [event for event, _ in shared.events] == ["reserve"]

    commit_shared = Shared(fail_commit=True)
    dispatcher, admission, local, _slot, _shared, sdk = real_fixture_dispatcher(
        tmp_path / "commit-fail", shared=commit_shared
    )
    with pytest.raises(LLMBudgetError, match="commit uncertain"):
        run(dispatcher.dispatch(system="s", user="u", admission=admission))
    commit_state = _PILOT_BUDGET_TEST_HELPERS["_reopen"](local.path).snapshot()
    assert len(sdk.calls) == 1
    assert commit_state["slot_admissions"] == 1
    assert commit_state["held_reservation_micro_usd"] > 0
    assert commit_state["committed_micro_usd"] == 0
    assert [event for event, _ in commit_shared.events] == ["reserve", "commit"]


def test_new_adapter_cannot_reuse_real_sqlite_one_shot_slot(tmp_path):
    dispatcher, admission, local, slot, shared, sdk = real_fixture_dispatcher(tmp_path)
    run(dispatcher.dispatch(system="s", user="u", admission=admission))
    sdk_again = InjectedResponses()
    paired_again = PairedPilotUsageBudget(local, shared, slot)
    native_again = make_native_gateway(
        LLMGateway(settings=LLMSettings(max_retries=0), client=sdk_again), paired_again
    )
    dispatcher_again = HistoricalPilotDispatcher(
        native_again, local, shared, slot, lambda: True, fixture_only=True
    )
    with pytest.raises(ValueError, match="already consumed"):
        run(dispatcher_again.dispatch(system="s", user="u", admission=admission))
    assert sdk_again.calls == []
    assert _PILOT_BUDGET_TEST_HELPERS["_reopen"](local.path).snapshot()["slot_admissions"] == 1


def test_native_router_isolated_from_shared_mutable_router():
    local, shared = local_budget(), Shared()
    paired = PairedPilotUsageBudget(local, shared, "slot-1")
    raw = LLMGateway(settings=LLMSettings(max_retries=0), client=object())
    native = make_native_gateway(raw, paired)
    raw.router.override_workload(
        LLMWorkload.AGGREGATOR_NORMAL, "gpt-6-sol", Provider.OPENAI, ReasoningEffort.HIGH, "high", 2_048
    )
    route = native.router.resolve(workload=LLMWorkload.AGGREGATOR_NORMAL)
    assert (route.choice.model, route.choice.provider, route.effort, route.max_output_tokens) == (
        "gpt-6-luna",
        Provider.OPENAI,
        ReasoningEffort.MEDIUM,
        2_048,
    )


def test_shared_reserve_cannot_mutate_native_sdk_route_mid_dispatch():
    local = local_budget()
    raw = LLMGateway(settings=LLMSettings(max_retries=0), client=InjectedResponses())
    shared = Shared(
        on_reserve=lambda: raw.router.override_workload(
            LLMWorkload.AGGREGATOR_NORMAL,
            "gpt-6-sol",
            Provider.OPENAI,
            ReasoningEffort.HIGH,
            "high",
            2_048,
        )
    )
    paired = PairedPilotUsageBudget(local, shared, "slot-1")
    native = make_native_gateway(raw, paired)
    dispatcher = HistoricalPilotDispatcher(native, local, shared, "slot-1", lambda: True, fixture_only=True)
    admission = SourceAdmission(True, True, False, "a" * 64, fixture_only=True)
    result = run(dispatcher.dispatch(system="s", user="u", admission=admission))
    assert result["model"] == "gpt-6-luna"
    assert raw._injected_client.calls[0]["model"] == "gpt-6-luna"


@pytest.mark.parametrize("decision", ["ALLOW", "VETO"])
def test_synthetic_native_review_flows_through_fixture_replay_common_account(decision):
    from adaptive_replay.historical_replay import RetrospectiveReview, evaluate_historical_review

    inputs, original_frames = replay_fixture()
    chosen = next(index for index, frame in enumerate(original_frames) if frame.candidate is not None)
    frames = tuple(
        frame if index == chosen else replace(frame, candidate=None, state="QUIET")
        for index, frame in enumerate(original_frames)
    )
    frame = frames[chosen]
    local, shared = local_budget(), Shared()
    sdk = InjectedResponses(parsed={"decision": decision})
    paired = PairedPilotUsageBudget(local, shared, "slot-1")
    native = make_native_gateway(LLMGateway(settings=LLMSettings(max_retries=0), client=sdk), paired)
    dispatcher = HistoricalPilotDispatcher(native, local, shared, "slot-1", lambda: True, fixture_only=True)
    admission = SourceAdmission(True, True, False, "a" * 64, fixture_only=True)
    result = run(
        dispatcher.dispatch(
            system="synthetic fixture prompt",
            user=json.dumps(frame.prompt_payload(), sort_keys=True, separators=(",", ":")),
            admission=admission,
        )
    )
    assert result["fixture_only"] is True
    review = RetrospectiveReview(
        frame_id=frame.frame_id,
        prompt_sha256=frame.prompt_sha256,
        attempt_id=result["attempt_id"],
        model=result["model"],
        model_config_sha256="e" * 64,
        actual_requested_ms=result["actual_requested_ms"],
        actual_observed_ms=result["actual_observed_ms"],
        actual_cost_observed_ms=result["actual_cost_observed_ms"],
        recorded_cost_usd=result["recorded_cost_usd"],
        status=result["status"],
        response_json=result["response_json"],
        raw_response_sha256=result["raw_response_sha256"],
        evidence_kind="TEST_FIXTURE",
        provider=result["provider"],
    )
    replay = evaluate_historical_review(
        inputs,
        frames,
        (review,),
        REPLAY_SCENARIO,
        "STRICT_MINUTE_OPEN",
        simulated_delay_ms=100,
        feed_costs=(),
        fixture_only=True,
    )
    arm = replay["arms"]["context_review"]
    assert arm["status"] == "FIXTURE_ONLY"
    assert arm["economic_results"]["model_cost_usd"] == pytest.approx(result["recorded_cost_usd"])
    entries = [event for event in arm["events"] if event["kind"] == "ENTRY"]
    assert not entries
    if decision == "ALLOW":
        # Strict minute-open rounds readiness beyond this candidate's fixed expiry.
        assert frame.candidate.entry_expires_ts_ms < ((inputs.start_ms + 100 + 59_999) // 60_000) * 60_000
    assert replay["known_modern_model_cost_usd"] == pytest.approx(result["recorded_cost_usd"])
