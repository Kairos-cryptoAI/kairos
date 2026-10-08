"""Standalone synthetic durable-native-book integration tests (offline only)."""

import hashlib
import json
from dataclasses import replace

import pytest
from kairos_core.contracts.simulation import RecordedBookLevelV1, RecordedTopNBookFrameV2
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay.book_bundle import (
    admit_retained_book_capture,
    audit_retained_journal_sources,
    open_book_bundle,
    prepare_book_bundle,
    retain_book_bundle,
)
from adaptive_replay.fill_feasibility import SimulatedFill, assess_journal_simulated_fill
from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_journal import HypothesisJournal, JournalArm, JournalSeal
from adaptive_replay.hypothesis_v2 import (
    HypothesisObservation,
    HypothesisPlan,
    HypothesisPolicy,
    evaluate_hypothesis,
)
from adaptive_replay.native_book_capture import MIGRATED_PROFILE, NativeBookCapture, NativeBookPolicy
from adaptive_replay.scenarios import MINUTE, ScenarioEvidence, ScenarioObservation

START = 86_400_000
SYMBOL = "BTCUSDT"


def _bar(open_ms, close=100.0):
    return Candle(SYMBOL, "1m", open_ms, open_ms + MINUTE - 1, 100, 101, 99, close, 10)


def _evidence(candle):
    return ScenarioEvidence(
        "bars",
        "MARKET",
        SYMBOL,
        digest(candle_payload(candle)),
        candle.close_time_ms,
        candle.close_time_ms + 1,
        candle.close_time_ms + 1,
        600_000,
    )


def _frame(side, event, sequence, previous=None, *, update_id=None):
    bid, ask = ("100.49", "100.50") if side is Side.LONG else ("99.50", "99.51")
    update_id = 10 * sequence + 1 if update_id is None else update_id
    body = {
        "e": "depthUpdate",
        "E": event,
        "T": event - 1,
        "s": SYMBOL,
        "U": update_id - 1,
        "u": update_id,
        "pu": 0 if sequence == 1 else update_id - 10,
        "b": [[bid, "2.0"]],
        "a": [[ask, "2.0"]],
        "st": 1,
        "ps": SYMBOL,
    }
    raw = json.dumps({"stream": "btcusdt@depth10@100ms", "data": body}, separators=(",", ":"))
    return RecordedTopNBookFrameV2(
        source="offline-native-fixture",
        tape_id="bundle-fixture",
        stream_epoch="epoch-one",
        symbol=SYMBOL,
        tape_sequence=sequence,
        exchange_update_id=update_id,
        exchange_at_ms=event,
        received_at_ms=event + 1,
        persisted_at_ms=event + 2,
        raw_payload=raw,
        raw_payload_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        previous_frame_sha256=previous,
        continuity="ADMITTED",
        source_reason="SYNTHETIC",
        bids=(RecordedBookLevelV1(price=float(bid), quantity=2.0),),
        asks=(RecordedBookLevelV1(price=float(ask), quantity=2.0),),
    )


def _setup(side, tmp_path, *, frame_count=2):
    sign = 1 if side is Side.LONG else -1
    anchor = _bar(START - MINUTE)
    parent = SleeveIntent(
        "trend_breakout_v1",
        SYMBOL,
        side,
        START - 1,
        START,
        START + MINUTE - 1,
        100,
        0.7,
        500,
        ExitPlan(100 - 2 * sign, 100 + 5 * sign, 5 * MINUTE, 100 + 3 * sign, 1),
        (("bundle_fixture", "unchanged"),),
    )
    book_policy = NativeBookPolicy(MIGRATED_PROFILE, "quotes", 5_000, "TEST_FIXTURE")
    policy = HypothesisPolicy(
        START - 1, 5 * MINUTE, book_policy.quote_source_id, 5_000, "TEST_FIXTURE", False
    )

    def make_plan(source_set):
        return HypothesisPlan(
            parent,
            "TECHNICAL",
            "BULL" if side is Side.LONG else "BEAR",
            START,
            source_set,
            "b" * 64,
            (_evidence(anchor),),
            anchor,
            (("MARKET", "bars"),),
            policy,
        )

    first = _bar(START)
    quiet = HypothesisObservation(
        ScenarioObservation(first, first.close_time_ms + 20, (_evidence(first),)), None
    )
    confirmation = _bar(START + MINUTE, 100.5 if side is Side.LONG else 99.5)
    issue_frame = _frame(side, confirmation.close_time_ms + 10, 1)
    issue = NativeBookCapture(issue_frame, book_policy)
    trigger = HypothesisObservation(
        ScenarioObservation(confirmation, confirmation.close_time_ms + 20, (_evidence(confirmation),)),
        issue.capture.quote,
    )
    evaluated = evaluate_hypothesis(make_plan("a" * 64), (quiet, trigger))[-1].candidate
    assert evaluated is not None
    frames = [issue_frame]
    if frame_count >= 2:
        frames.append(_frame(side, evaluated.entry_eligible_ts_ms + 1, 2, issue_frame.frame_sha256))
    bundle_path = tmp_path / "fixture.native-book.research.json"
    bundle_seal = prepare_book_bundle("bundle-fixture", tuple(frames), book_policy)
    retention = retain_book_bundle(bundle_path, bundle_seal, tuple(frames))
    plan = make_plan(bundle_seal.sha256)
    journal_path = tmp_path / "fixture.research.sqlite3"
    journal_seal = JournalSeal(
        "journal-fixture", START - 1, bundle_seal.sha256, (JournalArm("native", policy),), 4
    )
    journal = HypothesisJournal.create(journal_path, journal_seal)
    journal.register("native", plan)
    evaluated = evaluate_hypothesis(plan, (quiet, trigger))[-1].candidate
    assert evaluated is not None
    return (
        book_policy,
        plan,
        parent,
        quiet,
        trigger,
        issue_frame,
        evaluated,
        tuple(frames),
        bundle_path,
        bundle_seal,
        retention,
        journal_path,
        journal_seal,
        journal,
    )


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_retained_native_prefix_reopens_reconciles_journal_and_checks_supplied_fill(tmp_path, side):
    (
        policy,
        plan,
        parent,
        quiet,
        trigger,
        issue_frame,
        candidate,
        frames,
        book_path,
        book_seal,
        retention,
        journal_path,
        journal_seal,
        journal,
    ) = _setup(side, tmp_path)
    journal.append("native", parent.intent_id, quiet)
    journal.append("native", parent.intent_id, trigger)
    before_book, before_journal = book_path.read_bytes(), journal_path.read_bytes()
    reopened = open_book_bundle(book_path, book_seal, retention)
    assert tuple(item.frame.raw_payload for item in reopened.bindings) == tuple(f.raw_payload for f in frames)
    issue = admit_retained_book_capture(
        book_path,
        book_seal,
        retention,
        sequence=1,
        expected_binding_sha256=reopened.bindings[0].sha256,
        asof_ms=trigger.market.observed_ms,
        after_ms=trigger.market.candle.close_time_ms,
    )
    executable = admit_retained_book_capture(
        book_path,
        book_seal,
        retention,
        sequence=2,
        expected_binding_sha256=reopened.bindings[1].sha256,
        asof_ms=frames[1].persisted_at_ms,
        after_ms=frames[1].exchange_at_ms,
    )
    assert issue.binding.capture.quote == trigger.quote
    assert issue.binding.capture.raw_payload != issue.binding.frame.raw_payload.encode()
    assert issue.risk_authority == executable.risk_authority == retention.risk_authority == "NONE"
    snapshot = HypothesisJournal.open(journal_path, journal_seal).snapshot()
    audit = audit_retained_journal_sources(
        journal_path=journal_path,
        journal_seal=journal_seal,
        book_path=book_path,
        book_seal=book_seal,
        retention=retention,
        expected_journal_head_sha256=snapshot.head_sha256,
        expected_journal_event_count=snapshot.event_count,
    )
    assert len(audit.matches) == 1
    assert (audit.matches[0].sequence, audit.matches[0].binding_sha256) == (1, issue.binding.sha256)
    fill = SimulatedFill(
        "native",
        parent.intent_id,
        candidate.intent_id,
        SYMBOL,
        side,
        100.505 if side is Side.LONG else 99.495,
        1.0,
        executable.binding.frame.persisted_at_ms,
        plan.protection_sha256,
    )
    result = assess_journal_simulated_fill(
        journal_path=journal_path,
        seal=journal_seal,
        candidate=candidate,
        fill=fill,
        issue_capture=issue.binding.capture,
        execution_capture=executable.binding.capture,
    )
    assert (result.state, result.risk_authority) == ("SIMULATED_CHECK_ONLY", "NONE")
    assert (book_path.read_bytes(), journal_path.read_bytes()) == (before_book, before_journal)


def test_null_quote_stays_missing_and_later_retained_quote_does_not_resurrect_terminal_attempt(tmp_path):
    (
        policy,
        plan,
        parent,
        quiet,
        trigger,
        issue_frame,
        candidate,
        frames,
        book_path,
        book_seal,
        retention,
        journal_path,
        journal_seal,
        journal,
    ) = _setup(Side.LONG, tmp_path)
    missing = trigger.__class__(trigger.market, None)
    journal.append("native", parent.intent_id, quiet)
    terminal = journal.append("native", parent.intent_id, missing)
    assert terminal.evaluation.candidate is None
    later_bar = _bar(START + 2 * MINUTE, 101.0)
    later_quote = NativeBookCapture(frames[1], policy).capture.quote
    later = HypothesisObservation(
        ScenarioObservation(later_bar, later_bar.close_time_ms + 20, (_evidence(later_bar),)), later_quote
    )
    receipt = journal.append("native", parent.intent_id, later)
    assert receipt.evaluation.candidate is None
    snapshot = HypothesisJournal.open(journal_path, journal_seal).snapshot()
    assert snapshot.hypotheses[0].observations[1].quote is None
    assert snapshot.hypotheses[0].receipts[-1].evaluation.candidate is None
    with pytest.raises(ValueError, match="causal admission boundary|unavailable at the causal boundary"):
        audit_retained_journal_sources(
            journal_path=journal_path,
            journal_seal=journal_seal,
            book_path=book_path,
            book_seal=book_seal,
            retention=retention,
            expected_journal_head_sha256=HypothesisJournal.open(journal_path, journal_seal)
            .snapshot()
            .head_sha256,
            expected_journal_event_count=HypothesisJournal.open(journal_path, journal_seal)
            .snapshot()
            .event_count,
        )


def test_source_set_mismatch_and_unretained_quote_fail_closed(tmp_path):
    (
        policy,
        plan,
        parent,
        quiet,
        trigger,
        issue_frame,
        candidate,
        frames,
        book_path,
        book_seal,
        retention,
        journal_path,
        journal_seal,
        journal,
    ) = _setup(Side.LONG, tmp_path)
    wrong_seal = JournalSeal("wrong-source", START - 1, "c" * 64, (JournalArm("native", plan.policy),), 4)
    wrong_path = tmp_path / "wrong.research.sqlite3"
    HypothesisJournal.create(wrong_path, wrong_seal)
    with pytest.raises(ValueError, match="journal source set must freeze"):
        audit_retained_journal_sources(
            journal_path=wrong_path,
            journal_seal=wrong_seal,
            book_path=book_path,
            book_seal=book_seal,
            retention=retention,
            expected_journal_head_sha256=HypothesisJournal.open(wrong_path, wrong_seal)
            .snapshot()
            .head_sha256,
            expected_journal_event_count=0,
        )
    forged_quote = trigger.quote.__class__(**{**trigger.quote.__dict__, "bid": trigger.quote.bid - 0.01})
    journal.append("native", parent.intent_id, quiet)
    journal.append("native", parent.intent_id, trigger.__class__(trigger.market, forged_quote))
    with pytest.raises(ValueError, match="unique retained native original"):
        audit_retained_journal_sources(
            journal_path=journal_path,
            journal_seal=journal_seal,
            book_path=book_path,
            book_seal=book_seal,
            retention=retention,
            expected_journal_head_sha256=HypothesisJournal.open(journal_path, journal_seal)
            .snapshot()
            .head_sha256,
            expected_journal_event_count=HypothesisJournal.open(journal_path, journal_seal)
            .snapshot()
            .event_count,
        )


def test_ambiguous_equal_quotes_are_not_guessed_and_causal_lookup_is_exact(tmp_path):
    values = _setup(Side.LONG, tmp_path, frame_count=1)
    (
        policy,
        plan,
        parent,
        quiet,
        trigger,
        issue_frame,
        candidate,
        frames,
        book_path,
        book_seal,
        retention,
        journal_path,
        journal_seal,
        journal,
    ) = values
    # A distinct native update with the same BBO/clock yields the same generic quote.
    duplicate = _frame(Side.LONG, issue_frame.exchange_at_ms, 2, issue_frame.frame_sha256, update_id=22)
    # Use a new separately sealed bundle so the complete prefix contains both originals.
    path2 = tmp_path / "ambiguous.native-book.research.json"
    seal2 = prepare_book_bundle("ambiguous-fixture", (issue_frame, duplicate), policy)
    retention2 = retain_book_bundle(path2, seal2, (issue_frame, duplicate))
    plan2 = replace(plan, source_set_sha256=seal2.sha256)
    journal2_path = tmp_path / "ambiguous.research.sqlite3"
    journal2_seal = JournalSeal(
        "ambiguous-journal", START - 1, seal2.sha256, (JournalArm("native", plan2.policy),), 4
    )
    journal2 = HypothesisJournal.create(journal2_path, journal2_seal)
    journal2.register("native", plan2)
    journal2.append("native", parent.intent_id, quiet)
    journal2.append("native", parent.intent_id, trigger)
    with pytest.raises(ValueError, match="unique retained native original"):
        audit_retained_journal_sources(
            journal_path=journal2_path,
            journal_seal=journal2_seal,
            book_path=path2,
            book_seal=seal2,
            retention=retention2,
            expected_journal_head_sha256=HypothesisJournal.open(journal2_path, journal2_seal)
            .snapshot()
            .head_sha256,
            expected_journal_event_count=HypothesisJournal.open(journal2_path, journal2_seal)
            .snapshot()
            .event_count,
        )
    binding = NativeBookCapture(issue_frame, policy)
    for kwargs, message in [
        (
            {
                "sequence": 1,
                "expected_binding_sha256": "f" * 64,
                "asof_ms": trigger.market.observed_ms,
                "after_ms": trigger.market.candle.close_time_ms,
            },
            "explicitly expected binding",
        ),
        (
            {
                "sequence": 1,
                "expected_binding_sha256": binding.sha256,
                "asof_ms": issue_frame.persisted_at_ms - 1,
                "after_ms": trigger.market.candle.close_time_ms,
            },
            "causal boundary",
        ),
        (
            {
                "sequence": 1,
                "expected_binding_sha256": binding.sha256,
                "asof_ms": trigger.market.observed_ms,
                "after_ms": trigger.market.observed_ms + 1,
            },
            "causal admission boundary",
        ),
    ]:
        with pytest.raises(ValueError, match=message):
            admit_retained_book_capture(path2, seal2, retention2, **kwargs)


def test_retention_receipt_detects_post_retention_byte_tampering(tmp_path):
    (_, _, _, _, _, _, _, frames, path, seal, retention, *_) = _setup(Side.LONG, tmp_path)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="caller-pinned retention"):
        open_book_bundle(path, seal, retention)


def test_journal_rollback_cannot_match_independently_pinned_latest_head(tmp_path):
    (
        policy,
        plan,
        parent,
        quiet,
        trigger,
        _,
        _,
        _,
        book_path,
        book_seal,
        retention,
        journal_path,
        journal_seal,
        journal,
    ) = _setup(Side.LONG, tmp_path)
    journal.append("native", parent.intent_id, quiet)
    old_image = journal_path.read_bytes()
    old_snapshot = HypothesisJournal.open(journal_path, journal_seal).snapshot()
    journal.append("native", parent.intent_id, trigger)
    latest = HypothesisJournal.open(journal_path, journal_seal).snapshot()
    assert latest.event_count == old_snapshot.event_count + 1
    # Restore a previously valid older local image; the caller-pinned latest head/count
    # remain independent and must prevent this otherwise-consistent rollback.
    journal_path.write_bytes(old_image)
    with pytest.raises(ValueError, match="independently caller-pinned head/count"):
        audit_retained_journal_sources(
            journal_path=journal_path,
            journal_seal=journal_seal,
            book_path=book_path,
            book_seal=book_seal,
            retention=retention,
            expected_journal_head_sha256=latest.head_sha256,
            expected_journal_event_count=latest.event_count,
        )
