"""No-network CURRENT Catalyst/native adapter tests, not real model evidence."""

from dataclasses import replace
from functools import lru_cache
from types import SimpleNamespace

import pytest
from adaptive_replay import catalyst_policy_v1 as cp
from adaptive_replay import research_profile_v1 as rp
from adaptive_replay.catalyst_hypothesis_v1 import evaluate_hypothesis
from adaptive_replay.historical_context import HistoricalVersion, canonical, digest
from adaptive_replay.hypothesis_v3 import CreationAssessment, EntryQuote, HypothesisObservation
from adaptive_replay.inputs import UNIVERSE
from adaptive_replay.scenarios import MINUTE, ScenarioEvidence, ScenarioObservation
from kairos_aggregator.candidate_review import CandidateReviewBrain
from kairos_core.contracts import (
    DerivativesMetrics,
    MarketSnapshot,
    OrderBookSummary,
    RecordedBookLevelV1,
    RecordedTopNBookFrameV1,
    SentimentSignal,
    SimulationAssumptionsV1,
    SimulationSessionV1,
    SimulationStrategyRefV1,
    StrategicAllocation,
    TechnicalIndicators,
)
from kairos_core.contracts.base import datetime_from_unix_ms
from kairos_core.enums import ImpactDirection, MarketRegime, ReasoningEffort, Side, StrategicTrigger
from kairos_router.aggregation import TextAggregate
from kairos_strategy.candles import Candle
from kairos_strategy.provenance import candle_payload
from kairos_strategy.runtime import candle_to_closed_bar

from kairos_native_campaign.current_chain import (
    CurrentCatalystChain,
    bind_scenario_review,
    build_final_route,
    build_hypothesis_preview,
    build_native_context,
    decide_sim,
    native_intent,
    review_native,
)

START = 1_700_000_100_000
SYMBOL = sorted(UNIVERSE)[0]
REQUIRED = (("MACRO", "macro-fixture"), ("MARKET", "market-fixture"), ("NEWS", "news-fixture"))
NATIVE = dict(strategy_revision="current-chain.fixture.v1", code_sha256="a" * 64, config_sha256="b" * 64)


def policy():
    return cp.CatalystPolicy(
        rp.ResearchProfile(
            START - MINUTE,
            START,
            START + 30 * MINUTE,
            "c" * 64,
            "d" * 64,
            "quote-fixture",
            REQUIRED,
            "TEST_FIXTURE",
        )
    )


def sources(bar, clock):
    return tuple(
        ScenarioEvidence(
            source,
            kind,
            bar.symbol,
            digest(candle_payload(bar)),
            bar.close_time_ms,
            bar.close_time_ms,
            clock,
            10 * MINUTE,
        )
        for kind, source in REQUIRED
    )


def cells():
    result = []
    for symbol in sorted(UNIVERSE):
        rows = tuple(
            Candle(symbol, "1m", t, t + MINUTE - 1, 100.0, 100.7, 99.3, 100.0, 10.0)
            for t in range(START - rp.HISTORY_BARS * MINUTE, START, MINUTE)
        )
        price = rp.PriceCell(START, START + 100, symbol, rows, sources(rows[-1], START + 100), "AVAILABLE")
        events = ()
        if symbol == SYMBOL:
            payload = canonical({"headline": "Synthetic event", "body": "Fixture only."})
            version = HistoricalVersion(
                "version-1",
                "doc-1",
                "news-fixture",
                "NEWS",
                (symbol,),
                "https://example.test/event",
                payload,
                digest(payload),
                "e" * 64,
                START - 2000,
                START - 2000,
                START - 1,
                START - 1,
                "TEST_FIXTURE",
                "f" * 64,
            )
            events = (cp.CatalystEvent("news-fixture", "event-1", version, START - 1, 10 * MINUTE),)
        result.append(cp.CatalystCell(price, "KNOWN", events))
    return tuple(result)


@lru_cache(maxsize=1)
def prepared_plan():
    chain, prepared = CurrentCatalystChain.start(policy()).prepare(cells())
    slot = next(s for s in prepared.slots if s.cell.price.symbol == SYMBOL)
    assessment = CreationAssessment(
        slot.creation_input_sha256,
        "1" * 64,
        chain.policy.session.model_config_sha256,
        "LONG",
        START + 200,
        START + 210,
        START + 220,
        "TEST_FIXTURE",
    )
    outcome = rp.CreationOutcome("DIRECTION", "1" * 64, START + 220, assessment)
    chain, plans = chain.materialize(prepared, symbol=SYMBOL, origin="CONTEXT_PROPOSAL", outcome=outcome)
    plan = dict(plans)["independent_proposals"]
    bar = Candle(SYMBOL, "1m", START, START + MINUTE - 1, 100.0, 100.2, 99.9, 100.1, 10.0)
    observed = START + MINUTE + 100
    observation = HypothesisObservation(
        ScenarioObservation(bar, observed, sources(bar, observed)),
        EntryQuote(
            "quote-fixture", SYMBOL, 100.09, 100.10, START + MINUTE, observed, observed, 2_000, "TEST_FIXTURE"
        ),
    )
    bars = tuple(candle_to_closed_bar(b) for b in slot.cell.price.rows + (bar,))
    preview = build_hypothesis_preview(plan, (observation,), input_bars=bars, **NATIVE)
    return chain, prepared, outcome, plan, bars, preview


def native_context(intent):
    at = intent.decision_ts_ms
    text = SentimentSignal(
        source="fixture-text",
        produced_at=datetime_from_unix_ms(at - 1),
        topic=SYMBOL,
        sentiment=0.0,
        impact=ImpactDirection.NEUTRAL,
        confidence=0.9,
        sources=["https://example.test/event"],
        summary="Synthetic only",
    )
    route = build_final_route(intent, TextAggregate(sentiment_ids=(text.message_id,)))
    market = MarketSnapshot(
        source="fixture-market",
        produced_at=datetime_from_unix_ms(at),
        symbol=SYMBOL,
        mid_price=100.095,
        volume_usd=10000.0,
        order_book=OrderBookSummary(
            best_bid=100.09, best_ask=100.10, spread_bps=1.0, imbalance=0.0, depth_usd=10000.0
        ),
        derivatives=DerivativesMetrics(funding_rate=0.0, open_interest=1000.0),
        indicators=TechnicalIndicators(rsi_14=50.0, macd=0.0, macd_signal=0.0, macd_hist=0.0, atr_pct=0.01),
        quant_bias=Side.FLAT,
    )
    macro = StrategicAllocation(
        source="fixture-macro",
        produced_at=datetime_from_unix_ms(at - 1),
        regime=MarketRegime.CHOP,
        stable_reserve_pct=0.2,
        strategy_weights={intent.strategy_id: 0.8},
        max_gross_leverage=1.0,
        triggered_by=StrategicTrigger.SCHEDULE,
        rationale="Synthetic only",
    )
    return route, (("market", market, at), ("text", text, at), ("macro", macro, at))


class FixtureGateway:
    def __init__(self):
        self.calls = 0

    async def complete(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            parsed=kwargs["schema"].model_validate(
                dict(decision="ALLOW", priority=1, reason_codes=["FIXTURE_ONLY"])
            ),
            content='{"decision":"ALLOW"}',
            provider="fixture",
            model="fixture",
            resolved_model="fixture",
            request_id=f"fixture-{self.calls}",
            budget_reservation_id=f"fixture-zero-cost-{self.calls}",
            latency_s=0.0,
            cost_usd=0.0,
            effort=ReasoningEffort.MEDIUM,
        )


async def reviewed(intent, bars, *, gateway=None, completion_offset=10):
    route, receipts = native_context(intent)
    receipts += tuple(("closed_bars", bar, intent.decision_ts_ms) for bar in bars[-60:])
    context = build_native_context(
        route, receipts, cutoff_ms=intent.decision_ts_ms, captured_at_ms=intent.decision_ts_ms
    )
    gateway = gateway or FixtureGateway()
    brain = CandidateReviewBrain(gateway, clock_ms=lambda: intent.decision_ts_ms + completion_offset)
    return await review_native(brain, route, context), gateway


@pytest.mark.asyncio
async def test_two_actual_native_brain_calls_keep_preview_and_final_identity_separate():
    chain, prepared, _outcome, plan, bars, preview = prepared_plan()
    first, gateway = await reviewed(preview.intent, bars, completion_offset=0)
    assert first.reviewer == "LLM" and gateway.calls == 1
    observation = bind_scenario_review(preview, first, actual_completed_ms=first.reviewed_at_ms)
    raw = evaluate_hypothesis(plan, (observation,))[-1].candidate
    assert raw is not None
    final = native_intent(raw, input_bars=bars, **NATIVE)
    assert final.intent_id != preview.intent.intent_id
    assert final.exit_plan == preview.intent.exit_plan
    assert final.entry_expires_ts_ms == preview.intent.entry_expires_ts_ms
    second, gateway = await reviewed(final, bars, gateway=gateway)
    assert gateway.calls == 2
    assert second.intent.canonical_intent_bytes() == final.canonical_intent_bytes()
    assert second.model_provenance.request_id != first.model_provenance.request_id
    with pytest.raises(ValueError, match="another immutable"):
        bind_scenario_review(replace(preview, intent=final), first, actual_completed_ms=first.reviewed_at_ms)
    # Current 5m context is retained; combined peer is positively quiet in this fixture.
    chain, decision = chain.resolve(
        prepared,
        symbol=SYMBOL,
        arm_id="independent_proposals",
        issued_ms=raw.decision_ts_ms,
        runs=(cp.OriginRun(plan, (observation,)),),
        shared_gate="PASS",
        current_prepared=prepared,
    )
    assert decision.candidate == raw
    restored = CurrentCatalystChain(chain.policy, chain.state, chain.creation_ledger, chain.decision_ledger)
    again, duplicate = restored.resolve(
        prepared,
        symbol=SYMBOL,
        arm_id="independent_proposals",
        issued_ms=raw.decision_ts_ms,
        runs=(cp.OriginRun(plan, (observation,)),),
        shared_gate="PASS",
        current_prepared=prepared,
    )
    assert duplicate == decision and again.decision_ledger == chain.decision_ledger


def sim_session(intent):
    return SimulationSessionV1(
        source="fixture",
        tape_id="fixture",
        tape_sha256="9" * 64,
        started_at_ms=START,
        ends_at_ms=START + 30 * MINUTE,
        strategy_allowlist=(
            SimulationStrategyRefV1(
                strategy_id=intent.strategy_id, strategy_revision=intent.strategy_revision
            ),
        ),
        assumptions=SimulationAssumptionsV1(
            latency_ms=0,
            maximum_book_age_ms=2000,
            maximum_frame_latency_ms=1000,
            depth_participation_fraction=1.0,
            adverse_slippage_bps=0.0,
            taker_fee_bps=5.0,
            price_tick=0.01,
            quantity_step=0.001,
        ),
    )


@pytest.mark.asyncio
async def test_actual_sim_risk_rejects_expired_original_even_with_fresh_book():
    _chain, _prepared, _outcome, plan, bars, preview = prepared_plan()
    first, _ = await reviewed(preview.intent, bars, completion_offset=0)
    observation = bind_scenario_review(preview, first, actual_completed_ms=first.reviewed_at_ms)
    final = native_intent(evaluate_hypothesis(plan, (observation,))[-1].candidate, input_bars=bars, **NATIVE)
    second, _ = await reviewed(final, bars)
    at = final.entry_expires_ts_ms + 1

    def frame_at(clock):
        return RecordedTopNBookFrameV1(
            source="fixture",
            tape_id="fixture",
            stream_epoch="fixture",
            symbol=SYMBOL,
            tape_sequence=1,
            exchange_update_id=1,
            exchange_at_ms=clock,
            received_at_ms=clock,
            persisted_at_ms=clock,
            raw_payload_sha256="7" * 64,
            continuity="ADMITTED",
            bids=(RecordedBookLevelV1(price=100.09, quantity=100.0),),
            asks=(RecordedBookLevelV1(price=100.10, quantity=100.0),),
        )

    frame = frame_at(at)
    decision, admission = decide_sim(
        session=sim_session(final),
        final_intent=final,
        final_review=second,
        selected_book_frame=frame,
        decided_at_ms=at,
        requested_quantity=1.0,
    )
    assert not decision.approved and "INTENT_EXPIRED" in decision.rejection_reasons
    assert admission is None and decision.quantity == 0
    with pytest.raises(ValueError, match="another immutable"):
        decide_sim(
            session=sim_session(final),
            final_intent=final,
            final_review=first,
            selected_book_frame=frame,
            decided_at_ms=at,
            requested_quantity=1.0,
        )
    positive, admitted = decide_sim(
        session=sim_session(final),
        final_intent=final,
        final_review=second,
        selected_book_frame=frame_at(second.reviewed_at_ms),
        decided_at_ms=second.reviewed_at_ms,
        requested_quantity=1.0,
    )
    assert positive.approved and admitted is not None


def test_five_symbol_denominator_invalid_source_and_original_response_restart():
    chain = CurrentCatalystChain.start(policy())
    with pytest.raises(ValueError, match="full five-symbol"):
        chain.prepare(cells()[:-1])
    all_cells = list(cells())
    target = next(i for i, c in enumerate(all_cells) if c.events)
    event = all_cells[target].events[0]
    bad_version = replace(event.version, source_name="undeclared")
    all_cells[target] = replace(
        all_cells[target], events=(replace(event, source_id="undeclared", version=bad_version),)
    )
    with pytest.raises(ValueError, match="source/proof outside"):
        chain.prepare(tuple(all_cells))
    retained, prepared, outcome, _plan, _bars, _preview = prepared_plan()
    restored = CurrentCatalystChain(
        retained.policy, retained.state, retained.creation_ledger, retained.decision_ledger
    )
    duplicate, _ = restored.materialize(prepared, symbol=SYMBOL, origin="CONTEXT_PROPOSAL", outcome=outcome)
    assert duplicate.creation_ledger == retained.creation_ledger
    with pytest.raises(ValueError, match="already consumed"):
        restored.materialize(
            prepared,
            symbol=SYMBOL,
            origin="CONTEXT_PROPOSAL",
            outcome=replace(
                outcome,
                original_sha256="2" * 64,
                assessment=replace(outcome.assessment, response_sha256="2" * 64),
            ),
        )


@pytest.mark.asyncio
async def test_slow_review_actual_clock_is_not_native_defer_clamped_clock():
    _chain, _prepared, _outcome, plan, bars, preview = prepared_plan()
    first, _ = await reviewed(preview.intent, bars, completion_offset=0)
    observed = bind_scenario_review(
        preview, first, actual_completed_ms=preview.intent.entry_expires_ts_ms + 1
    )
    result = evaluate_hypothesis(plan, (observed,))[-1]
    assert result.candidate is None
    assert result.reason == "ENTRY_QUOTE_IDENTITY_CLOCK_OR_FRESHNESS_CONFLICT"
    assert observed.market.observed_ms > first.reviewed_at_ms


def test_real_midminute_candidate_uses_explicit_v2_without_rounding_or_v1_bypass():
    _chain, _prepared, _outcome, plan, bars, preview = prepared_plan()
    from adaptive_replay.catalyst_hypothesis_v1 import _entry

    shifted = replace(
        preview.observation, market=replace(preview.observation.market, observed_ms=START + MINUTE + 101)
    )
    raw, _ = _entry(plan, shifted)
    assert raw is not None and raw.entry_eligible_ts_ms % MINUTE == 101
    native = native_intent(raw, input_bars=bars, **NATIVE)
    assert native.contract_version == "strategy-intent.observed-sim.v2"
    assert native.entry_eligible_ts_ms == raw.entry_eligible_ts_ms
    assert native.decision_ts_ms == raw.decision_ts_ms
