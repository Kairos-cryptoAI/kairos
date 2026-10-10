"""Offline isolation/causality tests: do not connect to providers or databases."""

import importlib.util
from dataclasses import dataclass
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "market_comparison", Path(__file__).with_name("run_comparison.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@dataclass
class Bar:
    open_time_ms: int
    close_time_ms: int
    open: float = 10
    high: float = 12
    low: float = 9
    close: float = 11
    volume: float = 100


def test_complete_context_masks_price_and_calendar():
    bars = [Bar(i * 60_000, (i + 1) * 60_000 - 1) for i in range(15)]
    actual = module.frames(bars, 5, bars[-1].close_time_ms, count=3)
    assert len(actual) == 3
    assert actual[-1]["ohlc"][-1] == 100
    assert actual[-1]["age_seconds"] == 0
    assert not any("time_ms" in key for row in actual for key in row)


def test_future_bar_is_not_silently_accepted():
    bars = [Bar(i * 60_000, (i + 1) * 60_000 - 1) for i in range(15)]
    with pytest.raises(ValueError, match="future"):
        module.frames(bars, 5, bars[-2].close_time_ms, count=2)


def test_partial_frame_not_promoted():
    bars = [Bar(i * 60_000, (i + 1) * 60_000 - 1) for i in range(14)]
    actual = module.frames(bars, 5, bars[-1].close_time_ms, count=2)
    assert actual[-1]["age_seconds"] == 240
    with pytest.raises(ValueError, match="insufficient"):
        module.frames(bars, 5, bars[-1].close_time_ms, count=3)


def valid_review():
    return {
        "candidate_id": "a",
        "prompt_sha256": "x",
        "decision": "VETO",
        "state": "OBSERVED_COMMITTED",
        "model": "gpt-6-luna",
        "effort": "medium",
        "actual_microusd": 100,
        "measured_pipeline_duration_ms": 50,
        "modern_attempt_started_ms": 100,
        "modern_response_observed_ms": 150,
        "modern_adapter_finished_ms": 155,
    }


def test_veto_cost_is_known_not_free():
    assert (
        module.validate_reviews(
            [{"candidate_id": "a", "prompt_sha256": "x"}], [valid_review()]
        )["a"]["actual_microusd"]
        == 100
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"actual_microusd": None},
        {"state": "FAILED_CLOSED"},
        {"prompt_sha256": "wrong"},
        {"decision": "BUY"},
        {"measured_pipeline_duration_ms": 0},
        {"modern_response_observed_ms": 99},
    ],
)
def test_unknown_cost_or_bad_identity_clock_never_completes(mutation):
    with pytest.raises(ValueError):
        module.validate_reviews(
            [{"candidate_id": "a", "prompt_sha256": "x"}],
            [{**valid_review(), **mutation}],
        )


def test_duplicate_review_denied():
    with pytest.raises(ValueError, match="unique"):
        module.validate_reviews(
            [{"candidate_id": "a", "prompt_sha256": "x"}],
            [valid_review(), valid_review()],
        )
