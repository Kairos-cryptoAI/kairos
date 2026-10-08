"""Create-only offline native source retention, never a recorder or admission gate.

Caller-held seal AND retention receipt are required on every read. Original
vendor text and derived research bytes stay distinct. Consistency is not feed
authenticity, historical clock proof, continuous coverage or trading authority.
"""

from __future__ import annotations

import hashlib
import os
import stat
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from kairos_core.contracts.simulation import RecordedTopNBookFrameV2

from .historical_context import _clock, _json, _name, _sha, canonical, digest
from .hypothesis_journal import HypothesisJournal, JournalSeal, implementation_binding
from .native_book_capture import (
    MAX_PREFIX_FRAMES,
    BookPrefixReceipt,
    NativeBookCapture,
    NativeBookPolicy,
    audit_book_prefix,
)
from .quote_capture import admit_capture
from .scenarios import MAX_OBSERVATIONS

SCHEMA = "kairos.development.retained-native-book.v1"
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_RECORD_BYTES = 256 * 1024
COVERAGE = "STRUCTURAL_PREFIX_ONLY_NOT_CONTINUOUS_MARKET_COVERAGE"
CLOCKS = "CALLER_ATTESTED_NATIVE_TIMES_NOT_AUTHENTICATED"


def _count(value: int) -> None:
    if type(value) is not int or not 1 <= value <= MAX_PREFIX_FRAMES:
        raise ValueError("bounded complete source frame count required (1..512)")


def _implementation_sha() -> str:
    return digest(_json(implementation_binding()))


@dataclass(frozen=True)
class BookBundleSeal:
    """Caller commitment, NOT an independently signed source acceptance."""

    bundle_id: str
    tape_id: str
    stream_epoch: str
    policy: NativeBookPolicy
    frame_count: int
    native_head_sha256: str
    records_sha256: str
    implementation_sha256: str

    def __post_init__(self) -> None:
        for value in (self.bundle_id, self.tape_id, self.stream_epoch):
            _name(value)
        if type(self.policy) is not NativeBookPolicy:
            raise ValueError("exact native policy required")
        NativeBookPolicy(**asdict(self.policy))
        _count(self.frame_count)
        for value in (self.native_head_sha256, self.records_sha256, self.implementation_sha256):
            _sha(value)

    @property
    def sha256(self) -> str:
        self.__post_init__()
        return digest({"schema": SCHEMA, "seal": asdict(self)})


@dataclass(frozen=True)
class RetentionReceipt:
    seal_sha256: str
    file_sha256: str
    retained_at_ms: int
    frame_count: int
    native_head_sha256: str
    risk_authority: str = "NONE"
    coverage_authority: str = COVERAGE
    clock_authority: str = CLOCKS

    def __post_init__(self) -> None:
        for value in (self.seal_sha256, self.file_sha256, self.native_head_sha256):
            _sha(value)
        _clock(self.retained_at_ms)
        _count(self.frame_count)
        if (
            self.risk_authority != "NONE"
            or self.coverage_authority != COVERAGE
            or self.clock_authority != CLOCKS
        ):
            raise ValueError("retention cannot grant origin/coverage/clock/trading authority")

    @property
    def sha256(self) -> str:
        self.__post_init__()
        return digest({"schema": SCHEMA, "retention": asdict(self)})


@dataclass(frozen=True)
class RetainedBookBundle:
    seal: BookBundleSeal
    retention: RetentionReceipt
    bindings: tuple[NativeBookCapture, ...]


@dataclass(frozen=True)
class DurableBookCapture:
    binding: NativeBookCapture
    prefix: BookPrefixReceipt
    retention: RetentionReceipt
    risk_authority: str = "NONE"


@dataclass(frozen=True)
class BookSourceMatch:
    arm_id: str
    parent_id: str
    minute_ms: int
    sequence: int
    binding_sha256: str
    visible_prefix_sha256: str


@dataclass(frozen=True)
class BookSourceAudit:
    journal_head_sha256: str
    journal_event_count: int
    bundle_seal_sha256: str
    retention_sha256: str
    matches: tuple[BookSourceMatch, ...]
    risk_authority: str = "NONE"
    coverage_authority: str = COVERAGE
    clock_authority: str = CLOCKS

    @property
    def sha256(self) -> str:
        return digest({"schema": SCHEMA, "source_audit": asdict(self)})


def _record(binding: NativeBookCapture) -> dict[str, Any]:
    capture = binding.capture  # Fresh native/raw revalidation, including copied objects.
    result = {
        "frame": binding.frame.model_dump(mode="json", warnings="error"),
        "binding_sha256": binding.sha256,
        "derived_capture": {
            "raw_payload_utf8": capture.raw_payload.decode("utf-8"),
            "raw_payload_sha256": capture.raw_payload_sha256,
            "received_ms": capture.received_ms,
            "captured_ms": capture.captured_ms,
            "ttl_ms": capture.ttl_ms,
            "evidence_kind": capture.evidence_kind,
            "capture_sha256": capture.sha256,
        },
    }
    if len(canonical(result).encode("utf-8")) > MAX_RECORD_BYTES:
        raise ValueError("bounded native record required")
    return result


def _records(
    frames: tuple[RecordedTopNBookFrameV2, ...], policy: NativeBookPolicy
) -> tuple[list[dict[str, Any]], BookPrefixReceipt]:
    if type(frames) is not tuple or not 1 <= len(frames) <= MAX_PREFIX_FRAMES:
        raise ValueError("bounded immutable complete native prefix required (1..512)")
    # Validate before using even the root/tail attributes of a caller object.
    bindings = tuple(NativeBookCapture(frame, policy) for frame in frames)
    prefix = audit_book_prefix(
        frames,
        policy,
        tape_id=bindings[0].frame.tape_id,
        stream_epoch=bindings[0].frame.stream_epoch,
        expected_head_sha256=bindings[-1].frame.frame_sha256,
        asof_ms=bindings[-1].frame.persisted_at_ms,
    )
    return [_record(binding) for binding in bindings], prefix


def prepare_book_bundle(
    bundle_id: str,
    frames: tuple[RecordedTopNBookFrameV2, ...],
    policy: NativeBookPolicy,
) -> BookBundleSeal:
    """Describe supplied bytes; this does not admit/authenticate a data source."""
    records, prefix = _records(frames, policy)
    return BookBundleSeal(
        bundle_id,
        prefix.tape_id,
        prefix.stream_epoch,
        policy,
        len(frames),
        prefix.head_sha256,
        digest(records),
        _implementation_sha(),
    )


def _seal(seal: BookBundleSeal) -> BookBundleSeal:
    if type(seal) is not BookBundleSeal:
        raise ValueError("caller-retained typed source seal required")
    seal.__post_init__()
    result = BookBundleSeal(
        seal.bundle_id,
        seal.tape_id,
        seal.stream_epoch,
        NativeBookPolicy(**asdict(seal.policy)),
        seal.frame_count,
        seal.native_head_sha256,
        seal.records_sha256,
        seal.implementation_sha256,
    )
    if result.implementation_sha256 != _implementation_sha():
        raise ValueError("installed implementation changed; never reseal/adopt an old bundle")
    return result


def _path(path: Path, *, exists: bool) -> Path:
    path = Path(path).absolute()
    if not path.name.endswith(".native-book.research.json"):
        raise ValueError("dedicated .native-book.research.json source file required")
    for item in (*reversed(path.parents), path):
        if item == path and not exists and not item.exists():
            continue
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("source paths cannot traverse symlinks or reparse points")
        if item != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError("existing dedicated parent directory required")
        if item == path and (
            not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE_BYTES
        ):
            raise ValueError("bounded unaliased regular source file required")
    return path


def retain_book_bundle(
    path: Path, seal: BookBundleSeal, frames: tuple[RecordedTopNBookFrameV2, ...]
) -> RetentionReceipt:
    """Exclusive one-shot retention; failed/partial attempts are never removed.

    Modern retention time is separate from original native clocks. No append,
    resume, overwrite or claim that this newly written file existed historically.
    """
    seal = _seal(seal)
    prepared = prepare_book_bundle(seal.bundle_id, frames, seal.policy)
    if prepared != seal:
        raise ValueError("supplied frames differ from the caller-pinned source seal")
    records, _ = _records(frames, seal.policy)
    retained_at_ms = time.time_ns() // 1_000_000
    if frames[-1].persisted_at_ms > retained_at_ms:
        raise ValueError("native persistence cannot postdate modern retention")
    raw = canonical(
        {"schema": SCHEMA, "seal": asdict(seal), "retained_at_ms": retained_at_ms, "records": records}
    ).encode("utf-8")
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("bounded complete source file required; never truncate")
    path = _path(path, exists=False)
    with path.open("xb") as stream:
        if stream.write(raw) != len(raw):
            raise OSError("incomplete source retention; preserve the failed attempt")
        stream.flush()
        os.fsync(stream.fileno())
    receipt = RetentionReceipt(
        seal.sha256,
        hashlib.sha256(raw).hexdigest(),
        retained_at_ms,
        seal.frame_count,
        seal.native_head_sha256,
    )
    open_book_bundle(path, seal, receipt)
    return receipt


def open_book_bundle(path: Path, seal: BookBundleSeal, receipt: RetentionReceipt) -> RetainedBookBundle:
    """Read-only full audit against independently retained caller expectations.

    A coordinated replacement of file, seal AND receipt is not detectable here.
    Hold expectations separately; no external signature or origin trust implied.
    """
    seal = _seal(seal)
    if type(receipt) is not RetentionReceipt:
        raise ValueError("caller-retained typed retention receipt required")
    receipt = RetentionReceipt(**asdict(receipt))
    if (
        receipt.seal_sha256 != seal.sha256
        or receipt.frame_count != seal.frame_count
        or receipt.native_head_sha256 != seal.native_head_sha256
    ):
        raise ValueError("caller-pinned retention/source identity conflict")
    path = _path(path, exists=True)
    before = path.stat()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_size) != (
            before.st_dev,
            before.st_ino,
            before.st_size,
        ) or opened.st_nlink != 1:
            raise ValueError("source file changed during open")
        raw = stream.read(MAX_FILE_BYTES + 1)
        after = os.fstat(stream.fileno())

    def stable(info: os.stat_result) -> tuple[int, ...]:
        # Filesystem timestamps are not content identity (Windows handle/path
        # metadata may settle after close, and Linux reads may change atime).
        # The independently pinned whole-byte hash below decides content.
        return (info.st_dev, info.st_ino, info.st_size, info.st_nlink)

    if (
        stable(before) != stable(after)
        or stable(path.stat()) != stable(after)
        or not 0 < len(raw) <= MAX_FILE_BYTES
    ):
        raise ValueError("source file changed or exceeded its byte bound")
    if hashlib.sha256(raw).hexdigest() != receipt.file_sha256:
        raise ValueError("source bytes differ from caller-pinned retention; no repair")
    try:
        text = raw.decode("utf-8", errors="strict")
        payload = _json(text)
        if type(payload) is not dict or set(payload) != {"schema", "seal", "retained_at_ms", "records"}:
            raise ValueError("exact retained source fields required")
        if (
            payload["schema"] != SCHEMA
            or canonical(payload["seal"]) != canonical(asdict(seal))
            or type(payload["retained_at_ms"]) is not int
            or payload["retained_at_ms"] != receipt.retained_at_ms
            or canonical(payload) != text
        ):
            raise ValueError("exact source seal/retention encoding required")
        records = payload["records"]
        if type(records) is not list or len(records) != seal.frame_count:
            raise ValueError("complete source count required; no sampling/adoption")
        bindings = []
        for record in records:
            if (
                type(record) is not dict
                or set(record) != {"frame", "binding_sha256", "derived_capture"}
                or len(canonical(record).encode("utf-8")) > MAX_RECORD_BYTES
            ):
                raise ValueError("exact bounded source record required")
            # JSON-mode strict validation admits JSON tuples/datetimes without
            # allowing Python coercion, then demands exact regenerated encoding.
            frame = RecordedTopNBookFrameV2.model_validate_json(canonical(record["frame"]), strict=True)
            binding = NativeBookCapture(frame, seal.policy)
            if canonical(_record(binding)) != canonical(record):
                raise ValueError("retained raw/native/derived binding conflict")
            bindings.append(binding)
        reconstructed, prefix = _records(tuple(b.frame for b in bindings), seal.policy)
        if (
            digest(reconstructed) != seal.records_sha256
            or prefix.tape_id != seal.tape_id
            or prefix.stream_epoch != seal.stream_epoch
            or prefix.head_sha256 != seal.native_head_sha256
            or bindings[-1].frame.persisted_at_ms > receipt.retained_at_ms
        ):
            raise ValueError("complete root/head/content commitment conflict")
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("source file must be bounded strict UTF-8 JSON") from exc
    return RetainedBookBundle(seal, receipt, tuple(bindings))


def _admit(
    bundle: RetainedBookBundle,
    *,
    sequence: int,
    expected_binding_sha256: str,
    asof_ms: int,
    after_ms: int,
) -> DurableBookCapture:
    _count(sequence)
    _sha(expected_binding_sha256)
    _clock(asof_ms)
    _clock(after_ms)
    if after_ms > asof_ms or sequence > len(bundle.bindings):
        raise ValueError("exact retained sequence and causal admission boundary required")
    binding = bundle.bindings[sequence - 1]
    capture = binding.capture
    quote = capture.quote
    if binding.sha256 != expected_binding_sha256:
        raise ValueError("retained sequence differs from explicitly expected binding")
    if quote.event_ms < after_ms or quote.captured_ms > asof_ms:
        raise ValueError("retained capture unavailable at the causal boundary")
    if asof_ms - quote.event_ms > quote.ttl_ms:
        raise ValueError("retained event is stale; modern retention cannot renew its TTL")
    visible = tuple(b.frame for b in bundle.bindings if b.frame.persisted_at_ms <= asof_ms)
    prefix = audit_book_prefix(
        visible,
        bundle.seal.policy,
        tape_id=bundle.seal.tape_id,
        stream_epoch=bundle.seal.stream_epoch,
        expected_head_sha256=visible[-1].frame_sha256,
        asof_ms=asof_ms,
    )
    return DurableBookCapture(binding, prefix, bundle.retention)


def admit_retained_book_capture(
    path: Path,
    seal: BookBundleSeal,
    receipt: RetentionReceipt,
    *,
    sequence: int,
    expected_binding_sha256: str,
    asof_ms: int,
    after_ms: int,
) -> DurableBookCapture:
    """Explicit exact capture lookup; never pick a convenient replacement quote."""
    return _admit(
        open_book_bundle(path, seal, receipt),
        sequence=sequence,
        expected_binding_sha256=expected_binding_sha256,
        asof_ms=asof_ms,
        after_ms=after_ms,
    )


def audit_retained_journal_sources(
    *,
    journal_path: Path,
    journal_seal: JournalSeal,
    book_path: Path,
    book_seal: BookBundleSeal,
    retention: RetentionReceipt,
    expected_journal_head_sha256: str,
    expected_journal_event_count: int,
) -> BookSourceAudit:
    """Separate source reconciliation, not a mutation of the old journal schema.

    Null quotes remain missing. Ambiguous generic quotes fail closed; the
    journal cannot retroactively invent a binding to one of several originals.
    """
    _sha(expected_journal_head_sha256)
    if type(expected_journal_event_count) is not int or not 0 <= expected_journal_event_count <= 128 * (
        MAX_OBSERVATIONS + 1
    ):
        raise ValueError("bounded caller-pinned journal event count required")
    bundle = open_book_bundle(book_path, book_seal, retention)
    snapshot = HypothesisJournal.open(journal_path, journal_seal).snapshot()
    if (
        snapshot.head_sha256 != expected_journal_head_sha256
        or snapshot.event_count != expected_journal_event_count
    ):
        raise ValueError("journal differs from independently caller-pinned head/count")
    if journal_seal.source_set_sha256 != bundle.seal.sha256:
        raise ValueError("journal source set must freeze the retained bundle seal")
    for arm in journal_seal.arms:
        if (
            arm.policy.quote_source_id != bundle.seal.policy.quote_source_id
            or arm.policy.evidence_kind != bundle.seal.policy.evidence_kind
        ):
            raise ValueError("journal arm differs from retained native source policy")
    by_quote: dict[str, list[NativeBookCapture]] = {}
    for binding in bundle.bindings:
        by_quote.setdefault(binding.capture.quote.sha256, []).append(binding)
    matches = []
    for hypothesis in snapshot.hypotheses:
        for observation in hypothesis.observations:
            if observation.quote is None:
                continue
            originals = by_quote.get(observation.quote.sha256, [])
            if len(originals) != 1:
                raise ValueError("journal quote lacks a unique retained native original")
            binding = originals[0]
            checked = _admit(
                bundle,
                sequence=binding.frame.tape_sequence,
                expected_binding_sha256=binding.sha256,
                asof_ms=observation.market.observed_ms,
                after_ms=observation.market.candle.close_time_ms,
            )
            quote = admit_capture(
                hypothesis.plan,
                binding.capture,
                observation.market.observed_ms,
                observation.market.candle.close_time_ms,
            )
            if asdict(quote) != asdict(observation.quote):
                raise ValueError("journal quote fields differ from retained native original")
            matches.append(
                BookSourceMatch(
                    hypothesis.arm_id,
                    hypothesis.plan.template.intent_id,
                    observation.market.candle.open_time_ms,
                    binding.frame.tape_sequence,
                    binding.sha256,
                    checked.prefix.sha256,
                )
            )
    return BookSourceAudit(
        snapshot.head_sha256,
        snapshot.event_count,
        bundle.seal.sha256,
        bundle.retention.sha256,
        tuple(matches),
    )
