# Complete original BBO objects for one fixed day — October 9, 2026

All five original Binance USD-M `bookTicker` archives for **January 8, 2024**
are retained and fully profiled. This advances original-source collection;
it does not close the fixed five-day source requirement.

| Symbol | Original rows | Compressed bytes | Original CSV bytes |
| --- | ---: | ---: | ---: |
| BTCUSDT | 19,245,805 | 206,972,981 | 1,811,753,894 |
| ETHUSDT | 18,468,747 | 201,456,380 | 1,726,038,635 |
| SOLUSDT | 12,152,615 | 133,780,447 | 1,083,546,700 |
| BNBUSDT | 5,681,616 | 67,674,558 | 517,131,353 |
| XRPUSDT | 4,089,964 | 56,165,831 | 384,288,600 |
| Total | **59,638,747** | **666,050,197** | **5,522,759,182** |

The [earlier BTC receipt](HISTORICAL-BBO-OBJECT-2026-10-09.md) remains unchanged.
A separate create-only acquisition retained the four peers in eight GET
requests, without retry or redirect. Each complete archive matches its retained
public checksum. One worker then examined every row sequentially; both native
processes terminated with exit zero. Reaching each member's EOF validated its
CRC, and the compressed SHA-256 remained equal before and after profiling.
Every declared numeric/schema/book/ID/clock/day check found zero anomalies;
this does not assert that every possible source defect has been excluded.

The [portable five-symbol receipt](receipts/historical-bbo-jan8-five-symbols-20261009.json)
binds each original ZIP/CSV hash, totals, acquisition/profile receipts and exact
script bytes. Original archives and native reports stay outside Git under
`D:\Kairos\runtime\historical-bbo-object-20261009-a` and
`D:\Kairos\runtime\historical-bbo-jan8-peers-20261009-a`.

## Admission remains separate

These are complete original **objects for one day**, not authenticated lossless
exchange-feed coverage, historical local receiving clocks, level-2 depth or
EVEDEX liquidity. Exchange transaction/event clocks are retained as published;
modern download clocks are never backdated. The BTC final event extending five
milliseconds past the UTC day remains in its original evidence.

The other days, the May-2021 scenario, causal NEWS/MACRO/funding, full financial
stream capacity and the continuous four-arm comparison remain unaccepted. No
economic result, winner, blind enrollment, model request, runtime recovery,
service start or trade follows. All four readiness flags remain false and
policy remains `REJECT_ALL`.
