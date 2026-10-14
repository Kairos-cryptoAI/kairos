"""Explicit atomic native-ledger consumer for the bounded five-day V3 path.

This relocates ALL original financial events without changing the fold. It
does not admit historical sources or lift the inherited finite source roster,
parent, core, state or file bounds. No migration, daily reset, forced exit,
latest-head adoption, model execution, network or trading authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from kairos_execution.simulation.models import LiquidityState

from . import adaptive_sim_account as account_api
from .account_event_context_v3 import current_native_event_context
from .continuous_sim import UNIVERSE, ContinuousSimPortfolio, SimInputError, _id, _ms, _plain
from .continuous_sim_v3_horizon import ContinuousSimV3Horizon, FiveDayHorizonV3
from .historical_context import digest
from .sim_account_core_codec_v3 import decode_account_core, encode_account_core
from .sim_financial_journal_v3 import DEFAULT_LIMITS, SimFinancialJournalV3, initial_ledger_reference
from .sim_state_journal import JournalIdentity

FINANCIAL_HORIZON_ID = "kairos.research.continuous-financial-five-day.v3"


class ContinuousSimFinancialV3Horizon(ContinuousSimV3Horizon):
    """One non-resetting account; native audit and source cursor commit together."""

    def __init__(self, journal, binding, models, rules, funding, config, path, candle_originals=None):
        if type(journal) is not SimFinancialJournalV3 or config.get("schema") != FINANCIAL_HORIZON_ID:
            raise SimInputError("explicit financial horizon journal/config required; no old adoption")
        super().__init__(journal, binding, models, rules, funding, config, path, candle_originals)
        if (
            journal.owner_id != config["financial_account"]["owner_id"]
            or journal.account_id != config["financial_account"]["account_id"]
            or journal.allowed_quantity_steps != tuple(sorted({r.quantity_step for r in rules.values()}))
            or journal.identity.source_id != binding.source_id
            or journal.identity.policy_id != digest(config)
            or journal.identity.implementation_id != config["implementation"]
        ):
            raise SimInputError("sealed financial owner/account/steps/identity conflict")
        self._sealed_journal = journal

    @staticmethod
    def _financial_config(*, owner_id, account_id, **arguments):
        _id(owner_id)
        _id(account_id)
        config = ContinuousSimV3Horizon._horizon_config(**arguments)
        config["schema"] = FINANCIAL_HORIZON_ID
        config["financial_account"] = {
            "owner_id": owner_id,
            "account_id": account_id,
            "allowed_quantity_steps": [
                str(s) for s in sorted({r.quantity_step for r in arguments["rules"].values()})
            ],
        }
        config["flat_mark_ledger"] = "ALL_EXACT_NATIVE_EVENTS_EXTERNAL_ATOMIC_LEDGER_NO_OMISSION"
        config["source_resource_profile"]["account_delta_mode"] = (
            "STRUCTURED_CORE_EXTERNAL_EXACT_NATIVE_LEDGER"
        )
        config["source_resource_profile"]["arbitrary_native_feed_capacity"] = False
        config["implementation"] = digest(
            [
                config["implementation"],
                *[
                    [str(path.absolute()), hashlib.sha256(path.read_bytes()).hexdigest()]
                    for path in (
                        Path(__file__),
                        Path(SimFinancialJournalV3.create.__func__.__code__.co_filename),
                        Path(encode_account_core.__code__.co_filename),
                    )
                ],
            ]
        )
        return config

    @classmethod
    def create(
        cls,
        path,
        *,
        campaign_id,
        arm_id,
        owner_id,
        account_id,
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
        **storage,
    ):
        _id(campaign_id)
        limits = {**DEFAULT_LIMITS, **storage}
        if set(limits) != set(DEFAULT_LIMITS):
            raise SimInputError("exact financial storage bounds required")
        config = cls._financial_config(
            owner_id=owner_id,
            account_id=account_id,
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
            storage=limits,
        )
        identity = JournalIdentity(campaign_id, binding.source_id, digest(config), config["implementation"])
        model = models[UNIVERSE[0]]
        policy = account_api.AccountPolicy(
            rules[UNIVERSE[0]].quantity_step,
            model.taker_fee_bps,
            model.taker_fee_bps,
            model.adverse_slippage_bps,
            model.maximum_book_age_ms,
            "ENTRY_STOP_RESERVED",
        )
        ledger = initial_ledger_reference(identity, owner_id=owner_id, account_id=account_id)
        # A distinct create-only schema; never deserialize/adopt an old journal.
        state = {
            "config": config,
            "clock": horizon.data_start_ms,
            "cursor": 0,
            "account": encode_account_core(account_api.new_account(initial_equity, policy), ledger),
            "latest": {},
            "liquidity": {
                symbol: LiquidityState(
                    session_id=arm_id,
                    tape_id=binding.tape_id,
                    stream_epoch=binding.stream_epoch,
                    symbol=symbol,
                ).model_dump(mode="json")
                for symbol in UNIVERSE
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
        journal = SimFinancialJournalV3.create(
            path,
            identity=identity,
            owner_id=owner_id,
            account_id=account_id,
            initial_state=state,
            initial_clock_ms=horizon.data_start_ms,
            allowed_quantity_steps=tuple(sorted({r.quantity_step for r in rules.values()})),
            **limits,
        )
        try:
            return cls(journal, binding, models, rules, funding_schedule, config, path, candle_originals)
        except BaseException:
            journal.close()
            raise

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
        financial = config["financial_account"]
        rebuilt = cls._financial_config(
            owner_id=financial["owner_id"],
            account_id=financial["account_id"],
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
            raise SimInputError("sealed financial horizon configuration drift")
        journal = SimFinancialJournalV3.open(
            path,
            identity=identity,
            expected_checkpoint=expected_checkpoint,
            owner_id=financial["owner_id"],
            account_id=financial["account_id"],
            allowed_quantity_steps=tuple(sorted({r.quantity_step for r in rules.values()})),
            **config["storage"],
        )
        try:
            if journal.snapshot().state["config"] != config:
                raise SimInputError("durable financial horizon configuration conflict")
            return cls(journal, binding, models, rules, funding_schedule, config, path, candle_originals)
        except BaseException:
            journal.close()
            raise

    def _load_account(self, document):
        account, ledger = decode_account_core(document)
        self.journal.validate_ledger_reference(ledger)
        current_native_event_context(account)
        return account

    def _store_account(self, account):
        return encode_account_core(account, self.journal.ledger_reference())

    def _mark_book(self, account, frame, global_sequence, now_ms):
        # Bypass the old horizon's declared flat-audit omission, not its reducer.
        return ContinuousSimPortfolio._mark_book(self, account, frame, global_sequence, now_ms)

    def _event(self, event_id, payload, now, reducer):
        _ms(now)
        horizon = self.config["horizon"]
        if not horizon["data_start_ms"] <= now <= horizon["retained_end_ms"]:
            raise SimInputError("event outside fixed retained horizon")
        if (
            self.journal is not self._sealed_journal
            or self.binding is not self._sealed_binding
            or self.funding is not self._sealed_funding
            or self.candle_originals is not self._sealed_candle_originals
            or self.config != self._sealed_config
            or {s: m.fingerprint() for s, m in self.models.items()} != self._sealed_config["models"]
            or _plain({s: asdict(r) for s, r in self.rules.items()}) != self._sealed_config["rules"]
        ):
            raise SimInputError("immutable sealed financial horizon runtime drift")
        prior = self.journal.lookup(event_id=event_id, payload=payload)
        if prior is not None:
            return prior
        snapshot = self.snapshot()

        def atomic_fold(state):
            if state["config"] != self._sealed_config or state["terminal"] or now < state["clock"]:
                raise SimInputError("terminal, regressing or configuration-conflicting financial event")
            outcome = reducer(state)
            if payload.get("kind") == "FINISH":
                self._finish_liability_gates(state, outcome)
            return outcome

        return self.journal.transition(
            event_id=event_id,
            payload=payload,
            at_ms=now,
            expected_version=snapshot.version,
            expected_state_hash=snapshot.state_hash,
            expected_head_sha256=snapshot.head_hash,
            fold=atomic_fold,
        )

    def _finish_liability_gates(self, state, outcome):
        missing, unknown = [], []
        for cost_id in self.config["expected_cost_ids"]:
            liability = state["service_liabilities"].get(cost_id)
            if liability is None or liability["status"] != "SETTLED":
                missing.append(cost_id)
                if liability is not None and liability["status"] == "UNAVAILABLE":
                    unknown.append(cost_id)
                continue
            event = self.journal.lookup_native_event(cost_id)
            expected = ("SERVICE", Decimal(liability["amount"]), liability["at"])
            if event is None:
                missing.append(cost_id)
            elif event.payload != expected:
                raise SimInputError("settled service liability differs from exact original native debit")
        unadmitted = self.binding.evidence_kind != "TEST_FIXTURE"
        if missing or unknown or unadmitted:
            outcome["status"], outcome["net_return"] = "UNRESOLVED", None
        outcome.update(
            {
                "missing_service_costs": missing,
                "unavailable_service_costs": unknown,
                "episode_minutes": 7200,
                "storage": FINANCIAL_HORIZON_ID,
                "funding_schedule_unadmitted": unadmitted,
                "accepted_historical_inputs": False,
            }
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
            state["account"] = self._store_account(
                account_api.debit_cost(
                    self._load_account(state["account"]),
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
