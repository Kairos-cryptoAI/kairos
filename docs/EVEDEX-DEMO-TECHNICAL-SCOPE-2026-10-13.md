# EVEDEX Demo: separate technical scope after support response

## Accepted support facts, not trading acceptance

Official EVEDEX Help 24/7 ticket **1013-20** received the owner's approved
public-only report on October 13. No account ID, wallet address, balance,
credential, private log or attachment was sent. The report explicitly treated
the earlier roughly 9% BTC spread as a dated observation; later GUI quotes had
narrowed. It did not claim that spread was a permanent venue state.

Daniel's subsequent response states that Demo supports three pairs. The
attached instrument picker identifies **BTCUSD, ETHUSD and 1000PEPEUSD**.
The reply also says Demo prices may differ from real prices and the environment
is intended for testing exchange tools. The local protected conversation proof
is in `D:/Kairos/runtime/evedex-demo-support-20261013`; its screenshots were not
uploaded to support or Git. A chat response does not explain ETH's earlier empty
REST book or establish ongoing liquidity, executable fills or account authority.

## Independent bounded public tool

`development/ops_alerts/evedex_demo_public_diagnostic.py` has a separate DEMO
origin, report schema, fixed three-symbol roster and dedicated evidence root.
It does not generalize Execution's DEV qualification origin or PAPER validators.
It makes at most **eleven anonymous GET attempts**, each reserved on disk before
the network call: matcher state, instruments, and default depth, best-only depth,
and recent trades for each supported Demo pair. There is no credential reader,
account endpoint, order/transfer method, wallet signer, database/queue client,
cross-venue comparison, background scheduler or automatic retry.

[Official public-data documentation](https://docs.evedex.com/developers/developers/public_exchange_data)
documents anonymous matcher/instrument/depth/recent-trade reads and the
`marketLevel=1` best-price query. The
[official REST gateway](https://github.com/evedex-official/exchange-api/blob/master/src/exchangeRestGateway.ts)
separates these public GETs from authenticated account and mutation methods.
No guessed candle endpoint is used. No fixed BTC rounding step is applied to
the much smaller PEPE price. Validated depth uses numeric extrema rather than
assuming the REST bid ladder is already in best-first order.

Default CLI invocation is plan-only. Execution requires the explicit
`--execute-public-demo-diagnostic` flag, verified GPG-signed `main==origin/main`,
exact committed source bytes, and an existing non-reparse evidence root.
A Moscow-calendar-day directory is an exclusive durable reservation; interrupted
or repeated same-day invocations cannot resume, overwrite or retry it. Redirects,
proxy forwarding, foreign paths, oversized responses and non-finite/duplicate
JSON are rejected. Only schema-validated numeric public depth DTOs are retained
raw; account data and arbitrary response text are never written or printed.

Prepare the dedicated evidence directory privately before the one authorized
invocation; do not mount it, credentials or Demo keys into PAPER services.
The report is under
`D:/Kairos/runtime/evedex-demo-public-diagnostic/YYYYMMDD/report.json`.
Empty/stale/crossed books remain explicit findings, not discarded denominators.
Serial requests are not simultaneous paired snapshots or a 24-hour window.

## Gates unchanged

Kairos still requires BTC/ETH/SOL/BNB/XRP on its separately approved venue route.
1000PEPE is a **Demo mechanics test instrument only**, not a substitute for one
of those five, a strategy candidate or an alpha/universe amendment. Neither
three-symbol Demo observations nor venue-synthetic prices can pass the existing
five-symbol availability/basis/spread/slippage, canary, soak or economic gates.

Until an official usable five-instrument route is accepted, that qualification
remains blocked. A later manual Demo order/signature would require a separately
bounded handoff and is not authorized by this anonymous public tool. No trading
is started here. All readiness remains false and policy remains `REJECT_ALL`.

## Later public snapshot — 17:44:06–17:44:47 UTC

The signed source `6c1af3fd9cceaf4b1dd99bcd79093ede129beaf3` completed its
one allowed daily diagnostic. All **11 GETs returned HTTP 200**, with zero
transport/schema errors. Matcher is `active`; all three selected instruments
are present, `trading=all`, `visibility=all`. Both default and best-only queries
returned two-sided, uncrossed, snapshot-fresh depth for every selected instrument.

| Instrument | Default bids / asks | Best bid | Best ask | Best-only spread, bps |
| --- | --- | --- | --- | --- |
| BTCUSD:DEMO | 18 / 15 | 83,203.10 | 83,204.90 | 0.216336 |
| ETHUSD:DEMO | 11 / 10 | 2,503.73 | 2,504.14 | 1.637423 |
| 1000PEPEUSD:DEMO | 10 / 10 | 0.004179 | 0.004184 | 11.957432 |

Each recent-trade response has 36 records. Latest-trade ages were approximately
0.38 seconds for BTC, 1.08 seconds for ETH and 96.77 seconds for 1000PEPE.
Default and best-only snapshots were serial; the two ETH ask prices differed.
Book timestamps were about 1–1.45 seconds ahead of local capture. This is retained
as a signed negative age, not independent NTP/skew acceptance.

An independent later Demo UI inspection showed both sides of ETH Order Book.
The earlier 15:03 UTC empty ETH book and wide BTC snapshot are retained unchanged;
those failures no longer reproduce in this sample. No Kairos change is credited
with fixing the venue, and its historical internal cause remains unknown.

The [factual signed receipt](receipts/evedex-demo-three-pair-20261013.json) binds
source, report, numeric depth and protected UI/support evidence hashes. The tool
has 18 new offline tests; the complete ops suite passes **202 tests on each of
Windows Python 3.11.15 and 3.14**. Scoped Ruff/format and Meta static checks pass.
The exact source passed hosted
[validate](https://github.com/Kairos-cryptoAI/kairos/actions/runs/38440992415),
[adaptive-development](https://github.com/Kairos-cryptoAI/kairos/actions/runs/38440992066),
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos/actions/runs/38440991191).

One public-only update was visibly sent in the same official support conversation,
without attachments or private data, reporting the recovered snapshot and asking
for an official active five-instrument, no-real-funds test route. That route's
answer remains pending at this checkpoint. No 24-hour observer, authenticated
signing test, canary, transfer, order, paid provider, primary/legacy database or
queue operation was started. This closes the finite public three-pair diagnostic,
not any trading/readiness gate. Existing runtime and adaptive WIP were untouched.
