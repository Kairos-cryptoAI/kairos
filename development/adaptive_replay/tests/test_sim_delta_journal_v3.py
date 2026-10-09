"""Delta storage mechanics only: no source admission or portfolio economics."""

import json
import shutil
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from decimal import Decimal

import pytest

from adaptive_replay.sim_delta_journal_v3 import (
    DEFAULT_MAX_EVENT_ROWS,
    DeltaCheckpointV3,
    SimDeltaJournalV3,
    apply_delta,
    make_delta,
)
from adaptive_replay.sim_state_journal import (
    EventConflict,
    IdentityMismatch,
    JournalError,
    JournalFull,
    JournalIdentity,
    OptimisticConflict,
    SimStateJournal,
)

IDENTITY = JournalIdentity("delta-campaign", "retained-source", "unchanged-policy", "delta-impl")
LIMITS = {
    "max_event_rows": 50,
    "max_event_bytes": 100_000,
    "max_state_bytes": 1024 * 1024,
    "max_database_bytes": 8 * 1024 * 1024,
}


def create(path, *, initial=None, **limits):
    return SimDeltaJournalV3.create(
        path,
        identity=IDENTITY,
        initial_state={"cash": Decimal("1000.00"), "history": []} if initial is None else initial,
        initial_clock_ms=10,
        **(LIMITS | limits),
    )


def append(journal, event_id="one", *, state=None, prior=None, payload=None, at_ms=None, outcome=None):
    before = journal.snapshot() if prior is None else prior
    return journal.append(
        event_id=event_id,
        payload={"event": event_id} if payload is None else payload,
        outcome={"status": "RECORDED"} if outcome is None else outcome,
        state={"cash": "999.00", "history": [[event_id, "1.00"]]} if state is None else state,
        expected_version=before.version,
        expected_state_hash=before.state_hash,
        expected_head_sha256=before.head_hash,
        at_ms=before.last_clock_ms + 1 if at_ms is None else at_ms,
    )


def reopen(path, checkpoint, **limits):
    return SimDeltaJournalV3.open(
        path, identity=IDENTITY, expected_checkpoint=checkpoint, **(LIMITS | limits)
    )


def test_recursive_delta_is_exact_for_nested_maps_lists_and_boolean_numeric_types():
    before = {"a": {"deleted": 1, "history": [{"flag": True}, "old"]}, "ab": "KEEP", "empty": {}}
    after = {"a": {"history": [{"flag": 1}, "new", {"x": [None, False]}]}, "ab": "KEEP", "added": []}
    delta = make_delta(before, after)
    assert apply_delta(before, delta) == after
    assert before["a"]["history"][0]["flag"] is True
    assert type(apply_delta(before, delta)["a"]["history"][0]["flag"]) is int
    assert any(op["op"] == "APPEND" for op in delta["operations"])
    shorter = {"a": {"history": [{"flag": 1}]}, "ab": "KEEP", "added": []}
    assert apply_delta(after, make_delta(after, shorter)) == shorter


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "REMOVE", "path": []},
        {"op": "SET", "path": ["history", True], "value": 1},
        {"op": "APPEND", "path": ["history"], "values": []},
        {"op": "TRUNCATE", "path": ["history"], "length": True},
        {"op": "SET", "path": ["cash"], "value": "1", "unknown": 1},
    ],
)
def test_delta_rejects_unknown_fields_invalid_paths_and_root_loss(operation):
    with pytest.raises((JournalError, ValueError)):
        apply_delta({"cash": "1", "history": ["old"]}, {"operations": [operation]})


def test_differential_state_hash_against_old_full_state_journal(tmp_path):
    initial = {
        "account": {"cash": Decimal("1000.00"), "events": []},
        "slots": {},
        "liquidity": [],
        "funding": {},
    }
    old = SimStateJournal.create(
        tmp_path / "old.sqlite3",
        identity=IDENTITY,
        initial_state=initial,
        initial_clock_ms=10,
        max_event_rows=50,
        max_event_bytes=100_000,
    )
    new = create(tmp_path / "new.sqlite3", initial=initial)
    before_old, before_new = old.snapshot(), new.snapshot()
    states = [
        {
            "account": {"cash": "999.00", "events": [["entry", "0.2"]]},
            "slots": {"BTC:1": "CANDIDATE"},
            "liquidity": [["ASK", "100.5", "0.2"]],
            "funding": {},
        },
        {
            "account": {"cash": "999.00", "events": [["entry", "0.2"], ["partial-stop", "0.1"]]},
            "slots": {"BTC:1": "CANDIDATE", "ETH:1": "UNAVAILABLE"},
            "liquidity": [["ASK", "100.5", "0.2"]],
            "funding": {"BTC:1": ["UNAVAILABLE", None]},
        },
        {
            "account": {
                "cash": "998.98",
                "events": [["entry", "0.2"], ["partial-stop", "0.1"], ["late-funding", "-0.02"]],
            },
            "slots": {"BTC:1": "CANDIDATE", "ETH:1": "UNAVAILABLE"},
            "liquidity": [["ASK", "100.5", "0.2"]],
            "funding": {"BTC:1": ["SETTLED", "-0.02"]},
        },
    ]
    try:
        for index, state in enumerate(states, 1):
            payload, outcome = {"index": index}, {"status": "RECORDED", "index": index}
            result_old = old.append(
                event_id=f"e:{index}",
                payload=payload,
                outcome=outcome,
                state=state,
                expected_version=before_old.version,
                expected_state_hash=before_old.state_hash,
                at_ms=10 + index,
            )
            result_new = append(
                new,
                f"e:{index}",
                payload=payload,
                outcome=outcome,
                state=state,
                prior=before_new,
                at_ms=10 + index,
            )
            before_old, before_new = result_old.snapshot, result_new.snapshot
            assert before_old.state == before_new.state == state
            assert before_old.state_hash == before_new.state_hash
            assert result_old.outcome == result_new.outcome
        assert new.audit() == before_new
        stored = json.loads(
            new._connection.execute("SELECT delta_json FROM events WHERE version=3").fetchone()[0]
        )
        assert "partial-stop" not in json.dumps(stored)  # append never repeats the retained history
        assert "state_json" not in {r[1] for r in new._connection.execute("PRAGMA table_info(events)")}
    finally:
        old.close()
        new.close()


def test_indexed_projection_handles_escaped_keys_deletion_and_list_append(tmp_path):
    journal = create(
        tmp_path / "paths.sqlite3", initial={"a": {"remove": [1, 2]}, "ab": "KEEP", 'x%,"\\': {"z": []}}
    )
    try:
        state = {"a": {}, "ab": "KEEP", 'x%,"\\': {"z": [{"nested": "retained"}]}}
        append(journal, state=state)
        assert journal.snapshot().state == state
        assert (
            journal._connection.execute(
                "SELECT COUNT(*) FROM projection WHERE path LIKE '%remove%'"
            ).fetchone()[0]
            == 0
        )
    finally:
        journal.close()


def test_restart_exact_checkpoint_duplicate_returns_old_outcome_and_latest_state(tmp_path):
    path = tmp_path / "restart.sqlite3"
    journal = create(path)
    first = append(journal)
    latest = append(
        journal,
        "two",
        state={"cash": "998.00", "history": [["one", "1"], ["two", "1"]]},
        prior=first.snapshot,
    )
    checkpoint = journal.checkpoint()
    journal.close()
    journal = reopen(path, checkpoint)
    try:
        duplicate = append(
            journal,
            prior=first.snapshot,
            state={"DO_NOT_APPLY": True},
            at_ms=11,
            outcome={"DO_NOT_RETURN": True},
        )
        assert duplicate.replayed and duplicate.outcome == first.outcome
        assert duplicate.snapshot == latest.snapshot
        assert journal.lookup(event_id="one", payload={"event": "one"}).snapshot == latest.snapshot
        with pytest.raises(EventConflict):
            append(journal, payload={"conflict": True})
        assert journal.snapshot() == latest.snapshot
    finally:
        journal.close()


def test_old_copy_wrong_head_and_wrong_identity_are_not_adopted(tmp_path):
    path, old_path = tmp_path / "current.sqlite3", tmp_path / "older.sqlite3"
    journal = create(path)
    older = journal.checkpoint()
    shutil.copyfile(path, old_path)
    append(journal)
    current = journal.checkpoint()
    journal.close()
    with pytest.raises(JournalError):
        reopen(old_path, current)
    with pytest.raises(JournalError):
        reopen(path, older)
    with pytest.raises(JournalError):
        reopen(path, replace(current, head_hash="b" * 64))
    with pytest.raises(IdentityMismatch):
        SimDeltaJournalV3.open(
            path, identity=replace(IDENTITY, campaign_id="other"), expected_checkpoint=current, **LIMITS
        )
    with pytest.raises(TypeError):
        reopen(path, current.__dict__)
    assert isinstance(current, DeltaCheckpointV3)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE events SET payload_json='{}' WHERE version=1",
        "UPDATE events SET outcome_json='null' WHERE version=1",
        "UPDATE events SET delta_json='{\"operations\":[]}' WHERE version=1",
        "UPDATE events SET state_hash=printf('%064d',0) WHERE version=1",
        "DELETE FROM events WHERE version=1",
        "UPDATE projection SET value_json='\"FORGED\"' WHERE path='[\"cash\"]'",
        "UPDATE head SET last_clock_ms=0",
        "CREATE TABLE unexpected(x TEXT)",
    ],
)
def test_open_rejects_tampering_truncation_projection_and_unknown_schema(tmp_path, sql):
    path = tmp_path / "tamper.sqlite3"
    journal = create(path)
    append(journal)
    checkpoint = journal.checkpoint()
    journal.close()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(sql)
    with pytest.raises((JournalError, ValueError)):
        reopen(path, checkpoint)


def test_full_audit_catches_older_event_corruption_not_just_current_tail(tmp_path):
    path = tmp_path / "older-event.sqlite3"
    journal = create(path)
    append(journal)
    append(journal, "two")
    current, checkpoint = journal.snapshot(), journal.checkpoint()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("UPDATE events SET delta_json='{\"operations\":[]}' WHERE version=1")
    try:
        assert journal.snapshot() == current  # current/tail validation is intentionally not full replay
        with pytest.raises(JournalError):
            journal.audit()
    finally:
        journal.close()
    with pytest.raises(JournalError):
        reopen(path, checkpoint)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE projection SET value_json='\"FORGED\"' WHERE path='[\"cash\"]'",
        "UPDATE events SET outcome_json='null' WHERE version=1",
    ],
)
def test_snapshot_immediately_detects_projection_or_current_tail_corruption(tmp_path, sql):
    path = tmp_path / "current-corrupt.sqlite3"
    journal = create(path)
    append(journal)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(sql)
    try:
        with pytest.raises(JournalError):
            journal.snapshot()
    finally:
        journal.close()


def test_normal_snapshot_checkpoint_lookup_and_append_do_not_replay_old_history(tmp_path, monkeypatch):
    journal = create(tmp_path / "normal-api.sqlite3")

    def forbidden_audit():
        raise AssertionError("normal operations must not replay the full old chain")

    monkeypatch.setattr(journal, "_audit", forbidden_audit)
    try:
        before = journal.snapshot()
        assert journal.checkpoint().version == 0
        latest = append(journal, prior=before)
        assert journal.snapshot() == latest.snapshot
        assert journal.lookup(event_id="one", payload={"event": "one"}).replayed
        assert journal.checkpoint().version == 1
    finally:
        journal.close()


def test_same_instance_serializes_checkpoint_handoff_after_commit(tmp_path, monkeypatch):
    journal = create(tmp_path / "same-owner.sqlite3")
    before = journal.snapshot()
    original_checkpoint = journal._checkpoint
    committed, release, second_started = threading.Event(), threading.Event(), threading.Event()

    def delayed_checkpoint(snapshot):
        if snapshot.version == 1 and threading.current_thread().name.startswith("delta-owner"):
            committed.set()
            if not release.wait(5):
                raise AssertionError("checkpoint handoff test timed out")
        return original_checkpoint(snapshot)

    def second_append():
        second_started.set()
        return append(journal, "two")

    monkeypatch.setattr(journal, "_checkpoint", delayed_checkpoint)
    try:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="delta-owner") as executor:
            first = executor.submit(append, journal, "one", prior=before)
            try:
                assert committed.wait(5)
                second = executor.submit(second_append)
                assert second_started.wait(5)
                assert not second.done()  # it cannot overtake a committed but unhanded checkpoint
            finally:
                release.set()
            assert first.result(timeout=5).snapshot.version == 1
            assert second.result(timeout=5).snapshot.version == 2
        assert journal.checkpoint().version == journal._retained_checkpoint.version == 2
    finally:
        release.set()
        journal.close()


@pytest.mark.parametrize("limit,huge", [("max_state_bytes", 400), ("max_event_bytes", 400)])
def test_canonical_state_and_delta_caps_do_not_commit_or_reset_prior_state(tmp_path, limit, huge):
    journal = create(tmp_path / f"{limit}.sqlite3", **{limit: huge})
    try:
        before = journal.snapshot()
        with pytest.raises(JournalFull):
            append(journal, state={"cash": "1", "history": ["x" * 2000]}, prior=before)
        assert journal.snapshot() == before
        assert journal._connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    finally:
        journal.close()


def test_sqlite_database_cap_rolls_back_event_and_projection(tmp_path):
    journal = create(tmp_path / "database-cap.sqlite3", max_database_bytes=32 * 1024)
    try:
        before = journal.snapshot()
        with pytest.raises(JournalFull):
            append(journal, state={"cash": "1", "history": ["x" * 20_000]}, prior=before)
        assert journal.snapshot() == before
        assert journal.path.stat().st_size <= 32 * 1024
    finally:
        journal.close()


def test_write_failure_after_event_and_projection_changes_rolls_back(tmp_path):
    journal = create(tmp_path / "rollback.sqlite3")
    before = journal.snapshot()

    def deny_head(action, table, _column, _database, _trigger):
        return (
            sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_UPDATE and table == "head" else sqlite3.SQLITE_OK
        )

    try:
        journal._connection.set_authorizer(deny_head)
        with pytest.raises(sqlite3.DatabaseError):
            append(journal, prior=before)
        journal._connection.set_authorizer(None)
        assert journal.snapshot() == before
        assert journal._connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        checkpoint = journal.checkpoint()
    finally:
        journal.close()
    reopened = reopen(tmp_path / "rollback.sqlite3", checkpoint)
    reopened.close()


def test_two_owners_version_and_head_fences_and_row_cap(tmp_path):
    path = tmp_path / "owners.sqlite3"
    first = create(path, max_event_rows=1)
    before = first.snapshot()
    second = reopen(path, first.checkpoint(), max_event_rows=1)
    try:
        latest = append(first, prior=before)
        with pytest.raises(OptimisticConflict):
            append(second, "other-owner", prior=before)
        assert second.snapshot() == latest.snapshot
        with pytest.raises(OptimisticConflict):
            second.append(
                event_id="wrong-head",
                payload={},
                outcome={},
                state=latest.snapshot.state,
                expected_version=latest.snapshot.version,
                expected_state_hash=latest.snapshot.state_hash,
                expected_head_sha256="c" * 64,
                at_ms=12,
            )
        with pytest.raises(JournalFull):
            append(first, "next", prior=latest.snapshot)
        assert first.snapshot() == latest.snapshot
    finally:
        first.close()
        second.close()


def test_create_only_no_old_schema_adoption_and_numeric_rules(tmp_path):
    path = tmp_path / "create.sqlite3"
    journal = create(path)
    checkpoint = journal.checkpoint()
    try:
        with pytest.raises(FileExistsError):
            create(path)
        with pytest.raises(ValueError):
            append(journal, state={"float": 1.5})
    finally:
        journal.close()
    old = SimStateJournal.create(
        tmp_path / "old.sqlite3", identity=IDENTITY, initial_state={}, initial_clock_ms=10, max_event_rows=50
    )
    old.close()
    with pytest.raises(JournalError):
        reopen(tmp_path / "old.sqlite3", checkpoint)


def test_complete_five_day_36000_cell_and_candle_storage_scale(tmp_path, request):
    """Twenty-four bounded batches test storage, NOT intraminute execution.

    The entire 7,200-minute/five-symbol denominator and 36,000 causal candle
    records survive together with partial exposure, consumed liquidity and
    unresolved funding. Batching does not claim a continuous portfolio run.
    Actual file size and elapsed time are recorded without a flaky speed gate.
    """
    path = tmp_path / "five-day.sqlite3"
    start_ms, minute, source_sha = 86_400_000, 60_000, "a" * 64
    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT")
    state = {
        "slots": {},
        "candles": {},
        "cursor": 0,
        "sources": {"market": source_sha},
        "account": {
            "cash": "999.98",
            "exposures": [["BTCUSDT", "0.2"]],
            "fills": [["partial-entry", "0.2"]],
            "natural_exits": [],
        },
        "liquidity": {"BTCUSDT": {"consumed": [["ASK", "100.5", "0.2"]]}},
        "funding": {"BTCUSDT:funding-due": {"status": "UNAVAILABLE", "cashflow": None}},
    }
    started = time.perf_counter()
    journal = SimDeltaJournalV3.create(
        path, identity=IDENTITY, initial_state=state, initial_clock_ms=start_ms
    )
    prior = journal.snapshot()
    try:
        for batch, offset in enumerate(range(0, 36_000, 1500), 1):
            for ordinal in range(offset, offset + 1500):
                open_ms = start_ms + ordinal // 5 * minute
                key = f"{symbols[ordinal % 5]}:{open_ms}"
                state["slots"][key] = "QUIET"
                state["candles"][key] = {"close": "100.00", "available": open_ms + minute}
            state["cursor"] = offset + 1500
            result = journal.append(
                event_id=f"batch:{batch}",
                payload={"first": offset + 1, "last": offset + 1500},
                outcome={"status": "RECORDED"},
                state=state,
                expected_version=prior.version,
                expected_state_hash=prior.state_hash,
                expected_head_sha256=prior.head_hash,
                at_ms=start_ms + (offset + 1500) // 5 * minute,
            )
            prior = result.snapshot
        assert len(prior.state["slots"]) == len(prior.state["candles"]) == 36_000
        assert prior.last_clock_ms - start_ms == 5 * 86_400_000
        assert prior.state["account"]["exposures"] == [["BTCUSDT", "0.2"]]
        assert prior.state["liquidity"]["BTCUSDT"]["consumed"] == [["ASK", "100.5", "0.2"]]
        assert prior.state["funding"]["BTCUSDT:funding-due"]["status"] == "UNAVAILABLE"
        checkpoint = journal.checkpoint()
        delta_bytes = journal._connection.execute(
            "SELECT SUM(length(CAST(delta_json AS BLOB))) FROM events"
        ).fetchone()[0]
        assert journal.max_event_rows == DEFAULT_MAX_EVENT_ROWS == 512_192
    finally:
        journal.close()
    reopened = SimDeltaJournalV3.open(path, identity=IDENTITY, expected_checkpoint=checkpoint)
    try:
        assert reopened.snapshot() == prior
    finally:
        reopened.close()
    actual_bytes, seconds = path.stat().st_size, time.perf_counter() - started
    metrics = {
        "cells": 36_000,
        "candles": 36_000,
        "events": 24,
        "database_bytes": actual_bytes,
        "delta_bytes": delta_bytes,
        "elapsed_seconds": round(seconds, 3),
    }
    request.node.user_properties.append(("five_day_storage_metrics", json.dumps(metrics, sort_keys=True)))
    print("five_day_storage_metrics=" + json.dumps(metrics, sort_keys=True))
    assert actual_bytes < 64 * 1024 * 1024
    assert delta_bytes < 16 * 1024 * 1024
