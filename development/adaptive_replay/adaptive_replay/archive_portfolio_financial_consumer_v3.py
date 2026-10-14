"""Atomic non-resetting modeled archive portfolio lifecycle, never admission.

Every original quote is marked. Own modeled command/book/debit views reuse
only the pure one-level depth-walk arithmetic; no AcceptedBookFrame, receive
clock or observed venue execution is fabricated. Real archive entry requires
a future reviewed native candidate/source bridge and currently fails closed.
Fixture entry plans exercise the connected financial lifecycle, not strategy
or economic qualification. The frozen stream's five-day/25-source capability
does not cover a sixth transaction-day exit tail.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import asdict, dataclass, replace
from decimal import ROUND_FLOOR, Context, Decimal, localcontext
from pathlib import Path

from kairos_execution.simulation import fill_model
from kairos_execution.simulation import models as fill_models
from kairos_execution.simulation.models import ConsumedDepth, FillAssumptions

from . import adaptive_sim_account as api
from . import archive_financial_consumer_v3, archive_portfolio_stream_v3, sim_financial_journal_v3
from .account_event_context_v3 import current_native_event_context
from .archive_batch_cursor_v3 import ArchiveCursorCheckpointV3, _read_json
from .archive_financial_consumer_v3 import ArchiveFundingCalendarV3, ArchiveFundingReceiptV3, _plain
from .archive_market_clock_v3 import MAX_CLOCK_MS, ArchiveBBOQuoteV3, archive_quote_v3
from .archive_portfolio_stream_v3 import (
    ArchivePortfolioBoundaryV3,
    ArchivePortfolioCheckpointV3,
    ArchivePortfolioOperationV3,
    ArchivePortfolioSealV3,
    ArchivePortfolioSourceCheckpointV3,
    ArchivePortfolioStreamV3,
)
from .bookticker_archive_stream_v3 import MAX_MANIFEST_BYTES, _canonical, _day_start_ms, _sha
from .sim_account_core_codec_v3 import decode_account_core, encode_account_core
from .sim_financial_journal_v3 import FinancialCheckpointV3, SimFinancialJournalV3, initial_ledger_reference
from .sim_state_journal import JournalIdentity

SCHEMA = "kairos.research.archive-portfolio-financial.v3"
ARITHMETIC = Context(prec=96)
ZERO = Decimal(0)
MAX_PLANS = 128
MAX_COMMANDS = 1024
MAX_DEBITS = 4096


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _ms(value):
    if type(value) is not int or not 0 <= value <= MAX_CLOCK_MS:
        raise ValueError("exact bounded modeled clock required")


def _positive(value):
    if type(value) is not Decimal or not value.is_finite() or value <= 0 or value > Decimal("1e18"):
        raise ValueError("finite positive exact modeled Decimal required")


def _implementation():
    paths = [
        Path(__file__),
        Path(fill_model.__file__),
        Path(fill_models.__file__),
        Path(api.__file__),
        Path(archive_portfolio_stream_v3.__file__),
        Path(archive_financial_consumer_v3.__file__),
        Path(sim_financial_journal_v3.__file__),
        Path(encode_account_core.__code__.co_filename),
        Path(current_native_event_context.__code__.co_filename),
    ]
    return _hash(
        [
            archive_financial_consumer_v3._implementation(),
            [[str(p.absolute()), hashlib.sha256(p.read_bytes()).hexdigest()] for p in paths],
        ]
    )


def _checkpoint(document):
    doc = dict(document)
    doc["source_vector"] = tuple(
        ArchivePortfolioSourceCheckpointV3(item["source_key"], ArchiveCursorCheckpointV3(**item["cursor"]))
        for item in doc["source_vector"]
    )
    return ArchivePortfolioCheckpointV3(**doc)


@dataclass(frozen=True, slots=True)
class ArchiveExecutionModelV3:
    symbol: str
    assumptions: FillAssumptions
    maximum_order_price: Decimal

    def __post_init__(self):
        if self.symbol not in api.SYMBOLS or type(self.assumptions) is not FillAssumptions:
            raise ValueError("exact modeled symbol and immutable assumptions required")
        _positive(self.maximum_order_price)
        if self.maximum_order_price % self.assumptions.price_tick:
            raise ValueError("maximum modeled order price must follow tick rule")

    @property
    def document(self):
        return {
            "symbol": self.symbol,
            "assumptions": self.assumptions.model_dump(mode="json"),
            "maximum_order_price": str(self.maximum_order_price),
            "historical_frame_latency": "NOT_OBSERVED_NOT_AN_ADMISSION_CHECK",
        }


@dataclass(frozen=True, slots=True)
class ArchiveFixtureEntryV3:
    intent_id: str
    symbol: str
    side: str
    stop_price: Decimal
    target_price: Decimal
    price_cap: Decimal
    worst_entry_price: Decimal
    worst_notional_price: Decimal
    eligible_at_ms: int
    expires_at_ms: int
    max_holding_ms: int
    trailing_activation_price: Decimal | None
    trailing_distance: Decimal | None
    producer_seal_sha256: str
    original_parent_sha256: str
    original_candidate_sha256: str
    proof_kind: str = "TEST_FIXTURE_NOT_NATIVE_V3_ADMISSION"

    def __post_init__(self):
        api._id(self.intent_id, "fixture intent")
        if (
            self.symbol not in api.SYMBOLS
            or self.side not in {"LONG", "SHORT"}
            or self.proof_kind != "TEST_FIXTURE_NOT_NATIVE_V3_ADMISSION"
        ):
            raise ValueError("fixture plan is not genuine native V3 admission")
        for value in (
            self.stop_price,
            self.target_price,
            self.price_cap,
            self.worst_entry_price,
            self.worst_notional_price,
        ):
            _positive(value)
        for value in (self.eligible_at_ms, self.expires_at_ms, self.max_holding_ms):
            _ms(value)
        if not self.eligible_at_ms < self.expires_at_ms or self.max_holding_ms == 0:
            raise ValueError("positive causal entry/holding lifetime required")
        if not (
            self.stop_price < self.worst_entry_price < self.target_price
            if self.side == "LONG"
            else self.target_price < self.worst_entry_price < self.stop_price
        ):
            raise ValueError("directional unchanged protection plan required")
        if (self.trailing_activation_price is None) != (self.trailing_distance is None):
            raise ValueError("both trailing parameters or neither required")
        if self.trailing_distance is not None:
            _positive(self.trailing_distance)
            _positive(self.trailing_activation_price)
        for value in (self.producer_seal_sha256, self.original_parent_sha256, self.original_candidate_sha256):
            _sha(value, "fixture provenance commitment")


@dataclass(frozen=True, slots=True)
class ArchiveClosedProtectionV3:
    symbol: str
    close_at_ms: int
    close: Decimal
    original_candle_sha256: str

    def __post_init__(self):
        if self.symbol not in api.SYMBOLS:
            raise ValueError("fixed protection symbol required")
        _ms(self.close_at_ms)
        _positive(self.close)
        _sha(self.original_candle_sha256, "original closed candle SHA256")


@dataclass(frozen=True, slots=True)
class ArchiveFundingDueV3:
    symbol: str
    due_at_ms: int

    def __post_init__(self):
        if self.symbol not in api.SYMBOLS:
            raise ValueError("fixed funding symbol required")
        _ms(self.due_at_ms)


@dataclass(frozen=True, slots=True)
class ArchiveFundingDeliveryV3:
    symbol: str
    receipt: ArchiveFundingReceiptV3

    def __post_init__(self):
        if self.symbol not in api.SYMBOLS or type(self.receipt) is not ArchiveFundingReceiptV3:
            raise ValueError("typed symbol-bound original funding receipt required")


@dataclass(frozen=True, slots=True)
class ArchiveServiceCostV3:
    cost_id: str
    amount: Decimal | None

    def __post_init__(self):
        api._id(self.cost_id, "cost")
        if self.amount is not None and (
            type(self.amount) is not Decimal or not self.amount.is_finite() or self.amount < 0
        ):
            raise ValueError("known exact nonnegative cost or explicit unknown required")


@dataclass(frozen=True, slots=True)
class ArchiveAdvanceV3:
    reason: str

    def __post_init__(self):
        api._id(self.reason, "deadline reason")


@dataclass(frozen=True, slots=True)
class ArchivePortfolioActionV3:
    boundary_id: str
    at_ms: int
    source_sha256: str
    parameters: object

    def __post_init__(self):
        api._id(self.boundary_id, "boundary")
        _ms(self.at_ms)
        _sha(self.source_sha256, "boundary original source SHA256")
        _ = self.kind

    @property
    def kind(self):
        mapping = {
            ArchiveFixtureEntryV3: "CONTROL",
            ArchiveServiceCostV3: "CONTROL",
            ArchiveClosedProtectionV3: "CANDLE",
            ArchiveFundingDueV3: "FUNDING",
            ArchiveFundingDeliveryV3: "FUNDING",
            ArchiveAdvanceV3: "DEADLINE",
        }
        if type(self.parameters) not in mapping:
            raise ValueError("typed exact modeled boundary action required")
        return mapping[type(self.parameters)]

    @property
    def document(self):
        return {
            "namespace": SCHEMA,
            "boundary_id": self.boundary_id,
            "at_ms": self.at_ms,
            "source_sha256": self.source_sha256,
            "clock_evidence": "MODELED_REFERENCE",
            "parameter_type": type(self.parameters).__name__,
            "parameters": _plain(asdict(self.parameters)),
        }

    @property
    def boundary(self):
        return ArchivePortfolioBoundaryV3(
            self.boundary_id, self.kind, self.at_ms, _canonical(self.document), self.source_sha256
        )


@dataclass(frozen=True, slots=True)
class ModeledIOCCommandV3:
    command_id: str
    symbol: str
    side: str
    quantity: Decimal
    price_cap: Decimal
    submitted_at_ms: int
    eligible_at_ms: int
    expires_at_ms: int

    def __post_init__(self):
        api._id(self.command_id, "modeled command")
        if self.symbol not in api.SYMBOLS or self.side not in {"BUY", "SELL"}:
            raise ValueError("typed modeled command side/symbol required")
        _positive(self.quantity)
        _positive(self.price_cap)
        for value in (self.submitted_at_ms, self.eligible_at_ms, self.expires_at_ms):
            _ms(value)
        if self.expires_at_ms < self.submitted_at_ms:
            raise ValueError("modeled command expiry before submission")


@dataclass(frozen=True, slots=True)
class _Level:
    price: Decimal
    quantity: Decimal

    def __post_init__(self):
        _positive(self.price)
        _positive(self.quantity)


@dataclass(frozen=True, slots=True)
class _ModeledBook:
    bids: tuple[_Level, ...]
    asks: tuple[_Level, ...]

    def __post_init__(self):
        if (
            type(self.bids) is not tuple
            or type(self.asks) is not tuple
            or len(self.bids) != 1
            or len(self.asks) != 1
            or any(type(x) is not _Level for x in (*self.bids, *self.asks))
            or self.bids[0].price >= self.asks[0].price
        ):
            raise ValueError("one-level immutable noncrossed modeled book required")


@dataclass(frozen=True, slots=True)
class _ModeledDebit:
    consumed_depth: tuple[ConsumedDepth, ...]

    def __post_init__(self):
        if (
            type(self.consumed_depth) is not tuple
            or len(self.consumed_depth) > MAX_DEBITS
            or any(type(x) is not ConsumedDepth for x in self.consumed_depth)
            or len({(x.side, x.price) for x in self.consumed_depth}) != len(self.consumed_depth)
        ):
            raise ValueError("bounded exact immutable cumulative price debits required")


@dataclass(frozen=True, slots=True)
class PreparedArchivePortfolioFinancialV3:
    before_financial: FinancialCheckpointV3
    operation: ArchivePortfolioOperationV3
    event_id: str

    @property
    def payload(self):
        return {
            "schema": SCHEMA,
            "kind": "ARCHIVE_PORTFOLIO_OPERATION",
            "clock_evidence": "MODELED_REFERENCE",
            "operation_kind": self.operation.kind,
            "operation_sha256": self.operation.sha256,
            "before": _plain(asdict(self.operation.before)),
            "after": _plain(asdict(self.operation.after)),
            "original_rows": len(self.operation.rows),
            "original_bytes": self.operation.raw_byte_count,
        }


class ArchivePortfolioFinancialConsumerV3:
    """One shared account/source/native transaction, no daily economic reset.

    Caller retains prepared before-financial plus exact stream pending anchor
    in its WAL. Exact open never adopts latest. This class does not invent the
    journal's postcommit/pre-external-checkpoint crash proof: driver must use
    its independently anchored exact-known-transition recovery contract.
    """

    def __init__(self, journal, seal, models, calendars, actions, config):
        if type(journal) is not SimFinancialJournalV3 or type(seal) is not ArchivePortfolioSealV3:
            raise ValueError("exact financial journal and portfolio seal required")
        self.journal, self.seal, self.models, self.calendars, self.actions, self.config = (
            journal,
            seal,
            models,
            calendars,
            actions,
            config,
        )
        self._objects = (journal, seal, models, calendars, actions)
        self._policy_sha = _hash(config)
        self._implementation_sha = self._implementation_id()
        self._functions = (
            fill_model._walk,
            api.mark_account,
            api.reserve_entry,
            api.record_entry_fill,
            api.resolve_entry,
            api.record_exit_fill,
            api.tighten_stop,
            api.request_protective_exit,
            api.record_funding,
            api.record_late_known_funding,
            api.debit_cost,
            api.set_barrier,
        )
        self._lock = threading.RLock()
        self._pending = None
        self._model = {item.symbol: item for item in models}
        self._source = {source.source_key: source for source in seal.sources}
        self._calendar = dict(calendars)
        self._action = {item.boundary_id: item for item in actions}
        snapshot = journal.snapshot()
        if (
            snapshot.state["config"] != config
            or journal.identity.policy_id != self._policy_sha
            or journal.identity.source_id != seal.sha256
            or journal.identity.implementation_id != self._implementation_sha
        ):
            raise ValueError("sealed source/model/action/financial identity conflict")
        core, _ = decode_account_core(snapshot.state["account"])
        original_policy = config["initial_core"]["policy"]
        policy = api.AccountPolicy(
            **{
                k: Decimal(v)
                if k in {"quantity_step", "entry_fee_bps", "exit_fee_bps", "adverse_exit_slippage_bps"}
                else v
                for k, v in original_policy.items()
            }
        )
        if (
            journal.owner_id != config["owner_id"]
            or journal.account_id != config["account_id"]
            or journal.allowed_quantity_steps != tuple(sorted({m.assumptions.quantity_step for m in models}))
            or replace(core.policy, quantity_step=policy.quantity_step) != policy
            or core.initial_equity != Decimal(config["initial_core"]["initial_equity"])
        ):
            raise ValueError("financial owner/account/policy/quantity-rule contract conflict")
        self._stream = ArchivePortfolioStreamV3(
            seal,
            expected_seal_sha256=seal.sha256,
            expected_checkpoint=_checkpoint(snapshot.state["portfolio_checkpoint"]),
        )

    @classmethod
    def _implementation_id(cls):
        return _implementation()

    @classmethod
    def _profile_config(cls, profile, **_):
        if profile is not None:
            raise ValueError("default V3 is fixture-only; explicit new consumer profile required")
        return {}

    @classmethod
    def _action_entries(cls, actions, *, seal, fixture, models, profile):
        if (
            type(actions) is not tuple
            or any(type(a) is not ArchivePortfolioActionV3 for a in actions)
            or tuple(a.boundary for a in actions) != seal.boundaries
        ):
            raise ValueError(
                "every sealed boundary must bind one exact typed financial action, no opaque skip"
            )
        entries = [(a, a.parameters) for a in actions if type(a.parameters) is ArchiveFixtureEntryV3]
        if entries and not fixture:
            raise ValueError(
                "NATIVE_CANDIDATE_BRIDGE_UNAVAILABLE: fixture commands are not native V3 admission"
            )
        return entries

    def _entry_view(self, state, action):
        return action.parameters if type(action.parameters) is ArchiveFixtureEntryV3 else None

    @classmethod
    def create(
        cls,
        path,
        *,
        campaign_id,
        owner_id,
        account_id,
        seal,
        models,
        calendars,
        actions,
        initial_account,
        entry_start_ms,
        entry_end_ms,
        retained_end_ms,
        expected_cost_ids,
        maximum_exit_attempts,
        storage_bounds,
        profile=None,
    ):
        for value in (campaign_id, owner_id, account_id):
            api._id(value, "owned financial identifier")
        for value in (entry_start_ms, entry_end_ms, retained_end_ms):
            _ms(value)
        if (
            type(seal) is not ArchivePortfolioSealV3
            or not _day_start_ms(seal.days[0]) <= entry_start_ms < entry_end_ms <= retained_end_ms
        ):
            raise ValueError("separate exact entry and retained-source windows required")
        transaction_end = _day_start_ms(seal.days[-1]) + 86400000
        processing_end = max(
            transaction_end,
            *(
                b.last_event_ms + source.clock.feed_delay_ms + source.clock.processing_delay_ms
                for source in seal.sources
                for b in source.index.blocks
            ),
            *(boundary.at_ms for boundary in seal.boundaries),
        )
        if retained_end_ms != processing_end:
            raise ValueError(
                "EXACT_PROCESSING_END_REQUIRED: E/model-delay overhang is not another transaction day"
            )
        if (
            entry_start_ms < _day_start_ms(seal.entry_days[0])
            or entry_end_ms > _day_start_ms(seal.entry_days[-1]) + 86400000
        ):
            raise ValueError("entry window outside exact independently sealed entry-day roster")
        if seal.boundary_tie_order != ("FUNDING", "CANDLE", "DEADLINE", "CONTROL"):
            raise ValueError("financial source/command/sizing tie order must be explicitly pinned")
        if any(
            b.last_event_ms + source.clock.feed_delay_ms + source.clock.processing_delay_ms > retained_end_ms
            for source in seal.sources
            for b in source.index.blocks
        ) or any(b.at_ms > retained_end_ms for b in seal.boundaries):
            raise ValueError("original availability/boundary beyond retained end; never filter tail rows")
        if (
            type(models) is not tuple
            or tuple(x.symbol for x in models) != seal.symbols
            or any(type(x) is not ArchiveExecutionModelV3 for x in models)
        ):
            raise ValueError("exact frozen model for every declared symbol required")
        if (
            type(calendars) is not tuple
            or tuple(x[0] for x in calendars) != seal.symbols
            or any(
                type(x) is not tuple or len(x) != 2 or type(x[1]) is not ArchiveFundingCalendarV3
                for x in calendars
            )
        ):
            raise ValueError("all symbol funding calendars required, including unknown schedules")
        if type(initial_account) is not api.SimAccount or initial_account.events:
            raise ValueError("pure initial core without historical event adoption required")
        if any(p.symbol not in seal.symbols for p in initial_account.positions) or any(
            r.symbol not in seal.symbols for r in initial_account.reservations
        ):
            raise ValueError("initial exposure outside complete declared symbol roster")
        if type(maximum_exit_attempts) is not int or not 1 <= maximum_exit_attempts <= 16:
            raise ValueError("explicit bounded protective exit attempts required")
        if type(expected_cost_ids) is not tuple or expected_cost_ids != tuple(sorted(set(expected_cost_ids))):
            raise ValueError("exact presealed service liability roster required")
        for item in expected_cost_ids:
            api._id(item, "cost roster")
        if len(expected_cost_ids) > MAX_COMMANDS:
            raise ValueError("cost roster capacity exceeded")
        fixture = all(
            _read_json(
                source.index.source_root / "manifest.json",
                MAX_MANIFEST_BYTES,
                source.index.source_manifest_sha256,
            )[0]["evidence_kind"]
            == "TEST_FIXTURE"
            for source in seal.sources
        )
        if not fixture and (
            initial_account != api.new_account(initial_account.initial_equity, initial_account.policy)
            or any(calendar.evidence_kind == "TEST_FIXTURE" for _, calendar in calendars)
            or entry_end_ms - entry_start_ms != 5 * 86400000
        ):
            raise ValueError(
                "real comparison requires flat genesis, nonfixture calendars and exact five-day entry window"
            )
        for model in models:
            policy, assumption = initial_account.policy, model.assumptions
            if (
                policy.entry_fee_bps != assumption.taker_fee_bps
                or policy.exit_fee_bps != assumption.taker_fee_bps
                or policy.adverse_exit_slippage_bps != assumption.adverse_slippage_bps
                or policy.maximum_mark_age_ms != assumption.maximum_book_age_ms
            ):
                raise ValueError("shared account costs/freshness must match every frozen execution model")
        if initial_account.policy.quantity_step not in {m.assumptions.quantity_step for m in models}:
            raise ValueError("initial quantity step outside frozen symbol-rule roster")
        profile_config = cls._profile_config(
            profile,
            actions=actions,
            seal=seal,
            fixture=fixture,
            models=models,
            expected_cost_ids=expected_cost_ids,
        )
        entries = cls._action_entries(actions, seal=seal, fixture=fixture, models=models, profile=profile)
        if len(entries) > MAX_PLANS or len({p.intent_id for _, p in entries}) != len(entries):
            raise ValueError("bounded unique parent/intent roster required")
        for action, p in entries:
            model = next((m for m in models if m.symbol == p.symbol), None)
            if (
                model is None
                or not entry_start_ms <= action.at_ms < entry_end_ms
                or not p.eligible_at_ms <= action.at_ms <= p.expires_at_ms
            ):
                raise ValueError("entry outside actual causal slot/declared entry window")
            if (
                any(
                    price % model.assumptions.price_tick
                    for price in (p.stop_price, p.target_price, p.price_cap)
                )
                or p.price_cap > model.maximum_order_price
                or not (
                    p.stop_price < p.price_cap < p.target_price
                    if p.side == "LONG"
                    else p.target_price < p.price_cap < p.stop_price
                )
            ):
                raise ValueError("fixture candidate/order protection violates frozen symbol rules")
        if len(entries) * (1 + maximum_exit_attempts) > MAX_COMMANDS:
            raise ValueError("full planned entry/protective-command roster cannot fit without eviction")
        expected_funding = []
        for symbol, calendar in calendars:
            for due in calendar.expected_due:
                if not _day_start_ms(seal.days[0]) <= due <= retained_end_ms:
                    raise ValueError("funding due outside complete retained window")
                expected_funding.append((symbol, due))
            for receipt in calendar.receipts:
                if receipt.modeled_available_at_ms > retained_end_ms:
                    raise ValueError("frozen late funding receipt beyond retained window")
        dues = [
            (a.parameters.symbol, a.parameters.due_at_ms)
            for a in actions
            if type(a.parameters) is ArchiveFundingDueV3
        ]
        deliveries = [
            (a.parameters.symbol, a.parameters.receipt)
            for a in actions
            if type(a.parameters) is ArchiveFundingDeliveryV3
        ]
        if sorted(dues) != sorted(expected_funding) or sorted(
            deliveries, key=lambda x: (x[0], x[1].modeled_available_at_ms, x[1].due_at_ms)
        ) != sorted(
            [(s, r) for s, c in calendars for r in c.receipts],
            key=lambda x: (x[0], x[1].modeled_available_at_ms, x[1].due_at_ms),
        ):
            raise ValueError("every funding due and original resolution needs an explicit boundary")
        for action in actions:
            p = action.parameters
            if type(p) is ArchiveFundingDueV3 and action.at_ms != p.due_at_ms:
                raise ValueError("funding entitlement boundary must retain exact due clock")
            if type(p) is ArchiveFundingDeliveryV3 and action.at_ms != p.receipt.modeled_available_at_ms:
                raise ValueError("funding delivery must retain explicit modeled availability")
            if type(p) is ArchiveClosedProtectionV3 and (
                p.symbol not in seal.symbols
                or p.close_at_ms > action.at_ms
                or p.original_candle_sha256 != action.source_sha256
            ):
                raise ValueError("exact original closed-source and availability proof required")
            if type(p) is ArchiveServiceCostV3 and p.cost_id not in expected_cost_ids:
                raise ValueError("extra service cost cannot escape sealed expected roster")
        if type(storage_bounds) is not dict or set(storage_bounds) != set(
            sim_financial_journal_v3.DEFAULT_LIMITS
        ):
            raise ValueError("all five durable financial resource bounds must be explicit")
        rows = sum(source.index.row_count for source in seal.sources)
        required_native = rows + len(actions) * 8 + len(entries) * (maximum_exit_attempts * 4 + 8) + 1
        if (
            type(storage_bounds["max_native_event_rows"]) is not int
            or storage_bounds["max_native_event_rows"] < required_native
            or type(storage_bounds["max_event_rows"]) is not int
            or storage_bounds["max_event_rows"] < rows + len(actions) + 1
        ):
            raise ValueError(
                "durable capacity must retain every source row, action, failure and bounded lifecycle event"
            )
        initial_cursor = ArchivePortfolioStreamV3(seal, expected_seal_sha256=seal.sha256).checkpoint()
        config = {
            "schema": SCHEMA,
            "clock_evidence": "MODELED_REFERENCE",
            "portfolio_seal_sha256": seal.sha256,
            "models": [m.document for m in models],
            "funding": [[s, _plain(asdict(c))] for s, c in calendars],
            "actions": [a.document for a in actions],
            "initial_core": _plain(asdict(initial_account)),
            "owner_id": owner_id,
            "account_id": account_id,
            "entry_start_ms": entry_start_ms,
            "entry_end_ms": entry_end_ms,
            "retained_end_ms": retained_end_ms,
            "transaction_roster_end_ms": transaction_end,
            "processing_end_ms": processing_end,
            "expected_cost_ids": list(expected_cost_ids),
            "maximum_exit_attempts": maximum_exit_attempts,
            "storage_bounds": dict(storage_bounds),
            "implementation": cls._implementation_id(),
            "accepted_historical_inputs": False,
            "economics_qualified": False,
            "execution_scope": "MODELED_TOP_OF_BOOK_LIFECYCLE_NATIVE_REDUCERS_FIXTURE_ENTRY_ONLY",
            "tail_capability": seal.limits.window_profile,
            "entry_days": list(seal.entry_days),
            "retained_days": list(seal.days),
            "resource_profile": {
                "required_native_rows": required_native,
                "required_original_rows": rows,
                "database_capacity": "UNMEASURED_FAIL_CLOSED",
                "max_plans": MAX_PLANS,
                "max_commands": MAX_COMMANDS,
                "max_distinct_side_prices_per_symbol": MAX_DEBITS,
            },
        }
        config.update(profile_config)
        identity = JournalIdentity(campaign_id, seal.sha256, _hash(config), config["implementation"])
        ledger = initial_ledger_reference(identity, owner_id=owner_id, account_id=account_id)
        state = {
            "config": config,
            "account": encode_account_core(initial_account, ledger),
            "clock": initial_cursor.last_clock_ms,
            "cursor": 0,
            "portfolio_checkpoint": _plain(asdict(initial_cursor)),
            "latest": {},
            "debits": {s: {} for s in seal.symbols},
            "liquidity": {},
            "parents": {},
            "unowned_protection": {p.intent_id: "NATIVE_PLAN_UNAVAILABLE" for p in initial_account.positions},
            "pending_commands": {},
            "command_count": 0,
            "funding": {},
            "service_costs": {},
            "native_mark_count": 0,
            "boundary_count": 0,
            "terminal": False,
            "last_outcome": None,
        }
        journal = SimFinancialJournalV3.create(
            path,
            identity=identity,
            owner_id=owner_id,
            account_id=account_id,
            initial_state=state,
            initial_clock_ms=initial_cursor.last_clock_ms,
            allowed_quantity_steps=tuple(sorted({m.assumptions.quantity_step for m in models})),
            **storage_bounds,
        )
        try:
            return cls(journal, seal, models, calendars, actions, config)
        except BaseException:
            journal.close()
            raise

    @classmethod
    def open(cls, path, *, identity, expected_checkpoint, seal, models, calendars, actions, config):
        journal = SimFinancialJournalV3.open(
            path,
            identity=identity,
            expected_checkpoint=expected_checkpoint,
            owner_id=config["owner_id"],
            account_id=config["account_id"],
            allowed_quantity_steps=tuple(sorted({m.assumptions.quantity_step for m in models})),
            **config["storage_bounds"],
        )
        try:
            return cls(journal, seal, models, calendars, actions, config)
        except BaseException:
            journal.close()
            raise

    def _guard(self):
        if str(ARITHMETIC) != str(Context(prec=96)):
            raise ValueError("exact frozen Decimal96 modeled arithmetic required")
        if (
            any(
                a is not b
                for a, b in zip(
                    (self.journal, self.seal, self.models, self.calendars, self.actions),
                    self._objects,
                    strict=True,
                )
            )
            or _hash(self.config) != self._policy_sha
            or self.config["implementation"] != self._implementation_sha
            or self.config["models"] != [m.document for m in self.models]
            or self.config["funding"] != [[s, _plain(asdict(c))] for s, c in self.calendars]
            or self.config["actions"] != [a.document for a in self.actions]
            or self.config["portfolio_seal_sha256"] != self.seal.sha256
            or self._functions
            != (
                fill_model._walk,
                api.mark_account,
                api.reserve_entry,
                api.record_entry_fill,
                api.resolve_entry,
                api.record_exit_fill,
                api.tighten_stop,
                api.request_protective_exit,
                api.record_funding,
                api.record_late_known_funding,
                api.debit_cost,
                api.set_barrier,
            )
        ):
            raise ValueError("sealed financial/source/action/reducer runtime drift")

    def _load(self, state):
        account, ref = decode_account_core(state["account"])
        self.journal.validate_ledger_reference(ref)
        if current_native_event_context(account) is None:
            raise ValueError("owned atomic native event context required")
        return account

    def _queue_exit(self, state, account, intent, now, reason):
        parent = state["parents"][intent]
        position = next((p for p in account.positions if p.intent_id == intent), None)
        if position is None:
            return account
        urgency = {None: 0, "TARGET": 1, "TIMEOUT": 2, "STOP": 3, "TRAILING_STOP": 3}
        if urgency[reason] > urgency[parent["exit_reason"]]:
            parent["exit_reason"] = reason
            account = api.request_protective_exit(
                account, intent_id=intent, event_id=f"portfolio-protect:{intent}:{reason}", reason=reason
            )
        if any(command["intent_id"] == intent for command in state["pending_commands"].values()):
            return account
        if parent["exit_attempts"] >= self.config["maximum_exit_attempts"]:
            return api.set_barrier(
                account, event_id=f"portfolio-exhaust:{intent}", reason="PROTECTIVE_EXIT_ATTEMPTS_EXHAUSTED"
            )
        parent["exit_attempts"] += 1
        model = self._model[position.symbol]
        target = Decimal(parent["plan"]["target_price"])
        cap = (
            target
            if parent["exit_reason"] == "TARGET"
            else model.assumptions.price_tick
            if position.side == "LONG"
            else model.maximum_order_price
        )
        command = ModeledIOCCommandV3(
            f"portfolio-exit:{intent}:{parent['exit_attempts']}",
            position.symbol,
            "SELL" if position.side == "LONG" else "BUY",
            position.quantity,
            cap,
            now,
            now,
            now + model.assumptions.latency_ms,
        )
        self._queue(state, command, intent, "EXIT", parent["exit_reason"])
        return account

    def _queue(self, state, command, intent, purpose, reason):
        if state["command_count"] >= MAX_COMMANDS:
            raise ValueError("modeled command resource cap exhausted; nothing discarded")
        state["command_count"] += 1
        state["pending_commands"][command.command_id] = {
            "command": _plain(asdict(command)),
            "intent_id": intent,
            "purpose": purpose,
            "reason": reason,
        }

    def _evaluate(self, state, command, arrival):
        model = self._model[command.symbol]
        policy = model.assumptions
        quote_doc = state["latest"].get(command.symbol)
        base = {
            "namespace": SCHEMA,
            "execution_kind": "MODELED_REFERENCE",
            "venue_execution_observed": False,
            "command": _plain(asdict(command)),
            "command_sha256": _hash(_plain(asdict(command))),
            "model_sha256": policy.fingerprint(),
            "arrival_at_ms": arrival,
            "original_line_sha256": None,
            "filled_quantity": "0",
            "fee": "0",
            "average_price": None,
        }
        reason = None
        if command.submitted_at_ms < command.eligible_at_ms or arrival < command.eligible_at_ms:
            reason = "NOT_YET_ELIGIBLE"
        elif arrival > command.expires_at_ms:
            reason = "COMMAND_EXPIRED"
        elif (
            command.quantity % policy.quantity_step
            or command.price_cap % policy.price_tick
            or command.price_cap > model.maximum_order_price
        ):
            reason = "COMMAND_RULE_MISMATCH"
        elif quote_doc is None:
            reason = "NO_MODELED_QUOTE"
        if reason is not None:
            return base | {"status": "NO_FILL", "reason": reason}
        quote = ArchiveBBOQuoteV3(
            **{
                key: Decimal(value) if key in {"bid_price", "ask_price", "bid_qty", "ask_qty"} else value
                for key, value in quote_doc.items()
            }
        )
        key = f"{quote.symbol}:{quote.transaction_day}"
        source = self._source.get(key)
        if source is None or quote.symbol != command.symbol:
            raise ValueError("model command and exact retained archive source disagree")
        original = self._stream._readers[key].lookup_row(quote.row_index)
        if (
            archive_quote_v3(
                original, clock=source.clock, source_manifest_sha256=source.index.source_manifest_sha256
            )
            != quote
        ):
            raise ValueError("model fill quote differs from the exact original row/source/clock")
        base["original_line_sha256"] = quote.original_line_sha256
        if quote.modeled_available_at_ms > arrival or quote.event_at_ms > arrival:
            return base | {"status": "BLOCKED", "reason": "MODEL_QUOTE_NOT_AVAILABLE_AT_ARRIVAL"}
        if arrival - quote.event_at_ms > policy.maximum_book_age_ms:
            return base | {"status": "BLOCKED", "reason": "STALE_MODELED_BOOK"}
        if any(price % policy.price_tick for price in (quote.bid_price, quote.ask_price)) or any(
            quantity % policy.quantity_step for quantity in (quote.bid_qty, quote.ask_qty)
        ):
            return base | {"status": "BLOCKED", "reason": "ARCHIVE_BOOK_RULE_MISMATCH"}
        if max(quote.bid_price, quote.ask_price) > model.maximum_order_price:
            return base | {"status": "BLOCKED", "reason": "ARCHIVE_BOOK_ABOVE_SEALED_PRICE_CEILING"}
        book = _ModeledBook(
            (_Level(quote.bid_price, quote.bid_qty),), (_Level(quote.ask_price, quote.ask_qty),)
        )
        debit = _ModeledDebit(
            tuple(
                ConsumedDepth(side=k.split(":", 1)[0], price=Decimal(k.split(":", 1)[1]), quantity=Decimal(v))
                for k, v in sorted(state["debits"][command.symbol].items())
            )
        )
        with localcontext(ARITHMETIC):
            fills, consumed = fill_model._walk(command, book, policy, debit)
            qty = sum((f.quantity for f in fills), ZERO)
            fees = sum((f.fee_quote for f in fills), ZERO)
            notional = sum((f.quantity * f.execution_price for f in fills), ZERO)
            if len(consumed) > MAX_DEBITS:
                raise ValueError(
                    "cumulative distinct-price debit capacity exhausted; no replenishment/eviction"
                )
            state["debits"][command.symbol] = {
                f"{item.side}:{item.price}": str(item.quantity) for item in consumed
            }
            self._update_liquidity(state, quote)
            return base | {
                "status": "NO_FILL" if qty == 0 else "FILLED" if qty == command.quantity else "PARTIAL",
                "reason": "MODELED_TOP_OF_BOOK_IOC",
                "filled_quantity": str(qty),
                "fee": str(fees),
                "average_price": str(notional / qty) if qty else None,
                "level_fills": [f.model_dump(mode="json") for f in fills],
            }

    def _update_liquidity(self, state, quote):
        policy = self._model[quote.symbol].assumptions
        debits = state["debits"][quote.symbol]

        def remaining(side, price, quantity):
            debit = next(
                (
                    Decimal(v)
                    for k, v in debits.items()
                    if k.split(":", 1)[0] == side and Decimal(k.split(":", 1)[1]) == price
                ),
                ZERO,
            )
            return str(max(ZERO, quantity * policy.depth_participation_fraction - debit))

        state["liquidity"][quote.symbol] = {
            "scope": "TOP_OF_BOOK_ONLY_MODELED_REFERENCE",
            "policy": "SESSION_PRICE_DEBIT_NO_REPLENISHMENT",
            "source_manifest_sha256": quote.source_manifest_sha256,
            "row_index": quote.row_index,
            "original_line_sha256": quote.original_line_sha256,
            "bid_remaining": remaining("BID", quote.bid_price, quote.bid_qty),
            "ask_remaining": remaining("ASK", quote.ask_price, quote.ask_qty),
            "distinct_price_debits": len(debits),
            "historical_received_at_ms": None,
            "historical_persisted_at_ms": None,
        }

    def _drain(self, state, account, through):
        while True:
            positions = {p.intent_id: p for p in account.positions}
            deadlines = [
                (parent["first_fill_at_ms"] + parent["plan"]["max_holding_ms"], intent)
                for intent, parent in state["parents"].items()
                if intent in positions
                and parent["first_fill_at_ms"] is not None
                and parent["exit_reason"] in {None, "TARGET"}
            ]
            timeout = min(deadlines, default=None)
            commands = sorted(
                state["pending_commands"].items(),
                key=lambda item: (
                    item[1]["command"]["submitted_at_ms"]
                    + self._model[item[1]["command"]["symbol"]].assumptions.latency_ms,
                    0 if item[1]["purpose"] == "EXIT" else 1,
                    item[0],
                ),
            )
            arrival = (
                None
                if not commands
                else commands[0][1]["command"]["submitted_at_ms"]
                + self._model[commands[0][1]["command"]["symbol"]].assumptions.latency_ms
            )
            if timeout is not None and timeout[0] <= through and (arrival is None or timeout[0] <= arrival):
                account = self._queue_exit(state, account, timeout[1], timeout[0], "TIMEOUT")
                continue
            if arrival is None or arrival > through:
                return account
            command_id, item = commands[0]
            command = ModeledIOCCommandV3(
                **{k: Decimal(v) if k in {"quantity", "price_cap"} else v for k, v in item["command"].items()}
            )
            outcome = self._evaluate(state, command, arrival)
            del state["pending_commands"][command_id]
            parent = state["parents"][item["intent_id"]]
            parent["outcomes"].append(outcome)
            qty = Decimal(outcome["filled_quantity"])
            if qty:
                common = {
                    "fill_id": f"fill:{command_id}",
                    "quantity": qty,
                    "average_price": Decimal(outcome["average_price"]),
                    "fee": Decimal(outcome["fee"]),
                    "at_ms": arrival,
                }
                if item["purpose"] == "ENTRY":
                    account, _ = api.record_entry_fill(
                        account, reservation_id=f"r:{item['intent_id']}", **common
                    )
                    parent["first_fill_at_ms"] = arrival
                else:
                    account, _ = api.record_exit_fill(account, intent_id=item["intent_id"], **common)
            if item["purpose"] == "ENTRY":
                account = api.resolve_entry(
                    account,
                    reservation_id=f"r:{item['intent_id']}",
                    event_id=f"resolved:{command_id}",
                    outcome="FILLED" if outcome["status"] == "FILLED" else "PARTIAL" if qty else "NO_FILL",
                )
                parent["entry_status"] = outcome["status"]
            if outcome["status"] == "BLOCKED":
                account = api.set_barrier(account, event_id=f"blocked:{command_id}", reason=outcome["reason"])
            position = next((p for p in account.positions if p.intent_id == item["intent_id"]), None)
            if position is None and item["purpose"] == "EXIT" and qty:
                parent["closed_at_ms"] = arrival
            if position is not None and item["purpose"] == "ENTRY" and qty:
                # Birth-time stop uses the already available exit-side quote.
                quote = state["latest"].get(position.symbol)
                px = (
                    None
                    if quote is None
                    else Decimal(quote["bid_price"] if position.side == "LONG" else quote["ask_price"])
                )
                if px is not None and (
                    px <= position.stop_price if position.side == "LONG" else px >= position.stop_price
                ):
                    account = self._queue_exit(state, account, position.intent_id, arrival, "STOP")
            if position is not None and item["purpose"] == "EXIT" and parent["exit_reason"] != item["reason"]:
                account = self._queue_exit(state, account, position.intent_id, arrival, parent["exit_reason"])

    def _quote(self, state, account, row):
        quote = row.quote
        now = quote.modeled_available_at_ms
        account = self._drain(state, account, now - 1)
        account, _ = api.mark_account(
            account,
            mark_id=f"portfolio-mark:{self.seal.sha256[:16]}:{row.global_sequence}",
            marks=((quote.symbol, (quote.bid_price + quote.ask_price) / Decimal(2), quote.event_at_ms),),
            as_of_ms=now,
        )
        state["latest"][quote.symbol] = _plain(asdict(quote))
        self._update_liquidity(state, quote)
        state["native_mark_count"] += 1
        for position in account.positions:
            if position.symbol == quote.symbol and position.intent_id not in state["parents"]:
                state.setdefault("unowned_protection", {})[position.intent_id] = "NATIVE_PLAN_UNAVAILABLE"
        for intent, parent in sorted(state["parents"].items()):
            position = next(
                (p for p in account.positions if p.intent_id == intent and p.symbol == quote.symbol), None
            )
            if position is None:
                continue
            price = quote.bid_price if position.side == "LONG" else quote.ask_price
            stop = price <= position.stop_price if position.side == "LONG" else price >= position.stop_price
            target = Decimal(parent["plan"]["target_price"])
            target_hit = price >= target if position.side == "LONG" else price <= target
            reason = (
                ("TRAILING_STOP" if position.stop_price != Decimal(parent["plan"]["stop_price"]) else "STOP")
                if stop
                else parent["exit_reason"] or ("TARGET" if target_hit else None)
            )
            if reason:
                account = self._queue_exit(state, account, intent, now, reason)
        return account

    def _apply_entry(self, state, account, boundary, p):
        """Unchanged execution fold for an explicitly validated entry view."""
        now = boundary.at_ms
        if p.intent_id in state["parents"]:
            raise ValueError("parent/intent cannot be redelivered under a new boundary")
        model = self._model[p.symbol]
        unknown_funding = sorted(
            key
            for key, due in state["funding"].items()
            if due["exposures"] and due["status"] in {"UNAVAILABLE", "RATE_ONLY"}
        )
        unknown_costs = sorted(key for key, amount in state["service_costs"].items() if amount is None)
        unknown_schedule = any(c.evidence_kind == "UNRESOLVED" for _, c in self.calendars)
        # Fixture declarations are audit-only. Future execution is bounded by
        # the actual IOC permission and the separately frozen model ceiling.
        # SHORT favorable execution can increase fees/gross even though its
        # adverse price is floor-bounded. A conservative tick-rounded risk
        # proxy covers the entire ceiling fee before native sizing; it never
        # expands the command's actual price permission.
        with localcontext(ARITHMETIC):
            risk_entry = p.price_cap
            notional_ceiling = p.price_cap if p.side == "LONG" else model.maximum_order_price
            if p.side == "SHORT":
                fee_fraction = account.policy.entry_fee_bps / Decimal(10000)
                mark = next((price for symbol, price, _ in account.marks if symbol == p.symbol), None)
                risk_entry = (
                    ZERO
                    if mark is None or fee_fraction >= 1
                    else (
                        (min(p.price_cap, mark) - notional_ceiling * fee_fraction / (1 - fee_fraction))
                        / model.assumptions.price_tick
                    ).to_integral_value(rounding=ROUND_FLOOR)
                    * model.assumptions.price_tick
                )
        refused = (
            "UNRESOLVED_FUNDING_LIABILITY"
            if unknown_funding or unknown_schedule
            else "UNRESOLVED_SERVICE_LIABILITY"
            if unknown_costs
            else "INVALID_DERIVED_WORST_PRICE"
            if risk_entry <= ZERO
            else None
        )
        parent = {
            "plan": _plain(asdict(p)),
            "entry_status": refused,
            "first_fill_at_ms": None,
            "closed_at_ms": None,
            "trailing_active": False,
            "exit_reason": None,
            "exit_attempts": 0,
            "outcomes": [],
            "sizing": {
                "authority": "DERIVED_IOC_CAP_AND_SEALED_MODEL_CEILING_NATIVE_RISK_REDUCER",
                "worst_entry_price": str(risk_entry),
                "worst_notional_price": str(notional_ceiling),
                "unresolved_funding": unknown_funding,
                "unresolved_costs": unknown_costs,
                "unresolved_schedule": unknown_schedule,
            },
        }
        state["parents"][p.intent_id] = parent
        if refused:
            state["boundary_count"] += 1
            return account
        account = replace(
            account, policy=replace(account.policy, quantity_step=model.assumptions.quantity_step)
        )
        account, reservation, status = api.reserve_entry(
            account,
            reservation_id=f"r:{p.intent_id}",
            intent_id=p.intent_id,
            symbol=p.symbol,
            side=p.side,
            stop_price=p.stop_price,
            worst_entry_price=risk_entry,
            worst_notional_price=notional_ceiling,
            as_of_ms=now,
            expires_at_ms=p.expires_at_ms,
        )
        parent["entry_status"] = status
        if reservation is not None:
            command = ModeledIOCCommandV3(
                f"portfolio-entry:{p.intent_id}",
                p.symbol,
                "BUY" if p.side == "LONG" else "SELL",
                reservation.quantity,
                p.price_cap,
                now,
                p.eligible_at_ms,
                p.expires_at_ms,
            )
            self._queue(state, command, p.intent_id, "ENTRY", None)
        state["boundary_count"] += 1
        return account

    def _boundary(self, state, account, boundary):
        action = self._action[boundary.boundary_id]
        if action.boundary != boundary:
            raise ValueError("financial boundary/source commitment conflict")
        now, parameters = boundary.at_ms, action.parameters
        # Only the first CONTROL at this clock may drain equality. Commands
        # created by the same-clock CONTROL roster execute after its final item.
        first_control = boundary.kind == "CONTROL" and state.get("control_clock") != now
        account = self._drain(state, account, now if first_control else now - 1)
        if boundary.kind == "CONTROL":
            state["control_clock"] = now
        entry = self._entry_view(state, action)
        if entry is not None:
            return self._apply_entry(state, account, boundary, entry)
        elif type(parameters) is ArchiveClosedProtectionV3:
            for intent, parent in sorted(state["parents"].items()):
                position = next(
                    (p for p in account.positions if p.intent_id == intent and p.symbol == parameters.symbol),
                    None,
                )
                plan = parent["plan"]
                if (
                    position is None
                    or parent["exit_reason"]
                    or plan["trailing_activation_price"] is None
                    or parameters.close_at_ms < position.opened_at_ms
                ):
                    continue
                activation = Decimal(plan["trailing_activation_price"])
                parent["trailing_active"] |= (
                    parameters.close >= activation
                    if position.side == "LONG"
                    else parameters.close <= activation
                )
                if parent["trailing_active"]:
                    proposed = (
                        parameters.close - Decimal(plan["trailing_distance"])
                        if position.side == "LONG"
                        else parameters.close + Decimal(plan["trailing_distance"])
                    )
                    if (
                        proposed > position.stop_price
                        if position.side == "LONG"
                        else proposed < position.stop_price
                    ):
                        account = api.tighten_stop(
                            account,
                            intent_id=intent,
                            event_id=f"trail:{boundary.boundary_id}:{intent}",
                            stop_price=proposed,
                            source_event_ms=parameters.close_at_ms,
                            available_ms=now,
                            as_of_ms=now,
                        )
        elif type(parameters) is ArchiveFundingDueV3:
            key = f"{parameters.symbol}:{parameters.due_at_ms}"
            if key in state["funding"]:
                raise ValueError("funding due exposure cannot be reset")
            state["funding"][key] = {
                "status": "UNAVAILABLE",
                "receipts": [],
                "exposures": [
                    {"intent_id": p.intent_id, "side": p.side, "quantity": str(p.quantity)}
                    for p in account.positions
                    if p.symbol == parameters.symbol and p.opened_at_ms < parameters.due_at_ms
                ],
            }
        elif type(parameters) is ArchiveFundingDeliveryV3:
            receipt = parameters.receipt
            key = f"{parameters.symbol}:{receipt.due_at_ms}"
            if key not in state["funding"]:
                raise ValueError("funding receipt before retained due-time entitlement")
            due = state["funding"][key]
            due["receipts"].append(_plain(asdict(receipt)))
            due["status"] = receipt.status
            if receipt.status in {"KNOWN", "NO_PAYMENT"}:
                for exposure in due["exposures"]:
                    cashflow = (
                        ZERO
                        if receipt.status == "NO_PAYMENT"
                        else -Decimal(exposure["quantity"])
                        * receipt.settlement_price
                        * receipt.rate
                        * (Decimal(1) if exposure["side"] == "LONG" else Decimal(-1))
                    )
                    event_id = f"portfolio-fund:{_hash([key, exposure['intent_id']])[:32]}"
                    if any(p.intent_id == exposure["intent_id"] for p in account.positions):
                        account = api.record_funding(
                            account,
                            intent_id=exposure["intent_id"],
                            event_id=event_id,
                            cashflow=cashflow,
                            at_ms=now,
                        )
                    else:
                        account = api.record_late_known_funding(
                            account, event_id=event_id, funding_key=key, cashflow=cashflow, at_ms=now
                        )
        elif type(parameters) is ArchiveServiceCostV3:
            if parameters.cost_id in state["service_costs"]:
                raise ValueError("service cost cannot be replaced under another boundary")
            state["service_costs"][parameters.cost_id] = (
                None if parameters.amount is None else str(parameters.amount)
            )
            if parameters.amount is not None:
                account = api.debit_cost(
                    account, cost_id=parameters.cost_id, amount=parameters.amount, at_ms=now, kind="SERVICE"
                )
        elif type(parameters) is not ArchiveAdvanceV3:
            raise ValueError("unsupported boundary action; never silently skip")
        state["boundary_count"] += 1
        return account

    def prepare_next(self):
        with self._lock:
            self._guard()
            if self._pending is not None:
                return self._pending
            snapshot, before = self.journal.snapshot(), self.journal.checkpoint()
            if (snapshot.version, snapshot.state_hash, snapshot.head_hash) != (
                before.version,
                before.state_hash,
                before.head_hash,
            ):
                raise ValueError("financial head changed during preparation")
            if snapshot.state["terminal"]:
                raise ValueError("terminal modeled portfolio")
            if self._stream.checkpoint() != _checkpoint(snapshot.state["portfolio_checkpoint"]):
                raise ValueError("durable global source vector and volatile reader disagree")
            operation = self._stream.prepare_next()
            if operation is None:
                return None
            self._pending = PreparedArchivePortfolioFinancialV3(
                before, operation, f"portfolio-financial:{operation.operation_id}"
            )
            return self._pending

    def recover_prepared(self, *, before_financial, retained_stream_anchor):
        """Only a known pending operation at the exact independently saved head."""
        with self._lock:
            self._guard()
            if self.journal.checkpoint() != before_financial:
                raise ValueError(
                    "pending recovery requires exact retained financial before; no latest adoption"
                )
            stream, operation = ArchivePortfolioStreamV3.recover_pending(
                self.seal, expected_seal_sha256=self.seal.sha256, retained_anchor=retained_stream_anchor
            )
            if _checkpoint(self.journal.snapshot().state["portfolio_checkpoint"]) != operation.before:
                raise ValueError("pending source before differs from durable financial prefix")
            self._stream = stream
            self._pending = PreparedArchivePortfolioFinancialV3(
                before_financial, operation, f"portfolio-financial:{operation.operation_id}"
            )
            return self._pending

    def commit_prepared(self, prepared):
        with self._lock:
            self._guard()
            if type(prepared) is not PreparedArchivePortfolioFinancialV3:
                raise ValueError("typed immutable original operation required")
            before, operation = prepared.before_financial, prepared.operation
            if (
                type(before) is not FinancialCheckpointV3
                or before.identity_sha256 != _hash(asdict(self.journal.identity))
                or before.owner_id != self.journal.owner_id
                or before.account_id != self.journal.account_id
                or before.source_cursor != operation.before.global_row_count
                or operation.before.seal_sha256 != self.seal.sha256
            ):
                raise ValueError("prepared owner/account/identity/global source fence conflict")
            prior = self.journal.lookup(event_id=prepared.event_id, payload=prepared.payload)
            if prior is not None:
                if prepared is self._pending:
                    if prior.snapshot.version != before.version + 1 or prior.snapshot.state[
                        "portfolio_checkpoint"
                    ] != _plain(asdict(operation.after)):
                        raise ValueError("known pending operation cannot adopt a newer unrelated head")
                    self._stream.acknowledge(operation)
                    self._pending = None
                return prior
            if prepared is not self._pending:
                raise ValueError("one exact owned pending financial operation required")

            def fold(state):
                if (
                    state["terminal"]
                    or state["config"] != self.config
                    or state["portfolio_checkpoint"] != _plain(asdict(operation.before))
                    or state["cursor"] != operation.before.global_row_count
                ):
                    raise ValueError("atomic financial/source-vector/config prefix conflict")
                account = self._load(state)
                if operation.kind == "SOURCE_BATCH":
                    for ordinal, row in enumerate(operation.rows):
                        account = self._quote(state, account, row)
                        next_same = (
                            ordinal + 1 < len(operation.rows)
                            and operation.rows[ordinal + 1].quote.modeled_available_at_ms
                            == row.quote.modeled_available_at_ms
                        )
                        if not next_same and (
                            ordinal + 1 < len(operation.rows)
                            or (
                                not operation.source_rows_at_clock_remaining
                                and not operation.boundaries_at_clock_remaining
                            )
                        ):
                            account = self._drain(state, account, row.quote.modeled_available_at_ms)
                else:
                    account = self._boundary(state, account, operation.boundary)
                    if (
                        not operation.source_rows_at_clock_remaining
                        and not operation.boundaries_at_clock_remaining
                    ):
                        account = self._drain(state, account, operation.at_ms)
                state["account"] = encode_account_core(account, self.journal.ledger_reference())
                state["portfolio_checkpoint"] = _plain(asdict(operation.after))
                state["cursor"] = operation.after.global_row_count
                return {
                    "status": "MODELED_REFERENCE_RECORDED",
                    "cursor": state["cursor"],
                    "native_marks": state["native_mark_count"],
                    "boundaries": state["boundary_count"],
                    "open_positions": len(account.positions),
                    "accepted_historical_inputs": False,
                }

            try:
                result = self.journal.transition(
                    event_id=prepared.event_id,
                    payload=prepared.payload,
                    at_ms=operation.at_ms,
                    expected_version=before.version,
                    expected_state_hash=before.state_hash,
                    expected_head_sha256=before.head_hash,
                    fold=fold,
                )
            except BaseException:
                self._pending = None
                self._stream = ArchivePortfolioStreamV3(
                    self.seal, expected_seal_sha256=self.seal.sha256, expected_checkpoint=operation.before
                )
                raise
            # If this handoff fails/crashes, durable source/native/core already
            # contain exact after. Caller resumes with its independently saved
            # financial after or exact known-transition WAL proof, never latest.
            self._stream.acknowledge(operation)
            self._pending = None
            return result

    def consume_next(self):
        prepared = self.prepare_next()
        return None if prepared is None else self.commit_prepared(prepared)

    def finish(self, *, at_ms):
        with self._lock:
            self._guard()
            _ms(at_ms)
            if self._pending is not None or self._stream.prepare_next() is not None:
                raise ValueError("finish cannot omit pending originals or any boundary")
            snapshot, checkpoint = self.journal.snapshot(), self.journal.checkpoint()
            if at_ms != self.config["retained_end_ms"] or at_ms < snapshot.last_clock_ms:
                raise ValueError("finish requires exact separately sealed retained end")
            payload = {
                "schema": SCHEMA,
                "kind": "PORTFOLIO_MODELED_FINISH",
                "at_ms": at_ms,
                "source_checkpoint": snapshot.state["portfolio_checkpoint"],
            }

            def fold(state):
                if state["terminal"] or state["portfolio_checkpoint"] != _plain(
                    asdict(self._stream.checkpoint())
                ):
                    raise ValueError("terminal or global prefix conflict")
                account = self._drain(state, self._load(state), at_ms)
                missing = [
                    k
                    for k, receipt in state["funding"].items()
                    if receipt["exposures"] and receipt["status"] in {"UNAVAILABLE", "RATE_ONLY"}
                ]
                missing_costs = [
                    k for k in self.config["expected_cost_ids"] if state["service_costs"].get(k) is None
                ]
                if state["native_mark_count"] != self.config["resource_profile"][
                    "required_original_rows"
                ] or state["boundary_count"] != len(self.actions):
                    raise ValueError("full original-row/boundary denominator required")
                unresolved = bool(state.get("unowned_protection")) or (
                    bool(
                        missing
                        or missing_costs
                        or account.positions
                        or account.unresolved_fills
                        or account.barrier
                        or account.risk_over_limit
                        or state["pending_commands"]
                    )
                    or any(r.terminal in {"OPEN", "UNKNOWN"} for r in account.reservations)
                    or any(c.evidence_kind == "UNRESOLVED" for _, c in self.calendars)
                )
                state["account"] = encode_account_core(account, self.journal.ledger_reference())
                state["terminal"] = True
                return {
                    "status": "UNRESOLVED" if unresolved else "MODELED_REFERENCE_COMPLETE",
                    "source_complete": True,
                    "original_rows": state["cursor"],
                    "native_marks": state["native_mark_count"],
                    "boundaries": state["boundary_count"],
                    "cash": str(account.cash),
                    "marked_equity": str(account.equity),
                    "open_positions": len(account.positions),
                    "missing_funding": missing,
                    "missing_service_costs": missing_costs,
                    "barrier": account.barrier,
                    "risk_over_limit": account.risk_over_limit,
                    "historical_risk_overrun": account.historical_risk_overrun,
                    "accepted_historical_inputs": False,
                    "economics_qualified": False,
                    "net_return": None,
                    "entry_start_ms": self.config["entry_start_ms"],
                    "entry_end_ms": self.config["entry_end_ms"],
                    "retained_end_ms": at_ms,
                    "tail_capability": self.config["tail_capability"],
                }

            return self.journal.transition(
                event_id="portfolio-modeled-finish",
                payload=payload,
                at_ms=at_ms,
                expected_version=checkpoint.version,
                expected_state_hash=checkpoint.state_hash,
                expected_head_sha256=checkpoint.head_hash,
                fold=fold,
            )
