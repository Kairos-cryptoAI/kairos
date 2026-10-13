# EVEDEX Demo support draft — 2026-10-13

**Draft only; not sent.** Recipient: official EVEDEX support. Content is limited
to public market observations; no wallet/account identity, credentials, private
balance or research performance. This is separate from the earlier DEV draft.

## English message

Hello EVEDEX support,

We are preparing a five-instrument, read-only qualification of your DEMO venue.
Could you clarify the supported test route for BTC, ETH, SOL, BNB and XRP?

At 2026-10-13 15:03 UTC we observed:

- Origin: `https://trading-api.evedex.io`, instruments with the `:DEMO` suffix.
- BTCUSD:DEMO: best ask 87,740.00, best bid 80,194.90; spread about 898.57 bps.
  The exchange's Demo UI showed the same prices.
- ETHUSD:DEMO: trading/visibility `all`, but empty asks and bids.
- SOLUSD:DEMO, BNBUSD:DEMO, XRPUSD:DEMO: trading/visibility `none`, empty books.
- The instrument-list and all twenty depth requests returned HTTP 200. Default,
  `marketLevel=1`, SDK-style `maxLevel=30&roundPrice=0.1`, and the authenticated
  SDK-style requests produced the same book availability for all five symbols.

Are these disabled/empty markets and BTC's wide spread expected limitations of
DEMO, or is there a supported way to obtain active five-instrument test books?
If another official test environment is required, please identify its exact
API/UI hosts and instrument namespace. We will not substitute Mainnet or real
funding, manufacture liquidity, or send test orders to repair the books.

No orders were placed during this diagnosis. Thank you.

## Evidence scope

The [funding/depth receipt](EVEDEX-DEMO-FUNDING-DEPTH-2026-10-13.md) records the
bounded requests, integrity hashes and limitations. Only the public market
portion above is intended for external support; do not attach private receipts,
screenshots, owner key files, wallet data or auth headers.
