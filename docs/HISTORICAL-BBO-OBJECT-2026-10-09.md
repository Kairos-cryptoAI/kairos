# Original historical top-of-book object — October 9, 2026

## Actual source progress

Public Binance USD-M `bookTicker` objects exist for all five required symbols
on January 8, 2024. The bounded discovery checked object metadata without
downloading their bodies. The observed compressed sizes are BTC 206,972,981,
ETH 201,456,380, SOL 133,780,447, BNB 67,674,558 and XRP 56,165,831 bytes.
Exact daily checksum paths for all five symbols on May 17, 2021 returned 404.
This does not prove absence at other paths, vendors or dates.

The discovery performed 56 requests with no retries/redirects or ZIP downloads.
Its full printed fifty-path roster was truncated by the tool and was not saved;
only the fully observed five May-17 failures, five Jan-8 ZIP metadata results
and one BTC checksum body are credited. Other statuses remain unknown, rather
than being reconstructed from the intended loop.

Two separate bounded HTTP range requests inspected the BTC ZIP structure and
first CSV rows (196,629 bytes total). They showed the original seven columns:
update ID, best bid price/quantity, best ask price/quantity, transaction time and
event time. This range-only inspection did not establish its checksum or CRC.

## Complete BTC object retained and profiled

One create-only acquisition then retained the complete BTC January-8 ZIP and
its original public checksum body, using exactly two GET requests and no retry.
It finished at `2026-10-09T03:29:17.3306824Z`. Its full 206,972,981 bytes match
the independently observed public SHA-256:

`87716a48513fd29a49d32dab5b78ab0788dd58259a307bf5224f9a4a4c59b4ec`

A one-worker streaming profile completed all **19,245,805 rows** in 91.328
seconds without extracting the 1,811,753,894-byte CSV to another file. Reaching
the ZIP member's EOF validates its complete CRC. Uncompressed SHA-256 is
`799529f78e6d4463e9af24bd6e93a8ac13eb93044ac6cbbb88eecaf1537f6a05`.
The full compressed object was hashed again after profiling and remains equal
to the public checksum.

Every row passed the declared seven-column/numeric/finite/price/quantity,
strictly increasing update-ID, nonregressing transaction/event-clock,
event-not-before-transaction and transaction-day checks. No crossed/locked or
zero-top-quantity row was observed. These are the implemented checks, not a
claim that every possible source defect is excluded. Transaction timestamps
span `1704672000006` to `1704758399998`; event timestamps span `1704672000012`
to `1704758400005`. The last event crosses the day boundary by five milliseconds
and must remain retained. Largest adjacent event gap is 1,776 milliseconds;
this is not an independently authenticated lossless exchange-feed assertion.

Native originals and generated receipts are retained under
`D:\Kairos\runtime\historical-bbo-object-20261009-a`. The
[portable receipt](receipts/historical-bbo-object-20261009.json) binds their
hashes and the exact inspection/acquisition/profile scripts. No original body
or failed evidence was rewritten. Large market archives are not committed to
Git.

## Required next integration, not false completion

This is one symbol/day of the fixed January window, not accepted complete
five-symbol/five-day BBO, not level-2 depth and not EVEDEX liquidity. The archive
contains exchange transaction/event clocks, not historical local receiving
clocks. Modern acquisition times are not backdated. NEWS/MACRO, source coverage,
provider costs and source/policy admission remain separate requirements.

The actual row count exceeds the unfinished horizon's 900,000-input tuple cap;
its uncompressed bytes exceed the 512-MiB source profile. Dense financial MARK
history also exceeds the existing two-MiB opaque account codec. Increasing one
limit or sampling quote rows is not a valid full fix. The next path requires a
shared immutable on-disk source stream, bounded operational state and complete
indexed native event retention committed atomically with financial state.
Original reservations, liquidity use, exposure/funding history, costs, refusals,
all four accounts and checkpoint restart semantics must survive that relocation.

No paid model request, winner, blind credit, primary recovery, service start or
trade occurred. Full points 1–3 remain open. Readiness remains false and policy
`REJECT_ALL`.

Public dataset checksum/publication/update rules:
[Binance Public Data](https://github.com/binance/binance-public-data/blob/master/README.md).
