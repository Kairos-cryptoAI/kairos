"""Observed decisions followed by explicitly later, sealed native-SIM replay.

There is no provider, clock backdating, venue client or growing-tape execution
here. Actual decision-request and journal clocks are distinct from logical
Risk/controller replay clocks. All original expiries and native policies stay.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import re
import time
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from kairos_core.contracts import (
    CandidateReviewV1,
    ObservedSimStrategyIntentV2,
    RecordedTopNBookFrameV2,
    SimulationAssumptionsV1,
    SimulationSessionV1,
    SimulationStrategyRefV1,
)
from kairos_execution.simulation.controller import SimulationExecutionController
from kairos_strategy.runtime import candle_to_closed_bar

from .current_capture import FreshQuoteSnapshot, _canonical_bytes, _write_receipt
from .current_chain import decide_sim

MODE = "OFFLINE_NATIVE_SIM_REPLAY_FROM_OBSERVED_DECISIONS"
SYMBOLS = ("BNBUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")


def _now_ms():
    return time.time_ns() // 1_000_000


def _sha(value):
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class DeferredSimulationPlan:
    tape_id: str
    assumptions: SimulationAssumptionsV1
    strategy_allowlist: tuple[SimulationStrategyRefV1, ...]
    started_at_ms: int
    ends_at_ms: int
    source_set_sha256: str
    model_config_sha256: str

    def __post_init__(self):
        if re.fullmatch(r"current-native-[0-9a-f]{32}", self.tape_id) is None:
            raise ValueError("FRESH_DECLARED_DEFERRED_TAPE_ID_REQUIRED")
        if (
            type(self.started_at_ms) is not int
            or type(self.ends_at_ms) is not int
            or not 0 <= self.started_at_ms < self.ends_at_ms <= self.started_at_ms + 900_000
        ):
            raise ValueError("BOUNDED_DEFERRED_CAPTURE_WINDOW_REQUIRED")
        if type(self.assumptions) is not SimulationAssumptionsV1:
            raise ValueError("EXACT_NATIVE_REPLAY_ASSUMPTIONS_REQUIRED")
        SimulationAssumptionsV1.model_validate(self.assumptions.model_dump(mode="python"), strict=True)
        if type(self.strategy_allowlist) is not tuple or not self.strategy_allowlist:
            raise ValueError("EXPLICIT_DEFERRED_STRATEGY_ALLOWLIST_REQUIRED")
        for item in self.strategy_allowlist:
            if type(item) is not SimulationStrategyRefV1:
                raise ValueError("EXACT_DEFERRED_STRATEGY_REFERENCE_REQUIRED")
            SimulationStrategyRefV1.model_validate(item.model_dump(mode="python"), strict=True)
        for value in (self.source_set_sha256, self.model_config_sha256):
            if re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("EXACT_DEFERRED_SOURCE_IDENTITIES_REQUIRED")

    def payload(self):
        return {
            "mode": MODE,
            "tape_id": self.tape_id,
            "assumptions": self.assumptions.model_dump(mode="json"),
            "strategy_allowlist": [item.model_dump(mode="json") for item in self.strategy_allowlist],
            "started_at_ms": self.started_at_ms,
            "ends_at_ms": self.ends_at_ms,
            "source_set_sha256": self.source_set_sha256,
            "model_config_sha256": self.model_config_sha256,
            "actual_live_risk_or_execution": False,
        }

    @property
    def sha256(self):
        return _sha(self.payload())

    def bind_seal(self, seal):
        if seal.tape_id != self.tape_id:
            raise ValueError("DEFERRED_SEAL_TAPE_MISMATCH")
        return SimulationSessionV1(
            source="kairos-current-observed-decisions-native-replay",
            tape_id=self.tape_id,
            tape_sha256=seal.tape_sha256,
            assumptions=self.assumptions,
            strategy_allowlist=self.strategy_allowlist,
            started_at_ms=self.started_at_ms,
            ends_at_ms=self.ends_at_ms,
        )


class ObservedSimulationRequests:
    """Create-only evidence sink, not an admission or an order dispatcher."""

    def __init__(self, plan: DeferredSimulationPlan, output: Path):
        if type(plan) is not DeferredSimulationPlan:
            raise ValueError("EXPLICIT_DEFERRED_PLAN_REQUIRED")
        plan.__post_init__()
        output.mkdir(exist_ok=False)
        self.plan, self.output = plan, output
        self.requests: list[dict] = []
        self._bodies: list[bytes] = []
        self._durable_bodies: list[bytes] = []
        self._entry_authorizations: dict[int, object] = {}
        _write_receipt(output, "plan.json", {**plan.payload(), "plan_sha256": plan.sha256})
        self._plan_body = (output / "plan.json").read_bytes()

    async def record(
        self, *, intent, review, quote, frame, request_ms, requested_quantity, entry_authorization=None
    ):
        if type(intent) is not ObservedSimStrategyIntentV2 or type(review) is not CandidateReviewV1:
            raise ValueError("EXACT_OBSERVED_SIM_INTENT_AND_REVIEW_REQUIRED")
        checked = ObservedSimStrategyIntentV2.model_validate(intent.model_dump(mode="python"), strict=True)
        if (
            checked.provenance.strategy_code_sha256 != self.plan.source_set_sha256
            or checked.provenance.config_sha256 != self.plan.model_config_sha256
        ):
            raise ValueError("DEFERRED_REQUEST_SOURCE_IDENTITY_CONFLICT")
        if review.intent.canonical_intent_bytes() != checked.canonical_intent_bytes():
            raise ValueError("ORIGINAL_DEFERRED_REVIEW_IDENTITY_CONFLICT")
        if (intent.strategy_id, intent.strategy_revision) not in {
            (item.strategy_id, item.strategy_revision) for item in self.plan.strategy_allowlist
        }:
            raise ValueError("DEFERRED_INTENT_NOT_ALLOWLISTED")
        if (
            type(request_ms) is not int
            or not self.plan.started_at_ms <= request_ms <= self.plan.ends_at_ms
            or request_ms < review.reviewed_at_ms
            or request_ms > _now_ms()
            or len(self.requests) >= 5
        ):
            raise ValueError("ORIGINAL_BOUNDED_DEFERRED_REQUEST_CLOCK_REQUIRED")
        if type(quote) is not FreshQuoteSnapshot or (
            quote.entry_quote.sha256 != dict(intent.metadata).get("entry_quote_sha256")
        ):
            raise ValueError("EXACT_ORIGINAL_DEFERRED_QUOTE_REQUIRED")
        if frame is not None and (
            type(frame) is not RecordedTopNBookFrameV2
            or frame.tape_id != self.plan.tape_id
            or frame.symbol != intent.symbol
            or frame.persisted_at_ms > request_ms
        ):
            raise ValueError("CAUSAL_ORIGINAL_DEFERRED_BOOK_REQUIRED")
        if type(requested_quantity) not in {float, int} or not 0 < requested_quantity < float("inf"):
            raise ValueError("POSITIVE_DEFERRED_QUANTITY_REQUIRED")
        if any(row["intent"]["intent_id"] == intent.intent_id for row in self.requests):
            raise ValueError("DEFERRED_INTENT_ALREADY_RECORDED")
        authorization_payload = _validate_plan_entry_authorization(intent, review, entry_authorization)
        payload = {
            "schema": "kairos.current-observed-sim-request.v1",
            "mode": MODE,
            "sequence": len(self.requests) + 1,
            "plan_sha256": self.plan.sha256,
            "observed_request_ms": request_ms,
            "intent": intent.model_dump(mode="json"),
            "review": review.model_dump(mode="json"),
            "quote": {
                "entry_quote_sha256": quote.entry_quote.sha256,
                "raw_sha256": quote.raw_sha256,
                "event_ms": quote.entry_quote.event_ms,
                "received_ms": quote.received_ms,
                "persisted_ms": quote.captured_ms,
            },
            "frame": frame.model_dump(mode="json") if frame is not None else None,
            "selected_frame_sequence_watermark": frame.tape_sequence if frame is not None else None,
            "requested_quantity": requested_quantity,
            "risk_evaluated_live": False,
            "actual_venue_order": False,
        }
        if authorization_payload is not None:
            payload["entry_authorization"] = authorization_payload
            payload["entry_authorization_sha256"] = _sha(authorization_payload)
        path = _write_receipt(self.output, f"request-{payload['sequence']:02d}.json", payload)
        durable_ms = _now_ms()
        if durable_ms < request_ms:
            raise ValueError("DEFERRED_JOURNAL_CLOCK_REGRESSION")
        body = path.read_bytes()
        durable_path = _write_receipt(
            self.output,
            f"request-{payload['sequence']:02d}.durable.json",
            {"request_sha256": hashlib.sha256(body).hexdigest(), "journal_durable_ms": durable_ms},
        )
        self.requests.append(payload)
        self._bodies.append(body)
        self._durable_bodies.append(durable_path.read_bytes())
        if entry_authorization is not None:
            self._entry_authorizations[payload["sequence"]] = entry_authorization
        return {"sequence": payload["sequence"], "state": "OBSERVED_REQUEST_NOT_RISK_ADMISSION"}

    def validate(self):
        if (self.output / "plan.json").read_bytes() != self._plan_body:
            raise ValueError("DEFERRED_PLAN_MUTATION_OR_REPLACEMENT")
        for index, (row, original, durable_body) in enumerate(
            zip(self.requests, self._bodies, self._durable_bodies, strict=True), 1
        ):
            if (
                (self.output / f"request-{index:02d}.json").read_bytes() != original
                or _canonical_bytes(row) + b"\n" != original
                or row["plan_sha256"] != self.plan.sha256
            ):
                raise ValueError("DEFERRED_REQUEST_MUTATION_OR_REPLACEMENT")
            durable_path = self.output / f"request-{index:02d}.durable.json"
            if not durable_path.is_file() or durable_path.read_bytes() != durable_body:
                raise ValueError("DEFERRED_DURABILITY_RECEIPT_MUTATION_OR_REMOVAL")
            durable = json.loads(durable_body)
            if (
                durable.get("request_sha256") != hashlib.sha256(original).hexdigest()
                or type(durable.get("journal_durable_ms")) is not int
                or not row["observed_request_ms"] <= durable["journal_durable_ms"] <= _now_ms()
            ):
                raise ValueError("DEFERRED_DURABILITY_RECEIPT_CHRONOLOGY_CONFLICT")
            # A deterministic entry authorization in CURRENT v3 is not a final
            # LLM review. Reconstruct its complete retained plan/model/trigger
            # proof before any native Risk evaluation, not merely its label.
            intent = ObservedSimStrategyIntentV2.model_validate(row["intent"])
            review = CandidateReviewV1.model_validate(row["review"])
            certificate = _validate_plan_entry_authorization(
                intent, review, self._entry_authorizations.get(index)
            )
            if certificate is not None and (
                row.get("entry_authorization") != certificate
                or row.get("entry_authorization_sha256") != _sha(certificate)
            ):
                raise ValueError("DEFERRED_PLAN_ENTRY_AUTHORIZATION_CONFLICT")
            if certificate is None and ("entry_authorization" in row or "entry_authorization_sha256" in row):
                raise ValueError("UNDECLARED_DEFERRED_PLAN_ENTRY_AUTHORIZATION")
        return tuple(self.requests)


def _validate_plan_entry_authorization(intent, review, authorization):
    from .current_plan import STRATEGY_ID, CurrentEntryAuthorization, revalidate_authorization

    if intent.strategy_id != STRATEGY_ID:
        if authorization is not None:
            raise ValueError("PLAN_ENTRY_AUTHORIZATION_FOR_DIFFERENT_STRATEGY")
        return None
    if type(authorization) is not CurrentEntryAuthorization:
        raise ValueError("CURRENT_PLAN_ENTRY_AUTHORIZATION_REQUIRED")
    revalidate_authorization(authorization)
    if (
        authorization.intent.canonical_intent_bytes() != intent.canonical_intent_bytes()
        or authorization.native_review.model_dump(mode="json") != review.model_dump(mode="json")
    ):
        raise ValueError("CURRENT_PLAN_ENTRY_AUTHORIZATION_BINDING_CONFLICT")
    return authorization.payload()


async def import_complete_tape(repository, *, tape_id, history, observed_bars, frames):
    """Import full original facts before the one seal; never reopen an old tape."""
    counts, all_bars = {}, {}
    if set(history.bars_by_symbol) != set(SYMBOLS) or any(
        len(history.bars_by_symbol[symbol]) != 3_240 for symbol in SYMBOLS
    ):
        raise ValueError("COMPLETE_FIVE_SYMBOL_HISTORY_BEFORE_SEAL_REQUIRED")
    for symbol in SYMBOLS:
        merged = {}
        candles = list(history.bars_by_symbol[symbol]) + [item.candle for item in observed_bars[symbol]]
        for candle in candles:
            bar = candle_to_closed_bar(candle)
            existing = merged.get(bar.open_time_ms)
            if existing is not None and existing.bar_sha256 != bar.bar_sha256:
                raise ValueError("CONFLICTING_REST_AND_OBSERVED_CLOSED_BAR")
            merged[bar.open_time_ms] = bar
        ordered = tuple(merged[key] for key in sorted(merged))
        if any(
            right.open_time_ms != left.close_time_ms + 1
            for left, right in zip(ordered, ordered[1:], strict=False)
        ):
            raise ValueError("OBSERVED_NATIVE_BAR_PROVENANCE_GAP")
        for bar in ordered:
            await repository.record_closed_bar(tape_id, bar)
        counts[symbol], all_bars[symbol] = len(ordered), ordered
    for index, frame in enumerate(frames, 1):
        if (
            type(frame) is not RecordedTopNBookFrameV2
            or frame.tape_id != tape_id
            or frame.tape_sequence != index
            or frame.previous_frame_sha256 != (frames[index - 2].frame_sha256 if index > 1 else None)
        ):
            raise ValueError("ORIGINAL_CONTINUOUS_NATIVE_TAPE_REQUIRED")
        await repository.record_book_frame(frame)
    return counts, all_bars


def _validate_observed_selection(item, frames, latest):
    """A later same-ms frame cannot conceal an earlier omitted durable frame."""
    logical_ms, symbol = item["observed_request_ms"], item["intent"]["symbol"]
    eligible = [frame for frame in frames if frame.symbol == symbol and frame.persisted_at_ms <= logical_ms]
    sealed_latest = max(
        eligible, key=lambda frame: (frame.persisted_at_ms, frame.tape_sequence), default=None
    )
    if (latest.frame_sha256 if latest else None) != (sealed_latest.frame_sha256 if sealed_latest else None):
        raise ValueError("SEALED_NATIVE_BOOK_ROSTER_CONFLICT")
    original = RecordedTopNBookFrameV2.model_validate(item["frame"]) if item["frame"] else None
    watermark = item["selected_frame_sequence_watermark"]
    if original is None:
        if watermark is not None or eligible:
            raise ValueError("OBSERVED_REQUEST_BOOK_SELECTION_CONFLICT")
        return None
    if type(watermark) is not int or watermark != original.tape_sequence:
        raise ValueError("OBSERVED_REQUEST_BOOK_WATERMARK_CONFLICT")
    prefix = [frame for frame in eligible if frame.tape_sequence <= watermark]
    selected = max(prefix, key=lambda frame: (frame.persisted_at_ms, frame.tape_sequence), default=None)
    if (
        selected is None
        or selected.model_dump(mode="json") != original.model_dump(mode="json")
        or any(frame.persisted_at_ms < logical_ms for frame in eligible if frame.tape_sequence > watermark)
    ):
        raise ValueError("OBSERVED_REQUEST_BOOK_SELECTION_CONFLICT")
    return original


async def replay_observed_requests(repository, requests: ObservedSimulationRequests, *, seal, bars, frames):
    """Later deterministic native replay, never an earlier actual Risk action."""
    wall_started = _now_ms()
    rows = requests.validate()
    session = requests.plan.bind_seal(seal)
    for index, frame in enumerate(frames, 1):
        if (
            type(frame) is not RecordedTopNBookFrameV2
            or frame.tape_id != session.tape_id
            or frame.tape_sequence != index
            or frame.previous_frame_sha256 != (frames[index - 2].frame_sha256 if index > 1 else None)
        ):
            raise ValueError("ORIGINAL_CONTINUOUS_REPLAY_ROSTER_REQUIRED")
    if not await repository.verify_tape(session.tape_id):
        raise ValueError("NATIVE_REPLAY_TAPE_VERIFICATION_FAILED")
    await repository.create_session(session)
    controller = SimulationExecutionController(repository, source="kairos-current-observed-native-replay")
    events, outcomes, trades, serial = [], {}, {}, 0
    for row in rows:
        heapq.heappush(events, (row["observed_request_ms"], 0, serial, "REQUEST", row))
        serial += 1
    # Exit close+1 and fixed arrival latency are the existing native SIM model,
    # not observed live stop/target instruction times. No future bar is invented.
    for symbol in SYMBOLS:
        for bar in bars[symbol]:
            due = bar.close_time_ms + 1 + session.assumptions.latency_ms
            if session.started_at_ms <= due <= session.ends_at_ms:
                heapq.heappush(events, (due, 2, serial, "BAR", bar))
                serial += 1
    conservative_open_risk = 0
    while events:
        logical_ms, _priority, _serial, kind, item = heapq.heappop(events)
        if kind == "REQUEST":
            intent = ObservedSimStrategyIntentV2.model_validate(item["intent"])
            review = CandidateReviewV1.model_validate(item["review"])
            latest = await repository.load_latest_book_frame(
                session.tape_id, intent.symbol, as_of_ms=logical_ms
            )
            frame = _validate_observed_selection(item, frames, latest)
            decision, admission = decide_sim(
                session=session,
                final_intent=intent,
                final_review=review,
                selected_book_frame=frame,
                decided_at_ms=logical_ms,
                requested_quantity=item["requested_quantity"],
            )
            requested_risk = int(
                (
                    Decimal(str(item["requested_quantity"]))
                    * abs(Decimal(str(intent.reference_price)) - Decimal(str(intent.exit_plan.stop_price)))
                    * 1_000_000
                ).to_integral_value(rounding=ROUND_CEILING)
            )
            if requested_risk > 25_000_000 or conservative_open_risk + requested_risk > 100_000_000:
                raise ValueError("OBSERVED_REPLAY_ACCOUNT_RISK_CEILING_EXCEEDED")
            await repository.record_risk_decision(decision)
            output = {
                "symbol": intent.symbol,
                "observed_request_sequence": item["sequence"],
                "observed_request_ms": logical_ms,
                "replay_risk_approved": decision.approved,
                "risk_rejection_reasons": list(decision.rejection_reasons),
                "risk_decision_id": decision.decision_id,
                "admission_id": admission.admission_id if admission else None,
                "execution_state": None,
                "fill_receipt": None,
                "closing_receipt": None,
            }
            if "entry_authorization_sha256" in item:
                output["entry_authorization_sha256"] = item["entry_authorization_sha256"]
                output["entry_review_semantics"] = "DETERMINISTIC_AFTER_RETAINED_PLAN_MODEL_REVIEW"
            outcomes[item["sequence"]] = output
            if admission is not None:
                conservative_open_risk += requested_risk
                arrival_ms = logical_ms + session.assumptions.latency_ms
                if arrival_ms > session.ends_at_ms:
                    output["execution_state"] = "NOT_SUBMITTED_ARRIVAL_OUTSIDE_ORIGINAL_WINDOW"
                    continue
                trade = await controller.start_trade(admission, created_at_ms=logical_ms)
                output["trade_id"] = trade.trade_id
                trades[item["sequence"]] = trade
                heapq.heappush(
                    events,
                    (arrival_ms, 1, serial, "ENTRY", item["sequence"]),
                )
                serial += 1
        elif kind == "ENTRY":
            result = await controller.submit_entry(trades[item], as_of_ms=logical_ms)
            outcomes[item]["execution_state"] = result.lifecycle_state
            outcomes[item]["fill_receipt"] = (
                result.receipt.model_dump(mode="json") if result.receipt else None
            )
        else:
            for identity, trade in trades.items():
                if trade.symbol != item.symbol or outcomes[identity]["execution_state"] != "ACTIVE":
                    continue
                if item.close_time_ms + 1 <= trade.created_at_ms + session.assumptions.latency_ms:
                    # This candle was already closed when the entry arrived.
                    # Its pre-entry extrema cannot trigger a new position's exit.
                    continue
                result = await controller.process_closed_bar(trade, item, as_of_ms=logical_ms)
                if result is not None:
                    outcomes[identity]["execution_state"] = result.lifecycle_state
                    if result.lifecycle_state == "FLAT" and result.receipt is not None:
                        outcomes[identity]["closing_receipt"] = result.receipt.model_dump(mode="json")
    incomplete = [
        {
            "observed_request_sequence": identity,
            "trade_id": row.get("trade_id"),
            "execution_state": row["execution_state"],
        }
        for identity, row in outcomes.items()
        if row["replay_risk_approved"]
        and (
            row["execution_state"] is None
            or row["execution_state"] in {"ACTIVE", "PENDING", "UNRESOLVED"}
            or row["execution_state"] == "NOT_SUBMITTED_ARRIVAL_OUTSIDE_ORIGINAL_WINDOW"
        )
    ]
    result = {
        "schema": "kairos.current-observed-native-replay.v1",
        "mode": MODE,
        "plan_sha256": requests.plan.sha256,
        "session_id": session.session_id,
        "tape_sha256": session.tape_sha256,
        "actual_replay_started_ms": wall_started,
        "actual_replay_completed_ms": _now_ms(),
        "sim_outcomes": list(outcomes.values()),
        "request_count": len(rows),
        "source_end_watermark": {
            "original_frame_count": len(frames),
            "last_frame_sha256": frames[-1].frame_sha256 if frames else None,
            "last_frame_persisted_ms": frames[-1].persisted_at_ms if frames else None,
            "last_observed_bar_close_ms_by_symbol": {
                symbol: max((bar.close_time_ms for bar in bars[symbol]), default=None) for symbol in SYMBOLS
            },
        },
        "window_completion": "INSUFFICIENT_FUTURE_OBSERVATION"
        if incomplete
        else "NO_UNRESOLVED_REPLAY_TRADES",
        "incomplete_lifecycles": incomplete,
        "full_trade_lifecycle_verified": bool(outcomes)
        and not incomplete
        and any(
            row["execution_state"] == "FLAT" and row["closing_receipt"] is not None
            for row in outcomes.values()
        ),
        "actual_live_risk_or_execution": False,
        "exit_trigger_assumption": "NATIVE_CLOSED_BAR_CLOSE_PLUS_ONE_MS_NOT_OBSERVED_LIVE_COMMAND",
        "open_risk_accounting": "CONSERVATIVE_NO_RELEASE_BOUND_NOT_REAL_ACCOUNT_RISK",
        "readiness_promotion": False,
    }
    _write_receipt(requests.output, "native-replay-result.json", result)
    return result
