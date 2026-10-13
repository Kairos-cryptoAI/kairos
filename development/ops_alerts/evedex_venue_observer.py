"""Plan-gated, durable public Binance/EVEDEX DEV book observer.

This observer records public market data only. It never authenticates, trades,
connects to Kairos services, or changes readiness. A completed run still needs
owner review and external account/instrument prerequisites before qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import ssl
import stat
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
DEFAULT_OUTPUT_ROOT = Path("D:/Kairos/runtime/evedex-venue-observer")
QUANT_SOURCE = Path("D:/Kairos/kairos-quant-scouts/kairos_quant/venue_comparison.py")
QUANT_SOURCE_SHA256 = "edc06b208356058f8df1912e20fdccd1fadb7ecc0ce29054e89fd9711c641aa3"
EVEDEX_ORIGIN = "https://trading-api.evedex.tech"
BINANCE_ORIGIN = "https://fapi.binance.com"
INSTRUMENTS = (
    ("BTCUSDT", "BTCUSD:DEV"),
    ("ETHUSDT", "ETHUSD:DEV"),
    ("SOLUSDT", "SOLUSD:DEV"),
    ("BNBUSDT", "BNBUSD:DEV"),
    ("XRPUSDT", "XRPUSD:DEV"),
)
MAX_DURATION_S = 24 * 60 * 60
POLL_INTERVAL_S = 120
REQUEST_TIMEOUT_S = 8
SLOT_DEADLINE_S = 90
MAX_RESPONSE_BYTES = 64 * 1024
MAX_STORAGE_BYTES = 1_073_741_824
REQUESTS_PER_SLOT = len(INSTRUMENTS) * 2
MAX_SLOTS = math.ceil(MAX_DURATION_S / POLL_INTERVAL_S)
MAX_REQUESTS = MAX_SLOTS * REQUESTS_PER_SLOT
ASSESSED_NOTIONAL_USD = 1_000.0
MAX_BOOK_AGE_MS = 5_000
MAX_CLOCK_AHEAD_MS = 2_000
MAX_TIMESTAMP_SKEW_MS = 2_000


class ObserverError(Exception):
    """Fixed public-facing observer error category."""


@dataclass(frozen=True)
class ObservationPlan:
    duration_s: int = MAX_DURATION_S
    poll_interval_s: int = POLL_INTERVAL_S
    request_timeout_s: int = REQUEST_TIMEOUT_S
    slot_deadline_s: int = SLOT_DEADLINE_S
    max_response_bytes: int = MAX_RESPONSE_BYTES
    max_storage_bytes: int = MAX_STORAGE_BYTES

    def __post_init__(self) -> None:
        values = (
            self.duration_s,
            self.poll_interval_s,
            self.request_timeout_s,
            self.slot_deadline_s,
            self.max_response_bytes,
            self.max_storage_bytes,
        )
        if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in values):
            raise ValueError("observer limits must be positive integers")
        if self.duration_s > MAX_DURATION_S or self.poll_interval_s < 10:
            raise ValueError("observer duration or polling rate exceeds fixed limits")
        if self.request_timeout_s > REQUEST_TIMEOUT_S or self.slot_deadline_s > SLOT_DEADLINE_S:
            raise ValueError("observer request deadline exceeds fixed limits")
        if self.max_response_bytes > MAX_RESPONSE_BYTES or self.max_storage_bytes > MAX_STORAGE_BYTES:
            raise ValueError("observer storage limits exceed fixed limits")
        if self.request_timeout_s * REQUESTS_PER_SLOT > self.slot_deadline_s:
            raise ValueError("request timeouts cannot fit within one slot deadline")
        if self.slot_deadline_s > self.poll_interval_s:
            raise ValueError("slot deadline cannot overlap the next poll")
        if self.maximum_storage_reservation > self.max_storage_bytes:
            raise ValueError("planned samples exceed the storage budget")
        if self.slots * REQUESTS_PER_SLOT > MAX_REQUESTS:
            raise ValueError("observer request count exceeds fixed limits")

    @property
    def slots(self) -> int:
        return math.ceil(self.duration_s / self.poll_interval_s)

    @property
    def maximum_storage_reservation(self) -> int:
        per_slot = REQUESTS_PER_SLOT * (self.max_response_bytes + 4_096) + 8_192
        return self.slots * per_slot + 1_048_576


_DEFAULT_PLAN = ObservationPlan()


@dataclass(frozen=True)
class PublicResponse:
    status: int | None
    body: bytes | None
    latency_ms: float
    captured_at_ms: int
    error_category: str | None = None
    oversized: bool = False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _comparison_logic(*, path: Path = QUANT_SOURCE, expected_sha256: str = QUANT_SOURCE_SHA256) -> Any:
    """Load only the pinned Quant venue-comparison implementation."""
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ObserverError("MEASUREMENT_SOURCE_UNAVAILABLE")
        source = path.read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        if digest != expected_sha256:
            raise ObserverError("MEASUREMENT_SOURCE_CHANGED")
        spec = importlib.util.spec_from_file_location("_kairos_pinned_venue_comparison", path)
        if spec is None or spec.loader is None:
            raise ObserverError("MEASUREMENT_SOURCE_UNAVAILABLE")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        exec(  # noqa: S102 -- execute only the exact bytes whose configured digest was verified above.
            compile(source, str(path), "exec", dont_inherit=True), module.__dict__
        )
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ObserverError("MEASUREMENT_SOURCE_CHANGED")
        return module
    except ObserverError:
        raise
    except Exception:  # noqa: BLE001 -- hide filesystem and loader details from callers.
        raise ObserverError("MEASUREMENT_SOURCE_UNAVAILABLE") from None


def build_plan(plan: ObservationPlan = _DEFAULT_PLAN) -> dict[str, Any]:
    comparison = _comparison_logic()
    return {
        "schema": "kairos-evedex-public-observer-plan-v1",
        "status": "PLAN_ONLY",
        "duration_seconds": plan.duration_s,
        "poll_interval_seconds": plan.poll_interval_s,
        "planned_slots": plan.slots,
        "planned_slot_ids": [f"slot-{slot:04d}" for slot in range(1, plan.slots + 1)],
        "requests_per_slot": REQUESTS_PER_SLOT,
        "maximum_requests": plan.slots * REQUESTS_PER_SLOT,
        "request_timeout_seconds": plan.request_timeout_s,
        "slot_deadline_seconds": plan.slot_deadline_s,
        "maximum_response_bytes": plan.max_response_bytes,
        "maximum_storage_bytes": plan.max_storage_bytes,
        "maximum_storage_reservation_bytes": plan.maximum_storage_reservation,
        "instruments": [{"binance": b, "evedex_dev": e} for b, e in INSTRUMENTS],
        "authenticated": False,
        "orders_enabled": False,
        "database_or_redis": False,
        "readiness_changed": False,
        "qualification_status": "NOT_QUALIFIED_OWNER_REVIEW_REQUIRED",
        "measurement_source_sha256": hashlib.sha256(QUANT_SOURCE.read_bytes()).hexdigest(),
        "comparison_logic": "kairos_quant.venue_comparison",
        "thresholds_reference": dict(comparison.DEFAULT_THRESHOLDS),
    }


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _create_only(path: Path, payload: bytes) -> None:
    """Durably create one immutable file; never replace an existing record."""
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        raise ObserverError("CREATE_ONLY_COLLISION") from None
    except Exception:  # noqa: BLE001 -- return one fixed category without leaking local paths.
        raise ObserverError("DURABLE_WRITE_FAILED") from None


def _create_json(path: Path, value: Any) -> None:
    _create_only(path, _json_bytes(value))


def _url(symbol: str, venue: str) -> str:
    mapping = dict(INSTRUMENTS)
    if symbol not in mapping or venue not in {"evedex", "binance"}:
        raise ObserverError("FIXED_PUBLIC_ENDPOINT_REQUIRED")
    if venue == "evedex":
        return f"{EVEDEX_ORIGIN}/api/market/{mapping[symbol]}/deep"
    return f"{BINANCE_ORIGIN}/fapi/v1/depth?symbol={symbol}&limit=100"


def _http_get(url: str, *, timeout_s: float, max_bytes: int) -> PublicResponse:
    parsed = urlsplit(url)
    allowed_urls = {
        _url(symbol, venue) for symbol, _venue_symbol in INSTRUMENTS for venue in ("evedex", "binance")
    }
    if (
        url not in allowed_urls
        or parsed.scheme != "https"
        or parsed.hostname
        not in {
            "trading-api.evedex.tech",
            "fapi.binance.com",
        }
        or parsed.port
        or parsed.username
        or parsed.password
    ):
        raise ObserverError("FIXED_PUBLIC_ENDPOINT_REQUIRED")
    # Caller validates one of two fixed HTTPS public origins.
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
        response = opener.open(request, timeout=timeout_s)
    except urllib.error.HTTPError as error:
        try:
            body = error.read(max_bytes + 1)
            oversized = len(body) > max_bytes
            return PublicResponse(
                int(error.code),
                None if oversized else body,
                (time.monotonic() - started) * 1000,
                int(time.time() * 1000),
                "REDIRECT_BLOCKED" if 300 <= error.code < 400 else "HTTP_ERROR",
                oversized,
            )
        finally:
            error.close()
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError):
        return PublicResponse(
            None, None, (time.monotonic() - started) * 1000, int(time.time() * 1000), "TLS_OR_TRANSPORT_ERROR"
        )
    try:
        if response.geturl() != url:
            return PublicResponse(
                int(response.status),
                None,
                (time.monotonic() - started) * 1000,
                int(time.time() * 1000),
                "REDIRECT_BLOCKED",
            )
        length = response.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > max_bytes:
            return PublicResponse(
                int(response.status),
                None,
                (time.monotonic() - started) * 1000,
                int(time.time() * 1000),
                "OVERSIZED_RESPONSE",
                True,
            )
        body = response.read(max_bytes + 1)
        oversized = len(body) > max_bytes
        return PublicResponse(
            int(response.status),
            None if oversized else body,
            (time.monotonic() - started) * 1000,
            int(time.time() * 1000),
            "OVERSIZED_RESPONSE" if oversized else None,
            oversized,
        )
    finally:
        response.close()


def _decode_json(body: bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    return json.loads(
        body.decode("utf-8"),
        object_pairs_hook=unique,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
    )


def _endpoint_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _reserve_slot(run_dir: Path, slot: int, scheduled_at: str, source_hash: str) -> list[dict[str, Any]]:
    slot_id = f"slot-{slot:04d}"
    attempts_dir = run_dir / "attempts"
    attempts: list[dict[str, Any]] = []
    for binance, evedex in INSTRUMENTS:
        for venue, symbol in (("evedex", evedex), ("binance", binance)):
            url = _url(binance, venue)
            key = f"{slot_id}-{binance}-{venue}"
            attempt = {
                "schema": "kairos-public-get-reservation-v1",
                "slot_id": slot_id,
                "instrument": binance,
                "venue_symbol": symbol,
                "venue": venue,
                "method": "GET",
                "endpoint_sha256": _endpoint_hash(url),
                "implementation_sha256": source_hash,
                "reserved_at_utc": datetime.now(UTC).isoformat(),
                "automatic_retry": False,
                "authenticated": False,
                "outcome": "UNKNOWN_UNTIL_RESULT",
            }
            _create_json(attempts_dir / f"{key}.reserved.json", attempt)
            attempts.append({**attempt, "key": key, "url": url})
    return attempts


def _summary_sample(
    module: Any, binance_symbol: str, evedex_symbol: str, bbook: Any, ebook: Any, captured_at_ms: int
) -> Any:
    observed = max(captured_at_ms, bbook.timestamp_ms, ebook.timestamp_ms)
    return module.VenueSample(
        logical_symbol=binance_symbol,
        captured_at=datetime.fromtimestamp(captured_at_ms / 1000, UTC).isoformat(),
        evedex_timestamp_ms=ebook.timestamp_ms,
        binance_timestamp_ms=bbook.timestamp_ms,
        timestamp_skew_ms=abs(ebook.timestamp_ms - bbook.timestamp_ms),
        evedex_age_ms=observed - ebook.timestamp_ms,
        binance_age_ms=observed - bbook.timestamp_ms,
        basis_bps=(ebook.mid - bbook.mid) / bbook.mid * 10_000,
        evedex_spread_bps=ebook.spread_bps,
        binance_spread_bps=bbook.spread_bps,
        evedex_buy_slippage_bps=module.market_slippage_bps(
            ebook, buy=True, notional_usd=ASSESSED_NOTIONAL_USD
        ),
        evedex_sell_slippage_bps=module.market_slippage_bps(
            ebook, buy=False, notional_usd=ASSESSED_NOTIONAL_USD
        ),
        binance_buy_slippage_bps=module.market_slippage_bps(
            bbook, buy=True, notional_usd=ASSESSED_NOTIONAL_USD
        ),
        binance_sell_slippage_bps=module.market_slippage_bps(
            bbook, buy=False, notional_usd=ASSESSED_NOTIONAL_USD
        ),
        evedex_latency_ms=ebook.latency_ms,
        binance_latency_ms=bbook.latency_ms,
    )


def _collect_slot(
    *,
    run_dir: Path,
    slot: int,
    scheduled_at: str,
    source_hash: str,
    plan: ObservationPlan,
    module: Any,
    fetcher: Callable[..., PublicResponse] = _http_get,
    monotonic: Callable[[], float] = time.monotonic,
    wall_ms: Callable[[], int] = lambda: int(time.time() * 1000),
    run_deadline: float | None = None,
) -> tuple[dict[str, Any], list[tuple[str, Any]]]:
    """Reserve every request before the first GET; never resume a partial slot."""
    slot_id = f"slot-{slot:04d}"
    slot_started = monotonic()
    _create_json(
        run_dir / "slots" / f"{slot_id}.reserved.json",
        {
            "schema": "kairos-public-slot-reservation-v1",
            "slot_id": slot_id,
            "scheduled_at_utc": scheduled_at,
            "requests_reserved": REQUESTS_PER_SLOT,
            "automatic_retry": False,
            "outcome": "UNKNOWN_UNTIL_RESULT",
        },
    )
    attempts = _reserve_slot(run_dir, slot, scheduled_at, source_hash)
    deadline = slot_started + plan.slot_deadline_s
    if run_deadline is not None:
        deadline = min(deadline, run_deadline)
    responses: dict[str, dict[str, Any]] = {}
    samples: list[tuple[str, Any]] = []
    for attempt in attempts:
        key = attempt["key"]
        start = monotonic()
        if start >= deadline:
            reason = (
                "NOT_SENT_RUN_DEADLINE"
                if run_deadline is not None and start >= run_deadline
                else "NOT_SENT_SLOT_DEADLINE"
            )
            response = PublicResponse(None, None, 0.0, wall_ms(), reason)
        else:
            # The reservation deliberately remains without a result if this
            # call is interrupted; a later invocation cannot resume the slot.
            response = fetcher(
                attempt["url"],
                timeout_s=min(plan.request_timeout_s, deadline - start),
                max_bytes=plan.max_response_bytes,
            )
        raw_hash = hashlib.sha256(response.body).hexdigest() if response.body is not None else None
        raw_name = f"{key}.raw" if response.body is not None else None
        if response.body is not None:
            _create_only(run_dir / "public" / raw_name, response.body)
        result = {
            "schema": "kairos-public-get-result-v1",
            "attempt_id": key,
            "outcome": (
                "NOT_SENT"
                if response.error_category == "NOT_SENT_SLOT_DEADLINE"
                else ("UNKNOWN_OUTCOME" if response.status is None else "RESPONSE_RECEIVED")
            ),
            "http_status": response.status,
            "error_category": response.error_category,
            "latency_ms": response.latency_ms if math.isfinite(response.latency_ms) else None,
            "captured_at_ms": response.captured_at_ms,
            "response_bytes": len(response.body) if response.body is not None else None,
            "response_sha256": raw_hash,
            "raw_file": raw_name,
            "oversized": response.oversized,
            "automatic_retry": False,
        }
        _create_json(run_dir / "attempts" / f"{key}.result.json", result)
        responses[key] = {"attempt": attempt, "response": response, "result": result}

    for binance, evedex in INSTRUMENTS:
        ekey, bkey = f"{slot_id}-{binance}-evedex", f"{slot_id}-{binance}-binance"
        ev, br = responses[ekey]["response"], responses[bkey]["response"]
        metrics: dict[str, Any] = {
            "schema": "kairos-public-venue-measurement-v1",
            "slot_id": slot_id,
            "binance_symbol": binance,
            "evedex_symbol": evedex,
            "measurement_status": "UNAVAILABLE",
            "reason": None,
            "binance_response_sha256": responses[bkey]["result"]["response_sha256"],
            "evedex_response_sha256": responses[ekey]["result"]["response_sha256"],
            "reference_timestamp_ms": None,
            "book_timestamp_ms": None,
            "reference_age_ms": None,
            "book_age_ms": None,
            "timestamp_skew_ms": None,
            "local_clock_ahead_ms": None,
            "capture_delta_ms": abs(ev.captured_at_ms - br.captured_at_ms),
            "basis_bps": None,
            "spread_bps": None,
            "depth_usd": None,
            "buy_slippage_bps": None,
            "sell_slippage_bps": None,
            "latency_ms": None,
            "freshness": "UNAVAILABLE",
        }
        if ev.status != 200 or br.status != 200 or ev.body is None or br.body is None:
            metrics["reason"] = "public_response_unavailable"
        else:
            try:
                ebook = module.parse_evedex_book(evedex, _decode_json(ev.body), latency_ms=ev.latency_ms)
                bbook = module.parse_binance_book(binance, _decode_json(br.body), latency_ms=br.latency_ms)
                captured = max(ev.captured_at_ms, br.captured_at_ms)
                observed = max(captured, ebook.timestamp_ms, bbook.timestamp_ms)
                local_ahead = max(0, max(ebook.timestamp_ms, bbook.timestamp_ms) - captured)
                reference_age = observed - bbook.timestamp_ms
                book_age = observed - ebook.timestamp_ms
                skew = abs(ebook.timestamp_ms - bbook.timestamp_ms)
                depth = min(
                    sum(level.price * level.quantity for level in ebook.bids),
                    sum(level.price * level.quantity for level in ebook.asks),
                )
                buy_slippage = module.market_slippage_bps(ebook, buy=True, notional_usd=ASSESSED_NOTIONAL_USD)
                sell_slippage = module.market_slippage_bps(
                    ebook, buy=False, notional_usd=ASSESSED_NOTIONAL_USD
                )
                future_or_stale = (
                    local_ahead > MAX_CLOCK_AHEAD_MS
                    or skew > MAX_TIMESTAMP_SKEW_MS
                    or abs(ev.captured_at_ms - br.captured_at_ms) > MAX_TIMESTAMP_SKEW_MS
                    or max(reference_age, book_age) > MAX_BOOK_AGE_MS
                )
                metrics.update(
                    {
                        "measurement_status": "MEASURED",
                        "reason": None,
                        "reference_timestamp_ms": bbook.timestamp_ms,
                        "book_timestamp_ms": ebook.timestamp_ms,
                        "reference_age_ms": reference_age,
                        "book_age_ms": book_age,
                        "timestamp_skew_ms": skew,
                        "local_clock_ahead_ms": local_ahead,
                        "basis_bps": (ebook.mid - bbook.mid) / bbook.mid * 10_000,
                        "spread_bps": ebook.spread_bps,
                        "depth_usd": depth,
                        "buy_slippage_bps": buy_slippage,
                        "sell_slippage_bps": sell_slippage,
                        "latency_ms": max(ev.latency_ms, br.latency_ms),
                        "freshness": "STALE_OR_CLOCK_SKEWED" if future_or_stale else "FRESH",
                    }
                )
                samples.append((binance, _summary_sample(module, binance, evedex, bbook, ebook, captured)))
            except Exception:  # noqa: BLE001 -- malformed public books stay unavailable, never synthesized.
                metrics["reason"] = "book_missing_or_invalid"
        _create_json(run_dir / "slots" / f"{slot_id}-{binance}.measurement.json", metrics)
    slot_result = {
        "schema": "kairos-public-slot-result-v1",
        "slot_id": slot_id,
        "outcome": "COMPLETED",
        "requests_reserved": REQUESTS_PER_SLOT,
        "requests_attempted": sum(item["result"]["outcome"] != "NOT_SENT" for item in responses.values()),
        "requests_completed": sum(item["result"]["http_status"] is not None for item in responses.values()),
        "requests_not_sent": sum(item["result"]["outcome"] == "NOT_SENT" for item in responses.values()),
        "unknown_outcomes": sum(
            item["result"]["outcome"] == "UNKNOWN_OUTCOME" for item in responses.values()
        ),
        "automatic_retry": False,
    }
    _create_json(run_dir / "slots" / f"{slot_id}.result.json", slot_result)
    return slot_result, samples


def _execute_observation(
    *,
    authorize: bool,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    plan: ObservationPlan = _DEFAULT_PLAN,
    fetcher: Callable[..., PublicResponse] = _http_get,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    make_uuid: Callable[[], str] = lambda: str(uuid.uuid4()),
    source_path: Path = QUANT_SOURCE,
    expected_source_sha256: str = QUANT_SOURCE_SHA256,
) -> dict[str, Any]:
    if authorize is not True:
        raise ObserverError("EXPLICIT_EXECUTION_GATE_REQUIRED")
    module = _comparison_logic(path=source_path, expected_sha256=expected_source_sha256)
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if output_root.is_symlink():
        raise ObserverError("OUTPUT_ROOT_REPARSE_BLOCKED")
    output_root.mkdir(parents=True, exist_ok=True)
    lock_path = output_root / "observer.lock"
    try:
        lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ObserverError("OBSERVER_ALREADY_RUNNING_OR_LATCHED") from None
    run_id = make_uuid()
    try:
        with os.fdopen(lock_fd, "wb") as lock:
            lock.write(
                _json_bytes(
                    {
                        "schema": "kairos-observer-lock-v1",
                        "run_id": run_id,
                        "created_at_utc": wall_clock().astimezone(UTC).isoformat(),
                    }
                )
            )
            lock.flush()
            os.fsync(lock.fileno())
        run_dir = output_root / f"run-{run_id}"
        run_dir.mkdir(exist_ok=False)
        (run_dir / "attempts").mkdir()
        (run_dir / "slots").mkdir()
        (run_dir / "public").mkdir()
        started_wall = wall_clock().astimezone(UTC)
        started_mono = monotonic()
        plan_data = build_plan(plan)
        plan_data.update(
            {
                "status": "RUNNING",
                "run_id": run_id,
                "started_at_utc": started_wall.isoformat(),
                "observer_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "maximum_requests": plan.slots * REQUESTS_PER_SLOT,
                "scheduled_slots": [
                    {
                        "slot_id": f"slot-{slot:04d}",
                        "scheduled_at_utc": datetime.fromtimestamp(
                            started_wall.timestamp() + (slot - 1) * plan.poll_interval_s, UTC
                        ).isoformat(),
                    }
                    for slot in range(1, plan.slots + 1)
                ],
            }
        )
        _create_json(run_dir / "plan.json", plan_data)
        samples: dict[str, list[Any]] = {symbol: [] for symbol, _ in INSTRUMENTS}
        outcomes: list[dict[str, Any]] = []
        missed_slots = 0
        for slot in range(1, plan.slots + 1):
            scheduled = started_mono + (slot - 1) * plan.poll_interval_s
            delay = scheduled - monotonic()
            if delay > 0:
                sleep(delay)
            if monotonic() >= started_mono + plan.duration_s:
                missed_slots += plan.slots - slot + 1
                for skipped in range(slot, plan.slots + 1):
                    stamp = started_wall.timestamp() + (skipped - 1) * plan.poll_interval_s
                    _create_json(
                        run_dir / "slots" / f"slot-{skipped:04d}.missed.json",
                        {
                            "schema": "kairos-public-slot-result-v1",
                            "slot_id": f"slot-{skipped:04d}",
                            "outcome": "MISSED_RUN_DEADLINE",
                            "scheduled_at_utc": datetime.fromtimestamp(stamp, UTC).isoformat(),
                        },
                    )
                break
            scheduled_at = datetime.fromtimestamp(
                started_wall.timestamp() + (slot - 1) * plan.poll_interval_s, UTC
            ).isoformat()
            outcome, slot_samples = _collect_slot(
                run_dir=run_dir,
                slot=slot,
                scheduled_at=scheduled_at,
                source_hash=source_hash,
                plan=plan,
                module=module,
                fetcher=fetcher,
                monotonic=monotonic,
                wall_ms=lambda: int(wall_clock().timestamp() * 1000),
                run_deadline=started_mono + plan.duration_s,
            )
            outcomes.append(outcome)
            for symbol, sample in slot_samples:
                samples[symbol].append(sample)
        summaries: dict[str, Any] = {}
        for symbol, _venue_symbol in INSTRUMENTS:
            summary = module._summary(
                symbol,
                samples[symbol],
                requested=plan.slots,
                thresholds=dict(module.DEFAULT_THRESHOLDS),
            )
            summaries[symbol] = {
                "sample_count": summary.samples,
                "availability": summary.availability,
                "p50_abs_basis_bps": summary.p50_abs_basis_bps,
                "p95_abs_basis_bps": summary.p95_abs_basis_bps,
                "p95_spread_bps": summary.p95_evedex_spread_bps,
                "p95_buy_slippage_bps": summary.p95_evedex_buy_slippage_bps,
                "p95_sell_slippage_bps": summary.p95_evedex_sell_slippage_bps,
                "max_timestamp_skew_ms": summary.max_timestamp_skew_ms,
                "max_book_age_ms": summary.max_book_age_ms,
            }
        report = {
            "schema": "kairos-evedex-public-observer-report-v1",
            "status": "OBSERVATION_RECORDED",
            "run_id": run_id,
            "started_at_utc": started_wall.isoformat(),
            "finished_at_utc": wall_clock().astimezone(UTC).isoformat(),
            "elapsed_seconds": max(0.0, monotonic() - started_mono),
            "planned_slots": plan.slots,
            "completed_slots": len(outcomes),
            "missed_slots": missed_slots,
            "maximum_requests": plan.slots * REQUESTS_PER_SLOT,
            "requests_reserved": sum(item["requests_reserved"] for item in outcomes),
            "requests_attempted": sum(item["requests_attempted"] for item in outcomes),
            "requests_completed": sum(item["requests_completed"] for item in outcomes),
            "requests_not_sent": sum(item["requests_not_sent"] for item in outcomes),
            "unknown_outcomes": sum(item["unknown_outcomes"] for item in outcomes),
            "symbols": summaries,
            "measurement_source_sha256": source_hash,
            "authenticated": False,
            "orders_enabled": False,
            "database_or_redis": False,
            "readiness_changed": False,
            "sample_is_24h_evidence": False,
            "account_prerequisites_attested": False,
            "qualification_status": "NOT_QUALIFIED_OWNER_REVIEW_REQUIRED",
            "automatic_retry": False,
            "resume_supported": False,
        }
        _create_json(run_dir / "report.json", report)
        return report
    except BaseException:  # noqa: TRY203 -- preserve interruption while leaving the run latch intact.
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-public-observation", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute_public_observation:
        print(json.dumps(build_plan(), sort_keys=True, allow_nan=False))
        return 0
    try:
        report = _execute_observation(authorize=True)
    except ObserverError as error:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "error_category": str(error),
                    "authenticated": False,
                    "orders_enabled": False,
                    "readiness_changed": False,
                },
                sort_keys=True,
            )
        )
        return 2
    except Exception:  # noqa: BLE001 -- CLI emits only a sanitized local failure category.
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "error_category": "LOCAL_VALIDATION_FAILED",
                    "authenticated": False,
                    "orders_enabled": False,
                    "readiness_changed": False,
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
