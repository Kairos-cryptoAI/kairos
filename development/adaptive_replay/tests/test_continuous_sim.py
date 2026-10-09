"""Full mechanical portfolio path on explicit synthetic evidence, never alpha proof."""

from decimal import Decimal as D

import pytest
from kairos_core.enums import Side
from kairos_execution.simulation.models import AcceptedBookFrame, BookLevel, FillAssumptions
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

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
)
from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_journal import HypothesisJournal, JournalArm, JournalSeal
from adaptive_replay.hypothesis_v2 import EntryQuote, HypothesisObservation, HypothesisPlan, HypothesisPolicy
from adaptive_replay.scenarios import ScenarioEvidence, ScenarioObservation
from adaptive_replay.sim_account_codec import decode_account

START, MINUTE = 86_400_000, 60_000
ISSUE, SHA = START + MINUTE + 20, "a" * 64


def book(
    symbol="BTCUSDT",
    *,
    seq=1,
    at=ISSUE - 8,
    bid="100.49",
    ask="100.5",
    bqty="20",
    aqty="20",
    continuity="ADMITTED",
):
    return AcceptedBookFrame(
        tape_id="fixture-tape",
        stream_epoch="fixture-epoch",
        symbol=symbol,
        sequence=seq,
        exchange_update_id=seq * 10,
        exchange_at_ms=at - 2,
        received_at_ms=at - 1,
        persisted_at_ms=at,
        raw_payload_sha256=SHA,
        continuity=continuity,
        bids=(BookLevel(price=D(bid), quantity=D(bqty)),),
        asks=(BookLevel(price=D(ask), quantity=D(aqty)),),
    )


def models(age=5000, fees="10"):
    return {
        s: FillAssumptions(
            latency_ms=2,
            maximum_book_age_ms=age,
            maximum_frame_latency_ms=5000,
            depth_participation_fraction=D(1),
            adverse_slippage_bps=D(0),
            taker_fee_bps=D(fees),
            price_tick=D("0.01"),
            quantity_step=D("0.001"),
        )
        for s in UNIVERSE
    }


def bar(symbol, open_at, close=100.5):
    return Candle(symbol, "1m", open_at, open_at + MINUTE - 1, 100, 101, 99, close, 10)


def evidence(c):
    return ScenarioEvidence(
        "bars",
        "MARKET",
        c.symbol,
        digest(candle_payload(c)),
        c.close_time_ms,
        c.close_time_ms + 1,
        c.close_time_ms + 1,
        600_000,
    )


def parent(symbol="BTCUSDT", *, label="one", side=Side.LONG, holding=300_000, trailing=True, created=START):
    long = side is Side.LONG
    anchor = bar(symbol, created - MINUTE, 100.0)
    template = SleeveIntent(
        "trend_breakout_v1",
        symbol,
        side,
        created - 1,
        created,
        created + MINUTE - 1,
        100.0,
        0.7,
        600.0,
        ExitPlan(
            98.5 if long else 101.5,
            106.0 if long else 94.0,
            holding,
            (103.0 if long else 97.0) if trailing else None,
            1.0 if trailing else None,
        ),
        (("variant", label),),
    )
    policy = HypothesisPolicy(START - 1, 5 * MINUTE, "quotes", 5000, "TEST_FIXTURE", False)
    return HypothesisPlan(
        template,
        "TECHNICAL",
        "BULL" if long else "BEAR",
        created,
        SHA,
        "b" * 64,
        (evidence(anchor),),
        anchor,
        (("MARKET", "bars"),),
        policy,
    )


def issue_journal(tmp_path, plans, quote_books, *, arms=("arm",), missing_quote=False):
    seal = JournalSeal(
        "fixture-hypotheses",
        START - 1,
        SHA,
        tuple(JournalArm(arm, plans[0].policy) for arm in arms),
        max(16, len(plans) * len(arms)),
    )
    h = HypothesisJournal.create(tmp_path / "hypotheses.research.sqlite3", seal)
    for arm in arms:
        for p in plans:
            h.register(arm, p)
    receipts = {}
    for arm in arms:
        for p in plans:
            f = quote_books[p.template.symbol]
            c = bar(f.symbol, START, 100.5 if p.template.side is Side.LONG else 99.5)
            q = EntryQuote(
                "quotes",
                f.symbol,
                float(f.bids[0].price),
                float(f.asks[0].price),
                f.exchange_at_ms,
                f.received_at_ms,
                f.persisted_at_ms,
                5000,
                "TEST_FIXTURE",
            )
            obs = HypothesisObservation(
                ScenarioObservation(c, ISSUE, (evidence(c),)), None if missing_quote else q
            )
            receipts[arm, p.template.intent_id] = h.append(arm, p.template.intent_id, obs)
    return h, receipts


def runner(
    tmp_path,
    values,
    *,
    h=None,
    arm="arm",
    due=(),
    age=5000,
    equity="1000",
    fees="10",
    minutes=(START + MINUTE,),
):
    binding = TapeBinding(
        "fixture-source",
        "fixture-tape",
        "fixture-epoch",
        "quotes",
        "TEST_FIXTURE",
        tuple(TapeInput(i, v) for i, v in enumerate(values, 1)),
    )
    rules = {s: SymbolRules(s, D("0.01"), D("0.001"), D("100000")) for s in UNIVERSE}
    return ContinuousSimPortfolio.create(
        tmp_path / f"{arm}.sqlite3",
        campaign_id="fixture-campaign",
        arm_id=arm,
        binding=binding,
        models=models(age, fees),
        rules=rules,
        funding_schedule=FundingSchedule("funding", "TEST_FIXTURE", tuple(sorted(due)), SHA),
        minutes=minutes,
        initial_equity=D(equity),
        hypothesis_seal_sha256=SHA if h is None else h.snapshot().seal_sha256,
    )


def ingest(r, seq):
    v = r.binding.inputs[seq - 1].value
    return r.ingest(
        global_sequence=seq,
        now_ms=v.persisted_at_ms if isinstance(v, AcceptedBookFrame) else v.available_at_ms,
    )


def intake(r, h, receipt):
    return r.intake(
        hypothesis_journal=h,
        receipt=receipt,
        expected_hypothesis_head_sha256=h.snapshot().head_sha256,
        at_ms=ISSUE,
    )


def account(r):
    return decode_account(r.snapshot().state["account"])


def seal_slots(r, at=START + 2 * MINUTE):
    existing = r.snapshot().state["slots"]
    for minute in r.config["minutes"]:
        for s in UNIVERSE:
            if f"{s}:{minute}" not in existing:
                r.record_slot(symbol=s, minute=minute, status="QUIET", source_sha256=SHA, at_ms=at)


def reopen(r):
    path, identity, snap = r.path, r.journal.identity, r.snapshot()
    args = dict(
        identity=identity,
        binding=r.binding,
        models=r.models,
        rules=r.rules,
        funding_schedule=r.funding,
        config=r.config,
        expected_head_sha256=snap.head_hash,
    )
    r.close()
    return ContinuousSimPortfolio.open(path, **args)


def test_full_v2_partial_entry_crash_reopen_duplicate_partial_stop(tmp_path):
    p, f = parent(), book(aqty="0.2")
    stops = [
        book(seq=2, at=ISSUE + 100, bid="98", ask="98.01", bqty="0.1"),
        book(seq=3, at=ISSUE + 110, bid="98", ask="98.01", bqty="0.1"),
        book(seq=4, at=ISSUE + 120, bid="98.01", ask="98.02", bqty="0.1"),
    ]
    h, receipts = issue_journal(tmp_path, [p], {f.symbol: f})
    receipt = receipts["arm", p.template.intent_id]
    r = runner(tmp_path, [f, *stops], h=h)
    ingest(r, 1)
    assert intake(r, h, receipt).outcome["status"] == "PENDING"
    assert receipt.evaluation.candidate.entry_eligible_ts_ms == ISSUE
    assert receipt.evaluation.candidate.exit_plan == p.template.exit_plan
    r = reopen(r)
    r.advance_to(now_ms=ISSUE + 2, event_id="entry-arrival")
    assert account(r).positions[0].quantity == D("0.2") and not account(r).barrier
    assert account(r).reservations[0].terminal == "PARTIAL"
    r = reopen(r)
    version = r.snapshot().version
    assert intake(r, h, receipt).replayed
    assert r.advance_to(now_ms=ISSUE + 2, event_id="entry-arrival").replayed
    assert r.snapshot().version == version
    ingest(r, 2)
    r.advance_to(now_ms=ISSUE + 102, event_id="exit-one")
    assert account(r).positions[0].quantity == D("0.1") and account(r).protective_exit_pending
    r = reopen(r)
    ingest(r, 3)
    r.advance_to(now_ms=ISSUE + 112, event_id="exit-two")
    assert account(r).positions[0].quantity == D("0.1")  # no same-price replenishment
    ingest(r, 4)
    r.advance_to(now_ms=ISSUE + 122, event_id="exit-three")
    assert not account(r).positions and not account(r).protective_exit_pending and not account(r).barrier
    seal_slots(r)
    result = r.finish(now_ms=START + 2 * MINUTE, event_id="finish").outcome
    assert (
        result["status"] == "COMPLETE"
        and result["natural_closes"] == 1
        and result["qualified_economics"] is None
    )
    assert len(r.snapshot().state["liquidity"]["BTCUSDT"]["receipts"]) == 4
    r.close()


@pytest.mark.parametrize(
    "side,reason,bid,ask",
    [
        (Side.LONG, "TARGET", "106", "106.01"),
        (Side.SHORT, "TARGET", "93.99", "94"),
        (Side.SHORT, "STOP", "101.59", "101.6"),
    ],
)
def test_natural_long_short_targets_and_short_stop(tmp_path, side, reason, bid, ask):
    p = parent(side=side)
    f = book(bid="99.5", ask="99.51") if side is Side.SHORT else book()
    h, receipts = issue_journal(tmp_path, [p], {f.symbol: f})
    r = runner(tmp_path, [f, book(seq=2, at=ISSUE + 100, bid=bid, ask=ask)], h=h)
    ingest(r, 1)
    assert intake(r, h, receipts["arm", p.template.intent_id]).outcome["status"] == "PENDING"
    r.advance_to(now_ms=ISSUE + 2, event_id="entry")
    assert not account(r).barrier
    ingest(r, 2)
    r.advance_to(now_ms=ISSUE + 102, event_id="exit")
    assert not account(r).positions
    assert r.snapshot().state["parents"][p.template.intent_id]["exit_reason"] == reason
    seal_slots(r)
    assert r.finish(now_ms=START + 2 * MINUTE, event_id="finish").outcome["status"] == "COMPLETE"
    r.close()


def test_closed_only_trailing_preserves_initial_risk_and_never_clamps_target(tmp_path):
    p, f = parent(), book(aqty="0.2")
    high = book(seq=2, at=START + 2 * MINUTE - 2, bid="104", ask="104.01")
    candle = ClosedCandleInput(
        "BTCUSDT",
        START + MINUTE,
        START + 2 * MINUTE - 1,
        START + 2 * MINUTE,
        D("107"),
        "bars",
        "TEST_FIXTURE",
        SHA,
    )
    stopped = book(seq=3, at=START + 2 * MINUTE + 10, bid="105.99", ask="106")
    h, receipts = issue_journal(tmp_path, [p], {f.symbol: f})
    r = runner(tmp_path, [f, high, candle, stopped], h=h, age=60_000)
    ingest(r, 1)
    intake(r, h, receipts["arm", p.template.intent_id])
    r.advance_to(now_ms=ISSUE + 2, event_id="entry")
    initial_risk = account(r).open_risk
    ingest(r, 2)
    assert account(r).positions[0].stop_price == D("98.5")
    ingest(r, 3)
    assert account(r).positions[0].stop_price == D("106") and account(r).open_risk == initial_risk
    ingest(r, 4)
    r.advance_to(now_ms=START + 2 * MINUTE + 12, event_id="exit")
    assert not account(r).positions
    assert r.snapshot().state["parents"][p.template.intent_id]["exit_reason"] == "TRAILING_STOP"
    r.close()


def test_single_advance_merges_first_fill_timeout_before_future_book(tmp_path):
    p, f = parent(holding=100, trailing=False), book(aqty="0.2")
    h, receipts = issue_journal(tmp_path, [p], {f.symbol: f})
    r = runner(tmp_path, [f, book(seq=2, at=ISSUE + 500, bid="102", ask="102.01")], h=h)
    ingest(r, 1)
    intake(r, h, receipts["arm", p.template.intent_id])
    r.advance_to(now_ms=ISSUE + 200, event_id="jump")
    saved = r.snapshot().state["parents"][p.template.intent_id]
    assert saved["exposure"][0][0] == ISSUE + 2 and saved["closed_at"] == ISSUE + 104
    assert saved["exit_reason"] == "TIMEOUT" and saved["outcomes"][-1]["frame_sha256"] == f.fingerprint()
    assert not account(r).positions
    r.close()


@pytest.mark.parametrize("late", [True, False])
def test_funding_due_history_survives_flat_late_cash_or_null_net(tmp_path, late):
    p, f, due = parent(), book(aqty="0.2"), ISSUE + 50
    values = [f, book(seq=2, at=ISSUE + 100, bid="106", ask="106.01")]
    if late:
        values.append(
            FundingInput(
                "BTCUSDT", due, ISSUE + 200, "funding", "TEST_FIXTURE", "SETTLED", D("0.001"), D("101"), SHA
            )
        )
    h, receipts = issue_journal(tmp_path, [p], {f.symbol: f})
    r = runner(tmp_path, values, h=h, due=(("BTCUSDT", due),))
    ingest(r, 1)
    intake(r, h, receipts["arm", p.template.intent_id])
    r.advance_to(now_ms=ISSUE + 2, event_id="entry")
    ingest(r, 2)
    r.advance_to(now_ms=ISSUE + 102, event_id="exit")
    before = account(r).cash
    assert not account(r).positions and r._missing_funding(r.snapshot().state, ISSUE + 102) == [
        f"BTCUSDT:{due}"
    ]
    if late:
        r = reopen(r)
        ingest(r, 3)
        assert account(r).cash == before - D("0.0202")
    else:
        r.debit_service(cost_id="actual-known-service", amount=D("0.01"), at_ms=ISSUE + 103)
    seal_slots(r)
    result = r.finish(now_ms=START + 2 * MINUTE, event_id="finish").outcome
    assert result["status"] == ("COMPLETE" if late else "UNRESOLVED")
    assert (result["net_return"] is None) is (not late)
    r.close()


def test_multi_parent_five_symbol_aggregate_cap_and_matched_arm_isolation(tmp_path):
    plans, frames = [parent(s) for s in UNIVERSE], {s: book(s) for s in UNIVERSE}
    h, receipts = issue_journal(tmp_path, plans, frames, arms=("baseline", "reviewed"))
    runners = [
        runner(tmp_path, list(frames.values()), h=h, arm=arm, fees="0") for arm in ("baseline", "reviewed")
    ]
    for r in runners:
        for seq in range(1, 6):
            ingest(r, seq)
        for p in plans:
            intake(r, h, receipts[r.config["arm"], p.template.intent_id])
        assert account(r).open_risk <= account(r).equity * D("0.01")
        quantities = [x.quantity for x in account(r).reservations]
        assert len(quantities) <= 4 or min(quantities) < max(quantities) / 100
        r.advance_to(now_ms=ISSUE + 2, event_id="all-entries")
        assert 4 <= len(account(r).positions) <= 5 and len(r.snapshot().state["parents"]) == 5
        assert account(r).open_risk <= account(r).equity * D("0.01") and not account(r).barrier
    assert account(runners[0]) == account(runners[1])
    runners[0].debit_service(cost_id="one-arm-only", amount=D("1"), at_ms=ISSUE + 3)
    assert account(runners[0]).cash == account(runners[1]).cash - 1
    for r in runners:
        assert r.finish(now_ms=START + 2 * MINUTE, event_id="finish").outcome["net_return"] is None
        r.close()


def test_missing_quote_first_trigger_is_consumed_without_rescue(tmp_path):
    p, f = parent(), book()
    h, receipts = issue_journal(tmp_path, [p], {f.symbol: f}, missing_quote=True)
    r = runner(tmp_path, [f], h=h)
    ingest(r, 1)
    result = intake(r, h, receipts["arm", p.template.intent_id])
    assert (
        result.outcome["status"] == "REFUSED" and result.outcome["reason"] == "FRESH_ENTRY_QUOTE_UNAVAILABLE"
    )
    assert not account(r).positions and not account(r).reservations
    r = reopen(r)
    assert intake(r, h, receipts["arm", p.template.intent_id]).replayed
    seal_slots(r)
    result = r.finish(now_ms=START + 2 * MINUTE, event_id="finish").outcome
    assert result["status"] == "UNRESOLVED" and result["net_return"] is None
    assert result["unavailable_slots"] == [f"BTCUSDT:{START + MINUTE}"]
    r.close()


def test_full_denominator_clock_and_prefix_are_not_optional(tmp_path):
    r = runner(tmp_path, [book()])
    with pytest.raises(SimInputError, match="bypass"):
        r.advance_to(now_ms=ISSUE, event_id="skip")
    with pytest.raises(SimInputError, match="replay clock"):
        r.ingest(global_sequence=1, now_ms=ISSUE)
    ingest(r, 1)
    with pytest.raises(SimInputError, match="horizon"):
        r.finish(now_ms=ISSUE, event_id="early")
    result = r.finish(now_ms=START + 2 * MINUTE, event_id="finish").outcome
    assert (
        result["status"] == "UNRESOLVED"
        and result["net_return"] is None
        and len(result["missing_slots"]) == 5
    )
    r.close()


def test_gap_never_generates_fill_or_forced_close(tmp_path):
    p, f = parent(), book(aqty="0.2")
    h, receipts = issue_journal(tmp_path, [p], {f.symbol: f})
    r = runner(tmp_path, [f, book(seq=2, at=ISSUE + 100, continuity="GAP")], h=h)
    ingest(r, 1)
    intake(r, h, receipts["arm", p.template.intent_id])
    r.advance_to(now_ms=ISSUE + 2, event_id="entry")
    ingest(r, 2)
    seal_slots(r)
    result = r.finish(now_ms=START + 2 * MINUTE, event_id="finish").outcome
    assert (
        result["status"] == "UNRESOLVED"
        and result["net_return"] is None
        and account(r).positions[0].quantity == D("0.2")
    )
    r.close()


def test_per_symbol_order_and_real_book_membership_are_mandatory():
    f = book()
    later = book("ETHUSDT", at=ISSUE - 7)
    TapeBinding(
        "fixture",
        "fixture-tape",
        "fixture-epoch",
        "quotes",
        "TEST_FIXTURE",
        (TapeInput(1, f), TapeInput(2, later)),
    )
    with pytest.raises(SimInputError, match="per-symbol"):
        TapeBinding(
            "fixture",
            "fixture-tape",
            "fixture-epoch",
            "quotes",
            "TEST_FIXTURE",
            (TapeInput(1, f), TapeInput(2, book(seq=1, at=ISSUE))),
        )
    with pytest.raises(SimInputError, match="public tape"):
        TapeBinding(
            "unproved",
            "fixture-tape",
            "fixture-epoch",
            "quotes",
            "CALLER_ATTESTED_POINT_IN_TIME",
            (TapeInput(1, f),),
        )


def test_target_no_fill_escalates_to_owned_stop_not_target_limit_forever(tmp_path):
    p, f = parent(), book(aqty="0.2")
    target = book(seq=2, at=ISSUE + 100, bid="106", ask="106.01", bqty="0.05")
    stop = book(seq=3, at=ISSUE + 101, bid="98", ask="98.01")
    h, receipts = issue_journal(tmp_path, [p], {f.symbol: f})
    r = runner(tmp_path, [f, target, stop], h=h)
    ingest(r, 1)
    intake(r, h, receipts["arm", p.template.intent_id])
    r.advance_to(now_ms=ISSUE + 2, event_id="entry")
    ingest(r, 2)
    ingest(r, 3)  # STOP precedes target IOC arrival; original IOC is not rewritten
    r.advance_to(now_ms=ISSUE + 110, event_id="protect")
    saved = r.snapshot().state["parents"][p.template.intent_id]
    assert saved["outcomes"][1]["status"] == "NO_FILL"
    assert saved["outcomes"][2]["status"] == "FILLED"
    assert saved["exit_trigger_history"] == [[ISSUE + 100, "TARGET"], [ISSUE + 101, "STOP"]]
    assert saved["exit_reason"] == "STOP" and saved["closed_at"] == ISSUE + 104
    assert not account(r).positions and not account(r).protective_exit_pending
    r.close()


def test_no_fill_is_consumed_and_old_duplicate_survives_later_hypothesis_head(tmp_path):
    p, f = parent(), book()
    later = book(seq=2, at=ISSUE + 2, bid="100.59", ask="100.6")
    h, receipts = issue_journal(tmp_path, [p], {f.symbol: f})
    old_head, receipt = h.snapshot().head_sha256, receipts["arm", p.template.intent_id]
    r = runner(tmp_path, [f, later], h=h)
    ingest(r, 1)
    intake(r, h, receipt)
    ingest(r, 2)  # equality: already durable new source precedes arrival
    saved = r.snapshot().state["parents"][p.template.intent_id]
    assert saved["entry"] == "NO_FILL" and not account(r).positions
    assert saved["outcomes"][0]["frame_sha256"] == later.fingerprint()
    # A later durable observation changes the global producer head, not the first trigger.
    c = bar("BTCUSDT", START + MINUTE)
    h.append(
        "arm",
        p.template.intent_id,
        HypothesisObservation(ScenarioObservation(c, START + 2 * MINUTE + 20, (evidence(c),)), None),
    )
    version = r.snapshot().version
    assert r.intake(
        hypothesis_journal=h, receipt=receipt, expected_hypothesis_head_sha256=old_head, at_ms=ISSUE
    ).replayed
    assert r.snapshot().version == version and not account(r).positions
    r.close()


def test_missing_held_trailing_bar_keeps_flat_net_unknown(tmp_path):
    p, f = parent(), book(aqty="0.2")
    close = book(seq=2, at=START + 2 * MINUTE + 10, bid="106", ask="106.01")
    h, receipts = issue_journal(tmp_path, [p], {f.symbol: f})
    r = runner(tmp_path, [f, close], h=h, age=60_000)
    ingest(r, 1)
    intake(r, h, receipts["arm", p.template.intent_id])
    r.advance_to(now_ms=ISSUE + 2, event_id="entry")
    ingest(r, 2)
    r.advance_to(now_ms=START + 2 * MINUTE + 12, event_id="exit")
    assert not account(r).positions
    seal_slots(r, START + 2 * MINUTE + 12)
    result = r.finish(now_ms=START + 2 * MINUTE + 12, event_id="finish").outcome
    assert result["net_return"] is None and result["missing_protection_bars"] == [f"BTCUSDT:{START + MINUTE}"]
    r.close()


def test_unavailable_funding_can_be_settled_late_once_and_no_double_cash(tmp_path):
    p, f, due = parent(), book(aqty="0.2"), ISSUE + 50
    unknown = FundingInput("BTCUSDT", due, due, "funding", "TEST_FIXTURE", "UNAVAILABLE", None, None, SHA)
    close = book(seq=2, at=ISSUE + 100, bid="106", ask="106.01")
    actual = FundingInput(
        "BTCUSDT", due, ISSUE + 200, "funding", "TEST_FIXTURE", "SETTLED", D("0.001"), D("101"), SHA
    )
    h, receipts = issue_journal(tmp_path, [p], {f.symbol: f})
    r = runner(tmp_path, [f, unknown, close, actual], h=h, due=(("BTCUSDT", due),))
    ingest(r, 1)
    intake(r, h, receipts["arm", p.template.intent_id])
    r.advance_to(now_ms=ISSUE + 2, event_id="entry")
    ingest(r, 2)
    ingest(r, 3)
    r.advance_to(now_ms=ISSUE + 102, event_id="exit")
    before = account(r).cash
    ingest(r, 4)
    assert account(r).cash == before - D("0.0202")
    assert ingest(r, 4).replayed and account(r).cash == before - D("0.0202")
    assert len(r.snapshot().state["funding"][f"BTCUSDT:{due}"]["earlier_unavailable_receipts"]) == 1
    r.close()


def test_runtime_configuration_cannot_change_under_a_sealed_account(tmp_path):
    r = runner(tmp_path, [book()])
    r.config["maximum_exit_attempts"] = 8
    with pytest.raises(SimInputError, match="configuration drift"):
        ingest(r, 1)
    assert r.snapshot().version == 0
    r.close()


def test_next_fresh_hypothesis_reuses_account_and_session_depth_not_new_session(tmp_path):
    first, f = parent(), book(aqty="0.2")
    second_issue = START + 2 * MINUTE + 20
    second = parent(label="next-minute-parent", created=START + MINUTE)
    exit_one = book(seq=2, at=ISSUE + 100, bid="106", ask="106.01")
    next_quote = book(seq=3, at=second_issue - 8, aqty="0.3")
    exit_two = book(seq=4, at=second_issue + 100, bid="106", ask="106.01")
    h, receipts = issue_journal(tmp_path, [first], {f.symbol: f})
    r = runner(
        tmp_path, [f, exit_one, next_quote, exit_two], h=h, minutes=(START + MINUTE, START + 2 * MINUTE)
    )
    ingest(r, 1)
    intake(r, h, receipts["arm", first.template.intent_id])
    r.advance_to(now_ms=ISSUE + 2, event_id="entry-one")
    ingest(r, 2)
    r.advance_to(now_ms=ISSUE + 102, event_id="exit-one")
    first_cash = account(r).cash
    r = reopen(r)
    ingest(r, 3)
    h.register("arm", second)
    c = bar("BTCUSDT", START + MINUTE)
    q = EntryQuote(
        "quotes",
        "BTCUSDT",
        100.49,
        100.5,
        next_quote.exchange_at_ms,
        next_quote.received_at_ms,
        next_quote.persisted_at_ms,
        5000,
        "TEST_FIXTURE",
    )
    receipt = h.append(
        "arm",
        second.template.intent_id,
        HypothesisObservation(ScenarioObservation(c, second_issue, (evidence(c),)), q),
    )
    assert receipt.evaluation.candidate is not None
    r.intake(
        hypothesis_journal=h,
        receipt=receipt,
        expected_hypothesis_head_sha256=h.snapshot().head_sha256,
        at_ms=second_issue,
    )
    r.advance_to(now_ms=second_issue + 2, event_id="entry-two")
    assert account(r).positions[0].quantity == D("0.1")  # .2 already debited at ask100.5
    assert account(r).cash == first_cash - D("0.01005")
    assert len(account(r).reservations) == 2 and len(r.snapshot().state["parents"]) == 2
    ingest(r, 4)
    r.advance_to(now_ms=second_issue + 102, event_id="exit-two")
    seal_slots(r, START + 3 * MINUTE)
    result = r.finish(now_ms=START + 3 * MINUTE, event_id="finish").outcome
    assert result["status"] == "COMPLETE" and result["natural_closes"] == 2
    assert len(r.snapshot().state["slots"]) == 10
    assert account(r).cash > D("1000")
    r.close()


def test_all_declared_unavailable_cells_never_qualify_zero_return(tmp_path):
    r = runner(tmp_path, [book()])
    ingest(r, 1)
    for s in UNIVERSE:
        r.record_slot(
            symbol=s, minute=START + MINUTE, status="UNAVAILABLE", source_sha256=SHA, at_ms=START + 2 * MINUTE
        )
    result = r.finish(now_ms=START + 2 * MINUTE, event_id="finish").outcome
    assert result["status"] == "UNRESOLVED" and result["net_return"] is None
    assert not result["missing_slots"] and len(result["unavailable_slots"]) == 5
    assert result["denominator_cells"] == 5 and result["qualified_economics"] is None
    assert r.snapshot().state["last_outcome"] == result
    r.close()


def test_unavailable_cell_keeps_naturally_flat_return_unknown(tmp_path):
    p, f = parent(), book(aqty="0.2")
    h, receipts = issue_journal(tmp_path, [p], {f.symbol: f})
    r = runner(tmp_path, [f, book(seq=2, at=ISSUE + 100, bid="106", ask="106.01")], h=h)
    ingest(r, 1)
    intake(r, h, receipts["arm", p.template.intent_id])
    r.advance_to(now_ms=ISSUE + 2, event_id="entry")
    ingest(r, 2)
    r.advance_to(now_ms=ISSUE + 102, event_id="exit")
    r.record_slot(
        symbol="ETHUSDT",
        minute=START + MINUTE,
        status="UNAVAILABLE",
        source_sha256=SHA,
        at_ms=START + 2 * MINUTE,
    )
    seal_slots(r)
    result = r.finish(now_ms=START + 2 * MINUTE, event_id="finish").outcome
    assert result["status"] == "UNRESOLVED" and result["net_return"] is None
    assert not account(r).positions and result["natural_closes"] == 1
    assert result["unavailable_slots"] == [f"ETHUSDT:{START + MINUTE}"]
    r.close()


def test_stop_breached_on_entry_frame_is_protected_without_waiting_for_new_book(tmp_path):
    p, f = parent(), book()
    already_breached = book(seq=2, at=ISSUE + 2, bid="98.49", ask="98.5", aqty="0.2")
    h, receipts = issue_journal(tmp_path, [p], {f.symbol: f})
    r = runner(tmp_path, [f, already_breached], h=h)
    ingest(r, 1)
    intake(r, h, receipts["arm", p.template.intent_id])
    ingest(r, 2)
    assert account(r).positions and account(r).protective_exit_pending
    r.advance_to(now_ms=ISSUE + 4, event_id="birth-stop-exit")
    saved = r.snapshot().state["parents"][p.template.intent_id]
    assert saved["exit_reason"] == "STOP" and saved["closed_at"] == ISSUE + 4
    assert saved["outcomes"][-1]["frame_sha256"] == already_breached.fingerprint()
    assert not account(r).positions and not account(r).protective_exit_pending
    r.close()
