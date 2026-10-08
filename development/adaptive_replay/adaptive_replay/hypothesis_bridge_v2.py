"""Research-only bridge from unchanged native decisions to sealed hypotheses.

The native candidate remains the original parent evidence.  A separate typed
v2 policy supplies the hypothesis validity and quote-evidence requirements;
this module does not fetch sources or alter any native strategy behavior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from kairos_strategy.adaptive.logic import evaluate_adaptive
from kairos_strategy.candles import Candle

from .complex_strategy import ComplexDecision, evaluate_complex, map_context_proposal
from .historical_context import _sha, digest
from .hypothesis_v2 import HypothesisPlan, HypothesisPolicy
from .scenarios import CAPABILITIES, ScenarioEvidence


@dataclass(frozen=True)
class HypothesisPreparation:
    origin: str
    state: str
    reason: str
    plan: HypothesisPlan | None
    input_sha256: str


def _policy(policy: HypothesisPolicy) -> None:
    if type(policy) is not HypothesisPolicy:
        raise ValueError("explicit typed hypothesis policy required")
    HypothesisPolicy(**asdict(policy))


def technical_hypothesis(
    prefix: tuple[Candle, ...],
    *,
    prefix_start_ms: int,
    cut_ms: int,
    source_set_sha256: str,
    context_sha256: str,
    sources: tuple[ScenarioEvidence, ...],
    required_sources: tuple[tuple[str, str], ...],
    policy: HypothesisPolicy,
) -> tuple[ComplexDecision, HypothesisPreparation]:
    """Wrap one unchanged technical decision; never synthesize a quiet slot."""
    _policy(policy)
    _sha(source_set_sha256)
    _sha(context_sha256)
    decision = evaluate_complex(prefix, prefix_start_ms=prefix_start_ms, cut_ms=cut_ms)
    if decision.candidate is None:
        return decision, HypothesisPreparation(
            "TECHNICAL", decision.state, decision.reason, None, decision.expanding_prefix_sha256
        )
    if decision.defense != "NORMAL" or decision.regime not in {"BULL", "BEAR", "RANGE"}:
        return decision, HypothesisPreparation(
            "TECHNICAL",
            "ABSTAIN",
            "HYPOTHESIS_V2_UNSUPPORTED_REGIME_OR_DEFENSE",
            None,
            decision.expanding_prefix_sha256,
        )
    if decision.candidate.side not in CAPABILITIES[decision.regime]:
        return decision, HypothesisPreparation(
            "TECHNICAL",
            "ABSTAIN",
            "TECHNICAL_DIRECTION_OUTSIDE_PRICE_CAPABILITY",
            None,
            decision.expanding_prefix_sha256,
        )
    plan = HypothesisPlan(
        decision.candidate,
        "TECHNICAL",
        decision.regime,
        cut_ms,
        source_set_sha256,
        context_sha256,
        sources,
        prefix[-1],
        required_sources,
        policy,
    )
    return decision, HypothesisPreparation(
        "TECHNICAL",
        "WAITING_TRIGGER",
        "NATIVE_PARENT_SEALED_AS_V2_HYPOTHESIS",
        plan,
        decision.expanding_prefix_sha256,
    )


def context_hypothesis(
    direction: str,
    rows: tuple[Candle, ...],
    *,
    cut_ms: int,
    assessment_sha256: str,
    source_set_sha256: str,
    sources: tuple[ScenarioEvidence, ...],
    required_sources: tuple[tuple[str, str], ...],
    policy: HypothesisPolicy,
) -> HypothesisPreparation:
    """Map direction through the unchanged mapper; prices remain history-owned."""
    _policy(policy)
    _sha(source_set_sha256)
    _sha(assessment_sha256)
    mapped = map_context_proposal(direction, rows, cut_ms=cut_ms, assessment_sha256=assessment_sha256)
    if mapped.candidate is None:
        return HypothesisPreparation(
            "CONTEXT_PROPOSAL", "ABSTAIN", mapped.reason, None, mapped.history_sha256
        )
    regime = evaluate_adaptive(rows).regime.value
    if regime not in {"BULL", "BEAR", "RANGE"}:
        return HypothesisPreparation(
            "CONTEXT_PROPOSAL",
            "ABSTAIN",
            "HYPOTHESIS_V2_UNSUPPORTED_REGIME",
            None,
            mapped.history_sha256,
        )
    if mapped.candidate.side not in CAPABILITIES[regime]:
        return HypothesisPreparation(
            "CONTEXT_PROPOSAL",
            "ABSTAIN",
            "MODEL_DIRECTION_OUTSIDE_PRICE_CAPABILITY",
            None,
            mapped.history_sha256,
        )
    plan = HypothesisPlan(
        mapped.candidate,
        "CONTEXT_PROPOSAL",
        regime,
        cut_ms,
        source_set_sha256,
        digest({"assessment": assessment_sha256, "history": mapped.history_sha256}),
        sources,
        rows[-1],
        required_sources,
        policy,
    )
    return HypothesisPreparation(
        "CONTEXT_PROPOSAL",
        "WAITING_TRIGGER",
        "MAPPED_IDEA_SEALED_AS_V2_HYPOTHESIS",
        plan,
        mapped.history_sha256,
    )
