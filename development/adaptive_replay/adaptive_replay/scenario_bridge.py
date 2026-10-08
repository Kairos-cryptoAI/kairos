"""Research-only bridge from actual native/LLM-direction mappers to scenarios.

No production registry change, no paid dispatch, no rewriting the old complex.
The caller supplies qualified causal receipts; this module checks consistency.
New closed-price confirmation is a hypothesis, not a proven improvement.
"""

from __future__ import annotations

from dataclasses import dataclass

from kairos_strategy.adaptive.logic import evaluate_adaptive
from kairos_strategy.candles import Candle

from .complex_strategy import ComplexDecision, evaluate_complex, map_context_proposal
from .historical_context import _sha, digest
from .scenarios import CAPABILITIES, ScenarioEvidence, ScenarioPlan


@dataclass(frozen=True)
class ScenarioPreparation:
    origin: str
    state: str
    reason: str
    plan: ScenarioPlan | None
    input_sha256: str


def technical_scenario(
    prefix: tuple[Candle, ...],
    *,
    prefix_start_ms: int,
    cut_ms: int,
    source_set_sha256: str,
    context_sha256: str,
    sources: tuple[ScenarioEvidence, ...],
    required_sources: tuple[tuple[str, str], ...],
) -> tuple[ComplexDecision, ScenarioPreparation]:
    """Reuse the original technical decision; never invent a plan in a quiet slot."""
    _sha(source_set_sha256)
    _sha(context_sha256)
    decision = evaluate_complex(prefix, prefix_start_ms=prefix_start_ms, cut_ms=cut_ms)
    if decision.candidate is None:
        return decision, ScenarioPreparation(
            "TECHNICAL", decision.state, decision.reason, None, decision.expanding_prefix_sha256
        )
    if decision.defense != "NORMAL" or decision.regime not in {"BULL", "BEAR", "RANGE"}:
        return decision, ScenarioPreparation(
            "TECHNICAL", "ABSTAIN", "SCENARIO_V1_UNSUPPORTED_REGIME", None, decision.expanding_prefix_sha256
        )
    if decision.candidate.side not in CAPABILITIES[decision.regime]:
        return decision, ScenarioPreparation(
            "TECHNICAL",
            "ABSTAIN",
            "TECHNICAL_DIRECTION_OUTSIDE_PRICE_CAPABILITY",
            None,
            decision.expanding_prefix_sha256,
        )
    plan = ScenarioPlan(
        decision.candidate,
        "TECHNICAL",
        decision.regime,
        cut_ms,
        source_set_sha256,
        context_sha256,
        sources,
        prefix[-1],
        required_sources,
    )
    return decision, ScenarioPreparation(
        "TECHNICAL",
        "WAITING_TRIGGER",
        "NATIVE_CANDIDATE_NOT_ENTRY_PERMISSION",
        plan,
        decision.expanding_prefix_sha256,
    )


def context_scenario(
    direction: str,
    rows: tuple[Candle, ...],
    *,
    cut_ms: int,
    assessment_sha256: str,
    source_set_sha256: str,
    sources: tuple[ScenarioEvidence, ...],
    required_sources: tuple[tuple[str, str], ...],
) -> ScenarioPreparation:
    """Model direction fixes neither prices nor size and never grants an entry.

    The unchanged old mapper supplies price geometry solely from closed history.
    The new scenario additionally requires subsequent closed-price confirmation,
    source-bound directional review and unchanged downstream Risk. CRASH and
    UNCERTAIN remain abstentions; no new crash/contrarian hypothesis is added.
    """
    _sha(source_set_sha256)
    _sha(assessment_sha256)
    mapped = map_context_proposal(direction, rows, cut_ms=cut_ms, assessment_sha256=assessment_sha256)
    if mapped.candidate is None:
        return ScenarioPreparation("CONTEXT_PROPOSAL", "ABSTAIN", mapped.reason, None, mapped.history_sha256)
    regime = evaluate_adaptive(rows).regime.value
    if regime not in {"BULL", "BEAR", "RANGE"}:
        return ScenarioPreparation(
            "CONTEXT_PROPOSAL", "ABSTAIN", "SCENARIO_V1_UNSUPPORTED_REGIME", None, mapped.history_sha256
        )
    if mapped.candidate.side not in CAPABILITIES[regime]:
        return ScenarioPreparation(
            "CONTEXT_PROPOSAL",
            "ABSTAIN",
            "MODEL_DIRECTION_OUTSIDE_PRICE_CAPABILITY",
            None,
            mapped.history_sha256,
        )
    plan = ScenarioPlan(
        mapped.candidate,
        "CONTEXT_PROPOSAL",
        regime,
        cut_ms,
        source_set_sha256,
        digest({"assessment": assessment_sha256, "history": mapped.history_sha256}),
        sources,
        rows[-1],
        required_sources,
    )
    return ScenarioPreparation(
        "CONTEXT_PROPOSAL",
        "WAITING_TRIGGER",
        "MODEL_IDEA_REQUIRES_LATER_MARKET_CONFIRMATION",
        plan,
        mapped.history_sha256,
    )
