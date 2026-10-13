"""Bounded anonymous DEMO diagnostic, never DEV/PAPER or liquidity qualification.

Exactly eleven public GETs: matcher/instruments and default depth, best depth,
recent trades for BTC, ETH and 1000PEPE. No credentials, wallet, account endpoint,
orders, database, Binance comparison, scheduler or automatic retry. A durable
daily reservation survives interruption; this program has no resume operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import ssl
import stat
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ORIGIN = "https://trading-api.evedex.io"
SYMBOLS = ("BTCUSD:DEMO", "ETHUSD:DEMO", "1000PEPEUSD:DEMO")
KAIROS_REQUIRED_DEV_SYMBOLS = (
    "BTCUSD:DEV",
    "ETHUSD:DEV",
    "SOLUSD:DEV",
    "BNBUSD:DEV",
    "XRPUSD:DEV",
)
SOURCE_ROOT = Path("D:/Kairos/kairos")
SOURCE_RELATIVE = "development/ops_alerts/evedex_demo_public_diagnostic.py"
EVIDENCE_ROOT = Path("D:/Kairos/runtime/evedex-demo-public-diagnostic")
SIGNER = "40AF365C6682B73D056A6A274DBFF6B65BE9F827"
GIT = Path("C:/Program Files/Git/cmd/git.exe")
MAX_CALLS = 11
MAX_BODY_BYTES = 256 * 1024
TIMEOUT_SECONDS = 10
MAX_RUN_SECONDS = 180
MOSCOW = timezone(timedelta(hours=3))


class DiagnosticError(Exception):
    """Only fixed categories; never include URLs, response bodies or driver text."""


@dataclass(frozen=True)
class Endpoint:
    kind: str
    path: str
    symbol: str | None = None
    variant: str | None = None


@dataclass(frozen=True)
class Response:
    body: bytes
    captured_at: datetime
    http_status: int = 200
    latency_ms: float = 0.0


ENDPOINTS = (
    Endpoint("matcher", "/api/market"),
    Endpoint("instruments", "/api/market/instrument"),
    *(
        endpoint
        for symbol in SYMBOLS
        for endpoint in (
            Endpoint("depth", f"/api/market/{symbol}/deep", symbol, "default"),
            Endpoint(
                "depth", f"/api/market/{symbol}/deep?marketLevel=1", symbol, "best"
            ),
            Endpoint("trades", f"/api/market/{symbol}/recent-trades", symbol),
        )
    ),
)
PATHS = frozenset(endpoint.path for endpoint in ENDPOINTS)


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def exclusive_json(path: Path, value: Any) -> None:
    with path.open("xb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def _no_reparse(path: Path) -> None:
    info = path.lstat()
    if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
        raise DiagnosticError("UNSAFE_LOCAL_PATH")


def _source_bytes() -> bytes:
    path = SOURCE_ROOT / SOURCE_RELATIVE
    for parent in (SOURCE_ROOT, path.parent.parent, path.parent, path):
        _no_reparse(parent)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 128 * 1024:
        raise DiagnosticError("SOURCE_NOT_ADMITTED")
    return path.read_bytes()


def _git(*args: str, binary: bool = False) -> Any:
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {
            "SYSTEMROOT",
            "WINDIR",
            "PATH",
            "TEMP",
            "TMP",
            "COMSPEC",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "HOMEDRIVE",
            "HOMEPATH",
            "HOME",
            "GNUPGHOME",
        }
    }
    env.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
        }
    )
    result = subprocess.run(
        [str(GIT), "-C", str(SOURCE_ROOT), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=not binary,
        env=env,
        shell=False,
        timeout=20,
        check=False,
    )
    if result.returncode:
        raise DiagnosticError("SOURCE_NOT_ADMITTED")
    return result.stdout


def verify_source() -> tuple[str, str]:
    record = _git("show", "-s", "--format=%H %G? %GF", "HEAD").split()
    if (
        len(record) != 3
        or not re.fullmatch(r"[0-9a-f]{40}", record[0])
        or record[1:] != ["G", SIGNER]
        or _git("branch", "--show-current").strip() != "main"
        or _git("rev-parse", "origin/main").strip() != record[0]
        or _git("status", "--porcelain", "--", SOURCE_RELATIVE).strip()
    ):
        raise DiagnosticError("SOURCE_NOT_ADMITTED")
    content = _source_bytes()
    if content != _git("show", f"HEAD:{SOURCE_RELATIVE}", binary=True):
        raise DiagnosticError("SOURCE_NOT_ADMITTED")
    return hashlib.sha256(content).hexdigest(), record[0]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def request_url(path: str) -> str:
    if type(path) is not str or path not in PATHS:
        raise DiagnosticError("REQUEST_NOT_ADMITTED")
    return ORIGIN + path


def http_get(path: str) -> Response:
    url = request_url(path)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    request = urllib.request.Request(
        url, method="GET", headers={"Accept": "application/json"}
    )
    started = time.monotonic()
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            if response.geturl() != url:
                raise DiagnosticError("REDIRECT_BLOCKED")
            if response.status != 200:
                raise DiagnosticError("HTTP_ERROR")
            body = response.read(MAX_BODY_BYTES + 1)
            if len(body) > MAX_BODY_BYTES:
                raise DiagnosticError("RESPONSE_TOO_LARGE")
            return Response(
                body,
                datetime.now(UTC),
                int(response.status),
                round((time.monotonic() - started) * 1000, 2),
            )
    except urllib.error.HTTPError as error:
        category = "REDIRECT_BLOCKED" if 300 <= error.code < 400 else "HTTP_ERROR"
        error.close()
        raise DiagnosticError(category) from None
    except (urllib.error.URLError, OSError, TimeoutError, ssl.SSLError):
        raise DiagnosticError("TRANSPORT_UNKNOWN_NO_RETRY") from None


def parse_json(body: bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DiagnosticError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    if len(body) > MAX_BODY_BYTES:
        raise DiagnosticError("RESPONSE_TOO_LARGE")
    try:
        return json.loads(
            body.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=lambda _v: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, UnicodeError, RecursionError):
        raise DiagnosticError("JSON_INVALID") from None


def positive(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise DiagnosticError("SCHEMA_INVALID")
    if isinstance(value, str) and (
        len(value) > 128
        or not re.fullmatch(
            r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value
        )
    ):
        raise DiagnosticError("SCHEMA_INVALID")
    try:
        number = float(value)
    except (ValueError, OverflowError):
        raise DiagnosticError("SCHEMA_INVALID") from None
    if not math.isfinite(number) or number <= 0:
        raise DiagnosticError("SCHEMA_INVALID")
    return number


def inspect_book(payload: Any, captured_at: datetime) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"bids", "asks", "t"}:
        raise DiagnosticError("SCHEMA_INVALID")
    timestamp_ms = positive(payload["t"])
    sides = []
    for side in ("bids", "asks"):
        levels = payload[side]
        if not isinstance(levels, list) or len(levels) > 10000:
            raise DiagnosticError("SCHEMA_INVALID")
        prices = []
        for level in levels:
            if not isinstance(level, dict) or set(level) != {"price", "quantity"}:
                raise DiagnosticError("SCHEMA_INVALID")
            prices.append(positive(level["price"]))
            positive(level["quantity"])
        if len(set(prices)) != len(prices):
            raise DiagnosticError("SCHEMA_INVALID")
        sides.append(prices)
    bids, asks = sides
    age = round(captured_at.timestamp() - timestamp_ms / 1000, 6)
    observation: dict[str, Any] = {
        "bid_levels": len(bids),
        "ask_levels": len(asks),
        "timestamp_ms": timestamp_ms,
        "signed_age_seconds": age,
        "freshness": "FUTURE" if age < -2 else ("STALE" if age > 5 else "FRESH"),
    }
    if not bids or not asks:
        observation["state"] = (
            "EMPTY_BOOK" if not bids and not asks else "ONE_SIDED_BOOK"
        )
        return observation
    # REST bid ladders may be ascending; never confuse order with missing liquidity.
    best_bid, best_ask = max(bids), min(asks)
    observation.update(
        {
            "state": "TWO_SIDED_BOOK" if best_bid < best_ask else "CROSSED_BOOK",
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_bps": round(
                (best_ask - best_bid) / ((best_ask + best_bid) / 2) * 10000, 6
            ),
        }
    )
    return observation


def inspect_instruments(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list):
        raise DiagnosticError("SCHEMA_INVALID")
    by_name: dict[str, Any] = {}
    for row in payload:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise DiagnosticError("SCHEMA_INVALID")
        name = row["name"]
        if name in by_name:
            raise DiagnosticError("SCHEMA_INVALID")
        by_name[name] = row
    result = {}
    for symbol in SYMBOLS:
        row = by_name.get(symbol)
        if row is None:
            result[symbol] = {"present": False}
            continue
        flags = {}
        for key in ("trading", "visibility"):
            value = row.get(key)
            if not isinstance(value, str) or value not in {
                "all",
                "none",
                "restricted",
                "onlyClose",
            }:
                raise DiagnosticError("SCHEMA_INVALID")
            flags[key] = value
        result[symbol] = {"present": True, **flags}
    return result


def inspect_trades(payload: Any, symbol: str, captured_at: datetime) -> dict[str, Any]:
    if not isinstance(payload, list):
        raise DiagnosticError("SCHEMA_INVALID")
    timestamps = []
    seen = set()
    for row in payload:
        if not isinstance(row, dict) or row.get("instrument") != symbol:
            raise DiagnosticError("SCHEMA_INVALID")
        identity = row.get("executionId")
        if (
            not isinstance(identity, str)
            or not 0 < len(identity) <= 128
            or identity in seen
        ):
            raise DiagnosticError("SCHEMA_INVALID")
        seen.add(identity)
        positive(row.get("fillPrice"))
        positive(row.get("fillQuantity"))
        timestamp = row.get("createdAt")
        if not isinstance(timestamp, str) or len(timestamp) > 128:
            raise DiagnosticError("SCHEMA_INVALID")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            raise DiagnosticError("SCHEMA_INVALID") from None
        if parsed.tzinfo is None:
            raise DiagnosticError("SCHEMA_INVALID")
        timestamps.append(parsed.astimezone(UTC))
    if not timestamps:
        return {"count": 0, "state": "NO_RECENT_TRADES"}
    age = round((captured_at - max(timestamps)).total_seconds(), 6)
    return {
        "count": len(payload),
        "latest_trade_age_seconds": age,
        "state": "TRADES_OBSERVED",
        "freshness": "FUTURE" if age < -2 else ("STALE" if age > 300 else "RECENT"),
    }


def _boundaries() -> dict[str, Any]:
    return {
        "authenticated": False,
        "credentials_read": False,
        "order_count": 0,
        "transfer_count": 0,
        "wallet_signature_count": 0,
        "paid_api_calls": 0,
        "dev_configuration_changed": False,
        "primary_or_queue_changed": False,
        "sample_is_24h_evidence": False,
        "market_liquidity_qualified": False,
        "economic_validation": False,
        "paper_qualified": False,
        "alpha_ready": False,
        "live_ready": False,
        "trading_authority": False,
        "strategy_policy": "REJECT_ALL",
    }


def probe(
    run_dir: Path,
    *,
    source_hash: str,
    source_revision: str,
    fetcher: Callable[[str], Response] = http_get,
    source_check: Callable[[], None] = lambda: None,
    writer: Callable[[Path, Any], None] = exclusive_json,
) -> dict[str, Any]:
    started = time.monotonic()
    report: dict[str, Any] = {
        "schema": "kairos.evedex-demo-public-diagnostic.v1",
        "origin": ORIGIN,
        "environment": "DEMO",
        "support_ticket": "1013-20",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "source_sha256": source_hash,
        "source_revision": source_revision,
        "symbols": list(SYMBOLS),
        "unchanged_kairos_required_dev_symbols": list(KAIROS_REQUIRED_DEV_SYMBOLS),
        "max_calls": MAX_CALLS,
        "http_calls": 0,
        "requests": [],
        **_boundaries(),
    }
    for index, endpoint in enumerate(ENDPOINTS, 1):
        if time.monotonic() - started > MAX_RUN_SECONDS:
            raise DiagnosticError("RUN_BUDGET_EXHAUSTED")
        source_check()
        record: dict[str, Any] = {
            "path": endpoint.path,
            "kind": endpoint.kind,
            "symbol": endpoint.symbol,
            "variant": endpoint.variant,
            "method": "GET",
            "authenticated": False,
            "retry": False,
            "state": "RESERVED",
        }
        writer(run_dir / f"request-{index:02d}.reserved.json", record)
        report["http_calls"] += 1
        try:
            response = fetcher(endpoint.path)
            if type(response) is not Response or response.http_status != 200:
                raise DiagnosticError("HTTP_ERROR")
            record.update(
                {
                    "http_status": response.http_status,
                    "latency_ms": response.latency_ms,
                    "captured_at_utc": response.captured_at.isoformat(),
                    "body_sha256": hashlib.sha256(response.body).hexdigest(),
                }
            )
            payload = parse_json(response.body)
            if endpoint.kind == "depth":
                record["observation"] = inspect_book(payload, response.captured_at)
                # Only the exact numeric public depth schema may be retained raw.
                writer(run_dir / f"request-{index:02d}.public-depth.json", payload)
            elif endpoint.kind == "instruments":
                record["observation"] = inspect_instruments(payload)
            elif endpoint.kind == "trades":
                record["observation"] = inspect_trades(
                    payload, endpoint.symbol or "", response.captured_at
                )
            else:
                if not isinstance(payload, dict) or payload.get("state") not in {
                    "active",
                    "request-status-fail",
                    "me-dead",
                    "db-admin-dead",
                }:
                    raise DiagnosticError("SCHEMA_INVALID")
                record["observation"] = {"matcher_state": payload["state"]}
            record["state"] = "OBSERVED"
        except DiagnosticError as error:
            if str(error) not in {
                "HTTP_ERROR",
                "REDIRECT_BLOCKED",
                "TRANSPORT_UNKNOWN_NO_RETRY",
                "RESPONSE_TOO_LARGE",
                "JSON_INVALID",
                "DUPLICATE_JSON_KEY",
                "SCHEMA_INVALID",
            }:
                raise DiagnosticError("LOCAL_FAILURE") from None
            record.update({"state": "UNVERIFIED", "error_category": str(error)})
        except Exception:  # noqa: BLE001 - local failure cannot be mistaken for venue evidence.
            raise DiagnosticError("LOCAL_FAILURE") from None
        writer(run_dir / f"request-{index:02d}.result.json", record)
        report["requests"].append(record)
    source_check()
    report["ended_at_utc"] = datetime.now(UTC).isoformat()
    report["diagnostic_errors"] = sum(
        row["state"] == "UNVERIFIED" for row in report["requests"]
    )
    report["status"] = "DIAGNOSTIC_RECORDED_NOT_QUALIFIED"
    writer(run_dir / "report.json", report)
    return report


def run(*, authorize: bool) -> dict[str, Any]:
    if authorize is not True:
        raise DiagnosticError("AUTHORIZATION_REQUIRED")
    source_hash, revision = verify_source()
    _no_reparse(EVIDENCE_ROOT)
    _no_reparse(EVIDENCE_ROOT.parent)
    if not EVIDENCE_ROOT.is_dir():
        raise DiagnosticError("UNSAFE_LOCAL_PATH")
    # mkdir's exclusive daily reservation blocks concurrent/duplicate invocations.
    run_dir = EVIDENCE_ROOT / datetime.now(MOSCOW).strftime("%Y%m%d")
    try:
        run_dir.mkdir(exist_ok=False)
    except FileExistsError:
        raise DiagnosticError("DAY_ALREADY_RESERVED_NO_RETRY") from None
    exclusive_json(
        run_dir / "run.claim.json",
        {
            "source_sha256": source_hash,
            "source_revision": revision,
            "max_calls": MAX_CALLS,
            "automatic_retry": False,
            "symbols": list(SYMBOLS),
            **_boundaries(),
        },
    )

    def source_check() -> None:
        if (
            hashlib.sha256(_source_bytes()).hexdigest() != source_hash
            or _git("rev-parse", "HEAD").strip() != revision
        ):
            raise DiagnosticError("SOURCE_CHANGED")

    try:
        return probe(
            run_dir,
            source_hash=source_hash,
            source_revision=revision,
            source_check=source_check,
        )
    except Exception:  # noqa: BLE001 - retain a failed reservation without resuming/retrying it.
        exclusive_json(
            run_dir / "failure.json",
            {"status": "FAILED_CLOSED_NO_RETRY", **_boundaries()},
        )
        raise DiagnosticError("FAILED_CLOSED_NO_RETRY") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-public-demo-diagnostic", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute_public_demo_diagnostic:
        print(
            json.dumps(
                {
                    "status": "PLAN_ONLY",
                    "http_calls": 0,
                    "symbols": list(SYMBOLS),
                    **_boundaries(),
                }
            )
        )
        return 0
    try:
        result = run(authorize=True)
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in (
                        "status",
                        "http_calls",
                        "diagnostic_errors",
                        "source_revision",
                        "source_sha256",
                    )
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception:  # noqa: BLE001 - never print unsanitized driver or response details.
        print(json.dumps({"status": "FAILED_CLOSED_NO_RETRY", **_boundaries()}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
