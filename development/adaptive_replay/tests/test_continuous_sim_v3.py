"""End-to-end portfolio contracts for the distinct prospective V3 producer."""

from dataclasses import asdict, replace
from decimal import Decimal as D

import pytest
from kairos_core.enums import Side
from kairos_execution.simulation.models import AcceptedBookFrame, BookLevel, FillAssumptions
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent
from kairos_strategy.provenance import candle_payload

from adaptive_replay.candle_originals_v3 import CandleOriginalsV3, RetainedCandleV3
from adaptive_replay.continuous_sim import (
    UNIVERSE,
    ClosedCandleInput,
    ContinuousSimPortfolio,
    FundingSchedule,
    SimInputError,
    SymbolRules,
    TapeBinding,
    TapeInput,
)
from adaptive_replay.historical_context import digest
from adaptive_replay.hypothesis_journal import HypothesisJournal, JournalArm, JournalSeal
from adaptive_replay.hypothesis_journal_v3 import (
    ArmReviewReceiptV3,
    HypothesisJournalV3,
    JournalArmV3,
    JournalSealV3,
    MatchedObservationV3,
)
from adaptive_replay.hypothesis_v2 import HypothesisPlan as HypothesisPlanV2
from adaptive_replay.hypothesis_v2 import HypothesisPolicy as HypothesisPolicyV2
from adaptive_replay.hypothesis_v3 import (
    CreationAssessment,
    EntryQuote,
    HypothesisObservation,
    HypothesisPlan,
    HypothesisPolicy,
    creation_input_sha256,
)
from adaptive_replay.scenarios import (
    MINUTE,
    ScenarioEvaluation,
    ScenarioEvidence,
    ScenarioObservation,
    ScenarioReview,
)
from adaptive_replay.sim_account_codec import decode_account

START = 86_400_000
OBSERVED = START + MINUTE + 200
ISSUE_SHA = "a" * 64
SOURCE_SHA = "b" * 64
CONTEXT_SHA = "c" * 64
MODEL_SHA = "d" * 64


def candle(open_ms, *, high=101.0, low=99.0, close=100.0, volume=10.0):
    return Candle("BTCUSDT", "1m", open_ms, open_ms + MINUTE - 1, 100.0, high, low, close, volume)


def evidence(bar, *, source_id="bars", captured=None, kind="MARKET"):
    captured = bar.close_time_ms + 10 if captured is None else captured
    return ScenarioEvidence(
        source_id,
        kind,
        bar.symbol,
        digest(candle_payload(bar)) if kind == "MARKET" else SOURCE_SHA,
        bar.close_time_ms,
        captured,
        captured,
        600_000,
    )


def retained(bar, receipt, available):
    return RetainedCandleV3(bar, receipt, available, "TEST_FIXTURE")


def candle_input(record):
    bar, receipt = record.candle, record.evidence
    return ClosedCandleInput(
        bar.symbol,
        bar.open_time_ms,
        bar.close_time_ms,
        record.available_at_ms,
        D(str(bar.close)),
        receipt.source_id,
        record.evidence_kind,
        receipt.payload_sha256,
    )


def book(*, seq=1, at=OBSERVED - 2, bid="100.49", ask="100.50", bqty="20", aqty="20"):
    return AcceptedBookFrame(
        tape_id="fixture-tape",
        stream_epoch="fixture-epoch",
        symbol="BTCUSDT",
        sequence=seq,
        exchange_update_id=seq * 10,
        exchange_at_ms=at - 2,
        received_at_ms=at - 1,
        persisted_at_ms=at,
        raw_payload_sha256=ISSUE_SHA,
        continuity="ADMITTED",
        bids=(BookLevel(price=D(bid), quantity=D(bqty)),),
        asks=(BookLevel(price=D(ask), quantity=D(aqty)),),
    )


def policy(*, review=False):
    return HypothesisPolicy(START - 1, 5 * MINUTE, "quotes", 5_000, "TEST_FIXTURE", review)


def plan(*, arm_policy=None, origin="TECHNICAL", created=None):
    arm_policy = arm_policy or policy()
    created = START + 10_020 if created is None else created
    anchor = candle(START - MINUTE)
    anchor_receipt = evidence(anchor)
    parent = SleeveIntent(
        "trend_breakout_v1",
        "BTCUSDT",
        Side.LONG,
        START - 1,
        START,
        START + 5 * MINUTE,
        100.0,
        0.7,
        600.0,
        ExitPlan(98.5, 106.0, 300_000, None, None),
        (("fixture", "v3"),),
    )
    return HypothesisPlan(
        parent,
        origin,
        "BULL",
        START,
        created,
        ISSUE_SHA,
        CONTEXT_SHA,
        (anchor_receipt,),
        anchor,
        (("MARKET", "bars"),),
        arm_policy,
    )


def context_plan(arm_policy):
    base = plan(arm_policy=arm_policy, created=START + 10_040)
    extra = tuple(
        sorted(
            base.creation_evidence
            + (
                evidence(base.anchor, source_id="macro", captured=START + 10_020, kind="MACRO"),
                evidence(base.anchor, source_id="news", captured=START + 10_020, kind="NEWS"),
            ),
            key=lambda item: (item.kind, item.source_id),
        )
    )
    sources = (("MACRO", "macro"), ("MARKET", "bars"), ("NEWS", "news"))
    actual_created = START + 10_040
    input_hash = creation_input_sha256(ISSUE_SHA, CONTEXT_SHA, base.anchor, extra)
    assessment = CreationAssessment(
        input_hash,
        "e" * 64,
        MODEL_SHA,
        "LONG",
        START + 10_020,
        START + 10_030,
        START + 10_035,
        "TEST_FIXTURE",
    )
    return HypothesisPlan(
        base.template,
        "CONTEXT_PROPOSAL",
        "BULL",
        START,
        actual_created,
        ISSUE_SHA,
        CONTEXT_SHA,
        extra,
        base.anchor,
        sources,
        arm_policy,
        assessment,
    )


def make_fixture(
    tmp_path,
    *,
    request=None,
    plans=None,
    arms=("arm",),
    require_review=False,
    review=None,
    quote=True,
    allowed_origins=("TECHNICAL",),
    minutes=None,
    anchor_available=None,
    trigger_available=None,
    extra_records=(),
    extra_values=(),
    initial_aqty="20",
):
    arms = tuple(sorted(arms))
    arm_policies = {arm: policy(review=require_review) for arm in arms}
    plans = plans or {arm: plan(arm_policy=arm_policies[arm]) for arm in arms}
    seal_arms = tuple(
        JournalArmV3(arm, arm_policies[arm], MODEL_SHA if arm_policies[arm].require_review else None)
        for arm in arms
    )
    seal = JournalSealV3("continuous-v3-fixture", START - 1, ISSUE_SHA, seal_arms, 16)
    hypothesis = HypothesisJournalV3.create(tmp_path / "hypotheses.research.sqlite3", seal)
    for arm in arms:
        hypothesis.register(arm, plans[arm])

    trigger = candle(START, high=101.5, low=99.5, close=100.5)
    trigger_receipt = evidence(trigger)
    trigger_sources = [trigger_receipt]
    if plans[arms[0]].origin == "CONTEXT_PROPOSAL":
        trigger_sources.extend(
            (
                evidence(trigger, source_id="macro", captured=trigger_receipt.captured_ms, kind="MACRO"),
                evidence(trigger, source_id="news", captured=trigger_receipt.captured_ms, kind="NEWS"),
            )
        )
    trigger_sources = tuple(sorted(trigger_sources, key=lambda item: (item.kind, item.source_id)))
    frame = book(aqty=initial_aqty)
    quote = (
        None
        if not quote
        else EntryQuote(
            "quotes",
            frame.symbol,
            float(frame.bids[0].price),
            float(frame.asks[0].price),
            frame.exchange_at_ms,
            frame.received_at_ms,
            frame.persisted_at_ms,
            5_000,
            "TEST_FIXTURE",
        )
    )
    scenario_review = None
    receipts_by_arm = {}
    shared_observation = HypothesisObservation(ScenarioObservation(trigger, OBSERVED, trigger_sources), quote)
    if review is not None:
        scenario_review = ScenarioReview(
            plans[arms[0]].scenario_id,
            Side.LONG,
            review,
            shared_observation.context_sha256,
            OBSERVED + 20,
            "f" * 64,
        )
    matched = MatchedObservationV3(
        shared_observation,
        tuple(
            ArmReviewReceiptV3(
                arm,
                OBSERVED + (40 if review is not None else 0),
                OBSERVED,
                scenario_review,
                MODEL_SHA if review is not None else None,
                OBSERVED + 1 if review is not None else None,
                OBSERVED + 30 if review is not None else None,
            )
            for arm in arms
        ),
    )
    receipts = hypothesis.append(plans[arms[0]].template.intent_id, matched)
    for receipt in receipts:
        receipts_by_arm[receipt.arm_id] = receipt

    anchor_receipt = next(
        item
        for item in plans[arms[0]].creation_evidence
        if item.kind == "MARKET" and item.payload_sha256 == digest(candle_payload(plans[arms[0]].anchor))
    )
    anchor_record = retained(
        plans[arms[0]].anchor,
        anchor_receipt,
        START + 10_010 if anchor_available is None else anchor_available,
    )
    trigger_record = retained(
        trigger,
        trigger_receipt,
        OBSERVED if trigger_available is None else trigger_available,
    )
    all_records = (anchor_record, trigger_record, *extra_records)
    originals = CandleOriginalsV3(
        tuple(sorted(all_records, key=lambda r: (r.candle.symbol, r.candle.open_time_ms)))
    )
    values = [
        TapeInput(1, candle_input(anchor_record)),
        TapeInput(2, frame),
        TapeInput(3, candle_input(trigger_record)),
    ]
    values.extend(TapeInput(i + 4, candle_input(record)) for i, record in enumerate(extra_records))
    values.extend(extra_values)
    values.sort(key=lambda item: item.global_sequence)
    binding = TapeBinding(
        "fixture-source",
        "fixture-tape",
        "fixture-epoch",
        "quotes",
        "TEST_FIXTURE",
        tuple(values),
    )
    models = {
        symbol: FillAssumptions(
            latency_ms=2,
            maximum_book_age_ms=60_000,
            maximum_frame_latency_ms=5_000,
            depth_participation_fraction=D(1),
            adverse_slippage_bps=D(0),
            taker_fee_bps=D(10),
            price_tick=D("0.01"),
            quantity_step=D("0.001"),
        )
        for symbol in UNIVERSE
    }
    rules = {symbol: SymbolRules(symbol, D("0.01"), D("0.001"), D("100000")) for symbol in UNIVERSE}
    schedule = FundingSchedule("funding", "TEST_FIXTURE", (), ISSUE_SHA)
    portfolio = ContinuousSimPortfolio.create(
        tmp_path / "portfolio-arm.sqlite3",
        campaign_id="fixture-campaign",
        arm_id=arms[0],
        binding=binding,
        models=models,
        rules=rules,
        funding_schedule=schedule,
        minutes=tuple(minutes or (START + MINUTE,)),
        initial_equity=D("1000"),
        hypothesis_seal_sha256=hypothesis.snapshot().seal_sha256,
        hypothesis_contract="V3",
        candle_originals=originals,
        allowed_origins=allowed_origins,
    )
    fixture = {
        "binding": binding,
        "frame": frame,
        "hypothesis": hypothesis,
        "originals": originals,
        "plans": plans,
        "portfolio": portfolio,
        "receipts": receipts_by_arm,
        "models": models,
        "rules": rules,
        "schedule": schedule,
        "seal": seal,
        "trigger": trigger,
        "trigger_receipt": trigger_receipt,
    }
    if request is not None:
        request.addfinalizer(lambda: safe_close(fixture["portfolio"]))
    return fixture


def ingest_all(runner):
    for item in runner.binding.inputs:
        value = item.value
        at = value.persisted_at_ms if isinstance(value, AcceptedBookFrame) else value.available_at_ms
        runner.ingest(global_sequence=item.global_sequence, now_ms=at)


def account(runner):
    return decode_account(runner.snapshot().state["account"])


def reopen(fixture, runner):
    snapshot = runner.snapshot()
    path, identity = runner.path, runner.journal.identity
    safe_close(runner)
    reopened = ContinuousSimPortfolio.open(
        path,
        identity=identity,
        binding=fixture["binding"],
        models=fixture["models"],
        rules=fixture["rules"],
        funding_schedule=fixture["schedule"],
        config=snapshot.state["config"],
        expected_head_sha256=snapshot.head_hash,
        candle_originals=fixture["originals"],
    )
    fixture["portfolio"] = reopened
    return reopened


def safe_close(runner):
    if not getattr(runner, "_test_closed", False):
        runner.close()
        runner._test_closed = True


def intake(runner, hypothesis, receipt, head, *, at=OBSERVED + 40):
    return runner.intake_v3(
        hypothesis_journal=hypothesis,
        receipt=receipt,
        expected_hypothesis_head_sha256=head,
        at_ms=at,
    )


def v2_registration(tmp_path):
    anchor = candle(START - MINUTE)
    source = ScenarioEvidence(
        "bars",
        "MARKET",
        "BTCUSDT",
        digest(candle_payload(anchor)),
        anchor.close_time_ms,
        START,
        START,
        600_000,
    )
    parent = SleeveIntent(
        "trend_breakout_v1",
        "BTCUSDT",
        Side.LONG,
        START - 1,
        START,
        START + 5 * MINUTE,
        100.0,
        0.7,
        600.0,
        ExitPlan(98.5, 106.0, 300_000, None, None),
        (("fixture", "v2-boundary"),),
    )
    v2_policy = HypothesisPolicyV2(START - 1, 5 * MINUTE, "quotes", 5_000, "TEST_FIXTURE", False)
    v2_plan = HypothesisPlanV2(
        parent,
        "TECHNICAL",
        "BULL",
        START,
        ISSUE_SHA,
        CONTEXT_SHA,
        (source,),
        anchor,
        (("MARKET", "bars"),),
        v2_policy,
    )
    seal = JournalSeal("v2-boundary", START - 1, ISSUE_SHA, (JournalArm("arm", v2_policy),), 1)
    journal = HypothesisJournal.create(tmp_path / "v2-boundary.research.sqlite3", seal)
    registration = journal.register("arm", v2_plan)
    assert type(registration.evaluation) is ScenarioEvaluation
    return journal, registration


def test_v3_partial_entry_restart_duplicate_and_partial_protective_exit(tmp_path, request):
    stop_frames = (
        book(seq=2, at=OBSERVED + 100, bid="98.00", ask="98.01", bqty="0.1"),
        book(seq=3, at=OBSERVED + 110, bid="98.00", ask="98.01", bqty="0.1"),
        book(seq=4, at=OBSERVED + 120, bid="98.01", ask="98.02", bqty="0.1"),
    )
    fixture = make_fixture(
        tmp_path,
        request=request,
        initial_aqty="0.2",
        extra_values=tuple(TapeInput(i + 4, f) for i, f in enumerate(stop_frames)),
    )
    runner, hypothesis = fixture["portfolio"], fixture["hypothesis"]
    receipt = fixture["receipts"]["arm"]
    head = hypothesis.snapshot().head_sha256
    for item in runner.binding.inputs[:3]:
        value = item.value
        at = value.persisted_at_ms if isinstance(value, AcceptedBookFrame) else value.available_at_ms
        runner.ingest(global_sequence=item.global_sequence, now_ms=at)
    assert receipt.evaluation.state == "CONSUMED"
    assert receipt.evaluation.candidate is not None
    assert receipt.evaluation.candidate.decision_ts_ms == OBSERVED
    assert receipt.evaluation.candidate.decision_ts_ms != START
    assert intake(runner, hypothesis, receipt, head).outcome["status"] == "PENDING"
    runner.advance_to(now_ms=OBSERVED + 42, event_id="entry-arrival")
    assert account(runner).positions[0].quantity == D("0.2")
    assert account(runner).reservations[0].terminal == "PARTIAL"

    runner = reopen(fixture, runner)
    before = runner.snapshot().version
    assert intake(runner, hypothesis, receipt, head).replayed
    assert runner.advance_to(now_ms=OBSERVED + 42, event_id="entry-arrival").replayed
    assert runner.snapshot().version == before

    for seq in (4, 5, 6):
        frame = runner.binding.inputs[seq - 1].value
        runner.ingest(global_sequence=seq, now_ms=frame.persisted_at_ms)
        runner.advance_to(now_ms=frame.persisted_at_ms + 2, event_id=f"protective-{seq}")
        if seq == 4:
            assert account(runner).positions[0].quantity == D("0.1")
            assert account(runner).protective_exit_pending
        if seq == 5:
            assert account(runner).positions[0].quantity == D("0.1")
    assert not account(runner).positions
    assert not account(runner).protective_exit_pending
    safe_close(runner)


def test_v3_intake_rejects_forged_arm_and_wrong_head_without_mutation(tmp_path, request):
    fixture = make_fixture(tmp_path, request=request)
    runner, hypothesis = fixture["portfolio"], fixture["hypothesis"]
    ingest_all(runner)
    receipt = fixture["receipts"]["arm"]
    head = hypothesis.snapshot().head_sha256
    before = runner.snapshot()
    with pytest.raises(SimInputError, match="arm mismatch"):
        intake(runner, hypothesis, replace(receipt, arm_id="forged-arm"), head)
    with pytest.raises(SimInputError, match="head mismatch"):
        intake(runner, hypothesis, receipt, "f" * 64)
    assert runner.snapshot() == before
    safe_close(runner)


@pytest.mark.parametrize("foreign", ["journal", "receipt"])
def test_v3_portfolio_rejects_real_v2_journal_or_receipt(tmp_path, request, foreign):
    fixture = make_fixture(tmp_path, request=request)
    runner, v3_journal = fixture["portfolio"], fixture["hypothesis"]
    ingest_all(runner)
    v3_receipt = fixture["receipts"]["arm"]
    v2_journal, v2_receipt = v2_registration(tmp_path)
    before = runner.snapshot()
    journal = v2_journal if foreign == "journal" else v3_journal
    receipt = v3_receipt if foreign == "journal" else v2_receipt
    with pytest.raises(SimInputError, match="original typed evidence"):
        intake(runner, journal, receipt, v3_journal.snapshot().head_sha256)
    assert runner.snapshot() == before
    safe_close(runner)


def test_v3_intake_requires_originals_for_earlier_waiting_prefix_before_trigger(tmp_path, request):
    arm_policy = policy()
    parent = plan(arm_policy=arm_policy)
    seal = JournalSealV3("prefix-fixture", START - 1, ISSUE_SHA, (JournalArmV3("arm", arm_policy),), 4)
    hypothesis = HypothesisJournalV3.create(tmp_path / "prefix-hypotheses.research.sqlite3", seal)
    hypothesis.register("arm", parent)

    waiting = candle(START, high=101.0, low=99.0, close=100.0)
    waiting_evidence = evidence(waiting)
    waiting_observation = HypothesisObservation(
        ScenarioObservation(waiting, START + MINUTE + 100, (waiting_evidence,)), None
    )
    hypothesis.append(
        parent.template.intent_id,
        MatchedObservationV3(
            waiting_observation,
            (
                ArmReviewReceiptV3(
                    "arm", waiting_observation.market.observed_ms, waiting_observation.market.observed_ms
                ),
            ),
        ),
    )

    later = candle(START + MINUTE, high=101.5, low=99.5, close=100.5)
    later_evidence = evidence(later)
    decision_ms = START + 2 * MINUTE + 200
    frame = book(at=decision_ms - 2)
    quote = EntryQuote(
        "quotes",
        "BTCUSDT",
        100.49,
        100.50,
        frame.exchange_at_ms,
        frame.received_at_ms,
        frame.persisted_at_ms,
        5_000,
        "TEST_FIXTURE",
    )
    later_observation = HypothesisObservation(
        ScenarioObservation(later, decision_ms, (later_evidence,)), quote
    )
    receipt = hypothesis.append(
        parent.template.intent_id,
        MatchedObservationV3(
            later_observation,
            (ArmReviewReceiptV3("arm", decision_ms, decision_ms),),
        ),
    )[0]
    assert receipt.evaluation.state == "CONSUMED" and receipt.evaluation.candidate is not None

    anchor_receipt = parent.creation_evidence[0]
    anchor_record = retained(parent.anchor, anchor_receipt, START + 10_010)
    later_record = retained(later, later_evidence, decision_ms)
    # The earlier WAITING candle is deliberately absent from the caller's retained originals.
    originals = CandleOriginalsV3((anchor_record, later_record))
    binding = TapeBinding(
        "fixture-source",
        "fixture-tape",
        "fixture-epoch",
        "quotes",
        "TEST_FIXTURE",
        (
            TapeInput(1, candle_input(anchor_record)),
            TapeInput(2, frame),
            TapeInput(3, candle_input(later_record)),
        ),
    )
    models = {
        symbol: FillAssumptions(
            latency_ms=2,
            maximum_book_age_ms=60_000,
            maximum_frame_latency_ms=5_000,
            depth_participation_fraction=D(1),
            adverse_slippage_bps=D(0),
            taker_fee_bps=D(10),
            price_tick=D("0.01"),
            quantity_step=D("0.001"),
        )
        for symbol in UNIVERSE
    }
    rules = {symbol: SymbolRules(symbol, D("0.01"), D("0.001"), D("100000")) for symbol in UNIVERSE}
    schedule = FundingSchedule("funding", "TEST_FIXTURE", (), ISSUE_SHA)
    runner = ContinuousSimPortfolio.create(
        tmp_path / "prefix-portfolio.sqlite3",
        campaign_id="prefix-campaign",
        arm_id="arm",
        binding=binding,
        models=models,
        rules=rules,
        funding_schedule=schedule,
        minutes=(START + 2 * MINUTE,),
        initial_equity=D("1000"),
        hypothesis_seal_sha256=hypothesis.snapshot().seal_sha256,
        hypothesis_contract="V3",
        candle_originals=originals,
        allowed_origins=("TECHNICAL",),
    )
    request.addfinalizer(lambda: safe_close(runner))
    ingest_all(runner)
    before = runner.snapshot()
    with pytest.raises(ValueError, match="not retained originals"):
        intake(runner, hypothesis, receipt, hypothesis.snapshot().head_sha256, at=decision_ms + 40)
    assert runner.snapshot() == before
    safe_close(runner)


def test_context_anchor_must_be_available_at_actual_proposal_request(tmp_path, request):
    context = context_plan(policy())
    request_ms = context.creation_assessment.actual_requested_ms
    fixture = make_fixture(
        tmp_path,
        request=request,
        plans={"arm": context},
        anchor_available=request_ms + 1,
        allowed_origins=("CONTEXT_PROPOSAL",),
    )
    runner, hypothesis = fixture["portfolio"], fixture["hypothesis"]
    ingest_all(runner)
    receipt = fixture["receipts"]["arm"]
    before = runner.snapshot()
    with pytest.raises(ValueError, match="not yet available"):
        intake(runner, hypothesis, receipt, hypothesis.snapshot().head_sha256)
    assert runner.snapshot() == before
    safe_close(runner)


def test_trigger_original_must_be_ready_at_shared_observation_not_later_arm_decision(tmp_path, request):
    fixture = make_fixture(
        tmp_path,
        request=request,
        require_review=True,
        review="ALLOW",
        trigger_available=OBSERVED + 2,
    )
    runner, hypothesis = fixture["portfolio"], fixture["hypothesis"]
    ingest_all(runner)
    receipt = fixture["receipts"]["arm"]
    assert receipt.evaluation.observed_ms == OBSERVED + 40
    assert receipt.evaluation.candidate is not None
    before = runner.snapshot()
    with pytest.raises(ValueError, match="not yet available"):
        intake(runner, hypothesis, receipt, hypothesis.snapshot().head_sha256)
    assert runner.snapshot() == before
    safe_close(runner)


def test_old_exact_receipt_is_idempotent_after_valid_terminal_next_minute_append(tmp_path, request):
    next_candle = candle(START + MINUTE, high=101.0, low=100.0, close=100.4)
    next_evidence = evidence(next_candle)
    next_record = retained(next_candle, next_evidence, START + 2 * MINUTE + 200)
    fixture = make_fixture(
        tmp_path,
        request=request,
        minutes=(START + MINUTE, START + 2 * MINUTE),
        extra_records=(next_record,),
    )
    runner, hypothesis = fixture["portfolio"], fixture["hypothesis"]
    for item in runner.binding.inputs[:3]:
        value = item.value
        at = value.persisted_at_ms if isinstance(value, AcceptedBookFrame) else value.available_at_ms
        runner.ingest(global_sequence=item.global_sequence, now_ms=at)
    receipt = fixture["receipts"]["arm"]
    old_head = hypothesis.snapshot().head_sha256
    intake(runner, hypothesis, receipt, old_head)
    future_input = runner.binding.inputs[3]
    runner.ingest(global_sequence=4, now_ms=future_input.value.available_at_ms)
    later = HypothesisObservation(
        ScenarioObservation(next_candle, next_record.available_at_ms, (next_evidence,)), None
    )
    terminal_batch = MatchedObservationV3(
        later,
        (ArmReviewReceiptV3("arm", next_record.available_at_ms, next_record.available_at_ms),),
    )
    hypothesis.append(receipt.parent_id, terminal_batch)
    assert hypothesis.snapshot().head_sha256 != old_head
    before = runner.snapshot().version
    assert intake(runner, hypothesis, receipt, old_head).replayed
    assert runner.snapshot().version == before
    safe_close(runner)


@pytest.mark.parametrize("case", ["missing-quote", "missing-review"])
def test_unavailable_first_decision_is_consumed_and_finishes_null_after_restart(tmp_path, request, case):
    fixture = make_fixture(
        tmp_path,
        request=request,
        require_review=case == "missing-review",
        quote=case != "missing-quote",
    )
    runner, hypothesis = fixture["portfolio"], fixture["hypothesis"]
    ingest_all(runner)
    receipt = fixture["receipts"]["arm"]
    assert receipt.evaluation.state == "CONSUMED"
    assert receipt.evaluation.candidate is None
    assert receipt.evaluation.coverage == "UNAVAILABLE"
    assert receipt.evaluation.reason in {"FRESH_ENTRY_QUOTE_UNAVAILABLE", "REVIEW_MISSING_DEFER"}
    head = hypothesis.snapshot().head_sha256
    result = intake(runner, hypothesis, receipt, head)
    assert result.outcome["status"] == "REFUSED"
    assert result.outcome["reason"] == receipt.evaluation.reason
    runner = reopen(fixture, runner)
    assert intake(runner, hypothesis, receipt, head).replayed
    minute = START + MINUTE
    for symbol in UNIVERSE:
        key = f"{symbol}:{minute}"
        if key not in runner.snapshot().state["slots"]:
            runner.record_slot(
                symbol=symbol, minute=minute, status="QUIET", source_sha256=SOURCE_SHA, at_ms=minute + MINUTE
            )
    final = runner.finish(now_ms=minute + MINUTE, event_id="finish-unavailable").outcome
    assert final["status"] == "UNRESOLVED"
    assert final["net_return"] is None
    assert final["denominator_cells"] == len(UNIVERSE)
    assert final["unavailable_slots"] == [f"BTCUSDT:{minute}"]
    safe_close(runner)


def test_available_veto_is_known_refusal_and_can_finish_complete(tmp_path, request):
    fixture = make_fixture(tmp_path, request=request, require_review=True, review="VETO")
    runner, hypothesis = fixture["portfolio"], fixture["hypothesis"]
    ingest_all(runner)
    receipt = fixture["receipts"]["arm"]
    assert receipt.evaluation.state == "CONSUMED"
    assert receipt.evaluation.reason == "REVIEW_VETO"
    assert receipt.evaluation.coverage == "AVAILABLE"
    assert receipt.evaluation.candidate is None
    head = hypothesis.snapshot().head_sha256
    refused = intake(runner, hypothesis, receipt, head)
    assert refused.outcome["status"] == "REFUSED"
    minute = START + MINUTE
    for symbol in UNIVERSE:
        key = f"{symbol}:{minute}"
        if key not in runner.snapshot().state["slots"]:
            runner.record_slot(
                symbol=symbol, minute=minute, status="QUIET", source_sha256=SOURCE_SHA, at_ms=minute + MINUTE
            )
    final = runner.finish(now_ms=minute + MINUTE, event_id="finish-veto").outcome
    assert final["status"] == "COMPLETE"
    assert final["net_return"] is not None
    assert final["denominator_cells"] == len(UNIVERSE)
    safe_close(runner)


def test_sealed_origin_routing_rejects_context_proposal_for_strategy_only_runner(tmp_path, request):
    reviewed_policy = policy()
    context = context_plan(reviewed_policy)
    fixture = make_fixture(tmp_path, request=request, plans={"arm": context})
    runner, hypothesis = fixture["portfolio"], fixture["hypothesis"]
    ingest_all(runner)
    receipt = fixture["receipts"]["arm"]
    assert receipt.evaluation.state == "CONSUMED"
    with pytest.raises(SimInputError, match="routing permission"):
        intake(runner, hypothesis, receipt, hypothesis.snapshot().head_sha256)
    assert not runner.snapshot().state["parents"]
    safe_close(runner)


def test_context_proposal_can_route_when_explicitly_presealed(tmp_path, request):
    context = context_plan(policy())
    fixture = make_fixture(
        tmp_path,
        request=request,
        plans={"arm": context},
        allowed_origins=("CONTEXT_PROPOSAL",),
    )
    runner, hypothesis = fixture["portfolio"], fixture["hypothesis"]
    ingest_all(runner)
    receipt = fixture["receipts"]["arm"]
    assert receipt.evaluation.candidate is not None
    assert receipt.evaluation.coverage == "AVAILABLE"
    result = intake(runner, hypothesis, receipt, hypothesis.snapshot().head_sha256)
    assert result.outcome["status"] == "PENDING"
    parent = runner.snapshot().state["parents"][receipt.parent_id]
    assert parent["candidate"]["exact_original_sha256"] == digest(asdict(receipt.evaluation.candidate))
    safe_close(runner)


def test_reopen_rejects_changed_full_candle_provenance_and_binding(tmp_path, request):
    fixture = make_fixture(tmp_path, request=request)
    runner = fixture["portfolio"]
    snapshot = runner.snapshot()
    identity = runner.journal.identity
    safe_close(runner)
    changed_binding_input = replace(
        fixture["binding"].inputs[2].value,
        source_payload_sha256="f" * 64,
    )
    changed_binding = replace(
        fixture["binding"],
        inputs=(
            fixture["binding"].inputs[0],
            fixture["binding"].inputs[1],
            TapeInput(3, changed_binding_input),
        ),
    )
    with pytest.raises(ValueError, match="retained original receipt"):
        ContinuousSimPortfolio.open(
            runner.path,
            identity=identity,
            binding=changed_binding,
            models=fixture["models"],
            rules=fixture["rules"],
            funding_schedule=fixture["schedule"],
            config=snapshot.state["config"],
            expected_head_sha256=snapshot.head_hash,
            candle_originals=fixture["originals"],
        )

    original = fixture["originals"].records[1]
    changed_bar = replace(original.candle, high=102.0)
    with pytest.raises(ValueError, match="exact closed candle"):
        RetainedCandleV3(changed_bar, original.evidence, original.available_at_ms, original.evidence_kind)

    changed_receipt = replace(original.evidence, source_id="rewritten-bars")
    changed_original = RetainedCandleV3(
        original.candle, changed_receipt, original.available_at_ms, original.evidence_kind
    )
    changed_originals = CandleOriginalsV3((fixture["originals"].records[0], changed_original))
    with pytest.raises((SimInputError, ValueError), match="original|provenance|receipt|drift"):
        ContinuousSimPortfolio.open(
            runner.path,
            identity=identity,
            binding=fixture["binding"],
            models=fixture["models"],
            rules=fixture["rules"],
            funding_schedule=fixture["schedule"],
            config=snapshot.state["config"],
            expected_head_sha256=snapshot.head_hash,
            candle_originals=changed_originals,
        )


def test_same_journal_and_sources_keep_account_state_arm_local(tmp_path, request):
    fixture = make_fixture(tmp_path, request=request, arms=("arm-a", "arm-b"))
    # Each portfolio is a separate ledger over the same exact external source/journal bytes.
    runners = {"arm-a": fixture["portfolio"]}
    for arm in ("arm-a", "arm-b"):
        if arm == "arm-a":
            runner = runners[arm]
        else:
            runner = ContinuousSimPortfolio.create(
                tmp_path / f"{arm}.sqlite3",
                campaign_id="shared-fixture-campaign",
                arm_id=arm,
                binding=fixture["binding"],
                models=fixture["models"],
                rules=fixture["rules"],
                funding_schedule=fixture["schedule"],
                minutes=(START + MINUTE,),
                initial_equity=D("1000"),
                hypothesis_seal_sha256=fixture["hypothesis"].snapshot().seal_sha256,
                hypothesis_contract="V3",
                candle_originals=fixture["originals"],
                allowed_origins=("TECHNICAL",),
            )
            request.addfinalizer(lambda runner=runner: safe_close(runner))
            runners[arm] = runner
        ingest_all(runner)
        receipt = fixture["receipts"][arm]
        intake(runner, fixture["hypothesis"], receipt, fixture["hypothesis"].snapshot().head_sha256)
    assert account(runners["arm-a"]) == account(runners["arm-b"])
    for arm, runner in runners.items():
        runner.advance_to(now_ms=OBSERVED + 42, event_id=f"entries-{arm}")
        runner.advance_to(now_ms=OBSERVED + 50, event_id=f"equal-clock-{arm}")
    assert account(runners["arm-a"]) == account(runners["arm-b"])
    unaffected_arm = runners["arm-b"].snapshot()
    runners["arm-a"].debit_service(cost_id="one-arm-only", amount=D("1"), at_ms=OBSERVED + 50)
    assert account(runners["arm-a"]).cash == account(runners["arm-b"]).cash - D("1")
    # Arm-bound issue receipts intentionally differ. A command on one arm must
    # instead leave every byte and journal version of the other arm unchanged.
    assert runners["arm-b"].snapshot() == unaffected_arm
    for runner in runners.values():
        safe_close(runner)
