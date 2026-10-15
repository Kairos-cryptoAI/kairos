"""One-shot publication-proxy diagnostic using the existing cumulative budget.

Never invoked by CI. No historical source admission, native context, or orders.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sys
import time
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import model_worker as existing

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reconstruct_context as reconstruction


def checked_requests(root, sources_path, baseline_path, prior_path=None):
    plan, rows = existing.verified_inputs(root)
    bundle, source_sha = reconstruction._validate_sources(sources_path)
    baseline, baseline_rows, _ = reconstruction._baseline(baseline_path)
    originals = {row["candidate_id"]: row for row in baseline_rows}
    if plan.get("prior_provider_attempts", 0):
        if prior_path is None:
            raise ValueError("retained prior failures required for corrected launch")
        correction = reconstruction.approved_correction(prior_path, source_sha)
        if any(plan.get(k) != value for k, value in correction.items()):
            raise ValueError("prior failure evidence changed")
    if (
        plan.get("schema") != "kairos.publication-time-proxy-review.plan.v1"
        or plan.get("experiment_id") != "publication-proxy-20261015"
        or plan.get("strict_causal_admission") is not False
        or plan.get("source_bundle_sha256") != source_sha
        or plan.get("baseline_result_sha256") != baseline["hashes"]["result.json"]
        or plan.get("gateway_image") != baseline["plan"]["gateway_image"]
    ):
        raise ValueError("explicit isolated publication-proxy identity required")
    for row in rows:
        user = json.loads(row["user"])
        context = user["publication_time_proxy_context"]
        sources = context["sources"]
        selected = reconstruction._select_sources(bundle, row["historical_cut_ms"])
        if sources != {
            kind: reconstruction._source_view(items) for kind, items in selected.items()
        }:
            raise ValueError("request differs from sealed publication-only sources")
        old = originals[row["candidate_id"]]
        if (
            row["historical_cut_ms"] != old["historical_cut_ms"]
            or row["window_id"] != old["window_id"]
            or row["slot_id"] != old["slot_id"]
            or user["candidate"] != json.loads(old["user"])["candidate"]
            or row["system"] != reconstruction.SYSTEM
        ):
            raise ValueError("immutable candidate or diagnostic prompt changed")
        eligible = bool(sources["NEWS"] and sources["MACRO"])
        if (
            type(row["dispatch_eligible"]) is not bool
            or row["dispatch_eligible"] != eligible
        ):
            raise ValueError("missing source cannot become a paid diagnostic")
        for kind, records in sources.items():
            for record in records:
                age = row["historical_cut_ms"] - record["published_upper_ms"]
                if not 0 <= age <= (86400000 if kind == "NEWS" else 31 * 86400000):
                    raise ValueError("future/stale proxy context")
    if (
        sum(r["dispatch_eligible"] for r in rows)
        + plan.get("prior_provider_attempts", 0)
        > plan["max_attempts"]
    ):
        raise ValueError("cumulative attempt limit exceeded")
    return plan, rows


def capture_signature(manifest_path, sources_path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    projected = json.loads(sources_path.read_text(encoding="utf-8"))
    originals = {row["id"]: row for row in manifest["sources"]}
    if len(originals) != len(manifest["sources"]) or set(originals) != {
        r["id"] for r in projected["sources"]
    }:
        raise ValueError("raw source projection roster mismatch")
    result = {
        "manifest": existing.sha(manifest_path),
        "projection": existing.sha(sources_path),
    }
    for row in projected["sources"]:
        original = originals[row["id"]]
        relative = Path(original["raw_file"].replace("\\", "/"))
        if (
            relative.is_absolute()
            or len(relative.parts) != 2
            or relative.parts[0] != "raw"
            or relative.name in {".", ".."}
        ):
            raise ValueError("exact relative raw artifact path required")
        target = (manifest_path.parent / relative).resolve(strict=True)
        if (
            target.parent != (manifest_path.parent / "raw").resolve(strict=True)
            or target.is_symlink()
        ):
            raise ValueError("source artifact escapes bounded raw input directory")
        value = existing.sha(target)
        if value != row["raw_sha256"] or value != original["raw_sha256"]:
            raise ValueError("retained raw source digest mismatch")
        if any(
            row[name] != original[name]
            for name in (
                "payload_json",
                "published_upper_ms",
                "captured_ms",
                "url",
                "kind",
            )
        ):
            raise ValueError("source excerpt/provenance projection changed")
        result[row["id"]] = value
    return result


async def run(args):
    plan, requests = checked_requests(
        args.evidence, args.sources, args.baseline, args.prior_failed_run
    )
    raw_signature = capture_signature(args.capture_manifest, args.sources)
    frozen = hashlib.sha256(
        existing.json.dumps((plan, requests), sort_keys=True).encode()
    ).hexdigest()
    if (
        len(requests) != 12
        or plan["max_attempts"] != 12
        or not any(r["dispatch_eligible"] for r in requests)
    ):
        raise ValueError("exact nonempty bounded twelve-candidate roster required")
    existing.write(
        args.one_shot_root / "publication-proxy-20261015.provider-start.json",
        {
            "experiment_id": plan["experiment_id"],
            "source_bundle_sha256": plan["source_bundle_sha256"],
            "requests_sha256": existing.sha(args.evidence / "requests.json"),
            "started_at_ms": time.time_ns() // 1000000,
            "no_automatic_resume_or_retry": True,
        },
    )
    existing.write(
        args.evidence / "worker-start.json",
        {
            "experiment_id": plan["experiment_id"],
            "scope": "PUBLICATION_ONLY_DIAGNOSTIC",
            "started_at_ms": time.time_ns() // 1000000,
            "one_shot": True,
            "worker_sha256": existing.sha(Path(__file__)),
            "raw_input_signature": raw_signature,
        },
    )
    # Secrets exist only in protected file mounts and memory, never argv/output.
    key = args.openai_key.read_text().strip()
    password = args.database_password.read_text().strip()
    if not key or not password:
        raise ValueError("protected existing credentials unavailable")
    database = existing.Database(
        existing.PersistenceSettings(
            _env_file=None,
            database_url="postgresql://kairos:"
            + quote(password, safe="")
            + "@timescaledb:5432/kairos",
            pool_min_size=1,
            pool_max_size=2,
        )
    )
    gateway = None
    try:
        await existing.connect_verified_database(database, "kairos", local_only=True)
        await database.verify_schema()
        repo = existing.SourceStateRepository(
            database.pool, campaign_id=plan["shared_campaign"]
        )
        before = await repo.campaign_usage("openai")
        adoption = await database.pool.fetchrow(
            "SELECT * FROM campaign_source_budgets WHERE source='openai'"
        )
        if (
            before.budget_microusd != plan["shared_openai_cap_microusd"]
            or before.historical_cost_microusd != plan["historical_cost_microusd"]
            or adoption["historical_evidence_sha256"]
            != plan["historical_budget_evidence_sha256"]
        ):
            raise ValueError("authoritative cumulative budget identity changed")
        budget = existing.ScopedBudget(
            existing.CampaignLLMUsageBudget(repo),
            args.evidence / "local-budget.jsonl",
            plan["max_local_reserved_microusd"]
            - plan.get("prior_local_held_microusd", 0),
        )
        native = existing.LLMGateway(
            existing.LLMSettings(
                _env_file=None,
                openai_api_key=key,
                openai_base_url="https://api.openai.com/v1",
                max_retries=0,
                max_output_tokens=2048,
                request_timeout_s=plan["request_timeout_seconds"],
            ),
            router=existing.FixedRouter(),
        )
        gateway = existing.BudgetedLLMGateway(native, budget)
        import kairos_llm.budget as budget_module
        import kairos_llm.gateway as gateway_module
        import kairos_llm.pricing as pricing_module

        existing.write(
            args.evidence / "gateway-source.json",
            {
                "image": plan["gateway_image"],
                "cumulative_budget_before": asdict(before),
                "registered_price": asdict(gateway.prices.for_model("gpt-6-luna")),
                "loaded_source_sha256": {
                    m.__name__: existing.sha(Path(m.__file__))
                    for m in (budget_module, gateway_module, pricing_module)
                },
            },
        )
        failures = 0
        observed = []
        for number, row in enumerate(requests, 1):
            identity = {
                k: row[k] for k in ("candidate_id", "window_id", "prompt_sha256")
            }
            if not row["dispatch_eligible"]:
                receipt = {
                    **identity,
                    "state": "NOT_CALLED_MISSING_PROXY_CONTEXT",
                    "decision": "DEFER",
                    "actual_microusd": 0,
                    "no_call_reason": "MISSING_PUBLICATION_PROXY_CONTEXT",
                    "modern_attempt_started_ms": None,
                    "modern_response_observed_ms": None,
                    "modern_adapter_finished_ms": None,
                    "request_id": None,
                    "budget_reservation_id": None,
                }
            elif failures >= plan["stop_after_consecutive_request_failures"]:
                receipt = {
                    **identity,
                    "state": "NOT_CALLED_AFTER_FAILURE_LIMIT",
                    "decision": "DEFER",
                    "actual_microusd": None,
                }
            else:
                current = checked_requests(
                    args.evidence, args.sources, args.baseline, args.prior_failed_run
                )
                if (
                    hashlib.sha256(
                        existing.json.dumps(current, sort_keys=True).encode()
                    ).hexdigest()
                    != frozen
                    or capture_signature(args.capture_manifest, args.sources)
                    != raw_signature
                ):
                    raise ValueError("input sources changed after worker start")
                existing.append(
                    args.evidence / "attempts.jsonl",
                    {
                        **identity,
                        "state": "ONE_SHOT_PROXY_ATTEMPT",
                        "observed_at_ms": time.time_ns() // 1000000,
                    },
                )
                started = time.monotonic_ns()
                try:
                    response = await gateway.complete(
                        system=row["system"],
                        user=row["user"],
                        workload=existing.LLMWorkload.AGGREGATOR_NORMAL,
                        schema=existing.Review,
                    )
                    finished = time.time_ns() // 1000000
                    if (
                        not isinstance(response.parsed, existing.Review)
                        or response.budget_reservation_id is None
                    ):
                        raise ValueError("typed committed result required")
                    receipt = {
                        **identity,
                        "state": "OBSERVED_COMMITTED",
                        "decision": response.parsed.decision,
                        "reason": response.parsed.reason,
                        "model": response.model,
                        "effort": response.effort,
                        "resolved_model": response.resolved_model,
                        "request_id": response.request_id,
                        "usage": asdict(response.usage),
                        "actual_microusd": math.ceil(response.cost_usd * 1000000),
                        "budget_reservation_id": response.budget_reservation_id,
                        "modern_attempt_started_ms": response.attempt_started_at_ts_ms,
                        "modern_response_observed_ms": response.response_observed_at_ts_ms,
                        "modern_adapter_finished_ms": finished,
                        "measured_pipeline_duration_ms": max(
                            1, math.ceil((time.monotonic_ns() - started) / 1000000)
                        ),
                        "clock_authority": plan["latency_authority"],
                    }
                    failures = 0
                except Exception as exc:  # noqa: BLE001 - retain holds, never print credentials/SDK diagnostics
                    failures += 1
                    receipt = {
                        **identity,
                        "state": "FAILED_CLOSED_COST_UNKNOWN_HELD",
                        "decision": "DEFER",
                        "actual_microusd": None,
                        "error_type": type(exc).__name__,
                        "http_status": getattr(exc, "status_code", None)
                        if type(getattr(exc, "status_code", None)) is int
                        else None,
                        "api_error_code": getattr(exc, "code", None)
                        if getattr(exc, "code", None)
                        in {
                            "invalid_api_key",
                            "insufficient_quota",
                            "rate_limit_exceeded",
                            "model_not_found",
                            "permission_denied",
                        }
                        else None,
                    }
            observed.append(receipt)
            journal = "reviews.jsonl" if row["dispatch_eligible"] else "no-calls.jsonl"
            existing.append(args.evidence / journal, receipt)
            print(
                f"proxy_progress={number}/12 state={receipt['state']} decision={receipt['decision']}",
                flush=True,
            )
        current = checked_requests(
            args.evidence, args.sources, args.baseline, args.prior_failed_run
        )
        if (
            hashlib.sha256(
                existing.json.dumps(current, sort_keys=True).encode()
            ).hexdigest()
            != frozen
            or capture_signature(args.capture_manifest, args.sources) != raw_signature
        ):
            raise ValueError("input sources changed before finalization")
        complete = all(
            r["state"] in {"OBSERVED_COMMITTED", "NOT_CALLED_MISSING_PROXY_CONTEXT"}
            for r in observed
        )
        existing.write(
            args.evidence / "worker-result.json",
            {
                "state": "COMPLETED_PROXY_DIAGNOSTIC"
                if complete
                else "INCOMPLETE_FAIL_CLOSED",
                "real_model_calls": sum(
                    r["state"] == "OBSERVED_COMMITTED" for r in observed
                ),
                "candidate_count": len(observed),
                "local_budgeted_microusd": budget.held,
                "cumulative_budget_after": asdict(await repo.campaign_usage("openai")),
                "full_system_tested": False,
                "strict_causal_admission": False,
            },
        )
        return 0 if complete else 2
    finally:
        if gateway is not None:
            await gateway.close()
        await database.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--capture-manifest", type=Path, required=True)
    parser.add_argument("--one-shot-root", type=Path, required=True)
    parser.add_argument("--prior-failed-run", type=Path)
    parser.add_argument("--openai-key", type=Path, required=True)
    parser.add_argument("--database-password", type=Path, required=True)
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except Exception as exc:  # noqa: BLE001 - sanitized top-level failure, no retry
        if not (args.evidence / "worker-failure.json").exists():
            existing.write(
                args.evidence / "worker-failure.json",
                {"state": "FAILED_CLOSED", "error_type": type(exc).__name__},
            )
        print(f"state=FAILED_CLOSED error_type={type(exc).__name__}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
