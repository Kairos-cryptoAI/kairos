import json

import pytest

from kairos_native_campaign.current_runtime import (
    _ACTIVE,
    CurrentScopedBudget,
    RecordingCurrentGateway,
    read_existing_openai_key,
)


class Shared:
    def __init__(self, *, fail=False):
        self.fail, self.reservations, self.commits = fail, [], []

    async def reserve(self, **kw):
        self.reservations.append(kw)
        if self.fail:
            raise ConnectionError("deliberately private error")

    async def commit(self, **kw):
        self.commits.append(kw)


@pytest.mark.asyncio
async def test_local_limit_before_shared_and_does_not_recycle(tmp_path):
    shared = Shared()
    budget = CurrentScopedBudget(shared, tmp_path / "journal.jsonl")
    token = _ACTIVE.set(("aggregator_normal", "gpt-6-luna"))
    try:
        await budget.reserve(
            provider="openai",
            reservation_id="one",
            reserved_microusd=600_000,
            monthly_budget_microusd=12_000_000,
        )
        await budget.commit(provider="openai", reservation_id="one", actual_microusd=1)
        with pytest.raises(ValueError, match="PRECALL"):
            await budget.reserve(
                provider="openai",
                reservation_id="two",
                reserved_microusd=600_000,
                monthly_budget_microusd=12_000_000,
            )
    finally:
        _ACTIVE.reset(token)
    assert len(shared.reservations) == 1
    assert (await budget.snapshot()).attempts[0].actual_microusd == 1


@pytest.mark.asyncio
async def test_ambiguous_shared_reserve_remains_unknown(tmp_path):
    budget = CurrentScopedBudget(Shared(fail=True), tmp_path / "journal.jsonl")
    token = _ACTIVE.set(("text_scouts", "gpt-6-luna"))
    try:
        with pytest.raises(ConnectionError):
            await budget.reserve(
                provider="openai",
                reservation_id="one",
                reserved_microusd=100,
                monthly_budget_microusd=12_000_000,
            )
    finally:
        _ACTIVE.reset(token)
    assert (await budget.snapshot()).attempts[0].state == "UNKNOWN"
    assert "private error" not in (tmp_path / "journal.jsonl").read_text()


@pytest.mark.asyncio
async def test_no_implicit_route_no_paid_call(tmp_path):
    shared = Shared()
    budget = CurrentScopedBudget(shared, tmp_path / "journal.jsonl")
    with pytest.raises(ValueError, match="EXPLICIT"):
        await budget.reserve(
            provider="openai", reservation_id="one", reserved_microusd=10, monthly_budget_microusd=12_000_000
        )
    assert not shared.reservations
    assert (tmp_path / "journal.jsonl").exists()
    assert (tmp_path / "journal.jsonl").read_bytes() == b""


def test_existing_key_unique_and_memory_only(tmp_path):
    path = tmp_path / "keys.txt"
    key = "sk-proj-" + "a" * 24
    path.write_text("OpenAI=" + key)
    assert read_existing_openai_key(path) == key
    assert sorted(p.name for p in tmp_path.iterdir()) == ["keys.txt"]
    path.write_text(key + "\n" + "sk-proj-" + "b" * 24)
    with pytest.raises(ValueError, match="NOT_UNIQUE"):
        read_existing_openai_key(path)


def test_existing_journal_not_reused(tmp_path):
    path = tmp_path / "journal.jsonl"
    path.write_text(json.dumps({"retained": True}))
    with pytest.raises(ValueError, match="CREATE_ONLY"):
        CurrentScopedBudget(Shared(), path)


@pytest.mark.asyncio
async def test_failed_original_source_prevents_even_provider_attempt_and_reservation(tmp_path):
    from types import SimpleNamespace

    gateway = RecordingCurrentGateway(SimpleNamespace(), tmp_path)

    def failed_source():
        raise ValueError("ORIGINAL_SOURCE_HORIZON_INSUFFICIENT_BEFORE_PAID_CALL")

    gateway.source_guard = failed_source
    with pytest.raises(ValueError, match="SOURCE_HORIZON"):
        await gateway.complete(system="synthetic-test", user="synthetic-test", workload=object())
    assert gateway._index == 0
    assert not list(tmp_path.iterdir())
