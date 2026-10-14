import hashlib
import os
import zipfile
from dataclasses import replace

import pytest

import adaptive_replay.archive_portfolio_stream_v3 as module
from adaptive_replay.archive_batch_cursor_v3 import ArchiveBatchLimitsV3, build_archive_batch_index_v3
from adaptive_replay.archive_market_clock_v3 import ArchiveMarketClockV3
from adaptive_replay.archive_portfolio_stream_v3 import (
    FIVE_DAY_WITH_ONE_DAY_EXIT_TAIL,
    TIE_RULE,
    WINDOW_ONLY,
    ArchivePortfolioBoundaryV3,
    ArchivePortfolioLimitsV3,
    ArchivePortfolioPendingAnchorV3,
    ArchivePortfolioSealV3,
    ArchivePortfolioSourceV3,
    ArchivePortfolioStreamV3,
)
from adaptive_replay.bookticker_archive_stream_v3 import (
    HEADER,
    StreamLimitsV3,
    _day_start_ms,
    build_bookticker_archive_stream_v3,
)

ORDER = ("FUNDING", "CANDLE", "DEADLINE", "CONTROL")
CLOCK = ArchiveMarketClockV3("TRANSACTION_T", 3, 2)
START = _day_start_ms("2024-01-08")


def _source(tmp_path, symbol, day, times):
    root = tmp_path / f"{symbol}-{day}"
    root.mkdir()
    rows = tuple(f"{i + 10},100.00,1.25,100.10,2.00,{t},{e}\r\n".encode() for i, (t, e) in enumerate(times))
    payload = HEADER + b"\r\n" + b"".join(rows)
    archive = root / "input.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr(f"{symbol}-bookTicker-{day}.csv", payload)
    source = build_bookticker_archive_stream_v3(
        archive,
        root / "source",
        symbol=symbol,
        transaction_day=day,
        expected_archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        expected_rows=len(rows),
        expected_uncompressed_bytes=len(payload),
        expected_uncompressed_sha256=hashlib.sha256(payload).hexdigest(),
        limits=StreamLimitsV3(
            max_archive_bytes=10000,
            max_uncompressed_bytes=10000,
            max_rows=20,
            segment_bytes=300,
            index_stride=2,
            max_line_bytes=256,
            max_segments=20,
        ),
        evidence_kind="TEST_FIXTURE",
    )
    index = build_archive_batch_index_v3(
        source,
        root / "index",
        expected_source_manifest_sha256=source.manifest_sha256,
        limits=ArchiveBatchLimitsV3(max_block_bytes=120, max_batch_rows=3, max_batch_bytes=200),
    )
    return ArchivePortfolioSourceV3(f"{symbol}:{day}", index, CLOCK), rows


def _seal(
    tmp_path,
    *,
    boundaries=(),
    days=("2024-01-08",),
    symbols=("BTCUSDT", "ETHUSDT"),
    entry_days=(),
    **limits,
):
    sources, originals = [], {}
    for symbol in symbols:
        for day in days:
            start = _day_start_ms(day)
            times = (
                (start + 6, start + 12),
                (start + 10, start + 12),
                (start + 20, start + 25),
                (start + 86400000 - 2, start + 86400000 + 5),
            )
            source, rows = _source(tmp_path, symbol, day, times)
            sources.append(source)
            originals[source.source_key] = rows
    seal = ArchivePortfolioSealV3(
        tuple(sources),
        symbols,
        days,
        boundaries,
        TIE_RULE,
        ORDER,
        ArchivePortfolioLimitsV3(
            **{"max_batch_rows": 2, "max_batch_bytes": 200, "prefetch_rows": 2, **limits}
        ),
        entry_days=entry_days,
    )
    return seal, originals


def _open(seal, checkpoint=None):
    return ArchivePortfolioStreamV3(seal, expected_seal_sha256=seal.sha256, expected_checkpoint=checkpoint)


def _drain(stream, *, restart=False):
    operations = []
    while (operation := stream.prepare_next()) is not None:
        assert stream.checkpoint() == operation.before
        assert stream.prepare_next() is operation
        operations.append(operation)
        checkpoint = stream.acknowledge(operation)
        if restart:
            stream = _open(stream.seal, checkpoint)
    return operations, stream.checkpoint()


def _boundary(name, kind, at):
    return ArchivePortfolioBoundaryV3(name, kind, at, b"original boundary bytes", "a" * 64)


def test_lossless_two_symbols_two_days_and_exact_restart(tmp_path):
    seal, originals = _seal(tmp_path, days=("2024-01-08", "2024-01-09"))
    operations, final = _drain(_open(seal))
    restarted, resumed = _drain(_open(seal), restart=True)
    assert resumed == final
    assert [x.sha256 for x in restarted] == [x.sha256 for x in operations]
    merged = [row for op in operations for row in op.rows]
    expected = sorted(
        (int(raw.rstrip().split(b",")[-1]) + 5, key, ordinal, raw)
        for key, rows in originals.items()
        for ordinal, raw in enumerate(rows)
    )
    assert [
        (r.quote.modeled_available_at_ms, r.source_key, r.original.row_index, r.original.raw_csv_line)
        for r in merged
    ] == expected
    assert [r.global_sequence for r in merged] == list(range(1, 17))
    assert final.global_row_count == 16
    assert all(
        x.cursor.next_row == 4 and x.cursor.prefix_sha256 == source.index.prefix_final
        for x, source in zip(final.source_vector, seal.sources, strict=True)
    )
    assert all(
        r.quote.historical_received_at_ms is None and r.quote.historical_persisted_at_ms is None
        for r in merged
    )


def test_all_source_ties_before_equal_commands_and_exact_boundary_order(tmp_path):
    boundaries = tuple(_boundary(kind.lower(), kind, START + 17) for kind in ORDER)
    seal, _ = _seal(tmp_path, boundaries=boundaries, max_batch_rows=1)
    operations, final = _drain(_open(seal), restart=True)
    equal = [op for op in operations if op.at_ms == START + 17]
    assert [op.kind for op in equal] == ["SOURCE_BATCH"] * 4 + list(ORDER)
    assert all(op.source_rows_at_clock_remaining for op in equal[:3])
    assert not equal[3].source_rows_at_clock_remaining
    assert all(op.boundaries_at_clock_remaining for op in equal[:-1])
    assert not equal[-1].boundaries_at_clock_remaining
    assert final.boundary_cursor == 4
    assert all(op.boundary.payload == b"original boundary bytes" for op in equal[4:])


def test_batches_stop_at_every_explicit_boundary_including_source_tail(tmp_path):
    boundaries = (
        _boundary("early", "CONTROL", START),
        _boundary("middle", "CANDLE", START + 20),
        _boundary("fund", "FUNDING", START + 31),
        _boundary("final", "DEADLINE", START + 86400020),
    )
    seal, _ = _seal(tmp_path, boundaries=boundaries, max_batch_rows=3)
    operations, final = _drain(_open(seal), restart=True)
    assert operations[0].kind == "CONTROL"
    assert operations[-1].kind == "DEADLINE"
    seen_sources = []
    for op in operations:
        if op.kind == "SOURCE_BATCH":
            seen_sources.extend(op.rows)
        else:
            assert all(row.quote.modeled_available_at_ms <= op.at_ms for row in seen_sources)
            assert sum(
                row.quote.modeled_available_at_ms <= op.at_ms for other in operations for row in other.rows
            ) == len(seen_sources)
    assert final.global_row_count == 8 and final.boundary_cursor == 4


def test_cross_midnight_tail_interleaves_new_day_by_model_not_source_key(tmp_path):
    first, _ = _source(
        tmp_path, "BTCUSDT", "2024-01-08", ((START + 1, START + 1), (START + 86399999, START + 86400020))
    )
    second, _ = _source(
        tmp_path,
        "BTCUSDT",
        "2024-01-09",
        ((START + 86400001, START + 86400012), (START + 86400021, START + 86400030)),
    )
    seal = ArchivePortfolioSealV3(
        (first, second),
        ("BTCUSDT",),
        ("2024-01-08", "2024-01-09"),
        (),
        TIE_RULE,
        ORDER,
        ArchivePortfolioLimitsV3(prefetch_rows=2, max_batch_rows=1),
    )
    operations, _ = _drain(_open(seal), restart=True)
    assert [(r.original.transaction_day, r.original.row_index) for op in operations for r in op.rows] == [
        ("2024-01-08", 0),
        ("2024-01-09", 0),
        ("2024-01-08", 1),
        ("2024-01-09", 1),
    ]


def test_independently_sealed_latency_changes_merge_without_fabricated_receive(tmp_path):
    seal, _ = _seal(tmp_path)
    delayed = replace(seal.sources[0], clock=ArchiveMarketClockV3("EVENT_E", 100, 0))
    seal = replace(seal, sources=(delayed, seal.sources[1]))
    operations, _ = _drain(_open(seal))
    rows = [r for op in operations for r in op.rows]
    assert [r.source_key for r in rows[:3]] == [seal.sources[1].source_key] * 3
    assert all(r.quote.historical_received_at_ms is None for r in rows)
    assert rows[3].quote.event_at_ms == START + 12


def test_pending_exact_after_id_and_before_anchors_cannot_be_adopted(tmp_path):
    seal, _ = _seal(tmp_path)
    stream = _open(seal)
    operation = stream.prepare_next()
    anchor = ArchivePortfolioPendingAnchorV3(
        operation.before, operation.after, operation.operation_id, operation.sha256
    )
    for wrong in (
        replace(anchor, operation_id="different"),
        replace(anchor, after=operation.before),
        replace(anchor, before=operation.after),
    ):
        with pytest.raises(ValueError):
            ArchivePortfolioStreamV3.recover_pending(
                seal, expected_seal_sha256=seal.sha256, retained_anchor=wrong
            )


def test_pending_discard_and_exact_anchor_recovery(tmp_path):
    seal, _ = _seal(tmp_path)
    stream = _open(seal)
    first = stream.prepare_next()
    anchor = ArchivePortfolioPendingAnchorV3(first.before, first.after, first.operation_id, first.sha256)
    with pytest.raises(ValueError, match="exact owned"):
        stream.acknowledge(replace(first))
    with pytest.raises(ValueError, match="before checkpoint"):
        stream.discard_pending(expected_before=first.after)
    stream.discard_pending(expected_before=first.before)
    assert stream.prepare_next().sha256 == first.sha256
    recovered, operation = ArchivePortfolioStreamV3.recover_pending(
        seal, expected_seal_sha256=seal.sha256, retained_anchor=anchor
    )
    assert recovered.checkpoint() == first.before
    assert operation.sha256 == first.sha256
    assert recovered.acknowledge(operation) == first.after
    with pytest.raises(ValueError, match="exact deterministic"):
        ArchivePortfolioStreamV3.recover_pending(
            seal, expected_seal_sha256=seal.sha256, retained_anchor=replace(anchor, operation_sha256="b" * 64)
        )


@pytest.mark.parametrize("change", ["missing", "order", "duplicate", "gap", "tie", "boundary_order"])
def test_sealed_roster_and_order_fail_closed(tmp_path, change):
    seal, _ = _seal(tmp_path)
    kwargs = {}
    if change == "missing":
        kwargs["sources"] = seal.sources[:-1]
    elif change == "order":
        kwargs["sources"] = tuple(reversed(seal.sources))
    elif change == "duplicate":
        kwargs["sources"] = (seal.sources[0], seal.sources[0])
    elif change == "gap":
        kwargs["days"] = ("2024-01-08", "2024-01-10")
    elif change == "tie":
        kwargs["tie_rule"] = "hidden-default"
    else:
        kwargs["boundary_tie_order"] = ("CONTROL",) * 4
    with pytest.raises(ValueError):
        replace(seal, **kwargs)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_sources": 1},
        {"max_total_blocks": 1},
        {"max_raw_buffer_bytes": 1},
        {"max_decoded_rows": 1},
        {"prefetch_rows": 4},
        {"max_batch_rows": True},
        {"max_batch_bytes": 0},
    ],
)
def test_aggregate_resource_preflight(tmp_path, limits):
    with pytest.raises(ValueError):
        _seal(tmp_path, **limits)


def test_boundary_bytes_caps_and_clock_roster(tmp_path):
    seal, _ = _seal(tmp_path)
    boundaries = (_boundary("a", "CONTROL", START), _boundary("b", "CONTROL", START + 1))
    with pytest.raises(ValueError, match="payload"):
        replace(seal, boundaries=boundaries, limits=replace(seal.limits, max_total_boundary_payload_bytes=25))
    with pytest.raises(ValueError, match="payload"):
        replace(seal, boundaries=boundaries, limits=replace(seal.limits, max_boundary_payload_bytes=1))
    with pytest.raises(ValueError, match="payload"):
        replace(seal, boundaries=(_boundary("old", "CONTROL", START - 1),))
    with pytest.raises(ValueError, match="boundaries"):
        replace(seal, boundaries=tuple(reversed(boundaries)))


def test_retained_checkpoint_cannot_skip_other_source_tie_or_boundary(tmp_path):
    boundary = _boundary("command", "CONTROL", START + 17)
    seal, _ = _seal(tmp_path, boundaries=(boundary,), max_batch_rows=1)
    stream = _open(seal)
    initial = stream.checkpoint()
    first = stream.prepare_next()
    stream.acknowledge(first)
    second = stream.prepare_next()
    # A valid per-source prefix is insufficient: ETH cannot be consumed before BTC.
    eth_cursor = seal.sources[1].index.cursor(clock=CLOCK).read_batch(max_rows=1).after
    vector = (initial.source_vector[0], replace(initial.source_vector[1], cursor=eth_cursor))
    bad = replace(first.after, source_vector=vector)
    with pytest.raises(ValueError, match="earlier/tied"):
        _open(seal, bad)
    with pytest.raises(ValueError, match="source-before-equal"):
        _open(seal, replace(second.after, boundary_cursor=1, operation_count=3))
    with pytest.raises(ValueError, match="last clock"):
        _open(seal, replace(first.after, last_clock_ms=START + 18))
    with pytest.raises(ValueError, match="seal"):
        ArchivePortfolioStreamV3(seal, expected_seal_sha256="b" * 64)


def test_cached_original_mutation_even_restored_mtime_poison_without_advance(tmp_path):
    seal, _ = _seal(tmp_path)
    stream = _open(seal)
    before = stream.checkpoint()
    path = seal.sources[0].index.source_root / seal.sources[0].index.blocks[0].segment
    stat = path.stat()
    payload = path.read_bytes()
    path.write_bytes(payload.replace(b"100.00", b"101.00", 1))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(ValueError, match="hash"):
        stream.prepare_next()
    assert stream.checkpoint() == before
    with pytest.raises(ValueError, match="poisoned"):
        stream.prepare_next()


def test_single_original_row_over_byte_cap_no_sampling(tmp_path):
    seal, _ = _seal(tmp_path, max_batch_bytes=1)
    stream = _open(seal)
    before = stream.checkpoint()
    with pytest.raises(ValueError, match="one original row"):
        stream.prepare_next()
    assert stream.checkpoint() == before


def test_failed_discard_reopen_cannot_ack_prior_pending_operation(tmp_path, monkeypatch):
    seal, _ = _seal(tmp_path)
    stream = _open(seal)
    operation = stream.prepare_next()

    def failed_reopen(*args):
        raise OSError("source reopen failure")

    monkeypatch.setattr(stream, "_restore", failed_reopen)
    with pytest.raises(OSError, match="reopen failure"):
        stream.discard_pending(expected_before=operation.before)
    assert stream.checkpoint() == operation.before
    with pytest.raises(ValueError, match="exact owned"):
        stream.acknowledge(operation)
    with pytest.raises(ValueError, match="poisoned"):
        stream.prepare_next()


def test_final_deadline_after_authentication_before_handoff(tmp_path, monkeypatch):
    seal, _ = _seal(tmp_path)
    stream = _open(seal)
    before = stream.checkpoint()
    original = stream._authenticate_rows

    def authenticate(rows, deadline):
        original(rows, deadline)
        monkeypatch.setattr(
            stream, "_check_time", lambda deadline: (_ for _ in ()).throw(TimeoutError("final deadline"))
        )

    monkeypatch.setattr(stream, "_authenticate_rows", authenticate)
    with pytest.raises(TimeoutError, match="final deadline"):
        stream.prepare_next()
    assert stream.checkpoint() == before


def test_reader_never_uses_segment_wide_row_at_or_iter_rows(tmp_path, monkeypatch):
    seal, _ = _seal(tmp_path)
    cls = module.bookticker_archive_stream_v3.BookTickerArchiveStreamV3

    def forbidden(*args, **kwargs):
        raise AssertionError("segment-wide point read")

    monkeypatch.setattr(cls, "row_at", forbidden)
    monkeypatch.setattr(cls, "iter_rows", forbidden)
    _, final = _drain(_open(seal), restart=True)
    assert final.global_row_count == 8


def test_exact_five_day_five_symbol_window_plus_exit_tail_same_stream(tmp_path):
    days = tuple(f"2024-01-{day:02d}" for day in range(8, 14))
    symbols = tuple(sorted(module.UNIVERSE))
    seal, originals = _seal(
        tmp_path,
        days=days,
        symbols=symbols,
        entry_days=days[:5],
        window_profile=FIVE_DAY_WITH_ONE_DAY_EXIT_TAIL,
        max_sources=30,
    )
    assert seal.entry_days == days[:5]
    assert seal.days[-1] == "2024-01-13"
    assert len(seal.sources) == 30
    stream = _open(seal)
    operations, final = _drain(stream)
    rows = [row for op in operations for row in op.rows]
    assert final.global_row_count == 120
    assert len(final.source_vector) == 30
    assert sum(row.original.transaction_day == days[-1] for row in rows) == 20
    assert [row.global_sequence for row in rows] == list(range(1, 121))
    assert [
        (row.quote.modeled_available_at_ms, row.source_key, row.original.row_index, row.original.raw_csv_line)
        for row in rows
    ] == sorted(
        (int(raw.rstrip().split(b",")[-1]) + 5, key, index, raw)
        for key, values in originals.items()
        for index, raw in enumerate(values)
    )
    # Tail resumes the same exact vector and global prefix; no second genesis.
    tail_index = next(
        i for i, op in enumerate(operations) if any(r.original.transaction_day == days[-1] for r in op.rows)
    )
    anchor = operations[tail_index].before
    resumed, resumed_final = _drain(_open(seal, anchor))
    assert [op.sha256 for op in resumed] == [op.sha256 for op in operations[tail_index:]]
    assert resumed_final == final


@pytest.mark.parametrize(
    "invalid", ["implicit", "six-entry-days", "wrong-entry-day", "missing-tail", "default-cap"]
)
def test_exit_tail_is_never_implicit_or_a_smaller_entry_window(tmp_path, invalid):
    days = tuple(f"2024-01-{day:02d}" for day in range(8, 14))
    entries = days[:5]
    kwargs = {"window_profile": FIVE_DAY_WITH_ONE_DAY_EXIT_TAIL, "max_sources": 30}
    if invalid == "implicit":
        kwargs = {}
    elif invalid == "six-entry-days":
        entries = days
    elif invalid == "wrong-entry-day":
        entries = days[1:]
    elif invalid == "missing-tail":
        days = days[:5]
    else:
        kwargs["max_sources"] = 25
    with pytest.raises(ValueError):
        _seal(tmp_path, days=days, symbols=tuple(sorted(module.UNIVERSE)), entry_days=entries, **kwargs)


def test_window_only_does_not_silently_gain_six_days_or_thirty_sources(tmp_path):
    seal, _ = _seal(tmp_path)
    assert seal.limits.window_profile == WINDOW_ONLY and seal.entry_days == seal.days
    with pytest.raises(ValueError, match="max_sources"):
        ArchivePortfolioLimitsV3(max_sources=30)
    with pytest.raises(ValueError, match="profile"):
        ArchivePortfolioLimitsV3(window_profile="UNSEALED_DEFAULT")
    with pytest.raises(ValueError, match="identical"):
        replace(seal, entry_days=("2024-01-09",))
