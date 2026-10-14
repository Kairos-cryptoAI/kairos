from __future__ import annotations

import inspect
import json
from dataclasses import replace

import pytest

from adaptive_replay.historical_context import (
    HistoricalArchive,
    HistoricalCoverage,
    HistoricalVersion,
    SourceRequirement,
    as_of_context,
    canonical,
    digest,
)
from adaptive_replay.historical_four_arm_slot_binding_v1 import (
    NO_CALL_REASON,
    SlotSourceReceiptClockV1,
    bind_historical_four_arm_slot_v1,
    binding_from_json,
)

CUT = 3_000_000
CAPTURED = 5_000_000
WINDOW_START = 0
WINDOW_END = 4_000_000
SYMBOL = "BTCUSDT"
WINDOW = "window-1"
SAMPLE = "sample-1"
SCHEDULE = "a" * 64
PROTOCOL = "b" * 64
REQS = (
    SourceRequirement("official-news", "NEWS", True, 86_400_000, 86_400_000),
    SourceRequirement("official-macro", "MACRO", True, 31 * 86_400_000, 31 * 86_400_000),
)


def _version(kind: str, name: str, *, proof_kind="ARCHIVE_VERSION", available=CUT - 1_000):
    payload = (
        {"headline": "bounded", "body": "example"}
        if kind == "NEWS"
        else {"metric": "index", "value": "1", "unit": "index"}
    )
    if proof_kind == "PUBLICATION_ONLY":
        available = None
    return HistoricalVersion(
        record_id=f"{kind.lower()}-record",
        document_id=f"{kind.lower()}-document",
        source_name=name,
        kind=kind,
        symbols=(SYMBOL,),
        url="https://example.invalid/source",
        payload_json=canonical(payload),
        raw_content_sha256=digest(payload),
        extraction_policy_sha256="c" * 64,
        published_lower_ms=CUT - 10_000,
        published_upper_ms=CUT - 9_000,
        version_available_ms=available,
        captured_ms=CAPTURED,
        proof_kind=proof_kind,
        proof_sha256=None if proof_kind == "PUBLICATION_ONLY" else "d" * 64,
        event_ms=CUT - 9_500 if kind == "NEWS" else None,
        realized_ms=CUT - 8_000 if kind == "MACRO" else None,
    )


def _coverage(kind: str, name: str, *, status="COMPLETE", record_ids=()):
    return HistoricalCoverage(
        source_name=name,
        kind=kind,
        symbol=SYMBOL,
        start_ms=0,
        end_ms=CAPTURED + 1,
        record_ids=tuple(record_ids),
        status=status,
        proof_kind="ARCHIVE_VERSION",
        proof_sha256="e" * 64 if status == "COMPLETE" else None,
        captured_ms=CAPTURED,
    )


def _archive(*, versions=(), coverage_status="COMPLETE"):
    versions = tuple(versions)
    by_key = {}
    for version in versions:
        by_key.setdefault((version.kind, version.source_name), []).append(version.record_id)
    coverage = tuple(
        _coverage(
            kind,
            name,
            status=coverage_status[kind] if isinstance(coverage_status, dict) else coverage_status,
            record_ids=() if (kind, name) not in by_key else tuple(sorted(by_key[kind, name])),
        )
        for kind, name in (("NEWS", "official-news"), ("MACRO", "official-macro"))
    )
    return HistoricalArchive(versions, coverage)


def _receipt(kind: str, name: str, receipt_hash: str, *, observed=None, captured=CAPTURED):
    return SlotSourceReceiptClockV1(
        sample_id=SAMPLE,
        window_id=WINDOW,
        symbol=SYMBOL,
        cut_ms=CUT,
        source_kind=kind,
        source_name=name,
        source_receipt_sha256=receipt_hash,
        source_as_of_ms=CUT - 1,
        observed_received_at_ms=observed,
        captured_at_ms=captured,
    )


def _bind(
    archive,
    *,
    technical_state="QUIET",
    technical_reason="NO_TECHNICAL_CANDIDATE",
    context=None,
    cut=CUT,
    sample=SAMPLE,
    window_id=WINDOW,
    requirements=REQS,
):
    return bind_historical_four_arm_slot_v1(
        sample_id=sample,
        window_id=window_id,
        window_start_ms=WINDOW_START,
        window_end_exclusive_ms=WINDOW_END,
        symbol=SYMBOL,
        cut_ms=cut,
        schedule_sha256=SCHEDULE,
        protocol_sha256=PROTOCOL,
        technical_state=technical_state,
        technical_reason=technical_reason,
        market_source_name="official-market",
        market_source_receipt_sha256="1" * 64,
        market_source_as_of_ms=CUT,
        market_observed_received_at_ms=None,
        market_captured_at_ms=CAPTURED,
        archive=archive,
        requirements=requirements,
        context_source_receipts=context
        or (
            _receipt("NEWS", "official-news", "2" * 64),
            _receipt("MACRO", "official-macro", "3" * 64),
        ),
    )


def _complete_versions():
    return (
        _version("NEWS", "official-news"),
        _version("MACRO", "official-macro"),
    )


def test_complete_empty_coverage_is_consistent_but_never_admitted_or_dispatched():
    binding = _bind(_archive())

    assert binding.source_consistency_ready is True
    assert binding.source_admission_status == "NOT_ESTABLISHED"
    assert binding.context_eligibility == "UNAVAILABLE"
    assert binding.context_no_call_reason == "SOURCE_ADMISSION_NOT_ESTABLISHED"
    assert binding.proposal_state == "UNAVAILABLE"
    assert binding.source_denial_detail == "SOURCE_ADMISSION_NOT_ESTABLISHED"
    assert binding.context_sha256 == binding_from_json(binding.to_json()).context_sha256
    assert json.loads(binding.to_json())["binding_role"] == "AUDIT_ONLY_NOT_ROUTING_BRIDGE"
    assert binding.provenance_authenticity_verified is False
    assert binding.provider_dispatch_authorized is False
    assert binding.runtime_authority is False
    assert binding.economic_result_authorized is False


def test_publication_only_and_unknown_coverage_keep_explicit_deny_reasons():
    pub_only = _version("NEWS", "official-news", proof_kind="PUBLICATION_ONLY")
    binding = _bind(_archive(versions=(pub_only,), coverage_status="UNKNOWN"))

    assert binding.source_consistency_ready is False
    assert "NEWS:official-news:UNVERIFIED_CONTENT_VERSION" in binding.source_denial_detail
    assert "MACRO:official-macro:UNVERIFIED_SOURCE_COVERAGE" in binding.source_denial_detail
    assert binding.context_no_call_reason == "REQUIRED_SOURCE_UNAVAILABLE"


def test_coverage_ending_at_cut_is_stale_for_the_required_window():
    stale_news = HistoricalCoverage(
        source_name="official-news",
        kind="NEWS",
        symbol=SYMBOL,
        start_ms=0,
        end_ms=CUT,
        record_ids=(),
        status="COMPLETE",
        proof_kind="ARCHIVE_VERSION",
        proof_sha256="e" * 64,
        captured_ms=CAPTURED,
    )
    current_macro = _coverage("MACRO", "official-macro")
    archive = HistoricalArchive((), (stale_news, current_macro))
    binding = _bind(archive)

    assert binding.source_consistency_ready is False
    assert binding.source_denial_detail == "NEWS:official-news:UNVERIFIED_SOURCE_COVERAGE"
    assert binding.context_no_call_reason == NO_CALL_REASON


@pytest.mark.parametrize(
    ("technical_state", "technical_reason"),
    [
        ("QUIET", "NO_TECHNICAL_CANDIDATE"),
        ("HARD_VETO", "NATIVE_HARD_VETO"),
        ("CONFLICT", "NATIVE_CONFLICT"),
        ("CRASH_DEFENSE", "NATIVE_CRASH_DEFENSE"),
        ("UNCERTAIN", "NATIVE_UNCERTAIN"),
        ("UNAVAILABLE", "NATIVE_INPUT_UNAVAILABLE"),
    ],
)
def test_source_deny_does_not_relabel_original_technical_state(technical_state, technical_reason):
    binding = _bind(
        _archive(coverage_status="UNKNOWN"),
        technical_state=technical_state,
        technical_reason=technical_reason,
    )

    assert binding.technical_state == technical_state
    assert binding.technical_reason == technical_reason
    assert binding.context_eligibility == "UNAVAILABLE"
    assert binding.proposal_state == "UNAVAILABLE"
    assert binding.context_no_call_reason == NO_CALL_REASON


def test_actual_receive_clock_unknown_is_not_filled_from_source_or_capture_clock():
    binding = _bind(_archive(versions=_complete_versions()))
    market = next(r for r in binding.source_receipts if r.source_kind == "MARKET_SNAPSHOT")
    news_version = next(v for v in binding.version_refs if v.kind == "NEWS")

    assert market.source_as_of_ms == CUT
    assert market.observed_received_at_ms is None
    assert market.captured_at_ms == CAPTURED
    assert news_version.version_available_ms == CUT - 1_000
    assert news_version.captured_ms == CAPTURED
    assert binding.source_admission_status == "NOT_ESTABLISHED"


def test_late_local_version_and_receive_are_not_backdated_to_cut():
    late = _version("NEWS", "official-news", proof_kind="CONTEMPORANEOUS_LOCAL", available=CAPTURED)
    macro = _version("MACRO", "official-macro")
    news_receipt = _receipt("NEWS", "official-news", "2" * 64, observed=CAPTURED - 1)
    binding = _bind(
        _archive(versions=(late, macro)),
        context=(news_receipt, _receipt("MACRO", "official-macro", "3" * 64)),
    )

    # The complete archive coverage can establish consistency even when this
    # particular local version arrived after the cut; it cannot backdate it.
    assert binding.source_consistency_ready is True
    assert binding.source_denial_detail == "SOURCE_ADMISSION_NOT_ESTABLISHED"
    news_receipt = next(r for r in binding.source_receipts if r.source_kind == "NEWS")
    assert news_receipt.observed_received_at_ms == CAPTURED - 1
    future_news = next(v for v in binding.version_refs if v.kind == "NEWS")
    assert future_news.version_available_ms == CAPTURED  # retained as an audit reference
    assert future_news.record_id not in {v.record_id for v in binding.selected_versions}


def test_latest_eligible_revision_of_old_publication_is_bound_as_selected():
    # The evaluator selects on exact version availability, not publication time.
    # This revision's publication interval is outside the NEWS lookback, while
    # its later exact version became locally available inside that lookback.
    earlier_revision = replace(
        _version("NEWS", "official-news", available=CUT - 800),
        published_lower_ms=CUT - 10_000,
        published_upper_ms=CUT - 5_000,
    )
    later_revision = replace(
        _version("NEWS", "official-news", available=CUT - 500),
        record_id="news-record-v2",
        published_lower_ms=CUT - 10_000,
        published_upper_ms=CUT - 5_000,
    )
    narrow_news_requirement = SourceRequirement("official-news", "NEWS", True, 1_000, 1_000)
    requirements = (narrow_news_requirement, REQS[1])
    binding = _bind(
        _archive(
            versions=(
                earlier_revision,
                later_revision,
                _version("MACRO", "official-macro"),
            )
        ),
        requirements=requirements,
    )

    news_refs = [v for v in binding.version_refs if v.kind == "NEWS"]
    assert len(news_refs) == 2  # older eligible revision remains bound for audit
    assert all(v.published_upper_ms < CUT - narrow_news_requirement.lookback_ms for v in news_refs)
    assert [v.record_id for v in binding.selected_versions if v.kind == "NEWS"] == ["news-record-v2"]


def test_unknown_news_coverage_suppresses_news_selection_but_not_available_macro():
    archive = _archive(
        versions=_complete_versions(),
        coverage_status={"NEWS": "UNKNOWN", "MACRO": "COMPLETE"},
    )
    binding = _bind(archive)
    expected_context = as_of_context(archive, SYMBOL, CUT, REQS)

    assert binding.source_consistency_ready is False
    assert binding.context_sha256 == expected_context["context_sha256"]
    assert not [v for v in binding.selected_versions if v.kind == "NEWS"]
    assert [v.kind for v in binding.selected_versions] == ["MACRO"]


def test_publication_only_blocker_suppresses_news_selection_despite_exact_version():
    publication_only = replace(
        _version("NEWS", "official-news", proof_kind="PUBLICATION_ONLY"),
        record_id="news-publication-only",
    )
    archive = _archive(
        versions=(publication_only, *_complete_versions()),
        coverage_status="COMPLETE",
    )
    binding = _bind(archive)
    expected_context = as_of_context(archive, SYMBOL, CUT, REQS)

    assert binding.source_consistency_ready is False
    assert binding.context_sha256 == expected_context["context_sha256"]
    assert not [v for v in binding.selected_versions if v.kind == "NEWS"]
    assert [v.kind for v in binding.selected_versions] == ["MACRO"]


def test_source_receipt_window_cut_and_hash_roster_mismatches_fail_closed():
    wrong_window = _receipt("NEWS", "official-news", "2" * 64)
    wrong_window = replace(wrong_window, window_id="other-window")
    with pytest.raises(ValueError, match="frozen sample/symbol/cut"):
        _bind(_archive(), context=(wrong_window, _receipt("MACRO", "official-macro", "3" * 64)))

    with pytest.raises(ValueError, match="outside its exact frozen window"):
        _bind(_archive(), cut=CUT + 2_000_000)

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        _bind(
            _archive(),
            context=(
                _receipt("NEWS", "official-news", "not-a-hash"),
                _receipt("MACRO", "official-macro", "3" * 64),
            ),
        )

    with pytest.raises(ValueError, match="outside frozen required-source roster"):
        _bind(
            _archive(),
            context=(
                _receipt("NEWS", "unplanned-news", "2" * 64),
                _receipt("MACRO", "official-macro", "3" * 64),
            ),
        )


def test_actual_receive_after_package_capture_is_rejected():
    receipt = _receipt("NEWS", "official-news", "2" * 64, observed=CAPTURED + 1)
    with pytest.raises(ValueError, match="receive clock cannot follow"):
        receipt.validate()


def test_canonical_roundtrip_binds_exact_clocks_and_derived_deny_state():
    binding = _bind(_archive(versions=_complete_versions()))
    encoded = binding.to_json()
    restored = binding_from_json(encoded)

    assert restored == binding
    assert restored.receipt_sha256 == binding.receipt_sha256
    document = json.loads(encoded)
    document["provider_dispatch_authorized"] = True
    forged = canonical(document)
    with pytest.raises(ValueError, match="receipt hash"):
        binding_from_json(forged)


def test_rehashed_capsule_cannot_drop_mandatory_market_snapshot_receipt():
    binding = _bind(_archive())
    document = json.loads(binding.to_json())
    document["source_receipts"] = [
        receipt for receipt in document["source_receipts"] if receipt["source_kind"] != "MARKET_SNAPSHOT"
    ]
    payload = {key: value for key, value in document.items() if key != "receipt_sha256"}
    document["receipt_sha256"] = digest(payload)

    with pytest.raises(ValueError):
        binding_from_json(canonical(document))


def test_binding_api_has_no_provider_or_network_callback_surface():
    calls = []
    signature = inspect.signature(bind_historical_four_arm_slot_v1)
    assert "provider" not in signature.parameters
    assert "transport" not in signature.parameters
    with pytest.raises(TypeError):
        _bind(_archive(), provider=lambda: calls.append("called"))
    assert calls == []
