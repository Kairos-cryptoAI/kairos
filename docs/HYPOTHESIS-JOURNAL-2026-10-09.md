# Durable hypothesis evidence and quote-source boundary

Date: 2026-10-09 Europe/Moscow; work began October 8.
Classification: ENGINEERING_ONLY_TEST_FIXTURES, trading authority NONE.
This is an additive continuation of [hypothesis v2](HYPOTHESIS-LIFECYCLE-V2-2026-10-08.md),
not another historical attempt, model experiment or production recovery.

## Delivered library boundary

[hypothesis_journal.py](../development/adaptive_replay/adaptive_replay/hypothesis_journal.py)
is an opt-in bounded local SQLite research journal. Nothing registers it with a
runner, event bus, runtime publisher, PostgreSQL database or venue. There is no
CLI, credential loader, background process, automatic retry or migration.
The prior v1/v2 engines, bridge, comparator, results and frozen ledgers are unchanged.

The journal freezes an explicit experiment identity, source-set hash, seal clock,
canonical arm roster, exact arm policies and capacity before observations.
All arm policies share that seal clock; chronology is caller-attested consistency,
not proof of genuine historical preregistration. At most eight declared arms,
128 arm/parent registrations and 60 observations per registered hypothesis are
supported. These are engineering bounds, not a selected campaign or daily quota.
Capacity exhaustion refuses work without eviction or a replacement journal.

Consumption is keyed by the **original native parent intent ID within the sealed
arm**, not the changeable hypothesis ID. Changed validity, policy, context,
regime, protections or source identity cannot rescue that parent's refusal.
Matched arms retain the same original plan/evidence except their declared policy.
An arm must register a parent before the first observation for that parent in
any arm; even a quiet first observation closes late enrollment. This prevents
selectively adding a control after seeing treatment outcomes. The journal does
not generate or authenticate upstream parents or prove exhaustive enrollment.

The API is deliberately small:

```text
HypothesisJournal.create(new_path_ending_in_.research.sqlite3, retained_seal)
HypothesisJournal.open(existing_path, the_same_retained_seal)
register(arm_id, exact_original_HypothesisPlan)
append(arm_id, original_native_parent_intent_id, exact_HypothesisObservation)
snapshot()
```

Create reserves the file exclusively in an existing directory. Existing files,
missing journals on reopen, symlinks/junctions/reparse paths, hard-link aliases,
oversized files and incompatible schemas fail closed. An interrupted invalid
creation is preserved, not deleted/reinitialized. Opening a valid journal may
recover its own SQLite hot rollback journal; this is unrelated to the guarded
primary/runtime recovery contour.

## Durable first-trigger and replay checks

Each operation holds a SQLite transaction while checking the exact schema,
retained seal, installed research/Strategy/Core Python source-byte inventory,
current mechanics/capabilities/planning configuration, parent/event parity,
contiguous global sequence, complete hash links and anchored count/head.
No edited file or configuration is silently adopted by reopening a journal.
Source bytes describe the installed inventory; they cannot attest hostile
in-process monkeypatches or prove loaded code equals a subsequently rewritten file.
A fresh process using the retained admitted source set remains required.

Exact canonical JSON reconstructs typed native intents, complete ExitPlans,
candles, context receipts, quotes, reviews, policies and observations. Missing,
unknown, duplicate or normalized-away fields are rejected. Native intent IDs are
recomputed rather than trusted. Every stored evaluation/candidate is compared
to a fresh execution of the unchanged v2 fold; stored result JSON alone has no
authority. Snapshots use immutable typed objects rather than mutable dictionaries.

Registration/observation, candidate evidence and chain head/count commit atomically
with `BEGIN IMMEDIATE`, foreign keys and FULL synchronization in DELETE-journal
mode. Concurrent independent writers serialize; conflicts never overwrite the
winning original receipt. A lock timeout/error has no automatic retry path.
Exact redelivery returns its original receipt with `new_event=false`; changed
same-minute quote/review/source/clock data is rejected, including after terminal
states. Subsequent terminal observations may be recorded for refusal accounting,
but cannot issue another candidate. Crash before commit rolls back; crash after
commit/before acknowledgement reopens as redelivery, not a fresh attempt.

The guarantee is **at most one durably recorded research candidate per registered
parent/arm in this retained journal**. It is not global exactly-once publication,
an outbox, Risk approval or venue execution. A candidate field on a replayed
receipt is historical evidence, not a command to dispatch. Local hash links are
not signatures, publisher authentication or protection against an owner copying
an older entire database/rewriting all anchors. No new file, changed experiment
or fabricated parent is permitted to rescue this result. Future admitted campaigns
still need independently retained/signed anchors and their complete source roster.

## Source capability audit: no accepted causal quote corpus

The inspected existing sources do **not** supply accepted historical two-sided
quotes together with preserved local receipt/capture clocks:

| Existing evidence | What it contains | Missing authority |
| --- | --- | --- |
| Accepted kline/source set | Minute OHLCV and exchange open/close clocks | Bid/ask, depth and historical local receipt; `historical_receive_clock_proven=false` |
| PRICE_ONLY reference | Explicit OHLC projection, volume fields withheld | It does not repair source fields or inherit volume/quote qualification |
| Fixed aggTrades source plan | Recorded aggregate prints and exchange transaction/ID data | Explicitly not BBO, depth or our fill; arrival timing is an assumption |
| Runtime MarketSnapshot/context cache | Best bid/ask summary plus source-produced time; process-local receiver receipts | No accepted durable historical quote corpus; cache restart cannot prove old local availability |
| v2 EntryQuote fixtures/attestation | Explicit bid/ask, event/receipt/capture clocks, source and evidence label | Consistency checks and hashes do not authenticate the publisher or supplied chronology |

Source boundaries are preserved in
[source composition](../development/adaptive_replay/adaptive_replay/source_composition.py),
[source acceptance](../development/adaptive_replay/adaptive_replay/source_set.py),
[intraday plan](../development/adaptive_replay/intraday-source-plan.json),
[price-source protocol](STRATEGY-PRICE-SOURCE-PROTOCOL-2026-10-07.md) and the
[scoped causal engineering manifest](../config/adaptive-causal-source-set.json).
The neighboring native `kairos-core/kairos_core/contracts/market.py` defines
the summary; `kairos-aggregator/kairos_aggregator/decision_context.py` explicitly
states the process-local receipt/restart limitation. Neither neighboring repository
was modified by this work.

No candle close, mid-price, mark or print is converted into an alleged historical
bid/ask. No modern download/inference clock becomes a historical local receipt.
The journal preserves all supplied observations and refusals but cannot upgrade
`TEST_FIXTURE`/`CALLER_ATTESTED_POINT_IN_TIME` into accepted source provenance.
Actual quote admission still needs immutable raw payload/source binding and
independently accepted provenance, clock coverage and missing-denominator evidence.
No feed was started or downloaded here.

## Verification and next gate

Synthetic tests cover restart with complete LONG/SHORT trailing protection,
quiet-to-trigger transitions, refusal persistence, exact/conflicting duplicates,
changed parent plans/policies, frozen source/arm identity, late-arm exclusion,
capacity, missing/invalid files, competing independent writers, exception rollback,
actual isolated process exit before/after commit, and corruption of schema,
plan/intent/protection, stored result/candidate, minute key, hash links and head/count.
These are engineering fixtures, not real market observations or economic results.
The implementation is GPG-signed main
`48cce97c7eafeaba83ff4b55e0552fad1b1e21c1`; complete scope documentation is
`c7dc0d674096608219c9f7f2a5f6e74f30529df8`. GitHub confirms both signatures
as verified/valid.

All 43 new cases pass, without new skips. Complete fresh **non-editable installed
wheel** suites pass on Python 3.11.15 and 3.14.7: 994 passed and two existing
platform symlink-fixture skips in each. Ruff lint/format (116 files), unchanged
lock verification, wheel/sdist build and Meta static/Markdown/checkout-regression
gates pass. Environments/builds are retained under
`D:\Kairos\runtime\hypothesis-journal-build-20261008`. Installed journal bytes
match the checkout in both environments; SHA-256 is
`ba82877477bc1b0b81c8128361518e52287633e800e02d2d8402a35535b4a21d`.
The old v1 scenario/bridge/comparator and v2 hypothesis/bridge byte hashes match
their prior receipts; Strategy and Backtest main remain clean and unchanged.
Complete source/documentation revision
`c7dc0d674096608219c9f7f2a5f6e74f30529df8` passed all hosted gates:

- [Adaptive installed-wheel fixtures](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37846033803):
  996 passed, zero skips, in each Windows/Linux x Python 3.11/3.14 job.
- [Meta validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37846033717): passed.
- [CodeQL](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37846034031): Python and Actions passed.

This verification-only receipt changes no source/configuration/dependency identity,
old evidence, research enrollment, runtime pins or trading authority.

Remaining before a new economic/model experiment: authentic causal quote/context
coverage; independent actual-fill feasibility against unchanged stop/target/trailing
activation and execution costs; one new predeclared matched roster/identity with
all refusals and unavailable cells. A closed-bar journal does not prove continuous
tick-path integrity, safe adverse fills or production trailing support. Native
runtime still refuses trailing; it was not changed. No automatic parameter search,
old-result rescue, provider rerun or new blind campaign follows.

Paid models/feeds, EVEDEX/canary/LIVE, Docker PAPER services, primary DB/leases/cursors,
runtime recovery, release/dependency pins and locks remain untouched. Risk caps
remain 0.25% per trade and 1% aggregate open risk, without a required daily trade count.
`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`.
