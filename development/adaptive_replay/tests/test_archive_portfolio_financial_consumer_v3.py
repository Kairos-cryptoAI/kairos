import hashlib
import zipfile
from dataclasses import asdict, replace
from decimal import Context, localcontext
from decimal import Decimal as D

import pytest
from kairos_execution.simulation.models import FillAssumptions

from adaptive_replay import adaptive_sim_account as api
from adaptive_replay import archive_portfolio_financial_consumer_v3 as module
from adaptive_replay.archive_batch_cursor_v3 import ArchiveBatchLimitsV3, build_archive_batch_index_v3
from adaptive_replay.archive_financial_consumer_v3 import ArchiveFundingCalendarV3, ArchiveFundingReceiptV3
from adaptive_replay.archive_market_clock_v3 import ArchiveMarketClockV3
from adaptive_replay.archive_portfolio_financial_consumer_v3 import (
    ArchiveAdvanceV3,
    ArchiveClosedProtectionV3,
    ArchiveExecutionModelV3,
    ArchiveFixtureEntryV3,
    ArchiveFundingDeliveryV3,
    ArchiveFundingDueV3,
    ArchivePortfolioActionV3,
    ArchivePortfolioFinancialConsumerV3,
    ArchiveServiceCostV3,
)
from adaptive_replay.archive_portfolio_stream_v3 import (
    TIE_RULE,
    ArchivePortfolioLimitsV3,
    ArchivePortfolioPendingAnchorV3,
    ArchivePortfolioSealV3,
    ArchivePortfolioSourceV3,
)
from adaptive_replay.bookticker_archive_stream_v3 import (
    HEADER,
    StreamLimitsV3,
    _day_start_ms,
    build_bookticker_archive_stream_v3,
)
from adaptive_replay.sim_account_core_codec_v3 import decode_account_core
from adaptive_replay.sim_financial_journal_v3 import DEFAULT_LIMITS
from adaptive_replay.sim_state_journal import EventConflict, JournalFull, OptimisticConflict

FIRST = _day_start_ms("2024-01-08")
MIDNIGHT = FIRST + 86400000
BASE = MIDNIGHT - 100
END = MIDNIGHT + 86400000
POLICY = api.AccountPolicy(D("0.1"), D("5"), D("5"), D("0"), 10000, "ENTRY_STOP_RESERVED")
ORDER = ("FUNDING", "CANDLE", "DEADLINE", "CONTROL")
OPENED = []


@pytest.fixture(autouse=True)
def close_all_journals_even_when_assertion_fails():
    OPENED.clear()
    try:
        yield
    finally:
        for journal in reversed(OPENED):
            journal.close()
        OPENED.clear()


def _source(root, symbol, day, rows, *, evidence_kind="TEST_FIXTURE", clock_policy=None):
    root.mkdir()

    def row_line(ordinal, row):
        clock, bid, ask = row[:3]
        event = row[3] if len(row) == 4 else clock
        bid_quantity = "1.2" if symbol == "BTCUSDT" and bid == "98.90" else "2.0"
        return f"{ordinal + 10},{bid},{bid_quantity},{ask},2.0,{clock},{event}\r\n".encode()

    raw = tuple(row_line(i, row) for i, row in enumerate(rows))
    payload = HEADER + b"\r\n" + b"".join(raw)
    path = root / "input.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{symbol}-bookTicker-{day}.csv", payload)
    original = build_bookticker_archive_stream_v3(
        path,
        root / "source",
        symbol=symbol,
        transaction_day=day,
        expected_archive_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        expected_rows=len(raw),
        expected_uncompressed_bytes=len(payload),
        expected_uncompressed_sha256=hashlib.sha256(payload).hexdigest(),
        limits=StreamLimitsV3(
            max_archive_bytes=10000,
            max_uncompressed_bytes=10000,
            max_rows=20,
            segment_bytes=300,
            index_stride=2,
            max_line_bytes=256,
            max_segments=20,
        ),
        evidence_kind=evidence_kind,
    )
    index = build_archive_batch_index_v3(
        original,
        root / "index",
        expected_source_manifest_sha256=original.manifest_sha256,
        limits=ArchiveBatchLimitsV3(max_block_bytes=120, max_batch_rows=3, max_batch_bytes=200),
    )
    return ArchivePortfolioSourceV3(
        f"{symbol}:{day}", index, clock_policy or ArchiveMarketClockV3("EVENT_E", 0, 0)
    ), raw


def _model(symbol, *, step="0.1", latency=1):
    return ArchiveExecutionModelV3(
        symbol,
        FillAssumptions(
            latency_ms=latency,
            maximum_book_age_ms=10000,
            maximum_frame_latency_ms=1,
            depth_participation_fraction=D("0.5"),
            adverse_slippage_bps=D(0),
            taker_fee_bps=D(5),
            price_tick=D("0.01"),
            quantity_step=D(step),
        ),
        D("1000000"),
    )


def _entry(intent, symbol, *, max_holding=500, expires=None):
    return ArchiveFixtureEntryV3(
        intent,
        symbol,
        "LONG",
        D("99.00"),
        D("101.00"),
        D("100.10"),
        D("100.10"),
        D("100.10"),
        BASE + 3,
        expires or BASE + 1000,
        max_holding,
        D("100.20") if symbol == "BTCUSDT" else None,
        D("0.80") if symbol == "BTCUSDT" else None,
        "a" * 64,
        "b" * 64,
        "c" * 64,
    )


def _action(name, at, parameters, source="d" * 64):
    return ArchivePortfolioActionV3(name, at, source, parameters)


def _fixture(
    tmp_path,
    *,
    rate_only=False,
    unknown_cost=False,
    timeout=False,
    batch_rows=2,
    entries=True,
    storage=None,
    latency=1,
    entry_expiry=None,
    reuse_ask=False,
    final_overhang=False,
):
    models = (_model("BTCUSDT", latency=latency), _model("ETHUSDT", step="0.2", latency=latency))
    sources, raws = [], {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for day in ("2024-01-08", "2024-01-09"):
            if day.endswith("08"):
                rows = [(BASE + offset, "100.00", "100.10") for offset in (1, 2, 10)]
                rows.append(
                    (BASE + 30, "98.90", "99.00") if symbol == "BTCUSDT" else (BASE + 30, "101.00", "101.10")
                )
            else:
                rows = [
                    (MIDNIGHT + offset, "98.80", "100.10" if reuse_ask else "98.90")
                    if symbol == "BTCUSDT"
                    else (MIDNIGHT + offset, "101.00", "101.10")
                    for offset in (1, 10, 20)
                ]
            if final_overhang and day.endswith("09"):
                rows.append((END - 2, "100.00", "100.10", END + 5))
            source, raw = _source(
                tmp_path / f"{symbol}-{day}",
                symbol,
                day,
                rows,
                clock_policy=ArchiveMarketClockV3("TRANSACTION_T", 3, 2) if final_overhang else None,
            )
            sources.append(source)
            raws[source.source_key] = raw
    due = BASE + 40
    rate = ArchiveFundingReceiptV3(due, due + 1, due + 1, "RATE_ONLY", D("0.0002"), None, None, "e" * 64)
    known = ArchiveFundingReceiptV3(
        due, due + 1, MIDNIGHT + 15, "KNOWN", D("0.0002"), D("99.50"), "f" * 64, "e" * 64
    )
    calendars = (
        (
            "BTCUSDT",
            ArchiveFundingCalendarV3(
                "TEST_FIXTURE", "a" * 64, 1, (due,), (rate,) if rate_only else (rate, known)
            ),
        ),
        ("ETHUSDT", ArchiveFundingCalendarV3("TEST_FIXTURE", "a" * 64, 0, (), ())),
    )
    actions = []
    if entries:
        actions.extend(
            (
                _action(
                    "entry-btc",
                    BASE + 3,
                    _entry("btc", "BTCUSDT", max_holding=15 if timeout else 500, expires=entry_expiry),
                ),
                _action("entry-eth", BASE + 3, _entry("eth", "ETHUSDT", expires=entry_expiry)),
            )
        )
    if timeout:
        actions.append(_action("timeout-check", BASE + 19, ArchiveAdvanceV3("HOLDING_DEADLINE")))
    actions.extend(
        (
            _action(
                "trail", BASE + 23, ArchiveClosedProtectionV3("BTCUSDT", BASE + 22, D("100.30"), "d" * 64)
            ),
            _action("fund-due", due, ArchiveFundingDueV3("BTCUSDT", due)),
            _action("fund-rate", due + 1, ArchiveFundingDeliveryV3("BTCUSDT", rate)),
            _action(
                "cost", MIDNIGHT + 3, ArchiveServiceCostV3("service-a", None if unknown_cost else D("1.23"))
            ),
            _action("end", END, ArchiveAdvanceV3("RETAINED_END")),
        )
    )
    if not rate_only:
        actions.append(
            _action("fund-known", known.modeled_available_at_ms, ArchiveFundingDeliveryV3("BTCUSDT", known))
        )
    if reuse_ask:
        repeated = replace(
            _entry("btc-repeat", "BTCUSDT"),
            stop_price=D("98.00"),
            eligible_at_ms=MIDNIGHT + 16,
            expires_at_ms=MIDNIGHT + 100,
            trailing_activation_price=None,
            trailing_distance=None,
        )
        actions.append(_action("entry-btc-repeat", MIDNIGHT + 16, repeated))
    actions = tuple(sorted(actions, key=lambda a: (a.at_ms, ORDER.index(a.kind), a.boundary_id)))
    seal = ArchivePortfolioSealV3(
        tuple(sources),
        ("BTCUSDT", "ETHUSDT"),
        ("2024-01-08", "2024-01-09"),
        tuple(a.boundary for a in actions),
        TIE_RULE,
        ORDER,
        ArchivePortfolioLimitsV3(max_batch_rows=batch_rows, max_batch_bytes=200, prefetch_rows=2),
    )
    initial = api.new_account(D(10000), POLICY)
    consumer = ArchivePortfolioFinancialConsumerV3.create(
        tmp_path / "portfolio.sqlite3",
        campaign_id="portfolio-reference",
        owner_id="owner",
        account_id="shared-account",
        seal=seal,
        models=models,
        calendars=calendars,
        actions=actions,
        initial_account=initial,
        entry_start_ms=FIRST,
        entry_end_ms=END,
        retained_end_ms=END + 10 if final_overhang else END,
        expected_cost_ids=("service-a",),
        maximum_exit_attempts=3,
        storage_bounds={**DEFAULT_LIMITS, **(storage or {})},
    )
    OPENED.append(consumer.journal)
    return consumer, initial, raws


def _core(consumer):
    return decode_account_core(consumer.journal.snapshot().state["account"])[0]


def _open(consumer, checkpoint):
    reopened = ArchivePortfolioFinancialConsumerV3.open(
        consumer.journal.path,
        identity=consumer.journal.identity,
        expected_checkpoint=checkpoint,
        seal=consumer.seal,
        models=consumer.models,
        calendars=consumer.calendars,
        actions=consumer.actions,
        config=consumer.config,
    )
    OPENED.append(reopened.journal)
    return reopened


def _create_again(consumer, path, **overrides):
    values = {
        "campaign_id": "another-reference",
        "owner_id": "owner",
        "account_id": "another-account",
        "seal": consumer.seal,
        "models": consumer.models,
        "calendars": consumer.calendars,
        "actions": consumer.actions,
        "initial_account": api.new_account(D(10000), POLICY),
        "entry_start_ms": FIRST,
        "entry_end_ms": END,
        "retained_end_ms": END,
        "expected_cost_ids": ("service-a",),
        "maximum_exit_attempts": 3,
        "storage_bounds": dict(DEFAULT_LIMITS),
        **overrides,
    }
    created = ArchivePortfolioFinancialConsumerV3.create(path, **values)
    OPENED.append(created.journal)
    return created


def _drain(consumer, *, restart=False):
    rows = []
    while (prepared := consumer.prepare_next()) is not None:
        assert consumer.journal.checkpoint() == prepared.before_financial
        assert consumer.journal.snapshot().state["portfolio_checkpoint"] == module._plain(
            asdict(prepared.operation.before)
        )
        rows.extend(
            (r.source_key, r.original.row_index, r.original.raw_csv_line) for r in prepared.operation.rows
        )
        consumer.commit_prepared(prepared)
        assert consumer.journal.snapshot().state["portfolio_checkpoint"] == module._plain(
            asdict(prepared.operation.after)
        )
        if restart:
            checkpoint = consumer.journal.checkpoint()
            consumer.journal.close()
            consumer = _open(consumer, checkpoint)
    return consumer, rows


def _replay_native(initial, events, models):
    account = initial
    steps = {m.symbol: m.assumptions.quantity_step for m in models}
    with localcontext(Context(prec=96)):
        for event in events:
            p, event_id = event.payload, event.event_id
            if p[0] == "MARK":
                account, _ = api.mark_account(account, mark_id=event_id, marks=p[1], as_of_ms=p[2])
            elif p[0] == "RESERVE":
                account = replace(account, policy=replace(account.policy, quantity_step=steps[p[3]]))
                account, _, _ = api.reserve_entry(
                    account,
                    reservation_id=p[1],
                    intent_id=p[2],
                    symbol=p[3],
                    side=p[4],
                    stop_price=p[5],
                    worst_entry_price=p[6],
                    worst_notional_price=p[7],
                    as_of_ms=p[8],
                    expires_at_ms=p[9],
                )
            elif p[0] == "ENTRY_FILL":
                account, _ = api.record_entry_fill(
                    account,
                    reservation_id=p[1],
                    fill_id=event_id,
                    quantity=p[2],
                    average_price=p[3],
                    fee=p[4],
                    at_ms=p[5],
                )
            elif p[0] == "EXIT_FILL":
                account, _ = api.record_exit_fill(
                    account,
                    intent_id=p[1],
                    fill_id=event_id,
                    quantity=p[2],
                    average_price=p[3],
                    fee=p[4],
                    at_ms=p[5],
                )
            elif p[0] == "ENTRY_RESOLUTION":
                account = api.resolve_entry(account, reservation_id=p[1], event_id=event_id, outcome=p[2])
            elif p[0] == "OWNED_PROTECTIVE_EXIT":
                account = api.request_protective_exit(account, intent_id=p[1], event_id=event_id, reason=p[2])
            elif p[0] == "TIGHTEN_STOP":
                account = api.tighten_stop(
                    account,
                    intent_id=p[1],
                    event_id=event_id,
                    stop_price=p[2],
                    source_event_ms=p[3],
                    available_ms=p[4],
                    as_of_ms=p[5],
                )
            elif p[0] == "FUNDING":
                account = api.record_funding(
                    account, intent_id=p[1], event_id=event_id, cashflow=p[2], at_ms=p[3]
                )
            elif p[0] == "LATE_KNOWN_FUNDING":
                account = api.record_late_known_funding(
                    account, event_id=event_id, funding_key=p[1], cashflow=p[2], at_ms=p[3]
                )
            elif p[0] == "SERVICE":
                account = api.debit_cost(account, cost_id=event_id, amount=p[1], at_ms=p[2], kind="SERVICE")
            elif p[0] == "BARRIER":
                account = api.set_barrier(account, event_id=event_id, reason=p[1])
            else:
                raise AssertionError(f"unhandled native event {p[0]}")
    return account


def test_shared_nonresetting_multisymbol_midnight_partials_trailing_funding_native_differential(tmp_path):
    consumer, initial, raws = _fixture(tmp_path)
    consumer, rows = _drain(consumer, restart=True)
    state = consumer.journal.snapshot().state
    assert sorted(rows) == sorted(
        (key, i, raw) for key, values in raws.items() for i, raw in enumerate(values)
    )
    assert state["cursor"] == state["native_mark_count"] == 14
    assert state["parents"]["btc"]["entry_status"] == "PARTIAL"
    assert state["parents"]["eth"]["entry_status"] == "PARTIAL"
    assert state["parents"]["btc"]["closed_at_ms"] == MIDNIGHT + 2
    assert state["parents"]["btc"]["trailing_active"]
    assert len([o for o in state["parents"]["btc"]["outcomes"] if o["command"]["side"] == "SELL"]) == 2
    assert state["parents"]["btc"]["outcomes"][1]["status"] == "PARTIAL"
    assert state["debits"]["BTCUSDT"]["ASK:100.10"] == "1.0"
    assert all(
        value["historical_received_at_ms"] is None and value["historical_persisted_at_ms"] is None
        for value in state["liquidity"].values()
    )
    assert state["funding"][f"BTCUSDT:{BASE + 40}"]["status"] == "KNOWN"
    events = tuple(consumer.journal.native_events())
    expected = _replay_native(initial, events, consumer.models)
    assert replace(expected, events=()) == _core(consumer)
    assert expected.events == events
    assert any(e.payload[0] == "LATE_KNOWN_FUNDING" for e in events)
    assert len([e for e in events if e.payload[0] == "MARK"]) == 14
    result = consumer.finish(at_ms=END).outcome
    assert result["status"] == "MODELED_REFERENCE_COMPLETE"
    assert result["open_positions"] == 0 and result["net_return"] is None
    assert not result["economics_qualified"] and not result["accepted_historical_inputs"]
    consumer.journal.close()


def test_rate_without_settlement_and_unknown_cost_remain_numeric_unresolved(tmp_path):
    consumer, _, _ = _fixture(tmp_path, rate_only=True, unknown_cost=True)
    consumer, _ = _drain(consumer)
    outcome = consumer.finish(at_ms=END).outcome
    assert outcome["status"] == "UNRESOLVED"
    assert outcome["missing_funding"] == [f"BTCUSDT:{BASE + 40}"]
    assert outcome["missing_service_costs"] == ["service-a"]
    assert not any(
        e.payload[0] in {"FUNDING", "LATE_KNOWN_FUNDING"} for e in consumer.journal.native_events()
    )
    consumer.journal.close()


def test_timeout_boundary_preserves_existing_positions_and_native_protection(tmp_path):
    consumer, initial, _ = _fixture(tmp_path, timeout=True)
    consumer, _ = _drain(consumer, restart=True)
    events = tuple(consumer.journal.native_events())
    assert any(e.payload == ("OWNED_PROTECTIVE_EXIT", "btc", "TIMEOUT") for e in events)
    assert consumer.journal.snapshot().state["parents"]["btc"]["closed_at_ms"] == BASE + 20
    assert replace(_replay_native(initial, events, consumer.models), events=()) == _core(consumer)
    consumer.journal.close()


def test_pending_before_recovery_exact_duplicate_and_conflict(tmp_path):
    consumer, _, _ = _fixture(tmp_path)
    prepared = consumer.prepare_next()
    anchor = ArchivePortfolioPendingAnchorV3(
        prepared.operation.before,
        prepared.operation.after,
        prepared.operation.operation_id,
        prepared.operation.sha256,
    )
    consumer.journal.close()
    consumer = _open(consumer, prepared.before_financial)
    recovered = consumer.recover_prepared(
        before_financial=prepared.before_financial, retained_stream_anchor=anchor
    )
    assert recovered.payload == prepared.payload
    first = consumer.commit_prepared(recovered)
    checkpoint = consumer.journal.checkpoint()
    duplicate = consumer.commit_prepared(recovered)
    assert duplicate.replayed and first.outcome == duplicate.outcome
    assert consumer.journal.checkpoint() == checkpoint
    with pytest.raises(EventConflict):
        consumer.commit_prepared(replace(recovered, operation=replace(recovered.operation, raw_byte_count=0)))
    with pytest.raises(ValueError, match="exact retained financial"):
        consumer.recover_prepared(before_financial=prepared.before_financial, retained_stream_anchor=anchor)
    consumer.journal.close()


def test_atomic_fault_rolls_back_core_native_liquidity_source_vector_and_reader(tmp_path, monkeypatch):
    consumer, _, _ = _fixture(tmp_path)
    before = consumer.journal.checkpoint()
    prepared = consumer.prepare_next()
    original = consumer.journal._before_commit
    monkeypatch.setattr(
        consumer.journal,
        "_before_commit",
        lambda: (_ for _ in ()).throw(RuntimeError("injected commit fault")),
    )
    with pytest.raises(RuntimeError, match="commit fault"):
        consumer.commit_prepared(prepared)
    assert consumer.journal.checkpoint() == before
    assert tuple(consumer.journal.native_events()) == ()
    assert consumer.journal.snapshot().state["latest"] == {}
    monkeypatch.setattr(consumer.journal, "_before_commit", original)
    retried = consumer.prepare_next()
    assert retried.payload == prepared.payload and retried.event_id == prepared.event_id
    consumer.commit_prepared(retried)
    assert consumer.journal.snapshot().state["native_mark_count"] == len(prepared.operation.rows)
    consumer.journal.close()


def test_lifecycle_failure_after_prior_commits_keeps_full_denominator_and_sticky_expenses(
    tmp_path, monkeypatch
):
    consumer, _, _ = _fixture(tmp_path)
    while consumer.journal.snapshot().state["clock"] < MIDNIGHT + 3:
        consumer.consume_next()
    checkpoint = consumer.journal.checkpoint()
    cash = _core(consumer).cash
    prepared = consumer.prepare_next()
    monkeypatch.setattr(
        consumer.journal, "_before_commit", lambda: (_ for _ in ()).throw(RuntimeError("after service"))
    )
    with pytest.raises(RuntimeError):
        consumer.commit_prepared(prepared)
    assert consumer.journal.checkpoint() == checkpoint and _core(consumer).cash == cash
    assert _core(consumer).service_cost_total == D("1.23")
    consumer.journal.close()


def test_known_postcommit_pending_retries_handoff_without_reapply(tmp_path, monkeypatch):
    consumer, _, _ = _fixture(tmp_path)
    prepared = consumer.prepare_next()
    original = consumer._stream.acknowledge
    monkeypatch.setattr(
        consumer._stream,
        "acknowledge",
        lambda operation: (_ for _ in ()).throw(RuntimeError("after durable commit")),
    )
    with pytest.raises(RuntimeError, match="durable commit"):
        consumer.commit_prepared(prepared)
    after = consumer.journal.checkpoint()
    monkeypatch.setattr(consumer._stream, "acknowledge", original)
    result = consumer.commit_prepared(prepared)
    assert result.replayed and consumer.journal.checkpoint() == after
    assert consumer._stream.checkpoint() == prepared.operation.after
    consumer.journal.close()


def test_journal_open_cannot_adopt_latest_after_unretained_commit(tmp_path):
    consumer, _, _ = _fixture(tmp_path)
    before = consumer.journal.checkpoint()
    consumer.consume_next()
    consumer.journal.close()
    with pytest.raises(Exception, match="checkpoint"):
        _open(consumer, before)


def test_nonowned_prepared_or_another_writer_head_refuses(tmp_path):
    consumer, _, _ = _fixture(tmp_path)
    prepared = consumer.prepare_next()
    with pytest.raises(ValueError, match="owned pending"):
        consumer.commit_prepared(replace(prepared))
    consumer.journal.transition(
        event_id="other-owned-action",
        payload={"kind": "OTHER"},
        at_ms=FIRST,
        expected_version=prepared.before_financial.version,
        expected_state_hash=prepared.before_financial.state_hash,
        expected_head_sha256=prepared.before_financial.head_hash,
        fold=lambda state: {"status": "OTHER"},
    )
    with pytest.raises(OptimisticConflict):
        consumer.commit_prepared(prepared)
    consumer.journal.close()


def test_actual_row_clock_not_batch_tail_and_expired_arrival_no_invented_fill(tmp_path):
    consumer, _, _ = _fixture(tmp_path, latency=20, entry_expiry=BASE + 5, batch_rows=3)
    consumer, _ = _drain(consumer)
    parents = consumer.journal.snapshot().state["parents"]
    assert all(p["entry_status"] == "NO_FILL" for p in parents.values())
    assert all(
        p["outcomes"][0]["reason"] == "COMMAND_EXPIRED" and p["outcomes"][0]["arrival_at_ms"] == BASE + 23
        for p in parents.values()
    )
    assert not _core(consumer).positions
    consumer.journal.close()


def test_finish_before_source_or_boundary_is_fail_closed(tmp_path):
    consumer, _, _ = _fixture(tmp_path)
    with pytest.raises(ValueError, match="omit"):
        consumer.finish(at_ms=END)
    consumer.journal.close()


def test_reducer_or_configuration_drift_refuses_before_financial_write(tmp_path, monkeypatch):
    consumer, _, _ = _fixture(tmp_path)
    before = consumer.journal.checkpoint()
    original = module.api.mark_account
    monkeypatch.setattr(module.api, "mark_account", lambda *a, **kw: None)
    with pytest.raises(ValueError, match="runtime drift"):
        consumer.prepare_next()
    monkeypatch.setattr(module.api, "mark_account", original)
    consumer.config["entry_end_ms"] += 1
    with pytest.raises(ValueError, match="runtime drift"):
        consumer.prepare_next()
    assert consumer.journal.checkpoint() == before
    consumer.journal.close()


def test_same_price_capacity_never_replenishes_with_new_row_or_midnight(tmp_path):
    consumer, _, _ = _fixture(tmp_path, reuse_ask=True)
    consumer, _ = _drain(consumer, restart=True)
    parent = consumer.journal.snapshot().state["parents"]["btc-repeat"]
    assert parent["entry_status"] == "NO_FILL"
    assert parent["outcomes"][0]["filled_quantity"] == "0"
    assert consumer.journal.snapshot().state["debits"]["BTCUSDT"]["ASK:100.10"] == "1.0"
    assert not _core(consumer).positions
    consumer.journal.close()


def test_atomic_event_byte_cap_refuses_without_dropping_original_rows(tmp_path):
    consumer, _, _ = _fixture(tmp_path, storage={"max_event_bytes": 100})
    prepared = consumer.prepare_next()
    before = consumer.journal.checkpoint()
    with pytest.raises(JournalFull):
        consumer.commit_prepared(prepared)
    assert consumer.journal.checkpoint() == before
    assert consumer.journal.snapshot().state["cursor"] == 0
    assert tuple(consumer.journal.native_events()) == ()
    consumer.journal.close()


@pytest.mark.parametrize(
    "case", ["tail", "models", "native_capacity", "outer_capacity", "cost_roster", "ties"]
)
def test_full_roster_models_costs_storage_and_tail_preflight(tmp_path, case):
    consumer, _, _ = _fixture(tmp_path)
    arguments = {}
    if case == "tail":
        arguments["retained_end_ms"] = END + 86400000
    elif case == "models":
        arguments["models"] = consumer.models[:-1]
    elif case == "native_capacity":
        arguments["storage_bounds"] = {**DEFAULT_LIMITS, "max_native_event_rows": 14}
    elif case == "outer_capacity":
        arguments["storage_bounds"] = {**DEFAULT_LIMITS, "max_event_rows": 14}
    elif case == "cost_roster":
        arguments["expected_cost_ids"] = ()
    else:
        arguments["seal"] = replace(
            consumer.seal, boundary_tie_order=("CONTROL", "DEADLINE", "CANDLE", "FUNDING")
        )
    with pytest.raises(ValueError):
        _create_again(consumer, tmp_path / "refused.sqlite3", **arguments)
    assert not (tmp_path / "refused.sqlite3").exists()
    consumer.journal.close()


def test_all_due_and_receipt_boundaries_required_not_automatic_funding_skip(tmp_path):
    consumer, _, _ = _fixture(tmp_path)
    actions = tuple(a for a in consumer.actions if type(a.parameters) is not ArchiveFundingDueV3)
    seal = replace(consumer.seal, boundaries=tuple(a.boundary for a in actions))
    with pytest.raises(ValueError, match="explicit boundary"):
        _create_again(consumer, tmp_path / "missing-due.sqlite3", seal=seal, actions=actions)
    consumer.journal.close()


def test_candidate_rule_and_actual_clock_guards_before_reservation(tmp_path):
    consumer, _, _ = _fixture(tmp_path)
    actions = tuple(
        replace(a, parameters=replace(a.parameters, price_cap=D("100.105")))
        if type(a.parameters) is ArchiveFixtureEntryV3
        else a
        for a in consumer.actions
    )
    seal = replace(consumer.seal, boundaries=tuple(a.boundary for a in actions))
    with pytest.raises(ValueError, match="symbol rules"):
        _create_again(consumer, tmp_path / "bad-candidate.sqlite3", seal=seal, actions=actions)
    with pytest.raises(ValueError, match="fixture plan"):
        replace(_entry("bad", "BTCUSDT"), proof_kind="NATIVE_V3_ADMITTED")
    consumer.journal.close()


def test_final_original_event_overhang_and_model_delays_not_extra_transaction_day(tmp_path):
    consumer, _, raws = _fixture(tmp_path, entries=False, final_overhang=True)
    assert consumer.config["transaction_roster_end_ms"] == END
    assert consumer.config["processing_end_ms"] == consumer.config["retained_end_ms"] == END + 10
    assert consumer.config["entry_days"] == ["2024-01-08", "2024-01-09"]
    consumer, rows = _drain(consumer, restart=True)
    assert len(rows) == sum(map(len, raws.values())) == 16
    with pytest.raises(ValueError, match="exact separately sealed"):
        consumer.finish(at_ms=END)
    assert consumer.finish(at_ms=END + 10).outcome["source_complete"]
    for wrong in (END + 9, END + 11, END + 86400000):
        with pytest.raises(ValueError, match="EXACT_PROCESSING_END"):
            _create_again(consumer, tmp_path / f"bad-processing-{wrong}.sqlite3", retained_end_ms=wrong)
    consumer.journal.close()


@pytest.mark.parametrize("liability", ["funding", "service"])
def test_unknown_due_liability_refuses_new_reservation_but_preserves_prior_effects(tmp_path, liability):
    original, _, _ = _fixture(tmp_path, unknown_cost=liability == "service")
    now = MIDNIGHT + (11 if liability == "funding" else 16)
    plan = replace(
        _entry("blocked-repeat", "BTCUSDT"),
        stop_price=D("98"),
        eligible_at_ms=now,
        expires_at_ms=now + 100,
        trailing_activation_price=None,
        trailing_distance=None,
    )
    actions = tuple(
        sorted(
            (*original.actions, _action("blocked-repeat", now, plan)),
            key=lambda a: (a.at_ms, ORDER.index(a.kind), a.boundary_id),
        )
    )
    consumer = _create_again(
        original,
        tmp_path / "blocked.sqlite3",
        actions=actions,
        seal=replace(original.seal, boundaries=tuple(a.boundary for a in actions)),
    )
    consumer, _ = _drain(consumer, restart=True)
    state = consumer.journal.snapshot().state
    parent = state["parents"][plan.intent_id]
    assert parent["entry_status"] == f"UNRESOLVED_{liability.upper()}_LIABILITY"
    assert not parent["outcomes"]
    assert not any(e.event_id == "r:blocked-repeat" for e in consumer.journal.native_events())
    assert any(e.payload[0] == "LATE_KNOWN_FUNDING" for e in consumer.journal.native_events())
    assert state["native_mark_count"] == state["cursor"] == 14
    assert state["funding"][f"BTCUSDT:{BASE + 40}"]["exposures"]


def test_flat_due_zero_entitlement_does_not_invent_cash_or_block_later_entry(tmp_path):
    original, _, _ = _fixture(tmp_path, entries=False, rate_only=True)
    now = MIDNIGHT + 16
    plan = replace(
        _entry("after-flat-due", "BTCUSDT"),
        stop_price=D("98"),
        eligible_at_ms=now,
        expires_at_ms=now + 100,
        trailing_activation_price=None,
        trailing_distance=None,
    )
    actions = tuple(
        sorted(
            (*original.actions, _action("after-flat-due", now, plan)),
            key=lambda a: (a.at_ms, ORDER.index(a.kind), a.boundary_id),
        )
    )
    consumer = _create_again(
        original,
        tmp_path / "flat-due.sqlite3",
        actions=actions,
        seal=replace(original.seal, boundaries=tuple(a.boundary for a in actions)),
    )
    consumer, _ = _drain(consumer, restart=True)
    state = consumer.journal.snapshot().state
    assert not state["funding"][f"BTCUSDT:{BASE + 40}"]["exposures"]
    assert state["parents"][plan.intent_id]["first_fill_at_ms"] == now + 1
    assert not state["parents"][plan.intent_id]["sizing"]["unresolved_funding"]
    assert not any(
        e.payload[0] in {"FUNDING", "LATE_KNOWN_FUNDING"} for e in consumer.journal.native_events()
    )
    assert consumer.finish(at_ms=END).outcome["missing_funding"] == []


def test_fixture_worst_amounts_are_audit_only_not_native_sizing_authority(tmp_path):
    original, initial, _ = _fixture(tmp_path)
    actions = tuple(
        replace(
            a, parameters=replace(a.parameters, worst_entry_price=D("99.01"), worst_notional_price=D("0.01"))
        )
        if type(a.parameters) is ArchiveFixtureEntryV3
        else a
        for a in original.actions
    )
    changed = _create_again(
        original,
        tmp_path / "poisoned-declarations.sqlite3",
        actions=actions,
        seal=replace(original.seal, boundaries=tuple(a.boundary for a in actions)),
    )
    original, _ = _drain(original)
    changed, _ = _drain(changed, restart=True)
    events = tuple(changed.journal.native_events())
    original_events = tuple(original.journal.native_events())
    # MARK IDs bind their distinct complete campaign seals, which include the
    # deliberately poisoned audit declarations. All financial payloads and
    # non-MARK identities remain exact, and each full stream replays separately.
    assert tuple(e.payload for e in events) == tuple(e.payload for e in original_events)
    assert tuple(e for e in events if e.payload[0] != "MARK") == tuple(
        e for e in original_events if e.payload[0] != "MARK"
    )
    assert replace(_replay_native(initial, original_events, original.models), events=()) == _core(original)
    assert (
        _core(changed)
        == _core(original)
        == replace(_replay_native(initial, events, changed.models), events=())
    )
    assert changed.journal.snapshot().state["parents"]["btc"]["sizing"]["worst_entry_price"] == "100.10"


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_future_ioc_permission_fees_slippage_and_ceiling_drive_native_reserved_risk(tmp_path, side):
    original, _, _ = _fixture(tmp_path, entries=False)
    assumptions = replace(POLICY, adverse_exit_slippage_bps=D("2"))
    models = tuple(
        replace(
            m,
            assumptions=m.assumptions.model_copy(update={"adverse_slippage_bps": D("2")}),
            maximum_order_price=D("102"),
        )
        for m in original.models
    )
    plan = replace(
        _entry("bounded", "ETHUSDT"),
        side=side,
        stop_price=D("99") if side == "LONG" else D("102"),
        target_price=D("101") if side == "LONG" else D("98"),
        price_cap=D("100.90") if side == "LONG" else D("99.90"),
    )
    actions = tuple(
        sorted(
            (*original.actions, _action("bounded", BASE + 3, plan)),
            key=lambda a: (a.at_ms, ORDER.index(a.kind), a.boundary_id),
        )
    )
    initial = api.new_account(D(10000), assumptions)
    consumer = _create_again(
        original,
        tmp_path / f"risk-{side}.sqlite3",
        models=models,
        initial_account=initial,
        actions=actions,
        seal=replace(original.seal, boundaries=tuple(a.boundary for a in actions)),
    )
    while (prepared := consumer.prepare_next()) is not None:
        consumer.commit_prepared(prepared)
        if "bounded" in consumer.journal.snapshot().state["parents"]:
            break
    account = _core(consumer)
    reservation = next(r for r in account.reservations if r.intent_id == "bounded")
    expected_entry = D("100.90") if side == "LONG" else D("99.84")
    assert reservation.worst_entry_price == expected_entry
    assert reservation.worst_notional_price == (D("100.90") if side == "LONG" else D("102"))
    assert reservation.worst_entry_price != plan.worst_entry_price
    with localcontext(Context(prec=96)):
        adverse_stop = plan.stop_price * (1 - D("0.0002") if side == "LONG" else 1 + D("0.0002"))
        unit = (
            (expected_entry - adverse_stop) * (1 if side == "LONG" else -1)
            + expected_entry * D("0.0005")
            + adverse_stop * D("0.0005")
        )
        assert reservation.reserved_risk == reservation.quantity * unit
        assert reservation.reserved_risk <= account.equity * D("0.0025")
        assert account.open_risk <= account.equity * D("0.01")
    consumer, _ = _drain(consumer, restart=True)
    events = tuple(consumer.journal.native_events())
    assert replace(_replay_native(initial, events, models), events=()) == _core(consumer)


def test_original_quote_above_frozen_ceiling_cannot_escape_short_gross_bound(tmp_path):
    original, _, _ = _fixture(tmp_path, entries=False)
    plan = replace(
        _entry("short", "ETHUSDT"),
        side="SHORT",
        stop_price=D("102"),
        target_price=D("98"),
        price_cap=D("99.90"),
    )
    models = tuple(replace(m, maximum_order_price=D("100.00")) for m in original.models)
    actions = tuple(
        sorted(
            (*original.actions, _action("short", BASE + 3, plan)),
            key=lambda a: (a.at_ms, ORDER.index(a.kind), a.boundary_id),
        )
    )
    consumer = _create_again(
        original,
        tmp_path / "ceiling.sqlite3",
        models=models,
        actions=actions,
        seal=replace(original.seal, boundaries=tuple(a.boundary for a in actions)),
    )
    consumer, _ = _drain(consumer)
    parent = consumer.journal.snapshot().state["parents"]["short"]
    assert parent["entry_status"] == "BLOCKED"
    assert parent["outcomes"][0]["reason"] == "ARCHIVE_BOOK_ABOVE_SEALED_PRICE_CEILING"
    assert not _core(consumer).positions
