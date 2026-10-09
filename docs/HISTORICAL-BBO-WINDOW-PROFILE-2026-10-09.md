# Complete original BBO window profile — October 9, 2026

All 25 retained original January 9–13, 2024 Binance USD-M bookTicker archives
completed their separately sealed full-row/CRC profile. The single sequential
worker returned exit zero after **4,099.031 seconds**, reading **394,149,722
rows** and **36,639,819,228 original CSV bytes**. Each complete ZIP member reached
EOF with its CRC validated, and every recorded anomaly counter is empty.

The [portable receipt](receipts/historical-bbo-jan9-13-full-profile-20261009.json)
binds all twenty-five object/profile SHA-256 identities, original CSV hashes,
exact row/byte counts, source clocks, worker, sealed plan, run intent and final
summary. Root independently compared every profile against the exact sealed
roster and final summary, recomputed retained receipt/worker hashes, and
reconciled all counts. The worker verified every original archive SHA-256 and
filesystem identity before and after the scan; raw originals remain unchanged.

| UTC transaction day | Five-symbol original rows |
| --- | ---: |
| 2024-01-09 | 65,672,514 |
| 2024-01-10 | 81,991,463 |
| 2024-01-11 | 89,688,805 |
| 2024-01-12 | 89,210,003 |
| 2024-01-13 | 67,586,937 |

Together with the separately verified [January 8 profiles](HISTORICAL-BBO-FIVE-SYMBOLS-2026-10-09.md),
the thirty original daily objects contain **453,788,469 rows**: the January
8–12 entry window contains **386,201,532**, and the January 13 exit-tail day
contains **67,586,937**. This arithmetic counts source rows, not orders, fills,
trades or financial-account events.

The fixed profile checks exact native header/seven columns, canonical ASCII
numeric fields, Decimal prices/quantities, positive unlocked books, nonzero
top quantities, strictly increasing update IDs, nonregressing transaction/event
times, transaction-day membership and event time not before transaction time.
Source event timestamps that cross UTC midnight are retained, not clipped.
The immutable plan keeps 900 seconds per object, 7,200 seconds overall,
one sequential worker and create-only stop-on-failure semantics.

These results establish integrity under those checks, **not** continuous feed
coverage, cross-day feed continuity, historical local receiving clocks,
level-2 depth, accepted NEWS/MACRO/funding or EVEDEX executable liquidity.
The [acquisition receipt](HISTORICAL-BBO-WINDOW-ACQUISITION-2026-10-09.md) remains
an unchanged object-only receipt; this later profile does not rewrite it.

Lossless block indexing/portfolio streaming, continuous non-resetting native
financial accounts and fixed four-arm economics still require their own actual
runs and gates. The fixed May 2021 original BBO source set remains unavailable
at the checked official URLs. No performance winner, model execution, blind
enrollment, recovery, runtime service start or trading permission follows.
All readiness flags remain false with `REJECT_ALL`.
