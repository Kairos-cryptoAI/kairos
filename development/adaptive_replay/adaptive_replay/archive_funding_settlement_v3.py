"""Exact original rate/REST settlement joins for modeled research accounting.

The REST mark is the price associated with a funding charge, not a candle,
entry quote, historical local receipt, or independently authenticated source.
Every read re-verifies the original monthly archive and its whole calendar.
Retrieval wall clocks stay separate from explicitly modeled historical delivery.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from .archive_financial_consumer_v3 import ArchiveFundingCalendarV3, ArchiveFundingReceiptV3
from .archive_funding_rate_v3 import (
    DEFAULT_LIMITS,
    FundingArchiveLimitsV3,
    FundingEntitlementV3,
    OriginalFundingRateV3,
    load_original_funding_archive_v3,
)
from .bookticker_archive_stream_v3 import _canonical, _sha

SCHEMA = "kairos.research.original-funding-settlement.v3"
MAX_RESPONSE_BYTES = 262_144
MAX_EVENTS = 256
MAX_CLOCK_MS = 9_999_999_999_999
DAY_MS = 86_400_000
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]{0,31})(?:\.[0-9]{1,64})?(?:[eE][+-]?[0-9]{1,2})?\Z")


def _ms(value):
    if type(value) is not int or not 0 <= value <= MAX_CLOCK_MS:
        raise ValueError("exact bounded UTC milliseconds required")


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError("duplicate original REST JSON key")
        result[key] = value
    return result


def _not_float(value):
    raise ValueError("REST numbers cannot be floats or nonfinite constants")


def _decimal(value, *, price=False):
    if type(value) is not str or _DECIMAL.fullmatch(value) is None:
        raise ValueError("bounded original Decimal string required")
    number = Decimal(value)
    if not number.is_finite() or (number <= 0 if price else number.copy_abs() > 1):
        raise ValueError("positive settlement price or bounded finite funding rate required")
    return number


@dataclass(frozen=True, slots=True)
class FundingRESTCaptureV3:
    request_wall_ms: int
    response_wall_ms: int
    captured_wall_ms: int
    original_capture_sha256: str
    response_body_sha256: str
    host: str = "fapi.binance.com"
    path: str = "/fapi/v1/fundingRate"
    evidence_kind: str = "RETROSPECTIVE_PUBLIC_FUNDING_SETTLEMENT_MARK_OBSERVATION"

    def __post_init__(self):
        for value in (self.request_wall_ms, self.response_wall_ms, self.captured_wall_ms):
            _ms(value)
        _sha(self.original_capture_sha256, "retained original acquisition receipt SHA256")
        _sha(self.response_body_sha256, "retained original REST body SHA256")
        if not (
            self.request_wall_ms <= self.response_wall_ms <= self.captured_wall_ms
            and self.host == "fapi.binance.com"
            and self.path == "/fapi/v1/fundingRate"
            and self.evidence_kind == "RETROSPECTIVE_PUBLIC_FUNDING_SETTLEMENT_MARK_OBSERVATION"
        ):
            raise ValueError("separate actual wall acquisition and exact public funding endpoint required")


@dataclass(frozen=True, slots=True)
class OriginalFundingSettlementV3:
    rate_record: OriginalFundingRateV3
    settlement_price: Decimal
    response_record_sha256: str
    settlement_price_source_sha256: str

    def __post_init__(self):
        row = self.rate_record
        if type(row) is not OriginalFundingRateV3 or type(row.raw_record) is not bytes:
            raise ValueError("complete original monthly funding record required")
        _sha(row.raw_record_sha256, "original monthly row SHA256")
        _sha(self.response_record_sha256, "original REST record SHA256")
        _sha(self.settlement_price_source_sha256, "original settlement source SHA256")
        fields = row.raw_record.rstrip(b"\r\n").split(b",")
        if (
            len(fields) != 3
            or hashlib.sha256(row.raw_record).hexdigest() != row.raw_record_sha256
            or int(fields[0]) != row.exchange_calc_time_ms
            or int(fields[1]) != row.interval_hours
            or type(row.rate) is not Decimal
            or _decimal(fields[2].decode("ascii")).as_tuple() != row.rate.as_tuple()
            or type(self.settlement_price) is not Decimal
            or not self.settlement_price.is_finite()
            or self.settlement_price <= 0
        ):
            raise ValueError("original monthly raw fields or positive settlement price differ")


@dataclass(frozen=True, slots=True)
class FundingSettlementWindowV3:
    symbol: str
    start_ms: int
    end_ms: int
    archive_sha256: str
    checksum_sha256: str
    csv_sha256: str
    calendar_sha256: str
    maximum_calc_time_offset_ms: int
    capture: FundingRESTCaptureV3
    records: tuple[OriginalFundingSettlementV3, ...]
    evidence_sha256: str
    historical_received_at_ms: None = None
    funding_for_entry_decisions: bool = False
    source_admitted: bool = False

    def _evidence(self):
        return {
            "schema": SCHEMA,
            "symbol": self.symbol,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "archive_sha256": self.archive_sha256,
            "checksum_sha256": self.checksum_sha256,
            "csv_sha256": self.csv_sha256,
            "calendar_sha256": self.calendar_sha256,
            "maximum_calc_time_offset_ms": self.maximum_calc_time_offset_ms,
            "capture": asdict(self.capture),
            "records": [
                {
                    "due_at_ms": row.rate_record.due_at_ms,
                    "exchange_calc_time_ms": row.rate_record.exchange_calc_time_ms,
                    "original_rate": str(row.rate_record.rate),
                    "original_record_sha256": row.rate_record.raw_record_sha256,
                    "settlement_price": str(row.settlement_price),
                    "response_record_sha256": row.response_record_sha256,
                    "settlement_price_source_sha256": row.settlement_price_source_sha256,
                }
                for row in self.records
            ],
            "historical_received_at_ms": None,
            "funding_for_entry_decisions": False,
            "source_admitted": False,
        }

    def calendar(self, *, feed_delay_ms: int, processing_delay_ms: int) -> ArchiveFundingCalendarV3:
        """KNOWN accounting only; no rate/mark permission for entry features."""
        if (
            type(self.capture) is not FundingRESTCaptureV3
            or type(self.records) is not tuple
            or not 1 <= len(self.records) <= MAX_EVENTS
            or self.historical_received_at_ms is not None
            or self.funding_for_entry_decisions is not False
            or self.source_admitted is not False
        ):
            raise ValueError("retained exact settlement evidence required")
        FundingRESTCaptureV3(**asdict(self.capture))
        if self.evidence_sha256 != _hash(self._evidence()):
            raise ValueError("settlement evidence changed after exact original join")
        receipts = []
        for item in self.records:
            row = item.rate_record
            if (
                type(item) is not OriginalFundingSettlementV3
                or type(row) is not OriginalFundingRateV3
                or hashlib.sha256(row.raw_record).hexdigest() != row.raw_record_sha256
            ):
                raise ValueError("unchanged complete original funding record required")
            OriginalFundingSettlementV3(
                **{
                    name: getattr(item, name)
                    for name in (
                        "rate_record",
                        "settlement_price",
                        "response_record_sha256",
                        "settlement_price_source_sha256",
                    )
                }
            )
            _ms(
                available := row.modeled_available_at(
                    feed_delay_ms=feed_delay_ms, processing_delay_ms=processing_delay_ms
                )
            )
            receipts.append(
                ArchiveFundingReceiptV3(
                    row.due_at_ms,
                    row.exchange_calc_time_ms,
                    available,
                    "NO_PAYMENT" if row.rate == 0 else "KNOWN",
                    row.rate,
                    item.settlement_price,
                    item.settlement_price_source_sha256,
                    row.raw_record_sha256,
                )
            )
        return ArchiveFundingCalendarV3(
            "EXHAUSTIVE_RETAINED_ROSTER",
            _hash(
                {
                    "evidence": self.evidence_sha256,
                    "feed_delay_ms": feed_delay_ms,
                    "processing_delay_ms": processing_delay_ms,
                    "authority": "MODELED_ACCOUNTING_ONLY",
                }
            ),
            self.maximum_calc_time_offset_ms,
            tuple(item.rate_record.due_at_ms for item in self.records),
            tuple(sorted(receipts, key=lambda item: (item.modeled_available_at_ms, item.due_at_ms))),
        )


def load_funding_settlement_window_v3(
    archive_path: Path,
    *,
    symbol: str,
    month: str,
    expected_archive_sha256: str,
    expected_checksum_sha256: str,
    entitlements: tuple[FundingEntitlementV3, ...],
    maximum_calc_time_offset_ms: int,
    start_ms: int,
    end_ms: int,
    response_body: bytes,
    capture: FundingRESTCaptureV3,
    limits: FundingArchiveLimitsV3 = DEFAULT_LIMITS,
) -> FundingSettlementWindowV3:
    """Reconcile one exact five-day window plus tail; no pagination or substitution."""
    _ms(start_ms)
    _ms(end_ms)
    if start_ms % DAY_MS or end_ms - start_ms != 6 * DAY_MS:
        raise ValueError("exact predeclared six UTC days including exit tail required")
    if type(capture) is not FundingRESTCaptureV3:
        raise ValueError("typed separate wall acquisition receipt required")
    FundingRESTCaptureV3(**asdict(capture))
    if capture.request_wall_ms < end_ms:
        raise ValueError("retrospective retrieval wall clock cannot impersonate historical delivery")
    if type(response_body) is not bytes or not 1 <= len(response_body) <= MAX_RESPONSE_BYTES:
        raise ValueError("bounded complete immutable original REST body required")
    if hashlib.sha256(response_body).hexdigest() != capture.response_body_sha256:
        raise ValueError("independently retained REST response byte hash mismatch")
    archive = load_original_funding_archive_v3(
        archive_path,
        symbol=symbol,
        month=month,
        expected_archive_sha256=expected_archive_sha256,
        expected_checksum_sha256=expected_checksum_sha256,
        entitlements=entitlements,
        maximum_calc_time_offset_ms=maximum_calc_time_offset_ms,
        limits=limits,
    )
    original = archive.window(start_ms, end_ms)
    if not 1 <= len(original) <= MAX_EVENTS or any(
        not start_ms <= row.exchange_calc_time_ms < end_ms for row in original
    ):
        raise ValueError("whole original calendar must supply the complete fixed response window")
    try:
        response = json.loads(
            response_body.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_float=_not_float,
            parse_constant=_not_float,
        )
    except (UnicodeError, RecursionError) as error:
        raise ValueError("bounded strict original REST JSON required") from error
    if type(response) is not list or len(response) != len(original):
        raise ValueError("complete original funding roster must match REST response exactly")
    settlements = []
    previous_time = -1
    for row, event in zip(original, response, strict=True):
        if (
            type(event) is not dict
            or set(event)
            not in (
                {"symbol", "fundingRate", "fundingTime", "markPrice"},
                {"symbol", "fundingRate", "fundingTime", "markPrice", "rateType"},
            )
            or event.get("rateType", "Regular") != "Regular"
        ):
            raise ValueError("exact regular funding REST schema required")
        _ms(event["fundingTime"])
        rate = _decimal(event["fundingRate"])
        price = _decimal(event["markPrice"], price=True)
        if (
            event["symbol"] != symbol
            or event["fundingTime"] <= previous_time
            or event["fundingTime"] != row.exchange_calc_time_ms
            or rate != row.rate
        ):
            raise ValueError("exact symbol/rate/calcTime join failed; never round due or price")
        response_hash = _hash(event)
        source_hash = _hash(
            {
                "schema": SCHEMA,
                "response_body": capture.response_body_sha256,
                "response_record": response_hash,
                "capture": asdict(capture),
            }
        )
        settlements.append(OriginalFundingSettlementV3(row, price, response_hash, source_hash))
        previous_time = event["fundingTime"]
    result = FundingSettlementWindowV3(
        symbol,
        start_ms,
        end_ms,
        archive.archive_sha256,
        archive.checksum_sha256,
        archive.csv_sha256,
        archive.calendar_sha256,
        maximum_calc_time_offset_ms,
        capture,
        tuple(settlements),
        "",
    )
    return FundingSettlementWindowV3(
        **{
            **asdict(result),
            "capture": capture,
            "records": tuple(settlements),
            "evidence_sha256": _hash(result._evidence()),
        }
    )
