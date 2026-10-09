"""Prospective, caller-attested binding of REST candle receipts to native bars.

This pure/offline fold parses only already-retained response bytes. It mirrors
the pinned quant collector's two-identical-REST-observation and contiguous-bar
promotion rules, but its clocks and receipts do not authenticate Binance or
prove exchange finality. It never fetches data or backdates modern captures.

Native equality is the projection of every ``ClosedKline`` field; REST
trade-count and ignored slot 12 remain retained but do not affect confirmation.
The binding parser is intentionally stricter than native parsing: it requires
exactly 12 fields, validates those metadata slots, rejects a malformed page,
and caps each raw response at 2 MiB and rows at the requested limit.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass

from kairos_strategy.candles import Candle
from kairos_strategy.provenance import candle_payload

from .candle_originals_v3 import CandleOriginalsV3, RetainedCandleV3
from .historical_context import digest
from .inputs import UNIVERSE
from .rest_candle_receipts_v3 import (
    MAX_ATTEMPTS,
    MAX_BODY_BYTES,
    SCHEMA,
    CandleRequestV3,
    ReceiptCheckpoint,
    RestCandleAttemptV3,
    _validate_attempt_id,
)
from .scenarios import ScenarioEvidence

MINUTE_MS = 60_000
DEFAULT_NATIVE_FINALITY_DELAY_MS = 5_000
MAX_PENDING_BARS = 1_000
MAX_CANDIDATE_BARS = 10_000
BOOTSTRAP_POLICY = "ANCHORED_PRIOR_BAR"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ClosedBarEvidenceError(ValueError):
    """A raw REST receipt pair or native promotion fold is inconsistent."""


@dataclass(frozen=True, slots=True)
class NormalizedKlineRowV3:
    """All twelve Binance REST array slots in deterministic native-like form."""

    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    base_volume: float
    close_time_ms: int
    quote_volume: float
    trade_count: int
    taker_buy_base_volume: float
    taker_buy_quote_volume: float
    ignored_field: str

    @property
    def sha256(self) -> str:
        return digest(asdict(self))

    def native_projection(self, symbol: str) -> tuple[object, ...]:
        """Exact fields of the pinned native ``ClosedKline`` equality tuple."""
        return (
            symbol,
            "1m",
            self.open_time_ms,
            self.close_time_ms,
            self.open,
            self.high,
            self.low,
            self.close,
            self.base_volume,
            self.quote_volume,
            self.taker_buy_base_volume,
            self.taker_buy_quote_volume,
        )

    def candle(self, symbol: str) -> Candle:
        return Candle(
            symbol=symbol,
            timeframe="1m",
            open_time_ms=self.open_time_ms,
            close_time_ms=self.close_time_ms,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.base_volume,
            quote_volume=self.quote_volume,
            taker_buy_volume=self.taker_buy_base_volume,
        )


@dataclass(frozen=True, slots=True)
class RestCandleBarPairV3:
    """A validated two-observation binding; not standalone native-count authority."""

    symbol: str
    row: NormalizedKlineRowV3
    first_row: NormalizedKlineRowV3
    candle: Candle
    first_attempt: RestCandleAttemptV3
    first_raw_response: bytes
    second_attempt: RestCandleAttemptV3
    second_raw_response: bytes
    first_raw_sha256: str
    second_raw_sha256: str
    finality_delay_ms: int

    def __post_init__(self) -> None:
        if type(self.symbol) is not str or self.symbol not in UNIVERSE:
            raise ClosedBarEvidenceError("pair symbol must be in the fixed universe")
        if (
            type(self.row) is not NormalizedKlineRowV3
            or type(self.first_row) is not NormalizedKlineRowV3
            or type(self.candle) is not Candle
        ):
            raise ClosedBarEvidenceError("pair requires exact normalized row and Candle types")
        if self.candle != self.row.candle(self.symbol):
            raise ClosedBarEvidenceError("forged pair candle does not match normalized row")
        if (
            type(self.first_attempt) is not RestCandleAttemptV3
            or type(self.second_attempt) is not RestCandleAttemptV3
        ):
            raise ClosedBarEvidenceError("pair must retain two exact receipt attempts")
        if self.first_attempt.attempt_number >= self.second_attempt.attempt_number:
            raise ClosedBarEvidenceError("pair attempt order is not increasing")
        if (
            self.first_attempt.request != self.second_attempt.request
            or self.first_attempt.request.symbol != self.symbol
        ):
            raise ClosedBarEvidenceError("pair requests do not match the exact source symbol")
        if type(self.finality_delay_ms) is not int or self.finality_delay_ms < 0:
            raise ClosedBarEvidenceError("pair finality delay must be an exact nonnegative integer")
        first_row, first_candle = _attempt_row(
            self.first_attempt, self.first_raw_response, self.row.open_time_ms
        )
        second_row, second_candle = _attempt_row(
            self.second_attempt, self.second_raw_response, self.row.open_time_ms
        )
        if first_row != self.first_row or second_row != self.row or first_candle != self.candle:
            raise ClosedBarEvidenceError("pair raw responses do not bind the exact declared normalized row")
        if first_row.native_projection(self.symbol) != second_row.native_projection(self.symbol):
            raise ClosedBarEvidenceError("pair raw responses disagree on native ClosedKline fields")
        if (
            self.first_raw_sha256 != self.first_attempt.raw_response_sha256
            or self.second_raw_sha256 != self.second_attempt.raw_response_sha256
        ):
            raise ClosedBarEvidenceError("pair raw body hashes differ from their canonical receipts")
        if self.second_attempt.requested_at_ms < self.first_attempt.persisted_at_ms:
            raise ClosedBarEvidenceError("second request precedes first response-body fsync")
        if self.second_attempt.persisted_at_ms < self.row.close_time_ms + 1:
            raise ClosedBarEvidenceError("second raw body fsync predates candle close")

    @property
    def sha256(self) -> str:
        return digest(
            {
                "symbol": self.symbol,
                "row": asdict(self.row),
                "first_row": asdict(self.first_row),
                "candle": asdict(self.candle),
                "first_receipt_sha256": self.first_attempt.receipt_sha256,
                "second_receipt_sha256": self.second_attempt.receipt_sha256,
                "first_raw_sha256": self.first_raw_sha256,
                "second_raw_sha256": self.second_raw_sha256,
                "first_body_sha256": hashlib.sha256(self.first_raw_response).hexdigest(),
                "second_body_sha256": hashlib.sha256(self.second_raw_response).hexdigest(),
                "finality_delay_ms": self.finality_delay_ms,
            }
        )

    @classmethod
    def from_attempts(
        cls,
        first_attempt: RestCandleAttemptV3,
        first_raw_response: bytes,
        second_attempt: RestCandleAttemptV3,
        second_raw_response: bytes,
        *,
        open_time_ms: int,
        finality_delay_ms: int = DEFAULT_NATIVE_FINALITY_DELAY_MS,
    ) -> RestCandleBarPairV3:
        """Bind exact bytes and receipts; does not establish intervening page history."""

        _clock(open_time_ms, "open_time_ms")
        if open_time_ms % MINUTE_MS:
            raise ClosedBarEvidenceError("target open time must be minute aligned")
        if type(finality_delay_ms) is not int or finality_delay_ms < 0:
            raise ClosedBarEvidenceError("exact nonnegative native finality delay required")
        first_row, first_candle = _attempt_row(first_attempt, first_raw_response, open_time_ms)
        second_row, second_candle = _attempt_row(second_attempt, second_raw_response, open_time_ms)
        if first_attempt.attempt_id == second_attempt.attempt_id:
            raise ClosedBarEvidenceError("two different REST attempt identities are required")
        if first_attempt.attempt_number >= second_attempt.attempt_number:
            raise ClosedBarEvidenceError("REST confirmation attempts must retain increasing ledger order")
        if first_attempt.request != second_attempt.request:
            raise ClosedBarEvidenceError("two REST observations must use the exact same request descriptor")
        if first_attempt.request.symbol not in UNIVERSE:
            raise ClosedBarEvidenceError("REST request symbol is outside the fixed source universe")
        if first_row.native_projection(first_attempt.request.symbol) != second_row.native_projection(
            second_attempt.request.symbol
        ):
            raise ClosedBarEvidenceError("the two REST observations disagree on native ClosedKline fields")
        if second_attempt.requested_at_ms < first_attempt.persisted_at_ms:
            raise ClosedBarEvidenceError(
                "second REST request must follow durable first-response body capture"
            )
        symbol = first_attempt.request.symbol
        return cls(
            symbol=symbol,
            row=second_row,
            first_row=first_row,
            candle=second_candle,
            first_attempt=first_attempt,
            first_raw_response=first_raw_response,
            second_attempt=second_attempt,
            second_raw_response=second_raw_response,
            first_raw_sha256=first_attempt.raw_response_sha256,
            second_raw_sha256=second_attempt.raw_response_sha256,
            finality_delay_ms=finality_delay_ms,
        )


def _clock(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ClosedBarEvidenceError(f"{name} must be an exact nonnegative millisecond clock")
    return value


def _sha(value: object, name: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ClosedBarEvidenceError(f"{name} must be a lowercase SHA-256 digest")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", errors="strict")


def _reject_constant(value: str) -> None:
    raise ClosedBarEvidenceError(f"response contains unsupported JSON constant {value}")


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ClosedBarEvidenceError("response contains duplicate JSON object keys")
        result[key] = value
    return result


def _integer(value: object) -> int | None:
    """Mirror the pinned native collector's REST integer conversion."""
    if isinstance(value, bool) or (
        isinstance(value, float) and (not math.isfinite(value) or not value.is_integer())
    ):
        return None
    try:
        return int(value) if value is not None else None
    except (OverflowError, TypeError, ValueError):
        return None


def _finite_float(value: object) -> float | None:
    """Mirror the pinned native collector's REST numeric conversion."""
    try:
        result = float(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result is not None and math.isfinite(result) else None


def _normalize_row(value: object, expected_open_ms: int) -> NormalizedKlineRowV3:
    if type(value) is not list or len(value) != 12:
        raise ClosedBarEvidenceError("target REST kline must have exactly twelve fields")
    open_ms = _integer(value[0])
    close_ms = _integer(value[6])
    trade_count = _integer(value[8])
    if open_ms != expected_open_ms or close_ms is None or trade_count is None or trade_count < 0:
        raise ClosedBarEvidenceError("target REST kline timestamps or trade count are invalid")
    numeric = tuple(_finite_float(value[index]) for index in (1, 2, 3, 4, 5, 7, 9, 10))
    if any(item is None for item in numeric):
        raise ClosedBarEvidenceError("target REST kline has a non-finite normalized numeric field")
    if type(value[11]) is not str:
        raise ClosedBarEvidenceError("target REST kline ignored twelfth field must remain a string")
    open_price, high, low, close, base, quote, taker_base, taker_quote = numeric
    row = NormalizedKlineRowV3(
        open_time_ms=open_ms,
        open=open_price,
        high=high,
        low=low,
        close=close,
        base_volume=base,
        close_time_ms=close_ms,
        quote_volume=quote,
        trade_count=trade_count,
        taker_buy_base_volume=taker_base,
        taker_buy_quote_volume=taker_quote,
        ignored_field=value[11],
    )
    _validate_native_row(row)
    return row


def _validate_native_row(row: NormalizedKlineRowV3) -> None:
    prices = (row.open, row.high, row.low, row.close)
    volumes = (row.base_volume, row.quote_volume, row.taker_buy_base_volume, row.taker_buy_quote_volume)
    if (
        row.open_time_ms < 0
        or row.close_time_ms != row.open_time_ms + MINUTE_MS - 1
        or row.close_time_ms % MINUTE_MS != MINUTE_MS - 1
        or not all(math.isfinite(value) for value in (*prices, *volumes))
        or min(prices) <= 0
        or row.high < max(row.open, row.close)
        or row.low > min(row.open, row.close)
        or min(volumes) < 0
        or row.taker_buy_base_volume > row.base_volume
        or row.taker_buy_quote_volume > row.quote_volume
    ):
        raise ClosedBarEvidenceError("target REST kline violates pinned native closed-bar validation")


def _target_row(raw_response: bytes, open_time_ms: int) -> NormalizedKlineRowV3:
    if type(raw_response) is not bytes or not 0 < len(raw_response) <= 2 * 1024 * 1024:
        raise ClosedBarEvidenceError("exact bounded raw response bytes required")
    try:
        body = json.loads(
            raw_response.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ClosedBarEvidenceError("retained response is not strict UTF-8 JSON") from exc
    if type(body) is not list:
        raise ClosedBarEvidenceError("retained REST response must be a JSON array")
    matches: list[object] = []
    for item in body:
        if type(item) is list and item:
            row_open = _integer(item[0])
            if row_open == open_time_ms:
                matches.append(item)
    if len(matches) != 1:
        raise ClosedBarEvidenceError("response must contain exactly one row for the requested candle")
    return _normalize_row(matches[0], open_time_ms)


def _parse_page(raw_response: bytes | None, symbol: str) -> tuple[NormalizedKlineRowV3, ...]:
    if type(raw_response) is not bytes or not 0 < len(raw_response) <= MAX_BODY_BYTES:
        raise ClosedBarEvidenceError("exact bounded REST page body required")
    try:
        body = json.loads(
            raw_response.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ClosedBarEvidenceError("REST page is not strict UTF-8 JSON") from exc
    if type(body) is not list or len(body) > 1_500:
        raise ClosedBarEvidenceError("REST page must be a bounded JSON kline array")
    rows: list[NormalizedKlineRowV3] = []
    seen_open: set[int] = set()
    for item in body:
        if type(item) is not list or not item:
            raise ClosedBarEvidenceError("REST page contains a malformed row")
        open_ms = _integer(item[0])
        if open_ms is None or open_ms in seen_open:
            raise ClosedBarEvidenceError("REST page has invalid or duplicate candle identity")
        row = _normalize_row(item, open_ms)
        row.candle(symbol)
        seen_open.add(open_ms)
        rows.append(row)
    return tuple(sorted(rows, key=lambda row: row.close_time_ms))


def _attempt_row(
    attempt: RestCandleAttemptV3,
    raw_response: bytes,
    open_time_ms: int,
) -> tuple[NormalizedKlineRowV3, Candle]:
    _validate_receipt_attempt(attempt, raw_response)
    if attempt.state != "HTTP_RESPONSE" or attempt.http_status != 200:
        raise ClosedBarEvidenceError("two successful HTTP 200 receipt bodies are required for a bar pair")
    row = _target_row(raw_response, open_time_ms)
    candle = row.candle(attempt.request.symbol)
    _validate_native_row(row)
    return row, candle


def _validate_receipt_attempt(attempt: RestCandleAttemptV3, raw_response: bytes | None) -> None:
    """Recompute every receipt field and body binding, not just its digest shape."""
    if type(attempt) is not RestCandleAttemptV3 or type(attempt.request) is not CandleRequestV3:
        raise ClosedBarEvidenceError("exact retained REST attempt and fixed request descriptor required")
    if type(attempt.attempt_number) is not int or not 1 <= attempt.attempt_number <= MAX_ATTEMPTS:
        raise ClosedBarEvidenceError("attempt number is outside the retained receipt bound")
    try:
        attempt_id = _validate_attempt_id(attempt.attempt_id)
        CandleRequestV3(attempt.request.symbol, attempt.request.limit)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ClosedBarEvidenceError("retained REST attempt identity or request is invalid") from exc
    _clock(attempt.requested_at_ms, "requested_at_ms")
    _clock(attempt.persisted_at_ms, "persisted_at_ms")
    if attempt.persisted_at_ms < attempt.requested_at_ms:
        raise ClosedBarEvidenceError("raw body fsync clock precedes the request clock")
    _sha(attempt.receipt_sha256, "receipt hash")
    previous = attempt.previous_receipt_sha256
    if previous is not None:
        _sha(previous, "previous receipt hash")
    if attempt.state == "HTTP_RESPONSE":
        if (
            type(attempt.response_received_at_ms) is not int
            or type(attempt.http_status) is not int
            or not 100 <= attempt.http_status <= 599
            or attempt.failure_kind is not None
            or type(attempt.raw_response_file) is not str
            or attempt.raw_response_file != f"{attempt.attempt_number:08d}.response.raw"
            or type(attempt.raw_response_bytes) is not int
            or not 0 <= attempt.raw_response_bytes <= MAX_BODY_BYTES
            or type(attempt.raw_response_sha256) is not str
        ):
            raise ClosedBarEvidenceError("HTTP response receipt fields are invalid")
        _clock(attempt.response_received_at_ms, "response_received_at_ms")
        _sha(attempt.raw_response_sha256, "raw response hash")
        if not attempt.requested_at_ms <= attempt.response_received_at_ms <= attempt.persisted_at_ms:
            raise ClosedBarEvidenceError("request/receive/body-fsync clocks are not causal")
        if type(raw_response) is not bytes or len(raw_response) != attempt.raw_response_bytes:
            raise ClosedBarEvidenceError("exact bounded response body is required")
        if hashlib.sha256(raw_response).hexdigest() != attempt.raw_response_sha256:
            raise ClosedBarEvidenceError("supplied body differs from retained raw response hash")
    elif attempt.state == "NO_RESPONSE":
        if (
            attempt.response_received_at_ms is not None
            or attempt.http_status is not None
            or type(attempt.failure_kind) is not str
            or attempt.failure_kind
            not in {"CANCELLED", "CONNECTION_ERROR", "INTERRUPTED", "TIMEOUT", "UNKNOWN"}
            or attempt.raw_response_file is not None
            or type(attempt.raw_response_bytes) is not int
            or attempt.raw_response_bytes != 0
            or attempt.raw_response_sha256 is not None
            or raw_response is not None
        ):
            raise ClosedBarEvidenceError("no-response attempt must keep its explicit empty response fields")
    else:
        raise ClosedBarEvidenceError("unknown retained attempt state")

    record = {
        "schema": SCHEMA,
        "attempt_number": attempt.attempt_number,
        "attempt_id": attempt_id,
        "previous_receipt_sha256": previous,
        "request": attempt.request.descriptor(),
        "state": attempt.state,
        "requested_at_ms": attempt.requested_at_ms,
        "response_received_at_ms": attempt.response_received_at_ms,
        "persisted_at_ms": attempt.persisted_at_ms,
        "http_status": attempt.http_status,
        "failure_kind": attempt.failure_kind,
        "raw_response_file": attempt.raw_response_file,
        "raw_response_bytes": attempt.raw_response_bytes,
        "raw_response_sha256": attempt.raw_response_sha256,
    }
    if hashlib.sha256(_canonical(record)).hexdigest() != attempt.receipt_sha256:
        raise ClosedBarEvidenceError("canonical receipt hash does not bind its exact fields")


@dataclass(frozen=True, slots=True)
class ClosedBarEvidenceV3:
    """One candle only after the caller-attested native contiguous promotion."""

    pair: RestCandleBarPairV3
    promotion_sequence: int
    promotion_at_ms: int

    def __post_init__(self) -> None:
        if type(self.pair) is not RestCandleBarPairV3:
            raise ClosedBarEvidenceError("exact two-response candle pair required")
        if type(self.promotion_sequence) is not int or self.promotion_sequence < 1:
            raise ClosedBarEvidenceError("positive promotion sequence required")
        _clock(self.promotion_at_ms, "promotion_at_ms")
        if self.promotion_at_ms < self.pair.second_attempt.persisted_at_ms:
            raise ClosedBarEvidenceError("promotion cannot predate the second raw response body fsync")

    @property
    def candle(self) -> Candle:
        return self.pair.candle

    @property
    def available_at_ms(self) -> int:
        """Caller-attested native processing/promotion clock, never event time."""
        return self.promotion_at_ms

    @property
    def sha256(self) -> str:
        return digest(
            {
                "pair_sha256": self.pair.sha256,
                "promotion_sequence": self.promotion_sequence,
                "promotion_at_ms": self.promotion_at_ms,
                "classification": "CALLER_ATTESTED_NATIVE_CONTIGUOUS_PROMOTION_NOT_SOURCE_AUTHENTICATION",
            }
        )

    def to_retained_candle_v3(self, *, ttl_ms: int) -> RetainedCandleV3:
        if type(ttl_ms) is not int or ttl_ms <= 0:
            raise ClosedBarEvidenceError("explicit positive evidence TTL required by ScenarioEvidence")
        source_id = f"rest-candle-v3:{self.pair.sha256}"
        evidence = ScenarioEvidence(
            source_id=source_id,
            kind="MARKET",
            symbol=self.candle.symbol,
            payload_sha256=digest(candle_payload(self.candle)),
            event_ms=self.candle.close_time_ms,
            received_ms=self.pair.second_attempt.response_received_at_ms,
            captured_ms=self.pair.second_attempt.persisted_at_ms,
            ttl_ms=ttl_ms,
        )
        return RetainedCandleV3(
            candle=self.candle,
            evidence=evidence,
            available_at_ms=self.promotion_at_ms,
            evidence_kind="CALLER_ATTESTED_POINT_IN_TIME",
        )


@dataclass(frozen=True, slots=True)
class ClosedBarFoldResultV3:
    state: str
    promoted: tuple[ClosedBarEvidenceV3, ...]
    pending_close_times_ms: tuple[int, ...]
    blocked_reason: str | None
    attempt_number: int
    page_open_times_ms: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ReceiptObservationV3:
    """One ledger denominator row and its actual response-processing clock."""

    attempt: RestCandleAttemptV3
    raw_response: bytes | None
    native_processed_at_ms: int | None


@dataclass(frozen=True, slots=True)
class _CandidateObservation:
    row: NormalizedKlineRowV3
    count: int
    attempt: RestCandleAttemptV3
    raw_response: bytes


class ClosedBarEvidenceFoldV3:
    """Fold one complete, independently checkpointed attempt ledger.

    Bootstrap is explicitly anchored to a caller-attested bounded
    ``restored_through`` close watermark, matching native restore filtering.
    The watermark is not a verified prior original or full warmup history.
    """

    def __init__(
        self,
        symbol: str,
        *,
        bootstrap_policy: str,
        restored_through_close_time_ms: int,
        max_pending: int = MAX_PENDING_BARS,
        finality_delay_ms: int = DEFAULT_NATIVE_FINALITY_DELAY_MS,
    ) -> None:
        if type(symbol) is not str or symbol not in UNIVERSE:
            raise ClosedBarEvidenceError("fold symbol must be in the fixed five-symbol universe")
        if bootstrap_policy != BOOTSTRAP_POLICY:
            raise ClosedBarEvidenceError("explicit ANCHORED_PRIOR_BAR bootstrap policy is required")
        _clock(restored_through_close_time_ms, "restored_through_close_time_ms")
        if restored_through_close_time_ms % MINUTE_MS != MINUTE_MS - 1:
            raise ClosedBarEvidenceError("restored-through watermark must be a native minute close timestamp")
        if type(max_pending) is not int or not 1 <= max_pending <= MAX_PENDING_BARS:
            raise ClosedBarEvidenceError("bounded positive pending-bar capacity required")
        if type(finality_delay_ms) is not int or finality_delay_ms < 0:
            raise ClosedBarEvidenceError("exact nonnegative native finality delay required")
        self.symbol = symbol
        self.bootstrap_policy = bootstrap_policy
        self.source_scope = "BOUNDED_POINT_IN_TIME_SAMPLE_NOT_FULL_WARMUP"
        self.restored_through_close_time_ms = restored_through_close_time_ms
        self._last_close_ms = restored_through_close_time_ms
        self._max_pending = max_pending
        self._finality_delay_ms = finality_delay_ms
        self._pending: dict[int, RestCandleBarPairV3] = {}
        self._promoted: dict[int, ClosedBarEvidenceV3] = {}
        self._candidates: dict[int, _CandidateObservation] = {}
        self._attempt_count = 0
        self._receipt_head: str | None = None
        self._last_native_processed_ms: int | None = None
        self._blocked_reason: str | None = None
        self._next_promotion_sequence = 1

    @property
    def pending_close_times_ms(self) -> tuple[int, ...]:
        return tuple(sorted(self._pending))

    @property
    def promoted(self) -> tuple[ClosedBarEvidenceV3, ...]:
        return tuple(self._promoted[key] for key in sorted(self._promoted))

    @property
    def blocked_reason(self) -> str | None:
        return self._blocked_reason

    def ingest_receipt_sequence(
        self,
        observations: tuple[ReceiptObservationV3, ...],
        *,
        checkpoint: ReceiptCheckpoint,
    ) -> tuple[ClosedBarFoldResultV3, ...]:
        """Audit and fold the complete ledger exactly once, including failures.

        Receipt IDs may recur across candle rows from the same page; they are
        sequence identities, not per-bar deduplication keys. Any omitted row
        breaks attempt numbering or the predecessor-hash chain.
        """
        if self._attempt_count or self._blocked_reason is not None:
            raise ClosedBarEvidenceError("receipt sequence is one-shot and fold is already initialized")
        if type(checkpoint) is not ReceiptCheckpoint or type(observations) is not tuple:
            raise ClosedBarEvidenceError(
                "exact independent receipt checkpoint and immutable sequence required"
            )
        if (
            not observations
            or len(observations) > MAX_ATTEMPTS
            or len(observations) != checkpoint.attempt_count
        ):
            raise ClosedBarEvidenceError("complete bounded attempt sequence must match checkpoint count")
        previous_hash: str | None = None
        previous_persisted_at_ms: int | None = None
        seen_ids: set[str] = set()
        last_processed: int | None = None
        for index, observation in enumerate(observations, start=1):
            if type(observation) is not ReceiptObservationV3:
                raise ClosedBarEvidenceError("exact receipt observation rows required")
            attempt = observation.attempt
            _validate_receipt_attempt(attempt, observation.raw_response)
            if attempt.attempt_number != index or attempt.previous_receipt_sha256 != previous_hash:
                raise ClosedBarEvidenceError("omitted, reordered, or unchained receipt attempt")
            if previous_persisted_at_ms is not None and attempt.requested_at_ms < previous_persisted_at_ms:
                raise ClosedBarEvidenceError("next request clock predates prior raw-body/marker fsync")
            if attempt.attempt_id in seen_ids:
                raise ClosedBarEvidenceError("duplicate attempt identity in complete receipt sequence")
            seen_ids.add(attempt.attempt_id)
            previous_hash = attempt.receipt_sha256
            previous_persisted_at_ms = attempt.persisted_at_ms
            if observation.native_processed_at_ms is None:
                if attempt.state != "NO_RESPONSE":
                    raise ClosedBarEvidenceError("HTTP response requires its actual native processing clock")
            else:
                _clock(observation.native_processed_at_ms, "native_processed_at_ms")
                if attempt.state != "HTTP_RESPONSE":
                    raise ClosedBarEvidenceError(
                        "no-response attempt cannot claim a response processing clock"
                    )
                if observation.native_processed_at_ms < attempt.persisted_at_ms:
                    raise ClosedBarEvidenceError("native processing clock predates response-body fsync")
                if last_processed is not None and observation.native_processed_at_ms < last_processed:
                    raise ClosedBarEvidenceError(
                        "native processing clocks regress across the receipt sequence"
                    )
                last_processed = observation.native_processed_at_ms
        if previous_hash != checkpoint.head_sha256:
            raise ClosedBarEvidenceError(
                "complete receipt sequence does not end at independent checkpoint head"
            )

        results: list[ClosedBarFoldResultV3] = []
        for observation in observations:
            attempt = observation.attempt
            if self._blocked_reason is not None:
                results.append(self._result("BLOCKED", (), attempt.attempt_number, ()))
                continue
            if attempt.state == "NO_RESPONSE":
                results.append(self._result("NO_RESPONSE", (), attempt.attempt_number, ()))
                continue
            at_ms = observation.native_processed_at_ms
            assert at_ms is not None
            self._last_native_processed_ms = at_ms
            if attempt.request.symbol != self.symbol:
                results.append(self._result("OTHER_SYMBOL", (), attempt.attempt_number, ()))
                continue
            if attempt.http_status != 200:
                results.append(self._result("HTTP_FAILURE", (), attempt.attempt_number, ()))
                continue
            try:
                rows = _parse_page(observation.raw_response, self.symbol)
            except ClosedBarEvidenceError:
                results.append(self._result("MALFORMED", (), attempt.attempt_number, ()))
                continue
            if len(rows) > attempt.request.limit:
                results.append(self._result("MALFORMED", (), attempt.attempt_number, ()))
                continue
            promoted: list[ClosedBarEvidenceV3] = []
            for row in rows:
                # The latest REST page can overlap a bounded restore window.
                # Native _append_authoritative_kline ignores every close at or
                # before its restored-through watermark; retain coverage only.
                if row.close_time_ms <= self.restored_through_close_time_ms:
                    continue
                if at_ms < row.close_time_ms + self._finality_delay_ms:
                    continue
                known = self._promoted.get(row.close_time_ms)
                if known is not None:
                    if known.pair.row.native_projection(self.symbol) != row.native_projection(self.symbol):
                        self._blocked_reason = "conflicting_closed_bar"
                        break
                    # Native _observe_rest_closed_kline sends already-known
                    # closes straight to _append_authoritative_kline, where
                    # the first changed row conflicts immediately.
                    continue
                if row.close_time_ms not in self._candidates and len(self._candidates) >= MAX_CANDIDATE_BARS:
                    self._blocked_reason = "candidate_bar_capacity_exceeded"
                    break
                previous = self._candidates.get(row.close_time_ms)
                if previous is not None and previous.row.native_projection(
                    self.symbol
                ) == row.native_projection(self.symbol):
                    candidate = _CandidateObservation(
                        row, previous.count + 1, attempt, observation.raw_response
                    )
                    prior_observation = previous
                else:
                    candidate = _CandidateObservation(row, 1, attempt, observation.raw_response)
                    prior_observation = None
                self._candidates[row.close_time_ms] = candidate
                if candidate.count >= 2 and prior_observation is not None:
                    pair = RestCandleBarPairV3.from_attempts(
                        prior_observation.attempt,
                        prior_observation.raw_response,
                        attempt,
                        observation.raw_response,
                        open_time_ms=row.open_time_ms,
                        finality_delay_ms=self._finality_delay_ms,
                    )
                    promoted.extend(self._accept_confirmed(pair, at_ms))
            state = "PROMOTED" if promoted else "OBSERVED"
            if self._blocked_reason:
                state = "BLOCKED"
            results.append(
                self._result(
                    state, tuple(promoted), attempt.attempt_number, tuple(row.open_time_ms for row in rows)
                )
            )
        self._attempt_count = len(observations)
        self._receipt_head = checkpoint.head_sha256
        return tuple(results)

    def _accept_confirmed(self, pair: RestCandleBarPairV3, at_ms: int) -> tuple[ClosedBarEvidenceV3, ...]:
        if self._blocked_reason:
            return ()
        close_ms = pair.row.close_time_ms
        existing = self._promoted.get(close_ms)
        if existing is not None:
            if existing.pair.row.native_projection(self.symbol) != pair.row.native_projection(self.symbol):
                self._blocked_reason = "conflicting_closed_bar"
            return ()
        pending = self._pending.get(close_ms)
        if pending is not None:
            if pending.row.native_projection(self.symbol) != pair.row.native_projection(self.symbol):
                self._blocked_reason = "conflicting_closed_bar"
            return ()
        if close_ms < self._last_close_ms:
            self._blocked_reason = "reordered_closed_bar"
            return ()
        if close_ms == self._last_close_ms:
            self._blocked_reason = "anchor_duplicate_without_original"
            return ()
        if close_ms != self._last_close_ms + MINUTE_MS:
            if len(self._pending) >= self._max_pending:
                self._blocked_reason = "pending_bar_capacity_exceeded"
                return ()
            self._pending[close_ms] = pair
            return ()
        promoted = [self._promote(pair, at_ms)]
        next_close_ms = close_ms + MINUTE_MS
        while next_close_ms in self._pending:
            promoted.append(self._promote(self._pending.pop(next_close_ms), at_ms))
            next_close_ms += MINUTE_MS
        return tuple(promoted)

    def to_candle_originals_v3(self, *, ttl_ms: int) -> CandleOriginalsV3:
        if self._blocked_reason is not None:
            raise ClosedBarEvidenceError(f"blocked fold has no usable originals: {self._blocked_reason}")
        if not self._promoted:
            raise ClosedBarEvidenceError("no contiguous promoted candle evidence is available")
        records = tuple(
            self._promoted[key].to_retained_candle_v3(ttl_ms=ttl_ms) for key in sorted(self._promoted)
        )
        try:
            return CandleOriginalsV3(records=records)
        except (TypeError, ValueError) as exc:
            raise ClosedBarEvidenceError(
                "promoted records failed the existing CandleOriginalsV3 contract"
            ) from exc

    def _result(
        self,
        state: str,
        promoted: tuple[ClosedBarEvidenceV3, ...],
        attempt_number: int,
        page_open_times_ms: tuple[int, ...],
    ) -> ClosedBarFoldResultV3:
        return ClosedBarFoldResultV3(
            state=state,
            promoted=promoted,
            pending_close_times_ms=self.pending_close_times_ms,
            blocked_reason=self._blocked_reason,
            attempt_number=attempt_number,
            page_open_times_ms=page_open_times_ms,
        )

    def _promote(self, pair: RestCandleBarPairV3, at_ms: int) -> ClosedBarEvidenceV3:
        value = ClosedBarEvidenceV3(
            pair=pair,
            promotion_sequence=self._next_promotion_sequence,
            promotion_at_ms=at_ms,
        )
        self._promoted[pair.row.close_time_ms] = value
        self._last_close_ms = pair.row.close_time_ms
        self._next_promotion_sequence += 1
        return value
