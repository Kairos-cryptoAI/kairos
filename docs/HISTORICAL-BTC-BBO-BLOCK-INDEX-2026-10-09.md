# Complete original BTC-day block index — October 9, 2026

The create-only block derivation completed for all **19,245,805 original
BTCUSDT bookTicker rows on January 8, 2024**, without resampling. The bounded
worker returned exit zero in 1,338.203 seconds and measured a peak Windows
working set of 62,427,136 bytes. Its 27,672 blocks occupy 15,060,526 index bytes;
the retained source still contains the original 1,811,753,894 CSV bytes in
27 segments.

The [portable receipt](receipts/historical-btc-bbo-block-index-20261009.json)
binds the original ZIP/CSV, source manifest, every tool module, worker,
preregistered intent, native result, index manifest and blocks file by SHA-256.
The original complete-day receipt remains
[unchanged](HISTORICAL-BBO-FIVE-SYMBOLS-2026-10-09.md). Native files are preserved
outside Git under `D:\Kairos\runtime\original-btc-bookticker-batch-index-20261009-i`.

The derivation read and parsed the entire original source, reopened it around
the build, and verified the generated index. The declared profile allows
64-KiB blocks, at most 100,000 blocks and a 64-MiB index, with 500-row/2-MiB
consumer batches. The whole attempt retained its 2,700-second bound; the
builder received the remaining 2,468 seconds. Original source bytes were not
rewritten. The final exchange event at `1704758400005`, five milliseconds
past the UTC day boundary, was retained rather than clipped.

## Exactly what this establishes

All original BTC-day rows are indexed for bounded streaming. The subsequent
500-row first-batch read and exact last-row lookup are functional inspections,
not a claim that financial accounts processed the entire day. The tool used a
separately byte-bound import namespace; this is not an installed-wheel release
gate for the unfinished current implementation.

For that functional inspection only, exchange event `E` was selected with
explicit modeled feed/processing delays of 100/100 ms. These are declared
reference assumptions, **not historical receiving clocks or the frozen latency
policy of a financial campaign**. Historical received-at remains null.

This result supplies one original-source indexing step. It does not complete
the other symbols/days, May-2021 sources, NEWS/MACRO/funding settlement,
five-day non-resetting financial lifecycle or fixed four-arm economic
comparison. No fill, winner, model request, blind enrollment, runtime recovery,
service start or trading authority follows. All four readiness flags remain
false and policy remains `REJECT_ALL`.
