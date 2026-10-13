from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import patch

from development.ops_alerts import runtime_status_r5_notifier as r5
from development.ops_alerts import runtime_status_r7_notifier as r7


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

    def _source(self) -> dict[str, Any]:
        return {
            "helpers": SimpleNamespace(R5Journal=r5.R5Journal, R5Error=r5.R5Error),
            "continuation": FakeContinuation(),
            "delivery": FakeDelivery(),
            "binding": r7._binding_record(),
            "binding_sha256": r7._binding_sha256(),
        }

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
