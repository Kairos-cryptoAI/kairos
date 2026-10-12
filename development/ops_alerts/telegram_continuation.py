"""One-shot, read-only continuation after a proven pre-HTTP ACL failure.

This module never sends Telegram messages. It is deliberately separate from
the prior handoff and diagnostic; all prior evidence remains immutable.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEPLOY = Path("D:/Kairos/kairos-deploy")
KAIROS_ROOT = Path("D:/Kairos/kairos")
NEW_ROOT = Path("D:/Kairos/runtime/alert-delivery-20261012")
OLD_ROOT = Path("D:/Kairos/runtime/alert-delivery")
HANDOFF = NEW_ROOT / "receipts/handoff.json"
HANDOFF_SHA256 = "7d02015d35c65a00d062a996fda73e2c4197a5e4858e72bb895c152048a56eef"
PARENT_META_ID = "6bb7e8d5f20c2f22bae223f02f7d2c0b76dce7c0"
RESERVE = (
    NEW_ROOT
    / "receipts/telegram-readonly-diagnostic-7c4ab990589b0a68f90c87f82bff6aa7a6807a01bff5bfab1dfa07946f58eee7.json"
)
RESERVE_SHA256 = "5fda77a4b050b8796e9d1f6cc55c96925d4795e4c9946a33d5987b2c8aa4bab9"
RESERVE_BYTES = 60
OLD_DIAGNOSTIC_SHA256 = (
    "a2ff0a659ca3e2b16498282756b05d1ae6a323753bb1f943ca507458a032dc06"
)
OLD_DIAGNOSTIC_PATH = (
    OLD_ROOT
    / "receipts/telegram-readonly-diagnostic-7c4ab990589b0a68f90c87f82bff6aa7a6807a01bff5bfab1dfa07946f58eee7.result.json"
)
OLD_QUALIFICATION = (
    OLD_ROOT
    / "receipts/telegram-qualification-7a3845200b24af637213739b21f914b81bb13f0282bb5c751fb106732a52abe5.jsonl"
)
OLD_QUALIFICATION_SHA256 = (
    "b6c6a066e86915aa28bca3ff036ed5ec0b58d75b7dd176ccf11d3600674c4d4d"
)
HANDOFF_SOURCE_SHA256 = (
    "81d11f1b754ee245527a1b72e3f8b3bf828c816fefa650f76f4724a26bd48d5d"
)
DELIVERY_SOURCE_SHA256 = (
    "fa9d58a7c1d7967c5aacf107accfbc72ff61fe5c71e4348a9c75dcf44e976ce5"
)
DIAGNOSTIC_SOURCE_SHA256 = (
    "12c4a6ea0e11d7d48e3c538ead76b5237ad8c491e04a87a5094d26fe5ff6c5ee"
)
EXPECTED_DEPLOY = "0427f7cf1e1cd70f2ddd05b80b4d7d6219736412"
EXPECTED_SIGNER = "40AF365C6682B73D056A6A274DBFF6B65BE9F827"
EXPECTED_BOT_PREFIX = "8898378227:"
EXPECTED_BOT_ID = 8898378227
GUARD = (
    NEW_ROOT
    / "receipts/telegram-readonly-continuation-6bb7e8d5f20c2f22bae223f02f7d2c0b76dce7c0.guard"
)
RESULT = (
    NEW_ROOT
    / "receipts/telegram-readonly-continuation-6bb7e8d5f20c2f22bae223f02f7d2c0b76dce7c0.result.json"
)

_TOKEN = re.compile(r"[0-9]{5,20}:[A-Za-z0-9_-]{30,100}\Z")
_SAFE_ERRORS = {
    "ACL_VERIFICATION_FAILED",
    "API_REJECTED",
    "AUTHENTICATION_REJECTED",
    "BOT_IDENTITY_MISMATCH",
    "BOT_NOT_MEMBER",
    "CHAT_IDENTITY_MISMATCH",
    "CHAT_NOT_FOUND",
    "DEDICATED_TOKEN_FILE_REQUIRED",
    "EXPLICIT_READ_ONLY_AUTHORIZATION_REQUIRED",
    "INVALID_RESPONSE",
    "INVALID_TOKEN_FILE",
    "LOCAL_FAILURE",
    "LOCAL_VALIDATION_FAILED",
    "PERMISSION_DENIED",
    "PROTECTED_ACL_REQUIRED",
    "RATE_LIMIT",
    "READ_ONLY_METHOD_REJECTED",
    "REDIRECT_REJECTED",
    "RESPONSE_TOO_LARGE",
    "TLS",
    "TRANSPORT",
}


def _decode_token(raw: bytes) -> str:
    """Accept one exact token, with the optional terminator used by importers."""
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        raise ContinuationError("INVALID_TOKEN_FILE") from None
    if text.endswith("\r\n"):
        text = text[:-2]
    elif text.endswith("\n"):
        text = text[:-1]
    if _TOKEN.fullmatch(text) is None:
        raise ContinuationError("INVALID_TOKEN_FILE")
    return text


class ContinuationError(Exception):
    """An allowlisted public category; never contains secret or raw details."""

    def __init__(self, category: str) -> None:
        self.category = (
            category if category in _SAFE_ERRORS else "LOCAL_VALIDATION_FAILED"
        )
        super().__init__(self.category)


def _digest(path: Path, *, maximum: int) -> tuple[bytes, str]:
    if not path.is_file() or path.stat().st_size > maximum:
        raise ContinuationError("LOCAL_VALIDATION_FAILED")
    content = path.read_bytes()
    return content, hashlib.sha256(content).hexdigest()


def _check_path(path: Path, no_reparse: Callable[[Path], None]) -> None:
    try:
        no_reparse(path)
    except Exception:  # noqa: BLE001 - fail closed without exposing path errors.
        raise ContinuationError("LOCAL_VALIDATION_FAILED") from None


def _exclusive_fsync(path: Path, payload: bytes) -> None:
    """Create once and retain even a partial guard after any failure."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    if os.name != "nt":
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def _set_exact_file_acl(path: Path) -> None:
    """Apply and verify exactly user, SYSTEM and Administrators on one file."""
    if os.name != "nt":
        if path.stat().st_mode & 0o077:
            raise ContinuationError("PROTECTED_ACL_REQUIRED")
        return
    try:
        target = Path(path)
        if not target.is_absolute() or target.anchor.startswith("\\\\"):
            raise ContinuationError("PROTECTED_ACL_REQUIRED")
        kernel = _kernel32()
        if kernel.GetDriveTypeW(target.drive + "\\") == 4:
            raise ContinuationError("PROTECTED_ACL_REQUIRED")
        for component in (target, *target.parents):
            attributes = kernel.GetFileAttributesW(str(component))
            if attributes == 0xFFFFFFFF or attributes & 0x400:
                raise ContinuationError("PROTECTED_ACL_REQUIRED")
        if not stat.S_ISREG(target.stat().st_mode):
            raise ContinuationError("PROTECTED_ACL_REQUIRED")
        advapi = _advapi32()
        user_sid = _current_user_sid(advapi, kernel)
        sddl = f"D:P(A;;FA;;;{user_sid})(A;;FA;;;SY)(A;;FA;;;BA)"
        descriptor = wintypes.LPVOID()
        descriptor_size = wintypes.DWORD()
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), ctypes.byref(descriptor_size)
        ):
            raise ContinuationError("ACL_VERIFICATION_FAILED")
        try:
            dacl_present = wintypes.BOOL()
            dacl_defaulted = wintypes.BOOL()
            dacl = wintypes.LPVOID()
            if (
                not advapi.GetSecurityDescriptorDacl(
                    descriptor,
                    ctypes.byref(dacl_present),
                    ctypes.byref(dacl),
                    ctypes.byref(dacl_defaulted),
                )
                or not dacl_present.value
                or not dacl
            ):
                raise ContinuationError("ACL_VERIFICATION_FAILED")
            status = advapi.SetNamedSecurityInfoW(
                str(target), 1, 0x00000004 | 0x80000000, None, None, dacl, None
            )
            if status:
                raise ContinuationError("ACL_VERIFICATION_FAILED")
        finally:
            kernel.LocalFree(descriptor)
        _verify_exact_file_acl(target, user_sid, advapi, kernel)
    except ContinuationError:
        raise
    except Exception:  # noqa: BLE001 - native API failures are intentionally opaque.
        raise ContinuationError("ACL_VERIFICATION_FAILED") from None


def _kernel32():
    kernel = ctypes.WinDLL(r"C:\Windows\System32\kernel32.dll", use_last_error=True)
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel.LocalFree.restype = wintypes.HLOCAL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
    kernel.GetFileAttributesW.restype = wintypes.DWORD
    kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    kernel.GetDriveTypeW.restype = wintypes.UINT
    return kernel


def _advapi32():
    advapi = ctypes.WinDLL(r"C:\Windows\System32\advapi32.dll", use_last_error=True)
    advapi.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi.GetSecurityDescriptorDacl.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.BOOL),
    ]
    advapi.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    advapi.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    advapi.SetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
    ]
    advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi.GetSecurityDescriptorControl.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.WORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi.GetAclInformation.argtypes = [
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.c_int,
    ]
    advapi.GetAclInformation.restype = wintypes.BOOL
    advapi.GetAce.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    advapi.GetAce.restype = wintypes.BOOL
    return advapi


def _current_user_sid(advapi, kernel) -> str:
    token = wintypes.HANDLE()
    current_process = kernel.GetCurrentProcess()
    if not advapi.OpenProcessToken(current_process, 0x0008, ctypes.byref(token)):
        raise ContinuationError("ACL_VERIFICATION_FAILED")
    sid_string = wintypes.LPWSTR()
    try:
        needed = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
        if not 8 <= needed.value <= 1024 * 1024:
            raise ContinuationError("ACL_VERIFICATION_FAILED")
        buffer = ctypes.create_string_buffer(needed.value)
        if not advapi.GetTokenInformation(
            token, 1, buffer, needed.value, ctypes.byref(needed)
        ):
            raise ContinuationError("ACL_VERIFICATION_FAILED")
        sid_address = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        if not sid_address or not advapi.ConvertSidToStringSidW(
            sid_address, ctypes.byref(sid_string)
        ):
            raise ContinuationError("ACL_VERIFICATION_FAILED")
        sid = sid_string.value
        if not sid or not re.fullmatch(r"S-1-(?:[0-9]+-)*[0-9]+", sid):
            raise ContinuationError("ACL_VERIFICATION_FAILED")
        return sid
    finally:
        if sid_string:
            kernel.LocalFree(ctypes.cast(sid_string, wintypes.HLOCAL))
        kernel.CloseHandle(token)


def _verify_exact_file_acl(path: Path, user_sid: str, advapi, kernel) -> None:
    owner = wintypes.LPVOID()
    group = wintypes.LPVOID()
    dacl = wintypes.LPVOID()
    sacl = wintypes.LPVOID()
    descriptor = wintypes.LPVOID()
    status = advapi.GetNamedSecurityInfoW(
        str(path),
        1,
        0x00000004,
        ctypes.byref(owner),
        ctypes.byref(group),
        ctypes.byref(dacl),
        ctypes.byref(sacl),
        ctypes.byref(descriptor),
    )
    if status or not descriptor:
        raise ContinuationError("ACL_VERIFICATION_FAILED")
    try:
        control = wintypes.WORD()
        revision = wintypes.DWORD()
        if (
            not advapi.GetSecurityDescriptorControl(
                descriptor, ctypes.byref(control), ctypes.byref(revision)
            )
            or not control.value & 0x1000
        ):
            raise ContinuationError("PROTECTED_ACL_REQUIRED")
        present = wintypes.BOOL()
        defaulted = wintypes.BOOL()
        read_dacl = wintypes.LPVOID()
        if (
            not advapi.GetSecurityDescriptorDacl(
                descriptor,
                ctypes.byref(present),
                ctypes.byref(read_dacl),
                ctypes.byref(defaulted),
            )
            or not present.value
            or not read_dacl
        ):
            raise ContinuationError("PROTECTED_ACL_REQUIRED")

        class ACL_SIZE_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("AceCount", wintypes.DWORD),
                ("AclBytesInUse", wintypes.DWORD),
                ("AclBytesFree", wintypes.DWORD),
            ]

        size_info = ACL_SIZE_INFORMATION()
        if not advapi.GetAclInformation(
            read_dacl, ctypes.byref(size_info), ctypes.sizeof(size_info), 2
        ):
            raise ContinuationError("ACL_VERIFICATION_FAILED")
        expected = {user_sid, "S-1-5-18", "S-1-5-32-544"}
        observed: set[str] = set()
        for index in range(size_info.AceCount):
            ace = wintypes.LPVOID()
            if not advapi.GetAce(read_dacl, index, ctypes.byref(ace)) or not ace:
                raise ContinuationError("ACL_VERIFICATION_FAILED")
            header = ctypes.cast(ace, ctypes.POINTER(ctypes.c_ubyte * 4)).contents
            if header[0] != 0 or header[1] != 0:
                raise ContinuationError("PROTECTED_ACL_REQUIRED")
            mask = ctypes.cast(
                ctypes.c_void_p(ace.value + 4), ctypes.POINTER(wintypes.DWORD)
            ).contents.value
            sid_ptr = ctypes.c_void_p(ace.value + 8)
            sid_text = wintypes.LPWSTR()
            if mask != 0x001F01FF or not advapi.ConvertSidToStringSidW(
                sid_ptr, ctypes.byref(sid_text)
            ):
                raise ContinuationError("PROTECTED_ACL_REQUIRED")
            try:
                sid_value = sid_text.value
            finally:
                kernel.LocalFree(ctypes.cast(sid_text, wintypes.HLOCAL))
            if sid_value not in expected or sid_value in observed:
                raise ContinuationError("PROTECTED_ACL_REQUIRED")
            observed.add(sid_value)
        if observed != expected:
            raise ContinuationError("PROTECTED_ACL_REQUIRED")
    finally:
        kernel.LocalFree(descriptor)


def _load_signed_sources():
    """Return trusted, signed-deploy helpers; never run from an unpinned tree."""
    if str(DEPLOY) not in sys.path:
        sys.path.insert(0, str(DEPLOY))
    if str(KAIROS_ROOT) not in sys.path:
        sys.path.insert(0, str(KAIROS_ROOT))
    from development.ops_alerts import telegram_handoff
    from scripts import alert_delivery, telegram_readonly_diagnostic

    _verify_parent_meta()
    expected_handoff_source = KAIROS_ROOT / "development/ops_alerts/telegram_handoff.py"
    alert_delivery._no_reparse(expected_handoff_source)
    for module, name, digest in (
        (alert_delivery, "alert_delivery.py", DELIVERY_SOURCE_SHA256),
        (
            telegram_readonly_diagnostic,
            "telegram_readonly_diagnostic.py",
            DIAGNOSTIC_SOURCE_SHA256,
        ),
    ):
        expected_source = DEPLOY / "scripts" / name
        actual_source = Path(module.__file__).resolve(strict=True)
        alert_delivery._no_reparse(expected_source)
        if (
            actual_source != expected_source.resolve(strict=True)
            or expected_source.stat().st_size > 256 * 1024
            or hashlib.sha256(expected_source.read_bytes()).hexdigest() != digest
        ):
            raise ContinuationError("LOCAL_VALIDATION_FAILED")
    if (
        Path(telegram_handoff.__file__).resolve(strict=True)
        != expected_handoff_source.resolve(strict=True)
        or telegram_handoff.DEPLOY_SHA != EXPECTED_DEPLOY
        or telegram_handoff.SIGNER != EXPECTED_SIGNER
        or hashlib.sha256(Path(telegram_handoff.__file__).read_bytes()).hexdigest()
        != HANDOFF_SOURCE_SHA256
    ):
        raise ContinuationError("LOCAL_VALIDATION_FAILED")
    telegram_handoff.verify_deploy()
    return alert_delivery, telegram_readonly_diagnostic, telegram_handoff


def _verify_parent_meta() -> None:
    """Verify the signed parent commit without requiring it to be HEAD."""
    git = Path("C:/Program Files/Git/cmd/git.exe")
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
    blob_path = f"{PARENT_META_ID}:development/ops_alerts/telegram_handoff.py"
    try:
        commit = subprocess.run(
            [
                str(git),
                "-C",
                str(KAIROS_ROOT),
                "show",
                "-s",
                "--format=%H %G? %GF",
                PARENT_META_ID,
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
        ancestor = subprocess.run(
            [
                str(git),
                "-C",
                str(KAIROS_ROOT),
                "merge-base",
                "--is-ancestor",
                PARENT_META_ID,
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
        size = subprocess.run(
            [str(git), "-C", str(KAIROS_ROOT), "cat-file", "-s", blob_path],
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
            or int(size.stdout.strip()) > 32768
        ):
            raise ContinuationError("LOCAL_VALIDATION_FAILED")
        source = subprocess.run(
            [str(git), "-C", str(KAIROS_ROOT), "show", blob_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
            env=environment,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise ContinuationError("LOCAL_VALIDATION_FAILED") from None
    if (
        commit.returncode
        or commit.stdout.strip() != f"{PARENT_META_ID} G {EXPECTED_SIGNER}"
        or ancestor.returncode
        or source.returncode
        or hashlib.sha256(source.stdout).hexdigest() != HANDOFF_SOURCE_SHA256
    ):
        raise ContinuationError("LOCAL_VALIDATION_FAILED")


def _validate_handoff(
    handoff_bytes: bytes,
    token: str,
    old_token: str,
    handoff_module: Any,
) -> None:
    try:
        handoff = json.loads(handoff_bytes)
    except (ValueError, UnicodeError):
        raise ContinuationError("LOCAL_VALIDATION_FAILED") from None
    expected_keys = {
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
    if (
        not isinstance(handoff, dict)
        or set(handoff) != expected_keys
        or handoff.get("kind") != "REVIEWED_CURRENT_TOKEN_NO_SEND_HANDOFF"
        or handoff.get("deploy_revision") != EXPECTED_DEPLOY
        or handoff.get("implementation_sha256") != HANDOFF_SOURCE_SHA256
        or handoff.get("old_diagnostic_sha256") != OLD_DIAGNOSTIC_SHA256
        or handoff.get("old_qualification_sha256") != OLD_QUALIFICATION_SHA256
        or handoff.get("current_token_differs_from_previous") is not True
        or handoff.get("current_token_sha256")
        != hashlib.sha256(token.encode()).hexdigest()
        or handoff.get("automatic_retry") is not False
        or handoff.get("trading_authority") is not False
        or token == old_token
        or not token.startswith(handoff_module.BOT_PREFIX)
        or not token.startswith(EXPECTED_BOT_PREFIX)
        or not old_token.startswith(EXPECTED_BOT_PREFIX)
    ):
        raise ContinuationError("LOCAL_VALIDATION_FAILED")


def _continue_once(
    *,
    authorize: bool,
    root: Path,
    old_root: Path,
    handoff_path: Path,
    reserve_path: Path,
    guard_path: Path,
    result_path: Path,
    expected_handoff_sha256: str,
    expected_reserve_sha256: str,
    expected_reserve_bytes: int,
    old_diagnostic_path: Path,
    expected_old_diagnostic_sha256: str,
    old_qualification_path: Path,
    expected_old_qualification_sha256: str,
    key_source_path: Path,
    no_reparse: Callable[[Path], None],
    private_acl: Callable[[Path], None],
    set_file_acl: Callable[[Path], None],
    exclusive_fsync: Callable[[Path, bytes], None],
    source_loader: Callable[[], tuple[Any, Any, Any]],
) -> dict[str, Any]:
    if authorize is not True:
        raise ContinuationError("EXPLICIT_READ_ONLY_AUTHORIZATION_REQUIRED")
    delivery, diagnostic, handoff_module = source_loader()
    token_path = root / "secrets/telegram_bot_token"
    old_token_path = old_root / "secrets/telegram_bot_token"
    old_result_path = reserve_path.with_suffix(".result.json")
    for path in (
        root,
        root / "secrets",
        root / "receipts",
        token_path,
        key_source_path,
        old_root,
        old_root / "receipts",
        old_token_path,
        old_diagnostic_path,
        old_qualification_path,
        handoff_path,
        reserve_path,
        old_result_path,
        guard_path,
        result_path,
    ):
        _check_path(path, no_reparse)
    for path in (
        root,
        root / "secrets",
        root / "receipts",
        token_path,
        handoff_path,
        reserve_path,
        old_root,
        old_root / "receipts",
        old_token_path,
        old_diagnostic_path,
        old_qualification_path,
    ):
        try:
            private_acl(path)
        except Exception:  # noqa: BLE001 - ACL failures must never reach transport.
            raise ContinuationError("PROTECTED_ACL_REQUIRED") from None

    handoff_bytes, handoff_sha = _digest(handoff_path, maximum=4096)
    if handoff_sha != expected_handoff_sha256:
        raise ContinuationError("LOCAL_VALIDATION_FAILED")
    reserve_bytes, reserve_sha = _digest(reserve_path, maximum=expected_reserve_bytes)
    if (
        len(reserve_bytes) != expected_reserve_bytes
        or reserve_sha != expected_reserve_sha256
    ):
        raise ContinuationError("LOCAL_VALIDATION_FAILED")
    _, old_diagnostic_sha = _digest(old_diagnostic_path, maximum=128 * 1024)
    _, old_qualification_sha = _digest(old_qualification_path, maximum=128 * 1024)
    if (
        old_diagnostic_sha != expected_old_diagnostic_sha256
        or old_qualification_sha != expected_old_qualification_sha256
    ):
        raise ContinuationError("LOCAL_VALIDATION_FAILED")
    if old_result_path.exists() or guard_path.exists() or result_path.exists():
        raise ContinuationError("LOCAL_VALIDATION_FAILED")
    try:
        if any(
            item.name.startswith("telegram-readonly-continuation-")
            for item in (root / "receipts").iterdir()
        ):
            raise ContinuationError("LOCAL_VALIDATION_FAILED")
    except OSError:
        raise ContinuationError("LOCAL_VALIDATION_FAILED") from None

    current_raw, _ = _digest(token_path, maximum=256)
    previous_raw, _ = _digest(old_token_path, maximum=256)
    _check_path(key_source_path, no_reparse)
    if key_source_path.resolve(strict=True) != handoff_module.KEY_SOURCE.resolve(
        strict=True
    ):
        raise ContinuationError("LOCAL_VALIDATION_FAILED")
    if not key_source_path.is_file() or key_source_path.stat().st_size > 32768:
        raise ContinuationError("LOCAL_VALIDATION_FAILED")
    token = _decode_token(current_raw)
    old_token = _decode_token(previous_raw)
    _validate_handoff(handoff_bytes, token, old_token, handoff_module)
    try:
        if key_source_path.stat().st_size > 32768:
            raise ContinuationError("LOCAL_VALIDATION_FAILED")
        key_source_text = key_source_path.read_text(encoding="utf-8")
        selected_key = handoff_module.choose_current_token(key_source_text, old_token)
    except Exception:  # noqa: BLE001 - never expose owner key-source contents.
        raise ContinuationError("LOCAL_VALIDATION_FAILED") from None
    if selected_key != token:
        raise ContinuationError("LOCAL_VALIDATION_FAILED")

    guard_payload = (
        json.dumps(
            {
                "kind": "KAIROS_TELEGRAM_READONLY_CONTINUATION_GUARD_V1",
                "parent_meta_id": PARENT_META_ID,
                "handoff_sha256": handoff_sha,
                "reserve_sha256": reserve_sha,
                "automatic_retry": False,
                "send_attempts": 0,
                "trading_authority": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    try:
        exclusive_fsync(guard_path, guard_payload)
        set_file_acl(guard_path)
        private_acl(guard_path)
    except Exception as error:  # noqa: BLE001 - retain only an allowlisted category.
        category = getattr(error, "category", "LOCAL_VALIDATION_FAILED")
        raise ContinuationError(category) from None

    report: dict[str, Any] = {
        "schema_version": 1,
        "kind": "kairos.telegram.readonly-continuation.v1",
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "implementation_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "status": "BLOCKED",
        "error_category": None,
        "http_method_counts": {"getMe": 0, "getChat": 0},
        "send_attempts": 0,
        "chat_identity_verified": False,
        "delivery_qualified": False,
        "trading_authority": False,
        "automatic_retry": False,
        "parent_meta_id": PARENT_META_ID,
        "handoff_sha256": handoff_sha,
        "reserve_sha256": reserve_sha,
        "guard_sha256": hashlib.sha256(guard_payload).hexdigest(),
        "expected_bot_username": delivery.EXPECTED_BOT,
        "expected_test_chat_id": delivery.EXPECTED_TEST_CHAT,
    }
    try:
        transport = diagnostic.ReadOnlyTransport(token)
        report["http_method_counts"]["getMe"] = 1
        identity = transport.call("getMe", {})
        _copy_numeric_api_metadata(report, identity)
        if not isinstance(identity, dict) or identity.get("ok") is not True:
            report["error_category"] = _transport_category(identity)
        elif (
            not isinstance(identity.get("result"), dict)
            or type(identity["result"].get("id")) is not int
            or identity["result"].get("id") != EXPECTED_BOT_ID
            or identity["result"].get("is_bot") is not True
            or identity["result"].get("username") != delivery.EXPECTED_BOT
        ):
            report["error_category"] = "BOT_IDENTITY_MISMATCH"
        else:
            report["http_method_counts"]["getChat"] = 1
            chat = transport.call("getChat", {"chat_id": delivery.EXPECTED_TEST_CHAT})
            _copy_numeric_api_metadata(report, chat)
            if not isinstance(chat, dict) or chat.get("ok") is not True:
                report["error_category"] = _transport_category(chat)
            elif (
                not isinstance(chat.get("result"), dict)
                or type(chat["result"].get("id")) is not int
                or chat["result"].get("id") != delivery.EXPECTED_TEST_CHAT
                or chat["result"].get("type") not in {"group", "supergroup"}
            ):
                report["error_category"] = "CHAT_IDENTITY_MISMATCH"
            else:
                report["status"] = "PASS_READ_ONLY_IDENTITY_ONLY"
                report["chat_identity_verified"] = True
                report["http_status"] = 200
    except Exception:  # noqa: BLE001 - never expose transport exception text.
        report["error_category"] = "LOCAL_FAILURE"
    if report["error_category"] is not None:
        report["error_category"] = _safe_category(report["error_category"])

    result_bytes = (
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )
    try:
        exclusive_fsync(result_path, result_bytes)
        set_file_acl(result_path)
        private_acl(result_path)
    except Exception:  # noqa: BLE001 - permanent guard prevents any retry.
        # The permanent guard remains. Never retry or overwrite a partial result.
        raise ContinuationError("LOCAL_VALIDATION_FAILED") from None
    return report


def _safe_category(category: Any) -> str:
    return (
        category
        if isinstance(category, str) and category in _SAFE_ERRORS
        else "LOCAL_FAILURE"
    )


def _copy_numeric_api_metadata(report: dict[str, Any], response: Any) -> None:
    if not isinstance(response, dict):
        return
    for name in ("http_status", "api_error_code"):
        value = response.get(name)
        if type(value) is int and 100 <= value <= 599:
            report[name] = value


def _transport_category(value: Any) -> str:
    return (
        _safe_category(value.get("error_category"))
        if isinstance(value, dict)
        else "LOCAL_FAILURE"
    )


def continue_read_only(*, authorize: bool) -> dict[str, Any]:
    """Run the one fixed production continuation; no caller paths are accepted."""
    if authorize is not True:
        raise ContinuationError("EXPLICIT_READ_ONLY_AUTHORIZATION_REQUIRED")
    sources = _load_signed_sources()
    delivery = sources[0]
    return _continue_once(
        authorize=authorize,
        root=NEW_ROOT,
        old_root=OLD_ROOT,
        handoff_path=HANDOFF,
        reserve_path=RESERVE,
        guard_path=GUARD,
        result_path=RESULT,
        expected_handoff_sha256=HANDOFF_SHA256,
        expected_reserve_sha256=RESERVE_SHA256,
        expected_reserve_bytes=RESERVE_BYTES,
        old_diagnostic_path=OLD_DIAGNOSTIC_PATH,
        expected_old_diagnostic_sha256=OLD_DIAGNOSTIC_SHA256,
        old_qualification_path=OLD_QUALIFICATION,
        expected_old_qualification_sha256=OLD_QUALIFICATION_SHA256,
        key_source_path=Path("C:/Users/loval/Documents/keys.txt"),
        no_reparse=delivery._no_reparse,
        private_acl=delivery._private_acl,
        set_file_acl=_set_exact_file_acl,
        exclusive_fsync=_exclusive_fsync,
        source_loader=lambda: sources,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-reviewed-pre-api-continuation", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute_reviewed_pre_api_continuation:
        print(json.dumps({"status": "PLAN_ONLY", "http_calls": 0, "send_attempts": 0}))
        return 0
    try:
        report = continue_read_only(authorize=True)
    except Exception as error:  # noqa: BLE001 - output only a fixed safe category.
        category = _safe_category(getattr(error, "category", None))
        report = {
            "status": "BLOCKED",
            "error_category": category,
            "send_attempts": 0,
            "automatic_retry": False,
            "trading_authority": False,
        }
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("chat_identity_verified") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
