from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from development.ops_alerts import runtime_status_r7_escalation as escalation
from development.ops_alerts import runtime_status_r7_notifier as r7
from development.ops_alerts import test_runtime_status_r7_notifier as support


class RuntimeStatusR7EscalationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = support.RuntimeStatusR7NotifierTests()
        self.source = self.fixture._source()

    def _journal(self, directory: str) -> r7.R7Journal:
        return r7.R7Journal(
            Path(directory) / "events.jsonl",
            self.source["continuation"],
            self.source["delivery"],
            self.source["helpers"],
            self.source["binding_sha256"],
        )

    def _baseline(self, journal: r7.R7Journal) -> None:
        with journal.locked():
            journal._append(
                {
                    "schema_version": 1,
                    "seq": 0,
                    "kind": "baseline",
                    "state": "running_fresh",
                    "binding_sha256": self.source["binding_sha256"],
                }
            )

    def _poll(self, directory: str, state: str, sender: Any) -> dict[str, Any]:
        return escalation.poll_once(
            source_admitter=lambda: self.source,
            observer=lambda _path, _source: state,
            sender=sender,
            root=Path(directory),
        )

    def test_real_journal_accepts_one_escalation_then_resolves(self) -> None:
        events: list[dict[str, Any]] = []

        def accepted(event: dict[str, Any]) -> bool:
            events.append(event)
            return True

        with tempfile.TemporaryDirectory() as directory:
            journal = self._journal(directory)
            self._baseline(journal)
            self._poll(directory, "running_stale", accepted)
            self._poll(directory, "failed_closed", accepted)
            self.assertEqual(
                [event["transition"] for event in events], ["firing", "firing"]
            )
            self.assertIn("status escalation: failed_closed", events[1]["text"])
            with journal.locked():
                outcomes = [
                    row for row in journal.read() if row["kind"] == "send_outcome"
                ]
            self.assertEqual(
                [(row["transition"], row["state"], row["result"]) for row in outcomes],
                [
                    ("firing", "running_stale", "accepted"),
                    ("firing", "failed_closed", "accepted"),
                ],
            )
            quiet = self._poll(
                directory,
                "failed_closed",
                lambda _event: self.fail("accepted escalation must not repeat"),
            )
            self.assertEqual(quiet["send_attempts"], 0)
            self._poll(directory, "running_fresh", accepted)
            self.assertEqual(events[-1]["transition"], "resolved")

    def test_unknown_escalation_and_interrupted_reservation_never_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = self._journal(directory)
            self._baseline(journal)
            self._poll(directory, "running_stale", lambda _event: True)
            attempts = 0

            def unknown(_event: dict[str, Any]) -> bool:
                nonlocal attempts
                attempts += 1
                return False

            with self.assertRaisesRegex(r7.R7Error, "R7_SEND_OUTCOME_UNKNOWN"):
                self._poll(directory, "failed_closed", unknown)
            with self.assertRaisesRegex(r7.R7Error, "R7_SEND_OUTCOME_UNKNOWN"):
                self._poll(
                    directory,
                    "failed_closed",
                    lambda _event: self.fail("unknown escalation must not replay"),
                )
            self.assertEqual(attempts, 1)

        with tempfile.TemporaryDirectory() as directory:
            journal = self._journal(directory)
            self._baseline(journal)
            self._poll(directory, "running_stale", lambda _event: True)
            with journal.locked():
                rows = journal.read()
                journal._append(
                    {
                        "schema_version": 1,
                        "seq": len(rows),
                        "kind": "observe",
                        "state": "failed_closed",
                    }
                )
                rows = journal.read()
                journal._append(
                    {
                        "schema_version": 1,
                        "seq": len(rows),
                        "kind": "send_reserved",
                        "event_id": "d" * 64,
                        "transition": "firing",
                        "state": "failed_closed",
                    }
                )
            with self.assertRaisesRegex(r7.R7Error, "R7_SEND_OUTCOME_UNKNOWN"):
                self._poll(
                    directory,
                    "failed_closed",
                    lambda _event: self.fail("interrupted escalation must not replay"),
                )

    def test_budget_refusal_precedes_guard_and_can_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = self._journal(directory)
            self._baseline(journal)
            self._poll(directory, "running_stale", lambda _event: True)
            guard_paths = set(Path(directory).glob("events.jsonl.*.guard"))
            self.assertEqual(len(guard_paths), 1)
            with (
                patch.object(r7, "MAX_RECORDS", 6),
                self.assertRaisesRegex(r7.R7Error, "R7_JOURNAL_LIMIT_BEFORE_GUARD"),
            ):
                self._poll(
                    directory,
                    "failed_closed",
                    lambda _event: self.fail("budget refusal must precede send"),
                )
            self.assertEqual(
                set(Path(directory).glob("events.jsonl.*.guard")), guard_paths
            )
            events: list[dict[str, Any]] = []
            result = self._poll(
                directory, "failed_closed", lambda event: events.append(event) or True
            )
            self.assertEqual(result["status"], "alert_accepted")
            self.assertIn("status escalation: failed_closed", events[0]["text"])


if __name__ == "__main__":
    unittest.main()
