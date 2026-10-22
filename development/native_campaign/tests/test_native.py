"""Opt-in native A/B + SIM composition acceptance on a disposable local DB.

This target proves engineering contracts only. Every bar, producer message,
model response, token count and equity amount is synthetic. It has no credential,
network transport, execution/admission, campaign qualification, or economic claim.
The selected database must be separately prepared; this test never creates,
migrates, resets, or deletes a database.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from kairos_aggregator.candidate_review import (
    CAUSAL_CANDIDATE_REVIEW_SYSTEM,
    CandidateReviewOutput,
)
from kairos_core import (
    AdaptiveCandidateProtocolV1,
    LLMProposalAction,
    LLMProposalAdaptiveCandidateArmV1,
    MarketSnapshot,
    ResearchObservationScheduleV1,
    ResearchObservationWindowV1,
    SentimentSignal,
    StrategicAllocation,
    StrategyOnlyAdaptiveCandidateArmV1,
    StrategyReviewAdaptiveCandidateArmV1,
    canonical_sha256,
)
from kairos_core.contracts.market import DerivativesMetrics, OrderBookSummary, TechnicalIndicators
from kairos_core.enums import ReviewDecision
from kairos_llm.budget import BudgetedLLMGateway
from kairos_llm.causal_campaign import (
    CausalReviewContextProjector,
    CausalRouterContextPolicyV1,
)
from kairos_llm.config import LLMSettings
from kairos_llm.gateway import LLMGateway
from kairos_llm.models import LLMWorkload, ModelRouter, Provider
from kairos_llm.proposals import LLMProposalOutputV1
from kairos_llm.research import RESEARCH_INPUT_FEATURE_SHA256, ResearchPromptArtifactV1
from kairos_persistence import (
    Database,
    MessageIdentityConflict,
    MigrationProfile,
    PersistenceSettings,
    ResearchAdaptiveCandidateProtocolRepository,
    ResearchObservationScheduleRepository,
)
from kairos_persistence.campaign_inputs import CampaignInputCaptureBridge
from kairos_persistence.causal_campaign import campaign_bar_window_sha256
from kairos_persistence.database_target import connect_verified_database, require_database_target_url
from kairos_persistence.research_campaign import (
    ResearchCampaignPlanV1,
    ResearchCampaignRepository,
    ResearchCaptureRequirementV1,
)
from kairos_persistence.simulation_repository import SimulationRepository
from kairos_persistence.source_state import QUALIFICATION_CAMPAIGN_ID, SourceStateRepository
from kairos_persistence.usage_budget import CampaignLLMUsageBudget
from kairos_strategy.campaign import CausalStrategyEvaluator
from kairos_strategy.sleeves import RangeMeanReversionConfig
from pydantic import ValidationError

from kairos_native_campaign.contracts import NativeReviewRiskReceiptV1
from kairos_native_campaign.scheduler import (
    CONTEXT_RENDERER,
    FrozenSimSizing,
    NativeCandidateReviewScheduler,
    NativeSimPolicy,
    native_review_artifact_sha256,
    native_scheduler_sha256,
)
from kairos_native_campaign.storage import (
    NativeReviewRiskJournal,
    ReadOnlySealedBarWindowResolver,
    SealedBarWindowV1,
)
from kairos_native_campaign.transport import NoNetworkReply, NoNetworkResponsesTransport

from .native_fixtures import (
    SYMBOLS,
    book_frame,
    fixture_produced_at,
    historical_adoption_sha256,
    parity_history,
    projector_fixture,
    simulation_session,
    strategy_evaluator,
)

_DB_PREFIX = "kairos_sim_test_campaign_"
_HISTORICAL_COST = 6_000_000
_OPENAI_CAP = 12_000_000


def _router(*, conflict: bool) -> ModelRouter:
    del conflict  # The pinned router owns the exact gpt-6.1-sol/high route.
    return ModelRouter(allowed_providers={Provider.OPENAI})


def _prompt(router: ModelRouter, workload: LLMWorkload, *, review: bool) -> ResearchPromptArtifactV1:
    route = router.resolve(workload=workload)
    return ResearchPromptArtifactV1(
        system=CAUSAL_CANDIDATE_REVIEW_SYSTEM if review else "Synthetic no-proposal classification only.",
        user_prefix=CONTEXT_RENDERER if review else "Synthetic proposal evidence:",
        workload=workload,
        reasoning_effort=route.effort.value,
        provider_effort=route.choice.provider_effort,
        max_output_tokens=route.max_output_tokens,
    )


async def _write_tape_bars(database: Database, *, tape_id: str, now_ms: int, quiet: bool):
    simulation = SimulationRepository(database.pool)
    all_bars = {symbol: parity_history(now_ms, quiet=quiet, symbol=symbol) for symbol in SYMBOLS}
    for symbol in SYMBOLS:
        for bar in all_bars[symbol]:
            assert await simulation.record_closed_bar(tape_id, bar)
    return all_bars


async def _seal_tape(database: Database, *, tape_id: str, all_bars, at_ms: int):
    simulation = SimulationRepository(database.pool)
    previous = None
    for sequence, symbol in enumerate(SYMBOLS, start=1):
        frame = book_frame(
            tape_id=tape_id,
            symbol=symbol,
            sequence=sequence,
            at_ms=at_ms,
            previous_sha256=previous,
        )
        assert await simulation.record_book_frame(frame)
        previous = frame.frame_sha256
    seal = await simulation.seal_tape(tape_id, sealed_at_ms=at_ms)
    session = simulation_session(tape_id=tape_id, tape_sha256=seal.tape_sha256, at_ms=at_ms)
    assert await simulation.create_session(session)
    reference = f"synthetic-window:{tape_id}:BTCUSDT"
    bars = all_bars["BTCUSDT"]
    window = SealedBarWindowV1(
        tape_id=tape_id,
        tape_sha256=seal.tape_sha256,
        symbol="BTCUSDT",
        first_open_ms=bars[0].open_time_ms,
        last_open_ms=bars[-1].open_time_ms,
        bar_count=len(bars),
        window_sha256=campaign_bar_window_sha256(bars),
    )
    return session, reference, bars, window


async def _wait_for_database_clock(repository, target_ms: int, *, timeout_s: float):
    async with asyncio.timeout(timeout_s):
        remaining = target_ms - await repository.clock()
        while remaining > 0:
            await asyncio.sleep(min(0.05, remaining / 1_000))
            remaining = target_ms - await repository.clock()


async def _register_capture(
    *,
    database: Database,
    campaign_id: str,
    sample_id: str,
    projector: CausalReviewContextProjector,
    router: ModelRouter,
    session,
    reference: str,
    bars,
    resolver: ReadOnlySealedBarWindowResolver,
    conflict: bool,
    quiet: bool,
    sentiment: float,
    review_decision: ReviewDecision,
    replies: tuple[NoNetworkReply, ...],
    repository: ResearchCampaignRepository,
):
    now_ms = await repository.clock()
    campaign_projector = projector
    window = ResearchObservationWindowV1(
        sample_id=sample_id,
        symbol="BTCUSDT",
        timeframe="1m",
        market_as_of_ts_ms=now_ms + 500,
        paired_at_ts_ms=now_ms + 8_000,
        sample_deadline_ts_ms=now_ms + 12_000,
    )
    config = RangeMeanReversionConfig(
        vwap_lookback_bars=3,
        atr_period=2,
        regime_lookback_hours=2,
        maximum_regime_efficiency=1,
        maximum_abs_hourly_slope=1,
        band_atr_multiple=0.5,
        stop_atr_multiple=1,
        max_hold_bars=6,
    )
    prototype = CausalStrategyEvaluator(
        strategy_id="range_mean_reversion_v1",
        strategy_revision="1",
        config=config,
        minimum_window_bars=200,
        bar_window_resolver=resolver,
        campaign_id=campaign_id,
        schedule_digest="1" * 64,
        candidate_protocol_digest="2" * 64,
    )
    schedule = ResearchObservationScheduleV1(
        campaign_id=campaign_id,
        strategy_id=prototype.strategy_id,
        strategy_revision=prototype.strategy_revision,
        source_set_sha256="a" * 64,
        evaluator_sha256=prototype.artifact_sha256,
        windows=(window,),
    )
    review_workload = LLMWorkload.AGGREGATOR_CONFLICT if conflict else LLMWorkload.AGGREGATOR_NORMAL
    review_prompt = _prompt(router, review_workload, review=True)
    proposal_prompt = _prompt(router, LLMWorkload.AGGREGATOR_NORMAL, review=False)
    sizing = FrozenSimSizing(equity_usd="10000", existing_open_risk_usd="0")
    sim_policy = NativeSimPolicy(sizing=sizing, sessions=((sample_id, session),))
    review_artifact = native_review_artifact_sha256(campaign_projector)
    common = {
        "candidate_revision": "native-engineering-only",
        "artifact_sha256": "c" * 64,
        "decision_mapping_sha256": "d" * 64,
        "hypothetical_exit_sha256": sim_policy.artifact_sha256,
        "cost_model_sha256": sizing.artifact_sha256,
    }
    review_route = router.resolve(workload=review_workload)
    proposal_route = router.resolve(workload=LLMWorkload.AGGREGATOR_NORMAL)
    protocol = AdaptiveCandidateProtocolV1(
        campaign_id=campaign_id,
        schedule_digest=schedule.schedule_digest,
        arms=(
            StrategyOnlyAdaptiveCandidateArmV1(
                candidate_id="native-baseline",
                input_feature_sha256=RESEARCH_INPUT_FEATURE_SHA256,
                **common,
            ),
            StrategyReviewAdaptiveCandidateArmV1(
                candidate_id="native-review",
                input_feature_sha256=review_artifact,
                schema_sha256=canonical_sha256(CandidateReviewOutput.model_json_schema()),
                **common,
                provider="openai",
                model=review_route.choice.model,
                prompt_sha256=review_prompt.prompt_sha256,
            ),
            LLMProposalAdaptiveCandidateArmV1(
                candidate_id="native-proposal",
                input_feature_sha256=RESEARCH_INPUT_FEATURE_SHA256,
                schema_sha256=canonical_sha256(LLMProposalOutputV1.model_json_schema()),
                **common,
                provider="openai",
                model=proposal_route.choice.model,
                prompt_sha256=proposal_prompt.prompt_sha256,
            ),
        ),
    )
    scheduler_sha256 = native_scheduler_sha256(campaign_projector, sim_policy)
    required_sources = tuple(
        ResearchCaptureRequirementV1(source_kind=kind, source_name=name, maximum_age_ms=10_000)
        for kind, name in (("MACRO", "macro"), ("MARKET_SNAPSHOT", "bars"), ("NEWS", "news"))
    )
    plan = ResearchCampaignPlanV1(
        campaign_id=campaign_id,
        schedule_digest=schedule.schedule_digest,
        candidate_protocol_digest=protocol.protocol_digest,
        recording_mode="OFFLINE_ENGINEERING_FIXTURE",
        scheduler_sha256=scheduler_sha256,
        required_sources=required_sources,
        maximum_windows_per_tick=1,
        maximum_clock_skew_ms=2_000,
        maximum_call_seconds=2,
    )
    campaign_repository = ResearchCampaignRepository(
        database,
        causal_scheduler_sha256=scheduler_sha256,
    )
    await ResearchObservationScheduleRepository(database).register(schedule)
    await ResearchAdaptiveCandidateProtocolRepository(database).register(protocol)
    assert await campaign_repository.register(plan)
    bridge = CampaignInputCaptureBridge(campaign_repository, bar_window_resolver=resolver)
    observed_now = await campaign_repository.clock()
    at = fixture_produced_at(observed_now)
    await bridge.capture_news(
        campaign_id=campaign_id,
        sample_id=sample_id,
        source_name="news",
        payload=SentimentSignal(
            source="text-scouts",
            message_id=f"synthetic-news-{campaign_id}",
            schema_version="1.0",
            produced_at=at,
            topic="BTCUSDT",
            sentiment=sentiment,
            impact="bearish" if sentiment < 0 else "neutral",
            confidence=0.95 if abs(sentiment) >= 0.7 else 0.4,
            sources=["https://example.invalid/synthetic-only"],
        ),
    )
    await bridge.capture_macro(
        campaign_id=campaign_id,
        sample_id=sample_id,
        source_name="macro",
        payload=StrategicAllocation(
            source="macro-strategist",
            message_id=f"synthetic-macro-{campaign_id}",
            schema_version="1.0",
            produced_at=at,
            regime="CHOP",
            stable_reserve_pct=1.0,
        ),
    )
    await bridge.capture_market(
        campaign_id=campaign_id,
        sample_id=sample_id,
        source_name="bars",
        payload=MarketSnapshot(
            source="quant-scouts",
            message_id=f"synthetic-market-{campaign_id}",
            schema_version="1.0",
            produced_at=at,
            symbol="BTCUSDT",
            timeframe="1m",
            mid_price=100.0 if quiet else 98.0,
            volume_usd=1_000,
            order_book=OrderBookSummary(
                best_bid=99.9 if quiet else 97.9,
                best_ask=100.1 if quiet else 98.1,
                spread_bps=20,
                imbalance=0,
                depth_usd=1_000,
            ),
            derivatives=DerivativesMetrics(funding_rate=0, open_interest=1_000),
            indicators=TechnicalIndicators(rsi_14=50, macd=0, macd_signal=0, macd_hist=0),
        ),
        bars=bars,
        bar_window_reference=reference,
    )
    evaluator = CausalStrategyEvaluator(
        strategy_id=prototype.strategy_id,
        strategy_revision=prototype.strategy_revision,
        config=config,
        minimum_window_bars=200,
        bar_window_resolver=resolver,
        campaign_id=campaign_id,
        schedule_digest=schedule.schedule_digest,
        candidate_protocol_digest=protocol.protocol_digest,
    )
    assert evaluator.artifact_sha256 == schedule.evaluator_sha256
    transport = NoNetworkResponsesTransport(replies)
    llm = LLMGateway(
        LLMSettings(
            _env_file=None,
            openai_api_key=None,
            deepseek_api_key=None,
            max_retries=0,
            request_timeout_s=1.0,
            max_output_tokens=8_192,
        ),
        router=router,
        client=transport,
    )
    gateway = BudgetedLLMGateway(
        llm,
        CampaignLLMUsageBudget(
            SourceStateRepository(
                database.pool,
                campaign_id=QUALIFICATION_CAMPAIGN_ID,
            )
        ),
    )
    scheduler = NativeCandidateReviewScheduler(
        database=database,
        sim_policy=sim_policy,
        repository=campaign_repository,
        gateway=gateway,
        evaluator=evaluator,
        projector=campaign_projector,
        review_prompt=review_prompt,
        proposal_prompt=proposal_prompt,
        clock=lambda: time.time_ns() // 1_000_000,
    )
    return {
        "campaign_id": campaign_id,
        "sample_id": sample_id,
        "schedule": schedule,
        "protocol": protocol,
        "sim_policy": sim_policy,
        "scheduler": scheduler,
        "transport": transport,
        "review_decision": review_decision,
    }


@pytest.mark.asyncio
async def test_native_candidate_review_risk_budget_restart_on_disposable_campaign_db():
    """Exercise actual pinned strategy/router/LLM/SIM/Persistence code offline."""
    url = os.getenv("KAIROS_NATIVE_CAMPAIGN_TEST_DATABASE_URL")
    if not url:
        pytest.skip("explicit disposable RESEARCH_CAMPAIGN test DB required")
    database_name = urlsplit(url).path.removeprefix("/")
    if not database_name.startswith(_DB_PREFIX) or len(database_name) != len(_DB_PREFIX) + 32:
        raise RuntimeError("refusing non-disposable native campaign target")
    suffix = database_name.removeprefix(_DB_PREFIX)
    namespace = UUID(hex=suffix)
    if namespace.version != 4 or namespace.hex != suffix:
        raise RuntimeError("native campaign test requires exact UUID4 database identity")
    require_database_target_url(url, database_name, local_only=True)

    async def connect():
        current = Database(
            PersistenceSettings(
                _env_file=None,
                database_url=url,
                pool_min_size=1,
                pool_max_size=4,
                command_timeout_s=5,
            ),
            migration_profile=MigrationProfile.RESEARCH_CAMPAIGN,
        )
        try:
            await connect_verified_database(current, database_name, local_only=True)
            await current.verify_schema()
        except BaseException:
            await current.close()
            raise
        return current, ResearchCampaignRepository(current)

    async with asyncio.timeout(90):
        database, unbound_repository = await connect()
        projector = CausalReviewContextProjector(
            CausalRouterContextPolicyV1(
                sentiment_ttl_s=600.0,
                deadband=0.25,
                minimum_confidence=0.25,
                maximum_evidence=5,
                trading_symbols=SYMBOLS,
            )
        )
        source_state = SourceStateRepository(
            database.pool,
            campaign_id=QUALIFICATION_CAMPAIGN_ID,
        )
        try:
            tables = (
                "sim_tapes",
                "sim_closed_bars",
                "sim_book_frames",
                "sim_sessions",
                "sim_risk_decisions",
                "sim_research_observation_schedules",
                "sim_research_adaptive_candidate_protocols",
                "sim_adaptive_campaign_plans",
                "sim_adaptive_window_claims",
                "sim_adaptive_campaign_receipts",
                "sim_adaptive_campaign_denominators",
            )
            for table in tables:
                count = await database.pool.fetchval(f"SELECT count(*) FROM {table}")
                assert count == 0, f"fresh disposable DB required; {table} already contains rows"
            native_receipts = await database.pool.fetchval(
                "SELECT count(*) FROM event_audit WHERE topic='native.review-risk.v1'"
            )
            assert native_receipts == 0
            existing_adoption = await database.pool.fetchval(
                "SELECT count(*) FROM campaign_source_budgets WHERE source='openai'"
            )
            assert existing_adoption == 0, "adoption is written exactly once by this isolated test"

            await source_state.register_campaign(
                source="openai",
                budget_microusd=_OPENAI_CAP,
                historical_cost_microusd=_HISTORICAL_COST,
                historical_evidence_sha256=historical_adoption_sha256(),
            )
            initial_usage = await source_state.campaign_usage("openai")
            assert initial_usage.historical_cost_microusd == _HISTORICAL_COST
            assert initial_usage.budget_microusd == _OPENAI_CAP
            assert initial_usage.committed_cost_microusd == initial_usage.reserved_cost_microusd == 0

            now = await unbound_repository.clock()
            if now % 300_000 >= 285_000:
                await _wait_for_database_clock(
                    unbound_repository,
                    now // 300_000 * 300_000 + 300_001,
                    timeout_s=16,
                )
                now = await unbound_repository.clock()
            matching_tape_id = f"native-match-{uuid4().hex}"
            quiet_tape_id = f"native-quiet-{uuid4().hex}"
            matching_all_bars = await _write_tape_bars(
                database,
                tape_id=matching_tape_id,
                now_ms=now,
                quiet=False,
            )
            quiet_all_bars = await _write_tape_bars(
                database,
                tape_id=quiet_tape_id,
                now_ms=now,
                quiet=True,
            )
            book_at_ms = time.time_ns() // 1_000_000
            matching_session, matching_ref, matching_bars, matching_window = await _seal_tape(
                database,
                tape_id=matching_tape_id,
                all_bars=matching_all_bars,
                at_ms=book_at_ms,
            )
            quiet_session, quiet_ref, quiet_bars, quiet_window = await _seal_tape(
                database,
                tape_id=quiet_tape_id,
                all_bars=quiet_all_bars,
                at_ms=book_at_ms,
            )
            resolver = ReadOnlySealedBarWindowResolver(
                database,
                {matching_ref: matching_window, quiet_ref: quiet_window},
            )
            projector = projector_fixture()

            async def setup_case(name: str, *, conflict=False, quiet=False, sentiment=-0.1, decision="ALLOW"):
                decision_value = ReviewDecision(decision)
                case_router = _router(conflict=conflict)
                review_workload = (
                    LLMWorkload.AGGREGATOR_CONFLICT if conflict else LLMWorkload.AGGREGATOR_NORMAL
                )
                review_schema = CandidateReviewOutput(
                    decision=decision_value,
                    priority=50,
                    reason_codes=("SYNTHETIC_FIXTURE",),
                )
                proposal = LLMProposalOutputV1(
                    contract_version="kairos-llm-proposal-output.v1",
                    action=LLMProposalAction.NO_PROPOSAL,
                    rationale="Synthetic fixture deliberately emits no proposal.",
                    evidence_ids=(),
                )
                selected_session = quiet_session if quiet else matching_session
                selected_ref = quiet_ref if quiet else matching_ref
                selected_bars = quiet_bars if quiet else matching_bars
                replies = (
                    ()
                    if name in {"budget-denied", "ambiguous"}
                    else (
                        NoNetworkReply(
                            schema_name="CandidateReviewOutput",
                            model=case_router.resolve(workload=review_workload).choice.model,
                            output_json=review_schema.model_dump_json(),
                        ),
                        NoNetworkReply(
                            schema_name="LLMProposalOutputV1",
                            model=case_router.resolve(workload=LLMWorkload.AGGREGATOR_NORMAL).choice.model,
                            output_json=proposal.model_dump_json(),
                        ),
                    )
                )
                if quiet:
                    replies = replies[1:]  # NO_INTENT must not dispatch a review response.
                case = await _register_capture(
                    database=database,
                    campaign_id=f"native-{name}-{uuid4().hex[:12]}",
                    sample_id=f"sample-{name}",
                    projector=projector,
                    router=case_router,
                    session=selected_session,
                    reference=selected_ref,
                    bars=selected_bars,
                    resolver=resolver,
                    conflict=conflict,
                    quiet=quiet,
                    sentiment=sentiment,
                    review_decision=decision_value,
                    replies=replies,
                    repository=unbound_repository,
                )
                case["bar_windows"] = {
                    matching_ref: matching_window,
                    quiet_ref: quiet_window,
                }
                case["projector"] = projector
                await _wait_for_database_clock(
                    case["scheduler"].repository,
                    case["schedule"].windows[0].market_as_of_ts_ms,
                    timeout_s=1.0,
                )
                return case

            # Independent, explicitly preregistered campaigns preserve each
            # route/schema identity while sharing one adopted PostgreSQL ledger.
            # Each case executes immediately so its paired cutoff remains live.
            results = {}
            cases = {}
            for name, options in (
                ("allow", {"sentiment": 0.0, "decision": "ALLOW"}),
                ("veto", {"sentiment": 0.0, "decision": "VETO"}),
                ("defer", {"sentiment": 0.0, "decision": "DEFER"}),
                ("conflict", {"conflict": True, "sentiment": -0.95, "decision": "ALLOW"}),
                ("quiet", {"quiet": True, "sentiment": 0.0, "decision": "ALLOW"}),
                ("budget-denied", {"sentiment": 0.0, "decision": "ALLOW"}),
                ("ambiguous", {"sentiment": 0.0, "decision": "ALLOW"}),
            ):
                case = await setup_case(name, **options)
                cases[name] = case
                if name == "budget-denied":
                    case["scheduler"].gateway.monthly_budgets_microusd[Provider.OPENAI] = _HISTORICAL_COST - 1
                    evaluator_errors = []
                    case["evaluator_errors"] = evaluator_errors
                    previous_trace = sys.gettrace()

                    def capture_scheduler_exception(frame, event, args, errors=evaluator_errors):
                        if (
                            event == "exception"
                            and frame.f_code.co_name == "run_once"
                            and frame.f_code.co_filename.replace("\\", "/").endswith(
                                "/kairos_llm/campaign.py"
                            )
                            and 155 <= frame.f_lineno <= 167
                        ):
                            # Record only a source line and exception class; exception text can
                            # contain SQL, connection details, or credentials.
                            errors.append(f"line-{frame.f_lineno}:{args[0].__name__}")
                        return capture_scheduler_exception

                    sys.settrace(capture_scheduler_exception)
                    try:
                        results[name] = await case["scheduler"].run_once(case["campaign_id"])
                    finally:
                        sys.settrace(previous_trace)
                else:
                    results[name] = await case["scheduler"].run_once(case["campaign_id"])
                denominator = await case["scheduler"].repository.seal_denominator(case["campaign_id"])
                assert denominator.expected_outcomes == 3
                assert denominator.qualification == "SCHEDULED_DENOMINATOR_ONLY"
                assert denominator.economic_qualification is False
                assert denominator.live_orders_allowed is False

            def outcome_statuses(name):
                return tuple(item.status for item in results[name])

            assert outcome_statuses("allow") == ("BASELINE", "ALLOW", "PROPOSAL")
            assert outcome_statuses("veto") == ("BASELINE", "VETO", "PROPOSAL")
            assert outcome_statuses("defer") == ("BASELINE", "DEFER", "PROPOSAL")
            assert outcome_statuses("conflict") == ("BASELINE", "DEFER", "PROPOSAL")
            assert outcome_statuses("quiet") == ("NO_INTENT", "NO_INTENT", "PROPOSAL")
            assert outcome_statuses("budget-denied") == (
                "BASELINE",
                "BUDGET_BLOCKED",
                "BUDGET_BLOCKED",
            ), f"sanitized evaluator diagnostics={cases['budget-denied']['evaluator_errors']}"
            assert outcome_statuses("ambiguous") == ("BASELINE", "UNKNOWN", "UNKNOWN")
            ambiguous = cases["ambiguous"]
            assert len(ambiguous["transport"].calls) == 2
            unknown_usage = await source_state.campaign_usage("openai")
            assert unknown_usage.reserved_cost_microusd > 0
            assert await ambiguous["scheduler"].run_once(ambiguous["campaign_id"]) == ()
            assert len(ambiguous["transport"].calls) == 2  # Never resend unknown attempts.
            assert await source_state.campaign_usage("openai") == unknown_usage

            fault = await setup_case("fault-after-save", sentiment=0.0, decision="ALLOW")
            cases["fault-after-save"] = fault
            normal = cases["allow"]
            veto = cases["veto"]
            defer = cases["defer"]
            conflict = cases["conflict"]
            quiet = cases["quiet"]
            budget_denied = cases["budget-denied"]

            allow_receipt = await NativeReviewRiskJournal(database).load(
                normal["campaign_id"], normal["sample_id"]
            )
            veto_receipt = await NativeReviewRiskJournal(database).load(
                veto["campaign_id"], veto["sample_id"]
            )
            defer_receipt = await NativeReviewRiskJournal(database).load(
                defer["campaign_id"], defer["sample_id"]
            )
            conflict_receipt = await NativeReviewRiskJournal(database).load(
                conflict["campaign_id"], conflict["sample_id"]
            )
            quiet_receipt = await NativeReviewRiskJournal(database).load(
                quiet["campaign_id"], quiet["sample_id"]
            )
            budget_receipt = await NativeReviewRiskJournal(database).load(
                budget_denied["campaign_id"], budget_denied["sample_id"]
            )
            assert type(allow_receipt) is NativeReviewRiskReceiptV1
            assert all(
                type(receipt) is NativeReviewRiskReceiptV1
                for receipt in (veto_receipt, defer_receipt, conflict_receipt)
            )
            assert quiet_receipt is None
            assert type(budget_receipt) is NativeReviewRiskReceiptV1
            assert allow_receipt.candidate_review.decision is ReviewDecision.ALLOW
            assert allow_receipt.sim_risk_decision.approved
            assert veto_receipt.candidate_review.decision is ReviewDecision.VETO
            assert not veto_receipt.sim_risk_decision.approved
            assert defer_receipt.candidate_review.decision is ReviewDecision.DEFER
            assert not defer_receipt.sim_risk_decision.approved
            assert conflict_receipt.candidate_review.decision is ReviewDecision.DEFER
            assert "CONFLICT_ALLOW_GUARD" in conflict_receipt.candidate_review.reason_codes
            assert not conflict_receipt.sim_risk_decision.approved
            assert budget_receipt.start is None
            assert (
                conflict["scheduler"]
                .gateway.router.resolve(workload=LLMWorkload.AGGREGATOR_CONFLICT)
                .choice.model
                == "gpt-6.1-sol"
            )
            assert len(conflict["transport"].calls) == 2
            assert len(quiet["transport"].calls) == 1
            assert len(budget_denied["transport"].calls) == 0
            assert conflict["transport"].calls[0]["text_format"] is CandidateReviewOutput
            assert conflict["transport"].calls[0]["model"] == "gpt-6.1-sol"
            assert conflict["transport"].calls[1]["text_format"] is LLMProposalOutputV1
            assert quiet["transport"].calls[0]["text_format"] is LLMProposalOutputV1
            quiet_state = await quiet["scheduler"].repository.window_state(
                quiet["campaign_id"], quiet["sample_id"]
            )
            assert quiet_state[("evaluation", "all", "one")].intent is None
            assert not any(kind == "start" and arm == "strategy-review" for kind, arm, _ in quiet_state)
            assert quiet_state[("sample", "llm-proposal-research", "one")].llm_outcome == "NO_PROPOSAL"
            quiet_risk_count = await database.pool.fetchval(
                "SELECT count(*) FROM sim_risk_decisions WHERE session_id=$1",
                quiet["sim_policy"].sessions[0][1].session_id,
            )
            assert quiet_risk_count == 0

            receipt_cases = (
                (allow_receipt, normal),
                (veto_receipt, veto),
                (defer_receipt, defer),
                (conflict_receipt, conflict),
            )
            for receipt, case in receipt_cases:
                assert receipt.authority == "SIM_RESEARCH_ONLY"
                assert receipt.source == "native-campaign-composition"
                assert receipt.start is not None and receipt.normalized_review is not None
                assert receipt.start.requested_model == receipt.candidate_review.model_provenance.model
                assert receipt.start.prompt_sha256 == receipt.normalized_review.prompt_sha256
                assert (
                    receipt.normalized_review.response_sha256
                    == receipt.candidate_review.model_provenance.response_sha256
                )
                assert (
                    receipt.normalized_review.request_id
                    == receipt.candidate_review.model_provenance.request_id
                )
                assert receipt.scheduler_sha256 == case["scheduler"].scheduler_sha256
                assert receipt.candidate_review.intent.decision_ts_ms < receipt.start.market_as_of_ts_ms
                assert receipt.start.market_as_of_ts_ms < receipt.candidate_review.route.routed_at_ms
                assert receipt.sizing_sha256 == case["sim_policy"].sizing.artifact_sha256

            # Stored identity, protocol, source, anchor/cutoff, candidate, model,
            # book, sizing and risk all survive canonical revalidation. Adversarial
            # source/hash/session/stable-ID rewrites must fail before journaling.
            with pytest.raises(ValidationError):
                NativeReviewRiskReceiptV1.model_validate(
                    allow_receipt.model_dump(mode="python") | {"message_id": "f" * 64}
                )
            for field in (
                "plan_receipt_sha256",
                "bundle_receipt_sha256",
                "evaluation_receipt_sha256",
                "scheduler_sha256",
                "sizing_sha256",
            ):
                with pytest.raises(ValidationError):
                    NativeReviewRiskReceiptV1.model_validate(
                        allow_receipt.model_dump(mode="python") | {field: "0" * 64}
                    )
            tampered_decision = allow_receipt.sim_risk_decision.model_copy(
                update={
                    "session": allow_receipt.sim_risk_decision.session.model_copy(
                        update={"ends_at_ms": 999_999_999_999}
                    )
                }
            )
            with pytest.raises(ValidationError):
                NativeReviewRiskReceiptV1.model_validate(
                    allow_receipt.model_dump(mode="python") | {"sim_risk_decision": tampered_decision}
                )

            # Durable shared usage retains adoption and every committed scenario
            # spend; lower-cap denial is recorded without a transport dispatch.
            usage_before_restart = await source_state.campaign_usage("openai")
            assert usage_before_restart.historical_cost_microusd == _HISTORICAL_COST
            assert usage_before_restart.committed_cost_microusd > 0
            assert usage_before_restart.reserved_cost_microusd == unknown_usage.reserved_cost_microusd
            assert usage_before_restart.budgeted_cost_microusd <= _OPENAI_CAP

            # Inject exactly one failure after NativeReviewRiskJournal.save and
            # before the scheduler writes SIM risk/normalized campaign review.
            fault_scheduler = fault["scheduler"]
            original_persist = fault_scheduler._persist_saved
            injected = {"raised": False}

            async def fail_once(receipt):
                if not injected["raised"]:
                    injected["raised"] = True
                    raise RuntimeError("synthetic post-journal interruption")
                await original_persist(receipt)

            fault_scheduler._persist_saved = fail_once
            fault_calls_before = len(fault["transport"].calls)
            try:
                await fault_scheduler.run_once(fault["campaign_id"])
                raise AssertionError("fault injection did not interrupt after native journal save")
            except RuntimeError as exc:
                assert str(exc) == "synthetic post-journal interruption"
            fault_saved = await NativeReviewRiskJournal(database).load(
                fault["campaign_id"], fault["sample_id"]
            )
            assert type(fault_saved) is NativeReviewRiskReceiptV1
            assert len(fault["transport"].calls) == fault_calls_before + 1
            usage_after_saved_response = await source_state.campaign_usage("openai")
            assert (
                usage_after_saved_response.committed_cost_microusd
                > usage_before_restart.committed_cost_microusd
            )
            assert (
                usage_after_saved_response.reserved_cost_microusd
                == usage_before_restart.reserved_cost_microusd
            )
            await database.close()

            # New DB/repository/journal/gateway/scheduler instances replay the
            # durable native bytes only: no model, evaluator or budget retry.
            database, _fresh_unbound_repository = await connect()
            fresh_source_state = SourceStateRepository(
                database.pool,
                campaign_id=QUALIFICATION_CAMPAIGN_ID,
            )
            fresh_usage_before = await fresh_source_state.campaign_usage("openai")
            assert fresh_usage_before.historical_cost_microusd == _HISTORICAL_COST
            assert fresh_usage_before == usage_after_saved_response
            fresh_journal = NativeReviewRiskJournal(database)
            assert await fresh_journal.load(fault["campaign_id"], fault["sample_id"]) == fault_saved
            fresh_resolver = ReadOnlySealedBarWindowResolver(database, fault["bar_windows"])
            fresh_evaluator = strategy_evaluator(
                fresh_resolver,
                fault["campaign_id"],
                fault["schedule"].schedule_digest,
                fault["protocol"].protocol_digest,
            )
            assert fresh_evaluator.artifact_sha256 == fault["schedule"].evaluator_sha256
            fresh_transport = NoNetworkResponsesTransport(())
            fresh_scheduler = NativeCandidateReviewScheduler(
                database=database,
                sim_policy=fault["sim_policy"],
                repository=ResearchCampaignRepository(
                    database,
                    causal_scheduler_sha256=fault["scheduler"].scheduler_sha256,
                ),
                gateway=BudgetedLLMGateway(
                    LLMGateway(
                        LLMSettings(
                            _env_file=None,
                            openai_api_key=None,
                            deepseek_api_key=None,
                            max_retries=0,
                            request_timeout_s=1.0,
                            max_output_tokens=8_192,
                        ),
                        router=fault["scheduler"].gateway.router,
                        client=fresh_transport,
                    ),
                    CampaignLLMUsageBudget(fresh_source_state),
                ),
                evaluator=fresh_evaluator,
                projector=fault["projector"],
                review_prompt=fault["scheduler"].review_prompt,
                proposal_prompt=fault["scheduler"].proposal_prompt,
                clock=lambda: time.time_ns() // 1_000_000,
            )
            evaluator_calls = {"count": 0}
            original_evaluate = fresh_scheduler.evaluator.evaluate

            async def counted_evaluate(**kwargs):
                evaluator_calls["count"] += 1
                return await original_evaluate(**kwargs)

            fresh_scheduler.evaluator.evaluate = counted_evaluate
            calls_before_reconcile = len(fresh_transport.calls)
            budget_before_reconcile = await fresh_source_state.campaign_usage("openai")
            await fresh_scheduler.reconcile(fault["campaign_id"])
            assert len(fresh_transport.calls) == calls_before_reconcile == 0
            assert evaluator_calls["count"] == 0
            budget_after_reconcile = await fresh_source_state.campaign_usage("openai")
            assert budget_after_reconcile == budget_before_reconcile

            # The proposal arm was intentionally never reached; wait only for
            # this fault case's actual DB paired cutoff, bounded by eight seconds.
            remaining = (
                fault["schedule"].windows[0].paired_at_ts_ms - await fresh_scheduler.repository.clock()
            )
            assert remaining <= 8_000
            async with asyncio.timeout(8):
                while remaining > 0:
                    await asyncio.sleep(min(0.05, remaining / 1_000))
                    remaining = (
                        fault["schedule"].windows[0].paired_at_ts_ms
                        - await fresh_scheduler.repository.clock()
                    )
            final_fault_outcomes = await fresh_scheduler.reconcile(fault["campaign_id"])
            assert any(
                item.arm_id == "llm-proposal-research" and item.status == "MISSED"
                for item in final_fault_outcomes
            )
            fault_denominator = await fresh_scheduler.repository.seal_denominator(fault["campaign_id"])
            assert fault_denominator.expected_outcomes == 3
            assert fault_denominator.status_counts.get("MISSED", 0) >= 1
            assert fault_denominator.qualification == "SCHEDULED_DENOMINATOR_ONLY"
            assert fault_denominator.economic_qualification is False
            assert fault_denominator.live_orders_allowed is False

            # No authority path was created by any engineering scenario.
            for table in ("sim_admissions", "sim_commands", "sim_command_receipts", "sim_trades"):
                count = await database.pool.fetchval(f"SELECT count(*) FROM {table}")
                assert count == 0
            for table in ("execution_orders",):
                present = await database.pool.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema=current_schema() AND table_name=$1)",
                    table,
                )
                if present:
                    count = await database.pool.fetchval(f"SELECT count(*) FROM {table}")
                    assert count == 0
            # SimulationRepository atomically queues its own diagnostic artifacts
            # in this isolated DB. No publisher is constructed and no runtime/
            # trade topic, lease, cursor or legacy outbox is accessed.
            assert (
                await database.pool.fetchval(
                    "SELECT count(*) FROM message_outbox WHERE producer <> 'kairos-market-simulator' "
                    "OR published_at IS NOT NULL OR topic NOT IN "
                    "('kairos.simulation.tape_seal.v1','kairos.simulation.session.v1',"
                    "'kairos.simulation.risk_decision.v1')"
                )
                == 0
            )
            readiness = await database.pool.fetchrow(
                "SELECT bool_or(paper_qualification_eligible) AS paper, "
                "bool_or(trial15_eligible) AS trial15, bool_or(alpha_claim) AS alpha "
                "FROM sim_sessions"
            )
            assert readiness["paper"] is False
            assert readiness["trial15"] is False
            assert readiness["alpha"] is False

            # Corrupt only this disposable fixture's unrelated XRP book chain.
            # The saved BTC bar tail still validates page-by-page, but replay
            # must reject the entire tape before adopting any saved decision.
            risk_count = await database.pool.fetchval("SELECT count(*) FROM sim_risk_decisions")
            receipts_count = await database.pool.fetchval(
                "SELECT count(*) FROM sim_adaptive_campaign_receipts"
            )
            usage_before_corruption = await fresh_source_state.campaign_usage("openai")
            update = await database.pool.execute(
                "UPDATE sim_book_frames SET chain_sha256=$2 WHERE tape_id=$1 AND symbol='XRPUSDT'",
                matching_tape_id,
                "0" * 64,
            )
            assert update == "UPDATE 1"
            saved_bars = next(x for x in fault_saved.decision_context.sources if x.kind == "closed_bars")
            unchanged_tail = await SimulationRepository(database.pool).load_closed_bar_page(
                matching_tape_id,
                "BTCUSDT",
                after_open_time_ms=saved_bars.payloads()[0]["open_time_ms"] - 60_000,
                limit=len(saved_bars.payloads()),
            )
            assert saved_bars.payloads() == tuple(bar.model_dump(mode="json") for bar in unchanged_tail)
            with pytest.raises(MessageIdentityConflict, match="full immutable-chain audit"):
                await fresh_scheduler._persist_saved(fault_saved)
            assert await database.pool.fetchval("SELECT count(*) FROM sim_risk_decisions") == risk_count
            assert (
                await database.pool.fetchval("SELECT count(*) FROM sim_adaptive_campaign_receipts")
                == receipts_count
            )
            assert await fresh_source_state.campaign_usage("openai") == usage_before_corruption
            assert len(fresh_transport.calls) == evaluator_calls["count"] == 0
        finally:
            await database.close()
