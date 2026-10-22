"""Explicit finite verification of CURRENT sources, real models, isolated SIM.

Default invocation only prints the scope. ``--execute`` is opt-in and uses the
already approved existing credential and cumulative qualification budget.
No exchange adapter or trading runtime is constructed by this module.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import re
import time
from dataclasses import asdict
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from uuid import uuid4

from kairos_core.contracts import (
    SimulationAssumptionsV1,
    SimulationStrategyRefV1,
)
from kairos_llm.models import DEFAULT_WORKLOAD_ROUTES
from kairos_text.config import TextSettings
from kairos_text.dedup import EventDeduplicator
from kairos_text.filter import LocalRelevanceFilter
from kairos_text.freshness import EventFreshnessFilter
from kairos_text.normalize import EventNormalizer

from .current_capture import TEXT_FEEDS, CurrentPublicCapture
from .current_deferred import (
    DeferredSimulationPlan,
    ObservedSimulationRequests,
    import_complete_tape,
    replay_observed_requests,
)
from .current_inputs import UNIVERSE, CurrentObservationSource, _directional_prices, build_current_cut_inputs
from .current_resources import isolated_resources
from .current_runner import (
    CurrentRunConfig,
    CurrentRunServices,
    OpenRiskSnapshot,
    run_one_cut,
    write_create_only,
)
from .current_runtime import append_evidence, build_existing_gateway, canonical, read_existing_openai_key
from .current_tape import ContinuousNativeTape

ROOT = Path("D:/Kairos/runtime/current-system-20261022")
PUBLIC_BOOK_ROOT = Path("C:/Users/loval/Documents/ChatGPT/Kairos/current-system-public-capture-20261022")
STRATEGY_ID = "closed-catalyst-hypothesis.research.v1"
REVISION = "current-chain.observed-sim.v2"
TEXT_FEED = "https://www.coindesk.com/arc/outboundfeeds/rss"


class PhaseBoundedCapture:
    """One finite source roster; waiting for a cut never resets an old capture.

    Every HTTP phase has a new independently retained 120s source receipt.
    This facade additionally limits their total to 40 requests / 32 MiB.
    """

    def __init__(self, output: Path, *, require_fresh_news: bool = False, text_feed: str = TEXT_FEED):
        if text_feed not in TEXT_FEEDS:
            raise ValueError("EXISTING_CONFIGURED_NEWS_FEED_REQUIRED")
        self.output = output
        self.text_feed = text_feed
        self.requests = 0
        self.bytes_used = 0
        self._text = None
        self._news_model_eligibility = None
        self._history = None
        self._start = time.monotonic()
        self.require_fresh_news = require_fresh_news

    def _phase(self, maximum_requests):
        if (
            time.monotonic() - self._start >= 900
            or self.requests + maximum_requests > 40
            or self.bytes_used >= 32 * 1024 * 1024
        ):
            raise ValueError("CURRENT_TOTAL_PUBLIC_CAPTURE_ENVELOPE_EXCEEDED")
        return CurrentPublicCapture(
            self.output, text_feed=self.text_feed, byte_limit=32 * 1024 * 1024 - self.bytes_used
        )

    def _retain(self, phase):
        self.requests += phase.requests
        self.bytes_used += phase.bytes_used
        append_evidence(
            self.output / "public-phase-budget.jsonl",
            {
                "requests": self.requests,
                "bytes": self.bytes_used,
                "phase_capture_id": phase.capture_id,
                "at_ms": time.time_ns() // 1_000_000,
            },
        )

    async def capture_text(self):
        if self._text is None:
            phase = self._phase(1)
            try:
                self._text = await phase.capture_text()
            finally:
                self._retain(phase)
        if self._news_model_eligibility is None:
            self._news_model_eligibility = self._assess_news_model_eligibility(self._text)
            write_create_only(self.output / "news-model-eligibility.json", self._news_model_eligibility)
        if self.require_fresh_news and not self._news_model_eligibility["eligible"]:
            raise ValueError("VERIFICATION_NEEDS_FRESH_NEWS_BEFORE_PAID_CALLS")
        return self._text

    @staticmethod
    def _assess_news_model_eligibility(snapshot) -> dict:
        settings = TextSettings(
            _env_file=None,
            bus_backend="memory",
            service_name="kairos-current-chain-text",
            enable_gdelt=False,
            enable_rss=False,
        )
        actual_at_ms = time.time_ns() // 1_000_000
        actual_now = datetime.fromtimestamp(actual_at_ms / 1_000, tz=UTC)
        captured = tuple(snapshot.news_items)
        normalized = EventNormalizer().normalize(captured)
        timely = EventFreshnessFilter(
            settings.max_event_age_s,
            settings.max_future_skew_s,
            allow_estimated_timestamps=settings.allow_estimated_timestamps,
            clock=lambda: actual_now,
        ).select(normalized)
        deduplicator = EventDeduplicator(settings.dedup_window_s)
        collapsed = deduplicator.collapse_batch(timely)
        unseen = deduplicator.filter_unseen(collapsed)
        selected = LocalRelevanceFilter(settings.relevance_threshold, settings.top_k).select(unseen)
        capture_sha256 = getattr(snapshot, "sha256", None)
        if not isinstance(capture_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", capture_sha256) is None:
            raise ValueError("EXACT_CAPTURED_TEXT_SNAPSHOT_HASH_REQUIRED")
        return {
            "schema": "kairos.current-news-model-eligibility.v1",
            "state": "ELIGIBLE" if selected else "NO_ELIGIBLE_NEWS",
            "eligible": bool(selected),
            "required_selected_item_count": 1,
            "captured_item_count": len(captured),
            "normalized_item_count": len(normalized),
            "timely_item_count": len(timely),
            "collapsed_unique_item_count": len(collapsed),
            "unseen_item_count": len(unseen),
            "selected_item_count": len(selected),
            "relevance_threshold": settings.relevance_threshold,
            "top_k": settings.top_k,
            "settings_bounds": {
                "max_event_age_s": settings.max_event_age_s,
                "max_future_skew_s": settings.max_future_skew_s,
                "allow_estimated_timestamps": settings.allow_estimated_timestamps,
                "dedup_window_s": settings.dedup_window_s,
            },
            "capture_sha256": capture_sha256,
            "actual_at_ms": actual_at_ms,
            "secrets_included": False,
        }

    async def fetch_history(self, cut_ms):
        if self._history is not None:
            if self._history.cut_ms != cut_ms:
                raise ValueError("ONE_CURRENT_HISTORY_ONLY")
            return self._history
        phase = self._phase(15)
        try:
            self._history = await phase.fetch_history(cut_ms)
        finally:
            self._retain(phase)
        return self._history

    async def fresh_quote(self, symbol):
        phase = self._phase(1)
        try:
            return await phase.fresh_quote(symbol)
        finally:
            self._retain(phase)


def scope(*, text_feed: str = TEXT_FEED):
    if text_feed not in TEXT_FEEDS:
        raise ValueError("EXISTING_CONFIGURED_NEWS_FEED_REQUIRED")
    return {
        "schema": "kairos.current-system-verification-plan.v1",
        "mode": "CURRENT_OBSERVED_DECISIONS_THEN_SEALED_NATIVE_SIM_REPLAY",
        "components": [
            "current Catalyst",
            "TextScoutsService",
            "MacroStrategist",
            "CandidateRouterPolicy",
            "CandidateReviewBrain",
            "SimulationRiskPolicy",
            "SimulationExecutionController",
        ],
        "sources": "fixed-five public Binance USD-M plus one existing configured RSS snapshot",
        "text_feed": text_feed,
        "maximum_openai_calls": 24,
        "local_cap_microusd": 1_000_000,
        "existing_cumulative_cap_microusd": 12_000_000,
        "new_key_or_project": False,
        "provider_retries": 0,
        "readiness_promotion": False,
        "real_venue_orders": False,
        "historical_test": False,
        "maximum_continuous_native_book_window_seconds": 900,
        "initial_quant_window_seconds": 70,
        "blind_campaign_credit": False,
        "external_macro_release_coverage": "NOT_ESTABLISHED",
        "continuous_original_tape_and_full_provenance_required": True,
        "actual_live_risk_or_execution": False,
    }


def initial_execution_compatibility(initial, *, cut_ms: int, observed_ms: int) -> dict:
    """Refuse permanent incompatibilities before spending on a finite tape.

    This is a necessary-condition check, not a source/admission certificate.
    No frame is retimed and a complete count is not proof of matching bar IDs.
    Once sealed, this driver's initial tape cannot accept the later provenance
    or future execution frames. Its ``latest`` source never advances either.
    """
    if any(type(value) is not int or value < 0 for value in (cut_ms, observed_ms)):
        raise ValueError("EXACT_COMPATIBILITY_CLOCKS_REQUIRED")
    earliest_ms = max(cut_ms, observed_ms)
    bars = dict(initial.closed_bars)
    rows = []
    for symbol in UNIVERSE:
        frames = [frame for frame in initial.frames if frame.symbol == symbol]
        frame = max(frames, key=lambda item: item.tape_sequence, default=None)
        reasons = []
        age_ms = latency_ms = None
        if frame is None:
            reasons.append("NO_INITIAL_BOOK_FRAME")
        else:
            age_ms = earliest_ms - frame.persisted_at_ms
            latency_ms = frame.persisted_at_ms - frame.exchange_at_ms
            if frame.tape_id != initial.tape_id or frame.continuity != "ADMITTED":
                reasons.append("INITIAL_BOOK_IDENTITY_OR_CONTINUITY_CONFLICT")
            if frame.persisted_at_ms > observed_ms:
                reasons.append("INITIAL_BOOK_PERSISTENCE_FROM_FUTURE")
            if age_ms > 5_000:
                reasons.append("FROZEN_INITIAL_BOOK_ALREADY_STALE_AT_EARLIEST_DECISION")
            if not 0 <= latency_ms <= 1_000:
                reasons.append("INITIAL_BOOK_SOURCE_LATENCY_EXCEEDED")
        bar_count = len(bars.get(symbol, ()))
        missing_lower_bound = max(0, 3_240 - bar_count)
        if missing_lower_bound:
            reasons.append("SEALED_INITIAL_TAPE_TOO_SHORT_FOR_54H_INTENT_PROVENANCE")
        rows.append(
            {
                "symbol": symbol,
                "latest_original_frame_sha256": frame.frame_sha256 if frame else None,
                "latest_original_frame_persisted_ms": frame.persisted_at_ms if frame else None,
                "age_at_earliest_decision_ms": age_ms,
                "source_latency_ms": latency_ms,
                "sealed_initial_closed_bar_count": bar_count,
                "minimum_missing_history_bar_count": missing_lower_bound,
                "reasons": reasons,
            }
        )
    blocked = [row["symbol"] for row in rows if row["reasons"]]
    return {
        "schema": "kairos.current-initial-execution-compatibility.v1",
        "state": "EXECUTION_INCOMPATIBLE" if blocked else "NECESSARY_CHECKS_ONLY_NOT_ADMISSION",
        "observed_ms": observed_ms,
        "earliest_decision_ms": earliest_ms,
        "original_tape_id": initial.tape_id,
        "initial_tape_sealed": True,
        "latest_frame_source_advances": False,
        "maximum_book_age_ms": 5_000,
        "maximum_frame_latency_ms": 1_000,
        "required_history_bars_per_symbol": 3_240,
        "symbols": rows,
        "blocked_symbols": blocked,
        "no_symbol_can_reach_native_sim_entry": len(blocked) == len(UNIVERSE),
        "bar_identity_and_future_observation_coverage_proven": False,
        "risk_authority": "NONE",
    }


def macro_context_factory(
    *, config, history, text, quotes, simulation_repository, official_macro_context=None
):
    """Truthful SIM context, not invented CPI, rates or an actual account balance."""
    del simulation_repository
    quote_map = {item.symbol: item for item in quotes}
    return canonical(
        {
            "mode": "ISOLATED_ENGINEERING_SIM_NOT_A_REAL_PORTFOLIO",
            "as_of_ms": time.time_ns() // 1_000_000,
            "scheduled_cut_ms": config.cut_ms,
            "portfolio": {
                "equity_usd": 10_000.0,
                "origin": "EXPLICIT_SIM_ASSUMPTION",
                "open_positions": [],
                "closed_trades": [],
                "no_real_money": True,
            },
            "market_factors": {
                "status": "observed",
                "source": "public Binance USD-M",
                "history_captured_ms": history.captured_ms,
                "symbols": {
                    symbol: {
                        "closed_prices": _directional_prices(tuple(history.bars_by_symbol[symbol])),
                        "bid": quote_map[symbol].entry_quote.bid,
                        "ask": quote_map[symbol].entry_quote.ask,
                        "quote_received_ms": quote_map[symbol].received_ms,
                    }
                    for symbol in UNIVERSE
                },
            },
            "news": {
                "status": "observed_single_RSS_snapshot",
                "coverage_scope": text.coverage_scope,
                "raw_sha256": text.raw_sha256,
                "received_ms": text.received_ms,
                "items": [
                    {
                        "title": item.title,
                        "body": item.body,
                        "url": item.url,
                        "published_at": item.published_at.isoformat(),
                    }
                    for item in text.news_items
                ],
            },
            "macro_factors": official_macro_context
            or {"status": "unavailable", "reason": "no admitted current macro release feed"},
            "onchain_factors": {"status": "unavailable", "reason": "no admitted current onchain feed"},
            "limits": {
                "risk_per_trade": 0.0025,
                "aggregate_open_risk": 0.01,
                "frequency": "natural, including zero; no daily quota",
            },
        }
    ).decode("utf-8")


def installed_source_identity():
    """Attest actual installed noneditable sources, not a different old checkout."""
    names = (
        "kairos-core",
        "kairos-persistence",
        "kairos-strategy-engine",
        "kairos-router",
        "kairos-llm",
        "kairos-aggregator",
        "kairos-risk-manager",
        "kairos-execution-engine",
        "kairos-text-scouts",
        "kairos-macro-strategist",
        "kairos-quant-scouts",
    )
    result = {}
    for name in names:
        direct = json.loads(importlib.metadata.distribution(name).read_text("direct_url.json") or "{}")
        commit = direct.get("vcs_info", {}).get("commit_id")
        if not commit or direct.get("dir_info", {}).get("editable"):
            raise ValueError("CURRENT_INSTALLED_GIT_SOURCE_REQUIRED")
        result[name] = commit
    here = Path(__file__).parent
    result["current_adapter_files"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(here.glob("current_*.py"))
    }
    # Catalyst/policy and the reused recorder are the installed existing local
    # engineering package, not one of the Git-installed service distributions.
    import adaptive_replay

    adaptive_root = Path(adaptive_replay.__file__).parent
    result["installed_adaptive_replay_files"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(adaptive_root.glob("*.py"))
    }
    return result


async def execute(*, require_fresh_news: bool = True, capture_only: bool = False, text_feed: str = TEXT_FEED):
    from .current_live import CurrentLiveCapture

    identity = uuid4().hex
    output = ROOT / ("run-" + identity)
    output.mkdir()  # No adoption, overwrite or resumption of old/partial evidence.
    gateway = None
    exit_status = 0
    try:
        sources = installed_source_identity()
        source_sha = hashlib.sha256(canonical(sources)).hexdigest()
        model_routes = {key.value: asdict(value) for key, value in DEFAULT_WORKLOAD_ROUTES.items()}
        model_sha = hashlib.sha256(canonical(model_routes)).hexdigest()
        write_create_only(
            output / "before.json",
            {
                "plan": {
                    **scope(text_feed=text_feed),
                    "require_fresh_news_before_paid_calls": require_fresh_news,
                    "capture_only_no_models": capture_only,
                },
                "sources": sources,
                "model_routes": model_routes,
                "at_ms": time.time_ns() // 1_000_000,
            },
        )
        async with asyncio.timeout(1800), isolated_resources(output) as resources:
            # Resolve only the already-authorized existing key, in memory.
            key = read_existing_openai_key(Path("C:/Users/loval/Documents/keys.txt"))
            gateway, budget = build_existing_gateway(
                key=key, budget_pool=resources.budget_pool, evidence_root=output
            )
            del key
            from .current_macro import capture_current_macro

            official_macro = await capture_current_macro(
                output / ("official-context-20261022-" + uuid4().hex[:12])
            )
            write_create_only(output / "official-macro-context.json", official_macro)
            # This new capture uses the observed faster local volume. Old D:
            # captures are retained in place; fsync/clock/TTL rules are identical.
            PUBLIC_BOOK_ROOT.mkdir(exist_ok=True)
            book_output = PUBLIC_BOOK_ROOT / identity
            book_output.mkdir()
            metric_capture = CurrentPublicCapture(book_output)
            tape = ContinuousNativeTape(
                book_output / "original-continuous-native", "current-native-" + identity
            )
            write_create_only(
                output / "public-book-location.json",
                {"public_book_parent": str(book_output), "old_evidence_moved": False},
            )
            async with CurrentLiveCapture(
                book_output,
                capture=metric_capture,
                tape_id="current-" + identity,
                max_seconds=70,
                observation_seconds=900,
                quote_capture_factory=lambda: CurrentPublicCapture(book_output),
                book_output_root=book_output,
                book_seconds=10,
                continuous_tape=tape,
            ) as live:
                gateway.source_guard = live.assert_continuous_source
                print("Bounded current public capture started; models not called yet", flush=True)
                initial = await live.capture_initial()
                repository = resources.simulation_repository
                # New actual source phase. Do not reset a spent capture's clock/budget.
                capture = PhaseBoundedCapture(
                    output, require_fresh_news=require_fresh_news and not capture_only, text_feed=text_feed
                )
                started_ms = time.time_ns() // 1_000_000
                # A source-only proof needs no 5m strategy decision: the next
                # complete minute suffices for its same 54h original-bar import.
                # Actual model/Catalyst runs retain their original 5m cadence.
                period = 60_000 if capture_only else 300_000
                cut = ((started_ms + period - 1) // period) * period
                if cut - started_ms < 30_000:
                    cut += period
                # The source epoch began at the original verified handshake.
                # Neither a later cut nor a slow setup renews its 900s budget.
                live.required_source_until_ms = cut + (0 if capture_only else 300_000 + 120_000)
                live.assert_continuous_source()
                session = DeferredSimulationPlan(
                    tape_id=initial.tape_id,
                    assumptions=SimulationAssumptionsV1(
                        latency_ms=25,
                        maximum_book_age_ms=5_000,
                        maximum_frame_latency_ms=1_000,
                        depth_participation_fraction=0.1,
                        adverse_slippage_bps=2.0,
                        taker_fee_bps=5.0,
                        price_tick=0.0001,
                        quantity_step=0.000001,
                    ),
                    strategy_allowlist=(
                        SimulationStrategyRefV1(strategy_id=STRATEGY_ID, strategy_revision=REVISION),
                    ),
                    started_at_ms=tape.capture_started_ms,
                    ends_at_ms=tape.capture_started_ms + 900_000,
                    source_set_sha256=source_sha,
                    model_config_sha256=model_sha,
                )
                requests = ObservedSimulationRequests(session, output / "deferred-sim-requests")

                async def open_risk_snapshot():
                    async with resources.sim_database.pool.acquire() as connection:
                        async with connection.transaction(readonly=True):
                            count = await connection.fetchval("SELECT count(*) FROM sim_trades")
                    if count:
                        raise ValueError("CURRENT_NEW_SESSION_NOT_EMPTY")
                    at = time.time_ns() // 1_000_000
                    payload = {
                        "deferred_plan_sha256": session.sha256,
                        "trade_rows": 0,
                        "equity_usd": 10_000,
                        "open_risk_microusd": 0,
                        "at_ms": at,
                    }
                    append_evidence(output / "account-baseline.jsonl", payload)
                    return OpenRiskSnapshot(0, at, hashlib.sha256(canonical(payload)).hexdigest())

                config = CurrentRunConfig(
                    output_path=output / "current-chain-result.json",
                    capture_start_ms=started_ms,
                    capture_end_ms=cut,
                    cut_ms=cut,
                    source_set_sha256=source_sha,
                    model_config_sha256=model_sha,
                    strategy_ids=(STRATEGY_ID,),
                    run_id=identity,
                )
                observation = CurrentObservationSource(live, live, max_wait_ms=300_000, max_observations=5)
                services = CurrentRunServices(
                    capture=capture,
                    gateway=gateway,
                    simulation_repository=repository,
                    usage_snapshot=budget.snapshot,
                    open_risk_snapshot=open_risk_snapshot,
                    macro_context_factory=partial(
                        macro_context_factory, official_macro_context=official_macro
                    ),
                    build_cut_inputs=build_current_cut_inputs,
                    observation_source=observation,
                    risk_frame_source=live,
                    quant_measurements_by_symbol=initial.quant_measurements_by_symbol,
                    simulation_session=session,
                    tape_id=initial.tape_id,
                    requested_quantities=tuple((symbol, 0.000001) for symbol in UNIVERSE),
                    deferred_requests=requests,
                )
                print("Current chain starting at its declared cut; cumulative budget retained", flush=True)
                if capture_only:
                    while (remaining := (cut - time.time_ns() // 1_000_000) / 1_000) > 0:
                        await asyncio.sleep(min(10.0, remaining))
                    await capture.fetch_history(cut)
                    result = {"result": "SOURCE_TAPE_ONLY_NO_MODEL_OR_TRADE_VERIFICATION"}
                else:
                    result = await run_one_cut(config, services)
                # Requests are already immutable. Only actual later source bars
                # are observed; no forced price, trade, stop, or close is added.
                future_until = min(
                    session.ends_at_ms - 5_000,
                    time.time_ns() // 1_000_000 + (120_000 if requests.requests else 0),
                )
                while time.time_ns() // 1_000_000 < future_until:
                    live.assert_continuous_source()
                    await asyncio.sleep(min(5.0, (future_until - time.time_ns() // 1_000_000) / 1_000))
                await live.finish_observations()
                native_receipt = await live.finish_native()
                write_create_only(output / "continuous-source-receipt.json", native_receipt)
                if capture._history is None:
                    raise ValueError("FULL_CAPTURED_HISTORY_REQUIRED_BEFORE_NATIVE_SEAL")
                print("Importing complete original source tape; no provider calls in replay", flush=True)
                bar_counts, replay_bars = await import_complete_tape(
                    repository,
                    tape_id=tape.tape_id,
                    history=capture._history,
                    observed_bars=live.closed_bar_roster(),
                    frames=tape.frames,
                )
                seal = await repository.seal_tape(tape.tape_id, sealed_at_ms=time.time_ns() // 1_000_000)
                replay = await replay_observed_requests(
                    repository, requests, seal=seal, bars=replay_bars, frames=tape.frames
                )
                write_create_only(
                    output / "native-tape-verification.json",
                    {
                        "state": "PASS_RECORDED_NATIVE_SOURCE_TAPE_ONLY",
                        "tape_sha256": seal.tape_sha256,
                        "tape_id": tape.tape_id,
                        "plan_sha256": session.sha256,
                        "session_id": replay["session_id"],
                        "full_closed_bar_counts": bar_counts,
                        "original_v2_frame_count": len(tape.frames),
                        "observed_request_count": len(requests.requests),
                        "capture_only_no_models": capture_only,
                        "replay_mode": replay["mode"],
                        "readiness_promotion": False,
                    },
                )
                if capture_only:
                    print(
                        json.dumps({"result": result["result"], "receipt_directory": str(output)}), flush=True
                    )
                    return 2
                from .current_acceptance import assess_directory

                acceptance = assess_directory(output)
                write_create_only(output / "verification-acceptance.json", acceptance)
                if acceptance["missing_required_evidence"]:
                    exit_status = 2
                print(
                    json.dumps(
                        {
                            "result": result["result"],
                            "real_path_acceptance": acceptance["state"],
                            "budget_delta": result.get("budget_delta"),
                            "receipt_directory": str(output),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    except BaseException as exc:
        # Preserve partial evidence without printing provider/credential/backend errors.
        path = output / "bootstrap-failure.json"
        if not path.exists():
            category = str(exc).partition(":")[0]
            safe_category = category if re.fullmatch(r"[A-Z0-9_]{1,128}", category) else None
            write_create_only(
                path,
                {
                    "state": "FAILED_CLOSED",
                    "exception_type": type(exc).__name__,
                    "safe_category": safe_category,
                    "at_ms": time.time_ns() // 1_000_000,
                    "no_readiness_promotion": True,
                },
            )
        print(
            json.dumps(
                {
                    "result": "FAILED_CLOSED",
                    "exception_type": type(exc).__name__,
                    "receipt_directory": str(output),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 1
    finally:
        if gateway is not None:
            await gateway.close()
    return exit_status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--require-fresh-news", action="store_true")
    parser.add_argument("--text-feed", choices=tuple(TEXT_FEEDS), default=TEXT_FEED)
    parser.add_argument(
        "--capture-only", action="store_true", help="Real public tape preflight; no model calls"
    )
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps(scope(text_feed=args.text_feed), indent=2, ensure_ascii=False))
        return 0
    from adaptive_replay.public_book_capture import CaptureOwner

    # One OS-owned full-run exclusion across output UUIDs. Stale metadata never
    # resumes/retries a failed run, and a concurrent run cannot duplicate it.
    with CaptureOwner(ROOT):
        return asyncio.run(
            execute(require_fresh_news=True, capture_only=args.capture_only, text_feed=args.text_feed)
        )


if __name__ == "__main__":
    raise SystemExit(main())
