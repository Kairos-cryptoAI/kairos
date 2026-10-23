"""Finite free-source availability probe; no models, SIM, or trading path."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .current_capture import (
    BAR_COUNT,
    BAR_MS,
    MAX_CAPTURE_BYTES,
    PAGE_LIMIT,
    TEXT_FEEDS,
    UNIVERSE,
    CurrentPublicCapture,
    _canonical_bytes,
)

MAX_TOTAL_SECONDS = 900
OFFICIAL_CONTEXT_MAX_BYTES = 4 * 1024 * 1024
SOURCE_HTTP_MAX_BYTES = MAX_CAPTURE_BYTES - OFFICIAL_CONTEXT_MAX_BYTES
MAX_TOTAL_REQUESTS = 40


class CreateOnlyPublicationError(OSError):
    def __init__(self, partial_path: Path, cause: BaseException):
        super().__init__("CREATE_ONLY_PUBLICATION_INCOMPLETE")
        self.partial_path = partial_path
        self.__cause__ = cause


def _validate_output_path(path: Path) -> None:
    """Apply current_capture's no-symlink/no-reparse traversal policy pre-mkdir."""

    absolute = path.absolute()
    for component in reversed((absolute.parent, *absolute.parent.parents)):
        try:
            info = component.lstat()
        except OSError as exc:
            raise FileNotFoundError("SOURCE_PROBE_PARENT_MUST_EXIST") from exc
        if component.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("SOURCE_PROBE_CANNOT_TRAVERSE_LINKS")
    if not absolute.parent.is_dir():
        raise FileNotFoundError("SOURCE_PROBE_PARENT_MUST_BE_DIRECTORY")


def _write_create_only(path: Path, value: Any) -> None:
    payload = _canonical_bytes(value) + b"\n"
    partial = path.with_name(f".{path.name}.partial-{uuid.uuid4().hex}")
    try:
        fd = os.open(partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            written = stream.write(payload)
            if written != len(payload):
                raise OSError("CREATE_ONLY_SHORT_WRITE")
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link publication is atomic and fails if the final name exists.
        # The explicit .partial file remains as evidence if publication fails.
        os.link(partial, path)
        partial.unlink()
    except BaseException as exc:
        raise CreateOnlyPublicationError(partial, exc) from exc


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("CAPTURE_RECEIPT_INTEGRITY_FAILURE") from exc
    if type(value) is not dict:
        raise ValueError("CAPTURE_RECEIPT_NOT_OBJECT")
    return value


def _feed_roster() -> tuple[str, ...]:
    seen: set[str] = set()
    feeds: list[str] = []
    for url, configuration in TEXT_FEEDS.items():
        source_id = configuration[0]
        if source_id not in seen:
            seen.add(source_id)
            feeds.append(url)
    return tuple(feeds)


def _eligibility(snapshot: Any) -> dict[str, Any]:
    # Reuse the exact normalizer/freshness/dedup/relevance stages already used
    # by the bounded CURRENT capture. This helper makes no provider call.
    from .current_verify import PhaseBoundedCapture

    return PhaseBoundedCapture._assess_news_model_eligibility(snapshot)


def _new_capture(output: Path, feed: str, *, started: float, consumed_bytes: int) -> CurrentPublicCapture:
    remaining_seconds = MAX_TOTAL_SECONDS - (time.monotonic() - started)
    remaining_bytes = SOURCE_HTTP_MAX_BYTES - consumed_bytes
    if remaining_seconds <= 0:
        raise ValueError("AGGREGATE_TIME_BOUND_EXCEEDED")
    if remaining_bytes <= 0:
        raise ValueError("AGGREGATE_BYTE_BOUND_EXCEEDED")
    return CurrentPublicCapture(
        output,
        text_feed=feed,
        byte_limit=remaining_bytes,
        deadline_seconds=min(120.0, remaining_seconds),
    )


def _ensure_request_capacity(used: int, planned: int) -> None:
    if used + planned > MAX_TOTAL_REQUESTS:
        raise ValueError("AGGREGATE_REQUEST_BOUND_EXCEEDED")


def _is_global_bound_failure(
    exc: Exception,
    *,
    started: float,
    used_bytes: int,
    capture: CurrentPublicCapture | None,
) -> bool:
    reason = str(exc)
    return (
        isinstance(exc, CreateOnlyPublicationError)
        or "CREATE_ONLY_WRITE_FAILED" in reason
        or "RECEIPT_INTEGRITY_FAILURE" in reason
        or "RECEIPT_NOT_OBJECT" in reason
        or time.monotonic() - started >= MAX_TOTAL_SECONDS
        or used_bytes >= SOURCE_HTTP_MAX_BYTES
        or reason
        in {
            "AGGREGATE_TIME_BOUND_EXCEEDED",
            "AGGREGATE_BYTE_BOUND_EXCEEDED",
            "AGGREGATE_REQUEST_BOUND_EXCEEDED",
            "CAPTURE_BYTE_LIMIT_EXCEEDED",
        }
        or (
            reason == "HTTP_BODY_LIMIT_EXCEEDED"
            and capture is not None
            and capture.byte_limit - capture.bytes_used < 2 * 1024 * 1024
        )
    )


async def _capture_probe(output: Path) -> dict[str, Any]:
    started_monotonic = time.monotonic()
    started_ms = time.time_ns() // 1_000_000
    total_bytes = 0
    total_requests = 0
    feed_results: list[dict[str, Any]] = []
    source_failures: list[dict[str, str]] = []
    feeds = _feed_roster()
    request_ceiling = (
        len(feeds)
        + len(UNIVERSE) * ((BAR_COUNT + PAGE_LIMIT - 1) // PAGE_LIMIT)
        + len(UNIVERSE)
        + 2  # existing official-context fixed roster
    )
    if request_ceiling > MAX_TOTAL_REQUESTS:
        raise ValueError("AGGREGATE_REQUEST_PLAN_EXCEEDED")

    # Four MiB is reserved for the existing official-context capture's fixed
    # two-source roster (2 MiB per body); the remaining original 32 MiB budget
    # is shared by both RSS feeds, Binance bars, and depth snapshots.
    for feed in feeds:
        capture: CurrentPublicCapture | None = None
        result: dict[str, Any] = {"source_id": TEXT_FEEDS[feed][0], "url": feed, "state": "UNAVAILABLE"}
        try:
            _ensure_request_capacity(total_requests, 1)
            capture = _new_capture(output, feed, started=started_monotonic, consumed_bytes=total_bytes)
            snapshot = await capture.capture_text()
            result.update(
                {
                    "state": "CAPTURED",
                    "receipt": str(snapshot.receipt_path),
                    "raw_sha256": snapshot.raw_sha256,
                    "requested_ms": snapshot.requested_ms,
                    "received_ms": snapshot.received_ms,
                    "persisted_ms": snapshot.persisted_ms,
                }
            )
            receipt = _load_json(snapshot.receipt_path)
            try:
                eligible = _eligibility(snapshot)
                result.update(
                    {
                        "raw_item_count": receipt["raw_item_count"],
                        "fresh_item_count": receipt["fresh_item_count"],
                        "native_text_eligibility": eligible,
                    }
                )
            except Exception as exc:
                result["eligibility_state"] = "REFUSED"
                result["eligibility_error_type"] = type(exc).__name__
        except Exception as exc:
            if _is_global_bound_failure(
                exc, started=started_monotonic, used_bytes=total_bytes, capture=capture
            ):
                raise
            result.update({"state": "REFUSED", "error_type": type(exc).__name__})
            source_failures.append({"stage": result["source_id"], "error_type": type(exc).__name__})
        finally:
            if capture is not None:
                total_bytes += capture.bytes_used
                total_requests += capture.requests
        feed_results.append(result)

    macro: dict[str, Any] = {
        "status": "unavailable",
        "classification": "OFFICIAL_CONTEXT_CAPTURE_NOT_COMPLETED",
        "available_sources": [],
        "source_statuses": [],
    }
    macro_dir = output / f"official-context-{datetime.now(UTC):%Y%m%d}-first"
    macro_path = output / "official-macro-context.json"
    try:
        _ensure_request_capacity(total_requests, 2)
        from .current_macro import capture_current_macro

        macro = await capture_current_macro(macro_dir)
        _write_create_only(macro_path, macro)
    except Exception as exc:
        if _is_global_bound_failure(exc, started=started_monotonic, used_bytes=total_bytes, capture=None):
            raise
        source_failures.append({"stage": "official_macro_capture", "error_type": type(exc).__name__})
    macro_receipt_path = macro_dir / "receipt.json"
    macro_receipt: dict[str, Any] | None = None
    if macro_receipt_path.is_file():
        macro_receipt = _load_json(macro_receipt_path)
    macro_bytes = (
        sum(int(row.get("raw_bytes") or 0) for row in macro_receipt.get("source_results", []))
        if macro_receipt
        else 0
    )
    macro_requests = (
        sum(int(row.get("attempts") or 0) for row in macro_receipt.get("source_results", []))
        if macro_receipt
        else 0
    )
    if macro_bytes > OFFICIAL_CONTEXT_MAX_BYTES or total_bytes + macro_bytes > MAX_CAPTURE_BYTES:
        raise ValueError("AGGREGATE_BYTE_BOUND_EXCEEDED")
    total_bytes += macro_bytes
    total_requests += macro_requests

    # Each symbol is an independent one-shot source request. A malformed or
    # unavailable symbol does not suppress the remaining preplanned checks.
    quote_results: list[dict[str, Any]] = []
    for symbol in UNIVERSE:
        capture = None
        row: dict[str, Any] = {"symbol": symbol, "state": "UNAVAILABLE"}
        try:
            _ensure_request_capacity(total_requests, 1)
            capture = _new_capture(output, feeds[0], started=started_monotonic, consumed_bytes=total_bytes)
            quote = await capture.fresh_quote(symbol)
            row.update(
                {
                    "state": "CAPTURED",
                    "raw_sha256": quote.raw_sha256,
                    "requested_ms": quote.requested_ms,
                    "received_ms": quote.received_ms,
                    "captured_ms": quote.captured_ms,
                    "source_event_age_ms": quote.received_ms - quote.entry_quote.observed_at_ms,
                    "live_two_second_authorization_equivalent": False,
                    "receipt": str(quote.receipt_path),
                }
            )
        except Exception as exc:
            if _is_global_bound_failure(
                exc, started=started_monotonic, used_bytes=total_bytes, capture=capture
            ):
                raise
            row.update({"state": "REFUSED", "error_type": type(exc).__name__})
            source_failures.append({"stage": f"depth:{symbol}", "error_type": type(exc).__name__})
        finally:
            if capture is not None:
                total_bytes += capture.bytes_used
                total_requests += capture.requests
        quote_results.append(row)

    history_result: dict[str, Any] = {"state": "UNAVAILABLE"}
    cut_ms = (time.time_ns() // 1_000_000 // BAR_MS) * BAR_MS
    bar_counts: dict[str, int] | None = None
    page_receipts: list[str] = []
    capture = None
    try:
        _ensure_request_capacity(total_requests, len(UNIVERSE) * ((BAR_COUNT + PAGE_LIMIT - 1) // PAGE_LIMIT))
        capture = _new_capture(output, feeds[0], started=started_monotonic, consumed_bytes=total_bytes)
        history = await capture.fetch_history(cut_ms)
        bar_counts = {symbol: len(history.bars_by_symbol[symbol]) for symbol in UNIVERSE}
        page_receipts = [str(row.receipt_path) for row in history.page_receipts]
        history_result = {"state": "CAPTURED", "coverage_scope": history.coverage_scope}
    except Exception as exc:
        if _is_global_bound_failure(exc, started=started_monotonic, used_bytes=total_bytes, capture=capture):
            raise
        history_result.update({"state": "REFUSED", "error_type": type(exc).__name__})
        source_failures.append({"stage": "closed_bar_history", "error_type": type(exc).__name__})
    finally:
        if capture is not None:
            total_bytes += capture.bytes_used
            total_requests += capture.requests

    elapsed = time.monotonic() - started_monotonic
    if total_requests > MAX_TOTAL_REQUESTS:
        raise ValueError("AGGREGATE_REQUEST_BOUND_EXCEEDED")
    if total_bytes > MAX_CAPTURE_BYTES:
        raise ValueError("AGGREGATE_BYTE_BOUND_EXCEEDED")
    if elapsed > MAX_TOTAL_SECONDS:
        raise ValueError("AGGREGATE_TIME_BOUND_EXCEEDED")

    all_captured = (
        not source_failures
        and all(row["state"] == "CAPTURED" for row in feed_results)
        and all(row["state"] == "CAPTURED" for row in quote_results)
        and history_result["state"] == "CAPTURED"
        and macro.get("status") == "available"
        and all("native_text_eligibility" in row for row in feed_results)
    )
    summary = {
        "schema": "kairos.current-free-source-qualification.v1",
        "state": "CAPTURED_SOURCE_AVAILABILITY_ONLY" if all_captured else "PARTIAL_SOURCE_AVAILABILITY",
        "started_ms": started_ms,
        "ended_ms": time.time_ns() // 1_000_000,
        "elapsed_seconds": round(elapsed, 3),
        "aggregate_limits": {
            "requests_max": MAX_TOTAL_REQUESTS,
            "requests_used": total_requests,
            "bytes_max": MAX_CAPTURE_BYTES,
            "bytes_used": total_bytes,
            "wall_seconds_max": MAX_TOTAL_SECONDS,
            "paid_calls": 0,
            "retries": 0,
            "sim_resources": False,
            "database_or_queue_writes": False,
            "orders": False,
        },
        "news": feed_results,
        "source_failures": source_failures,
        "market": {
            "source": "Binance USD-M public REST",
            "cut_ms": cut_ms,
            "closed_history": history_result,
            "bar_count_per_symbol": bar_counts,
            "bar_page_receipts": page_receipts,
            "depth_snapshots": quote_results,
            "depth_source_freshness_limit_ms": 5_000,
            "live_market_authorization_limit_ms": 2_000,
        },
        "official_macro_capture": {
            "status": macro["status"],
            "classification": macro["classification"],
            "available_sources": macro["available_sources"],
            "source_statuses": macro["source_statuses"],
            "receipt": str(macro_receipt_path) if macro_receipt_path.is_file() else None,
            "context": str(macro_path) if macro_path.is_file() else None,
            "request_count": macro_requests,
            "raw_bytes": macro_bytes,
            "numeric_macro_values_are_not_inferred": True,
        },
        "unestablished_stages": [
            "MacroStrategist output",
            "Router route",
            "candidate review receipt",
            "authenticated LiveInputsSourceVerifier receipt",
            "unified LIVE Risk admission",
        ],
        "readiness_promotion": False,
    }
    _write_create_only(output / "source-qualification.json", summary)
    return summary


async def run_probe(output_dir: Path) -> dict[str, Any]:
    """Create a new source directory and capture once; never adopt old evidence."""

    output = Path(output_dir).absolute()
    _validate_output_path(output)
    if output.exists():
        raise FileExistsError("SOURCE_PROBE_OUTPUT_MUST_BE_NEW")
    output.mkdir()  # Atomic create-only run identity; existing paths are refused.
    try:
        _write_create_only(
            output / "source-probe-plan.json",
            {
                "schema": "kairos.current-free-source-qualification-plan.v1",
                "feeds": list(_feed_roster()),
                "market_symbols": list(UNIVERSE),
                "market_history": f"{BAR_COUNT} closed 1m bars per symbol",
                "official_macro_sources": "existing fixed official-context roster",
                "models_or_provider_calls": False,
                "sim_or_database": False,
                "strategy_or_campaign": False,
            },
        )
        async with asyncio.timeout(MAX_TOTAL_SECONDS):
            return await _capture_probe(output)
    except BaseException as exc:
        failure = output / "source-probe-failure.json"
        if not failure.exists():
            try:
                _write_create_only(
                    failure,
                    {
                        "state": "FAILED_CLOSED",
                        "exception_type": type(exc).__name__,
                        "at_ms": time.time_ns() // 1_000_000,
                        "readiness_promotion": False,
                    },
                )
            except Exception as receipt_exc:
                exc.add_note(f"Failure receipt could not be published: {type(receipt_exc).__name__}")
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Perform one bounded public-source capture")
    parser.add_argument("--output", type=Path, required=True, help="New create-only run directory")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"execute_required": True, "output": str(args.output)}, indent=2))
        return 0
    summary = asyncio.run(run_probe(args.output))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
