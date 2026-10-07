"""Bounded exact-version historical context, never historical receive-clock proof.

No fetch, provider, database or trading operation. Archive text is untrusted data.
The input checksum establishes bytes, not authenticity or exhaustive world news.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .inputs import UNIVERSE

SCHEMA = "kairos.development.historical-context.v1"
POLICY = "EXACT_VERSION_UPPER_BOUND_ASOF_V1"
MAX_RECORDS = 2_000
MAX_BYTES = 16 * 1024 * 1024
PROOFS = {"CONTEMPORANEOUS_LOCAL", "ARCHIVE_VERSION", "PUBLICATION_ONLY", "TEST_FIXTURE"}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _sha(value: str) -> None:
    if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise ValueError("canonical historical SHA256 required")


def _clock(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("nonnegative integer historical clock required")


def _name(value: str) -> None:
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is None:
        raise ValueError("bounded source identity required")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate historical JSON key")
        result[key] = value
    return result


def _bad_constant(_: str) -> None:
    raise ValueError("nonfinite historical JSON")


def _json(value: str | bytes) -> Any:
    try:
        return json.loads(value, object_pairs_hook=_pairs, parse_constant=_bad_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("invalid historical JSON") from None


@dataclass(frozen=True)
class HistoricalVersion:
    """Caller-attested exact content version. Event time is not availability."""

    record_id: str
    document_id: str
    source_name: str
    kind: str
    symbols: tuple[str, ...]
    url: str
    payload_json: str
    raw_content_sha256: str
    extraction_policy_sha256: str
    published_lower_ms: int
    published_upper_ms: int
    version_available_ms: int | None
    captured_ms: int
    proof_kind: str
    proof_sha256: str | None
    event_ms: int | None = None
    realized_ms: int | None = None

    def __post_init__(self) -> None:
        for name in (self.record_id, self.document_id, self.source_name):
            _name(name)
        if self.kind not in {"NEWS", "MACRO"} or self.proof_kind not in PROOFS:
            raise ValueError("explicit historical kind/proof required")
        if (
            type(self.symbols) is not tuple
            or not self.symbols
            or len(set(self.symbols)) != len(self.symbols)
            or any(s not in UNIVERSE for s in self.symbols)
        ):
            raise ValueError("explicit immutable symbol scope required")
        if type(self.url) is not str:
            raise ValueError("source URL must be a string")
        url = urlsplit(self.url)
        if (
            type(self.url) is not str
            or len(self.url) > 2_048
            or url.scheme != "https"
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.fragment
        ):
            raise ValueError("bounded HTTPS source reference required; never fetched")
        _sha(self.raw_content_sha256)
        _sha(self.extraction_policy_sha256)
        for clock in (self.published_lower_ms, self.published_upper_ms, self.captured_ms):
            _clock(clock)
        if not self.published_lower_ms <= self.published_upper_ms <= self.captured_ms:
            raise ValueError("publication interval/capture ordering invalid")
        if self.event_ms is not None:
            _clock(self.event_ms)
        if self.realized_ms is not None:
            _clock(self.realized_ms)
        if self.kind == "MACRO" and self.realized_ms is None:
            raise ValueError("macro vintage requires realized measurement clock")
        if self.proof_kind == "PUBLICATION_ONLY":
            if self.version_available_ms is not None or self.proof_sha256 is not None:
                raise ValueError("publication metadata cannot invent exact-version availability")
        else:
            _clock(self.version_available_ms)
            _sha(self.proof_sha256)
            if not self.published_upper_ms <= self.version_available_ms <= self.captured_ms:
                raise ValueError("exact version availability must follow publication and precede capture")
            if self.proof_kind == "CONTEMPORANEOUS_LOCAL" and self.version_available_ms != self.captured_ms:
                raise ValueError("local receipt availability must retain actual local capture")
        if type(self.payload_json) is not str or len(self.payload_json.encode()) > 32_768:
            raise ValueError("bounded canonical source payload required")
        content = _json(self.payload_json)
        expected = {"headline", "body"} if self.kind == "NEWS" else {"metric", "value", "unit"}
        if type(content) is not dict or set(content) != expected or canonical(content) != self.payload_json:
            raise ValueError("exact canonical NEWS/MACRO extracted payload required")
        if any(type(value) is not str or len(value) > 24_000 for value in content.values()):
            raise ValueError("bounded extracted strings required, not executable references")
        if not content["headline" if self.kind == "NEWS" else "metric"].strip():
            raise ValueError("source headline/metric required")

    @property
    def sha256(self) -> str:
        self.__post_init__()
        return digest(asdict(self))

    def available_at(self, cutoff_ms: int) -> bool:
        self.__post_init__()
        _clock(cutoff_ms)
        return (
            self.version_available_ms is not None
            and self.version_available_ms <= cutoff_ms
            and self.published_upper_ms <= cutoff_ms
            and (self.kind != "MACRO" or self.realized_ms <= cutoff_ms)
        )


@dataclass(frozen=True)
class HistoricalCoverage:
    """Explicit bounded source coverage claim, not proof of every world news item."""

    source_name: str
    kind: str
    symbol: str
    start_ms: int
    end_ms: int
    record_ids: tuple[str, ...]
    status: str
    proof_kind: str
    proof_sha256: str | None
    captured_ms: int

    def __post_init__(self) -> None:
        _name(self.source_name)
        for clock in (self.start_ms, self.end_ms, self.captured_ms):
            _clock(clock)
        if self.kind not in {"NEWS", "MACRO"} or self.symbol not in UNIVERSE or self.end_ms <= self.start_ms:
            raise ValueError("exact source coverage scope required")
        if type(self.record_ids) is not tuple or tuple(sorted(set(self.record_ids))) != self.record_ids:
            raise ValueError("canonical unique coverage member roster required")
        for record_id in self.record_ids:
            _name(record_id)
        if self.status not in {"COMPLETE", "UNKNOWN"} or self.proof_kind not in PROOFS - {"PUBLICATION_ONLY"}:
            raise ValueError("explicit coverage status/proof required")
        if self.status == "COMPLETE":
            _sha(self.proof_sha256)
            if self.captured_ms < self.end_ms - 1:
                raise ValueError("coverage cannot precede its covered interval")
        elif self.proof_sha256 is not None:
            raise ValueError("unknown coverage cannot invent completeness proof")


@dataclass(frozen=True)
class SourceRequirement:
    source_name: str
    kind: str
    required: bool
    lookback_ms: int
    maximum_age_ms: int

    def __post_init__(self) -> None:
        _name(self.source_name)
        if self.kind not in {"NEWS", "MACRO"} or type(self.required) is not bool:
            raise ValueError("explicit source requirement required")
        for clock in (self.lookback_ms, self.maximum_age_ms):
            _clock(clock)
        if not 0 < self.maximum_age_ms <= self.lookback_ms <= 31 * 86_400_000:
            raise ValueError("bounded positive lookback and TTL required")


@dataclass(frozen=True)
class HistoricalArchive:
    versions: tuple[HistoricalVersion, ...]
    coverage: tuple[HistoricalCoverage, ...]

    def validate(self) -> None:
        if (
            type(self.versions) is not tuple
            or type(self.coverage) is not tuple
            or len(self.versions) > MAX_RECORDS
            or len(self.coverage) > 1_000
        ):
            raise ValueError("bounded immutable historical archive required")
        for version in self.versions:
            if not isinstance(version, HistoricalVersion):
                raise ValueError("typed exact historical version required")
            version.__post_init__()
        ids = {v.record_id: v for v in self.versions}
        if len(ids) != len(self.versions):
            raise ValueError("duplicate historical record identity")
        seen = set()
        for version in self.versions:
            key = (version.source_name, version.kind, version.document_id, version.version_available_ms)
            if key in seen:
                raise ValueError("ambiguous document version availability")
            seen.add(key)
        coverage_keys = set()
        for coverage in self.coverage:
            if not isinstance(coverage, HistoricalCoverage):
                raise ValueError("typed coverage receipt required")
            coverage.__post_init__()
            key = (coverage.source_name, coverage.kind, coverage.symbol, coverage.start_ms, coverage.end_ms)
            if key in coverage_keys:
                raise ValueError("duplicate coverage scope")
            coverage_keys.add(key)
            members = set(coverage.record_ids)
            if any(
                member not in ids
                or (ids[member].source_name, ids[member].kind) != (coverage.source_name, coverage.kind)
                or coverage.symbol not in ids[member].symbols
                for member in members
            ):
                raise ValueError("coverage member/source identity differs")
            expected = {
                v.record_id
                for v in self.versions
                if (v.source_name, v.kind) == (coverage.source_name, coverage.kind)
                and coverage.symbol in v.symbols
                and coverage.start_ms
                <= (v.version_available_ms if v.version_available_ms is not None else v.published_upper_ms)
                < coverage.end_ms
            }
            if expected != members:
                raise ValueError("coverage omitted or added an out-of-interval exact version")
        fixture_modes = {v.proof_kind == "TEST_FIXTURE" for v in self.versions}
        fixture_modes.update(c.proof_kind == "TEST_FIXTURE" for c in self.coverage)
        if len(fixture_modes) > 1:
            raise ValueError("fixture and historical evidence cannot be mixed")
        if len(self.to_json_unchecked().encode()) > MAX_BYTES:
            raise ValueError("historical archive byte bound exceeded")

    def to_json_unchecked(self) -> str:
        return canonical(
            {
                "schema": SCHEMA,
                "versions": [asdict(v) for v in self.versions],
                "coverage": [asdict(c) for c in self.coverage],
            }
        )

    def to_json(self) -> str:
        self.validate()
        return self.to_json_unchecked()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()


def import_archive(encoded: bytes, expected_sha256: str) -> HistoricalArchive:
    """Require externally recorded canonical bytes; no URL/reference is opened."""
    _sha(expected_sha256)
    if type(encoded) is not bytes or len(encoded) > MAX_BYTES:
        raise ValueError("bounded historical bytes required")
    if hashlib.sha256(encoded).hexdigest() != expected_sha256:
        raise ValueError("historical archive digest differs")
    raw = _json(encoded)
    if type(raw) is not dict or set(raw) != {"schema", "versions", "coverage"} or raw["schema"] != SCHEMA:
        raise ValueError("exact historical archive schema required")
    try:
        versions = tuple(HistoricalVersion(**{**v, "symbols": tuple(v["symbols"])}) for v in raw["versions"])
        coverage = tuple(
            HistoricalCoverage(**{**c, "record_ids": tuple(c["record_ids"])}) for c in raw["coverage"]
        )
        archive = HistoricalArchive(versions, coverage)
        if archive.to_json().encode() != encoded:
            raise ValueError
        return archive
    except (TypeError, KeyError, ValueError, RecursionError):
        raise ValueError("noncanonical historical archive contract") from None


def read_archive(path: Path, expected_sha256: str) -> HistoricalArchive:
    with path.open("rb") as stream:
        return import_archive(stream.read(MAX_BYTES + 1), expected_sha256)


def export_archive(path: Path, archive: HistoricalArchive) -> str:
    """Create-only canonical transport; preserve existing receipts on collision."""
    encoded = archive.to_json().encode()
    with path.open("xb") as stream:
        stream.write(encoded)
    return hashlib.sha256(encoded).hexdigest()


def as_of_context(
    archive: HistoricalArchive, symbol: str, cutoff_ms: int, requirements: tuple[SourceRequirement, ...]
) -> dict[str, Any]:
    """Latest eligible versions only; unknown coverage never becomes known no-news."""
    archive.validate()
    _clock(cutoff_ms)
    if symbol not in UNIVERSE or type(requirements) is not tuple or not 0 < len(requirements) <= 20:
        raise ValueError("explicit bounded source roster/symbol required")
    keys = []
    source_views = []
    material_captured_ms = []
    for requirement in requirements:
        requirement.__post_init__()
        key = (requirement.source_name, requirement.kind)
        keys.append(key)
        lower = max(0, cutoff_ms - requirement.lookback_ms)
        coverage = [
            c
            for c in archive.coverage
            if (c.source_name, c.kind, c.symbol) == (*key, symbol)
            and c.start_ms <= lower
            and cutoff_ms < c.end_ms
            and c.status == "COMPLETE"
            and (c.proof_kind != "CONTEMPORANEOUS_LOCAL" or c.captured_ms <= cutoff_ms)
        ]
        latest: dict[str, HistoricalVersion] = {}
        unknown_content = False
        for version in archive.versions:
            if (version.source_name, version.kind) != key or symbol not in version.symbols:
                continue
            if version.proof_kind == "PUBLICATION_ONLY" and (
                version.published_lower_ms <= cutoff_ms and version.published_upper_ms >= lower
            ):
                unknown_content = True
                material_captured_ms.append(version.captured_ms)
            if not version.available_at(cutoff_ms):
                continue
            previous = latest.get(version.document_id)
            if previous is None or version.version_available_ms > previous.version_available_ms:
                latest[version.document_id] = version
        selected = sorted(
            (
                v
                for v in latest.values()
                if v.version_available_ms >= lower
                and cutoff_ms - v.version_available_ms <= requirement.maximum_age_ms
            ),
            key=lambda v: (v.version_available_ms, v.record_id),
        )
        state = "AVAILABLE" if coverage and not unknown_content else "UNAVAILABLE"
        if state == "AVAILABLE":
            material_captured_ms.append(min(c.captured_ms for c in coverage))
            material_captured_ms.extend(v.captured_ms for v in selected)
        else:
            relevant_coverage = [
                c
                for c in archive.coverage
                if (c.source_name, c.kind, c.symbol) == (*key, symbol)
                and c.start_ms <= lower
                and cutoff_ms < c.end_ms
            ]
            if relevant_coverage:
                material_captured_ms.append(min(c.captured_ms for c in relevant_coverage))
        # Raw archive/coverage/future-window hashes and today's capture clocks are
        # audit-only. Do not let future archive membership change earlier prompts.
        source_views.append(
            {
                "source_name": requirement.source_name,
                "kind": requirement.kind,
                "required": requirement.required,
                "state": state,
                "reason": None
                if state == "AVAILABLE"
                else "UNVERIFIED_CONTENT_VERSION"
                if unknown_content
                else "UNVERIFIED_SOURCE_COVERAGE",
                "lookback_ms": requirement.lookback_ms,
                "maximum_age_ms": requirement.maximum_age_ms,
                "items": [
                    {
                        "content_ref": digest(_json(v.payload_json)),
                        "url": v.url,
                        "published_lower_ms": v.published_lower_ms,
                        "published_upper_ms": v.published_upper_ms,
                        "available_ms": v.version_available_ms,
                        "event_ms": v.event_ms,
                        "realized_ms": v.realized_ms,
                        "payload": _json(v.payload_json),
                    }
                    for v in selected
                ]
                if state == "AVAILABLE"
                else [],
            }
        )
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate source requirement")
    result = {
        "schema": SCHEMA,
        "selection_policy": POLICY,
        "symbol": symbol,
        "cutoff_ms": cutoff_ms,
        "sources": source_views,
    }
    return {
        "context": result,
        "context_sha256": digest(result),
        "required_sources_ready": all(s["state"] == "AVAILABLE" for s in source_views if s["required"]),
        "archive_sha256": archive.sha256,
        "context_materialized_ms": max(material_captured_ms, default=0),
        "historical_receive_clock_proven": False,
        "provenance_authenticity_verified": False,
        "all_world_news_complete": False,
        "fixture_only": any(c.proof_kind == "TEST_FIXTURE" for c in archive.coverage)
        or any(v.proof_kind == "TEST_FIXTURE" for v in archive.versions),
        "trading_authority": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect exact historical source transport offline")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        archive = read_archive(args.input, args.expected_sha256)
        print(
            canonical(
                {
                    "schema": SCHEMA,
                    "archive_sha256": archive.sha256,
                    "versions": len(archive.versions),
                    "coverage_receipts": len(archive.coverage),
                    "historical_receive_clock_proven": False,
                    "provenance_authenticity_verified": False,
                    "economics_executed": False,
                    "LIVE_READY": False,
                    "STRATEGY_POLICY": "REJECT_ALL",
                }
            )
        )
    except (OSError, ValueError, TypeError):
        print(canonical({"status": "REJECTED", "reason": "INVALID_HISTORICAL_ARCHIVE"}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
