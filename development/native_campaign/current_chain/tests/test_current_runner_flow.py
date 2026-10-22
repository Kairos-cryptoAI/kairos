"""Actual typed CURRENT runner flow, fixed synthetic sources/model transport.

No chain/fold/builder/Brain/Risk functions are patched. Absent execution book
must reach actual native Risk refusal, never a fabricated SIM admission.
"""

import hashlib
import json
import time
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from adaptive_replay.catalyst_policy_v1 import CatalystEvent
from adaptive_replay.historical_context import HistoricalVersion, canonical
from adaptive_replay.hypothesis_v3 import EntryQuote
from kairos_core.contracts import SimulationStrategyRefV1
from kairos_llm.models import LLMWorkload
from kairos_llm.schemas import LLMResult
from kairos_strategy.candles import Candle
from kairos_text.models import NewsItem
from test_current_chain import prepared_plan, sim_session
from test_current_inputs import _metrics

from kairos_native_campaign import current_runner as runner
from kairos_native_campaign.current_capture import (
    TEXT_COVERAGE_SCOPE,
    CapturedTextSnapshot,
    CurrentHistorySnapshot,
    FreshQuoteSnapshot,
    RawPageReceipt,
)
from kairos_native_campaign.current_inputs import (
    UNIVERSE,
    CapturedClosedBar,
    CurrentObservationSource,
    build_current_cut_inputs,
)


@pytest.mark.asyncio
async def test_actual_typed_run_one_cut_reaches_catalyst_brain_and_native_risk(monkeypatch, tmp_path):
    # Native Macro envelopes use actual construction time. Leave bounded setup
    # slack before our injected future cut, even when pytest starts just before
    # a real five-minute boundary; the news remains inside its native 600s TTL.
    cut = ((time.time_ns() // 1_000_000 + 120_000 + 299_999) // 300_000) * 300_000
    clock = [cut + 10]
    monkeypatch.setattr(runner, "_now_ms", lambda: clock[0])
    body = b"synthetic retained RSS, no source authentication claim"
    sha = hashlib.sha256(body).hexdigest()
    published = time.time_ns() // 1_000_000 - 1_000
    version = HistoricalVersion(
        "version-fixed",
        "doc-fixed",
        "fixture-current-rss",
        "NEWS",
        ("BTCUSDT",),
        "https://example.test/bitcoin",
        canonical({"headline": "Bitcoin exchange announcement", "body": "Bitcoin market news."}),
        sha,
        "e" * 64,
        published,
        published,
        cut - 400,
        cut - 400,
        "CONTEMPORANEOUS_LOCAL",
        "f" * 64,
    )
    news = NewsItem(
        title="Bitcoin exchange announcement",
        body="Bitcoin market news.",
        url=version.url,
        source="fixture-current-rss",
        source_kind="rss",
        published_at=datetime.now(UTC),
        timestamp_is_estimated=False,
    )
    text = CapturedTextSnapshot(
        "fixture-current-rss",
        body,
        sha,
        cut - 1000,
        cut - 500,
        cut - 400,
        (news,),
        (CatalystEvent("fixture-current-rss", "event-fixed", version, cut - 500, 600_000),),
        ("fixed-item",),
        TEXT_COVERAGE_SCOPE,
        tmp_path / "rss.receipt",
    )
    histories = {
        symbol: tuple(
            Candle(symbol, "1m", t, t + 59_999, 100.0, 100.7, 99.3, 100.0, 10.0, 1000.0, 5.0, 500.0)
            for t in range(cut - 3_240 * 60_000, cut, 60_000)
        )
        for symbol in UNIVERSE
    }
    pages = tuple(
        RawPageReceipt(
            "fixture-rest-bars",
            symbol,
            0,
            "https://example.test/bars",
            b"[]",
            hashlib.sha256(b"[]").hexdigest(),
            cut,
            cut + 1,
            cut + 2,
            3_240,
            tmp_path / (symbol + ".bars.receipt"),
        )
        for symbol in UNIVERSE
    )
    history = CurrentHistorySnapshot(
        cut, cut + 2, histories, pages, "FIVE_SYMBOLS_EXACT_54H_CLOSED_1M_BARS_AT_CAPTURE_ONLY"
    )
    metrics = []
    for symbol in UNIVERSE:
        values = _metrics(symbol)
        converted = {}
        for key in (
            "funding_rate",
            "open_interest",
            "oi_change_pct_1h",
            "long_liquidations_usd",
            "short_liquidations_usd",
        ):
            metric = getattr(values, key)
            converted[key] = replace(
                metric,
                event_ms=cut - 1000,
                received_ms=cut - 999,
                captured_ms=cut - 998,
                window_start_ms=cut - 60_000 if metric.window_start_ms is not None else None,
                window_end_ms=cut - 998 if metric.window_end_ms is not None else None,
            )
        metrics.append((symbol, replace(values, **converted)))

    class FixedCapture:
        retained = {}

        async def capture_text(self):
            return text

        async def fetch_history(self, cut_ms):
            assert cut_ms == cut
            return history

        async def fresh_quote(self, symbol):
            at = clock[0]
            bid, ask = (100.09, 100.10) if at >= cut + 60_000 else (99.99, 100.0)
            raw = json.dumps(
                {
                    "E": at,
                    "T": at,
                    "lastUpdateId": 1,
                    "bids": [[str(bid), "100"]],
                    "asks": [[str(ask), "100"]],
                },
                separators=(",", ":"),
            ).encode()
            quote = FreshQuoteSnapshot(
                symbol,
                EntryQuote(
                    "binance_um_rest_depth_snapshot",
                    symbol,
                    bid,
                    ask,
                    at,
                    at,
                    at,
                    5_000,
                    "CALLER_ATTESTED_POINT_IN_TIME",
                ),
                raw,
                hashlib.sha256(raw).hexdigest(),
                at,
                at,
                at,
                100.0,
                100.0,
                tmp_path / (symbol + ".quote.receipt"),
            )
            self.retained[(symbol, quote.entry_quote.sha256)] = quote
            return quote

        def quote_snapshot_for(self, quote):
            return self.retained.get((quote.symbol, quote.sha256))

        async def wait_closed_bar(self, symbol, after_close_ms, *, timeout_s):
            clock[0] = cut + 60_000 + 100
            candle = Candle(
                symbol, "1m", cut, cut + 59_999, 100.0, 100.2, 99.9, 100.1, 10.0, 1000.0, 5.0, 500.0
            )
            raw = b"fixed synthetic closed-bar payload"
            return CapturedClosedBar(
                candle,
                raw,
                "fixture-current-kline",
                candle.close_time_ms,
                clock[0],
                clock[0],
                hashlib.sha256(raw).hexdigest(),
            )

        async def latest(self, symbol):
            return None  # Explicit absent native execution book, never REST promotion.

    class FixedGateway:
        attempts = []
        workloads = []

        async def complete(self, *, system, user, workload, schema, effort=None):
            self.workloads.append(workload)
            if workload is LLMWorkload.TEXT_SCOUTS:
                items = json.loads(user)["items"]
                payload = {
                    "signals": [
                        {
                            "topic": "BTCUSDT",
                            "sentiment": 0.5,
                            "impact": "bullish",
                            "confidence": 0.9,
                            "summary": "Synthetic fixed news only",
                            "item_ids": [item["id"] for item in items],
                        }
                    ]
                }
            elif workload is LLMWorkload.MACRO_STRATEGIST:
                payload = {
                    "regime": "CHOP",
                    "stable_reserve_pct": 0.2,
                    "strategy_weights": [
                        {"strategy_name": "closed-catalyst-hypothesis.research.v1", "weight": 0.8}
                    ],
                    "max_gross_leverage": 1.0,
                    "rationale": "Synthetic model transport only",
                }
            elif schema.__name__ == "DirectionalAssessment":
                payload = {
                    "proposal": "LONG",
                    "long_review": "ALLOW",
                    "short_review": "DEFER",
                    "evidence_ids": json.loads(user)["evidence_ids"],
                }
            else:
                payload = {"decision": "ALLOW", "priority": 1, "reason_codes": ["SYNTHETIC_ONLY"]}
            identity = "synthetic-call-" + str(len(self.attempts) + 1)
            self.attempts.append(
                runner.ProviderAttempt(
                    identity, "openai", workload.value, "synthetic-no-provider", "COMMITTED", 1, 0
                )
            )
            return LLMResult(
                content=json.dumps(payload),
                parsed=schema.model_validate(payload),
                model="synthetic-no-provider",
                resolved_model="synthetic-no-provider",
                effort="medium",
                cost_usd=0.0,
                provider="openai",
                workload=workload.value,
                request_id=identity,
                budget_reservation_id=identity,
                attempt_started_at_ts_ms=clock[0],
                response_observed_at_ts_ms=clock[0],
            )

        async def usage(self):
            return runner.UsageSnapshot(tuple(self.attempts))

    class FixedRepository:
        decisions = []

        async def record_risk_decision(self, decision):
            assert not decision.approved
            self.decisions.append(decision)
            return True

    capture, gateway, repository = FixedCapture(), FixedGateway(), FixedRepository()
    config = runner.CurrentRunConfig(
        tmp_path / "actual-type-run.json",
        cut - 2000,
        cut,
        cut,
        "a" * 64,
        "b" * 64,
        ("closed-catalyst-hypothesis.research.v1",),
        "fixed-run",
    )
    fixture_native = prepared_plan()[-1].intent
    # A synthetic session is a transport input only; actual Risk must refuse
    # because no native book exists. No controller start/entry can occur.
    session = sim_session(fixture_native)
    session = type(session).model_validate(
        {
            **session.model_dump(mode="python"),
            "session_id": None,
            "message_id": "fixed-session",
            "started_at_ms": cut - 2000,
            "ends_at_ms": cut + 900_000,
            "strategy_allowlist": (
                SimulationStrategyRefV1(
                    strategy_id="closed-catalyst-hypothesis.research.v1",
                    strategy_revision="current-chain.observed-sim.v2",
                ),
            ),
        }
    )

    async def risk():
        return runner.OpenRiskSnapshot(0, clock[0], "c" * 64)

    result = await runner.run_one_cut(
        config,
        runner.CurrentRunServices(
            capture=capture,
            gateway=gateway,
            simulation_repository=repository,
            usage_snapshot=gateway.usage,
            open_risk_snapshot=risk,
            macro_context_factory=lambda **kwargs: "{}",
            build_cut_inputs=build_current_cut_inputs,
            observation_source=CurrentObservationSource(capture, capture, clock_ms=lambda: clock[0]),
            risk_frame_source=capture,
            quant_measurements_by_symbol=tuple(metrics),
            simulation_session=session,
            tape_id=session.tape_id,
            requested_quantities=tuple((symbol, 0.001) for symbol in UNIVERSE),
        ),
    )
    assert result["result"] == "COMPLETED"
    assert LLMWorkload.TEXT_SCOUTS in gateway.workloads and LLMWorkload.MACRO_STRATEGIST in gateway.workloads
    assert any(stage["name"].startswith("native_brain_final_review:") for stage in result["stages"])
    assert len(repository.decisions) == 1 and not repository.decisions[0].approved
    outcome = next(item for item in result["sim_outcomes"] if item["symbol"] == "BTCUSDT")
    assert outcome["review_decision"] == "ALLOW"
    assert outcome["risk_rejection_reasons"] == ["NO_RECORDED_BOOK_FRAME"]
    assert outcome["admission_id"] is None and outcome["fill_receipt"] is None
    assert len(gateway.attempts) == 6  # Text, Macro, proposal, two previews, final review.
