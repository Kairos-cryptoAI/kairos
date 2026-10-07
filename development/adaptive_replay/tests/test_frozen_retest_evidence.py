"""Original census bytes and complete denominator, not a profit qualification."""

import gzip
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from adaptive_replay.frozen_retest import STRATEGY_ID
from adaptive_replay.frozen_retest_census import fixed_census_protocol
from adaptive_replay.historical_context import canonical, digest

ROOT = Path(__file__).parents[1] / "evidence/frozen-retest-2026-10-07"


def read(name):
    return json.loads((ROOT / name).read_bytes())


def test_original_census_bytes_are_bound_on_all_platforms():
    receipt = read("checksums.json")
    assert receipt["scope"] == "SHA256_OF_ORIGINAL_CENSUS_BYTES_NOT_SOURCE_AUTHENTICITY"
    assert receipt["original_file_count"] == len(receipt["files"]) == 7
    assert {p.name for p in ROOT.iterdir()} == {"checksums.json", *receipt["files"]}
    for name, expected in receipt["files"].items():
        assert Path(name).name == name and ".." not in Path(name).parts and "\\" not in name
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    result = read("result.json")
    compressed = (ROOT / "decisions.jsonl.gz").read_bytes()
    decoded = gzip.decompress(compressed)
    assert hashlib.sha256(compressed).hexdigest() == result["decisions_gzip_sha256"]
    assert hashlib.sha256(decoded).hexdigest() == result["decisions_canonical_jsonl_sha256"]


def test_protocol_source_inputs_and_actual_attempt_remain_sealed():
    result, before, after = (read(name) for name in ("result.json", "before.json", "after.json"))
    assert read("protocol.json") == fixed_census_protocol()
    assert digest(fixed_census_protocol()) == result["protocol_sha256"] == before["protocol_sha256"]
    assert before["sources"] == after["sources"]
    assert result["source_receipt_unchanged"] and after["source_receipt_unchanged"]
    assert {"frozen_retest.py", "frozen_retest_entry.py", "frozen_retest_census.py"} <= (
        before["sources"]["replay_modules_sha256"].keys()
    )
    assert before["actual_started_utc"] == result["actual_started_utc"]
    assert (
        datetime.fromisoformat(result["actual_started_utc"])
        < datetime.fromisoformat(after["actual_finished_utc"])
        <= datetime.fromisoformat(result["actual_finished_utc"])
    )
    assert 0 < result["elapsed_seconds"] < 300
    for eid in result["episodes"]:
        for market in read(f"{eid}-inputs.json")["market"].values():
            assert market["bars"] == 12960 and market["funding"] == 27 and market["gaps"] == 0


def test_every_slot_and_refusal_is_retained_with_full_zero_day_denominator():
    protocol, result = read("protocol.json"), read("result.json")
    expected = []
    for episode in protocol["episodes"]:
        start = int(datetime.fromisoformat(episode["start"]).replace(tzinfo=UTC).timestamp() * 1000)
        end = int(datetime.fromisoformat(episode["end_exclusive"]).replace(tzinfo=UTC).timestamp() * 1000)
        expected.extend(
            (episode["id"], symbol, ts)
            for symbol in protocol["universe"]
            for ts in range(start, end, 300_000)
        )
    rows = []
    with gzip.open(ROOT / "decisions.jsonl.gz", "rb") as stream:
        for line in stream:
            row = json.loads(line)
            assert (canonical(row) + "\n").encode() == line
            rows.append(row)
    assert [(r["episode"], r["symbol"], r["technical"]["cut_ms"]) for r in rows] == expected
    assert len(rows) == result["complete_scheduled_slots"] == 14_400
    arms = reclaims = retests = 0
    rejected_reclaims = Counter()
    for eid, cells in result["episodes"].items():
        for symbol, count in cells.items():
            technical = [r["technical"] for r in rows if r["episode"] == eid and r["symbol"] == symbol]
            assert len(technical) == count["scheduled_slots"] == 1440
            for field in ("state", "reason", "transition", "defense"):
                assert dict(Counter(t[field] for t in technical)) == count[f"{field}_counts"]
            arms += count["breakouts_armed"]
            reclaims += count["structural_reclaims_consumed"]
            retests += count["reason_counts"].get("FIRST_RETEST_RECORDED", 0)
            for t in technical:
                if t["transition"] == "RECLAIM_CONSUMED_NO_RETRY":
                    assert t["consumed"] and t["state"] == "BLOCKED"
                    assert t["candidate"] is None
                    rejected_reclaims[t["reason"]] += 1
            assert count["raw_candidates_after_fixed_base_hurdle"] == 0
            assert len(count["candidates_each_utc_day"]) == 5
            assert set(count["candidates_each_utc_day"].values()) == {0}
            for scenario in count["scenarios"].values():
                assert (
                    scenario["first_arrival_geometry_feasible"]
                    == scenario["reference_geometry_feasible"]
                    == 0
                )
                assert set(scenario["first_arrival_feasible_each_utc_day"].values()) == {0}
    assert (arms, retests, reclaims) == (122, 50, 23)
    assert rejected_reclaims == {
        "NET_REWARD_RISK_TOO_LOW": 13,
        "INSUFFICIENT_COST_HEADROOM": 5,
        "TARGET_NOT_BEYOND_RECLAIM": 5,
    }
    assert all(r["geometries"] == {} and r["technical"]["candidate"] is None for r in rows)
    assert STRATEGY_ID == protocol["strategy"]["id"]


def test_empty_candidate_set_is_not_zero_return_or_model_alpha():
    result = read("result.json")
    assert result["provider_calls"] == result["provider_cost_usd"] == 0
    assert result["economic_result"] is None
    for key in (
        "economics_executed",
        "source_authenticity_admitted",
        "required_news_macro_ready",
        "model_execution_admitted",
        "blind_campaign_credit",
    ):
        assert result[key] is False
    assert result["readiness"]["STRATEGY_POLICY"] == "REJECT_ALL"
    assert not any(v for k, v in result["readiness"].items() if k != "STRATEGY_POLICY")
