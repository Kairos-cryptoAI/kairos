"""Bounded R4 status-file notifier. Default mode is strictly plan-only."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(r"D:\Kairos\kairos")
DEPLOY = Path(r"D:\Kairos\kairos-deploy")
PERSISTENCE = Path(r"D:\Kairos\kairos-persistence")
PRIVATE_ROOT = Path(r"D:\Kairos\runtime\alert-delivery-20261012\operational-r4")
PLANNER_COMMIT = "752f6460e817037de5292f101e27c36c67d5dbc8"
CONTINUATION_COMMIT = "f7b2f249c028a4a947b7279e677f21ee85bee8fc"
CONTINUATION_SHA256 = "b308e19753be088966e3fed4d1ddacc47ca3ef8d90089d1c527d1c93813d3930"
CORRECTED_TEST_COMMIT = "3432ee81f930887785a5ac5ecd2c4f3cb9bb6c5b"
CORRECTED_TEST_SHA256 = (
    "eda1ad2f83b1da8e10a0427355a7083f051741220f8b8e9eb5be8279568e0f68"
)
PERSISTENCE_COMMIT = "ea0c73395352f71da196270fe16659f1f0298a52"
PERSISTENCE_OBSERVER_SHA256 = (
    "27b244e7f20f3ae5cae52e1ab23d96db67429bec51d633eae68fe225f3b1af20"
)
PLANNER_SHA256 = "7b7e7d60ff850f9b8e7130cdd4b9170b160a3442c3f4cb4364ff550aff8694ca"
DEPLOY_COMMIT = "0427f7cf1e1cd70f2ddd05b80b4d7d6219736412"
SIGNER = "40AF365C6682B73D056A6A274DBFF6B65BE9F827"
CORRECTED_CHAT_ID = -1004475802889
CORRECTED_MESSAGE_ID = 2
CORRECTED_RESULT_SHA256 = (
    "59d102c129f0baf17f548763be1f55587be32673a3be7bfe81b57bb5966d489a"
)
EXPECTED_BOT = "KairosCryptoAI_bot"
TOKEN_PREFIX = "8898378227:"
ACK_TEXT = "DIRECT_OWNER_REPLY"
OWNER_DIRECTION_PATH = "development/ops_alerts/notification-routing-20261012.json"
OWNER_DIRECTION_SHA256 = (
    "6691779312c346c72a2e0e788a7a2827d59b93865f205704b47b41a43eaac5bc"
)
OWNER_ROUTING = "ALL_NOTIFICATION_CLASSES_TO_ONE_GROUP"
_FIRING_STATES = {
    "failed_closed",
    "missing",
    "invalid",
    "unknown_owner",
    "running_stale",
}
POLL_SECONDS = 15
MAX_SERVE_SECONDS = 8 * 60 * 60
MAX_STATUS_BYTES = 32 * 1024
SAFE_STATES = {
    "failed_closed",
    "missing",
    "invalid",
    "unknown_owner",
    "running_stale",
    "running_fresh",
}


class NotifierError(RuntimeError):
    """Sanitized fixed-category notifier failure."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


def _git(args: list[str], *, timeout: int = 20) -> bytes:
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper()
        in {
            "SYSTEMROOT",
            "WINDIR",
            "PATH",
            "TEMP",
            "TMP",
            "COMSPEC",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "HOMEDRIVE",
            "HOMEPATH",
            "HOME",
            "GNUPGHOME",
        }
    }
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
        }
    )
    git = Path("C:/Program Files/Git/cmd/git.exe")
    try:
        result = subprocess.run(
            [str(git), "-C", str(ROOT), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
            env=env,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise NotifierError("SOURCE_ADMISSION_FAILED") from None
    if result.returncode:
        raise NotifierError("SOURCE_ADMISSION_FAILED")
    return result.stdout


def _verify_signed_commit(
    commit: str, path: str, expected_sha: str | None = None
) -> bytes:
    metadata = (
        _git(["show", "-s", "--format=%H %G? %GF", commit])
        .decode("ascii", "strict")
        .strip()
    )
    if metadata != f"{commit} G {SIGNER}":
        raise NotifierError("SOURCE_ADMISSION_FAILED")
    _git(["merge-base", "--is-ancestor", commit, "HEAD"])
    blob = _git(["show", f"{commit}:{path}"])
    if expected_sha is not None and hashlib.sha256(blob).hexdigest() != expected_sha:
        raise NotifierError("SOURCE_ADMISSION_FAILED")
    return blob


def _read_regular_bytes(path: Path, *, maximum: int) -> bytes:
    """Read a bounded regular file while checking opened identity and reparse bits."""
    try:
        for component in (path, *path.parents):
            metadata = component.lstat()
            if (
                component.is_symlink()
                or getattr(metadata, "st_file_attributes", 0) & 0x400
            ):
                raise NotifierError("SOURCE_ADMISSION_FAILED")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise NotifierError("SOURCE_ADMISSION_FAILED")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise NotifierError("SOURCE_ADMISSION_FAILED")
            raw = stream.read(maximum + 1)
        if len(raw) > maximum or len(raw) != before.st_size:
            raise NotifierError("SOURCE_ADMISSION_FAILED")
        return raw
    except NotifierError:
        raise
    except (OSError, ValueError):
        raise NotifierError("SOURCE_ADMISSION_FAILED") from None


def _verify_working_source(
    path: Path, expected_sha256: str, *, maximum: int = 256 * 1024
) -> bytes:
    raw = _read_regular_bytes(path, maximum=maximum)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise NotifierError("SOURCE_ADMISSION_FAILED")
    return raw


def _parse_owner_direction(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (ValueError, UnicodeError, TypeError):
        raise NotifierError("OWNER_DIRECTION_INVALID") from None
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or value.get("kind") != "kairos.notifications.direct-owner-direction.v1"
        or value.get("basis") != "DIRECT_OWNER_REPLY_IN_CURRENT_TASK"
        or value.get("qualification_message_seen") is not True
        or value.get("qualification_message_id") != CORRECTED_MESSAGE_ID
        or value.get("qualification_receipt_sha256") != CORRECTED_RESULT_SHA256
        or value.get("temporary_chat_id") != CORRECTED_CHAT_ID
        or value.get("requested_routing") != OWNER_ROUTING
        or value.get("currently_enabled_sources") != ["R4_TECHNICAL_RUNTIME_STATUS"]
        or value.get("telegram_user_authenticated") is not False
        or value.get("trading_authority") is not False
        or value.get("qualification_authority") != "NOTIFICATION_ROUTE_ONLY"
        or value.get("eventual_final_group")
        != "NOT_REDIRECTED_OR_SELECTED_BY_THIS_RECEIPT"
    ):
        raise NotifierError("OWNER_DIRECTION_INVALID")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _parse_handoff(raw: bytes, continuation: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (ValueError, UnicodeError, TypeError):
        raise NotifierError("PROTECTED_EVIDENCE_REQUIRED") from None
    required = {
        "kind",
        "deploy_revision",
        "implementation_sha256",
        "old_diagnostic_sha256",
        "old_qualification_sha256",
        "current_token_differs_from_previous",
        "current_token_sha256",
        "automatic_retry",
        "trading_authority",
    }
    token_sha = value.get("current_token_sha256") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("kind") != "REVIEWED_CURRENT_TOKEN_NO_SEND_HANDOFF"
        or value.get("deploy_revision") != DEPLOY_COMMIT
        or value.get("implementation_sha256") != continuation.HANDOFF_SOURCE_SHA256
        or value.get("current_token_differs_from_previous") is not True
        or not isinstance(token_sha, str)
        or re.fullmatch(r"[0-9a-f]{64}", token_sha) is None
        or value.get("automatic_retry") is not False
        or value.get("trading_authority") is not False
    ):
        raise NotifierError("PROTECTED_EVIDENCE_REQUIRED")
    return value


def admit_sources() -> dict[str, Any]:
    """Verify signed source ancestry and working files before private inputs."""
    head = (
        _git(["show", "-s", "--format=%H %G? %GF", "HEAD"])
        .decode("ascii", "strict")
        .strip()
    )
    fields = head.split()
    if len(fields) != 3 or fields[1:] != ["G", SIGNER]:
        raise NotifierError("SOURCE_ADMISSION_FAILED")
    branch = _git(["branch", "--show-current"]).decode("ascii", "strict").strip()
    if branch != "main":
        raise NotifierError("SOURCE_ADMISSION_FAILED")
    _verify_signed_commit(
        CONTINUATION_COMMIT,
        "development/ops_alerts/telegram_continuation.py",
        CONTINUATION_SHA256,
    )
    _verify_signed_commit(
        CORRECTED_TEST_COMMIT,
        "development/ops_alerts/telegram_corrected_test.py",
        CORRECTED_TEST_SHA256,
    )
    planner_commit_blob = _verify_signed_commit(
        PLANNER_COMMIT, "development/ops_alerts/runtime_status_alerts.py"
    )
    if hashlib.sha256(planner_commit_blob).hexdigest() != PLANNER_SHA256:
        raise NotifierError("SOURCE_ADMISSION_FAILED")
    _verify_external_commit(
        DEPLOY, DEPLOY_COMMIT, "scripts/alert_delivery.py", exact_head=True
    )
    persistence = (
        _external_git(
            PERSISTENCE, ["show", "-s", "--format=%H %G? %GF", PERSISTENCE_COMMIT]
        )
        .decode("ascii", "strict")
        .strip()
    )
    observer_blob = _external_git(
        PERSISTENCE,
        ["show", f"{PERSISTENCE_COMMIT}:kairos_persistence/metrics_exporter.py"],
    )
    observer_path = PERSISTENCE / "kairos_persistence/metrics_exporter.py"
    persistence_head = (
        _external_git(PERSISTENCE, ["rev-parse", "HEAD"])
        .decode("ascii", "strict")
        .strip()
    )
    persistence_branch = (
        _external_git(PERSISTENCE, ["branch", "--show-current"])
        .decode("ascii", "strict")
        .strip()
    )
    persistence_dirty = _external_git(
        PERSISTENCE, ["status", "--porcelain", "--untracked-files=no"]
    )
    if (
        persistence != f"{PERSISTENCE_COMMIT} G {SIGNER}"
        or persistence_head != PERSISTENCE_COMMIT
        or persistence_branch != "main"
        or persistence_dirty
        or hashlib.sha256(observer_blob).hexdigest() != PERSISTENCE_OBSERVER_SHA256
        or hashlib.sha256(
            _read_regular_bytes(observer_path, maximum=256 * 1024)
        ).hexdigest()
        != PERSISTENCE_OBSERVER_SHA256
    ):
        raise NotifierError("SOURCE_ADMISSION_FAILED")
    notifier_path = ROOT / "development/ops_alerts/runtime_status_notifier.py"
    planner_path = ROOT / "development/ops_alerts/runtime_status_alerts.py"
    continuation_path = ROOT / "development/ops_alerts/telegram_continuation.py"
    corrected_path = ROOT / "development/ops_alerts/telegram_corrected_test.py"
    for path, expected in (
        (continuation_path, CONTINUATION_SHA256),
        (corrected_path, CORRECTED_TEST_SHA256),
        (planner_path, PLANNER_SHA256),
    ):
        _verify_working_source(path, expected)
    # Driver must be committed and byte-identical to the admitted signed HEAD.
    tracked = _git(["show", f"HEAD:{notifier_path.relative_to(ROOT).as_posix()}"])
    working_notifier = _read_regular_bytes(notifier_path, maximum=256 * 1024)
    if hashlib.sha256(tracked).digest() != hashlib.sha256(working_notifier).digest():
        raise NotifierError("SOURCE_ADMISSION_FAILED")
    planner_blob = _git(["show", f"HEAD:{planner_path.relative_to(ROOT).as_posix()}"])
    if (
        hashlib.sha256(planner_blob).digest()
        != hashlib.sha256(
            _read_regular_bytes(planner_path, maximum=256 * 1024)
        ).digest()
        or hashlib.sha256(planner_blob).hexdigest() != PLANNER_SHA256
    ):
        raise NotifierError("SOURCE_ADMISSION_FAILED")
    direction_path = ROOT / OWNER_DIRECTION_PATH
    direction_blob = _git(["show", f"HEAD:{OWNER_DIRECTION_PATH}"])
    direction_working = _read_regular_bytes(direction_path, maximum=16 * 1024)
    if (
        hashlib.sha256(direction_blob).hexdigest() != OWNER_DIRECTION_SHA256
        or hashlib.sha256(direction_working).hexdigest() != OWNER_DIRECTION_SHA256
        or direction_blob != direction_working
    ):
        raise NotifierError("SOURCE_ADMISSION_FAILED")
    direction = _parse_owner_direction(direction_working)
    return {
        "head": fields[0],
        "notifier_sha256": hashlib.sha256(tracked).hexdigest(),
        "planner_sha256": hashlib.sha256(planner_blob).hexdigest(),
        "persistence_observer_sha256": PERSISTENCE_OBSERVER_SHA256,
        "owner_direction_sha256": OWNER_DIRECTION_SHA256,
        "requested_routing": direction["requested_routing"],
    }


def _external_git(repo: Path, args: list[str]) -> bytes:
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper()
        in {
            "SYSTEMROOT",
            "WINDIR",
            "PATH",
            "TEMP",
            "TMP",
            "COMSPEC",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "HOMEDRIVE",
            "HOMEPATH",
            "HOME",
            "GNUPGHOME",
        }
    }
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
        }
    )
    try:
        result = subprocess.run(
            ["C:/Program Files/Git/cmd/git.exe", "-C", str(repo), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
            env=env,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise NotifierError("SOURCE_ADMISSION_FAILED") from None
    if result.returncode:
        raise NotifierError("SOURCE_ADMISSION_FAILED")
    return result.stdout


def _verify_external_commit(
    repo: Path, commit: str, path: str, *, exact_head: bool = False
) -> None:
    metadata = (
        _external_git(repo, ["show", "-s", "--format=%H %G? %GF", commit])
        .decode("ascii", "strict")
        .strip()
    )
    source = _external_git(repo, ["show", f"{commit}:{path}"])
    current = repo / path
    if (
        metadata != f"{commit} G {SIGNER}"
        or hashlib.sha256(source).digest()
        != hashlib.sha256(_read_regular_bytes(current, maximum=256 * 1024)).digest()
    ):
        raise NotifierError("SOURCE_ADMISSION_FAILED")
    if exact_head:
        head = (
            _external_git(repo, ["rev-parse", "HEAD"]).decode("ascii", "strict").strip()
        )
        branch = (
            _external_git(repo, ["branch", "--show-current"])
            .decode("ascii", "strict")
            .strip()
        )
        dirty = _external_git(repo, ["status", "--porcelain", "--untracked-files=no"])
        if head != commit or branch != "main" or dirty:
            raise NotifierError("SOURCE_ADMISSION_FAILED")


def _helpers() -> tuple[Any, Any, Any, Any]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if str(DEPLOY) not in sys.path:
        sys.path.insert(0, str(DEPLOY))
    if str(PERSISTENCE) not in sys.path:
        sys.path.insert(0, str(PERSISTENCE))
    from development.ops_alerts import runtime_status_alerts as planner
    from development.ops_alerts import telegram_continuation as continuation
    from development.ops_alerts import telegram_corrected_test as corrected
    from scripts import alert_delivery

    approved_delivery, _diagnostic, _handoff = continuation._load_signed_sources()
    if approved_delivery is not alert_delivery:
        raise NotifierError("SOURCE_ADMISSION_FAILED")

    return planner, continuation, corrected, alert_delivery


def _read_private(
    path: Path,
    *,
    maximum: int,
    no_reparse: Callable[[Path], None],
    private_acl: Callable[[Path], None],
) -> bytes:
    try:
        no_reparse(path)
        private_acl(path)
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or path.is_symlink()
            or getattr(before, "st_file_attributes", 0) & 0x400
            or before.st_size > maximum
        ):
            raise NotifierError("PROTECTED_EVIDENCE_REQUIRED")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise NotifierError("PROTECTED_EVIDENCE_REQUIRED")
            raw = stream.read(maximum + 1)
        if len(raw) > maximum or len(raw) != before.st_size:
            raise NotifierError("PROTECTED_EVIDENCE_REQUIRED")
        return raw
    except NotifierError:
        raise
    except Exception:  # noqa: BLE001 - never expose path, ACL, or OS details.
        raise NotifierError("PROTECTED_EVIDENCE_REQUIRED") from None


def validate_corrected_receipt(
    paths: dict[str, Path], *, continuation: Any, delivery: Any
) -> tuple[dict[str, Any], str]:
    raw = _read_private(
        paths["result"],
        maximum=16 * 1024,
        no_reparse=delivery._no_reparse,
        private_acl=delivery._private_acl,
    )
    digest = hashlib.sha256(raw).hexdigest()
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeError):
        raise NotifierError("CORRECTED_TEST_RECEIPT_INVALID") from None
    if (
        digest != CORRECTED_RESULT_SHA256
        or not isinstance(obj, dict)
        or obj.get("kind") != "kairos.telegram.corrected-chat-test.v1"
        or obj.get("status") != "TRANSPORT_ACCEPTED"
        or obj.get("stage") != "TRANSPORT_ACCEPTED"
        or obj.get("corrected_test_chat_id") != CORRECTED_CHAT_ID
        or obj.get("expected_bot_username") != delivery.EXPECTED_BOT
        or delivery.EXPECTED_BOT != EXPECTED_BOT
        or obj.get("implementation_sha256") != CORRECTED_TEST_SHA256
        or obj.get("transport_accepted") is not True
        or obj.get("message_id") != CORRECTED_MESSAGE_ID
        or obj.get("send_attempts") != 1
        or obj.get("http_method_counts") != {"getMe": 1, "getChat": 1, "sendMessage": 1}
        or obj.get("human_acknowledged") is not False
        or obj.get("automatic_retry") is not False
        or obj.get("trading_authority") is not False
        or obj.get("delivery_qualified") is not False
        or obj.get("operationally_qualified") is not False
    ):
        raise NotifierError("CORRECTED_TEST_RECEIPT_INVALID")
    return obj, digest


def _write_exclusive(
    path: Path, payload: bytes, continuation: Any, private_acl: Callable[[Path], None]
) -> None:
    continuation._exclusive_fsync(path, payload)
    continuation._set_exact_file_acl(path)
    private_acl(path)


def record_owner_acceptance(
    *, source_admitter: Callable[[], Any] = admit_sources
) -> dict[str, Any]:
    source = source_admitter()
    _planner, continuation, corrected, delivery = _helpers()
    paths = corrected._paths(continuation, delivery)
    _receipt, digest = validate_corrected_receipt(
        paths, continuation=continuation, delivery=delivery
    )
    if not PRIVATE_ROOT.is_dir() or PRIVATE_ROOT.is_symlink():
        raise NotifierError("PROTECTED_ROOT_REQUIRED")
    delivery._no_reparse(PRIVATE_ROOT)
    delivery._private_acl(PRIVATE_ROOT)
    for private_path in (paths["root"] / "secrets", paths["token"]):
        delivery._no_reparse(private_path)
        delivery._private_acl(private_path)
    handoff = _read_private(
        continuation.HANDOFF,
        maximum=4096,
        no_reparse=delivery._no_reparse,
        private_acl=delivery._private_acl,
    )
    handoff_digest = hashlib.sha256(handoff).hexdigest()
    if handoff_digest != continuation.HANDOFF_SHA256:
        raise NotifierError("PROTECTED_EVIDENCE_REQUIRED")
    _parse_handoff(handoff, continuation)
    direction_raw = _read_regular_bytes(ROOT / OWNER_DIRECTION_PATH, maximum=16 * 1024)
    direction = _parse_owner_direction(direction_raw)
    direction_digest = hashlib.sha256(direction_raw).hexdigest()
    if (
        direction_digest != OWNER_DIRECTION_SHA256
        or source.get("owner_direction_sha256") != direction_digest
        or source.get("requested_routing") != direction.get("requested_routing")
    ):
        raise NotifierError("OWNER_DIRECTION_INVALID")
    ack = {
        "schema_version": 1,
        "kind": "kairos.runtime-status.owner-acceptance.v1",
        "status": "RECORDED_OWNER_DIRECTION_ATTESTATION",
        "basis": "DIRECT_OWNER_REPLY_IN_CURRENT_TASK",
        "acknowledgement": ACK_TEXT,
        "acknowledgement_source": "DIRECT_OWNER_REPLY",
        "human_acknowledged": True,
        "telegram_user_authenticated": False,
        "chat_id": CORRECTED_CHAT_ID,
        "corrected_test_receipt_sha256": digest,
        "corrected_test_message_id": CORRECTED_MESSAGE_ID,
        "corrected_test_chat_id": CORRECTED_CHAT_ID,
        "handoff_sha256": handoff_digest,
        "notifier_sha256": source["notifier_sha256"],
        "owner_direction_sha256": direction_digest,
        "requested_routing": direction["requested_routing"],
        "routing": "temporary-corrected-group",
        "enabled_alert_classes": ["technical_runtime"],
        "disabled_alert_classes": ["strategy", "risk", "trading"],
        "trading_authority": False,
        "created_at_utc": datetime.now(UTC).isoformat(),
    }
    target = PRIVATE_ROOT / "owner-acceptance.json"
    with _lease(PRIVATE_ROOT, continuation, delivery):
        if target.exists():
            raise NotifierError("ACCEPTANCE_ALREADY_RECORDED")
        _write_exclusive(target, _json_bytes(ack), continuation, delivery._private_acl)
    return {"status": "OWNER_ACCEPTANCE_RECORDED", "send_attempts": 0}


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    )


@contextmanager
def _lease(root: Path, continuation: Any, delivery: Any):
    lease = root / "notifier.lock"
    token = uuid.uuid4().hex.encode("ascii")
    try:
        fd = os.open(
            lease,
            os.O_CREAT
            | os.O_EXCL
            | os.O_WRONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except FileExistsError:
        raise NotifierError("SINGLETON_BUSY_OR_STALE_LEASE") from None
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(token)
            stream.flush()
            os.fsync(stream.fileno())
        continuation._set_exact_file_acl(lease)
        delivery._private_acl(lease)
        yield
    finally:
        try:
            if (
                _read_private(
                    lease,
                    maximum=64,
                    no_reparse=delivery._no_reparse,
                    private_acl=delivery._private_acl,
                )
                != token
            ):
                raise NotifierError("LEASE_CHANGED")
            lease.unlink()
        except (OSError, NotifierError):
            # If ownership cannot be proven, preserve the lease fail-closed.
            pass


def _journal(planner: Any, root: Path, continuation: Any, delivery: Any) -> Any:
    return planner.FileJournal(
        root / "events.jsonl",
        secure_new_file=continuation._set_exact_file_acl,
        verify_private_file=delivery._private_acl,
    )


def _sender_factory(
    *,
    token_path: Path,
    delivery: Any,
    continuation: Any,
    receipt_path: Callable[[str], Path],
    expected_token_sha256: str,
):
    def send(alert: Any) -> bool:
        # Message is produced solely by planner constants; never append status data.
        if (
            not isinstance(alert.event_id, str)
            or re.fullmatch(r"[0-9a-f]{64}", alert.event_id) is None
            or (alert.transition == "firing" and alert.state not in _FIRING_STATES)
            or (alert.transition == "resolved" and alert.state != "running_fresh")
            or alert.transition not in {"firing", "resolved"}
        ):
            raise NotifierError("ALERT_TEMPLATE_REJECTED")
        expected_message = (
            "[Kairos R4] Runtime status is unhealthy. Trading remains disabled."
            if alert.transition == "firing"
            else "[Kairos R4] Runtime status returned to fresh RUNNING_NONTRADING. Trading remains disabled."
        )
        if alert.message != expected_message:
            raise NotifierError("ALERT_TEMPLATE_REJECTED")
        token_raw = _read_private(
            token_path,
            maximum=256,
            no_reparse=delivery._no_reparse,
            private_acl=delivery._private_acl,
        )
        token = continuation._decode_token(token_raw)
        if (
            not token.startswith(TOKEN_PREFIX)
            or hashlib.sha256(token.encode("utf-8")).hexdigest()
            != expected_token_sha256
        ):
            raise NotifierError("TOKEN_INVALID")
        transport = delivery.TelegramTransport(token)
        response = transport.call(
            "sendMessage",
            {
                "chat_id": CORRECTED_CHAT_ID,
                "text": alert.message,
                "protect_content": True,
            },
        )
        if (
            not isinstance(response, dict)
            or type(response.get("message_id")) is not int
            or response.get("message_id") < 1
            or type(response.get("date")) is not int
            or not isinstance(response.get("chat"), dict)
            or type(response["chat"].get("id")) is not int
            or response["chat"]["id"] != CORRECTED_CHAT_ID
        ):
            raise NotifierError("SEND_OUTCOME_UNKNOWN")
        receipt = {
            "schema_version": 1,
            "kind": "kairos.runtime-status.telegram-send-receipt.v1",
            "event_id": alert.event_id,
            "transition": alert.transition,
            "state": alert.state,
            "recipient_chat_id": CORRECTED_CHAT_ID,
            "message_id": response["message_id"],
            "telegram_date": response["date"],
            "accepted_at_utc": datetime.now(UTC).isoformat(),
            "protect_content": True,
            "trading_authority": False,
        }
        _write_exclusive(
            receipt_path(alert.event_id),
            _json_bytes(receipt),
            continuation,
            delivery._private_acl,
        )
        return True

    return send


def poll_once(
    *, source_admitter: Callable[[], Any] = admit_sources, _lease_held: bool = False
) -> dict[str, Any]:
    source = source_admitter()
    planner, continuation, corrected, delivery = _helpers()
    paths = corrected._paths(continuation, delivery)
    validate_corrected_receipt(paths, continuation=continuation, delivery=delivery)
    acceptance_path = PRIVATE_ROOT / "owner-acceptance.json"
    try:
        acceptance = json.loads(
            _read_private(
                acceptance_path,
                maximum=4096,
                no_reparse=delivery._no_reparse,
                private_acl=delivery._private_acl,
            ),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (ValueError, TypeError, UnicodeError):
        raise NotifierError("OWNER_ACCEPTANCE_INVALID") from None
    handoff_raw = _read_private(
        continuation.HANDOFF,
        maximum=4096,
        no_reparse=delivery._no_reparse,
        private_acl=delivery._private_acl,
    )
    handoff_digest = hashlib.sha256(handoff_raw).hexdigest()
    handoff = _parse_handoff(handoff_raw, continuation)
    direction_raw = _read_regular_bytes(ROOT / OWNER_DIRECTION_PATH, maximum=16 * 1024)
    direction = _parse_owner_direction(direction_raw)
    direction_digest = hashlib.sha256(direction_raw).hexdigest()
    try:
        ack_time = datetime.fromisoformat(acceptance["created_at_utc"])
    except (KeyError, TypeError, ValueError):
        raise NotifierError("OWNER_ACCEPTANCE_INVALID") from None
    if (
        not isinstance(acceptance, dict)
        or set(acceptance)
        != {
            "schema_version",
            "kind",
            "status",
            "basis",
            "acknowledgement",
            "acknowledgement_source",
            "human_acknowledged",
            "telegram_user_authenticated",
            "chat_id",
            "corrected_test_receipt_sha256",
            "corrected_test_message_id",
            "corrected_test_chat_id",
            "handoff_sha256",
            "notifier_sha256",
            "owner_direction_sha256",
            "requested_routing",
            "routing",
            "enabled_alert_classes",
            "disabled_alert_classes",
            "trading_authority",
            "created_at_utc",
        }
        or acceptance.get("schema_version") != 1
        or acceptance.get("kind") != "kairos.runtime-status.owner-acceptance.v1"
        or acceptance.get("status") != "RECORDED_OWNER_DIRECTION_ATTESTATION"
        or acceptance.get("basis") != "DIRECT_OWNER_REPLY_IN_CURRENT_TASK"
        or acceptance.get("acknowledgement") != ACK_TEXT
        or acceptance.get("acknowledgement_source") != "DIRECT_OWNER_REPLY"
        or acceptance.get("human_acknowledged") is not True
        or acceptance.get("telegram_user_authenticated") is not False
        or acceptance.get("corrected_test_receipt_sha256") != CORRECTED_RESULT_SHA256
        or acceptance.get("corrected_test_message_id") != CORRECTED_MESSAGE_ID
        or acceptance.get("corrected_test_chat_id") != CORRECTED_CHAT_ID
        or acceptance.get("chat_id") != CORRECTED_CHAT_ID
        or acceptance.get("notifier_sha256") != source.get("notifier_sha256")
        or acceptance.get("owner_direction_sha256")
        != source.get("owner_direction_sha256")
        or acceptance.get("requested_routing") != source.get("requested_routing")
        or acceptance.get("handoff_sha256") != handoff_digest
        or acceptance.get("owner_direction_sha256") != direction_digest
        or direction_digest != OWNER_DIRECTION_SHA256
        or acceptance.get("requested_routing") != OWNER_ROUTING
        or direction.get("temporary_chat_id") != CORRECTED_CHAT_ID
        or handoff_digest != continuation.HANDOFF_SHA256
        or acceptance.get("routing") != "temporary-corrected-group"
        or acceptance.get("enabled_alert_classes") != ["technical_runtime"]
        or acceptance.get("disabled_alert_classes") != ["strategy", "risk", "trading"]
        or acceptance.get("trading_authority") is not False
        or ack_time.tzinfo is None
        or ack_time.utcoffset() != dt.timedelta(0)
    ):
        raise NotifierError("OWNER_ACCEPTANCE_INVALID")
    delivery._no_reparse(PRIVATE_ROOT)
    delivery._private_acl(PRIVATE_ROOT)

    def run_poll():
        journal = _journal(planner, PRIVATE_ROOT, continuation, delivery)
        receipt_path = lambda event_id: (
            PRIVATE_ROOT / ("telegram-" + event_id + ".json")
        )
        sender = _sender_factory(
            token_path=paths["token"],
            delivery=delivery,
            continuation=continuation,
            receipt_path=receipt_path,
            expected_token_sha256=handoff["current_token_sha256"],
        )
        engine = planner.RuntimeStatusAlertPlanner(journal=journal, sender=sender)
        return engine.poll_once()

    if _lease_held:
        result = run_poll()
    else:
        with _lease(PRIVATE_ROOT, continuation, delivery):
            result = run_poll()
    return {
        "status": result.status,
        "state": result.state,
        "send_attempts": result.send_attempts,
        "trading_authority": False,
    }


def serve(
    *,
    source_admitter: Callable[[], Any] = admit_sources,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    source_admitter()
    _planner, continuation, _corrected, delivery = _helpers()
    started = time.monotonic()
    attempts = 0
    last: dict[str, Any] = {"status": "SERVING", "send_attempts": 0}
    polls = 0
    with _lease(PRIVATE_ROOT, continuation, delivery):
        while time.monotonic() - started < MAX_SERVE_SECONDS:
            last = poll_once(source_admitter=source_admitter, _lease_held=True)
            polls += 1
            attempts += int(last.get("send_attempts", 0))
            if last.get("status") in {
                "journal_blocked",
                "send_outcome_unknown",
                "send_outcome_unknown_or_journal_failed",
                "send_outcome_unknown_or_unresolved",
            }:
                break
            remaining = MAX_SERVE_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                break
            sleep(min(POLL_SECONDS, remaining))
    return {
        "status": "BOUNDED_WINDOW_COMPLETE",
        "polls": polls,
        "send_attempts": attempts,
        "last_status": last.get("status"),
        "trading_authority": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--record-owner-acceptance", action="store_true")
    modes.add_argument("--poll-once", action="store_true")
    modes.add_argument("--serve", action="store_true")
    parser.add_argument(
        "--armed", action="store_true", help="required for any delivery-enabled run"
    )
    args = parser.parse_args(argv)
    if not (args.record_owner_acceptance or args.poll_once or args.serve):
        print(
            json.dumps(
                {
                    "status": "PLAN_ONLY",
                    "send_attempts": 0,
                    "network_calls": 0,
                    "trading_authority": False,
                },
                sort_keys=True,
            )
        )
        return 0
    if not args.armed and not args.record_owner_acceptance:
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
        report = (
            record_owner_acceptance()
            if args.record_owner_acceptance
            else (serve() if args.serve else poll_once())
        )
    except Exception as error:  # noqa: BLE001 - public output is category-only.
        category = getattr(error, "category", None)
        if category not in {
            "SOURCE_ADMISSION_FAILED",
            "PROTECTED_EVIDENCE_REQUIRED",
            "PROTECTED_ROOT_REQUIRED",
            "CORRECTED_TEST_RECEIPT_INVALID",
            "ACCEPTANCE_ALREADY_RECORDED",
            "SINGLETON_BUSY_OR_STALE_LEASE",
            "OWNER_ACCEPTANCE_INVALID",
            "TOKEN_INVALID",
            "SEND_OUTCOME_UNKNOWN",
        }:
            category = "NOTIFIER_BLOCKED"
        report = {
            "status": "BLOCKED",
            "error_category": category,
            "send_attempts": None,
            "trading_authority": False,
        }
    print(json.dumps(report, sort_keys=True))
    failed = report.get("status") in {
        "BLOCKED",
        "journal_blocked",
        "send_outcome_unknown",
        "send_outcome_unknown_or_journal_failed",
        "send_outcome_unknown_or_unresolved",
    } or (
        report.get("status") == "BOUNDED_WINDOW_COMPLETE"
        and report.get("last_status")
        in {
            "journal_blocked",
            "send_outcome_unknown",
            "send_outcome_unknown_or_journal_failed",
            "send_outcome_unknown_or_unresolved",
        }
    )
    return 2 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
