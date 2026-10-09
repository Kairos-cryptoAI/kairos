"""Synthetic TEST-only coverage for the bounded official-context capture."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from adaptive_replay import official_context_capture as capture
from adaptive_replay.historical_context import import_archive

CAPTURE_MS = 1_800_000_000_000
BLS_TEST_HTML = b"""<!doctype html><html><body>
Transmission of material in this release is embargoed until
8:30 a.m. (ET) Friday, September 12, 2025
CONSUMER PRICE INDEX - AUGUST 2025
The Consumer Price Index for All Urban Consumers (CPI-U) increased 0.4 percent
on a seasonally adjusted basis in August after rising 0.1 percent in July,
the U.S. Bureau of Labor Statistics reported today. Over the last 12 months,
the all items index increased 3.4 percent before seasonal adjustment.
</body></html>"""
FED_TEST_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>TEST Federal Reserve</title>
<link>https://www.federalreserve.gov/</link><description>TEST feed</description><item>
<title>TEST: Federal Reserve monetary policy statement</title>
<link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20250917a.htm</link>
<guid>TEST-monetary-20250917</guid>
<pubDate>Wed, 17 Sep 2025 14:00:00 GMT</pubDate>
<description><![CDATA[<p>Synthetic test statement body.</p>]]></description>
</item></channel></rss>"""


class FakeBody:
    def __init__(self, body: bytes):
        self.body = body

    async def iter_chunked(self, size):
        chunk_size = min(size, 8_192)
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]


class FakeResponse:
    def __init__(self, url: str, body: bytes, *, status: int = 200):
        self.url = url
        self.status = status
        self.content = FakeBody(body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


def _install_http(monkeypatch, responses: dict[str, FakeResponse]):
    calls = []

    class FakeSession:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def get(self, url, **kwargs):
            calls.append(url)
            assert kwargs["allow_redirects"] is False
            assert kwargs["proxy"] is None
            assert kwargs["ssl"].check_hostname is True
            return responses[url]

    fake = SimpleNamespace(
        ClientTimeout=lambda **kwargs: SimpleNamespace(**kwargs),
        ClientSession=FakeSession,
    )
    monkeypatch.setitem(sys.modules, "aiohttp", fake)
    return calls


def _responses(*, bls=BLS_TEST_HTML, fed=FED_TEST_XML, bls_status=200, fed_status=200):
    return {
        capture.BLS_URL: FakeResponse(capture.BLS_URL, bls, status=bls_status),
        capture.FED_URL: FakeResponse(capture.FED_URL, fed, status=fed_status),
    }


def _output(tmp_path: Path, suffix: str = "synthetic-test") -> Path:
    return tmp_path / f"official-context-20261009-{suffix}"


def test_capture_retains_exact_source_bytes_and_exports_exact_version_records(tmp_path, monkeypatch):
    calls = _install_http(monkeypatch, _responses())
    times = iter(CAPTURE_MS + step for step in (0, 10, 20, 30, 40, 50))
    monkeypatch.setattr(capture, "wall_ms", lambda: next(times))

    receipt = asyncio.run(capture.capture_official_context(_output(tmp_path)))

    assert calls == [capture.BLS_URL, capture.FED_URL]
    assert receipt["get_count"] == 2
    assert receipt["retry_count"] == 0
    assert receipt["coverage_status"] == "UNKNOWN"
    assert receipt["all_world_news_complete"] is False
    assert receipt["historical_availability_proven"] is False
    assert receipt["provenance_authenticity_verified"] is False
    assert receipt["trading_authority"] is False
    source_results = {row["source_name"]: row for row in receipt["source_results"]}
    assert source_results["BLS_CPI_RELEASE"]["parse_status"] == "PARSED"
    assert source_results["FED_MONETARY_RSS"]["parse_status"] == "PARSED"

    out = _output(tmp_path)
    assert (out / "bls-cpi.html").read_bytes() == BLS_TEST_HTML
    assert (out / "fed-monetary.xml").read_bytes() == FED_TEST_XML
    archive_bytes = (out / "historical-context.json").read_bytes()
    archive = import_archive(archive_bytes, receipt["archive_sha256"])
    assert len(archive.versions) == 4
    assert {version.kind for version in archive.versions} == {"NEWS", "MACRO"}
    assert all(version.proof_kind == "CONTEMPORANEOUS_LOCAL" for version in archive.versions)
    assert all(version.version_available_ms == version.captured_ms for version in archive.versions)
    assert all(
        version.published_upper_ms - version.published_lower_ms == 59_999
        for version in archive.versions
        if version.source_name == "BLS_CPI_RELEASE"
    )
    expected_period = int(datetime(2025, 9, 1, tzinfo=UTC).timestamp() * 1000) - 1
    assert {version.realized_ms for version in archive.versions if version.kind == "MACRO"} == {
        expected_period
    }
    macro = [json.loads(version.payload_json) for version in archive.versions if version.kind == "MACRO"]
    assert {(row["value"], row["unit"]) for row in macro} == {("0.4", "percent"), ("3.4", "percent")}
    assert all("2025-08" in row["metric"] for row in macro)
    # All inputs are hand-authored TEST fixtures, not claims about either publisher.
    fed_versions = [version for version in archive.versions if version.source_name.startswith("FED")]
    assert all("TEST" in json.dumps(json.loads(version.payload_json)) for version in fed_versions)
    assert (out / "plan.json").exists()
    receipt_bytes = (out / "receipt.json").read_bytes()
    before = {
        name: (out / name).read_bytes()
        for name in (
            "plan.json",
            "receipt.json",
            "historical-context.json",
            "bls-cpi.html",
            "fed-monetary.xml",
        )
    }
    assert (
        capture.audit_official_context_capture(out, hashlib.sha256(receipt_bytes).hexdigest())["valid"]
        is True
    )
    assert before == {name: (out / name).read_bytes() for name in before}


@pytest.mark.parametrize(
    "source_bytes, expected_parse",
    [(b"not the official CPI structure", "UNPARSEABLE"), (b"", "UNPARSEABLE")],
)
def test_unparseable_source_bytes_are_retained_with_explicit_unknown_coverage(
    tmp_path, monkeypatch, source_bytes, expected_parse
):
    calls = _install_http(monkeypatch, _responses(bls=source_bytes))
    times = iter([CAPTURE_MS + index for index in range(6)])
    monkeypatch.setattr(capture, "wall_ms", lambda: next(times))

    receipt = asyncio.run(capture.capture_official_context(_output(tmp_path)))

    assert len(calls) == 2
    bls = receipt["source_results"][0]
    assert bls["parse_status"] == expected_parse
    assert bls["raw_bytes"] == len(source_bytes)
    assert bls["raw_sha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert (_output(tmp_path) / "bls-cpi.html").read_bytes() == source_bytes
    assert receipt["coverage_status"] == "UNKNOWN"
    assert receipt["historical_availability_proven"] is False


def test_redirect_and_http_error_are_not_followed_or_retried_and_raw_body_is_kept(tmp_path, monkeypatch):
    calls = _install_http(
        monkeypatch,
        _responses(bls=b"redirect diagnostic", bls_status=302, fed=b"upstream diagnostic", fed_status=503),
    )
    times = iter([CAPTURE_MS + index for index in range(6)])
    monkeypatch.setattr(capture, "wall_ms", lambda: next(times))

    receipt = asyncio.run(capture.capture_official_context(_output(tmp_path)))

    assert calls == [capture.BLS_URL, capture.FED_URL]
    assert [row["attempts"] for row in receipt["source_results"]] == [1, 1]
    assert [row["redirects"] for row in receipt["source_results"]] == [1, 0]
    assert receipt["retry_count"] == 0
    assert (_output(tmp_path) / "bls-cpi.html").read_bytes() == b"redirect diagnostic"
    assert (_output(tmp_path) / "fed-monetary.xml").read_bytes() == b"upstream diagnostic"
    assert receipt["version_count"] == 0
    assert all(row["parse_status"] == "UNAVAILABLE" for row in receipt["source_results"])


def test_empty_official_feed_is_distinct_from_known_no_news_and_coverage_stays_unknown(tmp_path, monkeypatch):
    empty_feed = b"<rss version='2.0'><channel><title>TEST</title><link>https://www.federalreserve.gov/</link><description>TEST</description></channel></rss>"
    _install_http(monkeypatch, _responses(fed=empty_feed))
    times = iter([CAPTURE_MS + index for index in range(6)])
    monkeypatch.setattr(capture, "wall_ms", lambda: next(times))

    receipt = asyncio.run(capture.capture_official_context(_output(tmp_path)))

    assert receipt["source_results"][1]["parse_status"] == "EMPTY_FEED"
    assert receipt["source_results"][1]["version_record_ids"] == []
    assert receipt["coverage_status"] == "UNKNOWN"
    assert receipt["all_world_news_complete"] is False


def test_partial_response_failure_retains_exact_prefix_and_is_not_parsed(tmp_path, monkeypatch):
    responses = _responses()

    class BrokenBody:
        async def iter_chunked(self, _size):
            yield b"TEST partial source bytes"
            raise OSError("TEST read break")

    responses[capture.BLS_URL].content = BrokenBody()
    _install_http(monkeypatch, responses)
    times = iter(CAPTURE_MS + step for step in range(6))
    monkeypatch.setattr(capture, "wall_ms", lambda: next(times))

    receipt = asyncio.run(capture.capture_official_context(_output(tmp_path)))

    bls = receipt["source_results"][0]
    assert bls["body_complete"] is False
    assert bls["error"] == "OSError_PREFIX_RETAINED"
    assert bls["parse_status"] == "UNAVAILABLE"
    assert bls["raw_sha256"] == hashlib.sha256(b"TEST partial source bytes").hexdigest()
    assert (_output(tmp_path) / "bls-cpi.html").read_bytes() == b"TEST partial source bytes"
    assert receipt["coverage_status"] == "UNKNOWN"


def test_default_cli_is_noop_and_existing_output_cannot_be_overwritten(tmp_path, monkeypatch, capsys):
    real_run = asyncio.run

    def forbidden(*args, **kwargs):
        raise AssertionError("default CLI must not run network or write output")

    monkeypatch.setattr(capture.asyncio, "run", forbidden)
    output = _output(tmp_path)
    assert capture.main(["--workspace-root", str(tmp_path), "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "NOT_STARTED"
    assert not output.exists()

    output.mkdir()
    marker = output / "untouched.txt"
    marker.write_text("TEST keep", encoding="utf-8")
    _install_http(monkeypatch, _responses())
    with pytest.raises(FileExistsError):
        real_run(capture.capture_official_context(output))
    assert marker.read_text(encoding="utf-8") == "TEST keep"


def test_capture_lock_excludes_other_owner_and_is_reusable_after_release(tmp_path):
    with capture.CaptureOwner(tmp_path):
        with pytest.raises((OSError, BlockingIOError)):
            with capture.CaptureOwner(tmp_path):
                pass
    with capture.CaptureOwner(tmp_path):
        pass


@pytest.mark.parametrize(
    "xml",
    [
        b"<rss version='2.0' extra='bad'><channel><title>a</title><link>https://www.federalreserve.gov/</link><description>x</description></channel></rss>",
        b"<rss version='2.0'><channel><title>a</title><title>b</title><link>https://www.federalreserve.gov/</link><description>x</description></channel></rss>",
        FED_TEST_XML.replace(b"<guid>TEST-monetary-20250917</guid>", b"<guid>a</guid><guid>b</guid>"),
    ],
)
def test_rss_structure_and_duplicate_identity_fail_closed_but_bytes_are_kept(tmp_path, monkeypatch, xml):
    _install_http(monkeypatch, _responses(fed=xml))
    times = iter(CAPTURE_MS + index for index in range(6))
    monkeypatch.setattr(capture, "wall_ms", lambda: next(times))
    receipt = asyncio.run(capture.capture_official_context(_output(tmp_path)))
    assert (_output(tmp_path) / "fed-monetary.xml").read_bytes() == xml
    assert receipt["source_results"][1]["parse_status"] == "UNPARSEABLE"
    assert receipt["source_results"][1]["version_record_ids"] == []


def test_html_script_and_style_are_not_extracted():
    assert (
        capture._plain_html("<p>Visible</p><script>FAKE HEADLINE</script><style>fake</style><p>text</p>")
        == "Visible text"
    )


def test_cpi_future_reference_period_is_rejected():
    future_period = BLS_TEST_HTML.replace(b"AUGUST 2025", b"SEPTEMBER 2025").replace(
        b"in August after", b"in September after"
    )
    with pytest.raises(ValueError, match="period must end before"):
        capture._extract(
            "BLS_CPI_RELEASE",
            future_period,
            captured_ms=CAPTURE_MS,
            raw_sha256=hashlib.sha256(future_period).hexdigest(),
            proof_sha256="1" * 64,
        )


def test_fed_document_identity_stable_across_feed_versions_and_order():
    other_item = b"""<item><title>TEST Other notice</title>
<link>https://www.federalreserve.gov/newsevents/pressreleases/other.htm</link>
<guid>TEST-other</guid><pubDate>Wed, 17 Sep 2025 13:00:00 GMT</pubDate>
<description>TEST Other body</description></item>"""
    original_item = FED_TEST_XML.split(b"<item>", 1)[1].split(b"</item>", 1)[0]
    first = (
        b"<rss version='2.0'><channel><title>TEST</title><link>https://www.federalreserve.gov/</link><description>TEST</description><item>"
        + original_item
        + b"</item>"
        + other_item
        + b"</channel></rss>"
    )
    reordered = (
        b"<rss version='2.0'><channel><title>TEST</title><link>https://www.federalreserve.gov/</link><description>TEST</description>"
        + other_item
        + b"<item>"
        + original_item
        + b"</item></channel></rss>"
    )
    first_target = next(
        row for row in capture._rss_items(first) if row["headline"].startswith("TEST: Federal")
    )
    reordered_target = next(
        row for row in capture._rss_items(reordered) if row["headline"].startswith("TEST: Federal")
    )
    assert first_target["document_id"] == reordered_target["document_id"]
    first_versions = capture._extract(
        "FED_MONETARY_RSS",
        first,
        captured_ms=CAPTURE_MS,
        raw_sha256=hashlib.sha256(first).hexdigest(),
        proof_sha256="2" * 64,
    )
    reordered_versions = capture._extract(
        "FED_MONETARY_RSS",
        reordered,
        captured_ms=CAPTURE_MS + 1,
        raw_sha256=hashlib.sha256(reordered).hexdigest(),
        proof_sha256="3" * 64,
    )
    first_article = next(row for row in first_versions if row.document_id == first_target["document_id"])
    next_article = next(row for row in reordered_versions if row.document_id == first_target["document_id"])
    assert first_article.document_id == next_article.document_id
    assert first_article.record_id != next_article.record_id
    assert first_article.extraction_policy_sha256 == next_article.extraction_policy_sha256


def test_audit_rejects_unpinned_receipt_and_raw_tampering(tmp_path, monkeypatch):
    _install_http(monkeypatch, _responses())
    times = iter(CAPTURE_MS + index for index in range(6))
    monkeypatch.setattr(capture, "wall_ms", lambda: next(times))
    out = _output(tmp_path)
    asyncio.run(capture.capture_official_context(out))
    receipt = (out / "receipt.json").read_bytes()
    with pytest.raises(ValueError, match="caller pin"):
        capture.audit_official_context_capture(out, "0" * 64)
    (out / "bls-cpi.html").write_bytes(BLS_TEST_HTML + b" ")
    with pytest.raises(ValueError, match="raw source"):
        capture.audit_official_context_capture(out, hashlib.sha256(receipt).hexdigest())


@pytest.mark.parametrize("artifact", ["plan.json", "historical-context.json"])
def test_audit_rejects_plan_or_export_tampering(tmp_path, monkeypatch, artifact):
    _install_http(monkeypatch, _responses())
    times = iter(CAPTURE_MS + index for index in range(6))
    monkeypatch.setattr(capture, "wall_ms", lambda: next(times))
    out = _output(tmp_path)
    asyncio.run(capture.capture_official_context(out))
    pin = hashlib.sha256((out / "receipt.json").read_bytes()).hexdigest()
    path = out / artifact
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        capture.audit_official_context_capture(out, pin)


def test_audit_rejects_impossible_clock_claim_even_with_rehashed_receipt(tmp_path, monkeypatch):
    _install_http(monkeypatch, _responses())
    times = iter(CAPTURE_MS + index for index in range(6))
    monkeypatch.setattr(capture, "wall_ms", lambda: next(times))
    out = _output(tmp_path)
    asyncio.run(capture.capture_official_context(out))
    receipt = json.loads((out / "receipt.json").read_bytes())
    receipt["ended_ms"] = receipt["started_ms"] - 1
    capture._write_json(out / "tampered-receipt.json", receipt, capture.MAX_RECEIPT_BYTES)
    (out / "tampered-receipt.json").replace(out / "receipt.json")
    with pytest.raises(ValueError, match="receipt invariant"):
        capture.audit_official_context_capture(
            out, hashlib.sha256((out / "receipt.json").read_bytes()).hexdigest()
        )


def test_audit_rejects_parser_source_pin_mismatch(tmp_path, monkeypatch):
    _install_http(monkeypatch, _responses())
    times = iter(CAPTURE_MS + index for index in range(6))
    monkeypatch.setattr(capture, "wall_ms", lambda: next(times))
    out = _output(tmp_path)
    asyncio.run(capture.capture_official_context(out))
    receipt = json.loads((out / "receipt.json").read_bytes())
    receipt["parser_sha256_final"] = "0" * 64
    (out / "tampered-receipt.json").write_bytes(capture.canonical(receipt).encode())
    (out / "tampered-receipt.json").replace(out / "receipt.json")
    with pytest.raises(ValueError, match="receipt invariant"):
        capture.audit_official_context_capture(
            out, hashlib.sha256((out / "receipt.json").read_bytes()).hexdigest()
        )
