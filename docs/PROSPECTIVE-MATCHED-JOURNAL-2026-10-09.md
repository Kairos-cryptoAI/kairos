# Prospective V3 matched journal — October 9, 2026

## Implemented boundary

The separate `hypothesis_journal_v3` is durable local research evidence for the
unchanged V3 first-trigger fold. It is not production intake, source admission,
an authenticated provider ledger or a completed historical economic comparison.
V2, Trial 15, V4/V5 and their frozen plans/ledgers/originals are not migrated.

A pre-cut seal fixes the bounded arm roster, V3 policies, model configuration
identities and static source profile. It does not precommit unknown future
candidate payloads. Actual post-cut parents enroll with their unchanged
anchor, source/context identity and complete ExitPlan before observations.
Every enrolled arm has the exact same parent plan except its sealed policy.
Counterfactual enrollment is not permission to execute a context proposal in
the strategy-only account; explicit origin routing remains a driver obligation.

## Matched observations without invented review identity or latency

`MatchedObservationV3` commits the original shared candle, source and quote
bytes/clocks once in its input contract, with one explicit completion receipt
for every sealed arm. A shared observation has no arm-bound review and cannot
contain source/quote captures after its shared availability clock.

Reviewed arms retain their own unmodified scenario/response identity, sealed
model configuration and actual requested/completed/captured/decision clocks.
Requests cannot predate supplied inputs. Their original quote is not replaced
after model completion: expiry is a refusal, not a retry with a favorable quote.
The no-review arm has no model review and keeps the original shared clock; it
does not inherit model latency. A missing review remains explicitly missing,
not a receipt added to an already consumed trigger on redelivery.

All arm rows for one observation commit in one SQLite transaction. Audit checks
equal source denominators, exact enrollment/protection and complete contiguous
arm sequence blocks, while preserving different actual decision clocks and
review outcomes. Exact full-batch redelivery returns original receipts;
changed market, quote, decision or review bytes conflict. The fold records
`CONSUMED` even when a first trigger is refused: tests assert reason, coverage
and candidate separately, never equate consumption with a trade.

The arm clocks remain caller attestations. Batch commit is not proof that the
baseline was physically dispatched earlier, that a model actually ran, that
its output was authenticated or that sources were comprehensive. The later
driver/provider receipts must supply those distinct evidence boundaries.

## Restart, concurrency and boundedness

Reopening requires a caller-retained `JournalCheckpointV3` (seal, sequence and
head hash). A longer valid suffix is permitted; a shorter/divergent chain is
rejected. The caller must durably retain its strongest checkpoint independently
of the journal. Reading a checkpoint from the same restored database does not
authenticate recency, and hashes alone do not establish publisher authenticity.

SQLite `BEGIN IMMEDIATE`, FULL synchronous mode and rollback retain all-or-none
matched writes. Instance operations also serialize checkpoint handoff after
commit, preventing a slower older same-instance operation from downgrading it.
The page limit is checked before commit; crossing the byte cap cannot silently
commit a journal that its next reader refuses. No repair, schema migration,
automatic retries, queue/cursor reset or production database connection exists.

The final G immutable installed-wheel gate is under
`D:\Kairos\runtime\v3-journal-gates-20261009-g`. Seventy-five focused V3/journal
checks pass on Python 3.11 and 3.14 with `-I --import-mode=importlib -W error`.
The complete G suites each finish with native exit zero: 1,603 passed and four
explicit platform skips, in 329.62 s / 259.64 s on Python 3.11 / 3.14. All 66
installed adaptive Python sources in each private environment match the exact
retained wheel bytes; its SHA-256 is
`821f025ad0231e23415438189c2fb49eb296bcd0bdbec7bc4b0d16b1bf616083`.
The scoped [gate receipt](receipts/prospective-journal-gates-20261009.json)
records these engineering checks, not source or economic admission.

The first F Python 3.14 focused process is retained as a failure: its 61 test
assertions passed, but strict shutdown failed on an unclosed connection in a
test fixture. Explicit connection closure fixes that fixture; no warnings were
filtered and no failing case was skipped. The separate corrected F run returns
zero. F predates the instance-lock fix and is not final G acceptance.

## Full points 1–3 are still open

The current source inventory does not contain the complete accepted historical
NEWS/MACRO/BBO corpus. Transferred sampled depth is not historical coverage.
Current native REST finality correctly requires two matching normalized closed
bar observations, but discards exact response bytes and per-attempt receipt
clocks. Its return can also mean a bar is pending a gap, not yet promoted into
a usable contiguous prefix. A new raw receipt producer must retain both actual
attempts, native finality identity and actual later promotion/persistence.
WebSocket `x=true` alone cannot supply authoritative finality.

The old frame cannot be relabelled prospective: its contemporaneous history
requires capture by the price cut, unlike real post-cut finality. The new frame
must keep the price origin separate from actual knowledge/materialization,
filter future-captured context versions and coverage before selecting them,
and never turn an origin-frame response into a review of later quotes.

At the G journal stage the continuous portfolio had exact V2 intake. The later
[separate V3 intake](PROSPECTIVE-PORTFOLIO-INTAKE-2026-10-09.md) connects original
receipts and normalized candle provenance, while retaining the 1,440-minute
denominator limit. It is not the fixed five-day episode or indefinite SIM.
The remaining sealed horizon/rollover must preserve the same
account, exposures, liquidity, natural exits, funding, expenses, source cursor
and complete denominator; new daily accounts are not an acceptable substitute.
Native 200-bar default buffers / 1,500-row REST pages also do not supply the
3,240-bar rolling context or expanding breakout prefix without pinned warmup.

The fixed four-arm source/provider/cost-routing driver and actual economic run
remain unfinished. Unknown costs, missing sources and unresolved exits cannot
be turned into zero or omitted. Paid model execution still needs accepted
source/budget evidence and fresh owner confirmation. No winner, new blind
campaign credit, PAPER/ALPHA/LIVE approval or trading authority follows.

All four readiness flags remain false and `STRATEGY_POLICY=REJECT_ALL`.
