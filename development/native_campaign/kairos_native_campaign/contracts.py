"""Hash-bound, SIM-only receipts for native research composition.

These contracts bind existing decisions. They do not call a provider, create a
simulation command, reserve risk, or confer paper/live authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from typing import Annotated, Literal, Self

from kairos_core import CandidateReviewV1, DecisionContextV1, SimulationRiskDecisionV1, canonical_sha256
from kairos_core.contracts.base import (
    StrictKairosMessage,
    StrictValueModel,
    canonical_json_bytes,
    datetime_from_unix_ms,
)
from kairos_persistence.research_campaign import ResearchReviewReceiptV1
from kairos_persistence.research_evidence import ResearchLLMAttemptStartV1
from pydantic import Field, StrictInt, StrictStr, model_validator

_SHA = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
_ID = Annotated[StrictStr, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
_MS = Annotated[StrictInt, Field(ge=0, le=253_402_300_799_999)]
_CANONICAL_NONNEGATIVE_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")


class NativeSimSizingSnapshotV1(StrictValueModel):
    """Exact scheduler artifact; explicitly not account/portfolio admission."""

    version: Literal["native-hypothetical-stop-sizing.v1"]
    equity_usd: Annotated[StrictStr, Field(min_length=1, max_length=64)]
    existing_open_risk_usd: Annotated[StrictStr, Field(min_length=1, max_length=64)]
    maximum_trade_risk_fraction: Literal["0.0025"]
    maximum_open_risk_fraction: Literal["0.01"]
    authority: Literal["SIM_FIXTURE_ONLY_NOT_ACCOUNT_ADMISSION"]

    @model_validator(mode="after")
    def exact_decimal_inputs(self) -> Self:
        for name, positive in (("equity_usd", True), ("existing_open_risk_usd", False)):
            text = getattr(self, name)
            try:
                amount = Decimal(text)
            except (ValueError, ArithmeticError) as exc:
                raise ValueError("sizing snapshot amounts must be canonical finite decimal strings") from exc
            if (
                not _CANONICAL_NONNEGATIVE_DECIMAL.fullmatch(text)
                or not amount.is_finite()
                or amount < 0
                or (positive and amount == 0)
            ):
                raise ValueError("sizing snapshot amounts must be canonical finite decimal strings")
        return self


def native_review_risk_message_id(campaign_id: str, sample_id: str) -> str:
    """Stable identity independent of response or decision bytes."""
    return canonical_sha256(
        {
            "domain": "kairos.native-review-risk.message.v1",
            "campaign_id": campaign_id,
            "sample_id": sample_id,
        }
    )


def native_review_risk_composition_sha256(
    *,
    campaign_id: str,
    sample_id: str,
    scheduler_sha256: str,
    plan_receipt_sha256: str,
    bundle_receipt_sha256: str,
    evaluation_receipt_sha256: str,
    start: ResearchLLMAttemptStartV1 | None,
    decision_context: DecisionContextV1,
    candidate_review: CandidateReviewV1,
    sim_risk_decision: SimulationRiskDecisionV1,
    normalized_review: ResearchReviewReceiptV1 | None,
    sizing_sha256: str,
) -> str:
    """Hash the exact set of typed inputs that make up one SIM composition."""
    return canonical_sha256(
        {
            "domain": "kairos.native-review-risk.composition.v1",
            "campaign_id": campaign_id,
            "sample_id": sample_id,
            "scheduler_sha256": scheduler_sha256,
            "plan_receipt_sha256": plan_receipt_sha256,
            "bundle_receipt_sha256": bundle_receipt_sha256,
            "evaluation_receipt_sha256": evaluation_receipt_sha256,
            "start_receipt_sha256": None if start is None else start.receipt_sha256,
            "decision_context": decision_context.model_dump(mode="json"),
            "candidate_review": candidate_review.model_dump(mode="json"),
            "sim_risk_decision": sim_risk_decision.model_dump(mode="json"),
            "normalized_review_receipt_sha256": (
                None if normalized_review is None else normalized_review.receipt_sha256
            ),
            "sizing_sha256": sizing_sha256,
        }
    )


class NativeReviewRiskReceiptV1(StrictKairosMessage):
    """Immutable binding/recovery record for one native candidate's SIM review."""

    schema_version: Literal["1.0"] = "1.0"
    contract_version: Literal["native-review-risk.v1"] = "native-review-risk.v1"
    authority: Literal["SIM_RESEARCH_ONLY"] = "SIM_RESEARCH_ONLY"
    source: Literal["native-campaign-composition"] = "native-campaign-composition"
    message_id: _SHA | None = None
    campaign_id: _ID
    sample_id: _ID
    scheduler_sha256: _SHA
    plan_receipt_sha256: _SHA
    bundle_receipt_sha256: _SHA
    evaluation_receipt_sha256: _SHA
    start: ResearchLLMAttemptStartV1 | None = None
    decision_context: DecisionContextV1
    candidate_review: CandidateReviewV1
    sim_risk_decision: SimulationRiskDecisionV1
    normalized_review: ResearchReviewReceiptV1 | None = None
    sizing_snapshot: NativeSimSizingSnapshotV1
    sizing_sha256: _SHA
    composition_sha256: _SHA
    observed_at_ts_ms: _MS
    receipt_sha256: _SHA | None = None

    def identity_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"receipt_sha256"})

    @model_validator(mode="after")
    def exact_native_lineage_and_hashes(self) -> Self:
        # Round-trip nested models so unchecked object.__setattr__/model_copy
        # mutations cannot be smuggled into a durable receipt.
        for model in (
            (DecisionContextV1, self.decision_context),
            (CandidateReviewV1, self.candidate_review),
            (SimulationRiskDecisionV1, self.sim_risk_decision),
            (NativeSimSizingSnapshotV1, self.sizing_snapshot),
        ):
            model[0].model_validate_json(model[1].model_dump_json())
        if self.start is not None:
            ResearchLLMAttemptStartV1.model_validate_json(self.start.model_dump_json())
        if self.normalized_review is not None:
            ResearchReviewReceiptV1.model_validate_json(self.normalized_review.model_dump_json())

        expected_message_id = native_review_risk_message_id(self.campaign_id, self.sample_id)
        if self.message_id is not None and self.message_id != expected_message_id:
            raise ValueError("native review/risk message ID must be stable for campaign/sample")
        object.__setattr__(self, "message_id", expected_message_id)
        if self.correlation_id is None:
            object.__setattr__(self, "correlation_id", expected_message_id)
        expected_produced_at = datetime_from_unix_ms(self.observed_at_ts_ms)
        if "produced_at" not in self.model_fields_set:
            object.__setattr__(self, "produced_at", expected_produced_at)
        elif (
            self.produced_at.tzinfo is None
            or self.produced_at.utcoffset() is None
            or int(self.produced_at.timestamp() * 1_000) != self.observed_at_ts_ms
        ):
            raise ValueError("native receipt produced_at must equal its actual observed millisecond clock")

        review = self.candidate_review
        context = self.decision_context
        decision = self.sim_risk_decision
        if (
            context.intent_id != review.intent.intent_id
            or context.route_id != review.route.route_id
            or context.intent_identity_json != canonical_json_bytes(review.intent.identity_payload()).decode()
            or context.route_identity_json != canonical_json_bytes(review.route.identity_payload()).decode()
            or decision.intent.intent_id != review.intent.intent_id
            or decision.review.review_id != review.review_id
            or canonical_sha256(decision.review.model_dump(mode="json"))
            != canonical_sha256(review.model_dump(mode="json"))
            or canonical_sha256(decision.intent.model_dump(mode="json"))
            != canonical_sha256(review.intent.model_dump(mode="json"))
        ):
            raise ValueError(
                "review, route, decision context, SIM risk and intent lineage must match exactly"
            )
        if not (review.reviewed_at_ms <= decision.decided_at_ms <= self.observed_at_ts_ms):
            raise ValueError("review, SIM risk decision and receipt clocks must be causally ordered")
        equity = Decimal(self.sizing_snapshot.equity_usd)
        open_risk = Decimal(self.sizing_snapshot.existing_open_risk_usd)
        risk_cap = min(equity * Decimal("0.0025"), max(Decimal(0), equity * Decimal("0.01") - open_risk))
        if decision.approved:
            stop = Decimal(str(review.intent.exit_plan.stop_price))
            worst_entry = Decimal(str(decision.price_cap))
            if Decimal(str(decision.quantity)) * abs(worst_entry - stop) > risk_cap:
                raise ValueError("approved SIM quantity exceeds the bound hypothetical risk caps")
        elif decision.quantity != 0:
            raise ValueError("rejected SIM decision cannot carry a nonzero quantity")

        if review.reviewer == "LLM":
            if self.start is None or self.normalized_review is None or review.model_provenance is None:
                raise ValueError("LLM review requires its exact START and normalized model receipt")
        elif self.normalized_review is not None:
            raise ValueError("deterministic review cannot be paired with a normalized model review")
        if (
            review.reviewer == "DETERMINISTIC"
            and review.decision.value == "DEFER"
            and review.model_provenance
        ):
            raise ValueError("deterministic DEFER cannot claim model provenance")
        if self.start is not None:
            if (
                self.start.campaign_id != self.campaign_id
                or self.start.sample_id != self.sample_id
                or self.start.arm_id != "strategy-review"
                or self.start.symbol != review.intent.symbol
                or not (
                    review.intent.decision_ts_ms <= self.start.market_as_of_ts_ms <= review.route.routed_at_ms
                )
                or self.start.attempt_started_at_ts_ms > self.observed_at_ts_ms
            ):
                raise ValueError("attempt START differs from the native review scope or observed clock")
        if self.normalized_review is not None:
            start = self.start
            normalized = self.normalized_review
            provenance = review.model_provenance
            assert start is not None and provenance is not None
            if (
                normalized.campaign_id != self.campaign_id
                or normalized.sample_id != self.sample_id
                or normalized.attempt_id != start.attempt_id
                or normalized.start_receipt_sha256 != start.receipt_sha256
                or normalized.bundle_receipt_sha256 != self.bundle_receipt_sha256
                or normalized.evaluation_receipt_sha256 != self.evaluation_receipt_sha256
                or normalized.output.action != review.decision.value
                or not (
                    start.attempt_started_at_ts_ms
                    <= normalized.observed_at_ts_ms
                    <= review.reviewed_at_ms
                    <= decision.decided_at_ms
                    <= self.observed_at_ts_ms
                )
                or normalized.requested_model != start.requested_model
                or normalized.prompt_sha256 != start.prompt_sha256
                or normalized.resolved_model != provenance.model
                or normalized.request_id != provenance.request_id
                or normalized.response_sha256 != provenance.response_sha256
                or start.provider != provenance.provider
                or start.budget_reservation_id != provenance.budget_reservation_id
            ):
                raise ValueError("normalized review/model provenance differs from START or native lineage")

        expected_sizing_sha256 = canonical_sha256(self.sizing_snapshot.model_dump(mode="json"))
        if self.sizing_sha256 != expected_sizing_sha256:
            raise ValueError("SIM sizing snapshot hash differs from its exact canonical content")
        expected_composition_sha256 = native_review_risk_composition_sha256(
            campaign_id=self.campaign_id,
            sample_id=self.sample_id,
            scheduler_sha256=self.scheduler_sha256,
            plan_receipt_sha256=self.plan_receipt_sha256,
            bundle_receipt_sha256=self.bundle_receipt_sha256,
            evaluation_receipt_sha256=self.evaluation_receipt_sha256,
            start=self.start,
            decision_context=self.decision_context,
            candidate_review=self.candidate_review,
            sim_risk_decision=self.sim_risk_decision,
            normalized_review=self.normalized_review,
            sizing_sha256=self.sizing_sha256,
        )
        if self.composition_sha256 != expected_composition_sha256:
            raise ValueError("native composition hash differs from its exact typed receipt members")
        expected_receipt_sha256 = canonical_sha256(self.identity_payload())
        if self.receipt_sha256 is not None and self.receipt_sha256 != expected_receipt_sha256:
            raise ValueError("native review/risk receipt hash differs from its canonical content")
        object.__setattr__(self, "receipt_sha256", expected_receipt_sha256)
        return self


def canonical_receipt_json(receipt: NativeReviewRiskReceiptV1) -> tuple[dict[str, object], str, str]:
    """Revalidate and return the audit payload, stable JSON and payload digest."""
    if type(receipt) is not NativeReviewRiskReceiptV1:
        raise TypeError("native journal requires the exact NativeReviewRiskReceiptV1 type")
    payload = receipt.model_dump(mode="json")
    validated = NativeReviewRiskReceiptV1.model_validate_json(json.dumps(payload, allow_nan=False))
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if validated.model_dump(mode="json") != payload:
        raise ValueError("native review/risk payload changed during canonical validation")
    return payload, canonical, digest
