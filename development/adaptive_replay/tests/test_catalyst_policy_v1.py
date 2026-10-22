"""Bounded synthetic catalyst-policy contracts; not news or economic evidence."""

from dataclasses import replace

import pytest
from kairos_strategy.candles import Candle
from kairos_strategy.provenance import candle_payload

from adaptive_replay import catalyst_policy_v1 as cp
from adaptive_replay import research_profile_v1 as rp
from adaptive_replay.historical_context import HistoricalVersion, canonical, digest
from adaptive_replay.hypothesis_v3 import CreationAssessment
from adaptive_replay.inputs import UNIVERSE
from adaptive_replay.scenarios import MINUTE, ScenarioEvidence

START = 1_700_000_100_000
REQUIRED = (("MACRO", "macro-fixture"), ("MARKET", "market-fixture"), ("NEWS", "news-fixture"))


def session(**changes):
    values = dict(
        declared_ms=START - MINUTE,
        start_ms=START,
        end_ms=START + 60 * MINUTE,
        source_set_sha256="a" * 64,
        model_config_sha256="b" * 64,
        quote_source_id="quote-fixture",
        required_sources=REQUIRED,
        evidence_kind="TEST_FIXTURE",
    )
    values.update(changes)
    return rp.ResearchProfile(**values)


def history(symbol, cut):
    """Flat, stable absolute-time rolling history that produces a native RANGE."""
    first = cut - rp.HISTORY_BARS * MINUTE
    return tuple(
        Candle(symbol, "1m", t, t + MINUTE - 1, 100.0, 100.7, 99.3, 100.0, 10.0)
        for t in (first + i * MINUTE for i in range(rp.HISTORY_BARS))
    )


def price_cell(symbol, cut, *, observed=None, rows=None, budget="AVAILABLE", sources=None):
    observed = cut + 1_000 if observed is None else observed
    rows = history(symbol, cut) if rows is None else rows
    anchor = rows[-1]
    receipts = (
        tuple(
            ScenarioEvidence(
                source_id,
                kind,
                symbol,
                digest(candle_payload(anchor)),
                anchor.close_time_ms,
                anchor.close_time_ms,
                observed,
                10 * MINUTE,
            )
            for kind, source_id in REQUIRED
        )
        if sources is None
        else sources
    )
    return rp.PriceCell(cut, observed, symbol, rows, receipts, budget)


def historical_version(
    symbol,
    *,
    captured=START - 1,
    document="doc-news",
    content="Original notice",
    proof="TEST_FIXTURE",
    source_name="news-fixture",
):
    payload = canonical({"headline": content, "body": "Synthetic bounded fixture."})
    return HistoricalVersion(
        record_id="version-" + document,
        document_id=document,
        source_name=source_name,
        kind="NEWS",
        symbols=(symbol,),
        url="https://example.test/notice",
        payload_json=payload,
        raw_content_sha256=digest(payload),
        extraction_policy_sha256="c" * 64,
        published_lower_ms=captured - 4_000,
        published_upper_ms=captured - 3_000,
        version_available_ms=None if proof == "PUBLICATION_ONLY" else captured - 1_000,
        captured_ms=captured,
        proof_kind=proof,
        proof_sha256=None if proof == "PUBLICATION_ONLY" else "d" * 64,
    )


def catalyst(
    symbol, *, event_id="root-1", version=None, first_received=None, ttl=10 * MINUTE, source_id="news-fixture"
):
    version = historical_version(symbol) if version is None else version
    received = version.captured_ms if first_received is None else first_received
    return cp.CatalystEvent(source_id, event_id, version, received, ttl)


def catalyst_cell(symbol, cut, *, event=None, coverage="KNOWN", observed=None, budget="AVAILABLE", active=()):
    return cp.CatalystCell(
        price_cell(symbol, cut, observed=observed, budget=budget),
        coverage,
        () if event is None else (event,),
        tuple(sorted(active)),
    )


def full_cut(cut, *, events=None, **kwargs):
    events = {} if events is None else events
    return tuple(
        catalyst_cell(symbol, cut, event=events.get(symbol), **kwargs) for symbol in sorted(UNIVERSE)
    )


def policy():
    return cp.CatalystPolicy(session())


def prepare(p, *, event=None, symbol=None, **cell_kwargs):
    events = {} if event is None else {symbol or sorted(UNIVERSE)[0]: event}
    return cp.prepare_cut(p, cp.initial_state(p), full_cut(START, events=events, **cell_kwargs))


def event_slot(prepared, symbol=None):
    return next(s for s in prepared.slots if s.cell.price.symbol == (symbol or sorted(UNIVERSE)[0]))


def outcome(prepared, p, symbol=None, direction="LONG", *, status="DIRECTION", response="e" * 64):
    slot = event_slot(prepared, symbol)
    created = slot.cell.price.observed_ms + 5_000
    assessment = None
    if status == "DIRECTION":
        assessment = CreationAssessment(
            slot.creation_input_sha256,
            response,
            p.session.model_config_sha256,
            direction,
            created,
            created + 10,
            created + 20,
            p.session.evidence_kind,
        )
    return rp.CreationOutcome(status, response, created + 20, assessment)


def test_native_quiet_range_keeps_full_five_symbol_denominator_and_event_is_independent():
    p = policy()
    target = sorted(UNIVERSE)[0]
    prepared = prepare(p, event=catalyst(target), symbol=target)
    assert len(prepared.slots) == len(UNIVERSE)
    assert tuple(s.cell.price.symbol for s in prepared.slots) == tuple(sorted(UNIVERSE))
    slot = event_slot(prepared, target)
    assert slot.technical_state == "QUIET"
    assert slot.regime == "RANGE" and slot.defense == "NORMAL"
    assert slot.context_state == "ELIGIBLE" and slot.reason == "NEW_CANONICAL_EVENT_BATCH"
    assert slot.cell.price.rows[-1].close == 100.0


def test_all_slots_without_event_are_retained_no_call_not_missing():
    p = policy()
    prepared = prepare(p)
    assert len(prepared.slots) == 5
    assert all(s.context_state == "NO_CALL" and s.reason == "NO_NEW_EVENT" for s in prepared.slots)
    assert all(s.creation_input_sha256 is None for s in prepared.slots)


def test_only_event_due_at_this_original_cut_is_eligible():
    target = sorted(UNIVERSE)[0]
    late_capture = historical_version(target, captured=START + 1)
    event = catalyst(target, version=late_capture, first_received=START + 1)
    with pytest.raises(ValueError, match="future first eligible cut"):
        catalyst_cell(target, START, event=event)


def test_publication_only_version_cannot_become_a_catalyst_event():
    target = sorted(UNIVERSE)[0]
    with pytest.raises(ValueError, match="exact-version proof"):
        catalyst(target, version=historical_version(target, proof="PUBLICATION_ONLY"))


def test_event_source_kind_and_declared_source_binding_are_enforced():
    p = policy()
    target = sorted(UNIVERSE)[0]
    wrong_source = catalyst(
        target,
        source_id="unlisted-source",
        version=historical_version(target, source_name="unlisted-source"),
    )
    with pytest.raises(ValueError, match="source/proof outside declared source set"):
        prepare(p, event=wrong_source, symbol=target)


def test_event_scope_must_include_the_price_symbol():
    target = sorted(UNIVERSE)[0]
    other = sorted(UNIVERSE)[1]
    with pytest.raises(ValueError, match="event symbol conflict"):
        catalyst_cell(target, START, event=catalyst(other))


def test_unknown_coverage_consumes_slot_without_fabricating_known_no_event():
    p = policy()
    target = sorted(UNIVERSE)[0]
    prepared = prepare(p, event=catalyst(target), symbol=target, coverage="UNKNOWN")
    slot = event_slot(prepared, target)
    assert slot.reason == "EVENT_COVERAGE_UNKNOWN"
    assert slot.context_state == "NO_CALL" and slot.creation_input_sha256 is None
    assert len(prepared.checkpoint.stamps) == 1


def test_budget_unavailable_consumes_seen_event_and_does_not_create_candidate_input():
    p = policy()
    target = sorted(UNIVERSE)[0]
    prepared = prepare(p, event=catalyst(target), symbol=target, budget="BLOCKED")
    slot = event_slot(prepared, target)
    assert slot.reason == "BUDGET_UNAVAILABLE_EVENT_CONSUMED"
    assert slot.context_state == "NO_CALL" and slot.creation_input_sha256 is None
    assert len(prepared.checkpoint.stamps) == 1


def test_missed_observation_slot_is_not_backfilled():
    p = policy()
    target = sorted(UNIVERSE)[0]
    prepared = prepare(p, event=catalyst(target), symbol=target, observed=START + MINUTE)
    slot = event_slot(prepared, target)
    assert slot.reason == "LATE_SLOT_NO_CATCH_UP"
    assert slot.context_state == "NO_CALL"


def test_event_ttl_expiry_is_terminal_for_this_opportunity():
    p = policy()
    target = sorted(UNIVERSE)[0]
    event = catalyst(target, ttl=1)
    prepared = prepare(p, event=event, symbol=target)
    slot = event_slot(prepared, target)
    assert slot.reason == "MISSED_OR_STALE_EVENT_NO_CATCH_UP"
    assert slot.context_state == "NO_CALL"


def test_duplicate_event_id_and_new_capture_do_not_rearm_next_cut():
    p = policy()
    target = sorted(UNIVERSE)[0]
    original = catalyst(target)
    first = cp.prepare_cut(p, cp.initial_state(p), full_cut(START, events={target: original}))
    newer = historical_version(target, captured=START + rp.PERIOD_MS - 1)
    duplicate = catalyst(target, version=newer, first_received=newer.captured_ms)
    next_cut = START + rp.PERIOD_MS
    second = cp.prepare_cut(p, first.checkpoint, full_cut(next_cut, events={target: duplicate}))
    slot = event_slot(second, target)
    assert slot.reason == "NO_NEW_EVENT"
    assert slot.context_state == "NO_CALL"


def test_changed_document_revision_conflicts_and_blocks_symbol_stickily():
    p = policy()
    target = sorted(UNIVERSE)[0]
    original = catalyst(target)
    first = cp.prepare_cut(p, cp.initial_state(p), full_cut(START, events={target: original}))
    revision = catalyst(
        target,
        version=historical_version(target, captured=START + rp.PERIOD_MS - 1, content="Later correction"),
    )
    cut2 = START + rp.PERIOD_MS
    second = cp.prepare_cut(p, first.checkpoint, full_cut(cut2, events={target: revision}))
    assert target in second.checkpoint.blocked_symbols
    assert event_slot(second, target).reason == "INTEGRITY_OR_PRICE_GAP_BLOCKED_SESSION"
    third = cp.prepare_cut(p, second.checkpoint, full_cut(cut2 + rp.PERIOD_MS))
    assert target in third.checkpoint.blocked_symbols
    assert event_slot(third, target).reason == "INTEGRITY_OR_PRICE_GAP_BLOCKED_SESSION"


def test_same_content_alias_event_id_is_integrity_conflict_not_new_event():
    p = policy()
    target = sorted(UNIVERSE)[0]
    first = cp.prepare_cut(p, cp.initial_state(p), full_cut(START, events={target: catalyst(target)}))
    alias = catalyst(
        target,
        event_id="different-root-same-content",
        version=historical_version(target, captured=START + rp.PERIOD_MS - 1),
    )
    second = cp.prepare_cut(p, first.checkpoint, full_cut(START + rp.PERIOD_MS, events={target: alias}))
    assert target in second.checkpoint.blocked_symbols


def test_active_context_arm_is_excluded_without_blocking_another_arm():
    p = policy()
    target = sorted(UNIVERSE)[0]
    active_arm = "combined"
    prepared = prepare(p, event=catalyst(target), symbol=target, active=(active_arm,))
    slot = event_slot(prepared, target)
    assert active_arm not in slot.consumer_arms
    assert "independent_proposals" in slot.consumer_arms
    assert slot.context_state == "ELIGIBLE"


def test_active_all_context_arms_suppress_call_but_keep_event_receipt():
    p = policy()
    target = sorted(UNIVERSE)[0]
    prepared = prepare(p, event=catalyst(target), symbol=target, active=cp.CONTEXT_ARMS)
    slot = event_slot(prepared, target)
    assert slot.reason == "NO_CALL_ACTIVE_ALL_CONTEXT_ARMS"
    assert slot.context_state == "NO_CALL" and slot.creation_input_sha256 is None
    assert len(prepared.checkpoint.stamps) == 1


def test_event_identity_and_price_overlap_checkpoint_are_hash_bound():
    p = policy()
    prepared = prepare(p, event=catalyst(sorted(UNIVERSE)[0]), symbol=sorted(UNIVERSE)[0])
    with pytest.raises(ValueError, match="retained event state changed"):
        replace(prepared.checkpoint, last_cut_ms=prepared.checkpoint.last_cut_ms + rp.PERIOD_MS)
    with pytest.raises(ValueError, match="original full-universe preparation"):
        replace(prepared, slots=prepared.slots[:-1])


def test_canonical_same_cut_event_batch_order_is_required():
    symbol = sorted(UNIVERSE)[0]
    events = (
        catalyst(symbol),
        catalyst(
            symbol,
            event_id="root-2",
            version=historical_version(symbol, document="doc-news-2", content="Another notice"),
        ),
    )
    ordered = tuple(sorted(events, key=lambda e: e.sha256))
    with pytest.raises(ValueError, match="canonical event batch"):
        cp.CatalystCell(price_cell(symbol, START), "KNOWN", tuple(reversed(ordered)))


def test_creation_ledger_rejects_duplicate_origin_record():
    p = policy()
    prepared = prepare(p, event=catalyst(sorted(UNIVERSE)[0]), symbol=sorted(UNIVERSE)[0])
    ledger, plans = cp.materialize(
        p,
        prepared,
        cp.CreationLedger(p.sha256),
        symbol=sorted(UNIVERSE)[0],
        origin="CONTEXT_PROPOSAL",
        outcome=outcome(prepared, p),
    )
    assert len(ledger.records) == 1 and plans
    with pytest.raises(ValueError, match="duplicate original creation record"):
        replace(ledger, records=ledger.records + ledger.records)


def test_creation_consumption_is_original_and_exact_redelivery_is_idempotent():
    p = policy()
    target = sorted(UNIVERSE)[0]
    prepared = prepare(p, event=catalyst(target), symbol=target)
    original = outcome(prepared, p)
    ledger, plans = cp.materialize(
        p,
        prepared,
        cp.CreationLedger(p.sha256),
        symbol=target,
        origin="CONTEXT_PROPOSAL",
        outcome=original,
    )
    again, same_plans = cp.materialize(
        p,
        prepared,
        ledger,
        symbol=target,
        origin="CONTEXT_PROPOSAL",
        outcome=original,
    )
    assert again is ledger and same_plans == plans
    changed = outcome(prepared, p, response="f" * 64)
    with pytest.raises(ValueError, match="already consumed"):
        cp.materialize(p, prepared, ledger, symbol=target, origin="CONTEXT_PROPOSAL", outcome=changed)


@pytest.mark.parametrize("status", ["NONE", "FAILED", "UNKNOWN"])
def test_no_direction_or_failed_original_response_is_recorded_without_plan(status):
    p = policy()
    target = sorted(UNIVERSE)[0]
    prepared = prepare(p, event=catalyst(target), symbol=target)
    no_call = rp.CreationOutcome(status, "f" * 64, START + 10_000)
    ledger, plans = cp.materialize(
        p,
        prepared,
        cp.CreationLedger(p.sha256),
        symbol=target,
        origin="CONTEXT_PROPOSAL",
        outcome=no_call,
    )
    assert len(ledger.records) == 1 and plans == ()


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
def test_materialized_context_direction_is_independent_and_mapper_geometry_is_fixed(direction):
    p = policy()
    target = sorted(UNIVERSE)[0]
    prepared = prepare(p, event=catalyst(target), symbol=target)
    ledger, plans = cp.materialize(
        p,
        prepared,
        cp.CreationLedger(p.sha256),
        symbol=target,
        origin="CONTEXT_PROPOSAL",
        outcome=outcome(prepared, p, direction=direction),
    )
    assert len(ledger.records) == 1
    assert {arm for arm, _ in plans} == set(
        slot_arm for slot_arm in event_slot(prepared, target).consumer_arms
    )
    assert all(plan.template.side.value == direction for _, plan in plans)
    assert all(plan.template.sleeve_id == "context_atr_proposal_v1" for _, plan in plans)


def test_wrong_model_input_direction_or_creation_clock_cannot_be_materialized():
    p = policy()
    target = sorted(UNIVERSE)[0]
    prepared = prepare(p, event=catalyst(target), symbol=target)
    good = outcome(prepared, p)
    assessment = good.assessment
    with pytest.raises(ValueError, match="original proposal model/input/evidence/clock"):
        bad = replace(good, assessment=replace(assessment, input_sha256="f" * 64))
        cp.materialize(
            p,
            prepared,
            cp.CreationLedger(p.sha256),
            symbol=target,
            origin="CONTEXT_PROPOSAL",
            outcome=bad,
        )


def test_wrong_arm_and_substituted_prepared_receipt_are_rejected():
    p = policy()
    target = sorted(UNIVERSE)[0]
    prepared = prepare(p, event=catalyst(target), symbol=target)
    with pytest.raises(ValueError, match="original preparation, arm"):
        cp.resolve_arm(
            p,
            prepared,
            cp.CreationLedger(p.sha256),
            decisions=cp.DecisionLedger(p.sha256),
            symbol=target,
            arm_id="not-an-arm",
            issued_ms=START + 10_000,
            runs=(),
            shared_gate="PASS",
        )
    altered_slot = replace(event_slot(prepared, target), reason="NO_NEW_EVENT")
    altered_slots = tuple(altered_slot if s.cell.price.symbol == target else s for s in prepared.slots)
    with pytest.raises(ValueError, match="original full-universe preparation receipts"):
        replace(prepared, slots=altered_slots)


@pytest.mark.parametrize("gate", ["UNKNOWN", "BLOCKED"])
def test_shared_unknown_or_blocked_gate_fails_closed(gate):
    p = policy()
    target = sorted(UNIVERSE)[0]
    prepared = prepare(p, event=catalyst(target), symbol=target)
    _, decision = cp.resolve_arm(
        p,
        prepared,
        cp.CreationLedger(p.sha256),
        decisions=cp.DecisionLedger(p.sha256),
        symbol=target,
        arm_id="independent_proposals",
        issued_ms=START + 10_000,
        runs=(),
        shared_gate=gate,
    )
    assert decision.reason == "SHARED_GATE_BLOCKED_OR_UNKNOWN" and decision.candidate is None


def test_pass_gate_requires_fresh_current_context_and_never_falls_back_for_unknown_peer():
    p = policy()
    target = sorted(UNIVERSE)[0]
    prepared = prepare(p, event=catalyst(target), symbol=target)
    ledger, _ = cp.materialize(
        p,
        prepared,
        cp.CreationLedger(p.sha256),
        symbol=target,
        origin="CONTEXT_PROPOSAL",
        outcome=outcome(prepared, p),
    )
    _, missing_current = cp.resolve_arm(
        p,
        prepared,
        ledger,
        decisions=cp.DecisionLedger(p.sha256),
        symbol=target,
        arm_id="independent_proposals",
        issued_ms=START + 10_000,
        runs=(),
        shared_gate="PASS",
    )
    assert missing_current.reason == "CURRENT_ADMISSION_CONTEXT_MISSING"
    _, no_peer = cp.resolve_arm(
        p,
        prepared,
        ledger,
        decisions=cp.DecisionLedger(p.sha256),
        symbol=target,
        arm_id="independent_proposals",
        issued_ms=START + 10_000,
        runs=(),
        shared_gate="PASS",
        current_prepared=prepared,
    )
    assert no_peer.reason == "REQUIRED_PEER_UNAVAILABLE_NO_LATE_FALLBACK"
    assert no_peer.candidate is None


def test_current_context_cannot_be_backdated_or_stale_for_issue_clock():
    p = policy()
    target = sorted(UNIVERSE)[0]
    prepared = prepare(p, event=catalyst(target), symbol=target)
    later_issue = START + rp.PERIOD_MS + 10_000
    _, decision = cp.resolve_arm(
        p,
        prepared,
        cp.CreationLedger(p.sha256),
        decisions=cp.DecisionLedger(p.sha256),
        symbol=target,
        arm_id="independent_proposals",
        issued_ms=later_issue,
        runs=(),
        shared_gate="PASS",
        current_prepared=prepared,
    )
    assert decision.reason == "CURRENT_ADMISSION_CONTEXT_STALE_OR_CONFLICTING"
