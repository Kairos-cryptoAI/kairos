"""Synthetic adversarial composition, not actual news/model/fill/PnL evidence."""

from dataclasses import asdict, replace

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay import catalyst_policy_v1 as cp
from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_v3 import EntryQuote, HypothesisObservation
from adaptive_replay.scenarios import MINUTE, ScenarioEvidence, ScenarioObservation, ScenarioReview

from . import test_catalyst_policy_v1 as f

TARGET = sorted(f.UNIVERSE)[0]
ISSUE = f.START + MINUTE + 120


@pytest.fixture
def setup(monkeypatch):
    # Explicit synthetic native parent for isolating arbitration; the separate
    # policy suite exercises the genuinely native quiet RANGE without this patch.
    original = cp.evaluate_adaptive

    def native(rows):
        result = original(rows)
        if rows[-1].symbol != TARGET:
            return result
        cut = rows[-1].close_time_ms + 1
        intent = SleeveIntent(
            "adaptive_pullback_range_v1",
            TARGET,
            Side.LONG,
            cut - 1,
            cut,
            cut + MINUTE - 1,
            100.0,
            1.0,
            500.0,
            ExitPlan(98.0, 105.0, 5 * MINUTE),
            (),
        )
        return replace(result, status="INTENT", intent=intent)

    monkeypatch.setattr(cp, "evaluate_adaptive", native)
    p = f.policy()
    prepared = f.prepare(p, event=f.catalyst(TARGET), symbol=TARGET)
    slot = f.event_slot(prepared, TARGET)
    ledger, technical = cp.materialize(
        p,
        prepared,
        cp.CreationLedger(p.sha256),
        symbol=TARGET,
        origin="TECHNICAL",
        outcome=f.rp.CreationOutcome("NATIVE", digest(asdict(slot.technical)), f.START + 1_000),
    )
    ledger, context = cp.materialize(
        p,
        prepared,
        ledger,
        symbol=TARGET,
        origin="CONTEXT_PROPOSAL",
        outcome=f.outcome(prepared, p),
    )
    return p, prepared, ledger, dict(technical), dict(context)


def observation(plan, *, minute=f.START, close=100.1, disposition="ALLOW"):
    clock = minute + MINUTE + 120
    candle = Candle(
        TARGET, "1m", minute, minute + MINUTE - 1, 100.0, max(100.2, close), min(99.8, close), close, 10.0
    )
    sources = tuple(
        sorted(
            tuple(e for e in plan.creation_evidence if e.kind != "MARKET")
            + (
                ScenarioEvidence(
                    "market-fixture",
                    "MARKET",
                    TARGET,
                    digest(candle_payload(candle)),
                    candle.close_time_ms,
                    clock - 20,
                    clock - 20,
                    10 * MINUTE,
                ),
            ),
            key=lambda e: (e.kind, e.source_id),
        )
    )
    quote = EntryQuote(
        "quote-fixture",
        TARGET,
        close - 0.005,
        close + 0.005,
        clock - 10,
        clock - 9,
        clock - 8,
        2_000,
        "TEST_FIXTURE",
    )
    value = HypothesisObservation(ScenarioObservation(candle, clock, sources), quote)
    if disposition is not None:
        review = ScenarioReview(
            plan.scenario_id, plan.template.side, disposition, value.context_sha256, clock, "f" * 64
        )
        value = replace(value, market=replace(value.market, review=review))
    return value


def resolve(setup, *, arm="combined", runs=(), decisions=None, issued=ISSUE, current=None, **kwargs):
    p, prepared, ledger, _, _ = setup
    return cp.resolve_arm(
        p,
        prepared,
        ledger,
        decisions=decisions or cp.DecisionLedger(p.sha256),
        symbol=TARGET,
        arm_id=arm,
        issued_ms=issued,
        runs=runs,
        shared_gate=kwargs.pop("shared_gate", "PASS"),
        current_prepared=prepared if current is None else current,
        **kwargs,
    )


def test_candidate_specific_veto_does_not_globally_ban_an_independent_event(setup):
    _, _, _, technical, context = setup
    tech, event = technical["combined"], context["combined"]
    runs = (
        cp.OriginRun(tech, (observation(tech, disposition="VETO"),)),
        cp.OriginRun(event, (observation(event),)),
    )
    _, result = resolve(setup, runs=runs)
    assert result.reason == "CONTEXT_PROPOSAL" and result.candidate is not None
    assert result.candidate.exit_plan == event.template.exit_plan


def test_same_direction_selects_one_technical_parent_without_doubled_risk(setup):
    _, _, _, technical, context = setup
    tech, event = technical["combined"], context["combined"]
    runs = (cp.OriginRun(tech, (observation(tech),)), cp.OriginRun(event, (observation(event),)))
    state, result = resolve(setup, runs=runs)
    assert result.reason == "TECHNICAL_PRIORITY_ON_SAME_SIDE"
    assert result.candidate.exit_plan == tech.template.exit_plan
    assert len(state.resolutions) == 1
    duplicate_state, duplicate = resolve(setup, runs=runs, decisions=state)
    assert duplicate_state == state and duplicate == result


def test_reviewed_technical_arms_require_news_and_macro_but_control_does_not(setup):
    _, _, _, technical, _ = setup
    assert technical["strategy_only"].required_sources == (("MARKET", "market-fixture"),)
    for arm in ("context_review", "combined"):
        assert {k for k, _ in technical[arm].required_sources} == {"MARKET", "NEWS", "MACRO"}
        assert technical[arm].policy.require_review
    assert not technical["strategy_only"].policy.require_review


def test_unknown_peer_refusal_cannot_be_rescued_by_adding_same_time_evidence(setup):
    _, _, _, technical, context = setup
    tech, event = technical["combined"], context["combined"]
    first = (cp.OriginRun(event, (observation(event),)),)
    state, refused = resolve(setup, runs=first)
    assert refused.reason == "REQUIRED_PEER_UNAVAILABLE_NO_LATE_FALLBACK"
    _, retry = resolve(setup, decisions=state, runs=first + (cp.OriginRun(tech, (observation(tech),)),))
    assert retry.reason == "OPPORTUNITY_ALREADY_CONSUMED_NO_RESURRECTION" and retry.candidate is None


def test_missing_review_cannot_be_replaced_with_a_later_allow_for_same_bar(setup):
    _, _, _, _, context = setup
    event = context["independent_proposals"]
    state, refused = resolve(
        setup,
        arm="independent_proposals",
        runs=(cp.OriginRun(event, (observation(event, disposition=None),)),),
    )
    assert refused.candidate is None
    with pytest.raises(ValueError, match="original review/quote prefix"):
        resolve(
            setup,
            arm="independent_proposals",
            decisions=state,
            runs=(cp.OriginRun(event, (observation(event),)),),
        )


def test_later_bar_cannot_rescue_a_cohort_after_shared_gate_refusal(setup):
    _, _, _, _, context = setup
    event = context["independent_proposals"]
    original = observation(event)
    state, refused = resolve(
        setup, arm="independent_proposals", shared_gate="UNKNOWN", runs=(cp.OriginRun(event, (original,)),)
    )
    assert refused.reason == "SHARED_GATE_BLOCKED_OR_UNKNOWN"
    later = observation(event, minute=f.START + MINUTE)
    _, result = resolve(
        setup,
        arm="independent_proposals",
        decisions=state,
        issued=ISSUE + MINUTE,
        runs=(cp.OriginRun(event, (original, later)),),
    )
    assert result.reason == "OPPORTUNITY_ALREADY_CONSUMED_NO_RESURRECTION" and result.candidate is None


def test_unobserved_earlier_candidate_is_not_a_late_winner(setup):
    _, _, _, _, context = setup
    event = context["independent_proposals"]
    runs = (cp.OriginRun(event, (observation(event), observation(event, minute=f.START + MINUTE))),)
    _, result = resolve(setup, arm="independent_proposals", runs=runs, issued=ISSUE + MINUTE)
    assert result.reason == "FIRST_CANDIDATE_ARBITRATION_MISSED_NO_LATE_RESCUE"
    assert result.candidate is None


def test_future_peer_refusal_cannot_make_an_earlier_candidate_look_unopposed(setup):
    _, _, _, technical, context = setup
    tech, event = technical["combined"], context["combined"]
    runs = (
        cp.OriginRun(tech, (observation(tech),)),
        cp.OriginRun(
            event,
            (
                observation(event, close=100.0),
                observation(event, minute=f.START + MINUTE, disposition="VETO"),
            ),
        ),
    )
    with pytest.raises(ValueError, match="future peer observation"):
        resolve(setup, runs=runs)


def test_future_creation_none_is_not_positive_absence_at_an_earlier_issue(setup):
    p, prepared, ledger, _, _ = setup
    future = replace(ledger.records[-1], outcome=f.rp.CreationOutcome("NONE", "e" * 64, ISSUE + MINUTE))
    forged = replace(ledger, records=ledger.records[:-1] + (future,))
    with pytest.raises(ValueError, match="future creation outcome"):
        cp.resolve_arm(
            p,
            prepared,
            forged,
            decisions=cp.DecisionLedger(p.sha256),
            symbol=TARGET,
            arm_id="combined",
            issued_ms=ISSUE,
            runs=(),
            current_prepared=prepared,
            shared_gate="PASS",
        )


def test_conflicting_closed_price_histories_cannot_be_two_legitimate_origins(setup):
    _, _, _, technical, context = setup
    tech, event = technical["combined"], context["combined"]
    with pytest.raises(ValueError, match="conflicting shared closed-market"):
        resolve(
            setup,
            runs=(
                cp.OriginRun(tech, (observation(tech, close=100.1),)),
                cp.OriginRun(event, (observation(event, close=100.2),)),
            ),
        )


def test_same_cut_clean_branch_cannot_replace_original_preparation(setup):
    p, prepared, _, _, _ = setup
    other = f.prepare(p)  # internally valid, but not the same event history
    with pytest.raises(ValueError, match="same-cut substitution"):
        resolve(setup, current=other)
    assert other.previous == prepared.previous and other != prepared


def test_later_context_requires_linked_history_and_blocks_pending_after_revision(setup):
    p, prepared, _, _, context = setup
    event = context["independent_proposals"]
    cut = f.START + cp.PERIOD
    revised = f.catalyst(TARGET, version=f.historical_version(TARGET, captured=cut - 1, content="Revision"))
    current = cp.prepare_cut(p, prepared.checkpoint, f.full_cut(cut, events={TARGET: revised}))
    runs = (
        cp.OriginRun(
            event,
            tuple(observation(event, minute=f.START + i * MINUTE, close=100.0) for i in range(5))
            + (observation(event, minute=cut),),
        ),
    )
    with pytest.raises(ValueError, match="incomplete retained context chain"):
        resolve(setup, arm="independent_proposals", issued=cut + MINUTE + 120, runs=runs, current=current)
    _, result = resolve(
        setup,
        arm="independent_proposals",
        issued=cut + MINUTE + 120,
        runs=runs,
        current=current,
        context_chain=(current,),
    )
    assert result.reason == "CURRENT_INTEGRITY_BLOCKED_NO_PENDING_RESCUE"
    assert result.candidate is None


def test_current_unknown_coverage_blocks_pending_even_with_caller_pass(setup):
    p, prepared, _, _, context = setup
    event = context["independent_proposals"]
    cut = f.START + cp.PERIOD
    current = cp.prepare_cut(p, prepared.checkpoint, f.full_cut(cut, coverage="UNKNOWN"))
    runs = (
        cp.OriginRun(
            event,
            tuple(observation(event, minute=f.START + i * MINUTE, close=100.0) for i in range(5))
            + (observation(event, minute=cut),),
        ),
    )
    _, result = resolve(
        setup,
        arm="independent_proposals",
        issued=cut + MINUTE + 120,
        runs=runs,
        current=current,
        context_chain=(current,),
    )
    assert result.reason == "CURRENT_CONTEXT_UNAVAILABLE_OR_LATE" and result.candidate is None


def test_all_documents_of_new_root_share_the_batch_and_its_ttl():
    p = f.policy()
    first = f.catalyst(TARGET, version=f.historical_version(TARGET, document="first"))
    second = f.catalyst(
        TARGET, version=f.historical_version(TARGET, document="second", content="Part two"), ttl=100
    )
    cells = list(f.full_cut(f.START))
    cells[0] = replace(cells[0], events=tuple(sorted((first, second), key=lambda e: e.sha256)))
    prepared = cp.prepare_cut(p, cp.initial_state(p), tuple(cells))
    slot = f.event_slot(prepared)
    assert set(slot.event_batch) == {first.sha256, second.sha256}
    assert slot.reason == "MISSED_OR_STALE_EVENT_NO_CATCH_UP"


def test_event_cannot_impersonate_a_different_declared_publisher():
    with pytest.raises(ValueError, match="exact-version proof"):
        f.catalyst(TARGET, source_id="macro-fixture")
