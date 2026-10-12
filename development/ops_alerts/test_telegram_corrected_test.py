"""Offline contracts for the single corrected-chat test delivery."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import telegram_continuation as continuation
import telegram_corrected_test as corrected


class FakeDelivery:
    EXPECTED_BOT = "KairosCryptoAI_bot"
    TEST_MESSAGE = "A reviewed test message."

    @staticmethod
    def canonical(value: dict) -> bytes:
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class FakeTransport:
    def __init__(self, responses: list[dict | Exception], events: list[str]):
        self.responses = list(responses)
        self.events = events
        self.calls: list[tuple[str, dict]] = []

    def call(self, method: str, parameters: dict) -> dict:
        self.events.append("http:" + method)
        self.calls.append((method, parameters))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class CorrectedTestContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "receipts").mkdir()
        self.paths = {
            "root": self.root,
            "guard": self.root / "receipts/telegram-corrected-chat-test-fixed.guard",
            "send_reserved": self.root
            / "receipts/telegram-corrected-chat-test-fixed.send-reserved.json",
            "result": self.root
            / "receipts/telegram-corrected-chat-test-fixed.result.json",
        }
        self.events: list[str] = []
        self.acl_fail_path: Path | None = None
        self.transport: FakeTransport | None = None
        self.continuation = SimpleNamespace(
            EXPECTED_BOT_ID=8898378227,
            _exclusive_fsync=self._exclusive_write,
        )
        self.handoff = object()

    def _exclusive_write(self, path: Path, payload: bytes) -> None:
        self.events.append("fsync:" + path.name)
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()

    @staticmethod
    def _noop(_path: Path) -> None:
        return None

    def _acl(self, path: Path) -> None:
        self.events.append("acl:" + path.name)
        if path == self.acl_fail_path:
            raise corrected.CorrectedTestError("ACL_VERIFICATION_FAILED")

    def _factory(self, _token: str) -> FakeTransport:
        self.transport = FakeTransport(
            [
                {
                    "id": 8898378227,
                    "is_bot": True,
                    "username": FakeDelivery.EXPECTED_BOT,
                },
                {
                    "id": corrected.CORRECTED_CHAT_ID,
                    "type": "supergroup",
                    "title": "PRIVATE_TITLE",
                },
                {
                    "chat": {"id": corrected.CORRECTED_CHAT_ID},
                    "message_id": 12,
                    "text": "PRIVATE_BODY",
                },
            ],
            self.events,
        )
        return self.transport

    def _run(
        self, *, responses: list[dict | Exception] | None = None, **changes
    ) -> dict:
        if responses is not None:
            self.transport = FakeTransport(responses, self.events)

        def factory(_token: str) -> FakeTransport:
            if self.transport is None:
                self._factory(_token)
            assert self.transport is not None
            return self.transport

        args = {
            "authorize": True,
            "continuation": self.continuation,
            "delivery": FakeDelivery,
            "handoff": self.handoff,
            "paths": self.paths,
            "no_reparse": self._noop,
            "private_acl": self._acl,
            "exclusive_fsync": self._exclusive_write,
            "set_file_acl": self._noop,
            "transport_factory": factory,
            "source_bytes": b"reviewed test controller",
        }
        args.update(changes)
        with mock.patch.object(
            corrected,
            "_read_preflight",
            return_value=(
                "synthetic-token-never-serialized",
                "a" * 64,
                "b" * 64,
                "c" * 64,
            ),
        ):
            return corrected._execute_once(**args)

    def test_exact_single_send_and_durable_reservation_before_network(self) -> None:
        report = self._run()
        self.assertEqual(report["status"], "TRANSPORT_ACCEPTED")
        self.assertEqual(
            report["http_method_counts"], {"getMe": 1, "getChat": 1, "sendMessage": 1}
        )
        self.assertEqual(report["send_attempts"], 1)
        assert self.transport is not None
        self.assertEqual(
            [m for m, _ in self.transport.calls], ["getMe", "getChat", "sendMessage"]
        )
        self.assertEqual(
            self.transport.calls[1][1], {"chat_id": corrected.CORRECTED_CHAT_ID}
        )
        self.assertEqual(
            self.transport.calls[2][1],
            {
                "chat_id": corrected.CORRECTED_CHAT_ID,
                "text": FakeDelivery.TEST_MESSAGE,
                "disable_notification": False,
                "protect_content": True,
            },
        )
        reserve_index = self.events.index("acl:" + self.paths["send_reserved"].name)
        send_index = self.events.index("http:sendMessage")
        self.assertLess(reserve_index, send_index)
        self.assertEqual(
            json.loads(self.paths["send_reserved"].read_text())["stage"],
            "SEND_RESERVED",
        )
        saved = self.paths["result"].read_text()
        self.assertNotIn("PRIVATE_TITLE", saved)
        self.assertNotIn("PRIVATE_BODY", saved)
        self.assertNotIn("synthetic-token", saved)
        self.assertFalse(report["human_acknowledged"])
        self.assertFalse(report["operationally_qualified"])

    def test_wrong_bot_id_suppresses_chat_and_send(self) -> None:
        result = self._run(
            responses=[
                {
                    "id": 8898378228,
                    "is_bot": True,
                    "username": FakeDelivery.EXPECTED_BOT,
                }
            ]
        )
        self.assertEqual(result["error_category"], "BOT_IDENTITY_MISMATCH")
        assert self.transport is not None
        self.assertEqual([m for m, _ in self.transport.calls], ["getMe"])
        self.assertFalse(self.paths["send_reserved"].exists())

    def test_wrong_chat_id_or_type_suppresses_send(self) -> None:
        result = self._run(
            responses=[
                {
                    "id": 8898378227,
                    "is_bot": True,
                    "username": FakeDelivery.EXPECTED_BOT,
                },
                {"id": corrected.OLD_CHAT_ID, "type": "supergroup"},
            ]
        )
        self.assertEqual(result["error_category"], "CHAT_IDENTITY_MISMATCH")
        assert self.transport is not None
        self.assertEqual([m for m, _ in self.transport.calls], ["getMe", "getChat"])
        self.assertEqual(
            self.transport.calls[1][1]["chat_id"], corrected.CORRECTED_CHAT_ID
        )
        self.assertFalse(self.paths["send_reserved"].exists())

    def test_acl_failure_on_reservation_retains_guard_and_never_sends(self) -> None:
        self.acl_fail_path = self.paths["send_reserved"]
        result = self._run()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["error_category"], "ACL_VERIFICATION_FAILED")
        self.assertTrue(self.paths["guard"].is_file())
        assert self.transport is not None
        self.assertEqual([m for m, _ in self.transport.calls], ["getMe", "getChat"])
        self.assertTrue(self.paths["result"].is_file())

    def test_send_exception_is_unknown_and_reentry_is_blocked(self) -> None:
        result = self._run(
            responses=[
                {
                    "id": 8898378227,
                    "is_bot": True,
                    "username": FakeDelivery.EXPECTED_BOT,
                },
                {"id": corrected.CORRECTED_CHAT_ID, "type": "group"},
                RuntimeError("PRIVATE_TOKEN_OR_RESPONSE"),
            ]
        )
        self.assertEqual(result["stage"], "SEND_OUTCOME_UNKNOWN")
        self.assertEqual(result["error_category"], "SEND_OUTCOME_UNKNOWN")
        self.assertEqual(result["send_attempts"], 1)
        self.assertNotIn("PRIVATE_TOKEN_OR_RESPONSE", self.paths["result"].read_text())
        self.transport = None
        with self.assertRaises(corrected.CorrectedTestError):
            self._run()
        self.assertIsNone(self.transport)

    def test_plan_only_has_no_effect(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(corrected.main([]), 0)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"status": "PLAN_ONLY", "http_calls": 0, "send_attempts": 0},
        )
        self.assertFalse(self.paths["guard"].exists())

    def test_unauthorized_or_preexisting_result_blocks_before_preflight(self) -> None:
        with self.assertRaises(corrected.CorrectedTestError):
            self._run(authorize=False)
        self.paths["result"].write_text("existing")
        self.transport = None
        with self.assertRaises(corrected.CorrectedTestError):
            self._run()
        self.assertIsNone(self.transport)


class CorrectedPreflightContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root, self.old = base / "new", base / "old"
        for folder in (
            self.root / "receipts",
            self.root / "secrets",
            self.old / "secrets",
        ):
            folder.mkdir(parents=True)
        self.token = "8898378227:" + "B" * 40
        old_token = "8898378227:" + "A" * 40
        self.key_source = base / "keys.txt"
        self.key_source.write_text(self.token)
        self.handoff = SimpleNamespace(
            KEY_SOURCE=self.key_source,
            BOT_PREFIX="8898378227:",
            choose_current_token=lambda raw, old: raw,
        )
        self.c = SimpleNamespace(
            NEW_ROOT=self.root,
            OLD_ROOT=self.old,
            HANDOFF=self.root / "receipts/handoff.json",
            RESERVE=self.root / "receipts/original-reserve.json",
            RESULT=self.root / "receipts/reviewed-continuation.result.json",
            GUARD=self.root / "receipts/reviewed-continuation.guard",
            _check_path=continuation._check_path,
            _digest=continuation._digest,
            _decode_token=continuation._decode_token,
            _validate_handoff=continuation._validate_handoff,
        )
        handoff = {
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
        self.c.HANDOFF.write_bytes(corrected._json_bytes(handoff))
        self.c.RESERVE.write_bytes(b"original immutable reserve\n")
        self.c.GUARD.write_bytes(b"reviewed immutable continuation guard\n")
        self.c.HANDOFF_SHA256 = hashlib.sha256(self.c.HANDOFF.read_bytes()).hexdigest()
        self.c.RESERVE_SHA256 = hashlib.sha256(self.c.RESERVE.read_bytes()).hexdigest()
        self.c.RESERVE_BYTES = self.c.RESERVE.stat().st_size
        self.guard_hash = hashlib.sha256(self.c.GUARD.read_bytes()).hexdigest()
        self.prior = {
            "kind": "kairos.telegram.readonly-continuation.v1",
            "implementation_sha256": corrected.OBSERVED_PREFLIGHT_SOURCE_SHA256,
            "guard_sha256": self.guard_hash,
            "handoff_sha256": self.c.HANDOFF_SHA256,
            "reserve_sha256": self.c.RESERVE_SHA256,
            "expected_bot_username": FakeDelivery.EXPECTED_BOT,
            "expected_test_chat_id": corrected.OLD_CHAT_ID,
            "status": "BLOCKED",
            "http_method_counts": {"getMe": 1, "getChat": 1},
            "send_attempts": 0,
            "chat_identity_verified": False,
            "delivery_qualified": False,
            "trading_authority": False,
            "automatic_retry": False,
            "error_category": "CHAT_NOT_FOUND",
        }
        self.c.RESULT.write_bytes(corrected._json_bytes(self.prior))
        self.paths = corrected._paths(self.c, FakeDelivery)
        self.paths["token"].write_bytes((self.token + "\n").encode())
        self.paths["old_token"].write_bytes(old_token.encode())

    @staticmethod
    def _noop(_path: Path) -> None:
        return None

    def _read(self, *, prior_hash: str | None = None, **overrides) -> tuple:
        arguments = {
            "paths": self.paths,
            "continuation": self.c,
            "delivery": FakeDelivery,
            "handoff": self.handoff,
            "no_reparse": self._noop,
            "private_acl": self._noop,
        }
        arguments.update(overrides)
        with (
            mock.patch.object(
                corrected,
                "OLD_FAILED_READONLY_SHA256",
                prior_hash or hashlib.sha256(self.c.RESULT.read_bytes()).hexdigest(),
            ),
            mock.patch.object(
                corrected, "OBSERVED_PREFLIGHT_GUARD_SHA256", self.guard_hash
            ),
        ):
            return corrected._read_preflight(**arguments)

    def test_uses_reviewed_continuation_result_not_original_missing_result(self):
        self.assertEqual(self.paths["prior_result"], self.c.RESULT)
        self.assertFalse(self.c.RESERVE.with_suffix(".result.json").exists())
        self.assertEqual(self._read()[0], self.token)

    def test_prior_hash_or_wrong_record_kind_blocks(self):
        with self.assertRaises(corrected.CorrectedTestError):
            self._read(prior_hash="0" * 64)
        self.prior["kind"] = "kairos.telegram.readonly-diagnostic.v1"
        self.c.RESULT.write_bytes(corrected._json_bytes(self.prior))
        with self.assertRaises(corrected.CorrectedTestError):
            self._read()

    def test_altered_guard_blocks(self):
        self.c.GUARD.write_bytes(b"changed guard")
        with self.assertRaises(corrected.CorrectedTestError):
            self._read()

    def test_owner_source_token_mismatch_blocks(self):
        self.key_source.write_text("8898378227:" + "C" * 40)
        with self.assertRaises(corrected.CorrectedTestError):
            self._read()

    def test_credential_acl_failure_blocks_before_returning_token(self):
        def reject(path: Path) -> None:
            if path == self.paths["token"]:
                raise corrected.CorrectedTestError("PROTECTED_ACL_REQUIRED")

        with self.assertRaises(corrected.CorrectedTestError):
            self._read(private_acl=reject)


if __name__ == "__main__":
    unittest.main()
