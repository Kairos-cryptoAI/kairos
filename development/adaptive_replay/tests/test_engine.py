from dataclasses import replace
from types import SimpleNamespace

import pytest
from kairos_core.enums import Side
from kairos_strategy.adaptive.config import UNIVERSE
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent

from adaptive_replay.engine import CostScenario, Portfolio, entry_time, fill_price, replay_tape

BASE = CostScenario("base", 4.5, 2, 1, 2, 2, 3)
FREE = CostScenario("zero_cost_fixture", 0, 0, 0, 0, 0, 0)
START = 86_400_000


def bar(symbol="BTCUSDT", ts=START, open_=100.0, high=100.1, low=99.9, close=100.0):
    return Candle(symbol, "1m", ts, ts + 59_999, open_, high, low, close, 1000)


def intent(symbol="BTCUSDT", side=Side.LONG, ts=START, risk=1.0, atr=1.0, holding=120_000):
    sign = 1 if side is Side.LONG else -1
    return SleeveIntent(
        "adaptive_pullback_range_v1",
        symbol,
        side,
        ts - 1,
        ts,
        ts + 59_999,
        100.0,
        1.0,
        risk * 2 / 100 * 10_000,
        ExitPlan(100 - sign * risk, 100 + sign * risk * 2, holding),
        (("frozen_atr15", str(atr)), ("regime", "BULL" if sign == 1 else "BEAR")),
    )


def opens(value=100.0):
    return {s: value for s in UNIVERSE}


@pytest.mark.parametrize("latency,expected", [(0, START), (1, START), (2, None), (100, None)])
def test_exact_strict_entry_clock(latency, expected):
    value = intent()
    assert entry_time(value, value.decision_ts_ms + latency, "STRICT_MINUTE_OPEN") == expected


@pytest.mark.parametrize(
    "offset,expected", [(59_998, START + 59_998), (59_999, START + 59_999), (60_000, None)]
)
def test_proxy_never_extends_lifetime(offset, expected):
    assert entry_time(intent(), START + offset, "INTRABAR_OPEN_PROXY") == expected


def test_completion_not_backdated():
    with pytest.raises(ValueError, match="precede"):
        entry_time(intent(), START - 2, "INTRABAR_OPEN_PROXY")


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_fill_priced_sizing_includes_post_entry_debits(side):
    p = Portfolio(10_000, BASE, "INTRABAR_OPEN_PROXY")
    assert p.admit(intent(side=side), START + 99, bar(), opens())
    position = p.positions["BTCUSDT"]
    post = p.equity(opens())
    assert position.reserved_risk <= post * 0.0025 + 1e-9
    assert position.quantity * max(position.entry_price, 100) <= post * 0.25 + 1e-9


def test_fifth_risk_reservation_rejected_without_long_short_netting():
    p = Portfolio(10_000, FREE, "INTRABAR_OPEN_PROXY")
    for idx, symbol in enumerate(UNIVERSE[:4]):
        side = Side.LONG if idx % 2 else Side.SHORT
        assert p.admit(intent(symbol, side), START + 99, bar(symbol), opens())
    assert sum(v.reserved_risk for v in p.positions.values()) == pytest.approx(100)
    assert not p.admit(intent(UNIVERSE[4]), START + 99, bar(UNIVERSE[4]), opens())
    assert p.rejections["AGGREGATE_OPEN_RISK_CAP"] == 1


def test_no_intrabar_cash_or_risk_release_before_new_entries():
    p = Portfolio(10_000, FREE, "INTRABAR_OPEN_PROXY")
    for symbol in UNIVERSE[:4]:
        assert p.admit(intent(symbol), START + 99, bar(symbol), opens())
    b = bar(UNIVERSE[0], START + 60_000, high=103)
    p.exit_at_open(b)
    assert len(p.positions) == 4
    assert not p.admit(
        intent(UNIVERSE[4], ts=START + 60_000), START + 60_099, bar(UNIVERSE[4], START + 60_000), opens()
    )
    p.exit_intrabar(b)
    assert len(p.positions) == 3


@pytest.mark.parametrize("side,gap,expected", [(Side.LONG, 90, 90), (Side.SHORT, 110, 110)])
def test_gap_stop_preserves_loss_beyond_stop(side, gap, expected):
    p = Portfolio(10_000, BASE, "INTRABAR_OPEN_PROXY")
    assert p.admit(intent(side=side), START + 99, bar(), opens())
    p.exit_at_open(bar(ts=START + 60_000, open_=gap, high=gap, low=gap, close=gap))
    assert p.trades[0]["exit_price"] == pytest.approx(fill_price(expected, side, False, BASE))
    assert p.trades[0]["realized_loss_exceeds_reservation"]


@pytest.mark.parametrize("side,gap", [(Side.LONG, 110), (Side.SHORT, 90)])
def test_gap_target_no_favorable_improvement(side, gap):
    p = Portfolio(10_000, BASE, "INTRABAR_OPEN_PROXY")
    value = intent(side=side)
    assert p.admit(value, START + 99, bar(), opens())
    p.exit_at_open(bar(ts=START + 60_000, open_=gap, high=gap, low=gap, close=gap))
    assert p.trades[0]["exit_price"] == pytest.approx(
        fill_price(value.exit_plan.target_price, side, False, BASE)
    )


def test_changed_fill_geometry_rejected_without_moving_stop():
    p = Portfolio(10_000, BASE, "INTRABAR_OPEN_PROXY")
    assert not p.admit(intent(), START + 99, bar(open_=101, high=101, low=101, close=101), opens(101))
    assert not p.positions


def test_entry_minute_both_barriers_stop_first():
    p = Portfolio(10_000, BASE, "INTRABAR_OPEN_PROXY")
    assert p.admit(intent(), START + 99, bar(), opens())
    p.exit_intrabar(bar(high=103, low=98))
    assert p.trades[0]["reason"] == "SL"
    assert p.intrabar_ambiguities == 1


def test_entry_minute_target_only_is_not_credited():
    p = Portfolio(10_000, BASE, "INTRABAR_OPEN_PROXY")
    assert p.admit(intent(), START + 99, bar(), opens())
    p.exit_intrabar(bar(high=103))
    assert p.positions and not p.trades
    assert p.suppressed_entry_minute_targets == 1


def test_timeout_uses_first_fill_clock_and_conservative_deadline_proxy():
    p = Portfolio(10_000, FREE, "INTRABAR_OPEN_PROXY")
    assert p.admit(intent(holding=60_000), START + 99, bar(), opens())
    p.exit_intrabar(bar(ts=START + 60_000, high=103))
    assert p.trades[0]["exit_ms"] == START + 60_099
    assert p.trades[0]["reason"] == "TIMEOUT"
    assert p.suppressed_deadline_minute_targets == 1


@pytest.mark.parametrize(
    "side,rate,sign",
    [(Side.LONG, 0.001, 1), (Side.SHORT, 0.001, -1), (Side.LONG, -0.001, -1), (Side.SHORT, -0.001, 1)],
)
def test_signed_native_funding_and_cash_identity(side, rate, sign):
    p = Portfolio(10_000, FREE, "INTRABAR_OPEN_PROXY")
    assert p.admit(intent(side=side), START + 99, bar(), opens())
    quantity = p.positions["BTCUSDT"].quantity
    p.settle("BTCUSDT", START + 60_000, rate, 100)
    assert 10_000 - p.cash == pytest.approx(sign * quantity * 100 * abs(rate))
    report = p.report(opens(), ["1970-01-02"])
    assert report["ledger_reconciliation_error_usd"] == pytest.approx(0)
    assert len(report["terminal_unresolved_positions"]) == 1
    p.exit_intrabar(bar(ts=START + 120_000))
    assert p.report(opens(), ["1970-01-02"])["ledger_reconciliation_error_usd"] == pytest.approx(0)


def test_uncertainty_and_planning_carry_not_double_cash_charged():
    p = Portfolio(10_000, BASE, "INTRABAR_OPEN_PROXY")
    assert p.admit(intent(holding=60_000), START + 99, bar(), opens())
    p.exit_intrabar(bar(ts=START + 60_000))
    t = p.trades[0]
    assert t["net_pnl_usd"] == pytest.approx(t["gross_pnl_usd"] - t["entry_fee_usd"] - t["exit_fee_usd"])
    assert BASE.costs.estimated_round_trip_bps == 20


def test_duplicate_deliveries_do_not_make_second_entry():
    p = Portfolio(10_000, BASE, "INTRABAR_OPEN_PROXY")
    value = intent()
    assert p.admit(value, START + 99, bar(), opens())
    assert not p.admit(value, START + 99, bar(), opens())
    assert p.rejections["DUPLICATE_INTENT"] == 1


def test_no_trades_distinct_from_zero_pnl_completed_trades():
    p = Portfolio(10_000, FREE, "INTRABAR_OPEN_PROXY")
    assert p.report(opens(), ["1970-01-02"])["profit_factor_status"] == "NO_TRADES"
    assert p.admit(intent(holding=60_000), START + 99, bar(), opens())
    p.exit_intrabar(bar(ts=START + 60_000))
    assert p.report(opens(), ["1970-01-02"])["profit_factor_status"] == "ZERO_PNL_TRADES"


def inputs_fixture():
    return SimpleNamespace(
        start_ms=START,
        end_ms=START + 60_000,
        data_start_ms=START,
        data_end_ms=START + 86_400_000,
        bars={s: tuple(bar(s, ts) for ts in range(START, START + 86_400_000, 60_000)) for s in UNIVERSE},
        funding={s: () for s in UNIVERSE},
    )


def test_three_hour_tail_never_replays_padded_extra_days_or_tail_entries():
    inputs = inputs_fixture()
    late = START + 60_000
    # Engine fixtures may use holding beyond strategy; terminal exposure remains
    # visible. No forced liquidation or candidate generation in the exit tail.
    value = intent(holding=8 * 3_600_000)
    report, account = replay_tape(
        inputs, {START: [value], late: [intent("ETHUSDT", ts=late)]}, FREE, "INTRABAR_OPEN_PROXY", 100
    )
    assert report["closed_trades"] == 0
    assert len(report["terminal_unresolved_positions"]) == 1
    assert list(account.positions) == ["BTCUSDT"]
    assert report["forced_settlements"] == 0


def test_same_open_funding_before_exit_but_new_entry_not_charged():
    inputs = inputs_fixture()
    ts = START + 60_000
    inputs.funding["BTCUSDT"] = (SimpleNamespace(timestamp_ms=ts, rate=0.001),)
    # Exact open timeout and new same-open funding event for another symbol.
    inputs.funding["ETHUSDT"] = (SimpleNamespace(timestamp_ms=ts, rate=0.001),)
    inputs.end_ms = START + 120_000
    value = intent(holding=60_000)
    # zero latency fixture enters eligible minute open; deadline exactly next open
    _, account = replay_tape(
        inputs, {START: [value], ts: [intent("ETHUSDT", ts=ts)]}, FREE, "INTRABAR_OPEN_PROXY", 0
    )
    first = next(t for t in account.trades if t["symbol"] == "BTCUSDT")
    second = next(t for t in account.trades if t["symbol"] == "ETHUSDT")
    assert first["signed_funding_cost_usd"] > 0
    assert second["signed_funding_cost_usd"] == 0


@pytest.mark.parametrize("offset,charged", [(1, False), (18, False), (99, False), (100, True)])
def test_native_funding_timestamp_merged_against_99ms_entry(offset, charged):
    inputs = inputs_fixture()
    inputs.funding["BTCUSDT"] = (SimpleNamespace(timestamp_ms=START + offset, rate=0.001),)
    _, account = replay_tape(inputs, {START: [intent()]}, FREE, "INTRABAR_OPEN_PROXY", 100)
    assert (account.trades[0]["signed_funding_cost_usd"] > 0) is charged
    funding_events = [e for e in account.events if e["kind"] == "FUNDING"]
    if charged:
        assert funding_events[0]["timestamp_ms"] == START + offset
        assert funding_events[0]["clock_authority"] == "ARCHIVE_CALC_TIME_ENTITLEMENT_PROXY"
    else:
        assert not funding_events


@pytest.mark.parametrize("offset,charged", [(18, True), (99, True), (100, False)])
def test_native_funding_at_deadline_and_one_ms_after(offset, charged):
    inputs = inputs_fixture()
    inputs.funding["BTCUSDT"] = (SimpleNamespace(timestamp_ms=START + 60_000 + offset, rate=0.001),)
    _, account = replay_tape(inputs, {START: [intent(holding=60_000)]}, FREE, "INTRABAR_OPEN_PROXY", 100)
    trade = account.trades[0]
    assert trade["exit_ms"] == START + 60_099
    assert trade["reason"] == "TIMEOUT"
    assert (trade["signed_funding_cost_usd"] > 0) is charged


def test_gap_open_exit_never_charged_later_native_funding():
    inputs = inputs_fixture()
    ts = START + 60_000
    rows = list(inputs.bars["BTCUSDT"])
    rows[1] = bar(ts=ts, open_=90, high=90, low=90, close=90)
    inputs.bars["BTCUSDT"] = tuple(rows)
    inputs.funding["BTCUSDT"] = (SimpleNamespace(timestamp_ms=ts + 18, rate=0.001),)
    _, account = replay_tape(inputs, {START: [intent()]}, FREE, "INTRABAR_OPEN_PROXY", 100)
    assert account.trades[0]["gap"] is True
    assert account.trades[0]["exit_ms"] == ts
    assert account.trades[0]["signed_funding_cost_usd"] == 0


def test_intraminute_timeout_before_native_funding_skips_later_charge():
    inputs = inputs_fixture()
    inputs.funding["BTCUSDT"] = (SimpleNamespace(timestamp_ms=START + 60_018, rate=0.001),)
    _, account = replay_tape(inputs, {START: [intent(holding=59_911)]}, FREE, "INTRABAR_OPEN_PROXY", 100)
    assert account.trades[0]["exit_ms"] == START + 60_010
    assert account.trades[0]["signed_funding_cost_usd"] == 0


def test_marks_include_current_open_peak_before_adverse_envelope():
    p = Portfolio(10_000, FREE, "INTRABAR_OPEN_PROXY")
    assert p.admit(intent(risk=2, atr=2), START + 99, bar(), opens())
    current = {s: bar(s, START + 60_000, open_=101, high=101.1, low=100, close=100) for s in UNIVERSE}
    p.mark(opens(101))
    p.adverse_envelope(current)
    assert p.peak > 10_000
    assert p.max_adverse_envelope_drawdown > 0


def test_reordered_input_same_fixed_symbol_priority_and_independent_arm():
    inputs = inputs_fixture()
    values = [intent(s, risk=1) for s in UNIVERSE]
    a, pa = replay_tape(inputs, {START: values}, FREE, "INTRABAR_OPEN_PROXY", 100)
    b, pb = replay_tape(inputs, {START: list(reversed(values))}, FREE, "INTRABAR_OPEN_PROXY", 100)
    assert a == b and pa.trades == pb.trades and pa.events == pb.events
    replay_tape(inputs, {START: []}, FREE, "INTRABAR_OPEN_PROXY", 100)
    c, pc = replay_tape(inputs, {START: values}, FREE, "INTRABAR_OPEN_PROXY", 100)
    assert a == c and pa.events == pc.events


def test_invalid_fill_mode_and_backdated_fill_refused():
    with pytest.raises(ValueError):
        Portfolio(10_000, BASE, "INVENTED")
    with pytest.raises(ValueError):
        entry_time(intent(), START + 100, "INVENTED")
    with pytest.raises(ValueError):
        CostScenario("bad", float("nan"), 2, 1, 2, 2, 3)


def test_invalid_atr_is_not_complete_no_trade_state():
    p = Portfolio(10_000, BASE, "INTRABAR_OPEN_PROXY")
    bad = replace(intent(), metadata=(("frozen_atr15", "nan"),))
    assert not p.admit(bad, START + 99, bar(), opens())
    assert p.rejections["STRUCTURAL_ATR_UNAVAILABLE"] == 1


def test_future_funding_does_not_change_initial_admission_or_quantity():
    inputs = inputs_fixture()
    future = START + 60_000
    inputs.funding["BTCUSDT"] = (SimpleNamespace(timestamp_ms=future, rate=0.02),)
    _, costly = replay_tape(inputs, {START: [intent()]}, BASE, "INTRABAR_OPEN_PROXY", 100)
    inputs.funding["BTCUSDT"] = (SimpleNamespace(timestamp_ms=future, rate=-0.02),)
    _, credit = replay_tape(inputs, {START: [intent()]}, BASE, "INTRABAR_OPEN_PROXY", 100)
    first_a = next(e for e in costly.events if e["kind"] == "ENTRY")
    first_b = next(e for e in credit.events if e["kind"] == "ENTRY")
    assert first_a == first_b
    assert costly.trades[0]["signed_funding_cost_usd"] > 0
    assert credit.trades[0]["signed_funding_cost_usd"] < 0
