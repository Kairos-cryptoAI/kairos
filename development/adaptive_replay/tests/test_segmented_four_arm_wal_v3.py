"""Small real-fsync/process-exit checks, not a dense replay or power-loss proof."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from adaptive_replay import segmented_four_arm_wal_v3 as api
from adaptive_replay.continuous_four_arm_v3 import ARMS, FourArmCheckpointV3
from adaptive_replay.four_arm_checkpoint_wal_v3 import checkpoint_document, checkpoint_from_document
from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_journal_v3 import JournalCheckpointV3
from adaptive_replay.sim_delta_journal_v3 import DeltaCheckpointV3
from adaptive_replay.sim_financial_journal_v3 import FinancialCheckpointV3

SHA = "a" * 64


def initial():
    return FourArmCheckpointV3(
        SHA,
        DeltaCheckpointV3(SHA, 0, SHA, SHA, 0),
        tuple((arm, FinancialCheckpointV3(SHA, "owner", arm, 0, SHA, SHA, 0, 0, 0, SHA)) for arm in ARMS),
        (("producer", JournalCheckpointV3(SHA, 0, SHA)),),
        0,
        None,
    )


def phases(before):
    sequence = before.operation_cursor + 1
    at = sequence * 10
    head = digest(["head", sequence])
    pending = {
        "operation": {"kind": "SOURCE", "first": sequence, "last": sequence, "at": at},
        "before": {arm: asdict(cp) for arm, cp in before.arm_checkpoints},
        "effects": {
            arm: {
                "event_id": f"source:{sequence}",
                "payload": {"kind": "SOURCE_BATCH", "first": sequence, "last": sequence, "at": at},
            }
            for arm in ARMS
        },
    }
    prepared = replace(
        before,
        pending_operation=pending,
        pending_operation_sha256=digest(pending),
        checkpoint_phase="PREPARED_INTENT",
    )
    intent = replace(
        prepared,
        driver_checkpoint=replace(
            before.driver_checkpoint,
            version=before.driver_checkpoint.version + 1,
            state_hash=head,
            head_hash=head,
            last_clock_ms=at,
        ),
        checkpoint_phase="INTENT_COMMITTED",
    )
    advanced = tuple(
        (
            arm,
            replace(
                cp,
                version=cp.version + 1,
                state_hash=head,
                head_hash=head,
                last_clock_ms=at,
                source_cursor=sequence,
                native_count=cp.native_count + 1,
                native_head=head,
            ),
        )
        for arm, cp in intent.arm_checkpoints
    )
    completed = replace(
        intent,
        driver_checkpoint=replace(
            intent.driver_checkpoint,
            version=intent.driver_checkpoint.version + 1,
            state_hash=digest(["done", sequence]),
            head_hash=digest(["done", sequence]),
        ),
        arm_checkpoints=advanced,
        operation_cursor=sequence,
        pending_operation=None,
        pending_operation_sha256=None,
    )
    return prepared, intent, completed


def limits(**changes):
    return replace(
        api.SegmentedWalLimitsV3(
            max_frame_bytes=16 * 1024,
            max_segment_frames=8,
            max_segment_bytes=256 * 1024,
            max_segments=8,
            max_global_frames=100,
            max_total_bytes=16 * 1024 * 1024,
            max_catalog_bytes=1024 * 1024,
        ),
        **changes,
    )


def populate(path, *, bounds=None):
    with api.SegmentedFourArmCheckpointWalV3.create(path, initial(), limits=bounds or limits()) as wal:
        for checkpoint in phases(initial()):
            assert wal(checkpoint) is True
        return wal.snapshot()


def checkpoint_frames(path, bounds):
    result = []
    for segment in sorted(path.glob("*.wal")):
        if segment.name == "catalog.wal":
            continue
        with segment.open("rb") as stream:
            assert stream.read(len(api.MAGIC)) == api.MAGIC
            header, torn = api._read_frame(stream, bounds.framing())
            assert not torn
            if header[0]["segment_number"] == 0:
                result.append(header[0]["checkpoint"])
            while True:
                record, torn = api._read_frame(stream, bounds.framing())
                assert not torn
                if record is None:
                    break
                result.append(record[0]["checkpoint"])
    return result


def namespace_bytes(path, *, catalog=None):
    result = {}
    for entry in path.iterdir():
        if entry.name == "catalog.wal" and catalog is not None:
            position = catalog.tell()
            catalog.seek(0)
            result[entry.name] = catalog.read()
            catalog.seek(position)
        else:
            result[entry.name] = entry.read_bytes()
    return result


def test_real_fsync_rotation_retains_every_checkpoint_and_exact_anchor(tmp_path, monkeypatch):
    calls = []
    original_sync = api.os.fsync

    def observed(fd):
        original_sync(fd)
        calls.append(fd)

    monkeypatch.setattr(api.os, "fsync", observed)
    path = tmp_path / "evidence"
    expected = [checkpoint_document(initial())]
    with api.SegmentedFourArmCheckpointWalV3.create(path, initial(), limits=limits()) as wal:
        current = initial()
        for _ in range(3):
            for checkpoint in phases(current):
                assert wal(checkpoint) is True
                expected.append(checkpoint_document(checkpoint))
            current = checkpoint
        saved = wal.snapshot()
        assert saved.anchor.segment_number == 2
        assert saved.anchor.global_frames == 10
        assert wal(current) is True
        assert wal.snapshot() == saved
        # Two bootstrap fsyncs, nine checkpoint fsyncs, two three-step rotations.
        assert len(calls) == 17
    assert checkpoint_frames(path, limits()) == expected
    assert api.inspect_segmented_four_arm_wal_v3(path, identity_sha256=SHA) == saved
    with api.SegmentedFourArmCheckpointWalV3.open(path, expected_anchor=saved.anchor) as wal:
        assert wal.snapshot() == saved


def test_maximal_partial_progress_reserve_and_pending_rotation_refusal(tmp_path):
    path = tmp_path / "evidence"
    with api.SegmentedFourArmCheckpointWalV3.create(path, initial(), limits=limits()) as wal:
        prepared, intent, complete = phases(initial())
        wal(prepared)
        before = wal.snapshot()
        with pytest.raises(ValueError, match="completed/no-pending"):
            wal.rotate()
        assert wal.snapshot() == before
        wal(intent)
        partial = intent
        for index in range(4):
            partial = replace(
                partial,
                arm_checkpoints=complete.arm_checkpoints[: index + 1] + intent.arm_checkpoints[index + 1 :],
            )
            wal(partial)
        wal(complete)
        saved = wal.snapshot()
        assert saved.anchor.global_frames == saved.anchor.segment_frames == 8
        original = (path / "segment-000000.wal").read_bytes()
        rotated = wal.rotate()
        assert rotated.anchor.global_frames == saved.anchor.global_frames
        assert rotated.anchor.global_head_sha256 == saved.anchor.global_head_sha256
        assert rotated.checkpoint == complete
        assert (path / "segment-000000.wal").read_bytes() == original
    with api.SegmentedFourArmCheckpointWalV3.open(path, expected_anchor=rotated.anchor) as wal:
        assert wal.snapshot() == rotated


@pytest.mark.parametrize("boundary", [1, 2, 3, 4])
def test_rotation_and_checkpoint_fsync_failure_never_ack_or_repair(tmp_path, monkeypatch, boundary):
    path = tmp_path / "evidence"
    saved = populate(path)
    original_sync = api.os.fsync
    count = 0

    def failing(fd):
        nonlocal count
        count += 1
        if count == boundary:
            raise OSError(f"fsync boundary {boundary}")
        original_sync(fd)

    with api.SegmentedFourArmCheckpointWalV3.open(path, expected_anchor=saved.anchor) as wal:
        monkeypatch.setattr(api.os, "fsync", failing)
        with pytest.raises(OSError, match="fsync boundary"):
            wal(phases(saved.checkpoint)[0])
        with pytest.raises(ValueError, match="poisoned"):
            wal.snapshot()
    monkeypatch.setattr(api.os, "fsync", original_sync)
    bytes_before = {p.name: p.read_bytes() for p in path.iterdir()}
    with pytest.raises(ValueError):
        api.SegmentedFourArmCheckpointWalV3.open(path, expected_anchor=saved.anchor)
    assert {p.name: p.read_bytes() for p in path.iterdir()} == bytes_before


def crash_worker(directory, anchor_json, boundary, when):
    """Run ONLY in the private test subprocess. os._exit is an actual process exit."""
    bootstrap = anchor_json == "BOOTSTRAP"
    if not bootstrap:
        anchor = api.SegmentedWalAnchorV3(**json.loads(anchor_json))
        wal = api.SegmentedFourArmCheckpointWalV3.open(directory, expected_anchor=anchor)
        checkpoint = phases(wal.snapshot().checkpoint)[0]
    original_sync = api.os.fsync
    count = 0

    def crash_sync(fd):
        nonlocal count
        count += 1
        if count == boundary and when == "before":
            os._exit(91)
        original_sync(fd)
        if count == boundary and when == "after":
            os._exit(91)

    api.os.fsync = crash_sync
    if bootstrap:
        api.SegmentedFourArmCheckpointWalV3.create(directory, initial(), limits=limits())
    else:
        wal(checkpoint)
    os._exit(92)  # Test failure: the requested boundary was never reached.


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("boundary", [1, 2, 3, 4])
def test_actual_process_exit_at_publication_boundaries_no_latest_adoption(tmp_path, boundary, when):
    from ._isolated_fixture import FIXTURE_BOOTSTRAP

    path = tmp_path / "evidence"
    saved = populate(path)
    script = (
        FIXTURE_BOOTSTRAP + "\nload_isolated_fixture_module(sys.argv[1]).crash_worker"
        "(sys.argv[2],sys.argv[3],int(sys.argv[4]),sys.argv[5])"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-W",
            "error",
            "-c",
            script,
            str(Path(__file__).absolute()),
            str(path),
            json.dumps(asdict(saved.anchor)),
            str(boundary),
            when,
        ],
        check=False,
        capture_output=True,
        timeout=180,
    )
    assert result.returncode == 91, result.stderr.decode(errors="replace")
    bytes_before = {p.name: p.read_bytes() for p in path.iterdir()}
    with pytest.raises(ValueError):
        api.SegmentedFourArmCheckpointWalV3.open(path, expected_anchor=saved.anchor)
    assert {p.name: p.read_bytes() for p in path.iterdir()} == bytes_before
    if boundary >= 3:
        # Complete bytes may be visible even before fsync; this is NOT durability
        # evidence. Read-only inspection cannot authorize adopting the new anchor.
        inspected = api.inspect_segmented_four_arm_wal_v3(path, identity_sha256=SHA)
        assert inspected.anchor != saved.anchor


@pytest.mark.parametrize("target", ["catalog.wal", "segment-000000.wal", "segment-000000.seal"])
def test_full_open_audit_rejects_tampered_or_torn_closed_history(tmp_path, target):
    path = tmp_path / "evidence"
    saved = populate(path)
    with api.SegmentedFourArmCheckpointWalV3.open(path, expected_anchor=saved.anchor) as wal:
        saved = wal.rotate()
    victim = path / target
    with victim.open("ab") as stream:
        stream.write(b"torn")
    exact_bytes = victim.read_bytes()
    with pytest.raises(ValueError):
        api.SegmentedFourArmCheckpointWalV3.open(path, expected_anchor=saved.anchor)
    assert victim.read_bytes() == exact_bytes


def test_closed_segment_self_rehash_cannot_escape_pinned_seal(tmp_path):
    path = tmp_path / "evidence"
    saved = populate(path)
    with api.SegmentedFourArmCheckpointWalV3.open(path, expected_anchor=saved.anchor) as wal:
        saved = wal.rotate()
    victim = path / "segment-000000.wal"
    raw = victim.read_bytes()
    with victim.open("rb") as stream:
        stream.seek(len(api.MAGIC))
        (header, _), torn = api._read_frame(stream, limits().framing())
        assert not torn
        offset = stream.tell()
    # Recompute a VALID frame checksum after changing old canonical content.
    # Its locally consistent new hash is still not the retained catalog seal.
    header["checkpoint"]["driver_checkpoint"]["state_hash"] = "b" * 64
    replacement, _ = api._frame(header, limits().framing())
    victim.write_bytes(api.MAGIC + replacement + raw[offset:])
    with pytest.raises(ValueError, match="catalog commitment"):
        api.SegmentedFourArmCheckpointWalV3.open(path, expected_anchor=saved.anchor)


def test_unknown_heads_identity_checkpoint_pin_and_foreign_lock(tmp_path):
    path = tmp_path / "evidence"
    with api.SegmentedFourArmCheckpointWalV3.create(path, initial(), limits=limits()) as wal:
        old = wal.snapshot()
        with pytest.raises(OSError):
            api.SegmentedFourArmCheckpointWalV3.open(path, expected_anchor=old.anchor)
        with pytest.raises(FileExistsError):
            api.SegmentedFourArmCheckpointWalV3.create(path, initial(), limits=limits())
        wal(phases(initial())[0])
        saved = wal.snapshot()
    for anchor in (
        old.anchor,
        replace(saved.anchor, identity_sha256="b" * 64),
        replace(saved.anchor, checkpoint_sha256="b" * 64),
        replace(saved.anchor, global_head_sha256="b" * 64),
    ):
        with pytest.raises(ValueError):
            api.SegmentedFourArmCheckpointWalV3.open(path, expected_anchor=anchor)


def test_conflicts_and_mutable_payload_never_rewrite_original(tmp_path):
    with api.SegmentedFourArmCheckpointWalV3.create(tmp_path / "evidence", initial(), limits=limits()) as wal:
        prepared, intent, complete = phases(initial())
        with pytest.raises(ValueError):
            wal(intent)
        wal(prepared)
        snapshot = wal.snapshot()
        assert wal(prepared) is True and wal.snapshot() == snapshot
        with pytest.raises(ValueError, match="whole pending"):
            altered = replace(prepared, pending_operation_sha256="b" * 64)
            wal(altered)
        exposed = wal.snapshot()
        exposed.checkpoint.pending_operation["operation"]["first"] = 999
        assert wal.snapshot() == snapshot
        wal(intent)
        wal(complete)
        with pytest.raises(ValueError):
            wal(initial())


def test_owned_namespace_external_addition_poisoned(tmp_path):
    with api.SegmentedFourArmCheckpointWalV3.create(tmp_path / "evidence", initial(), limits=limits()) as wal:
        (tmp_path / "evidence" / "orphan").write_bytes(b"not ours")
        with pytest.raises(ValueError, match="namespace changed"):
            wal(phases(initial())[0])


def test_global_and_rotation_limits_refuse_before_any_new_bytes(tmp_path):
    path = tmp_path / "evidence"
    with api.SegmentedFourArmCheckpointWalV3.create(
        path, initial(), limits=limits(max_global_frames=7)
    ) as wal:
        before = namespace_bytes(path, catalog=wal._catalog)
        with pytest.raises(ValueError, match="global complete-operation"):
            wal(phases(initial())[0])
        assert namespace_bytes(path, catalog=wal._catalog) == before
    path = tmp_path / "one-segment"
    saved = populate(path, bounds=limits(max_segments=1))
    with api.SegmentedFourArmCheckpointWalV3.open(path, expected_anchor=saved.anchor) as wal:
        before = namespace_bytes(path, catalog=wal._catalog)
        with pytest.raises(ValueError, match="segment capacity"):
            wal(phases(saved.checkpoint)[0])
        assert namespace_bytes(path, catalog=wal._catalog) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"max_segment_frames": 7},
        {"max_segment_bytes": 1},
        {"max_global_frames": True},
        {"max_segments": 100001},
    ],
)
def test_invalid_limits(changes):
    with pytest.raises(ValueError):
        limits(**changes)


def test_ordinary_append_does_not_scan_catalog_or_closed_frames(tmp_path, monkeypatch):
    path = tmp_path / "evidence"
    saved = populate(path)
    with api.SegmentedFourArmCheckpointWalV3.open(path, expected_anchor=saved.anchor) as wal:
        wal.rotate()

        def forbidden(*args, **kwargs):
            raise AssertionError("history audit on ordinary own append")

        monkeypatch.setattr(api, "_audit", forbidden)
        monkeypatch.setattr(api, "_read_frame", forbidden)
        for checkpoint in phases(saved.checkpoint):
            assert wal(checkpoint) is True
        assert wal.snapshot().checkpoint.operation_cursor == 2


def test_checkpoint_closed_schema_reuse():
    assert checkpoint_from_document(checkpoint_document(initial())) == initial()


@pytest.mark.parametrize("boundary", [1, 2])
def test_bootstrap_sync_failure_retains_artifacts_no_create_adoption(tmp_path, monkeypatch, boundary):
    path = tmp_path / "evidence"
    original_sync = api.os.fsync
    count = 0

    def failing(fd):
        nonlocal count
        count += 1
        if count == boundary:
            raise OSError("bootstrap fsync failure")
        original_sync(fd)

    monkeypatch.setattr(api.os, "fsync", failing)
    with pytest.raises(OSError, match="bootstrap fsync"):
        api.SegmentedFourArmCheckpointWalV3.create(path, initial(), limits=limits())
    before = namespace_bytes(path)
    with pytest.raises(FileExistsError):
        api.SegmentedFourArmCheckpointWalV3.create(path, initial(), limits=limits())
    assert namespace_bytes(path) == before


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("boundary", [1, 2])
def test_actual_bootstrap_process_exit_no_recreate_or_repair(tmp_path, boundary, when):
    from ._isolated_fixture import FIXTURE_BOOTSTRAP

    path = tmp_path / "evidence"
    script = (
        FIXTURE_BOOTSTRAP + "\nload_isolated_fixture_module(sys.argv[1]).crash_worker"
        "(sys.argv[2],'BOOTSTRAP',int(sys.argv[3]),sys.argv[4])"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-W",
            "error",
            "-c",
            script,
            str(Path(__file__).absolute()),
            str(path),
            str(boundary),
            when,
        ],
        check=False,
        capture_output=True,
        timeout=180,
    )
    assert result.returncode == 91, result.stderr.decode(errors="replace")
    before = namespace_bytes(path)
    with pytest.raises(FileExistsError):
        api.SegmentedFourArmCheckpointWalV3.create(path, initial(), limits=limits())
    assert namespace_bytes(path) == before


@pytest.mark.parametrize("alien", ["file", "bytes"])
def test_fsync_callback_cannot_rebase_unknown_publication(tmp_path, monkeypatch, alien):
    path = tmp_path / "evidence"
    original_sync = api.os.fsync
    with api.SegmentedFourArmCheckpointWalV3.create(path, initial(), limits=limits()) as wal:

        def foreign(fd):
            original_sync(fd)
            if alien == "file":
                (path / "unknown").write_bytes(b"outside writer")
            else:
                with (path / "segment-000000.wal").open("ab") as stream:
                    stream.write(b"outside writer")

        monkeypatch.setattr(api.os, "fsync", foreign)
        with pytest.raises(ValueError, match="publication|namespace"):
            wal(phases(initial())[0])
        with pytest.raises(ValueError, match="poisoned"):
            wal.snapshot()


def test_invalid_initial_or_false_limits_never_create_namespace(tmp_path):
    path = tmp_path / "evidence"
    with pytest.raises(ValueError, match="typed segmented"):
        api.SegmentedFourArmCheckpointWalV3.create(path, initial(), limits=False)
    with pytest.raises(ValueError, match="completed/no-pending"):
        api.SegmentedFourArmCheckpointWalV3.create(path, phases(initial())[0], limits=limits())
    assert not path.exists()


def test_catalog_locked_before_bootstrap_fsync_visibility(tmp_path, monkeypatch):
    path = tmp_path / "evidence"
    original_sync = api.os.fsync
    calls = 0

    def observed(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            with (path / "catalog.wal").open("r+b", buffering=0) as foreign:
                with pytest.raises(OSError):
                    api._lock(foreign.fileno())
        original_sync(fd)

    monkeypatch.setattr(api.os, "fsync", observed)
    with api.SegmentedFourArmCheckpointWalV3.create(path, initial(), limits=limits()) as wal:
        assert wal.snapshot().anchor.global_frames == 1
    assert calls == 2


def test_open_cannot_adopt_same_size_change_after_anchored_audit(tmp_path, monkeypatch):
    path = tmp_path / "evidence"
    saved = populate(path)
    original_audit = api._audit

    def raced(*args, **kwargs):
        inspected = original_audit(*args, **kwargs)
        target = path / "segment-000000.wal"
        previous = target.stat()
        raw = bytearray(target.read_bytes())
        raw[-5] ^= 1
        target.write_bytes(raw)
        os.utime(target, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000))
        return inspected

    monkeypatch.setattr(api, "_audit", raced)
    with pytest.raises(ValueError, match="files replaced after anchored audit"):
        api.SegmentedFourArmCheckpointWalV3.open(path, expected_anchor=saved.anchor)
