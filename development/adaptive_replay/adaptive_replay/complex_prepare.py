"""Create-only OFFLINE preparation; deliberately no paid execution option.

This prepares exact inputs, cut roster, strategy candidates and prompt bytes.
It neither admits source authenticity nor initializes/changes a spend ledger.
Model execution still requires an independently accepted source/budget receipt
and a new explicit owner confirmation through the guarded dispatcher.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import stat
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .complex_frame import ContextAssessmentFrame
from .complex_protocol import EPISODES, READINESS, fixed_protocol, protocol_sha256, requirements, utc_ms
from .complex_replay import _frame_snapshot
from .complex_strategy import HISTORY_BARS, evaluate_complex
from .historical_bars import _payload_bytes, resolve_closed_history
from .historical_context import HistoricalArchive, canonical, digest, read_archive
from .historical_inputs import validate_replay_inputs
from .historical_pilot_preflight import _input_roots, _market_summary
from .historical_pilot_sim import installed_sources
from .inputs import UNIVERSE, load_window
from .runner import load_plan, utc_now, write_json

REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
OUTPUT_NAME = re.compile(r"^compact-context-preparation-[0-9]{8}-[a-z0-9-]+$")


def validate_paths(workspace_root: Path, output_root: Path) -> Path:
    if not workspace_root.is_absolute() or not output_root.is_absolute():
        raise ValueError("absolute workspace/output paths required")
    workspace = workspace_root.resolve(strict=True)
    runtime = workspace / "runtime"
    if not runtime.is_dir() or output_root.parent != runtime or not OUTPUT_NAME.fullmatch(output_root.name):
        raise ValueError("create-only specifically named direct runtime child required")
    for path in (*reversed(output_root.parents), output_root, workspace_root):
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            continue
        if path.is_symlink() or getattr(metadata, "st_file_attributes", 0) & REPARSE:
            raise ValueError("symlink/junction output paths are forbidden")
    if output_root.exists():
        raise FileExistsError("preparation receipts are immutable; never retry into an existing directory")
    if not (workspace / "kairos" / "development" / "adaptive_replay" / "plan.json").is_file():
        raise ValueError("Kairos dependency source plan required")
    return workspace


def prepare(
    workspace_root: Path,
    output_root: Path,
    *,
    archive_path: Path | None = None,
    expected_archive_sha256: str | None = None,
) -> dict:
    workspace = validate_paths(workspace_root, output_root)
    if (archive_path is None) != (expected_archive_sha256 is None):
        raise ValueError("historical archive path and exact checksum must be supplied together")
    archive = (
        HistoricalArchive((), ())
        if archive_path is None
        else read_archive(archive_path, expected_archive_sha256)
    )
    archive.validate()
    if any(c.proof_kind == "TEST_FIXTURE" for c in archive.coverage) or any(
        v.proof_kind == "TEST_FIXTURE" for v in archive.versions
    ):
        raise ValueError("production preparation cannot relabel fixture source evidence")
    source_plan_path = workspace / "kairos" / "development" / "adaptive_replay" / "plan.json"
    source_plan = load_plan(source_plan_path)
    before = installed_sources(source_plan, source_plan_path)
    protocol = fixed_protocol()
    protocol_sha = protocol_sha256()
    started = time.monotonic()
    deadline = started + protocol["max_wall_seconds"]
    actual_started = utc_now()
    captured_ms = time.time_ns() // 1_000_000
    output_root.mkdir(exist_ok=False)
    write_json(output_root / "protocol.json", protocol)
    write_json(
        output_root / "before.json",
        {"actual_started_utc": actual_started, "sources": before, "protocol_sha256": protocol_sha},
    )
    cells = []
    input_receipts = {}
    try:
        for eid, start, end, cuts, cache_kind in EPISODES:
            if time.monotonic() >= deadline:
                raise TimeoutError("bounded preparation deadline reached")
            bar_root, factor_root = _input_roots(workspace, cache_kind)
            window = {"id": eid, "start": start, "end_exclusive": end}
            inputs = load_window(bar_root, factor_root, window)
            validate_replay_inputs(inputs, fixture_only=False, deadline=deadline)
            market = _market_summary(inputs)
            input_receipts[eid] = {"market": market, "evidence": inputs.evidence}
            write_json(output_root / f"{eid}-inputs.json", input_receipts[eid])
            prefix_start = inputs.start_ms - HISTORY_BARS * 60_000
            for cut_text in cuts:
                cut = utc_ms(cut_text)
                for symbol in UNIVERSE:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("bounded preparation deadline reached")
                    prefix = tuple(c for c in inputs.bars[symbol] if prefix_start <= c.open_time_ms < cut)
                    decision = evaluate_complex(prefix, prefix_start_ms=prefix_start, cut_ms=cut)
                    rolling = prefix[-HISTORY_BARS:]
                    history = resolve_closed_history(
                        candles=rolling,
                        expected_payload_sha256=hashlib.sha256(_payload_bytes(rolling)).hexdigest(),
                        expected_symbol=symbol,
                        expected_timeframe="1m",
                        expected_count=HISTORY_BARS,
                        expected_first_open_ms=cut - HISTORY_BARS * 60_000,
                        expected_last_closed_ms=cut - 1,
                        cutoff_ms=cut,
                        provenance="HISTORICAL_ARCHIVE",
                        captured_at_ms=captured_ms,
                        source_artifact_sha256=market[symbol]["bar_rows_sha256"],
                    )
                    frame = ContextAssessmentFrame(history, archive, requirements(), cut, protocol_sha)
                    snapshot = _frame_snapshot(frame)
                    prompt = frame.prompt_payload()
                    label = f"{eid}-{cut}-{symbol}"
                    write_json(output_root / f"{label}-prompt.json", prompt)
                    cell = {
                        "episode": eid,
                        "slot_id": f"{eid}|{cut_text}|{symbol}",
                        "cut_ms": cut,
                        "symbol": symbol,
                        "technical": asdict(decision),
                        "frame_id": snapshot["frame_id"],
                        "prompt_sha256": snapshot["prompt_sha256"],
                        "prompt_filename": f"{label}-prompt.json",
                        "prompt_canonical_utf8_bytes": len(canonical(prompt).encode()),
                        "history": {k: v for k, v in asdict(history).items() if k != "candles"},
                        "archive_sha256": archive.sha256,
                        "required_sources_ready": snapshot["sources_ready"],
                        "source_authenticity_admitted": False,
                        "call_status": "NOT_CALLED",
                        "no_call_reason": "REQUIRED_SOURCE_UNAVAILABLE"
                        if not snapshot["sources_ready"]
                        else "OWNER_CONFIRMATION_AND_SOURCE_BUDGET_ADMISSION_PENDING",
                        "model_result": None,
                        "model_arm_economics": None,
                        "provider_calls": 0,
                        "provider_cost_usd": 0,
                    }
                    cells.append(cell)
                    print(
                        f"phase=prepared_cell episode={eid} symbol={symbol} "
                        f"cut={cut_text} state={decision.state}",
                        flush=True,
                    )
            if load_window(bar_root, factor_root, window).evidence != inputs.evidence:
                raise ValueError("source archive or normalized market rows changed during preparation")
        after = installed_sources(load_plan(source_plan_path), source_plan_path)
        if before != after or protocol_sha != protocol_sha256():
            raise ValueError("source modules/locks/native identities or fixed protocol changed")
        if archive_path is not None and read_archive(archive_path, expected_archive_sha256) != archive:
            raise ValueError("historical source archive changed during preparation")
        if time.monotonic() >= deadline or len(cells) != 20 or len({c["slot_id"] for c in cells}) != 20:
            raise ValueError("complete bounded twenty-cell roster required")
        write_json(output_root / "cells.json", cells)
        write_json(
            output_root / "after.json",
            {"actual_finished_utc": utc_now(), "sources": after, "source_receipt_unchanged": before == after},
        )
        result = {
            "schema": "kairos.development.compact-context-preparation.v1",
            "state": "ENGINEERING_PREPARED_MODEL_EXECUTION_NOT_ADMITTED",
            "protocol_sha256": protocol_sha,
            "actual_started_utc": actual_started,
            "actual_finished_utc": utc_now(),
            "elapsed_seconds": time.monotonic() - started,
            "scheduled_cells": len(cells),
            "technical_states": dict(Counter(c["technical"]["state"] for c in cells)),
            "cells_sha256": digest(cells),
            "required_sources_ready_cells": sum(c["required_sources_ready"] for c in cells),
            "source_authenticity_admitted": False,
            "shared_budget_identity_admitted": False,
            "fresh_owner_confirmation_received": False,
            "model_execution_admitted": False,
            "paid_run_executed": False,
            "provider_calls": 0,
            "provider_cost_usd": 0,
            "budget_created_or_reset": False,
            "economic_replay_executed": False,
            "source_receipt_unchanged": before == after,
            "unevaluated_slots_are_not_quiet": True,
            "scope": protocol["scope"],
            "historical_receive_clock_proven": False,
            "training_contamination_excluded": False,
            "blind_campaign_credit_days": 0,
            **READINESS,
        }
        write_json(output_root / "result.json", result)
        return result
    except BaseException as error:
        write_json(
            output_root / "failure.json",
            {
                "state": "FAILED_CLOSED",
                "error_type": type(error).__name__,
                "partial_cells": len(cells),
                "elapsed_seconds": time.monotonic() - started,
                "provider_calls": 0,
                "economic_replay_executed": False,
                "partial_receipts_retained": True,
                **READINESS,
            },
        )
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--expected-archive-sha256")
    args = parser.parse_args(argv)
    try:
        result = prepare(
            args.workspace_root,
            args.output_root,
            archive_path=args.archive,
            expected_archive_sha256=args.expected_archive_sha256,
        )
        print(f"state={result['state']} cells={result['scheduled_cells']} provider_calls=0")
    except (OSError, ValueError, TypeError, TimeoutError) as error:
        print(f"state=FAILED_CLOSED error_type={type(error).__name__} provider_calls=0")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
