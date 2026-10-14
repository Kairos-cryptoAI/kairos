import asyncio
from dataclasses import replace
from decimal import Decimal as D

import pytest

from adaptive_replay.account_event_context_v3 import (
    NativeEventContext,
    NativeEventContextError,
    canonical_native_event,
    current_native_event_context,
    decode_native_event,
)
from adaptive_replay.adaptive_sim_account import AccountEvent, AccountPolicy, new_account

POLICY = AccountPolicy(D("0.1"), D("5"), D("5"), D("2"), 10_000)


def context(*, lookup=None, account=None, **limits):
    return NativeEventContext(
        owner_id="arm-a",
        account_id="account-a",
        account=account or new_account(D("10000"), POLICY),
        lookup_exact=lookup or (lambda _: None),
        **limits,
    )


def scope(value):
    return value.scope(owner_id="arm-a", account_id="account-a")


def test_default_absent_exact_index_staged_order_duplicate_conflict_and_finally_reset():
    assert current_native_event_context() is None
    original = AccountEvent("old", ("SERVICE", D("1.00"), 10))
    value = context(lookup=lambda key: original if key == "old" else None)
    with scope(value):
        assert current_native_event_context(new_account(D("10000"), POLICY)) is value
        assert value.lookup("old", ("SERVICE", D("1"), 10)) is original
        assert not value.stage_append(original)
        first = AccountEvent("mark:1", ("MARK", (("BTCUSDT", D("100.00"), 11),), 11))
        second = AccountEvent("mark:2", ("MARK", (("BTCUSDT", D("100.01"), 12),), 12))
        assert value.stage_append(first)
        assert value.stage_append(second)
        assert not value.stage_append(first)
        assert value.staged_events == (first, second)
        assert '"$decimal":"100.00"' in canonical_native_event(first)
        assert decode_native_event(canonical_native_event(first)) == first
        with pytest.raises(NativeEventContextError, match="conflicting"):
            value.lookup("old", ("SERVICE", D("2"), 10))
        with pytest.raises(NativeEventContextError, match="conflicting"):
            value.stage_append(AccountEvent("mark:1", ("MARK", (("BTCUSDT", D("99"), 11),), 11)))
    assert current_native_event_context() is None
    with pytest.raises(NativeEventContextError, match="scope"):
        _ = value.staged_events
    with scope(value):
        assert value.staged_events == ()


def test_indexed_stage_suffix_count_and_lookup_preserve_exact_order_and_scope():
    value = context()
    with scope(value):
        events = tuple(AccountEvent(f"mark:{i}", ("MARK", i)) for i in range(512))
        for i, event in enumerate(events):
            assert value.stage_append(event)
            assert value.staged_event_count == i + 1
            assert value.staged_suffix(i) == (event,)
            assert value.lookup_staged_event(event.event_id) is event
        assert value.staged_suffix(0) == value.staged_events == events
        assert value.staged_suffix(512) == ()
        assert not value.stage_append(events[0])
        assert value.staged_event_count == 512
        assert value.lookup_staged_event("not-staged") is None
        for invalid in (-1, 513, True, 1.0):
            with pytest.raises(NativeEventContextError, match="prefix"):
                value.staged_suffix(invalid)
    for operation in (lambda: value.staged_event_count, lambda: value.staged_suffix(0)):
        with pytest.raises(NativeEventContextError, match="scope"):
            operation()
    with pytest.raises(NativeEventContextError, match="scope"):
        value.lookup_staged_event("mark:0")
    with scope(value):
        assert value.staged_event_count == 0
        assert value.staged_suffix(0) == ()
        assert value.lookup_staged_event("mark:0") is None


def test_exception_cleanup_owner_identity_and_nested_scope_guards():
    value = context()
    with pytest.raises(NativeEventContextError, match="binding"):
        with value.scope(owner_id="arm-b", account_id="account-a"):
            pass
    with pytest.raises(RuntimeError, match="rollback"):
        with scope(value):
            value.stage_append(AccountEvent("cost", ("SERVICE", D("1"), 10)))
            with pytest.raises(NativeEventContextError, match="nested"):
                with scope(context()):
                    pass
            with pytest.raises(NativeEventContextError, match="identity"):
                current_native_event_context(new_account(D("20000"), POLICY))
            raise RuntimeError("rollback")
    assert current_native_event_context() is None
    with scope(value):
        assert value.staged_events == ()


def test_new_mode_does_not_strip_history_or_accept_wrong_external_index():
    account = replace(new_account(D("10000"), POLICY), events=(AccountEvent("old", ("MARK",)),))
    with pytest.raises(NativeEventContextError, match="empty events"):
        context(account=account)
    value = context(lookup=lambda _: AccountEvent("different", ("MARK",)))
    with scope(value), pytest.raises(NativeEventContextError, match="different ID"):
        value.lookup("wanted", ("MARK",))


@pytest.mark.parametrize("payload", [(1.25,), ([1],), (D("Infinity"),)])
def test_exact_event_schema_rejects_unserializable_native_payloads(payload):
    value = context()
    with scope(value), pytest.raises(NativeEventContextError, match="canonical"):
        value.stage_append(AccountEvent("bad", payload))


@pytest.mark.parametrize("encoded", ['{"x":1,"x":2}', '{"$decimal":"NaN"}', "1.25", "[]"])
def test_exact_native_event_decoder_rejects_duplicate_keys_unknown_roots_and_float(encoded):
    with pytest.raises(NativeEventContextError, match="canonical"):
        decode_native_event(encoded)


def test_native_event_decoder_rejects_alternate_canonical_text():
    encoded = canonical_native_event(AccountEvent("a", ("MARK",)))
    with pytest.raises(NativeEventContextError, match="canonical"):
        decode_native_event(" " + encoded)


def test_staging_count_and_byte_bounds_never_evict_prior_events():
    first, second = AccountEvent("a", ("MARK",)), AccountEvent("b", ("MARK",))
    for limits in ({"max_staged_events": 1}, {"max_staged_bytes": len(canonical_native_event(first))}):
        value = context(**limits)
        with scope(value):
            assert value.stage_append(first)
            with pytest.raises(NativeEventContextError, match="bound"):
                value.stage_append(second)
            assert value.staged_events == (first,)


def test_sealed_distinct_symbol_quantity_steps_do_not_change_native_policy_behavior():
    value = context(allowed_quantity_steps=(D("0.01"), D("0.1")))
    account = new_account(D("10000"), POLICY)
    with scope(value):
        switched = replace(account, policy=replace(POLICY, quantity_step=D("0.01")))
        assert current_native_event_context(switched) is value
        with pytest.raises(NativeEventContextError, match="identity"):
            current_native_event_context(replace(account, policy=replace(POLICY, quantity_step=D("1"))))
        with pytest.raises(NativeEventContextError, match="identity"):
            current_native_event_context(replace(account, policy=replace(POLICY, entry_fee_bps=D("6"))))


def test_inherited_async_context_cannot_share_mutable_stage():
    async def child():
        with pytest.raises(NativeEventContextError, match="scope"):
            current_native_event_context()

    async def parent():
        value = context()
        with scope(value):
            await asyncio.create_task(child())
            assert current_native_event_context() is value

    asyncio.run(parent())


@pytest.mark.parametrize("limit", [0, -1, True, 10_001])
def test_exact_positive_bounded_event_limit(limit):
    with pytest.raises(NativeEventContextError, match="limit"):
        context(max_staged_events=limit)
