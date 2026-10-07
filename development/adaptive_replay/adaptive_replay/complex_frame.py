"""Causal, strategy-blind market/context prompt frame for complex assessment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kairos_strategy.timeframes import aggregate

from .historical_bars import ClosedHistoryPayload
from .historical_context import (
    HistoricalArchive,
    SourceRequirement,
    _clock,
    _sha,
    as_of_context,
    digest,
)

SCHEMA = "kairos.development.context-assessment-frame.v1"
MINUTE_MS = 60_000
FIVE_MINUTE_MS = 300_000
HISTORY_BARS = 54 * 60


@dataclass(frozen=True)
class ContextAssessmentFrame:
    history: ClosedHistoryPayload
    archive: HistoricalArchive
    requirements: tuple[SourceRequirement, ...]
    knowledge_cut_ms: int
    protocol_sha256: str

    def validate(self) -> None:
        if type(self.history) is not ClosedHistoryPayload or type(self.archive) is not HistoricalArchive:
            raise ValueError("exact closed-history and historical-archive contracts required")
        self.history.validate()
        self.archive.validate()
        _clock(self.knowledge_cut_ms)
        _sha(self.protocol_sha256)
        if type(self.requirements) is not tuple or not self.requirements:
            raise ValueError("immutable explicit source requirements required")
        if (
            self.history.timeframe != "1m"
            or len(self.history.candles) != HISTORY_BARS
            or self.knowledge_cut_ms % FIVE_MINUTE_MS
            or self.history.cutoff_ms != self.knowledge_cut_ms
            or self.history.last_closed_ms != self.knowledge_cut_ms - 1
            or self.history.candles[0].open_time_ms != self.knowledge_cut_ms - HISTORY_BARS * MINUTE_MS
        ):
            raise ValueError("exact contiguous 3240-bar 1m history ending at 5m context cut required")
        if not any(req.kind == "NEWS" and req.required for req in self.requirements):
            raise ValueError("at least one required NEWS source requirement is mandatory")
        if not any(req.kind == "MACRO" and req.required for req in self.requirements):
            raise ValueError("at least one required MACRO source requirement is mandatory")
        view = as_of_context(self.archive, self.history.symbol, self.knowledge_cut_ms, self.requirements)
        if view["fixture_only"] != (self.history.provenance == "TEST_FIXTURE"):
            raise ValueError("history and context fixture modes cannot be mixed or relabelled")

    def prompt_payload(self) -> dict[str, Any]:
        self.validate()
        view = as_of_context(self.archive, self.history.symbol, self.knowledge_cut_ms, self.requirements)
        bars = list(self.history.candles)
        five = aggregate(bars, "5m")[-24:]
        fifteen = aggregate(bars, "15m")[-16:]
        hourly = aggregate(bars, "1h")[-54:]
        if len(five) != 24 or len(fifteen) != 16 or len(hourly) < 53:
            raise ValueError("insufficient complete closed higher-timeframe bars")

        def price_bars(rows: list[Any]) -> list[dict[str, int | float]]:
            return [
                {
                    "open_time_ms": row.open_time_ms,
                    "close_time_ms": row.close_time_ms,
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                }
                for row in rows
            ]

        return {
            "schema": SCHEMA,
            "symbol": self.history.symbol,
            "knowledge_cut_ms": self.knowledge_cut_ms,
            "market_prices": {
                "1m": price_bars(bars[-30:]),
                "5m": price_bars(five),
                "15m": price_bars(fifteen),
                "1h": price_bars(hourly),
            },
            "context": view["context"],
            "assessment_contract": {
                "long_review": ["ALLOW", "VETO", "DEFER"],
                "short_review": ["ALLOW", "VETO", "DEFER"],
                "proposal": ["NONE", "LONG", "SHORT"],
                "proposal_requires_directional_allow": True,
                "evidence_ids": "unique content_ref SHA-256 values from supplied context only",
                "no_prices_size_or_confidence_in_response": True,
            },
            "source_text_is_untrusted_data": True,
        }

    @property
    def prompt_sha256(self) -> str:
        return digest(self.prompt_payload())

    @property
    def frame_id(self) -> str:
        return digest(
            {
                "prompt": self.prompt_payload(),
                "protocol_sha256": self.protocol_sha256,
            }
        )

    @property
    def sources_ready(self) -> bool:
        self.validate()
        return as_of_context(self.archive, self.history.symbol, self.knowledge_cut_ms, self.requirements)[
            "required_sources_ready"
        ]

    @property
    def materialized_ms(self) -> int:
        self.validate()
        context = as_of_context(self.archive, self.history.symbol, self.knowledge_cut_ms, self.requirements)
        return max(self.history.captured_at_ms, context["context_materialized_ms"], self.knowledge_cut_ms)

    @property
    def permitted_evidence_ids(self) -> frozenset[str]:
        payload = self.prompt_payload()["context"]
        return frozenset(item["content_ref"] for source in payload["sources"] for item in source["items"])
