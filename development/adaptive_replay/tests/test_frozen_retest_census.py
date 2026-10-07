import json
import time
from pathlib import Path

import pytest
from kairos_strategy.candles import Candle

from adaptive_replay.engine import CostScenario
from adaptive_replay.frozen_retest import HISTORY_BARS
from adaptive_replay.frozen_retest_census import (
    census,
    diagnose_symbol,
    fixed_census_protocol,
    validate_paths,
)
from adaptive_replay.historical_context import digest
from adaptive_replay.inputs import WindowInputs


def workspace(tmp_path):
    root = tmp_path / "kairos-workspace"
    (root / "runtime").mkdir(parents=True)
    plan = root / "kairos" / "development" / "adaptive_replay" / "plan.json"
    plan.parent.mkdir(parents=True)
    original = Path(__file__).parents[1] / "plan.json"
    plan.write_bytes(original.read_bytes())
    return root


def test_full_fixed_roster_costs_no_paid_calls_or_economics():
    protocol = fixed_census_protocol()
    assert len(protocol["episodes"]) == 2 and len(protocol["universe"]) == 5
    assert protocol["max_wall_seconds"] == 300 and protocol["workers"] == 1
    assert protocol["cost_scenarios"][0]["fee_bps_per_side"] == 4.5
    assert protocol["cost_scenarios"][1]["fee_bps_per_side"] == 9
    assert not protocol["parameter_search"] and not protocol["new_downloads"]
    assert not protocol["economics_executed"] and protocol["provider_calls"] == 0
    assert protocol["readiness"]["STRATEGY_POLICY"] == "REJECT_ALL"
    assert not any(v for k, v in protocol["readiness"].items() if k != "STRATEGY_POLICY")
    assert digest(fixed_census_protocol()) == digest(protocol)
    protocol["strategy"]["entry_lifetime_ms"] = 1
    assert digest(fixed_census_protocol()) != digest(protocol)


@pytest.mark.parametrize("name", ["runtime", "old-receipt", "frozen-retest-census-20261007-a/nested"])
def test_output_scope_cannot_be_broad_or_nested(tmp_path, name):
    root = workspace(tmp_path)
    with pytest.raises(ValueError):
        validate_paths(root, root / "runtime" / name)


def test_existing_attempt_never_overwritten(tmp_path):
    root = workspace(tmp_path)
    output = root / "runtime" / "frozen-retest-census-20261007-a"
    output.mkdir()
    with pytest.raises(FileExistsError):
        validate_paths(root, output)
    with pytest.raises(ValueError):
        validate_paths(root, Path(output.name))


def test_dependency_guard_precedes_any_created_output(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    output = root / "runtime" / "frozen-retest-census-20261007-a"

    def fail(*args):
        raise ValueError("immutable dependency mismatch")

    monkeypatch.setattr("adaptive_replay.frozen_retest_census.installed_sources", fail)
    with pytest.raises(ValueError, match="immutable dependency"):
        census(root, output)
    assert not output.exists()


def test_source_load_failure_retains_sealed_pre_run_and_failure_receipts(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    output = root / "runtime" / "frozen-retest-census-20261007-a"
    monkeypatch.setattr(
        "adaptive_replay.frozen_retest_census.installed_sources", lambda *args: {"fixture": True}
    )

    def fail(*args):
        raise FileNotFoundError("fixture missing cache")

    monkeypatch.setattr("adaptive_replay.frozen_retest_census.load_window", fail)
    with pytest.raises(FileNotFoundError):
        census(root, output)
    assert (output / "before.json").is_file() and (output / "protocol.json").is_file()
    failure = json.loads((output / "failure.json").read_text())
    assert failure["state"] == "FAILED_CLOSED_ATTEMPT_RETAINED" and failure["provider_calls"] == 0
    assert not (output / "result.json").exists()
    with pytest.raises(FileExistsError):
        census(root, output)


def test_deadline_cannot_be_silently_ignored():
    from adaptive_replay.frozen_retest_census import _check

    with pytest.raises(TimeoutError):
        _check(time.monotonic() - 1)


def test_census_uses_every_complete_five_minute_slot_and_retains_zero_days():
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
    scenarios = (CostScenario("base", 4.5, 2, 1, 2, 2, 3), CostScenario("stress", 9, 4, 2, 2, 2, 3))
    records, counts = diagnose_symbol(inputs, "BTCUSDT", scenarios, time.monotonic() + 10)
    assert counts["scheduled_slots"] == len(records) == 4
    assert [r["technical"]["cut_ms"] for r in records] == list(range(inputs.start_ms, inputs.end_ms, 300_000))
    assert counts["candidates_each_utc_day"] == {"1970-01-03": 0}
    assert counts["raw_candidates_after_fixed_base_hurdle"] == 0
    assert counts["scenarios"]["base"]["first_arrival_geometry_feasible"] == 0
    with pytest.raises(TimeoutError):
        diagnose_symbol(inputs, "BTCUSDT", scenarios, time.monotonic() - 1)
