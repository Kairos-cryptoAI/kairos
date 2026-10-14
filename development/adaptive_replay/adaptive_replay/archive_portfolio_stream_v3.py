"""Deterministic lossless multi-source archive operations, research-only.

Original rows are merged by model availability and an explicitly sealed tie
rule. Every declared symbol/day source must be present. Bounded prefetch is
volatile; the retained checkpoint is a small exact source vector, not a tape
of millions of rows. Pending operations do not advance that checkpoint until
explicit acknowledgement. A financial driver must persist operation.after
with all effects BEFORE acknowledgement. No fills, admission, actual receive
clocks, journal recovery/latest adoption, or economics are inferred here.
"""

from __future__ import annotations

import bisect
import hashlib
import heapq
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import archive_batch_cursor_v3, archive_market_clock_v3, bookticker_archive_stream_v3
from .archive_batch_cursor_v3 import (
    ArchiveBatchIndexV3,
    ArchiveCursorCheckpointV3,
    _advance,
    _genesis,
)
from .archive_market_clock_v3 import MAX_CLOCK_MS, ArchiveBBOQuoteV3, ArchiveMarketClockV3, archive_quote_v3
from .bookticker_archive_stream_v3 import (
    BookTickerArchiveRowV3,
    _canonical,
    _day_start_ms,
    _identity,
    _regular_nofollow,
    _sha,
)

SCHEMA = "kairos.research.archive-portfolio-stream.v3"
TIE_RULE = "MODELED_AVAILABILITY_THEN_SYMBOL_DAY_ORIGINAL_ROW"
BOUNDARY_KINDS = frozenset({"CONTROL", "CANDLE", "FUNDING", "DEADLINE"})
UNIVERSE = frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"})
WINDOW_ONLY = "WINDOW_ONLY"
FIVE_DAY_WITH_ONE_DAY_EXIT_TAIL = "FIVE_DAY_WITH_ONE_DAY_EXIT_TAIL"


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _identifier(value):
    if (
        type(value) is not str
        or not 1 <= len(value) <= 128
        or any(not 33 <= ord(char) <= 126 for char in value)
    ):
        raise ValueError("normalized canonical ASCII identifier required")


def _clock(value):
    if type(value) is not int or not 0 <= value <= MAX_CLOCK_MS:
        raise ValueError("exact nonnegative bounded model clock required")


def _implementation():
    paths = [
        Path(__file__),
        *(
            Path(module.__file__)
            for module in (archive_batch_cursor_v3, archive_market_clock_v3, bookticker_archive_stream_v3)
        ),
    ]
    return _hash([[str(path.absolute()), hashlib.sha256(path.read_bytes()).hexdigest()] for path in paths])


@dataclass(frozen=True, slots=True)
class ArchivePortfolioLimitsV3:
    max_sources: int = 25
    max_boundaries: int = 100_000
    max_boundary_payload_bytes: int = 64 * 1024
    max_total_boundary_payload_bytes: int = 64 * 1024 * 1024
    max_batch_rows: int = 500
    max_batch_bytes: int = 2 * 1024 * 1024
    prefetch_rows: int = 500
    max_raw_buffer_bytes: int = 128 * 1024 * 1024
    max_decoded_rows: int = 100_000
    max_total_blocks: int = 1_000_000
    timeout_seconds: int = 1800
    window_profile: str = WINDOW_ONLY

    def __post_init__(self):
        if type(self.window_profile) is not str or self.window_profile not in {
            WINDOW_ONLY,
            FIVE_DAY_WITH_ONE_DAY_EXIT_TAIL,
        }:
            raise ValueError("explicit known retained-window profile required")
        caps = {
            "max_sources": 30 if self.window_profile == FIVE_DAY_WITH_ONE_DAY_EXIT_TAIL else 25,
            "max_boundaries": 100_000,
            "max_boundary_payload_bytes": 64 * 1024,
            "max_total_boundary_payload_bytes": 64 * 1024 * 1024,
            "max_batch_rows": 1000,
            "max_batch_bytes": 4 * 1024 * 1024,
            "prefetch_rows": 1000,
            "max_raw_buffer_bytes": 128 * 1024 * 1024,
            "max_decoded_rows": 1_000_000,
            "max_total_blocks": 2_500_000,
            "timeout_seconds": 86_400,
        }
        for name, cap in caps.items():
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= cap:
                raise ValueError(f"{name} exceeds explicit portfolio resource profile")


@dataclass(frozen=True, slots=True)
class ArchivePortfolioSourceV3:
    source_key: str
    index: ArchiveBatchIndexV3
    clock: ArchiveMarketClockV3

    def __post_init__(self):
        if (
            type(self.index) is not ArchiveBatchIndexV3
            or type(self.clock) is not ArchiveMarketClockV3
            or self.source_key != f"{self.index.symbol}:{self.index.transaction_day}"
        ):
            raise ValueError("exact symbol/day source key, index and model clock required")
        _identifier(self.source_key)

    @property
    def document(self):
        return {
            "source_key": self.source_key,
            "symbol": self.index.symbol,
            "day": self.index.transaction_day,
            "rows": self.index.row_count,
            "source_manifest_sha256": self.index.source_manifest_sha256,
            "index_manifest_sha256": self.index.manifest_sha256,
            "clock_policy_sha256": self.clock.sha256,
        }


@dataclass(frozen=True, slots=True)
class ArchivePortfolioBoundaryV3:
    boundary_id: str
    kind: str
    at_ms: int
    payload: bytes
    source_sha256: str

    def __post_init__(self):
        _identifier(self.boundary_id)
        _clock(self.at_ms)
        _sha(self.source_sha256, "boundary source SHA256")
        if type(self.kind) is not str or self.kind not in BOUNDARY_KINDS or type(self.payload) is not bytes:
            raise ValueError("explicit immutable boundary kind/payload required")

    @property
    def document(self):
        return {
            "boundary_id": self.boundary_id,
            "kind": self.kind,
            "at_ms": self.at_ms,
            "payload_sha256": hashlib.sha256(self.payload).hexdigest(),
            "payload_bytes": len(self.payload),
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True, slots=True)
class ArchivePortfolioSealV3:
    sources: tuple[ArchivePortfolioSourceV3, ...]
    symbols: tuple[str, ...]
    days: tuple[str, ...]
    boundaries: tuple[ArchivePortfolioBoundaryV3, ...]
    tie_rule: str
    boundary_tie_order: tuple[str, ...]
    limits: ArchivePortfolioLimitsV3
    entry_days: tuple[str, ...] = ()
    _sha256: str = field(init=False, repr=False)
    implementation_sha256: str = field(init=False)

    def __post_init__(self):
        if (
            type(self.limits) is not ArchivePortfolioLimitsV3
            or self.tie_rule != TIE_RULE
            or type(self.tie_rule) is not str
        ):
            raise ValueError("explicit supported source tie rule and limits required")
        if (
            type(self.symbols) is not tuple
            or not self.symbols
            or self.symbols != tuple(sorted(set(self.symbols)))
            or any(type(s) is not str or s not in UNIVERSE for s in self.symbols)
        ):
            raise ValueError("exact fixed-universe symbol roster required")
        maximum_days = 6 if self.limits.window_profile == FIVE_DAY_WITH_ONE_DAY_EXIT_TAIL else 5
        if (
            type(self.days) is not tuple
            or not 1 <= len(self.days) <= maximum_days
            or self.days != tuple(sorted(set(self.days)))
        ):
            raise ValueError("exact ordered days within explicit retained-window profile required")
        if type(self.entry_days) is not tuple:
            raise ValueError("exact immutable entry-day roster required")
        if self.limits.window_profile == FIVE_DAY_WITH_ONE_DAY_EXIT_TAIL:
            if len(self.days) != 6 or self.entry_days != self.days[:5]:
                raise ValueError(
                    "exit-tail profile requires exactly five entry days and one following retained day"
                )
        elif self.entry_days not in ((), self.days):
            raise ValueError("window-only profile requires entry days identical to retained days")
        else:
            object.__setattr__(self, "entry_days", self.days)
        starts = tuple(_day_start_ms(day) for day in self.days)
        if any(b - a != 86_400_000 for a, b in zip(starts, starts[1:], strict=False)):
            raise ValueError("fixed scenario days must be contiguous; no omitted day")
        if (
            type(self.sources) is not tuple
            or len(self.sources) > self.limits.max_sources
            or any(type(s) is not ArchivePortfolioSourceV3 for s in self.sources)
        ):
            raise ValueError("bounded exact source roster required")
        required = tuple(sorted(f"{symbol}:{day}" for symbol in self.symbols for day in self.days))
        if tuple(s.source_key for s in self.sources) != required:
            raise ValueError("every declared symbol/day index required once in canonical source order")
        if (
            type(self.boundary_tie_order) is not tuple
            or len(self.boundary_tie_order) != len(BOUNDARY_KINDS)
            or set(self.boundary_tie_order) != BOUNDARY_KINDS
        ):
            raise ValueError("explicit boundary-kind tie permutation required")
        if (
            type(self.boundaries) is not tuple
            or len(self.boundaries) > self.limits.max_boundaries
            or any(type(b) is not ArchivePortfolioBoundaryV3 for b in self.boundaries)
        ):
            raise ValueError("bounded immutable boundary roster required")
        order = {kind: ordinal for ordinal, kind in enumerate(self.boundary_tie_order)}
        if self.boundaries != tuple(
            sorted(self.boundaries, key=lambda b: (b.at_ms, order[b.kind], b.boundary_id))
        ) or len({b.boundary_id for b in self.boundaries}) != len(self.boundaries):
            raise ValueError("boundaries must be unique and follow exact sealed clock/kind/id order")
        if (
            any(
                b.at_ms < starts[0] or len(b.payload) > self.limits.max_boundary_payload_bytes
                for b in self.boundaries
            )
            or sum(len(b.payload) for b in self.boundaries) > self.limits.max_total_boundary_payload_bytes
        ):
            raise ValueError("boundary clock/payload capacity exceeded without filtering")
        if any(self.limits.prefetch_rows > s.index.limits.max_batch_rows for s in self.sources):
            raise ValueError("prefetch exceeds a sealed source batch-row profile")
        raw_bound = self.limits.max_batch_bytes + sum(
            s.index.limits.max_batch_bytes + s.index.limits.max_block_bytes for s in self.sources
        )
        decoded_bound = self.limits.max_batch_rows + sum(
            self.limits.prefetch_rows + max(b.row_count for b in s.index.blocks) for s in self.sources
        )
        if (
            raw_bound > self.limits.max_raw_buffer_bytes
            or decoded_bound > self.limits.max_decoded_rows
            or sum(len(s.index.blocks) for s in self.sources) > self.limits.max_total_blocks
        ):
            raise ValueError("aggregate source buffer/decoded-row/block capacity exceeded")
        implementation = _implementation()
        object.__setattr__(self, "implementation_sha256", implementation)
        digest = hashlib.sha256(
            _canonical(
                {
                    "schema": SCHEMA,
                    "clock_evidence": "MODELED_REFERENCE",
                    "symbols": self.symbols,
                    "days": self.days,
                    "entry_days": self.entry_days,
                    "retained_window_profile": self.limits.window_profile,
                    "sources": [s.document for s in self.sources],
                    "tie_rule": self.tie_rule,
                    "boundary_tie_order": self.boundary_tie_order,
                    "limits": asdict(self.limits),
                    "implementation_sha256": implementation,
                }
            )
        )
        for boundary in self.boundaries:
            digest.update(b"\n" + _canonical(boundary.document))
        object.__setattr__(self, "_sha256", digest.hexdigest())

    @property
    def sha256(self):
        return self._sha256


@dataclass(frozen=True, slots=True)
class ArchivePortfolioSourceCheckpointV3:
    source_key: str
    cursor: ArchiveCursorCheckpointV3

    def __post_init__(self):
        _identifier(self.source_key)
        if type(self.cursor) is not ArchiveCursorCheckpointV3:
            raise ValueError("exact retained source cursor required")


@dataclass(frozen=True, slots=True)
class ArchivePortfolioCheckpointV3:
    seal_sha256: str
    source_vector: tuple[ArchivePortfolioSourceCheckpointV3, ...]
    global_row_count: int
    boundary_cursor: int
    operation_count: int
    last_clock_ms: int
    prefix_sha256: str

    def __post_init__(self):
        _sha(self.seal_sha256, "portfolio seal SHA256")
        _sha(self.prefix_sha256, "portfolio prefix SHA256")
        _clock(self.last_clock_ms)
        if (
            any(
                type(x) is not int or x < 0
                for x in (self.global_row_count, self.boundary_cursor, self.operation_count)
            )
            or type(self.source_vector) is not tuple
            or len(self.source_vector) > 30
            or any(type(x) is not ArchivePortfolioSourceCheckpointV3 for x in self.source_vector)
        ):
            raise ValueError("exact bounded global/vector checkpoint required")
        if sum(x.cursor.next_row for x in self.source_vector) != self.global_row_count:
            raise ValueError("global source row denominator differs from exact vector")


@dataclass(frozen=True, slots=True)
class ArchivePortfolioRowV3:
    source_key: str
    global_sequence: int
    original: BookTickerArchiveRowV3
    quote: ArchiveBBOQuoteV3


@dataclass(frozen=True, slots=True)
class ArchivePortfolioOperationV3:
    kind: str
    operation_id: str
    at_ms: int
    before: ArchivePortfolioCheckpointV3
    after: ArchivePortfolioCheckpointV3
    rows: tuple[ArchivePortfolioRowV3, ...]
    boundary: ArchivePortfolioBoundaryV3 | None
    raw_byte_count: int
    source_rows_at_clock_remaining: bool
    boundaries_at_clock_remaining: bool

    @property
    def sha256(self):
        return _hash(
            {
                "schema": SCHEMA,
                "clock_evidence": "MODELED_REFERENCE",
                "kind": self.kind,
                "operation_id": self.operation_id,
                "at_ms": self.at_ms,
                "before": asdict(self.before),
                "after": asdict(self.after),
                "rows": [
                    {
                        "source_key": row.source_key,
                        "global_sequence": row.global_sequence,
                        "row_index": row.original.row_index,
                        "line_sha256": row.quote.original_line_sha256,
                        "clock_policy_sha256": row.quote.clock_policy_sha256,
                        "event_at_ms": row.quote.event_at_ms,
                        "modeled_available_at_ms": row.quote.modeled_available_at_ms,
                    }
                    for row in self.rows
                ],
                "boundary": None if self.boundary is None else self.boundary.document,
                "raw_byte_count": self.raw_byte_count,
                "source_rows_at_clock_remaining": self.source_rows_at_clock_remaining,
                "boundaries_at_clock_remaining": self.boundaries_at_clock_remaining,
            }
        )


@dataclass(frozen=True, slots=True)
class ArchivePortfolioPendingAnchorV3:
    before: ArchivePortfolioCheckpointV3
    after: ArchivePortfolioCheckpointV3
    operation_id: str
    operation_sha256: str

    def __post_init__(self):
        if (
            type(self.before) is not ArchivePortfolioCheckpointV3
            or type(self.after) is not ArchivePortfolioCheckpointV3
        ):
            raise ValueError("exact independently retained pending anchors required")
        _identifier(self.operation_id)
        _sha(self.operation_sha256, "pending operation SHA256")


class ArchivePortfolioStreamV3:
    """Bounded k-way merge, explicit prepare/ack, independent exact recovery.

    The bounded cursor's read-only block primitives are reused for batched
    authentication, never row_at/whole-segment rehash per row. That private API
    boundary is pinned by the seal's implementation fingerprint. Resource
    bounds cover raw buffers/record counts, not measured total Python heap.
    Source cursor prefixes and the global merge frontier are checked on
    restart. The global prefix is an independently retained anchor, not a
    claim that this reader replays the whole prior multi-source history.
    """

    def __init__(self, seal, *, expected_seal_sha256, expected_checkpoint=None):
        if (
            type(seal) is not ArchivePortfolioSealV3
            or seal.sha256 != expected_seal_sha256
            or seal.implementation_sha256 != _implementation()
        ):
            raise ValueError("independently pinned exact portfolio seal required")
        _sha(expected_seal_sha256, "expected portfolio seal SHA256")
        self._seal = seal
        self._lock = threading.RLock()
        self._sources = {s.source_key: s for s in seal.sources}
        self._keys = tuple(self._sources)
        initial_vector = tuple(
            ArchivePortfolioSourceCheckpointV3(
                s.source_key,
                ArchiveCursorCheckpointV3(
                    s.index.manifest_sha256,
                    s.index.source_manifest_sha256,
                    s.clock.sha256,
                    0,
                    _genesis(s.index.source_manifest_sha256),
                ),
            )
            for s in seal.sources
        )
        initial = ArchivePortfolioCheckpointV3(
            seal.sha256,
            initial_vector,
            0,
            0,
            0,
            _day_start_ms(seal.days[0]),
            _hash([SCHEMA, seal.sha256, "GLOBAL_PREFIX"]),
        )
        if expected_checkpoint is not None and (
            type(expected_checkpoint) is not ArchivePortfolioCheckpointV3
            or expected_checkpoint.seal_sha256 != seal.sha256
        ):
            raise ValueError("independent global checkpoint/seal mismatch")
        self._committed = initial if expected_checkpoint is None else expected_checkpoint
        self._pending = None
        self._poisoned = False
        self._restore(self._committed, initial)

    @property
    def seal(self):
        return self._seal

    def checkpoint(self):
        with self._lock:
            return self._committed

    def _check_time(self, deadline):
        if time.monotonic() > deadline:
            raise TimeoutError("portfolio operation exceeded explicit bounded timeout")

    def _restore(self, checkpoint, initial=None):
        if tuple(
            x.source_key for x in checkpoint.source_vector
        ) != self._keys or checkpoint.boundary_cursor > len(self.seal.boundaries):
            raise ValueError("global checkpoint exact source/boundary roster mismatch")
        if checkpoint.operation_count == 0 and (initial is None or checkpoint != initial):
            # Rollback to genesis uses the already retained exact initial value.
            if (
                checkpoint.global_row_count != 0
                or checkpoint.boundary_cursor != 0
                or checkpoint.prefix_sha256 != _hash([SCHEMA, self.seal.sha256, "GLOBAL_PREFIX"])
                or checkpoint.last_clock_ms != _day_start_ms(self.seal.days[0])
            ):
                raise ValueError("global checkpoint genesis mismatch")
        if (
            checkpoint.operation_count > checkpoint.global_row_count + checkpoint.boundary_cursor
            or checkpoint.operation_count < checkpoint.boundary_cursor
        ):
            raise ValueError("checkpoint operation/denominator count mismatch")
        self._readers, self._buffers, self._positions, self._heap = {}, {}, {}, []
        deadline = time.monotonic() + self.seal.limits.timeout_seconds
        prior_source_key = None
        for retained in checkpoint.source_vector:
            self._check_time(deadline)
            source = self._sources[retained.source_key]
            reader = source.index.cursor(clock=source.clock, expected_checkpoint=retained.cursor)
            self._readers[retained.source_key] = reader
            self._buffers[retained.source_key] = ()
            self._positions[retained.source_key] = 0
            if retained.cursor.next_row:
                original = reader.lookup_row(retained.cursor.next_row - 1)
                quote = archive_quote_v3(
                    original, clock=source.clock, source_manifest_sha256=source.index.source_manifest_sha256
                )
                key = (quote.modeled_available_at_ms, source.source_key, original.row_index)
                prior_source_key = key if prior_source_key is None else max(prior_source_key, key)
            self._refill(retained.source_key, deadline)
        prior_boundary = (
            None if checkpoint.boundary_cursor == 0 else self.seal.boundaries[checkpoint.boundary_cursor - 1]
        )
        if prior_source_key is not None and self._heap and self._heap[0][:3] < prior_source_key:
            raise ValueError("checkpoint omitted an earlier/tied original source row")
        if prior_boundary is not None and self._heap and self._heap[0][0] <= prior_boundary.at_ms:
            raise ValueError("checkpoint boundary skipped a source-before-equal-command row")
        if (
            checkpoint.boundary_cursor < len(self.seal.boundaries)
            and prior_source_key is not None
            and self.seal.boundaries[checkpoint.boundary_cursor].at_ms < prior_source_key[0]
        ):
            raise ValueError("checkpoint skipped a frozen boundary")
        expected_clock = max(
            _day_start_ms(self.seal.days[0]),
            0 if prior_source_key is None else prior_source_key[0],
            0 if prior_boundary is None else prior_boundary.at_ms,
        )
        if checkpoint.last_clock_ms != expected_clock:
            raise ValueError("checkpoint last clock differs from exact consumed frontier")
        self._check_time(deadline)

    def _refill(self, source_key, deadline):
        self._check_time(deadline)
        batch = self._readers[source_key].read_batch(max_rows=self.seal.limits.prefetch_rows)
        self._buffers[source_key] = tuple(zip(batch.rows, batch.quotes, strict=True))
        self._positions[source_key] = 0
        self._check_time(deadline)
        if batch.rows:
            row, quote = self._buffers[source_key][0]
            heapq.heappush(self._heap, (quote.modeled_available_at_ms, source_key, row.row_index))

    def _consume_head(self, deadline):
        _, source_key, _ = heapq.heappop(self._heap)
        position = self._positions[source_key]
        row, quote = self._buffers[source_key][position]
        self._positions[source_key] = position + 1
        if position + 1 == len(self._buffers[source_key]):
            self._refill(source_key, deadline)
        else:
            next_row, next_quote = self._buffers[source_key][position + 1]
            heapq.heappush(self._heap, (next_quote.modeled_available_at_ms, source_key, next_row.row_index))
        return source_key, row, quote

    def _authenticate_rows(self, rows, deadline):
        grouped = {}
        for row in rows:
            grouped.setdefault(row.source_key, []).append(row)
        for source_key, values in grouped.items():
            reader = self._readers[source_key]
            reader._checked_blocks.clear()
            reader._fence()
            for number in sorted(
                {bisect.bisect_right(reader._starts, row.original.row_index) - 1 for row in values}
            ):
                authenticated = reader._load_block(number, deadline)
                first_row = reader.index.blocks[number].first_row
                for row in values:
                    offset = row.original.row_index - first_row
                    if 0 <= offset < len(authenticated) and authenticated[offset] != row.original:
                        raise ValueError("prefetched row differs from authenticated original block")
            reader._fence()
            for segment in {
                reader.index.blocks[bisect.bisect_right(reader._starts, row.original.row_index) - 1].segment
                for row in values
            }:
                if (
                    _identity(_regular_nofollow(reader.index.source_root / segment))
                    != reader._identities[segment]
                ):
                    raise ValueError("original source changed before portfolio handoff")
            self._check_time(deadline)

    def prepare_next(self):
        with self._lock:
            if self._poisoned:
                raise ValueError("portfolio stream poisoned; recover only an independent retained checkpoint")
            if self._pending is not None:
                return self._pending
            before = self._committed
            boundary = (
                None
                if before.boundary_cursor == len(self.seal.boundaries)
                else self.seal.boundaries[before.boundary_cursor]
            )
            if not self._heap and boundary is None:
                return None
            deadline = time.monotonic() + self.seal.limits.timeout_seconds
            vectors = {x.source_key: x.cursor for x in before.source_vector}
            prefix, count, size, rows = before.prefix_sha256, before.global_row_count, 0, []
            boundary_cursor = before.boundary_cursor
            try:
                if self._heap and (boundary is None or self._heap[0][0] <= boundary.at_ms):
                    kind = "SOURCE_BATCH"
                    while (
                        self._heap
                        and len(rows) < self.seal.limits.max_batch_rows
                        and (boundary is None or self._heap[0][0] <= boundary.at_ms)
                    ):
                        self._check_time(deadline)
                        source_key = self._heap[0][1]
                        candidate = self._buffers[source_key][self._positions[source_key]][0]
                        if size + len(candidate.raw_csv_line) > self.seal.limits.max_batch_bytes:
                            if not rows:
                                raise ValueError("one original row exceeds portfolio batch byte bound")
                            break
                        source_key, original, quote = self._consume_head(deadline)
                        old = vectors[source_key]
                        if original.row_index != old.next_row:
                            raise ValueError("source vector would omit/duplicate an original row")
                        vectors[source_key] = ArchiveCursorCheckpointV3(
                            old.index_manifest_sha256,
                            old.source_manifest_sha256,
                            old.clock_policy_sha256,
                            old.next_row + 1,
                            _advance(old.prefix_sha256, original.row_index, original.raw_csv_line),
                        )
                        count += 1
                        prefix = _hash(
                            [
                                prefix,
                                "SOURCE",
                                source_key,
                                original.row_index,
                                quote.original_line_sha256,
                                quote.clock_policy_sha256,
                                quote.modeled_available_at_ms,
                            ]
                        )
                        rows.append(ArchivePortfolioRowV3(source_key, count, original, quote))
                        size += len(original.raw_csv_line)
                    selected_boundary = None
                    at_ms = rows[-1].quote.modeled_available_at_ms
                    self._authenticate_rows(rows, deadline)
                else:
                    kind = boundary.kind
                    selected_boundary = boundary
                    at_ms = boundary.at_ms
                    prefix = _hash([prefix, "BOUNDARY", boundary_cursor, boundary.document])
                    boundary_cursor += 1
                if at_ms < before.last_clock_ms:
                    raise ValueError("global modeled clock regressed")
                next_boundary = (
                    None
                    if boundary_cursor == len(self.seal.boundaries)
                    else self.seal.boundaries[boundary_cursor]
                )
                source_remaining = bool(self._heap and self._heap[0][0] == at_ms)
                boundary_remaining = bool(next_boundary is not None and next_boundary.at_ms == at_ms)
                after = ArchivePortfolioCheckpointV3(
                    self.seal.sha256,
                    tuple(ArchivePortfolioSourceCheckpointV3(key, vectors[key]) for key in self._keys),
                    count,
                    boundary_cursor,
                    before.operation_count + 1,
                    at_ms,
                    prefix,
                )
                operation_id = f"portfolio-op:{after.operation_count}:{prefix[:32]}"
                self._check_time(deadline)
                operation = ArchivePortfolioOperationV3(
                    kind,
                    operation_id,
                    at_ms,
                    before,
                    after,
                    tuple(rows),
                    selected_boundary,
                    size,
                    source_remaining,
                    boundary_remaining,
                )
            except (ValueError, OSError, TimeoutError):
                self._poisoned = True
                raise
            self._pending = operation
            return operation

    def acknowledge(self, operation):
        with self._lock:
            if (
                self._poisoned
                or operation is not self._pending
                or type(operation) is not ArchivePortfolioOperationV3
                or operation.before != self._committed
            ):
                raise ValueError("acknowledgement must match the one exact owned pending operation")
            self._committed = operation.after
            self._pending = None
            return self._committed

    def discard_pending(self, *, expected_before):
        with self._lock:
            if (
                type(expected_before) is not ArchivePortfolioCheckpointV3
                or expected_before != self._committed
            ):
                raise ValueError("independent before checkpoint required; no latest adoption")
            # A failed reopen cannot leave the old operation acknowledgeable
            # with a partially replaced volatile reader set.
            self._pending = None
            self._poisoned = True
            self._restore(expected_before)
            self._poisoned = False

    @classmethod
    def recover_pending(cls, seal, *, expected_seal_sha256, retained_anchor):
        if type(retained_anchor) is not ArchivePortfolioPendingAnchorV3:
            raise ValueError("typed independently retained pending operation required")
        stream = cls(
            seal, expected_seal_sha256=expected_seal_sha256, expected_checkpoint=retained_anchor.before
        )
        operation = stream.prepare_next()
        if (
            operation is None
            or operation.after != retained_anchor.after
            or operation.operation_id != retained_anchor.operation_id
            or operation.sha256 != retained_anchor.operation_sha256
        ):
            raise ValueError("retained pending operation is not the exact deterministic next operation")
        return stream, operation
