"""Offline tests for native Binance UM depth payload to research-BBO binding.

Fixtures are authored here so this suite does not borrow mutable helpers from
other test modules or treat vendor examples as captured evidence.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from kairos_core.contracts.simulation import (
    RecordedBookLevelV1,
    RecordedTopNBookFrameV1,
    RecordedTopNBookFrameV2,
)
from pydantic import ValidationError

import adaptive_replay.native_book_capture as native_book_capture
from adaptive_replay.native_book_capture import (
    LEGACY_PROFILE,
    MAX_RAW_BYTES,
    MIGRATED_PROFILE,
    NativeBookCapture,
    NativeBookPolicy,
    audit_book_prefix,
)

T0 = 1_800_000_000_000
SYMBOL = "BTCUSDT"
SOURCE_ID = "native-depth"
EVIDENCE = "TEST_FIXTURE"


def _native_data(
    *,
    symbol: str = SYMBOL,
    event_ms: int = T0 + 10,
    transaction_ms: int = T0 + 9,
    first_update_id: int = 100,
    final_update_id: int = 101,
    previous_update_id: int = 99,
    bids: list[list[object]] | None = None,
    asks: list[list[object]] | None = None,
    migrated: bool = False,
    **changes: object,
) -> dict[str, object]:
    data: dict[str, object] = {
        "e": "depthUpdate",
        "E": event_ms,
        "T": transaction_ms,
        "s": symbol,
        "U": first_update_id,
        "u": final_update_id,
        "pu": previous_update_id,
        "b": bids if bids is not None else [["100.00", "1.25"], ["99.50", "2.5"]],
        "a": asks if asks is not None else [["100.50", "3.75"], ["101.00", "4"]],
    }
    if migrated:
        data.update({"st": 1, "ps": symbol})
    data.update(changes)
    return data


def _wire(
    *,
    profile: str = LEGACY_PROFILE,
    symbol: str = SYMBOL,
    data: dict[str, object] | None = None,
    stream: str | None = None,
    raw: bytes | None = None,
) -> bytes:
    if raw is not None:
        return raw
    migrated = profile == MIGRATED_PROFILE
    body = data if data is not None else _native_data(symbol=symbol, migrated=migrated)
    envelope = {
        "stream": stream if stream is not None else f"{symbol.lower()}@depth10@100ms",
        "data": body,
    }
    return json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _levels(wire: bytes, side: str) -> tuple[RecordedBookLevelV1, ...]:
    body = json.loads(wire)["data"]
    return tuple(
        RecordedBookLevelV1(price=float(price), quantity=float(quantity)) for price, quantity in body[side]
    )


def _frame(
    *,
    profile: str = LEGACY_PROFILE,
    symbol: str = SYMBOL,
    sequence: int = 1,
    previous_hash: str | None = None,
    epoch: str = "public-000001",
    tape_id: str = "native-tape",
    event_ms: int = T0 + 10,
    received_ms: int | None = None,
    persisted_ms: int | None = None,
    update_id: int = 101,
    wire: bytes | None = None,
    data: dict[str, object] | None = None,
    stream: str | None = None,
    continuity: str = "ADMITTED",
    bid_levels: tuple[RecordedBookLevelV1, ...] | None = None,
    ask_levels: tuple[RecordedBookLevelV1, ...] | None = None,
) -> RecordedTopNBookFrameV2:
    if wire is None and data is None:
        data = _native_data(
            symbol=symbol,
            event_ms=event_ms,
            transaction_ms=max(0, event_ms - 1),
            first_update_id=max(1, update_id - 1),
            final_update_id=update_id,
            previous_update_id=max(0, update_id - 2),
            migrated=profile == MIGRATED_PROFILE,
        )
    raw = _wire(profile=profile, symbol=symbol, data=data, stream=stream, raw=wire)
    try:
        body = json.loads(raw)["data"]
        if type(body) is not dict or "b" not in body or "a" not in body:
            raise KeyError("synthetic fallback for malformed/partial payload")
        level_wire = raw
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        # A malformed-byte fixture still needs a structurally valid V2 frame;
        # only the adapter under test should reject its source bytes.
        body = _native_data(symbol=symbol, migrated=profile == MIGRATED_PROFILE)
        level_wire = _wire(profile=profile, symbol=symbol, data=body)
    fallback_wire = _wire(profile=profile, symbol=symbol)

    def valid_contract_levels(side: str) -> tuple[RecordedBookLevelV1, ...]:
        try:
            values = _levels(level_wire, side)
            prices = [item.price for item in values]
            ordered = prices == sorted(set(prices), reverse=side == "b")
            if values and ordered:
                return values
        except (KeyError, TypeError, ValueError, IndexError):
            pass
        return _levels(fallback_wire, side)

    bids = valid_contract_levels("b") if bid_levels is None else bid_levels
    asks = valid_contract_levels("a") if ask_levels is None else ask_levels
    if bid_levels is None and ask_levels is None and bids[0].price >= asks[0].price:
        bids, asks = _levels(fallback_wire, "b"), _levels(fallback_wire, "a")
    received = event_ms + 1 if received_ms is None else received_ms
    persisted = received + 1 if persisted_ms is None else persisted_ms
    return RecordedTopNBookFrameV2(
        source="synthetic-fixture",
        tape_id=tape_id,
        stream_epoch=epoch,
        symbol=symbol,
        tape_sequence=sequence,
        exchange_update_id=update_id,
        exchange_at_ms=event_ms,
        received_at_ms=received,
        persisted_at_ms=persisted,
        raw_payload=raw.decode("utf-8"),
        raw_payload_sha256=hashlib.sha256(raw).hexdigest(),
        previous_frame_sha256=previous_hash,
        continuity=continuity,
        source_reason="SNAPSHOT_RECEIVED",
        bids=bids,
        asks=asks,
    )


def _policy(profile: str = LEGACY_PROFILE, **changes: object) -> NativeBookPolicy:
    values: dict[str, object] = {
        "profile_id": profile,
        "source_id": SOURCE_ID,
        "ttl_ms": 1_000,
        "evidence_kind": EVIDENCE,
    }
    values.update(changes)
    return NativeBookPolicy(**values)


def _ten_levels(*, bid: bool) -> list[list[str]]:
    base = 110 if bid else 111
    return [[str(base - i if bid else base + i), str(i + 1)] for i in range(10)]


def test_legacy_native_frame_binds_every_level_then_derives_separate_bbo_bytes() -> None:
    wire = _wire(data=_native_data(bids=_ten_levels(bid=True), asks=_ten_levels(bid=False)))
    frame = _frame(wire=wire, bid_levels=_levels(wire, "b"), ask_levels=_levels(wire, "a"))

    result = NativeBookCapture(frame, _policy())
    derived = result.capture

    assert frame.raw_payload.encode("utf-8") == wire
    assert frame.raw_payload_sha256 == hashlib.sha256(wire).hexdigest()
    assert derived.raw_payload != wire
    assert derived.raw_payload != frame.raw_payload.encode("utf-8")
    assert json.loads(derived.raw_payload) == {
        "schema_id": "kairos.development.bbo-payload.v1",
        "timestamp_unit": "ms",
        "source_id": result.policy.quote_source_id,
        "symbol": SYMBOL,
        "event_ms": T0 + 10,
        "bid": 110.0,
        "ask": 111.0,
        "bid_quantity": 1.0,
        "ask_quantity": 1.0,
    }
    assert derived.raw_payload_sha256 == hashlib.sha256(derived.raw_payload).hexdigest()
    assert derived.evidence_kind == EVIDENCE
    assert result.sha256 != frame.raw_payload_sha256


def test_migrated_profile_requires_explicit_um_and_matching_pair() -> None:
    frame = _frame(profile=MIGRATED_PROFILE)
    native = NativeBookCapture(frame, _policy(MIGRATED_PROFILE))
    capture = native.capture
    assert capture.quote.symbol == SYMBOL
    assert capture.quote.source_id == native.policy.quote_source_id
    assert capture.quote.source_id != _policy(LEGACY_PROFILE).quote_source_id

    for data in (
        _native_data(migrated=True, st=2),
        _native_data(migrated=True, ps="ETHUSDT"),
        _native_data(migrated=True, st=True),
    ):
        with pytest.raises(ValueError, match="migrated source"):
            NativeBookCapture(_frame(profile=MIGRATED_PROFILE, data=data), _policy(MIGRATED_PROFILE))


def test_legacy_and_migrated_profile_fields_cannot_be_interchanged() -> None:
    migrated = _native_data(migrated=True)
    with pytest.raises(ValueError, match="selected wire profile"):
        NativeBookCapture(_frame(data=migrated), _policy(LEGACY_PROFILE))

    legacy = _native_data()
    with pytest.raises(ValueError, match="selected wire profile"):
        NativeBookCapture(_frame(profile=MIGRATED_PROFILE, data=legacy), _policy(MIGRATED_PROFILE))


@pytest.mark.parametrize(
    "field,value",
    [
        ("E", T0 + 11),
        ("u", 102),
        ("s", "ETHUSDT"),
        ("e", "bookTicker"),
    ],
)
def test_original_event_symbol_and_update_id_are_bound_to_frame(field: str, value: object) -> None:
    data = _native_data(**{field: value})
    with pytest.raises(ValueError):
        NativeBookCapture(_frame(data=data), _policy())


@pytest.mark.parametrize("side", ["b", "a"])
@pytest.mark.parametrize("field", ["price", "quantity"])
@pytest.mark.parametrize("index", [0, 1])
def test_every_original_price_and_quantity_is_bound_not_only_top_of_book(
    side: str, field: str, index: int
) -> None:
    wire = _wire()
    bids, asks = list(_levels(wire, "b")), list(_levels(wire, "a"))
    levels = bids if side == "b" else asks
    first = levels[index]
    levels[index] = RecordedBookLevelV1(
        price=first.price + (0.01 if field == "price" else 0),
        quantity=first.quantity + (0.01 if field == "quantity" else 0),
    )
    with pytest.raises(ValueError, match="ALL original/native levels"):
        NativeBookCapture(_frame(wire=wire, bid_levels=tuple(bids), ask_levels=tuple(asks)), _policy())


def test_truncated_or_extra_normalized_depth_does_not_match_native_payload() -> None:
    wire = _wire()
    bids, asks = _levels(wire, "b"), _levels(wire, "a")
    with pytest.raises(ValueError, match="ALL original/native levels"):
        NativeBookCapture(_frame(wire=wire, bid_levels=bids[:1]), _policy())
    with pytest.raises(ValueError, match="ALL original/native levels"):
        NativeBookCapture(_frame(wire=wire, ask_levels=asks[:1]), _policy())


@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        b"[]",
        b"\xef\xbb\xbf{}",
        b'{"stream":"btcusdt@depth10@100ms","data":{"e":"depthUpdate","E":1800000000010,"T":1800000000009,"s":"BTCUSDT","U":100,"u":101,"pu":99,"b":[[NaN,"1"]],"a":[["100.5","1"]]}}',
        b'{"stream":"btcusdt@depth10@100ms","stream":"btcusdt@depth10@100ms","data":{}}',
        b'{"stream":"btcusdt@depth10@100ms","data":{},"extra":1}',
    ],
)
def test_invalid_json_bom_duplicate_and_unknown_envelope_fields_rejected(raw: bytes) -> None:
    with pytest.raises(ValueError):
        NativeBookCapture(_frame(wire=raw), _policy())


def test_payload_byte_bound_is_enforced() -> None:
    raw = _wire() + b" " * (MAX_RAW_BYTES + 1)
    with pytest.raises(ValueError, match="32768"):
        NativeBookCapture(_frame(wire=raw), _policy())


@pytest.mark.parametrize(
    "data",
    [
        {},
        _native_data(extra=1),
        _native_data(e=True),
        _native_data(E=True),
        _native_data(T="1800000000009"),
        _native_data(U=False),
        _native_data(u="101"),
        _native_data(pu=True),
        _native_data(b=[[100, "1"]]),
        _native_data(a=[["100.5"]]),
        _native_data(b=[]),
        _native_data(a=[["100.5", "1"]] * 11),
    ],
)
def test_native_body_schema_and_required_fields_are_strict(data: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        NativeBookCapture(_frame(data=data), _policy())


@pytest.mark.parametrize("price", ["0", "-1", "1e2", ".5", "1.", "1.00000000000000001", "NaN"])
def test_level_price_requires_positive_exact_decimal_roundtrip(price: str) -> None:
    data = _native_data(bids=[[price, "1"]])
    with pytest.raises(ValueError):
        NativeBookCapture(_frame(data=data), _policy())


@pytest.mark.parametrize("quantity", ["0", "-1", "1e2", "1.00000000000000001", "Infinity"])
def test_level_quantity_is_never_inferred_or_coerced(quantity: str) -> None:
    data = _native_data(bids=[["100", quantity]])
    with pytest.raises(ValueError):
        NativeBookCapture(_frame(data=data), _policy())


@pytest.mark.parametrize(
    "bids,asks",
    [
        ([["100", "1"], ["100", "2"]], [["101", "1"]]),
        ([["99", "1"], ["100", "2"]], [["101", "1"]]),
        ([["100", "1"]], [["102", "1"], ["101", "1"]]),
        ([["100", "1"]], [["100", "1"]]),
        ([["101", "1"]], [["100", "1"]]),
    ],
)
def test_original_order_duplicates_and_uncrossed_bbo_are_required(bids, asks) -> None:
    with pytest.raises(ValueError):
        NativeBookCapture(_frame(data=_native_data(bids=bids, asks=asks)), _policy())


def test_route_and_complete_combined_envelope_are_required() -> None:
    with pytest.raises(ValueError, match="route"):
        NativeBookCapture(_frame(stream="btcusdt@depth20@100ms"), _policy())
    raw_stream = json.dumps(_native_data()).encode()
    with pytest.raises(ValueError, match="combined-stream envelope"):
        NativeBookCapture(_frame(wire=raw_stream), _policy())


@pytest.mark.parametrize(
    "overrides",
    [
        {"transaction_ms": T0 + 11},
        {"first_update_id": 102, "final_update_id": 101},
        {"previous_update_id": 101},
    ],
)
def test_transaction_event_and_update_id_ranges_are_consistent(overrides: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        NativeBookCapture(_frame(data=_native_data(**overrides)), _policy())


def test_non_admitted_barrier_cannot_be_used_as_a_quote() -> None:
    barrier = _frame(continuity="GAP", bid_levels=(), ask_levels=())
    with pytest.raises(ValueError, match="barrier/non-admitted"):
        NativeBookCapture(barrier, _policy())


def test_only_exact_validated_v2_frame_is_accepted_and_copied_models_are_revalidated() -> None:
    wire = _wire()
    common = {
        "source": "synthetic-fixture",
        "tape_id": "native-tape",
        "stream_epoch": "public-000001",
        "symbol": SYMBOL,
        "tape_sequence": 1,
        "exchange_update_id": 101,
        "exchange_at_ms": T0 + 10,
        "received_at_ms": T0 + 11,
        "persisted_at_ms": T0 + 12,
        "raw_payload_sha256": hashlib.sha256(wire).hexdigest(),
        "continuity": "ADMITTED",
        "bids": _levels(wire, "b"),
        "asks": _levels(wire, "a"),
    }
    v1 = RecordedTopNBookFrameV1(**common)
    with pytest.raises(ValueError, match="exact typed native V2"):
        NativeBookCapture(v1, _policy())  # type: ignore[arg-type]

    good = _frame(wire=wire)
    forged = good.model_copy(update={"bids": (RecordedBookLevelV1(price=98, quantity=9),)})
    with pytest.raises((ValueError, ValidationError)):
        NativeBookCapture(forged, _policy())

    constructed = RecordedTopNBookFrameV2.model_construct(**good.model_dump(mode="python"))
    altered = constructed.model_copy(update={"exchange_update_id": 777})
    with pytest.raises((ValueError, ValidationError)):
        NativeBookCapture(altered, _policy())


@pytest.mark.parametrize(
    "values",
    [
        {"profile_id": "", "ttl_ms": 1, "evidence_kind": EVIDENCE},
        {"profile_id": LEGACY_PROFILE, "ttl_ms": 0, "evidence_kind": EVIDENCE},
        {"profile_id": LEGACY_PROFILE, "ttl_ms": 5_001, "evidence_kind": EVIDENCE},
        {"profile_id": LEGACY_PROFILE, "ttl_ms": True, "evidence_kind": EVIDENCE},
        {"profile_id": LEGACY_PROFILE, "ttl_ms": 1, "evidence_kind": "AUTHENTICATED"},
    ],
)
def test_policy_requires_explicit_supported_profile_bounded_ttl_and_evidence(values) -> None:
    with pytest.raises(ValueError):
        _policy(**values)


def test_quote_source_identity_isolated_by_every_policy_component(monkeypatch) -> None:
    base = _policy()
    assert base.quote_source_id == f"native-book:{base.sha256}"
    variants = (
        _policy(MIGRATED_PROFILE),
        _policy(ttl_ms=999),
        _policy(evidence_kind="CALLER_ATTESTED_POINT_IN_TIME"),
        _policy(source_id="other-label"),
    )
    assert len({base.quote_source_id, *(item.quote_source_id for item in variants)}) == 5

    before = base.quote_source_id
    monkeypatch.setattr(native_book_capture, "CONVERSION_SHA256", "c" * 64)
    assert base.quote_source_id != before


@pytest.mark.parametrize(
    "profile,source,ttl,evidence",
    [
        (None, SOURCE_ID, 1, EVIDENCE),
        (True, SOURCE_ID, 1, EVIDENCE),
        (1, SOURCE_ID, 1, EVIDENCE),
        (LEGACY_PROFILE, None, 1, EVIDENCE),
        (LEGACY_PROFILE, True, 1, EVIDENCE),
        (LEGACY_PROFILE, "", 1, EVIDENCE),
        (LEGACY_PROFILE, " spaced", 1, EVIDENCE),
        (LEGACY_PROFILE, "bad label", 1, EVIDENCE),
        (LEGACY_PROFILE, "/bad", 1, EVIDENCE),
        (LEGACY_PROFILE, "x" * 129, 1, EVIDENCE),
        (LEGACY_PROFILE, SOURCE_ID, None, EVIDENCE),
        (LEGACY_PROFILE, SOURCE_ID, False, EVIDENCE),
        (LEGACY_PROFILE, SOURCE_ID, 1.0, EVIDENCE),
        (LEGACY_PROFILE, SOURCE_ID, -1, EVIDENCE),
        (LEGACY_PROFILE, SOURCE_ID, 1, None),
        (LEGACY_PROFILE, SOURCE_ID, 1, True),
        (LEGACY_PROFILE, SOURCE_ID, 1, "UNKNOWN_EVIDENCE"),
    ],
)
def test_policy_rejects_bad_field_types_ranges_and_source_labels(profile, source, ttl, evidence) -> None:
    with pytest.raises(ValueError):
        NativeBookPolicy(profile, source, ttl, evidence)


@pytest.mark.parametrize("ttl", [1, 5_000])
def test_policy_accepts_inclusive_ttl_boundaries(ttl: int) -> None:
    policy = _policy(ttl_ms=ttl)
    assert policy.ttl_ms == ttl
    assert policy.quote_source_id == f"native-book:{policy.sha256}"


def test_capture_keeps_caller_evidence_and_never_promotes_authority() -> None:
    native = NativeBookCapture(_frame(), _policy(evidence_kind="TEST_FIXTURE"))
    capture = native.capture
    assert capture.evidence_kind == "TEST_FIXTURE"
    assert native.frame.source == "synthetic-fixture"
    assert native.frame.raw_payload_sha256 == hashlib.sha256(native.frame.raw_payload.encode()).hexdigest()
    assert not hasattr(native, "risk_authority")


def _prefix(*, epoch2: bool = False):
    first = _frame(sequence=1, symbol="BTCUSDT", event_ms=T0 + 10, received_ms=T0 + 11, persisted_ms=T0 + 12)
    second_epoch = "public-000002" if epoch2 else "public-000001"
    second = _frame(
        sequence=2,
        symbol="ETHUSDT",
        event_ms=T0 + 20,
        received_ms=T0 + 21,
        persisted_ms=T0 + 22,
        epoch=second_epoch,
        previous_hash=first.frame_sha256,
        update_id=101,
    )
    return first, second


def test_prefix_requires_full_root_to_head_chain_and_reports_zero_symbol_counts() -> None:
    frames = _prefix()
    receipt = audit_book_prefix(
        frames,
        _policy(),
        tape_id="native-tape",
        stream_epoch="public-000001",
        expected_head_sha256=frames[-1].frame_sha256 or "",
        asof_ms=T0 + 100,
    )
    assert receipt.frame_sha256s == tuple(frame.frame_sha256 for frame in frames)
    assert receipt.symbol_counts == (
        ("BNBUSDT", 0),
        ("BTCUSDT", 1),
        ("ETHUSDT", 1),
        ("SOLUSDT", 0),
        ("XRPUSDT", 0),
    )
    assert receipt.risk_authority == "NONE"
    assert receipt.coverage_authority == "STRUCTURAL_PREFIX_ONLY_NOT_CONTINUOUS_MARKET_COVERAGE"


@pytest.mark.parametrize(
    "case", ["wrong_head", "wrong_tape", "wrong_epoch", "asof", "regress_persist", "skip_root"]
)
def test_prefix_rejects_wrong_identity_incomplete_chain_and_clock_boundaries(case: str) -> None:
    frames = _prefix()
    expected = frames[-1].frame_sha256 or ""
    tape, epoch, asof = "native-tape", "public-000001", T0 + 100
    if case == "wrong_head":
        expected = "0" * 64
    elif case == "wrong_tape":
        tape = "other-tape"
    elif case == "wrong_epoch":
        frames = _prefix(epoch2=True)
    elif case == "asof":
        asof = T0 + 21
    elif case == "regress_persist":
        second = _frame(
            sequence=2,
            symbol="ETHUSDT",
            event_ms=T0 + 10,
            received_ms=T0 + 10,
            persisted_ms=T0 + 11,
            data=_native_data(symbol="ETHUSDT", event_ms=T0 + 10, transaction_ms=T0 + 9),
            previous_hash=frames[0].frame_sha256,
        )
        frames = (frames[0], second)
    elif case == "skip_root":
        frames = frames[1:]
    for frame in frames:
        if frame.continuity == "ADMITTED":
            NativeBookCapture(frame, _policy())
    match = {
        "wrong_head": "supplied prefix does not end",
        "wrong_tape": "tape/epoch conflict",
        "wrong_epoch": "tape/epoch conflict",
        "asof": "prefix persistence clocks",
        "regress_persist": "prefix persistence clocks",
        "skip_root": "complete consecutive root-to-head",
    }[case]
    with pytest.raises(ValueError, match=match):
        audit_book_prefix(
            frames,
            _policy(),
            tape_id=tape,
            stream_epoch=epoch,
            expected_head_sha256=expected,
            asof_ms=asof,
        )


@pytest.mark.parametrize("case", ["update", "event", "received", "repeat"])
def test_prefix_rejects_per_symbol_order_regressions(case: str) -> None:
    first = _frame(sequence=1, event_ms=T0 + 10, received_ms=T0 + 11, persisted_ms=T0 + 12, update_id=101)
    update_id, event_ms, received_ms = 102, T0 + 20, T0 + 21
    if case in {"update", "repeat"}:
        update_id = 100 if case == "update" else 101
    elif case == "event":
        event_ms = T0 + 9
    else:
        event_ms, received_ms = T0 + 10, T0 + 10
    data = _native_data(
        event_ms=event_ms,
        transaction_ms=min(T0 + 9, event_ms),
        final_update_id=update_id,
    )
    second = _frame(
        sequence=2,
        event_ms=event_ms,
        received_ms=received_ms,
        persisted_ms=T0 + 22,
        update_id=update_id,
        data=data,
        previous_hash=first.frame_sha256,
    )
    NativeBookCapture(first, _policy())
    NativeBookCapture(second, _policy())
    with pytest.raises(ValueError, match="per-symbol"):
        audit_book_prefix(
            (first, second),
            _policy(),
            tape_id="native-tape",
            stream_epoch="public-000001",
            expected_head_sha256=second.frame_sha256 or "",
            asof_ms=T0 + 100,
        )


def test_prefix_rejects_gap_and_cross_epoch_barrier_instead_of_joining_streams() -> None:
    first = _frame(sequence=1)
    gap = _frame(
        sequence=2,
        previous_hash=first.frame_sha256,
        epoch="public-000002",
        continuity="GAP",
        bid_levels=(),
        ask_levels=(),
    )
    with pytest.raises(ValueError):
        audit_book_prefix(
            (first, gap),
            _policy(),
            tape_id="native-tape",
            stream_epoch="public-000001",
            expected_head_sha256=gap.frame_sha256 or "",
            asof_ms=T0 + 100,
        )


def test_prefix_requires_immutable_bounded_tuple_not_selected_list() -> None:
    frame = _frame()
    with pytest.raises(ValueError, match="immutable"):
        audit_book_prefix(
            [frame],  # type: ignore[arg-type]
            _policy(),
            tape_id="native-tape",
            stream_epoch="public-000001",
            expected_head_sha256=frame.frame_sha256 or "",
            asof_ms=T0 + 100,
        )
