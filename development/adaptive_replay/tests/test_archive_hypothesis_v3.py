"""Strict dual-clock fixtures only; no original model/source admission proof."""

from dataclasses import asdict, replace
from decimal import Decimal

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay import archive_hypothesis_v3 as module
from adaptive_replay.archive_batch_cursor_v3 import ArchiveCursorCheckpointV3
from adaptive_replay.archive_hypothesis_v3 import (
    ArchiveHypothesisObservationV3,
    ArchiveHypothesisPlanV3,
    ArchiveHypothesisPolicyV3,
    ArchiveHypothesisProducerV3,
    ArchiveModelCompletionV3,
    ArchiveQuoteProofV3,
    ArchiveReviewV3,
    ArchiveSourceEvidenceV3,
    evaluate_archive_hypothesis_v3,
)
from adaptive_replay.archive_market_clock_v3 import ArchiveMarketClockV3, archive_quote_v3
from adaptive_replay.archive_portfolio_stream_v3 import (
    ArchivePortfolioCheckpointV3,
    ArchivePortfolioSourceCheckpointV3,
)
from adaptive_replay.bookticker_archive_stream_v3 import _day_start_ms, _parse_row
from adaptive_replay.historical_context import digest as native_digest
from adaptive_replay.hypothesis_journal_v3 import JournalReceiptV3
from adaptive_replay.hypothesis_v3 import EntryQuote, evaluate_hypothesis
from adaptive_replay.scenarios import MINUTE
from adaptive_replay.system import AttemptReceipt

CUT = _day_start_ms("2024-01-08") + MINUTE
WALL = _day_start_ms("2026-10-09")
SYMBOL = "BTCUSDT"


def candle(open_ms, close=100, low=99, high=101):
    return Candle(
        SYMBOL, "1m", open_ms, open_ms + MINUTE - 1, 100, max(high, close), min(low, close), close, 10
    )


def source(bar, *, kind="MARKET", source_id="bars", available=True):
    return ArchiveSourceEvidenceV3(
        source_id,
        kind,
        SYMBOL,
        native_digest(candle_payload(bar))
        if kind == "MARKET" and available
        else "d" * 64
        if available
        else None,
        "e" * 64,
        bar.close_time_ms,
        bar.close_time_ms + 10 if available else None,
        600000,
        "AVAILABLE" if available else "UNAVAILABLE",
        "f" * 64,
    )


def policy(review=False):
    return ArchiveHypothesisPolicyV3(
        WALL - 1,
        WALL,
        5 * MINUTE,
        5000,
        "archive-quotes",
        ArchiveMarketClockV3("EVENT_E", 3, 2),
        2,
        3,
        "TEST_FIXTURE",
        review,
    )


def completion(
    input_sha, *, role="REVIEW", decision="ALLOW", status="COMPLETE", cost=0.01, request=WALL + 100, elapsed=7
):
    attempt = AttemptReceipt(
        f"original-attempt:{input_sha[:16]}",
        request,
        request + elapsed,
        cost,
        status,
        "TEST_FIXTURE",
        input_sha,
    )
    return ArchiveModelCompletionV3(
        attempt,
        request + 1,
        request + elapsed - 1,
        request + elapsed,
        "a" * 64,
        input_sha,
        "b" * 64 if status == "COMPLETE" else None,
        "c" * 64,
        role,
        decision if status == "COMPLETE" else None,
    )


def plan(side=Side.LONG, *, review=False, origin="TECHNICAL", unavailable=None, model_status="COMPLETE"):
    sign = 1 if side is Side.LONG else -1
    anchor = candle(CUT - MINUTE)
    parent = SleeveIntent(
        "trend_breakout_v1",
        SYMBOL,
        side,
        CUT - 1,
        CUT,
        CUT + MINUTE - 1,
        100,
        0.7,
        500,
        ExitPlan(100 - 2 * sign, 100 + 5 * sign, 5 * MINUTE, 100 + 3 * sign, 1),
        (("native_marker", "unchanged"),),
    )
    sources = (source(anchor),)
    if origin == "CONTEXT_PROPOSAL":
        sources += tuple(
            source(anchor, kind=kind, source_id=kind.lower(), available=unavailable != kind)
            for kind in ("NEWS", "MACRO")
        )
    sources = tuple(sorted(sources, key=lambda e: (e.kind, e.source_id)))
    proof = None
    if origin == "CONTEXT_PROPOSAL":
        input_sha = module._creation_input(parent, anchor, sources, "a" * 64, "b" * 64)
        proof = completion(input_sha, role="PROPOSAL", decision=side.value, status=model_status)
    return ArchiveHypothesisPlanV3(
        parent,
        origin,
        "BULL" if side is Side.LONG else "BEAR",
        CUT,
        "a" * 64,
        "b" * 64,
        anchor,
        sources,
        tuple((s.kind, s.source_id) for s in sources),
        policy(review),
        proof,
    )


def quote_proof(p, open_ms=CUT, *, bid=None, ask=None, row_index=0):
    if bid is None:
        bid = "100.49" if p.template.side is Side.LONG else "99.50"
    if ask is None:
        ask = "100.50" if p.template.side is Side.LONG else "99.51"
    event = open_ms + MINUTE + 11
    raw = f"7,{bid},2,{ask},3,{event - 1},{event}\n".encode()
    row = _parse_row(raw, SYMBOL, "2024-01-08", row_index)
    quote = archive_quote_v3(row, clock=p.policy.quote_clock, source_manifest_sha256="a" * 64)
    cursor = ArchiveCursorCheckpointV3(
        "b" * 64, "a" * 64, p.policy.quote_clock.sha256, row_index + 1, "c" * 64
    )
    prefix = ArchivePortfolioCheckpointV3(
        "d" * 64,
        (ArchivePortfolioSourceCheckpointV3(f"{SYMBOL}:2024-01-08", cursor),),
        row_index + 1,
        0,
        1,
        quote.modeled_available_at_ms,
        "e" * 64,
    )
    return ArchiveQuoteProofV3("archive-quotes", row, quote, "b" * 64, p.policy.quote_clock, prefix)


def observation(
    p,
    open_ms=CUT,
    *,
    confirming=True,
    disposition="ALLOW",
    error=False,
    cost=0.01,
    missing_quote=False,
    sources=None,
    elapsed=7,
):
    close = 100.5 if p.template.side is Side.LONG else 99.5
    bar = candle(open_ms, close if confirming else 100)
    if sources is None:
        sources = tuple(
            sorted(
                (
                    source(bar),
                    *(source(bar, kind=k, source_id=s) for k, s in p.required_sources if k != "MARKET"),
                ),
                key=lambda e: (e.kind, e.source_id),
            )
        )
    quote = None if missing_quote else quote_proof(p, open_ms)
    result = ArchiveHypothesisObservationV3(bar, open_ms + MINUTE + 16, sources, quote)
    if p.policy.require_review:
        proof = completion(
            result.context_sha256,
            decision=disposition,
            status="ERROR" if error else "COMPLETE",
            cost=cost,
            elapsed=elapsed,
        )
        review = ArchiveReviewV3(p.scenario_id, p.template.side, result.context_sha256, proof)
        result = replace(
            result,
            decision_history_ms=proof.available_at(result.input_ready_history_ms, p.policy),
            review=review,
        )
    return result


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
@pytest.mark.parametrize("origin", ["TECHNICAL", "CONTEXT_PROPOSAL"])
@pytest.mark.parametrize("review", [False, True])
def test_both_origins_routes_preserve_original_parent_protection_and_two_clock_domains(side, origin, review):
    p = plan(side, origin=origin, review=review)
    before = asdict(p.template)
    obs = observation(p)
    result = evaluate_archive_hypothesis_v3(p, (obs,))[-1]
    assert result.state == "CONSUMED" and result.candidate is not None
    assert result.candidate.exit_plan is p.template.exit_plan
    assert asdict(p.template) == before
    assert result.candidate.decision_ts_ms == result.candidate.entry_eligible_ts_ms == obs.decision_history_ms
    assert Decimal(str(result.candidate.reference_price)) == (
        obs.quote.quote.ask_price if side is Side.LONG else obs.quote.quote.bid_price
    )
    assert p.policy.sealed_wall_ms > p.origin_cut_history_ms
    assert p.valid_until_history_ms == CUT + 5 * MINUTE - 1
    assert obs.quote.quote.historical_received_at_ms is None
    assert obs.quote.quote.historical_persisted_at_ms is None
    assert type(obs.quote) is not EntryQuote
    if origin == "CONTEXT_PROPOSAL":
        assert p.proposal.attempt.requested_ms >= WALL
        assert p.created_history_ms == p.input_ready_history_ms + 2 + 7 + 3
    assert dict(result.candidate.metadata)["evidence_kind"] == "ARCHIVE_MODELED_REFERENCE"
    with pytest.raises(ValueError):
        evaluate_hypothesis(p, ())


@pytest.mark.parametrize("disposition", ["ALLOW", "VETO", "DEFER"])
def test_first_trigger_review_consumes_once_without_later_fallback(disposition):
    p = plan(review=True)
    first = observation(p, disposition=disposition)
    later = observation(p, CUT + MINUTE)
    result = evaluate_archive_hypothesis_v3(p, (first, later))
    assert result[-2].state == "CONSUMED"
    assert (result[-2].candidate is not None) == (disposition == "ALLOW")
    assert result[-1].reason == "TERMINAL_NO_RESURRECTION" and result[-1].candidate is None


@pytest.mark.parametrize("kind", ["NEWS", "MACRO"])
def test_creation_missing_context_is_explicit_unavailable_never_quiet(kind):
    p = plan(origin="CONTEXT_PROPOSAL", unavailable=kind)
    result = evaluate_archive_hypothesis_v3(p, (observation(p),))
    assert result[0].state == "BLOCKED" and result[0].coverage == "UNAVAILABLE"
    assert all(r.candidate is None and r.state != "QUIET" for r in result)


@pytest.mark.parametrize(
    "mode", ["creation_error", "review_error", "unknown_expense", "missing_review", "missing_quote"]
)
def test_model_error_missing_and_unknown_expense_remain_unavailable(mode):
    p = plan(
        origin="CONTEXT_PROPOSAL" if mode == "creation_error" else "TECHNICAL",
        review=True,
        model_status="ERROR" if mode == "creation_error" else "COMPLETE",
    )
    obs = observation(
        p,
        error=mode == "review_error",
        cost=None if mode == "unknown_expense" else 0.01,
        missing_quote=mode == "missing_quote",
    )
    if mode == "missing_review":
        obs = replace(obs, review=None)
    result = evaluate_archive_hypothesis_v3(p, (obs,))[-1]
    assert result.coverage == "UNAVAILABLE" and result.candidate is None


def test_wall_elapsed_includes_capture_and_declared_delays_without_historical_actual_fields():
    p = plan(review=True)
    obs = observation(p, elapsed=25)
    proof = obs.review.completion
    assert obs.decision_history_ms == obs.input_ready_history_ms + 2 + 25 + 3
    assert proof.response_wall_ms < proof.completed_wall_ms < proof.captured_wall_ms
    assert proof.captured_wall_ms == proof.attempt.observed_ms >= WALL
    assert evaluate_archive_hypothesis_v3(p, (obs,))[-1].candidate is not None
    with pytest.raises(ValueError):
        replace(p.policy, replay_started_wall_ms=WALL - 2)
    with pytest.raises(ValueError):
        replace(proof, response_wall_ms=proof.completed_wall_ms + 1)
    with pytest.raises(ValueError):
        replace(proof, captured_wall_ms=proof.captured_wall_ms + 1)
    with pytest.raises(ValueError):
        replace(proof, attempt=replace(proof.attempt, requested_ms=WALL - 1)).available_at(
            obs.input_ready_history_ms, p.policy
        )
    with pytest.raises(ValueError):
        replace(p.policy, quote_clock=ArchiveMarketClockV3("TRANSACTION_T", 3, 2))


def test_original_cut_ttl_late_model_no_renewal_and_full_first_minute_required():
    p = plan(origin="CONTEXT_PROPOSAL")
    with pytest.raises(ValueError, match="renew TTL"):
        replace(
            p,
            proposal=replace(
                p.proposal,
                attempt=replace(p.proposal.attempt, observed_ms=WALL + 100 + MINUTE),
                completed_wall_ms=WALL + 100 + MINUTE - 1,
                captured_wall_ms=WALL + 100 + MINUTE,
            ),
        )
    expired = replace(p, policy=replace(p.policy, hypothesis_lifetime_ms=MINUTE + 5))
    assert evaluate_archive_hypothesis_v3(expired, (observation(expired),))[-1].state == "EXPIRED"
    skipped = evaluate_archive_hypothesis_v3(p, (observation(p, CUT + MINUTE),))[-1]
    assert skipped.state == "BLOCKED" and skipped.coverage == "UNAVAILABLE"


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_frozen_stop_wins_same_bar_confirmation(side):
    p = plan(side)
    obs = observation(p)
    bar = replace(obs.candle, low=98 if side is Side.LONG else 99, high=102)
    obs = replace(obs, candle=bar, sources=(source(bar),))
    assert evaluate_archive_hypothesis_v3(p, (obs,))[-1].state == "INVALIDATED"


@pytest.mark.parametrize("poison", ["review", "context", "quote"])
def test_pretrigger_poison_does_not_change_later_first_trigger_candidate(poison):
    p = plan(review=True)
    first = observation(p, confirming=False)
    changed = first
    if poison == "review":
        changed = observation(p, confirming=False, disposition="VETO")
    elif poison == "context":
        changed = replace(
            first,
            sources=(*first.sources, source(first.candle, kind="NEWS", source_id="unused", available=False)),
        )
    else:
        changed = replace(first, quote=None)
    trigger = observation(p, CUT + MINUTE)
    a = evaluate_archive_hypothesis_v3(p, (first, trigger))
    b = evaluate_archive_hypothesis_v3(p, (changed, trigger))
    assert a[-2].state == b[-2].state == "WAITING_TRIGGER"
    assert a[-1].candidate == b[-1].candidate


@pytest.mark.parametrize("change", ["decimal", "raw", "clock", "index", "prefix", "future", "stale"])
def test_exact_quote_raw_decimal_source_prefix_and_clock_guards(change):
    p = plan()
    obs = observation(p)
    proof = obs.quote
    if change == "decimal":
        with pytest.raises(ValueError):
            replace(proof, quote=replace(proof.quote, bid_price=proof.quote.bid_price + Decimal("0.01")))
    elif change == "raw":
        with pytest.raises(ValueError):
            replace(
                proof,
                original=replace(
                    proof.original, raw_csv_line=proof.original.raw_csv_line.replace(b"100.49", b"100.48")
                ),
            )
    elif change == "clock":
        with pytest.raises(ValueError):
            replace(proof, clock=ArchiveMarketClockV3("EVENT_E", 4, 2))
    elif change == "index":
        with pytest.raises(ValueError):
            replace(proof, index_manifest_sha256="f" * 64)
    elif change == "prefix":
        cursor = replace(proof.source_prefix.source_vector[0].cursor, next_row=0)
        prefix = replace(
            proof.source_prefix,
            source_vector=(replace(proof.source_prefix.source_vector[0], cursor=cursor),),
            global_row_count=0,
        )
        with pytest.raises(ValueError):
            replace(proof, source_prefix=prefix)
    elif change == "future":
        result = evaluate_archive_hypothesis_v3(
            p, (replace(obs, decision_history_ms=obs.decision_history_ms - 1),)
        )[-1]
        assert result.candidate is None and result.coverage == "UNAVAILABLE"
    else:
        result = evaluate_archive_hypothesis_v3(
            p, (replace(obs, decision_history_ms=obs.decision_history_ms + 5001),)
        )[-1]
        assert result.candidate is None and result.coverage == "UNAVAILABLE"


def test_quote_more_precise_than_native_planning_cannot_round_to_executable_candidate():
    p = plan()
    obs = observation(p)
    proof = quote_proof(p, bid="100.499999999999999999", ask="100.500000000000000001")
    result = evaluate_archive_hypothesis_v3(p, (replace(obs, quote=proof),))[-1]
    assert result.candidate is None and result.reason == "NATIVE_PLANNING_PRICE_NOT_EXACTLY_REPRESENTABLE"
    assert proof.quote.ask_price == Decimal("100.500000000000000001")


def test_pure_producer_restore_exact_redelivery_first_receipt_and_no_latest_adoption():
    p = plan(review=True)
    producer = ArchiveHypothesisProducerV3(p)
    first = observation(p, confirming=False)
    receipt = producer.append(first, expected_checkpoint=producer.checkpoint())
    before = producer.checkpoint()
    assert producer.append(first, expected_checkpoint=before) is receipt
    assert producer.checkpoint() == before and type(receipt) is not JournalReceiptV3
    snapshot = producer.snapshot()
    restored = ArchiveHypothesisProducerV3.restore(snapshot, expected_checkpoint=before)
    trigger = observation(p, CUT + MINUTE)
    original = producer.append(trigger, expected_checkpoint=before)
    assert restored.append(trigger, expected_checkpoint=before) == original
    with pytest.raises(ValueError):
        ArchiveHypothesisProducerV3.restore(producer.snapshot(), expected_checkpoint=before)
    with pytest.raises(ValueError):
        restored.append(first, expected_checkpoint=before)
    with pytest.raises(ValueError, match="conflicting"):
        producer.append(replace(first, quote=None), expected_checkpoint=producer.checkpoint())
    damaged = replace(snapshot, receipts=(replace(receipt, head_sha256="f" * 64),))
    with pytest.raises(ValueError, match="tampered"):
        ArchiveHypothesisProducerV3.restore(damaged, expected_checkpoint=before)


def test_producer_failed_append_source_drift_and_caps_preserve_checkpoint(monkeypatch):
    p = plan()
    producer = ArchiveHypothesisProducerV3(p)
    before = producer.checkpoint()
    obs = observation(p)
    monkeypatch.setattr(module, "MAX_DOCUMENT_BYTES", 10)
    with pytest.raises(ValueError, match="bounded"):
        producer.append(obs, expected_checkpoint=before)
    assert producer.checkpoint() == before
    monkeypatch.undo()
    monkeypatch.setattr(module, "_implementation", lambda: "f" * 64)
    with pytest.raises(ValueError, match="source/parent"):
        producer.append(obs, expected_checkpoint=before)
    assert producer.checkpoint() == before


def test_unchecked_nested_mutation_original_geometry_and_wrong_review_identity_fail_closed():
    p = plan(review=True)
    obs = observation(p)
    wrong = replace(obs, review=replace(obs.review, scenario_id="f" * 64))
    assert evaluate_archive_hypothesis_v3(p, (wrong,))[-1].coverage == "UNAVAILABLE"
    object.__setattr__(p.policy.quote_clock, "feed_delay_ms", True)
    with pytest.raises(ValueError):
        evaluate_archive_hypothesis_v3(p, (obs,))
    with pytest.raises(ValueError):
        replace(plan(), regime="CRASH")
    with pytest.raises(ValueError):
        replace(plan(), origin_cut_history_ms=CUT + 1)


def test_nested_clock_cached_sha_and_decimal_context_cannot_be_poisoned(monkeypatch):
    p = plan()
    obs = observation(p)
    object.__setattr__(p.policy.quote_clock, "_sha256", "f" * 64)
    with pytest.raises(ValueError, match="computed-field"):
        evaluate_archive_hypothesis_v3(p, (obs,))
    p = plan()
    monkeypatch.setattr(module, "ARITHMETIC", module.Context(prec=12))
    with pytest.raises(ValueError, match="Decimal96"):
        evaluate_archive_hypothesis_v3(p, (observation(p),))


def test_attempt_id_reuse_with_changed_model_input_or_expense_rejects_prefix():
    p = plan(review=True)
    first, trigger = observation(p, confirming=False), observation(p, CUT + MINUTE)
    proof = replace(
        trigger.review.completion,
        attempt=replace(
            trigger.review.completion.attempt, attempt_id=first.review.completion.attempt.attempt_id
        ),
    )
    trigger = replace(trigger, review=replace(trigger.review, completion=proof))
    with pytest.raises(ValueError, match="attempt ID reused"):
        evaluate_archive_hypothesis_v3(p, (first, trigger))


def test_original_wall_model_proof_provider_and_production_evidence_domain_explicit():
    p = plan(review=True)
    obs = observation(p)
    with pytest.raises(ValueError):
        replace(obs.review.completion, provider="UNSEALED_PROVIDER")
    policy = replace(p.policy, evidence_kind="RETAINED_WALL_MODEL_OUTPUT")
    with pytest.raises(ValueError, match="evidence domain"):
        obs.review.completion.available_at(obs.input_ready_history_ms, policy)
    proof = replace(
        obs.review.completion,
        attempt=replace(obs.review.completion.attempt, evidence_kind="OBSERVED_POINT_IN_TIME"),
    )
    assert proof.available_at(obs.input_ready_history_ms, policy) == obs.decision_history_ms
