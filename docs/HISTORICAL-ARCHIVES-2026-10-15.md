# Historical archive acquisition — 2026-10-15

## Outcome and owner decision

**Scoped source acquisition is verified; the strict historical native SIM is
not executed or admitted.** The owner explicitly selected strict native SIM
instead of substituting the existing modeled OHLC fill path. No purchase,
invoice, subscription, account creation or new paid model call was made.

The four original UTC windows remain November 7–10, 2021; February 5–8,
May 9–12 and June 13–16, 2022, end exclusive, for BTC/ETH/SOL/BNB/XRP USDT
perpetuals. The same twelve candidates remain fixed. The new NEWS acquisition
covers their May/June cuts, not every minute of all four windows. No new
strategy, evaluator, episode, model comparison or trading authority is added.

[Machine-readable acquisition receipt](../reports/historical-archives/2026-10-15/source-acquisition.json)
binds the actual captures, per-file hashes, candidate schedules and checks.
Original raw bodies and task-scoped validation scripts remain under
`D:\Kairos\runtime\strict-history-20261015`; they are not copied into Git.

## What was actually obtained

- **GDELT English GKG:** all 29 predeclared quarter-hour objects, 183,172,605
  compressed bytes, 44,890 records. All rows have the expected 27 fields and
  batch identity; all have an archived title. The fixed title keyword filter
  retains 255 records. ZIP CRC, storage MD5/ETag and retained SHA-256 checks pass.
  Each candidate has its three scheduled objects; their Last-Modified bounds
  precede its cut. Before/after source signatures are identical.
- **ALFRED CPIAUCSL:** 16 historical vintage columns, 21 contiguous observation
  months from September 2020 through May 2022, 277 nonempty cells. Units remain
  the seasonally adjusted index, 1982–1984=100, not year-on-year inflation.
  Missing future observations remain missing, never forward-filled or zeroed.
  Raw ZIP SHA-256 is
  `b08f6255180d30187c30603158d3f1585ab4be2ff271b6697516fd27907a2f2e`.
- **GDELT GQG sample:** a distinct May 9, 2022 14:16 file contains 434 archived
  quotation records. Its Last-Modified is 14:18:07 UTC, before the 14:19:59.999
  candidate cut. The absent 14:15 file and denied anonymous bucket listings
  are retained as failures/unknowns, not evidence of an empty news period.

GKG preserves the archived headline, not the complete article or the exact
historical DOC API query result. The [GDELT title definition](https://blog.gdeltproject.org/gkg-2-0-now-includes-page-titles/)
and [15-minute update definition](https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/)
support this narrower scope. The [GQG definition](https://blog.gdeltproject.org/announcing-the-global-quotation-graph/)
defines its date as GDELT observation and documents heartbeat gaps. Neither
dataset proves completeness of every configured RSS/X/news source or a
historical Kairos receipt. GCS generation identifiers are retained as opaque
version identifiers, not interpreted as an authoritative timestamp.

[ALFRED vintage semantics](https://alfred.stlouisfed.org/help/downloaddata)
support historical revisions at date granularity. The download is not an
intraday release-time record. The same-day May 11 column must not be silently
backdated to a pre-release cut. CPI alone is not the native StrategicAllocation
contract, and NEWS text alone is not a native SentimentSignal.

## Existing source gate, without paid calls

The existing `adaptive_replay.historical_context` contract accepts the 255
individually witnessed NEWS versions with their retained archive references.
Coverage remains explicitly UNKNOWN: no checksum or complete ZIP is promoted
into proof of all configured feed coverage. Date-granularity macro cells are
not invented as intraday releases.

Across twelve fixed cuts and all five symbols, **60 source-gate checks retain
UNAVAILABLE**, with no source content dispatched to a model. Six additional
offline checks pass: canonical archive round trip, changed-byte refusal,
future-version refusal, refusal to promote UNKNOWN without proof, complete
60-check coverage, and zero provider/execution invocation. This is expected
fail-closed behavior, not a full-system economic result or zero return.

## Strict depth archive: actual pre-purchase check

Local OHLCV/funding archives do not contain the historical native top-N tape.
Executed aggregate trades cannot supply resting bid/ask depth. Four representative
public Binance bookTicker objects returned 404; this is not a global absence proof.
Native SIM also needs a causal MarketSnapshot, original sequence evidence and
honest source/import/persistence clock domains. No clocks or book levels were
fabricated to pass those contracts.

Tardis is the best documented raw-format candidate among the reviewed suppliers,
not an accepted input or a claim of the cheapest market-wide offer. Its
[public exchange metadata](https://api.tardis.dev/v1/exchanges/binance-futures)
lists all five requested perpetuals as available before the earliest window.
Nominal availability does not prove uninterrupted symbol/channel coverage.

One explicitly free BTCUSDT minute from May 1, 2022 was downloaded **outside the
test windows for schema qualification only**, using the documented
[first-day free access](https://docs.tardis.dev/faq/billing-and-subscriptions).
It contains one REST-generated snapshot and 1,565 native depth messages with
collector receive clocks and Binance `U/u/pu`. Reconstructing the snapshot plus
diffs applies 1,560 contiguous events and skips five older buffered events;
there are zero sequence gaps, collector clock regressions or exchange clocks
after receipt. Every applied top-10 view passes the existing Quant normalizer.
There was no native tape admission, durable import, SIM fill, database mutation
or replacement of a frozen target window.

The [Binance reconstruction rules](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/How-to-manage-a-local-order-book-correctly)
and [Tardis Binance details](https://docs.tardis.dev/historical-data-details/binance-futures)
define the relevant source protocol. Generated REST snapshots must keep that
origin; collector receipt time is not proof of historical Kairos persistence.

## Price and approval boundary

As checked on October 15, 2026, [Tardis Perpetuals pricing](https://tardis.dev/)
lists Professional at USD 1,000/month. Its
[billing terms](https://docs.tardis.dev/faq/billing-and-subscriptions) distinguish
the following:

- Academic/Solo are CSV-only; raw replay requires Professional or Business.
- Monthly access reaches four months; ordinary yearly access reaches four years,
  which excludes every fixed window as of today.
- Yearly invoicing adds twelve months of history. Professional with that method
  therefore appears to be the minimum advertised raw-access configuration that
  reaches these dates: **USD 12,000/year before applicable tax**, calculated from
  the listed monthly rate. This is not a personalized invoice or purchase offer.
- The supplier expressly does not sell individual date ranges/custom exports,
  and does not prepare quotation documents. No such arrangement is assumed.

**Do not buy this subscription merely to unblock this test.** First agree the
owner's archive budget, exact entitlement start date, permitted research use,
actual required data volume, symbol/channel completeness and import feasibility.
CoinAPI/Kaiko were also reviewed, but their public descriptions did not establish
the same required 2021–22 native sequence/raw-clock evidence; no substitute was
declared qualified or purchased. A sufficiently complete existing licensed tape
would also be acceptable without a new subscription.

## Remaining work, not relabeled as completion

1. Admit a complete, explicitly bounded NEWS source roster and correct macro
   release/version clocks. This is not a claim that all world news is knowable.
2. Obtain and qualify the required historical depth/derivatives inputs within an
   approved archive budget, including starting snapshots, sequence continuity,
   raw bytes and source clocks. Do not invent OI/liquidation values where absent.
3. Bind accepted raw inputs through the existing Text/Macro/Quant/Router/review/
   Risk/native SIM components, preserving simulated logical time separately from
   real provider observation and import time. The existing no-network fixture
   and frozen campaign guards remain intact.
4. Only then seal and execute the bounded historical run within the unchanged
   cumulative provider budget, and report actual full-path results and limits.

Primary/legacy/R7 databases and queues, Trial 15/V2/V4/V5, frozen strategy and
prior failed/partial receipts remain untouched. Trading is not started.
`PAPER_QUALIFIED=false`, `ALPHA_READY=false`, `LIVE_READY=false`,
`STRATEGY_POLICY=REJECT_ALL`; all other readiness markers remain unchanged.
