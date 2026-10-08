"""Offline byte-to-field binding for supplied native V2 top-ten book frames.

Only the explicitly named combined Binance UM depth10@100ms wire profiles
are understood. No sockets, downloads, recorder upgrade or trading authority.
Hashes and caller-attested clocks prove consistency, not publisher authenticity.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from kairos_core.contracts.simulation import RecordedTopNBookFrameV2

from .historical_context import _clock, _name, _sha, canonical, digest
from .hypothesis_v2 import EVIDENCE_KINDS
from .inputs import UNIVERSE
from .quote_capture import PAYLOAD_SCHEMA, BboCapture

SCHEMA = "kairos.development.native-book-binding.v1"
PREFIX_SCHEMA = "kairos.development.native-book-prefix.v1"
LEGACY_PROFILE = "BINANCE_UM_COMBINED_DEPTH10_100MS_LEGACY_V1"
MIGRATED_PROFILE = "BINANCE_UM_COMBINED_DEPTH10_100MS_MIGRATED_V1"
MAX_RAW_BYTES = 32_768
MAX_PREFIX_FRAMES = 512
_BASE_FIELDS = {"e", "E", "T", "s", "U", "u", "pu", "b", "a"}
_INT64_MAX = 2**63 - 1
_CONVERSION = {
    "schema": SCHEMA,
    "route": "<lowercase-symbol>@depth10@100ms",
    "levels": "all 1..10 per side; strict original order; base-asset quantity",
    "numbers": "positive decimal strings; exact decimal-to-str(float) round trip",
    "clocks": "transaction<=event<=received<=persisted; event-anchored TTL",
    "evidence": "caller-attested only; derived research bytes are NOT vendor bytes",
    "authority": "NONE",
}
CONVERSION_SHA256 = digest(_CONVERSION)


@dataclass(frozen=True)
class NativeBookPolicy:
    profile_id: str
    source_id: str
    ttl_ms: int
    evidence_kind: str

    def __post_init__(self) -> None:
        if type(self.profile_id) is not str or self.profile_id not in {LEGACY_PROFILE, MIGRATED_PROFILE}:
            raise ValueError("explicit supported native wire profile required")
        _name(self.source_id)
        _clock(self.ttl_ms)
        if not 0 < self.ttl_ms <= 5_000:
            raise ValueError("native quote TTL must be 1..5000 milliseconds")
        if type(self.evidence_kind) is not str or self.evidence_kind not in EVIDENCE_KINDS:
            raise ValueError("explicit caller-attested evidence kind required")

    @property
    def sha256(self) -> str:
        return digest(
            {
                "profile": self.profile_id,
                "source_id": self.source_id,
                "ttl_ms": self.ttl_ms,
                "evidence_kind": self.evidence_kind,
                "conversion_sha256": CONVERSION_SHA256,
            }
        )

    @property
    def quote_source_id(self) -> str:
        """Profile/conversion/TTL-bound identity required by a future hypothesis.

        The human-supplied source label is not enough to isolate two parsers.
        This is a consistency identity, still not source authentication.
        """
        NativeBookPolicy(self.profile_id, self.source_id, self.ttl_ms, self.evidence_kind)
        return f"native-book:{self.sha256}"


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate native JSON key")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise ValueError("nonfinite native JSON number")


def _integer(value: Any, name: str, *, positive: bool = False) -> int:
    if type(value) is not int or not (int(positive) <= value <= _INT64_MAX):
        raise ValueError(f"{name} must be a bounded integer without coercion")
    return value


def _decimal(value: Any) -> float:
    if type(value) is not str or len(value) > 64 or re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value) is None:
        raise ValueError("book levels require bounded positive decimal strings")
    number = Decimal(value)
    normalized = float(number)
    if not math.isfinite(normalized) or normalized <= 0 or Decimal(str(normalized)) != number:
        raise ValueError("decimal value cannot be preserved in the native float contract")
    return normalized


def _levels(value: Any, *, bids: bool) -> tuple[tuple[float, float], ...]:
    if type(value) is not list or not 1 <= len(value) <= 10:
        raise ValueError("top-ten source requires 1..10 levels on each side")
    result = []
    for level in value:
        if type(level) is not list or len(level) != 2:
            raise ValueError("each original level requires price AND quantity")
        result.append((_decimal(level[0]), _decimal(level[1])))
    prices = [price for price, _ in result]
    if prices != sorted(set(prices), reverse=bids):
        raise ValueError("original source levels must be unique and strictly ordered")
    return tuple(result)


def _bind(frame: RecordedTopNBookFrameV2, policy: NativeBookPolicy) -> dict[str, Any]:
    if type(frame) is not RecordedTopNBookFrameV2 or type(policy) is not NativeBookPolicy:
        raise ValueError("exact typed native V2 frame and policy required")
    NativeBookPolicy(policy.profile_id, policy.source_id, policy.ttl_ms, policy.evidence_kind)
    if type(frame.raw_payload) is not str:
        raise ValueError("exact original UTF-8 text required")
    try:
        raw = frame.raw_payload.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError("original text must be strict UTF-8") from exc
    if not 0 < len(raw) <= MAX_RAW_BYTES or raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("native payload requires 1..32768 UTF-8 bytes without BOM")
    # Revalidate copied/mutated/constructed Pydantic instances, not just their type.
    try:
        payload = frame.model_dump(mode="python", warnings="error")
    except ValueError:
        raise ValueError("malformed native value objects; no implicit serialization repair") from None
    checked = RecordedTopNBookFrameV2.model_validate(payload, strict=True)
    if frame.frame_sha256 != checked.frame_sha256:
        raise ValueError("original canonical frame identity required")
    if checked.continuity != "ADMITTED":
        raise ValueError("barrier/non-admitted frame cannot supply a quote")
    try:
        wire = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("native payload must be strict UTF-8 JSON") from exc
    if type(wire) is not dict or set(wire) != {"stream", "data"}:
        raise ValueError("exact combined-stream envelope required; raw/diff streams are not admitted")
    body = wire["data"]
    fields = _BASE_FIELDS | ({"st", "ps"} if policy.profile_id == MIGRATED_PROFILE else set())
    if type(body) is not dict or set(body) != fields:
        raise ValueError("native payload fields do not match the explicitly selected wire profile")
    symbol = body["s"]
    if type(symbol) is not str or symbol not in UNIVERSE or symbol != checked.symbol:
        raise ValueError("original/native symbol mismatch")
    if type(wire["stream"]) is not str or wire["stream"] != f"{symbol.lower()}@depth10@100ms":
        raise ValueError("original combined-stream route mismatch")
    if type(body["e"]) is not str or body["e"] != "depthUpdate":
        raise ValueError("original event must be depthUpdate")
    if policy.profile_id == MIGRATED_PROFILE and (
        type(body["st"]) is not int or body["st"] != 1 or type(body["ps"]) is not str or body["ps"] != symbol
    ):
        raise ValueError("migrated source must explicitly be UM with matching pair symbol")
    event = _integer(body["E"], "event_ms")
    transaction = _integer(body["T"], "transaction_ms")
    first = _integer(body["U"], "first_update_id", positive=True)
    final = _integer(body["u"], "final_update_id", positive=True)
    previous = _integer(body["pu"], "previous_update_id")
    if transaction > event or first > final or previous >= final:
        raise ValueError("original transaction/event or update-ID bounds conflict")
    if event != checked.exchange_at_ms or final != checked.exchange_update_id:
        raise ValueError("original/native event clock or update ID mismatch")
    for name in ("exchange_at_ms", "received_at_ms", "persisted_at_ms", "tape_sequence"):
        _integer(getattr(checked, name), name, positive=name == "tape_sequence")
    bid_levels, ask_levels = _levels(body["b"], bids=True), _levels(body["a"], bids=False)
    if bid_levels[0][0] >= ask_levels[0][0]:
        raise ValueError("original book must be strictly uncrossed")
    for original, normalized in ((bid_levels, checked.bids), (ask_levels, checked.asks)):
        retained = tuple((level.price, level.quantity) for level in normalized)
        if original != retained:
            raise ValueError("ALL original/native levels and quantities must match")
    return body


@dataclass(frozen=True)
class NativeBookCapture:
    """Retain original frame separately from explicitly derived research bytes."""

    frame: RecordedTopNBookFrameV2
    policy: NativeBookPolicy

    def __post_init__(self) -> None:
        _bind(self.frame, self.policy)

    @property
    def capture(self) -> BboCapture:
        body = _bind(self.frame, self.policy)
        raw = canonical(
            {
                "schema_id": PAYLOAD_SCHEMA,
                "timestamp_unit": "ms",
                "source_id": self.policy.quote_source_id,
                "symbol": body["s"],
                "event_ms": body["E"],
                "bid": _decimal(body["b"][0][0]),
                "ask": _decimal(body["a"][0][0]),
                "bid_quantity": _decimal(body["b"][0][1]),
                "ask_quantity": _decimal(body["a"][0][1]),
            }
        ).encode("utf-8")
        return BboCapture(
            raw,
            hashlib.sha256(raw).hexdigest(),
            self.frame.received_at_ms,
            self.frame.persisted_at_ms,
            self.policy.ttl_ms,
            self.policy.evidence_kind,
        )

    @property
    def sha256(self) -> str:
        return digest(
            {
                "schema": SCHEMA,
                "native_frame_sha256": self.frame.frame_sha256,
                "vendor_raw_payload_sha256": self.frame.raw_payload_sha256,
                "policy_sha256": self.policy.sha256,
                "derived_capture_sha256": self.capture.sha256,
                "risk_authority": "NONE",
            }
        )


@dataclass(frozen=True)
class BookPrefixReceipt:
    tape_id: str
    stream_epoch: str
    head_sha256: str
    policy_sha256: str
    frame_sha256s: tuple[str, ...]
    symbol_counts: tuple[tuple[str, int], ...]
    asof_ms: int
    risk_authority: str = "NONE"
    coverage_authority: str = "STRUCTURAL_PREFIX_ONLY_NOT_CONTINUOUS_MARKET_COVERAGE"

    @property
    def sha256(self) -> str:
        from dataclasses import asdict

        return digest({"schema": PREFIX_SCHEMA, **asdict(self)})


def audit_book_prefix(
    frames: tuple[RecordedTopNBookFrameV2, ...],
    policy: NativeBookPolicy,
    *,
    tape_id: str,
    stream_epoch: str,
    expected_head_sha256: str,
    asof_ms: int,
) -> BookPrefixReceipt:
    """Audit a supplied complete root-to-head prefix, never a selected subsequence.

    The head is caller-pinned, not an external signature. Symbol counts include
    zeros. Even all five symbols and intact hashes do NOT prove no dropped
    market events, authenticated clocks, episode completeness or fill authority.
    ``pu`` is retained, not repurposed as a diff-depth reconstruction gate.
    """
    if type(frames) is not tuple or not 1 <= len(frames) <= MAX_PREFIX_FRAMES:
        raise ValueError("bounded immutable native frame prefix required (1..512)")
    _name(tape_id)
    _name(stream_epoch)
    _sha(expected_head_sha256)
    _clock(asof_ms)
    counts = {symbol: 0 for symbol in sorted(UNIVERSE)}
    previous_hash = None
    previous_persisted = -1
    previous_by_symbol: dict[str, tuple[int, int, int]] = {}
    hashes = []
    for sequence, frame in enumerate(frames, start=1):
        bound = NativeBookCapture(frame, policy)
        body = _bind(bound.frame, bound.policy)
        if frame.tape_id != tape_id or frame.stream_epoch != stream_epoch:
            raise ValueError("tape/epoch conflict: never join across reconnects")
        if frame.tape_sequence != sequence or frame.previous_frame_sha256 != previous_hash:
            raise ValueError("complete consecutive root-to-head frame chain required")
        if frame.persisted_at_ms < previous_persisted or frame.persisted_at_ms > asof_ms:
            raise ValueError("prefix persistence clocks regress or exceed as-of boundary")
        previous = previous_by_symbol.get(frame.symbol)
        clocks = (body["u"], body["E"], frame.received_at_ms)
        if previous is not None and (
            clocks[0] <= previous[0] or clocks[1] < previous[1] or clocks[2] < previous[2]
        ):
            raise ValueError("per-symbol update IDs or event/receive clocks regress")
        previous_by_symbol[frame.symbol] = clocks
        counts[frame.symbol] += 1
        hashes.append(frame.frame_sha256)
        previous_hash = frame.frame_sha256
        previous_persisted = frame.persisted_at_ms
    if previous_hash != expected_head_sha256:
        raise ValueError("supplied prefix does not end at the explicitly expected head")
    return BookPrefixReceipt(
        tape_id,
        stream_epoch,
        expected_head_sha256,
        policy.sha256,
        tuple(hashes),
        tuple(counts.items()),
        asof_ms,
    )
