"""Capture one small public ALFRED vintage download; never admit source coverage."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .historical_context_capture import _validate_output_root, _write_create_only

URL = "https://alfred.stlouisfed.org/series/downloaddata?seid=CPIAUCSL"
FIELDS = {
    "form[units]": "lin",
    "form[obs_start_date]": "2021-04-01",
    "form[obs_end_date]": "2023-11-01",
    "form[entered_vintage_dates]": "2021-05-18 2024-01-08",
    "form[file_type]": "2",
    "form[file_format]": "csv",
    "form[download_data]": "",
}
BODY_LIMIT = 1_048_576
EXPANDED_LIMIT = 2_097_152
TIMEOUT_SECONDS = 20.0


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@dataclass(frozen=True)
class Response:
    body: bytes
    status: int
    content_type: str


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise ValueError("public macro download redirect rejected")


def _fetch(clock: Any = time.monotonic) -> Response:
    request = urllib.request.Request(
        URL,
        data=urllib.parse.urlencode(FIELDS).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    started = clock()
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        if response.status != 200 or response.geturl() != URL:
            raise ValueError("public macro download HTTP status rejected")
        declared = response.headers.get("Content-Length")
        if declared is not None and (not declared.isdecimal() or int(declared) > BODY_LIMIT):
            raise ValueError("public macro download declared length rejected")
        blocks = []
        total = 0
        while True:
            if clock() - started >= TIMEOUT_SECONDS:
                raise TimeoutError("public macro cooperative download deadline reached")
            block = response.read1(min(65_536, BODY_LIMIT + 1 - total))
            if clock() - started >= TIMEOUT_SECONDS:
                raise TimeoutError("public macro cooperative download deadline reached")
            if not block:
                break
            total += len(block)
            if total > BODY_LIMIT:
                raise ValueError("public macro download body limit reached")
            blocks.append(block)
        body = b"".join(blocks)
        if not body or (declared is not None and len(body) != int(declared)):
            raise ValueError("public macro download empty or truncated")
        return Response(body, response.status, response.headers.get("Content-Type", ""))


def inspect_zip(body: bytes) -> list[dict[str, Any]]:
    """Bounded ZIP inventory only; no filesystem extraction, vintage or coverage promotion."""
    if type(body) is not bytes or not body or len(body) > BODY_LIMIT:
        raise ValueError("bounded public macro bytes required")
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        members = archive.infolist()
        if not 1 <= len(members) <= 8 or len({item.filename for item in members}) != len(members):
            raise ValueError("bounded unique macro ZIP members required")
        if sum(item.file_size for item in members) > EXPANDED_LIMIT:
            raise ValueError("public macro expanded size limit reached")
        result = []
        for item in members:
            if (
                item.is_dir()
                or item.flag_bits & 1
                or not item.filename.isascii()
                or not item.filename.endswith((".csv", ".txt"))
                or "/" in item.filename
                or "\\" in item.filename
                or ":" in item.filename
                or len(item.filename) > 128
            ):
                raise ValueError("public macro ZIP member path or format rejected")
            with archive.open(item) as stream:
                payload = stream.read(EXPANDED_LIMIT + 1)
            if len(payload) != item.file_size or len(payload) > EXPANDED_LIMIT:
                raise ValueError("public macro ZIP member length differs")
            result.append(
                {
                    "filename": item.filename,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        return result


def capture(root: Path, *, workspace_root: Path, fetch: Any = _fetch, wall_ms: Any = None) -> dict[str, Any]:
    _validate_output_root(root, workspace_root)
    root.mkdir()
    if wall_ms is None:

        def wall_ms() -> int:
            return int(time.time() * 1000)

    requested = wall_ms()
    record = {
        "schema": "kairos.development.historical-macro-capture.v1",
        "capture_module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "pilot_plan_sha256": hashlib.sha256(
            (
                workspace_root
                / "kairos"
                / "development"
                / "adaptive_replay"
                / "historical-episodes-draft.json"
            ).read_bytes()
        ).hexdigest(),
        "url": URL,
        "method": "POST_PUBLIC_DATA_DOWNLOAD_ONLY",
        "fields": FIELDS,
        "actual_requested_ms": requested,
        "requests": 1,
        "automatic_retries": 0,
        "transport_deadline": "20_SECONDS_COOPERATIVE_NOT_HARD_WATCHDOG",
        "raw_file": None,
        "raw_sha256": None,
        "coverage": "UNKNOWN",
        "admitted_to_prompt": False,
        "historical_receive_clock_proven": False,
        "provider_calls": 0,
        "economics_executed": False,
        "trading_authority": False,
    }
    _write_create_only(root / "request.json", _canonical(record))
    try:
        response = fetch()
        observed = wall_ms()
        if (
            not isinstance(response, Response)
            or type(response.body) is not bytes
            or not 0 < len(response.body) <= BODY_LIMIT
            or response.status != 200
            or observed < requested
        ):
            raise ValueError("public macro response rejected")
        _write_create_only(root / "alfred-cpiaucsl-vintages.raw", response.body)
        record.update(
            raw_file="alfred-cpiaucsl-vintages.raw",
            raw_sha256=hashlib.sha256(response.body).hexdigest(),
            bytes=len(response.body),
            actual_captured_ms=observed,
            http_status=response.status,
            content_type=response.content_type,
        )
        record["zip_members"] = inspect_zip(response.body)
        record["state"] = "RAW_VINTAGE_DOWNLOAD_CAPTURED_UNADMITTED"
    except (OSError, ValueError, TimeoutError, zipfile.BadZipFile, RuntimeError) as exc:
        record.update(state="MACRO_CAPTURE_BLOCKED_NO_ABSENCE_PROOF", error_type=type(exc).__name__)
    _write_create_only(root / "receipt.json", _canonical(record))
    return record


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
        result = capture(args.output_root, workspace_root=args.workspace_root)
        print(_canonical(result).decode())
        return 0 if result["state"] == "RAW_VINTAGE_DOWNLOAD_CAPTURED_UNADMITTED" else 2
    except (OSError, ValueError) as exc:
        print(_canonical({"state": "MACRO_CAPTURE_FAILED_CLOSED", "error_type": type(exc).__name__}).decode())
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
