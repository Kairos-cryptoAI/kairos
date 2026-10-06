from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

import pytest
from kairos_core import (
    EvidenceReferenceV1,
    ResearchObservationWindowV1,
    canonical_json_bytes,
    canonical_sha256,
)
from kairos_core.contracts.llm_call_failure import LLMCallFailureV1
from kairos_core.contracts.llm_proposal import LLMProposalModelProvenanceV1, LLMTradeProposalV1
from kairos_core.contracts.llm_proposal_completion import LLMProposalCompletionReceiptV1
from kairos_core.contracts.strategy import (
    ExitPlanV1,
    StrategyIntentV1,
    StrategyProvenanceV1,
)
from kairos_core.enums import LLMProposalAction
from kairos_persistence.causal_campaign import (
    CampaignMarketContextV1,
    ResearchCausalPairReceiptV1,
    ResearchCausalStrategyEvaluationReceiptV1,
)
from kairos_persistence.research_campaign import (
    ResearchArmOutcomeV1,
    ResearchCampaignPlanV1,
    ResearchCaptureRequirementV1,
    ResearchCausalBundleV1,
    ResearchCostReceiptV1,
    ResearchReviewOutputV1,
    ResearchReviewReceiptV1,
)
from kairos_persistence.research_evidence import (
    ResearchLLMAttemptStartV1,
    ResearchLLMAttemptTerminalV1,
    ResearchSourceReceiptV1,
    ResearchStrategyEvaluationReceiptV1,
)

from adaptive_replay import observations


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


CAMPAIGN = "fixture-campaign"
SAMPLE = "fixture-sample"
SCHEDULE = _sha("schedule")
PROTOCOL = _sha("protocol")
DECISION = 120_000
DEADLINE = 130_000
ATTEMPT_REVIEW = "review-attempt-1"
ATTEMPT_PROPOSAL = "proposal-attempt-1"


def _plan(mode="OFFLINE_ENGINEERING_FIXTURE"):
    return ResearchCampaignPlanV1(
        campaign_id=CAMPAIGN,
        schedule_digest=SCHEDULE,
        candidate_protocol_digest=PROTOCOL,
        recording_mode=mode,
        scheduler_sha256=_sha("scheduler"),
        required_sources=(
            ResearchCaptureRequirementV1(source_kind="MACRO", source_name="macro-1", maximum_age_ms=50_000),
            ResearchCaptureRequirementV1(
                source_kind="MARKET_SNAPSHOT", source_name="market-1", maximum_age_ms=50_000
            ),
            ResearchCaptureRequirementV1(source_kind="NEWS", source_name="news-1", maximum_age_ms=50_000),
        ),
        maximum_windows_per_tick=1,
        maximum_clock_skew_ms=2_000,
        maximum_call_seconds=5,
    )


def _window():
    return ResearchObservationWindowV1(
        sample_id=SAMPLE,
        symbol="BTCUSDT",
        timeframe="1m",
        market_as_of_ts_ms=DECISION,
        market_snapshot_sha256=None,
        paired_at_ts_ms=DECISION + 200,
        sample_deadline_ts_ms=DEADLINE,
    )


def _source(kind, name):
    as_of, observed = DECISION - 2_000, DECISION - 1_000
    if kind == "MARKET_SNAPSHOT":
        as_of = observed = DECISION - 1
        from datetime import datetime

        from kairos_core import ClosedBarEventV1, MarketSnapshot
        from kairos_core.contracts.market import DerivativesMetrics, OrderBookSummary, TechnicalIndicators

        bar = ClosedBarEventV1(
            source="fixture",
            symbol="BTCUSDT",
            timeframe="1m",
            open_time_ms=60_000,
            close_time_ms=119_999,
            open=100,
            high=101,
            low=99,
            close=100,
            base_volume=1,
            quote_volume=100,
            taker_buy_base_volume=0.5,
            taker_buy_quote_volume=50,
        )
        snapshot = MarketSnapshot(
            source="fixture",
            message_id="fixture-market-1",
            produced_at=datetime.fromtimestamp(observed / 1000, UTC),
            symbol="BTCUSDT",
            timeframe="1m",
            mid_price=100,
            volume_usd=100,
            order_book=OrderBookSummary(
                best_bid=99.9, best_ask=100.1, spread_bps=20, imbalance=0, depth_usd=1000
            ),
            derivatives=DerivativesMetrics(funding_rate=0, open_interest=100),
            indicators=TechnicalIndicators(rsi_14=50, macd=0, macd_signal=0, macd_hist=0),
        )
        content = CampaignMarketContextV1(
            anchor_bar=bar,
            market_snapshot=snapshot,
            bar_window_reference="fixture-window",
            bar_window_sha256=_sha("bar-window"),
            bar_count=2,
            first_open_time_ms=0,
        ).model_dump(mode="json")
    else:
        content = {"contract_version": f"fixture-{kind.lower()}-v1", "value": kind.lower()}
    return ResearchSourceReceiptV1(
        campaign_id=CAMPAIGN,
        sample_id=SAMPLE,
        schedule_digest=SCHEDULE,
        candidate_protocol_digest=PROTOCOL,
        source_kind=kind,
        source_name=name,
        reference="fixture-market-1" if kind == "MARKET_SNAPSHOT" else f"source:{name}",
        source_as_of_ts_ms=as_of,
        observed_at_ts_ms=observed,
        content=content,
    )


def _source_roster():
    return tuple(
        sorted(
            (
                _source("MARKET_SNAPSHOT", "market-1"),
                _source("NEWS", "news-1"),
                _source("MACRO", "macro-1"),
            ),
            key=lambda x: x.receipt_sha256,
        )
    )


def _intent(anchor_sha):
    anchor = 119_999
    return StrategyIntentV1(
        source="kairos-strategy-engine",
        strategy_id="offline-fixture",
        strategy_revision="v1",
        symbol="BTCUSDT",
        side="LONG",
        decision_ts_ms=anchor,
        entry_eligible_ts_ms=120_000,
        entry_expires_ts_ms=180_000,
        reference_price=100,
        signal_strength=0.5,
        gross_reward_bps=100,
        exit_plan=ExitPlanV1(stop_price=99, target_price=101, max_holding_ms=60_000),
        provenance=StrategyProvenanceV1(
            strategy_code_sha256=_sha("code"),
            config_sha256=_sha("config"),
            input_window_sha256=_sha("bar-window"),
            features_sha256=_sha("features"),
            input_bar_sha256s=(_sha("prior-bar"), anchor_sha),
        ),
    )


def _bundle(plan, window, sources):
    market = next(s for s in sources if s.source_kind == "MARKET_SNAPSHOT")
    return ResearchCausalBundleV1(
        campaign_id=CAMPAIGN,
        sample_id=SAMPLE,
        claim_id=canonical_sha256(
            {"plan_receipt_sha256": plan.receipt_sha256, "sample_id": window.sample_id}
        ),
        market_snapshot_sha256=market.content_sha256,
        source_receipt_sha256s=tuple(sorted(s.receipt_sha256 for s in sources)),
        frozen_at_ts_ms=DECISION + 1,
    )


def _evaluation(plan, window, sources, *, with_intent=False):
    market = next(s for s in sources if s.source_kind == "MARKET_SNAPSHOT")
    context = CampaignMarketContextV1.model_validate(market.content)
    return ResearchCausalStrategyEvaluationReceiptV1(
        campaign_id=CAMPAIGN,
        sample_id=SAMPLE,
        schedule_digest=plan.schedule_digest,
        candidate_protocol_digest=plan.candidate_protocol_digest,
        strategy_id="offline-fixture",
        strategy_revision="v1",
        symbol=window.symbol,
        timeframe="1m",
        evidence_as_of_ts_ms=window.market_as_of_ts_ms,
        evaluated_at_ts_ms=window.market_as_of_ts_ms + 10,
        market_snapshot_sha256=market.content_sha256,
        evaluator_sha256=_sha("evaluator"),
        source_receipt_sha256s=tuple(sorted(s.receipt_sha256 for s in sources)),
        context_source_receipt_sha256=market.receipt_sha256,
        anchor_bar_sha256=context.anchor_bar.bar_sha256,
        anchor_bar_close_ts_ms=context.anchor_bar.close_time_ms,
        bar_window_sha256=context.bar_window_sha256,
        bar_count=context.bar_count,
        intent=_intent(context.anchor_bar.bar_sha256) if with_intent else None,
    )


def _start(plan, window, bundle, arm, attempt):
    market = bundle.market_snapshot_sha256
    return ResearchLLMAttemptStartV1(
        attempt_id=attempt,
        campaign_id=CAMPAIGN,
        arm_id=arm,
        sample_id=SAMPLE,
        schedule_digest=plan.schedule_digest,
        candidate_protocol_digest=plan.candidate_protocol_digest,
        arm_protocol_digest=_sha(f"arm:{arm}"),
        symbol=window.symbol,
        timeframe=window.timeframe,
        market_as_of_ts_ms=window.market_as_of_ts_ms,
        market_snapshot_sha256=market,
        sample_deadline_ts_ms=window.sample_deadline_ts_ms,
        provider="openai",
        requested_model="fixture-model",
        prompt_sha256=_sha(f"prompt:{arm}"),
        budget_reservation_id=attempt,
        attempt_started_at_ts_ms=window.market_as_of_ts_ms + 20,
    )


def _proposal(start, sources):
    source = next(s for s in sources if s.source_kind == "NEWS")
    evidence = EvidenceReferenceV1(
        kind=source.source_kind,
        reference=source.reference,
        content_sha256=source.content_sha256,
        observed_at_ms=source.observed_at_ts_ms,
    )
    provenance = LLMProposalModelProvenanceV1(
        provider="openai",
        requested_model="fixture-model",
        resolved_model="fixture-model",
        request_id="request-1",
        prompt_sha256=start.prompt_sha256,
        response_sha256=_sha("proposal-response"),
        budget_reservation_id=start.budget_reservation_id,
        latency_ms=100,
        cost_usd=0.000004,
    )
    proposal = LLMTradeProposalV1(
        campaign_id=CAMPAIGN,
        arm_id=start.arm_id,
        sample_id=SAMPLE,
        symbol=start.symbol,
        timeframe=start.timeframe,
        market_as_of_ts_ms=start.market_as_of_ts_ms,
        expires_at_ts_ms=DEADLINE,
        market_snapshot_sha256=start.market_snapshot_sha256,
        action=LLMProposalAction.LONG_BIAS,
        rationale="fixture proposal",
        evidence=(evidence,),
        model_provenance=provenance,
    )
    completion = LLMProposalCompletionReceiptV1(
        campaign_id=CAMPAIGN,
        arm_id=start.arm_id,
        sample_id=SAMPLE,
        symbol=start.symbol,
        timeframe=start.timeframe,
        market_as_of_ts_ms=start.market_as_of_ts_ms,
        market_snapshot_sha256=start.market_snapshot_sha256,
        sample_deadline_ts_ms=start.sample_deadline_ts_ms,
        attempt_id=start.attempt_id,
        proposal_id=proposal.proposal_id,
        model_provenance=provenance,
        attempt_started_at_ts_ms=start.attempt_started_at_ts_ms,
        response_observed_at_ts_ms=start.attempt_started_at_ts_ms + 100,
    )
    terminal = ResearchLLMAttemptTerminalV1(
        attempt_id=start.attempt_id,
        start_receipt_sha256=start.receipt_sha256,
        terminal_status="COMPLETED",
        observed_at_ts_ms=completion.response_observed_at_ts_ms,
        proposal=proposal,
        completion=completion,
    )
    return proposal, completion, terminal


def _review(plan, window, bundle, evaluation, start, sources):
    news = next(s for s in sources if s.source_kind == "NEWS")
    evidence = EvidenceReferenceV1(
        kind=news.source_kind,
        reference=news.reference,
        content_sha256=news.content_sha256,
        observed_at_ms=news.observed_at_ts_ms,
    )
    return ResearchReviewReceiptV1(
        campaign_id=CAMPAIGN,
        sample_id=SAMPLE,
        attempt_id=start.attempt_id,
        start_receipt_sha256=start.receipt_sha256,
        bundle_receipt_sha256=bundle.receipt_sha256,
        evaluation_receipt_sha256=evaluation.receipt_sha256,
        output=ResearchReviewOutputV1(
            action="ALLOW",
            rationale="fixture review",
            evidence_ids=(canonical_sha256(evidence),),
        ),
        response_sha256=_sha("review-response"),
        requested_model=start.requested_model,
        resolved_model=start.requested_model,
        request_id="review-request-1",
        prompt_sha256=start.prompt_sha256,
        observed_at_ts_ms=start.attempt_started_at_ts_ms + 80,
    )


def _cost(plan, window, arm, attempt, stage, amount, clock):
    return ResearchCostReceiptV1(
        campaign_id=CAMPAIGN,
        sample_id=SAMPLE,
        arm_id=arm,
        attempt_id=attempt,
        stage=stage,
        amount_microusd=amount,
        observed_at_ts_ms=clock,
    )


def _pair(fixture, start, terminal, proposal, completion, *, paired_at=None):
    return ResearchCausalPairReceiptV1(
        campaign_id=CAMPAIGN,
        sample_id=SAMPLE,
        schedule_digest=fixture.plan.schedule_digest,
        candidate_protocol_digest=fixture.plan.candidate_protocol_digest,
        arm_protocol_digest=start.arm_protocol_digest,
        bundle_receipt_sha256=fixture.bundle.receipt_sha256,
        evaluation_receipt_sha256=fixture.evaluation.receipt_sha256,
        source_receipt_sha256s=fixture.bundle.source_receipt_sha256s,
        market_snapshot_sha256=fixture.bundle.market_snapshot_sha256,
        anchor_bar_sha256=fixture.evaluation.anchor_bar_sha256,
        bar_window_sha256=fixture.evaluation.bar_window_sha256,
        bar_count=fixture.evaluation.bar_count,
        market_as_of_ts_ms=fixture.window.market_as_of_ts_ms,
        paired_at_ts_ms=paired_at or fixture.window.paired_at_ts_ms,
        attempt_id=start.attempt_id,
        start_receipt_sha256=start.receipt_sha256,
        terminal_receipt_sha256=terminal.receipt_sha256,
        completion_receipt_id=completion.completion_receipt_id,
        proposal_id=proposal.proposal_id,
        strategy_outcome=fixture.evaluation.intent.side.value if fixture.evaluation.intent else "NO_INTENT",
        strategy_intent_id=fixture.evaluation.intent.intent_id if fixture.evaluation.intent else None,
        llm_outcome=proposal.action.value,
    )


def _replace_state(fixture, *receipts):
    rows = dict(fixture.state)
    rows.update(receipts)
    return observations.snapshot_window(fixture.plan, fixture.window, rows, fixture_only=True)


@dataclass(frozen=True)
class Fixture:
    plan: ResearchCampaignPlanV1
    window: ResearchObservationWindowV1
    state: dict
    sources: tuple
    bundle: ResearchCausalBundleV1
    evaluation: ResearchCausalStrategyEvaluationReceiptV1

    def snapshot(self, **kwargs):
        return observations.snapshot_window(self.plan, self.window, self.state, fixture_only=True, **kwargs)


def _fixture(*, candidate=False, with_calls=True, committed=True, complete_outcomes=False):
    plan, window = _plan(), _window()
    sources = _source_roster()
    bundle = _bundle(plan, window, sources)
    evaluation = _evaluation(plan, window, sources, with_intent=candidate)
    rows = {("source", "all", f"{s.source_kind}:{s.source_name}"): s for s in sources}
    rows[("bundle", "all", "one")] = bundle
    rows[("evaluation", "all", "one")] = evaluation
    if with_calls:
        review_start = _start(plan, window, bundle, "strategy-review", ATTEMPT_REVIEW)
        proposal_start = _start(plan, window, bundle, "llm-proposal-research", ATTEMPT_PROPOSAL)
        rows[("start", review_start.arm_id, review_start.attempt_id)] = review_start
        rows[("start", proposal_start.arm_id, proposal_start.attempt_id)] = proposal_start
        if candidate:
            review = _review(plan, window, bundle, evaluation, review_start, sources)
            rows[("review", review_start.arm_id, review_start.attempt_id)] = review
        _, _, terminal = _proposal(proposal_start, sources)
        rows[("terminal", proposal_start.arm_id, proposal_start.attempt_id)] = terminal
        for start in (review_start, proposal_start):
            stages = [
                ("RESERVATION_REQUESTED", 9, start.attempt_started_at_ts_ms - 2),
                ("RESERVED", 9, start.attempt_started_at_ts_ms - 1),
            ]
            if committed:
                stages.extend(
                    [
                        ("COMMIT_REQUESTED", 4, start.attempt_started_at_ts_ms + 110),
                        ("COMMITTED", 4, start.attempt_started_at_ts_ms + 120),
                    ]
                )
            for stage, amount, clock in stages:
                receipt = _cost(plan, window, start.arm_id, start.attempt_id, stage, amount, clock)
                rows[("cost", start.arm_id, f"{stage}:{start.attempt_id}")] = receipt
    if complete_outcomes:
        starts = {r.arm_id: r for (kind, _, _), r in rows.items() if kind == "start"}
        decisions = {r.attempt_id: r for (kind, _, _), r in rows.items() if kind in {"review", "terminal"}}
        statuses = {
            "strategy-only": "BASELINE" if candidate else "NO_INTENT",
            "strategy-review": "ALLOW" if candidate else "NO_INTENT",
            "llm-proposal-research": "PROPOSAL" if candidate else "MISSED",
        }
        for arm, status in statuses.items():
            start = starts.get(arm)
            decision = decisions.get(start.attempt_id) if start else None
            outcome = ResearchArmOutcomeV1(
                campaign_id=CAMPAIGN,
                sample_id=SAMPLE,
                arm_id=arm,
                claim_id=bundle.claim_id,
                status=status,
                bundle_receipt_sha256=bundle.receipt_sha256,
                evaluation_receipt_sha256=evaluation.receipt_sha256,
                attempt_id=start.attempt_id if start else None,
                decision_receipt_sha256=decision.receipt_sha256 if decision else None,
                observed_at_ts_ms=window.paired_at_ts_ms,
            )
            rows[("outcome", arm, "one")] = outcome
    return Fixture(plan, window, rows, sources, bundle, evaluation)


def _canonical_document(fixture):
    return json.loads(fixture.snapshot().canonical_json)


def test_quiet_native_baseline_bundle_and_source_roster_roundtrip():
    fixture = _fixture(with_calls=False)
    snapshot = fixture.snapshot()
    plan, window, decoded = snapshot.decoded()
    assert plan == fixture.plan
    assert window == fixture.window
    assert decoded[("evaluation", "all", "one")].intent is None
    assert len([k for k in decoded if k[0] == "source"]) == 3
    info = snapshot.inspection()
    assert info["baseline_state"] == "QUIET"
    assert info["economics_ready"] is False
    assert info["strategy_policy"] == "REJECT_ALL"


def test_candidate_review_and_proposal_completion_native_linkage_roundtrips():
    fixture = _fixture(candidate=True)
    snapshot = fixture.snapshot()
    _, _, decoded = snapshot.decoded()
    assert decoded[("evaluation", "all", "one")].intent.intent_id == fixture.evaluation.intent.intent_id
    review = decoded[("review", "strategy-review", ATTEMPT_REVIEW)]
    assert review.output.action == "ALLOW"
    terminal = decoded[("terminal", "llm-proposal-research", ATTEMPT_PROPOSAL)]
    assert terminal.completion.response_observed_at_ts_ms == terminal.observed_at_ts_ms
    assert terminal.proposal.proposal_id == terminal.completion.proposal_id


def test_native_causal_pair_roundtrip_and_forged_terminal_link_rejected():
    fixture = _fixture(candidate=True)
    start = fixture.state[("start", "llm-proposal-research", ATTEMPT_PROPOSAL)]
    proposal, completion, terminal = _proposal(start, fixture.sources)
    pair = _pair(fixture, start, terminal, proposal, completion)
    valid = _replace_state(
        fixture,
        (("sample", "llm-proposal-research", "one"), pair),
    )
    assert valid.decoded()[2][("sample", "llm-proposal-research", "one")] == pair
    forged = ResearchCausalPairReceiptV1.model_validate(
        {
            **pair.model_dump(mode="json"),
            "terminal_receipt_sha256": _sha("foreign-terminal"),
            "receipt_sha256": None,
        }
    )
    with pytest.raises(ValueError, match="pair"):
        _replace_state(fixture, (("sample", "llm-proposal-research", "one"), forged))


def test_duplicate_start_per_arm_and_cost_only_cross_arm_alias_are_rejected():
    fixture = _fixture(candidate=True)
    duplicate = _start(fixture.plan, fixture.window, fixture.bundle, "strategy-review", "review-attempt-2")
    with pytest.raises(ValueError, match="START fence"):
        _replace_state(fixture, (("start", "strategy-review", duplicate.attempt_id), duplicate))
    alias = _cost(
        fixture.plan, fixture.window, "strategy-review", ATTEMPT_PROPOSAL, "RESERVED", 9, DECISION + 19
    )
    with pytest.raises(ValueError, match="identity reused"):
        _replace_state(fixture, (("cost", "strategy-review", f"RESERVED:{ATTEMPT_PROPOSAL}"), alias))


def test_market_context_and_review_terminal_cannot_be_repointed():
    fixture = _fixture(candidate=True)
    payload = fixture.evaluation.model_dump(mode="json")
    news = next(s for s in fixture.sources if s.source_kind == "NEWS")
    payload["context_source_receipt_sha256"] = news.receipt_sha256
    forged = ResearchCausalStrategyEvaluationReceiptV1.model_validate({**payload, "receipt_sha256": None})
    rows = dict(fixture.state)
    rows.pop(("review", "strategy-review", ATTEMPT_REVIEW))
    rows[("evaluation", "all", "one")] = forged
    with pytest.raises(ValueError, match="evaluation differs"):
        observations.snapshot_window(fixture.plan, fixture.window, rows, fixture_only=True)

    review_start = fixture.state[("start", "strategy-review", ATTEMPT_REVIEW)]
    proposal, completion, terminal = _proposal(review_start, fixture.sources)
    rows = dict(fixture.state)
    rows.pop(("review", "strategy-review", ATTEMPT_REVIEW))
    rows[("terminal", "strategy-review", ATTEMPT_REVIEW)] = terminal
    with pytest.raises(ValueError, match="review cannot complete"):
        observations.snapshot_window(fixture.plan, fixture.window, rows, fixture_only=True)


@pytest.mark.parametrize("forgery", ["allow", "attempt", "pair"])
def test_outcome_cannot_invent_review_attempt_or_causal_pair(forgery):
    fixture = _fixture(candidate=False)
    if forgery == "allow":
        outcome = ResearchArmOutcomeV1(
            campaign_id=CAMPAIGN,
            sample_id=SAMPLE,
            arm_id="strategy-review",
            claim_id=fixture.bundle.claim_id,
            status="ALLOW",
            bundle_receipt_sha256=fixture.bundle.receipt_sha256,
            evaluation_receipt_sha256=fixture.evaluation.receipt_sha256,
            attempt_id=ATTEMPT_REVIEW,
            observed_at_ts_ms=fixture.window.paired_at_ts_ms,
        )
    elif forgery == "attempt":
        outcome = ResearchArmOutcomeV1(
            campaign_id=CAMPAIGN,
            sample_id=SAMPLE,
            arm_id="strategy-review",
            claim_id=fixture.bundle.claim_id,
            status="UNKNOWN",
            bundle_receipt_sha256=fixture.bundle.receipt_sha256,
            evaluation_receipt_sha256=fixture.evaluation.receipt_sha256,
            attempt_id="invented-attempt",
            observed_at_ts_ms=fixture.window.paired_at_ts_ms,
        )
    else:
        outcome = ResearchArmOutcomeV1(
            campaign_id=CAMPAIGN,
            sample_id=SAMPLE,
            arm_id="llm-proposal-research",
            claim_id=fixture.bundle.claim_id,
            status="PROPOSAL",
            bundle_receipt_sha256=fixture.bundle.receipt_sha256,
            evaluation_receipt_sha256=fixture.evaluation.receipt_sha256,
            attempt_id=ATTEMPT_PROPOSAL,
            decision_receipt_sha256=fixture.state[
                ("terminal", "llm-proposal-research", ATTEMPT_PROPOSAL)
            ].receipt_sha256,
            causal_sample_receipt_sha256=_sha("invented-pair"),
            observed_at_ts_ms=fixture.window.paired_at_ts_ms,
        )
    with pytest.raises(ValueError, match="outcome"):
        _replace_state(fixture, (("outcome", outcome.arm_id, "one"), outcome))


def test_observed_unknown_outcome_stays_unlinked_when_terminal_arrives_late():
    fixture = _fixture(candidate=True)
    start = fixture.state[("start", "llm-proposal-research", ATTEMPT_PROPOSAL)]
    terminal = fixture.state[("terminal", "llm-proposal-research", ATTEMPT_PROPOSAL)]
    outcome = ResearchArmOutcomeV1(
        campaign_id=CAMPAIGN,
        sample_id=SAMPLE,
        arm_id="llm-proposal-research",
        claim_id=fixture.bundle.claim_id,
        status="UNKNOWN",
        bundle_receipt_sha256=fixture.bundle.receipt_sha256,
        evaluation_receipt_sha256=fixture.evaluation.receipt_sha256,
        attempt_id=start.attempt_id,
        decision_receipt_sha256=None,
        observed_at_ts_ms=fixture.window.paired_at_ts_ms,
    )
    # Native terminal's provider completion is after the captured outcome clock.
    payload = terminal.model_dump(mode="json")
    payload["completion"]["response_observed_at_ts_ms"] = fixture.window.paired_at_ts_ms + 1
    payload["completion"]["completion_receipt_id"] = None
    from kairos_core.contracts.llm_proposal_completion import LLMProposalCompletionReceiptV1

    payload["completion"] = LLMProposalCompletionReceiptV1.model_validate(payload["completion"]).model_dump(
        mode="json"
    )
    payload["observed_at_ts_ms"] = fixture.window.paired_at_ts_ms + 1
    late = ResearchLLMAttemptTerminalV1.model_validate({**payload, "receipt_sha256": None})
    snapshot = _replace_state(
        fixture,
        (("terminal", "llm-proposal-research", ATTEMPT_PROPOSAL), late),
        (("outcome", outcome.arm_id, "one"), outcome),
    )
    assert snapshot.decoded()[2][("outcome", "llm-proposal-research", "one")].decision_receipt_sha256 is None


def test_historical_source_missing_without_inputs_stays_unlinked_after_later_capture():
    fixture = _fixture(candidate=True)
    missing = ResearchArmOutcomeV1(
        campaign_id=CAMPAIGN,
        sample_id=SAMPLE,
        arm_id="strategy-review",
        claim_id=fixture.bundle.claim_id,
        status="SOURCE_MISSING",
        observed_at_ts_ms=DECISION + 15,
    )
    key = ("outcome", "strategy-review", "one")
    first = observations.snapshot_window(fixture.plan, fixture.window, {key: missing}, fixture_only=True)
    later_rows = dict(fixture.state)
    later_rows[key] = missing
    later = observations.snapshot_window(fixture.plan, fixture.window, later_rows, fixture_only=True)
    retained = later.decoded()[2][key]
    assert retained.status == "SOURCE_MISSING"
    assert retained.bundle_receipt_sha256 is None
    assert retained.evaluation_receipt_sha256 is None
    assert retained.attempt_id is None
    assert first.inspection()["total_model_cost_microusd"] is None
    assert later.inspection()["total_model_cost_microusd"] is None


@pytest.mark.parametrize("bad_json", [b'{"x":NaN}', b'{ "schema": "x" }'])
def test_nonfinite_and_noncanonical_transport_are_rejected(bad_json):
    with pytest.raises(ValueError):
        observations.NativeWindowSnapshot(bad_json.decode(), fixture_only=True)


def test_oversized_transport_and_cost_without_commit_remains_unknown():
    with pytest.raises(ValueError, match="bounded bytes"):
        observations.NativeWindowSnapshot(" " * (observations.MAX_BYTES + 1), fixture_only=True)
    info = _fixture(with_calls=True, committed=False).snapshot().inspection()
    assert info["total_model_cost_microusd"] is None
    assert info["unresolved_cost_attempt_count"] == 2


def test_inspection_distinguishes_committed_cost_from_reserved_unknown():
    fixture = _fixture(candidate=True, committed=True, complete_outcomes=True)
    info = fixture.snapshot().inspection()
    assert info["known_committed_model_cost_microusd"] == 8
    assert info["total_model_cost_microusd"] == 8
    assert info["unresolved_cost_attempt_count"] == 0


def test_missing_and_empty_cost_ledgers_remain_explicit_unknown_or_zero():
    fixture = _fixture(with_calls=False)
    assert fixture.snapshot().inspection()["total_model_cost_microusd"] is None
    called_without_cost = _fixture(with_calls=True, committed=False)
    info = called_without_cost.snapshot().inspection()
    assert info["known_committed_model_cost_microusd"] == 0
    assert info["total_model_cost_microusd"] is None
    assert info["unresolved_cost_attempt_count"] == 2


def test_decoded_models_and_inspection_are_fresh_mutation_independent():
    fixture = _fixture(candidate=True)
    snapshot = fixture.snapshot()
    _, _, first = snapshot.decoded()
    source = first[("source", "all", "NEWS:news-1")]
    source.content["value"] = "mutated"
    first.clear()
    info = snapshot.inspection()
    info["receipt_counts"].clear()
    _, _, second = snapshot.decoded()
    assert second[("source", "all", "NEWS:news-1")].content["value"] == "news"
    assert len(second) == len(fixture.state)
    assert snapshot.inspection()["receipt_counts"]["source"] == 3


def test_write_is_create_only_and_read_requires_independent_exact_digest(tmp_path: Path):
    snapshot = _fixture(candidate=True).snapshot()
    path = tmp_path / "observations.json"
    assert observations.write_snapshot(path, snapshot) == snapshot.sha256
    loaded = observations.read_snapshot(path, expected_sha256=snapshot.sha256, fixture_only=True)
    assert loaded.canonical_json == snapshot.canonical_json
    with pytest.raises(FileExistsError):
        observations.write_snapshot(path, snapshot)
    with pytest.raises(ValueError, match="checksum"):
        observations.read_snapshot(path, expected_sha256=_sha("wrong"), fixture_only=True)
    with pytest.raises(ValueError, match="independently supplied"):
        observations.read_snapshot(path, expected_sha256="NOT-A-SHA", fixture_only=True)


def test_file_mode_rejects_observed_flag_and_accepts_explicit_fixture_flag(tmp_path: Path):
    fixture = _fixture()
    snapshot = fixture.snapshot()
    path = tmp_path / "snapshot.json"
    observations.write_snapshot(path, snapshot)
    with pytest.raises(ValueError, match="fixture/observation mode"):
        observations.read_snapshot(path, expected_sha256=snapshot.sha256, fixture_only=False)
    assert observations.read_snapshot(path, expected_sha256=snapshot.sha256, fixture_only=True) == snapshot


def test_canonical_json_and_duplicate_object_fields_are_required(tmp_path: Path):
    path = tmp_path / "duplicate.json"
    raw = b'{"schema":"one","schema":"two","plan":{},"window":{},"receipts":[]}'
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="invalid bounded observation JSON"):
        observations.read_snapshot(path, expected_sha256=hashlib.sha256(raw).hexdigest(), fixture_only=True)


@pytest.mark.parametrize("tamper", ["scope", "extra", "duplicate-key", "old-evaluator-family"])
def test_native_receipt_scope_shape_identity_and_family_are_closed_world(tmp_path: Path, tamper):
    fixture = _fixture(with_calls=False)
    doc = _canonical_document(fixture)
    if tamper == "scope":
        doc["receipts"][0]["payload"]["campaign_id"] = "foreign-campaign"
    elif tamper == "extra":
        doc["receipts"][0]["payload"]["unexpected"] = "not-ignored"
    elif tamper == "duplicate-key":
        doc["receipts"].append(doc["receipts"][0])
    else:
        old = ResearchStrategyEvaluationReceiptV1(
            campaign_id=CAMPAIGN,
            sample_id=SAMPLE,
            schedule_digest=SCHEDULE,
            candidate_protocol_digest=PROTOCOL,
            strategy_id="offline-fixture",
            strategy_revision="v1",
            symbol="BTCUSDT",
            timeframe="1m",
            evidence_as_of_ts_ms=DECISION,
            evaluated_at_ts_ms=DECISION + 1,
            market_snapshot_sha256=fixture.bundle.market_snapshot_sha256,
            evaluator_sha256=_sha("evaluator"),
            source_receipt_sha256s=fixture.bundle.source_receipt_sha256s,
            intent=None,
        )
        doc["receipts"][-1] = {"key": ["evaluation", "all", "one"], "payload": old.model_dump(mode="json")}
    path = tmp_path / f"{tamper}.json"
    raw = canonical_json_bytes(doc)
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        observations.read_snapshot(path, expected_sha256=hashlib.sha256(raw).hexdigest(), fixture_only=True)


def test_noncanonical_receipt_order_and_foreign_plan_window_are_rejected():
    fixture = _fixture(with_calls=False)
    doc = _canonical_document(fixture)
    doc["receipts"].reverse()
    raw = canonical_json_bytes(doc)
    # Decode rejects the order regardless of a correctly recomputed outer digest.
    with pytest.raises(ValueError, match="deterministic ordering"):
        observations.NativeWindowSnapshot(raw.decode(), fixture_only=True)
    foreign = ResearchObservationWindowV1.model_validate(
        {**fixture.window.model_dump(mode="json"), "sample_id": "foreign-sample"}
    )
    with pytest.raises(ValueError, match="import scope"):
        observations.snapshot_window(fixture.plan, foreign, fixture.state, fixture_only=True)


def test_capture_uses_one_injected_reader_call_and_never_needs_provider_or_writer():
    fixture = _fixture(candidate=True)

    class Reader:
        def __init__(self):
            self.calls = []

        async def window_state(self, campaign_id, sample_id):
            self.calls.append((campaign_id, sample_id))
            return fixture.state

    reader = Reader()
    captured = asyncio.run(
        observations.capture_window(reader, plan=fixture.plan, window=fixture.window, fixture_only=True)
    )
    assert reader.calls == [(CAMPAIGN, SAMPLE)]
    assert captured.sha256 == fixture.snapshot().sha256


def test_capture_rejects_foreign_returned_receipts_after_one_scoped_reader_call():
    fixture = _fixture()

    class Reader:
        calls = 0

        async def window_state(self, campaign_id, sample_id):
            self.calls += 1
            return fixture.state

    reader = Reader()
    foreign = ResearchObservationWindowV1.model_validate(
        {**fixture.window.model_dump(mode="json"), "sample_id": "other-sample"}
    )
    with pytest.raises(ValueError, match="import scope"):
        asyncio.run(observations.capture_window(reader, plan=fixture.plan, window=foreign, fixture_only=True))
    assert reader.calls == 1


def test_receipt_and_roster_bounds_reject_before_snapshot_creation():
    fixture = _fixture(with_calls=False)
    with pytest.raises(ValueError, match="bounded native window"):
        observations.snapshot_window(
            fixture.plan,
            fixture.window,
            {**fixture.state, **{("bad", "a", str(i)): object() for i in range(62)}},
            fixture_only=True,
        )


def test_cost_only_attempt_alias_cannot_merge_across_arms():
    fixture = _fixture(with_calls=False)
    rows = {}
    for arm in ("strategy-review", "llm-proposal-research"):
        receipt = _cost(
            fixture.plan, fixture.window, arm, "budget-only", "RESERVATION_REQUESTED", 9, DECISION
        )
        rows[("cost", arm, "RESERVATION_REQUESTED:budget-only")] = receipt
    with pytest.raises(ValueError, match="identity reused"):
        observations.snapshot_window(fixture.plan, fixture.window, rows, fixture_only=True)


def test_sealed_unknown_budget_outcome_survives_later_denial():
    fixture = _fixture(candidate=True, with_calls=False)
    arm, attempt = "llm-proposal-research", "budget-only"
    requested = _cost(fixture.plan, fixture.window, arm, attempt, "RESERVATION_REQUESTED", 9, DECISION + 15)
    outcome = ResearchArmOutcomeV1(
        campaign_id=CAMPAIGN,
        sample_id=SAMPLE,
        arm_id=arm,
        claim_id=fixture.bundle.claim_id,
        status="UNKNOWN",
        bundle_receipt_sha256=fixture.bundle.receipt_sha256,
        evaluation_receipt_sha256=fixture.evaluation.receipt_sha256,
        observed_at_ts_ms=DECISION + 20,
    )
    rows = {
        **fixture.state,
        ("cost", arm, f"RESERVATION_REQUESTED:{attempt}"): requested,
        ("outcome", arm, "one"): outcome,
    }
    before = observations.snapshot_window(fixture.plan, fixture.window, rows, fixture_only=True)
    denied = _cost(fixture.plan, fixture.window, arm, attempt, "RESERVATION_DENIED", 0, DECISION + 30)
    rows[("cost", arm, f"RESERVATION_DENIED:{attempt}")] = denied
    after = observations.snapshot_window(fixture.plan, fixture.window, rows, fixture_only=True)
    assert before.inspection()["unresolved_cost_attempt_count"] == 1
    assert after.inspection()["unresolved_cost_attempt_count"] == 0
    assert after.inspection()["denied_reservation_count"] == 1
    assert after.inspection()["retained_outcome_statuses"] == {"UNKNOWN": 1}
    assert after.decoded()[2][("outcome", arm, "one")] == outcome
    assert before.inspection()["total_model_cost_microusd"] is None
    assert after.inspection()["total_model_cost_microusd"] is None


def test_explicit_complete_no_call_window_can_have_known_zero_not_empty_zero():
    fixture = _fixture(candidate=False, with_calls=False, complete_outcomes=True)
    info = fixture.snapshot().inspection()
    assert info["total_model_cost_microusd"] == 0
    assert info["model_cost_coverage_complete"] is True
    assert info["missing_scheduled_arm_outcomes"] == []
    assert info["economics_ready"] is False
    assert info["full_schedule_denominator_qualified"] is False
    observed = observations.snapshot_window(_plan("CAUSAL_OBSERVATION"), fixture.window, {})
    assert observed.inspection()["total_model_cost_microusd"] is None
    assert observed.inspection()["fixture_only"] is False


@pytest.mark.parametrize("changed", [None, "provider", "requested_model"])
def test_failure_provenance_remains_exact_to_start(changed):
    fixture = _fixture(candidate=True)
    start = fixture.state[("start", "strategy-review", ATTEMPT_REVIEW)]
    payload = {
        name: getattr(start, name)
        for name in (
            "campaign_id",
            "arm_id",
            "sample_id",
            "symbol",
            "timeframe",
            "market_as_of_ts_ms",
            "market_snapshot_sha256",
            "sample_deadline_ts_ms",
            "attempt_id",
            "provider",
            "requested_model",
            "prompt_sha256",
            "budget_reservation_id",
            "attempt_started_at_ts_ms",
        )
    }
    if changed is not None:
        payload[changed] = "different-route"
    failure = LLMCallFailureV1(
        **payload, failure_observed_at_ts_ms=start.attempt_started_at_ts_ms + 50, failure_class="TIMEOUT"
    )
    terminal = ResearchLLMAttemptTerminalV1(
        attempt_id=start.attempt_id,
        start_receipt_sha256=start.receipt_sha256,
        terminal_status="FAILED",
        observed_at_ts_ms=failure.failure_observed_at_ts_ms,
        failure=failure,
    )
    rows = dict(fixture.state)
    rows.pop(("review", start.arm_id, start.attempt_id))
    rows[("terminal", start.arm_id, start.attempt_id)] = terminal
    if changed:
        with pytest.raises(ValueError, match="failure changes"):
            observations.snapshot_window(fixture.plan, fixture.window, rows, fixture_only=True)
    else:
        snapshot = observations.snapshot_window(fixture.plan, fixture.window, rows, fixture_only=True)
        assert snapshot.inspection()["retained_terminal_statuses"]["FAILED"] == 1


@pytest.mark.parametrize("timeout", [0, 31, True, float("nan")])
def test_capture_rejects_unbounded_timeout_without_invoking_reader(timeout):
    fixture = _fixture()

    class Reader:
        calls = 0

        async def window_state(self, campaign_id, sample_id):
            self.calls += 1
            return {}

    reader = Reader()
    with pytest.raises(ValueError, match="timeout"):
        asyncio.run(
            observations.capture_window(
                reader, plan=fixture.plan, window=fixture.window, fixture_only=True, timeout_seconds=timeout
            )
        )
    assert reader.calls == 0


def test_cli_emits_sanitized_inspection_and_generic_failure_only(tmp_path, monkeypatch, capsys):
    snapshot = _fixture(candidate=True).snapshot()
    path = tmp_path / "native-window.json"
    observations.write_snapshot(path, snapshot)
    args = ["observations", "--input", str(path), "--expected-sha256", snapshot.sha256, "--fixture-only"]
    monkeypatch.setattr("sys.argv", args)
    assert observations.main() == 0
    result = capsys.readouterr().out
    assert json.loads(result)["economics_ready"] is False
    assert "fixture proposal" not in result
    assert "content" not in json.loads(result)
    monkeypatch.setattr("sys.argv", [*args[:4], _sha("wrong"), "--fixture-only"])
    assert observations.main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "REJECTED",
        "reason": "NATIVE_OBSERVATION_IMPORT_INVALID",
    }
