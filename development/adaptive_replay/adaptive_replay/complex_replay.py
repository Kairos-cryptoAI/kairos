"""Matched sparse-cut reconstruction using one common modern assessment.

No provider, database, archive download, production registration or order path.
Modern clocks remain in the receipt; only explicitly labelled elapsed times and
recorded costs are projected into hypothetical historical accounts.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from typing import Any

from .complex_assessment import (
    RetrospectiveAssessment,
    arbitrate_combined,
    directional_review,
    read_assessment,
)
from .complex_frame import ContextAssessmentFrame
from .complex_protocol import (
    EPISODES,
    MODEL_ROUTE,
    READINESS,
    fixed_protocol,
    model_config_sha256,
    protocol_sha256,
    requirements,
    utc_ms,
)
from .complex_strategy import HISTORY_BARS, MappedProposal, evaluate_complex, map_context_proposal
from .engine import COMMON_COST_RISK, AccountCost, CostScenario, entry_time, replay_tape
from .historical_context import _clock, _sha, as_of_context, digest
from .historical_inputs import validate_replay_inputs
from .inputs import UNIVERSE, WindowInputs

ARMS = ("strategy_only", "context_review", "independent_proposals", "combined", "review_timing_control")
MAX_DELAY_MS = 300_000


def _frame_snapshot(frame: ContextAssessmentFrame) -> dict[str, Any]:
    """Reuse one validated immutable prompt within a call, never trust a cache."""
    prompt = frame.prompt_payload()  # revalidates all closed bars and sources
    view = as_of_context(frame.archive, frame.history.symbol, frame.knowledge_cut_ms, frame.requirements)
    return {
        "frame_id": digest({"prompt": prompt, "protocol_sha256": frame.protocol_sha256}),
        "prompt_sha256": digest(prompt),
        "context": prompt["context"],
        "sources_ready": view["required_sources_ready"],
        "materialized_ms": max(
            frame.history.captured_at_ms, view["context_materialized_ms"], frame.knowledge_cut_ms
        ),
        "permitted_evidence_ids": frozenset(
            item["content_ref"] for s in prompt["context"]["sources"] for item in s["items"]
        ),
    }


@dataclass(frozen=True)
class TimedProposalMapping:
    frame_id: str
    assessment_sha256: str
    mapping: MappedProposal
    actual_started_ms: int
    actual_observed_ms: int
    monotonic_elapsed_ns: int

    @property
    def delay_ms(self) -> int:
        return math.ceil(self.monotonic_elapsed_ns / 1_000_000)

    def validate(self) -> None:
        _sha(self.frame_id)
        _sha(self.assessment_sha256)
        _clock(self.actual_started_ms)
        _clock(self.actual_observed_ms)
        _clock(self.monotonic_elapsed_ns)
        if self.actual_observed_ms < self.actual_started_ms or self.delay_ms > MAX_DELAY_MS:
            raise ValueError("bounded actual mapper observation clocks required")
        if (
            type(self.mapping) is not MappedProposal
            or self.mapping.assessment_sha256 != self.assessment_sha256
        ):
            raise ValueError("timed mapping must bind the exact assessment identity")


def prepare_assessment_mappings(
    frames: tuple[ContextAssessmentFrame, ...],
    observations: tuple[RetrospectiveAssessment, ...],
    *,
    fixture_only: bool = False,
) -> tuple[TimedProposalMapping, ...]:
    """Materialize/timestamp ONCE, then reuse these receipts across all accounts."""
    snapshots = [(frame, _frame_snapshot(frame)) for frame in frames]
    by_id = {snapshot["frame_id"]: (frame, snapshot) for frame, snapshot in snapshots}
    if len(by_id) != len(frames) or len({o.frame_id for o in observations}) != len(observations):
        raise ValueError("unique frames and observations required before mapping")
    result = []
    for observation in observations:
        if observation.frame_id not in by_id:
            raise ValueError("mapping observation outside the declared frame roster")
        frame, snapshot = by_id[observation.frame_id]
        assessment = read_assessment(
            observation,
            expected_frame_id=snapshot["frame_id"],
            expected_prompt_sha256=snapshot["prompt_sha256"],
            permitted_evidence_ids=snapshot["permitted_evidence_ids"],
            fixture_only=fixture_only,
            not_before_ms=snapshot["materialized_ms"],
        )
        if assessment is None or not snapshot["sources_ready"]:
            continue
        actual_started = time.time_ns() // 1_000_000
        started = time.perf_counter_ns()
        mapping = map_context_proposal(
            assessment.proposal,
            frame.history.candles,
            cut_ms=frame.knowledge_cut_ms,
            assessment_sha256=digest(asdict(observation)),
        )
        elapsed = time.perf_counter_ns() - started
        timed = TimedProposalMapping(
            snapshot["frame_id"],
            digest(asdict(observation)),
            mapping,
            actual_started,
            time.time_ns() // 1_000_000,
            elapsed,
        )
        timed.validate()
        if timed.actual_started_ms < observation.actual_observed_ms:
            raise ValueError("mapping cannot precede the actual model observation")
        result.append(timed)
    return tuple(result)


def held_context_fresh(
    frame: ContextAssessmentFrame, at_ms: int, *, original_context: dict | None = None
) -> bool:
    """Do not trade on stale/unconsidered context or import it into the prompt.

    Recheck coverage and source-version identity at the effective quote clock.
    Newly available items can only cause DEFER, never supply favorable evidence
    or revise the immutable model response. Audit-only future versions are not
    passed to the model or proposal mapper.
    """
    original = frame.prompt_payload()["context"] if original_context is None else original_context
    later = as_of_context(frame.archive, frame.history.symbol, at_ms, frame.requirements)
    if later["required_sources_ready"] is not True:
        return False
    prior = {(s["source_name"], s["kind"]): s for s in original["sources"]}
    for source in later["context"]["sources"]:
        if not source["required"]:
            continue
        old = prior[source["source_name"], source["kind"]]
        if digest(source["items"]) != digest(old["items"]):
            return False
        if any(at_ms - item["available_ms"] > source["maximum_age_ms"] for item in old["items"]):
            return False
    return True


def evaluate_complex_historical(
    inputs: WindowInputs,
    frames: tuple[ContextAssessmentFrame, ...],
    observations: tuple[RetrospectiveAssessment, ...],
    scenario: CostScenario,
    mode: str,
    *,
    expected_cuts_ms: tuple[int, ...],
    fixture_only: bool = False,
    feed_costs: tuple[AccountCost, ...] | None = None,
    mappings: tuple[TimedProposalMapping, ...] = (),
    deadline: float | None = None,
) -> dict[str, Any]:
    """Evaluate ALL predeclared cells, never a profitable/available subset.

    Unavailable strategies, source gaps, missing receipts or unknown expenses
    null the affected whole account. Sparse roster economics are not continuous
    strategy/monthly performance and confer zero blind-campaign credit.
    """
    deadline = time.monotonic() + 300 if deadline is None else deadline
    validate_replay_inputs(inputs, fixture_only=fixture_only, deadline=deadline)
    if type(expected_cuts_ms) is not tuple or not 1 <= len(expected_cuts_ms) <= 4:
        raise ValueError("bounded immutable predeclared cut roster required")
    for cut in expected_cuts_ms:
        _clock(cut)
        if cut % 300_000 or not inputs.start_ms <= cut < inputs.end_ms:
            raise ValueError("in-window five-minute cut required")
    if tuple(sorted(set(expected_cuts_ms))) != expected_cuts_ms:
        raise ValueError("cut roster must be unique and ordered")
    if not fixture_only:
        matching = [
            cuts
            for _, start, end, cuts, _ in EPISODES
            if (utc_ms(start), utc_ms(end)) == (inputs.start_ms, inputs.end_ms)
        ]
        if len(matching) != 1 or expected_cuts_ms != tuple(utc_ms(c) for c in matching[0]):
            raise ValueError("non-fixture evaluation accepts only the frozen sparse episode cuts")
        if asdict(scenario) not in fixed_protocol()["cost_scenarios"]:
            raise ValueError("fixed base/stress scenarios only")
    if mode not in {"STRICT_MINUTE_OPEN", "INTRABAR_OPEN_PROXY"}:
        raise ValueError("explicit execution-resolution mode required")
    if type(frames) is not tuple or type(observations) is not tuple:
        raise ValueError("immutable frame/observation roster required")
    roster = {(cut, symbol) for cut in expected_cuts_ms for symbol in UNIVERSE}
    by_cell = {}
    snapshots = {}
    for frame in frames:
        frame.validate()
        key = (frame.knowledge_cut_ms, frame.history.symbol)
        if key not in roster or key in by_cell:
            raise ValueError("duplicate or undeclared frame in denominator")
        if frame.protocol_sha256 != protocol_sha256() or frame.requirements != requirements():
            raise ValueError("frame differs from frozen complex protocol/source requirements")
        if (frame.history.provenance == "TEST_FIXTURE") != fixture_only:
            raise ValueError("frame fixture mode differs from replay")
        source_rows = tuple(
            c for c in inputs.bars[key[1]] if key[0] - HISTORY_BARS * 60_000 <= c.open_time_ms < key[0]
        )
        if source_rows != frame.history.candles:
            raise ValueError("prompt history differs from replay input")
        by_cell[key] = frame
        snapshots[key] = _frame_snapshot(frame)
    if set(by_cell) != roster:
        raise ValueError("complete five-symbol/cut denominator required")
    by_id = {snapshots[key]["frame_id"]: frame for key, frame in by_cell.items()}
    if len(by_id) != len(frames):
        raise ValueError("duplicate frame identity")
    by_observation = {}
    attempted_ids = set()
    for observation in observations:
        if type(observation) is not RetrospectiveAssessment:
            raise ValueError("typed exact retrospective assessment required")
        if observation.frame_id not in by_id or observation.frame_id in by_observation:
            raise ValueError("extra or duplicate observation identity")
        if observation.attempt_id in attempted_ids:
            raise ValueError("one underlying attempt cannot belong to two assessment cells")
        attempted_ids.add(observation.attempt_id)
        by_observation[observation.frame_id] = observation
    by_mapping = {}
    if type(mappings) is not tuple:
        raise ValueError("immutable once-measured mapping receipt roster required")
    for timed in mappings:
        if type(timed) is not TimedProposalMapping:
            raise ValueError("exact typed mapping receipt required")
        timed.validate()
        observation = by_observation.get(timed.frame_id)
        if timed.frame_id in by_mapping or observation is None or observation.status != "COMPLETE":
            raise ValueError("extra, duplicate or uncalled mapping receipt")
        if (
            timed.assessment_sha256 != digest(asdict(observation))
            or timed.actual_started_ms < observation.actual_observed_ms
        ):
            raise ValueError("mapping identity/modern clock differs from assessment")
        by_mapping[timed.frame_id] = timed

    tapes = {arm: {} for arm in ARMS}
    completions = {arm: {} for arm in ARMS}
    costs: list[AccountCost] = []
    rows = []
    unknown_cost = 0
    known_costs = []
    baseline_complete = True
    model_complete = len(observations) == len(frames)
    feed_complete = feed_costs is not None
    if feed_costs is not None:
        if type(feed_costs) is not tuple or any(c.kind != "FEED" for c in feed_costs):
            raise ValueError("explicit immutable FEED-only costs required")

    def add(arm, candidate, ready_ms):
        if candidate is not None:
            tapes[arm].setdefault(candidate.entry_eligible_ts_ms, []).append(candidate)
            completions[arm][candidate.intent_id] = ready_ms

    for cut, symbol in sorted(roster, key=lambda k: (k[0], UNIVERSE.index(k[1]))):
        if time.monotonic() >= deadline:
            raise TimeoutError("bounded complex evaluation deadline reached")
        frame = by_cell[cut, symbol]
        snapshot = snapshots[cut, symbol]
        prefix_start = inputs.start_ms - HISTORY_BARS * 60_000
        prefix = tuple(c for c in inputs.bars[symbol] if prefix_start <= c.open_time_ms < cut)
        decision = evaluate_complex(prefix, prefix_start_ms=prefix_start, cut_ms=cut)
        baseline = decision.candidate
        baseline_complete &= decision.state != "UNAVAILABLE"
        baseline_ready = cut + 100
        add("strategy_only", baseline, baseline_ready)
        observation = by_observation.get(snapshot["frame_id"])
        assessment = None
        ready = cost_ready = baseline_ready
        mapping_elapsed = 0
        mapping = None
        reason = "MISSING_ASSESSMENT"
        if observation is not None:
            assessment = read_assessment(
                observation,
                expected_frame_id=snapshot["frame_id"],
                expected_prompt_sha256=snapshot["prompt_sha256"],
                permitted_evidence_ids=snapshot["permitted_evidence_ids"],
                fixture_only=fixture_only,
                not_before_ms=snapshot["materialized_ms"],
            )
            if not fixture_only and (
                observation.model != MODEL_ROUTE["model"]
                or observation.model_config_sha256 != model_config_sha256()
            ):
                raise ValueError("observation route differs from fixed approved model route")
            elapsed = observation.actual_observed_ms - observation.actual_requested_ms
            cost_elapsed = observation.actual_cost_observed_ms - observation.actual_requested_ms
            if cost_elapsed > MAX_DELAY_MS:
                # Cost must not disappear outside the replay horizon.
                model_complete = False
            ready = baseline_ready + elapsed
            cost_ready = baseline_ready + cost_elapsed
            if observation.recorded_cost_usd is None:
                unknown_cost += 1
                model_complete = False
            else:
                known_costs.append(float(observation.recorded_cost_usd))
                costs.append(
                    AccountCost(
                        "MODEL:" + observation.attempt_id, cost_ready, observation.recorded_cost_usd, "MODEL"
                    )
                )
            if not snapshot["sources_ready"]:
                if (
                    observation.status != "NOT_CALLED"
                    or observation.no_call_reason != "REQUIRED_SOURCE_UNAVAILABLE"
                ):
                    raise ValueError("unadmitted source frame must record required-source no-call")
                model_complete = False
            reason = observation.status
            if (
                observation.status == "NOT_CALLED"
                and observation.no_call_reason == "REQUIRED_SOURCE_UNAVAILABLE"
            ):
                model_complete = False
        else:
            model_complete = False
        if assessment is not None and snapshot["sources_ready"] and decision.state != "UNAVAILABLE":
            timed = by_mapping.get(snapshot["frame_id"])
            if timed is None:
                raise ValueError("complete assessment requires its once-measured mapping receipt")
            mapping = timed.mapping
            # Validate immutable geometry, not retime it for a favorable scenario.
            expected_mapping = map_context_proposal(
                assessment.proposal,
                frame.history.candles,
                cut_ms=cut,
                assessment_sha256=digest(asdict(observation)),
            )
            if mapping != expected_mapping:
                raise ValueError("unchecked proposal geometry differs from the fixed causal mapper")
            mapping_elapsed = timed.delay_ms
            mapped = mapping.candidate
            model_ready = max(ready, cost_ready)
            baseline_quote = None if baseline is None else entry_time(baseline, model_ready, mode)
            review_fresh = held_context_fresh(
                frame,
                model_ready if baseline_quote is None else baseline_quote,
                original_context=snapshot["context"],
            )
            if review_fresh:
                if directional_review(assessment, None if baseline is None else baseline.side) == "ALLOW":
                    add("context_review", baseline, model_ready)
                add("review_timing_control", baseline, model_ready)
            proposal_ready = max(ready + mapping_elapsed, cost_ready)
            proposal_quote = None if mapped is None else entry_time(mapped, proposal_ready, mode)
            if held_context_fresh(
                frame,
                proposal_ready if proposal_quote is None else proposal_quote,
                original_context=snapshot["context"],
            ):
                add("independent_proposals", mapped, proposal_ready)
            chosen, reason = arbitrate_combined(baseline, mapped, assessment)
            if decision.state == "CONFLICT":
                chosen, reason = None, "OPPOSITE_TECHNICAL_ABSTAIN_NO_RESURRECTION"
            combined_ready = proposal_ready
            combined_quote = None if chosen is None else entry_time(chosen, combined_ready, mode)
            if held_context_fresh(
                frame,
                combined_ready if combined_quote is None else combined_quote,
                original_context=snapshot["context"],
            ):
                add("combined", chosen, combined_ready)
            else:
                reason = "HELD_CONTEXT_STALE_OR_CHANGED"
        elif observation is not None and snapshot["sources_ready"] and decision.state != "UNAVAILABLE":
            # Error/budget denial is an abstention, not free success. The timing
            # control retains the underlying baseline at the observed failure clock.
            failure_ready = max(ready, cost_ready)
            failure_quote = None if baseline is None else entry_time(baseline, failure_ready, mode)
            if held_context_fresh(
                frame,
                failure_ready if failure_quote is None else failure_quote,
                original_context=snapshot["context"],
            ):
                add("review_timing_control", baseline, failure_ready)
        rows.append(
            {
                "cut_ms": cut,
                "symbol": symbol,
                "frame_id": snapshot["frame_id"],
                "prompt_sha256": snapshot["prompt_sha256"],
                "technical": asdict(decision),
                "sources_ready": snapshot["sources_ready"],
                "assessment_status": "MISSING" if observation is None else observation.status,
                "assessment_attempt_id": None if observation is None else observation.attempt_id,
                "assessment": None if assessment is None else assessment.model_dump(mode="json"),
                "actual_requested_ms": None if observation is None else observation.actual_requested_ms,
                "actual_observed_ms": None if observation is None else observation.actual_observed_ms,
                "actual_cost_observed_ms": None
                if observation is None
                else observation.actual_cost_observed_ms,
                "projected_assessment_ready_ms": ready,
                "projected_cost_ready_ms": cost_ready,
                "mapping_elapsed_ms": mapping_elapsed,
                "mapping": None if mapping is None else asdict(mapping),
                "timed_mapping": None
                if snapshot["frame_id"] not in by_mapping
                else asdict(by_mapping[snapshot["frame_id"]]),
                "combined_reason": reason,
            }
        )
    # Service expenses outside the horizon invalidate the whole model account,
    # never discard an expensive/late observation to improve a reported return.
    if any(not inputs.start_ms <= c.timestamp_ms < inputs.end_ms + 3 * 3_600_000 for c in costs):
        model_complete = False
    arms = {}
    for arm in ARMS:
        complete = baseline_complete and feed_complete and (arm == "strategy_only" or model_complete)
        report = account = None
        if complete:
            report, account = replay_tape(
                inputs,
                tapes[arm],
                scenario,
                mode,
                100,
                admission_policy=COMMON_COST_RISK,
                deadline=deadline,
                completion_times_ms=completions[arm],
                service_costs=tuple(feed_costs or ()) + (() if arm == "strategy_only" else tuple(costs)),
            )
        arms[arm] = {
            "status": "FIXTURE_ONLY"
            if complete and fixture_only
            else "SPARSE_RETROSPECTIVE_RECONSTRUCTION"
            if complete
            else "INCOMPLETE",
            "economic_results": report,
            "events": None if account is None else account.events,
            "trades": None if account is None else account.trades,
            "candidate_ids": [c.intent_id for group in tapes[arm].values() for c in group],
            "projected_model_charge_count": 0 if arm == "strategy_only" else len(costs),
            "account_model_cost_usd": 0.0
            if arm == "strategy_only"
            else None
            if unknown_cost or len(observations) != len(frames)
            else math.fsum(known_costs),
            "quote_unavailable_candidates": sum(
                entry_time(c, completions[arm][c.intent_id], mode) is None
                for group in tapes[arm].values()
                for c in group
            ),
        }
    return {
        "schema": "kairos.development.compact-context-reconstruction.v1",
        "protocol_sha256": protocol_sha256(),
        "scheduled_cells": len(roster),
        "scope": fixed_protocol()["scope"],
        "cells": rows,
        "arms": arms,
        "physical_known_model_spend_usd": math.fsum(known_costs),
        "physical_known_model_spend_is_lower_bound": bool(unknown_cost or len(observations) != len(frames)),
        "unknown_cost_attempts": unknown_cost,
        "physical_attempt_count": sum(o.status != "NOT_CALLED" for o in observations),
        "counterfactual_costs_are_not_additive_physical_spend": True,
        "model_roles_statistically_independent": False,
        "historical_model_observation": False,
        "training_contamination_excluded": False,
        "blind_campaign_credit_days": 0,
        **READINESS,
    }
