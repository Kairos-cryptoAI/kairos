"""Authenticated lossless block cursor over already sealed archive segments.

One create-only derivation scans the source, without copying or sampling its
CSV. Normal reads hash bounded row-boundary blocks, not an entire
segment per row. Open performs a full source audit; reads validate active
blocks and physical source fences. Inactive blocks are checked when reached.
The cursor is not durable by itself: a financial consumer must atomically
persist batch.after with *all* resulting account/native/liquidity effects.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .archive_market_clock_v3 import ArchiveBBOQuoteV3, ArchiveMarketClockV3, archive_quote_v3
from .bookticker_archive_stream_v3 import (
    HEADER,
    MAX_MANIFEST_BYTES,
    BookTickerArchiveRowV3,
    BookTickerArchiveStreamV3,
    _canonical,
    _exact_keys,
    _identity,
    _integer,
    _open_regular,
    _pairs,
    _parse_row,
    _regular_nofollow,
    _safe_path,
    _sha,
    open_bookticker_archive_stream_v3,
)

SCHEMA = "kairos.research.archive-batch-index.v3"
MAX_BLOCK_BYTES = 4 * 1024 * 1024
MAX_BATCH_BYTES = 4 * 1024 * 1024
MAX_BATCH_ROWS = 1000
MAX_BLOCKS = 100_000
MAX_INDEX_BYTES = 64 * 1024 * 1024
MAX_INDEX_LINE_BYTES = 1024
MAX_INDEX_MANIFEST_BYTES = 2 * 1024 * 1024


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _genesis(source_sha: str) -> str:
    return _digest([SCHEMA, source_sha, "ORIGINAL_ROWS"])


def _advance(prefix: str, row: int, raw: bytes) -> str:
    return _digest([prefix, row, hashlib.sha256(raw).hexdigest()])


def _deadline_check(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise TimeoutError("archive block operation exceeded explicit timeout")


@dataclass(frozen=True, slots=True)
class ArchiveBatchLimitsV3:
    """Bounded metadata/buffers; source row/byte ceilings remain source-sealed."""

    max_block_bytes: int = 1024 * 1024
    max_batch_rows: int = 500
    max_batch_bytes: int = 2 * 1024 * 1024
    max_blocks: int = 100_000
    max_index_bytes: int = 64 * 1024 * 1024
    timeout_seconds: int = 1800

    def __post_init__(self) -> None:
        caps = {
            "max_block_bytes": MAX_BLOCK_BYTES,
            "max_batch_rows": MAX_BATCH_ROWS,
            "max_batch_bytes": MAX_BATCH_BYTES,
            "max_blocks": MAX_BLOCKS,
            "max_index_bytes": MAX_INDEX_BYTES,
            "timeout_seconds": 86_400,
        }
        for name, cap in caps.items():
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= cap:
                raise ValueError(f"{name} exceeds explicit bounded profile")


@dataclass(frozen=True, slots=True)
class _Block:
    segment: str
    offset: int
    byte_count: int
    first_row: int
    row_count: int
    sha256: str
    prefix_before: str
    prefix_after: str
    first_update_id: int
    last_update_id: int
    first_transaction_ms: int
    last_transaction_ms: int
    first_event_ms: int
    last_event_ms: int


@dataclass(frozen=True, slots=True)
class ArchiveCursorCheckpointV3:
    """Independent retained source/model fence; never adopt a latest cursor."""

    index_manifest_sha256: str
    source_manifest_sha256: str
    clock_policy_sha256: str
    next_row: int
    prefix_sha256: str

    def __post_init__(self) -> None:
        for value in (
            self.index_manifest_sha256,
            self.source_manifest_sha256,
            self.clock_policy_sha256,
            self.prefix_sha256,
        ):
            _sha(value, "cursor SHA256")
        _integer(self.next_row, "cursor next row")


@dataclass(frozen=True, slots=True)
class ArchiveBatchV3:
    """Every original row in one contiguous interval plus exact model quotes."""

    before: ArchiveCursorCheckpointV3
    after: ArchiveCursorCheckpointV3
    rows: tuple[BookTickerArchiveRowV3, ...]
    quotes: tuple[ArchiveBBOQuoteV3, ...]
    raw_byte_count: int

    @property
    def sha256(self) -> str:
        return _digest(
            {
                "before": asdict(self.before),
                "after": asdict(self.after),
                "row_sha256": [hashlib.sha256(row.raw_csv_line).hexdigest() for row in self.rows],
                "raw_byte_count": self.raw_byte_count,
            }
        )


def _source_identities(root: Path, manifest: dict) -> dict[str, list[int]]:
    names = ["manifest.json", "sparse-index.jsonl"] + [s["name"] for s in manifest["segments"]]
    return {name: list(_identity(_regular_nofollow(root / name))) for name in names}


def _read_json(path: Path, cap: int, expected_sha: str) -> tuple[dict, tuple[int, ...]]:
    _sha(expected_sha, "independent manifest SHA256")
    stream, metadata = _open_regular(path)
    with stream:
        if metadata.st_size > cap:
            raise ValueError("manifest exceeds explicit byte bound")
        raw = stream.read(cap + 1)
        if _identity(os.fstat(stream.fileno())) != _identity(metadata):
            raise ValueError("manifest changed during read")
    if _identity(_regular_nofollow(path)) != _identity(metadata):
        raise ValueError("manifest path changed during read")
    if len(raw) > cap or hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("independent manifest hash mismatch")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
        if type(value) is not dict or _canonical(value) + b"\n" != raw:
            raise ValueError
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("invalid canonical manifest") from None
    return value, _identity(metadata)


def build_archive_batch_index_v3(
    source: BookTickerArchiveStreamV3,
    output_dir: str | Path,
    *,
    expected_source_manifest_sha256: str,
    limits: ArchiveBatchLimitsV3,
) -> ArchiveBatchIndexV3:
    """Create a new index only after whole before/after source verification.

    Failure leaves an unaccepted create-only directory, not a partial usable
    index. Original source files are opened read-only and never modified.
    """
    if type(source) is not BookTickerArchiveStreamV3 or type(limits) is not ArchiveBatchLimitsV3:
        raise ValueError("exact verified archive stream and explicit limits required")
    if source.manifest_sha256 != expected_source_manifest_sha256:
        raise ValueError("source is not the independently pinned stream")
    started = time.monotonic()
    deadline = started + limits.timeout_seconds
    root = _safe_path(Path(output_dir))
    root.mkdir(parents=False, exist_ok=False)
    original_manifest = source.manifest
    before = _source_identities(source.root, original_manifest)
    audited = open_bookticker_archive_stream_v3(
        source.root, expected_manifest_sha256=expected_source_manifest_sha256, _deadline=deadline
    )
    if before != _source_identities(source.root, audited.manifest):
        raise ValueError("source changed during initial full audit")
    manifest = audited.manifest
    max_line = manifest["limits"]["max_line_bytes"]
    row_index = index_bytes = block_count = 0
    prefix = _genesis(expected_source_manifest_sha256)
    csv_hash = hashlib.sha256()
    header = b""
    prior = (-1, -1, -1)
    with (root / "blocks.jsonl").open("xb") as index_file:
        index_hash = hashlib.sha256()

        def emit(
            segment: str,
            offset: int,
            raw_lines: list[bytes],
            rows: list[BookTickerArchiveRowV3],
            start_prefix: str,
        ) -> None:
            nonlocal block_count, index_bytes
            if not rows:
                return
            block_count += 1
            if block_count > limits.max_blocks:
                raise ValueError("block-count capacity exceeded without sampling")
            first, last = rows[0], rows[-1]
            block = _Block(
                segment,
                offset,
                sum(map(len, raw_lines)),
                first.row_index,
                len(rows),
                hashlib.sha256(b"".join(raw_lines)).hexdigest(),
                start_prefix,
                prefix,
                first.update_id,
                last.update_id,
                first.transaction_time_ms,
                last.transaction_time_ms,
                first.event_time_ms,
                last.event_time_ms,
            )
            raw = _canonical(asdict(block)) + b"\n"
            index_bytes += len(raw)
            if len(raw) > MAX_INDEX_LINE_BYTES or index_bytes > limits.max_index_bytes:
                raise ValueError("index byte capacity exceeded without sampling")
            index_file.write(raw)
            index_hash.update(raw)

        for segment in manifest["segments"]:
            _deadline_check(deadline)
            path = source.root / segment["name"]
            stream, metadata = _open_regular(path)
            segment_hash = hashlib.sha256()
            offset = segment_rows = 0
            block_offset = 0
            block_bytes = 0
            lines: list[bytes] = []
            rows: list[BookTickerArchiveRowV3] = []
            start_prefix = prefix
            with stream:
                while True:
                    _deadline_check(deadline)
                    raw = stream.readline(max_line + 1)
                    if not raw:
                        break
                    if len(raw) > max_line or not raw.endswith(b"\n"):
                        raise ValueError("invalid source row framing")
                    segment_hash.update(raw)
                    csv_hash.update(raw)
                    if segment["name"] == "segment-000001.csv" and offset == 0:
                        if raw not in (HEADER + b"\n", HEADER + b"\r\n"):
                            raise ValueError("exact native header required")
                        header = raw
                        offset += len(raw)
                        block_offset = offset
                        continue
                    if len(raw) > limits.max_block_bytes or len(raw) > limits.max_batch_bytes:
                        raise ValueError("one original row exceeds bounded block/batch profile")
                    if block_bytes + len(raw) > limits.max_block_bytes:
                        emit(segment["name"], block_offset, lines, rows, start_prefix)
                        lines, rows = [], []
                        block_bytes = 0
                        block_offset = offset
                        start_prefix = prefix
                    row = _parse_row(raw, source.symbol, source.transaction_day, row_index)
                    current = (row.update_id, row.transaction_time_ms, row.event_time_ms)
                    if current[0] <= prior[0] or current[1] < prior[1] or current[2] < prior[2]:
                        raise ValueError("source IDs/clocks regress")
                    prior = current
                    lines.append(raw)
                    rows.append(row)
                    block_bytes += len(raw)
                    prefix = _advance(prefix, row_index, raw)
                    row_index += 1
                    segment_rows += 1
                    offset += len(raw)
                emit(segment["name"], block_offset, lines, rows, start_prefix)
                if _identity(os.fstat(stream.fileno())) != tuple(before[segment["name"]]):
                    raise ValueError("source changed while deriving blocks")
            if (
                segment_hash.hexdigest() != segment["sha256"]
                or offset != segment["bytes"]
                or segment_rows != segment["rows"]
                or _identity(_regular_nofollow(path)) != tuple(before[segment["name"]])
            ):
                raise ValueError("original segment hash/identity/count mismatch")
        index_file.flush()
        os.fsync(index_file.fileno())
    if row_index != source.row_count or csv_hash.hexdigest() != manifest["csv"]["sha256"]:
        raise ValueError("lossless source CSV membership mismatch")
    # Rehash every source object after derivation, rather than trusting mtime.
    open_bookticker_archive_stream_v3(
        source.root, expected_manifest_sha256=expected_source_manifest_sha256, _deadline=deadline
    )
    after = _source_identities(source.root, manifest)
    if before != after:
        raise ValueError("whole source before/after physical identity mismatch")
    index_manifest = {
        "schema": SCHEMA,
        "source_root": str(source.root),
        "source_manifest_sha256": expected_source_manifest_sha256,
        "source_archive": manifest["archive"],
        "source_csv": manifest["csv"],
        "source_sparse_index": manifest["sparse_index"],
        "source_segments": manifest["segments"],
        "source_identities_before": before,
        "source_identities_after": after,
        "header_bytes": len(header),
        "header_sha256": hashlib.sha256(header).hexdigest(),
        "blocks": {
            "name": "blocks.jsonl",
            "count": block_count,
            "bytes": index_bytes,
            "sha256": index_hash.hexdigest(),
        },
        "limits": asdict(limits),
        "prefix_genesis": _genesis(expected_source_manifest_sha256),
        "prefix_final": prefix,
        "trading_authority": "NONE",
    }
    raw_manifest = _canonical(index_manifest) + b"\n"
    if len(raw_manifest) > MAX_INDEX_MANIFEST_BYTES:
        raise ValueError("index manifest exceeds bounded metadata capacity")
    _deadline_check(deadline)
    # Only the final marker accepts this create-only derivation.
    staged_manifest = root / "manifest.json.tmp"
    with staged_manifest.open("xb") as destination:
        destination.write(raw_manifest)
        destination.flush()
        os.fsync(destination.fileno())
    os.link(staged_manifest, root / "manifest.json")
    return open_archive_batch_index_v3(
        root,
        source.root,
        expected_index_manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
        expected_source_manifest_sha256=expected_source_manifest_sha256,
        _deadline=deadline,
    )


@dataclass(frozen=True, slots=True)
class ArchiveBatchIndexV3:
    root: Path
    source_root: Path
    manifest_sha256: str
    source_manifest_sha256: str
    symbol: str
    transaction_day: str
    row_count: int
    limits: ArchiveBatchLimitsV3
    blocks: tuple[_Block, ...]
    source_identities: tuple[tuple[str, tuple[int, ...]], ...]
    index_file_identity: tuple[int, ...]
    prefix_final: str
    max_line_bytes: int

    def cursor(
        self,
        *,
        clock: ArchiveMarketClockV3,
        expected_checkpoint: ArchiveCursorCheckpointV3 | None = None,
    ) -> ArchiveBatchCursorV3:
        return ArchiveBatchCursorV3(self, clock=clock, expected_checkpoint=expected_checkpoint)


def open_archive_batch_index_v3(
    index_dir: str | Path,
    source_root: str | Path,
    *,
    expected_index_manifest_sha256: str,
    expected_source_manifest_sha256: str,
    _deadline: float | None = None,
) -> ArchiveBatchIndexV3:
    """Whole source audit on open; independently pinned index, no migration."""
    started = time.monotonic()
    root, source_path = _safe_path(Path(index_dir)), _safe_path(Path(source_root))
    value, _ = _read_json(root / "manifest.json", MAX_INDEX_MANIFEST_BYTES, expected_index_manifest_sha256)
    _exact_keys(
        value,
        {
            "schema",
            "source_root",
            "source_manifest_sha256",
            "source_archive",
            "source_csv",
            "source_sparse_index",
            "source_segments",
            "source_identities_before",
            "source_identities_after",
            "header_bytes",
            "header_sha256",
            "blocks",
            "limits",
            "prefix_genesis",
            "prefix_final",
            "trading_authority",
        },
        "batch index manifest",
    )
    if (
        value["schema"] != SCHEMA
        or value["trading_authority"] != "NONE"
        or value["source_root"] != str(source_path)
        or value["source_manifest_sha256"] != expected_source_manifest_sha256
    ):
        raise ValueError("index source/namespace mismatch")
    _exact_keys(value["limits"], set(asdict(ArchiveBatchLimitsV3())), "batch limits")
    limits = ArchiveBatchLimitsV3(**value["limits"])
    deadline = _deadline if _deadline is not None else started + limits.timeout_seconds
    _deadline_check(deadline)
    source = open_bookticker_archive_stream_v3(
        source_path, expected_manifest_sha256=expected_source_manifest_sha256, _deadline=deadline
    )
    source_meta = source.manifest
    for name, key in (
        ("source_archive", "archive"),
        ("source_csv", "csv"),
        ("source_sparse_index", "sparse_index"),
        ("source_segments", "segments"),
    ):
        if value[name] != source_meta[key]:
            raise ValueError("index original source fingerprints mismatch")
    actual = _source_identities(source_path, source_meta)
    for key in ("source_identities_before", "source_identities_after"):
        identities = _exact_keys(value[key], set(actual), "source physical identities")
        if any(
            type(identity) is not list
            or len(identity) != 4
            or any(type(item) is not int or item < 0 for item in identity)
            for identity in identities.values()
        ):
            raise ValueError("invalid exact source physical identities")
    if value["source_identities_before"] != actual or value["source_identities_after"] != actual:
        raise ValueError("index source physical identity changed; no relocation adoption")
    if value["header_bytes"] not in (len(HEADER) + 1, len(HEADER) + 2):
        raise ValueError("invalid original header byte count")
    expected_header = HEADER + (b"\n" if value["header_bytes"] == len(HEADER) + 1 else b"\r\n")
    if value["header_sha256"] != hashlib.sha256(expected_header).hexdigest():
        raise ValueError("invalid original header hash")
    if value["prefix_genesis"] != _genesis(expected_source_manifest_sha256):
        raise ValueError("prefix genesis mismatch")
    _sha(value["prefix_final"], "final prefix SHA256")
    meta = _exact_keys(value["blocks"], {"name", "count", "bytes", "sha256"}, "block index")
    count, size = (
        _integer(meta["count"], "block count", minimum=1),
        _integer(meta["bytes"], "index bytes", minimum=1),
    )
    _sha(meta["sha256"], "block index SHA256")
    if meta["name"] != "blocks.jsonl" or count > limits.max_blocks or size > limits.max_index_bytes:
        raise ValueError("block index capacity/name mismatch")
    stream, opened = _open_regular(root / "blocks.jsonl")
    if opened.st_size != size:
        stream.close()
        raise ValueError("block index byte count mismatch")
    blocks = []
    digest = hashlib.sha256()
    fields = set(_Block.__dataclass_fields__)
    with stream:
        while raw := stream.readline(MAX_INDEX_LINE_BYTES + 1):
            _deadline_check(deadline)
            if len(raw) > MAX_INDEX_LINE_BYTES or len(blocks) >= count:
                raise ValueError("block index framing/count exceeded")
            doc = _exact_keys(json.loads(raw, object_pairs_hook=_pairs), fields, "block")
            if _canonical(doc) + b"\n" != raw:
                raise ValueError("noncanonical block metadata")
            for name in fields - {"segment", "sha256", "prefix_before", "prefix_after"}:
                _integer(doc[name], name)
            for name in ("sha256", "prefix_before", "prefix_after"):
                _sha(doc[name], name)
            if (
                type(doc["segment"]) is not str
                or doc["row_count"] < 1
                or not 1 <= doc["byte_count"] <= limits.max_block_bytes
            ):
                raise ValueError("invalid block segment/size/count")
            blocks.append(_Block(**doc))
            digest.update(raw)
        if _identity(os.fstat(stream.fileno())) != _identity(opened):
            raise ValueError("index changed during read")
    if (
        digest.hexdigest() != meta["sha256"]
        or len(blocks) != count
        or _identity(_regular_nofollow(root / "blocks.jsonl")) != _identity(opened)
    ):
        raise ValueError("index hash/count/identity mismatch")
    # Every source data byte and row is covered once, with no gap or overlap.
    next_row = block_number = 0
    prefix = value["prefix_genesis"]
    prior = (-1, -1, -1)
    for segment in source_meta["segments"]:
        offset = value["header_bytes"] if segment["name"] == "segment-000001.csv" else 0
        segment_rows = 0
        while block_number < len(blocks) and blocks[block_number].segment == segment["name"]:
            block = blocks[block_number]
            if (
                block.offset != offset
                or block.first_row != next_row
                or block.prefix_before != prefix
                or block.first_update_id <= prior[0]
                or block.first_transaction_ms < prior[1]
                or block.first_event_ms < prior[2]
                or block.last_update_id < block.first_update_id
                or block.last_transaction_ms < block.first_transaction_ms
                or block.last_event_ms < block.first_event_ms
                or block.first_event_ms < block.first_transaction_ms
                or block.last_event_ms < block.last_transaction_ms
            ):
                raise ValueError("block coverage/order/prefix metadata mismatch")
            offset += block.byte_count
            next_row += block.row_count
            segment_rows += block.row_count
            prefix = block.prefix_after
            prior = block.last_update_id, block.last_transaction_ms, block.last_event_ms
            block_number += 1
        if offset != segment["bytes"] or segment_rows != segment["rows"]:
            raise ValueError("index omits/duplicates original source bytes or rows")
    if block_number != count or next_row != source.row_count or prefix != value["prefix_final"]:
        raise ValueError("index final source/prefix coverage mismatch")
    if actual != _source_identities(source_path, source_meta):
        raise ValueError("source changed during index open")
    _deadline_check(deadline)
    return ArchiveBatchIndexV3(
        root,
        source_path,
        expected_index_manifest_sha256,
        expected_source_manifest_sha256,
        source.symbol,
        source.transaction_day,
        source.row_count,
        limits,
        tuple(blocks),
        tuple((name, tuple(identity)) for name, identity in actual.items()),
        _identity(opened),
        value["prefix_final"],
        source_meta["limits"]["max_line_bytes"],
    )


class ArchiveBatchCursorV3:
    """Single-owner cursor. Failed source reads poison it; no skip/repair API."""

    @property
    def index(self) -> ArchiveBatchIndexV3:
        return self._index

    @property
    def clock(self) -> ArchiveMarketClockV3:
        return self._clock

    def __init__(
        self,
        index: ArchiveBatchIndexV3,
        *,
        clock: ArchiveMarketClockV3,
        expected_checkpoint: ArchiveCursorCheckpointV3 | None = None,
    ) -> None:
        if type(index) is not ArchiveBatchIndexV3 or type(clock) is not ArchiveMarketClockV3:
            raise ValueError("exact sealed index and clock required")
        self._index, self._clock = index, clock
        self._lock = threading.RLock()
        deadline = time.monotonic() + index.limits.timeout_seconds
        # A dataclass replacement is not a verified handle. Bind its complete
        # bounded block metadata back to the independently pinned manifest.
        manifest, _ = _read_json(
            index.root / "manifest.json", MAX_INDEX_MANIFEST_BYTES, index.manifest_sha256
        )
        source_manifest, _ = _read_json(
            index.source_root / "manifest.json", MAX_MANIFEST_BYTES, index.source_manifest_sha256
        )
        metadata_hash = hashlib.sha256()
        if len(index.blocks) > MAX_BLOCKS:
            raise ValueError("unbounded block handle")
        for block in index.blocks:
            _deadline_check(deadline)
            if type(block) is not _Block:
                raise ValueError("exact authenticated block metadata required")
            metadata_hash.update(_canonical(asdict(block)) + b"\n")
        if (
            manifest["source_root"] != str(index.source_root)
            or manifest["source_manifest_sha256"] != index.source_manifest_sha256
            or manifest["blocks"]["sha256"] != metadata_hash.hexdigest()
            or manifest["blocks"]["count"] != len(index.blocks)
            or manifest["limits"] != asdict(index.limits)
            or manifest["source_csv"]["rows"] != index.row_count
            or manifest["prefix_final"] != index.prefix_final
            or source_manifest["symbol"] != index.symbol
            or source_manifest["transaction_day"] != index.transaction_day
            or source_manifest["limits"]["max_line_bytes"] != index.max_line_bytes
            or dict(index.source_identities)
            != {name: tuple(identity) for name, identity in manifest["source_identities_after"].items()}
        ):
            raise ValueError("index handle differs from independently sealed metadata")
        self._starts = tuple(block.first_row for block in index.blocks)
        self._identities = dict(index.source_identities)
        self._cached_number = -1
        self._cached_rows: tuple[BookTickerArchiveRowV3, ...] = ()
        self._checked_blocks: set[int] = set()
        self._poisoned = False
        self._next_row = 0
        self._prefix = _genesis(index.source_manifest_sha256)
        if expected_checkpoint is not None:
            if type(expected_checkpoint) is not ArchiveCursorCheckpointV3 or (
                expected_checkpoint.index_manifest_sha256 != index.manifest_sha256
                or expected_checkpoint.source_manifest_sha256 != index.source_manifest_sha256
                or expected_checkpoint.clock_policy_sha256 != clock.sha256
                or expected_checkpoint.next_row > index.row_count
            ):
                raise ValueError("independent retained cursor fence mismatch")
            row_index = expected_checkpoint.next_row
            prefix = self._prefix_at(row_index, deadline)
            if prefix != expected_checkpoint.prefix_sha256:
                raise ValueError("independent retained cursor prefix mismatch")
            self._next_row, self._prefix = row_index, prefix

    def checkpoint(self) -> ArchiveCursorCheckpointV3:
        """Returns the last success, also after a poisoned operation."""
        with self._lock:
            return ArchiveCursorCheckpointV3(
                self.index.manifest_sha256,
                self.index.source_manifest_sha256,
                self.clock.sha256,
                self._next_row,
                self._prefix,
            )

    def _fence(self) -> None:
        _safe_path(self.index.root)
        _safe_path(self.index.source_root)
        _read_json(self.index.root / "manifest.json", MAX_INDEX_MANIFEST_BYTES, self.index.manifest_sha256)
        _read_json(
            self.index.source_root / "manifest.json", MAX_MANIFEST_BYTES, self.index.source_manifest_sha256
        )
        if _identity(_regular_nofollow(self.index.root / "blocks.jsonl")) != self.index.index_file_identity:
            raise ValueError("index file identity changed")
        for name in ("manifest.json", "sparse-index.jsonl"):
            if _identity(_regular_nofollow(self.index.source_root / name)) != self._identities[name]:
                raise ValueError("source metadata identity changed")

    def _load_block(self, number: int, deadline: float) -> tuple[BookTickerArchiveRowV3, ...]:
        block = self.index.blocks[number]
        path = self.index.source_root / block.segment
        if number in self._checked_blocks and self._cached_number == number:
            return self._cached_rows
        if _identity(_regular_nofollow(path)) != self._identities[block.segment]:
            raise ValueError("original segment physical identity changed")
        _deadline_check(deadline)
        stream, opened = _open_regular(path)
        with stream:
            stream.seek(block.offset)
            raw = stream.read(block.byte_count)
            if _identity(os.fstat(stream.fileno())) != self._identities[block.segment]:
                raise ValueError("original segment changed while reading block")
        if (
            _identity(_regular_nofollow(path)) != self._identities[block.segment]
            or len(raw) != block.byte_count
            or hashlib.sha256(raw).hexdigest() != block.sha256
        ):
            raise ValueError("original bounded block hash/identity mismatch")
        self._checked_blocks.add(number)
        if self._cached_number == number:
            return self._cached_rows
        # No row can escape before the complete bounded block is authenticated.
        lines = raw.splitlines(keepends=True)
        if len(lines) != block.row_count or any(
            not line.endswith(b"\n") or len(line) > self.index.max_line_bytes for line in lines
        ):
            raise ValueError("block row-boundary/count mismatch")
        rows = tuple(
            _parse_row(line, self.index.symbol, self.index.transaction_day, block.first_row + offset)
            for offset, line in enumerate(lines)
        )
        prefix = block.prefix_before
        prior = (-1, -1, -1)
        for row in rows:
            _deadline_check(deadline)
            current = row.update_id, row.transaction_time_ms, row.event_time_ms
            if current[0] <= prior[0] or current[1] < prior[1] or current[2] < prior[2]:
                raise ValueError("authenticated block IDs/clocks regress")
            prefix = _advance(prefix, row.row_index, row.raw_csv_line)
            prior = current
        first, last = rows[0], rows[-1]
        if prefix != block.prefix_after or (
            first.update_id,
            last.update_id,
            first.transaction_time_ms,
            last.transaction_time_ms,
            first.event_time_ms,
            last.event_time_ms,
        ) != (
            block.first_update_id,
            block.last_update_id,
            block.first_transaction_ms,
            block.last_transaction_ms,
            block.first_event_ms,
            block.last_event_ms,
        ):
            raise ValueError("block prefix/original clock metadata mismatch")
        self._cached_number, self._cached_rows = number, rows
        return rows

    def _prefix_at(self, row_index: int, deadline: float) -> str:
        self._fence()
        if row_index == self.index.row_count:
            return self.index.prefix_final
        number = bisect.bisect_right(self._starts, row_index) - 1
        block = self.index.blocks[number]
        prefix = block.prefix_before
        for row in self._load_block(number, deadline)[: row_index - block.first_row]:
            prefix = _advance(prefix, row.row_index, row.raw_csv_line)
        return prefix

    def lookup_row(self, row_index: int) -> BookTickerArchiveRowV3:
        """Bounded authenticated membership lookup; does not move the cursor."""
        with self._lock:
            return self._lookup_row(row_index)

    def _lookup_row(self, row_index: int) -> BookTickerArchiveRowV3:
        if type(row_index) is not int or not 0 <= row_index < self.index.row_count:
            raise ValueError("lookup row outside fixed source")
        if self._poisoned:
            raise ValueError("cursor is poisoned; reopen with independently retained checkpoint")
        deadline = time.monotonic() + self.index.limits.timeout_seconds
        try:
            self._checked_blocks.clear()
            self._fence()
            number = bisect.bisect_right(self._starts, row_index) - 1
            result = self._load_block(number, deadline)[row_index - self._starts[number]]
            _deadline_check(deadline)
            return result
        except (ValueError, OSError, TimeoutError):
            self._poisoned = True
            raise

    def read_batch(
        self,
        *,
        max_rows: int,
        stop_modeled_available_ms: int | None = None,
    ) -> ArchiveBatchV3:
        """Read an exact contiguous prefix; inclusive availability cutoff.

        Ties remain ordered by original row index. Limits/cutoff may end a
        batch, never discard a row. Consumer WAL must retain batch.before/
        batch.after/hash before committing its financial transition.
        """
        with self._lock:
            return self._read_batch(max_rows=max_rows, stop_modeled_available_ms=stop_modeled_available_ms)

    def _read_batch(
        self,
        *,
        max_rows: int,
        stop_modeled_available_ms: int | None = None,
    ) -> ArchiveBatchV3:
        if type(max_rows) is not int or not 1 <= max_rows <= self.index.limits.max_batch_rows:
            raise ValueError("batch row request exceeds sealed bounded profile")
        if stop_modeled_available_ms is not None and (
            type(stop_modeled_available_ms) is not int or stop_modeled_available_ms < 0
        ):
            raise ValueError("invalid explicit availability cutoff")
        if self._poisoned:
            raise ValueError("cursor is poisoned; no skip/repair allowed")
        before = self.checkpoint()
        rows, quotes = [], []
        size, row_index, prefix = 0, self._next_row, self._prefix
        deadline = time.monotonic() + self.index.limits.timeout_seconds
        try:
            self._checked_blocks.clear()
            self._fence()
            while row_index < self.index.row_count and len(rows) < max_rows:
                _deadline_check(deadline)
                number = bisect.bisect_right(self._starts, row_index) - 1
                row = self._load_block(number, deadline)[row_index - self._starts[number]]
                quote = archive_quote_v3(
                    row, clock=self.clock, source_manifest_sha256=self.index.source_manifest_sha256
                )
                if (
                    stop_modeled_available_ms is not None
                    and quote.modeled_available_at_ms > stop_modeled_available_ms
                ):
                    break
                if size + len(row.raw_csv_line) > self.index.limits.max_batch_bytes:
                    if not rows:
                        raise ValueError("one original row exceeds sealed batch bytes")
                    break
                rows.append(row)
                quotes.append(quote)
                size += len(row.raw_csv_line)
                prefix = _advance(prefix, row_index, row.raw_csv_line)
                row_index += 1
            self._fence()
            _deadline_check(deadline)
            # Validate every used segment once more before exposing the batch.
            for segment in {
                self.index.blocks[bisect.bisect_right(self._starts, row.row_index) - 1].segment
                for row in rows
            }:
                if (
                    _identity(_regular_nofollow(self.index.source_root / segment))
                    != self._identities[segment]
                ):
                    raise ValueError("source changed before batch handoff")
            _deadline_check(deadline)
            after = ArchiveCursorCheckpointV3(
                self.index.manifest_sha256,
                self.index.source_manifest_sha256,
                self.clock.sha256,
                row_index,
                prefix,
            )
        except (ValueError, OSError, TimeoutError):
            self._poisoned = True
            raise
        self._next_row, self._prefix = row_index, prefix
        return ArchiveBatchV3(before, after, tuple(rows), tuple(quotes), size)
