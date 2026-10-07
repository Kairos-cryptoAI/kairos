# Historical pilot: local companion budget prerequisite

## Scope and result

Added `historical_pilot_budget.py` and offline tests to the development replay
package. This is a reusable prerequisite, **not** completion of the requested
paid historical A/B. No model request, secret read, runtime budget creation,
shared PostgreSQL mutation, primary recovery or venue action was performed.
The prior source-only and no-call evidence remains unchanged.

The approved fixed draft has SHA-256
`d9347eeca568f6b8fc98a75645ffe484e27df2ce3cd84415b97f8b554d12e497`.
The helper binds its exact two episodes, four UTC cuts and five symbols to twenty
one-shot slots, with a cumulative local ceiling of 1,000,000 microUSD (USD 1).
Neither a new slot roster nor a different draft identity is accepted implicitly.

## Implemented invariants

- Explicit create-new initialization; opening a missing ledger never creates it.
- Canonical externally supplied UUID, unchanged draft hash and exact slot roster.
- Absolute task-owned runtime path; symlinks/junctions are rejected.
- Atomic `BEGIN IMMEDIATE`, foreign keys and FULL synchronization.
- Full metadata, ordinal/slot, row, cost, state and seal checks before opening,
  calculating headroom, reserving or settling.
- Positive integer worst-case reservations; committed plus unresolved held costs
  consume the cap. A duplicate slot cannot obtain another admission.
- Known actual-cost settlement releases only unused monetary reserve, not a slot.
  Error/cancellation/unknown outcomes have no automatic release operation.
- Known expense overruns are retained and seal new reservations. Multiple already
  held attempts may still return actual overruns; each is recorded, the first
  seal reason is preserved, and repeated identical settlement is idempotent.
  A conflicting settlement is rejected without rewriting accepted expense.

Independent review found and fixed persisted-row accounting and public-constructor
validation defects, then the multiple-already-held-overruns rollback edge case.
The final review found no remaining substantive defect in this helper's scope.
Tests cover concurrency, duplicate-slot races, cap exhaustion, reopen, missing
and mismatched identities, held expenses, corrupt SQL rows, constructor bypass,
conflicting settlement and multiple-overrun/reopen retention.

## Explicit limits

The snapshot metric is `slot_admissions`, **not observed provider calls**.
This helper does not adopt/query/replace the existing authoritative PostgreSQL
USD 12 campaign accounting or prove current shared headroom. It is not protection
against creating a replacement ledger under a new identity or administrative
rollback of a filesystem. A later admitted dispatcher must fix one ledger
path/UUID in its external run admission, forbid replacement/reset, reserve both
budgets before one native underlying attempt and preserve unresolved outcomes.

No production ledger was initialized and no actual slot was consumed here.
NEWS/MACRO semantic source admission, the final candidate/route identity and the
native paid dispatcher remain separate gates. Local tests cannot grant them.
The old no-call preflight is not rerun. The frozen plans, Trial 15 and V4/V5
evidence are not changed. `PAPER_QUALIFIED`, `ALPHA_READY`, `LIVE_READY` remain
false and `STRATEGY_POLICY=REJECT_ALL`.
