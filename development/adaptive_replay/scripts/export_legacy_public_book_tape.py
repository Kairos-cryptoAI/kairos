"""Run ONLY with the preserved private B Python -I; no current bridge import.

Read-only source/capture inspection, followed by one create-only export outside
the environment and original capture. Independently retain stdout commitments.
This is not publisher authentication, historical availability or source admission.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import platform
import re
import stat
import sys
import zipfile
from pathlib import Path

SCHEMA = "kairos.development.public-book-transfer.v1"
MAX_BYTES = 32 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
LIMITATIONS = (
    "LEGACY_AUDITOR_RESULT_TRANSFERRED_NOT_CURRENT_ORIGINAL_AUDIT",
    "EXTERNAL_EXPORT_COMMITMENT_NOT_PUBLISHER_AUTHENTICATION",
    "ORIGINAL_EVENT_RECEIVE_PERSIST_CLOCKS_NEVER_RETIMED",
    "NO_HISTORICAL_AVAILABILITY_OR_FULL_TICK_COVERAGE",
    "NO_NEWS_MACRO_BAR_HYPOTHESIS_SOURCE_ADMISSION",
    "LATER_CONTEXT_OR_MODEL_COMPLETION_CANNOT_REFRESH_OLD_QUOTES",
    "EXACT_NATIVE_CREATION_CUT_STILL_REQUIRES_ALREADY_AVAILABLE_EVIDENCE",
    "NO_RISK_TRADING_READINESS_ALPHA_OR_QUALIFIED_ECONOMICS",
)
SOURCE_MODULES = {
    "loader": "adaptive_replay.sim_book_tape",
    "auditor": "adaptive_replay.public_book_capture",
    "kernel_bridge": "kairos_execution.simulation.bridge",
    "kernel_models": "kairos_execution.simulation.models",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _expected(value):
    if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise ValueError("independently retained full SHA256 required")
    return value


def _safe(path, *, directory=False):
    path = Path(path).absolute()
    if ".." in path.parts:
        raise ValueError("parent traversal prohibited")
    for item in (*reversed(path.parents), path):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("symlink/reparse paths prohibited")
        if item != path or directory:
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("regular directory required")
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("unaliased regular file required")
    return path


def _read(path, maximum):
    path = _safe(path)
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > maximum or before.st_nlink != 1:
            raise ValueError("file exceeds bound or is aliased")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    current = _safe(path).stat()

    def identity(value):
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_nlink

    if (
        identity(before) != identity(after)
        or identity(after) != identity(current)
        or not 0 < len(raw) <= maximum
    ):
        raise ValueError("file changed during bounded immutable snapshot")
    return raw


def build_document(*, receipt_bytes, legacy_audit, tape, producer):
    """Pure serialization of legacy DTOs; no importer, normalization or reseal."""
    if type(receipt_bytes) is not bytes or not 0 < len(receipt_bytes) <= 1024 * 1024:
        raise ValueError("bounded exact receipt bytes required")
    if not 1 <= len(tape.frames) <= 6000:
        raise ValueError("bounded complete legacy frame roster required")
    document = {
        "schema": SCHEMA,
        "producer": producer,
        "receipt_utf8": receipt_bytes.decode("utf-8"),
        "legacy_audit": legacy_audit,
        "tape": {
            "receipt_sha256": tape.receipt_sha256,
            "source_sha256": tape.source_sha256,
            "tape_id": tape.tape_id,
            "epoch": tape.epoch,
            "quote_source_id": tape.quote_source_id,
            "sha256": tape.sha256,
            "frames": [
                {
                    "frame_utf8": item.frame.canonical_bytes().decode("utf-8"),
                    "frame_sha256": item.frame.fingerprint(),
                    "receipt_sha256": item.receipt_sha256,
                    "native_frame_sha256": item.native_frame_sha256,
                    "raw_record_sha256": item.raw_record_sha256,
                    "segment_ordinal": item.segment_ordinal,
                    "segment_sequence": item.segment_sequence,
                    "mapping_sha256": item.mapping_sha256,
                }
                for item in tape.frames
            ],
        },
        "limitations": list(LIMITATIONS),
    }
    raw = canonical(document).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("export exceeds immutable transfer bound")
    return raw


def _wheel_roster(wheel_bytes):
    # No extraction. Reject duplicates/oversized expansion and unsafe members.
    import io

    with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as wheel:
        infos = wheel.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)) or len(names) > 4096 or sum(i.file_size for i in infos) > MAX_BYTES:
            raise ValueError("bounded nonduplicated wheel roster required")
        roster = {}
        for item in infos:
            name = item.filename
            if ".." in name.split("/") or name.startswith("/") or "\\" in name:
                raise ValueError("unsafe wheel member")
            if name.startswith("adaptive_replay/") and name.endswith(".py"):
                if item.file_size > MAX_SOURCE_BYTES or len(roster) >= 512:
                    raise ValueError("adaptive source bounds exceeded")
                roster[name] = sha(wheel.read(item))
    if (
        "adaptive_replay/sim_book_tape.py" not in roster
        or "adaptive_replay/public_book_capture.py" not in roster
    ):
        raise ValueError("named wheel lacks legacy capture loader/auditor")
    return roster


def _runtime_sources(wheel_roster):
    # Locate and verify the adaptive package before executing its initializer or
    # reader/auditor. Imported module paths are checked again below.
    spec = importlib.util.find_spec("adaptive_replay")
    if spec is None or spec.origin is None:
        raise ValueError("ordinary installed legacy package required")
    package_root = _safe(Path(spec.origin).parent, directory=True)
    private_root = _safe(Path(sys.prefix), directory=True)
    if not package_root.is_relative_to(private_root):
        raise ValueError("loaded adaptive package is not inside the private legacy environment")
    files = sorted(package_root.rglob("*.py"))
    if not 1 <= len(files) <= 512:
        raise ValueError("bounded loaded adaptive source roster required")
    actual = {
        "adaptive_replay/" + path.relative_to(package_root).as_posix(): sha(_read(path, MAX_SOURCE_BYTES))
        for path in files
    }
    if actual != wheel_roster:
        raise ValueError("loaded adaptive source bytes do not match the named committed B wheel")
    modules = {key: importlib.import_module(name) for key, name in SOURCE_MODULES.items()}
    package = importlib.import_module("adaptive_replay")
    if _safe(Path(package.__file__)) != _safe(Path(spec.origin)):
        raise ValueError("imported adaptive package differs from its verified wheel location")
    sources = {}
    for key, module in modules.items():
        source = _safe(Path(module.__file__))
        if source.suffix != ".py" or not source.is_relative_to(private_root):
            raise ValueError("actual imported source must be .py inside the private environment")
        logical = SOURCE_MODULES[key].replace(".", "/") + ".py"
        sources[key] = {"path": logical, "sha256": sha(_read(source, MAX_SOURCE_BYTES))}
        if key in ("loader", "auditor") and sources[key]["sha256"] != wheel_roster[logical]:
            raise ValueError("imported reader/auditor differs from the named wheel member")
    return modules, sources


def export(args):
    if not sys.flags.isolated or sys.prefix == sys.base_prefix:
        raise ValueError("preserved private legacy Python -I is mandatory")
    for name in (
        "expected_wheel_sha256",
        "expected_script_sha256",
        "expected_implementation_sha256",
        "expected_receipt_sha256",
    ):
        _expected(getattr(args, name))
    script_bytes = _read(Path(__file__), MAX_SOURCE_BYTES)
    wheel_bytes = _read(args.legacy_wheel, MAX_BYTES)
    if sha(script_bytes) != args.expected_script_sha256 or sha(wheel_bytes) != args.expected_wheel_sha256:
        raise ValueError("script/wheel bytes differ from independent commitments")
    roster = _wheel_roster(wheel_bytes)
    modules, sources = _runtime_sources(roster)
    journal = importlib.import_module("adaptive_replay.hypothesis_journal")
    implementation_utf8 = journal.implementation_binding()
    if (
        type(implementation_utf8) is not str
        or len(implementation_utf8.encode("utf-8")) > 65_536
        or sha(implementation_utf8.encode("utf-8")) != args.expected_implementation_sha256
    ):
        raise ValueError("actual B implementation differs from original bundle seal commitment")
    capture = _safe(args.capture_directory, directory=True)
    receipt_path = capture / "receipt.json"
    receipt_bytes = _read(receipt_path, 1024 * 1024)
    if sha(receipt_bytes) != args.expected_receipt_sha256:
        raise ValueError("receipt bytes differ from independent original commitment")
    audit = modules["auditor"].audit_public_capture(
        capture, expected_receipt_sha256=args.expected_receipt_sha256
    )
    if audit.get("state") != "PASS_OBSERVED_SOURCE_CONSISTENCY_ONLY":
        raise ValueError("legacy original auditor did not return observed-consistency PASS")
    tape = modules["loader"].load_public_book_tape(
        capture, expected_receipt_sha256=args.expected_receipt_sha256
    )
    # Recheck code and exact original receipt after the legacy audit/mapping.
    _, sources_after = _runtime_sources(roster)
    if (
        sources_after != sources
        or journal.implementation_binding() != implementation_utf8
        or _read(receipt_path, 1024 * 1024) != receipt_bytes
        or _read(Path(__file__), MAX_SOURCE_BYTES) != script_bytes
    ):
        raise ValueError("legacy source/script/receipt changed during export")
    producer = {
        "wheel_sha256": args.expected_wheel_sha256,
        "exporter_script_sha256": args.expected_script_sha256,
        "implementation_utf8": implementation_utf8,
        "implementation_sha256": args.expected_implementation_sha256,
        "sources": sources,
        "python_version": platform.python_version(),
        "isolated_private_environment": True,
    }
    raw = build_document(receipt_bytes=receipt_bytes, legacy_audit=audit, tape=tape, producer=producer)
    output = Path(args.output).absolute()
    if ".." in output.parts:
        raise ValueError("parent traversal prohibited")
    parent = _safe(output.parent, directory=True)
    if (
        output.is_relative_to(capture)
        or output.is_relative_to(Path(sys.prefix).absolute())
        or output.suffix != ".json"
    ):
        raise ValueError("dedicated JSON output must be outside originals and private environment")
    if output.name in ("receipt.json", "received.raw.jsonl"):
        raise ValueError("original artifact filenames prohibited")
    # Parent recheck before exclusive create; never overwrite or delete failures.
    if _safe(parent, directory=True) != parent:
        raise ValueError("output ancestry changed")
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if _read(output, MAX_BYTES) != raw:
        raise ValueError("created export failed exact-byte verification; preserved for inspection")
    return {
        "state": "EXPORTED_LEGACY_OBSERVED_CONSISTENCY_ONLY",
        "export_sha256": sha(raw),
        "legacy_wheel_sha256": args.expected_wheel_sha256,
        "exporter_script_sha256": args.expected_script_sha256,
        "legacy_implementation_sha256": args.expected_implementation_sha256,
        "receipt_sha256": args.expected_receipt_sha256,
        "producer_sources": sources,
        "tape_sha256": tape.sha256,
        "frames": len(tape.frames),
        "risk_authority": "NONE",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-wheel", type=Path, required=True)
    parser.add_argument("--capture-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    for name in ("wheel", "script", "implementation", "receipt"):
        parser.add_argument(f"--expected-{name}-sha256", required=True)
    args = parser.parse_args()
    print(canonical(export(args)))


if __name__ == "__main__":
    main()
