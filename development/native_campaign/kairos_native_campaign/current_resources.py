"""Explicit, bounded resources for one opt-in current-system verification.

No existing container is restarted, reconfigured or migrated. An ephemeral
loopback-only tunnel reaches the unchanged existing budget authority. New DDL
is restricted to a fresh, owned, uniquely named SIM PostgreSQL container.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import asyncpg
from kairos_persistence.config import PersistenceSettings
from kairos_persistence.database import Database, MigrationProfile
from kairos_persistence.simulation_repository import SimulationRepository

from .current_runtime import append_evidence, verify_existing_budget

_FORWARDER = """
import selectors,socket,socketserver,time
deadline=time.monotonic()+1800
class Handler(socketserver.BaseRequestHandler):
 def handle(self):
  upstream=socket.create_connection(('timescaledb',5432),timeout=10)
  with upstream,selectors.DefaultSelector() as sel:
   self.request.settimeout(10); upstream.settimeout(10)
   sel.register(self.request,selectors.EVENT_READ,upstream)
   sel.register(upstream,selectors.EVENT_READ,self.request)
   while time.monotonic()<deadline:
    for key,_ in sel.select(1):
     data=key.fileobj.recv(65536)
     if not data:return
     key.data.sendall(data)
class Server(socketserver.ThreadingTCPServer):
 allow_reuse_address=True
 daemon_threads=True
with Server(('0.0.0.0',15432),Handler) as server:
 server.timeout=1
 while time.monotonic()<deadline:server.handle_request()
"""


def docker(*args: str, timeout: int = 30, env: dict[str, str] | None = None) -> str:
    """Fixed bounded CLI; never forward raw errors which may contain secrets."""
    try:
        result = subprocess.run(
            ["docker", *args],
            capture_output=True,
            timeout=timeout,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("CURRENT_RESOURCE_DOCKER_UNAVAILABLE") from None
    if result.returncode or len(result.stdout) > 64 * 1024:
        raise RuntimeError("CURRENT_RESOURCE_DOCKER_REFUSED")
    return result.stdout.strip()


def _port(name: str, container_port: str) -> int:
    value = json.loads(docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", name))
    rows = value[container_port + "/tcp"]
    if len(rows) != 1 or rows[0]["HostIp"] != "127.0.0.1":
        raise ValueError("CURRENT_RESOURCE_LOOPBACK_BIND_REQUIRED")
    return int(rows[0]["HostPort"])


@dataclass
class CurrentResources:
    budget_pool: asyncpg.Pool
    sim_database: Database
    simulation_repository: SimulationRepository
    sim_container: str
    database_name: str
    sim_dsn: str = field(repr=False)


def _owned_container_id(*, name: str, identity: str, image: str) -> str:
    """Resolve a fresh named resource only after its exact ownership proof."""
    if re.fullmatch(r"[0-9a-f]{32}", identity) is None or name not in {
        "kairos-current-budget-tunnel-" + identity[:12],
        "kairos-current-sim-" + identity[:12],
    }:
        raise ValueError("CURRENT_RESOURCE_CLEANUP_SCOPE_INVALID")
    state = json.loads(docker("inspect", "--format", "{{json .}}", name))
    container_id = state.get("Id", "")
    if (
        re.fullmatch(r"[0-9a-f]{64}", container_id) is None
        or state.get("Name") != "/" + name
        or state.get("Image") != image
        or state.get("Config", {}).get("Labels", {}).get("kairos.current-verification") != identity
    ):
        raise ValueError("CURRENT_RESOURCE_CLEANUP_OWNERSHIP_NOT_PROVEN")
    return container_id


def _cleanup_resource(*, name: str, identity: str, image: str, retain: bool) -> str:
    """Inspect even uncertain creates, then address only the exact owned ID."""
    container_id = _owned_container_id(name=name, identity=identity, image=image)
    if retain:
        docker("stop", "--time", "10", container_id, timeout=30)
        return "OWNED_SIM_STOPPED_RETAINED"
    docker("rm", "--force", container_id)
    return "OWNED_CREDENTIAL_FREE_TUNNEL_REMOVED"


@asynccontextmanager
async def isolated_resources(evidence_root: Path):
    """Stop/retain only our new SIM container; remove only our credential-free tunnel."""
    identity = uuid4().hex
    tunnel_name = "kairos-current-budget-tunnel-" + identity[:12]
    sim_name = "kairos-current-sim-" + identity[:12]
    sim_database_name = "kairos_sim_current_" + identity
    attempted: dict[str, tuple[str, bool]] = {}
    pool = sim = None
    password = secrets.token_urlsafe(32)
    # These two existing identities are observations, not mutation targets.
    budget_network = json.loads(
        docker(
            "inspect", "--format", "{{json .NetworkSettings.Networks}}", "kairos-shadow-gate-timescaledb-1"
        )
    )
    if "kairos-shadow-gate_data" not in budget_network:
        raise ValueError("EXISTING_BUDGET_NETWORK_MISMATCH")
    python_image = docker("image", "inspect", "--format", "{{.Id}}", "python:3.13-slim")
    pg_image = docker("inspect", "--format", "{{.Image}}", "kairos-shadow-gate-timescaledb-1")
    before_names = set(docker("ps", "-a", "--format", "{{.Names}}").splitlines())
    if {tunnel_name, sim_name} & before_names:
        raise ValueError("FRESH_RESOURCE_IDENTITY_COLLISION")
    try:
        # Track before the CLI call: a timeout can follow a successful create.
        attempted[tunnel_name] = (python_image, False)
        docker(
            "run",
            "-d",
            "--name",
            tunnel_name,
            "--label",
            "kairos.current-verification=" + identity,
            "--network",
            "bridge",
            "--publish",
            "127.0.0.1::15432",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--cpus",
            "0.1",
            "--memory",
            "64m",
            "--pids-limit",
            "32",
            python_image,
            "python",
            "-u",
            "-c",
            _FORWARDER,
        )
        # Docker does not publish host ports on this existing internal network.
        # Start on bridge, then attach only our exact newly verified tunnel ID;
        # no existing container or its network attachments are changed.
        tunnel_id = _owned_container_id(name=tunnel_name, identity=identity, image=python_image)
        tunnel_port = _port(tunnel_name, "15432")
        docker("network", "connect", "kairos-shadow-gate_data", tunnel_id)
        if _port(tunnel_name, "15432") != tunnel_port:
            raise ValueError("CURRENT_RESOURCE_LOOPBACK_BIND_CHANGED")
        # Generated disposable SIM credential is passed through the child environment,
        # not argv, logs or a persistent plaintext credential file.
        child_env = os.environ.copy()
        child_env["POSTGRES_PASSWORD"] = password
        attempted[sim_name] = (pg_image, True)
        docker(
            "run",
            "-d",
            "--name",
            sim_name,
            "--label",
            "kairos.current-verification=" + identity,
            "--publish",
            "127.0.0.1::5432",
            "--cpus",
            "1",
            "--memory",
            "768m",
            "--pids-limit",
            "128",
            "--security-opt",
            "no-new-privileges",
            "--env",
            "POSTGRES_PASSWORD",
            "--env",
            "POSTGRES_USER=kairos",
            "--env",
            "POSTGRES_DB=" + sim_database_name,
            pg_image,
            env=child_env,
        )
        child_env.pop("POSTGRES_PASSWORD", None)
        sim_port = _port(sim_name, "5432")
        existing_password = (
            Path("D:/Kairos/runtime/shadow-gate/secrets/postgres_password").read_text().strip()
        )
        if not existing_password:
            raise ValueError("EXISTING_BUDGET_CREDENTIAL_UNAVAILABLE")
        budget_dsn = (
            "postgresql://kairos:" + quote(existing_password, safe="") + f"@127.0.0.1:{tunnel_port}/kairos"
        )
        sim_dsn = (
            "postgresql://kairos:" + quote(password, safe="") + f"@127.0.0.1:{sim_port}/{sim_database_name}"
        )
        # Each connect below is to a uniquely created resource, never a retry of
        # an uncertain model request, trade or migration.
        deadline = time.monotonic() + 45
        while True:
            try:
                connection = await asyncpg.connect(sim_dsn, timeout=3)
                break
            except (OSError, asyncpg.PostgresError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("NEW_SIM_DATABASE_START_TIMEOUT") from None
                await asyncio.sleep(0.5)
        try:
            actual_name = await connection.fetchval("SELECT current_database()")
            tables = await connection.fetchval(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
            )
            if actual_name != sim_database_name or tables != 0:
                raise ValueError("NEW_SIM_DATABASE_NOT_EMPTY_OR_WRONG_TARGET")
        finally:
            await connection.close()
        pool = await asyncpg.create_pool(budget_dsn, min_size=1, max_size=2, timeout=10, command_timeout=10)
        before_budget = await verify_existing_budget(pool)
        sim = Database(
            PersistenceSettings(_env_file=None, database_url=sim_dsn, pool_min_size=1, pool_max_size=2),
            migration_profile=MigrationProfile.SIMULATOR,
        )
        await sim.connect()
        await sim.migrate()
        await sim.verify_schema()
        append_evidence(
            evidence_root / "resources.jsonl",
            {
                "event": "ISOLATED_RESOURCES_READY",
                "identity": identity,
                "sim_container": sim_name,
                "sim_database": sim_database_name,
                "sim_image_id": pg_image,
                "budget_tunnel_image_id": python_image,
                "loopback_only": True,
                "existing_budget_adoption": before_budget,
                "existing_runtime_mutation": False,
                "at_ms": time.time_ns() // 1_000_000,
            },
        )
        yield CurrentResources(
            pool, sim, SimulationRepository(sim.pool), sim_name, sim_database_name, sim_dsn
        )
    finally:
        original_failure = sys.exc_info()[0] is not None
        cleanup_failed = False
        if pool is not None:
            try:
                after_budget = await verify_existing_budget(pool)
                append_evidence(
                    evidence_root / "resources.jsonl",
                    {
                        "event": "CUMULATIVE_BUDGET_AFTER",
                        "usage": after_budget,
                        "at_ms": time.time_ns() // 1_000_000,
                    },
                )
            except BaseException:
                cleanup_failed = True
                try:
                    append_evidence(
                        evidence_root / "resources.jsonl",
                        {
                            "event": "CUMULATIVE_BUDGET_AFTER_UNKNOWN",
                            "at_ms": time.time_ns() // 1_000_000,
                        },
                    )
                except BaseException:
                    pass
        # Every cleanup is independent. One failed close/stop must not skip the
        # credential-free tunnel or another owned connection/container.
        for client in (sim, pool):
            if client is not None:
                try:
                    await asyncio.wait_for(client.close(), timeout=10)
                except BaseException:
                    cleanup_failed = True
        for name in (sim_name, tunnel_name):
            if name not in attempted:
                continue
            image, retain = attempted[name]
            try:
                event = _cleanup_resource(name=name, identity=identity, image=image, retain=retain)
            except BaseException:
                cleanup_failed = True
                event = "OWNED_RESOURCE_CLEANUP_UNCONFIRMED"
            try:
                append_evidence(
                    evidence_root / "resources.jsonl",
                    {"event": event, "container": name, "at_ms": time.time_ns() // 1_000_000},
                )
            except BaseException:
                cleanup_failed = True
        if cleanup_failed and not original_failure:
            raise RuntimeError("CURRENT_RESOURCE_CLEANUP_INCOMPLETE")
