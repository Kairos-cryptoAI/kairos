"""Engineering fixtures only: never real provider/feed or trade acceptance credit."""

import hashlib
import json
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from adaptive_replay.hypothesis_v3 import EntryQuote, HypothesisObservation, creation_input_sha256
from adaptive_replay.scenarios import MINUTE, ScenarioObservation
from kairos_core.contracts import (
    ModelProvenanceV1,
    RecordedBookLevelV1,
    RecordedTopNBookFrameV1,
    SentimentSignal,
    StrategicAllocation,
)
from kairos_core.contracts.base import canonical_sha256, datetime_from_unix_ms
from kairos_core.enums import ImpactDirection, ReviewDecision
from kairos_strategy.candles import Candle
from kairos_strategy.runtime import candle_to_closed_bar
from test_current_chain import START, SYMBOL, native_context, prepared_plan, sim_session, sources

from kairos_native_campaign.current_chain import decide_sim
from kairos_native_campaign.current_plan import (
    CONFIRMATION_SOURCE_ID,
    PLAN_REVIEW_SYSTEM,
    POLICY_ID,
    STRATEGY_ID,
    CurrentEntryAuthorization,
    CurrentPlan,
    CurrentPlanReview,
    PlanningSource,
    authorize_current_entry,
    macro_allocation_allows_entry,
    plan_review_prompt,
    plan_review_workload,
    revalidate_authorization,
    review_current_plan,
)


def entry_sources(plan, candle, at):
    market = next(e for e in sources(candle, at) if e.kind == "MARKET")
    result = tuple(e for e in plan.creation_evidence if e.kind != "MARKET") + (
        replace(market, source_id=CONFIRMATION_SOURCE_ID),
    )
    return tuple(sorted(result, key=lambda e: (e.kind, e.source_id)))


def setup_plan(*, creation_delay=220):
    _chain, _prepared, _outcome, original, bars, preview = prepared_plan()
    text = SentimentSignal(
        source="fixture-text",
        produced_at=datetime_from_unix_ms(START),
        topic=SYMBOL,
        sentiment=0.0,
        impact=ImpactDirection.NEUTRAL,
        confidence=0.9,
        sources=["https://example.test/fixture"],
        summary="Engineering fixture only",
    )
    _route, receipts = native_context(preview.intent)
    market = next(model.model_dump(mode="json") for kind, model, _at in receipts if kind == "market")
    macro = next(model.model_dump(mode="json") for kind, model, _at in receipts if kind == "macro")
    macro["strategy_weights"] = {STRATEGY_ID: 0.8}
    for payload in (market, macro):
        payload["produced_at"] = datetime_from_unix_ms(START).isoformat()
    quote = EntryQuote(
        "quote-fixture", SYMBOL, 100.09, 100.10, START, START + 100, START + 100, 5_000, "TEST_FIXTURE"
    )
    payload_by_kind = {
        "MARKET": {"quote": asdict(quote), "quote_raw_sha256": "3" * 64, "market_snapshot": market},
        "CLOSED_BARS": {
            "source_id": "fixture-rest",
            "page_sha256": "4" * 64,
            "bar_count": 3240,
            "bars": [asdict(original.anchor)],
        },
        "TEXT": text.model_dump(mode="json"),
        "MACRO": macro,
    }
    context = tuple(
        PlanningSource(
            kind,
            json.dumps(
                [payload_by_kind[kind]],
                sort_keys=True,
                separators=(",", ":"),
            ),
            START,
            START + 100,
            START + 100,
            600_000,
        )
        for kind in ("MARKET", "CLOSED_BARS", "TEXT", "MACRO")
    )
    directional_json = json.dumps({"symbol": SYMBOL, "cut_ms": START}, sort_keys=True, separators=(",", ":"))
    directional_sha = hashlib.sha256(directional_json.encode("utf-8")).hexdigest()
    creation = replace(
        original.creation_assessment,
        input_sha256=creation_input_sha256(
            original.source_set_sha256, directional_sha, original.anchor, original.creation_evidence
        ),
    )
    plan = CurrentPlan(
        template=original.template,
        origin=original.origin,
        regime=original.regime,
        defense=original.defense,
        origin_cut_ms=original.origin_cut_ms,
        created_at_ms=START + creation_delay,
        valid_until_ms=START + 500_000,
        source_set_sha256=original.source_set_sha256,
        creation_evidence=original.creation_evidence,
        anchor=original.anchor,
        required_sources=original.required_sources,
        policy=original.policy,
        context=context,
        creation_assessment=creation,
        creation_input_json=directional_json,
    )
    provenance = ModelProvenanceV1(
        provider="openai",
        model="engineering-fixture",
        request_id="fixture-1",
        prompt_sha256=canonical_sha256({"system": PLAN_REVIEW_SYSTEM, "user": plan_review_prompt(plan)}),
        response_sha256="2" * 64,
        budget_reservation_id="fixture-zero-cost",
        latency_ms=5_000,
        cost_usd=0.0,
    )
    review = CurrentPlanReview(
        plan.sha256,
        plan.context_sha256,
        ReviewDecision.ALLOW,
        1,
        ("FIXTURE_ONLY",),
        plan.created_at_ms,
        plan.created_at_ms + 5_000,
        plan.created_at_ms + 5_000,
        provenance,
    )
    expected = ((review.completed_at_ms + MINUTE - 1) // MINUTE) * MINUTE
    candle = Candle(SYMBOL, "1m", expected, expected + MINUTE - 1, 100.0, 100.2, 99.9, 100.1, 10.0)
    at = candle.close_time_ms + 101
    obs = HypothesisObservation(
        ScenarioObservation(candle, at, entry_sources(plan, candle, at)),
        EntryQuote(
            "quote-fixture", SYMBOL, 100.09, 100.10, candle.close_time_ms + 1, at, at, 2_000, "TEST_FIXTURE"
        ),
    )
    return plan, review, (obs,), tuple(bars) + (candle_to_closed_bar(candle),)


def authorize(plan, review, observations, bars, *, at=None):
    return authorize_current_entry(
        plan,
        review,
        observations,
        input_bars=bars,
        authorized_at_ms=at or observations[-1].market.observed_ms,
        code_sha256=plan.source_set_sha256,
        config_sha256=plan.creation_assessment.model_config_sha256,
    )


def test_plan_created_after_old_first_minute_is_new_version_not_backdated():
    plan, review, _observations, _bars = setup_plan(creation_delay=95_000)
    assert plan.created_at_ms == START + 95_000
    assert review.completed_at_ms > START + MINUTE
    assert plan.sha256 != plan.template.intent_id


def test_authorization_new_truthful_deterministic_review_has_no_final_llm_provenance():
    plan, review, observations, bars = setup_plan()
    result = authorize(plan, review, observations, bars)
    revalidate_authorization(result)
    assert type(result) is CurrentEntryAuthorization
    assert result.intent.strategy_id == STRATEGY_ID
    assert result.native_review.reviewer == "DETERMINISTIC"
    assert result.native_review.model_provenance is None
    assert result.native_review.source == POLICY_ID
    assert result.intent.entry_expires_ts_ms <= observations[-1].quote.event_ms + 2_000
    assert result.intent.exit_plan.stop_price == plan.template.exit_plan.stop_price
    assert result.intent.exit_plan.target_price == plan.template.exit_plan.target_price
    assert dict(result.intent.metadata)["current_plan_review_sha256"] == review.sha256


def test_expired_quote_refused_even_after_valid_five_second_plan_review():
    plan, review, observations, bars = setup_plan()
    with pytest.raises(ValueError, match="ENTRY_QUOTE_IDENTITY_CLOCK_OR_FRESHNESS_CONFLICT"):
        authorize(plan, review, observations, bars, at=observations[-1].quote.event_ms + 2_001)


def test_wrong_review_and_relabelled_model_authorization_refused():
    plan, review, observations, bars = setup_plan()
    with pytest.raises(ValueError, match="PLAN_REVIEW_BINDING_CONFLICT"):
        authorize(plan, replace(review, plan_sha256="f" * 64), observations, bars)
    authorization = authorize(plan, review, observations, bars)
    with pytest.raises(ValueError):
        replace(
            authorization,
            native_review=authorization.native_review.model_copy(
                update={"reviewer": "LLM", "model_provenance": review.model_provenance}
            ),
        )


def test_quote_policy_cannot_exceed_original_two_seconds():
    plan, _review, _observations, _bars = setup_plan()
    with pytest.raises(ValueError, match="original two seconds"):
        replace(plan, policy=replace(plan.policy, maximum_quote_age_ms=2_001))


def test_first_post_review_bar_gap_no_signal_and_stop_refusals():
    plan, review, observations, bars = setup_plan()
    original = observations[-1]
    with pytest.raises(ValueError):
        changed = replace(
            original.market.candle,
            open_time_ms=original.market.candle.open_time_ms + MINUTE,
            close_time_ms=original.market.candle.close_time_ms + MINUTE,
        )
        authorize(plan, review, (replace(original, market=replace(original.market, candle=changed)),), bars)
    with pytest.raises(ValueError, match="NO_CLOSED_PRICE_CONFIRMATION"):
        changed = replace(original.market.candle, close=100.0)
        authorize(
            plan,
            review,
            (
                replace(
                    original,
                    market=replace(
                        original.market,
                        candle=changed,
                        sources=entry_sources(plan, changed, original.market.observed_ms),
                    ),
                ),
            ),
            bars,
        )
    with pytest.raises(ValueError, match="PLAN_STOP_INVALIDATED"):
        changed = replace(original.market.candle, low=plan.template.exit_plan.stop_price)
        authorize(
            plan,
            review,
            (
                replace(
                    original,
                    market=replace(
                        original.market,
                        candle=changed,
                        sources=entry_sources(plan, changed, original.market.observed_ms),
                    ),
                ),
            ),
            bars,
        )


class Gateway:
    calls = 0

    def __init__(self, plan, *, latency=5_000):
        self.plan, self.latency = plan, latency
        self.workloads = []

    async def complete(self, **kwargs):
        self.calls += 1
        self.workloads.append(kwargs["workload"].value)
        content = '{"decision":"ALLOW","priority":1,"reason_codes":["FIXTURE_ONLY"]}'
        return SimpleNamespace(
            parsed=kwargs["schema"].model_validate_json(content),
            content=content,
            provider="openai",
            model="engineering-fixture",
            resolved_model="engineering-fixture",
            request_id="fixture-1",
            budget_reservation_id="fixture-zero-cost",
            effort="medium",
            latency_s=self.latency / 1_000,
            cost_usd=0.0,
            cached=False,
            workload=kwargs["workload"].value,
            attempt_started_at_ts_ms=self.plan.created_at_ms,
            response_observed_at_ts_ms=self.plan.created_at_ms + self.latency,
        )


@pytest.mark.asyncio
async def test_plan_review_five_seconds_precedes_independent_quote_not_executable_deadline():
    plan, _review, _obs, _bars = setup_plan()
    clocks = iter((plan.created_at_ms, plan.created_at_ms + 5_000))
    gateway = Gateway(plan)
    result = await review_current_plan(plan, gateway, clock_ms=lambda: next(clocks))
    assert gateway.calls == 1
    assert result.decision is ReviewDecision.ALLOW
    assert result.completed_at_ms - result.requested_at_ms == 5_000


@pytest.mark.asyncio
async def test_plan_review_late_actual_completion_defers_without_retiming():
    plan, _review, _obs, _bars = setup_plan()
    gateway = Gateway(plan, latency=500_000)
    clocks = iter((plan.created_at_ms, plan.created_at_ms + gateway.latency))
    result = await review_current_plan(plan, gateway, clock_ms=lambda: next(clocks))
    assert result.decision is ReviewDecision.DEFER
    assert result.reason_codes == ("PLANNING_CONTEXT_EXPIRED_DURING_MODEL",)
    assert result.completed_at_ms > plan.valid_until_ms


def test_native_risk_remains_independent_and_rejects_expired_entry_with_fresh_book():
    plan, review, observations, bars = setup_plan()
    authorization = authorize(plan, review, observations, bars)

    def decide(at):
        frame = RecordedTopNBookFrameV1(
            source="fixture",
            tape_id="fixture",
            stream_epoch="fixture",
            symbol=SYMBOL,
            tape_sequence=1,
            exchange_update_id=1,
            exchange_at_ms=at,
            received_at_ms=at,
            persisted_at_ms=at,
            raw_payload_sha256="7" * 64,
            continuity="ADMITTED",
            bids=(RecordedBookLevelV1(price=100.09, quantity=100.0),),
            asks=(RecordedBookLevelV1(price=100.10, quantity=100.0),),
        )
        return decide_sim(
            session=sim_session(authorization.intent),
            final_intent=authorization.intent,
            final_review=authorization.native_review,
            selected_book_frame=frame,
            decided_at_ms=at,
            requested_quantity=1.0,
        )

    decision, admission = decide(authorization.authorized_at_ms)
    assert decision.approved and admission is not None
    decision, admission = decide(authorization.intent.entry_expires_ts_ms + 1)
    assert not decision.approved and admission is None
    assert "INTENT_EXPIRED" in decision.rejection_reasons


def test_entry_proof_rejects_changed_source_identity_quote_or_confirmation_hash():
    plan, review, observations, bars = setup_plan()
    authorization = authorize(plan, review, observations, bars)
    for field in ("quote_sha256", "confirmation_prefix_sha256", "context_sha256"):
        forged = replace(authorization, **{field: "f" * 64})
        with pytest.raises(ValueError, match="PROOF_CONFLICT"):
            revalidate_authorization(forged)
    with pytest.raises(ValueError, match="SOURCE_IDENTITY_CONFLICT"):
        authorize_current_entry(
            plan,
            review,
            observations,
            input_bars=bars,
            authorized_at_ms=observations[-1].market.observed_ms,
            code_sha256="f" * 64,
            config_sha256="d" * 64,
        )


@pytest.mark.asyncio
async def test_stale_plan_refused_before_paid_work_and_no_renewal():
    plan, _review, _observations, _bars = setup_plan()
    gateway = Gateway(plan)
    with pytest.raises(ValueError, match="PLAN_CONTEXT_UNAVAILABLE_BEFORE_REVIEW"):
        await review_current_plan(plan, gateway, clock_ms=lambda: plan.valid_until_ms + 1)
    assert gateway.calls == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", "binance_um_klines_rest"),
        ("payload_sha256", "f" * 64),
        ("event_ms", START + 2 * MINUTE - 2),
    ],
)
def test_confirmation_ws_identity_hash_and_event_clock_are_not_rest_aliases(field, value):
    plan, review, observations, bars = setup_plan()
    observation = observations[-1]
    altered = tuple(
        replace(e, **{field: value}) if e.kind == "MARKET" else e for e in observation.market.sources
    )
    altered = tuple(sorted(altered, key=lambda e: (e.kind, e.source_id)))
    bad = replace(observation, market=replace(observation.market, sources=altered))
    with pytest.raises(ValueError, match="CONFIRMATION_MARKET_SOURCE_BINDING_CONFLICT"):
        authorize(plan, review, (bad,), bars)


def test_confirmation_cannot_replace_reviewed_news_context_or_reuse_old_trigger():
    plan, review, observations, bars = setup_plan()
    first = observations[-1]
    altered = tuple(
        replace(e, payload_sha256="f" * 64) if e.kind == "NEWS" else e for e in first.market.sources
    )
    with pytest.raises(ValueError, match="REVIEWED_ENTRY_CONTEXT_BINDING_CONFLICT"):
        authorize(plan, review, (replace(first, market=replace(first.market, sources=altered)),), bars)
    candle = replace(
        first.market.candle,
        open_time_ms=first.market.candle.open_time_ms + MINUTE,
        close_time_ms=first.market.candle.close_time_ms + MINUTE,
    )
    at = first.market.observed_ms + MINUTE
    second = HypothesisObservation(
        ScenarioObservation(candle, at, entry_sources(plan, candle, at)),
        replace(first.quote, event_ms=first.quote.event_ms + MINUTE, received_ms=at, captured_ms=at),
    )
    with pytest.raises(ValueError, match="FIRST_TRIGGER_ALREADY_CONSUMED"):
        authorize(plan, review, (first, second), bars, at=at)


def changed_text(plan, *, sentiment=-0.5, topic=SYMBOL, confidence=0.9):
    context = []
    for source in plan.context:
        if source.kind == "TEXT":
            payload = json.loads(source.payloads_json)[0]
            payload.update(topic=topic, sentiment=sentiment, impact="bearish", confidence=confidence)
            source = replace(
                source, payloads_json=json.dumps([payload], sort_keys=True, separators=(",", ":"))
            )
        context.append(source)
    return replace(plan, context=tuple(context))


@pytest.mark.asyncio
async def test_plan_conflict_uses_existing_conflict_workload_and_strong_allow_guard():
    original, _review, _observations, _bars = setup_plan()
    for score, expected in ((-0.5, ReviewDecision.ALLOW), (-0.99, ReviewDecision.DEFER)):
        plan = changed_text(original, sentiment=score)
        assert plan_review_workload(plan).value == "aggregator_conflict"
        gateway = Gateway(plan)
        clocks = iter((plan.created_at_ms, plan.created_at_ms + 5_000))
        review = await review_current_plan(plan, gateway, clock_ms=lambda clocks=clocks: next(clocks))
        assert review.decision is expected
        assert gateway.workloads == ["aggregator_conflict"]
        if expected is ReviewDecision.DEFER:
            assert review.reason_codes == ("CONFLICT_ALLOW_GUARD",)


def test_plan_text_topic_and_original_directional_input_must_be_exactly_bound():
    plan, _review, _observations, _bars = setup_plan()
    with pytest.raises(ValueError, match="text topic"):
        changed_text(plan, topic="ETHUSDT" if SYMBOL != "ETHUSDT" else "BTCUSDT")
    with pytest.raises(ValueError, match="DIRECTIONAL_CREATION_INPUT_BINDING_CONFLICT"):
        replace(
            plan,
            creation_input_json=json.dumps(
                {"symbol": SYMBOL, "cut_ms": START, "changed": True}, sort_keys=True, separators=(",", ":")
            ),
        )


@pytest.mark.parametrize(
    "reserve,weights",
    [(1.0, {}), (0.2, {}), (0.2, {"other-strategy": 0.8}), (0.2, {STRATEGY_ID: 0.0})],
)
@pytest.mark.asyncio
async def test_macro_cash_or_no_target_capital_blocks_paid_review_and_exact_entry(reserve, weights):
    plan, review, observations, bars = setup_plan()
    context = []
    for source in plan.context:
        if source.kind == "MACRO":
            payload = json.loads(source.payloads_json)[0]
            payload.update(stable_reserve_pct=reserve, strategy_weights=weights)
            allocation = StrategicAllocation.model_validate(payload)
            assert not macro_allocation_allows_entry(allocation)
            source = replace(
                source, payloads_json=json.dumps([payload], sort_keys=True, separators=(",", ":"))
            )
        context.append(source)
    plan = replace(plan, context=tuple(context))
    gateway = Gateway(plan)
    with pytest.raises(ValueError, match="MACRO_CAPITAL_BLOCKED"):
        await review_current_plan(plan, gateway, clock_ms=lambda: plan.created_at_ms)
    assert gateway.calls == 0
    # Even an independently forged ALLOW cannot override this native capital veto.
    review = replace(
        review,
        plan_sha256=plan.sha256,
        context_sha256=plan.context_sha256,
        model_provenance=review.model_provenance.model_copy(
            update={
                "prompt_sha256": canonical_sha256(
                    {"system": PLAN_REVIEW_SYSTEM, "user": plan_review_prompt(plan)}
                )
            }
        ),
    )
    with pytest.raises(ValueError, match="MACRO_CAPITAL_BLOCKED"):
        authorize(plan, review, observations, bars)
