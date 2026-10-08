"""Strict engineering-only parser for caller-supplied BBO capture bytes.

This is a Kairos research wire schema, not an exchange protocol or an
authenticated feed. Clock and source checks establish internal consistency
only; they do not establish publisher authenticity or real-world chronology.
The payload's bid_quantity and ask_quantity fields are base-asset units.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any

from .historical_context import _clock, _name, digest
from .hypothesis_v2 import EVIDENCE_KINDS, EntryQuote, HypothesisPlan
from .inputs import UNIVERSE

SCHEMA = "kairos.development.bbo-capture.v1"
PAYLOAD_SCHEMA = "kairos.development.bbo-payload.v1"
MAX_PAYLOAD_BYTES = 8_192
_PAYLOAD_FIELDS = frozenset(
    {
        "schema_id",
        "timestamp_unit",
        "source_id",
        "symbol",
        "event_ms",
        "bid",
        "ask",
        "bid_quantity",
        "ask_quantity",
    }
)


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not permitted: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _positive_number(value: Any, name: str) -> float:
    try:
        valid = type(value) in {int, float} and math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be a finite positive JSON number")
    return float(value)


def _payload(raw_payload: bytes) -> dict[str, Any]:
    if type(raw_payload) is not bytes:
        raise ValueError("raw_payload must be immutable bytes")
    if not raw_payload or len(raw_payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("raw_payload must contain 1..8192 bytes")
    if raw_payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError("UTF-8 BOM is not permitted")
    try:
        text = raw_payload.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("raw_payload must be strict UTF-8 JSON") from exc
    if type(value) is not dict:
        raise ValueError("raw_payload must be a JSON object")
    if set(value) != _PAYLOAD_FIELDS:
        raise ValueError("raw_payload fields must exactly match the v1 BBO payload schema")
    if value["schema_id"] != PAYLOAD_SCHEMA or type(value["schema_id"]) is not str:
        raise ValueError("unsupported BBO payload schema_id")
    if value["timestamp_unit"] != "ms" or type(value["timestamp_unit"]) is not str:
        raise ValueError("timestamp_unit must be exactly 'ms'")
    if type(value["source_id"]) is not str:
        raise ValueError("source_id must be a string")
    _name(value["source_id"])
    if type(value["symbol"]) is not str or value["symbol"] not in UNIVERSE:
        raise ValueError("symbol must be in the configured research universe")
    _clock(value["event_ms"])
    bid = _positive_number(value["bid"], "bid")
    ask = _positive_number(value["ask"], "ask")
    _positive_number(value["bid_quantity"], "bid_quantity")
    _positive_number(value["ask_quantity"], "ask_quantity")
    if bid >= ask:
        raise ValueError("BBO must be strictly uncrossed (bid < ask)")
    return value


@dataclass(frozen=True)
class BboCapture:
    """Exact-byte BBO capture with caller-attested clocks, not feed provenance."""

    raw_payload: bytes
    raw_payload_sha256: str
    received_ms: int
    captured_ms: int
    ttl_ms: int
    evidence_kind: str

    def __post_init__(self) -> None:
        value = _payload(self.raw_payload)
        for clock in (self.received_ms, self.captured_ms, self.ttl_ms):
            _clock(clock)
        _name(self.evidence_kind)
        if self.evidence_kind not in EVIDENCE_KINDS:
            raise ValueError("unsupported evidence_kind")
        if self.ttl_ms <= 0:
            raise ValueError("ttl_ms must be positive")
        if not value["event_ms"] <= self.received_ms <= self.captured_ms:
            raise ValueError("capture clocks must satisfy event <= received <= captured")
        expected = hashlib.sha256(self.raw_payload).hexdigest()
        if type(self.raw_payload_sha256) is not str or self.raw_payload_sha256 != expected:
            raise ValueError("raw_payload_sha256 does not match exact raw_payload bytes")

    @property
    def quote(self) -> EntryQuote:
        value = _payload(self.raw_payload)
        return EntryQuote(
            value["source_id"],
            value["symbol"],
            _positive_number(value["bid"], "bid"),
            _positive_number(value["ask"], "ask"),
            value["event_ms"],
            self.received_ms,
            self.captured_ms,
            self.ttl_ms,
            self.evidence_kind,
        )

    @property
    def bid_quantity(self) -> float:
        """Displayed bid quantity in base-asset units (not quote notional)."""
        return _positive_number(_payload(self.raw_payload)["bid_quantity"], "bid_quantity")

    @property
    def ask_quantity(self) -> float:
        """Displayed ask quantity in base-asset units (not quote notional)."""
        return _positive_number(_payload(self.raw_payload)["ask_quantity"], "ask_quantity")

    @property
    def sha256(self) -> str:
        quote = self.quote
        return digest(
            {
                "schema": SCHEMA,
                "raw_payload_sha256": self.raw_payload_sha256,
                "received_ms": self.received_ms,
                "captured_ms": self.captured_ms,
                "ttl_ms": self.ttl_ms,
                "evidence_kind": self.evidence_kind,
                "quote": asdict(quote),
                "bid_quantity": self.bid_quantity,
                "ask_quantity": self.ask_quantity,
            }
        )


def admit_capture(
    plan: HypothesisPlan,
    capture: BboCapture,
    at_ms: int,
    after_ms: int,
) -> EntryQuote:
    """Admit an internally consistent point-in-time quote for research only."""

    if type(plan) is not HypothesisPlan or type(capture) is not BboCapture:
        raise ValueError("typed hypothesis plan and BBO capture required")
    _clock(at_ms)
    _clock(after_ms)
    # Re-run the typed plan's invariants as well as the capture parser at this
    # admission boundary; neither object is an authority by its hash alone.
    checked_plan = HypothesisPlan(
        plan.template,
        plan.origin,
        plan.regime,
        plan.created_ms,
        plan.source_set_sha256,
        plan.context_sha256,
        plan.creation_evidence,
        plan.anchor,
        plan.required_sources,
        plan.policy,
    )
    checked = BboCapture(
        capture.raw_payload,
        capture.raw_payload_sha256,
        capture.received_ms,
        capture.captured_ms,
        capture.ttl_ms,
        capture.evidence_kind,
    )
    quote = checked.quote
    if (
        quote.source_id != checked_plan.policy.quote_source_id
        or quote.symbol != checked_plan.template.symbol
        or quote.evidence_kind != checked_plan.policy.evidence_kind
    ):
        raise ValueError("BBO source, symbol, or evidence kind does not match hypothesis plan")
    if quote.event_ms < after_ms:
        raise ValueError("BBO event predates the required causal boundary")
    if quote.captured_ms > at_ms:
        raise ValueError("BBO capture is later than the admission clock")
    if at_ms - quote.event_ms > min(quote.ttl_ms, checked_plan.policy.maximum_quote_age_ms):
        raise ValueError("BBO event is stale at the admission clock")
    return quote
