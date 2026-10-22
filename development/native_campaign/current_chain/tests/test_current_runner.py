"""No-provider/no-database runner-boundary tests."""

from __future__ import annotations

import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from kairos_native_campaign.current_runner import (
    MAX_SCHEDULED_WAIT_MS,
    CurrentRunConfig,
    CurrentRunRefused,
    OpenRiskSnapshot,
    ProviderAttempt,
    UsageSnapshot,
    _arm_creation_status,
    _canonical_sha,
    _scheduled_wait_seconds,
    _shared_gate,
    _stage,
    _stop_risk_microusd,
    _usage_delta,
    write_create_only,
)

SHA = "a" * 64


def _config(path, **overrides):
    values = dict(
        output_path=path,
        capture_start_ms=1_800_000_000_000,
        capture_end_ms=1_800_000_300_000,
        cut_ms=1_800_000_300_000,
        source_set_sha256=SHA,
        model_config_sha256="b" * 64,
        strategy_ids=("current-chain-fixture",),
        run_id="fixture-run",
    )
    values.update(overrides)
    return CurrentRunConfig(**values)


def test_run_config_fixes_fifteen_minute_capture_and_wall_ceiling(tmp_path):
    path = tmp_path / "receipt.json"
    assert _config(path).max_wall_seconds == 1_800
    with pytest.raises(ValueError, match="fifteen|15 minutes"):
        _config(path, capture_end_ms=1_800_000_901_000)
    with pytest.raises(ValueError, match="1800"):
        _config(path, max_wall_seconds=1_801)


def test_scheduled_cut_wait_is_bounded_to_330_seconds_without_rewriting_cut():
    now_ms = 1_800_000_000_000
    cut_ms = now_ms + MAX_SCHEDULED_WAIT_MS
    assert _scheduled_wait_seconds(cut_ms, now_ms) == 330.0
    with pytest.raises(CurrentRunRefused, match="SCHEDULED_CUT_TOO_FAR_AHEAD"):
        _scheduled_wait_seconds(cut_ms + 1, now_ms)
    assert _scheduled_wait_seconds(cut_ms, cut_ms + 1) == 0.0
    assert cut_ms == now_ms + MAX_SCHEDULED_WAIT_MS


def test_create_only_receipt_never_overwrites_existing_evidence(tmp_path):
    path = tmp_path / "receipt.json"
    write_create_only(path, {"status": "first"})
    original = path.read_bytes()
    with pytest.raises(CurrentRunRefused, match="CREATE_ONLY"):
        write_create_only(path, {"status": "replacement"})
    assert path.read_bytes() == original
    assert json.loads(original) == {"status": "first"}


def test_provider_budget_snapshot_tracks_exact_new_reservations_only():
    before = UsageSnapshot(())
    after = UsageSnapshot(
        (
            ProviderAttempt("r1", "openai", "text", "gpt-6-luna", "COMMITTED", 400_000, 350_000),
            ProviderAttempt("r2", "openai", "macro", "gpt-6.1-sol", "RESERVED", 500_000, 0),
        )
    )
    assert _usage_delta(before, after)[:3] == (2, 900_000, 350_000)
    too_large = UsageSnapshot(
        (ProviderAttempt("r3", "openai", "review", "gpt-6-luna", "RESERVED", 1_000_001, 0),)
    )
    with pytest.raises(CurrentRunRefused, match="LOCAL_COST_CAP"):
        _usage_delta(before, too_large)


def test_none_context_proposal_is_retained_for_all_arms_without_fabricating_a_plan():
    outcome = {"TECHNICAL": "QUIET", "CONTEXT_PROPOSAL": "NONE"}
    assert _arm_creation_status(outcome, "strategy_only") == "NO_PLAN_ORIGIN_OUTCOME_RETAINED"
    assert _arm_creation_status(outcome, "context_review") == "NO_PLAN_ORIGIN_OUTCOME_RETAINED"
    assert _arm_creation_status(outcome, "independent_proposals") == "NO_PLAN_ORIGIN_OUTCOME_RETAINED"
    assert _arm_creation_status(outcome, "combined") == "NO_PLAN_ORIGIN_OUTCOME_RETAINED"


def test_unexercised_live_and_paper_are_not_claimed_as_completed_stages():
    from kairos_native_campaign.current_runner import ARM_IDS

    assert ARM_IDS == ("strategy_only", "context_review", "independent_proposals", "combined")
    # A traversal may complete with an explicit no-signal result; that never
    # implies that any arm, fill, PAPER path, or LIVE path was exercised.
    assert (
        _arm_creation_status({"TECHNICAL": "UNAVAILABLE", "CONTEXT_PROPOSAL": "NO_CALL"}, "combined")
        == "NO_PLAN_ORIGIN_OUTCOME_RETAINED"
    )


def test_open_risk_snapshot_requires_explicit_fresh_source_identity():
    snapshot = OpenRiskSnapshot(0, 1_800_000_000_000, "c" * 64)
    assert snapshot.amount_microusd == 0
    with pytest.raises(ValueError, match="open-risk snapshot"):
        OpenRiskSnapshot(0, 1_800_000_000_000, "not-a-hash")


def test_account_stop_risk_is_rounded_up_and_rejects_invalid_quantity():
    assert _stop_risk_microusd(0.0025, 100.0, 90.0) == 25_000
    assert _stop_risk_microusd(0.0000001, 100.0, 99.0) == 1
    with pytest.raises(CurrentRunRefused, match="RISK_INPUT_INVALID"):
        _stop_risk_microusd(0.0, 100.0, 90.0)


def test_defensive_macro_blocks_combined_but_not_matched_technical_baseline():
    allocation = SimpleNamespace(stable_reserve_pct=1.0, strategy_weights={})
    assert _shared_gate("combined", allocation, macro_fallback=False) == "BLOCKED"
    assert _shared_gate("strategy_only", allocation, macro_fallback=False) == "PASS"


@pytest.mark.asyncio
async def test_actual_catalyst_plan_fold_and_dataclass_receipts_not_v3_or_model_dump():
    from test_current_chain import prepared_plan

    from kairos_native_campaign import current_runner

    _chain, _prepared, _outcome, plan, _bars, preview = prepared_plan()
    result = current_runner.evaluate_hypothesis(plan, preview.observations)[-1]
    assert result.reason == "REVIEW_MISSING_DEFER" and result.state == "CONSUMED"
    # Native emitted raw candidates are dataclasses, never Pydantic objects.
    from adaptive_replay.catalyst_hypothesis_v1 import _entry

    raw, _ = _entry(plan, preview.observation)
    assert raw is not None and not hasattr(raw, "model_dump")
    assert _canonical_sha(raw) == _canonical_sha(asdict(raw))
    records = []

    async def operation():
        return raw

    async def usage():
        return UsageSnapshot(())

    assert await _stage("actual-current-candidate", operation, usage, UsageSnapshot(()), records) is raw
    assert records[0].status == "COMPLETED"
