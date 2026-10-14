import json
import shutil
import sqlite3
from contextlib import closing
from dataclasses import replace
from decimal import Decimal as D

import pytest

from adaptive_replay import adaptive_sim_account as api
from adaptive_replay import sim_financial_journal_v3 as financial_module
from adaptive_replay.account_event_context_v3 import (
    NativeEventContext,
    NativeEventContextError,
    canonical_native_event,
    current_native_event_context,
)
from adaptive_replay.sim_account_core_codec_v3 import decode_account_core, encode_account_core
from adaptive_replay.sim_financial_journal_v3 import SimFinancialJournalV3, initial_ledger_reference
from adaptive_replay.sim_state_journal import (
    EventConflict,
    IdentityMismatch,
    JournalError,
    JournalFull,
    JournalIdentity,
    OptimisticConflict,
    _canonical,
    _hash,
)

IDENTITY = JournalIdentity("financial-test", "exact-input", "policy", "implementation")
POLICY = api.AccountPolicy(D("0.1"), D("5"), D("5"), D("2"), 10_000, "ENTRY_STOP_RESERVED")
OWNER, ACCOUNT, STEPS = "arm-a", "account-a", (D("0.01"), D("0.1"))


def create(path, **limits):
    ref = initial_ledger_reference(IDENTITY, owner_id=OWNER, account_id=ACCOUNT)
    return SimFinancialJournalV3.create(
        path,
        identity=IDENTITY,
        owner_id=OWNER,
        account_id=ACCOUNT,
        allowed_quantity_steps=STEPS,
        initial_state={"account": encode_account_core(api.new_account(D("10000"), POLICY), ref), "cursor": 0},
        **limits,
    )


def reopen(path, checkpoint, **overrides):
    return SimFinancialJournalV3.open(
        path,
        **{
            "identity": IDENTITY,
            "owner_id": OWNER,
            "account_id": ACCOUNT,
            "allowed_quantity_steps": STEPS,
            "expected_checkpoint": checkpoint,
            **overrides,
        },
    )


def transition(journal, name, fold, *, at=10, payload=None, snapshot=None):
    snap = snapshot or journal.snapshot()
    return journal.transition(
        event_id=name,
        payload={"kind": name} if payload is None else payload,
        at_ms=at,
        expected_version=snap.version,
        expected_state_hash=snap.state_hash,
        expected_head_sha256=snap.head_hash,
        fold=fold,
    )


def load(journal, state):
    account, ref = decode_account_core(state["account"])
    journal.validate_ledger_reference(ref)
    current_native_event_context(account)
    return account


def store(journal, state, account):
    state["account"] = encode_account_core(account, journal.ledger_reference())


def mark(name, at=10, price="100"):
    return api.mark_account, {
        "mark_id": name,
        "marks": (("BTCUSDT", D(price), at),),
        "as_of_ms": at,
    }


def cost(name, amount="1", at=10):
    return api.debit_cost, {"cost_id": name, "amount": D(amount), "at_ms": at, "kind": "SERVICE"}


def fold_actions(journal, actions, *, cursor=None):
    def fold(state):
        assert journal._connection.in_transaction
        assert current_native_event_context() is not None
        account = load(journal, state)
        statuses = []
        for function, kwargs in actions:
            result = function(account, **kwargs)
            account = result[0] if type(result) is tuple else result
            statuses.append(result[-1] if type(result) is tuple else "RECORDED")
            store(journal, state, account)
            account = load(journal, state)  # Proves exact advanced staged prefix is readable.
        if cursor is not None:
            state["cursor"] = cursor
        return {"statuses": statuses}

    return fold


def test_financial_fold_never_copies_retained_stage_prefix_and_preserves_native_audit(tmp_path, monkeypatch):
    def forbidden_full_prefix(_):
        raise AssertionError("full staged prefix copied in per-event financial hot path")

    monkeypatch.setattr(NativeEventContext, "staged_events", property(forbidden_full_prefix))
    journal = create(tmp_path / "indexed-stage.sqlite3")
    try:
        actions = [mark(f"stage:{i}", i + 10, str(100 + i)) for i in range(512)]
        result = transition(journal, "dense-stage", fold_actions(journal, actions, cursor=512), at=522)
        assert result.snapshot.state["cursor"] == 512
        checkpoint = journal.checkpoint()
        assert checkpoint.native_count == 512
        events = tuple(journal.native_events())
        assert len(events) == 512
        assert tuple(event.event_id for event in events) == tuple(f"stage:{i}" for i in range(512))
        assert journal.audit().state_hash == result.snapshot.state_hash
    finally:
        journal.close()


def test_exact_native_full_financial_differential_flat_marks_crossday_partial_late_funding_restart(tmp_path):
    path = tmp_path / "financial.sqlite3"
    journal = create(path)
    native = api.new_account(D("10000"), POLICY)
    actions = [
        mark("flat:1", 10),
        mark("flat:2", 11, "100.01"),
        (
            api.reserve_entry,
            {
                "reservation_id": "r",
                "intent_id": "i",
                "symbol": "BTCUSDT",
                "side": "LONG",
                "stop_price": D("90"),
                "worst_entry_price": D("100.1"),
                "worst_notional_price": D("101"),
                "as_of_ms": 12,
                "expires_at_ms": 86_400_050,
            },
        ),
        (
            api.record_entry_fill,
            {
                "reservation_id": "r",
                "fill_id": "entry",
                "quantity": D("1"),
                "average_price": D("100"),
                "fee": D("0.05"),
                "at_ms": 13,
            },
        ),
        (api.resolve_entry, {"reservation_id": "r", "event_id": "resolved", "outcome": "PARTIAL"}),
        cost("service", "2.25", 14),
        (api.record_funding, {"intent_id": "i", "event_id": "funding", "cashflow": D("-0.125"), "at_ms": 15}),
        mark("active:1", 16, "100.25"),
        (
            api.tighten_stop,
            {
                "intent_id": "i",
                "event_id": "trail",
                "stop_price": D("95"),
                "source_event_ms": 16,
                "available_ms": 16,
                "as_of_ms": 16,
            },
        ),
        (
            api.record_exit_fill,
            {
                "intent_id": "i",
                "fill_id": "partial-exit",
                "quantity": D("0.4"),
                "average_price": D("102"),
                "fee": D("0.02"),
                "at_ms": 17,
            },
        ),
        mark("crossday:mark", 86_400_020, "103"),
        (
            api.record_exit_fill,
            {
                "intent_id": "i",
                "fill_id": "last-exit",
                "quantity": D("0.6"),
                "average_price": D("103"),
                "fee": D("0.03"),
                "at_ms": 86_400_021,
            },
        ),
        (
            api.record_late_known_funding,
            {
                "event_id": "late-funding",
                "funding_key": "BTCUSDT:86400000",
                "cashflow": D("-0.375"),
                "at_ms": 86_400_022,
            },
        ),
        mark("flat:3", 86_400_023, "103"),
    ]
    for index, action in enumerate(actions, 1):
        result = action[0](native, **action[1])
        native = result[0] if type(result) is tuple else result
        at = max(10 + index, action[1].get("at_ms", action[1].get("as_of_ms", 10)))
        result = transition(journal, f"outer:{index}", fold_actions(journal, [action], cursor=index), at=at)
        actual, ref = decode_account_core(result.snapshot.state["account"])
        assert actual == replace(native, events=())
        assert ref.event_count == len(native.events)
        assert tuple(journal.native_events()) == native.events
        if index == 10:
            checkpoint = journal.checkpoint()
            journal.close()
            journal = reopen(path, checkpoint)
    assert [event.event_id for event in journal.native_events() if event.payload[0] == "MARK"] == [
        "flat:1",
        "flat:2",
        "active:1",
        "crossday:mark",
        "flat:3",
    ]
    assert journal.audit() == journal.snapshot()
    journal.close()


def test_outer_duplicate_returns_original_outcome_latest_state_without_fold_and_conflicts(tmp_path):
    journal = create(tmp_path / "duplicate.sqlite3")
    genesis = journal.snapshot()
    first = transition(journal, "first", fold_actions(journal, [mark("m1"), cost("c1")]), at=10)
    latest = transition(journal, "second", fold_actions(journal, [mark("m2", 11)]), at=11)

    def never(_):
        raise AssertionError("duplicate envelope must not fold")

    duplicate = transition(journal, "first", never, at=10, snapshot=genesis)
    assert duplicate.replayed
    assert duplicate.outcome == first.outcome
    assert duplicate.snapshot == latest.snapshot
    with pytest.raises(EventConflict):
        transition(journal, "first", never, payload={"kind": "different"})
    with pytest.raises(EventConflict):
        transition(journal, "first", never, at=12)
    with pytest.raises(OptimisticConflict):
        transition(journal, "new", never, at=11, snapshot=genesis)
    journal.close()


def test_native_exact_durable_and_staged_duplicates_conflicts_after_restart(tmp_path):
    path = tmp_path / "native-duplicate.sqlite3"
    journal = create(path)
    transition(journal, "first", fold_actions(journal, [cost("cost"), cost("cost"), mark("flat", 10)]))
    checkpoint = journal.checkpoint()
    journal.close()
    journal = reopen(path, checkpoint)
    before = decode_account_core(journal.snapshot().state["account"])[0]
    result = transition(journal, "duplicate-native", fold_actions(journal, [cost("cost"), mark("flat", 10)]))
    assert decode_account_core(result.snapshot.state["account"])[0] == before
    assert journal.checkpoint().native_count == 2
    previous = journal.checkpoint()
    with pytest.raises(NativeEventContextError, match="conflicting"):
        transition(journal, "conflict", fold_actions(journal, [cost("cost", "2")]))
    assert journal.checkpoint() == previous
    journal.close()


@pytest.mark.parametrize("seam", ["_insert_native", "_update_projection", "_before_commit"])
def test_fault_after_native_projection_or_precommit_rolls_back_every_table(tmp_path, monkeypatch, seam):
    journal = create(tmp_path / f"fault-{seam}.sqlite3")
    checkpoint = journal.checkpoint()
    original = getattr(journal, seam)

    def fail(*args):
        original(*args)
        raise RuntimeError("injected failure")

    with monkeypatch.context() as patch:
        patch.setattr(journal, seam, fail)
        with pytest.raises(RuntimeError, match="injected failure"):
            transition(journal, "failed", fold_actions(journal, [mark("flat"), cost("cost")], cursor=1))
    assert current_native_event_context() is None
    assert not journal._connection.in_transaction
    assert journal.checkpoint() == checkpoint
    assert journal._connection.execute("SELECT COUNT(*) FROM native_events").fetchone()[0] == 0
    assert journal._connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    journal.audit()
    journal.close()


def test_silent_projection_update_failure_is_detected_before_commit_and_rolls_back(tmp_path, monkeypatch):
    journal = create(tmp_path / "silent-projection.sqlite3")
    checkpoint = journal.checkpoint()
    with monkeypatch.context() as patch:
        patch.setattr(journal, "_update_projection", lambda _: None)
        with pytest.raises(JournalError, match="projection"):
            transition(journal, "failed", fold_actions(journal, [mark("flat"), cost("cost")], cursor=1))
    assert journal.checkpoint() == checkpoint
    assert tuple(journal.native_events()) == ()
    assert journal._connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    journal.close()


def test_fold_failure_cursor_regression_wrong_owner_ref_and_nested_operations_rollback(tmp_path):
    journal = create(tmp_path / "fold.sqlite3")
    transition(journal, "first", fold_actions(journal, [mark("flat")], cursor=1))
    checkpoint = journal.checkpoint()

    def fail(state):
        account = api.debit_cost(load(journal, state), cost_id="c", amount=D("1"), at_ms=10, kind="SERVICE")
        store(journal, state, account)
        raise RuntimeError("fold failed")

    with pytest.raises(RuntimeError, match="fold failed"):
        transition(journal, "bad-fold", fail)
    with pytest.raises(JournalError, match="regressed"):
        transition(journal, "bad-cursor", fold_actions(journal, [cost("c")], cursor=0))

    def wrong_ref(state):
        ref = journal.ledger_reference()
        for changed in (
            replace(ref, owner_id="arm-b"),
            replace(ref, head_sha256="0" * 64),
            replace(ref, account_id="account-b"),
            replace(ref, event_count=ref.event_count + 1),
        ):
            with pytest.raises(JournalError, match="prefix"):
                journal.validate_ledger_reference(changed)
        with pytest.raises(JournalError, match="nested"):
            journal.snapshot()
        state["account"]["ledger"]["owner_id"] = "arm-b"

    with pytest.raises(JournalError, match="prefix"):
        transition(journal, "wrong-ref", wrong_ref)
    assert journal.checkpoint() == checkpoint
    journal.close()


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE native_events SET event_json='{}' WHERE ordinal=1",
        "UPDATE native_events SET within_outer=99 WHERE ordinal=1",
        "UPDATE native_events SET event_id='other' WHERE ordinal=1",
        "DELETE FROM native_events WHERE ordinal=1",
        "UPDATE events SET delta_json='{\"operations\":[]}' WHERE version=1",
        "UPDATE projection SET value_json='0' WHERE path='[\"cursor\"]'",
        "CREATE TABLE extra(x INTEGER)",
    ],
)
def test_full_open_rejects_old_native_or_outer_tamper_missing_history_and_unknown_schema(tmp_path, sql):
    path = tmp_path / "tamper.sqlite3"
    journal = create(path)
    transition(journal, "first", fold_actions(journal, [mark("m1"), cost("c1")], cursor=1))
    transition(journal, "second", fold_actions(journal, [mark("m2", 11)], cursor=2), at=11)
    checkpoint = journal.checkpoint()
    journal.close()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(sql)
    with pytest.raises(JournalError):
        reopen(path, checkpoint)


def test_create_only_wrong_identity_owner_steps_checkpoint_and_old_copy_not_adopted(tmp_path):
    path, old = tmp_path / "create.sqlite3", tmp_path / "old.sqlite3"
    journal = create(path)
    genesis = journal.checkpoint()
    with pytest.raises(FileExistsError):
        create(path)
    shutil.copyfile(path, old)
    transition(journal, "first", fold_actions(journal, [mark("m1")]))
    checkpoint = journal.checkpoint()
    journal.close()
    with pytest.raises(JournalError, match="checkpoint"):
        reopen(path, genesis)
    with pytest.raises(JournalError, match="checkpoint"):
        reopen(old, checkpoint)
    with pytest.raises(IdentityMismatch):
        reopen(path, checkpoint, owner_id="arm-b")
    with pytest.raises(IdentityMismatch):
        reopen(path, checkpoint, identity=replace(IDENTITY, campaign_id="different"))
    with pytest.raises(JournalError, match="configuration"):
        reopen(path, checkpoint, allowed_quantity_steps=(D("0.1"),))


@pytest.mark.parametrize(
    "limits,actions",
    [
        ({"max_native_event_rows": 1}, [mark("one"), mark("two", 11)]),
        ({"max_event_bytes": 512}, [mark("one"), cost("cost")]),
    ],
)
def test_explicit_native_and_atomic_byte_caps_rollback_without_eviction(tmp_path, limits, actions):
    journal = create(tmp_path / "bounds.sqlite3", **limits)
    checkpoint = journal.checkpoint()
    with pytest.raises(JournalFull):
        transition(journal, "too-large", fold_actions(journal, actions), at=11)
    assert journal.checkpoint() == checkpoint
    assert tuple(journal.native_events()) == ()
    journal.close()


def test_append_and_snapshot_never_count_or_replay_history_and_account_delta_is_structured(
    tmp_path, monkeypatch
):
    journal = create(tmp_path / "append.sqlite3")
    statements = []
    journal._connection.set_trace_callback(statements.append)

    def forbidden():
        raise AssertionError("ordinary append must not full-audit")

    monkeypatch.setattr(journal, "_audit", forbidden)
    transition(journal, "first", fold_actions(journal, [mark("m1"), cost("c1")]))
    transition(journal, "second", fold_actions(journal, [mark("m2", 11)]), at=11)
    journal.snapshot()
    assert not any("COUNT(" in sql.upper() for sql in statements)
    delta = json.loads(
        journal._connection.execute("SELECT delta_json FROM events WHERE version=2").fetchone()[0]
    )
    assert not any(op["path"] == ["account"] for op in delta["operations"])
    journal.close()


def test_allowed_distinct_quantity_steps_and_exact_owned_ledger_prefix(tmp_path):
    journal = create(tmp_path / "step.sqlite3")

    def fold(state):
        base = journal.ledger_reference()
        account = replace(load(journal, state), policy=replace(POLICY, quantity_step=D("0.01")))
        account = api.debit_cost(account, cost_id="cost", amount=D("1"), at_ms=10, kind="SERVICE")
        advanced = journal.ledger_reference()
        journal.validate_ledger_reference(base)
        journal.validate_ledger_reference(advanced)
        assert advanced.event_count == base.event_count + 1
        assert advanced.head_sha256 != base.head_sha256
        assert journal.lookup_native_event("cost").payload[0] == "SERVICE"
        store(journal, state, account)
        return "STEP_CHANGED"

    result = transition(journal, "step", fold)
    assert decode_account_core(result.snapshot.state["account"])[0].policy.quantity_step == D("0.01")
    journal.audit()
    journal.close()


def test_exact_native_audit_lookup_and_ledger_reference_have_no_outside_transaction_authority(tmp_path):
    journal = create(tmp_path / "audit-gate.sqlite3")
    with pytest.raises(JournalError, match="context"):
        journal.ledger_reference()
    with pytest.raises(JournalError, match="context"):
        journal.lookup_native_event("missing")
    transition(journal, "cost", fold_actions(journal, [cost("service")]))

    def audit_gate(state):
        assert journal.lookup_native_event("missing") is None
        assert journal.lookup_native_event("service").payload == ("SERVICE", D("1"), 10)
        return "AUDITED"

    transition(journal, "finish-gate", audit_gate)
    assert journal.checkpoint().native_count == 1
    journal.close()


def test_two_writers_are_fenced_and_outer_row_bound_does_not_invoke_fold(tmp_path):
    path = tmp_path / "writers.sqlite3"
    first = create(path, max_event_rows=1)
    checkpoint = first.checkpoint()
    second = reopen(path, checkpoint, max_event_rows=1)
    prior = second.snapshot()
    transition(first, "one", fold_actions(first, [mark("one")]))

    def never(_):
        raise AssertionError("fenced/full fold must not execute")

    with pytest.raises(OptimisticConflict):
        transition(second, "stale", never, snapshot=prior)
    with pytest.raises(JournalFull):
        transition(first, "full", never)
    first.close()
    second.close()


def test_sqlite_page_cap_preserves_complete_prior_prefix_and_no_failed_native_rows(tmp_path):
    journal = create(tmp_path / "pages.sqlite3", max_database_bytes=128 * 1024)
    exhausted = False
    for index in range(20):
        checkpoint = journal.checkpoint()
        try:
            transition(
                journal,
                f"cost:{index}",
                fold_actions(journal, [cost(f"cost:{index}")]),
                payload={"padding": "x" * 32_000, "index": index},
            )
        except JournalFull:
            exhausted = True
            assert journal.checkpoint() == checkpoint
            assert len(tuple(journal.native_events())) == checkpoint.native_count
            assert (
                journal.lookup(event_id=f"cost:{index}", payload={"padding": "x" * 32_000, "index": index})
                is None
            )
            break
    assert exhausted
    journal.audit()
    journal.close()


def test_invalid_create_bounds_preserve_no_destination_and_wrong_native_checkpoint_is_not_adopted(tmp_path):
    invalid = tmp_path / "invalid.sqlite3"
    with pytest.raises(ValueError):
        create(invalid, max_native_event_rows=0)
    assert not invalid.exists()
    path = tmp_path / "checkpoint.sqlite3"
    journal = create(path)
    transition(journal, "one", fold_actions(journal, [mark("one")]))
    checkpoint = journal.checkpoint()
    journal.close()
    with pytest.raises(JournalError, match="checkpoint"):
        reopen(path, replace(checkpoint, native_head="0" * 64))
    legacy = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(legacy)) as connection, connection:
        connection.execute("CREATE TABLE legacy(value TEXT)")
    with pytest.raises(JournalError, match="schema"):
        reopen(legacy, checkpoint)


def test_external_rehashed_middle_native_row_is_reaudited_before_native_duplicate_fold(tmp_path):
    path = tmp_path / "rehashed-native.sqlite3"
    journal = create(path)
    transition(journal, "first", fold_actions(journal, [mark("m1"), cost("c1")]))
    transition(journal, "second", fold_actions(journal, [mark("m2", 11)]), at=11)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.row_factory = sqlite3.Row
        row = dict(connection.execute("SELECT * FROM native_events WHERE ordinal=2").fetchone())
        row["event_json"] = canonical_native_event(api.AccountEvent("c1", ("SERVICE", D("2"), 10)))
        row["content_hash"] = _hash(row["event_json"])
        row["event_hash"] = financial_module._native_hash(row)
        connection.execute(
            "UPDATE native_events SET event_json=?,content_hash=?,event_hash=? WHERE ordinal=2",
            (row["event_json"], row["content_hash"], row["event_hash"]),
        )
    # The old current-tail-only check passes. Public operations must additionally
    # notice the external revision and validate the entire committed old prefix.
    journal._current()
    with pytest.raises(JournalError, match="native chain"):
        transition(journal, "replay-c1", fold_actions(journal, [cost("c1", "2")]), at=11)
    assert current_native_event_context() is None
    journal.close()


def test_external_rehashed_old_outer_duplicate_is_reaudited_before_acknowledgement(tmp_path):
    path = tmp_path / "rehashed-outer.sqlite3"
    journal = create(path)
    transition(journal, "first", fold_actions(journal, [mark("m1"), cost("c1")]))
    transition(journal, "second", fold_actions(journal, [mark("m2", 11)]), at=11)
    changed_payload = {"kind": "rewritten"}
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.row_factory = sqlite3.Row
        row = dict(connection.execute("SELECT * FROM events WHERE version=1").fetchone())
        row["payload_json"] = _canonical(changed_payload)
        row["payload_hash"] = _hash(row["payload_json"])
        row["outcome_json"] = _canonical({"invented": "outcome"})
        row["outcome_hash"] = _hash(row["outcome_json"])
        row["event_hash"] = financial_module._outer_hash(row)
        connection.execute(
            "UPDATE events SET payload_json=?,payload_hash=?,outcome_json=?,outcome_hash=?,event_hash=? "
            "WHERE version=1",
            tuple(
                row[key]
                for key in ("payload_json", "payload_hash", "outcome_json", "outcome_hash", "event_hash")
            ),
        )
    journal._current()
    with pytest.raises(JournalError, match="prefix"):
        journal.lookup(event_id="first", payload=changed_payload)
    journal.close()
