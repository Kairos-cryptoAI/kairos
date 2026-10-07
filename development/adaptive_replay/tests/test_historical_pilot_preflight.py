"""Offline guards for the bounded no-call historical pilot preflight."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from adaptive_replay import historical_pilot_preflight as preflight

PLAN = Path(__file__).parents[1] / "historical-episodes-draft.json"


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "Kairos"
    repo = workspace / "kairos"
    (repo / "development" / "adaptive_replay").mkdir(parents=True)
    (workspace / "runtime").mkdir()
    (repo / "development" / "adaptive_replay" / "historical-episodes-draft.json").write_bytes(
        PLAN.read_bytes()
    )
    (repo / "development" / "adaptive_replay" / "plan.json").write_text("{}", encoding="utf-8")
    return workspace, repo / "development" / "adaptive_replay" / "historical-episodes-draft.json"


def test_fixed_windows_cuts_and_counts() -> None:
    assert tuple(item[:3] for item in preflight.EPISODES) == (
        ("episode_a", "2021-05-17", "2021-05-22"),
        ("episode_d", "2024-01-08", "2024-01-13"),
    )
    assert (
        sum(
            (preflight._utc_ms(item[2] + "T00:00:00Z") - preflight._utc_ms(item[1] + "T00:00:00Z"))
            // 60_000
            * 5
            for item in preflight.EPISODES
        )
        == 72_000
    )
    assert sum(len(preflight.EXPECTED_CUTS[item[0]]) * 5 for item in preflight.EPISODES) == 20
    assert all(
        preflight._utc_ms(cut) % 60_000 == 0 for cuts in preflight.EXPECTED_CUTS.values() for cut in cuts
    )


def test_mutated_pilot_plan_is_rejected(tmp_path: Path) -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    plan["low_cost_pilot"]["maximum_paid_requests_total"] = 21
    path = tmp_path / "draft.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="fixed source-gated"):
        preflight.validate_pilot_plan(path)


def test_paths_require_task_owned_new_direct_runtime_child(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path)
    good = workspace / "runtime" / "new-preflight"
    assert preflight.validate_paths(workspace, good)[0] == workspace.resolve()
    with pytest.raises(ValueError, match="direct child"):
        preflight.validate_paths(workspace, workspace / "other" / "nested")
    good.mkdir()
    with pytest.raises(FileExistsError, match="must not exist"):
        preflight.validate_paths(workspace, good)


def test_stream_preserves_exclusive_window_and_fixed_no_call_rows(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    start = preflight._utc_ms("2021-05-19T00:00:00Z")
    end = start + 6 * 60_000
    preflight._stream_rows(
        path, "episode_a", start, end, ("2021-05-19T00:00:00Z", "2021-05-19T00:05:00Z"), 10.0, lambda: 0.0
    )
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 6 * len(preflight.UNIVERSE)
    assert {row["minute_open_ms"] for row in rows} == {start + minute * 60_000 for minute in range(6)}
    assert all(row["source_ready"] is False and row["source_state"] == "UNKNOWN" for row in rows)
    assert all(row["required_sources_ready"] is False for row in rows)
    assert all(row["required_source_coverage"] == {"NEWS": "UNKNOWN", "MACRO": "UNKNOWN"} for row in rows)
    assert all(row["call_status"] == "NOT_CALLED" and row["paid_run_executed"] is False for row in rows)
    assert all(row["candidate_status"] == "NOT_EVALUATED" and row["candidate_count"] is None for row in rows)
    assert all(row["model_decision"] is None and row["economic_result"] is None for row in rows)
    assert all(
        row["historical_receive_clock_proven"] is False and row["provider_cost_usd"] == 0 for row in rows
    )
    cut_rows = [row for row in rows if row["minute_open_ms"] == start]
    assert len(cut_rows) == 5
    assert all(row["no_call_reason"] == "REQUIRED_SOURCE_UNAVAILABLE" for row in cut_rows)
    assert sum(row["no_call_reason"] == "REQUIRED_SOURCE_UNAVAILABLE" for row in rows) == 10
    assert all(
        row["no_call_reason"] == "SCHEDULED_POLICY_ABSTAIN"
        for row in rows
        if row["minute_open_ms"] not in {start, start + 5 * 60_000}
    )


def test_stream_obeys_deadline_and_is_create_only(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    now = iter((0.0, 11.0))
    with pytest.raises(TimeoutError):
        preflight._stream_rows(
            path,
            "episode_a",
            0,
            6 * 60_000,
            ("1970-01-01T00:00:00Z", "1970-01-01T00:05:00Z"),
            10.0,
            lambda: next(now),
        )
    assert path.exists()
    with pytest.raises(FileExistsError):
        preflight._stream_rows(
            path,
            "episode_a",
            0,
            6 * 60_000,
            ("1970-01-01T00:00:00Z", "1970-01-01T00:05:00Z"),
            10.0,
            lambda: 0.0,
        )


def _fake_inputs() -> SimpleNamespace:
    return SimpleNamespace(
        evidence={
            "bars": {
                symbol: {"gaps": 0, "normalized_rows_sha256": "a" * 64} for symbol in preflight.UNIVERSE
            },
            "funding": {symbol: {"normalized_rows_sha256": "b" * 64} for symbol in preflight.UNIVERSE},
        },
        bars={symbol: (None,) * 12_960 for symbol in preflight.UNIVERSE},
        funding={symbol: (None,) * 27 for symbol in preflight.UNIVERSE},
    )


def _patch_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        preflight,
        "load_plan",
        lambda _path: {"readiness": {"STRATEGY_POLICY": "REJECT_ALL", "LIVE_READY": False}},
    )
    monkeypatch.setattr(preflight, "source_receipt", lambda *_args: {"identity": "test"})
    monkeypatch.setattr(preflight, "load_window", lambda *_args: _fake_inputs())
    monkeypatch.setattr(preflight, "validate_replay_inputs", lambda *_args, **_kwargs: None)


def test_completed_preflight_streams_exact_full_denominator_and_twenty_cuts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace, _ = _workspace(tmp_path)
    output = workspace / "runtime" / "preflight"
    _patch_preflight(monkeypatch)
    validation_calls: list[tuple[bool, float]] = []
    monkeypatch.setattr(
        preflight,
        "validate_replay_inputs",
        lambda _inputs, *, fixture_only, deadline: validation_calls.append((fixture_only, deadline)),
    )
    result = preflight.run_preflight(workspace, output, clock=lambda: 1.0)
    assert len(validation_calls) == 2 and all(fixture_only is False for fixture_only, _ in validation_calls)
    assert result["state"] == "PREFLIGHT_COMPLETED_PAID_RUN_BLOCKED"
    assert result["purpose"].endswith("NOT_THE_REQUESTED_PAID_LLM_OR_ECONOMIC_RUN")
    assert result["denominator_rows_total"] == 72_000
    assert result["scheduled_symbol_cut_records_total"] == 20
    assert result["provider_calls"] == result["database_calls"] == result["network_calls"] == 0
    assert result["paid_run_executed"] is False and result["economics_executed"] is False
    assert result["readiness"] == {"STRATEGY_POLICY": "REJECT_ALL", "LIVE_READY": False}
    total = required = abstain = 0
    unique: set[tuple[str, int, str]] = set()
    for episode in ("episode_a", "episode_d"):
        rows_path = output / episode / "source-no-call-rows.jsonl"
        digest = hashlib.sha256()
        for line in rows_path.open(encoding="utf-8"):
            digest.update(line.encode("utf-8"))
            row = json.loads(line)
            total += 1
            key = (row["episode"], row["minute_open_ms"], row["symbol"])
            assert key not in unique
            unique.add(key)
            required += row["no_call_reason"] == "REQUIRED_SOURCE_UNAVAILABLE"
            abstain += row["no_call_reason"] == "SCHEDULED_POLICY_ABSTAIN"
            assert row["candidate_status"] == "NOT_EVALUATED"
            assert row["candidate_count"] is None and row["candidate"] is None
            assert row["model_decision"] is None and row["provider_calls"] == 0
            assert row["provider_cost_usd"] == 0 and row["history_local_receipt_proven"] is False
            assert row["required_sources_ready"] is False
            assert row["required_source_coverage"] == {"NEWS": "UNKNOWN", "MACRO": "UNKNOWN"}
            assert row["historical_receive_clock_proven"] is False
        assert digest.hexdigest() == result["episodes"][episode]["row_stream_sha256"]
    assert (total, required, abstain) == (72_000, 20, 71_980)
    assert len(unique) == 72_000
    assert (output / "preflight-summary.json").is_file()
    assert not (output / "preflight-summary.json.partial").exists()


def test_input_failure_is_not_promoted_to_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path)
    output = workspace / "runtime" / "preflight"
    _patch_preflight(monkeypatch)
    loads = 0

    def load_then_fail(*_args: object) -> SimpleNamespace:
        nonlocal loads
        loads += 1
        if loads == 1:
            return _fake_inputs()
        raise FileNotFoundError

    def partial_stream(path: Path, *_args: object) -> str:
        with path.open("x", encoding="utf-8") as stream:
            stream.write("partial evidence\n")
        return "c" * 64

    monkeypatch.setattr(preflight, "load_window", load_then_fail)
    monkeypatch.setattr(preflight, "_stream_rows", partial_stream)
    with pytest.raises(FileNotFoundError):
        preflight.run_preflight(workspace, output, clock=lambda: 1.0)
    assert (output / "failure.json").is_file()
    assert not (output / "preflight-summary.json").exists()
    failure = json.loads((output / "failure.json").read_text(encoding="utf-8"))
    assert failure["state"] == "FAILED_NO_SUCCESS_RECEIPT"
    assert failure["provider_calls"] == failure["database_calls"] == failure["network_calls"] == 0
    assert failure["completed_row_streams"] == {"episode_a": "c" * 64}
    assert (output / "episode_a" / "source-no-call-rows.jsonl").is_file()


def test_changed_source_identity_does_not_emit_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace, _ = _workspace(tmp_path)
    output = workspace / "runtime" / "preflight"
    _patch_preflight(monkeypatch)
    calls = iter(({"identity": "before"}, {"identity": "after"}))
    monkeypatch.setattr(preflight, "source_receipt", lambda *_args: next(calls))
    monkeypatch.setattr(preflight, "_stream_rows", lambda *_args: "0" * 64)
    with pytest.raises(ValueError, match="identity changed"):
        preflight.run_preflight(workspace, output, clock=lambda: 1.0)
    assert (output / "failure.json").is_file()
    assert not (output / "preflight-summary.json").exists()


def test_duplicate_json_keys_and_episode_ids_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON keys"):
        preflight.validate_pilot_plan(path)

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    plan["episodes"].append(dict(plan["episodes"][0]))
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate episode ids"):
        preflight.validate_pilot_plan(path)
