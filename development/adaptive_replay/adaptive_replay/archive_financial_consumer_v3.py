"""Lossless archive BBO -> atomic account/native-ledger research endpoint.

This explicit MODELED_REFERENCE path marks every original row, with the
unchanged financial reducer, and retains funding/risk/source/liquidity state
in one non-resetting journal. It does not manufacture AcceptedBookFrame,
historical receive clocks, strategy calls, fills, exits or source admission.
Current scope is the archive MARK/funding/risk endpoint, not IOC equivalence.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from . import (
    account_event_context_v3,
    archive_batch_cursor_v3,
    archive_market_clock_v3,
    bookticker_archive_stream_v3,
    sim_account_core_codec_v3,
    sim_delta_journal_v3,
    sim_financial_journal_v3,
    sim_state_journal,
)
from . import adaptive_sim_account as account_api
from .account_event_context_v3 import current_native_event_context
from .archive_batch_cursor_v3 import ArchiveBatchIndexV3, ArchiveBatchV3, ArchiveCursorCheckpointV3
from .archive_market_clock_v3 import MAX_CLOCK_MS, ArchiveMarketClockV3
from .bookticker_archive_stream_v3 import MAX_MANIFEST_BYTES, _canonical, _day_start_ms, _sha
from .sim_account_core_codec_v3 import decode_account_core, encode_account_core
from .sim_financial_journal_v3 import FinancialCheckpointV3, SimFinancialJournalV3, initial_ledger_reference
from .sim_state_journal import JournalIdentity

SCHEMA = "kairos.research.archive-financial-consumer.v3"
MAX_FUNDING_DUES = 256
MAX_FUNDING_RECEIPTS = 512


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _plain(value):
    if type(value) is Decimal:
        return str(value)
    if type(value) in (tuple, list):
        return [_plain(item) for item in value]
    if type(value) is dict:
        return {key: _plain(item) for key, item in value.items()}
    return value


def _implementation():
    modules = (
        account_api,
        archive_batch_cursor_v3,
        archive_market_clock_v3,
        bookticker_archive_stream_v3,
        account_event_context_v3,
        sim_account_core_codec_v3,
        sim_financial_journal_v3,
        sim_delta_journal_v3,
        sim_state_journal,
    )
    paths = [Path(__file__), *(Path(module.__file__) for module in modules)]
    return _hash([[str(path.absolute()), hashlib.sha256(path.read_bytes()).hexdigest()] for path in paths])


@dataclass(frozen=True, slots=True)
class ArchiveFundingReceiptV3:
    """Separately labeled modeled availability; no historical local clocks."""

    due_at_ms: int
    exchange_calc_time_ms: int | None
    modeled_available_at_ms: int
    status: str
    rate: Decimal | None
    settlement_price: Decimal | None
    settlement_price_source_sha256: str | None
    original_record_sha256: str

    def __post_init__(self):
        if (
            any(
                type(value) is not int or not 0 <= value <= MAX_CLOCK_MS
                for value in (self.due_at_ms, self.modeled_available_at_ms)
            )
            or self.modeled_available_at_ms < self.due_at_ms
        ):
            raise ValueError("causal explicit modeled funding clocks required")
        _sha(self.original_record_sha256, "original funding record SHA256")
        if self.exchange_calc_time_ms is not None and (
            type(self.exchange_calc_time_ms) is not int
            or not 0 <= self.exchange_calc_time_ms <= MAX_CLOCK_MS
            or self.modeled_available_at_ms < self.exchange_calc_time_ms
        ):
            raise ValueError("modeled funding cannot be available before original exchange calcTime")
        if self.status == "UNAVAILABLE":
            if (
                self.rate is not None
                or self.settlement_price is not None
                or self.settlement_price_source_sha256 is not None
            ):
                raise ValueError("unknown funding cannot invent economics")
        elif self.status in {"KNOWN", "NO_PAYMENT", "RATE_ONLY"}:
            if (
                type(self.rate) is not Decimal
                or self.exchange_calc_time_ms is None
                or not self.rate.is_finite()
                or (self.status == "NO_PAYMENT" and self.rate != 0)
            ):
                raise ValueError("exact original funding rate/calcTime required")
            if self.status == "KNOWN" or self.settlement_price is not None:
                if (
                    type(self.settlement_price) is not Decimal
                    or not self.settlement_price.is_finite()
                    or self.settlement_price <= 0
                ):
                    raise ValueError("exact modeled settlement price required")
                _sha(self.settlement_price_source_sha256, "frozen settlement price source SHA256")
            elif self.settlement_price_source_sha256 is not None:
                raise ValueError("no settlement source without a settlement price")
            if self.status == "RATE_ONLY" and self.settlement_price is not None:
                raise ValueError("rate-only receipt cannot invent settlement pricing")
        else:
            raise ValueError("explicit modeled funding disposition required")


@dataclass(frozen=True, slots=True)
class ArchiveFundingCalendarV3:
    """Frozen caller-retained roster; this type confers NO source admission.

    EXHAUSTIVE_RETAINED_ROSTER records a claim/evidence hash, not an archive
    parser or independent absence proof. UNRESOLVED remains explicit even
    when the initial account is flat. TEST_FIXTURE may use an empty roster.
    """

    evidence_kind: str
    retained_calendar_sha256: str
    maximum_calc_time_offset_ms: int
    expected_due: tuple[int, ...]
    receipts: tuple[ArchiveFundingReceiptV3, ...]

    def __post_init__(self):
        _sha(self.retained_calendar_sha256, "retained funding calendar SHA256")
        if (
            type(self.maximum_calc_time_offset_ms) is not int
            or not 0 <= self.maximum_calc_time_offset_ms <= 60_000
        ):
            raise ValueError("explicit bounded entitlement proxy offset required")
        if (
            self.evidence_kind not in {"UNRESOLVED", "TEST_FIXTURE", "EXHAUSTIVE_RETAINED_ROSTER"}
            or type(self.expected_due) is not tuple
            or len(self.expected_due) > MAX_FUNDING_DUES
            or any(type(value) is not int or not 0 <= value <= MAX_CLOCK_MS for value in self.expected_due)
            or tuple(sorted(set(self.expected_due))) != self.expected_due
        ):
            raise ValueError("bounded exact frozen funding due roster required")
        if (
            type(self.receipts) is not tuple
            or len(self.receipts) > MAX_FUNDING_RECEIPTS
            or any(
                type(item) is not ArchiveFundingReceiptV3 or item.due_at_ms not in self.expected_due
                for item in self.receipts
            )
        ):
            raise ValueError("funding receipt outside frozen roster")
        if (
            tuple(sorted(self.receipts, key=lambda item: (item.modeled_available_at_ms, item.due_at_ms)))
            != self.receipts
        ):
            raise ValueError("funding receipts must be in frozen causal order")
        prior = {}
        for receipt in self.receipts:
            if (
                receipt.exchange_calc_time_ms is not None
                and abs(receipt.exchange_calc_time_ms - receipt.due_at_ms) > self.maximum_calc_time_offset_ms
            ):
                raise ValueError("original calcTime exceeds frozen entitlement proxy offset")
            old = prior.get(receipt.due_at_ms)
            if old is not None and (
                old.status not in {"UNAVAILABLE", "RATE_ONLY"}
                or receipt.status == "UNAVAILABLE"
                or (old.status == "RATE_ONLY" and receipt.status == "RATE_ONLY")
            ):
                raise ValueError("only unresolved-to-known funding resolution permitted")
            if (
                old is not None
                and old.rate is not None
                and (receipt.rate != old.rate or receipt.exchange_calc_time_ms != old.exchange_calc_time_ms)
            ):
                raise ValueError("funding resolution cannot replace the original rate/calcTime")
            prior[receipt.due_at_ms] = receipt


@dataclass(frozen=True, slots=True)
class PreparedArchiveFinancialBatchV3:
    before_financial: FinancialCheckpointV3
    batch: ArchiveBatchV3
    event_id: str

    @property
    def payload(self):
        # Fresh plain document: external WAL can freeze it before invoking commit.
        return {
            "kind": "ARCHIVE_MODELED_BATCH",
            "schema": SCHEMA,
            "clock_evidence": "MODELED_REFERENCE",
            "batch_sha256": self.batch.sha256,
            "before": asdict(self.batch.before),
            "after": asdict(self.batch.after),
            "raw_rows": len(self.batch.rows),
            "raw_bytes": self.batch.raw_byte_count,
        }


class ArchiveFinancialBatchConsumerV3:
    """One owned journal, fixed source/model, exact prefix, no flat MARK omission.

    ``prepare_next`` exposes the full before-anchor/envelope for an external
    driver WAL. It advances only a volatile reader. ``commit_prepared`` commits
    every row's account event and the after cursor in one journal transaction.
    Failure reconstructs the reader from the durable before cursor. Exact open
    still needs the independently retained financial checkpoint; postcommit
    crash recovery is NOT latest-checkpoint adoption.
    """

    def __init__(self, journal, index, clock, funding, config):
        if (
            type(journal) is not SimFinancialJournalV3
            or type(index) is not ArchiveBatchIndexV3
            or type(clock) is not ArchiveMarketClockV3
            or type(funding) is not ArchiveFundingCalendarV3
        ):
            raise ValueError("exact archive/financial contracts required")
        self.journal, self.index, self.clock, self.funding = journal, index, clock, funding
        self.config = config
        self._sealed = _hash(config)
        self._sealed_objects = (journal, index, clock, funding)
        self._sealed_implementation = _implementation()
        self._native_functions = (
            account_api.mark_account,
            account_api.record_funding,
            account_api.record_late_known_funding,
        )
        self._lock = threading.RLock()
        self._pending = None
        snapshot = journal.snapshot()
        if (
            snapshot.state["config"] != config
            or journal.identity.policy_id != self._sealed
            or journal.identity.source_id != index.source_manifest_sha256
            or journal.identity.implementation_id != self._sealed_implementation
        ):
            raise ValueError("sealed archive financial configuration/implementation mismatch")
        self._reader = index.cursor(
            clock=clock, expected_checkpoint=ArchiveCursorCheckpointV3(**snapshot.state["archive_cursor"])
        )

    @classmethod
    def create(
        cls,
        path,
        *,
        campaign_id,
        owner_id,
        account_id,
        index,
        clock,
        funding,
        initial_account,
        batch_rows,
        storage_bounds,
    ):
        if type(initial_account) is not account_api.SimAccount or initial_account.events:
            raise ValueError("pure typed initial financial core required")
        account_api._id(campaign_id, "campaign")
        account_api._id(owner_id, "owner")
        account_api._id(account_id, "account")
        if (
            type(index) is not ArchiveBatchIndexV3
            or type(clock) is not ArchiveMarketClockV3
            or type(funding) is not ArchiveFundingCalendarV3
            or index.symbol not in account_api.SYMBOLS
        ):
            raise ValueError("exact archive consumer configuration required")
        if type(batch_rows) is not int or not 1 <= batch_rows <= index.limits.max_batch_rows:
            raise ValueError("explicit bounded batch size required")
        if type(storage_bounds) is not dict or set(storage_bounds) != set(
            sim_financial_journal_v3.DEFAULT_LIMITS
        ):
            raise ValueError("all financial storage bounds must be explicitly pinned")
        # Preflight row cardinality, not an optimistic claim that a byte cap fits.
        required_native = index.row_count + len(funding.receipts) * 5 + 1
        if (
            type(storage_bounds["max_native_event_rows"]) is not int
            or storage_bounds["max_native_event_rows"] < required_native
        ):
            raise ValueError("native audit capacity cannot retain the complete source and funding roster")
        if (
            type(storage_bounds["max_event_rows"]) is not int
            or storage_bounds["max_event_rows"] < index.row_count + 1
        ):
            raise ValueError("outer capacity must cover worst-case bounded one-row batches")
        source_manifest, _ = archive_batch_cursor_v3._read_json(
            index.source_root / "manifest.json", MAX_MANIFEST_BYTES, index.source_manifest_sha256
        )
        fixture = source_manifest["evidence_kind"] == "TEST_FIXTURE"
        if not fixture and (
            initial_account != account_api.new_account(initial_account.initial_equity, initial_account.policy)
            or funding.evidence_kind == "TEST_FIXTURE"
        ):
            raise ValueError("real archive starts at flat genesis; no fixture economics adoption")
        start = _day_start_ms(index.transaction_day)
        end = start + 86_400_000
        if any(not start <= due < end for due in funding.expected_due):
            raise ValueError("funding due roster outside exact transaction day")
        cursor = index.cursor(clock=clock).checkpoint()
        config = {
            "schema": SCHEMA,
            "clock_evidence": "MODELED_REFERENCE",
            "source_manifest_sha256": index.source_manifest_sha256,
            "index_manifest_sha256": index.manifest_sha256,
            "symbol": index.symbol,
            "day": index.transaction_day,
            "rows": index.row_count,
            "clock_policy": {
                "event_basis": clock.event_basis,
                "feed_delay_ms": clock.feed_delay_ms,
                "processing_delay_ms": clock.processing_delay_ms,
            },
            "clock_policy_sha256": clock.sha256,
            "funding": _plain(asdict(funding)),
            "funding_clock_rule": (
                "ARCHIVE_CALC_TIME_ENTITLEMENT_PROXY_MODEL_AVAILABILITY_NOT_BEFORE_CALCTIME"
            ),
            "batch_rows": batch_rows,
            "storage_bounds": dict(storage_bounds),
            "initial_core": _plain(asdict(initial_account)),
            "owner_id": owner_id,
            "account_id": account_id,
            "implementation": _implementation(),
            "resource_profile": {
                "required_native_rows": required_native,
                "dense_database_capacity": "UNMEASURED_FAIL_CLOSED",
                "source_sampling": False,
            },
            "accepted_historical_inputs": False,
            "execution_scope": "EXACT_MARK_FUNDING_RISK_NO_INVENTED_IOC",
        }
        identity = JournalIdentity(
            campaign_id, index.source_manifest_sha256, _hash(config), config["implementation"]
        )
        ref = initial_ledger_reference(identity, owner_id=owner_id, account_id=account_id)
        state = {
            "config": config,
            "account": encode_account_core(initial_account, ref),
            "clock": start,
            "cursor": 0,
            "archive_cursor": asdict(cursor),
            "latest_bbo": None,
            "liquidity": None,
            "funding": {},
            "funding_due_cursor": 0,
            "funding_receipt_cursor": 0,
            "native_mark_count": 0,
            "terminal": False,
            "last_outcome": None,
        }
        journal = SimFinancialJournalV3.create(
            path,
            identity=identity,
            owner_id=owner_id,
            account_id=account_id,
            initial_state=state,
            initial_clock_ms=start,
            allowed_quantity_steps=(initial_account.policy.quantity_step,),
            **storage_bounds,
        )
        try:
            return cls(journal, index, clock, funding, config)
        except BaseException:
            journal.close()
            raise

    @classmethod
    def open(cls, path, *, identity, expected_checkpoint, index, clock, funding, config):
        journal = SimFinancialJournalV3.open(
            path,
            identity=identity,
            expected_checkpoint=expected_checkpoint,
            owner_id=config["owner_id"],
            account_id=config["account_id"],
            allowed_quantity_steps=(Decimal(config["initial_core"]["policy"]["quantity_step"]),),
            **config["storage_bounds"],
        )
        try:
            return cls(journal, index, clock, funding, config)
        except BaseException:
            journal.close()
            raise

    def _guard(self):
        if (
            any(
                actual is not original
                for actual, original in zip(
                    (self.journal, self.index, self.clock, self.funding), self._sealed_objects, strict=True
                )
            )
            or _hash(self.config) != self._sealed
            or self.config["implementation"] != self._sealed_implementation
            or (account_api.mark_account, account_api.record_funding, account_api.record_late_known_funding)
            != self._native_functions
            or self.index.source_manifest_sha256 != self.config["source_manifest_sha256"]
            or self.index.manifest_sha256 != self.config["index_manifest_sha256"]
            or self.clock.sha256 != self.config["clock_policy_sha256"]
            or _plain(asdict(self.funding)) != self.config["funding"]
        ):
            raise ValueError("frozen archive consumer runtime drift")

    def _load(self, state):
        account, ref = decode_account_core(state["account"])
        self.journal.validate_ledger_reference(ref)
        current_native_event_context(account)
        return account

    def _funding_through(self, state, account, through):
        while state["funding_due_cursor"] < len(self.funding.expected_due):
            due = self.funding.expected_due[state["funding_due_cursor"]]
            if due > through:
                break
            state["funding"][str(due)] = {
                "status": "UNAVAILABLE",
                "exposures": [
                    {"intent_id": p.intent_id, "side": p.side, "quantity": str(p.quantity)}
                    for p in account.positions
                    if p.symbol == self.index.symbol and p.opened_at_ms < due
                ],
                "receipts": [],
            }
            state["funding_due_cursor"] += 1
        while state["funding_receipt_cursor"] < len(self.funding.receipts):
            receipt = self.funding.receipts[state["funding_receipt_cursor"]]
            if receipt.modeled_available_at_ms > through:
                break
            due = state["funding"][str(receipt.due_at_ms)]
            due["receipts"].append(_plain(asdict(receipt)))
            due["status"] = receipt.status
            if receipt.status in {"KNOWN", "NO_PAYMENT"}:
                for exposure in due["exposures"]:
                    cashflow = (
                        Decimal(0)
                        if receipt.status == "NO_PAYMENT"
                        else (
                            -Decimal(exposure["quantity"])
                            * receipt.settlement_price
                            * receipt.rate
                            * (Decimal(1) if exposure["side"] == "LONG" else Decimal(-1))
                        )
                    )
                    event_id = f"archive-funding:{receipt.due_at_ms}:{_hash(exposure['intent_id'])[:24]}"
                    if any(p.intent_id == exposure["intent_id"] for p in account.positions):
                        account = account_api.record_funding(
                            account,
                            intent_id=exposure["intent_id"],
                            event_id=event_id,
                            cashflow=cashflow,
                            at_ms=receipt.modeled_available_at_ms,
                        )
                    else:
                        account = account_api.record_late_known_funding(
                            account,
                            event_id=event_id,
                            funding_key=f"{self.index.symbol}:{receipt.due_at_ms}",
                            cashflow=cashflow,
                            at_ms=receipt.modeled_available_at_ms,
                        )
            state["funding_receipt_cursor"] += 1
        return account

    def prepare_next(self):
        with self._lock:
            self._guard()
            if self._pending is not None:
                return self._pending
            snapshot = self.journal.snapshot()
            before = self.journal.checkpoint()
            if (snapshot.version, snapshot.state_hash, snapshot.head_hash) != (
                before.version,
                before.state_hash,
                before.head_hash,
            ):
                raise ValueError("financial checkpoint changed during batch preparation")
            if snapshot.state["terminal"]:
                raise ValueError("terminal archive consumer")
            retained = ArchiveCursorCheckpointV3(**snapshot.state["archive_cursor"])
            if self._reader.checkpoint() != retained:
                raise ValueError("volatile reader and durable source checkpoint disagree")
            batch = self._reader.read_batch(max_rows=self.config["batch_rows"])
            if not batch.rows:
                return None
            event_id = f"archive-batch:{batch.before.next_row}:{batch.after.next_row}:{batch.sha256[:24]}"
            self._pending = PreparedArchiveFinancialBatchV3(before, batch, event_id)
            return self._pending

    def commit_prepared(self, prepared):
        with self._lock:
            self._guard()
            if type(prepared) is not PreparedArchiveFinancialBatchV3:
                raise ValueError("typed retained archive batch required")
            if (
                type(prepared.before_financial) is not FinancialCheckpointV3
                or prepared.before_financial.owner_id != self.journal.owner_id
                or prepared.before_financial.account_id != self.journal.account_id
                or prepared.before_financial.identity_sha256 != _hash(asdict(self.journal.identity))
                or prepared.before_financial.source_cursor != prepared.batch.before.next_row
            ):
                raise ValueError("prepared financial owner/identity/source fence mismatch")
            prior = self.journal.lookup(event_id=prepared.event_id, payload=prepared.payload)
            if prior is not None:
                return prior
            if prepared is not self._pending:
                raise ValueError("exact owned prepared archive batch required")
            batch = prepared.batch
            before = prepared.before_financial
            now = batch.quotes[-1].modeled_available_at_ms

            def fold(state):
                if (
                    state["config"] != self.config
                    or state["terminal"]
                    or state["archive_cursor"] != asdict(batch.before)
                    or state["cursor"] != batch.before.next_row
                ):
                    raise ValueError("atomic financial source prefix/terminal/configuration conflict")
                account = self._load(state)
                for row, quote in zip(batch.rows, batch.quotes, strict=True):
                    account = self._funding_through(state, account, quote.modeled_available_at_ms)
                    account, _ = account_api.mark_account(
                        account,
                        mark_id=f"archive-mark:{self.index.source_manifest_sha256[:16]}:{row.row_index}",
                        marks=(
                            (
                                quote.symbol,
                                (quote.bid_price + quote.ask_price) / Decimal(2),
                                quote.event_at_ms,
                            ),
                        ),
                        as_of_ms=quote.modeled_available_at_ms,
                    )
                    state["latest_bbo"] = {
                        **_plain(asdict(quote)),
                        "historical_received_at_ms": None,
                        "historical_persisted_at_ms": None,
                        "clock_evidence": "MODELED_REFERENCE",
                        "stream_kind": "TOP_OF_BOOK_ONLY",
                    }
                    state["liquidity"] = {
                        "scope": "TOP_OF_BOOK_ONLY_MODELED_REFERENCE",
                        "row_index": row.row_index,
                        "update_id": row.update_id,
                        "bid_remaining": str(quote.bid_qty),
                        "ask_remaining": str(quote.ask_qty),
                        "execution_consumed": False,
                        "original_line_sha256": quote.original_line_sha256,
                    }
                    state["native_mark_count"] += 1
                state["account"] = encode_account_core(account, self.journal.ledger_reference())
                state["archive_cursor"] = asdict(batch.after)
                state["cursor"] = batch.after.next_row
                return {
                    "status": "MODELED_REFERENCE_RECORDED",
                    "rows": len(batch.rows),
                    "cursor": batch.after.next_row,
                    "native_marks": state["native_mark_count"],
                    "accepted_historical_inputs": False,
                }

            try:
                result = self.journal.transition(
                    event_id=prepared.event_id,
                    payload=prepared.payload,
                    at_ms=now,
                    expected_version=before.version,
                    expected_state_hash=before.state_hash,
                    expected_head_sha256=before.head_hash,
                    fold=fold,
                )
            except BaseException:
                # No latest adoption. The owned reader returns to independently
                # retained before, and another writer's checkpoint is not accepted.
                self._reader = self.index.cursor(clock=self.clock, expected_checkpoint=batch.before)
                self._pending = None
                raise
            self._pending = None
            return result

    def consume_next(self):
        prepared = self.prepare_next()
        return None if prepared is None else self.commit_prepared(prepared)

    def finish(self, *, at_ms):
        with self._lock:
            self._guard()
            account_api._ms(at_ms, "finish clock")
            if self._pending is not None:
                raise ValueError("commit retained prepared batch before finish")
            snapshot = self.journal.snapshot()
            checkpoint = self.journal.checkpoint()
            if snapshot.state[
                "cursor"
            ] != self.index.row_count or self._reader.checkpoint() != ArchiveCursorCheckpointV3(
                **snapshot.state["archive_cursor"]
            ):
                raise ValueError("finish cannot omit any original archive row")
            if (
                at_ms < snapshot.last_clock_ms
                or at_ms < _day_start_ms(self.index.transaction_day) + 86_400_000
            ):
                raise ValueError("finish before full archive transaction day/availability")
            if self.funding.receipts and at_ms < self.funding.receipts[-1].modeled_available_at_ms:
                raise ValueError("finish cannot omit frozen late funding receipts")
            payload = {
                "kind": "ARCHIVE_MODELED_FINISH",
                "at_ms": at_ms,
                "source_prefix": snapshot.state["archive_cursor"],
            }

            def fold(state):
                if state["terminal"]:
                    raise ValueError("terminal archive consumer")
                account = self._funding_through(state, self._load(state), at_ms)
                state["account"] = encode_account_core(account, self.journal.ledger_reference())
                missing = [
                    due
                    for due, receipt in state["funding"].items()
                    if receipt["status"] in {"UNAVAILABLE", "RATE_ONLY"}
                ]
                unresolved = (
                    self.funding.evidence_kind == "UNRESOLVED"
                    or bool(missing)
                    or bool(account.positions)
                    or any(r.terminal in {"OPEN", "UNKNOWN"} for r in account.reservations)
                    or bool(account.unresolved_fills)
                    or account.barrier is not None
                    or account.risk_over_limit
                )
                state["terminal"] = True
                return {
                    "status": "UNRESOLVED" if unresolved else "MODELED_REFERENCE_COMPLETE",
                    "raw_rows": state["cursor"],
                    "source_complete": True,
                    "native_marks": state["native_mark_count"],
                    "missing_funding": missing,
                    "cash": str(account.cash),
                    "marked_equity": str(account.equity),
                    "marked_equity_source_clock_ms": snapshot.last_clock_ms,
                    "open_positions": len(account.positions),
                    "barrier": account.barrier,
                    "risk_over_limit": account.risk_over_limit,
                    "historical_risk_overrun": account.historical_risk_overrun,
                    "accepted_historical_inputs": False,
                    "economics_qualified": False,
                    "net_return": None,
                    "execution_scope": self.config["execution_scope"],
                }

            return self.journal.transition(
                event_id="archive-finish",
                payload=payload,
                at_ms=at_ms,
                expected_version=checkpoint.version,
                expected_state_hash=checkpoint.state_hash,
                expected_head_sha256=checkpoint.head_hash,
                fold=fold,
            )
