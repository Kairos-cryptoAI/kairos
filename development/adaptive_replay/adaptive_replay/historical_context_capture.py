"""Bounded public-document capture, never historical source admission.

The fixed accessible leads are retained as modern raw bytes. Publication dates,
archive names and hashes alone cannot grant exact-version or coverage authority.
No extraction into HistoricalArchive or model prompt takes place here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from .historical_acquisition import _NoRedirect, _validate_output_root, _write_create_only

# Do not add failed archival probes here as an automatic retry/resume mechanism.
TARGETS = (
    ("bls-cpi-20210413", "UNADMITTED_RELEASE", "https://www.bls.gov/news.release/archives/cpi_04132021.htm"),
    ("bls-cpi-20210512", "UNADMITTED_RELEASE", "https://www.bls.gov/news.release/archives/cpi_05122021.htm"),
    ("bls-cpi-20231212", "UNADMITTED_RELEASE", "https://www.bls.gov/news.release/archives/cpi_12122023.htm"),
    ("bls-cpi-20240111", "UNADMITTED_RELEASE", "https://www.bls.gov/news.release/archives/cpi_01112024.htm"),
    (
        "xinhua-20210518",
        "PUBLICATION_ONLY_LEAD",
        "https://www.xinhuanet.com/fortune/2021-05/18/c_1127461941.htm",
    ),
    (
        "gensler-1744833049064288387",
        "UNADMITTED_VERSION_ATTESTATION_LEAD",
        "https://cdn.syndication.twimg.com/tweet-result?id=1744833049064288387&lang=en&token=0",
    ),
    (
        "sec-1744829327294837236",
        "MODERN_DELETION_WITNESS_ONLY",
        "https://cdn.syndication.twimg.com/tweet-result?id=1744829327294837236&lang=en&token=0",
    ),
    (
        "sec-jan12-event-audit",
        "FUTURE_AT_JAN9_CUTS_AUDIT_ONLY",
        "https://www.sec.gov/newsroom/speeches-statements/gensler-x-account",
    ),
    (
        "house-jan10-authenticity-audit",
        "FUTURE_AT_JAN9_CUTS_AUDIT_ONLY",
        "https://financialservices.house.gov/uploadedfiles/2024-01-10_letter_to_sec_re_x_hack_final.pdf",
    ),
)
MAX_BODY_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = len(TARGETS) * MAX_BODY_BYTES
TIMEOUT_SECONDS = 15.0
DEADLINE_SECONDS = 150.0


@dataclass(frozen=True)
class CapturedResponse:
    body: bytes
    http_status: int
    content_type: str | None


Fetch = Callable[[str, int, float, int], bytes | CapturedResponse]


def _fetch_public(url: str, byte_limit: int, timeout: float, total_remaining: int) -> CapturedResponse:
    if url not in {target[2] for target in TARGETS}:
        raise ValueError("request is outside the fixed public document allowlist")
    limit = min(byte_limit, total_remaining)
    if limit <= 0:
        raise ValueError("public capture byte budget exhausted")
    request = Request(url, headers={"User-Agent": "Kairos-public-context-capture/1.0"})
    request_deadline = time.monotonic() + timeout
    try:
        with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            if response.getcode() != 200 or response.geturl() != url:
                raise ValueError("unexpected public capture HTTP response")
            length = response.headers.get("Content-Length")
            if length is not None and not 0 < int(length) <= limit:
                raise ValueError("public capture Content-Length exceeds bound or is empty")
            chunks: list[bytes] = []
            read_bytes = 0
            while read_bytes < limit:
                if time.monotonic() >= request_deadline:
                    raise TimeoutError("public capture per-request elapsed limit reached")
                # read1 performs at most one raw read, unlike read(limit), which
                # could wait indefinitely for a slow-drip full response. Socket
                # inactivity timeout still bounds a blocked raw read; elapsed
                # checks are cooperative, not a hard process watchdog.
                chunk = response.read1(min(64 * 1024, limit - read_bytes))
                if time.monotonic() >= request_deadline:
                    raise TimeoutError("public capture per-request elapsed limit reached")
                if not chunk:
                    break
                chunks.append(chunk)
                read_bytes += len(chunk)
                if length is not None and read_bytes == int(length):
                    break
            body = b"".join(chunks)
            if length is not None and len(body) != int(length):
                raise ValueError("public response body length differs from Content-Length")
            if length is None and len(body) == limit:
                raise ValueError("public response reached an uncertain byte bound")
            return CapturedResponse(body, 200, response.headers.get("Content-Type"))
    except HTTPError as exc:
        try:
            raise ValueError(f"public capture HTTP failed ({type(exc).__name__})") from None
        finally:
            exc.close()
    except (URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"public capture HTTP failed ({type(exc).__name__})") from None


def capture_public_leads(
    output: Path,
    *,
    workspace_root: Path,
    fetch: Fetch = _fetch_public,
    clock: Callable[[], float] = time.monotonic,
    wall_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
) -> dict[str, Any]:
    """One create-only capture of nine fixed public leads; failures are retained."""
    root = _validate_output_root(output, workspace_root)
    started = clock()
    root.mkdir(exist_ok=False)
    records: list[dict[str, Any]] = []
    total = 0
    for record_id, scope, url in TARGETS:
        remaining = DEADLINE_SECONDS - (clock() - started)
        if remaining <= 0:
            raise TimeoutError("public context capture deadline reached; partial bytes retained")
        requested = wall_ms()
        record: dict[str, Any] = {
            "id": record_id,
            "url": url,
            "scope": scope,
            "actual_capture_requested_ms": requested,
            "historical_availability_ms": None,
            "historical_local_receipt_ms": None,
            "coverage": "UNKNOWN",
            "admitted_to_prompt": False,
        }
        try:
            response = fetch(url, MAX_BODY_BYTES, min(TIMEOUT_SECONDS, remaining), MAX_TOTAL_BYTES - total)
            payload = response.body if isinstance(response, CapturedResponse) else response
            observed = wall_ms()
            if clock() - started >= DEADLINE_SECONDS:
                raise TimeoutError("public context capture deadline reached")
            if type(payload) is not bytes or not payload or len(payload) > MAX_BODY_BYTES:
                raise ValueError("public response must be non-empty bounded bytes")
            if isinstance(response, CapturedResponse) and response.http_status != 200:
                raise ValueError("public response must be HTTP 200")
            if observed < requested:
                raise ValueError("actual capture wall clock moved backwards")
            total += len(payload)
            if total > MAX_TOTAL_BYTES:
                raise ValueError("public context capture total byte limit exceeded")
            filename = f"{record_id}.raw"
            _write_create_only(root / filename, payload)
            record.update(
                state="RAW_CAPTURED_UNADMITTED",
                actual_captured_ms=observed,
                filename=filename,
                body_bytes=len(payload),
                raw_sha256=hashlib.sha256(payload).hexdigest(),
                http_status=response.http_status if isinstance(response, CapturedResponse) else None,
                content_type=response.content_type if isinstance(response, CapturedResponse) else None,
            )
        except (OSError, TimeoutError, ValueError) as exc:
            # Exception text could include server-controlled content. Keep only
            # the class; this is a capture failure, not proof of source absence.
            record.update(state="CAPTURE_FAILED_NO_ABSENCE_PROOF", error_type=type(exc).__name__)
        records.append(record)
        _write_create_only(root / f"{record_id}.receipt.json", _canonical(record))
    if clock() - started >= DEADLINE_SECONDS:
        raise TimeoutError("public context capture deadline reached; partial receipts retained")
    result = {
        "schema": "kairos.development.historical-context-capture.v1",
        "state": "CAPTURE_COMPLETED_NO_SOURCE_ADMISSION",
        "requests": len(records),
        "automatic_retries": 0,
        "captured_body_bytes": total,
        "records": records,
        "required_sources_ready": False,
        "coverage": "UNKNOWN",
        "provider_calls": 0,
        "strategy_generation_executed": False,
        "economics_executed": False,
        "trading_authority": False,
    }
    _write_create_only(root / "capture-summary.json", _canonical(result))
    return result


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--capture", action="store_true")
    args = parser.parse_args(argv)
    try:
        _validate_output_root(args.output_root, args.workspace_root)
        if not args.capture:
            print(_canonical({"state": "CAPTURE_NOT_REQUESTED", "network": False}).decode())
            return 0
        result = capture_public_leads(args.output_root, workspace_root=args.workspace_root)
    except (OSError, TimeoutError, ValueError) as exc:
        print(_canonical({"state": "CAPTURE_FAILED_CLOSED", "error_type": type(exc).__name__}).decode())
        return 2
    print(_canonical(result).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
