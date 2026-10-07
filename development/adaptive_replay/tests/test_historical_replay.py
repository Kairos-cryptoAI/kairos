import hashlib
from dataclasses import replace

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent

from adaptive_replay.engine import CostScenario
from adaptive_replay.historical_bars import _payload_bytes, resolve_closed_history
from adaptive_replay.historical_context import (
    HistoricalArchive,
    HistoricalCoverage,
    SourceRequirement,
    canonical,
)
from adaptive_replay.historical_replay import HistoricalFrame, RetrospectiveReview, evaluate_historical_review
from adaptive_replay.inputs import UNIVERSE, WindowInputs

START = 86_400_000
END = START + 60_000
TODAY = START + 365 * 86_400_000
SCENARIO = CostScenario("fixture", 0, 0, 0, 0, 0, 0)


def fixture():
    bars = {
        s: tuple(
            Candle(s, "1m", t, t + 59_999, 100, 100.1, 99.9, 100, 10)
            for t in range(START - 60_000, END + 3 * 3_600_000, 60_000)
        )
        for s in UNIVERSE
    }
    inputs = WindowInputs(
        bars, {s: () for s in UNIVERSE}, {}, START, END, START - 60_000, END + 3 * 3_600_000
    )
    archive = HistoricalArchive(
        (),
        tuple(
            HistoricalCoverage(
                "official", "NEWS", s, 0, TODAY, (), "COMPLETE", "TEST_FIXTURE", "a" * 64, TODAY
            )
            for s in UNIVERSE
        ),
    )
    req = (SourceRequirement("official", "NEWS", True, 60_000, 30_000),)
    frames = []
    for index, symbol in enumerate(UNIVERSE):
        history = resolve_closed_history(
            candles=bars[symbol],
            expected_payload_sha256=hashlib.sha256(_payload_bytes(bars[symbol])).hexdigest(),
            expected_symbol=symbol,
            expected_timeframe="1m",
            expected_count=len(bars[symbol]),
            expected_first_open_ms=START - 60_000,
            expected_last_closed_ms=START - 1,
            cutoff_ms=START,
            provenance="TEST_FIXTURE",
            captured_at_ms=TODAY,
        )
        candidate = (
            None
            if index == 0
            else SleeveIntent(
                "adaptive_pullback_range_v1",
                symbol,
                Side.LONG,
                START - 1,
                START,
                START + 59_999,
                100,
                1,
                200,
                ExitPlan(99, 102, 120_000),
            )
        )
        frames.append(
            HistoricalFrame(
                history,
                archive,
                req,
                START,
                "QUIET" if candidate is None else "CANDIDATE",
                candidate,
                "b" * 64,
                "c" * 64,
            )
        )
    return inputs, tuple(frames)


def reviews(frames, disposition="ALLOW"):
    return tuple(
        RetrospectiveReview(
            f.frame_id,
            f.prompt_sha256,
            "attempt-" + f.history.symbol,
            "fixture-model",
            "e" * 64,
            TODAY,
            TODAY + 500,
            TODAY + 600,
            0.01,
            "COMPLETE",
            canonical({"decision": disposition}),
            "f" * 64,
            evidence_kind="TEST_FIXTURE",
        )
        for f in frames
        if f.candidate is not None
    )


def run(data=None, observations=None, **kwargs):
    inputs, frames = fixture() if data is None else data
    return evaluate_historical_review(
        inputs,
        frames,
        reviews(frames) if observations is None else observations,
        SCENARIO,
        "INTRABAR_OPEN_PROXY",
        simulated_delay_ms=100,
        fixture_only=True,
        **kwargs,
    )


def test_native_minute_and_context_clock_preserved_without_observed_relabelling():
    result = run(feed_costs=())
    assert result["scheduled_slots"] == 5
    assert result["slot_states"] == {"QUIET": 1, "CANDIDATE": 4}
    assert all(a["status"] == "FIXTURE_ONLY" for a in result["arms"].values())
    assert result["known_modern_model_cost_usd"] == pytest.approx(0.04)
    assert not result["historical_model_observation"]
    assert not result["training_contamination_excluded"]
    assert result["LIVE_READY"] is False
    assert result["STRATEGY_POLICY"] == "REJECT_ALL"
    for projection in result["projections"]:
        assert projection["actual_requested_ms"] == TODAY
        assert projection["actual_observed_ms"] == TODAY + 500
        assert projection["simulated_ready_ms"] == START + 100
    original = {f.candidate.intent_id for f in fixture()[1] if f.candidate}
    for path in result["arms"].values():
        assert all(e["intent_id"] in original for e in path["events"] if e["kind"] == "ENTRY")


@pytest.mark.parametrize("disposition", ["VETO", "DEFER"])
def test_review_abstention_retains_modern_and_projected_cost(disposition):
    inputs, frames = fixture()
    result = run((inputs, frames), reviews(frames, disposition), feed_costs=())
    arm = result["arms"]["context_review"]
    assert not any(e["kind"] == "ENTRY" for e in arm["events"])
    assert arm["economic_results"]["model_cost_usd"] == pytest.approx(0.04)
    assert any(e["kind"] == "ENTRY" for e in result["arms"]["review_timing_control"]["events"])


def test_missing_observations_or_unknown_expense_null_whole_review_not_selected_subset():
    inputs, frames = fixture()
    result = run((inputs, frames), reviews(frames)[:-1])
    assert result["arms"]["strategy_only"]["economic_results"] is not None
    assert result["arms"]["context_review"]["economic_results"] is None
    obs = tuple(replace(r, recorded_cost_usd=None) for r in reviews(frames))
    result = run((inputs, frames), obs)
    assert result["arms"]["context_review"]["economic_results"] is None
    assert result["unknown_modern_model_cost_attempts"] == 4


def test_expired_original_candidate_never_gets_backdated_fill_but_cost_is_retained():
    inputs, frames = fixture()
    result = evaluate_historical_review(
        inputs,
        frames,
        reviews(frames),
        SCENARIO,
        "INTRABAR_OPEN_PROXY",
        simulated_delay_ms=60_000,
        fixture_only=True,
    )
    assert not any(e["kind"] == "ENTRY" for e in result["arms"]["context_review"]["events"])
    assert result["arms"]["context_review"]["economic_results"]["model_cost_usd"] == pytest.approx(0.04)


def test_future_execution_prices_do_not_change_earlier_prompt_or_frame_identity():
    inputs, frames = fixture()
    mutated = replace(
        inputs,
        bars={
            s: tuple(replace(c, high=110) if c.open_time_ms >= START else c for c in rows)
            for s, rows in inputs.bars.items()
        },
    )
    before = [f.prompt_sha256 for f in frames]
    run((mutated, frames))
    assert [f.prompt_sha256 for f in frames] == before
    assert all("archive_sha256" not in canonical(f.prompt_payload()) for f in frames)
    assert all("episode" not in canonical(f.prompt_payload()) for f in frames)


def test_changed_prompt_bars_or_candidate_identity_rejected():
    inputs, frames = fixture()
    symbol = frames[0].history.symbol
    bad = replace(
        inputs,
        bars={
            **inputs.bars,
            symbol: tuple(replace(c, high=105) if c.open_time_ms < START else c for c in inputs.bars[symbol]),
        },
    )
    with pytest.raises(ValueError, match="differs from replay"):
        run((bad, frames))
    f = frames[1]
    with pytest.raises(ValueError, match="closed-anchor"):
        replace(f, candidate=replace(f.candidate, decision_ts_ms=START)).validate()


def test_incomplete_roster_unavailable_strategy_duplicate_attempt_fail_closed():
    inputs, frames = fixture()
    with pytest.raises(ValueError, match="denominator"):
        run((inputs, frames[:-1]))
    missing = (replace(frames[0], state="UNAVAILABLE"), *frames[1:])
    result = run((inputs, missing), reviews(missing))
    assert all(a["economic_results"] is None for a in result["arms"].values())
    obs = reviews(frames)
    with pytest.raises(ValueError, match="binding"):
        run((inputs, frames), (*obs, obs[0]))


def test_reconstruction_cannot_be_relabelled_observed_or_forget_failure_cost():
    inputs, frames = fixture()
    obs = reviews(frames)
    with pytest.raises(ValueError, match="OBSERVED_POINT_IN_TIME"):
        replace(obs[0], evidence_kind="OBSERVED_POINT_IN_TIME").validate()
    failed = tuple(replace(o, status="ERROR", response_json=None) for o in obs)
    result = run((inputs, frames), failed)
    assert result["arms"]["context_review"]["economic_results"]["model_cost_usd"] == pytest.approx(0.04)
    assert not any(e["kind"] == "ENTRY" for e in result["arms"]["context_review"]["events"])


def test_source_ttl_empty_coverage_and_feed_unknown_remain_explicit():
    inputs, frames = fixture()
    result = run((inputs, frames))
    assert result["arms"]["context_review"]["recorded_all_in_net_result"] is None
    aged = tuple(
        replace(f, requirements=(SourceRequirement("official", "NEWS", True, 60_000, 50),)) for f in frames
    )
    result = run((inputs, aged), reviews(aged))
    assert not any(e["kind"] == "ENTRY" for e in result["arms"]["context_review"]["events"])


def test_forced_low_level_clock_mutation_and_backdated_actual_call_rejected():
    inputs, frames = fixture()
    obs = reviews(frames)
    object.__setattr__(obs[0], "actual_observed_ms", True)
    with pytest.raises(ValueError, match="integer"):
        run((inputs, frames), obs)
    obs = reviews(frames)
    with pytest.raises(ValueError, match="binding"):
        run((inputs, frames), (replace(obs[0], actual_requested_ms=START - 1), *obs[1:]))


def test_invocation_cannot_precede_materialized_prompt_bars_or_coverage():
    inputs, frames = fixture()
    obs = reviews(frames)
    too_early = replace(
        obs[0], actual_requested_ms=START, actual_observed_ms=START + 500, actual_cost_observed_ms=START + 600
    )
    with pytest.raises(ValueError, match="binding"):
        run((inputs, frames), (too_early, *obs[1:]))
    assert frames[1].materialized_ms == TODAY


@pytest.mark.parametrize(
    "changed",
    [
        {"strategy_code_sha256": "d" * 64},
        {"strategy_config_sha256": "e" * 64},
        {"requirements": (SourceRequirement("official", "NEWS", False, 60_000, 30_000),)},
        {"requirements": (SourceRequirement("official", "NEWS", True, 60_000, 20_000),)},
    ],
)
def test_slot_protocol_drift_requires_separate_account(changed):
    inputs, frames = fixture()
    drifted = (frames[0], replace(frames[1], **changed), *frames[2:])
    with pytest.raises(ValueError, match="one immutable|one fixed"):
        run((inputs, drifted), reviews(drifted))


def test_execution_duplicate_and_missing_tail_rejected_before_account_creation():
    inputs, frames = fixture()
    symbol = UNIVERSE[0]
    for rows in ((*inputs.bars[symbol], inputs.bars[symbol][-1]), inputs.bars[symbol][:-1]):
        with pytest.raises(ValueError):
            run((replace(inputs, bars={**inputs.bars, symbol: rows}), frames))


def test_explicit_no_call_has_no_model_debit_or_invented_inference_completion():
    inputs, frames = fixture()
    obs = tuple(
        replace(
            r,
            status="NOT_CALLED",
            response_json=None,
            raw_response_sha256=None,
            recorded_cost_usd=0,
            no_call_reason="BUDGET_DENIED",
        )
        for r in reviews(frames)
    )
    result = run((inputs, frames), obs)
    assert result["known_modern_model_cost_usd"] == 0
    assert all(p["simulated_ready_ms"] == START for p in result["projections"])
    assert not any(e["kind"] == "ENTRY" for e in result["arms"]["context_review"]["events"])


def test_no_call_cannot_fabricate_missing_required_source():
    inputs, frames = fixture()
    obs = tuple(
        replace(
            r,
            status="NOT_CALLED",
            response_json=None,
            raw_response_sha256=None,
            recorded_cost_usd=0,
            no_call_reason="REQUIRED_SOURCE_UNAVAILABLE",
        )
        for r in reviews(frames)
    )
    with pytest.raises(ValueError, match="contradicts"):
        run((inputs, frames), obs)
