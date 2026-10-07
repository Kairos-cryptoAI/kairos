"""Actual compact preparation is byte-bound, causal and explicitly not admission."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from adaptive_replay.complex_protocol import EPISODES, READINESS, fixed_protocol, utc_ms
from adaptive_replay.historical_context import canonical, digest
from adaptive_replay.inputs import UNIVERSE

ROOT = Path(__file__).parents[1] / "evidence/compact-context-2026-10-07"


def read(name: str):
    return json.loads((ROOT / name).read_bytes())


def test_original_preparation_files_are_exactly_byte_bound() -> None:
    manifest = read("checksums.json")
    assert manifest["scope"] == "SHA256_OF_ORIGINAL_PREPARATION_BYTES_NOT_SOURCE_AUTHENTICITY"
    assert manifest["original_file_count"] == len(manifest["files"]) == 27
    assert {p.name for p in ROOT.iterdir() if p.is_file()} == {"checksums.json", *manifest["files"]}
    for name, expected in manifest["files"].items():
        assert Path(name).name == name and "\\" not in name and ".." not in Path(name).parts
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected


def test_source_protocol_and_actual_clocks_remain_sealed() -> None:
    result, before, after, protocol = (
        read(name) for name in ("result.json", "before.json", "after.json", "protocol.json")
    )
    assert protocol == fixed_protocol()
    assert digest(protocol) == result["protocol_sha256"] == before["protocol_sha256"]
    assert before["sources"] == after["sources"]
    assert result["source_receipt_unchanged"] and after["source_receipt_unchanged"]
    modules = before["sources"]["replay_modules_sha256"]
    assert {
        f"complex_{part}.py"
        for part in ("assessment", "dispatch", "frame", "prepare", "protocol", "replay", "strategy")
    } <= set(modules)
    assert before["actual_started_utc"] == result["actual_started_utc"]
    assert (
        datetime.fromisoformat(result["actual_started_utc"])
        < datetime.fromisoformat(after["actual_finished_utc"])
        <= datetime.fromisoformat(result["actual_finished_utc"])
    )
    assert 0 < result["elapsed_seconds"] < 300


def test_exact_sparse_roster_has_causal_strategy_blind_prompts() -> None:
    cells, result = read("cells.json"), read("result.json")
    expected = {
        (episode, utc_ms(cut), symbol)
        for episode, _, _, cuts, _ in EPISODES
        for cut in cuts
        for symbol in UNIVERSE
    }
    assert len(cells) == len({c["slot_id"] for c in cells}) == len(expected) == 20
    assert {(c["episode"], c["cut_ms"], c["symbol"]) for c in cells} == expected
    assert digest(cells) == result["cells_sha256"]
    for cell in cells:
        cut, history = cell["cut_ms"], cell["history"]
        assert history["cutoff_ms"] == cut and history["last_closed_ms"] == cut - 1
        assert history["first_open_ms"] == cut - 3240 * 60_000
        assert history["captured_at_ms"] > cut and history["provenance"] == "HISTORICAL_ARCHIVE"
        prompt = read(cell["prompt_filename"])
        assert digest(prompt) == cell["prompt_sha256"]
        assert len(canonical(prompt).encode()) == cell["prompt_canonical_utf8_bytes"]
        assert digest({"prompt": prompt, "protocol_sha256": result["protocol_sha256"]}) == cell["frame_id"]
        assert set(prompt) == {
            "schema",
            "symbol",
            "knowledge_cut_ms",
            "market_prices",
            "context",
            "assessment_contract",
            "source_text_is_untrusted_data",
        }
        assert prompt["knowledge_cut_ms"] == cut and prompt["symbol"] == cell["symbol"]
        assert prompt["source_text_is_untrusted_data"] is True
        for timeframe, rows in prompt["market_prices"].items():
            minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}[timeframe]
            assert len(rows) in (
                {53, 54} if timeframe == "1h" else {"1m": {30}, "5m": {24}, "15m": {16}}[timeframe]
            )
            for i, row in enumerate(rows):
                assert set(row) == {"open_time_ms", "close_time_ms", "open", "high", "low", "close"}
                assert row["close_time_ms"] - row["open_time_ms"] == minutes * 60_000 - 1
                assert row["close_time_ms"] < cut
                if i:
                    assert row["open_time_ms"] == rows[i - 1]["close_time_ms"] + 1
        market = read(f"{cell['episode']}-inputs.json")["market"][cell["symbol"]]
        assert market["bars"] == 12960 and market["funding"] == 27 and market["gaps"] == 0
        assert history["source_artifact_sha256"] == market["bar_rows_sha256"]


def test_unavailable_sources_and_quiet_cells_do_not_become_model_results() -> None:
    result = read("result.json")
    assert result["state"] == "ENGINEERING_PREPARED_MODEL_EXECUTION_NOT_ADMITTED"
    assert result["technical_states"] == {"QUIET": 20}
    assert result["scheduled_cells"] == 20 and result["required_sources_ready_cells"] == 0
    assert (
        result["provider_calls"] == result["provider_cost_usd"] == result["blind_campaign_credit_days"] == 0
    )
    assert result["unevaluated_slots_are_not_quiet"] is True
    for name in (
        "paid_run_executed",
        "economic_replay_executed",
        "budget_created_or_reset",
        "model_execution_admitted",
        "fresh_owner_confirmation_received",
        "source_authenticity_admitted",
        "shared_budget_identity_admitted",
        "historical_receive_clock_proven",
        "training_contamination_excluded",
    ):
        assert result[name] is False
    assert {name: result[name] for name in READINESS} == READINESS
    for cell in read("cells.json"):
        assert cell["call_status"] == "NOT_CALLED" and cell["no_call_reason"] == "REQUIRED_SOURCE_UNAVAILABLE"
        assert cell["model_result"] is cell["model_arm_economics"] is None
        assert cell["provider_calls"] == cell["provider_cost_usd"] == 0
        assert cell["required_sources_ready"] is cell["source_authenticity_admitted"] is False
        assert cell["technical"]["state"] == "QUIET" and cell["technical"]["candidate"] is None
        assert cell["technical"]["candidate_ids"] == cell["technical"]["dropped_ids"] == []
        sources = read(cell["prompt_filename"])["context"]["sources"]
        assert {source["kind"] for source in sources} == {"NEWS", "MACRO"}
        assert all(
            source["required"]
            and source["state"] == "UNAVAILABLE"
            and source["reason"] == "UNVERIFIED_SOURCE_COVERAGE"
            and source["items"] == []
            for source in sources
        )
