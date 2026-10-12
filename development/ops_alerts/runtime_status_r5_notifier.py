"""Create-only R5 technical-runtime notifier. Default mode performs no I/O."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(r"D:\Kairos\kairos")
DEPLOY = Path(r"D:\Kairos\kairos-deploy")
PERSISTENCE = Path(r"D:\Kairos\kairos-persistence")
PRIVATE_ROOT = Path(r"D:\Kairos\runtime\alert-delivery-20261012\operational-r5-v2")
PREVIOUS_ROOT = Path(r"D:\Kairos\runtime\alert-delivery-20261012\operational-r5")
RUNTIME_ROOT = Path(r"D:\Kairos\runtime\runtime-incident-20261012")
OWNER = "69893dc7b7c647f49967387e7efca9fb"
TASK_NAME = "Kairos-R5-TechnicalAlerts-V2-20261012"
GROUP_ID = -1004475802889
SCOPE = "kairos-r5-technical-runtime-alerts-v2"
SIGNER = "40AF365C6682B73D056A6A274DBFF6B65BE9F827"
GPG = Path(r"C:\Program Files\Git\usr\bin\gpg.exe")
ROUTE_SHA256 = "6691779312c346c72a2e0e788a7a2827d59b93865f205704b47b41a43eaac5bc"
ROUTE_PATH = "development/ops_alerts/notification-routing-20261012.json"
TOKEN_PATH = Path(
    r"D:\Kairos\runtime\alert-delivery-20261012\secrets\telegram_bot_token"
)
TOKEN_PREFIX = "8898378227:"
EXPECTED_BOT = "KairosCryptoAI_bot"
HANDOFF_COMMIT = "f7b2f249c028a4a947b7279e677f21ee85bee8fc"
HANDOFF_SHA256 = "b308e19753be088966e3fed4d1ddacc47ca3ef8d90089d1c527d1c93813d3930"
DELIVERY_SHA256 = "fa9d58a7c1d7967c5aacf107accfbc72ff61fe5c71e4348a9c75dcf44e976ce5"
PERSISTENCE_COMMIT = "ea0c73395352f71da196270fe16659f1f0298a52"
OBSERVER_SHA256 = "27b244e7f20f3ae5cae52e1ab23d96db67429bec51d633eae68fe225f3b1af20"
PREVIOUS_COMMIT = "d000ab1cd07e03e21221ab407f52de7240cbe396"
PREVIOUS_SOURCE_SHA256 = (
    "4b5dce84f9832ab32bd48a74db84964e5e08fb52a03e55f1a39d5dbac4bb3e4c"
)
PREVIOUS_JOURNAL_SHA256 = (
    "61b7bbff1adfb67b1b695aaca968f85d097c5f5c2fdddb4898b05de26dcf4791"
)
PREVIOUS_BINDING_SHA256 = (
    "788d58a63d51691e749b64d0c6e1134d6a8e36861edacadf4364e2c0aebd76e6"
)
PREVIOUS_EVENT = "dea935887a941fc9ce741358c48425853a04a79235ee42f90172afc3c7ecf5d8"
MAX_BYTES = 65_536
MAX_RECORDS = 256
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_OWNER = re.compile(r"[0-9a-f]{32}\Z")
_WORK = re.compile(r"read-recovery-r5-[0-9a-f]{32}\Z")
_CONTAINER = re.compile(r"[0-9a-f]{64}\Z")
_STATES = {
    "failed_closed",
    "missing",
    "invalid",
    "unknown_owner",
    "running_stale",
    "running_fresh",
}
_ALERTS = _STATES - {"running_fresh"}


class R5Error(RuntimeError):
    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


def _json(raw: bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate")
            out[key] = value
        return out

    return json.loads(raw, object_pairs_hook=unique)


def _read(path: Path, maximum: int) -> bytes:
    try:
        before = path.lstat()
        if (
            path.is_symlink()
            or getattr(before, "st_file_attributes", 0) & 0x400
            or not path.is_file()
            or before.st_size > maximum
        ):
            raise R5Error("PROTECTED_EVIDENCE_REQUIRED")
        fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise R5Error("PROTECTED_EVIDENCE_REQUIRED")
            value = stream.read(maximum + 1)
        if len(value) != before.st_size or len(value) > maximum:
            raise R5Error("PROTECTED_EVIDENCE_REQUIRED")
        return value
    except R5Error:
        raise
    except Exception:  # noqa: BLE001 - sanitize protected-file failures.
        raise R5Error("PROTECTED_EVIDENCE_REQUIRED") from None


def _read_private(path: Path, *, maximum: int, delivery: Any) -> bytes:
    """Bounded regular-file read after path and private-ACL admission."""
    try:
        delivery._no_reparse(path)
        delivery._private_acl(path)
        return _read(path, maximum)
    except Exception:  # noqa: BLE001 - never expose protected path/ACL details.
        raise R5Error("PROTECTED_EVIDENCE_REQUIRED") from None


def _git(repo: Path, args: list[str], timeout: int = 20) -> bytes:
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
            timeout=timeout,
            check=False,
            env=env,
            shell=False,
        )
    except Exception:  # noqa: BLE001 - no raw process diagnostics escape.
        raise R5Error("SOURCE_ADMISSION_FAILED") from None
    if result.returncode:
        raise R5Error("SOURCE_ADMISSION_FAILED")
    return result.stdout


def _verify_signature(data: Path, signature: Path) -> None:
    try:
        result = subprocess.run(
            [
                str(GPG),
                "--batch",
                "--no-auto-key-retrieve",
                "--status-fd",
                "1",
                "--verify",
                str(signature),
                str(data),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
            shell=False,
        )
        lines = result.stdout.decode("ascii", "strict").splitlines()
        valid = [
            line.split() for line in lines if line.startswith("[GNUPG:] VALIDSIG ")
        ]
        if result.returncode or len(valid) != 1 or SIGNER not in valid[0][2:]:
            raise R5Error("SIGNATURE_INVALID")
    except R5Error:
        raise
    except Exception:  # noqa: BLE001 - sanitize verifier details.
        raise R5Error("SIGNATURE_INVALID") from None


def _signed_blob(
    repo: Path, commit: str, relpath: str, expected: str | None = None
) -> bytes:
    fields = (
        _git(repo, ["show", "-s", "--format=%H %G? %GF", commit])
        .decode("ascii", "strict")
        .strip()
        .split()
    )
    if len(fields) != 3 or fields[0] != commit or fields[1:] != ["G", SIGNER]:
        raise R5Error("SOURCE_ADMISSION_FAILED")
    _git(repo, ["merge-base", "--is-ancestor", commit, "HEAD"])
    blob = _git(repo, ["show", f"{commit}:{relpath}"])
    if expected is not None and hashlib.sha256(blob).hexdigest() != expected:
        raise R5Error("SOURCE_ADMISSION_FAILED")
    return blob


def _verify_binding(binding: dict[str, Any]) -> dict[str, Any]:
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
        "predecessor_adjudication_sha256",
        "authorization",
        "trading_started",
    }
    auth = binding.get("authorization") if isinstance(binding, dict) else None
    if (
        not isinstance(binding, dict)
        or set(binding) != keys
        or binding.get("schema_version") != 1
        or binding.get("scope") != SCOPE
        or binding.get("owner") != OWNER
        or binding.get("task_name") != TASK_NAME
        or not isinstance(binding.get("work"), str)
        or _WORK.fullmatch(binding["work"]) is None
        or not isinstance(binding.get("serve_container_id"), str)
        or _CONTAINER.fullmatch(binding["serve_container_id"]) is None
        or not isinstance(binding.get("receipt_sha256"), str)
        or _HEX64.fullmatch(binding["receipt_sha256"]) is None
        or not isinstance(binding.get("receipt_source_revision"), str)
        or _HEX40.fullmatch(binding["receipt_source_revision"]) is None
        or not isinstance(binding.get("deploy_revision"), str)
        or _HEX40.fullmatch(binding["deploy_revision"]) is None
        or not isinstance(binding.get("notifier_sha256"), str)
        or _HEX64.fullmatch(binding["notifier_sha256"]) is None
        or not isinstance(binding.get("predecessor_adjudication_sha256"), str)
        or _HEX64.fullmatch(binding["predecessor_adjudication_sha256"]) is None
        or not isinstance(auth, dict)
        or auth
        != {
            "kind": "DIRECT_OWNER_REPAIR_AND_EXISTING_TECHNICAL_ROUTING",
            "route_sha256": ROUTE_SHA256,
        }
        or binding.get("trading_started") is not False
    ):
        raise R5Error("BINDING_INVALID")
    return binding


def _admit_local_no_send(binding: dict[str, Any], delivery: Any) -> None:
    """Admit only this exact pre-transport import defect, never a network unknown.

    The predecessor's unknown journal/guard remain immutable. V2 starts a new
    healthy baseline, does not retry the historical event or claim it delivered.
    """
    proof = PRIVATE_ROOT / "predecessor-no-send.json"
    raw = _read_private(proof, maximum=4096, delivery=delivery)
    _read_private(proof.with_suffix(".json.asc"), maximum=4096, delivery=delivery)
    _verify_signature(proof, proof.with_suffix(".json.asc"))
    expected = {
        "schema_version": 1,
        "kind": "kairos.r5.exact-pretransport-import-failure.v1",
        "previous_source_commit": PREVIOUS_COMMIT,
        "previous_source_sha256": PREVIOUS_SOURCE_SHA256,
        "helper_sha256": HANDOFF_SHA256,
        "previous_journal_sha256": PREVIOUS_JOURNAL_SHA256,
        "previous_binding_sha256": PREVIOUS_BINDING_SHA256,
        "event_id": PREVIOUS_EVENT,
        "journal_records": 4,
        "failure": "ImportError_before_token_read_and_transport_construction",
        "wire_attempts": 0,
        "historical_event_retried": False,
        "historical_unknown_record_rewritten": False,
        "new_healthy_baseline_required": True,
        "trading_authority": False,
    }
    if (
        hashlib.sha256(raw).hexdigest() != binding["predecessor_adjudication_sha256"]
        or _json(raw) != expected
    ):
        raise R5Error("PREDECESSOR_NO_SEND_PROOF_REQUIRED")
    _signed_blob(
        ROOT,
        PREVIOUS_COMMIT,
        "development/ops_alerts/runtime_status_r5_notifier.py",
        PREVIOUS_SOURCE_SHA256,
    )
    previous = _read_private(
        PREVIOUS_ROOT / "events.jsonl", maximum=MAX_BYTES, delivery=delivery
    )
    guard = _read_private(
        PREVIOUS_ROOT / f"events.jsonl.{PREVIOUS_EVENT}.guard",
        maximum=1024,
        delivery=delivery,
    )
    old_binding = _read_private(
        PREVIOUS_ROOT / "binding.json", maximum=16 * 1024, delivery=delivery
    )
    if (
        hashlib.sha256(previous).hexdigest() != PREVIOUS_JOURNAL_SHA256
        or len(previous.splitlines()) != 4
        or hashlib.sha256(old_binding).hexdigest() != PREVIOUS_BINDING_SHA256
        or _json(guard)
        != {
            "event_id": PREVIOUS_EVENT,
            "transition": "firing",
            "state": "running_stale",
        }
    ):
        raise R5Error("PREDECESSOR_EVIDENCE_CHANGED")


def admit_sources() -> dict[str, Any]:
    """Admit only signed current Meta/Deploy plus the immutable R5 receipt binding."""
    head = (
        _git(ROOT, ["show", "-s", "--format=%H %G? %GF", "HEAD"])
        .decode("ascii", "strict")
        .strip()
        .split()
    )
    if (
        len(head) != 3
        or head[1:] != ["G", SIGNER]
        or _git(ROOT, ["branch", "--show-current"]).decode("ascii", "strict").strip()
        != "main"
    ):
        raise R5Error("SOURCE_ADMISSION_FAILED")
    head_id = head[0]
    if (
        _git(ROOT, ["rev-parse", "origin/main"]).decode("ascii", "strict").strip()
        != head_id
    ):
        raise R5Error("SOURCE_ADMISSION_FAILED")
    rel = "development/ops_alerts/runtime_status_r5_notifier.py"
    blob = _git(ROOT, ["show", f"{head_id}:{rel}"])
    working = _read(ROOT / rel, 256 * 1024)
    if blob != working:
        raise R5Error("SOURCE_ADMISSION_FAILED")
    if _git(ROOT, ["status", "--porcelain", "--", rel]).strip():
        raise R5Error("SOURCE_ADMISSION_FAILED")
    binding_path = PRIVATE_ROOT / "binding.json"
    _c, delivery = _continuation()
    delivery._no_reparse(PRIVATE_ROOT)
    delivery._private_acl(PRIVATE_ROOT)
    delivery._no_reparse(binding_path)
    delivery._private_acl(binding_path)
    delivery._no_reparse(PRIVATE_ROOT / "binding.json.asc")
    delivery._private_acl(PRIVATE_ROOT / "binding.json.asc")
    binding_raw = _read(binding_path, 16 * 1024)
    _verify_signature(binding_path, PRIVATE_ROOT / "binding.json.asc")
    binding = _verify_binding(_json(binding_raw))
    if hashlib.sha256(blob).hexdigest() != binding["notifier_sha256"]:
        raise R5Error("SOURCE_ADMISSION_FAILED")
    _admit_local_no_send(binding, delivery)
    deploy_head = _git(DEPLOY, ["rev-parse", "HEAD"]).decode("ascii", "strict").strip()
    deploy_branch = (
        _git(DEPLOY, ["branch", "--show-current"]).decode("ascii", "strict").strip()
    )
    origin = (
        _git(DEPLOY, ["rev-parse", "origin/main"]).decode("ascii", "strict").strip()
    )
    deploy_fields = (
        _git(DEPLOY, ["show", "-s", "--format=%H %G? %GF", binding["deploy_revision"]])
        .decode("ascii", "strict")
        .strip()
        .split()
    )
    dirty = _git(DEPLOY, ["status", "--porcelain", "--untracked-files=no"])
    if (
        deploy_head != binding["deploy_revision"]
        or origin != deploy_head
        or deploy_branch != "main"
        or dirty
        or len(deploy_fields) != 3
        or deploy_fields[0] != binding["deploy_revision"]
        or deploy_fields[1:] != ["G", SIGNER]
    ):
        raise R5Error("SOURCE_ADMISSION_FAILED")
    receipt_source_fields = (
        _git(
            DEPLOY,
            [
                "show",
                "-s",
                "--format=%H %G? %GF",
                binding["receipt_source_revision"],
            ],
        )
        .decode("ascii", "strict")
        .strip()
        .split()
    )
    if receipt_source_fields != [binding["receipt_source_revision"], "G", SIGNER]:
        raise R5Error("SOURCE_ADMISSION_FAILED")
    _git(
        DEPLOY,
        [
            "merge-base",
            "--is-ancestor",
            binding["receipt_source_revision"],
            binding["deploy_revision"],
        ],
    )
    route = _git(ROOT, ["show", f"{head_id}:{ROUTE_PATH}"])
    if hashlib.sha256(route).hexdigest() != ROUTE_SHA256:
        raise R5Error("SOURCE_ADMISSION_FAILED")
    if _read(ROOT / ROUTE_PATH, 16 * 1024) != route:
        raise R5Error("SOURCE_ADMISSION_FAILED")
    _signed_blob(
        ROOT,
        HANDOFF_COMMIT,
        "development/ops_alerts/telegram_continuation.py",
        HANDOFF_SHA256,
    )
    _signed_blob(
        DEPLOY,
        "0427f7cf1e1cd70f2ddd05b80b4d7d6219736412",
        "scripts/alert_delivery.py",
        DELIVERY_SHA256,
    )
    _signed_blob(
        PERSISTENCE,
        PERSISTENCE_COMMIT,
        "kairos_persistence/metrics_exporter.py",
        OBSERVER_SHA256,
    )
    persistence_head = (
        _git(PERSISTENCE, ["rev-parse", "HEAD"]).decode("ascii", "strict").strip()
    )
    persistence_origin = (
        _git(PERSISTENCE, ["rev-parse", "origin/main"])
        .decode("ascii", "strict")
        .strip()
    )
    persistence_branch = (
        _git(PERSISTENCE, ["branch", "--show-current"])
        .decode("ascii", "strict")
        .strip()
    )
    persistence_dirty = _git(
        PERSISTENCE, ["status", "--porcelain", "--untracked-files=no"]
    )
    if (
        persistence_head != PERSISTENCE_COMMIT
        or persistence_origin != persistence_head
        or persistence_branch != "main"
        or persistence_dirty
        or hashlib.sha256(
            _read(PERSISTENCE / "kairos_persistence/metrics_exporter.py", 256 * 1024)
        ).hexdigest()
        != OBSERVER_SHA256
    ):
        raise R5Error("SOURCE_ADMISSION_FAILED")
    work = RUNTIME_ROOT / binding["work"]
    receipt = work / "receipt.json"
    delivery._no_reparse(work)
    delivery._private_acl(work)
    delivery._no_reparse(receipt)
    delivery._private_acl(receipt)
    delivery._no_reparse(work / "receipt.json.asc")
    delivery._private_acl(work / "receipt.json.asc")
    receipt_raw = _read(receipt, 256 * 1024)
    _verify_signature(receipt, work / "receipt.json.asc")
    if hashlib.sha256(receipt_raw).hexdigest() != binding["receipt_sha256"]:
        raise R5Error("RECEIPT_INVALID")
    obj = _json(receipt_raw)
    generation = obj.get("generation") if isinstance(obj, dict) else None
    if (
        not isinstance(obj, dict)
        or obj.get("result") != "PASS_NEW_NONTRADING_GENERATION"
        or obj.get("owner") != OWNER
        or obj.get("source_revision") != binding["receipt_source_revision"]
        or not isinstance(generation, dict)
        or generation.get("name") != "kairos-epoch-69893dc7b7c6-serve-r5"
        or generation.get("container_id") != binding["serve_container_id"]
        or not isinstance(generation.get("status"), dict)
        or generation["status"].get("state") != "RUNNING_NONTRADING"
        or generation["status"].get("owner") != OWNER
        or any(
            generation["status"].get(field) != 0
            for field in (
                "pending_outbox",
                "unresolved_inbox",
                "uncompleted_publications",
            )
        )
        or obj.get("trading_started") is not False
        or any(
            obj.get(flag) is not False
            for flag in ("PAPER_QUALIFIED", "ALPHA_READY", "LIVE_READY")
        )
        or obj.get("STRATEGY_POLICY") != "REJECT_ALL"
    ):
        raise R5Error("RECEIPT_INVALID")
    return {
        "binding": binding,
        "binding_sha256": hashlib.sha256(binding_raw).hexdigest(),
        "receipt": obj,
        "notifier_sha256": hashlib.sha256(blob).hexdigest(),
        "head": head_id,
    }


def _runtime_observer(path: Path, *, expected_owner: str) -> Any:
    if str(PERSISTENCE) not in sys.path:
        sys.path.insert(0, str(PERSISTENCE))
    from kairos_persistence.metrics_exporter import observe_runtime_epoch_serve_status

    return observe_runtime_epoch_serve_status(path, expected_owner=expected_owner)


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
    return state if state in _ALERTS - {"running_stale"} else "invalid"


def _continuation():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if str(DEPLOY) not in sys.path:
        sys.path.insert(0, str(DEPLOY))
    from development.ops_alerts import telegram_continuation as c
    from scripts import alert_delivery

    if (
        hashlib.sha256(
            _read(ROOT / "development/ops_alerts/telegram_continuation.py", 256 * 1024)
        ).hexdigest()
        != HANDOFF_SHA256
        or hashlib.sha256(
            _read(DEPLOY / "scripts/alert_delivery.py", 256 * 1024)
        ).hexdigest()
        != DELIVERY_SHA256
    ):
        raise R5Error("SOURCE_ADMISSION_FAILED")
    return c, alert_delivery


def _write_new(path: Path, raw: bytes, c: Any, delivery: Any) -> None:
    c._exclusive_fsync(path, raw)
    c._set_exact_file_acl(path)
    delivery._no_reparse(path)
    delivery._private_acl(path)


class R5Journal:
    """Append-only private journal with O_EXCL lease and fail-closed guards."""

    def __init__(self, path: Path, c: Any, delivery: Any):
        self.path, self.c, self.delivery = path, c, delivery
        self.lease_path = path.with_name(path.name + ".lock")

    def _verify(self, path: Path) -> bytes:
        self.delivery._no_reparse(path)
        self.delivery._private_acl(path)
        return _read(path, MAX_BYTES)

    def _append(self, record: dict[str, Any]) -> None:
        encoded = (
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        if len(encoded) > 1024:
            raise R5Error("JOURNAL_LIMIT")
        try:
            if record.get("kind") == "send_reserved":
                guard = self.path.with_name(
                    self.path.name + "." + record["event_id"] + ".guard"
                )
                guard_payload = json.dumps(
                    {key: record[key] for key in ("event_id", "transition", "state")},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                _write_new(guard, guard_payload, self.c, self.delivery)
            if self.path.exists():
                records = self.read(allow_pending=record.get("kind") == "send_outcome")
                if len(records) >= MAX_RECORDS:
                    raise R5Error("JOURNAL_LIMIT")
                fd = os.open(
                    self.path,
                    os.O_WRONLY
                    | os.O_APPEND
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_BINARY", 0),
                )
                is_new = False
            else:
                fd = os.open(
                    self.path,
                    os.O_CREAT
                    | os.O_EXCL
                    | os.O_WRONLY
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_BINARY", 0),
                    0o600,
                )
                is_new = True
            with os.fdopen(fd, "ab") as stream:
                if stream.write(encoded) != len(encoded):
                    raise R5Error("JOURNAL_WRITE_FAILED")
                stream.flush()
                os.fsync(stream.fileno())
            if is_new:
                self.c._set_exact_file_acl(self.path)
            self.delivery._no_reparse(self.path)
            self.delivery._private_acl(self.path)
        except R5Error:
            raise
        except Exception:  # noqa: BLE001 - sanitize filesystem/ACL details.
            raise R5Error("JOURNAL_WRITE_FAILED") from None

    def read(self, *, allow_pending: bool = False) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        raw = self._verify(self.path)
        if not raw or not raw.endswith(b"\n") or len(raw) > MAX_BYTES:
            raise R5Error("JOURNAL_INVALID")
        try:
            rows = [_json(line) for line in raw.splitlines()]
            if len(rows) > MAX_RECORDS or any(
                not isinstance(row, dict) or row.get("seq") != i
                for i, row in enumerate(rows)
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
                    and row.get("transition") in {"firing", "resolved"}
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
                        raise R5Error("SEND_OUTCOME_UNKNOWN")
                    pending = None
                else:
                    raise ValueError("event")
            if pending is not None and not allow_pending:
                raise R5Error("SEND_OUTCOME_UNKNOWN")
            return rows
        except R5Error:
            raise
        except Exception:  # noqa: BLE001 - malformed journals fail closed.
            raise R5Error("JOURNAL_INVALID") from None

    @contextmanager
    def locked(self):
        token = uuid.uuid4().hex.encode()
        try:
            fd = os.open(
                self.lease_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except FileExistsError:
            raise R5Error("SINGLETON_BUSY_OR_STALE_LEASE") from None
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(token)
                stream.flush()
                os.fsync(stream.fileno())
            self.c._set_exact_file_acl(self.lease_path)
            self.delivery._no_reparse(self.lease_path)
            self.delivery._private_acl(self.lease_path)
            yield
        finally:
            try:
                if self._verify(self.lease_path) == token:
                    self.lease_path.unlink()
            except Exception:  # noqa: BLE001, S110 - retain unprovable lease.
                pass


def _status_path(binding: dict[str, Any]) -> Path:
    return RUNTIME_ROOT / binding["work"] / "output-serve" / "status.json"


def initialize(
    *,
    source_admitter: Callable[[], Any] = admit_sources,
    observer: Callable[..., Any] = _runtime_observer,
    root: Path = PRIVATE_ROOT,
) -> dict[str, Any]:
    source = source_admitter()
    c, delivery = _continuation()
    delivery._no_reparse(root)
    delivery._private_acl(root)
    journal = R5Journal(root / "events.jsonl", c, delivery)
    with journal.locked():
        if journal.read():
            raise R5Error("BASELINE_ALREADY_EXISTS")
        status_path = _status_path(source["binding"])
        delivery._no_reparse(status_path)
        state = _classify(observer(status_path, expected_owner=OWNER))
        if state != "running_fresh":
            raise R5Error("HEALTHY_BASELINE_REQUIRED")
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
        "status": "BASELINE_RECORDED",
        "state": state,
        "send_attempts": 0,
        "trading_authority": False,
    }


def poll_once(
    *,
    source_admitter: Callable[[], Any] = admit_sources,
    observer: Callable[..., Any] = _runtime_observer,
    sender: Callable[..., bool] | None = None,
    root: Path = PRIVATE_ROOT,
) -> dict[str, Any]:
    source = source_admitter()
    c, delivery = _continuation()
    delivery._no_reparse(root)
    delivery._private_acl(root)
    journal = R5Journal(root / "events.jsonl", c, delivery)
    with journal.locked():
        rows = journal.read()
        if not rows or rows[0].get("binding_sha256") != source["binding_sha256"]:
            raise R5Error("BASELINE_REQUIRED_OR_BINDING_CHANGED")
        status_path = _status_path(source["binding"])
        delivery._no_reparse(status_path)
        state = _classify(observer(status_path, expected_owner=OWNER))
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
        # Import, ACL, token/handoff and constructor checks precede ANY journal
        # transition/reservation. A proven pre-wire failure stays retryable;
        # once sendMessage is invoked, any uncertainty remains fail-closed.
        if transition is not None and sender is None:
            sender = _sender_factory(source, c, delivery, root)
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
                "state": state,
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
            "recipient_chat_id": GROUP_ID,
            "text": (
                "[Kairos R5] Non-trading runtime status is unhealthy. Trading remains disabled."
                if transition == "firing"
                else "[Kairos R5] Non-trading runtime status returned to fresh RUNNING. Trading remains disabled."
            ),
        }
        assert sender is not None
        try:
            accepted = sender(alert) is True
        except Exception:  # noqa: BLE001 - transport failure is ambiguous.
            accepted = False
        result = "accepted" if accepted else "unknown"
        rows = journal.read(allow_pending=True)
        journal._append(
            {
                "schema_version": 1,
                "seq": len(rows),
                "kind": "send_outcome",
                "event_id": event_id,
                "transition": transition,
                "state": state,
                "result": result,
            }
        )
        return {
            "status": transition + ("_accepted" if accepted else "_outcome_unknown"),
            "state": state,
            "send_attempts": 1,
            "trading_authority": False,
        }


def _prepare_transport(c: Any, delivery: Any) -> Any:
    """Credential/constructor preflight; TelegramTransport construction is offline."""
    try:
        token_raw = _read_private(TOKEN_PATH, maximum=256, delivery=delivery)
        token = c._decode_token(token_raw)
        handoff_raw = _read_private(c.HANDOFF, maximum=4096, delivery=delivery)
        if hashlib.sha256(handoff_raw).hexdigest() != c.HANDOFF_SHA256:
            raise R5Error("TOKEN_INVALID")
        handoff = _json(handoff_raw)
        if (
            not isinstance(handoff, dict)
            or handoff.get("kind") != "REVIEWED_CURRENT_TOKEN_NO_SEND_HANDOFF"
            or handoff.get("deploy_revision")
            != "0427f7cf1e1cd70f2ddd05b80b4d7d6219736412"
            or handoff.get("current_token_differs_from_previous") is not True
            or handoff.get("automatic_retry") is not False
            or handoff.get("trading_authority") is not False
            or handoff.get("current_token_sha256")
            != hashlib.sha256(token.encode()).hexdigest()
            or not token.startswith(TOKEN_PREFIX)
        ):
            raise R5Error("TOKEN_INVALID")
        return delivery.TelegramTransport(token)
    except Exception:  # noqa: BLE001 - pre-send failures cannot leak secrets.
        raise R5Error("SENDER_PREFLIGHT_FAILED_NO_SEND") from None


def _sender_factory(source: dict[str, Any], c: Any, delivery: Any, root: Path):
    transport = _prepare_transport(c, delivery)

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
            raise R5Error("SEND_OUTCOME_UNKNOWN")
        receipt = {
            "schema_version": 1,
            "kind": "kairos.runtime-status-r5.telegram-send-receipt.v1",
            "event_id": alert["event_id"],
            "transition": alert["transition"],
            "state": alert["state"],
            "recipient_chat_id": GROUP_ID,
            "message_id": response["message_id"],
            "accepted_at_utc": datetime.now(UTC).isoformat(),
            "protect_content": True,
            "binding_sha256": source["binding_sha256"],
            "trading_authority": False,
        }
        _write_new(
            root / ("telegram-" + alert["event_id"] + ".json"),
            json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode(),
            c,
            delivery,
        )
        return True

    return send


def plan() -> dict[str, Any]:
    return {
        "status": "PLAN_ONLY",
        "scope": SCOPE,
        "task_name": TASK_NAME,
        "network_calls": 0,
        "status_file_read": False,
        "database_or_redis": False,
        "trading_authority": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--initialize", action="store_true")
    modes.add_argument("--poll-once", action="store_true")
    modes.add_argument("--verify-only", action="store_true")
    parser.add_argument("--armed", action="store_true")
    args = parser.parse_args(argv)
    if not (args.initialize or args.poll_once or args.verify_only):
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
        if args.verify_only:
            source = admit_sources()
            c, delivery = _continuation()
            _prepare_transport(c, delivery)
            report = {
                "status": "ADMITTED_NO_SEND",
                "binding_sha256": source["binding_sha256"],
                "send_attempts": 0,
                "trading_authority": False,
            }
        else:
            report = initialize() if args.initialize else poll_once()
    except R5Error as error:
        report = {
            "status": "BLOCKED",
            "error_category": error.category,
            "send_attempts": None,
            "trading_authority": False,
        }
    except Exception:  # noqa: BLE001 - public CLI must never emit diagnostics.
        report = {
            "status": "BLOCKED",
            "error_category": "NOTIFIER_BLOCKED",
            "send_attempts": None,
            "trading_authority": False,
        }
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
