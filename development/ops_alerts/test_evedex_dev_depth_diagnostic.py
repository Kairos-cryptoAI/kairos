"""Offline safety and schema tests for the one-shot EVEDEX depth diagnostic."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SOURCE = Path(__file__).with_name("evedex_dev_depth_diagnostic.py")
SPEC = importlib.util.spec_from_file_location("depth_diagnostic_under_test", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


NOW = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)


class Delivery:
    @staticmethod
    def _no_reparse(_path):
        return None

    @staticmethod
    def _private_acl(_path):
        return None


class Continuation:
    @staticmethod
    def _exclusive_fsync(path, payload):
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()

    @staticmethod
    def _set_exact_file_acl(_path):
        return None


def _instrument(symbol):
    return {
        "name": symbol,
        "trading": "all",
        "visibility": "all",
        "lastPrice": 0,
        "markPrice": 100.0,
        "minQuantity": 0.1,
        "maxQuantity": 1000,
        "quantityIncrement": 0.1,
        "priceIncrement": 0.1,
    }


def _book():
    return {
        "bids": [{"price": "99.9", "quantity": "1.2"}],
        "asks": [{"price": "100.1", "quantity": "2.3"}],
        "t": str(int(NOW.timestamp() * 1000)),
    }


def _response(payload, *, status=200, error=None):
    return MODULE.PublicResponse(status, 1.0, json.dumps(payload).encode(), NOW, error)


class DepthDiagnosticTests(unittest.TestCase):
    def test_exact_allowlist_and_request_bound(self):
        self.assertEqual(len(MODULE.ENDPOINTS), 17)
        self.assertEqual(len({row.path for row in MODULE.ENDPOINTS}), 17)
        self.assertEqual(MODULE.ENDPOINTS[0].path, "/api/market")
        self.assertEqual(MODULE.ENDPOINTS[1].path, "/api/market/instrument")
        for symbol in MODULE.SYMBOLS:
            paths = [row.path for row in MODULE.ENDPOINTS if row.symbol == symbol]
            self.assertEqual(
                paths,
                [
                    f"/api/market/{symbol}/deep",
                    f"/api/market/{symbol}/deep?marketLevel=1",
                    f"/api/market/{symbol}/deep?roundPrice=0.1&maxLevel=30",
                ],
            )
        self.assertEqual(
            MODULE._request_url(MODULE.ENDPOINTS[2].path),
            MODULE.ORIGIN + MODULE.ENDPOINTS[2].path,
        )
        for candidate in (
            "https://evil.invalid/x",
            "/api/market/BTCUSD:DEV/deep?x=1",
            MODULE.ENDPOINTS[2].path + "#frag",
        ):
            with self.assertRaises(MODULE.DiagnosticError):
                MODULE._request_url(candidate)

    def test_http_is_anonymous_get_strict_tls_no_redirect_proxy_or_retry(self):
        response = SimpleNamespace(
            status=200,
            headers={"Content-Length": "2"},
            geturl=lambda: MODULE.ORIGIN + MODULE.ENDPOINTS[0].path,
            read=lambda _limit: b"{}",
            close=lambda: None,
        )
        opener = SimpleNamespace(
            open=lambda request, timeout: (
                self.assertEqual(request.method, "GET"),
                self.assertNotIn("Authorization", request.headers),
                self.assertEqual(timeout, 15),
                response,
            )[-1]
        )
        with patch.object(
            MODULE.urllib.request, "build_opener", return_value=opener
        ) as build:
            result = MODULE._http_get(MODULE.ENDPOINTS[0].path)
        self.assertEqual(result.body, b"{}")
        handlers = build.call_args.args
        self.assertIsInstance(handlers[0], MODULE.urllib.request.ProxyHandler)
        self.assertEqual(handlers[0].proxies, {})
        self.assertIsInstance(handlers[1], MODULE._NoRedirect)
        self.assertIsInstance(handlers[2], MODULE.urllib.request.HTTPSHandler)
        self.assertTrue(handlers[2]._context.check_hostname)
        self.assertEqual(handlers[2]._context.verify_mode, MODULE.ssl.CERT_REQUIRED)

    def test_transport_error_has_one_open_attempt(self):
        opener = SimpleNamespace(
            open=unittest.mock.Mock(side_effect=MODULE.urllib.error.URLError("offline"))
        )
        with (
            patch.object(MODULE.urllib.request, "build_opener", return_value=opener),
            self.assertRaises(MODULE.DiagnosticError) as caught,
        ):
            MODULE._http_get(MODULE.ENDPOINTS[0].path)
        self.assertEqual(caught.exception.category, "TLS_OR_TRANSPORT_ERROR")
        opener.open.assert_called_once()

    def test_http_redirect_is_terminal_and_body_bound_is_enforced(self):
        redirect = MODULE.urllib.error.HTTPError(
            MODULE.ORIGIN, 302, "redirect", {}, None
        )
        with patch.object(
            MODULE.urllib.request,
            "build_opener",
            return_value=SimpleNamespace(
                open=lambda *_a, **_k: (_ for _ in ()).throw(redirect)
            ),
        ):
            result = MODULE._http_get(MODULE.ENDPOINTS[0].path)
        self.assertEqual(result.error_category, "REDIRECT_BLOCKED")
        self.assertEqual(result.status, 302)
        huge = SimpleNamespace(
            status=200,
            headers={},
            geturl=lambda: MODULE.ORIGIN + MODULE.ENDPOINTS[0].path,
            read=lambda _n: b"x" * (MODULE.MAX_RESPONSE_BYTES + 1),
            close=lambda: None,
        )
        with (
            patch.object(
                MODULE.urllib.request,
                "build_opener",
                return_value=SimpleNamespace(open=lambda *_a, **_k: huge),
            ),
            self.assertRaises(MODULE.DiagnosticError) as caught,
        ):
            MODULE._http_get(MODULE.ENDPOINTS[0].path)
        self.assertEqual(caught.exception.category, "OVERSIZED_RESPONSE")

    def test_duplicate_safe_json_and_nonfinite_rejection(self):
        with self.assertRaises(MODULE.DiagnosticError) as duplicate:
            MODULE._parse_json(b'{"bids": [], "bids": []}')
        self.assertEqual(duplicate.exception.category, "DUPLICATE_JSON_KEY")
        with self.assertRaises(MODULE.DiagnosticError):
            MODULE._parse_json(b'{"t": NaN}')
        malformed = _book()
        malformed["bids"][0]["price"] = float("inf")
        self.assertEqual(
            MODULE._inspect_book(malformed, captured_at=NOW)["state"], "SCHEMA_ERROR"
        )

    def test_empty_book_is_distinct_from_schema_error_and_reports_freshness(self):
        empty = {"bids": [], "asks": [], "t": int(NOW.timestamp() * 1000)}
        result = MODULE._inspect_book(empty, captured_at=NOW)
        self.assertEqual(result["state"], "EMPTY_BOOK")
        self.assertEqual(result["freshness"], "FRESH")
        one_sided = {
            "bids": [],
            "asks": [{"price": 101, "quantity": 1}],
            "t": empty["t"],
        }
        self.assertEqual(
            MODULE._inspect_book(one_sided, captured_at=NOW)["state"], "PARTIAL_BOOK"
        )
        ordered_bad = {
            "bids": [{"price": 99, "quantity": 1}, {"price": 100, "quantity": 1}],
            "asks": [{"price": 101, "quantity": 1}],
            "t": empty["t"],
        }
        self.assertEqual(
            MODULE._inspect_book(ordered_bad, captured_at=NOW)["state"],
            "NON_EXECUTABLE",
        )
        crossed = {
            "bids": [{"price": 102, "quantity": 1}],
            "asks": [{"price": 101, "quantity": 1}],
            "t": empty["t"],
        }
        self.assertEqual(
            MODULE._inspect_book(crossed, captured_at=NOW)["reason"], "book_crossed"
        )
        bad_schema = {"bids": [], "asks": [], "t": 0}
        self.assertEqual(
            MODULE._inspect_book(bad_schema, captured_at=NOW)["state"], "SCHEMA_ERROR"
        )
        stale = {"bids": [], "asks": [], "t": int((NOW.timestamp() - 6) * 1000)}
        self.assertEqual(
            MODULE._inspect_book(stale, captured_at=NOW)["freshness"], "STALE"
        )

    def test_duplicate_instrument_identity_and_zero_price_status(self):
        rows, issue = MODULE._instrument_index(
            [_instrument("BTCUSD:DEV"), _instrument("btcusd:dev")]
        )
        self.assertEqual(rows, {})
        self.assertEqual(issue, "duplicate_instrument_identity")
        self.assertEqual(MODULE._price_status(0), "ZERO")
        self.assertEqual(MODULE._price_status(float("nan")), "INVALID")

    def test_instrument_index_keeps_unrelated_malformed_metadata_and_supported_flags(
        self,
    ):
        unrelated = {
            "name": "UNRELATED:DEV",
            "trading": "restricted",
            "visibility": "onlyClose",
        }
        rows, issue = MODULE._instrument_index([_instrument("BTCUSD:DEV"), unrelated])
        self.assertIsNone(issue)
        self.assertIn("UNRELATED:DEV", rows)
        self.assertEqual(MODULE._flag_status("restricted"), "RESTRICTED")
        self.assertEqual(MODULE._flag_status("onlyClose"), "ONLY_CLOSE")
        flags, target_issue = MODULE._instrument_observation(_instrument("BTCUSD:DEV"))
        self.assertIsNone(target_issue)
        self.assertEqual(flags["raw_last_price"], "ZERO")
        only_close = _instrument("BTCUSD:DEV")
        only_close["trading"] = "onlyClose"
        only_close["visibility"] = "restricted"
        flags, target_issue = MODULE._instrument_observation(only_close)
        self.assertIsNone(target_issue)
        self.assertEqual(flags["trading"], "ONLY_CLOSE")
        self.assertEqual(flags["visibility"], "RESTRICTED")

    def test_target_metadata_error_does_not_mask_depth_results(self):
        replies = self._successful_fixture()
        instruments = [_instrument(symbol) for symbol in MODULE.SYMBOLS]
        instruments[0] = {
            "name": "BTCUSD:DEV",
            "trading": "restricted",
            "visibility": "all",
            "lastPrice": 0,
            "markPrice": 100,
        }
        instruments.append({"name": "UNRELATED:DEV", "trading": "restricted"})
        replies["/api/market/instrument"] = _response(instruments)
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            run_dir.mkdir()
            report = MODULE._probe_all(
                run_dir=run_dir,
                source_hash="f" * 64,
                continuation=Continuation,
                delivery=Delivery,
                fetcher=lambda path: replies[path],
                clock=lambda: NOW,
            )
        self.assertEqual(
            report["instrument_issues"]["BTCUSD:DEV"], "instrument_schema_invalid"
        )
        self.assertEqual(
            report["symbols"]["BTCUSD:DEV"]["depth"]["default"]["state"],
            "TWO_SIDED_BOOK",
        )
        self.assertEqual(report["symbols"]["ETHUSD:DEV"]["trading"], "ALL")

    def _successful_fixture(self):
        replies = {
            "/api/market": _response({"state": "active", "updatedAt": NOW.isoformat()}),
            "/api/market/instrument": _response(
                [_instrument(symbol) for symbol in MODULE.SYMBOLS]
            ),
        }
        for endpoint in MODULE.ENDPOINTS:
            if endpoint.symbol:
                replies[endpoint.path] = _response(_book())
        return replies

    def test_all_requests_persist_reservation_before_wire_and_report_per_variant_counts(
        self,
    ):
        replies = self._successful_fixture()
        calls = []
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            run_dir.mkdir()

            def fetch(path):
                calls.append(path)
                name = next(row.label for row in MODULE.ENDPOINTS if row.path == path)
                reserved = next((run_dir / "requests").glob(f"*-{name}.reserved.json"))
                self.assertTrue(reserved.is_file())
                request = json.loads(reserved.read_bytes())
                self.assertFalse(request["automatic_retry"])
                return replies[path]

            report = MODULE._probe_all(
                run_dir=run_dir,
                source_hash="a" * 64,
                continuation=Continuation,
                delivery=Delivery,
                fetcher=fetch,
                clock=lambda: NOW,
            )
            self.assertEqual(len(calls), 17)
            self.assertEqual(report["request_count"], 17)
            self.assertEqual(report["status"], "DIAGNOSIS_RECORDED")
            self.assertFalse(report["authenticated"])
            self.assertFalse(report["trading_authority"])
            self.assertFalse(report["sample_is_24h_evidence"])
            self.assertEqual(report["book_counts"]["valid"], 15)
            for variant, _query in MODULE.VARIANTS:
                self.assertEqual(
                    report["book_counts"]["by_variant"][variant]["valid"], 5
                )
            self.assertEqual(report["symbols"]["BTCUSD:DEV"]["raw_last_price"], "ZERO")
            self.assertEqual(len(list((run_dir / "public-json").glob("*.json"))), 17)

    def test_true_empty_counted_independently_and_does_not_prevent_diagnosis(self):
        replies = self._successful_fixture()
        replies[MODULE.ENDPOINTS[2].path] = _response(
            {"bids": [], "asks": [], "t": int(NOW.timestamp() * 1000)}
        )
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            run_dir.mkdir()
            report = MODULE._probe_all(
                run_dir=run_dir,
                source_hash="b" * 64,
                continuation=Continuation,
                delivery=Delivery,
                fetcher=lambda path: replies[path],
                clock=lambda: NOW,
            )
        self.assertEqual(report["book_counts"]["empty"], 1)
        self.assertEqual(report["book_counts"]["by_variant"]["default"]["empty"], 1)
        self.assertEqual(report["status"], "DIAGNOSIS_RECORDED")
        self.assertFalse(report["paper_qualified"])

    def test_reservation_writer_failure_stops_before_any_request(self):
        calls = []

        def fail_write(_path, _payload, _continuation, _delivery):
            raise OSError("private path must not be surfaced")

        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            run_dir.mkdir()
            with self.assertRaises(MODULE.DiagnosticError) as caught:
                MODULE._probe_all(
                    run_dir=run_dir,
                    source_hash="c" * 64,
                    continuation=Continuation,
                    delivery=Delivery,
                    fetcher=lambda path: calls.append(path),
                    clock=lambda: NOW,
                    writer=fail_write,
                )
        self.assertEqual(caught.exception.category, "LOCAL_VALIDATION_FAILED")
        self.assertEqual(caught.exception.http_calls, 0)
        self.assertEqual(calls, [])

    def test_result_writer_failure_stops_remaining_requests(self):
        calls = []

        def fail_result(path, payload, continuation, delivery):
            if path.name.endswith(".result.json"):
                raise OSError("private path must not be surfaced")
            MODULE._exclusive_write(path, payload, continuation, delivery)

        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            run_dir.mkdir()
            with self.assertRaises(MODULE.DiagnosticError) as caught:
                MODULE._probe_all(
                    run_dir=run_dir,
                    source_hash="e" * 64,
                    continuation=Continuation,
                    delivery=Delivery,
                    fetcher=lambda path: (calls.append(path), _response({}))[1],
                    clock=lambda: NOW,
                    writer=fail_result,
                )
        self.assertEqual(caught.exception.category, "LOCAL_VALIDATION_FAILED")
        self.assertEqual(caught.exception.http_calls, 1)
        self.assertEqual(len(calls), 1)

    def test_missing_authorization_stops_before_source_admission(self):
        def forbidden_admission(_root):
            self.fail("source admission must not run without explicit authorization")

        with self.assertRaises(MODULE.DiagnosticError) as caught:
            MODULE._run_diagnostic(authorize=False, source_admitter=forbidden_admission)
        self.assertEqual(caught.exception.http_calls, 0)

    def test_source_check_failure_leaves_reservation_and_never_fetches_or_retries(self):
        calls = []

        def drift():
            raise MODULE.DiagnosticError("LOCAL_VALIDATION_FAILED")

        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            run_dir.mkdir()
            with self.assertRaises(MODULE.DiagnosticError):
                MODULE._probe_all(
                    run_dir=run_dir,
                    source_hash="d" * 64,
                    continuation=Continuation,
                    delivery=Delivery,
                    fetcher=lambda path: calls.append(path),
                    clock=lambda: NOW,
                    source_check=drift,
                )
            reservations = list((run_dir / "requests").glob("*.reserved.json"))
        self.assertEqual(len(reservations), 1)
        self.assertEqual(calls, [])

    def test_source_admission_requires_signed_current_main_origin_and_unchanged_bytes(
        self,
    ):
        content = SOURCE.read_bytes()

        def admission(
            head_record=None,
            origin=None,
            branch="main",
            status="",
            committed=None,
            current=None,
        ):
            head_id = "a" * 40
            outputs = [
                head_record or f"{head_id} G {MODULE.META_SIGNER}",
                head_id,
                origin or head_id,
                branch,
                status,
                content if committed is None else committed,
            ]
            results = [
                subprocess.CompletedProcess([], 0, output, "") for output in outputs
            ]

            def fake_git(_root, _args, *, binary=False, run=subprocess.run):
                result = results.pop(0)
                if binary and isinstance(result.stdout, str):
                    result.stdout = result.stdout.encode()
                return result

            with (
                patch.object(MODULE, "_git_run", side_effect=fake_git),
                patch.object(
                    MODULE,
                    "_regular_source_bytes",
                    return_value=content if current is None else current,
                ),
            ):
                return MODULE._verify_own_source(MODULE.KAIROS_ROOT)

        actual, digest = admission()
        self.assertEqual(actual, content)
        self.assertEqual(digest, hashlib.sha256(content).hexdigest())

        invalid_cases = (
            {"head_record": f"{'a' * 40} B {MODULE.META_SIGNER}"},
            {"head_record": f"{'a' * 40} G {'F' * 40}"},
            {"origin": "b" * 40},
            {"branch": "feature"},
            {"status": " M " + MODULE.SOURCE_RELATIVE},
            {"committed": content + b"committed drift"},
            {"current": content + b"working drift"},
        )
        for fields in invalid_cases:
            with (
                self.subTest(fields=tuple(fields)),
                self.assertRaises(MODULE.DiagnosticError),
            ):
                admission(**fields)

    def test_partial_and_non_executable_books_have_separate_counts(self):
        replies = self._successful_fixture()
        partial_path = MODULE.ENDPOINTS[2].path
        crossed_path = MODULE.ENDPOINTS[3].path
        replies[partial_path] = _response(
            {
                "bids": [],
                "asks": [{"price": 101, "quantity": 1}],
                "t": int(NOW.timestamp() * 1000),
            }
        )
        replies[crossed_path] = _response(
            {
                "bids": [{"price": 102, "quantity": 1}],
                "asks": [{"price": 101, "quantity": 1}],
                "t": int(NOW.timestamp() * 1000),
            }
        )
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            run_dir.mkdir()
            report = MODULE._probe_all(
                run_dir=run_dir,
                source_hash="1" * 64,
                continuation=Continuation,
                delivery=Delivery,
                fetcher=lambda path: replies[path],
                clock=lambda: NOW,
            )
        self.assertEqual(report["book_counts"]["partial"], 1)
        self.assertEqual(report["book_counts"]["non_executable"], 1)
        self.assertEqual(report["book_counts"]["valid"], 13)

    def test_committed_sampler_drift_and_import_failure_are_rejected(self):
        good_hash_bytes = b"committed sampler bytes"
        completed = subprocess.CompletedProcess([], 0, good_hash_bytes, "")
        with (
            patch.object(MODULE, "_git_run", return_value=completed),
            patch.object(
                MODULE, "_regular_source_bytes", return_value=b"different local sampler"
            ),
            self.assertRaises(MODULE.DiagnosticError),
        ):
            MODULE._load_preflight(MODULE.KAIROS_ROOT, SOURCE.read_bytes())

        invalid_python = b"def invalid(:\n"
        with (
            patch.object(
                MODULE,
                "_git_run",
                return_value=subprocess.CompletedProcess([], 0, invalid_python, ""),
            ),
            patch.object(MODULE, "_regular_source_bytes", return_value=invalid_python),
            self.assertRaises(MODULE.DiagnosticError),
        ):
            MODULE._load_preflight(MODULE.KAIROS_ROOT, SOURCE.read_bytes())


if __name__ == "__main__":
    unittest.main()
