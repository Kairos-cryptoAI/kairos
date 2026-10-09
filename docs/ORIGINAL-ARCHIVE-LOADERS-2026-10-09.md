# Original archive loaders: installed engineering gate — 2026-10-09

Two separate research-only foundations now preserve original Binance monthly
funding records and lossless daily bookTicker bytes. They neither change the
frozen Backtest evaluator nor arm runtime, PAPER, EVEDEX or LIVE.

The bookTicker loader binds the original ZIP/checksum/member identity and raw
Decimal fields, supports bounded full-row block indexing and prefix/cursor
verification, and retains source rows without resampling. The funding loader
checks the whole monthly calendar against an explicitly declared entitlement
schedule and maximum calculation-time offset; it preserves original raw rows,
rates and archive/member/calendar hashes. Its delivery time is explicitly
modeled, not an invented historical local receiving clock. A rate is not a
settlement price or an executable quote.

The [portable engineering receipt](receipts/original-archive-loader-gates-20261009.json)
records an immutable 616-file snapshot of published main `0e8c7b5` plus exactly
these two modules and their two tests. The retained wheel has 72 adaptive Python
modules; every source, wheel and installed module byte matches, including
post-test source and installed-module verification. Other unpublished financial,
hypothesis, horizon and four-arm drafts are deliberately outside this gate.

| Full installed-wheel gate | Actual passed | Explicit skipped | Failed / errors |
| --- | ---: | ---: | ---: |
| Windows Python 3.11.15, isolated, warnings as errors | 1,737 | 5 | 0 / 0 |
| Windows Python 3.14.7, isolated, warnings as errors | 1,737 | 5 | 0 / 0 |

Each suite collected 1,742 cases. The five skips are unavailable Windows
symlink-fixture privileges, not unreported successes. Native XML records
433.307 and 351.369 seconds respectively. Ruff/format, frozen offline lock
verification and meta static/link checks pass. No dependency lock changed.
Earlier failed dependency installation diagnostics remain retained; subsequent
project-aware frozen installation uses the original lock's source overrides.
No hosted CI result is inherited from a preceding revision.

This gate does not prove the full historical financial task. The fixed May
original BBO gap and causal NEWS/MACRO admission remain open. Full January
archive profiles retain their separate source-only receipts. Original funding
settlement prices, durable producer-to-account entry, complete lossless
five-symbol/five-day non-resetting financial accounts and fixed four-arm
economics need their own accepted originals, integrations and actual runs.
All four readiness flags remain false with `REJECT_ALL`.
