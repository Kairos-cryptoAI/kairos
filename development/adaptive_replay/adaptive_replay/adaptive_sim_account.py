"""Pure immutable account/risk reducer for isolated adaptive book-SIM research.

This module is an accounting primitive only. It has no persistence, venue,
source-authentication, execution, campaign, or qualification authority.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_FLOOR, Context, Decimal, localcontext
from functools import wraps
from typing import Literal

ZERO = Decimal("0")
ONE = Decimal("1")
BPS = Decimal("10000")
MAX_TRADE_RISK = Decimal("0.0025")
MAX_OPEN_RISK = Decimal("0.01")
MAX_GROSS = Decimal("1")
SideName = Literal["LONG", "SHORT"]
SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"})
_ARITHMETIC = Context(prec=96)


def _decimal_context(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with localcontext(_ARITHMETIC):
            return function(*args, **kwargs)

    return wrapped


def _d(value: Decimal, name: str, *, positive: bool = False, nonnegative: bool = False) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal (bool/float coercion is forbidden)")
    if positive and value <= ZERO:
        raise ValueError(f"{name} must be positive")
    if nonnegative and value < ZERO:
        raise ValueError(f"{name} must be nonnegative")
    return value


def _id(value: str, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > 128:
        raise ValueError(f"{name} must be a normalized nonempty identifier")
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise ValueError(f"{name} must use printable canonical ASCII")
    return value


def _ms(value: int, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer millisecond clock")
    return value


@dataclass(frozen=True)
class AccountPolicy:
    quantity_step: Decimal
    entry_fee_bps: Decimal
    exit_fee_bps: Decimal
    adverse_exit_slippage_bps: Decimal
    maximum_mark_age_ms: int
    risk_basis: Literal["MARKED_STRICT", "ENTRY_STOP_RESERVED"] = "MARKED_STRICT"

    def __post_init__(self) -> None:
        if self.risk_basis not in {"MARKED_STRICT", "ENTRY_STOP_RESERVED"}:
            raise ValueError("explicit supported account risk basis required")
        _d(self.quantity_step, "quantity_step", positive=True)
        for name in ("entry_fee_bps", "exit_fee_bps", "adverse_exit_slippage_bps"):
            _d(getattr(self, name), name, nonnegative=True)
        _ms(self.maximum_mark_age_ms, "maximum_mark_age_ms")
        if self.maximum_mark_age_ms == 0 or any(
            getattr(self, name) >= BPS
            for name in ("entry_fee_bps", "exit_fee_bps", "adverse_exit_slippage_bps")
        ):
            raise ValueError("positive mark-age bound and sub-100% costs required")


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    intent_id: str
    symbol: str
    side: SideName
    stop_price: Decimal
    quantity: Decimal
    worst_entry_price: Decimal
    worst_notional_price: Decimal
    reserved_risk: Decimal
    created_at_ms: int
    expires_at_ms: int
    filled_quantity: Decimal = ZERO
    filled_notional: Decimal = ZERO
    entry_fees: Decimal = ZERO
    terminal: str = "OPEN"

    def __post_init__(self) -> None:
        _id(self.reservation_id, "reservation_id")
        _id(self.intent_id, "intent_id")
        _id(self.symbol, "symbol")
        if self.symbol not in SYMBOLS:
            raise ValueError("symbol outside fixed five-symbol SIM universe")
        _direction(self.side)
        for name in ("stop_price", "quantity", "worst_entry_price", "worst_notional_price"):
            _d(getattr(self, name), name, positive=True)
        for name in ("reserved_risk", "filled_quantity", "filled_notional", "entry_fees"):
            _d(getattr(self, name), name, nonnegative=True)
        _ms(self.created_at_ms, "created_at_ms")
        _ms(self.expires_at_ms, "expires_at_ms")
        if self.expires_at_ms < self.created_at_ms:
            raise ValueError("reservation expiry cannot precede creation")
        if self.terminal not in {
            "OPEN",
            "FILLED",
            "PARTIAL",
            "NO_FILL",
            "UNKNOWN",
        }:
            raise ValueError("invalid reservation fill total or lifecycle state")


@dataclass(frozen=True)
class Position:
    intent_id: str
    symbol: str
    side: SideName
    stop_price: Decimal
    quantity: Decimal
    entry_price: Decimal
    entry_fees: Decimal
    exit_fees: Decimal = ZERO
    realized_gross: Decimal = ZERO
    funding_cashflow: Decimal = ZERO
    opened_at_ms: int = 0

    def __post_init__(self) -> None:
        _id(self.intent_id, "intent_id")
        _id(self.symbol, "symbol")
        if self.symbol not in SYMBOLS:
            raise ValueError("symbol outside fixed five-symbol SIM universe")
        _direction(self.side)
        for name in ("stop_price", "quantity", "entry_price"):
            _d(getattr(self, name), name, positive=True)
        for name in ("entry_fees", "exit_fees"):
            _d(getattr(self, name), name, nonnegative=True)
        _d(self.realized_gross, "realized_gross")
        _d(self.funding_cashflow, "funding_cashflow")
        _ms(self.opened_at_ms, "opened_at_ms")


@dataclass(frozen=True)
class AccountEvent:
    event_id: str
    payload: tuple[object, ...]

    def __post_init__(self) -> None:
        _id(self.event_id, "event_id")
        if type(self.payload) is not tuple:
            raise ValueError("event payload must be an immutable tuple")


@dataclass(frozen=True)
class UnresolvedFill:
    fill_id: str
    reservation_id: str
    quantity: Decimal
    average_price: Decimal
    fee: Decimal
    at_ms: int

    def __post_init__(self) -> None:
        _id(self.fill_id, "fill_id")
        _id(self.reservation_id, "reservation_id")
        _d(self.quantity, "quantity", positive=True)
        _d(self.average_price, "average_price", positive=True)
        _d(self.fee, "fee", nonnegative=True)
        _ms(self.at_ms, "at_ms")


@dataclass(frozen=True)
class SimAccount:
    policy: AccountPolicy
    initial_equity: Decimal
    cash: Decimal
    realized_net_pnl: Decimal = ZERO
    service_cost_total: Decimal = ZERO
    marks: tuple[tuple[str, Decimal, int], ...] = ()
    reservations: tuple[Reservation, ...] = ()
    positions: tuple[Position, ...] = ()
    events: tuple[AccountEvent, ...] = ()
    unresolved_fills: tuple[UnresolvedFill, ...] = ()
    barrier: str | None = None
    risk_over_limit: bool = False
    historical_risk_overrun: bool = False
    protective_exit_pending: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _d(self.initial_equity, "initial_equity", positive=True)
        _d(self.cash, "cash")
        _d(self.realized_net_pnl, "realized_net_pnl")
        _d(self.service_cost_total, "service_cost_total", nonnegative=True)
        if self.barrier is not None:
            _id(self.barrier, "account barrier")
        if type(self.risk_over_limit) is not bool or type(self.historical_risk_overrun) is not bool:
            raise ValueError("account risk gates must be exact booleans")
        if type(self.policy) is not AccountPolicy or any(type(x) is not AccountEvent for x in self.events):
            raise ValueError("typed account policy and immutable event ledger required")
        if any(type(x) is not Reservation for x in self.reservations) or any(
            type(x) is not Position for x in self.positions
        ):
            raise ValueError("typed immutable reservations and positions required")
        if (
            type(self.marks) is not tuple
            or type(self.reservations) is not tuple
            or type(self.positions) is not tuple
            or type(self.events) is not tuple
            or type(self.unresolved_fills) is not tuple
        ):
            raise ValueError("account collections must be immutable tuples")
        if any(type(x) is not UnresolvedFill for x in self.unresolved_fills):
            raise ValueError("typed unresolved fill evidence required")
        if tuple(sorted(self.marks)) != self.marks:
            raise ValueError("marks must be canonically ordered")
        for symbol, price, timestamp in self.marks:
            _id(symbol, "mark symbol")
            _d(price, "mark", positive=True)
            _ms(timestamp, "mark timestamp")
        if tuple(sorted(self.reservations, key=lambda x: x.reservation_id)) != self.reservations:
            raise ValueError("reservations must be canonically ordered")
        if tuple(sorted(self.positions, key=lambda x: x.symbol)) != self.positions:
            raise ValueError("positions must be canonically ordered by symbol")
        if len({p.symbol for p in self.positions}) != len(self.positions):
            raise ValueError("at most one active position per symbol")
        if len({e.event_id for e in self.events}) != len(self.events):
            raise ValueError("event IDs must be unique")
        if len({r.reservation_id for r in self.reservations}) != len(self.reservations):
            raise ValueError("reservation IDs must be unique")
        if len({r.intent_id for r in self.reservations}) != len(self.reservations):
            raise ValueError("reservation intents must be unique")
        if len({p.intent_id for p in self.positions}) != len(self.positions):
            raise ValueError("position intents must be unique")
        if len({fill.fill_id for fill in self.unresolved_fills}) != len(self.unresolved_fills):
            raise ValueError("unresolved fill IDs must be unique")
        if (
            type(self.protective_exit_pending) is not tuple
            or tuple(sorted(set(self.protective_exit_pending))) != self.protective_exit_pending
            or not set(self.protective_exit_pending) <= {p.intent_id for p in self.positions}
        ):
            raise ValueError("pending owned protection must identify exact current positions")

    @property
    @_decimal_context
    def equity(self) -> Decimal:
        marks = {symbol: price for symbol, price, _ in self.marks}
        return self.cash + sum(
            (
                p.quantity * (marks[p.symbol] - p.entry_price) * _direction(p.side)
                for p in self.positions
                if p.symbol in marks
            ),
            ZERO,
        )

    @property
    def realized_net(self) -> Decimal:
        return self.realized_net_pnl

    @property
    @_decimal_context
    def net_return(self) -> Decimal:
        return (self.equity - self.initial_equity) / self.initial_equity

    @property
    @_decimal_context
    def open_risk(self) -> Decimal:
        marks = {symbol: price for symbol, price, _ in self.marks}
        reserved = sum(
            (
                r.reserved_risk * max(ZERO, r.quantity - r.filled_quantity) / r.quantity
                for r in self.reservations
                if r.terminal in {"OPEN", "UNKNOWN"}
            ),
            ZERO,
        )
        positions = sum(
            (self._position_risk(p, marks.get(p.symbol, p.entry_price)) for p in self.positions), ZERO
        )
        unknown = sum((f.quantity * f.average_price for f in self.unresolved_fills), ZERO)
        return reserved + positions + unknown

    @property
    @_decimal_context
    def gross_notional(self) -> Decimal:
        marks = {symbol: price for symbol, price, _ in self.marks}
        reserved = sum(
            (
                max(ZERO, r.quantity - r.filled_quantity) * r.worst_notional_price
                for r in self.reservations
                if r.terminal in {"OPEN", "UNKNOWN"}
            ),
            ZERO,
        )
        positions = sum((p.quantity * marks.get(p.symbol, p.entry_price) for p in self.positions), ZERO)
        unknown = sum((f.quantity * f.average_price for f in self.unresolved_fills), ZERO)
        return reserved + positions + unknown

    @_decimal_context
    def _position_risk(self, position: Position, mark: Decimal) -> Decimal:
        # Stop risk is marked against current equity; a breached stop is an
        # unresolved safety barrier, never a zero-risk position.
        stop = position.stop_price
        reference = mark
        if self.policy.risk_basis == "ENTRY_STOP_RESERVED":
            reservation = next((r for r in self.reservations if r.intent_id == position.intent_id), None)
            if reservation is None:
                # No original reservation means no honest released risk budget.
                return position.quantity * max(mark, position.entry_price)
            stop, reference = reservation.stop_price, position.entry_price
        adverse_stop = stop * (
            ONE - self.policy.adverse_exit_slippage_bps / BPS
            if position.side == "LONG"
            else ONE + self.policy.adverse_exit_slippage_bps / BPS
        )
        per_unit = abs(reference - adverse_stop) + adverse_stop * self.policy.exit_fee_bps / BPS
        per_unit += position.entry_fees / position.quantity
        return position.quantity * per_unit


def _direction(side: SideName) -> Decimal:
    if side == "LONG":
        return ONE
    if side == "SHORT":
        return -ONE
    raise ValueError("side must be LONG or SHORT")


def new_account(initial_equity: Decimal, policy: AccountPolicy) -> SimAccount:
    _d(initial_equity, "initial_equity", positive=True)
    if type(policy) is not AccountPolicy:
        raise ValueError("typed immutable account policy required")
    return SimAccount(policy, initial_equity, initial_equity)


def _once(account: SimAccount, event_id: str, payload: tuple[object, ...]) -> bool:
    _id(event_id, "event_id")
    prior = next((e for e in account.events if e.event_id == event_id), None)
    if prior is not None and prior.payload != payload:
        raise ValueError("event ID reused with conflicting content")
    return prior is not None


def _commit(account: SimAccount, event_id: str, payload: tuple[object, ...], **changes: object) -> SimAccount:
    if _once(account, event_id, payload):
        return account
    if account.barrier is not None:
        changes["barrier"] = account.barrier
    return replace(account, **changes, events=(*account.events, AccountEvent(event_id, payload)))


@_decimal_context
def _floor_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


@_decimal_context
def reserve_entry(
    account: SimAccount,
    *,
    reservation_id: str,
    intent_id: str,
    symbol: str,
    side: SideName,
    stop_price: Decimal,
    worst_entry_price: Decimal,
    worst_notional_price: Decimal,
    as_of_ms: int,
    expires_at_ms: int,
) -> tuple[SimAccount, Reservation | None, str]:
    """Reserve a bounded size at worst entry; returned refusal is explicit, not authority."""
    _id(reservation_id, "reservation_id")
    _id(intent_id, "intent_id")
    _id(symbol, "symbol")
    _direction(side)
    _d(stop_price, "stop_price", positive=True)
    _d(worst_entry_price, "worst_entry_price", positive=True)
    _d(worst_notional_price, "worst_notional_price", positive=True)
    _ms(as_of_ms, "as_of_ms")
    _ms(expires_at_ms, "expires_at_ms")
    if expires_at_ms <= as_of_ms:
        raise ValueError("reservation must have positive remaining lifetime")
    payload = (
        "RESERVE",
        reservation_id,
        intent_id,
        symbol,
        side,
        stop_price,
        worst_entry_price,
        worst_notional_price,
        as_of_ms,
        expires_at_ms,
    )
    if _once(account, reservation_id, payload):
        existing = next((r for r in account.reservations if r.reservation_id == reservation_id), None)
        return account, existing, "REPLAYED"
    if account.barrier or account.risk_over_limit or account.protective_exit_pending:
        return _commit(account, reservation_id, payload), None, "BARRIER"
    if any(p.symbol == symbol for p in account.positions) or any(
        r.symbol == symbol and r.terminal == "OPEN" for r in account.reservations
    ):
        return _commit(account, reservation_id, payload), None, "SYMBOL_ALREADY_RESERVED_OR_OPEN"
    if not account.marks:
        return _commit(account, reservation_id, payload), None, "MARKS_UNAVAILABLE"
    marks = {symbol: (price, timestamp) for symbol, price, timestamp in account.marks}
    required_symbols = {symbol}
    required_symbols.update(position.symbol for position in account.positions)
    required_symbols.update(r.symbol for r in account.reservations if r.terminal in {"OPEN", "UNKNOWN"})
    if any(
        item not in marks
        or marks[item][1] > as_of_ms
        or as_of_ms - marks[item][1] > account.policy.maximum_mark_age_ms
        for item in required_symbols
    ):
        return (
            _commit(account, reservation_id, payload, barrier="STALE_OR_MISSING_ENTRY_MARK"),
            None,
            "BARRIER",
        )
    equity = account.equity
    if equity <= ZERO:
        return _commit(account, reservation_id, payload), None, "NONPOSITIVE_EQUITY"
    adverse_stop = stop_price * (
        ONE - account.policy.adverse_exit_slippage_bps / BPS
        if side == "LONG"
        else ONE + account.policy.adverse_exit_slippage_bps / BPS
    )
    directional_loss = (worst_entry_price - adverse_stop) * _direction(side)
    if directional_loss <= ZERO:
        return _commit(account, reservation_id, payload), None, "STOP_NOT_ADVERSE_TO_ENTRY"
    entry_fee_per_unit = worst_entry_price * account.policy.entry_fee_bps / BPS
    unit_loss = directional_loss + entry_fee_per_unit + adverse_stop * account.policy.exit_fee_bps / BPS
    if unit_loss <= ZERO:
        return _commit(account, reservation_id, payload), None, "INVALID_UNIT_RISK"
    # Current-equity limits must still hold after known immediate spread/fee
    # losses, including pending entries that may all fill before another mark.
    # Do not book hypothetical favorable marks or release original stop risk.
    pending_capital_loss = sum(
        (
            max(ZERO, r.quantity - r.filled_quantity)
            * (
                r.worst_entry_price * account.policy.entry_fee_bps / BPS
                + max(ZERO, (r.worst_entry_price - marks[r.symbol][0]) * _direction(r.side))
            )
            for r in account.reservations
            if r.terminal in {"OPEN", "UNKNOWN"}
        ),
        ZERO,
    )
    projected_equity = max(ZERO, equity - pending_capital_loss)
    immediate_loss_per_unit = entry_fee_per_unit + max(
        ZERO, (worst_entry_price - marks[symbol][0]) * _direction(side)
    )
    trade_qty = projected_equity * MAX_TRADE_RISK / (unit_loss + MAX_TRADE_RISK * immediate_loss_per_unit)
    open_budget = max(ZERO, projected_equity * MAX_OPEN_RISK - account.open_risk)
    open_qty = open_budget / (unit_loss + MAX_OPEN_RISK * immediate_loss_per_unit)
    gross_budget = max(ZERO, projected_equity * MAX_GROSS - account.gross_notional)
    gross_qty = gross_budget / (worst_notional_price + MAX_GROSS * immediate_loss_per_unit)
    risk_qty = min(trade_qty, open_qty)
    quantity = _floor_step(min(risk_qty, gross_qty), account.policy.quantity_step)
    if quantity <= ZERO:
        return _commit(account, reservation_id, payload), None, "RISK_OR_GROSS_CAPACITY_EXHAUSTED"
    reserved = Reservation(
        reservation_id,
        intent_id,
        symbol,
        side,
        stop_price,
        quantity,
        worst_entry_price,
        worst_notional_price,
        quantity * unit_loss,
        as_of_ms,
        expires_at_ms,
    )
    next_account = _commit(
        account,
        reservation_id,
        payload,
        reservations=tuple(sorted((*account.reservations, reserved), key=lambda r: r.reservation_id)),
    )
    return next_account, reserved, "RESERVED"


@_decimal_context
def record_entry_fill(
    account: SimAccount,
    *,
    reservation_id: str,
    fill_id: str,
    quantity: Decimal,
    average_price: Decimal,
    fee: Decimal,
    at_ms: int,
) -> tuple[SimAccount, str]:
    _id(reservation_id, "reservation_id")
    _id(fill_id, "fill_id")
    _d(quantity, "quantity", positive=True)
    _d(average_price, "average_price", positive=True)
    _d(fee, "fee", nonnegative=True)
    _ms(at_ms, "at_ms")
    payload = ("ENTRY_FILL", reservation_id, quantity, average_price, fee, at_ms)
    if _once(account, fill_id, payload):
        return account, "REPLAYED"
    r = next((x for x in account.reservations if x.reservation_id == reservation_id), None)
    if r is None or r.terminal not in {"OPEN", "UNKNOWN"}:
        fact = UnresolvedFill(fill_id, reservation_id, quantity, average_price, fee, at_ms)
        result = _commit(
            account,
            fill_id,
            payload,
            cash=account.cash - fee,
            realized_net_pnl=account.realized_net_pnl - fee,
            unresolved_fills=(*account.unresolved_fills, fact),
            barrier=account.barrier or "ENTRY_FILL_WITHOUT_RESERVATION",
        )
        return result, "BARRIER"
    late = at_ms > r.expires_at_ms or at_ms < r.created_at_ms
    over = r.filled_quantity + quantity > r.quantity
    filled_qty = r.filled_quantity + quantity
    notional = r.filled_notional + quantity * average_price
    fees = r.entry_fees + fee
    avg = notional / filled_qty
    adverse_stop = r.stop_price * (
        ONE - account.policy.adverse_exit_slippage_bps / BPS
        if r.side == "LONG"
        else ONE + account.policy.adverse_exit_slippage_bps / BPS
    )
    risk_unit = abs(avg - adverse_stop) + fees / filled_qty + adverse_stop * account.policy.exit_fee_bps / BPS
    over |= (
        filled_qty * risk_unit > r.reserved_risk
        or (r.filled_quantity + quantity > r.quantity)
        or quantity * average_price > max(ZERO, r.quantity - r.filled_quantity) * r.worst_notional_price
        or (
            (average_price > r.worst_entry_price if r.side == "LONG" else average_price < r.worst_entry_price)
            and r.filled_quantity + quantity <= r.quantity
        )
    )
    updated = replace(r, filled_quantity=filled_qty, filled_notional=notional, entry_fees=fees)
    reservations = tuple(updated if x.reservation_id == reservation_id else x for x in account.reservations)
    positions = list(account.positions)
    pos = next((p for p in positions if p.intent_id == r.intent_id), None)
    if pos is None and any(p.symbol == r.symbol for p in positions):
        fact = UnresolvedFill(fill_id, reservation_id, quantity, average_price, fee, at_ms)
        result = _commit(
            account,
            fill_id,
            payload,
            cash=account.cash - fee,
            realized_net_pnl=account.realized_net_pnl - fee,
            reservations=tuple(sorted(reservations, key=lambda x: x.reservation_id)),
            unresolved_fills=(*account.unresolved_fills, fact),
            barrier=account.barrier or "UNMATCHED_SYMBOL_EXPOSURE",
        )
        return result, "BARRIER"
    if pos is None:
        positions.append(
            Position(
                r.intent_id, r.symbol, r.side, r.stop_price, quantity, average_price, fee, opened_at_ms=at_ms
            )
        )
    else:
        total = pos.quantity + quantity
        positions[positions.index(pos)] = replace(
            pos,
            quantity=total,
            entry_price=(pos.entry_price * pos.quantity + average_price * quantity) / total,
            entry_fees=pos.entry_fees + fee,
        )
    result = _commit(
        account,
        fill_id,
        payload,
        cash=account.cash - fee,
        realized_net_pnl=account.realized_net_pnl - fee,
        reservations=tuple(sorted(reservations, key=lambda x: x.reservation_id)),
        positions=tuple(sorted(positions, key=lambda x: x.symbol)),
        barrier=account.barrier
        or ("LATE_ENTRY_FILL" if late else "ENTRY_FILL_EXCEEDS_RESERVATION" if over else None),
    )
    marks = {s: price for s, price, ts in result.marks if ts <= at_ms}
    mark_times = {s: ts for s, _, ts in result.marks}
    active_symbols = {p.symbol for p in result.positions}
    active_symbols.update(
        reservation.symbol
        for reservation in result.reservations
        if reservation.terminal in {"OPEN", "UNKNOWN"}
    )
    stale_marks = any(
        symbol not in marks or at_ms - mark_times[symbol] > result.policy.maximum_mark_age_ms
        for symbol in active_symbols
    )
    stop_breach = any(
        p.symbol in marks
        and (marks[p.symbol] <= p.stop_price if p.side == "LONG" else marks[p.symbol] >= p.stop_price)
        for p in result.positions
    )
    limit_breached = (
        result.open_risk > result.equity * MAX_OPEN_RISK
        or result.gross_notional > result.equity
        or any(
            result._position_risk(p, marks.get(p.symbol, p.entry_price)) > result.equity * MAX_TRADE_RISK
            for p in result.positions
            if result.policy.risk_basis == "MARKED_STRICT" or p.intent_id == r.intent_id
        )
    )
    breached = limit_breached or stale_marks
    if over or late or breached:
        result = replace(
            result,
            barrier=result.barrier
            or (
                "LATE_ENTRY_FILL"
                if late
                else "ENTRY_FILL_EXCEEDS_RESERVATION"
                if over
                else "STALE_OR_MISSING_ENTRY_FILL_MARK"
                if stale_marks
                else "ACTUAL_FILL_OVER_LIMIT"
            ),
            risk_over_limit=result.risk_over_limit or limit_breached,
            historical_risk_overrun=result.historical_risk_overrun or limit_breached,
        )
    if stop_breach:
        result = replace(
            result,
            protective_exit_pending=tuple(
                sorted(
                    set(result.protective_exit_pending)
                    | {
                        p.intent_id
                        for p in result.positions
                        if p.symbol in marks
                        and (
                            marks[p.symbol] <= p.stop_price
                            if p.side == "LONG"
                            else marks[p.symbol] >= p.stop_price
                        )
                    }
                )
            ),
        )
    return result, "BARRIER" if over or late or breached else "RECORDED"


@_decimal_context
def resolve_entry(
    account: SimAccount,
    *,
    reservation_id: str,
    event_id: str,
    outcome: Literal["FILLED", "PARTIAL", "NO_FILL", "UNKNOWN"],
) -> SimAccount:
    _id(reservation_id, "reservation_id")
    _id(event_id, "event_id")
    if outcome not in {"FILLED", "PARTIAL", "NO_FILL", "UNKNOWN"}:
        raise ValueError("explicit terminal entry outcome required")
    payload = ("ENTRY_RESOLUTION", reservation_id, outcome)
    if _once(account, event_id, payload):
        return account
    r = next((x for x in account.reservations if x.reservation_id == reservation_id), None)
    if r is None or r.terminal != "OPEN":
        return _commit(account, event_id, payload, barrier="ENTRY_RESOLUTION_WITHOUT_RESERVATION")
    if (
        (outcome == "FILLED" and r.filled_quantity != r.quantity)
        or (outcome == "PARTIAL" and not ZERO < r.filled_quantity < r.quantity)
        or (outcome == "NO_FILL" and r.filled_quantity != ZERO)
    ):
        return _commit(account, event_id, payload, barrier="ENTRY_RESOLUTION_FILL_TOTAL_CONFLICT")
    terminal = "UNKNOWN" if outcome == "UNKNOWN" else outcome
    updated = replace(r, terminal=terminal)
    reservations = tuple(updated if x.reservation_id == reservation_id else x for x in account.reservations)
    barrier = "UNKNOWN_ENTRY_EXPOSURE" if outcome == "UNKNOWN" else account.barrier
    if outcome in {"FILLED", "PARTIAL", "NO_FILL"}:
        # Released unused reservation is conservative only after explicit terminal evidence.
        pass
    return _commit(
        account,
        event_id,
        payload,
        reservations=tuple(sorted(reservations, key=lambda x: x.reservation_id)),
        barrier=barrier,
    )


@_decimal_context
def record_exit_fill(
    account: SimAccount,
    *,
    intent_id: str,
    fill_id: str,
    quantity: Decimal,
    average_price: Decimal,
    fee: Decimal,
    at_ms: int,
) -> tuple[SimAccount, str]:
    _id(intent_id, "intent_id")
    _id(fill_id, "fill_id")
    _d(quantity, "quantity", positive=True)
    _d(average_price, "average_price", positive=True)
    _d(fee, "fee", nonnegative=True)
    _ms(at_ms, "at_ms")
    payload = ("EXIT_FILL", intent_id, quantity, average_price, fee, at_ms)
    if _once(account, fill_id, payload):
        return account, "REPLAYED"
    p = next((x for x in account.positions if x.intent_id == intent_id), None)
    if p is None:
        fact = UnresolvedFill(fill_id, intent_id, quantity, average_price, fee, at_ms)
        result = _commit(
            account,
            fill_id,
            payload,
            cash=account.cash - fee,
            realized_net_pnl=account.realized_net_pnl - fee,
            unresolved_fills=(*account.unresolved_fills, fact),
            barrier=account.barrier or "EXIT_FILL_WITHOUT_MATCHING_EXPOSURE",
        )
        return result, "BARRIER"
    if at_ms < p.opened_at_ms:
        fact = UnresolvedFill(fill_id, intent_id, quantity, average_price, fee, at_ms)
        return _commit(
            account,
            fill_id,
            payload,
            cash=account.cash - fee,
            realized_net_pnl=account.realized_net_pnl - fee,
            unresolved_fills=(*account.unresolved_fills, fact),
            barrier=account.barrier or "EXIT_BEFORE_ENTRY_TIME",
        ), "BARRIER"
    overfill = quantity > p.quantity
    matched_qty = min(quantity, p.quantity)
    matched_fee = fee * matched_qty / quantity
    excess_fact = (
        UnresolvedFill(fill_id, intent_id, quantity - matched_qty, average_price, fee - matched_fee, at_ms)
        if overfill
        else None
    )
    gross = matched_qty * (average_price - p.entry_price) * _direction(p.side)
    allocated_entry_fees = p.entry_fees * matched_qty / p.quantity
    next_quantity = p.quantity - matched_qty
    next_position = (
        replace(
            p,
            quantity=next_quantity,
            entry_fees=p.entry_fees - allocated_entry_fees,
            realized_gross=p.realized_gross + gross,
            exit_fees=p.exit_fees + matched_fee,
        )
        if next_quantity > ZERO
        else None
    )
    positions = tuple(
        sorted((x for x in account.positions if x.intent_id != intent_id), key=lambda x: x.symbol)
    )
    if next_position is not None:
        positions = tuple(sorted((*positions, next_position), key=lambda x: x.symbol))
    return _commit(
        account,
        fill_id,
        payload,
        cash=account.cash + gross - fee,
        realized_net_pnl=account.realized_net_pnl + gross - fee,
        positions=positions,
        protective_exit_pending=tuple(
            item for item in account.protective_exit_pending if item != intent_id or next_position is not None
        ),
        unresolved_fills=(*account.unresolved_fills, excess_fact)
        if excess_fact
        else account.unresolved_fills,
        barrier=account.barrier or ("EXIT_OVERFILL" if overfill else None),
    ), "BARRIER" if overfill else "RECORDED"


@_decimal_context
def record_funding(
    account: SimAccount, *, intent_id: str, event_id: str, cashflow: Decimal, at_ms: int
) -> SimAccount:
    _id(intent_id, "intent_id")
    _id(event_id, "event_id")
    _d(cashflow, "cashflow")
    _ms(at_ms, "at_ms")
    payload = ("FUNDING", intent_id, cashflow, at_ms)
    if _once(account, event_id, payload):
        return account
    p = next((x for x in account.positions if x.intent_id == intent_id), None)
    if p is None:
        return _commit(account, event_id, payload, barrier="FUNDING_WITHOUT_MATCHING_EXPOSURE")
    if at_ms < p.opened_at_ms:
        return _commit(account, event_id, payload, barrier=account.barrier or "FUNDING_BEFORE_ENTRY_TIME")
    updated = replace(p, funding_cashflow=p.funding_cashflow + cashflow)
    positions = tuple(
        sorted(
            (updated if x.intent_id == intent_id else x for x in account.positions), key=lambda x: x.symbol
        )
    )
    return _commit(
        account,
        event_id,
        payload,
        cash=account.cash + cashflow,
        realized_net_pnl=account.realized_net_pnl + cashflow,
        positions=positions,
    )


@_decimal_context
def debit_cost(account: SimAccount, *, cost_id: str, amount: Decimal, at_ms: int, kind: str) -> SimAccount:
    _id(cost_id, "cost_id")
    _d(amount, "amount", nonnegative=True)
    _ms(at_ms, "at_ms")
    if kind not in {"SERVICE", "ENTRY_FEE"}:
        raise ValueError("explicit SERVICE or ENTRY_FEE cost kind required")
    payload = (kind, amount, at_ms)
    if _once(account, cost_id, payload):
        return account
    return _commit(
        account,
        cost_id,
        payload,
        cash=account.cash - amount,
        service_cost_total=account.service_cost_total + amount,
    )


@_decimal_context
def mark_account(
    account: SimAccount, *, mark_id: str, marks: tuple[tuple[str, Decimal, int], ...], as_of_ms: int
) -> tuple[SimAccount, str]:
    _id(mark_id, "mark_id")
    _ms(as_of_ms, "as_of_ms")
    if (
        type(marks) is not tuple
        or not marks
        or tuple(sorted(marks)) != marks
        or len({x[0] for x in marks}) != len(marks)
    ):
        raise ValueError("nonempty unique canonically ordered immutable marks required")
    old = {symbol: (price, timestamp) for symbol, price, timestamp in account.marks}
    new = {}
    for symbol, price, timestamp in marks:
        _id(symbol, "mark symbol")
        _d(price, "mark", positive=True)
        _ms(timestamp, "mark timestamp")
        if (
            timestamp > as_of_ms
            or timestamp < old.get(symbol, (ZERO, 0))[1]
            or as_of_ms - timestamp > account.policy.maximum_mark_age_ms
        ):
            payload = ("MARK", marks, as_of_ms)
            return _commit(account, mark_id, payload, barrier="STALE_OR_REGRESSING_MARK"), "BARRIER"
        new[symbol] = (price, timestamp)
    payload = ("MARK", marks, as_of_ms)
    if _once(account, mark_id, payload):
        return account, "REPLAYED"
    merged = {**old, **new}
    next_account = replace(account, marks=tuple(sorted((s, p, t) for s, (p, t) in merged.items())))
    current_marks = {symbol: price for symbol, price, _ in next_account.marks}
    stop_breached = any(
        (
            current_marks[p.symbol] <= p.stop_price
            if p.side == "LONG"
            else current_marks[p.symbol] >= p.stop_price
        )
        for p in next_account.positions
        if p.symbol in current_marks
    )
    per_trade_over = account.policy.risk_basis == "MARKED_STRICT" and any(
        next_account._position_risk(p, current_marks.get(p.symbol, p.entry_price))
        > next_account.equity * MAX_TRADE_RISK
        for p in next_account.positions
    )
    over = (
        (account.risk_over_limit if account.policy.risk_basis == "MARKED_STRICT" else False)
        or next_account.equity <= ZERO
        or per_trade_over
        or (next_account.open_risk > next_account.equity * MAX_OPEN_RISK)
        or next_account.gross_notional > next_account.equity * MAX_GROSS
    )
    timestamp_by_symbol = {symbol: timestamp for symbol, _, timestamp in next_account.marks}
    required = {p.symbol for p in next_account.positions}
    required.update(r.symbol for r in next_account.reservations if r.terminal in {"OPEN", "UNKNOWN"})
    if any(
        symbol not in current_marks
        or timestamp_by_symbol[symbol] > as_of_ms
        or as_of_ms - timestamp_by_symbol[symbol] > account.policy.maximum_mark_age_ms
        for symbol in required
    ):
        return _commit(
            next_account, mark_id, payload, barrier=account.barrier or "STALE_OR_MISSING_ACTIVE_MARK"
        ), "BARRIER"
    pending = tuple(
        sorted(
            set(next_account.protective_exit_pending)
            | {
                p.intent_id
                for p in next_account.positions
                if p.symbol in current_marks
                and (
                    current_marks[p.symbol] <= p.stop_price
                    if p.side == "LONG"
                    else current_marks[p.symbol] >= p.stop_price
                )
            }
        )
    )
    return _commit(
        next_account,
        mark_id,
        payload,
        risk_over_limit=over,
        historical_risk_overrun=account.historical_risk_overrun or over,
        protective_exit_pending=pending,
    ), "PROTECTIVE_EXIT_PENDING" if stop_breached else "OVER_LIMIT" if over else "MARKED"


@_decimal_context
def tighten_stop(
    account: SimAccount,
    *,
    intent_id: str,
    event_id: str,
    stop_price: Decimal,
    source_event_ms: int,
    available_ms: int,
    as_of_ms: int,
) -> SimAccount:
    """Causal tighter effective stop; the original risk reservation is never released.

    Caller must bind the closed-candle activation/distance to the unchanged plan.
    This reducer cannot establish that source or replace the original plan.
    """
    _id(intent_id, "intent_id")
    _id(event_id, "event_id")
    _d(stop_price, "stop_price", positive=True)
    for value in (source_event_ms, available_ms, as_of_ms):
        _ms(value, "trailing clock")
    payload = ("TIGHTEN_STOP", intent_id, stop_price, source_event_ms, available_ms, as_of_ms)
    if _once(account, event_id, payload):
        return account
    position = next((p for p in account.positions if p.intent_id == intent_id), None)
    if position is None or not position.opened_at_ms <= source_event_ms <= available_ms <= as_of_ms:
        raise ValueError("owned position and causal closed-source stop update required")
    if not (
        stop_price > position.stop_price if position.side == "LONG" else stop_price < position.stop_price
    ):
        raise ValueError("effective stop may only tighten")
    positions = tuple(
        replace(p, stop_price=stop_price) if p.intent_id == intent_id else p for p in account.positions
    )
    return _commit(account, event_id, payload, positions=positions)


def request_protective_exit(
    account: SimAccount,
    *,
    intent_id: str,
    event_id: str,
    reason: str,
) -> SimAccount:
    """Block new admission while a known owned SL/TP/timeout exit is unresolved."""
    _id(intent_id, "intent_id")
    _id(event_id, "event_id")
    if reason not in {"STOP", "TRAILING_STOP", "TARGET", "TIMEOUT"}:
        raise ValueError("exact owned protective-exit reason required")
    payload = ("OWNED_PROTECTIVE_EXIT", intent_id, reason)
    if _once(account, event_id, payload):
        return account
    if not any(p.intent_id == intent_id for p in account.positions):
        raise ValueError("protective exit requires known matching exposure")
    return _commit(
        account,
        event_id,
        payload,
        protective_exit_pending=tuple(sorted(set(account.protective_exit_pending) | {intent_id})),
    )


def set_barrier(account: SimAccount, *, event_id: str, reason: str) -> SimAccount:
    _id(event_id, "event_id")
    _id(reason, "reason")
    payload = ("BARRIER", reason)
    if _once(account, event_id, payload):
        return account
    return _commit(account, event_id, payload, barrier=reason)
