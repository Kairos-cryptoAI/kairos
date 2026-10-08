"""Additive, provided simulated-fill checks; never an executor or risk approval.

The original journal is freshly audited, not replaced by a caller-made receipt.
Raw quote bytes are supplied separately and remain caller-attested. A successful
check proves neither a venue fill nor continuous tick-path/protection coverage.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from kairos_core.enums import Side
from kairos_strategy.adaptive.config import DEFAULT_CONFIG
from kairos_strategy.adaptive.logic import _planning_economics
from kairos_strategy.models import ExitPlan, SleeveIntent

from .historical_context import _clock, _name, _sha, digest
from .hypothesis_journal import HypothesisJournal, JournalSeal
from .quote_capture import BboCapture, admit_capture

SCHEMA = "kairos.development.simulated-fill-feasibility.v1"
ASSUMPTIONS = {
    "price": "LONG_AT_OR_ABOVE_ASK_SHORT_AT_OR_BELOW_BID",
    "capacity": "ONE_SUPPLIED_FILL_WITHIN_SAME_CAPTURE_TOP_SIDE_BASE_QUANTITY",
    "cost": "UNCHANGED_PLANNING_CONFIG_NOT_MEASURED_EXECUTION_COST",
    "source": "EXACT_BYTES_AND_CALLER_ATTESTED_CLOCKS_NOT_AUTHENTICATION",
    "path": "NO_CONTINUOUS_TICK_PATH_OR_PROTECTIVE_ORDER_PROOF",
    "authority": "NONE_NO_SIZING_POSITION_ORDER_OR_FILL_LEDGER",
}


def _positive(value: float) -> None:
    try:
        valid = type(value) in {int, float} and math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("finite positive simulated price/quantity required")


@dataclass(frozen=True)
class SimulatedFill:
    """One hypothetical fill supplied by a caller, not an exchange acknowledgement."""

    arm_id: str
    parent_id: str
    intent_id: str
    symbol: str
    side: Side
    price: float
    quantity: float
    filled_ms: int
    protection_sha256: str

    def __post_init__(self) -> None:
        _name(self.arm_id)
        _name(self.symbol)
        for value in (self.parent_id, self.intent_id, self.protection_sha256):
            _sha(value)
        _clock(self.filled_ms)
        for value in (self.price, self.quantity):
            _positive(value)
        if type(self.side) is not Side or self.side is Side.FLAT:
            raise ValueError("typed directional simulated fill required")


@dataclass(frozen=True)
class FillAssessment:
    schema_id: str
    state: str
    reason: str
    coverage: str
    journal_seal_sha256: str
    journal_head_sha256: str
    issue_chain_sha256: str | None
    candidate_sha256: str
    fill_sha256: str
    issue_capture_sha256: str | None
    execution_capture_sha256: str | None
    assumptions_sha256: str
    risk_authority: str = "NONE"

    @property
    def sha256(self) -> str:
        return digest(asdict(self))


def assess_journal_simulated_fill(
    *,
    journal_path: Path,
    seal: JournalSeal,
    candidate: SleeveIntent,
    fill: SimulatedFill,
    issue_capture: BboCapture | None,
    execution_capture: BboCapture | None,
) -> FillAssessment:
    """Check a fresh journal-issued candidate against one hypothetical fill.

    No journal append, retries, dependency adoption, position or economic result.
    Repeated checks are deterministic diagnostics, NOT multiple fill permission.
    Missing evidence remains unavailable. Integrity/schema conflicts raise.
    """
    if type(candidate) is not SleeveIntent or type(fill) is not SimulatedFill:
        raise ValueError("typed candidate and simulated fill required")
    SimulatedFill(**asdict(fill))
    # Reconstruct the native contract and identity; matching metadata alone is
    # insufficient, and an object whose computed ID was tampered with is invalid.
    values = {f.name: getattr(candidate, f.name) for f in fields(candidate) if f.init}
    values["exit_plan"] = ExitPlan(**asdict(candidate.exit_plan))
    rebuilt = SleeveIntent(**values)
    if asdict(rebuilt) != asdict(candidate):
        raise ValueError("candidate identity or exact native contract changed")
    for capture in (issue_capture, execution_capture):
        if capture is not None:
            if type(capture) is not BboCapture:
                raise ValueError("typed exact-byte quote capture required")
            BboCapture(**asdict(capture))

    # open/snapshot revalidate original seal, chronology, every typed fold and
    # installed source bytes. Caller-created snapshots/receipts cannot enter.
    snapshot = HypothesisJournal.open(journal_path, seal).snapshot()
    groups = [
        group
        for group in snapshot.hypotheses
        if group.arm_id == fill.arm_id and group.plan.template.intent_id == fill.parent_id
    ]
    issued = []
    if len(groups) == 1:
        issued = [receipt for receipt in groups[0].receipts if receipt.evaluation.candidate is not None]
    issue = issued[0] if len(issued) == 1 else None

    def result(state: str, reason: str, coverage: str = "AVAILABLE") -> FillAssessment:
        return FillAssessment(
            SCHEMA,
            state,
            reason,
            coverage,
            snapshot.seal_sha256,
            snapshot.head_sha256,
            None if issue is None else issue.chain_sha256,
            digest(asdict(candidate)),
            digest(asdict(fill)),
            None if issue_capture is None else issue_capture.sha256,
            None if execution_capture is None else execution_capture.sha256,
            digest({"schema": SCHEMA, "mechanics": ASSUMPTIONS, "config": asdict(DEFAULT_CONFIG)}),
        )

    if issue is None or asdict(issue.evaluation.candidate) != asdict(candidate):
        return result("REFUSED", "NOT_EXACT_JOURNAL_ISSUED_CANDIDATE")
    group = groups[0]
    plan = group.plan
    if (
        fill.intent_id != candidate.intent_id
        or fill.symbol != candidate.symbol
        or fill.side is not candidate.side
        or fill.protection_sha256 != plan.protection_sha256
        or candidate.exit_plan != plan.template.exit_plan
    ):
        return result("REFUSED", "FILL_IDENTITY_OR_ORIGINAL_PROTECTION_CONFLICT")
    if not candidate.entry_eligible_ts_ms <= fill.filled_ms <= candidate.entry_expires_ts_ms:
        return result("REFUSED", "ORIGINAL_ENTRY_DEADLINE_CONFLICT")
    if issue_capture is None or execution_capture is None:
        return result("UNAVAILABLE", "EXACT_BYTE_QUOTE_CAPTURE_MISSING", "UNAVAILABLE")
    observation = next(o for o in group.observations if o.observation_id == issue.evaluation.observation_id)
    try:
        original_quote = admit_capture(
            plan,
            issue_capture,
            at_ms=candidate.entry_eligible_ts_ms,
            after_ms=observation.market.candle.close_time_ms + 1,
        )
        quote = admit_capture(
            plan,
            execution_capture,
            at_ms=fill.filled_ms,
            after_ms=candidate.entry_eligible_ts_ms,
        )
    except ValueError:
        return result("UNAVAILABLE", "QUOTE_SOURCE_CLOCK_OR_FRESHNESS_CONFLICT", "UNAVAILABLE")
    if observation.quote is None or original_quote.sha256 != observation.quote.sha256:
        return result("UNAVAILABLE", "ISSUE_CAPTURE_DIFFERS_FROM_RETAINED_QUOTE", "UNAVAILABLE")

    long = candidate.side is Side.LONG
    exits = plan.template.exit_plan
    stop, target = exits.stop_price, exits.target_price
    activation = exits.trailing_activation_price
    executable = quote.ask if long else quote.bid
    capacity = execution_capture.ask_quantity if long else execution_capture.bid_quantity
    if quote.bid <= stop if long else quote.ask >= stop:
        return result("REFUSED", "EXECUTION_EXIT_SIDE_ALREADY_BREACHES_STOP")
    if not (
        executable > plan.template.reference_price if long else executable < plan.template.reference_price
    ):
        return result("REFUSED", "ORIGINAL_CONFIRMATION_NOT_HELD_AT_EXECUTION_QUOTE")
    if not (stop < fill.price < target if long else target < fill.price < stop):
        return result("REFUSED", "FILL_OUTSIDE_UNCHANGED_STOP_TARGET")
    if activation is not None and not (fill.price < activation if long else fill.price > activation):
        return result("REFUSED", "FILL_PASSED_UNCHANGED_TRAILING_ACTIVATION")
    if fill.quantity > capacity:
        return result("REFUSED", "FILL_EXCEEDS_SAME_SNAPSHOT_TOP_SIDE_CAPACITY")
    if fill.price < executable if long else fill.price > executable:
        return result("REFUSED", "FAVORABLE_FILL_NOT_SUPPORTED_BY_CONSERVATIVE_BBO_MODEL")
    spread_bps = (quote.ask - quote.bid) / executable * 10_000
    slippage_bps = abs(fill.price - executable) / executable * 10_000
    if (
        not math.isfinite(spread_bps)
        or not math.isfinite(slippage_bps)
        or spread_bps > DEFAULT_CONFIG.spread_bps
        or slippage_bps > DEFAULT_CONFIG.slippage_bps_per_side
    ):
        return result("REFUSED", "FILL_EXCEEDS_UNCHANGED_SPREAD_OR_SLIPPAGE_ASSUMPTION")
    frozen_atr = dict(candidate.metadata).get("frozen_atr15")
    if frozen_atr is not None:
        try:
            atr = float(frozen_atr)
        except ValueError:
            return result("REFUSED", "INVALID_FROZEN_VOLATILITY_AT_FILL")
        if not math.isfinite(atr) or atr <= 0:
            return result("REFUSED", "INVALID_FROZEN_VOLATILITY_AT_FILL")
        if not (
            DEFAULT_CONFIG.minimum_stop_atr * atr
            <= abs(fill.price - stop)
            <= DEFAULT_CONFIG.maximum_stop_atr * atr
        ):
            return result("REFUSED", "FILL_STOP_OUTSIDE_ORIGINAL_FROZEN_ATR_BOUNDS")
    risk_bps, _, cost, net_rr = _planning_economics(fill.price, stop, target, DEFAULT_CONFIG)
    if not all(math.isfinite(value) for value in (risk_bps, cost, net_rr)) or (
        risk_bps > DEFAULT_CONFIG.maximum_stop_bps
        or cost > DEFAULT_CONFIG.maximum_cost_stop_fraction * risk_bps
        or net_rr < DEFAULT_CONFIG.minimum_net_reward_risk
    ):
        return result("REFUSED", "FILL_INSUFFICIENT_UNCHANGED_PLANNING_COST_HEADROOM")
    return result("SIMULATED_CHECK_ONLY", "PROVIDED_FILL_COMPATIBLE_NOT_EXECUTION_OR_RISK_APPROVAL")
