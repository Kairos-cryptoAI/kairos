import hashlib
from dataclasses import replace

import pytest
from kairos_core.contracts.decision_context import DecisionContextReceiptV1
from kairos_core.contracts.llm_proposal import LLMProposalModelProvenanceV1, LLMTradeProposalV1
from kairos_core.contracts.llm_proposal_completion import LLMProposalCompletionReceiptV1
from kairos_core.contracts.strategy import EvidenceReferenceV1
from kairos_core.enums import LLMProposalAction, Side
from kairos_core.topics import Topics
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent

from adaptive_replay.engine import AccountCost, CostScenario
from adaptive_replay.inputs import UNIVERSE, WindowInputs
from adaptive_replay.matched import MatchedSlot, ReviewReceipt
from adaptive_replay.system import (
    AttemptReceipt,
    ProposalMapping,
    ProposalObservation,
    ReviewObservation,
    SourceCut,
    SystemSlot,
    evaluate_system_paths,
)

START = 86_400_000
END = START + 5 * 60_000


def H(value):
    return hashlib.sha256(value.encode()).hexdigest()


SCENARIO = CostScenario("fixture", 0, 0, 0, 0, 0, 0)
POLICY = H("mapper-policy")


def _intent(symbol, decision, side, tag):
    sign = 1 if side is Side.LONG else -1
    return SleeveIntent(
        "adaptive_pullback_range_v1",
        symbol,
        side,
        decision,
        decision + 1,
        decision + 59_999,
        100.0,
        1.0,
        200.0,
        ExitPlan(100 - sign, 100 + 2 * sign, 120_000),
        (("fixture", tag),),
    )


def _sources(decision):
    rows = []
    for kind in ("market", "closed_bars", "text", "macro"):
        if kind in {"text", "macro"}:
            rows.append(SourceCut(kind, False, "UNAVAILABLE", (), "fixture_not_supplied"))
            continue
        digest = H(f"{kind}-{decision}")
        receipt = DecisionContextReceiptV1(
            message_id=f"{kind}-{decision}",
            source="fixture",
            topic=Topics.MARKET_SNAPSHOT if kind == "market" else Topics.CLOSED_BAR,
            content_sha256=digest,
            event_at_ms=decision,
            produced_at_ms=decision,
            received_at_ms=decision,
            ttl_ms=10_000_000,
        )
        rows.append(SourceCut(kind, kind in {"market", "closed_bars"}, "AVAILABLE", (receipt,)))
    return tuple(rows)


def _fixture():
    bars = {
        s: tuple(
            Candle(s, "1m", ts, ts + 59_999, 100, 100.1, 99.9, 100, 1000)
            for ts in range(START, END + 3 * 3_600_000, 60_000)
        )
        for s in UNIVERSE
    }
    inputs = WindowInputs(bars, {s: () for s in UNIVERSE}, {}, START, END, START, END + 3 * 3_600_000)
    slots, reviews, proposals = [], [], []
    for minute in range(1):
        decision = START - 1
        for idx, symbol in enumerate(UNIVERSE):
            key = f"slot-{minute}-{symbol}"
            candidate = None if idx == 0 else _intent(symbol, decision, Side.LONG, key)
            slot_id = H(key)
            matched = MatchedSlot(
                slot_id,
                decision,
                decision,
                H(key + "input"),
                candidate.intent_id if candidate else None,
                H("tape"),
            )
            slot = SystemSlot(
                matched, symbol, "QUIET" if candidate is None else "CANDIDATE", candidate, _sources(decision)
            )
            slots.append(slot)
            # A deterministic fixture review with its own observed/captured clock.
            rid = H(key + "review-attempt")
            review_result = "ALLOW"
            review_attempt = AttemptReceipt(
                rid,
                decision,
                decision + 100 if candidate is not None else decision,
                0.01 if candidate is not None else 0,
                "COMPLETE" if candidate is not None else "NOT_CALLED",
                "TEST_FIXTURE",
                slot.context_sha256,
                "SCHEDULED_POLICY_ABSTAIN" if candidate is None else None,
            )
            receipt = (
                None
                if candidate is None
                else ReviewReceipt(
                    matched,
                    candidate.intent_id,
                    decision,
                    decision + 50,
                    decision + 100,
                    review_result,
                    "OPENAI",
                    "fixture-model",
                    0.01,
                    "TEST_FIXTURE",
                    slot.sources[2].sha256,
                    H(key + "response"),
                )
            )
            if candidate is not None:
                reviews.append(ReviewObservation(slot_id, review_attempt, receipt))
            aid = H(key + "proposal-attempt")
            observed = decision + 200
            attempt = AttemptReceipt(
                aid, decision, observed, 0.02, "COMPLETE", "TEST_FIXTURE", slot.context_sha256
            )
            market_digest = slot.sources[0].receipts[0].content_sha256
            provenance = LLMProposalModelProvenanceV1(
                provider="OPENAI",
                requested_model="fixture",
                resolved_model="fixture",
                request_id=f"req-{minute}-{idx}",
                prompt_sha256=H(key + "prompt"),
                response_sha256=H(key + "response"),
                budget_reservation_id=f"budget-{minute}-{idx}",
                latency_ms=100,
                cost_usd=0.02,
            )
            action = LLMProposalAction.LONG_BIAS if candidate is None else LLMProposalAction.LONG_BIAS
            native = LLMTradeProposalV1(
                campaign_id="fixture-campaign",
                arm_id="llm-proposal-research",
                sample_id=slot_id,
                symbol=symbol,
                timeframe="5m",
                market_as_of_ts_ms=decision,
                expires_at_ts_ms=decision + 120_000,
                market_snapshot_sha256=market_digest,
                action=action,
                rationale="fixture only",
                evidence=(
                    EvidenceReferenceV1(
                        kind="source",
                        reference=slot.sources[0].receipts[0].message_id,
                        content_sha256=market_digest,
                        observed_at_ms=decision,
                    ),
                ),
                model_provenance=provenance,
            )
            completion = LLMProposalCompletionReceiptV1(
                campaign_id="fixture-campaign",
                arm_id="llm-proposal-research",
                sample_id=slot_id,
                symbol=symbol,
                timeframe="5m",
                market_as_of_ts_ms=decision,
                market_snapshot_sha256=market_digest,
                sample_deadline_ts_ms=decision + 10_000,
                attempt_id=aid,
                proposal_id=native.proposal_id,
                model_provenance=provenance,
                attempt_started_at_ts_ms=decision,
                response_observed_at_ts_ms=observed,
            )
            mapped = _intent(symbol, decision, Side.LONG, key + "proposal")
            mapping = ProposalMapping(
                native.proposal_id, matched.input_window_sha256, POLICY, observed + 1, mapped
            )
            proposals.append(ProposalObservation(slot_id, attempt, native, completion, mapping))
    return inputs, tuple(slots), tuple(reviews), tuple(proposals)


def _run(data):
    return evaluate_system_paths(
        *data, SCENARIO, "INTRABAR_OPEN_PROXY", mapper_policy_sha256=POLICY, fixture_only=True
    )


def test_four_independent_paths_and_quiet_slot_proposals_are_fixture_only():
    result = _run(_fixture())
    assert result["scheduled_slots"] == 5
    assert result["slot_states"] == {"QUIET": 1, "CANDIDATE": 4}
    assert set(result["arms"]) == {"strategy_only", "context_review", "independent_proposals", "combined"}
    assert all(arm["status"] == "FIXTURE_ONLY" for arm in result["arms"].values())
    assert all(arm["economic_results"] is not None for arm in result["arms"].values())
    assert result["arms"]["independent_proposals"]["known_model_cost_usd"] == pytest.approx(0.1)
    assert result["arms"]["context_review"]["known_model_cost_usd"] == pytest.approx(0.04)
    review_slot = next(s for s in _fixture()[1] if s.state == "CANDIDATE")
    context_entries = result["arms"]["context_review"]["events"]
    entry = next(
        e
        for e in context_entries
        if e.get("kind") == "ENTRY" and e["intent_id"] == review_slot.candidate.intent_id
    )
    receipt = next(r.review for r in _fixture()[2] if r.slot_id == review_slot.matched.slot_id)
    assert entry["timestamp_ms"] == receipt.captured_ms
    assert entry["timestamp_ms"] != receipt.completed_ms
    baseline_entries = [e for e in result["arms"]["strategy_only"]["events"] if e.get("kind") == "ENTRY"]
    combined_entries = [e for e in result["arms"]["combined"]["events"] if e.get("kind") == "ENTRY"]
    combined_by_symbol = {e["symbol"]: e["intent_id"] for e in combined_entries}
    baseline_by_symbol = {e["symbol"]: e["intent_id"] for e in baseline_entries}
    common = baseline_by_symbol.keys() & combined_by_symbol.keys()
    assert all(combined_by_symbol[s] == baseline_by_symbol[s] for s in common)
    assert "BTCUSDT" in combined_by_symbol  # independent proposal on a quiet strategy slot


@pytest.mark.parametrize("disposition", ["VETO", "DEFER"])
def test_review_refusal_cannot_be_undone_by_same_direction_proposal(disposition):
    inputs, slots, reviews, proposals = _fixture()
    candidate = next(s for s in slots if s.state == "CANDIDATE")
    i = next(i for i, r in enumerate(reviews) if r.slot_id == candidate.matched.slot_id)
    prior = reviews[i]
    review = replace(prior.review, result=disposition)
    reviews = (*reviews[:i], replace(prior, review=review), *reviews[i + 1 :])
    result = _run((inputs, slots, reviews, proposals))
    assert result["arms"]["combined"]["decisions"].get("REVIEW_BLOCKED", 0) > 0


def test_fixture_receipts_cannot_be_relabelled_as_observed():
    inputs, slots, reviews, proposals = _fixture()
    altered = replace(
        proposals[0], attempt=replace(proposals[0].attempt, evidence_kind="OBSERVED_POINT_IN_TIME")
    )
    with pytest.raises(ValueError, match="cannot be mixed or relabelled"):
        _run((inputs, slots, reviews, (altered, *proposals[1:])))


def test_full_five_symbol_schedule_is_required():
    inputs, slots, reviews, proposals = _fixture()
    with pytest.raises(ValueError, match="complete fixed five-minute"):
        _run((inputs, slots[:-1], reviews, proposals))


def test_native_linkage_and_mapper_policy_changes_rejected():
    inputs, slots, reviews, proposals = _fixture()
    bad = replace(proposals[0], mapping=replace(proposals[0].mapping, policy_sha256=H("other")))
    with pytest.raises(ValueError, match="mapper policy"):
        _run((inputs, slots, reviews, (bad, *proposals[1:])))
    bad_payload = proposals[0].proposal.model_dump(mode="json")
    bad_payload.update(sample_id=H("other-sample"), proposal_id=None)
    bad_native = LLMTradeProposalV1.model_validate(bad_payload)
    with pytest.raises(ValueError, match="native proposal/completion/attempt"):
        replace(proposals[0], proposal=bad_native)
    bad_digest = H("forged-proposal-digest")
    with pytest.raises(ValueError, match="proposal_id"):
        forged_payload = proposals[0].proposal.model_dump(mode="json")
        forged_payload["proposal_id"] = bad_digest
        LLMTradeProposalV1.model_validate(forged_payload)


def test_opposite_direction_proposal_abstains_and_no_action_error_late_costs_remain():
    inputs, slots, reviews, proposals = _fixture()
    candidate_slot = next(s for s in slots if s.state == "CANDIDATE")
    index = next(i for i, p in enumerate(proposals) if p.slot_id == candidate_slot.matched.slot_id)
    original = proposals[index]
    opposite = _intent(
        candidate_slot.symbol, candidate_slot.matched.decision_ms, Side.SHORT, "independent-short"
    )
    mapping = replace(original.mapping, candidate=opposite)
    # The native/completion pair remains the source of observed clocks; a mapper
    # may only emit geometry in the direction of the native hypothesis.
    short_payload = original.proposal.model_dump(mode="json")
    short_payload.update(action=LLMProposalAction.SHORT_BIAS.value, proposal_id=None)
    short_native = LLMTradeProposalV1.model_validate(short_payload)
    completion_payload = original.completion.model_dump(mode="json")
    completion_payload.update(proposal_id=short_native.proposal_id, completion_receipt_id=None)
    completion = LLMProposalCompletionReceiptV1.model_validate(completion_payload)
    short_obs = replace(
        original,
        proposal=short_native,
        completion=completion,
        mapping=replace(mapping, proposal_id=short_native.proposal_id),
    )
    proposals = (*proposals[:index], short_obs, *proposals[index + 1 :])
    result = _run((inputs, slots, reviews, proposals))
    assert result["arms"]["combined"]["decisions"].get("DIRECTION_CONFLICT", 0) == 1

    # No-action, failed, and late calls still incur their known observed debit.
    inputs, slots, reviews, proposals = _fixture()
    first = proposals[0]
    no_action_payload = first.proposal.model_dump(mode="json")
    no_action_payload.update(action=LLMProposalAction.NO_PROPOSAL.value, proposal_id=None)
    no_action_native = LLMTradeProposalV1.model_validate(no_action_payload)
    no_action_completion_payload = first.completion.model_dump(mode="json")
    no_action_completion_payload.update(proposal_id=no_action_native.proposal_id, completion_receipt_id=None)
    no_action_completion = LLMProposalCompletionReceiptV1.model_validate(no_action_completion_payload)
    no_action = replace(first, proposal=no_action_native, completion=no_action_completion, mapping=None)
    error_attempt = replace(proposals[1].attempt, status="ERROR")
    error = replace(proposals[1], attempt=error_attempt, proposal=None, completion=None, mapping=None)
    late_clock = proposals[2].attempt.requested_ms + 10_000
    late_attempt = replace(proposals[2].attempt, observed_ms=late_clock)
    late_payload = proposals[2].completion.model_dump(mode="json")
    late_payload.update(response_observed_at_ts_ms=late_clock, completion_receipt_id=None)
    late_completion = LLMProposalCompletionReceiptV1.model_validate(late_payload)
    late_mapping = replace(proposals[2].mapping, mapped_ms=late_clock + 1)
    late = replace(proposals[2], attempt=late_attempt, completion=late_completion, mapping=late_mapping)
    edited = (no_action, error, late, *proposals[3:])
    result = _run((inputs, slots, reviews, edited))
    proposal_arm = result["arms"]["independent_proposals"]
    assert proposal_arm["known_model_cost_usd"] == pytest.approx(0.1)
    assert proposal_arm["decisions"].get("NO_PROPOSAL", 0) == 1
    assert proposal_arm["decisions"].get("ERROR", 0) == 1
    assert proposal_arm["decisions"].get("LATE_PROPOSAL", 0) == 1


def test_unknown_observation_cost_nulls_economic_arm():
    inputs, slots, reviews, proposals = _fixture()
    unknown = replace(proposals[0].attempt, cost_usd=None)
    proposals = (replace(proposals[0], attempt=unknown), *proposals[1:])
    arm = _run((inputs, slots, reviews, proposals))["arms"]["independent_proposals"]
    assert arm["status"] == "INCOMPLETE"
    assert arm["economic_results"] is None
    assert arm["unknown_cost_attempts"] == 1


def _proposal_variant(original, *, action=None, observed_ms=None, mapped_ms=None, deadline_ms=None):
    payload = original.proposal.model_dump(mode="json")
    payload["proposal_id"] = None
    if action is not None:
        payload["action"] = action.value
    native = LLMTradeProposalV1.model_validate(payload)
    attempt = original.attempt if observed_ms is None else replace(original.attempt, observed_ms=observed_ms)
    completion_payload = original.completion.model_dump(mode="json")
    completion_payload.update(
        proposal_id=native.proposal_id,
        completion_receipt_id=None,
        response_observed_at_ts_ms=attempt.observed_ms,
    )
    if deadline_ms is not None:
        completion_payload["sample_deadline_ts_ms"] = deadline_ms
    completion = LLMProposalCompletionReceiptV1.model_validate(completion_payload)
    if native.action in {
        LLMProposalAction.NO_PROPOSAL,
        LLMProposalAction.DEFER,
        LLMProposalAction.VOLATILITY_ALERT,
    }:
        mapping = None
    else:
        side = Side.LONG if native.action is LLMProposalAction.LONG_BIAS else Side.SHORT
        mapped = _intent(native.symbol, native.market_as_of_ts_ms, side, "variant-independent")
        mapping = replace(
            original.mapping,
            proposal_id=native.proposal_id,
            candidate=mapped,
            mapped_ms=mapped_ms if mapped_ms is not None else attempt.observed_ms + 1,
        )
    return replace(original, proposal=native, completion=completion, attempt=attempt, mapping=mapping)


def test_missing_quiet_response_is_not_zero_cost_no_proposal():
    inputs, slots, reviews, proposals = _fixture()
    result = _run((inputs, slots, reviews, proposals[1:]))
    for path in ("independent_proposals", "combined"):
        assert result["arms"][path]["status"] == "INCOMPLETE"
        assert result["arms"][path]["economic_results"] is None
        assert result["paired_account_deltas_usd"][path] is None
    assert result["arms"]["context_review"]["economic_results"] is not None


@pytest.mark.parametrize(
    "action", [LLMProposalAction.NO_PROPOSAL, LLMProposalAction.DEFER, LLMProposalAction.VOLATILITY_ALERT]
)
def test_exact_deadline_nontrading_completion_cannot_unlock_combined(action):
    inputs, slots, reviews, proposals = _fixture()
    late = _proposal_variant(
        proposals[1], action=action, observed_ms=proposals[1].completion.sample_deadline_ts_ms
    )
    result = _run((inputs, slots, reviews, (proposals[0], late, *proposals[2:])))
    combined = result["arms"]["combined"]
    assert combined["decisions"]["PROPOSAL_UNUSABLE"] == 1
    assert not any(e.get("symbol") == slots[1].symbol and e["kind"] == "ENTRY" for e in combined["events"])
    assert combined["known_model_cost_usd"] == pytest.approx(0.14)


def test_native_uuid_attempt_id_does_not_require_rewriting_receipt_identity():
    inputs, slots, reviews, proposals = _fixture()
    attempt = replace(proposals[0].attempt, attempt_id="63956903-bd43-4b58-bcee-8dddf51b4674")
    payload = proposals[0].completion.model_dump(mode="json")
    payload.update(attempt_id=attempt.attempt_id, completion_receipt_id=None)
    completion = LLMProposalCompletionReceiptV1.model_validate(payload)
    changed = replace(proposals[0], attempt=attempt, completion=completion)
    assert (
        _run((inputs, slots, reviews, (changed, *proposals[1:])))["arms"]["combined"]["status"]
        == "FIXTURE_ONLY"
    )


def test_forged_native_model_copy_cannot_bypass_canonical_validation():
    original = _fixture()[3][0]
    forged_id = H("forged-native")
    with pytest.raises(ValueError, match="proposal_id"):
        replace(
            original,
            proposal=original.proposal.model_copy(update={"proposal_id": forged_id}),
            completion=original.completion.model_copy(
                update={"proposal_id": forged_id, "completion_receipt_id": None}
            ),
            mapping=replace(original.mapping, proposal_id=forged_id),
        )


def test_optional_available_text_still_expires_and_never_becomes_neutral():
    inputs, slots, reviews, proposals = _fixture()
    original = slots[1]
    cut = original.matched.decision_ms
    receipt = DecisionContextReceiptV1(
        message_id="short-lived-news",
        source="fixture",
        topic=Topics.SENTIMENT_SIGNAL,
        content_sha256=H("short-lived-news"),
        event_at_ms=cut,
        produced_at_ms=cut,
        received_at_ms=cut,
        ttl_ms=50,
    )
    text = SourceCut("text", False, "AVAILABLE", (receipt,))
    slot = replace(original, sources=(*original.sources[:2], text, original.sources[3]))
    review = replace(
        reviews[0],
        attempt=replace(reviews[0].attempt, context_sha256=slot.context_sha256),
        review=replace(reviews[0].review, point_in_time_news_sha256=text.sha256),
    )
    proposal = replace(
        proposals[1], attempt=replace(proposals[1].attempt, context_sha256=slot.context_sha256)
    )
    result = _run(
        (
            inputs,
            (slots[0], slot, *slots[2:]),
            (review, *reviews[1:]),
            (proposals[0], proposal, *proposals[2:]),
        )
    )
    assert result["arms"]["context_review"]["decisions"]["STALE_CONTEXT"] == 1
    assert result["arms"]["independent_proposals"]["decisions"]["LATE_OR_STALE_MAPPING"] == 1


def test_expired_opposite_mapping_is_not_a_live_direction_conflict():
    inputs, slots, reviews, proposals = _fixture()
    expired = _proposal_variant(
        proposals[1],
        action=LLMProposalAction.SHORT_BIAS,
        mapped_ms=START + 60_000,
        deadline_ms=START + 90_000,
    )
    result = _run((inputs, slots, reviews, (proposals[0], expired, *proposals[2:])))
    decisions = result["arms"]["combined"]["decisions"]
    assert decisions.get("DIRECTION_CONFLICT", 0) == 0
    assert decisions["PROPOSAL_NO_ELIGIBLE_QUOTE"] == 1


def test_unknown_feed_cost_keeps_all_in_result_null_not_invented_free_feed():
    data = _fixture()
    unknown = _run(data)
    assert all(a["recorded_all_in_net_result"] is None for a in unknown["arms"].values())
    known = evaluate_system_paths(
        *data,
        SCENARIO,
        "INTRABAR_OPEN_PROXY",
        mapper_policy_sha256=POLICY,
        fixture_only=True,
        feed_costs=(AccountCost("fixture-feed", START, 0.5, "FEED"),),
    )
    for arm in known["arms"].values():
        assert arm["recorded_all_in_net_result"] is not None
        # Charges also affect sizing, so this is NOT necessarily an exact $0.50
        # account delta when trades are present.
        assert arm["economic_results"]["recorded_service_cost_usd"] == pytest.approx(
            arm["known_model_cost_usd"] + 0.5
        )
        assert arm["complete_all_in_net_economics"] is False


def test_fixture_only_is_explicit_and_never_an_observed_campaign_pass():
    with pytest.raises(ValueError, match="cannot be mixed or relabelled"):
        evaluate_system_paths(*_fixture(), SCENARIO, "INTRABAR_OPEN_PROXY", mapper_policy_sha256=POLICY)
    result = _run(_fixture())
    assert not any(
        result[key]
        for key in (
            "technical_paper_ready",
            "paper_qualified",
            "alpha_ready",
            "live_ready",
            "matched_campaign_executed",
        )
    )
    assert result["strategy_policy"] == "REJECT_ALL"


def test_unavailable_and_unmapped_are_not_quiet_or_no_proposal():
    inputs, slots, reviews, proposals = _fixture()
    absent = replace(slots[0], state="UNAVAILABLE", unavailable_reason="DETECTOR_FAILURE")
    no_mapper = replace(proposals[1], mapping=None)
    result = _run((inputs, (absent, *slots[1:]), reviews, (proposals[0], no_mapper, *proposals[2:])))
    assert result["slot_states"]["UNAVAILABLE"] == 1
    assert result["unavailable_reasons"] == {"DETECTOR_FAILURE": 1}
    arm = result["arms"]["independent_proposals"]
    assert arm["decisions"]["SOURCE_UNAVAILABLE"] == 1
    assert arm["decisions"]["MAPPER_UNAVAILABLE"] == 1
    assert arm["economic_results"] is None
    assert arm["known_model_cost_usd"] == pytest.approx(0.1)


@pytest.mark.parametrize("action", [LLMProposalAction.LONG_BIAS, LLMProposalAction.SHORT_BIAS])
def test_proposal_expiring_while_waiting_for_review_cannot_affect_combined(action):
    inputs, slots, reviews, proposals = _fixture()
    original = _proposal_variant(proposals[1], action=action)
    cut = slots[1].matched.decision_ms
    payload = original.proposal.model_dump(mode="json")
    payload.update(expires_at_ts_ms=cut + 1000, proposal_id=None)
    native = LLMTradeProposalV1.model_validate(payload)
    completion_payload = original.completion.model_dump(mode="json")
    completion_payload.update(proposal_id=native.proposal_id, completion_receipt_id=None)
    completion = LLMProposalCompletionReceiptV1.model_validate(completion_payload)
    mapping = replace(
        original.mapping,
        proposal_id=native.proposal_id,
        candidate=replace(original.mapping.candidate, entry_expires_ts_ms=cut + 999),
    )
    proposal = replace(original, proposal=native, completion=completion, mapping=mapping)
    review = replace(
        reviews[0],
        attempt=replace(reviews[0].attempt, observed_ms=cut + 5000),
        review=replace(reviews[0].review, captured_ms=cut + 5000),
    )
    result = _run((inputs, slots, (review, *reviews[1:]), (proposals[0], proposal, *proposals[2:])))
    arm = result["arms"]["combined"]
    assert arm["decisions"]["PROPOSAL_UNUSABLE"] == 1
    assert arm["decisions"].get("DIRECTION_CONFLICT", 0) == 0
    assert not any(e["kind"] == "ENTRY" and e["symbol"] == slots[1].symbol for e in arm["events"])


def test_window_bound_refuses_huge_range_before_building_roster():
    inputs, slots, reviews, proposals = _fixture()
    with pytest.raises(ValueError, match="bounded window"):
        _run((replace(inputs, end_ms=60_000 * 10**14), slots, reviews, proposals))


def test_unavailable_slot_still_validates_native_source_link_before_replay():
    inputs, slots, reviews, proposals = _fixture()
    unavailable = replace(slots[0], state="UNAVAILABLE", unavailable_reason="COLLECTOR_GAP")
    original = proposals[0]
    payload = original.proposal.model_dump(mode="json")
    payload.update(market_snapshot_sha256=H("wrong-market"), proposal_id=None)
    native = LLMTradeProposalV1.model_validate(payload)
    completion_payload = original.completion.model_dump(mode="json")
    completion_payload.update(
        market_snapshot_sha256=native.market_snapshot_sha256,
        proposal_id=native.proposal_id,
        completion_receipt_id=None,
    )
    completion = LLMProposalCompletionReceiptV1.model_validate(completion_payload)
    forged = replace(
        original,
        proposal=native,
        completion=completion,
        mapping=replace(original.mapping, proposal_id=native.proposal_id),
    )
    with pytest.raises(ValueError, match="common causal slot/market"):
        _run((inputs, (unavailable, *slots[1:]), reviews, (forged, *proposals[1:])))
