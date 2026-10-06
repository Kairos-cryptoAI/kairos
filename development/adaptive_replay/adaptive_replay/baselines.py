"""Fixed legacy sleeves adapted to the bounded adaptive replay input boundary.

This module reuses registered native candidates unchanged.  It does not tune
their configurations, normalize their exits, or imply strategy approval.
"""

from __future__ import annotations

import time
from dataclasses import asdict, is_dataclass
from typing import Any

from kairos_strategy.models import SleeveIntent
from kairos_strategy.provenance import installed_source_tree_sha256
from kairos_strategy.registry import generate_sleeve_intents, get_strategy
from kairos_strategy.sleeves import RangeMeanReversionConfig, TrendBreakoutConfig

from .inputs import UNIVERSE, WindowInputs

MINUTE_MS = 60_000
HOUR_MS = 60 * MINUTE_MS
FIVE_MINUTES_MS = 5 * MINUTE_MS
WARMUP_MS = 54 * HOUR_MS
BASELINE_IDS = ("trend_breakout_v1", "range_mean_reversion_v1")
_PRIORITY = {strategy_id: index for index, strategy_id in enumerate(BASELINE_IDS)}


def baseline_configs() -> dict[str, object]:
    """Return the two preselected, unmodified native default configurations."""

    return {
        "trend_breakout_v1": TrendBreakoutConfig(),
        "range_mean_reversion_v1": RangeMeanReversionConfig(),
    }


def baseline_identities() -> dict[str, dict[str, Any]]:
    """Bind fixed defaults to the installed registry source and status."""

    identities: dict[str, dict[str, Any]] = {}
    for strategy_id, config in baseline_configs().items():
        definition = get_strategy(strategy_id)
        if not is_dataclass(config) or isinstance(config, type):
            raise TypeError("baseline configurations must be dataclass instances")
        identities[strategy_id] = {
            "revision": definition.revision,
            "config": asdict(config),
            "fingerprint": config.fingerprint,
            "installed_source_tree_sha256": installed_source_tree_sha256(definition.source_files),
            "registry_status": definition.status.value,
        }
    return identities


def _check_deadline(deadline: float, strategy_id: str, symbol: str, stage: str) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError(f"baseline replay deadline reached: {strategy_id}/{symbol}/{stage}")


def _invoke(
    strategy_id: str,
    candles: list[Any],
    config: object,
    deadline: float,
    symbol: str,
    stage: str,
) -> tuple[SleeveIntent, ...]:
    _check_deadline(deadline, strategy_id, symbol, f"before_{stage}")
    generated = generate_sleeve_intents(strategy_id, candles, config)
    _check_deadline(deadline, strategy_id, symbol, f"after_{stage}")
    return tuple(generated)


def _ids_through(intents: tuple[SleeveIntent, ...] | list[SleeveIntent], cut_ms: int) -> tuple[str, ...]:
    return tuple(sorted(intent.intent_id for intent in intents if intent.decision_ts_ms <= cut_ms - 1))


def _validate_candidate(intent: SleeveIntent, strategy_id: str, start_ms: int, end_ms: int) -> bool:
    if intent.sleeve_id != strategy_id:
        raise ValueError(f"{strategy_id} emitted an intent with a different sleeve id")
    eligible = intent.entry_eligible_ts_ms
    if intent.decision_ts_ms != eligible - 1 or eligible % FIVE_MINUTES_MS != 0:
        raise ValueError(f"{strategy_id} emitted an intent off its native five-minute decision cut")
    return start_ms <= eligible < end_ms


def generate_baseline_tapes(
    inputs: WindowInputs,
    deadline: float,
) -> tuple[dict[str, dict[int, list[SleeveIntent]]], dict[str, Any]]:
    """Generate and prefix-check native baseline intents for scoring-window slots.

    The generator gets one canonical expanding 1m prefix beginning exactly 54h
    before ``inputs.start_ms`` and ending at ``inputs.end_ms``. Loader-added
    date-rounding bars and the replay's exit tail are excluded. Prefix replay at
    the fixed +24h/+48h cuts verifies causality; native intents remain untouched.
    """

    if inputs.end_ms <= inputs.start_ms:
        raise ValueError("baseline scoring window must be non-empty")
    prefix_start = inputs.start_ms - WARMUP_MS
    score_cuts = tuple(
        cut for cut in (inputs.start_ms + 24 * HOUR_MS, inputs.start_ms + 48 * HOUR_MS) if cut < inputs.end_ms
    )
    score_cuts = (*score_cuts, inputs.end_ms)
    configs = baseline_configs()
    tapes: dict[str, dict[int, list[SleeveIntent]]] = {strategy_id: {} for strategy_id in BASELINE_IDS}
    evidence: dict[str, Any] = {
        "protocol": "NATIVE_EXPANDING_PREFIX_V1",
        "prefix_start_ms": prefix_start,
        "score_start_ms": inputs.start_ms,
        "score_end_exclusive_ms": inputs.end_ms,
        "warmup_hours": 54,
        "exit_tail_used": False,
        "prefix_semantics": (
            "Native EMA/Wilder state initializes on the exact 54h prefix; this differs from "
            "adaptive's rolling 54h decision window."
        ),
        "scoring_cuts_ms": list(score_cuts),
        "baselines": {},
    }

    for strategy_id, config in configs.items():
        per_strategy: dict[str, Any] = {"symbols": {}, "scoring_intents": 0}
        for symbol in UNIVERSE:
            rows = tuple(inputs.bars[symbol])
            prefix = tuple(row for row in rows if prefix_start <= row.open_time_ms < inputs.end_ms)
            if not prefix or prefix[0].open_time_ms != prefix_start:
                raise ValueError(f"{symbol} lacks the exact 54h baseline prefix start")
            if any(
                left.open_time_ms + MINUTE_MS != right.open_time_ms
                for left, right in zip(prefix, prefix[1:], strict=False)
            ):
                raise ValueError(f"{symbol} has a gap in the baseline expanding prefix")
            if prefix[-1].open_time_ms != inputs.end_ms - MINUTE_MS:
                raise ValueError(f"{symbol} lacks the complete baseline prefix through the scoring end")

            full = _invoke(strategy_id, list(prefix), config, deadline, symbol, "full_prefix")
            for cut_ms in score_cuts:
                cut_prefix = tuple(row for row in prefix if row.open_time_ms < cut_ms)
                at_cut = _invoke(strategy_id, list(cut_prefix), config, deadline, symbol, f"prefix_{cut_ms}")
                if _ids_through(full, cut_ms) != _ids_through(at_cut, cut_ms):
                    raise ValueError(
                        f"{strategy_id}/{symbol} prefix mutation detected at scoring cut {cut_ms}"
                    )

            accepted = 0
            for intent in full:
                if intent.symbol != symbol:
                    raise ValueError(f"{strategy_id} generated an intent under the wrong symbol input")
                if not _validate_candidate(intent, strategy_id, inputs.start_ms, inputs.end_ms):
                    continue
                tapes[strategy_id].setdefault(intent.entry_eligible_ts_ms, []).append(intent)
                accepted += 1
            per_strategy["symbols"][symbol] = {
                "prefix_bar_count": len(prefix),
                "full_prefix_intent_count": len(full),
                "scoring_intent_count": accepted,
                "verified_prefix_cuts_ms": list(score_cuts),
            }
            per_strategy["scoring_intents"] += accepted
        for _eligible_ms, intents in tapes[strategy_id].items():
            intents.sort(key=lambda item: (UNIVERSE.index(item.symbol), item.intent_id))
        evidence["baselines"][strategy_id] = per_strategy
    evidence["identities"] = baseline_identities()
    return tapes, evidence


def combine_tapes(
    tapes: dict[str, dict[int, list[SleeveIntent]]],
) -> tuple[dict[int, list[SleeveIntent]], dict[str, int]]:
    """Combine fixed family tapes with one candidate per symbol and eligible cut."""

    unknown = set(tapes) - set(BASELINE_IDS)
    if unknown:
        raise ValueError(f"unknown baseline tape ids: {', '.join(sorted(unknown))}")
    grouped: dict[tuple[int, str], list[SleeveIntent]] = {}
    for strategy_id, tape in tapes.items():
        for eligible_ms, intents in tape.items():
            for intent in intents:
                if intent.sleeve_id != strategy_id or intent.entry_eligible_ts_ms != eligible_ms:
                    raise ValueError("baseline tape key does not match its native intent")
                if intent.symbol not in UNIVERSE:
                    raise ValueError(f"unsupported baseline symbol: {intent.symbol}")
                grouped.setdefault((eligible_ms, intent.symbol), []).append(intent)

    union: dict[int, list[SleeveIntent]] = {}
    stats = {
        "candidate_count": 0,
        "kept_count": 0,
        "same_direction_collisions": 0,
        "opposite_direction_conflicts": 0,
    }
    for (eligible_ms, symbol), candidates in grouped.items():
        stats["candidate_count"] += len(candidates)
        if any(intent.symbol != symbol for intent in candidates):
            raise ValueError("baseline tape symbol key does not match its native intent")
        sides = {intent.side for intent in candidates}
        if len(sides) > 1:
            stats["opposite_direction_conflicts"] += 1
            continue
        candidates.sort(key=lambda item: (_PRIORITY.get(item.sleeve_id, len(_PRIORITY)), item.intent_id))
        chosen = candidates[0]
        stats["same_direction_collisions"] += len(candidates) - 1
        union.setdefault(eligible_ms, []).append(chosen)
        stats["kept_count"] += 1
    for intents in union.values():
        intents.sort(key=lambda item: (UNIVERSE.index(item.symbol), item.intent_id))
    return union, stats
