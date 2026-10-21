# Non-strategy engineering continuation — 2026-10-21

This receipt records bounded implemented work, not a completed real-money
launch. Strategy, evaluators and Trial 15/V2/V4/V5 evidence are unchanged.
Every readiness flag remains false and `STRATEGY_POLICY=REJECT_ALL`.

## Real PROD delegation and local encrypted custody candidate

One new, no-retry authenticated `GET /api/user/oct/delegate` on the official
PROD Exchange API returned HTTP 200. Its two public delegate addresses include
the full address independently derived from the supplied dedicated EVEDEX
signing entry. The owner wallet is not that delegate. This closes the previous
mask-only uncertainty at **API-reported delegation** scope, not an order-signing
or on-chain acceptance test. No account permission, key or delegation was created.

The dedicated key was explicitly imported into a new Ethereum V3 encrypted
keystore candidate, using PBKDF2 with 1,000,000 iterations and a random 256-bit
unlock value in a separate file. Windows ACL verification accepts only explicit
current-user/SYSTEM access. A fresh process decrypted the stored file and
independently matched the delegate public address. The owner key was not chosen.
No key/unlock value was printed, committed or sent to another service. The
original supplied file is unchanged: this is **not** removal of every plaintext
source or protection against the current user / compromised administrator.

The private candidate directory is
`D:/Kairos/runtime/evedex-prod-signer-20261021-9f7d12`.
Signed retained reports:

| Report | SHA-256 |
| --- | --- |
| `delegation.report.json` | `5636c43aebd2dbda222f6e8dac4293af6a618324fc1b6576c74965e2cca6cd6e` |
| `delegated-public-binding.json` | `074220552d4b1557637ddb91a2630c7ff5686bba7440586b0e826a8707b257fa` |
| `custody-provision.report.json` | `4f6c1d1176c0adb83754a76129471efea97dd95d1aeba8bb47efa3bb9ab53602` |
| `custody-verification.report.json` | `1ef2b561117085a4e720ada2d62396ab9ef8943aa00fddbf5d823f5131e0db12` |

These signatures verify the retained evidence, not a LIVE authorization. The
keystore remains `accepted_for_signing=false`; the candidate binding has no
verified chain ID. Eight synthetic selection/refusal tests passed, including
owner exclusion, ambiguous entries, changed public address and DEV/DEMO refusal.

## PROD signing-chain uncertainty is narrowed, not guessed away

The installed SDK 1.2.11 selects PROD chain 42161; the
[current official SDK source](https://github.com/evedex-official/exchange-bot-sdk/blob/master/src/params.ts)
selects 161803. The deployed web release `0.8.21349` was traced through its
public chunks. Its order-signing helper derives both payload and EIP-712 domain
chain from the connected wallet client's `getChainId()`; its configured
fallback is Arbitrum One (42161). This proves deployed client logic, **not** the
actual connected wallet result or backend acceptance of a particular signature.

The deployed root chunk snapshot is
`https://exchange.evedex.com/assets/index-BVHFPblI.js`, SHA-256
`de6fa290b1a2b888011e502edc37b7ad30e52adad789f417b60c62f3a1211619`.
The signing chunk is
`https://exchange.evedex.com/assets/dist-DXc6wzQY.js`, SHA-256
`4d5ba1075c5100bbd4749880cc13506c18b3722225d5927da73e2c742c7304f3`.
These are dated public observations, not independently accepted production gates.

The [official PROD OpenAPI](https://exchange-api.evedex.com/api/openapi.json)
has no documented GET order-signature/domain validation endpoint. Order reads
do not return accepted chain/domain/signature fields. Smart-account address
validation is not a substitute. Its changing full-body hashes were not treated
as stable release identities; sampled relevant schemas agreed. The retained
public audit is `public-openapi-chain-audit-20261021.md` in the previous private
credential-check directory, SHA-256
`5eb730966fee39c5cd4579c4d3eec85346af48a06dd173ee45465ec164703346`.

Backend clarification or an explicitly bounded test with an authoritative
validation result is still needed. A valid private API read, listed delegate,
deposit network or client fallback cannot manufacture that result. No real
wallet signature, order, transfer or paid-provider request was made here.

## Signing authorization policy implementation

Execution now contains `ProductionSigningAuthorizationVerifier`. It binds the
owner's signed request and exact accepted durable nonce/context/database UUID,
the specific request/order/effect geometry, fresh entry operator state, risk
sizing, owner capital/daily-loss limits and fixed 0.25% / 1% risk ceilings.
The signing deadline must fit inside the risk lease and, for exits, the current
exposure lease. Reducing exits do not require a still-ARMED entry latch or an
unexpired historical arm; they retain authenticated origin and exact exposure,
parent, side, quantity and protection-trigger checks. They are not blocked by an
entry notional ceiling when reducing a grown position.

Independent review caught an authorization/signature time-of-check-use gap;
it was fixed and regression-tested before publication. The state-source
interface is **not** a deployed PROD reader. `PostgresProductionClaims.load_claim`
is asynchronous; the existing operator repository remains PAPER/DEV-only. No
fixture source, independently constructed readiness record or this policy class
alone is accepted as production state. Factory LIVE refusal is unchanged.

Signed Execution source `7e7ab28b707157405a80c384fcf3e55ede7dcfbb` passes
701 local regular tests (one existing skip, 47 native tests deselected locally),
Ruff/format, mypy and Bandit. Its 33 new tests include the actual one-shot local
keystore/Coincurve path with a public synthetic wallet and synthetic claim store;
negative authorization refuses before claim/backend invocation. That is not a
new native SQL or real-account acceptance claim. The exact source's
[six-job CI](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/39592433556)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/39592433555)
passed. All 13 current deployment projections retain the same source identity;
historical gates and frozen evidence are not rewritten.

Deploy `532d5d44531b6b503680d861c514608434b84f9b` updates only those exact
13 source projections. Both nested lock checks and all eleven source validators
pass. Its local stdlib suite ran 1,064 tests with eight existing skips. An initial
run using Execution's installed environment had four test-namespace import
errors; the clean stdlib `-S` run passed without changing code or assertions.

## Current runtime observation, not recovery acceptance

The exact failed non-trading serve remains stopped. A separately signed,
create-once authenticated read-only preflight targeted the exact existing Redis
container/image. Each producer/consumer role had one AUTH/PING/ACL-WHOAMI session;
both authenticated and returned PONG. Both refused ACL WHOAMI with NOPERM. No ACL
grant was added merely to make the diagnostic pass. This proves current role
authentication/reachability, not permission for every queue operation, the
historical outage cause, queue reconciliation, restart or stable uptime.

Thirteen synthetic preflight tests pass. The signed result is
`D:/Kairos/runtime/runtime-preflight-20261021-68255c9b335b/preflight-result.json`,
SHA-256 `adfe9c0f6b1d48e0a283baadd2eb7dd6825a389906f852ba3e59b992ce23a4ac`.
No old generation/UNKNOWN_PARTIAL claim was retried. No container was started or
stopped, and no database row, queue, lease or cursor was changed.

During initial diagnosis an agent mistakenly emitted a generation-local config
containing four local PG/Redis application-role credentials into its tool output.
Those values are not repeated or copied into this receipt. No exchange/provider
credential was in that object. Future generation credentials must be newly
provisioned; the exposed local credentials must not be silently reused as a
qualified secret source. They were not rotated on the retained database/queue.

## Still not closed

1. Authoritative PROD chain/signature acceptance and final signer admission.
2. Actual PROD state readers, one-use mutation capability and lifecycle/service
   composition. The evaluator and encrypted candidate are components, not that
   deployed service.
3. Fresh non-trading recovery/admission with newly provisioned local credentials,
   preserved history/queue proofs and current sanitized diagnostics; the prior
   failure's cause is still unestablished.
4. Real feed/model/context acceptance with the existing adopted budget, plus
   final-host operational checks. No paid API or readiness promotion is inferred.

Owner capital/stop-loss and the separately qualified strategy are still needed
before arming; neither is invented during this non-strategy engineering work.
See the [active remaining register](LAUNCH-REMAINING-2026-10-18.md).
