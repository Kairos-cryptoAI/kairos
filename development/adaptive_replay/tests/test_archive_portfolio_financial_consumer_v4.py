"""Offline original-packet/S5 ENTRY wiring, never an historical model run."""

import hashlib
import importlib.machinery
import importlib.util
import sys
from dataclasses import fields, replace
from decimal import Decimal as D
from pathlib import Path

import pytest
from kairos_core.enums import Side

from adaptive_replay import archive_hypothesis_journal_v3 as store
from adaptive_replay import archive_hypothesis_v3 as hypothesis
from adaptive_replay import archive_portfolio_financial_consumer_v3 as base
from adaptive_replay import archive_portfolio_financial_consumer_v4 as module
from adaptive_replay.archive_market_clock_v3 import archive_quote_v3
from adaptive_replay.archive_portfolio_stream_v3 import (
    TIE_RULE,
    ArchivePortfolioLimitsV3,
    ArchivePortfolioSealV3,
    ArchivePortfolioStreamV3,
)
from adaptive_replay.bookticker_archive_stream_v3 import _canonical, _day_start_ms
from adaptive_replay.inputs import UNIVERSE
from adaptive_replay.scenarios import MINUTE
from adaptive_replay.sim_account_core_codec_v3 import decode_account_core
from adaptive_replay.sim_financial_journal_v3 import DEFAULT_LIMITS

from . import test_archive_hypothesis_v3 as r2
from . import test_archive_portfolio_financial_consumer_v3 as q5

OPENED = []


@pytest.fixture(autouse=True)
def close_owned_handles():
    OPENED.clear()
    try:
        yield
    finally:
        for journal in reversed(OPENED):
            journal.close()
        OPENED.clear()
        q5.OPENED.clear()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _prefix(seal, through):
    stream = ArchivePortfolioStreamV3(seal, expected_seal_sha256=seal.sha256)
    while (operation := stream.prepare_next()) is not None:
        if operation.at_ms > through:
            break
        stream.acknowledge(operation)
    return stream.checkpoint()


def _packet(completion, context):
    config = _canonical(
        {
            "provider": "OPENAI",
            "model": "explicit-engineering-fixture",
            "model_path": ["model"],
            "context_path": ["context"],
            "context_prefix": "",
            "context_suffix": "",
            "decision_path": ["decision"],
            "decision_json_key": None,
            "parser": "BOUNDED_JSON_PATH_V4",
        }
    )
    attempt = completion.attempt
    request = (
        None
        if attempt.status == "NOT_CALLED"
        else _canonical(
            {
                "model": "explicit-engineering-fixture",
                "context": context.decode("utf-8"),
            }
        )
    )
    response = (
        None
        if attempt.status == "NOT_CALLED"
        else _canonical(
            {
                "decision": completion.decision,
                "status": attempt.status,
            }
        )
    )
    expense = _canonical(
        {
            "attempt_id": attempt.attempt_id,
            "captured_wall_ms": completion.captured_wall_ms,
            "currency": "USD",
            "status": attempt.status,
            "evidence_kind": attempt.evidence_kind,
            "cost_usd": None if attempt.cost_usd is None else str(D(str(attempt.cost_usd))),
        }
    )
    receipt = _canonical(
        {
            "schema": module.PACKET_SCHEMA,
            "clock_domain": "ACTUAL_WALL_UTC",
            "provider": "OPENAI",
            "attempt_id": attempt.attempt_id,
            "requested_wall_ms": attempt.requested_ms,
            "response_wall_ms": completion.response_wall_ms,
            "completed_wall_ms": completion.completed_wall_ms,
            "captured_wall_ms": completion.captured_wall_ms,
            "status": attempt.status,
            "role": completion.role,
            "decision": completion.decision,
            "evidence_kind": attempt.evidence_kind,
            "no_call_reason": attempt.no_call_reason,
            "context_sha256": _sha(context),
            "config_sha256": _sha(config),
            "request_body_sha256": None if request is None else _sha(request),
            "raw_response_sha256": None if response is None else _sha(response),
            "expense_record_sha256": _sha(expense),
        }
    )
    completed = replace(
        completion,
        original_receipt_sha256=_sha(receipt),
        model_config_sha256=_sha(config),
        response_sha256=_sha(response) if attempt.status == "COMPLETE" else None,
    )
    packet = module.ArchiveModelOriginalPacketV4(
        "TEST_FIXTURE",
        request,
        context,
        config,
        response,
        receipt,
        expense,
    )
    packet.verify(completed)
    return completed, packet


def _context(observation):
    return _canonical(
        hypothesis._plain(
            {
                "schema": hypothesis.SCHEMA,
                "candle": hypothesis.candle_payload(observation.candle),
                "sources": observation.sources,
                "quote": observation.quote,
            }
        )
    )


def _routing_fixture(tmp_path, arm, *, conflict=False, technical_disposition="ALLOW"):
    """Actual typed first-trigger originals; no altered issued receipt/candidate."""
    review = arm in {"context_review", "combined"}
    policy = r2.policy(review)
    sources = []
    first_clock = r2.CUT + MINUTE + 11
    for symbol in sorted(UNIVERSE):
        original, _ = q5._source(
            tmp_path / symbol,
            symbol,
            "2024-01-08",
            [
                (first_clock, "99.49" if conflict else "100.49", "99.50" if conflict else "100.50"),
                (first_clock + MINUTE, "100.49", "100.50"),
            ],
            clock_policy=policy.quote_clock,
        )
        sources.append(original)
    market = ArchivePortfolioSealV3(
        tuple(sources),
        tuple(sorted(UNIVERSE)),
        ("2024-01-08",),
        (),
        TIE_RULE,
        q5.ORDER,
        ArchivePortfolioLimitsV3(max_batch_rows=1, max_batch_bytes=200, prefetch_rows=1),
    )
    plans, packets = [], []
    if arm != "independent_proposals":
        plans.append(r2.plan(review=review))
    if arm in {"independent_proposals", "combined"}:
        p = r2.plan(Side.SHORT if conflict else Side.LONG, origin="CONTEXT_PROPOSAL", review=review)
        parent = replace(
            p.template, metadata=(*p.template.metadata, ("fixture_original_origin", "CONTEXT_PROPOSAL"))
        )
        context = _canonical(
            hypothesis._plain(
                {
                    "schema": hypothesis.SCHEMA,
                    "original_parent": parent,
                    "anchor": hypothesis.candle_payload(p.anchor),
                    "sources": p.creation_sources,
                    "source_set": p.source_set_sha256,
                    "context": p.context_sha256,
                }
            )
        )
        completion = r2.completion(
            _sha(context), role="PROPOSAL", decision=parent.side.value, request=r2.WALL + 10
        )
        completion, packet = _packet(completion, context)
        plans.append(replace(p, template=parent, proposal=completion))
        packets.append((completion, packet))
    observations = []
    for p in plans:
        minutes = (r2.CUT, r2.CUT + MINUTE) if conflict and p.origin == "TECHNICAL" else (r2.CUT,)
        for open_ms in minutes:
            close = 99.5 if conflict and open_ms == r2.CUT else 100.5
            bar = r2.candle(open_ms, close)
            row_index = (open_ms - r2.CUT) // MINUTE
            source = next(s for s in sources if s.source_key == "BTCUSDT:2024-01-08")
            row = source.index.cursor(clock=policy.quote_clock).lookup_row(row_index)
            quote = archive_quote_v3(
                row, clock=policy.quote_clock, source_manifest_sha256=source.index.source_manifest_sha256
            )
            proof = hypothesis.ArchiveQuoteProofV3(
                policy.quote_source_id,
                row,
                quote,
                source.index.manifest_sha256,
                policy.quote_clock,
                _prefix(market, quote.modeled_available_at_ms),
            )
            evidence = tuple(
                sorted(
                    (
                        r2.source(bar),
                        *(
                            r2.source(bar, kind=k, source_id=s)
                            for k, s in p.required_sources
                            if k != "MARKET"
                        ),
                    ),
                    key=lambda e: (e.kind, e.source_id),
                )
            )
            obs = hypothesis.ArchiveHypothesisObservationV3(
                bar, quote.modeled_available_at_ms, evidence, proof
            )
            confirming = not (conflict and p.origin == "TECHNICAL" and open_ms == r2.CUT)
            if review and confirming:
                disposition = technical_disposition if p.origin == "TECHNICAL" else "ALLOW"
                completion = r2.completion(obs.context_sha256, decision=disposition)
                completion, packet = _packet(completion, _context(obs))
                obs = replace(
                    obs,
                    decision_history_ms=completion.available_at(obs.input_ready_history_ms, policy),
                    review=hypothesis.ArchiveReviewV3(
                        p.scenario_id, p.template.side, obs.context_sha256, completion
                    ),
                )
                packets.append((completion, packet))
            observations.append((p, obs))
    journal = store.ArchiveHypothesisJournalV3.create(
        tmp_path / "routing-producer.sqlite3",
        producer_id="original-routing-producer",
        arm_id=arm,
        plans=tuple(sorted(plans, key=lambda p: p.template.intent_id)),
        market_seal=market,
    )
    retained = {}
    try:
        for number, (p, obs) in enumerate(
            sorted(observations, key=lambda item: (item[1].decision_history_ms, item[0].origin))
        ):
            before = journal.checkpoint()
            prepared = journal.prepare_append(
                event_id=f"routing-original:{number}",
                parent_id=p.template.intent_id,
                observation=obs,
                decision_market_checkpoint=_prefix(market, obs.decision_history_ms),
                expected_checkpoint=before,
            )
            issued = journal.append(
                event_id=f"routing-original:{number}",
                parent_id=p.template.intent_id,
                observation=obs,
                decision_market_checkpoint=_prefix(market, obs.decision_history_ms),
                expected_checkpoint=before,
            )
            if issued.receipt.evaluation.state == "CONSUMED":
                retained[p.origin] = (p.template.intent_id, prepared.after)
        final = journal.checkpoint()
    finally:
        journal.close()
    refs = []
    for completion, packet in packets:
        path = tmp_path / f"packet-{completion.attempt.attempt_id.split(':')[-1]}.json"
        path.write_bytes(packet.bytes)
        refs.append(
            module.ArchivePacketReferenceV4(
                completion.attempt.attempt_id, str(path), _sha(packet.bytes), len(packet.bytes)
            )
        )
    profile = module.ArchiveResearchProfileV4(
        arm,
        r2.WALL + 1000,
        r2.WALL + 1001,
        "TEST_FIXTURE",
        "USD_ACCOUNT_UNIT_EQUIVALENCE_MODELED_1_TO_1",
        module.ArchiveProducerReferenceV4(str(tmp_path / "routing-producer.sqlite3"), final, market),
        tuple(sorted(refs, key=lambda p: p.attempt_id)),
    )
    issued_refs = {
        origin: module.issued_reference_v4(profile, parent_id=parent, issued_checkpoint=cp)
        for origin, (parent, cp) in retained.items()
    }
    return profile, issued_refs, tuple(q5._model(s) for s in sorted(UNIVERSE))


def _fixture(tmp_path, *, disposition="ALLOW", cost=0.01, midnight=False, create=True):
    tmp_path.mkdir(exist_ok=True)
    cut = _day_start_ms("2024-01-09") - MINUTE if midnight else r2.CUT
    p = r2.plan(review=True)
    parent = replace(
        p.template, decision_ts_ms=cut - 1, entry_eligible_ts_ms=cut, entry_expires_ts_ms=cut + MINUTE - 1
    )
    anchor = r2.candle(cut - MINUTE)
    p = replace(
        p, template=parent, anchor=anchor, origin_cut_history_ms=cut, creation_sources=(r2.source(anchor),)
    )
    day = "2024-01-09" if midnight else "2024-01-08"
    days = ("2024-01-08", "2024-01-09") if midnight else (day,)
    quote_clock = cut + MINUTE + 11
    sources = []
    for symbol in sorted(UNIVERSE):
        for source_day in days:
            if midnight and source_day == "2024-01-08":
                rows = [(cut - 10, "100.00", "100.01")]
            else:
                rows = [(quote_clock, "100.49", "100.50"), (quote_clock + MINUTE, "100.49", "100.50")]
                if symbol == "BTCUSDT":
                    rows.insert(1, (cut + MINUTE + 60, "97.00", "97.01"))
                if symbol == "ETHUSDT":
                    rows.insert(1, (quote_clock + 8, "100.48", "100.51"))
            original, _ = q5._source(
                tmp_path / f"{symbol}-{source_day}",
                symbol,
                source_day,
                rows,
                clock_policy=p.policy.quote_clock,
            )
            sources.append(original)
    market = ArchivePortfolioSealV3(
        tuple(sources),
        tuple(sorted(UNIVERSE)),
        days,
        (),
        TIE_RULE,
        q5.ORDER,
        ArchivePortfolioLimitsV3(max_batch_rows=1, max_batch_bytes=200, prefetch_rows=1),
    )
    bar = r2.candle(cut, 100.5)
    input_cp = _prefix(market, quote_clock + 5)
    original_source = next(s for s in sources if s.source_key == f"BTCUSDT:{day}")
    original = original_source.index.cursor(clock=p.policy.quote_clock).lookup_row(0)
    quote = archive_quote_v3(
        original,
        clock=p.policy.quote_clock,
        source_manifest_sha256=original_source.index.source_manifest_sha256,
    )
    proof = hypothesis.ArchiveQuoteProofV3(
        p.policy.quote_source_id,
        original,
        quote,
        original_source.index.manifest_sha256,
        p.policy.quote_clock,
        input_cp,
    )
    obs = hypothesis.ArchiveHypothesisObservationV3(
        bar, quote.modeled_available_at_ms, (r2.source(bar),), proof
    )
    comp = r2.completion(
        obs.context_sha256,
        decision=disposition,
        status="ERROR" if disposition == "ERROR" else "COMPLETE",
        cost=cost,
    )
    comp, packet = _packet(comp, _context(obs))
    obs = replace(
        obs,
        decision_history_ms=comp.available_at(obs.input_ready_history_ms, p.policy),
        review=hypothesis.ArchiveReviewV3(p.scenario_id, p.template.side, obs.context_sha256, comp),
    )
    decision_cp = _prefix(market, obs.decision_history_ms)
    producer = store.ArchiveHypothesisJournalV3.create(
        tmp_path / "producer.sqlite3",
        producer_id="original-producer",
        arm_id="context_review",
        plans=(p,),
        market_seal=market,
    )
    before = producer.checkpoint()
    prepared = producer.prepare_append(
        event_id="original-first-trigger",
        parent_id=p.template.intent_id,
        observation=obs,
        decision_market_checkpoint=decision_cp,
        expected_checkpoint=before,
    )
    producer.append(
        event_id="original-first-trigger",
        parent_id=p.template.intent_id,
        observation=obs,
        decision_market_checkpoint=decision_cp,
        expected_checkpoint=before,
    )
    assert producer.checkpoint() == prepared.after
    producer.close()
    packet_path = tmp_path / "original-model-packet.json"
    packet_path.write_bytes(packet.bytes)
    packet_ref = module.ArchivePacketReferenceV4(
        comp.attempt.attempt_id, str(packet_path), _sha(packet.bytes), len(packet.bytes)
    )
    profile = module.ArchiveResearchProfileV4(
        "context_review",
        r2.WALL + 1000,
        r2.WALL + 1001,
        "TEST_FIXTURE",
        "USD_ACCOUNT_UNIT_EQUIVALENCE_MODELED_1_TO_1",
        module.ArchiveProducerReferenceV4(str(tmp_path / "producer.sqlite3"), prepared.after, market),
        (packet_ref,),
    )
    reference = module.issued_reference_v4(
        profile, parent_id=p.template.intent_id, issued_checkpoint=prepared.after
    )
    if not create:
        return profile, reference, packet, comp, obs
    entry = module.journal_entry_action_v4(profile, reference)
    due = cut + MINUTE + 35
    known = q5.ArchiveFundingReceiptV3(
        due, due + 1, cut + MINUTE + 75, "KNOWN", D("0.001"), D(100), "f" * 64, "e" * 64
    )
    calendars = tuple(
        (
            s,
            q5.ArchiveFundingCalendarV3(
                "TEST_FIXTURE",
                "a" * 64,
                1 if s == "BTCUSDT" else 0,
                (due,) if s == "BTCUSDT" else (),
                (known,) if s == "BTCUSDT" else (),
            ),
        )
        for s in sorted(UNIVERSE)
    )
    end = _day_start_ms(days[-1]) + 86400000
    actions = (
        *module.model_expense_actions_v4(profile),
        entry,
        q5._action("fund-due", due, base.ArchiveFundingDueV3("BTCUSDT", due)),
        q5._action(
            "fund-known", known.modeled_available_at_ms, base.ArchiveFundingDeliveryV3("BTCUSDT", known)
        ),
        q5._action("end", end, base.ArchiveAdvanceV3("RETAINED_END")),
    )
    actions = tuple(sorted(actions, key=lambda a: (a.at_ms, q5.ORDER.index(a.kind), a.boundary_id)))
    financial = replace(market, boundaries=tuple(a.boundary for a in actions))
    consumer = module.ArchivePortfolioFinancialConsumerV4.create(
        tmp_path / "financial.sqlite3",
        campaign_id="v4-source-engineering",
        owner_id="owner",
        account_id="one-shared-account",
        seal=financial,
        models=tuple(q5._model(s) for s in sorted(UNIVERSE)),
        calendars=calendars,
        actions=actions,
        initial_account=q5.api.new_account(D(10000), q5.POLICY),
        entry_start_ms=_day_start_ms(days[0]),
        entry_end_ms=end,
        retained_end_ms=end,
        expected_cost_ids=(comp.attempt.attempt_id,),
        maximum_exit_attempts=3,
        storage_bounds=dict(DEFAULT_LIMITS),
        profile=profile,
    )
    OPENED.append(consumer.journal)
    return consumer, profile, reference, packet, comp, obs


@pytest.mark.parametrize("midnight", [False, True])
def test_original_s5_entry_partial_natural_stop_late_funding_cost_and_restart(tmp_path, midnight):
    consumer, profile, reference, _, comp, obs = _fixture(tmp_path, midnight=midnight)
    count = 0
    while consumer.consume_next() is not None:
        count += 1
        if count == 8:
            cp = consumer.journal.checkpoint()
            reopened = module.ArchivePortfolioFinancialConsumerV4.open(
                consumer.journal.path,
                identity=consumer.journal.identity,
                expected_checkpoint=cp,
                seal=consumer.seal,
                models=consumer.models,
                calendars=consumer.calendars,
                actions=consumer.actions,
                config=consumer.config,
            )
            OPENED.append(reopened.journal)
            consumer = reopened
    state = consumer.journal.snapshot().state
    core = decode_account_core(state["account"])[0]
    parent = next(iter(state["parents"].values()))
    assert parent["entry_status"] == "PARTIAL" and parent["exit_reason"] == "STOP"
    assert (
        parent["closed_at_ms"] is not None
        and not core.positions
        and not any(r.terminal == "OPEN" for r in core.reservations)
    )
    assert state["service_costs"][comp.attempt.attempt_id] == str(D(str(comp.attempt.cost_usd)))
    assert next(iter(state["funding"].values()))["status"] == "KNOWN"
    assert core.cash < D(10000) and state["cursor"] == sum(s.index.row_count for s in consumer.seal.sources)
    assert state["native_mark_count"] == state["cursor"]
    consumed = state["archive_consumed_parents"][reference.parent_id]
    assert consumed["original_quote_input_prefix_sha256"] == hypothesis.digest(obs.quote.source_prefix)
    assert consumed["decision_market_prefix_sha256"] != consumed["original_quote_input_prefix_sha256"]
    assert consumer.config["source_admission"] is False and consumer.config["trading_authority"] == "NONE"
    events = tuple(consumer.journal.native_events())
    kinds = [e.payload[0] for e in events]
    assert kinds.count("MARK") == state["cursor"] and "RESERVE" in kinds and "SERVICE" in kinds
    assert profile.document["evidence_kind"] == "TEST_FIXTURE"


@pytest.mark.parametrize(
    "disposition,cost", [("VETO", 0.01), ("DEFER", 0.01), ("ERROR", 0.01), ("ALLOW", None)]
)
def test_first_veto_defer_error_unknown_expense_never_promotes_to_entry(tmp_path, disposition, cost):
    profile, reference, packet, comp, _ = _fixture(tmp_path, disposition=disposition, cost=cost, create=False)
    assert packet.verify(comp) is None if cost is None else packet.verify(comp) == D(str(cost))
    with pytest.raises(ValueError, match="no usable"):
        module.journal_entry_action_v4(profile, reference)


@pytest.mark.parametrize(
    "field", ["context_body", "request_body", "raw_response", "wall_receipt", "expense_record", "config_body"]
)
def test_original_packet_mutation_never_rebinds_typed_completion(tmp_path, field):
    _, _, packet, comp, _ = _fixture(tmp_path, create=False)
    original = getattr(packet, field)
    altered = original + b" "
    with pytest.raises((ValueError, TypeError)):
        replace(packet, **{field: altered}).verify(comp)


def test_entry_same_clock_requires_original_cost_already_debited_and_rolls_back(tmp_path):
    consumer, _, _, _, _, _ = _fixture(tmp_path)
    while True:
        prepared = consumer.prepare_next()
        if (
            prepared.operation.kind != "SOURCE_BATCH"
            and type(consumer._action[prepared.operation.boundary.boundary_id])
            is module.ArchiveJournalEntryActionV4
        ):
            break
        consumer.commit_prepared(prepared)
    before = consumer.journal.checkpoint()
    state = consumer.journal.snapshot().state
    state["service_costs"].clear()
    with pytest.raises(ValueError, match="UNRESOLVED_OR_UNDEBITED"):
        consumer._entry_view(state, consumer._action[prepared.operation.boundary.boundary_id])
    native_before = tuple(consumer.journal.native_events())

    def fault():
        raise RuntimeError("injected after original proof/native reserve staging")

    consumer.journal._before_commit = fault
    with pytest.raises(RuntimeError, match="injected"):
        consumer.commit_prepared(prepared)
    assert consumer.journal.checkpoint() == before
    assert tuple(consumer.journal.native_events()) == native_before
    assert "archive_consumed_parents" not in consumer.journal.snapshot().state


def test_v4_never_accepts_fixture_entry_or_renewed_actual_clock(tmp_path):
    consumer, profile, reference, _, _, obs = _fixture(tmp_path)
    action = module.journal_entry_action_v4(profile, reference)
    with pytest.raises(ValueError, match="modeled slot"):
        module._execution_view(profile, replace(action, at_ms=obs.decision_history_ms + 1), consumer.models)
    with pytest.raises(ValueError, match="FixtureEntry"):
        module.ArchivePortfolioFinancialConsumerV4._action_entries(
            (q5._action("fake", action.at_ms, q5._entry("fixture", "BTCUSDT")),),
            seal=replace(
                consumer.seal,
                boundaries=(q5._action("fake", action.at_ms, q5._entry("fixture", "BTCUSDT")).boundary,),
            ),
            fixture=True,
            models=consumer.models,
            profile=profile,
        )


@pytest.mark.parametrize(
    "arm,origin", [("strategy_only", "TECHNICAL"), ("independent_proposals", "CONTEXT_PROPOSAL")]
)
def test_both_unreviewed_original_origins_connect_without_fixture_entry_conversion(tmp_path, arm, origin):
    profile, refs, models = _routing_fixture(tmp_path, arm)
    action = module.journal_entry_action_v4(profile, refs[origin])
    bundle, view = module._execution_view(profile, action, models)
    assert bundle.plan.origin == origin and not bundle.plan.policy.require_review
    assert type(view) is not base.ArchiveFixtureEntryV3
    assert view.original_parent_id == bundle.plan.template.intent_id
    assert view.expires_at_ms == bundle.issued.receipt.evaluation.candidate.entry_expires_ts_ms
    assert len(module.model_expense_actions_v4(profile)) == (origin == "CONTEXT_PROPOSAL")


def test_combined_exact_original_peers_technical_priority_and_no_implicit_absence(tmp_path):
    profile, refs, models = _routing_fixture(tmp_path, "combined")
    technical = module.journal_entry_action_v4(profile, refs["TECHNICAL"], peers=(refs["CONTEXT_PROPOSAL"],))
    bundle, view = module._execution_view(profile, technical, models)
    assert view.original_parent_id == bundle.plan.template.intent_id and bundle.plan.origin == "TECHNICAL"
    with pytest.raises(ValueError, match="peer roster incomplete"):
        module._execution_view(profile, module.journal_entry_action_v4(profile, refs["TECHNICAL"]), models)
    context = module.journal_entry_action_v4(profile, refs["CONTEXT_PROPOSAL"], peers=(refs["TECHNICAL"],))
    with pytest.raises(ValueError, match="TECHNICAL_PRIORITY"):
        module._execution_view(profile, context, models)


@pytest.mark.parametrize("veto", ["VETO", "DEFER"])
def test_combined_technical_first_veto_cannot_fallback_to_allowed_proposal(tmp_path, veto):
    profile, refs, models = _routing_fixture(tmp_path, "combined", technical_disposition=veto)
    with pytest.raises(ValueError, match="no usable"):
        module.journal_entry_action_v4(profile, refs["TECHNICAL"])
    action = module.journal_entry_action_v4(profile, refs["CONTEXT_PROPOSAL"], peers=(refs["TECHNICAL"],))
    with pytest.raises(ValueError, match="TECHNICAL_PRIORITY"):
        module._execution_view(profile, action, models)


def test_combined_opposite_original_first_trigger_candidates_refuse_conflict(tmp_path):
    profile, refs, models = _routing_fixture(tmp_path, "combined", conflict=True)
    action = module.journal_entry_action_v4(profile, refs["TECHNICAL"], peers=(refs["CONTEXT_PROPOSAL"],))
    with pytest.raises(ValueError, match="ARBITRATION_CONFLICT_NO_ENTRY"):
        module._execution_view(profile, action, models)


def test_default_q5_full_financial_and_complete_native_stream_equals_archived_q5_reference(tmp_path):
    original_path = Path(__file__).resolve().parent / "fixtures" / "q5-archived-consumer.py.txt"
    expected = "e8b34996a1479eeb99c9a2457a5a3bc661bdce445d09be2031919c7009c629ef"
    assert _sha(original_path.read_bytes()) == expected
    name = "adaptive_replay._archived_q5_default_reference"
    loader = importlib.machinery.SourceFileLoader(name, str(original_path))
    spec = importlib.util.spec_from_loader(name, loader)
    original = importlib.util.module_from_spec(spec)
    sys.modules[name] = original
    spec.loader.exec_module(original)
    (tmp_path / "current").mkdir()
    current, initial, _ = q5._fixture(tmp_path / "current")
    OPENED.append(current.journal)

    def clone(value):
        cls = getattr(original, type(value).__name__)
        return cls(**{f.name: getattr(value, f.name) for f in fields(value) if f.init})

    actions = tuple(
        original.ArchivePortfolioActionV3(
            a.boundary_id,
            a.at_ms,
            a.source_sha256,
            clone(a.parameters),
        )
        for a in current.actions
    )
    old = original.ArchivePortfolioFinancialConsumerV3.create(
        tmp_path / "archived-reference.sqlite3",
        campaign_id="portfolio-reference",
        owner_id="owner",
        account_id="shared-account",
        seal=current.seal,
        models=tuple(clone(m) for m in current.models),
        calendars=current.calendars,
        actions=actions,
        initial_account=initial,
        entry_start_ms=q5.FIRST,
        entry_end_ms=q5.END,
        retained_end_ms=q5.END,
        expected_cost_ids=("service-a",),
        maximum_exit_attempts=3,
        storage_bounds=dict(DEFAULT_LIMITS),
    )
    OPENED.append(old.journal)
    while current.consume_next() is not None:
        assert old.consume_next() is not None
    assert old.consume_next() is None
    current_state, old_state = current.journal.snapshot().state, old.journal.snapshot().state
    assert decode_account_core(current_state["account"])[0] == decode_account_core(old_state["account"])[0]
    assert {k: v for k, v in current_state.items() if k not in {"account", "config"}} == {
        k: v for k, v in old_state.items() if k not in {"account", "config"}
    }
    assert {k: v for k, v in current.config.items() if k != "implementation"} == {
        k: v for k, v in old.config.items() if k != "implementation"
    }
    assert tuple(current.journal.native_events()) == tuple(old.journal.native_events())
    assert _sha(original_path.read_bytes()) == expected
