"""Opt-in, bounded capture of fresh public Binance UM inputs into native SIM.

This is deliberately a small operational adapter around the pinned public
collector, the existing book recorder, and the simulator repository.  It does
not run a strategy, model, risk decision, or venue adapter.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

SYMBOLS = ("BNBUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
MAX_SECONDS = 300
MAX_BYTES = 16 * 1024 * 1024
BOOK_MAX_AGE_MS = 5_000
BAR_MAX_AGE_MS = 90_000
PRODUCER_STOP_TIMEOUT_S = 2.0
PINNED_COMMITS = {
    "kairos-quant-scouts": "7db2712dc9995e7adbb0947104572b88f45368a0",
    "kairos-persistence": "ea0c73395352f71da196270fe16659f1f0298a52",
    "kairos-core": "6937eb4773fc00afaf5ba4e020b28b689f48e377",
}
_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*\Z")


class CaptureRefused(RuntimeError):
    """A bounded capture cannot prove the required source coverage."""


def plan() -> dict[str, object]:
    return {
        "mode": "PLAN_ONLY",
        "symbols": list(SYMBOLS),
        "maximum_seconds": MAX_SECONDS,
        "maximum_accounted_ingress_bytes": MAX_BYTES,
        "byte_cap_scope": (
            "admitted book payloads, market WebSocket text, canonical bars; excludes REST/transport overhead"
        ),
        "market_data": "public Binance USD-M futures only",
        "database_profile": "isolated PostgreSQL SIMULATOR only",
        "database_name_pattern": "kairos_sim_native_capture_<run-uuid4-hex>",
        "book_frame_contract": "sim-book-frame.v1 (payload hash retained; raw book text not retained)",
        "qualification_scope": "sealed capture only; not full-system, native-fill, or model qualification",
        "models": "not called",
        "venue_orders": "not available",
    }


def require_uuid4(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise ValueError("RUN_ID_MUST_BE_UUID4") from None
    if parsed.version != 4 or str(parsed) != value.lower():
        raise ValueError("RUN_ID_MUST_BE_UUID4")
    return str(parsed)


def read_database_url(*, env_name: str | None, file_path: str | None) -> str:
    if (env_name is None) == (file_path is None):
        raise ValueError("EXACTLY_ONE_DATABASE_URL_SOURCE_REQUIRED")
    if env_name is not None:
        if not _ENV_NAME.fullmatch(env_name):
            raise ValueError("DATABASE_URL_ENV_NAME_INVALID")
        value = os.environ.get(env_name)
    else:
        try:
            path = Path(file_path).expanduser()
            if not path.is_file() or path.stat().st_size > 16_384:
                raise ValueError
            value = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError, ValueError):
            raise ValueError("DATABASE_URL_FILE_UNAVAILABLE") from None
    if not value or "\n" in value or "\r" in value:
        raise ValueError("DATABASE_URL_UNAVAILABLE")
    return value


def verify_pinned_sources() -> dict[str, str]:
    """Reject editable or unpinned runtime distributions without printing paths."""

    verified: dict[str, str] = {}
    for name, expected in PINNED_COMMITS.items():
        try:
            dist = importlib.metadata.distribution(name)
            raw = dist.read_text("direct_url.json")
            if not raw:
                raise ValueError
            direct = json.loads(raw)
            vcs = direct.get("vcs_info", {})
            if direct.get("dir_info", {}).get("editable") is True:
                raise ValueError
            actual = vcs.get("commit_id")
            if actual != expected:
                raise ValueError
        except Exception:
            raise CaptureRefused("PINNED_RUNTIME_SOURCE_MISMATCH") from None
        verified[name] = expected
    return verified


async def persist_pending_books(
    recorder: Any,
    repository: Any,
    *,
    latest_persisted_book_received_at_ms: dict[str, int] | None = None,
) -> int:
    """Persist each queue head before acknowledging it; barriers are durable then fatal."""

    persisted = 0
    for frame in recorder.pending_frames():
        await repository.record_book_frame(frame)
        recorder.acknowledge(frame.frame_sha256)
        persisted += 1
        if frame.continuity == "ADMITTED" and latest_persisted_book_received_at_ms is not None:
            latest_persisted_book_received_at_ms[frame.symbol] = frame.received_at_ms
        if frame.continuity != "ADMITTED":
            raise CaptureRefused("PUBLIC_BOOK_SOURCE_BARRIER")
    return persisted


async def persist_pending_bars(
    collector: Any,
    repository: Any,
    tape_id: str,
    *,
    started_at_ms: int,
    now_ms: int,
    captured_symbols: set[str],
    latest_bar_close_time_ms: dict[str, int],
    add_evidence_bytes,
) -> int:
    """Append only post-start closed bars and acknowledge after durable writes."""

    count = 0
    for symbol in SYMBOLS:
        pending = collector.pending_closed_klines(symbol.lower())
        acknowledged = 0
        for candle in pending:
            if candle.close_time_ms <= started_at_ms:
                # Startup REST reconciliation supplies history; it is intentionally not
                # represented as a fresh capture input for this bounded run.
                acknowledged += 1
                continue
            if candle.close_time_ms > now_ms or now_ms - candle.close_time_ms > BAR_MAX_AGE_MS:
                raise CaptureRefused("CLOSED_BAR_STALE_OR_FUTURE")
            if not collector.is_kline_stream_safe(symbol.lower()):
                raise CaptureRefused("CLOSED_BAR_STREAM_GAP")
            from kairos_core.contracts import ClosedBarEventV1

            bar = ClosedBarEventV1(
                source="kairos-quant-scouts",
                symbol=candle.symbol.upper(),
                timeframe="1m",
                open_time_ms=candle.open_time_ms,
                close_time_ms=candle.close_time_ms,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                base_volume=candle.base_volume,
                quote_volume=candle.quote_volume,
                taker_buy_base_volume=candle.taker_buy_base_volume,
                taker_buy_quote_volume=candle.taker_buy_quote_volume,
            )
            payload_size = len(bar.model_dump_json().encode("utf-8"))
            add_evidence_bytes(payload_size)
            await repository.record_closed_bar(tape_id, bar)
            captured_symbols.add(symbol)
            latest_bar_close_time_ms[symbol] = candle.close_time_ms
            acknowledged += 1
            count += 1
        # If a write failed, the exception above prevents acknowledging any of this
        # symbol's queue; a retry is safe because repository inserts are idempotent.
        collector.acknowledge_closed_klines(symbol.lower(), acknowledged)
    return count


def require_complete_coverage(
    *,
    expected_symbols: tuple[str, ...],
    captured_bar_symbols: set[str],
    latest_bar_close_time_ms: dict[str, int],
    latest_book_received_at_ms: dict[str, int],
    now_ms: int,
) -> None:
    if captured_bar_symbols != set(expected_symbols):
        raise CaptureRefused("FIVE_SYMBOL_FRESH_BAR_COVERAGE_REQUIRED")
    if set(latest_bar_close_time_ms) != set(expected_symbols) or any(
        close_time > now_ms or now_ms - close_time > BAR_MAX_AGE_MS
        for close_time in latest_bar_close_time_ms.values()
    ):
        raise CaptureRefused("FRESH_CLOSED_BAR_COVERAGE_REQUIRED")
    if set(latest_book_received_at_ms) != set(expected_symbols):
        raise CaptureRefused("FIVE_SYMBOL_ADMITTED_BOOK_COVERAGE_REQUIRED")
    if any(
        received > now_ms or now_ms - received > BOOK_MAX_AGE_MS
        for received in latest_book_received_at_ms.values()
    ):
        raise CaptureRefused("FRESH_BOOK_COVERAGE_REQUIRED")


def make_bounded_book_recorder(*, byte_limit: int, recorder_base=None, **kwargs):
    """Create the existing recorder with a hard source-byte ceiling at ingress."""

    if recorder_base is None:
        from kairos_quant.simulation_book import SimulationBookTapeRecorder

        recorder_base = SimulationBookTapeRecorder

    class BoundedRecorder(recorder_base):
        def __init__(self, *, byte_limit: int, **recorder_kwargs):
            super().__init__(**recorder_kwargs)
            self.byte_limit = byte_limit
            self.evidence_bytes = 0
            self.planned_stop_requested = False
            self.planned_stop_barrier_seen = False

        def request_planned_stop(self) -> None:
            if self.status.blocked_reason:
                raise CaptureRefused("PUBLIC_BOOK_RECORDER_BLOCKED")
            self.planned_stop_requested = True

        def record_source_barrier(self, *, continuity: str, at_ms: int, reason: str):
            # The pinned collector currently translates task cancellation into a
            # reconnect barrier in its public-stream finally block. At the explicit
            # sealed-window boundary only, suppress that expected close marker; any
            # unplanned reconnect/gap remains an ordinary durable barrier.
            if self.planned_stop_requested and reason == "PUBLIC_STREAM_RECONNECT":
                self.planned_stop_barrier_seen = True
                return ()
            return super().record_source_barrier(
                continuity=continuity,
                at_ms=at_ms,
                reason=reason,
            )

        def add_evidence_bytes(self, size: int) -> None:
            if size < 0 or self.evidence_bytes + size > self.byte_limit:
                raise CaptureRefused("EVIDENCE_BYTE_LIMIT_REACHED")
            self.evidence_bytes += size

        def capture_depth(self, **capture_kwargs):
            raw_payload = capture_kwargs.get("raw_payload")
            try:
                size = len(raw_payload.encode("utf-8"))
            except (AttributeError, UnicodeError):
                raise CaptureRefused("PUBLIC_PAYLOAD_NOT_UTF8") from None
            if self.evidence_bytes + size > self.byte_limit:
                # A durable terminal marker prevents a partial book capture from
                # being mistaken for a complete tape.
                self.record_source_barrier(
                    continuity="UNKNOWN",
                    at_ms=capture_kwargs.get("received_at_ms"),
                    reason="CAPTURE_BYTE_LIMIT",
                )
                raise CaptureRefused("EVIDENCE_BYTE_LIMIT_REACHED")
            frame = super().capture_depth(**capture_kwargs)
            self.evidence_bytes += size
            return frame

    return BoundedRecorder(byte_limit=byte_limit, **kwargs)


def make_bounded_collector(*, recorder: Any, byte_limit: int, **kwargs):
    """Count all admitted market WebSocket text while reusing the pinned collector."""

    from kairos_quant.collectors.binance_ws import BinanceFuturesCollector

    class BoundedCollector(BinanceFuturesCollector):
        def _on_message(self, message, *, route=None, raw_payload=None, received_at_ms=None):
            if route == "market" and raw_payload is not None:
                try:
                    recorder.add_evidence_bytes(len(raw_payload.encode("utf-8")))
                except UnicodeError:
                    raise CaptureRefused("PUBLIC_PAYLOAD_NOT_UTF8") from None
            return super()._on_message(
                message,
                route=route,
                raw_payload=raw_payload,
                received_at_ms=received_at_ms,
            )

    return BoundedCollector(**kwargs)


async def stop_and_join_producers(
    *, recorder: Any, collector_task: asyncio.Task, reconciliation_task: asyncio.Task
) -> None:
    if collector_task.done() or reconciliation_task.done():
        raise CaptureRefused("PUBLIC_PRODUCER_STOPPED_BEFORE_PLANNED_BOUNDARY")
    recorder.request_planned_stop()
    collector_task.cancel()
    reconciliation_task.cancel()
    try:
        async with asyncio.timeout(PRODUCER_STOP_TIMEOUT_S):
            results = await asyncio.gather(
                collector_task,
                reconciliation_task,
                return_exceptions=True,
            )
    except TimeoutError:
        raise CaptureRefused("PUBLIC_PRODUCERS_DID_NOT_STOP_WITHIN_BOUND") from None
    if not recorder.planned_stop_barrier_seen:
        raise CaptureRefused("PLANNED_PUBLIC_STREAM_CLOSE_NOT_CONFIRMED")
    if recorder.status.blocked_reason:
        raise CaptureRefused("PUBLIC_BOOK_RECORDER_BLOCKED")
    if isinstance(results[1], BaseException) and not isinstance(results[1], asyncio.CancelledError):
        raise CaptureRefused("PUBLIC_KLINE_RECONCILIATION_STOP_FAILED")


async def finalize_capture(
    *,
    collector: Any,
    recorder: Any,
    repository: Any,
    collector_task: asyncio.Task,
    reconciliation_task: asyncio.Task,
    tape_id: str,
    started_at_ms: int,
    captured_bar_symbols: set[str],
    latest_bar_close_time_ms: dict[str, int],
    latest_persisted_book_received_at_ms: dict[str, int],
) -> tuple[Any, int, int]:
    """Stop producers, drain their final queues, then verify and seal once."""

    if not all(collector.is_book_fresh(symbol.lower(), BOOK_MAX_AGE_MS / 1_000) for symbol in SYMBOLS):
        raise CaptureRefused("FRESH_BOOK_COVERAGE_REQUIRED")
    if not all(collector.is_kline_stream_safe(symbol.lower()) for symbol in SYMBOLS):
        raise CaptureRefused("CLOSED_BAR_STREAM_GAP")
    await stop_and_join_producers(
        recorder=recorder,
        collector_task=collector_task,
        reconciliation_task=reconciliation_task,
    )
    now_ms = int(time.time() * 1_000)
    bar_count = await persist_pending_bars(
        collector,
        repository,
        tape_id,
        started_at_ms=started_at_ms,
        now_ms=now_ms,
        captured_symbols=captured_bar_symbols,
        latest_bar_close_time_ms=latest_bar_close_time_ms,
        add_evidence_bytes=recorder.add_evidence_bytes,
    )
    book_count = await persist_pending_books(
        recorder,
        repository,
        latest_persisted_book_received_at_ms=latest_persisted_book_received_at_ms,
    )
    if recorder.status.blocked_reason:
        raise CaptureRefused("PUBLIC_BOOK_RECORDER_BLOCKED")
    require_complete_coverage(
        expected_symbols=SYMBOLS,
        captured_bar_symbols=captured_bar_symbols,
        latest_bar_close_time_ms=latest_bar_close_time_ms,
        latest_book_received_at_ms=latest_persisted_book_received_at_ms,
        now_ms=now_ms,
    )
    seal = await repository.seal_tape(tape_id, sealed_at_ms=now_ms, source="native-public-capture")
    if not await repository.verify_tape(tape_id):
        raise CaptureRefused("SEALED_TAPE_VERIFICATION_FAILED")
    return seal, bar_count, book_count


def _reserve_receipt(path: Path, document: dict[str, object]) -> int:
    payload = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(descriptor, payload)
        os.fsync(descriptor)
        return descriptor
    except OSError:
        raise CaptureRefused("RECEIPT_PATH_MUST_BE_NEW_AND_WRITABLE") from None


def _update_receipt(descriptor: int, document: dict[str, object]) -> None:
    payload = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.ftruncate(descriptor, 0)
    os.write(descriptor, payload)
    os.fsync(descriptor)


async def _execute_bounded(args: argparse.Namespace, *, cleanup_budget_s: float) -> dict[str, object]:
    run_id = require_uuid4(args.run_id)
    database_name = f"kairos_sim_native_capture_{run_id.replace('-', '')}"
    database_url = read_database_url(env_name=args.database_url_env, file_path=args.database_url_file)
    source_commits = verify_pinned_sources()
    source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receipt_path = Path(args.receipt).expanduser().resolve(strict=False)
    receipt: dict[str, object] = {
        "receipt_version": "native-public-sim-capture.v1",
        "run_id": run_id,
        "tape_id": run_id,
        "database_name": database_name,
        "source_sha256": source_sha256,
        "runtime_commits": source_commits,
        "symbols": list(SYMBOLS),
        "maximum_seconds": args.seconds,
        "maximum_accounted_ingress_bytes": MAX_BYTES,
        "byte_cap_scope": (
            "admitted book payloads, market WebSocket text, canonical bars; excludes REST/transport overhead"
        ),
        "book_frame_contract": "sim-book-frame.v1",
        "raw_book_text_retained": False,
        "book_source_evidence": "raw payload SHA-256 plus recorder clocks and normalized top-N levels",
        "qualification_scope": "sealed capture only; not full-system, native-fill, or model qualification",
        "paper_qualification_eligible": False,
        "trial15_eligible": False,
        "alpha_claim": False,
        "state": "RESERVED",
    }
    descriptor = _reserve_receipt(receipt_path, receipt)
    db = None
    collector_task: asyncio.Task | None = None
    reconciliation_task: asyncio.Task | None = None
    recorder = None
    repository = None
    try:
        from kairos_persistence import Database, MigrationProfile, PersistenceSettings
        from kairos_persistence.database_target import (
            connect_verified_database,
            require_database_target_url,
        )
        from kairos_persistence.simulation_repository import SimulationRepository

        require_database_target_url(database_url, database_name, local_only=True)
        db = Database(
            PersistenceSettings(
                _env_file=None,
                database_url=database_url,
                pool_min_size=1,
                pool_max_size=2,
                command_timeout_s=10,
            ),
            migration_profile=MigrationProfile.SIMULATOR,
        )
        await connect_verified_database(db, database_name, local_only=True)
        facts = await db.pool.fetchrow(
            "SELECT current_user AS role, current_setting('server_version_num')::integer AS version, "
            "(SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='public' "
            "AND c.relkind IN ('r','p','v','m','S')) AS objects, "
            "to_regclass('public.schema_migrations') IS NOT NULL AS has_migrations"
        )
        if (
            facts["role"] != "kairos"
            or not 160000 <= facts["version"] < 170000
            or facts["objects"] != 0
            or facts["has_migrations"]
        ):
            raise CaptureRefused("FRESH_DISPOSABLE_PG16_TARGET_REQUIRED")
        await db.migrate()
        await db.verify_schema()
        repository = SimulationRepository(db.pool)
        recorder = make_bounded_book_recorder(
            tape_id=run_id,
            symbols=SYMBOLS,
            source="kairos-quant-scouts",
            max_pending_frames=256,
            byte_limit=MAX_BYTES,
        )
        collector = make_bounded_collector(
            recorder=recorder,
            byte_limit=MAX_BYTES,
            symbols=[symbol.lower() for symbol in SYMBOLS],
            ws_base="wss://fstream.binance.com",
            rest_base="https://fapi.binance.com",
            reconnect_initial_s=1.0,
            reconnect_max_s=5.0,
            kline_finality_delay_s=5.0,
            kline_buffer_size=10,
            simulation_book_recorder=recorder,
        )
        started_at_ms = int(time.time() * 1_000)
        captured_bar_symbols: set[str] = set()
        latest_bar_close_time_ms: dict[str, int] = {}
        receipt["state"] = "CAPTURING"
        receipt["started_at_ms"] = started_at_ms
        _update_receipt(descriptor, receipt)
        collector_task = asyncio.create_task(collector.run(), name="native-public-sim-capture")
        reconciliation_task = asyncio.create_task(
            collector.run_kline_reconciliation_loop(5.0),
            name="native-public-sim-kline-reconciliation",
        )
        latest_persisted_book_received_at_ms: dict[str, int] = {}
        while True:
            now_ms = int(time.time() * 1_000)
            await persist_pending_bars(
                collector,
                repository,
                run_id,
                started_at_ms=started_at_ms,
                now_ms=now_ms,
                captured_symbols=captured_bar_symbols,
                latest_bar_close_time_ms=latest_bar_close_time_ms,
                add_evidence_bytes=recorder.add_evidence_bytes,
            )
            await persist_pending_books(
                recorder,
                repository,
                latest_persisted_book_received_at_ms=latest_persisted_book_received_at_ms,
            )
            if collector_task.done():
                raise CaptureRefused("PUBLIC_COLLECTOR_STOPPED_OR_BLOCKED")
            if reconciliation_task.done():
                raise CaptureRefused("PUBLIC_KLINE_RECONCILIATION_STOPPED")
            if recorder.status.blocked_reason:
                raise CaptureRefused("PUBLIC_BOOK_RECORDER_BLOCKED")
            if captured_bar_symbols == set(SYMBOLS):
                try:
                    require_complete_coverage(
                        expected_symbols=SYMBOLS,
                        captured_bar_symbols=captured_bar_symbols,
                        latest_bar_close_time_ms=latest_bar_close_time_ms,
                        latest_book_received_at_ms=latest_persisted_book_received_at_ms,
                        now_ms=now_ms,
                    )
                except CaptureRefused:
                    pass
                else:
                    books_are_fresh = all(
                        collector.is_book_fresh(symbol.lower(), BOOK_MAX_AGE_MS / 1_000) for symbol in SYMBOLS
                    )
                    if books_are_fresh:
                        seal, final_bar_count, final_book_count = await finalize_capture(
                            collector=collector,
                            recorder=recorder,
                            repository=repository,
                            collector_task=collector_task,
                            reconciliation_task=reconciliation_task,
                            tape_id=run_id,
                            started_at_ms=started_at_ms,
                            captured_bar_symbols=captured_bar_symbols,
                            latest_bar_close_time_ms=latest_bar_close_time_ms,
                            latest_persisted_book_received_at_ms=latest_persisted_book_received_at_ms,
                        )
                        receipt.update(
                            {
                                "state": "SEALED",
                                "sealed_at_ms": seal.sealed_at_ms,
                                "seal_sha256": seal.tape_sha256,
                                "bar_symbols": sorted(captured_bar_symbols),
                                "book_symbols": sorted(latest_persisted_book_received_at_ms),
                                "accounted_ingress_bytes": recorder.evidence_bytes,
                                "final_drain_bars": final_bar_count,
                                "final_drain_book_frames": final_book_count,
                            }
                        )
                        _update_receipt(descriptor, receipt)
                        return receipt
            await asyncio.sleep(0.05)
    except CaptureRefused as exc:
        receipt["state"] = "REFUSED"
        receipt["refusal"] = str(exc)
        _update_receipt(descriptor, receipt)
        raise
    except asyncio.CancelledError:
        receipt["state"] = "CANCELLED"
        receipt["refusal"] = "CAPTURE_CANCELLED_NO_SEAL"
        _update_receipt(descriptor, receipt)
        raise
    except Exception:
        receipt["state"] = "FAILED_REDACTED"
        receipt["refusal"] = "CAPTURE_FAILED_CHECK_LOCAL_LOGS_WITHOUT_SHARING_SECRETS"
        _update_receipt(descriptor, receipt)
        raise CaptureRefused("CAPTURE_FAILED_REDACTED") from None
    finally:
        try:
            async with asyncio.timeout(cleanup_budget_s):
                for task in (collector_task, reconciliation_task):
                    if task is not None and not task.done():
                        task.cancel()
                pending = [task for task in (collector_task, reconciliation_task) if task is not None]
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                if db is not None:
                    await db.close()
        except TimeoutError:
            pass
        os.close(descriptor)


async def _execute(args: argparse.Namespace) -> dict[str, object]:
    """Bound preflight, migration, network capture, final drain, and sealing together."""

    cleanup_reserve_s = min(PRODUCER_STOP_TIMEOUT_S, args.seconds * 0.25)
    work_budget_s = max(0.05, args.seconds - cleanup_reserve_s)
    try:
        async with asyncio.timeout(work_budget_s):
            return await _execute_bounded(args, cleanup_budget_s=cleanup_reserve_s)
    except TimeoutError:
        raise CaptureRefused("CAPTURE_TOTAL_DEADLINE_NO_SEAL") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="show the fixed capture envelope (default)")
    mode.add_argument(
        "--execute",
        action="store_true",
        help="capture fresh public market inputs into isolated SIM",
    )
    parser.add_argument("--run-id", help="new UUID4 used as the immutable root receipt and tape id")
    parser.add_argument("--receipt", help="new create-only local JSON receipt path")
    database = parser.add_mutually_exclusive_group()
    database.add_argument("--database-url-env", help="name of the environment variable containing the DSN")
    database.add_argument("--database-url-file", help="protected file containing the DSN")
    parser.add_argument("--seconds", type=int, default=MAX_SECONDS, help="capture deadline, 1..300 seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.execute:
        print(json.dumps(plan(), sort_keys=True, indent=2))
        return 0
    if not args.run_id or not args.receipt or not (args.database_url_env or args.database_url_file):
        print("EXECUTE_REQUIRES_RUN_ID_RECEIPT_AND_EXPLICIT_DATABASE_URL_SOURCE", file=sys.stderr)
        return 2
    if not 1 <= args.seconds <= MAX_SECONDS:
        print("SECONDS_OUT_OF_BOUNDS", file=sys.stderr)
        return 2
    try:
        result = asyncio.run(_execute(args))
    except CaptureRefused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (ValueError, OSError):
        print("CAPTURE_PREFLIGHT_REFUSED", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
