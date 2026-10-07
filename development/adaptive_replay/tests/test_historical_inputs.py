from __future__ import annotations

import time
from dataclasses import replace

import pytest
from kairos_backtest.factor_data import FundingObservation
from kairos_strategy.candles import Candle

from adaptive_replay.historical_inputs import validate_replay_inputs
from adaptive_replay.inputs import FUNDING_INTERVAL_MS, UNIVERSE, WindowInputs

MINUTE = 60_000


def _bars(symbol: str, start: int, count: int) -> tuple[Candle, ...]:
    return tuple(
        Candle(
            symbol, "1m", start + i * MINUTE, start + (i + 1) * MINUTE - 1, 100, 101, 99, 100, 2, 200, 1, 100
        )
        for i in range(count)
    )


def _short_inputs() -> WindowInputs:
    data_end_ms = 2 * MINUTE + 3 * 60 * 60 * 1_000
    bar_count = data_end_ms // MINUTE
    return WindowInputs(
        bars={symbol: _bars(symbol, 0, bar_count) for symbol in UNIVERSE},
        funding={symbol: () for symbol in UNIVERSE},
        evidence={},
        start_ms=MINUTE,
        end_ms=2 * MINUTE,
        data_start_ms=0,
        data_end_ms=data_end_ms,
    )


def _native_inputs() -> WindowInputs:
    horizon = 16 * 60 * 60 * 1_000
    rows = {}
    funding = {}
    for symbol in UNIVERSE:
        rows[symbol] = _bars(symbol, 0, horizon // MINUTE)
        funding[symbol] = (
            FundingObservation(symbol, 0, 8, -0.0001),
            FundingObservation(symbol, FUNDING_INTERVAL_MS + 59_999, 8, 0.0002),
        )
    return WindowInputs(
        bars=rows,
        funding=funding,
        evidence={},
        start_ms=8 * 60 * 60 * 1_000,
        end_ms=13 * 60 * 60 * 1_000,
        data_start_ms=0,
        data_end_ms=horizon,
    )


def _validate(inputs: WindowInputs, *, fixture_only: bool = True, deadline: float | None = None) -> None:
    validate_replay_inputs(
        inputs,
        fixture_only=fixture_only,
        deadline=time.monotonic() + 30 if deadline is None else deadline,
    )


def test_complete_fixture_bar_prefix_and_explicit_empty_funding_are_valid() -> None:
    _validate(_short_inputs())


def test_nonfixture_requires_complete_native_funding_buckets_without_rounding() -> None:
    _validate(_native_inputs(), fixture_only=False)


@pytest.mark.parametrize("field", ["bars", "funding"])
def test_symbol_mapping_must_be_exact_fixed_universe(field: str) -> None:
    data = _short_inputs()
    mapping = dict(getattr(data, field))
    mapping.pop(UNIVERSE[-1])
    with pytest.raises(ValueError, match="universe"):
        _validate(replace(data, **{field: mapping}))


def test_bar_rows_must_be_immutable_exact_count_and_reach_tail_anchor() -> None:
    data = _short_inputs()
    bars = dict(data.bars)
    bars[UNIVERSE[0]] = list(bars[UNIVERSE[0]])  # type: ignore[assignment]
    with pytest.raises(ValueError, match="tuple"):
        _validate(replace(data, bars=bars))

    bars[UNIVERSE[0]] = data.bars[UNIVERSE[0]][:-1]
    with pytest.raises(ValueError, match="complete horizon"):
        _validate(replace(data, bars=bars))


@pytest.mark.parametrize("defect", ["gap", "duplicate", "reverse", "symbol", "timeframe"])
def test_bar_grid_defects_fail_closed(defect: str) -> None:
    data = _short_inputs()
    bars = dict(data.bars)
    original = bars[UNIVERSE[0]]
    if defect == "gap":
        changed = replace(
            original[1],
            open_time_ms=original[1].open_time_ms + MINUTE,
            close_time_ms=original[1].close_time_ms + MINUTE,
        )
        rows = (original[0], changed, *original[2:])
    elif defect == "duplicate":
        rows = (original[0], original[0], *original[2:])
    elif defect == "reverse":
        rows = tuple(reversed(original))
    elif defect == "symbol":
        rows = (replace(original[0], symbol="ETHUSDT"), *original[1:])
    else:
        rows = (replace(original[0], timeframe="5m"), *original[1:])
    bars[UNIVERSE[0]] = rows
    with pytest.raises(ValueError):
        _validate(replace(data, bars=bars))


def test_candle_ohlcv_contract_is_rechecked_for_all_rows() -> None:
    data = _short_inputs()
    original = data.bars[UNIVERSE[0]]
    invalid = object.__new__(Candle)
    for name in Candle.__dataclass_fields__:
        object.__setattr__(invalid, name, getattr(original[-1], name))
    object.__setattr__(invalid, "high", 99.0)
    bars = dict(data.bars)
    bars[UNIVERSE[0]] = (*original[:-1], invalid)
    with pytest.raises(ValueError, match="OHLC"):
        _validate(replace(data, bars=bars))


@pytest.mark.parametrize(
    "change",
    [
        {"start_ms": True},
        {"end_ms": 121_000},
        {"data_start_ms": 60_000},
        {"data_end_ms": 299_999},
    ],
)
def test_episode_and_data_clocks_must_be_exact_utc_minute_anchors(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _validate(replace(_short_inputs(), **change))


def test_nonfixture_funding_must_cover_every_eighthour_bucket() -> None:
    data = _native_inputs()
    funding = dict(data.funding)
    funding[UNIVERSE[0]] = funding[UNIVERSE[0]][:1]
    with pytest.raises(ValueError, match="every native"):
        _validate(replace(data, funding=funding), fixture_only=False)


@pytest.mark.parametrize("defect", ["symbol", "interval", "rate", "late", "duplicate", "order"])
def test_supplied_funding_observations_are_typed_and_strict(defect: str) -> None:
    data = _native_inputs()
    funding = dict(data.funding)
    obs = list(funding[UNIVERSE[0]])
    if defect == "symbol":
        obs[0] = replace(obs[0], symbol="ETHUSDT")
    elif defect == "interval":
        obs[0] = replace(obs[0], interval_hours=7)
    elif defect == "rate":
        obs[0] = replace(obs[0], rate=float("inf"))
    elif defect == "late":
        obs[1] = replace(obs[1], timestamp_ms=FUNDING_INTERVAL_MS + 60_000)
    elif defect == "duplicate":
        obs[1] = replace(obs[1], timestamp_ms=1)
    else:
        obs.reverse()
    funding[UNIVERSE[0]] = tuple(obs)
    with pytest.raises(ValueError):
        _validate(replace(data, funding=funding), fixture_only=False)


def test_fixture_empty_funding_is_allowed_but_supplied_rows_are_still_checked() -> None:
    data = _short_inputs()
    funding = dict(data.funding)
    funding[UNIVERSE[0]] = (FundingObservation(UNIVERSE[0], -1, 8, 0.0),)
    with pytest.raises(ValueError, match="timestamp"):
        _validate(replace(data, funding=funding))


def test_validation_obeys_absolute_monotonic_deadline() -> None:
    with pytest.raises(TimeoutError):
        _validate(_short_inputs(), deadline=time.monotonic() - 1)


def test_nonfixture_funding_covers_settlements_not_arbitrary_bar_endpoints():
    data = _short_inputs()
    funding = {symbol: (FundingObservation(symbol, 0, 8, 0.0),) for symbol in UNIVERSE}
    _validate(replace(data, funding=funding), fixture_only=False)


def test_nonfixture_horizon_without_a_scheduled_settlement_is_known_empty():
    data_start = 3_600_000
    start, end = data_start + MINUTE, data_start + 2 * MINUTE
    data_end = end + 3 * 3_600_000
    data = WindowInputs(
        {s: _bars(s, data_start, (data_end - data_start) // MINUTE) for s in UNIVERSE},
        {s: () for s in UNIVERSE},
        {},
        start,
        end,
        data_start,
        data_end,
    )
    _validate(data, fixture_only=False)
