from types import SimpleNamespace

import pytest

from adaptive_replay.candidate_audit import build_candidate_audit


def _slot(state, name, ts=1000, source_avail="AVAILABLE", stale=False):
    candidate = SimpleNamespace(intent_id=f"intent-{name}") if state == "CANDIDATE" else None
    sources = tuple(
        SimpleNamespace(
            kind=kind,
            availability=source_avail if kind == "text" else "AVAILABLE",
            reason="fixture_gap" if kind == "text" and source_avail == "UNAVAILABLE" else None,
            ready_at=lambda clock, avail=(source_avail if kind == "text" else "AVAILABLE"), stale=stale: (
                avail == "AVAILABLE" and not stale
            ),
        )
        for kind in ("market", "closed_bars", "text", "macro")
    )
    return SimpleNamespace(
        state=state,
        symbol="BTCUSDT",
        candidate=candidate,
        sources=sources,
        matched=SimpleNamespace(slot_id=f"slot-{name}", decision_ms=ts),
    )


def _arm(events=(), trades=(), unresolved=(), complete=True):
    return {
        "events": list(events),
        "trades": list(trades),
        "economic_results": {"terminal_unresolved_positions": list(unresolved)} if complete else None,
    }


def _decision(disposition, retained, observed=1010, cost=0.2):
    return {
        "disposition": disposition,
        "retained_for_replay": retained,
        "observed_ms": observed,
        "cost_usd": cost,
        "no_call_reason": None,
    }


def test_full_roster_and_source_availability_keep_candidate_denominator():
    slots = (
        _slot("CANDIDATE", "a"),
        _slot("QUIET", "b"),
        _slot("UNAVAILABLE", "c", source_avail="UNAVAILABLE"),
    )
    arms = {"strategy_only": _arm()}
    result = build_candidate_audit(slots, arms, {})
    assert result["schedule_denominator"] == 3
    assert result["slot_states"] == {"CANDIDATE": 1, "QUIET": 1, "UNAVAILABLE": 1}
    assert result["baseline_candidate_denominator"] == 1
    assert result["source_coverage"]["text"] == {
        "AVAILABLE": 2,
        "UNAVAILABLE": 1,
        "STALE_AT_DECISION": 0,
        "unavailable_reasons": {"fixture_gap": 1},
    }


def test_filter_audit_separates_missed_winner_and_avoided_loss_with_cost_delay():
    slots = (_slot("CANDIDATE", "win"), _slot("CANDIDATE", "loss"))
    baseline = _arm(
        events=[
            {"kind": "ENTRY", "intent_id": "intent-win"},
            {"kind": "ENTRY", "intent_id": "intent-loss"},
        ],
        trades=[
            {"intent_id": "intent-win", "net_pnl_usd": 12.0},
            {"intent_id": "intent-loss", "net_pnl_usd": -7.0},
        ],
    )
    arms = {"strategy_only": baseline, "context_review": _arm()}
    decisions = {
        "context_review": {
            "slot-win": _decision("VETO", False),
            "slot-loss": _decision("VETO", False, observed=1020, cost=None),
        }
    }
    result = build_candidate_audit(slots, arms, decisions)
    assert result["classification_counts"]["context_review"] == {
        "MISSED_BASELINE_WINNER": 1,
        "AVOIDED_BASELINE_LOSS": 1,
    }
    winner = result["candidates"][0]["paths"]["context_review"]
    assert winner["execution_status"] == "NOT_SELECTED"
    assert winner["delay_ms"] == 10
    assert winner["cost_usd"] == pytest.approx(0.2)
    assert result["candidates"][1]["paths"]["context_review"]["cost_usd"] is None
    assert result["scope"] == "DIAGNOSTIC_ONLY_NOT_SELECTOR"


def test_incomplete_arm_is_unknown_even_for_unselected_candidate():
    slot = _slot("CANDIDATE", "unknown")
    result = build_candidate_audit(
        (slot,),
        {"strategy_only": _arm(complete=False), "deterministic_filter": _arm(complete=False)},
        {"deterministic_filter": {"slot-unknown": _decision("REJECT", False)}},
    )
    row = result["candidates"][0]
    assert row["baseline_execution_status"] == "UNKNOWN"
    assert row["paths"]["deterministic_filter"]["execution_status"] == "UNKNOWN"
    assert row["paths"]["deterministic_filter"]["classification"] == "UNKNOWN"


def test_conflicting_replay_identities_are_rejected():
    slot = _slot("CANDIDATE", "duplicate")
    bad = _arm(
        events=[
            {"kind": "ENTRY", "intent_id": "intent-duplicate"},
            {"kind": "REJECT", "intent_id": "intent-duplicate"},
        ]
    )
    with pytest.raises(ValueError, match="both entered and rejected"):
        build_candidate_audit((slot,), {"strategy_only": bad}, {})


def test_retained_but_engine_rejected_is_not_a_filter_veto():
    slot = _slot("CANDIDATE", "rejected")
    arms = {
        "strategy_only": _arm(
            events=[{"kind": "ENTRY", "intent_id": "intent-rejected"}],
            trades=[{"intent_id": "intent-rejected", "net_pnl_usd": 5.0}],
        ),
        "context_review": _arm(
            events=[{"kind": "REJECT", "intent_id": "intent-rejected", "reason": "FILL_CAP"}]
        ),
    }
    result = build_candidate_audit(
        (slot,), arms, {"context_review": {"slot-rejected": _decision("ALLOW", True)}}
    )
    path = result["candidates"][0]["paths"]["context_review"]
    assert path["execution_status"] == "REJECTED"
    assert path["classification"] == "NOT_FILLED_BASELINE_WINNER"


def test_open_and_flat_baseline_have_nullable_closed_result():
    open_slot, flat_slot = _slot("CANDIDATE", "open"), _slot("CANDIDATE", "flat")
    baseline = _arm(
        events=[
            {"kind": "ENTRY", "intent_id": "intent-open"},
            {"kind": "ENTRY", "intent_id": "intent-flat"},
        ],
        trades=[{"intent_id": "intent-flat", "net_pnl_usd": 0.0}],
        unresolved=[{"intent_id": "intent-open", "unrealized_usd": 2.0}],
    )
    result = build_candidate_audit(
        (open_slot, flat_slot),
        {"strategy_only": baseline, "context_review": _arm()},
        {
            "context_review": {
                "slot-open": _decision("VETO", False),
                "slot-flat": _decision("VETO", False),
            }
        },
    )
    assert result["candidates"][0]["baseline_execution_status"] == "OPEN"
    assert result["candidates"][0]["baseline_closed_net_usd"] is None
    assert result["candidates"][1]["paths"]["context_review"]["classification"] == "OMITTED_BASELINE_FLAT"


def test_incomplete_path_is_unknown_even_when_baseline_trade_is_known():
    slot = _slot("CANDIDATE", "known")
    baseline = _arm(
        events=[{"kind": "ENTRY", "intent_id": "intent-known"}],
        trades=[{"intent_id": "intent-known", "net_pnl_usd": -3.0}],
    )
    result = build_candidate_audit(
        (slot,),
        {"strategy_only": baseline, "context_review": _arm(complete=False)},
        {"context_review": {"slot-known": _decision("VETO", False)}},
    )
    path = result["candidates"][0]["paths"]["context_review"]
    assert path["execution_status"] == "UNKNOWN"
    assert path["baseline_closed_net_usd"] == -3.0
    assert path["classification"] == "UNKNOWN"


def test_stale_source_and_duplicate_trade_are_audited_or_rejected():
    stale = _slot("CANDIDATE", "stale", stale=True)
    result = build_candidate_audit((stale,), {"strategy_only": _arm()}, {})
    assert result["source_coverage"]["text"]["STALE_AT_DECISION"] == 1
    duplicate = _arm(
        events=[{"kind": "ENTRY", "intent_id": "intent-stale"}],
        trades=[
            {"intent_id": "intent-stale", "net_pnl_usd": 1.0},
            {"intent_id": "intent-stale", "net_pnl_usd": 1.0},
        ],
    )
    with pytest.raises(ValueError, match="duplicate closed trade"):
        build_candidate_audit((stale,), {"strategy_only": duplicate}, {})
