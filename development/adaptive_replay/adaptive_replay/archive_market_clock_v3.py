"""Exchange-archive clocks and exact BBOs, not observed historical receipts.

The availability clock is a frozen MODEL. Even when freshness uses T, a row
cannot become model-available before its exchange publication clock E. No
WS AcceptedBookFrame, source admission, or local receive clock is inferred.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Literal

from .bookticker_archive_stream_v3 import (
    DEFAULT_MAX_LINE_BYTES,
    BookTickerArchiveRowV3,
    _canonical,
    _parse_row,
    _sha,
)

MAX_CLOCK_MS = 2**63 - 1
MAX_MODELED_DELAY_MS = 60_000
CLOCK_SCHEMA = "kairos.research.archive-market-clock.v3"


@dataclass(frozen=True, slots=True)
class ArchiveMarketClockV3:
    """All timing assumptions are required, including an explicit zero delay."""

    event_basis: Literal["TRANSACTION_T", "EVENT_E"]
    feed_delay_ms: int
    processing_delay_ms: int
    _sha256: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.event_basis) is not str or self.event_basis not in {"TRANSACTION_T", "EVENT_E"}:
            raise ValueError("explicit exchange T/E event basis required")
        for value in (self.feed_delay_ms, self.processing_delay_ms):
            if type(value) is not int or not 0 <= value <= MAX_MODELED_DELAY_MS:
                raise ValueError("modeled delay exceeds explicit 0..60000 ms profile")
        object.__setattr__(
            self,
            "_sha256",
            hashlib.sha256(
                _canonical(
                    {
                        "schema": CLOCK_SCHEMA,
                        "domain": "EXCHANGE_ARCHIVE_MODEL_REFERENCE",
                        "event_basis": self.event_basis,
                        "feed_delay_ms": self.feed_delay_ms,
                        "processing_delay_ms": self.processing_delay_ms,
                        "availability_basis": "EVENT_E_PLUS_EXPLICIT_DELAYS",
                        "historical_received_at_ms": None,
                        "historical_persisted_at_ms": None,
                    }
                )
            ).hexdigest(),
        )

    @property
    def sha256(self) -> str:
        return self._sha256


@dataclass(frozen=True, slots=True)
class ArchiveBBOQuoteV3:
    """Immutable exact-decimal TOP_OF_BOOK_ONLY model reference.

    Construct through ``archive_quote_v3`` to validate original byte binding.
    This is intentionally not the native prospective V3 EntryQuote type.
    """

    symbol: str
    transaction_day: str
    row_index: int
    update_id: int
    bid_price: Decimal
    bid_qty: Decimal
    ask_price: Decimal
    ask_qty: Decimal
    transaction_time_ms: int
    exchange_event_time_ms: int
    event_at_ms: int
    modeled_available_at_ms: int
    source_manifest_sha256: str
    original_line_sha256: str
    clock_policy_sha256: str

    @property
    def historical_received_at_ms(self) -> None:
        return None

    @property
    def historical_persisted_at_ms(self) -> None:
        return None

    @property
    def stream_kind(self) -> str:
        return "TOP_OF_BOOK_ONLY"

    @property
    def clock_evidence(self) -> str:
        return "MODEL_NOT_OBSERVED_HISTORICAL_RECEIPT"


def archive_quote_v3(
    row: BookTickerArchiveRowV3,
    *,
    clock: ArchiveMarketClockV3,
    source_manifest_sha256: str,
) -> ArchiveBBOQuoteV3:
    """Reparse exact source bytes; manually forged typed rows are rejected."""
    if type(row) is not BookTickerArchiveRowV3 or type(clock) is not ArchiveMarketClockV3:
        raise ValueError("exact archive row and frozen clock required")
    _sha(source_manifest_sha256, "source manifest SHA256")
    if (
        type(row.row_index) is not int
        or row.row_index < 0
        or type(row.symbol) is not str
        or type(row.transaction_day) is not str
        or re.fullmatch(r"[A-Z0-9]{3,20}", row.symbol) is None
        or type(row.raw_csv_line) is not bytes
        or not row.raw_csv_line.endswith(b"\n")
        or len(row.raw_csv_line) > DEFAULT_MAX_LINE_BYTES
        or type(row.update_id) is not int
        or row.update_id < 0
        or any(
            type(value) is not int or not 0 <= value <= MAX_CLOCK_MS
            for value in (row.transaction_time_ms, row.event_time_ms)
        )
    ):
        raise ValueError("invalid exact archive row clocks/framing")
    original = _parse_row(row.raw_csv_line, row.symbol, row.transaction_day, row.row_index)
    if asdict(original) != asdict(row):
        raise ValueError("archive quote fields differ from original bytes")
    available = row.event_time_ms + clock.feed_delay_ms + clock.processing_delay_ms
    if available > MAX_CLOCK_MS:
        raise ValueError("modeled availability timestamp overflow")
    return ArchiveBBOQuoteV3(
        row.symbol,
        row.transaction_day,
        row.row_index,
        row.update_id,
        row.best_bid_price,
        row.best_bid_qty,
        row.best_ask_price,
        row.best_ask_qty,
        row.transaction_time_ms,
        row.event_time_ms,
        row.transaction_time_ms if clock.event_basis == "TRANSACTION_T" else row.event_time_ms,
        available,
        source_manifest_sha256,
        hashlib.sha256(row.raw_csv_line).hexdigest(),
        clock.sha256,
    )
