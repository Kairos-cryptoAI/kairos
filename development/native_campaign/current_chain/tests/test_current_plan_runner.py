"""Plan-first runner invariants using typed synthetic engineering fixtures only."""

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from adaptive_replay.hypothesis_v3 import EntryQuote
from kairos_core.contracts import RecordedBookLevelV1, RecordedTopNBookFrameV2, SimulationStrategyRefV1
from kairos_strategy.candles import Candle
from test_current_chain import SYMBOL, cells
from test_current_plan import setup_plan

from kairos_native_campaign import current_plan_runner as runner
from kairos_native_campaign.current_deferred import DeferredSimulationPlan, ObservedSimulationRequests
from kairos_native_campaign.current_inputs import BAR_MS, CapturedClosedBar
from kairos_native_campaign.current_runner import CurrentRunConfig


def _captured(candle: Candle, *, source_id="binance_um_market_ws_closed_kline"):
    raw = f"fixture:{candle.symbol}:{candle.open_time_ms}".encode()
    return CapturedClosedBar(
        candle,
        raw,
        source_id,
        candle.close_time_ms,
        candle.close_time_ms + 1,
        candle.close_time_ms + 2,
        hashlib.sha256(raw).hexdigest(),
    )


def _flat_bar(symbol: str, open_ms: int) -> Candle:
    return Candle(symbol, "1m", open_ms, open_ms + BAR_MS - 1, 100.0, 100.1, 99.9, 100.0, 1.0)


def _supported_range(_bars):
    return SimpleNamespace(regime=SimpleNamespace(value="RANGE"))


def _normal_defense(*_args):
    return "NORMAL"


def test_native_prefix_keeps_pre_review_bars_but_requires_full_gapless_roster():
    cut = 3_240 * BAR_MS
    history = tuple(_flat_bar(SYMBOL, open_ms) for open_ms in range(cut - 3_240 * BAR_MS, cut, BAR_MS))
    after = tuple(_captured(_flat_bar(SYMBOL, cut + index * BAR_MS)) for index in range(3))
    # The first two native bars occurred before model review completed. They
    # prove continuity, but only the final post-review candle is an observation.
    observed = (SimpleNamespace(market=SimpleNamespace(candle=after[-1].candle)),)

    bars, candles = runner._native_prefix(SYMBOL, cut, history, {SYMBOL: after}, observed)

    assert len(bars) == 3_243
    assert candles[-1] == after[-1].candle
    with pytest.raises(runner.CurrentPlanRunRefused, match="CURRENT_NATIVE_BAR_ROSTER_GAP"):
        runner._native_prefix(SYMBOL, cut, history, {SYMBOL: (after[0], after[2])}, observed)


@pytest.mark.asyncio
async def test_missing_native_prefix_refuses_before_quote_or_deferred_request(monkeypatch, tmp_path):
    plan, review, _observations, _bars = setup_plan()
    expected_open = ((review.completed_at_ms + BAR_MS - 1) // BAR_MS) * BAR_MS
    if plan.template.side.value == "LONG":
        stop = plan.template.exit_plan.stop_price
        reference = plan.template.reference_price
        candle = Candle(
            SYMBOL,
            "1m",
            expected_open,
            expected_open + BAR_MS - 1,
            reference,
            reference + 0.2,
            (stop + reference) / 2,
            reference + 0.1,
            1.0,
        )
    else:
        stop = plan.template.exit_plan.stop_price
        reference = plan.template.reference_price
        candle = Candle(
            SYMBOL,
            "1m",
            expected_open,
            expected_open + BAR_MS - 1,
            reference,
            (stop + reference) / 2,
            reference - 0.2,
            reference - 0.1,
            1.0,
        )
    captured = _captured(candle)
    observed_ms = candle.close_time_ms + 3
    monkeypatch.setattr(runner, "_now_ms", lambda: observed_ms)

    class BarSource:
        async def wait_closed_bar(self, symbol, after_close_ms, *, timeout_s):
            assert symbol == SYMBOL
            assert after_close_ms == expected_open - 1
            return captured

        def closed_bar_roster(self):
            return {}

    class QuoteSource:
        calls = 0

        async def fresh_quote(self, symbol):
            self.calls += 1
            raise AssertionError("quote must not be acquired without a complete native prefix")

    quote_source = QuoteSource()
    observation_source = SimpleNamespace(bar_source=BarSource(), quote_source=quote_source)
    deferred_requests = SimpleNamespace(record=None)
    history = SimpleNamespace(bars_by_symbol={SYMBOL: ()})

    with pytest.raises(runner.CurrentPlanRunRefused, match="ACTUAL_CLOSED_BAR_ROSTER_REQUIRED"):
        await runner._observe_confirm_and_authorize(
            plan=plan,
            review=review,
            history=history,
            symbol=SYMBOL,
            cut_ms=plan.origin_cut_ms,
            observation_source=observation_source,
            risk_frame_source=SimpleNamespace(),
            fold_lock=asyncio.Lock(),
            deferred_requests=deferred_requests,
            artifact_root=tmp_path,
            code_sha256=plan.source_set_sha256,
            config_sha256=plan.creation_assessment.model_config_sha256,
            run_deadline_ms=plan.origin_cut_ms + 300_000,
            risk_lock=asyncio.Lock(),
            aggregate_open_risk=[0],
            requested_quantity=1.0,
        )

    assert quote_source.calls == 0


@pytest.mark.asyncio
async def test_budget_refusal_cancels_and_drains_other_observers():
    started = asyncio.Event()
    release = asyncio.Event()

    async def fail_budget():
        raise runner.CurrentRunRefused("PROVIDER_CALL_CAP_EXCEEDED")

    async def wait_until_cancelled():
        started.set()
        await release.wait()

    wait_task = asyncio.create_task(wait_until_cancelled())
    await started.wait()
    fail_task = asyncio.create_task(fail_budget())

    with pytest.raises(runner.CurrentRunRefused, match="PROVIDER_CALL_CAP_EXCEEDED"):
        await runner._gather_observers((("BTCUSDT", fail_task), ("ETHUSDT", wait_task)))

    assert wait_task.done() and wait_task.cancelled()


@pytest.mark.asyncio
async def test_typed_observer_consumes_first_post_review_confirmation_and_authorizes(monkeypatch, tmp_path):
    plan, review, _observations, _full_bars = setup_plan()
    history_bars = next(cell.price.rows for cell in cells() if cell.price.symbol == SYMBOL)
    cut = plan.origin_cut_ms
    expected_open = ((review.completed_at_ms + BAR_MS - 1) // BAR_MS) * BAR_MS
    template = plan.template
    reference = template.reference_price
    stop = template.exit_plan.stop_price
    if template.side.value == "LONG":
        candle = Candle(
            SYMBOL,
            "1m",
            expected_open,
            expected_open + BAR_MS - 1,
            reference,
            reference + 0.2,
            (reference + stop) / 2,
            reference + 0.1,
            1.0,
        )
    else:
        candle = Candle(
            SYMBOL,
            "1m",
            expected_open,
            expected_open + BAR_MS - 1,
            reference,
            (reference + stop) / 2,
            reference - 0.2,
            reference - 0.1,
            1.0,
        )
    captured_ms = candle.close_time_ms + 101
    clock = [captured_ms]
    monkeypatch.setattr(runner, "_now_ms", lambda: clock[0])
    captured = _captured(candle)
    prefix_receipts = []
    for open_ms in range(cut, expected_open, BAR_MS):
        continuity_bar = _flat_bar(SYMBOL, open_ms)
        prefix_receipts.append(_captured(continuity_bar))

    class Bars:
        def closed_bar_roster(self):
            return {SYMBOL: (*prefix_receipts, captured)}

        async def wait_closed_bar(self, symbol, after_close_ms, *, timeout_s):
            assert symbol == SYMBOL
            assert after_close_ms == expected_open - 1
            assert timeout_s >= 1
            return captured

    class Quotes:
        async def fresh_quote(self, symbol):
            raw = b"typed synthetic post-confirmation quote"
            bid, ask = reference + 0.19, reference + 0.20
            if template.side.value == "SHORT":
                bid, ask = reference - 0.20, reference - 0.19
            quote = EntryQuote(
                "quote-fixture",
                symbol,
                bid,
                ask,
                candle.close_time_ms + 10,
                captured_ms,
                captured_ms,
                2_000,
                "TEST_FIXTURE",
            )
            return runner.FreshQuoteSnapshot(
                symbol,
                quote,
                raw,
                hashlib.sha256(raw).hexdigest(),
                captured_ms,
                captured_ms,
                captured_ms,
                100.0,
                100.0,
                tmp_path / "quote.receipt",
            )

    class RiskFrame:
        async def request_snapshot(self, symbol):
            request_ms = captured_ms + 50
            clock[0] = request_ms
            raw = json.dumps({"fixture": "admitted typed book"}, separators=(",", ":"))
            bid, ask = reference + 0.19, reference + 0.20
            if template.side.value == "SHORT":
                bid, ask = reference - 0.20, reference - 0.19
            frame = RecordedTopNBookFrameV2(
                source="fixture-recorded-book",
                tape_id="fixture-tape",
                stream_epoch="fixture-epoch",
                symbol=symbol,
                tape_sequence=1,
                exchange_update_id=1,
                exchange_at_ms=candle.close_time_ms + 20,
                received_at_ms=request_ms,
                persisted_at_ms=request_ms,
                raw_payload=raw,
                raw_payload_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                continuity="ADMITTED",
                source_reason="FIXTURE_ADMITTED",
                bids=(RecordedBookLevelV1(price=bid, quantity=10.0),),
                asks=(RecordedBookLevelV1(price=ask, quantity=10.0),),
            )
            return request_ms, frame

    class Deferred:
        plan = SimpleNamespace(tape_id="fixture-tape")
        recorded = None

        async def record(self, **kwargs):
            self.recorded = kwargs
            return {"sequence": 1}

    deferred = Deferred()
    observation_source = SimpleNamespace(bar_source=Bars(), quote_source=Quotes())
    (tmp_path / "plan-reviews").mkdir()
    # Exercise the typed authorization boundary independently from the frozen
    # adaptive classifier; its actual implementation is covered by its own suite.
    monkeypatch.setattr(runner, "evaluate_adaptive", _supported_range)
    monkeypatch.setattr(runner, "crash_defense", _normal_defense)
    async with runner._fold_worker():
        result = await runner._observe_confirm_and_authorize(
            plan=plan,
            review=review,
            history=SimpleNamespace(bars_by_symbol={SYMBOL: history_bars}),
            symbol=SYMBOL,
            cut_ms=cut,
            observation_source=observation_source,
            risk_frame_source=RiskFrame(),
            fold_lock=asyncio.Lock(),
            deferred_requests=deferred,
            artifact_root=tmp_path,
            code_sha256=plan.source_set_sha256,
            config_sha256=plan.creation_assessment.model_config_sha256,
            run_deadline_ms=cut + 300_000,
            risk_lock=asyncio.Lock(),
            aggregate_open_risk=[0],
            requested_quantity=0.001,
        )

    assert result["state"] == "OBSERVED_REQUEST_PENDING_LATER_NATIVE_SIM_REPLAY"
    assert result["actual_live_risk_or_execution"] is False
    assert deferred.recorded["entry_authorization"].sha256 == result["authorization_sha256"]
    auth_files = tuple((tmp_path / "plan-reviews").glob("entry-authorization-*.json"))
    assert len(auth_files) == 1
    auth_payload = json.loads(auth_files[0].read_text(encoding="utf-8"))
    assert auth_payload["schema"] == "kairos.current-plan-entry-authorization.v1"


@pytest.mark.asyncio
async def test_run_one_plan_cut_requires_explicit_deferred_native_sim_injection(tmp_path):
    config = CurrentRunConfig(
        tmp_path / "injected-run.json",
        1_700_000_000_000,
        1_700_000_060_000,
        1_700_000_060_000,
        "a" * 64,
        "b" * 64,
        ("fixture-strategy.v1",),
        "fixture-run",
    )
    services = SimpleNamespace(
        deferred_requests=None,
        simulation_session=None,
        risk_frame_source=SimpleNamespace(),
        open_risk_snapshot=None,
        usage_snapshot=None,
        gateway=SimpleNamespace(),
        build_cut_inputs=None,
    )
    with pytest.raises(runner.CurrentRunRefused, match="EXPLICIT_DEFERRED_NATIVE_SIM_DEPENDENCIES_REQUIRED"):
        await runner.run_one_plan_cut(config, services)
    assert not config.output_path.exists()


@pytest.mark.asyncio
async def test_positive_whole_plan_cut_reuses_existing_typed_source_and_gateway_fixture(
    monkeypatch, tmp_path
):
    """Run the same fixed-source fixture through the new orchestration end to end."""
    from dataclasses import replace

    import test_current_runner_flow as existing_fixture

    from kairos_native_campaign import current_runner as current_runner_module

    original_run_one_cut = current_runner_module.run_one_cut
    plan_cut_receipt = {}
    builder_errors = []

    async def run_plan_then_keep_legacy_assertions(config, services):
        # The existing test owns the fixed RSS, full 5-symbol typed REST pages,
        # quote snapshots, budgeted gateway fixture, and real input builder.
        tape_id = "current-native-" + hashlib.sha256(b"plan-first-fixed-fixture").hexdigest()[:32]
        plan = DeferredSimulationPlan(
            tape_id=tape_id,
            assumptions=services.simulation_session.assumptions,
            strategy_allowlist=(
                SimulationStrategyRefV1(
                    strategy_id="current-plan-reviewed-catalyst.v1",
                    strategy_revision="current-chain.plan-reviewed-sim.v3",
                ),
            ),
            started_at_ms=config.cut_ms,
            ends_at_ms=config.cut_ms + 900_000,
            source_set_sha256=config.source_set_sha256,
            model_config_sha256=config.model_config_sha256,
        )
        output = config.output_path.parent / "plan-first-deferred"
        deferred = ObservedSimulationRequests(plan, output)

        async def unavailable_typed_frame(_symbol):
            raise AssertionError("the roster-less fixed fixture must not request a frame")

        def observed_real_builder(**kwargs):
            try:
                return services.build_cut_inputs(**kwargs)
            except Exception as exc:
                builder_errors.append(f"{type(exc).__name__}: {exc}")
                raise

        plan_services = replace(
            services,
            simulation_session=plan,
            tape_id=tape_id,
            deferred_requests=deferred,
            risk_frame_source=SimpleNamespace(request_snapshot=unavailable_typed_frame),
            build_cut_inputs=observed_real_builder,
        )
        services.gateway.macro_strategy_id = "current-plan-reviewed-catalyst.v1"
        plan_config = replace(
            config,
            output_path=config.output_path.parent / "whole-cut-plan-first.json",
            strategy_ids=("current-plan-reviewed-catalyst.v1",),
            run_id="fixed-plan-first-run",
        )
        # The legacy fixture's injected clock advances to its scheduled cut;
        # share it with the plan-first module so this test never waits on wall time.
        monkeypatch.setattr(runner, "_now_ms", current_runner_module._now_ms)
        plan_cut_receipt.update(await runner.run_one_plan_cut(plan_config, plan_services))
        if builder_errors or plan_cut_receipt.get("result") != "COMPLETED":
            raise AssertionError({"builder_errors": builder_errors, "receipt": plan_cut_receipt})
        # The existing test continues to execute all its original assertions,
        # using a clean ledger snapshot for its separate v2 run.
        services.gateway.attempts.clear()
        services.gateway.workloads.clear()
        services.gateway.macro_strategy_id = "closed-catalyst-hypothesis.research.v1"
        return await original_run_one_cut(config, services)

    monkeypatch.setattr(current_runner_module, "run_one_cut", run_plan_then_keep_legacy_assertions)
    await existing_fixture.test_actual_typed_run_one_cut_reaches_catalyst_brain_and_native_risk(
        monkeypatch, tmp_path
    )

    assert plan_cut_receipt["result"] == "COMPLETED"
    assert plan_cut_receipt["planning_semantics"] == (
        "PLAN_LLM_REVIEW_BEFORE_NEW_POST_REVIEW_CONFIRMATION_AND_ENTRY_QUOTE_V3"
    )
    assert any(stage["name"] == "capture_history" for stage in plan_cut_receipt["stages"])
    assert any(stage["name"] == "macro_strategist_allocate" for stage in plan_cut_receipt["stages"])
    assert builder_errors == []
    assert plan_cut_receipt["macro_capital_allowed"] is True
    assert plan_cut_receipt["selected_plans"]
    assert any(stage["name"] == "plan_llm_review:BTCUSDT" for stage in plan_cut_receipt["stages"])
    assert len(plan_cut_receipt["plan_reviews"]) == 1
    review_receipt = plan_cut_receipt["plan_reviews"][0]
    assert review_receipt["decision"] == "ALLOW"
    selected = plan_cut_receipt["selected_plans"][0]
    assert selected["plan_sha256"] == review_receipt["plan_sha256"]
    plan_payload = json.loads(Path(selected["plan_path"]).read_text(encoding="utf-8"))
    review_payload = json.loads(Path(review_receipt["review_path"]).read_text(encoding="utf-8"))
    assert runner._canonical_sha(plan_payload) == selected["plan_sha256"]
    assert runner._canonical_sha(review_payload) == review_receipt["review_sha256"]
    assert review_payload["plan_review"]["plan_sha256"] == selected["plan_sha256"]
    assert all(
        not item.get("actual_live_risk_or_execution", False) for item in plan_cut_receipt["sim_outcomes"]
    )
