"""Exact legacy-export compatibility, not a new original-source audit.

Only a caller's independently retained export/wheel/script/receipt commitments
admit this transfer. Legacy audit assertions remain attributed to the old
auditor; current code checks transport bytes and unchanged DTO compatibility.
No capture, source repair, bundle reseal, network, historical clock, full tick
coverage, news/macro admission or economic/trading authority is provided.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from kairos_execution.simulation.models import AcceptedBookFrame

from .historical_context import _json, _sha, canonical, digest
from .sim_book_tape import BoundBookFrame, PublicBookTape

SCHEMA = "kairos.development.public-book-transfer.v1"
MAX_TRANSFER_BYTES = 32 * 1024 * 1024
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_IMPLEMENTATION_BYTES = 65_536
MAX_FRAMES = 6_000
SEGMENT_FRAMES = 256
MAX_GAP_MS = 5_000
SYMBOLS = tuple(sorted(("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")))
CAPTURE_LIMITATIONS = (
    "FORWARD_LOCAL_OBSERVATION_NOT_HISTORICAL_AVAILABILITY",
    "SAMPLED_TOP_TEN_NOT_EVERY_MARKET_TICK_OR_FULL_DEPTH",
    "LOCAL_UTC_NOT_INDEPENDENT_CLOCK_ATTESTATION",
    "TLS_TRANSPORT_NOT_EXCHANGE_SIGNED_SOURCE",
    "NO_NEWS_MACRO_BAR_SOURCE_SET_OR_EXECUTION_ADMISSION",
    "NO_RISK_TRADING_OR_READINESS_AUTHORITY",
    "BOUNDED_APPLICATION_TEXT_DELIVERY_NOT_ALL_WIRE_FRAMES",
)
LIMITATIONS = (
    "LEGACY_AUDITOR_RESULT_TRANSFERRED_NOT_CURRENT_ORIGINAL_AUDIT",
    "EXTERNAL_EXPORT_COMMITMENT_NOT_PUBLISHER_AUTHENTICATION",
    "ORIGINAL_EVENT_RECEIVE_PERSIST_CLOCKS_NEVER_RETIMED",
    "NO_HISTORICAL_AVAILABILITY_OR_FULL_TICK_COVERAGE",
    "NO_NEWS_MACRO_BAR_HYPOTHESIS_SOURCE_ADMISSION",
    "LATER_CONTEXT_OR_MODEL_COMPLETION_CANNOT_REFRESH_OLD_QUOTES",
    "EXACT_NATIVE_CREATION_CUT_STILL_REQUIRES_ALREADY_AVAILABLE_EVIDENCE",
    "NO_RISK_TRADING_READINESS_ALPHA_OR_QUALIFIED_ECONOMICS",
)
SOURCE_KEYS = ("loader", "auditor", "kernel_bridge", "kernel_models")
SOURCE_PATHS = {
    "loader": "adaptive_replay/sim_book_tape.py",
    "auditor": "adaptive_replay/public_book_capture.py",
    "kernel_bridge": "kairos_execution/simulation/bridge.py",
    "kernel_models": "kairos_execution/simulation/models.py",
}
_ENVELOPE = {"schema", "producer", "receipt_utf8", "legacy_audit", "tape", "limitations"}
_RECEIPT = {
    "schema",
    "capture_id",
    "epoch",
    "plan_sha256",
    "source_sha256",
    "state",
    "reason",
    "started_ms",
    "ended_ms",
    "elapsed_monotonic_ms",
    "observed_messages",
    "admitted_frames",
    "raw_payload_bytes",
    "raw_file_sha256",
    "raw_head_sha256",
    "symbol_counts",
    "first_received_ms",
    "maximum_observed_gap_ms",
    "terminal_gap_ms",
    "segments",
    "transport",
    "observed_stream_check",
    "market_tick_completeness",
    "source_set_admitted",
    "risk_authority",
    "limitations",
}
_SEGMENT = {
    "ordinal",
    "name",
    "global_first",
    "global_last",
    "previous_segment_sha256",
    "raw_prefix_head_sha256",
    "observed_prefix_head_at_flush_sha256",
    "seal",
    "retention",
}
_SEAL = {
    "bundle_id",
    "tape_id",
    "stream_epoch",
    "policy",
    "frame_count",
    "native_head_sha256",
    "records_sha256",
    "implementation_sha256",
}
_RETENTION = {
    "seal_sha256",
    "file_sha256",
    "retained_at_ms",
    "frame_count",
    "native_head_sha256",
    "risk_authority",
    "coverage_authority",
    "clock_authority",
}
_AUDIT = {
    "state",
    "receipt_sha256",
    "observed_messages",
    "symbol_counts",
    "segments",
    "market_tick_completeness",
    "source_set_admitted",
    "risk_authority",
}
_TAPE = {"receipt_sha256", "source_sha256", "tape_id", "epoch", "quote_source_id", "sha256", "frames"}
_FRAME = {
    "frame_utf8",
    "frame_sha256",
    "receipt_sha256",
    "native_frame_sha256",
    "raw_record_sha256",
    "segment_ordinal",
    "segment_sequence",
    "mapping_sha256",
}


class TransferError(ValueError):
    """Byte, version, schema or compatibility denial; never repaired in place."""


def _object(value, fields, label):
    if type(value) is not dict or set(value) != fields:
        raise TransferError(f"exact {label} fields required")
    return value


def _integer(value, *, minimum=0, maximum=2**63 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise TransferError("bounded exact integer required")
    return value


def _name(value):
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", value) is None:
        raise TransferError("bounded canonical identity required")


def _canonical_document(text, maximum, label):
    if type(text) is not str or not 0 < len(text.encode("utf-8")) <= maximum:
        raise TransferError(f"bounded {label} bytes required")
    value = _json(text)
    if canonical(value) != text:
        raise TransferError(f"exact canonical {label} bytes required")
    return value


def _safe_path(path):
    path = Path(path).absolute()
    if ".." in path.parts:
        raise TransferError("parent traversal prohibited")
    for entry in (*reversed(path.parents), path):
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise TransferError("transfer path cannot traverse symlinks/reparse points")
        if entry != path and not stat.S_ISDIR(info.st_mode):
            raise TransferError("regular directory ancestry required")
        if entry == path and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise TransferError("unaliased regular transfer file required")
    return path


def _snapshot(path):
    path = _safe_path(path)
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > MAX_TRANSFER_BYTES or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise TransferError("transfer exceeds byte bound or aliases another file")
        raw = stream.read(MAX_TRANSFER_BYTES + 1)
        after = os.fstat(stream.fileno())
    current = _safe_path(path).stat()

    def stable(info):
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink

    if (
        stable(before) != stable(after)
        or stable(after) != stable(current)
        or not 0 < len(raw) <= MAX_TRANSFER_BYTES
    ):
        raise TransferError("transfer changed while taking the immutable byte snapshot")
    return raw


@dataclass(frozen=True)
class TransferCommitment:
    export_sha256: str
    legacy_wheel_sha256: str
    exporter_script_sha256: str
    legacy_implementation_sha256: str
    receipt_sha256: str

    def __post_init__(self):
        for value in self.__dict__.values():
            _sha(value)


@dataclass(frozen=True)
class ImportedPublicBookTransfer:
    tape: PublicBookTape
    commitment: TransferCommitment
    producer_sources_sha256: str
    validation_state: str = "PASS_LEGACY_EXPORT_BYTE_CONSISTENCY_ONLY"
    original_audit_owner: str = "LEGACY_PINNED_ENVIRONMENT"
    source_authentication: bool = False
    market_tick_completeness: str = "UNKNOWN_NOT_CLAIMED"
    risk_authority: str = "NONE"

    def __post_init__(self):
        if type(self.tape) is not PublicBookTape or type(self.commitment) is not TransferCommitment:
            raise TransferError("exact compatible tape and external commitment required")
        _sha(self.producer_sources_sha256)
        if (
            self.tape.receipt_sha256 != self.commitment.receipt_sha256
            or self.validation_state != "PASS_LEGACY_EXPORT_BYTE_CONSISTENCY_ONLY"
            or self.original_audit_owner != "LEGACY_PINNED_ENVIRONMENT"
            or self.source_authentication is not False
            or self.market_tick_completeness != "UNKNOWN_NOT_CLAIMED"
            or self.risk_authority != "NONE"
        ):
            raise TransferError("legacy transfer cannot upgrade source or economic authority")

    @property
    def source_id(self):
        return f"legacy-public-transfer:{self.commitment.export_sha256}"


def _producer(value, commitment):
    producer = _object(
        value,
        {
            "wheel_sha256",
            "exporter_script_sha256",
            "implementation_utf8",
            "implementation_sha256",
            "sources",
            "python_version",
            "isolated_private_environment",
        },
        "producer",
    )
    if (
        producer["wheel_sha256"] != commitment.legacy_wheel_sha256
        or producer["exporter_script_sha256"] != commitment.exporter_script_sha256
        or producer["implementation_sha256"] != commitment.legacy_implementation_sha256
        or producer["isolated_private_environment"] is not True
    ):
        raise TransferError("legacy wheel/script/implementation/version commitment conflict")
    if (
        type(producer["python_version"]) is not str
        or re.fullmatch(r"3\.(?:11|14)\.\d+", producer["python_version"]) is None
    ):
        raise TransferError("explicit supported legacy Python version required")
    implementation = _canonical_document(
        producer["implementation_utf8"], MAX_IMPLEMENTATION_BYTES, "implementation"
    )
    _object(implementation, {"schema", "sources", "mechanics", "planning", "capabilities"}, "implementation")
    if digest(implementation) != commitment.legacy_implementation_sha256:
        raise TransferError("legacy implementation bytes differ from expected commitment")
    if implementation["schema"] != "kairos.development.hypothesis-journal.v1":
        raise TransferError("unsupported legacy implementation contract version")
    manifest = implementation["sources"]
    if type(manifest) is not dict or not 1 <= len(manifest) <= 1536:
        raise TransferError("bounded exact legacy source manifest required")
    for name, value in manifest.items():
        if (
            type(name) is not str
            or len(name) > 256
            or re.fullmatch(
                r"(?:adaptive_replay|kairos_strategy|kairos_core)/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.py",
                name,
            )
            is None
        ):
            raise TransferError("invalid legacy implementation source identity")
        _sha(value)
    sources = _object(producer["sources"], set(SOURCE_KEYS), "imported producer sources")
    for key in SOURCE_KEYS:
        item = _object(sources[key], {"path", "sha256"}, "producer source")
        if item["path"] != SOURCE_PATHS[key]:
            raise TransferError("exact logical source paths required; private absolute paths prohibited")
        _sha(item["sha256"])
    if sources["loader"]["sha256"] != manifest.get("adaptive_replay/sim_book_tape.py") or sources["auditor"][
        "sha256"
    ] != manifest.get("adaptive_replay/public_book_capture.py"):
        raise TransferError("actual legacy loader/auditor differs from its implementation manifest")
    return sources


def _receipt(raw, commitment, producer):
    receipt = _object(_canonical_document(raw, MAX_RECEIPT_BYTES, "receipt"), _RECEIPT, "receipt")
    if hashlib.sha256(raw.encode("utf-8")).hexdigest() != commitment.receipt_sha256:
        raise TransferError("exact original receipt bytes differ from external commitment")
    for key in ("capture_id", "epoch", "reason"):
        _name(receipt[key])
    for key in ("plan_sha256", "source_sha256", "raw_file_sha256", "raw_head_sha256"):
        _sha(receipt[key])
    if (
        receipt["schema"] != "kairos.development.public-book-capture.v1"
        or receipt["state"] != "CAPTURED"
        or receipt["observed_stream_check"] != "PASS"
        or receipt["market_tick_completeness"] != "UNKNOWN_NOT_CLAIMED"
        or receipt["source_set_admitted"] is not False
        or receipt["risk_authority"] != "NONE"
        or receipt["limitations"] != list(CAPTURE_LIMITATIONS)
        or receipt["source_sha256"] != producer["auditor"]["sha256"]
    ):
        raise TransferError("capture version/state/authority/source conflict")
    for key in (
        "started_ms",
        "ended_ms",
        "elapsed_monotonic_ms",
        "observed_messages",
        "admitted_frames",
        "raw_payload_bytes",
    ):
        _integer(receipt[key])
    count = _integer(receipt["admitted_frames"], minimum=1, maximum=MAX_FRAMES)
    if (
        receipt["observed_messages"] != count
        or receipt["ended_ms"] < receipt["started_ms"]
        or not 1000 <= receipt["elapsed_monotonic_ms"] <= 135_000
    ):
        raise TransferError("original capture count/duration conflict")
    if abs(receipt["ended_ms"] - receipt["started_ms"] - receipt["elapsed_monotonic_ms"]) > 1000:
        raise TransferError("original UTC/monotonic duration conflict")
    if not 0 < receipt["raw_payload_bytes"] <= 16 * 1024 * 1024:
        raise TransferError("original raw payload bound exceeded")
    for key in ("symbol_counts", "first_received_ms", "maximum_observed_gap_ms", "terminal_gap_ms"):
        _object(receipt[key], set(SYMBOLS), key)
        for value in receipt[key].values():
            _integer(value)
    if sum(receipt["symbol_counts"].values()) != count or any(
        n < 1 for n in receipt["symbol_counts"].values()
    ):
        raise TransferError("full five-symbol denominator required")
    transport = _object(
        receipt["transport"],
        {"endpoint", "attempts", "retries", "redirects", "tls_default_validation", "handshake_completed"},
        "transport",
    )
    endpoint = "wss://fstream.binance.com/public/stream?streams=" + "/".join(
        f"{s.lower()}@depth10@100ms" for s in SYMBOLS
    )
    if (
        transport["endpoint"] != endpoint
        or transport["tls_default_validation"] is not True
        or transport["handshake_completed"] is not True
    ):
        raise TransferError("original transport contract conflict")
    for name, expected in (("attempts", 1), ("retries", 0), ("redirects", 0)):
        if _integer(transport[name]) != expected:
            raise TransferError("original transport attempts/redirects/retries conflict")
    return receipt


def _segments(receipt, commitment):
    segments = receipt["segments"]
    if type(segments) is not list or not 1 <= len(segments) <= 24:
        raise TransferError("bounded full segment manifest required")
    prior, cursor, quote_policy = None, 0, None
    for ordinal, segment in enumerate(segments, 1):
        _object(segment, _SEGMENT, "segment")
        seal = _object(segment["seal"], _SEAL, "original seal")
        retention = _object(segment["retention"], _RETENTION, "original retention")
        policy = _object(
            seal["policy"], {"profile_id", "source_id", "ttl_ms", "evidence_kind"}, "native policy"
        )
        if (
            policy["profile_id"] != "BINANCE_UM_COMBINED_DEPTH10_100MS_MIGRATED_V1"
            or policy["source_id"] != "binance-um-public-depth10-100ms"
            or _integer(policy["ttl_ms"]) != MAX_GAP_MS
            or policy["evidence_kind"] != "CALLER_ATTESTED_POINT_IN_TIME"
        ):
            raise TransferError("unsupported original native source policy")
        if quote_policy is not None and quote_policy != policy:
            raise TransferError("native policy changed between segments")
        quote_policy = policy
        n = _integer(seal["frame_count"], minimum=1, maximum=SEGMENT_FRAMES)
        if ordinal != len(segments) and n != SEGMENT_FRAMES:
            raise TransferError("nonterminal original segment was truncated")
        if (
            _integer(segment["ordinal"], minimum=1) != ordinal
            or segment["name"] != f"segment-{ordinal:04d}.native-book.research.json"
            or _integer(segment["global_first"], minimum=1) != cursor + 1
            or _integer(segment["global_last"], minimum=1) != cursor + n
            or segment["previous_segment_sha256"] != prior
            or seal["bundle_id"] != f"{receipt['capture_id']}:{ordinal:04d}"
            or seal["tape_id"] != seal["bundle_id"]
            or seal["stream_epoch"] != receipt["epoch"]
            or seal["implementation_sha256"] != commitment.legacy_implementation_sha256
        ):
            raise TransferError("original segment chain/ordinal/epoch/implementation conflict")
        for value in (
            seal["native_head_sha256"],
            seal["records_sha256"],
            segment["raw_prefix_head_sha256"],
            retention["file_sha256"],
        ):
            _sha(value)
        if (
            segment["observed_prefix_head_at_flush_sha256"] != segment["raw_prefix_head_sha256"]
            or retention["seal_sha256"]
            != digest({"schema": "kairos.development.retained-native-book.v1", "seal": seal})
            or _integer(retention["frame_count"], minimum=1) != n
            or retention["native_head_sha256"] != seal["native_head_sha256"]
            or retention["risk_authority"] != "NONE"
            or retention["coverage_authority"] != "STRUCTURAL_PREFIX_ONLY_NOT_CONTINUOUS_MARKET_COVERAGE"
            or retention["clock_authority"] != "CALLER_ATTESTED_NATIVE_TIMES_NOT_AUTHENTICATED"
        ):
            raise TransferError("original retention bytes/authority conflict")
        _integer(retention["retained_at_ms"])
        prior, cursor = digest(segment), cursor + n
    if cursor != receipt["admitted_frames"]:
        raise TransferError("segments do not cover complete original denominator")
    return segments


def import_public_book_transfer(path: Path, *, commitment: TransferCommitment) -> ImportedPublicBookTransfer:
    """Read one exact snapshot; never call current or legacy original auditors.

    The commitment must come from the independently observed legacy export run,
    not from this file/directory during admission. Owner-controlled full rewrites
    of both evidence and independent commitments are outside this hash boundary.
    """
    if type(commitment) is not TransferCommitment:
        raise TransferError("externally retained typed transfer commitment required")
    commitment.__post_init__()
    raw = _snapshot(path)
    if hashlib.sha256(raw).hexdigest() != commitment.export_sha256:
        raise TransferError("transfer byte snapshot differs from external export commitment")
    value = _object(_json(raw), _ENVELOPE, "transfer")
    if (
        canonical(value).encode("utf-8") != raw
        or value["schema"] != SCHEMA
        or value["limitations"] != list(LIMITATIONS)
    ):
        raise TransferError("transfer schema/canonical bytes/authority limitations conflict")
    sources = _producer(value["producer"], commitment)
    receipt = _receipt(value["receipt_utf8"], commitment, sources)
    segments = _segments(receipt, commitment)
    audit = _object(value["legacy_audit"], _AUDIT, "legacy audit result")
    _object(audit["symbol_counts"], set(SYMBOLS), "legacy audit symbol counts")
    for count in audit["symbol_counts"].values():
        _integer(count, minimum=1, maximum=MAX_FRAMES)
    if (
        audit["state"] != "PASS_OBSERVED_SOURCE_CONSISTENCY_ONLY"
        or audit["receipt_sha256"] != commitment.receipt_sha256
        or type(audit["observed_messages"]) is not int
        or audit["observed_messages"] != receipt["admitted_frames"]
        or audit["symbol_counts"] != receipt["symbol_counts"]
        or type(audit["segments"]) is not int
        or audit["segments"] != len(segments)
        or audit["market_tick_completeness"] != "UNKNOWN_NOT_CLAIMED"
        or audit["source_set_admitted"] is not False
        or audit["risk_authority"] != "NONE"
    ):
        raise TransferError("legacy audit assertion differs from original capture/authority")
    tape = _object(value["tape"], _TAPE, "tape")
    for name in ("tape_id", "epoch", "quote_source_id"):
        _name(tape[name])
    _sha(tape["sha256"])
    if (
        tape["receipt_sha256"] != commitment.receipt_sha256
        or tape["source_sha256"] != receipt["source_sha256"]
        or tape["tape_id"] != f"public-native:{receipt['capture_id']}"
        or tape["epoch"] != receipt["epoch"]
        or re.fullmatch(r"native-book:[0-9a-f]{64}", tape["quote_source_id"]) is None
    ):
        raise TransferError("original tape/source/epoch/quote identity conflict")
    rows = tape["frames"]
    if type(rows) is not list or len(rows) != receipt["admitted_frames"]:
        raise TransferError("complete original frame roster required; no sampling")
    frames, counts, first, last, gaps, native_seen, raw_seen = (
        [],
        dict.fromkeys(SYMBOLS, 0),
        {},
        {},
        dict.fromkeys(SYMBOLS, 0),
        set(),
        set(),
    )
    for sequence, row in enumerate(rows, 1):
        _object(row, _FRAME, "frame mapping")
        text = row["frame_utf8"]
        frame_doc = _object(
            _canonical_document(text, 16_384, "kernel frame"),
            set(AcceptedBookFrame.model_fields),
            "kernel frame",
        )
        frame = AcceptedBookFrame.model_validate_json(text)
        if frame.canonical_bytes() != text.encode("utf-8") or frame.fingerprint() != row["frame_sha256"]:
            raise TransferError("current kernel canonical contract differs; no normalization/adoption")
        if (
            frame.sequence != sequence
            or frame.tape_id != tape["tape_id"]
            or frame.stream_epoch != tape["epoch"]
            or frame.continuity != "ADMITTED"
            or not 1 <= len(frame.bids) <= 10
            or not 1 <= len(frame.asks) <= 10
            or not receipt["started_ms"]
            <= frame.received_at_ms
            <= frame.persisted_at_ms
            <= receipt["ended_ms"]
            or frame.received_at_ms - frame.exchange_at_ms > MAX_GAP_MS
        ):
            raise TransferError("original frame clock/order/top-ten/continuity conflict")
        # Force exact declared strings, not JSON numeric or added default fields.
        if any(
            type(level[k]) is not str
            for side in ("bids", "asks")
            for level in frame_doc[side]
            for k in ("price", "quantity")
        ):
            raise TransferError("exact legacy canonical Decimal strings required")
        ordinal = _integer(row["segment_ordinal"], minimum=1, maximum=len(segments))
        segment = segments[ordinal - 1]
        if (
            not segment["global_first"] <= sequence <= segment["global_last"]
            or _integer(row["segment_sequence"], minimum=1) != sequence - segment["global_first"] + 1
        ):
            raise TransferError("frame mapping belongs to different original segment")
        bound = BoundBookFrame(
            frame,
            row["receipt_sha256"],
            row["native_frame_sha256"],
            row["raw_record_sha256"],
            ordinal,
            row["segment_sequence"],
        )
        if bound.receipt_sha256 != commitment.receipt_sha256 or bound.mapping_sha256 != row["mapping_sha256"]:
            raise TransferError("exact original mapping commitment conflict")
        if bound.native_frame_sha256 in native_seen or bound.raw_record_sha256 in raw_seen:
            raise TransferError("duplicated original native/raw mapping member")
        native_seen.add(bound.native_frame_sha256)
        raw_seen.add(bound.raw_record_sha256)
        if sequence == segment["global_last"] and (
            bound.native_frame_sha256 != segment["seal"]["native_head_sha256"]
            or bound.raw_record_sha256 != segment["raw_prefix_head_sha256"]
        ):
            raise TransferError("mapping terminal native/raw heads differ from original segment")
        s = frame.symbol
        counts[s] += 1
        first.setdefault(s, frame.received_at_ms)
        if s in last:
            gaps[s] = max(
                gaps[s],
                frame.exchange_at_ms - last[s].exchange_at_ms,
                frame.received_at_ms - last[s].received_at_ms,
            )
        last[s] = frame
        frames.append(bound)
    if (
        counts != receipt["symbol_counts"]
        or first != receipt["first_received_ms"]
        or gaps != receipt["maximum_observed_gap_ms"]
        or {s: receipt["ended_ms"] - f.received_at_ms for s, f in last.items()} != receipt["terminal_gap_ms"]
        or any(t - receipt["started_ms"] > MAX_GAP_MS for t in first.values())
        or any(g > MAX_GAP_MS for g in receipt["terminal_gap_ms"].values())
        or frames[-1].raw_record_sha256 != receipt["raw_head_sha256"]
    ):
        raise TransferError("all original symbol/boundary/raw coverage commitments must reconcile")
    imported = PublicBookTape(
        commitment.receipt_sha256,
        tape["source_sha256"],
        tape["tape_id"],
        tape["epoch"],
        tape["quote_source_id"],
        tuple(frames),
    )
    if imported.sha256 != tape["sha256"]:
        raise TransferError("complete legacy tape hash differs from current compatible reconstruction")
    return ImportedPublicBookTransfer(imported, commitment, digest(sources))
