"""Plan-review-first CURRENT v3 orchestration for real observed inputs.

This is a new planning/entry path. It does not call the frozen four-arm
Catalyst materializer or reinterpret a plan-level LLM review as executable
authorization. A successful run records only observed SIM requests; later
sealed native replay remains the only route to Risk/SIM execution evidence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from adaptive_replay.complex_assessment import DirectionalAssessment
from adaptive_replay.complex_strategy import crash_defense, evaluate_complex, map_context_proposal
from adaptive_replay.hypothesis_v3 import (
    CreationAssessment,
    EntryQuote,
    HypothesisObservation,
    HypothesisPolicy,
    creation_input_sha256,
)
from adaptive_replay.scenarios import ScenarioEvidence, ScenarioObservation
from kairos_core.contracts import RecordedTopNBookFrameV2
from kairos_core.enums import ReasoningEffort, StrategicTrigger
from kairos_llm import LLMWorkload
from kairos_macro.strategist import MacroStrategist
from kairos_strategy.adaptive.logic import evaluate_adaptive
from kairos_strategy.candles import Candle
from kairos_strategy.provenance import candle_payload
from kairos_strategy.runtime import candle_to_closed_bar
from kairos_text.config import TextSettings
from kairos_text.service import TextScoutsService

from .current_capture import FreshQuoteSnapshot
from .current_inputs import (
    BAR_MS,
    CAPTURE_UNIVERSE,
    UNIVERSE,
    CurrentCutInputs,
)
from .current_plan import (
    PLANNING_TTL_CAPS,
    STRATEGY_REVISION,
    CurrentPlan,
    CurrentPlanReview,
    PlanningSource,
    authorize_current_entry,
    macro_allocation_allows_entry,
    review_current_plan,
)
from .current_runner import (
    _DIRECTION_SYSTEM,
    MAX_LOCAL_COST_MICROUSD,
    MAX_PROVIDER_CALLS,
    CurrentRunConfig,
    CurrentRunRefused,
    CurrentRunServices,
    OpenRiskSnapshot,
    StageRecord,
    UsageSnapshot,
    _by_symbol,
    _canonical_sha,
    _CollectingMemoryBus,
    _CreateOnlyRunLock,
    _fold_worker,
    _now_ms,
    _receipt_value,
    _run_cpu,
    _run_fold,
    _safe_exception,
    _scheduled_wait_seconds,
    _stage,
    _stop_risk_microusd,
    _usage_delta,
    write_create_only,
)

_SCHEMA = "kairos.current-plan-run.v3"
_MAX_RUN_OBSERVATION_MS = 300_000
_SOURCE_CAPTURE_LIMIT_MS = 900_000
_MAX_SINGLE_STOP_RISK_MICROUSD = 25_000_000
_MAX_TOTAL_OPEN_RISK_MICROUSD = 100_000_000
_CREATION_EVIDENCE_TTLS = {"MARKET": 900_000, "NEWS": 1_800_000, "MACRO": 1_800_000}


class CurrentPlanRunRefused(RuntimeError):
    """Sanitized plan-first run refusal."""


def _is_budget_refusal(exc: BaseException) -> bool:
    return isinstance(exc, CurrentRunRefused) and str(exc) in {
        "PROVIDER_CALL_CAP_EXCEEDED",
        "LOCAL_COST_CAP_EXCEEDED",
    }


@asynccontextmanager
async def _drain_observers_on_error(tasks: list[tuple[str, asyncio.Task]]):
    try:
        yield
    except BaseException:
        await _cancel_observers(tasks)
        raise


async def _cancel_observers(
    tasks: tuple[tuple[str, asyncio.Task], ...] | list[tuple[str, asyncio.Task]],
) -> None:
    pending = tuple(task for _, task in tasks if not task.done())
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _run_plan_fold(fold_lock: asyncio.Lock, operation, /, *args, **kwargs):
    async with fold_lock:
        return await _run_fold(operation, *args, **kwargs)


async def _gather_observers(tasks: list[tuple[str, asyncio.Task]]):
    pending = {task for _, task in tasks}
    completed = {}
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            result = asyncio.CancelledError() if task.cancelled() else task.exception()
            if isinstance(result, BaseException) and _is_budget_refusal(result):
                await _cancel_observers(tuple(("", other) for other in pending))
                raise result
            completed[task] = result if isinstance(result, BaseException) else task.result()
    return [completed[task] for _, task in tasks]


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _ms(value: Any) -> int:
    if type(value) is int:
        return value
    if hasattr(value, "utcoffset") and value.utcoffset() is not None:
        return int(value.timestamp() * 1_000)
    raise CurrentPlanRunRefused("SOURCE_EVENT_CLOCK_UNAVAILABLE")


def _model_payload(value: Any) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dataclass_fields__"):
        return _receipt_value(value)
    raise CurrentPlanRunRefused("TYPED_SOURCE_PAYLOAD_REQUIRED")


def _planning_source(
    kind: str,
    payloads: list[dict],
    *,
    event_ms: int,
    received_ms: int,
    persisted_ms: int,
    ttl_ms: int,
) -> PlanningSource:
    return PlanningSource(
        kind,
        _canonical(payloads).decode("utf-8"),
        event_ms,
        received_ms,
        persisted_ms,
        min(ttl_ms, PLANNING_TTL_CAPS[kind]),
    )


def _planning_context(
    *,
    symbol: str,
    history,
    signals: tuple,
    macro_allocation,
    macro_received_ms: int,
    signal_received_ms: int,
    quote: FreshQuoteSnapshot,
    market_snapshot,
) -> tuple[PlanningSource, ...]:
    rows = tuple(history.bars_by_symbol[symbol])
    pages = tuple(page for page in history.page_receipts if page.symbol == symbol)
    if len(rows) != 3_240 or not pages:
        raise CurrentPlanRunRefused("COMPLETE_RETAINED_MARKET_SOURCE_REQUIRED")
    latest_page = max(pages, key=lambda page: page.page)
    received = max(page.received_ms for page in pages)
    persisted = max(page.persisted_ms for page in pages)
    quote_row = quote.entry_quote
    text_event_ms = min(_ms(signal.produced_at) for signal in signals)
    if text_event_ms > signal_received_ms:
        raise CurrentPlanRunRefused("TEXT_SIGNAL_CLOCK_AFTER_CAPTURE")
    source_rows = (
        _planning_source(
            "MARKET",
            [
                {
                    "quote": _model_payload(quote_row),
                    "quote_raw_sha256": quote.raw_sha256,
                    "market_snapshot": _model_payload(market_snapshot),
                }
            ],
            event_ms=quote_row.event_ms,
            received_ms=quote.received_ms,
            persisted_ms=quote.captured_ms,
            ttl_ms=PLANNING_TTL_CAPS["MARKET"],
        ),
        _planning_source(
            "CLOSED_BARS",
            [
                {
                    "source_id": latest_page.source_id,
                    "page_sha256": latest_page.raw_sha256,
                    "bar_count": len(rows),
                    "bars": [candle_payload(row) for row in rows[-60:]],
                }
            ],
            event_ms=rows[-1].close_time_ms,
            received_ms=received,
            persisted_ms=persisted,
            ttl_ms=PLANNING_TTL_CAPS["CLOSED_BARS"],
        ),
        _planning_source(
            "TEXT",
            [_model_payload(signal) for signal in signals],
            event_ms=text_event_ms,
            received_ms=signal_received_ms,
            persisted_ms=signal_received_ms,
            ttl_ms=600_000,
        ),
        _planning_source(
            "MACRO",
            [_model_payload(macro_allocation)],
            event_ms=_ms(macro_allocation.produced_at),
            received_ms=macro_received_ms,
            persisted_ms=macro_received_ms,
            ttl_ms=1_800_000,
        ),
    )
    return source_rows


def _current_creation_evidence(cell) -> tuple[ScenarioEvidence, ...]:
    original = tuple(cell.price.sources)
    output = []
    for item in original:
        ttl = _CREATION_EVIDENCE_TTLS.get(item.kind)
        if ttl is None:
            raise CurrentPlanRunRefused("UNSUPPORTED_CREATION_EVIDENCE_KIND")
        # This is the new plan-reviewed version's bounded lifetime. Original
        # event, receive, persistence, identity and content hash remain exact;
        # the old cell/evidence object is never changed.
        output.append(
            ScenarioEvidence(
                item.source_id,
                item.kind,
                item.symbol,
                item.payload_sha256,
                item.event_ms,
                item.received_ms,
                item.captured_ms,
                ttl,
            )
        )
    return tuple(sorted(output, key=lambda item: (item.kind, item.source_id)))


def _plan_for_candidate(
    *,
    template,
    origin: str,
    complex_decision,
    cell,
    context: tuple[PlanningSource, ...],
    config: CurrentRunConfig,
    quote: FreshQuoteSnapshot,
    directional_sha256: str | None,
    directional_result,
    directional_assessment,
    directional_input_json: str | None,
    created_at_ms: int,
) -> tuple[CurrentPlan, tuple[ScenarioEvidence, ...]]:
    evidence = _current_creation_evidence(cell)
    required = tuple(sorted({(item.kind, item.source_id) for item in evidence}))
    anchor = cell.price.rows[-1]
    quote_row = quote.entry_quote
    policy = HypothesisPolicy(
        sealed_ms=config.cut_ms,
        hypothesis_lifetime_ms=900_000,
        quote_source_id=quote_row.source_id,
        maximum_quote_age_ms=2_000,
        evidence_kind=quote_row.evidence_kind,
        require_review=True,
    )
    assessment = None
    if origin == "CONTEXT_PROPOSAL":
        if (
            directional_result is None
            or directional_assessment is None
            or directional_sha256 is None
            or directional_input_json is None
        ):
            raise CurrentPlanRunRefused("ORIGINAL_DIRECTIONAL_ASSESSMENT_REQUIRED")
        directional_input_sha = hashlib.sha256(directional_input_json.encode("utf-8")).hexdigest()
        input_sha = creation_input_sha256(
            config.source_set_sha256,
            directional_input_sha,
            anchor,
            evidence,
        )
        assessment = CreationAssessment(
            input_sha,
            directional_sha256,
            config.model_config_sha256,
            directional_assessment.proposal,
            directional_result.attempt_started_at_ts_ms,
            directional_result.response_observed_at_ts_ms,
            created_at_ms,
            "CALLER_ATTESTED_POINT_IN_TIME",
        )
    max_until = min(
        config.cut_ms + min(900_000, policy.hypothesis_lifetime_ms) - 1,
        *(item.event_ms + item.ttl_ms for item in evidence),
        *(item.event_ms + item.ttl_ms for item in context),
    )
    plan = CurrentPlan(
        template=template,
        origin=origin,
        regime=complex_decision.regime,
        defense=complex_decision.defense,
        origin_cut_ms=config.cut_ms,
        created_at_ms=created_at_ms,
        valid_until_ms=max_until,
        source_set_sha256=config.source_set_sha256,
        creation_evidence=evidence,
        anchor=anchor,
        required_sources=required,
        policy=policy,
        context=context,
        creation_assessment=assessment,
        creation_input_json=directional_input_json,
    )
    plan.__post_init__()
    return plan, tuple(cell.price.sources)


def _triggered(template, candle: Candle) -> tuple[bool, bool]:
    if template.side.value == "LONG":
        invalidated = candle.low <= template.exit_plan.stop_price
        confirmed = candle.close > template.reference_price
    else:
        invalidated = candle.high >= template.exit_plan.stop_price
        confirmed = candle.close < template.reference_price
    return invalidated, confirmed


def _native_prefix(symbol, cut_ms: int, history_rows, roster, observations):
    if not callable(getattr(roster, "get", None)):
        raise CurrentPlanRunRefused("ACTUAL_CLOSED_BAR_ROSTER_REQUIRED")
    retained = roster.get(symbol)
    if type(retained) is not tuple:
        raise CurrentPlanRunRefused("ACTUAL_CLOSED_BAR_ROSTER_REQUIRED")
    observed_by_open: dict[int, Any] = {}
    max_close = observations[-1].market.candle.close_time_ms
    for receipt in retained:
        receipt.__post_init__()
        if receipt.candle.open_time_ms < cut_ms or receipt.candle.close_time_ms > max_close:
            continue
        existing = observed_by_open.get(receipt.candle.open_time_ms)
        if existing is not None and existing != receipt:
            raise CurrentPlanRunRefused("CONFLICTING_NATIVE_CLOSED_BAR_RECEIPT")
        observed_by_open[receipt.candle.open_time_ms] = receipt
    expected = cut_ms
    after = []
    while expected <= max_close:
        receipt = observed_by_open.get(expected)
        if receipt is None:
            raise CurrentPlanRunRefused("CURRENT_NATIVE_BAR_ROSTER_GAP")
        after.append(receipt.candle)
        expected += BAR_MS
    retained_by_open = {bar.open_time_ms: bar for bar in after}
    for item in observations:
        candle = item.market.candle
        if retained_by_open.get(candle.open_time_ms) != candle:
            raise CurrentPlanRunRefused("OBSERVATION_NOT_BOUND_TO_NATIVE_BAR_ROSTER")
    full = tuple(history_rows) + tuple(after)
    if len(full) < 3_240 or any(
        right.open_time_ms != left.close_time_ms + 1 for left, right in zip(full[:-1], full[1:], strict=True)
    ):
        raise CurrentPlanRunRefused("GAPLESS_ORIGINAL_TO_CONFIRMATION_BAR_PREFIX_REQUIRED")
    return tuple(candle_to_closed_bar(bar) for bar in full), full


async def _observe_confirm_and_authorize(
    *,
    plan: CurrentPlan,
    review: CurrentPlanReview,
    history,
    symbol: str,
    cut_ms: int,
    observation_source,
    risk_frame_source,
    fold_lock: asyncio.Lock,
    deferred_requests,
    artifact_root: Path,
    code_sha256: str,
    config_sha256: str,
    run_deadline_ms: int,
    risk_lock: asyncio.Lock,
    aggregate_open_risk: list[int],
    requested_quantity: float,
):
    if review.decision.value != "ALLOW":
        return {"state": "PLAN_REVIEW_" + review.decision.value, "reason_codes": list(review.reason_codes)}
    bar_source = getattr(observation_source, "bar_source", None)
    quote_source = getattr(observation_source, "quote_source", None)
    if (
        not callable(getattr(bar_source, "wait_closed_bar", None))
        or not callable(getattr(bar_source, "closed_bar_roster", None))
        or not callable(getattr(quote_source, "fresh_quote", None))
    ):
        return {"state": "NO_ENTRY", "reason": "ACTUAL_POST_REVIEW_BAR_AND_QUOTE_SOURCES_REQUIRED"}
    expected_open = ((review.completed_at_ms + BAR_MS - 1) // BAR_MS) * BAR_MS
    latest_close = expected_open - 1
    deadline = min(run_deadline_ms, plan.valid_until_ms, cut_ms + _MAX_RUN_OBSERVATION_MS)
    original_sources = tuple(plan.creation_evidence)
    observations: list[HypothesisObservation] = []
    for _index in range(5):
        remaining_ms = deadline - _now_ms()
        if remaining_ms <= 0:
            return {"state": "NO_ENTRY", "reason": "POST_REVIEW_CONFIRMATION_WINDOW_ELAPSED"}
        captured = await bar_source.wait_closed_bar(
            symbol,
            latest_close,
            timeout_s=min(
                remaining_ms / 1_000,
                max(1.0, (expected_open + BAR_MS + 5_000 - _now_ms()) / 1_000),
            ),
        )
        if captured is None:
            return {"state": "NO_ENTRY", "reason": "POST_REVIEW_CLOSED_BAR_UNAVAILABLE"}
        captured.__post_init__()
        candle = captured.candle
        if (
            candle.symbol != symbol
            or candle.timeframe != "1m"
            or candle.open_time_ms != expected_open
            or candle.close_time_ms != expected_open + BAR_MS - 1
            or captured.received_ms > deadline
            or captured.captured_ms > deadline
        ):
            return {"state": "NO_ENTRY", "reason": "POST_REVIEW_BAR_GAP_OR_LATE"}
        observed_ms = max(captured.captured_ms, _now_ms())
        if observed_ms >= candle.open_time_ms + 2 * BAR_MS:
            return {"state": "NO_ENTRY", "reason": "POST_REVIEW_BAR_OBSERVED_TOO_LATE"}
        market = ScenarioEvidence(
            captured.source_id,
            "MARKET",
            symbol,
            hashlib.sha256(_canonical(candle_payload(candle))).hexdigest(),
            candle.close_time_ms,
            captured.received_ms,
            captured.captured_ms,
            _CREATION_EVIDENCE_TTLS["MARKET"],
        )
        evidence = tuple(sorted((*original_sources, market), key=lambda item: (item.kind, item.source_id)))
        observation = HypothesisObservation(ScenarioObservation(candle, observed_ms, evidence), None)
        observations.append(observation)
        invalidated, confirmed = _triggered(plan.template, candle)
        if invalidated:
            return {
                "state": "NO_ENTRY",
                "reason": "PLAN_STOP_INVALIDATED",
                "observed_bars": len(observations),
            }
        if confirmed:
            # Before the only entry quote, require the original native stream's
            # complete cut-to-trigger bar roster and unchanged fresh defense.
            roster = bar_source.closed_bar_roster()
            input_bars, full_candles = _native_prefix(
                symbol, cut_ms, history.bars_by_symbol[symbol], roster, tuple(observations)
            )
            adaptive = await _run_plan_fold(fold_lock, evaluate_adaptive, full_candles[-3_240:])
            defense = await _run_plan_fold(fold_lock, crash_defense, adaptive, full_candles[-3_240:])
            capabilities = {
                "BULL": {"LONG"},
                "BEAR": {"SHORT"},
                "RANGE": {"LONG", "SHORT"},
            }
            supported = adaptive.regime.value in capabilities
            side_allowed = plan.origin == "CONTEXT_PROPOSAL" or plan.template.side.value in capabilities.get(
                adaptive.regime.value, set()
            )
            if defense != "NORMAL" or not supported or not side_allowed:
                return {
                    "state": "NO_ENTRY",
                    "reason": "FRESH_DEFENSE_OR_REGIME_REJECTED",
                    "defense": defense,
                    "regime": adaptive.regime.value,
                    "observed_bars": len(observations),
                }
            assert_continuous = getattr(bar_source, "assert_continuous_source", None)
            if callable(assert_continuous):
                assert_continuous()
            if _now_ms() >= deadline:
                return {"state": "NO_ENTRY", "reason": "ENTRY_WINDOW_ELAPSED_BEFORE_QUOTE"}
            async with fold_lock:
                entry_quote_snapshot = await quote_source.fresh_quote(symbol)
                if (
                    type(entry_quote_snapshot) is not FreshQuoteSnapshot
                    or entry_quote_snapshot.symbol != symbol
                ):
                    return {"state": "NO_ENTRY", "reason": "FRESH_ENTRY_QUOTE_UNAVAILABLE"}
                quote = entry_quote_snapshot.entry_quote
                if type(quote) is not EntryQuote or quote.event_ms <= candle.close_time_ms:
                    return {"state": "NO_ENTRY", "reason": "ENTRY_QUOTE_NOT_AFTER_FIRST_CONFIRMATION"}
                authorized_at_ms = max(_now_ms(), entry_quote_snapshot.captured_ms)
                if authorized_at_ms > deadline:
                    return {"state": "NO_ENTRY", "reason": "ENTRY_WINDOW_ELAPSED_AFTER_QUOTE"}
                final_obs = HypothesisObservation(
                    ScenarioObservation(candle, authorized_at_ms, evidence),
                    quote,
                )
                observations[-1] = final_obs
                authorization = await _run_fold(
                    authorize_current_entry,
                    plan,
                    review,
                    tuple(observations),
                    input_bars=input_bars,
                    authorized_at_ms=authorized_at_ms,
                    code_sha256=code_sha256,
                    config_sha256=config_sha256,
                    strategy_revision=STRATEGY_REVISION,
                )
            auth_path = _plan_artifact_path(
                artifact_root, "entry-authorization", symbol, authorization.sha256
            )
            await _run_cpu(write_create_only, auth_path, authorization.payload())

            intent = authorization.intent
            risk_microusd = _stop_risk_microusd(
                requested_quantity,
                quote.ask if intent.side.value == "LONG" else quote.bid,
                intent.exit_plan.stop_price,
            )
            async with risk_lock:
                if risk_microusd > _MAX_SINGLE_STOP_RISK_MICROUSD:
                    return {
                        "state": "NO_ENTRY",
                        "reason": "REJECTED_PER_TRADE_STOP_RISK_OVER_25_USD",
                        "requested_stop_risk_microusd": risk_microusd,
                    }
                if aggregate_open_risk[0] + risk_microusd > _MAX_TOTAL_OPEN_RISK_MICROUSD:
                    return {
                        "state": "NO_ENTRY",
                        "reason": "REJECTED_AGGREGATE_OPEN_RISK_OVER_100_USD",
                        "requested_stop_risk_microusd": risk_microusd,
                        "aggregate_open_risk_microusd": aggregate_open_risk[0],
                    }
                if _now_ms() > min(deadline, intent.entry_expires_ts_ms) or (
                    _now_ms() - quote.event_ms > min(quote.ttl_ms, plan.policy.maximum_quote_age_ms)
                ):
                    return {"state": "NO_ENTRY", "reason": "ORIGINAL_ENTRY_QUOTE_EXPIRED_BEFORE_REQUEST"}
                request_ms, frame = await risk_frame_source.request_snapshot(symbol)
                if (
                    type(request_ms) is not int
                    or request_ms < quote.event_ms
                    or request_ms > _now_ms()
                    or request_ms > min(deadline, intent.entry_expires_ts_ms)
                    or request_ms - quote.event_ms > min(quote.ttl_ms, plan.policy.maximum_quote_age_ms)
                    or type(frame) is not RecordedTopNBookFrameV2
                    or frame.symbol != symbol
                    or frame.tape_id != deferred_requests.plan.tape_id
                    or frame.persisted_at_ms > request_ms
                ):
                    return {"state": "NO_ENTRY", "reason": "EXACT_LIVE_REQUEST_FRAME_UNAVAILABLE_OR_STALE"}
                outcome = await deferred_requests.record(
                    intent=intent,
                    review=authorization.native_review,
                    quote=entry_quote_snapshot,
                    frame=frame,
                    request_ms=request_ms,
                    requested_quantity=requested_quantity,
                    entry_authorization=authorization,
                )
                aggregate_open_risk[0] += risk_microusd
            return {
                "state": "OBSERVED_REQUEST_PENDING_LATER_NATIVE_SIM_REPLAY",
                "intent_sha256": intent.intent_id,
                "authorization_sha256": authorization.sha256,
                "observed_request_sequence": outcome["sequence"],
                "actual_live_risk_or_execution": False,
                "requested_stop_risk_microusd": risk_microusd,
                "aggregate_open_risk_microusd": aggregate_open_risk[0],
            }
        latest_close = candle.close_time_ms
        expected_open += BAR_MS
    return {"state": "NO_ENTRY", "reason": "FIRST_CONFIRMATION_NOT_FOUND_WITHIN_FIVE_BARS"}


def _plan_artifact_path(root: Path, kind: str, symbol: str, identity: str) -> Path:
    return root / "plan-reviews" / f"{kind}-{symbol}-{identity[:16]}.json"


async def run_one_plan_cut(config: CurrentRunConfig, services: CurrentRunServices) -> dict[str, Any]:
    """Run the separately-versioned plan-review-first CURRENT path.

    All outputs are local create-only receipts. No direct live/PAPER action is
    available here; entry authorization becomes a deferred native-SIM request
    only, followed later by the existing source seal and replay.
    """
    config.__post_init__()
    deferred = services.deferred_requests
    if (
        deferred is None
        or services.simulation_session != getattr(deferred, "plan", None)
        or not callable(getattr(deferred, "record", None))
        or not callable(getattr(services.risk_frame_source, "request_snapshot", None))
        or not callable(services.open_risk_snapshot)
        or not callable(services.usage_snapshot)
        or not callable(getattr(services.gateway, "complete", None))
        or not callable(services.build_cut_inputs)
    ):
        raise CurrentRunRefused("EXPLICIT_DEFERRED_NATIVE_SIM_DEPENDENCIES_REQUIRED")
    if config.output_path.exists():
        raise CurrentRunRefused("CREATE_ONLY_RECEIPT_EXISTS")
    artifact_root = config.output_path.parent
    (artifact_root / "plan-reviews").mkdir(parents=True, exist_ok=True)
    _scheduled_wait_seconds(config.cut_ms, _now_ms())
    baseline = await services.usage_snapshot()
    if type(baseline) is not UsageSnapshot:
        raise CurrentRunRefused("PROVIDER_LEDGER_UNAVAILABLE")
    initial_open = await services.open_risk_snapshot()
    if type(initial_open) is not OpenRiskSnapshot:
        raise CurrentRunRefused("ISOLATED_SIM_OPEN_RISK_SNAPSHOT_REQUIRED")
    now = _now_ms()
    if initial_open.observed_ms > now or now - initial_open.observed_ms > 300_000:
        raise CurrentRunRefused("ISOLATED_SIM_OPEN_RISK_SNAPSHOT_STALE")
    records: list[StageRecord] = []
    creation_results: list[dict] = []
    plan_reviews: list[dict] = []
    candidate_receipts: list[dict] = []
    slot_results: list[dict] = []
    sim_outcomes: list[dict] = []
    observer_tasks: list[tuple[str, asyncio.Task]] = []
    risk_lock = asyncio.Lock()
    fold_lock = asyncio.Lock()
    aggregate_open_risk = [initial_open.amount_microusd]
    began = time.monotonic()
    receipt: dict[str, Any] = {
        "schema_version": _SCHEMA,
        "run_id": config.run_id,
        "classification": "CURRENT_RESEARCH_SIM_ONLY",
        "planning_semantics": "PLAN_LLM_REVIEW_BEFORE_NEW_POST_REVIEW_CONFIRMATION_AND_ENTRY_QUOTE_V3",
        "source_set_sha256": config.source_set_sha256,
        "model_config_sha256": config.model_config_sha256,
        "capture_window_ms": [config.capture_start_ms, config.capture_end_ms],
        "scheduled_cut_ms": config.cut_ms,
        "universe": list(UNIVERSE),
        "stages": [],
        "provider_attempts": [],
        "creation_results": creation_results,
        "plan_reviews": plan_reviews,
        "entry_authorizations": [],
        "slot_results": slot_results,
        "sim_outcomes": sim_outcomes,
        "macro_capital_allowed": False,
        "result": "INCOMPLETE",
        "readiness": {
            "paper_qualified": False,
            "alpha_ready": False,
            "live_ready": False,
            "strategy_policy": "REJECT_ALL",
        },
    }
    try:
        with _CreateOnlyRunLock(config.output_path.with_suffix(config.output_path.suffix + ".lock")):
            async with (
                _fold_worker(),
                _drain_observers_on_error(observer_tasks),
                asyncio.timeout(config.max_wall_seconds),
            ):
                text_snapshot = await _stage(
                    "capture_text", services.capture.capture_text, services.usage_snapshot, baseline, records
                )
                if not (
                    config.capture_start_ms
                    <= text_snapshot.requested_ms
                    <= text_snapshot.received_ms
                    <= config.capture_end_ms
                ):
                    raise CurrentRunRefused("TEXT_CAPTURE_CLOCK_OUTSIDE_DECLARED_WINDOW")
                while (remaining := _scheduled_wait_seconds(config.cut_ms, _now_ms())) > 0:
                    await asyncio.sleep(min(10.0, remaining))
                history = await _stage(
                    "capture_history",
                    lambda: services.capture.fetch_history(config.cut_ms),
                    services.usage_snapshot,
                    baseline,
                    records,
                )
                if (
                    history.cut_ms != config.cut_ms
                    or set(history.bars_by_symbol) != set(UNIVERSE)
                    or any(len(history.bars_by_symbol[symbol]) != 3_240 for symbol in UNIVERSE)
                    or history.coverage_scope != "FIVE_SYMBOLS_EXACT_54H_CLOSED_1M_BARS_AT_CAPTURE_ONLY"
                ):
                    raise CurrentRunRefused("FULL_UNIVERSE_HISTORY_REQUIRED")
                quotes = []
                for symbol in CAPTURE_UNIVERSE:
                    quote = await _stage(
                        "capture_quote:" + symbol,
                        lambda symbol=symbol: services.capture.fresh_quote(symbol),
                        services.usage_snapshot,
                        baseline,
                        records,
                    )
                    if quote.symbol != symbol:
                        raise CurrentRunRefused("QUOTE_SYMBOL_MISMATCH")
                    quotes.append(quote)
                quotes = tuple(quotes)
                macro_json = services.macro_context_factory(
                    config=config,
                    history=history,
                    text=text_snapshot,
                    quotes=quotes,
                    simulation_repository=services.simulation_repository,
                )
                if type(macro_json) is not str or not macro_json:
                    raise CurrentRunRefused("MACRO_CONTEXT_UNAVAILABLE")
                text_bus = _CollectingMemoryBus()
                text_service = TextScoutsService(
                    TextSettings(
                        _env_file=None,
                        service_name="kairos-current-plan-text",
                        bus_backend="memory",
                        enable_gdelt=False,
                        enable_rss=False,
                    ),
                    gateway=services.gateway,
                    bus=text_bus,
                    sources=[text_snapshot.text_source],
                )
                await _stage(
                    "text_scouts_poll_once",
                    text_service.poll_once,
                    services.usage_snapshot,
                    baseline,
                    records,
                )
                signal_received_ms = _now_ms()
                signals = tuple(text_bus.sentiments)
                macro = MacroStrategist(
                    services.gateway,
                    source="kairos-current-plan-macro",
                    allowed_strategy_ids=config.strategy_ids,
                )
                allocation = await _stage(
                    "macro_strategist_allocate",
                    lambda: macro.allocate(macro_json, trigger=StrategicTrigger.SCHEDULE),
                    services.usage_snapshot,
                    baseline,
                    records,
                )
                macro_received_ms = _now_ms()
                macro_capital_allowed = macro_allocation_allows_entry(allocation)
                macro_stage = next(
                    record for record in reversed(records) if record.name == "macro_strategist_allocate"
                )
                if allocation.rationale.startswith("defensive fallback:"):
                    raise CurrentRunRefused("MACRO_MODEL_FALLBACK")
                cut_inputs = await _run_cpu(
                    services.build_cut_inputs,
                    config=config,
                    history=history,
                    text_snapshot=text_snapshot,
                    quotes=quotes,
                    signals=signals,
                    allocation=allocation,
                    allocation_received_ms=macro_received_ms,
                    signal_received_ms=signal_received_ms,
                    quant_measurements_by_symbol=services.quant_measurements_by_symbol,
                    simulation_session=services.simulation_session,
                    tape_id=services.tape_id,
                    requested_quantities=services.requested_quantities,
                )
                if type(cut_inputs) is not CurrentCutInputs or (
                    cut_inputs.policy.session.source_set_sha256 != config.source_set_sha256
                    or cut_inputs.policy.session.model_config_sha256 != config.model_config_sha256
                    or any(cell.price.cut_ms != config.cut_ms for cell in cut_inputs.cells)
                ):
                    raise CurrentRunRefused("CUT_POLICY_OR_SOURCE_HASH_BINDING_MISMATCH")
                cells = _by_symbol(tuple((cell.price.symbol, cell) for cell in cut_inputs.cells), "cells")
                prompt_by_symbol = _by_symbol(cut_inputs.directional_payloads, "directional_payloads")
                text_by_symbol = {
                    symbol: tuple(signal for signal in signals if signal.topic.strip().upper() == symbol)
                    for symbol in UNIVERSE
                }
                quote_by_symbol = {quote.symbol: quote for quote in quotes}
                market_by_symbol = _by_symbol(cut_inputs.market_snapshots, "market_snapshots")
                quantity_by_symbol = _by_symbol(cut_inputs.requested_quantities, "requested_quantities")
                for symbol in UNIVERSE:
                    slot = {
                        "symbol": symbol,
                        "technical": "NOT_EVALUATED",
                        "context_proposal": "NOT_ATTEMPTED",
                        "selected_origin": None,
                        "reason": None,
                        "plan_sha256": None,
                    }
                    slot_results.append(slot)
                    if not macro_capital_allowed:
                        slot["reason"] = "MACRO_CAPITAL_BLOCKED"
                        slot["context_proposal"] = "MACRO_CAPITAL_BLOCKED"
                        sim_outcomes.append(
                            {"symbol": symbol, "state": "NO_PLAN", "reason": "MACRO_CAPITAL_BLOCKED"}
                        )
                        continue
                    bars = tuple(history.bars_by_symbol[symbol])
                    complex_decision = await _stage(
                        "evaluate_complex:" + symbol,
                        lambda bars=bars: _run_plan_fold(
                            fold_lock,
                            evaluate_complex,
                            bars,
                            prefix_start_ms=bars[0].open_time_ms,
                            cut_ms=config.cut_ms,
                        ),
                        services.usage_snapshot,
                        baseline,
                        records,
                    )
                    tech = complex_decision.candidate if complex_decision.defense == "NORMAL" else None
                    slot["technical"] = complex_decision.reason if tech is None else "CANDIDATE"
                    matching_signals = text_by_symbol[symbol]
                    if not matching_signals:
                        slot["reason"] = "NO_TEXT"
                        slot["context_proposal"] = "NO_TEXT"
                        sim_outcomes.append({"symbol": symbol, "state": "NO_PLAN", "reason": "NO_TEXT"})
                        continue
                    cell = cells[symbol]
                    if not cell.events:
                        slot["context_proposal"] = "NO_NATIVE_ELIGIBLE_EVENT"
                        context_candidate = None
                        context_reason = "NO_NATIVE_ELIGIBLE_EVENT"
                    else:
                        context_candidate = None
                        context_reason = "MODEL_NOT_ATTEMPTED"
                        direction_result = None
                        direction_assessment = None
                        direction_sha = None
                        try:
                            prompt = prompt_by_symbol[symbol]
                            result = await _stage(
                                "directional_creation:" + symbol,
                                lambda prompt=prompt: services.gateway.complete(
                                    system=_DIRECTION_SYSTEM,
                                    user=prompt,
                                    effort=ReasoningEffort.MEDIUM,
                                    workload=LLMWorkload.AGGREGATOR_NORMAL,
                                    schema=DirectionalAssessment,
                                ),
                                services.usage_snapshot,
                                baseline,
                                records,
                            )
                            if (
                                result.cached is not False
                                or result.provider != "openai"
                                or result.workload != LLMWorkload.AGGREGATOR_NORMAL.value
                                or result.attempt_started_at_ts_ms is None
                                or result.response_observed_at_ts_ms is None
                            ):
                                raise CurrentRunRefused("DIRECTIONAL_MODEL_PROVENANCE_INVALID")
                            direction_assessment = DirectionalAssessment.model_validate_json(result.content)
                            if direction_assessment != DirectionalAssessment.model_validate(
                                result.parsed.model_dump(mode="json")
                            ):
                                raise CurrentRunRefused("DIRECTIONAL_RESPONSE_PARSE_BINDING_CONFLICT")
                            permitted = dict(cut_inputs.permitted_evidence_ids)[symbol]
                            if not set(direction_assessment.evidence_ids) <= set(permitted):
                                raise CurrentRunRefused("DIRECTIONAL_EVIDENCE_OUTSIDE_CUT")
                            direction_result = result
                            direction_sha = hashlib.sha256(result.content.encode("utf-8")).hexdigest()
                            mapped = await _run_plan_fold(
                                fold_lock,
                                map_context_proposal,
                                direction_assessment.proposal,
                                bars,
                                cut_ms=config.cut_ms,
                                assessment_sha256=direction_sha,
                            )
                            context_candidate = mapped.candidate
                            context_reason = mapped.reason
                            slot["context_proposal"] = mapped.reason
                            creation_results.append(
                                {
                                    "symbol": symbol,
                                    "provider": result.provider,
                                    "model": result.resolved_model,
                                    "reservation_id": result.budget_reservation_id,
                                    "proposal": direction_assessment.proposal,
                                    "response_sha256": direction_sha,
                                    "mapped_state": mapped.state,
                                    "mapped_reason": mapped.reason,
                                    "candidate_sha256": _canonical_sha(mapped.candidate)
                                    if mapped.candidate is not None
                                    else None,
                                }
                            )
                        except Exception as exc:
                            if _is_budget_refusal(exc):
                                raise
                            context_reason = _safe_exception(exc)
                            slot["context_proposal"] = context_reason
                            creation_results.append(
                                {"symbol": symbol, "proposal": "UNKNOWN", "safe_failure": context_reason}
                            )
                    selected, origin, reason = None, None, "NO_PLAN"
                    if tech is not None and context_candidate is not None:
                        if tech.side != context_candidate.side:
                            reason = "OPPOSITE_TECHNICAL_CONTEXT_ABSTAIN"
                        else:
                            selected, origin, reason = tech, "TECHNICAL", "SAME_SIDE_TECHNICAL_PRIORITY"
                    elif tech is not None:
                        selected, origin, reason = tech, "TECHNICAL", "TECHNICAL_ONLY"
                    elif context_candidate is not None:
                        selected, origin, reason = context_candidate, "CONTEXT_PROPOSAL", "CONTEXT_ONLY"
                    if selected is None:
                        slot["reason"] = reason if reason != "NO_PLAN" else context_reason
                        sim_outcomes.append({"symbol": symbol, "state": "NO_PLAN", "reason": slot["reason"]})
                        continue
                    slot["selected_origin"] = origin
                    slot["reason"] = reason
                    created_ms = _now_ms()
                    assessment_sha = None
                    if origin == "CONTEXT_PROPOSAL":
                        assessment_sha = direction_sha
                    try:
                        context = _planning_context(
                            symbol=symbol,
                            history=history,
                            signals=matching_signals,
                            macro_allocation=allocation,
                            macro_received_ms=macro_received_ms,
                            signal_received_ms=signal_received_ms,
                            quote=quote_by_symbol[symbol],
                            market_snapshot=market_by_symbol[symbol],
                        )
                        plan, original_evidence = _plan_for_candidate(
                            template=selected,
                            origin=origin,
                            complex_decision=complex_decision,
                            cell=cell,
                            context=context,
                            config=config,
                            quote=quote_by_symbol[symbol],
                            directional_sha256=assessment_sha,
                            directional_result=direction_result if origin == "CONTEXT_PROPOSAL" else None,
                            directional_assessment=(
                                direction_assessment if origin == "CONTEXT_PROPOSAL" else None
                            ),
                            directional_input_json=(
                                prompt_by_symbol[symbol] if origin == "CONTEXT_PROPOSAL" else None
                            ),
                            created_at_ms=created_ms,
                        )
                    except Exception as exc:
                        slot["reason"] = _safe_exception(exc)
                        sim_outcomes.append({"symbol": symbol, "state": "NO_PLAN", "reason": slot["reason"]})
                        continue
                    plan_path = _plan_artifact_path(config.output_path.parent, "plan", symbol, plan.sha256)
                    await _run_cpu(
                        write_create_only,
                        plan_path,
                        plan.payload(),
                    )
                    evidence_path = _plan_artifact_path(
                        config.output_path.parent, "original-evidence", symbol, plan.sha256
                    )
                    await _run_cpu(write_create_only, evidence_path, _receipt_value(original_evidence))
                    slot["plan_sha256"] = plan.sha256
                    candidate_receipts.append(
                        {
                            "symbol": symbol,
                            "origin": origin,
                            "candidate_sha256": _canonical_sha(selected),
                            "plan_sha256": plan.sha256,
                            "plan_path": str(plan_path),
                            "original_evidence_path": str(evidence_path),
                        }
                    )
                    review_task = asyncio.create_task(
                        _review_plan_then_observe(
                            plan=plan,
                            plan_path=plan_path,
                            config=config,
                            services=services,
                            history=history,
                            symbol=symbol,
                            baseline=baseline,
                            records=records,
                            deadline_ms=min(
                                config.cut_ms + _MAX_RUN_OBSERVATION_MS,
                                deferred.plan.ends_at_ms,
                            ),
                            risk_lock=risk_lock,
                            fold_lock=fold_lock,
                            aggregate_open_risk=aggregate_open_risk,
                            requested_quantity=quantity_by_symbol[symbol],
                        )
                    )
                    observer_tasks.append((symbol, review_task))

                gathered = await _gather_observers(observer_tasks)
                for (symbol, _task), result in zip(observer_tasks, gathered, strict=True):
                    if isinstance(result, BaseException):
                        status = {"state": "NO_ENTRY", "reason": _safe_exception(result)}
                    else:
                        status = result
                    sim_outcomes.append({"symbol": symbol, **status})
                    if status.get("authorization") is not None:
                        receipt["entry_authorizations"].append(status.pop("authorization"))
                    if status.get("plan_review") is not None:
                        plan_reviews.append(status.pop("plan_review"))
                elapsed = time.monotonic() - began
                calls, reserved, actual, attempts = _usage_delta(baseline, await services.usage_snapshot())
                receipt.update(
                    result="COMPLETED",
                    macro_capital_allowed=macro_capital_allowed,
                    completion_semantics="PLAN_REVIEW_AND_DEFERRED_REQUESTS_ONLY_NO_RISK_OR_FILL_CREDIT",
                    elapsed_seconds=round(elapsed, 3),
                    stages=[asdict(item) for item in records],
                    provider_attempts=[asdict(item) for item in attempts],
                    budget_delta={"calls": calls, "reserved_microusd": reserved, "actual_microusd": actual},
                    history_coverage=history.coverage_scope,
                    history_bar_counts={symbol: len(history.bars_by_symbol[symbol]) for symbol in UNIVERSE},
                    quote_receipt_sha256s={quote.symbol: quote.raw_sha256 for quote in quotes},
                    text_snapshot_sha256=text_snapshot.sha256,
                    text_poll={
                        "signals_published": len(signals),
                        "captured_item_count": len(text_snapshot.news_items),
                        "coverage_scope": text_snapshot.coverage_scope,
                    },
                    macro_allocation=allocation.model_dump(mode="json"),
                    macro_allocation_origin="MODEL_OUTPUT",
                    macro_provider_reservation_ids=list(macro_stage.provider_reservation_ids),
                    selected_plans=candidate_receipts,
                    initial_open_risk=asdict(initial_open),
                    final_aggregate_open_risk_microusd=aggregate_open_risk[0],
                    local_cost_limit_microusd=MAX_LOCAL_COST_MICROUSD,
                    provider_call_limit=MAX_PROVIDER_CALLS,
                )
    except BaseException as exc:
        if observer_tasks:
            await asyncio.gather(*(task for _, task in observer_tasks), return_exceptions=True)
        receipt.update(
            result="FAILED_CLOSED",
            safe_failure=_safe_exception(exc),
            elapsed_seconds=round(time.monotonic() - began, 3),
            stages=[asdict(item) for item in records],
        )
        try:
            final_usage = await services.usage_snapshot()
            _, reserved, actual, attempts = _usage_delta(baseline, final_usage)
            receipt["provider_attempts"] = [asdict(item) for item in attempts]
            receipt["budget_delta"] = {"reserved_microusd": reserved, "actual_microusd": actual}
        except BaseException:
            receipt["provider_ledger_status"] = "UNAVAILABLE_AFTER_FAILURE"
        try:
            await _run_cpu(write_create_only, config.output_path, receipt)
        except BaseException:
            pass
        return receipt
    receipt["stages"] = [asdict(item) for item in records]
    await _run_cpu(write_create_only, config.output_path, receipt)
    return receipt


async def _review_plan_then_observe(
    *,
    plan: CurrentPlan,
    plan_path: Path,
    config: CurrentRunConfig,
    services: CurrentRunServices,
    history,
    symbol: str,
    baseline: UsageSnapshot,
    records: list[StageRecord],
    deadline_ms: int,
    risk_lock: asyncio.Lock,
    fold_lock: asyncio.Lock,
    aggregate_open_risk: list[int],
    requested_quantity: float,
) -> dict:
    review_path = _plan_artifact_path(config.output_path.parent, "review", symbol, plan.sha256)
    review = None
    try:
        review = await _stage(
            "plan_llm_review:" + symbol,
            lambda: review_current_plan(plan, services.gateway, clock_ms=_now_ms),
            services.usage_snapshot,
            baseline,
            records,
        )
        await _run_cpu(write_create_only, review_path, review.payload())
    except Exception as exc:
        if _is_budget_refusal(exc):
            raise
        try:
            await _run_cpu(
                write_create_only,
                review_path,
                {"schema": "kairos.current-plan-review-failure.v1", "safe_failure": _safe_exception(exc)},
            )
        except Exception:
            pass
        return {
            "state": "NO_ENTRY",
            "reason": _safe_exception(exc),
            "plan_review": {
                "symbol": symbol,
                "plan_sha256": plan.sha256,
                "state": "FAILED_CLOSED",
                "safe_failure": _safe_exception(exc),
            },
        }
    review_receipt = {
        "symbol": symbol,
        "plan_sha256": plan.sha256,
        "review_sha256": review.sha256,
        "decision": review.decision.value,
        "priority": review.priority,
        "reason_codes": list(review.reason_codes),
        "requested_at_ms": review.requested_at_ms,
        "response_observed_at_ms": review.response_observed_at_ms,
        "completed_at_ms": review.completed_at_ms,
        "model_provenance": review.model_provenance.model_dump(mode="json"),
        "review_path": str(review_path),
    }
    outcome = await _stage(
        "post_review_confirmation_and_request:" + symbol,
        lambda: _observe_confirm_and_authorize(
            plan=plan,
            review=review,
            history=history,
            symbol=symbol,
            cut_ms=config.cut_ms,
            observation_source=services.observation_source,
            risk_frame_source=services.risk_frame_source,
            fold_lock=fold_lock,
            deferred_requests=services.deferred_requests,
            artifact_root=config.output_path.parent,
            code_sha256=config.source_set_sha256,
            config_sha256=config.model_config_sha256,
            run_deadline_ms=deadline_ms,
            risk_lock=risk_lock,
            aggregate_open_risk=aggregate_open_risk,
            requested_quantity=requested_quantity,
        ),
        services.usage_snapshot,
        baseline,
        records,
    )
    outcome["plan_review"] = review_receipt
    if outcome.get("authorization_sha256"):
        outcome["authorization"] = {
            "symbol": symbol,
            "plan_sha256": plan.sha256,
            "authorization_sha256": outcome["authorization_sha256"],
            "actual_live_risk_or_execution": False,
            "state": "DETERMINISTIC_AUTHORIZED_DEFERRED_REQUEST_ONLY",
        }
    return outcome
