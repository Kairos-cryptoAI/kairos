"""Synthetic version transfer only: no legacy export run or source promotion."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from adaptive_replay import public_book_capture as capture
from adaptive_replay import public_book_transfer as transfer
from adaptive_replay.continuous_sim import TapeBinding, TapeInput
from adaptive_replay.historical_context import canonical, digest
from adaptive_replay.hypothesis_journal import implementation_binding
from adaptive_replay.sim_book_tape import load_public_book_tape

SCRIPT = Path(__file__).parents[1] / "scripts" / "export_legacy_public_book_tape.py"
spec = importlib.util.spec_from_file_location("standalone_legacy_exporter", SCRIPT)
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)
START = 1_791_400_000_000
MONO = 9_000_000_000_000


@pytest.fixture
def sample(tmp_path, request):
    clock = {"ms": START, "ns": MONO}
    source = tmp_path / "public-book-capture-20261009-transfer-fixture"
    recorder = capture.PublicBookRecorder(
        source, seconds=1, clock=lambda: clock["ms"], monotonic=lambda: clock["ns"]
    )
    frame_count = getattr(request, "param", 10)
    step_ms = 90 if frame_count == 10 else 2
    for index in range(frame_count):
        symbol = capture.SYMBOLS[index % 5]
        event = START + 10 + (index // 5) * step_ms * 5 - index % 5
        raw = json.dumps(
            {
                "stream": f"{symbol.lower()}@depth10@100ms",
                "data": {
                    "e": "depthUpdate",
                    "E": event,
                    "T": event - 1,
                    "s": symbol,
                    "U": 99 + index // 5,
                    "u": 100 + index // 5,
                    "pu": 98 + index // 5,
                    "st": 1,
                    "ps": symbol,
                    "b": [["100", "1"]],
                    "a": [["101", "1"]],
                },
            },
            separators=(",", ":"),
        )
        clock.update(ms=START + 100 + index * step_ms, ns=MONO + (100 + index * step_ms) * 1_000_000)
        recorder.accept(raw, received_ms=clock["ms"], received_ns=clock["ns"])
    clock.update(ms=START + 1000, ns=MONO + 1_000_000_000)
    recorder.finish(
        state="CAPTURED",
        reason="SYNTHETIC_TEST_ONLY",
        transport={
            "endpoint": capture.ENDPOINT,
            "attempts": 1,
            "retries": 0,
            "redirects": 0,
            "tls_default_validation": True,
            "handshake_completed": True,
        },
    )
    receipt_bytes = (source / "receipt.json").read_bytes()
    receipt_sha = exporter.sha(receipt_bytes)
    audit = capture.audit_public_capture(source, expected_receipt_sha256=receipt_sha)
    tape = load_public_book_tape(source, expected_receipt_sha256=receipt_sha)
    implementation = implementation_binding()
    manifest = json.loads(implementation)["sources"]
    producer = {
        "wheel_sha256": "a" * 64,
        "exporter_script_sha256": exporter.sha(SCRIPT.read_bytes()),
        "implementation_utf8": implementation,
        "implementation_sha256": exporter.sha(implementation.encode()),
        "sources": {
            key: {"path": logical, "sha256": manifest.get(logical, "b" * 64)}
            for key, logical in {
                "loader": "adaptive_replay/sim_book_tape.py",
                "auditor": "adaptive_replay/public_book_capture.py",
                "kernel_bridge": "kairos_execution/simulation/bridge.py",
                "kernel_models": "kairos_execution/simulation/models.py",
            }.items()
        },
        "python_version": "3.11.9",
        "isolated_private_environment": True,
    }
    raw = exporter.build_document(
        receipt_bytes=receipt_bytes, legacy_audit=audit, tape=tape, producer=producer
    )
    path = tmp_path / "synthetic-transfer.research.json"
    path.write_bytes(raw)
    commitment = transfer.TransferCommitment(
        exporter.sha(raw),
        producer["wheel_sha256"],
        producer["exporter_script_sha256"],
        producer["implementation_sha256"],
        receipt_sha,
    )
    return path, commitment, tape


def _change(sample, mutate):
    path, commitment, _ = sample
    value = json.loads(path.read_bytes())
    mutate(value)
    raw = canonical(value).encode()
    path.write_bytes(raw)
    return path, replace(commitment, export_sha256=exporter.sha(raw))


def _relink(value):
    """Recommit frame/tape hashes, making semantic checks independently necessary."""
    from kairos_execution.simulation.models import AcceptedBookFrame

    from adaptive_replay.sim_book_tape import BoundBookFrame

    for row in value["tape"]["frames"]:
        frame = AcceptedBookFrame.model_validate_json(row["frame_utf8"])
        row["frame_sha256"] = frame.fingerprint()
        row["mapping_sha256"] = BoundBookFrame(
            frame,
            row["receipt_sha256"],
            row["native_frame_sha256"],
            row["raw_record_sha256"],
            row["segment_ordinal"],
            row["segment_sequence"],
        ).mapping_sha256
    value["tape"]["sha256"] = digest(
        {
            key: value["tape"][key]
            for key in ("receipt_sha256", "source_sha256", "tape_id", "epoch", "quote_source_id")
        }
        | {"mappings": [row["mapping_sha256"] for row in value["tape"]["frames"]]}
    )


def test_complete_original_mapping_import_and_current_portfolio_binding(sample, monkeypatch):
    path, commitment, tape = sample

    def forbidden(*args, **kwargs):
        raise AssertionError("current original auditor/loader must never execute")

    monkeypatch.setattr(capture, "audit_public_capture", forbidden)
    imported = transfer.import_public_book_transfer(path, commitment=commitment)
    assert imported.tape == tape
    assert imported.tape.sha256 == tape.sha256
    assert imported.source_authentication is False
    assert imported.risk_authority == "NONE"
    assert imported.validation_state == "PASS_LEGACY_EXPORT_BYTE_CONSISTENCY_ONLY"
    binding = TapeBinding(
        imported.source_id,
        tape.tape_id,
        tape.epoch,
        tape.quote_source_id,
        "CALLER_ATTESTED_POINT_IN_TIME",
        tuple(TapeInput(i, item.frame) for i, item in enumerate(tape.frames, 1)),
        imported.tape,
    )
    assert binding.public_book_tape is imported.tape
    for old, new in zip(tape.frames, imported.tape.frames, strict=True):
        assert old.frame.canonical_bytes() == new.frame.canonical_bytes()
        imported.tape.require_member(new.frame, old.mapping_sha256)


@pytest.mark.parametrize("sample", [260], indirect=True)
def test_complete_rollover_manifest_and_local_to_global_coordinates(sample):
    path, commitment, original = sample
    imported = transfer.import_public_book_transfer(path, commitment=commitment)
    assert len(imported.tape.frames) == 260
    assert imported.tape.frames[255].segment_ordinal == 1
    assert imported.tape.frames[255].segment_sequence == 256
    assert imported.tape.frames[256].segment_ordinal == 2
    assert imported.tape.frames[256].segment_sequence == 1
    assert imported.tape.sha256 == original.sha256


def test_typed_wrapper_cannot_upgrade_authority(sample):
    path, commitment, _ = sample
    imported = transfer.import_public_book_transfer(path, commitment=commitment)
    with pytest.raises(ValueError, match="cannot upgrade"):
        replace(imported, source_authentication=True)


@pytest.mark.parametrize(
    "field",
    [
        "export_sha256",
        "legacy_wheel_sha256",
        "exporter_script_sha256",
        "legacy_implementation_sha256",
        "receipt_sha256",
    ],
)
def test_independent_commitments_cannot_be_discovered_or_overridden(sample, field):
    path, commitment, _ = sample
    with pytest.raises(ValueError):
        transfer.import_public_book_transfer(path, commitment=replace(commitment, **{field: "f" * 64}))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(schema="kairos.development.public-book-transfer.v2"),
        lambda d: d.update(extra="not allowed"),
        lambda d: d["producer"].update(isolated_private_environment=False),
        lambda d: d["producer"].update(python_version="3.10.9"),
        lambda d: d["producer"]["sources"]["loader"].update(sha256="f" * 64),
        lambda d: d["producer"]["sources"]["loader"].update(path="C:/private/secret/source.py"),
        lambda d: d.update(limitations=[]),
        lambda d: d["legacy_audit"].update(source_set_admitted=True),
        lambda d: d["tape"].update(quote_source_id="new-normalized-source"),
        lambda d: d["tape"]["frames"].pop(),
        lambda d: d["tape"]["frames"][0].update(mapping_sha256="f" * 64),
        lambda d: d["tape"]["frames"][0].update(segment_sequence=2),
        lambda d: d["tape"]["frames"][0].update(native_frame_sha256="f" * 64),
        lambda d: d["tape"].update(sha256="f" * 64),
    ],
)
def test_recommitted_tampering_still_denied(sample, mutate):
    path, commitment = _change(sample, mutate)
    with pytest.raises(ValueError):
        transfer.import_public_book_transfer(path, commitment=commitment)


def test_noncanonical_or_duplicate_json_denied_even_with_outer_commitment(sample):
    path, commitment, _ = sample
    raw = path.read_bytes()
    for changed in (raw + b"\n", b'{"schema":"duplicate",' + raw[1:]):
        path.write_bytes(changed)
        with pytest.raises(ValueError):
            transfer.import_public_book_transfer(
                path, commitment=replace(commitment, export_sha256=exporter.sha(changed))
            )


@pytest.mark.parametrize(
    "kind", ["global_clock", "symbol_update", "numeric_decimal", "canonical_decimal", "kernel_version"]
)
def test_kernel_exact_bytes_and_original_continuity_no_normalization(sample, kind):
    def mutate(value):
        index = 1 if kind == "global_clock" else 5 if kind == "symbol_update" else 0
        row = value["tape"]["frames"][index]
        frame = json.loads(row["frame_utf8"])
        if kind == "global_clock":
            frame.update(received_at_ms=START + 20, persisted_at_ms=START + 20)
        elif kind == "symbol_update":
            frame["exchange_update_id"] = 100
        elif kind == "numeric_decimal":
            frame["bids"][0]["price"] = 100
        elif kind == "canonical_decimal":
            frame["bids"][0]["price"] = "100.0"
        else:
            frame["contract_version"] = "simulated-book-input.v2"
        row["frame_utf8"] = canonical(frame)
        if kind in {"global_clock", "symbol_update"}:
            _relink(value)

    path, commitment = _change(sample, mutate)
    with pytest.raises(ValueError):
        transfer.import_public_book_transfer(path, commitment=commitment)


def test_current_kernel_canonical_change_refuses_adoption(sample, monkeypatch):
    path, commitment, _ = sample
    from kairos_execution.simulation.models import AcceptedBookFrame

    original = AcceptedBookFrame.canonical_bytes
    monkeypatch.setattr(AcceptedBookFrame, "canonical_bytes", lambda self: original(self) + b" ")
    with pytest.raises(ValueError, match="no normalization"):
        transfer.import_public_book_transfer(path, commitment=commitment)


def test_original_receipt_seal_version_cannot_be_resealed(sample):
    path, commitment, _ = sample
    value = json.loads(path.read_bytes())
    receipt = json.loads(value["receipt_utf8"])
    receipt["segments"][0]["seal"]["implementation_sha256"] = "f" * 64
    value["receipt_utf8"] = canonical(receipt)
    raw = canonical(value).encode()
    path.write_bytes(raw)
    commitment = replace(
        commitment,
        export_sha256=exporter.sha(raw),
        receipt_sha256=exporter.sha(value["receipt_utf8"].encode()),
    )
    with pytest.raises(ValueError, match="implementation conflict"):
        transfer.import_public_book_transfer(path, commitment=commitment)


def test_snapshot_byte_hash_not_mutable_directory_second_read(sample, monkeypatch):
    path, commitment, _ = sample
    exact = path.read_bytes()

    def snapshot(_):
        path.write_bytes(b"mutated after one snapshot")
        return exact

    monkeypatch.setattr(transfer, "_snapshot", snapshot)
    assert transfer.import_public_book_transfer(path, commitment=commitment).tape.sha256 == sample[2].sha256


def test_import_rejects_hardlink_alias(sample, tmp_path):
    path, commitment, _ = sample
    alias = tmp_path / "aliased.json"
    os.link(path, alias)
    with pytest.raises(ValueError, match="unaliased"):
        transfer.import_public_book_transfer(alias, commitment=commitment)


def test_import_bounded_snapshot_denies_oversize_and_parent_traversal(sample, monkeypatch):
    path, commitment, _ = sample
    monkeypatch.setattr(transfer, "MAX_TRANSFER_BYTES", 10)
    with pytest.raises(ValueError, match="byte bound"):
        transfer.import_public_book_transfer(path, commitment=commitment)
    with pytest.raises(ValueError, match="parent traversal"):
        transfer.import_public_book_transfer(
            path.parent / "uncreated" / ".." / path.name, commitment=commitment
        )


@pytest.mark.parametrize("isolated,private", [(False, True), (True, False)])
def test_exporter_requires_isolated_private_runtime_without_imports(monkeypatch, isolated, private):
    from argparse import Namespace
    from types import SimpleNamespace

    # Explicitly exercise both denial boundaries, independent of whether the
    # surrounding test runner itself uses the stronger Python -I mode.
    monkeypatch.setattr(
        exporter,
        "sys",
        SimpleNamespace(
            flags=SimpleNamespace(isolated=isolated),
            prefix="private" if private else "base",
            base_prefix="base",
        ),
    )
    monkeypatch.setattr(exporter, "_runtime_sources", lambda _: pytest.fail("imports before runtime gate"))
    with pytest.raises(ValueError, match="private legacy Python -I"):
        exporter.export(Namespace())


def test_exporter_wheel_roster_bound_exact_and_duplicate_denial():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as wheel:
        wheel.writestr("adaptive_replay/sim_book_tape.py", b"legacy-loader")
        wheel.writestr("adaptive_replay/public_book_capture.py", b"legacy-auditor")
    assert exporter._wheel_roster(buffer.getvalue()) == {
        "adaptive_replay/sim_book_tape.py": hashlib.sha256(b"legacy-loader").hexdigest(),
        "adaptive_replay/public_book_capture.py": hashlib.sha256(b"legacy-auditor").hexdigest(),
    }
    with zipfile.ZipFile(buffer, "a") as wheel, pytest.warns(UserWarning):
        wheel.writestr("adaptive_replay/sim_book_tape.py", b"shadow-loader")
    with pytest.raises(ValueError, match="nonduplicated"):
        exporter._wheel_roster(buffer.getvalue())


def test_exporter_matches_loaded_source_roster_not_just_named_wheel_hash(tmp_path, monkeypatch):
    from types import SimpleNamespace

    private = tmp_path / "legacy-private"
    package = private / "Lib" / "site-packages" / "adaptive_replay"
    package.mkdir(parents=True)
    init = package / "__init__.py"
    init.write_bytes(b"legacy init")
    modules = {"adaptive_replay": SimpleNamespace(__file__=str(init))}
    roster = {"adaptive_replay/__init__.py": exporter.sha(init.read_bytes())}
    for key, name in exporter.SOURCE_MODULES.items():
        path = private / "Lib" / "site-packages" / (name.replace(".", "/") + ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"legacy {key}".encode())
        modules[name] = SimpleNamespace(__file__=str(path))
        if key in {"loader", "auditor"}:
            roster[name.replace(".", "/") + ".py"] = exporter.sha(path.read_bytes())
    monkeypatch.setattr(exporter.sys, "prefix", str(private))
    monkeypatch.setattr(exporter.importlib.util, "find_spec", lambda name: SimpleNamespace(origin=str(init)))
    monkeypatch.setattr(exporter.importlib, "import_module", lambda name: modules[name])
    _, sources = exporter._runtime_sources(roster)
    assert sources["kernel_models"]["path"] == "kairos_execution/simulation/models.py"
    assert all(not item["path"].startswith(str(private)) for item in sources.values())
    Path(modules["adaptive_replay.sim_book_tape"].__file__).write_bytes(b"shadowed loader")
    with pytest.raises(ValueError, match="do not match"):
        exporter._runtime_sources(roster)


def test_exporter_all_package_bytes_detect_added_shadow_source(tmp_path, monkeypatch):
    from types import SimpleNamespace

    private = tmp_path / "private"
    package = private / "adaptive_replay"
    package.mkdir(parents=True)
    init = package / "__init__.py"
    init.write_bytes(b"init")
    (package / "shadow.py").write_bytes(b"uncommitted addition")
    modules = {name: SimpleNamespace(__file__=str(init)) for name in exporter.SOURCE_MODULES.values()}
    modules["adaptive_replay"] = SimpleNamespace(__file__=str(init))
    monkeypatch.setattr(exporter.sys, "prefix", str(private))
    monkeypatch.setattr(exporter.importlib.util, "find_spec", lambda name: SimpleNamespace(origin=str(init)))
    monkeypatch.setattr(exporter.importlib, "import_module", lambda name: modules[name])
    with pytest.raises(ValueError, match="do not match"):
        exporter._runtime_sources({"adaptive_replay/__init__.py": exporter.sha(b"init")})
