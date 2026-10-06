"""One causal shared-account clock; all fills are declared development assumptions.

No orders, providers, database, random draws, campaign enrollment or qualification.
Minute OHLC cannot prove intraminute quotes, capacity or protective-order latency.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from kairos_backtest.cost_risk import AllInCostModel, RiskLimits, size_and_admit
from kairos_core.enums import Side
from kairos_strategy.adaptive.config import DEFAULT_CONFIG, UNIVERSE
from kairos_strategy.candles import Candle
from kairos_strategy.models import SleeveIntent

MINUTE = 60_000


@dataclass(frozen=True)
class CostScenario:
    id: str
    fee_bps_per_side: float
    spread_bps: float
    slippage_bps_per_side: float
    latency_bps_round_trip: float
    uncertainty_bps: float
    admission_adverse_carry_bps: float

    def __post_init__(self) -> None:
        values = [v for k, v in asdict(self).items() if k != "id"]
        if not self.id or any(not math.isfinite(v) or v < 0 for v in values):
            raise ValueError("invalid finite nonnegative execution assumptions")

    @property
    def costs(self) -> AllInCostModel:
        return AllInCostModel(
            fee_bps_per_side=self.fee_bps_per_side,
            spread_bps=self.spread_bps,
            slippage_bps_per_side=self.slippage_bps_per_side,
            adverse_funding_bps=self.admission_adverse_carry_bps,
            latency_bps=self.latency_bps_round_trip,
            uncertainty_buffer_bps=self.uncertainty_bps,
        )

    @property
    def displacement(self) -> float:
        return (self.spread_bps / 2 + self.slippage_bps_per_side + self.latency_bps_round_trip / 2) / 10_000


def entry_time(intent: SleeveIntent, completion_ms: int, mode: str) -> int | None:
    if isinstance(completion_ms, bool) or completion_ms < intent.decision_ts_ms:
        raise ValueError("completion cannot precede the decision")
    earliest = max(intent.entry_eligible_ts_ms, completion_ms)
    if mode == "STRICT_MINUTE_OPEN":
        earliest = ((earliest + MINUTE - 1) // MINUTE) * MINUTE
    elif mode != "INTRABAR_OPEN_PROXY":
        raise ValueError("unknown fill observation mode")
    return None if earliest > intent.entry_expires_ts_ms else earliest


def fill_price(reference: float, side: Side, entering: bool, scenario: CostScenario) -> float:
    sign = 1 if side is Side.LONG else -1
    result = reference * (1 + sign * (1 if entering else -1) * scenario.displacement)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("nonpositive modeled fill")
    return result


@dataclass
class Position:
    intent: SleeveIntent
    quantity: float
    entry_price: float
    entry_ms: int
    entry_fee: float
    reserved_risk: float
    funding_cost: float = 0.0

    @property
    def direction(self) -> int:
        return 1 if self.intent.side is Side.LONG else -1

    def unrealized(self, price: float) -> float:
        return self.direction * self.quantity * (price - self.entry_price)


class Portfolio:
    def __init__(self, equity: float, scenario: CostScenario, mode: str) -> None:
        if not math.isfinite(equity) or equity <= 0:
            raise ValueError("positive finite equity required")
        if mode not in {"STRICT_MINUTE_OPEN", "INTRABAR_OPEN_PROXY"}:
            raise ValueError("unknown fill observation mode")
        self.initial_equity = self.cash = self.peak = equity
        self.scenario, self.mode = scenario, mode
        self.positions: dict[str, Position] = {}
        self.seen: set[str] = set()
        self.rejections: Counter[str] = Counter()
        self.entries_by_day: Counter[str] = Counter()
        self.trades: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.max_closed_minute_drawdown = 0.0
        self.max_adverse_envelope_drawdown = 0.0
        self.max_open_risk_fraction = 0.0
        self.max_gross_leverage = 0.0
        self.intrabar_ambiguities = 0
        self.suppressed_entry_minute_targets = 0
        self.suppressed_deadline_minute_targets = 0

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + math.fsum(p.unrealized(prices[s]) for s, p in self.positions.items())

    def _reject(self, reason: str, intent: SleeveIntent) -> bool:
        self.rejections[reason] += 1
        self.events.append({"kind": "REJECT", "intent_id": intent.intent_id, "reason": reason})
        return False

    def admit(self, intent: SleeveIntent, completion_ms: int, bar: Candle, prices: dict[str, float]) -> bool:
        if intent.intent_id in self.seen:
            return self._reject("DUPLICATE_INTENT", intent)
        self.seen.add(intent.intent_id)
        ts = entry_time(intent, completion_ms, self.mode)
        if ts is None:
            return self._reject("NO_OBSERVED_MINUTE_QUOTE_WITHIN_LIFETIME", intent)
        if bar.symbol != intent.symbol or not bar.open_time_ms <= ts <= bar.close_time_ms:
            return self._reject("FILL_BAR_UNAVAILABLE", intent)
        if intent.symbol in self.positions:
            return self._reject("SYMBOL_POSITION_ALREADY_OPEN", intent)
        equity = self.equity(prices)
        if equity <= 0:
            return self._reject("NO_POSITIVE_EQUITY", intent)
        entry = fill_price(bar.open, intent.side, True, self.scenario)
        stop, target = intent.exit_plan.stop_price, intent.exit_plan.target_price
        features = dict(intent.metadata)
        try:
            atr = float(features["frozen_atr15"])
        except (KeyError, ValueError):
            return self._reject("STRUCTURAL_ATR_UNAVAILABLE", intent)
        risk = abs(entry - stop)
        risk_bps = risk / entry * 10_000
        if not math.isfinite(atr) or atr <= 0:
            return self._reject("STRUCTURAL_ATR_UNAVAILABLE", intent)
        if not DEFAULT_CONFIG.minimum_stop_atr * atr <= risk <= DEFAULT_CONFIG.maximum_stop_atr * atr:
            return self._reject("FILL_STOP_OUTSIDE_STRUCTURAL_ATR_BOUNDS", intent)
        if (
            self.scenario.costs.estimated_round_trip_bps
            > DEFAULT_CONFIG.maximum_cost_stop_fraction * risk_bps
        ):
            return self._reject("FILL_INSUFFICIENT_COST_HEADROOM", intent)
        decision = size_and_admit(
            side=intent.side,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            equity_usd=equity,
            costs=self.scenario.costs,
            limits=RiskLimits(maximum_stop_distance_bps=DEFAULT_CONFIG.maximum_stop_bps),
        )
        if not decision.accepted:
            return self._reject(f"FILL_{decision.reason}", intent)
        loss_unit = risk + max(entry, stop) * self.scenario.costs.estimated_round_trip_bps / 10_000
        fee_unit = entry * self.scenario.fee_bps_per_side / 10_000
        # Sizing uses post-entry fee/mark debit, not overstated pre-entry equity.
        debit_unit = fee_unit + abs(entry - bar.open)
        quantity = min(
            decision.quantity,
            equity * 0.0025 / (loss_unit + 0.0025 * debit_unit),
            equity * 0.25 / (max(entry, bar.open) + 0.25 * debit_unit),
        )
        reserved = quantity * loss_unit
        post_equity = equity - quantity * debit_unit
        open_risk = math.fsum(p.reserved_risk for p in self.positions.values())
        if open_risk + reserved > post_equity * 0.01 + 1e-9:
            return self._reject("AGGREGATE_OPEN_RISK_CAP", intent)
        gross = math.fsum(p.quantity * prices[s] for s, p in self.positions.items())
        if gross + quantity * max(entry, bar.open) > post_equity + 1e-9:
            return self._reject("GROSS_1X_CAP", intent)
        self.cash -= quantity * fee_unit
        self.positions[intent.symbol] = Position(intent, quantity, entry, ts, quantity * fee_unit, reserved)
        day = datetime.fromtimestamp(ts / 1000, UTC).date().isoformat()
        self.entries_by_day[day] += 1
        self.events.append(
            {
                "kind": "ENTRY",
                "intent_id": intent.intent_id,
                "symbol": intent.symbol,
                "timestamp_ms": ts,
                "quantity": quantity,
                "price": entry,
                "reserved_risk_usd": reserved,
                "post_entry_equity_usd": post_equity,
                "authority": "CONDITIONAL_CANDLE_PRICE_PROXY"
                if self.mode == "INTRABAR_OPEN_PROXY"
                else "OBSERVED_MINUTE_OPEN_PRICE_WITH_MODELED_COSTS",
            }
        )
        return True

    def settle(self, symbol: str, ts: int, rate: float, price: float) -> None:
        if not math.isfinite(rate) or not math.isfinite(price) or price <= 0:
            raise ValueError("invalid funding event")
        position = self.positions.get(symbol)
        if position is None:
            return
        if ts < position.entry_ms or ts > position.entry_ms + position.intent.exit_plan.max_holding_ms:
            return
        cost = position.direction * position.quantity * price * rate
        self.cash -= cost
        position.funding_cost += cost
        self.events.append(
            {
                "kind": "FUNDING",
                "intent_id": position.intent.intent_id,
                "timestamp_ms": ts,
                "native_8h_rate": rate,
                "signed_cost_usd": cost,
                "price_authority": "CANDLE_OPEN_NOT_MARK_PRICE",
                "clock_authority": "ARCHIVE_CALC_TIME_ENTITLEMENT_PROXY",
            }
        )

    def _close(self, symbol: str, ts: int, reference: float, reason: str, gap: bool = False) -> None:
        p = self.positions.pop(symbol)
        price = fill_price(reference, p.intent.side, False, self.scenario)
        fee = p.quantity * price * self.scenario.fee_bps_per_side / 10_000
        gross = p.unrealized(price)
        self.cash += gross - fee
        net = gross - p.entry_fee - fee - p.funding_cost
        self.trades.append(
            {
                "intent_id": p.intent.intent_id,
                "symbol": symbol,
                "side": p.intent.side.value,
                "entry_ms": p.entry_ms,
                "exit_ms": ts,
                "entry_price": p.entry_price,
                "exit_price": price,
                "quantity": p.quantity,
                "reason": reason,
                "gap": gap,
                "gross_pnl_usd": gross,
                "entry_fee_usd": p.entry_fee,
                "exit_fee_usd": fee,
                "signed_funding_cost_usd": p.funding_cost,
                "net_pnl_usd": net,
                "reserved_risk_usd": p.reserved_risk,
                "realized_loss_exceeds_reservation": -net > p.reserved_risk + 1e-9,
                "holding_ms": ts - p.entry_ms,
                "regime": dict(p.intent.metadata).get("regime"),
                "timestamp_authority": "MINUTE_BOUND_OR_TIMEOUT_PROXY_NOT_TICK_RECEIPT",
            }
        )

    def exit_at_open(self, bar: Candle) -> None:
        p = self.positions.get(bar.symbol)
        if p is None:
            return
        stop, target = p.intent.exit_plan.stop_price, p.intent.exit_plan.target_price
        stop_gap = bar.open <= stop if p.direction == 1 else bar.open >= stop
        target_gap = bar.open >= target if p.direction == 1 else bar.open <= target
        if stop_gap:
            self._close(bar.symbol, bar.open_time_ms, bar.open, "SL", True)
        elif target_gap:
            self._close(bar.symbol, bar.open_time_ms, target, "TP", True)
        elif bar.open_time_ms >= p.entry_ms + p.intent.exit_plan.max_holding_ms:
            self._close(bar.symbol, bar.open_time_ms, bar.open, "TIMEOUT")

    def exit_intrabar(self, bar: Candle) -> None:
        p = self.positions.get(bar.symbol)
        if p is None:
            return
        stop, target = p.intent.exit_plan.stop_price, p.intent.exit_plan.target_price
        stop_touch = bar.low <= stop if p.direction == 1 else bar.high >= stop
        target_touch = bar.high >= target if p.direction == 1 else bar.low <= target
        deadline = p.entry_ms + p.intent.exit_plan.max_holding_ms
        entry_minute = p.entry_ms >= bar.open_time_ms
        deadline_minute = deadline <= bar.close_time_ms
        if stop_touch and target_touch:
            self.intrabar_ambiguities += 1
        if target_touch and entry_minute:
            self.suppressed_entry_minute_targets += 1
        if target_touch and deadline_minute:
            self.suppressed_deadline_minute_targets += 1
        # An intrabar stop may have preceded the entry/deadline: adverse bound,
        # explicitly not an inferred observed sequence. Never credit that TP.
        if stop_touch:
            self._close(bar.symbol, min(bar.close_time_ms, deadline), stop, "SL")
        elif deadline_minute:
            self._close(bar.symbol, deadline, bar.open, "TIMEOUT")
        elif target_touch and not entry_minute:
            self._close(bar.symbol, bar.close_time_ms, target, "TP")

    def adverse_envelope(self, bars: dict[str, Candle]) -> None:
        # Worst prices need not have been simultaneous, and may be after a stop:
        # this is an adverse bound, NOT observed intraday/tick equity drawdown.
        bound = self.cash + math.fsum(
            p.unrealized(bars[s].low if p.direction == 1 else bars[s].high) for s, p in self.positions.items()
        )
        self.max_adverse_envelope_drawdown = max(
            self.max_adverse_envelope_drawdown, max(0.0, (self.peak - bound) / self.peak)
        )

    def mark(self, prices: dict[str, float]) -> None:
        equity = self.equity(prices)
        self.peak = max(self.peak, equity)
        self.max_closed_minute_drawdown = max(
            self.max_closed_minute_drawdown, (self.peak - equity) / self.peak
        )
        risk = math.fsum(p.reserved_risk for p in self.positions.values())
        gross = math.fsum(p.quantity * prices[s] for s, p in self.positions.items())
        self.max_open_risk_fraction = max(self.max_open_risk_fraction, risk / equity if equity > 0 else 1.0)
        self.max_gross_leverage = max(self.max_gross_leverage, gross / equity if equity > 0 else 1.0)

    def report(self, final_prices: dict[str, float], days: list[str]) -> dict[str, Any]:
        equity = self.equity(final_prices)
        closed_net = math.fsum(t["net_pnl_usd"] for t in self.trades)
        open_contribution = math.fsum(
            p.unrealized(final_prices[s]) - p.entry_fee - p.funding_cost for s, p in self.positions.items()
        )
        error = equity - self.initial_equity - closed_net - open_contribution
        if not math.isclose(error, 0.0, abs_tol=1e-7):
            raise ValueError("economic cash/fee/funding ledger does not reconcile")
        profits = math.fsum(max(t["net_pnl_usd"], 0) for t in self.trades)
        losses = math.fsum(max(-t["net_pnl_usd"], 0) for t in self.trades)
        return {
            "entry_mode": self.mode,
            "cost_scenario": asdict(self.scenario),
            "planning_round_trip_bps": self.scenario.costs.estimated_round_trip_bps,
            "final_equity_usd": equity,
            "net_return_pct": (equity / self.initial_equity - 1) * 100,
            "closed_trade_net_usd": closed_net,
            "closed_trades": len(self.trades),
            "profit_factor": profits / losses if losses else None,
            "profit_factor_status": "FINITE"
            if losses
            else "NO_LOSSES"
            if profits
            else "ZERO_PNL_TRADES"
            if self.trades
            else "NO_TRADES",
            "return_scope": "TRADING_NET_WITH_CANDLE_FUNDING_PROXY_EXCLUDING_UNAVAILABLE_MODEL_FEED_COSTS",
            "funding_clock_authority": "ARCHIVE_CALC_TIME_ENTITLEMENT_PROXY",
            "intraminute_timeout_reservation": (
                "HELD_UNTIL_BAR_CLOSE_CONSERVATIVE_ADMISSION_NOT_EXACT_EXECUTION"
            ),
            "complete_all_in_net_economics": False,
            "closed_minute_mtm_drawdown_pct": self.max_closed_minute_drawdown * 100,
            "adverse_envelope_bound_pct": self.max_adverse_envelope_drawdown * 100,
            "max_observed_mark_open_risk_fraction": self.max_open_risk_fraction,
            "max_observed_mark_gross_leverage": self.max_gross_leverage,
            "risk_ceiling_mark_overrun": self.max_open_risk_fraction > 0.01 + 1e-9,
            "gross_ceiling_mark_overrun": self.max_gross_leverage > 1 + 1e-9,
            "admission_rejections": dict(sorted(self.rejections.items())),
            "entries_each_utc_day": {day: self.entries_by_day[day] for day in days},
            "zero_entry_days": sum(self.entries_by_day[d] == 0 for d in days),
            "natural_exit_counts": dict(Counter(t["reason"] for t in self.trades)),
            "long_net_usd": math.fsum(t["net_pnl_usd"] for t in self.trades if t["side"] == Side.LONG.value),
            "short_net_usd": math.fsum(
                t["net_pnl_usd"] for t in self.trades if t["side"] == Side.SHORT.value
            ),
            "realized_loss_over_reservation_count": sum(
                t["realized_loss_exceeds_reservation"] for t in self.trades
            ),
            "mean_holding_minutes": math.fsum(t["holding_ms"] for t in self.trades)
            / MINUTE
            / len(self.trades)
            if self.trades
            else None,
            "ambiguous_barrier_minutes": self.intrabar_ambiguities,
            "suppressed_entry_minute_targets": self.suppressed_entry_minute_targets,
            "suppressed_deadline_minute_targets": self.suppressed_deadline_minute_targets,
            "terminal_unresolved_positions": [
                {
                    "symbol": s,
                    "intent_id": p.intent.intent_id,
                    "reserved_risk_usd": p.reserved_risk,
                    "unrealized_usd": p.unrealized(final_prices[s]),
                }
                for s, p in self.positions.items()
            ],
            "forced_settlements": 0,
            "ledger_reconciliation_error_usd": error,
            "model_calls": 0,
            "model_cost_usd": None,
            "model_cost_status": "NOT_CALLED_NOT_FREE_SERVICE",
            "market_feed_cost_usd": None,
            "market_feed_cost_status": "LOCAL_ARCHIVE_NOT_LIVE_FEED",
            "partial_fill_status": "NOT_MODELED_FULL_FILL_CONDITIONAL_APPROXIMATION",
            "execution_qualification": False,
        }


def replay_tape(
    inputs: Any,
    tape: dict[int, list[SleeveIntent]],
    scenario: CostScenario,
    mode: str,
    latency_ms: int,
    exit_tail_hours: int = 3,
) -> tuple[dict[str, Any], Portfolio]:
    account = Portfolio(10_000, scenario, mode)
    funding: dict[int, list[tuple[int, str, float]]] = {}
    for symbol, rows in inputs.funding.items():
        for event in rows:
            minute = event.timestamp_ms // MINUTE * MINUTE
            funding.setdefault(minute, []).append((event.timestamp_ms, symbol, event.rate))
    by_symbol = {s: {bar.open_time_ms: bar for bar in rows} for s, rows in inputs.bars.items()}
    final_prices: dict[str, float] = {}
    replay_end = inputs.end_ms + exit_tail_hours * 3_600_000
    if inputs.data_end_ms < replay_end:
        raise ValueError("complete bounded exit tail required")
    for ts in range(inputs.start_ms, replay_end, MINUTE):
        bars = {s: by_symbol[s][ts] for s in UNIVERSE}
        opens = {s: bar.open for s, bar in bars.items()}
        events = funding.get(ts, [])
        for event_ms, symbol, rate in events:
            if event_ms == ts:
                account.settle(symbol, event_ms, rate, opens[symbol])
        for symbol in UNIVERSE:
            account.exit_at_open(bars[symbol])
        # Actual archive funding events are NOT rounded back to open. Merge
        # their cash clocks with the modeled review/entry attempt clocks.
        ordered_events: list[tuple[int, int, int, Any]] = [
            (event_ms, 0, UNIVERSE.index(symbol), (symbol, rate))
            for event_ms, symbol, rate in events
            if event_ms > ts
        ]
        if ts < inputs.end_ms:
            ordered_events.extend(
                (
                    max(intent.entry_eligible_ts_ms, intent.decision_ts_ms + latency_ms),
                    1,
                    UNIVERSE.index(intent.symbol),
                    intent,
                )
                for intent in tape.get(ts, [])
            )
        for event_ms, kind, _, payload in sorted(ordered_events, key=lambda item: item[:3]):
            if kind == 0:
                symbol, rate = payload
                account.settle(symbol, event_ms, rate, opens[symbol])
            else:
                intent = payload
                account.admit(intent, intent.decision_ts_ms + latency_ms, bars[intent.symbol], opens)
        account.mark(opens)
        account.adverse_envelope(bars)
        for bar in bars.values():
            account.exit_intrabar(bar)
        final_prices = {s: bar.close for s, bar in bars.items()}
        account.mark(final_prices)
    days = [
        datetime.fromtimestamp(ts / 1000, UTC).date().isoformat()
        for ts in range(inputs.start_ms, inputs.end_ms, 86_400_000)
    ]
    return account.report(final_prices, days), account
