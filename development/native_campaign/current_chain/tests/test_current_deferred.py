"""Engineering regressions with explicitly synthetic inputs; no real-path credit."""

import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest
from adaptive_replay.catalyst_hypothesis_v1 import evaluate_hypothesis
from kairos_core.contracts import SimulationAssumptionsV1, SimulationStrategyRefV1
from kairos_strategy.candles import Candle
from test_current_chain import NATIVE, START, prepared_plan, reviewed, sim_session

from kairos_native_campaign import current_deferred as module
from kairos_native_campaign.current_capture import FreshQuoteSnapshot
from kairos_native_campaign.current_chain import bind_scenario_review, native_intent
from kairos_native_campaign.current_deferred import (
    MODE,
    SYMBOLS,
    DeferredSimulationPlan,
    ObservedSimulationRequests,
    import_complete_tape,
    replay_observed_requests,
)


async def _original_request(tmp_path, monkeypatch, *, expired=False, final_window_ms=None):
    _, _, _, plan, bars, preview = prepared_plan()
    first, gateway = await reviewed(preview.intent, bars, completion_offset=0)
    observation = bind_scenario_review(preview, first, actual_completed_ms=first.reviewed_at_ms)
    final = native_intent(evaluate_hypothesis(plan, (observation,))[-1].candidate, input_bars=bars, **NATIVE)
    review, _ = await reviewed(final, bars, gateway=gateway)
    at = final.entry_expires_ts_ms + 1 if expired else review.reviewed_at_ms + 1
    monkeypatch.setattr(module, "_now_ms", lambda: at)
    source_quote = preview.observation.quote
    quote = FreshQuoteSnapshot(
        final.symbol,
        source_quote,
        b"synthetic fixture quote only",
        hashlib.sha256(b"synthetic fixture quote only").hexdigest(),
        source_quote.received_ms,
        source_quote.received_ms,
        source_quote.captured_ms,
        1.0,
        1.0,
        tmp_path / "synthetic-quote.receipt.json",
    )
    deferred = DeferredSimulationPlan(
        "current-native-" + "a" * 32,
        SimulationAssumptionsV1(
            **{**sim_session(final).assumptions.model_dump(exclude={"assumptions_sha256"}), "latency_ms": 25}
        ),
        (SimulationStrategyRefV1(strategy_id=final.strategy_id, strategy_revision=final.strategy_revision),),
        START,
        START + 900_000 if final_window_ms is None else at + final_window_ms,
        NATIVE["code_sha256"],
        NATIVE["config_sha256"],
    )
    sink = ObservedSimulationRequests(deferred, tmp_path / "observed-requests")
    await sink.record(
        intent=final,
        review=review,
        quote=quote,
        frame=None,
        request_ms=at,
        requested_quantity=0.001,
    )
    return sink, final, bars, at


@pytest.mark.asyncio
async def test_deferred_request_is_not_a_session_or_order_and_cannot_be_rewritten(tmp_path, monkeypatch):
    sink, final, _, _ = await _original_request(tmp_path, monkeypatch)
    assert sink.validate()[0]["intent"]["intent_id"] == final.intent_id
    assert sink.validate()[0]["mode"] == MODE
    assert not sink.validate()[0]["risk_evaluated_live"]
    sink.requests[0]["requested_quantity"] = 0.002
    with pytest.raises(ValueError, match="MUTATION"):
        sink.validate()


@pytest.mark.asyncio
async def test_deferred_plan_requires_explicit_type_fresh_tape_and_original_sources(tmp_path, monkeypatch):
    sink, _, _, _ = await _original_request(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="FRESH_DECLARED"):
        replace(sink.plan, tape_id="some-older-sealed-tape")
    with pytest.raises(ValueError, match="BOUNDED_DEFERRED"):
        replace(sink.plan, ends_at_ms=sink.plan.started_at_ms + 900_001)
    with pytest.raises(ValueError, match="EXPLICIT_DEFERRED"):
        ObservedSimulationRequests(None, tmp_path / "invalid")


@pytest.mark.asyncio
async def test_later_native_risk_replay_preserves_expired_original_and_real_replay_clock(
    tmp_path, monkeypatch
):
    sink, final, _, at = await _original_request(tmp_path, monkeypatch, expired=True)
    decisions = []

    class Repository:
        async def verify_tape(self, tape_id):
            assert tape_id == sink.plan.tape_id
            return True

        async def create_session(self, session):
            assert session.tape_id == sink.plan.tape_id

        async def load_latest_book_frame(self, tape_id, symbol, *, as_of_ms):
            assert as_of_ms == at
            return None

        async def record_risk_decision(self, decision):
            decisions.append(decision)

    monkeypatch.setattr(module, "_now_ms", lambda: at + 100_000)
    result = await replay_observed_requests(
        Repository(),
        sink,
        seal=SimpleNamespace(tape_id=sink.plan.tape_id, tape_sha256="d" * 64),
        bars=dict.fromkeys(SYMBOLS, ()),
        frames=(),
    )
    assert len(decisions) == 1 and not decisions[0].approved
    assert "INTENT_EXPIRED" in decisions[0].rejection_reasons
    assert decisions[0].intent.entry_expires_ts_ms == final.entry_expires_ts_ms
    assert decisions[0].decided_at_ms == at
    assert result["actual_replay_started_ms"] == at + 100_000
    assert not result["actual_live_risk_or_execution"]
    assert result["sim_outcomes"][0]["fill_receipt"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ("remove", "replace"))
async def test_original_durability_receipt_is_required(tmp_path, monkeypatch, change):
    sink, _, _, _ = await _original_request(tmp_path, monkeypatch)
    path = sink.output / "request-01.durable.json"
    if change == "remove":
        path.unlink()
    else:
        path.write_bytes(b"{}\n")
    with pytest.raises(ValueError, match="DURABILITY_RECEIPT_MUTATION_OR_REMOVAL"):
        sink.validate()


def test_later_same_ms_frame_never_masks_omitted_earlier_frame(tmp_path):
    from test_current_tape import _accept, _Clocks, _start

    clocks = _Clocks()
    tape = _start(tmp_path, clocks)
    first = _accept(tape, clocks, "BTCUSDT", 1, clocks.ms)
    second = _accept(tape, clocks, "BTCUSDT", 2, clocks.ms)
    third = _accept(tape, clocks, "BTCUSDT", 3, clocks.ms)
    row = {
        "observed_request_ms": third.persisted_at_ms,
        "intent": {"symbol": "BTCUSDT"},
        "frame": first.model_dump(mode="json"),
        "selected_frame_sequence_watermark": first.tape_sequence,
    }
    with pytest.raises(ValueError, match="BOOK_SELECTION_CONFLICT"):
        module._validate_observed_selection(row, (first, second, third), third)
    row["frame"] = second.model_dump(mode="json")
    row["selected_frame_sequence_watermark"] = second.tape_sequence
    assert module._validate_observed_selection(row, (first, second, third), third) == second
    tape.finish()  # synthetic incomplete roster is deliberately not admitted.


@pytest.mark.asyncio
async def test_entry_arrival_after_original_window_is_not_started_or_clamped(tmp_path, monkeypatch):
    sink, _, _, at = await _original_request(tmp_path, monkeypatch, final_window_ms=10)
    recorded = []

    class Repository:
        async def verify_tape(self, tape_id):
            return True

        async def create_session(self, session):
            assert session.ends_at_ms == at + 10

        async def load_latest_book_frame(self, *args, **kwargs):
            return None

        async def record_risk_decision(self, decision):
            recorded.append(decision)

    # Clearly synthetic approval isolates the boundary; real native-Risk expiry
    # refusal is independently tested above. No execution method may be called.
    monkeypatch.setattr(
        module,
        "decide_sim",
        lambda **kw: (
            SimpleNamespace(approved=True, rejection_reasons=(), decision_id="synthetic-decision"),
            SimpleNamespace(admission_id="synthetic-admission"),
        ),
    )
    result = await replay_observed_requests(
        Repository(),
        sink,
        seal=SimpleNamespace(tape_id=sink.plan.tape_id, tape_sha256="d" * 64),
        bars=dict.fromkeys(SYMBOLS, ()),
        frames=(),
    )
    assert recorded and result["sim_outcomes"][0]["execution_state"] == (
        "NOT_SUBMITTED_ARRIVAL_OUTSIDE_ORIGINAL_WINDOW"
    )
    assert result["window_completion"] == "INSUFFICIENT_FUTURE_OBSERVATION"
    assert not result["full_trade_lifecycle_verified"]


@pytest.mark.asyncio
async def test_already_closed_bar_cannot_exit_later_entry_and_active_is_incomplete(tmp_path, monkeypatch):
    sink, intent, _, at = await _original_request(tmp_path, monkeypatch)

    class Repository:
        async def verify_tape(self, tape_id):
            return True

        async def create_session(self, session):
            return True

        async def load_latest_book_frame(self, *args, **kwargs):
            return None

        async def record_risk_decision(self, decision):
            return True

    class Controller:
        def __init__(self, *args, **kwargs):
            pass

        async def start_trade(self, admission, *, created_at_ms):
            return SimpleNamespace(
                symbol=intent.symbol, trade_id="synthetic-trade", created_at_ms=created_at_ms
            )

        async def submit_entry(self, trade, *, as_of_ms):
            assert as_of_ms == at + 25
            return SimpleNamespace(
                lifecycle_state="ACTIVE",
                receipt=SimpleNamespace(model_dump=lambda **kwargs: {"synthetic_fixture": True}),
            )

        async def process_closed_bar(self, *args, **kwargs):
            raise AssertionError("pre-entry bar must not trigger a stop or target")

    monkeypatch.setattr(module, "SimulationExecutionController", Controller)
    monkeypatch.setattr(
        module,
        "decide_sim",
        lambda **kw: (
            SimpleNamespace(approved=True, rejection_reasons=(), decision_id="synthetic-decision"),
            SimpleNamespace(admission_id="synthetic-admission"),
        ),
    )
    bars = dict.fromkeys(SYMBOLS, ())
    bars[intent.symbol] = (SimpleNamespace(symbol=intent.symbol, close_time_ms=at - 1),)
    result = await replay_observed_requests(
        Repository(),
        sink,
        seal=SimpleNamespace(tape_id=sink.plan.tape_id, tape_sha256="d" * 64),
        bars=bars,
        frames=(),
    )
    assert result["incomplete_lifecycles"][0]["trade_id"] == "synthetic-trade"
    assert result["window_completion"] == "INSUFFICIENT_FUTURE_OBSERVATION"
    assert not result["full_trade_lifecycle_verified"]


@pytest.mark.asyncio
async def test_full_history_and_observation_merge_precedes_seal_without_synthetic_gap_fill():
    histories = {
        symbol: tuple(
            Candle(symbol, "1m", t, t + 59_999, 100.0, 101.0, 99.0, 100.0, 10.0)
            for t in range(START - 3240 * 60_000, START, 60_000)
        )
        for symbol in SYMBOLS
    }
    recorded = []

    class Repository:
        async def record_closed_bar(self, tape_id, bar):
            recorded.append((tape_id, bar.bar_sha256))

    counts, bars = await import_complete_tape(
        Repository(),
        tape_id="synthetic-test-only",
        history=SimpleNamespace(bars_by_symbol=histories),
        observed_bars=dict.fromkeys(SYMBOLS, ()),
        frames=(),
    )
    assert len(recorded) == 16_200 and all(count == 3_240 for count in counts.values())
    assert len(bars[SYMBOLS[0]]) == 3_240
    gap = Candle(SYMBOLS[0], "1m", START + 60_000, START + 119_999, 100.0, 101.0, 99.0, 100.0, 10.0)
    observed = dict.fromkeys(SYMBOLS, ())
    observed[SYMBOLS[0]] = (SimpleNamespace(candle=gap),)
    with pytest.raises(ValueError, match="PROVENANCE_GAP"):
        await import_complete_tape(
            Repository(),
            tape_id="synthetic-test-only-gap",
            history=SimpleNamespace(bars_by_symbol=histories),
            observed_bars=observed,
            frames=(),
        )
