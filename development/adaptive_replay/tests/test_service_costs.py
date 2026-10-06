from types import SimpleNamespace

import pytest
from kairos_core.enums import Side
from kairos_strategy.adaptive.config import UNIVERSE
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent

from adaptive_replay.engine import AccountCost, CostScenario, replay_tape

START = 86_400_000
ZERO = CostScenario("zero", 0, 0, 0, 0, 0, 0)


def _bar(symbol, ts, price=100):
    return Candle(symbol, "1m", ts, ts + 59_999, price, price + 0.1, price - 0.1, price, 1000)


def _intent(symbol, ts, tag="one"):
    return SleeveIntent(
        "adaptive_pullback_range_v1",
        symbol,
        Side.LONG,
        ts - 1,
        ts,
        ts + 59_999,
        100,
        1,
        200,
        ExitPlan(99, 102, 120_000),
        (("frozen_atr15", "1"), ("regime", "BULL"), ("tag", tag)),
    )


def _inputs(end=START + 5 * 60_000):
    replay_end = end + 3 * 3_600_000
    bars = {s: tuple(_bar(s, ts) for ts in range(START, replay_end, 60_000)) for s in UNIVERSE}
    return SimpleNamespace(
        start_ms=START, end_ms=end, data_end_ms=replay_end, bars=bars, funding={s: () for s in UNIVERSE}
    )


def test_no_trade_error_and_late_attempts_still_debit_account():
    inputs = _inputs()
    costs = tuple(AccountCost(f"cost-{i}", START + i * 60_000, 0.1, "MODEL") for i in range(3))
    report, account = replay_tape(inputs, {}, ZERO, "INTRABAR_OPEN_PROXY", 0, service_costs=costs)
    assert report["closed_trades"] == 0
    assert report["recorded_service_cost_usd"] == pytest.approx(0.3)
    assert report["ledger_reconciliation_error_usd"] == pytest.approx(0, abs=2e-12)
    assert report["model_calls"] == 3
    assert account.cash == pytest.approx(9_999.7)


def test_same_time_costs_across_symbols_debited_before_all_sizing():
    inputs = _inputs()
    ts = START
    costs = (AccountCost("z", ts, 10, "MODEL"), AccountCost("a", ts, 20, "MODEL"))
    tape = {ts: [_intent(s, ts, s) for s in reversed(UNIVERSE)]}
    _, account = replay_tape(inputs, tape, ZERO, "INTRABAR_OPEN_PROXY", 0, service_costs=costs)
    entries = [e for e in account.events if e["kind"] == "ENTRY"]
    assert [e["symbol"] for e in entries] == list(UNIVERSE[:4])
    assert len(entries) == 4
    assert all(e["post_entry_equity_usd"] <= 9_970 for e in entries)
    first_entry = next(i for i, event in enumerate(account.events) if event["kind"] == "ENTRY")
    debit_events = [i for i, event in enumerate(account.events) if "cost_id" in event]
    assert debit_events and max(debit_events) < first_entry
    assert account.report({s: 100 for s in UNIVERSE}, ["1970-01-02"])[
        "ledger_reconciliation_error_usd"
    ] == pytest.approx(0, abs=2e-12)


def test_tail_cost_is_kept_but_outside_horizon_refused():
    inputs = _inputs()
    tail = inputs.end_ms + 3 * 3_600_000 - 1
    report, account = replay_tape(
        inputs,
        {},
        ZERO,
        "INTRABAR_OPEN_PROXY",
        0,
        service_costs=(AccountCost("tail", tail, 0.25, "FEED"),),
    )
    assert report["recorded_service_cost_usd"] == pytest.approx(0.25)
    assert account.cash == pytest.approx(9_999.75)
    with pytest.raises(ValueError, match="outside replay horizon"):
        replay_tape(
            inputs,
            {},
            ZERO,
            "INTRABAR_OPEN_PROXY",
            0,
            service_costs=(AccountCost("outside", tail + 1, 0.25, "FEED"),),
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: (AccountCost("same", START, 0.1, "MODEL"), AccountCost("same", START + 1, 0.2, "MODEL")),
        lambda: (AccountCost("bad", START, float("nan"), "MODEL"),),
        lambda: (AccountCost("bool", START, True, "MODEL"),),
    ],
)
def test_duplicate_bool_and_nonfinite_costs_refused(factory):
    with pytest.raises((ValueError, TypeError)):
        replay_tape(_inputs(), {}, ZERO, "INTRABAR_OPEN_PROXY", 0, service_costs=factory())


def test_default_replay_output_stays_equal_with_explicit_equivalent_completion():
    inputs = _inputs()
    value = _intent("BTCUSDT", START)
    default_report, default_account = replay_tape(inputs, {START: [value]}, ZERO, "INTRABAR_OPEN_PROXY", 100)
    explicit_report, explicit_account = replay_tape(
        inputs,
        {START: [value]},
        ZERO,
        "INTRABAR_OPEN_PROXY",
        100,
        completion_times_ms={value.intent_id: value.decision_ts_ms + 100},
    )
    assert default_report == explicit_report
    assert default_account.events == explicit_account.events
    assert default_account.trades == explicit_account.trades


def test_same_clock_costs_are_not_order_dependent():
    inputs = _inputs()
    ts = START
    intents = [_intent(s, ts, s) for s in UNIVERSE]
    debits = (AccountCost("b", ts + 1, 3, "MODEL"), AccountCost("a", ts + 1, 7, "FEED"))
    reports = [
        replay_tape(inputs, {ts: intents}, ZERO, "INTRABAR_OPEN_PROXY", 0, service_costs=order)[0]
        for order in (debits, tuple(reversed(debits)))
    ]
    assert reports[0] == reports[1]
