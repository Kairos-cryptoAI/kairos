from decimal import Decimal as D

import pytest

from adaptive_replay.adaptive_sim_account import (
    AccountPolicy,
    mark_account,
    new_account,
    record_entry_fill,
    record_exit_fill,
    record_funding,
    request_protective_exit,
    reserve_entry,
    resolve_entry,
    set_barrier,
    tighten_stop,
)

POLICY = AccountPolicy(D("0.1"), D("0"), D("0"), D("0"), 1_000)


def account():
    result = new_account(D("10000"), POLICY)
    return mark_account(result, mark_id="mark-0", marks=(("BTCUSDT", D("100"), 10),), as_of_ms=10)[0]


def reserve(
    a,
    *,
    symbol="BTCUSDT",
    side="LONG",
    rid="r1",
    stop=None,
    entry=None,
    notional=None,
    as_of=20,
    expiry=500,
):
    return reserve_entry(
        a,
        reservation_id=rid,
        intent_id=f"i-{rid}",
        symbol=symbol,
        side=side,
        stop_price=stop or (D("90") if side == "LONG" else D("110")),
        worst_entry_price=entry or D("100"),
        worst_notional_price=notional or D("100"),
        as_of_ms=as_of,
        expires_at_ms=expiry,
    )


@pytest.mark.parametrize("side,stop", [("LONG", "90"), ("SHORT", "110")])
def test_risk_and_gross_caps_size_by_exact_step_and_charge_entry_fee(side, stop):
    p = AccountPolicy(D("0.3"), D("10"), D("10"), D("5"), 1_000)
    a = new_account(D("10000"), p)
    a, _ = mark_account(a, mark_id="m", marks=(("BTCUSDT", D("100"), 1),), as_of_ms=1)
    a, r, outcome = reserve_entry(
        a,
        reservation_id="r",
        intent_id="i",
        symbol="BTCUSDT",
        side=side,
        stop_price=D(stop),
        worst_entry_price=D("100"),
        worst_notional_price=D("100"),
        as_of_ms=1,
        expires_at_ms=100,
    )
    assert outcome == "RESERVED"
    assert r.quantity % D("0.3") == 0
    assert r.reserved_risk <= D("25")
    assert r.quantity * D("100") <= D("10000")
    a, state = record_entry_fill(
        a,
        reservation_id="r",
        fill_id="f",
        quantity=r.quantity,
        average_price=D("100"),
        fee=r.quantity * D("100") * D("10") / D("10000"),
        at_ms=2,
    )
    assert state == "RECORDED"
    assert a.cash < D("10000")
    assert a.realized_net < 0
    assert a.open_risk <= a.equity * D("0.01")
    assert a._position_risk(a.positions[0], D("100")) <= a.equity * D("0.0025")
    assert resolve_entry(a, reservation_id="r", event_id="resolve", outcome="FILLED").open_risk > 0


@pytest.mark.parametrize("side,exit_price,expected", [("LONG", "105", "5"), ("SHORT", "95", "5")])
def test_partial_exit_realizes_side_correct_pnl_and_funding(side, exit_price, expected):
    a, r, _ = reserve(account(), side=side)
    a, _ = record_entry_fill(
        a, reservation_id="r1", fill_id="f1", quantity=D("1"), average_price=D("100"), fee=D("1"), at_ms=20
    )
    a = resolve_entry(a, reservation_id="r1", event_id="resolve1", outcome="PARTIAL")
    original_risk = a.open_risk
    a, state = record_exit_fill(
        a,
        intent_id="i-r1",
        fill_id="x1",
        quantity=D("0.4"),
        average_price=D(exit_price),
        fee=D("0.2"),
        at_ms=30,
    )
    assert state == "RECORDED"
    assert a.positions[0].quantity == D("0.6")
    assert a.positions[0].realized_gross == D("2.0")
    assert a.realized_net == D("0.8")  # entry fee 1, partial gross 2, exit fee .2
    assert a.open_risk == original_risk * D("0.6")
    a = record_funding(a, intent_id="i-r1", event_id="funding", cashflow=D("-0.1"), at_ms=31)
    assert a.realized_net == D("0.7")


@pytest.mark.parametrize("side,exit_price,expected", [("LONG", "105", "3"), ("SHORT", "95", "3")])
def test_full_exit_closes_without_constructing_zero_quantity_position(side, exit_price, expected):
    a, _, _ = reserve(account(), side=side)
    a, _ = record_entry_fill(
        a, reservation_id="r1", fill_id="entry", quantity=D("1"), average_price=D("100"), fee=D("1"), at_ms=20
    )
    a = resolve_entry(a, reservation_id="r1", event_id="resolved", outcome="FILLED")
    a, state = record_exit_fill(
        a,
        intent_id="i-r1",
        fill_id="full-exit",
        quantity=D("1"),
        average_price=D(exit_price),
        fee=D("1"),
        at_ms=21,
    )
    assert state == "RECORDED"
    assert a.positions == ()
    assert a.realized_net == D(expected)
    assert a.equity == D("10000") + D(expected)


def test_expired_reservation_and_missing_active_symbol_marks_are_barriers():
    a = account()
    with pytest.raises(ValueError, match="positive remaining lifetime"):
        reserve_entry(
            a,
            reservation_id="expired",
            intent_id="expired-i",
            symbol="BTCUSDT",
            side="LONG",
            stop_price=D("90"),
            worst_entry_price=D("100"),
            worst_notional_price=D("100"),
            as_of_ms=10,
            expires_at_ms=10,
        )
    a, r, _ = reserve(a)
    a, _ = record_entry_fill(
        a,
        reservation_id="r1",
        fill_id="entry",
        quantity=r.quantity,
        average_price=D("100"),
        fee=D("0"),
        at_ms=20,
    )
    a = resolve_entry(a, reservation_id="r1", event_id="resolve", outcome="FILLED")
    a, state = mark_account(
        a, mark_id="other-symbol-only", marks=(("ETHUSDT", D("100"), 2_000),), as_of_ms=2_000
    )
    assert state == "BARRIER"
    assert a.barrier == "STALE_OR_MISSING_ACTIVE_MARK"


def test_late_entry_fill_preserves_exposure_and_sticky_barrier():
    a, r, _ = reserve(account(), expiry=21)
    a, state = record_entry_fill(
        a,
        reservation_id="r1",
        fill_id="late",
        quantity=r.quantity,
        average_price=D("100"),
        fee=D("1"),
        at_ms=22,
    )
    assert state == "BARRIER"
    assert a.positions and a.positions[0].quantity == r.quantity
    assert a.cash == D("9999")
    assert a.barrier == "LATE_ENTRY_FILL"
    assert set_barrier(a, event_id="later", reason="OTHER").barrier == "LATE_ENTRY_FILL"


def test_unmatched_and_overquantity_fills_keep_observed_facts_and_never_negative_reservations():
    a, state = record_entry_fill(
        account(),
        reservation_id="missing-reservation",
        fill_id="orphan-fill",
        quantity=D("0.2"),
        average_price=D("100"),
        fee=D("0.5"),
        at_ms=20,
    )
    assert state == "BARRIER"
    assert a.unresolved_fills[0].quantity == D("0.2")
    assert a.unresolved_fills[0].fee == D("0.5")
    assert a.cash == D("9999.5")

    b, r, _ = reserve(account())
    b, state = record_entry_fill(
        b,
        reservation_id="r1",
        fill_id="overfill",
        quantity=r.quantity * D("2"),
        average_price=D("100"),
        fee=D("1"),
        at_ms=20,
    )
    assert state == "BARRIER"
    assert b.positions[0].quantity == r.quantity * D("2")
    assert b.open_risk > 0
    assert b.reservations[0].filled_quantity > b.reservations[0].quantity


def test_short_adverse_lower_fill_is_preserved_but_blocks_admission():
    a, r, _ = reserve(account(), side="SHORT", stop=D("110"), entry=D("100"), notional=D("110"))
    a, state = record_entry_fill(
        a,
        reservation_id="r1",
        fill_id="worse-short",
        quantity=r.quantity,
        average_price=D("99"),
        fee=D("0"),
        at_ms=20,
    )
    assert state == "BARRIER"
    assert a.positions[0].entry_price == D("99")
    assert a.barrier == "ENTRY_FILL_EXCEEDS_RESERVATION"


def test_short_favorable_higher_fill_is_not_misclassified_as_bad_entry_price():
    a, r, _ = reserve(account(), side="SHORT", stop=D("110"), entry=D("100"), notional=D("120"))
    a, state = record_entry_fill(
        a,
        reservation_id="r1",
        fill_id="better-short",
        quantity=r.quantity,
        average_price=D("101"),
        fee=D("0"),
        at_ms=20,
    )
    assert state == "RECORDED"
    assert a.positions[0].entry_price == D("101")


def test_duplicate_ids_are_exact_once_and_conflicts_fail():
    a, r, _ = reserve(account())
    same, state = record_entry_fill(
        a, reservation_id="r1", fill_id="f", quantity=D("0.5"), average_price=D("100"), fee=D("0.1"), at_ms=20
    )
    again, outcome = record_entry_fill(
        same,
        reservation_id="r1",
        fill_id="f",
        quantity=D("0.5"),
        average_price=D("100"),
        fee=D("0.1"),
        at_ms=20,
    )
    assert outcome == "REPLAYED" and again == same
    with pytest.raises(ValueError, match="conflicting"):
        record_entry_fill(
            same,
            reservation_id="r1",
            fill_id="f",
            quantity=D("0.6"),
            average_price=D("100"),
            fee=D("0.1"),
            at_ms=20,
        )


def test_service_cost_debits_equity_and_unknown_fill_preserves_barrier_and_reserved_exposure():
    from adaptive_replay.adaptive_sim_account import debit_cost

    a = account()
    a = debit_cost(a, cost_id="api", amount=D("25"), at_ms=11, kind="SERVICE")
    assert a.equity == D("9975")
    a, r, _ = reserve(a)
    a = resolve_entry(a, reservation_id="r1", event_id="unknown", outcome="UNKNOWN")
    assert a.barrier == "UNKNOWN_ENTRY_EXPOSURE"
    assert a.open_risk >= r.reserved_risk
    a, denied, reason = reserve_entry(
        a,
        reservation_id="r2",
        intent_id="i2",
        symbol="ETHUSDT",
        side="LONG",
        stop_price=D("90"),
        worst_entry_price=D("100"),
        worst_notional_price=D("100"),
        as_of_ms=20,
        expires_at_ms=500,
    )
    assert denied is None and reason == "BARRIER"
    assert a.barrier == "UNKNOWN_ENTRY_EXPOSURE"


def test_mark_over_limit_is_recorded_and_sticky_blocks_entries():
    a, r, _ = reserve(account())
    a, _ = record_entry_fill(
        a, reservation_id="r1", fill_id="f", quantity=r.quantity, average_price=D("100"), fee=D("0"), at_ms=20
    )
    a = resolve_entry(a, reservation_id="r1", event_id="resolved", outcome="FILLED")
    a, status = mark_account(a, mark_id="spike", marks=(("BTCUSDT", D("500"), 30),), as_of_ms=30)
    assert status == "OVER_LIMIT"
    assert a.risk_over_limit and a.open_risk > a.equity * D("0.01")
    a, _, reason = reserve_entry(
        a,
        reservation_id="r2",
        intent_id="i2",
        symbol="ETHUSDT",
        side="LONG",
        stop_price=D("90"),
        worst_entry_price=D("100"),
        worst_notional_price=D("100"),
        as_of_ms=30,
        expires_at_ms=500,
    )
    assert reason == "BARRIER"
    a, status = mark_account(a, mark_id="recovery-mark", marks=(("BTCUSDT", D("100"), 31),), as_of_ms=31)
    assert status == "OVER_LIMIT" and a.risk_over_limit


@pytest.mark.parametrize("price,ts,now", [(D("0"), 10, 10), (D("100"), 9, 10), (D("100"), 10, 2_000)])
def test_zero_regressing_or_stale_marks_set_barrier(price, ts, now):
    a = account()
    if price <= 0:
        with pytest.raises(ValueError, match="positive"):
            mark_account(a, mark_id="bad", marks=(("BTCUSDT", price, ts),), as_of_ms=now)
        return
    a, status = mark_account(a, mark_id="bad", marks=(("BTCUSDT", price, ts),), as_of_ms=now)
    assert status == "BARRIER" and a.barrier == "STALE_OR_REGRESSING_MARK"


@pytest.mark.parametrize("value", [100.0, True, D("NaN"), D("Infinity")])
def test_float_bool_and_nonfinite_decimals_rejected(value):
    with pytest.raises(ValueError):
        AccountPolicy(value, D("0"), D("0"), D("0"), 100)


def test_service_and_entry_events_deduct_once_and_exact_boundary_reservation():
    from adaptive_replay.adaptive_sim_account import debit_cost

    a = account()
    a = debit_cost(a, cost_id="fee", amount=D("10"), at_ms=11, kind="SERVICE")
    assert debit_cost(a, cost_id="fee", amount=D("10"), at_ms=11, kind="SERVICE") == a
    with pytest.raises(ValueError, match="conflicting"):
        debit_cost(a, cost_id="fee", amount=D("11"), at_ms=11, kind="SERVICE")
    a, r, _ = reserve(a, stop=D("99.75"), entry=D("100"))
    assert r is not None and r.reserved_risk <= a.equity * D("0.0025")
    assert a.gross_notional <= a.equity


def test_gap_barrier_is_durable_in_reducer_and_not_force_closed():
    a, r, _ = reserve(account())
    a, _ = record_entry_fill(
        a, reservation_id="r1", fill_id="f", quantity=r.quantity, average_price=D("100"), fee=D("0"), at_ms=20
    )
    a = resolve_entry(a, reservation_id="r1", event_id="resolved", outcome="FILLED")
    before = a.positions
    a = set_barrier(a, event_id="gap", reason="BOOK_COVERAGE_GAP")
    assert a.positions == before and a.barrier == "BOOK_COVERAGE_GAP"


def _entry_basis_account():
    p = AccountPolicy(D("0.1"), D("0"), D("0"), D("0"), 1_000, "ENTRY_STOP_RESERVED")
    a = new_account(D("10000"), p)
    symbols = ("BNBUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    return mark_account(a, mark_id="all-marks", marks=tuple((s, D("100"), 10) for s in symbols), as_of_ms=10)[
        0
    ]


def _full_entry(a, *, rid="r1", symbol="BTCUSDT", side="LONG", at=20):
    a, r, status = reserve(a, rid=rid, symbol=symbol, side=side, as_of=at)
    assert status == "RESERVED" and r is not None
    a, status = record_entry_fill(
        a,
        reservation_id=rid,
        fill_id=f"fill-{rid}",
        quantity=r.quantity,
        average_price=D("100"),
        fee=D("0"),
        at_ms=at,
    )
    assert status == "RECORDED"
    return resolve_entry(a, reservation_id=rid, event_id=f"resolved-{rid}", outcome="FILLED")


@pytest.mark.parametrize("side,stop", [("LONG", "95"), ("SHORT", "105")])
def test_original_entry_risk_remains_reserved_after_tighter_trailing_stop(side, stop):
    a = _full_entry(_entry_basis_account(), side=side)
    risk_before = a.open_risk
    original = a.reservations[0]
    a = tighten_stop(
        a,
        intent_id="i-r1",
        event_id="closed-trail",
        stop_price=D(stop),
        source_event_ms=21,
        available_ms=22,
        as_of_ms=23,
    )
    assert a.open_risk == risk_before and a.reservations[0] == original
    assert a.positions[0].stop_price == D(stop)
    assert (
        tighten_stop(
            a,
            intent_id="i-r1",
            event_id="closed-trail",
            stop_price=D(stop),
            source_event_ms=21,
            available_ms=22,
            as_of_ms=23,
        )
        == a
    )
    with pytest.raises(ValueError, match="only tighten"):
        tighten_stop(
            a,
            intent_id="i-r1",
            event_id="looser",
            stop_price=original.stop_price,
            source_event_ms=24,
            available_ms=24,
            as_of_ms=24,
        )
    with pytest.raises(ValueError, match="causal"):
        tighten_stop(
            a,
            intent_id="i-r1",
            event_id="future",
            stop_price=D("99"),
            source_event_ms=30,
            available_ms=31,
            as_of_ms=29,
        )


def test_second_fill_does_not_requalify_old_entry_sizing_against_lower_equity():
    a = _full_entry(_entry_basis_account())
    a, status = mark_account(a, mark_id="small-loss", marks=(("BTCUSDT", D("99"), 30),), as_of_ms=30)
    assert status == "MARKED" and a.barrier is None
    assert a._position_risk(a.positions[0], D("99")) > a.equity * D("0.0025")
    a = _full_entry(a, rid="r2", symbol="ETHUSDT", at=31)
    assert len(a.positions) == 2 and a.barrier is None and not a.risk_over_limit
    assert a.open_risk <= a.equity * D("0.01")


def test_aggregate_risk_overrun_blocks_now_but_retains_historical_fact_after_recovery():
    a = _entry_basis_account()
    symbols = ("BNBUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT")
    for index, symbol in enumerate(symbols):
        a = _full_entry(a, rid=f"r{index}", symbol=symbol)
    assert a.open_risk == D("100")
    a, status = mark_account(
        a, mark_id="aggregate-loss", marks=tuple((s, D("99"), 30) for s in symbols), as_of_ms=30
    )
    assert status == "OVER_LIMIT" and a.risk_over_limit and a.historical_risk_overrun
    _, r, reason = reserve(a, rid="denied", symbol="XRPUSDT", as_of=30)
    assert r is None and reason == "BARRIER"
    a, status = mark_account(
        a, mark_id="aggregate-recovery", marks=tuple((s, D("100"), 31) for s in symbols), as_of_ms=31
    )
    assert status == "MARKED" and not a.risk_over_limit and a.historical_risk_overrun


@pytest.mark.parametrize("reason", ["STOP", "TRAILING_STOP", "TARGET", "TIMEOUT"])
def test_owned_protection_pending_survives_partial_exit_then_full_flat_releases_it(reason):
    a = _full_entry(_entry_basis_account())
    a = request_protective_exit(a, intent_id="i-r1", event_id="exit-request", reason=reason)
    assert a.protective_exit_pending == ("i-r1",) and a.barrier is None
    assert request_protective_exit(a, intent_id="i-r1", event_id="exit-request", reason=reason) == a
    _, r, state = reserve(a, rid="denied", symbol="ETHUSDT", as_of=21)
    assert r is None and state == "BARRIER"
    qty = a.positions[0].quantity
    a, _ = record_exit_fill(
        a,
        intent_id="i-r1",
        fill_id="partial-exit",
        quantity=D("0.5"),
        average_price=D("95"),
        fee=D("0"),
        at_ms=22,
    )
    assert a.protective_exit_pending == ("i-r1",)
    a, _ = record_exit_fill(
        a,
        intent_id="i-r1",
        fill_id="last-exit",
        quantity=qty - D("0.5"),
        average_price=D("95"),
        fee=D("0"),
        at_ms=23,
    )
    assert not a.positions and not a.protective_exit_pending and a.barrier is None
    _, r, state = reserve(a, rid="new-parent", symbol="ETHUSDT", as_of=24)
    assert r is not None and state == "RESERVED"


def test_owned_stop_crossing_is_pending_protection_not_permanent_unknown_exposure():
    a = _full_entry(_entry_basis_account())
    a, status = mark_account(a, mark_id="cross-stop", marks=(("BTCUSDT", D("89"), 30),), as_of_ms=30)
    assert status == "PROTECTIVE_EXIT_PENDING" and a.barrier is None
    assert a.protective_exit_pending == ("i-r1",)


def test_external_barrier_cannot_be_cleared_by_closing_owned_protection():
    a = _full_entry(_entry_basis_account())
    a = request_protective_exit(a, intent_id="i-r1", event_id="stop-owned", reason="STOP")
    a = set_barrier(a, event_id="source-gap", reason="BOOK_COVERAGE_GAP")
    a, _ = record_exit_fill(
        a,
        intent_id="i-r1",
        fill_id="flat-after-gap",
        quantity=a.positions[0].quantity,
        average_price=D("90"),
        fee=D("0"),
        at_ms=30,
    )
    assert a.barrier == "BOOK_COVERAGE_GAP" and not a.protective_exit_pending


@pytest.mark.parametrize("side,entry,stop", [("LONG", "101", "90"), ("SHORT", "99", "110")])
def test_normal_spread_and_fees_are_reserved_against_post_fill_equity(side, entry, stop):
    policy = AccountPolicy(D("0.00001"), D("5"), D("5"), D("0"), 1_000, "ENTRY_STOP_RESERVED")
    a = new_account(D("10000"), policy)
    a, _ = mark_account(a, mark_id="mid", marks=(("BTCUSDT", D("100"), 10),), as_of_ms=10)
    a, reservation, state = reserve(a, side=side, entry=D(entry), stop=D(stop), notional=D("101"))
    assert state == "RESERVED"
    a, state = record_entry_fill(
        a,
        reservation_id="r1",
        fill_id="normal-spread-fill",
        quantity=reservation.quantity,
        average_price=D(entry),
        fee=reservation.quantity * D(entry) * D("5") / D("10000"),
        at_ms=21,
    )
    assert state == "RECORDED" and a.barrier is None
    assert reservation.reserved_risk <= a.equity * D("0.0025")
    assert a.open_risk <= a.equity * D("0.01")


def test_all_pending_spread_fee_losses_fit_shared_current_equity_cap_after_fills():
    symbols = ("BNBUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT")
    policy = AccountPolicy(D("0.00001"), D("5"), D("5"), D("0"), 1_000, "ENTRY_STOP_RESERVED")
    a = new_account(D("10000"), policy)
    a, _ = mark_account(a, mark_id="all-mids", marks=tuple((s, D("100"), 10) for s in symbols), as_of_ms=10)
    reservations = []
    for i, symbol in enumerate(symbols):
        a, reservation, state = reserve(
            a, symbol=symbol, rid=f"pending-{i}", entry=D("101"), notional=D("101")
        )
        assert state == "RESERVED"
        reservations.append(reservation)
    for i, reservation in enumerate(reservations):
        a, state = record_entry_fill(
            a,
            reservation_id=reservation.reservation_id,
            fill_id=f"actual-fill-{i}",
            quantity=reservation.quantity,
            average_price=D("101"),
            fee=reservation.quantity * D("101") * D("5") / D("10000"),
            at_ms=21,
        )
        assert state == "RECORDED" and a.barrier is None
        assert a.open_risk <= a.equity * D("0.01")
        assert a.gross_notional <= a.equity
    assert len(a.positions) == 4 and not a.historical_risk_overrun


def test_gross_capacity_reserves_immediate_spread_loss_without_crediting_future_gains():
    policy = AccountPolicy(D("0.00001"), D("0"), D("0"), D("0"), 1_000, "ENTRY_STOP_RESERVED")
    a = new_account(D("10000"), policy)
    a, _ = mark_account(a, mark_id="mid", marks=(("BTCUSDT", D("100"), 10),), as_of_ms=10)
    a, reservation, state = reserve(a, entry=D("101"), stop=D("100.99"), notional=D("101"))
    assert state == "RESERVED"
    a, state = record_entry_fill(
        a,
        reservation_id="r1",
        fill_id="gross-capped-fill",
        quantity=reservation.quantity,
        average_price=D("101"),
        fee=D("0"),
        at_ms=21,
    )
    assert state == "RECORDED" and a.barrier is None
    assert reservation.quantity * D("101") <= a.equity
