"""Fabricated complete observed captures; never actual source authenticity proof."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from adaptive_replay import public_book_capture as capture
from adaptive_replay import sim_book_tape as mapping
from adaptive_replay.historical_context import canonical

START = 1_791_400_000_000
MONO = 9_000_000_000_000


def _capture(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "SEGMENT_FRAMES", 2)
    clock = {"ms": START, "ns": MONO}
    output = tmp_path / "public-book-capture-20261009-test"
    rec = capture.PublicBookRecorder(
        output, seconds=1, clock=lambda: clock["ms"], monotonic=lambda: clock["ns"]
    )
    for index, symbol in enumerate(capture.SYMBOLS):
        # Exchange E is not globally monotonic across independent symbols.
        event = START + 10 - index
        raw = json.dumps(
            {
                "stream": f"{symbol.lower()}@depth10@100ms",
                "data": {
                    "e": "depthUpdate",
                    "E": event,
                    "T": event - 1,
                    "s": symbol,
                    "U": 99,
                    "u": 100,
                    "pu": 98,
                    "st": 1,
                    "ps": symbol,
                    "b": [["100", "1"]],
                    "a": [["101", "1"]],
                },
            },
            separators=(",", ":"),
        )
        clock["ms"] = START + 100 + index * 100
        clock["ns"] = MONO + (100 + index * 100) * 1_000_000
        rec.accept(raw, received_ms=clock["ms"], received_ns=clock["ns"])
    clock.update(ms=START + 1_000, ns=MONO + 1_000_000_000)
    receipt = rec.finish(
        state="CAPTURED",
        reason="SYNTHETIC_TEST_COMPLETE",
        transport={
            "endpoint": capture.ENDPOINT,
            "attempts": 1,
            "retries": 0,
            "redirects": 0,
            "tls_default_validation": True,
            "handshake_completed": True,
        },
    )
    assert receipt["state"] == "CAPTURED"
    return output, hashlib.sha256((output / "receipt.json").read_bytes()).hexdigest()


def test_global_mapping_keeps_complete_denominator_physical_epoch_and_original_clocks(tmp_path, monkeypatch):
    output, sha = _capture(tmp_path, monkeypatch)
    tape = mapping.load_public_book_tape(output, expected_receipt_sha256=sha)
    raw = [json.loads(line) for line in (output / "received.raw.jsonl").read_bytes().splitlines()]
    assert len(tape.frames) == 5
    assert {item.segment_ordinal for item in tape.frames} == {1, 2, 3}
    assert tuple(item.frame.sequence for item in tape.frames) == (1, 2, 3, 4, 5)
    assert all(item.frame.stream_epoch == tape.epoch for item in tape.frames)
    for item, row in zip(tape.frames, raw, strict=True):
        assert item.frame.received_at_ms == row["received_ms"]
        assert item.frame.raw_payload_sha256 == row["raw_payload_sha256"]
        assert item.raw_record_sha256 == row["record_sha256"]
        tape.require_member(item.frame, item.mapping_sha256)
    assert mapping.load_public_book_tape(output, expected_receipt_sha256=sha).sha256 == tape.sha256


def test_changed_raw_middle_read_is_not_authenticated_by_restore_before_second_audit(tmp_path, monkeypatch):
    output, sha = _capture(tmp_path, monkeypatch)
    path = output / "received.raw.jsonl"
    original = path.read_bytes()
    rows = [json.loads(line) for line in original.splitlines()]
    rows[0]["record_sha256"] = "f" * 64
    changed = b"".join((canonical(row) + "\n").encode() for row in rows)
    real_audit = mapping.audit_public_capture
    calls = []

    def change_then_restore(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            path.write_bytes(original)
        result = real_audit(*args, **kwargs)
        if len(calls) == 1:
            path.write_bytes(changed)
        return result

    monkeypatch.setattr(mapping, "audit_public_capture", change_then_restore)
    try:
        with pytest.raises(ValueError, match="raw snapshot"):
            mapping.load_public_book_tape(output, expected_receipt_sha256=sha)
        assert len(calls) == 1  # rejection does not rely on a second mutable-folder audit
    finally:
        path.write_bytes(original)


def test_mapping_requires_exact_member_not_matching_sequence_only(tmp_path, monkeypatch):
    output, sha = _capture(tmp_path, monkeypatch)
    tape = mapping.load_public_book_tape(output, expected_receipt_sha256=sha)
    item = tape.frames[0]
    changed = item.frame.model_copy(update={"exchange_update_id": 101})
    with pytest.raises(ValueError, match="differs"):
        tape.require_member(changed, item.mapping_sha256)
    with pytest.raises(ValueError, match="differs"):
        tape.require_member(item.frame, "f" * 64)


def test_mapping_rejects_global_local_clock_regression(tmp_path, monkeypatch):
    output, sha = _capture(tmp_path, monkeypatch)
    tape = mapping.load_public_book_tape(output, expected_receipt_sha256=sha)
    items = list(tape.frames)
    item = items[1]
    items[1] = replace(
        item,
        frame=item.frame.model_copy(
            update={
                "received_at_ms": START + 50,
                "persisted_at_ms": START + 50,
            }
        ),
    )
    with pytest.raises(ValueError, match="clocks must not regress"):
        replace(tape, frames=tuple(items))


def _repeated_symbol_tail(tape, **overrides):
    item = tape.frames[0]
    clocks = {
        "sequence": len(tape.frames) + 1,
        "exchange_update_id": item.frame.exchange_update_id + 1,
        "exchange_at_ms": item.frame.exchange_at_ms + 1,
        "received_at_ms": START + 600,
        "persisted_at_ms": START + 600,
    }
    clocks.update(overrides)
    return replace(item, frame=item.frame.model_copy(update=clocks), segment_ordinal=4, segment_sequence=1)


def test_mapping_constructor_preserves_symbol_history_across_segment_rotation(tmp_path, monkeypatch):
    output, sha = _capture(tmp_path, monkeypatch)
    tape = mapping.load_public_book_tape(output, expected_receipt_sha256=sha)
    tail = _repeated_symbol_tail(tape)
    assert len(replace(tape, frames=(*tape.frames, tail)).frames) == 6


@pytest.mark.parametrize("field", ["exchange_update_id", "exchange_at_ms"])
def test_mapping_constructor_refuses_symbol_regression_across_segment_rotation(tmp_path, monkeypatch, field):
    output, sha = _capture(tmp_path, monkeypatch)
    tape = mapping.load_public_book_tape(output, expected_receipt_sha256=sha)
    old = getattr(tape.frames[0].frame, field)
    tail = _repeated_symbol_tail(tape, **{field: old if field == "exchange_update_id" else old - 1})
    with pytest.raises(ValueError, match="per-symbol"):
        replace(tape, frames=(*tape.frames, tail))


def test_mapping_constructor_does_not_reset_symbol_gap_at_segment_boundary(tmp_path, monkeypatch):
    output, sha = _capture(tmp_path, monkeypatch)
    tape = mapping.load_public_book_tape(output, expected_receipt_sha256=sha)
    tail = _repeated_symbol_tail(tape, received_at_ms=START + 6_000, persisted_at_ms=START + 6_000)
    with pytest.raises(ValueError, match="per-symbol"):
        replace(tape, frames=(*tape.frames, tail))


def test_mapping_rejects_wrong_independent_terminal_commitment(tmp_path, monkeypatch):
    output, _ = _capture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="terminal bytes"):
        mapping.load_public_book_tape(output, expected_receipt_sha256="f" * 64)


def test_failed_capture_never_maps_to_accepted_tape(tmp_path):
    output = tmp_path / "public-book-capture-20261009-failed"
    rec = capture.PublicBookRecorder(output, seconds=1, clock=lambda: START, monotonic=lambda: MONO)
    rec.finish(
        state="FAILED",
        reason="SYNTHETIC_FAILURE",
        transport={
            "endpoint": capture.ENDPOINT,
            "attempts": 1,
            "retries": 0,
            "redirects": 0,
            "tls_default_validation": True,
            "handshake_completed": True,
        },
    )
    sha = hashlib.sha256((output / "receipt.json").read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="failed/partial"):
        mapping.load_public_book_tape(output, expected_receipt_sha256=sha)
