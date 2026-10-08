"""Crash, corruption and racing-writer proof on disposable fixture journals."""

import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from threading import Barrier

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay import hypothesis_journal as journal_module
from adaptive_replay.historical_context import canonical, digest
from adaptive_replay.hypothesis_journal import HypothesisJournal, JournalArm, JournalSeal
from adaptive_replay.hypothesis_v2 import EntryQuote, HypothesisObservation, HypothesisPlan, HypothesisPolicy
from adaptive_replay.scenarios import ScenarioEvidence, ScenarioObservation

START = 86_400_000


def fixture_plan():
    anchor = Candle("BTCUSDT", "1m", START - 60_000, START - 1, 100, 101, 99, 100, 10)
    evidence = ScenarioEvidence(
        "bars", "MARKET", "BTCUSDT", digest(candle_payload(anchor)), START - 1, START, START, 600_000
    )
    parent = SleeveIntent(
        "native-fixture",
        "BTCUSDT",
        Side.LONG,
        START - 1,
        START,
        START + 59_999,
        100,
        0.7,
        500,
        ExitPlan(98, 105, 300_000, 103, 1),
        (("proof", "fixture"),),
    )
    policy = HypothesisPolicy(START - 1, 300_000, "quotes", 5_000, "TEST_FIXTURE", False)
    return HypothesisPlan(
        parent,
        "TECHNICAL",
        "BULL",
        START,
        "a" * 64,
        "b" * 64,
        (evidence,),
        anchor,
        (("MARKET", "bars"),),
        policy,
    )


def fixture_observation(*, quote=True, open_ms=START, confirming=True):
    candle = Candle(
        "BTCUSDT", "1m", open_ms, open_ms + 59_999, 100, 101, 99, 100.5 if confirming else 100, 10
    )
    evidence = ScenarioEvidence(
        "bars",
        "MARKET",
        "BTCUSDT",
        digest(candle_payload(candle)),
        open_ms + 59_999,
        open_ms + 60_000,
        open_ms + 60_000,
        600_000,
    )
    bbo = EntryQuote(
        "quotes",
        "BTCUSDT",
        100.49,
        100.5,
        open_ms + 60_010,
        open_ms + 60_011,
        open_ms + 60_012,
        5_000,
        "TEST_FIXTURE",
    )
    return HypothesisObservation(
        ScenarioObservation(candle, open_ms + 60_020, (evidence,)), bbo if quote else None
    )


@pytest.fixture
def recorded(tmp_path):
    plan = fixture_plan()
    seal = JournalSeal("integrity-fixture", START - 1, "a" * 64, (JournalArm("control", plan.policy),), 2)
    path = tmp_path / "integrity.research.sqlite3"
    journal = HypothesisJournal.create(path, seal)
    journal.register("control", plan)
    return path, seal, plan, journal


@pytest.mark.parametrize("field", ["context_sha256", "regime"])
@pytest.mark.parametrize("terminal", [False, True])
def test_original_parent_cannot_be_repackaged_to_rescue_outcome(recorded, field, terminal):
    _, _, plan, journal = recorded
    if terminal:
        journal.append("control", plan.template.intent_id, fixture_observation(quote=False))
    before = journal.snapshot()
    changed = replace(plan, **{field: "c" * 64 if field == "context_sha256" else "RANGE"})
    assert changed.scenario_id != plan.scenario_id
    with pytest.raises(ValueError):
        journal.register("control", changed)
    assert journal.snapshot() == before


@pytest.mark.parametrize(
    "mutation",
    [
        "intent_id",
        "protection",
        "unknown_plan_field",
        "missing_plan_field",
        "boolean_clock",
        "evaluation",
        "candidate",
        "previous_hash",
        "head",
        "count",
        "truncate",
        "parent_delete",
        "extra_table",
        "implementation",
        "noncanonical_json",
        "duplicate_json_key",
        "minute",
    ],
)
def test_corruption_never_restores_or_emits_an_entry(recorded, mutation):
    path, seal, plan, journal = recorded
    journal.append("control", plan.template.intent_id, fixture_observation())
    with sqlite3.connect(path) as connection:
        if mutation in {
            "intent_id",
            "protection",
            "unknown_plan_field",
            "missing_plan_field",
            "boolean_clock",
        }:
            raw = asdict(plan)
            if mutation == "intent_id":
                raw["template"]["intent_id"] = "e" * 64
            elif mutation == "protection":
                raw["template"]["exit_plan"]["trailing_distance"] = 0.5
            elif mutation == "unknown_plan_field":
                raw["untrusted_override"] = True
            elif mutation == "missing_plan_field":
                raw.pop("policy")
            else:
                raw["created_ms"] = True
            connection.execute("UPDATE parents SET plan_json=?", (canonical(raw),))
        elif mutation in {"evaluation", "candidate"}:
            raw = asdict(journal.snapshot().hypotheses[0].receipts[-1].evaluation)
            if mutation == "evaluation":
                raw["state"] = "WAITING_TRIGGER"
            else:
                raw["candidate"]["exit_plan"]["trailing_distance"] = 0.5
            connection.execute("UPDATE events SET evaluation_json=? WHERE sequence=2", (canonical(raw),))
        elif mutation == "previous_hash":
            connection.execute("UPDATE events SET previous_sha256=? WHERE sequence=2", ("e" * 64,))
        elif mutation == "head":
            connection.execute("UPDATE meta SET head_sha256=?", ("e" * 64,))
        elif mutation == "count":
            connection.execute("UPDATE meta SET event_count=1")
        elif mutation == "truncate":
            connection.execute("DELETE FROM events WHERE sequence=2")
        elif mutation == "parent_delete":
            connection.execute("DELETE FROM parents")
        elif mutation == "extra_table":
            connection.execute("CREATE TABLE override (payload TEXT)")
        elif mutation == "implementation":
            connection.execute("UPDATE meta SET implementation_json='{}'")
        elif mutation == "noncanonical_json":
            connection.execute("UPDATE parents SET plan_json=' ' || plan_json")
        elif mutation == "duplicate_json_key":
            connection.execute("UPDATE parents SET plan_json=?", ('{"created_ms":1,"created_ms":2}',))
        elif mutation == "minute":
            connection.execute("UPDATE events SET minute_ms=1 WHERE sequence=2")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        HypothesisJournal.open(path, seal)
    assert path.read_bytes() == before


def test_exception_after_event_and_head_writes_rolls_back_entire_attempt(recorded, monkeypatch):
    path, seal, plan, journal = recorded
    before = journal.snapshot()
    original = journal._append_event

    class Crash(BaseException):
        pass

    def crash(*args):
        original(*args)
        raise Crash("synthetic interruption before commit")

    monkeypatch.setattr(journal, "_append_event", crash)
    with pytest.raises(Crash):
        journal.append("control", plan.template.intent_id, fixture_observation())
    restored = HypothesisJournal.open(path, seal)
    assert restored.snapshot() == before
    assert restored.append("control", plan.template.intent_id, fixture_observation()).new_event


@pytest.mark.parametrize("committed", [False, True])
def test_actual_process_exit_restores_atomic_transaction_and_duplicate_semantics(recorded, committed):
    path, seal, plan, _ = recorded
    # Two tiny isolated fixture workers, never a market/model/trading runner.
    script = """
import os, sys
from adaptive_replay.hypothesis_journal import HypothesisJournal, _seal, _plan, _observation
j = HypothesisJournal.open(sys.argv[1], _seal(sys.argv[2]))
p, o = _plan(sys.argv[3]), _observation(sys.argv[4])
if sys.argv[5] == 'False':
    original = j._append_event
    def crash(*args):
        original(*args)
        os._exit(73)
    j._append_event = crash
j.append('control', p.template.intent_id, o)
os._exit(73)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(path),
            canonical(asdict(seal)),
            canonical(asdict(plan)),
            canonical(asdict(fixture_observation())),
            str(committed),
        ],
        timeout=20,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 73, result.stderr
    restored = HypothesisJournal.open(path, seal)
    assert restored.snapshot().event_count == (2 if committed else 1)
    receipt = restored.append("control", plan.template.intent_id, fixture_observation())
    assert receipt.new_event is not committed
    assert restored.snapshot().event_count == 2


def test_conflicting_racing_writers_commit_one_immutable_winner(recorded):
    path, seal, plan, journal = recorded
    obs = fixture_observation()
    alternative = replace(obs, quote=replace(obs.quote, bid=100.48))
    barrier = Barrier(2)

    def worker(observation):
        instance = HypothesisJournal.open(path, seal)
        barrier.wait(timeout=10)
        try:
            return instance.append("control", plan.template.intent_id, observation)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(worker, (obs, alternative)))
    assert sum(r is not None and r.new_event for r in receipts) == 1
    assert journal.snapshot().event_count == 2
    assert len(journal.snapshot().hypotheses[0].observations) == 1


def test_runtime_mechanics_mutation_and_changed_expected_source_binding_fail_closed(recorded, monkeypatch):
    path, seal, _, journal = recorded
    monkeypatch.setitem(journal_module.CAPABILITIES, "CRASH", {Side.LONG})
    with pytest.raises(ValueError):
        journal.snapshot()
    with pytest.raises(ValueError):
        HypothesisJournal.open(path, seal)


def test_empty_preserved_creation_attempt_is_never_automatically_reinitialized(tmp_path):
    path = tmp_path / "interrupted.research.sqlite3"
    path.touch()
    plan = fixture_plan()
    seal = JournalSeal("integrity-fixture", START - 1, "a" * 64, (JournalArm("control", plan.policy),), 2)
    with pytest.raises(ValueError):
        HypothesisJournal.open(path, seal)
    with pytest.raises(FileExistsError):
        HypothesisJournal.create(path, seal)
    assert path.read_bytes() == b""


def test_hard_link_alias_cannot_be_opened_as_separate_research_journal(recorded):
    path, seal, _, _ = recorded
    alias = path.with_name("alias.research.sqlite3")
    os.link(path, alias)
    with pytest.raises(ValueError):
        HypothesisJournal.open(alias, seal)
    with pytest.raises(ValueError):
        HypothesisJournal.open(path, seal)


def test_later_successful_trigger_after_restart_does_not_record_another_candidate(recorded):
    path, seal, plan, journal = recorded
    journal.append("control", plan.template.intent_id, fixture_observation())
    restored = HypothesisJournal.open(path, seal)
    result = restored.append("control", plan.template.intent_id, fixture_observation(open_ms=START + 60_000))
    assert result.new_event and result.evaluation.reason == "TERMINAL_NO_RESURRECTION"
    assert result.evaluation.candidate is None
    assert sum(r.evaluation.candidate is not None for r in restored.snapshot().hypotheses[0].receipts) == 1


def test_quiet_first_observation_already_blocks_late_control_enrollment(tmp_path):
    plan = fixture_plan()
    reviewed = replace(plan, policy=replace(plan.policy, require_review=True))
    seal = JournalSeal(
        "late-arm-fixture",
        START - 1,
        "a" * 64,
        (JournalArm("control", plan.policy), JournalArm("reviewed", reviewed.policy)),
        2,
    )
    journal = HypothesisJournal.create(tmp_path / "late-arm.research.sqlite3", seal)
    journal.register("reviewed", reviewed)
    result = journal.append("reviewed", reviewed.template.intent_id, fixture_observation(confirming=False))
    assert result.evaluation.state == "WAITING_TRIGGER"
    with pytest.raises(ValueError):
        journal.register("control", plan)


def test_registration_and_initial_receipt_roll_back_together(tmp_path, monkeypatch):
    plan = fixture_plan()
    seal = JournalSeal("atomic-register", START - 1, "a" * 64, (JournalArm("control", plan.policy),), 2)
    path = tmp_path / "register.research.sqlite3"
    journal = HypothesisJournal.create(path, seal)
    original = journal._append_event

    def interrupted(*args):
        original(*args)
        raise RuntimeError("synthetic failure before registration commit")

    monkeypatch.setattr(journal, "_append_event", interrupted)
    with pytest.raises(RuntimeError):
        journal.register("control", plan)
    restored = HypothesisJournal.open(path, seal)
    assert restored.snapshot().hypotheses == () and restored.snapshot().event_count == 0
    assert restored.register("control", plan).new_event
