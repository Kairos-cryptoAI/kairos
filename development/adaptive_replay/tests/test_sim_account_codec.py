import json
from dataclasses import replace
from decimal import Decimal as D

import pytest

from adaptive_replay.adaptive_sim_account import (
    AccountEvent,
    AccountPolicy,
    debit_cost,
    mark_account,
    new_account,
    record_entry_fill,
    record_exit_fill,
    record_funding,
    reserve_entry,
    resolve_entry,
    set_barrier,
)
from adaptive_replay.sim_account_codec import (
    AccountCodecError,
    decode_account,
    encode_account,
)

POLICY = AccountPolicy(D("0.1"), D("5"), D("5"), D("2"), 10_000)


def start_account():
    account = new_account(D("10000"), POLICY)
    account, _ = mark_account(account, mark_id="mark-0", marks=(("BTCUSDT", D("100"), 10),), as_of_ms=10)
    return account


def reserve(account, *, reservation_id="r1", side="LONG"):
    stop = D("90") if side == "LONG" else D("110")
    return reserve_entry(
        account,
        reservation_id=reservation_id,
        intent_id=f"i-{reservation_id}",
        symbol="BTCUSDT",
        side=side,
        stop_price=stop,
        worst_entry_price=D("100"),
        worst_notional_price=D("110"),
        as_of_ms=20,
        expires_at_ms=1_000,
    )


def test_round_trip_partial_position_service_funding_marks_barrier_and_unknown_fill():
    account, reservation, status = reserve(start_account())
    assert status == "RESERVED"
    account, status = record_entry_fill(
        account,
        reservation_id="r1",
        fill_id="entry-partial",
        quantity=D("1"),
        average_price=D("100"),
        fee=D("0.5"),
        at_ms=21,
    )
    assert status == "RECORDED"
    account = resolve_entry(account, reservation_id="r1", event_id="resolve-partial", outcome="PARTIAL")
    account = debit_cost(account, cost_id="service", amount=D("2.25"), at_ms=22, kind="SERVICE")
    account = record_funding(account, intent_id="i-r1", event_id="funding", cashflow=D("-0.125"), at_ms=23)
    account, _ = mark_account(account, mark_id="mark-1", marks=(("BTCUSDT", D("101.25"), 24),), as_of_ms=24)
    account = set_barrier(account, event_id="coverage-gap", reason="BOOK_COVERAGE_GAP")
    account, status = record_entry_fill(
        account,
        reservation_id="missing-reservation",
        fill_id="orphan-fill",
        quantity=D("0.1"),
        average_price=D("101"),
        fee=D("0.01"),
        at_ms=25,
    )
    assert status == "BARRIER"
    assert account.barrier == "BOOK_COVERAGE_GAP"
    assert account.positions and account.unresolved_fills

    restored = decode_account(encode_account(account))
    assert restored == account
    assert restored.events == account.events
    replayed, status = record_entry_fill(
        restored,
        reservation_id="missing-reservation",
        fill_id="orphan-fill",
        quantity=D("0.1"),
        average_price=D("101"),
        fee=D("0.01"),
        at_ms=25,
    )
    assert status == "REPLAYED"
    assert replayed == restored


@pytest.mark.parametrize("side,exit_price", [("LONG", D("105")), ("SHORT", D("95"))])
def test_round_trip_full_close_and_exact_duplicate_exit_after_decode(side, exit_price):
    account, reservation, status = reserve(start_account(), side=side)
    assert status == "RESERVED"
    account, status = record_entry_fill(
        account,
        reservation_id="r1",
        fill_id="entry-full",
        quantity=reservation.quantity,
        average_price=D("100"),
        fee=reservation.quantity * D("100") * D("5") / D("10000"),
        at_ms=21,
    )
    assert status == "RECORDED"
    account = resolve_entry(account, reservation_id="r1", event_id="resolve-full", outcome="FILLED")
    account, status = record_exit_fill(
        account,
        intent_id="i-r1",
        fill_id="exit-full",
        quantity=reservation.quantity,
        average_price=exit_price,
        fee=D("0.5"),
        at_ms=22,
    )
    assert status == "RECORDED"
    assert account.positions == ()
    restored = decode_account(encode_account(account))
    assert restored == account
    replayed, status = record_exit_fill(
        restored,
        intent_id="i-r1",
        fill_id="exit-full",
        quantity=reservation.quantity,
        average_price=exit_price,
        fee=D("0.5"),
        at_ms=22,
    )
    assert status == "REPLAYED"
    assert replayed == restored


def _canonical(document):
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def test_closed_schema_rejects_unknown_versions_tags_and_fields():
    encoded = encode_account(start_account())
    original = json.loads(encoded)

    wrong_version = dict(original, version=99)
    with pytest.raises(AccountCodecError, match="version"):
        decode_account(_canonical(wrong_version))

    extra_field = json.loads(encoded)
    extra_field["root"]["$fields"]["surprise"] = True
    with pytest.raises(AccountCodecError, match="schema mismatch"):
        decode_account(_canonical(extra_field))

    unknown_tag = json.loads(encoded)
    unknown_tag["root"]["$type"] = "UnknownAccount"
    with pytest.raises(AccountCodecError, match="unknown dataclass"):
        decode_account(_canonical(unknown_tag))

    unknown_top_field = dict(original, extension=True)
    with pytest.raises(AccountCodecError, match="top-level"):
        decode_account(_canonical(unknown_top_field))


def test_decoder_rejects_float_coercion_and_untagged_arrays():
    encoded = encode_account(start_account())
    float_document = json.loads(encoded)
    float_document["root"]["$fields"]["cash"] = 1.25
    with pytest.raises(AccountCodecError, match="floating-point"):
        decode_account(_canonical(float_document))

    list_document = json.loads(encoded)
    list_document["root"]["$fields"]["marks"] = []
    with pytest.raises(AccountCodecError, match="untagged arrays"):
        decode_account(_canonical(list_document))

    with pytest.raises(AccountCodecError, match="lists are not accepted"):
        encode_account(replace(start_account(), events=(AccountEvent("list-event", ([1, 2],)),)))


def test_dataclass_validators_run_and_decimal_is_exactly_tagged():
    account = start_account()
    encoded = encode_account(account)
    assert '"$decimal":"10000"' in encoded
    document = json.loads(encoded)
    document["root"]["$fields"]["policy"]["$fields"]["quantity_step"] = {"$decimal": "0"}
    with pytest.raises(AccountCodecError, match="invalid AccountPolicy"):
        decode_account(_canonical(document))


@pytest.mark.parametrize(
    "field,value",
    [
        ("barrier", 0),
        ("barrier", False),
        ("barrier", ""),
        ("barrier", " UNTRUSTED "),
        ("risk_over_limit", 0),
        ("risk_over_limit", 1),
        ("risk_over_limit", "false"),
        ("risk_over_limit", None),
        ("historical_risk_overrun", 0),
        ("historical_risk_overrun", "false"),
        ("historical_risk_overrun", None),
    ],
)
def test_decoder_rejects_non_typed_persisted_safety_gates(field, value):
    document = json.loads(encode_account(start_account()))
    document["root"]["$fields"][field] = value
    with pytest.raises(AccountCodecError, match="invalid SimAccount"):
        decode_account(_canonical(document))


def test_exact_risk_flags_and_normalized_barrier_survive_restart():
    account = replace(
        start_account(), barrier="SOURCE_GAP", risk_over_limit=True, historical_risk_overrun=True
    )
    restored = decode_account(encode_account(account))
    assert restored == account
    refused_account, reservation, status = reserve(restored)
    assert reservation is None
    assert status != "RESERVED"
    assert refused_account.barrier == "SOURCE_GAP"


def test_document_size_and_nesting_bounds():
    account = replace(start_account(), events=(AccountEvent("huge", ("x" * (2 * 1024 * 1024),)),))
    with pytest.raises(AccountCodecError, match="exceeds"):
        encode_account(account)

    deeply_nested = "end"
    for _ in range(70):
        deeply_nested = (deeply_nested,)
    account = replace(start_account(), events=(AccountEvent("deep", (deeply_nested,)),))
    with pytest.raises(AccountCodecError, match="nesting"):
        encode_account(account)


def test_decode_rejects_noncanonical_text_and_duplicate_keys():
    encoded = encode_account(start_account())
    with pytest.raises(AccountCodecError, match="canonical"):
        decode_account(" " + encoded)
    with pytest.raises(AccountCodecError, match="duplicate"):
        decode_account('{"codec":"adaptive-sim-account","codec":"x","root":null,"version":1}')
