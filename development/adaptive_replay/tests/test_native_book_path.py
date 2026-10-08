"""Synthetic raw native book -> journal -> supplied fill path; no economics."""

import hashlib
import json

import pytest
from kairos_core.contracts.simulation import RecordedBookLevelV1, RecordedTopNBookFrameV2
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay.fill_feasibility import SimulatedFill, assess_journal_simulated_fill
from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_journal import HypothesisJournal, JournalArm, JournalSeal
from adaptive_replay.hypothesis_v2 import HypothesisObservation, HypothesisPlan, HypothesisPolicy
from adaptive_replay.native_book_capture import (
    MIGRATED_PROFILE,
    NativeBookCapture,
    NativeBookPolicy,
    audit_book_prefix,
)
from adaptive_replay.scenarios import MINUTE, ScenarioEvidence, ScenarioObservation

START = 86_400_000
SYMBOL = "BTCUSDT"


def bar(open_ms, close=100.0):
    return Candle(SYMBOL, "1m", open_ms, open_ms + MINUTE - 1, 100, 101, 99, close, 10)


def evidence(candle):
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


def native_frame(side, event, sequence, previous=None):
    bid, ask = ("100.49", "100.50") if side is Side.LONG else ("99.50", "99.51")
    body = {
        "e": "depthUpdate",
        "E": event,
        "T": event - 1,
        "s": SYMBOL,
        "U": 10 * sequence,
        "u": 10 * sequence + 1,
        "pu": 0 if sequence == 1 else 11,
        "b": [[bid, "2.0"]],
        "a": [[ask, "2.0"]],
        "st": 1,
        "ps": SYMBOL,
    }
    raw = json.dumps({"stream": "btcusdt@depth10@100ms", "data": body}, separators=(",", ":"))
    return RecordedTopNBookFrameV2(
        source="offline-native-fixture",
        tape_id="fixture-tape",
        stream_epoch="fixture-epoch",
        symbol=SYMBOL,
        tape_sequence=sequence,
        exchange_update_id=body["u"],
        exchange_at_ms=event,
        received_at_ms=event + 1,
        persisted_at_ms=event + 2,
        raw_payload=raw,
        raw_payload_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        previous_frame_sha256=previous,
        continuity="ADMITTED",
        source_reason="OFFLINE_FIXTURE",
        bids=(RecordedBookLevelV1(price=float(bid), quantity=2.0),),
        asks=(RecordedBookLevelV1(price=float(ask), quantity=2.0),),
    )


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_native_byte_binding_to_journal_and_supplied_fill_is_offline_read_only(tmp_path, side):
    anchor = bar(START - MINUTE)
    sign = 1 if side is Side.LONG else -1
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
    quote_policy = NativeBookPolicy(MIGRATED_PROFILE, "quotes", 5_000, "TEST_FIXTURE")
    policy = HypothesisPolicy(
        START - 1, 5 * MINUTE, quote_policy.quote_source_id, 5_000, "TEST_FIXTURE", False
    )
    plan = HypothesisPlan(
        parent,
        "TECHNICAL",
        "BULL" if side is Side.LONG else "BEAR",
        START,
        "a" * 64,
        "b" * 64,
        (evidence(anchor),),
        anchor,
        (("MARKET", "bars"),),
        policy,
    )
    seal = JournalSeal("native-path-fixture", START - 1, "a" * 64, (JournalArm("native", policy),), 4)
    path = tmp_path / "native.research.sqlite3"
    journal = HypothesisJournal.create(path, seal)
    journal.register("native", plan)
    first = bar(START)
    journal.append(
        "native",
        parent.intent_id,
        HypothesisObservation(
            ScenarioObservation(first, first.close_time_ms + 20, (evidence(first),)),
            None,
        ),
    )
    confirmation = bar(START + MINUTE, 100.5 if side is Side.LONG else 99.5)
    issuing = NativeBookCapture(native_frame(side, confirmation.close_time_ms + 10, 1), quote_policy)
    receipt = journal.append(
        "native",
        parent.intent_id,
        HypothesisObservation(
            ScenarioObservation(confirmation, confirmation.close_time_ms + 20, (evidence(confirmation),)),
            issuing.capture.quote,
        ),
    )
    candidate = receipt.evaluation.candidate
    assert candidate is not None
    assert candidate.exit_plan == parent.exit_plan
    executable = NativeBookCapture(
        native_frame(
            side,
            candidate.entry_eligible_ts_ms + 1,
            2,
            issuing.frame.frame_sha256,
        ),
        quote_policy,
    )
    fill = SimulatedFill(
        "native",
        parent.intent_id,
        candidate.intent_id,
        SYMBOL,
        side,
        100.505 if side is Side.LONG else 99.495,
        1.0,
        executable.frame.persisted_at_ms,
        plan.protection_sha256,
    )
    prefix = audit_book_prefix(
        (issuing.frame, executable.frame),
        quote_policy,
        tape_id="fixture-tape",
        stream_epoch="fixture-epoch",
        expected_head_sha256=executable.frame.frame_sha256,
        asof_ms=fill.filled_ms,
    )
    assert dict(prefix.symbol_counts) == {
        symbol: 2 if symbol == SYMBOL else 0
        for symbol in (
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "BNBUSDT",
            "XRPUSDT",
        )
    }
    assert prefix.risk_authority == "NONE"
    assert "NOT_CONTINUOUS" in prefix.coverage_authority
    before = path.read_bytes()
    assessment = assess_journal_simulated_fill(
        journal_path=path,
        seal=seal,
        candidate=candidate,
        fill=fill,
        issue_capture=issuing.capture,
        execution_capture=executable.capture,
    )
    assert (assessment.state, assessment.risk_authority) == ("SIMULATED_CHECK_ONLY", "NONE")
    assert path.read_bytes() == before
    assert issuing.frame.raw_payload_sha256 != issuing.capture.raw_payload_sha256
    assert executable.frame.raw_payload_sha256 != executable.capture.raw_payload_sha256
    assert len(issuing.sha256) == len(executable.sha256) == 64
    assert (
        HypothesisJournal.open(path, seal).snapshot().hypotheses[0].receipts[-1].evaluation.candidate
        == candidate
    )


def test_copied_frame_with_non_utf8_text_is_refused_without_serializer_output():
    frame = native_frame(Side.LONG, START, 1).model_copy(update={"raw_payload": "\ud800"})
    with pytest.raises(ValueError, match="strict UTF-8"):
        NativeBookCapture(frame, NativeBookPolicy(MIGRATED_PROFILE, "quotes", 5_000, "TEST_FIXTURE"))


@pytest.mark.parametrize("kind", ["empty", "oversize", "list"])
def test_prefix_input_bounds_do_not_imply_sampled_or_complete_coverage(kind):
    frame = native_frame(Side.LONG, START, 1)
    frames = () if kind == "empty" else ((frame,) * 513 if kind == "oversize" else [frame])
    with pytest.raises(ValueError, match="bounded immutable"):
        audit_book_prefix(
            frames,
            NativeBookPolicy(MIGRATED_PROFILE, "quotes", 5_000, "TEST_FIXTURE"),
            tape_id="fixture-tape",
            stream_epoch="fixture-epoch",
            expected_head_sha256=frame.frame_sha256,
            asof_ms=START + 2,
        )
