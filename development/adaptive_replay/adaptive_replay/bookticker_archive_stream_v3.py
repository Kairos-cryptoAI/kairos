"""Create-only, lossless, bounded on-disk streams for native bookTicker ZIPs.

The stream retains original CSV bytes (including the header and line endings)
in sealed line-boundary segments. Sparse offsets permit bounded point/range
reads without loading the full archive or its rows into memory. This records
exchange T/E clocks only; it does not establish a historical local receive
clock, feed completeness, venue authenticity, or trading authority.
"""

from __future__ import annotations

import bisect
import copy
import hashlib
import json
import os
import re
import stat
import time
import zipfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

SCHEMA = "kairos.development.bookticker-archive-stream.v3"
HEADER = b"update_id,best_bid_price,best_bid_qty,best_ask_price,best_ask_qty,transaction_time,event_time"
DEFAULT_SEGMENT_BYTES = 64 * 1024 * 1024
DEFAULT_INDEX_STRIDE = 4096
DEFAULT_MAX_LINE_BYTES = 4096
DEFAULT_MAX_SEGMENTS = 4096
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_INDEX_BYTES = 16 * 1024 * 1024
MAX_INDEX_LINE_BYTES = 512
MAX_INDEX_ANCHORS = 100_000
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SYMBOL = re.compile(r"[A-Z0-9]{3,20}\Z")
_DAY = re.compile(r"20\d{2}-\d{2}-\d{2}\Z")
_INTEGER_TEXT = re.compile(r"(?:0|[1-9][0-9]{0,19})\Z")
_DECIMAL_TEXT = re.compile(r"(?:0|[1-9][0-9]{0,63})(?:\.[0-9]{1,64})?\Z")
_SEGMENT_NAME = re.compile(r"segment-[0-9]{6}\.csv\Z")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _sha(value: str, label: str) -> None:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA256")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _exact_keys(value: object, keys: set[str], label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError(f"invalid {label} schema")
    return value


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"invalid {label}")
    return value


def _is_reparse(path: Path, mode: int) -> bool:
    if stat.S_ISLNK(mode):
        return True
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _regular_nofollow(path: Path) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValueError("required stream file is unavailable") from exc
    if _is_reparse(path, metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("stream input must be a regular non-reparse file")
    return metadata


def _open_regular(path: Path):
    before = _regular_nofollow(path)
    stream = path.open("rb")
    opened = os.fstat(stream.fileno())
    after = _regular_nofollow(path)
    if _identity(before) != _identity(opened) or _identity(opened) != _identity(after):
        stream.close()
        raise ValueError("stream path changed while opening")
    return stream, opened


def _identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _safe_path(path: Path) -> Path:
    """Resolve an existing input path without accepting symlink components."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            metadata = current.lstat()
            if _is_reparse(current, metadata.st_mode):
                raise ValueError("symlink or reparse paths are not accepted")
        except FileNotFoundError:
            pass
    return absolute


@dataclass(frozen=True)
class StreamLimitsV3:
    """Explicit hard ceilings; defaults match the exact profiled BTC source."""

    max_archive_bytes: int = 206_972_981
    max_uncompressed_bytes: int = 1_811_753_894
    max_rows: int = 19_245_805
    segment_bytes: int = DEFAULT_SEGMENT_BYTES
    index_stride: int = DEFAULT_INDEX_STRIDE
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES
    max_segments: int = DEFAULT_MAX_SEGMENTS
    max_open_files: int = 3
    timeout_seconds: int = 1800
    max_index_anchors: int = MAX_INDEX_ANCHORS

    def __post_init__(self) -> None:
        for name in (
            "max_archive_bytes",
            "max_uncompressed_bytes",
            "max_rows",
            "segment_bytes",
            "index_stride",
            "max_line_bytes",
            "max_segments",
            "max_open_files",
            "timeout_seconds",
            "max_index_anchors",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (
            self.segment_bytes < self.max_line_bytes
            or self.max_segments > 4096
            or self.max_open_files != 3
            or self.timeout_seconds > 86_400
            or self.max_line_bytes > DEFAULT_MAX_LINE_BYTES
            or self.max_index_anchors > MAX_INDEX_ANCHORS
        ):
            raise ValueError("inconsistent stream segment limits")


@dataclass(frozen=True)
class BookTickerArchiveRowV3:
    """Exact native row: original spellings plus validated typed quote values."""

    symbol: str
    transaction_day: str
    row_index: int
    raw_csv_line: bytes
    update_id: int
    best_bid_price_text: str
    best_bid_qty_text: str
    best_ask_price_text: str
    best_ask_qty_text: str
    transaction_time_ms: int
    event_time_ms: int

    @property
    def best_bid_price(self) -> Decimal:
        return Decimal(self.best_bid_price_text)

    @property
    def best_bid_qty(self) -> Decimal:
        return Decimal(self.best_bid_qty_text)

    @property
    def best_ask_price(self) -> Decimal:
        return Decimal(self.best_ask_price_text)

    @property
    def best_ask_qty(self) -> Decimal:
        return Decimal(self.best_ask_qty_text)


@dataclass(frozen=True)
class _Anchor:
    row_index: int
    segment: str
    offset: int
    transaction_time_ms: int


@dataclass(frozen=True)
class _Segment:
    name: str
    byte_count: int
    row_count: int
    sha256: str


def _parse_row(raw: bytes, symbol: str, day: str, row_index: int) -> BookTickerArchiveRowV3:
    line = raw[:-2] if raw.endswith(b"\r\n") else raw[:-1] if raw.endswith(b"\n") else raw
    try:
        fields = line.decode("ascii").split(",")
        if (
            len(fields) != 7
            or any(not item for item in fields)
            or _INTEGER_TEXT.fullmatch(fields[0]) is None
            or _INTEGER_TEXT.fullmatch(fields[5]) is None
            or _INTEGER_TEXT.fullmatch(fields[6]) is None
            or any(_DECIMAL_TEXT.fullmatch(item) is None for item in fields[1:5])
        ):
            raise ValueError
        update_id = int(fields[0])
        transaction_ms, event_ms = int(fields[5]), int(fields[6])
        prices = [Decimal(value) for value in (fields[1], fields[3])]
        quantities = [Decimal(value) for value in (fields[2], fields[4])]
    except (UnicodeError, ValueError, InvalidOperation):
        raise ValueError("invalid native seven-column bookTicker row") from None
    if (
        update_id < 0
        or transaction_ms < 0
        or event_ms < transaction_ms
        or transaction_ms // 86_400_000 != _day_start_ms(day) // 86_400_000
        or any(not value.is_finite() or value <= 0 for value in prices + quantities)
        or prices[0] >= prices[1]
    ):
        raise ValueError("bookTicker row violates identifier, clock, day, or quote invariants")
    return BookTickerArchiveRowV3(
        symbol,
        day,
        row_index,
        raw,
        update_id,
        fields[1],
        fields[2],
        fields[3],
        fields[4],
        transaction_ms,
        event_ms,
    )


def _day_start_ms(day: str) -> int:
    if type(day) is not str or _DAY.fullmatch(day) is None:
        raise ValueError("ISO transaction day required")
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        raise ValueError("valid ISO transaction day required") from None
    return int(datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC).timestamp() * 1000)


def _hash_file(path: Path, deadline: float | None = None) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    stream, before = _open_regular(path)
    with stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError("stream integrity scan exceeded explicit timeout")
            digest.update(block)
            size += len(block)
        if _identity(os.fstat(stream.fileno())) != _identity(before):
            raise ValueError("stream file changed during integrity scan")
        if _identity(_regular_nofollow(path)) != _identity(before):
            raise ValueError("stream path changed during integrity scan")
    return digest.hexdigest(), size


def build_bookticker_archive_stream_v3(
    archive_path: str | Path,
    output_dir: str | Path,
    *,
    symbol: str,
    transaction_day: str,
    expected_archive_sha256: str,
    expected_rows: int,
    expected_uncompressed_bytes: int,
    expected_uncompressed_sha256: str,
    expected_member: str | None = None,
    limits: StreamLimitsV3 | None = None,
    evidence_kind: str = "PUBLIC_CHECKSUM_OBJECT",
) -> BookTickerArchiveStreamV3:
    """Convert one checksum-bound original ZIP to create-only sealed disk files.

    Partial outputs are deliberately retained after failure, but without the
    final `manifest.json` they cannot be opened as an accepted stream.
    """
    started = time.monotonic()
    limits = limits or StreamLimitsV3()
    if type(limits) is not StreamLimitsV3:
        raise ValueError("exact explicit stream limits required")
    if type(symbol) is not str or _SYMBOL.fullmatch(symbol) is None:
        raise ValueError("bounded uppercase native symbol required")
    _day_start_ms(transaction_day)
    _sha(expected_archive_sha256, "expected archive SHA256")
    _sha(expected_uncompressed_sha256, "expected uncompressed SHA256")
    if (
        type(expected_rows) is not int
        or expected_rows <= 0
        or expected_rows > limits.max_rows
        or type(expected_uncompressed_bytes) is not int
        or expected_uncompressed_bytes <= len(HEADER)
        or expected_uncompressed_bytes > limits.max_uncompressed_bytes
        or type(evidence_kind) is not str
        or evidence_kind not in {"PUBLIC_CHECKSUM_OBJECT", "TEST_FIXTURE"}
        or (expected_rows + limits.index_stride - 1) // limits.index_stride > limits.max_index_anchors
    ):
        raise ValueError("source profile exceeds explicit limits or evidence class is invalid")
    source = _safe_path(Path(archive_path))
    target = Path(os.path.abspath(output_dir))
    if not target.parent.is_dir():
        raise ValueError("source archive and existing output parent are required")
    _regular_nofollow(source)
    _safe_path(target.parent)
    if target.exists():
        raise FileExistsError("stream output is create-only; target already exists")
    archive_sha, archive_bytes = _hash_file(source, started + limits.timeout_seconds)
    if archive_sha != expected_archive_sha256 or archive_bytes > limits.max_archive_bytes:
        raise ValueError("archive checksum or compressed-byte ceiling mismatch")
    source_stat = _regular_nofollow(source)
    source_identity = _identity(source_stat)

    member_name = f"{symbol}-bookTicker-{transaction_day}.csv" if expected_member is None else expected_member
    if (
        type(member_name) is not str
        or Path(member_name).name != member_name
        or not member_name.endswith(".csv")
    ):
        raise ValueError("safe exact CSV member name required")
    target.mkdir()
    segment_records: list[dict[str, object]] = []
    anchors: list[_Anchor] = []
    raw_digest = hashlib.sha256()
    index_digest = hashlib.sha256()
    raw_size = rows = 0
    prior_update = prior_transaction = prior_event = -1
    segment_number = 0
    segment_stream = None
    segment_name = ""
    segment_size = segment_rows = 0
    segment_digest = hashlib.sha256()
    started = time.monotonic()

    def seal_segment() -> None:
        nonlocal segment_stream, segment_size, segment_rows, segment_digest
        if segment_stream is None:
            return
        segment_stream.flush()
        os.fsync(segment_stream.fileno())
        segment_stream.close()
        segment_records.append(
            {
                "name": segment_name,
                "bytes": segment_size,
                "rows": segment_rows,
                "sha256": segment_digest.hexdigest(),
            }
        )
        segment_stream = None
        segment_size = segment_rows = 0
        segment_digest = hashlib.sha256()

    def write_raw_line(line: bytes, data_row_index: int | None) -> tuple[str, int]:
        nonlocal segment_number, segment_stream, segment_name, segment_size, segment_rows
        if segment_stream is None or (segment_size and segment_size + len(line) > limits.segment_bytes):
            seal_segment()
            segment_number += 1
            if segment_number > limits.max_segments:
                raise ValueError("stream exceeds explicit segment-count ceiling")
            segment_name = f"segment-{segment_number:06d}.csv"
            segment_stream = (target / segment_name).open("xb")
        offset = segment_size
        segment_stream.write(line)
        segment_digest.update(line)
        segment_size += len(line)
        if data_row_index is not None:
            segment_rows += 1
        return segment_name, offset

    try:
        with zipfile.ZipFile(source, "r") as archive:
            files = [info for info in archive.infolist() if not info.is_dir()]
            if len(files) != 1 or files[0].filename != member_name:
                raise ValueError("ZIP must contain exactly the expected original CSV member")
            info = files[0]
            if (
                info.file_size != expected_uncompressed_bytes
                or info.file_size > limits.max_uncompressed_bytes
            ):
                raise ValueError("ZIP member size does not match the explicit source profile")
            with archive.open(info, "r") as csv_stream:
                header = csv_stream.readline(limits.max_line_bytes + 1)
                if len(header) > limits.max_line_bytes or header not in {HEADER + b"\n", HEADER + b"\r\n"}:
                    raise ValueError("exact native seven-column CSV header required")
                raw_digest.update(header)
                raw_size += len(header)
                write_raw_line(header, None)
                while True:
                    if time.monotonic() > started + limits.timeout_seconds:
                        raise TimeoutError("bookTicker source stream exceeded its explicit timeout")
                    line = csv_stream.readline(limits.max_line_bytes + 1)
                    if not line:
                        break
                    if len(line) > limits.max_line_bytes or not line.endswith(b"\n"):
                        raise ValueError("truncated or overlong CSV line")
                    if rows >= expected_rows or rows >= limits.max_rows:
                        raise ValueError("source has more rows than its explicit profile")
                    row = _parse_row(line, symbol, transaction_day, rows)
                    if (
                        row.update_id <= prior_update
                        or row.transaction_time_ms < prior_transaction
                        or row.event_time_ms < prior_event
                    ):
                        raise ValueError(
                            "bookTicker IDs and T/E clocks must be strictly/nonregressively ordered"
                        )
                    prior_update, prior_transaction, prior_event = (
                        row.update_id,
                        row.transaction_time_ms,
                        row.event_time_ms,
                    )
                    if rows % limits.index_stride == 0:
                        # The returned location is recorded after the segment is selected.
                        seg, off = write_raw_line(line, rows)
                        anchor = _Anchor(rows, seg, off, row.transaction_time_ms)
                        anchors.append(anchor)
                        if len(anchors) > limits.max_index_anchors:
                            raise ValueError("stream exceeds explicit sparse-anchor ceiling")
                        packed = _canonical(asdict(anchor)) + b"\n"
                        with (target / "sparse-index.jsonl").open("ab") as index_stream:
                            index_stream.write(packed)
                        index_digest.update(packed)
                    else:
                        write_raw_line(line, rows)
                    raw_digest.update(line)
                    raw_size += len(line)
                    rows += 1
                    if raw_size > limits.max_uncompressed_bytes:
                        raise ValueError("source exceeds explicit uncompressed-byte ceiling")
                seal_segment()
            # ZipExtFile validates CRC when the entire member reaches EOF.
        if rows != expected_rows or raw_size != expected_uncompressed_bytes:
            raise ValueError("source row count or exact original CSV byte count mismatch")
        if raw_digest.hexdigest() != expected_uncompressed_sha256:
            raise ValueError("full uncompressed CSV SHA256 mismatch")
        after_stat = _regular_nofollow(source)
        after_identity = _identity(after_stat)
        after_sha, after_size = _hash_file(source, started + limits.timeout_seconds)
        if source_identity != after_identity or after_sha != archive_sha or after_size != archive_bytes:
            raise ValueError("source archive changed during streaming")
        if not anchors:
            raise ValueError("nonempty sparse index required")
        index_path = target / "sparse-index.jsonl"
        index_sha, index_bytes = _hash_file(index_path)
        if index_sha != index_digest.hexdigest():
            raise ValueError("sparse index changed while being written")
        for record in segment_records:
            observed_sha, observed_size = _hash_file(
                target / str(record["name"]), started + limits.timeout_seconds
            )
            if observed_sha != record["sha256"] or observed_size != record["bytes"]:
                raise ValueError("sealed segment failed post-write verification")
        manifest = {
            "schema": SCHEMA,
            "symbol": symbol,
            "transaction_day": transaction_day,
            "evidence_kind": evidence_kind,
            "archive": {
                "basename": source.name,
                "bytes": archive_bytes,
                "sha256": archive_sha,
                "member": member_name,
            },
            "csv": {"rows": rows, "bytes": raw_size, "sha256": raw_digest.hexdigest()},
            "segments": segment_records,
            "sparse_index": {
                "name": "sparse-index.jsonl",
                "stride": limits.index_stride,
                "anchors": len(anchors),
                "bytes": index_bytes,
                "sha256": index_sha,
            },
            "limits": asdict(limits),
            "elapsed_ms_before_manifest": int((time.monotonic() - started) * 1000),
            "clock_semantics": {
                "transaction_time": "EXCHANGE_TRANSACTION_TIME_T",
                "event_time": "EXCHANGE_EVENT_TIME_E",
                "historical_local_receive_clock": "UNKNOWN",
            },
            "trading_authority": "NONE",
        }
        temp_manifest = target / "manifest.json.tmp"
        manifest_bytes = _canonical(manifest) + b"\n"
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        with temp_manifest.open("xb") as output:
            output.write(manifest_bytes)
            output.flush()
            os.fsync(output.fileno())
        # Audit the complete candidate before the sole acceptance marker exists.
        # A failed audit leaves only the recoverable staged file, never a final manifest.
        verified = open_bookticker_archive_stream_v3(
            target,
            expected_manifest_sha256=manifest_sha,
            _deadline=started + limits.timeout_seconds,
            _staged_candidate=True,
        )
        final_manifest = target / "manifest.json"
        os.link(temp_manifest, final_manifest)  # Atomic create-only publication; fails if target exists.
        try:
            temp_manifest.unlink()
        except OSError:
            # The final hard link already publishes the audited bytes; a staged
            # duplicate is harmless forensic residue if cleanup is unavailable.
            pass
        return verified
    except BaseException:
        if segment_stream is not None:
            segment_stream.close()
        raise


class BookTickerArchiveStreamV3:
    """Immutable verified view; mutable JSON is exposed only as a deep copy."""

    __slots__ = (
        "_root",
        "_manifest_bytes",
        "_manifest_sha256",
        "_anchors",
        "_segments",
        "_limits",
        "_symbol",
        "_transaction_day",
        "_row_count",
        "_verification_elapsed_ms",
    )

    def __init__(
        self,
        root: Path,
        manifest_bytes: bytes,
        manifest_sha256: str,
        anchors: tuple[_Anchor, ...],
        segments: tuple[_Segment, ...],
        limits: StreamLimitsV3,
        symbol: str,
        transaction_day: str,
        row_count: int,
        verification_elapsed_ms: int,
    ):
        object.__setattr__(self, "_root", root)
        object.__setattr__(self, "_manifest_bytes", manifest_bytes)
        object.__setattr__(self, "_manifest_sha256", manifest_sha256)
        object.__setattr__(self, "_anchors", anchors)
        object.__setattr__(self, "_segments", segments)
        object.__setattr__(self, "_limits", limits)
        object.__setattr__(self, "_symbol", symbol)
        object.__setattr__(self, "_transaction_day", transaction_day)
        object.__setattr__(self, "_row_count", row_count)
        object.__setattr__(self, "_verification_elapsed_ms", verification_elapsed_ms)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("BookTickerArchiveStreamV3 is immutable")

    @property
    def root(self) -> Path:
        return self._root

    @property
    def manifest(self) -> dict[str, object]:
        return copy.deepcopy(json.loads(self._manifest_bytes))

    @property
    def manifest_sha256(self) -> str:
        return self._manifest_sha256

    @property
    def verification_elapsed_ms(self) -> int:
        return self._verification_elapsed_ms

    @property
    def total_elapsed_ms(self) -> int:
        before_manifest = json.loads(self._manifest_bytes)["elapsed_ms_before_manifest"]
        return before_manifest + self._verification_elapsed_ms

    @property
    def anchors(self) -> tuple[_Anchor, ...]:
        return self._anchors

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def transaction_day(self) -> str:
        return self._transaction_day

    @property
    def row_count(self) -> int:
        return self._row_count

    def _verify_manifest_current(self, deadline: float) -> None:
        path = self._root / "manifest.json"
        metadata = _regular_nofollow(path)
        if metadata.st_size > MAX_MANIFEST_BYTES:
            raise ValueError("manifest changed since stream acceptance")
        digest, size = _hash_file(path, deadline)
        if digest != self._manifest_sha256 or size != len(self._manifest_bytes):
            raise ValueError("manifest changed since stream acceptance")

    def iter_rows(self, start_row: int = 0, stop_row: int | None = None) -> Iterator[BookTickerArchiveRowV3]:
        """Yield [start_row, stop_row) with bounded memory and sparse seeking."""
        stop = self.row_count if stop_row is None else stop_row
        if (
            type(start_row) is not int
            or type(stop) is not int
            or not 0 <= start_row <= stop <= self.row_count
        ):
            raise ValueError("valid half-open row interval required")
        if start_row == stop:
            return
        deadline = time.monotonic() + self._limits.timeout_seconds
        self._verify_manifest_current(deadline)
        row_anchors = self._anchors
        anchor_number = max(0, bisect.bisect_right([a.row_index for a in row_anchors], start_row) - 1)
        anchor = row_anchors[anchor_number]
        segment_index = next(i for i, segment in enumerate(self._segments) if segment.name == anchor.segment)
        row_index = anchor.row_index
        while segment_index < len(self._segments) and row_index < stop:
            segment = self._segments[segment_index]
            path = self._root / segment.name
            stream, opened_stat = _open_regular(path)
            with stream:
                if opened_stat.st_size != segment.byte_count:
                    raise ValueError("stream segment changed since acceptance")
                current_digest = hashlib.sha256()
                while block := stream.read(1024 * 1024):
                    if time.monotonic() > deadline:
                        raise TimeoutError("stream read exceeded explicit timeout")
                    current_digest.update(block)
                if current_digest.hexdigest() != segment.sha256:
                    raise ValueError("stream segment changed since acceptance")
                stream.seek(anchor.offset if segment.name == anchor.segment else 0)
                while row_index < stop:
                    if time.monotonic() > deadline:
                        raise TimeoutError("stream read exceeded explicit timeout")
                    line = stream.readline(self._limits.max_line_bytes + 1)
                    if not line:
                        break
                    if len(line) > self._limits.max_line_bytes or not line.endswith(b"\n"):
                        raise ValueError("sealed CSV segment has invalid line framing")
                    row = _parse_row(line, self.symbol, self.transaction_day, row_index)
                    if row_index >= start_row:
                        yield row
                    row_index += 1
                if _identity(os.fstat(stream.fileno())) != _identity(opened_stat):
                    raise ValueError("stream segment identity changed during read")
                current_path_stat = _regular_nofollow(path)
                if _identity(current_path_stat) != _identity(opened_stat):
                    raise ValueError("stream segment path changed during read")
            segment_index += 1

    def iter_range(
        self, start_transaction_ms: int, stop_transaction_ms: int
    ) -> Iterator[BookTickerArchiveRowV3]:
        """Yield rows in the half-open transaction-clock range [start, stop)."""
        if (
            type(start_transaction_ms) is not int
            or type(stop_transaction_ms) is not int
            or start_transaction_ms < 0
            or stop_transaction_ms < start_transaction_ms
        ):
            raise ValueError("valid half-open transaction-time range required")
        anchors = self._anchors
        anchor_times = [anchor.transaction_time_ms for anchor in anchors]
        anchor_index = max(0, bisect.bisect_left(anchor_times, start_transaction_ms) - 1)
        first_row = anchors[anchor_index].row_index
        for row in self.iter_rows(first_row):
            if row.transaction_time_ms >= stop_transaction_ms:
                break
            if row.transaction_time_ms >= start_transaction_ms:
                yield row

    def row_at(self, row_index: int) -> BookTickerArchiveRowV3:
        if type(row_index) is not int or not 0 <= row_index < self.row_count:
            raise IndexError("bookTicker row index outside accepted stream")
        rows = self.iter_rows(row_index, row_index + 1)
        try:
            return next(rows)
        finally:
            rows.close()


def open_bookticker_archive_stream_v3(
    output_dir: str | Path,
    *,
    expected_manifest_sha256: str,
    _deadline: float | None = None,
    _staged_candidate: bool = False,
) -> BookTickerArchiveStreamV3:
    """Verify an independently pinned manifest and all bounded stream objects."""
    started = time.monotonic()
    root = _safe_path(Path(output_dir))
    root_stat = root.lstat()
    if _is_reparse(root, root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("stream root must be a regular non-reparse directory")
    if type(_staged_candidate) is not bool:
        raise ValueError("exact manifest-candidate selector required")
    manifest_path = root / ("manifest.json.tmp" if _staged_candidate else "manifest.json")
    manifest_stat = _regular_nofollow(manifest_path)
    if manifest_stat.st_size > MAX_MANIFEST_BYTES:
        raise ValueError("manifest exceeds bounded byte limit")
    manifest_stream, manifest_opened_stat = _open_regular(manifest_path)
    with manifest_stream:
        manifest_bytes = manifest_stream.read(MAX_MANIFEST_BYTES + 1)
        if len(manifest_bytes) > MAX_MANIFEST_BYTES:
            raise ValueError("manifest exceeds bounded byte limit")
        if _identity(os.fstat(manifest_stream.fileno())) != _identity(manifest_opened_stat):
            raise ValueError("manifest changed while being read")
    if _identity(_regular_nofollow(manifest_path)) != _identity(manifest_opened_stat):
        raise ValueError("manifest path changed while being read")
    _sha(expected_manifest_sha256, "expected manifest SHA256")
    if hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha256:
        raise ValueError("independent expected manifest SHA256 mismatch")
    try:
        if not manifest_bytes.endswith(b"\n") or manifest_bytes.endswith(b"\n\n"):
            raise ValueError
        manifest = json.loads(
            manifest_bytes[:-1],
            object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON number")),
        )
        if _canonical(manifest) + b"\n" != manifest_bytes:
            raise ValueError
    except (ValueError, UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("invalid, duplicate-key, or noncanonical stream manifest") from None
    manifest = _exact_keys(
        manifest,
        {
            "schema",
            "symbol",
            "transaction_day",
            "evidence_kind",
            "archive",
            "csv",
            "segments",
            "sparse_index",
            "limits",
            "elapsed_ms_before_manifest",
            "clock_semantics",
            "trading_authority",
        },
        "manifest",
    )
    if (
        manifest["schema"] != SCHEMA
        or type(manifest["schema"]) is not str
        or type(manifest["symbol"]) is not str
        or _SYMBOL.fullmatch(manifest["symbol"]) is None
        or type(manifest["evidence_kind"]) is not str
        or manifest["evidence_kind"] not in {"PUBLIC_CHECKSUM_OBJECT", "TEST_FIXTURE"}
        or manifest["trading_authority"] != "NONE"
        or type(manifest["trading_authority"]) is not str
    ):
        raise ValueError("unsupported or authority-inflating stream manifest")
    _day_start_ms(manifest["transaction_day"])
    if type(manifest["transaction_day"]) is not str:
        raise ValueError("transaction day must be a string")
    clock_meta = _exact_keys(
        manifest["clock_semantics"],
        {"transaction_time", "event_time", "historical_local_receive_clock"},
        "clock semantics",
    )
    if clock_meta != {
        "transaction_time": "EXCHANGE_TRANSACTION_TIME_T",
        "event_time": "EXCHANGE_EVENT_TIME_E",
        "historical_local_receive_clock": "UNKNOWN",
    }:
        raise ValueError("clock semantics must preserve exchange T/E and unknown local receive")
    limit_values = _exact_keys(manifest["limits"], set(asdict(StreamLimitsV3())), "stream limits")
    limits = StreamLimitsV3(**limit_values)
    deadline = _deadline if _deadline is not None else started + limits.timeout_seconds
    if time.monotonic() > deadline:
        raise TimeoutError("stream verification exceeded explicit timeout")
    archive_meta = _exact_keys(manifest["archive"], {"basename", "bytes", "sha256", "member"}, "archive")
    if (
        type(archive_meta["basename"]) is not str
        or Path(archive_meta["basename"]).name != archive_meta["basename"]
        or type(archive_meta["member"]) is not str
        or Path(archive_meta["member"]).name != archive_meta["member"]
    ):
        raise ValueError("invalid source archive identity")
    archive_bytes = _integer(archive_meta["bytes"], "archive byte count", minimum=1)
    _sha(archive_meta["sha256"], "archive SHA256")
    if archive_bytes > limits.max_archive_bytes:
        raise ValueError("archive exceeds persisted explicit capacity")
    csv_meta = _exact_keys(manifest["csv"], {"rows", "bytes", "sha256"}, "CSV")
    csv_rows = _integer(csv_meta["rows"], "CSV row count", minimum=1)
    csv_bytes = _integer(csv_meta["bytes"], "CSV byte count", minimum=len(HEADER) + 1)
    _sha(csv_meta["sha256"], "CSV SHA256")
    if csv_rows > limits.max_rows or csv_bytes > limits.max_uncompressed_bytes:
        raise ValueError("CSV exceeds persisted explicit capacities")
    if type(manifest["segments"]) is not list or not manifest["segments"]:
        raise ValueError("nonempty ordered segment list required")
    segment_values = manifest["segments"]
    if len(segment_values) > limits.max_segments or len(segment_values) > DEFAULT_MAX_SEGMENTS:
        raise ValueError("stream exceeds persisted segment-count capacity")
    segments: list[_Segment] = []
    for number, record_value in enumerate(segment_values, 1):
        record = _exact_keys(record_value, {"name", "bytes", "rows", "sha256"}, "segment")
        expected_name = f"segment-{number:06d}.csv"
        if type(record["name"]) is not str or record["name"] != expected_name:
            raise ValueError("segment names must be unique, contiguous and ordered")
        byte_count = _integer(record["bytes"], "segment byte count", minimum=1)
        row_count = _integer(record["rows"], "segment row count")
        _sha(record["sha256"], "segment SHA256")
        if byte_count > limits.segment_bytes:
            raise ValueError("segment exceeds persisted byte capacity")
        segments.append(_Segment(expected_name, byte_count, row_count, record["sha256"]))
    index_meta = _exact_keys(
        manifest["sparse_index"], {"name", "stride", "anchors", "bytes", "sha256"}, "sparse index"
    )
    stride = _integer(index_meta["stride"], "index stride", minimum=1)
    anchor_count = _integer(index_meta["anchors"], "anchor count", minimum=1)
    index_bytes = _integer(index_meta["bytes"], "index byte count", minimum=1)
    _sha(index_meta["sha256"], "index SHA256")
    expected_anchor_count = (csv_rows + stride - 1) // stride
    if (
        index_meta["name"] != "sparse-index.jsonl"
        or type(index_meta["name"]) is not str
        or stride != limits.index_stride
        or anchor_count != expected_anchor_count
        or anchor_count > limits.max_index_anchors
        or anchor_count > MAX_INDEX_ANCHORS
        or index_bytes > MAX_INDEX_BYTES
    ):
        raise ValueError("sparse index metadata exceeds explicit bounded profile")
    if type(manifest["elapsed_ms_before_manifest"]) is not int or manifest["elapsed_ms_before_manifest"] < 0:
        raise ValueError("invalid stream elapsed-time receipt")

    # No untrusted manifest/index size can trigger an unbounded read or allocation.
    index_path = root / "sparse-index.jsonl"
    index_stat = _regular_nofollow(index_path)
    if index_stat.st_size != index_bytes:
        raise ValueError("sparse index exact byte count mismatch")
    index_stream, index_opened_stat = _open_regular(index_path)
    anchors: list[_Anchor] = []
    index_digest = hashlib.sha256()
    try:
        with index_stream:
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError("sparse index verification exceeded explicit timeout")
                raw = index_stream.readline(MAX_INDEX_LINE_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_INDEX_LINE_BYTES or not raw.endswith(b"\n"):
                    raise ValueError("sparse index line exceeds bounded framing")
                if len(anchors) >= anchor_count:
                    raise ValueError("sparse index contains excess anchors")
                try:
                    value = json.loads(
                        raw[:-1],
                        object_pairs_hook=_pairs,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON number")),
                    )
                    anchor_value = _exact_keys(
                        value, {"row_index", "segment", "offset", "transaction_time_ms"}, "anchor"
                    )
                    anchor = _Anchor(
                        _integer(anchor_value["row_index"], "anchor row"),
                        anchor_value["segment"],
                        _integer(anchor_value["offset"], "anchor offset"),
                        _integer(anchor_value["transaction_time_ms"], "anchor T"),
                    )
                    if type(anchor.segment) is not str or _SEGMENT_NAME.fullmatch(anchor.segment) is None:
                        raise ValueError("unsafe index segment name")
                    if _canonical(asdict(anchor)) + b"\n" != raw:
                        raise ValueError("noncanonical sparse index line")
                except (ValueError, TypeError, json.JSONDecodeError, RecursionError):
                    raise ValueError("invalid or noncanonical sparse index anchor") from None
                if anchor.row_index != len(anchors) * stride:
                    raise ValueError("sparse index rows are not exact ordered stride anchors")
                anchors.append(anchor)
                index_digest.update(raw)
            if _identity(os.fstat(index_stream.fileno())) != _identity(index_opened_stat):
                raise ValueError("sparse index changed while being read")
    except BaseException:
        raise
    if index_digest.hexdigest() != index_meta["sha256"] or len(anchors) != anchor_count:
        raise ValueError("sparse index checksum or anchor count mismatch")
    if _identity(_regular_nofollow(index_path)) != _identity(index_opened_stat):
        raise ValueError("sparse index path changed while being read")

    combined_csv_digest = hashlib.sha256()
    anchor_cursor = row_cursor = total_segment_rows = total_segment_bytes = 0
    prior_update = prior_transaction = prior_event = -1
    for segment in segments:
        if time.monotonic() > deadline:
            raise TimeoutError("stream audit exceeded explicit timeout")
        path = root / segment.name
        metadata = _regular_nofollow(path)
        if metadata.st_size != segment.byte_count:
            raise ValueError("segment exact byte count mismatch")
        stream, opened_stat = _open_regular(path)
        segment_digest = hashlib.sha256()
        segment_bytes = segment_rows = 0
        with stream:
            offset = 0
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError("stream audit exceeded explicit timeout")
                line = stream.readline(limits.max_line_bytes + 1)
                if not line:
                    break
                if len(line) > limits.max_line_bytes or not line.endswith(b"\n"):
                    raise ValueError("sealed source has invalid line framing")
                segment_digest.update(line)
                combined_csv_digest.update(line)
                segment_bytes += len(line)
                if row_cursor == 0:
                    if segment.name != "segment-000001.csv" or line not in {HEADER + b"\n", HEADER + b"\r\n"}:
                        raise ValueError("native header must appear once at start of first segment")
                else:
                    row = _parse_row(line, manifest["symbol"], manifest["transaction_day"], row_cursor - 1)
                    if (
                        row.update_id <= prior_update
                        or row.transaction_time_ms < prior_transaction
                        or row.event_time_ms < prior_event
                    ):
                        raise ValueError("sealed source IDs or clocks regress")
                    prior_update, prior_transaction, prior_event = (
                        row.update_id,
                        row.transaction_time_ms,
                        row.event_time_ms,
                    )
                    segment_rows += 1
                    if (row_cursor - 1) % stride == 0:
                        if anchor_cursor >= len(anchors):
                            raise ValueError("sparse index omits a required row")
                        anchor = anchors[anchor_cursor]
                        if (
                            anchor.row_index != row_cursor - 1
                            or anchor.segment != segment.name
                            or anchor.offset != offset
                            or anchor.transaction_time_ms != row.transaction_time_ms
                        ):
                            raise ValueError("sparse index does not point to the exact original row")
                        anchor_cursor += 1
                offset += len(line)
                row_cursor += 1
            if _identity(os.fstat(stream.fileno())) != _identity(opened_stat):
                raise ValueError("segment changed during full integrity audit")
        if _identity(_regular_nofollow(path)) != _identity(opened_stat):
            raise ValueError("segment path changed during full integrity audit")
        if (
            segment_bytes != segment.byte_count
            or segment_rows != segment.row_count
            or segment_digest.hexdigest() != segment.sha256
        ):
            raise ValueError("segment hash, exact size, or per-segment row count mismatch")
        total_segment_bytes += segment_bytes
        total_segment_rows += segment_rows
    if (
        row_cursor != csv_rows + 1
        or total_segment_rows != csv_rows
        or total_segment_bytes != csv_bytes
        or anchor_cursor != len(anchors)
        or combined_csv_digest.hexdigest() != csv_meta["sha256"]
    ):
        raise ValueError("segments differ from exact CSV rows, bytes, SHA, or index profile")
    if time.monotonic() > deadline:
        raise TimeoutError("stream verification exceeded explicit timeout")
    return BookTickerArchiveStreamV3(
        root,
        manifest_bytes,
        expected_manifest_sha256,
        tuple(anchors),
        tuple(segments),
        limits,
        manifest["symbol"],
        manifest["transaction_day"],
        csv_rows,
        int((time.monotonic() - started) * 1000),
    )
