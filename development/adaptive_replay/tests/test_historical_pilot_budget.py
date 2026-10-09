from __future__ import annotations

import hashlib
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

from adaptive_replay import historical_pilot_budget as budget

PLAN = Path(__file__).parents[1] / "historical-episodes-draft.json"
PLAN_SHA256 = hashlib.sha256(PLAN.read_bytes()).hexdigest()
LEDGER_UUID = "f30e5e27-57f0-44b6-9e4c-544d4db529c7"


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "Kairos"
    repo = workspace / "kairos"
    adaptive = repo / "development" / "adaptive_replay"
    adaptive.mkdir(parents=True)
    (workspace / "runtime").mkdir()
    (repo / ".git").mkdir()
    (adaptive / "historical-episodes-draft.json").write_bytes(PLAN.read_bytes())
    return workspace


def _create(workspace: Path, *, ledger_uuid: str = LEDGER_UUID) -> budget.PilotBudget:
    return budget.create_new_ledger(
        workspace / "runtime" / "pilot-budget.sqlite",
        ledger_uuid=ledger_uuid,
        plan_sha256=PLAN_SHA256,
        slot_ids=budget.ALLOWED_SLOT_IDS,
    )


def _reopen(path: Path, *, ledger_uuid: str = LEDGER_UUID) -> budget.PilotBudget:
    return budget.open_existing_ledger(
        path,
        ledger_uuid=ledger_uuid,
        plan_sha256=PLAN_SHA256,
        slot_ids=budget.ALLOWED_SLOT_IDS,
    )


def test_frozen_pilot_binding_and_empty_ledger_are_explicit_and_not_dispatch_ready(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    ledger = _create(workspace)
    state = ledger.snapshot()
    assert len(budget.ALLOWED_SLOT_IDS) == budget.MAX_ATTEMPTS == 20
    assert len(set(budget.ALLOWED_SLOT_IDS)) == 20
    assert budget.CEILING_MICRO_USD == 1_000_000
    assert state == {
        "schema": budget.SCHEMA,
        "ledger_uuid": LEDGER_UUID,
        "pilot_plan_sha256": PLAN_SHA256,
        "ceiling_micro_usd": 1_000_000,
        "max_attempts": 20,
        "slot_admissions": 0,
        "committed_micro_usd": 0,
        "held_reservation_micro_usd": 0,
        "committed_plus_held_micro_usd": 0,
        "sealed": False,
        "seal_reason": None,
        "paid_dispatch_ready": False,
    }
    assert _reopen(ledger.path).snapshot() == state


def test_every_slot_is_one_shot_and_twenty_requests_fit_exact_cap(tmp_path: Path) -> None:
    ledger = _create(_workspace(tmp_path))
    for slot in budget.ALLOWED_SLOT_IDS:
        state = ledger.reserve_attempt(slot, 50_000)
        assert state["slot_admissions"] <= 20
        with pytest.raises(ValueError, match="already consumed"):
            ledger.reserve_attempt(slot, 1)
    final = ledger.snapshot()
    assert final["slot_admissions"] == 20
    assert final["held_reservation_micro_usd"] == 1_000_000
    assert final["committed_micro_usd"] == 0
    assert final["paid_dispatch_ready"] is False


def test_concurrent_duplicate_slot_race_admits_exactly_one_attempt(tmp_path: Path) -> None:
    ledger = _create(_workspace(tmp_path))
    slot = budget.ALLOWED_SLOT_IDS[0]

    def reserve(_: int) -> str:
        try:
            ledger.reserve_attempt(slot, 75_000)
            return "admitted"
        except ValueError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=12) as pool:
        outcomes = list(pool.map(reserve, range(24)))
    assert outcomes.count("admitted") == 1
    assert outcomes.count("rejected") == 23
    assert ledger.snapshot()["slot_admissions"] == 1
    assert ledger.snapshot()["held_reservation_micro_usd"] == 75_000


def test_concurrent_money_cap_race_never_admits_over_ceiling(tmp_path: Path) -> None:
    ledger = _create(_workspace(tmp_path))

    def reserve(slot: str) -> str:
        try:
            ledger.reserve_attempt(slot, 50_001)
            return "admitted"
        except ValueError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=20) as pool:
        outcomes = list(pool.map(reserve, budget.ALLOWED_SLOT_IDS))
    state = ledger.snapshot()
    assert outcomes.count("admitted") == 19
    assert outcomes.count("rejected") == 1
    assert state["slot_admissions"] == 19
    assert state["committed_plus_held_micro_usd"] == 19 * 50_001
    assert state["committed_plus_held_micro_usd"] <= budget.CEILING_MICRO_USD


def test_unknown_or_unsettled_attempt_stays_held_across_reopen(tmp_path: Path) -> None:
    ledger = _create(_workspace(tmp_path))
    ledger.reserve_attempt(budget.ALLOWED_SLOT_IDS[0], 123_456)
    state = _reopen(ledger.path).snapshot()
    assert state["slot_admissions"] == 1
    assert state["committed_micro_usd"] == 0
    assert state["held_reservation_micro_usd"] == 123_456
    assert state["committed_plus_held_micro_usd"] == 123_456


def test_known_settlement_releases_unused_reserve_idempotently_without_releasing_slot(tmp_path: Path) -> None:
    ledger = _create(_workspace(tmp_path))
    slot, next_slot = budget.ALLOWED_SLOT_IDS[:2]
    ledger.reserve_attempt(slot, 100_000)
    settled = ledger.settle_known_cost(slot, 25_000)
    assert settled["slot_admissions"] == 1
    assert settled["committed_micro_usd"] == 25_000
    assert settled["held_reservation_micro_usd"] == 0
    assert ledger.settle_known_cost(slot, 25_000) == settled
    with pytest.raises(ValueError, match="conflicts"):
        ledger.settle_known_cost(slot, 24_999)
    next_state = ledger.reserve_attempt(next_slot, 975_000)
    assert next_state["slot_admissions"] == 2
    assert next_state["committed_plus_held_micro_usd"] == budget.CEILING_MICRO_USD
    with pytest.raises(ValueError, match="already consumed"):
        ledger.reserve_attempt(slot, 1)


def test_zero_known_cost_is_recorded_but_attempt_slot_stays_consumed(tmp_path: Path) -> None:
    ledger = _create(_workspace(tmp_path))
    slot = budget.ALLOWED_SLOT_IDS[0]
    ledger.reserve_attempt(slot, 1)
    settled = ledger.settle_known_cost(slot, 0)
    assert settled["slot_admissions"] == 1
    assert settled["committed_micro_usd"] == 0
    assert settled["held_reservation_micro_usd"] == 0
    with pytest.raises(ValueError, match="already consumed"):
        ledger.reserve_attempt(slot, 1)


def test_observed_overrun_is_durable_and_seals_all_future_admission(tmp_path: Path) -> None:
    ledger = _create(_workspace(tmp_path))
    slot = budget.ALLOWED_SLOT_IDS[0]
    ledger.reserve_attempt(slot, 100_000)
    state = ledger.settle_known_cost(slot, 100_001)
    assert state["committed_micro_usd"] == 100_001
    assert state["held_reservation_micro_usd"] == 0
    assert state["sealed"] is True
    assert state["seal_reason"] == f"observed_cost_overrun:{slot}"
    with pytest.raises(ValueError, match="sealed"):
        ledger.reserve_attempt(budget.ALLOWED_SLOT_IDS[1], 1)
    assert _reopen(ledger.path).snapshot() == state


def test_extremely_large_observed_overrun_is_exactly_recorded_and_seals(tmp_path: Path) -> None:
    ledger = _create(_workspace(tmp_path))
    slot = budget.ALLOWED_SLOT_IDS[0]
    ledger.reserve_attempt(slot, 1)
    observed = 10**100
    state = ledger.settle_known_cost(slot, observed)
    assert state["committed_micro_usd"] == observed
    assert state["sealed"] is True
    assert _reopen(ledger.path).snapshot() == state


def test_multiple_prior_held_settlements_survive_seal_and_reopen(tmp_path: Path) -> None:
    ledger = _create(_workspace(tmp_path))
    first, second, third, unused = budget.ALLOWED_SLOT_IDS[:4]
    for slot in (first, second, third):
        ledger.reserve_attempt(slot, 100)

    first_state = ledger.settle_known_cost(first, 101)
    assert first_state["sealed"] is True
    assert first_state["seal_reason"] == f"observed_cost_overrun:{first}"

    second_state = ledger.settle_known_cost(second, 102)
    assert second_state["sealed"] is True
    assert second_state["seal_reason"] == f"observed_cost_overrun:{first}"
    assert second_state["committed_micro_usd"] == 203
    assert second_state["held_reservation_micro_usd"] == 100

    final = ledger.settle_known_cost(third, 90)
    assert final["committed_micro_usd"] == 293
    assert final["held_reservation_micro_usd"] == 0
    assert final["seal_reason"] == f"observed_cost_overrun:{first}"
    with pytest.raises(ValueError, match="sealed"):
        ledger.reserve_attempt(unused, 1)

    reopened = _reopen(ledger.path)
    assert reopened.snapshot() == final
    assert reopened.settle_known_cost(second, 102) == final


def test_reopening_requires_existing_file_and_matching_identity_and_roster(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    path = workspace / "runtime" / "missing.sqlite"
    with pytest.raises(FileNotFoundError, match="never initialized"):
        _reopen(path)
    ledger = _create(workspace)
    with pytest.raises(ValueError, match="identity"):
        _reopen(ledger.path, ledger_uuid=str(uuid.uuid4()))
    with pytest.raises(ValueError, match="slot roster"):
        budget.open_existing_ledger(
            ledger.path,
            ledger_uuid=LEDGER_UUID,
            plan_sha256=PLAN_SHA256,
            slot_ids=budget.ALLOWED_SLOT_IDS[:-1] + ("replacement-slot",),
        )
    with pytest.raises(FileExistsError, match="create-new"):
        _create(workspace)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ledger_uuid", "not-a-uuid"),
        ("plan_sha256", "0" * 64),
        ("slot_ids", budget.ALLOWED_SLOT_IDS[:-1]),
        ("slot_ids", budget.ALLOWED_SLOT_IDS + ("extra",)),
        ("slot_ids", budget.ALLOWED_SLOT_IDS[:-1] + (budget.ALLOWED_SLOT_IDS[0],)),
    ],
)
def test_create_rejects_malformed_or_nonfrozen_metadata(tmp_path: Path, field: str, value: object) -> None:
    workspace = _workspace(tmp_path)
    arguments: dict[str, object] = {
        "ledger_uuid": LEDGER_UUID,
        "plan_sha256": PLAN_SHA256,
        "slot_ids": budget.ALLOWED_SLOT_IDS,
    }
    arguments[field] = value
    with pytest.raises(ValueError):
        budget.create_new_ledger(workspace / "runtime" / "bad.sqlite", **arguments)  # type: ignore[arg-type]
    assert not (workspace / "runtime" / "bad.sqlite").exists()


@pytest.mark.parametrize("bad_amount", [True, False, 0, -1, 0.5, "100"])
def test_reservation_requires_positive_strict_integer(tmp_path: Path, bad_amount: object) -> None:
    ledger = _create(_workspace(tmp_path))
    with pytest.raises(ValueError, match="positive integer"):
        ledger.reserve_attempt(budget.ALLOWED_SLOT_IDS[0], bad_amount)  # type: ignore[arg-type]
    assert ledger.snapshot()["slot_admissions"] == 0


@pytest.mark.parametrize("bad_actual", [True, -1, 1.5, "10"])
def test_actual_settlement_requires_nonnegative_strict_integer(tmp_path: Path, bad_actual: object) -> None:
    ledger = _create(_workspace(tmp_path))
    slot = budget.ALLOWED_SLOT_IDS[0]
    ledger.reserve_attempt(slot, 1)
    with pytest.raises(ValueError, match="nonnegative strict integer"):
        ledger.settle_known_cost(slot, bad_actual)  # type: ignore[arg-type]
    assert ledger.snapshot()["held_reservation_micro_usd"] == 1


def test_duplicate_or_unapproved_slot_cannot_modify_ledger(tmp_path: Path) -> None:
    ledger = _create(_workspace(tmp_path))
    with pytest.raises(ValueError, match="outside"):
        ledger.reserve_attempt("x'); DROP TABLE attempts;--", 1)
    with pytest.raises(ValueError, match="without an admitted"):
        ledger.settle_known_cost(budget.ALLOWED_SLOT_IDS[0], 1)
    assert ledger.snapshot()["slot_admissions"] == 0
    # The schema remains readable after rejected SQL-looking input.
    with closing(sqlite3.connect(ledger.path)) as connection:
        with connection:
            assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0


def test_path_symlink_and_ledger_corruption_fail_closed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    ledger = _create(workspace)
    link = workspace / "runtime" / "linked.sqlite"
    try:
        link.symlink_to(ledger.path)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"platform cannot create test symlink: {exc}")
    with pytest.raises(ValueError, match="symlinks or junctions"):
        _reopen(link)

    corrupt = workspace / "runtime" / "corrupt.sqlite"
    corrupt.write_bytes(b"not sqlite")
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        _reopen(corrupt)


def test_plan_draft_mutation_blocks_open_and_existing_ledger_is_not_reset(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    ledger = _create(workspace)
    draft = workspace / "kairos" / "development" / "adaptive_replay" / "historical-episodes-draft.json"
    draft.write_bytes(draft.read_bytes() + b" ")
    with pytest.raises(ValueError, match="does not match"):
        _reopen(ledger.path)
    # The ledger is still present and unchanged; it was not re-created or reset.
    assert ledger.path.is_file()
    assert ledger.path.stat().st_size > 0


@pytest.mark.parametrize(
    "corruption",
    [
        "negative_reservation",
        "fractional_reservation",
        "unknown_foreign_slot",
        "held_with_actual",
        "settled_over_reservation",
        "noncanonical_actual",
        "overrun_without_seal",
        "overrun_wrong_reason",
        "invalid_state",
        "extra_metadata",
        "invalid_ordinal",
        "unsealed_sum_over_cap",
    ],
)
def test_corrupted_rows_or_metadata_fail_before_snapshot_admission_or_settlement(
    tmp_path: Path, corruption: str
) -> None:
    ledger = _create(_workspace(tmp_path))
    damaged_slot, settlement_slot = budget.ALLOWED_SLOT_IDS[:2]
    ledger.reserve_attempt(damaged_slot, 400_000)
    ledger.reserve_attempt(settlement_slot, 400_000)
    with closing(sqlite3.connect(ledger.path)) as connection:
        with connection:
            connection.execute("PRAGMA ignore_check_constraints=ON")
            if corruption == "negative_reservation":
                connection.execute(
                    "UPDATE attempts SET reserved_micro_usd=-1 WHERE slot_id=?", (damaged_slot,)
                )
            elif corruption == "fractional_reservation":
                connection.execute(
                    "UPDATE attempts SET reserved_micro_usd=1.5 WHERE slot_id=?", (damaged_slot,)
                )
            elif corruption == "unknown_foreign_slot":
                connection.execute(
                    "INSERT INTO attempts(slot_id,reserved_micro_usd,actual_micro_usd,state) "
                    "VALUES('foreign-slot',1,NULL,'HELD')"
                )
            elif corruption == "held_with_actual":
                connection.execute(
                    "UPDATE attempts SET actual_micro_usd='1' WHERE slot_id=?", (damaged_slot,)
                )
            elif corruption == "settled_over_reservation":
                connection.execute(
                    "UPDATE attempts SET actual_micro_usd='400001',state='SETTLED' WHERE slot_id=?",
                    (damaged_slot,),
                )
            elif corruption == "noncanonical_actual":
                connection.execute(
                    "UPDATE attempts SET actual_micro_usd='01',state='SETTLED' WHERE slot_id=?",
                    (damaged_slot,),
                )
            elif corruption == "overrun_without_seal":
                connection.execute(
                    "UPDATE attempts SET actual_micro_usd='400001',state='OVERRUN' WHERE slot_id=?",
                    (damaged_slot,),
                )
            elif corruption == "overrun_wrong_reason":
                connection.execute(
                    "UPDATE attempts SET actual_micro_usd='400001',state='OVERRUN' WHERE slot_id=?",
                    (damaged_slot,),
                )
                connection.execute("UPDATE metadata SET value='1' WHERE key='sealed'")
                connection.execute("UPDATE metadata SET value='wrong' WHERE key='seal_reason'")
            elif corruption == "invalid_state":
                connection.execute("UPDATE attempts SET state='UNKNOWN' WHERE slot_id=?", (damaged_slot,))
            elif corruption == "extra_metadata":
                connection.execute("INSERT INTO metadata(key,value) VALUES('untrusted','x')")
            elif corruption == "invalid_ordinal":
                connection.execute(
                    "UPDATE allowed_slots SET ordinal=99 WHERE slot_id=?", (budget.ALLOWED_SLOT_IDS[0],)
                )
            else:
                connection.execute(
                    "UPDATE attempts SET reserved_micro_usd=600000 WHERE slot_id=?", (damaged_slot,)
                )
                connection.execute(
                    "UPDATE attempts SET reserved_micro_usd=600000 WHERE slot_id=?", (settlement_slot,)
                )

    with pytest.raises(ValueError):
        ledger.snapshot()
    with pytest.raises(ValueError):
        ledger.reserve_attempt(budget.ALLOWED_SLOT_IDS[2], 1)
    with pytest.raises(ValueError):
        ledger.settle_known_cost(settlement_slot, 1)
    with closing(sqlite3.connect(ledger.path)) as connection:
        with connection:
            row = connection.execute(
                "SELECT actual_micro_usd, state FROM attempts WHERE slot_id=?", (settlement_slot,)
            ).fetchone()
    assert row == (None, "HELD")


@pytest.mark.parametrize(
    "arguments",
    [
        ("relative.sqlite", LEDGER_UUID, PLAN_SHA256, budget.ALLOWED_SLOT_IDS),
        (Path("relative.sqlite"), "bad-uuid", PLAN_SHA256, budget.ALLOWED_SLOT_IDS),
        (Path("relative.sqlite"), LEDGER_UUID, "0" * 64, budget.ALLOWED_SLOT_IDS),
        (Path("relative.sqlite"), LEDGER_UUID, PLAN_SHA256, list(budget.ALLOWED_SLOT_IDS)),
    ],
)
def test_public_constructor_cannot_bypass_frozen_identity_or_types(arguments: tuple[object, ...]) -> None:
    with pytest.raises(ValueError):
        budget.PilotBudget(*arguments)  # type: ignore[arg-type]
