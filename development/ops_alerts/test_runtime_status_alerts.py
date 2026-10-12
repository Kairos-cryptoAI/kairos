from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from runtime_status_alerts import (
    R4_OWNER,
    R4_STATUS_PATH,
    AlertJournalError,
    FileJournal,
    RuntimeStatusAlertPlanner,
    plan,
)


class FakeObserver:
    def __init__(self, *observations):
        self.observations = list(observations)
        self.calls = []

    def __call__(self, path, *, expected_owner):
        self.calls.append((path, expected_owner))
        item = self.observations.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeSender:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.alerts = []

    def __call__(self, alert):
        self.alerts.append(alert)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def observed(state: str, *, stale: bool = False):
    return SimpleNamespace(state=state, stale=stale)


class RuntimeStatusAlertTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal_path = Path(self.temp.name) / "status-alerts.jsonl"

    def planner(self, observations, outcomes):
        observer = FakeObserver(*observations)
        sender = FakeSender(*outcomes)
        planner = RuntimeStatusAlertPlanner(
            journal=FileJournal(self.journal_path), sender=sender, observer=observer
        )
        return planner, observer, sender

    def test_initial_failure_fires_once_and_unchanged_state_does_not_flood(self):
        planner, observer, sender = self.planner(
            [observed("failed_closed"), observed("failed_closed")], [True]
        )
        first = planner.poll_once()
        second = planner.poll_once()

        self.assertEqual(first.status, "firing_accepted")
        self.assertEqual(second.status, "quiet_incident_active")
        self.assertEqual(first.send_attempts, 1)
        self.assertEqual(second.send_attempts, 0)
        self.assertEqual(len(sender.alerts), 1)
        self.assertEqual(observer.calls, [(R4_STATUS_PATH, R4_OWNER)] * 2)
        guard = self.journal_path.with_name(
            self.journal_path.name + "." + first.event_id + ".guard"
        )
        self.assertTrue(guard.is_file())
        self.assertEqual(
            json.loads(guard.read_text(encoding="utf-8"))["transition"], "firing"
        )

    def test_initial_healthy_is_quiet_and_is_remembered(self):
        planner, _, sender = self.planner([observed("running")], [])

        result = planner.poll_once()

        self.assertEqual(result.status, "quiet_healthy")
        self.assertEqual(result.state, "running_fresh")
        self.assertEqual(sender.alerts, [])
        self.assertEqual(len(FileJournal(self.journal_path).read_records()), 1)

    def test_failed_closed_is_firing_even_when_its_observation_is_stale(self):
        planner, _, sender = self.planner(
            [observed("failed_closed", stale=True)], [True]
        )

        result = planner.poll_once()

        self.assertEqual(result.state, "failed_closed")
        self.assertEqual(result.status, "firing_accepted")
        self.assertEqual(len(sender.alerts), 1)

    def test_accepted_failure_then_actual_fresh_running_sends_recovery(self):
        planner, _, sender = self.planner(
            [observed("missing"), observed("running")], [True, True]
        )

        firing = planner.poll_once()
        recovery = planner.poll_once()

        self.assertEqual(firing.status, "firing_accepted")
        self.assertEqual(recovery.status, "resolved_accepted")
        self.assertEqual(
            [alert.transition for alert in sender.alerts], ["firing", "resolved"]
        )
        self.assertIn("fresh RUNNING_NONTRADING", sender.alerts[1].message)

    def test_sender_unknown_is_never_retried_and_never_resolved_automatically(self):
        planner, _, sender = self.planner(
            [observed("invalid"), observed("running"), observed("running")],
            [TimeoutError("private transport detail")],
        )

        first = planner.poll_once()
        second = planner.poll_once()
        third = planner.poll_once()

        self.assertEqual(first.status, "send_outcome_unknown")
        self.assertEqual(second.status, "send_outcome_unknown_or_unresolved")
        self.assertEqual(third.status, "send_outcome_unknown_or_unresolved")
        self.assertEqual(len(sender.alerts), 1)
        self.assertTrue(
            all(result.send_attempts <= 1 for result in (first, second, third))
        )
        self.assertEqual(len(FileJournal(self.journal_path).read_records()), 3)

    def test_restart_with_same_state_deduplicates_from_durable_journal(self):
        first, _, first_sender = self.planner([observed("running", stale=True)], [True])
        accepted = first.poll_once()
        guard = self.journal_path.with_name(
            self.journal_path.name + "." + accepted.event_id + ".guard"
        )
        guard_before = guard.read_bytes()
        second, _, second_sender = self.planner([observed("running", stale=True)], [])

        after_restart = second.poll_once()

        self.assertEqual(accepted.status, "firing_accepted")
        self.assertEqual(after_restart.status, "quiet_incident_active")
        self.assertEqual(len(first_sender.alerts), 1)
        self.assertEqual(second_sender.alerts, [])
        self.assertEqual(guard.read_bytes(), guard_before)

    def test_malformed_journal_fails_closed_without_observation_or_send(self):
        self.journal_path.write_text('{"schema_version":1}\n', encoding="utf-8")
        planner, observer, sender = self.planner([observed("failed_closed")], [True])

        result = planner.poll_once()

        self.assertEqual(result.status, "journal_blocked")
        self.assertEqual(observer.calls, [])
        self.assertEqual(sender.alerts, [])

    def test_sender_exception_is_redacted_and_payload_has_fixed_safe_fields(self):
        planner, _, sender = self.planner(
            [RuntimeError("C:\\private\\keys.txt PnL=12345 https://secret.invalid")],
            [RuntimeError("token=private endpoint=https://private.invalid")],
        )

        result = planner.poll_once()
        alert = sender.alerts[0]

        self.assertEqual(result.status, "send_outcome_unknown")
        self.assertEqual(
            set(alert.__dataclass_fields__),
            {"event_id", "transition", "state", "message"},
        )
        serialized = json.dumps(
            alert.__dict__
            if hasattr(alert, "__dict__")
            else {field: getattr(alert, field) for field in alert.__dataclass_fields__}
        )
        for private in (
            "keys.txt",
            "PnL",
            "12345",
            "secret.invalid",
            "token=",
            "private.invalid",
        ):
            self.assertNotIn(private, serialized)
        self.assertEqual(
            alert.message,
            "[Kairos R4] Runtime status is unhealthy. Trading remains disabled.",
        )

    def test_each_poll_has_at_most_one_send_and_plan_cli_claims_no_delivery(self):
        planner, _, sender = self.planner(
            [observed("failed_closed"), observed("running"), observed("running")],
            [True, True],
        )
        results = [planner.poll_once(), planner.poll_once(), planner.poll_once()]
        self.assertTrue(all(result.send_attempts in (0, 1) for result in results))
        self.assertLessEqual(max(result.send_attempts for result in results), 1)
        self.assertEqual(len(sender.alerts), 2)
        self.assertEqual(plan()["status"], "PLAN_ONLY")
        self.assertFalse(plan()["automatic_execution"])
        self.assertFalse(plan()["network_calls"])
        self.assertFalse(plan()["telegram_delivery_qualified"])

    def test_module_has_no_network_or_financial_mutation_imports(self):
        source = (
            Path(__file__)
            .with_name("runtime_status_alerts.py")
            .read_text(encoding="utf-8")
        )
        tree = ast.parse(source)
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertFalse(imported & {"socket", "requests", "httpx", "ccxt", "aiohttp"})
        self.assertNotIn("kairos_execution", imported)
        self.assertNotIn(
            "kairos_persistence", imported
        )  # only a lazy pure-reader import is used.

    def test_ambiguous_running_observation_cannot_send_false_recovery(self):
        planner, _, sender = self.planner(
            [observed("failed_closed"), SimpleNamespace(state="running", stale=None)],
            [True],
        )
        self.assertEqual(planner.poll_once().status, "firing_accepted")
        self.assertEqual(planner.poll_once().status, "quiet_incident_active")
        self.assertEqual(len(sender.alerts), 1)

    def test_outcome_write_failure_keeps_unknown_send_and_never_retries(self):
        journal = FileJournal(self.journal_path)
        planner = RuntimeStatusAlertPlanner(
            journal=journal,
            sender=FakeSender(True),
            observer=FakeObserver(observed("failed_closed")),
        )
        append = journal.append

        def write(record):
            if record["kind"] == "send_outcome":
                raise AlertJournalError("JOURNAL_WRITE_FAILED")
            append(record)

        with mock.patch.object(journal, "append", side_effect=write):
            refused = planner.poll_once()
        self.assertEqual(refused.status, "send_outcome_unknown_or_journal_failed")
        self.assertEqual(refused.send_attempts, 1)
        fresh, _, sender = self.planner([observed("running")], [])
        self.assertEqual(fresh.poll_once().status, "send_outcome_unknown_or_unresolved")
        self.assertEqual(sender.alerts, [])

    def test_private_file_checks_finish_before_the_sender(self):
        secured = set()

        def secure(path):
            secured.add(path)

        def verify(path):
            if path not in secured:
                raise AlertJournalError("PROTECTED_FILE_REQUIRED")

        journal = FileJournal(
            self.journal_path, secure_new_file=secure, verify_private_file=verify
        )

        def send(alert):
            self.assertIn(journal.path, secured)
            self.assertIn(journal.lease_path, secured)
            self.assertTrue(
                any(p.name.endswith(alert.event_id + ".guard") for p in secured)
            )
            return True

        planner = RuntimeStatusAlertPlanner(
            journal=journal,
            sender=send,
            observer=FakeObserver(observed("failed_closed")),
        )
        self.assertEqual(planner.poll_once().status, "firing_accepted")


if __name__ == "__main__":
    unittest.main()
