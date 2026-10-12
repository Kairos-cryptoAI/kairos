"""Offline safety contracts for the one-shot Telegram continuation."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import telegram_continuation as continuation


class FakeDelivery:
    EXPECTED_BOT = "KairosCryptoAI_bot"
    EXPECTED_TEST_CHAT = -100447580288


class FakeHandoff:
    BOT_PREFIX = "8898378227:"

    @classmethod
    def choose_current_token(cls, raw: str, old: str) -> str:
        matches = set(re.findall(r"[0-9]{5,20}:[A-Za-z0-9_-]{30,100}", raw))
        if len(matches) != 1:
            raise ValueError("invalid synthetic source")
        token = matches.pop()
        if token == old or not token.startswith(cls.BOT_PREFIX):
            raise ValueError("invalid synthetic source")
        return token


class FakeTransport:
    def __init__(self, token: str, responses: list[dict]):
        self.token = token
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def call(self, method: str, parameters: dict) -> dict:
        self.calls.append((method, parameters))
        return self.responses.pop(0)


class ContinuationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.root = base / "new"
        self.old_root = base / "old"
        for path in (
            self.root / "secrets",
            self.root / "receipts",
            self.old_root / "secrets",
            self.old_root / "receipts",
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.token = FakeHandoff.BOT_PREFIX + "B" * 40
        self.old_token = FakeHandoff.BOT_PREFIX + "A" * 40
        (self.root / "secrets/telegram_bot_token").write_bytes(
            (self.token + "\n").encode()
        )
        (self.old_root / "secrets/telegram_bot_token").write_bytes(
            (self.old_token + "\n").encode()
        )
        self.handoff = {
            "kind": "REVIEWED_CURRENT_TOKEN_NO_SEND_HANDOFF",
            "deploy_revision": continuation.EXPECTED_DEPLOY,
            "implementation_sha256": continuation.HANDOFF_SOURCE_SHA256,
            "old_diagnostic_sha256": continuation.OLD_DIAGNOSTIC_SHA256,
            "old_qualification_sha256": continuation.OLD_QUALIFICATION_SHA256,
            "current_token_differs_from_previous": True,
            "current_token_sha256": hashlib.sha256(self.token.encode()).hexdigest(),
            "automatic_retry": False,
            "trading_authority": False,
        }
        self.handoff_path = self.root / "receipts/handoff.json"
        self.handoff_path.write_text(json.dumps(self.handoff, sort_keys=True) + "\n")
        self.reserve_path = self.root / "receipts/reserve.json"
        self.reserve_bytes = b"R" * continuation.RESERVE_BYTES
        self.reserve_path.write_bytes(self.reserve_bytes)
        self.old_diagnostic = self.old_root / "receipts/old-diagnostic.json"
        self.old_diagnostic_bytes = b"approved-old-diagnostic"
        self.old_diagnostic.write_bytes(self.old_diagnostic_bytes)
        self.old_qualification = self.old_root / "receipts/old-qualification.jsonl"
        self.old_qualification_bytes = b"approved-old-qualification\n"
        self.old_qualification.write_bytes(self.old_qualification_bytes)
        self.guard = self.root / "receipts/new.guard"
        self.result = self.root / "receipts/new.result.json"
        self.key_source = base / "keys.txt"
        self.key_source.write_text("Current Telegram token: " + self.token + "\n")
        FakeHandoff.KEY_SOURCE = self.key_source
        self.transport: FakeTransport | None = None
        self.acl_calls: list[Path] = []
        self.source_loader = lambda: (
            FakeDelivery,
            SimpleNamespace(ReadOnlyTransport=self._transport_factory),
            FakeHandoff,
        )

    def _transport_factory(self, token: str) -> FakeTransport:
        self.transport = FakeTransport(
            token,
            [
                {
                    "ok": True,
                    "result": {
                        "id": continuation.EXPECTED_BOT_ID,
                        "is_bot": True,
                        "username": FakeDelivery.EXPECTED_BOT,
                    },
                    "http_status": 200,
                },
                {
                    "ok": True,
                    "http_status": 200,
                    "result": {
                        "id": FakeDelivery.EXPECTED_TEST_CHAT,
                        "type": "supergroup",
                        "title": "DO_NOT_SERIALIZE_PRIVATE_TITLE",
                    },
                },
            ],
        )
        return self.transport

    @staticmethod
    def _noop_path(_path: Path) -> None:
        return None

    def _run(self, *, authorize: bool = True, **overrides) -> dict:
        arguments = {
            "authorize": authorize,
            "root": self.root,
            "old_root": self.old_root,
            "handoff_path": self.handoff_path,
            "reserve_path": self.reserve_path,
            "guard_path": self.guard,
            "result_path": self.result,
            "expected_handoff_sha256": hashlib.sha256(
                self.handoff_path.read_bytes()
            ).hexdigest(),
            "expected_reserve_sha256": hashlib.sha256(self.reserve_bytes).hexdigest(),
            "expected_reserve_bytes": len(self.reserve_bytes),
            "old_diagnostic_path": self.old_diagnostic,
            "expected_old_diagnostic_sha256": hashlib.sha256(
                self.old_diagnostic_bytes
            ).hexdigest(),
            "old_qualification_path": self.old_qualification,
            "expected_old_qualification_sha256": hashlib.sha256(
                self.old_qualification_bytes
            ).hexdigest(),
            "key_source_path": self.key_source,
            "no_reparse": self._noop_path,
            "private_acl": self._private_acl,
            "set_file_acl": self._noop_path,
            "exclusive_fsync": continuation._exclusive_fsync,
            "source_loader": self.source_loader,
        }
        arguments.update(overrides)
        return continuation._continue_once(**arguments)

    def _private_acl(self, path: Path) -> None:
        self.acl_calls.append(path)

    def test_unauthorized_call_has_no_filesystem_or_transport_effect(self):
        with self.assertRaises(continuation.ContinuationError):
            self._run(authorize=False)
        self.assertFalse(self.guard.exists())
        self.assertIsNone(self.transport)
        self.assertEqual(self.acl_calls, [])

    def test_success_is_only_two_reads_and_never_serializes_chat_title(self):
        report = self._run()
        self.assertEqual(report["status"], "PASS_READ_ONLY_IDENTITY_ONLY")
        self.assertEqual(report["http_method_counts"], {"getMe": 1, "getChat": 1})
        self.assertEqual(report["send_attempts"], 0)
        self.assertFalse(report["delivery_qualified"])
        self.assertFalse(report["trading_authority"])
        self.assertFalse(report["automatic_retry"])
        self.assertTrue(self.guard.is_file())
        self.assertTrue(self.result.is_file())
        self.assertEqual(
            [method for method, _ in self.transport.calls], ["getMe", "getChat"]
        )
        self.assertNotIn("DO_NOT_SERIALIZE_PRIVATE_TITLE", self.result.read_text())
        self.assertNotIn(self.token, self.result.read_text())

    def test_bot_identity_mismatch_never_calls_get_chat(self):
        def factory(token: str) -> FakeTransport:
            self.transport = FakeTransport(
                token,
                [
                    {
                        "ok": True,
                        "result": {
                            "id": continuation.EXPECTED_BOT_ID,
                            "is_bot": True,
                            "username": "wrong",
                        },
                    }
                ],
            )
            return self.transport

        self.source_loader = lambda: (
            FakeDelivery,
            SimpleNamespace(ReadOnlyTransport=factory),
            FakeHandoff,
        )
        report = self._run()
        self.assertEqual(report["error_category"], "BOT_IDENTITY_MISMATCH")
        self.assertEqual(report["http_method_counts"], {"getMe": 1, "getChat": 0})
        self.assertEqual([method for method, _ in self.transport.calls], ["getMe"])

    def test_getme_numeric_id_mismatch_never_calls_get_chat(self):
        def factory(token: str) -> FakeTransport:
            self.transport = FakeTransport(
                token,
                [
                    {
                        "ok": True,
                        "result": {
                            "id": continuation.EXPECTED_BOT_ID + 1,
                            "is_bot": True,
                            "username": FakeDelivery.EXPECTED_BOT,
                        },
                    }
                ],
            )
            return self.transport

        self.source_loader = lambda: (
            FakeDelivery,
            SimpleNamespace(ReadOnlyTransport=factory),
            FakeHandoff,
        )
        report = self._run()
        self.assertEqual(report["error_category"], "BOT_IDENTITY_MISMATCH")
        self.assertEqual(report["http_method_counts"], {"getMe": 1, "getChat": 0})

    def test_keys_source_must_select_the_same_current_token(self):
        other = FakeHandoff.BOT_PREFIX + "C" * 40
        self.key_source.write_text("Current Telegram token: " + other + "\n")
        with self.assertRaises(continuation.ContinuationError):
            self._run()
        self.assertFalse(self.guard.exists())
        self.assertIsNone(self.transport)

    def test_handoff_schema_and_source_identity_are_exact(self):
        self.handoff["unexpected"] = "value"
        self.handoff_path.write_text(json.dumps(self.handoff, sort_keys=True) + "\n")
        with self.assertRaises(continuation.ContinuationError):
            self._run()
        self.handoff.pop("unexpected")
        self.handoff["implementation_sha256"] = "0" * 64
        self.handoff_path.write_text(json.dumps(self.handoff, sort_keys=True) + "\n")
        with self.assertRaises(continuation.ContinuationError):
            self._run()
        self.assertFalse(self.guard.exists())

    def test_signed_source_loader_mismatch_fails_before_guard(self):
        class WrongSourceHandoff(FakeHandoff):
            BOT_PREFIX = "123456789:"

        self.source_loader = lambda: (
            FakeDelivery,
            SimpleNamespace(ReadOnlyTransport=self._transport_factory),
            WrongSourceHandoff,
        )
        with self.assertRaises(continuation.ContinuationError):
            self._run()
        self.assertFalse(self.guard.exists())
        self.assertIsNone(self.transport)

    def test_reparse_path_failure_blocks_before_guard(self):
        def reject_token(path: Path) -> None:
            if path == self.root / "secrets/telegram_bot_token":
                raise OSError("reparse path")

        with self.assertRaises(continuation.ContinuationError):
            self._run(no_reparse=reject_token)
        self.assertFalse(self.guard.exists())
        self.assertIsNone(self.transport)

    def test_chat_not_found_is_blocked_without_retry_or_qualification(self):
        def factory(token: str) -> FakeTransport:
            self.transport = FakeTransport(
                token,
                [
                    {
                        "ok": True,
                        "result": {
                            "id": continuation.EXPECTED_BOT_ID,
                            "is_bot": True,
                            "username": FakeDelivery.EXPECTED_BOT,
                        },
                        "http_status": 200,
                    },
                    {
                        "ok": False,
                        "error_category": "CHAT_NOT_FOUND",
                        "api_error_code": 400,
                    },
                ],
            )
            return self.transport

        self.source_loader = lambda: (
            FakeDelivery,
            SimpleNamespace(ReadOnlyTransport=factory),
            FakeHandoff,
        )
        report = self._run()
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["error_category"], "CHAT_NOT_FOUND")
        self.assertFalse(report["chat_identity_verified"])
        self.assertFalse(report["delivery_qualified"])
        self.assertEqual(report["http_method_counts"], {"getMe": 1, "getChat": 1})
        self.assertTrue(self.guard.exists())

    def test_guard_acl_failure_prevents_transport_and_retains_guard(self):
        def reject_guard(path: Path) -> None:
            if path == self.guard:
                raise RuntimeError("PRIVATE PATH / URL MUST NOT ESCAPE")

        with self.assertRaises(continuation.ContinuationError):
            self._run(set_file_acl=reject_guard)
        self.assertTrue(self.guard.exists())
        self.assertIsNone(self.transport)
        self.assertFalse(self.result.exists())

    def test_private_acl_failure_before_guard_prevents_transport(self):
        def reject_reserve(path: Path) -> None:
            if path == self.reserve_path:
                raise RuntimeError("do not print this")

        with self.assertRaises(continuation.ContinuationError):
            self._run(private_acl=reject_reserve)
        self.assertFalse(self.guard.exists())
        self.assertIsNone(self.transport)

    def test_handoff_or_reserve_digest_mismatch_blocks_without_writes(self):
        for override in (
            {"expected_handoff_sha256": "0" * 64},
            {"expected_reserve_sha256": "1" * 64},
        ):
            with (
                self.subTest(override=override),
                self.assertRaises(continuation.ContinuationError),
            ):
                self._run(**override)
            self.assertFalse(self.guard.exists())
            self.assertIsNone(self.transport)

    def test_updated_token_must_match_handoff_and_differ_from_old(self):
        (self.old_root / "secrets/telegram_bot_token").write_bytes(
            (self.token + "\n").encode()
        )
        with self.assertRaises(continuation.ContinuationError):
            self._run()
        self.assertFalse(self.guard.exists())
        self.assertIsNone(self.transport)

    def test_previous_importer_without_final_newline_is_supported(self):
        (self.old_root / "secrets/telegram_bot_token").write_bytes(
            self.old_token.encode()
        )
        self.assertTrue(self._run()["chat_identity_verified"])

    def test_token_terminators_are_bounded_not_arbitrary_whitespace(self):
        for terminator in (b"", b"\n", b"\r\n"):
            self.assertEqual(
                continuation._decode_token(self.token.encode() + terminator), self.token
            )
        for suffix in (b"\n\n", b"\r", b" ", b"\nvalue"):
            with self.assertRaises(continuation.ContinuationError):
                continuation._decode_token(self.token.encode() + suffix)

    def test_any_prior_result_or_continuation_artifact_blocks_without_retry(self):
        (self.reserve_path.with_suffix(".result.json")).write_text("{}\n")
        with self.assertRaises(continuation.ContinuationError):
            self._run()
        (self.reserve_path.with_suffix(".result.json")).unlink()
        (self.root / "receipts/telegram-readonly-continuation-old.guard").write_text(
            "x"
        )
        with self.assertRaises(continuation.ContinuationError):
            self._run()
        self.assertIsNone(self.transport)

    def test_preexisting_exact_guard_or_result_blocks_without_transport(self):
        self.guard.write_text("existing guard")
        with self.assertRaises(continuation.ContinuationError):
            self._run()
        self.guard.unlink()
        self.result.write_text("existing result")
        with self.assertRaises(continuation.ContinuationError):
            self._run()
        self.assertIsNone(self.transport)

    def test_transport_failure_is_sanitized_and_guard_is_permanent(self):
        def factory(token: str) -> FakeTransport:
            self.transport = FakeTransport(
                token,
                [
                    {
                        "ok": False,
                        "error_category": "TRANSPORT",
                        "detail": "PRIVATE_URL_TOKEN",
                        "http_status": 503,
                        "api_error_code": 503,
                    }
                ],
            )
            return self.transport

        self.source_loader = lambda: (
            FakeDelivery,
            SimpleNamespace(ReadOnlyTransport=factory),
            FakeHandoff,
        )
        report = self._run()
        self.assertEqual(report["error_category"], "TRANSPORT")
        self.assertTrue(self.guard.exists())
        self.assertTrue(self.result.exists())
        self.assertEqual(report["http_method_counts"], {"getMe": 1, "getChat": 0})
        self.assertEqual(report["http_status"], 503)
        self.assertEqual(report["api_error_code"], 503)
        serialized = self.result.read_text()
        self.assertNotIn("PRIVATE_URL_TOKEN", serialized)
        self.assertNotIn(self.token, serialized)

    def test_parent_commit_requires_exact_signature_source_hash_and_not_head(self):
        source = b"reviewed parent source"
        completed = [
            SimpleNamespace(
                returncode=0,
                stdout=f"{continuation.PARENT_META_ID} G {continuation.EXPECTED_SIGNER}\n",
            ),
            SimpleNamespace(returncode=0, stdout=""),
            SimpleNamespace(returncode=0, stdout="123\n"),
            SimpleNamespace(returncode=0, stdout=source),
        ]
        with (
            mock.patch.object(
                continuation.subprocess, "run", side_effect=completed
            ) as run,
            mock.patch.object(
                continuation.hashlib,
                "sha256",
                return_value=SimpleNamespace(
                    hexdigest=lambda: continuation.HANDOFF_SOURCE_SHA256
                ),
            ),
        ):
            continuation._verify_parent_meta()
        self.assertEqual(run.call_count, 4)
        self.assertTrue(
            all(
                continuation.PARENT_META_ID in " ".join(call.args[0])
                for call in run.call_args_list
            )
        )

    def test_parent_meta_source_hash_mismatch_is_rejected(self):
        completed = [
            SimpleNamespace(
                returncode=0,
                stdout=f"{continuation.PARENT_META_ID} G {continuation.EXPECTED_SIGNER}\n",
            ),
            SimpleNamespace(returncode=0, stdout=""),
            SimpleNamespace(returncode=0, stdout="123\n"),
            SimpleNamespace(returncode=0, stdout=b"different signed source"),
        ]
        with (
            mock.patch.object(continuation.subprocess, "run", side_effect=completed),
            self.assertRaises(continuation.ContinuationError),
        ):
            continuation._verify_parent_meta()

    def test_numeric_api_metadata_is_strictly_filtered(self):
        report = {}
        continuation._copy_numeric_api_metadata(
            report,
            {
                "http_status": 200,
                "api_error_code": 503,
                "detail": "PRIVATE",
                "title": "PRIVATE",
            },
        )
        continuation._copy_numeric_api_metadata(
            report, {"http_status": True, "api_error_code": 700}
        )
        self.assertEqual(report, {"http_status": 200, "api_error_code": 503})

    def test_cli_plan_does_not_execute_continuation(self):
        output = io.StringIO()
        with (
            mock.patch.object(continuation, "continue_read_only") as execute,
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(continuation.main([]), 0)
        execute.assert_not_called()
        self.assertIn('"http_calls": 0', output.getvalue())

    @unittest.skipUnless(os.name == "nt", "Native Windows ACL verification")
    def test_native_file_acl_hardening_preserves_bytes_without_http(self):
        payload = b"non-secret offline ACL probe\n"
        path = self.root / "receipts/offline-acl-probe"
        continuation._exclusive_fsync(path, payload)
        continuation._set_exact_file_acl(path)
        self.assertEqual(path.read_bytes(), payload)
        self.assertIsNone(self.transport)

    @unittest.skipUnless(os.name == "nt", "Windows helper boundary")
    def test_acl_helper_has_bounded_timeout_and_inbox_modules_only(self):
        fake = SimpleNamespace(returncode=0, stdout="SAFE\n")
        with mock.patch.object(
            continuation.subprocess, "run", return_value=fake
        ) as run:
            continuation._set_exact_file_acl(self.guard)
        arguments = run.call_args.kwargs
        self.assertEqual(arguments["timeout"], 30)
        self.assertFalse(arguments["shell"])
        executable = Path(run.call_args.args[0][0])
        self.assertEqual(
            arguments["env"]["PSModulePath"], str(executable.parent / "Modules")
        )
        self.assertEqual(arguments["env"]["KAIROS_ALERT_ACL_TARGET"], str(self.guard))

    @unittest.skipUnless(os.name == "nt", "Windows helper boundary")
    def test_acl_timeout_retains_guard_and_never_contacts_transport(self):
        timeout = continuation.subprocess.TimeoutExpired("PRIVATE_UNTRUSTED_DETAIL", 30)
        with (
            mock.patch.object(continuation.subprocess, "run", side_effect=timeout),
            self.assertRaises(continuation.ContinuationError) as refused,
        ):
            self._run(set_file_acl=continuation._set_exact_file_acl)
        self.assertEqual(refused.exception.category, "ACL_VERIFICATION_FAILED")
        self.assertTrue(self.guard.exists())
        self.assertIsNone(self.transport)
        self.assertFalse(self.result.exists())


if __name__ == "__main__":
    unittest.main()
