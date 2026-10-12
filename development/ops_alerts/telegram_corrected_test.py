"""One authorized test delivery to the corrected Telegram group only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

KAIROS_ROOT = Path("D:/Kairos/kairos")
CONTINUATION_PATH = KAIROS_ROOT / "development/ops_alerts/telegram_continuation.py"
CONTINUATION_COMMIT = "f7b2f249c028a4a947b7279e677f21ee85bee8fc"
CONTINUATION_SHA256 = "b308e19753be088966e3fed4d1ddacc47ca3ef8d90089d1c527d1c93813d3930"
DEPLOY_SHA = "0427f7cf1e1cd70f2ddd05b80b4d7d6219736412"
TRUSTED_FINGERPRINT = "40AF365C6682B73D056A6A274DBFF6B65BE9F827"
CORRECTED_CHAT_ID = -1004475802889
OLD_FAILED_READONLY_SHA256 = (
    "d97b016332038598b46cc1b414b9610ff28ee45b1df1bc8ab76577482f80bd86"
)
OBSERVED_PREFLIGHT_SOURCE_SHA256 = (
    "51be3ef2ab6e4672e2e4a6d4a014fec5de5300956faa1f44457194d1431960ff"
)
OBSERVED_PREFLIGHT_GUARD_SHA256 = (
    "80fc29b552af48b9f4feb37543df168235f1046849509e812a7fe9b0cf10a5af"
)
OLD_CHAT_ID = -100447580288
PURPOSE = "corrected_group_test_only"

_SAFE_ERRORS = {
    "ACL_VERIFICATION_FAILED",
    "API_REJECTED",
    "BOT_IDENTITY_MISMATCH",
    "CHAT_IDENTITY_MISMATCH",
    "DEDICATED_TOKEN_FILE_REQUIRED",
    "HTTP_REJECTED",
    "INVALID_TOKEN_FILE",
    "LOCAL_FAILURE",
    "LOCAL_VALIDATION_FAILED",
    "METHOD_REJECTED",
    "PROTECTED_ACL_REQUIRED",
    "READ_ONLY_METHOD_REJECTED",
    "REDIRECT_REJECTED",
    "RESPONSE_TOO_LARGE",
    "SEND_OUTCOME_UNKNOWN",
    "SEND_RESPONSE_IDENTITY_MISMATCH",
    "TRANSPORT_FAILED",
}


class CorrectedTestError(Exception):
    """Fixed public error category; never retain raw transport details."""

    def __init__(self, category: str) -> None:
        self.category = (
            category if category in _SAFE_ERRORS else "LOCAL_VALIDATION_FAILED"
        )
        super().__init__(self.category)


def _verify_continuation_pin(
    *,
    root: Path,
    helper_path: Path,
    expected_helper_hash: str,
    commit_id: str,
    git: Path,
    signer: str,
    run: Callable[..., Any] = subprocess.run,
) -> None:
    """Verify signed ancestor blob and exact working helper before importing it."""
    try:
        metadata = helper_path.lstat()
        if (
            helper_path.resolve(strict=True) != helper_path
            or stat.S_ISLNK(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > 256 * 1024
        ):
            raise CorrectedTestError("LOCAL_VALIDATION_FAILED")
    except OSError:
        raise CorrectedTestError("LOCAL_VALIDATION_FAILED")
    if hashlib.sha256(helper_path.read_bytes()).hexdigest() != expected_helper_hash:
        raise CorrectedTestError("LOCAL_VALIDATION_FAILED")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
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
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
        }
    )
    blob = f"{commit_id}:development/ops_alerts/telegram_continuation.py"
    try:
        signed = run(
            [
                str(git),
                "-C",
                str(root),
                "show",
                "-s",
                "--format=%H %G? %GF",
                commit_id,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=20,
            check=False,
            env=environment,
            shell=False,
        )
        ancestor = run(
            [
                str(git),
                "-C",
                str(root),
                "merge-base",
                "--is-ancestor",
                commit_id,
                "HEAD",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
            env=environment,
            shell=False,
        )
        size = run(
            [str(git), "-C", str(root), "cat-file", "-s", blob],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
            check=False,
            env=environment,
            shell=False,
        )
        if (
            size.returncode
            or not size.stdout.strip().isdigit()
            or int(size.stdout.strip()) > 256 * 1024
        ):
            raise CorrectedTestError("LOCAL_VALIDATION_FAILED")
        source = run(
            [str(git), "-C", str(root), "show", blob],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
            env=environment,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise CorrectedTestError("LOCAL_VALIDATION_FAILED") from None
    if (
        signed.returncode
        or signed.stdout.strip() != f"{commit_id} G {signer}"
        or ancestor.returncode
        or source.returncode
        or hashlib.sha256(source.stdout).hexdigest() != expected_helper_hash
    ):
        raise CorrectedTestError("LOCAL_VALIDATION_FAILED")


def _load_pinned():
    _verify_continuation_pin(
        root=KAIROS_ROOT,
        helper_path=CONTINUATION_PATH,
        expected_helper_hash=CONTINUATION_SHA256,
        commit_id=CONTINUATION_COMMIT,
        git=Path("C:/Program Files/Git/cmd/git.exe"),
        signer=TRUSTED_FINGERPRINT,
    )
    if str(KAIROS_ROOT) not in sys.path:
        sys.path.insert(0, str(KAIROS_ROOT))
    from development.ops_alerts import telegram_continuation as continuation

    if (
        Path(continuation.__file__).resolve(strict=True)
        != CONTINUATION_PATH.resolve(strict=True)
        or hashlib.sha256(CONTINUATION_PATH.read_bytes()).hexdigest()
        != CONTINUATION_SHA256
    ):
        raise CorrectedTestError("LOCAL_VALIDATION_FAILED")
    delivery, diagnostic, handoff = continuation._load_signed_sources()
    if handoff.DEPLOY_SHA != DEPLOY_SHA or handoff.SIGNER != TRUSTED_FINGERPRINT:
        raise CorrectedTestError("LOCAL_VALIDATION_FAILED")
    return continuation, delivery, diagnostic, handoff


def _paths(continuation: Any, delivery: Any) -> dict[str, Path]:
    scope = hashlib.sha256(
        delivery.canonical(
            {
                "bot": delivery.EXPECTED_BOT,
                "chat": CORRECTED_CHAT_ID,
                "purpose": PURPOSE,
            }
        )
    ).hexdigest()
    stem = "telegram-corrected-chat-test-" + scope
    receipts = continuation.NEW_ROOT / "receipts"
    return {
        "root": continuation.NEW_ROOT,
        "old_root": continuation.OLD_ROOT,
        "token": continuation.NEW_ROOT / "secrets/telegram_bot_token",
        "old_token": continuation.OLD_ROOT / "secrets/telegram_bot_token",
        "handoff": continuation.HANDOFF,
        "reserve": continuation.RESERVE,
        "prior_result": continuation.RESULT,
        "prior_guard": continuation.GUARD,
        "guard": receipts / (stem + ".guard"),
        "send_reserved": receipts / (stem + ".send-reserved.json"),
        "result": receipts / (stem + ".result.json"),
    }


def _read_preflight(
    *,
    paths: dict[str, Path],
    continuation: Any,
    delivery: Any,
    handoff: Any,
    no_reparse: Callable[[Path], None],
    private_acl: Callable[[Path], None],
) -> tuple[str, str, str, str]:
    all_paths = (
        paths["root"],
        paths["root"] / "secrets",
        paths["root"] / "receipts",
        paths["token"],
        paths["old_root"],
        paths["old_root"] / "secrets",
        paths["old_token"],
        paths["handoff"],
        paths["reserve"],
        paths["prior_result"],
        paths["prior_guard"],
        paths["guard"],
        paths["send_reserved"],
        paths["result"],
        handoff.KEY_SOURCE,
    )
    for path in all_paths:
        continuation._check_path(path, no_reparse)
    for path in (
        paths["root"],
        paths["root"] / "secrets",
        paths["root"] / "receipts",
        paths["token"],
        paths["handoff"],
        paths["reserve"],
        paths["prior_result"],
        paths["prior_guard"],
        paths["old_root"],
        paths["old_root"] / "secrets",
        paths["old_token"],
    ):
        private_acl(path)

    handoff_raw, handoff_hash = continuation._digest(paths["handoff"], maximum=4096)
    reserve_raw, reserve_hash = continuation._digest(paths["reserve"], maximum=256)
    if (
        handoff_hash != continuation.HANDOFF_SHA256
        or reserve_hash != continuation.RESERVE_SHA256
        or len(reserve_raw) != continuation.RESERVE_BYTES
    ):
        raise CorrectedTestError("LOCAL_VALIDATION_FAILED")

    prior_raw, prior_hash = continuation._digest(
        paths["prior_result"], maximum=16 * 1024
    )
    if prior_hash != OLD_FAILED_READONLY_SHA256:
        raise CorrectedTestError("LOCAL_VALIDATION_FAILED")
    _, prior_guard_hash = continuation._digest(paths["prior_guard"], maximum=4096)
    if prior_guard_hash != OBSERVED_PREFLIGHT_GUARD_SHA256:
        raise CorrectedTestError("LOCAL_VALIDATION_FAILED")
    try:
        prior = json.loads(prior_raw)
    except (ValueError, UnicodeError):
        raise CorrectedTestError("LOCAL_VALIDATION_FAILED") from None
    if (
        not isinstance(prior, dict)
        or prior.get("kind") != "kairos.telegram.readonly-continuation.v1"
        or prior.get("implementation_sha256") != OBSERVED_PREFLIGHT_SOURCE_SHA256
        or prior.get("guard_sha256") != prior_guard_hash
        or prior.get("handoff_sha256") != handoff_hash
        or prior.get("reserve_sha256") != reserve_hash
        or prior.get("automatic_retry") is not False
        or prior.get("expected_bot_username") != delivery.EXPECTED_BOT
        or type(prior.get("expected_test_chat_id")) is not int
        or prior.get("expected_test_chat_id") != OLD_CHAT_ID
        or prior.get("status") != "BLOCKED"
        or prior.get("http_method_counts") != {"getMe": 1, "getChat": 1}
        or type(prior.get("send_attempts")) is not int
        or prior.get("send_attempts") != 0
        or prior.get("chat_identity_verified") is not False
        or prior.get("delivery_qualified") is not False
        or prior.get("trading_authority") is not False
        or prior.get("error_category") != "CHAT_NOT_FOUND"
    ):
        raise CorrectedTestError("LOCAL_VALIDATION_FAILED")

    token_raw, _ = continuation._digest(paths["token"], maximum=256)
    old_token_raw, _ = continuation._digest(paths["old_token"], maximum=256)
    token = continuation._decode_token(token_raw)
    old_token = continuation._decode_token(old_token_raw)
    continuation._validate_handoff(handoff_raw, token, old_token, handoff)
    if handoff.KEY_SOURCE.stat().st_size > 32768:
        raise CorrectedTestError("LOCAL_VALIDATION_FAILED")
    try:
        source_token = handoff.choose_current_token(
            handoff.KEY_SOURCE.read_text(encoding="utf-8"), old_token
        )
    except Exception:  # noqa: BLE001 - never reveal key-source material.
        raise CorrectedTestError("LOCAL_VALIDATION_FAILED") from None
    if source_token != token:
        raise CorrectedTestError("LOCAL_VALIDATION_FAILED")
    return token, handoff_hash, reserve_hash, prior_hash


def _safe_error(error: Any) -> str:
    category = getattr(error, "category", None)
    return (
        category
        if isinstance(category, str) and category in _SAFE_ERRORS
        else "LOCAL_FAILURE"
    )


def _result_template(
    *,
    delivery: Any,
    source_sha256: str,
    handoff_sha256: str,
    reserve_sha256: str,
    prior_result_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "kairos.telegram.corrected-chat-test.v1",
        "status": "BLOCKED",
        "stage": "PRECHECK_FAILED",
        "error_category": None,
        "corrected_test_chat_id": CORRECTED_CHAT_ID,
        "expected_bot_username": delivery.EXPECTED_BOT,
        "http_method_counts": {"getMe": 0, "getChat": 0, "sendMessage": 0},
        "send_attempts": 0,
        "transport_accepted": False,
        "human_acknowledged": False,
        "operationally_qualified": False,
        "delivery_qualified": False,
        "trading_authority": False,
        "automatic_retry": False,
        "implementation_sha256": source_sha256,
        "handoff_sha256": handoff_sha256,
        "reserve_sha256": reserve_sha256,
        "prior_readonly_result_sha256": prior_result_sha256,
        "test_message_sha256": hashlib.sha256(
            delivery.TEST_MESSAGE.encode()
        ).hexdigest(),
    }


def _write_private(
    *,
    path: Path,
    payload: bytes,
    exclusive_fsync: Callable[[Path, bytes], None],
    set_file_acl: Callable[[Path], None],
    private_acl: Callable[[Path], None],
) -> None:
    exclusive_fsync(path, payload)
    set_file_acl(path)
    private_acl(path)


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    )


def _execute_once(
    *,
    authorize: bool,
    continuation: Any,
    delivery: Any,
    handoff: Any,
    paths: dict[str, Path],
    no_reparse: Callable[[Path], None],
    private_acl: Callable[[Path], None],
    exclusive_fsync: Callable[[Path, bytes], None],
    set_file_acl: Callable[[Path], None],
    transport_factory: Callable[[str], Any],
    source_bytes: bytes,
) -> dict[str, Any]:
    if authorize is not True:
        raise CorrectedTestError("LOCAL_VALIDATION_FAILED")
    for name in ("guard", "send_reserved", "result"):
        if paths[name].exists() or paths[name].is_symlink():
            raise CorrectedTestError("LOCAL_VALIDATION_FAILED")
    receipts = paths["root"] / "receipts"
    try:
        if any(
            item.name.startswith("telegram-corrected-chat-test-")
            for item in receipts.iterdir()
        ):
            raise CorrectedTestError("LOCAL_VALIDATION_FAILED")
    except OSError:
        raise CorrectedTestError("LOCAL_VALIDATION_FAILED") from None

    token, handoff_hash, reserve_hash, prior_hash = _read_preflight(
        paths=paths,
        continuation=continuation,
        delivery=delivery,
        handoff=handoff,
        no_reparse=no_reparse,
        private_acl=private_acl,
    )
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    report = _result_template(
        delivery=delivery,
        source_sha256=source_sha,
        handoff_sha256=handoff_hash,
        reserve_sha256=reserve_hash,
        prior_result_sha256=prior_hash,
    )
    guard = {
        "schema_version": 1,
        "kind": "KAIROS_CORRECTED_CHAT_TEST_GUARD_V1",
        "purpose": PURPOSE,
        "corrected_test_chat_id": CORRECTED_CHAT_ID,
        "handoff_sha256": handoff_hash,
        "reserve_sha256": reserve_hash,
        "prior_readonly_result_sha256": prior_hash,
        "implementation_sha256": source_sha,
        "automatic_retry": False,
        "send_attempts": 0,
        "trading_authority": False,
    }
    _write_private(
        path=paths["guard"],
        payload=_json_bytes(guard),
        exclusive_fsync=exclusive_fsync,
        set_file_acl=set_file_acl,
        private_acl=private_acl,
    )

    sending = False
    try:
        transport = transport_factory(token)
        report["http_method_counts"]["getMe"] = 1
        identity = transport.call("getMe", {})
        if (
            not isinstance(identity, dict)
            or type(identity.get("id")) is not int
            or identity.get("id") != continuation.EXPECTED_BOT_ID
            or identity.get("is_bot") is not True
            or identity.get("username") != delivery.EXPECTED_BOT
        ):
            report["error_category"] = "BOT_IDENTITY_MISMATCH"
            return _write_result(
                report, paths, exclusive_fsync, set_file_acl, private_acl
            )

        report["http_method_counts"]["getChat"] = 1
        chat = transport.call("getChat", {"chat_id": CORRECTED_CHAT_ID})
        if (
            not isinstance(chat, dict)
            or type(chat.get("id")) is not int
            or chat.get("id") != CORRECTED_CHAT_ID
            or chat.get("type") not in {"group", "supergroup"}
        ):
            report["error_category"] = "CHAT_IDENTITY_MISMATCH"
            return _write_result(
                report, paths, exclusive_fsync, set_file_acl, private_acl
            )

        reserved = {
            "schema_version": 1,
            "kind": "KAIROS_CORRECTED_CHAT_TEST_SEND_RESERVED_V1",
            "stage": "SEND_RESERVED",
            "purpose": PURPOSE,
            "corrected_test_chat_id": CORRECTED_CHAT_ID,
            "guard_sha256": hashlib.sha256(paths["guard"].read_bytes()).hexdigest(),
            "send_attempts": 0,
            "max_send_attempts": 1,
            "http_method_counts": {"getMe": 1, "getChat": 1, "sendMessage": 0},
            "automatic_retry": False,
            "trading_authority": False,
        }
        _write_private(
            path=paths["send_reserved"],
            payload=_json_bytes(reserved),
            exclusive_fsync=exclusive_fsync,
            set_file_acl=set_file_acl,
            private_acl=private_acl,
        )

        # The durable reservation and ACL check complete before this sole send.
        sending = True
        report["stage"] = "SEND_OUTCOME_UNKNOWN"
        report["send_attempts"] = 1
        report["http_method_counts"]["sendMessage"] = 1
        sent = transport.call(
            "sendMessage",
            {
                "chat_id": CORRECTED_CHAT_ID,
                "text": delivery.TEST_MESSAGE,
                "disable_notification": False,
                "protect_content": True,
            },
        )
        if (
            not isinstance(sent, dict)
            or not isinstance(sent.get("chat"), dict)
            or type(sent["chat"].get("id")) is not int
            or sent["chat"].get("id") != CORRECTED_CHAT_ID
            or type(sent.get("message_id")) is not int
            or sent.get("message_id") <= 0
        ):
            report["error_category"] = "SEND_OUTCOME_UNKNOWN"
            return _write_result(
                report, paths, exclusive_fsync, set_file_acl, private_acl
            )
        report["status"] = "TRANSPORT_ACCEPTED"
        report["stage"] = "TRANSPORT_ACCEPTED"
        report["transport_accepted"] = True
        report["message_id"] = sent["message_id"]
    except Exception as error:  # noqa: BLE001 - don't serialize transport exception.
        report["stage"] = "SEND_OUTCOME_UNKNOWN" if sending else "PRECHECK_FAILED"
        report["status"] = "BLOCKED"
        report["error_category"] = (
            "SEND_OUTCOME_UNKNOWN" if sending else _safe_error(error)
        )
    return _write_result(report, paths, exclusive_fsync, set_file_acl, private_acl)


def _write_result(
    report: dict[str, Any],
    paths: dict[str, Path],
    exclusive_fsync: Callable[[Path, bytes], None],
    set_file_acl: Callable[[Path], None],
    private_acl: Callable[[Path], None],
) -> dict[str, Any]:
    if report["error_category"] not in (None, *_SAFE_ERRORS):
        report["error_category"] = "LOCAL_FAILURE"
    report["observed_at_utc"] = datetime.now(UTC).isoformat()
    _write_private(
        path=paths["result"],
        payload=_json_bytes(report),
        exclusive_fsync=exclusive_fsync,
        set_file_acl=set_file_acl,
        private_acl=private_acl,
    )
    return report


def run_corrected_test(*, authorize: bool) -> dict[str, Any]:
    if authorize is not True:
        raise CorrectedTestError("LOCAL_VALIDATION_FAILED")
    continuation, delivery, _diagnostic, handoff = _load_pinned()
    paths = _paths(continuation, delivery)
    source_path = Path(__file__).resolve(strict=True)
    source_bytes = source_path.read_bytes()
    return _execute_once(
        authorize=True,
        continuation=continuation,
        delivery=delivery,
        handoff=handoff,
        paths=paths,
        no_reparse=delivery._no_reparse,
        private_acl=delivery._private_acl,
        exclusive_fsync=continuation._exclusive_fsync,
        set_file_acl=continuation._set_exact_file_acl,
        transport_factory=delivery.TelegramTransport,
        source_bytes=source_bytes,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize-one-corrected-chat-test", action="store_true")
    args = parser.parse_args(argv)
    if not args.authorize_one_corrected_chat_test:
        print(json.dumps({"status": "PLAN_ONLY", "http_calls": 0, "send_attempts": 0}))
        return 0
    try:
        result = run_corrected_test(authorize=True)
    except Exception as error:  # noqa: BLE001 - only fixed category can leave process.
        result = {
            "status": "BLOCKED",
            "stage": "PRECHECK_FAILED",
            "error_category": _safe_error(error),
            # A partial/result-write failure may follow a successful send. Never
            # turn missing terminal evidence into an asserted zero attempts.
            "send_attempts": None,
            "requires_manual_review": True,
            "automatic_retry": False,
            "human_acknowledged": False,
            "operationally_qualified": False,
            "delivery_qualified": False,
            "trading_authority": False,
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("status") == "TRANSPORT_ACCEPTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
