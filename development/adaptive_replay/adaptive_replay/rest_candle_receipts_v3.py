"""Create-only storage for prospective raw REST candle response receipts.

This module deliberately performs no HTTP, JSON parsing of response bodies,
source authentication, historical reconstruction, or candle-finality claim.
It records caller-supplied request/receive clocks and exact response bytes so a
later producer can audit what it actually observed and when those bytes were
durably written.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ENDPOINT = "https://fapi.binance.com/fapi/v1/klines"
UNIVERSE = ("BNBUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
MAX_ATTEMPTS = 512
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BODY_BYTES = 128 * 1024 * 1024
MAX_METADATA_BYTES = 16 * 1024
SCHEMA = "kairos.development.rest-candle-receipts.v3"

_ATTEMPT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,95}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FAILURE_KINDS = frozenset({"CANCELLED", "CONNECTION_ERROR", "INTERRUPTED", "TIMEOUT", "UNKNOWN"})
_MANIFEST = {
    "schema": SCHEMA,
    "endpoint": ENDPOINT,
    "universe": list(UNIVERSE),
    "request_contract": {
        "method": "GET",
        "params": {"interval": "1m", "limit": "1..1500", "symbol": "UNIVERSE"},
    },
    "max_attempts": MAX_ATTEMPTS,
    "max_body_bytes": MAX_BODY_BYTES,
    "max_total_body_bytes": MAX_TOTAL_BODY_BYTES,
    "scope": "BOUNDED_FIXTURE_OR_PUBLIC_SAMPLE_ONLY_NOT_FULL_HORIZON_FEED",
    "clock_semantics": (
        "requested_and_response_received_are_caller_supplied; "
        "persisted_at_ms_is_sampled_after_raw_body_or_no_response_marker_fsync_before_receipt_commit"
    ),
    "limitations": [
        "public-byte-hash-is-not-source-authentication",
        "storage-does-not-prove-exchange-finality",
        "no-response-must-be-explicitly-recorded-by-caller",
        "no-historical-backdating-or-promotion-linkage",
    ],
}


class ReceiptStoreError(ValueError):
    """The requested receipt operation violates the storage contract."""


class ReceiptIntegrityError(ReceiptStoreError):
    """Existing receipt bytes are incomplete, changed, or inconsistent."""


class ReceiptLimitError(ReceiptStoreError):
    """A configured attempt or byte bound would be exceeded."""


@dataclass(frozen=True, slots=True)
class CandleRequestV3:
    """The only request descriptor allowed by this raw-receipt foundation."""

    symbol: str
    limit: int

    def __post_init__(self) -> None:
        if type(self.symbol) is not str or self.symbol not in UNIVERSE:
            raise ReceiptStoreError("normalized symbol must be in the fixed five-symbol universe")
        if type(self.limit) is not int or not 1 <= self.limit <= 1_500:
            raise ReceiptStoreError("request limit must be an integer in [1, 1500]")

    def descriptor(self) -> dict[str, object]:
        return {
            "method": "GET",
            "url": ENDPOINT,
            "params": {"symbol": self.symbol, "interval": "1m", "limit": self.limit},
        }


@dataclass(frozen=True, slots=True)
class ReceiptCheckpoint:
    """Exact caller-owned anchor required before reopening an existing store."""

    attempt_count: int
    head_sha256: str | None

    def __post_init__(self) -> None:
        if type(self.attempt_count) is not int or not 0 <= self.attempt_count <= MAX_ATTEMPTS:
            raise ReceiptStoreError("checkpoint attempt_count is outside the bounded store")
        if self.attempt_count == 0:
            if self.head_sha256 is not None:
                raise ReceiptStoreError("empty checkpoint must have no receipt head")
        elif type(self.head_sha256) is not str or _SHA256.fullmatch(self.head_sha256) is None:
            raise ReceiptStoreError("nonempty checkpoint requires an exact SHA-256 receipt head")


@dataclass(frozen=True, slots=True)
class RestCandleAttemptV3:
    """One stored REST attempt; persisted_at_ms is payload fsync, not ledger commit."""

    attempt_number: int
    attempt_id: str
    request: CandleRequestV3
    state: str
    requested_at_ms: int
    response_received_at_ms: int | None
    # Sampled after the raw body/marker fsync; not receipt commit or SIM availability.
    persisted_at_ms: int
    http_status: int | None
    failure_kind: str | None
    raw_response_file: str | None
    raw_response_bytes: int
    raw_response_sha256: str | None
    previous_receipt_sha256: str | None
    receipt_sha256: str


def _clock_ms(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ReceiptStoreError(f"{name} must be an exact nonnegative integer millisecond clock")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", errors="strict")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReceiptIntegrityError("receipt JSON contains a duplicate object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ReceiptIntegrityError(f"receipt JSON contains unsupported constant {value}")


def _parse_canonical_json(payload: bytes, name: str) -> dict[str, object]:
    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptIntegrityError(f"{name} is not valid UTF-8 JSON") from exc
    if type(value) is not dict or _canonical(value) != payload:
        raise ReceiptIntegrityError(f"{name} is not a canonical JSON object")
    return value


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)


def _reject_reparse_components(path: Path) -> None:
    for component in (*reversed(path.parents), path):
        if _is_reparse_point(component):
            raise ReceiptStoreError("receipt path must not contain linked or reparse-point components")


def _reject_nonlocal_path(path: Path) -> None:
    # A UNC path is a network share even though pathlib considers it absolute.
    if str(path).startswith("\\\\") or path.drive.startswith("\\\\"):
        raise ReceiptStoreError("receipt storage must use a local filesystem path")


def _write_create_only_fsynced(
    path: Path,
    payload: bytes,
    *,
    guard: Callable[[], None] | None = None,
) -> None:
    if type(payload) is not bytes:
        raise ReceiptStoreError("create-only payload must be exact bytes")
    if guard is not None:
        guard()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd: int | None = None
    try:
        fd = os.open(path, flags, 0o600)
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise ReceiptIntegrityError("new receipt file is not a single-link regular file")
        offset = 0
        while offset < len(payload):
            offset += os.write(fd, payload[offset:])
        os.fsync(fd)
        completed = os.fstat(fd)
        visible = path.lstat()
        if (
            _file_identity(opened) != _file_identity(completed)
            or _file_identity(completed) != _file_identity(visible)
            or completed.st_nlink != 1
            or visible.st_nlink != 1
            or not stat.S_ISREG(visible.st_mode)
            or completed.st_size != len(payload)
            or visible.st_size != len(payload)
        ):
            raise ReceiptIntegrityError("create-only receipt file identity or link count changed")
        if guard is not None:
            guard()
    except FileExistsError:
        raise ReceiptIntegrityError("create-only receipt path already exists") from None
    finally:
        if fd is not None:
            os.close(fd)


def _file_identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _read_bounded_regular_file(path: Path, maximum_bytes: int, name: str) -> bytes:
    try:
        before_path = path.lstat()
    except OSError as exc:
        raise ReceiptIntegrityError(f"{name} is missing or unreadable") from exc
    if (
        not stat.S_ISREG(before_path.st_mode)
        or path.is_symlink()
        or bool(getattr(before_path, "st_file_attributes", 0) & 0x400)
        or before_path.st_nlink != 1
        or before_path.st_size < 0
        or before_path.st_size > maximum_bytes
    ):
        raise ReceiptLimitError(f"{name} is linked, non-regular, multiply linked, or exceeds its read bound")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd: int | None = None
    try:
        fd = os.open(path, flags)
        before_fd = os.fstat(fd)
        if (
            not stat.S_ISREG(before_fd.st_mode)
            or before_fd.st_nlink != 1
            or _file_identity(before_fd) != _file_identity(before_path)
            or before_fd.st_size != before_path.st_size
        ):
            raise ReceiptIntegrityError(f"{name} identity changed while being opened")
        payload = bytearray()
        while len(payload) <= maximum_bytes:
            chunk = os.read(fd, min(64 * 1024, maximum_bytes + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        after_fd = os.fstat(fd)
        after_path = path.lstat()
    except OSError as exc:
        raise ReceiptIntegrityError(f"{name} is missing or unreadable") from exc
    finally:
        if fd is not None:
            os.close(fd)
    if (
        len(payload) > maximum_bytes
        or not stat.S_ISREG(after_fd.st_mode)
        or after_fd.st_nlink != 1
        or _file_identity(after_fd) != _file_identity(before_fd)
        or _file_identity(after_path) != _file_identity(after_fd)
        or after_fd.st_size != before_fd.st_size
        or getattr(after_fd, "st_mtime_ns", None) != getattr(before_fd, "st_mtime_ns", None)
        or not stat.S_ISREG(after_path.st_mode)
        or after_path.st_nlink != 1
        or after_path.st_size != before_path.st_size
        or getattr(after_path, "st_mtime_ns", None) != getattr(before_path, "st_mtime_ns", None)
        or len(payload) != after_fd.st_size
    ):
        raise ReceiptIntegrityError(f"{name} grew, changed identity, or changed size while being audited")
    return bytes(payload)


def _bounded_names(directory: Path, maximum_entries: int) -> set[str]:
    names: set[str] = set()
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                names.add(entry.name)
                if len(names) > maximum_entries:
                    raise ReceiptLimitError("receipt directory contains too many entries to audit safely")
    except OSError as exc:
        raise ReceiptIntegrityError("receipt directory cannot be audited") from exc
    return names


def _validate_attempt_id(value: object) -> str:
    if type(value) is not str or _ATTEMPT_ID.fullmatch(value) is None or ".." in value:
        raise ReceiptStoreError("attempt_id must be a unique normalized bounded identifier")
    return value


def _validate_request_descriptor(value: object) -> CandleRequestV3:
    if type(value) is not dict or set(value) != {"method", "url", "params"}:
        raise ReceiptIntegrityError("stored request descriptor has unknown or missing fields")
    params = value["params"]
    if (
        value["method"] != "GET"
        or value["url"] != ENDPOINT
        or type(params) is not dict
        or set(params) != {"symbol", "interval", "limit"}
        or params["interval"] != "1m"
    ):
        raise ReceiptIntegrityError("stored request descriptor is outside the fixed credential-free contract")
    try:
        request = CandleRequestV3(params["symbol"], params["limit"])
    except ReceiptStoreError as exc:
        raise ReceiptIntegrityError("stored request descriptor is invalid") from exc
    if request.descriptor() != value:
        raise ReceiptIntegrityError("stored request descriptor is not canonical")
    return request


class RestCandleReceiptStoreV3:
    """Bounded create-only append ledger for exact REST response bytes.

    A failed HTTP response is stored exactly like any other response. A caller
    that received no HTTP response must use ``record_no_response`` so the
    attempt remains in the denominator. Reopen performs a full audit and
    requires the caller's independently retained exact checkpoint.
    """

    def __init__(self, root: Path, *, wall_ms: Callable[[], int]):
        self.root = root
        self._wall_ms = wall_ms
        self._attempts: list[RestCandleAttemptV3] = []
        self._attempt_ids: set[str] = set()
        self._total_body_bytes = 0
        self._failed = False
        self._lock = threading.RLock()
        self._root_identity: tuple[int, int] | None = None
        self._attempts_identity: tuple[int, int] | None = None
        self._manifest_identity: tuple[int, int] | None = None

    def _pin_directories(self) -> None:
        _reject_reparse_components(self.root)
        attempts_path = self.root / "attempts"
        _reject_reparse_components(attempts_path)
        try:
            root_stat = self.root.lstat()
            attempts_stat = attempts_path.lstat()
        except OSError as exc:
            raise ReceiptIntegrityError("receipt directories are missing or unreadable") from exc
        if not stat.S_ISDIR(root_stat.st_mode) or not stat.S_ISDIR(attempts_stat.st_mode):
            raise ReceiptIntegrityError("receipt root and attempts paths must be ordinary directories")
        self._root_identity = _file_identity(root_stat)
        self._attempts_identity = _file_identity(attempts_stat)

    def _verify_pinned_directories(self) -> None:
        if self._root_identity is None or self._attempts_identity is None:
            raise ReceiptIntegrityError("receipt directory identities were not pinned")
        _reject_nonlocal_path(self.root)
        _reject_reparse_components(self.root)
        attempts_path = self.root / "attempts"
        _reject_reparse_components(attempts_path)
        try:
            root_stat = self.root.lstat()
            attempts_stat = attempts_path.lstat()
        except OSError as exc:
            raise ReceiptIntegrityError("pinned receipt directories changed or disappeared") from exc
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or not stat.S_ISDIR(attempts_stat.st_mode)
            or _file_identity(root_stat) != self._root_identity
            or _file_identity(attempts_stat) != self._attempts_identity
        ):
            raise ReceiptIntegrityError("pinned receipt directory identity changed")

    def _remember_manifest(self, expected_bytes: bytes) -> None:
        _reject_reparse_components(self.root / "manifest.json")
        try:
            metadata = (self.root / "manifest.json").lstat()
        except OSError as exc:
            raise ReceiptIntegrityError("receipt manifest is missing or unreadable") from exc
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ReceiptIntegrityError("receipt manifest must be a single-link regular file")
        self._manifest_identity = _file_identity(metadata)
        manifest_path = self.root / "manifest.json"
        if _read_bounded_regular_file(manifest_path, MAX_METADATA_BYTES, "manifest") != expected_bytes:
            raise ReceiptIntegrityError("receipt manifest changed while being pinned")
        after_read = manifest_path.lstat()
        if _file_identity(after_read) != self._manifest_identity or after_read.st_nlink != 1:
            raise ReceiptIntegrityError("receipt manifest identity changed while being pinned")

    def _verify_pinned_paths(self) -> None:
        self._verify_pinned_directories()
        if self._manifest_identity is None:
            raise ReceiptIntegrityError("receipt manifest authority was not pinned")
        manifest_path = self.root / "manifest.json"
        _reject_reparse_components(manifest_path)
        try:
            metadata = manifest_path.lstat()
        except OSError as exc:
            raise ReceiptIntegrityError("pinned receipt manifest changed or disappeared") from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or _file_identity(metadata) != self._manifest_identity
        ):
            raise ReceiptIntegrityError("pinned receipt manifest identity changed")
        if _read_bounded_regular_file(manifest_path, MAX_METADATA_BYTES, "manifest") != _canonical(_MANIFEST):
            raise ReceiptIntegrityError("pinned receipt manifest content changed")

    def _verify_current_ledger(self) -> None:
        self._verify_pinned_paths()
        audited = type(self).reopen(
            self.root,
            expected_checkpoint=self.checkpoint,
            wall_ms=self._wall_ms,
        )
        if audited.attempts != tuple(self._attempts) or audited._total_body_bytes != self._total_body_bytes:
            raise ReceiptIntegrityError("on-disk ledger differs from the pinned in-memory append head")
        self._verify_pinned_paths()

    @classmethod
    def create(
        cls,
        root: Path,
        *,
        wall_ms: Callable[[], int],
    ) -> RestCandleReceiptStoreV3:
        if not callable(wall_ms):
            raise ReceiptStoreError("an injected wall clock is required")
        output = Path(root).absolute()
        _reject_nonlocal_path(output)
        _reject_reparse_components(output)
        parent = output.parent
        if not parent.is_dir():
            raise ReceiptStoreError("receipt output parent must already exist as a local directory")
        if output.exists():
            raise ReceiptIntegrityError("receipt output directory is create-only and already exists")
        store = cls(output, wall_ms=wall_ms)
        try:
            output.mkdir(exist_ok=False)
            (output / "attempts").mkdir(exist_ok=False)
            store._pin_directories()
            manifest_bytes = _canonical(_MANIFEST)
            _write_create_only_fsynced(
                output / "manifest.json",
                manifest_bytes,
                guard=store._verify_pinned_directories,
            )
            store._remember_manifest(manifest_bytes)
            store._verify_pinned_paths()
        except BaseException:
            # Never remove or repair a partially created research directory.
            store._failed = True
            raise
        return store

    @classmethod
    def reopen(
        cls,
        root: Path,
        *,
        expected_checkpoint: ReceiptCheckpoint,
        wall_ms: Callable[[], int],
    ) -> RestCandleReceiptStoreV3:
        if type(expected_checkpoint) is not ReceiptCheckpoint:
            raise ReceiptStoreError("reopen requires an exact independently retained checkpoint")
        if not callable(wall_ms):
            raise ReceiptStoreError("an injected wall clock is required")
        output = Path(root).absolute()
        _reject_nonlocal_path(output)
        _reject_reparse_components(output)
        if not output.is_dir() or not (output / "attempts").is_dir():
            raise ReceiptIntegrityError("receipt directory is missing or incomplete")
        store = cls(output, wall_ms=wall_ms)
        store._pin_directories()
        _reject_reparse_components(output / "manifest.json")
        _reject_reparse_components(output / "attempts")
        try:
            top_names = _bounded_names(output, 2)
            attempt_dir_names = _bounded_names(output / "attempts", 2 * MAX_ATTEMPTS)
        except OSError as exc:
            raise ReceiptIntegrityError("receipt directory cannot be audited") from exc
        if top_names != {"manifest.json", "attempts"}:
            raise ReceiptIntegrityError("unexpected, missing, or interrupted top-level receipt entry")
        try:
            manifest_bytes = _read_bounded_regular_file(
                output / "manifest.json", MAX_METADATA_BYTES, "manifest"
            )
        except OSError as exc:
            raise ReceiptIntegrityError("receipt manifest cannot be read") from exc
        if _parse_canonical_json(manifest_bytes, "manifest") != _MANIFEST:
            raise ReceiptIntegrityError("receipt manifest differs from the supported exact schema")
        store._remember_manifest(manifest_bytes)
        store._verify_pinned_paths()

        receipt_names = sorted(
            name for name in attempt_dir_names if re.fullmatch(r"[0-9]{8}\.receipt\.json", name)
        )
        if len(receipt_names) > MAX_ATTEMPTS:
            raise ReceiptLimitError("stored attempt count exceeds the explicit bounded limit")
        expected_names: set[str] = set(receipt_names)
        previous_hash: str | None = None
        previous_persisted: int | None = None
        previous_attempt_id: str | None = None
        for index, name in enumerate(receipt_names, 1):
            if name != f"{index:08d}.receipt.json":
                raise ReceiptIntegrityError("attempt receipt sequence has a gap or reordering")
            receipt_path = output / "attempts" / name
            _reject_reparse_components(receipt_path)
            try:
                receipt_bytes = _read_bounded_regular_file(receipt_path, MAX_METADATA_BYTES, name)
            except OSError as exc:
                raise ReceiptIntegrityError("attempt receipt cannot be read") from exc
            record = _parse_canonical_json(receipt_bytes, name)
            receipt = store._decode_record(
                record,
                expected_number=index,
                expected_previous_hash=previous_hash,
                previous_persisted=previous_persisted,
            )
            if receipt.attempt_id in store._attempt_ids:
                raise ReceiptIntegrityError("duplicate attempt_id in receipt ledger")
            if previous_attempt_id == receipt.attempt_id:
                raise ReceiptIntegrityError("adjacent duplicate attempt_id in receipt ledger")
            if receipt.state == "HTTP_RESPONSE":
                assert receipt.raw_response_file is not None
                raw_path = output / "attempts" / receipt.raw_response_file
                _reject_reparse_components(raw_path)
                try:
                    raw = _read_bounded_regular_file(raw_path, MAX_BODY_BYTES, "raw response")
                except OSError as exc:
                    raise ReceiptIntegrityError("retained raw response is missing or unreadable") from exc
                if len(raw) != receipt.raw_response_bytes or _sha256(raw) != receipt.raw_response_sha256:
                    raise ReceiptIntegrityError("retained raw response bytes differ from their receipt")
                expected_names.add(receipt.raw_response_file)
                store._total_body_bytes += len(raw)
            else:
                marker = f"{index:08d}.no-response.marker"
                marker_path = output / "attempts" / marker
                _reject_reparse_components(marker_path)
                try:
                    marker_bytes = _read_bounded_regular_file(marker_path, 64, "no-response marker")
                except OSError as exc:
                    raise ReceiptIntegrityError("explicit no-response marker is missing") from exc
                if marker_bytes != b"NO_HTTP_RESPONSE\n":
                    raise ReceiptIntegrityError("no-response marker bytes differ")
                expected_names.add(marker)
            store._attempts.append(receipt)
            store._attempt_ids.add(receipt.attempt_id)
            previous_hash = receipt.receipt_sha256
            previous_persisted = receipt.persisted_at_ms
            previous_attempt_id = receipt.attempt_id
        if attempt_dir_names != expected_names:
            raise ReceiptIntegrityError(
                "unexpected or interrupted attempt files; no repair or cleanup is allowed"
            )
        if store._total_body_bytes > MAX_TOTAL_BODY_BYTES:
            raise ReceiptLimitError("stored raw responses exceed the explicit total byte limit")
        if store.checkpoint != expected_checkpoint:
            raise ReceiptIntegrityError("caller checkpoint does not exactly match audited receipt head")
        store._verify_pinned_paths()
        return store

    @property
    def attempts(self) -> tuple[RestCandleAttemptV3, ...]:
        with self._lock:
            return tuple(self._attempts)

    @property
    def checkpoint(self) -> ReceiptCheckpoint:
        with self._lock:
            return ReceiptCheckpoint(
                attempt_count=len(self._attempts),
                head_sha256=None if not self._attempts else self._attempts[-1].receipt_sha256,
            )

    def record_response(
        self,
        *,
        attempt_id: str,
        request: CandleRequestV3,
        requested_at_ms: int,
        response_received_at_ms: int,
        http_status: int,
        raw_response: bytes,
    ) -> RestCandleAttemptV3:
        """Retain exact bytes first; this method never decodes/parses the body."""
        attempt_id = _validate_attempt_id(attempt_id)
        if type(request) is not CandleRequestV3:
            raise ReceiptStoreError("exact fixed-contract CandleRequestV3 required")
        CandleRequestV3(request.symbol, request.limit)
        requested = _clock_ms(requested_at_ms, "requested_at_ms")
        received = _clock_ms(response_received_at_ms, "response_received_at_ms")
        if received < requested:
            raise ReceiptStoreError("response receive clock cannot precede request clock")
        if type(http_status) is not int or not 100 <= http_status <= 599:
            raise ReceiptStoreError("HTTP status must be an exact integer in [100, 599]")
        if type(raw_response) is not bytes:
            raise ReceiptStoreError("raw_response must be exact immutable bytes")
        if len(raw_response) > MAX_BODY_BYTES:
            raise ReceiptLimitError("raw response exceeds the 2 MiB per-attempt bound")
        return self._append(
            attempt_id=attempt_id,
            request=request,
            requested_at_ms=requested,
            response_received_at_ms=received,
            http_status=http_status,
            failure_kind=None,
            raw_response=raw_response,
        )

    def record_no_response(
        self,
        *,
        attempt_id: str,
        request: CandleRequestV3,
        requested_at_ms: int,
        failure_kind: str,
    ) -> RestCandleAttemptV3:
        """Explicitly retain an interrupted/failed attempt with no HTTP response."""
        attempt_id = _validate_attempt_id(attempt_id)
        if type(request) is not CandleRequestV3:
            raise ReceiptStoreError("exact fixed-contract CandleRequestV3 required")
        CandleRequestV3(request.symbol, request.limit)
        requested = _clock_ms(requested_at_ms, "requested_at_ms")
        if type(failure_kind) is not str or failure_kind not in _FAILURE_KINDS:
            raise ReceiptStoreError("explicit bounded no-response failure_kind required")
        return self._append(
            attempt_id=attempt_id,
            request=request,
            requested_at_ms=requested,
            response_received_at_ms=None,
            http_status=None,
            failure_kind=failure_kind,
            raw_response=None,
        )

    def _append(
        self,
        *,
        attempt_id: str,
        request: CandleRequestV3,
        requested_at_ms: int,
        response_received_at_ms: int | None,
        http_status: int | None,
        failure_kind: str | None,
        raw_response: bytes | None,
    ) -> RestCandleAttemptV3:
        with self._lock:
            if self._failed:
                raise ReceiptIntegrityError("receipt store is terminal after a partial or failed write")
            if attempt_id in self._attempt_ids:
                raise ReceiptIntegrityError("attempt_id is append-only and already exists")
            if len(self._attempts) >= MAX_ATTEMPTS:
                raise ReceiptLimitError("receipt store reached the 512-attempt bound")
            body_bytes = 0 if raw_response is None else len(raw_response)
            if self._total_body_bytes + body_bytes > MAX_TOTAL_BODY_BYTES:
                raise ReceiptLimitError("receipt store would exceed the 128 MiB total raw-body bound")

            number = len(self._attempts) + 1
            prefix = f"{number:08d}"
            raw_name = f"{prefix}.response.raw" if raw_response is not None else None
            marker_name = f"{prefix}.no-response.marker" if raw_response is None else None
            payload = raw_response if raw_response is not None else b"NO_HTTP_RESPONSE\n"
            payload_path = self.root / "attempts" / (raw_name or marker_name or "")
            try:
                self._verify_current_ledger()
                _write_create_only_fsynced(payload_path, payload, guard=self._verify_pinned_paths)
                # This is the raw body/marker fsync completion clock, not the
                # receipt commit or SIM promotion/availability clock.
                persisted = _clock_ms(self._wall_ms(), "persisted_at_ms")
                if persisted < requested_at_ms:
                    raise ReceiptStoreError("persisted clock cannot precede request clock")
                if response_received_at_ms is not None and persisted < response_received_at_ms:
                    raise ReceiptStoreError("persisted clock cannot precede response receive clock")
                if self._attempts and persisted < self._attempts[-1].persisted_at_ms:
                    raise ReceiptStoreError("persisted clock regressed across append-only attempts")
                raw_sha = None if raw_response is None else _sha256(raw_response)
                unsigned = {
                    "schema": SCHEMA,
                    "attempt_number": number,
                    "attempt_id": attempt_id,
                    "previous_receipt_sha256": self.checkpoint.head_sha256,
                    "request": request.descriptor(),
                    "state": "NO_RESPONSE" if raw_response is None else "HTTP_RESPONSE",
                    "requested_at_ms": requested_at_ms,
                    "response_received_at_ms": response_received_at_ms,
                    "persisted_at_ms": persisted,
                    "http_status": http_status,
                    "failure_kind": failure_kind,
                    "raw_response_file": raw_name,
                    "raw_response_bytes": body_bytes,
                    "raw_response_sha256": raw_sha,
                }
                receipt_sha = _sha256(_canonical(unsigned))
                record = {**unsigned, "receipt_sha256": receipt_sha}
                _write_create_only_fsynced(
                    self.root / "attempts" / f"{prefix}.receipt.json",
                    _canonical(record),
                    guard=self._verify_pinned_paths,
                )
            except BaseException:
                # Keep any orphan/partial bytes for forensic review; never clean up.
                self._failed = True
                raise

            result = RestCandleAttemptV3(
                attempt_number=number,
                attempt_id=attempt_id,
                request=request,
                state="NO_RESPONSE" if raw_response is None else "HTTP_RESPONSE",
                requested_at_ms=requested_at_ms,
                response_received_at_ms=response_received_at_ms,
                persisted_at_ms=persisted,
                http_status=http_status,
                failure_kind=failure_kind,
                raw_response_file=raw_name,
                raw_response_bytes=body_bytes,
                raw_response_sha256=raw_sha,
                previous_receipt_sha256=unsigned["previous_receipt_sha256"],
                receipt_sha256=receipt_sha,
            )
            self._attempts.append(result)
            self._attempt_ids.add(attempt_id)
            self._total_body_bytes += body_bytes
            try:
                self._verify_current_ledger()
            except BaseException:
                self._failed = True
                raise
            return result

    def _decode_record(
        self,
        value: dict[str, object],
        *,
        expected_number: int,
        expected_previous_hash: str | None,
        previous_persisted: int | None,
    ) -> RestCandleAttemptV3:
        expected_keys = {
            "schema",
            "attempt_number",
            "attempt_id",
            "previous_receipt_sha256",
            "request",
            "state",
            "requested_at_ms",
            "response_received_at_ms",
            "persisted_at_ms",
            "http_status",
            "failure_kind",
            "raw_response_file",
            "raw_response_bytes",
            "raw_response_sha256",
            "receipt_sha256",
        }
        if set(value) != expected_keys or value.get("schema") != SCHEMA:
            raise ReceiptIntegrityError("attempt receipt schema or field set is unsupported")
        try:
            attempt_id = _validate_attempt_id(value["attempt_id"])
            request = _validate_request_descriptor(value["request"])
            requested = _clock_ms(value["requested_at_ms"], "requested_at_ms")
            persisted = _clock_ms(value["persisted_at_ms"], "persisted_at_ms")
        except (ReceiptStoreError, KeyError) as exc:
            raise ReceiptIntegrityError(
                "attempt receipt contains invalid identity, request, or clock"
            ) from exc
        if (
            type(value["attempt_number"]) is not int
            or value["attempt_number"] != expected_number
            or value["previous_receipt_sha256"] != expected_previous_hash
            or (previous_persisted is not None and persisted < previous_persisted)
            or persisted < requested
            or type(value["raw_response_bytes"]) is not int
        ):
            raise ReceiptIntegrityError("attempt sequence, chain, or persistence clocks are inconsistent")
        raw_count = value["raw_response_bytes"]
        if not 0 <= raw_count <= MAX_BODY_BYTES:
            raise ReceiptLimitError("stored per-attempt body length is outside the configured bound")
        unsigned = {key: value[key] for key in value if key != "receipt_sha256"}
        receipt_sha = value["receipt_sha256"]
        if (
            type(receipt_sha) is not str
            or _SHA256.fullmatch(receipt_sha) is None
            or _sha256(_canonical(unsigned)) != receipt_sha
        ):
            raise ReceiptIntegrityError("attempt receipt hash does not match canonical receipt bytes")

        state = value["state"]
        received = value["response_received_at_ms"]
        status = value["http_status"]
        failure = value["failure_kind"]
        raw_file = value["raw_response_file"]
        raw_sha = value["raw_response_sha256"]
        if state == "HTTP_RESPONSE":
            try:
                received = _clock_ms(received, "response_received_at_ms")
            except ReceiptStoreError as exc:
                raise ReceiptIntegrityError("HTTP response receipt has no valid receive clock") from exc
            if (
                received < requested
                or persisted < received
                or type(status) is not int
                or not 100 <= status <= 599
                or failure is not None
                or raw_file != f"{expected_number:08d}.response.raw"
                or type(raw_sha) is not str
                or _SHA256.fullmatch(raw_sha) is None
            ):
                raise ReceiptIntegrityError("HTTP response receipt fields are inconsistent")
        elif state == "NO_RESPONSE":
            if (
                received is not None
                or status is not None
                or type(failure) is not str
                or failure not in _FAILURE_KINDS
                or raw_file is not None
                or raw_count != 0
                or raw_sha is not None
            ):
                raise ReceiptIntegrityError("no-response receipt must explicitly omit response bytes/status")
        else:
            raise ReceiptIntegrityError("unknown attempt state")
        return RestCandleAttemptV3(
            attempt_number=expected_number,
            attempt_id=attempt_id,
            request=request,
            state=state,
            requested_at_ms=requested,
            response_received_at_ms=received,
            persisted_at_ms=persisted,
            http_status=status,
            failure_kind=failure,
            raw_response_file=raw_file,
            raw_response_bytes=raw_count,
            raw_response_sha256=raw_sha,
            previous_receipt_sha256=expected_previous_hash,
            receipt_sha256=receipt_sha,
        )
