"""Bounded no-network and pure-contract tests for native SIM engineering."""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal
from typing import Literal
from uuid import UUID

import pytest
from kairos_aggregator.candidate_review import CandidateReviewOutput
from kairos_core.contracts import (
    CandidateReviewV1,
    CandidateRouteV1,
    ExitPlanV1,
    RecordedBookLevelV1,
    RecordedTopNBookFrameV1,
    SimulationAssumptionsV1,
    SimulationSessionV1,
    SimulationStrategyRefV1,
    StrategyIntentV1,
    StrategyProvenanceV1,
)
from kairos_core.enums import CandidateReviewTier, ReasoningEffort, ReviewDecision, Side
from kairos_llm.budget import BudgetedLLMGateway, DenyLLMUsageBudget
from kairos_llm.config import LLMSettings
from kairos_llm.errors import LLMBadOutput, LLMBudgetError
from kairos_llm.gateway import LLMGateway
from kairos_llm.models import LLMWorkload
from kairos_persistence import Database, MigrationProfile
from kairos_persistence.config import PersistenceSettings
from kairos_risk.simulation import SimulationRiskPolicy
from pydantic import BaseModel, ConfigDict, ValidationError

from kairos_native_campaign.scheduler import FrozenSimSizing
from kairos_native_campaign.storage import (
    SealedBarWindowV1,
    require_disposable_campaign_database,
)
from kairos_native_campaign.transport import NoNetworkReply, NoNetworkResponsesTransport

T0 = 1_800_000_000_000
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
CAMPAIGN_UUID = "123e4567e89b42d3a456426614174000"
CAMPAIGN_DB = f"kairos_sim_test_campaign_{CAMPAIGN_UUID}"


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: Literal["ok"]


class _ReservationRecorder:
    """A tiny unit-test budget double; it is not PostgreSQL budget evidence."""

    def __init__(self) -> None:
        self.reservations: list[dict[str, object]] = []
        self.commits: list[dict[str, object]] = []

    async def reserve(self, **kwargs: object) -> None:
        self.reservations.append(kwargs)

    async def commit(self, **kwargs: object) -> None:
        self.commits.append(kwargs)


def _intent(**overrides: object) -> StrategyIntentV1:
    values: dict[str, object] = {
        "source": "strategy-engine",
        "strategy_id": "sim-test-strategy",
        "strategy_revision": "1",
        "symbol": "BTCUSDT",
        "side": Side.LONG,
        "decision_ts_ms": T0 + 59_999,
        "entry_eligible_ts_ms": T0 + 60_000,
        "entry_expires_ts_ms": T0 + 120_000,
        "reference_price": 100.0,
        "signal_strength": 0.7,
        "gross_reward_bps": 1_000.0,
        "exit_plan": ExitPlanV1(stop_price=95.0, target_price=110.0, max_holding_ms=180_000),
        "provenance": StrategyProvenanceV1(
            strategy_code_sha256=SHA_A,
            config_sha256=SHA_B,
            input_window_sha256=SHA_C,
            features_sha256=SHA_D,
            input_bar_sha256s=(SHA_A, SHA_B),
        ),
    }
    values.update(overrides)
    return StrategyIntentV1(**values)


def _review(
    *,
    intent: StrategyIntentV1 | None = None,
    decision: ReviewDecision = ReviewDecision.ALLOW,
    reviewed_at_ms: int = T0 + 60_100,
) -> CandidateReviewV1:
    candidate = intent or _intent()
    route = CandidateRouteV1(
        source="router",
        intent=candidate,
        review_tier=CandidateReviewTier.NORMAL,
        requested_reasoning_effort=ReasoningEffort.MEDIUM,
        routed_at_ms=T0 + 59_999,
        review_deadline_ms=T0 + 119_000,
    )
    return CandidateReviewV1(
        source="aggregator",
        route=route,
        intent=candidate,
        decision=decision,
        priority=50,
        reviewed_at_ms=reviewed_at_ms,
        reviewer="DETERMINISTIC",
        reason_codes=(decision.value,),
    )


def _session() -> SimulationSessionV1:
    return SimulationSessionV1(
        source="simulator-controller",
        tape_id="sim-tape",
        tape_sha256="e" * 64,
        assumptions=SimulationAssumptionsV1(
            latency_ms=25,
            maximum_book_age_ms=5_000,
            maximum_frame_latency_ms=1_000,
            depth_participation_fraction=0.1,
            adverse_slippage_bps=2.0,
            taker_fee_bps=5.0,
            price_tick=0.1,
            quantity_step=0.001,
        ),
        strategy_allowlist=(SimulationStrategyRefV1(strategy_id="sim-test-strategy", strategy_revision="1"),),
        started_at_ms=T0,
        ends_at_ms=T0 + 360_000,
    )


def _frame() -> RecordedTopNBookFrameV1:
    return RecordedTopNBookFrameV1(
        source="quant-scouts",
        tape_id="sim-tape",
        stream_epoch="epoch-1",
        symbol="BTCUSDT",
        tape_sequence=1,
        exchange_update_id=1,
        exchange_at_ms=T0 + 60_000,
        received_at_ms=T0 + 60_010,
        persisted_at_ms=T0 + 60_020,
        raw_payload_sha256="f" * 64,
        continuity="ADMITTED",
        bids=(RecordedBookLevelV1(price=99.9, quantity=100.0),),
        asks=(RecordedBookLevelV1(price=100.1, quantity=100.0),),
    )


def _answer_reply(output_json: str = '{"answer":"ok"}') -> NoNetworkReply:
    return NoNetworkReply(schema_name=_Answer.__name__, model="gpt-6-luna", output_json=output_json)


def _gateway(transport: NoNetworkResponsesTransport, *, retries: int = 0) -> LLMGateway:
    return LLMGateway(
        settings=LLMSettings(openai_api_key=None, deepseek_api_key=None, max_retries=retries),
        client=transport,
    )


def test_no_network_transport_is_finite_and_requires_exact_program_types() -> None:
    reply = _answer_reply()
    transport = NoNetworkResponsesTransport((reply,))
    assert transport.responses is transport

    with pytest.raises(ValueError, match="finite exact"):
        NoNetworkResponsesTransport([])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite exact"):
        NoNetworkResponsesTransport((object(),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite exact"):
        NoNetworkResponsesTransport((reply,) * 33)
    with pytest.raises(ValueError, match="bounded explicit"):
        NoNetworkReply(_Answer.__name__, "gpt-6-luna", "x" * 65_537)
    with pytest.raises(ValueError, match="bounded nonnegative"):
        NoNetworkReply(_Answer.__name__, "gpt-6-luna", '{"answer":"ok"}', input_tokens=True)
    with pytest.raises(ValueError, match="bounded nonnegative"):
        NoNetworkReply(_Answer.__name__, "gpt-6-luna", '{"answer":"ok"}', output_tokens=8_193)


@pytest.mark.asyncio
async def test_no_network_transport_checks_model_schema_payload_and_does_not_retry() -> None:
    mismatch = NoNetworkResponsesTransport((reply := _answer_reply(),))
    with pytest.raises(RuntimeError, match="ROUTE_OR_SCHEMA_MISMATCH"):
        await mismatch.responses.parse(model="other-model", text_format=_Answer)
    assert len(mismatch.calls) == 1
    with pytest.raises(RuntimeError, match="PROGRAM_EXHAUSTED_NO_RETRY"):
        await mismatch.responses.parse(model=reply.model, text_format=_Answer)
    assert len(mismatch.calls) == 2

    invalid = NoNetworkResponsesTransport((_answer_reply('{"answer":"invalid"}'),))
    gateway = _gateway(invalid, retries=3)
    with pytest.raises(LLMBadOutput):
        await gateway.complete(
            system="test", user="test", workload=LLMWorkload.AGGREGATOR_NORMAL, schema=_Answer
        )
    assert len(invalid.calls) == 1

    wrong_schema = NoNetworkResponsesTransport((_answer_reply(),))
    with pytest.raises(RuntimeError, match="ROUTE_OR_SCHEMA_MISMATCH"):
        await wrong_schema.responses.parse(model="gpt-6-luna", text_format=CandidateReviewOutput)
    assert len(wrong_schema.calls) == 1


@pytest.mark.asyncio
async def test_real_gateway_and_budget_adapter_deny_before_dispatch_then_accept_unit_double() -> None:
    denied_transport = NoNetworkResponsesTransport((_answer_reply(),))
    denied = BudgetedLLMGateway(_gateway(denied_transport), DenyLLMUsageBudget())
    with pytest.raises(LLMBudgetError, match="durable usage budget"):
        await denied.complete(
            system="frozen system",
            user="bounded prompt",
            workload=LLMWorkload.AGGREGATOR_NORMAL,
            schema=_Answer,
        )
    assert denied_transport.calls == []

    success_transport = NoNetworkResponsesTransport((_answer_reply(),))
    recorder = _ReservationRecorder()
    budgeted = BudgetedLLMGateway(_gateway(success_transport), recorder)
    result = await budgeted.complete(
        system="frozen system",
        user="bounded prompt",
        workload=LLMWorkload.AGGREGATOR_NORMAL,
        schema=_Answer,
    )
    assert result.parsed == _Answer(answer="ok")
    assert len(success_transport.calls) == 1
    assert len(recorder.reservations) == len(recorder.commits) == 1
    assert recorder.reservations[0]["reserved_microusd"] > recorder.commits[0]["actual_microusd"]
    # This double exercises adapter accounting only; it is not PostgreSQL proof.


def test_default_gateway_construction_does_not_create_an_active_network_client() -> None:
    gateway = LLMGateway(settings=LLMSettings(openai_api_key=None, deepseek_api_key=None))
    assert gateway._injected_client is None
    assert gateway._clients == {}


@pytest.mark.parametrize(
    ("equity", "open_risk", "expected_cap"),
    [("1000", "0", Decimal("2.5")), ("1000", "9.5", Decimal("0.5"))],
)
def test_frozen_sim_sizing_respects_trade_and_aggregate_caps_through_real_policy(
    equity: str, open_risk: str, expected_cap: Decimal
) -> None:
    session, frame, review = _session(), _frame(), _review()
    sizing = FrozenSimSizing(equity, open_risk)
    requested = sizing.quantity(review.intent, session, frame)
    conservative_stop_distance = (
        abs(Decimal("100.1") - Decimal("95"))
        + Decimal("100.1") * Decimal("2") / Decimal("10000")
        + Decimal("0.1")
    )
    assert requested == pytest.approx(float(expected_cap / conservative_stop_distance))
    decision = SimulationRiskPolicy().evaluate(
        session=session,
        review=review,
        selected_book_frame=frame,
        decided_at_ms=T0 + 60_100,
        requested_quantity=requested,
    )

    assert decision.approved
    assert Decimal(str(decision.price_cap)) == Decimal("100.2")
    assert Decimal(str(decision.quantity)) == Decimal(str(decision.quantity)).quantize(Decimal("0.001"))
    expected_rounded_quantity = (Decimal(str(requested)) / Decimal("0.001")).to_integral_value(
        rounding=ROUND_FLOOR
    ) * Decimal("0.001")
    assert Decimal(str(decision.quantity)) == expected_rounded_quantity
    actual_stop_risk = Decimal(str(decision.quantity)) * abs(
        Decimal(str(decision.price_cap)) - Decimal(str(review.intent.exit_plan.stop_price))
    )
    assert actual_stop_risk <= expected_cap
    assert decision.quantity <= requested


def test_frozen_sim_sizing_exhausted_aggregate_cap_produces_no_risk_admission() -> None:
    session, frame, review = _session(), _frame(), _review()
    sizing = FrozenSimSizing("1000", "10")
    assert sizing.quantity(review.intent, session, frame) == 0
    decision = SimulationRiskPolicy().evaluate(
        session=session,
        review=review,
        selected_book_frame=frame,
        decided_at_ms=T0 + 60_100,
        requested_quantity=sizing.quantity(review.intent, session, frame),
    )
    assert not decision.approved
    assert decision.quantity == 0
    assert "REQUESTED_QUANTITY_INVALID" in decision.rejection_reasons


def _database(database_name: str, *, profile: MigrationProfile, host: str = "localhost") -> Database:
    url = f"postgresql://kairos:kairos@{host}:5432/{database_name}"
    return Database(
        settings=PersistenceSettings(database_url=url),
        migration_profile=profile,
    )


@pytest.mark.parametrize(
    ("database_name", "profile", "host"),
    [
        ("kairos", MigrationProfile.RUNTIME, "localhost"),
        ("kairos_sim_test_campaign_not-a-uuid", MigrationProfile.RESEARCH_CAMPAIGN, "localhost"),
        (CAMPAIGN_DB, MigrationProfile.RESEARCH_CAMPAIGN, "database.internal"),
        (CAMPAIGN_DB, MigrationProfile.SIMULATOR, "localhost"),
    ],
)
def test_campaign_target_guard_rejects_unsafe_target_before_connection(
    database_name: str, profile: MigrationProfile, host: str
) -> None:
    database = _database(database_name, profile=profile, host=host)
    with pytest.raises((TypeError, ValueError)):
        require_disposable_campaign_database(database)
    assert database._pool is None


def test_campaign_target_guard_accepts_only_exact_local_uuid4_target_without_connecting() -> None:
    assert UUID(hex=CAMPAIGN_UUID).version == 4
    database = _database(CAMPAIGN_DB, profile=MigrationProfile.RESEARCH_CAMPAIGN)
    assert require_disposable_campaign_database(database) == CAMPAIGN_DB
    assert database._pool is None


def test_primary_database_cannot_be_constructed_as_research_campaign_target() -> None:
    with pytest.raises(ValueError, match="simulator migration_profile"):
        _database("kairos", profile=MigrationProfile.RESEARCH_CAMPAIGN)


def test_sealed_bar_window_has_exact_minute_geometry_and_is_immutable() -> None:
    window = SealedBarWindowV1(
        tape_id="sealed-fixture",
        tape_sha256=SHA_A,
        symbol="BTCUSDT",
        first_open_ms=T0,
        last_open_ms=T0 + 2 * 60_000,
        bar_count=3,
        window_sha256=SHA_B,
    )
    with pytest.raises(ValidationError):
        window.bar_count = 4  # type: ignore[misc]
    with pytest.raises(ValidationError):
        SealedBarWindowV1(
            tape_id="sealed-fixture",
            tape_sha256=SHA_A,
            symbol="BTCUSDT",
            first_open_ms=T0,
            last_open_ms=T0 + 3 * 60_000,
            bar_count=3,
            window_sha256=SHA_B,
        )
    with pytest.raises(ValidationError):
        SealedBarWindowV1(
            tape_id="sealed-fixture",
            tape_sha256=SHA_A,
            symbol="BTCUSDT",
            first_open_ms=T0 + 1,
            last_open_ms=T0 + 2 * 60_000 + 1,
            bar_count=3,
            window_sha256=SHA_B,
        )
