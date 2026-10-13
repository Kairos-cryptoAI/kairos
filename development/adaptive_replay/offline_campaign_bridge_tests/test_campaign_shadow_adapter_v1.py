import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adaptive_replay.campaign_shadow_adapter_v1 import (
    ACCEPTED_PERSISTENCE_REVISION,
    LOCKED_PERSISTENCE_REVISION,
    AmbiguousCall,
    Arm,
    BudgetCommit,
    BudgetReservation,
    CampaignBinding,
    OfflineCampaignOrchestrator,
    PlanStatus,
    ProposalCompletion,
    Readiness,
    ReviewCompletion,
    TimedSource,
    assert_non_trading_plan,
    build_campaign_plan,
)


class CampaignShadowAdapterTests(unittest.TestCase):
    def test_default_is_blocked_plan_only_with_exact_three_arms(self):
        plan = build_campaign_plan(Readiness())

        self.assertEqual(plan.status, PlanStatus.BLOCKED)
        self.assertIn("PLAN_ONLY_DEFAULT_NO_RUNTIME_EXECUTION", plan.blockers)
        self.assertIn("MISSING_IMMUTABLE_CAMPAIGN_WINDOW_BUNDLE_EVALUATION_IDENTITY", plan.blockers)
        self.assertEqual({arm.arm for arm in plan.arms}, set(Arm))
        self.assertEqual(len(plan.arms), 3)
        assert_non_trading_plan(plan)

    def test_actual_accepted_head_differs_from_lock_projection(self):
        readiness = Readiness(
            persistence_revision=ACCEPTED_PERSISTENCE_REVISION,
            lock_projection_revision=LOCKED_PERSISTENCE_REVISION,
            immutable_binding=CampaignBinding("c", "s", "claim", "w", "b", "e"),
            causal_sources_admitted=True,
            typed_composition_accepted=True,
            owner_enabled_shadow_wiring=True,
            plan_only=False,
        )
        plan = build_campaign_plan(readiness)
        self.assertIn("LOCK_PROJECTION_DOES_NOT_PIN_ACCEPTED_PERSISTENCE_HEAD", plan.blockers)


class FakeRepository:
    """Offline protocol fake; bodies do not validate persistence/source claims."""

    def __init__(self, *, paired_at=10_000, market_cutoff=1_000):
        self.events = []
        self.claim_calls = 0
        self.db_now_ms = 900
        self.market_cutoff = market_cutoff
        self.sources = {}
        self.claim = SimpleNamespace(campaign_id="mock-campaign", sample_id="mock-sample", claim_id="c" * 64)
        self.plan = SimpleNamespace(
            # This is only a protocol-shape value. FakeRepository does not
            # authenticate source capture or validate causal campaign gates.
            recording_mode="CAUSAL_OBSERVATION",
            required_sources=(
                SimpleNamespace(source_kind="MARKET_SNAPSHOT", source_name="mkt", maximum_age_ms=1000),
                SimpleNamespace(source_kind="NEWS", source_name="news", maximum_age_ms=1000),
                SimpleNamespace(source_kind="MACRO", source_name="macro", maximum_age_ms=1000),
            ),
            maximum_call_seconds=1,
        )
        self.schedule = SimpleNamespace(
            windows=(
                SimpleNamespace(
                    sample_id="mock-sample", market_as_of_ts_ms=market_cutoff, paired_at_ts_ms=paired_at
                ),
            )
        )
        self.protocol = SimpleNamespace()
        self.bundle = SimpleNamespace(receipt_sha256="b" * 64)
        self.evaluation = SimpleNamespace(
            receipt_sha256="e" * 64,
            intent=SimpleNamespace(intent_id="intent-1"),
            evaluated_at_ts_ms=1_900,
        )
        self.starts = {}
        self.terminals = {}
        self.reviews = {}
        self.outcome_rows = []
        self.cost_rows = []
        self.recorded_evaluation_at = 2_000
        self.recorded_decision_at = 3_000

    async def load_campaign(self, campaign_id):
        self.events.append("load_campaign")
        return self.plan, self.schedule, self.protocol

    async def claim_next(self, campaign_id):
        self.events.append("claim_next")
        self.claim_calls += 1
        if self.db_now_ms < self.market_cutoff:
            return None
        return self.claim if self.claim_calls == 1 else None

    async def capture_source(
        self, *, campaign_id, sample_id, source_kind, source_name, reference, source_as_of_ts_ms, content
    ):
        self.events.append(f"capture:{source_kind}")
        if self.db_now_ms >= self.market_cutoff:
            raise AssertionError("Persistence must not accept late source capture for a causal bundle")
        receipt = SimpleNamespace(
            source_kind=source_kind,
            source_name=source_name,
            content=content,
            source_as_of_ts_ms=source_as_of_ts_ms,
            observed_at_ts_ms=self.db_now_ms,
            receipt_sha256=(source_kind.lower() + "x") * 32,
        )
        self.sources[(source_kind, source_name)] = receipt
        return receipt

    async def freeze_bundle(self, claim):
        self.events.append("freeze_bundle")
        if self.db_now_ms < self.market_cutoff:
            raise AssertionError("claim/freeze must follow the market cutoff")
        if len(self.sources) != len(self.plan.required_sources):
            raise RuntimeError("preregistered causal source is missing")
        if any(row.observed_at_ts_ms > self.market_cutoff for row in self.sources.values()):
            raise AssertionError("source receipt was observed after cutoff")
        self.bundle.source_receipt_sha256s = tuple(
            sorted(row.receipt_sha256 for row in self.sources.values())
        )
        return self.bundle

    async def resolve_causal_sources(self, *, campaign_id, sample_id, source_receipt_sha256s):
        self.events.append("resolve_causal_sources")
        rows = tuple(sorted(self.sources.values(), key=lambda row: row.receipt_sha256))
        if tuple(row.receipt_sha256 for row in rows) != tuple(sorted(source_receipt_sha256s)):
            raise AssertionError("resolved receipts must match the frozen bundle")
        return rows

    async def record_causal_evaluation(self, *, claim, bundle, result):
        self.events.append("record_causal_evaluation")
        return self.evaluation

    async def evaluation_recorded_at(self, *, campaign_id, sample_id, evaluation_receipt_sha256):
        return self.recorded_evaluation_at

    async def start_attempt(self, attempt):
        attempt_id = attempt.attempt_id
        self.events.append(f"start:{attempt.arm_id}")
        if attempt_id in self.starts:
            return False
        self.starts[attempt_id] = attempt
        return True

    async def find_attempt(self, attempt_id):
        if attempt_id not in self.starts:
            return None
        return self.starts[attempt_id], self.terminals.get(attempt_id)

    async def find_review(self, attempt_id):
        return self.reviews.get(attempt_id)

    async def finish_attempt(self, terminal):
        self.events.append(f"terminal:{terminal.arm_id}:{terminal.terminal_status}")
        self.terminals[terminal.attempt_id] = terminal
        return True

    async def record_review(self, receipt):
        self.events.append("record_review")
        self.reviews[receipt.attempt_id] = receipt
        return True

    async def record_cost(self, receipt):
        self.events.append(f"cost:{receipt.stage}:{receipt.arm_id}")
        self.cost_rows.append(receipt)
        return True

    async def decision_recorded_at(self, *, campaign_id, sample_id, arm_id, attempt_id):
        return self.recorded_decision_at

    async def record_outcome(self, outcome):
        self.events.append(f"outcome:{outcome.arm_id}:{outcome.status}")
        self.outcome_rows.append(outcome)
        return True

    async def outcomes(self, campaign_id, sample_id):
        return tuple(self.outcome_rows)

    async def pending_claims(self, campaign_id, *, limit=64):
        return (self.claim,) if len(self.outcome_rows) < 3 else ()

    async def window_state(self, campaign_id, sample_id):
        state = {
            ("bundle", "all", "one"): self.bundle,
            ("evaluation", "all", "one"): self.evaluation,
        }
        for attempt_id, start in self.starts.items():
            state[("start", start.arm_id, attempt_id)] = start
            if attempt_id in self.terminals:
                state[("terminal", start.arm_id, attempt_id)] = self.terminals[attempt_id]
            if attempt_id in self.reviews:
                state[("review", start.arm_id, attempt_id)] = self.reviews[attempt_id]
        for row in self.cost_rows:
            state[("cost", row.arm_id, f"{row.stage}:{row.attempt_id}")] = row
        for row in self.outcome_rows:
            state[("outcome", row.arm_id, "one")] = row
        return state

    async def seal_denominator(self, campaign_id):
        self.events.append("seal_denominator")
        self.assert_three_arm_denominator()
        return SimpleNamespace(
            expected_outcomes=len(self.outcome_rows),
            status_counts={
                status: sum(row.status == status for row in self.outcome_rows)
                for status in {row.status for row in self.outcome_rows}
            },
        )

    def assert_three_arm_denominator(self):
        self_events = [row.arm_id for row in self.outcome_rows]
        if len(self_events) != 3 or set(self_events) != {arm.value for arm in Arm}:
            raise AssertionError("denominator requires one receipt for every registered arm")


class FakeEvaluator:
    def __init__(self, repository, *, no_intent=False, advance_to=None):
        self.repository = repository
        self.no_intent = no_intent
        self.advance_to = advance_to

    async def evaluate(self, *, campaign_context, claim, bundle, sources):
        self.repository.events.append("evaluate")
        if self.advance_to is not None:
            self.repository.recorded_evaluation_at = self.advance_to
        if self.no_intent:
            self.repository.evaluation.intent = None
        return object()


class FakeComposition:
    def __init__(self, repository, *, review_action="DEFER", ambiguous_review=False, block_review=None):
        self.repository = repository
        self.review_action = review_action
        self.ambiguous_review = ambiguous_review
        self.block_review = block_review
        self.review_calls = 0
        self.proposal_calls = 0
        self.venue_calls = 0
        self.risk_inputs = []

    async def review_shadow(self, *, campaign_context, bundle, evaluation, source_receipts, start):
        self.review_calls += 1
        self.repository.events.append("compose_review")
        self.assert_started(start)
        self.risk_inputs.append(start)
        if self.block_review is not None:
            self.block_review.set()
            await asyncio.Event().wait()
        if self.ambiguous_review:
            raise AmbiguousCall("offline simulated lost response")
        return ReviewCompletion(
            action=self.review_action,
            rationale="offline protocol fake",
            evidence_ids=("a" * 64,),
            response_sha256="d" * 64,
            requested_model="mock-model",
            resolved_model="mock-model",
            request_id="mock-review",
            prompt_sha256="p" * 64,
            observed_at_ts_ms=2_500,
            gateway_observed_cost_microusd=100,
            risk_shadow_result=SimpleNamespace(quantity=0, allowed=False),
        )

    async def propose_shadow(self, *, campaign_context, bundle, evaluation, source_receipts, start):
        self.proposal_calls += 1
        self.repository.events.append("compose_proposal")
        self.assert_started(start)
        return ProposalCompletion(
            proposal=SimpleNamespace(id="mock-candidate"),
            completion=SimpleNamespace(id="mock-completion"),
            observed_at_ts_ms=2_600,
            gateway_observed_cost_microusd=120,
        )

    def assert_started(self, start):
        if start.attempt_id not in self.repository.starts:
            raise AssertionError("composition/provider call occurred before durable START")


class FakeBudget:
    def __init__(self, repository):
        self.repository = repository
        self.reserve_calls = []
        self.commit_calls = []

    async def reserve(self, *, attempt_id, arm_id, maximum_microusd):
        self.repository.events.append(f"reserve:{arm_id.value}")
        self.reserve_calls.append((attempt_id, arm_id))
        return BudgetReservation(True, maximum_microusd, 2_000)

    async def commit(self, *, attempt_id, arm_id, actual_microusd):
        self.repository.events.append(f"commit:{arm_id.value}")
        self.commit_calls.append((attempt_id, arm_id))
        return BudgetCommit(actual_microusd, 3_000)


class FakeClock:
    def __init__(self, repository):
        self.repository = repository

    def now_ms(self):
        return self.repository.db_now_ms


class FakeReceiptFactory:
    def cost(self, **fields):
        return SimpleNamespace(**fields)

    def start(self, **fields):
        values = dict(fields)
        values.update(
            campaign_id=fields["claim"].campaign_id,
            sample_id=fields["claim"].sample_id,
            receipt_sha256="s" * 64,
        )
        return SimpleNamespace(**values)

    def unresolved_terminal(self, **fields):
        start = fields["start"]
        return SimpleNamespace(
            attempt_id=start.attempt_id,
            arm_id=start.arm_id,
            terminal_status="UNRESOLVED",
            observed_at_ts_ms=fields["observed_at_ts_ms"],
            receipt_sha256="u" * 64,
        )

    def failed_terminal(self, **fields):
        start = fields["start"]
        return SimpleNamespace(
            attempt_id=start.attempt_id,
            arm_id=start.arm_id,
            terminal_status="FAILED",
            observed_at_ts_ms=fields["observed_at_ts_ms"],
            receipt_sha256="f" * 64,
        )

    def proposal_terminal(self, **fields):
        start = fields["start"]
        return SimpleNamespace(
            attempt_id=start.attempt_id,
            arm_id=start.arm_id,
            terminal_status="COMPLETED",
            observed_at_ts_ms=fields["observed_at_ts_ms"],
            receipt_sha256="t" * 64,
        )

    def review(self, **fields):
        start = fields["start"]
        completion = fields["completion"]
        return SimpleNamespace(
            attempt_id=start.attempt_id,
            output=SimpleNamespace(action=completion.action),
            observed_at_ts_ms=completion.observed_at_ts_ms,
            receipt_sha256="r" * 64,
        )

    def outcome(self, **fields):
        return SimpleNamespace(**fields)


def make_orchestrator(repository, composition, *, evaluator=None, budget=None):
    return OfflineCampaignOrchestrator(
        repository=repository,
        evaluator=evaluator or FakeEvaluator(repository),
        composition=composition,
        budget=budget or FakeBudget(repository),
        receipts=FakeReceiptFactory(),
        clock=FakeClock(repository),
        attempt_id=lambda claim, arm: f"{claim.sample_id}-{arm.value}",
        persistence_revision=ACCEPTED_PERSISTENCE_REVISION,
        lock_projection_revision=LOCKED_PERSISTENCE_REVISION,
        offline_test_mode=True,
    )


def timed_sources():
    return tuple(
        TimedSource(kind, name, f"mock:{name}", 800, {"offline_fixture": True})
        for kind, name in (
            ("MARKET_SNAPSHOT", "mkt"),
            ("NEWS", "news"),
            ("MACRO", "macro"),
        )
    )


class CampaignOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def prepare(self, bridge, sources=None):
        return await bridge.capture_before_cutoff(
            campaign_id="mock-campaign",
            sample_id="mock-sample",
            provided_sources=timed_sources() if sources is None else sources,
        )

    async def test_persistence_call_order_defer_proposal_isolation_and_three_arm_seal(self):
        repository = FakeRepository()
        composition = FakeComposition(repository)
        bridge = make_orchestrator(repository, composition)

        report = await self.prepare(bridge)
        self.assertEqual(len(report.receipts), 3)
        self.assertTrue(all(row.observed_at_ts_ms <= report.market_cutoff_ts_ms for row in report.receipts))
        repository.db_now_ms = repository.market_cutoff
        (result,) = await bridge.run_bounded(campaign_id="mock-campaign")

        self.assertEqual([row.arm_id for row in result.outcomes], [arm.value for arm in Arm])
        self.assertEqual([row.status for row in result.outcomes], ["BASELINE", "DEFER", "PROPOSAL"])
        self.assertEqual(result.denominator_receipt.expected_outcomes, 3)
        self.assertLess(
            repository.events.index("start:strategy-review"), repository.events.index("compose_review")
        )
        self.assertLess(
            repository.events.index("start:llm-proposal-research"),
            repository.events.index("compose_proposal"),
        )
        self.assertLess(
            repository.events.index("cost:RESERVATION_REQUESTED:strategy-review"),
            repository.events.index("reserve:strategy-review"),
        )
        self.assertLess(
            repository.events.index("reserve:strategy-review"),
            repository.events.index("start:strategy-review"),
        )
        self.assertLess(repository.events.index("capture:MACRO"), repository.events.index("claim_next"))
        self.assertLess(repository.events.index("claim_next"), repository.events.index("freeze_bundle"))
        self.assertLess(
            repository.events.index("freeze_bundle"), repository.events.index("resolve_causal_sources")
        )
        self.assertEqual(composition.venue_calls, 0)
        self.assertEqual(composition.review_calls, 1)
        self.assertEqual(composition.proposal_calls, 1)
        self.assertEqual(result.risk_shadow_results[0].quantity, 0)
        self.assertEqual(
            result.durability_blockers,
            ("RISK_SHADOW_RESULT_NOT_REPRESENTABLE_IN_ACCEPTED_CAMPAIGN_RECEIPTS",),
        )

    async def test_ambiguous_provider_result_becomes_unknown_and_is_not_replayed(self):
        repository = FakeRepository()
        composition = FakeComposition(repository, ambiguous_review=True)
        bridge = make_orchestrator(repository, composition)

        await self.prepare(bridge)
        repository.db_now_ms = repository.market_cutoff
        (first,) = await bridge.run_bounded(campaign_id="mock-campaign")
        (second,) = await bridge.run_bounded(campaign_id="mock-campaign")

        self.assertEqual([row.status for row in first.outcomes], ["BASELINE", "UNKNOWN", "PROPOSAL"])
        self.assertEqual(first.denominator_receipt.status_counts["UNKNOWN"], 1)
        self.assertIsNone(second.claim)
        self.assertEqual(composition.review_calls, 1)
        self.assertEqual(composition.proposal_calls, 1)

    async def test_restart_reconciles_durable_start_without_provider_resend(self):
        repository = FakeRepository()
        composition = FakeComposition(repository)
        bridge = make_orchestrator(repository, composition)
        attempt_id = "mock-sample-strategy-review"
        repository.starts[attempt_id] = SimpleNamespace(
            attempt_id=attempt_id,
            campaign_id="mock-campaign",
            sample_id="mock-sample",
            arm_id=Arm.STRATEGY_REVIEW.value,
            receipt_sha256="s" * 64,
            attempt_started_at_ts_ms=1_200,
        )
        repository.cost_rows.extend(
            (
                SimpleNamespace(
                    arm_id=Arm.STRATEGY_REVIEW.value, attempt_id=attempt_id, stage="RESERVATION_REQUESTED"
                ),
                SimpleNamespace(arm_id=Arm.STRATEGY_REVIEW.value, attempt_id=attempt_id, stage="RESERVED"),
            )
        )

        (result,) = await bridge.reconcile_pending(campaign_id="mock-campaign")

        outcomes = {row.arm_id: row.status for row in result.outcomes}
        self.assertEqual(outcomes[Arm.STRATEGY_REVIEW.value], "UNKNOWN")
        self.assertEqual(outcomes[Arm.STRATEGY_ONLY.value], "BASELINE")
        self.assertNotIn(Arm.LLM_PROPOSAL_RESEARCH.value, outcomes)
        self.assertEqual(composition.review_calls + composition.proposal_calls, 0)
        self.assertIn("RESTART_RECONCILIATION_NO_DISPATCH", result.stopped_reason)

    async def test_cutoff_records_missed_arms_and_denominator_includes_missed(self):
        repository = FakeRepository(paired_at=1_500)
        composition = FakeComposition(repository)
        bridge = make_orchestrator(repository, composition)

        await self.prepare(bridge)
        repository.db_now_ms = 1_500
        (result,) = await bridge.run_bounded(campaign_id="mock-campaign")

        self.assertEqual([row.status for row in result.outcomes], ["LATE", "MISSED", "MISSED"])
        self.assertEqual(result.denominator_receipt.status_counts["MISSED"], 2)
        self.assertEqual(composition.review_calls, 0)
        self.assertEqual(composition.proposal_calls, 0)

    async def test_missing_sources_are_not_fetched_and_all_three_are_counted(self):
        repository = FakeRepository()
        composition = FakeComposition(repository)
        bridge = make_orchestrator(repository, composition)

        report = await self.prepare(bridge, timed_sources()[:2])
        self.assertEqual(len(report.missing_source_keys), 1)
        repository.db_now_ms = repository.market_cutoff
        (result,) = await bridge.run_bounded(campaign_id="mock-campaign")

        self.assertEqual([row.status for row in result.outcomes], ["SOURCE_MISSING"] * 3)
        self.assertEqual(result.denominator_receipt.status_counts["SOURCE_MISSING"], 3)
        self.assertEqual(composition.review_calls + composition.proposal_calls, 0)
        self.assertEqual(sum(event.startswith("capture:") for event in repository.events), 2)

    async def test_capture_after_cutoff_is_rejected_without_backdating_or_capture_call(self):
        repository = FakeRepository()
        repository.db_now_ms = repository.market_cutoff
        composition = FakeComposition(repository)
        bridge = make_orchestrator(repository, composition)

        (result,) = await bridge.run_bounded(campaign_id="mock-campaign")
        self.assertEqual([row.status for row in result.outcomes], ["SOURCE_MISSING"] * 3)
        report = await self.prepare(bridge)
        self.assertEqual(report.receipts, ())
        self.assertIn("CAPTURE_STARTED_AT_OR_AFTER_MARKET_CUTOFF", report.blockers)
        self.assertFalse(any(event.startswith("capture:") for event in repository.events))

    async def test_cancellation_persists_unknown_and_never_resends(self):
        repository = FakeRepository()
        started = asyncio.Event()
        composition = FakeComposition(repository, block_review=started)
        bridge = make_orchestrator(repository, composition)
        await self.prepare(bridge)
        repository.db_now_ms = repository.market_cutoff
        task = asyncio.create_task(bridge.run_bounded(campaign_id="mock-campaign"))

        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertTrue(any(row.status == "UNKNOWN" for row in repository.outcome_rows))
        self.assertEqual(composition.review_calls, 1)
        self.assertNotIn("compose_proposal", repository.events)

    async def test_observation_cap_and_native_mode_fail_closed_before_ports(self):
        repository = FakeRepository()
        composition = FakeComposition(repository)
        bridge = make_orchestrator(repository, composition)

        with self.assertRaises(ValueError):
            await bridge.run_bounded(campaign_id="mock-campaign", max_observations=2)
        with self.assertRaises(RuntimeError):
            OfflineCampaignOrchestrator(
                repository=repository,
                evaluator=FakeEvaluator(repository),
                composition=composition,
                budget=FakeBudget(repository),
                receipts=FakeReceiptFactory(),
                clock=FakeClock(repository),
                attempt_id=lambda claim, arm: "x",
                persistence_revision=ACCEPTED_PERSISTENCE_REVISION,
                lock_projection_revision=ACCEPTED_PERSISTENCE_REVISION,
            )
        self.assertEqual(repository.events, [])

    def test_proposal_arm_never_enters_risk_path(self):
        plan = build_campaign_plan(Readiness())
        proposal = next(arm for arm in plan.arms if arm.arm is Arm.LLM_PROPOSAL_RESEARCH)

        self.assertTrue(proposal.candidate_isolated)
        self.assertFalse(proposal.risk_shadow_only)
        self.assertNotIn("risk_shadow_decision", proposal.required_steps)
        self.assertFalse(proposal.trading_allowed)
        self.assertFalse(proposal.venue_calls_allowed)

    def test_bound_and_identity_mismatches_fail_closed(self):
        readiness = Readiness(
            persistence_revision="not-accepted",
            lock_projection_revision=LOCKED_PERSISTENCE_REVISION,
            immutable_binding=CampaignBinding("c", "s", "claim", "w", "b", "e"),
            causal_sources_admitted=True,
            typed_composition_accepted=True,
            owner_enabled_shadow_wiring=True,
            plan_only=False,
        )

        plan = build_campaign_plan(readiness, max_observations=2, max_window_seconds=61)

        self.assertEqual(plan.status, PlanStatus.BLOCKED)
        self.assertIn("PERSISTENCE_API_REVISION_NOT_ACCEPTED_HEAD", plan.blockers)
        self.assertIn("LOCK_PROJECTION_DOES_NOT_PIN_ACCEPTED_PERSISTENCE_HEAD", plan.blockers)
        self.assertIn("OBSERVATION_BOUND_MUST_BE_EXACTLY_ONE", plan.blockers)
        self.assertIn("WINDOW_BOUND_OUTSIDE_ALLOWED_FINITE_LIMIT", plan.blockers)
        self.assertEqual(plan.max_observations, 1)
        self.assertEqual(plan.max_window_seconds, 60)


if __name__ == "__main__":
    unittest.main()
