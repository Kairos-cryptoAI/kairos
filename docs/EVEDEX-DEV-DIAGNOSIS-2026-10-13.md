# EVEDEX DEV empty-book diagnosis — 2026-10-13

## Result and scope

The three missing books are empty in EVEDEX's raw responses, not lost by
Kairos's parser. A new public preflight made 12 GETs, all HTTP 200; a separate
signed-source depth diagnostic made 17 GETs, all HTTP 200. Neither program
used an API key, wallet, signature, order, database, Redis or paid provider.
The qualification remains blocked; no 24-hour/PAPER/canary/soak services started.

The diagnostic compared the exact five `USD:DEV` instruments on
`https://trading-api.evedex.tech` with three fixed query variants:

| Instrument | Default depth | `marketLevel=1` | SDK-style parameters |
| --- | --- | --- | --- |
| BTCUSD:DEV | 8 bids / 8 asks | 1 / 1 | 8 / 8 |
| ETHUSD:DEV | 10 / 10 | 1 / 1 | 10 / 10 |
| SOLUSD:DEV | 0 / 0 | 0 / 0 | 0 / 0 |
| BNBUSD:DEV | 0 / 0 | 0 / 0 | 0 / 0 |
| XRPUSD:DEV | 0 / 0 | 0 / 0 | 0 / 0 |

SDK-style here means only `roundPrice=0.1&maxLevel=30`; it is not a claim to
reproduce every aspect of the published SDK 1.2.11. Requests were sequential,
not simultaneous paired snapshots. The diagnostic ended at
2026-10-13 04:07:26.673287 UTC (07:07 MSK). Its 15 depth replies contain nine
empty and six two-sided books, with no schema/partial/crossed/transport errors.
The matcher snapshot reports `active`. Timestamp age is reported as a snapshot
observation, not proof of ongoing heartbeat, availability or future freshness.

The populated controls show that the documented query actually changes the
returned level count. For these samples, neither the tested query choices nor
our parsing explains why SOL/BNB/XRP are empty. This does **not** identify the
venue's internal maker, listing, maintenance or account-policy cause. Missing
resting liquidity is the plausible interpretation, pending venue confirmation.

## Independent metadata failures

BNB is `trading=all` but `visibility=none`, with zero last and mark prices.
XRP has a zero last price; SOL's most recent trade in the new preflight is
about 156 days old. These are additional failures of Kairos's existing gate.
`visibility=none` is not asserted to cause an empty API book: SOL/XRP are visible
and are also empty. The depth diagnostic's metadata `VALID` means schema-valid,
not admission-valid; zero prices and hidden instruments are retained explicitly.

[Public Exchange Data](https://docs.evedex.com/developers/developers/public_exchange_data)
documents unauthenticated depth and recent-trade reads, includes unavailable
instruments in the instrument list, and distinguishes matcher state from
instrument state. Funding an account does not establish book liquidity.

## DEV, DEMO and PROD are separate

Browser inspection found the owner's existing settings tab on Mainnet
`exchange.evedex.com`; only its API section/field presence was observed.
No secret value was emitted, copied, regenerated or used as a DEV credential.

The official documentation's `demo-exchange.evedex.com` link redirects to
`demo-exchange.evedex.io`, displaying `:DEMO` instruments and a login button.
The separate `exchange.evedex.tech/en` interface displays `:DEV` instruments
and also requires login in the currently available browser session.
[SDK parameters](https://raw.githubusercontent.com/evedex-official/exchange-bot-sdk/master/src/params.ts)
keep DEV `.tech`, DEMO `.io` and PROD `.com` backends distinct. The fixed Kairos
DEV mapping, chain 16182 and five-symbol universe were not changed.

The owner authorized browser inspection but later said login was unavailable.
Account/key inspection is therefore deferred. The computer-use workflow keeps
authentication/wallet dialogs with the owner; no login signature was submitted.
The prepared DEV tab is a handoff, not an authenticated account receipt.

The default PAPER secret mount has no dedicated DEV API/signing files. A bounded
label-only inventory of the supplied local file found no unambiguous recognized
DEV API-key, signing-key or expected-account-ID labels. This says the supported
import format is unresolved, **not** that the file has no credential bytes.
No secret was imported, changed or substituted; browser network counts are not
claimed by the two programmatic request counts above.

## What can continue without login

- The bounded depth diagnostic, offline schema/partial/crossed-book tests,
  source admission and evidence collection are complete. All 133 ops tests
  pass on Windows Python 3.11.15 and 3.14; scoped Ruff/format checks pass.
- The [support request draft](EVEDEX-DEV-SUPPORT-DRAFT-2026-10-13.md) is prepared
  with public facts only. It was not sent and contains no keys/account identity.
- Authenticated GET-only account pairing waits for dedicated DEV access.
  An API key and signing key are different credentials; neither is inferred
  from an untyped entry or copied from Mainnet.
- A 24-hour qualification cannot be accepted until all five required books,
  instruments and account prerequisites pass. Snapshot successes, fresh empty
  timestamps, reduced universes and synthetic self-liquidity do not substitute.

There is no standalone accepted 24-hour qualifier in the inspected source.
Existing one-shot execution qualification and short venue comparison are not
24-hour evidence; the durable quant poller belongs to the guarded PAPER topology.
It was not started as a shortcut. Auth, 24-hour availability/basis/spread/slippage,
canary and seven-day soak remain outstanding.

The [factual receipt](receipts/evedex-dev-diagnosis-20261013.json), with its
detached GPG signature, binds the underlying preflight/depth report and
raw-response hashes; it does not claim a separate hash of this Markdown page.
Earlier snapshots and frozen
research evidence were not rewritten. Unrelated adaptive WIP remains untouched.
All readiness flags remain false; `STRATEGY_POLICY=REJECT_ALL`.
