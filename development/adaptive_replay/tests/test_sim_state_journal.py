import os
import sqlite3
from decimal import Decimal as D

import pytest

from adaptive_replay.sim_state_journal import (
    DEFAULT_MAX_DATABASE_BYTES,
    EventConflict,
    IdentityMismatch,
    JournalError,
    JournalFull,
    JournalIdentity,
    OptimisticConflict,
    SimStateJournal,
)

IDENTITY = JournalIdentity("campaign-a", "capture-a", "policy-a", "impl-a")


def create(path, *, rows=10, bytes_per_event=100_000):
    return SimStateJournal.create(
        path,
        identity=IDENTITY,
        initial_state={"cash": D("1000.00"), "positions": []},
        initial_clock_ms=10,
        max_event_rows=rows,
        max_event_bytes=bytes_per_event,
    )


def append(journal, event_id, *, expected=None, at_ms=11, state=None, payload=None, outcome=None):
    prior = expected or journal.snapshot()
    return journal.append(
        event_id=event_id,
        payload=payload or {"kind": "MARK", "price": D("100.25")},
        outcome=outcome or {"status": "RECORDED", "sequence": prior.version + 1},
        state=state or {"cash": D("999.75"), "positions": []},
        expected_version=prior.version,
        expected_state_hash=prior.state_hash,
        at_ms=at_ms,
    )


def test_create_only_decimal_canonicalization_and_restart_validation(tmp_path):
    path = tmp_path / "sim.sqlite3"
    journal = create(path)
    initial = journal.snapshot()
    assert initial.version == 0
    assert initial.state == {"cash": "1000.00", "positions": []}
    result = append(journal, "e-1")
    assert result.snapshot.version == 1
    assert result.snapshot.state["cash"] == "999.75"
    journal.close()

    with pytest.raises(FileExistsError):
        create(path)
    reopened = SimStateJournal.open(path, identity=IDENTITY, max_event_rows=10, max_event_bytes=100_000)
    assert reopened.snapshot() == result.snapshot
    reopened.close()


def test_transaction_failure_after_event_insert_rolls_back_and_restart_is_clean(tmp_path):
    path = tmp_path / "rollback.sqlite3"
    journal = create(path)
    start = journal.snapshot()

    def deny_head_update(action, table, _column, _database, _trigger):
        if action == sqlite3.SQLITE_UPDATE and table == "head":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    journal._connection.set_authorizer(deny_head_update)
    with pytest.raises(sqlite3.DatabaseError):
        append(journal, "never-committed")
    journal._connection.set_authorizer(None)
    assert journal.snapshot() == start
    journal.close()

    reopened = SimStateJournal.open(path, identity=IDENTITY, max_event_rows=10, max_event_bytes=100_000)
    assert reopened.snapshot() == start
    assert append(reopened, "never-committed").snapshot.version == 1
    reopened.close()


def test_duplicate_after_restart_returns_historical_outcome_and_current_state(tmp_path):
    path = tmp_path / "duplicate.sqlite3"
    journal = create(path)
    first = append(journal, "event-1", outcome={"result": "first-outcome"})
    second = append(
        journal,
        "event-2",
        at_ms=12,
        state={"cash": D("999.50"), "positions": []},
        payload={"kind": "FEE", "amount": D("0.25")},
    )
    journal.close()

    reopened = SimStateJournal.open(path, identity=IDENTITY, max_event_rows=10, max_event_bytes=100_000)
    replay = reopened.append(
        event_id="event-1",
        payload={"kind": "MARK", "price": D("100.25")},
        outcome={"ignored": True},
        state={"ignored": True},
        expected_version=0,
        expected_state_hash=first.snapshot.state_hash,
        at_ms=10,
    )
    assert replay.replayed
    assert replay.outcome == {"result": "first-outcome"}
    assert replay.snapshot == second.snapshot
    reopened.close()


def test_event_id_payload_conflict_and_optimistic_race_fail_closed(tmp_path):
    path = tmp_path / "race.sqlite3"
    left = create(path)
    right = SimStateJournal.open(path, identity=IDENTITY, max_event_rows=10, max_event_bytes=100_000)
    common = left.snapshot()
    append(left, "winner", expected=common)
    with pytest.raises(OptimisticConflict):
        append(right, "loser", expected=common)
    with pytest.raises(EventConflict):
        append(left, "winner", payload={"kind": "DIFFERENT"})
    left.close()
    right.close()


def test_clock_monotonicity_and_capacity_are_enforced(tmp_path):
    path = tmp_path / "bounded.sqlite3"
    journal = create(path, rows=1)
    with pytest.raises(JournalError, match="clock regressed"):
        append(journal, "old-clock", at_ms=9)
    append(journal, "only-row")
    with pytest.raises(JournalFull):
        append(journal, "second-row", at_ms=12)
    journal.close()


def test_event_bytes_and_json_numeric_policy_are_bounded(tmp_path):
    journal = create(tmp_path / "size.sqlite3", bytes_per_event=100)
    with pytest.raises(JournalError, match="exceeds max_event_bytes"):
        append(journal, "large", payload={"body": "x" * 200})
    with pytest.raises(ValueError, match="float values"):
        append(journal, "float", payload={"bad": 0.1})
    with pytest.raises(ValueError, match="non-finite"):
        append(journal, "nonfinite", payload={"bad": D("NaN")})
    journal.close()


@pytest.mark.parametrize("corruption", ["state", "head", "clock", "chain"])
def test_restart_rejects_corrupt_projection_chain_and_clock(tmp_path, corruption):
    path = tmp_path / f"corrupt-{corruption}.sqlite3"
    journal = create(path)
    append(journal, "event-1")
    journal.close()
    connection = sqlite3.connect(path)
    if corruption == "state":
        connection.execute("UPDATE events SET state_json='{}' WHERE version=1")
    elif corruption == "head":
        connection.execute("UPDATE head SET state_json='{}' WHERE singleton=1")
    elif corruption == "clock":
        connection.execute("UPDATE events SET clock_ms=1 WHERE version=1")
    else:
        connection.execute("UPDATE events SET previous_hash=? WHERE version=1", ("f" * 64,))
    connection.commit()
    connection.close()
    with pytest.raises(JournalError):
        SimStateJournal.open(path, identity=IDENTITY, max_event_rows=10, max_event_bytes=100_000)


@pytest.mark.parametrize("unknown", ["sqlite-user-version", "metadata-version"])
def test_open_rejects_unknown_schema_version(tmp_path, unknown):
    path = tmp_path / f"schema-{unknown}.sqlite3"
    journal = create(path)
    journal.close()
    connection = sqlite3.connect(path)
    if unknown == "sqlite-user-version":
        connection.execute("PRAGMA user_version=99")
    else:
        connection.execute("UPDATE metadata SET value='99' WHERE key='schema_version'")
    connection.commit()
    connection.close()
    with pytest.raises(JournalError, match="schema version|configuration mismatch"):
        SimStateJournal.open(path, identity=IDENTITY, max_event_rows=10, max_event_bytes=100_000)


def test_open_requires_matching_identity_and_configuration(tmp_path):
    path = tmp_path / "identity.sqlite3"
    journal = create(path)
    journal.close()
    with pytest.raises(IdentityMismatch):
        SimStateJournal.open(
            path,
            identity=JournalIdentity("other", "capture-a", "policy-a", "impl-a"),
            max_event_rows=10,
            max_event_bytes=100_000,
        )
    with pytest.raises(JournalError, match="configuration mismatch"):
        SimStateJournal.open(path, identity=IDENTITY, max_event_rows=9, max_event_bytes=100_000)


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE injected(value TEXT)",
        "CREATE INDEX injected ON events(event_id)",
        "CREATE TRIGGER injected AFTER INSERT ON events BEGIN SELECT 1; END",
    ],
)
def test_open_rejects_any_non_whitelisted_schema_object(tmp_path, ddl):
    path = tmp_path / "extra-schema.sqlite3"
    journal = create(path)
    journal.close()
    connection = sqlite3.connect(path)
    connection.execute(ddl)
    connection.commit()
    connection.close()
    before = path.read_bytes()

    with pytest.raises(JournalError, match="schema objects"):
        SimStateJournal.open(path, identity=IDENTITY, max_event_rows=10, max_event_bytes=100_000)
    assert path.read_bytes() == before


def test_create_failure_preserves_partial_artifact_without_delete_or_resume(tmp_path, monkeypatch):
    path = tmp_path / "partial.sqlite3"
    monkeypatch.setattr(
        "adaptive_replay.sim_state_journal._SCHEMA",
        "CREATE TABLE partial(value TEXT); CREATE TABLE partial(value TEXT);",
    )
    with pytest.raises(sqlite3.OperationalError):
        create(path)
    assert path.exists()
    original = path.read_bytes()
    assert original
    monkeypatch.undo()
    with pytest.raises(FileExistsError):
        create(path)
    assert path.read_bytes() == original


@pytest.mark.skipif(not hasattr(os, "link"), reason="hard-link creation unavailable")
def test_create_and_open_refuse_symlink_and_hardlink_path_aliases(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    directory_link = tmp_path / "dir-alias"
    file_link = tmp_path / "file-alias.sqlite3"
    hardlink = tmp_path / "hardlink.sqlite3"
    try:
        directory_link.symlink_to(real_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        directory_link = None

    journal_path = real_dir / "journal.sqlite3"
    journal = create(journal_path)
    journal.close()
    try:
        os.link(journal_path, hardlink)
    except OSError:
        pytest.skip("hard-link creation is not permitted")
    with pytest.raises(JournalError, match="aliased"):
        SimStateJournal.open(hardlink, identity=IDENTITY, max_event_rows=10, max_event_bytes=100_000)
    if directory_link is not None:
        with pytest.raises(JournalError, match="symlink/reparse"):
            create(directory_link / "new.sqlite3")
        try:
            file_link.symlink_to(journal_path)
        except (OSError, NotImplementedError):
            pass
        else:
            with pytest.raises(JournalError, match="aliased"):
                SimStateJournal.open(file_link, identity=IDENTITY, max_event_rows=10, max_event_bytes=100_000)


def test_database_byte_bound_is_persisted_and_enforced_at_open(tmp_path):
    path = tmp_path / "db-bound.sqlite3"
    bound = 32 * 1024
    journal = SimStateJournal.create(
        path,
        identity=IDENTITY,
        initial_state={"state": "x"},
        initial_clock_ms=10,
        max_event_rows=10,
        max_event_bytes=10_000,
        max_database_bytes=bound,
    )
    assert path.stat().st_size <= bound
    assert journal._connection.execute(
        "SELECT value FROM metadata WHERE key='max_database_bytes'"
    ).fetchone()[0] == str(bound)
    assert DEFAULT_MAX_DATABASE_BYTES == 64 * 1024 * 1024
    with pytest.raises(JournalError, match="configuration mismatch"):
        SimStateJournal.open(
            path,
            identity=IDENTITY,
            max_event_rows=10,
            max_event_bytes=10_000,
            max_database_bytes=bound * 2,
        )
    current = journal.snapshot()
    state = {"blob": "x" * 8_000}
    with pytest.raises((JournalFull, sqlite3.DatabaseError)):
        journal.append(
            event_id="database-growth",
            payload={"kind": "TEST"},
            outcome={"status": "TEST"},
            state=state,
            expected_version=current.version,
            expected_state_hash=current.state_hash,
            at_ms=11,
        )
    assert path.stat().st_size <= bound
    assert journal.snapshot() == current
    journal.close()


def test_read_only_duplicate_lookup_returns_outcome_and_latest_snapshot_before_reducer(tmp_path):
    journal = create(tmp_path / "lookup.sqlite3")
    original = append(journal, "already-seen", outcome={"fill": "TEST-only"})
    latest = append(journal, "later-event", at_ms=12, state={"cash": D("999.50"), "positions": []})
    reducer_calls = []

    def fake_fresh_runner(event_id, payload):
        prior = journal.lookup(event_id=event_id, payload=payload)
        if prior is not None:
            return prior
        reducer_calls.append(event_id)
        return append(journal, event_id, payload=payload, at_ms=13)

    result = fake_fresh_runner("already-seen", {"kind": "MARK", "price": D("100.25")})
    assert result.replayed is True
    assert result.outcome == {"fill": "TEST-only"}
    assert result.snapshot == latest.snapshot
    assert reducer_calls == []
    assert original.snapshot.version == 1

    with pytest.raises(EventConflict):
        journal.lookup(event_id="already-seen", payload={"kind": "DIFFERENT"})
    assert fake_fresh_runner("new-event", {"kind": "TEST_NEW"}).snapshot.version == 3
    assert reducer_calls == ["new-event"]
    journal.close()
