"""Explicit, bounded native-event relocation plumbing; no persistence authority.

The caller owns the exact account/owner binding and the external event index.
Staging is NOT a commit: a transactional consumer must seal these original
events together with the financial projection. No existing reducer is hooked
by importing this module. Without an explicit scope, the context is absent.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from decimal import Decimal

from .adaptive_sim_account import AccountEvent, SimAccount, _id
from .sim_account_codec import _decode_value, _encode_value, _reject_constant, _reject_float, _unique_object

MAX_NATIVE_EVENT_BYTES = 2 * 1024 * 1024
MAX_STAGED_EVENTS = 10_000
MAX_STAGED_BYTES = 16 * 1024 * 1024


class NativeEventContextError(ValueError):
    """A binding, exact event, duplicate, or explicit staging bound failed."""


_ACTIVE: ContextVar[NativeEventContext | None] = ContextVar("native_account_event_context_v3", default=None)


def _execution_owner() -> tuple[int, object | None]:
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return threading.get_ident(), task


def canonical_native_event(event: AccountEvent) -> str:
    """Preserve the original typed event, Decimal spelling, and tuple tags."""
    if type(event) is not AccountEvent:
        raise NativeEventContextError("exact native AccountEvent required")
    try:
        AccountEvent(event.event_id, event.payload)
        encoded = json.dumps(
            _encode_value(event, 0), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
    except (TypeError, ValueError, RecursionError) as error:
        raise NativeEventContextError("invalid exact canonical native event") from error
    if len(encoded.encode("utf-8")) > MAX_NATIVE_EVENT_BYTES:
        raise NativeEventContextError("native event byte bound exceeded; nothing staged")
    return encoded


def decode_native_event(encoded: str) -> AccountEvent:
    """Strict canonical native audit decoding for a future exact index consumer."""
    if type(encoded) is not str or len(encoded.encode("utf-8")) > MAX_NATIVE_EVENT_BYTES:
        raise NativeEventContextError("bounded exact canonical native event text required")
    try:
        document = json.loads(
            encoded,
            object_pairs_hook=_unique_object,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
        event = _decode_value(document, 0)
        if canonical_native_event(event) != encoded:
            raise NativeEventContextError("native event text is not canonical")
        return event
    except (TypeError, ValueError, RecursionError) as error:
        raise NativeEventContextError("invalid exact canonical native event text") from error


class NativeEventContext:
    """One explicit account binding and transaction-local exact indexed stage.

    SimAccount has no owner field: owner/account IDs must come from the caller's
    independently bound portfolio, never be inferred from equal financial data.
    Sealed policy fields/quantity steps and capital additionally fence drift.
    ContextVar inheritance does not permit sharing an active context across
    async tasks: each caller must create and enter its own context.
    """

    def __init__(
        self,
        *,
        owner_id: str,
        account_id: str,
        account: SimAccount,
        lookup_exact: Callable[[str], AccountEvent | None],
        allowed_quantity_steps: tuple[Decimal, ...] | None = None,
        max_staged_events: int = MAX_STAGED_EVENTS,
        max_staged_bytes: int = MAX_STAGED_BYTES,
    ) -> None:
        _id(owner_id, "native owner_id")
        _id(account_id, "native account_id")
        if not callable(lookup_exact):
            raise NativeEventContextError("external exact event lookup required")
        for value, maximum in ((max_staged_events, MAX_STAGED_EVENTS), (max_staged_bytes, MAX_STAGED_BYTES)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise NativeEventContextError("explicit positive bounded staging limit required")
        self._owner_id, self._account_id = owner_id, account_id
        self._lookup_exact = lookup_exact
        self._max_events, self._max_bytes = max_staged_events, max_staged_bytes
        self._staged: dict[str, AccountEvent] = {}
        self._staged_order: list[AccountEvent] = []
        self._staged_bytes = 0
        self._entered = False
        self._execution: tuple[int, object | None] | None = None
        if type(account) is not SimAccount:
            raise NativeEventContextError("exact bound SimAccount required")
        self._policy, self._initial_equity = account.policy, account.initial_equity
        steps = (account.policy.quantity_step,) if allowed_quantity_steps is None else allowed_quantity_steps
        if (
            type(steps) is not tuple
            or not 1 <= len(steps) <= 5
            or any(type(step) is not Decimal or not step.is_finite() or step <= 0 for step in steps)
            or tuple(sorted(set(steps))) != steps
        ):
            raise NativeEventContextError("sealed canonical positive quantity-step roster required")
        self._quantity_steps = steps
        self.validate_account(account)

    @property
    def owner_id(self) -> str:
        return self._owner_id

    @property
    def account_id(self) -> str:
        return self._account_id

    def validate_account(self, account: SimAccount) -> None:
        """Validate only new-mode accounts; do not strip existing audit history."""
        if type(account) is not SimAccount or account.events != ():
            raise NativeEventContextError("new-mode account requires exact SimAccount with empty events")
        if (
            account.policy.quantity_step not in self._quantity_steps
            or replace(account.policy, quantity_step=self._policy.quantity_step) != self._policy
            or account.initial_equity != self._initial_equity
        ):
            raise NativeEventContextError("bound account identity changed")

    def _require_active(self) -> None:
        if not self._entered or _ACTIVE.get() is not self or self._execution != _execution_owner():
            raise NativeEventContextError("explicit matching native event scope required")

    @contextmanager
    def scope(self, *, owner_id: str, account_id: str) -> Iterator[NativeEventContext]:
        """Scope staging only; always discard the stage and restore the token."""
        _id(owner_id, "native owner_id")
        _id(account_id, "native account_id")
        if (owner_id, account_id) != (self.owner_id, self.account_id):
            raise NativeEventContextError("native owner/account binding conflict")
        if self._entered or _ACTIVE.get() is not None:
            raise NativeEventContextError("nested or shared native event scope forbidden")
        self._entered = True
        self._execution = _execution_owner()
        token = _ACTIVE.set(self)
        try:
            yield self
        finally:
            _ACTIVE.reset(token)
            self._staged.clear()
            self._staged_order.clear()
            self._staged_bytes = 0
            self._entered = False
            self._execution = None

    def lookup(self, event_id: str, payload: tuple[object, ...]) -> AccountEvent | None:
        """Match native reducer equality; conflicting content never becomes replay."""
        self._require_active()
        candidate = AccountEvent(event_id, payload)
        canonical_native_event(candidate)
        prior = self._staged.get(event_id)
        if prior is None:
            prior = self._lookup_exact(event_id)
        if prior is not None:
            canonical_native_event(prior)
            if prior.event_id != event_id:
                raise NativeEventContextError("external event index returned a different ID")
            if prior.payload != payload:
                raise NativeEventContextError("event ID reused with conflicting content")
        return prior

    def stage_append(self, event: AccountEvent) -> bool:
        """Stage one original event once, preserving native order; never evict."""
        self._require_active()
        encoded = canonical_native_event(event)
        if self.lookup(event.event_id, event.payload) is not None:
            return False
        size = len(encoded.encode("utf-8"))
        if len(self._staged) >= self._max_events or self._staged_bytes + size > self._max_bytes:
            raise NativeEventContextError("native staging bound exceeded; nothing evicted")
        self._staged[event.event_id] = event
        self._staged_order.append(event)
        self._staged_bytes += size
        return True

    @property
    def staged_events(self) -> tuple[AccountEvent, ...]:
        """Consumer must seal this ordered stage before leaving the scope."""
        self._require_active()
        return tuple(self._staged.values())

    @property
    def staged_event_count(self) -> int:
        """Constant-time count; read only within the same exact task scope."""
        self._require_active()
        if len(self._staged_order) != len(self._staged):
            raise NativeEventContextError("native stage index/order mismatch")
        return len(self._staged_order)

    def staged_suffix(self, start: int) -> tuple[AccountEvent, ...]:
        """Copy only newly staged events, never the already committed prefix."""
        count = self.staged_event_count
        if type(start) is not int or not 0 <= start <= count:
            raise NativeEventContextError("exact retained native stage prefix required")
        return tuple(self._staged_order[start:])

    def lookup_staged_event(self, event_id: str) -> AccountEvent | None:
        """Indexed, scope-bound lookup; absence is not a persistence answer."""
        self._require_active()
        _id(event_id, "native event_id")
        return self._staged.get(event_id)


def current_native_event_context(account: SimAccount | None = None) -> NativeEventContext | None:
    """Default is absent; an active context validates any supplied native core."""
    context = _ACTIVE.get()
    if context is not None:
        context._require_active()
        if account is not None:
            context.validate_account(account)
    return context
