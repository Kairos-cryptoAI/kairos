from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from adaptive_replay import runner
from adaptive_replay.inputs import UNIVERSE

PLAN_PATH = Path(__file__).parents[1] / "plan.json"


def _plan() -> dict[str, Any]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def _write_plan(tmp_path: Path, plan: dict[str, Any]) -> Path:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    (tmp_path / "uv.lock").write_text("fixture lock", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["risk_policy"].update(per_trade_fraction=0.5),
        lambda p: p["windows"][0].update(start="2021-11-06"),
        lambda p: p.update(pipeline_latency_ms_assumed=0),
        lambda p: p["readiness"].update(ALPHA_READY=True),
    ],
)
def test_load_plan_rejects_scope_or_safety_weakening(tmp_path: Path, change: Any) -> None:
    plan = _plan()
    change(plan)
    with pytest.raises(ValueError):
        runner.load_plan(_write_plan(tmp_path, plan))


@dataclass(frozen=True)
class _Identity:
    strategy_code_sha256: str
    config_sha256: str
    detector_code_sha256: str
    detector_config_sha256: str


def test_source_receipt_binds_live_strategy_and_immutable_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan = _plan()
    expected_strategy = plan["strategy_code_sha256"]
    expected_config = plan["strategy_config_sha256"]
    monkeypatch.setattr(
        runner,
        "adaptive_source_identity",
        lambda: _Identity(expected_strategy, expected_config, expected_strategy, expected_config),
    )

    class Distribution:
        version = "0.1.0"

        def __init__(self, package: str) -> None:
            self.package = package

        def read_text(self, _name: str) -> str:
            return json.dumps(
                {
                    "vcs_info": {"commit_id": plan["source_revisions"][self.package]},
                    "dir_info": {"editable": False},
                }
            )

    monkeypatch.setattr(runner, "distribution", lambda package: Distribution(package))
    path = _write_plan(tmp_path, plan)
    receipt = runner.source_receipt(plan, path)
    assert receipt["adaptive_identity"]["strategy_code_sha256"] == expected_strategy
    assert receipt["adaptive_identity"]["config_sha256"] == expected_config
    assert (
        receipt["installed_dependencies"]["kairos-backtest"]["revision"]
        == plan["source_revisions"]["kairos-backtest"]
    )
    assert (
        receipt["dependency_projection"] == "EXPLICIT_DEVELOPMENT_OVERRIDES_NOT_FROZEN_CAMPAIGN_ENVIRONMENT"
    )
    assert receipt["uv_lock_sha256"]


def test_installed_source_receipt_matches_selected_immutable_source() -> None:
    plan = _plan()
    receipt = runner.source_receipt(plan, PLAN_PATH)
    identity = receipt["adaptive_identity"]
    assert identity["strategy_code_sha256"] == plan["strategy_code_sha256"]
    assert identity["config_sha256"] == plan["strategy_config_sha256"]
    assert {package: item["revision"] for package, item in receipt["installed_dependencies"].items()} == plan[
        "source_revisions"
    ]


@pytest.mark.parametrize("field", ["strategy_code_sha256", "config_sha256"])
def test_source_drift_refused_before_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, field: str
) -> None:
    plan = _plan()
    wrong = "0" * 64
    monkeypatch.setattr(
        runner,
        "adaptive_source_identity",
        lambda: _Identity(
            wrong if field == "strategy_code_sha256" else plan["strategy_code_sha256"],
            wrong if field == "config_sha256" else plan["strategy_config_sha256"],
            wrong,
            wrong,
        ),
    )
    with pytest.raises(ValueError, match="selected strategy"):
        runner.source_receipt(plan, _write_plan(tmp_path, plan))


def test_source_receipt_refuses_mutable_dependency_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan = _plan()
    monkeypatch.setattr(
        runner,
        "adaptive_source_identity",
        lambda: _Identity(
            plan["strategy_code_sha256"],
            plan["strategy_config_sha256"],
            plan["strategy_code_sha256"],
            plan["strategy_config_sha256"],
        ),
    )

    class EditableDistribution:
        version = "0.1.0"

        def read_text(self, _name: str) -> str:
            return json.dumps(
                {
                    "vcs_info": {"commit_id": plan["source_revisions"]["kairos-backtest"]},
                    "dir_info": {"editable": True},
                }
            )

    monkeypatch.setattr(runner, "distribution", lambda _package: EditableDistribution())
    with pytest.raises(ValueError, match="immutable installed dependency mismatch"):
        runner.source_receipt(plan, _write_plan(tmp_path, plan))


def test_existing_output_is_never_overwritten(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = tmp_path / "already-there"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("untouched", encoding="utf-8")
    monkeypatch.setattr(runner, "load_plan", lambda _path: {})
    monkeypatch.setattr(runner, "source_receipt", lambda _plan, _path: {})
    with pytest.raises(FileExistsError):
        runner.run(tmp_path / "plan", tmp_path / "bars", tmp_path / "factors", output)
    assert marker.read_text(encoding="utf-8") == "untouched"


def test_cached_integrity_failure_is_retained_with_null_economics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan = _plan()
    plan["windows"] = plan["windows"][:1]
    path = _write_plan(tmp_path, plan)
    monkeypatch.setattr(runner, "load_plan", lambda _path: plan)
    monkeypatch.setattr(runner, "source_receipt", lambda _plan, _path: {"pinned": True})
    monkeypatch.setattr(
        runner,
        "load_window",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("synthetic checksum/gap integrity failure")
        ),
    )
    output = tmp_path / "failed-input-run"
    assert runner.run(path, tmp_path / "bars", tmp_path / "factors", output) == 2
    blocked = json.loads((output / "late_2021" / "blocked.json").read_text(encoding="utf-8"))
    result = json.loads((output / "result.json").read_text(encoding="utf-8"))
    assert blocked["state"] == "BLOCKED_INPUT_INTEGRITY"
    assert blocked["economic_results"] is None
    assert result["state"] == "COMPLETED_WITH_BLOCKED_INPUTS"
    assert result["windows"][0]["state"] == "BLOCKED_INPUT_INTEGRITY"
    assert result["windows"][0]["economic_results"] is None


def test_build_tape_counts_quiet_and_unavailable_separately_and_skips_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    @dataclass
    class Intent:
        intent_id: str

    class Regime:
        value = "UNKNOWN"

    class Status:
        def __init__(self, value: str) -> None:
            self.value = value

        def __str__(self) -> str:
            return self.value

    class Decision:
        def __init__(self, ts: int, status: str, intent: Any = None) -> None:
            self.decision_ts_ms = ts - 1
            self.input_window_sha256 = "a" * 64
            self.status = Status(status)
            self.reason = status.lower()
            self.regime = Regime()
            self.intent = intent

    decisions = iter(
        [
            Decision(300_000, "UNAVAILABLE"),
            Decision(300_000, "QUIET"),
            Decision(300_000, "QUIET"),
            Decision(300_000, "CANDIDATE", Intent("x")),
            Decision(300_000, "QUIET"),
        ]
    )
    monkeypatch.setattr(runner, "evaluate_adaptive", lambda _rows: next(decisions))
    monkeypatch.setattr(runner.time, "monotonic", lambda: 1.0)
    rows = {symbol: tuple(range(4_000)) for symbol in UNIVERSE}
    inputs = SimpleNamespace(bars=rows, start_ms=300_000, end_ms=600_000, data_start_ms=0)
    out = tmp_path / "tape"
    out.mkdir()
    tape, counts = runner.build_tape(inputs, out, 2.0)
    assert counts["scheduled_slots"] == 5
    assert counts["statuses"] == {"CANDIDATE": 1, "QUIET": 3, "UNAVAILABLE": 1}
    assert counts["candidates"] == 1
    assert counts["warmup_slots"] == 0
    assert counts["decisions_in_exit_tail"] == 0
    assert sum(len(items) for items in tape.values()) == 1
    decisions_written = (out / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(decisions_written) == 5
    assert all(json.loads(item)["logical_decision_ms"] == 299_999 for item in decisions_written)
