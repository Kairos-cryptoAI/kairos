"""Consistency tests for normalized V3 candle originals, not source proof."""

from dataclasses import replace
from decimal import Decimal

import pytest
from kairos_strategy.candles import Candle
from kairos_strategy.provenance import candle_payload

from adaptive_replay.candle_originals_v3 import CandleOriginalsV3, RetainedCandleV3
from adaptive_replay.continuous_sim import ClosedCandleInput, TapeBinding, TapeInput
from adaptive_replay.historical_context import digest
from adaptive_replay.scenarios import MINUTE, ScenarioEvidence

OPEN = 86_400_000
SYMBOL = "BTCUSDT"


def _candle(open_ms=OPEN, *, high=101.0, volume=10.0, close=100.0):
    return Candle(SYMBOL, "1m", open_ms, open_ms + MINUTE - 1, 100.0, high, 99.0, close, volume)


def _evidence(candle, *, source_id="bars", captured=None):
    closed = candle.close_time_ms
    captured = closed + 5 if captured is None else captured
    return ScenarioEvidence(
        source_id,
        "MARKET",
        candle.symbol,
        digest(candle_payload(candle)),
        closed,
        captured,
        captured,
        600_000,
    )


def _record(candle=None, *, evidence=None, available=None, kind="TEST_FIXTURE"):
    candle = _candle() if candle is None else candle
    evidence = _evidence(candle) if evidence is None else evidence
    available = evidence.captured_ms + 20 if available is None else available
    return RetainedCandleV3(candle, evidence, available, kind)


def _binding(record, *, available=None, close=None, source_id=None, payload_sha256=None):
    evidence, candle = record.evidence, record.candle
    value = ClosedCandleInput(
        candle.symbol,
        candle.open_time_ms,
        candle.close_time_ms,
        record.available_at_ms if available is None else available,
        Decimal(str(candle.close)) if close is None else close,
        evidence.source_id if source_id is None else source_id,
        record.evidence_kind,
        evidence.payload_sha256 if payload_sha256 is None else payload_sha256,
    )
    return TapeBinding("sim", "tape", "epoch", "quotes", record.evidence_kind, (TapeInput(1, value),))


def test_exact_original_finds_only_after_retained_availability_and_binds():
    record = _record()
    originals = CandleOriginalsV3((record,))

    assert originals.find(record.candle, record.evidence, record.available_at_ms) is record
    assert len(originals.sha256) == 64
    originals.validate_binding(_binding(record))

    with pytest.raises(ValueError, match="not yet available"):
        originals.find(record.candle, record.evidence, record.available_at_ms - 1)


def test_rejects_invalid_bar_shape_and_bool_receipt_clock():
    candle = _candle()
    evidence = _evidence(candle)
    with pytest.raises(ValueError):
        RetainedCandleV3(candle, evidence, True, "TEST_FIXTURE")
    with pytest.raises(ValueError, match="closed 1m"):
        RetainedCandleV3(
            replace(candle, close_time_ms=candle.close_time_ms + 1),
            evidence,
            evidence.captured_ms,
            "TEST_FIXTURE",
        )
    with pytest.raises(ValueError, match="causal clocks"):
        RetainedCandleV3(candle, evidence, evidence.captured_ms - 1, "TEST_FIXTURE")


def test_rejects_market_receipt_that_does_not_bind_full_bar_payload():
    candle = _candle()
    wrong_receipt = _evidence(_candle(high=102.0))
    with pytest.raises(ValueError, match="exact closed candle"):
        _record(candle, evidence=wrong_receipt)


def test_rejects_nonmarket_or_mismatched_event_evidence():
    candle = _candle()
    valid = _evidence(candle)
    with pytest.raises(ValueError, match="exact closed candle"):
        _record(candle, evidence=replace(valid, kind="NEWS"))
    with pytest.raises(ValueError, match="exact closed candle"):
        _record(candle, evidence=replace(valid, event_ms=valid.event_ms - 1))


def test_rejects_unknown_candle_and_ohlc_volume_rewrite():
    record = _record()
    originals = CandleOriginalsV3((record,))
    unknown = _candle(open_ms=OPEN + MINUTE)
    with pytest.raises(ValueError, match="not retained"):
        originals.find(unknown, _evidence(unknown), record.available_at_ms)

    changed = _candle(high=102.0, volume=11.0)
    with pytest.raises(ValueError, match="not retained"):
        originals.find(changed, record.evidence, record.available_at_ms)
    with pytest.raises(ValueError, match="retained original"):
        originals.validate_binding(_binding(record, payload_sha256=digest(candle_payload(changed))))


def test_binding_rejects_receipt_clock_close_and_source_tampering():
    record = _record()
    originals = CandleOriginalsV3((record,))
    with pytest.raises(ValueError, match="retained original receipt"):
        originals.validate_binding(_binding(record, available=record.available_at_ms + 1))
    with pytest.raises(ValueError, match="retained original receipt"):
        originals.validate_binding(_binding(record, close=Decimal("100.01")))
    with pytest.raises(ValueError, match="retained original receipt"):
        originals.validate_binding(_binding(record, source_id="other"))


def test_preserves_later_promotion_delay_as_availability():
    candle = _candle()
    evidence = _evidence(candle)
    delayed = _record(candle, evidence=evidence, available=evidence.captured_ms + 9_000)
    originals = CandleOriginalsV3((delayed,))
    with pytest.raises(ValueError, match="not yet available"):
        originals.find(candle, evidence, evidence.captured_ms + 8_999)
    assert originals.find(candle, evidence, delayed.available_at_ms) is delayed
    originals.validate_binding(_binding(delayed))


def test_rejects_mixed_evidence_classes_and_binding_downgrade():
    first = _record()
    second_candle = _candle(open_ms=OPEN + MINUTE)
    second = _record(second_candle, kind="CALLER_ATTESTED_POINT_IN_TIME")
    with pytest.raises(ValueError, match="cannot be mixed"):
        CandleOriginalsV3((first, second))

    originals = CandleOriginalsV3((first,))
    downgraded = _binding(first)
    object.__setattr__(downgraded, "evidence_kind", "CALLER_ATTESTED_POINT_IN_TIME")
    with pytest.raises(ValueError, match="evidence classes"):
        originals.validate_binding(downgraded)


def test_rejects_noncanonical_order_and_duplicate_identity():
    first = _record()
    later_candle = _candle(open_ms=OPEN + MINUTE)
    later = _record(later_candle)
    with pytest.raises(ValueError, match="canonical"):
        CandleOriginalsV3((later, first))
    conflict = _record(_candle(high=102.0))
    with pytest.raises(ValueError, match="duplicate or conflicting"):
        CandleOriginalsV3((first, conflict))
