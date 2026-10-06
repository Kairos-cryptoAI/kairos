from dataclasses import replace

import pytest
from kairos_core.enums import Side
from kairos_strategy.models import ExitPlan

from adaptive_replay.engine import COMMON_COST_RISK, Portfolio, replay_tape

from .test_engine import FREE, START, bar, inputs_fixture, intent, opens


def native(side=Side.LONG, holding=120_000):
    value = intent(side=side, holding=holding)
    return replace(value, sleeve_id="trend_breakout_v1", metadata=(), entry_expires_ts_ms=START + 299_999)


def test_common_admission_does_not_require_adaptive_atr_metadata():
    old = Portfolio(10_000, FREE, "INTRABAR_OPEN_PROXY")
    assert not old.admit(native(), START + 99, bar(), opens())
    assert old.rejections["STRUCTURAL_ATR_UNAVAILABLE"] == 1
    common = Portfolio(10_000, FREE, "INTRABAR_OPEN_PROXY", COMMON_COST_RISK)
    assert common.admit(native(), START + 99, bar(), opens())
    assert common.positions["BTCUSDT"].reserved_risk <= 25


def test_unknown_admission_policy_cannot_silently_weaken_risk():
    with pytest.raises(ValueError, match="admission"):
        Portfolio(10_000, FREE, "INTRABAR_OPEN_PROXY", "NO_RISK")


def test_strict_fill_waits_for_actual_next_minute_quote_without_backdating():
    inputs = inputs_fixture()
    inputs.end_ms = START + 180_000
    inputs.bars = {
        symbol: tuple(
            bar(symbol, row.open_time_ms, open_=100.2, high=100.3, low=100.1, close=100.2)
            if row.open_time_ms == START + 60_000
            else row
            for row in rows
        )
        for symbol, rows in inputs.bars.items()
    }
    inputs.funding["BTCUSDT"] = (type("Funding", (), {"timestamp_ms": START + 60_005, "rate": 0.001})(),)
    report, account = replay_tape(
        inputs, {START: [native()]}, FREE, "STRICT_MINUTE_OPEN", 100, admission_policy=COMMON_COST_RISK
    )
    entry = next(event for event in account.events if event["kind"] == "ENTRY")
    assert entry["timestamp_ms"] == START + 60_000
    assert entry["price"] == 100.2
    assert report["closed_trades"] == 1
    assert account.trades[0]["entry_ms"] == START + 60_000
    assert account.trades[0]["signed_funding_cost_usd"] > 0
    assert "FILL_BAR_UNAVAILABLE" not in report["admission_rejections"]


def test_adaptive_native_expiry_remains_no_fill_in_strict_mode():
    inputs = inputs_fixture()
    report, account = replay_tape(
        inputs, {START: [intent()]}, FREE, "STRICT_MINUTE_OPEN", 100, admission_policy=COMMON_COST_RISK
    )
    assert not account.trades and not account.positions
    assert report["admission_rejections"] == {"NO_OBSERVED_MINUTE_QUOTE_WITHIN_LIFETIME": 1}


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_trailing_close_update_never_hits_retroactively_or_releases_reserved_risk(side):
    sign = 1 if side is Side.LONG else -1
    value = native(side=side, holding=600_000)
    value = replace(value, exit_plan=ExitPlan(100 - sign, 100 + 2 * sign, 600_000, 100 + sign, 0.5))
    account = Portfolio(10_000, FREE, "INTRABAR_OPEN_PROXY", COMMON_COST_RISK)
    assert account.admit(value, START + 99, bar(), opens())
    before = account.positions["BTCUSDT"].reserved_risk
    row = bar(
        ts=START + 60_000,
        high=101.5 if sign == 1 else 100.1,
        low=99.9 if sign == 1 else 98.5,
        close=100 + 1.2 * sign,
    )
    account.exit_intrabar(row)
    assert account.positions and not account.trades
    account.update_trailing_at_close(row)
    position = account.positions["BTCUSDT"]
    assert position.stop == pytest.approx(100 + 0.7 * sign)
    assert position.reserved_risk == before
    assert account.events[-1]["risk_reservation_released_usd"] == 0
    assert not account.trades  # Earlier low/high on the same candle cannot hit the new stop.
    next_row = bar(
        ts=START + 120_000,
        open_=100 + 0.6 * sign,
        high=100 + 0.6 * sign,
        low=100 + 0.6 * sign,
        close=100 + 0.6 * sign,
    )
    account.exit_at_open(next_row)
    assert account.trades[0]["reason"] == "TRAILING_STOP"
    assert account.trades[0]["gap"] is True
    assert account.trades[0]["exit_price"] == 100 + 0.6 * sign


def test_trailing_activation_is_sticky_and_stop_cannot_loosen():
    value = replace(native(holding=600_000), exit_plan=ExitPlan(99, 102, 600_000, 101, 0.5))
    account = Portfolio(10_000, FREE, "INTRABAR_OPEN_PROXY", COMMON_COST_RISK)
    assert account.admit(value, START + 99, bar(), opens())
    account.update_trailing_at_close(bar(ts=START + 60_000, close=101.5, high=101.5))
    account.update_trailing_at_close(bar(ts=START + 120_000, close=101.1, high=101.5))
    assert account.positions["BTCUSDT"].trailing_activated
    assert account.positions["BTCUSDT"].stop == 101


def test_comparison_account_and_ledgers_are_independent():
    inputs = inputs_fixture()
    tape = {START: [native()]}
    report_a, account_a = replay_tape(
        inputs, tape, FREE, "INTRABAR_OPEN_PROXY", 100, admission_policy=COMMON_COST_RISK
    )
    report_b, account_b = replay_tape(
        inputs, tape, FREE, "INTRABAR_OPEN_PROXY", 100, admission_policy=COMMON_COST_RISK
    )
    assert report_a == report_b
    assert account_a.events == account_b.events
    assert account_a is not account_b and account_a.positions is not account_b.positions


def test_expired_wall_deadline_fails_closed():
    with pytest.raises(TimeoutError):
        replay_tape(inputs_fixture(), {}, FREE, "STRICT_MINUTE_OPEN", 100, deadline=0)
