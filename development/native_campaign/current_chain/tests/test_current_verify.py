"""CLI/factual capture-envelope tests; no provider, socket or database."""

from types import SimpleNamespace

import pytest

from kairos_native_campaign import current_verify as cv


@pytest.mark.asyncio
async def test_phase_wait_does_not_reset_an_old_capture(tmp_path, monkeypatch):
    phases = []

    class Phase:
        def __init__(self, output, **kw):
            self.requests = self.bytes_used = 0
            self.capture_id = str(len(phases))
            self.limit = kw["byte_limit"]
            phases.append(self)

        async def capture_text(self):
            self.requests, self.bytes_used = 1, 100
            return object()

        async def fetch_history(self, cut):
            self.requests, self.bytes_used = 15, 1000
            return type("History", (), {"cut_ms": cut})()

        async def fresh_quote(self, symbol):
            self.requests, self.bytes_used = 1, 50
            return symbol

    monkeypatch.setattr(cv, "CurrentPublicCapture", Phase)
    capture = cv.PhaseBoundedCapture(tmp_path)
    text = await capture.capture_text()
    assert await capture.capture_text() is text
    await capture.fetch_history(300_000)
    assert await capture.fresh_quote("BTCUSDT") == "BTCUSDT"
    assert len(phases) == 3
    assert capture.requests == 17 and capture.bytes_used == 1150
    assert phases[0].requests == 1  # Not reset or repurposed to renew old clocks.
    assert phases[1].limit == 32 * 1024 * 1024 - 100


def test_phase_cap_is_pre_request_and_plan_does_not_arm(tmp_path):
    capture = cv.PhaseBoundedCapture(tmp_path)
    capture.requests = 40
    with pytest.raises(ValueError, match="ENVELOPE"):
        capture._phase(1)
    plan = cv.scope()
    assert plan["real_venue_orders"] is False
    assert plan["new_key_or_project"] is False
    assert plan["maximum_openai_calls"] == 24
    assert plan["local_cap_microusd"] == 1_000_000
    assert not list(tmp_path.iterdir())


def test_news_selection_is_only_existing_configured_feed_not_implicit_fallback(tmp_path):
    chosen = "https://cointelegraph.com/rss"
    capture = cv.PhaseBoundedCapture(tmp_path, text_feed=chosen)
    assert cv.scope(text_feed=chosen)["text_feed"] == chosen
    phase = capture._phase(1)
    assert phase.text_feed == chosen
    with pytest.raises(ValueError, match="CONFIGURED_NEWS_FEED"):
        cv.scope(text_feed="https://unapproved.invalid/rss")


@pytest.mark.asyncio
async def test_full_verification_can_require_fresh_news_before_any_paid_stage(tmp_path, monkeypatch):
    class EmptyNews:
        requests = 1
        bytes_used = 100
        capture_id = "no-news"

        async def capture_text(self):
            return SimpleNamespace(news_items=())

    capture = cv.PhaseBoundedCapture(tmp_path, require_fresh_news=True)
    monkeypatch.setattr(capture, "_phase", lambda maximum_requests: EmptyNews())
    with pytest.raises(ValueError, match="FRESH_NEWS_BEFORE_PAID_CALLS"):
        await capture.capture_text()


def test_initial_sealed_book_and_short_provenance_refuse_before_paid_calls():
    now, cut = 1_800_000_070_000, 1_800_000_300_000
    frames = tuple(
        SimpleNamespace(
            symbol=symbol,
            tape_sequence=i,
            tape_id="original-native:0002",
            continuity="ADMITTED",
            frame_sha256="a" * 64,
            persisted_at_ms=now - 60_000,
            exchange_at_ms=now - 60_100,
        )
        for i, symbol in enumerate(cv.UNIVERSE, 1)
    )
    initial = SimpleNamespace(
        frames=frames,
        closed_bars=tuple((symbol, (object(), object())) for symbol in cv.UNIVERSE),
        tape_id="original-native:0002",
    )
    result = cv.initial_execution_compatibility(initial, cut_ms=cut, observed_ms=now)
    assert result["state"] == "EXECUTION_INCOMPATIBLE"
    assert result["no_symbol_can_reach_native_sim_entry"]
    assert result["earliest_decision_ms"] == cut
    for row in result["symbols"]:
        assert row["age_at_earliest_decision_ms"] == 290_000
        assert row["minimum_missing_history_bar_count"] == 3_238
        assert "FROZEN_INITIAL_BOOK_ALREADY_STALE_AT_EARLIEST_DECISION" in row["reasons"]
    assert frames[0].persisted_at_ms == now - 60_000  # Not refreshed by the check.


def test_fresh_initial_book_and_full_counts_do_not_claim_actual_admission():
    now = 1_800_000_000_000
    initial = SimpleNamespace(
        tape_id="original-native:0001",
        frames=tuple(
            SimpleNamespace(
                symbol=symbol,
                tape_sequence=i,
                tape_id="original-native:0001",
                continuity="ADMITTED",
                frame_sha256="b" * 64,
                persisted_at_ms=now - 100,
                exchange_at_ms=now - 200,
            )
            for i, symbol in enumerate(cv.UNIVERSE, 1)
        ),
        closed_bars=tuple((symbol, (None,) * 3_240) for symbol in cv.UNIVERSE),
    )
    result = cv.initial_execution_compatibility(initial, cut_ms=now, observed_ms=now)
    assert result["state"] == "NECESSARY_CHECKS_ONLY_NOT_ADMISSION"
    assert not result["no_symbol_can_reach_native_sim_entry"]
    assert not result["bar_identity_and_future_observation_coverage_proven"]
    assert result["risk_authority"] == "NONE"
