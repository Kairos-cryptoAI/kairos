"""Preserved partial prints cannot be promoted to complete source or execution evidence."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parents[1] / "evidence/intraday-reference-2026-10-07"
SOURCE_COMMIT = "0dee566dd392ff2e969db3aff43d1f1126790c2e"
PLAN_SHA = "89e1a6641e228365ffec5011da2f456f6af67d3a83d46ccfe037ff0f360f6748"


def payload(name: str) -> bytes:
    return gzip.decompress((ROOT / (name + ".gz")).read_bytes())


def read(name: str) -> dict:
    return json.loads(payload(name))


def archives() -> list[dict]:
    return [read(f"archive-{i:02d}.json") for i in range(1, 8)]


def native_intents() -> list[dict]:
    return [
        slot["intent"]
        for tape in read("sealed-source-plan.json")["tapes"]
        for encoded in payload(f"native/{tape['window']}/decisions.jsonl").splitlines()
        if (slot := json.loads(encoded))["intent"] is not None
    ]


def test_all_thirty_two_partial_artifacts_are_lossless_and_byte_bound() -> None:
    index = json.loads((ROOT / "checksums.json").read_bytes())
    assert index["source_commit"] == SOURCE_COMMIT
    assert index["source_plan_file_sha256"] == PLAN_SHA
    assert index["source_attempts"] == 1 and index["economic_attempts"] == 0
    assert index["source_attempt_state"] == "FAILED_CLOSED"
    for field in (
        "source_prerequisite_resolved",
        "final_runner_source_binding_completed",
        "raw_archives_in_git",
        "old_attempt_rewritten",
    ):
        assert index[field] is False
    records = index["files"]
    assert len(records) == len({r["file"] for r in records}) == 32
    assert {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()} == {
        "checksums.json",
        *(r["file"] for r in records),
    }
    for row in records:
        assert "\\" not in row["file"] and ".." not in Path(row["file"]).parts
        compressed = (ROOT / row["file"]).read_bytes()
        original = gzip.decompress(compressed)
        assert hashlib.sha256(compressed).hexdigest() == row["compressed_sha256"]
        assert hashlib.sha256(original).hexdigest() == row["original_sha256"]
        assert len(compressed) == row["compressed_bytes"] and len(original) == row["original_bytes"]
    assert hashlib.sha256(payload("failure.json")).hexdigest() == (
        "56e9ff6929d12b6b8d87b9819b745a2beffb6362c95dd1c1afc036cbd657d722"
    )
    assert not (ROOT / "result.json.gz").exists()


def test_resource_failure_does_not_become_an_integrity_or_economic_rejection() -> None:
    failure = read("failure.json")
    assert failure["state"] == "FAILED_CLOSED" and failure["error_type"] == "ValueError"
    assert failure["phase"] == "WHOLE_ARCHIVE_INTEGRITY"
    assert failure["source_error"] == "row count exceeds configured limit"
    assert failure["archive"] == {"symbol": "BTCUSDT", "day": "2022-06-14"}
    assert failure["source_prerequisite_resolved"] is failure["economics_computed"] is False
    assert failure["no_automatic_retry"] is True
    assert failure["readiness"]["STRATEGY_POLICY"] == "REJECT_ALL"
    assert all(v is False for k, v in failure["readiness"].items() if k != "STRATEGY_POLICY")
    audit = read("independent-partial-witness-audit.json")
    assert audit["state"] == "PASSED_PARTIAL_WITNESSES"
    assert audit["complete"] is audit["global_before_after_source_equality_proven"] is False
    assert audit["failed_archive"]["failed_archive_prefix_rows"] is None
    assert audit["failed_archive"]["whole_member_crc_verified"] is False
    assert audit["source_prerequisite_resolved"] is False
    assert audit["qualification"]["winner"] is None and audit["qualification"]["readiness"] == "REJECT_ALL"
    assert all(v is False for k, v in audit["qualification"].items() if k not in {"winner", "readiness"})


def test_original_native_denominator_preserves_all_slots_and_candidate_order() -> None:
    plan, before = read("sealed-source-plan.json"), read("before.json")
    actual_plan_path = ROOT.parents[1] / "intraday-source-plan.json"
    assert hashlib.sha256(actual_plan_path.read_bytes()).hexdigest() == PLAN_SHA
    assert json.loads(actual_plan_path.read_bytes()) == plan
    assert plan["limits"]["max_rows_each"] == 5_000_000
    assert before["sources"]["source_plan_file_sha256"] == PLAN_SHA
    assert before["economic_evidence_read"] is False
    counts = Counter()
    for tape in plan["tapes"]:
        original = payload(f"native/{tape['window']}/decisions.jsonl")
        assert hashlib.sha256(original).hexdigest() == tape["sha256"]
        slots = [json.loads(line) for line in original.splitlines()]
        assert len(slots) == tape["slots"] == 4320
        assert sum(s["intent"] is not None for s in slots) == tape["candidates"]
        counts.update(s["status"] for s in slots)
    assert counts == {"NO_INTENT": 17268, "INTENT": 12}
    intents = native_intents()
    assert [intent["intent_id"] for intent in intents] == plan["candidate_ids"]
    for intent in intents:
        assert intent["entry_eligible_ts_ms"] == intent["decision_ts_ms"] + 1
        assert intent["entry_expires_ts_ms"] == intent["decision_ts_ms"] + 60_000


def test_seven_completed_archives_and_eight_get_pairs_have_distinct_totals() -> None:
    plan, failure = read("sealed-source-plan.json"), read("failure.json")
    completed = archives()
    downloads = [read(f"downloads-{i:02d}.json") for i in range(1, 9)]
    assert failure["archives_completed"] == len(completed) == 7
    assert sum(r["rows"] for r in completed) == failure["rows_checked"] == 13_214_561
    assert sum(r["archive_bytes"] for r in completed) == 177_977_563
    assert sum(pair[1]["bytes"] for pair in downloads) == failure["compressed_bytes_fetched"] == 244_624_875
    assert not (ROOT / "archive-08.json.gz").exists()
    assert not (ROOT / "downloads-09.json.gz").exists()
    for i, pair in enumerate(downloads):
        item = plan["archives"][i]
        name = f"{item['symbol']}-aggTrades-{item['day']}.zip"
        assert [r["filename"] for r in pair] == [name + ".CHECKSUM", name]
        for get in pair:
            assert get["url"] == (
                f"https://data.binance.vision/data/futures/um/daily/aggTrades/{item['symbol']}/{get['filename']}"
            )
            assert get["http_status"] == 200 and get["requests"] == 1 and get["redirects"] == 0
        if i < 7:
            receipt = completed[i]
            assert (receipt["symbol"], receipt["day"]) == (item["symbol"], item["day"])
            assert receipt["archive_sha256"] == pair[1]["sha256"]
            assert receipt["checksum_sidecar_sha256"] == pair[0]["sha256"]
            assert receipt["archive_bytes"] == pair[1]["bytes"]
            assert receipt["aggregate_id_gap_count"] == 0


def test_ten_partial_witnesses_leave_two_unresolved_not_no_reference() -> None:
    plan, audit = read("sealed-source-plan.json"), read("independent-partial-witness-audit.json")
    by_id = {r["intent_id"]: r for archive in archives() for r in archive["requests"]}
    intents = {r["intent_id"]: r for r in native_intents()}
    assert len(by_id) == audit["completed_candidate_witnesses"] == 10
    assert (
        Counter(r["status"] for r in by_id.values())
        == audit["completed_reference_statuses"]
        == {"RECORDED_PRINT_REFERENCE": 10}
    )
    unresolved = audit["unresolved_candidate_ids"]
    assert [r["intent_id"] for r in unresolved] == plan["candidate_ids"][6:8]
    assert {r["intent_id"] for r in unresolved} | set(by_id) == set(plan["candidate_ids"])
    assert {r["intent_id"] for r in unresolved}.isdisjoint(by_id)
    assert [r["reason"] for r in unresolved] == [
        "FAILED_ARCHIVE_ROW_LIMIT_PREFIX_UNKNOWN",
        "NOT_REACHED_AFTER_FAILED_ARCHIVE",
    ]
    waits = []
    for identifier, witness in by_id.items():
        intent = intents[identifier]
        decision = intent["decision_ts_ms"]
        assert witness["decision_ts_ms"] == decision
        assert witness["entry_eligible_ts_ms"] == intent["entry_eligible_ts_ms"] == decision + 1
        assert witness["expires_ts_ms"] == intent["entry_expires_ts_ms"] == decision + 60_000
        assert witness["completion_ts_ms_assumed"] == decision + 100
        assert witness["transport_delay_ms_assumed"] == 0
        arrival = witness["arrival_ts_ms_assumed"]
        assert arrival == decision + 100
        reference = witness["first_reference"]
        assert Decimal(reference["price"]) > 0 and Decimal(reference["quantity"]) > 0
        assert arrival <= reference["transact_time_ms"] <= witness["expires_ts_ms"]
        assert witness["strict_pre_window_predecessor"]["transact_time_ms"] < arrival
        assert witness["strict_post_window_successor"]["transact_time_ms"] > witness["expires_ts_ms"]
        assert witness["immediate_predecessor"]["aggregate_trade_id"] + 1 == reference["aggregate_trade_id"]
        assert witness["aggregate_gap_intersects_window"] is False
        assert witness["wait_ms"] == reference["transact_time_ms"] - arrival
        waits.append(witness["wait_ms"])
    assert (min(waits), max(waits)) == (1, 736)


def test_independent_partial_arithmetic_is_bound_to_exact_retained_artifacts() -> None:
    audit = read("independent-partial-witness-audit.json")
    assert (
        audit["auditor_sha256"] == hashlib.sha256(payload("independent-partial-calculator.ps1")).hexdigest()
    )
    for record in audit["exact_original_json_hashes"]:
        original = payload(record["name"])
        assert hashlib.sha256(original).hexdigest() == record["sha256"] and len(original) == record["bytes"]
    assert audit["completed_archive_rows"] == 13_214_561
    assert audit["completed_archive_zip_bytes"] == 177_977_563
    assert audit["all_downloaded_zip_bytes"] == 244_624_875
    # Its launch=false marker was root-local only; the real sibling proof is retained separately.
    assert audit["launch_artifact_present"] is False
    launch = read("launch-evidence.json")
    assert launch["source_commit"] == SOURCE_COMMIT and launch["attempt"] == 1
    assert [r["run_id"] for r in launch["exact_source_ci"]] == [37573651611, 37573651603, 37573651296]
    assert all(r["conclusion"] == "success" for r in launch["exact_source_ci"])
    assert launch["verified_gpg_signer"] == "40AF365C6682B73D056A6A274DBFF6B65BE9F827"


def test_corrected_launch_utc_binding_preserves_superseded_bookkeeping() -> None:
    launch, before, failure = read("launch-evidence.json"), read("before.json"), read("failure.json")
    old = read("independent-launch-binding.json")
    corrected = read("independent-launch-binding-v2.json")
    assert old["state"] == "PASSED_LAUNCH_BOOKKEEPING_ONLY"
    assert corrected["state"] == "PASSED_SUPPLEMENTAL_LAUNCH_BINDING_V2"
    instant = datetime.fromisoformat
    assert instant(old["launch_not_before_utc"]) != instant(launch["not_before_utc"])
    assert (
        instant(launch["not_before_utc"]) - instant(old["launch_not_before_utc"])
    ).total_seconds() == 10800
    timeline = corrected["timestamps_parsed_and_roundtripped_utc"]
    assert instant(timeline["launch_not_before_utc"]) == instant(launch["not_before_utc"])
    assert instant(timeline["attempt_started_utc"]) == instant(before["started_utc"])
    assert instant(timeline["attempt_failed_utc"]) == instant(failure["completed_utc"])
    assert corrected["timestamps_raw_utc"] == {
        "launch_not_before_utc": launch["not_before_utc"],
        "attempt_started_utc": before["started_utc"],
        "attempt_failed_utc": failure["completed_utc"],
    }
    assert (
        instant(launch["not_before_utc"])
        <= instant(before["started_utc"])
        < instant(failure["completed_utc"])
    )
    assert corrected["launch_proof_sha256"] == hashlib.sha256(payload("launch-evidence.json")).hexdigest()
    assert (
        corrected["correction"]["prior_report_sha256"]
        == hashlib.sha256(payload("independent-launch-binding.json")).hexdigest()
    )
    assert (
        corrected["correction"]["prior_calculator_sha256"]
        == hashlib.sha256(payload("independent-launch-calculator.ps1")).hexdigest()
    )
    assert (
        corrected["prior_partial_audit_sha256"]
        == hashlib.sha256(payload("independent-partial-witness-audit.json")).hexdigest()
    )
    assert hashlib.sha256(payload("independent-launch-calculator-v2.ps1")).hexdigest() == (
        "a265794be6f0a25407a1e474a19f49415d298b585d40eb870d931caac5421b65"
    )
    assert corrected["source_prerequisite_resolved"] is False
    assert corrected["complete_source_coverage"] is corrected["economics_computed"] is False
    assert corrected["qualification_or_promotion_credit"] is False
