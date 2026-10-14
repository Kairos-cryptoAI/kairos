"""External, framed/fsynced checkpoint WAL for the financial four-arm driver.

This owns a NEW file outside the account databases. ACK means write/flush/fsync
returned successfully, not hardware power-loss durability, authentication or
off-host backup. Opening a writer requires an independently retained WAL anchor;
inspection never adopts a newer account/driver database. A torn final frame may
be inspected for recovery, but this implementation never truncates or repairs it.
Windows directory-entry durability at bootstrap is not asserted. Keep the WAL
in the owner's trusted filesystem; file hashes do not authenticate an attacker.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from .continuous_four_arm_v3 import ARMS, FourArmCheckpointV3
from .historical_context import digest
from .hypothesis_journal_v3 import JournalCheckpointV3
from .sim_delta_journal_v3 import DeltaCheckpointV3
from .sim_financial_journal_v3 import FinancialCheckpointV3

SCHEMA = "kairos.research.four-arm-checkpoint-wal.v3"
MAGIC = b"KAIROS-FOUR-ARM-WAL-V3\n"
FOOTER = b"CPV3"
ZERO = "0" * 64


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def _sha(value):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("exact lowercase SHA256 required")


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError("duplicate WAL JSON key")
        result[key] = value
    return result


def _path(value, *, exists):
    path = Path(os.path.abspath(value))
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            if current != path or exists:
                raise ValueError("existing non-reparse WAL parent required") from None
            break
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ValueError("WAL symlink/reparse components forbidden")
    if exists and not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("regular WAL file required")
    return path


@dataclass(frozen=True)
class CheckpointWalLimitsV3:
    max_frame_bytes: int = 2 * 1024 * 1024
    max_frames: int = 100_000
    max_file_bytes: int = 512 * 1024 * 1024

    def __post_init__(self):
        for field in self.__dataclass_fields__:
            if type(getattr(self, field)) is not int or getattr(self, field) <= 0:
                raise ValueError("positive exact WAL resource limits required")
        if (
            self.max_frame_bytes > 32 * 1024 * 1024
            or self.max_frames > 1_000_000
            or self.max_file_bytes > 8 * 1024**3
        ):
            raise ValueError("WAL resource ceiling exceeded")


@dataclass(frozen=True)
class CheckpointWalAnchorV3:
    identity_sha256: str
    frame_count: int
    head_sha256: str
    durable_bytes: int

    def __post_init__(self):
        _sha(self.identity_sha256)
        _sha(self.head_sha256)
        if (
            type(self.frame_count) is not int
            or self.frame_count < 1
            or type(self.durable_bytes) is not int
            or self.durable_bytes < len(MAGIC)
        ):
            raise ValueError("exact WAL prefix counts required")


@dataclass(frozen=True)
class CheckpointWalInspectionV3:
    anchor: CheckpointWalAnchorV3
    checkpoint: FourArmCheckpointV3
    limits: CheckpointWalLimitsV3
    torn_tail_bytes: int


def checkpoint_document(checkpoint):
    if type(checkpoint) is not FourArmCheckpointV3:
        raise ValueError("typed financial four-arm checkpoint required")
    _sha(checkpoint.identity_sha256)
    if type(checkpoint.driver_checkpoint) is not DeltaCheckpointV3:
        raise ValueError("typed driver delta checkpoint required")
    DeltaCheckpointV3(**asdict(checkpoint.driver_checkpoint))
    if (
        type(checkpoint.arm_checkpoints) is not tuple
        or tuple(a for a, _ in checkpoint.arm_checkpoints) != ARMS
    ):
        raise ValueError("exact fixed four-arm financial roster required")
    for arm, value in checkpoint.arm_checkpoints:
        if type(value) is not FinancialCheckpointV3 or value.account_id != arm:
            raise ValueError("native financial arm checkpoint required")
        FinancialCheckpointV3(**asdict(value))
    producers = checkpoint.producer_checkpoints
    if (
        type(producers) is not tuple
        or not 1 <= len(producers) <= 128
        or len({name for name, _ in producers}) != len(producers)
    ):
        raise ValueError("unique bounded producer checkpoint roster required")
    for name, value in producers:
        if type(name) is not str or not name or len(name) > 128 or type(value) is not JournalCheckpointV3:
            raise ValueError("typed producer checkpoint required")
        JournalCheckpointV3(**asdict(value))
    if type(checkpoint.operation_cursor) is not int or checkpoint.operation_cursor < 0:
        raise ValueError("exact nonnegative operation cursor required")
    pending = checkpoint.pending_operation
    if pending is None:
        if (
            checkpoint.pending_operation_sha256 is not None
            or checkpoint.checkpoint_phase != "INTENT_COMMITTED"
        ):
            raise ValueError("null pending requires completed checkpoint phase")
    else:
        if (
            type(pending) is not dict
            or set(pending) != {"operation", "before", "effects"}
            or checkpoint.checkpoint_phase not in {"PREPARED_INTENT", "INTENT_COMMITTED"}
        ):
            raise ValueError("exact pending WAL structure and phase required")
        if (
            any(type(pending[k]) is not dict or set(pending[k]) != set(ARMS) for k in ("before", "effects"))
            or type(pending["operation"]) is not dict
        ):
            raise ValueError("complete four-arm pending WAL required")
        if checkpoint.pending_operation_sha256 != digest(pending):
            raise ValueError("whole pending WAL commitment differs")
        for arm, value in checkpoint.arm_checkpoints:
            before = FinancialCheckpointV3(**pending["before"][arm])
            if (
                before.account_id != arm
                or before.owner_id != value.owner_id
                or before.identity_sha256 != value.identity_sha256
            ):
                raise ValueError("pending account owner/identity differs")
            if checkpoint.checkpoint_phase == "PREPARED_INTENT" and before != value:
                raise ValueError("prepared intent cannot already contain account effects")
            maximum_version = before.version + (pending["effects"][arm] is not None)
            if not before.version <= value.version <= maximum_version:
                raise ValueError("pending account advanced outside its one exact effect")
    return json.loads(_canonical(asdict(checkpoint)), object_pairs_hook=_pairs)


def checkpoint_from_document(document):
    if type(document) is not dict or set(document) != set(FourArmCheckpointV3.__dataclass_fields__):
        raise ValueError("closed checkpoint document schema required")
    try:
        result = FourArmCheckpointV3(
            document["identity_sha256"],
            DeltaCheckpointV3(**document["driver_checkpoint"]),
            tuple((a, FinancialCheckpointV3(**value)) for a, value in document["arm_checkpoints"]),
            tuple((name, JournalCheckpointV3(**value)) for name, value in document["producer_checkpoints"]),
            document["operation_cursor"],
            document["pending_operation_sha256"],
            document["pending_operation"],
            document["checkpoint_phase"],
        )
        if checkpoint_document(result) != document:
            raise ValueError("checkpoint document changed during decode")
    except (KeyError, TypeError) as exc:
        raise ValueError("invalid typed checkpoint document") from exc
    return result


def _progress(before, after):
    # The driver performs the independent financial/effect audit. This sink
    # additionally refuses rollback, foreign owners and unlicensed phase moves.
    if (
        before.identity_sha256 != after.identity_sha256
        or before.producer_checkpoints != after.producer_checkpoints
    ):
        raise ValueError("WAL experiment/producer identity changed")
    if before.driver_checkpoint.identity_sha256 != after.driver_checkpoint.identity_sha256:
        raise ValueError("WAL driver identity changed")
    for (_, old), (_, new) in zip(before.arm_checkpoints, after.arm_checkpoints, strict=True):
        if (
            (old.identity_sha256, old.owner_id, old.account_id)
            != (new.identity_sha256, new.owner_id, new.account_id)
            or not old.version <= new.version <= old.version + 1
            or new.source_cursor < old.source_cursor
            or new.native_count < old.native_count
            or new.last_clock_ms < old.last_clock_ms
        ):
            raise ValueError("WAL financial owner/head/cursor regression")
        if old.version == new.version and old != new:
            raise ValueError("financial same-version head changed")
    if checkpoint_document(before) == checkpoint_document(after):
        return
    if before.pending_operation is None:
        if (
            after.pending_operation is None
            or after.checkpoint_phase != "PREPARED_INTENT"
            or before.operation_cursor != after.operation_cursor
            or before.driver_checkpoint != after.driver_checkpoint
            or before.arm_checkpoints != after.arm_checkpoints
        ):
            raise ValueError("new operation must first retain its exact preintent")
    elif after.pending_operation is not None:
        if (
            before.pending_operation_sha256 != after.pending_operation_sha256
            or before.operation_cursor != after.operation_cursor
            or after.checkpoint_phase != "INTENT_COMMITTED"
        ):
            raise ValueError("pending operation/phase changed")
        step = 1 if before.checkpoint_phase == "PREPARED_INTENT" else 0
        if after.driver_checkpoint.version != before.driver_checkpoint.version + step:
            raise ValueError("intent must advance exactly one driver event")
        if step == 0 and before.driver_checkpoint != after.driver_checkpoint:
            raise ValueError("pending driver head changed")
        if step == 1 and before.arm_checkpoints != after.arm_checkpoints:
            raise ValueError("account effects preceded intent durability")
    elif (
        before.checkpoint_phase != "INTENT_COMMITTED"
        or after.operation_cursor != before.operation_cursor + 1
        or after.driver_checkpoint.version != before.driver_checkpoint.version + 1
    ):
        raise ValueError("completed operation must follow its retained intent")
    if before.pending_operation is not None and after.pending_operation is None:
        for arm, current in after.arm_checkpoints:
            original = FinancialCheckpointV3(**before.pending_operation["before"][arm])
            expected_version = original.version + (before.pending_operation["effects"][arm] is not None)
            if current.version != expected_version:
                raise ValueError("completed checkpoint lacks its financial account effect")
    if after.driver_checkpoint.last_clock_ms < before.driver_checkpoint.last_clock_ms:
        raise ValueError("WAL driver clock regressed")


def _frame(value, limits):
    payload = _canonical(value)
    if len(payload) > limits.max_frame_bytes:
        raise ValueError("WAL frame byte ceiling exceeded")
    head = hashlib.sha256(payload).digest()
    return struct.pack(">Q", len(payload)) + payload + head + FOOTER, head.hex()


def _read_frame(stream, limits):
    length_raw = stream.read(8)
    if not length_raw:
        return None, False
    if len(length_raw) != 8:
        return None, True
    length = struct.unpack(">Q", length_raw)[0]
    if not 1 <= length <= limits.max_frame_bytes:
        raise ValueError("invalid WAL frame length")
    payload = stream.read(length)
    trailer = stream.read(36)
    if len(payload) != length or len(trailer) != 36:
        return None, True
    if trailer[-4:] != FOOTER or hashlib.sha256(payload).digest() != trailer[:32]:
        raise ValueError("WAL frame hash/footer conflict")
    try:
        value = json.loads(payload, object_pairs_hook=_pairs)
        if _canonical(value) != payload:
            raise ValueError("noncanonical WAL frame")
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid WAL frame JSON") from exc
    return (value, trailer[:32].hex()), False


def _inspection(stream, identity_sha256):
    _sha(identity_sha256)
    before = os.fstat(stream.fileno())
    stream.seek(0)
    if stream.read(len(MAGIC)) != MAGIC:
        raise ValueError("unknown checkpoint WAL magic")
    first, torn = _read_frame(stream, CheckpointWalLimitsV3(max_frame_bytes=32 * 1024 * 1024))
    if first is None or torn:
        raise ValueError("complete WAL bootstrap required")
    header, head = first
    if (
        type(header) is not dict
        or set(header) != {"schema", "kind", "identity_sha256", "limits", "checkpoint"}
        or header["schema"] != SCHEMA
        or header["kind"] != "BOOTSTRAP"
        or header["identity_sha256"] != identity_sha256
    ):
        raise ValueError("checkpoint WAL header/identity conflict")
    limits = CheckpointWalLimitsV3(**header["limits"])
    if before.st_size > limits.max_file_bytes or len(_canonical(header)) > limits.max_frame_bytes:
        raise ValueError("WAL file/frame byte ceiling exceeded")
    checkpoint = checkpoint_from_document(header["checkpoint"])
    if (
        checkpoint.identity_sha256 != identity_sha256
        or checkpoint.operation_cursor != 0
        or checkpoint.pending_operation is not None
        or checkpoint.driver_checkpoint.version != 0
        or any(value.version != 0 for _, value in checkpoint.arm_checkpoints)
    ):
        raise ValueError("WAL bootstrap must retain unadvanced enrolled accounts")
    frames, durable_bytes = 1, stream.tell()
    while True:
        record, torn = _read_frame(stream, limits)
        if record is None:
            break
        if frames >= limits.max_frames:
            raise ValueError("WAL frame-count ceiling exceeded")
        value, record_head = record
        if (
            type(value) is not dict
            or set(value) != {"schema", "kind", "sequence", "previous_sha256", "checkpoint"}
            or value["schema"] != SCHEMA
            or value["kind"] != "CHECKPOINT"
            or type(value["sequence"]) is not int
            or value["sequence"] != frames
            or value["previous_sha256"] != head
        ):
            raise ValueError("WAL frame sequence/chain conflict")
        current = checkpoint_from_document(value["checkpoint"])
        _progress(checkpoint, current)
        checkpoint, head = current, record_head
        frames += 1
        durable_bytes = stream.tell()
    after = os.fstat(stream.fileno())
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ValueError("WAL changed during full prefix audit")
    tail = before.st_size - durable_bytes
    if bool(tail) != torn:
        raise ValueError("WAL trailing bytes conflict")
    return CheckpointWalInspectionV3(
        CheckpointWalAnchorV3(identity_sha256, frames, head, durable_bytes), checkpoint, limits, tail
    )


def inspect_checkpoint_wal_v3(path, *, identity_sha256):
    """Inspect trusted external evidence; torn tail is explicit, never repaired."""
    path = _path(path, exists=True)
    before = path.lstat()
    with path.open("rb") as stream:
        if (before.st_dev, before.st_ino) != (
            os.fstat(stream.fileno()).st_dev,
            os.fstat(stream.fileno()).st_ino,
        ):
            raise ValueError("WAL file replaced while opening")
        result = _inspection(stream, identity_sha256)
    after = path.lstat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ValueError("WAL path changed during full prefix audit")
    return result


def _lock(fd, *, release=False):
    os.lseek(fd, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_UNLCK if release else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN if release else fcntl.LOCK_EX | fcntl.LOCK_NB)


class FourArmCheckpointWalV3:
    """Single-writer callable sink; every new ACK follows file fsync."""

    def __init__(self, path, stream, inspection):
        self._path, self._stream, self._inspection = path, stream, inspection
        self._metadata = os.fstat(stream.fileno())
        self._mutex = threading.RLock()
        self._poisoned = False
        self._closed = False

    @classmethod
    def create(cls, path, initial_checkpoint, *, limits=None):
        limits = limits or CheckpointWalLimitsV3()
        if type(limits) is not CheckpointWalLimitsV3:
            raise ValueError("typed explicit WAL limits required")
        document = checkpoint_document(initial_checkpoint)
        if (
            initial_checkpoint.operation_cursor != 0
            or initial_checkpoint.pending_operation is not None
            or initial_checkpoint.driver_checkpoint.version != 0
            or any(cp.version != 0 for _, cp in initial_checkpoint.arm_checkpoints)
        ):
            raise ValueError("new WAL requires initial unadvanced accounts")
        path = _path(path, exists=False)
        header = {
            "schema": SCHEMA,
            "kind": "BOOTSTRAP",
            "identity_sha256": initial_checkpoint.identity_sha256,
            "limits": asdict(limits),
            "checkpoint": document,
        }
        framed, head = _frame(header, limits)
        data = MAGIC + framed
        if len(data) > limits.max_file_bytes:
            raise ValueError("WAL bootstrap exceeds file ceiling")
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        stream = os.fdopen(fd, "r+b", buffering=0)
        try:
            _lock(fd)
            cls._write(stream, data)
            os.fsync(fd)
            anchor = CheckpointWalAnchorV3(initial_checkpoint.identity_sha256, 1, head, len(data))
            inspection = CheckpointWalInspectionV3(anchor, checkpoint_from_document(document), limits, 0)
            return cls(path, stream, inspection)
        except BaseException:
            stream.close()
            raise  # Retain the exact partial bootstrap; never delete/adopt it.

    @classmethod
    def open(cls, path, *, expected_anchor):
        if type(expected_anchor) is not CheckpointWalAnchorV3:
            raise ValueError("independent typed WAL anchor required")
        path = _path(path, exists=True)
        before = path.lstat()
        stream = path.open("r+b", buffering=0)
        try:
            if (before.st_dev, before.st_ino) != (
                os.fstat(stream.fileno()).st_dev,
                os.fstat(stream.fileno()).st_ino,
            ):
                raise ValueError("WAL file replaced while opening")
            _lock(stream.fileno())
            inspection = _inspection(stream, expected_anchor.identity_sha256)
            if inspection.torn_tail_bytes or inspection.anchor != expected_anchor:
                raise ValueError("WAL differs from independent exact anchor or has torn tail")
            return cls(path, stream, inspection)
        except BaseException:
            stream.close()
            raise

    @staticmethod
    def _write(stream, data):
        view = memoryview(data)
        while view:
            count = stream.write(view)
            if not count:
                raise OSError("WAL short write")
            view = view[count:]
        stream.flush()

    def _assert_owned(self):
        if self._closed or self._poisoned:
            raise ValueError("WAL writer closed or poisoned; no retry/adoption")
        path = _path(self._path, exists=True)
        current, opened = path.lstat(), os.fstat(self._stream.fileno())
        expected = self._metadata
        for actual in (current, opened):
            if (actual.st_dev, actual.st_ino, actual.st_size, actual.st_mtime_ns) != (
                expected.st_dev,
                expected.st_ino,
                expected.st_size,
                expected.st_mtime_ns,
            ):
                self._poisoned = True
                raise ValueError("WAL advanced or replaced outside owned writer")

    def snapshot(self):
        with self._mutex:
            self._assert_owned()
            value = self._inspection
            return CheckpointWalInspectionV3(
                value.anchor, checkpoint_from_document(checkpoint_document(value.checkpoint)), value.limits, 0
            )

    def __call__(self, checkpoint):
        with self._mutex:
            self._assert_owned()
            document = checkpoint_document(checkpoint)
            retained = checkpoint_from_document(document)
            current = self._inspection
            _progress(current.checkpoint, retained)
            if checkpoint_document(current.checkpoint) == document:
                return True  # Exact already-fsynced redelivery, not new effects.
            record = {
                "schema": SCHEMA,
                "kind": "CHECKPOINT",
                "sequence": current.anchor.frame_count,
                "previous_sha256": current.anchor.head_sha256,
                "checkpoint": document,
            }
            data, head = _frame(record, current.limits)
            size = current.anchor.durable_bytes + len(data)
            if (
                current.anchor.frame_count >= current.limits.max_frames
                or size > current.limits.max_file_bytes
            ):
                raise ValueError("WAL resource ceiling exceeded before append")
            try:
                self._stream.seek(current.anchor.durable_bytes)
                self._write(self._stream, data)
                os.fsync(self._stream.fileno())  # The only new-success ACK boundary.
                self._metadata = os.fstat(self._stream.fileno())
                anchor = CheckpointWalAnchorV3(
                    current.anchor.identity_sha256, current.anchor.frame_count + 1, head, size
                )
                self._inspection = CheckpointWalInspectionV3(anchor, retained, current.limits, 0)
            except BaseException:
                self._poisoned = True
                raise
            return True

    def close(self):
        with self._mutex:
            if not self._closed:
                self._closed = True
                try:
                    _lock(self._stream.fileno(), release=True)
                finally:
                    self._stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
