"""Offline, synthetic tests for the isolated R5 technical notifier."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from development.ops_alerts import runtime_status_r5_notifier as r5


class _C:
    @staticmethod
    def _exclusive_fsync(path, payload):
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()

    @staticmethod
    def _set_exact_file_acl(_path):
        return None


class _Delivery:
    @staticmethod
    def _no_reparse(_path):
        return None

    @staticmethod
    def _private_acl(_path):
        return None


def _source():
    binding = {
        "schema_version": 1,
        "scope": r5.SCOPE,
        "owner": r5.OWNER,
        "task_name": r5.TASK_NAME,
        "work": "read-recovery-r5-" + "a" * 32,
        "serve_container_id": "b" * 64,
        "receipt_sha256": "c" * 64,
        "receipt_source_revision": "d" * 40,
        "deploy_revision": "e" * 40,
        "notifier_sha256": "f" * 64,
        "authorization": {
            "kind": "DIRECT_OWNER_REPAIR_AND_EXISTING_TECHNICAL_ROUTING",
            "route_sha256": r5.ROUTE_SHA256,
        },
        "trading_started": False,
    }
    raw = json.dumps(binding, sort_keys=True).encode()
    return {"binding": binding, "binding_sha256": hashlib.sha256(raw).hexdigest()}


def _obs(state):
    return SimpleNamespace(state=state, stale=False)


class R5NotifierTests(unittest.TestCase):
    def test_initial_unhealthy_status_cannot_silence_future_alerts(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(r5, "_continuation", return_value=(_C, _Delivery)),
                self.assertRaisesRegex(r5.R5Error, "HEALTHY_BASELINE_REQUIRED"),
            ):
                r5.initialize(
                    source_admitter=_source,
                    observer=lambda *_a, **_k: _obs("failed_closed"),
                    root=Path(directory),
                )
            self.assertFalse((Path(directory) / "events.jsonl").exists())

    def test_default_cli_is_plan_only_without_admission_or_files(self):
        with patch.object(r5, "admit_sources", side_effect=AssertionError("admission")):
            self.assertEqual(r5.main([]), 0)
            self.assertEqual(r5.plan()["network_calls"], 0)

    def test_mutating_modes_require_explicit_arm_before_admission(self):
        with patch.object(r5, "admit_sources", side_effect=AssertionError("admission")):
            self.assertEqual(r5.main(["--initialize"]), 2)
            self.assertEqual(r5.main(["--poll-once"]), 2)

    def test_binding_exact_scope_and_fixed_recipient(self):
        binding = _source()["binding"]
        self.assertEqual(r5._verify_binding(binding), binding)
        for field, value in (
            ("task_name", "other"),
            ("work", "../elsewhere"),
            ("owner", "0" * 32),
            ("trading_started", True),
        ):
            wrong = dict(binding)
            wrong[field] = value
            with self.assertRaisesRegex(r5.R5Error, "BINDING_INVALID"):
                r5._verify_binding(wrong)
        wrong = dict(binding)
        wrong["authorization"] = {
            "kind": "DIRECT_OWNER_REPAIR_AND_EXISTING_TECHNICAL_ROUTING",
            "route_sha256": "0" * 64,
        }
        with self.assertRaisesRegex(r5.R5Error, "BINDING_INVALID"):
            r5._verify_binding(wrong)

    def test_healthy_initial_baseline_and_duplicate_do_not_send(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _source()
            with patch.object(r5, "_continuation", return_value=(_C, _Delivery)):
                initialized = r5.initialize(
                    source_admitter=lambda: source,
                    observer=lambda *_a, **_k: _obs("running"),
                    root=root,
                )
                calls = []
                unchanged = r5.poll_once(
                    source_admitter=lambda: source,
                    observer=lambda *_a, **_k: _obs("running"),
                    sender=lambda alert: calls.append(alert) or True,
                    root=root,
                )
            self.assertEqual(initialized["status"], "BASELINE_RECORDED")
            self.assertEqual(unchanged["send_attempts"], 0)
            self.assertEqual(calls, [])

    def test_new_failure_transition_sends_once_to_fixed_group_and_dedupes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _source()
            calls = []
            with patch.object(r5, "_continuation", return_value=(_C, _Delivery)):
                r5.initialize(
                    source_admitter=lambda: source,
                    observer=lambda *_a, **_k: _obs("running"),
                    root=root,
                )
                result = r5.poll_once(
                    source_admitter=lambda: source,
                    observer=lambda *_a, **_k: _obs("failed_closed"),
                    sender=lambda alert: calls.append(alert) or True,
                    root=root,
                )
                duplicate = r5.poll_once(
                    source_admitter=lambda: source,
                    observer=lambda *_a, **_k: _obs("failed_closed"),
                    sender=lambda alert: calls.append(alert) or True,
                    root=root,
                )
            self.assertEqual(result["status"], "firing_accepted")
            self.assertEqual(duplicate["send_attempts"], 0)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["recipient_chat_id"], -1004475802889)
            self.assertIn("R5", calls[0]["text"])
            self.assertFalse(calls[0].get("trading_authority", False))

    def test_unknown_send_outcome_poisoned_no_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _source()
            with patch.object(r5, "_continuation", return_value=(_C, _Delivery)):
                r5.initialize(
                    source_admitter=lambda: source,
                    observer=lambda *_a, **_k: _obs("running"),
                    root=root,
                )
                result = r5.poll_once(
                    source_admitter=lambda: source,
                    observer=lambda *_a, **_k: _obs("failed_closed"),
                    sender=lambda _alert: False,
                    root=root,
                )
                with self.assertRaisesRegex(r5.R5Error, "SEND_OUTCOME_UNKNOWN"):
                    r5.poll_once(
                        source_admitter=lambda: source,
                        observer=lambda *_a, **_k: _obs("failed_closed"),
                        sender=lambda _alert: self.fail("must not retry"),
                        root=root,
                    )
            self.assertEqual(result["status"], "firing_outcome_unknown")

    def test_bad_to_bad_transition_does_not_repeat_alert(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _source()
            sent = []
            with patch.object(r5, "_continuation", return_value=(_C, _Delivery)):
                r5.initialize(
                    source_admitter=lambda: source,
                    observer=lambda *_a, **_k: _obs("running"),
                    root=root,
                )
                r5.poll_once(
                    source_admitter=lambda: source,
                    observer=lambda *_a, **_k: _obs("failed_closed"),
                    sender=lambda alert: sent.append(alert) or True,
                    root=root,
                )
                second_bad = r5.poll_once(
                    source_admitter=lambda: source,
                    observer=lambda *_a, **_k: _obs("invalid"),
                    sender=lambda alert: sent.append(alert) or True,
                    root=root,
                )
            self.assertEqual(second_bad["send_attempts"], 0)
            self.assertEqual(len(sent), 1)

    def test_guard_acl_failure_suppresses_send_and_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _source()
            sent = []

            class BadAcl(_C):
                @staticmethod
                def _set_exact_file_acl(path):
                    if path.name.endswith(".guard"):
                        raise OSError("synthetic acl failure")

            with patch.object(r5, "_continuation", return_value=(BadAcl, _Delivery)):
                r5.initialize(
                    source_admitter=lambda: source,
                    observer=lambda *_a, **_k: _obs("running"),
                    root=root,
                )
                with self.assertRaisesRegex(r5.R5Error, "JOURNAL_WRITE_FAILED"):
                    r5.poll_once(
                        source_admitter=lambda: source,
                        observer=lambda *_a, **_k: _obs("failed_closed"),
                        sender=lambda alert: sent.append(alert) or True,
                        root=root,
                    )
                retry = r5.poll_once(
                    source_admitter=lambda: source,
                    observer=lambda *_a, **_k: _obs("failed_closed"),
                    sender=lambda alert: sent.append(alert) or True,
                    root=root,
                )
            self.assertEqual(sent, [])
            self.assertEqual(retry["send_attempts"], 0)

    def test_baseline_is_create_only_and_binding_must_match(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _source()
            with patch.object(r5, "_continuation", return_value=(_C, _Delivery)):
                r5.initialize(
                    source_admitter=lambda: source,
                    observer=lambda *_a, **_k: _obs("running"),
                    root=root,
                )
                with self.assertRaisesRegex(r5.R5Error, "BASELINE_ALREADY_EXISTS"):
                    r5.initialize(
                        source_admitter=lambda: source,
                        observer=lambda *_a, **_k: self.fail("must not observe"),
                        root=root,
                    )
                changed = _source()
                changed["binding_sha256"] = "1" * 64
                with self.assertRaisesRegex(
                    r5.R5Error, "BASELINE_REQUIRED_OR_BINDING_CHANGED"
                ):
                    r5.poll_once(
                        source_admitter=lambda: changed,
                        observer=lambda *_a, **_k: self.fail("must not observe"),
                        root=root,
                    )


if __name__ == "__main__":
    unittest.main()
