"""Offline send-once journal and source-admission tests; transport is always fake."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

if __package__:
    from . import ops_source_feed as feed
    from . import ops_source_notifier_v1 as notifier
else:
    import ops_source_feed as feed
    import ops_source_notifier_v1 as notifier


class FakeTransport:
    def __init__(self, *, error: bool = False, entered=None, release=None):
        self.error = error
        self.entered = entered
        self.release = release
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call(self, method: str, parameters: dict[str, object]) -> dict[str, object]:
        self.calls.append((method, parameters))
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            self.release.wait(5)
        if self.error:
            raise RuntimeError("fake transport failure")
        return {"message_id": 17, "chat": {"id": notifier.OPERATIONAL_CHAT_ID}}


def _intent(
    source: feed.Source = feed.Source.VENUE_OBSERVATION,
) -> notifier.DispatchIntent:
    namespace = notifier._NAMESPACES[source]
    source_state = (
        "UNKNOWN_OUTCOME"
        if source is feed.Source.VENUE_OBSERVATION
        else "FAILED_CLOSED"
    )
    candidate = feed.normalize_event(
        feed.SourceEvent(
            source=source,
            source_state=source_state,
            source_key_sha256="b" * 64,
            observed_at_ms=int(datetime.now(UTC).timestamp() * 1000),
            recovery_kind=(
                "R7_REDIS_TRANSPORT_RECOVERY"
                if source is feed.Source.BACKUP_RESTORE
                else None
            ),
        ),
        now_ms=int(datetime.now(UTC).timestamp() * 1000),
        freshness_bound_ms=notifier.MAX_FRESHNESS_MS,
    )
    assert candidate is not None
    return notifier.DispatchIntent(
        event_id=hashlib.sha256(
            f"ops-source-notifier-v1|{namespace}|{candidate.event_id}".encode("ascii")
        ).hexdigest(),
        source=source,
        source_state=source_state,
        state=feed.State.VENUE_UNKNOWN
        if source is feed.Source.VENUE_OBSERVATION
        else feed.State.BACKUP_RESTORE_FAILED,
        severity=feed.Severity.CRITICAL,
        namespace=namespace,
        binding_sha256="a" * 64,
        source_receipt_sha256="b" * 64,
        text="[Kairos technical] Fixed safe notice. Trading remains disabled.",
        observed_at_ms=int(datetime.now(UTC).timestamp() * 1000),
    )


class SourceNotifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Exercise the real journal primitives without the workstation-only
        # native source/key/ACL admission path. Native admission has separate
        # fail-closed tests; this fixture never prepares a real transport.
        from development.ops_alerts import runtime_status_r5_notifier
        from development.ops_alerts.test_runtime_status_r6_notifier import (
            _C,
            _Delivery,
        )

        cls.helpers = runtime_status_r5_notifier
        cls.c, cls.delivery = _C, _Delivery

    def make_journal(
        self, root: Path, source: feed.Source = feed.Source.VENUE_OBSERVATION
    ):
        namespace = notifier._NAMESPACES[source]
        journal_dir = root / namespace
        journal_dir.mkdir(exist_ok=True)
        return notifier.SourceJournal(
            journal_dir / "events.jsonl",
            namespace,
            self.helpers,
            self.c,
            self.delivery,
        )

    def temp_root(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return Path(temp.name)

    def make_observer_receipt(self, root: Path) -> tuple[bytes, dict[str, object]]:
        from development.ops_alerts import evedex_venue_observer as observer
        from development.ops_alerts.test_evedex_venue_observer import _fake_fetcher

        fetcher, _calls = _fake_fetcher(bad={("BTCUSDT", "evedex"): "unknown"})
        started = datetime.now(UTC)
        plan = observer.ObservationPlan(
            duration_s=10,
            poll_interval_s=10,
            request_timeout_s=1,
            slot_deadline_s=10,
            max_response_bytes=observer.MAX_RESPONSE_BYTES,
            max_storage_bytes=observer.MAX_STORAGE_BYTES,
        )
        with mock.patch.object(
            observer,
            "QUANT_SOURCE",
            Path(os.environ.get("KAIROS_TEST_QUANT_SOURCE", str(observer.QUANT_SOURCE))),
        ):
            report = observer._execute_observation(
                authorize=True,
                output_root=root / "observer-out",
                plan=plan,
                fetcher=fetcher,
                sleep=lambda _seconds: None,
                monotonic=lambda: 0.0,
                wall_clock=lambda: started,
                make_uuid=lambda: "12345678-1234-1234-1234-123456789abc",
            )
        receipt_path = root / "observer-out" / f"run-{report['run_id']}" / "report.json"
        return receipt_path.read_bytes(), report

    def make_binding(
        self, receipt_bytes: bytes, report: dict[str, object]
    ) -> tuple[bytes, str, int]:
        receipt_hash = hashlib.sha256(receipt_bytes).hexdigest()
        observed = notifier._timestamp_ms(report["finished_at_utc"])
        binding = {
            "schema_version": 1,
            "kind": "kairos.ops-source-notifier-binding.v1",
            "source": feed.Source.VENUE_OBSERVATION.value,
            "namespace": notifier._NAMESPACES[feed.Source.VENUE_OBSERVATION],
            "receipt_locator": "run-12345678-1234-1234-1234-123456789abc/report.json",
            "receipt_sha256": receipt_hash,
            "source_key_sha256": receipt_hash,
            "source_state": "UNKNOWN_OUTCOME",
            "observed_at_ms": observed,
            "recovery_kind": None,
            "producer_fingerprint": report["observer_source_sha256"],
            "meta_revision": "d" * 40,
            "notifier_sha256": notifier._module_sha256(),
        }
        binding_bytes = json.dumps(
            binding, sort_keys=True, separators=(",", ":")
        ).encode()
        return binding_bytes, hashlib.sha256(binding_bytes).hexdigest(), observed

    def test_plan_is_no_io_and_native_requires_armed_signed_binding(self):
        self.assertEqual(notifier.plan()["status"], "PLAN_ONLY")
        self.assertEqual(notifier.plan()["journal_writes"], 0)
        self.assertEqual(notifier.main([]), 0)
        self.assertEqual(notifier.main(["--execute-once"]), 2)

    def test_business_sources_are_muted_by_default(self):
        event = feed.SourceEvent(
            source=feed.Source.CAMPAIGN,
            source_state="BUDGET_BLOCKED",
            source_key_sha256="c" * 64,
            observed_at_ms=int(datetime.now(UTC).timestamp() * 1000),
        )
        candidate = notifier.project_event(
            event,
            now_ms=event.observed_at_ms,
            freshness_bound_ms=60_000,
        )
        self.assertIsNotNone(candidate)
        self.assertFalse(candidate.enabled)

    def test_reviewed_binding_and_receipt_hash_produce_redacted_intent(self):
        receipt_bytes, report = self.make_observer_receipt(self.temp_root())
        _binding, binding_sha, _observed = self.make_binding(receipt_bytes, report)
        binding_bytes = _binding
        receipt_hash = hashlib.sha256(receipt_bytes).hexdigest()
        intent = notifier._binding_event(
            binding_bytes,
            receipt_bytes,
            binding_sha256=binding_sha,
            meta_revision="d" * 40,
            verify_binding=lambda payload, signature: (
                payload == binding_bytes and signature == b"fake-signature"
            ),
            binding_signature=b"fake-signature",
        )
        self.assertIsNotNone(intent)
        self.assertEqual(intent.namespace, "ops-source-venue-v1")
        self.assertEqual(intent.source_receipt_sha256, receipt_hash)
        self.assertNotIn('"symbols"', intent.text)
        self.assertLessEqual(len(intent.text.encode()), 512)
        self.assertFalse(intent.automatic_retry)

    def test_binding_rejects_tampered_signature_or_receipt(self):
        receipt_bytes, report = self.make_observer_receipt(self.temp_root())
        binding_bytes, binding_sha, _observed = self.make_binding(receipt_bytes, report)
        args = {
            "binding_sha256": binding_sha,
            "meta_revision": "d" * 40,
            "verify_binding": lambda _payload, _signature: False,
            "binding_signature": b"fake-signature",
        }
        with self.assertRaisesRegex(notifier.NotifierError, "SOURCE_BINDING_MISMATCH"):
            notifier._binding_event(binding_bytes, receipt_bytes, **args)
        args["verify_binding"] = lambda _payload, _signature: True
        with self.assertRaisesRegex(notifier.NotifierError, "SOURCE_BINDING_MISMATCH"):
            notifier._binding_event(binding_bytes, receipt_bytes + b" ", **args)

    def test_actual_observer_report_to_unknown_journal_is_end_to_end_no_retry(self):
        receipt_bytes, report = self.make_observer_receipt(self.temp_root())
        binding_bytes, binding_sha, _observed = self.make_binding(receipt_bytes, report)
        intent = notifier._binding_event(
            binding_bytes,
            receipt_bytes,
            binding_sha256=binding_sha,
            meta_revision="d" * 40,
            verify_binding=lambda payload, signature: (
                payload == binding_bytes and signature == b"fake-signature"
            ),
            binding_signature=b"fake-signature",
        )
        self.assertIsNotNone(intent)
        root = self.temp_root()
        transport = FakeTransport(error=True)
        result = notifier.dispatch_once(
            intent,
            journal=self.make_journal(root),
            prepare_transport=lambda: transport,
        )
        self.assertEqual(result["status"], "SEND_OUTCOME_UNKNOWN")
        with self.assertRaisesRegex(
            notifier.NotifierError, "EVENT_ALREADY_CLAIMED_NO_RESEND"
        ):
            notifier.dispatch_once(
                intent,
                journal=self.make_journal(root),
                prepare_transport=lambda: transport,
            )
        self.assertEqual(len(transport.calls), 1)

    def test_journal_byte_limit_rejects_before_creating_event_guard(self):
        root = self.temp_root()
        journal = self.make_journal(root)
        journal._append(
            {
                "schema_version": 1,
                "seq": 0,
                "kind": "baseline",
                "namespace": journal.namespace,
                "schema_sha256": notifier._JOURNAL_SCHEMA_SHA256,
            }
        )
        intent = _intent()
        current_size = len(journal._verify(journal.path))
        with (
            mock.patch.object(notifier, "MAX_JOURNAL_BYTES", current_size + 1),
            self.assertRaisesRegex(notifier.NotifierError, "JOURNAL_BYTE_LIMIT"),
        ):
            journal.reserve(intent)
        guard = journal.path.with_name(
            journal.path.name + "." + intent.event_id + ".guard"
        )
        self.assertFalse(guard.exists())

    def _mock_signed_meta_gate(self, root: Path, *, changed_source: str | None = None):
        for relative in notifier._META_EXECUTED_SOURCES:
            path = root / Path(*relative.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"working:" + relative.encode())
        (root / "adaptive_sim_unrelated_wip.py").write_text(
            "user WIP", encoding="utf-8"
        )

        def git(_repo, *args):
            if args == ("branch", "--show-current"):
                return "main"
            if args == ("show", "-s", "--format=%H %G? %GF", "HEAD"):
                return "e" * 40 + " G " + notifier.SIGNER
            if args == ("rev-parse", "origin/main"):
                return "e" * 40
            if args[:3] == ("status", "--porcelain", "--untracked-files=all"):
                self.assertIn("--", args)
                self.assertEqual(args[4:], notifier._META_EXECUTED_SOURCES)
                return ""
            self.fail(f"unexpected git request: {args!r}")

        def blob(_repo, relative):
            if relative == changed_source:
                return b"different accepted Git blob"
            return (root / Path(*relative.split("/"))).read_bytes()

        return mock.patch.object(notifier, "_git", side_effect=git), mock.patch.object(
            notifier, "_git_blob", side_effect=blob
        )

    def test_scoped_signed_meta_gate_ignores_unrelated_wip_but_exact_checks_sources(
        self,
    ):
        root = self.temp_root()
        git_patch, blob_patch = self._mock_signed_meta_gate(root)
        with (
            mock.patch.object(notifier, "META_ROOT", root),
            git_patch,
            blob_patch,
        ):
            self.assertEqual(notifier._verify_signed_main(root), "e" * 40)

    def test_executed_source_drift_blocks_before_helpers_or_binding(self):
        root = self.temp_root()
        changed = notifier._META_EXECUTED_SOURCES[0]
        git_patch, blob_patch = self._mock_signed_meta_gate(
            root, changed_source=changed
        )
        with (
            mock.patch.object(notifier, "META_ROOT", root),
            git_patch,
            blob_patch,
            mock.patch.object(notifier, "_trusted_helpers") as helpers,
            mock.patch.object(notifier, "_admit_files") as admit,
            self.assertRaisesRegex(
                notifier.NotifierError, "SIGNED_SOURCE_ADMISSION_FAILED"
            ),
        ):
            notifier._execute_once(
                notifier.BINDING_ROOT / ("a" * 64 + ".json"), "a" * 64
            )
        helpers.assert_not_called()
        admit.assert_not_called()

    def test_namespace_init_files_are_rejected_before_helper_import(self):
        for relative in (
            "development/__init__.py",
            "development/ops_alerts/__init__.py",
        ):
            with self.subTest(relative=relative):
                root = self.temp_root()
                init_file = root / Path(*relative.split("/"))
                init_file.parent.mkdir(parents=True, exist_ok=True)
                init_file.write_text("# unexpected namespace package", encoding="utf-8")
                original_path = list(notifier.sys.path)
                with (
                    mock.patch.object(notifier, "META_ROOT", root),
                    self.assertRaisesRegex(
                        notifier.NotifierError, "META_NAMESPACE_PACKAGE_BLOCKED"
                    ),
                ):
                    notifier._trusted_helpers()
                self.assertEqual(notifier.sys.path, original_path)

    def test_r7_failure_without_producer_revision_is_explicitly_inadmissible(self):
        receipt = json.dumps(
            {
                "result": "FAILED_CLOSED",
                "automatic_retry": False,
                "trading_started": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        with self.assertRaisesRegex(
            notifier.NotifierError, "SOURCE_FAILURE_REVISION_REQUIRED"
        ):
            notifier._receipt_event(feed.Source.BACKUP_RESTORE, receipt)

    def test_preflight_failure_has_no_reservation_or_send(self):
        root = self.temp_root()
        journal = self.make_journal(root)
        with self.assertRaisesRegex(
            notifier.NotifierError, "SENDER_PREFLIGHT_FAILED_NO_SEND"
        ):
            notifier.dispatch_once(
                _intent(),
                journal=journal,
                prepare_transport=lambda: (_ for _ in ()).throw(RuntimeError()),
            )
        self.assertFalse(journal.path.exists())
        self.assertFalse(journal.lease_path.exists())

    def test_accepted_event_dedupes_after_restart(self):
        root = self.temp_root()
        first = self.make_journal(root)
        transport = FakeTransport()
        result = notifier.dispatch_once(
            _intent(), journal=first, prepare_transport=lambda: transport
        )
        self.assertEqual(result["status"], "TRANSPORT_ACCEPTED")
        self.assertEqual(result["send_attempts"], 1)
        self.assertEqual(transport.calls[0][0], "sendMessage")
        self.assertEqual(transport.calls[0][1]["chat_id"], notifier.OPERATIONAL_CHAT_ID)
        self.assertTrue(transport.calls[0][1]["protect_content"])
        restarted = self.make_journal(root)
        with self.assertRaisesRegex(
            notifier.NotifierError, "EVENT_ALREADY_CLAIMED_NO_RESEND"
        ):
            notifier.dispatch_once(
                _intent(), journal=restarted, prepare_transport=lambda: transport
            )
        self.assertEqual(len(transport.calls), 1)

    def test_unknown_outcome_is_terminal_after_restart(self):
        root = self.temp_root()
        journal = self.make_journal(root)
        transport = FakeTransport(error=True)
        result = notifier.dispatch_once(
            _intent(), journal=journal, prepare_transport=lambda: transport
        )
        self.assertEqual(result["status"], "SEND_OUTCOME_UNKNOWN")
        with self.assertRaisesRegex(
            notifier.NotifierError, "EVENT_ALREADY_CLAIMED_NO_RESEND"
        ):
            notifier.dispatch_once(
                _intent(),
                journal=self.make_journal(root),
                prepare_transport=lambda: transport,
            )
        self.assertEqual(len(transport.calls), 1)

    def test_interrupted_reservation_latches_unknown_without_transport(self):
        root = self.temp_root()
        journal = self.make_journal(root)
        with journal.locked():
            journal.reserve(_intent())
        transport = FakeTransport()
        with self.assertRaisesRegex(notifier.NotifierError, "SEND_OUTCOME_UNKNOWN"):
            notifier.dispatch_once(
                _intent(),
                journal=self.make_journal(root),
                prepare_transport=lambda: transport,
            )
        self.assertEqual(len(transport.calls), 0)

    def test_corrupt_journal_blocks_before_preflight_or_send(self):
        root = self.temp_root()
        journal = self.make_journal(root)
        self.helpers._write_new(journal.path, b"not-json\n", self.c, self.delivery)
        transport = FakeTransport()
        prepared = []
        with self.assertRaisesRegex(notifier.NotifierError, "JOURNAL_INVALID"):
            notifier.dispatch_once(
                _intent(),
                journal=journal,
                prepare_transport=lambda: prepared.append(True) or transport,
            )
        self.assertFalse(prepared)
        self.assertEqual(transport.calls, [])

    def test_namespace_isolation_and_concurrent_claim(self):
        root = self.temp_root()
        intent = _intent()
        first_journal = self.make_journal(root)
        second_journal = self.make_journal(root)
        entered, release = threading.Event(), threading.Event()
        transport = FakeTransport(entered=entered, release=release)
        result: list[dict[str, object]] = []
        errors: list[Exception] = []

        def send_first():
            try:
                result.append(
                    notifier.dispatch_once(
                        intent,
                        journal=first_journal,
                        prepare_transport=lambda: transport,
                    )
                )
            except Exception as error:  # noqa: BLE001 -- transfer worker exception to the joining test thread.
                errors.append(error)

        thread = threading.Thread(target=send_first)
        thread.start()
        self.assertTrue(entered.wait(5))
        with self.assertRaisesRegex(
            notifier.NotifierError, "JOURNAL_LOCKED_OR_INVALID"
        ):
            notifier.dispatch_once(
                intent, journal=second_journal, prepare_transport=lambda: transport
            )
        release.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(len(result), 1)
        backup = self.make_journal(root, feed.Source.BACKUP_RESTORE)
        self.assertNotEqual(backup.path, first_journal.path)


if __name__ == "__main__":
    unittest.main()
