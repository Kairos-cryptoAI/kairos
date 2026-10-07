"""Offline four-path accounting of caller-attested causal observations.

This module makes no model/venue calls and creates no runtime risk decisions.
Receipts are validated inputs, not proof of a producer, invoice or alpha. The
existing campaign evaluator, strategy configurations and frozen plans are not used.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from kairos_core.contracts.decision_context import DecisionContextReceiptV1
from kairos_core.contracts.llm_proposal import LLMTradeProposalV1
from kairos_core.contracts.llm_proposal_completion import LLMProposalCompletionReceiptV1
from kairos_core.enums import LLMProposalAction, Side
from kairos_core.topics import Topics
from kairos_strategy.models import SleeveIntent

from .engine import COMMON_COST_RISK, AccountCost, CostScenario, entry_time, replay_tape
from .filters import FILTER_POLICY, FILTER_POLICY_SHA256, CausalFilterObservation, causal_filter_decision
from .inputs import UNIVERSE, WindowInputs
from .matched import MatchedSlot, ReviewReceipt

PATHS = ("strategy_only", "context_review", "independent_proposals", "combined")
COMBINED_POLICY = "REVIEW_REQUIRED_CONFLICT_ABSTAIN_STRATEGY_FIRST_V1"
CADENCE_MS = 300_000
BIAS = {LLMProposalAction.LONG_BIAS: Side.LONG, LLMProposalAction.SHORT_BIAS: Side.SHORT}
SOURCE_TOPICS = {
    "market": Topics.MARKET_SNAPSHOT,
    "closed_bars": Topics.CLOSED_BAR,
    "text": Topics.SENTIMENT_SIGNAL,
    "macro": Topics.STRATEGIC_ALLOCATION,
}


def _sha(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise ValueError("canonical SHA256 identity required")


def _clock(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("clock must be a nonnegative integer")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class SourceCut:
    """Source-specific receive clocks/TTL; payload archive qualification is separate."""

    kind: str
    required: bool
    availability: str
    receipts: tuple[DecisionContextReceiptV1, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"market", "closed_bars", "text", "macro"} or type(self.required) is not bool:
            raise ValueError("explicit source kind and requirement required")
        if not isinstance(self.receipts, tuple):
            raise ValueError("immutable source receipts required")
        if any(
            not isinstance(r, DecisionContextReceiptV1) or r.topic != SOURCE_TOPICS[self.kind]
            for r in self.receipts
        ):
            raise ValueError("source receipt topic differs from its declared kind")
        for receipt in self.receipts:
            DecisionContextReceiptV1.model_validate(receipt.model_dump(mode="json"))
        if self.availability == "AVAILABLE":
            if not self.receipts or self.reason is not None:
                raise ValueError("available source needs receipts, not an absence reason")
            if self.kind in {"market", "macro"} and len(self.receipts) != 1:
                raise ValueError("exact single market/macro snapshot required")
            if len({r.message_id for r in self.receipts}) != len(self.receipts):
                raise ValueError("duplicate source receipt")
        elif self.availability != "UNAVAILABLE" or self.receipts or not self.reason:
            raise ValueError("unavailable source needs a reason and no fabricated receipt")

    @property
    def sha256(self) -> str:
        return _digest(
            {
                "kind": self.kind,
                "required": self.required,
                "availability": self.availability,
                "reason": self.reason,
                "receipts": [r.model_dump(mode="json") for r in self.receipts],
            }
        )

    def ready_at(self, clock_ms: int) -> bool:
        return self.availability == "AVAILABLE" and all(
            r.event_at_ms <= r.produced_at_ms <= r.received_at_ms <= clock_ms
            and clock_ms - r.event_at_ms <= r.ttl_ms
            for r in self.receipts
        )


@dataclass(frozen=True)
class SystemSlot:
    matched: MatchedSlot
    symbol: str
    state: str
    candidate: SleeveIntent | None
    sources: tuple[SourceCut, ...]
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        _clock(self.matched.decision_ms)
        _clock(self.matched.context_cut_ms)
        if self.symbol not in UNIVERSE or self.state not in {"CANDIDATE", "QUIET", "UNAVAILABLE"}:
            raise ValueError("explicit fixed-universe strategy state required")
        if self.state == "UNAVAILABLE":
            if not self.unavailable_reason or self.unavailable_reason != self.unavailable_reason.strip():
                raise ValueError("unavailable strategy must retain its explicit reason")
        elif self.unavailable_reason is not None:
            raise ValueError("valid strategy slot cannot have an unavailable reason")
        if not isinstance(self.sources, tuple) or len(self.sources) != 4:
            raise ValueError("all four immutable source slots required")
        if {s.kind for s in self.sources} != {"market", "closed_bars", "text", "macro"}:
            raise ValueError("all four source kinds required exactly once")
        for source in self.sources:
            if source.kind in {"market", "closed_bars"} and not source.required:
                raise ValueError("market and closed bars always mandatory")
            for receipt in source.receipts:
                if not receipt.event_at_ms <= receipt.produced_at_ms <= receipt.received_at_ms:
                    raise ValueError("source clock ordering invalid")
                if receipt.received_at_ms > self.matched.context_cut_ms:
                    raise ValueError("source was not received at causal cut")
        if self.state == "CANDIDATE":
            if (
                self.candidate is None
                or self.candidate.intent_id != self.matched.candidate_id
                or self.candidate.symbol != self.symbol
                or self.candidate.decision_ts_ms != self.matched.decision_ms
            ):
                raise ValueError("exact immutable baseline candidate required")
        elif self.candidate is not None or self.matched.candidate_id is not None:
            raise ValueError("quiet/unavailable cannot carry a baseline candidate")
        if self.state != "UNAVAILABLE" and not all(
            s.ready_at(self.matched.decision_ms) for s in self.sources if s.kind in {"market", "closed_bars"}
        ):
            raise ValueError("valid candidate/quiet state requires causal market sources")

    def context_ready_at(self, clock_ms: int) -> bool:
        # Optional absence is explicit; an AVAILABLE source in the supplied
        # context may not be silently reused after its own TTL expires.
        return all(s.ready_at(clock_ms) for s in self.sources if s.required or s.availability == "AVAILABLE")

    @property
    def context_sha256(self) -> str:
        # The whole tape digest is an audit identity, NEVER future model input.
        return _digest(
            {
                "slot_id": self.matched.slot_id,
                "input_window_sha256": self.matched.input_window_sha256,
                "sources": {source.kind: source.sha256 for source in self.sources},
            }
        )


@dataclass(frozen=True)
class AttemptReceipt:
    """Local observable clock, retained cost (possibly unknown) and disposition."""

    attempt_id: str
    requested_ms: int
    observed_ms: int
    cost_usd: float | None
    status: str
    evidence_kind: str
    context_sha256: str
    no_call_reason: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.attempt_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", self.attempt_id) is None
        ):
            raise ValueError("native normalized attempt identifier required")
        _sha(self.context_sha256)
        _clock(self.requested_ms)
        _clock(self.observed_ms)
        if self.observed_ms < self.requested_ms:
            raise ValueError("response cannot be observed before request")
        if self.status not in {"COMPLETE", "ERROR", "NOT_CALLED"}:
            raise ValueError("explicit attempt disposition required")
        if self.evidence_kind not in {"TEST_FIXTURE", "OBSERVED_POINT_IN_TIME"}:
            raise ValueError("explicit fixture/observation provenance required")
        if self.cost_usd is not None and (
            isinstance(self.cost_usd, bool)
            or not isinstance(self.cost_usd, (int, float))
            or not math.isfinite(self.cost_usd)
            or self.cost_usd < 0
        ):
            raise ValueError("finite nonnegative recorded cost or unknown required")
        if self.status == "NOT_CALLED" and self.cost_usd != 0:
            raise ValueError("explicit no-call outcome must record zero call cost")
        if self.status == "NOT_CALLED":
            if self.no_call_reason not in {
                "BUDGET_DENIED",
                "REQUIRED_SOURCE_UNAVAILABLE",
                "SCHEDULED_POLICY_ABSTAIN",
            }:
                raise ValueError("scheduled no-call must retain its explicit policy reason")
        elif self.no_call_reason is not None:
            raise ValueError("called attempt cannot have a no-call policy reason")


@dataclass(frozen=True)
class ReviewObservation:
    slot_id: str
    attempt: AttemptReceipt
    review: ReviewReceipt | None

    def __post_init__(self) -> None:
        _sha(self.slot_id)
        if (self.attempt.status == "COMPLETE") != (self.review is not None):
            raise ValueError("completed review needs its exact receipt; errors cannot invent one")
        if self.review is not None and (
            self.review.slot.slot_id != self.slot_id
            or self.review.requested_ms != self.attempt.requested_ms
            or self.review.captured_ms != self.attempt.observed_ms
            or self.review.evidence_kind != self.attempt.evidence_kind
            or self.attempt.cost_usd is not None
            and self.review.cost_usd != self.attempt.cost_usd
        ):
            raise ValueError("review attempt/cost/local observation link mismatch")
        if self.review is not None:
            for clock in (self.review.requested_ms, self.review.completed_ms, self.review.captured_ms):
                _clock(clock)


@dataclass(frozen=True)
class ProposalMapping:
    """Separate deterministic mapper output, never raw model order parameters."""

    proposal_id: str
    input_window_sha256: str
    policy_sha256: str
    mapped_ms: int
    candidate: SleeveIntent | None

    def __post_init__(self) -> None:
        for value in (self.proposal_id, self.input_window_sha256, self.policy_sha256):
            _sha(value)
        _clock(self.mapped_ms)


@dataclass(frozen=True)
class ProposalObservation:
    slot_id: str
    attempt: AttemptReceipt
    proposal: LLMTradeProposalV1 | None
    completion: LLMProposalCompletionReceiptV1 | None
    mapping: ProposalMapping | None = None

    def __post_init__(self) -> None:
        _sha(self.slot_id)
        if self.attempt.status != "COMPLETE":
            if self.proposal is not None or self.completion is not None or self.mapping is not None:
                raise ValueError("error/no-call cannot invent a proposal or mapping")
            return
        p, c = self.proposal, self.completion
        if p is None or c is None:
            raise ValueError("completed proposal needs native proposal and completion")
        # A frozen Pydantic model_copy can bypass its constructor validators.
        # Revalidate raw canonical facts, not only agreement between forged IDs.
        LLMTradeProposalV1.model_validate(p.model_dump(mode="json"))
        LLMProposalCompletionReceiptV1.model_validate(c.model_dump(mode="json"))
        fields = (
            "proposal_id",
            "campaign_id",
            "arm_id",
            "sample_id",
            "symbol",
            "timeframe",
            "market_as_of_ts_ms",
            "market_snapshot_sha256",
            "model_provenance",
        )
        if any(getattr(p, field) != getattr(c, field) for field in fields) or (
            c.attempt_id != self.attempt.attempt_id
            or c.attempt_started_at_ts_ms != self.attempt.requested_ms
            or c.response_observed_at_ts_ms != self.attempt.observed_ms
            or p.model_provenance.provider != "OPENAI"
            or p.model_provenance.latency_ms > self.attempt.observed_ms - self.attempt.requested_ms
            or self.attempt.cost_usd is not None
            and p.model_provenance.cost_usd != self.attempt.cost_usd
        ):
            raise ValueError("native proposal/completion/attempt identity mismatch")
        if self.mapping is not None and (
            self.mapping.proposal_id != p.proposal_id or self.mapping.mapped_ms < self.attempt.observed_ms
        ):
            raise ValueError("mapper must follow observation of the exact proposal")


def _index(observations: tuple[Any, ...], slots: dict[str, SystemSlot], fixture_only: bool) -> dict[str, Any]:
    indexed: dict[str, Any] = {}
    for obs in observations:
        if obs.slot_id not in slots or obs.slot_id in indexed:
            raise ValueError("unknown/duplicate slot observation")
        if (obs.attempt.evidence_kind == "TEST_FIXTURE") != fixture_only:
            raise ValueError("fixture and observation economics cannot be mixed or relabelled")
        if obs.attempt.requested_ms < slots[obs.slot_id].matched.decision_ms:
            raise ValueError("attempt cannot predate the causal slot")
        if obs.attempt.context_sha256 != slots[obs.slot_id].context_sha256:
            raise ValueError("attempt differs from the common causal source context")
        indexed[obs.slot_id] = obs
    return indexed


def _validate_links(
    slots: dict[str, SystemSlot],
    reviews: dict[str, ReviewObservation],
    proposals: dict[str, ProposalObservation],
    policy_sha256: str,
) -> None:
    """Validate even late/unavailable inputs before replaying any account."""
    for slot_id, obs in reviews.items():
        slot = slots[slot_id]
        if slot.candidate is None:
            raise ValueError("review cannot invent a candidate on a quiet/unavailable slot")
        if obs.review is not None and (
            obs.review.slot != slot.matched
            or obs.review.point_in_time_news_sha256
            != next(s.sha256 for s in slot.sources if s.kind == "text")
        ):
            raise ValueError("review cannot change slot/candidate/causal news source")
    scopes = set()
    for slot_id, obs in proposals.items():
        slot, p, mapping = slots[slot_id], obs.proposal, obs.mapping
        if p is None:
            continue
        market = next(s for s in slot.sources if s.kind == "market")
        if (
            not market.receipts
            or p.symbol != slot.symbol
            or p.sample_id != slot.matched.slot_id
            or p.timeframe != "5m"
            or p.market_as_of_ts_ms != slot.matched.decision_ms
            or p.market_snapshot_sha256 != market.receipts[0].content_sha256
        ):
            raise ValueError("proposal is not linked to the common causal slot/market")
        scopes.add((p.campaign_id, p.arm_id))
        allowed = {
            (r.message_id, r.content_sha256, r.received_at_ms)
            for source in slot.sources
            for r in source.receipts
        }
        allowed.add(("input_window", slot.matched.input_window_sha256, slot.matched.context_cut_ms))
        if any((e.reference, e.content_sha256, e.observed_at_ms) not in allowed for e in p.evidence):
            raise ValueError("proposal cites evidence outside the causal source roster")
        if p.action not in BIAS and mapping is not None:
            raise ValueError("nontrading model action cannot carry trade geometry")
        if mapping is not None:
            if (
                mapping.policy_sha256 != policy_sha256
                or mapping.input_window_sha256 != slot.matched.input_window_sha256
            ):
                raise ValueError("mapper policy or causal input identity changed")
            candidate = mapping.candidate
            if candidate is not None and (
                candidate.symbol != slot.symbol
                or candidate.side is not BIAS[p.action]
                or candidate.decision_ts_ms != slot.matched.decision_ms
                or candidate.intent_id == slot.matched.candidate_id
                or candidate.entry_expires_ts_ms > p.expires_at_ts_ms
            ):
                raise ValueError("independent mapped candidate direction/scope/lifetime mismatch")
    if len(scopes) > 1:
        raise ValueError("proposal campaign/arm scope cannot be mixed")


def evaluate_system_paths(
    inputs: WindowInputs,
    slots: tuple[SystemSlot, ...],
    reviews: tuple[ReviewObservation, ...],
    proposals: tuple[ProposalObservation, ...],
    scenario: CostScenario,
    mode: str,
    *,
    mapper_policy_sha256: str,
    fixture_only: bool = False,
    baseline_latency_ms: int = 100,
    feed_costs: tuple[AccountCost, ...] | None = None,
    deadline: float | None = None,
    deterministic_filters: tuple[CausalFilterObservation, ...] | None = None,
    include_selection_audit: bool = False,
    include_review_timing_control: bool = False,
) -> dict[str, Any]:
    """Validate complete roster first, then replay independent nonqualifying accounts.

    Missing/unknown-cost observations null that path, not a selected profitable
    subset. Missing mapper evidence is not a genuine NO_PROPOSAL observation.
    Feed debits are copied to each hypothetical path; shared model attempts are
    charged once per account, not added a second time in the combined path.
    An explicit filter roster adds a fifth independent causal-source control;
    absent filter observations null its economics, never select a winning subset.
    A timing/cost-matched control omits review content but pays the same attempts;
    its independent delta includes content selection AND operational error gating,
    not pure content alpha. The called-error clock is terminal observation only.
    Default four-arm semantics and output remain unchanged.
    """
    _sha(mapper_policy_sha256)
    _clock(baseline_latency_ms)
    if (
        type(fixture_only) is not bool
        or type(include_selection_audit) is not bool
        or type(include_review_timing_control) is not bool
        or not isinstance(slots, tuple)
        or not 0 < len(slots) <= 100_000
        or not isinstance(reviews, tuple)
        or not isinstance(proposals, tuple)
        or feed_costs is not None
        and not isinstance(feed_costs, tuple)
        or type(inputs.start_ms) is not int
        or type(inputs.end_ms) is not int
        or inputs.start_ms <= 0
        or inputs.end_ms <= inputs.start_ms
        or inputs.start_ms % 60_000
        or inputs.end_ms % 60_000
    ):
        raise ValueError("bounded immutable full schedule required")
    implied_count = ((inputs.end_ms - inputs.start_ms + CADENCE_MS - 1) // CADENCE_MS) * len(UNIVERSE)
    if implied_count > 100_000 or implied_count != len(slots):
        raise ValueError("complete fixed five-minute/five-symbol roster required within bounded window")
    expected = {
        (ts - 1, symbol) for ts in range(inputs.start_ms, inputs.end_ms, CADENCE_MS) for symbol in UNIVERSE
    }
    if len(slots) != len(expected) or {(s.matched.decision_ms, s.symbol) for s in slots} != expected:
        raise ValueError("complete fixed five-minute/five-symbol roster required")
    by_id = {slot.matched.slot_id: slot for slot in slots}
    if len(by_id) != len(slots) or len({s.matched.tape_sha256 for s in slots}) != 1:
        raise ValueError("unique slot identity and one common tape required")
    review_index, proposal_index = (
        _index(reviews, by_id, fixture_only),
        _index(proposals, by_id, fixture_only),
    )
    _validate_links(by_id, review_index, proposal_index, mapper_policy_sha256)
    filter_decisions: dict[str, dict[str, Any]] = {}
    if deterministic_filters is not None:
        if not isinstance(deterministic_filters, tuple) or len(deterministic_filters) > len(slots):
            raise ValueError("bounded immutable filter roster required")
        for observation in deterministic_filters:
            if (
                not isinstance(observation, CausalFilterObservation)
                or observation.slot_id not in by_id
                or observation.slot_id in filter_decisions
            ):
                raise ValueError("unknown or duplicate filter observation")
            filter_decisions[observation.slot_id] = causal_filter_decision(
                by_id[observation.slot_id], observation, mode, fixture_only=fixture_only
            )
    attempts = [obs.attempt for obs in (*reviews, *proposals)]
    if len({a.attempt_id for a in attempts}) != len(attempts):
        raise ValueError("duplicate model attempt identity")
    horizon = inputs.end_ms + 3 * 3_600_000
    if any(not inputs.start_ms <= a.observed_ms < horizon for a in attempts):
        raise ValueError("out-of-horizon model liability cannot be silently dropped")
    if any(not inputs.start_ms <= d["observed_ms"] < horizon for d in filter_decisions.values()):
        raise ValueError("out-of-horizon filter observation cannot be silently dropped")
    if feed_costs is not None and (
        any(c.kind != "FEED" or not inputs.start_ms <= c.timestamp_ms < horizon for c in feed_costs)
        or len({c.cost_id for c in feed_costs}) != len(feed_costs)
        or {c.cost_id for c in feed_costs} & {a.attempt_id for a in attempts}
    ):
        raise ValueError("exact unique feed debit clocks required")
    paths = (*PATHS, "deterministic_filter") if deterministic_filters is not None else PATHS
    if include_review_timing_control:
        paths = (*paths, "review_timing_control")
    selected: dict[str, list[tuple[SleeveIntent, int]]] = {path: [] for path in paths}
    reasons: dict[str, Counter[str]] = {path: Counter() for path in paths}
    missing = Counter()
    for slot in sorted(slots, key=lambda s: (s.matched.decision_ms, UNIVERSE.index(s.symbol))):
        r, p = review_index.get(slot.matched.slot_id), proposal_index.get(slot.matched.slot_id)
        if slot.state == "UNAVAILABLE":
            for path in paths:
                reasons[path]["SOURCE_UNAVAILABLE"] += 1
            continue
        base, reviewed, proposed = slot.candidate, None, None
        if include_review_timing_control:
            if base is None:
                reasons["review_timing_control"]["QUIET"] += 1
            elif r is None:
                missing["review_timing_control"] += 1
            elif r.attempt.status == "NOT_CALLED":
                # A budget/source denial is not an actual inference completion.
                reasons["review_timing_control"]["NOT_CALLED"] += 1
            else:
                quote_ms = entry_time(base, r.attempt.observed_ms, mode)
                if slot.context_ready_at(max(r.attempt.observed_ms, quote_ms or 0)):
                    selected["review_timing_control"].append((base, r.attempt.observed_ms))
                else:
                    reasons["review_timing_control"]["STALE_CONTEXT"] += 1
        if deterministic_filters is not None:
            if base is None:
                reasons["deterministic_filter"]["QUIET"] += 1
            elif slot.matched.slot_id not in filter_decisions:
                missing["deterministic_filter"] += 1
            else:
                decision = filter_decisions[slot.matched.slot_id]
                if decision["disposition"] == "ALLOW":
                    selected["deterministic_filter"].append((base, decision["observed_ms"]))
                else:
                    reasons["deterministic_filter"][decision["reason"]] += 1
        if base is not None:
            selected["strategy_only"].append((base, base.decision_ts_ms + baseline_latency_ms))
            if r is None:
                missing["context_review"] += 1
            elif r.review is not None:
                quote_ms = entry_time(base, r.attempt.observed_ms, mode)
                if r.review.result == "ALLOW" and slot.context_ready_at(
                    max(r.attempt.observed_ms, quote_ms or 0)
                ):
                    reviewed = (base, r.attempt.observed_ms)
                else:
                    reasons["context_review"][
                        r.review.result if r.review.result != "ALLOW" else "STALE_CONTEXT"
                    ] += 1
            else:
                reasons["context_review"][r.attempt.status] += 1
        else:
            if r is not None:
                raise ValueError("review cannot invent a candidate on a quiet slot")
            reasons["strategy_only"]["QUIET"] += 1
            reasons["context_review"]["QUIET"] += 1
        if reviewed is not None:
            selected["context_review"].append(reviewed)
        if p is None:
            missing["independent_proposals"] += 1
        elif p.proposal is not None:
            native, completion, mapping = p.proposal, p.completion, p.mapping
            if completion.is_late or p.attempt.observed_ms > native.expires_at_ts_ms:
                reasons["independent_proposals"]["LATE_PROPOSAL"] += 1
            elif native.action not in BIAS:
                reasons["independent_proposals"][native.action.value] += 1
            elif mapping is None:
                missing["independent_proposals"] += 1
                reasons["independent_proposals"]["MAPPER_UNAVAILABLE"] += 1
            else:
                candidate = mapping.candidate
                if candidate is None:
                    reasons["independent_proposals"]["MAPPER_REJECTED"] += 1
                elif mapping.mapped_ms >= completion.sample_deadline_ts_ms or not slot.context_ready_at(
                    max(mapping.mapped_ms, entry_time(candidate, mapping.mapped_ms, mode) or 0)
                ):
                    reasons["independent_proposals"]["LATE_OR_STALE_MAPPING"] += 1
                else:
                    proposed = (candidate, mapping.mapped_ms)
                    selected["independent_proposals"].append(proposed)
        else:
            reasons["independent_proposals"][p.attempt.status] += 1
        # Fixed conservative research control, not a new frozen production policy.
        # A proposal cannot override a baseline review refusal in this combined arm.
        if base is None and proposed is not None:
            selected["combined"].append(proposed)
        elif base is not None and reviewed is not None and p is not None:
            combined_ms = max(reviewed[1], p.attempt.observed_ms, proposed[1] if proposed else 0)
            base_quote_ms = entry_time(base, combined_ms, mode)
            arbitration_ms = max(combined_ms, base_quote_ms or 0)
            if (
                p.attempt.status != "COMPLETE"
                or p.completion.is_late
                or arbitration_ms >= p.completion.sample_deadline_ts_ms
                or arbitration_ms > p.proposal.expires_at_ts_ms
            ):
                reasons["combined"]["PROPOSAL_UNUSABLE"] += 1
            elif p.proposal.action in BIAS and proposed is None:
                reasons["combined"]["PROPOSAL_UNUSABLE"] += 1
            elif proposed is not None and (
                entry_time(proposed[0], arbitration_ms, mode) is None
                or entry_time(proposed[0], arbitration_ms, mode) >= inputs.end_ms
            ):
                reasons["combined"]["PROPOSAL_NO_ELIGIBLE_QUOTE"] += 1
            elif proposed is not None and proposed[0].side is not base.side:
                reasons["combined"]["DIRECTION_CONFLICT"] += 1
            else:
                if slot.context_ready_at(arbitration_ms):
                    selected["combined"].append((base, combined_ms))
                else:
                    reasons["combined"]["STALE_CONTEXT"] += 1
        else:
            reasons["combined"]["REVIEW_BLOCKED" if base else "NO_MAPPED_PROPOSAL"] += 1
    results: dict[str, Any] = {}
    for path in paths:
        observations = (
            ()
            if path in {"strategy_only", "deterministic_filter"}
            else reviews
            if path in {"context_review", "review_timing_control"}
            else proposals
            if path == "independent_proposals"
            else (*reviews, *proposals)
        )
        missing_count = (
            missing[path]
            if path != "combined"
            else missing["context_review"] + missing["independent_proposals"]
        )
        unknown = sum(obs.attempt.cost_usd is None for obs in observations)
        costs = tuple(
            AccountCost(obs.attempt.attempt_id, obs.attempt.observed_ms, obs.attempt.cost_usd, "MODEL")
            for obs in observations
            if obs.attempt.cost_usd is not None and obs.attempt.status != "NOT_CALLED"
        )
        result: dict[str, Any] = {
            "status": "INCOMPLETE"
            if missing_count or unknown
            else "FIXTURE_ONLY"
            if fixture_only
            else "CALLER_ATTESTED_CONDITIONAL_REPLAY",
            "missing_observations": missing_count,
            "unknown_cost_attempts": unknown,
            "known_model_cost_usd": math.fsum(c.amount_usd for c in costs),
            "decisions": dict(sorted(reasons[path].items())),
            "economic_results": None,
            "recorded_all_in_net_result": None,
            "model_call_count": sum(obs.attempt.status != "NOT_CALLED" for obs in observations),
            "scheduled_no_call_outcomes": sum(obs.attempt.status == "NOT_CALLED" for obs in observations),
            "observed_complete_response_count": sum(obs.attempt.status == "COMPLETE" for obs in observations),
            "retained_error_outcomes": sum(obs.attempt.status == "ERROR" for obs in observations),
            "complete_all_in_net_economics": False,
        }
        if not missing_count and not unknown:
            tape: dict[int, list[SleeveIntent]] = {}
            clocks: dict[str, int] = {}
            for candidate, clock in selected[path]:
                if candidate.intent_id in clocks:
                    raise ValueError("duplicate candidate across scheduled slots")
                tape.setdefault(candidate.decision_ts_ms, []).append(candidate)
                clocks[candidate.intent_id] = clock
            economics, account = replay_tape(
                inputs,
                tape,
                scenario,
                mode,
                baseline_latency_ms,
                admission_policy=COMMON_COST_RISK,
                completion_times_ms=clocks,
                service_costs=(*costs, *(feed_costs or ())),
                deadline=deadline,
            )
            result.update({"economic_results": economics, "events": account.events, "trades": account.trades})
            result["all_recorded_costs_included"] = feed_costs is not None
            if feed_costs is not None:
                result["recorded_all_in_net_result"] = {
                    "final_equity_usd": economics["final_equity_usd"],
                    "net_return_pct": economics["net_return_pct"],
                    "scope": "RECORDED_COSTS_CONDITIONAL_EXECUTION_NOT_INVOICE_OR_ALPHA_PROOF",
                }
        results[path] = result
    report = {
        "schema": "kairos.development.full-system-paths.v2"
        if deterministic_filters is not None or include_selection_audit or include_review_timing_control
        else "kairos.development.full-system-paths.v1",
        "scope": "FIXTURE_ONLY" if fixture_only else "CALLER_ATTESTED_CONDITIONAL_REPLAY",
        "scheduled_slots": len(slots),
        "slot_states": dict(Counter(s.state for s in slots)),
        "unavailable_reasons": dict(Counter(s.unavailable_reason for s in slots if s.state == "UNAVAILABLE")),
        "combined_policy": COMBINED_POLICY,
        "mapper_policy_sha256": mapper_policy_sha256,
        "arms": results,
        "paired_account_deltas_usd": {
            path: results[path]["economic_results"]["final_equity_usd"]
            - results["strategy_only"]["economic_results"]["final_equity_usd"]
            if results[path]["economic_results"] is not None
            else None
            for path in paths
            if path != "strategy_only"
        },
        "review_counterfactuals": [
            {
                "slot_id": slot_id,
                "candidate_id": observation.review.candidate_id,
                "review_result": observation.review.result,
                "baseline_closed_trade_net_usd": next(
                    (
                        trade["net_pnl_usd"]
                        for trade in results["strategy_only"]["trades"]
                        if trade["intent_id"] == observation.review.candidate_id
                    ),
                    None,
                ),
                "scope": "BASELINE_TRADE_DIAGNOSTIC_NOT_ATTRIBUTABLE_ARM_PROFIT",
            }
            for slot_id, observation in review_index.items()
            if observation.review is not None and observation.review.result != "ALLOW"
        ],
        "account_delta_scope": "INDEPENDENT_ACCOUNTS_NOT_ADDITIVE_TRADE_ATTRIBUTION",
        "cash_event_mark_authority": "MINUTE_OPEN_PRICE_PROXY_NOT_OBSERVED_INTRAMINUTE_MARK",
        "source_attestation": "CALLER_SUPPLIED_CLOCKS_DIGESTS_NOT_PRODUCER_OR_PAYLOAD_ARCHIVE_QUALIFICATION",
        "admission_policy": COMMON_COST_RISK,
        "execution_qualified": False,
        "matched_campaign_executed": False,
        "blind_campaign_enrolled": False,
        "alpha_ready": False,
        "technical_paper_ready": False,
        "paper_qualified": False,
        "live_ready": False,
        "strategy_policy": "REJECT_ALL",
    }
    if deterministic_filters is not None:
        report["deterministic_filter_control"] = {
            "policy": FILTER_POLICY,
            "policy_sha256": FILTER_POLICY_SHA256,
            "receipt_count": len(filter_decisions),
            "decisions": list(filter_decisions.values()),
            "source_truth": "CALLER_ATTESTED_RECEIPTS_NOT_RAW_NEWS_OR_MACRO_PAYLOAD_PROOF",
            "standalone_profitability_is_admission_requirement": False,
            "daily_trade_quota": None,
            "cpu_and_unrecorded_infrastructure_costs": "UNQUALIFIED",
        }
    if include_review_timing_control:
        review_net = results["context_review"]["economic_results"]
        timing_net = results["review_timing_control"]["economic_results"]
        report["review_timing_control"] = {
            "policy": "SAME_REVIEW_ATTEMPTS_CLOCKS_COSTS_CAUSAL_CONTEXT_WITHOUT_CONTENT_V1",
            "called_errors": "KNOWN_TERMINAL_OBSERVATION_CLOCK_NOT_SUCCESSFUL_COMPLETION_STILL_CHARGED",
            "not_called": "KNOWN_POLICY_ABSTENTION_NOT_INFERENCE_COMPLETION",
            "context_review_minus_timing_control_usd": (
                review_net["final_equity_usd"] - timing_net["final_equity_usd"]
                if review_net is not None and timing_net is not None
                else None
            ),
            "scope": "INDEPENDENT_ACCOUNT_CONTROL_NOT_ADDITIVE_TRADE_ALPHA_OR_INVOICE_PROOF",
            "delta_includes": "REVIEW_CONTENT_SELECTION_AND_OPERATIONAL_ERROR_GATING_NOT_PURE_CONTENT_ALPHA",
        }
    if deterministic_filters is not None or include_selection_audit or include_review_timing_control:
        from .candidate_audit import build_candidate_audit

        audit_decisions: dict[str, dict[str, dict[str, Any]]] = {"context_review": {}}
        reviewed_ids = {candidate.intent_id for candidate, _ in selected["context_review"]}
        for slot_id, observation in review_index.items():
            disposition = observation.attempt.status
            if observation.review is not None:
                disposition = observation.review.result
                if disposition == "ALLOW" and observation.review.candidate_id not in reviewed_ids:
                    disposition = "STALE_CONTEXT"
            audit_decisions["context_review"][slot_id] = {
                "disposition": disposition,
                "retained_for_replay": by_id[slot_id].candidate.intent_id in reviewed_ids,
                "observed_ms": observation.attempt.observed_ms,
                "cost_usd": observation.attempt.cost_usd,
                "no_call_reason": observation.attempt.no_call_reason,
            }
        if include_review_timing_control:
            timing_ids = {candidate.intent_id for candidate, _ in selected["review_timing_control"]}
            audit_decisions["review_timing_control"] = {
                slot_id: {
                    "disposition": "CONTENT_IGNORED_CAUSAL_CONTEXT_READY"
                    if by_id[slot_id].candidate.intent_id in timing_ids
                    else "NOT_CALLED"
                    if observation.attempt.status == "NOT_CALLED"
                    else "STALE_CONTEXT",
                    "retained_for_replay": by_id[slot_id].candidate.intent_id in timing_ids,
                    "observed_ms": observation.attempt.observed_ms,
                    "cost_usd": observation.attempt.cost_usd,
                    "no_call_reason": observation.attempt.no_call_reason,
                }
                for slot_id, observation in review_index.items()
            }
        if deterministic_filters is not None:
            audit_decisions["deterministic_filter"] = {
                slot_id: {
                    "disposition": decision["reason"],
                    "retained_for_replay": decision["disposition"] == "ALLOW",
                    "observed_ms": decision["observed_ms"],
                    "cost_usd": 0.0,
                    "no_call_reason": "DETERMINISTIC_CONTROL_NO_MODEL_CALL",
                }
                for slot_id, decision in filter_decisions.items()
            }
        report["candidate_selection_audit"] = build_candidate_audit(slots, results, audit_decisions)
    return report
