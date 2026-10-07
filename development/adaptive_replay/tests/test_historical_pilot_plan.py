"""Source/configuration guards for the bounded historical pilot draft.

These checks do not admit historical sources, verify the live budget ledger,
or authorize provider dispatch.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

PLAN_PATH = Path(__file__).parents[1] / "historical-episodes-draft.json"
EXPECTED_CUTS = {
    "episode_a": ("2021-05-19T00:00:00Z", "2021-05-19T08:00:00Z"),
    "episode_d": ("2024-01-09T21:15:00Z", "2024-01-09T21:30:00Z"),
}


def load_plan() -> dict:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def as_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def test_historical_pilot_uses_only_fixed_in_window_native_cadence_cuts() -> None:
    plan = load_plan()
    pilot = plan["low_cost_pilot"]
    episodes = {episode["id"]: episode for episode in plan["episodes"]}

    assert pilot["selected_episode_ids"] == ["episode_a", "episode_d"]
    assert pilot["decision_cuts_per_episode"] == 2
    assert pilot["utc_decision_cuts"] == {episode: list(cuts) for episode, cuts in EXPECTED_CUTS.items()}

    for episode_id, cuts in EXPECTED_CUTS.items():
        episode = episodes[episode_id]
        start = as_utc(episode["candidate_start_utc"])
        end = as_utc(episode["candidate_end_exclusive_utc"])
        parsed_cuts = tuple(as_utc(cut) for cut in cuts)
        assert all(start <= cut < end for cut in parsed_cuts)
        assert all(cut.minute % 5 == 0 and cut.second == 0 for cut in parsed_cuts)


def test_historical_pilot_limits_do_not_make_the_plan_executable() -> None:
    plan = load_plan()
    pilot = plan["low_cost_pilot"]

    assert pilot["maximum_paid_requests_total"] <= 20
    assert pilot["automatic_retries"] == 0
    assert pilot["additional_model_or_effort_comparisons"] is False
    assert pilot["approved_cumulative_pilot_ceiling_usd"] == 1.0
    assert pilot["approved_cumulative_pilot_ceiling_usd"] <= 12.0
    assert "existing OpenAI 12 USD limit" in pilot["budget_rule"]
    assert "No budget is adopted or reset" in pilot["budget_rule"]

    assert pilot["paid_dispatch_ready"] is False
    assert pilot["admitted_strategy_identity"] is None
    assert pilot["admitted_model_route"] is None
    assert pilot["required_context_source_roster"] is None
    assert pilot["strategy_generation_executed"] is False
    assert pilot["economics_executed"] is False
    assert pilot["paid_requests_executed"] == 0
    assert plan["LIVE_READY"] is False
    assert plan["STRATEGY_POLICY"] == "REJECT_ALL"
