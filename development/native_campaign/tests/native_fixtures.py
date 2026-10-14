"""Bounded synthetic inputs for the native PostgreSQL engineering target.

Nothing in this module reads a credential, queries a database, calls a provider,
or represents observed market/news/model evidence. The integration test writes
these explicit fixtures through the real SIM and campaign repositories.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime

from kairos_core import canonical_sha256
from kairos_core.config import DEFAULT_TRADING_SYMBOLS
from kairos_core.contracts import (
    RecordedBookLevelV1,
    RecordedTopNBookFrameV1,
    SimulationAssumptionsV1,
    SimulationSessionV1,
    SimulationStrategyRefV1,
)
from kairos_strategy.campaign import CausalStrategyEvaluator
from kairos_strategy.candles import Candle
from kairos_strategy.runtime import candle_to_closed_bar, closed_bar_to_candle
from kairos_strategy.sleeves import RangeMeanReversionConfig

SYMBOLS = tuple(DEFAULT_TRADING_SYMBOLS)
_SOURCE_T0 = 1_700_000_000_000


def projector_fixture():
    """Build the actual, immutable router-context projector and policy."""
    from kairos_llm.causal_campaign import (
        CausalReviewContextProjector,
        CausalRouterContextPolicyV1,
    )

    return CausalReviewContextProjector(
        CausalRouterContextPolicyV1(
            sentiment_ttl_s=600.0,
            deadband=0.25,
            minimum_confidence=0.25,
            maximum_evidence=5,
            trading_symbols=SYMBOLS,
        )
    )


def parity_history(now_ms: int, *, quiet: bool, symbol: str):
    """260 canonical minute bars, preserving the existing 200-bar parity tail."""
    closes = [100.0 + (index % 2) * 0.2 for index in range(40)]
    closes[-2:] = [96.0, 98.0]
    tail = []
    anchor = now_ms // 300_000 * 300_000
    delta = anchor - _SOURCE_T0
    for five_minute_bar, close_value in enumerate(closes):
        for minute in range(5):
            index = five_minute_bar * 5 + minute
            close = 100.0 if quiet else close_value
            tail.append(
                candle_to_closed_bar(
                    Candle(
                        symbol=symbol,
                        timeframe="1m",
                        open_time_ms=_SOURCE_T0 - (200 - index) * 60_000 + delta,
                        close_time_ms=_SOURCE_T0 - (199 - index) * 60_000 - 1 + delta,
                        open=close,
                        high=close + 0.2,
                        low=close - 0.2,
                        close=close,
                        volume=10.0,
                        quote_volume=10.0 * close,
                        taker_buy_volume=5.0,
                        taker_buy_quote_volume=5.0 * close,
                    )
                )
            )
    # The first 60 bars provide complete hourly warmup at every five-minute
    # boundary; values are copied unchanged from the parity tail.
    earlier = tuple(
        candle_to_closed_bar(
            replace(
                closed_bar_to_candle(bar),
                open_time_ms=bar.open_time_ms - 3_600_000,
                close_time_ms=bar.close_time_ms - 3_600_000,
            )
        )
        for bar in tail[:60]
    )
    return earlier + tuple(tail)


def strategy_evaluator(resolver, campaign_id: str, schedule_digest: str, protocol_digest: str):
    """The real pinned strategy adapter with the unchanged parity config."""
    return CausalStrategyEvaluator(
        strategy_id="range_mean_reversion_v1",
        strategy_revision="1",
        config=RangeMeanReversionConfig(
            vwap_lookback_bars=3,
            atr_period=2,
            regime_lookback_hours=2,
            maximum_regime_efficiency=1,
            maximum_abs_hourly_slope=1,
            band_atr_multiple=0.5,
            stop_atr_multiple=1,
            max_hold_bars=6,
        ),
        minimum_window_bars=200,
        bar_window_resolver=resolver,
        campaign_id=campaign_id,
        schedule_digest=schedule_digest,
        candidate_protocol_digest=protocol_digest,
    )


def simulation_assumptions() -> SimulationAssumptionsV1:
    return SimulationAssumptionsV1(
        latency_ms=25,
        # The target runs several independent sub-second synthetic cases on
        # one sealed tape, so the bounded fixture book remains usable for the
        # full test window without claiming venue freshness.
        maximum_book_age_ms=90_000,
        maximum_frame_latency_ms=1_000,
        depth_participation_fraction=0.1,
        adverse_slippage_bps=2.0,
        taker_fee_bps=5.0,
        price_tick=0.1,
        quantity_step=0.001,
    )


def book_frame(*, tape_id: str, symbol: str, sequence: int, at_ms: int, previous_sha256: str | None):
    return RecordedTopNBookFrameV1(
        source="native-campaign-synthetic-sim-fixture",
        tape_id=tape_id,
        stream_epoch="native-campaign-fixture-epoch",
        symbol=symbol,
        tape_sequence=sequence,
        exchange_update_id=sequence,
        exchange_at_ms=at_ms,
        received_at_ms=at_ms,
        persisted_at_ms=at_ms,
        raw_payload_sha256=hashlib.sha256(f"synthetic-book:{tape_id}:{symbol}".encode()).hexdigest(),
        previous_frame_sha256=previous_sha256,
        continuity="ADMITTED",
        bids=(RecordedBookLevelV1(price=97.9, quantity=50.0),),
        asks=(RecordedBookLevelV1(price=98.1, quantity=50.0),),
    )


def simulation_session(*, tape_id: str, tape_sha256: str, at_ms: int) -> SimulationSessionV1:
    return SimulationSessionV1(
        source="native-campaign-synthetic-sim-fixture",
        tape_id=tape_id,
        tape_sha256=tape_sha256,
        assumptions=simulation_assumptions(),
        strategy_allowlist=(
            SimulationStrategyRefV1(strategy_id="range_mean_reversion_v1", strategy_revision="1"),
        ),
        started_at_ms=at_ms,
        ends_at_ms=at_ms + 120_000,
    )


def historical_adoption_sha256() -> str:
    """Domain-separated synthetic adoption evidence; never read from a report."""
    return canonical_sha256(
        {
            "fixture": "native-campaign-engineering-only",
            "historical_cost_microusd": 6_000_000,
            "qualification": False,
        }
    )


def fixture_produced_at(at_ms: int) -> datetime:
    return datetime.fromtimestamp(at_ms / 1_000, tz=UTC)
