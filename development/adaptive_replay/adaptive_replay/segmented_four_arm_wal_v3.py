"""Create-only segmented checkpoint evidence, not database transaction authority.

Every checkpoint uses the original ROOT WAL codec/progression and framing.
No checkpoint is dropped, rewritten or compacted. Rotation adds an immutable
seal, a linked segment header and a catalog record, in that fsync order, only
at a completed operation. An interrupted publication is retained and refused;
there is deliberately no repair, truncation or latest-head adoption.

ACK means OS file fsync succeeded, not hardware power-loss durability, Windows
directory-entry durability, authentication or off-host retention. Independently
retain snapshot().anchor; it includes an exact checkpoint commitment. Open
audits ALL retained bytes/frames, so restart is linear, not constant-time.
"""

from __future__ import annotations

import hashlib
import os
import stat
import threading
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from pathlib import Path

from .continuous_four_arm_v3 import FourArmCheckpointV3
from .four_arm_checkpoint_wal_v3 import (
    SCHEMA as ROOT_SCHEMA,
)
from .four_arm_checkpoint_wal_v3 import (
    ZERO,
    CheckpointWalLimitsV3,
    FourArmCheckpointWalV3,
    _canonical,
    _frame,
    _lock,
    _path,
    _progress,
    _read_frame,
    _sha,
    checkpoint_document,
    checkpoint_from_document,
)

SCHEMA = "kairos.research.segmented-four-arm-checkpoint-wal.v3"
MAGIC = b"KAIROS-SEGMENTED-FOUR-ARM-V3\n"
CATALOG_MAGIC = b"KAIROS-SEGMENTED-CATALOG-V3\n"
SEAL_MAGIC = b"KAIROS-SEGMENTED-SEAL-V3\n"
# PREPARED, INTENT, up to four partial arm checkpoints, completed.
OPERATION_FRAME_RESERVE = 7
FRAME_OVERHEAD = 44


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _metadata(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _directory(path, *, exists):
    path = Path(os.path.abspath(path))
    _path(path.parent / "catalog.wal", exists=False)
    if exists:
        info = path.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
        ):
            raise ValueError("ordinary non-reparse segmented namespace required")
    return path


def _name(segment, *, seal=False):
    return f"segment-{segment:06d}.{'seal' if seal else 'wal'}"


@dataclass(frozen=True)
class SegmentedWalLimitsV3:
    max_frame_bytes: int = 2 * 1024 * 1024
    max_segment_frames: int = 10_000
    max_segment_bytes: int = 64 * 1024 * 1024
    max_segments: int = 4096
    max_global_frames: int = 10_000_000
    max_total_bytes: int = 512 * 1024**3
    max_catalog_bytes: int = 64 * 1024 * 1024

    def __post_init__(self):
        maxima = (
            32 * 1024 * 1024,
            1_000_000,
            8 * 1024**3,
            100_000,
            2**63 - 1,
            8 * 1024**4,
            256 * 1024 * 1024,
        )
        for field, maximum in zip(self.__dataclass_fields__, maxima, strict=True):
            value = getattr(self, field)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("exact bounded segmented WAL limits required")
        if self.max_segment_frames < OPERATION_FRAME_RESERVE + 1 or self.max_segment_bytes < (
            OPERATION_FRAME_RESERVE + 1
        ) * (self.max_frame_bytes + FRAME_OVERHEAD) + len(MAGIC):
            raise ValueError("segment must reserve a complete seven-frame operation plus header")

    def framing(self):
        return CheckpointWalLimitsV3(self.max_frame_bytes, self.max_segment_frames, self.max_segment_bytes)


@dataclass(frozen=True)
class SegmentedWalAnchorV3:
    identity_sha256: str
    catalog_count: int
    catalog_head_sha256: str
    catalog_bytes: int
    segment_number: int
    segment_header_sha256: str
    segment_frames: int
    segment_head_sha256: str
    segment_bytes: int
    global_frames: int
    global_head_sha256: str
    total_bytes: int
    checkpoint_sha256: str

    def __post_init__(self):
        for name in (
            "identity_sha256",
            "catalog_head_sha256",
            "segment_header_sha256",
            "segment_head_sha256",
            "global_head_sha256",
            "checkpoint_sha256",
        ):
            _sha(getattr(self, name))
        for name in (
            "catalog_count",
            "catalog_bytes",
            "segment_frames",
            "segment_bytes",
            "global_frames",
            "total_bytes",
        ):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 2**63 - 1:
                raise ValueError("positive exact segmented anchor counters required")
        if type(self.segment_number) is not int or not 0 <= self.segment_number < 100_000:
            raise ValueError("bounded exact segment number required")
        if self.catalog_count != self.segment_number + 1:
            raise ValueError("catalog count/segment mismatch")


@dataclass(frozen=True)
class SegmentedWalInspectionV3:
    anchor: SegmentedWalAnchorV3
    checkpoint: FourArmCheckpointV3
    limits: SegmentedWalLimitsV3


def _copy_checkpoint(value):
    return checkpoint_from_document(checkpoint_document(value))


def _closed_checkpoint(value):
    document = checkpoint_document(value)
    if value.pending_operation is not None:
        raise ValueError("rotation requires completed/no-pending checkpoint")
    return document


def _header(identity, limits, number, checkpoint, global_frames, global_head, catalog_head, seal_sha):
    return {
        "schema": SCHEMA,
        "kind": "SEGMENT",
        "identity_sha256": identity,
        "limits": asdict(limits),
        "segment_number": number,
        "checkpoint": checkpoint_document(checkpoint),
        "global_frames": global_frames,
        "global_head_sha256": global_head,
        "previous_catalog_sha256": catalog_head,
        "previous_seal_sha256": seal_sha,
    }


def _single(path, magic, limits):
    path = _path(path, exists=True)
    before = path.lstat()
    with path.open("rb") as stream:
        if _metadata(os.fstat(stream.fileno())) != _metadata(before) or stream.read(len(magic)) != magic:
            raise ValueError("control file identity/magic conflict")
        record, torn = _read_frame(stream, limits.framing())
        if torn or record is None or stream.read(1):
            raise ValueError("torn/extra control file bytes; no repair")
    if _metadata(path.lstat()) != _metadata(before):
        raise ValueError("control file changed during audit")
    return record, before.st_size


def _audit(directory, identity, *, catalog=None):
    """Linear full audit. No returned prefix on torn/orphan/unknown bytes."""
    _sha(identity)
    directory = _directory(directory, exists=True)
    before_dir = _metadata(directory.lstat())
    path = _path(directory / "catalog.wal", exists=True)
    catalog_meta = path.lstat()
    audited_metadata = {path: _metadata(catalog_meta)}
    records = []
    # Windows byte-range locks deny a second descriptor's reads. Audit the
    # catalog through the already locked owned descriptor during writer open.
    with path.open("rb") if catalog is None else nullcontext(catalog) as stream:
        stream.seek(0)
        if _metadata(os.fstat(stream.fileno())) != _metadata(catalog_meta):
            raise ValueError("catalog replaced while opening")
        if stream.read(len(CATALOG_MAGIC)) != CATALOG_MAGIC:
            raise ValueError("unknown segmented catalog magic")
        first, torn = _read_frame(stream, CheckpointWalLimitsV3(max_frame_bytes=32 * 1024 * 1024))
        if torn or first is None:
            raise ValueError("torn catalog bootstrap; no repair")
        bootstrap, catalog_head = first
        if (
            type(bootstrap) is not dict
            or set(bootstrap) != {"schema", "kind", "identity_sha256", "limits", "segment_header_sha256"}
            or bootstrap["schema"] != SCHEMA
            or bootstrap["kind"] != "BOOTSTRAP"
            or (bootstrap["identity_sha256"] != identity)
        ):
            raise ValueError("catalog bootstrap identity/schema conflict")
        limits = SegmentedWalLimitsV3(**bootstrap["limits"])
        if (
            catalog_meta.st_size > limits.max_catalog_bytes
            or len(_canonical(bootstrap)) > limits.max_frame_bytes
        ):
            raise ValueError("catalog capacity exceeded")
        catalog_count = 1
        while True:
            record, torn = _read_frame(stream, limits.framing())
            if torn:
                raise ValueError("torn catalog rotation; no repair")
            if record is None:
                break
            value, head = record
            if (
                len(records) + 1 >= limits.max_segments
                or type(value) is not dict
                or set(value)
                != {"schema", "kind", "sequence", "previous_sha256", "seal_sha256", "segment_header_sha256"}
                or value["schema"] != SCHEMA
                or value["kind"] != "ROTATE"
                or (
                    type(value["sequence"]) is not int
                    or value["sequence"] != catalog_count
                    or value["previous_sha256"] != catalog_head
                )
            ):
                raise ValueError("catalog rotation chain/capacity conflict")
            records.append((value, catalog_head))
            catalog_head = head
            catalog_count += 1
    if _metadata(path.lstat()) != _metadata(catalog_meta):
        raise ValueError("catalog changed during audit")
    expected_names = {"catalog.wal"}
    checkpoint = None
    global_frames, global_head = 0, ZERO
    total_bytes = catalog_meta.st_size
    previous_seal = ZERO
    previous_catalog = ZERO
    for number in range(catalog_count):
        name = _name(number)
        expected_names.add(name)
        segment_path = _path(directory / name, exists=True)
        segment_meta = segment_path.lstat()
        audited_metadata[segment_path] = _metadata(segment_meta)
        with segment_path.open("rb") as stream:
            if _metadata(os.fstat(stream.fileno())) != _metadata(segment_meta):
                raise ValueError("segment replaced during audit")
            if stream.read(len(MAGIC)) != MAGIC:
                raise ValueError("unknown segment magic")
            first, torn = _read_frame(stream, limits.framing())
            if torn or first is None:
                raise ValueError("torn segment header; no repair")
            header, header_head = first
            if number == 0:
                candidate = (
                    checkpoint_from_document(header.get("checkpoint")) if type(header) is dict else None
                )
                if (
                    candidate is None
                    or candidate.identity_sha256 != identity
                    or candidate.operation_cursor != 0
                    or candidate.pending_operation is not None
                    or (
                        candidate.driver_checkpoint.version != 0
                        or any(cp.version != 0 for _, cp in candidate.arm_checkpoints)
                    )
                ):
                    raise ValueError("segment genesis requires unadvanced accounts")
                checkpoint = candidate
            expected_header = _header(
                identity,
                limits,
                number,
                checkpoint,
                global_frames,
                global_head,
                previous_catalog,
                previous_seal,
            )
            if _canonical(header) != _canonical(expected_header):
                raise ValueError("segment linked header/checkpoint conflict")
            pinned_header = (
                bootstrap["segment_header_sha256"]
                if number == 0
                else records[number - 1][0]["segment_header_sha256"]
            )
            if header_head != pinned_header:
                raise ValueError("segment header differs from catalog commitment")
            if number == 0:
                global_frames, global_head = 1, header_head
            local_frames, local_head = 1, header_head
            while True:
                record, torn = _read_frame(stream, limits.framing())
                if torn:
                    raise ValueError("torn checkpoint segment; no repair")
                if record is None:
                    break
                value, head = record
                if (
                    type(value) is not dict
                    or set(value) != {"schema", "kind", "sequence", "previous_sha256", "checkpoint"}
                    or value["schema"] != ROOT_SCHEMA
                    or value["kind"] != "CHECKPOINT"
                    or (
                        type(value["sequence"]) is not int
                        or value["sequence"] != global_frames
                        or value["previous_sha256"] != global_head
                    )
                ):
                    raise ValueError("exact global checkpoint frame chain conflict")
                candidate = checkpoint_from_document(value["checkpoint"])
                _progress(checkpoint, candidate)
                if checkpoint_document(candidate) == checkpoint_document(checkpoint):
                    raise ValueError("duplicate physical checkpoint frame")
                checkpoint = candidate
                global_frames += 1
                local_frames += 1
                global_head = local_head = head
                if global_frames > limits.max_global_frames or local_frames > limits.max_segment_frames:
                    raise ValueError("checkpoint frame capacity exceeded")
            stream.seek(0)
            segment_digest = hashlib.file_digest(stream, "sha256")
        if (
            _metadata(segment_path.lstat()) != _metadata(segment_meta)
            or segment_meta.st_size > limits.max_segment_bytes
        ):
            raise ValueError("segment changed/capacity conflict")
        total_bytes += segment_meta.st_size
        if number < catalog_count - 1:
            seal_name = _name(number, seal=True)
            expected_names.add(seal_name)
            seal_path = _path(directory / seal_name, exists=True)
            audited_metadata[seal_path] = _metadata(seal_path.lstat())
            (seal, seal_head), seal_bytes = _single(directory / seal_name, SEAL_MAGIC, limits)
            expected_seal = {
                "schema": SCHEMA,
                "kind": "SEAL",
                "segment_number": number,
                "segment_header_sha256": header_head,
                "segment_frames": local_frames,
                "segment_bytes": segment_meta.st_size,
                "segment_sha256": segment_digest.hexdigest(),
                "global_frames": global_frames,
                "global_head_sha256": global_head,
                "checkpoint": _closed_checkpoint(checkpoint),
            }
            if (
                _canonical(seal) != _canonical(expected_seal)
                or seal_head != records[number][0]["seal_sha256"]
            ):
                raise ValueError("sealed segment bytes/checkpoint/catalog conflict")
            total_bytes += seal_bytes
            previous_seal, previous_catalog = seal_head, records[number][1]
    if {child.name for child in directory.iterdir()} != expected_names:
        raise ValueError("orphan/unknown rotation files; no adoption or repair")
    if any(
        _metadata(_path(file, exists=True).lstat()) != recorded for file, recorded in audited_metadata.items()
    ):
        raise ValueError("retained file changed during complete namespace audit")
    if _metadata(directory.lstat()) != before_dir or total_bytes > limits.max_total_bytes:
        raise ValueError("namespace changed/global byte capacity exceeded")
    anchor = SegmentedWalAnchorV3(
        identity,
        catalog_count,
        catalog_head,
        catalog_meta.st_size,
        catalog_count - 1,
        header_head,
        local_frames,
        local_head,
        segment_meta.st_size,
        global_frames,
        global_head,
        total_bytes,
        _hash(checkpoint_document(checkpoint)),
    )
    return SegmentedWalInspectionV3(anchor, checkpoint, limits), segment_digest


def inspect_segmented_four_arm_wal_v3(directory, *, identity_sha256):
    """Read-only full audit; never licenses advancing beyond caller's anchor."""
    return _audit(directory, identity_sha256)[0]


class SegmentedFourArmCheckpointWalV3:
    """Owned callable sink. Old closed segments are retained, never mutated."""

    def __init__(self, directory, catalog, segment, inspection, segment_digest):
        self.directory, self._catalog, self._segment = directory, catalog, segment
        self._inspection, self._segment_digest = inspection, segment_digest
        self._mutex = threading.RLock()
        self._closed = self._poisoned = False
        self._remember(allow_namespace_change=True)

    def _remember(self, *, allow_namespace_change=False):
        # Retain only our EXACT publication, not later bytes/new files written
        # during fsync. No file-history scan on an ordinary checkpoint append.
        anchor = self._inspection.anchor
        catalog_meta = _metadata(os.fstat(self._catalog.fileno()))
        segment_meta = _metadata(os.fstat(self._segment.fileno()))
        directory_meta = _metadata(self.directory.lstat())
        if (
            catalog_meta[2] != anchor.catalog_bytes
            or segment_meta[2] != anchor.segment_bytes
            or (
                _metadata(_path(self.directory / "catalog.wal", exists=True).lstat()) != catalog_meta
                or _metadata(_path(self.directory / _name(anchor.segment_number), exists=True).lstat())
                != segment_meta
            )
        ):
            raise ValueError("publication differs from exact own bytes/file identity")
        if hasattr(self, "_catalog_meta") and catalog_meta[:2] != self._catalog_meta[:2]:
            raise ValueError("catalog identity changed during publication")
        if allow_namespace_change:
            expected_names = {
                "catalog.wal",
                *(_name(n) for n in range(anchor.segment_number + 1)),
                *(_name(n, seal=True) for n in range(anchor.segment_number)),
            }
            if {entry.name for entry in self.directory.iterdir()} != expected_names:
                raise ValueError("unknown files during rotation publication")
        elif directory_meta != self._directory_meta or segment_meta[:2] != self._segment_meta[:2]:
            raise ValueError("namespace/segment changed during owned append")
        self._catalog_meta, self._segment_meta, self._directory_meta = (
            catalog_meta,
            segment_meta,
            directory_meta,
        )

    @staticmethod
    def _new_file(path, data, *, lock=False):
        path = _path(path, exists=False)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        stream = os.fdopen(fd, "r+b", buffering=0)
        try:
            if lock:
                _lock(fd)  # Own catalog BEFORE bootstrap bytes become visible.
            FourArmCheckpointWalV3._write(stream, data)
            os.fsync(fd)
            return stream
        except BaseException:
            stream.close()
            raise

    @classmethod
    def create(cls, directory, initial_checkpoint, *, limits=None):
        limits = SegmentedWalLimitsV3() if limits is None else limits
        if type(limits) is not SegmentedWalLimitsV3:
            raise ValueError("typed segmented limits required")
        document = _closed_checkpoint(initial_checkpoint)
        if (
            initial_checkpoint.operation_cursor != 0
            or initial_checkpoint.driver_checkpoint.version != 0
            or any(cp.version != 0 for _, cp in initial_checkpoint.arm_checkpoints)
        ):
            raise ValueError("new namespace requires unadvanced accounts")
        directory = _directory(directory, exists=False)
        header = _header(
            initial_checkpoint.identity_sha256, limits, 0, initial_checkpoint, 0, ZERO, ZERO, ZERO
        )
        frame, header_head = _frame(header, limits.framing())
        segment_data = MAGIC + frame
        bootstrap = {
            "schema": SCHEMA,
            "kind": "BOOTSTRAP",
            "identity_sha256": initial_checkpoint.identity_sha256,
            "limits": asdict(limits),
            "segment_header_sha256": header_head,
        }
        frame, catalog_head = _frame(bootstrap, limits.framing())
        catalog_data = CATALOG_MAGIC + frame
        if (
            len(catalog_data) > limits.max_catalog_bytes
            or len(segment_data) + len(catalog_data) > limits.max_total_bytes
        ):
            raise ValueError("bootstrap exceeds global/catalog capacity")
        directory.mkdir()
        catalog = segment = None
        try:
            # Exclusive directory creation owns bootstrap. Subsequent writers lock catalog.
            segment = cls._new_file(directory / _name(0), segment_data)
            catalog = cls._new_file(directory / "catalog.wal", catalog_data, lock=True)
            anchor = SegmentedWalAnchorV3(
                initial_checkpoint.identity_sha256,
                1,
                catalog_head,
                len(catalog_data),
                0,
                header_head,
                1,
                header_head,
                len(segment_data),
                1,
                header_head,
                len(segment_data) + len(catalog_data),
                _hash(document),
            )
            return cls(
                directory,
                catalog,
                segment,
                SegmentedWalInspectionV3(anchor, _copy_checkpoint(initial_checkpoint), limits),
                hashlib.sha256(segment_data),
            )
        except BaseException:
            if catalog is not None:
                catalog.close()
            if segment is not None:
                segment.close()
            raise

    @classmethod
    def open(cls, directory, *, expected_anchor):
        if type(expected_anchor) is not SegmentedWalAnchorV3:
            raise ValueError("independent typed segmented anchor required")
        SegmentedWalAnchorV3(**asdict(expected_anchor))
        directory = _directory(directory, exists=True)
        catalog_path = _path(directory / "catalog.wal", exists=True)
        catalog_meta = _metadata(catalog_path.lstat())
        catalog = catalog_path.open("r+b", buffering=0)
        segment = None
        try:
            if _metadata(os.fstat(catalog.fileno())) != catalog_meta:
                raise ValueError("catalog replaced while opening writer")
            _lock(catalog.fileno())
            segment_path = _path(directory / _name(expected_anchor.segment_number), exists=True)
            segment_meta = _metadata(segment_path.lstat())
            inspection, segment_digest = _audit(directory, expected_anchor.identity_sha256, catalog=catalog)
            if inspection.anchor != expected_anchor:
                raise ValueError("namespace differs from independent exact anchor; no latest adoption")
            segment = segment_path.open("r+b", buffering=0)
            if (
                _metadata(os.fstat(segment.fileno())) != segment_meta
                or _metadata(segment_path.lstat()) != segment_meta
                or _metadata(catalog_path.lstat()) != catalog_meta
            ):
                raise ValueError("files replaced after anchored audit")
            return cls(directory, catalog, segment, inspection, segment_digest)
        except BaseException:
            if segment is not None:
                segment.close()
            catalog.close()
            raise

    def _assert_owned(self):
        if self._closed or self._poisoned:
            raise ValueError("segmented writer closed or poisoned; no retry/adoption")
        anchor = self._inspection.anchor
        for path, stream, expected in (
            (self.directory / "catalog.wal", self._catalog, self._catalog_meta),
            (self.directory / _name(anchor.segment_number), self._segment, self._segment_meta),
        ):
            if (
                _metadata(_path(path, exists=True).lstat()) != expected
                or _metadata(os.fstat(stream.fileno())) != expected
            ):
                self._poisoned = True
                raise ValueError("owned WAL file changed externally")
        if _metadata(_directory(self.directory, exists=True).lstat()) != self._directory_meta:
            self._poisoned = True
            raise ValueError("namespace changed externally; possible orphan rotation")

    def snapshot(self):
        with self._mutex:
            self._assert_owned()
            current = self._inspection
            return SegmentedWalInspectionV3(
                current.anchor, _copy_checkpoint(current.checkpoint), current.limits
            )

    def _rotate(self):
        current = self._inspection
        anchor, limits = current.anchor, current.limits
        document = _closed_checkpoint(current.checkpoint)
        number = anchor.segment_number + 1
        if number >= limits.max_segments:
            raise ValueError("segment capacity exhausted before rotation")
        seal = {
            "schema": SCHEMA,
            "kind": "SEAL",
            "segment_number": anchor.segment_number,
            "segment_header_sha256": anchor.segment_header_sha256,
            "segment_frames": anchor.segment_frames,
            "segment_bytes": anchor.segment_bytes,
            "segment_sha256": self._segment_digest.hexdigest(),
            "global_frames": anchor.global_frames,
            "global_head_sha256": anchor.global_head_sha256,
            "checkpoint": document,
        }
        seal_frame, seal_head = _frame(seal, limits.framing())
        seal_data = SEAL_MAGIC + seal_frame
        header = _header(
            anchor.identity_sha256,
            limits,
            number,
            current.checkpoint,
            anchor.global_frames,
            anchor.global_head_sha256,
            anchor.catalog_head_sha256,
            seal_head,
        )
        header_frame, header_head = _frame(header, limits.framing())
        segment_data = MAGIC + header_frame
        catalog_record = {
            "schema": SCHEMA,
            "kind": "ROTATE",
            "sequence": anchor.catalog_count,
            "previous_sha256": anchor.catalog_head_sha256,
            "seal_sha256": seal_head,
            "segment_header_sha256": header_head,
        }
        catalog_data, catalog_head = _frame(catalog_record, limits.framing())
        total = anchor.total_bytes + len(seal_data) + len(segment_data) + len(catalog_data)
        if (
            anchor.catalog_bytes + len(catalog_data) > limits.max_catalog_bytes
            or total + (OPERATION_FRAME_RESERVE * (limits.max_frame_bytes + FRAME_OVERHEAD))
            > limits.max_total_bytes
        ):
            raise ValueError("rotation/global operation capacity exhausted before writes")
        next_segment = None
        try:
            with self._new_file(self.directory / _name(anchor.segment_number, seal=True), seal_data):
                pass  # fsync seal completed before publishing linked header.
            next_segment = self._new_file(self.directory / _name(number), segment_data)
            self._catalog.seek(anchor.catalog_bytes)
            FourArmCheckpointWalV3._write(self._catalog, catalog_data)
            os.fsync(self._catalog.fileno())
            new_anchor = SegmentedWalAnchorV3(
                anchor.identity_sha256,
                anchor.catalog_count + 1,
                catalog_head,
                anchor.catalog_bytes + len(catalog_data),
                number,
                header_head,
                1,
                header_head,
                len(segment_data),
                anchor.global_frames,
                anchor.global_head_sha256,
                total,
                anchor.checkpoint_sha256,
            )
            self._segment.close()
            self._segment = next_segment
            next_segment = None
            self._segment_digest = hashlib.sha256(segment_data)
            self._inspection = SegmentedWalInspectionV3(new_anchor, current.checkpoint, limits)
            self._remember(allow_namespace_change=True)
        except BaseException:
            self._poisoned = True
            if next_segment is not None:
                next_segment.close()
            raise

    def rotate(self):
        """Explicit durable rotation; retain the returned new anchor independently."""
        with self._mutex:
            self._assert_owned()
            self._rotate()
            return self.snapshot()

    def __call__(self, checkpoint):
        with self._mutex:
            self._assert_owned()
            current = self._inspection
            document = checkpoint_document(checkpoint)
            retained = checkpoint_from_document(document)
            _progress(current.checkpoint, retained)
            if checkpoint_document(current.checkpoint) == document:
                return True
            limits, anchor = current.limits, current.anchor
            # Validate full checkpoint bytes BEFORE any rotation mutation.
            # Rotation preserves global count/head, so this exact frame remains
            # correct in the newly linked segment.
            record = {
                "schema": ROOT_SCHEMA,
                "kind": "CHECKPOINT",
                "sequence": anchor.global_frames,
                "previous_sha256": anchor.global_head_sha256,
                "checkpoint": document,
            }
            data, head = _frame(record, limits.framing())
            if current.checkpoint.pending_operation is None:
                reserve = OPERATION_FRAME_RESERVE * (limits.max_frame_bytes + FRAME_OVERHEAD)
                if anchor.global_frames + OPERATION_FRAME_RESERVE > limits.max_global_frames or (
                    anchor.total_bytes + reserve > limits.max_total_bytes
                ):
                    raise ValueError("global complete-operation capacity exhausted before writes")
                if anchor.segment_frames + OPERATION_FRAME_RESERVE > limits.max_segment_frames or (
                    anchor.segment_bytes + reserve > limits.max_segment_bytes
                ):
                    self._rotate()
                    current, anchor = self._inspection, self._inspection.anchor
            if (
                anchor.segment_frames + 1 > limits.max_segment_frames
                or anchor.segment_bytes + len(data) > (limits.max_segment_bytes)
                or anchor.global_frames + 1 > limits.max_global_frames
                or anchor.total_bytes + len(data) > limits.max_total_bytes
            ):
                raise ValueError("WAL capacity exhausted; no pending rotation or omission")
            try:
                self._segment.seek(anchor.segment_bytes)
                FourArmCheckpointWalV3._write(self._segment, data)
                os.fsync(self._segment.fileno())
                self._segment_digest.update(data)
                new_anchor = SegmentedWalAnchorV3(
                    anchor.identity_sha256,
                    anchor.catalog_count,
                    anchor.catalog_head_sha256,
                    anchor.catalog_bytes,
                    anchor.segment_number,
                    anchor.segment_header_sha256,
                    anchor.segment_frames + 1,
                    head,
                    anchor.segment_bytes + len(data),
                    anchor.global_frames + 1,
                    head,
                    anchor.total_bytes + len(data),
                    _hash(document),
                )
                self._inspection = SegmentedWalInspectionV3(new_anchor, retained, limits)
                self._remember()
            except BaseException:
                self._poisoned = True
                raise
            return True

    def close(self):
        with self._mutex:
            if not self._closed:
                self._closed = True
                try:
                    _lock(self._catalog.fileno(), release=True)
                finally:
                    try:
                        self._catalog.close()
                    finally:
                        self._segment.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
