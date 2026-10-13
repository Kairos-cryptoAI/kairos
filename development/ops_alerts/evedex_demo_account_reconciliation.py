"""Pure, fail-closed parsers for a bounded EVEDEX DEMO account sample.

This module deliberately contains no transport, credential, persistence, or
trading code. Returned summaries contain only counts, booleans, and fixed
categories; raw exchange objects and financial amounts are never returned.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


class AccountSchemaError(ValueError):
    """A sanitized schema/consistency error with a fixed category."""

    def __init__(self, category: str) -> None:
        if category not in {
            "invalid_shape",
            "invalid_type",
            "invalid_number",
            "negative_value",
            "count_mismatch",
            "pagination_incomplete",
            "ambiguous_coin",
            "duplicate_currency",
        }:
            category = "invalid_shape"
        self.category = category
        super().__init__(category)


# Internal short name, never carrying payload text.
ParseError = AccountSchemaError


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ParseError("invalid_shape")
    return value


def _required(obj: Mapping[str, Any], *keys: str) -> None:
    if any(key not in obj for key in keys):
        raise ParseError("invalid_shape")


def _string(value: Any, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise ParseError("invalid_type")
    return value


def _number(value: Any, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ParseError("invalid_type")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ParseError("invalid_number")
    if nonnegative and value < 0:
        raise ParseError("negative_value")
    return float(value)


def _numeric_string(value: Any) -> None:
    if not isinstance(value, str) or not value:
        raise ParseError("invalid_type")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ParseError("invalid_number") from None
    if not math.isfinite(parsed):
        raise ParseError("invalid_number")
    if parsed < 0:
        raise ParseError("negative_value")


def _list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ParseError("invalid_type")
    return value


def _record(value: Any) -> Mapping[str, Any]:
    record = _mapping(value)
    if any(not isinstance(key, str) for key in record):
        raise ParseError("invalid_type")
    for item in record.values():
        _number(item, nonnegative=True)
    return record


def _validate_available_position(value: Any) -> None:
    item = _mapping(value)
    _required(item, "instrument", "side", "volume", "initialMargin")
    _string(item["instrument"])
    _string(item["side"])
    _numeric_string(item["volume"])
    _numeric_string(item["initialMargin"])


def _validate_available_order(value: Any) -> None:
    item = _mapping(value)
    _required(item, "instrument", "side", "unFilledVolume", "unFilledInitialMargin")
    _string(item["instrument"])
    _string(item["side"])
    _numeric_string(item["unFilledVolume"])
    _numeric_string(item["unFilledInitialMargin"])


def parse_available_balance(
    payload: Any, coin_list: Any | None = None
) -> dict[str, Any]:
    """Validate the SDK AvailableBalance DTO and return a redacted summary."""
    obj = _mapping(payload)
    _required(
        obj,
        "currency",
        "funding",
        "position",
        "openOrder",
        "availableBalance",
        "updatedAt",
        "openOrders",
        "positions",
    )
    currency = _string(obj["currency"])
    funding = _mapping(obj["funding"])
    _required(funding, "currency", "balance")
    funding_currency = _string(funding["currency"])
    funding_amount = _number(funding["balance"], nonnegative=True)
    positions = _list(obj["position"])
    orders = _list(obj["openOrder"])
    for item in positions:
        _validate_available_position(item)
    for item in orders:
        _validate_available_order(item)
    available_amount = _number(obj["availableBalance"], nonnegative=True)
    _string(obj["updatedAt"])
    open_orders_map = _record(obj["openOrders"])
    positions_map = _record(obj["positions"])
    coin_ids, usdt_ids = {}, set()
    if coin_list is not None:
        _, coin_ids, usdt_ids = _parse_coin_catalog(coin_list)
    return {
        "valid": True,
        "currency_is_usdt": _matches_usdt(currency, coin_ids, usdt_ids),
        "funding_currency_matches": currency == funding_currency,
        "funding_currency_is_usdt": _matches_usdt(funding_currency, coin_ids, usdt_ids),
        "funding_positive": funding_amount > 0,
        "available_positive": available_amount > 0,
        "position_count": len(positions),
        "open_order_count": len(orders),
        "open_orders_map_count": len(open_orders_map),
        "positions_map_count": len(positions_map),
    }


def _parse_bare_list(payload: Any, item_validator: Any) -> dict[str, Any]:
    obj = _mapping(payload)
    _required(obj, "list")
    items = _list(obj["list"])
    for item in items:
        item_validator(item)
    return {"valid": True, "count": len(items)}


def _validate_position(value: Any) -> None:
    item = _mapping(value)
    _required(
        item,
        "id",
        "user",
        "instrument",
        "side",
        "quantity",
        "avgPrice",
        "fundingRate",
        "fee",
        "leverage",
        "maintenanceMargin",
        "createdAt",
        "updatedAt",
        "unRealizedPnL",
        "adlLevel",
    )
    for key in ("id", "user", "instrument", "side", "createdAt", "updatedAt"):
        _string(item[key])
    for key in (
        "quantity",
        "avgPrice",
        "fundingRate",
        "fee",
        "leverage",
        "maintenanceMargin",
        "unRealizedPnL",
        "adlLevel",
    ):
        _number(item[key])


def parse_position_list(payload: Any) -> dict[str, Any]:
    """Validate PositionList (a list-only DTO, not a paginated ListOf)."""
    return _parse_bare_list(payload, _validate_position)


def _validate_order(value: Any) -> None:
    item = _mapping(value)
    required = (
        "id",
        "user",
        "instrument",
        "side",
        "type",
        "quantity",
        "cashQuantity",
        "limitPrice",
        "stopPrice",
        "status",
        "unFilledQuantity",
        "filledAvgPrice",
        "realizedPnL",
        "fee",
        "createdAt",
        "updatedAt",
        "triggeredAt",
        "exchangeRequestId",
        "group",
    )
    _required(item, *required)
    for key in (
        "id",
        "user",
        "instrument",
        "side",
        "type",
        "status",
        "createdAt",
        "updatedAt",
        "exchangeRequestId",
    ):
        _string(item[key])
    for key in (
        "quantity",
        "cashQuantity",
        "limitPrice",
        "unFilledQuantity",
        "filledAvgPrice",
        "realizedPnL",
    ):
        _number(item[key])
    for key in ("stopPrice", "triggeredAt"):
        if item[key] is not None:
            _number(item[key]) if key == "stopPrice" else _string(item[key])
    fee = _list(item["fee"])
    for entry in fee:
        fee_obj = _mapping(entry)
        _required(fee_obj, "coin", "quantity")
        _string(fee_obj["coin"])
        _number(fee_obj["quantity"])
    _string(item["group"])


def _validate_paged_list(payload: Any, item_validator: Any) -> dict[str, Any]:
    obj = _mapping(payload)
    _required(obj, "list", "count")
    items = _list(obj["list"])
    count_value = obj["count"]
    if isinstance(count_value, bool) or not isinstance(count_value, int):
        raise ParseError("invalid_type")
    if count_value < 0:
        raise ParseError("negative_value")
    if count_value != len(items):
        raise ParseError("count_mismatch")
    if "next" in obj and obj["next"] not in (None, ""):
        raise ParseError("pagination_incomplete")
    for item in items:
        item_validator(item)
    return {"valid": True, "count": count_value, "pagination_complete": True}


def parse_order_list(payload: Any) -> dict[str, Any]:
    """Validate OrderList = ListOf<Order>; non-final pages fail closed."""
    return _validate_paged_list(payload, _validate_order)


def parse_opened_orders(payload: Any) -> dict[str, Any]:
    """The GET /api/order/opened endpoint returns OpenedOrder[], not OrderList."""
    items = _list(payload)
    for row in items:
        item = _mapping(row)
        _required(
            item,
            "id",
            "user",
            "instrument",
            "side",
            "type",
            "status",
            "quantity",
            "limitPrice",
            "unFilledQuantity",
            "fee",
            "updatedAt",
            "cashQuantity",
        )
        for key in ("id", "user", "instrument", "side", "type", "status", "updatedAt"):
            _string(item[key])
        for key in ("quantity", "limitPrice", "unFilledQuantity", "cashQuantity"):
            _number(item[key], nonnegative=True)
        for fee in _list(item["fee"]):
            fee_item = _mapping(fee)
            _required(fee_item, "coin", "quantity")
            _string(fee_item["coin"])
            _number(fee_item["quantity"])
    return {"valid": True, "count": len(items)}


def _validate_tpsl(value: Any) -> None:
    item = _mapping(value)
    _required(
        item,
        "id",
        "instrument",
        "type",
        "side",
        "quantity",
        "price",
        "status",
        "triggerOrder",
        "triggeredQuantity",
        "cancelledReason",
        "createdAt",
        "updatedAt",
    )
    for key in (
        "id",
        "instrument",
        "type",
        "side",
        "status",
        "quantity",
        "price",
        "triggeredQuantity",
    ):
        _string(item[key])
    for key in ("quantity", "price", "triggeredQuantity"):
        _numeric_string(item[key])
    _string(item["cancelledReason"], nonempty=False)
    for key in ("createdAt", "updatedAt"):
        # SDK declares Date; JSON transport serializes these as strings.
        _string(item[key])
    if item["triggerOrder"] is not None:
        _string(item["triggerOrder"])


def parse_tpsl_list(payload: Any) -> dict[str, Any]:
    """Validate TpSlList = ListOf<TpSl>; non-final pages fail closed."""
    return _validate_paged_list(payload, _validate_tpsl)


def _parse_coin_catalog(
    payload: Any,
) -> tuple[dict[str, Any], dict[str, str], set[str]]:
    obj = _mapping(payload)
    _required(obj, "list")
    rows = _list(obj["list"])
    ids: dict[str, str] = {}
    usdt_ids: set[str] = set()
    for row_value in rows:
        row = _mapping(row_value)
        _required(row, "id", "name", "symbol")
        coin_id = _string(row["id"])
        _string(row["name"])
        symbol = _string(row["symbol"])
        if coin_id in ids:
            raise ParseError("ambiguous_coin")
        ids[coin_id] = symbol
        if symbol == "USDT":
            usdt_ids.add(coin_id)
        for key in ("image", "createdAt"):
            if key in row:
                _string(row[key], nonempty=False)
        for key in ("precision", "showPrecision", "price"):
            if key in row:
                _number(row[key], nonnegative=True)
    if len(usdt_ids) > 1:
        raise ParseError("ambiguous_coin")
    return (
        {
            "valid": True,
            "coin_count": len(rows),
            "usdt_symbol_count": len(usdt_ids),
            "usdt_id_unique": len(usdt_ids) == 1,
        },
        ids,
        usdt_ids,
    )


def _matches_usdt(currency: str, coin_ids: dict[str, str], usdt_ids: set[str]) -> bool:
    # A catalog ID that contradicts the literal symbol is not guessed away.
    if currency in coin_ids:
        return currency in usdt_ids
    return currency == "USDT"


def parse_wallet_balance_list(payload: Any, coin_list: Any) -> dict[str, Any]:
    """Validate wallet DTOs and identify USDT only by exact public identity.

    A wallet currency is USDT iff it is the literal ``USDT`` or equals the
    unique public coin id whose symbol is exactly ``USDT``. No aliases are
    guessed; unrelated coin rows are accepted but never counted as USDT.
    """
    _, coin_ids, usdt_ids = _parse_coin_catalog(coin_list)
    wallet = _list(payload)
    if len(usdt_ids) > 1:
        raise ParseError("ambiguous_coin")
    seen: set[str] = set()
    usdt_count = 0
    usdt_positive = False
    identified_by_coin_id = False
    for row_value in wallet:
        row = _mapping(row_value)
        _required(row, "currency", "balance", "balanceUSD")
        currency = _string(row["currency"])
        if currency in seen:
            raise ParseError("duplicate_currency")
        seen.add(currency)
        amount = _number(row["balance"], nonnegative=True)
        _number(row["balanceUSD"], nonnegative=True)
        # A known unrelated public coin id is explicitly non-USDT.
        if _matches_usdt(currency, coin_ids, usdt_ids):
            usdt_count += 1
            usdt_positive = amount > 0
            identified_by_coin_id = currency in usdt_ids
    if usdt_count > 1:
        raise ParseError("duplicate_currency")
    return {
        "valid": True,
        "wallet_balance_count": len(wallet),
        "usdt_entry_count": usdt_count,
        "usdt_currency_resolved": usdt_count == 1,
        "usdt_positive": usdt_positive,
        "identified_by_public_coin_id": identified_by_coin_id,
    }


def parse_coin_list(payload: Any) -> dict[str, Any]:
    """Validate the public CoinList; never return coin identifiers."""
    summary, _, _ = _parse_coin_catalog(payload)
    return summary


def reconcile_empty_account(
    available: Any,
    positions: Any,
    opened_orders: Any,
    tpsl: Any,
    wallet_balances: Any,
    coins: Any,
) -> dict[str, Any]:
    """Reconcile one bounded sample; no transport or history claim is made.

    The orchestrator must supply responses from its bounded, consecutive GET
    sequence. This parser cannot prove ordering, atomicity, or freshness.
    """
    available = parse_available_balance(available, coins)
    positions_summary = parse_position_list(positions)
    orders_summary = parse_opened_orders(opened_orders)
    tpsl_summary = parse_tpsl_list(tpsl)
    wallet_summary = parse_wallet_balance_list(wallet_balances, coins)
    usdt_currency_ok = (
        available["currency_is_usdt"]
        and available["funding_currency_is_usdt"]
        and available["funding_currency_matches"]
        and wallet_summary["usdt_currency_resolved"]
    )
    sections_empty = (
        usdt_currency_ok
        and available["position_count"] == 0
        and available["open_order_count"] == 0
        and available["positions_map_count"] == 0
        and available["open_orders_map_count"] == 0
        and positions_summary["count"] == 0
        and orders_summary["count"] == 0
        and tpsl_summary["count"] == 0
    )
    confirmed = sections_empty
    return {
        "valid": True,
        "state": "EMPTY_CONFIRMED_NONTRADING_SAMPLE"
        if confirmed
        else "NONEMPTY_OR_INCONSISTENT",
        "currency_consistent": usdt_currency_ok,
        "sections_empty": sections_empty,
        "sample_scope": "EXACT_EMPTY_CONSISTENT_SERIAL_GET_SAMPLE",
        "non_atomic_sample": True,
        "empty_confirmed": confirmed,
        "full_history_proven": False,
        "available": available,
        "positions": positions_summary,
        "opened_orders": orders_summary,
        "tpsl": tpsl_summary,
        "wallet": wallet_summary,
        "coins": parse_coin_list(coins),
    }
