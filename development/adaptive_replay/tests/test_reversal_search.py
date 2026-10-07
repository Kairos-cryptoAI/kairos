import json
import time
from pathlib import Path

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent

from adaptive_replay.engine import CostScenario
from adaptive_replay.failed_reversal import HISTORY_BARS, STRATEGY_ID
from adaptive_replay.historical_context import digest
from adaptive_replay.inputs import UNIVERSE, WindowInputs
from adaptive_replay.reversal_search import (
    CONTROL_ID,
    _control_arrivals,
    _market_summary,
    diagnose_symbol,
    fixed_search_protocol,
    search,
    validate_paths,
)

BASE = CostScenario("base", 4.5, 2, 1, 2, 2, 3)
STRESS = CostScenario("stress", 9, 4, 2, 2, 2, 3)


def workspace(tmp_path):
    root = tmp_path / "kairos-workspace"
    (root / "runtime").mkdir(parents=True)
    plan = root / "kairos" / "development" / "adaptive_replay" / "plan.json"
    plan.parent.mkdir(parents=True)
    plan.write_bytes((Path(__file__).parents[1] / "plan.json").read_bytes())
    return root


def test_fixed_roster_costs_accounts_and_no_frequency_or_profit_quota():
    protocol = fixed_search_protocol()
    assert len(protocol["windows"]) == 6 and len(protocol["universe"]) == 5
    assert protocol["expected_slots_each_arm"] == 31_680
    assert protocol["max_wall_seconds"] == 600 and protocol["workers"] == 1
    assert protocol["geometry"]["minimum_net_reward_risk"] == 1.25
    assert protocol["geometry"]["maximum_stop_bps"] == 300
    assert not protocol["geometry"]["atr_multiple_filter_on_independent_or_native_candidate"]
    assert protocol["risk"] == {
        "per_trade_fraction": 0.0025,
        "aggregate_open_fraction": 0.01,
        "maximum_symbol_notional_fraction": 0.25,
        "maximum_leverage": 1,
    }
    assert protocol["natural_frequency_quota"] is None
    assert not protocol["control"]["modified"]
    assert not protocol["parameter_search"] and not protocol["new_downloads"]
    assert protocol["provider_calls"] == 0 and not protocol["complete_system_economics"]
    assert not protocol["blind_campaign_credit"]
    assert protocol["readiness"]["STRATEGY_POLICY"] == "REJECT_ALL"
    assert not any(v for k, v in protocol["readiness"].items() if k != "STRATEGY_POLICY")
    assert digest(fixed_search_protocol()) == digest(protocol)
    protocol["challenger"]["entry_lifetime_ms"] = 1
    assert digest(fixed_search_protocol()) != digest(protocol)


@pytest.mark.parametrize("name", ["runtime", "old-receipt", "reversal-search-20261007-a/nested"])
def test_output_scope_cannot_be_broad_nested_or_relative(tmp_path, name):
    root = workspace(tmp_path)
    with pytest.raises(ValueError):
        validate_paths(root, root / "runtime" / name)
    with pytest.raises(ValueError):
        validate_paths(root, Path("reversal-search-20261007-a"))


def test_existing_attempt_never_overwritten(tmp_path):
    root = workspace(tmp_path)
    output = root / "runtime" / "reversal-search-20261007-a"
    output.mkdir()
    with pytest.raises(FileExistsError):
        validate_paths(root, output)


@pytest.mark.parametrize("data_days,bars,funding", [(7, 10_080, 21), (9, 12_960, 27)])
def test_market_report_uses_actual_3day_or_5day_padded_data_horizon(data_days, bars, funding):
    # Count-only reporter fixture. These placeholders are not input-valid
    # market data and never pass the separate real replay validation boundary.
    inputs = WindowInputs(
        {s: (None,) * bars for s in UNIVERSE},
        {s: (None,) * funding for s in UNIVERSE},
        {
            "bars": {s: {"gaps": 0, "normalized_rows_sha256": "a" * 64} for s in UNIVERSE},
            "funding": {s: {"normalized_rows_sha256": "b" * 64} for s in UNIVERSE},
        },
        3 * 86_400_000,
        (data_days - 1) * 86_400_000,
        0,
        data_days * 86_400_000,
    )
    report = _market_summary(inputs)
    assert all(r["bars"] == bars and r["funding"] == funding and r["gaps"] == 0 for r in report.values())
    inputs.bars["BTCUSDT"] = inputs.bars["BTCUSDT"][:-1]
    with pytest.raises(ValueError, match="complete bar/funding"):
        _market_summary(inputs)


def test_dependency_guard_precedes_created_output(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    output = root / "runtime" / "reversal-search-20261007-a"

    def fail(*args):
        raise ValueError("immutable dependency mismatch")

    monkeypatch.setattr("adaptive_replay.reversal_search.installed_sources", fail)
    with pytest.raises(ValueError, match="immutable dependency"):
        search(root, output)
    assert not output.exists()


def test_source_load_failure_retains_attempt_and_forbids_retry(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    output = root / "runtime" / "reversal-search-20261007-a"
    monkeypatch.setattr("adaptive_replay.reversal_search.installed_sources", lambda *args: {"fixture": True})

    def fail(*args):
        raise FileNotFoundError("missing fixture input")

    monkeypatch.setattr("adaptive_replay.reversal_search.load_window", fail)
    with pytest.raises(FileNotFoundError):
        search(root, output)
    assert (output / "before.json").is_file() and (output / "protocol.json").is_file()
    failure = json.loads((output / "failure.json").read_text())
    assert failure["state"] == "FAILED_CLOSED_ATTEMPT_RETAINED" and failure["provider_calls"] == 0
    assert not (output / "result.json").exists()
    with pytest.raises(FileExistsError):
        search(root, output)


def test_complete_symbol_roster_retains_every_zero_slot_for_both_arms():
    bars = tuple(
        Candle("BTCUSDT", "1m", i * 60_000, i * 60_000 + 59_999, 100, 100.2, 99.8, 100, 1)
        for i in range(HISTORY_BARS + 20)
    )
    inputs = WindowInputs(
        {"BTCUSDT": bars},
        {},
        {},
        HISTORY_BARS * 60_000,
        (HISTORY_BARS + 20) * 60_000,
        0,
        (HISTORY_BARS + 20) * 60_000,
    )
    records, counts, tapes = diagnose_symbol(inputs, "BTCUSDT", (BASE, STRESS), time.monotonic() + 20)
    assert len(records) == 8
    for arm in (STRATEGY_ID, CONTROL_ID):
        assert counts[arm]["scheduled_slots"] == 4
        assert counts[arm]["candidates_each_utc_day"] == {"1970-01-03": 0}
        assert counts[arm]["raw_candidates"] == 0
        assert counts[arm]["no_candidate_slots"] == 4
        assert tapes[arm] == {"base": {}, "stress": {}}
        assert [r["cut_ms"] for r in records if r["arm"] == arm] == list(
            range(inputs.start_ms, inputs.end_ms, 300_000)
        )
    assert all(
        r["technical"]["native_quiet_reason"] == "NOT_EXPOSED_BY_REGISTERED_GENERATOR"
        for r in records
        if r["arm"] == CONTROL_ID
    )
    with pytest.raises(TimeoutError):
        diagnose_symbol(inputs, "BTCUSDT", (BASE, STRESS), time.monotonic() - 1)


def test_native_control_keeps_own_barriers_but_common_intermediate_touch_cancels():
    intent = SleeveIntent(
        CONTROL_ID,
        "BTCUSDT",
        Side.LONG,
        299_999,
        300_000,
        599_999,
        100,
        1,
        400,
        ExitPlan(99, 104, 120 * 60_000),
    )
    elapsed = (Candle("BTCUSDT", "1m", 300_000, 359_999, 100, 100.2, 99, 100, 1),)
    refused = _control_arrivals(intent, elapsed, 300_099, 360_000, 100, (BASE, STRESS))
    assert all(v["reason"] == "FROZEN_BARRIER_TOUCHED_BEFORE_ARRIVAL" for v in refused.values())
    untouched = (Candle("BTCUSDT", "1m", 300_000, 359_999, 100, 100.2, 99.8, 100, 1),)
    result = _control_arrivals(intent, untouched, 300_099, 360_000, 100, (BASE, STRESS))
    assert all(v["geometry_feasible"] for v in result.values())
    assert result["base"]["original_target_price"] == 104
    with pytest.raises(ValueError, match="first strict quote"):
        _control_arrivals(intent, untouched, 300_099, 420_000, 100, (BASE,))


def test_after_source_hashing_deadline_failure_cannot_be_success(tmp_path, monkeypatch):
    """An explicit synthetic harness, not a historical replay or cost proof."""
    import adaptive_replay.reversal_search as module

    root = workspace(tmp_path)
    output = root / "runtime" / "reversal-search-20261007-fixture"
    actual_protocol = fixed_search_protocol()
    actual_protocol["expected_slots_each_arm"] = len(UNIVERSE)
    monkeypatch.setattr(module, "fixed_search_protocol", lambda: actual_protocol)
    monkeypatch.setattr(module, "WINDOWS", (("fixture", "1970-01-03", "1970-01-04", "original"),))
    inputs = WindowInputs({}, {}, {}, 0, 86_400_000, 0, 86_400_000 + 3 * 3_600_000)
    monkeypatch.setattr(module, "load_window", lambda *args: inputs)
    monkeypatch.setattr(module, "validate_replay_inputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_market_summary", lambda *args: {})
    now, sources_seen = [0.0], [0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])

    def sources(*args):
        sources_seen[0] += 1
        if sources_seen[0] == 2:
            now[0] = 601
        return {"fixture": True}

    monkeypatch.setattr(module, "installed_sources", sources)

    def diagnostic(inputs, symbol, scenarios, deadline):
        records = [{"arm": a, "symbol": symbol, "cut_ms": 0} for a in (STRATEGY_ID, CONTROL_ID)]
        counts = {
            a: {
                "raw_candidates": 0,
                "scenarios": {s.id: {"first_arrival_geometry_feasible": 0} for s in scenarios},
            }
            for a in (STRATEGY_ID, CONTROL_ID)
        }
        tapes = {a: {s.id: {} for s in scenarios} for a in (STRATEGY_ID, CONTROL_ID)}
        return records, counts, tapes

    monkeypatch.setattr(module, "diagnose_symbol", diagnostic)

    class Account:
        rejections, trades, events = {}, [], []

    monkeypatch.setattr(
        module,
        "replay_tape",
        lambda *args, **kwargs: ({"entries_each_utc_day": {"1970-01-03": 0}}, Account()),
    )
    with pytest.raises(TimeoutError):
        search(root, output)
    assert (output / "failure.json").is_file() and not (output / "after.json").exists()
    assert not (output / "result.json").exists()
