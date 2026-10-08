"""Synthetic, offline-only checks for journal-bound simulated-fill feasibility."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay.fill_feasibility import SimulatedFill, assess_journal_simulated_fill
from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_journal import HypothesisJournal, JournalArm, JournalSeal
from adaptive_replay.hypothesis_v2 import EntryQuote, HypothesisObservation, HypothesisPlan, HypothesisPolicy
from adaptive_replay.quote_capture import PAYLOAD_SCHEMA, BboCapture
from adaptive_replay.scenarios import MINUTE, ScenarioEvidence, ScenarioObservation

START = 86_400_000
SYMBOL = "BTCUSDT"
ARM = "fill-check"


def _bar(open_ms: int, close: float = 100.0) -> Candle:
    return Candle(SYMBOL, "1m", open_ms, open_ms + MINUTE - 1, 100, 101, 99, close, 10)


def _evidence(candle: Candle) -> ScenarioEvidence:
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


def _plan(side: Side) -> HypothesisPlan:
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
        (("native_marker", "unchanged"),),
    )
    policy = HypothesisPolicy(START - 1, 5 * MINUTE, "quotes", 5_000, "TEST_FIXTURE", False)
    return HypothesisPlan(
        parent,
        "TECHNICAL",
        "BULL" if side is Side.LONG else "BEAR",
        START,
        "a" * 64,
        "b" * 64,
        (_evidence(anchor),),
        anchor,
        (("MARKET", "bars"),),
        policy,
    )


def _obs(open_ms: int, side: Side, *, confirming: bool, quote: bool = True) -> HypothesisObservation:
    candle = _bar(open_ms, 100.5 if confirming and side is Side.LONG else (99.5 if confirming else 100.0))
    close = candle.close_time_ms
    observed = close + 20
    q = EntryQuote(
        "quotes",
        SYMBOL,
        100.49 if side is Side.LONG else 99.5,
        100.5 if side is Side.LONG else 99.51,
        close + 10,
        close + 11,
        close + 12,
        5_000,
        "TEST_FIXTURE",
    )
    return HypothesisObservation(
        ScenarioObservation(candle, observed, (_evidence(candle),)), q if quote else None
    )


def _journal(tmp_path: Path, side: Side, *, early_unavailable: bool = False):
    plan = _plan(side)
    seal = JournalSeal("offline-fill-test", START - 1, "a" * 64, (JournalArm(ARM, plan.policy),), 4)
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "hypotheses.research.sqlite3"
    journal = HypothesisJournal.create(path, seal)
    journal.register(ARM, plan)
    first = _obs(START, side, confirming=early_unavailable, quote=not early_unavailable)
    journal.append(ARM, plan.template.intent_id, first)
    journal.append(ARM, plan.template.intent_id, _obs(START + MINUTE, side, confirming=True))
    return path, seal, plan, HypothesisJournal.open(path, seal).snapshot()


def _capture(
    *,
    side: Side,
    event_ms: int,
    received_ms: int,
    captured_ms: int,
    bid: float | None = None,
    ask: float | None = None,
    bid_quantity: float = 2.0,
    ask_quantity: float = 2.0,
    source: str = "quotes",
    symbol: str = SYMBOL,
    evidence: str = "TEST_FIXTURE",
    ttl: int = 5_000,
) -> BboCapture:
    if bid is None:
        bid = 100.49 if side is Side.LONG else 99.5
    if ask is None:
        ask = 100.5 if side is Side.LONG else 99.51
    raw = json.dumps(
        {
            "schema_id": PAYLOAD_SCHEMA,
            "timestamp_unit": "ms",
            "source_id": source,
            "symbol": symbol,
            "event_ms": event_ms,
            "bid": bid,
            "ask": ask,
            "bid_quantity": bid_quantity,
            "ask_quantity": ask_quantity,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return BboCapture(raw, hashlib.sha256(raw).hexdigest(), received_ms, captured_ms, ttl, evidence)


def _assessment(path, seal, candidate, fill, side, issue_capture, execution_capture):
    return assess_journal_simulated_fill(
        journal_path=path,
        seal=seal,
        candidate=candidate,
        fill=fill,
        issue_capture=issue_capture,
        execution_capture=execution_capture,
    )


@pytest.fixture(params=[Side.LONG, Side.SHORT], ids=["long", "short"])
def valid_case(tmp_path, request):
    side = request.param
    path, seal, plan, snapshot = _journal(tmp_path, side)
    candidate = snapshot.hypotheses[0].receipts[-1].evaluation.candidate
    assert candidate is not None
    assert candidate.exit_plan == plan.template.exit_plan
    observation = snapshot.hypotheses[0].observations[-1]
    close = observation.market.candle.close_time_ms
    issue_capture = _capture(
        side=side,
        event_ms=close + 10,
        received_ms=close + 11,
        captured_ms=close + 12,
    )
    eligible = candidate.entry_eligible_ts_ms
    execution_capture = _capture(
        side=side,
        event_ms=eligible + 1,
        received_ms=eligible + 2,
        captured_ms=eligible + 3,
    )
    # A lower short-sale price is adverse; one tick is within the fixed cost budget.
    fill_price = 100.51 if side is Side.LONG else 99.496
    fill = SimulatedFill(
        ARM,
        plan.template.intent_id,
        candidate.intent_id,
        SYMBOL,
        side,
        fill_price,
        1.0,
        eligible + 3,
        plan.protection_sha256,
    )
    return path, seal, plan, candidate, issue_capture, execution_capture, fill


def test_long_short_fill_success_survives_restart_and_preserves_exact_exit_plan(valid_case):
    path, seal, plan, candidate, issue_capture, execution_capture, fill = valid_case
    before = path.read_bytes()
    first = _assessment(path, seal, candidate, fill, plan.template.side, issue_capture, execution_capture)
    reopened = HypothesisJournal.open(path, seal)
    again = _assessment(path, seal, candidate, fill, plan.template.side, issue_capture, execution_capture)
    assert first.state == "SIMULATED_CHECK_ONLY", first.reason
    assert first.reason == "PROVIDED_FILL_COMPATIBLE_NOT_EXECUTION_OR_RISK_APPROVAL"
    assert first.risk_authority == again.risk_authority == "NONE"
    assert first == again
    assert (
        reopened.snapshot().hypotheses[0].plan.template.exit_plan
        == candidate.exit_plan
        == plan.template.exit_plan
    )
    assert path.read_bytes() == before


def test_missing_capture_is_unavailable_not_a_refusal(valid_case):
    path, seal, plan, candidate, issue_capture, execution_capture, fill = valid_case
    result = _assessment(path, seal, candidate, fill, plan.template.side, issue_capture, None)
    assert (result.state, result.coverage, result.risk_authority) == ("UNAVAILABLE", "UNAVAILABLE", "NONE")


def test_issue_capture_must_match_retained_quote_digest_not_just_normalized_prices(tmp_path):
    side = Side.LONG
    plan = _plan(side)
    seal = JournalSeal("offline-fill-test", START - 1, "a" * 64, (JournalArm(ARM, plan.policy),), 4)
    path = tmp_path / "hypotheses.research.sqlite3"
    journal = HypothesisJournal.create(path, seal)
    journal.register(ARM, plan)
    journal.append(ARM, plan.template.intent_id, _obs(START, side, confirming=False))
    ordinary = _obs(START + MINUTE, side, confirming=True)
    close = ordinary.market.candle.close_time_ms
    retained = EntryQuote(
        "quotes",
        SYMBOL,
        100,
        100.01,
        close + 10,
        close + 11,
        close + 12,
        5_000,
        "TEST_FIXTURE",
    )
    # The parser normalizes JSON numeric prices to float. Numeric equality must
    # not erase the exact typed quote digest retained in the journal.
    journal.append(ARM, plan.template.intent_id, replace(ordinary, quote=retained))
    snapshot = HypothesisJournal.open(path, seal).snapshot()
    candidate = snapshot.hypotheses[0].receipts[-1].evaluation.candidate
    assert candidate is not None
    issue = _capture(
        side=side,
        event_ms=close + 10,
        received_ms=close + 11,
        captured_ms=close + 12,
        bid=100.0,
        ask=100.01,
    )
    eligible = candidate.entry_eligible_ts_ms
    execution = _capture(
        side=side,
        event_ms=eligible + 1,
        received_ms=eligible + 2,
        captured_ms=eligible + 3,
        bid=100.02,
        ask=100.03,
    )
    fill = SimulatedFill(
        ARM,
        plan.template.intent_id,
        candidate.intent_id,
        SYMBOL,
        side,
        100.04,
        1,
        eligible + 3,
        plan.protection_sha256,
    )
    result = _assessment(path, seal, candidate, fill, side, issue, execution)
    assert result.state == "UNAVAILABLE"
    assert result.reason == "ISSUE_CAPTURE_DIFFERS_FROM_RETAINED_QUOTE"


@pytest.mark.parametrize(
    "change",
    [
        lambda c: replace(c, entry_expires_ts_ms=c.entry_expires_ts_ms - 1),
        lambda c: replace(c, signal_strength=c.signal_strength - 0.1),
        lambda c: replace(
            c,
            reference_price=c.reference_price + 0.01,
            gross_reward_bps=abs(c.exit_plan.target_price - (c.reference_price + 0.01))
            / (c.reference_price + 0.01)
            * 10_000,
        ),
        lambda c: replace(
            c,
            exit_plan=replace(
                c.exit_plan, target_price=c.exit_plan.target_price + (0.1 if c.side is Side.SHORT else -0.1)
            ),
            gross_reward_bps=abs(
                (c.exit_plan.target_price + (0.1 if c.side is Side.SHORT else -0.1)) - c.reference_price
            )
            / c.reference_price
            * 10_000,
        ),
    ],
)
def test_candidate_copied_metadata_cannot_change_any_native_candidate_field(valid_case, change):
    path, seal, plan, candidate, issue, execution, fill = valid_case
    altered = change(candidate)
    result = _assessment(path, seal, altered, fill, plan.template.side, issue, execution)
    assert (result.state, result.reason) == ("REFUSED", "NOT_EXACT_JOURNAL_ISSUED_CANDIDATE")


@pytest.mark.parametrize(
    "field,value",
    [
        ("arm_id", "other-arm"),
        ("parent_id", "f" * 64),
        ("side", None),
        ("symbol", "ETHUSDT"),
        ("intent_id", "e" * 64),
        ("protection_sha256", "d" * 64),
    ],
)
def test_fill_identity_and_original_protection_must_match(valid_case, field, value):
    path, seal, plan, candidate, issue, execution, fill = valid_case
    if field == "side":
        value = Side.SHORT if fill.side is Side.LONG else Side.LONG
    altered = replace(fill, **{field: value})
    result = _assessment(path, seal, candidate, altered, plan.template.side, issue, execution)
    assert result.state == "REFUSED"


def test_earlier_terminal_no_candidate_receipt_cannot_be_hidden_by_later_valid_quote(tmp_path):
    side = Side.LONG
    good_path, good_seal, good_plan, good_snapshot = _journal(tmp_path / "good", side)
    good_candidate = good_snapshot.hypotheses[0].receipts[-1].evaluation.candidate
    assert good_candidate is not None
    # First confirmation has no quote and consumes the fold; a later valid-looking
    # confirming observation cannot produce or overwrite the original candidate.
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    path, seal, plan, _ = _journal(bad_dir, side, early_unavailable=True)
    close = _obs(START, side, confirming=True).market.candle.close_time_ms
    issue = _capture(side=side, event_ms=close + 10, received_ms=close + 11, captured_ms=close + 12)
    eligible = good_candidate.entry_eligible_ts_ms
    execution = _capture(side=side, event_ms=eligible + 1, received_ms=eligible + 2, captured_ms=eligible + 3)
    fill = SimulatedFill(
        ARM,
        plan.template.intent_id,
        good_candidate.intent_id,
        SYMBOL,
        side,
        100.51,
        1,
        eligible + 3,
        plan.protection_sha256,
    )
    result = _assessment(path, seal, good_candidate, fill, side, issue, execution)
    assert (result.state, result.reason) == ("REFUSED", "NOT_EXACT_JOURNAL_ISSUED_CANDIDATE")


@pytest.mark.parametrize(
    "capture_kind", ["future", "stale", "changed_quote", "wrong_source", "wrong_symbol", "wrong_evidence"]
)
def test_issue_capture_must_match_original_quote_clock_bytes_source_and_evidence(valid_case, capture_kind):
    path, seal, plan, candidate, issue, execution, fill = valid_case
    if capture_kind == "future":
        issue = _capture(
            side=plan.template.side,
            event_ms=candidate.entry_eligible_ts_ms + 1,
            received_ms=candidate.entry_eligible_ts_ms + 1,
            captured_ms=candidate.entry_eligible_ts_ms + 1,
        )
    elif capture_kind == "stale":
        issue = _capture(
            side=plan.template.side,
            event_ms=issue.quote.event_ms,
            received_ms=issue.received_ms,
            captured_ms=issue.captured_ms,
            ttl=1,
        )
    elif capture_kind == "changed_quote":
        issue = _capture(
            side=plan.template.side,
            event_ms=issue.quote.event_ms,
            received_ms=issue.received_ms,
            captured_ms=issue.captured_ms,
            bid=issue.quote.bid - 0.01,
        )
    elif capture_kind == "wrong_source":
        issue = _capture(
            side=plan.template.side,
            event_ms=issue.quote.event_ms,
            received_ms=issue.received_ms,
            captured_ms=issue.captured_ms,
            source="other",
        )
    elif capture_kind == "wrong_symbol":
        issue = _capture(
            side=plan.template.side,
            event_ms=issue.quote.event_ms,
            received_ms=issue.received_ms,
            captured_ms=issue.captured_ms,
            symbol="ETHUSDT",
        )
    else:
        issue = _capture(
            side=plan.template.side,
            event_ms=issue.quote.event_ms,
            received_ms=issue.received_ms,
            captured_ms=issue.captured_ms,
            evidence="CALLER_ATTESTED_POINT_IN_TIME",
        )
    result = _assessment(path, seal, candidate, fill, plan.template.side, issue, execution)
    assert result.state == "UNAVAILABLE"


@pytest.mark.parametrize("field,value", [("source", "other"), ("evidence", "CALLER_ATTESTED_POINT_IN_TIME")])
def test_execution_capture_source_and_evidence_mismatch_is_unavailable(valid_case, field, value):
    path, seal, plan, candidate, issue, execution, fill = valid_case
    execution = _capture(
        side=plan.template.side,
        event_ms=execution.quote.event_ms,
        received_ms=execution.received_ms,
        captured_ms=execution.captured_ms,
        **{field: value},
    )
    assert (
        _assessment(path, seal, candidate, fill, plan.template.side, issue, execution).state == "UNAVAILABLE"
    )


@pytest.mark.parametrize("mode", ["wide_spread", "excess_slippage"])
def test_spread_and_adverse_slippage_cost_limits_refuse_fill(valid_case, mode):
    path, seal, plan, candidate, issue, execution, fill = valid_case
    side = plan.template.side
    if mode == "wide_spread":
        if side is Side.LONG:
            execution = _capture(
                side=side,
                event_ms=execution.quote.event_ms,
                received_ms=execution.received_ms,
                captured_ms=execution.captured_ms,
                bid=100.45,
                ask=100.51,
            )
            fill = replace(fill, price=100.52)
        else:
            execution = _capture(
                side=side,
                event_ms=execution.quote.event_ms,
                received_ms=execution.received_ms,
                captured_ms=execution.captured_ms,
                bid=99.49,
                ask=99.55,
            )
            fill = replace(fill, price=99.48)
    else:
        # Keep the BBO narrow while supplying adverse slippage beyond the frozen
        # one-basis-point per-side assumption.
        fill = replace(fill, price=100.52 if side is Side.LONG else 99.48)
    result = _assessment(path, seal, candidate, fill, side, issue, execution)
    assert result.state == "REFUSED"
    assert result.reason == "FILL_EXCEEDS_UNCHANGED_SPREAD_OR_SLIPPAGE_ASSUMPTION"


@pytest.mark.parametrize("quantity", [2.01, 100])
def test_fill_cannot_exceed_displayed_top_side_capacity(valid_case, quantity):
    path, seal, plan, candidate, issue, execution, fill = valid_case
    assert (
        _assessment(
            path, seal, candidate, replace(fill, quantity=quantity), plan.template.side, issue, execution
        ).reason
        == "FILL_EXCEEDS_SAME_SNAPSHOT_TOP_SIDE_CAPACITY"
    )


def test_capacity_uses_ask_for_long_and_bid_for_short(valid_case):
    path, seal, plan, candidate, issue, execution, fill = valid_case
    side = plan.template.side
    low_side_depth = _capture(
        side=side,
        event_ms=execution.quote.event_ms,
        received_ms=execution.received_ms,
        captured_ms=execution.captured_ms,
        bid_quantity=0.5 if side is Side.SHORT else 2.0,
        ask_quantity=0.5 if side is Side.LONG else 2.0,
    )
    adequate_side_depth = _capture(
        side=side,
        event_ms=execution.quote.event_ms,
        received_ms=execution.received_ms,
        captured_ms=execution.captured_ms,
        bid_quantity=2.0 if side is Side.SHORT else 0.5,
        ask_quantity=2.0 if side is Side.LONG else 0.5,
    )
    refused = _assessment(path, seal, candidate, fill, side, issue, low_side_depth)
    accepted = _assessment(path, seal, candidate, fill, side, issue, adequate_side_depth)
    assert refused.reason == "FILL_EXCEEDS_SAME_SNAPSHOT_TOP_SIDE_CAPACITY"
    assert accepted.state == "SIMULATED_CHECK_ONLY"


@pytest.mark.parametrize("offset", [-0.01, 0.0])
def test_favorable_or_equal_to_executable_bbo_fill_is_not_supported(valid_case, offset):
    path, seal, plan, candidate, issue, execution, fill = valid_case
    executable = execution.quote.ask if plan.template.side is Side.LONG else execution.quote.bid
    # Equal is the conservative executable BBO and is supported; only the
    # favorable side of it is forbidden by this model.
    if offset == 0:
        result = _assessment(
            path, seal, candidate, replace(fill, price=executable), plan.template.side, issue, execution
        )
        assert result.state == "SIMULATED_CHECK_ONLY"
    else:
        favorable = executable + offset if plan.template.side is Side.LONG else executable - offset
        result = _assessment(
            path, seal, candidate, replace(fill, price=favorable), plan.template.side, issue, execution
        )
        assert result.reason == "FAVORABLE_FILL_NOT_SUPPORTED_BY_CONSERVATIVE_BBO_MODEL"


@pytest.mark.parametrize("barrier", ["stop", "target", "activation"])
@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT], ids=["long", "short"])
@pytest.mark.parametrize("beyond", [False, True], ids=["equal", "overshoot"])
def test_stop_target_and_trailing_activation_equalities_and_overshoots_are_refused(
    tmp_path, side, barrier, beyond
):
    path, seal, plan, snapshot = _journal(tmp_path, side)
    candidate = snapshot.hypotheses[0].receipts[-1].evaluation.candidate
    observation = snapshot.hypotheses[0].observations[-1]
    close, eligible = observation.market.candle.close_time_ms, candidate.entry_eligible_ts_ms
    issue = _capture(side=side, event_ms=close + 10, received_ms=close + 11, captured_ms=close + 12)
    execution = _capture(side=side, event_ms=eligible + 1, received_ms=eligible + 2, captured_ms=eligible + 3)
    exits = candidate.exit_plan
    if barrier == "stop":
        price = exits.stop_price + (
            -0.01 if side is Side.LONG and beyond else 0.01 if side is Side.SHORT and beyond else 0
        )
    elif barrier == "target":
        price = exits.target_price + (
            0.01 if side is Side.LONG and beyond else -0.01 if side is Side.SHORT and beyond else 0
        )
    else:
        price = exits.trailing_activation_price + (
            0.01 if side is Side.LONG and beyond else -0.01 if side is Side.SHORT and beyond else 0
        )
    fill = SimulatedFill(
        ARM,
        plan.template.intent_id,
        candidate.intent_id,
        SYMBOL,
        side,
        price,
        1,
        eligible + 3,
        plan.protection_sha256,
    )
    assert _assessment(path, seal, candidate, fill, side, issue, execution).state == "REFUSED"


def test_execution_stop_side_breach_is_refused(valid_case):
    path, seal, plan, candidate, issue, execution, fill = valid_case
    side = plan.template.side
    execution = _capture(
        side=side,
        event_ms=execution.quote.event_ms,
        received_ms=execution.received_ms,
        captured_ms=execution.captured_ms,
        bid=98 if side is Side.LONG else 102,
        ask=98.01 if side is Side.LONG else 102.01,
    )
    assert (
        _assessment(path, seal, candidate, fill, side, issue, execution).reason
        == "EXECUTION_EXIT_SIDE_ALREADY_BREACHES_STOP"
    )


@pytest.mark.parametrize("delay", [0, 1])
def test_original_candidate_expiry_is_inclusive_and_fresh_quote_cannot_extend_it(valid_case, delay):
    path, seal, plan, candidate, issue, execution, fill = valid_case
    time = candidate.entry_expires_ts_ms + delay
    execution = _capture(side=plan.template.side, event_ms=time, received_ms=time, captured_ms=time)
    fill = replace(fill, filled_ms=time)
    result = _assessment(path, seal, candidate, fill, plan.template.side, issue, execution)
    assert result.state == ("SIMULATED_CHECK_ONLY" if delay == 0 else "REFUSED"), result.reason
    if delay:
        assert result.reason == "ORIGINAL_ENTRY_DEADLINE_CONFLICT"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"price": True},
        {"price": float("nan")},
        {"price": float("inf")},
        {"quantity": False},
        {"quantity": float("nan")},
        {"quantity": float("inf")},
        {"quantity": 10**400},
        {"filled_ms": True},
    ],
)
def test_malformed_or_nonfinite_simulated_fill_is_rejected(valid_case, kwargs):
    path, seal, plan, candidate, issue, execution, fill = valid_case
    with pytest.raises(ValueError):
        replace(fill, **kwargs)


def test_untyped_fill_side_is_rejected(valid_case):
    path, seal, plan, candidate, issue, execution, fill = valid_case
    with pytest.raises(ValueError):
        replace(fill, side="LONG")


def test_cost_headroom_is_rechecked_at_displaced_fill_not_issuing_reference(valid_case):
    path, seal, plan, candidate, issue, execution, fill = valid_case
    side = plan.template.side
    price = 101.0 if side is Side.LONG else 99.05
    execution = _capture(
        side=side,
        event_ms=execution.quote.event_ms,
        received_ms=execution.received_ms,
        captured_ms=execution.captured_ms,
        bid=price - 0.01 if side is Side.LONG else price,
        ask=price if side is Side.LONG else price + 0.01,
    )
    result = _assessment(path, seal, candidate, replace(fill, price=price), side, issue, execution)
    assert result.reason == "FILL_INSUFFICIENT_UNCHANGED_PLANNING_COST_HEADROOM"


def test_original_frozen_atr_is_rechecked_at_adverse_fill(tmp_path):
    side = Side.LONG
    original = _plan(side)
    plan = replace(
        original,
        template=replace(
            original.template, metadata=original.template.metadata + (("frozen_atr15", "1.25"),)
        ),
    )
    seal = JournalSeal("frozen-atr-fill", START - 1, "a" * 64, (JournalArm(ARM, plan.policy),), 1)
    path = tmp_path / "atr.research.sqlite3"
    journal = HypothesisJournal.create(path, seal)
    journal.register(ARM, plan)
    observation = _obs(START, side, confirming=True)
    candidate = journal.append(ARM, plan.template.intent_id, observation).evaluation.candidate
    assert candidate is not None
    q = observation.quote
    issue = _capture(side=side, event_ms=q.event_ms, received_ms=q.received_ms, captured_ms=q.captured_ms)
    time = candidate.entry_eligible_ts_ms + 3
    execution = _capture(side=side, event_ms=time - 2, received_ms=time - 1, captured_ms=time)
    fill = SimulatedFill(
        ARM,
        plan.template.intent_id,
        candidate.intent_id,
        SYMBOL,
        side,
        100.51,
        1.0,
        time,
        plan.protection_sha256,
    )
    assert _assessment(path, seal, candidate, fill, side, issue, execution).reason == (
        "FILL_STOP_OUTSIDE_ORIGINAL_FROZEN_ATR_BOUNDS"
    )
