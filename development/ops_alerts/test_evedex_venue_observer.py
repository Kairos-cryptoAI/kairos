"""Synthetic, offline tests for the plan-gated public observer."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

if __package__:
    from . import evedex_venue_observer as observer
else:
    import evedex_venue_observer as observer


class SimulatedCrash(BaseException):
    pass


def _body(
    symbol: str, venue: str, *, mid: float = 100.0, timestamp: int = 1_000_000, empty: bool = False
) -> bytes:
    if venue == "evedex":
        bids = [] if empty else [{"price": mid - 0.01, "quantity": 100.0}]
        asks = [] if empty else [{"price": mid + 0.01, "quantity": 100.0}]
        return json.dumps({"t": timestamp, "bids": bids, "asks": asks}).encode()
    bids = [] if empty else [[mid - 0.01, 100.0]]
    asks = [] if empty else [[mid + 0.01, 100.0]]
    return json.dumps({"T": timestamp, "bids": bids, "asks": asks}).encode()


def _fake_fetcher(
    *, bad: dict[tuple[str, str], str] | None = None, shift_evedex_after_first_slot: bool = False
):
    calls: list[str] = []
    bad = bad or {}

    def fetch(url: str, *, timeout_s: int, max_bytes: int) -> observer.PublicResponse:
        calls.append(url)
        parsed = urlsplit(url)
        venue = "evedex" if parsed.hostname == "trading-api.evedex.tech" else "binance"
        if venue == "evedex":
            venue_symbol = parsed.path.rsplit("/", 2)[-2]
            symbol = venue_symbol.replace("USD:DEV", "USDT")
        else:
            from urllib.parse import parse_qs

            symbol = parse_qs(parsed.query)["symbol"][0]
        mode = bad.get((symbol, venue))
        if mode == "unknown":
            return observer.PublicResponse(None, None, 8.0, 1_000_000, "TLS_OR_TRANSPORT_ERROR")
        timestamp = 1_000_000
        if mode == "stale":
            timestamp -= 10_000
        elif mode == "future":
            timestamp += 5_000
        empty = mode == "empty"
        mid = (
            101.0 if shift_evedex_after_first_slot and venue == "evedex" and (len(calls) - 1) // 10 else 100.0
        )
        body = _body(symbol, venue, mid=mid, timestamp=timestamp, empty=empty)
        return observer.PublicResponse(200, body, 2.0, 1_000_000)

    return fetch, calls


class ObserverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparison = observer._comparison_logic()

    def small_plan(self, *, duration=10, interval=10):
        return observer.ObservationPlan(
            duration_s=duration,
            poll_interval_s=interval,
            request_timeout_s=1,
            slot_deadline_s=10,
            max_response_bytes=observer.MAX_RESPONSE_BYTES,
            max_storage_bytes=observer.MAX_STORAGE_BYTES,
        )

    def make_run_dir(self, root: Path) -> Path:
        run_dir = root / "run-test"
        run_dir.mkdir()
        for name in ("attempts", "slots", "public"):
            (run_dir / name).mkdir()
        return run_dir

    def test_dry_plan_is_network_free_and_not_qualification(self):
        output = io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            mock.patch.object(observer, "_http_get", side_effect=AssertionError("network called")),
        ):
            self.assertEqual(observer.main([]), 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan["status"], "PLAN_ONLY")
        self.assertEqual(plan["maximum_requests"], observer.MAX_REQUESTS)
        self.assertEqual(len(plan["instruments"]), 5)
        self.assertFalse(plan["authenticated"])
        self.assertFalse(plan["orders_enabled"])
        self.assertFalse(plan["readiness_changed"])
        self.assertIn("NOT_QUALIFIED", plan["qualification_status"])

    def test_all_five_books_are_paired_and_hashed(self):
        fetcher, calls = _fake_fetcher()
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run_dir(Path(directory))
            outcome, samples = observer._collect_slot(
                run_dir=run_dir,
                slot=1,
                scheduled_at="2026-01-01T00:00:00+00:00",
                source_hash="a" * 64,
                plan=self.small_plan(),
                module=self.comparison,
                fetcher=fetcher,
                monotonic=lambda: 0.0,
                wall_ms=lambda: 1_000_000,
            )
            self.assertEqual(outcome["requests_reserved"], 10)
            self.assertEqual(outcome["unknown_outcomes"], 0)
            self.assertEqual(len(calls), 10)
            self.assertEqual(
                {symbol for symbol, _sample in samples}, {symbol for symbol, _venue in observer.INSTRUMENTS}
            )
            measurements = list((run_dir / "slots").glob("*.measurement.json"))
            self.assertEqual(len(measurements), 5)
            for path in measurements:
                record = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(record["measurement_status"], "MEASURED")
                self.assertTrue(record["evedex_response_sha256"])
                self.assertTrue(record["binance_response_sha256"])
                self.assertIsNotNone(record["buy_slippage_bps"])
            self.assertEqual(len(list((run_dir / "public").glob("*.raw"))), 10)

    def test_missing_stale_and_exchange_clock_skew_stay_explicit(self):
        fetcher, _calls = _fake_fetcher(
            bad={
                ("BTCUSDT", "evedex"): "unknown",
                ("SOLUSDT", "evedex"): "empty",
                ("BNBUSDT", "evedex"): "stale",
                ("XRPUSDT", "evedex"): "future",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run_dir(Path(directory))
            _outcome, samples = observer._collect_slot(
                run_dir=run_dir,
                slot=1,
                scheduled_at="2026-01-01T00:00:00+00:00",
                source_hash="b" * 64,
                plan=self.small_plan(),
                module=self.comparison,
                fetcher=fetcher,
                monotonic=lambda: 0.0,
                wall_ms=lambda: 1_000_000,
            )
            self.assertEqual(len(samples), 3)
            records = {
                json.loads(path.read_text(encoding="utf-8"))["binance_symbol"]: json.loads(
                    path.read_text(encoding="utf-8")
                )
                for path in (run_dir / "slots").glob("*.measurement.json")
            }
            self.assertEqual(records["BTCUSDT"]["reason"], "public_response_unavailable")
            self.assertIsNone(records["BTCUSDT"]["basis_bps"])
            self.assertIsNone(records["BTCUSDT"]["buy_slippage_bps"])
            self.assertEqual(records["SOLUSDT"]["reason"], "book_missing_or_invalid")
            self.assertIsNone(records["SOLUSDT"]["spread_bps"])
            self.assertEqual(records["BNBUSDT"]["freshness"], "STALE_OR_CLOCK_SKEWED")
            self.assertEqual(records["XRPUSDT"]["freshness"], "STALE_OR_CLOCK_SKEWED")
            self.assertGreater(records["XRPUSDT"]["local_clock_ahead_ms"], 0)

    def test_two_slots_use_quant_p95_and_never_qualify(self):
        fetcher, _calls = _fake_fetcher(shift_evedex_after_first_slot=True)
        with tempfile.TemporaryDirectory() as directory:
            mono = {"now": 0.0}
            wall = {"now": datetime(2026, 1, 1, tzinfo=UTC)}

            def sleep(seconds: float) -> None:
                mono["now"] += seconds
                wall["now"] += timedelta(seconds=seconds)

            report = observer._execute_observation(
                authorize=True,
                output_root=Path(directory),
                plan=self.small_plan(duration=20),
                fetcher=fetcher,
                sleep=sleep,
                monotonic=lambda: mono["now"],
                wall_clock=lambda: wall["now"],
                make_uuid=lambda: "12345678-1234-4234-8234-123456789abc",
            )
            self.assertEqual(report["planned_slots"], 2)
            self.assertEqual(report["completed_slots"], 2)
            self.assertEqual(report["symbols"]["BTCUSDT"]["sample_count"], 2)
            self.assertAlmostEqual(report["symbols"]["BTCUSDT"]["p95_abs_basis_bps"], 95.0)
            self.assertFalse(report["sample_is_24h_evidence"])
            self.assertFalse(report["account_prerequisites_attested"])
            self.assertEqual(report["qualification_status"], "NOT_QUALIFIED_OWNER_REVIEW_REQUIRED")
            self.assertFalse(report["readiness_changed"])
            self.assertTrue((Path(directory) / "observer.lock").exists())

    def test_crash_leaves_unknown_reservation_and_lock_blocks_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fetcher, calls = _fake_fetcher()

            def crash_after_one(url: str, *, timeout_s: int, max_bytes: int):
                if calls:
                    raise SimulatedCrash()
                return fetcher(url, timeout_s=timeout_s, max_bytes=max_bytes)

            with self.assertRaises(SimulatedCrash):
                observer._execute_observation(
                    authorize=True,
                    output_root=root,
                    plan=self.small_plan(),
                    fetcher=crash_after_one,
                    monotonic=lambda: 0.0,
                    wall_clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
                    make_uuid=lambda: "22345678-1234-4234-8234-123456789abc",
                )
            self.assertEqual(len(list(root.glob("run-*/attempts/*.reserved.json"))), 10)
            self.assertEqual(len(list(root.glob("run-*/attempts/*.result.json"))), 1)
            reservations = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in root.glob("run-*/attempts/*.reserved.json")
            ]
            self.assertTrue(all(item["outcome"] == "UNKNOWN_UNTIL_RESULT" for item in reservations))
            self.assertTrue((root / "observer.lock").exists())
            self.assertEqual(len(calls), 1)
            with self.assertRaisesRegex(observer.ObserverError, "LATCHED"):
                observer._execute_observation(
                    authorize=True,
                    output_root=root,
                    plan=self.small_plan(),
                    fetcher=fetcher,
                )
            self.assertEqual(len(calls), 1)

    def test_changed_quant_measurement_source_is_rejected(self):
        original = observer.QUANT_SOURCE.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "venue_comparison.py"
            changed.write_bytes(original + b"\n# changed\n")
            with self.assertRaisesRegex(observer.ObserverError, "SOURCE_CHANGED"):
                observer._comparison_logic(path=changed)

    def test_slot_deadline_marks_reserved_but_unsent_attempts(self):
        fetcher, calls = _fake_fetcher()
        monotonic = {"now": 0.0}

        def consume_deadline(url: str, *, timeout_s: int, max_bytes: int):
            response = fetcher(url, timeout_s=timeout_s, max_bytes=max_bytes)
            monotonic["now"] = 10.0
            return response

        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run_dir(Path(directory))
            outcome, _samples = observer._collect_slot(
                run_dir=run_dir,
                slot=1,
                scheduled_at="2026-01-01T00:00:00+00:00",
                source_hash="c" * 64,
                plan=self.small_plan(),
                module=self.comparison,
                fetcher=consume_deadline,
                monotonic=lambda: monotonic["now"],
                wall_ms=lambda: 1_000_000,
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(outcome["requests_reserved"], 10)
        self.assertEqual(outcome["requests_attempted"], 1)
        self.assertEqual(outcome["requests_not_sent"], 9)
        self.assertEqual(outcome["unknown_outcomes"], 0)

    def test_plan_limits_keep_duration_polling_and_storage_finite(self):
        with self.assertRaises(ValueError):
            observer.ObservationPlan(duration_s=observer.MAX_DURATION_S + 1)
        plan = observer.ObservationPlan()
        self.assertLessEqual(plan.maximum_storage_reservation, plan.max_storage_bytes)
        self.assertEqual(plan.slots * observer.REQUESTS_PER_SLOT, observer.MAX_REQUESTS)


if __name__ == "__main__":
    unittest.main()
