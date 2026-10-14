"""Caller-attested historical source bindings for a prospective four-arm slot.

This companion binds exact archive/source references to one frozen symbol/cut
and retains distinct source clocks. It deliberately has no ADMITTED state:
hash consistency and ``as_of_context`` consistency are not source authentication.
No provider, network, database, runtime, or economics capability is exposed.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from .historical_context import (
    HistoricalArchive,
    SourceRequirement,
    _clock,
    as_of_context,
    canonical,
    digest,
)
from .inputs import UNIVERSE

SCHEMA = "kairos.research.historical-four-arm-slot-binding.v1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
TECHNICAL_STATES = {
    "PARENT",
    "QUIET",
    "HARD_VETO",
    "CONFLICT",
    "CRASH_DEFENSE",
    "UNCERTAIN",
    "UNAVAILABLE",
}
NO_CALL_REASON = "REQUIRED_SOURCE_UNAVAILABLE"
ADMISSION_NO_CALL_REASON = "SOURCE_ADMISSION_NOT_ESTABLISHED"
SOURCE_KINDS = {"MARKET_SNAPSHOT", "NEWS", "MACRO"}
MAX_BINDING_BYTES = 4 * 1024 * 1024
_BINDING_FIELDS = {
    "schema",
    "binding_role",
    "sample_id",
    "window_id",
    "window_start_ms",
    "window_end_exclusive_ms",
    "symbol",
    "cut_ms",
    "schedule_sha256",
    "protocol_sha256",
    "technical_state",
    "technical_reason",
    "source_archive_sha256",
    "required_sources",
    "source_receipts",
    "coverage_refs",
    "version_refs",
    "source_consistency_ready",
    "source_denial_detail",
    "context_sha256",
    "selected_versions",
    "context_eligibility",
    "context_no_call_reason",
    "proposal_state",
    "source_admission_status",
    "provenance_authenticity_verified",
    "provider_dispatch_authorized",
    "runtime_authority",
    "economic_result_authorized",
}


def _sha(value: object, name: str) -> None:
    if type(value) is not str or SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _identifier(value: object, name: str) -> None:
    if type(value) is not str or not value or len(value) > 128 or value.strip() != value:
        raise ValueError(f"bounded {name} required")


@dataclass(frozen=True)
class SlotSourceReceiptClockV1:
    """A reference to a source receipt, not a claim that the source was admitted.

    ``source_as_of_ms`` is the source/producer's asserted event/publication
    clock. ``observed_received_at_ms`` is the actual local receive clock when
    one was retained; it remains ``None`` when unknown. ``captured_at_ms`` is
    the receipt-package capture clock and must not be substituted for either.
    """

    sample_id: str
    window_id: str
    symbol: str
    cut_ms: int
    source_kind: str
    source_name: str
    source_receipt_sha256: str
    source_as_of_ms: int | None
    observed_received_at_ms: int | None
    captured_at_ms: int

    def validate(self) -> None:
        _identifier(self.sample_id, "sample identity")
        _identifier(self.window_id, "window identity")
        if self.symbol not in UNIVERSE:
            raise ValueError("source receipt symbol outside fixed universe")
        _clock(self.cut_ms)
        if self.source_kind not in SOURCE_KINDS:
            raise ValueError("unsupported source receipt kind")
        _identifier(self.source_name, "source name")
        _sha(self.source_receipt_sha256, "source receipt hash")
        for name in ("source_as_of_ms", "observed_received_at_ms"):
            value = getattr(self, name)
            if value is not None:
                _clock(value)
        _clock(self.captured_at_ms)
        if self.source_as_of_ms is not None and self.source_as_of_ms > self.captured_at_ms:
            raise ValueError("source/event clock cannot follow actual receipt capture clock")
        if self.observed_received_at_ms is not None and self.observed_received_at_ms > self.captured_at_ms:
            raise ValueError("actual receive clock cannot follow receipt capture clock")


@dataclass(frozen=True)
class SlotRequiredSourceV1:
    kind: str
    source_name: str
    required: bool
    lookback_ms: int
    maximum_age_ms: int

    def validate(self) -> None:
        if self.kind not in {"NEWS", "MACRO"}:
            raise ValueError("historical context requirement must be NEWS or MACRO")
        _identifier(self.source_name, "required source name")
        if type(self.required) is not bool or not self.required:
            raise ValueError("four-arm slot binding requires explicit required sources")
        _clock(self.lookback_ms)
        _clock(self.maximum_age_ms)
        if self.lookback_ms <= 0 or self.maximum_age_ms <= 0:
            raise ValueError("positive source lookback and maximum age required")


@dataclass(frozen=True)
class SlotCoverageRefV1:
    source_name: str
    kind: str
    symbol: str
    start_ms: int
    end_ms: int
    status: str
    proof_kind: str
    proof_sha256: str | None
    captured_ms: int
    coverage_sha256: str

    def validate(self) -> None:
        _identifier(self.source_name, "coverage source name")
        if self.kind not in {"NEWS", "MACRO"} or self.symbol not in UNIVERSE:
            raise ValueError("coverage reference source/symbol outside fixed contract")
        _clock(self.start_ms)
        _clock(self.end_ms)
        _clock(self.captured_ms)
        if self.end_ms <= self.start_ms or self.status not in {"COMPLETE", "UNKNOWN"}:
            raise ValueError("coverage reference has invalid interval/status")
        if self.proof_kind not in {"CONTEMPORANEOUS_LOCAL", "ARCHIVE_VERSION", "TEST_FIXTURE"}:
            raise ValueError("coverage reference has invalid proof kind")
        if self.proof_sha256 is not None:
            _sha(self.proof_sha256, "coverage proof hash")
        _sha(self.coverage_sha256, "coverage receipt hash")


@dataclass(frozen=True)
class SlotVersionRefV1:
    record_id: str
    document_id: str
    source_name: str
    kind: str
    symbol: str
    raw_content_sha256: str
    published_lower_ms: int
    published_upper_ms: int
    version_available_ms: int | None
    captured_ms: int
    proof_kind: str
    proof_sha256: str | None
    event_ms: int | None
    realized_ms: int | None
    version_sha256: str

    def validate(self) -> None:
        for name, value in (
            ("record identity", self.record_id),
            ("document identity", self.document_id),
            ("version source name", self.source_name),
        ):
            _identifier(value, name)
        if self.kind not in {"NEWS", "MACRO"}:
            raise ValueError("version reference kind must be NEWS or MACRO")
        if self.symbol not in UNIVERSE:
            raise ValueError("version reference symbol outside fixed universe")
        for name in ("raw_content_sha256", "version_sha256"):
            _sha(getattr(self, name), name)
        for name in ("published_lower_ms", "published_upper_ms", "captured_ms"):
            _clock(getattr(self, name))
        for name in ("version_available_ms", "event_ms", "realized_ms"):
            value = getattr(self, name)
            if value is not None:
                _clock(value)
        if self.proof_kind not in {
            "CONTEMPORANEOUS_LOCAL",
            "ARCHIVE_VERSION",
            "PUBLICATION_ONLY",
            "TEST_FIXTURE",
        }:
            raise ValueError("version reference has invalid proof kind")
        if self.proof_sha256 is not None:
            _sha(self.proof_sha256, "version proof hash")


@dataclass(frozen=True)
class SlotSelectedVersionV1:
    """Identity receipt for a version selected by the historical as-of policy."""

    kind: str
    source_name: str
    document_id: str
    record_id: str
    version_sha256: str
    version_available_ms: int

    def validate(self) -> None:
        if self.kind not in {"NEWS", "MACRO"}:
            raise ValueError("selected version kind must be NEWS or MACRO")
        for name, value in (
            ("selected source name", self.source_name),
            ("selected document identity", self.document_id),
            ("selected record identity", self.record_id),
        ):
            _identifier(value, name)
        _sha(self.version_sha256, "selected version hash")
        _clock(self.version_available_ms)


@dataclass(frozen=True)
class HistoricalFourArmSlotBindingV1:
    """Immutable audit binding for one symbol/cut; not a routing bridge.

    This schema has no positive admission state. Even when archive parsing and
    ``as_of_context`` are consistent, independent source admission is unproven.
    """

    sample_id: str
    window_id: str
    window_start_ms: int
    window_end_exclusive_ms: int
    symbol: str
    cut_ms: int
    schedule_sha256: str
    protocol_sha256: str
    technical_state: str
    technical_reason: str
    source_archive_sha256: str
    required_sources: tuple[SlotRequiredSourceV1, ...]
    source_receipts: tuple[SlotSourceReceiptClockV1, ...]
    coverage_refs: tuple[SlotCoverageRefV1, ...]
    version_refs: tuple[SlotVersionRefV1, ...]
    source_consistency_ready: bool
    source_denial_detail: str
    context_sha256: str
    selected_versions: tuple[SlotSelectedVersionV1, ...]

    def validate(self) -> None:
        _identifier(self.sample_id, "sample identity")
        _identifier(self.window_id, "window identity")
        _clock(self.window_start_ms)
        _clock(self.window_end_exclusive_ms)
        _clock(self.cut_ms)
        if self.window_end_exclusive_ms <= self.window_start_ms:
            raise ValueError("nonempty frozen window required")
        if not self.window_start_ms <= self.cut_ms < self.window_end_exclusive_ms:
            raise ValueError("slot cut falls outside its exact frozen window")
        if self.cut_ms % 300_000:
            raise ValueError("four-arm symbol/cut slot must be five-minute aligned")
        if self.symbol not in UNIVERSE:
            raise ValueError("slot symbol outside fixed universe")
        _sha(self.schedule_sha256, "schedule digest")
        _sha(self.protocol_sha256, "protocol digest")
        _sha(self.source_archive_sha256, "source archive digest")
        if self.technical_state not in TECHNICAL_STATES:
            raise ValueError("unknown original technical slot state")
        if (
            type(self.technical_reason) is not str
            or not self.technical_reason
            or len(self.technical_reason) > 256
        ):
            raise ValueError("original technical reason must be retained explicitly")
        if type(self.required_sources) is not tuple or not 0 < len(self.required_sources) <= 20:
            raise ValueError("immutable required NEWS/MACRO roster required")
        if type(self.source_receipts) is not tuple or not 0 < len(self.source_receipts) <= 16:
            raise ValueError("immutable source receipt references required")
        if (
            type(self.coverage_refs) is not tuple
            or len(self.coverage_refs) > 1_000
            or type(self.version_refs) is not tuple
            or len(self.version_refs) > 2_000
        ):
            raise ValueError("immutable coverage/version reference tuples required")
        for source in self.required_sources:
            if type(source) is not SlotRequiredSourceV1:
                raise ValueError("typed required-source reference required")
            source.validate()
        requirements = {(s.kind, s.source_name) for s in self.required_sources}
        if len(requirements) != len(self.required_sources):
            raise ValueError("duplicate required-source pair")
        expected_sources = tuple(sorted(self.required_sources, key=lambda r: (r.kind, r.source_name)))
        if self.required_sources != expected_sources:
            raise ValueError("required-source roster must be canonically sorted")
        if not {"NEWS", "MACRO"} <= {kind for kind, _ in requirements}:
            raise ValueError("at least one required NEWS and MACRO source is mandatory")
        for receipt in self.source_receipts:
            if type(receipt) is not SlotSourceReceiptClockV1:
                raise ValueError("typed source receipt reference required")
            receipt.validate()
            if (
                receipt.sample_id,
                receipt.window_id,
                receipt.symbol,
                receipt.cut_ms,
            ) != (self.sample_id, self.window_id, self.symbol, self.cut_ms):
                raise ValueError("raw source receipt reference differs from frozen sample/symbol/cut")
            if (
                receipt.source_kind != "MARKET_SNAPSHOT"
                and (
                    receipt.source_kind,
                    receipt.source_name,
                )
                not in requirements
            ):
                raise ValueError("raw context receipt outside frozen required-source roster")
        market_receipts = [r for r in self.source_receipts if r.source_kind == "MARKET_SNAPSHOT"]
        if len(market_receipts) != 1:
            raise ValueError("exactly one mandatory market snapshot receipt required")
        expected_pairs = requirements | {
            (r.source_kind, r.source_name) for r in self.source_receipts if r.source_kind == "MARKET_SNAPSHOT"
        }
        observed_pairs = {(r.source_kind, r.source_name) for r in self.source_receipts}
        if observed_pairs != expected_pairs or len(observed_pairs) != len(self.source_receipts):
            raise ValueError("exact market and complete required-source receipt roster required")
        if self.source_receipts != tuple(
            sorted(
                self.source_receipts,
                key=lambda r: (r.source_kind, r.source_name, r.source_receipt_sha256),
            )
        ):
            raise ValueError("source receipt references must be canonically sorted")
        window_ids = {r.window_id for r in self.source_receipts}
        if window_ids != {self.window_id}:
            raise ValueError("source receipt references disagree on frozen window identity")
        for ref in self.coverage_refs:
            if type(ref) is not SlotCoverageRefV1:
                raise ValueError("typed coverage receipt reference required")
            ref.validate()
            if (ref.kind, ref.source_name, ref.symbol) not in {
                (kind, name, self.symbol) for kind, name in requirements
            }:
                raise ValueError("coverage reference outside exact source/symbol roster")
        for ref in self.version_refs:
            if type(ref) is not SlotVersionRefV1:
                raise ValueError("typed exact-version reference required")
            ref.validate()
            if (ref.kind, ref.source_name, ref.symbol) not in {
                (kind, name, self.symbol) for kind, name in requirements
            }:
                raise ValueError("version reference outside required context kinds")
        if self.coverage_refs != tuple(
            sorted(self.coverage_refs, key=lambda r: (r.kind, r.source_name, r.start_ms, r.end_ms))
        ):
            raise ValueError("coverage references must be canonically sorted")
        if self.version_refs != tuple(
            sorted(
                self.version_refs,
                key=lambda r: (
                    r.kind,
                    r.source_name,
                    r.document_id,
                    r.version_available_ms or -1,
                    r.record_id,
                ),
            )
        ):
            raise ValueError("version references must be canonically sorted")
        if type(self.source_consistency_ready) is not bool:
            raise ValueError("explicit source consistency result required")
        if type(self.source_denial_detail) is not str or not self.source_denial_detail:
            raise ValueError("explicit source denial detail required")
        _sha(self.context_sha256, "as-of context hash")
        if type(self.selected_versions) is not tuple or len(self.selected_versions) > 2_000:
            raise ValueError("immutable bounded selected-version receipt tuple required")
        for selected in self.selected_versions:
            if type(selected) is not SlotSelectedVersionV1:
                raise ValueError("typed selected-version identity receipt required")
            selected.validate()
            if (selected.kind, selected.source_name) not in requirements:
                raise ValueError("selected version identity outside required source roster")
        if self.selected_versions != _expected_selected_versions(
            self.version_refs, self.coverage_refs, self.required_sources, self.symbol, self.cut_ms
        ):
            raise ValueError("selected-version receipt differs from exact as-of latest-version policy")
        ready, detail = self._expected_consistency()
        if self.source_consistency_ready is not ready or self.source_denial_detail != detail:
            raise ValueError("source consistency summary differs from bound coverage/version references")

    def _expected_consistency(self) -> tuple[bool, str]:
        by_source: list[tuple[str, str, bool, str]] = []
        for requirement in self.required_sources:
            available = _source_context_available(
                requirement, self.coverage_refs, self.version_refs, self.symbol, self.cut_ms
            )
            detail = (
                "UNVERIFIED_CONTENT_VERSION"
                if _source_has_publication_only_overlap(requirement, self.version_refs, self.cut_ms)
                else "UNVERIFIED_SOURCE_COVERAGE"
            )
            by_source.append((requirement.kind, requirement.source_name, available, detail))
        ready = all(item[2] for item in by_source)
        if ready:
            return True, "SOURCE_ADMISSION_NOT_ESTABLISHED"
        blocked = sorted(
            f"{kind}:{name}:{detail}" for kind, name, available, detail in by_source if not available
        )
        return False, "|".join(blocked) or NO_CALL_REASON

    @property
    def context_eligibility(self) -> str:
        return "UNAVAILABLE"

    @property
    def context_no_call_reason(self) -> str:
        return NO_CALL_REASON if not self.source_consistency_ready else ADMISSION_NO_CALL_REASON

    @property
    def proposal_state(self) -> str:
        """No source-blocked slot may fall back to proposal QUIET."""
        return "UNAVAILABLE"

    @property
    def source_admission_status(self) -> str:
        return "NOT_ESTABLISHED"

    @property
    def provenance_authenticity_verified(self) -> bool:
        return False

    @property
    def provider_dispatch_authorized(self) -> bool:
        return False

    @property
    def runtime_authority(self) -> bool:
        return False

    @property
    def economic_result_authorized(self) -> bool:
        return False

    @property
    def receipt_sha256(self) -> str:
        return digest(_payload(self))

    def to_json(self) -> str:
        self.validate()
        payload = _payload(self)
        encoded = canonical(payload | {"receipt_sha256": digest(payload)})
        if len(encoded.encode("utf-8")) > MAX_BINDING_BYTES:
            raise ValueError("four-arm slot binding exceeds the bounded evidence envelope")
        return encoded


def _payload(binding: HistoricalFourArmSlotBindingV1) -> dict[str, Any]:
    value = asdict(binding)
    return {
        "schema": SCHEMA,
        "binding_role": "AUDIT_ONLY_NOT_ROUTING_BRIDGE",
        **value,
        "context_eligibility": binding.context_eligibility,
        "context_no_call_reason": binding.context_no_call_reason,
        "proposal_state": binding.proposal_state,
        "source_admission_status": binding.source_admission_status,
        "provenance_authenticity_verified": binding.provenance_authenticity_verified,
        "provider_dispatch_authorized": binding.provider_dispatch_authorized,
        "runtime_authority": binding.runtime_authority,
        "economic_result_authorized": binding.economic_result_authorized,
    }


def _expected_selected_versions(
    version_refs: tuple[SlotVersionRefV1, ...],
    coverage_refs: tuple[SlotCoverageRefV1, ...],
    requirements: tuple[SlotRequiredSourceV1, ...],
    symbol: str,
    cut_ms: int,
) -> tuple[SlotSelectedVersionV1, ...]:
    selected: list[SlotSelectedVersionV1] = []
    for requirement in requirements:
        if not _source_context_available(requirement, coverage_refs, version_refs, symbol, cut_ms):
            continue
        lower = max(0, cut_ms - requirement.lookback_ms)
        latest_by_document: dict[str, SlotVersionRefV1] = {}
        for version in version_refs:
            if (version.kind, version.source_name) != (requirement.kind, requirement.source_name):
                continue
            available_at_cut = (
                version.version_available_ms is not None
                and version.version_available_ms <= cut_ms
                and version.published_upper_ms <= cut_ms
                and (
                    version.kind != "MACRO"
                    or (version.realized_ms is not None and version.realized_ms <= cut_ms)
                )
            )
            if not available_at_cut:
                continue
            previous = latest_by_document.get(version.document_id)
            if previous is None or version.version_available_ms > previous.version_available_ms:
                latest_by_document[version.document_id] = version
        for version in latest_by_document.values():
            if (
                version.version_available_ms >= lower
                and cut_ms - version.version_available_ms <= requirement.maximum_age_ms
            ):
                selected.append(
                    SlotSelectedVersionV1(
                        kind=version.kind,
                        source_name=version.source_name,
                        document_id=version.document_id,
                        record_id=version.record_id,
                        version_sha256=version.version_sha256,
                        version_available_ms=version.version_available_ms,
                    )
                )
    return tuple(sorted(selected, key=lambda r: (r.version_available_ms, r.record_id)))


def _source_has_publication_only_overlap(
    requirement: SlotRequiredSourceV1,
    version_refs: tuple[SlotVersionRefV1, ...],
    cut_ms: int,
) -> bool:
    lower = max(0, cut_ms - requirement.lookback_ms)
    return any(
        ref.kind == requirement.kind
        and ref.source_name == requirement.source_name
        and ref.proof_kind == "PUBLICATION_ONLY"
        and ref.published_lower_ms <= cut_ms
        and ref.published_upper_ms >= lower
        for ref in version_refs
    )


def _source_context_available(
    requirement: SlotRequiredSourceV1,
    coverage_refs: tuple[SlotCoverageRefV1, ...],
    version_refs: tuple[SlotVersionRefV1, ...],
    symbol: str,
    cut_ms: int,
) -> bool:
    lower = max(0, cut_ms - requirement.lookback_ms)
    coverage_ok = any(
        ref.kind == requirement.kind
        and ref.source_name == requirement.source_name
        and ref.symbol == symbol
        and ref.start_ms <= lower
        and cut_ms < ref.end_ms
        and ref.status == "COMPLETE"
        and (ref.proof_kind != "CONTEMPORANEOUS_LOCAL" or ref.captured_ms <= cut_ms)
        for ref in coverage_refs
    )
    return coverage_ok and not _source_has_publication_only_overlap(requirement, version_refs, cut_ms)


def bind_historical_four_arm_slot_v1(
    *,
    sample_id: str,
    window_id: str,
    window_start_ms: int,
    window_end_exclusive_ms: int,
    symbol: str,
    cut_ms: int,
    schedule_sha256: str,
    protocol_sha256: str,
    technical_state: str,
    technical_reason: str,
    market_source_name: str,
    market_source_receipt_sha256: str,
    market_source_as_of_ms: int | None,
    market_observed_received_at_ms: int | None,
    market_captured_at_ms: int,
    archive: HistoricalArchive,
    requirements: tuple[SourceRequirement, ...],
    context_source_receipts: tuple[SlotSourceReceiptClockV1, ...],
) -> HistoricalFourArmSlotBindingV1:
    """Bind a complete fixed slot roster while keeping admission fail-closed.

    The caller supplies receipt hashes and clocks; this function only validates
    consistency. No combination of those values can set admission to accepted.
    """
    if type(archive) is not HistoricalArchive:
        raise TypeError("exact HistoricalArchive required")
    archive.validate()
    if type(requirements) is not tuple or not requirements:
        raise ValueError("immutable source requirement roster required")
    if type(context_source_receipts) is not tuple:
        raise ValueError("immutable context source receipt tuple required")
    if any(type(r) is not SourceRequirement for r in requirements):
        raise TypeError("exact SourceRequirement values required")
    source_requirements = tuple(
        sorted(
            (
                SlotRequiredSourceV1(r.kind, r.source_name, r.required, r.lookback_ms, r.maximum_age_ms)
                for r in requirements
            ),
            key=lambda r: (r.kind, r.source_name),
        )
    )
    source_receipts = (
        SlotSourceReceiptClockV1(
            sample_id,
            window_id,
            symbol,
            cut_ms,
            "MARKET_SNAPSHOT",
            market_source_name,
            market_source_receipt_sha256,
            market_source_as_of_ms,
            market_observed_received_at_ms,
            market_captured_at_ms,
        ),
        *context_source_receipts,
    )
    # Canonicalize the derived tuple; this changes order only, never content.
    source_receipts = tuple(
        sorted(source_receipts, key=lambda r: (r.source_kind, r.source_name, r.source_receipt_sha256))
    )
    for receipt in source_receipts:
        if type(receipt) is not SlotSourceReceiptClockV1:
            raise TypeError("exact SlotSourceReceiptClockV1 values required")
        receipt.validate()
    view = as_of_context(archive, symbol, cut_ms, requirements)
    required_ready = view["required_sources_ready"] is True
    lower_by_pair = {(r.kind, r.source_name): max(0, cut_ms - r.lookback_ms) for r in requirements}
    coverage_refs = tuple(
        SlotCoverageRefV1(
            source_name=c.source_name,
            kind=c.kind,
            symbol=c.symbol,
            start_ms=c.start_ms,
            end_ms=c.end_ms,
            status=c.status,
            proof_kind=c.proof_kind,
            proof_sha256=c.proof_sha256,
            captured_ms=c.captured_ms,
            coverage_sha256=digest(asdict(c)),
        )
        for c in sorted(
            (
                c
                for c in archive.coverage
                if (c.kind, c.source_name, c.symbol) in {(kind, name, symbol) for kind, name in lower_by_pair}
                and c.start_ms < cut_ms
                and c.end_ms > lower_by_pair[c.kind, c.source_name]
            ),
            key=lambda c: (c.kind, c.source_name, c.start_ms, c.end_ms),
        )
    )
    # Retain every exact version in the bounded archive for these required
    # source/symbol pairs. Future/old rows are audit-only; selected identities
    # are separately derived with the exact as-of policy below.
    version_refs = tuple(
        SlotVersionRefV1(
            record_id=v.record_id,
            document_id=v.document_id,
            source_name=v.source_name,
            kind=v.kind,
            symbol=symbol,
            raw_content_sha256=v.raw_content_sha256,
            published_lower_ms=v.published_lower_ms,
            published_upper_ms=v.published_upper_ms,
            version_available_ms=v.version_available_ms,
            captured_ms=v.captured_ms,
            proof_kind=v.proof_kind,
            proof_sha256=v.proof_sha256,
            event_ms=v.event_ms,
            realized_ms=v.realized_ms,
            version_sha256=v.sha256,
        )
        for v in sorted(
            (
                v
                for v in archive.versions
                if v.kind in {kind for kind, _ in lower_by_pair}
                and (v.kind, v.source_name) in lower_by_pair
                and symbol in v.symbols
            ),
            key=lambda v: (v.kind, v.source_name, v.document_id, v.version_available_ms or -1, v.record_id),
        )
    )
    if required_ready:
        denial_detail = "SOURCE_ADMISSION_NOT_ESTABLISHED"
    else:
        source_reasons = sorted(
            f"{s['kind']}:{s['source_name']}:{s['reason']}"
            for s in view["context"]["sources"]
            if s["required"] and s["state"] != "AVAILABLE"
        )
        denial_detail = "|".join(source_reasons) or NO_CALL_REASON
    binding = HistoricalFourArmSlotBindingV1(
        sample_id=sample_id,
        window_id=window_id,
        window_start_ms=window_start_ms,
        window_end_exclusive_ms=window_end_exclusive_ms,
        symbol=symbol,
        cut_ms=cut_ms,
        schedule_sha256=schedule_sha256,
        protocol_sha256=protocol_sha256,
        technical_state=technical_state,
        technical_reason=technical_reason,
        source_archive_sha256=archive.sha256,
        required_sources=source_requirements,
        source_receipts=source_receipts,
        coverage_refs=coverage_refs,
        version_refs=version_refs,
        source_consistency_ready=required_ready,
        source_denial_detail=denial_detail,
        context_sha256=view["context_sha256"],
        selected_versions=_expected_selected_versions(
            version_refs, coverage_refs, source_requirements, symbol, cut_ms
        ),
    )
    binding.validate()
    return binding


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(_: str) -> None:
    raise ValueError("non-finite JSON constants are forbidden")


def binding_from_json(raw: str | bytes) -> HistoricalFourArmSlotBindingV1:
    """Strict canonical read-back; verifies schema, derived deny fields and hash."""
    if type(raw) not in {str, bytes}:
        raise TypeError("canonical binding JSON bytes or string required")
    if len(raw if type(raw) is bytes else raw.encode("utf-8")) > MAX_BINDING_BYTES:
        raise ValueError("four-arm slot binding exceeds the bounded evidence envelope")
    try:
        doc = json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_reject_json_constant)
    except (ValueError, TypeError, UnicodeDecodeError, RecursionError):
        raise ValueError("invalid strict binding JSON") from None
    if (
        type(doc) is not dict
        or set(doc) != _BINDING_FIELDS | {"receipt_sha256"}
        or doc.get("schema") != SCHEMA
    ):
        raise ValueError("binding schema or exact fields differ")
    _sha(doc["receipt_sha256"], "binding receipt hash")
    payload = {k: v for k, v in doc.items() if k != "receipt_sha256"}
    canonical_text = raw.decode("utf-8") if type(raw) is bytes else raw
    if canonical(doc) != canonical_text:
        raise ValueError("canonical binding JSON required")
    if digest(payload) != doc["receipt_sha256"]:
        raise ValueError("binding receipt hash differs from canonical content")
    try:
        binding = HistoricalFourArmSlotBindingV1(
            sample_id=doc["sample_id"],
            window_id=doc["window_id"],
            window_start_ms=doc["window_start_ms"],
            window_end_exclusive_ms=doc["window_end_exclusive_ms"],
            symbol=doc["symbol"],
            cut_ms=doc["cut_ms"],
            schedule_sha256=doc["schedule_sha256"],
            protocol_sha256=doc["protocol_sha256"],
            technical_state=doc["technical_state"],
            technical_reason=doc["technical_reason"],
            source_archive_sha256=doc["source_archive_sha256"],
            required_sources=tuple(SlotRequiredSourceV1(**x) for x in doc["required_sources"]),
            source_receipts=tuple(SlotSourceReceiptClockV1(**x) for x in doc["source_receipts"]),
            coverage_refs=tuple(SlotCoverageRefV1(**x) for x in doc["coverage_refs"]),
            version_refs=tuple(SlotVersionRefV1(**x) for x in doc["version_refs"]),
            source_consistency_ready=doc["source_consistency_ready"],
            source_denial_detail=doc["source_denial_detail"],
            context_sha256=doc["context_sha256"],
            selected_versions=tuple(SlotSelectedVersionV1(**x) for x in doc["selected_versions"]),
        )
        binding.validate()
    except (KeyError, TypeError, ValueError, RecursionError):
        raise ValueError("binding fields failed strict validation") from None
    if canonical(_payload(binding)) != canonical(payload):
        raise ValueError("binding derived fields or receipt roster changed")
    return binding


__all__ = [
    "HistoricalFourArmSlotBindingV1",
    "MAX_BINDING_BYTES",
    "SlotCoverageRefV1",
    "SlotRequiredSourceV1",
    "SlotSelectedVersionV1",
    "SlotSourceReceiptClockV1",
    "SlotVersionRefV1",
    "bind_historical_four_arm_slot_v1",
    "binding_from_json",
]
