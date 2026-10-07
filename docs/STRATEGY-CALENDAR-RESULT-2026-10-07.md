# Calendar reference comparison: input-blocked, 2026-10-07

## Outcome and exact boundary

The [preregistered calendar protocol](STRATEGY-CALENDAR-PROTOCOL-2026-10-07.md)
was signed and pushed in `99802ff6148289638858a4b0709d92a34f4e93a3`
before execution. All 277 installed-wheel tests passed on local Python 3.11 and
3.14; the exact revision passed
[all four Windows/Linux CI jobs](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37565297135),
[static validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37565297173)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37565296685).
The current-release check verified all 14 clean `main` repositories.

After retaining the failure and complete input-only inventory, all 281
installed-wheel tests passed locally on both Python versions (40.85s/37.63s).
Four published-evidence tests bind all six retained files, reconcile monthly
row counts and prevent the input-blocked attempt becoming an economic result.
Style and static documentation/source-manifest validation also pass. These
are engineering checks, not restoration of missing market observations.

One cache-only process started at 2026-10-07 03:09:24.425983 UTC and stopped
after 58.156 seconds: `FAILED_CLOSED`, `ValueError`,
`incomplete verified FULL_KLINE span for SOLUSDT`. Failure occurred inside the
first year's input load, before native generation, tapes, accounts or economic
replay. Complete years: zero. Economic cells: zero. `result.json` is absent.
This is **unavailable annual evidence**, not negative strategy performance and
not the economic decision `NO_ECONOMIC_REFERENCE_WINNER`.

Byte-retained [failure](../development/adaptive_replay/evidence/calendar-2026-10-07/failure.json),
[source receipt](../development/adaptive_replay/evidence/calendar-2026-10-07/before.json)
and [sealed plan](../development/adaptive_replay/evidence/calendar-2026-10-07/sealed-calendar-plan.json)
preserve this attempt. No retry, partial-year winner or adjusted source set was
used. The independent annual ledger calculator was **not run**: there are no
annual ledgers to reconcile.
The exact plan and installed-source bindings were independently rechecked
after the input-only failure and remained unchanged.

## Exact observed SOL data gap

The separate [input-only diagnostic](../development/adaptive_replay/evidence/calendar-2026-10-07/sol-calendar-gap-diagnostic.json)
reused the installed strict loader without generators or economics. The
2022 scoring year plus 35-day prefix and three-day exit tail requires 580,320
minutes per symbol. SOL contains 573,120, with two gaps, zero quarantined
optional rows, exact outer boundaries and 15/15 cached SHA sidecars verified.

| Missing UTC interval, start inclusive / end exclusive | Missing minutes | Local archive |
| --- | ---: | --- |
| 2022-02-26 00:00 / 2022-03-01 00:00 | 4,320 | SOLUSDT-1m-2022-02.zip |
| 2022-04-01 00:00 / 2022-04-03 00:00 | 2,880 | SOLUSDT-1m-2022-04.zip |

The two archive hashes match their local sidecars. That confirms byte
consistency, not a complete calendar or independent authentication of the
exchange's historical data. Do not classify the missing candles as flat
markets, no-action decisions, losing trades or a proven exchange outage.

## Completed bounded input-only inventory

The separate [monthly coverage audit](../development/adaptive_replay/evidence/calendar-2026-10-07/calendar-input-audit.json)
completed all 255 requested files: November 2021--January 2026 inclusive,
five symbols, 51 months each. One worker took 165.406 seconds within its
180-second cooperative bound. There are no missing ZIPs or audit exceptions;
255/255 local checksum sidecars matched. `state=COMPLETED` means that the
inventory finished, **not** that its inputs passed: `coverage_complete=false`.

| Symbol | Monthly files checked | Absent minute rows | Invalid rows |
| --- | ---: | ---: | ---: |
| BTCUSDT | 51 | 0 | 0 |
| ETHUSDT | 51 | 0 | 0 |
| SOLUSDT | 51 | 7,200 | 0 |
| BNBUSDT | 51 | 0 | 0 |
| XRPUSDT | 51 | 7,200 | 1 |

XRP has the same two missing 2022 intervals as SOL. Its November 2023 archive
also has one row rejected by the installed FULL_KLINE validator: quote volume
is inconsistent with OHLC and base volume (CSV line 42,517). The resulting
clock gap lies between 2023-11-30 12:34 and 12:36 UTC. This invalid row is
counted separately, not reclassified as one of the 14,400 absent symbol-minutes.
Expected rows are 11,181,600; valid rows are 11,167,199, reconciling exactly
with 14,400 absent rows and one invalid row. These are input counts, not
executed trades or missing decision counts.

The [retained helper bytes](../development/adaptive_replay/evidence/calendar-2026-10-07/Inspect-CalendarInputs.py.txt)
reuse the pinned `audit_cached_archives` checks. The text suffix prevents
formatting the archived helper; its hash still matches the original runtime
script. It audited input fields, ZIP CRC, cached SHA and monthly chronology,
without a generator, funding-rate read, replay, retry or download. Monthly
edge absence and within-month gap counts are distinct: the monthly SOL gap
counter is zero even though its missing-minute count is nonzero. The exact
joined-span SOL diagnostic above detects two discontinuities.

## Strategy decision and remaining prerequisite

The [completed twelve-day paired result](STRATEGY-SELECTION-2026-10-07.md)
remains unchanged: nine/eight closes per cost scenario do not select a final
champion. The small shortlist stays provisional; the base is a mechanical
control, not a newly qualified winning strategy. Neither annual returns nor
nomination, CAGR, compound portfolio earnings or matched full-system alpha
exists from the failed calendar attempt.

Full-year selection needs a separately accepted complete historical source
set before a new explicitly agreed protocol. Preserve this failure and prior
exposure; never fill the missing minutes, exclude SOL, delete problematic
days or move to favorable years silently. Native event-driven adaptive
60-second entry observability also remains separate and unresolved.

The new fixed funding schedule loader and its synthetic integrity gates are
engineering work, not a completed annual economic experiment. Existing
right-tail/default strategies, evaluator, risk limits, frozen Trial 15/V4/V5
evidence and historical receipts are unchanged. No news/LLM/Macro/Router
integration, paid call, download, primary mutation, consumer start or trading
authority follows. All four readiness flags remain false and policy is
`REJECT_ALL`.
