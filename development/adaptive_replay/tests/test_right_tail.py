from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.sleeves.right_tail_trend import RightTailTrendConfig

from adaptive_replay import right_tail as pair
from adaptive_replay.engine import entry_time
from adaptive_replay.inputs import WindowInputs

PROJECT = Path(__file__).resolve().parents[1]


def _base(eligible: int = 40 * pair.DAY + pair.HOUR) -> SleeveIntent:
    return SleeveIntent(
        sleeve_id=pair.ARMS[0],
        symbol="BTCUSDT",
        side=Side.LONG,
        decision_ts_ms=eligible - 1,
        entry_eligible_ts_ms=eligible,
        entry_expires_ts_ms=eligible + pair.HOUR - 1,
        reference_price=100,
        signal_strength=0.5,
        gross_reward_bps=800,
        exit_plan=ExitPlan(stop_price=98, target_price=108, max_holding_ms=72 * pair.HOUR),
        metadata=(("feature_hash", "original"),),
    )


def _aligned(base: SleeveIntent, **changes: object) -> SleeveIntent:
    regime_ts = (base.entry_eligible_ts_ms // (4 * pair.HOUR)) * (4 * pair.HOUR) - 1
    reference = changes.get("reference_price", base.reference_price)
    exits = changes.get("exit_plan", base.exit_plan)
    changes["gross_reward_bps"] = abs(exits.target_price - reference) / reference * 10_000
    return replace(
        base,
        sleeve_id=pair.ARMS[1],
        metadata=(
            ("base_intent_id", base.intent_id),
            ("base_feature_hash", "original"),
            ("base_config_sha256", RightTailTrendConfig().fingerprint),
            ("regime_close_ts_ms", str(regime_ts)),
        ),
        **changes,
    )


def _flat_window() -> WindowInputs:
    start = 40 * pair.DAY
    end = start + 3 * pair.DAY
    bars = tuple(
        Candle(
            symbol="BTCUSDT",
            timeframe="1m",
            open_time_ms=ts,
            close_time_ms=ts + pair.MINUTE - 1,
            open=100,
            high=101,
            low=99,
            close=100,
            volume=10,
        )
        for ts in range(start - pair.WARMUP, end + 72 * pair.HOUR, pair.MINUTE)
    )
    return WindowInputs(
        bars={"BTCUSDT": bars},
        funding={},
        evidence={},
        start_ms=start,
        end_ms=end,
        data_start_ms=start - pair.WARMUP,
        data_end_ms=end + 72 * pair.HOUR,
    )


def test_protocol_is_fixed_separate_and_installed_pair_identity_is_bound() -> None:
    plan, base = pair.load_protocol(PROJECT / "right-tail-plan.json")
    assert plan["warmup_hours"] == 840 and plan["exit_tail_hours"] == 72
    assert base["warmup_hours"] == 54 and base["exit_tail_hours"] == 3
    receipt = pair.sources(plan, base, PROJECT / "right-tail-plan.json")
    assert (
        receipt["aligned_transitive_base_source_sha256"]
        == receipt["native_pair"][pair.ARMS[0]]["registry_source_sha256"]
    )
    assert receipt["native_pair"][pair.ARMS[1]]["config"]["regime_sma_bars"] == 200


@pytest.mark.parametrize(
    "field,value",
    [
        ("warmup_hours", 54),
        ("exit_tail_hours", 3),
        ("workers", 2),
        ("max_wall_seconds", 9999),
        ("entry_modes", ["INTRABAR_OPEN_PROXY"]),
        ("no_downloads", False),
        ("extra_windows", []),
        ("no_parameter_search", False),
        ("no_paid_calls", False),
        ("workers", True),
    ],
)
def test_protocol_rejects_mutation(tmp_path: Path, field: str, value: object) -> None:
    plan = json.loads((PROJECT / "right-tail-plan.json").read_text())
    plan[field] = value
    (tmp_path / "right-tail-plan.json").write_text(json.dumps(plan))
    (tmp_path / "plan.json").write_bytes((PROJECT / "plan.json").read_bytes())
    with pytest.raises(ValueError, match="fixed right-tail"):
        pair.load_protocol(tmp_path / "right-tail-plan.json")


def test_pair_ids_differ_but_geometry_and_feature_lineage_match() -> None:
    base = _base()
    aligned = _aligned(base)
    assert aligned.intent_id != base.intent_id
    pair.check_pair([base], [aligned])
    assert (
        entry_time(base, base.decision_ts_ms + 100, "STRICT_MINUTE_OPEN")
        == base.entry_eligible_ts_ms + pair.MINUTE
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("reference_price", 100.1),
        ("signal_strength", 0.6),
        ("entry_expires_ts_ms", 40 * pair.DAY + 3 * pair.HOUR),
        ("exit_plan", ExitPlan(stop_price=98, target_price=110, max_holding_ms=72 * pair.HOUR)),
    ],
)
def test_aligned_geometry_cannot_change(field: str, value: object) -> None:
    base = _base()
    with pytest.raises(ValueError, match="changed base economics"):
        pair.check_pair([base], [_aligned(base, **{field: value})])


def test_pair_rejects_orphan_duplicate_and_future_regime() -> None:
    base = _base()
    aligned = _aligned(base)
    with pytest.raises(ValueError, match="exact native base"):
        pair.check_pair([], [aligned])
    with pytest.raises(ValueError, match="duplicate"):
        pair.check_pair([base, base], [aligned])
    metadata = dict(aligned.metadata)
    metadata["regime_close_ts_ms"] = str(40 * pair.DAY + 4 * pair.HOUR - 1)
    with pytest.raises(ValueError, match="causal 4h"):
        pair.check_pair([base], [replace(aligned, metadata=tuple(metadata.items()))])


def test_native_generation_on_flat_full_prefix_is_quiet_and_tail_is_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _flat_window()
    monkeypatch.setattr(pair, "UNIVERSE", ("BTCUSDT",))
    tapes, evidence = pair.generate_pair(inputs, time.monotonic() + 60)
    assert tapes == {arm: {} for arm in pair.ARMS}
    assert evidence["exit_tail_used"] is False
    assert evidence["symbols"]["BTCUSDT"]["prefix_bars"] == 38 * 1440
    assert len(evidence["symbols"]["BTCUSDT"]["prefix_checks_ms"]) == 6


def test_missing_warmup_and_deadline_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = _flat_window()
    monkeypatch.setattr(pair, "UNIVERSE", ("BTCUSDT",))
    with pytest.raises(TimeoutError):
        pair.generate_pair(inputs, 0)
    short = replace(inputs, bars={"BTCUSDT": inputs.bars["BTCUSDT"][1:]})
    with pytest.raises(ValueError, match="complete exact"):
        pair.generate_pair(short, time.monotonic() + 60)


def test_generator_future_dependency_cannot_pass_prefix_check(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = _flat_window()
    monkeypatch.setattr(pair, "UNIVERSE", ("BTCUSDT",))

    def future_sensitive(arm: str, rows: list[Candle], config: object) -> list[SleeveIntent]:
        marker = str(rows[-1].open_time_ms)
        return [replace(_base(inputs.start_ms + pair.HOUR), metadata=(("feature_hash", marker),))]

    monkeypatch.setattr(pair, "generate_sleeve_intents", future_sensitive)
    with pytest.raises(ValueError, match="prefix mutation"):
        pair.generate_pair(inputs, time.monotonic() + 60)


def test_within_day_lookahead_is_checked_at_the_actual_daily_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _flat_window()
    monkeypatch.setattr(pair, "UNIVERSE", ("BTCUSDT",))

    def midday_leak(arm: str, rows: list[Candle], config: object) -> list[SleeveIntent]:
        marker = "future" if rows[-1].close_time_ms >= inputs.start_ms + 12 * pair.HOUR else "causal"
        return [replace(_base(inputs.start_ms + pair.HOUR), metadata=(("feature_hash", marker),))]

    monkeypatch.setattr(pair, "generate_sleeve_intents", midday_leak)
    with pytest.raises(ValueError, match="prefix mutation"):
        pair.generate_pair(inputs, time.monotonic() + 60)


def test_independent_regime_check_rejects_arbitrary_subset(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = _flat_window()
    base = _base(inputs.start_ms + pair.HOUR)
    last = inputs.start_ms - 1
    prefix = [row for row in inputs.bars["BTCUSDT"] if row.open_time_ms < inputs.end_ms]
    prefix = [replace(row, close=100.5) if row.close_time_ms == last else row for row in prefix]
    with pytest.raises(ValueError, match="exact causal SMA predicate"):
        pair.check_regime_selection([base], [], prefix)
    average = (199 * 100 + 100.5) / 200
    aligned = _aligned(base)
    metadata = dict(aligned.metadata)
    metadata.update({"regime_close": "100.5", "regime_sma": format(average, ".17g")})
    pair.check_regime_selection([base], [replace(aligned, metadata=tuple(metadata.items()))], prefix)


def test_tape_keeps_native_daily_roster_unknown_reasons_and_original_intent(tmp_path: Path) -> None:
    inputs = _flat_window()
    base = _base(inputs.start_ms + pair.HOUR)
    path = tmp_path / "daily.jsonl"
    receipt = pair.write_daily_tape(path, {base.entry_eligible_ts_ms: [base]}, inputs)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert receipt["native_daily_slots"] == 15 and receipt["candidates"] == 1
    assert rows[0]["intent"] == json.loads(pair.canonical(asdict(base)))
    assert all(row["source_outcome_reason"] is None for row in rows)
    assert rows[1]["status"] == "NO_NATIVE_CANDIDATE_REASON_UNAVAILABLE"
    with pytest.raises(FileExistsError):
        pair.write_daily_tape(path, {}, inputs)


def test_run_rejects_overlapping_cache_before_any_output(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="overlap"):
        pair.run(PROJECT / "right-tail-plan.json", tmp_path, tmp_path / "factors", tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_published_result_and_independent_calculator_preserve_exact_bytes() -> None:
    root = PROJECT / "evidence" / "right-tail-2026-10-07"
    result_bytes = (root / "result.json").read_bytes()
    audit_bytes = (root / "independent-ledger-audit.json").read_bytes()
    result_sha = hashlib.sha256(result_bytes).hexdigest()
    audit = json.loads(audit_bytes)
    assert result_sha == "0caaec779e2e4172484ebb9ab9c4830b946da29d62f31358291185f2113eb1d3"
    assert (
        hashlib.sha256(audit_bytes).hexdigest()
        == "8ef189863b30b305954cae7f87f363b4b32fd249005bdc272aa03d6320b04e08"
    )
    assert audit["result_sha256"] == result_sha
    assert (
        audit["calculator_sha256"] == hashlib.sha256((root / "Test-PairLedgers.ps1").read_bytes()).hexdigest()
    )
    assert audit["state"] == "PASSED_SCOPED_ARITHMETIC"
    assert audit["complete_venue_or_alpha_validation"] is False


def test_published_cells_tapes_ledgers_and_finite_selection_boundary_are_bound() -> None:
    root = PROJECT / "evidence" / "right-tail-2026-10-07"
    result = json.loads((root / "result.json").read_bytes())
    audit = json.loads((root / "independent-ledger-audit.json").read_bytes())
    assert result["qualified_winner"] is None and result["strategy_selected_for_live"] is None
    assert result["compound_return_across_windows"] is None
    assert result["blind_results_read"] is False and result["blind_campaign_days_added"] == 0
    assert result["paid_calls"] == 0
    assert result["readiness"]["STRATEGY_POLICY"] == "REJECT_ALL"
    assert all(value is False for key, value in result["readiness"].items() if key != "STRATEGY_POLICY")
    assert len(audit["cells"]) == 16
    counts = {arm: {"candidates": 0, "closes_per_cost": {"base": 0, "stress": 0}} for arm in pair.ARMS}
    for window in result["windows"]:
        for arm in window["arms"]:
            arm_root = root / window["window"]["id"] / arm["arm_id"]
            assert (
                hashlib.sha256((arm_root / "decisions.jsonl").read_bytes()).hexdigest()
                == arm["counts"]["tape_sha256"]
            )
            assert arm["counts"]["native_daily_slots"] == 15
            counts[arm["arm_id"]]["candidates"] += arm["counts"]["candidates"]
            for report in arm["economic_results"]:
                cost = report["cost_scenario"]["id"]
                recorded = next(
                    cell
                    for cell in audit["cells"]
                    if (
                        cell["window"] == window["window"]["id"]
                        and cell["arm"] == arm["arm_id"]
                        and cell["cost"] == cost
                    )
                )
                ledger_bytes = (arm_root / f"{cost}-ledger.json").read_bytes()
                assert hashlib.sha256(ledger_bytes).hexdigest() == recorded["ledger_sha256"]
                assert (
                    len(json.loads(ledger_bytes)["trades"]) == report["closed_trades"] == recorded["closed"]
                )
                assert recorded["return_pct"] == report["net_return_pct"]
                assert report["terminal_unresolved_positions"] == []
                assert report["complete_all_in_net_economics"] is False
                assert report["execution_qualification"] is False
                counts[arm["arm_id"]]["closes_per_cost"][cost] += report["closed_trades"]
    assert counts == {
        pair.ARMS[0]: {"candidates": 25, "closes_per_cost": {"base": 9, "stress": 9}},
        pair.ARMS[1]: {"candidates": 22, "closes_per_cost": {"base": 8, "stress": 8}},
    }
