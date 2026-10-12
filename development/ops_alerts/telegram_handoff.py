"""Reviewed current-token Telegram preflight; old evidence and runtime are untouched."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

DEPLOY = Path("D:/Kairos/kairos-deploy")
DEPLOY_SHA = "0427f7cf1e1cd70f2ddd05b80b4d7d6219736412"
SIGNER = "40AF365C6682B73D056A6A274DBFF6B65BE9F827"
KEY_SOURCE = Path("C:/Users/loval/Documents/keys.txt")
OLD_ROOT = Path("D:/Kairos/runtime/alert-delivery")
NEW_ROOT = Path("D:/Kairos/runtime/alert-delivery-20261012")
OLD_DIAGNOSTIC = (
    OLD_ROOT
    / "receipts/telegram-readonly-diagnostic-7c4ab990589b0a68f90c87f82bff6aa7a6807a01bff5bfab1dfa07946f58eee7.result.json"
)
OLD_DIAGNOSTIC_SHA = "a2ff0a659ca3e2b16498282756b05d1ae6a323753bb1f943ca507458a032dc06"
OLD_QUALIFICATION = (
    OLD_ROOT
    / "receipts/telegram-qualification-7a3845200b24af637213739b21f914b81bb13f0282bb5c751fb106732a52abe5.jsonl"
)
OLD_QUALIFICATION_SHA = (
    "b6c6a066e86915aa28bca3ff036ed5ec0b58d75b7dd176ccf11d3600674c4d4d"
)
BOT_PREFIX = "8898378227:"


class HandoffError(Exception):
    """Only public fixed categories may leave this process."""


def choose_current_token(raw: str, old: str) -> str:
    matches = set(
        re.findall(
            r"(?<![A-Za-z0-9_-])[0-9]{5,20}:[A-Za-z0-9_-]{30,100}(?![A-Za-z0-9_-])", raw
        )
    )
    if len(matches) != 1:
        raise HandoffError("EXACTLY_ONE_TELEGRAM_TOKEN_REQUIRED")
    token = matches.pop()
    if not token.startswith(BOT_PREFIX):
        raise HandoffError("EXPECTED_BOT_PREFIX_REQUIRED")
    if token == old.strip():
        raise HandoffError("EXPOSED_PREVIOUS_TOKEN_ROTATION_REQUIRED")
    return token


def verify_deploy() -> None:
    git = "C:/Program Files/Git/cmd/git.exe"
    result = subprocess.run(
        [git, "-C", str(DEPLOY), "log", "-1", "--format=%H %G? %GF"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
        text=True,
    )
    branch = subprocess.run(
        [git, "-C", str(DEPLOY), "branch", "--show-current"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
        text=True,
    )
    changes = subprocess.run(
        [git, "-C", str(DEPLOY), "status", "--porcelain", "--untracked-files=no"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
        text=True,
    )
    if (
        result.returncode
        or branch.returncode
        or changes.returncode
        or result.stdout.strip() != f"{DEPLOY_SHA} G {SIGNER}"
        or branch.stdout.strip() != "main"
        or changes.stdout.strip()
    ):
        raise HandoffError("EXACT_SIGNED_CLEAN_DEPLOY_REQUIRED")


def prepare_and_preflight() -> dict:
    verify_deploy()
    sys.path.insert(0, str(DEPLOY))
    from scripts import alert_delivery as delivery
    from scripts import provision_secrets as provisioning
    from scripts import telegram_readonly_diagnostic as diagnostic

    for path in (
        KEY_SOURCE,
        OLD_ROOT,
        OLD_ROOT / "secrets/telegram_bot_token",
        OLD_DIAGNOSTIC,
        OLD_QUALIFICATION,
        NEW_ROOT,
    ):
        delivery._no_reparse(path)
    for path, expected in (
        (OLD_DIAGNOSTIC, OLD_DIAGNOSTIC_SHA),
        (OLD_QUALIFICATION, OLD_QUALIFICATION_SHA),
    ):
        if (
            not path.is_file()
            or path.stat().st_size > 128 * 1024
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise HandoffError("REVIEWED_PRIOR_NO_SEND_EVIDENCE_REQUIRED")
    previous = json.loads(OLD_DIAGNOSTIC.read_bytes())
    entries = [json.loads(line) for line in OLD_QUALIFICATION.read_bytes().splitlines()]
    if (
        previous.get("error_category") != "CHAT_NOT_FOUND"
        or previous.get("send_attempts") != 0
        or not entries
        or entries[-1].get("stage") != "PRECHECK_FAILED"
        or any(
            row.get("expected_chat_id") != delivery.EXPECTED_TEST_CHAT
            or row.get("send_attempts") != 0
            for row in entries
        )
    ):
        raise HandoffError("REVIEWED_PRIOR_NO_SEND_EVIDENCE_REQUIRED")
    if NEW_ROOT.exists() or NEW_ROOT.is_symlink():
        raise HandoffError("NEW_ATTEMPT_ALREADY_EXISTS_NO_RETRY")
    if not KEY_SOURCE.is_file() or not 0 < KEY_SOURCE.stat().st_size <= 32768:
        raise HandoffError("BOUNDED_OWNER_KEY_FILE_REQUIRED")
    old_token_path = OLD_ROOT / "secrets/telegram_bot_token"
    delivery._private_acl(old_token_path)
    if not 0 < old_token_path.stat().st_size <= 256:
        raise HandoffError("INVALID_PREVIOUS_TOKEN_METADATA")
    token = choose_current_token(
        KEY_SOURCE.read_text(encoding="utf-8"),
        old_token_path.read_text(encoding="utf-8"),
    )

    # Empty generated directories are hardened before any credential is written.
    NEW_ROOT.mkdir()
    (NEW_ROOT / "secrets").mkdir()
    (NEW_ROOT / "receipts").mkdir()
    provisioning.harden_permissions(NEW_ROOT)
    for path in (NEW_ROOT, NEW_ROOT / "secrets", NEW_ROOT / "receipts"):
        delivery._private_acl(path)
    token_path = NEW_ROOT / "secrets/telegram_bot_token"
    provisioning._write_exclusive(token_path, token)
    provisioning.harden_permissions(NEW_ROOT)
    delivery._private_acl(token_path)
    delivery._exclusive(
        NEW_ROOT / "receipts/handoff.json",
        delivery.canonical(
            {
                "kind": "REVIEWED_CURRENT_TOKEN_NO_SEND_HANDOFF",
                "deploy_revision": DEPLOY_SHA,
                "implementation_sha256": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
                "old_diagnostic_sha256": OLD_DIAGNOSTIC_SHA,
                "old_qualification_sha256": OLD_QUALIFICATION_SHA,
                "current_token_differs_from_previous": True,
                "current_token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                "automatic_retry": False,
                "trading_authority": False,
            }
        )
        + b"\n",
    )
    return diagnostic.diagnose(token_path, authorize_readonly=True, ops_root=NEW_ROOT)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-readonly", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute_readonly:
        print(json.dumps({"status": "PLAN_ONLY", "http_calls": 0, "send_attempts": 0}))
        return 0
    try:
        result = prepare_and_preflight()
    except Exception as exc:  # noqa: BLE001 - do not expose credential-bearing errors.
        # Raw exception strings can contain URLs/credentials. Never print them.
        category = (
            str(exc)
            if isinstance(exc, HandoffError)
            else "LOCAL_OPERATION_FAILED_" + type(exc).__name__
        )
        result = {
            "status": "BLOCKED",
            "error_category": category,
            "send_attempts": 0,
            "automatic_retry": False,
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("chat_identity_verified") else 2


if __name__ == "__main__":
    raise SystemExit(main())
