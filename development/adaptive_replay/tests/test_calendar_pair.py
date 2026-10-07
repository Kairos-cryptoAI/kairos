from __future__ import annotations

import copy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from adaptive_replay import calendar_pair


def _ms(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(datetime(year, month, day, hour, tzinfo=UTC).timestamp() * 1_000)


def _native_and_base() -> tuple[dict[str, Any], dict[str, Any]]:
    readiness = {
        "TECHNICAL_PAPER_READY": False,
        "PAPER_QUALIFIED": False,
        "ALPHA_READY": False,
        "LIVE_READY": False,
        "STRATEGY_POLICY": "REJECT_ALL",
    }
    native = {
        "schema": "kairos.strategy.right-tail-pair-plan.v1",
        "purpose": "SEEN_HISTORICAL_COMPATIBILITY_NOT_STRATEGY_SELECTION_OR_QUALIFICATION",
        "base_development_plan_sha256": "a" * 64,
        "arms": list(calendar_pair.pair.ARMS),
        "common_admission": {"policy": "COMMON_COST_RISK_V1"},
        "warmup_hours": 840,
        "exit_tail_hours": 72,
        "entry_modes": ["STRICT_MINUTE_OPEN"],
        "workers": 1,
        "max_wall_seconds": 1200,
        "readiness": readiness,
        "unchanged_native_defaults": True,
        "transitive_base_source_binding": True,
        "no_downloads": True,
        "no_paid_calls": True,
        "no_parameter_search": True,
        "no_blind_campaign_credit": True,
        "config_fingerprints": {arm: f"{i:064x}" for i, arm in enumerate(calendar_pair.pair.ARMS, 1)},
        "registry_source_fingerprints": {
            arm: f"{i + 2:064x}" for i, arm in enumerate(calendar_pair.pair.ARMS, 1)
        },
    }
    base = {
        "cost_scenarios": [
            {"id": "base", "fee_bps_per_side": 4.5},
            {"id": "stress", "fee_bps_per_side": 9.0},
        ],
        "pipeline_latency_ms_assumed": 100,
        "readiness": readiness,
    }
    return native, base


def _expected_plan(native: dict[str, Any]) -> dict[str, Any]:
    return {
        **native,
        "schema": "kairos.strategy.calendar-pair-plan.v1",
        "purpose": "FULL_YEAR_DEVELOPMENT_PRIOR_EXPOSURE_NOT_EXCLUDED",
        "windows": list(calendar_pair.WINDOWS),
        "prefix_cuts": "JAN_APR_JUL_OCT_01_0100_UTC_PLUS_END",
        "reference_rule": calendar_pair.RULE,
        "funding_schedule": "DEFAULT_8H_WITH_BYTE_BOUND_SOL_NOV2022_4H_2H_EXCEPTION",
        "sol_exception_archive_sha256": calendar_pair.SOL_EXCEPTION_SHA,
        "no_second_economic_attempt": True,
    }


def _protocol_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    native, base = _native_and_base()
    monkeypatch.setattr(
        calendar_pair.pair, "load_protocol", lambda _path: (copy.deepcopy(native), copy.deepcopy(base))
    )
    plan = _expected_plan(native)
    path = tmp_path / "calendar-plan.json"
    path.write_bytes(calendar_pair.canonical(plan))
    return path, plan, base


def test_calendar_protocol_is_exact_four_year_protocol(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path, expected, base = _protocol_fixture(monkeypatch, tmp_path)

    plan, loaded_base = calendar_pair.load_protocol(path)

    assert plan == expected
    assert [window["start"][:4] for window in plan["windows"]] == ["2022", "2023", "2024", "2025"]
    assert loaded_base == base


@pytest.mark.parametrize(
    "change",
    [
        lambda plan: plan["windows"][0].update(start="2021-01-01"),
        lambda plan: plan.update(cost_scenarios=[{"id": "cheaper"}]),
        lambda plan: plan.update(max_wall_seconds=1201),
    ],
    ids=["year", "cost-scope", "resource-bound"],
)
def test_calendar_protocol_rejects_year_cost_or_bound_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, change: Any
) -> None:
    path, plan, _base = _protocol_fixture(monkeypatch, tmp_path)
    altered = copy.deepcopy(plan)
    change(altered)
    path.write_bytes(calendar_pair.canonical(altered))

    with pytest.raises(ValueError, match="unchanged full-calendar reference protocol"):
        calendar_pair.load_protocol(path)


def test_quarterly_prefix_cuts_are_utc_exact_through_leap_year() -> None:
    cuts = calendar_pair.prefix_cuts(_ms(2024, 1, 1), _ms(2025, 1, 1))

    assert cuts == (
        _ms(2024, 1, 1, 1),
        _ms(2024, 4, 1, 1),
        _ms(2024, 7, 1, 1),
        _ms(2024, 10, 1, 1),
        _ms(2025, 1, 1),
    )


def _cell(
    cost: str,
    returned: float,
    drawdown: float,
    closes: int = 25,
    *,
    risk_overrun: bool = False,
    forced: int = 0,
    unresolved: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "cost_scenario": {"id": cost},
        "net_return_pct": returned,
        "closed_minute_mtm_drawdown_pct": drawdown,
        "closed_trades": closes,
        "risk_ceiling_mark_overrun": risk_overrun,
        "gross_ceiling_mark_overrun": False,
        "forced_settlements": forced,
        "terminal_unresolved_positions": unresolved or [],
    }


def _windows(
    base_metrics: list[tuple[float, float]] | None = None,
    aligned_metrics: list[tuple[float, float]] | None = None,
    *,
    closes: int = 25,
    base_risk_year: int | None = None,
) -> list[dict[str, Any]]:
    base_metrics = base_metrics or [(1.0, 2.0)] * 4
    aligned_metrics = aligned_metrics or [(2.0, 1.5)] * 4
    windows = []
    for index, window in enumerate(calendar_pair.WINDOWS):
        arms = []
        for arm_id, metrics in zip(calendar_pair.pair.ARMS, (base_metrics, aligned_metrics), strict=True):
            returned, drawdown = metrics[index]
            risk = arm_id == calendar_pair.pair.ARMS[1] and base_risk_year == index
            arms.append(
                {
                    "arm_id": arm_id,
                    "economic_results": [
                        _cell("base", returned, drawdown, closes, risk_overrun=risk),
                        _cell("stress", returned, drawdown, closes, risk_overrun=risk),
                    ],
                }
            )
        windows.append({"window": copy.deepcopy(window), "arms": arms})
    return windows


def test_pareto_nomination_requires_weak_all_years_and_strict_improvement() -> None:
    decision = calendar_pair.select_reference(_windows())

    assert decision["state"] == "REFERENCE_NOMINATED"
    assert decision["economic_reference_nominee"] == calendar_pair.pair.ARMS[1]
    assert decision["qualified_winner"] is None
    assert decision["strategy_selected_for_live"] is None


@pytest.mark.parametrize(
    "base_metrics,aligned_metrics",
    [
        ([(1.0, 2.0)] * 4, [(1.0, 2.0)] * 4),  # exact tie
        ([(1.0, 2.0)] * 4, [(2.0, 1.0), (0.5, 3.0), (2.0, 1.0), (2.0, 1.0)]),  # return/DD tradeoff
        ([(0.0, 3.0)] * 4, [(-1.0, 2.0)] * 4),  # Pareto but negative equal-year mean
    ],
    ids=["tie", "tradeoff", "negative-mean"],
)
def test_no_nomination_for_tie_tradeoff_or_negative_mean(
    base_metrics: list[tuple[float, float]], aligned_metrics: list[tuple[float, float]]
) -> None:
    decision = calendar_pair.select_reference(_windows(base_metrics, aligned_metrics))

    assert decision["state"] == "NO_ECONOMIC_REFERENCE_WINNER"
    assert decision["economic_reference_nominee"] is None


def test_sparse_activity_blocks_nomination() -> None:
    decision = calendar_pair.select_reference(_windows(closes=19))

    assert decision["state"] == "INSUFFICIENT_REFERENCE_ACTIVITY"
    assert decision["economic_reference_nominee"] is None


def test_total_activity_threshold_is_not_replaced_by_each_year_minimum() -> None:
    decision = calendar_pair.select_reference(_windows(closes=20))

    assert decision["state"] == "INSUFFICIENT_REFERENCE_ACTIVITY"
    assert decision["stress_closes_each_arm"] == {arm: 80 for arm in calendar_pair.pair.ARMS}


def test_high_total_does_not_rescue_one_sparse_year() -> None:
    windows = _windows(closes=40)
    for arm in windows[0]["arms"]:
        for cell in arm["economic_results"]:
            cell["closed_trades"] = 19
    decision = calendar_pair.select_reference(windows)

    assert decision["state"] == "INSUFFICIENT_REFERENCE_ACTIVITY"
    assert decision["economic_reference_nominee"] is None


def test_observed_risk_overrun_blocks_otherwise_pareto_nominee() -> None:
    decision = calendar_pair.select_reference(_windows(base_risk_year=2))

    assert decision["state"] == "NO_ECONOMIC_REFERENCE_WINNER"
    assert decision["economic_reference_nominee"] is None


def test_missing_year_or_cost_cell_fails_closed() -> None:
    missing_year = _windows()
    missing_year.pop()
    with pytest.raises(ValueError, match="all four exact years"):
        calendar_pair.select_reference(missing_year)

    missing_cost = _windows()
    missing_cost[0]["arms"][0]["economic_results"].pop()
    with pytest.raises(ValueError, match="both cost cells"):
        calendar_pair.select_reference(missing_cost)


@pytest.mark.parametrize("field", ["forced", "unresolved"])
def test_forced_or_unresolved_position_rejects_reference_decision(field: str) -> None:
    windows = _windows()
    cell = windows[0]["arms"][0]["economic_results"][0]
    if field == "forced":
        cell["forced_settlements"] = 1
    else:
        cell["terminal_unresolved_positions"] = [{"symbol": "SYNTHETIC"}]

    with pytest.raises(ValueError, match="natural complete exits"):
        calendar_pair.select_reference(windows)


def test_run_refuses_source_overlap_before_creating_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan_dir = tmp_path / "plan-source"
    plan_dir.mkdir()
    plan_path = plan_dir / "calendar-plan.json"
    plan_path.write_text("synthetic", encoding="utf-8")
    monkeypatch.setattr(calendar_pair, "load_protocol", lambda _path: ({"max_wall_seconds": 10}, {}))
    monkeypatch.setattr(calendar_pair.pair, "sources", lambda *_args: {"synthetic": True})
    output = plan_dir / "nested-output"

    with pytest.raises(ValueError, match="must not overlap source or cache"):
        calendar_pair.run(plan_path, tmp_path / "bars", tmp_path / "factors", output)

    assert not output.exists()


def test_run_is_create_only_and_preserves_existing_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan_dir = tmp_path / "plan-source"
    plan_dir.mkdir()
    plan_path = plan_dir / "calendar-plan.json"
    plan_path.write_text("synthetic", encoding="utf-8")
    output = tmp_path / "existing-output"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("untouched", encoding="utf-8")
    monkeypatch.setattr(calendar_pair, "load_protocol", lambda _path: ({"max_wall_seconds": 10}, {}))
    monkeypatch.setattr(calendar_pair.pair, "sources", lambda *_args: {"synthetic": True})

    with pytest.raises(FileExistsError):
        calendar_pair.run(plan_path, tmp_path / "bars", tmp_path / "factors", output)

    assert marker.read_text(encoding="utf-8") == "untouched"


@pytest.mark.parametrize("error", [TimeoutError("synthetic deadline"), ValueError("synthetic integrity")])
def test_incomplete_run_retains_failure_without_nomination_or_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: Exception
) -> None:
    import json

    plan_dir = tmp_path / "plan-source"
    plan_dir.mkdir()
    plan_path = plan_dir / "calendar-plan.json"
    plan_path.write_text("synthetic", encoding="utf-8")
    output = tmp_path / "new-output"
    plan = {"max_wall_seconds": 10, "windows": list(calendar_pair.WINDOWS)}
    monkeypatch.setattr(calendar_pair, "load_protocol", lambda _path: (plan, {}))
    monkeypatch.setattr(calendar_pair.pair, "sources", lambda *_args: {"synthetic": True})

    def failed_load(*_args: Any) -> Any:
        raise error

    monkeypatch.setattr(calendar_pair, "load_calendar_window", failed_load)
    with pytest.raises(type(error), match="synthetic"):
        calendar_pair.run(plan_path, tmp_path / "bars", tmp_path / "factors", output)

    failure = json.loads((output / "failure.json").read_text(encoding="utf-8"))
    assert failure["state"] == (
        "INCOMPLETE_RESOURCE_BOUND" if isinstance(error, TimeoutError) else "FAILED_CLOSED"
    )
    assert failure["completed_windows"] == []
    assert failure["economic_reference_nominee"] is None
    assert not (output / "result.json").exists()
