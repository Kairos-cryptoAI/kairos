from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from adaptive_replay.archive_market_clock_v3 import ArchiveMarketClockV3, archive_quote_v3
from adaptive_replay.bookticker_archive_stream_v3 import _parse_row

SOURCE = "a" * 64
RAW = b"10,100.00,1.250,100.10,2.00,1704672000006,1704672000012\r\n"


def _row(raw=RAW):
    return _parse_row(raw, "BTCUSDT", "2024-01-08", 0)


@pytest.mark.parametrize("basis,event", [("TRANSACTION_T", 1704672000006), ("EVENT_E", 1704672000012)])
def test_explicit_exchange_basis_never_exposes_before_e(basis, event):
    clock = ArchiveMarketClockV3(basis, 4, 7)
    quote = archive_quote_v3(_row(), clock=clock, source_manifest_sha256=SOURCE)
    assert quote.event_at_ms == event
    assert quote.modeled_available_at_ms == 1704672000023
    assert quote.historical_received_at_ms is None
    assert quote.historical_persisted_at_ms is None
    assert quote.stream_kind == "TOP_OF_BOOK_ONLY"
    assert quote.clock_evidence == "MODEL_NOT_OBSERVED_HISTORICAL_RECEIPT"
    assert quote.bid_price == Decimal("100.00")
    assert str(quote.bid_qty) == "1.250"
    assert not hasattr(quote, "admitted")
    with pytest.raises(FrozenInstanceError):
        quote.bid_qty = Decimal(9)


def test_no_hidden_timing_default_and_policy_is_frozen():
    with pytest.raises(TypeError):
        ArchiveMarketClockV3("EVENT_E")
    zero = ArchiveMarketClockV3("EVENT_E", 0, 0)
    assert (
        archive_quote_v3(_row(), clock=zero, source_manifest_sha256=SOURCE).modeled_available_at_ms
        == 1704672000012
    )
    assert (
        len(
            {
                zero.sha256,
                ArchiveMarketClockV3("TRANSACTION_T", 0, 0).sha256,
                ArchiveMarketClockV3("EVENT_E", 1, 0).sha256,
            }
        )
        == 3
    )
    with pytest.raises(FrozenInstanceError):
        zero.feed_delay_ms = 1


@pytest.mark.parametrize(
    "args",
    [("AUTO", 0, 0), ("EVENT_E", True, 0), ("EVENT_E", -1, 0), ("EVENT_E", 0, 60001), ("EVENT_E", 0, 1.0)],
)
def test_invalid_model_policy(args):
    with pytest.raises(ValueError):
        ArchiveMarketClockV3(*args)


@pytest.mark.parametrize(
    "change",
    [
        {"best_bid_price_text": "99"},
        {"event_time_ms": True},
        {"row_index": True},
        {"symbol": "../BTC"},
        {"raw_csv_line": RAW[:-2]},
        {"event_time_ms": 2**63},
    ],
)
def test_typed_row_cannot_replace_original_bytes(change):
    with pytest.raises(ValueError):
        archive_quote_v3(
            replace(_row(), **change),
            clock=ArchiveMarketClockV3("EVENT_E", 0, 0),
            source_manifest_sha256=SOURCE,
        )


def test_event_crossing_day_preserved_and_overflow_refused():
    raw = b"11,100.00,1.250,100.10,2.00,1704758399998,1704758400005\n"
    quote = archive_quote_v3(
        _row(raw), clock=ArchiveMarketClockV3("TRANSACTION_T", 2, 3), source_manifest_sha256=SOURCE
    )
    assert quote.modeled_available_at_ms == 1704758400010
    overflow = b"11,100.00,1.250,100.10,2.00,1704758399998,9223372036854775807\n"
    with pytest.raises(ValueError, match="overflow"):
        archive_quote_v3(
            _row(overflow), clock=ArchiveMarketClockV3("EVENT_E", 1, 0), source_manifest_sha256=SOURCE
        )


def test_source_hash_and_exact_types_required():
    with pytest.raises(ValueError):
        archive_quote_v3(_row(), clock=ArchiveMarketClockV3("EVENT_E", 0, 0), source_manifest_sha256="A" * 64)
    with pytest.raises(ValueError):
        archive_quote_v3(object(), clock=ArchiveMarketClockV3("EVENT_E", 0, 0), source_manifest_sha256=SOURCE)


def test_update_id_is_not_mistaken_for_a_signed_clock():
    raw = RAW.replace(b"10,", b"9223372036854775809,", 1)
    quote = archive_quote_v3(
        _row(raw), clock=ArchiveMarketClockV3("EVENT_E", 0, 0), source_manifest_sha256=SOURCE
    )
    assert quote.update_id == 9223372036854775809
