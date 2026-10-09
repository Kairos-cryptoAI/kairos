"""Focused offline invariants for the fixed price-only scenario comparison."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent

from adaptive_replay import scenario_compare as compare
from adaptive_replay.complex_strategy import HISTORY_BARS, ComplexDecision
from adaptive_replay.inputs import UNIVERSE, WindowInputs
from adaptive_replay.scenario_bridge import ScenarioPreparation
from adaptive_replay.scenarios import ScenarioPlan

MINUTE = 60_000
START = int(datetime(2022, 6, 13, tzinfo=UTC).timestamp() * 1_000)
HASH_A, HASH_B = "a" * 64, "b" * 64


def _inputs() -> WindowInputs:
    data_start = START - HISTORY_BARS * MINUTE
    # The scored five-minute cell plus the full three-hour exit tail.
    count = HISTORY_BARS + 5 + 180
    bars = {}
    for symbol in UNIVERSE:
        rows = []
        for index in range(count):
            opened = data_start + index * MINUTE
            close = 100.5 if symbol == UNIVERSE[0] and index == HISTORY_BARS else 100.0
            rows.append(
                Candle(symbol, "1m", opened, opened + MINUTE - 1, 100.0, max(101.0, close), 99.0, close, 10.0)
            )
        bars[symbol] = tuple(rows)
    return WindowInputs(
        bars,
        {symbol: () for symbol in UNIVERSE},
        {},
        START,
        START + 5 * MINUTE,
        data_start,
        data_start + count * MINUTE,
    )


def _decision(symbol: str, cut: int, candidate: SleeveIntent | None = None) -> ComplexDecision:
    return ComplexDecision(
        symbol,
        cut,
        "CANDIDATE" if candidate else "QUIET",
        "TECHNICAL_SELECTED" if candidate else "NO_TECHNICAL_CANDIDATE",
        "BULL",
        "NORMAL",
        candidate,
        (candidate.intent_id,) if candidate else (),
        (),
        HASH_A,
        HASH_B,
    )


def _scenario_fixture(monkeypatch: pytest.MonkeyPatch, lifetime_ms: int) -> list[SleeveIntent]:
    parent_holder: list[SleeveIntent] = []

    def fake_technical(
        prefix, *, prefix_start_ms, cut_ms, source_set_sha256, context_sha256, sources, required_sources
    ):
        symbol = prefix[-1].symbol
        if symbol != UNIVERSE[0]:
            return _decision(symbol, cut_ms), ScenarioPreparation(
                "TECHNICAL", "QUIET", "NO_TECHNICAL_CANDIDATE", None, HASH_A
            )
        parent = SleeveIntent(
            "adaptive_pullback_range_v1",
            symbol,
            Side.LONG,
            cut_ms - 1,
            cut_ms,
            cut_ms + lifetime_ms,
            100.0,
            1.0,
            500.0,
            ExitPlan(98.0, 105.0, 3_600_000),
        )
        parent_holder.append(parent)
        plan = ScenarioPlan(
            parent,
            "TECHNICAL",
            "BULL",
            cut_ms,
            source_set_sha256,
            context_sha256,
            sources,
            prefix[-1],
            required_sources,
        )
        prep = ScenarioPreparation(
            "TECHNICAL", "WAITING_TRIGGER", "NATIVE_CANDIDATE_NOT_ENTRY_PERMISSION", plan, HASH_A
        )
        return _decision(symbol, cut_ms, parent), prep

    monkeypatch.setattr(compare, "technical_scenario", fake_technical)
    return parent_holder


def test_fixed_protocol_is_a_frozen_six_hour_market_only_comparison():
    source = compare.load_plan(Path(__file__).parents[1] / "plan.json")
    protocol = compare.fixed_protocol(source)
    assert protocol["start_ms"] == START
    assert protocol["end_exclusive_ms"] - protocol["start_ms"] == 6 * 60 * MINUTE
    assert protocol["scheduled_5m_slots"] == 360
    assert protocol["full_1m_cells"] == 1_800
    assert protocol["universe"] == list(UNIVERSE)
    assert protocol["required_sources"] == [["MARKET", compare.MARKET_SOURCE]]
    assert protocol["model_and_feed_costs"] is None
    assert protocol["complete_system_economics"] is None
    assert all(value is False for key, value in protocol["readiness"].items() if key.endswith("READY"))
    assert protocol["readiness"]["STRATEGY_POLICY"] == "REJECT_ALL"


def test_quiet_slots_are_preserved_and_minute_denominator_is_complete(tmp_path: Path, monkeypatch):
    def quiet(prefix, *, cut_ms, **kwargs):
        return _decision(prefix[-1].symbol, cut_ms), ScenarioPreparation(
            "TECHNICAL", "QUIET", "NO_TECHNICAL_CANDIDATE", None, HASH_A
        )

    monkeypatch.setattr(compare, "technical_scenario", quiet)
    _, completions, rows, counts = compare.build_pairs(_inputs(), tmp_path, HASH_A, float("inf"))
    assert len(rows) == 5
    assert counts["scheduled_slots"] == 5
    assert counts["full_minute_cells"] == 25
    assert counts["original_candidates"] == counts["supported_scenarios"] == 0
    assert completions == {"immediate": {}, "scenario": {}}
    with (tmp_path / "denominator.jsonl").open(encoding="utf-8") as stream:
        assert sum(1 for _ in stream) == 25
    with (tmp_path / "pairs.jsonl").open(encoding="utf-8") as stream:
        assert sum(1 for _ in stream) == 5


def test_unavailable_native_decision_is_ledgered_and_counted(tmp_path: Path, monkeypatch):
    def unavailable(prefix, *, cut_ms, **kwargs):
        decision = _decision(prefix[-1].symbol, cut_ms)
        decision = ComplexDecision(
            decision.symbol,
            decision.cut_ms,
            "UNAVAILABLE",
            "NATIVE_INPUT_UNAVAILABLE",
            decision.regime,
            "SOURCE_UNAVAILABLE",
            None,
            (),
            (),
            HASH_A,
            HASH_B,
        )
        prep = ScenarioPreparation("TECHNICAL", "UNAVAILABLE", "NATIVE_INPUT_UNAVAILABLE", None, HASH_A)
        return decision, prep

    monkeypatch.setattr(compare, "technical_scenario", unavailable)
    _, _, rows, counts = compare.build_pairs(_inputs(), tmp_path, HASH_A, float("inf"))
    assert counts["unavailable_slots"] == len(UNIVERSE)
    assert all(row["decision"]["state"] == "UNAVAILABLE" for row in rows)
    with (tmp_path / "pairs.jsonl").open(encoding="utf-8") as stream:
        assert sum(1 for _ in stream) == len(UNIVERSE)


@pytest.mark.parametrize(("lifetime", "expected_b"), [(59_999, False), (299_999, True)])
def test_observation_clock_respects_original_expiry_and_records_only_confirmed_b(
    tmp_path: Path, monkeypatch, lifetime: int, expected_b: bool
):
    parents = _scenario_fixture(monkeypatch, lifetime)
    tapes, completions, rows, counts = compare.build_pairs(_inputs(), tmp_path, HASH_A, float("inf"))
    btc = next(row for row in rows if row["symbol"] == UNIVERSE[0])
    assert btc["scenario_supported"] is True
    assert len(parents) == 1
    assert tapes["immediate"][START] == [parents[0]]
    assert completions["immediate"][parents[0].intent_id] == START + compare.LATENCY_MS
    if expected_b:
        assert btc["scenario_outcome"]["state"] == "CONSUMED"
        assert btc["scenario_candidate_id"] == btc["scenario_emitted_candidate_id"]
        candidate_id = btc["scenario_candidate_id"]
        assert candidate_id in completions["scenario"]
        assert completions["scenario"][candidate_id] == START + MINUTE + 2 * compare.LATENCY_MS
        assert tapes["scenario"][START + MINUTE + compare.LATENCY_MS]
        journal = (tmp_path / "scenarios.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(json.loads(journal[0])["observations"]) == 1  # first terminal outcome; no resurrection
    else:
        assert btc["scenario_outcome"]["reason"] == "ORIGINAL_ENTRY_LIFETIME_ELAPSED"
        assert btc["scenario_candidate_id"] is None
        assert not tapes["scenario"] and not completions["scenario"]
    assert counts["scheduled_slots"] == 5
    with (tmp_path / "scenarios.jsonl").open(encoding="utf-8") as stream:
        assert sum(1 for _ in stream) == 1


def _audit_row(candidate: SleeveIntent, *, supported: bool = True) -> dict:
    return {
        "slot_id": "slot",
        "decision": {"candidate": asdict(candidate), "state": "CANDIDATE"},
        "scenario_supported": supported,
        "scenario_candidate_id": None,
        "scenario_outcome": None,
        "preparation": {"reason": "UNSUPPORTED" if not supported else "NO_CONFIRMATION"},
        "outside_entry_window": False,
    }


def _audit_arms(candidate_id: str, *, net: float, economics: bool = True) -> dict:
    return {
        "immediate": {
            "economic_results": {"final_equity_usd": 10_100.0} if economics else None,
            "events": [{"kind": "ENTRY", "intent_id": candidate_id}],
            "trades": [{"intent_id": candidate_id, "net_pnl_usd": net}],
        },
        "scenario": {
            "economic_results": {"final_equity_usd": 10_050.0} if economics else None,
            "events": [],
            "trades": [],
        },
    }


def test_matching_audit_null_economics_stays_unknown_without_invented_delta():
    candidate = SleeveIntent(
        "adaptive_pullback_range_v1",
        "BTCUSDT",
        Side.LONG,
        START - 1,
        START,
        START + 60_000,
        100.0,
        1.0,
        500.0,
        ExitPlan(98.0, 105.0, 60_000),
    )
    audit = compare.matching_audit(
        [_audit_row(candidate)], _audit_arms(candidate.intent_id, net=20.0, economics=False)
    )
    assert audit["rows"][0]["classification"] == "UNKNOWN"
    assert audit["primary_account_delta_usd"] is None
    assert audit["complete_system_net_delta_usd"] is None


@pytest.mark.parametrize(
    ("net", "classification"), [(20.0, "MISSED_BASELINE_WINNER"), (-20.0, "AVOIDED_BASELINE_LOSS")]
)
def test_matching_audit_labels_excluded_closed_baseline_result_and_policy_subgroup(net, classification):
    candidate = SleeveIntent(
        "adaptive_pullback_range_v1",
        "BTCUSDT",
        Side.LONG,
        START - 1,
        START,
        START + 60_000,
        100.0,
        1.0,
        500.0,
        ExitPlan(98.0, 105.0, 60_000),
    )
    row = _audit_row(candidate, supported=False)
    audit = compare.matching_audit([row], _audit_arms(candidate.intent_id, net=net))
    assert audit["rows"][0]["classification"] == classification
    assert audit["rows"][0]["subgroup"] == "UNSUPPORTED_POLICY"
    assert audit["primary_account_delta_usd"] == -50.0


def test_matching_audit_rejects_duplicate_economic_ids():
    candidate = SleeveIntent(
        "adaptive_pullback_range_v1",
        "BTCUSDT",
        Side.LONG,
        START - 1,
        START,
        START + 60_000,
        100.0,
        1.0,
        500.0,
        ExitPlan(98.0, 105.0, 60_000),
    )
    arms = _audit_arms(candidate.intent_id, net=1.0)
    arms["immediate"]["events"].append({"kind": "ENTRY", "intent_id": candidate.intent_id})
    with pytest.raises(ValueError, match="duplicate economic identity"):
        compare.matching_audit([_audit_row(candidate)], arms)
