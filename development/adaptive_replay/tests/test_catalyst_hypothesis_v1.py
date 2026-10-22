"""Synthetic countertrend contract checks, not news/model/economic evidence."""

from dataclasses import asdict, replace

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay import hypothesis_v3 as v3
from adaptive_replay.catalyst_hypothesis_v1 import (
    ENTRY_KERNEL_ID,
    ENTRY_KERNEL_SOURCE_SHA256,
    POLICY_ID,
    CatalystPlan,
    evaluate_hypothesis,
)
from adaptive_replay.historical_context import digest
from adaptive_replay.scenarios import MINUTE, ScenarioEvidence, ScenarioObservation, ScenarioReview

CUT = 86_400_000
SYMBOL = "BTCUSDT"


def bar(open_ms, close=100.0, *, low=99.0, high=101.0):
    return Candle(
        SYMBOL, "1m", open_ms, open_ms + MINUTE - 1, 100, max(high, close), min(low, close), close, 10
    )


def source(candle):
    return ScenarioEvidence(
        "bars",
        "MARKET",
        SYMBOL,
        digest(candle_payload(candle)),
        candle.close_time_ms,
        candle.close_time_ms + 10_001,
        candle.close_time_ms + 10_001,
        600_000,
    )


def plan(*, side=Side.SHORT, regime="BULL", origin="CONTEXT_PROPOSAL", created=CUT + 12_001):
    sign = 1 if side is Side.LONG else -1
    anchor = bar(CUT - MINUTE)
    parent = SleeveIntent(
        "context_atr_proposal_v1" if origin == "CONTEXT_PROPOSAL" else "adaptive_pullback_range_v1",
        SYMBOL,
        side,
        CUT - 1,
        CUT,
        CUT + MINUTE - 1,
        100,
        1,
        500,
        ExitPlan(100 - 2 * sign, 100 + 5 * sign, 5 * MINUTE),
        (("native_marker", "unchanged"),),
    )
    policy = v3.HypothesisPolicy(CUT - 1, 5 * MINUTE, "quotes", 2_000, "TEST_FIXTURE", True)
    evidence = tuple(
        sorted(
            (source(anchor),)
            + tuple(
                ScenarioEvidence(name, kind, SYMBOL, "d" * 64, CUT - 1, CUT, CUT, 10 * MINUTE)
                for name, kind in (("macro", "MACRO"), ("news", "NEWS"))
            ),
            key=lambda e: (e.kind, e.source_id),
        )
    )
    assessment = (
        None
        if origin == "TECHNICAL"
        else v3.CreationAssessment(
            v3.creation_input_sha256("a" * 64, "b" * 64, anchor, evidence),
            "c" * 64,
            "e" * 64,
            side.value,
            CUT + 10_000,
            CUT + 12_000,
            CUT + 12_001,
            "TEST_FIXTURE",
        )
    )
    return CatalystPlan(
        parent,
        origin,
        regime,
        "NORMAL",
        CUT,
        created,
        "a" * 64,
        "b" * 64,
        evidence,
        anchor,
        tuple((e.kind, e.source_id) for e in evidence),
        policy,
        assessment,
    )


def observation(p, *, open_ms=CUT, confirming=True, disposition="ALLOW", quote=True, low=99, high=101):
    close = (100.5 if p.template.side is Side.LONG else 99.5) if confirming else 100
    candle = bar(open_ms, close, low=low, high=high)
    arrival = open_ms + MINUTE + 10_000
    sources = tuple(
        sorted(
            tuple(e for e in p.creation_evidence if e.kind != "MARKET") + (source(candle),),
            key=lambda e: (e.kind, e.source_id),
        )
    )
    market = ScenarioObservation(candle, arrival + 20, sources)
    prices = (100.49, 100.5) if p.template.side is Side.LONG else (99.5, 99.51)
    q = v3.EntryQuote(
        "quotes", SYMBOL, *prices, arrival + 10, arrival + 11, arrival + 12, 2_000, "TEST_FIXTURE"
    )
    obs = v3.HypothesisObservation(market, q if quote else None)
    if disposition is not None:
        review = ScenarioReview(
            p.scenario_id, p.template.side, disposition, obs.context_sha256, arrival + 20, "f" * 64
        )
        obs = replace(obs, market=replace(obs.market, review=review))
    return obs


@pytest.mark.parametrize("regime,side", [("BULL", Side.SHORT), ("BEAR", Side.LONG)])
def test_independent_catalyst_countertrend_preserves_true_regime_and_protection(regime, side):
    p = plan(regime=regime, side=side)
    before = asdict(p.template)
    result = evaluate_hypothesis(p, (observation(p),))[-1]
    assert result.state == "CONSUMED" and result.candidate is not None
    candidate = result.candidate
    assert p.regime == regime and candidate.side is side
    assert candidate.sleeve_id == POLICY_ID and candidate.sleeve_id != v3.POLICY_ID
    assert candidate.exit_plan is p.template.exit_plan
    assert asdict(p.template) == before
    metadata = dict(candidate.metadata)
    assert metadata["observed_regime"] == regime
    assert metadata["observed_defense"] == "NORMAL"
    assert metadata["entry_kernel_id"] == ENTRY_KERNEL_ID
    assert metadata["entry_kernel_source_sha256"] == ENTRY_KERNEL_SOURCE_SHA256
    assert metadata["hypothesis_policy_sha256"] == p.policy_sha256 != p.policy.sha256
    assert metadata["protection_sha256"] == p.protection_sha256
    assert candidate.intent_id != p.template.intent_id
    with pytest.raises(ValueError, match="unsupported regime/direction"):
        v3.HypothesisPlan(
            **{
                k: v
                for k, v in asdict(p).items()
                if k
                not in {"defense", "template", "policy", "anchor", "creation_evidence", "creation_assessment"}
            },
            template=p.template,
            policy=p.policy,
            anchor=p.anchor,
            creation_evidence=p.creation_evidence,
            creation_assessment=p.creation_assessment,
        )


@pytest.mark.parametrize(
    "regime,side", [("BULL", Side.LONG), ("BEAR", Side.SHORT), ("RANGE", Side.LONG), ("RANGE", Side.SHORT)]
)
def test_native_technical_capabilities_unchanged(regime, side):
    p = plan(regime=regime, side=side, origin="TECHNICAL")
    assert evaluate_hypothesis(p, (observation(p),))[-1].candidate is not None


@pytest.mark.parametrize("regime,side", [("BULL", Side.SHORT), ("BEAR", Side.LONG)])
def test_technical_countertrend_is_not_granted_by_context_capability(regime, side):
    with pytest.raises(ValueError, match="technical direction"):
        plan(regime=regime, side=side, origin="TECHNICAL")


@pytest.mark.parametrize(
    "changes",
    [
        {"regime": "CRASH"},
        {"regime": "UNCERTAIN"},
        {"regime": "CHOP"},
        {"defense": "CRASH"},
        {"defense": "POST_SHOCK_COOLDOWN"},
        {"defense": "SOURCE_UNAVAILABLE"},
    ],
)
def test_crash_uncertainty_cooldown_not_relabelled(changes):
    with pytest.raises(ValueError, match="NORMAL BULL/BEAR/RANGE"):
        replace(plan(), **changes)


@pytest.mark.parametrize("created", [CUT - 1, CUT + MINUTE, CUT + 2 * MINUTE])
def test_actual_late_birth_or_backdating_rejected(created):
    with pytest.raises(ValueError):
        plan(created=created)


@pytest.mark.parametrize("change", ["direction", "input", "future_capture", "early_request", "kind"])
def test_creation_assessment_binding_and_real_clocks(change):
    p = plan()
    a = p.creation_assessment
    changes = {
        "direction": {"direction": "LONG"},
        "input": {"input_sha256": "f" * 64},
        "future_capture": {"actual_captured_ms": p.created_ms + 1},
        "early_request": {"actual_requested_ms": CUT + 9_999},
        "kind": {"evidence_kind": "CALLER_ATTESTED_POINT_IN_TIME"},
    }
    with pytest.raises(ValueError, match="input/direction or actual"):
        replace(p, creation_assessment=replace(a, **changes[change]))


@pytest.mark.parametrize("change", ["missing", "additional", "stale", "future", "anchor"])
def test_exact_creation_sources_and_anchor(change):
    p = plan()
    receipts = p.creation_evidence
    index = next(i for i, e in enumerate(receipts) if e.kind == "MARKET")
    changes = {
        "stale": {"ttl_ms": 1},
        "future": {"captured_ms": p.created_ms + 1},
        "anchor": {"payload_sha256": "f" * 64},
    }
    if change == "missing":
        receipts = receipts[:index] + receipts[index + 1 :]
    elif change == "additional":
        receipts = tuple(
            sorted(
                receipts + (replace(receipts[index], source_id="extra-bars"),),
                key=lambda e: (e.kind, e.source_id),
            )
        )
    else:
        receipts = tuple(replace(e, **changes[change]) if i == index else e for i, e in enumerate(receipts))
    with pytest.raises(ValueError):
        replace(p, creation_evidence=receipts)


@pytest.mark.parametrize(
    "change", ["cut", "reference", "symbol", "metadata", "policy", "no_review", "no_assessment"]
)
def test_typed_plan_parent_provenance_cannot_be_forged(change):
    p = plan()
    changes = {
        "cut": {"origin_cut_ms": CUT + MINUTE},
        "reference": {
            "template": replace(p.template, reference_price=100.1, gross_reward_bps=5.1 / 100.1 * 10_000)
        },
        "symbol": {"anchor": replace(p.anchor, symbol="ETHUSDT")},
        "metadata": {"template": replace(p.template, metadata=(("observed_regime", "BEAR"),))},
        "policy": {"policy": asdict(p.policy)},
        "no_review": {"policy": replace(p.policy, require_review=False)},
        "no_assessment": {"creation_assessment": None},
    }
    with pytest.raises(ValueError):
        replace(p, **changes[change])


@pytest.mark.parametrize(
    "disposition,reason", [("VETO", "REVIEW_VETO"), ("DEFER", "REVIEW_DEFER"), (None, "REVIEW_MISSING_DEFER")]
)
def test_first_trigger_consumed_after_review_refusal_without_retry(disposition, reason):
    p = plan()
    first = observation(p, disposition=disposition)
    later = observation(p, open_ms=CUT + MINUTE)
    results = evaluate_hypothesis(p, (first, later))
    assert results[1].state == "CONSUMED" and results[1].reason == reason
    assert results[1].candidate is None
    assert results[2].reason == "TERMINAL_NO_RESURRECTION" and results[2].candidate is None


@pytest.mark.parametrize(
    "change",
    [
        "quote_missing",
        "quote_stale",
        "quote_stop",
        "review_identity",
        "review_context",
        "review_clock",
        "source_stale",
    ],
)
def test_confirmation_refuses_bad_quote_review_or_source_and_consumes(change):
    p = plan()
    obs = observation(p, quote=change != "quote_missing")
    if change in {"quote_stale", "quote_stop"}:
        q = (
            replace(obs.quote, event_ms=obs.market.observed_ms - 2_001)
            if change == "quote_stale"
            else replace(obs.quote, bid=102.0, ask=102.01)
        )
        obs = replace(obs, quote=q)
        obs = replace(
            obs,
            market=replace(obs.market, review=replace(obs.market.review, context_sha256=obs.context_sha256)),
        )
    elif change.startswith("review_"):
        edits = {
            "review_identity": {"scenario_id": "f" * 64},
            "review_context": {"context_sha256": "e" * 64},
            "review_clock": {"completed_ms": obs.market.observed_ms + 1},
        }
        obs = replace(obs, market=replace(obs.market, review=replace(obs.market.review, **edits[change])))
    elif change == "source_stale":
        sources = tuple(replace(e, ttl_ms=1) if e.kind == "NEWS" else e for e in obs.market.sources)
        obs = replace(obs, market=replace(obs.market, sources=sources))
    result = evaluate_hypothesis(p, (obs,))[-1]
    assert result.state == "CONSUMED" and result.candidate is None


@pytest.mark.parametrize("side,regime", [(Side.SHORT, "BULL"), (Side.LONG, "BEAR")])
def test_closed_stop_invalidation_precedes_same_bar_confirmation(side, regime):
    p = plan(side=side, regime=regime)
    obs = observation(p, low=97, high=103)
    result = evaluate_hypothesis(p, (obs,))[-1]
    assert result.state == "INVALIDATED" and result.candidate is None


def test_waiting_contiguity_missing_minute_expiry_duplicates_and_no_resurrection():
    p = plan()
    quiet = observation(p, confirming=False)
    confirming = observation(p, open_ms=CUT + MINUTE)
    result = evaluate_hypothesis(p, (quiet, quiet, confirming))
    assert len(result) == 3 and result[1].state == "WAITING_TRIGGER"
    assert result[-1].candidate is not None
    gap = evaluate_hypothesis(p, (confirming,))[-1]
    assert gap.state == "BLOCKED" and gap.reason == "MARKET_GAP_OR_UNAVAILABLE"
    expired = evaluate_hypothesis(p, (observation(p, open_ms=CUT + 5 * MINUTE),))[-1]
    assert expired.state == "EXPIRED" and expired.candidate is None
    with pytest.raises(ValueError, match="conflicting redelivery"):
        evaluate_hypothesis(p, (quiet, replace(quiet, quote=None)))
    with pytest.raises(ValueError, match="typed separate catalyst"):
        evaluate_hypothesis(asdict(p), ())


def test_scenario_and_policy_identity_do_not_hide_real_regime_or_kernel():
    p = plan()
    other = replace(p, regime="RANGE")
    assert p.scenario_id != other.scenario_id
    assert p.protection_sha256 == other.protection_sha256
    assert p.policy_sha256 != p.policy.sha256
    assert len(ENTRY_KERNEL_SOURCE_SHA256) == 64


@pytest.mark.parametrize(
    "origin,sleeve",
    [
        ("CONTEXT_PROPOSAL", "adaptive_pullback_range_v1"),
        ("TECHNICAL", "context_atr_proposal_v1"),
        ("CONTEXT_PROPOSAL", "unknown_family"),
    ],
)
def test_wrong_template_family_cannot_cross_origin_boundary(origin, sleeve):
    p = plan(origin=origin, side=Side.LONG)
    with pytest.raises(ValueError, match="exact unchanged native or context mapper"):
        replace(p, template=replace(p.template, sleeve_id=sleeve))


def test_old_v3_evaluator_cannot_accept_new_countertrend_plan():
    with pytest.raises(ValueError, match="typed separate V3"):
        v3.evaluate_hypothesis(plan(), ())


def test_no_closed_price_confirmation_means_no_candidate_even_after_allow_review():
    p = plan()
    result = evaluate_hypothesis(p, (observation(p, confirming=False),))[-1]
    assert result.state == "WAITING_TRIGGER" and result.candidate is None


def test_original_policy_and_source_declarations_cannot_be_late_or_unknown():
    p = plan()
    with pytest.raises(ValueError, match="sealed by original cut"):
        replace(p, policy=replace(p.policy, sealed_ms=CUT + 1))
    with pytest.raises(ValueError, match="cannot predate origin or renew"):
        replace(p, policy=replace(p.policy, hypothesis_lifetime_ms=1))
    with pytest.raises(ValueError, match="independent model creation"):
        replace(plan(origin="TECHNICAL", side=Side.LONG), creation_assessment=p.creation_assessment)


def test_revalidation_detects_mutation_bypassing_frozen_constructor():
    p = plan()
    object.__setattr__(p, "defense", "CRASH")
    with pytest.raises(ValueError, match="NORMAL BULL/BEAR/RANGE"):
        evaluate_hypothesis(p, ())
