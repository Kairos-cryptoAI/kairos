"""Short atomic financial integration on a full sealed fixture source roster.

Only the early prefix is executed: these tests are NOT a dense/full-horizon
capacity benchmark, accepted historical data, or qualified economics.
"""

import copy
from dataclasses import replace
from decimal import Decimal as D

import pytest

from adaptive_replay.account_event_context_v3 import canonical_native_event
from adaptive_replay.candle_originals_v3 import CandleOriginalsV3
from adaptive_replay.continuous_sim import (
    UNIVERSE,
    ContinuousSimPortfolio,
    FundingInput,
    FundingSchedule,
    SimInputError,
    SymbolRules,
    TapeBinding,
    _available,
)
from adaptive_replay.continuous_sim_financial_v3_horizon import ContinuousSimFinancialV3Horizon
from adaptive_replay.continuous_sim_v3_horizon import FIVE_DAYS, FiveDayHorizonV3, HorizonCandleOriginalsV3
from adaptive_replay.sim_account_codec import decode_account, encode_account
from adaptive_replay.sim_account_core_codec_v3 import decode_account_core
from adaptive_replay.sim_state_journal import JournalError, JournalFull

from . import test_continuous_sim_v3_horizon as fixture

START, MINUTE, SHA = fixture.START, fixture.MINUTE, fixture.SHA
CUT, ISSUE = START + MINUTE, START + 2 * MINUTE + 200


@pytest.fixture(scope="module")
def originals():
    return HorizonCandleOriginalsV3(
        tuple(
            fixture.original(symbol, START + i * MINUTE, 100.5 if symbol == "BTCUSDT" and i == 1 else 100.0)
            for symbol in UNIVERSE
            for i in range(7200)
        )
    )


@pytest.fixture(scope="module")
def source(originals):
    entry = fixture.frame(at=ISSUE - 2)
    exits = (
        fixture.frame(seq=2, at=ISSUE + 100, bid="98", ask="98.01", qty="0.1"),
        fixture.frame(seq=3, at=ISSUE + 110, bid="98", ask="98.01", qty="0.1"),
        fixture.frame(seq=4, at=ISSUE + 120, bid="98.01", ask="98.02", qty="0.1"),
    )
    funding = FundingInput(
        "BTCUSDT", ISSUE + 10, ISSUE + 130, "funding", "TEST_FIXTURE", "SETTLED", D("0.001"), D(100), SHA
    )
    return fixture.source_binding(originals, (entry, *exits, funding))


def create(tmp_path, originals, source, *, seal=SHA, costs=(), **limits):
    return ContinuousSimFinancialV3Horizon.create(
        tmp_path / "financial.sqlite3",
        campaign_id="financial-fixture",
        arm_id="arm",
        owner_id="fixture-owner",
        account_id="fixture-account",
        binding=source,
        models=fixture.models(),
        rules={s: SymbolRules(s, D("0.01"), D("0.001"), D(100000)) for s in UNIVERSE},
        funding_schedule=FundingSchedule("funding", "TEST_FIXTURE", (("BTCUSDT", ISSUE + 10),), SHA),
        horizon=FiveDayHorizonV3(START, START + FIVE_DAYS + 3 * 3_600_000, START),
        initial_equity=D(1000),
        hypothesis_seal_sha256=seal,
        candle_originals=originals,
        allowed_origins=("TECHNICAL",),
        expected_cost_ids=costs,
        **limits,
    )


def reopen(portfolio, *, checkpoint=None):
    arguments = dict(
        identity=portfolio.journal.identity,
        expected_checkpoint=checkpoint or portfolio.journal.checkpoint(),
        binding=portfolio.binding,
        models=portfolio.models,
        rules=portfolio.rules,
        funding_schedule=portfolio.funding,
        config=portfolio.config,
        candle_originals=portfolio.candle_originals,
    )
    path = portfolio.path
    portfolio.close()
    return ContinuousSimFinancialV3Horizon.open(path, **arguments)


def assert_financial_equal(old, new):
    old_state, new_state = old.snapshot().state, new.snapshot().state
    old_account = decode_account(old_state["account"])
    new_account, ledger = decode_account_core(new_state["account"])
    assert new_account.events == ()
    assert encode_account(replace(old_account, events=())) == encode_account(new_account)
    events = tuple(new.journal.native_events())
    assert tuple(map(canonical_native_event, events)) == tuple(
        map(canonical_native_event, old_account.events)
    )
    assert ledger.event_count == len(events) == new.journal.checkpoint().native_count
    assert ledger.head_sha256 == new.journal.checkpoint().native_head
    for field in ("cursor", "clock", "latest", "liquidity", "pending", "candles", "funding", "slots"):
        assert old_state[field] == new_state[field]
    assert set(old_state["parents"]) == set(new_state["parents"])
    for parent_id, old_parent in old_state["parents"].items():
        new_parent = new_state["parents"][parent_id]
        # Source/implementation commitments deliberately differ: one complete
        # fixed five-day roster versus the legacy short-prefix fixture.
        assert {k: v for k, v in old_parent.items() if k != "issue"} == {
            k: v for k, v in new_parent.items() if k != "issue"
        }


def test_actual_v3_intake_atomic_partials_cost_latefunding_restart_duplicate(
    tmp_path, originals, source, monkeypatch
):
    monkeypatch.setattr(fixture, "CUT", CUT)
    monkeypatch.setattr(fixture, "ISSUE", ISSUE)
    entry = next(i.value for i in source.inputs if getattr(i.value, "sequence", None) == 1)
    producer, receipt = fixture.hypothesis(tmp_path, originals, entry)
    new = create(tmp_path, originals, source, seal=producer.snapshot().seal_sha256, costs=("service",))
    early_inputs = tuple(i for i in source.inputs if _available(i.value) <= ISSUE + 130)
    short_binding = TapeBinding(
        source.source_id,
        source.tape_id,
        source.stream_epoch,
        source.quote_source_id,
        source.evidence_kind,
        early_inputs,
    )
    short_originals = CandleOriginalsV3(tuple(r for r in originals.records if r.candle.open_time_ms <= CUT))
    old = ContinuousSimPortfolio.create(
        tmp_path / "old.sqlite3",
        campaign_id="legacy-short-fixture",
        arm_id="arm",
        binding=short_binding,
        models=new.models,
        rules=new.rules,
        funding_schedule=new.funding,
        minutes=(ISSUE // MINUTE * MINUTE,),
        initial_equity=D(1000),
        hypothesis_seal_sha256=producer.snapshot().seal_sha256,
        hypothesis_contract="V3",
        candle_originals=short_originals,
        allowed_origins=("TECHNICAL",),
    )
    try:
        for item in early_inputs:
            if _available(item.value) > ISSUE:
                break
            for portfolio in (old, new):
                portfolio.ingest(global_sequence=item.global_sequence, now_ms=_available(item.value))
        for portfolio in (old, new):
            portfolio.debit_service(cost_id="service", amount=D("0.02"), at_ms=ISSUE)
            result = portfolio.intake_v3(
                hypothesis_journal=producer,
                receipt=receipt,
                expected_hypothesis_head_sha256=producer.snapshot().head_sha256,
                at_ms=ISSUE,
            )
            assert result.outcome["status"] == "PENDING"
            portfolio.advance_to(now_ms=ISSUE + 2, event_id="entry")
        assert_financial_equal(old, new)
        assert decode_account_core(new.snapshot().state["account"])[0].positions[0].quantity == D("0.2")
        before = new.journal.checkpoint()
        new = reopen(new)
        replay = new.intake_v3(
            hypothesis_journal=producer,
            receipt=receipt,
            expected_hypothesis_head_sha256=producer.snapshot().head_sha256,
            at_ms=ISSUE,
        )
        assert replay.replayed and new.journal.checkpoint() == before
        assert new.advance_to(now_ms=ISSUE + 2, event_id="entry").replayed
        assert new.journal.checkpoint() == before
        for item in early_inputs[new.snapshot().state["cursor"] :]:
            for portfolio in (old, new):
                portfolio.ingest(global_sequence=item.global_sequence, now_ms=_available(item.value))
                if _available(item.value) < ISSUE + 130:
                    portfolio.advance_to(
                        now_ms=_available(item.value) + 2, event_id=f"exit-{item.global_sequence}"
                    )
            assert_financial_equal(old, new)
        new = reopen(new)
        assert_financial_equal(old, new)
        account = decode_account_core(new.snapshot().state["account"])[0]
        assert not account.positions and not account.protective_exit_pending
        assert tuple(new.journal.native_events())[-1].payload == (
            "LATE_KNOWN_FUNDING",
            f"BTCUSDT:{ISSUE + 10}",
            D("-0.0200"),
            ISSUE + 130,
        )
        assert new.config["source_resource_profile"]["arbitrary_native_feed_capacity"] is False
        assert new.config["flat_mark_ledger"].startswith("ALL_EXACT_NATIVE_EVENTS")
    finally:
        old.close()
        new.close()


def test_source_batch_native_mark_fault_rolls_back_every_projection_and_restart(
    tmp_path, originals, source, monkeypatch
):
    portfolio = create(tmp_path, originals, source)
    last = max(i.global_sequence for i in source.inputs if _available(i.value) <= ISSUE)
    before = portfolio.journal.checkpoint()
    original = copy.deepcopy(portfolio.snapshot().state)

    def fail_before_commit():
        raise RuntimeError("injected precommit failure")

    monkeypatch.setattr(portfolio.journal, "_before_commit", fail_before_commit)
    with pytest.raises(RuntimeError, match="precommit"):
        portfolio.ingest_batch(first_sequence=1, last_sequence=last)
    assert portfolio.journal.checkpoint() == before
    assert portfolio.snapshot().state == original
    assert tuple(portfolio.journal.native_events()) == ()
    portfolio = reopen(portfolio, checkpoint=before)
    try:
        result = portfolio.ingest_batch(first_sequence=1, last_sequence=last)
        assert result.outcome["cursor"] == last
        events = tuple(portfolio.journal.native_events())
        assert len(events) == 1 and events[0].payload[0] == "MARK"  # flat MARK retained
        committed = portfolio.journal.checkpoint()
        assert portfolio.ingest_batch(first_sequence=1, last_sequence=last).replayed
        assert portfolio.journal.checkpoint() == committed
        with pytest.raises(JournalError, match="checkpoint"):
            ContinuousSimFinancialV3Horizon.open(
                portfolio.path,
                identity=portfolio.journal.identity,
                expected_checkpoint=before,
                binding=portfolio.binding,
                models=portfolio.models,
                rules=portfolio.rules,
                funding_schedule=portfolio.funding,
                config=portfolio.config,
                candle_originals=originals,
            )
    finally:
        portfolio.close()


def test_native_row_cap_does_not_skip_source_or_erase_flat_audit(tmp_path, originals, source):
    portfolio = create(tmp_path, originals, source, max_native_event_rows=1)
    try:
        last = max(i.global_sequence for i in source.inputs if _available(i.value) <= ISSUE)
        portfolio.ingest_batch(first_sequence=1, last_sequence=last)
        before, state = portfolio.journal.checkpoint(), portfolio.snapshot().state
        next_item = source.inputs[last]
        with pytest.raises(JournalFull, match="native row"):
            portfolio.ingest(global_sequence=next_item.global_sequence, now_ms=_available(next_item.value))
        assert portfolio.journal.checkpoint() == before
        assert portfolio.snapshot().state == state and portfolio.snapshot().state["cursor"] == last
        assert len(tuple(portfolio.journal.native_events())) == 1
    finally:
        portfolio.close()


def test_finish_service_gate_exact_native_index_unknown_retention_and_roster(tmp_path, originals, source):
    portfolio = create(tmp_path, originals, source, costs=("known", "missing", "unknown"))
    try:
        portfolio.debit_service(cost_id="known", amount=D("0.02"), at_ms=START)
        portfolio.record_unknown_service(cost_id="unknown", source_sha256=SHA, at_ms=START)
        before = portfolio.journal.checkpoint()
        with pytest.raises(SimInputError, match="roster"):
            portfolio.debit_service(cost_id="extra", amount=D(0), at_ms=START)
        assert portfolio.journal.checkpoint() == before

        def audit_liabilities(state):
            outcome = {"status": "COMPLETE", "net_return": "0"}
            portfolio._finish_liability_gates(state, outcome)
            return outcome

        result = portfolio._event(
            "liability-unit-audit", {"kind": "LIABILITY_UNIT_AUDIT"}, START, audit_liabilities
        )
        assert result.outcome["status"] == "UNRESOLVED" and result.outcome["net_return"] is None
        assert result.outcome["missing_service_costs"] == ["missing", "unknown"]
        assert result.outcome["unavailable_service_costs"] == ["unknown"]
        portfolio.debit_service(cost_id="unknown", amount=D("0.03"), at_ms=START)
        assert (
            portfolio.snapshot().state["service_liabilities"]["unknown"]["earlier_unavailable"]["status"]
            == "UNAVAILABLE"
        )
        result = portfolio._event(
            "liability-unit-audit-2", {"kind": "LIABILITY_UNIT_AUDIT"}, START, audit_liabilities
        )
        assert result.outcome["missing_service_costs"] == ["missing"]
        assert result.outcome["unavailable_service_costs"] == []

        # The gate requires the original native debit, not a SETTLED assertion.
        def forged_liability(state):
            state["service_liabilities"]["missing"] = {"status": "SETTLED", "amount": "0", "at": START}
            return audit_liabilities(state)

        result = portfolio._event(
            "forged-cost-unit-audit", {"kind": "LIABILITY_UNIT_AUDIT"}, START, forged_liability
        )
        assert result.outcome["missing_service_costs"] == ["missing"]
    finally:
        portfolio.close()
