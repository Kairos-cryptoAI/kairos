"""Predeclared compact-complex diagnostic, separate from every frozen campaign."""

from __future__ import annotations

from datetime import UTC, datetime

from .complex_assessment import DirectionalAssessment
from .complex_strategy import fixed_complex_policy
from .historical_context import SourceRequirement, digest
from .inputs import UNIVERSE

SCHEMA = "kairos.development.compact-context-diagnostic.v1"
EPISODES = (
    ("episode_a", "2021-05-17", "2021-05-22", ("2021-05-19T00:00:00Z", "2021-05-19T08:00:00Z"), "may"),
    ("episode_d", "2024-01-08", "2024-01-13", ("2024-01-09T21:15:00Z", "2024-01-09T21:30:00Z"), "jan_2024"),
)
READINESS = {
    "TECHNICAL_PAPER_READY": False,
    "PAPER_QUALIFIED": False,
    "ALPHA_READY": False,
    "LIVE_READY": False,
    "STRATEGY_POLICY": "REJECT_ALL",
}
MODEL_ROUTE = {
    "provider": "OPENAI",
    "model": "gpt-6-luna",
    "reasoning_effort": "medium",
    "max_output_tokens": 2_048,
    "max_retries": 0,
    "workload": "AGGREGATOR_NORMAL",
}


def model_config_sha256() -> str:
    return digest(
        {
            "provider": MODEL_ROUTE["provider"],
            "model": MODEL_ROUTE["model"],
            "effort": MODEL_ROUTE["reasoning_effort"],
            "workload": MODEL_ROUTE["workload"],
            "max_output_tokens": MODEL_ROUTE["max_output_tokens"],
            "max_retries": MODEL_ROUTE["max_retries"],
            "schema": DirectionalAssessment.model_json_schema(),
        }
    )


def utc_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=UTC).timestamp() * 1_000)


def requirements() -> tuple[SourceRequirement, ...]:
    return (
        SourceRequirement("official_market_news", "NEWS", True, 86_400_000, 86_400_000),
        SourceRequirement("official_macro", "MACRO", True, 31 * 86_400_000, 31 * 86_400_000),
    )


def fixed_protocol() -> dict:
    return {
        "schema": SCHEMA,
        "complex": fixed_complex_policy(),
        "universe": list(UNIVERSE),
        "episodes": [
            {"id": eid, "start": start, "end_exclusive": end, "assessment_cuts": list(cuts)}
            for eid, start, end, cuts, _ in EPISODES
        ],
        "scope": "SPARSE_FIXED_CUT_RETROSPECTIVE_DIAGNOSTIC_NOT_FULL_TRADING_CAMPAIGN",
        "arms": [
            "strategy_only",
            "context_review",
            "independent_proposals",
            "combined",
            "review_timing_control",
        ],
        "model_assessment": "ONE_STRATEGY_BLIND_JOINT_DIRECTIONAL_RESPONSE_PER_CELL",
        "model_roles_statistically_independent": False,
        "model_route": dict(MODEL_ROUTE),
        "model_config_sha256": model_config_sha256(),
        "budget": {
            "group": "EXISTING_HISTORICAL_SMALL_PILOT_CUMULATIVE_CAP",
            "maximum_total_attempts": 20,
            "maximum_total_usd": 1.0,
            "additional_budget_granted": False,
            "reset_or_new_cap_allowed": False,
            "openai_shared_ceiling_usd": 12.0,
            "reserve_existing_and_prior_usage": True,
        },
        "execution": {
            "baseline_delay_ms": 100,
            "model_delay": "ACTUAL_MODERN_ELAPSED_PROJECTED_AFTER_BASELINE_DELAY",
            "cost_clock": "ACTUAL_MODERN_COST_ELAPSED_PROJECTED_BEFORE_SIZING",
            "mapping_delay": "MEASURED_LOCAL_ELAPSED_ADDED_TO_ASSESSMENT_READY",
            "modes": ["STRICT_MINUTE_OPEN", "INTRABAR_OPEN_PROXY"],
            "initial_equity_usd_each_episode": 10_000,
            "exit_tail_hours": 3,
            "cost_risk_policy": "COMMON_COST_RISK_V1",
            "risk": {
                "per_trade": 0.0025,
                "aggregate_open": 0.01,
                "per_symbol_notional": 0.25,
                "gross_leverage": 1,
            },
        },
        "cost_scenarios": [
            {
                "id": "base",
                "fee_bps_per_side": 4.5,
                "spread_bps": 2,
                "slippage_bps_per_side": 1,
                "latency_bps_round_trip": 2,
                "uncertainty_bps": 2,
                "admission_adverse_carry_bps": 3,
            },
            {
                "id": "stress",
                "fee_bps_per_side": 9,
                "spread_bps": 4,
                "slippage_bps_per_side": 2,
                "latency_bps_round_trip": 2,
                "uncertainty_bps": 2,
                "admission_adverse_carry_bps": 3,
            },
        ],
        "source_requirements": [
            {
                "source_name": r.source_name,
                "kind": r.kind,
                "required": r.required,
                "lookback_ms": r.lookback_ms,
                "maximum_age_ms": r.maximum_age_ms,
            }
            for r in requirements()
        ],
        "source_admission": "EXPLICIT_AUTHENTICITY_AND_ARCHIVE_VERSION_COVERAGE_REVIEW_REQUIRED",
        "prompt_policy": "CAUSAL_PRICES_NEWS_MACRO_NO_STRATEGY_CANDIDATE_OR_OUTCOME",
        "combined": "STRATEGY_FIRST_NO_VETO_BYPASS_OPPOSITE_ABSTAIN_FAILED_MAPPING_ABSTAIN",
        "account_costs": "ONE_CHARGE_PER_ATTEMPT_PER_MODEL_COUNTERFACTUAL_NEVER_SUM_AS_PHYSICAL_SPEND",
        "max_wall_seconds": 300,
        "workers": 1,
        "owner_confirmation_required_before_models": True,
        "no_parameter_search": True,
        "no_blind_campaign_credit": True,
        "training_contamination_excluded": False,
        "readiness": dict(READINESS),
    }


def protocol_sha256() -> str:
    return digest(fixed_protocol())
