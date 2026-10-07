# Historical pilot: actual bounded attempts — 2026-10-07

This is a development diagnostic, not a completed paid matched A/B, alpha gate,
champion selection, blind-campaign result or trading authorization. No archive
queries, downloads, credentials, provider calls, production database operations
or venue actions were used for these attempts. Trial 15 and frozen campaigns
remain unchanged. All readiness fields remain false; policy is `REJECT_ALL`.

## Full price-only attempt: partial, not successful

After signed source `b6efee351624b299ae64681ccc3dbfcb8c818d42` passed exact
GitHub adaptive development CI `37660151639`, validate `37660151640` and CodeQL
`37660151839`, one installed-wheel attempt ran at
`D:\Kairos\runtime\historical-pilot-price-sim-20261007-a`.

It stopped fail-closed after **900.047 seconds** at its predeclared 900-second
cooperative bound. The [failure receipt](../development/adaptive_replay/evidence/historical-pilot-2026-10-07/partial-price-sim/failure.json)
records `TimeoutError`, completed episode A only and zero provider calls.
There is no `result.json` or final whole-run source equality proof. The bound
was not extended, and the attempt was not resumed, repeated or erased.

Episode A (May 17–22, 2021) completed its native 5m generation and four price
reports, including a raw-cache equality check before its completion marker:

- 7,200 native decisions: one candidate, 7,199 quiet decisions.
- 36,000 original 1m/five-symbol denominator cells: one candidate, 7,199 quiet
  and 28,800 explicitly not scheduled at the native cadence.
- No candidates at either original review cut; all ten cut/symbol cells quiet.
- Four retained base/stress × strict/proxy reports and account ledgers reconcile
  closed trades, fees, signed funding and net trading PnL. Strict modes have
  zero entries: the unchanged lifetime has no observed minute quote. Proxy
  modes have one simulated closed trade each, not an observed fill.

The [denominator receipt](../development/adaptive_replay/evidence/historical-pilot-2026-10-07/partial-price-sim/episode_a/denominator-receipt.json)
binds native tape SHA256
`d34f98002ea45082db0fcc4549af65b67a05ec5ad7675bbf83bdeafdeaa2e691`
and denominator SHA256
`8ba0542460631e761ed16fee222f68f0cf7dd673a51c2940636c69c00d38d9f6`.
Large JSONL tapes stay in the original runtime directory. The reports exclude
unavailable model/live-feed costs and do not demonstrate complete all-in returns.
No trading return was used to select parameters, cuts, strategy or limits.

Episode D has only **1,831 partial native rows**, spanning two symbols. It has
no denominator or economic reports. Observed partial rows are not extrapolated
to missing cells. Subsequent engineering changed the SIM module after the failed
attempt; the original sealed source receipt is retained, not relabelled current.

## Fixed twenty-cut audit: complete, no review candidates

A separate create-only protocol was sealed before evaluating only the original
review cuts. It has a 120-second bound, no economic replay and no full-window
retry/resume. Its installed-wheel attempt at
`D:\Kairos\runtime\historical-pilot-cut-audit-20261007-a` completed in
**19.375 seconds** with `TWENTY_CUT_AUDIT_COMPLETED_NOT_MATCHED_AB`.

The [actual result](../development/adaptive_replay/evidence/historical-pilot-2026-10-07/cut-audit/result.json)
retains exactly twenty unique cells: BTC/ETH/SOL/BNB/XRP at May 19, 2021
00:00Z/08:00Z and January 9, 2024 21:15Z/21:30Z. Every native decision uses
3,240 closed one-minute bars ending at cut minus one millisecond. All twenty
statuses are `NO_INTENT`, all intents and model decisions are null, and
`candidate_count=0`. Recorded reasons are crash protection, unfinished setup,
or uncertain regime/post-shock cooldown; they are not invented LLM vetoes.

Independent read-only review checked exact roster/order/uniqueness, anchors,
protocol digest, sealed-before/result source equality and all 34 installed
replay-module digests. Other original cells are explicitly
`NOT_EVALUATED_NOT_IMPUTED_QUIET`. Economic results/review arms remain null.
The successful small audit does not turn the separate failed full SIM into a
completed run or prove performance of the combined market/news/LLM system.

## Software verification and remaining prerequisite

The fixed-cut mode adds regression coverage for sealed-before generation,
exact anchors, no economics/full-tape execution, source/cache mutation,
cancellation, deadline, final source-hashing overrun and create-only outputs.
Independent source review identified the final-hashing deadline gap; it was
fixed before this audit, with a fake-clock regression test.

Installed non-editable wheels, tested from outside the checkout with
`--import-mode=importlib`, passed **647 tests and two existing Windows symlink
privilege skips** on both Python 3.11 (73.37s) and 3.14 (76.86s). Ruff lint/format,
locked dependencies, wheel/sdist build, static meta checks and Markdown links
passed. No source, market or model test was skipped to obtain this result.

All production source admissions remain separate. Exact historical NEWS versions
and bounded coverage are still unadmitted; CPI vintage semantics alone do not
supply them. Therefore paid matched A/B was **not executed**, no production
pilot ledger was initialized, and actual provider spend remains **USD 0**.
No model response, zero model-arm return or combined-system profitability is
imputed. Owner permission cannot replace missing source evidence.

Small public receipts/reports/ledgers are copied byte-for-byte into
[the retained evidence directory](../development/adaptive_replay/evidence/historical-pilot-2026-10-07/checksums.json);
the signed commit and scoped Git `-text` rule preserve these captured bytes.
