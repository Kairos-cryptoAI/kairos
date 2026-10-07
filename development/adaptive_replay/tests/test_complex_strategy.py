from dataclasses import replace

import pytest
from kairos_core.contracts.regime_capability import CapabilityRegime
from kairos_core.enums import Side
from kairos_strategy.adaptive.logic import AdaptiveDecision
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent

from adaptive_replay import complex_strategy as cs

CUT = 5 * 86_400_000
ORIGIN = CUT - cs.HISTORY_BARS * cs.MINUTE


def bars(count=cs.HISTORY_BARS, width=0.7):
    return tuple(
        Candle("BTCUSDT", "1m", t, t + 59_999, 100, 100 + width, 100 - width, 100, 10)
        for t in range(CUT - count * cs.MINUTE, CUT, cs.MINUTE)
    )


def intent(family=cs.BREAKOUT_ID, side=Side.LONG):
    return SleeveIntent(
        family,
        "BTCUSDT",
        side,
        CUT - 1,
        CUT,
        CUT + 59_999,
        100,
        1,
        200,
        ExitPlan(99 if side is Side.LONG else 101, 102 if side is Side.LONG else 98, 120_000),
    )


def adaptive(regime=CapabilityRegime.BULL, candidate=None, shock="NONE", status="NO_INTENT"):
    return AdaptiveDecision(
        status, "fixture", regime, CUT - 1, "a" * 64, (("last_shock_ms", shock),), candidate
    )


def test_compact_defaults_do_not_reconfigure_native_sleeves_or_introduce_quota():
    policy = cs.fixed_complex_policy()
    assert policy["families"] == ["trend_breakout_v1", "adaptive_pullback_range_v1"]
    assert policy["daily_trade_quota"] is None
    assert not policy["production_registration"]
    assert policy["adaptive_config"]["entry_lifetime_ms"] == 60_000
    assert policy["proposal_mapper"]["entry_lifetime_ms"] == 300_000


def test_same_side_priority_opposition_and_no_duplicate_resurrection():
    a, b = intent(cs.STRATEGY_ID), intent()
    selected, _, dropped = cs.select_technical((b, a))
    assert selected is a and dropped == (b.intent_id,)
    assert cs.select_technical((b, intent(cs.STRATEGY_ID, Side.SHORT)))[0] is None
    with pytest.raises(ValueError, match="duplicate"):
        cs.select_technical((b, b))
    with pytest.raises(ValueError, match="one original"):
        cs.select_technical((a, replace(b, symbol="ETHUSDT")))


def test_native_generator_receives_expanding_not_rolling_history(monkeypatch):
    prefix = bars(cs.HISTORY_BARS + 60)
    original = intent()
    seen = []

    def generate(family, rows, config):
        seen.append((rows[0].open_time_ms, len(rows)))
        assert family == cs.BREAKOUT_ID
        return (original,)

    monkeypatch.setattr(cs, "generate_sleeve_intents", generate)
    monkeypatch.setattr(cs, "evaluate_adaptive", lambda rows: adaptive())
    result = cs.evaluate_complex(prefix, prefix_start_ms=prefix[0].open_time_ms, cut_ms=CUT)
    assert result.candidate is original
    assert seen == [(prefix[0].open_time_ms, len(prefix))]
    assert result.expanding_prefix_sha256 != result.rolling_history_sha256


@pytest.mark.parametrize(
    "regime,shock", [(CapabilityRegime.CRASH, "NONE"), (CapabilityRegime.UNCERTAIN, str(CUT - 3_600_000))]
)
def test_breakout_cannot_bypass_crash_and_exact_postshock_cooldown(monkeypatch, regime, shock):
    b = intent()
    monkeypatch.setattr(cs, "generate_sleeve_intents", lambda *args: (b,))
    monkeypatch.setattr(cs, "evaluate_adaptive", lambda rows: adaptive(regime, shock=shock))
    result = cs.evaluate_complex(bars(), prefix_start_ms=ORIGIN, cut_ms=CUT)
    assert result.candidate is None and result.state == "QUIET"
    assert result.dropped_ids == (b.intent_id,)
    assert result.defense in {"CRASH", "POST_SHOCK_COOLDOWN"}


def test_invalid_source_never_becomes_quiet_or_valid_baseline(monkeypatch):
    monkeypatch.setattr(cs, "generate_sleeve_intents", lambda *args: (intent(),))
    monkeypatch.setattr(cs, "evaluate_adaptive", lambda rows: adaptive(status="UNAVAILABLE"))
    result = cs.evaluate_complex(bars(), prefix_start_ms=ORIGIN, cut_ms=CUT)
    assert result.state == "UNAVAILABLE" and result.candidate is None
    with pytest.raises(ValueError, match="discontinuous"):
        bad = list(bars())
        bad[30] = bad[29]
        cs.evaluate_complex(tuple(bad), prefix_start_ms=ORIGIN, cut_ms=CUT)
    with pytest.raises(ValueError, match="closed cut"):
        cs.evaluate_complex(bars(), prefix_start_ms=ORIGIN, cut_ms=CUT + 300_000)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_quiet_model_direction_has_real_deterministic_geometry_not_model_sizing(side):
    mapped = cs.map_context_proposal(side, bars(), cut_ms=CUT, assessment_sha256="a" * 64)
    assert mapped.state == "MAPPED"
    c = mapped.candidate
    assert c.sleeve_id == cs.MAPPER_ID
    assert c.decision_ts_ms == CUT - 1 and c.entry_expires_ts_ms == CUT + 299_999
    assert abs(c.exit_plan.stop_price - c.reference_price) == pytest.approx(1.75)
    assert abs(c.exit_plan.target_price - c.reference_price) == pytest.approx(3.5)
    assert "confidence" not in dict(c.metadata)
    assert cs.map_context_proposal(side, bars(), cut_ms=CUT, assessment_sha256="a" * 64) == mapped
    changed = cs.map_context_proposal(side, bars(), cut_ms=CUT, assessment_sha256="b" * 64)
    assert changed.mapping_id != mapped.mapping_id
    assert changed.candidate.intent_id != c.intent_id


@pytest.mark.parametrize(
    "width,reason", [(0.01, "INSUFFICIENT_COST_HEADROOM"), (2.0, "STOP_DISTANCE_TOO_WIDE")]
)
def test_mapper_denies_cost_or_wide_stop_no_force_trade(width, reason):
    mapped = cs.map_context_proposal("LONG", bars(width=width), cut_ms=CUT, assessment_sha256="a" * 64)
    assert mapped.candidate is None and mapped.reason == reason


def test_mapper_crash_reuses_only_original_controlled_short_and_lifetime(monkeypatch):
    original = intent(cs.STRATEGY_ID, Side.SHORT)
    monkeypatch.setattr(
        cs, "evaluate_adaptive", lambda rows: adaptive(CapabilityRegime.CRASH, original, status="INTENT")
    )
    mapped = cs.map_context_proposal("SHORT", bars(), cut_ms=CUT, assessment_sha256="a" * 64)
    assert mapped.candidate is original and mapped.candidate.entry_expires_ts_ms == CUT + 59_999
    assert cs.map_context_proposal("LONG", bars(), cut_ms=CUT, assessment_sha256="a" * 64).candidate is None


def test_none_unknown_price_direction_and_future_bars():
    assert cs.map_context_proposal("NONE", bars(), cut_ms=CUT, assessment_sha256="a" * 64).candidate is None
    with pytest.raises(ValueError, match="strict model direction"):
        cs.map_context_proposal("100x", bars(), cut_ms=CUT, assessment_sha256="a" * 64)
    with pytest.raises(ValueError, match="closed cut"):
        cs.map_context_proposal("LONG", bars(), cut_ms=CUT - 300_000, assessment_sha256="a" * 64)
