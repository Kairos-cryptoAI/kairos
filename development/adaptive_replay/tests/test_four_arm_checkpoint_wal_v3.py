"""Short real file durability/format checks, not a five-day economic run."""

from dataclasses import replace

import pytest

from adaptive_replay.continuous_four_arm_v3 import ARMS, FourArmCheckpointV3
from adaptive_replay.four_arm_checkpoint_wal_v3 import (
    CheckpointWalLimitsV3,
    FourArmCheckpointWalV3,
    checkpoint_document,
    checkpoint_from_document,
    inspect_checkpoint_wal_v3,
)
from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_journal_v3 import JournalCheckpointV3
from adaptive_replay.sim_delta_journal_v3 import DeltaCheckpointV3
from adaptive_replay.sim_financial_journal_v3 import FinancialCheckpointV3

SHA, NEXT = "a" * 64, "b" * 64


def initial():
    return FourArmCheckpointV3(
        SHA,
        DeltaCheckpointV3(SHA, 0, SHA, SHA, 0),
        tuple((a, FinancialCheckpointV3(SHA, "experiment", a, 0, SHA, SHA, 0, 0, 0, SHA)) for a in ARMS),
        (("producer", JournalCheckpointV3(SHA, 0, SHA)),),
        0,
        None,
    )


def phases():
    first = initial()
    pending = {
        "operation": {"kind": "SOURCE", "first": 1, "last": 1, "at": 10},
        "before": {a: checkpoint_document(first)["arm_checkpoints"][i][1] for i, a in enumerate(ARMS)},
        "effects": {
            a: {"event_id": "source:1", "payload": {"kind": "SOURCE_BATCH", "first": 1, "last": 1, "at": 10}}
            for a in ARMS
        },
    }
    prepared = replace(
        first,
        pending_operation=pending,
        pending_operation_sha256=digest(pending),
        checkpoint_phase="PREPARED_INTENT",
    )
    intent = replace(
        prepared,
        driver_checkpoint=replace(
            first.driver_checkpoint, version=1, state_hash=NEXT, head_hash=NEXT, last_clock_ms=10
        ),
        checkpoint_phase="INTENT_COMMITTED",
    )
    committed = replace(
        intent,
        driver_checkpoint=replace(intent.driver_checkpoint, version=2, state_hash=SHA, head_hash=SHA),
        arm_checkpoints=tuple(
            (
                a,
                replace(
                    cp,
                    version=1,
                    state_hash=NEXT,
                    head_hash=NEXT,
                    last_clock_ms=10,
                    source_cursor=1,
                    native_count=1,
                    native_head=NEXT,
                ),
            )
            for a, cp in intent.arm_checkpoints
        ),
        operation_cursor=1,
        pending_operation=None,
        pending_operation_sha256=None,
    )
    return first, prepared, intent, committed


def test_real_file_sink_ack_and_exact_reopen(tmp_path):
    first, prepared, intent, committed = phases()
    path = tmp_path / "external.wal"
    with FourArmCheckpointWalV3.create(path, first) as wal:
        assert wal(prepared) is True
        assert wal(intent) is True
        assert wal(committed) is True
        saved = wal.snapshot()
        assert wal(committed) is True
        assert wal.snapshot().anchor == saved.anchor
    read = inspect_checkpoint_wal_v3(path, identity_sha256=SHA)
    assert read == saved
    with FourArmCheckpointWalV3.open(path, expected_anchor=saved.anchor) as reopened:
        assert reopened.snapshot().checkpoint == committed


def test_ack_occurs_after_real_fsync_and_failure_poisons(tmp_path, monkeypatch):
    first, prepared, _, _ = phases()
    path = tmp_path / "external.wal"
    with FourArmCheckpointWalV3.create(path, first) as wal:
        before = wal.snapshot()

        def failing_fsync(fd):
            raise OSError("injected sync failure")

        monkeypatch.setattr("adaptive_replay.four_arm_checkpoint_wal_v3.os.fsync", failing_fsync)
        with pytest.raises(OSError, match="injected sync"):
            wal(prepared)
        assert wal._inspection == before
        with pytest.raises(ValueError, match="poisoned"):
            wal(prepared)


def test_create_only_and_foreign_writer_lock(tmp_path):
    path = tmp_path / "external.wal"
    with FourArmCheckpointWalV3.create(path, initial()) as wal:
        with pytest.raises(FileExistsError):
            FourArmCheckpointWalV3.create(path, initial())
        with pytest.raises(OSError):
            FourArmCheckpointWalV3.open(path, expected_anchor=wal.snapshot().anchor)


@pytest.mark.parametrize("tail", [b"x", b"\x00" * 7, b"\x00" * 7 + b"\x03" + b"{"])
def test_torn_suffix_visible_no_automatic_repair(tmp_path, tail):
    path = tmp_path / "external.wal"
    with FourArmCheckpointWalV3.create(path, initial()) as wal:
        saved = wal.snapshot()
    with path.open("ab") as target:
        target.write(tail)
    read = inspect_checkpoint_wal_v3(path, identity_sha256=SHA)
    assert read.anchor == saved.anchor and read.checkpoint == saved.checkpoint
    assert read.torn_tail_bytes == len(tail)
    with pytest.raises(ValueError, match="torn tail"):
        FourArmCheckpointWalV3.open(path, expected_anchor=saved.anchor)
    assert path.read_bytes().endswith(tail)


def test_frame_corruption_is_not_torn_or_accepted(tmp_path):
    path = tmp_path / "external.wal"
    with FourArmCheckpointWalV3.create(path, initial()) as wal:
        saved = wal.snapshot()
    raw = bytearray(path.read_bytes())
    raw[-5] ^= 1
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="hash/footer"):
        inspect_checkpoint_wal_v3(path, identity_sha256=SHA)
    with pytest.raises(ValueError):
        FourArmCheckpointWalV3.open(path, expected_anchor=saved.anchor)


def test_exact_anchor_refuses_old_or_unknown_head(tmp_path):
    first, prepared, _, _ = phases()
    path = tmp_path / "external.wal"
    with FourArmCheckpointWalV3.create(path, first) as wal:
        old = wal.snapshot().anchor
        wal(prepared)
        current = wal.snapshot().anchor
    with pytest.raises(ValueError, match="independent exact anchor"):
        FourArmCheckpointWalV3.open(path, expected_anchor=old)
    with pytest.raises(ValueError, match="identity"):
        FourArmCheckpointWalV3.open(path, expected_anchor=replace(current, identity_sha256=NEXT))


def test_mutable_cp_cannot_rewrite_retained_payload(tmp_path):
    first, prepared, _, _ = phases()
    with FourArmCheckpointWalV3.create(tmp_path / "external.wal", first) as wal:
        wal(prepared)
        prepared.pending_operation["operation"]["last"] = 999
        assert wal.snapshot().checkpoint.pending_operation["operation"]["last"] == 1
        exposed = wal.snapshot()
        exposed.checkpoint.pending_operation["operation"]["last"] = 888
        assert wal.snapshot().checkpoint.pending_operation["operation"]["last"] == 1


def test_all_phases_and_rollback_guard(tmp_path):
    first, prepared, intent, committed = phases()
    with FourArmCheckpointWalV3.create(tmp_path / "external.wal", first) as wal:
        with pytest.raises(ValueError, match="preintent"):
            wal(intent)
        wal(prepared)
        with pytest.raises(ValueError, match="retained intent"):
            wal(committed)
        wal(intent)
        wal(committed)
        with pytest.raises(ValueError):
            wal(first)


def test_pending_and_closed_document_schema():
    first, prepared, _, _ = phases()
    assert checkpoint_from_document(checkpoint_document(first)) == first
    with pytest.raises(ValueError, match="whole pending"):
        checkpoint_document(replace(prepared, pending_operation_sha256=NEXT))
    document = checkpoint_document(first)
    document["unknown"] = 1
    with pytest.raises(ValueError, match="closed checkpoint"):
        checkpoint_from_document(document)
    with pytest.raises(ValueError, match="financial arm"):
        checkpoint_document(replace(first, arm_checkpoints=tuple((a, first.driver_checkpoint) for a in ARMS)))


def test_resource_refusal_before_new_bytes(tmp_path):
    first, prepared, _, _ = phases()
    path = tmp_path / "external.wal"
    with FourArmCheckpointWalV3.create(path, first, limits=CheckpointWalLimitsV3(max_frames=1)) as wal:
        before = wal.snapshot()
        with pytest.raises(ValueError, match="resource ceiling"):
            wal(prepared)
        assert wal.snapshot() == before and path.stat().st_size == before.anchor.durable_bytes


def test_bootstrap_and_invalid_types_are_rejected_before_creation(tmp_path):
    first, prepared, _, _ = phases()
    path = tmp_path / "external.wal"
    with pytest.raises(ValueError, match="initial unadvanced"):
        FourArmCheckpointWalV3.create(path, prepared)
    assert not path.exists()
    with pytest.raises(ValueError):
        CheckpointWalLimitsV3(max_frames=True)
    with pytest.raises(ValueError):
        checkpoint_document(replace(first, operation_cursor=True))


def test_truncated_bootstrap_is_not_a_checkpoint(tmp_path):
    path = tmp_path / "external.wal"
    path.write_bytes(b"KAIROS-FOUR-ARM-WAL-V3\n\x00")
    with pytest.raises(ValueError, match="bootstrap"):
        inspect_checkpoint_wal_v3(path, identity_sha256=SHA)
