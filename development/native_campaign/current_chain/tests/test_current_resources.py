"""Offline boundary/failure checks. No Docker, socket, DB or provider is called."""

import asyncio
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from kairos_llm.budget import BudgetedLLMGateway
from kairos_llm.config import LLMSettings
from kairos_llm.models import LLMWorkload, ModelRouter
from kairos_llm.pricing import PriceTable
from kairos_llm.schemas import LLMResult, TokenUsage

from kairos_native_campaign import current_resources as resources
from kairos_native_campaign import current_runtime as runtime

IDENTITY = "a" * 32
PG_IMAGE = "sha256:" + "b" * 64
PY_IMAGE = "sha256:" + "c" * 64


class FakeDocker:
    def __init__(self, fail_create=None, fail_stop=False, foreign=False):
        self.calls, self.containers = [], {}
        self.fail_create, self.fail_stop, self.foreign = fail_create, fail_stop, foreign

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        if args[:2] == ("image", "inspect"):
            return PY_IMAGE
        if args[0] == "ps":
            return "kairos-shadow-gate-timescaledb-1\nlegacy-do-not-touch"
        if args[0] == "run":
            name = args[args.index("--name") + 1]
            is_sim = "-sim-" in name
            if not is_sim:
                assert args[args.index("--network") + 1] == "bridge"
            container_id = ("d" if is_sim else "e") * 64
            self.containers[name] = {
                "Id": container_id,
                "Name": "/" + name,
                "Image": PG_IMAGE if is_sim else PY_IMAGE,
                "Config": {
                    "Labels": {"kairos.current-verification": "foreign" if self.foreign else IDENTITY}
                },
            }
            assert "127.0.0.1::5432" in args or "127.0.0.1::15432" in args
            assert not any("fixture-only-password" in value for value in args)
            if self.fail_create == ("sim" if is_sim else "tunnel"):
                raise RuntimeError("AMBIGUOUS_FIXTURE_CREATE")
            return container_id
        if args[:2] == ("network", "connect"):
            assert args == ("network", "connect", "kairos-shadow-gate_data", "e" * 64)
            assert any(c["Id"] == args[-1] for c in self.containers.values())
            return ""
        if args[0] == "inspect":
            format_, name = args[args.index("--format") + 1], args[-1]
            if name == "kairos-shadow-gate-timescaledb-1":
                if format_ == "{{json .NetworkSettings.Networks}}":
                    return json.dumps({"kairos-shadow-gate_data": {}})
                if format_ == "{{.Image}}":
                    return PG_IMAGE
            if format_ == "{{json .NetworkSettings.Ports}}":
                port = "5432" if "-sim-" in name else "15432"
                return json.dumps({port + "/tcp": [{"HostIp": "127.0.0.1", "HostPort": "25432"}]})
            if format_ == "{{json .}}":
                return json.dumps(self.containers[name])
        if args[0] in {"stop", "rm"}:
            assert args[-1] in {"d" * 64, "e" * 64}
            if args[0] == "stop" and self.fail_stop:
                raise RuntimeError("FIXTURE_STOP_FAILURE")
            return args[-1]
        raise AssertionError("Unexpected offline Docker shape: " + repr(args))


def install_resource_fakes(
    monkeypatch, *, fail_create=None, fail_close=False, fail_stop=False, foreign=False
):
    docker = FakeDocker(fail_create, fail_stop, foreign)
    state = SimpleNamespace(migrations=[], closes=[], budget_reads=0, pool_dsns=[], sim_dsns=[])
    monkeypatch.setattr(resources, "docker", docker)
    monkeypatch.setattr(resources, "uuid4", lambda: SimpleNamespace(hex=IDENTITY))
    original_read = Path.read_text

    def read(path, *args, **kwargs):
        if str(path).replace("\\", "/") == "D:/Kairos/runtime/shadow-gate/secrets/postgres_password":
            return "fixture-only-password"
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)

    class Connection:
        async def fetchval(self, sql):
            assert sql.startswith("SELECT ")
            return "kairos_sim_current_" + IDENTITY if "current_database" in sql else 0

        async def close(self):
            state.closes.append("readiness")

    async def connect(dsn, **kwargs):
        state.sim_dsns.append(dsn)
        assert dsn.endswith("/kairos_sim_current_" + IDENTITY)
        return Connection()

    class Pool:
        async def close(self):
            state.closes.append("budget")
            if fail_close:
                raise RuntimeError("FIXTURE_CLOSE_FAILURE")

    async def pool(dsn, **kwargs):
        state.pool_dsns.append(dsn)
        assert dsn.endswith("/kairos")
        return Pool()

    async def verify(_pool):
        state.budget_reads += 1
        return {"committed_cost_microusd": 123, "reserved_cost_microusd": 456}

    class Database:
        def __init__(self, settings, migration_profile):
            self.settings, self.profile, self.pool = settings, migration_profile, object()
            assert str(settings.database_url).endswith("/kairos_sim_current_" + IDENTITY)

        async def connect(self):
            pass

        async def migrate(self):
            state.migrations.append((str(self.settings.database_url), self.profile))

        async def verify_schema(self):
            pass

        async def close(self):
            state.closes.append("sim")
            if fail_close:
                raise RuntimeError("FIXTURE_CLOSE_FAILURE")

    monkeypatch.setattr(resources.asyncpg, "connect", connect)
    monkeypatch.setattr(resources.asyncpg, "create_pool", pool)
    monkeypatch.setattr(resources, "verify_existing_budget", verify)
    monkeypatch.setattr(resources, "Database", Database)
    monkeypatch.setattr(resources, "SimulationRepository", lambda pool: object())
    return docker, state


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["tunnel", "sim"])
async def test_uncertain_create_is_cleaned_by_exact_owned_identity(monkeypatch, tmp_path, stage):
    docker, state = install_resource_fakes(monkeypatch, fail_create=stage)
    with pytest.raises(RuntimeError, match="AMBIGUOUS_FIXTURE_CREATE"):
        async with resources.isolated_resources(tmp_path):
            pytest.fail("ambiguous creation must never yield")
    assert ("rm", "--force", "e" * 64) in docker.calls
    assert not state.migrations and not state.pool_dsns
    if stage == "sim":
        assert ("stop", "--time", "10", "d" * 64) in docker.calls


@pytest.mark.asyncio
async def test_own_sim_only_migration_and_all_failure_cleanups_continue(monkeypatch, tmp_path):
    docker, state = install_resource_fakes(monkeypatch, fail_close=True, fail_stop=True)
    with pytest.raises(RuntimeError, match="FIXTURE_BODY_FAILURE"):
        async with resources.isolated_resources(tmp_path) as opened:
            assert "fixture-only-password" not in repr(opened)
            raise RuntimeError("FIXTURE_BODY_FAILURE")
    assert len(state.migrations) == 1
    dsn, profile = state.migrations[0]
    assert dsn.endswith("/kairos_sim_current_" + IDENTITY)
    assert profile is resources.MigrationProfile.SIMULATOR
    assert state.budget_reads == 2  # before AND after a failed run
    assert state.closes == ["readiness", "sim", "budget"]
    assert ("rm", "--force", "e" * 64) in docker.calls
    assert not any("legacy-do-not-touch" in call for call in docker.calls)
    evidence = (tmp_path / "resources.jsonl").read_text()
    assert "CUMULATIVE_BUDGET_AFTER" in evidence
    assert "fixture-only-password" not in evidence


@pytest.mark.asyncio
async def test_foreign_labels_prevent_destructive_cleanup(monkeypatch, tmp_path):
    docker, _state = install_resource_fakes(monkeypatch, fail_create="tunnel", foreign=True)
    with pytest.raises(RuntimeError, match="AMBIGUOUS_FIXTURE_CREATE"):
        async with resources.isolated_resources(tmp_path):
            pytest.fail("no yield")
    assert not any(call[0] in {"stop", "rm"} for call in docker.calls)
    assert "CLEANUP_UNCONFIRMED" in (tmp_path / "resources.jsonl").read_text()


@pytest.mark.asyncio
async def test_network_attachment_failure_still_removes_exact_own_tunnel(monkeypatch, tmp_path):
    docker, state = install_resource_fakes(monkeypatch)

    def failing_network(*args, **kwargs):
        if args[:2] == ("network", "connect"):
            assert args[-1] == "e" * 64
            raise RuntimeError("FIXTURE_UNCERTAIN_NETWORK_CONNECT")
        return docker(*args, **kwargs)

    monkeypatch.setattr(resources, "docker", failing_network)
    with pytest.raises(RuntimeError, match="UNCERTAIN_NETWORK"):
        async with resources.isolated_resources(tmp_path):
            pytest.fail("no yield")
    assert ("rm", "--force", "e" * 64) in docker.calls
    assert not state.migrations and not state.pool_dsns


@pytest.mark.asyncio
async def test_network_attachment_requires_owner_proof_before_connect(monkeypatch, tmp_path):
    docker, _state = install_resource_fakes(monkeypatch, foreign=True)
    with pytest.raises(ValueError, match="OWNERSHIP_NOT_PROVEN"):
        async with resources.isolated_resources(tmp_path):
            pytest.fail("no yield")
    assert not any(call[0] in {"network", "rm", "stop"} for call in docker.calls)


@pytest.mark.parametrize(
    "rows", [[], [{"HostIp": "0.0.0.0", "HostPort": "55002"}], [{"HostIp": "::", "HostPort": "55002"}]]
)
def test_port_parser_still_refuses_empty_or_wildcard_bindings(monkeypatch, rows):
    monkeypatch.setattr(resources, "docker", lambda *args, **kwargs: json.dumps({"15432/tcp": rows}))
    with pytest.raises(ValueError, match="LOOPBACK_BIND_REQUIRED"):
        resources._port("fixture-owned", "15432")


def test_docker_failures_never_echo_stderr_or_secret_argv(monkeypatch):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired(["docker", "fixture-secret"], 1, stderr="fixture-secret")

    monkeypatch.setattr(resources.subprocess, "run", run)
    with pytest.raises(RuntimeError) as caught:
        resources.docker("inspect", "fixture-secret")
    assert "fixture-secret" not in str(caught.value)


@pytest.mark.parametrize("changed", ["Id", "Name", "Image", "Labels"])
def test_cleanup_refuses_any_unproven_container_identity(monkeypatch, changed):
    name = "kairos-current-sim-" + IDENTITY[:12]
    value = {
        "Id": "d" * 64,
        "Name": "/" + name,
        "Image": PG_IMAGE,
        "Config": {"Labels": {"kairos.current-verification": IDENTITY}},
    }
    if changed == "Labels":
        value["Config"]["Labels"] = {}
    else:
        value[changed] = "foreign-or-invalid"
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        assert args[0] == "inspect"
        return json.dumps(value)

    monkeypatch.setattr(resources, "docker", docker)
    with pytest.raises(ValueError, match="OWNERSHIP_NOT_PROVEN"):
        resources._cleanup_resource(name=name, identity=IDENTITY, image=PG_IMAGE, retain=True)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_wrong_actual_database_is_never_migrated(monkeypatch, tmp_path):
    docker, state = install_resource_fakes(monkeypatch)

    class WrongConnection:
        async def fetchval(self, sql):
            return "legacy" if "current_database" in sql else 0

        async def close(self):
            pass

    async def connect(*args, **kwargs):
        return WrongConnection()

    monkeypatch.setattr(resources.asyncpg, "connect", connect)
    with pytest.raises(ValueError, match="WRONG_TARGET"):
        async with resources.isolated_resources(tmp_path):
            pytest.fail("no yield")
    assert not state.migrations and not state.pool_dsns
    assert ("rm", "--force", "e" * 64) in docker.calls


class SharedBudget:
    def __init__(self, uncertain=False):
        self.events, self.uncertain = [], uncertain

    async def reserve(self, **kwargs):
        self.events.append(("reserve", kwargs))
        if self.uncertain:
            raise RuntimeError("FIXTURE_UNCERTAIN_SHARED_RESERVE")

    async def commit(self, **kwargs):
        self.events.append(("commit", kwargs))


@pytest.mark.asyncio
async def test_local_budget_cap_is_before_shared_reserve_and_never_reuses_surplus(tmp_path):
    shared = SharedBudget()
    path = tmp_path / "budget.jsonl"
    budget = runtime.CurrentScopedBudget(shared, path)
    with pytest.raises(ValueError, match="CREATE_ONLY"):
        runtime.CurrentScopedBudget(shared, path)
    token = runtime._ACTIVE.set(("fixture", "fixture"))
    try:
        await budget.reserve(
            provider="openai",
            reservation_id="one",
            reserved_microusd=1_000_000,
            monthly_budget_microusd=12_000_000,
        )
        await budget.commit(provider="openai", reservation_id="one", actual_microusd=123)
        with pytest.raises(ValueError, match="ENVELOPE"):
            await budget.reserve(
                provider="openai",
                reservation_id="two",
                reserved_microusd=1,
                monthly_budget_microusd=12_000_000,
            )
    finally:
        runtime._ACTIVE.reset(token)
    assert [event for event, _ in shared.events] == ["reserve", "commit"]
    attempt = (await budget.snapshot()).attempts[0]
    assert attempt.actual_microusd == 123 and attempt.reserved_microusd == 1_000_000


@pytest.mark.asyncio
async def test_uncertain_shared_reservation_is_held_and_never_retried(tmp_path):
    shared = SharedBudget(uncertain=True)
    budget = runtime.CurrentScopedBudget(shared, tmp_path / "budget.jsonl")
    token = runtime._ACTIVE.set(("fixture", "fixture"))
    try:
        with pytest.raises(RuntimeError, match="UNCERTAIN"):
            await budget.reserve(
                provider="openai",
                reservation_id="one",
                reserved_microusd=100,
                monthly_budget_microusd=12_000_000,
            )
        with pytest.raises(ValueError, match="ENVELOPE"):
            await budget.reserve(
                provider="openai",
                reservation_id="one",
                reserved_microusd=100,
                monthly_budget_microusd=12_000_000,
            )
    finally:
        runtime._ACTIVE.reset(token)
    assert len(shared.events) == 1
    assert (await budget.snapshot()).attempts[0].state == "UNKNOWN"


class PhysicalFixture:
    def __init__(self):
        self.settings = LLMSettings(
            _env_file=None, max_retries=0, max_output_tokens=32, openai_api_key=None, deepseek_api_key=None
        )
        self.router, self.accountant, self.calls = ModelRouter(), None, 0

    async def complete(self, **kwargs):
        self.calls += 1
        route = self.router.resolve(kwargs.get("effort"), workload=kwargs["workload"])
        usage = TokenUsage(input_tokens=100, output_tokens=5, cache_write_tokens=100)
        return LLMResult(
            content='{"fixture":true}',
            parsed={"fixture": True},
            model=route.choice.model,
            effort=route.effort.value,
            usage=usage,
            provider=route.choice.provider.value,
            cost_usd=PriceTable().cost(route.choice.model, usage),
            request_id="fixture-request",
        )

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_real_budget_wrapper_settles_reported_usage_and_caps_before_physical_call(
    tmp_path, monkeypatch
):
    shared, physical = SharedBudget(), PhysicalFixture()
    scoped = runtime.CurrentScopedBudget(shared, tmp_path / "budget.jsonl")
    gateway = runtime.RecordingCurrentGateway(BudgetedLLMGateway(physical, scoped), tmp_path)
    result = await gateway.complete(
        system="Fixture only", user="Fixture only", workload=LLMWorkload.TEXT_SCOUTS
    )
    assert physical.calls == 1 and result.budget_reservation_id
    attempt = (await scoped.snapshot()).attempts[0]
    assert attempt.state == "COMMITTED" and attempt.actual_microusd > 0
    assert shared.events[1][1]["actual_microusd"] == attempt.actual_microusd
    monkeypatch.setattr(runtime, "LOCAL_CAP_MICROUSD", scoped._held)
    with pytest.raises(ValueError, match="ENVELOPE"):
        await gateway.complete(system="Fixture only", user="Fixture only", workload=LLMWorkload.TEXT_SCOUTS)
    assert physical.calls == 1


@pytest.mark.asyncio
async def test_concurrent_completions_keep_original_request_indices(monkeypatch, tmp_path):
    class OutOfOrder(PhysicalFixture):
        async def complete(self, **kwargs):
            result = await super().complete(**kwargs)
            if kwargs["user"] == "FIRST":
                await asyncio.sleep(0.01)
            result.request_id = kwargs["user"]
            return result

    scoped = runtime.CurrentScopedBudget(SharedBudget(), tmp_path / "budget.jsonl")
    gateway = runtime.RecordingCurrentGateway(BudgetedLLMGateway(OutOfOrder(), scoped), tmp_path)
    await asyncio.gather(
        *(
            gateway.complete(system="Fixture only", user=user, workload=LLMWorkload.TEXT_SCOUTS)
            for user in ("FIRST", "SECOND")
        )
    )
    results = [json.loads(line) for line in (tmp_path / "provider-results.jsonl").read_text().splitlines()]
    assert {row["index"]: row["result"]["request_id"] for row in results} == {1: "FIRST", 2: "SECOND"}


@pytest.mark.asyncio
async def test_existing_budget_adoption_verification_is_read_only(monkeypatch):
    events = []

    class Transaction:
        async def __aenter__(self):
            pass

        async def __aexit__(self, *args):
            pass

    class Connection(Transaction):
        def transaction(self, **kwargs):
            assert kwargs == {"readonly": True}
            return Transaction()

        async def execute(self, sql):
            events.append(sql)
            assert sql.startswith("SET LOCAL statement_timeout")

        async def fetchrow(self, sql):
            events.append(sql)
            assert sql.startswith("SELECT campaign_id")
            return (
                runtime.QUALIFICATION_CAMPAIGN_ID,
                12_000_000,
                runtime.HISTORICAL_COST_MICROUSD,
                runtime.HISTORICAL_EVIDENCE,
            )

        async def __aenter__(self):
            return self

    class Pool:
        def acquire(self):
            return Connection()

    @dataclass
    class Usage:
        committed_cost_microusd: int = 123
        reserved_cost_microusd: int = 456

    class Repository:
        def __init__(self, pool, campaign_id):
            assert campaign_id == runtime.QUALIFICATION_CAMPAIGN_ID

        async def campaign_usage(self, source):
            assert source == "openai"
            return Usage()

    monkeypatch.setattr(runtime, "SourceStateRepository", Repository)
    result = await runtime.verify_existing_budget(Pool())
    assert result == {"committed_cost_microusd": 123, "reserved_cost_microusd": 456}
    assert len(events) == 2 and not any(
        "INSERT" in sql or "UPDATE" in sql or "CREATE" in sql for sql in events
    )
