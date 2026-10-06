import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from adaptive_replay import compare

from .test_engine import START, UNIVERSE, bar, inputs_fixture, intent

ROOT = Path(__file__).parents[1]


def copied_plan(tmp_path):
    path = tmp_path / "comparison-plan.json"
    path.write_bytes((ROOT / "comparison-plan.json").read_bytes())
    (tmp_path / "plan.json").write_bytes((ROOT / "plan.json").read_bytes())
    return path


def test_fixed_plan_matches_installed_native_sources_without_changing_defaults():
    plan, base = compare.load_comparison_plan(ROOT / "comparison-plan.json")
    assert plan["arms"] == list(compare.ARMS)
    assert plan["common_admission"]["adaptive_atr15_fill_filter"] is False
    assert plan["readiness"] == base["readiness"]
    assert plan["readiness"]["STRATEGY_POLICY"] == "REJECT_ALL"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["common_admission"].update(minimum_net_reward_to_risk=0),
        lambda p: p["arms"].append("another_strategy"),
        lambda p: p.update(max_wall_seconds=3601),
        lambda p: p.update(no_paid_calls=False),
        lambda p: p.update(native_close_updated_trailing=False),
        lambda p: p["readiness"].update(ALPHA_READY=True),
        lambda p: p["baseline_config_fingerprints"].update(trend_breakout_v1="0" * 64),
        lambda p: p.update(adaptive_evidence_result_sha256="0" * 64),
    ],
)
def test_plan_scope_or_identity_change_fails_closed(tmp_path, mutate):
    path = copied_plan(tmp_path)
    value = json.loads(path.read_text())
    mutate(value)
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        compare.load_comparison_plan(path)


def test_decode_native_adaptive_id_is_unchanged_and_tampering_rejected():
    raw = json.loads(compare.canonical(asdict(intent())))
    assert compare.decode_intent(raw) == intent()
    raw["signal_strength"] = 0.1
    with pytest.raises(ValueError, match="identity"):
        compare.decode_intent(raw)


def test_quiet_slots_recorded_and_duplicate_symbol_slot_rejected(tmp_path):
    inputs = inputs_fixture()
    inputs.evidence = {"kind": "synthetic_verified_input_fixture"}
    inputs.end_ms = START + 300_000
    path = tmp_path / "quiet.jsonl"
    counts = compare.write_tape(path, {}, inputs)
    rows = [json.loads(row) for row in path.read_text().splitlines()]
    assert counts["scheduled_slots"] == len(UNIVERSE)
    assert counts["quiet_slots"] == len(UNIVERSE)
    assert counts["raw_candidates"] == 0
    assert counts["tape_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert all(row["context_cut_ms"] == START - 1 for row in rows)
    with pytest.raises(ValueError, match="duplicate"):
        compare.write_tape(tmp_path / "duplicate.jsonl", {START: [intent(), intent()]}, inputs)


def test_original_tape_result_byte_identity_required_before_import(tmp_path):
    (tmp_path / "result.json").write_text("{}")
    with pytest.raises(ValueError, match="published byte identity"):
        compare.adaptive_tape(tmp_path, inputs_fixture(), {}, {}, float("inf"))


def test_adaptive_tape_revalidates_native_closed_bar_hash_schema(tmp_path, monkeypatch):
    inputs = inputs_fixture()
    inputs.evidence = {"verified": "synthetic"}
    inputs.data_start_ms = START - 120_000
    inputs.end_ms = START + 300_000
    inputs.bars = {symbol: (bar(symbol, START - 120_000), bar(symbol, START - 60_000)) for symbol in UNIVERSE}
    monkeypatch.setattr(compare, "DEFAULT_CONFIG", SimpleNamespace(history_bars=2))
    base = {"strategy_code_sha256": "code", "strategy_config_sha256": "config"}
    window = {"id": "fixture"}
    directory = tmp_path / window["id"]
    directory.mkdir()
    compare.write_json(directory / "inputs.json", inputs.evidence)
    records = []
    for symbol in UNIVERSE:
        value = intent(symbol=symbol) if symbol == "BTCUSDT" else None
        records.append(
            {
                "symbol": symbol,
                "logical_decision_ms": START - 1,
                "context_cut_ms": START - 1,
                "input_window_sha256": compare.adaptive_window_sha256(inputs.bars[symbol]),
                "source_clock_authority": "HISTORICAL_EVENT_TIME_NOT_LIVE_RECEIPT",
                "status": "INTENT" if value else "NO_INTENT",
                "intent": asdict(value) if value else None,
            }
        )
    tape_bytes = b"".join(compare.canonical(row) + b"\n" for row in records)
    (directory / "decisions.jsonl").write_bytes(tape_bytes)
    result = {
        "state": "COMPLETED",
        "sources": {
            "plan_sha256": compare.digest(base),
            "adaptive_identity": {"strategy_code_sha256": "code", "config_sha256": "config"},
        },
        "windows": [
            {
                "window": window,
                "counts": {
                    "tape_sha256": hashlib.sha256(tape_bytes).hexdigest(),
                    "statuses": {"INTENT": 1, "NO_INTENT": 4},
                    "candidates": 1,
                },
            }
        ],
    }
    compare.write_json(tmp_path / "result.json", result)
    monkeypatch.setattr(compare, "ADAPTIVE_RESULT_SHA", compare.file_sha(tmp_path / "result.json"))
    imported, evidence = compare.adaptive_tape(tmp_path, inputs, window, base, float("inf"))
    assert imported[START] == [intent()]
    assert evidence["original_economic_results_reused"] is False
    # Using a different public provenance schema must not pass as the native
    # adaptive closed-bar runtime schema, even for the exact same price rows.
    from kairos_strategy.provenance import input_window_sha256

    monkeypatch.setattr(compare, "adaptive_window_sha256", input_window_sha256)
    with pytest.raises(ValueError, match="closed-history"):
        compare.adaptive_tape(tmp_path, inputs, window, base, float("inf"))


@pytest.mark.parametrize("status", ["WARMUP", "UNAVAILABLE", "NUMERIC_ERROR", "UNKNOWN"])
def test_unavailable_slot_cannot_be_relabelled_no_intent(status):
    with pytest.raises(ValueError, match="silence"):
        compare.require_ready_adaptive_slot({"status": status, "intent": None})


def test_complete_slot_status_must_match_candidate_presence():
    with pytest.raises(ValueError, match="disagree"):
        compare.require_ready_adaptive_slot({"status": "INTENT", "intent": None})


def test_native_missing_candidate_is_not_fabricated_source_availability(tmp_path):
    inputs = inputs_fixture()
    inputs.evidence = {}
    inputs.end_ms = START + 300_000
    path = tmp_path / "native.jsonl"
    counts = compare.write_tape(path, {}, inputs)
    assert counts["source_ready_slots"] is None
    assert counts["source_unavailable_slots"] is None
    assert json.loads(path.read_text().splitlines()[0])["status"] == "NO_CANDIDATE_REPORTED"


def test_comparison_output_cannot_replace_source_or_cached_data(tmp_path, monkeypatch):
    monkeypatch.setattr(compare, "comparison_sources", lambda *args: {})
    path = ROOT / "comparison-plan.json"
    cache = tmp_path / "cache"
    for output in (cache, cache / "result", tmp_path):
        with pytest.raises(ValueError, match="isolated"):
            compare.run(path, cache, tmp_path / "funding", tmp_path / "original", output)


def test_existing_output_is_not_resumed_or_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(compare, "comparison_sources", lambda *args: {})
    output = tmp_path / "retained"
    output.mkdir()
    original = output / "evidence"
    original.write_text("preserve")
    with pytest.raises(FileExistsError):
        compare.run(
            ROOT / "comparison-plan.json",
            tmp_path / "cache",
            tmp_path / "funding",
            tmp_path / "original",
            output,
        )
    assert original.read_text() == "preserve"
