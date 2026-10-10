"""No paid calls: local holds, retry rejection and fixed routes in isolation."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "market_worker_tests_subject", Path(__file__).parents[1] / "model_worker.py"
)
worker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = worker
spec.loader.exec_module(worker)


class Shared:
    def __init__(self, fail=False):
        self.fail, self.reserves, self.commits = fail, [], []

    async def reserve(self, **kwargs):
        self.reserves.append(kwargs)
        if self.fail:
            raise ValueError("isolated simulated shared failure")

    async def commit(self, **kwargs):
        self.commits.append(kwargs)


def reserve(budget, amount=100):
    return budget.reserve(
        provider="openai",
        reservation_id="id",
        reserved_microusd=amount,
        monthly_budget_microusd=12_000_000,
    )


def test_hold_precedes_shared_and_is_not_freed_after_error(tmp_path):
    shared = Shared(fail=True)
    journal = tmp_path / "journal.jsonl"
    budget = worker.ScopedBudget(shared, journal, 100)
    with pytest.raises(ValueError):
        asyncio.run(reserve(budget))
    assert budget.held == 100
    assert json.loads(journal.read_text())["state"] == "LOCAL_HOLD_BEFORE_SHARED"
    with pytest.raises(ValueError, match="duplicated"):
        asyncio.run(reserve(budget))
    assert len(shared.reserves) == 1


def test_committed_veto_cost_stays_spent(tmp_path):
    shared = Shared()
    budget = worker.ScopedBudget(shared, tmp_path / "journal.jsonl", 100)
    asyncio.run(reserve(budget))
    asyncio.run(
        budget.commit(provider="openai", reservation_id="id", actual_microusd=25)
    )
    assert budget.held == 25
    assert len(shared.commits) == 1
    with pytest.raises(ValueError):
        asyncio.run(reserve(budget))


def test_local_cap_blocks_before_request_or_shared(tmp_path):
    shared = Shared()
    budget = worker.ScopedBudget(shared, tmp_path / "journal.jsonl", 99)
    with pytest.raises(ValueError, match="envelope"):
        asyncio.run(reserve(budget))
    assert shared.reserves == []


def test_other_route_provider_or_ceiling_cannot_be_admitted(tmp_path):
    budget = worker.ScopedBudget(Shared(), tmp_path / "journal.jsonl", 100)
    with pytest.raises(ValueError, match="ceiling"):
        asyncio.run(
            budget.reserve(
                provider="deepseek",
                reservation_id="id",
                reserved_microusd=10,
                monthly_budget_microusd=1_000_000,
            )
        )
    with pytest.raises(ValueError, match="predeclared"):
        worker.FixedRouter().resolve()


@pytest.mark.parametrize("decision", ["BUY", "SELL", "MODIFY_STOP", "allow"])
def test_review_contract_cannot_create_order_or_change_stop(decision):
    with pytest.raises(ValueError):
        worker.Review(decision=decision, reason="fixture")


def test_review_extra_fields_denied():
    with pytest.raises(ValueError):
        worker.Review(decision="ALLOW", reason="fixture", quantity=1)
