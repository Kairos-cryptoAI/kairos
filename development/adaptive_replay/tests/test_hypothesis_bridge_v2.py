"""Synthetic checks for the separately versioned native-to-hypothesis bridge."""

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay import hypothesis_bridge_v2 as bridge
from adaptive_replay.complex_strategy import ComplexDecision, map_context_proposal
from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_v2 import HypothesisPlan, HypothesisPolicy
from adaptive_replay.inputs import UNIVERSE
from adaptive_replay.scenarios import ScenarioEvidence

CUT = 5 * 86_400_000
SYMBOL = UNIVERSE[0]
SOURCE_SET = "a" * 64
ASSESSMENT = "b" * 64


def policy(**changes):
    values = {
        "sealed_ms": CUT,
        "hypothesis_lifetime_ms": 20 * 60_000,
        "quote_source_id": "entry-quote",
        "maximum_quote_age_ms": 2_000,
        "evidence_kind": "TEST_FIXTURE",
    }
    values.update(changes)
    return HypothesisPolicy(**values)


def history():
    return tuple(
        Candle(SYMBOL, "1m", t, t + 59_999, 100, 100.7, 99.3, 100, 10)
        for t in range(CUT - 3_240 * 60_000, CUT, 60_000)
    )


def sources(anchor, *, context=False):
    rows = [
        ScenarioEvidence("bars", "MARKET", SYMBOL, digest(candle_payload(anchor)), CUT - 1, CUT, CUT, 900_000)
    ]
    if context:
        rows.extend(
            (
                ScenarioEvidence("news", "NEWS", SYMBOL, "c" * 64, CUT - 1, CUT, CUT, 900_000),
                ScenarioEvidence("macro", "MACRO", SYMBOL, "d" * 64, CUT - 1, CUT, CUT, 900_000),
            )
        )
    return tuple(sorted(rows, key=lambda item: (item.kind, item.source_id)))


def parent(*, side=Side.LONG, trailing=False, expiry_ms=59_999):
    if side is Side.SHORT:
        exits = ExitPlan(102, 95, 120_000)
    else:
        exits = ExitPlan(98, 105, 120_000, 101, 1) if trailing else ExitPlan(98, 105, 120_000)
    return SleeveIntent("trend_breakout_v1", SYMBOL, side, CUT - 1, CUT, CUT + expiry_ms, 100, 1, 500, exits)


def decision(candidate, *, state="CANDIDATE", regime="BULL", defense="NORMAL"):
    return ComplexDecision(
        SYMBOL,
        CUT,
        state,
        "TEST_DECISION",
        regime,
        defense,
        candidate,
        () if candidate is None else (candidate.intent_id,),
        (),
        "e" * 64,
        "f" * 64,
    )


def call_technical(monkeypatch, native, *, hypothesis_policy=None):
    calls = []

    def evaluate(*args, **kwargs):
        calls.append((args, kwargs))
        return native

    monkeypatch.setattr(bridge, "evaluate_complex", evaluate)
    rows = history()
    receipts = sources(rows[-1])
    result = bridge.technical_hypothesis(
        rows,
        prefix_start_ms=rows[0].open_time_ms,
        cut_ms=CUT,
        source_set_sha256=SOURCE_SET,
        context_sha256=ASSESSMENT,
        sources=receipts,
        required_sources=(("MARKET", "bars"),),
        policy=hypothesis_policy or policy(),
    )
    return result, calls, rows, receipts


def test_technical_hypothesis_wraps_original_parent_and_trailing_unchanged(monkeypatch):
    original = parent(trailing=True)
    native = decision(original)
    (returned, prepared), calls, _, _ = call_technical(monkeypatch, native)

    assert returned is native
    assert len(calls) == 1
    assert prepared.state == "WAITING_TRIGGER"
    assert isinstance(prepared.plan, HypothesisPlan)
    assert prepared.plan.template is original
    assert prepared.plan.template.intent_id == original.intent_id
    assert prepared.plan.template.entry_expires_ts_ms == original.entry_expires_ts_ms
    assert prepared.plan.template.exit_plan is original.exit_plan
    assert prepared.plan.template.exit_plan.trailing_activation_price == 101
    assert prepared.plan.policy == policy()


@pytest.mark.parametrize(("native_state", "candidate"), [("QUIET", None), ("UNAVAILABLE", None)])
def test_technical_quiet_and_unavailable_are_preserved_without_fake_plan(
    monkeypatch, native_state, candidate
):
    native = decision(candidate, state=native_state)
    (returned, prepared), calls, _, _ = call_technical(monkeypatch, native)
    assert returned is native and len(calls) == 1
    assert prepared.state == native_state
    assert prepared.reason == native.reason
    assert prepared.plan is None


def test_explicit_policy_is_validated_before_native_evaluation(monkeypatch):
    called = False

    def unexpected(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("native evaluator should not run for invalid policy")

    monkeypatch.setattr(bridge, "evaluate_complex", unexpected)
    rows = history()
    with pytest.raises(ValueError, match="typed hypothesis policy"):
        bridge.technical_hypothesis(
            rows,
            prefix_start_ms=rows[0].open_time_ms,
            cut_ms=CUT,
            source_set_sha256=SOURCE_SET,
            context_sha256=ASSESSMENT,
            sources=sources(rows[-1]),
            required_sources=(("MARKET", "bars"),),
            policy=object(),
        )
    assert not called


@pytest.mark.parametrize(
    ("regime", "defense", "reason"),
    [
        ("UNCERTAIN", "NORMAL", "HYPOTHESIS_V2_UNSUPPORTED_REGIME_OR_DEFENSE"),
        ("CRASH", "NORMAL", "HYPOTHESIS_V2_UNSUPPORTED_REGIME_OR_DEFENSE"),
        ("BULL", "CRASH", "HYPOTHESIS_V2_UNSUPPORTED_REGIME_OR_DEFENSE"),
    ],
)
def test_technical_unsupported_regime_or_defense_abstains(monkeypatch, regime, defense, reason):
    (native, prepared), calls, _, _ = call_technical(
        monkeypatch, decision(parent(), regime=regime, defense=defense)
    )
    assert len(calls) == 1
    assert prepared.plan is None and prepared.state == "ABSTAIN" and prepared.reason == reason
    assert native.candidate is not None


def test_opposite_technical_side_is_not_flipped_or_reissued(monkeypatch):
    original = parent(side=Side.SHORT)
    (native, prepared), calls, _, _ = call_technical(monkeypatch, decision(original, regime="BULL"))
    assert len(calls) == 1
    assert prepared.plan is None and prepared.state == "ABSTAIN"
    assert prepared.reason == "TECHNICAL_DIRECTION_OUTSIDE_PRICE_CAPABILITY"
    assert native.candidate is original and original.side is Side.SHORT


def test_context_hypothesis_uses_actual_mapper_and_requires_creation_news_macro():
    rows = history()
    receipts = sources(rows[-1], context=True)
    required = (("MACRO", "macro"), ("MARKET", "bars"), ("NEWS", "news"))
    result = bridge.context_hypothesis(
        "LONG",
        rows,
        cut_ms=CUT,
        assessment_sha256=ASSESSMENT,
        source_set_sha256=SOURCE_SET,
        sources=receipts,
        required_sources=required,
        policy=policy(),
    )
    assert result.state == "WAITING_TRIGGER"
    assert result.plan is not None and result.plan.origin == "CONTEXT_PROPOSAL"
    assert result.plan.template.entry_expires_ts_ms == CUT + 299_999
    assert result.plan.template.signal_strength == 1
    assert result.plan.policy == policy()
    mapped = map_context_proposal("LONG", rows, cut_ms=CUT, assessment_sha256=ASSESSMENT)
    assert result.plan.context_sha256 == digest({"assessment": ASSESSMENT, "history": mapped.history_sha256})
    assert dict(result.plan.template.metadata)["planning_cost_authority"] == (
        "ASSUMPTION_NOT_VENUE_MEASUREMENT"
    )
    with pytest.raises(ValueError, match="creation sources"):
        bridge.context_hypothesis(
            "LONG",
            rows,
            cut_ms=CUT,
            assessment_sha256=ASSESSMENT,
            source_set_sha256=SOURCE_SET,
            sources=tuple(item for item in receipts if item.kind != "NEWS"),
            required_sources=required,
            policy=policy(),
        )


def test_none_context_direction_is_abstention_not_synthetic_hypothesis():
    rows = history()
    receipts = sources(rows[-1], context=True)
    result = bridge.context_hypothesis(
        "NONE",
        rows,
        cut_ms=CUT,
        assessment_sha256=ASSESSMENT,
        source_set_sha256=SOURCE_SET,
        sources=receipts,
        required_sources=(("MACRO", "macro"), ("MARKET", "bars"), ("NEWS", "news")),
        policy=policy(),
    )
    assert result.state == "ABSTAIN"
    assert result.reason == "MODEL_PROPOSED_NONE"
    assert result.plan is None


def test_context_opposite_direction_is_abstained_not_flipped(monkeypatch):
    rows = history()
    original = parent(side=Side.SHORT, expiry_ms=299_999)
    mapped = type("Mapped", (), {"candidate": original, "reason": "MAPPED", "history_sha256": "f" * 64})()
    monkeypatch.setattr(bridge, "map_context_proposal", lambda *args, **kwargs: mapped)
    monkeypatch.setattr(
        bridge,
        "evaluate_adaptive",
        lambda *_: type("D", (), {"regime": type("R", (), {"value": "BULL"})()})(),
    )
    result = bridge.context_hypothesis(
        "SHORT",
        rows,
        cut_ms=CUT,
        assessment_sha256=ASSESSMENT,
        source_set_sha256=SOURCE_SET,
        sources=sources(rows[-1], context=True),
        required_sources=(("MACRO", "macro"), ("MARKET", "bars"), ("NEWS", "news")),
        policy=policy(),
    )
    assert result.plan is None and result.state == "ABSTAIN"
    assert result.reason == "MODEL_DIRECTION_OUTSIDE_PRICE_CAPABILITY"
    assert original.side is Side.SHORT


def test_context_crash_regime_is_explicitly_unsupported(monkeypatch):
    rows = history()
    original = parent(expiry_ms=299_999)
    mapped = type("Mapped", (), {"candidate": original, "reason": "MAPPED", "history_sha256": "f" * 64})()
    monkeypatch.setattr(bridge, "map_context_proposal", lambda *args, **kwargs: mapped)
    monkeypatch.setattr(
        bridge,
        "evaluate_adaptive",
        lambda *_: type("D", (), {"regime": type("R", (), {"value": "CRASH"})()})(),
    )
    result = bridge.context_hypothesis(
        "LONG",
        rows,
        cut_ms=CUT,
        assessment_sha256=ASSESSMENT,
        source_set_sha256=SOURCE_SET,
        sources=sources(rows[-1], context=True),
        required_sources=(("MACRO", "macro"), ("MARKET", "bars"), ("NEWS", "news")),
        policy=policy(),
    )
    assert result.plan is None and result.state == "ABSTAIN"
    assert result.reason == "HYPOTHESIS_V2_UNSUPPORTED_REGIME"
