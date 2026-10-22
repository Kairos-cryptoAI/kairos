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
from functools import partial
from pathlib import Path
from uuid import uuid4

from kairos_core.contracts import (
    SimulationAssumptionsV1,
    SimulationSessionV1,
    SimulationStrategyRefV1,
)
from kairos_llm.models import DEFAULT_WORKLOAD_ROUTES
from kairos_strategy.runtime import candle_to_closed_bar

from .current_capture import CurrentPublicCapture
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

    def __init__(self, output: Path):
        self.output = output
        self.requests = 0
        self.bytes_used = 0
        self._text = None
        self._history = None
        self._start = time.monotonic()

    def _phase(self, maximum_requests):
        if (
            time.monotonic() - self._start >= 900
            or self.requests + maximum_requests > 40
            or self.bytes_used >= 32 * 1024 * 1024
        ):
            raise ValueError("CURRENT_TOTAL_PUBLIC_CAPTURE_ENVELOPE_EXCEEDED")
        return CurrentPublicCapture(
            self.output, text_feed=TEXT_FEED, byte_limit=32 * 1024 * 1024 - self.bytes_used
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
        return self._text

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


def scope():
    return {
        "schema": "kairos.current-system-verification-plan.v1",
        "mode": "CURRENT_PROSPECTIVE_ENGINEERING_SIM_ONLY",
        "components": [
            "current Catalyst",
            "TextScoutsService",
            "MacroStrategist",
            "CandidateRouterPolicy",
            "CandidateReviewBrain",
            "SimulationRiskPolicy",
            "SimulationExecutionController",
        ],
        "sources": "fixed-five public Binance USD-M plus one existing configured CoinDesk RSS snapshot",
        "maximum_openai_calls": 24,
        "local_cap_microusd": 1_000_000,
        "existing_cumulative_cap_microusd": 12_000_000,
        "new_key_or_project": False,
        "provider_retries": 0,
        "readiness_promotion": False,
        "real_venue_orders": False,
        "historical_test": False,
        "initial_native_book_window_seconds": 10,
        "initial_quant_window_seconds": 70,
        "blind_campaign_credit": False,
        "external_macro_release_coverage": "NOT_ESTABLISHED",
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


async def execute():
    from .current_live import CurrentLiveCapture

    identity = uuid4().hex
    output = ROOT / ("run-" + identity)
    output.mkdir()  # No adoption, overwrite or resumption of old/partial evidence.
    gateway = None
    try:
        sources = installed_source_identity()
        source_sha = hashlib.sha256(canonical(sources)).hexdigest()
        model_routes = {key.value: asdict(value) for key, value in DEFAULT_WORKLOAD_ROUTES.items()}
        model_sha = hashlib.sha256(canonical(model_routes)).hexdigest()
        write_create_only(
            output / "before.json",
            {
                "plan": scope(),
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
            ) as live:
                print("Bounded current public capture started; models not called yet", flush=True)
                initial = await live.capture_initial()
                repository = resources.simulation_repository
                for frame in initial.frames:
                    await repository.record_book_frame(frame)
                for _symbol, bars in initial.closed_bars:
                    if not bars:
                        raise ValueError("INITIAL_FIVE_SYMBOL_CLOSED_BARS_REQUIRED")
                    for captured in bars:
                        await repository.record_closed_bar(
                            initial.tape_id, candle_to_closed_bar(captured.candle)
                        )
                seal = await repository.seal_tape(initial.tape_id, sealed_at_ms=time.time_ns() // 1_000_000)
                if not await repository.verify_tape(initial.tape_id):
                    raise ValueError("CURRENT_NATIVE_TAPE_VERIFICATION_FAILED")
                # New actual source phase. Do not reset a spent capture's clock/budget.
                capture = PhaseBoundedCapture(output)
                started_ms = time.time_ns() // 1_000_000
                cut = ((started_ms + 299_999) // 300_000) * 300_000
                if cut - started_ms < 30_000:
                    cut += 300_000
                session = SimulationSessionV1(
                    source="kairos-current-system-verification",
                    tape_id=initial.tape_id,
                    tape_sha256=seal.tape_sha256,
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
                    started_at_ms=started_ms,
                    ends_at_ms=cut + 15 * 60_000,
                )
                await repository.create_session(session)

                async def open_risk_snapshot():
                    async with resources.sim_database.pool.acquire() as connection:
                        async with connection.transaction(readonly=True):
                            count = await connection.fetchval(
                                "SELECT count(*) FROM sim_trades WHERE session_id=$1", session.session_id
                            )
                    if count:
                        raise ValueError("CURRENT_NEW_SESSION_NOT_EMPTY")
                    at = time.time_ns() // 1_000_000
                    payload = {
                        "session_id": session.session_id,
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
                )
                print("Current chain starting at its declared cut; cumulative budget retained", flush=True)
                result = await run_one_cut(config, services)
                print(
                    json.dumps(
                        {
                            "result": result["result"],
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
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps(scope(), indent=2, ensure_ascii=False))
        return 0
    from adaptive_replay.public_book_capture import CaptureOwner

    # One OS-owned full-run exclusion across output UUIDs. Stale metadata never
    # resumes/retries a failed run, and a concurrent run cannot duplicate it.
    with CaptureOwner(ROOT):
        return asyncio.run(execute())


if __name__ == "__main__":
    raise SystemExit(main())
