"""Separate 1m historical reconstruction bridge, never an observed native campaign.

Modern provider clocks stay modern. Only an explicit scenario projects latency
and recorded expense to a historical account. No provider/venue calls exist here.
"""

from __future__ import annotations

import math
import time
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from kairos_strategy.models import ExitPlan, SleeveIntent

from .engine import COMMON_COST_RISK, AccountCost, CostScenario, entry_time, replay_tape
from .historical_bars import ClosedHistoryPayload
from .historical_context import (
    HistoricalArchive,
    SourceRequirement,
    _clock,
    _json,
    _name,
    _sha,
    as_of_context,
    canonical,
    digest,
)
from .historical_inputs import validate_replay_inputs
from .inputs import UNIVERSE, WindowInputs

SCHEMA = "kairos.development.historical-review-reconstruction.v1"
PROJECTION_POLICY = "MODERN_RECORDED_COST_FIXED_SIMULATED_DELAY_V1"


def _validate_candidate(candidate: SleeveIntent) -> None:
    if not isinstance(candidate, SleeveIntent):
        raise ValueError("exact original SleeveIntent required, not a native contract conversion")
    rebuilt = SleeveIntent(
        **{
            **{k: v for k, v in asdict(candidate).items() if k != "intent_id"},
            "exit_plan": ExitPlan(**asdict(candidate.exit_plan)),
        }
    )
    if rebuilt != candidate:
        raise ValueError("unchecked candidate mutation detected")


@dataclass(frozen=True)
class HistoricalFrame:
    history: ClosedHistoryPayload
    archive: HistoricalArchive
    requirements: tuple[SourceRequirement, ...]
    knowledge_cut_ms: int
    state: str
    candidate: SleeveIntent | None
    strategy_code_sha256: str
    strategy_config_sha256: str

    def validate(self) -> None:
        self.history.validate()
        self.archive.validate()
        _clock(self.knowledge_cut_ms)
        _sha(self.strategy_code_sha256)
        _sha(self.strategy_config_sha256)
        if (
            self.history.symbol not in UNIVERSE
            or not (
                self.history.last_closed_ms <= self.knowledge_cut_ms < self.history.last_closed_ms + 60_000
            )
            or self.history.cutoff_ms != self.knowledge_cut_ms
        ):
            raise ValueError("explicit 1m closed anchor and later native context cut required")
        if self.state not in {"CANDIDATE", "QUIET", "UNAVAILABLE"}:
            raise ValueError("explicit candidate/quiet/unavailable state required")
        if (self.state == "CANDIDATE") != (self.candidate is not None):
            raise ValueError("candidate identity differs from strategy state")
        if self.candidate is not None:
            _validate_candidate(self.candidate)
            if (
                self.candidate.symbol != self.history.symbol
                or self.candidate.decision_ts_ms != self.history.last_closed_ms
            ):
                raise ValueError("candidate must preserve its original closed-anchor identity")
        view = as_of_context(self.archive, self.history.symbol, self.knowledge_cut_ms, self.requirements)
        if view["fixture_only"] != (self.history.provenance == "TEST_FIXTURE"):
            raise ValueError("bar/source fixture modes cannot be relabelled or mixed")

    def prompt_payload(self) -> dict[str, Any]:
        self.validate()
        view = as_of_context(self.archive, self.history.symbol, self.knowledge_cut_ms, self.requirements)
        # No episode labels, full tape/archive digests, future funding, capture
        # dates, ledgers or exit outcomes. Content is DATA, never instructions.
        candidate = (
            None
            if self.candidate is None
            else {
                "candidate_id": self.candidate.intent_id,
                "side": self.candidate.side.value,
                "reference_price": self.candidate.reference_price,
                "entry_eligible_ms": self.candidate.entry_eligible_ts_ms,
                "entry_expires_ms": self.candidate.entry_expires_ts_ms,
                "exit_plan": asdict(self.candidate.exit_plan),
            }
        )
        return {
            "schema": SCHEMA,
            "symbol": self.history.symbol,
            "closed_anchor_ms": self.history.last_closed_ms,
            "knowledge_cut_ms": self.knowledge_cut_ms,
            "strategy_state": self.state,
            "candidate": candidate,
            "closed_bars": self.history.prompt_payload(),
            "context": view["context"],
            "source_text_is_untrusted_data": True,
        }

    @property
    def frame_id(self) -> str:
        return digest(
            {
                "prompt": self.prompt_payload(),
                "strategy_code_sha256": self.strategy_code_sha256,
                "strategy_config_sha256": self.strategy_config_sha256,
            }
        )

    @property
    def prompt_sha256(self) -> str:
        return digest(self.prompt_payload())

    @property
    def sources_ready(self) -> bool:
        self.validate()
        return as_of_context(self.archive, self.history.symbol, self.knowledge_cut_ms, self.requirements)[
            "required_sources_ready"
        ]

    @property
    def materialized_ms(self) -> int:
        self.validate()
        view = as_of_context(self.archive, self.history.symbol, self.knowledge_cut_ms, self.requirements)
        return max(self.history.captured_at_ms, view["context_materialized_ms"], self.knowledge_cut_ms)


@dataclass(frozen=True)
class RetrospectiveReview:
    """Actual modern invocation, bound to exact historical prompt; not backdated."""

    frame_id: str
    prompt_sha256: str
    attempt_id: str
    model: str
    model_config_sha256: str
    actual_requested_ms: int
    actual_observed_ms: int
    actual_cost_observed_ms: int
    recorded_cost_usd: float | None
    status: str
    response_json: str | None
    raw_response_sha256: str | None
    no_call_reason: str | None = None
    evidence_kind: str = "MODERN_RETROSPECTIVE"
    provider: str = "OPENAI"

    def validate(self) -> None:
        for sha in (self.frame_id, self.prompt_sha256, self.model_config_sha256):
            _sha(sha)
        _name(self.attempt_id)
        _name(self.model)
        if self.provider != "OPENAI":
            raise ValueError("OpenAI-only retrospective review required")
        for clock in (self.actual_requested_ms, self.actual_observed_ms, self.actual_cost_observed_ms):
            _clock(clock)
        if not self.actual_requested_ms <= self.actual_observed_ms <= self.actual_cost_observed_ms:
            raise ValueError("actual modern response/cost clocks cannot be backdated")
        if self.evidence_kind not in {"MODERN_RETROSPECTIVE", "TEST_FIXTURE"}:
            raise ValueError("retrospective calls cannot become OBSERVED_POINT_IN_TIME")
        if self.recorded_cost_usd is not None and (
            type(self.recorded_cost_usd) not in {int, float}
            or not math.isfinite(self.recorded_cost_usd)
            or self.recorded_cost_usd < 0
        ):
            raise ValueError("known nonnegative actual cost or explicit unknown required")
        if self.status == "COMPLETE":
            _sha(self.raw_response_sha256)
            if type(self.response_json) is not str or len(self.response_json) > 1_024:
                raise ValueError("bounded parsed review response required")
            response = _json(self.response_json)
            if (
                type(response) is not dict
                or set(response) != {"decision"}
                or (
                    response["decision"] not in {"ALLOW", "VETO", "DEFER"}
                    or canonical(response) != self.response_json
                )
            ):
                raise ValueError("exact canonical ALLOW/VETO/DEFER response required")
            if self.no_call_reason is not None:
                raise ValueError("called response cannot claim a no-call reason")
        elif self.status in {"ERROR", "NOT_CALLED"}:
            if self.response_json is not None:
                raise ValueError("error/no-call cannot invent a model decision")
            if self.raw_response_sha256 is not None:
                _sha(self.raw_response_sha256)
            if self.status == "NOT_CALLED":
                if (
                    self.recorded_cost_usd != 0
                    or self.no_call_reason
                    not in {"BUDGET_DENIED", "REQUIRED_SOURCE_UNAVAILABLE", "SCHEDULED_POLICY_ABSTAIN"}
                    or self.raw_response_sha256 is not None
                ):
                    raise ValueError("explicit no-call reason and zero call expense required")
            elif self.no_call_reason is not None:
                raise ValueError("called failure cannot be a no-call")
        else:
            raise ValueError("explicit modern call disposition required")


def evaluate_historical_review(
    inputs: WindowInputs,
    frames: tuple[HistoricalFrame, ...],
    observations: tuple[RetrospectiveReview, ...],
    scenario: CostScenario,
    mode: str,
    *,
    simulated_delay_ms: int,
    baseline_delay_ms: int = 100,
    feed_costs: tuple[AccountCost, ...] | None = None,
    fixture_only: bool = False,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Complete 1m/five-symbol roster; reuse fixed common risk, no trade quota.

    This is conditional reconstructed economics even with real modern calls.
    Missing observations/costs null the whole review path. Original native
    campaign transport/receipt identities are not converted or altered.
    """
    _clock(simulated_delay_ms)
    _clock(baseline_delay_ms)
    if deadline is None:
        deadline = time.monotonic() + 900
    elif (
        type(deadline) not in {int, float}
        or not math.isfinite(deadline)
        or (not time.monotonic() < deadline <= time.monotonic() + 900)
    ):
        raise ValueError("finite bounded monotonic deadline required")
    if type(fixture_only) is not bool or type(frames) is not tuple or type(observations) is not tuple:
        raise ValueError("explicit immutable reconstruction mode/rosters required")
    validate_replay_inputs(inputs, fixture_only=fixture_only, deadline=deadline)
    if (
        type(inputs.start_ms) is not int
        or type(inputs.end_ms) is not int
        or inputs.start_ms <= 0
        or inputs.start_ms % 60_000
        or inputs.end_ms % 60_000
        or not 0 < inputs.end_ms - inputs.start_ms <= 14 * 86_400_000
        or not 0 < len(frames) <= 100_000
    ):
        raise ValueError("bounded complete episode interval required")
    expected = {(t - 1, s) for t in range(inputs.start_ms, inputs.end_ms, 60_000) for s in UNIVERSE}
    if (
        len(frames) != len(expected)
        or {(f.history.last_closed_ms, f.history.symbol) for f in frames} != expected
    ):
        raise ValueError("complete original 1m/five-symbol denominator required")
    by_id = {}
    source_bars = {symbol: {c.open_time_ms: c for c in inputs.bars[symbol]} for symbol in UNIVERSE}
    if any(len(source_bars[symbol]) != len(inputs.bars[symbol]) for symbol in UNIVERSE):
        raise ValueError("duplicate replay source bar")
    if len({(f.strategy_code_sha256, f.strategy_config_sha256) for f in frames}) != 1:
        raise ValueError("one immutable strategy source/configuration per episode account required")
    if len({f.requirements for f in frames}) != 1:
        raise ValueError("one fixed source requirements/TTL roster per episode account required")
    original_archive = frames[0].archive
    if len({f.candidate.sleeve_id for f in frames if f.candidate is not None}) > 1:
        raise ValueError("mixed strategy families require separate independent account runs")
    for frame in frames:
        if time.monotonic() >= deadline:
            raise TimeoutError("bounded historical validation time exceeded")
        if frame.archive is not original_archive and frame.archive != original_archive:
            raise ValueError("one full historical archive per episode account required")
        frame.validate()
        if (frame.history.provenance == "TEST_FIXTURE") != fixture_only:
            raise ValueError("fixture/real historical reconstruction mismatch")
        # Resolver prefix must equal actual replay bars, not an unrelated prompt.
        if any(source_bars[frame.history.symbol].get(c.open_time_ms) != c for c in frame.history.candles):
            raise ValueError("prompt bar prefix differs from replay source")
        if frame.frame_id in by_id:
            raise ValueError("duplicate historical frame")
        by_id[frame.frame_id] = frame
    index = {}
    attempt_ids = set()
    for observation in observations:
        observation.validate()
        frame = by_id.get(observation.frame_id)
        if (
            frame is None
            or observation.frame_id in index
            or observation.attempt_id in attempt_ids
            or observation.prompt_sha256 != frame.prompt_sha256
            or (observation.evidence_kind == "TEST_FIXTURE") != fixture_only
            or observation.actual_requested_ms < frame.materialized_ms
        ):
            raise ValueError("exact modern invocation/frame/clock binding required")
        if observation.status != "NOT_CALLED" and not frame.sources_ready:
            raise ValueError("required unavailable context must abstain before a model call")
        if observation.status == "NOT_CALLED" and (
            observation.no_call_reason == "REQUIRED_SOURCE_UNAVAILABLE" and frame.sources_ready
        ):
            raise ValueError("no-call source reason contradicts the actual context")
        index[observation.frame_id] = observation
        attempt_ids.add(observation.attempt_id)
    baseline, reviewed, timing, projected_costs = [], [], [], []
    missing, projection_rows = [], []
    for frame in frames:
        if time.monotonic() >= deadline:
            raise TimeoutError("bounded historical projection time exceeded")
        candidate = frame.candidate
        if candidate is not None:
            baseline.append((candidate, candidate.decision_ts_ms + baseline_delay_ms))
        observation = index.get(frame.frame_id)
        if observation is None:
            if candidate is not None:
                missing.append(frame.frame_id)
            continue
        ready = frame.knowledge_cut_ms + (0 if observation.status == "NOT_CALLED" else simulated_delay_ms)
        if observation.status != "NOT_CALLED" and not (
            inputs.start_ms <= ready < inputs.end_ms + 3 * 3_600_000
        ):
            raise ValueError("projected cost/completion outside retained account horizon")
        projection_rows.append(
            {
                "frame_id": frame.frame_id,
                "attempt_id": observation.attempt_id,
                "actual_requested_ms": observation.actual_requested_ms,
                "actual_observed_ms": observation.actual_observed_ms,
                "actual_cost_observed_ms": observation.actual_cost_observed_ms,
                "simulated_ready_ms": ready,
                "modern_recorded_cost_usd": observation.recorded_cost_usd,
                "status": observation.status,
            }
        )
        if observation.recorded_cost_usd is None:
            missing.append(frame.frame_id)
        elif observation.status != "NOT_CALLED":
            projected_costs.append(
                AccountCost(observation.attempt_id, ready, observation.recorded_cost_usd, "MODEL")
            )
        if candidate is None or observation.status == "NOT_CALLED":
            continue
        quote = entry_time(candidate, ready, mode)
        # Check source TTL at actual modeled quote, not just initial context.
        source_ready = quote is not None and frame.sources_ready
        # Never refresh context with later news. Even an explicitly empty source
        # view expires; it cannot remain fresh forever because it has no items.
        original = frame.prompt_payload()["context"]["sources"]
        source_ready = (
            source_ready
            and all(
                quote - frame.knowledge_cut_ms <= source["maximum_age_ms"]
                for source in original
                if source["required"] or source["state"] == "AVAILABLE"
            )
            and all(
                quote - item["available_ms"] <= source["maximum_age_ms"]
                for source in original
                if source["required"] or source["state"] == "AVAILABLE"
                for item in source["items"]
            )
        )
        if source_ready:
            timing.append((candidate, ready))
            if observation.status == "COMPLETE" and _json(observation.response_json)["decision"] == "ALLOW":
                reviewed.append((candidate, ready))
    if feed_costs is not None:
        if type(feed_costs) is not tuple or any(c.kind != "FEED" for c in feed_costs):
            raise ValueError("explicit immutable feed debits required")
        for cost in feed_costs:
            cost.__post_init__()
            if not inputs.start_ms <= cost.timestamp_ms < inputs.end_ms + 3 * 3_600_000:
                raise ValueError("feed liability outside retained horizon")
        if (
            len({c.cost_id for c in feed_costs}) != len(feed_costs)
            or {c.cost_id for c in feed_costs} & attempt_ids
        ):
            raise ValueError("duplicate/aliased feed debit identity")
    shared_feed = feed_costs or ()
    arms = {}
    for name, selected in (
        ("strategy_only", baseline),
        ("context_review", reviewed),
        ("review_timing_control", timing),
    ):
        complete = not any(f.state == "UNAVAILABLE" for f in frames) and (
            name == "strategy_only" or not missing
        )
        costs = shared_feed if name == "strategy_only" else (*shared_feed, *projected_costs)
        result, account = None, None
        if complete:
            tape: dict[int, list[SleeveIntent]] = {}
            clocks = {}
            for candidate, clock in selected:
                if candidate.intent_id in clocks:
                    raise ValueError("duplicate candidate across original historical slots")
                tape.setdefault(candidate.decision_ts_ms, []).append(candidate)
                clocks[candidate.intent_id] = clock
            result, account = replay_tape(
                inputs,
                tape,
                scenario,
                mode,
                baseline_delay_ms,
                service_costs=costs,
                completion_times_ms=clocks,
                admission_policy=COMMON_COST_RISK,
                deadline=deadline,
            )
        arms[name] = {
            "status": "FIXTURE_ONLY"
            if fixture_only and complete
            else "CONDITIONAL_RETROSPECTIVE"
            if complete
            else "INCOMPLETE",
            "economic_results": result,
            "missing_observation_or_cost_count": 0 if name == "strategy_only" else len(set(missing)),
            "complete_all_in_economics": False,
            "feed_costs_known": feed_costs is not None,
            "recorded_all_in_net_result": result if feed_costs is not None else None,
            "events": None if account is None else account.events,
            "trades": None if account is None else account.trades,
        }
    return {
        "schema": SCHEMA,
        "projection_policy": PROJECTION_POLICY,
        "projection_policy_sha256": digest(
            {
                "policy": PROJECTION_POLICY,
                "simulated_delay_ms": simulated_delay_ms,
                "baseline_delay_ms": baseline_delay_ms,
            }
        ),
        "scheduled_slots": len(frames),
        "slot_states": dict(Counter(f.state for f in frames)),
        "projections": projection_rows,
        "arms": arms,
        "known_modern_model_cost_usd": math.fsum(
            o.recorded_cost_usd for o in observations if o.recorded_cost_usd is not None
        ),
        "unknown_modern_model_cost_attempts": sum(o.recorded_cost_usd is None for o in observations),
        "actual_model_spend_is_separate_from_historical_account_debits": True,
        "historical_model_observation": False,
        "training_contamination_excluded": False,
        "source_authenticity_verified": False,
        "historical_execution_qualified": False,
        "native_campaign_transport_changed": False,
        "representative_sample": False,
        "blind_campaign_enrolled": False,
        "PAPER_QUALIFIED": False,
        "ALPHA_READY": False,
        "LIVE_READY": False,
        "STRATEGY_POLICY": "REJECT_ALL",
    }
