"""Strict exact-byte BBO parser fixtures; no feed or provenance claims."""

import hashlib
import json

import pytest
from kairos_core.enums import Side
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_v2 import EntryQuote, HypothesisPlan, HypothesisPolicy
from adaptive_replay.quote_capture import (
    PAYLOAD_SCHEMA,
    SCHEMA,
    BboCapture,
    admit_capture,
)
from adaptive_replay.scenarios import ScenarioEvidence

START = 86_400_000
SYMBOL = "BTCUSDT"


def plan():
    anchor = Candle(SYMBOL, "1m", START - 60_000, START - 1, 100, 101, 99, 100, 10)
    parent = SleeveIntent(
        "trend_breakout_v1",
        SYMBOL,
        Side.LONG,
        START - 1,
        START,
        START + 59_999,
        100,
        0.7,
        500,
        ExitPlan(98, 105, 300_000, 103, 1),
        (("native_marker", "unchanged"),),
    )
    policy = HypothesisPolicy(START - 1, 300_000, "quotes", 5_000, "TEST_FIXTURE", False)
    evidence = ScenarioEvidence(
        "bars",
        "MARKET",
        SYMBOL,
        digest(candle_payload(anchor)),
        START - 1,
        START,
        START,
        600_000,
    )
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


def payload(**changes):
    value = {
        "schema_id": PAYLOAD_SCHEMA,
        "timestamp_unit": "ms",
        "source_id": "quotes",
        "symbol": SYMBOL,
        "event_ms": START + 60_010,
        "bid": 100.49,
        "ask": 100.5,
        "bid_quantity": 1.25,
        "ask_quantity": 2.5,
    }
    value.update(changes)
    return json.dumps(value, separators=(",", ":"), allow_nan=True).encode("utf-8")


def capture(raw=None, **changes):
    raw = payload() if raw is None else raw
    values = {
        "raw_payload": raw,
        "raw_payload_sha256": hashlib.sha256(raw).hexdigest(),
        "received_ms": START + 60_011,
        "captured_ms": START + 60_012,
        "ttl_ms": 5_000,
        "evidence_kind": "TEST_FIXTURE",
    }
    values.update(changes)
    return BboCapture(**values)


def test_capture_retains_exact_bytes_and_exposes_quote_and_base_quantities():
    raw = payload()
    value = capture(raw)

    assert value.raw_payload is raw
    assert value.raw_payload_sha256 == hashlib.sha256(raw).hexdigest()
    assert value.quote == EntryQuote(
        "quotes",
        SYMBOL,
        100.49,
        100.5,
        START + 60_010,
        START + 60_011,
        START + 60_012,
        5_000,
        "TEST_FIXTURE",
    )
    assert (value.bid_quantity, value.ask_quantity) == (1.25, 2.5)
    assert len(value.sha256) == 64
    assert SCHEMA == "kairos.development.bbo-capture.v1"


def test_receipt_digest_binds_original_bytes_even_for_equivalent_json():
    compact = payload()
    spaced = json.dumps(json.loads(compact), indent=2).encode("utf-8")
    first, second = capture(compact), capture(spaced)

    assert first.quote == second.quote
    assert first.raw_payload_sha256 != second.raw_payload_sha256
    assert first.sha256 != second.sha256


@pytest.mark.parametrize("field", ["bid", "ask", "bid_quantity", "ask_quantity"])
@pytest.mark.parametrize("bad", ["1.0", True, float("nan"), float("inf"), "1e999", 10**400, 0, -1])
def test_prices_and_quantities_reject_strings_booleans_nonfinite_and_overflow(field, bad):
    with pytest.raises(ValueError):
        capture(payload(**{field: bad}))


@pytest.mark.parametrize("raw", [b"\xff", b"\xef\xbb\xbf{}", b"[]", b"null", b"[" * 1_100 + b"]" * 1_100])
def test_payload_requires_strict_utf8_without_bom_and_json_object(raw):
    with pytest.raises(ValueError):
        capture(raw)


def test_payload_is_bounded_to_8192_bytes():
    with pytest.raises(ValueError, match="1..8192"):
        capture(b" " * 8_193)


def test_payload_rejects_duplicate_unknown_missing_and_wrong_schema_fields():
    valid = payload().decode("utf-8")
    duplicate = valid[:-1] + ',"bid":100.49}'
    with pytest.raises(ValueError, match="duplicate"):
        capture(duplicate.encode("utf-8"))
    with pytest.raises(ValueError, match="exactly"):
        capture(payload(unexpected=1))
    missing = json.loads(valid)
    del missing["ask_quantity"]
    with pytest.raises(ValueError, match="exactly"):
        capture(json.dumps(missing).encode("utf-8"))
    with pytest.raises(ValueError, match="schema_id"):
        capture(payload(schema_id="other"))


@pytest.mark.parametrize("bid,ask", [(100.5, 100.5), (100.51, 100.5)])
def test_payload_rejects_locked_or_crossed_bbo(bid, ask):
    with pytest.raises(ValueError, match="uncrossed"):
        capture(payload(bid=bid, ask=ask))


def test_raw_hash_and_capture_clock_order_are_required():
    raw = payload()
    with pytest.raises(ValueError, match="exact raw_payload"):
        capture(raw, raw_payload_sha256="0" * 64)
    with pytest.raises(ValueError, match="event <= received <= captured"):
        capture(raw, received_ms=START + 60_009)
    with pytest.raises(ValueError, match="event <= received <= captured"):
        capture(raw, captured_ms=START + 60_010)


def test_admission_matches_plan_and_enforces_event_age_and_capture_cut():
    value = capture()
    p = plan()
    at_ms = START + 60_012
    assert admit_capture(p, value, at_ms, START + 60_010) == value.quote
    for args in (
        (p, value, at_ms, START + 60_011),  # event before required causal boundary
        (p, value, START + 60_011, START + 60_010),  # capture is in the future
        (p, value, START + 66_000, START + 60_010),  # stale event, not refreshed by capture
    ):
        with pytest.raises(ValueError):
            admit_capture(*args)


def test_admission_rejects_source_symbol_and_evidence_mismatch():
    p = plan()
    for raw in (payload(source_id="other"), payload(symbol="ETHUSDT")):
        with pytest.raises(ValueError, match="does not match"):
            admit_capture(p, capture(raw), START + 60_012, START + 60_010)
    with pytest.raises(ValueError, match="does not match"):
        admit_capture(
            p,
            capture(evidence_kind="CALLER_ATTESTED_POINT_IN_TIME"),
            START + 60_012,
            START + 60_010,
        )


def test_new_capture_clock_does_not_refresh_original_event_deadline():
    p = plan()
    value = capture(received_ms=START + 65_011, captured_ms=START + 65_012)
    with pytest.raises(ValueError, match="stale"):
        admit_capture(p, value, START + 65_012, START + 60_010)


@pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"])
def test_explicit_research_universe_is_accepted_without_venue_coverage_claim(symbol):
    value = capture(payload(symbol=symbol))
    assert value.quote.symbol == symbol
