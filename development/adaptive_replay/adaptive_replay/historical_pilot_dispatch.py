"""Fail-closed native-budgeted dispatch for the historical pilot.

This module is an adapter only: source identity and shared-budget identity must
be admitted by the caller at the execution boundary before ``dispatch``.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from kairos_core.enums import ReasoningEffort
from kairos_llm.budget import BudgetedLLMGateway, LLMUsageBudget
from kairos_llm.errors import LLMBudgetError
from kairos_llm.gateway import LLMGateway
from kairos_llm.models import LLMWorkload, ModelChoice, ModelRoute, Provider
from kairos_llm.schemas import LLMResult
from pydantic import BaseModel, ConfigDict, field_validator

from .historical_pilot_budget import PilotBudget

NATIVE_OPENAI_CEILING_MICROUSD = 12_000_000
LOCAL_RESERVATION_MICROUSD = 1_000_000


class PilotDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision: str

    @field_validator("decision")
    @classmethod
    def _decision_enum(cls, value: str) -> str:
        if value not in {"ALLOW", "VETO", "DEFER"}:
            raise ValueError("decision must be ALLOW, VETO, or DEFER")
        return value


@dataclass(frozen=True)
class SourceAdmission:
    """Caller-verified source gate; fixture-only evidence is never admitted."""

    required_sources_ready: bool
    candidate_present: bool
    production_source_admitted: bool
    source_identity_sha256: str
    fixture_only: bool = False

    def allows_dispatch(self) -> bool:
        return (
            self.required_sources_ready is True
            and self.candidate_present is True
            and self.production_source_admitted is True
            and self.fixture_only is False
            and _sha256(self.source_identity_sha256)
        )

    def allows_fixture(self) -> bool:
        return (
            self.required_sources_ready is True
            and self.candidate_present is True
            and self.production_source_admitted is False
            and self.fixture_only is True
            and _sha256(self.source_identity_sha256)
        )


class SharedBudgetIdentityGate(Protocol):
    """Execution-boundary evidence, verified by the owning application."""

    def __call__(self) -> bool: ...


def _sha256(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _native_reservation_id(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    prefix, separator, suffix = value.rpartition(":")
    if prefix != "kairos-llm-v1:openai" or not separator or len(suffix) != 32 or suffix.lower() != suffix:
        return False
    try:
        return uuid.UUID(hex=suffix).hex == suffix
    except ValueError:
        return False


def _valid_observed_clocks(started: Any, observed: Any, adapter_observed: int, now: int) -> bool:
    return (
        type(started) is int
        and type(observed) is int
        and started >= 0
        and started <= observed <= adapter_observed <= now
    )


class _FixedPilotRouter:
    """Immutable route resolver isolated from mutable application-wide routers."""

    __slots__ = ()

    _route = ModelRoute(
        ModelChoice("gpt-6-luna", Provider.OPENAI, "medium"),
        ReasoningEffort.MEDIUM,
        LLMWorkload.AGGREGATOR_NORMAL,
        2_048,
    )

    def resolve(
        self, effort: ReasoningEffort | None = None, *, workload: LLMWorkload | None = None
    ) -> ModelRoute:
        if workload is not LLMWorkload.AGGREGATOR_NORMAL or effort not in (None, ReasoningEffort.MEDIUM):
            raise ValueError("historical pilot accepts only its frozen workload and reasoning tier")
        return self._route


class PairedPilotUsageBudget(LLMUsageBudget):
    """One-shot local slot paired with the authoritative shared PG budget."""

    def __init__(self, local: PilotBudget, shared: LLMUsageBudget, slot_id: str) -> None:
        if (
            not isinstance(local, PilotBudget)
            or not isinstance(slot_id, str)
            or slot_id not in local.slot_ids
        ):
            raise ValueError("a valid local pilot budget and admitted slot are required")
        self.local, self.shared, self.slot_id = local, shared, slot_id
        self.reservation_id: str | None = None
        self.reserved_microusd: int | None = None
        self._attempted = False

    async def reserve(
        self, *, provider: str, reservation_id: str, reserved_microusd: int, monthly_budget_microusd: int
    ) -> None:
        if self._attempted:
            raise LLMBudgetError("pilot slot is one-shot; retries and duplicate reservations are denied")
        self._attempted = True
        if (
            provider != Provider.OPENAI.value
            or not _native_reservation_id(reservation_id)
            or type(reserved_microusd) is not int
            or not 0 < reserved_microusd <= LOCAL_RESERVATION_MICROUSD
            or monthly_budget_microusd != NATIVE_OPENAI_CEILING_MICROUSD
        ):
            raise LLMBudgetError("reservation does not match the fixed historical pilot route/ceiling")
        # Persist the local hold first. Any failure afterwards intentionally leaves it held.
        self.local.reserve_attempt(self.slot_id, reserved_microusd)
        self.reservation_id, self.reserved_microusd = reservation_id, reserved_microusd
        await self.shared.reserve(
            provider=provider,
            reservation_id=reservation_id,
            reserved_microusd=reserved_microusd,
            monthly_budget_microusd=monthly_budget_microusd,
        )

    async def commit(self, *, provider: str, reservation_id: str, actual_microusd: int) -> None:
        if (
            provider != Provider.OPENAI.value
            or reservation_id != self.reservation_id
            or self.reserved_microusd is None
            or type(actual_microusd) is not int
            or actual_microusd < 0
            or actual_microusd > self.reserved_microusd
        ):
            raise LLMBudgetError("commit does not match the sole admitted native reservation")
        # Shared authority commits first; local settlement failure cannot free either budget.
        await self.shared.commit(
            provider=provider, reservation_id=reservation_id, actual_microusd=actual_microusd
        )
        self.local.settle_known_cost(self.slot_id, actual_microusd)


class HistoricalPilotDispatcher:
    """Typed native gateway wrapper with a deny-by-default source gate."""

    def __init__(
        self,
        gateway: BudgetedLLMGateway,
        local_budget: PilotBudget,
        shared_budget: LLMUsageBudget,
        slot_id: str,
        shared_identity_admitted: SharedBudgetIdentityGate,
        *,
        fixture_only: bool = False,
    ) -> None:
        if not isinstance(gateway, BudgetedLLMGateway):
            raise TypeError("an actual BudgetedLLMGateway is required")
        if not callable(shared_identity_admitted):
            raise TypeError("shared-budget identity admission callback is required")
        self.gateway, self.local_budget, self.shared_budget = gateway, local_budget, shared_budget
        self.slot_id, self.shared_identity_admitted = slot_id, shared_identity_admitted
        if type(fixture_only) is not bool:
            raise TypeError("fixture_only must be an explicit boolean")
        self.fixture_only = fixture_only
        self._used = False

    async def dispatch(
        self, *, system: str, user: str, admission: SourceAdmission | None = None
    ) -> dict[str, Any]:
        if self._used:
            raise LLMBudgetError("dispatcher is one-shot; duplicate delivery is denied")
        if admission is None:
            raise LLMBudgetError("required sources/candidate are not admitted")
        injected_client = self.gateway.gateway._injected_client is not None
        if self.fixture_only:
            if not admission.allows_fixture() or not injected_client:
                raise LLMBudgetError("fixture mode requires an injected SDK client and fixture admission")
        elif not admission.allows_dispatch() or injected_client:
            raise LLMBudgetError("production dispatch requires admitted sources and a configured SDK client")
        if self.shared_identity_admitted() is not True:
            raise LLMBudgetError("shared authoritative budget identity is not admitted")
        self._used = True
        # Never accept an unbudgeted client or a caller-selected route.
        paired = self.gateway.budget
        if (
            not isinstance(paired, PairedPilotUsageBudget)
            or paired.local is not self.local_budget
            or paired.shared is not self.shared_budget
            or paired.slot_id != self.slot_id
        ):
            raise LLMBudgetError("gateway must use this invocation's exact paired budget")
        if self.gateway.monthly_budgets_microusd != {
            Provider.OPENAI: NATIVE_OPENAI_CEILING_MICROUSD,
            Provider.DEEPSEEK: 1_000_000,
        }:
            raise LLMBudgetError("native provider ceilings must match the fixed registered budget set")
        if self.gateway.settings.max_retries != 0:
            raise LLMBudgetError("native SDK retries must be disabled")
        if self.gateway.settings.max_output_tokens > 2_048:
            raise LLMBudgetError("pilot SDK output ceiling must not exceed 2048")
        route = self.gateway.router.resolve(workload=LLMWorkload.AGGREGATOR_NORMAL)
        if (
            route.choice.provider is not Provider.OPENAI
            or route.choice.model != "gpt-6-luna"
            or route.effort is not ReasoningEffort.MEDIUM
            or route.choice.provider_effort != "medium"
            or route.max_output_tokens != 2_048
        ):
            raise LLMBudgetError("historical pilot route must remain OpenAI gpt-6-luna medium/2048")
        started = time.time_ns() // 1_000_000
        result = await self.gateway.complete(
            system=system,
            user=user,
            effort=ReasoningEffort.MEDIUM,
            workload=LLMWorkload.AGGREGATOR_NORMAL,
            schema=PilotDecision,
        )
        observed = time.time_ns() // 1_000_000
        if (
            not isinstance(result, LLMResult)
            or result.parsed is None
            or result.provider != Provider.OPENAI.value
            or result.model != "gpt-6-luna"
            or result.effort != ReasoningEffort.MEDIUM.value
            or result.workload != LLMWorkload.AGGREGATOR_NORMAL.value
        ):
            raise LLMBudgetError("native response lacks a validated strict decision")
        decision = PilotDecision.model_validate(result.parsed, strict=True)
        if result.attempt_started_at_ts_ms is None or result.response_observed_at_ts_ms is None:
            raise LLMBudgetError("native gateway did not attach observed response clocks")
        if (
            not _valid_observed_clocks(
                result.attempt_started_at_ts_ms,
                result.response_observed_at_ts_ms,
                observed,
                time.time_ns() // 1_000_000,
            )
            or result.attempt_started_at_ts_ms < started
        ):
            raise LLMBudgetError("native response clocks are invalid or backdated")
        raw = result.content.encode("utf-8")
        cost_observed = time.time_ns() // 1_000_000
        if cost_observed < result.response_observed_at_ts_ms:
            raise LLMBudgetError("cost observation clock cannot precede provider observation")
        canonical_decision = json.dumps(
            decision.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return {
            "decision": decision.model_dump(mode="json"),
            "provider": "OPENAI",
            "model": result.model,
            "workload": result.workload,
            "reservation_id": result.budget_reservation_id,
            "attempt_id": result.budget_reservation_id,
            "actual_requested_ms": result.attempt_started_at_ts_ms,
            "actual_observed_ms": result.response_observed_at_ts_ms,
            "actual_cost_observed_ms": cost_observed,
            "recorded_cost_usd": result.cost_usd,
            "status": "COMPLETE",
            "response_json": canonical_decision,
            "raw_response_sha256": hashlib.sha256(raw).hexdigest(),
            "source_identity_sha256": admission.source_identity_sha256,
            "fixture_only": self.fixture_only,
        }


def make_native_gateway(gateway: Any, paired_budget: PairedPilotUsageBudget) -> BudgetedLLMGateway:
    """Bind a real gateway to the single native registered $12 OpenAI ceiling."""
    if not isinstance(gateway, LLMGateway) or not isinstance(paired_budget, PairedPilotUsageBudget):
        raise TypeError("a real LLMGateway and paired pilot budget are required")
    if gateway.settings.max_retries != 0:
        raise ValueError("native SDK max_retries must be zero")
    from kairos_llm.budget import BudgetedLLMGateway as NativeBudgetedGateway

    # Bind a fresh gateway to an immutable route and capped copy of settings.
    # Mutations to a process-wide router during budget admission cannot alter
    # the request the native gateway subsequently sends.
    settings = gateway.settings.model_copy(
        update={"max_retries": 0, "max_output_tokens": min(gateway.settings.max_output_tokens, 2_048)}
    )
    pinned = LLMGateway(
        settings=settings,
        router=_FixedPilotRouter(),
        accountant=gateway.accountant,
        client=gateway._injected_client,
        on_health=gateway._on_health,
    )
    return NativeBudgetedGateway(
        pinned,
        paired_budget,
        monthly_budgets_microusd={
            Provider.OPENAI: NATIVE_OPENAI_CEILING_MICROUSD,
            Provider.DEEPSEEK: 1_000_000,
        },
    )
