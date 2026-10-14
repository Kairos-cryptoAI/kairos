"""Structured strict current-account codec with an explicit external ledger ref.

This does not relocate events or prove a ledger exists. The transactional
consumer must verify/seal the referenced complete ledger. Codec V1 and its
bounds remain unchanged; native event history is never truncated here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .adaptive_sim_account import SimAccount, _id
from .sim_account_codec import AccountCodecError, _decode_value, _encode_value

CODEC_ID = "adaptive-sim-account-core"
CODEC_VERSION = 3
MAX_CORE_BYTES = 2 * 1024 * 1024


def _plain_tree(value: Any, depth: int = 0) -> None:
    if depth > 256:
        raise AccountCodecError("structured core nesting bound exceeded")
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise AccountCodecError("exact JSON string map keys required")
        for child in value.values():
            _plain_tree(child, depth + 1)
        return
    if type(value) is list:
        for child in value:
            _plain_tree(child, depth + 1)
        return
    raise AccountCodecError("exact JSON types required; floats and coercion forbidden")


@dataclass(frozen=True)
class AccountLedgerRefV3:
    owner_id: str
    account_id: str
    event_count: int
    head_sha256: str

    def __post_init__(self) -> None:
        _id(self.owner_id, "ledger owner_id")
        _id(self.account_id, "ledger account_id")
        if type(self.event_count) is not int or not 0 <= self.event_count <= 2**63 - 1:
            raise AccountCodecError("exact bounded nonnegative ledger event count required")
        if (
            type(self.head_sha256) is not str
            or len(self.head_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.head_sha256)
        ):
            raise AccountCodecError("exact lowercase ledger SHA256 required")


def _canonical(document: Any) -> str:
    try:
        text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as error:
        raise AccountCodecError("invalid structured core document") from error
    if len(text.encode("utf-8")) > MAX_CORE_BYTES:
        raise AccountCodecError("current account core byte bound exceeded")
    return text


def encode_account_core(account: SimAccount, ledger: AccountLedgerRefV3) -> dict[str, Any]:
    """Return a fresh canonical JSON tree, permitting recursive economic deltas."""
    if type(account) is not SimAccount or account.events != ():
        raise AccountCodecError("exact current SimAccount with empty events required; no truncation")
    if type(ledger) is not AccountLedgerRefV3:
        raise AccountCodecError("exact typed external ledger reference required")
    AccountLedgerRefV3(**ledger.__dict__)
    document = {
        "codec": CODEC_ID,
        "version": CODEC_VERSION,
        "root": _encode_value(account, 0),
        "ledger": ledger.__dict__.copy(),
    }
    # Run the same dataclass validators on encode, not just after a restart.
    restored = _decode_value(document["root"], 0)
    if type(restored) is not SimAccount or restored.events != ():
        raise AccountCodecError("invalid current account core")
    return json.loads(_canonical(document))


def decode_account_core(document: dict[str, Any]) -> tuple[SimAccount, AccountLedgerRefV3]:
    """Closed structured schema; no floats, coercion, unknown tags, or extra fields."""
    if type(document) is not dict or set(document) != {"codec", "version", "root", "ledger"}:
        raise AccountCodecError("exact closed core top-level fields required")
    _plain_tree(document)
    if (
        type(document["codec"]) is not str
        or document["codec"] != CODEC_ID
        or type(document["version"]) is not int
    ):
        raise AccountCodecError("unknown core codec identifier or version")
    if document["version"] != CODEC_VERSION:
        raise AccountCodecError("unsupported core codec version")
    reference = document["ledger"]
    if type(reference) is not dict or set(reference) != {
        "owner_id",
        "account_id",
        "event_count",
        "head_sha256",
    }:
        raise AccountCodecError("exact closed ledger reference fields required")
    try:
        ledger = AccountLedgerRefV3(**reference)
    except (TypeError, ValueError) as error:
        raise AccountCodecError("invalid ledger reference") from error
    _canonical(document)
    account = _decode_value(document["root"], 0)
    if type(account) is not SimAccount or account.events != ():
        raise AccountCodecError("exact current SimAccount with empty events required; no truncation")
    # Equality alone accepts bool == int. Canonical bytes enforce exact types
    # and reject dict/list subclasses that the tagged native encoder forbids.
    if _canonical(encode_account_core(account, ledger)) != _canonical(document):
        raise AccountCodecError("noncanonical structured account core")
    return account, ledger
