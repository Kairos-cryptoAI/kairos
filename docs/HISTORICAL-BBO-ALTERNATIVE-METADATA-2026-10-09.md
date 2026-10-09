# Fixed-window archive alternative: metadata only — October 9, 2026

One unauthenticated public GET of the
[Tardis Binance-futures exchange metadata](https://api.tardis.dev/v1/exchanges/binance-futures)
returned HTTP 200 and 384,303 original bytes. The predeclared request had a
1 MiB body limit, a thirty-second hard wall and no retry or redirect. The
request intent, raw headers, complete body and separate offline verification
are retained and hash-bound by the
[portable receipt](receipts/historical-bbo-alternative-metadata-20261009.json).
No historical dataset, authentication, account creation, trial, purchase or
provider credential was used.

The original metadata advertises `book_ticker`, `incremental_book_L2` and
`derivative_ticker` for BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT and XRPUSDT. Each
instrument's advertised availability spans the unchanged May 17–22, 2021
and January 8–13, 2024 windows. All five metadata entries end at
2026-10-09 00:00 UTC; their starts range from November 2019 to September 2020.
The eighteen returned incident reports contain no overlapping interval for
either fixed window. **An empty overlap in this metadata is not proof of
complete or incident-free historical data.** No original historical messages
have been downloaded, verified or admitted by this observation.

The [official collection description](https://docs.tardis.dev/historical-data-details/binance-futures)
describes native exchange messages and local collection timestamps, including
bookTicker and markPrice channels. Its keyless samples cover the first day of
a month, not the fixed May 17–22 roster. A generated REST depth snapshot is not
an original WebSocket snapshot; downstream interpretation must preserve the
actual channel, clocks, original raw bytes and snapshot/update continuity.

The [current access FAQ](https://docs.tardis.dev/faq/billing-and-subscriptions)
says it does not sell one-off fixed-date exports. Standard Academic/Solo/Pro
annual subscriptions cover four years; the May 2021 window is older than that
on the observation date. Business annual access is described as all available
history. A free trial offers limited history without payment details or an
automatic paid conversion, but its coverage of these exact dates is unknown.
No price, plan or license has been accepted for Kairos. Existing LLM/feed
budgets do not authorize a data subscription.

This is a verified discovery lead, not a replacement of the fixed dates, a
completed source gate, executable-book evidence, settlement-price proof or a
financial replay. Exact original fixed-window bodies, completeness, clock/
causality assumptions, access/license and accepted budget remain necessary.
May BBO and causal NEWS/MACRO remain open; the separate public Binance funding
response still lacks all eighteen required settlement prices. All readiness
remains false with `REJECT_ALL`.
