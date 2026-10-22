"""Fact-only CURRENT chain inputs built from retained public captures.

No provider, venue, database, or background task is created here. The caller
supplies finite REST/collector receipts and owns their transport lifecycle. The
only book frames accepted by the native SIM remain frames produced by an
existing WebSocket recorder; a REST quote here is only a point-in-time feature
and observation quote.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from adaptive_replay import catalyst_policy_v1 as catalyst
from adaptive_replay.catalyst_hypothesis_v1 import CatalystPlan
from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_v3 import HypothesisObservation
from adaptive_replay.research_profile_v1 import ResearchProfile
from adaptive_replay.scenarios import ScenarioEvidence, ScenarioObservation
from kairos_core.contracts import (
    ClosedBarEventV1,
    MarketSnapshot,
    SentimentSignal,
    StrategicAllocation,
)
from kairos_core.contracts.base import datetime_from_unix_ms
from kairos_core.contracts.simulation import SimulationSessionV1
from kairos_quant.snapshot import SnapshotBuilder
from kairos_router.aggregation import SignalWindow, TextAggregate
from kairos_strategy.candles import Candle
from kairos_strategy.provenance import candle_payload

from .current_capture import (
    BAR_COUNT,
    BAR_MS,
    MARKET_SOURCE_ID,
    TEXT_COVERAGE_SCOPE,
    CapturedTextSnapshot,
    CurrentHistorySnapshot,
    FreshQuoteSnapshot,
)
from .current_capture import (
    UNIVERSE as CAPTURE_UNIVERSE,
)

UNIVERSE = tuple(sorted(CAPTURE_UNIVERSE))
PERIOD_MS = 5 * BAR_MS
MAX_QUANT_METRIC_AGE_MS = 15 * 60 * 1_000
MAX_OBSERVATIONS = 5
MAX_OBSERVATION_WINDOW_MS = 5 * 60 * 1_000
MARKET_EVIDENCE_SOURCE = "binance_um_klines_rest"
MACRO_ALLOCATION_SOURCE = "macro_strategist_allocation"
BAR_MESSAGE_SOURCE = "kairos-current-public-bars"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class CurrentInputRefused(ValueError):
    """Current native facts are missing, stale, malformed, or out of scope."""


@dataclass(frozen=True, slots=True)
class QuantMeasurement:
    """One actual measurement and its source clocks/hash, never an imputed value."""

    value: float
    source_id: str
    event_ms: int
    received_ms: int
    captured_ms: int
    raw_sha256: str
    coverage_scope: str
    window_start_ms: int | None = None
    window_end_ms: int | None = None
    complete: bool = True

    def __post_init__(self) -> None:
        _measurement(self)


@dataclass(frozen=True, slots=True)
class QuantMeasurements:
    """Actual Quant metrics for one symbol; liquidation zero is window-scoped."""

    symbol: str
    funding_rate: QuantMeasurement
    open_interest: QuantMeasurement
    oi_change_pct_1h: QuantMeasurement
    long_liquidations_usd: QuantMeasurement
    short_liquidations_usd: QuantMeasurement

    def __post_init__(self) -> None:
        if self.symbol not in UNIVERSE:
            raise CurrentInputRefused("QUANT_SYMBOL_OUTSIDE_FIXED_UNIVERSE")
        if any(
            type(value) is not QuantMeasurement
            for value in (
                self.funding_rate,
                self.open_interest,
                self.oi_change_pct_1h,
                self.long_liquidations_usd,
                self.short_liquidations_usd,
            )
        ):
            raise CurrentInputRefused("QUANT_MEASUREMENTS_MISSING_NO_ZERO_FILL")
        if self.funding_rate.coverage_scope != "LATEST_PUBLIC_FUNDING_RATE":
            raise CurrentInputRefused("FUNDING_COVERAGE_SCOPE_INVALID")
        if self.open_interest.coverage_scope != "LATEST_OPEN_INTEREST_VALUE":
            raise CurrentInputRefused("OPEN_INTEREST_COVERAGE_SCOPE_INVALID")
        if self.oi_change_pct_1h.coverage_scope != "COMPLETE_13_CONSECUTIVE_5M_OPEN_INTEREST_POINTS":
            raise CurrentInputRefused("OPEN_INTEREST_HISTORY_INCOMPLETE")
        for value in (self.long_liquidations_usd, self.short_liquidations_usd):
            if (
                value.coverage_scope != "CONTINUOUS_FORCE_ORDER_CAPTURE_WINDOW"
                or not value.complete
                or value.window_start_ms is None
                or value.window_end_ms is None
                or value.window_end_ms <= value.window_start_ms
                or value.window_end_ms > value.captured_ms
                or value.captured_ms - value.window_end_ms > 15_000
            ):
                raise CurrentInputRefused("FORCE_ORDER_WINDOW_NOT_PROVEN_COMPLETE")
        if (
            self.long_liquidations_usd.window_start_ms != self.short_liquidations_usd.window_start_ms
            or self.long_liquidations_usd.window_end_ms != self.short_liquidations_usd.window_end_ms
        ):
            raise CurrentInputRefused("FORCE_ORDER_WINDOW_MISMATCH")


@dataclass(frozen=True, slots=True)
class CurrentMarketSnapshot:
    symbol: str
    snapshot: MarketSnapshot
    quote: FreshQuoteSnapshot
    measurements: QuantMeasurements
    captured_ms: int
    coverage: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class CurrentCutInputs:
    """Frozen facts-only boundary consumed by the current native runner."""

    policy: catalyst.CatalystPolicy
    cells: tuple[catalyst.CatalystCell, ...]
    native_receipts: tuple[tuple[str, tuple[tuple[str, Any, int], ...]], ...]
    text_aggregates: tuple[tuple[str, TextAggregate], ...]
    market_snapshots: tuple[tuple[str, MarketSnapshot], ...]
    input_bars: tuple[tuple[str, tuple[ClosedBarEventV1, ...]], ...]
    directional_payloads: tuple[tuple[str, str], ...]
    requested_quantities: tuple[tuple[str, float], ...]
    simulation_session: SimulationSessionV1
    tape_id: str
    permitted_evidence_ids: tuple[tuple[str, tuple[str, ...]], ...]

    def __post_init__(self) -> None:
        if type(self.policy) is not catalyst.CatalystPolicy:
            raise CurrentInputRefused("CURRENT_POLICY_REQUIRED")
        self.policy.__post_init__()
        if type(self.cells) is not tuple or tuple(c.price.symbol for c in self.cells) != UNIVERSE:
            raise CurrentInputRefused("EXACT_FIVE_SYMBOL_CELL_ROSTER_REQUIRED")
        for cell in self.cells:
            cell.__post_init__()
        for name, values in (
            ("native_receipts", self.native_receipts),
            ("text_aggregates", self.text_aggregates),
            ("market_snapshots", self.market_snapshots),
            ("input_bars", self.input_bars),
            ("directional_payloads", self.directional_payloads),
            ("requested_quantities", self.requested_quantities),
            ("permitted_evidence_ids", self.permitted_evidence_ids),
        ):
            _five_symbol_pairs(name, values)
        if type(self.simulation_session) is not SimulationSessionV1:
            raise CurrentInputRefused("SIMULATION_SESSION_REQUIRED")
        self.simulation_session.__class__.model_validate(
            self.simulation_session.model_dump(mode="json"), strict=True
        )
        if self.simulation_session.tape_id != self.tape_id or not _IDENTIFIER.fullmatch(self.tape_id):
            raise CurrentInputRefused("SIMULATION_TAPE_ID_CONFLICT")
        for _symbol, aggregate in self.text_aggregates:
            if type(aggregate) is not TextAggregate:
                raise CurrentInputRefused("TEXT_AGGREGATE_TYPE_INVALID")
        for symbol, snapshot in self.market_snapshots:
            if type(snapshot) is not MarketSnapshot or snapshot.symbol != symbol:
                raise CurrentInputRefused("MARKET_SNAPSHOT_SYMBOL_OR_TYPE_INVALID")
        for symbol, bars in self.input_bars:
            if (
                type(bars) is not tuple
                or len(bars) != BAR_COUNT
                or any(type(bar) is not ClosedBarEventV1 or bar.symbol != symbol for bar in bars)
            ):
                raise CurrentInputRefused("EXACT_NATIVE_54H_BAR_PREFIX_REQUIRED")
        for symbol, payload in self.directional_payloads:
            parsed = _strict_json_object(payload)
            if parsed.get("symbol") != symbol or parsed.get("source_coverage_scope") != TEXT_COVERAGE_SCOPE:
                raise CurrentInputRefused("DIRECTIONAL_PAYLOAD_SOURCE_SCOPE_INVALID")
        for _symbol, quantity in self.requested_quantities:
            if type(quantity) not in {int, float} or not math.isfinite(quantity) or quantity <= 0:
                raise CurrentInputRefused("POSITIVE_EXPLICIT_SIM_QUANTITY_REQUIRED")
        for _symbol, evidence_ids in self.permitted_evidence_ids:
            if type(evidence_ids) is not tuple or tuple(sorted(set(evidence_ids))) != evidence_ids:
                raise CurrentInputRefused("CANONICAL_EVIDENCE_ID_ROSTER_REQUIRED")
            if any(type(value) is not str or not _SHA256.fullmatch(value) for value in evidence_ids):
                raise CurrentInputRefused("INVALID_PERMITTED_EVIDENCE_ID")


@dataclass(frozen=True, slots=True)
class CapturedClosedBar:
    """One actual observed post-plan closed minute with its original raw bytes."""

    candle: Candle
    raw_payload: bytes
    source_id: str
    event_ms: int
    received_ms: int
    captured_ms: int
    raw_sha256: str
    continuity: str = "CONTIGUOUS_CAPTURED_BAR"

    def __post_init__(self) -> None:
        if type(self.candle) is not Candle or type(self.raw_payload) is not bytes or not self.raw_payload:
            raise CurrentInputRefused("ORIGINAL_CLOSED_BAR_BYTES_REQUIRED")
        if (
            not _IDENTIFIER.fullmatch(self.source_id)
            or self.continuity != "CONTIGUOUS_CAPTURED_BAR"
            or self.event_ms != self.candle.close_time_ms
            or not self.event_ms < self.received_ms <= self.captured_ms
            or hashlib.sha256(self.raw_payload).hexdigest() != self.raw_sha256
        ):
            raise CurrentInputRefused("CLOSED_BAR_RAW_SOURCE_CLOCK_OR_HASH_INVALID")


class ClosedBarSource(Protocol):
    async def wait_closed_bar(
        self, symbol: str, after_close_ms: int, *, timeout_s: float
    ) -> CapturedClosedBar | None: ...


class QuoteSource(Protocol):
    async def fresh_quote(self, symbol: str) -> FreshQuoteSnapshot: ...

    def quote_snapshot_for(self, entry_quote: Any) -> FreshQuoteSnapshot | None: ...


class CurrentObservationSource:
    """Bounded first-trigger observer over an injected actual closed-bar stream.

    It constructs only causal minute observations and point quotes. It never
    manufactures a book frame. A separate native RiskFrameSource must supply
    actual recorded V1/V2 WebSocket frames for SIM risk admission.
    """

    def __init__(
        self,
        bar_source: ClosedBarSource,
        quote_source: QuoteSource,
        *,
        clock_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        max_observations: int = MAX_OBSERVATIONS,
        max_wait_ms: int = MAX_OBSERVATION_WINDOW_MS,
    ) -> None:
        if not 1 <= max_observations <= MAX_OBSERVATIONS or not 1 <= max_wait_ms <= MAX_OBSERVATION_WINDOW_MS:
            raise ValueError("current observation bounds exceed 15 minutes / 15 bars")
        self.bar_source, self.quote_source, self.clock_ms = bar_source, quote_source, clock_ms
        self.max_observations, self.max_wait_ms = max_observations, max_wait_ms
        self.last_status = "NOT_STARTED"
        self.status_by_plan: dict[str, str] = {}
        self._bars_by_symbol: dict[str, dict[int, CapturedClosedBar]] = {}
        self._symbol_locks: dict[str, asyncio.Lock] = {}

    async def _next_closed_bar(
        self, symbol: str, after_close_ms: int, *, timeout_s: float
    ) -> CapturedClosedBar | None:
        """Read shared immutable first-receipt facts; never pop/ack source bars."""

        lock = self._symbol_locks.setdefault(symbol, asyncio.Lock())
        async with lock:
            cache = self._bars_by_symbol.setdefault(symbol, {})
            available = [close_ms for close_ms in cache if close_ms > after_close_ms]
            if available:
                return cache[min(available)]
            captured = await self.bar_source.wait_closed_bar(symbol, after_close_ms, timeout_s=timeout_s)
            if captured is None:
                return None
            captured.__post_init__()
            prior = cache.get(captured.event_ms)
            if prior is not None and prior != captured:
                raise CurrentInputRefused("SHARED_CLOSED_BAR_RECEIPT_CONFLICT")
            cache[captured.event_ms] = captured
            return captured

    def quote_snapshot_for(self, entry_quote: Any) -> FreshQuoteSnapshot | None:
        """Expose only the exact retained snapshot backing an observed quote."""

        lookup = getattr(self.quote_source, "quote_snapshot_for", None)
        if not callable(lookup):
            return None
        snapshot = lookup(entry_quote)
        if snapshot is None:
            return None
        if (
            type(snapshot) is not FreshQuoteSnapshot
            or snapshot.entry_quote != entry_quote
            or snapshot.symbol != getattr(entry_quote, "symbol", None)
        ):
            return None
        return snapshot

    async def wait_first_closed_trigger(
        self,
        plan: CatalystPlan,
        *,
        original_bars: tuple[ClosedBarEventV1, ...],
        original_quote: FreshQuoteSnapshot,
    ) -> tuple[HypothesisObservation, ...]:
        from adaptive_replay.catalyst_hypothesis_v1 import evaluate_hypothesis

        if (
            type(plan) is not CatalystPlan
            or type(original_bars) is not tuple
            or len(original_bars) < BAR_COUNT
            or type(original_quote) is not FreshQuoteSnapshot
            or original_quote.symbol != plan.template.symbol
        ):
            self.last_status = "ORIGINAL_PLAN_INPUTS_INVALID"
            return ()
        symbol = plan.template.symbol
        # Origin is the frozen price-cut boundary. Actual proposal completion may
        # be later within that first minute; it never shifts or rounds the bar
        # sequence to pretend earlier coverage was observed.
        expected_open = plan.origin_cut_ms
        last_close = plan.origin_cut_ms - 1
        if not plan.origin_cut_ms <= plan.created_ms < plan.origin_cut_ms + BAR_MS:
            self.last_status = "CREATION_AFTER_FIRST_POST_ORIGIN_MINUTE_STARTED"
            self.status_by_plan[plan.sha256] = self.last_status
            return ()
        deadline = min(plan.valid_until_ms, plan.origin_cut_ms + self.max_wait_ms)
        observations: list[HypothesisObservation] = []
        # Preserve original context evidence, replacing only the creation MARKET
        # anchor with each actual closed-bar receipt so the market hash binds the
        # current observation. No old availability clock is rewritten.
        context_sources = tuple(e for e in plan.creation_evidence if e.kind != "MARKET")
        market_source_id = next(
            (source_id for kind, source_id in plan.required_sources if kind == "MARKET"),
            None,
        )
        if market_source_id is None:
            self.last_status = "PLAN_MARKET_SOURCE_MISSING"
            self.status_by_plan[plan.sha256] = self.last_status
            return ()
        try:
            for _ in range(self.max_observations):
                now_ms = self.clock_ms()
                remaining_ms = deadline - now_ms
                if remaining_ms <= 0:
                    self.last_status = "NOT_REACHED_WINDOW"
                    self.status_by_plan[plan.sha256] = self.last_status
                    return tuple(observations)
                captured = await self._next_closed_bar(
                    symbol, last_close, timeout_s=min(60.0, remaining_ms / 1_000.0)
                )
                if captured is None:
                    self.last_status = "CLOSED_BAR_UNAVAILABLE"
                    self.status_by_plan[plan.sha256] = self.last_status
                    return tuple(observations)
                captured.__post_init__()
                candle = captured.candle
                if (
                    candle.symbol != symbol
                    or candle.timeframe != "1m"
                    or candle.open_time_ms != expected_open
                    or candle.close_time_ms != expected_open + BAR_MS - 1
                    or captured.received_ms > deadline
                    or captured.captured_ms > deadline
                ):
                    self.last_status = "CLOSED_BAR_GAP_OR_LATE"
                    self.status_by_plan[plan.sha256] = self.last_status
                    return tuple(observations)
                try:
                    quote_snapshot = await self.quote_source.fresh_quote(symbol)
                    quote = quote_snapshot.entry_quote
                    if (
                        quote_snapshot.symbol != symbol
                        or quote.event_ms <= candle.close_time_ms
                        or quote_snapshot.received_ms > deadline
                        or quote_snapshot.captured_ms > deadline
                    ):
                        raise CurrentInputRefused("TRIGGER_QUOTE_CAUSALITY_INVALID")
                except Exception:
                    quote = None
                    quote_snapshot = None
                observed_ms = max(
                    captured.captured_ms,
                    quote_snapshot.captured_ms if quote_snapshot is not None else captured.captured_ms,
                    self.clock_ms(),
                )
                if observed_ms > deadline:
                    self.last_status = "OBSERVATION_CAPTURED_AFTER_WINDOW"
                    self.status_by_plan[plan.sha256] = self.last_status
                    return tuple(observations)
                market_source = ScenarioEvidence(
                    market_source_id,
                    "MARKET",
                    symbol,
                    digest(candle_payload(candle)),
                    candle.close_time_ms,
                    captured.received_ms,
                    captured.captured_ms,
                    MAX_QUANT_METRIC_AGE_MS,
                )
                sources = tuple(
                    sorted((*context_sources, market_source), key=lambda e: (e.kind, e.source_id))
                )
                observation = HypothesisObservation(ScenarioObservation(candle, observed_ms, sources), quote)
                observations.append(observation)
                results = evaluate_hypothesis(plan, tuple(observations))
                final = results[-1]
                if final.state != "WAITING_TRIGGER":
                    self.last_status = final.reason
                    self.status_by_plan[plan.sha256] = self.last_status
                    return tuple(observations)
                expected_open += BAR_MS
                last_close = candle.close_time_ms
            self.last_status = "OBSERVATION_LIMIT_REACHED"
            self.status_by_plan[plan.sha256] = "NOT_REACHED_WINDOW"
            return tuple(observations)
        except (TimeoutError, OSError, CurrentInputRefused, ValueError):
            self.last_status = "SOURCE_UNAVAILABLE"
            self.status_by_plan[plan.sha256] = self.last_status
            return tuple(observations)


def build_current_cut_inputs(
    *,
    config: Any,
    history: CurrentHistorySnapshot,
    text_snapshot: CapturedTextSnapshot,
    quotes: tuple[FreshQuoteSnapshot, ...],
    signals: tuple[SentimentSignal, ...],
    allocation: StrategicAllocation,
    allocation_received_ms: int,
    signal_received_ms: int,
    quant_measurements_by_symbol: tuple[tuple[str, QuantMeasurements], ...],
    simulation_session: SimulationSessionV1,
    tape_id: str,
    requested_quantities: tuple[tuple[str, float], ...],
) -> CurrentCutInputs:
    """Build the exact five-cell current fact graph; no candidate is precomputed."""

    cut_ms = config.cut_ms
    if type(cut_ms) is not int or cut_ms % PERIOD_MS:
        raise CurrentInputRefused("CURRENT_DECISION_CUT_MUST_BE_FIVE_MINUTE_BOUNDARY")
    if (
        type(history) is not CurrentHistorySnapshot
        or history.cut_ms != cut_ms
        or tuple(history.bars_by_symbol) not in (UNIVERSE, CAPTURE_UNIVERSE)
        or any(len(history.bars_by_symbol[symbol]) != BAR_COUNT for symbol in UNIVERSE)
        or any(
            any(
                bar.symbol != symbol
                or bar.timeframe != "1m"
                or bar.open_time_ms != history.bars_by_symbol[symbol][0].open_time_ms + index * BAR_MS
                or bar.close_time_ms != bar.open_time_ms + BAR_MS - 1
                for index, bar in enumerate(history.bars_by_symbol[symbol])
            )
            for symbol in UNIVERSE
        )
    ):
        raise CurrentInputRefused("EXACT_CURRENT_FIVE_SYMBOL_HISTORY_REQUIRED")
    if type(text_snapshot) is not CapturedTextSnapshot or text_snapshot.coverage_scope != TEXT_COVERAGE_SCOPE:
        raise CurrentInputRefused("ONE_COMPLETE_CAPTURED_RSS_SNAPSHOT_REQUIRED")
    if type(quotes) is not tuple or tuple(q.symbol for q in quotes) != CAPTURE_UNIVERSE:
        raise CurrentInputRefused("FIVE_SYMBOL_POINT_QUOTE_ROSTER_REQUIRED")
    if type(allocation) is not StrategicAllocation:
        raise CurrentInputRefused("ACTUAL_MACRO_STRATEGIST_ALLOCATION_REQUIRED")
    allocation = StrategicAllocation.model_validate(allocation.model_dump(mode="json"), strict=True)
    allocation_ms = _datetime_ms(allocation.produced_at)
    _clock_pair(allocation_ms, allocation_received_ms, "MACRO_ALLOCATION")
    _clock_pair(signal_received_ms, signal_received_ms, "TEXT_SIGNAL")
    if type(signals) is not tuple or len(signals) > 500:
        raise CurrentInputRefused("BOUNDED_TEXT_SIGNAL_TUPLE_REQUIRED")
    for signal in signals:
        if type(signal) is not SentimentSignal:
            raise CurrentInputRefused("TYPED_TEXT_SCOUT_SIGNALS_REQUIRED")
        SentimentSignal.model_validate(signal.model_dump(mode="json"), strict=True)
        if _datetime_ms(signal.produced_at) > signal_received_ms:
            raise CurrentInputRefused("TEXT_SIGNAL_PRECEDES_LOCAL_RECEIPT")
    if type(quant_measurements_by_symbol) is not tuple:
        raise CurrentInputRefused("EXACT_FIVE_SYMBOL_QUANT_MEASUREMENTS_REQUIRED")
    measurements = dict(quant_measurements_by_symbol)
    if (
        type(quant_measurements_by_symbol) is not tuple
        or tuple(symbol for symbol, _ in quant_measurements_by_symbol) != UNIVERSE
        or any(
            type(value) is not QuantMeasurements or value.symbol != symbol
            for symbol, value in quant_measurements_by_symbol
        )
    ):
        raise CurrentInputRefused("EXACT_FIVE_SYMBOL_QUANT_MEASUREMENTS_REQUIRED")
    if (
        type(requested_quantities) is not tuple
        or tuple(symbol for symbol, _ in requested_quantities) != UNIVERSE
    ):
        raise CurrentInputRefused("EXACT_FIVE_SYMBOL_SIM_QUANTITY_ROSTER_REQUIRED")
    if type(simulation_session) is not SimulationSessionV1 or simulation_session.tape_id != tape_id:
        raise CurrentInputRefused("CURRENT_SIMULATION_SESSION_TAPE_BINDING_REQUIRED")

    text_source_id = text_snapshot.source_name
    if type(text_source_id) is not str or not _IDENTIFIER.fullmatch(text_source_id):
        raise CurrentInputRefused("CAPTURED_TEXT_SOURCE_ID_INVALID")
    source_set_sha = config.source_set_sha256
    model_sha = config.model_config_sha256
    start_ms = cut_ms
    end_ms = min(config.capture_end_ms + 15 * PERIOD_MS, cut_ms + 15 * PERIOD_MS)
    end_ms = max(cut_ms + PERIOD_MS, end_ms - end_ms % PERIOD_MS)
    profile = catalyst.CatalystPolicy(
        ResearchProfile(
            declared_ms=config.capture_start_ms,
            start_ms=start_ms,
            end_ms=end_ms,
            source_set_sha256=source_set_sha,
            model_config_sha256=model_sha,
            quote_source_id=MARKET_SOURCE_ID,
            required_sources=tuple(
                sorted(
                    (
                        ("MACRO", MACRO_ALLOCATION_SOURCE),
                        ("MARKET", MARKET_EVIDENCE_SOURCE),
                        ("NEWS", text_source_id),
                    )
                )
            ),
            evidence_kind="CALLER_ATTESTED_POINT_IN_TIME",
        )
    )
    quote_map = {quote.symbol: quote for quote in quotes}
    market_by_symbol: dict[str, CurrentMarketSnapshot] = {}
    snapshots: list[tuple[str, MarketSnapshot]] = []
    native_receipts: list[tuple[str, tuple[tuple[str, Any, int], ...]]] = []
    text_aggregates: list[tuple[str, TextAggregate]] = []
    input_bars: list[tuple[str, tuple[ClosedBarEventV1, ...]]] = []
    directional: list[tuple[str, str]] = []
    permitted: list[tuple[str, tuple[str, ...]]] = []
    cells: list[catalyst.CatalystCell] = []
    allocation_sha = _sha_model(allocation)
    for symbol in UNIVERSE:
        bars = tuple(history.bars_by_symbol[symbol])
        quote = quote_map[symbol]
        metrics = measurements[symbol]
        market_input = build_market_snapshot(symbol, bars, quote, metrics)
        market_by_symbol[symbol] = market_input
        snapshots.append((symbol, market_input.snapshot))

        latest_page = max(
            (page for page in history.page_receipts if page.symbol == symbol),
            key=lambda page: page.page,
        )
        anchor = bars[-1]
        market_evidence = ScenarioEvidence(
            MARKET_EVIDENCE_SOURCE,
            "MARKET",
            symbol,
            digest(candle_payload(anchor)),
            anchor.close_time_ms,
            latest_page.received_ms,
            latest_page.persisted_ms,
            90_000,
        )
        news_evidence = ScenarioEvidence(
            text_source_id,
            "NEWS",
            symbol,
            text_snapshot.raw_sha256,
            max(
                (event.version.published_upper_ms for event in text_snapshot.events),
                default=text_snapshot.received_ms,
            ),
            text_snapshot.received_ms,
            text_snapshot.persisted_ms,
            30 * 60 * 1_000,
        )
        macro_evidence = ScenarioEvidence(
            MACRO_ALLOCATION_SOURCE,
            "MACRO",
            symbol,
            allocation_sha,
            allocation_ms,
            allocation_received_ms,
            allocation_received_ms,
            30 * 60 * 1_000,
        )
        sources = tuple(
            sorted((market_evidence, news_evidence, macro_evidence), key=lambda e: (e.kind, e.source_id))
        )
        observed_ms = max(
            cut_ms,
            history.captured_ms,
            text_snapshot.persisted_ms,
            allocation_received_ms,
            quote.captured_ms,
            market_input.captured_ms,
        )
        price = catalyst.control.PriceCell(
            cut_ms=cut_ms,
            observed_ms=observed_ms,
            symbol=symbol,
            rows=bars,
            sources=sources,
            budget_state="AVAILABLE",
        )
        symbol_events = tuple(
            sorted(
                (
                    event
                    for event in text_snapshot.events
                    if symbol in event.version.symbols and event.due_ms <= cut_ms
                ),
                key=lambda event: event.sha256,
            )
        )
        # This is KNOWN only as the complete parsed roster of the exact retained
        # RSS document. It is not interval-wide or global news completeness.
        # Empty active-arm roster is correct for a fresh isolated SIM session;
        # this field denotes already-active positions/plans, not enabled tests.
        cells.append(catalyst.CatalystCell(price, "KNOWN", symbol_events, ()))

        matching_signals = tuple(signal for signal in signals if signal.topic.strip().upper() == symbol)
        window = SignalWindow(sentiment_ttl_s=600.0, deadband=0.25, min_confidence=0.25, max_evidence=5)
        for signal in matching_signals:
            window.add_sentiment(
                symbol,
                message_id=signal.message_id,
                produced_at=signal.produced_at,
                sentiment=signal.sentiment,
                impact=signal.impact,
                confidence=signal.confidence,
            )
        aggregate = window.aggregate(symbol, as_of=datetime.fromtimestamp(signal_received_ms / 1_000, tz=UTC))
        text_aggregates.append((symbol, aggregate))

        closed_events = tuple(_to_closed_bar(bar, received_ms=latest_page.received_ms) for bar in bars)
        input_bars.append((symbol, closed_events))
        receipt_rows: list[tuple[str, Any, int]] = [
            ("market", market_input.snapshot, market_input.captured_ms),
            ("macro", allocation, allocation_received_ms),
            *(("closed_bars", bar, latest_page.received_ms) for bar in closed_events[-60:]),
            *(("text", signal, signal_received_ms) for signal in matching_signals),
        ]
        receipt_rows.sort(key=lambda row: (row[0], getattr(row[1], "message_id", "")))
        native_receipts.append((symbol, tuple(receipt_rows)))

        news_items = [
            {
                "event_id": event.event_id,
                "source_id": event.source_id,
                "content_ref": event.version.sha256,
                "published_ms": event.version.published_upper_ms,
                "received_ms": event.first_received_ms,
                "headline": json.loads(event.version.payload_json)["headline"],
                "body": json.loads(event.version.payload_json)["body"],
                "url": event.version.url,
            }
            for event in text_snapshot.events
            if symbol in event.version.symbols
        ]
        payload = {
            "schema": "kairos.current-directional-input.v1",
            "symbol": symbol,
            "cut_ms": cut_ms,
            "history_sha256": digest([candle_payload(bar) for bar in bars]),
            "market_prices": _directional_prices(bars),
            "market_snapshot": market_input.snapshot.model_dump(mode="json"),
            "text_aggregate": _plain_aggregate(aggregate),
            "news": news_items,
            "macro_allocation": allocation.model_dump(mode="json"),
            "source_coverage_scope": TEXT_COVERAGE_SCOPE,
            "source_coverage_limits": {
                "news_interval_complete": False,
                "all_world_news_complete": False,
                "publisher_authenticity_verified": False,
                "macro_is_external_measurement": False,
                "macro_kind": "MODEL_OUTPUT_ALLOCATION",
            },
            "assessment_schema": _directional_schema(),
            "assessment_contract": {
                "directional_only": True,
                "no_candidate_geometry": True,
                "no_price_or_quantity_proposal": True,
                "evidence_ids": "unique SHA-256 content references in this payload only",
            },
            "evidence_ids": sorted({*(item["content_ref"] for item in news_items), allocation_sha}),
        }
        payload_json = _canonical_json(payload)
        if len(payload_json.encode("utf-8")) > 100_000:
            raise CurrentInputRefused("DIRECTIONAL_INPUT_SIZE_LIMIT_EXCEEDED")
        directional.append((symbol, payload_json))
        permitted.append(
            (symbol, tuple(sorted({*(item["content_ref"] for item in news_items), allocation_sha})))
        )

    result = CurrentCutInputs(
        profile,
        tuple(cells),
        tuple(native_receipts),
        tuple(text_aggregates),
        tuple(snapshots),
        tuple(input_bars),
        tuple(directional),
        requested_quantities,
        simulation_session,
        tape_id,
        tuple(permitted),
    )
    return result


def build_market_snapshot(
    symbol: str,
    bars: tuple[Candle, ...],
    quote: FreshQuoteSnapshot,
    measurements: QuantMeasurements,
) -> CurrentMarketSnapshot:
    """Use existing Quant SnapshotBuilder with exact bars, quote and actual metrics."""

    if symbol not in UNIVERSE or type(quote) is not FreshQuoteSnapshot or quote.symbol != symbol:
        raise CurrentInputRefused("CURRENT_QUOTE_SYMBOL_MISMATCH")
    if type(measurements) is not QuantMeasurements or measurements.symbol != symbol:
        raise CurrentInputRefused("CURRENT_QUANT_METRICS_REQUIRED")
    if type(bars) is not tuple or len(bars) != BAR_COUNT:
        raise CurrentInputRefused("EXACT_54H_BAR_HISTORY_REQUIRED")
    latest = bars[-1]
    if (
        latest.symbol != symbol
        or latest.close_time_ms + 1 != quote.entry_quote.event_ms
        and quote.entry_quote.event_ms - latest.close_time_ms > 24 * 60 * 60_000
    ):
        # The current point quote is not required to follow the latest candle by
        # only 1ms, but it may not be older than the retained 54h sample window.
        if quote.entry_quote.event_ms < latest.close_time_ms:
            raise CurrentInputRefused("CURRENT_QUOTE_PREDATES_BAR_HISTORY")
    _fresh_measurements(measurements, quote.received_ms)
    bids, asks = _depth_levels(quote.raw_body)
    builder = SnapshotBuilder(source="kairos-current-quant-snapshot", window=200, depth_levels=5)
    for candle in bars[-200:]:
        if candle.symbol != symbol:
            raise CurrentInputRefused("MIXED_SYMBOL_BAR_HISTORY")
        builder.push_candle(symbol, high=candle.high, low=candle.low, close=candle.close)
    captured_ms = max(
        quote.captured_ms,
        measurements.funding_rate.captured_ms,
        measurements.open_interest.captured_ms,
        measurements.oi_change_pct_1h.captured_ms,
        measurements.long_liquidations_usd.captured_ms,
        measurements.short_liquidations_usd.captured_ms,
    )
    snapshot = builder.build(
        symbol,
        bids=bids,
        asks=asks,
        funding_rate=measurements.funding_rate.value,
        open_interest=measurements.open_interest.value,
        oi_change_pct_1h=measurements.oi_change_pct_1h.value,
        long_liq_usd=measurements.long_liquidations_usd.value,
        short_liq_usd=measurements.short_liquidations_usd.value,
        volume_usd=latest.quote_volume,
    )
    # SnapshotBuilder already returned a validated MarketSnapshot.  Rebuilding
    # from a dump under strict validation would reject StrEnum values after
    # serialization (e.g. quant_bias="FLAT").  Preserve the typed object and
    # update only the capture-time envelope field with a typed datetime.
    snapshot = snapshot.model_copy(update={"produced_at": datetime_from_unix_ms(captured_ms)})
    coverage = tuple(
        sorted(
            (
                ("FUNDING", measurements.funding_rate.coverage_scope),
                ("OPEN_INTEREST", measurements.open_interest.coverage_scope),
                ("OPEN_INTEREST_CHANGE_1H", measurements.oi_change_pct_1h.coverage_scope),
                ("LONG_LIQUIDATIONS", measurements.long_liquidations_usd.coverage_scope),
                ("SHORT_LIQUIDATIONS", measurements.short_liquidations_usd.coverage_scope),
                ("VOLUME_USD", "LATEST_CLOSED_1M_QUOTE_VOLUME"),
                ("BOOK", "ONE_SHOT_REST_DEPTH_SNAPSHOT"),
            )
        )
    )
    return CurrentMarketSnapshot(symbol, snapshot, quote, measurements, captured_ms, coverage)


def _measurement(value: QuantMeasurement) -> None:
    if (
        type(value.value) not in {int, float}
        or not math.isfinite(value.value)
        or not _IDENTIFIER.fullmatch(value.source_id)
        or any(
            type(clock) is not int or clock < 0
            for clock in (value.event_ms, value.received_ms, value.captured_ms)
        )
        or not value.event_ms <= value.received_ms <= value.captured_ms
        or not _SHA256.fullmatch(value.raw_sha256)
        or type(value.coverage_scope) is not str
        or not value.coverage_scope
        or type(value.complete) is not bool
    ):
        raise CurrentInputRefused("QUANT_MEASUREMENT_PROVENANCE_INVALID")
    if value.window_start_ms is not None or value.window_end_ms is not None:
        if (
            type(value.window_start_ms) is not int
            or type(value.window_end_ms) is not int
            or value.window_start_ms < 0
            or value.window_end_ms <= value.window_start_ms
            or value.window_end_ms > value.captured_ms
        ):
            raise CurrentInputRefused("QUANT_MEASUREMENT_WINDOW_INVALID")


def _fresh_measurements(measurements: QuantMeasurements, quote_received_ms: int) -> None:
    if type(quote_received_ms) is not int or quote_received_ms < 0:
        raise CurrentInputRefused("QUOTE_LOCAL_RECEIVE_CLOCK_INVALID")
    for metric in (
        measurements.funding_rate,
        measurements.open_interest,
        measurements.oi_change_pct_1h,
        measurements.long_liquidations_usd,
        measurements.short_liquidations_usd,
    ):
        if metric.captured_ms > quote_received_ms + MAX_QUANT_METRIC_AGE_MS:
            raise CurrentInputRefused("QUANT_METRIC_CLOCK_AFTER_QUOTE")
        if quote_received_ms - metric.event_ms > MAX_QUANT_METRIC_AGE_MS:
            raise CurrentInputRefused("QUANT_METRIC_STALE")


def _depth_levels(body: bytes) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    try:
        value = json.loads(body.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise CurrentInputRefused("RAW_DEPTH_JSON_INVALID") from None
    if type(value) is not dict or type(value.get("bids")) is not list or type(value.get("asks")) is not list:
        raise CurrentInputRefused("RAW_DEPTH_SCHEMA_INVALID")
    sides = []
    for key in ("bids", "asks"):
        raw_rows = value[key]
        if not 1 <= len(raw_rows) <= 100:
            raise CurrentInputRefused("RAW_DEPTH_LEVEL_COUNT_INVALID")
        rows: list[tuple[float, float]] = []
        for row in raw_rows:
            if type(row) is not list or len(row) != 2 or any(type(v) is not str for v in row):
                raise CurrentInputRefused("RAW_DEPTH_LEVEL_INVALID")
            try:
                price, quantity = float(Decimal(row[0])), float(Decimal(row[1]))
            except (InvalidOperation, ValueError, OverflowError):
                raise CurrentInputRefused("RAW_DEPTH_LEVEL_INVALID") from None
            if not math.isfinite(price) or not math.isfinite(quantity) or price <= 0 or quantity <= 0:
                raise CurrentInputRefused("RAW_DEPTH_LEVEL_INVALID")
            rows.append((price, quantity))
        sides.append(rows)
    if sides[0][0][0] >= sides[1][0][0]:
        raise CurrentInputRefused("RAW_DEPTH_CROSSED")
    return sides[0], sides[1]


def _to_closed_bar(bar: Candle, *, received_ms: int) -> ClosedBarEventV1:
    return ClosedBarEventV1(
        source=BAR_MESSAGE_SOURCE,
        produced_at=datetime_from_unix_ms(received_ms),
        symbol=bar.symbol,
        timeframe=bar.timeframe,
        open_time_ms=bar.open_time_ms,
        close_time_ms=bar.close_time_ms,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        base_volume=bar.volume,
        quote_volume=bar.quote_volume,
        taker_buy_base_volume=bar.taker_buy_volume,
        taker_buy_quote_volume=bar.taker_buy_quote_volume,
    )


def _directional_prices(bars: tuple[Candle, ...]) -> dict[str, list[dict[str, int | float]]]:
    def aggregate(rows: tuple[Candle, ...], frame_ms: int) -> list[dict[str, int | float]]:
        output: list[dict[str, int | float]] = []
        for index in range(0, len(rows), frame_ms // BAR_MS):
            group = rows[index : index + frame_ms // BAR_MS]
            if len(group) != frame_ms // BAR_MS:
                continue
            if any(
                row.open_time_ms != group[0].open_time_ms + offset * BAR_MS
                for offset, row in enumerate(group)
            ):
                continue
            output.append(
                {
                    "open_time_ms": group[0].open_time_ms,
                    "close_time_ms": group[-1].close_time_ms,
                    "open": group[0].open,
                    "high": max(row.high for row in group),
                    "low": min(row.low for row in group),
                    "close": group[-1].close,
                }
            )
        return output

    return {
        "1m": [_bar_prompt(row) for row in bars[-30:]],
        "5m": aggregate(bars[-120:], 5 * BAR_MS)[-24:],
        "15m": aggregate(bars[-240:], 15 * BAR_MS)[-16:],
        "1h": aggregate(bars[-3_240:], 60 * BAR_MS)[-54:],
    }


def _bar_prompt(bar: Candle) -> dict[str, int | float]:
    return {
        "open_time_ms": bar.open_time_ms,
        "close_time_ms": bar.close_time_ms,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
    }


def _plain_aggregate(aggregate: TextAggregate) -> dict[str, Any]:
    return {
        "bias": aggregate.bias.value,
        "score": aggregate.score,
        "confidence": aggregate.confidence,
        "sentiment_ids": list(aggregate.sentiment_ids),
        "has_relevant_evidence": aggregate.has_relevant_evidence,
    }


def _directional_schema() -> dict[str, Any]:
    from adaptive_replay.complex_assessment import DirectionalAssessment

    return DirectionalAssessment.model_json_schema()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _strict_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (TypeError, ValueError, json.JSONDecodeError, RecursionError):
        raise CurrentInputRefused("DIRECTIONAL_PAYLOAD_INVALID_JSON") from None
    if type(parsed) is not dict or _canonical_json(parsed) != value:
        raise CurrentInputRefused("DIRECTIONAL_PAYLOAD_NOT_CANONICAL")
    return parsed


def _datetime_ms(value: datetime) -> int:
    if value.utcoffset() is None:
        raise CurrentInputRefused("NAIVE_KAIROS_TIMESTAMP")
    return int(value.astimezone(UTC).timestamp() * 1_000)


def _sha_model(value: Any) -> str:
    model = value.model_dump(mode="json")
    return hashlib.sha256(_canonical_json(model).encode("utf-8")).hexdigest()


def _clock_pair(first: int, second: int, name: str) -> None:
    if type(first) is not int or type(second) is not int or first < 0 or second < first:
        raise CurrentInputRefused(f"{name}_CLOCK_ORDER_INVALID")


def _five_symbol_pairs(name: str, value: Any) -> None:
    if type(value) is not tuple or tuple(row[0] for row in value) != UNIVERSE:
        raise CurrentInputRefused(f"{name.upper()}_EXACT_FIVE_SYMBOL_ROSTER_REQUIRED")
