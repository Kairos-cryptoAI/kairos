"""Bounded engineering-only preparation/result/source guards; no default target."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from kairos_persistence import Database, MigrationProfile, PersistenceSettings
from kairos_persistence.database_target import connect_verified_database

from kairos_native_campaign.storage import (
    record_prepared_native_target,
    require_disposable_campaign_database,
)

DATABASE_ENV = "KAIROS_NATIVE_CAMPAIGN_TEST_DATABASE_URL"
TARGET = "test_native_candidate_review_risk_budget_restart_on_disposable_campaign_db"
ROOT = Path(__file__).resolve().parent


def configured_database(url: str | None) -> Database:
    if not url:
        raise ValueError("EXPLICIT_TARGET_REQUIRED")
    database = Database(
        PersistenceSettings(
            _env_file=None,
            database_url=url,
            pool_min_size=1,
            pool_max_size=3,
            command_timeout_s=5,
        ),
        migration_profile=MigrationProfile.RESEARCH_CAMPAIGN,
    )
    require_disposable_campaign_database(database)
    return database


async def prepare(url: str | None):
    database = configured_database(url)
    try:
        async with asyncio.timeout(60):
            await connect_verified_database(database, database.database_name, local_only=True)
            facts = await database.pool.fetchrow(
                "SELECT current_user AS role, current_setting('server_version_num')::integer AS version, "
                "(SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
                "ON n.oid=c.relnamespace WHERE n.nspname='public' "
                "AND c.relkind IN ('r','p','v','m','S')) AS objects"
            )
            if facts["role"] != "kairos" or not 160000 <= facts["version"] < 170000 or facts["objects"] != 0:
                raise ValueError("FRESH_PG16_TARGET_REQUIRED")
            await database.migrate()
            await database.verify_schema()
            await record_prepared_native_target(database)
    finally:
        await asyncio.wait_for(database.close(), timeout=5)


def check_result(report: Path):
    if report.is_symlink() or not report.is_file() or report.stat().st_size > 1_048_576:
        raise ValueError("NATIVE_RESULT_REQUIRED")
    root = ET.fromstring(report.read_bytes())
    cases = list(root.iter("testcase"))
    if (
        len(cases) != 1
        or cases[0].get("name") != TARGET
        or any(cases[0].find(tag) is not None for tag in ("skipped", "failure", "error"))
        or any(root.iter("failure"))
        or any(root.iter("error"))
    ):
        raise ValueError("EXACT_NATIVE_PASS_REQUIRED")


def check_source():
    lock = json.loads((ROOT / "source-lock.json").read_text(encoding="utf-8"))
    if lock["classification"] != "OFFLINE_ENGINEERING_FIXTURE" or lock["authority"] != "NONE":
        raise ValueError("SOURCE_SCOPE_MISMATCH")
    for name, revision in lock["repositories"].items():
        distribution = importlib.metadata.distribution(name)
        origin = json.loads(distribution.read_text("direct_url.json") or "{}")
        if (
            origin.get("vcs_info", {}).get("commit_id") != revision
            or origin.get("vcs_info", {}).get("vcs") != "git"
            or origin.get("url") != f"https://github.com/Kairos-cryptoAI/{name}.git"
        ):
            raise ValueError("INSTALLED_GIT_SOURCE_MISMATCH")
    native = importlib.metadata.distribution("kairos-native-campaign-engineering")
    if json.loads(native.read_text("direct_url.json") or "{}").get("dir_info", {}).get("editable"):
        raise ValueError("INSTALLED_NATIVE_WHEEL_REQUIRED")
    for file in sorted((ROOT / "kairos_native_campaign").glob("*.py")):
        spec = importlib.util.find_spec("kairos_native_campaign." + file.stem)
        if spec is None or spec.origin is None:
            raise ValueError("INSTALLED_NATIVE_MODULE_REQUIRED")
        installed = Path(spec.origin).resolve()
        if installed.parent == file.parent.resolve():
            raise ValueError("WORKING_TREE_IMPORT_NOT_INSTALLED_PROOF")
        if (
            hashlib.sha256(installed.read_bytes().replace(b"\r\n", b"\n")).digest()
            != hashlib.sha256(file.read_bytes().replace(b"\r\n", b"\n")).digest()
        ):
            raise ValueError("INSTALLED_NATIVE_MODULE_HASH_MISMATCH")


def main(args=None):
    args = sys.argv[1:] if args is None else args
    try:
        if args == ["prepare"]:
            asyncio.run(prepare(os.environ.get(DATABASE_ENV)))
        elif args == ["check-source"]:
            check_source()
        elif len(args) == 2 and args[0] == "check-result":
            check_result(Path(args[1]))
        else:
            raise ValueError("INVALID_COMMAND")
    except BaseException:
        # No SQL, provider output, URL, credentials or body can enter this log.
        print("NATIVE_CAMPAIGN_ENGINEERING_GATE_FAILED")
        return 1
    print("NATIVE_CAMPAIGN_ENGINEERING_GATE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
