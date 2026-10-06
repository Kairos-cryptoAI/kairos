from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.sleeves import RangeMeanReversionConfig, TrendBreakoutConfig

from adaptive_replay import baselines
from adaptive_replay.inputs import UNIVERSE, WindowInputs

MINUTE = 60_000
HOUR = 60 * MINUTE


def _bars(start_ms: int, end_ms: int, symbol: str = "BTCUSDT") -> tuple[Candle, ...]:
    rows = []
    for open_ms in range(start_ms, end_ms, MINUTE):
        price = 100.0
        rows.append(
            Candle(
                symbol=symbol,
                timeframe="1m",
                open_time_ms=open_ms,
                close_time_ms=open_ms + MINUTE - 1,
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=10.0,
                quote_volume=1_000.0,
                taker_buy_volume=5.0,
                taker_buy_quote_volume=500.0,
            )
        )
    return tuple(rows)


def _window(*, scoring_hours: int = 72, symbols: tuple[str, ...] = ("BTCUSDT",)) -> WindowInputs:
    start_ms = 10 * 24 * HOUR
    end_ms = start_ms + scoring_hours * HOUR
    bars = {symbol: _bars(start_ms - baselines.WARMUP_MS - 18 * HOUR, end_ms, symbol) for symbol in symbols}
    return WindowInputs(
        bars=bars,
        funding={},
        evidence={},
        start_ms=start_ms,
        end_ms=end_ms,
        data_start_ms=start_ms - baselines.WARMUP_MS - 18 * HOUR,
        data_end_ms=end_ms,
    )


def _intent(
    strategy_id: str,
    symbol: str,
    eligible_ms: int,
    *,
    side: Side = Side.LONG,
    metadata: tuple[tuple[str, str], ...] = (),
) -> SleeveIntent:
    ref = 100.0
    stop, target = (99.0, 102.0) if side is Side.LONG else (101.0, 98.0)
    return SleeveIntent(
        sleeve_id=strategy_id,
        symbol=symbol,
        side=side,
        decision_ts_ms=eligible_ms - 1,
        entry_eligible_ts_ms=eligible_ms,
        entry_expires_ts_ms=eligible_ms + 5 * MINUTE - 1,
        reference_price=ref,
        signal_strength=0.5,
        gross_reward_bps=abs(target - ref) / ref * 10_000,
        exit_plan=ExitPlan(
            stop_price=stop,
            target_price=target,
            max_holding_ms=12 * HOUR,
            trailing_activation_price=101.0 if side is Side.LONG else 99.0,
            trailing_distance=0.5,
        ),
        metadata=metadata,
    )


def test_fixed_baseline_configs_expose_only_the_selected_native_defaults() -> None:
    configs = baselines.baseline_configs()
    assert tuple(configs) == ("trend_breakout_v1", "range_mean_reversion_v1")
    assert configs["trend_breakout_v1"] == TrendBreakoutConfig()
    assert configs["range_mean_reversion_v1"] == RangeMeanReversionConfig()
    with pytest.raises(TypeError):
        baselines.baseline_configs(tune=True)  # type: ignore[call-arg]
    with pytest.raises(FrozenInstanceError):
        configs["trend_breakout_v1"].donchian_lookback = 12  # type: ignore[attr-defined]


def test_baseline_tapes_keep_native_intent_identity_and_filter_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _window(symbols=UNIVERSE)
    inside = _intent("trend_breakout_v1", "BTCUSDT", inputs.start_ms + 24 * HOUR)
    calls: list[tuple[str, int, int]] = []

    def fake_generate(strategy_id: str, candles: list[Candle], config: object) -> tuple[SleeveIntent, ...]:
        assert config == baselines.baseline_configs()[strategy_id]
        calls.append((strategy_id, candles[0].open_time_ms, candles[-1].open_time_ms))
        if strategy_id == "trend_breakout_v1":
            symbol = candles[0].symbol
            return (
                inside if symbol == "BTCUSDT" else _intent(strategy_id, symbol, inputs.start_ms + 24 * HOUR),
                _intent(strategy_id, symbol, inputs.start_ms - 5 * MINUTE),
                _intent(strategy_id, symbol, inputs.end_ms),
            )
        return ()

    monkeypatch.setattr(baselines, "generate_sleeve_intents", fake_generate)
    tapes, evidence = baselines.generate_baseline_tapes(inputs, float("inf"))

    slot_intents = tapes["trend_breakout_v1"][inside.entry_eligible_ts_ms]
    assert len(slot_intents) == len(UNIVERSE)
    assert slot_intents[0] is inside
    assert slot_intents[0].exit_plan.trailing_activation_price == 101.0
    assert slot_intents[0].exit_plan.trailing_distance == 0.5
    assert tapes["range_mean_reversion_v1"] == {}
    assert evidence["exit_tail_used"] is False
    assert evidence["prefix_start_ms"] == inputs.start_ms - 54 * HOUR
    assert len(calls) == 40  # five symbols, two families, full plus three fixed cuts


def test_full_prefix_rejects_candidate_mutation_after_predetermined_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _window()
    eligible = inputs.start_ms + 24 * HOUR

    def future_sensitive(strategy_id: str, candles: list[Candle], config: object) -> tuple[SleeveIntent, ...]:
        marker = "full" if candles[-1].open_time_ms >= inputs.start_ms + 60 * HOUR else "prefix"
        return (_intent(strategy_id, "BTCUSDT", eligible, metadata=(("future_marker", marker),)),)

    monkeypatch.setattr(baselines, "generate_sleeve_intents", future_sensitive)
    with pytest.raises(ValueError, match="prefix mutation"):
        baselines.generate_baseline_tapes(inputs, float("inf"))


def test_baseline_identity_binds_registry_source_config_and_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(baselines, "installed_source_tree_sha256", lambda paths: "a" * 64)
    identities = baselines.baseline_identities()
    assert identities["trend_breakout_v1"]["installed_source_tree_sha256"] == "a" * 64
    assert identities["trend_breakout_v1"]["config"]["donchian_lookback"] == 20
    assert identities["range_mean_reversion_v1"]["fingerprint"] == RangeMeanReversionConfig().fingerprint
    assert identities["range_mean_reversion_v1"]["registry_status"] == "rejected"


def test_combine_tapes_resolves_same_direction_priority_suppresses_opposites_and_orders_symbols() -> None:
    at = 30 * HOUR
    breakout = _intent("trend_breakout_v1", "ETHUSDT", at)
    range_same = _intent("range_mean_reversion_v1", "ETHUSDT", at)
    range_conflict = _intent("range_mean_reversion_v1", "BTCUSDT", at, side=Side.SHORT)
    breakout_conflict = _intent("trend_breakout_v1", "BTCUSDT", at)
    bnb = _intent("range_mean_reversion_v1", "BNBUSDT", at)
    union, stats = baselines.combine_tapes(
        {
            "range_mean_reversion_v1": {at: [range_same, range_conflict, bnb]},
            "trend_breakout_v1": {at: [breakout, breakout_conflict]},
        }
    )

    assert [item.symbol for item in union[at]] == ["ETHUSDT", "BNBUSDT"]
    assert union[at][0] is breakout  # fixed priority, and original candidate preserved
    assert union[at][0].exit_plan == breakout.exit_plan
    assert stats == {
        "candidate_count": 5,
        "kept_count": 2,
        "same_direction_collisions": 1,
        "opposite_direction_conflicts": 1,
    }


def test_combine_tapes_rejects_unknown_families() -> None:
    with pytest.raises(ValueError, match="unknown baseline"):
        baselines.combine_tapes({"custom_tuned_strategy": {}})  # type: ignore[dict-item]
