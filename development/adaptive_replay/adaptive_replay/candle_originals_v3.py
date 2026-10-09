"""Bounded typed candle originals for prospective V3 SIM input consistency.

These records retain a normalized ``Candle`` plus caller-supplied receipt
clocks. They do not authenticate a source, prove raw REST bytes or exchange
finality, or qualify as a complete historical feed. In particular, this is
not an accepted full-history source.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal

from kairos_strategy.candles import Candle
from kairos_strategy.provenance import candle_payload

from .historical_context import digest
from .inputs import UNIVERSE
from .scenarios import MINUTE, ScenarioEvidence, _bar

EVIDENCE_KINDS = {"TEST_FIXTURE", "CALLER_ATTESTED_POINT_IN_TIME"}
MAX_RECORDS = 10_000


@dataclass(frozen=True)
class RetainedCandleV3:
    """One exact normalized 1m candle and its internally consistent receipt."""

    candle: Candle
    evidence: ScenarioEvidence
    available_at_ms: int
    evidence_kind: str

    def __post_init__(self) -> None:
        if type(self.candle) is not Candle or type(self.evidence) is not ScenarioEvidence:
            raise ValueError("exact typed candle and scenario evidence required")
        # Re-run both frozen contracts; frozen dataclasses can still be forged
        # through low-level mutation or supplied by unusual callers.
        _bar(self.candle)
        Candle(**asdict(self.candle))
        ScenarioEvidence(**asdict(self.evidence))
        if (
            self.candle.symbol not in UNIVERSE
            or self.candle.timeframe != "1m"
            or type(self.candle.open_time_ms) is not int
            or self.candle.open_time_ms < 0
            or self.candle.open_time_ms % MINUTE
            or type(self.candle.close_time_ms) is not int
            or self.candle.close_time_ms != self.candle.open_time_ms + MINUTE - 1
        ):
            raise ValueError("exact complete closed 1m candle required")
        if type(self.available_at_ms) is not int or self.available_at_ms < 0:
            raise ValueError("exact nonnegative availability clock required")
        if self.evidence_kind not in EVIDENCE_KINDS:
            raise ValueError("explicit retained-candle evidence class required")
        bar_sha256 = digest(candle_payload(self.candle))
        if (
            self.evidence.kind != "MARKET"
            or self.evidence.symbol != self.candle.symbol
            or self.evidence.event_ms != self.candle.close_time_ms
            or self.evidence.payload_sha256 != bar_sha256
            or self.evidence.captured_ms < self.candle.close_time_ms + 1
            or self.available_at_ms < self.evidence.captured_ms
        ):
            raise ValueError("market evidence must bind the exact closed candle and causal clocks")


@dataclass(frozen=True)
class CandleOriginalsV3:
    """Canonical bounded set of unchanged candle originals and receipt clocks."""

    records: tuple[RetainedCandleV3, ...]

    def __post_init__(self) -> None:
        if type(self.records) is not tuple or not 1 <= len(self.records) <= MAX_RECORDS:
            raise ValueError("nonempty bounded immutable candle originals required")
        if any(type(record) is not RetainedCandleV3 for record in self.records):
            raise ValueError("exact retained candle records required")
        for record in self.records:
            RetainedCandleV3(record.candle, record.evidence, record.available_at_ms, record.evidence_kind)
        if (
            tuple(sorted(self.records, key=lambda r: (r.candle.symbol, r.candle.open_time_ms)))
            != self.records
        ):
            raise ValueError("candle originals must use canonical symbol/open-time order")
        identities = [(r.candle.symbol, r.candle.open_time_ms) for r in self.records]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate or conflicting candle original identity")
        if len({r.evidence_kind for r in self.records}) != 1:
            raise ValueError("fixture and caller-attested candle originals cannot be mixed")

    @property
    def sha256(self) -> str:
        """Canonical digest of every full retained candle and receipt field."""
        return digest([asdict(record) for record in self.records])

    def find(
        self,
        candle: Candle,
        evidence: ScenarioEvidence,
        at_ms: int,
    ) -> RetainedCandleV3:
        """Return an exact original only when its unchanged receipt is ready."""
        if type(candle) is not Candle or type(evidence) is not ScenarioEvidence:
            raise ValueError("exact candle and evidence membership query required")
        _bar(candle)
        ScenarioEvidence(**asdict(evidence))
        if type(at_ms) is not int or at_ms < 0:
            raise ValueError("exact nonnegative query clock required")
        for record in self.records:
            if digest(asdict(record.candle)) == digest(asdict(candle)) and record.evidence == evidence:
                if record.available_at_ms <= at_ms:
                    return record
                raise ValueError("retained candle is not yet available at requested clock")
        raise ValueError("exact candle and evidence are not retained originals")

    def validate_binding(self, binding: object) -> None:
        """Check every candle input in a complete SIM binding against originals.

        This is deliberately a validator, not a filter or rebuilder: book and
        funding inputs remain untouched in the caller's complete binding.
        """
        # Local import keeps this support module independent of continuous_sim
        # initialization and avoids a module cycle.
        from .continuous_sim import ClosedCandleInput, TapeBinding

        if type(binding) is not TapeBinding:
            raise ValueError("exact complete tape binding required")
        if binding.evidence_kind != self.records[0].evidence_kind:
            raise ValueError("binding and retained originals evidence classes differ")
        for item in binding.inputs:
            value = item.value
            if type(value) is not ClosedCandleInput:
                continue
            match = next(
                (
                    record
                    for record in self.records
                    if record.candle.symbol == value.symbol
                    and record.candle.open_time_ms == value.open_at_ms
                    and record.candle.close_time_ms == value.close_at_ms
                ),
                None,
            )
            if match is None:
                raise ValueError("binding candle input has no retained original")
            candle, evidence = match.candle, match.evidence
            if (
                match.evidence_kind != value.evidence_kind
                or match.available_at_ms != value.available_at_ms
                or Decimal(str(candle.close)) != value.close
                or evidence.source_id != value.source_id
                or evidence.payload_sha256 != value.source_payload_sha256
            ):
                raise ValueError("binding candle differs from full retained original receipt")
