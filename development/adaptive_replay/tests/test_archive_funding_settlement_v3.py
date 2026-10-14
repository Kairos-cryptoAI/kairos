from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal

import pytest

from adaptive_replay.archive_funding_rate_v3 import load_original_funding_archive_v3
from adaptive_replay.archive_funding_settlement_v3 import (
    DAY_MS,
    MAX_RESPONSE_BYTES,
    FundingRESTCaptureV3,
    load_funding_settlement_window_v3,
)

from .test_archive_funding_rate_v3 import START, _archive


def _case(tmp_path):
    path, kwargs, _ = _archive(tmp_path)
    original = load_original_funding_archive_v3(path, **kwargs)
    events = [
        {
            "symbol": row.symbol,
            "fundingRate": str(row.rate),
            "fundingTime": row.exchange_calc_time_ms,
            "markPrice": "12345.123456789123456789123456789",
            "rateType": "Regular",
        }
        for row in original.window(START, START + 6 * DAY_MS)
    ]
    body = json.dumps(events).encode()
    capture = FundingRESTCaptureV3(
        START + 100 * DAY_MS,
        START + 100 * DAY_MS + 10,
        START + 100 * DAY_MS + 11,
        "a" * 64,
        hashlib.sha256(body).hexdigest(),
    )
    return (
        path,
        {
            **kwargs,
            "start_ms": START,
            "end_ms": START + 6 * DAY_MS,
            "response_body": body,
            "capture": capture,
        },
        events,
    )


def _body(kwargs, events):
    body = json.dumps(events).encode()
    return {
        **kwargs,
        "response_body": body,
        "capture": replace(kwargs["capture"], response_body_sha256=hashlib.sha256(body).hexdigest()),
    }


def test_complete_rate_calc_time_price_join_and_accounting_calendar(tmp_path):
    path, kwargs, _ = _case(tmp_path)
    result = load_funding_settlement_window_v3(path, **kwargs)
    assert len(result.records) == 18
    assert result.records[1].rate_record.exchange_calc_time_ms != result.records[1].rate_record.due_at_ms
    assert result.records[1].rate_record.rate == Decimal("-0.000000000000000000009")
    assert result.records[0].settlement_price == Decimal("12345.123456789123456789123456789")
    calendar = result.calendar(feed_delay_ms=10, processing_delay_ms=20)
    assert len(calendar.expected_due) == len(calendar.receipts) == 18
    assert (
        calendar.receipts[1].modeled_available_at_ms
        == result.records[1].rate_record.exchange_calc_time_ms + 30
    )
    assert calendar.receipts[1].original_record_sha256 == result.records[1].rate_record.raw_record_sha256
    assert (
        calendar.receipts[1].settlement_price_source_sha256
        == result.records[1].settlement_price_source_sha256
    )
    assert calendar.receipts[1].status == "KNOWN"
    assert calendar.receipts[1].rate < 0
    assert result.historical_received_at_ms is None
    assert result.source_admitted is False
    assert result.funding_for_entry_decisions is False
    assert result.capture.request_wall_ms > result.end_ms


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "extra",
        "duplicate",
        "reverse",
        "symbol",
        "rate",
        "rounded-clock",
        "future-clock",
        "zero-price",
        "negative-price",
        "float-price",
        "nan-price",
        "nan-rate",
        "float-clock",
        "bool-clock",
        "missing-field",
        "extra-field",
        "special",
        "huge-exponent",
    ],
)
def test_source_schema_complete_grain_and_exact_original_join_fail_closed(tmp_path, change):
    path, kwargs, events = _case(tmp_path)
    if change == "missing":
        events.pop()
    elif change == "extra":
        events.append(events[-1])
    elif change == "duplicate":
        events[1] = events[0]
    elif change == "reverse":
        events.reverse()
    elif change == "symbol":
        events[0]["symbol"] = "ETHUSDT"
    elif change == "rate":
        events[0]["fundingRate"] = "0.0002"
    elif change == "rounded-clock":
        events[1]["fundingTime"] -= 1
    elif change == "future-clock":
        events[-1]["fundingTime"] = kwargs["end_ms"]
    elif change in {"zero-price", "negative-price", "float-price", "nan-price", "huge-exponent"}:
        events[0]["markPrice"] = {
            "zero-price": "0",
            "negative-price": "-1",
            "float-price": 12345.0,
            "nan-price": "NaN",
            "huge-exponent": "1e999",
        }[change]
    elif change == "nan-rate":
        events[0]["fundingRate"] = "NaN"
    elif change in {"float-clock", "bool-clock"}:
        events[0]["fundingTime"] = 1.0 if change == "float-clock" else True
    elif change == "missing-field":
        events[0].pop("markPrice")
    elif change == "extra-field":
        events[0]["unknown"] = "unplanned"
    elif change == "special":
        events[0]["rateType"] = "Special"
    with pytest.raises(ValueError):
        load_funding_settlement_window_v3(path, **_body(kwargs, events))


def test_original_decimal_zero_is_no_payment_not_missing_price(tmp_path):
    path, kwargs, events = _case(tmp_path)
    # Change fixture source before its independently retained pins, not retained original evidence.
    from adaptive_replay.archive_funding_rate_v3 import HEADER

    from .test_archive_funding_rate_v3 import ROSTER

    payload = HEADER + b"\n" + b"".join(f"{r.due_at_ms},8,0E-8\n".encode() for r in ROSTER)
    path, archive_kwargs, _ = _archive(tmp_path, payload=payload)
    for event, row in zip(events, ROSTER, strict=False):
        event["fundingTime"], event["fundingRate"] = row.due_at_ms, "0.00000000"
    result = load_funding_settlement_window_v3(path, **_body({**kwargs, **archive_kwargs}, events))
    assert all(r.rate_record.rate.as_tuple() == Decimal("0E-8").as_tuple() for r in result.records)
    assert all(
        r.status == "NO_PAYMENT" for r in result.calendar(feed_delay_ms=0, processing_delay_ms=0).receipts
    )


def test_optional_regular_field_is_compatible_without_rewriting_body(tmp_path):
    path, kwargs, events = _case(tmp_path)
    for event in events:
        event.pop("rateType")
    kwargs = _body(kwargs, events)
    result = load_funding_settlement_window_v3(path, **kwargs)
    assert result.capture.response_body_sha256 == hashlib.sha256(kwargs["response_body"]).hexdigest()


def test_duplicate_json_keys_and_mutated_original_body_refused(tmp_path):
    path, kwargs, _ = _case(tmp_path)
    duplicate = kwargs["response_body"].replace(
        b'"symbol": "BTCUSDT"', b'"symbol":"BTCUSDT","symbol":"BTCUSDT"', 1
    )
    changed = {
        **kwargs,
        "response_body": duplicate,
        "capture": replace(kwargs["capture"], response_body_sha256=hashlib.sha256(duplicate).hexdigest()),
    }
    with pytest.raises(ValueError, match="duplicate"):
        load_funding_settlement_window_v3(path, **changed)
    with pytest.raises(ValueError, match="byte hash"):
        load_funding_settlement_window_v3(path, **{**kwargs, "response_body": kwargs["response_body"] + b" "})


@pytest.mark.parametrize(
    "field,value", [("start_ms", True), ("end_ms", START + 5 * DAY_MS), ("start_ms", START + 1)]
)
def test_fixed_six_day_window_cannot_be_changed(tmp_path, field, value):
    path, kwargs, _ = _case(tmp_path)
    with pytest.raises(ValueError):
        load_funding_settlement_window_v3(path, **{**kwargs, field: value})


def test_wall_clocks_remain_separate_and_complete_body_is_bounded(tmp_path):
    path, kwargs, _ = _case(tmp_path)
    with pytest.raises(ValueError, match="wall"):
        load_funding_settlement_window_v3(
            path, **{**kwargs, "capture": replace(kwargs["capture"], request_wall_ms=START)}
        )
    with pytest.raises(ValueError, match="acquisition"):
        replace(kwargs["capture"], response_wall_ms=kwargs["capture"].captured_wall_ms + 1)
    with pytest.raises(ValueError, match="bounded complete"):
        load_funding_settlement_window_v3(
            path, **{**kwargs, "response_body": b" " * (MAX_RESPONSE_BYTES + 1)}
        )


def test_monthly_and_joined_evidence_mutations_cannot_be_used(tmp_path):
    path, kwargs, _ = _case(tmp_path)
    result = load_funding_settlement_window_v3(path, **kwargs)
    with pytest.raises(ValueError, match="evidence changed"):
        replace(
            result, records=(*result.records[:-1], replace(result.records[-1], settlement_price=Decimal(2)))
        ).calendar(feed_delay_ms=0, processing_delay_ms=0)
    with path.open("ab") as stream:
        stream.write(b"changed-after-capture")
    with pytest.raises(ValueError, match="archive hash"):
        load_funding_settlement_window_v3(path, **kwargs)


@pytest.mark.parametrize("delay", [True, -1, 86_400_001])
def test_modeled_delivery_delay_is_explicit_and_bounded(tmp_path, delay):
    path, kwargs, _ = _case(tmp_path)
    result = load_funding_settlement_window_v3(path, **kwargs)
    with pytest.raises(ValueError):
        result.calendar(feed_delay_ms=delay, processing_delay_ms=0)
