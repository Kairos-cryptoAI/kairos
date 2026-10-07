# Native adaptive intraday source-only protocol — 2026-10-07

## Frozen scope, not another strategy or economic retry

The [separate source plan](../development/adaptive_replay/intraday-source-plan.json)
asks one narrow question: does the published transaction archive contain a
recorded price after assumed completion and before the unchanged native expiry
for **every one of the twelve original adaptive candidates**? It is not a
new generator, threshold search, execution evaluator, return comparison,
scientific campaign enrollment or retry of a frozen pipeline.

All four original development decision tapes remain immutable and byte-bound:
17,280 complete slots, 17,268 `NO_INTENT` and twelve `INTENT` outcomes.
Two windows have no candidates and are retained, not removed. The tape roster
preserves original slot/context hashes and native intent IDs, including the
volume-bearing provenance; it does not reuse the slow-reference `PRICE_ONLY`
zero projection or freshly qualify the original context inputs. No economic
result file, protected Trial 15/V4/V5 ledger or source archive is used to choose
signals or change their configuration.

## Separate clocks and observation fidelity

The original decision is the last closed minute's final millisecond.
Eligibility is `decision + 1ms`; expiry is `decision + 60,000ms`.
The separately fixed completion assumption is `decision + 100ms`, with zero
additional transport delay assumed. Thus modeled arrival is **eligibility +
99ms**, not the minute open, a measured receipt time or a future minute.
Neither time is rounded backwards and the original expiry is never extended.

The scanner searches the inclusive arrival/expiry interval in aggregate-ID
order. A strict predecessor **before** arrival and successor **after** expiry
must bracket the whole interval. An aggregate-ID gap envelope that intersects
the interval taints it, including a gap beginning inside it and ending after
expiry. Same-time events retain archive ID ordering; missing raw sub-events
receive no invented timestamps.

- `RECORDED_PRINT_REFERENCE`: first recorded aggregate transaction inside the
  assumed lifetime, with bracketing and no intersecting aggregate-ID gap.
- `NO_RECORDED_PRINT_IN_ASSUMED_WINDOW`: the bracketed archive interval has no
  recorded transaction; this does not prove that no executable quote existed.
- `GAP_TAINTED`: an aggregate-ID gap overlaps the interval; missing events are
  neither repaired nor allocated to guessed timestamps.
- `BOUNDARY_UNPROVEN`: strict boundary witnesses are absent.
- `EXPIRED_BEFORE_ARRIVAL`: modeled completion/transport is already too late.

Prices/quantities in these witnesses are completed **market transactions**, not
bid/ask quotes, available depth, our order acknowledgements, partial fills or
position protections. Historical transaction time is not local receive time.
Recorded trade size and subsequent volume do not prove executable capacity.
The read-only local inventory found aggTrades but no matching BBO/raw-trade
archives or parser. Metadata HEAD checks of the nine matching public daily
bookTicker paths returned 404, while the nine aggTrades paths returned 200;
this does not establish that historical BBO is unavailable everywhere.

The [official public-data schema](https://github.com/binance/binance-public-data)
defines seven USD-M aggTrades fields and archive SHA256 sidecars. The
[official market-data contract](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)
separates aggregate transactions from order-book ticker quotes and excludes
insurance/ADL transactions from market-trade responses. Raw-ID gaps therefore
remain reported as unknown/excluded, not automatically missing market events.
These present-day semantics do not independently certify the historical archive.

## One bounded source-only attempt

The fixed roster is nine symbol/day ZIPs: BTC/ETH/BNB/XRP on May 9, 2022;
ETH on May 11; SOL/BNB on June 13; BTC/ETH on June 14. This is the entire
candidate-derived roster, not cherry-picked dates or all annual history.
Fetch only those official public ZIPs and their CHECKSUMs into a fresh direct
child of the workspace runtime directory: eighteen fixed GETs, one attempt
each, TLS verification, no redirects/retries/credentials, and no cache writes.
No archive of the stopped quarter-hour contour is opened or repaired.

Limits: one worker, 900 seconds total, 96 MiB compressed/768 MiB expanded and
five million rows per file, 512 MiB compressed/thirty million rows total,
twenty-second HTTP timeout, 512-byte CHECKSUM and 512-character physical line.
At least one GiB free disk is required. Whole CSVs are streamed with bounded
memory; no decompressed archive is extracted to disk.

The scanner verifies exact file/member identity, SHA256, complete ZIP CRC,
schema, finite positive Decimal prices/quantity, UTC milliseconds within the
day, strict aggregate-ID order, nondecreasing timestamps and nonoverlapping
raw-ID ranges. It never sorts, deduplicates, fabricates ticks or interpolates.
Both scanner hashes are compared with the **actual official GET witnesses**;
all eighteen downloaded files are rehashed before completion. Original plan,
native tapes and installed pinned source are checked before/after. Mutating
ZIP and CHECKSUM together cannot replace the recorded GET identity silently.

Checksum/CRC/internal consistency prove the downloaded published bytes, not
independent completeness of the market. An integrity, network or resource
failure retains partial receipts, reports `FAILED_CLOSED` and never retries in
place or records a negative strategy-performance result.

## Engineering and completion rule

The additive [runner](../development/adaptive_replay/adaptive_replay/intraday_audit.py)
and [scanner](../development/adaptive_replay/adaptive_replay/intraday_references.py)
do not call an economic runner, generator, provider, database or exchange API.
Synthetic offline tests cover native clocks, exact expiry, same-time order,
whole-window gaps, strict boundaries, byte/row/deadline guards, CRC corruption,
official GET substitution, late file changes, original-plan changes and
create-only output. Tests do not download or inspect historical economics.
Pre-run engineering: all **375** installed-wheel tests pass on Python 3.11
(53.54 seconds) and Python 3.14 (50.57 seconds); Ruff and meta static/local
Markdown-link checks pass. An input-only preflight validates the original
17,280 tape slots/twelve IDs and the single assumed +99ms eligibility offset.
The source implementation/protocol is GPG-signed on main and its exact
Windows/Linux CI must pass **before** the bounded public-source attempt.

`COMPLETED` means that the source audit executed, not that all requests passed.
Only twelve untainted bracketed references would close the narrow recorded
price-reference prerequisite for this reused exposed sample. No statistical
power, strategy winner, economic pass or observed-fill credit follows.
Executable quotes, conditional lifecycle economics and eventual venue-qualified
fills remain distinct unresolved requirements. There are no exits, positions,
fees/funding/PnL calculations, real orders or paid model/feed calls in this task.
All four readiness flags stay false and `STRATEGY_POLICY=REJECT_ALL`.

The original Trial 15/V4/V5/frozen evaluators and evidence stay unchanged;
primary recovery/consumers, system integration, UI and EVEDEX remain outside
this strategy-only scope. The signed source-only attempt is reported separately
when completed; it cannot nominate the adaptive challenger automatically.
