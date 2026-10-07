from __future__ import annotations

import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent

from adaptive_replay import calendar_pair as calendar
from adaptive_replay import right_tail as pair
from adaptive_replay.inputs import WindowInputs


def test_real_calendar_protocol_binds_native_source_and_unchanged_evaluator() -> None:
    project = Path(__file__).resolve().parents[1]
    plan, base = calendar.load_protocol(project / "calendar-pair-plan.json")
    receipt = pair.sources(plan, base, project / "calendar-pair-plan.json")
    assert plan["reference_rule"] == calendar.RULE
    assert receipt["native_pair"][pair.ARMS[0]]["fingerprint"] == plan["config_fingerprints"][pair.ARMS[0]]
    assert (
        receipt["aligned_transitive_base_source_sha256"] == plan["registry_source_fingerprints"][pair.ARMS[0]]
    )
    assert "calendar_pair.py" in receipt["installed_replay_context"]["replay_modules_sha256"]
    assert "calendar_inputs.py" in receipt["installed_replay_context"]["replay_modules_sha256"]
    assert all(value is False for key, value in plan["readiness"].items() if key != "STRATEGY_POLICY")


def _flat_window() -> WindowInputs:
    start = int(datetime(2022, 1, 1, tzinfo=UTC).timestamp() * 1000)
    end = start + 2 * pair.DAY
    rows = tuple(
        Candle(
            symbol="BTCUSDT",
            timeframe="1m",
            open_time_ms=ts,
            close_time_ms=ts + pair.MINUTE - 1,
            open=100,
            high=101,
            low=99,
            close=100,
            volume=10,
        )
        for ts in range(start - pair.WARMUP, end + 3 * pair.DAY, pair.MINUTE)
    )
    return WindowInputs(
        bars={"BTCUSDT": rows},
        funding={},
        evidence={},
        start_ms=start,
        end_ms=end,
        data_start_ms=start - pair.WARMUP,
        data_end_ms=end + 3 * pair.DAY,
    )


def test_calendar_generation_obeys_exact_prefix_and_never_uses_exit_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _flat_window()
    monkeypatch.setattr(calendar, "UNIVERSE", ("BTCUSDT",))
    native = calendar.generate_sleeve_intents
    seen = []

    def checked(arm: str, rows: list[Candle], config: object) -> list[SleeveIntent]:
        assert rows[0].open_time_ms == inputs.start_ms - pair.WARMUP
        assert rows[-1].close_time_ms < inputs.end_ms
        seen.append(rows[-1].close_time_ms)
        return native(arm, rows, config)

    monkeypatch.setattr(calendar, "generate_sleeve_intents", checked)
    tapes, evidence = calendar.generate_calendar_pair(inputs, time.monotonic() + 60)
    assert all(not tape for tape in tapes.values())
    assert evidence["exit_tail_used"] is False
    assert inputs.start_ms + pair.HOUR - 1 in seen
    assert evidence["prefix_check_scope"] == "FIXED_QUARTERLY_CUTS_NOT_EVERY_DAILY_FUNCTION_PROOF"


def test_calendar_missing_prefix_fails_before_native_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = _flat_window()
    inputs = replace(inputs, bars={"BTCUSDT": inputs.bars["BTCUSDT"][1:]})
    monkeypatch.setattr(calendar, "UNIVERSE", ("BTCUSDT",))
    with pytest.raises(ValueError, match="complete exact causal calendar prefix"):
        calendar.generate_calendar_pair(inputs, time.monotonic() + 60)


def test_calendar_quarter_cut_catches_future_within_first_decision_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _flat_window()
    monkeypatch.setattr(calendar, "UNIVERSE", ("BTCUSDT",))
    eligible = inputs.start_ms + pair.HOUR
    intent = SleeveIntent(
        sleeve_id=pair.ARMS[0],
        symbol="BTCUSDT",
        side=Side.LONG,
        decision_ts_ms=eligible - 1,
        entry_eligible_ts_ms=eligible,
        entry_expires_ts_ms=eligible + pair.HOUR - 1,
        reference_price=100,
        signal_strength=0.5,
        gross_reward_bps=800,
        exit_plan=ExitPlan(stop_price=98, target_price=108, max_holding_ms=72 * pair.HOUR),
        metadata=(("config_sha256", pair.RightTailTrendConfig().fingerprint),),
    )

    def leaky(arm: str, rows: list[Candle], config: object) -> list[SleeveIntent]:
        return [intent] if rows[-1].open_time_ms >= inputs.start_ms + 2 * pair.HOUR else []

    monkeypatch.setattr(calendar, "generate_sleeve_intents", leaky)
    with pytest.raises(ValueError, match="same-origin prefix mutation"):
        calendar.generate_calendar_pair(inputs, time.monotonic() + 60)


def test_calendar_expired_resource_bound_prevents_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = _flat_window()
    monkeypatch.setattr(calendar, "UNIVERSE", ("BTCUSDT",))
    with pytest.raises(TimeoutError, match="resource bound"):
        calendar.generate_calendar_pair(inputs, time.monotonic() - 1)
