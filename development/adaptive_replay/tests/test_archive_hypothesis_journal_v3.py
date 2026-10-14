"""Durable producer offline fixtures and actual subprocess crash gates."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path

import pytest

from adaptive_replay import archive_hypothesis_journal_v3 as module
from adaptive_replay.archive_batch_cursor_v3 import open_archive_batch_index_v3
from adaptive_replay.archive_hypothesis_journal_v3 import ArchiveHypothesisJournalV3
from adaptive_replay.archive_hypothesis_v3 import (
    ArchiveHypothesisObservationV3,
    ArchiveHypothesisProducerV3,
    ArchiveQuoteProofV3,
    ArchiveReviewV3,
)
from adaptive_replay.archive_market_clock_v3 import archive_quote_v3
from adaptive_replay.archive_portfolio_stream_v3 import (
    TIE_RULE,
    ArchivePortfolioBoundaryV3,
    ArchivePortfolioLimitsV3,
    ArchivePortfolioSealV3,
    ArchivePortfolioSourceV3,
    ArchivePortfolioStreamV3,
)
from adaptive_replay.inputs import UNIVERSE
from adaptive_replay.scenarios import MINUTE
from adaptive_replay.sim_state_journal import EventConflict, JournalFull, OptimisticConflict

from ._isolated_fixture import FIXTURE_BOOTSTRAP
from .test_archive_hypothesis_v3 import CUT, candle, completion, plan, source
from .test_archive_portfolio_financial_consumer_v3 import _source

OPENED = []


@pytest.fixture(autouse=True)
def close_all_journals():
    OPENED.clear()
    try:
        yield
    finally:
        for journal in reversed(OPENED):
            if journal._db is not None:
                journal.close()
        OPENED.clear()


def market(tmp_path, p):
    sources = []
    for symbol in sorted(UNIVERSE):
        rows = [(CUT + MINUTE + 11, "100.49", "100.50"), (CUT + 2 * MINUTE + 11, "100.49", "100.50")]
        if symbol == "ETHUSDT":
            rows.insert(1, (CUT + MINUTE + 19, "100.48", "100.51"))
        if symbol == "SOLUSDT":
            rows.insert(1, (CUT + MINUTE + 24, "100.48", "100.51"))
        original, _ = _source(
            tmp_path / symbol, symbol, "2024-01-08", rows, clock_policy=p.policy.quote_clock
        )
        sources.append(original)
    return ArchivePortfolioSealV3(
        tuple(sources),
        tuple(sorted(UNIVERSE)),
        ("2024-01-08",),
        (),
        TIE_RULE,
        ("FUNDING", "CANDLE", "DEADLINE", "CONTROL"),
        ArchivePortfolioLimitsV3(max_batch_rows=1, max_batch_bytes=200, prefetch_rows=1),
    )


def prefix_at(seal, now):
    reader = ArchivePortfolioStreamV3(seal, expected_seal_sha256=seal.sha256)
    while (operation := reader.prepare_next()) is not None:
        if operation.rows[0].quote.modeled_available_at_ms > now:
            break
        reader.acknowledge(operation)
    return reader.checkpoint()


def observation(p, seal, open_ms=CUT, *, confirming=True):
    bar = candle(open_ms, 100.5 if confirming else 100)
    quote_at = open_ms + MINUTE + 16
    input_cp = prefix_at(seal, quote_at)
    index = next(s.index for s in seal.sources if s.index.symbol == "BTCUSDT")
    vector = next(v.cursor for v in input_cp.source_vector if v.source_key.startswith("BTCUSDT:"))
    original = index.cursor(clock=p.policy.quote_clock).lookup_row(vector.next_row - 1)
    quote = archive_quote_v3(
        original, clock=p.policy.quote_clock, source_manifest_sha256=index.source_manifest_sha256
    )
    proof = ArchiveQuoteProofV3(
        p.policy.quote_source_id, original, quote, index.manifest_sha256, p.policy.quote_clock, input_cp
    )
    sources = tuple(
        sorted(
            (
                source(bar),
                *(source(bar, kind=k, source_id=s) for k, s in p.required_sources if k != "MARKET"),
            ),
            key=lambda e: (e.kind, e.source_id),
        )
    )
    obs = ArchiveHypothesisObservationV3(bar, quote_at, sources, proof)
    if p.policy.require_review:
        receipt = completion(obs.context_sha256)
        obs = replace(
            obs,
            decision_history_ms=receipt.available_at(obs.input_ready_history_ms, p.policy),
            review=ArchiveReviewV3(p.scenario_id, p.template.side, obs.context_sha256, receipt),
        )
    return obs, prefix_at(seal, obs.decision_history_ms)


def fixture(tmp_path, **bounds):
    p = plan(review=True)
    seal = market(tmp_path, p)
    journal = ArchiveHypothesisJournalV3.create(
        tmp_path / "producer.sqlite3",
        producer_id="archive-source",
        arm_id="context_review",
        plans=(p,),
        market_seal=seal,
        **bounds,
    )
    OPENED.append(journal)
    return journal, p, seal


def append(journal, p, obs, cp, event="observation"):
    return journal.append(
        event_id=event,
        parent_id=p.template.intent_id,
        observation=obs,
        decision_market_checkpoint=cp,
        expected_checkpoint=journal.checkpoint(),
    )


def reopen(journal, seal, cp):
    result = ArchiveHypothesisJournalV3.open(journal.path, market_seal=seal, expected_checkpoint=cp)
    OPENED.append(result)
    return result


def test_full_original_first_trigger_replay_differential_and_independent_restart(tmp_path):
    journal, p, seal = fixture(tmp_path)
    pure = ArchiveHypothesisProducerV3(p)
    first, cp = observation(p, seal, confirming=False)
    issued = append(journal, p, first, cp)
    assert issued.receipt == pure.append(first, expected_checkpoint=pure.checkpoint())
    retained = journal.checkpoint()
    journal = reopen(journal, seal, retained)
    trigger, cp = observation(p, seal, CUT + MINUTE)
    final = append(journal, p, trigger, cp, "trigger")
    assert final.receipt == pure.append(trigger, expected_checkpoint=pure.checkpoint())
    snapshot = journal.snapshot()
    assert snapshot[1][0][1] == pure.snapshot()
    assert journal.first_consumed(p.template.intent_id, expected_checkpoint=snapshot[0]) == final
    assert (
        trigger.quote.source_prefix != cp
        or trigger.quote.source_prefix.global_row_count == cp.global_row_count
    )
    assert (
        first.quote.source_prefix.global_row_count == 5
        and issued.decision_market_checkpoint.global_row_count == 6
    )
    assert snapshot[1][0][1].observations[0].quote.original.raw_csv_line == first.quote.original.raw_csv_line


def test_exact_duplicate_conflict_new_id_same_payload_does_not_create_head(tmp_path):
    journal, p, seal = fixture(tmp_path)
    obs, cp = observation(p, seal)
    issued = append(journal, p, obs, cp)
    retained = journal.checkpoint()
    assert append(journal, p, obs, cp) == issued and journal.checkpoint() == retained
    with pytest.raises(EventConflict):
        append(journal, p, replace(obs, review=None), cp)
    with pytest.raises(EventConflict):
        append(journal, p, obs, cp, "new-id")
    with pytest.raises(EventConflict):
        journal.prepare_append(
            event_id="new-id",
            parent_id=p.template.intent_id,
            observation=obs,
            decision_market_checkpoint=cp,
            expected_checkpoint=retained,
        )
    assert journal.checkpoint() == retained


def test_input_quote_prefix_not_substituted_for_later_decision_prefix_and_all_symbols_due(tmp_path):
    journal, p, seal = fixture(tmp_path)
    obs, cp = observation(p, seal)
    before = journal.checkpoint()
    with pytest.raises(ValueError, match="full roster"):
        append(journal, p, obs, obs.quote.source_prefix)
    assert journal.checkpoint() == before
    assert cp.global_row_count == 6 and obs.quote.source_prefix.global_row_count == 5
    issued = append(journal, p, obs, cp)
    assert issued.receipt.evaluation.candidate is not None
    assert issued.decision_market_checkpoint == cp
    assert dict(issued.receipt.evaluation.candidate.metadata)[
        "archive_source_prefix_sha256"
    ] == module.hypothesis.digest(obs.quote.source_prefix)


def test_same_clock_other_symbol_source_must_precede_decision(tmp_path):
    journal, p, seal = fixture(tmp_path)
    obs, _ = observation(p, seal)
    now = CUT + MINUTE + 24
    cp = prefix_at(seal, now - 1)
    # ETH E+5 is exactly now; BTC quote itself was already present.
    obs = replace(obs, decision_history_ms=now, review=None)
    with pytest.raises(ValueError, match="full roster"):
        append(journal, p, obs, cp)


@pytest.mark.parametrize("damage", ["quote", "prefix", "source", "projection", "history", "truncation"])
def test_source_and_durable_tamper_rejected_without_repair(tmp_path, damage):
    journal, p, seal = fixture(tmp_path)
    obs, cp = observation(p, seal)
    if damage == "quote":
        # Consistent raw fields, but not a member of the frozen original source.
        raw = obs.quote.original.raw_csv_line.replace(b"100.49", b"100.48")
        from adaptive_replay.bookticker_archive_stream_v3 import _parse_row

        original = _parse_row(raw, "BTCUSDT", "2024-01-08", 0)
        quote = archive_quote_v3(
            original,
            clock=p.policy.quote_clock,
            source_manifest_sha256=obs.quote.quote.source_manifest_sha256,
        )
        altered = replace(obs, quote=replace(obs.quote, original=original, quote=quote), review=None)
        with pytest.raises(ValueError, match="original quote"):
            append(journal, p, altered, cp)
        return
    if damage == "prefix":
        vector = tuple(
            replace(v, cursor=replace(v.cursor, prefix_sha256="f" * 64))
            if v.source_key.startswith("ETHUSDT:")
            else v
            for v in cp.source_vector
        )
        with pytest.raises(ValueError):
            append(journal, p, obs, replace(cp, source_vector=vector))
        return
    if damage == "source":
        segment = next(seal.sources[0].index.source_root.glob("*.csv"), None)
        if segment is None:
            segment = next(seal.sources[0].index.source_root.rglob("*.csv"))
        segment.write_bytes(segment.read_bytes() + b"\n")
        with pytest.raises(ValueError):
            append(journal, p, obs, cp)
        return
    append(journal, p, obs, cp)
    retained = journal.checkpoint()
    db = sqlite3.connect(journal.path)
    try:
        if damage == "projection":
            db.execute("UPDATE parents SET projection='{}'")
        elif damage == "history":
            db.execute("UPDATE events SET payload=replace(payload,'100.49','100.48')")
        else:
            db.execute("DELETE FROM events")
        db.commit()
    finally:
        db.close()
    with pytest.raises((ValueError, OptimisticConflict)):
        journal.snapshot()
    with pytest.raises((ValueError, OptimisticConflict)):
        reopen(journal, seal, retained)


def test_wrong_owner_head_and_another_writer_cannot_adopt_latest(tmp_path):
    journal, p, seal = fixture(tmp_path)
    old = journal.checkpoint()
    other = reopen(journal, seal, old)
    obs, cp = observation(p, seal)
    append(journal, p, obs, cp)
    with pytest.raises(OptimisticConflict):
        other.append(
            event_id="writer-two",
            parent_id=p.template.intent_id,
            observation=obs,
            decision_market_checkpoint=cp,
            expected_checkpoint=old,
        )
    with pytest.raises(OptimisticConflict):
        reopen(journal, seal, old)


@pytest.mark.parametrize("fault", ["exception", "silent_projection"])
def test_atomic_write_failure_rolls_back_observation_receipt_projection_and_head(
    tmp_path, monkeypatch, fault
):
    journal, p, seal = fixture(tmp_path)
    obs, cp = observation(p, seal)
    before = journal.checkpoint()

    def broken():
        if fault == "exception":
            raise RuntimeError("injected precommit fault")
        journal._db.execute("UPDATE parents SET projection='{}'")

    monkeypatch.setattr(journal, "_before_commit", broken)
    with pytest.raises((RuntimeError, ValueError)):
        append(journal, p, obs, cp)
    assert journal.checkpoint() == before
    assert journal.snapshot()[2] == ()
    assert reopen(journal, seal, before).checkpoint() == before


@pytest.mark.parametrize("bound", ["bytes", "rows"])
def test_caps_fail_closed_no_dropped_first_trigger_or_partial_commit(tmp_path, bound):
    journal, p, seal = fixture(
        tmp_path, **({"max_event_bytes": 100} if bound == "bytes" else {"max_events": 1})
    )
    first, cp = observation(p, seal, confirming=False)
    if bound == "rows":
        append(journal, p, first, cp)
        first, cp = observation(p, seal, CUT + MINUTE)
    before = journal.checkpoint()
    with pytest.raises(JournalFull):
        append(journal, p, first, cp, "over-cap")
    assert journal.checkpoint() == before


def test_strict_codec_preserves_raw_decimal_native_computed_id_and_rejects_poison():
    p = plan()
    assert module._load(module._document(p)) == p
    values = (Decimal("0E-8"), b"\x00\xff\n", p.template.side, p.template)
    assert module._load(module._document(values)) == values
    for raw in ('{"x":1,"x":2}', '{"$type":"Unknown","fields":{}}', '{"$decimal":"NaN"}', '{"x":NaN}'):
        with pytest.raises(ValueError):
            module._load(raw)
    encoded = module._document(p.template).replace(p.template.intent_id, "f" * 64)
    with pytest.raises(ValueError, match="computed"):
        module._load(encoded)


def test_exact_checkpoint_type_cannot_be_replaced_by_equality_poison(tmp_path):
    journal, p, seal = fixture(tmp_path)
    obs, market_cp = observation(p, seal)

    class EqualityPoison:
        def __eq__(self, other):
            return True

    before = journal.checkpoint()
    for method in (journal.prepare_append, journal.append):
        with pytest.raises(ValueError):
            method(
                event_id="poison",
                parent_id=p.template.intent_id,
                observation=obs,
                decision_market_checkpoint=market_cp,
                expected_checkpoint=EqualityPoison(),
            )
    with pytest.raises(ValueError):
        journal.first_consumed(p.template.intent_id, expected_checkpoint=EqualityPoison())
    assert journal.checkpoint() == before


def test_prepare_refuses_uncommittable_cap(tmp_path):
    journal, p, seal = fixture(tmp_path, max_events=1)
    obs, market_cp = observation(p, seal)
    append(journal, p, obs, market_cp, "one")
    before = journal.checkpoint()
    with pytest.raises(JournalFull):
        journal.prepare_append(
            event_id="two",
            parent_id=p.template.intent_id,
            observation=obs,
            decision_market_checkpoint=market_cp,
            expected_checkpoint=before,
        )
    assert journal.checkpoint() == before


@pytest.mark.parametrize("disposition", ["ALLOW", "VETO", "DEFER", "ERROR", "UNKNOWN_COST"])
def test_issued_prefix_requires_both_exact_heads_and_excludes_later_model_originals(tmp_path, disposition):
    journal, p, seal = fixture(tmp_path)
    obs, market_cp = observation(p, seal)
    if disposition in {"ERROR", "UNKNOWN_COST"}:
        attempt = replace(
            obs.review.completion.attempt,
            status="ERROR" if disposition == "ERROR" else "COMPLETE",
            cost_usd=None if disposition == "UNKNOWN_COST" else obs.review.completion.attempt.cost_usd,
        )
        completed = replace(
            obs.review.completion,
            attempt=attempt,
            decision=None if disposition == "ERROR" else "ALLOW",
            response_sha256=None if disposition == "ERROR" else obs.review.completion.response_sha256,
        )
    else:
        completed = replace(obs.review.completion, decision=disposition)
    obs = replace(obs, review=replace(obs.review, completion=completed))
    prepared = journal.prepare_append(
        event_id="first",
        parent_id=p.template.intent_id,
        observation=obs,
        decision_market_checkpoint=market_cp,
        expected_checkpoint=journal.checkpoint(),
    )
    issued = append(journal, p, obs, market_cp, "first")
    assert journal.checkpoint() == prepared.after
    future, future_cp = observation(p, seal, CUT + MINUTE)
    future_completion = replace(
        future.review.completion,
        attempt=replace(future.review.completion.attempt, attempt_id="later-model-should-not-leak"),
    )
    future = replace(future, review=replace(future.review, completion=future_completion))
    append(journal, p, future, future_cp, "later")
    final = journal.checkpoint()
    journal = reopen(journal, seal, final)
    bundle = journal.issued_prefix(
        p.template.intent_id,
        issued.journal_version,
        expected_store_checkpoint=final,
        expected_issued_checkpoint=prepared.after,
    )
    assert bundle.plan == p and bundle.observations == (obs,) and bundle.receipts == (issued.receipt,)
    assert bundle.issued_checkpoint == prepared.after and bundle.issued == issued
    assert (bundle.issued.receipt.evaluation.candidate is not None) == (disposition == "ALLOW")
    document = module._document(bundle)
    assert "later-model-should-not-leak" not in document
    assert module._load(document) == bundle
    assert journal.checkpoint() == final
    for store_cp, issued_cp in ((prepared.after, prepared.after), (final, final)):
        with pytest.raises(OptimisticConflict):
            journal.issued_prefix(
                p.template.intent_id,
                issued.journal_version,
                expected_store_checkpoint=store_cp,
                expected_issued_checkpoint=issued_cp,
            )
    with pytest.raises(ValueError, match="first-trigger"):
        journal.issued_prefix(
            p.template.intent_id,
            final.version,
            expected_store_checkpoint=final,
            expected_issued_checkpoint=final,
        )
    with pytest.raises(ValueError):
        replace(bundle, observations=(obs, future), receipts=(issued.receipt,))
    assert journal.checkpoint() == final


def test_issued_prefix_cannot_export_waiting_or_another_parent(tmp_path):
    journal, p, seal = fixture(tmp_path)
    obs, market_cp = observation(p, seal, confirming=False)
    issued = append(journal, p, obs, market_cp)
    cp = journal.checkpoint()
    for parent in (p.template.intent_id, "f" * 64):
        with pytest.raises(ValueError):
            journal.issued_prefix(
                parent,
                issued.journal_version,
                expected_store_checkpoint=cp,
                expected_issued_checkpoint=cp,
            )
    assert journal.checkpoint() == cp


def test_market_financial_seals_no_circular_identity_equal_vector_mapping(tmp_path):
    journal, p, seal = fixture(tmp_path)
    obs, market_cp = observation(p, seal)
    command = ArchivePortfolioBoundaryV3(
        boundary_id="entry",
        kind="CONTROL",
        at_ms=obs.decision_history_ms,
        source_sha256="a" * 64,
        payload=b"original-producer-proof",
    )
    financial_seal = replace(seal, boundaries=(command,))
    financial_reader = ArchivePortfolioStreamV3(financial_seal, expected_seal_sha256=financial_seal.sha256)
    while (op := financial_reader.prepare_next()) is not None:
        if op.at_ms > obs.decision_history_ms:
            break
        financial_reader.acknowledge(op)
    financial_cp = financial_reader.checkpoint()
    assert (
        financial_cp.seal_sha256 != market_cp.seal_sha256
        and financial_cp.prefix_sha256 != market_cp.prefix_sha256
    )
    module.verify_source_vector_mapping(
        market_checkpoint=market_cp,
        financial_checkpoint=financial_cp,
        market_seal=seal,
        financial_seal=financial_seal,
    )
    with pytest.raises(ValueError, match="market-only"):
        ArchiveHypothesisJournalV3.create(
            tmp_path / "circular.sqlite3",
            producer_id="bad",
            arm_id="combined",
            plans=(p,),
            market_seal=financial_seal,
        )
    assert not (tmp_path / "circular.sqlite3").exists()


def _seal_from_descriptor(document):
    sources = []
    for key, index_root, source_root, index_sha, source_sha, clock in document["sources"]:
        index = open_archive_batch_index_v3(
            index_root,
            source_root,
            expected_index_manifest_sha256=index_sha,
            expected_source_manifest_sha256=source_sha,
        )
        original = ArchivePortfolioSourceV3(source_key=key, index=index, clock=clock)
        assert original.source_key == key
        sources.append(original)
    return ArchivePortfolioSealV3(
        tuple(sources),
        document["symbols"],
        document["days"],
        (),
        TIE_RULE,
        ("FUNDING", "CANDLE", "DEADLINE", "CONTROL"),
        ArchivePortfolioLimitsV3(**document["limits"]),
        document["entry_days"],
    )


@pytest.mark.parametrize("phase", ["precommit", "postcommit"])
def test_actual_subprocess_crash_atomicity_and_independent_exact_pending_after_anchor(tmp_path, phase):
    journal, p, seal = fixture(tmp_path)
    obs, market_cp = observation(p, seal)
    before = journal.checkpoint()
    prepared = journal.prepare_append(
        event_id="crash-event",
        parent_id=p.template.intent_id,
        observation=obs,
        decision_market_checkpoint=market_cp,
        expected_checkpoint=before,
    )
    descriptor = module.market_descriptor(seal) | {"limits": asdict(seal.limits)}
    request = {
        "path": str(journal.path),
        "market": descriptor,
        "before": before,
        "parent": p.template.intent_id,
        "observation": obs,
        "market_checkpoint": market_cp,
        "phase": phase,
    }
    request_path = tmp_path / "retained-before-request.json"
    request_path.write_text(module._document(request), encoding="utf-8")
    script = FIXTURE_BOOTSTRAP + "\nload_isolated_fixture_module(sys.argv[1])._crash_child(sys.argv[2])\n"
    result = subprocess.run(
        [sys.executable, "-I", "-W", "error", "-c", script, str(Path(__file__)), str(request_path)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == (61 if phase == "precommit" else 62), result.stderr
    if phase == "precommit":
        assert reopen(journal, seal, before).checkpoint() == before
        assert journal.checkpoint() == before
    else:
        with pytest.raises(OptimisticConflict):
            reopen(journal, seal, before)
        recovered = reopen(journal, seal, prepared.after)
        assert (
            recovered.first_consumed(p.template.intent_id, expected_checkpoint=prepared.after)
            == prepared.issued
        )
        assert recovered.snapshot()[2] == (prepared.issued,)


def _crash_child(request_path):
    def offline(event, args):
        if event in {"socket.connect", "subprocess.Popen", "os.system"}:
            raise RuntimeError("crash fixture child forbids external execution/network")

    sys.addaudithook(offline)
    request = module._load(Path(request_path).read_text(encoding="utf-8"))
    seal = _seal_from_descriptor(request["market"])
    journal = ArchiveHypothesisJournalV3.open(
        request["path"], market_seal=seal, expected_checkpoint=request["before"]
    )
    if request["phase"] == "precommit":
        journal._before_commit = lambda: os._exit(61)
    else:
        journal._after_commit = lambda: os._exit(62)
    journal.append(
        event_id="crash-event",
        parent_id=request["parent"],
        observation=request["observation"],
        decision_market_checkpoint=request["market_checkpoint"],
        expected_checkpoint=request["before"],
    )
    raise RuntimeError("crash hook did not execute")
