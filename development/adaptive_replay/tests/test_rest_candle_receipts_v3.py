from __future__ import annotations

import os
from pathlib import Path

import pytest

from adaptive_replay import rest_candle_receipts_v3 as MODULE

CandleRequestV3 = MODULE.CandleRequestV3
ReceiptCheckpoint = MODULE.ReceiptCheckpoint
ReceiptIntegrityError = MODULE.ReceiptIntegrityError
ReceiptLimitError = MODULE.ReceiptLimitError
ReceiptStoreError = MODULE.ReceiptStoreError
RestCandleReceiptStoreV3 = MODULE.RestCandleReceiptStoreV3


def _store(tmp_path: Path, *, clock=lambda: 1_000):
    output = tmp_path / "receipt-run"
    store = RestCandleReceiptStoreV3.create(output, wall_ms=clock)
    return output, store


def _record(store, *, attempt_id="attempt-1", body=b"[]\n"):
    return store.record_response(
        attempt_id=attempt_id,
        request=CandleRequestV3("BTCUSDT", 1_500),
        requested_at_ms=100,
        response_received_at_ms=200,
        http_status=200,
        raw_response=body,
    )


def _sequence(*values: int):
    iterator = iter(values)
    return lambda: next(iterator)


def test_exact_response_bytes_and_failed_http_body_are_retained_without_json_parsing(tmp_path):
    output, store = _store(tmp_path, clock=_sequence(250, 350))
    odd_bytes = b'[  "one",\r\n {not-json} ]  \n'
    first = store.record_response(
        attempt_id="attempt-1",
        request=CandleRequestV3("BTCUSDT", 1_500),
        requested_at_ms=100,
        response_received_at_ms=200,
        http_status=200,
        raw_response=odd_bytes,
    )
    error_body = b'{ "error" : "rate limited" }\n'
    second = store.record_response(
        attempt_id="attempt-2",
        request=CandleRequestV3("ETHUSDT", 1),
        requested_at_ms=300,
        response_received_at_ms=320,
        http_status=429,
        raw_response=error_body,
    )

    assert first.raw_response_sha256 == MODULE._sha256(odd_bytes)
    assert first.persisted_at_ms == 250
    assert second.http_status == 429
    assert second.raw_response_bytes == len(error_body)
    reopened = RestCandleReceiptStoreV3.reopen(
        output,
        expected_checkpoint=store.checkpoint,
        wall_ms=lambda: 999,
    )
    assert (output / "attempts" / first.raw_response_file).read_bytes() == odd_bytes
    assert (output / "attempts" / second.raw_response_file).read_bytes() == error_body
    assert reopened.checkpoint == store.checkpoint
    assert [item.http_status for item in reopened.attempts] == [200, 429]


def test_no_response_is_an_explicit_denominator_row_and_reopens(tmp_path):
    output, store = _store(tmp_path, clock=lambda: 150)
    receipt = store.record_no_response(
        attempt_id="cancelled-1",
        request=CandleRequestV3("SOLUSDT", 20),
        requested_at_ms=100,
        failure_kind="INTERRUPTED",
    )

    assert receipt.state == "NO_RESPONSE"
    assert receipt.response_received_at_ms is None
    assert receipt.http_status is None
    assert receipt.raw_response_file is None
    assert receipt.failure_kind == "INTERRUPTED"
    reopened = RestCandleReceiptStoreV3.reopen(
        output,
        expected_checkpoint=store.checkpoint,
        wall_ms=lambda: 999,
    )
    assert len(reopened.attempts) == 1
    assert (output / "attempts" / "00000001.no-response.marker").read_bytes() == b"NO_HTTP_RESPONSE\n"


def test_reopen_requires_independent_exact_checkpoint(tmp_path):
    output, store = _store(tmp_path)
    _record(store)

    with pytest.raises(ReceiptIntegrityError, match="checkpoint"):
        RestCandleReceiptStoreV3.reopen(
            output,
            expected_checkpoint=ReceiptCheckpoint(0, None),
            wall_ms=lambda: 1_000,
        )
    with pytest.raises(TypeError):
        RestCandleReceiptStoreV3.reopen(output, wall_ms=lambda: 1_000)


@pytest.mark.parametrize(
    "received,persisted",
    [(300, 299), (300, 100)],
)
def test_future_or_rollback_persistence_clock_fails_closed_without_cleanup(tmp_path, received, persisted):
    output, store = _store(tmp_path, clock=lambda: persisted)
    body = b"not parsed"
    with pytest.raises(ReceiptStoreError, match="persisted clock"):
        store.record_response(
            attempt_id="clock-bad",
            request=CandleRequestV3("BTCUSDT", 5),
            requested_at_ms=100,
            response_received_at_ms=received,
            http_status=200,
            raw_response=body,
        )

    orphan = output / "attempts" / "00000001.response.raw"
    assert orphan.read_bytes() == body
    assert not (output / "attempts" / "00000001.receipt.json").exists()
    with pytest.raises(ReceiptIntegrityError):
        RestCandleReceiptStoreV3.reopen(
            output,
            expected_checkpoint=ReceiptCheckpoint(0, None),
            wall_ms=lambda: 1_000,
        )
    assert orphan.exists(), "failed attempts are retained rather than cleaned up"


def test_cross_attempt_clock_rollback_retains_orphan_and_prevents_reopen(tmp_path):
    output, store = _store(tmp_path, clock=_sequence(250, 249))
    _record(store)
    with pytest.raises(ReceiptStoreError, match="regressed"):
        store.record_response(
            attempt_id="attempt-2",
            request=CandleRequestV3("ETHUSDT", 1),
            requested_at_ms=240,
            response_received_at_ms=245,
            http_status=200,
            raw_response=b"second exact body",
        )
    assert (output / "attempts" / "00000002.response.raw").read_bytes() == b"second exact body"
    with pytest.raises(ReceiptIntegrityError):
        RestCandleReceiptStoreV3.reopen(
            output,
            expected_checkpoint=store.checkpoint,
            wall_ms=lambda: 1_000,
        )


def test_duplicate_attempt_id_is_rejected_without_mutating_the_ledger(tmp_path):
    output, store = _store(tmp_path, clock=_sequence(250, 300))
    original = _record(store)
    with pytest.raises(ReceiptIntegrityError, match="already exists"):
        store.record_response(
            attempt_id="attempt-1",
            request=CandleRequestV3("ETHUSDT", 9),
            requested_at_ms=100,
            response_received_at_ms=200,
            http_status=503,
            raw_response=b"conflicting duplicate",
        )
    assert store.checkpoint.attempt_count == 1
    assert (output / "attempts" / original.raw_response_file).read_bytes() == b"[]\n"
    reopened = RestCandleReceiptStoreV3.reopen(
        output,
        expected_checkpoint=store.checkpoint,
        wall_ms=lambda: 999,
    )
    assert len(reopened.attempts) == 1


def test_tampered_raw_body_or_receipt_is_detected(tmp_path):
    output, store = _store(tmp_path)
    receipt = _record(store, body=b"original")
    raw_path = output / "attempts" / receipt.raw_response_file
    raw_path.write_bytes(b"tampered")

    with pytest.raises(ReceiptIntegrityError, match="raw response bytes"):
        RestCandleReceiptStoreV3.reopen(
            output,
            expected_checkpoint=store.checkpoint,
            wall_ms=lambda: 1_000,
        )

    raw_path.write_bytes(b"original")
    receipt_path = output / "attempts" / "00000001.receipt.json"
    receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
    with pytest.raises(ReceiptIntegrityError, match="canonical"):
        RestCandleReceiptStoreV3.reopen(
            output,
            expected_checkpoint=store.checkpoint,
            wall_ms=lambda: 1_000,
        )


def test_interrupted_partial_attempt_fails_closed_and_is_not_repaired(tmp_path):
    output, _store_instance = _store(tmp_path)
    orphan = output / "attempts" / "00000001.response.raw"
    orphan.write_bytes(b"partial attempt bytes")

    with pytest.raises(ReceiptIntegrityError, match="interrupted"):
        RestCandleReceiptStoreV3.reopen(
            output,
            expected_checkpoint=ReceiptCheckpoint(0, None),
            wall_ms=lambda: 1_000,
        )
    assert orphan.read_bytes() == b"partial attempt bytes"


def test_linked_output_paths_are_rejected(tmp_path):
    target = tmp_path / "real-parent"
    target.mkdir()
    link = tmp_path / "linked-parent"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"local filesystem does not permit symlink creation: {type(exc).__name__}")

    with pytest.raises(ReceiptStoreError, match="linked or reparse"):
        RestCandleReceiptStoreV3.create(link / "receipt-run", wall_ms=lambda: 1_000)
    assert not (target / "receipt-run").exists()


def test_attempts_directory_identity_is_pinned_before_append(tmp_path):
    output, store = _store(tmp_path)
    attempts = output / "attempts"
    moved = output / "attempts-original"
    attempts.rename(moved)
    attempts.mkdir()

    with pytest.raises(ReceiptIntegrityError, match="directory identity changed"):
        _record(store)
    assert list(attempts.iterdir()) == []
    assert moved.is_dir()


def test_manifest_authority_is_rechecked_before_append(tmp_path):
    output, store = _store(tmp_path)
    manifest = output / "manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b" ")

    with pytest.raises(ReceiptIntegrityError, match="manifest"):
        _record(store)
    assert not list((output / "attempts").iterdir())


def test_hardlinked_raw_leaf_is_rejected_on_reopen(tmp_path):
    output, store = _store(tmp_path)
    receipt = _record(store, body=b"hardlink-check")
    raw_path = output / "attempts" / receipt.raw_response_file
    external = tmp_path / "linked-body.raw"
    external.write_bytes(raw_path.read_bytes())
    raw_path.unlink()
    try:
        os.link(external, raw_path)
    except OSError as exc:
        pytest.skip(f"local filesystem does not support hard links: {type(exc).__name__}")

    with pytest.raises(ReceiptStoreError, match="multiply linked"):
        RestCandleReceiptStoreV3.reopen(
            output,
            expected_checkpoint=store.checkpoint,
            wall_ms=lambda: 1_000,
        )


def test_bounded_reader_rejects_growth_while_reading(tmp_path, monkeypatch):
    output, store = _store(tmp_path)
    receipt = _record(store, body=b"grow")
    raw_path = output / "attempts" / receipt.raw_response_file
    raw_identity = MODULE._file_identity(raw_path.lstat())
    original_read = MODULE.os.read
    grew = False

    def read_then_grow(fd: int, size: int) -> bytes:
        nonlocal grew
        chunk = original_read(fd, size)
        if not grew and MODULE._file_identity(os.fstat(fd)) == raw_identity and chunk:
            grew = True
            with raw_path.open("ab") as stream:
                stream.write(b"+")
                stream.flush()
        return chunk

    monkeypatch.setattr(MODULE.os, "read", read_then_grow)
    with pytest.raises(ReceiptIntegrityError, match="grew|changed"):
        RestCandleReceiptStoreV3.reopen(
            output,
            expected_checkpoint=store.checkpoint,
            wall_ms=lambda: 1_000,
        )
    assert grew


def test_bounded_reader_rejects_identity_change_during_open(tmp_path, monkeypatch):
    output, store = _store(tmp_path)
    receipt = _record(store, body=b"identity")
    raw_path = output / "attempts" / receipt.raw_response_file
    raw_identity = MODULE._file_identity(raw_path.lstat())
    original_identity = MODULE._file_identity
    changed = False

    def changed_identity(metadata):
        nonlocal changed
        identity = original_identity(metadata)
        if identity == raw_identity and not changed:
            changed = True
            return identity[0], identity[1] + 1
        return identity

    monkeypatch.setattr(MODULE, "_file_identity", changed_identity)
    with pytest.raises(ReceiptIntegrityError, match="identity changed"):
        RestCandleReceiptStoreV3.reopen(
            output,
            expected_checkpoint=store.checkpoint,
            wall_ms=lambda: 1_000,
        )
    assert changed


def test_request_contract_and_byte_bounds_are_strict(tmp_path):
    with pytest.raises(ReceiptStoreError):
        CandleRequestV3("btcusdt", 10)
    with pytest.raises(ReceiptStoreError):
        CandleRequestV3("BTCUSDT", True)

    _output, store = _store(tmp_path)
    with pytest.raises(ReceiptLimitError, match="2 MiB"):
        store.record_response(
            attempt_id="oversize",
            request=CandleRequestV3("BTCUSDT", 1),
            requested_at_ms=1,
            response_received_at_ms=2,
            http_status=200,
            raw_response=b"x" * (MODULE.MAX_BODY_BYTES + 1),
        )
    assert store.checkpoint == ReceiptCheckpoint(0, None)
