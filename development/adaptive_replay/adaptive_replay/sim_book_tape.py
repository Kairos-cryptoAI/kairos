"""Global book mapping from independently pinned retained public capture bytes.

Derived kernel frames retain original event/local clocks and physical epoch.
Global sequence/tape identity is explicitly a mapping, never new vendor bytes.
This is observed-source consistency, not full tick coverage or trading authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from kairos_execution.simulation.bridge import kernel_frame
from kairos_execution.simulation.models import AcceptedBookFrame

from .book_bundle import BookBundleSeal, RetentionReceipt, open_book_bundle
from .historical_context import _clock, _json, _sha, canonical, digest
from .native_book_capture import NativeBookPolicy
from .public_book_capture import MAX_FRAMES, MAX_GAP_MS, MAX_RAW_TOTAL, _safe_existing, audit_public_capture


@dataclass(frozen=True)
class BoundBookFrame:
    frame: AcceptedBookFrame
    receipt_sha256: str
    native_frame_sha256: str
    raw_record_sha256: str
    segment_ordinal: int
    segment_sequence: int

    def __post_init__(self) -> None:
        if type(self.frame) is not AcceptedBookFrame:
            raise ValueError("exact derived kernel frame required")
        AcceptedBookFrame.model_validate(self.frame)
        for value in (self.receipt_sha256, self.native_frame_sha256, self.raw_record_sha256):
            _sha(value)
        if any(type(x) is not int or x <= 0 for x in (self.segment_ordinal, self.segment_sequence)):
            raise ValueError("positive original segment coordinates required")

    @property
    def mapping_sha256(self) -> str:
        return digest(
            {
                "schema": "public-native-to-sim.global-mapping.v1",
                "receipt_sha256": self.receipt_sha256,
                "native_frame_sha256": self.native_frame_sha256,
                "raw_record_sha256": self.raw_record_sha256,
                "segment_ordinal": self.segment_ordinal,
                "segment_sequence": self.segment_sequence,
                "derived_frame_sha256": self.frame.fingerprint(),
            }
        )


@dataclass(frozen=True)
class PublicBookTape:
    receipt_sha256: str
    source_sha256: str
    tape_id: str
    epoch: str
    quote_source_id: str
    frames: tuple[BoundBookFrame, ...]

    def __post_init__(self) -> None:
        _sha(self.receipt_sha256)
        _sha(self.source_sha256)
        if type(self.frames) is not tuple or not 1 <= len(self.frames) <= MAX_FRAMES:
            raise ValueError("bounded immutable complete observed tape required")
        if any(type(item) is not BoundBookFrame for item in self.frames):
            raise ValueError("typed global frame bindings required")
        previous_received = previous_persisted = -1
        symbols = {}
        for sequence, item in enumerate(self.frames, 1):
            if (
                item.frame.sequence != sequence
                or item.frame.tape_id != self.tape_id
                or item.frame.stream_epoch != self.epoch
                or item.receipt_sha256 != self.receipt_sha256
            ):
                raise ValueError("mapping must preserve one physical epoch and complete global ordinal")
            frame = item.frame
            if frame.received_at_ms < previous_received or frame.persisted_at_ms < previous_persisted:
                raise ValueError("global original delivery/persistence clocks must not regress")
            previous_received, previous_persisted = frame.received_at_ms, frame.persisted_at_ms
            if frame.symbol in symbols:
                update, event, received = symbols[frame.symbol]
                if (
                    frame.exchange_update_id <= update
                    or frame.exchange_at_ms < event
                    or max(frame.exchange_at_ms - event, frame.received_at_ms - received) > MAX_GAP_MS
                ):
                    raise ValueError("per-symbol original update/event/delivery continuity conflict")
            symbols[frame.symbol] = (frame.exchange_update_id, frame.exchange_at_ms, frame.received_at_ms)

    @property
    def sha256(self) -> str:
        return digest(
            {
                "receipt_sha256": self.receipt_sha256,
                "source_sha256": self.source_sha256,
                "tape_id": self.tape_id,
                "epoch": self.epoch,
                "quote_source_id": self.quote_source_id,
                "mappings": [item.mapping_sha256 for item in self.frames],
            }
        )

    def require_member(self, frame: AcceptedBookFrame, mapping_sha256: str) -> None:
        _sha(mapping_sha256)
        if not 1 <= frame.sequence <= len(self.frames):
            raise ValueError("frame outside pinned complete observed tape")
        item = self.frames[frame.sequence - 1]
        if item.frame != frame or item.mapping_sha256 != mapping_sha256:
            raise ValueError("supplied frame differs from pinned retained original mapping")


def load_public_book_tape(output: Path, *, expected_receipt_sha256: str) -> PublicBookTape:
    """Audit all original bytes before returning a deterministic bounded mapping.

    The independently held receipt commitment must not be discovered from the
    mutable source folder by the caller during admission. Failed captures refuse.
    """
    _sha(expected_receipt_sha256)
    output = _safe_existing(output, directory=True)
    audited = audit_public_capture(output, expected_receipt_sha256=expected_receipt_sha256)
    if audited["state"] != "PASS_OBSERVED_SOURCE_CONSISTENCY_ONLY":
        raise ValueError("complete observed source reconciliation required")
    receipt_path = _safe_existing(output / "receipt.json", directory=False)
    with receipt_path.open("rb") as stream:
        receipt_bytes = stream.read(1024 * 1024 + 1)
    if len(receipt_bytes) > 1024 * 1024:
        raise ValueError("bounded capture receipt required")
    if hashlib.sha256(receipt_bytes).hexdigest() != expected_receipt_sha256:
        raise ValueError("capture changed between audit and mapping")
    receipt = _json(receipt_bytes)
    raw_path = _safe_existing(output / "received.raw.jsonl", directory=False)
    # Hash the exact immutable byte snapshot which is parsed below. Re-auditing
    # the directory afterward cannot authenticate an intervening changed read.
    with raw_path.open("rb") as stream:
        raw_bytes = stream.read(MAX_RAW_TOTAL * 3 + 1)
    if (
        len(raw_bytes) > MAX_RAW_TOTAL * 3
        or hashlib.sha256(raw_bytes).hexdigest() != receipt["raw_file_sha256"]
    ):
        raise ValueError("mapping raw snapshot differs from independently pinned original bytes")
    raw_rows = []
    head = None
    for sequence, line in enumerate(raw_bytes.splitlines(keepends=True), 1):
        if sequence > MAX_FRAMES:
            raise ValueError("bounded original raw denominator required")
        row = _json(line)
        if (
            type(row) is not dict
            or set(row)
            != {
                "sequence",
                "previous_record_sha256",
                "received_ms",
                "received_monotonic_ns",
                "raw_payload",
                "raw_payload_sha256",
                "record_sha256",
            }
            or (canonical(row) + "\n").encode("utf-8") != line
        ):
            raise ValueError("canonical exact original received record required")
        _clock(row["received_ms"])
        _clock(row["received_monotonic_ns"])
        _sha(row["record_sha256"])
        _sha(row["raw_payload_sha256"])
        fields = {key: value for key, value in row.items() if key != "record_sha256"}
        if (
            type(row["sequence"]) is not int
            or row["sequence"] != sequence
            or row["previous_record_sha256"] != head
            or digest(fields) != row["record_sha256"]
            or type(row["raw_payload"]) is not str
            or hashlib.sha256(row["raw_payload"].encode("utf-8")).hexdigest() != row["raw_payload_sha256"]
        ):
            raise ValueError("original received snapshot chain/payload identity conflict")
        head = row["record_sha256"]
        raw_rows.append(row)
    if len(raw_rows) != receipt["admitted_frames"]:
        raise ValueError("mapping raw denominator changed after audit")
    if head != receipt["raw_head_sha256"]:
        raise ValueError("original received snapshot terminal commitment conflict")
    tape_id = f"public-native:{receipt['capture_id']}"
    frames = []
    quote_source = None
    for segment in receipt["segments"]:
        seal_data = dict(segment["seal"])
        seal_data["policy"] = NativeBookPolicy(**seal_data["policy"])
        seal = BookBundleSeal(**seal_data)
        retained = open_book_bundle(output / segment["name"], seal, RetentionReceipt(**segment["retention"]))
        quote_source = seal.policy.quote_source_id
        for binding in retained.bindings:
            native = binding.frame
            ordinal = len(frames) + 1
            original = raw_rows[ordinal - 1]
            if (
                original["raw_payload"] != native.raw_payload
                or original["raw_payload_sha256"] != native.raw_payload_sha256
                or original["received_ms"] != native.received_at_ms
            ):
                raise ValueError("raw original changed after audit")
            derived = AcceptedBookFrame.model_validate(
                kernel_frame(native).model_dump(mode="python")
                | {
                    "tape_id": tape_id,
                    "sequence": ordinal,
                }
            )
            frames.append(
                BoundBookFrame(
                    derived,
                    expected_receipt_sha256,
                    native.frame_sha256,
                    original["record_sha256"],
                    segment["ordinal"],
                    native.tape_sequence,
                )
            )
    # Recheck the whole externally pinned source after reopening/mapping, rather
    # than allowing mutable raw rows read in between to gain authority.
    audit_public_capture(output, expected_receipt_sha256=expected_receipt_sha256)
    if quote_source is None:
        raise ValueError("no native source policy")
    return PublicBookTape(
        expected_receipt_sha256,
        receipt["source_sha256"],
        tape_id,
        receipt["epoch"],
        quote_source,
        tuple(frames),
    )
