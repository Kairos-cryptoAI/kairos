"""Fixed five-day portfolio mechanics, never historical/model economics."""

import hashlib
from dataclasses import replace
from decimal import Decimal as D

import pytest
from kairos_core.enums import Side
from kairos_execution.simulation.models import AcceptedBookFrame, BookLevel, FillAssumptions
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay import adaptive_sim_account as account_api
from adaptive_replay import continuous_sim_v3_horizon as horizon_module
from adaptive_replay.candle_originals_v3 import RetainedCandleV3
from adaptive_replay.continuous_sim import (
    UNIVERSE,
    ClosedCandleInput,
    ContinuousSimPortfolio,
    FundingInput,
    FundingSchedule,
    SimInputError,
    SymbolRules,
    TapeBinding,
    TapeInput,
    _available,
)
from adaptive_replay.continuous_sim_v3_horizon import (
    FIVE_DAYS,
    MAX_BATCH,
    ContinuousSimV3Horizon,
    FiveDayHorizonV3,
    HorizonCandleOriginalsV3,
    HorizonTapeBindingV3,
    NoRouteDecisionV3,
    PublicSegmentOriginalV3,
)
from adaptive_replay.historical_context import canonical, digest
from adaptive_replay.hypothesis_journal_v3 import (
    ArmReviewReceiptV3,
    HypothesisJournalV3,
    JournalArmV3,
    JournalSealV3,
    MatchedObservationV3,
)
from adaptive_replay.hypothesis_v3 import EntryQuote, HypothesisObservation, HypothesisPlan, HypothesisPolicy
from adaptive_replay.scenarios import ScenarioEvidence, ScenarioObservation
from adaptive_replay.sim_account_codec import decode_account, encode_account
from adaptive_replay.sim_book_tape import BoundBookFrame, PublicBookTape

START, MINUTE, DAY, SHA = 86_400_000, 60_000, 86_400_000, "a" * 64
CUT = START + DAY - 2 * MINUTE
ISSUE = CUT + MINUTE + 200


def frame(*, symbol="BTCUSDT", seq=1, at=ISSUE - 2, bid="100.49", ask="100.50", qty="0.2"):
    return AcceptedBookFrame(
        tape_id="horizon-tape",
        stream_epoch="one-epoch",
        symbol=symbol,
        sequence=seq,
        exchange_update_id=seq * 10,
        exchange_at_ms=at - 2,
        received_at_ms=at - 1,
        persisted_at_ms=at,
        raw_payload_sha256=SHA,
        continuity="ADMITTED",
        bids=(BookLevel(price=D(bid), quantity=D(qty)),),
        asks=(BookLevel(price=D(ask), quantity=D(qty)),),
    )


def original(symbol, open_ms, close=100.0):
    candle = Candle(symbol, "1m", open_ms, open_ms + MINUTE - 1, 100.0, 101.5, 99.5, close, 10.0)
    receipt = ScenarioEvidence(
        "bars",
        "MARKET",
        symbol,
        digest(candle_payload(candle)),
        candle.close_time_ms,
        open_ms + MINUTE,
        open_ms + MINUTE,
        600_000,
    )
    return RetainedCandleV3(candle, receipt, open_ms + MINUTE, "TEST_FIXTURE")


@pytest.fixture(scope="module")
def originals():
    records = tuple(
        original(s, START + i * MINUTE, 100.5 if s == "BTCUSDT" and START + i * MINUTE == CUT else 100.0)
        for s in UNIVERSE
        for i in range(7200)
    )
    return HorizonCandleOriginalsV3(records)


def models():
    return {
        s: FillAssumptions(
            latency_ms=2,
            maximum_book_age_ms=60_000,
            maximum_frame_latency_ms=5000,
            depth_participation_fraction=D(1),
            adverse_slippage_bps=D(0),
            taker_fee_bps=D(10),
            price_tick=D("0.01"),
            quantity_step=D("0.001"),
        )
        for s in UNIVERSE
    }


def source_binding(originals, extra=()):
    values = [
        ClosedCandleInput(
            r.candle.symbol,
            r.candle.open_time_ms,
            r.candle.close_time_ms,
            r.available_at_ms,
            D(str(r.candle.close)),
            r.evidence.source_id,
            "TEST_FIXTURE",
            r.evidence.payload_sha256,
        )
        for r in originals.records
    ]
    values.extend(extra)
    values.sort(key=lambda v: (_available(v), 0 if type(v) is FundingInput else 1))
    return HorizonTapeBindingV3(
        "fixture-source",
        "horizon-tape",
        "one-epoch",
        "quotes",
        "TEST_FIXTURE",
        tuple(TapeInput(i, value) for i, value in enumerate(values, 1)),
    )


def runner(tmp_path, originals, binding, *, seal=SHA, due=(), expected_cost_ids=(), **storage):
    return ContinuousSimV3Horizon.create(
        tmp_path / "horizon.sqlite3",
        campaign_id="horizon-fixture",
        arm_id="arm",
        binding=binding,
        models=models(),
        rules={s: SymbolRules(s, D("0.01"), D("0.001"), D("100000")) for s in UNIVERSE},
        funding_schedule=FundingSchedule("funding", "TEST_FIXTURE", tuple(sorted(due)), SHA),
        horizon=FiveDayHorizonV3(START, START + FIVE_DAYS + 3 * 3_600_000, START),
        initial_equity=D(1000),
        hypothesis_seal_sha256=seal,
        candle_originals=originals,
        allowed_origins=("TECHNICAL",),
        expected_cost_ids=expected_cost_ids,
        **storage,
    )


def consume(portfolio, through):
    cursor = portfolio.snapshot().state["cursor"]
    last = cursor
    while (
        last < len(portfolio.binding.inputs) and _available(portfolio.binding.inputs[last].value) <= through
    ):
        last += 1
    while cursor < last:
        end = min(last, cursor + MAX_BATCH)
        portfolio.ingest_batch(first_sequence=cursor + 1, last_sequence=end)
        cursor = end


def reopen(portfolio):
    args = dict(
        identity=portfolio.journal.identity,
        expected_checkpoint=portfolio.journal.checkpoint(),
        binding=portfolio.binding,
        models=portfolio.models,
        rules=portfolio.rules,
        funding_schedule=portfolio.funding,
        config=portfolio.config,
        candle_originals=portfolio.candle_originals,
    )
    path = portfolio.path
    portfolio.close()
    return ContinuousSimV3Horizon.open(path, **args)


def seal_cells(portfolio, *, unavailable=None):
    existing = portfolio.snapshot().state["slots"]
    cells = tuple(
        sorted(
            (s, m, "UNAVAILABLE" if (s, m) == unavailable else "QUIET")
            for s in UNIVERSE
            for m in portfolio.config["minutes"]
            if f"{s}:{m}" not in existing
        )
    )
    for offset in range(0, len(cells), MAX_BATCH):
        portfolio.record_slots_batch(
            cells=cells[offset : offset + MAX_BATCH],
            source_sha256=SHA,
            at_ms=portfolio.config["horizon"]["retained_end_ms"],
        )


def hypothesis(tmp_path, originals, entry_frame):
    policy = HypothesisPolicy(START - 1, 5 * MINUTE, "quotes", 5000, "TEST_FIXTURE", False)
    anchor = originals._index["BTCUSDT", CUT - MINUTE]
    template = SleeveIntent(
        "trend_breakout_v1",
        "BTCUSDT",
        Side.LONG,
        CUT - 1,
        CUT,
        CUT + MINUTE - 1,
        100.0,
        0.7,
        600.0,
        ExitPlan(98.5, 106.0, 300_000, None, None),
        (),
    )
    plan = HypothesisPlan(
        template,
        "TECHNICAL",
        "BULL",
        CUT,
        CUT + 10,
        SHA,
        "b" * 64,
        (anchor.evidence,),
        anchor.candle,
        (("MARKET", "bars"),),
        policy,
    )
    seal = JournalSealV3("five-day-producer", START - 1, SHA, (JournalArmV3("arm", policy),), 16)
    producer = HypothesisJournalV3.create(tmp_path / "producer.research.sqlite3", seal)
    producer.register("arm", plan)
    trigger = originals._index["BTCUSDT", CUT]
    quote = EntryQuote(
        "quotes",
        "BTCUSDT",
        float(entry_frame.bids[0].price),
        float(entry_frame.asks[0].price),
        entry_frame.exchange_at_ms,
        entry_frame.received_at_ms,
        entry_frame.persisted_at_ms,
        5000,
        "TEST_FIXTURE",
    )
    shared = HypothesisObservation(ScenarioObservation(trigger.candle, ISSUE, (trigger.evidence,)), quote)
    receipt = producer.append(
        template.intent_id, MatchedObservationV3(shared, (ArmReviewReceiptV3("arm", ISSUE, ISSUE),))
    )[0]
    assert receipt.evaluation.candidate is not None
    return producer, receipt


def test_real_full_five_day_portfolio_partial_cross_day_funding_cost_restart(tmp_path, originals):
    """Full fixed mechanical source/denominator; economics remains unqualified."""
    entry = frame()
    exit_one = frame(seq=2, at=START + DAY + MINUTE + 100, bid="106", ask="106.01", qty="0.1")
    exit_two = frame(seq=3, at=START + DAY + MINUTE + 110, bid="106.01", ask="106.02", qty="0.1")
    due = START + DAY
    funding = FundingInput(
        "BTCUSDT",
        due,
        START + DAY + 2 * MINUTE,
        "funding",
        "TEST_FIXTURE",
        "SETTLED",
        D("0.001"),
        D(101),
        SHA,
    )
    binding = source_binding(originals, (entry, exit_one, exit_two, funding))
    producer, receipt = hypothesis(tmp_path, originals, entry)
    portfolio = runner(
        tmp_path,
        originals,
        binding,
        seal=producer.snapshot().seal_sha256,
        due=(("BTCUSDT", due),),
        expected_cost_ids=("fixed-service",),
    )
    try:
        consume(portfolio, ISSUE)
        admitted = portfolio.intake_v3(
            hypothesis_journal=producer,
            receipt=receipt,
            expected_hypothesis_head_sha256=producer.snapshot().head_sha256,
            at_ms=ISSUE,
        )
        assert admitted.outcome["status"] == "PENDING"
        portfolio.advance_to(now_ms=ISSUE + 2, event_id="entry-arrival")
        before = decode_account(portfolio.snapshot().state["account"])
        assert before.positions[0].quantity == D("0.2")
        portfolio = reopen(portfolio)
        version = portfolio.snapshot().version
        assert portfolio.intake_v3(
            hypothesis_journal=producer,
            receipt=receipt,
            expected_hypothesis_head_sha256=producer.snapshot().head_sha256,
            at_ms=ISSUE,
        ).replayed
        assert portfolio.snapshot().version == version
        consume(portfolio, START + DAY + MINUTE + 112)
        portfolio.advance_to(now_ms=START + DAY + MINUTE + 112, event_id="natural-exit")
        closed = decode_account(portfolio.snapshot().state["account"])
        assert not closed.positions
        assert portfolio.snapshot().state["parents"][receipt.parent_id]["closed"]
        assert portfolio.snapshot().state["parents"][receipt.parent_id]["exposure"][0][0] < START + DAY
        portfolio = reopen(portfolio)
        consume(portfolio, START + DAY + 2 * MINUTE)
        assert decode_account(portfolio.snapshot().state["account"]).cash == closed.cash - D("0.0202")
        portfolio.debit_service(cost_id="fixed-service", amount=D("0.01"), at_ms=START + DAY + 2 * MINUTE)
        consume(portfolio, portfolio.config["horizon"]["retained_end_ms"])
        seal_cells(portfolio)
        final = portfolio.finish(
            now_ms=portfolio.config["horizon"]["retained_end_ms"], event_id="finish"
        ).outcome
        assert final["status"] == "COMPLETE" and final["denominator_cells"] == 36_000
        assert final["episode_minutes"] == 7200 and final["natural_closes"] == 1
        assert final["qualified_economics"] is None and final["source_authentication"] is False
        assert final["accepted_historical_inputs"] is False
        state = portfolio.snapshot().state
        assert (
            state["cursor"] == len(binding.inputs) and len(state["candles"]) == len(state["slots"]) == 36_000
        )
        assert len(state["liquidity"]["BTCUSDT"]["receipts"]) == 3
        final_snapshot = portfolio.snapshot()
        portfolio = reopen(portfolio)
        assert portfolio.snapshot() == final_snapshot
    finally:
        portfolio.close()


def test_batch_has_same_full_financial_fold_as_unbatched_short_prefix(tmp_path, originals):
    first, second = frame(at=START + 10), frame(seq=2, at=START + 20, bid="100.59", ask="100.60")
    portfolio = runner(tmp_path, originals, source_binding(originals, (first, second)))
    native = ContinuousSimPortfolio.create(
        tmp_path / "native.sqlite3",
        campaign_id="native-short-reference",
        arm_id="arm",
        binding=TapeBinding(
            "fixture-source",
            "horizon-tape",
            "one-epoch",
            "quotes",
            "TEST_FIXTURE",
            (TapeInput(1, first), TapeInput(2, second)),
        ),
        models=models(),
        rules=portfolio.rules,
        funding_schedule=FundingSchedule("funding", "TEST_FIXTURE", (), SHA),
        minutes=(START,),
        initial_equity=D(1000),
        hypothesis_seal_sha256=SHA,
    )
    try:
        native.ingest(global_sequence=1, now_ms=first.persisted_at_ms)
        native.ingest(global_sequence=2, now_ms=second.persisted_at_ms)
        expected = native.snapshot().state
        portfolio.ingest_batch(first_sequence=1, last_sequence=2)
        actual = portfolio.snapshot().state
        for field in ("account", "latest", "liquidity", "parents", "pending", "funding", "cursor"):
            if field == "account":
                actual_account = replace(decode_account(actual[field]), events=())
                expected_account = replace(decode_account(expected[field]), events=())
                assert encode_account(actual_account) == encode_account(expected_account)
            else:
                assert actual[field] == expected[field]
        saved = portfolio.snapshot()
        assert portfolio.ingest_batch(first_sequence=1, last_sequence=2).replayed
        assert portfolio.snapshot() == saved
        with pytest.raises(SimInputError):
            portfolio.ingest_batch(first_sequence=4, last_sequence=5)
        assert portfolio.snapshot() == saved
    finally:
        native.close()
        portfolio.close()


@pytest.mark.parametrize(
    "kind", ["flat", "stale", "regressing", "future", "reservation", "missing_active_mark"]
)
def test_mark_optimization_preserves_all_native_financial_and_failure_gates(kind):
    portfolio = object.__new__(ContinuousSimV3Horizon)
    policy = account_api.AccountPolicy(D("0.001"), D(10), D(10), D(0), 5000, "ENTRY_STOP_RESERVED")
    account = account_api.new_account(D(1000), policy)
    account, _ = account_api.mark_account(
        account, mark_id="initial", marks=(("BTCUSDT", D(100), 60000),), as_of_ms=60000
    )
    symbol, at, now = "BTCUSDT", 61002, 61002
    if kind in {"reservation", "missing_active_mark"}:
        account, reservation, reason = account_api.reserve_entry(
            account,
            reservation_id="reserve",
            intent_id="parent",
            symbol="BTCUSDT",
            side="LONG",
            stop_price=D("98.5"),
            worst_entry_price=D(100),
            worst_notional_price=D(100),
            as_of_ms=60000,
            expires_at_ms=70000,
        )
        assert reservation is not None and reason == "RESERVED"
    if kind == "stale":
        now = 70000
    elif kind == "regressing":
        at = 59002
    elif kind == "future":
        now = 60000
    elif kind == "missing_active_mark":
        symbol, at, now = "ETHUSDT", 70002, 70002
    book = frame(symbol=symbol, at=at)
    native = ContinuousSimPortfolio._mark_book(portfolio, account, book, 1, now)
    horizon = portfolio._mark_book(account, book, 1, now)
    assert encode_account(replace(native, events=())) == encode_account(replace(horizon, events=()))
    if kind != "flat":
        assert native.events == horizon.events
    else:
        assert horizon.events == account.events


def test_fixed_horizon_no_daily_reset_or_old_short_window_adoption():
    horizon = FiveDayHorizonV3(START, START + FIVE_DAYS, START)
    assert len(horizon.minutes) == 7200 and horizon.entry_end_ms - horizon.entry_start_ms == FIVE_DAYS
    with pytest.raises(SimInputError):
        FiveDayHorizonV3(START, START + DAY, START)
    with pytest.raises(SimInputError):
        FiveDayHorizonV3(START, START + FIVE_DAYS + 4 * 3_600_000, START)


def test_missing_full_candle_cell_nonfixture_roster_and_oversized_batch_failclosed(tmp_path, originals):
    binding = source_binding(originals)
    missing = replace(
        binding, inputs=tuple(TapeInput(i, item.value) for i, item in enumerate(binding.inputs[:-1], 1))
    )
    with pytest.raises(SimInputError, match="36,000"):
        runner(tmp_path, originals, missing)
    with pytest.raises(SimInputError, match="public segments"):
        replace(binding, evidence_kind="CALLER_ATTESTED_POINT_IN_TIME")
    portfolio = runner(tmp_path, originals, binding)
    try:
        before = portfolio.snapshot()
        with pytest.raises(SimInputError, match="batch"):
            portfolio.ingest_batch(first_sequence=1, last_sequence=MAX_BATCH + 1)
        assert portfolio.snapshot() == before
        with pytest.raises(SimInputError, match="presealed"):
            portfolio.finish(now_ms=START + DAY, event_id="daily-finish")
        assert portfolio.snapshot() == before
    finally:
        portfolio.close()


def structural_public_segment():
    """Invented budget-test bytes ONLY; never authenticated/historical evidence."""
    payload = '{"budget_test_fixture":true}'
    payload_sha = hashlib.sha256(payload.encode()).hexdigest()
    book = frame(at=START + 10).model_copy(update={"tape_id": "segment", "raw_payload_sha256": payload_sha})
    row = {
        "sequence": 1,
        "previous_record_sha256": None,
        "received_ms": book.received_at_ms,
        "received_monotonic_ns": 100,
        "raw_payload": payload,
        "raw_payload_sha256": payload_sha,
    }
    row["record_sha256"] = digest(row)
    raw = (canonical(row) + "\n").encode()
    receipt = {
        "raw_file_sha256": hashlib.sha256(raw).hexdigest(),
        "source_sha256": SHA,
        "epoch": book.stream_epoch,
        "state": "CAPTURED",
        "observed_stream_check": "PASS",
        "admitted_frames": 1,
        "observed_messages": 1,
        "raw_payload_bytes": len(payload.encode()),
        "raw_head_sha256": row["record_sha256"],
    }
    receipt_bytes = (canonical(receipt) + "\n").encode()
    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    segment = PublicBookTape(
        receipt_sha,
        SHA,
        "segment",
        "one-epoch",
        "quotes",
        (BoundBookFrame(book, receipt_sha, "b" * 64, row["record_sha256"], 1, 1),),
    )
    originals = PublicSegmentOriginalV3(receipt_bytes, raw)
    rebased = book.model_copy(update={"tape_id": "horizon-tape"})
    binding = HorizonTapeBindingV3(
        "budget-test",
        "horizon-tape",
        "one-epoch",
        "quotes",
        "CALLER_ATTESTED_POINT_IN_TIME",
        (TapeInput(1, rebased),),
        (segment,),
        (segment.sha256,),
        (originals,),
    )
    return binding, originals, segment


def test_original_public_aggregate_bytes_hash_count_and_normalized_caps(monkeypatch):
    binding, retained, segment = structural_public_segment()
    assert retained.byte_count == len(retained.receipt_bytes) + len(retained.received_raw_bytes)
    retained.validate(segment)
    with pytest.raises(SimInputError, match="receipt/segment"):
        replace(retained, received_raw_bytes=retained.received_raw_bytes + b"\n").validate(segment)
    with pytest.raises(SimInputError, match="roster"):
        replace(binding, inputs=())
    with monkeypatch.context() as context:
        context.setattr(horizon_module, "MAX_PUBLIC_ORIGINAL_BYTES", retained.byte_count - 1)
        with pytest.raises(SimInputError, match="aggregate original"):
            replace(binding)
    with monkeypatch.context() as context:
        context.setattr(horizon_module, "MAX_NORMALIZED_INPUT_BYTES", 1)
        with pytest.raises(SimInputError, match="normalized"):
            replace(binding)
    with pytest.raises(SimInputError, match="public segments"):
        replace(binding, segment_originals=())


def test_preflight_entire_first_receipt_roster_does_not_silently_raise_old_cap():
    ids = tuple(f"parent-{i:03d}" for i in range(128))
    assert ContinuousSimV3Horizon.preflight_parent_roster(
        parent_ids=ids,
        expected_roster_sha256=digest(ids),
    ) == digest(ids)
    too_many = ids + ("parent-128",)
    with pytest.raises(SimInputError, match="capacity"):
        ContinuousSimV3Horizon.preflight_parent_roster(
            parent_ids=too_many,
            expected_roster_sha256=digest(too_many),
        )
    with pytest.raises(SimInputError, match="commitment"):
        ContinuousSimV3Horizon.preflight_parent_roster(parent_ids=ids, expected_roster_sha256=SHA)


def no_route_decision(**changes):
    return NoRouteDecisionV3(
        parent_id="excluded-parent",
        symbol="BTCUSDT",
        origin="CONTEXT_PROPOSAL",
        actual_decision_ms=START + MINUTE,
        producer_seal_sha256=SHA,
        producer_head_sha256=SHA,
        native_sequence=1,
        native_chain_sha256=SHA,
        native_receipt_sha256=SHA,
        plan_sha256=SHA,
        native_reason="TRIGGERED",
        disposition_reason="ORIGIN_NOT_ROUTED",
        driver_seal_sha256=SHA,
        **changes,
    )


def test_cost_roster_unknown_retention_and_exact_no_route_event(tmp_path, originals):
    portfolio = runner(
        tmp_path,
        originals,
        source_binding(originals),
        expected_cost_ids=("known", "unavailable"),
        no_route_driver_seal_sha256=SHA,
    )
    try:
        before = portfolio.snapshot()
        for cost_id in ("not-presealed",):
            with pytest.raises(SimInputError, match="roster"):
                portfolio.debit_service(cost_id=cost_id, amount=D("0.01"), at_ms=START)
            with pytest.raises(SimInputError, match="roster"):
                portfolio.record_unknown_service(cost_id=cost_id, source_sha256=SHA, at_ms=START)
        assert portfolio.snapshot() == before
        portfolio.record_unknown_service(cost_id="known", source_sha256=SHA, at_ms=START)
        portfolio.debit_service(cost_id="known", amount=D("0.01"), at_ms=START)
        portfolio.record_unknown_service(cost_id="unavailable", source_sha256=SHA, at_ms=START)
        assert (
            portfolio.snapshot().state["service_liabilities"]["known"]["earlier_unavailable"]["status"]
            == "UNAVAILABLE"
        )
        cell = (("BTCUSDT", START + MINUTE),)
        decision = no_route_decision()
        args = dict(cells=cell, decisions=(decision,), source_sha256=SHA, at_ms=START + MINUTE)
        with pytest.raises(SimInputError, match="source prefix"):
            portfolio.record_no_route_cells(**args)
        assert portfolio.replay_source_through(now_ms=START + MINUTE)["source_items"] == 5
        event_id, payload = portfolio.no_route_event(**args)
        receipt = portfolio.record_no_route_cells(**args)
        state = portfolio.snapshot().state
        assert state["slots"][f"BTCUSDT:{START + MINUTE}"]["status"] == "NO_ROUTE"
        assert (
            state["slots"][f"BTCUSDT:{START + MINUTE}"]["native_decisions"][0]["native_reason"] == "TRIGGERED"
        )
        assert (
            portfolio.journal.lookup(event_id=event_id, payload=payload).snapshot.head_hash
            == receipt.snapshot.head_hash
        )
        saved = portfolio.snapshot()
        assert portfolio.record_no_route_cells(**args).replayed
        assert portfolio.snapshot() == saved
        with pytest.raises(SimInputError, match="overwrite"):
            portfolio.record_no_route_cells(**(args | {"source_sha256": "b" * 64}))
        assert portfolio.snapshot() == saved
        unavailable_cell = (("ETHUSDT", START, "UNAVAILABLE"),)
        portfolio.record_slots_batch(cells=unavailable_cell, source_sha256=SHA, at_ms=START + MINUTE)
        eth = replace(decision, parent_id="excluded-eth", symbol="ETHUSDT", actual_decision_ms=START + 10)
        with pytest.raises(SimInputError, match="overwrite"):
            portfolio.record_no_route_cells(
                cells=(("ETHUSDT", START),),
                decisions=(eth,),
                source_sha256=SHA,
                at_ms=START + MINUTE,
            )
        with pytest.raises(SimInputError, match="routing|seal"):
            portfolio.record_no_route_cells(
                **(args | {"decisions": (replace(decision, origin="TECHNICAL"),)})
            )
        with pytest.raises(SimInputError, match="seal"):
            portfolio.record_no_route_cells(
                **(args | {"decisions": (replace(decision, driver_seal_sha256="b" * 64),)})
            )
        with pytest.raises(SimInputError, match="known"):
            replace(decision, coverage="UNAVAILABLE")
        with pytest.raises(SimInputError, match="clock"):
            portfolio.record_no_route_cells(**(args | {"at_ms": START + MINUTE - 1}))
    finally:
        portfolio.close()
