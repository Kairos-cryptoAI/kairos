"""Strict canonical JSON codec for the pure adaptive SIM account reducer."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from adaptive_replay.adaptive_sim_account import (
    AccountEvent,
    AccountPolicy,
    Position,
    Reservation,
    SimAccount,
    UnresolvedFill,
)

CODEC_VERSION = 1
MAX_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 64


class AccountCodecError(ValueError):
    """The account document is malformed, out of bounds, or not canonical."""


_ALLOWED_TYPES = (AccountPolicy, Reservation, Position, UnresolvedFill, AccountEvent, SimAccount)
_TYPE_BY_NAME = {item.__name__: item for item in _ALLOWED_TYPES}


def encode_account(account: SimAccount) -> str:
    """Encode a validated account as canonical, bounded JSON text."""
    if type(account) is not SimAccount:
        raise AccountCodecError("root value must be an exact SimAccount")
    document = {"codec": "adaptive-sim-account", "version": CODEC_VERSION, "root": _encode_value(account, 0)}
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    _check_size(text)
    return text


def decode_account(text: str) -> SimAccount:
    """Decode canonical JSON, reject schema drift, and run every dataclass validator."""
    if type(text) is not str:
        raise AccountCodecError("encoded account must be a string")
    _check_size(text)
    try:
        document = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        if isinstance(error, AccountCodecError):
            raise
        raise AccountCodecError("invalid JSON account document") from error
    if type(document) is not dict or set(document) != {"codec", "version", "root"}:
        raise AccountCodecError("unknown or extra top-level fields")
    if document["codec"] != "adaptive-sim-account" or type(document["version"]) is not int:
        raise AccountCodecError("unknown account codec identifier or version")
    if document["version"] != CODEC_VERSION:
        raise AccountCodecError("unsupported account codec version")
    root = _decode_value(document["root"], 0)
    if type(root) is not SimAccount:
        raise AccountCodecError("decoded root is not a SimAccount")
    # This also rejects whitespace, alternate escaping, or otherwise noncanonical JSON.
    if encode_account(root) != text:
        raise AccountCodecError("account document is not canonical JSON")
    return root


def _encode_value(value: Any, depth: int) -> Any:
    _check_depth(depth)
    value_type = type(value)
    if value is None or value_type in {str, bool, int}:
        return value
    if value_type is Decimal:
        if not value.is_finite():
            raise AccountCodecError("non-finite Decimal is forbidden")
        return {"$decimal": str(value)}
    if value_type is tuple:
        return {"$tuple": [_encode_value(item, depth + 1) for item in value]}
    if value_type in _ALLOWED_TYPES and is_dataclass(value):
        values = {field.name: _encode_value(getattr(value, field.name), depth + 1) for field in fields(value)}
        return {"$type": value_type.__name__, "$fields": values}
    if value_type is float:
        raise AccountCodecError("float coercion is forbidden")
    if value_type is list:
        raise AccountCodecError("lists are not accepted; tuple values require the explicit tuple tag")
    raise AccountCodecError(f"unsupported account value type: {value_type.__name__}")


def _decode_value(value: Any, depth: int) -> Any:
    _check_depth(depth)
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is not dict:
        raise AccountCodecError("untagged arrays and non-JSON values are forbidden")
    keys = set(value)
    if keys == {"$decimal"}:
        text = value["$decimal"]
        if type(text) is not str:
            raise AccountCodecError("Decimal tag must contain a string")
        try:
            decimal = Decimal(text)
        except InvalidOperation as error:
            raise AccountCodecError("invalid Decimal tag") from error
        if not decimal.is_finite() or str(decimal) != text:
            raise AccountCodecError("Decimal tag must be finite and canonically formatted")
        return decimal
    if keys == {"$tuple"}:
        items = value["$tuple"]
        if type(items) is not list:
            raise AccountCodecError("tuple tag contents must be a JSON array")
        return tuple(_decode_value(item, depth + 1) for item in items)
    if keys == {"$type", "$fields"}:
        type_name = value["$type"]
        if type(type_name) is not str or type_name not in _TYPE_BY_NAME:
            raise AccountCodecError("unknown dataclass type tag")
        cls = _TYPE_BY_NAME[type_name]
        field_values = value["$fields"]
        if type(field_values) is not dict:
            raise AccountCodecError("dataclass fields must be an object")
        expected = {field.name for field in fields(cls)}
        if set(field_values) != expected:
            raise AccountCodecError(f"strict field schema mismatch for {type_name}")
        decoded = {name: _decode_value(item, depth + 1) for name, item in field_values.items()}
        try:
            return cls(**decoded)
        except (TypeError, ValueError) as error:
            raise AccountCodecError(f"invalid {type_name} values") from error
    raise AccountCodecError("unknown tag or extra tagged-object fields")


def _check_depth(depth: int) -> None:
    if depth > MAX_DEPTH:
        raise AccountCodecError(f"account nesting exceeds maximum depth {MAX_DEPTH}")


def _check_size(text: str) -> None:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise AccountCodecError(f"account document exceeds {MAX_BYTES} bytes")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AccountCodecError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_float(_: str) -> Any:
    raise AccountCodecError("JSON floating-point numbers are forbidden")


def _reject_constant(_: str) -> Any:
    raise AccountCodecError("non-finite JSON numbers are forbidden")
