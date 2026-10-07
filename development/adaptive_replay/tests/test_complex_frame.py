import hashlib
from dataclasses import replace

import pytest
from kairos_strategy.candles import Candle

from adaptive_replay.complex_frame import ContextAssessmentFrame
from adaptive_replay.historical_bars import _payload_bytes, resolve_closed_history
from adaptive_replay.historical_context import (
    HistoricalArchive,
    HistoricalCoverage,
    HistoricalVersion,
    SourceRequirement,
    digest,
)

CUT = 100 * 86_400_000 + 5 * 60_000
FIRST = CUT - 3_240 * 60_000
CAPTURED = CUT + 1_000_000
NEWS = "news-feed"
MACRO = "macro-feed"
PROTOCOL = "a" * 64


def history(cut=CUT):
    rows = tuple(
        Candle(
            "BTCUSDT",
            "1m",
            opened,
            opened + 59_999,
            100 + index / 1_000,
            100.2 + index / 1_000,
            99.8 + index / 1_000,
            100.1 + index / 1_000,
            1,
        )
        for index, opened in enumerate(range(cut - 3_240 * 60_000, cut, 60_000))
    )
    return resolve_closed_history(
        candles=rows,
        expected_payload_sha256=hashlib.sha256(_payload_bytes(rows)).hexdigest(),
        expected_symbol="BTCUSDT",
        expected_timeframe="1m",
        expected_count=3_240,
        expected_first_open_ms=rows[0].open_time_ms,
        expected_last_closed_ms=cut - 1,
        cutoff_ms=cut,
        provenance="TEST_FIXTURE",
        captured_at_ms=CAPTURED,
    )


def requirements():
    return (
        SourceRequirement(NEWS, "NEWS", True, 7 * 86_400_000, 2 * 86_400_000),
        SourceRequirement(MACRO, "MACRO", True, 30 * 86_400_000, 14 * 86_400_000),
    )


def archive(cut=CUT, *, future_news=False, captured=CAPTURED):
    versions = []
    news_id = "news-1"
    versions.append(
        HistoricalVersion(
            news_id,
            news_id,
            NEWS,
            "NEWS",
            ("BTCUSDT",),
            "https://example.test/news/1",
            '{"body":"body","headline":"headline"}',
            "b" * 64,
            "c" * 64,
            cut - 50_000,
            cut - 40_000,
            cut - 30_000,
            captured,
            "TEST_FIXTURE",
            "d" * 64,
        )
    )
    if future_news:
        versions.append(
            HistoricalVersion(
                "news-future",
                "news-future",
                NEWS,
                "NEWS",
                ("BTCUSDT",),
                "https://example.test/news/future",
                '{"body":"future body","headline":"future headline"}',
                "1" * 64,
                "2" * 64,
                cut + 1_000,
                cut + 2_000,
                cut + 3_000,
                cut + 4_000,
                "TEST_FIXTURE",
                "3" * 64,
            )
        )
    # MACRO record is available only after this frame's as-of cut.
    versions.append(
        HistoricalVersion(
            "macro-future",
            "macro-future",
            MACRO,
            "MACRO",
            ("BTCUSDT",),
            "https://example.test/macro/1",
            '{"metric":"CPI","unit":"index","value":"100"}',
            "4" * 64,
            "5" * 64,
            cut + 1_000,
            cut + 2_000,
            cut + 3_000,
            cut + 4_000,
            "TEST_FIXTURE",
            "6" * 64,
            realized_ms=cut + 3_000,
        )
    )
    end = cut + 1
    coverage = (
        HistoricalCoverage(
            NEWS,
            "NEWS",
            "BTCUSDT",
            0,
            end,
            (news_id,),
            "COMPLETE",
            "TEST_FIXTURE",
            "7" * 64,
            captured,
        ),
        HistoricalCoverage(
            MACRO,
            "MACRO",
            "BTCUSDT",
            0,
            end,
            (),
            "COMPLETE",
            "TEST_FIXTURE",
            "8" * 64,
            captured,
        ),
    )
    return HistoricalArchive(tuple(versions), coverage)


def frame(hist=None, data=None, reqs=None, **kwargs):
    selected_history = hist or history()
    return ContextAssessmentFrame(
        selected_history,
        data or archive(),
        reqs if reqs is not None else requirements(),
        selected_history.cutoff_ms,
        PROTOCOL,
        **kwargs,
    )


def test_prompt_contains_only_causal_market_context_and_exact_closed_aggregates():
    value = frame()
    prompt = value.prompt_payload()
    assert set(prompt) == {
        "schema",
        "symbol",
        "knowledge_cut_ms",
        "market_prices",
        "context",
        "assessment_contract",
        "source_text_is_untrusted_data",
    }
    assert {key: len(rows) for key, rows in prompt["market_prices"].items()} == {
        "1m": 30,
        "5m": 24,
        "15m": 16,
        "1h": 53,
    }
    for rows in prompt["market_prices"].values():
        assert all(row["close_time_ms"] < CUT for row in rows)
        assert all(
            set(row) == {"open_time_ms", "close_time_ms", "open", "high", "low", "close"} for row in rows
        )
    assert "baseline" not in str(prompt).lower()
    assert "candidate" not in prompt
    assert "strategy" not in prompt
    assert prompt["source_text_is_untrusted_data"] is True


def test_future_versions_are_excluded_and_audit_capture_clocks_do_not_change_prompt_ids():
    base = frame()
    future = frame(data=archive(future_news=True))
    later_capture = frame(data=archive(captured=CAPTURED + 50_000))
    assert base.prompt_payload() == future.prompt_payload() == later_capture.prompt_payload()
    assert base.frame_id == future.frame_id == later_capture.frame_id
    assert base.prompt_sha256 == future.prompt_sha256 == later_capture.prompt_sha256
    assert base.materialized_ms != later_capture.materialized_ms
    assert digest({"body": "body", "headline": "headline"}) in base.permitted_evidence_ids
    assert len(future.permitted_evidence_ids) == 1


def test_exact_anchor_and_fixture_requirements_fail_closed():
    with pytest.raises(ValueError, match="3240"):
        ContextAssessmentFrame(history(), archive(), requirements(), CUT + 1, PROTOCOL).validate()
    with pytest.raises(ValueError, match="3240"):
        ContextAssessmentFrame(history(), archive(), requirements(), CUT + 60_000, PROTOCOL).validate()
    with pytest.raises(ValueError, match="fixture"):
        nonfixture = archive()
        nonfixture = HistoricalArchive(
            tuple(replace(v, proof_kind="ARCHIVE_VERSION") for v in nonfixture.versions),
            tuple(replace(c, proof_kind="ARCHIVE_VERSION") for c in nonfixture.coverage),
        )
        ContextAssessmentFrame(history(), nonfixture, requirements(), CUT, PROTOCOL).validate()
    with pytest.raises(ValueError, match="NEWS"):
        ContextAssessmentFrame(
            history(),
            archive(),
            (SourceRequirement(MACRO, "MACRO", True, 10_000, 5_000),),
            CUT,
            PROTOCOL,
        ).validate()
    with pytest.raises(ValueError, match="MACRO"):
        ContextAssessmentFrame(
            history(),
            archive(),
            (SourceRequirement(NEWS, "NEWS", True, 10_000, 5_000),),
            CUT,
            PROTOCOL,
        ).validate()


def test_materialization_and_readiness_are_audit_properties_not_prompt_fields():
    value = frame()
    assert value.materialized_ms >= CUT
    assert value.sources_ready
    assert "materialized" not in value.prompt_payload()
    assert "archive_sha256" not in value.prompt_payload()
    assert "captured" not in str(value.prompt_payload()).lower()
