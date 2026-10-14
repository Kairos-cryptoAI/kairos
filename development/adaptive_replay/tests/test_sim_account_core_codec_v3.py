import copy
import json
from dataclasses import replace
from decimal import Decimal as D

import pytest

from adaptive_replay.adaptive_sim_account import AccountEvent, AccountPolicy, Position, new_account
from adaptive_replay.sim_account_codec import MAX_BYTES, AccountCodecError, decode_account, encode_account
from adaptive_replay.sim_account_core_codec_v3 import (
    AccountLedgerRefV3,
    decode_account_core,
    encode_account_core,
)

POLICY = AccountPolicy(D("0.1"), D("5"), D("5"), D("2"), 10_000, "ENTRY_STOP_RESERVED")
REF = AccountLedgerRefV3("arm-a", "account-a", 100_000_000, "a" * 64)


def document():
    account = replace(
        new_account(D("10000.00"), POLICY),
        cash=D("9999.00"),
        marks=(("BTCUSDT", D("101.25"), 24),),
        positions=(Position("intent", "BTCUSDT", "LONG", D("90"), D("1"), D("100"), D("0.5")),),
        barrier="SOURCE_GAP",
        risk_over_limit=True,
        historical_risk_overrun=True,
        protective_exit_pending=("intent",),
    )
    return account, encode_account_core(account, REF)


def test_structured_core_exact_roundtrip_safety_and_large_external_count():
    account, doc = document()
    assert type(doc) is dict
    assert type(doc["root"]) is dict
    assert doc["root"]["$fields"]["cash"] == {"$decimal": "9999.00"}
    assert decode_account_core(doc) == (account, REF)
    doc["ledger"]["event_count"] = 1
    assert REF.event_count == 100_000_000
    assert MAX_BYTES == 2 * 1024 * 1024
    old = replace(account, events=(AccountEvent("old", ("SERVICE", D("1"), 10)),))
    assert decode_account(encode_account(old)) == old


def test_no_history_truncation_or_implicit_ledger_existence_claim():
    account, doc = document()
    history = replace(account, events=(AccountEvent("old", ("MARK",)),))
    with pytest.raises(AccountCodecError, match="empty events"):
        encode_account_core(history, REF)
    old_fields = decode_account(encode_account(history))
    assert old_fields.events == history.events
    doc["root"] = json.loads(encode_account(history))["root"]
    with pytest.raises(AccountCodecError, match="empty events"):
        decode_account_core(doc)


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("top", "extra", None),
        ("top", "version", True),
        ("top", "version", 1),
        ("top", "codec", "adaptive-sim-account"),
        ("ledger", "extra", None),
        ("ledger", "event_count", True),
        ("ledger", "event_count", -1),
        ("ledger", "event_count", 2**63),
        ("ledger", "head_sha256", "A" * 64),
        ("ledger", "owner_id", " arm-a "),
        ("root", "extra", None),
        ("fields", "extra", None),
        ("fields", "cash", 1.25),
        ("fields", "cash", {"$decimal": "NaN"}),
        ("fields", "marks", []),
        ("fields", "risk_over_limit", 1),
    ],
)
def test_closed_schema_exact_types_tags_fields_and_bounds(section, key, value):
    _, doc = document()
    target = {"top": doc, "ledger": doc["ledger"], "root": doc["root"], "fields": doc["root"]["$fields"]}
    target[section][key] = value
    with pytest.raises(AccountCodecError):
        decode_account_core(doc)


@pytest.mark.parametrize("field,value", [("risk_basis", "UNKNOWN"), ("maximum_mark_age_ms", True)])
def test_native_enum_and_dataclass_validators_remain_strict(field, value):
    _, doc = document()
    doc["root"]["$fields"]["policy"]["$fields"][field] = value
    with pytest.raises(AccountCodecError):
        decode_account_core(doc)


def test_decode_does_not_mutate_input_or_accept_coercible_map_keys():
    _, doc = document()
    saved = copy.deepcopy(doc)
    decode_account_core(doc)
    assert doc == saved
    doc["root"]["$fields"][1] = "not-a-field"
    with pytest.raises(AccountCodecError, match="string map keys"):
        decode_account_core(doc)


def test_core_size_bound_is_independent_of_external_history_count():
    account, _ = document()
    huge = replace(account, marks=tuple((f"MARK{i:05d}" + "x" * 100, D("100"), 0) for i in range(20_000)))
    with pytest.raises(AccountCodecError, match="byte bound"):
        encode_account_core(huge, REF)
