"""Create-only R6 runtime notifier. Default mode is a no-I/O plan."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(r"D:\Kairos\kairos")
DEPLOY = Path(r"D:\Kairos\kairos-deploy")
RUNTIME_ROOT = Path(r"D:\Kairos\runtime\runtime-incident-20261012")
PRIVATE_ROOT = Path(r"D:\Kairos\runtime\alert-delivery-20261012\operational-r6")
PREVIOUS_R5_ROOT = Path(r"D:\Kairos\runtime\alert-delivery-20261012\operational-r5-v2")
OWNER = "69893dc7b7c647f49967387e7efca9fb"
TASK_NAME = "Kairos-R6-TechnicalAlerts-V3-20261012"
SCOPE = "kairos-r6-technical-runtime-alerts-v3"
GROUP_ID = -1004475802889
SIGNER = "40AF365C6682B73D056A6A274DBFF6B65BE9F827"
ROUTE_PATH = "development/ops_alerts/notification-routing-20261012.json"
ROUTE_SHA256 = "6691779312c346c72a2e0e788a7a2827d59b93865f205704b47b41a43eaac5bc"
R5_RELATIVE_SOURCE = "development/ops_alerts/runtime_status_r5_notifier.py"
R5_SOURCE_SHA256 = "b53b24d3d97d5d4bb58384e87073e2a3d9ad22f853adec263ec84813553555db"
EXPECTED_BOT = "KairosCryptoAI_bot"
MAX_BYTES = 65_536
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_WORK = re.compile(r"read-recovery-r6-feed-[0-9a-f]{32}\Z")
_STATES = {
    "failed_closed",
    "missing",
    "invalid",
    "unknown_owner",
    "running_stale",
    "running_fresh",
    "waiting_source_nontrading",
    "catching_up_nontrading",
}
_ALERTS = _STATES - {"running_fresh"}
STATUS_STALE_AFTER_SECONDS = 30.0
_SOURCE_TIMEOUT = "OFFICIAL_CLOSED_BAR_FETCH_TIMEOUT"


class R6Error(RuntimeError):
    def __init__(
        self, category: str, *, stage: str | None = None, send_attempts: int | None = 0
    ):
        self.category = category
        self.stage = stage
        self.send_attempts = send_attempts
        super().__init__(category)


def _json(raw: bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=unique)


def _bounded_source(path: Path, maximum: int) -> bytes:
    """Small source-only bounded reader used to authenticate the shared helpers."""
    try:
        before = path.lstat()
        if (
            path.is_symlink()
            or getattr(before, "st_file_attributes", 0) & 0x400
            or not path.is_file()
            or not 0 < before.st_size <= maximum
        ):
            raise R6Error("SOURCE_ADMISSION_FAILED")
        fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise R6Error("SOURCE_ADMISSION_FAILED")
            data = stream.read(maximum + 1)
        if len(data) != before.st_size or len(data) > maximum:
            raise R6Error("SOURCE_ADMISSION_FAILED")
        return data
    except R6Error:
        raise
    except Exception:  # noqa: BLE001 - collapse hostile filesystem errors to a safe admission category.
        raise R6Error("SOURCE_ADMISSION_FAILED") from None


def _r5_helpers():
    """Load only the exact reviewed R5 V2 helper module, after its hash check."""
    path = ROOT / R5_RELATIVE_SOURCE
    if (
        hashlib.sha256(_bounded_source(path, 256 * 1024)).hexdigest()
        != R5_SOURCE_SHA256
    ):
        raise R6Error("R5_HELPER_SOURCE_MISMATCH")
    name = "_kairos_pinned_r5_runtime_helpers"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise R6Error("R5_HELPER_SOURCE_MISMATCH")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - discard import diagnostics and fail closed on pinned-helper load errors.
        sys.modules.pop(name, None)
        raise R6Error("R5_HELPER_SOURCE_MISMATCH") from None
    if (
        Path(module.__file__).resolve() != path.resolve()
        or hashlib.sha256(_bounded_source(path, 256 * 1024)).hexdigest()
        != R5_SOURCE_SHA256
    ):
        sys.modules.pop(name, None)
        raise R6Error("R5_HELPER_SOURCE_MISMATCH")
    return module


def _read_private(path: Path, *, maximum: int, helpers: Any) -> bytes:
    try:
        _c, delivery = helpers._continuation()
        return helpers._read_private(path, maximum=maximum, delivery=delivery)
    except Exception:  # noqa: BLE001 - protected-reader failures are redacted to a fixed category.
        raise R6Error("PROTECTED_EVIDENCE_REQUIRED") from None


def _verify_binding(binding: Any) -> dict[str, Any]:
    keys = {
        "schema_version",
        "scope",
        "owner",
        "task_name",
        "work",
        "serve_container_id",
        "receipt_sha256",
        "receipt_source_revision",
        "deploy_revision",
        "notifier_sha256",
        "route_sha256",
        "handoff_sha256",
        "r5_binding_sha256",
        "r5_journal_sha256",
        "r5_guard_sha256",
        "r5_event_id",
        "owner_absence_observed",
        "trading_started",
    }
    if not isinstance(binding, dict) or set(binding) != keys:
        raise R6Error("BINDING_INVALID")
    if (
        type(binding.get("schema_version")) is not int
        or binding["schema_version"] != 1
        or binding.get("scope") != SCOPE
        or binding.get("owner") != OWNER
        or binding.get("task_name") != TASK_NAME
        or not isinstance(binding.get("work"), str)
        or _WORK.fullmatch(binding["work"]) is None
        or not isinstance(binding.get("serve_container_id"), str)
        or _HEX64.fullmatch(binding["serve_container_id"]) is None
        or any(
            not isinstance(binding.get(k), str) or _HEX64.fullmatch(binding[k]) is None
            for k in (
                "receipt_sha256",
                "notifier_sha256",
                "route_sha256",
                "handoff_sha256",
                "r5_binding_sha256",
                "r5_journal_sha256",
                "r5_guard_sha256",
                "r5_event_id",
            )
        )
        or any(
            not isinstance(binding.get(k), str) or _HEX40.fullmatch(binding[k]) is None
            for k in (
                "receipt_source_revision",
                "deploy_revision",
            )
        )
        or binding.get("route_sha256") != ROUTE_SHA256
        or binding.get("r5_event_id")
        != "9108bcba0a8ccf8f200c2654bb323216e4a8d14f991f69b67f6b0559ded20c92"
        or binding.get("owner_absence_observed") is not True
        or binding.get("trading_started") is not False
    ):
        raise R6Error("BINDING_INVALID")
    return binding


def _verify_previous_r5(binding: dict[str, Any], helpers: Any, delivery: Any) -> None:
    """Preserve the exact R5 unknown; owner absence is never converted to no-send."""
    prior_binding_path = PREVIOUS_R5_ROOT / "binding.json"
    journal_path = PREVIOUS_R5_ROOT / "events.jsonl"
    guard_path = PREVIOUS_R5_ROOT / f"events.jsonl.{binding['r5_event_id']}.guard"
    prior_binding_raw = helpers._read_private(
        prior_binding_path, maximum=16 * 1024, delivery=delivery
    )
    helpers._verify_signature(prior_binding_path, PREVIOUS_R5_ROOT / "binding.json.asc")
    journal_raw = helpers._read_private(
        journal_path, maximum=MAX_BYTES, delivery=delivery
    )
    guard_raw = helpers._read_private(guard_path, maximum=1024, delivery=delivery)
    if (
        hashlib.sha256(prior_binding_raw).hexdigest() != binding["r5_binding_sha256"]
        or hashlib.sha256(journal_raw).hexdigest() != binding["r5_journal_sha256"]
        or hashlib.sha256(guard_raw).hexdigest() != binding["r5_guard_sha256"]
    ):
        raise R6Error("PREVIOUS_R5_EVIDENCE_CHANGED")
    try:
        prior = helpers._json(prior_binding_raw)
        rows = [helpers._json(line) for line in journal_raw.splitlines()]
        guard = helpers._json(guard_raw)
    except Exception:  # noqa: BLE001 - malformed prior evidence is reported without raw parser details.
        raise R6Error("PREVIOUS_R5_EVIDENCE_INVALID") from None
    event_id = binding["r5_event_id"]
    if (
        not isinstance(prior, dict)
        or prior.get("scope") != helpers.SCOPE
        or prior.get("task_name") != helpers.TASK_NAME
        or prior.get("owner") != OWNER
        or prior.get("notifier_sha256") != R5_SOURCE_SHA256
        or prior.get("trading_started") is not False
        or len(rows) != 4
        or rows[2].get("kind") != "send_reserved"
        or rows[2].get("event_id") != event_id
        or rows[2].get("transition") != "firing"
        or rows[3].get("kind") != "send_outcome"
        or rows[3].get("event_id") != event_id
        or rows[3].get("result") != "unknown"
        or guard
        != {"event_id": event_id, "state": "failed_closed", "transition": "firing"}
    ):
        raise R6Error("PREVIOUS_R5_TERMINAL_UNKNOWN_REQUIRED")


def admit_sources(*, helpers: Any | None = None) -> dict[str, Any]:
    """Admit only the current signed source, signed R6 receipt, and R5 unknown binding."""
    helpers = helpers or _r5_helpers()
    c, delivery = helpers._continuation()
    head = (
        helpers._git(ROOT, ["show", "-s", "--format=%H %G? %GF", "HEAD"])
        .decode("ascii", "strict")
        .strip()
        .split()
    )
    if (
        len(head) != 3
        or head[1:] != ["G", SIGNER]
        or helpers._git(ROOT, ["branch", "--show-current"])
        .decode("ascii", "strict")
        .strip()
        != "main"
    ):
        raise R6Error("SOURCE_ADMISSION_FAILED")
    head_id = head[0]
    if (
        helpers._git(ROOT, ["rev-parse", "origin/main"])
        .decode("ascii", "strict")
        .strip()
        != head_id
    ):
        raise R6Error("SOURCE_ADMISSION_FAILED")
    rel = "development/ops_alerts/runtime_status_r6_notifier.py"
    source_blob = helpers._git(ROOT, ["show", f"{head_id}:{rel}"])
    source_working = helpers._read(ROOT / rel, 256 * 1024)
    if source_blob != source_working:
        raise R6Error("SOURCE_ADMISSION_FAILED")
    if helpers._git(ROOT, ["status", "--porcelain", "--", rel]).strip():
        raise R6Error("SOURCE_ADMISSION_FAILED")
    deploy_head = (
        helpers._git(DEPLOY, ["rev-parse", "HEAD"]).decode("ascii", "strict").strip()
    )
    deploy_origin = (
        helpers._git(DEPLOY, ["rev-parse", "origin/main"])
        .decode("ascii", "strict")
        .strip()
    )
    deploy_branch = (
        helpers._git(DEPLOY, ["branch", "--show-current"])
        .decode("ascii", "strict")
        .strip()
    )
    deploy_fields = (
        helpers._git(DEPLOY, ["show", "-s", "--format=%H %G? %GF", deploy_head])
        .decode("ascii", "strict")
        .strip()
        .split()
    )
    deploy_dirty = helpers._git(
        DEPLOY, ["status", "--porcelain", "--untracked-files=no"]
    )
    binding_path = PRIVATE_ROOT / "binding.json"
    delivery._no_reparse(PRIVATE_ROOT)
    delivery._private_acl(PRIVATE_ROOT)
    binding_raw = helpers._read_private(
        binding_path, maximum=16 * 1024, delivery=delivery
    )
    helpers._verify_signature(binding_path, PRIVATE_ROOT / "binding.json.asc")
    binding = _verify_binding(helpers._json(binding_raw))
    if (
        hashlib.sha256(source_blob).hexdigest() != binding["notifier_sha256"]
        or deploy_head != binding["deploy_revision"]
        or deploy_head != deploy_origin
        or deploy_branch != "main"
        or deploy_fields != [deploy_head, "G", SIGNER]
        or deploy_dirty
        or binding["handoff_sha256"] != c.HANDOFF_SHA256
    ):
        raise R6Error("SOURCE_ADMISSION_FAILED")
    route = helpers._git(ROOT, ["show", f"{head_id}:{ROUTE_PATH}"])
    if (
        hashlib.sha256(route).hexdigest() != ROUTE_SHA256
        or helpers._read(ROOT / ROUTE_PATH, 16 * 1024) != route
    ):
        raise R6Error("SOURCE_ADMISSION_FAILED")
    source_fields = (
        helpers._git(
            DEPLOY,
            ["show", "-s", "--format=%H %G? %GF", binding["receipt_source_revision"]],
        )
        .decode("ascii", "strict")
        .strip()
        .split()
    )
    if source_fields != [binding["receipt_source_revision"], "G", SIGNER]:
        raise R6Error("SOURCE_ADMISSION_FAILED")
    helpers._git(
        DEPLOY,
        [
            "merge-base",
            "--is-ancestor",
            binding["receipt_source_revision"],
            binding["deploy_revision"],
        ],
    )
    _verify_previous_r5(binding, helpers, delivery)
    work = RUNTIME_ROOT / binding["work"]
    receipt_path = work / "receipt.json"
    delivery._no_reparse(work)
    delivery._private_acl(work)
    receipt_raw = helpers._read_private(
        receipt_path, maximum=256 * 1024, delivery=delivery
    )
    helpers._verify_signature(receipt_path, work / "receipt.json.asc")
    if hashlib.sha256(receipt_raw).hexdigest() != binding["receipt_sha256"]:
        raise R6Error("RECEIPT_INVALID")
    receipt = helpers._json(receipt_raw)
    generation = receipt.get("generation") if isinstance(receipt, dict) else None
    status = generation.get("status") if isinstance(generation, dict) else None
    if (
        not isinstance(receipt, dict)
        or receipt.get("result") != "PASS_NEW_NONTRADING_GENERATION"
        or receipt.get("owner") != OWNER
        or receipt.get("source_revision") != binding["receipt_source_revision"]
        or not isinstance(generation, dict)
        or generation.get("name") != "kairos-epoch-69893dc7b7c6-serve-r6"
        or generation.get("container_id") != binding["serve_container_id"]
        or not isinstance(status, dict)
        or status.get("state") != "RUNNING_NONTRADING"
        or status.get("owner") != OWNER
        or any(
            status.get(k) != 0
            for k in ("pending_outbox", "unresolved_inbox", "uncompleted_publications")
        )
        or receipt.get("trading_started") is not False
        or any(
            receipt.get(k) is not False
            for k in ("PAPER_QUALIFIED", "ALPHA_READY", "LIVE_READY")
        )
        or receipt.get("STRATEGY_POLICY") != "REJECT_ALL"
    ):
        raise R6Error("RECEIPT_INVALID")
    return {
        "binding": binding,
        "binding_sha256": hashlib.sha256(binding_raw).hexdigest(),
        "receipt": receipt,
        "helpers": helpers,
        "continuation": c,
        "delivery": delivery,
    }


def _write_new(path: Path, raw: bytes, c: Any, delivery: Any) -> None:
    c._exclusive_fsync(path, raw)
    c._set_exact_file_acl(path)
    delivery._no_reparse(path)
    delivery._private_acl(path)


def _handoff_transport(helpers: Any, c: Any, delivery: Any):
    """Validate the byte-bound reviewed handoff; transport construction is offline."""
    try:
        return helpers._prepare_transport(c, delivery)
    except Exception:  # noqa: BLE001 - local sender-preflight failures are sanitized before any wire call.
        raise R6Error(
            "SENDER_PREFLIGHT_FAILED_NO_SEND", stage="SENDER_PREFLIGHT", send_attempts=0
        ) from None


def _qualifier_paths(root: Path, event_id: str) -> tuple[Path, Path, Path]:
    return (
        root / f"route-qualification-{event_id}.guard",
        root / f"route-qualification-{event_id}.receipt.json",
        root / f"route-qualification-{event_id}.result.json",
    )


def qualify_route(
    *,
    source_admitter: Callable[[], Any] = admit_sources,
    transport_factory=None,
    root: Path = PRIVATE_ROOT,
) -> dict[str, Any]:
    source = source_admitter()
    helpers = source["helpers"]
    c, delivery = source["continuation"], source["delivery"]
    delivery._no_reparse(root)
    delivery._private_acl(root)
    event_id = hashlib.sha256(
        f"{source['binding_sha256']}|r6-route-qualification-v1".encode()
    ).hexdigest()
    guard, receipt_path, result_path = _qualifier_paths(root, event_id)
    if any(
        path.exists() or path.is_symlink()
        for path in (guard, receipt_path, result_path)
    ):
        raise R6Error("QUALIFICATION_ALREADY_RESERVED_OR_GUARD_FAILED")
    # Pure local preflight precedes a NEW create-only event. A retained guard
    # always blocks even construction; no historical attempt is re-prepared.
    transport = (
        transport_factory()
        if transport_factory
        else _handoff_transport(helpers, c, delivery)
    )
    guard_record = {
        "schema_version": 1,
        "kind": "kairos.r6.route-qualification-guard.v1",
        "event_id": event_id,
        "scope": SCOPE,
        "state": "reserved",
        "automatic_retry": False,
        "trading_authority": False,
    }
    try:
        _write_new(
            guard,
            json.dumps(guard_record, sort_keys=True, separators=(",", ":")).encode(),
            c,
            delivery,
        )
    except Exception:  # noqa: BLE001 - persistence/ACL errors leave the create-only guard fail-closed.
        raise R6Error("QUALIFICATION_ALREADY_RESERVED_OR_GUARD_FAILED") from None
    result = {
        "schema_version": 1,
        "kind": "kairos.r6.route-qualification-result.v1",
        "event_id": event_id,
        "scope": SCOPE,
        "stage": "PRECHECK_STARTED",
        "send_attempts": 0,
        "http_method_counts": {"getMe": 0, "getChat": 0, "sendMessage": 0},
        "transport_accepted": False,
        "message_id": None,
        "automatic_retry": False,
        "trading_authority": False,
    }
    try:
        result["http_method_counts"]["getMe"] = 1
        identity = transport.call("getMe", {})
        if (
            identity.get("is_bot") is not True
            or identity.get("username") != EXPECTED_BOT
        ):
            raise R6Error("BOT_IDENTITY_MISMATCH")
        result["http_method_counts"]["getChat"] = 1
        chat = transport.call("getChat", {"chat_id": GROUP_ID})
        if (
            type(chat.get("id")) is not int
            or chat["id"] != GROUP_ID
            or chat.get("type") not in {"group", "supergroup"}
        ):
            raise R6Error("CHAT_IDENTITY_MISMATCH")
        result["stage"] = "IDENTITY_VERIFIED"
        result["send_attempts"] = 1
        result["http_method_counts"]["sendMessage"] = 1
        result["stage"] = "SEND_RESERVED"
        sent = transport.call(
            "sendMessage",
            {
                "chat_id": GROUP_ID,
                "text": "[Kairos R6 ROUTE QUALIFICATION] Non-trading alert route check; trading remains disabled.",
                "protect_content": True,
            },
        )
        if (
            not isinstance(sent.get("chat"), dict)
            or type(sent["chat"].get("id")) is not int
            or sent["chat"]["id"] != GROUP_ID
            or type(sent.get("message_id")) is not int
            or sent["message_id"] <= 0
        ):
            raise R6Error("SEND_OUTCOME_UNKNOWN")
        receipt = {
            "schema_version": 1,
            "kind": "kairos.r6.route-qualification-receipt.v1",
            "event_id": event_id,
            "scope": SCOPE,
            "recipient_chat_id": GROUP_ID,
            "message_id": sent["message_id"],
            "accepted_at_utc": datetime.now(UTC).isoformat(),
            "protect_content": True,
            "binding_sha256": source["binding_sha256"],
            "trading_authority": False,
        }
        _write_new(
            receipt_path,
            json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode(),
            c,
            delivery,
        )
        result.update(
            {
                "stage": "TRANSPORT_ACCEPTED",
                "transport_accepted": True,
                "message_id": sent["message_id"],
            }
        )
    except R6Error as error:
        result["stage"] = (
            "SEND_OUTCOME_UNKNOWN" if result["send_attempts"] else "PRECHECK_FAILED"
        )
        result["error_category"] = error.category
    except Exception as error:  # noqa: BLE001 - persist only an allowlisted category; never expose exception text.
        result["stage"] = (
            "SEND_OUTCOME_UNKNOWN" if result["send_attempts"] else "PRECHECK_FAILED"
        )
        category = getattr(error, "category", None)
        result["error_category"] = (
            category
            if category
            in {
                "TRANSPORT_FAILED",
                "HTTP_REJECTED",
                "API_REJECTED",
                "REDIRECT_REJECTED",
                "RESPONSE_TOO_LARGE",
                "PROTECTED_ACL_REQUIRED",
                "ACL_VERIFICATION_FAILED",
            }
            else "LOCAL_FAILURE"
        )
    try:
        _write_new(
            result_path,
            json.dumps(result, sort_keys=True, separators=(",", ":")).encode(),
            c,
            delivery,
        )
    except Exception:  # noqa: BLE001 - result-write failures become terminal unknown after any send attempt.
        # The exclusive guard is terminal; never retry even if persistence failed.
        if result["send_attempts"]:
            raise R6Error(
                "SEND_OUTCOME_UNKNOWN", stage="SEND_OUTCOME_UNKNOWN", send_attempts=1
            ) from None
        raise R6Error(
            "QUALIFICATION_RESULT_PERSISTENCE_FAILED",
            stage="RESULT_PERSISTENCE_FAILED",
            send_attempts=0,
        ) from None
    if result["stage"] != "TRANSPORT_ACCEPTED":
        raise R6Error(
            result.get("error_category", "QUALIFICATION_FAILED"),
            stage=result["stage"],
            send_attempts=result["send_attempts"],
        )
    return result


def _verify_qualification(
    source: dict[str, Any], root: Path, helpers: Any, delivery: Any
) -> dict[str, Any]:
    event_id = hashlib.sha256(
        f"{source['binding_sha256']}|r6-route-qualification-v1".encode()
    ).hexdigest()
    guard_path, receipt_path, result_path = _qualifier_paths(root, event_id)
    guard_raw = helpers._read_private(guard_path, maximum=4096, delivery=delivery)
    receipt_raw = helpers._read_private(receipt_path, maximum=4096, delivery=delivery)
    result_raw = helpers._read_private(result_path, maximum=4096, delivery=delivery)
    guard, receipt, result = (
        helpers._json(guard_raw),
        helpers._json(receipt_raw),
        helpers._json(result_raw),
    )
    if (
        not isinstance(guard, dict)
        or guard.get("schema_version") != 1
        or guard.get("kind") != "kairos.r6.route-qualification-guard.v1"
        or guard.get("event_id") != event_id
        or guard.get("scope") != SCOPE
        or guard.get("state") != "reserved"
        or guard.get("automatic_retry") is not False
        or guard.get("trading_authority") is not False
        or not isinstance(receipt, dict)
        or receipt.get("event_id") != event_id
        or receipt.get("binding_sha256") != source["binding_sha256"]
        or receipt.get("schema_version") != 1
        or receipt.get("kind") != "kairos.r6.route-qualification-receipt.v1"
        or receipt.get("scope") != SCOPE
        or receipt.get("recipient_chat_id") != GROUP_ID
        or type(receipt.get("message_id")) is not int
        or receipt["message_id"] <= 0
        or receipt.get("protect_content") is not True
        or receipt.get("trading_authority") is not False
        or not isinstance(result, dict)
        or result.get("event_id") != event_id
        or result.get("stage") != "TRANSPORT_ACCEPTED"
        or result.get("message_id") != receipt["message_id"]
        or result.get("transport_accepted") is not True
        or result.get("send_attempts") != 1
        or result.get("automatic_retry") is not False
        or result.get("trading_authority") is not False
        or result.get("http_method_counts")
        != {"getMe": 1, "getChat": 1, "sendMessage": 1}
    ):
        raise R6Error("ACCEPTED_ROUTE_QUALIFICATION_REQUIRED")
    return receipt


def _status_path(binding: dict[str, Any]) -> Path:
    return RUNTIME_ROOT / binding["work"] / "output-serve" / "status.json"


class R6Journal:
    """R6 state reader; pinning, lease, append, and guard writes reuse R5 helpers."""

    def __init__(self, path: Path, c: Any, delivery: Any, helpers: Any):
        self.path, self.c, self.delivery = path, c, delivery
        self.lease_path = path.with_name(path.name + ".lock")
        self._base, self._error = helpers.R5Journal, helpers.R5Error

    @contextmanager
    def locked(self):
        with self._base.locked(self):
            yield

    def _append(self, record: dict[str, Any]) -> None:
        self._base._append(self, record)

    def _verify(self, path: Path) -> bytes:
        return self._base._verify(self, path)

    def read(self, *, allow_pending: bool = False) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        raw = self._verify(self.path)
        if not raw or not raw.endswith(b"\n") or len(raw) > MAX_BYTES:
            raise self._error("JOURNAL_INVALID")
        try:
            rows = [_json(line) for line in raw.splitlines()]
            if len(rows) > 256 or any(
                not isinstance(row, dict) or row.get("seq") != index
                for index, row in enumerate(rows)
            ):
                raise ValueError("sequence")
            if rows and (
                set(rows[0])
                != {"schema_version", "seq", "kind", "state", "binding_sha256"}
                or rows[0].get("schema_version") != 1
                or rows[0].get("kind") != "baseline"
                or rows[0].get("state") not in _STATES
                or not isinstance(rows[0].get("binding_sha256"), str)
                or _HEX64.fullmatch(rows[0]["binding_sha256"]) is None
            ):
                raise ValueError("baseline")
            current = rows[0].get("state") if rows else None
            pending = None
            for row in rows[1:]:
                if (
                    set(row) == {"schema_version", "seq", "kind", "state"}
                    and row.get("schema_version") == 1
                    and row.get("kind") == "observe"
                    and row.get("state") in _STATES
                    and pending is None
                ):
                    current = row["state"]
                elif (
                    set(row)
                    == {
                        "schema_version",
                        "seq",
                        "kind",
                        "event_id",
                        "transition",
                        "state",
                    }
                    and row.get("schema_version") == 1
                    and row.get("kind") == "send_reserved"
                    and isinstance(row.get("event_id"), str)
                    and _HEX64.fullmatch(row["event_id"]) is not None
                    and (
                        (
                            row.get("transition") == "firing"
                            and row.get("state") in _ALERTS
                        )
                        or (
                            row.get("transition") == "resolved"
                            and row.get("state") == "running_fresh"
                        )
                    )
                    and row.get("state") == current
                    and pending is None
                ):
                    pending = row
                elif (
                    set(row)
                    == {
                        "schema_version",
                        "seq",
                        "kind",
                        "event_id",
                        "transition",
                        "state",
                        "result",
                    }
                    and row.get("schema_version") == 1
                    and row.get("kind") == "send_outcome"
                    and pending is not None
                    and row.get("event_id") == pending.get("event_id")
                    and row.get("transition") == pending.get("transition")
                    and row.get("state") == pending.get("state")
                    and row.get("result") in {"accepted", "unknown"}
                ):
                    if row["result"] == "unknown":
                        raise self._error("SEND_OUTCOME_UNKNOWN")
                    pending = None
                else:
                    raise ValueError("event")
            if pending is not None and not allow_pending:
                raise self._error("SEND_OUTCOME_UNKNOWN")
            return rows
        except self._error:
            raise
        except Exception:  # noqa: BLE001 - journal parser errors are redacted to JOURNAL_INVALID.
            raise self._error("JOURNAL_INVALID") from None


def _classify(observation: Any) -> str:
    state, stale = (
        getattr(observation, "state", None),
        getattr(observation, "stale", None),
    )
    if state == "running":
        return (
            "invalid"
            if type(stale) is not bool
            else ("running_stale" if stale else "running_fresh")
        )
    if state == "stale":
        return "running_stale"
    if state in {"waiting_source_nontrading", "catching_up_nontrading"}:
        if type(stale) is not bool:
            return "invalid"
        return "running_stale" if stale else state
    return state if state in _ALERTS - {"running_stale"} else "invalid"


def _observe_status(
    path: Path,
    *,
    expected_owner: str,
    source: dict[str, Any],
    now: datetime | None = None,
) -> Any:
    """Extend the pinned file observer only for known R6 feed lifecycle states."""
    helpers, delivery = source["helpers"], source["delivery"]
    try:
        raw = helpers._read_private(path, maximum=65_536, delivery=delivery)
        value = helpers._json(raw)
    except Exception:  # noqa: BLE001 - protected read/parse failure falls back to the pinned fail-closed observer.
        return helpers._runtime_observer(path, expected_owner=expected_owner)
    if not isinstance(value, dict) or value.get("state") not in {
        "WAITING_SOURCE_NONTRADING",
        "CATCHING_UP_NONTRADING",
    }:
        return helpers._runtime_observer(path, expected_owner=expected_owner)
    state = value["state"]
    observed_raw = value.get("observed_at_utc")
    try:
        observed = datetime.fromisoformat(observed_raw.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return SimpleNamespace(state="invalid", stale=False)
    current = now or datetime.now(UTC)
    if (
        observed.tzinfo is None
        or observed.utcoffset() is None
        or current.tzinfo is None
        or current.utcoffset() is None
    ):
        return SimpleNamespace(state="invalid", stale=False)
    age = (current.astimezone(UTC) - observed.astimezone(UTC)).total_seconds()
    if age < 0:
        return SimpleNamespace(state="invalid", stale=False)
    stale = age > STATUS_STALE_AFTER_SECONDS
    circuit = value.get("source_transport")
    counters = ("pending_outbox", "unresolved_inbox", "uncompleted_publications")
    circuit_keys = {"timeout_rounds", "recoveries", "consecutive_timeout_rounds"}
    valid_circuit = (
        isinstance(circuit, dict)
        and set(circuit) == circuit_keys
        and all(type(circuit[key]) is int and circuit[key] >= 0 for key in circuit_keys)
        and circuit["recoveries"] <= circuit["timeout_rounds"]
        and circuit["consecutive_timeout_rounds"] <= circuit["timeout_rounds"]
    )
    valid = (
        value.get("owner") == expected_owner
        and value.get("trading_started") is False
        and value.get("PAPER_QUALIFIED") is False
        and value.get("ALPHA_READY") is False
        and value.get("LIVE_READY") is False
        and value.get("STRATEGY_POLICY") == "REJECT_ALL"
        and all(type(value.get(key)) is int and value[key] == 0 for key in counters)
        and value.get("source_fresh") is False
        and valid_circuit
        and (
            (
                state == "WAITING_SOURCE_NONTRADING"
                and value.get("source_wait_reason") == _SOURCE_TIMEOUT
                and circuit["consecutive_timeout_rounds"] > 0
            )
            or (
                state == "CATCHING_UP_NONTRADING"
                and value.get("source_wait_reason") is None
                and circuit["consecutive_timeout_rounds"] == 0
            )
        )
    )
    if not valid:
        return SimpleNamespace(state="invalid", stale=stale)
    return SimpleNamespace(
        state="waiting_source_nontrading"
        if state == "WAITING_SOURCE_NONTRADING"
        else "catching_up_nontrading",
        stale=stale,
    )


def initialize(
    *,
    source_admitter: Callable[[], Any] = admit_sources,
    observer=None,
    root: Path = PRIVATE_ROOT,
) -> dict[str, Any]:
    source = source_admitter()
    helpers = source["helpers"]
    _verify_qualification(source, root, helpers, source["delivery"])
    source["delivery"]._no_reparse(root)
    source["delivery"]._private_acl(root)
    journal = R6Journal(
        root / "events.jsonl", source["continuation"], source["delivery"], helpers
    )
    observer = observer or (
        lambda path, *, expected_owner: _observe_status(
            path, expected_owner=expected_owner, source=source
        )
    )
    with journal.locked():
        if journal.read():
            raise R6Error("BASELINE_ALREADY_EXISTS")
        status_path = _status_path(source["binding"])
        source["delivery"]._no_reparse(status_path)
        state = _classify(
            observer(status_path, expected_owner=OWNER)
            if observer is not None
            else _observe_status(status_path, expected_owner=OWNER, source=source)
        )
        if state != "running_fresh":
            raise R6Error("HEALTHY_BASELINE_REQUIRED")
        journal._append(
            {
                "schema_version": 1,
                "seq": 0,
                "kind": "baseline",
                "state": state,
                "binding_sha256": source["binding_sha256"],
            }
        )
    return {
        "status": "BASELINE_RECORDED_AFTER_R6_ROUTE_ACCEPTED",
        "state": "running_fresh",
        "send_attempts": 0,
        "trading_authority": False,
    }


def _monitor_sender(source: dict[str, Any], root: Path):
    helpers, c, delivery = source["helpers"], source["continuation"], source["delivery"]
    transport = _handoff_transport(helpers, c, delivery)

    def send(alert: dict[str, Any]) -> bool:
        response = transport.call(
            "sendMessage",
            {"chat_id": GROUP_ID, "text": alert["text"], "protect_content": True},
        )
        if (
            not isinstance(response, dict)
            or type(response.get("message_id")) is not int
            or response["message_id"] < 1
            or not isinstance(response.get("chat"), dict)
            or type(response["chat"].get("id")) is not int
            or response["chat"]["id"] != GROUP_ID
        ):
            raise R6Error("SEND_OUTCOME_UNKNOWN")
        receipt = {
            "schema_version": 1,
            "kind": "kairos.r6.runtime-alert-receipt.v1",
            "event_id": alert["event_id"],
            "transition": alert["transition"],
            "state": alert["state"],
            "observed_state": alert.get("observed_state", alert["state"]),
            "recipient_chat_id": GROUP_ID,
            "message_id": response["message_id"],
            "accepted_at_utc": datetime.now(UTC).isoformat(),
            "protect_content": True,
            "binding_sha256": source["binding_sha256"],
            "trading_authority": False,
        }
        _write_new(
            root / f"r6-telegram-{alert['event_id']}.json",
            json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode(),
            c,
            delivery,
        )
        return True

    return send


def poll_once(
    *,
    source_admitter: Callable[[], Any] = admit_sources,
    observer=None,
    sender=None,
    root: Path = PRIVATE_ROOT,
) -> dict[str, Any]:
    source = source_admitter()
    helpers, c, delivery = source["helpers"], source["continuation"], source["delivery"]
    _verify_qualification(source, root, helpers, delivery)
    delivery._no_reparse(root)
    delivery._private_acl(root)
    journal = R6Journal(root / "events.jsonl", c, delivery, helpers)
    observer = observer or (
        lambda path, *, expected_owner: _observe_status(
            path, expected_owner=expected_owner, source=source
        )
    )
    with journal.locked():
        try:
            rows = journal.read()
        except helpers.R5Error as error:
            raise R6Error(error.category) from None
        if not rows or rows[0].get("binding_sha256") != source["binding_sha256"]:
            raise R6Error("BASELINE_REQUIRED_OR_BINDING_CHANGED")
        status_path = _status_path(source["binding"])
        delivery._no_reparse(status_path)
        observed_state = _classify(
            observer(status_path, expected_owner=OWNER)
            if observer is not None
            else _observe_status(status_path, expected_owner=OWNER, source=source)
        )
        state = observed_state
        current = (
            rows[-1]["state"]
            if rows[-1]["kind"] in {"baseline", "observe", "send_outcome"}
            else None
        )
        active = False
        for row in rows[1:]:
            if row["kind"] == "observe":
                current = row["state"]
            elif row["kind"] == "send_outcome":
                active = row["transition"] == "firing"
        previous = current
        if state in _ALERTS and not active and previous not in _ALERTS:
            transition = "firing"
        elif state == "running_fresh" and active and previous != "running_fresh":
            transition = "resolved"
        else:
            transition = None
        if transition is not None and sender is None:
            # Credential, signed-handoff and constructor preflight stay before
            # the irreversible journal reservation and make no network call.
            sender = _monitor_sender(source, root)
        if state != previous:
            journal._append(
                {
                    "schema_version": 1,
                    "seq": len(rows),
                    "kind": "observe",
                    "state": state,
                }
            )
            rows = journal.read()
        if transition is None:
            return {
                "status": "quiet_baseline_or_unchanged",
                "state": observed_state,
                "send_attempts": 0,
                "trading_authority": False,
            }
        event_id = hashlib.sha256(
            f"{source['binding_sha256']}|{len(rows)}|{transition}|{state}".encode()
        ).hexdigest()
        journal._append(
            {
                "schema_version": 1,
                "seq": len(rows),
                "kind": "send_reserved",
                "event_id": event_id,
                "transition": transition,
                "state": state,
            }
        )
        alert = {
            "event_id": event_id,
            "transition": transition,
            "state": state,
            "observed_state": observed_state,
            "recipient_chat_id": GROUP_ID,
            "text": "[Kairos R6] Non-trading runtime status is unhealthy. Trading remains disabled."
            if transition == "firing"
            else "[Kairos R6] Non-trading runtime status returned to fresh RUNNING. Trading remains disabled.",
        }
        try:
            assert sender is not None
            accepted = sender(alert) is True
        except Exception:  # noqa: BLE001 - any sender failure is terminal unknown; exception text is discarded.
            accepted = False
        rows = journal.read(allow_pending=True)
        journal._append(
            {
                "schema_version": 1,
                "seq": len(rows),
                "kind": "send_outcome",
                "event_id": event_id,
                "transition": transition,
                "state": state,
                "result": "accepted" if accepted else "unknown",
            }
        )
        return {
            "status": transition + ("_accepted" if accepted else "_outcome_unknown"),
            "state": observed_state,
            "send_attempts": 1,
            "trading_authority": False,
        }


def plan() -> dict[str, Any]:
    return {
        "status": "PLAN_ONLY",
        "scope": SCOPE,
        "task_name": TASK_NAME,
        "network_calls": 0,
        "database_or_queue": False,
        "trading_authority": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--qualify-route", action="store_true")
    modes.add_argument("--initialize", action="store_true")
    modes.add_argument("--poll-once", action="store_true")
    modes.add_argument("--verify-only", action="store_true")
    parser.add_argument("--armed", action="store_true")
    args = parser.parse_args(argv)
    if not (
        args.qualify_route or args.initialize or args.poll_once or args.verify_only
    ):
        print(json.dumps(plan(), sort_keys=True))
        return 0
    if not args.armed:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "error_category": "EXPLICIT_ARM_REQUIRED",
                    "send_attempts": 0,
                },
                sort_keys=True,
            )
        )
        return 2
    try:
        if args.qualify_route:
            report = qualify_route()
        elif args.verify_only:
            source = admit_sources()
            report = {
                "status": "ADMITTED_NO_SEND",
                "binding_sha256": source["binding_sha256"],
                "send_attempts": 0,
                "trading_authority": False,
            }
        elif args.initialize:
            report = initialize()
        else:
            report = poll_once()
    except R6Error as error:
        report = {
            "status": "BLOCKED",
            "error_category": error.category,
            "stage": error.stage,
            "send_attempts": error.send_attempts,
            "trading_authority": False,
        }
    except Exception:  # noqa: BLE001 - CLI emits a fixed safe category, never traceback or secret-bearing text.
        report = {
            "status": "BLOCKED",
            "error_category": "NOTIFIER_BLOCKED",
            "send_attempts": None,
            "trading_authority": False,
        }
    print(json.dumps(report, sort_keys=True))
    status = report.get("status", "")
    return (
        0
        if status not in {"BLOCKED", "PRECHECK_FAILED", "SEND_OUTCOME_UNKNOWN"}
        and not status.endswith("_outcome_unknown")
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
