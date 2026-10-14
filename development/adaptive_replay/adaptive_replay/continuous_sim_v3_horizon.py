"""One bounded, fixed five-day prospective V3 research portfolio per arm.

This additive path never increases old V2 limits or creates daily accounts.
Every source item inside a bounded batch executes the original financial fold,
in retained-availability order; batching is persistence, not price sampling.
Admission/decision boundaries are caller obligations: a batch cannot be used
to backdate a subsequent intake. The full 36,000-cell denominator is explicit.
Retained normalized originals and public-book mappings establish consistency,
not accepted historical NEWS/MACRO/BBO, provider execution or source authenticity.
No source/model/venue calls, forced close, strategy change or qualified economics.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from decimal import Context, Decimal, localcontext
from pathlib import Path
from types import MappingProxyType

from kairos_execution.simulation.models import AcceptedBookFrame, FillAssumptions, LiquidityState

from . import adaptive_sim_account as account_api
from .candle_originals_v3 import RetainedCandleV3
from .continuous_sim import (
    EVIDENCE,
    MAX_EXIT_ATTEMPTS,
    MAX_PARENTS,
    UNIVERSE,
    ClosedCandleInput,
    ContinuousSimPortfolio,
    FundingSchedule,
    SimInputError,
    SymbolRules,
    TapeInput,
    _available,
    _id,
    _implementation,
    _input_doc,
    _json,
    _ms,
    _plain,
    _sha,
)
from .historical_context import _json as parse_original_json
from .historical_context import canonical, digest
from .public_book_capture import MAX_RAW_TOTAL
from .sim_account_codec import MAX_BYTES as MAX_ACCOUNT_DOCUMENT_BYTES
from .sim_account_codec import decode_account, encode_account
from .sim_book_tape import PublicBookTape
from .sim_delta_journal_v3 import (
    DEFAULT_MAX_DATABASE_BYTES,
    DEFAULT_MAX_EVENT_ROWS,
    MAX_EVENT_BYTES,
    MAX_STATE_BYTES,
    SimDeltaJournalV3,
)
from .sim_state_journal import JournalIdentity

MINUTE = 60_000
FIVE_DAYS = 5 * 86_400_000
MAX_INPUTS = 900_000
MAX_ORIGINALS = 300_000
MAX_ORIGINAL_BYTES = 512 * 1024 * 1024
# Native segments are at most 120 seconds: five days alone can need >=3600.
# The independent input cap still refuses high-frequency feeds that exceed it;
# this is NOT a promise to accommodate arbitrary native 100-ms depth streams.
MAX_SEGMENTS = 8192
MAX_PUBLIC_ORIGINAL_BYTES = 512 * 1024 * 1024
MAX_NORMALIZED_INPUT_BYTES = 512 * 1024 * 1024
MAX_BATCH = 500
HORIZON_ID = "kairos.research.continuous-sim-fixed-five-day.v3"


@dataclass(frozen=True)
class FiveDayHorizonV3:
    entry_start_ms: int
    retained_end_ms: int
    data_start_ms: int

    def __post_init__(self):
        for value in (self.entry_start_ms, self.retained_end_ms, self.data_start_ms):
            _ms(value)
        if (
            self.entry_start_ms % MINUTE
            or self.retained_end_ms % MINUTE
            or self.data_start_ms % MINUTE
            or not max(0, self.entry_start_ms - 35 * 86_400_000) <= self.data_start_ms <= self.entry_start_ms
            or not self.entry_end_ms <= self.retained_end_ms <= self.entry_end_ms + 3 * 3_600_000
        ):
            raise SimInputError("fixed five days, bounded warmup and presealed natural-exit tail required")

    @property
    def entry_end_ms(self):
        return self.entry_start_ms + FIVE_DAYS

    @property
    def minutes(self):
        return tuple(range(self.entry_start_ms, self.entry_end_ms, MINUTE))


@dataclass(frozen=True)
class PublicSegmentOriginalV3:
    """Exact already-retained bytes; this never loads or authenticates a feed.

    The existing public loader must have audited this segment. These originals
    additionally establish an honest aggregate byte budget and cannot replace
    a real original with a caller's declared byte length or sampled frame list.
    """

    receipt_bytes: bytes
    received_raw_bytes: bytes

    def __post_init__(self):
        if (
            type(self.receipt_bytes) is not bytes
            or not 1 <= len(self.receipt_bytes) <= 1024 * 1024
            or type(self.received_raw_bytes) is not bytes
            or not 1 <= len(self.received_raw_bytes) <= MAX_RAW_TOTAL * 3
        ):
            raise SimInputError("bounded exact original public receipt/raw bytes required")

    @property
    def byte_count(self):
        return len(self.receipt_bytes) + len(self.received_raw_bytes)

    @property
    def commitment(self):
        return {
            "receipt": hashlib.sha256(self.receipt_bytes).hexdigest(),
            "raw": hashlib.sha256(self.received_raw_bytes).hexdigest(),
            "bytes": self.byte_count,
        }

    def validate(self, segment):
        receipt = parse_original_json(self.receipt_bytes)
        if (
            type(receipt) is not dict
            or (canonical(receipt) + "\n").encode("utf-8") != self.receipt_bytes
            or self.commitment["receipt"] != segment.receipt_sha256
            or self.commitment["raw"] != receipt.get("raw_file_sha256")
            or receipt.get("source_sha256") != segment.source_sha256
            or receipt.get("epoch") != segment.epoch
            or receipt.get("state") != "CAPTURED"
            or receipt.get("observed_stream_check") != "PASS"
            or type(receipt.get("admitted_frames")) is not int
            or receipt["admitted_frames"] != len(segment.frames)
            or receipt.get("observed_messages") != len(segment.frames)
        ):
            raise SimInputError("exact public original receipt/segment identity conflict")
        lines = self.received_raw_bytes.splitlines(keepends=True)
        if len(lines) != len(segment.frames):
            raise SimInputError("cannot omit any original received public record")
        prior, payload_bytes = None, 0
        for sequence, (line, bound) in enumerate(zip(lines, segment.frames, strict=True), 1):
            row = parse_original_json(line)
            fields = {
                "sequence",
                "previous_record_sha256",
                "received_ms",
                "received_monotonic_ns",
                "raw_payload",
                "raw_payload_sha256",
                "record_sha256",
            }
            if type(row) is not dict or set(row) != fields or (canonical(row) + "\n").encode() != line:
                raise SimInputError("canonical full original public record required")
            _ms(row["received_ms"])
            _ms(row["received_monotonic_ns"])
            if type(row["raw_payload"]) is not str:
                raise SimInputError("exact original public payload text required")
            payload = row["raw_payload"].encode("utf-8")
            payload_bytes += len(payload)
            if (
                type(row["sequence"]) is not int
                or row["sequence"] != sequence
                or row["previous_record_sha256"] != prior
                or digest({k: v for k, v in row.items() if k != "record_sha256"}) != row["record_sha256"]
                or row["record_sha256"] != bound.raw_record_sha256
                or row["received_ms"] != bound.frame.received_at_ms
                or hashlib.sha256(payload).hexdigest() != row["raw_payload_sha256"]
                or row["raw_payload_sha256"] != bound.frame.raw_payload_sha256
                or payload_bytes > MAX_RAW_TOTAL
            ):
                raise SimInputError("public original record/payload/mapping conflict")
            prior = row["record_sha256"]
        if (
            prior != receipt.get("raw_head_sha256")
            or type(receipt.get("raw_payload_bytes")) is not int
            or payload_bytes != receipt["raw_payload_bytes"]
        ):
            raise SimInputError("complete public original byte/terminal commitment conflict")


@dataclass(frozen=True)
class HorizonTapeBindingV3:
    """Complete retained roster, including every original public segment frame.

    Segment hashes are caller-supplied independent commitments, never discovered
    from mutable files here. Rebasing preserves native mapping hashes and cannot
    splice different source epochs into one liquid session. Sparse fixtures are
    mechanical tests; nonfixtures retain the original five-second continuity
    bound, including source startup/tail checks in portfolio configuration. A
    continuity bound is not a cadence claim. All original frames must fit the
    independently bounded roster or construction fails, never samples it.
    """

    source_id: str
    tape_id: str
    stream_epoch: str
    quote_source_id: str
    evidence_kind: str
    inputs: tuple[TapeInput, ...]
    book_segments: tuple[PublicBookTape, ...] = ()
    expected_segment_sha256s: tuple[str, ...] = ()
    segment_originals: tuple[PublicSegmentOriginalV3, ...] = ()
    _normalized_bytes: int = field(init=False, compare=False, repr=False)

    def __post_init__(self):
        for value in (self.source_id, self.tape_id, self.stream_epoch, self.quote_source_id):
            _id(value)
        if (
            self.evidence_kind not in EVIDENCE
            or type(self.inputs) is not tuple
            or not 1 <= len(self.inputs) <= MAX_INPUTS
        ):
            raise SimInputError("bounded exact full-horizon source roster required")
        if any(
            type(v) is not tuple
            for v in (
                self.book_segments,
                self.expected_segment_sha256s,
                self.segment_originals,
            )
        ):
            raise SimInputError("exact immutable public segment commitments required")
        if self.evidence_kind == "TEST_FIXTURE":
            if self.book_segments or self.expected_segment_sha256s or self.segment_originals:
                raise SimInputError("fixture cannot impersonate retained public originals")
        elif (
            not 1 <= len(self.book_segments) <= MAX_SEGMENTS
            or len(self.book_segments) != len(self.expected_segment_sha256s)
            or len(self.book_segments) != len(self.segment_originals)
        ):
            raise SimInputError("nonfixture requires complete independently pinned public segments")
        if (
            any(type(v) is not PublicSegmentOriginalV3 for v in self.segment_originals)
            or sum(v.byte_count for v in self.segment_originals) > MAX_PUBLIC_ORIGINAL_BYTES
        ):
            raise SimInputError("aggregate original public segment bytes exceed resource bound")
        if any(type(v) is not PublicBookTape for v in self.book_segments) or sum(
            len(v.frames) for v in self.book_segments
        ) > len(self.inputs):
            raise SimInputError("full public frame roster exceeds bounded input capacity")
        prior_at, books, per_symbol, candles, normalized_bytes = -1, [], {}, {}, 1
        for sequence, item in enumerate(self.inputs, 1):
            if (
                type(item) is not TapeInput
                or item.global_sequence != sequence
                or _available(item.value) < prior_at
            ):
                raise SimInputError("full consecutive available source prefix required")
            value, prior_at = item.value, _available(item.value)
            document = value.model_dump(mode="json") if type(value) is AcceptedBookFrame else asdict(value)
            normalized_bytes += len(_json(document).encode("utf-8")) + 1
            if normalized_bytes > MAX_NORMALIZED_INPUT_BYTES:
                raise SimInputError("aggregate complete normalized source bytes exceed resource bound")
            if type(value) is AcceptedBookFrame:
                AcceptedBookFrame.model_validate(value)
                if (
                    value.symbol not in UNIVERSE
                    or value.tape_id != self.tape_id
                    or value.stream_epoch != self.stream_epoch
                ):
                    raise SimInputError("source physical tape/epoch conflict")
                previous = per_symbol.get(value.symbol)
                if previous is not None and (
                    value.sequence <= previous.sequence
                    or value.exchange_update_id <= previous.exchange_update_id
                    or value.exchange_at_ms < previous.exchange_at_ms
                    or value.received_at_ms < previous.received_at_ms
                    or self.evidence_kind != "TEST_FIXTURE"
                    and max(
                        value.exchange_at_ms - previous.exchange_at_ms,
                        value.received_at_ms - previous.received_at_ms,
                    )
                    > 5000
                ):
                    raise SimInputError("cross-segment physical order/continuity conflict")
                per_symbol[value.symbol] = value
                books.append(value)
            else:
                if value.evidence_kind != self.evidence_kind:
                    raise SimInputError("mixed source evidence classes forbidden")
                if type(value) is ClosedCandleInput:
                    if value.open_at_ms <= candles.get(value.symbol, -1):
                        raise SimInputError("closed candle order/duplicate conflict")
                    candles[value.symbol] = value.open_at_ms
        if self.book_segments and sum(len(v.frames) for v in self.book_segments) != len(books):
            raise SimInputError("cannot sample or omit any retained public original frame")
        ordinal = 0
        for segment, commitment, original in zip(
            self.book_segments, self.expected_segment_sha256s, self.segment_originals, strict=True
        ):
            _sha(commitment)
            if segment.sha256 != commitment:
                raise SimInputError("complete original public segment differs from external commitment")
            if segment.epoch != self.stream_epoch or segment.quote_source_id != self.quote_source_id:
                raise SimInputError("cannot splice physical epochs or quote source policies")
            original.validate(segment)
            for bound in segment.frames:
                expected = AcceptedBookFrame.model_validate(
                    bound.frame.model_dump(mode="python") | {"tape_id": self.tape_id, "sequence": ordinal + 1}
                )
                if books[ordinal] != expected:
                    raise SimInputError("cannot sample or rewrite any retained public original frame")
                ordinal += 1
        object.__setattr__(self, "_normalized_bytes", normalized_bytes)

    @property
    def mapping_sha256(self):
        return digest(
            {
                "schema": HORIZON_ID,
                "source": self.source_id,
                "tape": self.tape_id,
                "epoch": self.stream_epoch,
                "quote": self.quote_source_id,
                "evidence": self.evidence_kind,
                "segments": self.expected_segment_sha256s,
                "original_bytes": [v.commitment for v in self.segment_originals],
                "normalized_bytes": self._normalized_bytes,
                "inputs": [_input_doc(item) for item in self.inputs],
            }
        )


@dataclass(frozen=True)
class HorizonCandleOriginalsV3:
    records: tuple[RetainedCandleV3, ...]
    _index: object = field(init=False, compare=False, repr=False)

    def __post_init__(self):
        if type(self.records) is not tuple or not 1 <= len(self.records) <= MAX_ORIGINALS:
            raise SimInputError("bounded immutable full-horizon originals required")
        index, prior, evidence_kind = {}, None, None
        for record in self.records:
            if type(record) is not RetainedCandleV3:
                raise SimInputError("exact retained normalized candle record required")
            RetainedCandleV3(record.candle, record.evidence, record.available_at_ms, record.evidence_kind)
            key = record.candle.symbol, record.candle.open_time_ms
            if prior is not None and key <= prior or evidence_kind not in {None, record.evidence_kind}:
                raise SimInputError("canonical unique originals and uniform evidence class required")
            index[key], prior, evidence_kind = record, key, record.evidence_kind
        if len(_json([asdict(record) for record in self.records]).encode("utf-8")) > MAX_ORIGINAL_BYTES:
            raise SimInputError("full retained normalized original bytes exceed bound")
        object.__setattr__(self, "_index", MappingProxyType(index))

    @property
    def sha256(self):
        return digest([asdict(record) for record in self.records])

    def find(self, candle, evidence, at_ms):
        _ms(at_ms)
        record = self._index.get((candle.symbol, candle.open_time_ms))
        if (
            record is None
            or digest(asdict(record.candle)) != digest(asdict(candle))
            or record.evidence != evidence
        ):
            raise SimInputError("exact full candle/source receipt not in retained horizon originals")
        if record.available_at_ms > at_ms:
            raise SimInputError("full original not yet available at supplied causal input clock")
        return record

    def validate_binding(self, binding):
        if (
            type(binding) is not HorizonTapeBindingV3
            or binding.evidence_kind != self.records[0].evidence_kind
        ):
            raise SimInputError("exact horizon source binding with matching evidence required")
        for item in binding.inputs:
            value = item.value
            if type(value) is not ClosedCandleInput:
                continue
            record = self._index.get((value.symbol, value.open_at_ms))
            if record is None or (
                value.close_at_ms != record.candle.close_time_ms
                or value.available_at_ms != record.available_at_ms
                or value.close != Decimal(str(record.candle.close))
                or value.source_id != record.evidence.source_id
                or value.source_payload_sha256 != record.evidence.payload_sha256
            ):
                raise SimInputError("source candle differs from retained full original")


@dataclass(frozen=True)
class NoRouteDecisionV3:
    """Driver-verified native decision; this records, never chooses arbitration.

    Combined conflict/priority dispositions require the independently frozen V3
    driver seal (conflict abstains, technical priority, veto has no fallback).
    They never assert equivalence to any static combined strategy.
    """

    parent_id: str
    symbol: str
    origin: str
    actual_decision_ms: int
    producer_seal_sha256: str
    producer_head_sha256: str
    native_sequence: int
    native_chain_sha256: str
    native_receipt_sha256: str
    plan_sha256: str
    native_reason: str
    disposition_reason: str
    driver_seal_sha256: str
    coverage: str = "AVAILABLE"

    def __post_init__(self):
        _id(self.parent_id)
        _id(self.native_reason)
        _ms(self.actual_decision_ms)
        for value in (
            self.producer_seal_sha256,
            self.producer_head_sha256,
            self.native_chain_sha256,
            self.native_receipt_sha256,
            self.plan_sha256,
            self.driver_seal_sha256,
        ):
            _sha(value)
        if (
            self.symbol not in UNIVERSE
            or self.origin not in {"TECHNICAL", "CONTEXT_PROPOSAL"}
            or type(self.native_sequence) is not int
            or self.native_sequence <= 0
            or self.coverage != "AVAILABLE"
            or self.disposition_reason
            not in {
                "ORIGIN_NOT_ROUTED",
                "ARBITRATION_CONFLICT",
                "TECHNICAL_PRIORITY",
            }
        ):
            raise SimInputError("exact known native no-route decision required")


class ContinuousSimV3Horizon(ContinuousSimPortfolio):
    """Existing financial reducer, one durable delta account over all five days."""

    @staticmethod
    def preflight_parent_roster(*, parent_ids, expected_roster_sha256):
        """Capacity check, not an assertion that a caller's roster is exhaustive.

        The matched driver must derive and freeze ALL routed native CONSUMED
        first receipts (including refusals) on actual in-window decision clocks.
        It must reject incomplete/unknown inventory before any comparison.
        """
        _sha(expected_roster_sha256)
        if (
            type(parent_ids) is not tuple
            or parent_ids != tuple(sorted(set(parent_ids)))
            or len(parent_ids) > MAX_PARENTS
        ):
            raise SimInputError("complete fixed native first-receipt roster exceeds parent capacity")
        for parent_id in parent_ids:
            _id(parent_id)
        if digest(parent_ids) != expected_roster_sha256:
            raise SimInputError("fixed native first-receipt roster differs from independent commitment")
        return expected_roster_sha256

    @staticmethod
    def _horizon_config(
        *,
        binding,
        models,
        rules,
        funding,
        arm_id,
        horizon,
        initial_equity,
        hypothesis_seal_sha256,
        candle_originals,
        allowed_origins,
        maximum_exit_attempts,
        expected_cost_ids,
        no_route_driver_seal_sha256,
        storage,
    ):
        if (
            type(binding) is not HorizonTapeBindingV3
            or type(horizon) is not FiveDayHorizonV3
            or type(candle_originals) is not HorizonCandleOriginalsV3
        ):
            raise SimInputError("separate typed fixed horizon, source roster and originals required")
        FiveDayHorizonV3(**asdict(horizon))
        _id(arm_id)
        _sha(hypothesis_seal_sha256)
        if (
            type(allowed_origins) is not tuple
            or not allowed_origins
            or allowed_origins != tuple(sorted(set(allowed_origins)))
            or not set(allowed_origins) <= {"TECHNICAL", "CONTEXT_PROPOSAL"}
        ):
            raise SimInputError("presealed explicit canonical origin routing required")
        if type(funding) is not FundingSchedule or funding.evidence_kind != binding.evidence_kind:
            raise SimInputError("exact scoped funding schedule required")
        FundingSchedule(**asdict(funding))
        if (
            type(initial_equity) is not Decimal
            or not initial_equity.is_finite()
            or initial_equity <= 0
            or type(maximum_exit_attempts) is not int
            or not 1 <= maximum_exit_attempts <= MAX_EXIT_ATTEMPTS
        ):
            raise SimInputError("unchanged positive capital and bounded exit policy required")
        if set(models) != set(UNIVERSE) or set(rules) != set(UNIVERSE):
            raise SimInputError("all five sealed rules/models required")
        for symbol in UNIVERSE:
            model, rule = models[symbol], rules[symbol]
            if (
                type(model) is not FillAssumptions
                or type(rule) is not SymbolRules
                or rule.symbol != symbol
                or model.price_tick != rule.price_tick
                or model.quantity_step != rule.quantity_step
            ):
                raise SimInputError("exact per-symbol instrument and fill rules required")
        if (
            len({(m.taker_fee_bps, m.adverse_slippage_bps, m.maximum_book_age_ms) for m in models.values()})
            != 1
        ):
            raise SimInputError("unchanged uniform financial mark/cost policy required")
        candle_originals.validate_binding(binding)
        expected = {(symbol, minute) for symbol in UNIVERSE for minute in horizon.minutes}
        actual = set()
        first, last = {}, {}
        for item in binding.inputs:
            value = item.value
            if not horizon.data_start_ms <= _available(value) <= horizon.retained_end_ms:
                raise SimInputError("retained source outside presealed data/exit horizon")
            if (
                type(value) is ClosedCandleInput
                and horizon.entry_start_ms <= value.open_at_ms < horizon.entry_end_ms
            ):
                actual.add((value.symbol, value.open_at_ms))
            if type(value) is AcceptedBookFrame:
                first.setdefault(value.symbol, value.persisted_at_ms)
                last[value.symbol] = value.persisted_at_ms
        if actual != expected:
            raise SimInputError("complete exact 36,000 original five-day candle cells required")
        if binding.evidence_kind != "TEST_FIXTURE" and any(
            symbol not in first
            or first[symbol] > horizon.entry_start_ms + 5000
            or last[symbol] < horizon.retained_end_ms - 5000
            for symbol in UNIVERSE
        ):
            raise SimInputError("complete five-symbol original book startup/tail coverage required")
        if any(
            not horizon.data_start_ms <= due <= horizon.retained_end_ms for _, due in funding.expected_due
        ):
            raise SimInputError("funding liability outside presealed retained horizon")
        if (
            type(expected_cost_ids) is not tuple
            or expected_cost_ids != tuple(sorted(set(expected_cost_ids)))
            or len(expected_cost_ids) > 8192
        ):
            raise SimInputError("bounded canonical presealed expense roster required")
        for cost_id in expected_cost_ids:
            _id(cost_id)
        if no_route_driver_seal_sha256 is not None:
            _sha(no_route_driver_seal_sha256)
        implementation = digest(
            [
                _implementation(),
                hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                hashlib.sha256(
                    Path(SimDeltaJournalV3.create.__func__.__code__.co_filename).read_bytes()
                ).hexdigest(),
            ]
        )
        return {
            "schema": HORIZON_ID,
            "arm": arm_id,
            "hypothesis_contract": "V3",
            "hypothesis_seal_sha256": hypothesis_seal_sha256,
            "candle_originals_sha256": candle_originals.sha256,
            "allowed_origins": list(allowed_origins),
            "tape": binding.mapping_sha256,
            "models": {s: models[s].fingerprint() for s in UNIVERSE},
            "rules": _plain({s: asdict(rules[s]) for s in UNIVERSE}),
            "funding": _plain(asdict(funding)),
            "minutes": list(horizon.minutes),
            "horizon": asdict(horizon),
            "initial_equity": str(initial_equity),
            "maximum_exit_attempts": maximum_exit_attempts,
            "risk_basis": "ENTRY_STOP_RESERVED",
            "implementation": implementation,
            "expected_cost_ids": list(expected_cost_ids),
            "no_route_driver_seal_sha256": no_route_driver_seal_sha256,
            "storage": storage,
            "clock_authority": "RETAINED_AVAILABILITY_MODELED_ORDER_CLOCK_NOT_OBSERVED_EXECUTION",
            "flat_mark_ledger": "OMIT_ONLY_SUCCESSFUL_REDUNDANT_FLAT_MARK_RECORD_AFTER_FULL_REDUCER",
            "source_resource_profile": {
                "policy": "FULL_RETAINED_ROSTER_OR_FAIL_CLOSED_NO_CADENCE_ACCEPTANCE",
                "max_inputs": MAX_INPUTS,
                "max_segments": MAX_SEGMENTS,
                "max_public_original_bytes": MAX_PUBLIC_ORIGINAL_BYTES,
                "public_original_bytes": sum(v.byte_count for v in binding.segment_originals),
                "max_normalized_input_bytes": MAX_NORMALIZED_INPUT_BYTES,
                "normalized_input_bytes": binding._normalized_bytes,
                "max_batch": MAX_BATCH,
                "max_routed_native_first_receipts": MAX_PARENTS,
                "max_account_document_bytes": MAX_ACCOUNT_DOCUMENT_BYTES,
                "account_delta_mode": "OPAQUE_CANONICAL_CODEC_V1_REPLACEMENT",
                "arbitrary_native_feed_capacity": False,
            },
        }

    @classmethod
    def create(
        cls,
        path,
        *,
        campaign_id,
        arm_id,
        binding,
        models,
        rules,
        funding_schedule,
        horizon,
        initial_equity,
        hypothesis_seal_sha256,
        candle_originals,
        allowed_origins,
        maximum_exit_attempts=3,
        expected_cost_ids=(),
        no_route_driver_seal_sha256=None,
        max_event_rows=DEFAULT_MAX_EVENT_ROWS,
        max_event_bytes=MAX_EVENT_BYTES,
        max_state_bytes=MAX_STATE_BYTES,
        max_database_bytes=DEFAULT_MAX_DATABASE_BYTES,
    ):
        _id(campaign_id)
        storage = {
            "max_event_rows": max_event_rows,
            "max_event_bytes": max_event_bytes,
            "max_state_bytes": max_state_bytes,
            "max_database_bytes": max_database_bytes,
        }
        config = cls._horizon_config(
            binding=binding,
            models=models,
            rules=rules,
            funding=funding_schedule,
            arm_id=arm_id,
            horizon=horizon,
            initial_equity=initial_equity,
            hypothesis_seal_sha256=hypothesis_seal_sha256,
            candle_originals=candle_originals,
            allowed_origins=allowed_origins,
            maximum_exit_attempts=maximum_exit_attempts,
            expected_cost_ids=expected_cost_ids,
            no_route_driver_seal_sha256=no_route_driver_seal_sha256,
            storage=storage,
        )
        model = models[UNIVERSE[0]]
        policy = account_api.AccountPolicy(
            rules[UNIVERSE[0]].quantity_step,
            model.taker_fee_bps,
            model.taker_fee_bps,
            model.adverse_slippage_bps,
            model.maximum_book_age_ms,
            "ENTRY_STOP_RESERVED",
        )
        state = {
            "config": config,
            "clock": horizon.data_start_ms,
            "cursor": 0,
            "account": encode_account(account_api.new_account(initial_equity, policy)),
            "latest": {},
            "liquidity": {
                s: LiquidityState(
                    session_id=arm_id, tape_id=binding.tape_id, stream_epoch=binding.stream_epoch, symbol=s
                ).model_dump(mode="json")
                for s in UNIVERSE
            },
            "parents": {},
            "pending": {},
            "slots": {},
            "candles": {},
            "funding": {},
            "service_liabilities": {},
            "terminal": False,
            "last_outcome": None,
        }
        identity = JournalIdentity(campaign_id, binding.source_id, digest(config), config["implementation"])
        journal = SimDeltaJournalV3.create(
            path, identity=identity, initial_state=state, initial_clock_ms=horizon.data_start_ms, **storage
        )
        return cls(journal, binding, models, rules, funding_schedule, config, path, candle_originals)

    @classmethod
    def open(
        cls,
        path,
        *,
        identity,
        expected_checkpoint,
        binding,
        models,
        rules,
        funding_schedule,
        config,
        candle_originals,
    ):
        rebuilt = cls._horizon_config(
            binding=binding,
            models=models,
            rules=rules,
            funding=funding_schedule,
            arm_id=config["arm"],
            horizon=FiveDayHorizonV3(**config["horizon"]),
            initial_equity=Decimal(config["initial_equity"]),
            hypothesis_seal_sha256=config["hypothesis_seal_sha256"],
            candle_originals=candle_originals,
            allowed_origins=tuple(config["allowed_origins"]),
            maximum_exit_attempts=config["maximum_exit_attempts"],
            expected_cost_ids=tuple(config["expected_cost_ids"]),
            no_route_driver_seal_sha256=config["no_route_driver_seal_sha256"],
            storage=config["storage"],
        )
        if rebuilt != config:
            raise SimInputError("fixed horizon/source/cost/implementation configuration drift")
        journal = SimDeltaJournalV3.open(
            path, identity=identity, expected_checkpoint=expected_checkpoint, **config["storage"]
        )
        if journal.snapshot().state["config"] != config:
            journal.close()
            raise SimInputError("durable horizon configuration conflict")
        return cls(journal, binding, models, rules, funding_schedule, config, path, candle_originals)

    def _require_v3_originals(self):
        if (
            type(self.candle_originals) is not HorizonCandleOriginalsV3
            or self.candle_originals.sha256 != self.config["candle_originals_sha256"]
        ):
            raise SimInputError("full horizon originals differ from sealed prospective source")

    def _mark_book(self, account, frame, global_sequence, now_ms):
        # Execute ALL native freshness/risk/protection logic, then omit only its
        # successful redundant flat ledger record. Source events remain durable.
        marked = super()._mark_book(account, frame, global_sequence, now_ms)
        active = account.positions or any(r.terminal in {"OPEN", "UNKNOWN"} for r in account.reservations)
        unchanged_gates = (
            marked.barrier,
            marked.risk_over_limit,
            marked.historical_risk_overrun,
            marked.protective_exit_pending,
        ) == (
            account.barrier,
            account.risk_over_limit,
            account.historical_risk_overrun,
            account.protective_exit_pending,
        )
        old_clock = next((t for s, _, t in account.marks if s == frame.symbol), 0)
        valid_mark = (
            old_clock <= frame.exchange_at_ms <= now_ms
            and now_ms - frame.exchange_at_ms <= account.policy.maximum_mark_age_ms
        )
        if (
            not active
            and account.equity > 0
            and unchanged_gates
            and valid_mark
            and len(marked.events) == len(account.events) + 1
        ):
            return replace(marked, events=account.events)
        return marked

    def _event(self, event_id, payload, now, reducer):
        _ms(now)
        horizon = self.config["horizon"]
        if not horizon["data_start_ms"] <= now <= horizon["retained_end_ms"]:
            raise SimInputError("event outside fixed retained horizon")
        if (
            self.binding is not self._sealed_binding
            or self.funding is not self._sealed_funding
            or self.candle_originals is not self._sealed_candle_originals
            or self.config != self._sealed_config
            or {s: m.fingerprint() for s, m in self.models.items()} != self._sealed_config["models"]
            or _plain({s: asdict(r) for s, r in self.rules.items()}) != self._sealed_config["rules"]
        ):
            raise SimInputError("immutable sealed horizon runtime drift")
        prior = self.journal.lookup(event_id=event_id, payload=payload)
        if prior is not None:
            return prior
        snapshot = self.snapshot()
        state = json.loads(_json(snapshot.state))
        if state["config"] != self._sealed_config or state["terminal"] or now < state["clock"]:
            raise SimInputError("terminal, regressing or configuration-conflicting horizon event")
        with localcontext(Context(prec=96)):
            outcome = reducer(state)
        if payload.get("kind") == "FINISH":
            known = {e.event_id for e in decode_account(state["account"]).events if e.payload[0] == "SERVICE"}
            missing = sorted(set(self.config["expected_cost_ids"]) - known)
            unknown = sorted(
                k for k, v in state["service_liabilities"].items() if v["status"] == "UNAVAILABLE"
            )
            if missing or unknown:
                outcome["status"], outcome["net_return"] = "UNRESOLVED", None
            unadmitted_funding = self.binding.evidence_kind != "TEST_FIXTURE"
            if unadmitted_funding:
                # A supplied due tuple/hash is not evidence of the venue's
                # exhaustive settlement calendar, especially an empty tuple.
                outcome["status"], outcome["net_return"] = "UNRESOLVED", None
            outcome.update(
                {
                    "missing_service_costs": missing,
                    "unavailable_service_costs": unknown,
                    "episode_minutes": 7200,
                    "storage": HORIZON_ID,
                    "funding_schedule_unadmitted": unadmitted_funding,
                    "accepted_historical_inputs": False,
                }
            )
        state["clock"], state["last_outcome"] = now, outcome
        return self.journal.append(
            event_id=event_id,
            payload=payload,
            outcome=outcome,
            state=state,
            expected_version=snapshot.version,
            expected_state_hash=snapshot.state_hash,
            expected_head_sha256=snapshot.head_hash,
            at_ms=now,
        )

    def ingest_batch(self, *, first_sequence, last_sequence):
        if (
            type(first_sequence) is not int
            or type(last_sequence) is not int
            or not 1 <= first_sequence <= last_sequence <= len(self.binding.inputs)
            or last_sequence - first_sequence + 1 > MAX_BATCH
        ):
            raise SimInputError("bounded exact consecutive source batch required")
        items = self.binding.inputs[first_sequence - 1 : last_sequence]
        now = _available(items[-1].value)

        def fold(state):
            if state["cursor"] + 1 != first_sequence:
                raise SimInputError("batch cannot skip/reapply any source prefix")
            for item in items:
                self._ingest_input(state, item, _available(item.value))
            return {"status": "RECORDED", "cursor": last_sequence, "source_items": len(items)}

        return self._event(
            f"source-batch:{first_sequence}:{last_sequence}",
            {
                "kind": "SOURCE_BATCH",
                "first": first_sequence,
                "last": last_sequence,
                "original_prefix": digest([_input_doc(item) for item in items]),
                "at": now,
            },
            now,
            fold,
        )

    def replay_source_through(self, *, now_ms):
        """Persist every retained input <= cutoff, in bounded exact batches.

        No clock projection or implicit admission: the driver must stop at each
        native decision/service boundary and explicitly advance pending commands.
        Restart resumes the same source cursor, account and liquid session.
        """
        _ms(now_ms)
        horizon = self.config["horizon"]
        snapshot = self.snapshot()
        if (
            not horizon["data_start_ms"] <= now_ms <= horizon["retained_end_ms"]
            or now_ms < snapshot.state["clock"]
            or snapshot.state["terminal"]
        ):
            raise SimInputError("causal nonterminal fixed source cutoff required")
        first, last = snapshot.state["cursor"], snapshot.state["cursor"]
        while last < len(self.binding.inputs) and _available(self.binding.inputs[last].value) <= now_ms:
            last += 1
        cursor = first
        while cursor < last:
            end = min(last, cursor + MAX_BATCH)
            self.ingest_batch(first_sequence=cursor + 1, last_sequence=end)
            cursor = end
        return {"cursor": cursor, "source_items": cursor - first, "through": now_ms}

    def record_slots_batch(self, *, cells, source_sha256, at_ms):
        _sha(source_sha256)
        if type(cells) is not tuple or not 1 <= len(cells) <= MAX_BATCH or cells != tuple(sorted(set(cells))):
            raise SimInputError("bounded canonical explicit cell roster required")
        for symbol, minute, status in cells:
            if (
                symbol not in UNIVERSE
                or type(minute) is not int
                or minute not in self.config["minutes"]
                or status not in {"QUIET", "UNAVAILABLE"}
                or at_ms < minute + MINUTE
            ):
                raise SimInputError("causal fixed noncandidate denominator cell required")

        def fold(state):
            if self._due_inputs(state, at_ms):
                raise SimInputError("consume complete available source prefix before denominator")
            self._drain(state, at_ms)
            for symbol, minute, status in cells:
                key = f"{symbol}:{minute}"
                if key in state["slots"]:
                    raise SimInputError("batch cannot overwrite consumed/quiet/unavailable cell")
                state["slots"][key] = {"status": status, "source": source_sha256, "parents": []}
            return {"status": "RECORDED", "cells": len(cells)}

        payload = {"kind": "DENOMINATOR_BATCH", "cells": cells, "source": source_sha256, "at": at_ms}
        return self._event(f"slots-batch:{digest(cells)}", payload, at_ms, fold)

    def record_no_route_cells(self, *, cells, decisions, source_sha256, at_ms):
        """Explicit known abstention with exact native/driver provenance.

        The frozen driver verifies complete native receipt membership and the
        arbitration policy before calling. This API cannot turn unavailable
        coverage into quiet, overwrite any slot, or create a tail entry cell.
        """
        _sha(source_sha256)
        _ms(at_ms)
        if (
            type(cells) is not tuple
            or not 1 <= len(cells) <= MAX_BATCH
            or cells != tuple(sorted(set(cells)))
            or type(decisions) is not tuple
            or not 1 <= len(decisions) <= MAX_PARENTS
            or any(type(d) is not NoRouteDecisionV3 for d in decisions)
            or tuple(d.parent_id for d in decisions) != tuple(sorted({d.parent_id for d in decisions}))
            or self.config["no_route_driver_seal_sha256"] is None
        ):
            raise SimInputError("bounded canonical frozen native no-route roster required")
        expected_cells = set()
        for decision in decisions:
            NoRouteDecisionV3(**asdict(decision))
            minute = decision.actual_decision_ms // MINUTE * MINUTE
            if (
                minute not in self.config["minutes"]
                or at_ms < decision.actual_decision_ms
                or decision.producer_seal_sha256 != self.config["hypothesis_seal_sha256"]
                or decision.driver_seal_sha256 != self.config["no_route_driver_seal_sha256"]
                or decision.disposition_reason == "ORIGIN_NOT_ROUTED"
                and decision.origin in self.config["allowed_origins"]
            ):
                raise SimInputError("native no-route actual clock, routing or frozen seal conflict")
            expected_cells.add((decision.symbol, minute))
        if set(cells) != expected_cells:
            raise SimInputError("no-route cells must exactly cover all supplied native decisions")

        def fold(state):
            if self._due_inputs(state, at_ms):
                raise SimInputError("consume complete available source prefix before no-route")
            if any(f"{symbol}:{minute}" in state["slots"] for symbol, minute in cells):
                raise SimInputError("no-route cannot overwrite consumed/quiet/unavailable slot")
            self._drain(state, at_ms)
            for symbol, minute in cells:
                records = [
                    asdict(d)
                    for d in decisions
                    if d.symbol == symbol and d.actual_decision_ms // MINUTE * MINUTE == minute
                ]
                state["slots"][f"{symbol}:{minute}"] = {
                    "status": "NO_ROUTE",
                    "coverage": "AVAILABLE",
                    "source": source_sha256,
                    "parents": [d["parent_id"] for d in records],
                    "native_decisions": records,
                }
            return {"status": "NO_ROUTE", "cells": len(cells), "native_decisions": len(decisions)}

        event_id, payload = self.no_route_event(
            cells=cells,
            decisions=decisions,
            source_sha256=source_sha256,
            at_ms=at_ms,
        )
        return self._event(event_id, payload, at_ms, fold)

    @staticmethod
    def no_route_event(*, cells, decisions, source_sha256, at_ms):
        """Pure exact write-ahead intent; recording still validates frozen state."""
        _sha(source_sha256)
        _ms(at_ms)
        if type(decisions) is not tuple or any(type(d) is not NoRouteDecisionV3 for d in decisions):
            raise SimInputError("typed native no-route write-ahead intent required")
        payload = {
            "kind": "NO_ROUTE",
            "cells": cells,
            "decisions": [asdict(d) for d in decisions],
            "source": source_sha256,
            "at": at_ms,
        }
        return f"no-route:{digest(payload)}", payload

    def record_unknown_service(self, *, cost_id, source_sha256, at_ms):
        _id(cost_id)
        _sha(source_sha256)
        if cost_id not in self.config["expected_cost_ids"]:
            raise SimInputError("service liability outside presealed expense roster")

        def fold(state):
            if self._due_inputs(state, at_ms):
                raise SimInputError("consume known source before cost liability")
            self._drain(state, at_ms)
            if cost_id in state["service_liabilities"]:
                raise SimInputError("service liability already immutable")
            state["service_liabilities"][cost_id] = {
                "status": "UNAVAILABLE",
                "source": source_sha256,
                "at": at_ms,
            }
            return {"status": "UNAVAILABLE"}

        return self._event(
            f"unknown-service:{cost_id}", {"cost": cost_id, "source": source_sha256, "at": at_ms}, at_ms, fold
        )

    def debit_service(self, *, cost_id, amount, at_ms):
        _id(cost_id)
        if cost_id not in self.config["expected_cost_ids"]:
            raise SimInputError("service debit outside presealed expense roster")
        if type(amount) is not Decimal or not amount.is_finite() or amount < 0:
            raise SimInputError("known exact service liability required")

        def fold(state):
            if self._due_inputs(state, at_ms):
                raise SimInputError("consume known source prefix before service/sizing")
            self._drain(state, at_ms)
            state["account"] = encode_account(
                account_api.debit_cost(
                    decode_account(state["account"]),
                    cost_id=cost_id,
                    amount=amount,
                    at_ms=at_ms,
                    kind="SERVICE",
                )
            )
            unknown = state["service_liabilities"].get(cost_id)
            state["service_liabilities"][cost_id] = {
                "status": "SETTLED",
                "amount": str(amount),
                "at": at_ms,
                "earlier_unavailable": unknown,
            }
            return {"status": "DEBITED"}

        return self._event(f"cost:{cost_id}", {"amount": str(amount), "at": at_ms}, at_ms, fold)

    def intake_v3(self, **kwargs):
        if (
            not self.config["horizon"]["entry_start_ms"]
            <= kwargs["at_ms"]
            < self.config["horizon"]["entry_start_ms"] + FIVE_DAYS
        ):
            raise SimInputError("no new admission in warmup or natural-exit tail")
        return super().intake_v3(**kwargs)

    def _missing_protection_bars(self, state, through):
        missing = set()
        for parent in state["parents"].values():
            if not parent["exposure"] or parent["candidate"]["plan"]["trailing_activation_price"] is None:
                continue
            first = parent["exposure"][0][0] // MINUTE * MINUTE
            last = min(through, parent["closed_at"] if parent["closed"] else through)
            for minute in range(first, last // MINUTE * MINUTE, MINUTE):
                if (
                    self._quantity_due(parent, minute + MINUTE) > 0
                    and f"{parent['candidate']['symbol']}:{minute}" not in state["candles"]
                ):
                    missing.add(f"{parent['candidate']['symbol']}:{minute}")
        return sorted(missing)

    def finish(self, *, now_ms, event_id):
        if now_ms != self.config["horizon"]["retained_end_ms"]:
            raise SimInputError("exact presealed natural-exit/liability horizon required")
        return super().finish(now_ms=now_ms, event_id=event_id)
