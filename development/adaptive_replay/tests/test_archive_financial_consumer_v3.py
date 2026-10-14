from dataclasses import asdict, replace
from decimal import Context, localcontext
from decimal import Decimal as D

import pytest

from adaptive_replay import adaptive_sim_account as api
from adaptive_replay import archive_financial_consumer_v3 as module
from adaptive_replay.account_event_context_v3 import canonical_native_event
from adaptive_replay.archive_financial_consumer_v3 import (
    ArchiveFinancialBatchConsumerV3,
    ArchiveFundingCalendarV3,
    ArchiveFundingReceiptV3,
)
from adaptive_replay.sim_account_core_codec_v3 import decode_account_core, encode_account_core
from adaptive_replay.sim_financial_journal_v3 import DEFAULT_LIMITS
from adaptive_replay.sim_state_journal import EventConflict, JournalError, JournalFull, OptimisticConflict

from .test_archive_batch_cursor_v3 import CLOCK, ROWS, _index

START = 1704672000000
POLICY = api.AccountPolicy(D("0.1"), D("5"), D("5"), D("2"), 10000, "ENTRY_STOP_RESERVED")


def _funding(known=False, unresolved=False):
    if not known:
        return ArchiveFundingCalendarV3("UNRESOLVED" if unresolved else "TEST_FIXTURE", "b" * 64, 0, (), ())
    due = START + 15
    return ArchiveFundingCalendarV3(
        "TEST_FIXTURE",
        "b" * 64,
        1,
        (due,),
        (
            ArchiveFundingReceiptV3(due, None, START + 16, "UNAVAILABLE", None, None, None, "c" * 64),
            ArchiveFundingReceiptV3(
                due, due + 1, START + 18, "KNOWN", D("0.0002"), D("100.050"), "e" * 64, "d" * 64
            ),
        ),
    )


def _initial(position=False):
    account = api.new_account(D("10000"), POLICY)
    if position:
        account = replace(
            account,
            marks=(("BTCUSDT", D("100.1"), START),),
            positions=(
                api.Position(
                    "fixture-i",
                    "BTCUSDT",
                    "LONG",
                    D("99"),
                    D("1"),
                    D("100.1"),
                    D("0.05005"),
                    opened_at_ms=START - 1,
                ),
            ),
        )
    return account


def _create(tmp_path, *, initial=None, funding=None, batch_rows=2, **storage):
    index = _index(tmp_path, max_block_bytes=200)
    return ArchiveFinancialBatchConsumerV3.create(
        tmp_path / "financial.sqlite3",
        campaign_id="archive-research",
        owner_id="owner",
        account_id="account",
        index=index,
        clock=CLOCK,
        funding=funding or _funding(),
        initial_account=initial or _initial(),
        batch_rows=batch_rows,
        storage_bounds={**DEFAULT_LIMITS, **storage},
    )


def _core(consumer):
    return decode_account_core(consumer.journal.snapshot().state["account"])[0]


def _reopen(consumer, checkpoint):
    return ArchiveFinancialBatchConsumerV3.open(
        consumer.journal.path,
        identity=consumer.journal.identity,
        expected_checkpoint=checkpoint,
        index=consumer.index,
        clock=consumer.clock,
        funding=consumer.funding,
        config=consumer.config,
    )


def test_every_raw_row_native_mark_account_funding_risk_and_restart_differential(tmp_path):
    initial = _initial(position=True)
    consumer = _create(tmp_path, initial=initial, funding=_funding(known=True))
    direct = initial
    all_rows = []
    expected_funding_applied = False
    while True:
        prepared = consumer.prepare_next()
        if prepared is None:
            break
        assert consumer.journal.checkpoint() == prepared.before_financial
        assert consumer.journal.snapshot().state["archive_cursor"] == asdict(prepared.batch.before)
        assert prepared.payload["clock_evidence"] == "MODELED_REFERENCE"
        with localcontext(Context(prec=96)):
            for row, quote in zip(prepared.batch.rows, prepared.batch.quotes, strict=True):
                if quote.modeled_available_at_ms >= START + 18 and not expected_funding_applied:
                    direct = api.record_funding(
                        direct,
                        intent_id="fixture-i",
                        event_id=f"archive-funding:{START + 15}:{module._hash('fixture-i')[:24]}",
                        cashflow=-D("1") * D("100.050") * D("0.0002"),
                        at_ms=START + 18,
                    )
                    expected_funding_applied = True
                direct, _ = api.mark_account(
                    direct,
                    mark_id=f"archive-mark:{consumer.index.source_manifest_sha256[:16]}:{row.row_index}",
                    marks=((quote.symbol, (quote.bid_price + quote.ask_price) / D(2), quote.event_at_ms),),
                    as_of_ms=quote.modeled_available_at_ms,
                )
                all_rows.append(row.raw_csv_line)
        result = consumer.commit_prepared(prepared)
        assert not result.replayed
        assert consumer.journal.snapshot().state["archive_cursor"] == asdict(prepared.batch.after)
        assert replace(direct, events=()) == _core(consumer)
        retained = consumer.journal.checkpoint()
        consumer.journal.close()
        consumer = _reopen(consumer, retained)
    assert all_rows == ROWS
    assert [canonical_native_event(e) for e in direct.events] == [
        canonical_native_event(e) for e in consumer.journal.native_events()
    ]
    assert len(direct.events) == len(ROWS) + 1
    state = consumer.journal.snapshot().state
    assert state["liquidity"]["bid_remaining"] == "1.875"
    assert state["liquidity"]["ask_remaining"] == "3.00"
    assert state["latest_bbo"]["row_index"] == 3
    assert state["latest_bbo"]["historical_received_at_ms"] is None
    assert state["latest_bbo"]["historical_persisted_at_ms"] is None
    result = consumer.finish(at_ms=START + 86400010)
    assert result.outcome["source_complete"] and result.outcome["native_marks"] == 4
    assert result.outcome["net_return"] is None
    assert not result.outcome["economics_qualified"]
    consumer.journal.close()


def test_precommit_fault_rolls_back_native_financial_liquidity_and_source_cursor(tmp_path, monkeypatch):
    consumer = _create(tmp_path, initial=_initial(position=True), funding=_funding(known=True))
    prepared = consumer.prepare_next()
    before = consumer.journal.checkpoint()
    original_state = consumer.journal.snapshot().state

    def crash():
        raise RuntimeError("precommit fault")

    monkeypatch.setattr(consumer.journal, "_before_commit", crash)
    with pytest.raises(RuntimeError, match="precommit fault"):
        consumer.commit_prepared(prepared)
    assert consumer.journal.checkpoint() == before
    assert consumer.journal.snapshot().state == original_state
    assert list(consumer.journal.native_events()) == []
    assert consumer._reader.checkpoint() == prepared.batch.before
    monkeypatch.undo()
    retry = consumer.prepare_next()
    assert retry.event_id == prepared.event_id and retry.payload == prepared.payload
    consumer.commit_prepared(retry)
    assert consumer.journal.checkpoint().source_cursor == 2
    consumer.journal.close()


def test_exact_redelivery_no_reapply_and_conflicting_hash_refused(tmp_path):
    consumer = _create(tmp_path)
    prepared = consumer.prepare_next()
    consumer.commit_prepared(prepared)
    checkpoint = consumer.journal.checkpoint()
    assert consumer.commit_prepared(prepared).replayed
    assert consumer.journal.checkpoint() == checkpoint
    bad = replace(prepared, batch=replace(prepared.batch, raw_byte_count=0))
    with pytest.raises(EventConflict):
        consumer.commit_prepared(bad)
    assert consumer.journal.checkpoint() == checkpoint
    consumer.journal.close()


def test_envelope_capacity_failure_no_loss_and_volatile_reader_reopens_before(tmp_path):
    consumer = _create(tmp_path, max_event_bytes=100)
    prepared = consumer.prepare_next()
    checkpoint = consumer.journal.checkpoint()
    with pytest.raises(JournalFull):
        consumer.commit_prepared(prepared)
    assert consumer.journal.checkpoint() == checkpoint
    assert list(consumer.journal.native_events()) == []
    assert consumer._reader.checkpoint() == prepared.batch.before
    consumer.journal.close()


def test_partial_source_cannot_finish_and_unknown_funding_not_hidden(tmp_path):
    consumer = _create(tmp_path, funding=_funding(unresolved=True))
    consumer.consume_next()
    checkpoint = consumer.journal.checkpoint()
    with pytest.raises(ValueError, match="omit"):
        consumer.finish(at_ms=START + 86400010)
    assert consumer.journal.checkpoint() == checkpoint
    consumer.consume_next()
    result = consumer.finish(at_ms=START + 86400010)
    assert result.outcome["status"] == "UNRESOLVED"
    assert result.outcome["net_return"] is None
    assert consumer.finish(at_ms=START + 86400010).replayed
    consumer.journal.close()


def test_concurrent_financial_writer_fence_preserves_prior_expense_and_no_quote_reapply(tmp_path):
    consumer = _create(tmp_path)
    prepared = consumer.prepare_next()
    before = consumer.journal.checkpoint()

    def cost_fold(state):
        account = consumer._load(state)
        account = api.debit_cost(account, cost_id="prior-expense", amount=D("2"), at_ms=START, kind="SERVICE")
        state["account"] = encode_account_core(account, consumer.journal.ledger_reference())
        return {"status": "DEBITED"}

    consumer.journal.transition(
        event_id="prior-expense",
        payload={"cost": "2"},
        at_ms=START,
        expected_version=before.version,
        expected_state_hash=before.state_hash,
        expected_head_sha256=before.head_hash,
        fold=cost_fold,
    )
    retained = consumer.journal.checkpoint()
    with pytest.raises(OptimisticConflict):
        consumer.commit_prepared(prepared)
    assert consumer.journal.checkpoint() == retained
    assert _core(consumer).cash == D("9998")
    consumer.consume_next()
    assert consumer.journal.checkpoint().source_cursor == 2
    assert len(list(consumer.journal.native_events())) == 3
    consumer.journal.close()


def test_native_core_retains_stale_mark_and_risk_barrier_exactly(tmp_path):
    initial = replace(_initial(position=True), policy=replace(POLICY, maximum_mark_age_ms=1))
    consumer = _create(tmp_path, initial=initial)
    direct = initial
    while (prepared := consumer.prepare_next()) is not None:
        for row, quote in zip(prepared.batch.rows, prepared.batch.quotes, strict=True):
            with localcontext(Context(prec=96)):
                direct, _ = api.mark_account(
                    direct,
                    mark_id=f"archive-mark:{consumer.index.source_manifest_sha256[:16]}:{row.row_index}",
                    marks=((quote.symbol, (quote.bid_price + quote.ask_price) / D(2), quote.event_at_ms),),
                    as_of_ms=quote.modeled_available_at_ms,
                )
        consumer.commit_prepared(prepared)
    assert _core(consumer) == replace(direct, events=())
    assert _core(consumer).barrier == "STALE_OR_REGRESSING_MARK"
    assert len(list(consumer.journal.native_events())) == 4
    consumer.journal.close()


@pytest.mark.parametrize("limit,value", [("max_native_event_rows", 3), ("max_event_rows", 4)])
def test_complete_source_resource_preflight_refuses_before_journal_creation(tmp_path, limit, value):
    with pytest.raises(ValueError, match="capacity"):
        _create(tmp_path, **{limit: value})
    assert not (tmp_path / "financial.sqlite3").exists()


def test_external_checkpoint_wrong_anchor_refused_and_no_latest_adoption(tmp_path):
    consumer = _create(tmp_path)
    before = consumer.journal.checkpoint()
    consumer.consume_next()
    consumer.journal.close()
    with pytest.raises(JournalError):
        _reopen(consumer, before)


def test_pending_prepare_is_same_immutable_batch_and_no_hidden_sampling(tmp_path):
    consumer = _create(tmp_path, batch_rows=1)
    prepared = consumer.prepare_next()
    assert consumer.prepare_next() is prepared
    assert consumer.journal.checkpoint().source_cursor == 0
    seen = []
    while (prepared := consumer.prepare_next()) is not None:
        seen.extend(row.row_index for row in prepared.batch.rows)
        consumer.commit_prepared(prepared)
    assert seen == [0, 1, 2, 3]
    assert consumer.journal.checkpoint().native_count == 4
    consumer.journal.close()


def test_original_calc_time_never_rounded_or_used_before_model_availability():
    due = START + 8 * 3600000
    with pytest.raises(ValueError, match="calcTime"):
        ArchiveFundingReceiptV3(due, due + 1, due, "KNOWN", D("0.01"), D("100"), "e" * 64, "a" * 64)
    receipt = ArchiveFundingReceiptV3(
        due, due + 22, due + 25, "KNOWN", D("0.01"), D("100"), "e" * 64, "a" * 64
    )
    with pytest.raises(ValueError, match="offset"):
        ArchiveFundingCalendarV3("EXHAUSTIVE_RETAINED_ROSTER", "b" * 64, 1, (due,), (receipt,))
    calendar = ArchiveFundingCalendarV3("EXHAUSTIVE_RETAINED_ROSTER", "b" * 64, 22, (due,), (receipt,))
    assert calendar.receipts[0].exchange_calc_time_ms == due + 22
    assert calendar.receipts[0].modeled_available_at_ms == due + 25


def test_late_known_funding_retains_due_exposure_after_native_exit(tmp_path):
    consumer = _create(tmp_path, initial=_initial(position=True), funding=_funding(known=True))
    consumer.consume_next()
    checkpoint = consumer.journal.checkpoint()

    def exit_fold(state):
        account, status = api.record_exit_fill(
            consumer._load(state),
            intent_id="fixture-i",
            fill_id="fixture-close",
            quantity=D("1"),
            average_price=D("100.07"),
            fee=D("0.05"),
            at_ms=START + 17,
        )
        state["account"] = encode_account_core(account, consumer.journal.ledger_reference())
        return {"status": status}

    consumer.journal.transition(
        event_id="fixture-close",
        payload={"fixture": "native exit"},
        at_ms=START + 17,
        expected_version=checkpoint.version,
        expected_state_hash=checkpoint.state_hash,
        expected_head_sha256=checkpoint.head_hash,
        fold=exit_fold,
    )
    cash_before = _core(consumer).cash
    consumer.consume_next()
    assert _core(consumer).positions == ()
    assert _core(consumer).cash == cash_before - D("0.020010")
    events = list(consumer.journal.native_events())
    late = [event for event in events if event.payload[0] == "LATE_KNOWN_FUNDING"]
    assert len(late) == 1 and late[0].payload[2] == -D("0.020010")
    assert len(events) == 6
    consumer.journal.close()


@pytest.mark.parametrize("status,rate", [("RATE_ONLY", D("0.001")), ("NO_PAYMENT", D("0"))])
def test_rate_only_or_known_zero_never_invents_settlement_price(tmp_path, status, rate):
    due = START + 15
    receipt = ArchiveFundingReceiptV3(due, due + 1, due + 2, status, rate, None, None, "a" * 64)
    funding = ArchiveFundingCalendarV3("TEST_FIXTURE", "b" * 64, 1, (due,), (receipt,))
    consumer = _create(tmp_path, initial=_initial(position=True), funding=funding)
    while consumer.consume_next() is not None:
        pass
    state = consumer.journal.snapshot().state
    assert state["funding"][str(due)]["receipts"][0]["settlement_price"] is None
    assert _core(consumer).cash == D("10000")
    native = list(consumer.journal.native_events())
    assert len(native) == (5 if status == "NO_PAYMENT" else 4)
    result = consumer.finish(at_ms=START + 86400010)
    assert result.outcome["missing_funding"] == ([str(due)] if status == "RATE_ONLY" else [])
    assert result.outcome["net_return"] is None
    consumer.journal.close()


def test_rate_only_resolution_requires_unchanged_rate_and_price_source():
    due = START + 15
    rate_only = ArchiveFundingReceiptV3(due, due + 1, due + 2, "RATE_ONLY", D("0.001"), None, None, "a" * 64)
    with pytest.raises(ValueError, match="settlement price source"):
        ArchiveFundingReceiptV3(due, due + 1, due + 3, "KNOWN", D("0.001"), D("100"), None, "a" * 64)
    wrong = ArchiveFundingReceiptV3(due, due + 1, due + 3, "KNOWN", D("0.002"), D("100"), "c" * 64, "a" * 64)
    with pytest.raises(ValueError, match="replace"):
        ArchiveFundingCalendarV3("TEST_FIXTURE", "b" * 64, 1, (due,), (rate_only, wrong))


def test_finish_does_not_drop_frozen_late_funding_receipt(tmp_path):
    due = START + 15
    receipt = ArchiveFundingReceiptV3(
        due, due + 1, START + 86400020, "RATE_ONLY", D("0.001"), None, None, "a" * 64
    )
    funding = ArchiveFundingCalendarV3("TEST_FIXTURE", "b" * 64, 1, (due,), (receipt,))
    consumer = _create(tmp_path, funding=funding)
    while consumer.consume_next() is not None:
        pass
    checkpoint = consumer.journal.checkpoint()
    with pytest.raises(ValueError, match="late funding"):
        consumer.finish(at_ms=START + 86400010)
    assert consumer.journal.checkpoint() == checkpoint
    assert consumer.finish(at_ms=START + 86400020).outcome["status"] == "UNRESOLVED"
    consumer.journal.close()


def test_prepared_financial_owner_and_source_anchor_not_substituted(tmp_path):
    consumer = _create(tmp_path)
    prepared = consumer.prepare_next()
    with pytest.raises(ValueError, match="fence"):
        consumer.commit_prepared(
            replace(prepared, before_financial=replace(prepared.before_financial, owner_id="other-owner"))
        )
    assert consumer.journal.checkpoint().native_count == 0
    consumer.commit_prepared(prepared)
    consumer.journal.close()
