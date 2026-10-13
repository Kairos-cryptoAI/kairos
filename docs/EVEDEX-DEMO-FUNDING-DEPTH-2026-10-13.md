# EVEDEX Demo: funding location and depth diagnosis — 2026-10-13

This continues the [authenticated Demo preflight](EVEDEX-DEMO-PREFLIGHT-2026-10-13.md)
without granting trading or DEV authority. Final depth capture:
**15:03:57 UTC / 18:03:57 Europe/Moscow**.

## Funding is present in the UI, not in trading margin

The already signed-in `demo-exchange.evedex.io` terminal and its Transfer dialog
showed positive test USDT on **Smart Account**, zero on **Trading Account**, and zero
Margin/Available Balance. Thus the earlier statement about no positive available
test balance remains accurate, but must not be read as absence of all Demo funds.
The [official SDK](https://github.com/evedex-official/exchange-bot-sdk/blob/master/README.md#how-to-get-test-usdt-in-development-environment)
describes test-faucet funds separately from real-money funding. No faucet action
was needed or performed to establish the observed existing balance.

The Transfer form was opened for inspection only. Its direction was Smart Account
to Trading Account; it auto-filled 0.21 USDT from the exchange's own insufficient
margin prompt, displayed a 2-USDT fee reserve and 0.03-USDT blockchain fee. This
auto-filled amount is **not** a Kairos capital limit, owner-approved canary cap,
or trading recommendation. The optional passive-income switch remained off.
No amount, leverage, order field, security setting or credential was changed.
No transfer confirmation, wallet signature or transaction was submitted.
Any final transfer/signature is an owner handoff; real-money/Mainnet funding is
outside this task. Funding margin would not itself repair public order books.

The exact Smart Account amount, screenshot and account-related evidence remain
private local artifacts, not Git attachments. The Demo credentials were neither
exported nor mounted into DEV.

## A local DTO guard is not proof of a venue failure

The first two authenticated GETs (`/api/user/me`, `/api/user/balance`) returned
HTTP 200. The identity matched the prior accepted exchange-account hash, public
profile `authId`, and browser wallet mask; margin call was false. The initial
local balance selector then failed closed because it required exactly one row
whose literal currency was `USDT`. This failure, its source and its receipt were
retained unchanged.

A separately admitted diagnostic of that confirmed-200 response shape found one
row with string currency and a balance field, but neither literal `USDT` nor
literal `USD`. No arbitrary currency value was printed, no alias was invented,
and no API-to-Smart-Account balance mapping was accepted. The Smart Account
amount above is **UI evidence**, not a claim derived from that unresolved DTO.
This does not invalidate the independently observed public depth replies.

The separate continuation preserved the first two durable request claims and
used at most the remaining 22 GET slots: one sanitized balance-shape check, one
instrument list, and twenty depth reads. Total: **24 GETs**, all HTTP 200, no
automatic retry, redirect, wallet login POST or mutation. It did not replay the
failed selector or alter the original receipt.

## Twenty depth observations

For every required `:DEMO` symbol, compare:

1. Default `/api/market/{instrument}/deep`.
2. `?marketLevel=1`.
3. SDK-style `?maxLevel=30&roundPrice=0.1` without authentication.
4. The same SDK-style request with the existing Demo API key.

| Instrument | Trading / visibility | All four observations |
| --- | --- | --- |
| BTCUSD:DEMO | `all` / `all` | Two-sided, uncrossed; spread 898.5674 bps, about 8.99%. Default/SDK: four bids and one ask; best-only: one each. |
| ETHUSD:DEMO | `all` / `all` | Empty asks and bids. |
| SOLUSD:DEMO | `none` / `none` | Empty asks and bids. |
| BNBUSD:DEMO | `none` / `none` | Empty asks and bids. |
| XRPUSD:DEMO | `none` / `none` | Empty asks and bids. |

The BTC terminal showed the same best ask/bid as the API; this was not a missing
local parser level or an anonymous-versus-authenticated difference. The empty
books likewise persisted across tested request variants and authenticated reads.
Fifteen strictly validated anonymous public depth DTOs were retained locally;
twelve are empty. No private account response or auth header was stored as raw
public evidence. Unknown schema fields are rejected before retention.

These sparse observations are **not** uptime, p95 spread/slippage, a 24-hour gate,
or proof of the exchange's internal root cause. They rule out the tested query
and authentication differences as a repair for this observed state. The exact
market-maker/listing/support policy requires an authoritative venue answer.
No required symbol was dropped and no synthetic quote was inserted.

## Evidence and verification

Private work directory: `D:/Kairos/runtime/evedex-demo-funding-depth-20261013`.

- Initial source SHA-256:
  `3ce815784bbbdf15eb63a38f8e386ad9725754bb5669f24863dfdda64ee699c7`.
- Preserved local-selector failure receipt SHA-256:
  `82820a1aab38ab8b8e1bb655dbf4a0fcd59ed9aefa5c58e2968d00373ea1aa79`.
- Additive depth/metadata source SHA-256:
  `1cd003b97c68f6b31d0b321bb535b7e882c5a4aa69060b9caa1ef8d75ae32e22`.
- Completed independent depth diagnostic receipt SHA-256:
  `04804e8af5e85cf3a8de508a6df52e9574e4e609033df55c96b977f358f70ac8`;
  retained detached GPG signature verified with the required signer.
- Ten offline tests passed on Windows Python 3.11 and 3.14: request/credential
  allowlists, five-symbol denominators, bounded calls, schema/duplicate rejection,
  no USD-to-USDT inference, private-data exclusion and no public retention of
  authenticated responses.

The [public support draft](EVEDEX-DEMO-SUPPORT-DRAFT-2026-10-13.md) contains only
public endpoint/instrument observations. It has not been sent; no credentials,
account IDs, wallet address or private balance are included.

## Next-stage boundary

Demo qualification remains blocked: unavailable required books, three disabled
instruments and BTC spread above the intended 25-bps limit. Owner confirmation
of a test-only internal transfer can resolve margin availability, not liquidity.
A venue-supported five-instrument route or explicit reviewed alternative is
needed before advancing. DEMO does not count as DEV evidence without a separate
environment/plan decision and source-bound acceptance.

No 24-hour observer, canary, soak, strategy, order, paid provider, primary database
or legacy queue operation was started. Existing non-trading runtime and frozen
research were not changed. All readiness remains false, `REJECT_ALL`.
