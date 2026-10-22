"""CLI/factual capture-envelope tests; no provider, socket or database."""

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
