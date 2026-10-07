"""Synthetic CLI/tape tests; never historical economic or paid-call evidence."""

import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from adaptive_replay import historical_pilot_sim as sim
from adaptive_replay.inputs import UNIVERSE
from adaptive_replay.runner import canonical, load_plan, write_json

PROJECT = Path(__file__).resolve().parents[1]
START = 1_621_382_400_000  # approved 2021-05-19 00:00 UTC cut
END = START + 600_000
CUTS = ("2021-05-19T00:00:00Z", "2021-05-19T00:05:00Z")


def native_rows():
    return [
        {
            "symbol": symbol,
            "logical_decision_ms": cut - 1,
            "status": "CANDIDATE" if cut == START and symbol == UNIVERSE[0] else "NO_INTENT",
            "slot_id": hashlib.sha256(f"{cut}:{symbol}".encode()).hexdigest(),
            "intent": {"symbol": symbol, "decision_ts_ms": cut - 1, "intent_id": "fixture-candidate"}
            if cut == START and symbol == UNIVERSE[0]
            else None,
        }
        for cut in range(START, END, 300_000)
        for symbol in UNIVERSE
    ]


def write_native(directory, rows):
    with (directory / "decisions.jsonl").open("xb") as stream:
        for row in rows:
            stream.write(canonical(row) + b"\n")


def emit(directory, rows=None, deadline=None):
    write_native(directory, native_rows() if rows is None else rows)
    inputs = SimpleNamespace(start_ms=START, end_ms=END)
    return sim.emit_denominator(
        inputs, directory, CUTS, time.monotonic() + 30 if deadline is None else deadline
    )


def test_full_denominator_retains_quiet_unscheduled_candidates_and_source_no_call(tmp_path):
    result = emit(tmp_path)
    assert result["rows"] == 50
    assert result["native_decisions"] == 10
    assert result["states"] == {"CANDIDATE": 1, "QUIET": 9, "NOT_SCHEDULED_NATIVE_CADENCE": 40}
    assert result["scheduled_candidates"] == ["fixture-candidate"]
    assert result["scheduled_states"] == {"CANDIDATE": 1, "QUIET": 9}
    assert result["no_call_reasons"] == {"REQUIRED_SOURCE_UNAVAILABLE": 10, "SCHEDULED_POLICY_ABSTAIN": 40}
    assert not result["required_sources_ready"]
    raw = (tmp_path / "denominator.jsonl").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == result["denominator_sha256"]
    assert all(json.loads(line)["model_decision"] is None for line in raw.splitlines())


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "foreign_symbol", "backdate", "moved_candidate"]
)
def test_malformed_native_cells_fail_closed(tmp_path, mutation):
    rows = native_rows()
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(rows[0])
    elif mutation == "foreign_symbol":
        rows[0] = {**rows[0], "symbol": "DOGEUSDT"}
    elif mutation == "backdate":
        rows[0] = {**rows[0], "logical_decision_ms": START - 2}
    else:
        rows[0] = {**rows[0], "intent": {**rows[0]["intent"], "decision_ts_ms": START}}
    with pytest.raises(ValueError):
        emit(tmp_path, rows)
    assert not (tmp_path / "denominator.jsonl").exists()


def test_deadline_and_create_only_keep_prior_evidence(tmp_path):
    with pytest.raises(TimeoutError):
        emit(tmp_path, deadline=time.monotonic() - 1)
    assert not (tmp_path / "denominator.jsonl").exists()
    with pytest.raises(FileExistsError):
        emit(tmp_path)


def test_fixed_protocol_does_not_modify_existing_frozen_plan():
    path = PROJECT / "plan.json"
    before = path.read_bytes()
    plan = load_plan(path)
    protocol = sim.sealed_protocol(plan)
    assert protocol["strategy_id"] == "adaptive_pullback_range_v1"
    assert [w["id"] for w in protocol["episodes"]] == ["episode_a", "episode_d"]
    assert protocol["entry_modes"] == ["STRICT_MINUTE_OPEN", "INTRABAR_OPEN_PROXY"]
    assert protocol["risk_policy"]["per_trade_fraction"] == 0.0025
    assert protocol["risk_policy"]["aggregate_open_fraction"] == 0.01
    assert protocol["review_arms"] == "UNAVAILABLE_NOT_EXECUTED_NOT_ZERO_RETURN"
    assert not protocol["required_news_ready"]
    assert protocol["provider_calls"] == 0
    assert not protocol["parameter_search"]
    assert not protocol["readiness"]["LIVE_READY"]
    assert path.read_bytes() == before


@pytest.mark.parametrize("editable,revision", [(True, sim.LLM_REVISION), (False, "f" * 40)])
def test_installed_llm_must_be_exact_immutable_pin(monkeypatch, editable, revision):
    monkeypatch.setattr(sim, "source_receipt", lambda *_: {})
    monkeypatch.setattr(
        sim,
        "distribution",
        lambda _: SimpleNamespace(
            read_text=lambda _: json.dumps(
                {"vcs_info": {"commit_id": revision}, "dir_info": {"editable": editable}}
            )
        ),
    )
    with pytest.raises(ValueError, match="immutable"):
        sim.installed_sources({}, PROJECT / "plan.json")


def prepare_run(monkeypatch, tmp_path, *, cancel=False, mutate_source=False):
    output = tmp_path / "run"
    draft = PROJECT / "historical-episodes-draft.json"
    path = PROJECT / "plan.json"
    monkeypatch.setattr(sim, "validate_paths", lambda *_: (tmp_path, draft, path))
    identities = iter([{"fixture_source": 1}, {"fixture_source": 2}])
    monkeypatch.setattr(
        sim, "installed_sources", lambda *_: next(identities) if mutate_source else {"fixture": True}
    )
    monkeypatch.setattr(sim, "EPISODES", (("fixture", "2021-05-19", "2021-05-20", *CUTS, "may"),))
    # Macro file semantics are independently tested against real retained digests;
    # this test isolates orchestration and does not claim archive authenticity.
    from adaptive_replay.historical_macro_archive import HistoricalMacroArchive

    monkeypatch.setattr(
        sim,
        "extract",
        lambda *_: HistoricalMacroArchive(
            "fixture",
            "a" * 64,
            "b" * 64,
            "c" * 64,
            "d" * 64,
            "e" * 64,
            (),
            (),
        ),
    )
    inputs = SimpleNamespace(start_ms=START, end_ms=END, evidence={"fixture_only": True})
    monkeypatch.setattr(sim, "load_window", lambda *_: inputs)
    monkeypatch.setattr(sim, "validate_replay_inputs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sim, "_market_summary", lambda *_: {})

    def build(_inputs, directory, _deadline):
        assert (output / "sealed-sim-plan.json").exists()
        assert (output / "before.json").exists()
        if cancel:
            raise KeyboardInterrupt
        write_native(directory, native_rows())
        return {}, {"tape_sha256": hashlib.sha256((directory / "decisions.jsonl").read_bytes()).hexdigest()}

    monkeypatch.setattr(sim, "build_tape", build)
    monkeypatch.setattr(
        sim,
        "replay_tape",
        lambda *_args, **kwargs: (
            {"fixture_only": True, "admission_policy": kwargs["admission_policy"]},
            SimpleNamespace(events=[], trades=[]),
        ),
    )
    return output


def test_cli_orchestration_seals_before_strategy_and_never_imputes_review(monkeypatch, tmp_path):
    output = prepare_run(monkeypatch, tmp_path)
    result = sim.run_sim(tmp_path, output)
    assert result["state"] == "PRICE_SIM_COMPLETED_PAID_MATCHED_AB_BLOCKED"
    assert result["provider_calls"] == result["network_calls"] == result["database_calls"] == 0
    assert result["review_arms"] is None
    assert result["denominator_rows"] == 50
    assert not result["paid_matched_ab_executed"]
    assert len(result["episodes"]["fixture"]["strategy_only"]) == 4
    assert (output / "result.json").exists()


@pytest.mark.parametrize("cancel,mutate_source", [(True, False), (False, True)])
def test_cancel_or_source_mutation_retains_failure_without_success(
    monkeypatch, tmp_path, cancel, mutate_source
):
    output = prepare_run(monkeypatch, tmp_path, cancel=cancel, mutate_source=mutate_source)
    with pytest.raises(KeyboardInterrupt if cancel else ValueError):
        sim.run_sim(tmp_path, output)
    assert not (output / "result.json").exists()
    assert json.loads((output / "failure.json").read_text())["state"] == "FAILED_CLOSED"
    assert (output / "sealed-sim-plan.json").exists()


def test_json_receipt_write_never_replaces_prior_content(tmp_path):
    path = tmp_path / "receipt.json"
    write_json(path, {"fixture": 1})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_json(path, {"fixture": 2})
    assert path.read_bytes() == before


def prepare_cut_audit(monkeypatch, tmp_path, *, mutation=None):
    output = prepare_run(monkeypatch, tmp_path, mutate_source=mutation == "source")
    rows = [SimpleNamespace(close_time_ms=START - 1)] * sim.DEFAULT_CONFIG.history_bars
    inputs = SimpleNamespace(
        start_ms=START,
        end_ms=END,
        data_start_ms=START - sim.DEFAULT_CONFIG.history_bars * 60_000,
        bars={
            symbol: rows + [SimpleNamespace(close_time_ms=START + i * 60_000 - 1) for i in range(1, 11)]
            for symbol in UNIVERSE
        },
        evidence={"fixture_only": True},
    )
    loads = 0

    def load(*_):
        nonlocal loads
        loads += 1
        return (
            SimpleNamespace(**{**vars(inputs), "evidence": {"changed": True}})
            if mutation == "cache" and loads > 1
            else inputs
        )

    monkeypatch.setattr(sim, "load_window", load)
    calls = []

    def evaluate(prefix):
        assert (output / "sealed-cut-plan.json").exists()
        assert (output / "before.json").exists()
        calls.append(prefix[-1].close_time_ms)
        if mutation == "cancel":
            raise KeyboardInterrupt
        if mutation == "deadline":
            raise TimeoutError
        return SimpleNamespace(
            status="NO_INTENT",
            reason="fixture_only",
            intent=None,
            decision_ts_ms=prefix[-1].close_time_ms - (1 if mutation == "anchor" else 0),
            input_window_sha256="a" * 64,
        )

    monkeypatch.setattr(sim, "evaluate_adaptive", evaluate)
    monkeypatch.setattr(sim, "build_tape", lambda *_: pytest.fail("cut audit must not replay full tape"))
    monkeypatch.setattr(sim, "replay_tape", lambda *_: pytest.fail("cut audit must not run economics"))
    return output, calls


def test_cut_audit_only_evaluates_fixed_cells_without_economics_or_quiet_imputation(monkeypatch, tmp_path):
    output, calls = prepare_cut_audit(monkeypatch, tmp_path)
    result = sim.run_cut_audit(tmp_path, output)
    assert calls == [START - 1] * 5 + [START + 300_000 - 1] * 5
    assert result["evaluated_cut_cells"] == 10  # one synthetic episode, not historical evidence
    assert result["candidate_count"] == 0
    assert result["economic_results"] is result["review_arms"] is None
    assert result["provider_calls"] == result["network_calls"] == result["database_calls"] == 0
    assert result["other_original_cells"] == "NOT_EVALUATED_NOT_IMPUTED_QUIET"
    protocol = json.loads((output / "sealed-cut-plan.json").read_text())
    assert not protocol["economic_replay"]
    assert protocol["max_wall_seconds"] == 120
    assert not result["readiness"]["LIVE_READY"]
    assert (output / "result.json").exists()
    before = (output / "result.json").read_bytes()
    with pytest.raises(FileExistsError):
        sim.run_cut_audit(tmp_path, output)
    assert (output / "result.json").read_bytes() == before


@pytest.mark.parametrize("mutation", ["source", "cache", "anchor", "cancel", "deadline"])
def test_cut_audit_failure_preserves_seal_and_never_writes_success(monkeypatch, tmp_path, mutation):
    output, _ = prepare_cut_audit(monkeypatch, tmp_path, mutation=mutation)
    error = (
        KeyboardInterrupt if mutation == "cancel" else TimeoutError if mutation == "deadline" else ValueError
    )
    with pytest.raises(error):
        sim.run_cut_audit(tmp_path, output)
    assert not (output / "result.json").exists()
    assert (output / "sealed-cut-plan.json").exists()
    assert json.loads((output / "failure.json").read_text())["state"] == "FAILED_CLOSED"


def test_cut_audit_final_source_hashing_cannot_exceed_deadline(monkeypatch, tmp_path):
    output, _ = prepare_cut_audit(monkeypatch, tmp_path)
    now = [0.0]
    source_calls = [0]
    monkeypatch.setattr(sim.time, "monotonic", lambda: now[0])

    def sources(*_):
        source_calls[0] += 1
        if source_calls[0] == 2:
            now[0] = 121.0
        return {"fixture": True}

    monkeypatch.setattr(sim, "installed_sources", sources)
    with pytest.raises(TimeoutError):
        sim.run_cut_audit(tmp_path, output)
    assert not (output / "result.json").exists()
    assert json.loads((output / "failure.json").read_text())["error_type"] == "TimeoutError"
