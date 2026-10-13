# Draft for EVEDEX support — NOT SENT

Subject: DEV `.tech` SOL/BNB/XRP books consistently empty; supported test environment?

We are qualifying a read-only client against `https://trading-api.evedex.tech`
with BTCUSD:DEV, ETHUSD:DEV, SOLUSD:DEV, BNBUSD:DEV and XRPUSD:DEV.
On 2026-10-13 around 04:07 UTC, matcher/instrument reads and three depth
variants per instrument returned HTTP 200 (17 requests total):

- `/api/market/{instrument}/deep`
- the same endpoint with `marketLevel=1`
- the same endpoint with `roundPrice=0.1&maxLevel=30`

BTC/ETH had populated two-sided books in every variant. SOL/BNB/XRP returned
`bids: []` and `asks: []` in every variant. BNB also has `visibility=none` and
zero last/mark prices; XRP has a zero last price. The matcher reports `active`.
An earlier same-day 12-request public preflight showed the same missing books;
SOL's recent-trade response contains only a roughly 156-day-old trade.

Could you confirm:

1. Are these three DEV instruments currently intended to have executable
   public books, or are they intentionally unavailable?
2. If supported, can the missing two-sided books and BNB visibility/price
   metadata be restored, or can you give the appropriate venue-side action?
3. Is the public testing target DEV `.tech` / `:DEV`, or DEMO `.io` / `:DEMO`?
   The SDK distinguishes them, while the documentation's demo link redirects
   to `demo-exchange.evedex.io`. We will not change profiles or reuse credentials
   across them without explicit confirmation.

We have not placed orders, seeded liquidity, funded an account or supplied
credentials in these diagnostics. This draft includes no account identity,
wallet address, token or private key. It has not been submitted by Kairos.
