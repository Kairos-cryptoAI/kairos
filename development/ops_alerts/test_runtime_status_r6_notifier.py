"""Offline tests for the R6 notifier; every transport is synthetic."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from development.ops_alerts import runtime_status_r5_notifier as r5
from development.ops_alerts import runtime_status_r6_notifier as r6


class _C:
    @staticmethod
    def _exclusive_fsync(path: Path, payload: bytes) -> None:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()

    @staticmethod
    def _set_exact_file_acl(_path: Path) -> None:
        return None


class _Delivery:
    @staticmethod
    def _no_reparse(_path: Path) -> None:
        return None

    @staticmethod
    def _private_acl(_path: Path) -> None:
        return None


def _source():
    binding = {"work": "read-recovery-r6-feed-" + "a" * 32}
    raw = json.dumps(binding, sort_keys=True).encode()
    return {
        "binding": binding,
        "binding_sha256": hashlib.sha256(raw).hexdigest(),
        "helpers": SimpleNamespace(
            _json=r6._json,
            R5Journal=r5.R5Journal,
            R5Error=r5.R5Error,
            _read_private=lambda path, *, maximum, delivery: path.read_bytes()[
                :maximum
            ],
            _runtime_observer=lambda *_a, **_k: SimpleNamespace(
                state="invalid", stale=False
            ),
        ),
        "continuation": _C,
        "delivery": _Delivery,
    }


def _obs(state: str):
    return SimpleNamespace(state=state, stale=False)


class _Transport:
    def __init__(self, test, root: Path, calls: list[str], *, send_error=False):
        self.test, self.root, self.calls, self.send_error = (
            test,
            root,
            calls,
            send_error,
        )

    def call(self, method, _payload):
        self.calls.append(method)
        guards = list(self.root.glob("route-qualification-*.guard"))
        self.test.assertTrue(guards, "qualification guard must exist before HTTP")
        if method == "getMe":
            return {"is_bot": True, "username": r6.EXPECTED_BOT}
        if method == "getChat":
            return {"id": r6.GROUP_ID, "type": "supergroup"}
        if self.send_error:
            raise TimeoutError("synthetic token-bearing URL must not escape")
        return {"message_id": 17, "chat": {"id": r6.GROUP_ID}}


class R6NotifierTests(unittest.TestCase):
    def test_binding_requires_explicit_absence_observation_but_never_no_send_claim(
        self,
    ):
        binding = {
            "schema_version": 1,
            "scope": r6.SCOPE,
            "owner": r6.OWNER,
            "task_name": r6.TASK_NAME,
            "work": "read-recovery-r6-feed-" + "a" * 32,
            "serve_container_id": "b" * 64,
            "receipt_sha256": "c" * 64,
            "receipt_source_revision": "d" * 40,
            "deploy_revision": "e" * 40,
            "notifier_sha256": "f" * 64,
            "route_sha256": r6.ROUTE_SHA256,
            "handoff_sha256": "1" * 64,
            "r5_binding_sha256": "2" * 64,
            "r5_journal_sha256": "3" * 64,
            "r5_guard_sha256": "4" * 64,
            "r5_event_id": "9108bcba0a8ccf8f200c2654bb323216e4a8d14f991f69b67f6b0559ded20c92",
            "owner_absence_observed": True,
            "trading_started": False,
        }
        self.assertEqual(r6._verify_binding(binding), binding)
        wrong = dict(binding, owner_absence_observed=False)
        with self.assertRaisesRegex(r6.R6Error, "BINDING_INVALID"):
            r6._verify_binding(wrong)
        self.assertNotIn("no_send", json.dumps(binding))

    def test_previous_r5_evidence_must_remain_terminal_unknown(self):
        event_id = "9108bcba0a8ccf8f200c2654bb323216e4a8d14f991f69b67f6b0559ded20c92"
        prior = {
            "scope": r5.SCOPE,
            "task_name": r5.TASK_NAME,
            "owner": r5.OWNER,
            "notifier_sha256": r5.R5_SOURCE_SHA256
            if hasattr(r5, "R5_SOURCE_SHA256")
            else r6.R5_SOURCE_SHA256,
            "trading_started": False,
        }
        rows = [
            {"seq": 0, "kind": "baseline"},
            {"seq": 1, "kind": "observe"},
            {
                "seq": 2,
                "kind": "send_reserved",
                "event_id": event_id,
                "transition": "firing",
            },
            {
                "seq": 3,
                "kind": "send_outcome",
                "event_id": event_id,
                "result": "unknown",
            },
        ]
        guard = {"event_id": event_id, "state": "failed_closed", "transition": "firing"}
        blobs = {
            "binding.json": json.dumps(prior, sort_keys=True).encode(),
            "events.jsonl": b"\n".join(
                json.dumps(row, sort_keys=True).encode() for row in rows
            )
            + b"\n",
            f"events.jsonl.{event_id}.guard": json.dumps(
                guard, sort_keys=True
            ).encode(),
        }
        hashes = {
            key: hashlib.sha256(value).hexdigest() for key, value in blobs.items()
        }
        binding = {
            "r5_event_id": event_id,
            "r5_binding_sha256": hashes["binding.json"],
            "r5_journal_sha256": hashes["events.jsonl"],
            "r5_guard_sha256": hashes[f"events.jsonl.{event_id}.guard"],
        }
        helper = SimpleNamespace(
            _read_private=lambda path, **_kwargs: blobs[path.name],
            _verify_signature=lambda *_args: None,
            _json=r6._json,
            SCOPE=r5.SCOPE,
            TASK_NAME=r5.TASK_NAME,
        )
        r6._verify_previous_r5(binding, helper, _Delivery)
        rows[3]["result"] = "accepted"
        blobs["events.jsonl"] = (
            b"\n".join(json.dumps(row, sort_keys=True).encode() for row in rows) + b"\n"
        )
        binding["r5_journal_sha256"] = hashlib.sha256(blobs["events.jsonl"]).hexdigest()
        with self.assertRaisesRegex(
            r6.R6Error, "PREVIOUS_R5_TERMINAL_UNKNOWN_REQUIRED"
        ):
            r6._verify_previous_r5(binding, helper, _Delivery)

    def test_route_qualification_uses_ordered_identity_preflight_and_one_guarded_send(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            root, calls = Path(temp), []
            source = _source()
            result = r6.qualify_route(
                source_admitter=lambda: source,
                transport_factory=lambda: _Transport(self, root, calls),
                root=root,
            )
            self.assertEqual(calls, ["getMe", "getChat", "sendMessage"])
            self.assertEqual(result["stage"], "TRANSPORT_ACCEPTED")
            self.assertEqual(result["send_attempts"], 1)
            self.assertEqual(result["message_id"], 17)
            self.assertEqual(len(list(root.glob("route-qualification-*.guard"))), 1)
            self.assertEqual(
                len(list(root.glob("route-qualification-*.receipt.json"))), 1
            )
            with self.assertRaisesRegex(
                r6.R6Error, "QUALIFICATION_ALREADY_RESERVED_OR_GUARD_FAILED"
            ):
                r6.qualify_route(
                    source_admitter=lambda: source,
                    transport_factory=lambda: self.fail("guard must prevent retry"),
                    root=root,
                )

    def test_route_qualification_preflight_precedes_guard_and_existing_guard_blocks_factory(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            root, source, factory_calls = Path(temp), _source(), []

            def fail_factory():
                factory_calls.append("constructed")
                raise OSError("synthetic local preflight failure")

            with self.assertRaises(OSError):
                r6.qualify_route(
                    source_admitter=lambda source=source: source,
                    transport_factory=fail_factory,
                    root=root,
                )
            self.assertEqual(factory_calls, ["constructed"])
            self.assertEqual(list(root.glob("route-qualification-*.guard")), [])

            event_id = hashlib.sha256(
                f"{source['binding_sha256']}|r6-route-qualification-v1".encode()
            ).hexdigest()
            for marker_index in range(3):
                with (
                    self.subTest(marker_index=marker_index),
                    tempfile.TemporaryDirectory() as marker_temp,
                ):
                    marker_root = Path(marker_temp)
                    marker_paths = r6._qualifier_paths(marker_root, event_id)
                    marker_paths[marker_index].write_bytes(b"retained")
                    with self.assertRaisesRegex(
                        r6.R6Error, "QUALIFICATION_ALREADY_RESERVED_OR_GUARD_FAILED"
                    ):
                        r6.qualify_route(
                            source_admitter=lambda source=source: source,
                            transport_factory=lambda: self.fail(
                                "existing qualification artifact must block construction"
                            ),
                            root=marker_root,
                        )
            self.assertEqual(factory_calls, ["constructed"])

    def test_unknown_send_and_receipt_persistence_failure_are_terminal_no_retry(self):
        for failure in ("http", "receipt"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root, calls = Path(temp), []
                source = _source()
                if failure == "receipt":
                    original = _C._set_exact_file_acl

                    def fail_receipt_acl(path, original=original):
                        if path.name.endswith("receipt.json"):
                            raise OSError("synthetic private persistence failure")
                        original(path)

                    source["continuation"] = SimpleNamespace(
                        _exclusive_fsync=_C._exclusive_fsync,
                        _set_exact_file_acl=fail_receipt_acl,
                    )
                with self.assertRaises(r6.R6Error):
                    r6.qualify_route(
                        source_admitter=lambda source=source: source,
                        transport_factory=lambda root=root, calls=calls, failure=failure: (
                            _Transport(self, root, calls, send_error=failure == "http")
                        ),
                        root=root,
                    )
                result_path = next(root.glob("route-qualification-*.result.json"))
                result = json.loads(result_path.read_bytes())
                self.assertEqual(result["stage"], "SEND_OUTCOME_UNKNOWN")
                self.assertEqual(result["send_attempts"], 1)
                self.assertEqual(calls, ["getMe", "getChat", "sendMessage"])
                with self.assertRaisesRegex(
                    r6.R6Error, "QUALIFICATION_ALREADY_RESERVED_OR_GUARD_FAILED"
                ):
                    r6.qualify_route(
                        source_admitter=lambda source=source: source,
                        transport_factory=lambda: self.fail("guard must prevent retry"),
                        root=root,
                    )

    def test_real_monitor_sender_with_fake_http_is_at_most_once_on_timeout_or_receipt_failure(
        self,
    ):
        for failure in ("http", "receipt"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root, calls = Path(temp), []
                source = _source()
                # Establish the distinct, accepted route qualifier through the real function.
                r6.qualify_route(
                    source_admitter=lambda source=source: source,
                    transport_factory=lambda root=root: _Transport(self, root, []),
                    root=root,
                )
                r6.initialize(
                    source_admitter=lambda source=source: source,
                    observer=lambda *_a, **_k: _obs("running"),
                    root=root,
                )
                if failure == "receipt":
                    original = _C._set_exact_file_acl

                    def fail_r6_receipt(path, original=original):
                        if path.name.startswith("r6-telegram-"):
                            raise OSError("synthetic private persistence failure")
                        original(path)

                    source["continuation"] = SimpleNamespace(
                        _exclusive_fsync=_C._exclusive_fsync,
                        _set_exact_file_acl=fail_r6_receipt,
                    )
                transport = _Transport(self, root, calls, send_error=failure == "http")
                with patch.object(r6, "_handoff_transport", return_value=transport):
                    report = r6.poll_once(
                        source_admitter=lambda source=source: source,
                        observer=lambda *_a, **_k: _obs("failed_closed"),
                        root=root,
                    )
                    self.assertEqual(report["status"], "firing_outcome_unknown")
                    with self.assertRaisesRegex(r6.R6Error, "SEND_OUTCOME_UNKNOWN"):
                        r6.poll_once(
                            source_admitter=lambda source=source: source,
                            observer=lambda *_a, **_k: _obs("failed_closed"),
                            root=root,
                        )
                self.assertEqual(calls, ["sendMessage"])
                self.assertEqual(len(list(root.glob("events.jsonl.*.guard"))), 1)

    def test_waiting_state_dedupes_and_fresh_state_resolves_through_r6_journal(self):
        with tempfile.TemporaryDirectory() as temp:
            root, source, sent = Path(temp), _source(), []
            r6.qualify_route(
                source_admitter=lambda: source,
                transport_factory=lambda: _Transport(self, root, []),
                root=root,
            )
            r6.initialize(
                source_admitter=lambda: source,
                observer=lambda *_a, **_k: _obs("running"),
                root=root,
            )
            waiting = _obs("waiting_source_nontrading")
            fired = r6.poll_once(
                source_admitter=lambda: source,
                observer=lambda *_a, **_k: waiting,
                sender=lambda alert: (
                    sent.append((alert["transition"], alert["state"])) or True
                ),
                root=root,
            )
            unchanged = r6.poll_once(
                source_admitter=lambda: source,
                observer=lambda *_a, **_k: waiting,
                sender=lambda alert: (
                    sent.append((alert["transition"], alert["state"])) or True
                ),
                root=root,
            )
            resolved = r6.poll_once(
                source_admitter=lambda: source,
                observer=lambda *_a, **_k: _obs("running"),
                sender=lambda alert: (
                    sent.append((alert["transition"], alert["state"])) or True
                ),
                root=root,
            )
            helpers = source["helpers"]
            rows = r6.R6Journal(
                root / "events.jsonl",
                source["continuation"],
                source["delivery"],
                helpers,
            ).read()
            self.assertEqual(fired["state"], "waiting_source_nontrading")
            self.assertEqual(unchanged["send_attempts"], 0)
            self.assertEqual(resolved["status"], "resolved_accepted")
            self.assertEqual(
                sent,
                [
                    ("firing", "waiting_source_nontrading"),
                    ("resolved", "running_fresh"),
                ],
            )
            self.assertTrue(
                any(
                    row.get("kind") == "observe"
                    and row.get("state") == "waiting_source_nontrading"
                    for row in rows
                )
            )
            self.assertEqual(rows[-1]["result"], "accepted")

    def test_sender_constructor_preflight_failure_precedes_observe_or_reservation(self):
        with tempfile.TemporaryDirectory() as temp:
            root, source = Path(temp), _source()
            r6.qualify_route(
                source_admitter=lambda: source,
                transport_factory=lambda: _Transport(self, root, []),
                root=root,
            )
            r6.initialize(
                source_admitter=lambda: source,
                observer=lambda *_a, **_k: _obs("running"),
                root=root,
            )
            with (
                patch.object(
                    r6,
                    "_handoff_transport",
                    side_effect=r6.R6Error("SENDER_PREFLIGHT_FAILED_NO_SEND"),
                ),
                self.assertRaisesRegex(r6.R6Error, "SENDER_PREFLIGHT_FAILED_NO_SEND"),
            ):
                r6.poll_once(
                    source_admitter=lambda: source,
                    observer=lambda *_a, **_k: _obs("failed_closed"),
                    root=root,
                )
            rows = r6.R6Journal(
                root / "events.jsonl",
                source["continuation"],
                source["delivery"],
                source["helpers"],
            ).read()
            self.assertEqual(len(rows), 1)
            self.assertEqual(list(root.glob("events.jsonl.*.guard")), [])

    def test_default_and_unarmed_cli_never_admit_or_send(self):
        with patch.object(
            r6, "admit_sources", side_effect=AssertionError("admission must not run")
        ):
            self.assertEqual(r6.main([]), 0)
            self.assertEqual(r6.main(["--qualify-route"]), 2)

    def test_known_feed_waiting_and_catching_states_are_alive_but_unhealthy(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "status.json"
            now = datetime(2026, 10, 12, 18, 0, tzinfo=UTC)
            base = {
                "owner": r6.OWNER,
                "trading_started": False,
                "PAPER_QUALIFIED": False,
                "ALPHA_READY": False,
                "LIVE_READY": False,
                "STRATEGY_POLICY": "REJECT_ALL",
                "pending_outbox": 0,
                "unresolved_inbox": 0,
                "uncompleted_publications": 0,
                "source_fresh": False,
                "source_transport": {
                    "timeout_rounds": 1,
                    "recoveries": 0,
                    "consecutive_timeout_rounds": 1,
                },
                "observed_at_utc": now.isoformat(),
            }
            path.write_text(
                json.dumps(
                    dict(
                        base,
                        state="WAITING_SOURCE_NONTRADING",
                        source_wait_reason=r6._SOURCE_TIMEOUT,
                    )
                )
            )
            observed = r6._observe_status(
                path, expected_owner=r6.OWNER, source=_source(), now=now
            )
            self.assertEqual(r6._classify(observed), "waiting_source_nontrading")
            catching = dict(
                base, state="CATCHING_UP_NONTRADING", source_wait_reason=None
            )
            catching["source_transport"] = {
                "timeout_rounds": 1,
                "recoveries": 1,
                "consecutive_timeout_rounds": 0,
            }
            path.write_text(json.dumps(catching))
            observed = r6._observe_status(
                path, expected_owner=r6.OWNER, source=_source(), now=now
            )
            self.assertEqual(r6._classify(observed), "catching_up_nontrading")
            catching["owner"] = "0" * 32
            path.write_text(json.dumps(catching))
            observed = r6._observe_status(
                path, expected_owner=r6.OWNER, source=_source(), now=now
            )
            self.assertEqual(r6._classify(observed), "invalid")

    def test_poll_default_observer_uses_r6_waiting_state_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _source()
            r6.qualify_route(
                source_admitter=lambda: source,
                transport_factory=lambda: _Transport(self, root, []),
                root=root,
            )
            r6.initialize(
                source_admitter=lambda: source,
                observer=lambda *_a, **_k: _obs("running"),
                root=root,
            )
            status_path = root / "status.json"
            now = datetime.now(UTC)
            status_path.write_text(
                json.dumps(
                    {
                        "state": "WAITING_SOURCE_NONTRADING",
                        "owner": r6.OWNER,
                        "trading_started": False,
                        "PAPER_QUALIFIED": False,
                        "ALPHA_READY": False,
                        "LIVE_READY": False,
                        "STRATEGY_POLICY": "REJECT_ALL",
                        "pending_outbox": 0,
                        "unresolved_inbox": 0,
                        "uncompleted_publications": 0,
                        "source_fresh": False,
                        "source_wait_reason": r6._SOURCE_TIMEOUT,
                        "source_transport": {
                            "timeout_rounds": 1,
                            "recoveries": 0,
                            "consecutive_timeout_rounds": 1,
                        },
                        "observed_at_utc": now.isoformat(),
                    }
                )
            )
            sent = []
            with patch.object(r6, "_status_path", return_value=status_path):
                report = r6.poll_once(
                    source_admitter=lambda: source,
                    sender=lambda alert: sent.append(alert["state"]) or True,
                    root=root,
                )
            self.assertEqual(report["state"], "waiting_source_nontrading")
            self.assertEqual(sent, ["waiting_source_nontrading"])


if __name__ == "__main__":
    unittest.main()
