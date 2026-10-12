"""Offline tests for the bounded status notifier; no network or service use."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from development.ops_alerts import runtime_status_alerts as planner
from development.ops_alerts import runtime_status_notifier as notifier


class _Delivery:
    EXPECTED_BOT = "KairosCryptoAI_bot"

    @staticmethod
    def _no_reparse(_path):
        return None

    @staticmethod
    def _private_acl(_path):
        return None


class _Continuation:
    HANDOFF_SHA256 = "a" * 64
    HANDOFF_SOURCE_SHA256 = "c" * 64

    @staticmethod
    def _decode_token(raw):
        text = raw.decode("utf-8")
        if not text.startswith(notifier.TOKEN_PREFIX):
            raise ValueError("bad token")
        return text

    @staticmethod
    def _set_exact_file_acl(_path):
        return None

    @staticmethod
    def _exclusive_fsync(path, payload):
        fd = path.open("xb")
        with fd:
            fd.write(payload)
            fd.flush()


class _Transport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        return self.response


class RuntimeStatusNotifierTests(unittest.TestCase):
    def _handoff(self, token):
        return json.dumps(
            {
                "kind": "REVIEWED_CURRENT_TOKEN_NO_SEND_HANDOFF",
                "deploy_revision": notifier.DEPLOY_COMMIT,
                "implementation_sha256": _Continuation.HANDOFF_SOURCE_SHA256,
                "old_diagnostic_sha256": "1" * 64,
                "old_qualification_sha256": "2" * 64,
                "current_token_differs_from_previous": True,
                "current_token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                "automatic_retry": False,
                "trading_authority": False,
            }
        ).encode()

    def _owner_direction(self):
        return json.dumps(
            {
                "schema_version": 1,
                "kind": "kairos.notifications.direct-owner-direction.v1",
                "basis": "DIRECT_OWNER_REPLY_IN_CURRENT_TASK",
                "owner_reply": "direct owner reply",
                "qualification_message_seen": True,
                "qualification_message_id": notifier.CORRECTED_MESSAGE_ID,
                "qualification_receipt_sha256": notifier.CORRECTED_RESULT_SHA256,
                "temporary_chat_id": notifier.CORRECTED_CHAT_ID,
                "eventual_final_group": "NOT_REDIRECTED_OR_SELECTED_BY_THIS_RECEIPT",
                "requested_routing": notifier.OWNER_ROUTING,
                "currently_enabled_sources": ["R4_TECHNICAL_RUNTIME_STATUS"],
                "telegram_user_authenticated": False,
                "trading_authority": False,
                "qualification_authority": "NOTIFICATION_ROUTE_ONLY",
            },
            separators=(",", ":"),
        ).encode()

    def test_wrong_source_hash_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.py"
            path.write_text("untrusted = True\n", encoding="utf-8")
            with self.assertRaisesRegex(
                notifier.NotifierError, "SOURCE_ADMISSION_FAILED"
            ):
                notifier._verify_working_source(path, "0" * 64)

    def test_source_admission_failure_precedes_helper_import(self):
        def reject_source():
            raise notifier.NotifierError("SOURCE_ADMISSION_FAILED")

        with (
            patch.object(
                notifier,
                "_helpers",
                side_effect=AssertionError("helper import occurred"),
            ),
            self.assertRaisesRegex(notifier.NotifierError, "SOURCE_ADMISSION_FAILED"),
        ):
            notifier.poll_once(source_admitter=reject_source)

    def test_owner_route_and_schema_are_exact(self):
        good = self._owner_direction()
        self.assertEqual(
            notifier._parse_owner_direction(good)["requested_routing"],
            notifier.OWNER_ROUTING,
        )
        for key, wrong in (("temporary_chat_id", -1001), ("schema_version", 2)):
            bad = json.loads(good)
            bad[key] = wrong
            with self.assertRaisesRegex(
                notifier.NotifierError, "OWNER_DIRECTION_INVALID"
            ):
                notifier._parse_owner_direction(json.dumps(bad).encode())

    def test_default_cli_is_plan_only_without_source_admission(self):
        with patch.object(
            notifier, "admit_sources", side_effect=AssertionError("unexpected")
        ):
            self.assertEqual(notifier.main([]), 0)

    def test_delivery_modes_require_arm_before_any_source_check(self):
        with patch.object(
            notifier, "admit_sources", side_effect=AssertionError("unexpected")
        ):
            self.assertEqual(notifier.main(["--poll-once"]), 2)
            self.assertEqual(notifier.main(["--serve"]), 2)

    def test_stale_singleton_lease_is_retained_and_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / "notifier.lock"
            lock.write_text("old owner", encoding="ascii")
            with (
                self.assertRaisesRegex(notifier.NotifierError, "SINGLETON_BUSY"),
                notifier._lease(root, _Continuation(), _Delivery()),
            ):
                self.fail("stale lease must block")
            self.assertEqual(lock.read_text(encoding="ascii"), "old owner")

    def test_owned_lease_is_released_after_normal_poll_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with notifier._lease(root, _Continuation(), _Delivery()):
                self.assertTrue((root / "notifier.lock").exists())
            self.assertFalse((root / "notifier.lock").exists())

    def test_corrected_receipt_requires_exact_digest_and_delivery_facts(self):
        payload = json.dumps(
            {
                "kind": "kairos.telegram.corrected-chat-test.v1",
                "status": "TRANSPORT_ACCEPTED",
                "stage": "TRANSPORT_ACCEPTED",
                "corrected_test_chat_id": notifier.CORRECTED_CHAT_ID,
                "expected_bot_username": notifier.EXPECTED_BOT,
                "transport_accepted": True,
                "message_id": notifier.CORRECTED_MESSAGE_ID,
                "send_attempts": 1,
                "http_method_counts": {"getMe": 1, "getChat": 1, "sendMessage": 1},
                "implementation_sha256": notifier.CORRECTED_TEST_SHA256,
                "human_acknowledged": False,
                "automatic_retry": False,
                "trading_authority": False,
                "delivery_qualified": False,
                "operationally_qualified": False,
            },
            separators=(",", ":"),
        ).encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_bytes(payload)
            paths = {"result": path}
            with patch.object(
                notifier, "CORRECTED_RESULT_SHA256", hashlib.sha256(payload).hexdigest()
            ):
                receipt, digest = notifier.validate_corrected_receipt(
                    paths, continuation=_Continuation(), delivery=_Delivery()
                )
            self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
            self.assertEqual(receipt["message_id"], 2)
            bad = dict(receipt, corrected_test_chat_id=-100123)
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(
                notifier.NotifierError, "CORRECTED_TEST_RECEIPT_INVALID"
            ):
                notifier.validate_corrected_receipt(
                    paths, continuation=_Continuation(), delivery=_Delivery()
                )

    def test_sender_uses_fixed_recipient_protection_and_receipt_before_accept(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token_path = root / "token"
            token = notifier.TOKEN_PREFIX + "x" * 35
            token_path.write_text(token, encoding="ascii")
            transport = _Transport(
                {
                    "chat": {"id": notifier.CORRECTED_CHAT_ID},
                    "message_id": 22,
                    "date": 123456,
                }
            )
            receipts = []

            class Delivery(_Delivery):
                @staticmethod
                def TelegramTransport(_token):
                    return transport

            callback = notifier._sender_factory(
                token_path=token_path,
                delivery=Delivery(),
                continuation=_Continuation(),
                receipt_path=lambda event: root / (event + ".json"),
                expected_token_sha256=hashlib.sha256(token.encode()).hexdigest(),
            )
            alert = planner.SanitizedAlert(
                "e" * 64,
                "firing",
                "failed_closed",
                "[Kairos R4] Runtime status is unhealthy. Trading remains disabled.",
            )
            self.assertTrue(callback(alert))
            method, params = transport.calls[0]
            self.assertEqual(method, "sendMessage")
            self.assertEqual(params["chat_id"], notifier.CORRECTED_CHAT_ID)
            self.assertIs(params["protect_content"], True)
            self.assertEqual(
                params["text"],
                "[Kairos R4] Runtime status is unhealthy. Trading remains disabled.",
            )
            receipt_path = root / (alert.event_id + ".json")
            receipts.append(json.loads(receipt_path.read_text(encoding="utf-8")))
            self.assertEqual(receipts[0]["message_id"], 22)
            self.assertEqual(
                receipts[0]["recipient_chat_id"], notifier.CORRECTED_CHAT_ID
            )
            self.assertNotIn("token", receipt_path.read_text(encoding="utf-8").lower())

    def test_sender_rejects_wrong_recipient_as_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token_path = root / "token"
            token = notifier.TOKEN_PREFIX + "x" * 35
            token_path.write_text(token, encoding="ascii")
            transport = _Transport(
                {"chat": {"id": -1001}, "message_id": 22, "date": 123456}
            )

            class Delivery(_Delivery):
                @staticmethod
                def TelegramTransport(_token):
                    return transport

            callback = notifier._sender_factory(
                token_path=token_path,
                delivery=Delivery(),
                continuation=_Continuation(),
                receipt_path=lambda event: root / (event + ".json"),
                expected_token_sha256=hashlib.sha256(token.encode()).hexdigest(),
            )
            with self.assertRaisesRegex(notifier.NotifierError, "SEND_OUTCOME_UNKNOWN"):
                callback(
                    planner.SanitizedAlert(
                        "e" * 64,
                        "firing",
                        "missing",
                        "[Kairos R4] Runtime status is unhealthy. Trading remains disabled.",
                    )
                )
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(list(root.glob("*.json")), [])

    def test_sender_rejects_token_not_bound_to_handoff_before_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token_path = root / "token"
            token = notifier.TOKEN_PREFIX + "x" * 35
            token_path.write_text(token, encoding="ascii")
            transport = _Transport({})

            class Delivery(_Delivery):
                @staticmethod
                def TelegramTransport(_token):
                    return transport

            callback = notifier._sender_factory(
                token_path=token_path,
                delivery=Delivery(),
                continuation=_Continuation(),
                receipt_path=lambda event: root / (event + ".json"),
                expected_token_sha256="0" * 64,
            )
            alert = planner.SanitizedAlert(
                "e" * 64,
                "firing",
                "missing",
                "[Kairos R4] Runtime status is unhealthy. Trading remains disabled.",
            )
            with self.assertRaisesRegex(notifier.NotifierError, "TOKEN_INVALID"):
                callback(alert)
            self.assertEqual(transport.calls, [])

    def test_journal_guard_and_events_are_acl_protected_before_send_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secured = []
            verified = []

            class Continuation(_Continuation):
                @staticmethod
                def _set_exact_file_acl(path):
                    secured.append(path.name)

            class Delivery(_Delivery):
                @staticmethod
                def _private_acl(path):
                    verified.append(path.name)

            journal = notifier._journal(planner, root, Continuation(), Delivery())
            observed = SimpleNamespace(state="failed_closed", stale=False)
            sends = []
            engine = planner.RuntimeStatusAlertPlanner(
                journal=journal,
                sender=lambda alert: sends.append(alert) or True,
                observer=lambda *_args, **_kwargs: observed,
            )
            result = engine.poll_once()
            self.assertEqual(result.status, "firing_accepted")
            self.assertEqual(len(sends), 1)
            self.assertIn("events.jsonl", secured)
            self.assertTrue(any(name.endswith(".guard") for name in secured))
            self.assertTrue(all(name.startswith("events.jsonl") for name in verified))
            self.assertEqual(len(journal.read_records()), 3)

    def test_poll_once_accepted_failure_then_restart_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token_path = root / "token"
            token = notifier.TOKEN_PREFIX + "x" * 35
            token_path.write_text(token, encoding="ascii")
            handoff_path = root / "handoff.json"
            handoff_path.write_bytes(self._handoff(token))
            handoff_sha = hashlib.sha256(handoff_path.read_bytes()).hexdigest()
            response = {
                "chat": {"id": notifier.CORRECTED_CHAT_ID},
                "message_id": 23,
                "date": 123457,
            }
            transport = _Transport(response)

            class Continuation(_Continuation):
                HANDOFF = handoff_path
                HANDOFF_SHA256 = handoff_sha

            class Delivery(_Delivery):
                @staticmethod
                def TelegramTransport(_token):
                    return transport

            class Corrected:
                @staticmethod
                def _paths(_continuation, _delivery):
                    return {"result": root / "test-result.json", "token": token_path}

            route_path = root / notifier.OWNER_DIRECTION_PATH
            route_path.parent.mkdir(parents=True)
            direction_raw = self._owner_direction()
            direction_sha = hashlib.sha256(direction_raw).hexdigest()
            route_path.write_bytes(direction_raw)
            acceptance = {
                "schema_version": 1,
                "kind": "kairos.runtime-status.owner-acceptance.v1",
                "status": "RECORDED_OWNER_DIRECTION_ATTESTATION",
                "basis": "DIRECT_OWNER_REPLY_IN_CURRENT_TASK",
                "acknowledgement": notifier.ACK_TEXT,
                "acknowledgement_source": "DIRECT_OWNER_REPLY",
                "human_acknowledged": True,
                "telegram_user_authenticated": False,
                "corrected_test_receipt_sha256": notifier.CORRECTED_RESULT_SHA256,
                "chat_id": notifier.CORRECTED_CHAT_ID,
                "notifier_sha256": "b" * 64,
                "handoff_sha256": handoff_sha,
                "owner_direction_sha256": direction_sha,
                "requested_routing": notifier.OWNER_ROUTING,
                "corrected_test_message_id": notifier.CORRECTED_MESSAGE_ID,
                "corrected_test_chat_id": notifier.CORRECTED_CHAT_ID,
                "disabled_alert_classes": ["strategy", "risk", "trading"],
                "trading_authority": False,
                "created_at_utc": "2026-10-12T10:00:00+00:00",
                "routing": "temporary-corrected-group",
                "enabled_alert_classes": ["technical_runtime"],
            }
            (root / "owner-acceptance.json").write_text(
                json.dumps(acceptance), encoding="utf-8"
            )
            observer = lambda *_args, **_kwargs: SimpleNamespace(
                state="failed_closed", stale=False
            )
            real_engine = planner.RuntimeStatusAlertPlanner

            def engine_factory(*, journal, sender):
                return real_engine(journal=journal, sender=sender, observer=observer)

            with (
                patch.object(notifier, "PRIVATE_ROOT", root),
                patch.object(notifier, "ROOT", root),
                patch.object(notifier, "OWNER_DIRECTION_SHA256", direction_sha),
                patch.object(
                    notifier,
                    "OWNER_ROUTING",
                    json.loads(direction_raw)["requested_routing"],
                ),
                patch.object(
                    notifier,
                    "_helpers",
                    return_value=(planner, Continuation, Corrected, Delivery),
                ),
                patch.object(
                    notifier,
                    "validate_corrected_receipt",
                    return_value=({}, notifier.CORRECTED_RESULT_SHA256),
                ),
                patch.object(
                    planner, "RuntimeStatusAlertPlanner", side_effect=engine_factory
                ),
            ):
                first = notifier.poll_once(
                    source_admitter=lambda: {
                        "notifier_sha256": "b" * 64,
                        "owner_direction_sha256": direction_sha,
                        "requested_routing": notifier.OWNER_ROUTING,
                    }
                )
                second = notifier.poll_once(
                    source_admitter=lambda: {
                        "notifier_sha256": "b" * 64,
                        "owner_direction_sha256": direction_sha,
                        "requested_routing": notifier.OWNER_ROUTING,
                    }
                )
                ack_path = root / "owner-acceptance.json"
                for key, wrong in (("chat_id", -1001), ("schema_version", 2)):
                    invalid = dict(acceptance, **{key: wrong})
                    ack_path.write_text(json.dumps(invalid), encoding="utf-8")
                    with self.assertRaisesRegex(
                        notifier.NotifierError, "OWNER_ACCEPTANCE_INVALID"
                    ):
                        notifier.poll_once(
                            source_admitter=lambda: {
                                "notifier_sha256": "b" * 64,
                                "owner_direction_sha256": direction_sha,
                                "requested_routing": notifier.OWNER_ROUTING,
                            }
                        )
                ack_path.write_text(json.dumps(acceptance), encoding="utf-8")

            self.assertEqual(first["status"], "firing_accepted")
            self.assertEqual(first["send_attempts"], 1)
            self.assertEqual(second["status"], "quiet_incident_active")
            self.assertEqual(second["send_attempts"], 0)
            self.assertEqual(len(transport.calls), 1)
            receipts = list(root.glob("telegram-*.json"))
            self.assertEqual(len(receipts), 1)
            receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
            self.assertEqual(receipt["message_id"], 23)
            self.assertEqual(receipt["recipient_chat_id"], notifier.CORRECTED_CHAT_ID)


if __name__ == "__main__":
    unittest.main()
