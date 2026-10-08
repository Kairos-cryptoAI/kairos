"""Synthetic durable source retention checks, never provider/market qualification."""

import hashlib
import json
import os
from dataclasses import replace

import pytest
from kairos_core.contracts.simulation import RecordedBookLevelV1, RecordedTopNBookFrameV2

import adaptive_replay.book_bundle as module
from adaptive_replay.book_bundle import (
    MAX_FILE_BYTES,
    MAX_RECORD_BYTES,
    BookBundleSeal,
    RetentionReceipt,
    admit_retained_book_capture,
    open_book_bundle,
    prepare_book_bundle,
    retain_book_bundle,
)
from adaptive_replay.historical_context import canonical
from adaptive_replay.native_book_capture import MIGRATED_PROFILE, NativeBookCapture, NativeBookPolicy

POLICY = NativeBookPolicy(MIGRATED_PROFILE, "fixture-quotes", 100, "TEST_FIXTURE")


def frame(sequence=1, previous=None, *, symbol="BTCUSDT", event=None, **changes):
    event = 1_000 + sequence * 10 if event is None else event
    body = {
        "e": "depthUpdate",
        "E": event,
        "T": event - 1,
        "s": symbol,
        "U": sequence * 10,
        "u": sequence * 10 + 1,
        "pu": sequence * 10 - 1,
        "b": [["100.00", "2.0"]],
        "a": [["100.01", "3.0"]],
        "st": 1,
        "ps": symbol,
    }
    raw = json.dumps({"stream": f"{symbol.lower()}@depth10@100ms", "data": body}, indent=2)
    values = dict(
        source="offline-fixture",
        tape_id="fixture-tape",
        stream_epoch="fixture-epoch",
        symbol=symbol,
        tape_sequence=sequence,
        exchange_update_id=body["u"],
        exchange_at_ms=event,
        received_at_ms=event + 1,
        persisted_at_ms=event + 2,
        raw_payload=raw,
        raw_payload_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        previous_frame_sha256=previous,
        continuity="ADMITTED",
        source_reason="OFFLINE_FIXTURE",
        bids=(RecordedBookLevelV1(price=100.0, quantity=2.0),),
        asks=(RecordedBookLevelV1(price=100.01, quantity=3.0),),
    )
    values.update(changes)
    return RecordedTopNBookFrameV2(**values)


def fixture(tmp_path, *, frames=None):
    if frames is None:
        root = frame()
        frames = (root, frame(2, root.frame_sha256, symbol="ETHUSDT"))
    seal = prepare_book_bundle("bundle-fixture", frames, POLICY)
    path = tmp_path / "quotes.native-book.research.json"
    receipt = retain_book_bundle(path, seal, frames)
    return path, seal, receipt, frames


def rewrite(path, receipt, transform):
    payload = json.loads(path.read_bytes())
    transform(payload)
    raw = canonical(payload).encode()
    path.write_bytes(raw)
    return replace(receipt, file_sha256=hashlib.sha256(raw).hexdigest())


def test_retention_exact_raw_and_derived_bytes_restart_and_readonly_restore(tmp_path):
    path, seal, receipt, frames = fixture(tmp_path)
    before = path.read_bytes()
    opened = open_book_bundle(path, seal, receipt)
    assert opened.seal == seal
    assert receipt.retained_at_ms > frames[-1].persisted_at_ms
    assert (receipt.risk_authority, receipt.coverage_authority, receipt.clock_authority) == (
        "NONE",
        module.COVERAGE,
        module.CLOCKS,
    )
    for original, retained in zip(frames, opened.bindings, strict=True):
        assert retained.frame == original
        assert retained.frame.raw_payload.encode() == original.raw_payload.encode()
        assert retained.capture.raw_payload != original.raw_payload.encode()
        assert retained.sha256 == NativeBookCapture(original, POLICY).sha256
    restored = tmp_path / "restored.native-book.research.json"
    restored.write_bytes(before)
    assert open_book_bundle(restored, seal, receipt) == opened
    assert path.read_bytes() == before
    assert len(seal.sha256) == len(receipt.sha256) == 64


def test_lookup_reports_all_visible_prefix_not_only_selected_frame(tmp_path):
    path, seal, receipt, frames = fixture(tmp_path)
    selected = NativeBookCapture(frames[0], POLICY)
    accepted = admit_retained_book_capture(
        path,
        seal,
        receipt,
        sequence=1,
        expected_binding_sha256=selected.sha256,
        asof_ms=frames[-1].persisted_at_ms,
        after_ms=1_000,
    )
    assert accepted.binding == selected
    assert accepted.prefix.frame_sha256s == tuple(f.frame_sha256 for f in frames)
    assert dict(accepted.prefix.symbol_counts)["SOLUSDT"] == 0
    assert accepted.risk_authority == "NONE"
    assert accepted.prefix.coverage_authority == module.COVERAGE
    earlier = admit_retained_book_capture(
        path,
        seal,
        receipt,
        sequence=1,
        expected_binding_sha256=selected.sha256,
        asof_ms=frames[0].persisted_at_ms,
        after_ms=1_000,
    )
    assert earlier.prefix.frame_sha256s == (frames[0].frame_sha256,)


@pytest.mark.parametrize(
    "change",
    [
        {"sequence": 3},
        {"sequence": 0},
        {"sequence": True},
        {"sequence": 513},
        {"expected_binding_sha256": "0" * 64},
        {"asof_ms": 1_011},
        {"after_ms": 1_011},
        {"after_ms": 1_101},
        {"asof_ms": 1_111},
        {"asof_ms": True},
        {"after_ms": -1},
    ],
)
def test_no_lookup_substitution_backfill_or_ttl_renewal(tmp_path, change):
    path, seal, receipt, frames = fixture(tmp_path)
    args = dict(
        sequence=1,
        expected_binding_sha256=NativeBookCapture(frames[0], POLICY).sha256,
        asof_ms=1_012,
        after_ms=1_000,
    )
    args.update(change)
    with pytest.raises(ValueError):
        admit_retained_book_capture(path, seal, receipt, **args)


def test_exact_event_ttl_boundary_is_inclusive(tmp_path):
    path, seal, receipt, frames = fixture(tmp_path)
    accepted = admit_retained_book_capture(
        path,
        seal,
        receipt,
        sequence=1,
        expected_binding_sha256=NativeBookCapture(frames[0], POLICY).sha256,
        asof_ms=1_110,
        after_ms=1_010,
    )
    assert accepted.binding.frame == frames[0]


@pytest.mark.parametrize(
    "field,value",
    [
        ("bundle_id", "wrong"),
        ("tape_id", "wrong"),
        ("stream_epoch", "wrong"),
        ("frame_count", 1),
        ("native_head_sha256", "0" * 64),
        ("records_sha256", "0" * 64),
        ("implementation_sha256", "0" * 64),
        ("policy", NativeBookPolicy(MIGRATED_PROFILE, "other", 100, "TEST_FIXTURE")),
    ],
)
def test_caller_seal_conflicts_refused_without_rewriting(tmp_path, field, value):
    path, seal, receipt, _ = fixture(tmp_path)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        open_book_bundle(path, replace(seal, **{field: value}), receipt)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("seal_sha256", "0" * 64),
        ("file_sha256", "0" * 64),
        ("retained_at_ms", 0),
        ("frame_count", 1),
        ("native_head_sha256", "0" * 64),
    ],
)
def test_caller_receipt_conflicts_refused(tmp_path, field, value):
    path, seal, receipt, _ = fixture(tmp_path)
    with pytest.raises(ValueError):
        open_book_bundle(path, seal, replace(receipt, **{field: value}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("risk_authority", "ALLOW"),
        ("coverage_authority", "COMPLETE"),
        ("clock_authority", "VERIFIED"),
        ("frame_count", True),
        ("retained_at_ms", True),
    ],
)
def test_retention_receipt_cannot_claim_more_authority(tmp_path, field, value):
    _, _, receipt, _ = fixture(tmp_path)
    with pytest.raises(ValueError):
        replace(receipt, **{field: value})


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(extra=1),
        lambda p: p.update(schema="wrong"),
        lambda p: p.update(retained_at_ms=True),
        lambda p: p["seal"].update(bundle_id="wrong"),
        lambda p: p["records"].pop(),
        lambda p: p["records"].reverse(),
        lambda p: p["records"].append(p["records"][0]),
        lambda p: p["records"][0].update(extra=1),
        lambda p: p["records"][0].update(binding_sha256="0" * 64),
        lambda p: p["records"][0]["derived_capture"].update(captured_ms=1_010),
        lambda p: p["records"][0]["derived_capture"].update(raw_payload_utf8="{}"),
        lambda p: p["records"][0]["frame"].update(raw_payload="{}"),
        lambda p: p["records"][0]["frame"].update(raw_payload_sha256="0" * 64),
        lambda p: p["records"][0]["frame"].update(exchange_update_id=3),
        lambda p: p["records"][0]["frame"].update(persisted_at_ms=True),
        lambda p: p["records"][0]["frame"]["bids"][0].update(quantity=9.0),
        lambda p: p["records"][1]["frame"].update(previous_frame_sha256="0" * 64),
    ],
)
def test_full_reconstruction_refuses_internal_conflict_even_with_new_file_hash(tmp_path, mutation):
    path, seal, receipt, _ = fixture(tmp_path)
    changed = rewrite(path, receipt, mutation)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        open_book_bundle(path, seal, changed)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "raw", [b"", b"{", b"\xff", b"\xef\xbb\xbf{}", b'{"schema":1,"schema":2}', b'{"x":NaN}']
)
def test_malformed_source_bytes_preserved_no_repair(tmp_path, raw):
    path, seal, receipt, _ = fixture(tmp_path)
    path.write_bytes(raw)
    changed = replace(receipt, file_sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError):
        open_book_bundle(path, seal, changed)
    assert path.read_bytes() == raw


def test_truncation_and_whole_valid_older_prefix_rollback_require_original_receipt(tmp_path):
    path, seal, receipt, frames = fixture(tmp_path)
    old_seal = prepare_book_bundle("bundle-fixture", frames[:1], POLICY)
    old_path = tmp_path / "old.native-book.research.json"
    old_receipt = retain_book_bundle(old_path, old_seal, frames[:1])
    path.write_bytes(old_path.read_bytes())
    with pytest.raises(ValueError):
        open_book_bundle(path, seal, receipt)
    with pytest.raises(ValueError):
        open_book_bundle(path, seal, old_receipt)
    # Coordinated replacement of file AND expectations is out of the trust claim.
    assert len(open_book_bundle(path, old_seal, old_receipt).bindings) == 1


def test_existing_missing_invalid_path_and_failed_attempt_are_not_recreated(tmp_path, monkeypatch):
    path, seal, receipt, frames = fixture(tmp_path)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        retain_book_bundle(path, seal, frames)
    assert path.read_bytes() == before
    missing = tmp_path / "missing.native-book.research.json"
    with pytest.raises(FileNotFoundError):
        open_book_bundle(missing, seal, receipt)
    assert not missing.exists()
    with pytest.raises(ValueError):
        retain_book_bundle(tmp_path / "quotes.json", seal, frames)
    with pytest.raises(FileNotFoundError):
        retain_book_bundle(tmp_path / "no-parent" / missing.name, seal, frames)

    def fail_sync(_):
        raise OSError("fixture interrupted persistence")

    monkeypatch.setattr(module.os, "fsync", fail_sync)
    with pytest.raises(OSError, match="interrupted persistence"):
        retain_book_bundle(missing, seal, frames)
    failed = missing.read_bytes()
    assert failed
    with pytest.raises(FileExistsError):
        retain_book_bundle(missing, seal, frames)
    assert missing.read_bytes() == failed


@pytest.mark.parametrize("kind", ["empty", "list", "oversize", "non-native"])
def test_complete_immutable_prefix_bounds(kind):
    root = frame()
    frames = {"empty": (), "list": [root], "oversize": (root,) * 513, "non-native": ({},)}[kind]
    with pytest.raises(ValueError):
        prepare_book_bundle("fixture", frames, POLICY)


def test_full_512_frame_prefix_is_retained_without_sampling(tmp_path):
    frames = []
    previous = None
    for sequence in range(1, 513):
        retained = frame(sequence, previous)
        frames.append(retained)
        previous = retained.frame_sha256
    path, seal, receipt, _ = fixture(tmp_path, frames=tuple(frames))
    assert seal.frame_count == receipt.frame_count == 512
    assert len(open_book_bundle(path, seal, receipt).bindings) == 512


def test_byte_and_record_bounds_never_truncate(tmp_path, monkeypatch):
    root = frame()
    seal = prepare_book_bundle("fixture", (root,), POLICY)
    path = tmp_path / "bounded.native-book.research.json"
    monkeypatch.setattr(module, "MAX_FILE_BYTES", 1)
    with pytest.raises(ValueError, match="bounded complete source file"):
        retain_book_bundle(path, seal, (root,))
    assert not path.exists()
    monkeypatch.setattr(module, "MAX_FILE_BYTES", MAX_FILE_BYTES)
    monkeypatch.setattr(module, "MAX_RECORD_BYTES", 1)
    with pytest.raises(ValueError, match="bounded native record"):
        retain_book_bundle(path, seal, (root,))
    assert not path.exists()
    assert MAX_RECORD_BYTES < MAX_FILE_BYTES


def test_changed_installed_implementation_fails_closed_without_adoption(tmp_path, monkeypatch):
    path, seal, receipt, _ = fixture(tmp_path)
    monkeypatch.setattr(module, "implementation_binding", lambda: canonical({"changed": True}))
    with pytest.raises(ValueError, match="implementation changed"):
        open_book_bundle(path, seal, receipt)


def test_future_native_persistence_cannot_be_retained_with_a_modern_past_clock(tmp_path, monkeypatch):
    frames = (frame(),)
    seal = prepare_book_bundle("fixture", frames, POLICY)
    path = tmp_path / "future.native-book.research.json"
    monkeypatch.setattr(module.time, "time_ns", lambda: 1_011 * 1_000_000)
    with pytest.raises(ValueError, match="postdate modern retention"):
        retain_book_bundle(path, seal, frames)
    assert not path.exists()


def test_reopen_refuses_receipted_modern_time_before_original_persistence(tmp_path):
    path, seal, receipt, _ = fixture(tmp_path)
    changed = rewrite(path, receipt, lambda p: p.update(retained_at_ms=1_011))
    changed = replace(changed, retained_at_ms=1_011)
    with pytest.raises(ValueError, match="root/head/content commitment"):
        open_book_bundle(path, seal, changed)


def test_noncanonical_encoding_and_symlink_are_not_adopted(tmp_path):
    path, seal, receipt, _ = fixture(tmp_path)
    raw = path.read_bytes() + b"\n"
    path.write_bytes(raw)
    changed = replace(receipt, file_sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match="encoding required"):
        open_book_bundle(path, seal, changed)
    alias = tmp_path / "alias.native-book.research.json"
    try:
        alias.symlink_to(path)
    except OSError:
        # Some Windows accounts cannot create symlinks; no new skip is introduced.
        return
    with pytest.raises(ValueError, match="symlinks"):
        open_book_bundle(alias, seal, receipt)


def test_aliased_hardlink_source_is_refused(tmp_path):
    path, seal, receipt, _ = fixture(tmp_path)
    alias = tmp_path / "alias.native-book.research.json"
    os.link(path, alias)
    with pytest.raises(ValueError, match="unaliased"):
        open_book_bundle(path, seal, receipt)
    with pytest.raises(ValueError, match="unaliased"):
        open_book_bundle(alias, seal, receipt)


def test_invalid_constructed_seal_and_untyped_receipts_are_refused(tmp_path):
    path, seal, receipt, frames = fixture(tmp_path)
    malformed = object.__new__(BookBundleSeal)
    for name, value in seal.__dict__.items():
        object.__setattr__(malformed, name, value)
    object.__setattr__(malformed, "policy", {})
    with pytest.raises(ValueError):
        open_book_bundle(path, malformed, receipt)
    with pytest.raises(ValueError):
        open_book_bundle(path, seal, {})
    with pytest.raises(ValueError):
        retain_book_bundle(path, {}, frames)
    assert isinstance(receipt, RetentionReceipt)
