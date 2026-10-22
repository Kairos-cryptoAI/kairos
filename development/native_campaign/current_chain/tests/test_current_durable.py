"""Opt-in actual PG/controller positive proof; synthetic sources/models only.

Only the parent's explicitly supplied fresh current-SIM database is accepted.
This test NEVER creates a database, migrates a schema, starts a container or
calls a provider. It preserves every recorded artifact for parent inspection.
"""

import json
import os
import re
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from adaptive_replay import catalyst_policy_v1 as catalyst
from adaptive_replay.catalyst_hypothesis_v1 import evaluate_hypothesis
from adaptive_replay.scenarios import MINUTE
from kairos_core.contracts import (
    RecordedBookLevelV1,
    RecordedTopNBookFrameV1,
    SimulationAssumptionsV1,
    SimulationResultV1,
    SimulationSessionV1,
)
from kairos_execution.simulation import SimulationExecutionController
from kairos_persistence import Database, MigrationProfile, PersistenceSettings, SimulationRepository
from kairos_persistence.database_target import connect_verified_database, require_database_target_url
from kairos_strategy.candles import Candle
from kairos_strategy.runtime import candle_to_closed_bar
from test_current_chain import NATIVE, START, SYMBOL, UNIVERSE, prepared_plan, reviewed, sim_session

from kairos_native_campaign.current_chain import bind_scenario_review, decide_sim, native_intent


def _target():
    url = os.getenv("KAIROS_CURRENT_SIM_DATABASE_URL")
    if not url:
        pytest.skip("explicit fresh KAIROS_CURRENT_SIM_DATABASE_URL required")
    parsed = urlsplit(url)
    name = parsed.path.removeprefix("/")
    suffix = name.removeprefix("kairos_sim_current_")
    if (
        re.fullmatch(r"[0-9a-f]{32}", suffix) is None
        or UUID(hex=suffix).version != 4
        or name != "kairos_sim_current_" + suffix
        or parsed.username != "kairos"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or not parsed.password
    ):
        raise ValueError("EXPLICIT_FRESH_CURRENT_SIM_TARGET_REQUIRED")
    require_database_target_url(url, name, local_only=True)
    return PersistenceSettings(_env_file=None, database_url=url, pool_min_size=1, pool_max_size=2), name


def _frame(tape_id, symbol, sequence, previous, clock, *, bid=100.09, ask=100.10):
    return RecordedTopNBookFrameV1(
        source="current-durable-synthetic-fixture",
        tape_id=tape_id,
        stream_epoch="current-durable-fixture",
        symbol=symbol,
        tape_sequence=sequence,
        exchange_update_id=sequence,
        exchange_at_ms=clock,
        received_at_ms=clock,
        persisted_at_ms=clock,
        raw_payload_sha256=f"{sequence:064x}",
        previous_frame_sha256=previous,
        continuity="ADMITTED",
        bids=(RecordedBookLevelV1(price=bid, quantity=100.0),),
        asks=(RecordedBookLevelV1(price=ask, quantity=100.0),),
    )


@pytest.mark.asyncio
async def test_current_v2_actual_sim_lifecycle_restart_duplicate_and_expiry():
    settings, name = _target()  # Refuse/skip BEFORE constructing a database client.
    database = Database(settings, migration_profile=MigrationProfile.SIMULATOR)
    await connect_verified_database(database, name, local_only=True)
    try:
        await database.verify_schema()  # No migrate: parent owns fresh DDL.
        for table in ("sim_tapes", "sim_sessions", "sim_admissions", "sim_commands"):
            assert await database.pool.fetchval(f"SELECT count(*) FROM {table}") == 0, (
                "CURRENT_DURABLE_TEST_REQUIRES_FRESH_EMPTY_SIM_TARGET"
            )
        repository = SimulationRepository(database.pool)
        chain, prepared, _outcome, plan, bars, preview = prepared_plan()
        first_review, gateway = await reviewed(preview.intent, bars)
        observation = bind_scenario_review(
            preview, first_review, actual_completed_ms=first_review.reviewed_at_ms
        )
        raw = evaluate_hypothesis(plan, (observation,))[-1].candidate
        assert raw is not None
        chain, arbitration = chain.resolve(
            prepared,
            symbol=SYMBOL,
            arm_id="independent_proposals",
            issued_ms=raw.decision_ts_ms,
            runs=(catalyst.OriginRun(plan, (observation,)),),
            shared_gate="PASS",
            current_prepared=prepared,
        )
        assert arbitration.candidate == raw
        final = native_intent(raw, input_bars=bars, **NATIVE)
        final_review, gateway = await reviewed(final, bars, gateway=gateway)
        assert gateway.calls == 2
        assert final.contract_version == "strategy-intent.observed-sim.v2"
        assert final.intent_id != preview.intent.intent_id
        immutable_bytes = final.canonical_intent_bytes()
        decided = final_review.reviewed_at_ms
        tape_id = "current-durable-fixture-" + uuid4().hex
        # Record the complete declared native provenance, not a shortened tail.
        for bar in bars:
            assert await repository.record_closed_bar(tape_id, bar)
        for symbol in UNIVERSE:
            if symbol != SYMBOL:
                bar = Candle(symbol, "1m", START, START + MINUTE - 1, 100.0, 100.7, 99.3, 100.0, 10.0)
                assert await repository.record_closed_bar(tape_id, candle_to_closed_bar(bar))
        exit_bar = candle_to_closed_bar(
            Candle(
                SYMBOL,
                "1m",
                START + MINUTE,
                START + 2 * MINUTE - 1,
                100.1,
                final.exit_plan.target_price + 0.1,
                final.exit_plan.stop_price - 0.1,
                100.0,
                10.0,
            )
        )
        assert await repository.record_closed_bar(tape_id, exit_bar)
        previous, entry_frame = None, None
        for sequence, symbol in enumerate((SYMBOL,) + tuple(s for s in UNIVERSE if s != SYMBOL), start=1):
            frame = _frame(tape_id, symbol, sequence, previous, decided + sequence - 1)
            assert await repository.record_book_frame(frame)
            previous = frame.frame_sha256
            if symbol == SYMBOL:
                entry_frame = frame
        exit_frame = _frame(
            tape_id,
            SYMBOL,
            6,
            previous,
            exit_bar.close_time_ms + 10,
            bid=round(final.exit_plan.stop_price, 2),
            ask=round(final.exit_plan.stop_price, 2) + 0.01,
        )
        assert await repository.record_book_frame(exit_frame)
        seal = await repository.seal_tape(tape_id, sealed_at_ms=exit_bar.close_time_ms + 100)
        assert await repository.verify_tape(tape_id)
        template = sim_session(final)
        assumptions = SimulationAssumptionsV1.model_validate(
            {
                **template.assumptions.identity_payload(),
                "latency_ms": 25,
            }
        )
        session = SimulationSessionV1(
            source="current-durable-synthetic-fixture",
            tape_id=tape_id,
            tape_sha256=seal.tape_sha256,
            assumptions=assumptions,
            strategy_allowlist=template.strategy_allowlist,
            started_at_ms=template.started_at_ms,
            ends_at_ms=template.ends_at_ms,
        )
        assert await repository.create_session(session)
        decision, admission = decide_sim(
            session=session,
            final_intent=final,
            final_review=final_review,
            selected_book_frame=entry_frame,
            decided_at_ms=decided,
            requested_quantity=1.0,
        )
        assert decision.approved and admission is not None
        assert await repository.record_risk_decision(decision)
        controller = SimulationExecutionController(repository, source="current-durable-fixture")
        trade = await controller.start_trade(admission, created_at_ms=decided)
        entry = await controller.submit_entry(trade, as_of_ms=decided + 100)
        assert entry.receipt is not None and entry.receipt.status == "FILLED"
        pending = await controller.process_closed_bar(trade, exit_bar, as_of_ms=exit_bar.close_time_ms + 1)
        assert pending is not None and pending.receipt is None
        assert pending.command.command_kind == "STOP_EXIT_IOC"
        # Reconnect actual persistence before completing the prepared stop.
        await database.close()
        database = Database(settings, migration_profile=MigrationProfile.SIMULATOR)
        await connect_verified_database(database, name, local_only=True)
        await database.verify_schema()
        repository = SimulationRepository(database.pool)
        controller = SimulationExecutionController(repository, source="current-durable-fixture")
        recovered = await controller.recover_prepared(
            session.session_id, as_of_ms=exit_bar.close_time_ms + 100
        )
        assert len(recovered) == 1 and recovered[0].command == pending.command
        stopped = recovered[0]
        assert stopped.receipt is not None and stopped.receipt.status == "FILLED"
        assert stopped.lifecycle_state == "FLAT"
        assert stopped.receipt.filled_quantity == entry.receipt.filled_quantity == decision.quantity
        assert await repository.verify_trade_chain(trade.trade_id)
        assert (
            await controller.recover_prepared(session.session_id, as_of_ms=exit_bar.close_time_ms + 100) == ()
        )
        repeated_entry = await controller.submit_entry(trade, as_of_ms=decided + 100)
        assert repeated_entry.replayed and repeated_entry.receipt == entry.receipt
        assert await controller.start_trade(admission, created_at_ms=decided) == trade
        assert not await repository.record_risk_decision(decision)
        counts = {
            table: await database.pool.fetchval(
                f"SELECT count(*) FROM {table} WHERE session_id=$1", session.session_id
            )
            for table in ("sim_admissions", "sim_commands", "sim_results")
        }
        assert counts == {"sim_admissions": 1, "sim_commands": 2, "sim_results": 1}
        expired, forbidden_admission = decide_sim(
            session=session,
            final_intent=final,
            final_review=final_review,
            selected_book_frame=entry_frame,
            decided_at_ms=final.entry_expires_ts_ms + 1,
            requested_quantity=1.0,
        )
        assert not expired.approved and "INTENT_EXPIRED" in expired.rejection_reasons
        assert forbidden_admission is None and await repository.record_risk_decision(expired)
        for table, count in counts.items():
            assert (
                await database.pool.fetchval(
                    f"SELECT count(*) FROM {table} WHERE session_id=$1", session.session_id
                )
                == count
            )
        payload = await database.pool.fetchval(
            "SELECT payload FROM sim_results WHERE trade_id=$1", trade.trade_id
        )
        result = SimulationResultV1.model_validate(
            json.loads(payload) if isinstance(payload, str) else payload
        )
        assert result.final_state == "FLAT" and result.model_realized_pnl_quote < 0 < result.model_fee_quote
        assert (
            not result.venue_execution_observed
            and not result.paper_qualification_eligible
            and not result.alpha_claim
        )
        assert decision.intent.canonical_intent_bytes() == immutable_bytes
        assert stopped.command.trade.admission.decision.intent.canonical_intent_bytes() == immutable_bytes
        assert final.canonical_intent_bytes() == immutable_bytes
    finally:
        await database.close()
