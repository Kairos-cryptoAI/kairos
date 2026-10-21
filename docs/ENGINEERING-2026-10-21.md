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
historical component Git pins and frozen research evidence are not rewritten.

Deploy `532d5d44531b6b503680d861c514608434b84f9b` updates only those exact
13 source projections. Both nested lock checks and all eleven source validators
pass. Its local stdlib suite ran 1,064 tests with eight existing skips. An initial
run using Execution's installed environment had four test-namespace import
errors; the clean stdlib `-S` run passed without changing code or assertions.

A subsequent proportional security commit, Deploy
`ffbcaaa061fc255f099055cf0ae88ed085007406`, patches the two additional Certifi
alerts discovered during delivery. The Text/Macro environment and older
`tests/release_gate` environment now explicitly require Certifi >=2026.10.19,
following [the published advisory](https://github.com/advisories/GHSA-6q48-6c7w-9gw2).
Their lock deltas contain only Certifi 2026.7.22 -> 2026.10.19 and root dependency
metadata; an independent TOML comparison confirms every component Git source
unchanged. This explicitly advances that old gate's **dependency environment**,
not its historical component pins or old acceptance receipts. Both updated locks
check successfully and the 1,064-test/eight-skip stdlib suite passes again. No
Backtest lock or frozen research artifact was edited, installed or executed.

At this source set, [current-source isolation](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39593394371),
[full-path SIM](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39593398790),
[installed context composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39593153020),
[the dependency-patched older gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39593152985),
[Deploy CI/builds](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39593153078)
and [Deploy CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39593151454)
have separate run identities. The first Deploy CI attempt stopped on Docker
Hub HTTP 502 while fetching the pinned Prometheus image, before checking rules;
only the failed portion was rerun once on the same commit, without a policy,
timeout, image-pin or assertion change. Its earlier failure is not erased.
These links identify each exact run; a nonterminal run is not counted as PASS.
Authenticated Deploy Dependabot inspection after the graph update returned no
open alerts; no alert was manually dismissed. The meta source verifier accepts
all 14 clean signed-main checkouts and their exact active projections.

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

### Later implementation checkpoint: native production plumbing

Execution `baeda0a28f2b85bb60aece15fa9b1fef430ba27a` adds concrete async PostgreSQL
signing-state reads, separate least-privilege append-only operator/risk/exposure
writers, strict JSONB identity/lease checks and accepted owner-arm nonce lineage.
Authorization is rechecked after I/O under the signer's shared bounded deadline.
TP/SL checks use the venue's protected-position side rather than an exit-order side.

The opt-in wire dispatcher verifies exact signed geometry, durable signing
terminal and current authorization; a separate durable one-use dispatch claim
commits before the sender callback. Timeout, cancellation or ambiguous response
does not authorize resend. Exact JSON types and immutable derived payloads are
enforced. A completed HTTP response is not represented as an exchange fill.
The existing LIVE factory refusal is unchanged; no real signer or wire call ran.

Local regular acceptance: 736 passed, one existing skip, 48 native tests excluded
from that regular invocation, plus seven subtests. Ruff/format, mypy and Bandit
pass. Two actual native PostgreSQL integration tests pass in a new isolated
synthetic database, including separated roles, async authorization, missing-risk
refusal before key access and refusal to re-arm with an old accepted nonce. Its
owned test container is stopped. The exact source's
[CI](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/39613189840)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/39613192263)
are completed successfully. Earlier failed native runs are retained; no assertion
or scientific gate was skipped to pass them.

Deploy `90759ffc0459f7684262a90e72632d5bbe647768` advances only the 13 active
Execution source projections to that SHA. Both nested lock checks, all eleven
source validators and 1,064 stdlib tests (eight existing skips) pass locally.
Historical component locks and frozen research evidence are unchanged.

See [fresh recovery evidence](RUNTIME-RECOVERY-2026-10-21.md) and the
[single approved EVEDEX inquiry](EVEDEX-PROD-SUPPORT-2026-10-21.md).
The adapters above do not calculate aggregate exposure or provide atomic pending
risk/notional reservations, independent deployed writers, or a production
lifecycle service. Those gaps remain real, not hidden behind fixture readiness.

### Bounded authenticated order/fill reads

Execution `1444900e8d1f18b183b82c9ff9a1bb1d8bda5b44` adds the existing
EVEDEX adapter's bounded order-history and per-order fill retrieval. The source
binds the authenticated `/api/user/me.exchangeId`, reads `/api/order` with
`version=2`, explicit limit/offset and a 10,000-row / 30-second ceiling, and
requires an exact parent-order binding before querying its fills. Duplicate or
conflicting rows, malformed identities/quantities, incomplete pagination and
timeouts fail closed. The adapter preserves REPLACED and EXPIRED rather than
inventing a fill from an HTTP response.

The retrieval timestamp is local capture time, not an exchange guarantee of
freshness. These records explicitly remain
`authoritative_reconciliation=false`: reading history does not release pending
risk, prove a complete authoritative venue snapshot, or enable LIVE.

The focused local suite passed 62 tests, Ruff/format and Bandit. The follow-up
commit repairs the original `_get(path)` callback compatibility by keeping
parameterized retrieval in a separate `_get_with_params` method; the earlier
failed mypy CI run is not counted as acceptance. The exact final source's
[CI](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/39627786003)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/39627789069)
completed successfully, including Linux/Windows, all-extras and native SQL jobs.
No real exchange query, signature, order or paid provider call was used to test
this change. A locally interrupted full-suite invocation is not reported as a
local full-suite pass.

### Atomic account-wide reservations: implemented and native-tested

Execution `6570747f9e277084dec4d1bfe6a0707ada83722b` adds production-state
schema v2 and exact-decimal, immutable pending-risk/notional reservations.
The PostgreSQL advisory lock serializes reservations across contexts for the
same venue account. Persisted operator/risk/arm/nonce lineage and freshness are
checked before capacity is granted. Both synchronous and asynchronous signing
authorization require the reservation contract before claims or key access;
missing sources fail closed. Reducing exits do not add entry exposure. Identical
effects are idempotent; changed payloads or request/context rebinding are refused.

Two native PostgreSQL tests passed on a fresh, isolated synthetic database.
The account-wide race admits one competing reservation and rejects the other;
the exact remaining limit is accepted and an extra 0.01 is refused. Separate
focused validation passed 65 tests, Ruff/format and mypy. The final source's
[CI](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/39640133218)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/39640132718)
completed successfully, including the native integration jobs. The owned
synthetic PostgreSQL container was stopped and removed after validation.

Earlier native fixture failures are retained. Corrections bind a distinct entry,
the persisted owner arm and a disarm timestamp after the latest race observation;
they do not relax production risk, freshness or authorization checks. Reservations
are deliberately not released by TTL, failed/unknown delivery or non-authoritative
history reads. This conservative behavior can strand capacity: authoritative
venue reconciliation and lifecycle-based release are still required, not claimed.
The opt-in components are not deployed production state producers; the LIVE
factory refusal remains intact. No real signature, order or paid API ran.

Deploy `5d915fe603176839cb06ce50481e02f4dd413375` advances only the 13 active
Execution projections to this exact source. Both nested lock checks, all eleven
source validators and 1,064 stdlib tests (eight existing skips) pass locally.
The exact source's [CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39641141796),
[current-release gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39641141681),
[full-path simulator](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39641141706),
[installed composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39641141675),
[CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39641141898)
and [dependency graph](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39641153699)
completed successfully. One Windows/Python 3.14 test job initially timed out
while probing `docker compose version --short` at its unchanged 45-second bound.
The failed job alone passed on one rerun of the same commit. No policy, assertion,
timeout, component pin or source file was changed to obtain that retry result.
CI image builds are not a local PAPER service launch.

### Remaining after these checkpoints

1. Authoritative PROD chain/signature acceptance and final signer admission.
2. Independent deployed PROD state producers, authoritative reconciliation,
   reservation release and lifecycle/service composition. Account-scoped atomic
   reservations are now native-tested source, not a deployed trading service.
3. Final-host/Windows reboot and logged-off operational acceptance. Non-trading
   feed/queue recovery itself now has fresh credentials, native joint proofs,
   an independently accepted serving contour, one drained restart and adopted
   technical monitoring. The original failure's cause remains unestablished.
4. Real feed/model/context acceptance with the existing adopted budget, plus
   final-host operational checks. No paid API or readiness promotion is inferred.

Owner capital/stop-loss and the separately qualified strategy are still needed
before arming; neither is invented during this non-strategy engineering work.
See the [active remaining register](LAUNCH-REMAINING-2026-10-18.md).
