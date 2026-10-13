"""Offline contracts for the EVEDEX DEMO account response parsers."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("evedex_demo_account_reconciliation.py")
SPEC = importlib.util.spec_from_file_location(
    "evedex_demo_account_reconciliation_under_test", SOURCE
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _available(**overrides):
    value = {
        "currency": "USDT",
        "funding": {"currency": "USDT", "balance": 0.0},
        "position": [],
        "openOrder": [],
        "availableBalance": 0.0,
        "updatedAt": "2026-10-13T12:00:00.000Z",
        "openOrders": {},
        "positions": {},
    }
    value.update(overrides)
    return value


def _coins():
    return {
        "list": [
            {"id": "coin-secret-marker", "name": "Tether", "symbol": "USDT"},
            {"id": "other-coin-marker", "name": "Other", "symbol": "OTHER"},
        ]
    }


def _wallet(currency="coin-secret-marker", **overrides):
    row = {"currency": currency, "balance": 12.5, "balanceUSD": 12.5}
    row.update(overrides)
    return [row]


def _order():
    return {
        "id": "private-order-id",
        "user": "private-user",
        "instrument": "private-instrument",
        "side": "buy",
        "type": "limit",
        "quantity": 1,
        "cashQuantity": 1,
        "limitPrice": 1,
        "stopPrice": None,
        "status": "open",
        "unFilledQuantity": 1,
        "filledAvgPrice": 0,
        "realizedPnL": 0,
        "fee": [],
        "createdAt": "then",
        "updatedAt": "then",
        "triggeredAt": None,
        "exchangeRequestId": "private-request-id",
        "group": "normal",
    }


def _tpsl():
    return {
        "id": "private-tpsl-id",
        "instrument": "private-instrument",
        "type": "take-profit",
        "side": "sell",
        "quantity": "1",
        "price": "1",
        "status": "active",
        "triggerOrder": None,
        "triggeredQuantity": "0",
        "cancelledReason": "",
        "createdAt": "then",
        "updatedAt": "then",
    }


def _empty_args(**overrides):
    args = {
        "available": _available(),
        "positions": {"list": []},
        "opened_orders": [],
        "tpsl": {"list": [], "count": 0},
        "wallet_balances": _wallet(),
        "coins": _coins(),
    }
    args.update(overrides)
    return args


class DemoAccountParserTests(unittest.TestCase):
    def assertCategory(self, category, function, *args, **kwargs):
        with self.assertRaises(MODULE.AccountSchemaError) as raised:
            function(*args, **kwargs)
        self.assertEqual(str(raised.exception), category)
        self.assertEqual(raised.exception.category, category)

    def test_empty_serial_get_sample_is_only_a_bounded_non_atomic_claim(self):
        result = MODULE.reconcile_empty_account(**_empty_args())
        self.assertEqual(result["state"], "EMPTY_CONFIRMED_NONTRADING_SAMPLE")
        self.assertTrue(result["empty_confirmed"])
        self.assertEqual(
            result["sample_scope"], "EXACT_EMPTY_CONSISTENT_SERIAL_GET_SAMPLE"
        )
        self.assertTrue(result["non_atomic_sample"])
        self.assertFalse(result["full_history_proven"])

    def test_available_balance_requires_expected_fields_and_exact_currency(self):
        summary = MODULE.parse_available_balance(_available())
        self.assertTrue(summary["currency_is_usdt"])
        self.assertTrue(summary["funding_currency_matches"])
        mismatch = _available(currency="USD", funding={"currency": "USD", "balance": 0})
        result = MODULE.reconcile_empty_account(**_empty_args(available=mismatch))
        self.assertFalse(result["empty_confirmed"])
        self.assertFalse(result["currency_consistent"])
        self.assertNotIn("USD", repr(result))
        self.assertCategory(
            "invalid_shape", MODULE.parse_available_balance, {"currency": "USDT"}
        )

    def test_list_dtos_and_pagination_contracts(self):
        self.assertEqual(MODULE.parse_position_list({"list": []})["count"], 0)
        self.assertEqual(MODULE.parse_order_list({"list": [], "count": 0})["count"], 0)
        self.assertEqual(MODULE.parse_tpsl_list({"list": [], "count": 0})["count"], 0)
        self.assertEqual(MODULE.parse_opened_orders([])["count"], 0)
        self.assertCategory(
            "invalid_type", MODULE.parse_opened_orders, {"list": [], "count": 0}
        )
        self.assertCategory(
            "count_mismatch", MODULE.parse_order_list, {"list": [], "count": 1}
        )
        self.assertCategory(
            "pagination_incomplete",
            MODULE.parse_tpsl_list,
            {"list": [], "count": 0, "next": "opaque-marker"},
        )
        self.assertCategory("invalid_shape", MODULE.parse_position_list, [])

    def test_count_zero_with_nonempty_list_never_confirms_empty(self):
        self.assertCategory(
            "count_mismatch",
            MODULE.parse_order_list,
            {"list": [{"private-marker": "x"}], "count": 0},
        )
        result = MODULE.reconcile_empty_account(**_empty_args(opened_orders=[_order()]))
        self.assertFalse(result["empty_confirmed"])
        self.assertEqual(result["state"], "NONEMPTY_OR_INCONSISTENT")

    def test_available_lists_and_reservation_maps_must_agree(self):
        for override in (
            {
                "position": [
                    {
                        "instrument": "id-marker",
                        "side": "long",
                        "volume": "1",
                        "initialMargin": "1",
                    }
                ]
            },
            {
                "openOrder": [
                    {
                        "instrument": "id-marker",
                        "side": "buy",
                        "unFilledVolume": "1",
                        "unFilledInitialMargin": "1",
                    }
                ]
            },
            {"positions": {"id-marker": 1}},
            {"openOrders": {"id-marker": 1}},
        ):
            with self.subTest(field=next(iter(override))):
                result = MODULE.reconcile_empty_account(
                    **_empty_args(available=_available(**override))
                )
                self.assertFalse(result["empty_confirmed"])
        self.assertCategory(
            "invalid_shape",
            MODULE.parse_available_balance,
            _available(openOrders=[]),
        )

    def test_wallet_usdt_exact_literal_or_unique_public_coin_id_only(self):
        literal = MODULE.parse_wallet_balance_list(_wallet("USDT"), _coins())
        by_id = MODULE.parse_wallet_balance_list(
            _wallet("coin-secret-marker"), _coins()
        )
        unrelated = MODULE.parse_wallet_balance_list(
            _wallet("other-coin-marker"), _coins()
        )
        opaque = MODULE.parse_wallet_balance_list(_wallet("USD"), _coins())
        self.assertEqual(literal["usdt_entry_count"], 1)
        self.assertEqual(by_id["usdt_entry_count"], 1)
        self.assertEqual(unrelated["usdt_entry_count"], 0)
        self.assertEqual(opaque["usdt_entry_count"], 0)
        self.assertFalse(opaque["usdt_currency_resolved"])
        # USD is never rewritten to USDT; ignored mappings cannot prove a target currency.
        # USD stays unmatched; it is not rewritten or counted as the USDT row.
        self.assertEqual(opaque["usdt_entry_count"], 0)
        self.assertTrue(by_id["usdt_positive"])
        self.assertTrue(by_id["identified_by_public_coin_id"])
        result = MODULE.reconcile_empty_account(
            **_empty_args(wallet_balances=_wallet("USD"))
        )
        self.assertFalse(result["empty_confirmed"])

    def test_available_balance_coin_ids_are_resolved_without_symbol_aliases(self):
        mapped = _available(
            currency="coin-secret-marker",
            funding={"currency": "coin-secret-marker", "balance": 0},
        )
        result = MODULE.reconcile_empty_account(**_empty_args(available=mapped))
        self.assertTrue(result["currency_consistent"])
        self.assertTrue(result["empty_confirmed"])

    def test_negative_reservations_and_catalog_contradictions_fail_closed(self):
        self.assertCategory(
            "negative_value",
            MODULE.parse_available_balance,
            _available(positions={"opaque": -1}),
        )
        contradictory = {"list": [{"id": "USDT", "name": "Other", "symbol": "OTHER"}]}
        result = MODULE.reconcile_empty_account(
            **_empty_args(coins=contradictory, wallet_balances=_wallet("USDT"))
        )
        self.assertFalse(result["currency_consistent"])

    def test_duplicate_coin_ids_and_ambiguous_usdt_symbols_fail_closed(self):
        duplicate_id = {
            "list": [
                {"id": "same", "name": "One", "symbol": "ONE"},
                {"id": "same", "name": "Two", "symbol": "TWO"},
            ]
        }
        self.assertCategory("ambiguous_coin", MODULE.parse_coin_list, duplicate_id)
        ambiguous_usdt = {
            "list": [
                {"id": "u1", "name": "One", "symbol": "USDT"},
                {"id": "u2", "name": "Two", "symbol": "USDT"},
            ]
        }
        self.assertCategory(
            "ambiguous_coin",
            MODULE.parse_wallet_balance_list,
            _wallet("USDT"),
            ambiguous_usdt,
        )

    def test_boolean_nan_infinity_wrong_types_and_negative_values_rejected(self):
        for value in (True, float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=repr(value)):
                expected = (
                    "invalid_type" if isinstance(value, bool) else "invalid_number"
                )
                self.assertCategory(
                    expected,
                    MODULE.parse_available_balance,
                    _available(availableBalance=value),
                )
                self.assertCategory(
                    expected,
                    MODULE.parse_wallet_balance_list,
                    _wallet(balance=value),
                    _coins(),
                )
        self.assertCategory(
            "invalid_number",
            MODULE.parse_available_balance,
            _available(availableBalance=10**10000),
        )
        self.assertCategory(
            "negative_value",
            MODULE.parse_available_balance,
            _available(funding={"currency": "USDT", "balance": -0.1}),
        )
        self.assertCategory(
            "negative_value",
            MODULE.parse_wallet_balance_list,
            _wallet(balance=-1),
            _coins(),
        )
        self.assertCategory(
            "negative_value", MODULE.parse_order_list, {"list": [], "count": -1}
        )

    def test_wallet_duplicates_and_missing_coin_schema_fail_closed(self):
        self.assertCategory(
            "duplicate_currency",
            MODULE.parse_wallet_balance_list,
            [_wallet("USDT")[0], _wallet("USDT")[0]],
            _coins(),
        )
        self.assertCategory(
            "invalid_shape",
            MODULE.parse_coin_list,
            {"list": [{"id": "x", "symbol": "USDT"}]},
        )
        self.assertCategory(
            "invalid_type",
            MODULE.parse_wallet_balance_list,
            {"currency": "USDT"},
            _coins(),
        )

    def test_nonempty_position_or_tpsl_prevents_empty_confirmation(self):
        position = {
            "id": "private-id",
            "user": "private-user",
            "instrument": "private-instrument",
            "side": "long",
            "quantity": 1,
            "avgPrice": 1,
            "fundingRate": 0,
            "fee": 0,
            "leverage": 1,
            "maintenanceMargin": 1,
            "createdAt": "then",
            "updatedAt": "then",
            "unRealizedPnL": 0,
            "adlLevel": 0,
        }
        result = MODULE.reconcile_empty_account(
            **_empty_args(positions={"list": [position]})
        )
        self.assertFalse(result["empty_confirmed"])
        self.assertEqual(result["state"], "NONEMPTY_OR_INCONSISTENT")
        result = MODULE.reconcile_empty_account(
            **_empty_args(tpsl={"list": [_tpsl()], "count": 1})
        )
        self.assertFalse(result["empty_confirmed"])

    def test_output_and_errors_never_echo_payload_identifiers_or_amounts(self):
        output = repr(MODULE.reconcile_empty_account(**_empty_args()))
        for marker in ("coin-secret-marker", "other-coin-marker", "12.5", "2026-10-13"):
            self.assertNotIn(marker, output)
        private_marker = "raw-account-secret-marker"
        with self.assertRaises(MODULE.AccountSchemaError) as raised:
            MODULE.parse_available_balance({"currency": private_marker})
        rendered_error = f"{raised.exception} {raised.exception.category}"
        self.assertNotIn(private_marker, rendered_error)
        self.assertNotIn("12.5", rendered_error)


if __name__ == "__main__":
    unittest.main()
