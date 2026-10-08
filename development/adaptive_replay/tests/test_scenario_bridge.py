"""Actual causal mapper bridge plus narrowly isolated technical control fixtures."""

from dataclasses import replace

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay import scenario_bridge as bridge
from adaptive_replay.complex_strategy import ComplexDecision
from adaptive_replay.historical_context import digest
from adaptive_replay.scenarios import ScenarioEvidence, evaluate_scenario

CUT = 5 * 86_400_000
SOURCE_SET = "a" * 64
ASSESSMENT = "b" * 64


def history():
    return tuple(
        Candle("BTCUSDT", "1m", t, t + 59_999, 100, 100.7, 99.3, 100, 10)
        for t in range(CUT - 3_240 * 60_000, CUT, 60_000)
    )


def sources(anchor):
    return tuple(
        sorted(
            (
                ScenarioEvidence(
                    "bars", "MARKET", "BTCUSDT", digest(candle_payload(anchor)), CUT - 1, CUT, CUT, 900_000
                ),
                ScenarioEvidence("news", "NEWS", "BTCUSDT", "c" * 64, CUT - 1, CUT, CUT, 900_000),
                ScenarioEvidence("macro", "MACRO", "BTCUSDT", "d" * 64, CUT - 1, CUT, CUT, 900_000),
            ),
            key=lambda e: (e.kind, e.source_id),
        )
    )


def context(direction="LONG", **kwargs):
    bars = history()
    return bridge.context_scenario(
        direction,
        bars,
        cut_ms=CUT,
        assessment_sha256=ASSESSMENT,
        source_set_sha256=SOURCE_SET,
        sources=sources(bars[-1]),
        required_sources=(("MACRO", "macro"), ("MARKET", "bars"), ("NEWS", "news")),
        **kwargs,
    )


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
def test_actual_mapper_only_prepares_a_waiting_idea(direction):
    result = context(direction)
    assert result.state == "WAITING_TRIGGER"
    assert result.plan.origin == "CONTEXT_PROPOSAL" and result.plan.regime == "RANGE"
    assert result.plan.template.entry_expires_ts_ms == CUT + 299_999
    assert result.plan.template.signal_strength == 1
    initial = evaluate_scenario(result.plan, ())
    assert initial[0].state == "WAITING_TRIGGER" and initial[0].candidate is None
    assert context(direction) == result


def test_none_model_proposal_is_an_explicit_abstention():
    result = context("NONE")
    assert result.plan is None and result.reason == "MODEL_PROPOSED_NONE"


def test_missing_required_news_cannot_prepare_a_context_scenario():
    bars = history()
    with pytest.raises(ValueError, match="creation context"):
        bridge.context_scenario(
            "LONG",
            bars,
            cut_ms=CUT,
            assessment_sha256=ASSESSMENT,
            source_set_sha256=SOURCE_SET,
            sources=tuple(e for e in sources(bars[-1]) if e.kind != "NEWS"),
            required_sources=(("MACRO", "macro"), ("MARKET", "bars"), ("NEWS", "news")),
        )


def test_technical_bridge_preserves_original_candidate_and_does_not_extend_expiry(monkeypatch):
    bars = history()
    parent = SleeveIntent(
        "trend_breakout_v1",
        "BTCUSDT",
        Side.LONG,
        CUT - 1,
        CUT,
        CUT + 59_999,
        100,
        1,
        500,
        ExitPlan(98, 105, 120_000),
    )
    decision = ComplexDecision(
        "BTCUSDT",
        CUT,
        "CANDIDATE",
        "TECHNICAL_SELECTED",
        "BULL",
        "NORMAL",
        parent,
        (parent.intent_id,),
        (),
        "e" * 64,
        "f" * 64,
    )
    monkeypatch.setattr(bridge, "evaluate_complex", lambda *args, **kwargs: decision)
    actual, result = bridge.technical_scenario(
        bars,
        prefix_start_ms=bars[0].open_time_ms,
        cut_ms=CUT,
        source_set_sha256=SOURCE_SET,
        context_sha256=ASSESSMENT,
        sources=sources(bars[-1]),
        required_sources=(("MARKET", "bars"),),
    )
    assert actual is decision and result.plan.template is parent
    assert result.plan.template.entry_expires_ts_ms == CUT + 59_999
    assert result.plan.template.exit_plan is parent.exit_plan


def test_quiet_native_slot_never_becomes_fake_scenario(monkeypatch):
    bars = history()
    decision = ComplexDecision(
        "BTCUSDT", CUT, "QUIET", "NO_TECHNICAL_CANDIDATE", "RANGE", "NORMAL", None, (), (), "e" * 64, "f" * 64
    )
    monkeypatch.setattr(bridge, "evaluate_complex", lambda *args, **kwargs: decision)
    _, result = bridge.technical_scenario(
        bars,
        prefix_start_ms=bars[0].open_time_ms,
        cut_ms=CUT,
        source_set_sha256=SOURCE_SET,
        context_sha256=ASSESSMENT,
        sources=sources(bars[-1]),
        required_sources=(("MARKET", "bars"),),
    )
    assert result.plan is None and result.state == "QUIET"
    assert result.reason == "NO_TECHNICAL_CANDIDATE"


def test_opposite_technical_side_is_abstained_not_flipped(monkeypatch):
    bars = history()
    parent = SleeveIntent(
        "trend_breakout_v1",
        "BTCUSDT",
        Side.SHORT,
        CUT - 1,
        CUT,
        CUT + 299_999,
        100,
        1,
        500,
        ExitPlan(102, 95, 120_000),
    )
    decision = ComplexDecision(
        "BTCUSDT",
        CUT,
        "CANDIDATE",
        "TECHNICAL_SELECTED",
        "BULL",
        "NORMAL",
        parent,
        (parent.intent_id,),
        (),
        "e" * 64,
        "f" * 64,
    )
    monkeypatch.setattr(bridge, "evaluate_complex", lambda *args, **kwargs: decision)
    _, result = bridge.technical_scenario(
        bars,
        prefix_start_ms=bars[0].open_time_ms,
        cut_ms=CUT,
        source_set_sha256=SOURCE_SET,
        context_sha256=ASSESSMENT,
        sources=sources(bars[-1]),
        required_sources=(("MARKET", "bars"),),
    )
    assert result.plan is None and result.reason == "TECHNICAL_DIRECTION_OUTSIDE_PRICE_CAPABILITY"
    assert decision.candidate is parent and parent.side is Side.SHORT


def test_original_native_defaults_are_not_reconfigured():
    from adaptive_replay.complex_strategy import fixed_complex_policy

    policy = fixed_complex_policy()
    assert policy["adaptive_config"]["entry_lifetime_ms"] == 60_000
    assert policy["proposal_mapper"]["entry_lifetime_ms"] == 300_000
    assert policy["daily_trade_quota"] is None
    assert policy["production_registration"] is False


def test_creation_anchor_receipt_does_not_accept_forged_price_bytes():
    bars = history()
    bad = tuple(replace(e, payload_sha256="0" * 64) if e.kind == "MARKET" else e for e in sources(bars[-1]))
    with pytest.raises(ValueError, match="anchor bytes"):
        bridge.context_scenario(
            "LONG",
            bars,
            cut_ms=CUT,
            assessment_sha256=ASSESSMENT,
            source_set_sha256=SOURCE_SET,
            sources=bad,
            required_sources=(("MACRO", "macro"), ("MARKET", "bars"), ("NEWS", "news")),
        )


def test_native_trailing_is_explicit_policy_abstention_and_parent_survives(monkeypatch):
    bars = history()
    parent = SleeveIntent(
        "trend_breakout_v1",
        "BTCUSDT",
        Side.LONG,
        CUT - 1,
        CUT,
        CUT + 299_999,
        100,
        1,
        500,
        ExitPlan(98, 105, 120_000, 101, 1),
    )
    decision = ComplexDecision(
        "BTCUSDT",
        CUT,
        "CANDIDATE",
        "TECHNICAL_SELECTED",
        "BULL",
        "NORMAL",
        parent,
        (parent.intent_id,),
        (),
        "e" * 64,
        "f" * 64,
    )
    monkeypatch.setattr(bridge, "evaluate_complex", lambda *args, **kwargs: decision)
    actual, prepared = bridge.technical_scenario(
        bars,
        prefix_start_ms=bars[0].open_time_ms,
        cut_ms=CUT,
        source_set_sha256=SOURCE_SET,
        context_sha256=ASSESSMENT,
        sources=sources(bars[-1]),
        required_sources=(("MARKET", "bars"),),
    )
    assert actual is decision and actual.candidate is parent
    assert parent.exit_plan.trailing_activation_price == 101
    assert prepared.plan is None and prepared.state == "ABSTAIN"
    assert prepared.reason == "SCENARIO_V1_UNSUPPORTED_TRAILING"
