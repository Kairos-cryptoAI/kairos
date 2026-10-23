from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kairos_native_campaign import current_macro
from kairos_native_campaign import current_source_probe as probe


def _native_bbo_quote(symbol: str, event_ms: int, received_ms: int, captured_ms: int):
    import hashlib

    from adaptive_replay.quote_capture import PAYLOAD_SCHEMA, BboCapture

    payload = json.dumps(
        {
            "schema_id": PAYLOAD_SCHEMA,
            "timestamp_unit": "ms",
            "source_id": "binance_um_rest_depth_snapshot",
            "symbol": symbol,
            "event_ms": event_ms,
            "bid": 99.0,
            "ask": 100.0,
            "bid_quantity": 2.0,
            "ask_quantity": 2.0,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return BboCapture(
        payload,
        hashlib.sha256(payload).hexdigest(),
        received_ms,
        captured_ms,
        5_000,
        "CALLER_ATTESTED_POINT_IN_TIME",
    ).quote


def test_feed_roster_uses_each_existing_source_once():
    roster = probe._feed_roster()
    assert len(roster) == 2
    assert {probe.TEXT_FEEDS[url][0] for url in roster} == {"cointelegraph_rss", "coindesk_rss"}
    assert "https://www.coindesk.com/arc/outboundfeeds/rss" in roster
    assert "https://www.coindesk.com/arc/outboundfeeds/rss/" not in roster


def test_refused_response_is_charged_before_another_source_uses_remaining_budget():
    capture = SimpleNamespace(requests=1, byte_limit=50, bytes_used=20)
    assert probe._failed_reply_allowance(capture, maximum_body=100) == 30
    assert probe._failed_reply_allowance(capture, maximum_body=10) == 10
    capture.requests = 0
    assert probe._failed_reply_allowance(capture, maximum_body=100) == 0
    assert probe._failed_reply_allowance(None, maximum_body=100) == 0


@pytest.mark.asyncio
async def test_probe_writes_create_only_source_only_summary(tmp_path: Path, monkeypatch):
    output = tmp_path / "sources-20261024-first"
    output.mkdir()

    cut_values: list[int] = []

    class FakeCapture:
        def __init__(self, root, *, text_feed, byte_limit, deadline_seconds):
            self.root = root
            self.text_feed = text_feed
            self.byte_limit = byte_limit
            self.bytes_used = 123
            self.requests = 1

        async def capture_text(self):
            receipt = self.root / f"{probe.TEXT_FEEDS[self.text_feed][0]}.receipt.json"
            receipt.write_text(json.dumps({"raw_item_count": 2, "fresh_item_count": 1}), encoding="utf-8")
            now = 1_800_000_000_000
            return SimpleNamespace(
                source_name=probe.TEXT_FEEDS[self.text_feed][0],
                receipt_path=receipt,
                raw_sha256="a" * 64,
                requested_ms=now - 100,
                received_ms=now,
                persisted_ms=now + 1,
            )

        async def fetch_history(self, cut_ms):
            cut_values.append(cut_ms)
            receipt = self.root / "bars.receipt.json"
            receipt.write_text("{}", encoding="utf-8")
            return SimpleNamespace(
                coverage_scope="FIVE_SYMBOLS_EXACT_54H_CLOSED_1M_BARS_AT_CAPTURE_ONLY",
                bars_by_symbol={symbol: tuple(range(probe.BAR_COUNT)) for symbol in probe.UNIVERSE},
                page_receipts=(SimpleNamespace(receipt_path=receipt),),
            )

        async def fresh_quote(self, symbol):
            now = 1_800_000_000_000
            receipt = self.root / f"{symbol}.depth.receipt.json"
            receipt.write_text("{}", encoding="utf-8")
            return SimpleNamespace(
                raw_sha256="b" * 64,
                requested_ms=now - 100,
                received_ms=now,
                captured_ms=now + 1,
                entry_quote=_native_bbo_quote(symbol, now - 100, now, now + 1),
                receipt_path=receipt,
            )

    monkeypatch.setattr(probe, "CurrentPublicCapture", FakeCapture)
    monkeypatch.setattr(
        probe,
        "_eligibility",
        lambda _snapshot: {"selected_item_count": 0, "eligible": False, "state": "NO_ELIGIBLE_NEWS"},
    )

    async def fake_macro(directory):
        directory.mkdir()
        (directory / "receipt.json").write_text(
            json.dumps({"source_results": [{"attempts": 1, "raw_bytes": 50}]}), encoding="utf-8"
        )
        return {
            "status": "available",
            "classification": "CURRENT_OBSERVED_OFFICIAL_PUBLICATIONS_NOT_COMPLETE_MACRO_FEED",
            "available_sources": ["source-a"],
            "source_statuses": [{"source_name": "source-a", "status": 200}],
        }

    monkeypatch.setattr(current_macro, "capture_current_macro", fake_macro)
    fixed_now_ms = 1_800_000_000_123
    monkeypatch.setattr(probe.time, "time_ns", lambda: fixed_now_ms * 1_000_000)
    result = await probe._capture_probe(output)

    assert result["state"] == "CAPTURED_SOURCE_AVAILABILITY_ONLY"
    assert len(result["news"]) == 2
    assert all(row["native_text_eligibility"]["selected_item_count"] == 0 for row in result["news"])
    assert result["market"]["live_market_authorization_limit_ms"] == 2_000
    assert result["aggregate_limits"]["paid_calls"] == 0
    assert result["aggregate_limits"]["sim_resources"] is False
    expected_cut = (fixed_now_ms // probe.BAR_MS) * probe.BAR_MS
    assert cut_values == [expected_cut]
    assert cut_values[0] <= fixed_now_ms
    assert cut_values[0] - 1 <= fixed_now_ms
    assert "authenticated LiveInputsSourceVerifier receipt" in result["unestablished_stages"]
    assert (output / "source-qualification.json").is_file()
    with pytest.raises(probe.CreateOnlyPublicationError):
        probe._write_create_only(output / "source-qualification.json", result)


@pytest.mark.asyncio
async def test_run_probe_refuses_existing_directory_without_touching_it(tmp_path: Path):
    output = tmp_path / "already-exists"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("untouched", encoding="utf-8")

    with pytest.raises(FileExistsError, match="SOURCE_PROBE_OUTPUT_MUST_BE_NEW"):
        await probe.run_probe(output)

    assert marker.read_text(encoding="utf-8") == "untouched"


@pytest.mark.asyncio
async def test_run_probe_records_failure_and_does_not_retry(tmp_path: Path, monkeypatch):
    output = tmp_path / "failed-first"
    calls = 0

    async def fail_once(_output):
        nonlocal calls
        calls += 1
        raise RuntimeError("source refused")

    monkeypatch.setattr(probe, "_capture_probe", fail_once)
    with pytest.raises(RuntimeError, match="source refused"):
        await probe.run_probe(output)

    assert calls == 1
    failure = json.loads((output / "source-probe-failure.json").read_text(encoding="utf-8"))
    assert failure["state"] == "FAILED_CLOSED"
    with pytest.raises(FileExistsError):
        await probe.run_probe(output)


def test_create_only_write_failure_keeps_partial_and_never_publishes_final(tmp_path: Path, monkeypatch):
    final = tmp_path / "receipt.json"

    def fail_fsync(_fd):
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(probe.os, "fsync", fail_fsync)
    with pytest.raises(probe.CreateOnlyPublicationError) as caught:
        probe._write_create_only(final, {"state": "PASS"})

    assert not final.exists()
    assert caught.value.partial_path.is_file()
    assert "partial" in caught.value.partial_path.name
    assert caught.value.partial_path.stat().st_size > 0


@pytest.mark.asyncio
async def test_failure_receipt_error_does_not_mask_original_error(tmp_path: Path, monkeypatch):
    output = tmp_path / "failed-receipt"
    original_writer = probe._write_create_only
    original = RuntimeError("original source failure")

    async def fail_source(_output):
        raise original

    def fail_failure_receipt(path, payload):
        if path.name == "source-probe-failure.json":
            raise OSError("failure receipt fsync failure")
        return original_writer(path, payload)

    monkeypatch.setattr(probe, "_capture_probe", fail_source)
    monkeypatch.setattr(probe, "_write_create_only", fail_failure_receipt)

    with pytest.raises(RuntimeError, match="original source failure") as caught:
        await probe.run_probe(output)

    assert caught.value is original
    assert any("Failure receipt could not be published" in note for note in caught.value.__notes__)


@pytest.mark.asyncio
async def test_run_probe_rejects_linked_ancestor_before_creating_output(tmp_path: Path):
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink unavailable: {type(exc).__name__}")
    output = linked_parent / "new-source-run"

    with pytest.raises(ValueError, match="SOURCE_PROBE_CANNOT_TRAVERSE_LINKS"):
        await probe.run_probe(output)

    assert not (real_parent / "new-source-run").exists()


@pytest.mark.asyncio
async def test_rss_refusal_does_not_suppress_other_planned_checks(tmp_path: Path, monkeypatch):
    output = tmp_path / "independent-checks"
    output.mkdir()
    macro_calls: list[Path] = []
    other_feed_completed: list[str] = []
    quote_attempts: list[str] = []

    class OneFeedRefuses:
        broken_quote = False

        def __init__(self, root, *, text_feed, byte_limit, deadline_seconds):
            self.root = root
            self.text_feed = text_feed
            self.byte_limit = byte_limit
            self.bytes_used = 0
            self.requests = 0

        async def capture_text(self):
            self.requests = 1
            if self.text_feed == probe._feed_roster()[0]:
                raise ValueError("configured feed refused")
            other_feed_completed.append(self.text_feed)
            receipt = self.root / "other-feed.receipt.json"
            receipt.write_text(json.dumps({"raw_item_count": 1, "fresh_item_count": 0}), encoding="utf-8")
            now = 1_800_000_000_000
            return SimpleNamespace(
                source_name=probe.TEXT_FEEDS[self.text_feed][0],
                receipt_path=receipt,
                raw_sha256="c" * 64,
                requested_ms=now - 100,
                received_ms=now,
                persisted_ms=now + 1,
            )

        async def fresh_quote(self, symbol):
            self.requests = 1
            quote_attempts.append(symbol)
            if self.broken_quote:
                return SimpleNamespace(
                    raw_sha256="d" * 64,
                    requested_ms=1_800_000_000_000,
                    received_ms=1_800_000_000_000,
                    captured_ms=1_800_000_000_001,
                    entry_quote=SimpleNamespace(),
                    receipt_path=self.root / f"{symbol}.receipt.json",
                )
            now = 1_800_000_000_000
            receipt = self.root / f"{symbol}.receipt.json"
            receipt.write_text("{}", encoding="utf-8")
            return SimpleNamespace(
                raw_sha256="d" * 64,
                requested_ms=now,
                received_ms=now,
                captured_ms=now,
                entry_quote=_native_bbo_quote(symbol, now, now, now),
                receipt_path=receipt,
            )

        async def fetch_history(self, cut_ms):
            self.requests = 15
            receipt = self.root / "bars.receipt.json"
            receipt.write_text("{}", encoding="utf-8")
            return SimpleNamespace(
                coverage_scope="FIVE_SYMBOLS_EXACT_54H_CLOSED_1M_BARS_AT_CAPTURE_ONLY",
                bars_by_symbol={symbol: tuple(range(probe.BAR_COUNT)) for symbol in probe.UNIVERSE},
                page_receipts=(SimpleNamespace(receipt_path=receipt),),
            )

    monkeypatch.setattr(probe, "CurrentPublicCapture", OneFeedRefuses)
    monkeypatch.setattr(probe, "_eligibility", lambda _snapshot: {"selected_item_count": 0})

    async def macro_partial(directory):
        macro_calls.append(directory)
        directory.mkdir()
        (directory / "receipt.json").write_text(
            json.dumps({"source_results": [{"attempts": 1, "raw_bytes": 10}]}), encoding="utf-8"
        )
        return {
            "status": "partial",
            "classification": "CURRENT_OBSERVED_OFFICIAL_PUBLICATIONS_NOT_COMPLETE_MACRO_FEED",
            "available_sources": ["one"],
            "source_statuses": [{"source_name": "one", "status": 200}],
        }

    monkeypatch.setattr(current_macro, "capture_current_macro", macro_partial)
    result = await probe._capture_probe(output)

    assert result["state"] == "PARTIAL_SOURCE_AVAILABILITY"
    assert result["news"][0]["state"] == "REFUSED"
    assert len(other_feed_completed) == 1
    assert len(macro_calls) == 1
    assert all(row["state"] == "CAPTURED" for row in result["market"]["depth_snapshots"])
    assert result["market"]["closed_history"]["state"] == "CAPTURED"

    broken_output = tmp_path / "broken-interface"
    broken_output.mkdir()
    quote_attempts.clear()
    OneFeedRefuses.broken_quote = True
    with pytest.raises(AttributeError):
        await probe._capture_probe(broken_output)
    assert quote_attempts == [probe.UNIVERSE[0]]
