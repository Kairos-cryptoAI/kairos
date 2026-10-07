"""Offline, source-only no-call preflight for the fixed two-episode pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .historical_inputs import validate_replay_inputs
from .inputs import UNIVERSE, WindowInputs, load_window
from .runner import load_plan, source_receipt

SCHEMA = "kairos.development.historical-pilot-preflight.v1"
PURPOSE = "OFFLINE_NO_CALL_HISTORICAL_PILOT_PREFLIGHT_ONLY_NOT_THE_REQUESTED_PAID_LLM_OR_ECONOMIC_RUN"
DEADLINE_SECONDS = 180.0
UNKNOWN = "UNKNOWN"
EPISODES = (
    ("episode_a", "2021-05-17", "2021-05-22", "2021-05-19T00:00:00Z", "2021-05-19T08:00:00Z", "may"),
    ("episode_d", "2024-01-08", "2024-01-13", "2024-01-09T21:15:00Z", "2024-01-09T21:30:00Z", "original"),
)
EXPECTED_CUTS = {item[0]: (item[3], item[4]) for item in EPISODES}
REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("pilot plan contains duplicate JSON keys")
        result[key] = value
    return result


def _utc_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo != UTC:
        raise ValueError("pilot timestamps must be UTC")
    return int(parsed.timestamp() * 1000)


def _check_deadline(deadline: float, clock: Any) -> None:
    if clock() >= deadline:
        raise TimeoutError("180-second offline pilot preflight deadline reached")


def validate_pilot_plan(plan_path: Path) -> dict[str, Any]:
    """Require the exact approved limits and fixed schedule; never promote readiness."""
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        if not isinstance(plan, dict) or not isinstance(plan.get("low_cost_pilot"), dict):
            raise ValueError("pilot plan object is missing required structure")
        pilot = plan["low_cost_pilot"]
        episode_list = plan.get("episodes")
        if not isinstance(episode_list, list) or any(not isinstance(item, dict) for item in episode_list):
            raise ValueError("pilot episode roster is missing or malformed")
        episode_ids = [episode.get("id") for episode in episode_list]
        if len(episode_ids) != len(set(episode_ids)):
            raise ValueError("pilot plan contains duplicate episode ids")
        episodes = {episode["id"]: episode for episode in episode_list}
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("pilot plan is unreadable or missing required fields") from exc
    expected_windows = {
        episode_id: (start + "T00:00:00Z", end + "T00:00:00Z") for episode_id, start, end, *_ in EPISODES
    }
    if (
        plan.get("schema") != "kairos.development.historical-episode-roster.v1"
        or plan.get("universe") != list(UNIVERSE)
        or set(episodes) != {"episode_a", "episode_b", "episode_c", "episode_d"}
        or any(
            episodes[episode_id].get("candidate_start_utc") != window[0]
            or episodes[episode_id].get("candidate_end_exclusive_utc") != window[1]
            for episode_id, window in expected_windows.items()
        )
        or pilot.get("selected_episode_ids") != ["episode_a", "episode_d"]
        or pilot.get("decision_cuts_per_episode") != 2
        or pilot.get("utc_decision_cuts") != {key: list(value) for key, value in EXPECTED_CUTS.items()}
        or pilot.get("maximum_paid_requests_total") != 20
        or type(pilot.get("maximum_paid_requests_total")) is not int
        or pilot.get("automatic_retries") != 0
        or type(pilot.get("automatic_retries")) is not int
        or pilot.get("approved_cumulative_pilot_ceiling_usd") != 1.0
        or type(pilot.get("approved_cumulative_pilot_ceiling_usd")) not in (int, float)
        or pilot.get("additional_model_or_effort_comparisons") is not False
        or pilot.get("paid_dispatch_ready") is not False
        or not all(
            key in pilot
            for key in (
                "admitted_strategy_identity",
                "admitted_model_route",
                "required_context_source_roster",
            )
        )
        or pilot.get("admitted_strategy_identity") is not None
        or pilot.get("admitted_model_route") is not None
        or pilot.get("required_context_source_roster") is not None
        or pilot.get("paid_requests_executed") != 0
        or pilot.get("economics_executed") is not False
        or pilot.get("strategy_generation_executed") is not False
        or plan.get("LIVE_READY") is not False
        or plan.get("STRATEGY_POLICY") != "REJECT_ALL"
    ):
        raise ValueError("historical pilot plan no longer matches the fixed source-gated no-call limits")
    return plan


def validate_paths(workspace_root: Path, output_root: Path) -> tuple[Path, Path, Path]:
    if not workspace_root.is_absolute() or not output_root.is_absolute():
        raise ValueError("workspace and output roots must be absolute paths")
    ws = workspace_root.absolute()
    for component in (*reversed(ws.parents), ws):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if component.is_symlink() or getattr(info, "st_file_attributes", 0) & REPARSE_POINT:
            raise ValueError("workspace path must not contain symlinks or junctions")
    ws = ws.resolve(strict=True)
    repo = ws / "kairos"
    runtime = ws / "runtime"
    plan_path = repo / "development" / "adaptive_replay" / "historical-episodes-draft.json"
    source_plan = repo / "development" / "adaptive_replay" / "plan.json"
    if not repo.is_dir() or not plan_path.is_file() or not source_plan.is_file() or not runtime.is_dir():
        raise ValueError("workspace is missing the expected Kairos repo, runtime or pilot plans")
    if runtime.resolve(strict=True).parent != ws:
        raise ValueError("runtime must be a direct child of workspace root")
    for component in (runtime, runtime.resolve(strict=True)):
        info = component.lstat()
        if component.is_symlink() or getattr(info, "st_file_attributes", 0) & REPARSE_POINT:
            raise ValueError("runtime must not be a symlink or junction")
    candidate = output_root.absolute()
    if candidate.parent != runtime.absolute():
        raise ValueError("output root must be a direct child of the task-owned runtime directory")
    if candidate.exists() or candidate.is_symlink():
        raise FileExistsError("output root must not exist; preflight is create-only")
    resolved = candidate.resolve(strict=False)
    if resolved.parent != runtime.resolve(strict=True):
        raise ValueError("output root escapes the task-owned runtime directory")
    for protected in (
        repo / "development" / "adaptive_replay" / "evidence",
        ws / "kairos-backtest" / "data" / "historical",
        ws / "kairos-backtest" / "data" / "historical-factors",
    ):
        p = os.path.normcase(str(protected.resolve(strict=False)))
        c = os.path.normcase(str(resolved))
        if c == p or c.startswith(p + os.sep):
            raise ValueError("output root overlaps protected cache or frozen evidence")
    return ws, plan_path, source_plan


def _input_roots(workspace: Path, cache_kind: str) -> tuple[Path, Path]:
    backtest = workspace / "kairos-backtest" / "data"
    if cache_kind == "may":
        may = workspace / "runtime" / "historical-pilot-market-20261007-a"
        return may / "bars", may / "factors"
    return backtest / "historical", backtest / "historical-factors"


def _stream_rows(
    path: Path,
    episode_id: str,
    start_ms: int,
    end_ms: int,
    cuts: tuple[str, str],
    deadline: float,
    clock: Any,
) -> str:
    scheduled = {_utc_ms(cut): cut for cut in cuts}
    if (
        end_ms <= start_ms
        or len(scheduled) != 2
        or any(not start_ms <= value < end_ms for value in scheduled)
    ):
        raise ValueError("exactly two unique fixed cuts inside the half-open episode window are required")
    digest = hashlib.sha256()
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for symbol in UNIVERSE:
            for timestamp in range(start_ms, end_ms, 60_000):
                if timestamp % (60 * 60_000) == 0:
                    _check_deadline(deadline, clock)
                is_cut = timestamp in scheduled
                row = {
                    "episode": episode_id,
                    "symbol": symbol,
                    "minute_open_ms": timestamp,
                    "scheduled_review_cut_utc": scheduled.get(timestamp),
                    "source_state": UNKNOWN,
                    "source_ready": False,
                    "required_sources_ready": False,
                    "required_source_coverage": {"NEWS": UNKNOWN, "MACRO": UNKNOWN},
                    "candidate_status": "NOT_EVALUATED",
                    "candidate_count": None,
                    "candidate": None,
                    "call_status": "NOT_CALLED",
                    "no_call_reason": "REQUIRED_SOURCE_UNAVAILABLE" if is_cut else "SCHEDULED_POLICY_ABSTAIN",
                    "model_decision": None,
                    "economic_result": None,
                    "provider_calls": 0,
                    "provider_cost_usd": 0,
                    "history_local_receipt_proven": False,
                    "historical_receive_clock_proven": False,
                    "economics_executed": False,
                    "paid_run_executed": False,
                }
                encoded = _canonical(row)
                digest.update(encoded + b"\n")
                stream.write(encoded.decode("utf-8") + "\n")
    return digest.hexdigest()


def _market_summary(inputs: WindowInputs) -> dict[str, Any]:
    summary = {
        symbol: {
            "bars": len(inputs.bars[symbol]),
            "funding": len(inputs.funding[symbol]),
            "gaps": inputs.evidence["bars"][symbol]["gaps"],
            "bar_rows_sha256": inputs.evidence["bars"][symbol]["normalized_rows_sha256"],
            "funding_rows_sha256": inputs.evidence["funding"][symbol]["normalized_rows_sha256"],
        }
        for symbol in UNIVERSE
    }
    if any(item["bars"] != 12_960 or item["funding"] != 27 or item["gaps"] != 0 for item in summary.values()):
        raise ValueError("source-only pilot requires exact complete 12,960-bar/27-funding inputs per symbol")
    return summary


def run_preflight(workspace_root: Path, output_root: Path, *, clock: Any = time.monotonic) -> dict[str, Any]:
    workspace, pilot_path, source_plan_path = validate_paths(workspace_root, output_root)
    started = clock()
    actual_started_utc = datetime.now(UTC).isoformat()
    deadline = started + DEADLINE_SECONDS
    output_root.mkdir(parents=False, exist_ok=False)
    row_fingerprints: dict[str, str] = {}
    try:
        pilot_plan = validate_pilot_plan(pilot_path)
        source_plan = load_plan(source_plan_path)
        sources = source_receipt(source_plan, source_plan_path)
        source_digest = _sha(_canonical(sources))
        _check_deadline(deadline, clock)
        with (output_root / "before.json").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(
                json.dumps(
                    {
                        "purpose": PURPOSE,
                        "actual_started_utc": actual_started_utc,
                        "pilot_plan_sha256": _sha(_canonical(pilot_plan)),
                        "sources": sources,
                        "workers": 1,
                        "max_wall_seconds": DEADLINE_SECONDS,
                        "trading_authority": False,
                    },
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                )
                + "\n"
            )
        episode_summaries: dict[str, Any] = {}
        for episode_id, start, end, cut1, cut2, cache in EPISODES:
            _check_deadline(deadline, clock)
            bar_root, factor_root = _input_roots(workspace, cache)
            window = {"id": episode_id, "start": start, "end_exclusive": end}
            inputs = load_window(bar_root, factor_root, window)
            _check_deadline(deadline, clock)
            validate_replay_inputs(inputs, fixture_only=False, deadline=deadline)
            _check_deadline(deadline, clock)
            episode_dir = output_root / episode_id
            episode_dir.mkdir()
            start_ms, end_ms = _utc_ms(start + "T00:00:00Z"), _utc_ms(end + "T00:00:00Z")
            fingerprint = _stream_rows(
                episode_dir / "source-no-call-rows.jsonl",
                episode_id,
                start_ms,
                end_ms,
                (cut1, cut2),
                deadline,
                clock,
            )
            row_fingerprints[episode_id] = fingerprint
            episode_summaries[episode_id] = {
                "window_start_utc": start + "T00:00:00Z",
                "window_end_exclusive_utc": end + "T00:00:00Z",
                "denominator_rows": (end_ms - start_ms) // 60_000 * len(UNIVERSE),
                "scheduled_symbol_cut_records": len(UNIVERSE) * 2,
                "scheduled_no_call_reason": "REQUIRED_SOURCE_UNAVAILABLE",
                "unscheduled_no_call_reason": "SCHEDULED_POLICY_ABSTAIN",
                "market_inputs": _market_summary(inputs),
                "row_stream_sha256": fingerprint,
            }
            del inputs
        _check_deadline(deadline, clock)
        # Recheck immutable plan and installed source pins before emitting success.
        if validate_pilot_plan(pilot_path) != pilot_plan:
            raise ValueError("historical pilot draft changed during preflight")
        if source_receipt(load_plan(source_plan_path), source_plan_path) != sources:
            raise ValueError("installed/source plan identity changed during preflight")
        _check_deadline(deadline, clock)
        result = {
            "schema": SCHEMA,
            "state": "PREFLIGHT_COMPLETED_PAID_RUN_BLOCKED",
            "purpose": PURPOSE,
            "source_identity_sha256": source_digest,
            "sources": sources,
            "actual_started_utc": actual_started_utc,
            "actual_finished_utc": datetime.now(UTC).isoformat(),
            "elapsed_seconds": clock() - started,
            "episodes": episode_summaries,
            "denominator_rows_total": sum(item["denominator_rows"] for item in episode_summaries.values()),
            "scheduled_symbol_cut_records_total": 20,
            "news_coverage": UNKNOWN,
            "macro_coverage": UNKNOWN,
            "all_scheduled_records": "NOT_CALLED/REQUIRED_SOURCE_UNAVAILABLE",
            "all_other_rows": "NOT_CALLED/SCHEDULED_POLICY_ABSTAIN",
            "candidate_count": None,
            "readiness": source_plan["readiness"],
            "historical_receive_clock_proven": False,
            "required_sources_ready": False,
            "provider_cost_usd": 0,
            "strategy_or_candidate_generation_executed": False,
            "strategy_generation_executed": False,
            "response_or_economics_executed": False,
            "economics_executed": False,
            "paid_run_executed": False,
            "paid_requests_executed": 0,
            "provider_calls": 0,
            "database_calls": 0,
            "network_calls": 0,
            "trading_authority": False,
        }
        partial = output_root / "preflight-summary.json.partial"
        with partial.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
            stream.flush()
        _check_deadline(deadline, clock)
        partial.rename(output_root / "preflight-summary.json")
        return result
    except Exception as exc:
        failure = {
            "schema": SCHEMA,
            "state": "FAILED_NO_SUCCESS_RECEIPT",
            "purpose": PURPOSE,
            "error_type": type(exc).__name__,
            "completed_row_streams": row_fingerprints,
            "provider_calls": 0,
            "database_calls": 0,
            "network_calls": 0,
        }
        with (output_root / "failure.json").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(failure, sort_keys=True, indent=2, allow_nan=False) + "\n")
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_preflight(args.workspace_root, args.output_root)
    except (OSError, TimeoutError, ValueError) as exc:
        print(json.dumps({"state": "FAILED_NO_SUCCESS_RECEIPT", "error_type": type(exc).__name__}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
