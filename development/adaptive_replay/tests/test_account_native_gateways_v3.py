"""Lossless native-fold differential tests, not transactional persistence proof."""

import ast
import copy
import inspect
from dataclasses import replace
from decimal import Context, localcontext
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import pytest

from adaptive_replay import adaptive_sim_account as api
from adaptive_replay.account_event_context_v3 import (
    NativeEventContext,
    NativeEventContextError,
    canonical_native_event,
)
from adaptive_replay.continuous_sim import ContinuousSimPortfolio, FundingInput
from adaptive_replay.sim_account_codec import decode_account, encode_account
from adaptive_replay.sim_account_core_codec_v3 import (
    AccountLedgerRefV3,
    decode_account_core,
    encode_account_core,
)

from . import test_continuous_sim as fixture


def financial(account):
    return encode_account(replace(account, events=()))


class ExplicitCoreFold(ContinuousSimPortfolio):
    """Test-only external index; deliberately no durable/atomic journal claim.

    Execute the real shared reducer with a codec boundary after every event.
    The production consumer must instead own one atomic financial transition.
    """

    def __init__(self, original):
        super().__init__(
            SimpleNamespace(lookup=lambda **kwargs: None),
            original.binding,
            original.models,
            original.rules,
            original.funding,
            original.config,
            original.path,
            original.candle_originals,
        )
        self.state = copy.deepcopy(original.snapshot().state)
        self.events = []
        self.ref = AccountLedgerRefV3("test-owner", "test-account", 0, "a" * 64)
        self.state["account"] = encode_account_core(decode_account(self.state["account"]), self.ref)
        self.active = None

    def _load_account(self, document):
        account, reference = decode_account_core(document)
        assert reference == self.ref
        if self.active is not None:
            self.active.validate_account(account)
        return account

    def _store_account(self, account):
        return encode_account_core(account, self.ref)

    def snapshot(self):
        return SimpleNamespace(state=copy.deepcopy(self.state))

    def _event(self, event_id, payload, now, reducer):
        state = copy.deepcopy(self.state)
        index = {e.event_id: e for e in self.events}
        context = NativeEventContext(
            owner_id="test-owner",
            account_id="test-account",
            account=self._load_account(state["account"]),
            lookup_exact=index.get,
            allowed_quantity_steps=tuple(sorted({r.quantity_step for r in self.rules.values()})),
        )
        with context.scope(owner_id="test-owner", account_id="test-account"):
            self.active = context
            try:
                with localcontext(Context(prec=96)):
                    outcome = reducer(state)
                stage = context.staged_events
                account = self._load_account(state["account"])
            finally:
                self.active = None
        # In-memory test sealing only, never presented as a durable commit.
        self.events.extend(stage)
        self.ref = replace(self.ref, event_count=len(self.events))
        state["account"] = encode_account_core(account, self.ref)
        state["clock"], state["last_outcome"] = now, outcome
        self.state = state
        return SimpleNamespace(outcome=outcome)


def assert_fold_equal(old, core):
    old_state = copy.deepcopy(old.snapshot().state)
    core_state = copy.deepcopy(core.state)
    old_account = decode_account(old_state.pop("account"))
    new_account, reference = decode_account_core(core_state.pop("account"))
    assert old_state == core_state
    assert financial(old_account) == financial(new_account)
    assert tuple(map(canonical_native_event, old_account.events)) == tuple(
        map(canonical_native_event, core.events)
    )
    assert reference == core.ref and new_account.events == ()


@pytest.mark.parametrize("reason,price", [("STOP", "98"), ("TARGET", "106")])
def test_shared_fold_partial_entry_partial_natural_exit_cost_late_funding(tmp_path, reason, price):
    p, first = fixture.parent(), fixture.book(aqty="0.2")
    due = fixture.ISSUE + 10
    funding = FundingInput(
        "BTCUSDT",
        due,
        fixture.ISSUE + 130,
        "funding",
        "TEST_FIXTURE",
        "SETTLED",
        D("0.001"),
        D("100"),
        fixture.SHA,
    )
    frames = [
        fixture.book(seq=2, at=fixture.ISSUE + 100, bid=price, ask=str(D(price) + D("0.01")), bqty="0.1"),
        fixture.book(seq=3, at=fixture.ISSUE + 110, bid=price, ask=str(D(price) + D("0.01")), bqty="0.1"),
        fixture.book(
            seq=4,
            at=fixture.ISSUE + 120,
            bid=str(D(price) + D("0.01")),
            ask=str(D(price) + D("0.02")),
            bqty="0.1",
        ),
    ]
    h, receipts = fixture.issue_journal(tmp_path, [p], {first.symbol: first})
    old = fixture.runner(tmp_path, [first, *frames, funding], h=h, due=(("BTCUSDT", due),))
    core = ExplicitCoreFold(old)
    try:
        for runner in (old, core):
            fixture.ingest(runner, 1)
            runner.debit_service(cost_id="service", amount=D("0.3"), at_ms=fixture.ISSUE)
            fixture.intake(runner, h, receipts["arm", p.template.intent_id])
            runner.advance_to(now_ms=fixture.ISSUE + 2, event_id="entry")
        assert_fold_equal(old, core)
        assert decode_account(old.snapshot().state["account"]).positions[0].quantity == D("0.2")
        # Actual V1 reopen, and explicit core serialization/reconstructed scope
        # at each boundary. The new durable journal is tested separately.
        old = fixture.reopen(old)
        for sequence, arrival in ((2, 102), (3, 112), (4, 122)):
            for runner in (old, core):
                fixture.ingest(runner, sequence)
                runner.advance_to(now_ms=fixture.ISSUE + arrival, event_id=f"exit-{sequence}")
            assert_fold_equal(old, core)
        assert not decode_account(old.snapshot().state["account"]).positions
        assert old.snapshot().state["parents"][p.template.intent_id]["exit_reason"] == reason
        for runner in (old, core):
            fixture.ingest(runner, 5)
            fixture.seal_slots(runner)
            runner.finish(now_ms=fixture.START + 2 * fixture.MINUTE, event_id="finish")
        assert_fold_equal(old, core)
        assert core.events[-1].payload[0] == "LATE_KNOWN_FUNDING"
        assert core.events[-1].payload[2] == D("-0.0200")
    finally:
        old.close()


def run_native(operations):
    old = api.new_account(D("10000"), api.AccountPolicy(D("0.1"), D("0"), D("0"), D("0"), 1000))
    core, retained = old, []
    for operation in operations:
        old_result = operation(old)
        old = old_result[0] if type(old_result) is tuple else old_result
        context = NativeEventContext(
            owner_id="owner",
            account_id="account",
            account=core,
            lookup_exact={e.event_id: e for e in retained}.get,
        )
        with context.scope(owner_id="owner", account_id="account"):
            core_result = operation(core)
            core = core_result[0] if type(core_result) is tuple else core_result
            assert (old_result[1:] if type(old_result) is tuple else ()) == (
                core_result[1:] if type(core_result) is tuple else ()
            )
            retained.extend(context.staged_events)
        assert financial(old) == financial(core)
        assert tuple(map(canonical_native_event, old.events)) == tuple(map(canonical_native_event, retained))
        reference = AccountLedgerRefV3("owner", "account", len(retained), "b" * 64)
        core, restored_ref = decode_account_core(encode_account_core(core, reference))
        assert restored_ref == reference
    return old, core, retained


def marked(account, event_id="flat", price="100", timestamp=10, clock=10):
    return api.mark_account(
        account, mark_id=event_id, marks=(("BTCUSDT", D(price), timestamp),), as_of_ms=clock
    )


@pytest.mark.parametrize("timestamp,clock", [(9, 10), (12, 11), (10, 1011)])
def test_flat_mark_keeps_all_audit_and_stale_regression_future_barriers(timestamp, clock):
    old, core, events = run_native(
        [
            marked,
            lambda a: marked(a, "invalid", timestamp=timestamp, clock=clock),
            lambda a: api.record_late_known_funding(
                a,
                event_id="late",
                funding_key="BTCUSDT:1",
                cashflow=D("-0.001"),
                at_ms=clock,
            ),
        ]
    )
    assert old.barrier == core.barrier == "STALE_OR_REGRESSING_MARK"
    assert [e.payload[0] for e in events] == ["MARK", "MARK", "LATE_KNOWN_FUNDING"]


def test_reservation_risk_tightening_funding_stop_and_duplicate_core_restart():
    def reserve(a):
        return api.reserve_entry(
            a,
            reservation_id="r",
            intent_id="i",
            symbol="BTCUSDT",
            side="LONG",
            stop_price=D("90"),
            worst_entry_price=D("100"),
            worst_notional_price=D("100"),
            as_of_ms=20,
            expires_at_ms=500,
        )

    operations = [
        marked,
        reserve,
        lambda a: marked(a, "reservation-mark", price="101", timestamp=21, clock=21),
        lambda a: api.record_entry_fill(
            a,
            reservation_id="r",
            fill_id="fill",
            quantity=D("1"),
            average_price=D("100"),
            fee=D("0.1"),
            at_ms=22,
        ),
        lambda a: api.resolve_entry(a, reservation_id="r", event_id="resolved", outcome="PARTIAL"),
        lambda a: api.tighten_stop(
            a,
            intent_id="i",
            event_id="tight",
            stop_price=D("95"),
            source_event_ms=23,
            available_ms=24,
            as_of_ms=24,
        ),
        lambda a: api.record_funding(a, intent_id="i", event_id="fund", cashflow=D("-0.0010"), at_ms=25),
        lambda a: marked(a, "stop", price="94", timestamp=26, clock=26),
        lambda a: api.request_protective_exit(a, intent_id="i", event_id="protect", reason="STOP"),
        lambda a: api.record_exit_fill(
            a,
            intent_id="i",
            fill_id="partial",
            quantity=D("0.4"),
            average_price=D("94"),
            fee=D("0.1"),
            at_ms=27,
        ),
        lambda a: api.record_exit_fill(
            a,
            intent_id="i",
            fill_id="closed",
            quantity=D("0.6"),
            average_price=D("94"),
            fee=D("0.1"),
            at_ms=28,
        ),
        lambda a: api.debit_cost(a, cost_id="cost", amount=D("0.02"), at_ms=29, kind="SERVICE"),
    ]
    old, core, retained = run_native([*operations, operations[-1]])
    assert not core.positions and core.events == () and len(retained) == len(operations)
    context = NativeEventContext(
        owner_id="owner",
        account_id="account",
        account=core,
        lookup_exact={e.event_id: e for e in retained}.get,
    )
    with context.scope(owner_id="owner", account_id="account"):
        assert operations[-1](core) is core
        with pytest.raises(NativeEventContextError, match="conflicting"):
            api.debit_cost(core, cost_id="cost", amount=D("0.03"), at_ms=29, kind="SERVICE")
        assert context.staged_events == ()
    assert financial(old) == financial(core)


def test_default_gateways_exact_v1_and_no_instance_codec_bypasses():
    portfolio = object.__new__(ContinuousSimPortfolio)
    account = api.new_account(D("1000"), api.AccountPolicy(D("0.1"), D(0), D(0), D(0), 1000))
    account = marked(account)[0]
    assert portfolio._store_account(account) == encode_account(account)
    assert portfolio._load_account(encode_account(account)) == account
    tree = ast.parse(inspect.getsource(ContinuousSimPortfolio))
    for method in tree.body[0].body:
        if not isinstance(method, ast.FunctionDef) or method.name in {
            "create",
            "_load_account",
            "_store_account",
        }:
            continue
        assert not any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id in {"encode_account", "decode_account"}
            for n in ast.walk(method)
        )


def test_late_helper_matches_original_inline_cash_pnl_tuple_with_decimal96():
    account = api.new_account(D("1000"), api.AccountPolicy(D("0.1"), D(0), D(0), D(0), 1000))
    account = api.set_barrier(account, event_id="before", reason="EXISTING_BARRIER")
    cashflow = D("-0.1234567890123456789012345678901234567890123456789")
    with localcontext(Context(prec=96)):
        expected = replace(
            account,
            cash=account.cash + cashflow,
            realized_net_pnl=account.realized_net_pnl + cashflow,
            events=(
                *account.events,
                api.AccountEvent("late", ("LATE_KNOWN_FUNDING", "BTCUSDT:1", cashflow, 10)),
            ),
        )
    actual = api.record_late_known_funding(
        account,
        event_id="late",
        funding_key="BTCUSDT:1",
        cashflow=cashflow,
        at_ms=10,
    )
    assert actual == expected
    assert encode_account(actual) == encode_account(expected)
    assert actual.barrier == "EXISTING_BARRIER"


def test_continuous_implementation_binds_explicit_native_context_source(monkeypatch):
    from adaptive_replay import continuous_sim
    from adaptive_replay.account_event_context_v3 import current_native_event_context

    context_path = Path(current_native_event_context.__code__.co_filename).absolute()
    baseline = continuous_sim._implementation()
    original_read = Path.read_bytes

    def changed_context_bytes(path):
        contents = original_read(path)
        return (
            contents + b"\n# virtual test-only context change\n"
            if path.absolute() == context_path
            else contents
        )

    monkeypatch.setattr(Path, "read_bytes", changed_context_bytes)
    assert continuous_sim._implementation() != baseline
