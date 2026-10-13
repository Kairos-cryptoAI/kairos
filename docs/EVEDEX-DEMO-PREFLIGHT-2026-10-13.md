# EVEDEX Demo: authenticated read-only preflight — 2026-10-13

Observation completed at **14:41:42 UTC / 17:41:42 Europe/Moscow**. This receipt
accepts a bounded DEMO account diagnostic, not DEV/PAPER/alpha/LIVE qualification.

## Scope and source

The owner independently signed into `demo-exchange.evedex.io` and created the
existing `Kairos-demo` API key. Read-only browser inspection found its Trading
permission and indefinite expiry; no key was created, regenerated, copied or
revealed by the agent. The user file was read privately by a bounded selector:
exactly one explicit Demo API entry matched the visible masked key, and one
Demo-labelled hexadecimal signing entry was present. The signing entry's account
relationship and usable signing authority remain **unverified**; it was not used.
No credential value, raw private account response, wallet address or account ID
is included in Git or this document. The owner file was not changed or mounted.

The [official SDK profiles](https://github.com/evedex-official/exchange-bot-sdk/blob/master/src/params.ts)
separate DEV `.tech`, DEMO `.io` and PROD `.com`; DEMO uses `:DEMO`, not `:DEV`.
The [SDK HTTP client](https://github.com/evedex-official/exchange-bot-sdk/blob/master/src/utils/rest.ts)
uses `x-api-key` for API-key reads. Only fixed-origin HTTPS GETs were admitted;
redirects, proxy forwarding, automatic retries and all mutation paths were blocked.
The [official exchange API](https://github.com/evedex-official/exchange-api/blob/master/src/exchangeRestGateway.ts)
defines the five account and public market endpoints used here.

## Authentication and identity

The first GET `/api/user/me` returned HTTP 200 but the initial local guard wrongly
assumed the browser public-profile UUID was the exchange account `id`. That
attempt failed closed before subsequent reads. Its source, claim and receipt
remain unchanged. A separate explicitly bounded identity-resolution diagnostic
then observed that the public-profile UUID equals API **`authId`**, while the
exchange **`id`** is different. The API wallet matched the signed-in browser's
visible wallet mask, and `marginCall` was false. This binds the API key to the
observed Demo identity without using a wallet signature or a login POST.

The second diagnostic made eleven GETs: five authenticated account reads and
six public instrument/depth reads, all HTTP 200. Together with the first confirmed
200 there were **twelve total GETs**, not an unbounded retry loop. Account state:

- `/api/market/available-balance`: no positive available test balance.
- `/api/position`, `/api/order/opened`, `/api/tpsl`: zero returned records.
- The empty position/open-order arrays in available-balance agreed with the
  independently read components. This narrow empty-state agreement is not a full
  fill/restart/venue reconciliation acceptance.

## Required five-instrument snapshot

| Demo instrument | Trading and visibility both `all` | Bid / ask levels | Observation |
| --- | --- | --- | --- |
| BTCUSD:DEMO | yes | 4 / 1 | Two-sided, uncrossed; 898.5674 bps spread, about 8.99%, far above 25 bps. |
| ETHUSD:DEMO | yes | 0 / 0 | Empty required book. |
| SOLUSD:DEMO | no | 0 / 0 | Empty required book; not fully enabled/visible. |
| BNBUSD:DEMO | no | 0 / 0 | Empty required book; not fully enabled/visible. |
| XRPUSD:DEMO | no | 0 / 0 | Empty required book; not fully enabled/visible. |

The documented SDK-style depth query was `maxLevel=30&roundPrice=0.1`. Every
required instrument stayed in the denominator. The BTC timestamp was about
1.37 seconds ahead of client capture, not proof of clock synchronization.
One sparse snapshot does not establish lasting absence of liquidity, 24-hour
availability, percentiles, execution slippage, or the venue's internal cause.
It does show that this sample cannot pass the intended five-instrument gate.

## Retained local evidence and checks

Protected evidence directory:
`D:/Kairos/runtime/evedex-demo-preflight-20261013`.

- Initial immutable helper SHA-256:
  `0ee7832c04282563239c5e028169eab4a44501d62cf73679bc5fbdea5c431a21`.
- Initial failed-local-guard receipt SHA-256:
  `9dc8508157e312b951c71aa2c48474a43c4f8c1092dd311c41fb3664ee56ca91`.
- Separate identity-resolution helper SHA-256:
  `a993d27218630c035e379e8e75081edc6acd93e0bde3e5ece49e97650dfc395b`.
- Accepted identity/read-only receipt SHA-256:
  `962cd5b37bc595581fc887faa770d5e11c8cd4d8a87a99e193562bf038773446`.
  Its retained detached GPG signature was verified with the required signer.
- Eleven offline tests passed on Windows Python 3.11 and 3.14, including explicit
  Demo selection, duplicate/foreign labels, masked-key matching, account/auth ID
  separation, foreign wallet refusal, malformed JSON, empty-book denominators,
  price extrema, mutation/foreign-origin rejection, and redirect rejection.

## What remains closed

No 24-hour observer, PAPER service, strategy, canary, soak, order, wallet signature,
funding request, paid provider call, database migration or queue change was made.
The DEV configuration, frozen research and existing non-trading runtime were not
modified by this diagnostic. `TECHNICAL_PAPER_READY`, `PAPER_QUALIFIED`,
`ALPHA_READY`, `LIVE_READY` remain false; strategy policy remains `REJECT_ALL`.

Before using this venue for a next stage, the Demo test-funds path and usable
five-instrument liquidity need resolution. Real-money funding is not an acceptable
substitute. Switching Kairos's frozen DEV qualification route to DEMO requires a
separate explicit environment/plan decision and source-bound acceptance, not
relabelled credentials or crediting a Demo GET as DEV evidence.
