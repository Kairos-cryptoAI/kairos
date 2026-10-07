import json
from pathlib import Path

import pytest
from kairos_strategy.candles import Candle

from adaptive_replay import complex_prepare as cp
from adaptive_replay.complex_protocol import EPISODES, protocol_sha256, utc_ms
from adaptive_replay.complex_strategy import ComplexDecision
from adaptive_replay.inputs import UNIVERSE, WindowInputs


def workspace(tmp_path):
    root = tmp_path / "workspace"
    (root / "runtime").mkdir(parents=True)
    plans = root / "kairos" / "development" / "adaptive_replay"
    plans.mkdir(parents=True)
    (plans / "plan.json").write_text("{}", encoding="utf-8")
    return root, root / "runtime" / "compact-context-preparation-20261007-fixture"


def mock_sources(monkeypatch):
    monkeypatch.setattr(cp, "load_plan", lambda path: {})
    monkeypatch.setattr(cp, "installed_sources", lambda *args: {"fixture_sources": "a" * 64})
    monkeypatch.setattr(cp, "validate_replay_inputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cp,
        "_market_summary",
        lambda inputs: {
            s: {"bar_rows_sha256": "b" * 64, "bars": len(rows), "gaps": 0} for s, rows in inputs.bars.items()
        },
    )

    def load(*args):
        window = args[2]
        start, end = utc_ms(window["start"]), utc_ms(window["end_exclusive"])
        origin = start - 54 * 3_600_000
        bars = {
            s: tuple(
                Candle(s, "1m", t, t + 59_999, 100, 101, 99, 100, 10)
                for t in range(origin, end + 3 * 3_600_000, 60_000)
            )
            for s in UNIVERSE
        }
        return WindowInputs(
            bars,
            {s: () for s in UNIVERSE},
            {"fixture": window["id"]},
            start,
            end,
            origin,
            end + 3 * 3_600_000,
        )

    monkeypatch.setattr(cp, "load_window", load)
    monkeypatch.setattr(
        cp,
        "evaluate_complex",
        lambda prefix, **kwargs: ComplexDecision(
            prefix[-1].symbol,
            kwargs["cut_ms"],
            "QUIET",
            "NO_TECHNICAL_CANDIDATE",
            "RANGE",
            "NORMAL",
            None,
            (),
            (),
            "c" * 64,
            "d" * 64,
        ),
    )


def test_preparation_is_create_only_offline_complete_roster_not_admission(tmp_path, monkeypatch):
    root, output = workspace(tmp_path)
    mock_sources(monkeypatch)
    result = cp.prepare(root, output)
    assert result["scheduled_cells"] == 20
    assert result["source_receipt_unchanged"]
    assert result["protocol_sha256"] == protocol_sha256()
    assert result["provider_calls"] == 0 and not result["model_execution_admitted"]
    assert not result["budget_created_or_reset"] and not result["economic_replay_executed"]
    assert not result["fresh_owner_confirmation_received"]
    cells = json.loads((output / "cells.json").read_text(encoding="utf-8"))
    assert len(cells) == len({c["slot_id"] for c in cells}) == 20
    assert {c["episode"] for c in cells} == {e[0] for e in EPISODES}
    assert all(c["no_call_reason"] == "REQUIRED_SOURCE_UNAVAILABLE" for c in cells)
    assert all(c["model_arm_economics"] is None for c in cells)
    assert len(list(output.glob("*-prompt.json"))) == 20
    with pytest.raises(FileExistsError):
        cp.prepare(root, output)
    assert not (root / "runtime" / "historical-pilot-budget.sqlite").exists()


def test_missing_inputs_fail_closed_and_keep_partial_receipts(tmp_path, monkeypatch):
    root, output = workspace(tmp_path)
    mock_sources(monkeypatch)

    def fail(*args):
        raise FileNotFoundError("fixture missing input")

    monkeypatch.setattr(cp, "load_window", fail)
    with pytest.raises(FileNotFoundError):
        cp.prepare(root, output)
    failure = json.loads((output / "failure.json").read_text(encoding="utf-8"))
    assert failure["state"] == "FAILED_CLOSED" and failure["partial_receipts_retained"]
    assert failure["provider_calls"] == 0
    assert (output / "before.json").is_file() and (output / "protocol.json").is_file()
    assert not (output / "result.json").exists()


def test_preparation_rejects_broad_paths_and_unpinned_archives(tmp_path):
    root, output = workspace(tmp_path)
    with pytest.raises(ValueError, match="specifically named"):
        cp.validate_paths(root, root / "runtime")
    with pytest.raises(ValueError, match="absolute"):
        cp.validate_paths(Path("relative"), output)
    with pytest.raises(ValueError, match="together"):
        cp.prepare(root, output, archive_path=output / "anything.json")
    assert not output.exists()


def test_cli_has_no_run_models_or_confirmation_bypass_flag():
    with pytest.raises(SystemExit):
        cp.main(["--run-models"])


def test_fixed_protocol_has_no_new_budget_or_income_guarantee():
    protocol = cp.fixed_protocol()
    assert protocol["budget"]["maximum_total_attempts"] == 20
    assert protocol["budget"]["maximum_total_usd"] == 1
    assert not protocol["budget"]["additional_budget_granted"]
    assert protocol["model_roles_statistically_independent"] is False
    assert protocol["complex"]["fixed_income_target"] is None
    assert protocol["owner_confirmation_required_before_models"]
