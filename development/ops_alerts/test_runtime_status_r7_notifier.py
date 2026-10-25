from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import patch


def _load_local(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("test module unavailable")
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


r5 = _load_local(
    "_runtime_status_r5_notifier_test",
    Path(__file__).with_name("runtime_status_r5_notifier.py"),
)
r7 = _load_local(
    "_runtime_status_r7_notifier_test",
    Path(__file__).with_name("runtime_status_r7_notifier.py"),
)


def valid_status(
    *, state: str = "RUNNING_NONTRADING", now: datetime | None = None
) -> dict[str, Any]:
    state_now = now or datetime.now(UTC)
    waiting = state == "WAITING_SOURCE_NONTRADING"
    return {
        "state": state,
        "owner": r7.OWNER,
        "cycles": 1,
        "watermarks_ms": {symbol: 1_791_894_180_000 for symbol in r7.SYMBOLS},
        "pending_outbox": 0,
        "unresolved_inbox": 0,
        "completed_inbox": 8070,
        "uncompleted_publications": 0,
        "new_publications": 0,
        "observed_at_utc": state_now.isoformat(),
        "PAPER_QUALIFIED": False,
        "ALPHA_READY": False,
        "LIVE_READY": False,
        "STRATEGY_POLICY": "REJECT_ALL",
        "source_transport": {
            "timeout_rounds": 1 if waiting else 0,
            "recoveries": 0,
            "consecutive_timeout_rounds": 1 if waiting else 0,
        },
        "source_wait_reason": r7._SOURCE_TIMEOUT if waiting else None,
        "source_fresh": state == "RUNNING_NONTRADING",
        "trading_started": False,
    }


def valid_dns_status(*, state: str = "WAITING_SOURCE_NONTRADING") -> dict[str, Any]:
    status = valid_status(state=state)
    status["source_transport"] = {
        "timeout_rounds": 0,
        "recoveries": 0,
        "consecutive_timeout_rounds": 0,
        "dns_failure_rounds": 2,
        "consecutive_dns_failure_rounds": 1
        if state == "WAITING_SOURCE_NONTRADING"
        else 0,
    }
    status["source_wait_reason"] = (
        "OFFICIAL_CLOSED_BAR_FETCH_DNS_FAILURE"
        if state == "WAITING_SOURCE_NONTRADING"
        else None
    )
    status["source_fresh"] = state == "RUNNING_NONTRADING"
    return status


CURRENT_TEST_OWNER = "a" * 32
CURRENT_TEST_DEPLOY_REVISION = "b" * 40
CURRENT_TEST_ACCEPTANCE_ID = "c" * 32


def current_binding() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": r7.CURRENT_ALERT_KIND,
        "owner": CURRENT_TEST_OWNER,
        "host_acceptance_id": CURRENT_TEST_ACCEPTANCE_ID,
        "native_receipt_sha256": "1" * 64,
        "native_receipt_signature_sha256": "2" * 64,
        "host_report_sha256": "3" * 64,
        "host_report_signature_sha256": "4" * 64,
        "deploy_revision": CURRENT_TEST_DEPLOY_REVISION,
        "status_schema": r7.CURRENT_STATUS_SCHEMA,
    }


def current_status(
    *,
    owner: str = CURRENT_TEST_OWNER,
    state: str = "RUNNING_NONTRADING",
    now: datetime | None = None,
) -> dict[str, Any]:
    observed = now or datetime.now(UTC)
    minute = int(observed.timestamp() * 1000) // 60_000 * 60_000
    waiting = state == "WAITING_SOURCE_NONTRADING"
    return {
        "state": state,
        "owner": owner,
        "schema_profile": r7.CURRENT_STATUS_SCHEMA,
        "schema_migration_count": r7.CURRENT_MIGRATION_COUNT,
        "schema_public_table_count": r7.CURRENT_PUBLIC_TABLE_COUNT,
        "observed_at_utc": observed.isoformat(),
        "mode": "serve",
        "cycles": 1,
        "pending_outbox": 0,
        "unresolved_inbox": 0,
        "completed_inbox": 1,
        "uncompleted_publications": 0,
        "new_publications": 0,
        "watermarks_ms": {symbol: minute for symbol in r7.SYMBOLS},
        "source_fresh": not waiting and state != "CATCHING_UP_NONTRADING",
        "source_wait_reason": "SOURCE_TIMEOUT" if waiting else None,
        "trading_started": False,
        "PAPER_QUALIFIED": False,
        "ALPHA_READY": False,
        "LIVE_READY": False,
        "STRATEGY_POLICY": "REJECT_ALL",
    }


class FakeDelivery:
    def _no_reparse(self, _path: Path) -> None:
        return None

    def _private_acl(self, _path: Path) -> None:
        return None


class FileReader:
    def __init__(self, *, fail: bool = False):
        self.fail = fail

    def _read_private(self, path: Path, *, maximum: int, delivery: Any) -> bytes:
        del delivery
        if self.fail:
            raise OSError("redacted reader failure")
        raw = path.read_bytes()
        if len(raw) > maximum:
            raise ValueError("limit")
        return raw


class FakeContinuation:
    def _set_exact_file_acl(self, _path: Path) -> None:
        return None

    def _exclusive_fsync(self, path: Path, raw: bytes) -> None:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())


class MemoryJournal:
    rows: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *_args: Any):
        self.rows = MemoryJournal.rows

    class _Lock:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *_args: object) -> None:
            return None

    def locked(self) -> MemoryJournal._Lock:
        return self._Lock()

    def read(self, *, allow_pending: bool = False) -> list[dict[str, Any]]:
        pending = None
        for row in self.rows:
            if row["kind"] == "send_reserved":
                pending = row
            elif row["kind"] == "send_outcome":
                if row["result"] == "unknown":
                    raise r7.R7Error("R7_SEND_OUTCOME_UNKNOWN")
                pending = None
        if pending is not None and not allow_pending:
            raise r7.R7Error("R7_SEND_OUTCOME_UNKNOWN")
        return list(self.rows)

    def _append(self, row: dict[str, Any]) -> None:
        self.rows.append(dict(row))


class RuntimeStatusR7NotifierTests(unittest.TestCase):
    def _successor_fixture(self, base: Path) -> tuple[Any, dict[str, Any], Path, bytes, bytes]:
        import hashlib

        predecessor = base / "predecessor"
        successor = base / "successor"
        predecessor.mkdir()
        successor.mkdir()
        old_binding = b'{"synthetic":"old binding"}'
        old_journal = b'{"synthetic":"old journal"}\n'
        old_guard = b"synthetic guard metadata"
        (predecessor / "binding.json").write_bytes(old_binding)
        (predecessor / "events.jsonl").write_bytes(old_journal)
        (predecessor / r7.R7SQL_PREDECESSOR_GUARD_NAME).write_bytes(old_guard)
        proof = {
            "schema_version": 1,
            "kind": "kairos.r7sql.notifier-successor-adjudication.v1",
            "predecessor_root": str(predecessor),
            "predecessor_binding_name": "binding.json",
            "predecessor_binding_sha256": hashlib.sha256(old_binding).hexdigest(),
            "predecessor_journal_name": "events.jsonl",
            "predecessor_journal_sha256": hashlib.sha256(old_journal).hexdigest(),
            "predecessor_guard_name": r7.R7SQL_PREDECESSOR_GUARD_NAME,
            "predecessor_guard_sha256": hashlib.sha256(old_guard).hexdigest(),
            "event_id": r7.R7SQL_PREDECESSOR_EVENT_ID,
            "human_adjudication": "CONFIRMED_EVENT_ABSENT_FROM_FINAL_GROUP",
            "event_resend_authorized": False,
            "runtime_pass_receipt_sha256": "a" * 64,
            "trading_started": False,
        }
        raw = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
        signature = b"synthetic detached signature"
        (successor / r7.R7SQL_SUCCESSOR_ADJUDICATION_NAME).write_bytes(raw)
        (successor / (r7.R7SQL_SUCCESSOR_ADJUDICATION_NAME + ".asc")).write_bytes(signature)
        reader = FileReader()
        helpers = SimpleNamespace(
            R5Journal=r5.R5Journal,
            R5Error=r5.R5Error,
            _read_private=reader._read_private,
            _verify_signature=lambda _data, _signature: None,
        )
        source = {
            "helpers": helpers,
            "continuation": FakeContinuation(),
            "delivery": FakeDelivery(),
            "profile": "r7-sql",
        }
        return predecessor, source, successor, raw, signature

    def test_initializer_only_allows_uniform_checkout_line_endings(self) -> None:
        initializer = b'"""Deployment validation helpers."""\n'
        self.assertEqual(r7._initializer_source_bytes(initializer), initializer)
        self.assertEqual(
            r7._initializer_source_bytes(initializer.replace(b"\n", b"\r\n")),
            initializer,
        )
        for invalid in (b"one\r\ntwo\n", b"one\rtwo", b"\xff"):
            with (
                self.subTest(invalid=invalid),
                self.assertRaisesRegex(r7.R7Error, "DEPLOY_NAMESPACE_IMPORT_REJECTED"),
            ):
                r7._initializer_source_bytes(invalid)

    def test_r7sql_root_override_is_rejected_before_any_private_read(self) -> None:
        source = {
            "profile": "r7-sql",
            "binding": r7._binding_record("r7-sql"),
            "binding_sha256": r7._binding_sha256("r7-sql"),
        }
        with self.assertRaisesRegex(r7.R7Error, "ROOT_OVERRIDE_REJECTED"):
            r7._profile_root(source, Path("arbitrary-root"))

    def test_successor_proof_tamper_fails_before_observer_or_journal(self) -> None:
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            predecessor, source, successor, raw, signature = self._successor_fixture(
                Path(directory)
            )
            old_binding_bytes = (predecessor / "binding.json").read_bytes()
            (predecessor / "events.jsonl").write_bytes(b"tampered\n")
            callbacks: list[str] = []
            with (
                patch.object(r7, "R7SQL_PREDECESSOR_ROOT", predecessor),
                patch.object(r7, "R7SQL_PRIVATE_ROOT", successor),
                patch.object(r7, "R7SQL_SUCCESSOR_ADJUDICATION_SHA256", hashlib.sha256(raw).hexdigest()),
                patch.object(r7, "R7SQL_SUCCESSOR_ADJUDICATION_SIGNATURE_SHA256", hashlib.sha256(signature).hexdigest()),
                patch.object(r7, "R7SQL_RUNTIME_PASS_RECEIPT_SHA256", "a" * 64),
                self.assertRaisesRegex(r7.R7Error, "PREDECESSOR_EVIDENCE_CHANGED"),
            ):
                source.update(
                    binding=r7._binding_record("r7-sql"),
                    binding_sha256=r7._binding_sha256("r7-sql"),
                )
                r7.poll_once(
                    source_admitter=lambda: source,
                    observer=lambda *_args: callbacks.append("observer") or "running_fresh",
                    sender=lambda _event: callbacks.append("sender") or True,
                    journal_factory=lambda *_args, **_kwargs: callbacks.append("journal") or MemoryJournal([]),
                )
            self.assertEqual(callbacks, [])
            self.assertEqual((predecessor / "binding.json").read_bytes(), old_binding_bytes)

    def test_successor_signature_and_hash_failures_precede_all_callbacks_and_writes(
        self,
    ) -> None:
        import hashlib

        cases = (
            ("signature", "R7SQL_SUCCESSOR_ADJUDICATION_SIGNATURE_INVALID", "initialize"),
            ("receipt_hash", "R7SQL_SUCCESSOR_ADJUDICATION_HASH_MISMATCH", "poll"),
            ("signature_hash", "R7SQL_SUCCESSOR_ADJUDICATION_HASH_MISMATCH", "initialize"),
        )
        for mode, expected_error, operation in cases:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                predecessor, source, successor, raw, signature = self._successor_fixture(
                    Path(directory)
                )
                old_before = {
                    name: (predecessor / name).read_bytes()
                    for name in ("binding.json", "events.jsonl", r7.R7SQL_PREDECESSOR_GUARD_NAME)
                }
                observer_calls: list[str] = []
                journal_calls: list[str] = []

                def bad_signature(*_args: Any) -> None:
                    raise ValueError("synthetic bad signature")

                source["helpers"]._verify_signature = (
                    bad_signature if mode == "signature" else lambda *_args: None
                )
                with (
                    patch.object(r7, "R7SQL_PREDECESSOR_ROOT", predecessor),
                    patch.object(r7, "R7SQL_PRIVATE_ROOT", successor),
                    patch.object(
                        r7,
                        "R7SQL_SUCCESSOR_ADJUDICATION_SHA256",
                        ("b" * 64 if mode == "receipt_hash" else hashlib.sha256(raw).hexdigest()),
                    ),
                    patch.object(
                        r7,
                        "R7SQL_SUCCESSOR_ADJUDICATION_SIGNATURE_SHA256",
                        ("b" * 64 if mode == "signature_hash" else hashlib.sha256(signature).hexdigest()),
                    ),
                    patch.object(r7, "R7SQL_RUNTIME_PASS_RECEIPT_SHA256", "a" * 64),
                    self.assertRaisesRegex(r7.R7Error, expected_error),
                ):
                    source.update(
                        binding=r7._binding_record("r7-sql"),
                        binding_sha256=r7._binding_sha256("r7-sql"),
                    )
                    if operation == "poll":
                        r7.poll_once(
                            source_admitter=lambda: source,
                            observer=lambda *_args: observer_calls.append("observer") or "running_fresh",
                            sender=lambda _event: observer_calls.append("sender") or True,
                            journal_factory=lambda *_args, **_kwargs: journal_calls.append("journal"),
                        )
                    else:
                        with patch.object(
                            r7,
                            "R7Journal",
                            side_effect=lambda *_args, **_kwargs: journal_calls.append("journal"),
                        ):
                            r7.initialize(
                                source_admitter=lambda: source,
                                observer=lambda *_args: observer_calls.append("observer") or "running_fresh",
                            )
                self.assertEqual(observer_calls, [])
                self.assertEqual(journal_calls, [])
                self.assertEqual(
                    {entry.name for entry in successor.iterdir()},
                    {
                        r7.R7SQL_SUCCESSOR_ADJUDICATION_NAME,
                        r7.R7SQL_SUCCESSOR_ADJUDICATION_NAME + ".asc",
                    },
                )
                self.assertEqual(
                    {name: (predecessor / name).read_bytes() for name in old_before},
                    old_before,
                )

    def test_fresh_successor_baseline_and_first_poll_are_quiet(self) -> None:
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            predecessor, source, successor, raw, signature = self._successor_fixture(
                Path(directory)
            )
            observed: list[str] = []
            original_predecessor = {
                name: (predecessor / name).read_bytes()
                for name in ("binding.json", "events.jsonl", r7.R7SQL_PREDECESSOR_GUARD_NAME)
            }
            with (
                patch.object(r7, "R7SQL_PREDECESSOR_ROOT", predecessor),
                patch.object(r7, "R7SQL_PRIVATE_ROOT", successor),
                patch.object(r7, "R7SQL_SUCCESSOR_ADJUDICATION_SHA256", hashlib.sha256(raw).hexdigest()),
                patch.object(r7, "R7SQL_SUCCESSOR_ADJUDICATION_SIGNATURE_SHA256", hashlib.sha256(signature).hexdigest()),
                patch.object(r7, "R7SQL_RUNTIME_PASS_RECEIPT_SHA256", "a" * 64),
            ):
                source.update(
                    binding=r7._binding_record("r7-sql"),
                    binding_sha256=r7._binding_sha256("r7-sql"),
                )
                initialized = r7.initialize(
                    source_admitter=lambda: source,
                    observer=lambda *_args: observed.append("initialize") or "running_fresh",
                )
                self.assertEqual(initialized["state"], "running_fresh")
                baseline_rows = [
                    r7._json(line)
                    for line in (successor / "events.jsonl").read_bytes().splitlines()
                ]
                self.assertEqual(baseline_rows[0]["kind"], "baseline")
                quiet = r7.poll_once(
                    source_admitter=lambda: source,
                    observer=lambda *_args: observed.append("poll") or "running_fresh",
                    sender=lambda _event: self.fail("fresh baseline must not send"),
                )
            self.assertEqual(quiet["send_attempts"], 0)
            self.assertEqual(observed, ["initialize", "poll"])
            self.assertEqual(
                {name: (predecessor / name).read_bytes() for name in original_predecessor},
                original_predecessor,
            )

    def test_successor_initialize_refuses_nonfresh_state_before_binding_write(self) -> None:
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            predecessor, source, successor, raw, signature = self._successor_fixture(
                Path(directory)
            )
            with (
                patch.object(r7, "R7SQL_PREDECESSOR_ROOT", predecessor),
                patch.object(r7, "R7SQL_PRIVATE_ROOT", successor),
                patch.object(r7, "R7SQL_SUCCESSOR_ADJUDICATION_SHA256", hashlib.sha256(raw).hexdigest()),
                patch.object(r7, "R7SQL_SUCCESSOR_ADJUDICATION_SIGNATURE_SHA256", hashlib.sha256(signature).hexdigest()),
                patch.object(r7, "R7SQL_RUNTIME_PASS_RECEIPT_SHA256", "a" * 64),
            ):
                source.update(
                    binding=r7._binding_record("r7-sql"),
                    binding_sha256=r7._binding_sha256("r7-sql"),
                )
                with self.assertRaisesRegex(r7.R7Error, "QUIET_BASELINE_REQUIRED"):
                    r7.initialize(
                        source_admitter=lambda: source,
                        observer=lambda *_args: "running_stale",
                    )
            self.assertFalse((successor / "binding.json").exists())
            self.assertFalse((successor / "events.jsonl").exists())

    def setUp(self) -> None:
        MemoryJournal.rows = [
            {
                "schema_version": 1,
                "seq": 0,
                "kind": "baseline",
                "state": "running_fresh",
                "binding_sha256": r7._binding_sha256(),
            }
        ]

    def test_fresh_running_is_quiet_and_fail_closed_flags_are_mandatory(self) -> None:
        status = valid_status()
        self.assertEqual(r7.classify_status(status), "running_fresh")
        status["trading_started"] = True
        self.assertEqual(r7.classify_status(status), "invalid")
        status = valid_status()
        status["pending_outbox"] = 1
        self.assertEqual(r7.classify_status(status), "invalid")

    def test_stale_or_wrong_owner_status_is_not_quiet(self) -> None:
        stale = valid_status(now=datetime.now(UTC) - timedelta(seconds=31))
        self.assertEqual(r7.classify_status(stale), "running_stale")
        wrong_owner = valid_status()
        wrong_owner["owner"] = "different-owner"
        self.assertEqual(r7.classify_status(wrong_owner), "invalid")

    def test_status_reader_maps_missing_and_protected_read_failure_to_alerts(
        self,
    ) -> None:
        status = valid_status()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            source = {
                "helpers": FileReader(),
                "delivery": FakeDelivery(),
            }
            path.write_text(json.dumps(status), encoding="utf-8")
            self.assertEqual(r7.read_status(path, source=source), "running_fresh")
            path.unlink()
            self.assertEqual(r7.read_status(path, source=source), "missing")
            path.write_text(json.dumps(status), encoding="utf-8")
            source["helpers"] = FileReader(fail=True)
            self.assertEqual(r7.read_status(path, source=source), "invalid")

    def test_meta_package_initializer_is_rejected_before_import_or_git_access(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initializer = root / "development" / "ops_alerts" / "__init__.py"
            initializer.parent.mkdir(parents=True)
            initializer.write_text("# unexpected package initializer", encoding="utf-8")
            with (
                patch.object(r7, "ROOT", root),
                self.assertRaisesRegex(r7.R7Error, "META_NAMESPACE_IMPORT_REJECTED"),
            ):
                r7._verify_signed_source(object())

    def test_main_redacts_unexpected_r5_helper_errors(self) -> None:
        output = io.StringIO()
        with (
            patch.object(r7, "poll_once", side_effect=r5.R5Error("SECRET_DETAIL")),
            redirect_stdout(output),
        ):
            result = r7.main(["--poll-once", "--armed"])
        self.assertEqual(result, 2)
        self.assertIn("R7_UNEXPECTED_FAILURE", output.getvalue())
        self.assertNotIn("SECRET_DETAIL", output.getvalue())

    def test_completion_and_watermark_regressions_and_boolean_counters_are_invalid(
        self,
    ) -> None:
        for field, bad_value in (
            ("completed_inbox", 8069),
            ("completed_inbox", True),
            ("cycles", True),
            ("cycles", -1),
        ):
            with self.subTest(field=field, bad_value=bad_value):
                status = valid_status()
                status[field] = bad_value
                self.assertEqual(r7.classify_status(status), "invalid")
        status = valid_status()
        status["watermarks_ms"]["BTCUSDT"] = r7.MIN_WATERMARK_MS - 60_000
        self.assertEqual(r7.classify_status(status), "invalid")
        status = valid_status()
        status["watermarks_ms"]["BTCUSDT"] = True
        self.assertEqual(r7.classify_status(status), "invalid")

    def test_receipt_budget_exceeds_accepted_receipt_but_status_stays_bounded(
        self,
    ) -> None:
        self.assertEqual(r7.MAX_RECEIPT_BYTES, 1_048_576)
        self.assertGreater(r7.MAX_RECEIPT_BYTES, 76_821)
        self.assertEqual(r7.MAX_BYTES, 65_536)

    def test_bounded_source_pause_is_quiet_but_malformed_circuit_is_not(self) -> None:
        waiting = valid_status(state="WAITING_SOURCE_NONTRADING")
        self.assertEqual(r7.classify_status(waiting), "waiting_source_nontrading")
        waiting["source_transport"]["consecutive_timeout_rounds"] = 0
        self.assertEqual(r7.classify_status(waiting), "invalid")
        catching_up = valid_status(state="CATCHING_UP_NONTRADING")
        catching_up["state"] = "CATCHING_UP_NONTRADING"
        catching_up["source_fresh"] = False
        catching_up["source_wait_reason"] = None
        catching_up["source_transport"] = {
            "timeout_rounds": 1,
            "recoveries": 1,
            "consecutive_timeout_rounds": 0,
        }
        self.assertEqual(r7.classify_status(catching_up), "catching_up_nontrading")

    def test_r7_dns_profile_requires_real_dns_pause_telemetry_and_is_isolated(
        self,
    ) -> None:
        # The accepted/current generation emits only the original three
        # timeout counters until it has seen a DNS failure.
        current = valid_status()
        self.assertEqual(r7.classify_status(current, profile="r7-dns"), "running_fresh")
        timeout_wait = valid_status(state="WAITING_SOURCE_NONTRADING")
        self.assertEqual(
            r7.classify_status(timeout_wait, profile="r7-dns"),
            "waiting_source_nontrading",
        )

        waiting = valid_dns_status()
        self.assertEqual(
            r7.classify_status(waiting, profile="r7-dns"),
            "waiting_source_nontrading",
        )
        # The old profile rejects the expanded circuit schema; it cannot
        # silently inherit the DNS exception or share its binding identity.
        self.assertEqual(r7.classify_status(waiting), "invalid")
        self.assertNotEqual(r7._binding_record(), r7._binding_record("r7-dns"))
        self.assertNotEqual(r7._binding_sha256(), r7._binding_sha256("r7-dns"))
        self.assertNotEqual(
            r7._status_path(r7._binding_record()),
            r7._status_path(r7._binding_record("r7-dns")),
        )

        for field, bad_value in (
            ("dns_failure_rounds", 0),
            ("consecutive_dns_failure_rounds", 0),
            ("consecutive_timeout_rounds", 1),
            ("dns_failure_rounds", True),
        ):
            status = valid_dns_status()
            status["source_transport"][field] = bad_value
            self.assertEqual(r7.classify_status(status, profile="r7-dns"), "invalid")
        wrong_reason = valid_dns_status()
        wrong_reason["source_wait_reason"] = r7._SOURCE_TIMEOUT
        self.assertEqual(r7.classify_status(wrong_reason, profile="r7-dns"), "invalid")
        # A post-recovery healthy sample must be fresh and all per-symbol
        # watermarks/readiness guards remain mandatory.
        fresh = valid_dns_status(state="RUNNING_NONTRADING")
        self.assertEqual(r7.classify_status(fresh, profile="r7-dns"), "running_fresh")
        fresh["watermarks_ms"].pop("XRPUSDT")
        self.assertEqual(r7.classify_status(fresh, profile="r7-dns"), "invalid")

        # Deploy's lifecycle contract also allows a later timeout wait after
        # DNS telemetry exists, but only when the DNS streak has returned to 0.
        later_timeout = valid_dns_status(state="WAITING_SOURCE_NONTRADING")
        later_timeout["source_transport"].update(
            timeout_rounds=1,
            recoveries=1,
            consecutive_timeout_rounds=1,
            consecutive_dns_failure_rounds=0,
        )
        later_timeout["source_wait_reason"] = r7._SOURCE_TIMEOUT
        self.assertEqual(
            r7.classify_status(later_timeout, profile="r7-dns"),
            "waiting_source_nontrading",
        )

    def test_r7_sql_profile_is_isolated_and_unpinned_admission_fails_closed(self) -> None:
        sql_status = valid_status()
        sql_status["completed_inbox"] = r7._R7SQL["min_completed_inbox"]
        self.assertEqual(r7.classify_status(sql_status, profile="r7-sql"), "running_fresh")
        sql_waiting = valid_dns_status()
        sql_waiting["completed_inbox"] = r7._R7SQL["min_completed_inbox"]
        self.assertEqual(
            r7.classify_status(sql_waiting, profile="r7-sql"),
            "waiting_source_nontrading",
        )
        self.assertEqual(r7.classify_status(sql_waiting), "invalid")
        self.assertNotEqual(r7._binding_record(), r7._binding_record("r7-sql"))
        self.assertNotEqual(r7._binding_record("r7-dns"), r7._binding_record("r7-sql"))
        self.assertNotEqual(
            r7._status_path(r7._binding_record()),
            r7._status_path(r7._binding_record("r7-sql")),
        )
        self.assertNotEqual(
            r7._status_path(r7._binding_record("r7-dns")),
            r7._status_path(r7._binding_record("r7-sql")),
        )
        self.assertTrue(r7._binding_record("r7-sql")["business_signals_muted"])
        self.assertIs(r7._binding_record("r7-sql")["trading_started"], False)
        with patch.dict(r7._R7SQL, {"receipt_sha256": None}), self.assertRaisesRegex(
            r7.R7Error, "R7SQL_RECEIPT_SIGNATURE_AND_SERVE_PINS_REQUIRED"
        ):
            r7.admit_r7(helpers=object(), profile="r7-sql")

    def test_r7_sql_receipt_projection_requires_zero_execution_and_restart_progress(self) -> None:
        pins = {
            **r7._R7SQL,
            "receipt_sha256": "a" * 64,
            "signature_sha256": "b" * 64,
            "container": "c" * 64,
        }
        first = valid_status()
        first["completed_inbox"] = pins["min_completed_inbox"]
        second = valid_status(now=datetime.now(UTC) + timedelta(seconds=1))
        second["completed_inbox"] = pins["min_completed_inbox"]
        second["cycles"] = first["cycles"] + 1
        second["watermarks_ms"] = {
            symbol: first["watermarks_ms"][symbol] + 60_000 for symbol in r7.SYMBOLS
        }

        def projection(value: dict[str, Any]) -> dict[str, Any]:
            return {key: value[key] for key in (
                "owner", "state", "cycles", "watermarks_ms", "pending_outbox",
                "unresolved_inbox", "completed_inbox", "uncompleted_publications",
                "new_publications", "observed_at_utc", "PAPER_QUALIFIED",
                "ALPHA_READY", "LIVE_READY", "STRATEGY_POLICY", "trading_started",
            )}

        receipt = {
            "schema_version": 1,
            "state": "PASS_NONTRADING_SQL_CONTINUATION",
            "owner": pins["owner"],
            "work_directory": str(pins["runtime_root"] / pins["work"]),
            "deploy_root": str(r7.DEPLOY_ROOT),
            "deploy_revision": pins["source_revision"],
            "worker_sha256": pins["worker_sha256"],
            "new_serve_name": "kairos-epoch-69893dc7b7c6-serve-r7-sql-a1b2c3d4",
            "new_serve_id": pins["container"],
            "old_failed_container_id": pins["old_failed_container"],
            "old_failed_status_sha256": pins["old_failed_status_sha256"],
            "legacy_unchanged": True,
            "five_symbol_fresh_progress_proven": True,
            "all_native_queue_rows_caught_up": True,
            "execution_rows_after": 0,
            "trading_started": False,
            "orders_submitted": 0,
            "paid_calls": 0,
            "primary_migration": False,
            "automatic_retry": False,
            "readiness": {"PAPER_QUALIFIED": False, "ALPHA_READY": False, "LIVE_READY": False},
            "serve_status": projection(first),
            "restart_status": projection(second),
        }
        self.assertIs(r7._validate_r7_sql_receipt(receipt, spec=pins), receipt)
        for field, bad_value in (
            ("execution_rows_after", 1),
            ("trading_started", True),
            ("all_native_queue_rows_caught_up", False),
        ):
            invalid = dict(receipt)
            invalid[field] = bad_value
            with self.subTest(field=field), self.assertRaises(r7.R7Error):
                r7._validate_r7_sql_receipt(invalid, spec=pins)

    def test_r7_dns_poll_uses_its_own_status_and_journal_binding(self) -> None:
        source = self._source()
        source.update(
            {
                "profile": "r7-dns",
                "binding": r7._binding_record("r7-dns"),
                "binding_sha256": r7._binding_sha256("r7-dns"),
            }
        )
        MemoryJournal.rows = [
            {
                "schema_version": 1,
                "seq": 0,
                "kind": "baseline",
                "state": "waiting_source_nontrading",
                "binding_sha256": source["binding_sha256"],
            }
        ]
        observed_paths: list[Path] = []
        result = r7.poll_once(
            source_admitter=lambda: source,
            observer=lambda path, _source: (
                observed_paths.append(path) or "waiting_source_nontrading"
            ),
            sender=lambda _event: self.fail("quiet DNS wait must not send"),
            root=Path("not-used"),
            journal_factory=MemoryJournal,
        )
        self.assertEqual(result["send_attempts"], 0)
        self.assertIn("runtime-dns-recovery-20261015", str(observed_paths[0]))
        self.assertEqual(
            MemoryJournal.rows[0]["binding_sha256"], source["binding_sha256"]
        )

    def _source(self) -> dict[str, Any]:
        return {
            "helpers": SimpleNamespace(
                R5Journal=r5.R5Journal,
                R5Error=r5.R5Error,
                _read_private=FileReader()._read_private,
            ),
            "continuation": FakeContinuation(),
            "delivery": FakeDelivery(),
            "binding": r7._binding_record(),
            "binding_sha256": r7._binding_sha256(),
        }

    def _current_source(self) -> dict[str, Any]:
        binding = current_binding()
        return {
            "helpers": SimpleNamespace(
                R5Journal=r5.R5Journal,
                R5Error=r5.R5Error,
                _read_private=FileReader()._read_private,
            ),
            "continuation": FakeContinuation(),
            "delivery": FakeDelivery(),
            "profile": "current",
            "binding": binding,
            "binding_sha256": r7._binding_sha256("current", binding),
        }

    def _current_signed_evidence(self, root: Path) -> tuple[dict[str, Any], Any]:
        binding = current_binding()
        work = root / ("run-" + binding["owner"])
        report_root = root / ("host-acceptance-" + binding["host_acceptance_id"])
        work.mkdir(parents=True)
        report_root.mkdir(parents=True)
        profile = {
            "schema": "kairos.current-nontrading-profile.v1",
            "deploy_revision": binding["deploy_revision"],
            "runner_receipt_sha256": "5" * 64,
        }
        receipt = {
            "result": "PASS_NONTRADING_RUNTIME_EPOCH",
            "owner": binding["owner"],
            "schema_profile": r7.CURRENT_STATUS_SCHEMA,
            "schema_migration_count": r7.CURRENT_MIGRATION_COUNT,
            "schema_public_table_count": r7.CURRENT_PUBLIC_TABLE_COUNT,
            "trading_started": False,
            "orders_submitted": 0,
            "paid_calls": 0,
            "production_trading_qualified": False,
            "root_cause_fixed": False,
            "prior_successor_preserved": True,
            "runner_receipt_sha256": profile["runner_receipt_sha256"],
            "source_profile": profile,
        }
        receipt_raw = json.dumps(receipt, sort_keys=True).encode()
        report = {
            "schema": "kairos.current-runtime-host-acceptance.v1",
            "state": "PASS_CURRENT_NONTRADING_HOST_ACCEPTANCE",
            "owner": binding["owner"],
            "receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
            "deploy_revision": binding["deploy_revision"],
            "old_resources_preserved": True,
            "production_trading_qualified": False,
            "trading_started": False,
            "orders_submitted": 0,
            "paid_calls": 0,
        }
        report_raw = json.dumps(report, sort_keys=True).encode()
        receipt_signature = b"synthetic receipt signature"
        report_signature = b"synthetic host report signature"
        receipt_path = work / "current-runtime-receipt.json"
        report_path = report_root / "acceptance.report.json"
        receipt_path.write_bytes(receipt_raw)
        receipt_path.with_name(receipt_path.name + ".asc").write_bytes(receipt_signature)
        report_path.write_bytes(report_raw)
        report_path.with_name(report_path.name + ".asc").write_bytes(report_signature)
        binding.update(
            native_receipt_sha256=hashlib.sha256(receipt_raw).hexdigest(),
            native_receipt_signature_sha256=hashlib.sha256(receipt_signature).hexdigest(),
            host_report_sha256=hashlib.sha256(report_raw).hexdigest(),
            host_report_signature_sha256=hashlib.sha256(report_signature).hexdigest(),
        )
        helper = SimpleNamespace(
            SIGNER=r7.CURRENT_SIGNER,
            _read_private=FileReader()._read_private,
            _verify_signature=lambda _data, _signature: None,
        )
        return binding, helper

    def test_current_binding_is_signed_identity_not_a_qualification_boolean(self) -> None:
        binding = current_binding()
        self.assertEqual(r7._parse_current_binding(json.dumps(binding).encode()), binding)
        self.assertFalse(
            {"qualified", "accepted", "trading_ready", "readiness"} & set(binding)
        )
        with self.assertRaisesRegex(r7.R7Error, "CURRENT_BINDING_INVALID"):
            r7._parse_current_binding(
                json.dumps({**binding, "qualified": True}).encode()
            )
        with self.assertRaisesRegex(r7.R7Error, "CURRENT_BINDING_INVALID"):
            r7._parse_current_binding(json.dumps({**binding, "owner": "../"}).encode())

    def test_current_binding_file_requires_pinned_signer_and_detached_signature(self) -> None:
        binding = current_binding()
        raw = json.dumps(binding, sort_keys=True).encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "current-owner-binding.json"
            path.write_bytes(raw)
            path.with_name(path.name + ".asc").write_bytes(b"synthetic config signature")
            with patch.object(r7, "CURRENT_CONFIG_PATH", path):
                helper = SimpleNamespace(
                    SIGNER=r7.CURRENT_SIGNER,
                    _read_private=FileReader()._read_private,
                    _verify_signature=lambda _data, _signature: None,
                )
                actual, digest = r7._read_current_signed_binding(
                    helpers=helper, delivery=FakeDelivery()
                )
                self.assertEqual(actual, binding)
                self.assertEqual(digest, r7._binding_sha256("current", binding))
                helper.SIGNER = "0" * 40
                with self.assertRaisesRegex(
                    r7.R7Error, "CURRENT_TRUSTED_SIGNER_MISMATCH"
                ):
                    r7._read_current_signed_binding(
                        helpers=helper, delivery=FakeDelivery()
                    )
                helper.SIGNER = r7.CURRENT_SIGNER
                helper._verify_signature = lambda *_args: (_ for _ in ()).throw(
                    ValueError("synthetic signature failure")
                )
                with self.assertRaisesRegex(
                    r7.R7Error, "CURRENT_BINDING_SIGNATURE_INVALID"
                ):
                    r7._read_current_signed_binding(
                        helpers=helper, delivery=FakeDelivery()
                    )

    def test_current_native_receipt_and_host_acceptance_must_both_verify(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binding, helper = self._current_signed_evidence(root)
            with (
                patch.object(r7, "CURRENT_RUNTIME_ROOT", root),
                patch.object(r7, "CURRENT_HOST_ACCEPTANCE_ROOT", root),
            ):
                receipt, report = r7._verify_current_acceptance(
                    binding=binding, helpers=helper, delivery=FakeDelivery()
                )
                self.assertEqual(receipt["owner"], CURRENT_TEST_OWNER)
                self.assertEqual(report["receipt_sha256"], binding["native_receipt_sha256"])
                report_path = (
                    root
                    / ("host-acceptance-" + binding["host_acceptance_id"])
                    / "acceptance.report.json"
                )
                bad_report = json.loads(report_path.read_text(encoding="utf-8"))
                bad_report["deploy_revision"] = "d" * 40
                bad_raw = json.dumps(bad_report, sort_keys=True).encode()
                report_path.write_bytes(bad_raw)
                binding["host_report_sha256"] = hashlib.sha256(bad_raw).hexdigest()
                with self.assertRaisesRegex(r7.R7Error, "CURRENT_ACCEPTANCE_INVALID"):
                    r7._verify_current_acceptance(
                        binding=binding, helpers=helper, delivery=FakeDelivery()
                    )
                helper._verify_signature = lambda *_args: (_ for _ in ()).throw(
                    ValueError("synthetic invalid signature")
                )
                with self.assertRaisesRegex(
                    r7.R7Error, "CURRENT_ACCEPTANCE_SIGNATURE_INVALID"
                ):
                    r7._verify_current_acceptance(
                        binding=binding, helpers=helper, delivery=FakeDelivery()
                    )

    def test_current_admission_binds_signed_config_receipt_report_and_deploy_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binding, helper = self._current_signed_evidence(root)
            config_path = root / "current-owner-binding.json"
            config_path.write_bytes(json.dumps(binding, sort_keys=True).encode())
            config_path.with_name(config_path.name + ".asc").write_bytes(
                b"synthetic config signature"
            )
            helper._continuation = lambda: (FakeContinuation(), FakeDelivery())
            helper._git = lambda *_args: ("a" * 40).encode("ascii")
            verified: list[tuple[str, str]] = []

            def verify_source(_helpers: Any, *, profile: str, current_source_revision: str | None = None) -> None:
                verified.append((profile, current_source_revision or ""))

            with (
                patch.object(r7, "CURRENT_CONFIG_PATH", config_path),
                patch.object(r7, "CURRENT_RUNTIME_ROOT", root),
                patch.object(r7, "CURRENT_HOST_ACCEPTANCE_ROOT", root),
                patch.object(r7, "_verify_signed_source", side_effect=verify_source),
            ):
                source = r7.admit_r7(helpers=helper, profile="current")
        self.assertEqual(source["profile"], "current")
        self.assertEqual(source["binding"]["owner"], CURRENT_TEST_OWNER)
        self.assertEqual(
            source["binding_sha256"],
            r7._binding_sha256("current", source["binding"]),
        )
        self.assertEqual(
            verified, [("current", "a" * 40), ("current", CURRENT_TEST_DEPLOY_REVISION)]
        )

    def test_current_source_verification_precedes_delivery_import(self) -> None:
        calls: list[str] = []
        helper = SimpleNamespace(
            _continuation=lambda: calls.append("continuation"),
            _git=lambda *_args: ("a" * 40).encode("ascii"),
        )

        def refuse(*_args: Any, **_kwargs: Any) -> None:
            calls.append("source")
            raise r7.R7Error("SIGNED_R7_SOURCE_REQUIRED")

        with patch.object(r7, "_verify_signed_source", side_effect=refuse):
            with self.assertRaisesRegex(r7.R7Error, "SIGNED_R7_SOURCE_REQUIRED"):
                r7.admit_r7(helpers=helper, profile="current")
        self.assertEqual(calls, ["source"])

    def test_legacy_signed_source_verification_precedes_continuation_setup(self) -> None:
        calls: list[str] = []
        helper = SimpleNamespace(_continuation=lambda: calls.append("continuation"))

        def verify_source(*_args: Any, **_kwargs: Any) -> None:
            calls.append("source")
            raise r7.R7Error("SIGNED_R7_SOURCE_REQUIRED")

        with patch.object(r7, "_verify_signed_source", side_effect=verify_source):
            with self.assertRaisesRegex(r7.R7Error, "SIGNED_R7_SOURCE_REQUIRED"):
                r7.admit_r7(helpers=helper, profile="legacy")
        self.assertEqual(calls, ["source"])

    def test_current_status_uses_expected_owner_native_schema_and_120_second_clock(self) -> None:
        now = datetime.now(UTC)
        fresh = current_status(now=now)
        self.assertEqual(
            r7.classify_status(
                fresh,
                profile="current",
                expected_owner=CURRENT_TEST_OWNER,
                now=now,
            ),
            "running_fresh",
        )
        boolean_counts = current_status(now=now)
        boolean_counts["schema_migration_count"] = True
        self.assertEqual(
            r7.classify_status(
                boolean_counts,
                profile="current",
                expected_owner=CURRENT_TEST_OWNER,
                now=now,
            ),
            "invalid",
        )
        self.assertEqual(
            r7.classify_status(
                current_status(owner="d" * 32, now=now),
                profile="current",
                expected_owner=CURRENT_TEST_OWNER,
                now=now,
            ),
            "unknown_owner",
        )
        unknown_schema = current_status(now=now)
        unknown_schema["schema_profile"] = "unknown"
        self.assertEqual(
            r7.classify_status(
                unknown_schema,
                profile="current",
                expected_owner=CURRENT_TEST_OWNER,
                now=now,
            ),
            "invalid",
        )
        self.assertEqual(
            r7.classify_status(
                current_status(now=now - timedelta(seconds=121)),
                profile="current",
                expected_owner=CURRENT_TEST_OWNER,
                now=now,
            ),
            "running_stale",
        )
        self.assertEqual(
            r7.classify_status(
                current_status(now=now - timedelta(seconds=120)),
                profile="current",
                expected_owner=CURRENT_TEST_OWNER,
                now=now,
            ),
            "running_fresh",
        )
        self.assertEqual(
            r7.classify_status(
                current_status(now=now + timedelta(seconds=1)),
                profile="current",
                expected_owner=CURRENT_TEST_OWNER,
                now=now,
            ),
            "invalid",
        )
        unsafe = current_status(now=now)
        unsafe["LIVE_READY"] = True
        self.assertEqual(
            r7.classify_status(
                unsafe,
                profile="current",
                expected_owner=CURRENT_TEST_OWNER,
                now=now,
            ),
            "invalid",
        )
        failed = {
            "state": "FAILED_CLOSED",
            "owner": CURRENT_TEST_OWNER,
            "observed_at_utc": now.isoformat(),
            "mode": "serve",
            "trading_started": False,
        }
        self.assertEqual(
            r7.classify_status(
                failed,
                profile="current",
                expected_owner=CURRENT_TEST_OWNER,
                now=now,
            ),
            "failed_closed",
        )

    def test_current_status_reader_missing_and_timestamp_is_not_refreshed(self) -> None:
        source = self._current_source()
        original = datetime.now(UTC) - timedelta(seconds=121)
        status = current_status(now=original)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            self.assertEqual(r7.read_status(path, source=source), "missing")
            path.write_text(json.dumps(status), encoding="utf-8")
            self.assertEqual(r7.read_status(path, source=source), "running_stale")
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["observed_at_utc"], original.isoformat())

    def test_current_incident_recovery_and_refailure_reuse_r7_transition_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "current-v1"
            root = base / ("owner-" + CURRENT_TEST_OWNER + "-" + current_binding()["native_receipt_sha256"][:12])
            root.mkdir(parents=True)
            source = self._current_source()
            MemoryJournal.rows = []
            with patch.object(r7, "CURRENT_PRIVATE_ROOT", base):
                with patch.object(r7, "R7Journal", MemoryJournal):
                    r7.initialize(
                        source_admitter=lambda: source,
                        observer=lambda *_args: "running_fresh",
                    )
                sent: list[dict[str, Any]] = []
                for observed in ("invalid", "invalid", "running_fresh", "invalid"):
                    r7.poll_once(
                        source_admitter=lambda: source,
                        observer=lambda *_args, state=observed: state,
                        sender=lambda event: sent.append(dict(event)) is None,
                        journal_factory=MemoryJournal,
                    )
            self.assertEqual(
                [event["transition"] for event in sent],
                ["firing", "resolved", "firing"],
            )
            self.assertTrue(all("CURRENT" in event["text"] for event in sent))

    def test_current_unknown_send_is_latched_without_retry(self) -> None:
        source = self._current_source()
        attempts = 0

        def unknown(_event: dict[str, Any]) -> bool:
            nonlocal attempts
            attempts += 1
            return False

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / ("owner-" + CURRENT_TEST_OWNER + "-" + current_binding()["native_receipt_sha256"][:12])
            root.mkdir()
            journal = r7.R7Journal(
                root / "events.jsonl",
                source["continuation"],
                source["delivery"],
                source["helpers"],
                source["binding_sha256"],
            )
            with journal.locked():
                journal._append(
                    {
                        "schema_version": 1,
                        "seq": 0,
                        "kind": "baseline",
                        "state": "running_fresh",
                        "binding_sha256": source["binding_sha256"],
                    }
                )
            with patch.object(r7, "CURRENT_PRIVATE_ROOT", base):
                for _ in range(2):
                    with self.assertRaisesRegex(r7.R7Error, "R7_SEND_OUTCOME_UNKNOWN"):
                        r7.poll_once(
                            source_admitter=lambda: source,
                            observer=lambda *_args: "failed_closed",
                            sender=unknown,
                        )
        self.assertEqual(attempts, 1)

    def test_current_profile_cli_default_is_plan_only_and_does_not_arm_delivery(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(r7.main(["--profile", "current"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "PLAN_ONLY")
        self.assertEqual(result["task"], r7.CURRENT_ALERT_TASK_NAME)
        self.assertIs(result["trading_authority"], False)

    def test_current_duplicate_concurrent_polls_reserve_only_one_send(self) -> None:
        source = self._current_source()
        sends: list[dict[str, Any]] = []
        send_lock = threading.Lock()
        sender_entered = threading.Event()
        second_poll_started = threading.Event()
        results: list[dict[str, Any]] = []
        failures: list[BaseException] = []
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "current-v1"
            root = base / ("owner-" + CURRENT_TEST_OWNER + "-" + current_binding()["native_receipt_sha256"][:12])
            root.mkdir(parents=True)
            journal = r7.R7Journal(
                root / "events.jsonl",
                source["continuation"],
                source["delivery"],
                source["helpers"],
                source["binding_sha256"],
            )
            with journal.locked():
                journal._append(
                    {
                        "schema_version": 1,
                        "seq": 0,
                        "kind": "baseline",
                        "state": "running_fresh",
                        "binding_sha256": source["binding_sha256"],
                    }
                )

            def sender(event: dict[str, Any]) -> bool:
                with send_lock:
                    sends.append(dict(event))
                sender_entered.set()
                second_poll_started.wait(5)
                return True

            def poll(*, second: bool = False) -> None:
                try:
                    if second:
                        second_poll_started.set()
                    results.append(
                        r7.poll_once(
                            source_admitter=lambda: source,
                            observer=lambda *_args: "invalid",
                            sender=sender,
                        )
                    )
                except BaseException as error:  # surface thread failures to unittest.
                    failures.append(error)

            with patch.object(r7, "CURRENT_PRIVATE_ROOT", base):
                first = threading.Thread(target=poll)
                first.start()
                self.assertTrue(sender_entered.wait(5))
                second = threading.Thread(target=lambda: poll(second=True))
                second.start()
                second.join(10)
                first.join(10)
                threads = [first, second]
            self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertLessEqual(len(failures), 1)
        self.assertEqual(len(sends), 1)
        self.assertEqual(sum(result["send_attempts"] for result in results), 1)

    def test_alert_is_reserved_before_send_and_duplicate_state_is_quiet(self) -> None:
        events: list[dict[str, Any]] = []

        def sender(event: dict[str, Any]) -> bool:
            events.append(event)
            return True

        result = r7.poll_once(
            source_admitter=self._source,
            observer=lambda _path, _source: "invalid",
            sender=sender,
            root=Path("not-used"),
            journal_factory=MemoryJournal,
        )
        self.assertEqual(result["send_attempts"], 1)
        self.assertEqual(
            [row["kind"] for row in MemoryJournal.rows],
            ["baseline", "observe", "send_reserved", "send_outcome"],
        )
        self.assertIn("technical status", events[0]["text"])
        self.assertNotIn("BTCUSDT", events[0]["text"])
        second = r7.poll_once(
            source_admitter=self._source,
            observer=lambda _path, _source: "invalid",
            sender=lambda _event: self.fail("duplicate alert must not send"),
            root=Path("not-used"),
            journal_factory=MemoryJournal,
        )
        self.assertEqual(second["send_attempts"], 0)

    def test_unknown_send_is_terminal_and_never_replayed(self) -> None:
        attempts = 0

        def unknown(_event: dict[str, Any]) -> bool:
            nonlocal attempts
            attempts += 1
            return False

        kwargs = {
            "source_admitter": self._source,
            "observer": lambda _path, _source: "failed_closed",
            "sender": unknown,
            "root": Path("not-used"),
            "journal_factory": MemoryJournal,
        }
        with self.assertRaisesRegex(r7.R7Error, "R7_SEND_OUTCOME_UNKNOWN"):
            r7.poll_once(**kwargs)
        with self.assertRaisesRegex(r7.R7Error, "R7_SEND_OUTCOME_UNKNOWN"):
            r7.poll_once(**kwargs)
        self.assertEqual(attempts, 1)

    def test_valid_pause_does_not_alert_or_resolve_an_active_failure(self) -> None:
        MemoryJournal.rows = [
            MemoryJournal.rows[0],
            {"schema_version": 1, "seq": 1, "kind": "observe", "state": "invalid"},
            {
                "schema_version": 1,
                "seq": 2,
                "kind": "send_reserved",
                "event_id": "a" * 64,
                "transition": "firing",
                "state": "invalid",
            },
            {
                "schema_version": 1,
                "seq": 3,
                "kind": "send_outcome",
                "event_id": "a" * 64,
                "transition": "firing",
                "state": "invalid",
                "result": "accepted",
            },
        ]
        result = r7.poll_once(
            source_admitter=self._source,
            observer=lambda _path, _source: "waiting_source_nontrading",
            sender=lambda _event: self.fail("bounded source pause must stay quiet"),
            root=Path("not-used"),
            journal_factory=MemoryJournal,
        )
        self.assertEqual(result["send_attempts"], 0)
        self.assertEqual(MemoryJournal.rows[-1]["state"], "waiting_source_nontrading")

    def _real_journal(self, directory: str) -> r7.R7Journal:
        source = self._source()
        return r7.R7Journal(
            Path(directory) / "events.jsonl",
            source["continuation"],
            source["delivery"],
            source["helpers"],
        )

    def test_real_r5_journal_methods_reserve_unknown_and_block_restart_replay(
        self,
    ) -> None:
        source = self._source()
        attempts = 0
        with tempfile.TemporaryDirectory() as directory:
            journal = self._real_journal(directory)
            with journal.locked():
                journal._append(
                    {
                        "schema_version": 1,
                        "seq": 0,
                        "kind": "baseline",
                        "state": "running_fresh",
                        "binding_sha256": r7._binding_sha256(),
                    }
                )

            def unknown(_event: dict[str, Any]) -> bool:
                nonlocal attempts
                attempts += 1
                return False

            with self.assertRaisesRegex(r7.R7Error, "R7_SEND_OUTCOME_UNKNOWN"):
                r7.poll_once(
                    source_admitter=lambda: source,
                    observer=lambda _path, _source: "invalid",
                    sender=unknown,
                    root=Path(directory),
                )
            with self.assertRaisesRegex(r7.R7Error, "R7_SEND_OUTCOME_UNKNOWN"):
                r7.poll_once(
                    source_admitter=lambda: source,
                    observer=lambda _path, _source: "invalid",
                    sender=unknown,
                    root=Path(directory),
                )
            self.assertEqual(attempts, 1)

    def test_real_budget_refusal_precedes_guard_and_retains_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = self._real_journal(directory)
            with journal.locked():
                journal._append(
                    {
                        "schema_version": 1,
                        "seq": 0,
                        "kind": "baseline",
                        "state": "invalid",
                        "binding_sha256": r7._binding_sha256(),
                    }
                )
                original = journal.path.read_bytes()
                reservation = {
                    "schema_version": 1,
                    "seq": 1,
                    "kind": "send_reserved",
                    "event_id": "c" * 64,
                    "transition": "firing",
                    "state": "invalid",
                }
                for setting, limit in (
                    ("MAX_BYTES", len(original) + 1),
                    ("MAX_RECORDS", 2),
                ):
                    with (
                        self.subTest(setting=setting),
                        patch.object(r7, setting, limit),
                        self.assertRaisesRegex(
                            r7.R7Error, "R7_JOURNAL_LIMIT_BEFORE_GUARD"
                        ),
                    ):
                        journal._append(reservation)
                    self.assertEqual(journal.path.read_bytes(), original)
                    self.assertEqual(list(Path(directory).glob("*.guard")), [])

    def test_real_interrupted_reservation_and_corrupt_journal_fail_before_sender(
        self,
    ) -> None:
        source = self._source()
        with tempfile.TemporaryDirectory() as directory:
            journal = self._real_journal(directory)
            with journal.locked():
                journal._append(
                    {
                        "schema_version": 1,
                        "seq": 0,
                        "kind": "baseline",
                        "state": "running_fresh",
                        "binding_sha256": r7._binding_sha256(),
                    }
                )
                journal._append(
                    {
                        "schema_version": 1,
                        "seq": 1,
                        "kind": "observe",
                        "state": "invalid",
                    }
                )
                journal._append(
                    {
                        "schema_version": 1,
                        "seq": 2,
                        "kind": "send_reserved",
                        "event_id": "b" * 64,
                        "transition": "firing",
                        "state": "invalid",
                    }
                )
            sender = lambda _event: self.fail(
                "interrupted reservation must block sends"
            )
            with self.assertRaisesRegex(r7.R7Error, "R7_SEND_OUTCOME_UNKNOWN"):
                r7.poll_once(
                    source_admitter=lambda: source,
                    observer=lambda _path, _source: "running_fresh",
                    sender=sender,
                    root=Path(directory),
                )

        for bad_row in (
            {
                "schema_version": 1,
                "seq": False,
                "kind": "baseline",
                "state": "running_fresh",
                "binding_sha256": r7._binding_sha256(),
            },
            {
                "schema_version": True,
                "seq": 0,
                "kind": "baseline",
                "state": "running_fresh",
                "binding_sha256": r7._binding_sha256(),
            },
        ):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "events.jsonl"
                path.write_text(json.dumps(bad_row) + "\n", encoding="utf-8")
                with self.assertRaisesRegex(r7.R7Error, "R7_JOURNAL_INVALID"):
                    r7.poll_once(
                        source_admitter=lambda: source,
                        observer=lambda _path, _source: "invalid",
                        sender=lambda _event: self.fail(
                            "corrupt journal must block sender"
                        ),
                        root=Path(directory),
                    )


if __name__ == "__main__":
    unittest.main()
