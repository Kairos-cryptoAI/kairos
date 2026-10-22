from __future__ import annotations

from types import SimpleNamespace

import pytest
from adaptive_replay.historical_context import HistoricalArchive
from adaptive_replay.official_context_capture import _extract

from kairos_native_campaign.current_macro import describe_official_context


def test_official_monetary_summaries_do_not_invent_missing_cpi_or_rates():
    body = b"""<rss version="2.0"><channel><title>FRB</title>
    <link>https://www.federalreserve.gov/feeds/feeds.htm</link><description>Policy</description>
    <item><title>Federal Reserve issues FOMC statement</title>
    <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm</link>
    <guid>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm</guid>
    <description>Federal Reserve issues FOMC statement</description>
    <pubDate>Wed, 16 Sep 2026 18:00:00 GMT</pubDate></item></channel></rss>"""
    captured = 1_792_685_681_663
    versions = _extract(
        "FED_MONETARY_RSS", body, captured_ms=captured, raw_sha256="a" * 64, proof_sha256="b" * 64
    )
    receipt = {
        "ended_ms": captured + 100,
        "archive_sha256": "c" * 64,
        "source_results": [
            {
                "source_name": "BLS_CPI_RELEASE",
                "url": "https://www.bls.gov/news.release/cpi.htm",
                "status": 403,
                "parse_status": "UNAVAILABLE",
                "error": "HTTP_STATUS_NOT_SUCCESS",
            },
            {
                "source_name": "FED_MONETARY_RSS",
                "url": "https://www.federalreserve.gov/feeds/press_monetary.xml",
                "status": 200,
                "parse_status": "PARSED",
                "error": None,
            },
        ],
    }
    context = describe_official_context(
        receipt, HistoricalArchive(tuple(versions), ()), receipt_sha256="d" * 64
    )
    assert context["status"] == "partial"
    assert context["macro_measurements"] == []
    assert len(context["monetary_publication_summaries"]) == 1
    item = context["monetary_publication_summaries"][0]
    assert item["published_upper_ms"] < item["captured_ms"] == captured
    assert item["payload"]["headline"] == "Federal Reserve issues FOMC statement"
    assert context["source_statuses"][0]["status"] == 403


def test_official_context_future_capture_is_not_backdated():
    with pytest.raises(ValueError, match="OFFICIAL_CONTEXT_AFTER_CAPTURE"):
        describe_official_context(
            {"ended_ms": 100},
            SimpleNamespace(versions=(SimpleNamespace(captured_ms=101),)),
            receipt_sha256="a" * 64,
        )
