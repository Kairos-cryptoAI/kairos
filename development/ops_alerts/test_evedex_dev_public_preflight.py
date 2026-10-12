"""No-network contracts for the public-only EVEDEX DEV sampler."""

from __future__ import annotations

import contextlib
import datetime as dt
import inspect
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest import mock

import evedex_dev_public_preflight as sampler


class FakeDelivery:
    @staticmethod
    def _no_reparse(_path: Path) -> None:
        return None

    @staticmethod
    def _private_acl(_path: Path) -> None:
        return None


class FakeContinuation:
    @staticmethod
    def _exclusive_fsync(path: Path, payload: bytes) -> None:
        with path.open("xb") as output:
            output.write(payload)
            output.flush()

    @staticmethod
    def _set_exact_file_acl(_path: Path) -> None:
        return None


class FakeProvisioner:
    calls: ClassVar[list[Path]] = []

    @classmethod
    def harden_permissions(cls, path: Path) -> None:
        if any(path.iterdir()):
            raise AssertionError("only a new empty root may be hardened")
        cls.calls.append(path)


class PublicSamplerTests(unittest.TestCase):
    def test_real_pin_loader_accepts_the_production_positional_source_root(
        self,
    ) -> None:
        bound = inspect.signature(sampler._verify_pins).bind(sampler.KAIROS_ROOT)
        self.assertEqual(bound.arguments["root"], sampler.KAIROS_ROOT)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = dt.datetime(2026, 10, 12, 12, 0, tzinfo=dt.UTC)
        self.root = Path(self.temp.name) / "runs"
        self.run_id = "11111111-1111-4111-8111-111111111111"
        self.calls: list[str] = []
        FakeProvisioner.calls = []
        self.payloads = self._valid_payloads()

    def _valid_payloads(self) -> dict[str, object]:
        mapping: dict[str, object] = {
            "/api/market": {"state": "active", "updatedAt": self.now.isoformat()},
            "/api/market/instrument": [
                {
                    "name": venue,
                    "trading": "all",
                    "visibility": "all",
                    "lastPrice": 100.0,
                    "markPrice": 100.0,
                    "minQuantity": 0.01,
                    "maxQuantity": 1000.0,
                    "quantityIncrement": 0.01,
                    "priceIncrement": 0.01,
                }
                for _, venue in sampler.SYMBOLS
            ],
        }
        for _, venue in sampler.SYMBOLS:
            mapping[f"/api/market/{venue}/deep?marketLevel=1"] = {
                "bids": [
                    {"price": 100.0, "quantity": 2.0},
                    {"price": 99.0, "quantity": 3.0},
                ],
                "asks": [
                    {"price": 100.1, "quantity": 4.0},
                    {"price": 101.0, "quantity": 5.0},
                ],
                "t": self.now.timestamp() * 1000,
            }
            mapping[f"/api/market/{venue}/recent-trades"] = [
                {
                    "id": "t-1",
                    "instrument": venue,
                    "fillQuantity": 0.5,
                    "fillPrice": 100.05,
                    "createdAt": self.now.isoformat(),
                }
            ]
        return mapping

    def _fetcher(self, path: str) -> sampler.PublicResponse:
        self.calls.append(path)
        value = self.payloads[path]
        body = (
            value
            if isinstance(value, bytes)
            else json.dumps(value, allow_nan=False).encode()
        )
        return sampler.PublicResponse(200, 12.5, body, self.now)

    def _run(self, *, make_uuid=None, **kwargs) -> dict:
        return sampler._run_with_dependencies(
            authorize=True,
            root=self.root,
            source_root=Path(self.temp.name),
            fetcher=self._fetcher,
            clock=lambda: self.now,
            make_uuid=make_uuid or (lambda: self.run_id),
            pin_loader=lambda _root: (FakeContinuation, FakeDelivery, FakeProvisioner),
            **kwargs,
        )

    def test_plan_only_is_zero_effect_and_has_no_mutation_switches(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(sampler.main([]), 0)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"status": "PLAN_ONLY", "http_calls": 0, "trading_authority": False},
        )
        self.assertEqual(self.calls, [])
        self.assertFalse(self.root.exists())

    def test_complete_sample_is_exactly_12_gets_and_not_a_qualification(self) -> None:
        report = self._run()
        self.assertEqual(report["status"], "PASS_PUBLIC_SNAPSHOT_ONLY")
        self.assertEqual(report["request_count"], 12)
        self.assertEqual(len(self.calls), 12)
        self.assertEqual(len(set(self.calls)), 12)
        self.assertEqual(set(self.calls), {row.path for row in sampler.ENDPOINTS})
        self.assertFalse(report["authenticated"])
        self.assertFalse(report["paper_qualified"])
        self.assertFalse(report["canary_qualified"])
        self.assertFalse(report["seven_day_qualified"])
        self.assertFalse(report["trading_authority"])
        run_dir = self.root / f"sample-20261012T120000Z-{self.run_id}"
        self.assertEqual(len(list((run_dir / "requests").glob("*.reserved.json"))), 12)
        self.assertEqual(len(list((run_dir / "requests").glob("*.result.json"))), 12)
        self.assertEqual(len(list((run_dir / "public-json").glob("*.json"))), 12)
        self.assertTrue((run_dir / "report.json").is_file())
        self.assertEqual(FakeProvisioner.calls, [self.root])
        results = [
            json.loads(path.read_text())
            for path in (run_dir / "requests").glob("*.result.json")
        ]
        self.assertTrue(
            all("request_sha256" in row and "captured_at_utc" in row for row in results)
        )

    def test_injected_writer_reserves_each_request_before_fetch(self) -> None:
        events: list[str] = []

        def writer(
            path: Path, payload: bytes, continuation: object, delivery: object
        ) -> None:
            events.append("write:" + path.name)
            sampler._exclusive_write(path, payload, continuation, delivery)

        def fetcher(path: str) -> sampler.PublicResponse:
            events.append("fetch:" + path)
            return self._fetcher(path)

        sampler._run_with_dependencies(
            authorize=True,
            root=self.root,
            source_root=Path(self.temp.name),
            fetcher=fetcher,
            clock=lambda: self.now,
            make_uuid=lambda: self.run_id,
            pin_loader=lambda _root: (FakeContinuation, FakeDelivery, FakeProvisioner),
            writer=writer,
        )
        for index, endpoint in enumerate(sampler.ENDPOINTS, start=1):
            stem = f"{index:02d}-{endpoint.label}"
            reservation = events.index("write:" + stem + ".reserved.json")
            request = events.index("fetch:" + endpoint.path)
            self.assertLess(reservation, request)

    def test_empty_book_blocks_but_all_five_symbol_pairs_are_sampled(self) -> None:
        self.payloads["/api/market/BTCUSD:DEV/deep?marketLevel=1"] = {
            "bids": [],
            "asks": [{"price": 100.1, "quantity": 1.0}],
            "t": self.now.timestamp() * 1000,
        }
        report = self._run()
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["symbols"]["BTCUSDT"]["depth"]["reason"], "depth_empty")
        self.assertEqual(len(self.calls), 12)
        self.assertEqual(sum("/deep?" in path for path in self.calls), 5)
        self.assertEqual(sum("recent-trades" in path for path in self.calls), 5)

    def test_future_and_stale_books_are_rejected(self) -> None:
        self.payloads["/api/market/BTCUSD:DEV/deep?marketLevel=1"]["t"] = (
            self.now.timestamp() + 3
        ) * 1000
        self.payloads["/api/market/ETHUSD:DEV/deep?marketLevel=1"]["t"] = (
            self.now.timestamp() - 6
        ) * 1000
        report = self._run()
        self.assertEqual(
            report["symbols"]["BTCUSDT"]["depth"]["reason"], "depth_from_future"
        )
        self.assertEqual(report["symbols"]["ETHUSDT"]["depth"]["reason"], "depth_stale")

    def test_duplicate_json_and_duplicate_instrument_identity_block(self) -> None:
        self.payloads["/api/market"] = (
            b'{"state":"active","state":"inactive","updatedAt":"2026-10-12T12:00:00Z"}'
        )
        instruments = self.payloads["/api/market/instrument"]
        assert isinstance(instruments, list)
        instruments.append(dict(instruments[0]))
        report = self._run()
        self.assertEqual(report["market_snapshot"], "UNVERIFIED")
        self.assertEqual(report["instrument_contract"], "BLOCKED")
        self.assertEqual(report["instrument_issue"], "duplicate_instrument_identity")
        run_dir = self.root / f"sample-20261012T120000Z-{self.run_id}"
        market_result = json.loads(
            (run_dir / "requests/01-market.result.json").read_text()
        )
        self.assertEqual(market_result["error_category"], "DUPLICATE_JSON_KEY")
        self.assertFalse((run_dir / "public-json/01-market.json").exists())

    def test_empty_or_stale_trades_are_unverified_not_liquidity_qualification(
        self,
    ) -> None:
        self.payloads["/api/market/BTCUSD:DEV/recent-trades"] = []
        stale = self.payloads["/api/market/ETHUSD:DEV/recent-trades"]
        assert isinstance(stale, list)
        stale[0]["createdAt"] = (self.now - dt.timedelta(seconds=301)).isoformat()
        report = self._run()
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(
            report["symbols"]["BTCUSDT"]["recent_trades"]["reason"], "no_recent_trades"
        )
        self.assertEqual(
            report["symbols"]["ETHUSDT"]["recent_trades"]["reason"],
            "latest_trade_stale_or_future",
        )

    def test_oversized_response_is_sanitized_and_bounded(self) -> None:
        self.payloads["/api/market"] = b" " * (sampler.MAX_RESPONSE_BYTES + 1)
        report = self._run()
        self.assertEqual(report["status"], "BLOCKED")
        run_dir = self.root / f"sample-20261012T120000Z-{self.run_id}"
        row = json.loads((run_dir / "requests/01-market.result.json").read_text())
        self.assertEqual(row["error_category"], "OVERSIZED_RESPONSE")
        self.assertEqual(len(self.calls), 12)
        self.assertNotIn(" " * 300, (run_dir / "report.json").read_text())

    def test_transport_exception_never_serializes_exception_text(self) -> None:
        secretish = "DO_NOT_LEAK_PRIVATE_EXCEPTION"

        def raising_fetch(path: str) -> sampler.PublicResponse:
            if path == "/api/market":
                self.calls.append(path)
                raise RuntimeError(secretish)
            return self._fetcher(path)

        report = sampler._run_with_dependencies(
            authorize=True,
            root=self.root,
            source_root=Path(self.temp.name),
            fetcher=raising_fetch,
            clock=lambda: self.now,
            make_uuid=lambda: self.run_id,
            pin_loader=lambda _root: (FakeContinuation, FakeDelivery, FakeProvisioner),
        )
        self.assertEqual(report["status"], "BLOCKED")
        saved = (
            self.root / f"sample-20261012T120000Z-{self.run_id}/report.json"
        ).read_text()
        self.assertNotIn(secretish, saved)
        self.assertEqual(len(self.calls), 12)

    def test_repeat_uuid_never_overwrites_existing_attempt(self) -> None:
        self._run()
        self.assertEqual(FakeProvisioner.calls, [self.root])
        self.calls.clear()
        with self.assertRaises(sampler.SamplerError):
            self._run()
        self.assertEqual(self.calls, [])
        self.assertEqual(FakeProvisioner.calls, [self.root])
        self.assertEqual(len(list(self.root.glob("sample-*/report.json"))), 1)

    def test_durable_write_failure_stops_after_current_request_and_reports_count(
        self,
    ) -> None:
        def failing_writer(
            path: Path, payload: bytes, continuation: object, delivery: object
        ) -> None:
            if path.name == "01-market.result.json":
                raise OSError("PRIVATE_WRITE_FAILURE_DETAIL")
            sampler._exclusive_write(path, payload, continuation, delivery)

        with self.assertRaises(sampler.SamplerError) as raised:
            self._run(writer=failing_writer)
        self.assertEqual(raised.exception.http_calls, 1)
        self.assertEqual(len(self.calls), 1)

    def test_main_reports_unknown_after_outer_exception_not_zero(self) -> None:
        output = io.StringIO()
        with (
            mock.patch.object(
                sampler,
                "run_public_preflight",
                side_effect=sampler.SamplerError(
                    "LOCAL_VALIDATION_FAILED", http_calls=2
                ),
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(sampler.main(["--execute-public-preflight"]), 2)
        report = json.loads(output.getvalue())
        self.assertEqual(report["http_calls"], 2)
        self.assertTrue(report["requires_manual_review"])
        self.assertFalse(report["trading_authority"])

    def test_unknown_url_is_rejected_before_fetch(self) -> None:
        with self.assertRaises(sampler.SamplerError):
            sampler._request_url("https://attacker.invalid/api/market")
        with self.assertRaises(sampler.SamplerError):
            sampler._request_url("/api/order")

    def test_dirty_or_untrusted_source_pin_fails_closed_before_run_creation(
        self,
    ) -> None:
        calls: list[list[str]] = []

        def git_runner(command: list[str], **_kwargs: object) -> SimpleNamespace:
            calls.append(command)
            if "--format=%H %G? %GF" in command and command[-1] == "HEAD":
                return SimpleNamespace(
                    returncode=0,
                    stdout=f"{'a' * 40} G {sampler.META_SIGNER}",
                )
            if command[-2:] == ["rev-parse", "HEAD"]:
                return SimpleNamespace(returncode=0, stdout="a" * 40)
            if command[-2:] == ["rev-parse", "refs/remotes/origin/main"]:
                return SimpleNamespace(returncode=0, stdout="a" * 40)
            if command[-2:] == ["branch", "--show-current"]:
                return SimpleNamespace(returncode=0, stdout="main")
            if "status" in command:
                return SimpleNamespace(
                    returncode=0,
                    stdout=f"?? {sampler.SOURCE_RELATIVE}\n",
                )
            if "--is-ancestor" in command:
                return SimpleNamespace(returncode=0, stdout="")
            return SimpleNamespace(returncode=0, stdout=b"")

        with self.assertRaises(sampler.SamplerError):
            sampler._verify_pins(root=Path(self.temp.name), run=git_runner)
        self.assertTrue(calls)
        self.assertFalse(self.root.exists())
        self.assertEqual(self.calls, [])
        self.assertTrue(
            sampler._scoped_status_has_changes(f" M {sampler.SOURCE_RELATIVE}\n")
        )
        self.assertFalse(
            sampler._scoped_status_has_changes(
                " M development/adaptive_replay/file.py\n"
            )
        )

    def test_transport_uses_only_fixed_verified_tls_get(self) -> None:
        class Response:
            status = 200
            headers: ClassVar[dict[str, str]] = {"Content-Length": "2"}

            @staticmethod
            def geturl() -> str:
                return sampler.ORIGIN + sampler.ENDPOINTS[0].path

            @staticmethod
            def read(limit: int) -> bytes:
                if limit != sampler.MAX_RESPONSE_BYTES + 1:
                    raise AssertionError("response bound missing")
                return b"{}"

            @staticmethod
            def close() -> None:
                return None

        class Opener:
            calls: ClassVar[list[tuple[object, int]]] = []

            def open(self, request: object, *, timeout: int) -> Response:
                self.calls.append((request, timeout))
                return Response()

        opener = Opener()
        with mock.patch.object(
            sampler.urllib.request, "build_opener", return_value=opener
        ) as build:
            result = sampler._http_get(sampler.ENDPOINTS[0].path)
        self.assertEqual(result.body, b"{}")
        self.assertEqual(len(opener.calls), 1)
        request, timeout = opener.calls[0]
        self.assertEqual(timeout, 15)
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.full_url, sampler.ORIGIN + sampler.ENDPOINTS[0].path)
        self.assertNotIn("Authorization", request.headers)
        handlers = build.call_args.args
        proxy = next(
            item
            for item in handlers
            if isinstance(item, sampler.urllib.request.ProxyHandler)
        )
        tls = next(
            item
            for item in handlers
            if isinstance(item, sampler.urllib.request.HTTPSHandler)
        )
        self.assertEqual(proxy.proxies, {})
        self.assertEqual(tls._context.verify_mode, sampler.ssl.CERT_REQUIRED)
        self.assertTrue(tls._context.check_hostname)
        self.assertTrue(any(isinstance(item, sampler._NoRedirect) for item in handlers))

    def test_public_decimal_strings_and_future_trade_skew_are_bounded(self) -> None:
        for value, expected in (("1", 1.0), ("0.125", 0.125), ("2e1", 20.0)):
            self.assertEqual(sampler._number(value), expected)
        for value in (" 1", "1 ", "NaN", "Infinity", True, "1e999"):
            with self.assertRaises((ValueError, TypeError)):
                sampler._number(value)
        trade = {
            "id": "future-1",
            "instrument": "BTCUSD:DEV",
            "fillQuantity": "0.1",
            "fillPrice": "10.25",
            "createdAt": (self.now + dt.timedelta(seconds=3)).isoformat(),
        }
        result = sampler._validate_trades(
            [trade], venue="BTCUSD:DEV", captured_at=self.now
        )
        self.assertEqual(result["state"], "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
