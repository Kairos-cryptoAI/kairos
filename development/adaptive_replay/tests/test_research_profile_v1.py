"""Bounded synthetic contract tests for the opt-in research preparation profile.

These fixtures validate deterministic mechanics only; they are not native market
evidence, model-quality evidence, or real-profit evidence.
"""

from dataclasses import asdict, replace

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay import research_profile_v1 as rp
from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_v3 import CreationAssessment
from adaptive_replay.inputs import UNIVERSE
from adaptive_replay.scenarios import MINUTE, ScenarioEvidence

START = 1_700_000_100_000  # absolute UTC-aligned five-minute boundary
SOURCE_SET = "a" * 64
MODEL = "b" * 64
REQUIRED = (("MACRO", "macro-fixture"), ("MARKET", "market-fixture"), ("NEWS", "news-fixture"))


def profile(**changes):
    values = dict(
        declared_ms=START - MINUTE,
        start_ms=START,
        end_ms=START + 60 * MINUTE,
        source_set_sha256=SOURCE_SET,
        model_config_sha256=MODEL,
        quote_source_id="quote-fixture",
        required_sources=REQUIRED,
        evidence_kind="TEST_FIXTURE",
    )
    values.update(changes)
    return rp.ResearchProfile(**values)


def history(symbol, cut, *, center=100.0, width=0.7, drift=0.0):
    """Stable absolute-time overlap: exactly the full 54h/3240 one-minute bars."""
    first = cut - rp.HISTORY_BARS * MINUTE
    rows = []
    for i in range(rp.HISTORY_BARS):
        t = first + i * MINUTE
        close = center + drift * i
        rows.append(Candle(symbol, "1m", t, t + MINUTE - 1, close, close + width, close - width, close, 10.0))
    return tuple(rows)


def sources_for(symbol, rows, observed):
    anchor = rows[-1]
    payload = digest(candle_payload(anchor))
    return tuple(
        ScenarioEvidence(
            source_id,
            kind,
            symbol,
            payload,
            anchor.close_time_ms,
            anchor.close_time_ms,
            observed,
            10 * MINUTE,
        )
        for kind, source_id in REQUIRED
    )


def cell(symbol, cut, *, observed=None, rows=None, budget="AVAILABLE", receipts=None):
    observed = cut + 1_000 if observed is None else observed
    rows = history(symbol, cut) if rows is None else rows
    return rp.PriceCell(
        cut,
        observed,
        symbol,
        rows,
        sources_for(symbol, rows, observed) if receipts is None else receipts,
        budget,
    )


def full_cut(cut, **kwargs):
    return tuple(cell(symbol, cut, **kwargs) for symbol in UNIVERSE)


def prepared_cut(p, *, cut=START):
    checkpoint, slots = rp.prepare_next_cut(p, rp.initial_state(p), full_cut(cut))
    return rp.PreparedCut(checkpoint, slots)


def direction_outcome(p, slot, direction="LONG", *, requested_delta=1_000, response="c" * 64):
    requested = slot.cell.observed_ms + requested_delta
    completed = requested + 10
    captured = completed + 10
    assessment = CreationAssessment(
        slot.creation_input_sha256,
        response,
        p.model_config_sha256,
        direction,
        requested,
        completed,
        captured,
        p.evidence_kind,
    )
    return rp.CreationOutcome("DIRECTION", response, captured, assessment)


def test_profile_is_explicit_research_only_and_preserves_native_gates():
    definition = rp.profile_definition()
    assert definition["classification"] == "RESEARCH_PREPARATION_ONLY"
    assert not definition["provider_dispatch"] and not definition["campaign_enrollment"]
    assert not definition["trading_authority"] and definition["daily_trade_quota"] is None
    assert definition["adaptive_code_sha256"] == rp.ADAPTIVE_CODE_SHA256
    assert definition["adaptive_config_sha256"] == rp.ADAPTIVE_CONFIG_SHA256
    # This rechecks the actual installed adaptive source/config fingerprint.
    state = rp.initial_state(profile())
    assert state.last_cut_ms == START - rp.PERIOD_MS


def test_quiet_real_native_range_full_universe_and_market_anchor_receipt(monkeypatch):
    # Keep the required quiet RANGE fixture genuinely native: no mocked evaluator.
    monkeypatch.setattr(rp, "_sources_ready", lambda p, c: True)
    p = profile()
    cut = rp.initial_state(p)
    next_state, receipts = rp.prepare_next_cut(p, cut, full_cut(START))
    assert len(receipts) == 5 and tuple(x.cell.symbol for x in receipts) == tuple(sorted(UNIVERSE))
    assert all(x.regime == "RANGE" and x.reason == "INITIAL_DECLARED_EPOCH" for x in receipts)
    assert all(x.allowed_directions == ("LONG", "SHORT") for x in receipts)
    assert all(len(x.cell.rows) == 3240 for x in receipts)
    assert all(x.cell.rows[0].open_time_ms == START - 3240 * MINUTE for x in receipts)
    for item in receipts:
        market = next(s for s in item.cell.sources if s.kind == "MARKET")
        assert market.event_ms == item.cell.rows[-1].close_time_ms
        assert market.payload_sha256 == digest(candle_payload(item.cell.rows[-1]))
    assert next_state.last_cut_ms == START


def test_receipts_require_ordered_actual_source_clocks_and_anchor_hash():
    symbol = UNIVERSE[0]
    rows = history(symbol, START)
    good = sources_for(symbol, rows, START + 1_000)
    assert rp._sources_ready(profile(), cell(symbol, START, receipts=good))
    late = tuple(replace(s, captured_ms=START + MINUTE + 1) if s.kind == "NEWS" else s for s in good)
    bad_anchor = tuple(replace(s, payload_sha256="c" * 64) if s.kind == "MARKET" else s for s in good)
    assert not rp._sources_ready(profile(), cell(symbol, START, receipts=late))
    assert not rp._sources_ready(profile(), cell(symbol, START, receipts=bad_anchor))
    with pytest.raises(ValueError):
        rp.PriceCell(START, START + 1, symbol, rows, tuple(reversed(good)), "AVAILABLE")


def test_full_five_symbol_cut_and_contiguous_absolute_overlap_are_mandatory():
    p, state = profile(), rp.initial_state(profile())
    with pytest.raises(ValueError, match="full five-symbol"):
        rp.prepare_next_cut(p, state, full_cut(START)[:-1])
    # Each next cut is generated from absolute time, so the 3235-row overlap is exact.
    first_state, _ = rp.prepare_next_cut(p, state, full_cut(START))
    second_state, out = rp.prepare_next_cut(p, first_state, full_cut(START + rp.PERIOD_MS))
    assert second_state.last_cut_ms == START + rp.PERIOD_MS
    assert len(out) == 5
    third_cut = START + 2 * rp.PERIOD_MS
    shifted = list(history(UNIVERSE[0], third_cut))
    shifted[10] = replace(shifted[10], close=shifted[10].close + 0.01)
    bad_cells = list(full_cut(third_cut))
    bad_cells[0] = cell(UNIVERSE[0], third_cut, rows=tuple(shifted))
    _, integrity_receipts = rp.prepare_next_cut(p, second_state, tuple(bad_cells))
    target_receipt = next(x for x in integrity_receipts if x.cell.symbol == UNIVERSE[0])
    assert target_receipt.reason == "PRICE_OVERLAP_INTEGRITY_CONFLICT"


def test_no_call_source_or_budget_consumes_initial_epoch_without_retry():
    p = profile()
    cells = list(full_cut(START))
    target = UNIVERSE[0]
    cells[0] = cell(target, START, budget="BLOCKED")
    state, out = rp.prepare_next_cut(p, rp.initial_state(p), tuple(cells))
    receipt = next(x for x in out if x.cell.symbol == target)
    assert receipt.context_state == "NO_CALL" and receipt.epoch_sha256
    assert receipt.reason == "BUDGET_UNAVAILABLE_EPOCH_CONSUMED_NO_CALL"
    assert state.symbols[0].consumed_observed_ms == receipt.cell.observed_ms
    with pytest.raises(ValueError, match="late or restarted"):
        rp._step_symbol(p, rp.SymbolLatch(target), cell(target, START + rp.PERIOD_MS))


def test_context_not_ready_consumes_eligible_epoch_and_emits_no_creation_input():
    p = profile()
    target = UNIVERSE[0]
    no_news = tuple(s for s in sources_for(target, history(target, START), START + 1000) if s.kind != "NEWS")
    cells = list(full_cut(START))
    cells[0] = cell(target, START, receipts=no_news)
    _, out = rp.prepare_next_cut(p, rp.initial_state(p), tuple(cells))
    receipt = next(x for x in out if x.cell.symbol == target)
    assert receipt.reason == "CONTEXT_UNAVAILABLE_EPOCH_CONSUMED_NO_CALL"
    assert receipt.creation_input_sha256 is None and receipt.context_state == "NO_CALL"


def test_reset_witness_is_distinct_from_later_event_and_frozen_bounds_survive_new_cut():
    g = rp.Geometry("CONTEXT_FROZEN_RANGE_EXCURSION", START, 99.0, 101.0)
    latch = rp.SymbolLatch(UNIVERSE[0], "RANGE", g, START + 1000, overlap_sha256="d" * 64)
    assert rp._reset(latch, 100.0)
    assert not rp._event_directions(latch, 100.0)
    assert rp._event_directions(latch, 99.1) == ("LONG",)
    assert rp._event_directions(latch, 100.9) == ("SHORT",)
    assert rp._event_directions(latch, 99.0) == ("LONG",)
    # A later cut does not alter these bounds; explicit replacement requires a new event.
    assert latch.geometry.lower == 99.0 and latch.geometry.upper == 101.0


def test_old_frozen_geometry_qualifies_event_not_new_geometry():
    old = rp.Geometry("CONTEXT_FROZEN_RANGE_EXCURSION", START, 99.0, 101.0)
    latch = rp.SymbolLatch(UNIVERSE[0], "RANGE", old, START + 500, START + rp.PERIOD_MS)
    assert rp._event_directions(latch, 99.2) == ("LONG",)
    new = rp.Geometry("CONTEXT_FROZEN_RANGE_EXCURSION", START + rp.PERIOD_MS, 98.0, 102.0)
    assert not rp._event_directions(replace(latch, geometry=new), 99.2)


@pytest.mark.parametrize("regime,close,direction", [("BULL", 99.0, "LONG"), ("BEAR", 101.0, "SHORT")])
def test_mean_reclaim_uses_original_frozen_mean(regime, close, direction):
    g = rp.Geometry("CONTEXT_FROZEN_MEAN_RECLAIM", START, 100.0, 100.0)
    latch = rp.SymbolLatch(UNIVERSE[0], regime, g, START + 1000, START + rp.PERIOD_MS)
    assert rp._event_directions(latch, 101.0 if regime == "BULL" else 99.0) == (direction,)


def test_none_or_error_is_receipt_only_and_not_retried(monkeypatch):
    p = profile()
    monkeypatch.setattr(rp, "crash_defense", lambda decision, rows: "NORMAL")
    # A consumed initial slot with unavailable sources produces no call permit.
    target = UNIVERSE[0]
    cells = list(full_cut(START))
    cells[0] = cell(target, START, receipts=())
    _, out = rp.prepare_next_cut(p, rp.initial_state(p), tuple(cells))
    slot = next(x for x in out if x.cell.symbol == target)
    assert slot.context_state == "NO_CALL" and slot.epoch_sha256
    monkeypatch.setattr(rp, "evaluate_adaptive", lambda _: None)
    # The public preparation contract only emits evidence; it never invokes a model.
    assert not hasattr(rp, "dispatch") and not hasattr(rp, "run_campaign")
    assert slot.creation_input_sha256 is None


def test_price_gap_regime_change_and_integrity_conflict_are_terminal(monkeypatch):
    p = profile()
    monkeypatch.setattr(rp, "crash_defense", lambda decision, rows: "NORMAL")
    native_evaluator = rp.evaluate_adaptive
    monkeypatch.setattr(rp, "evaluate_adaptive", native_evaluator)
    first, out = rp.prepare_next_cut(p, rp.initial_state(p), full_cut(START))
    # Regime flip cannot silently start a new epoch.
    monkeypatch.setattr(
        rp,
        "evaluate_adaptive",
        lambda rows: replace(native_evaluator(rows), regime=type(native_evaluator(rows).regime).BULL),
    )
    next_state, receipts = rp.prepare_next_cut(p, first, full_cut(START + rp.PERIOD_MS))
    assert all(x.reason == "REGIME_CHANGED_TERMINAL" for x in receipts)
    assert all(x.context_state == "NO_CALL" for x in receipts)
    with pytest.raises(ValueError, match="contiguous original cuts"):
        rp.prepare_next_cut(p, first, full_cut(START + 2 * rp.PERIOD_MS))
    assert next_state.last_cut_ms == START + rp.PERIOD_MS


@pytest.mark.parametrize(
    "mutation", ["missing_symbol", "duplicate_symbol", "wrong_cut", "late_observation", "lost_latch"]
)
def test_malformed_denominator_or_retained_state_rejected(mutation):
    p, state = profile(), rp.initial_state(profile())
    cells = list(full_cut(START))
    if mutation == "missing_symbol":
        cells.pop()
    elif mutation == "duplicate_symbol":
        cells[-1] = cells[0]
    elif mutation == "wrong_cut":
        cells[0] = cell(cells[0].symbol, START + rp.PERIOD_MS)
    elif mutation == "late_observation":
        cells[0] = cell(cells[0].symbol, START, observed=START + MINUTE + 1)
    else:
        state, _ = rp.prepare_next_cut(p, state, tuple(cells))
        with pytest.raises(ValueError, match="checkpoint hash"):
            replace(state, symbols=(rp.SymbolLatch(UNIVERSE[0]), *state.symbols[1:]))
        return
    if mutation == "late_observation":
        next_state, receipts = rp.prepare_next_cut(p, state, tuple(cells))
        reason = next(x for x in receipts if x.cell.symbol == UNIVERSE[0]).reason
        assert reason == "PRICE_UNAVAILABLE_OR_LATE_TERMINAL"
        assert next_state.symbols[0].terminal == "PRICE_UNAVAILABLE_OR_LATE_TERMINAL"
    else:
        with pytest.raises(ValueError):
            rp.prepare_next_cut(p, state, tuple(cells))


def test_preparation_receipts_cannot_be_replaced_under_checkpoint():
    p = profile()
    prepared = prepared_cut(p)
    altered = replace(prepared.slots[0], reason="ALTERED_AFTER_PREPARATION")
    with pytest.raises(ValueError, match="receipts changed"):
        rp.PreparedCut(prepared.checkpoint, (altered, *prepared.slots[1:]))


def test_context_v3_plan_actual_clock_ttl_parent_and_model_configuration():
    p = profile()
    prepared = prepared_cut(p)
    slot = prepared.slots[0]
    outcome = direction_outcome(p, slot)
    materializations = rp.initial_materializations(p)
    next_state, plan = rp.materialize_hypothesis(
        p,
        prepared,
        materializations,
        symbol=slot.cell.symbol,
        arm_id="independent_proposals",
        origin="CONTEXT_PROPOSAL",
        outcome=outcome,
    )
    assert plan is not None and plan.origin_cut_ms == START
    assert plan.created_ms == outcome.actual_created_ms
    assert plan.policy.hypothesis_lifetime_ms == 15 * MINUTE
    assert plan.policy.maximum_quote_age_ms == 2_000 and plan.policy.require_review is True
    assert plan.template.entry_eligible_ts_ms == START
    assert plan.template.decision_ts_ms == START - 1
    wrong_assessment = replace(outcome.assessment, model_config_sha256="e" * 64)
    wrong = replace(outcome, assessment=wrong_assessment, original_sha256=wrong_assessment.response_sha256)
    with pytest.raises(ValueError):
        rp.materialize_hypothesis(
            p,
            prepared,
            next_state,
            symbol=slot.cell.symbol,
            arm_id="independent_proposals",
            origin="CONTEXT_PROPOSAL",
            outcome=wrong,
        )
    late = direction_outcome(p, slot, requested_delta=MINUTE)
    with pytest.raises(ValueError):
        rp.materialize_hypothesis(
            p,
            prepared,
            materializations,
            symbol=slot.cell.symbol,
            arm_id="independent_proposals",
            origin="CONTEXT_PROPOSAL",
            outcome=late,
        )


def test_context_assessment_must_match_profile_evidence_kind():
    p = profile(evidence_kind="CALLER_ATTESTED_POINT_IN_TIME")
    prepared = prepared_cut(p)
    slot = prepared.slots[0]
    outcome = direction_outcome(profile(), slot)
    # Outcome itself is structurally valid; it cannot cross the profile clock domain.
    with pytest.raises(ValueError, match="evidence"):
        rp.materialize_hypothesis(
            p,
            prepared,
            rp.initial_materializations(p),
            symbol=slot.cell.symbol,
            arm_id="independent_proposals",
            origin="CONTEXT_PROPOSAL",
            outcome=outcome,
        )


def test_context_sources_must_still_be_fresh_at_actual_creation():
    p = profile()
    cells = list(full_cut(START))
    target = cells[0]
    short = tuple(replace(source, ttl_ms=1_001) for source in target.sources)
    cells[0] = replace(target, sources=short)
    checkpoint, slots = rp.prepare_next_cut(p, rp.initial_state(p), tuple(cells))
    prepared = rp.PreparedCut(checkpoint, slots)
    slot = next(item for item in prepared.slots if item.cell.symbol == target.symbol)
    outcome = direction_outcome(p, slot, requested_delta=0)
    assert slot.context_state == "ELIGIBLE"
    # All evidence is ready at the observation, but not beyond its one-minute TTL.
    stale_outcome = replace(
        outcome,
        actual_created_ms=slot.cell.observed_ms + 20,
        assessment=replace(
            outcome.assessment,
            actual_completed_ms=slot.cell.observed_ms + 10,
            actual_captured_ms=slot.cell.observed_ms + 20,
        ),
    )
    assert all(source.ready_at(slot.cell.observed_ms) for source in slot.cell.sources)
    assert not all(source.ready_at(stale_outcome.actual_created_ms) for source in slot.cell.sources)
    with pytest.raises(ValueError, match="evidence/actual clock"):
        rp.materialize_hypothesis(
            p,
            prepared,
            rp.initial_materializations(p),
            symbol=slot.cell.symbol,
            arm_id="independent_proposals",
            origin="CONTEXT_PROPOSAL",
            outcome=stale_outcome,
        )


def test_materialization_denies_none_failure_and_changed_direction_or_clock_retries():
    p = profile()
    prepared = prepared_cut(p)
    slot = prepared.slots[0]
    initial = rp.initial_materializations(p)
    none = rp.CreationOutcome("NONE", "d" * 64, slot.cell.observed_ms + 2_000)
    after_none, plan = rp.materialize_hypothesis(
        p,
        prepared,
        initial,
        symbol=slot.cell.symbol,
        arm_id="independent_proposals",
        origin="CONTEXT_PROPOSAL",
        outcome=none,
    )
    assert plan is None
    failed = replace(none, status="FAILED", original_sha256="e" * 64)
    with pytest.raises(ValueError, match="different outcome"):
        rp.materialize_hypothesis(
            p,
            prepared,
            after_none,
            symbol=slot.cell.symbol,
            arm_id="independent_proposals",
            origin="CONTEXT_PROPOSAL",
            outcome=failed,
        )
    direction = direction_outcome(p, slot)
    bound, _ = rp.materialize_hypothesis(
        p,
        prepared,
        initial,
        symbol=slot.cell.symbol,
        arm_id="independent_proposals",
        origin="CONTEXT_PROPOSAL",
        outcome=direction,
    )
    alternatives = (
        direction_outcome(p, slot, direction="SHORT"),
        direction_outcome(p, slot, direction="LONG", requested_delta=2_000),
        direction_outcome(p, slot, direction="LONG", response="f" * 64),
    )
    for changed in alternatives:
        with pytest.raises(ValueError, match="different outcome"):
            rp.materialize_hypothesis(
                p,
                prepared,
                bound,
                symbol=slot.cell.symbol,
                arm_id="independent_proposals",
                origin="CONTEXT_PROPOSAL",
                outcome=changed,
            )


def test_same_context_outcome_redelivery_and_ab_sharing_are_idempotent():
    p = profile()
    prepared = prepared_cut(p)
    slot = prepared.slots[0]
    outcome = direction_outcome(p, slot)
    initial = rp.initial_materializations(p)
    after_a, plan_a = rp.materialize_hypothesis(
        p,
        prepared,
        initial,
        symbol=slot.cell.symbol,
        arm_id="independent_proposals",
        origin="CONTEXT_PROPOSAL",
        outcome=outcome,
    )
    redelivered, plan_again = rp.materialize_hypothesis(
        p,
        prepared,
        after_a,
        symbol=slot.cell.symbol,
        arm_id="independent_proposals",
        origin="CONTEXT_PROPOSAL",
        outcome=outcome,
    )
    after_b, plan_b = rp.materialize_hypothesis(
        p,
        prepared,
        after_a,
        symbol=slot.cell.symbol,
        arm_id="combined",
        origin="CONTEXT_PROPOSAL",
        outcome=outcome,
    )
    assert redelivered == after_a and plan_again == plan_a
    assert plan_b == plan_a and len(after_b.bindings) == 1


def test_native_quiet_outcome_is_original_and_review_defaults_are_explicit():
    p = profile()
    prepared = prepared_cut(p)
    slot = prepared.slots[0]
    assert slot.technical is not None and slot.technical.intent is None
    native = rp.CreationOutcome("NONE", digest(asdict(slot.technical)), slot.cell.observed_ms)
    after, plan = rp.materialize_hypothesis(
        p,
        prepared,
        rp.initial_materializations(p),
        symbol=slot.cell.symbol,
        arm_id="strategy_only",
        origin="TECHNICAL",
        outcome=native,
    )
    assert plan is None and len(after.bindings) == 1
    assert p.hypothesis_policy(arm_id="independent_proposals").require_review is True
    assert rp.profile_definition()["review_arms"] == ["combined", "context_review", "independent_proposals"]


def test_native_candidate_materialization_preserves_exact_parent(monkeypatch):
    p = profile()
    symbol = UNIVERSE[0]
    anchor = history(symbol, START)[-1]
    parent = SleeveIntent(
        "adaptive_pullback_range_v1",
        symbol,
        Side.LONG,
        START - 1,
        START,
        START + 15 * MINUTE,
        anchor.close,
        1.0,
        500.0,
        ExitPlan(98.0, 105.0, 5 * MINUTE),
    )
    native_evaluator = rp.evaluate_adaptive

    def evaluator(rows):
        decision = native_evaluator(rows)
        return replace(decision, status="INTENT", intent=parent) if rows[-1].symbol == symbol else decision

    monkeypatch.setattr(rp, "evaluate_adaptive", evaluator)
    prepared = prepared_cut(p)
    slot = next(item for item in prepared.slots if item.cell.symbol == symbol)
    assert slot.technical is not None and slot.technical.intent == parent
    outcome = rp.CreationOutcome("NATIVE", digest(asdict(slot.technical)), slot.cell.observed_ms)
    _, plan = rp.materialize_hypothesis(
        p,
        prepared,
        rp.initial_materializations(p),
        symbol=symbol,
        arm_id="strategy_only",
        origin="TECHNICAL",
        outcome=outcome,
    )
    assert plan is not None and plan.origin == "TECHNICAL"
    assert plan.template == parent and plan.origin_cut_ms == START


def test_entry_batch_is_permutation_invariant_and_rejects_wrong_batch():
    def candidate(symbol, cut, parent):
        metadata = (("hypothesis_origin_cut_ms", str(cut)), ("parent_intent_id", parent))
        return SleeveIntent(
            "adaptive_pullback_range_v1",
            symbol,
            Side.LONG,
            issue - 1,
            issue,
            START + 5 * MINUTE,
            100.0,
            1.0,
            500.0,
            ExitPlan(98.0, 105.0, 5 * MINUTE),
            metadata=metadata,
        )

    issue = START + MINUTE
    rows = tuple(candidate(symbol, START, f"parent-{symbol}") for symbol in UNIVERSE)
    ordered = rp.order_entry_batch(rows, actual_issue_ms=issue)
    assert ordered == rp.order_entry_batch(tuple(reversed(rows)), actual_issue_ms=issue)
    assert tuple(x.symbol for x in ordered) == tuple(sorted(UNIVERSE))
    with pytest.raises(ValueError, match="same actual-issue"):
        rp.order_entry_batch((replace(rows[0], entry_eligible_ts_ms=issue + 1),), actual_issue_ms=issue)
    with pytest.raises(ValueError, match="one candidate per symbol"):
        rp.order_entry_batch(
            (
                rows[0],
                replace(
                    rows[0],
                    metadata=(("hypothesis_origin_cut_ms", str(START)), ("parent_intent_id", "other")),
                ),
            ),
            actual_issue_ms=issue,
        )
