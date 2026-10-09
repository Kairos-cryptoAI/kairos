"""Bounded portfolio SIM, one durable account per arm, never trading authority.

Retained availability is the logical replay clock. Commands/fills are modeled,
not backdated claims of actual order persistence. Caller-attested bars/funding
remain separate from observed public-book byte consistency. No model calls,
forced closes, source interpolation, campaign credit or qualified economics.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal, localcontext
from pathlib import Path
from types import MappingProxyType

from kairos_core.enums import Side
from kairos_execution.simulation.fill_model import simulate_ioc
from kairos_execution.simulation.models import (
    AcceptedBookFrame,
    CommandReceipt,
    FillAssumptions,
    FillOutcome,
    IOCCommand,
    LiquidityState,
)
from kairos_strategy.models import SleeveIntent
from kairos_strategy.provenance import candle_payload

from . import adaptive_sim_account as account_api
from .candle_originals_v3 import CandleOriginalsV3
from .historical_context import digest
from .hypothesis_journal import HypothesisJournal, JournalReceipt
from .hypothesis_journal_v3 import HypothesisJournalV3, JournalReceiptV3
from .hypothesis_v3 import POLICY_ID as V3_POLICY_ID
from .hypothesis_v3 import HypothesisPlan as V3HypothesisPlan
from .sim_account_codec import decode_account, encode_account
from .sim_book_tape import PublicBookTape
from .sim_state_journal import JournalIdentity, SimStateJournal

D = Decimal
ZERO = D(0)
UNIVERSE = tuple(sorted(account_api.SYMBOLS))
MAX_INPUTS = 10_000
MAX_EVENTS = 10_000
MAX_PARENTS = 128
MAX_EXIT_ATTEMPTS = 8
EVIDENCE = {"TEST_FIXTURE", "CALLER_ATTESTED_POINT_IN_TIME"}


class SimInputError(ValueError):
    pass


def _sha(value):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise SimInputError("exact lowercase SHA256 required")


def _ms(value):
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise SimInputError("nonnegative integer clock required")


def _id(value):
    if (
        type(value) is not str
        or not 1 <= len(value) <= 128
        or any(ord(c) < 33 or ord(c) > 126 for c in value)
    ):
        raise SimInputError("bounded canonical ASCII identity required")


def _plain(value):
    if type(value) in {Decimal, float}:
        return str(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def _json(value):
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    price_tick: Decimal
    quantity_step: Decimal
    maximum_order_price: Decimal

    def __post_init__(self):
        if self.symbol not in UNIVERSE:
            raise SimInputError("fixed universe required")
        for v in (self.price_tick, self.quantity_step, self.maximum_order_price):
            if type(v) is not Decimal or not v.is_finite() or v <= 0:
                raise SimInputError("finite positive exact instrument rule required")


@dataclass(frozen=True)
class ClosedCandleInput:
    symbol: str
    open_at_ms: int
    close_at_ms: int
    available_at_ms: int
    close: Decimal
    source_id: str
    evidence_kind: str
    source_payload_sha256: str

    def __post_init__(self):
        for t in (self.open_at_ms, self.close_at_ms, self.available_at_ms):
            _ms(t)
        if (
            self.symbol not in UNIVERSE
            or self.open_at_ms % 60_000
            or self.close_at_ms != self.open_at_ms + 59_999
            or self.available_at_ms < self.close_at_ms + 1
        ):
            raise SimInputError("exact closed minute and causal availability required")
        if type(self.close) is not Decimal or not self.close.is_finite() or self.close <= 0:
            raise SimInputError("positive close required")
        _id(self.source_id)
        _sha(self.source_payload_sha256)
        if self.evidence_kind not in EVIDENCE:
            raise SimInputError("explicit evidence class required")


@dataclass(frozen=True)
class FundingInput:
    symbol: str
    due_at_ms: int
    available_at_ms: int
    source_id: str
    evidence_kind: str
    status: str
    rate: Decimal | None
    settlement_price: Decimal | None
    source_payload_sha256: str

    def __post_init__(self):
        _ms(self.due_at_ms)
        _ms(self.available_at_ms)
        _id(self.source_id)
        _sha(self.source_payload_sha256)
        if (
            self.symbol not in UNIVERSE
            or self.available_at_ms < self.due_at_ms
            or self.evidence_kind not in EVIDENCE
        ):
            raise SimInputError("causal scoped funding receipt required")
        if self.status == "UNAVAILABLE":
            if self.rate is not None or self.settlement_price is not None:
                raise SimInputError("unknown funding cannot invent numbers")
        elif self.status in {"SETTLED", "NO_PAYMENT"}:
            if (
                type(self.rate) is not Decimal
                or not self.rate.is_finite()
                or type(self.settlement_price) is not Decimal
                or not self.settlement_price.is_finite()
                or self.settlement_price <= 0
            ):
                raise SimInputError("exact native funding rate/settlement price required")
            if self.status == "NO_PAYMENT" and self.rate != 0:
                raise SimInputError("explicit zero no-payment required")
        else:
            raise SimInputError("explicit funding disposition required")


@dataclass(frozen=True)
class TapeInput:
    global_sequence: int
    value: AcceptedBookFrame | ClosedCandleInput | FundingInput

    def __post_init__(self):
        if (
            type(self.global_sequence) is not int
            or self.global_sequence < 1
            or type(self.value) not in {AcceptedBookFrame, ClosedCandleInput, FundingInput}
        ):
            raise SimInputError("typed global input required")


def _available(value):
    return value.persisted_at_ms if type(value) is AcceptedBookFrame else value.available_at_ms


def _input_doc(item):
    value = item.value
    return [
        item.global_sequence,
        type(value).__name__,
        value.fingerprint() if type(value) is AcceptedBookFrame else digest(_plain(asdict(value))),
    ]


@dataclass(frozen=True)
class TapeBinding:
    source_id: str
    tape_id: str
    stream_epoch: str
    quote_source_id: str
    evidence_kind: str
    inputs: tuple[TapeInput, ...]
    public_book_tape: PublicBookTape | None = None

    def __post_init__(self):
        for v in (self.source_id, self.tape_id, self.stream_epoch, self.quote_source_id):
            _id(v)
        if (
            self.evidence_kind not in EVIDENCE
            or type(self.inputs) is not tuple
            or not 1 <= len(self.inputs) <= MAX_INPUTS
        ):
            raise SimInputError("bounded exact input roster required")
        if self.evidence_kind != "TEST_FIXTURE":
            if (
                type(self.public_book_tape) is not PublicBookTape
                or self.public_book_tape.tape_id != self.tape_id
                or self.public_book_tape.epoch != self.stream_epoch
                or self.public_book_tape.quote_source_id != self.quote_source_id
            ):
                raise SimInputError("nonfixture books require externally pinned retained public tape")
        prior_at = 0
        per_symbol = {}
        last_candle = {}
        books = []
        for seq, item in enumerate(self.inputs, 1):
            if (
                type(item) is not TapeInput
                or item.global_sequence != seq
                or _available(item.value) < prior_at
            ):
                raise SimInputError("complete consecutive globally available inputs required")
            prior_at = _available(item.value)
            v = item.value
            if type(v) is AcceptedBookFrame:
                AcceptedBookFrame.model_validate(v)
                if v.tape_id != self.tape_id or v.stream_epoch != self.stream_epoch:
                    raise SimInputError("physical tape/epoch conflict")
                p = per_symbol.get(v.symbol)
                if p and (
                    v.sequence <= p.sequence
                    or v.exchange_update_id <= p.exchange_update_id
                    or v.exchange_at_ms < p.exchange_at_ms
                    or v.received_at_ms < p.received_at_ms
                ):
                    raise SimInputError("per-symbol physical order regression")
                per_symbol[v.symbol] = v
                books.append(v)
            elif v.evidence_kind != self.evidence_kind:
                raise SimInputError("mixed fixture/real source classes forbidden")
            elif type(v) is ClosedCandleInput:
                if v.symbol in last_candle and v.open_at_ms <= last_candle[v.symbol]:
                    raise SimInputError("closed-candle symbol order regression")
                last_candle[v.symbol] = v.open_at_ms
        if self.public_book_tape is not None and tuple(books) != tuple(
            b.frame for b in self.public_book_tape.frames
        ):
            raise SimInputError("complete public original denominator differs")

    @property
    def mapping_sha256(self):
        return digest(
            {
                "source": self.source_id,
                "tape": self.tape_id,
                "epoch": self.stream_epoch,
                "quote": self.quote_source_id,
                "evidence": self.evidence_kind,
                "public": None if self.public_book_tape is None else self.public_book_tape.sha256,
                "inputs": [_input_doc(x) for x in self.inputs],
            }
        )


@dataclass(frozen=True)
class FundingSchedule:
    source_id: str
    evidence_kind: str
    expected_due: tuple[tuple[str, int], ...]
    coverage_sha256: str

    def __post_init__(self):
        _id(self.source_id)
        _sha(self.coverage_sha256)
        if (
            self.evidence_kind not in EVIDENCE
            or type(self.expected_due) is not tuple
            or len(self.expected_due) > MAX_INPUTS
            or self.expected_due != tuple(sorted(set(self.expected_due)))
        ):
            raise SimInputError("frozen explicit funding coverage required")
        for s, t in self.expected_due:
            if s not in UNIVERSE:
                raise SimInputError("funding universe mismatch")
            _ms(t)


def _implementation():
    paths = [
        Path(__file__),
        Path(account_api.__file__),
        Path(simulate_ioc.__code__.co_filename),
        Path(sys.modules[FillAssumptions.__module__].__file__),
        Path(SimStateJournal.create.__func__.__code__.co_filename),
        Path(encode_account.__code__.co_filename),
        Path(HypothesisJournal.snapshot.__code__.co_filename),
        Path(HypothesisJournalV3.snapshot.__code__.co_filename),
        Path(sys.modules[V3HypothesisPlan.__module__].__file__),
        Path(sys.modules[CandleOriginalsV3.__module__].__file__),
        Path(sys.modules[SleeveIntent.__module__].__file__),
    ]
    return digest([[str(p.absolute()), hashlib.sha256(p.read_bytes()).hexdigest()] for p in paths])


def _candidate(candidate):
    return {
        "intent_id": candidate.intent_id,
        "symbol": candidate.symbol,
        "side": candidate.side.value,
        "eligible": candidate.entry_eligible_ts_ms,
        "expires": candidate.entry_expires_ts_ms,
        "reference": str(candidate.reference_price),
        "plan": _plain(asdict(candidate.exit_plan)),
        "exact_original_sha256": digest(asdict(candidate)),
    }


def _no_book_outcome(command, model, arrival):
    return FillOutcome(
        command_id=command.command_id,
        command_sha256=command.fingerprint(),
        assumptions_sha256=model.fingerprint(),
        frame_sha256=None,
        arrival_at_ms=arrival,
        requested_quantity=command.quantity,
        filled_quantity=ZERO,
        cancelled_quantity=command.quantity,
        notional_quote=ZERO,
        fee_quote=ZERO,
        implementation_shortfall_quote=ZERO,
        level_fills=(),
        status="BLOCKED",
        reason="NO_DURABLE_BOOK_AT_ARRIVAL",
    )


class ContinuousSimPortfolio:
    """Finite shared-arm portfolio; intake consumes an exact sealed V2 or V3 issuance."""

    def __init__(self, journal, binding, models, rules, funding, config, path, candle_originals=None):
        self.journal, self.binding, self.funding = journal, binding, funding
        self._sealed_binding, self._sealed_funding = binding, funding
        self.models, self.rules = MappingProxyType(dict(models)), MappingProxyType(dict(rules))
        self.config = json.loads(_json(config))
        self._sealed_config = json.loads(_json(config))
        self.path = Path(path).absolute()
        self.candle_originals = self._sealed_candle_originals = candle_originals

    @staticmethod
    def _config(
        binding,
        models,
        rules,
        funding,
        arm_id,
        minutes,
        initial_equity,
        maximum_exit_attempts,
        hypothesis_seal_sha256,
        hypothesis_contract="V2",
        candle_originals=None,
        allowed_origins=(),
    ):
        _id(arm_id)
        _sha(hypothesis_seal_sha256)
        if hypothesis_contract == "V2":
            if candle_originals is not None or allowed_origins != ():
                raise SimInputError("V2 cannot adopt prospective originals or routing")
        elif hypothesis_contract == "V3":
            if (
                type(candle_originals) is not CandleOriginalsV3
                or type(allowed_origins) is not tuple
                or not allowed_origins
                or allowed_origins != tuple(sorted(set(allowed_origins)))
                or not set(allowed_origins) <= {"TECHNICAL", "CONTEXT_PROPOSAL"}
            ):
                raise SimInputError("V3 requires exact candle originals and presealed origin routing")
            candle_originals.validate_binding(binding)
        else:
            raise SimInputError("explicit V2 or V3 producer contract required")
        if set(models) != set(UNIVERSE) or set(rules) != set(UNIVERSE):
            raise SimInputError("all five sealed symbol models/rules required")
        for s in UNIVERSE:
            if (
                type(models[s]) is not FillAssumptions
                or type(rules[s]) is not SymbolRules
                or rules[s].symbol != s
                or models[s].price_tick != rules[s].price_tick
                or models[s].quantity_step != rules[s].quantity_step
            ):
                raise SimInputError("exact per-symbol models/rules required")
        financial = {
            (m.taker_fee_bps, m.adverse_slippage_bps, m.maximum_book_age_ms) for m in models.values()
        }
        if len(financial) != 1:
            raise SimInputError(
                "uniform financial cost/mark policy required; per-symbol ticks/steps remain distinct"
            )
        if (
            type(minutes) is not tuple
            or not minutes
            or len(minutes) > 1440
            or minutes != tuple(sorted(set(minutes)))
            or any(type(t) is not int or t < 0 or t % 60_000 for t in minutes)
        ):
            raise SimInputError("presealed complete minute denominator required")
        if any(b - a != 60_000 for a, b in zip(minutes, minutes[1:], strict=False)):
            raise SimInputError("minute denominator cannot select disconnected cells")
        if (
            funding.evidence_kind != binding.evidence_kind
            or type(initial_equity) is not Decimal
            or not initial_equity.is_finite()
            or initial_equity <= 0
            or type(maximum_exit_attempts) is not int
            or not 1 <= maximum_exit_attempts <= MAX_EXIT_ATTEMPTS
        ):
            raise SimInputError("fixed funding/equity/exit policy required")
        return {
            "arm": arm_id,
            "hypothesis_seal_sha256": hypothesis_seal_sha256,
            "hypothesis_contract": hypothesis_contract,
            "candle_originals_sha256": None if candle_originals is None else candle_originals.sha256,
            "allowed_origins": list(allowed_origins),
            "tape": binding.mapping_sha256,
            "models": {s: models[s].fingerprint() for s in UNIVERSE},
            "rules": _plain({s: asdict(rules[s]) for s in UNIVERSE}),
            "funding": _plain(asdict(funding)),
            "minutes": list(minutes),
            "initial_equity": str(initial_equity),
            "maximum_exit_attempts": maximum_exit_attempts,
            "risk_basis": "ENTRY_STOP_RESERVED",
            "implementation": _implementation(),
            "clock_authority": "RETAINED_AVAILABILITY_MODELED_ORDER_CLOCK_NOT_OBSERVED_EXECUTION",
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
        minutes,
        initial_equity,
        hypothesis_seal_sha256,
        maximum_exit_attempts=3,
        hypothesis_contract="V2",
        candle_originals=None,
        allowed_origins=(),
    ):
        _id(campaign_id)
        config = cls._config(
            binding,
            models,
            rules,
            funding_schedule,
            arm_id,
            minutes,
            initial_equity,
            maximum_exit_attempts,
            hypothesis_seal_sha256,
            hypothesis_contract,
            candle_originals,
            allowed_origins,
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
            "clock": 0,
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
            "terminal": False,
            "last_outcome": None,
        }
        identity = JournalIdentity(campaign_id, binding.source_id, digest(config), config["implementation"])
        journal = SimStateJournal.create(
            path,
            identity=identity,
            initial_state=state,
            initial_clock_ms=0,
            max_event_rows=MAX_EVENTS,
            max_event_bytes=2 * 1024 * 1024,
        )
        return cls(journal, binding, models, rules, funding_schedule, config, path, candle_originals)

    @classmethod
    def open(
        cls,
        path,
        *,
        identity,
        binding,
        models,
        rules,
        funding_schedule,
        config,
        expected_head_sha256,
        candle_originals=None,
    ):
        _sha(expected_head_sha256)
        rebuilt = cls._config(
            binding,
            models,
            rules,
            funding_schedule,
            config["arm"],
            tuple(config["minutes"]),
            D(config["initial_equity"]),
            config["maximum_exit_attempts"],
            config["hypothesis_seal_sha256"],
            config["hypothesis_contract"],
            candle_originals,
            tuple(config["allowed_origins"]),
        )
        if rebuilt != config:
            raise SimInputError("frozen configuration/implementation drift")
        journal = SimStateJournal.open(
            path, identity=identity, max_event_rows=MAX_EVENTS, max_event_bytes=2 * 1024 * 1024
        )
        snap = journal.snapshot()
        if snap.head_hash != expected_head_sha256 or snap.state["config"] != config:
            journal.close()
            raise SimInputError("independent head/config conflict")
        return cls(journal, binding, models, rules, funding_schedule, config, path, candle_originals)

    def close(self):
        self.journal.close()

    def snapshot(self):
        return self.journal.snapshot()

    def _due_inputs(self, state, now):
        return (
            state["cursor"] < len(self.binding.inputs)
            and _available(self.binding.inputs[state["cursor"]].value) <= now
        )

    def _event(self, event_id, payload, now, reducer):
        _ms(now)
        if (
            self.binding is not self._sealed_binding
            or self.funding is not self._sealed_funding
            or self.candle_originals is not self._sealed_candle_originals
            or self.config != self._sealed_config
            or {s: m.fingerprint() for s, m in self.models.items()} != self._sealed_config["models"]
            or _plain({s: asdict(r) for s, r in self.rules.items()}) != self._sealed_config["rules"]
        ):
            raise SimInputError("immutable sealed runtime configuration drift")
        prior = self.journal.lookup(event_id=event_id, payload=payload)
        if prior is not None:
            return prior
        snap = self.snapshot()
        state = json.loads(_json(snap.state))
        if state["config"] != self._sealed_config:
            raise SimInputError("durable configuration differs from sealed runtime")
        if state["terminal"] or now < state["clock"]:
            raise SimInputError("terminal or regressing event")
        with localcontext(Context(prec=96)):
            outcome = reducer(state)
        state["clock"] = now
        state["last_outcome"] = outcome
        return self.journal.append(
            event_id=event_id,
            payload=payload,
            outcome=outcome,
            state=state,
            expected_version=snap.version,
            expected_state_hash=snap.state_hash,
            at_ms=now,
        )

    def record_slot(self, *, symbol, minute, status, source_sha256, at_ms):
        _sha(source_sha256)
        if (
            symbol not in UNIVERSE
            or minute not in self.config["minutes"]
            or status not in {"QUIET", "UNAVAILABLE"}
            or at_ms < minute + 60_000
        ):
            raise SimInputError("causally observed declared noncandidate cell required")
        key = f"{symbol}:{minute}"

        def fold(st):
            if self._due_inputs(st, at_ms):
                raise SimInputError("consume known source prefix before denominator declaration")
            self._drain(st, at_ms)
            if key in st["slots"]:
                raise SimInputError("denominator cell already immutable")
            st["slots"][key] = {"status": status, "source": source_sha256, "parents": []}
            return {"status": status}

        return self._event(
            f"slot:{key}",
            {"symbol": symbol, "minute": minute, "status": status, "source": source_sha256, "at": at_ms},
            at_ms,
            fold,
        )

    def debit_service(self, *, cost_id, amount, at_ms):
        if type(amount) is not Decimal or not amount.is_finite() or amount < 0:
            raise SimInputError("known finite service liability required")

        def fold(st):
            if self._due_inputs(st, at_ms):
                raise SimInputError("consume known source prefix before service/sizing")
            self._drain(st, at_ms)
            st["account"] = encode_account(
                account_api.debit_cost(
                    decode_account(st["account"]), cost_id=cost_id, amount=amount, at_ms=at_ms, kind="SERVICE"
                )
            )
            return {"status": "DEBITED"}

        return self._event(f"cost:{cost_id}", {"amount": str(amount), "at": at_ms}, at_ms, fold)

    def intake(self, *, hypothesis_journal, receipt, expected_hypothesis_head_sha256, at_ms):
        """Consume exact V2 issued parent; never cast a prospective receipt to V2."""
        if self.config["hypothesis_contract"] != "V2":
            raise SimInputError("V2 intake cannot adopt a V3 producer configuration")
        return self._intake(
            hypothesis_journal=hypothesis_journal,
            receipt=receipt,
            expected_hypothesis_head_sha256=expected_hypothesis_head_sha256,
            at_ms=at_ms,
            prospective=False,
        )

    def intake_v3(self, *, hypothesis_journal, receipt, expected_hypothesis_head_sha256, at_ms):
        """Consume original V3 evidence on its actual clock with explicit routing."""
        if self.config["hypothesis_contract"] != "V3":
            raise SimInputError("V3 intake requires its own presealed producer configuration")
        return self._intake(
            hypothesis_journal=hypothesis_journal,
            receipt=receipt,
            expected_hypothesis_head_sha256=expected_hypothesis_head_sha256,
            at_ms=at_ms,
            prospective=True,
        )

    def _intake(self, *, hypothesis_journal, receipt, expected_hypothesis_head_sha256, at_ms, prospective):
        """Shared execution fold after version-specific original evidence validation."""
        _sha(expected_hypothesis_head_sha256)
        journal_type = HypothesisJournalV3 if prospective else HypothesisJournal
        receipt_type = JournalReceiptV3 if prospective else JournalReceipt
        if type(hypothesis_journal) is not journal_type or type(receipt) is not receipt_type:
            raise SimInputError("original typed evidence for the exact sealed producer required")
        hs = hypothesis_journal.snapshot()
        if hs.seal_sha256 != self.config["hypothesis_seal_sha256"]:
            raise SimInputError("producer journal differs from presealed hypothesis roster")
        if receipt.arm_id != self.config["arm"]:
            raise SimInputError("fresh external hypothesis arm mismatch")
        groups = [
            g
            for g in hs.hypotheses
            if g.arm_id == receipt.arm_id and g.plan.template.intent_id == receipt.parent_id
        ]
        if (
            len(groups) != 1
            or replace(receipt, new_event=False) not in groups[0].receipts
            or receipt.evaluation.state != "CONSUMED"
        ):
            raise SimInputError("exact durable issued first-trigger receipt required")
        group = groups[0]
        if (
            group.plan.policy.evidence_kind != self.binding.evidence_kind
            or group.plan.policy.quote_source_id != self.binding.quote_source_id
        ):
            raise SimInputError("first trigger policy/source evidence differs from sealed portfolio")
        first_consumed = next((r for r in group.receipts if r.evaluation.state == "CONSUMED"), None)
        if replace(receipt, new_event=False) != first_consumed:
            raise SimInputError("terminal redelivery is not a new first trigger")
        if digest(asdict(replace(receipt, new_event=False))) != digest(asdict(first_consumed)):
            raise SimInputError("unchanged full original receipt bytes required")
        c = receipt.evaluation.candidate
        obs = next(
            (o for o in group.observations if o.observation_id == receipt.evaluation.observation_id), None
        )
        if obs is None or at_ms < receipt.evaluation.observed_ms:
            raise SimInputError("causal original first-trigger observation required")
        if prospective:
            index = next(i for i, o in enumerate(group.observations) if o is obs)
            prefix = tuple(
                zip(group.observations[: index + 1], group.review_receipts[: index + 1], strict=True)
            )
            self._validate_v3_originals(group.plan, receipt, prefix, c)

        def commit(payload, reducer):
            event_id = f"{'v3-intake' if prospective else 'intake'}:{receipt.parent_id}"
            if prospective:
                payload = payload | {
                    "producer_contract": "V3",
                    "producer_seal": hs.seal_sha256,
                    "receipt_sequence": receipt.sequence,
                    "parent_plan": digest(asdict(group.plan)),
                }
            prior = self.journal.lookup(event_id=event_id, payload=payload)
            if prior is None and hs.head_sha256 != expected_hypothesis_head_sha256:
                raise SimInputError("fresh external hypothesis head mismatch")
            return self._event(event_id, payload, at_ms, reducer)

        if c is None:
            # Veto/missing context is still a consumed original first trigger, not
            # a renewable parent that the SIM can rescue with a later quote.
            doc = _candidate(group.plan.template)
            key = f"{group.plan.template.symbol}:{receipt.evaluation.observed_ms // 60_000 * 60_000}"
            if receipt.evaluation.observed_ms // 60_000 * 60_000 not in self.config["minutes"]:
                raise SimInputError("first trigger outside fixed causal denominator")
            payload = {
                "parent": receipt.parent_id,
                "candidate": None,
                "evaluation": receipt.evaluation.sha256,
                "issue": receipt.chain_sha256,
                "head": expected_hypothesis_head_sha256,
                "at": at_ms,
            }

            def refused(st):
                if self._due_inputs(st, at_ms):
                    raise SimInputError("consume full known source prefix before intake")
                if receipt.parent_id in st["parents"] or len(st["parents"]) >= MAX_PARENTS:
                    raise SimInputError("parent already consumed or bounded capacity reached")
                self._drain(st, at_ms)
                slot = st["slots"].get(key)
                if slot is not None and slot["status"] != "CANDIDATE":
                    raise SimInputError("first trigger cannot overwrite quiet/unavailable")
                slot = st["slots"].setdefault(
                    key,
                    {
                        "status": "CANDIDATE",
                        "source": expected_hypothesis_head_sha256,
                        "parents": [],
                        "coverage": "AVAILABLE",
                    },
                )
                slot["parents"].append(receipt.parent_id)
                if receipt.evaluation.coverage != "AVAILABLE":
                    slot["coverage"] = "UNAVAILABLE"
                st["parents"][receipt.parent_id] = {
                    "candidate": doc,
                    "issue": payload,
                    "entry": "REFUSED",
                    "admission_reason": receipt.evaluation.reason,
                    "exit_reason": None,
                    "exit_attempts": 0,
                    "trailing_active": False,
                    "exposure": [],
                    "closed": False,
                    "closed_at": None,
                }
                return {"status": "REFUSED", "reason": receipt.evaluation.reason, "parent": receipt.parent_id}

            return commit(payload, refused)
        if type(c) is not SleeveIntent or type(c.side) is not Side:
            raise SimInputError("typed original candidate required")
        meta = dict(c.metadata)
        if (
            c.exit_plan != group.plan.template.exit_plan
            or meta.get("parent_intent_id") != receipt.parent_id
            or meta.get("protection_sha256") != digest(asdict(c.exit_plan))
            or meta.get("source_set_sha256") != group.plan.source_set_sha256
            or obs is None
            or obs.quote is None
            or meta.get("entry_quote_sha256") != obs.quote.sha256
            or obs.quote.source_id != self.binding.quote_source_id
            or meta.get("evidence_kind") != self.binding.evidence_kind
            or c.decision_ts_ms != c.entry_eligible_ts_ms
        ):
            raise SimInputError("full original plan/source/quote/provenance conflict")
        quote = obs.quote
        quote_books = [
            i.value
            for i in self.binding.inputs
            if type(i.value) is AcceptedBookFrame
            and i.value.symbol == c.symbol
            and i.value.exchange_at_ms == quote.event_ms
            and i.value.persisted_at_ms == quote.captured_ms
            and i.value.received_at_ms == quote.received_ms
            and i.value.bids[0].price == D(str(quote.bid))
            and i.value.asks[0].price == D(str(quote.ask))
        ]
        if not quote_books:
            raise SimInputError("issue quote absent from pinned original book roster")
        doc = _candidate(c)
        key = f"{c.symbol}:{c.decision_ts_ms // 60_000 * 60_000}"
        if c.decision_ts_ms // 60_000 * 60_000 not in self.config["minutes"] or at_ms < c.decision_ts_ms:
            raise SimInputError("issuance outside fixed causal denominator")
        payload = {
            "parent": receipt.parent_id,
            "candidate": doc["exact_original_sha256"],
            "evaluation": receipt.evaluation.sha256,
            "issue": receipt.chain_sha256,
            "head": expected_hypothesis_head_sha256,
            "at": at_ms,
        }

        def fold(st):
            if self._due_inputs(st, at_ms):
                raise SimInputError("consume full known source prefix before intake")
            if receipt.parent_id in st["parents"] or len(st["parents"]) >= MAX_PARENTS:
                raise SimInputError("parent already consumed or bounded capacity reached")
            self._drain(st, at_ms)
            slot = st["slots"].get(key)
            if slot is not None and slot["status"] != "CANDIDATE":
                raise SimInputError("issued candidate cannot overwrite quiet/unavailable")
            st["slots"].setdefault(
                key,
                {
                    "status": "CANDIDATE",
                    "source": expected_hypothesis_head_sha256,
                    "parents": [],
                    "coverage": "AVAILABLE",
                },
            )["parents"].append(receipt.parent_id)
            parent = {
                "candidate": doc,
                "issue": payload,
                "entry": "REFUSED",
                "exit_reason": None,
                "exit_attempts": 0,
                "trailing_active": False,
                "exposure": [],
                "closed": False,
                "closed_at": None,
            }
            st["parents"][receipt.parent_id] = parent
            a = decode_account(st["account"])
            rule = self.rules[c.symbol]
            m = self.models[c.symbol]
            frame = self._latest(st, c.symbol)
            reason = (
                "EXPIRED"
                if at_ms > c.entry_expires_ts_ms
                else "NO_POSITIVE_RESERVATION_LIFETIME"
                if at_ms == c.entry_expires_ts_ms
                else "FUNDING_UNRESOLVED"
                if self._missing_funding(st, at_ms)
                else "PROTECTION_SOURCE_UNRESOLVED"
                if self._missing_protection_bars(st, at_ms)
                else "NO_FRESH_BOOK"
                if frame is None
                or frame.continuity != "ADMITTED"
                or at_ms - frame.exchange_at_ms > m.maximum_book_age_ms
                else None
            )
            reference = D(str(c.reference_price))
            cap = self._tick(reference, rule.price_tick, up=c.side is Side.SHORT)
            # A buy cap rounds DOWN and a sell cap UP: never invent favorable expanded permission.
            if reason is None and (cap <= 0 or cap > rule.maximum_order_price):
                reason = "PRICE_RULE_BOUND"
            if reason is None:
                a = replace(a, policy=replace(a.policy, quantity_step=rule.quantity_step))
                worst = cap
                worst_notional = max(worst, frame.asks[0].price, frame.bids[0].price)
                a, reservation, reason = account_api.reserve_entry(
                    a,
                    reservation_id=f"r:{c.intent_id}",
                    intent_id=c.intent_id,
                    symbol=c.symbol,
                    side=c.side.value,
                    stop_price=D(str(c.exit_plan.stop_price)),
                    worst_entry_price=worst,
                    worst_notional_price=worst_notional,
                    as_of_ms=at_ms,
                    expires_at_ms=c.entry_expires_ts_ms,
                )
                if reservation is not None:
                    command = IOCCommand(
                        session_id=self.config["arm"],
                        command_id=f"e:{c.intent_id}",
                        symbol=c.symbol,
                        side="BUY" if c.side is Side.LONG else "SELL",
                        quantity=reservation.quantity,
                        price_cap=cap,
                        submitted_at_ms=at_ms,
                        persisted_at_ms=at_ms,
                        eligible_at_ms=c.entry_eligible_ts_ms,
                        expires_at_ms=c.entry_expires_ts_ms,
                    )
                    st["pending"][command.command_id] = {
                        "command": command.model_dump(mode="json"),
                        "parent": receipt.parent_id,
                        "purpose": "ENTRY",
                        "attempt": 0,
                    }
                    parent["entry"] = "PENDING"
            st["account"] = encode_account(a)
            parent["admission_reason"] = reason
            return {"status": parent["entry"], "reason": reason, "parent": receipt.parent_id}

        return commit(payload, fold)

    def _require_v3_originals(self):
        """Require this path's exact sealed normalized originals container."""
        if (
            type(self.candle_originals) is not CandleOriginalsV3
            or self.candle_originals.sha256 != self.config["candle_originals_sha256"]
        ):
            raise SimInputError("retained full candle originals differ from the sealed V3 portfolio")

    def _validate_v3_originals(self, plan, receipt, prefix, candidate):
        """Full normalized-candle membership, not raw REST/source authentication."""
        self._require_v3_originals()
        if plan.origin not in self.config["allowed_origins"]:
            raise SimInputError("counterfactual journal enrollment is not sealed arm routing permission")
        creation_ready_at = (
            plan.created_ms
            if plan.creation_assessment is None
            else plan.creation_assessment.actual_requested_ms
        )
        checks = [(plan.anchor, plan.creation_evidence, creation_ready_at)]
        checks.extend(
            (o.market.candle, o.market.sources, completion.shared_observed_ms) for o, completion in prefix
        )
        obs = prefix[-1][0]
        for candle, sources, ready_at in checks:
            originals = [
                e
                for e in sources
                if e.kind == "MARKET" and e.payload_sha256 == digest(candle_payload(candle))
            ]
            if not originals:
                if (
                    candidate is None
                    and candle is not plan.anchor
                    and receipt.evaluation.coverage == "UNAVAILABLE"
                ):
                    continue  # explicitly missing source poisons coverage, never authenticates a candle
                raise SimInputError("exact original MARKET receipt required for the full V3 candle")
            for original in originals:
                self.candle_originals.find(candle, original, ready_at)
        if candidate is None:
            return
        expected = {
            "hypothesis_id": plan.scenario_id,
            "hypothesis_policy_sha256": plan.policy.sha256,
            "parent_intent_id": plan.template.intent_id,
            "parent_snapshot_sha256": digest(asdict(plan.template)),
            "protection_sha256": plan.protection_sha256,
            "confirmation_observation_id": obs.observation_id,
            "entry_quote_sha256": None if obs.quote is None else obs.quote.sha256,
            "source_set_sha256": plan.source_set_sha256,
            "hypothesis_origin": plan.origin,
            "evidence_kind": plan.policy.evidence_kind,
            "hypothesis_origin_cut_ms": str(plan.origin_cut_ms),
            "hypothesis_actual_created_ms": str(plan.created_ms),
            "creation_assessment_sha256": (
                "NONE" if plan.creation_assessment is None else plan.creation_assessment.sha256
            ),
            "planning_cost_authority": "ASSUMPTION_NOT_VENUE_MEASUREMENT",
        }
        meta = dict(candidate.metadata)
        if (
            any(meta.get(k) != v for k, v in expected.items())
            or candidate.sleeve_id != V3_POLICY_ID
            or candidate.symbol != plan.template.symbol
            or candidate.side != plan.template.side
            or candidate.decision_ts_ms != receipt.evaluation.observed_ms
            or candidate.decision_ts_ms != obs.market.observed_ms
            or candidate.exit_plan != plan.template.exit_plan
        ):
            raise SimInputError("native V3 candidate, original protection or actual clock conflict")

    @staticmethod
    def _tick(price, tick, up):
        return (price / tick).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * tick

    def _latest(self, st, symbol):
        v = st["latest"].get(symbol)
        return None if v is None else AcceptedBookFrame.model_validate_json(_json(v))

    def _liquidity(self, st, symbol):
        return LiquidityState.model_validate_json(_json(st["liquidity"][symbol]))

    def _exit(self, st, pid, now, reason):
        p = st["parents"][pid]
        a = decode_account(st["account"])
        pos = next((x for x in a.positions if x.intent_id == p["candidate"]["intent_id"]), None)
        if pos is None:
            return
        urgency = {None: 0, "TARGET": 1, "TIMEOUT": 2, "STOP": 3, "TRAILING_STOP": 3}
        if urgency[reason] > urgency[p["exit_reason"]]:
            p["exit_reason"] = reason
            p.setdefault("exit_trigger_history", []).append([now, reason])
            a = account_api.request_protective_exit(
                a, intent_id=pos.intent_id, event_id=f"protect:{pos.intent_id}:{reason}", reason=reason
            )
            st["account"] = encode_account(a)
        if any(x["parent"] == pid for x in st["pending"].values()):
            return  # never rewrite or pretend cancellation of an existing IOC
        if p["exit_attempts"] >= self.config["maximum_exit_attempts"]:
            st["account"] = encode_account(
                account_api.set_barrier(
                    a, event_id=f"exhaust:{pos.intent_id}", reason="PROTECTIVE_EXIT_ATTEMPTS_EXHAUSTED"
                )
            )
            return
        rule = self.rules[pos.symbol]
        m = self.models[pos.symbol]
        cap = (
            self._tick(D(p["candidate"]["plan"]["target_price"]), rule.price_tick, up=pos.side == "LONG")
            if p["exit_reason"] == "TARGET"
            else rule.price_tick
            if pos.side == "LONG"
            else self._tick(rule.maximum_order_price, rule.price_tick, up=False)
        )
        p["exit_attempts"] += 1
        command = IOCCommand(
            session_id=self.config["arm"],
            command_id=f"x:{pos.intent_id}:{p['exit_attempts']}",
            symbol=pos.symbol,
            side="SELL" if pos.side == "LONG" else "BUY",
            quantity=pos.quantity,
            price_cap=cap,
            submitted_at_ms=now,
            persisted_at_ms=now,
            eligible_at_ms=now,
            expires_at_ms=now + m.latency_ms,
        )
        st["pending"][command.command_id] = {
            "command": command.model_dump(mode="json"),
            "parent": pid,
            "purpose": "EXIT",
            "reason": p["exit_reason"],
            "attempt": p["exit_attempts"],
        }

    def _drain(self, st, through):
        # Dynamically merge first-fill timeout deadlines with command arrivals.
        # A single advance may both fill an entry and reach its later timeout;
        # deadlines may not be discovered after newer commands have executed.
        while True:
            owned = {p.intent_id for p in decode_account(st["account"]).positions}
            deadlines = [
                (p["exposure"][0][0] + p["candidate"]["plan"]["max_holding_ms"], pid)
                for pid, p in st["parents"].items()
                if p["candidate"]["intent_id"] in owned
                and p["exposure"]
                and not p["closed"]
                and p["exit_reason"] in {None, "TARGET"}
            ]
            next_timeout = min(deadlines, default=None)
            ordered = sorted(
                st["pending"].items(),
                key=lambda x: (
                    x[1]["command"]["submitted_at_ms"] + self.models[x[1]["command"]["symbol"]].latency_ms,
                    0 if x[1]["purpose"] == "EXIT" else 1,
                    x[0],
                ),
            )
            next_arrival = (
                None
                if not ordered
                else ordered[0][1]["command"]["submitted_at_ms"]
                + self.models[ordered[0][1]["command"]["symbol"]].latency_ms
            )
            if (
                next_timeout is not None
                and next_timeout[0] <= through
                and (next_arrival is None or next_timeout[0] <= next_arrival)
            ):
                self._exit(st, next_timeout[1], next_timeout[0], "TIMEOUT")
                continue
            if next_arrival is None or next_arrival > through:
                break
            cid, pending = ordered[0]
            cmd = IOCCommand.model_validate_json(_json(pending["command"]))
            model = self.models[cmd.symbol]
            arrival = cmd.submitted_at_ms + model.latency_ms
            f = self._latest(st, cmd.symbol)
            liq = self._liquidity(st, cmd.symbol)
            if f is None or f.persisted_at_ms > arrival:
                outcome = _no_book_outcome(cmd, model, arrival)
                if len(liq.receipts) >= 1024:
                    raise SimInputError("liquidity receipt capacity exhausted")
                liq = replace_liquidity(liq, cmd, outcome, arrival)
            else:
                step = simulate_ioc(cmd, f, model, liq, as_of_ms=arrival)
                outcome, liq = step.outcome, step.state
            st["liquidity"][cmd.symbol] = liq.model_dump(mode="json")
            del st["pending"][cid]
            parent = st["parents"][pending["parent"]]
            parent.setdefault("outcomes", []).append(outcome.model_dump(mode="json"))
            a = decode_account(st["account"])
            if outcome.filled_quantity > 0:
                fn = (
                    account_api.record_entry_fill
                    if pending["purpose"] == "ENTRY"
                    else account_api.record_exit_fill
                )
                identity = (
                    {"reservation_id": f"r:{parent['candidate']['intent_id']}"}
                    if pending["purpose"] == "ENTRY"
                    else {"intent_id": parent["candidate"]["intent_id"]}
                )
                a, _ = fn(
                    a,
                    **identity,
                    fill_id=f"fill:{cid}",
                    quantity=outcome.filled_quantity,
                    average_price=outcome.average_price,
                    fee=outcome.fee_quote,
                    at_ms=arrival,
                )
                parent["exposure"].append(
                    [
                        arrival,
                        str(
                            outcome.filled_quantity
                            if pending["purpose"] == "ENTRY"
                            else -outcome.filled_quantity
                        ),
                    ]
                )
            if pending["purpose"] == "ENTRY":
                terminal = (
                    "FILLED"
                    if outcome.status == "FILLED"
                    else "PARTIAL"
                    if outcome.filled_quantity
                    else "NO_FILL"
                )
                a = account_api.resolve_entry(
                    a,
                    reservation_id=f"r:{parent['candidate']['intent_id']}",
                    event_id=f"resolved:{cid}",
                    outcome=terminal,
                )
                parent["entry"] = terminal
            elif (
                not any(x.intent_id == parent["candidate"]["intent_id"] for x in a.positions)
                and outcome.filled_quantity
            ):
                parent["closed"], parent["closed_at"] = True, arrival
            if outcome.status == "BLOCKED":
                a = account_api.set_barrier(a, event_id=f"blocked:{cid}", reason=outcome.reason)
            st["account"] = encode_account(a)
            if pending["purpose"] == "ENTRY" and outcome.filled_quantity and f is not None:
                pos = next((p for p in a.positions if p.intent_id == parent["candidate"]["intent_id"]), None)
                if pos is not None:
                    px = f.bids[0].price if pos.side == "LONG" else f.asks[0].price
                    if px <= pos.stop_price if pos.side == "LONG" else px >= pos.stop_price:
                        # The frame was processed before this position existed.
                        # Birth-time stop protection therefore belongs here, using
                        # this already-durable exit-side quote, never a later frame.
                        self._exit(st, pending["parent"], arrival, "STOP")
            if (
                pending["purpose"] == "EXIT"
                and parent["exit_reason"] != pending["reason"]
                and not parent["closed"]
            ):
                self._exit(st, pending["parent"], arrival, parent["exit_reason"])

    def _mark_book(self, account, frame, global_sequence, now_ms):
        """Unchanged account marking; additive horizon paths may specialize storage."""
        marked, _ = account_api.mark_account(
            account,
            mark_id=f"mark:{global_sequence}",
            marks=((frame.symbol, (frame.bids[0].price + frame.asks[0].price) / 2, frame.exchange_at_ms),),
            as_of_ms=now_ms,
        )
        return marked

    def ingest(self, *, global_sequence, now_ms):
        if type(global_sequence) is not int or not 1 <= global_sequence <= len(self.binding.inputs):
            raise SimInputError("input outside complete source denominator")
        item = self.binding.inputs[global_sequence - 1]
        if now_ms != _available(item.value):
            raise SimInputError("retained-availability replay clock required; no projected consumer clock")

        return self._event(
            f"input:{global_sequence}",
            {"input": _input_doc(item), "at": now_ms},
            now_ms,
            lambda state: self._ingest_input(state, item, now_ms),
        )

    def _ingest_input(self, st, item, now_ms):
        """Apply one exact retained input in order within the caller's transaction."""
        global_sequence = item.global_sequence
        if now_ms != _available(item.value):
            raise SimInputError("retained-availability replay clock required; no projected consumer clock")

        def fold(st):
            if global_sequence != st["cursor"] + 1:
                raise SimInputError("complete consecutive source cursor required")
            # All arrivals strictly before this source precede it. Equal-time source
            # items precede commands; drain equality only after the last tied item.
            self._drain(st, now_ms - 1)
            v = item.value
            if type(v) is AcceptedBookFrame:
                st["latest"][v.symbol] = v.model_dump(mode="json")
                a = decode_account(st["account"])
                if v.continuity != "ADMITTED":
                    a = account_api.set_barrier(
                        a, event_id=f"source-gap:{global_sequence}", reason=f"SOURCE_{v.continuity}"
                    )
                else:
                    a = self._mark_book(a, v, global_sequence, now_ms)
                st["account"] = encode_account(a)
                for pid, p in sorted(st["parents"].items()):
                    pos = next(
                        (
                            x
                            for x in a.positions
                            if x.intent_id == p["candidate"]["intent_id"] and x.symbol == v.symbol
                        ),
                        None,
                    )
                    if pos is None or v.continuity != "ADMITTED":
                        continue
                    px = v.bids[0].price if pos.side == "LONG" else v.asks[0].price
                    stop = px <= pos.stop_price if pos.side == "LONG" else px >= pos.stop_price
                    target = (
                        px >= D(p["candidate"]["plan"]["target_price"])
                        if pos.side == "LONG"
                        else px <= D(p["candidate"]["plan"]["target_price"])
                    )
                    reason = (
                        (
                            "TRAILING_STOP"
                            if pos.stop_price != D(p["candidate"]["plan"]["stop_price"])
                            else "STOP"
                        )
                        if stop
                        else p["exit_reason"] or ("TARGET" if target else None)
                    )
                    if reason:
                        self._exit(st, pid, now_ms, reason)
            elif type(v) is ClosedCandleInput:
                candle_key = f"{v.symbol}:{v.open_at_ms}"
                if candle_key in st["candles"]:
                    raise SimInputError("closed-candle identity cannot be delivered twice")
                st["candles"][candle_key] = {"source": v.source_payload_sha256, "available": now_ms}
                a = decode_account(st["account"])
                for _pid, p in sorted(st["parents"].items()):
                    pos = next(
                        (
                            x
                            for x in a.positions
                            if x.intent_id == p["candidate"]["intent_id"] and x.symbol == v.symbol
                        ),
                        None,
                    )
                    plan = p["candidate"]["plan"]
                    if (
                        pos is None
                        or p["exit_reason"]
                        or plan["trailing_activation_price"] is None
                        or v.close_at_ms < pos.opened_at_ms
                    ):
                        continue
                    activation = D(plan["trailing_activation_price"])
                    p["trailing_active"] |= (
                        v.close >= activation if pos.side == "LONG" else v.close <= activation
                    )
                    if p["trailing_active"]:
                        proposed = (
                            v.close - D(plan["trailing_distance"])
                            if pos.side == "LONG"
                            else v.close + D(plan["trailing_distance"])
                        )
                        if proposed > pos.stop_price if pos.side == "LONG" else proposed < pos.stop_price:
                            a = account_api.tighten_stop(
                                a,
                                intent_id=pos.intent_id,
                                event_id=f"trail:{global_sequence}:{pos.intent_id}",
                                stop_price=proposed,
                                source_event_ms=v.close_at_ms,
                                available_ms=now_ms,
                                as_of_ms=now_ms,
                            )
                st["account"] = encode_account(a)
            else:
                self._funding(st, v)
            st["cursor"] = global_sequence
            if not self._due_inputs(st, now_ms):
                self._drain(st, now_ms)
            return {"status": "RECORDED", "cursor": global_sequence}

        return fold(st)

    def _funding(self, st, receipt):
        key = f"{receipt.symbol}:{receipt.due_at_ms}"
        prior = st["funding"].get(key)
        if (
            (receipt.symbol, receipt.due_at_ms) not in self.funding.expected_due
            or receipt.source_id != self.funding.source_id
            or (prior is not None and (prior["status"] != "UNAVAILABLE" or receipt.status == "UNAVAILABLE"))
        ):
            raise SimInputError("funding schedule/source/duplicate conflict")
        st["funding"][key] = _plain(asdict(receipt))
        st["funding"][key]["earlier_unavailable_receipts"] = (
            []
            if prior is None
            else [
                *prior.get("earlier_unavailable_receipts", []),
                {k: v for k, v in prior.items() if k != "earlier_unavailable_receipts"},
            ]
        )
        if receipt.status == "UNAVAILABLE":
            return
        a = decode_account(st["account"])
        for pid, p in sorted(st["parents"].items()):
            if p["candidate"]["symbol"] != receipt.symbol:
                continue
            qty = self._quantity_due(p, receipt.due_at_ms)
            if qty <= 0:
                continue
            cashflow = (
                -qty
                * receipt.settlement_price
                * receipt.rate
                * (D(1) if p["candidate"]["side"] == "LONG" else D(-1))
            )
            event_id = f"funding:{pid}:{receipt.due_at_ms}"
            # Late known liability remains due even when its owning trade is flat.
            if any(x.intent_id == p["candidate"]["intent_id"] for x in a.positions):
                a = account_api.record_funding(
                    a,
                    intent_id=p["candidate"]["intent_id"],
                    event_id=event_id,
                    cashflow=cashflow,
                    at_ms=receipt.available_at_ms,
                )
            else:
                a = replace(
                    a,
                    cash=a.cash + cashflow,
                    realized_net_pnl=a.realized_net_pnl + cashflow,
                    events=(
                        *a.events,
                        account_api.AccountEvent(
                            event_id, ("LATE_KNOWN_FUNDING", key, cashflow, receipt.available_at_ms)
                        ),
                    ),
                )
        st["account"] = encode_account(a)

    @staticmethod
    def _quantity_due(parent, due):
        # Settlement precedes entry/exit commands at the same clock: pre-event exposure.
        return sum((D(q) for t, q in parent["exposure"] if t < due), ZERO)

    def _missing_funding(self, st, through):
        missing = []
        for symbol, due in self.funding.expected_due:
            if due > through or not any(
                p["candidate"]["symbol"] == symbol and self._quantity_due(p, due) > 0
                for p in st["parents"].values()
            ):
                continue
            key = f"{symbol}:{due}"
            if key not in st["funding"] or st["funding"][key]["status"] == "UNAVAILABLE":
                missing.append(key)
        return missing

    def _missing_protection_bars(self, st, through):
        missing = set()
        for p in st["parents"].values():
            if not p["exposure"] or p["candidate"]["plan"]["trailing_activation_price"] is None:
                continue
            first = p["exposure"][0][0] // 60_000 * 60_000
            last = min(through, p["closed_at"] if p["closed"] else through)
            if last - first > 1440 * 60_000:
                missing.add("PROTECTION_COVERAGE_SPAN_EXCEEDS_BOUND")
                continue
            for minute in range(first, last // 60_000 * 60_000, 60_000):
                close = minute + 60_000
                if self._quantity_due(p, close) > 0:
                    key = f"{p['candidate']['symbol']}:{minute}"
                    if key not in st["candles"]:
                        missing.add(key)
        return sorted(missing)

    def advance_to(self, *, now_ms, event_id):
        def fold(st):
            if self._due_inputs(st, now_ms):
                raise SimInputError("cannot bypass available retained inputs")
            self._drain(st, now_ms)
            return {"status": "ADVANCED"}

        return self._event(event_id, {"at": now_ms, "kind": "ADVANCE"}, now_ms, fold)

    def finish(self, *, now_ms, event_id):
        def fold(st):
            if st["cursor"] != len(self.binding.inputs) or now_ms < self.config["minutes"][-1] + 60_000:
                raise SimInputError("full source cursor and denominator horizon required")
            self._drain(st, now_ms)
            a = decode_account(st["account"])
            expected = {f"{s}:{m}" for m in self.config["minutes"] for s in UNIVERSE}
            missing_slots = sorted(expected - set(st["slots"]))
            unavailable_slots = sorted(
                k
                for k, v in st["slots"].items()
                if v["status"] == "UNAVAILABLE" or v.get("coverage") == "UNAVAILABLE"
            )
            missing_funding = self._missing_funding(st, now_ms)
            missing_protection = self._missing_protection_bars(st, now_ms)
            unresolved = bool(
                a.positions
                or a.unresolved_fills
                or a.barrier
                or a.protective_exit_pending
                or st["pending"]
                or missing_slots
                or unavailable_slots
                or missing_funding
                or missing_protection
                or any(r.terminal in {"OPEN", "UNKNOWN"} for r in a.reservations)
            )
            st["terminal"] = True
            return {
                "status": "UNRESOLVED" if unresolved else "COMPLETE",
                "missing_slots": missing_slots,
                "unavailable_slots": unavailable_slots,
                "denominator_cells": len(expected),
                "coverage_sha256": digest(st["slots"]),
                "missing_funding": missing_funding,
                "missing_protection_bars": missing_protection,
                "known_cash": str(a.cash),
                "net_return": None if unresolved else str(a.net_return),
                "qualified_economics": None,
                "natural_closes": sum(p["closed"] for p in st["parents"].values()),
                "hypotheses": len(st["parents"]),
                "model_calls": "NOT_PERFORMED_BY_RUNNER",
                "historical_risk_overrun": a.historical_risk_overrun,
                "source_authentication": False,
                "trading_authority": "NONE",
            }

        return self._event(event_id, {"kind": "FINISH", "at": now_ms}, now_ms, fold)


def replace_liquidity(liq, command, outcome, arrival):
    return LiquidityState.model_validate(
        liq.model_dump(mode="python")
        | {
            "last_as_of_ms": arrival,
            "last_arrival_at_ms": arrival,
            "assumptions_sha256": outcome.assumptions_sha256,
            "barrier_reason": outcome.reason,
            "receipts": (
                *liq.receipts,
                CommandReceipt(
                    command_id=command.command_id,
                    command_sha256=command.fingerprint(),
                    assumptions_sha256=outcome.assumptions_sha256,
                    outcome=outcome,
                ),
            ),
        }
    )
