"""Create-only technical status notifier for the accepted R7 shadow epoch.

The default command is a no-I/O plan.  The monitor reads one protected status
file; it never queries Docker, PostgreSQL, Redis, a provider, or a venue.
"""

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
from typing import Any

ROOT = Path(r"D:\Kairos\kairos")
DEPLOY_ROOT = Path(r"D:\Kairos\kairos-deploy")
RUNTIME_ROOT = Path(r"D:\Kairos\runtime\runtime-incident-20261013")
PRIVATE_ROOT = Path(r"D:\Kairos\runtime\alert-delivery-20261013\operational-r7")
R7DNS_PRIVATE_ROOT = Path(
    r"D:\Kairos\runtime\alert-delivery-20261015\operational-r7-dns"
)
R7SQL_PREDECESSOR_ROOT = Path(
    r"D:\Kairos\runtime\alert-delivery-20261016\operational-r7-sql"
)
R7SQL_PRIVATE_ROOT = Path(
    r"D:\Kairos\runtime\alert-delivery-20261018\operational-r7-sql-successor"
)
R7SQL_PREDECESSOR_EVENT_ID = "6c06d9673800c48c297d05211d9d31abb7f062ac9a483ac3dc38a16e5b25091b"
R7SQL_PREDECESSOR_GUARD_NAME = (
    "events.jsonl." + R7SQL_PREDECESSOR_EVENT_ID + ".guard"
)
R7SQL_SUCCESSOR_ADJUDICATION_NAME = "predecessor-adjudication.json"
R7SQL_SUCCESSOR_ADJUDICATION_SHA256 = "8ed992d4b2b4381994f69d0c661c4a18a8c2bb3e910aba4dbef928eaf011f756"
R7SQL_SUCCESSOR_ADJUDICATION_SIGNATURE_SHA256 = "14901b7799ac0711b35ee17279a4e8546e5dd6bd67608a0aaea28742cee3e250"
R7SQL_RUNTIME_PASS_RECEIPT_SHA256 = "92a8e424a0ab27ebded11a7872f0d9cc588631b380c9c4377ce49b8df82014e9"
WORK = "read-recovery-r7-cb1bc3984d8440aa965af5b928d2b4fa"
OWNER = "69893dc7b7c647f49967387e7efca9fb"
TASK_NAME = "Kairos-R7-TechnicalAlerts-V1-20261013"
SCOPE = "kairos-r7-technical-runtime-alerts-v1"
GROUP_ID = -1004475802889
EXPECTED_CONTAINER = "c08f5b667a84febb2dc1639857b44a52208ea29f9836e14c11685d89ccd55ae0"
RECEIPT_SHA256 = "03b10208edd5d5d7957ceaf2d38a6d73b7acbef03bfd4f2a87e1fa8ef88cacb0"
SOURCE_REVISION = "98016d0f28fb175ba3a49ad328c2779c000e27d3"
GENERATION_NAME = "kairos-epoch-69893dc7b7c6-serve-r7"
R5_RELATIVE_SOURCE = "development/ops_alerts/runtime_status_r5_notifier.py"
R5_SOURCE_SHA256 = "b53b24d3d97d5d4bb58384e87073e2a3d9ad22f853adec263ec84813553555db"
HANDOFF_RELATIVE_SOURCE = "development/ops_alerts/telegram_continuation.py"
HANDOFF_SHA256 = "b308e19753be088966e3fed4d1ddacc47ca3ef8d90089d1c527d1c93813d3930"
DELIVERY_RELATIVE_SOURCE = "scripts/alert_delivery.py"
DELIVERY_SHA256 = "fa9d58a7c1d7967c5aacf107accfbc72ff61fe5c71e4348a9c75dcf44e976ce5"
DEPLOY_INIT_RELATIVE_SOURCE = "scripts/__init__.py"
SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"})
MIN_COMPLETED_INBOX = 8070
MIN_WATERMARK_MS = 1_791_894_180_000
MAX_STATUS_AGE_SECONDS = 30.0
MAX_BYTES = 65_536
MAX_RECEIPT_BYTES = 1_048_576
MAX_RECORDS = 256
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_ALERT_STATES = {
    "failed_closed",
    "missing",
    "invalid",
    "unknown_owner",
    "running_stale",
}
_QUIET_STATES = {
    "running_fresh",
    "waiting_source_nontrading",
    "catching_up_nontrading",
}
_KNOWN_STATES = _ALERT_STATES | _QUIET_STATES
_SOURCE_TIMEOUT = "OFFICIAL_CLOSED_BAR_FETCH_TIMEOUT"
_SOURCE_DNS_FAILURE = "OFFICIAL_CLOSED_BAR_FETCH_DNS_FAILURE"
_R7DNS = {
    "name": "r7-dns",
    "runtime_root": Path(r"D:\Kairos\runtime\runtime-dns-recovery-20261015"),
    "private_root": R7DNS_PRIVATE_ROOT,
    "work": "preflight-b0a90145752d4b1486a466125afbc131",
    "owner": OWNER,
    "task_name": "Kairos-R7-DNS-TechnicalAlerts-V1-20261015",
    "scope": "kairos-r7-dns-technical-runtime-alerts-v1",
    "container": "5a9fff5848ccd57529029ab8214fc97cc33de6b7efaa371f376fdb07491a2e5b",
    "generation": "kairos-epoch-69893dc7b7c6-serve-r7-dns-b0a90145",
    "receipt_sha256": "5933c8c99e994209d7829c5cb5ab4862b4522fe43afb2d7ff80e8f74e90765f0",
    "signature_sha256": "534803efd215c6e866894aa9be107e9ac528f4e3ba1ebac33b6ec28dc055afb7",
    "source_revision": "ffa09ddb5a433bdf1dad75b2c8d1f4e9d7999b65",
    "failed_status_path": Path(
        r"D:\Kairos\runtime\runtime-incident-20261013\read-recovery-r7-cb1bc3984d8440aa965af5b928d2b4fa\output-serve\status.json"
    ),
    "failed_status_sha256": "faf607e8b86b05b579aee162ab113b417356ce409ca41e38b913e3c2b8302354",
}
_R7SQL = {
    "name": "r7-sql",
    "runtime_root": Path(r"D:\Kairos\runtime\runtime-sql-recovery-20261016"),
    "private_root": R7SQL_PRIVATE_ROOT,
    "work": "work-b45eda59250048a6b376f625be82febe",
    "owner": OWNER,
    "task_name": "Kairos-R7-SQL-TechnicalAlerts-V1-20261016",
    "scope": "kairos-r7-sql-technical-runtime-alerts-v1",
    "container": "2cfadb6fe53a58639db6c74bbdd31d993fe7bc05f817668979a8bee407021a83",
    "generation_pattern": (
        r"kairos-epoch-69893dc7b7c6-serve-r7-sql-[0-9a-f]{8}"
    ),
    "receipt_name": "controlled-continuation-receipt.json",
    "receipt_sha256": "6d2e855c4804dfaffdfab91e604ab9f13e634b553824bd05dde3fa724e161c74",
    "signature_sha256": "72491a955dd7a616143673e1d3958b386a9b2201b709940321977849d9e99161",
    "source_revision": "682d8e237d0046371717981728aa23199fbb2d86",
    "worker_sha256": "5d9389b05b43ccf69ae8e2afff562a659d50a02f7ea00689078919e04ed1103b",
    "old_failed_container": "5a9fff5848ccd57529029ab8214fc97cc33de6b7efaa371f376fdb07491a2e5b",
    "old_failed_status_sha256": (
        "3ca166304a0a083c9c234dd3f7a2f589ebd8df4d7fa58891cbed5ff8824d911c"
    ),
    "min_completed_inbox": 8602,
}


class R7Error(RuntimeError):
    """Redacted, stable failure category for the technical monitor."""

    def __init__(self, category: str):
        self.category = category
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


def _binding_record(profile: str = "legacy") -> dict[str, Any]:
    if profile == "r7-dns":
        return {
            "schema_version": 1,
            "scope": _R7DNS["scope"],
            "owner": _R7DNS["owner"],
            "task_name": _R7DNS["task_name"],
            "work": _R7DNS["work"],
            "serve_container_id": _R7DNS["container"],
            "receipt_sha256": _R7DNS["receipt_sha256"],
            "receipt_signature_sha256": _R7DNS["signature_sha256"],
            "receipt_source_revision": _R7DNS["source_revision"],
            "failed_status_sha256": _R7DNS["failed_status_sha256"],
            "trading_started": False,
            "business_signals_muted": True,
        }
    if profile == "r7-sql":
        return {
            "schema_version": 1,
            "scope": _R7SQL["scope"],
            "owner": _R7SQL["owner"],
            "task_name": _R7SQL["task_name"],
            "work": _R7SQL["work"],
            "serve_container_id": _R7SQL["container"],
            "generation_name_pattern": _R7SQL["generation_pattern"],
            "receipt_sha256": _R7SQL["receipt_sha256"],
            "receipt_signature_sha256": _R7SQL["signature_sha256"],
            "receipt_source_revision": _R7SQL["source_revision"],
            "private_root": str(R7SQL_PRIVATE_ROOT),
            "predecessor_adjudication_sha256": R7SQL_SUCCESSOR_ADJUDICATION_SHA256,
            "runtime_pass_receipt_sha256": R7SQL_RUNTIME_PASS_RECEIPT_SHA256,
            "trading_started": False,
            "business_signals_muted": True,
        }
    if profile != "legacy":
        raise R7Error("R7_PROFILE_INVALID")
    return {
        "schema_version": 1,
        "scope": SCOPE,
        "owner": OWNER,
        "task_name": TASK_NAME,
        "work": WORK,
        "serve_container_id": EXPECTED_CONTAINER,
        "receipt_sha256": RECEIPT_SHA256,
        "receipt_source_revision": SOURCE_REVISION,
        "trading_started": False,
        "business_signals_muted": True,
    }


def _binding_bytes(profile: str = "legacy") -> bytes:
    return json.dumps(
        _binding_record(profile), sort_keys=True, separators=(",", ":")
    ).encode()


def _binding_sha256(profile: str = "legacy") -> str:
    return hashlib.sha256(_binding_bytes(profile)).hexdigest()


def _source_revision(profile: str) -> str:
    if profile == "r7-dns":
        return _R7DNS["source_revision"]
    if profile == "r7-sql":
        return _R7SQL["source_revision"]
    return SOURCE_REVISION


def _require_r7_sql_pins(spec: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = _R7SQL if spec is None else spec
    if (
        not isinstance(spec.get("receipt_sha256"), str)
        or _HEX64.fullmatch(spec["receipt_sha256"]) is None
        or not isinstance(spec.get("signature_sha256"), str)
        or _HEX64.fullmatch(spec["signature_sha256"]) is None
        or not isinstance(spec.get("container"), str)
        or re.fullmatch(r"[0-9a-f]{64}", spec["container"]) is None
    ):
        raise R7Error("R7SQL_RECEIPT_SIGNATURE_AND_SERVE_PINS_REQUIRED")
    return spec


def _validate_r7_sql_receipt(
    receipt: Any, *, spec: dict[str, Any] | None = None
) -> dict[str, Any]:
    spec = _require_r7_sql_pins(spec)
    if not isinstance(receipt, dict):
        raise R7Error("R7SQL_RECEIPT_INVALID")
    receipt_work = spec["runtime_root"] / spec["work"]
    serve_name = receipt.get("new_serve_name")
    serve_status = receipt.get("serve_status")
    restart_status = receipt.get("restart_status")
    readiness = receipt.get("readiness")
    status_fields = (
        "owner",
        "state",
        "cycles",
        "watermarks_ms",
        "pending_outbox",
        "unresolved_inbox",
        "completed_inbox",
        "uncompleted_publications",
        "new_publications",
        "observed_at_utc",
        "PAPER_QUALIFIED",
        "ALPHA_READY",
        "LIVE_READY",
        "STRATEGY_POLICY",
        "trading_started",
    )

    def valid_status(value: Any) -> bool:
        if not isinstance(value, dict) or not set(status_fields).issubset(value):
            return False
        watermarks = value.get("watermarks_ms")
        try:
            observed = datetime.fromisoformat(
                value["observed_at_utc"].replace("Z", "+00:00")
            )
        except (AttributeError, TypeError, ValueError):
            return False
        return (
            value.get("owner") == spec["owner"]
            and value.get("state") == "RUNNING_NONTRADING"
            and type(value.get("cycles")) is int
            and value["cycles"] > 0
            and isinstance(watermarks, dict)
            and set(watermarks) == SYMBOLS
            and all(type(mark) is int and mark > 0 for mark in watermarks.values())
            and all(
                type(value.get(key)) is int and value[key] == 0
                for key in (
                    "pending_outbox",
                    "unresolved_inbox",
                    "uncompleted_publications",
                )
            )
            and type(value.get("completed_inbox")) is int
            and value["completed_inbox"] >= spec["min_completed_inbox"]
            and type(value.get("new_publications")) is int
            and value["new_publications"] >= 0
            and all(
                value.get(key) is False
                for key in ("PAPER_QUALIFIED", "ALPHA_READY", "LIVE_READY", "trading_started")
            )
            and value.get("STRATEGY_POLICY") == "REJECT_ALL"
            and observed.tzinfo is not None
            and observed.utcoffset() is not None
        )

    try:
        if (
            type(receipt.get("schema_version")) is not int
            or receipt["schema_version"] != 1
            or receipt.get("state") != "PASS_NONTRADING_SQL_CONTINUATION"
            or receipt.get("owner") != spec["owner"]
            or receipt.get("work_directory") != str(receipt_work)
            or receipt.get("deploy_root") != str(DEPLOY_ROOT)
            or receipt.get("deploy_revision") != spec["source_revision"]
            or receipt.get("worker_sha256")
            != "5d9389b05b43ccf69ae8e2afff562a659d50a02f7ea00689078919e04ed1103b"
            or receipt.get("new_serve_id") != spec["container"]
            or not isinstance(serve_name, str)
            or re.fullmatch(spec["generation_pattern"], serve_name) is None
            or receipt.get("old_failed_container_id") != spec["old_failed_container"]
            or receipt.get("old_failed_status_sha256")
            != spec["old_failed_status_sha256"]
            or receipt.get("legacy_unchanged") is not True
            or receipt.get("five_symbol_fresh_progress_proven") is not True
            or receipt.get("all_native_queue_rows_caught_up") is not True
            or receipt.get("execution_rows_after") != 0
            or receipt.get("trading_started") is not False
            or receipt.get("orders_submitted") != 0
            or receipt.get("paid_calls") != 0
            or receipt.get("primary_migration") is not False
            or receipt.get("automatic_retry") is not False
            or readiness
            != {"PAPER_QUALIFIED": False, "ALPHA_READY": False, "LIVE_READY": False}
            or not valid_status(serve_status)
            or not valid_status(restart_status)
        ):
            raise R7Error("R7SQL_RECEIPT_INVALID")
        before_time = datetime.fromisoformat(
            serve_status["observed_at_utc"].replace("Z", "+00:00")
        )
        after_time = datetime.fromisoformat(
            restart_status["observed_at_utc"].replace("Z", "+00:00")
        )
        if (
            after_time <= before_time
            or any(
                restart_status["watermarks_ms"][symbol]
                <= serve_status["watermarks_ms"][symbol]
                for symbol in SYMBOLS
            )
        ):
            raise R7Error("R7SQL_RESTART_PROOF_INVALID")
    except R7Error:
        raise
    except Exception:  # noqa: BLE001 - never surface private receipt details.
        raise R7Error("R7SQL_RECEIPT_INVALID") from None
    return receipt


def _load_r5_helpers() -> Any:
    """Import only the byte-pinned R5 protected-reader/transport helper."""
    path = ROOT / R5_RELATIVE_SOURCE
    raw = _bounded_source(path, 256 * 1024)
    if len(raw) > 256 * 1024 or hashlib.sha256(raw).hexdigest() != R5_SOURCE_SHA256:
        raise R7Error("PROTECTED_HELPER_MISMATCH")
    name = "_kairos_pinned_r5_runtime_helpers_for_r7"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise R7Error("PROTECTED_HELPER_REQUIRED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - never disclose helper/import diagnostics.
        sys.modules.pop(name, None)
        raise R7Error("PROTECTED_HELPER_REQUIRED") from None
    if (
        Path(module.__file__).resolve() != path.resolve()
        or hashlib.sha256(_bounded_source(path, 256 * 1024)).hexdigest()
        != R5_SOURCE_SHA256
    ):
        sys.modules.pop(name, None)
        raise R7Error("PROTECTED_HELPER_MISMATCH")
    return module


def _bounded_source(path: Path, maximum: int) -> bytes:
    try:
        before = path.lstat()
        if (
            path.is_symlink()
            or getattr(before, "st_file_attributes", 0) & 0x400
            or not path.is_file()
            or not 0 < before.st_size <= maximum
        ):
            raise R7Error("PROTECTED_HELPER_REQUIRED")
        fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise R7Error("PROTECTED_HELPER_REQUIRED")
            raw = stream.read(maximum + 1)
        if len(raw) != before.st_size or len(raw) > maximum:
            raise R7Error("PROTECTED_HELPER_REQUIRED")
        return raw
    except R7Error:
        raise
    except Exception:  # noqa: BLE001 - safe path errors remain redacted.
        raise R7Error("PROTECTED_HELPER_REQUIRED") from None


def _initializer_source_bytes(raw: bytes) -> bytes:
    """Allow uniform checkout LF/CRLF only for the signed Deploy initializer."""
    if b"\r" in raw:
        without_pairs = raw.replace(b"\r\n", b"")
        if b"\r" in without_pairs or b"\n" in without_pairs:
            raise R7Error("DEPLOY_NAMESPACE_IMPORT_REJECTED")
        raw = raw.replace(b"\r\n", b"\n")
    try:
        raw.decode("utf-8", "strict")
    except UnicodeError:
        raise R7Error("DEPLOY_NAMESPACE_IMPORT_REJECTED") from None
    return raw


def _verify_signed_source(helpers: Any, *, profile: str = "legacy") -> None:
    """Require this runner and its installer/tests to be the exact signed main bytes."""
    try:
        for namespace_init in (
            ROOT / "development" / "__init__.py",
            ROOT / "development" / "ops_alerts" / "__init__.py",
        ):
            if namespace_init.exists() or namespace_init.is_symlink():
                raise R7Error("META_NAMESPACE_IMPORT_REJECTED")
        head = (
            helpers._git(ROOT, ["show", "-s", "--format=%H %G? %GF", "HEAD"])
            .decode("ascii", "strict")
            .strip()
            .split()
        )
        if (
            len(head) != 3
            or head[1:] != ["G", helpers.SIGNER]
            or helpers._git(ROOT, ["branch", "--show-current"]).decode().strip()
            != "main"
            or helpers._git(ROOT, ["rev-parse", "origin/main"]).decode().strip()
            != head[0]
        ):
            raise R7Error("SIGNED_R7_SOURCE_REQUIRED")
        deploy_source = (
            helpers._git(
                DEPLOY_ROOT,
                [
                    "show",
                    "-s",
                    "--format=%H %G? %GF",
                    _source_revision(profile),
                ],
            )
            .decode("ascii", "strict")
            .strip()
            .split()
        )
        source_revision = _source_revision(profile)
        if deploy_source != [source_revision, "G", helpers.SIGNER]:
            raise R7Error("SIGNED_R7_SOURCE_REQUIRED")
        deploy_head = (
            helpers._git(DEPLOY_ROOT, ["show", "-s", "--format=%H %G? %GF", "HEAD"])
            .decode("ascii", "strict")
            .strip()
            .split()
        )
        deploy_head_id = deploy_head[0] if deploy_head else ""
        if (
            len(deploy_head) != 3
            or deploy_head[1:] != ["G", helpers.SIGNER]
            or helpers._git(DEPLOY_ROOT, ["branch", "--show-current"])
            .decode("ascii", "strict")
            .strip()
            != "main"
            or helpers._git(DEPLOY_ROOT, ["rev-parse", "origin/main"])
            .decode("ascii", "strict")
            .strip()
            != deploy_head_id
        ):
            raise R7Error("SIGNED_R7_SOURCE_REQUIRED")
        helpers._git(
            DEPLOY_ROOT,
            ["merge-base", "--is-ancestor", source_revision, deploy_head_id],
        )
        for relative in (
            "development/ops_alerts/runtime_status_r7_notifier.py",
            "development/ops_alerts/test_runtime_status_r7_notifier.py",
            "development/ops_alerts/Install-R7RuntimeAlertTask.ps1",
            R5_RELATIVE_SOURCE,
            HANDOFF_RELATIVE_SOURCE,
        ):
            committed = helpers._git(ROOT, ["show", f"{head[0]}:{relative}"])
            local = helpers._read(ROOT / relative, 512 * 1024)
            if (
                committed != local
                or helpers._git(ROOT, ["status", "--porcelain", "--", relative]).strip()
            ):
                raise R7Error("SIGNED_R7_SOURCE_REQUIRED")
        for relative, expected_sha in ((HANDOFF_RELATIVE_SOURCE, HANDOFF_SHA256),):
            if (
                hashlib.sha256(helpers._read(ROOT / relative, 256 * 1024)).hexdigest()
                != expected_sha
            ):
                raise R7Error("PINNED_HANDOFF_MISMATCH")
        for relative, expected_sha in ((DELIVERY_RELATIVE_SOURCE, DELIVERY_SHA256),):
            committed = helpers._git(
                DEPLOY_ROOT, ["show", f"{deploy_head_id}:{relative}"]
            )
            local = helpers._read(DEPLOY_ROOT / relative, 512 * 1024)
            if (
                committed != local
                or hashlib.sha256(local).hexdigest() != expected_sha
                or helpers._git(
                    DEPLOY_ROOT, ["status", "--porcelain", "--", relative]
                ).strip()
            ):
                raise R7Error("PINNED_DELIVERY_MISMATCH")
        init_committed = helpers._git(
            DEPLOY_ROOT, ["show", f"{deploy_head_id}:{DEPLOY_INIT_RELATIVE_SOURCE}"]
        )
        init_local = helpers._read(DEPLOY_ROOT / DEPLOY_INIT_RELATIVE_SOURCE, 64 * 1024)
        if (
            _initializer_source_bytes(init_committed)
            != _initializer_source_bytes(init_local)
            or helpers._git(
                DEPLOY_ROOT,
                ["status", "--porcelain", "--", DEPLOY_INIT_RELATIVE_SOURCE],
            ).strip()
        ):
            raise R7Error("DEPLOY_NAMESPACE_IMPORT_REJECTED")
    except R7Error:
        raise
    except Exception:  # noqa: BLE001 - signed-source failures remain redacted.
        raise R7Error("SIGNED_R7_SOURCE_REQUIRED") from None


def _protected_read(path: Path, *, helpers: Any, delivery: Any, maximum: int) -> bytes:
    try:
        return helpers._read_private(path, maximum=maximum, delivery=delivery)
    except Exception:  # noqa: BLE001 - collapse filesystem/ACL detail.
        raise R7Error("PROTECTED_EVIDENCE_REQUIRED") from None


def _verify_r7sql_successor_adjudication(source: dict[str, Any]) -> None:
    """Verify the signed, pinned operator adjudication before touching status."""
    if any(
        _HEX64.fullmatch(value) is None or value == "0" * 64
        for value in (
            R7SQL_SUCCESSOR_ADJUDICATION_SHA256,
            R7SQL_SUCCESSOR_ADJUDICATION_SIGNATURE_SHA256,
            R7SQL_RUNTIME_PASS_RECEIPT_SHA256,
        )
    ):
        raise R7Error("R7SQL_SUCCESSOR_ADJUDICATION_NOT_PINNED")
    helpers, delivery = source["helpers"], source["delivery"]
    old_root = R7SQL_PREDECESSOR_ROOT
    new_root = R7SQL_PRIVATE_ROOT
    proof_path = new_root / R7SQL_SUCCESSOR_ADJUDICATION_NAME
    signature_path = proof_path.with_name(proof_path.name + ".asc")
    for path in (old_root, new_root, proof_path, signature_path):
        delivery._no_reparse(path)
        delivery._private_acl(path)
    raw = _protected_read(
        proof_path, helpers=helpers, delivery=delivery, maximum=8192
    )
    signature_raw = _protected_read(
        signature_path, helpers=helpers, delivery=delivery, maximum=16_384
    )
    if (
        hashlib.sha256(raw).hexdigest() != R7SQL_SUCCESSOR_ADJUDICATION_SHA256
        or hashlib.sha256(signature_raw).hexdigest()
        != R7SQL_SUCCESSOR_ADJUDICATION_SIGNATURE_SHA256
    ):
        raise R7Error("R7SQL_SUCCESSOR_ADJUDICATION_HASH_MISMATCH")
    try:
        helpers._verify_signature(proof_path, signature_path)
    except Exception:  # noqa: BLE001 - verifier diagnostics may contain private data.
        raise R7Error("R7SQL_SUCCESSOR_ADJUDICATION_SIGNATURE_INVALID") from None
    proof = _json(raw)
    expected_keys = {
        "schema_version",
        "kind",
        "predecessor_root",
        "predecessor_binding_name",
        "predecessor_binding_sha256",
        "predecessor_journal_name",
        "predecessor_journal_sha256",
        "predecessor_guard_name",
        "predecessor_guard_sha256",
        "event_id",
        "human_adjudication",
        "event_resend_authorized",
        "runtime_pass_receipt_sha256",
        "trading_started",
    }
    if (
        not isinstance(proof, dict)
        or set(proof) != expected_keys
        or type(proof.get("schema_version")) is not int
        or proof.get("schema_version") != 1
        or proof.get("kind") != "kairos.r7sql.notifier-successor-adjudication.v1"
        or proof.get("predecessor_root") != str(old_root)
        or proof.get("predecessor_binding_name") != "binding.json"
        or proof.get("predecessor_journal_name") != "events.jsonl"
        or proof.get("predecessor_guard_name") != R7SQL_PREDECESSOR_GUARD_NAME
        or proof.get("event_id") != R7SQL_PREDECESSOR_EVENT_ID
        or proof.get("human_adjudication")
        != "CONFIRMED_EVENT_ABSENT_FROM_FINAL_GROUP"
        or proof.get("event_resend_authorized") is not False
        or proof.get("runtime_pass_receipt_sha256")
        != R7SQL_RUNTIME_PASS_RECEIPT_SHA256
        or proof.get("trading_started") is not False
    ):
        raise R7Error("R7SQL_SUCCESSOR_ADJUDICATION_INVALID")
    old_files = (
        (old_root / "binding.json", "predecessor_binding_sha256", 4096),
        (old_root / "events.jsonl", "predecessor_journal_sha256", MAX_BYTES),
        (old_root / R7SQL_PREDECESSOR_GUARD_NAME, "predecessor_guard_sha256", 4096),
    )
    for path, digest_key, maximum in old_files:
        delivery._no_reparse(path)
        delivery._private_acl(path)
        previous = _protected_read(
            path, helpers=helpers, delivery=delivery, maximum=maximum
        )
        pinned = proof.get(digest_key)
        if (
            not isinstance(pinned, str)
            or _HEX64.fullmatch(pinned) is None
            or hashlib.sha256(previous).hexdigest() != pinned
        ):
            raise R7Error("R7SQL_PREDECESSOR_EVIDENCE_CHANGED")


def _profile_root(source: dict[str, Any], requested: Path | None) -> Path:
    profile = source.get("profile", "legacy")
    fixed = {
        "legacy": PRIVATE_ROOT,
        "r7-dns": R7DNS_PRIVATE_ROOT,
        "r7-sql": R7SQL_PRIVATE_ROOT,
    }.get(profile, PRIVATE_ROOT)
    if profile == "r7-sql":
        if requested is not None and requested != fixed:
            raise R7Error("R7SQL_SUCCESSOR_ROOT_OVERRIDE_REJECTED")
        if (
            source.get("binding") != _binding_record("r7-sql")
            or source.get("binding_sha256") != _binding_sha256("r7-sql")
        ):
            raise R7Error("R7SQL_SUCCESSOR_BINDING_INVALID")
        _verify_r7sql_successor_adjudication(source)
        return fixed
    return requested or fixed


def _write_new(path: Path, raw: bytes, continuation: Any, delivery: Any) -> None:
    try:
        continuation._exclusive_fsync(path, raw)
        continuation._set_exact_file_acl(path)
        delivery._no_reparse(path)
        delivery._private_acl(path)
    except Exception:  # noqa: BLE001 - create-only protected writes are redacted.
        raise R7Error("R7_PRIVATE_WRITE_FAILED") from None


def admit_r7(*, helpers: Any | None = None, profile: str = "legacy") -> dict[str, Any]:
    """Admit only the immutable accepted R7 receipt and its protected status path."""
    helpers = helpers or _load_r5_helpers()
    try:
        if profile not in {"legacy", "r7-dns", "r7-sql"}:
            raise R7Error("R7_PROFILE_INVALID")
        spec = (
            _R7DNS
            if profile == "r7-dns"
            else _require_r7_sql_pins()
            if profile == "r7-sql"
            else None
        )
        _verify_signed_source(helpers, profile=profile)
        continuation, delivery = helpers._continuation()
        work = spec["runtime_root"] / spec["work"] if spec else RUNTIME_ROOT / WORK
        delivery._no_reparse(work)
        delivery._private_acl(work)
        receipt_name = spec.get("receipt_name", "receipt.json") if spec else "receipt.json"
        receipt_path = work / receipt_name
        receipt_raw = _protected_read(
            receipt_path, helpers=helpers, delivery=delivery, maximum=MAX_RECEIPT_BYTES
        )
        signature_path = work / (receipt_name + ".asc")
        helpers._verify_signature(receipt_path, signature_path)
        if spec:
            signature_raw = _protected_read(
                signature_path, helpers=helpers, delivery=delivery, maximum=16_384
            )
            if hashlib.sha256(signature_raw).hexdigest() != spec["signature_sha256"]:
                raise R7Error(
                    "R7SQL_RECEIPT_SIGNATURE_MISMATCH"
                    if profile == "r7-sql"
                    else "R7DNS_RECEIPT_SIGNATURE_MISMATCH"
                )
        expected_receipt_sha = spec["receipt_sha256"] if spec else RECEIPT_SHA256
        if hashlib.sha256(receipt_raw).hexdigest() != expected_receipt_sha:
            raise R7Error(
                "R7SQL_RECEIPT_MISMATCH"
                if profile == "r7-sql"
                else "R7_RECEIPT_MISMATCH"
            )
        receipt = _json(receipt_raw)
        if profile == "r7-dns":
            failed_path = spec["failed_status_path"]
            delivery._no_reparse(failed_path)
            failed_raw = _protected_read(
                failed_path, helpers=helpers, delivery=delivery, maximum=MAX_BYTES
            )
            failed = _json(failed_raw)
            if (
                hashlib.sha256(failed_raw).hexdigest() != spec["failed_status_sha256"]
                or not isinstance(failed, dict)
                or failed.get("error_type") != "ClientConnectorDNSError"
            ):
                raise R7Error("R7DNS_ORIGINAL_FAILURE_LATCH_CHANGED")
            continuation_receipt = (
                receipt.get("continuation") if isinstance(receipt, dict) else None
            )
            continuation_status = (
                continuation_receipt.get("status")
                if isinstance(continuation_receipt, dict)
                else None
            )
            if (
                not isinstance(receipt, dict)
                or receipt.get("state") != "PASS_REVIEWED_NONTRADING_DNS_CONTINUATION"
                or receipt.get("source_revision") != spec["source_revision"]
                or receipt.get("failed_status_sha256") != spec["failed_status_sha256"]
                or receipt.get("legacy_unchanged") is not True
                or receipt.get("trading_started") is not False
                or receipt.get("serving_restart") is not False
                or not isinstance(continuation_receipt, dict)
                or continuation_receipt.get("container") != _R7DNS["generation"]
                or continuation_receipt.get("container_id") != spec["container"]
                or continuation_receipt.get("state")
                != "PASS_REVIEWED_NONTRADING_DNS_CONTINUATION"
                or continuation_receipt.get("graceful_restart_proven") is not True
                or continuation_receipt.get("trading_started") is not False
                or not isinstance(continuation_status, dict)
                or continuation_status.get("owner") != spec["owner"]
                or continuation_status.get("state")
                not in {"RUNNING_NONTRADING", "WAITING_SOURCE_NONTRADING"}
                or continuation_status.get("trading_started") is not False
                or continuation_status.get("PAPER_QUALIFIED") is not False
                or continuation_status.get("ALPHA_READY") is not False
                or continuation_status.get("LIVE_READY") is not False
                or continuation_status.get("STRATEGY_POLICY") != "REJECT_ALL"
                or any(
                    type(continuation_status.get(key)) is not int
                    or continuation_status[key] != 0
                    for key in (
                        "pending_outbox",
                        "unresolved_inbox",
                        "uncompleted_publications",
                    )
                )
            ):
                raise R7Error("R7DNS_RECEIPT_INVALID")
        elif profile == "r7-sql":
            _validate_r7_sql_receipt(receipt, spec=spec)
        generation = receipt.get("generation") if isinstance(receipt, dict) else None
        generation_status = (
            generation.get("status") if isinstance(generation, dict) else None
        )
        if (
            not isinstance(receipt, dict)
            or (profile == "legacy" and receipt.get("result") != "PASS_NEW_NONTRADING_GENERATION")
            or (profile == "legacy" and receipt.get("owner") != OWNER)
            or (profile == "legacy" and receipt.get("source_revision") != SOURCE_REVISION)
            or (profile == "legacy" and receipt.get("trading_started") is not False)
            or (
                profile == "legacy"
                and (
                    not isinstance(generation, dict)
                    or generation.get("name") != GENERATION_NAME
                    or generation.get("container_id") != EXPECTED_CONTAINER
                    or not isinstance(generation_status, dict)
                    or generation_status.get("state") != "RUNNING_NONTRADING"
                    or generation_status.get("owner") != OWNER
                    or any(
                        type(generation_status.get(key)) is not int
                        or generation_status[key] != 0
                        for key in (
                            "pending_outbox",
                            "unresolved_inbox",
                            "uncompleted_publications",
                        )
                    )
                )
            )
            or (
                profile == "legacy"
                and any(
                    receipt.get(key) is not False
                    for key in ("PAPER_QUALIFIED", "ALPHA_READY", "LIVE_READY")
                )
            )
            or (profile == "legacy" and receipt.get("STRATEGY_POLICY") != "REJECT_ALL")
        ):
            raise R7Error("R7_RECEIPT_INVALID")
        return {
            "helpers": helpers,
            "continuation": continuation,
            "delivery": delivery,
            "profile": profile,
            "binding": _binding_record(profile),
            "binding_sha256": _binding_sha256(profile),
            "receipt": receipt,
        }
    except R7Error:
        raise
    except Exception:  # noqa: BLE001 - admission errors are intentionally redacted.
        raise R7Error("R7_SOURCE_ADMISSION_FAILED") from None


def _source_pause_valid(
    value: dict[str, Any], state: str, *, profile: str = "legacy"
) -> bool:
    circuit = value.get("source_transport")
    base_keys = {"timeout_rounds", "recoveries", "consecutive_timeout_rounds"}
    dns_keys = {"dns_failure_rounds", "consecutive_dns_failure_rounds"}
    waiting = state == "WAITING_SOURCE_NONTRADING"
    if profile in {"r7-dns", "r7-sql"}:
        schema = frozenset(circuit) if isinstance(circuit, dict) else None
        has_dns_telemetry = schema == frozenset(base_keys | dns_keys)
        expected_schemas = {frozenset(base_keys), frozenset(base_keys | dns_keys)}
        if (
            not isinstance(circuit, dict)
            or schema not in expected_schemas
            or any(type(circuit[key]) is not int or circuit[key] < 0 for key in schema)
        ):
            return False
        dns_rounds = circuit.get("dns_failure_rounds", 0)
        consecutive_dns = circuit.get("consecutive_dns_failure_rounds", 0)
        return (
            (not has_dns_telemetry or dns_rounds >= 1)
            and circuit["recoveries"] <= circuit["timeout_rounds"] + dns_rounds
            and circuit["consecutive_timeout_rounds"] <= circuit["timeout_rounds"]
            and consecutive_dns <= dns_rounds
            and (
                (
                    (
                        value.get("source_wait_reason") == _SOURCE_TIMEOUT
                        and circuit["consecutive_timeout_rounds"] >= 1
                        and consecutive_dns == 0
                    )
                    or (
                        has_dns_telemetry
                        and value.get("source_wait_reason") == _SOURCE_DNS_FAILURE
                        and consecutive_dns >= 1
                        and circuit["consecutive_timeout_rounds"] == 0
                    )
                )
                if waiting
                else value.get("source_wait_reason") is None
                and circuit["consecutive_timeout_rounds"] == 0
                and consecutive_dns == 0
            )
        )
    return (
        isinstance(circuit, dict)
        and set(circuit) == base_keys
        and all(type(circuit[key]) is int and circuit[key] >= 0 for key in base_keys)
        and circuit["recoveries"] <= circuit["timeout_rounds"]
        and circuit["consecutive_timeout_rounds"] <= circuit["timeout_rounds"]
        and (
            (
                value.get("source_wait_reason") == _SOURCE_TIMEOUT
                and circuit["consecutive_timeout_rounds"] > 0
            )
            if waiting
            else value.get("source_wait_reason") is None
            and circuit["consecutive_timeout_rounds"] == 0
        )
    )


def classify_status(
    value: Any, *, now: datetime | None = None, profile: str = "legacy"
) -> str:
    """Validate the R7 status contract and return a quiet or alert state."""
    if not isinstance(value, dict):
        return "invalid"
    state = value.get("state")
    if not isinstance(state, str) or state not in {
        "RUNNING_NONTRADING",
        "WAITING_SOURCE_NONTRADING",
        "CATCHING_UP_NONTRADING",
    }:
        return "failed_closed"
    try:
        observed = datetime.fromisoformat(
            value["observed_at_utc"].replace("Z", "+00:00")
        )
    except (KeyError, AttributeError, TypeError, ValueError):
        return "invalid"
    current = now or datetime.now(UTC)
    if (
        observed.tzinfo is None
        or observed.utcoffset() is None
        or current.tzinfo is None
        or current.utcoffset() is None
    ):
        return "invalid"
    age = (current.astimezone(UTC) - observed.astimezone(UTC)).total_seconds()
    if age < 0:
        return "invalid"
    if age > MAX_STATUS_AGE_SECONDS:
        return "running_stale"
    watermarks = value.get("watermarks_ms")
    circuit_valid = _source_pause_valid(value, state, profile=profile)
    valid = (
        value.get("owner") == (OWNER if profile != "r7-dns" else _R7DNS["owner"])
        and type(value.get("cycles")) is int
        and value["cycles"] >= 0
        and type(value.get("completed_inbox")) is int
        and value["completed_inbox"]
        >= (_R7SQL["min_completed_inbox"] if profile == "r7-sql" else MIN_COMPLETED_INBOX)
        and value.get("trading_started") is False
        and value.get("PAPER_QUALIFIED") is False
        and value.get("ALPHA_READY") is False
        and value.get("LIVE_READY") is False
        and value.get("STRATEGY_POLICY") == "REJECT_ALL"
        and value.get("source_fresh") is (state == "RUNNING_NONTRADING")
        and all(
            type(value.get(key)) is int and value[key] == 0
            for key in (
                "pending_outbox",
                "unresolved_inbox",
                "uncompleted_publications",
            )
        )
        and isinstance(watermarks, dict)
        and set(watermarks) == SYMBOLS
        and all(
            type(mark) is int and mark >= MIN_WATERMARK_MS
            for mark in watermarks.values()
        )
        and circuit_valid
    )
    if not valid:
        return "invalid"
    if state == "RUNNING_NONTRADING":
        return "running_fresh"
    return (
        "waiting_source_nontrading"
        if state == "WAITING_SOURCE_NONTRADING"
        else "catching_up_nontrading"
    )


def read_status(path: Path, *, source: dict[str, Any]) -> str:
    """Read just the admitted status file using the existing protected helper."""
    helpers, delivery = source["helpers"], source["delivery"]
    try:
        delivery._no_reparse(path)
        try:
            path.lstat()
        except FileNotFoundError:
            return "missing"
        except Exception:  # noqa: BLE001 - local path errors become a technical alert.
            return "invalid"
        raw = _protected_read(
            path, helpers=helpers, delivery=delivery, maximum=MAX_BYTES
        )
        return classify_status(_json(raw), profile=source.get("profile", "legacy"))
    except R7Error:
        return "invalid"
    except Exception:  # noqa: BLE001 - malformed status is a redacted alert.
        return "invalid"


def _status_path(binding: dict[str, Any]) -> Path:
    if binding == _binding_record():
        return RUNTIME_ROOT / WORK / "output-serve" / "status.json"
    if binding == _binding_record("r7-dns"):
        return _R7DNS["runtime_root"] / _R7DNS["work"] / "output-serve" / "status.json"
    if binding == _binding_record("r7-sql"):
        return (
            _R7SQL["runtime_root"]
            / _R7SQL["work"]
            / "output-serve"
            / "status.json"
        )
    raise R7Error("R7_BINDING_INVALID")


class R7Journal:
    """Independent R7 journal; only low-level locked append is borrowed from R5."""

    def __init__(
        self,
        path: Path,
        continuation: Any,
        delivery: Any,
        helpers: Any,
        binding_sha256: str | None = None,
    ):
        self.path, self.c, self.delivery = path, continuation, delivery
        self.binding_sha256 = binding_sha256 or _binding_sha256()
        self.lease_path = path.with_name(path.name + ".lock")
        self._base = helpers.R5Journal
        self._error = helpers.R5Error

    @contextmanager
    def locked(self):
        with self._base.locked(self):
            yield

    def _append(self, row: dict[str, Any]) -> None:
        encoded = (
            json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        rows = self.read(allow_pending=row.get("kind") == "send_outcome")
        previous = self._verify(self.path) if self.path.exists() else b""
        # Check before the borrowed primitive creates an irreversible send
        # guard. A reservation must also leave room for its bounded outcome.
        reserve_outcome = row.get("kind") == "send_reserved"
        required_records = 2 if reserve_outcome else 1
        required_bytes = len(encoded) + (1024 if reserve_outcome else 0)
        if (
            len(encoded) > 1024
            or len(rows) + required_records > MAX_RECORDS
            or len(previous) + required_bytes > MAX_BYTES
        ):
            raise R7Error("R7_JOURNAL_LIMIT_BEFORE_GUARD")
        self._base._append(self, row)

    def _verify(self, path: Path) -> bytes:
        return self._base._verify(self, path)

    def read(self, *, allow_pending: bool = False) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        raw = self._verify(self.path)
        if not raw.endswith(b"\n") or len(raw) > MAX_BYTES:
            raise R7Error("R7_JOURNAL_INVALID")
        try:
            rows = [_json(line) for line in raw.splitlines()]
            if len(rows) > MAX_RECORDS or any(
                type(row.get("seq")) is not int or row["seq"] != i
                for i, row in enumerate(rows)
            ):
                raise ValueError("sequence")
            first = rows[0]
            if (
                set(first)
                != {"schema_version", "seq", "kind", "state", "binding_sha256"}
                or type(first.get("schema_version")) is not int
                or first["schema_version"] != 1
                or first.get("kind") != "baseline"
                or first.get("state") not in _KNOWN_STATES
                or first.get("binding_sha256") != self.binding_sha256
            ):
                raise ValueError("baseline")
            current, pending = first["state"], None
            for row in rows[1:]:
                if (
                    set(row) == {"schema_version", "seq", "kind", "state"}
                    and type(row.get("schema_version")) is int
                    and row["schema_version"] == 1
                    and row.get("kind") == "observe"
                    and row.get("state") in _KNOWN_STATES
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
                    and type(row.get("schema_version")) is int
                    and row["schema_version"] == 1
                    and row.get("kind") == "send_reserved"
                    and row.get("state") == current
                    and row.get("state") in _KNOWN_STATES
                    and row.get("transition") in {"firing", "resolved"}
                    and isinstance(row.get("event_id"), str)
                    and _HEX64.fullmatch(row["event_id"])
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
                    and type(row.get("schema_version")) is int
                    and row["schema_version"] == 1
                    and row.get("kind") == "send_outcome"
                    and pending is not None
                    and row.get("event_id") == pending["event_id"]
                    and row.get("transition") == pending["transition"]
                    and row.get("state") == pending["state"]
                    and row.get("result") in {"accepted", "unknown"}
                ):
                    if row["result"] == "unknown":
                        raise R7Error("R7_SEND_OUTCOME_UNKNOWN")
                    pending = None
                else:
                    raise ValueError("event")
            if pending is not None and not allow_pending:
                raise R7Error("R7_SEND_OUTCOME_UNKNOWN")
            return rows
        except R7Error:
            raise
        except Exception:  # noqa: BLE001 - do not leak local journal diagnostics.
            raise R7Error("R7_JOURNAL_INVALID") from None


def initialize(
    *,
    source_admitter: Callable[[], dict[str, Any]] = admit_r7,
    observer: Callable[[Path, dict[str, Any]], str] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    source = source_admitter()
    helpers, continuation, delivery = (
        source["helpers"],
        source["continuation"],
        source["delivery"],
    )
    root = _profile_root(source, root)
    delivery._no_reparse(root)
    delivery._private_acl(root)
    binding_path = root / "binding.json"
    binding_bytes = _binding_bytes(source.get("profile", "legacy"))
    successor = source.get("profile") == "r7-sql"
    if successor:
        expected_entries = {
            R7SQL_SUCCESSOR_ADJUDICATION_NAME,
            R7SQL_SUCCESSOR_ADJUDICATION_NAME + ".asc",
        }
        try:
            if {entry.name for entry in root.iterdir()} != expected_entries:
                raise R7Error("R7SQL_SUCCESSOR_ROOT_NOT_CLEAN")
        except R7Error:
            raise
        except Exception:  # noqa: BLE001 - private root errors remain redacted.
            raise R7Error("R7SQL_SUCCESSOR_ROOT_NOT_CLEAN") from None
        if binding_path.exists() or (root / "events.jsonl").exists():
            raise R7Error("R7SQL_SUCCESSOR_ROOT_NOT_CLEAN")
    if binding_path.exists():
        if (
            _protected_read(
                binding_path, helpers=helpers, delivery=delivery, maximum=4096
            )
            != binding_bytes
        ):
            raise R7Error("R7_BINDING_CHANGED")
    elif not successor:
        _write_new(binding_path, binding_bytes, continuation, delivery)
    journal = R7Journal(
        root / "events.jsonl", continuation, delivery, helpers, source["binding_sha256"]
    )
    with journal.locked():
        if journal.read():
            raise R7Error("R7_BASELINE_ALREADY_EXISTS")
        state = (
            observer(_status_path(source["binding"]), source)
            if observer
            else read_status(_status_path(source["binding"]), source=source)
        )
        if state not in ({"running_fresh"} if successor else _QUIET_STATES):
            raise R7Error("R7_QUIET_BASELINE_REQUIRED")
        if successor and not binding_path.exists():
            _write_new(binding_path, binding_bytes, continuation, delivery)
        journal._append(
            {
                "schema_version": 1,
                "seq": 0,
                "kind": "baseline",
                "state": state,
                "binding_sha256": source["binding_sha256"],
            }
        )
    return {"status": "R7_BASELINE_CREATED", "state": state, "trading_authority": False}


def _monitor_sender(
    source: dict[str, Any], root: Path
) -> Callable[[dict[str, Any]], bool]:
    helpers, continuation, delivery = (
        source["helpers"],
        source["continuation"],
        source["delivery"],
    )
    try:
        transport = helpers._prepare_transport(continuation, delivery)
    except Exception:  # noqa: BLE001 - fail before reserving a send attempt.
        raise R7Error("R7_SENDER_PREFLIGHT_FAILED_NO_SEND") from None

    def send(alert: dict[str, Any]) -> bool:
        try:
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
                raise R7Error("R7_SEND_OUTCOME_UNKNOWN")
            receipt = {
                "schema_version": 1,
                "kind": "kairos.r7.runtime-alert-receipt.v1",
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
                root / f"r7-telegram-{alert['event_id']}.json",
                json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode(),
                continuation,
                delivery,
            )
            return True
        except R7Error:
            raise
        except Exception:  # noqa: BLE001 - all send ambiguity is terminal.
            raise R7Error("R7_SEND_OUTCOME_UNKNOWN") from None

    return send


def poll_once(
    *,
    source_admitter: Callable[[], dict[str, Any]] = admit_r7,
    observer: Callable[[Path, dict[str, Any]], str] | None = None,
    sender: Callable[[dict[str, Any]], bool] | None = None,
    root: Path | None = None,
    journal_factory: Callable[..., Any] = R7Journal,
) -> dict[str, Any]:
    source = source_admitter()
    helpers, continuation, delivery = (
        source["helpers"],
        source["continuation"],
        source["delivery"],
    )
    root = _profile_root(source, root)
    delivery._no_reparse(root)
    delivery._private_acl(root)
    journal = journal_factory(
        root / "events.jsonl", continuation, delivery, helpers, source["binding_sha256"]
    )
    with journal.locked():
        rows = journal.read()
        if not rows or rows[0].get("binding_sha256") != source["binding_sha256"]:
            raise R7Error("R7_BASELINE_REQUIRED_OR_BINDING_CHANGED")
        observed_state = (
            observer(_status_path(source["binding"]), source)
            if observer
            else read_status(_status_path(source["binding"]), source=source)
        )
        current = rows[0]["state"]
        active = False
        for row in rows[1:]:
            if row["kind"] == "observe":
                current = row["state"]
            elif row["kind"] == "send_outcome":
                active = row["transition"] == "firing"
        transition = None
        if (
            observed_state in _ALERT_STATES
            and not active
            and current not in _ALERT_STATES
        ):
            transition = "firing"
        elif observed_state == "running_fresh" and active:
            transition = "resolved"
        if transition and sender is None:
            sender = _monitor_sender(source, root)
        if observed_state != current:
            journal._append(
                {
                    "schema_version": 1,
                    "seq": len(rows),
                    "kind": "observe",
                    "state": observed_state,
                }
            )
            rows = journal.read()
        if transition is None:
            return {
                "status": "quiet_or_unchanged",
                "state": observed_state,
                "send_attempts": 0,
            }
        event_id = hashlib.sha256(
            f"{source['binding_sha256']}|{len(rows)}|{transition}|{observed_state}".encode()
        ).hexdigest()
        event = {
            "event_id": event_id,
            "transition": transition,
            "state": observed_state,
            "text": (
                f"Kairos R7 technical status: {observed_state}. "
                "Non-trading shadow runtime; technical monitoring only."
            ),
        }
        journal._append(
            {
                "schema_version": 1,
                "seq": len(rows),
                "kind": "send_reserved",
                "event_id": event_id,
                "transition": transition,
                "state": observed_state,
            }
        )
        try:
            accepted = bool(sender(event)) if sender else False
        except Exception:  # noqa: BLE001 - an uncertain send is never replayed.
            accepted = False
        journal._append(
            {
                "schema_version": 1,
                "seq": len(journal.read(allow_pending=True)),
                "kind": "send_outcome",
                "event_id": event_id,
                "transition": transition,
                "state": observed_state,
                "result": "accepted" if accepted else "unknown",
            }
        )
        if not accepted:
            raise R7Error("R7_SEND_OUTCOME_UNKNOWN")
        return {"status": "alert_accepted", "state": observed_state, "send_attempts": 1}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--initialize", action="store_true")
    actions.add_argument("--poll-once", action="store_true")
    parser.add_argument("--armed", action="store_true")
    parser.add_argument(
        "--profile", choices=("legacy", "r7-dns", "r7-sql"), default="legacy"
    )
    args = parser.parse_args(argv)
    if not (args.initialize or args.poll_once) or not args.armed:
        print(
            json.dumps(
                {
                    "status": "PLAN_ONLY",
                    "task": {
                        "legacy": TASK_NAME,
                        "r7-dns": _R7DNS["task_name"],
                        "r7-sql": _R7SQL["task_name"],
                    }[args.profile],
                    "profile": args.profile,
                    "business_signals_muted": True,
                    "trading_authority": False,
                }
            )
        )
        return 0
    try:
        source_admitter = lambda: admit_r7(profile=args.profile)
        result = (
            initialize(source_admitter=source_admitter)
            if args.initialize
            else poll_once(source_admitter=source_admitter)
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except R7Error as error:
        print(json.dumps({"status": "FAILED_CLOSED", "category": error.category}))
        return 2
    except Exception:  # noqa: BLE001 - never surface helper/filesystem tracebacks.
        print(
            json.dumps({"status": "FAILED_CLOSED", "category": "R7_UNEXPECTED_FAILURE"})
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
