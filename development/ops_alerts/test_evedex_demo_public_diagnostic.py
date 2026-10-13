"""Offline contracts for the bounded public EVEDEX DEMO diagnostic."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).with_name("evedex_demo_public_diagnostic.py")
SPEC = importlib.util.spec_from_file_location(
    "evedex_demo_diagnostic_under_test", SOURCE
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

NOW = dt.datetime(2026, 10, 13, 12, 0, tzinfo=dt.UTC)


def _response(payload, *, captured_at=NOW, status=200):
    return MODULE.Response(
        json.dumps(payload, allow_nan=False).encode(), captured_at, status, 1.0
    )


def _instrument(symbol):
    return {"name": symbol, "trading": "all", "visibility": "all"}


def _book(*, bids=None, asks=None, timestamp=None):
    return {
        "bids": bids if bids is not None else [{"price": "99.9", "quantity": "1"}],
        "asks": asks if asks is not None else [{"price": "100.1", "quantity": "1"}],
        "t": timestamp if timestamp is not None else int(NOW.timestamp() * 1000),
    }


def _trades(symbol, *, timestamp=None, identity="exec-1"):
    return [
        {
            "instrument": symbol,
            "executionId": identity,
            "id": "not-the-identity",
            "fillPrice": "0.000001",
            "fillQuantity": "10",
            "createdAt": (timestamp or NOW).isoformat(),
        }
    ]


class DemoPublicDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payloads = {
            "/api/market": {"state": "active"},
            "/api/market/instrument": [_instrument(s) for s in MODULE.SYMBOLS],
        }
        for symbol in MODULE.SYMBOLS:
            self.payloads[f"/api/market/{symbol}/deep"] = _book()
            self.payloads[f"/api/market/{symbol}/deep?marketLevel=1"] = _book()
            self.payloads[f"/api/market/{symbol}/recent-trades"] = _trades(symbol)
        self.calls = []

    def fetch(self, path):
        self.calls.append(path)
        return _response(self.payloads[path])

    def run_probe(self, **kwargs):
        return MODULE.probe(
            self.root,
            source_hash="a" * 64,
            source_revision="b" * 40,
            fetcher=self.fetch,
            **kwargs,
        )

    def test_exact_eleven_get_roster_and_dev_gate_unchanged(self):
        self.assertEqual(MODULE.ORIGIN, "https://trading-api.evedex.io")
        self.assertEqual(
            MODULE.SYMBOLS, ("BTCUSD:DEMO", "ETHUSD:DEMO", "1000PEPEUSD:DEMO")
        )
        self.assertEqual(
            MODULE.KAIROS_REQUIRED_DEV_SYMBOLS,
            ("BTCUSD:DEV", "ETHUSD:DEV", "SOLUSD:DEV", "BNBUSD:DEV", "XRPUSD:DEV"),
        )
        self.assertEqual(len(MODULE.ENDPOINTS), MODULE.MAX_CALLS)
        self.assertEqual(len(MODULE.PATHS), MODULE.MAX_CALLS)
        self.assertEqual(MODULE.ENDPOINTS[0].path, "/api/market")
        self.assertEqual(MODULE.ENDPOINTS[1].path, "/api/market/instrument")
        for symbol in MODULE.SYMBOLS:
            self.assertEqual(
                [row.path for row in MODULE.ENDPOINTS if row.symbol == symbol],
                [
                    f"/api/market/{symbol}/deep",
                    f"/api/market/{symbol}/deep?marketLevel=1",
                    f"/api/market/{symbol}/recent-trades",
                ],
            )
        self.assertTrue(
            all(
                MODULE.request_url(path) == MODULE.ORIGIN + path
                for path in MODULE.PATHS
            )
        )
        for unsafe in (
            "/api/user/me",
            "/api/order/opened",
            "/api/market/BTCUSD:DEV/deep",
            "/api/market/ETHUSD:DEMO/deep?x=1",
            "https://evil.invalid/",
        ):
            with self.subTest(path=unsafe), self.assertRaises(MODULE.DiagnosticError):
                MODULE.request_url(unsafe)

    def test_plan_only_is_zero_network_and_reports_boundaries(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(MODULE.main([]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "PLAN_ONLY")
        self.assertEqual(result["http_calls"], 0)
        self.assertEqual(result["symbols"], list(MODULE.SYMBOLS))
        self.assertFalse(result["authenticated"])
        self.assertFalse(result["credentials_read"])
        self.assertFalse(result["market_liquidity_qualified"])
        self.assertFalse(result["paper_qualified"])
        self.assertFalse(result["alpha_ready"])
        self.assertFalse(result["live_ready"])
        self.assertFalse(result["trading_authority"])
        self.assertEqual(self.calls, [])

    def test_transport_is_single_anonymous_get_no_proxy_tls_and_no_redirect(self):
        request_seen = []

        class FakeReply:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def geturl(self):
                return MODULE.ORIGIN + MODULE.ENDPOINTS[0].path

            def read(self, size):
                self.read_size = size
                return b'{"state":"active"}'

        class FakeOpener:
            def open(self, request, timeout):
                request_seen.append((request, timeout))
                return FakeReply()

        with mock.patch.object(
            MODULE.urllib.request, "build_opener", return_value=FakeOpener()
        ) as build:
            response = MODULE.http_get(MODULE.ENDPOINTS[0].path)
        request, timeout = request_seen[0]
        self.assertEqual(len(request_seen), 1)
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.full_url, MODULE.ORIGIN + MODULE.ENDPOINTS[0].path)
        self.assertEqual(dict(request.header_items()), {"Accept": "application/json"})
        self.assertEqual(timeout, MODULE.TIMEOUT_SECONDS)
        self.assertEqual(response.http_status, 200)
        handlers = list(build.call_args.args)
        self.assertTrue(
            any(
                isinstance(handler, MODULE.urllib.request.ProxyHandler)
                for handler in handlers
            )
        )
        self.assertTrue(
            any(isinstance(handler, MODULE.NoRedirect) for handler in handlers)
        )
        tls = [
            handler
            for handler in handlers
            if isinstance(handler, MODULE.urllib.request.HTTPSHandler)
        ]
        self.assertEqual(len(tls), 1)
        self.assertEqual(tls[0]._context.verify_mode, 2)
        self.assertTrue(tls[0]._context.check_hostname)

    def test_http_get_redirect_and_transport_errors_are_terminal(self):
        class RedirectOpener:
            def open(self, *_args, **_kwargs):
                raise MODULE.urllib.error.HTTPError(
                    "url", 302, "redirect", {}, io.BytesIO()
                )

        class BrokenOpener:
            def open(self, *_args, **_kwargs):
                raise OSError("sensitive text must not escape")

        with (
            mock.patch.object(
                MODULE.urllib.request, "build_opener", return_value=RedirectOpener()
            ),
            self.assertRaisesRegex(MODULE.DiagnosticError, "REDIRECT_BLOCKED"),
        ):
            MODULE.http_get(MODULE.ENDPOINTS[0].path)
        broken = BrokenOpener()
        with (
            mock.patch.object(
                MODULE.urllib.request, "build_opener", return_value=broken
            ),
            self.assertRaisesRegex(
                MODULE.DiagnosticError, "TRANSPORT_UNKNOWN_NO_RETRY"
            ),
        ):
            MODULE.http_get(MODULE.ENDPOINTS[0].path)
        self.assertEqual(len(self.calls), 0)

    def test_response_byte_cap_and_duplicate_or_malformed_json(self):
        with self.assertRaisesRegex(MODULE.DiagnosticError, "RESPONSE_TOO_LARGE"):
            MODULE.parse_json(b" " * (MODULE.MAX_BODY_BYTES + 1))
        with self.assertRaisesRegex(MODULE.DiagnosticError, "DUPLICATE_JSON_KEY"):
            MODULE.parse_json(b'{"x":1,"x":2}')
        for invalid in (b"not-json", b'{"x":NaN}', b"\xff"):
            with (
                self.subTest(payload=invalid),
                self.assertRaisesRegex(MODULE.DiagnosticError, "JSON_INVALID"),
            ):
                MODULE.parse_json(invalid)

    def test_books_use_bid_ask_extrema_and_accept_tiny_pepe_prices(self):
        result = MODULE.inspect_book(
            _book(
                bids=[
                    {"price": "0.000002", "quantity": "100"},
                    {"price": "0.000003", "quantity": "50"},
                ],
                asks=[
                    {"price": "0.000005", "quantity": "40"},
                    {"price": "0.000004", "quantity": "60"},
                ],
            ),
            NOW,
        )
        self.assertEqual(result["state"], "TWO_SIDED_BOOK")
        self.assertEqual(result["best_bid"], 0.000003)
        self.assertEqual(result["best_ask"], 0.000004)
        self.assertEqual(result["freshness"], "FRESH")

    def test_empty_one_sided_crossed_future_and_stale_books(self):
        cases = [
            (_book(bids=[], asks=[]), "EMPTY_BOOK"),
            (_book(bids=[], asks=[{"price": 1, "quantity": 1}]), "ONE_SIDED_BOOK"),
            (
                _book(
                    bids=[{"price": 2, "quantity": 1}],
                    asks=[{"price": 1, "quantity": 1}],
                ),
                "CROSSED_BOOK",
            ),
            (_book(timestamp=int((NOW.timestamp() + 3) * 1000)), "TWO_SIDED_BOOK"),
            (_book(timestamp=int((NOW.timestamp() - 6) * 1000)), "TWO_SIDED_BOOK"),
        ]
        for payload, state in cases:
            with self.subTest(state=state, timestamp=payload["t"]):
                result = MODULE.inspect_book(payload, NOW)
                self.assertEqual(result["state"], state)
        self.assertEqual(MODULE.inspect_book(cases[3][0], NOW)["freshness"], "FUTURE")
        self.assertEqual(MODULE.inspect_book(cases[4][0], NOW)["freshness"], "STALE")

    def test_instruments_reject_malformed_and_duplicate_identity(self):
        with self.assertRaises(MODULE.DiagnosticError):
            MODULE.inspect_instruments({"list": []})
        with self.assertRaises(MODULE.DiagnosticError):
            MODULE.inspect_instruments([_instrument(MODULE.SYMBOLS[0]), {"name": 1}])
        with self.assertRaises(MODULE.DiagnosticError):
            MODULE.inspect_instruments(
                [_instrument(MODULE.SYMBOLS[0]), _instrument(MODULE.SYMBOLS[0])]
            )
        self.assertFalse(MODULE.inspect_instruments([])[MODULE.SYMBOLS[0]]["present"])

    def test_trades_require_execution_id_exact_instrument_and_aware_timestamp(self):
        valid = _trades(MODULE.SYMBOLS[0])
        self.assertEqual(
            MODULE.inspect_trades(valid, MODULE.SYMBOLS[0], NOW)["state"],
            "TRADES_OBSERVED",
        )
        old_id_only = [dict(valid[0])]
        old_id_only[0].pop("executionId")
        for rows in (
            old_id_only,
            [{**valid[0], "executionId": "", "id": "exec-1"}],
            [{**valid[0], "instrument": MODULE.SYMBOLS[1]}],
            [{**valid[0], "createdAt": "2026-10-13T12:00:00"}],
            [{**valid[0], "createdAt": "not-a-time"}],
            [valid[0], dict(valid[0])],
        ):
            with self.subTest(rows=rows), self.assertRaises(MODULE.DiagnosticError):
                MODULE.inspect_trades(rows, MODULE.SYMBOLS[0], NOW)
        self.assertEqual(
            MODULE.inspect_trades([], MODULE.SYMBOLS[0], NOW)["state"],
            "NO_RECENT_TRADES",
        )
        stale = _trades(MODULE.SYMBOLS[0], timestamp=NOW - dt.timedelta(seconds=301))
        future = _trades(MODULE.SYMBOLS[0], timestamp=NOW + dt.timedelta(seconds=3))
        self.assertEqual(
            MODULE.inspect_trades(stale, MODULE.SYMBOLS[0], NOW)["freshness"], "STALE"
        )
        self.assertEqual(
            MODULE.inspect_trades(future, MODULE.SYMBOLS[0], NOW)["freshness"], "FUTURE"
        )

    def test_probe_reserves_each_request_before_fetch_and_all_boundaries_stay_false(
        self,
    ):
        events = []

        def writer(path, value):
            path.write_text(json.dumps(value), encoding="utf-8")
            events.append("write:" + path.name)

        def fetcher(path):
            events.append("fetch:" + path)
            self.calls.append(path)
            return _response(self.payloads[path])

        report = MODULE.probe(
            self.root,
            source_hash="a" * 64,
            source_revision="b" * 40,
            fetcher=fetcher,
            writer=writer,
            source_check=lambda: None,
        )
        self.assertEqual(len(self.calls), 11)
        self.assertEqual(set(self.calls), MODULE.PATHS)
        for index, endpoint in enumerate(MODULE.ENDPOINTS, 1):
            reservation = events.index(f"write:request-{index:02d}.reserved.json")
            request = events.index("fetch:" + endpoint.path)
            self.assertLess(reservation, request)
        self.assertEqual(report["status"], "DIAGNOSTIC_RECORDED_NOT_QUALIFIED")
        self.assertEqual(report["http_calls"], 11)
        self.assertEqual(
            report["unchanged_kairos_required_dev_symbols"],
            list(MODULE.KAIROS_REQUIRED_DEV_SYMBOLS),
        )
        for key in (
            "authenticated",
            "credentials_read",
            "dev_configuration_changed",
            "primary_or_queue_changed",
            "sample_is_24h_evidence",
            "market_liquidity_qualified",
            "economic_validation",
            "paper_qualified",
            "alpha_ready",
            "live_ready",
            "trading_authority",
        ):
            self.assertFalse(report[key], key)
        self.assertEqual(report["strategy_policy"], "REJECT_ALL")

    def test_empty_eth_depth_does_not_abort_remaining_public_diagnosis(self):
        path = f"/api/market/{MODULE.SYMBOLS[1]}/deep?marketLevel=1"
        self.payloads[path] = _book(bids=[], asks=[])
        report = self.run_probe()
        eth = next(row for row in report["requests"] if row.get("path") == path)
        self.assertEqual(eth["observation"]["state"], "EMPTY_BOOK")
        self.assertEqual(len(self.calls), 11)
        self.assertEqual(report["http_calls"], 11)
        self.assertEqual(report["status"], "DIAGNOSTIC_RECORDED_NOT_QUALIFIED")

    def test_source_drift_or_reservation_write_failure_stops_before_next_fetch(self):
        checks = [0]

        def changing_source():
            checks[0] += 1
            if checks[0] == 2:
                raise MODULE.DiagnosticError("SOURCE_CHANGED")

        with self.assertRaises(MODULE.DiagnosticError):
            MODULE.probe(
                self.root,
                source_hash="a" * 64,
                source_revision="b" * 40,
                fetcher=self.fetch,
                source_check=changing_source,
            )
        self.assertEqual(self.calls, [MODULE.ENDPOINTS[0].path])
        self.calls.clear()

        def broken_writer(_path, _value):
            raise OSError("private path detail")

        with self.assertRaises(OSError):
            MODULE.probe(
                self.root,
                source_hash="a" * 64,
                source_revision="b" * 40,
                fetcher=self.fetch,
                writer=broken_writer,
            )
        self.assertEqual(self.calls, [])

    def test_transport_and_schema_failures_are_sanitized_and_do_not_abort_roster(self):
        path = MODULE.ENDPOINTS[0].path

        def bad_fetch(candidate):
            self.calls.append(candidate)
            if candidate == path:
                raise MODULE.DiagnosticError("TRANSPORT_UNKNOWN_NO_RETRY")
            return _response(self.payloads[candidate])

        report = MODULE.probe(
            self.root, source_hash="a" * 64, source_revision="b" * 40, fetcher=bad_fetch
        )
        first = report["requests"][0]
        self.assertEqual(first["state"], "UNVERIFIED")
        self.assertEqual(first["error_category"], "TRANSPORT_UNKNOWN_NO_RETRY")
        self.assertNotIn("secret.example", json.dumps(report))
        self.assertEqual(len(self.calls), 11)

    def test_daily_reservation_refuses_duplicate_run_without_probe(self):
        evidence = self.root / "evidence"
        evidence.mkdir()
        with (
            mock.patch.object(MODULE, "EVIDENCE_ROOT", evidence),
            mock.patch.object(
                MODULE, "verify_source", return_value=("a" * 64, "b" * 40)
            ),
            mock.patch.object(MODULE, "_no_reparse", return_value=None),
            mock.patch.object(MODULE, "probe", return_value={"status": "ok"}) as probe,
        ):
            self.assertEqual(MODULE.run(authorize=True)["status"], "ok")
            with self.assertRaisesRegex(
                MODULE.DiagnosticError, "DAY_ALREADY_RESERVED_NO_RETRY"
            ):
                MODULE.run(authorize=True)
            probe.assert_called_once()

    def test_verify_source_accepts_exact_trusted_signed_clean_main_source(self):
        revision = "a" * 40
        content = b"committed source bytes\n"
        outputs = {
            (
                "show",
                "-s",
                "--format=%H %G? %GF",
                "HEAD",
            ): f"{revision} G {MODULE.SIGNER}\n",
            ("branch", "--show-current"): "main\n",
            ("rev-parse", "origin/main"): revision + "\n",
            ("status", "--porcelain", "--", MODULE.SOURCE_RELATIVE): "",
            ("show", f"HEAD:{MODULE.SOURCE_RELATIVE}"): content,
        }

        def git(*args, binary=False):
            value = outputs[args]
            self.assertEqual(binary, args[0] == "show" and args[-1].startswith("HEAD:"))
            return value

        with (
            mock.patch.object(MODULE, "_git", side_effect=git),
            mock.patch.object(MODULE, "_source_bytes", return_value=content),
        ):
            source_hash, source_revision = MODULE.verify_source()
        self.assertEqual(source_hash, hashlib.sha256(content).hexdigest())
        self.assertEqual(source_revision, revision)

    def test_verify_source_rejects_signature_branch_origin_dirty_and_byte_drift(self):
        revision = "c" * 40
        content = b"committed source bytes\n"
        valid_record = f"{revision} G {MODULE.SIGNER}\n"
        base = {
            ("show", "-s", "--format=%H %G? %GF", "HEAD"): valid_record,
            ("branch", "--show-current"): "main\n",
            ("rev-parse", "origin/main"): revision + "\n",
            ("status", "--porcelain", "--", MODULE.SOURCE_RELATIVE): "",
            ("show", f"HEAD:{MODULE.SOURCE_RELATIVE}"): content,
        }
        failures = {
            "unsigned": ("show", "-s", "--format=%H %G? %GF", "HEAD"),
            "wrong_signer": ("show", "-s", "--format=%H %G? %GF", "HEAD"),
            "branch_drift": ("branch", "--show-current"),
            "origin_drift": ("rev-parse", "origin/main"),
            "dirty_scoped_source": (
                "status",
                "--porcelain",
                "--",
                MODULE.SOURCE_RELATIVE,
            ),
        }
        replacements = {
            "unsigned": f"{revision} N {MODULE.SIGNER}\n",
            "wrong_signer": f"{revision} G {'F' * 40}\n",
            "branch_drift": "feature\n",
            "origin_drift": "d" * 40 + "\n",
            "dirty_scoped_source": f" M {MODULE.SOURCE_RELATIVE}\n",
        }
        for label, key in failures.items():
            with self.subTest(case=label):
                outputs = dict(base)
                outputs[key] = replacements[label]

                def git(*args, binary=False, _outputs=outputs):
                    return _outputs[args]

                with (
                    mock.patch.object(MODULE, "_git", side_effect=git),
                    mock.patch.object(MODULE, "_source_bytes", return_value=content),
                    self.assertRaisesRegex(
                        MODULE.DiagnosticError, "SOURCE_NOT_ADMITTED"
                    ),
                ):
                    MODULE.verify_source()

        with (
            mock.patch.object(
                MODULE, "_git", side_effect=lambda *args, **kwargs: base[args]
            ),
            mock.patch.object(
                MODULE, "_source_bytes", return_value=b"working bytes differ\n"
            ),
            self.assertRaisesRegex(MODULE.DiagnosticError, "SOURCE_NOT_ADMITTED"),
        ):
            MODULE.verify_source()

    def test_missing_authorization_precedes_source_verification_and_directory_or_fetch(
        self,
    ):
        evidence = self.root / "evidence"
        with (
            mock.patch.object(MODULE, "EVIDENCE_ROOT", evidence),
            mock.patch.object(MODULE, "verify_source") as verify,
            mock.patch.object(MODULE, "probe") as probe,
            self.assertRaisesRegex(MODULE.DiagnosticError, "AUTHORIZATION_REQUIRED"),
        ):
            MODULE.run(authorize=False)
        verify.assert_not_called()
        probe.assert_not_called()
        self.assertFalse(evidence.exists())
        self.assertEqual(self.calls, [])

    def test_raw_local_failure_is_retained_and_second_run_does_not_retry(self):
        evidence = self.root / "evidence"
        evidence.mkdir()
        with (
            mock.patch.object(MODULE, "EVIDENCE_ROOT", evidence),
            mock.patch.object(
                MODULE, "verify_source", return_value=("e" * 64, "f" * 40)
            ),
            mock.patch.object(MODULE, "_no_reparse", return_value=None),
            mock.patch.object(
                MODULE, "probe", side_effect=OSError("private local detail")
            ) as probe,
        ):
            with self.assertRaisesRegex(
                MODULE.DiagnosticError, "FAILED_CLOSED_NO_RETRY"
            ):
                MODULE.run(authorize=True)
            run_dirs = list(evidence.iterdir())
            self.assertEqual(len(run_dirs), 1)
            failure = json.loads(
                (run_dirs[0] / "failure.json").read_text(encoding="utf-8")
            )
            self.assertEqual(failure["status"], "FAILED_CLOSED_NO_RETRY")
            self.assertNotIn("private local detail", json.dumps(failure))
            with self.assertRaisesRegex(
                MODULE.DiagnosticError, "DAY_ALREADY_RESERVED_NO_RETRY"
            ):
                MODULE.run(authorize=True)
            probe.assert_called_once()


if __name__ == "__main__":
    unittest.main()
