"""Opt-in current-chain resources; one shared budget, no trading authority.

The normal runtime, old queues and credentials on disk are never modified.
Only this run's SIM repository may be migrated by the explicit bootstrap.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from kairos_llm.budget import BudgetedLLMGateway
from kairos_llm.config import LLMSettings
from kairos_llm.gateway import LLMGateway
from kairos_llm.models import ModelRouter, Provider
from kairos_persistence.source_state import QUALIFICATION_CAMPAIGN_ID, SourceStateRepository
from kairos_persistence.usage_budget import CampaignLLMUsageBudget

from .current_runner import ProviderAttempt, UsageSnapshot

LOCAL_CAP_MICROUSD = 1_000_000
MAX_ATTEMPTS = 24
HISTORICAL_COST_MICROUSD = 1_984
HISTORICAL_EVIDENCE = "8269e2138dd331639888f8a3277c3229d0bc046d74af9b176ac5d78d23dcb185"
_ACTIVE = contextvars.ContextVar("kairos_current_provider_call", default=None)


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def append_evidence(path: Path, value: Any) -> None:
    with path.open("ab") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def read_existing_openai_key(path: Path) -> str:
    """Read the authorized existing file in memory; never echo any values.

    A unique project key is required. Ambiguous credentials are not guessed.
    No new key/project or plaintext secret copy is created.
    """
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("EXISTING_CREDENTIAL_FILE_UNAVAILABLE")
    raw = path.read_text(encoding="utf-8-sig")
    found = set(re.findall(r"(?<![A-Za-z0-9_-])sk-proj-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])", raw))
    if len(found) != 1:
        raise ValueError("EXISTING_OPENAI_PROJECT_KEY_NOT_UNIQUE")
    return found.pop()


async def verify_existing_budget(pool: Any) -> dict[str, Any]:
    """Read-only immutable adoption check; no schema/adoption/reset operation."""
    async with pool.acquire() as connection:
        async with connection.transaction(readonly=True):
            await connection.execute("SET LOCAL statement_timeout='5s'")
            row = await connection.fetchrow(
                "SELECT campaign_id,budget_microusd,historical_cost_microusd,"
                "historical_evidence_sha256 FROM campaign_source_budgets WHERE source='openai'"
            )
            if row is None or tuple(row) != (
                QUALIFICATION_CAMPAIGN_ID,
                12_000_000,
                HISTORICAL_COST_MICROUSD,
                HISTORICAL_EVIDENCE,
            ):
                raise ValueError("EXISTING_BUDGET_ADOPTION_MISMATCH")
    repository = SourceStateRepository(pool, campaign_id=QUALIFICATION_CAMPAIGN_ID)
    return asdict(await repository.campaign_usage("openai"))


@dataclass
class _Attempt:
    reservation_id: str
    provider: str
    workload: str
    model: str
    state: str
    reserved_microusd: int
    actual_microusd: int = 0


class CurrentScopedBudget:
    """Hard pre-call local envelope AND the unchanged cumulative authority.

    Uncertain reservations remain held. The local cap is conservative: even
    settled surplus is not reused within this one bounded verification.
    """

    def __init__(self, shared: Any, journal: Path):
        if journal.exists():
            raise ValueError("CREATE_ONLY_BUDGET_JOURNAL_REQUIRED")
        # Claim the identity immediately, before a competing builder or first
        # request can reuse an empty, not-yet-created journal on restart.
        with journal.open("xb"):
            pass
        self.shared = shared
        self.journal = journal
        self._attempts: dict[str, _Attempt] = {}
        self._held = 0
        self._lock = asyncio.Lock()

    async def reserve(self, *, provider, reservation_id, reserved_microusd, monthly_budget_microusd):
        active = _ACTIVE.get()
        if active is None or provider != "openai" or monthly_budget_microusd != 12_000_000:
            raise ValueError("EXPLICIT_OPENAI_ROUTE_AND_EXISTING_BUDGET_REQUIRED")
        if type(reserved_microusd) is not int or reserved_microusd <= 0:
            raise ValueError("INVALID_RESERVATION")
        async with self._lock:
            if (
                reservation_id in self._attempts
                or len(self._attempts) >= MAX_ATTEMPTS
                or self._held + reserved_microusd > LOCAL_CAP_MICROUSD
            ):
                raise ValueError("LOCAL_PRECALL_ENVELOPE_EXCEEDED")
            workload, model = active
            attempt = _Attempt(reservation_id, provider, workload, model, "UNKNOWN", reserved_microusd)
            append_evidence(
                self.journal,
                {
                    **asdict(attempt),
                    "event": "BEFORE_SHARED_RESERVE",
                    "observed_ms": time.time_ns() // 1_000_000,
                },
            )
            self._attempts[reservation_id] = attempt
            self._held += reserved_microusd
            # A failed/ambiguous shared reserve is never retried or released here.
            await self.shared.reserve(
                provider=provider,
                reservation_id=reservation_id,
                reserved_microusd=reserved_microusd,
                monthly_budget_microusd=monthly_budget_microusd,
            )
            attempt.state = "RESERVED"
            append_evidence(
                self.journal,
                {**asdict(attempt), "event": "SHARED_RESERVED", "observed_ms": time.time_ns() // 1_000_000},
            )

    async def commit(self, *, provider, reservation_id, actual_microusd):
        async with self._lock:
            attempt = self._attempts[reservation_id]
            if (
                provider != "openai"
                or attempt.state != "RESERVED"
                or type(actual_microusd) is not int
                or not 0 <= actual_microusd <= attempt.reserved_microusd
            ):
                raise ValueError("INVALID_SHARED_SETTLEMENT")
            await self.shared.commit(
                provider=provider, reservation_id=reservation_id, actual_microusd=actual_microusd
            )
            attempt.state = "COMMITTED"
            attempt.actual_microusd = actual_microusd
            append_evidence(
                self.journal,
                {**asdict(attempt), "event": "SHARED_COMMITTED", "observed_ms": time.time_ns() // 1_000_000},
            )

    async def snapshot(self) -> UsageSnapshot:
        return UsageSnapshot(tuple(ProviderAttempt(**asdict(a)) for a in self._attempts.values()))


class RecordingCurrentGateway:
    """Actual native gateway wrapper retaining public input and exact responses.

    No provider exception string, client settings, auth headers or key is saved.
    Method invocation alone is not counted as a successful model result.
    """

    def __init__(self, native: BudgetedLLMGateway, evidence_root: Path):
        self.native = native
        self.evidence_root = evidence_root
        self._index = 0
        self._consecutive_failures = 0

    @property
    def settings(self):
        return self.native.settings

    @property
    def router(self):
        return self.native.router

    @property
    def accountant(self):
        return self.native.accountant

    async def complete(self, *, system, user, effort=None, workload=None, schema=None):
        if workload is None or self._consecutive_failures >= 2:
            raise ValueError("CURRENT_RUN_STOPPED_AFTER_FAILURE_LIMIT")
        route = self.router.resolve(effort, workload=workload)
        if route.choice.provider is not Provider.OPENAI:
            raise ValueError("CURRENT_RUN_OPENAI_ONLY")
        self._index += 1
        index = self._index
        if index > MAX_ATTEMPTS:
            raise ValueError("CURRENT_RUN_CALL_LIMIT")
        request = {
            "index": index,
            "system": system,
            "user": user,
            "schema": schema.model_json_schema() if schema else None,
            "route": asdict(route),
            "requested_ms": time.time_ns() // 1_000_000,
        }
        raw = canonical(request)
        request_sha = hashlib.sha256(raw).hexdigest()
        path = self.evidence_root / f"provider-{index:02d}.request.json"
        with path.open("xb") as stream:
            stream.write(raw + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        token = _ACTIVE.set((workload.value, route.choice.model))
        try:
            result = await self.native.complete(
                system=system, user=user, effort=effort, workload=workload, schema=schema
            )
            parsed = result.parsed
            if hasattr(parsed, "model_dump"):
                parsed = parsed.model_dump(mode="json")
            payload = asdict(result)
            payload["parsed"] = parsed
            append_evidence(
                self.evidence_root / "provider-results.jsonl",
                {
                    "index": index,
                    "request_sha256": request_sha,
                    "completed_ms": time.time_ns() // 1_000_000,
                    "state": "ACTUAL_RESPONSE",
                    "result": payload,
                },
            )
            self._consecutive_failures = 0
            return result
        except BaseException as exc:
            self._consecutive_failures += 1
            append_evidence(
                self.evidence_root / "provider-results.jsonl",
                {
                    "index": index,
                    "request_sha256": request_sha,
                    "completed_ms": time.time_ns() // 1_000_000,
                    "state": "FAILED_OR_UNKNOWN",
                    "exception_type": type(exc).__name__,
                },
            )
            raise
        finally:
            _ACTIVE.reset(token)

    async def close(self):
        await self.native.close()


def build_existing_gateway(*, key: str, budget_pool: Any, evidence_root: Path):
    repository = SourceStateRepository(budget_pool, campaign_id=QUALIFICATION_CAMPAIGN_ID)
    budget = CurrentScopedBudget(CampaignLLMUsageBudget(repository), evidence_root / "budget.jsonl")
    gateway = LLMGateway(
        LLMSettings(
            _env_file=None,
            openai_api_key=key,
            openai_base_url="https://api.openai.com/v1",
            max_retries=0,
            max_output_tokens=8192,
            request_timeout_s=45,
        ),
        router=ModelRouter(),
    )
    wrapped = RecordingCurrentGateway(BudgetedLLMGateway(gateway, budget), evidence_root)
    return wrapped, budget
