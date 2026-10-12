"""Bounded, public-only EVEDEX DEV snapshot sampler; never a qualification gate."""

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
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

KAIROS_ROOT = Path("D:/Kairos/kairos")
RUNTIME_ROOT = Path("D:/Kairos/runtime/evedex-dev-preflight-20261012")
ORIGIN = "https://trading-api.evedex.tech"
META_SIGNER = "40AF365C6682B73D056A6A274DBFF6B65BE9F827"
CONTINUATION_COMMIT = "f7b2f249c028a4a947b7279e677f21ee85bee8fc"
CONTINUATION_SHA256 = "b308e19753be088966e3fed4d1ddacc47ca3ef8d90089d1c527d1c93813d3930"
CONTINUATION_RELATIVE = "development/ops_alerts/telegram_continuation.py"
PROVISION_RELATIVE = "scripts/provision_secrets.py"
PROVISION_SHA256 = "c24fd03888b09869eb0110ce9d2ad244ab8f4cf1e307a05a213bf514747223bc"
SOURCE_RELATIVE = "development/ops_alerts/evedex_dev_public_preflight.py"
SCOPED_STATUS_PATHS = (SOURCE_RELATIVE, CONTINUATION_RELATIVE)
MAX_REQUESTS = 12
REQUEST_TIMEOUT_S = 15
MAX_RESPONSE_BYTES = 256 * 1024
BOOK_MAX_AGE_S = 5.0
MAX_FUTURE_SKEW_S = 2.0
MAX_SPREAD_BPS = 25.0
TRADE_MAX_AGE_S = 300.0

SYMBOLS = (
    ("BTCUSDT", "BTCUSD:DEV"),
    ("ETHUSDT", "ETHUSD:DEV"),
    ("SOLUSDT", "SOLUSD:DEV"),
    ("BNBUSDT", "BNBUSD:DEV"),
    ("XRPUSDT", "XRPUSD:DEV"),
)


class SamplerError(Exception):
    """Only fixed public categories are surfaced."""

    def __init__(
        self,
        category: str,
        *,
        http_status: int | None = None,
        http_calls: int = 0,
    ) -> None:
        super().__init__(category if category in _ERRORS else "LOCAL_VALIDATION_FAILED")
        self.category = str(self)
        self.http_status = http_status
        self.http_calls = http_calls


_ERRORS = {
    "DUPLICATE_JSON_KEY",
    "HTTP_ERROR",
    "INVALID_JSON",
    "LOCAL_VALIDATION_FAILED",
    "OVERSIZED_RESPONSE",
    "REDIRECT_BLOCKED",
    "TLS_OR_TRANSPORT_ERROR",
}


@dataclass(frozen=True)
class PublicResponse:
    status: int
    latency_ms: float
    body: bytes
    captured_at: datetime
    error_category: str | None = None


@dataclass(frozen=True)
class Endpoint:
    label: str
    path: str


def _endpoint_table() -> tuple[Endpoint, ...]:
    rows = [
        Endpoint("market", "/api/market"),
        Endpoint("instruments", "/api/market/instrument"),
    ]
    for _, symbol in SYMBOLS:
        rows.extend(
            (
                Endpoint(
                    f"depth_{symbol.replace(':', '_')}",
                    f"/api/market/{symbol}/deep?marketLevel=1",
                ),
                Endpoint(
                    f"trades_{symbol.replace(':', '_')}",
                    f"/api/market/{symbol}/recent-trades",
                ),
            )
        )
    if len(rows) != MAX_REQUESTS or len({row.label for row in rows}) != MAX_REQUESTS:
        raise SamplerError("LOCAL_VALIDATION_FAILED")
    return tuple(rows)


ENDPOINTS = _endpoint_table()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _request_url(path: str) -> str:
    if not isinstance(path, str) or path not in {item.path for item in ENDPOINTS}:
        raise SamplerError("LOCAL_VALIDATION_FAILED")
    url = ORIGIN + path
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "trading-api.evedex.tech"
        or parsed.port
    ):
        raise SamplerError("LOCAL_VALIDATION_FAILED")
    return url


def _http_get(path: str) -> PublicResponse:
    """One fixed-origin GET; proxies, redirects, retries and auth are disabled."""
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
    captured = datetime.now(UTC)
    try:
        response = opener.open(request, timeout=REQUEST_TIMEOUT_S)
    except urllib.error.HTTPError as error:
        category = "REDIRECT_BLOCKED" if 300 <= error.code < 400 else "HTTP_ERROR"
        try:
            return PublicResponse(
                status=int(error.code),
                latency_ms=(time.monotonic() - started) * 1000,
                body=b"",
                captured_at=datetime.now(UTC),
                error_category=category,
            )
        finally:
            error.close()
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError):
        raise SamplerError("TLS_OR_TRANSPORT_ERROR") from None
    try:
        if response.geturl() != url:
            raise SamplerError("REDIRECT_BLOCKED")
        content_length = response.headers.get("Content-Length")
        if (
            content_length is not None
            and content_length.isdigit()
            and int(content_length) > MAX_RESPONSE_BYTES
        ):
            raise SamplerError("OVERSIZED_RESPONSE")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise SamplerError("OVERSIZED_RESPONSE", http_status=int(response.status))
        captured = datetime.now(UTC)
        return PublicResponse(
            status=int(response.status),
            latency_ms=(time.monotonic() - started) * 1000,
            body=body,
            captured_at=captured,
        )
    finally:
        response.close()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SamplerError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _parse_json(body: bytes) -> Any:
    try:
        return json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except SamplerError:
        raise
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise SamplerError("INVALID_JSON") from None


def _number(value: Any) -> float:
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
            raise TypeError
    elif not isinstance(value, (int, float)):
        raise TypeError
    try:
        parsed = float(value)
    except (ValueError, OverflowError):
        raise ValueError from None
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError
    return parsed


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError from None
    if parsed.tzinfo is None:
        raise ValueError
    return parsed.astimezone(UTC)


def _duplicate_safe_instruments(
    payload: Any,
) -> tuple[dict[str, dict[str, Any]], str | None]:
    if not isinstance(payload, list):
        return {}, "instrument_list_invalid"
    by_name: dict[str, dict[str, Any]] = {}
    try:
        for row in payload:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("name"), str)
                or not row["name"]
            ):
                return {}, "instrument_identity_invalid"
            name = row["name"].upper()
            if name in by_name:
                return {}, "duplicate_instrument_identity"
            by_name[name] = row
        for logical, symbol in SYMBOLS:
            item = by_name.get(symbol)
            if item is None:
                return {}, "instrument_missing"
            if item.get("trading") != "all" or item.get("visibility") != "all":
                return {}, "instrument_not_fully_enabled"
            values = [
                _number(item.get(field))
                for field in (
                    "lastPrice",
                    "markPrice",
                    "minQuantity",
                    "maxQuantity",
                    "quantityIncrement",
                    "priceIncrement",
                )
            ]
            if values[2] > values[3]:
                return {}, "instrument_quantity_range_invalid"
    except (KeyError, ValueError, TypeError):
        return {}, "instrument_numeric_rule_invalid"
    return by_name, None


def _validate_book(
    payload: Any, *, venue: str, captured_at: datetime
) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"bids", "asks", "t"}:
        raise ValueError("depth_schema_invalid")
    sides: dict[str, list[tuple[float, float]]] = {}
    for side in ("bids", "asks"):
        levels = payload[side]
        if not isinstance(levels, list) or not levels:
            raise ValueError("depth_empty")
        parsed: list[tuple[float, float]] = []
        for level in levels:
            if not isinstance(level, dict) or set(level) != {"price", "quantity"}:
                raise ValueError("depth_level_schema_invalid")
            parsed.append((_number(level["price"]), _number(level["quantity"])))
        prices = [price for price, _ in parsed]
        if len(prices) != len(set(prices)):
            raise ValueError("depth_duplicate_price_level")
        expected = sorted(parsed, key=lambda row: row[0], reverse=(side == "bids"))
        if parsed != expected:
            raise ValueError("depth_order_invalid")
        sides[side] = parsed
    timestamp_ms = _number(payload["t"])
    age = captured_at.timestamp() - timestamp_ms / 1000
    if age < -MAX_FUTURE_SKEW_S:
        raise ValueError("depth_from_future")
    if age > BOOK_MAX_AGE_S:
        raise ValueError("depth_stale")
    bid, bid_qty = sides["bids"][0]
    ask, ask_qty = sides["asks"][0]
    if bid >= ask:
        raise ValueError("depth_crossed")
    spread = (ask - bid) / ((ask + bid) / 2) * 10_000
    if spread > MAX_SPREAD_BPS:
        raise ValueError("spread_above_one_shot_limit")
    return {
        "state": "FRESH_VALID",
        "venue_symbol": venue,
        "bid": bid,
        "bid_quantity": bid_qty,
        "ask": ask,
        "ask_quantity": ask_qty,
        "spread_bps": spread,
        "book_age_seconds": max(age, 0.0),
        "depth_timestamp_ms": timestamp_ms,
    }


def _validate_trades(
    payload: Any, *, venue: str, captured_at: datetime
) -> dict[str, Any]:
    if not isinstance(payload, list):
        return {"state": "UNVERIFIED", "reason": "trade_list_invalid", "count": 0}
    if not payload:
        return {"state": "UNVERIFIED", "reason": "no_recent_trades", "count": 0}
    try:
        ids: set[str] = set()
        timestamps: list[datetime] = []
        for trade in payload:
            if not isinstance(trade, dict):
                raise TypeError
            # The locked official exchange-api RecentTrade DTO uses executionId,
            # not the account/order object's id. Never infer bad venue data from
            # an unsupported local field requirement.
            trade_id = trade.get("executionId")
            if not isinstance(trade_id, str) or not trade_id or len(trade_id) > 128:
                raise ValueError
            if str(trade_id) in ids:
                raise ValueError
            ids.add(str(trade_id))
            if str(trade.get("instrument", "")).upper() != venue:
                raise ValueError
            _number(trade.get("fillQuantity"))
            _number(trade.get("fillPrice"))
            timestamps.append(_timestamp(trade.get("createdAt")))
        latest = max(timestamps)
    except (ValueError, TypeError):
        return {
            "state": "UNVERIFIED",
            "reason": "trade_schema_invalid",
            "count": len(payload),
        }
    age = (captured_at - latest).total_seconds()
    if age < -MAX_FUTURE_SKEW_S or age > TRADE_MAX_AGE_S:
        return {
            "state": "UNVERIFIED",
            "reason": "latest_trade_stale_or_future",
            "count": len(payload),
            "latest_trade_age_seconds": age,
        }
    return {
        "state": "OBSERVED_RECENT_TRADES",
        "reason": None,
        "count": len(payload),
        "latest_trade_age_seconds": age,
    }


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


def _new_run_directory(
    base: Path, *, now: datetime, make_uuid: Callable[[], str]
) -> Path:
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = make_uuid()
    try:
        if str(uuid.UUID(suffix)) != suffix.lower():
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise SamplerError("LOCAL_VALIDATION_FAILED") from None
    return base / f"sample-{stamp}-{suffix}"


def _verify_pins(
    root: Path, *, run: Callable[..., Any] = subprocess.run
) -> tuple[Any, Any, Any]:
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

    def git_run(args: list[str], *, capture: bool = True, binary: bool = False) -> Any:
        try:
            return run(
                [str(git), "-C", str(root), *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=capture and not binary,
                timeout=20,
                check=False,
                env=env,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            raise SamplerError("LOCAL_VALIDATION_FAILED") from None

    head = git_run(["show", "-s", "--format=%H %G? %GF", "HEAD"])
    head_id = git_run(["rev-parse", "HEAD"])
    origin_main = git_run(["rev-parse", "refs/remotes/origin/main"])
    branch = git_run(["branch", "--show-current"])
    status = git_run(
        [
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            SOURCE_RELATIVE,
            CONTINUATION_RELATIVE,
        ]
    )
    current = root / SOURCE_RELATIVE
    blob = git_run(["show", f"HEAD:{SOURCE_RELATIVE}"], binary=True)
    helper = root / CONTINUATION_RELATIVE
    helper_commit = git_run(["show", "-s", "--format=%H %G? %GF", CONTINUATION_COMMIT])
    helper_ancestor = git_run(
        ["merge-base", "--is-ancestor", CONTINUATION_COMMIT, "HEAD"], capture=False
    )
    helper_blob = git_run(
        ["show", f"{CONTINUATION_COMMIT}:{CONTINUATION_RELATIVE}"], binary=True
    )

    def regular_file(path: Path) -> bool:
        try:
            info = path.lstat()
            return (
                stat.S_ISREG(info.st_mode)
                and not stat.S_ISLNK(info.st_mode)
                and not (getattr(info, "st_file_attributes", 0) & 0x400)
                and path.resolve(strict=True) == path
                and info.st_size <= 512 * 1024
            )
        except OSError:
            return False

    if (
        head.returncode
        or len(head.stdout.split()) != 3
        or head.stdout.split()[1:] != ["G", META_SIGNER]
        or head_id.returncode
        or not head_id.stdout.strip()
        or head_id.stdout.strip() != head.stdout.split()[0]
        or origin_main.returncode
        or origin_main.stdout.strip() != head_id.stdout.strip()
        or branch.returncode
        or branch.stdout.strip() != "main"
        or status.returncode
        or _scoped_status_has_changes(status.stdout)
        or blob.returncode
        or len(head.stdout.split()[0]) != 40
        or not regular_file(current)
        or hashlib.sha256(current.read_bytes()).digest()
        != hashlib.sha256(blob.stdout).digest()
        or helper_commit.returncode
        or helper_commit.stdout.strip() != f"{CONTINUATION_COMMIT} G {META_SIGNER}"
        or helper_ancestor.returncode
        or helper_blob.returncode
        or hashlib.sha256(helper_blob.stdout).hexdigest() != CONTINUATION_SHA256
        or not regular_file(helper)
        or hashlib.sha256(helper.read_bytes()).hexdigest() != CONTINUATION_SHA256
    ):
        raise SamplerError("LOCAL_VALIDATION_FAILED")
    if str(root) not in os.sys.path:
        os.sys.path.insert(0, str(root))
    from development.ops_alerts import telegram_continuation as continuation

    if Path(continuation.__file__).resolve(strict=True) != helper.resolve(strict=True):
        raise SamplerError("LOCAL_VALIDATION_FAILED")
    delivery, _diagnostic, _handoff = continuation._load_signed_sources()
    from scripts import provision_secrets

    provision_source = Path("D:/Kairos/kairos-deploy") / PROVISION_RELATIVE
    delivery._no_reparse(provision_source)
    if (
        Path(provision_secrets.__file__).resolve(strict=True)
        != provision_source.resolve(strict=True)
        or provision_source.stat().st_size > 128 * 1024
        or hashlib.sha256(provision_source.read_bytes()).hexdigest() != PROVISION_SHA256
    ):
        raise SamplerError("LOCAL_VALIDATION_FAILED")
    return continuation, delivery, provision_secrets


def _scoped_status_has_changes(status: str) -> bool:
    """Only sampler/helper edits block; unrelated engineering WIP is preserved."""
    for row in status.splitlines():
        if len(row) < 4:
            return True
        changed_path = row[3:].strip().replace("\\", "/")
        candidates = changed_path.split(" -> ")
        if any(candidate in SCOPED_STATUS_PATHS for candidate in candidates):
            return True
    return False


def _safe_source_status(endpoint: Endpoint, source_hash: str) -> dict[str, Any]:
    return {
        "endpoint": endpoint.label,
        "request_sha256": hashlib.sha256(
            (ORIGIN + endpoint.path).encode("utf-8")
        ).hexdigest(),
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
    http_counter: list[int] | None = None,
) -> dict[str, Any]:
    requests_dir = run_dir / "requests"
    raw_dir = run_dir / "public-json"
    _write_new_directory(requests_dir, delivery=delivery)
    _write_new_directory(raw_dir, delivery=delivery)
    responses: dict[str, tuple[Any, PublicResponse | None, str | None]] = {}
    attempts = http_counter if http_counter is not None else [0]

    for index, endpoint in enumerate(ENDPOINTS, start=1):
        stem = f"{index:02d}-{endpoint.label}"
        base = _safe_source_status(endpoint, source_hash)
        reservation = {
            **base,
            "schema": "evedex-public-get-reserved-v1",
            "reserved_at_utc": clock().astimezone(UTC).isoformat(),
        }
        try:
            writer(
                requests_dir / f"{stem}.reserved.json",
                _json_bytes(reservation),
                continuation,
                delivery,
            )
        except Exception:  # noqa: BLE001 - storage failure stops before any GET.
            raise SamplerError(
                "LOCAL_VALIDATION_FAILED", http_calls=attempts[0]
            ) from None
        response: PublicResponse | None = None
        error_category: str | None = None
        error_status: int | None = None
        payload: Any = None
        started = time.monotonic()
        attempts[0] += 1
        try:
            response = fetcher(endpoint.path)
            if not isinstance(response, PublicResponse):
                raise SamplerError("LOCAL_VALIDATION_FAILED")
        except SamplerError as exc:
            if exc.category == "LOCAL_VALIDATION_FAILED":
                raise SamplerError(
                    exc.category, http_status=exc.http_status, http_calls=attempts[0]
                ) from None
            error_category = exc.category
            error_status = exc.http_status
        except Exception:  # noqa: BLE001 - arbitrary transport errors are never serialized.
            error_category = "TLS_OR_TRANSPORT_ERROR"
        if response is not None:
            if len(response.body) > MAX_RESPONSE_BYTES:
                error_category = "OVERSIZED_RESPONSE"
                error_status = response.status
            elif response.error_category is not None:
                error_category = response.error_category
            elif response.status != 200:
                error_category = "HTTP_ERROR"
            if error_category is None:
                try:
                    payload = _parse_json(response.body)
                except SamplerError as error:
                    error_category = error.category
                if error_category is None:
                    try:
                        writer(
                            raw_dir / f"{stem}.json",
                            response.body,
                            continuation,
                            delivery,
                        )
                    except Exception:  # noqa: BLE001 - persistence errors stop all later GETs.
                        raise SamplerError(
                            "LOCAL_VALIDATION_FAILED", http_calls=attempts[0]
                        ) from None
        latency = (
            response.latency_ms
            if response is not None
            else (time.monotonic() - started) * 1000
        )
        captured_at = (
            response.captured_at if response is not None else clock().astimezone(UTC)
        )
        result = {
            **base,
            "schema": "evedex-public-get-result-v1",
            "captured_at_utc": captured_at.astimezone(UTC).isoformat(),
            "http_status": response.status if response is not None else error_status,
            "latency_ms": max(0.0, latency) if math.isfinite(latency) else None,
            "response_sha256": hashlib.sha256(response.body).hexdigest()
            if response is not None
            else None,
            "response_bytes": len(response.body) if response is not None else None,
            "error_category": error_category,
            "automatic_retry": False,
        }
        try:
            writer(
                requests_dir / f"{stem}.result.json",
                _json_bytes(result),
                continuation,
                delivery,
            )
        except Exception:  # noqa: BLE001 - result write failure stops all later GETs.
            raise SamplerError(
                "LOCAL_VALIDATION_FAILED", http_calls=attempts[0]
            ) from None
        responses[endpoint.label] = (payload, response, error_category)

    captured = clock().astimezone(UTC)
    market_payload, _, market_error = responses["market"]
    market_state = "UNVERIFIED"
    if market_error is None and isinstance(market_payload, dict):
        try:
            if market_payload.get("state") != "active":
                raise ValueError
            _timestamp(market_payload.get("updatedAt"))
            market_state = "ACTIVE_SNAPSHOT"
        except ValueError:
            market_state = "UNVERIFIED"

    instrument_payload, _, instrument_error = responses["instruments"]
    instrument_map, instrument_problem = (
        _duplicate_safe_instruments(instrument_payload)
        if instrument_error is None
        else ({}, "instrument_http_or_parse_error")
    )
    symbols: dict[str, Any] = {}
    all_ready = market_state == "ACTIVE_SNAPSHOT" and instrument_problem is None
    for logical, venue in SYMBOLS:
        depth_label = f"depth_{venue.replace(':', '_')}"
        trade_label = f"trades_{venue.replace(':', '_')}"
        depth_payload, depth_response, depth_error = responses[depth_label]
        trades_payload, trades_response, trades_error = responses[trade_label]
        try:
            if depth_error is not None or depth_response is None:
                raise ValueError(depth_error or "depth_unavailable")
            depth_summary = _validate_book(
                depth_payload, venue=venue, captured_at=depth_response.captured_at
            )
        except (ValueError, TypeError) as error:
            reason = (
                str(error)
                if str(error)
                in {
                    "depth_schema_invalid",
                    "depth_empty",
                    "depth_level_schema_invalid",
                    "depth_duplicate_price_level",
                    "depth_order_invalid",
                    "depth_from_future",
                    "depth_stale",
                    "depth_crossed",
                    "spread_above_one_shot_limit",
                }
                else (depth_error or "depth_invalid")
            )
            depth_summary = {"state": "BLOCKED", "reason": reason}
        if depth_summary["state"] != "FRESH_VALID":
            all_ready = False
        if trades_error is not None or trades_response is None:
            trades_summary = {
                "state": "UNVERIFIED",
                "reason": trades_error or "trades_unavailable",
                "count": 0,
            }
        else:
            trades_summary = _validate_trades(
                trades_payload, venue=venue, captured_at=trades_response.captured_at
            )
        if trades_summary["state"] != "OBSERVED_RECENT_TRADES":
            all_ready = False
        if venue not in instrument_map:
            all_ready = False
        symbols[logical] = {
            "venue_symbol": venue,
            "depth": depth_summary,
            "recent_trades": trades_summary,
        }

    report = {
        "schema": "evedex-dev-public-preflight-v1",
        "status": "PASS_PUBLIC_SNAPSHOT_ONLY" if all_ready else "BLOCKED",
        "captured_at_utc": captured.isoformat(),
        "origin": ORIGIN,
        "request_count": len(ENDPOINTS),
        "max_requests": MAX_REQUESTS,
        "timeout_seconds": REQUEST_TIMEOUT_S,
        "maximum_response_bytes": MAX_RESPONSE_BYTES,
        "market_snapshot": market_state,
        "instrument_contract": "VALID" if instrument_problem is None else "BLOCKED",
        "instrument_issue": instrument_problem,
        "symbols": symbols,
        "implementation_sha256": source_hash,
        "authenticated": False,
        "account_reconciliation": False,
        "sample_is_24h_evidence": False,
        "paper_qualified": False,
        "canary_qualified": False,
        "seven_day_qualified": False,
        "trading_authority": False,
        "automatic_retry": False,
    }
    report["requires_manual_review"] = False
    try:
        writer(run_dir / "report.json", _json_bytes(report), continuation, delivery)
    except Exception:  # noqa: BLE001 - preserve the count on terminal write failure.
        raise SamplerError("LOCAL_VALIDATION_FAILED", http_calls=attempts[0]) from None
    return report


def _run_with_dependencies(
    *,
    authorize: bool,
    root: Path = RUNTIME_ROOT,
    source_root: Path = KAIROS_ROOT,
    fetcher: Callable[[str], PublicResponse] = _http_get,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    make_uuid: Callable[[], str] = lambda: str(uuid.uuid4()),
    pin_loader: Callable[[Path], tuple[Any, Any, Any]] = _verify_pins,
    writer: Callable[[Path, bytes, Any, Any], None] = _exclusive_write,
) -> dict[str, Any]:
    if authorize is not True:
        raise SamplerError("LOCAL_VALIDATION_FAILED")
    continuation, delivery, provisioner = pin_loader(source_root)
    delivery._no_reparse(root.parent)
    if root.exists():
        delivery._no_reparse(root)
        delivery._private_acl(root)
    else:
        root.mkdir()
        delivery._no_reparse(root)
        if any(root.iterdir()):
            raise SamplerError("LOCAL_VALIDATION_FAILED")
        provisioner.harden_permissions(root)
        delivery._private_acl(root)
    now = clock().astimezone(UTC)
    run_dir = _new_run_directory(root, now=now, make_uuid=make_uuid)
    if run_dir.exists():
        raise SamplerError("LOCAL_VALIDATION_FAILED")
    _write_new_directory(run_dir, delivery=delivery)
    source = Path(__file__).resolve(strict=True)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    http_counter = [0]
    try:
        return _probe_all(
            run_dir=run_dir,
            source_hash=source_hash,
            continuation=continuation,
            delivery=delivery,
            fetcher=fetcher,
            clock=clock,
            writer=writer,
            http_counter=http_counter,
        )
    except SamplerError as error:
        if error.http_calls != http_counter[0]:
            raise SamplerError(error.category, http_calls=http_counter[0]) from None
        raise
    except Exception:  # noqa: BLE001 - preserve attempted-call count without raw details.
        raise SamplerError(
            "LOCAL_VALIDATION_FAILED", http_calls=http_counter[0]
        ) from None


def run_public_preflight(*, authorize: bool) -> dict[str, Any]:
    """Production entry point with immutable paths and real pinned transport."""
    return _run_with_dependencies(
        authorize=authorize,
        root=RUNTIME_ROOT,
        source_root=KAIROS_ROOT,
        fetcher=_http_get,
        clock=lambda: datetime.now(UTC),
        make_uuid=lambda: str(uuid.uuid4()),
        pin_loader=_verify_pins,
        writer=_exclusive_write,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-public-preflight", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute_public_preflight:
        print(
            json.dumps(
                {"status": "PLAN_ONLY", "http_calls": 0, "trading_authority": False}
            )
        )
        return 0
    try:
        report = run_public_preflight(authorize=True)
    except Exception as error:  # noqa: BLE001 - never expose unexpected details on stdout.
        calls = getattr(error, "http_calls", None)
        if type(calls) is not int:
            calls = None
        report = {
            "status": "BLOCKED",
            "error_category": "LOCAL_VALIDATION_FAILED",
            "http_calls": calls,
            "requires_manual_review": calls is None or calls > 0,
            "trading_authority": False,
        }
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report.get("status") == "PASS_PUBLIC_SNAPSHOT_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
