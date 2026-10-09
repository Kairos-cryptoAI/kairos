# Prospective V3 storage foundations — October 9, 2026

## Implemented and retained

`sim_delta_journal_v3` is an additive, create-only SQLite journal. It commits
canonical state deltas and the indexed current projection atomically, retaining
the source cursor and exact original event outcomes. Reopen requires an
independently held checkpoint and replays the complete retained chain. Normal
append/lookup/checkpoint reads use the current projection and retained prefix;
they do not serialize a new complete historical snapshot for every event.
Exact redelivery returns its original outcome; changed payloads, missing tree
children, corrupted projections, rollback and checkpoint conflicts fail closed.
It does not migrate or repair any existing journal or frozen evidence.

`rest_candle_receipts_v3` retains exact caller-supplied response bytes for the
fixed public GET one-minute kline request. The response body, or explicit
no-response marker, is fsynced before sampling its persistence clock and
appending the chained receipt. HTTP errors, cancellation and no-response are
retained attempts, not omitted successes. Reopen audits against an independent
checkpoint. Request/receive/body-persistence clocks are explicit caller-attested
clocks, not an authenticated historical source or an exchange finality proof.
The body-persistence clock is not the later receipt-commit or SIM-availability
clock. This module performs no HTTP request and reads no credentials.

Three narrow hooks in the existing portfolio expose the unchanged one-input
financial reducer, exact-originals guard and account marking. Its public
one-day path retains the existing limits and semantics. The separate unfinished
five-day implementation is not part of this acceptance.

## Bounds and five-day storage fixture

The default delta journal permits 512,192 rows, with explicit state/event/byte
caps. This profile includes 36,000 candle cells and 36,000 minute-denominator
cells, plus a declared five-second quote roster and bounded control allowance.
It is not a claim that an arbitrary native 100-ms quote feed fits this profile.
Input batching must preserve every original input and its causal order; no
sampling, quiet-cell removal or forced natural exit is authorized.

The retained C storage-only fixture wrote all 36,000 candles and 36,000 cells in
24 delta events while preserving exposure, consumed liquidity and unavailable
funding state. On Python 3.11 it measured 21,602,304 database bytes and 6,010,058
delta bytes in 59.387 seconds. Those are fixture storage measurements, not
five-day execution, source completeness, funding qualification or economics.
The REST receipt store separately has bounded 512-attempt / 128-MiB capacity;
it is a retained sample foundation, not full historical warmup ingestion.

## Exact installed-wheel checks

The immutable D snapshot contains 69 adaptive Python modules and 84 test files.
Both isolated private environments install its exact non-editable wheel:

`db6de94fa7941dd47630a060dd77b345061dff4445c584d07b58342a1f922066`

The full suites finished with native exit zero:

| Python | Passed | Explicit skips | Console seconds |
| --- | --- | --- | --- |
| 3.11.15 | 1,672 | 5 | 408.86 |
| 3.14.7 | 1,672 | 5 | 328.95 |

Every installed adaptive module in each environment matches the wheel's exact
roster and bytes. Isolation, importlib loading and warnings-as-errors remain
enabled. Tests run through the 84 frozen filenames at their original repository
paths, where unchanged companion JSON/script assets exist. Their byte hashes
are checked against D before and after execution. Unfinished horizon and
closed-bar-fold modules/tests are excluded, not credited as accepted.
Ruff check/format, locked dependency checks and the meta static/link/release
checkout regression pass. No dependency, provider route or manifest pin changed.

The [machine-readable receipt](receipts/prospective-storage-gates-20261009.json)
retains exact hashes, results and failed earlier attempts. In particular, C's
full tests failed during collection because its copied test location omitted
the companion historical-episode JSON and legacy-export script. Those failures
remain intact. D uses original companion paths without suppressing an error or
skipping the affected tests. C's earlier REST lint findings and SQLite test
connection-lifetime fix are recorded separately from the final D passes.

## Remaining full points 1–3

Raw native closed-bar promotion, prospective frame/provider integration,
accepted complete historical BBO/NEWS/MACRO coverage, a non-resetting five-day
financial run and the fixed four-arm economic driver remain open. Storage-only
tests and receipt hash consistency cannot substitute for those requirements.
Unknown coverage and unknown expenses remain unavailable, never zero-return
evidence. Physical shared provider spend and each arm's modeled expenses must
remain distinct. No model call, winner, blind credit or trading follows.

All four readiness flags remain false and `STRATEGY_POLICY=REJECT_ALL`. Trial
15/V2/V4/V5 and their plans/ledgers are unchanged; primary recovery and consumers
remain guarded. UI remains deferred.
