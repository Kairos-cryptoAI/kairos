from __future__ import annotations

import hashlib

import pytest

from adaptive_replay.matched import MatchedSlot, ReviewReceipt, preparation_report

SHA = "a" * 64


def _slot(candidate: str | None = SHA) -> MatchedSlot:
    return MatchedSlot(SHA, 10_000, 10_000, "b" * 64, candidate, "c" * 64)


def _receipt(**overrides: object) -> ReviewReceipt:
    values: dict[str, object] = {
        "slot": _slot(),
        "candidate_id": SHA,
        "requested_ms": 10_001,
        "completed_ms": 10_002,
        "captured_ms": 10_003,
        "result": "ALLOW",
        "provider": "OPENAI",
        "model": "approved-model",
        "cost_usd": 0.01,
        "evidence_kind": "OBSERVED_POINT_IN_TIME",
        "point_in_time_news_sha256": "d" * 64,
        "raw_response_sha256": "e" * 64,
    }
    values.update(overrides)
    return ReviewReceipt(**values)  # type: ignore[arg-type]


def test_absent_arms_are_null_not_a_matched_ab_result() -> None:
    report = preparation_report("a" * 64, 20, 3, 17)
    assert report["matched_ab_executed"] is False
    assert report["arms"]["review"]["status"] == "NOT_CALLED"
    assert report["arms"]["review"]["economic_results"] is None
    assert report["arms"]["proposals"]["economic_results"] is None
    assert report["arms"]["review"]["paired_to_baseline"] is False
    assert report["quiet_slots_included"] == 17


def test_unavailable_or_error_slots_are_not_silent_quiet_slots() -> None:
    report = preparation_report(SHA, 20, 3, 12)
    assert report["quiet_slots_included"] == 12
    assert report["unavailable_or_nondecision_slots"] == 5
    assert preparation_report(SHA, 20, 3)["quiet_slots_included"] is None


def test_review_cannot_change_selected_candidate() -> None:
    with pytest.raises(ValueError, match="cannot invent or modify"):
        _receipt(candidate_id="f" * 64)


def test_matched_context_cannot_include_future_cut() -> None:
    with pytest.raises(ValueError, match="never future bars"):
        MatchedSlot(SHA, 10_000, 10_001, "b" * 64, SHA, "c" * 64)


@pytest.mark.parametrize(
    "clock",
    [
        {"requested_ms": 9_999},
        {"completed_ms": 10_000},
        {"captured_ms": 10_001},
    ],
)
def test_review_clocks_cannot_be_backdated(clock: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="backdated"):
        _receipt(**clock)


def test_fixture_receipt_cannot_become_economic_completion() -> None:
    fixture = _receipt(evidence_kind="TEST_FIXTURE")
    with pytest.raises(ValueError, match="fixtures cannot become observed"):
        fixture.execution_completion()


def test_receipt_accepts_only_actual_digest_shaped_evidence() -> None:
    with pytest.raises(ValueError, match="identity required"):
        _receipt(raw_response_sha256=hashlib.sha256(b"placeholder").hexdigest()[:-1])
