"""Offline durability and admission tests for the hypothesis research journal.

All observations here are deliberately synthetic. These tests do not qualify a
historical feed, quote source, strategy, or venue.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_journal import (
    HypothesisJournal,
    JournalArm,
    JournalSeal,
)
from adaptive_replay.hypothesis_v2 import (
    EntryQuote,
    HypothesisObservation,
    HypothesisPlan,
    HypothesisPolicy,
)
from adaptive_replay.scenarios import ScenarioEvidence, ScenarioObservation

START = 86_400_000
MINUTE = 60_000
SYMBOL = "BTCUSDT"


def bar(open_ms: int, close: float = 100.0) -> Candle:
    return Candle(SYMBOL, "1m", open_ms, open_ms + MINUTE - 1, 100, 101, 99, close, 10)


def source(candle: Candle) -> ScenarioEvidence:
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


def plan(
    *,
    side: Side = Side.LONG,
    review: bool = False,
    lifetime: int = 5 * MINUTE,
    quote_source: str = "quotes",
    sealed_ms: int = START - 1,
) -> HypothesisPlan:
    sign = 1 if side is Side.LONG else -1
    anchor = bar(START - MINUTE)
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
        (("native_marker", "unchanged"),),
    )
    policy = HypothesisPolicy(sealed_ms, lifetime, quote_source, 5_000, "TEST_FIXTURE", review)
    return HypothesisPlan(
        parent,
        "TECHNICAL",
        "BULL" if side is Side.LONG else "BEAR",
        START,
        "a" * 64,
        "b" * 64,
        (source(anchor),),
        anchor,
        (("MARKET", "bars"),),
        policy,
    )


def observation(
    open_ms: int = START,
    *,
    side: Side = Side.LONG,
    confirming: bool = True,
    quote: bool = True,
    review: bool = False,
) -> HypothesisObservation:
    close = (100.5 if side is Side.LONG else 99.5) if confirming else 100.0
    candle = bar(open_ms, close)
    cut = candle.close_time_ms + 1
    observed = cut + 20
    market = ScenarioObservation(candle, observed, (source(candle),))
    bid, ask = (100.49, 100.5) if side is Side.LONG else (99.5, 99.51)
    q = EntryQuote("quotes", SYMBOL, bid, ask, cut + 10, cut + 11, cut + 12, 5_000, "TEST_FIXTURE")
    obs = HypothesisObservation(market, q if quote else None)
    if review:
        from adaptive_replay.scenarios import ScenarioReview

        receipt = ScenarioReview("0" * 64, side, "ALLOW", obs.context_sha256, observed, "c" * 64)
        # The concrete plan ID is supplied by reviewed_observation below.
        obs = replace(obs, market=replace(obs.market, review=receipt))
    return obs


def reviewed_observation(p: HypothesisPlan, obs: HypothesisObservation) -> HypothesisObservation:
    from adaptive_replay.scenarios import ScenarioReview

    receipt = ScenarioReview(
        p.scenario_id,
        p.template.side,
        "ALLOW",
        obs.context_sha256,
        obs.market.observed_ms,
        "c" * 64,
    )
    return replace(obs, market=replace(obs.market, review=receipt))


def seal(*, arms: tuple[JournalArm, ...] | None = None, maximum_parents: int = 4) -> JournalSeal:
    p = plan()
    return JournalSeal(
        "offline-test", START - 1, "a" * 64, arms or (JournalArm("baseline", p.policy),), maximum_parents
    )


def journal_path(tmp_path: Path, name: str = "hypotheses.research.sqlite3") -> Path:
    return tmp_path / name


def test_round_trip_restarts_and_preserves_full_long_and_short_protection(tmp_path):
    long_plan, short_plan = plan(), plan(side=Side.SHORT)
    frozen = (long_plan.template.exit_plan, short_plan.template.exit_plan)
    s = seal(arms=(JournalArm("long", long_plan.policy), JournalArm("short", short_plan.policy)))
    path = journal_path(tmp_path)
    journal = HypothesisJournal.create(path, s)
    journal.register("long", long_plan)
    journal.register("short", short_plan)
    quiet = observation(confirming=False)
    trigger = observation(START + MINUTE)
    journal.append("long", long_plan.template.intent_id, quiet)
    journal.append("long", long_plan.template.intent_id, trigger)
    journal.append("short", short_plan.template.intent_id, observation(confirming=False, side=Side.SHORT))
    journal.append("short", short_plan.template.intent_id, observation(START + MINUTE, side=Side.SHORT))

    reopened = HypothesisJournal.open(path, s)
    snapshot = reopened.snapshot()
    by_arm = {item.arm_id: item for item in snapshot.hypotheses}
    assert snapshot.seal_sha256
    assert snapshot.event_count == 6
    assert by_arm["long"].observations == (quiet, trigger)
    assert by_arm["short"].observations[-1].quote.ask == pytest.approx(99.51)
    assert by_arm["long"].receipts[-1].evaluation.state == "CONSUMED"
    assert by_arm["short"].receipts[-1].evaluation.state == "CONSUMED"
    assert by_arm["long"].plan.template.exit_plan == frozen[0]
    assert by_arm["short"].plan.template.exit_plan == frozen[1]


def test_missing_quote_is_consumed_and_restart_cannot_rescue_it(tmp_path):
    p = plan()
    s = seal()
    path = journal_path(tmp_path)
    journal = HypothesisJournal.create(path, s)
    journal.register("baseline", p)
    first = observation(quote=False)
    receipt = journal.append("baseline", p.template.intent_id, first)
    assert receipt.evaluation.state == "CONSUMED"
    reopened = HypothesisJournal.open(path, s)
    later = reopened.append("baseline", p.template.intent_id, observation(START + MINUTE))
    assert later.evaluation.reason == "TERMINAL_NO_RESURRECTION"
    assert later.evaluation.candidate is None
    again = reopened.append("baseline", p.template.intent_id, first)
    assert not again.new_event
    assert again.chain_sha256 == receipt.chain_sha256
    assert reopened.snapshot().hypotheses[0].observations == (first, observation(START + MINUTE))


def test_exact_duplicate_returns_original_receipt_but_changed_quote_or_review_conflicts(tmp_path):
    p, s = plan(), seal()
    journal = HypothesisJournal.create(journal_path(tmp_path), s)
    registered = journal.register("baseline", p)
    same = journal.register("baseline", p)
    assert registered.new_event and not same.new_event
    assert same == replace(registered, new_event=False)
    obs = observation()
    first = journal.append("baseline", p.template.intent_id, obs)
    duplicate = journal.append("baseline", p.template.intent_id, obs)
    assert not duplicate.new_event and duplicate == replace(first, new_event=False)
    with pytest.raises(ValueError):
        journal.append("baseline", p.template.intent_id, replace(obs, quote=replace(obs.quote, bid=100.48)))
    with pytest.raises(ValueError):
        journal.append("baseline", p.template.intent_id, reviewed_observation(p, obs))


def test_seal_arm_policy_identity_and_required_creation_sources_are_enforced(tmp_path):
    p = plan()
    s = seal()
    journal = HypothesisJournal.create(journal_path(tmp_path), s)
    with pytest.raises(ValueError):
        journal.register("not-sealed", p)
    with pytest.raises(ValueError):
        journal.register("baseline", replace(p, policy=replace(p.policy, quote_source_id="other")))
    with pytest.raises(ValueError):
        journal.register("baseline", replace(p, required_sources=()))
    assert journal.snapshot().event_count == 0


def test_open_requires_matching_seal_and_never_creates_a_missing_database(tmp_path):
    path = journal_path(tmp_path)
    s = seal()
    with pytest.raises((FileNotFoundError, ValueError)):
        HypothesisJournal.open(path, s)
    assert not path.exists()
    journal = HypothesisJournal.create(path, s)
    with pytest.raises(ValueError):
        HypothesisJournal.open(path, seal(maximum_parents=3))
    assert journal.snapshot().event_count == 0


@pytest.mark.parametrize("name", ["journal.sqlite3", "journal.research.db", "journal.sqlite3.bak"])
def test_create_refuses_noncanonical_filename_and_does_not_clobber_existing_files(tmp_path, name):
    path = journal_path(tmp_path, name)
    with pytest.raises(ValueError):
        HypothesisJournal.create(path, seal())
    assert not path.exists()
    existing = journal_path(tmp_path)
    existing.write_bytes(b"preserve me")
    with pytest.raises((FileExistsError, ValueError)):
        HypothesisJournal.create(existing, seal())
    assert existing.read_bytes() == b"preserve me"


def test_additional_arm_must_be_registered_before_any_observation_for_parent(tmp_path):
    p1 = plan()
    p2 = plan(quote_source="quotes-v2")
    s = seal(arms=(JournalArm("first", p1.policy), JournalArm("second", p2.policy)))
    journal = HypothesisJournal.create(journal_path(tmp_path), s)
    journal.register("first", p1)
    journal.append("first", p1.template.intent_id, observation())
    with pytest.raises(ValueError):
        journal.register("second", p2)


def test_same_parent_may_have_only_policy_distinct_arm_hypotheses_before_observations(tmp_path):
    p1 = plan()
    p2 = plan(quote_source="quotes-v2")
    s = seal(arms=(JournalArm("first", p1.policy), JournalArm("second", p2.policy)))
    journal = HypothesisJournal.create(journal_path(tmp_path), s)
    journal.register("first", p1)
    journal.register("second", p2)
    with pytest.raises(ValueError):
        journal.register("second", p1)
    assert len(journal.snapshot().hypotheses) == 2


def test_concurrent_duplicate_append_is_idempotent_across_independent_connections(tmp_path):
    p, s, path = plan(), seal(), journal_path(tmp_path)
    HypothesisJournal.create(path, s).register("baseline", p)
    obs = observation(confirming=False)

    def append_once(_):
        return HypothesisJournal.open(path, s).append("baseline", p.template.intent_id, obs)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(append_once, range(12)))
    assert sum(result.new_event for result in results) == 1
    assert len({result.chain_sha256 for result in results}) == 1
    assert HypothesisJournal.open(path, s).snapshot().event_count == 2


def test_parent_capacity_is_sealed_and_full_observation_horizon_is_bounded(tmp_path):
    p = plan(lifetime=60 * MINUTE)
    s = seal(arms=(JournalArm("baseline", p.policy),), maximum_parents=1)
    journal = HypothesisJournal.create(journal_path(tmp_path), s)
    journal.register("baseline", p)
    other = replace(
        p,
        template=replace(p.template, metadata=(("native_marker", "different-parent"),)),
    )
    with pytest.raises(ValueError):
        journal.register("baseline", other)

    # Quiet observations exercise the maximum durable prefix without ever
    # producing a candidate or relying on any external input.
    current = p.template.intent_id
    for index in range(60):
        journal.append(
            "baseline", current, observation(START + index * MINUTE, confirming=False, quote=False)
        )
    with pytest.raises(ValueError):
        journal.append("baseline", current, observation(START + 60 * MINUTE, confirming=False, quote=False))
