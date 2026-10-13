"""One-shot, public-only EVEDEX DEV depth diagnostic; never a qualification gate.

This bounded diagnostic compares three fixed public depth query variants for five
DEV instruments. It is intentionally not an authenticated feed, health guarantee,
trading signal, readiness gate, or 24-hour evidence source. A stopped reservation
is never resumed or retried; every later invocation must create a new UUID run.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import ssl
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

KAIROS_ROOT = Path("D:/Kairos/kairos")
RUNTIME_ROOT = Path("D:/Kairos/runtime/evedex-depth-diagnostic-20261013")
ORIGIN = "https://trading-api.evedex.tech"
META_SIGNER = "40AF365C6682B73D056A6A274DBFF6B65BE9F827"
SOURCE_RELATIVE = "development/ops_alerts/evedex_dev_depth_diagnostic.py"
PREFLIGHT_RELATIVE = "development/ops_alerts/evedex_dev_public_preflight.py"
MAX_REQUESTS = 17
REQUEST_TIMEOUT_S = 15
MAX_RESPONSE_BYTES = 256 * 1024
MAX_BOOK_AGE_S = 5.0
MAX_FUTURE_SKEW_S = 2.0

SYMBOLS = ("BTCUSD:DEV", "ETHUSD:DEV", "SOLUSD:DEV", "BNBUSD:DEV", "XRPUSD:DEV")
VARIANTS = (
    ("default", ""),
    ("documented_market_level_1", "?marketLevel=1"),
    # Describes the parameter combination only; it does not prove it matches a
    # particular published SDK artifact or its exact version.
    ("sdk_style_round_price_max_level", "?roundPrice=0.1&maxLevel=30"),
)


class DiagnosticError(Exception):
    """A fixed, non-sensitive category; never includes paths or raw exceptions."""

    def __init__(self, category: str, *, http_calls: int = 0) -> None:
        allowed = {
            "LOCAL_VALIDATION_FAILED",
            "TLS_OR_TRANSPORT_ERROR",
            "REDIRECT_BLOCKED",
            "HTTP_ERROR",
            "OVERSIZED_RESPONSE",
            "INVALID_JSON",
            "DUPLICATE_JSON_KEY",
        }
        super().__init__(category if category in allowed else "LOCAL_VALIDATION_FAILED")
        self.category = str(self)
        self.http_calls = http_calls


@dataclass(frozen=True)
class Endpoint:
    label: str
    path: str
    symbol: str | None = None
    variant: str | None = None


@dataclass(frozen=True)
class PublicResponse:
    status: int
    latency_ms: float
    body: bytes
    captured_at: datetime
    error_category: str | None = None


def _endpoint_table() -> tuple[Endpoint, ...]:
    rows = [
        Endpoint("market", "/api/market"),
        Endpoint("instruments", "/api/market/instrument"),
    ]
    for symbol in SYMBOLS:
        for variant, query in VARIANTS:
            label_symbol = symbol.replace(":", "_")
            rows.append(
                Endpoint(
                    f"depth_{label_symbol}_{variant}",
                    f"/api/market/{symbol}/deep{query}",
                    symbol,
                    variant,
                )
            )
    if len(rows) != MAX_REQUESTS or len({row.path for row in rows}) != MAX_REQUESTS:
        raise DiagnosticError("LOCAL_VALIDATION_FAILED")
    return tuple(rows)


ENDPOINTS = _endpoint_table()
_PATHS = frozenset(endpoint.path for endpoint in ENDPOINTS)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _request_url(path: str) -> str:
    if type(path) is not str or path not in _PATHS:
        raise DiagnosticError("LOCAL_VALIDATION_FAILED")
    url = ORIGIN + path
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "trading-api.evedex.tech"
        or parsed.port
    ):
        raise DiagnosticError("LOCAL_VALIDATION_FAILED")
    return url


def _http_get(path: str) -> PublicResponse:
    """Make exactly one fixed-origin anonymous GET with strict TLS and bounded body."""
    url = _request_url(path)
    request = urllib.request.Request(
        url, method="GET", headers={"Accept": "application/json"}
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    started = time.monotonic()
    try:
        response = opener.open(request, timeout=REQUEST_TIMEOUT_S)
    except urllib.error.HTTPError as error:
        category = "REDIRECT_BLOCKED" if 300 <= error.code < 400 else "HTTP_ERROR"
        try:
            body = error.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise DiagnosticError("OVERSIZED_RESPONSE") from None
            return PublicResponse(
                int(error.code),
                (time.monotonic() - started) * 1000,
                body,
                datetime.now(UTC),
                category,
            )
        finally:
            error.close()
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError):
        raise DiagnosticError("TLS_OR_TRANSPORT_ERROR") from None
    try:
        if response.geturl() != url:
            raise DiagnosticError("REDIRECT_BLOCKED")
        length = response.headers.get("Content-Length")
        if length is not None and length.isdigit() and int(length) > MAX_RESPONSE_BYTES:
            raise DiagnosticError("OVERSIZED_RESPONSE")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise DiagnosticError("OVERSIZED_RESPONSE")
        return PublicResponse(
            int(response.status),
            (time.monotonic() - started) * 1000,
            body,
            datetime.now(UTC),
            None if response.status == 200 else "HTTP_ERROR",
        )
    finally:
        response.close()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DiagnosticError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _parse_json(body: bytes) -> Any:
    try:
        return json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except DiagnosticError:
        raise
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise DiagnosticError("INVALID_JSON") from None


def _positive_number(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError
    if isinstance(value, str):
        if (
            len(value) > 128
            or value != value.strip()
            or re.fullmatch(
                r"-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value
            )
            is None
        ):
            raise ValueError
    elif not isinstance(value, (int, float)):
        raise TypeError
    try:
        number = float(value)
    except (ValueError, OverflowError):
        raise ValueError from None
    if not math.isfinite(number) or number <= 0:
        raise ValueError
    return number


def _timestamp_ms(value: Any) -> float:
    # Exchange book DTO timestamp is milliseconds since epoch; retain zero separately.
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise TypeError
    if isinstance(value, str) and (value != value.strip() or len(value) > 128):
        raise ValueError
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise ValueError from None
    if not math.isfinite(result) or result <= 0:
        raise ValueError
    return result


def _timestamp_iso(value: Any) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError from None
    if parsed.tzinfo is None:
        raise ValueError
    return parsed.astimezone(UTC)


def _inspect_book(payload: Any, *, captured_at: datetime) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"bids", "asks", "t"}:
        return {"state": "SCHEMA_ERROR", "reason": "depth_schema_invalid"}
    bids, asks = payload["bids"], payload["asks"]
    if not isinstance(bids, list) or not isinstance(asks, list):
        return {"state": "SCHEMA_ERROR", "reason": "depth_schema_invalid"}
    try:
        stamp = _timestamp_ms(payload["t"])
        age = captured_at.timestamp() - stamp / 1000.0
        freshness = (
            "FUTURE"
            if age < -MAX_FUTURE_SKEW_S
            else ("STALE" if age > MAX_BOOK_AGE_S else "FRESH")
        )
        parsed_sides: list[list[float]] = []
        for side in (bids, asks):
            prices: set[float] = set()
            ordered: list[float] = []
            for level in side:
                if not isinstance(level, dict) or set(level) != {"price", "quantity"}:
                    raise TypeError
                price = _positive_number(level["price"])
                _positive_number(level["quantity"])
                if price in prices:
                    raise TypeError
                prices.add(price)
                ordered.append(price)
            parsed_sides.append(ordered)
        age_report = max(0.0, age) if math.isfinite(age) else None
    except (KeyError, TypeError, ValueError):
        return {"state": "SCHEMA_ERROR", "reason": "depth_level_or_timestamp_invalid"}
    if not bids and not asks:
        return {
            "state": "EMPTY_BOOK",
            "reason": "both_sides_empty",
            "timestamp_ms": stamp,
            "age_seconds": age_report,
            "freshness": freshness,
        }
    if not bids or not asks:
        return {
            "state": "PARTIAL_BOOK",
            "reason": "one_sided_book",
            "timestamp_ms": stamp,
            "age_seconds": age_report,
            "freshness": freshness,
        }
    bid_prices, ask_prices = parsed_sides
    if bid_prices != sorted(bid_prices, reverse=True):
        return {
            "state": "NON_EXECUTABLE",
            "reason": "bid_order_invalid",
            "timestamp_ms": stamp,
            "age_seconds": age_report,
            "freshness": freshness,
        }
    if ask_prices != sorted(ask_prices):
        return {
            "state": "NON_EXECUTABLE",
            "reason": "ask_order_invalid",
            "timestamp_ms": stamp,
            "age_seconds": age_report,
            "freshness": freshness,
        }
    if bid_prices[0] >= ask_prices[0]:
        return {
            "state": "NON_EXECUTABLE",
            "reason": "book_crossed",
            "timestamp_ms": stamp,
            "age_seconds": age_report,
            "freshness": freshness,
        }
    return {
        "state": "TWO_SIDED_BOOK",
        "reason": None,
        "bid_levels": len(bids),
        "ask_levels": len(asks),
        "timestamp_ms": stamp,
        "age_seconds": age_report,
        "freshness": freshness,
    }


def _instrument_index(payload: Any) -> tuple[dict[str, dict[str, Any]], str | None]:
    if not isinstance(payload, list):
        return {}, "instrument_schema_invalid"
    result: dict[str, dict[str, Any]] = {}
    for row in payload:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("name"), str)
            or not row["name"]
        ):
            return {}, "instrument_identity_invalid"
        key = row["name"].upper()
        if key in result:
            return {}, "duplicate_instrument_identity"
        result[key] = row
    return result, None


def _flag_status(value: Any) -> str:
    if not isinstance(value, str):
        return "UNSUPPORTED"
    return {
        "all": "ALL",
        "none": "NONE",
        "restricted": "RESTRICTED",
        "onlyClose": "ONLY_CLOSE",
    }.get(value, "UNSUPPORTED")


def _instrument_observation(
    item: dict[str, Any] | None,
) -> tuple[dict[str, str], str | None]:
    """Validate only the selected instrument, without discarding other identities."""
    if item is None:
        return {
            "trading": "UNAVAILABLE",
            "visibility": "UNAVAILABLE",
            "raw_last_price": "UNAVAILABLE",
            "mark_price": "UNAVAILABLE",
        }, "instrument_missing"
    required = {
        "name",
        "trading",
        "visibility",
        "lastPrice",
        "markPrice",
        "minQuantity",
        "maxQuantity",
        "quantityIncrement",
        "priceIncrement",
    }
    if not required.issubset(item):
        return {
            "trading": _flag_status(item.get("trading")),
            "visibility": _flag_status(item.get("visibility")),
            "raw_last_price": _price_status(item.get("lastPrice")),
            "mark_price": _price_status(item.get("markPrice")),
        }, "instrument_schema_invalid"
    flags = {
        "trading": _flag_status(item["trading"]),
        "visibility": _flag_status(item["visibility"]),
        "raw_last_price": _price_status(item["lastPrice"]),
        "mark_price": _price_status(item["markPrice"]),
    }
    if flags["trading"] == "UNSUPPORTED" or flags["visibility"] not in {
        "ALL",
        "NONE",
        "RESTRICTED",
    }:
        return flags, "instrument_flag_invalid"
    if flags["raw_last_price"] == "INVALID" or flags["mark_price"] == "INVALID":
        return flags, "instrument_price_invalid"
    try:
        minimum = _positive_number(item["minQuantity"])
        maximum = _positive_number(item["maxQuantity"])
        _positive_number(item["quantityIncrement"])
        _positive_number(item["priceIncrement"])
    except (TypeError, ValueError):
        return flags, "instrument_numeric_rule_invalid"
    if minimum > maximum:
        return flags, "instrument_quantity_range_invalid"
    return flags, None


def _price_status(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return "INVALID"
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return "INVALID"
    if not math.isfinite(result):
        return "INVALID"
    if result == 0:
        return "ZERO"
    return "POSITIVE" if result > 0 else "INVALID"


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        + b"\n"
    )


def _exclusive_write(
    path: Path, payload: bytes, continuation: Any, delivery: Any
) -> None:
    continuation._exclusive_fsync(path, payload)
    continuation._set_exact_file_acl(path)
    delivery._private_acl(path)


def _write_new_directory(path: Path, *, delivery: Any) -> None:
    path.mkdir(exist_ok=False)
    delivery._no_reparse(path)
    delivery._private_acl(path)


def _regular_source_bytes(path: Path, maximum: int = 512 * 1024) -> bytes:
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or path.is_symlink()
        or getattr(before, "st_file_attributes", 0) & 0x400
        or not 0 < before.st_size <= maximum
    ):
        raise DiagnosticError("LOCAL_VALIDATION_FAILED")
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise DiagnosticError("LOCAL_VALIDATION_FAILED")
        payload = stream.read(maximum + 1)
    if len(payload) != before.st_size or len(payload) > maximum:
        raise DiagnosticError("LOCAL_VALIDATION_FAILED")
    return payload


def _git_run(
    root: Path,
    args: list[str],
    *,
    binary: bool = False,
    run: Callable[..., Any] = subprocess.run,
) -> Any:
    git = Path("C:/Program Files/Git/cmd/git.exe")
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
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
        }
    )
    try:
        return run(
            [str(git), "-C", str(root), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=not binary,
            timeout=20,
            check=False,
            env=env,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise DiagnosticError("LOCAL_VALIDATION_FAILED") from None


def _verify_own_source(
    root: Path = KAIROS_ROOT, *, run: Callable[..., Any] = subprocess.run
) -> tuple[bytes, str]:
    """Require signed main==origin/main and exact committed bytes for this source."""
    if root != KAIROS_ROOT:
        raise DiagnosticError("LOCAL_VALIDATION_FAILED")
    head = _git_run(root, ["show", "-s", "--format=%H %G? %GF", "HEAD"], run=run)
    head_id = _git_run(root, ["rev-parse", "HEAD"], run=run)
    origin = _git_run(root, ["rev-parse", "refs/remotes/origin/main"], run=run)
    branch = _git_run(root, ["branch", "--show-current"], run=run)
    status = _git_run(
        root,
        ["status", "--porcelain", "--untracked-files=all", "--", SOURCE_RELATIVE],
        run=run,
    )
    committed = _git_run(
        root, ["show", f"HEAD:{SOURCE_RELATIVE}"], binary=True, run=run
    )
    parts = head.stdout.split() if head.returncode == 0 else []
    if (
        len(parts) != 3
        or parts[1:] != ["G", META_SIGNER]
        or len(parts[0]) != 40
        or head_id.returncode
        or origin.returncode
        or head_id.stdout.strip() != parts[0]
        or origin.stdout.strip() != parts[0]
        or branch.returncode
        or branch.stdout.strip() != "main"
        or status.returncode
        or status.stdout.strip()
        or committed.returncode
    ):
        raise DiagnosticError("LOCAL_VALIDATION_FAILED")
    path = root / SOURCE_RELATIVE
    current = _regular_source_bytes(path)
    if current != committed.stdout:
        raise DiagnosticError("LOCAL_VALIDATION_FAILED")
    return current, hashlib.sha256(current).hexdigest()


def _load_preflight(root: Path, source_bytes: bytes) -> Any:
    """Load only the committed sampler bytes after the caller has admitted signed main."""
    committed = _git_run(root, ["show", f"HEAD:{PREFLIGHT_RELATIVE}"], binary=True)
    local = _regular_source_bytes(root / PREFLIGHT_RELATIVE)
    if committed.returncode or local != committed.stdout:
        raise DiagnosticError("LOCAL_VALIDATION_FAILED")
    digest = hashlib.sha256(local).hexdigest()
    name = "_kairos_verified_evedex_public_preflight"
    spec = importlib.util.spec_from_file_location(name, root / PREFLIGHT_RELATIVE)
    if spec is None or spec.loader is None:
        raise DiagnosticError("LOCAL_VALIDATION_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        exec(  # noqa: S102 - execute only exact sampler bytes matched to signed current HEAD.
            compile(local, str(root / PREFLIGHT_RELATIVE), "exec", dont_inherit=True),
            module.__dict__,
        )
    except Exception:  # noqa: BLE001 - fail closed and hide import/path diagnostics.
        sys.modules.pop(name, None)
        raise DiagnosticError("LOCAL_VALIDATION_FAILED") from None
    if (
        hashlib.sha256(_regular_source_bytes(root / PREFLIGHT_RELATIVE)).hexdigest()
        != digest
    ):
        sys.modules.pop(name, None)
        raise DiagnosticError("LOCAL_VALIDATION_FAILED")
    # Re-check our own admission after module import and before authenticated helpers are used.
    if _regular_source_bytes(root / SOURCE_RELATIVE) != source_bytes:
        raise DiagnosticError("LOCAL_VALIDATION_FAILED")
    return module


def _safe_request_record(endpoint: Endpoint, source_hash: str) -> dict[str, Any]:
    return {
        "endpoint": endpoint.label,
        "request_sha256": hashlib.sha256((ORIGIN + endpoint.path).encode()).hexdigest(),
        "implementation_sha256": source_hash,
        "automatic_retry": False,
    }


def _probe_all(
    *,
    run_dir: Path,
    source_hash: str,
    continuation: Any,
    delivery: Any,
    fetcher: Callable[[str], PublicResponse],
    clock: Callable[[], datetime],
    writer: Callable[[Path, bytes, Any, Any], None] = _exclusive_write,
    source_check: Callable[[], None] = lambda: None,
) -> dict[str, Any]:
    requests_dir, raw_dir = run_dir / "requests", run_dir / "public-json"
    _write_new_directory(requests_dir, delivery=delivery)
    _write_new_directory(raw_dir, delivery=delivery)
    responses: dict[str, tuple[Any, PublicResponse | None, str | None]] = {}
    calls = 0
    for index, endpoint in enumerate(ENDPOINTS, start=1):
        stem = f"{index:02d}-{endpoint.label}"
        base = _safe_request_record(endpoint, source_hash)
        try:
            writer(
                requests_dir / f"{stem}.reserved.json",
                _json_bytes(
                    {
                        **base,
                        "schema": "evedex-public-get-reserved-v1",
                        "reserved_at_utc": clock().astimezone(UTC).isoformat(),
                    }
                ),
                continuation,
                delivery,
            )
        except Exception:  # noqa: BLE001 - persistence failure stops before any request.
            raise DiagnosticError("LOCAL_VALIDATION_FAILED", http_calls=calls) from None
        # The immutable reservation is durable before the one and only fetch attempt.
        source_check()
        calls += 1
        response: PublicResponse | None = None
        category: str | None = None
        payload: Any = None
        status: int | None = None
        try:
            response = fetcher(endpoint.path)
            if type(response) is not PublicResponse:
                raise DiagnosticError("LOCAL_VALIDATION_FAILED", http_calls=calls)
            status = response.status
            if len(response.body) > MAX_RESPONSE_BYTES:
                category = "OVERSIZED_RESPONSE"
            elif response.error_category is not None:
                category = response.error_category
            elif response.status != 200:
                category = "HTTP_ERROR"
            else:
                payload = _parse_json(response.body)
        except DiagnosticError as error:
            if error.category == "LOCAL_VALIDATION_FAILED":
                raise DiagnosticError(error.category, http_calls=calls) from None
            category = error.category
        except Exception:  # noqa: BLE001 - collapse unknown transport details to a safe category.
            category = "TLS_OR_TRANSPORT_ERROR"
        if response is not None and len(response.body) <= MAX_RESPONSE_BYTES:
            try:
                writer(raw_dir / f"{stem}.json", response.body, continuation, delivery)
            except Exception:  # noqa: BLE001 - persistence failure stops later requests.
                raise DiagnosticError(
                    "LOCAL_VALIDATION_FAILED", http_calls=calls
                ) from None
        captured = (
            response.captured_at if response is not None else clock().astimezone(UTC)
        )
        latency = response.latency_ms if response is not None else 0.0
        result = {
            **base,
            "schema": "evedex-public-get-result-v1",
            "captured_at_utc": captured.astimezone(UTC).isoformat(),
            "http_status": status,
            "latency_ms": max(0.0, latency) if math.isfinite(latency) else None,
            "response_sha256": hashlib.sha256(response.body).hexdigest()
            if response is not None
            else None,
            "response_bytes": len(response.body) if response is not None else None,
            "error_category": category,
            "automatic_retry": False,
        }
        try:
            writer(
                requests_dir / f"{stem}.result.json",
                _json_bytes(result),
                continuation,
                delivery,
            )
        except Exception:  # noqa: BLE001 - persistence failure stops later requests.
            raise DiagnosticError("LOCAL_VALIDATION_FAILED", http_calls=calls) from None
        responses[endpoint.label] = (payload, response, category)

    market, market_response, market_error = responses["market"]
    market_state = "UNVERIFIED"
    market_age: float | None = None
    market_freshness = "UNVERIFIED"
    if (
        market_error is None
        and isinstance(market, dict)
        and market_response is not None
    ):
        if not {"state", "updatedAt"}.issubset(market):
            market_state = "SCHEMA_ERROR"
        else:
            try:
                updated = _timestamp_iso(market["updatedAt"])
                market_age_value = (
                    market_response.captured_at.astimezone(UTC).timestamp()
                    - updated.timestamp()
                )
                market_age = max(0.0, market_age_value)
                market_freshness = (
                    "FUTURE"
                    if market_age_value < -MAX_FUTURE_SKEW_S
                    else ("STALE" if market_age_value > MAX_BOOK_AGE_S else "FRESH")
                )
                market_state = (
                    "ACTIVE"
                    if market.get("state") == "active"
                    else "INACTIVE_OR_UNSUPPORTED"
                )
            except (TypeError, ValueError, OverflowError):
                market_state = "SCHEMA_ERROR"
    instruments_payload, _, instrument_error = responses["instruments"]
    instrument_map, instrument_issue = (
        _instrument_index(instruments_payload)
        if instrument_error is None
        else ({}, "instrument_response_unavailable")
    )
    symbols: dict[str, Any] = {}
    counts = {
        "empty": 0,
        "partial": 0,
        "valid": 0,
        "non_executable": 0,
        "schema_error": 0,
        "unavailable": 0,
        "by_variant": {
            variant: {
                "empty": 0,
                "partial": 0,
                "valid": 0,
                "non_executable": 0,
                "schema_error": 0,
                "unavailable": 0,
            }
            for variant, _query in VARIANTS
        },
    }
    instrument_issues: dict[str, str] = {}
    for symbol in SYMBOLS:
        item = instrument_map.get(symbol) or instrument_map.get(symbol.upper())
        flags, metadata_issue = _instrument_observation(item)
        if metadata_issue:
            instrument_issues[symbol] = metadata_issue
        books: dict[str, Any] = {}
        for variant, _query in VARIANTS:
            endpoint = next(
                row
                for row in ENDPOINTS
                if row.symbol == symbol and row.variant == variant
            )
            payload, response, error = responses[endpoint.label]
            if error is not None or response is None:
                result = {"state": "UNAVAILABLE", "reason": error or "no_response"}
                counts["unavailable"] += 1
                counts["by_variant"][variant]["unavailable"] += 1
            else:
                result = _inspect_book(payload, captured_at=response.captured_at)
                bucket = {
                    "EMPTY_BOOK": "empty",
                    "PARTIAL_BOOK": "partial",
                    "TWO_SIDED_BOOK": "valid",
                    "NON_EXECUTABLE": "non_executable",
                }.get(result["state"], "schema_error")
                counts[bucket] += 1
                counts["by_variant"][variant][bucket] += 1
            books[variant] = result
        symbols[symbol] = {**flags, "depth": books}
    instrument_issue = instrument_issue or (
        "target_metadata_invalid" if instrument_issues else None
    )
    report = {
        "schema": "evedex-dev-depth-diagnostic-v1",
        "status": "DIAGNOSIS_RECORDED",
        "captured_at_utc": clock().astimezone(UTC).isoformat(),
        "origin": ORIGIN,
        "request_count": len(ENDPOINTS),
        "max_requests": MAX_REQUESTS,
        "timeout_seconds": REQUEST_TIMEOUT_S,
        "maximum_response_bytes": MAX_RESPONSE_BYTES,
        "market_status": market_state,
        "market_age_seconds": market_age,
        "market_freshness": market_freshness,
        "instrument_status": "VALID" if instrument_issue is None else "UNVERIFIED",
        "instrument_issue": instrument_issue,
        "instrument_issues": instrument_issues,
        "symbols": symbols,
        "book_counts": counts,
        "implementation_sha256": source_hash,
        "authenticated": False,
        "trading_authority": False,
        "sample_is_24h_evidence": False,
        "paper_qualified": False,
        "automatic_retry": False,
    }
    try:
        writer(run_dir / "report.json", _json_bytes(report), continuation, delivery)
    except Exception:  # noqa: BLE001 - persistence failure stops the diagnostic.
        raise DiagnosticError("LOCAL_VALIDATION_FAILED", http_calls=calls) from None
    return report


def _run_diagnostic(
    *,
    authorize: bool,
    root: Path = RUNTIME_ROOT,
    source_root: Path = KAIROS_ROOT,
    fetcher: Callable[[str], PublicResponse] = _http_get,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    make_uuid: Callable[[], str] = lambda: str(uuid.uuid4()),
    pin_loader: Callable[[Path, bytes], Any] | None = None,
    writer: Callable[[Path, bytes, Any, Any], None] = _exclusive_write,
    source_admitter: Callable[[Path], tuple[bytes, str]] = _verify_own_source,
) -> dict[str, Any]:
    calls = [0]
    try:
        if authorize is not True or root != RUNTIME_ROOT or source_root != KAIROS_ROOT:
            raise DiagnosticError("LOCAL_VALIDATION_FAILED")
        source_bytes, source_hash = source_admitter(source_root)
        preflight = (
            pin_loader(source_root, source_bytes)
            if pin_loader
            else _load_preflight(source_root, source_bytes)
        )
        continuation, delivery, provisioner = preflight._verify_pins(source_root)
        delivery._no_reparse(root.parent)
        if root.exists():
            delivery._no_reparse(root)
            delivery._private_acl(root)
        else:
            root.mkdir()
            delivery._no_reparse(root)
            if any(root.iterdir()):
                raise DiagnosticError("LOCAL_VALIDATION_FAILED")
            provisioner.harden_permissions(root)
            delivery._private_acl(root)
        now = clock().astimezone(UTC)
        suffix = make_uuid()
        try:
            if str(uuid.UUID(suffix)) != suffix.lower():
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise DiagnosticError("LOCAL_VALIDATION_FAILED") from None
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        run_dir = root / f"sample-{stamp}-{suffix}"
        if run_dir.exists():
            raise DiagnosticError("LOCAL_VALIDATION_FAILED")
        _write_new_directory(run_dir, delivery=delivery)

        def source_check() -> None:
            current, digest = source_admitter(source_root)
            if current != source_bytes or digest != source_hash:
                raise DiagnosticError("LOCAL_VALIDATION_FAILED")

        def counted_fetch(path: str) -> PublicResponse:
            calls[0] += 1
            return fetcher(path)

        return _probe_all(
            run_dir=run_dir,
            source_hash=source_hash,
            continuation=continuation,
            delivery=delivery,
            fetcher=counted_fetch,
            clock=clock,
            writer=writer,
            source_check=source_check,
        )
    except DiagnosticError as error:
        count = max(calls[0], error.http_calls)
        raise DiagnosticError(error.category, http_calls=count) from None
    except Exception:  # noqa: BLE001 - hide unexpected local details; fail closed.
        raise DiagnosticError("LOCAL_VALIDATION_FAILED", http_calls=calls[0]) from None


def run_public_depth_diagnostic(*, authorize: bool) -> dict[str, Any]:
    """Run only after signed-source, origin, helper-provenance, and private-root gates pass."""
    return _run_diagnostic(authorize=authorize)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-public-depth-diagnostic", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute_public_depth_diagnostic:
        print(
            json.dumps(
                {
                    "status": "PLAN_ONLY",
                    "http_calls": 0,
                    "authenticated": False,
                    "trading_authority": False,
                }
            )
        )
        return 0
    try:
        report = run_public_depth_diagnostic(authorize=True)
    except DiagnosticError as error:
        report = {
            "status": "BLOCKED",
            "error_category": error.category,
            "http_calls": error.http_calls,
            "authenticated": False,
            "trading_authority": False,
            "sample_is_24h_evidence": False,
        }
    except Exception:  # noqa: BLE001 - never expose unexpected exception details.
        report = {
            "status": "BLOCKED",
            "error_category": "LOCAL_VALIDATION_FAILED",
            "http_calls": None,
            "authenticated": False,
            "trading_authority": False,
            "sample_is_24h_evidence": False,
        }
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report.get("status") == "DIAGNOSIS_RECORDED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
