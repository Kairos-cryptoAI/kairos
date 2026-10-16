# EVEDEX DEV: bounded progress and remaining venue gate — 2026-10-16

This continues the [October 13 closeout](EVEDEX-NONTRADING-CLOSEOUT-2026-10-13.md).
The current user permits DEV qualification, defers strategy and prohibits real
trading. This checkpoint closes the finite work below, not the venue's missing
five-instrument route, owner signing authority, 24-hour acceptance or any order.

## Fresh native public snapshot

One existing signed-source preflight ran from **19:45:52 to 19:46:24 MSK**
(16:45:52–16:46:24 UTC). It reserved and completed exactly **12 anonymous GETs**;
all returned HTTP 200, with no transport/JSON errors or automatic retry.
It used the existing DEV `.tech` origin, not DEMO `.io` or PROD `.com`.
No account endpoint, API key, wallet key, signature or exchange mutation was used.
The official [SDK profiles](https://github.com/evedex-official/exchange-bot-sdk/blob/master/src/params.ts)
still separate those environments; the
[public API documentation](https://docs.evedex.com/developers/developers/public_exchange_data)
documents depth, best-price and recent-trade GETs. No guessed route was added.

| Required DEV instrument | Observed depth | Snapshot result |
| --- | --- | --- |
| BTCUSD:DEV | Two-sided, about 0.64 seconds old; 0.0123 bps spread | Fresh valid public book and recent trades |
| ETHUSD:DEV | Two-sided, about 0.64 seconds old; 2.0512 bps spread | Fresh valid public book and recent trades |
| SOLUSD:DEV | Empty | Blocked; latest trade about 82,032 seconds old |
| BNBUSD:DEV | Empty | Blocked; hidden instrument, zero last/mark prices, no recent trades |
| XRPUSD:DEV | Empty | Blocked; latest trade about 182,250 seconds old |

Matcher state was `active`. All five remain in the denominator. A healthy matcher
or HTTP 200 does not establish a usable book. Serial one-shot requests are not
simultaneous cross-venue measurements, independent clock proof, fill evidence,
continuous uptime or a 24-hour percentile. BTC/ETH snapshot success cannot qualify
the three unavailable instruments. No liquidity was manufactured or substituted.

Private evidence is retained at
`D:/Kairos/runtime/evedex-dev-preflight-20261012/sample-20261016T164551Z-1cd7fd2b-4703-4b80-b289-829afc25c029`.
`report.json` SHA-256 is
`02d7898c716db8eeac05d46dd12a8cd59301aebec9b8ca560802ec8e7bdec625`;
its detached GPG signature was verified with the required signer. Per-request
reservations, result records and raw public replies remain retained. Earlier
failures and snapshots were not overwritten.

## Engineering closed without trading

1. **Request accounting:** run-deadline requests that never reached the network
   are now `NOT_SENT`, like slot-deadline requests, rather than incorrectly counted
   as attempted/unknown. Tests cover zero-send expiry, one-send expiry and missed
   slots; a partial pair cannot become a usable measurement.
2. **Explicit freshness:** the observer retains its existing measured-pair
   availability and Quant percentiles. It additionally reports fresh availability,
   stale/skewed, unavailable and missed counts against the same planned denominator,
   with a fail-closed accounting invariant. Stale samples are not silently dropped.
   The pinned Quant source/evaluator and its fingerprint are unchanged. Even a
   synthetic all-fresh short run cannot change readiness or claim qualification.
3. **Error-data containment:** the GET-only qualifier no longer serializes
   arbitrary getter/account exception text or invalid instrument values into
   its returned report or saved JSON. Offline sentinel regressions cover those
   paths. This is scoped diagnostic redaction, not a claim that every possible
   secret exposure in the project has been audited.
4. **Actual signing implementation:** a deterministic EIP-712 limit-order test
   uses only a public test key. Its digest and 65-byte signature match the locked
   official `@evedex/exchange-crypto` 1.1.0 schema and ethers implementation,
   independently of the Python schema builder. Recovery succeeds for the original
   message and differs for changed quantity, instrument or chain. No provider was
   attached and no signature was sent. This does not qualify the owner's real
   credential or prove venue acceptance/permissions.

Signed sources: observer `fcf58df5236ca63315f699742cc02413d53500ab`;
Execution `e133eba09daae9accb8634073bfdf5af12dd81a2`;
Deploy projections `380680fdea3efd3ed32bf70ab8a8896f5f2aff09`.
The Execution change is projected into both current engineering fixture locks
and runtime/PAPER source declarations. Both uv locks were regenerated with uv;
only the Execution source revision changed, not third-party versions. No image
was deployed or running environment upgraded by this source synchronization.

Local checks: **223 ops tests on Python 3.11 and 3.14**; **586 Execution tests
on each**, including the optional real signer with zero skips. The 45 database
integration tests were explicitly deselected locally, not credited as passes.
Fresh locked test environments were installed offline from cache. **1,014 Deploy
tests** passed with eight existing Windows skips, plus all 11 source/deployment
validators. Rendered base/PAPER definitions were checked without starting services.
Execution lint, formatting, mypy, Bandit and source/wheel build passed. An initial
isolated-mode ops invocation exposed an existing import-path constraint; running
the normal repository-root command passed without changing unrelated imports.
An initial projection run exposed an omitted fixture policy pin; that pin was
synchronized and the complete Deploy suite then passed.

The exact observer source passed hosted
[validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/38935089867)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos/actions/runs/38935094865).
Execution passed hosted
[CI, including isolated journal integration and all adapters](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/38935811439)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/38935811856).
Deploy passed its exact-source
[standard CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38936270040),
[REJECT_ALL integration](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38936269834),
[full-path SIM fixture gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38936270313),
[installed composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38936270218)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38936268209).
Those isolated hosted fixture gates are not local trading service starts.
Final-document/source-manifest checks are accepted only when their exact-source
runs complete; this document does not predeclare pending checks green.

## Explicit remaining gates

- An officially usable **BTC/ETH/SOL/BNB/XRP** no-real-funds test route and dedicated
  DEV account/signing permission acceptance. Prior Demo GET evidence is not DEV
  evidence; the October 13 support reply only supplied three Demo pairs.
- Only after those prerequisites: accepted 24-hour five-symbol availability,
  basis/spread/depth-model slippage and freshness evidence; then a separately
  bounded DEV order canary and seven-day soak. None was started as a workaround.
- Strategy selection and prospective qualification remain deferred. No paid
  OpenAI/DeepSeek/X call, transfer, faucet request, owner-key read, real order,
  trading service, research/evaluator/ledger amendment or database/queue operation
  was performed in this checkpoint. All readiness remains false and policy is
  `REJECT_ALL`.

## Separate later-discovered runtime incident

Read-only release handoff inspection found that the previous guarded runtime
boot had already failed at **17:42 MSK**, before today's EVEDEX code changes.
The retained `boot-failure.json` records `BOUNDED_DOCKER_OPERATION_FAILED_GATEERROR`
for Deploy `c2b9486`. Redis and serving worker are stopped; the last saved
`RUNNING_NONTRADING` file is from 12:34 MSK and must not be treated as current
freshness. PostgreSQL and the unrelated standby are running.

The existing boot latch, failure artifacts and original binding were not
modified. Source re-binding stopped at that guard before any move, task change
or launch. The engineering manifest's newer Deploy revision is not an accepted
replacement operational boot binding. No automatic retry, queue repair or
database recovery was attempted. See the additive incident note in the
[recovery record](RECOVERY-2026-10-16.md#later-observation-runtime-is-stopped-and-latched).
