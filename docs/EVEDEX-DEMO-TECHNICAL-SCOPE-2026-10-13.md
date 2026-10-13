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
