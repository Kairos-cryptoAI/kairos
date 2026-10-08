# Offline native book bytes to research BBO binding

Date: 2026-10-09 Europe/Moscow. Additive engineering after
[quote/fill feasibility](QUOTE-FILL-FEASIBILITY-2026-10-09.md); not a strategy
selection, historical economics/model run, campaign enrollment or trading gate.

## Implemented scope

`development/adaptive_replay/adaptive_replay/native_book_capture.py` accepts
only exact typed `RecordedTopNBookFrameV2`, supplied offline by its caller.
It freshly reconstructs the native contract and rechecks original UTF-8 text,
raw SHA-256 and canonical frame identity. Text is bounded to 32,768 bytes.
Pydantic copied/constructed objects are not trusted just because of their type.

The converter supports two explicitly selected combined-stream profiles for
`<lowercase-symbol>@depth10@100ms`, not raw/diff streams or arbitrary depths:

- Legacy fields: `e`, `E`, `T`, `s`, `U`, `u`, `pu`, `b`, `a`.
- Migrated fields: exactly those plus `st=1` (UM) and `ps` matching `s`.

The format distinction follows the
[official Binance UM partial-depth reference](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/public#partial-book-depth-streams).
It is not proof of migration dates, provider identity or historical capture.
The documentation's incomplete one-element example levels are not treated as
quantity evidence: each supplied level must contain both price and quantity.
No missing value is inferred. Future unknown fields/formats fail closed.

Strict parsing rejects duplicate/unknown/missing keys, BOM, invalid UTF-8/JSON,
coercion, nonfinite values, malformed levels, locked/crossed books and reordered
or duplicate levels. Every original level (not only top of book), base-asset
quantity, symbol, event clock `E` and final update ID `u` must match the retained
native fields. There must be 1..10 levels per side in their original order.
Positive decimal strings must preserve their exact decimal value through the
native float contract's decimal round trip; unsafe precision loss is refused.
Update IDs are bounded integers; `U<=u`, `pu<u` and `T<=E` are required.
Original event, receive and persistence clocks remain `E<=received<=persisted`.
No new capture time or timestamp backdating is introduced.

`NativeBookCapture` retains the original V2 frame separately from the generated
`BboCapture`. Its receipt binds original vendor payload hash, native frame hash,
conversion/policy hash and derived research capture hash. Generated research
JSON is explicitly **not** the original exchange message. The derived quote's
source ID is `native-book:<policy-hash>`, so different profile/conversion/TTL,
human source labels or evidence classes cannot silently share a hypothesis
source identity. A future hypothesis must freeze that exact source identity.
The generic BBO alone does not retain the native receipt or original raw text;
those are not added as columns to the immutable hypothesis journal. An external
source-admission path must independently retain and accept the original frames
and binding receipts. A source label/hash by itself is not proof of native origin.
The TTL is 1..5000 ms and remains event-anchored; delayed persistence cannot
refresh freshness. Both evidence classes remain caller-attested, not verified.

`audit_book_prefix` accepts an immutable tuple of 1..512 supplied frames, from
sequence 1 through one caller-pinned expected head. It checks every frame,
consecutive global sequence and predecessor hash, exact tape/epoch identity,
nonregressing persistence times and per-symbol update/event/receive order.
Nothing persisted after the as-of boundary enters. Barriers, missing roots,
selected subsequences, duplicate delivery and epoch stitching are refused,
not repaired. Receipts retain counts for all five symbols, including zeros.

This is **structural recorded-prefix consistency only**. A caller-pinned head
is not an externally signed anchor. The partial-stream `pu` is retained but not
repurposed into a diff-depth reconstruction proof. Hashes, even with all five
symbols present, cannot prove that the recorder dropped no upstream messages,
that receive clocks are authenticated, or that an episode's source denominator
is complete. No continuous market-coverage or fill authority is granted.

## Preserved boundary and real-source gap

The existing Quant Scouts recorder currently constructs V1, which retains a raw
hash but no raw text. It is neither upgraded nor silently stitched to supplied
bytes. V1, summarized MarketSnapshot, candles, price SIM, aggTrades and prints
cannot enter this converter as a historical bid/ask source. A bounded read-only
inventory of the existing named historical-pilot/SIM fixture/capture locations
found no retained actual causal V2 quote corpus suitable for this adapter.
This is not an exhaustive inventory of the computer or a claim that such data
cannot be obtained. No feed/download/recording process is started here.

Old v1/v2 scenarios, journal, quote parser and fill assessment, native contracts,
dependency pins/locks, release manifest, Trial 15/V4/V5 plans/ledgers/results
remain unchanged. As before, adding an installed research module intentionally
changes future journal source binding. Old sealed journals are not resealed,
migrated, deleted, adopted or rescued. These checks introduce no CLI, publisher,
socket, database recovery, Portfolio.admit, sizing, order or execution ledger.

All success is engineering-only with authority `NONE`. Separate independent
source/clock/continuous coverage acceptance, sealed execution costs/roster and
complete-system matched evaluation remain required before a new economic/model
test. No paid APIs, EVEDEX/canary/LIVE, Docker PAPER, primary database/leases or
guarded recovery are touched. Risk ceilings remain 0.25% per trade and 1%
aggregate. `TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`,
`ALPHA_READY=false`, `LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`.

## Verification

Only synthetic offline fixtures: malformed input, raw/native mismatches,
profile/source isolation, precision loss, clock/depth/capacity boundaries,
complete recorded prefix checks and a LONG/SHORT raw-native-to-journal-to-fill
feasibility path. Real market provenance, continuous source availability,
venue execution and economic performance are not tested or claimed.
Fresh non-editable build environments are retained separately in
`D:\Kairos\runtime\native-book-admission-build-20261009`. All 103 new cases passed
in each Python 3.11.15/3.14.7 installed-wheel environment with warnings treated
as errors. This includes explicit malformed native value-object rejection,
not implicit serializer repair or warning output. Both installed module byte
hashes match checkout:
`103dca758236454f2b829ef2b004db72365d9d7453778825f4b17dbea5514f08`.
Ruff lint/format checks (123 files), unchanged lock verification, fresh final
wheel/sdist build, Meta static/local Markdown/checkout regression and git diff
checks passed. Full installed-wheel regressions passed on Python 3.11 and 3.14:
1,240 passed and the two existing platform symlink-fixture skips in each, with
no new skips. Four final added tail-level mismatch cases then passed as part of
the full 103-case new-module checks in each environment. Previously receipted
scenario/v2/journal/quote/fill source byte hashes remain unchanged. Commit/CI
identities are recorded separately after the complete revision passes.
