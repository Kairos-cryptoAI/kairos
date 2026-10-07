"""Keep the failed calendar attempt distinct from measured performance."""

from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import datetime
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parents[1] / "evidence" / "calendar-2026-10-07"


def read(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_bytes())


def test_failed_attempt_retains_exact_runtime_bytes() -> None:
    gap_name = "sol-calendar-gap-diagnostic.json"
    hashes = {
        "before.json": "33223ed0fb5de848375631e87f27c1bb45f1ab5c712b272b9b53e85ec7c4a51f",
        "failure.json": "63192f49e18a542ff0e52ea2ffb3eb3565257cde2a2e8c407dc9916dd549f6f1",
        "sealed-calendar-plan.json": "75a68d977519f3fdce3a494dbf6761887e89cfbca1c912f30be26df11c4d2fdd",
        gap_name: "c5f329fbca2c000ffe1ae9a0087c4e99bddba26dc5ff1361007cd3d27c64f2a8",
        "calendar-input-audit.json": "28b5bd74c983ed2761c1f6542566898ae7b5dd29a2edf645fbbcaac415b93db2",
        "Inspect-CalendarInputs.py.txt": "562e5c92a5ae5b87af128bf284a440e3bb47c49131d5bce1f1c32aaf7bdb4843",
    }
    for name, expected in hashes.items():
        assert hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest() == expected
    assert {path.name for path in EVIDENCE.iterdir() if path.is_file()} == set(hashes)


def test_unavailable_calendar_evidence_cannot_become_an_economic_decision() -> None:
    failure = read("failure.json")
    plan = read("sealed-calendar-plan.json")
    before = read("before.json")
    assert failure["state"] == "FAILED_CLOSED"
    assert failure["error_type"] == "ValueError"
    assert failure["reason"] == "incomplete verified FULL_KLINE span for SOLUSDT"
    assert failure["completed_windows"] == []
    assert failure["economic_reference_nominee"] is None
    assert not (EVIDENCE / "result.json").exists()
    assert not any(EVIDENCE.rglob("*-ledger.json"))
    assert plan["no_second_economic_attempt"] is True
    assert plan["readiness"]["STRATEGY_POLICY"] == "REJECT_ALL"
    assert all(value is False for key, value in plan["readiness"].items() if key != "STRATEGY_POLICY")
    assert len(plan["windows"]) == 4
    assert (
        before["sources"]["installed_replay_context"]["installed_dependencies"]["kairos-backtest"]["revision"]
        == "da1237854066fde381542e43c106d0de727448be"
    )


def test_observed_sol_gaps_reconcile_without_artificial_bars() -> None:
    diagnostic = read("sol-calendar-gap-diagnostic.json")
    assert diagnostic["expected_rows"] - diagnostic["actual_rows"] == diagnostic["missing_minutes"] == 7200
    assert diagnostic["checksum_files_verified"] == diagnostic["expected_files"] == 15
    assert diagnostic["gaps"] == 2
    assert diagnostic["quarantined_optional_rows"] == 0
    assert diagnostic["generator_invoked"] is False and diagnostic["economic_replay_invoked"] is False
    assert diagnostic["archive_sidecars_are_not_independent_external_completeness_proof"] is True
    intervals = diagnostic["missing_spans"]
    for interval in intervals:
        start = datetime.fromisoformat(interval["start_inclusive_utc"])
        end = datetime.fromisoformat(interval["end_exclusive_utc"])
        assert (end - start).total_seconds() / 60 == interval["missing_minutes"]
    assert sum(interval["missing_minutes"] for interval in intervals) == 7200
    start = datetime.fromisoformat(diagnostic["requested_start_utc"])
    end = datetime.fromisoformat(diagnostic["requested_end_exclusive_utc"])
    assert (end - start).total_seconds() / 60 == diagnostic["expected_rows"]


def test_finished_input_inventory_preserves_failed_coverage_and_exact_counts() -> None:
    audit = read("calendar-input-audit.json")
    assert audit["state"] == "COMPLETED" and audit["coverage_complete"] is False
    assert audit["processed_files"] == audit["audited_files"] == audit["checksum_files_verified"] == 255
    assert audit["missing_archives"] == audit["audit_errors"] == 0
    assert audit["elapsed_seconds"] < audit["deadline_seconds"] == 180
    assert audit["rows"] == 11167199 and audit["missing_minutes"] == 14400 and audit["invalid_rows"] == 1
    assert (
        audit["helper_sha256"]
        == hashlib.sha256((EVIDENCE / "Inspect-CalendarInputs.py.txt").read_bytes()).hexdigest()
    )
    assert len(audit["files"]) == len({record["filename"] for record in audit["files"]}) == 255
    inventory = hashlib.sha256()
    expected_total = 0
    for record in audit["files"]:
        assert record["status"] == "AUDITED"
        assert record["present_files"] == record["checksum_files_verified"] == 1
        year, month = map(int, record["month"].split("-"))
        expected = monthrange(year, month)[1] * 1440
        assert record["rows"] + record["missing_minutes"] + record["invalid_rows"] == expected
        expected_total += expected
        inventory.update(record["symbol"].encode("ascii"))
        inventory.update(b"\0")
        inventory.update(record["month"].encode("ascii"))
        inventory.update(b"\0")
        inventory.update(bytes.fromhex(record["inventory_sha256"]))
    assert expected_total == 11181600
    assert inventory.hexdigest() == audit["aggregate_cached_inventory_sha256"]
    summary = {record["symbol"]: record for record in audit["per_symbol"]}
    assert summary["SOLUSDT"]["missing_minutes"] == summary["XRPUSDT"]["missing_minutes"] == 7200
    assert summary["XRPUSDT"]["invalid_rows"] == summary["XRPUSDT"]["gaps"] == 1
    assert all(summary[symbol]["missing_minutes"] == 0 for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT"))
