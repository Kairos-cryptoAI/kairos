"""Single-window, bounded Binance archive acquisition for episode_a source prep.

This module is deliberately limited to the five fixed May 2021 USD-M archives.
It is not an economic runner and has no provider, database, or strategy calls.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .historical_inputs import validate_replay_inputs
from .inputs import UNIVERSE, load_window

BASE_URL = "https://data.binance.vision/data/futures/um/monthly"
EPISODE_WINDOW = {"id": "episode_a_may_2021", "start": "2021-05-17", "end_exclusive": "2021-05-22"}
REQUEST_TIMEOUT_SECONDS = 15.0
DEADLINE_SECONDS = 180.0
MAX_REQUESTS = 20
MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_CHECKSUM_BYTES = 2 * 1024
MAX_TOTAL_FETCHED_BYTES = 32 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 16 * 1024 * 1024
MAX_CHECKSUM = re.compile(rb"([0-9a-fA-F]{64})[ \t]+\*?([^\s]+)[ \t]*\n?\Z")

Fetch = Callable[[str, int, float, int], bytes]
Clock = Callable[[], float]
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _targets() -> tuple[tuple[str, str, str, Path], ...]:
    targets: list[tuple[str, str, str, Path]] = []
    for symbol in UNIVERSE:
        bar_name = f"{symbol}-1m-2021-05.zip"
        bar_path = Path("bars") / symbol / "1m" / bar_name
        bar_url = f"{BASE_URL}/klines/{symbol}/1m/{bar_name}"
        targets.append((symbol, "bars", bar_url, bar_path))
        funding_name = f"{symbol}-fundingRate-2021-05.zip"
        funding_path = Path("factors") / "fundingRate" / symbol / funding_name
        funding_url = f"{BASE_URL}/fundingRate/{symbol}/{funding_name}"
        targets.append((symbol, "funding", funding_url, funding_path))
    return tuple(targets)


def _validate_target_url(url: str, expected_url: str) -> None:
    parts = urlsplit(url)
    expected = urlsplit(expected_url)
    if (
        url != expected_url
        or parts.scheme != "https"
        or parts.hostname != "data.binance.vision"
        or parts.port not in (None, 443)
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.netloc != expected.netloc
    ):
        raise ValueError("request is outside the fixed official Binance archive allowlist")


def _http_fetch(url: str, byte_limit: int, timeout: float, total_remaining: int) -> bytes:
    if total_remaining <= 0:
        raise ValueError("historical acquisition total-byte limit reached")
    opener = build_opener(_NoRedirect())
    request = Request(url, headers={"User-Agent": "Kairos-bounded-historical-source-prep/1.0"})
    read_limit = min(byte_limit, total_remaining)
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.getcode() != 200 or response.geturl() != url:
                raise ValueError("unexpected HTTP response for fixed archive request")
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > read_limit:
                raise ValueError("response Content-Length exceeds remaining byte budget")
            payload = response.read(read_limit)
            if content_length is not None and len(payload) != int(content_length):
                raise ValueError("response body length differs from Content-Length")
            if len(payload) == read_limit and content_length is None:
                raise ValueError("response reached an uncertain hard byte limit")
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            raise ValueError("redirects are disabled for archive acquisition") from None
        raise ValueError(f"official archive request failed with HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"official archive request failed ({type(exc).__name__})") from None
    return payload


def _check_archive_zip(payload: bytes, expected_csv_name: str) -> None:
    if not isinstance(payload, bytes) or len(payload) > MAX_ARCHIVE_BYTES:
        raise ValueError("archive exceeds its compressed-byte bound")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].filename != expected_csv_name or members[0].is_dir():
                raise ValueError("archive must contain exactly its expected CSV member")
            if members[0].file_size > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("archive member exceeds its decompressed-byte bound")
            with archive.open(members[0]) as member:
                if len(member.read(MAX_UNCOMPRESSED_BYTES + 1)) > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("archive member exceeds its decompressed-byte bound")
    except zipfile.BadZipFile as exc:
        raise ValueError("archive is not a valid ZIP") from exc


def _verify_checksum(payload: bytes, sidecar: bytes, filename: str) -> str:
    if not isinstance(sidecar, bytes) or len(sidecar) > MAX_CHECKSUM_BYTES:
        raise ValueError("checksum sidecar exceeds its byte bound")
    match = MAX_CHECKSUM.fullmatch(sidecar)
    if match is None or match.group(2).decode("ascii", errors="strict") != filename:
        raise ValueError("checksum sidecar must name the exact archive filename")
    actual = hashlib.sha256(payload).hexdigest()
    if actual != match.group(1).decode("ascii").lower():
        raise ValueError("official archive SHA-256 mismatch")
    return actual


def _write_create_only(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)


def _validate_workspace_root(path: Path) -> tuple[Path, Path]:
    if not path.is_absolute():
        raise ValueError("--workspace-root must be an absolute Kairos workspace path")
    workspace_input = path.absolute()
    for component in (*reversed(workspace_input.parents), workspace_input):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        if component.is_symlink() or getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT:
            raise ValueError("workspace root and its parents must not be reparse points")
    workspace = workspace_input.resolve(strict=True)
    repository = workspace / "kairos"
    plan_path = workspace / "kairos" / "development" / "adaptive_replay" / "historical-episodes-draft.json"
    loader_path = workspace / "kairos-backtest" / "kairos_backtest" / "data.py"
    runtime_path = workspace / "runtime"
    if (
        not repository.is_dir()
        or not (repository / ".git").exists()
        or not plan_path.is_file()
        or not loader_path.is_file()
        or not runtime_path.is_dir()
    ):
        raise ValueError("--workspace-root does not have the expected Kairos repo/runtime layout")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        episode = next(item for item in plan["episodes"] if item["id"] == "episode_a")
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        raise ValueError("workspace historical episode roster is not readable") from None
    if (
        plan.get("schema") != "kairos.development.historical-episode-roster.v1"
        or episode.get("candidate_start_utc") != "2021-05-17T00:00:00Z"
        or episode.get("candidate_end_exclusive_utc") != "2021-05-22T00:00:00Z"
    ):
        raise ValueError("workspace does not contain the fixed episode_a May 2021 roster")
    runtime_path = runtime_path.absolute()
    runtime = runtime_path.resolve(strict=True)
    for component in (*reversed(workspace.parents), workspace, *reversed(runtime.parents), runtime_path):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        if component.is_symlink() or getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT:
            raise ValueError("workspace root and runtime parents must not be reparse points")
    if runtime.parent != workspace:
        raise ValueError("workspace runtime must be a direct child of the workspace root")
    return workspace, runtime


def _validate_output_root(path: Path, workspace_root: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("--output-root must be an absolute task-owned path")
    workspace, runtime = _validate_workspace_root(workspace_root)
    candidate_input = path.absolute()
    if candidate_input.is_symlink():
        raise ValueError("--output-root must not be a symlink or reparse point")
    if candidate_input.parent != runtime:
        raise ValueError("--output-root must be a direct child of the dedicated Kairos runtime directory")
    candidate = candidate_input.resolve(strict=False)
    if candidate.parent != runtime:
        raise ValueError("--output-root must be a direct child of the dedicated Kairos runtime directory")
    # Reject junctions/symlinks at the trusted runtime root and candidate itself.
    for component in (workspace, runtime, candidate_input, candidate):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        if component.is_symlink() or getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT:
            raise ValueError("--output-root and its runtime parent must not be reparse points")
    if candidate.exists() or candidate.is_symlink():
        raise FileExistsError("output root must be a new, nonexistent directory")
    forbidden = (
        (workspace / "kairos-backtest" / "data" / "historical").resolve(strict=False),
        (workspace / "kairos-backtest" / "data" / "historical-factors").resolve(strict=False),
        (workspace / "kairos" / "development" / "adaptive_replay" / "evidence").resolve(strict=False),
    )
    norm_candidate = os.path.normcase(str(candidate))
    if any(
        norm_candidate == os.path.normcase(str(item))
        or norm_candidate.startswith(os.path.normcase(str(item)) + os.sep)
        for item in forbidden
    ):
        raise ValueError("--output-root overlaps an original cache or frozen source evidence")
    return candidate


def acquire_episode_a_may_2021(
    output_root: Path,
    *,
    workspace_root: Path,
    fetch: Fetch = _http_fetch,
    clock: Clock = time.monotonic,
) -> dict[str, Any]:
    """Acquire and strictly validate the fixed May 2021 bars/funding roster.

    ``output_root`` must not exist. Completed checksum-verified pairs are
    intentionally retained if a later request or validation fails; there is no
    retry, resume, overwrite, or acceptance marker on failure.
    """
    root = _validate_output_root(Path(output_root), Path(workspace_root))
    start = clock()
    deadline = start + DEADLINE_SECONDS
    requests = 0
    fetched_bytes = 0
    downloaded: list[dict[str, Any]] = []
    root.mkdir(parents=True, exist_ok=False)

    for symbol, kind, archive_url, relative_path in _targets():
        filename = relative_path.name
        checksum_url = f"{archive_url}.CHECKSUM"
        for url, byte_limit in ((archive_url, MAX_ARCHIVE_BYTES), (checksum_url, MAX_CHECKSUM_BYTES)):
            _validate_target_url(url, archive_url if url == archive_url else checksum_url)
            remaining = deadline - clock()
            if remaining <= 0:
                raise TimeoutError("180-second historical acquisition deadline reached")
            total_remaining = MAX_TOTAL_FETCHED_BYTES - fetched_bytes
            if requests >= MAX_REQUESTS:
                raise ValueError("historical acquisition GET limit reached")
            if total_remaining <= 0:
                raise ValueError("historical acquisition total-byte limit reached")
            requests += 1
            payload = fetch(url, byte_limit, min(REQUEST_TIMEOUT_SECONDS, remaining), total_remaining)
            if not isinstance(payload, bytes):
                raise ValueError("archive fetcher must return bytes")
            fetched_bytes += len(payload)
            if fetched_bytes > MAX_TOTAL_FETCHED_BYTES:
                raise ValueError("historical acquisition total-byte limit reached")
            if len(payload) > byte_limit:
                raise ValueError("archive response exceeds its per-request byte bound")
            if clock() >= deadline:
                raise TimeoutError("180-second historical acquisition deadline reached")
            if url == archive_url:
                archive_payload = payload
            else:
                checksum_payload = payload

        expected_csv = filename[:-4] + ".csv"
        digest = _verify_checksum(archive_payload, checksum_payload, filename)
        if clock() >= deadline:
            raise TimeoutError("180-second historical acquisition deadline reached")
        _check_archive_zip(archive_payload, expected_csv)
        if clock() >= deadline:
            raise TimeoutError("180-second historical acquisition deadline reached")
        archive_path = root / relative_path
        checksum_path = archive_path.with_name(f"{filename}.CHECKSUM")
        _write_create_only(archive_path, archive_payload)
        _write_create_only(checksum_path, checksum_payload)
        downloaded.append(
            {
                "symbol": symbol,
                "kind": kind,
                "filename": filename,
                "bytes": len(archive_payload),
                "sha256": digest,
                "checksum_sha256": hashlib.sha256(checksum_payload).hexdigest(),
            }
        )

    # No downloader path is enabled in this source-only validator. Existing
    # defaults preserve the 54-hour warmup (rounded to midnight) and 3-hour tail.
    bars_root = root / "bars"
    factors_root = root / "factors"
    inputs = load_window(bars_root, factors_root, EPISODE_WINDOW)
    if clock() >= deadline:
        raise TimeoutError("180-second historical acquisition deadline reached")
    validate_replay_inputs(inputs, fixture_only=False, deadline=deadline)
    if clock() >= deadline:
        raise TimeoutError("180-second historical acquisition deadline reached")
    source_summary = {
        symbol: {
            "bars": len(inputs.bars[symbol]),
            "funding": len(inputs.funding[symbol]),
            "bar_sha256": inputs.evidence["bars"][symbol]["normalized_rows_sha256"],
            "funding_sha256": inputs.evidence["funding"][symbol]["normalized_rows_sha256"],
            "gaps": inputs.evidence["bars"][symbol]["gaps"],
        }
        for symbol in UNIVERSE
    }
    result = {
        "schema": "kairos.development.historical-acquisition.v1",
        "state": "SOURCE_INPUTS_VALIDATED_ONLY",
        "episode": EPISODE_WINDOW["id"],
        "requests": requests,
        "fetched_bytes": fetched_bytes,
        "archives": downloaded,
        "source_summary": source_summary,
        "strategy_or_economics_executed": False,
        "provider_calls": 0,
        "trading_authority": False,
    }
    if clock() >= deadline:
        raise TimeoutError("180-second historical acquisition deadline reached")
    summary = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    _write_create_only(root / "source-summary.json", summary)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bounded official-source preparation for fixed episode_a only"
    )
    parser.add_argument("--workspace-root", type=Path, required=True, help="absolute Kairos workspace root")
    parser.add_argument(
        "--output-root", type=Path, required=True, help="new task-owned cache root; must not exist"
    )
    parser.add_argument(
        "--fetch", action="store_true", help="explicitly authorize the fixed 20-GET acquisition"
    )
    args = parser.parse_args(argv)
    try:
        _validate_workspace_root(args.workspace_root)
        root = _validate_output_root(args.output_root, args.workspace_root)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if not args.fetch:
        print(
            json.dumps(
                {"state": "FETCH_NOT_REQUESTED", "network": False, "output_created": False},
                sort_keys=True,
            )
        )
        return 0
    try:
        result = acquire_episode_a_may_2021(root, workspace_root=args.workspace_root)
    except (OSError, TimeoutError, ValueError) as exc:
        print(json.dumps({"state": "FAILED_NO_ACCEPTANCE", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
