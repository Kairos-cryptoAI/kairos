"""Opt-in public-source liveness diagnostic under retained real-bar CPU load.

This is not another strategy/campaign or a model replay. Original historical
bar pages are hash-checked and used only as computation load. Missing context
is UNKNOWN, not fabricated news/Macro. No model, repository or venue is opened.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4

from adaptive_replay.catalyst_policy_v1 import CatalystCell, CatalystPolicy
from adaptive_replay.public_book_capture import CaptureOwner
from adaptive_replay.research_profile_v1 import PriceCell, ResearchProfile

from .current_capture import _parse_candle_row
from .current_chain import CurrentCatalystChain
from .current_runner import ARM_IDS, _fold_worker, _run_cpu, _run_fold, write_create_only
from .current_tape import SYMBOLS, ContinuousNativeTape, run_capture
from .current_verify import PUBLIC_BOOK_ROOT, ROOT


def retained_cells(run: Path):
    result_path = run / "current-chain-result.json"
    result = json.loads(result_path.read_bytes())
    cut = result["scheduled_cut_ms"]
    rows, hashes = {symbol: {} for symbol in SYMBOLS}, {}
    receipts = sorted(run.glob("current-public-capture-*/bars-*.receipt.json"))
    if len(receipts) != 15:
        raise ValueError("EXACT_RETAINED_REAL_HISTORY_PAGE_ROSTER_REQUIRED")
    total = 0
    for path in receipts:
        receipt = json.loads(path.read_bytes())
        raw_path = path.parent / receipt["raw_file"]
        if raw_path.parent != path.parent or raw_path.suffix != ".raw":
            raise ValueError("RETAINED_BAR_PAGE_PATH_CONFLICT")
        if raw_path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("BOUNDED_REAL_BAR_PAGE_REQUIRED")
        body = raw_path.read_bytes()
        total += len(body)
        if total > 32 * 1024 * 1024 or hashlib.sha256(body).hexdigest() != receipt["raw_sha256"]:
            raise ValueError("RETAINED_REAL_BAR_HASH_CONFLICT")
        symbol = receipt["symbol"]
        if symbol not in rows or receipt["cut_ms"] != cut or receipt["source_id"] != "binance_um_klines_rest":
            raise ValueError("RETAINED_REAL_BAR_SOURCE_CONFLICT")
        decoded = json.loads(body)
        if len(decoded) != receipt["row_count"]:
            raise ValueError("RETAINED_REAL_BAR_COUNT_CONFLICT")
        hashes[raw_path.relative_to(run).as_posix()] = receipt["raw_sha256"]
        for row in decoded:
            candle = _parse_candle_row(symbol, row, expected_open=row[0])
            if candle.open_time_ms in rows[symbol]:
                raise ValueError("RETAINED_REAL_BAR_DUPLICATE")
            rows[symbol][candle.open_time_ms] = candle
    policy = CatalystPolicy(
        ResearchProfile(
            declared_ms=result["capture_window_ms"][0],
            start_ms=cut,
            end_ms=cut + 300_000,
            source_set_sha256=result["source_set_sha256"],
            model_config_sha256=result["model_config_sha256"],
            quote_source_id="binance_um_rest_depth_snapshot",
            required_sources=(
                ("MACRO", "current_macro_allocation"),
                ("MARKET", "binance_um_klines_rest"),
                ("NEWS", "cointelegraph_rss"),
            ),
            evidence_kind="CALLER_ATTESTED_POINT_IN_TIME",
        )
    )
    cells = tuple(
        CatalystCell(
            PriceCell(
                cut, cut, symbol, tuple(rows[symbol][key] for key in sorted(rows[symbol])), (), "UNKNOWN"
            ),
            "UNKNOWN",
            (),
            (),
        )
        for symbol in sorted(SYMBOLS)
    )
    return policy, cells, hashes


async def execute(recorded_run: Path):
    source_files = ("current_liveness.py", "current_runner.py", "current_tape.py")
    executed_sources = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in source_files
    }
    policy, cells, hashes = await _run_cpu(retained_cells, recorded_run)
    PUBLIC_BOOK_ROOT.mkdir(exist_ok=True)
    output = PUBLIC_BOOK_ROOT / ("retained-real-load-" + uuid4().hex)
    output.mkdir()
    tape = ContinuousNativeTape(
        output / "original-native", "current-load-" + uuid4().hex, maximum_seconds=240
    )
    ready, stop, tick_stop = asyncio.Event(), asyncio.Event(), asyncio.Event()
    source = asyncio.create_task(run_capture(tape, ready, stop))
    intervals = []

    async def heartbeat():
        last = time.monotonic()
        while not tick_stop.is_set():
            await asyncio.sleep(0.025)
            now = time.monotonic()
            intervals.append(now - last)
            last = now

    pulse = asyncio.create_task(heartbeat())
    completed, started = 0, time.time_ns() // 1_000_000
    try:
        await asyncio.wait_for(ready.wait(), 20)
        async with _fold_worker():
            chain = await _run_fold(CurrentCatalystChain.start, policy)
            chain, prepared = await _run_fold(chain.prepare, cells)
            for symbol in sorted(SYMBOLS):
                for arm in ARM_IDS:
                    if source.done():
                        raise ValueError("ORIGINAL_SOURCE_ENDED_DURING_RETAINED_CPU_LOAD")
                    chain, _ = await _run_fold(
                        chain.resolve,
                        prepared,
                        symbol=symbol,
                        arm_id=arm,
                        issued_ms=policy.session.start_ms + 1,
                        runs=(),
                        shared_gate="BLOCKED",
                        current_prepared=prepared,
                    )
                    completed += 1
        stop.set()
        source_receipt = await asyncio.wait_for(asyncio.shield(source), 20)
        result = {
            "schema": "kairos.current-retained-real-load-liveness.v1",
            "state": "PASS_SOURCE_SCHEDULING_ONLY"
            if source_receipt["state"] == "CAPTURED"
            else "FAILED_CLOSED",
            "retained_run": str(recorded_run),
            "executed_adapter_file_sha256s": executed_sources,
            "retained_real_page_sha256s": hashes,
            "retained_bar_count": sum(len(cell.price.rows) for cell in cells),
            "sequential_native_folds": completed,
            "actual_started_ms": started,
            "actual_completed_ms": time.time_ns() // 1_000_000,
            "maximum_event_loop_interval_ms": round(max(intervals, default=0) * 1_000, 3),
            "source_receipt_sha256": source_receipt["receipt_sha256"],
            "real_native_frame_count": source_receipt["frame_count"],
            "new_paid_calls": 0,
            "new_database_or_orders": False,
            "context_missing_is_unknown": True,
            "model_or_trade_verification_credit": False,
            "readiness_promotion": False,
        }
        write_create_only(output / "verification.json", result)
        print(json.dumps({"state": result["state"], "receipt_directory": str(output)}), flush=True)
        return 0 if result["state"] == "PASS_SOURCE_SCHEDULING_ONLY" else 1
    finally:
        stop.set()
        if not source.done():
            await asyncio.wait_for(asyncio.shield(source), 20)
        tick_stop.set()
        await pulse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--recorded-run", type=Path, required=True)
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "new_paid_calls": 0,
                    "new_database_or_orders": False,
                    "model_or_trade_verification_credit": False,
                }
            )
        )
        return 0
    with CaptureOwner(ROOT):
        return asyncio.run(execute(args.recorded_run))


if __name__ == "__main__":
    raise SystemExit(main())
