import hashlib
import json
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

import adaptive_replay.archive_batch_cursor_v3 as module
from adaptive_replay.archive_batch_cursor_v3 import (
    ArchiveBatchLimitsV3,
    build_archive_batch_index_v3,
    open_archive_batch_index_v3,
)
from adaptive_replay.archive_market_clock_v3 import ArchiveMarketClockV3
from adaptive_replay.bookticker_archive_stream_v3 import (
    HEADER,
    StreamLimitsV3,
    build_bookticker_archive_stream_v3,
)

ROWS = [
    b"10,100.00,1.250,100.10,2.00,1704672000006,1704672000012\r\n",
    b"11,100.01,1.5,100.11,2.5,1704672000010,1704672000012\r\n",
    b"12,100.02,1.75,100.12,2.75,1704672000020,1704672000025\r\n",
    b"13,100.03,1.875,100.13,3.00,1704758399998,1704758400005\r\n",
]
CLOCK = ArchiveMarketClockV3("TRANSACTION_T", 3, 2)


def _source(tmp_path):
    payload = HEADER + b"\r\n" + b"".join(ROWS)
    archive = tmp_path / "input.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as stream:
        stream.writestr("BTCUSDT-bookTicker-2024-01-08.csv", payload)
    return build_bookticker_archive_stream_v3(
        archive,
        tmp_path / "source",
        symbol="BTCUSDT",
        transaction_day="2024-01-08",
        expected_archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        expected_rows=len(ROWS),
        expected_uncompressed_bytes=len(payload),
        expected_uncompressed_sha256=hashlib.sha256(payload).hexdigest(),
        limits=StreamLimitsV3(
            max_archive_bytes=10_000,
            max_uncompressed_bytes=10_000,
            max_rows=20,
            segment_bytes=300,
            index_stride=2,
            max_line_bytes=256,
            max_segments=20,
        ),
        evidence_kind="TEST_FIXTURE",
    )


def _index(tmp_path, **overrides):
    source = _source(tmp_path)
    limits = ArchiveBatchLimitsV3(
        **{"max_block_bytes": 120, "max_batch_rows": 3, "max_batch_bytes": 200, **overrides}
    )
    return build_archive_batch_index_v3(
        source, tmp_path / "index", expected_source_manifest_sha256=source.manifest_sha256, limits=limits
    )


def _open(index):
    return open_archive_batch_index_v3(
        index.root,
        index.source_root,
        expected_index_manifest_sha256=index.manifest_sha256,
        expected_source_manifest_sha256=index.source_manifest_sha256,
    )


def test_all_original_rows_bytes_and_ties_are_retained(tmp_path):
    index = _index(tmp_path)
    cursor = index.cursor(clock=CLOCK)
    batches = [cursor.read_batch(max_rows=3), cursor.read_batch(max_rows=3)]
    assert [row.raw_csv_line for batch in batches for row in batch.rows] == ROWS
    assert batches[0].after == batches[1].before
    assert cursor.checkpoint().next_row == 4
    assert cursor.checkpoint().prefix_sha256 == index.prefix_final
    assert sum(b.raw_byte_count for b in batches) == sum(map(len, ROWS))
    assert all(q.historical_received_at_ms is None for batch in batches for q in batch.quotes)
    assert batches[0].quotes[0].modeled_available_at_ms == batches[0].quotes[1].modeled_available_at_ms
    assert cursor.read_batch(max_rows=1).rows == ()
    original_manifest = json.loads((index.source_root / "manifest.json").read_bytes())
    derived = json.loads((index.root / "manifest.json").read_bytes())
    assert derived["source_csv"] == original_manifest["csv"]
    assert derived["source_archive"] == original_manifest["archive"]
    assert derived["source_identities_before"] == derived["source_identities_after"]


def test_inclusive_cutoff_keeps_all_ties_and_never_skips_next(tmp_path):
    index = _index(tmp_path)
    cursor = index.cursor(clock=CLOCK)
    first = cursor.read_batch(max_rows=3, stop_modeled_available_ms=1704672000017)
    assert [r.row_index for r in first.rows] == [0, 1]
    assert cursor.read_batch(max_rows=3, stop_modeled_available_ms=1704672000017).rows == ()
    assert [r.row_index for r in cursor.read_batch(max_rows=3).rows] == [2, 3]


def test_restart_middle_block_and_readonly_membership_lookup(tmp_path):
    index = _index(tmp_path, max_block_bytes=200)
    first = index.cursor(clock=CLOCK)
    batch = first.read_batch(max_rows=1)
    restarted = _open(index).cursor(clock=CLOCK, expected_checkpoint=batch.after)
    assert restarted.lookup_row(0).raw_csv_line == ROWS[0]
    assert restarted.lookup_row(3).raw_csv_line == ROWS[3]
    assert restarted.checkpoint() == batch.after
    assert restarted.read_batch(max_rows=3).sha256 == first.read_batch(max_rows=3).sha256
    assert (
        index.cursor(clock=CLOCK, expected_checkpoint=restarted.checkpoint()).checkpoint()
        == restarted.checkpoint()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("prefix_sha256", "f" * 64),
        ("source_manifest_sha256", "f" * 64),
        ("index_manifest_sha256", "f" * 64),
        ("clock_policy_sha256", "f" * 64),
        ("next_row", 5),
    ],
)
def test_wrong_independent_restart_anchor_rejected(tmp_path, field, value):
    index = _index(tmp_path)
    checkpoint = index.cursor(clock=CLOCK).read_batch(max_rows=1).after
    with pytest.raises(ValueError):
        index.cursor(clock=CLOCK, expected_checkpoint=replace(checkpoint, **{field: value}))


def test_bounded_block_read_not_segmentwide_row_at(tmp_path, monkeypatch):
    index = _index(tmp_path)
    monkeypatch.setattr(
        module.BookTickerArchiveStreamV3, "row_at", lambda *a: pytest.fail("segment-wide point lookup")
    )
    monkeypatch.setattr(
        module.BookTickerArchiveStreamV3, "iter_rows", lambda *a: pytest.fail("segment-wide repeated read")
    )
    original_open = module._open_regular
    reads = []

    class Spy:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size):
            reads.append(size)
            return self.stream.read(size)

    def spy(path):
        stream, metadata = original_open(path)
        return (Spy(stream) if path.name.startswith("segment-") else stream), metadata

    monkeypatch.setattr(module, "_open_regular", spy)
    cursor = index.cursor(clock=CLOCK)
    cursor.read_batch(max_rows=3)
    cursor.read_batch(max_rows=3)
    assert reads and max(reads) <= index.limits.max_block_bytes
    assert sum(reads) <= sum(len(row) for row in ROWS) + index.limits.max_block_bytes


@pytest.mark.parametrize("restore_stat", [False, True])
def test_cached_active_source_mutation_poisoned_without_cursor_advance(tmp_path, restore_stat):
    index = _index(tmp_path, max_block_bytes=200)
    cursor = index.cursor(clock=CLOCK)
    cursor.read_batch(max_rows=1)
    before = cursor.checkpoint()
    path = index.source_root / index.blocks[0].segment
    metadata = path.stat()
    raw = path.read_bytes().replace(b"100.01", b"100.09")
    path.write_bytes(raw)
    if restore_stat:
        os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    with pytest.raises(ValueError):
        cursor.read_batch(max_rows=1)
    assert cursor.checkpoint() == before
    with pytest.raises(ValueError, match="poisoned"):
        cursor.lookup_row(0)
    with pytest.raises(ValueError):
        _open(index)


@pytest.mark.parametrize("target", ["source_manifest", "index_manifest", "blocks", "sparse_index"])
def test_metadata_mutation_refuses_read(tmp_path, target):
    index = _index(tmp_path)
    cursor = index.cursor(clock=CLOCK)
    before = cursor.checkpoint()
    path = {
        "source_manifest": index.source_root / "manifest.json",
        "index_manifest": index.root / "manifest.json",
        "blocks": index.root / "blocks.jsonl",
        "sparse_index": index.source_root / "sparse-index.jsonl",
    }[target]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError):
        cursor.read_batch(max_rows=1)
    assert cursor.checkpoint() == before


@pytest.mark.parametrize(
    "limits", [{"max_block_bytes": 10}, {"max_blocks": 1}, {"max_index_bytes": 10}, {"max_batch_bytes": 10}]
)
def test_capacity_failure_does_not_publish_acceptance_marker(tmp_path, limits):
    with pytest.raises(ValueError):
        _index(tmp_path, **limits)
    assert not (tmp_path / "index" / "manifest.json").exists()
    assert (tmp_path / "source" / "manifest.json").is_file()


@pytest.mark.parametrize(
    "limits",
    [
        {"max_block_bytes": 2**30},
        {"max_batch_rows": True},
        {"max_batch_rows": 1001},
        {"timeout_seconds": 0},
        {"max_index_bytes": 2**30},
    ],
)
def test_unbounded_or_bool_resource_profile_refused(limits):
    with pytest.raises(ValueError):
        ArchiveBatchLimitsV3(**limits)


def test_create_only_and_invalid_request_not_poisoning(tmp_path):
    index = _index(tmp_path)
    cursor = index.cursor(clock=CLOCK)
    for kwargs in ({"max_rows": True}, {"max_rows": 4}, {"max_rows": 1, "stop_modeled_available_ms": True}):
        with pytest.raises(ValueError):
            cursor.read_batch(**kwargs)
    assert cursor.read_batch(max_rows=1).rows[0].raw_csv_line == ROWS[0]
    source = module.open_bookticker_archive_stream_v3(
        index.source_root, expected_manifest_sha256=index.source_manifest_sha256
    )
    with pytest.raises(FileExistsError):
        build_archive_batch_index_v3(
            source,
            index.root,
            expected_source_manifest_sha256=index.source_manifest_sha256,
            limits=index.limits,
        )


def test_source_mutation_during_derivation_never_publishes(tmp_path, monkeypatch):
    source = _source(tmp_path)
    original = module.open_bookticker_archive_stream_v3
    calls = 0

    def mutate(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            path = source.root / "segment-000001.csv"
            path.write_bytes(path.read_bytes().replace(b"100.00", b"100.09"))
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "open_bookticker_archive_stream_v3", mutate)
    with pytest.raises(ValueError):
        build_archive_batch_index_v3(
            source,
            tmp_path / "index",
            expected_source_manifest_sha256=source.manifest_sha256,
            limits=ArchiveBatchLimitsV3(max_block_bytes=120),
        )
    assert not (tmp_path / "index" / "manifest.json").exists()


@pytest.mark.parametrize("operation", ["truncate", "remove", "replace"])
def test_original_segment_unavailable_or_replaced_never_advances(tmp_path, operation):
    index = _index(tmp_path)
    cursor = index.cursor(clock=CLOCK)
    before = cursor.checkpoint()
    path = index.source_root / index.blocks[0].segment
    raw = path.read_bytes()
    if operation == "truncate":
        path.write_bytes(raw[:-1])
    elif operation == "remove":
        path.unlink()
    else:
        replacement = path.parent / "replacement.csv"
        replacement.write_bytes(raw)
        os.replace(replacement, path)
    with pytest.raises(ValueError):
        cursor.read_batch(max_rows=1)
    assert cursor.checkpoint() == before


def test_create_only_marker_publication_failure_leaves_no_partial_manifest(tmp_path, monkeypatch):
    source = _source(tmp_path)

    def crash_before_publish(*args):
        raise OSError("test publication crash")

    monkeypatch.setattr(module.os, "link", crash_before_publish)
    with pytest.raises(OSError, match="publication crash"):
        build_archive_batch_index_v3(
            source,
            tmp_path / "index",
            expected_source_manifest_sha256=source.manifest_sha256,
            limits=ArchiveBatchLimitsV3(),
        )
    assert not (tmp_path / "index" / "manifest.json").exists()
    assert (tmp_path / "index" / "manifest.json.tmp").is_file()


def test_forged_handle_and_policy_reassignment_are_not_adopted(tmp_path):
    index = _index(tmp_path)
    with pytest.raises(ValueError, match="handle differs"):
        replace(index, row_count=index.row_count - 1).cursor(clock=CLOCK)
    block = replace(index.blocks[0], prefix_before="f" * 64)
    with pytest.raises(ValueError, match="handle differs"):
        replace(index, blocks=(block,) + index.blocks[1:]).cursor(clock=CLOCK)
    cursor = index.cursor(clock=CLOCK)
    with pytest.raises(AttributeError):
        cursor.clock = ArchiveMarketClockV3("EVENT_E", 0, 0)
    with pytest.raises(AttributeError):
        cursor.index = index


def test_rehashed_index_cannot_omit_or_overlap_source_bytes(tmp_path):
    index = _index(tmp_path)
    path = index.root / "blocks.jsonl"
    blocks = [json.loads(line) for line in path.read_bytes().splitlines()]
    blocks[0]["offset"] += 1
    raw_blocks = b"".join(module._canonical(block) + b"\n" for block in blocks)
    path.write_bytes(raw_blocks)
    manifest = json.loads((index.root / "manifest.json").read_bytes())
    manifest["blocks"]["bytes"] = len(raw_blocks)
    manifest["blocks"]["sha256"] = hashlib.sha256(raw_blocks).hexdigest()
    raw_manifest = module._canonical(manifest) + b"\n"
    (index.root / "manifest.json").write_bytes(raw_manifest)
    with pytest.raises(ValueError, match="coverage"):
        open_archive_batch_index_v3(
            index.root,
            index.source_root,
            expected_index_manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
            expected_source_manifest_sha256=index.source_manifest_sha256,
        )


def test_same_cursor_concurrent_batches_cannot_downgrade_or_duplicate(tmp_path):
    index = _index(tmp_path)
    cursor = index.cursor(clock=CLOCK)
    with ThreadPoolExecutor(max_workers=4) as workers:
        batches = list(workers.map(lambda _: cursor.read_batch(max_rows=1), range(4)))
    assert sorted(batch.rows[0].row_index for batch in batches) == [0, 1, 2, 3]
    assert cursor.checkpoint().next_row == 4
    ordered = sorted(batches, key=lambda batch: batch.before.next_row)
    assert all(a.after == b.before for a, b in zip(ordered, ordered[1:], strict=False))


def test_missing_segment_truncation_and_timeout_failclosed(tmp_path, monkeypatch):
    index = _index(tmp_path)
    cursor = index.cursor(clock=CLOCK)
    before = cursor.checkpoint()

    def expired(deadline):
        raise TimeoutError("test bounded timeout")

    monkeypatch.setattr(module, "_deadline_check", expired)
    with pytest.raises(TimeoutError):
        cursor.read_batch(max_rows=1)
    assert cursor.checkpoint() == before
    with pytest.raises(ValueError, match="poisoned"):
        cursor.read_batch(max_rows=1)


def test_final_fence_exceeding_deadline_does_not_advance(tmp_path, monkeypatch):
    index = _index(tmp_path)
    cursor = index.cursor(clock=CLOCK)
    before = cursor.checkpoint()
    original_fence = cursor._fence
    expired = False
    fences = 0

    def late_fence():
        nonlocal fences, expired
        original_fence()
        fences += 1
        if fences == 2:
            expired = True

    original_check = module._deadline_check

    def check(deadline):
        if expired:
            raise TimeoutError("final fence exceeded deadline")
        original_check(deadline)

    monkeypatch.setattr(cursor, "_fence", late_fence)
    monkeypatch.setattr(module, "_deadline_check", check)
    with pytest.raises(TimeoutError, match="final fence"):
        cursor.read_batch(max_rows=1)
    assert cursor.checkpoint() == before
    with pytest.raises(ValueError, match="poisoned"):
        cursor.read_batch(max_rows=1)


def test_final_used_segment_stat_exceeding_deadline_does_not_advance(tmp_path, monkeypatch):
    index = _index(tmp_path)
    cursor = index.cursor(clock=CLOCK)
    before = cursor.checkpoint()
    timer = {"now": 0, "fences": 0}
    original_fence = cursor._fence
    original_regular = module._regular_nofollow

    def fence():
        original_fence()
        timer["fences"] += 1

    def slow_stat(path):
        metadata = original_regular(path)
        if timer["fences"] == 2 and path.name.startswith("segment-"):
            timer["now"] = index.limits.timeout_seconds + 1
        return metadata

    monkeypatch.setattr(module.time, "monotonic", lambda: timer["now"])
    monkeypatch.setattr(cursor, "_fence", fence)
    monkeypatch.setattr(module, "_regular_nofollow", slow_stat)
    with pytest.raises(TimeoutError):
        cursor.read_batch(max_rows=1)
    assert cursor.checkpoint() == before


@pytest.mark.parametrize("slow_part", ["fence", "block"])
def test_lookup_deadline_includes_fence_and_final_read(tmp_path, monkeypatch, slow_part):
    index = _index(tmp_path)
    cursor = index.cursor(clock=CLOCK)
    before = cursor.checkpoint()
    timer = {"now": 0}
    original_fence, original_load = cursor._fence, cursor._load_block

    def slow_fence():
        original_fence()
        if slow_part == "fence":
            timer["now"] = index.limits.timeout_seconds + 1

    def slow_load(number, deadline):
        result = original_load(number, deadline)
        if slow_part == "block":
            timer["now"] = index.limits.timeout_seconds + 1
        return result

    monkeypatch.setattr(module.time, "monotonic", lambda: timer["now"])
    monkeypatch.setattr(cursor, "_fence", slow_fence)
    monkeypatch.setattr(cursor, "_load_block", slow_load)
    with pytest.raises(TimeoutError):
        cursor.lookup_row(0)
    assert cursor.checkpoint() == before
    with pytest.raises(ValueError, match="poisoned"):
        cursor.lookup_row(0)
