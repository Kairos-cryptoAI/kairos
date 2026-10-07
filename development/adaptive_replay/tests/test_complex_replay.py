import hashlib
import time
from dataclasses import replace
from functools import lru_cache

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent

from adaptive_replay import complex_replay as cr
from adaptive_replay.complex_assessment import RetrospectiveAssessment
from adaptive_replay.complex_frame import ContextAssessmentFrame
from adaptive_replay.complex_protocol import model_config_sha256, protocol_sha256, requirements
from adaptive_replay.complex_strategy import ComplexDecision
from adaptive_replay.engine import CostScenario
from adaptive_replay.historical_bars import _payload_bytes, resolve_closed_history
from adaptive_replay.historical_context import HistoricalArchive, HistoricalCoverage, canonical
from adaptive_replay.inputs import UNIVERSE, WindowInputs

CUT = 5 * 86_400_000
END = CUT + 300_000
TODAY = 1_600_000_000_000
SCENARIO = CostScenario("fixture", 0, 0, 0, 0, 0, 0)


@lru_cache
def fixture():
    start = CUT - 3_240 * 60_000
    bars = {
        symbol: tuple(
            Candle(symbol, "1m", t, t + 59_999, 100, 100.7, 99.3, 100, 10)
            for t in range(start, END + 3 * 3_600_000, 60_000)
        )
        for symbol in UNIVERSE
    }
    inputs = WindowInputs(bars, {s: () for s in UNIVERSE}, {}, CUT, END, start, END + 3 * 3_600_000)
    archive = HistoricalArchive(
        (),
        tuple(
            HistoricalCoverage(
                r.source_name, r.kind, s, 0, CUT + 86_400_000, (), "COMPLETE", "TEST_FIXTURE", "a" * 64, TODAY
            )
            for r in requirements()
            for s in UNIVERSE
        ),
    )
    frames = []
    for symbol in UNIVERSE:
        history_bars = tuple(c for c in bars[symbol] if c.open_time_ms < CUT)
        history = resolve_closed_history(
            candles=history_bars,
            expected_payload_sha256=hashlib.sha256(_payload_bytes(history_bars)).hexdigest(),
            expected_symbol=symbol,
            expected_timeframe="1m",
            expected_count=3_240,
            expected_first_open_ms=start,
            expected_last_closed_ms=CUT - 1,
            cutoff_ms=CUT,
            provenance="TEST_FIXTURE",
            captured_at_ms=TODAY,
        )
        frames.append(ContextAssessmentFrame(history, archive, requirements(), CUT, protocol_sha256()))
    return inputs, tuple(frames)


def observations(frames, *, proposal="LONG", long_review="ALLOW", short_review="ALLOW"):
    return tuple(
        RetrospectiveAssessment(
            frame_id=f.frame_id,
            prompt_sha256=f.prompt_sha256,
            attempt_id="fixture-" + f.history.symbol,
            model="gpt-6-luna",
            model_config_sha256=model_config_sha256(),
            actual_requested_ms=TODAY,
            actual_observed_ms=TODAY + 250,
            actual_cost_observed_ms=TODAY + 300,
            recorded_cost_usd=0.1,
            status="COMPLETE",
            response_json=canonical(
                {
                    "long_review": long_review,
                    "short_review": short_review,
                    "proposal": proposal,
                    "evidence_ids": [],
                }
            ),
            raw_response_sha256="f" * 64,
            evidence_kind="TEST_FIXTURE",
        )
        for f in frames
    )


def run(*, data=None, obs=None, mappings=None, mode="INTRABAR_OPEN_PROXY", **kwargs):
    inputs, frames = fixture() if data is None else data
    obs = observations(frames) if obs is None else obs
    mappings = (
        cr.prepare_assessment_mappings(frames, obs, fixture_only=True) if mappings is None else mappings
    )
    return cr.evaluate_complex_historical(
        inputs,
        frames,
        obs,
        SCENARIO,
        mode,
        expected_cuts_ms=(CUT,),
        fixture_only=True,
        mappings=mappings,
        **kwargs,
    )


def baseline(symbol, side=Side.LONG):
    return SleeveIntent(
        "adaptive_pullback_range_v1",
        symbol,
        side,
        CUT - 1,
        CUT,
        CUT + 59_999,
        100,
        1,
        200,
        ExitPlan(99 if side is Side.LONG else 101, 102 if side is Side.LONG else 98, 120_000),
    )


def fake_technical(monkeypatch, *, state="CANDIDATE", reason="TECHNICAL_SELECTED"):
    def evaluate(prefix, **kwargs):
        s = prefix[-1].symbol
        c = baseline(s) if state == "CANDIDATE" else None
        return ComplexDecision(
            s,
            CUT,
            state,
            reason,
            "RANGE",
            "NORMAL",
            c,
            () if c is None else (c.intent_id,),
            (),
            "a" * 64,
            "b" * 64,
        )

    monkeypatch.setattr(cr, "evaluate_complex", evaluate)


def test_real_quiet_full_path_proposal_to_common_risk_account_and_cost_not_double_charged():
    result = run(feed_costs=())
    assert result["scheduled_cells"] == 5 and result["physical_attempt_count"] == 5
    assert result["physical_known_model_spend_usd"] == pytest.approx(0.5)
    assert result["arms"]["strategy_only"]["account_model_cost_usd"] == 0
    for arm in ("context_review", "independent_proposals", "combined", "review_timing_control"):
        assert result["arms"][arm]["account_model_cost_usd"] == pytest.approx(0.5)
        assert result["arms"][arm]["projected_model_charge_count"] == 5
        assert result["arms"][arm]["economic_results"]["model_cost_usd"] == pytest.approx(0.5)
    assert not result["arms"]["strategy_only"]["candidate_ids"]
    assert any(e["kind"] == "ENTRY" for e in result["arms"]["combined"]["events"])
    assert result["blind_campaign_credit_days"] == 0 and not result["LIVE_READY"]
    assert result["cells"][0]["actual_requested_ms"] == TODAY
    assert result["cells"][0]["projected_assessment_ready_ms"] == CUT + 350
    assert result["cells"][0]["projected_cost_ready_ms"] == CUT + 400


def test_missing_or_unknown_observation_cost_is_null_not_free():
    _, frames = fixture()
    obs = observations(frames)
    partial = run(obs=obs[:-1], feed_costs=())
    assert partial["arms"]["strategy_only"]["economic_results"] is not None
    assert partial["arms"]["combined"]["economic_results"] is None
    assert partial["arms"]["combined"]["account_model_cost_usd"] is None
    assert partial["physical_known_model_spend_is_lower_bound"]
    unknown = run(obs=tuple(replace(o, recorded_cost_usd=None) for o in obs), feed_costs=())
    assert unknown["unknown_cost_attempts"] == 5
    assert unknown["arms"]["context_review"]["economic_results"] is None


def test_feed_expense_not_supplied_never_means_zero():
    result = run()
    assert all(a["economic_results"] is None for a in result["arms"].values())


def test_review_veto_is_not_bypassed_by_allowed_opposite_proposal(monkeypatch):
    fake_technical(monkeypatch)
    _, frames = fixture()
    result = run(obs=observations(frames, proposal="SHORT", long_review="VETO"), feed_costs=())
    assert not result["arms"]["combined"]["candidate_ids"]
    assert result["arms"]["independent_proposals"]["candidate_ids"]
    assert result["arms"]["review_timing_control"]["candidate_ids"]
    assert all(c["combined_reason"] == "BASELINE_VETO" for c in result["cells"])


def test_technical_conflict_cannot_be_resurrected_as_quiet_proposal(monkeypatch):
    fake_technical(monkeypatch, state="CONFLICT", reason="OPPOSITE_TECHNICAL_ABSTAIN")
    result = run(feed_costs=())
    assert not result["arms"]["combined"]["candidate_ids"]
    assert result["arms"]["independent_proposals"]["candidate_ids"]
    assert all(c["combined_reason"] == "OPPOSITE_TECHNICAL_ABSTAIN_NO_RESURRECTION" for c in result["cells"])


def test_original_short_ttl_remains_unexecutable_at_delayed_minute_quote(monkeypatch):
    fake_technical(monkeypatch)
    _, frames = fixture()
    result = run(obs=observations(frames, proposal="NONE"), mode="STRICT_MINUTE_OPEN", feed_costs=())
    arm = result["arms"]["context_review"]
    assert arm["quote_unavailable_candidates"] == 5
    assert not any(e["kind"] == "ENTRY" for e in arm["events"])
    assert arm["economic_results"]["model_cost_usd"] == pytest.approx(0.5)


def test_once_measured_mapping_clock_is_shared_across_modes_and_review_control(monkeypatch):
    fake_technical(monkeypatch)
    _, frames = fixture()
    obs = observations(frames, proposal="NONE")
    mappings = tuple(
        replace(m, monotonic_elapsed_ns=90_000_000)
        for m in cr.prepare_assessment_mappings(frames, obs, fixture_only=True)
    )
    one = run(obs=obs, mappings=mappings, feed_costs=())
    two = run(obs=obs, mappings=mappings, mode="STRICT_MINUTE_OPEN", feed_costs=())
    assert [c["mapping_elapsed_ms"] for c in one["cells"]] == [90] * 5
    assert [c["timed_mapping"] for c in one["cells"]] == [c["timed_mapping"] for c in two["cells"]]
    review_entries = [e for e in one["arms"]["context_review"]["events"] if e["kind"] == "ENTRY"]
    control_entries = [e for e in one["arms"]["review_timing_control"]["events"] if e["kind"] == "ENTRY"]
    assert review_entries == control_entries


def test_error_retains_cost_and_missing_mapping_cannot_be_salvaged(monkeypatch):
    fake_technical(monkeypatch)
    _, frames = fixture()
    obs = tuple(replace(o, status="ERROR", response_json=None) for o in observations(frames))
    result = run(obs=obs, feed_costs=())
    assert not result["arms"]["combined"]["candidate_ids"]
    assert result["arms"]["combined"]["economic_results"]["model_cost_usd"] == pytest.approx(0.5)
    with pytest.raises(ValueError, match="once-measured"):
        run(mappings=(), feed_costs=())


def test_bad_denominator_protocol_observation_and_geometry_rejected():
    inputs, frames = fixture()
    with pytest.raises(ValueError, match="denominator"):
        run(data=(inputs, frames[:-1]), obs=(), mappings=())
    obs = observations(frames)
    with pytest.raises(ValueError, match="underlying attempt"):
        run(obs=(obs[0], replace(obs[1], attempt_id=obs[0].attempt_id), *obs[2:]), mappings=())
    mapping = cr.prepare_assessment_mappings(frames, obs, fixture_only=True)
    with pytest.raises(ValueError, match="geometry"):
        wrong = replace(mapping[0], mapping=replace(mapping[0].mapping, reason="ALTERED"))
        run(obs=obs, mappings=(wrong, *mapping[1:]), feed_costs=())
    with pytest.raises(ValueError, match="protocol"):
        run(data=(inputs, (replace(frames[0], protocol_sha256="f" * 64), *frames[1:])), obs=(), mappings=())
    with pytest.raises(TimeoutError):
        run(obs=(), mappings=(), deadline=time.monotonic() - 1)


def test_held_context_coverage_gap_at_quote_defers_without_changing_prompt(monkeypatch):
    inputs, frames = fixture()
    restricted = []
    for f in frames:
        archive = replace(f.archive, coverage=tuple(replace(c, end_ms=CUT + 200) for c in f.archive.coverage))
        restricted.append(replace(f, archive=archive))
    restricted = tuple(restricted)
    assert [f.prompt_sha256 for f in restricted] == [f.prompt_sha256 for f in frames]
    assert all(f.sources_ready for f in restricted)
    assert all(not cr.held_context_fresh(f, CUT + 400) for f in restricted)
    result = run(data=(inputs, restricted), obs=observations(restricted), feed_costs=())
    assert not result["arms"]["combined"]["candidate_ids"]
    assert result["arms"]["combined"]["economic_results"]["model_cost_usd"] == pytest.approx(0.5)
