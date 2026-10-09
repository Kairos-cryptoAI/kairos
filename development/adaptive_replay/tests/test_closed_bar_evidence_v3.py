from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from adaptive_replay.closed_bar_evidence_v3 import (
    BOOTSTRAP_POLICY,
    ClosedBarEvidenceError,
    ClosedBarEvidenceFoldV3,
    ReceiptObservationV3,
    RestCandleBarPairV3,
)
from adaptive_replay.rest_candle_receipts_v3 import (
    CandleRequestV3,
    ReceiptCheckpoint,
    RestCandleReceiptStoreV3,
)

SYMBOL = "BTCUSDT"
DELAY_MS = 5_000
ANCHOR = 59_999


def _body(
    open_ms: int,
    *,
    close: str = "100.0",
    trade_count: int = 42,
    ignored_field: str = "0",
    whitespace: bool = False,
) -> bytes:
    row = [
        open_ms,
        "99.0",
        "101.0",
        "98.0",
        close,
        "12.5",
        open_ms + 59_999,
        "1250.0",
        trade_count,
        "3.5",
        "350.0",
        ignored_field,
    ]
    if whitespace:
        return ("[  " + json.dumps(row, separators=(",", ":")) + "  ]\r\n").encode()
    return json.dumps([row], separators=(",", ":")).encode()


def _body_many(open_times: tuple[int, ...]) -> bytes:
    return b"[" + b",".join(_body(open_ms)[1:-1] for open_ms in open_times) + b"]"


def _store(tmp_path: Path):
    ticks = iter(range(2_000_000, 2_100_000))
    return RestCandleReceiptStoreV3.create(tmp_path / "receipt-store", wall_ms=lambda: next(ticks))


def _record(
    store, *, attempt_id: str, raw: bytes | None, status: int | None = 200, failure: str = "INTERRUPTED"
):
    prior = store.attempts[-1].persisted_at_ms if store.attempts else 1_000_000
    request = CandleRequestV3(SYMBOL, 1_500)
    if raw is None and status is None:
        return store.record_no_response(
            attempt_id=attempt_id,
            request=request,
            requested_at_ms=prior,
            failure_kind=failure,
        )
    return store.record_response(
        attempt_id=attempt_id,
        request=request,
        requested_at_ms=prior,
        response_received_at_ms=prior,
        http_status=status,
        raw_response=raw,
    )


def _observations(store, *, process_start: int = 3_000_000):
    results = []
    for index, attempt in enumerate(store.attempts):
        raw = None
        if attempt.state == "HTTP_RESPONSE":
            raw = (store.root / "attempts" / attempt.raw_response_file).read_bytes()
        processed = None if attempt.state == "NO_RESPONSE" else process_start + index
        results.append(ReceiptObservationV3(attempt, raw, processed))
    return tuple(results)


def _fold():
    return ClosedBarEvidenceFoldV3(
        SYMBOL,
        bootstrap_policy=BOOTSTRAP_POLICY,
        restored_through_close_time_ms=ANCHOR,
        finality_delay_ms=DELAY_MS,
    )


def test_full_page_ledger_promotes_two_consecutive_bars_and_reuses_page_attempts(tmp_path):
    store = _store(tmp_path)
    page = _body_many((60_000, 120_000))
    _record(store, attempt_id="page-1", raw=page)
    _record(store, attempt_id="page-2", raw=page)
    fold = _fold()

    results = fold.ingest_receipt_sequence(_observations(store), checkpoint=store.checkpoint)

    assert [result.state for result in results] == ["OBSERVED", "PROMOTED"]
    assert [item.candle.open_time_ms for item in results[1].promoted] == [60_000, 120_000]
    assert results[1].promoted[0].pair.first_attempt is store.attempts[0]
    assert results[1].promoted[1].pair.first_attempt is store.attempts[0]
    assert fold.source_scope == "BOUNDED_POINT_IN_TIME_SAMPLE_NOT_FULL_WARMUP"
    originals = fold.to_candle_originals_v3(ttl_ms=60_000)
    assert len(originals.records) == 2
    assert all(item.available_at_ms >= item.evidence.captured_ms for item in originals.records)


def test_changed_observation_resets_count_a_b_a_a_promotes_only_after_final_a(tmp_path):
    store = _store(tmp_path)
    for index, close in enumerate(("100.0", "100.25", "100.0", "100.0"), start=1):
        _record(store, attempt_id=f"observation-{index}", raw=_body(60_000, close=close))
    fold = _fold()

    results = fold.ingest_receipt_sequence(_observations(store), checkpoint=store.checkpoint)

    assert [result.state for result in results] == ["OBSERVED", "OBSERVED", "OBSERVED", "PROMOTED"]
    promoted = results[-1].promoted
    assert len(promoted) == 1
    assert promoted[0].candle.close == 100.0
    assert promoted[0].pair.first_attempt.attempt_id == "observation-3"
    assert promoted[0].pair.second_attempt.attempt_id == "observation-4"


def test_receipt_clock_tampering_with_unchanged_receipt_hash_is_rejected(tmp_path):
    store = _store(tmp_path)
    _record(store, attempt_id="page-1", raw=_body(60_000))
    _record(store, attempt_id="page-2", raw=_body(60_000))
    observations = list(_observations(store))
    forged_attempt = replace(
        observations[0].attempt, persisted_at_ms=observations[0].attempt.persisted_at_ms + 1
    )
    observations[0] = replace(observations[0], attempt=forged_attempt)

    with pytest.raises(ClosedBarEvidenceError, match="canonical receipt hash"):
        _fold().ingest_receipt_sequence(tuple(observations), checkpoint=store.checkpoint)


def test_forged_direct_pair_or_replaced_row_is_rejected(tmp_path):
    store = _store(tmp_path)
    body = _body(60_000, whitespace=True)
    first = _record(store, attempt_id="page-1", raw=body)
    second = _record(store, attempt_id="page-2", raw=body)
    pair = RestCandleBarPairV3.from_attempts(
        first, body, second, body, open_time_ms=60_000, finality_delay_ms=DELAY_MS
    )

    with pytest.raises(ClosedBarEvidenceError, match="does not match normalized row"):
        replace(pair, candle=replace(pair.candle, close=101.0))
    with pytest.raises(ClosedBarEvidenceError, match="canonical receipt hash"):
        forged = replace(second, persisted_at_ms=second.persisted_at_ms + 1)
        RestCandleBarPairV3.from_attempts(
            first, body, forged, body, open_time_ms=60_000, finality_delay_ms=DELAY_MS
        )


def test_omitted_intervening_receipt_breaks_complete_sequence_chain(tmp_path):
    store = _store(tmp_path)
    for index in range(3):
        _record(store, attempt_id=f"attempt-{index}", raw=_body(60_000))
    incomplete = _observations(store)[::2]
    checkpoint = ReceiptCheckpoint(2, incomplete[-1].attempt.receipt_sha256)

    with pytest.raises(ClosedBarEvidenceError, match="omitted, reordered, or unchained"):
        _fold().ingest_receipt_sequence(incomplete, checkpoint=checkpoint)


def test_request_clock_rollback_after_previous_body_fsync_is_rejected(tmp_path):
    store = _store(tmp_path)
    first = _record(store, attempt_id="attempt-1", raw=_body(60_000))
    store.record_response(
        attempt_id="attempt-2",
        request=CandleRequestV3(SYMBOL, 1_500),
        requested_at_ms=first.persisted_at_ms - 1,
        response_received_at_ms=first.persisted_at_ms - 1,
        http_status=200,
        raw_response=_body(60_000),
    )

    with pytest.raises(ClosedBarEvidenceError, match="next request clock predates"):
        _fold().ingest_receipt_sequence(_observations(store), checkpoint=store.checkpoint)


def test_failed_malformed_and_no_response_attempts_remain_in_denominator(tmp_path):
    store = _store(tmp_path)
    _record(store, attempt_id="bad-json", raw=b"{ malformed response retained exactly")
    _record(store, attempt_id="http-error", raw=b'{"error":"busy"}', status=429)
    _record(store, attempt_id="interrupted", raw=None, status=None)
    _record(store, attempt_id="good-1", raw=_body(60_000))
    _record(store, attempt_id="good-2", raw=_body(60_000))
    fold = _fold()

    results = fold.ingest_receipt_sequence(_observations(store), checkpoint=store.checkpoint)

    assert [item.state for item in results] == [
        "MALFORMED",
        "HTTP_FAILURE",
        "NO_RESPONSE",
        "OBSERVED",
        "PROMOTED",
    ]
    assert [item.attempt_number for item in results] == [1, 2, 3, 4, 5]
    assert len(results[-1].promoted) == 1


def test_bootstrap_requires_explicit_anchor_policy_and_anchor(tmp_path):
    with pytest.raises(ClosedBarEvidenceError, match="explicit ANCHORED_PRIOR_BAR"):
        ClosedBarEvidenceFoldV3(SYMBOL, bootstrap_policy="", restored_through_close_time_ms=ANCHOR)
    with pytest.raises(TypeError):
        ClosedBarEvidenceFoldV3(SYMBOL, bootstrap_policy=BOOTSTRAP_POLICY)


def test_receipt_request_sequence_is_audited_and_not_limited_to_one_bar(tmp_path):
    store = _store(tmp_path)
    page = _body_many((60_000, 120_000))
    _record(store, attempt_id="page-1", raw=page)
    _record(store, attempt_id="page-2", raw=page)
    results = _fold().ingest_receipt_sequence(_observations(store), checkpoint=store.checkpoint)

    assert results[-1].page_open_times_ms == (60_000, 120_000)
    assert len(results[-1].promoted) == 2


def test_pending_gap_is_not_usable_until_missing_predecessor_arrives(tmp_path):
    store = _store(tmp_path)
    gap_page = _body_many((60_000, 180_000))
    fill_page = _body(120_000)
    _record(store, attempt_id="gap-1", raw=gap_page)
    _record(store, attempt_id="gap-2", raw=gap_page)
    _record(store, attempt_id="fill-1", raw=fill_page)
    _record(store, attempt_id="fill-2", raw=fill_page)

    fold = _fold()
    results = fold.ingest_receipt_sequence(_observations(store), checkpoint=store.checkpoint)

    assert results[1].pending_close_times_ms == (239_999,)
    assert [item.candle.open_time_ms for item in results[1].promoted] == [60_000]
    assert [item.candle.open_time_ms for item in results[-1].promoted] == [120_000, 180_000]
    assert [item.candle.open_time_ms for item in fold.to_candle_originals_v3(ttl_ms=60_000).records] == [
        60_000,
        120_000,
        180_000,
    ]


def test_first_changed_final_row_blocks_an_already_promoted_bar_immediately(tmp_path):
    store = _store(tmp_path)
    _record(store, attempt_id="bar-a1", raw=_body(60_000, close="100.0"))
    _record(store, attempt_id="bar-a2", raw=_body(60_000, close="100.0"))
    _record(store, attempt_id="bar-b1", raw=_body(60_000, close="100.25"))
    fold = _fold()

    results = fold.ingest_receipt_sequence(_observations(store), checkpoint=store.checkpoint)

    assert results[1].state == "PROMOTED"
    assert results[2].state == "BLOCKED"
    assert fold.blocked_reason == "conflicting_closed_bar"
    with pytest.raises(ClosedBarEvidenceError, match="blocked fold"):
        fold.to_candle_originals_v3(ttl_ms=60_000)


def test_trade_count_and_ignored_slot_are_retained_but_do_not_reset_native_count(tmp_path):
    store = _store(tmp_path)
    first_body = _body(60_000, trade_count=42, ignored_field="0")
    second_body = _body(60_000, trade_count=43, ignored_field="different ignored metadata")
    third_body = _body(60_000, trade_count=44, ignored_field="another value")
    _record(store, attempt_id="metadata-1", raw=first_body)
    _record(store, attempt_id="metadata-2", raw=second_body)
    _record(store, attempt_id="metadata-3", raw=third_body)
    fold = _fold()

    results = fold.ingest_receipt_sequence(_observations(store), checkpoint=store.checkpoint)

    promoted = results[1].promoted
    assert len(promoted) == 1
    assert promoted[0].pair.first_raw_response == first_body
    assert promoted[0].pair.second_raw_response == second_body
    assert promoted[0].pair.first_row.trade_count == 42
    assert promoted[0].pair.first_row.ignored_field == "0"
    assert promoted[0].pair.row.trade_count == 43
    assert promoted[0].pair.row.ignored_field == "different ignored metadata"
    assert results[2].state == "OBSERVED"
    assert fold.blocked_reason is None


@pytest.mark.parametrize("slot,value", [(8, "not-an-integer"), (11, None)])
def test_malformed_metadata_is_rejected_even_when_native_projection_is_unchanged(tmp_path, slot, value):
    store = _store(tmp_path)
    malformed_row = json.loads(_body(60_000))
    malformed_row[0][slot] = value
    _record(store, attempt_id="metadata-bad", raw=json.dumps(malformed_row).encode())

    result = _fold().ingest_receipt_sequence(_observations(store), checkpoint=store.checkpoint)[0]

    assert result.state == "MALFORMED"
    assert result.page_open_times_ms == ()


def test_restored_through_overlap_is_recorded_but_not_counted_or_promoted(tmp_path):
    store = _store(tmp_path)
    page = _body_many((0, 60_000, 120_000))
    _record(store, attempt_id="page-1", raw=page)
    _record(store, attempt_id="page-2", raw=page)
    fold = ClosedBarEvidenceFoldV3(
        SYMBOL,
        bootstrap_policy=BOOTSTRAP_POLICY,
        restored_through_close_time_ms=119_999,
        finality_delay_ms=DELAY_MS,
    )

    results = fold.ingest_receipt_sequence(_observations(store), checkpoint=store.checkpoint)

    assert results[1].page_open_times_ms == (0, 60_000, 120_000)
    assert [item.candle.open_time_ms for item in results[1].promoted] == [120_000]
    assert [item.candle.open_time_ms for item in fold.to_candle_originals_v3(ttl_ms=60_000).records] == [
        120_000
    ]
    assert fold.restored_through_close_time_ms == 119_999


def test_changed_pending_bar_still_requires_two_observations_like_native(tmp_path):
    store = _store(tmp_path)
    _record(store, attempt_id="anchor-1", raw=_body(60_000))
    _record(store, attempt_id="anchor-2", raw=_body(60_000))
    _record(store, attempt_id="pending-1", raw=_body(180_000, close="100.0"))
    _record(store, attempt_id="pending-2", raw=_body(180_000, close="100.0"))
    _record(store, attempt_id="changed-1", raw=_body(180_000, close="100.25"))
    _record(store, attempt_id="changed-2", raw=_body(180_000, close="100.25"))
    fold = _fold()

    results = fold.ingest_receipt_sequence(_observations(store), checkpoint=store.checkpoint)

    assert results[4].state == "OBSERVED"
    assert results[4].blocked_reason is None
    assert results[5].state == "BLOCKED"
    assert fold.blocked_reason == "conflicting_closed_bar"
