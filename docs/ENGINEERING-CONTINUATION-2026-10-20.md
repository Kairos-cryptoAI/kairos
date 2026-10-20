# Non-strategy launch engineering — 2026-10-20

This is a bounded engineering continuation, not acceptance for real-money trading.
The requested endpoint has not been reached. Strategy rules, parameters, signals,
research evaluators and frozen Trial 15/V2/V4/V5 evidence are not changed.
All readiness flags remain false and `STRATEGY_POLICY=REJECT_ALL`.

## Later continuation — 16:10 UTC

This section supersedes the earlier Deploy source identity only; it does not
replace historical receipts or upgrade any readiness decision.

- Deploy `5f72f203717b94e5e7791dc74e0fac0195ef8e45` is on signed `main` and
  `origin/main`. Its three proportional commits add explicit bounded forensic
  AOF profiles/copy admission, patch the old release-gate environment without
  changing its historical Git pins, and add a manual current-runner build.
  The standard AOF admission defaults are unchanged; the larger forensic profile
  is explicit and is not an automatic recovery or restart authorization.
- The final local Deploy suite passes **1,055 tests**, with eight existing skips;
  all eleven static deployment/recovery validators and both PowerShell offline
  recovery checks pass. The local PowerShell checks used the installed PowerShell
  7 runtime; Windows PowerShell 5.1 refused script-file execution under its existing
  execution policy, which was not changed. Hosted Windows 3.11 checks also pass.
- The manual current-runner build and transport workflow passed at this exact
  Deploy head: [run 39454484978](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39454484978).
  It built Persistence `752c984ca276ccbb7fcbd1b60a6c75d95fe6f108` with the reviewed
  Deploy `418b0979bd53fcfaa1816392efebcff59162f601` recipe. Before registry login it
  verified Python 3.11.15, aiohttp 3.14.5, multidict 6.9.1, the full installed SQL
  migration hash map, non-root user and source/revision labels. The Docker-save
  artifact transports the image ID, not the original registry manifest bytes.
  This is a build proof, not deployment, current-R7 schema migration or LIVE approval.
- The independent retained-clone data/resource postvalidation passed, binding
  exactly five completed normal consumer deliveries and unchanged non-target
  state. The earlier host-cleanup failure remains immutable and is not relabelled
  as a successful original attempt. Postvalidation receipt SHA-256 is
  `510673d8b14c13e44e4efb09723060225a1dc5ff2b9d11e52da10455c50c112f`.
- The single source-helper attempt `21021a87167770b15f2584a6c234d2fb` failed closed.
  Its original claim is retained; both `UNKNOWN_PARTIAL` markers are retained
  and signed. It has not been retried. Private pure-input replay found that the immutable serving
  config intentionally lacks `admin_password`, which this candidate requires
  before source capture or consumer construction. No credential value is recorded
  here. An independent read-only source-state proof is still required before any
  further recovery admission. The old serve container/status and all legacy data,
  queues and frozen research inputs remain untouched.

Current source identity is recorded in `config/current-release.json`; GitHub CI,
local archive verification, recovery proof and production activation remain
distinct gates. In particular, neither the new image nor the five-message clone
proof is authority to run orders or to declare the working runtime healthy.

## Implemented and checked

- **Durable news processing.** Persistence adds migration `028_news_processing.sql`
  only to the independently prepared `controlled-runtime` profile. An atomic
  claim commits before a model call. Existing claims are never automatically
  reclaimed, deleted or retried after an ambiguous provider/publish outcome.
  The claim can suppress an event after a crash; this is conservative no-resend,
  not an exactly-once guarantee for an external model provider.
- **Actual Text integration.** Text uses that repository after durable bus startup,
  requires a stable operator-provisioned scope and refuses the all-zero example
  scope before source/provider work. An isolated real PostgreSQL test verifies
  the pre-call claim, durable publication and zero repeated provider calls after
  service reconstruction. Its dedicated hosted PostgreSQL job and Linux/Windows
  quality matrix passed at Text `3ae1570`:
  [CI](https://github.com/Kairos-cryptoAI/kairos-text-scouts/actions/runs/39407874218).
  Local provider/feed inputs were test doubles; no paid provider was contacted.
- **Owner-authenticated request validation.** Execution now verifies a complete,
  domain-separated Ed25519 manual-arm request against a server-owned pin of the
  full owner-key policy. Scope, freshness and limits precede one-use nonce
  consumption. The result is validation-only, not order or LIVE authority.
  The existing unconditional LIVE startup refusal remains. A scoped security
  diff review of commit `4540f73` completed without a verified finding; it is
  not a whole-project or deployed-production security approval.
- **Patched network dependencies.** Maintained runtime locks now select aiohttp
  `3.14.5` with a floor excluding releases below `3.14.4`. The update follows
  [the October advisory](https://github.com/advisories/GHSA-2g87-pp6c-29x5).
  Core's independently installed lock also required `multidict` to advance from
  `6.7.1` to `6.9.1`, with an explicit minimum, following the
  [multidict advisory](https://github.com/advisories/GHSA-54p9-h82j-f925).
  Core `d52fd97` passes 321 tests (two existing skips), lint, formatting, types
  and Bandit; its hosted main CI passed. Consumer locks already used `6.9.1`;
  their source pins are refreshed rather than waiving exact-source identity.
  Git pins and active deployment/gate projections were advanced coherently.
  Historical research lockfiles and Backtest remain untouched.
  A read-only check of all 14 repositories' open Dependabot alerts found no
  additional current maintained-service dependency finding. Backtest's frozen
  historical environment still resolves older vulnerable aiohttp/multidict:
  preserving its evidence does not make that environment safe to install or run.
  Its old environment was not installed or executed by this continuation.
  The full read-only GitHub source-security check finds Secret Scanning,
  push protection and required signed/no-force-push/no-deletion main protection
  enabled for all 14 repositories, with zero open redacted secret alerts.
  The strict all-repository security gate nevertheless **does not pass**:
  Backtest has three historical aiohttp alerts, Deploy has three for the old
  `tests/release_gate/uv.lock`, and Core's already-patched multidict alert remains
  open at the observation time. No alert was dismissed or exception weakened.
  A later authenticated check returned zero open Core alerts; the two historical
  environments remain distinct unresolved items in the strict aggregate gate.
- **Strategy packaging only.** Strategy commit `72a3fcf` changes only
  `pyproject.toml` and `uv.lock` so its service image uses the patched common
  runtime. The source subtree remains `836e84c2523e0ffd7a473ce31722baca4ca2a0bb`;
  the test subtree remains `e9439d5409955f4da2eda088ded5946bda0f7396`.
  All 480 unit tests pass. No strategy selection, optimization or replay was run.
- **Deployment startup.** Shared-database services explicitly select the prepared
  controlled profile; startup verifies it instead of applying DDL. Compose and
  deployment policy require Text's scope. Synthetic example values are permitted
  only by the explicit static-CI option and are rejected by actual Text startup.
  The generic controlled-schema transition inventory includes the new ledger;
  the separate historical R7 epoch remains on its exact old 32-table schema.
- **Redis diagnostics and backup primitives.** New diagnostics retain only bounded
  operation stage, elapsed time, attempt count and exception class. No raw driver
  text, payload or secret is included. The old retry/deadline policy is unchanged.
  Sandboxed AOF copy/inventory helpers were extracted without changing historical
  admission gates. Their 21 focused tests pass; this is not a fresh restore proof.

Local locked checks passed across the affected packages: lint, formatting, types,
Bandit and regular tests. Execution has 633 regular passes; Persistence 573,
Router 55, LLM 277, Quant/Risk 275 each, Aggregator 97 and Macro 92. Existing skips
and excluded integration cases are not counted as native acceptance. Deploy's
final local stdlib suite passed 1,037 tests with eight existing skips.
The separately owned synthetic PostgreSQL fixture and its private Docker network
were removed after the native Text proof; no user database or queue was removed.

## Matched final engineering source set

All 11 maintained Python package heads in the current manifest have successful
main CI and CodeQL runs. The final Strategy packaging head is `236361a`; its
source and test subtrees still match the hashes above. Backtest is unchanged.

The exact Deploy head `418b0979bd53fcfaa1816392efebcff59162f601` passed:

- [Current-source gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39414922090).
- [Full-path SIM gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39414922184).
- [Native PostgreSQL/Redis composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39414458882).
- [Repository CI and main/PAPER image builds](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39414458864).
- [CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39414457780).

The Windows 3.11 CI job initially timed out in the runner's `docker compose
version` probe. Only that failed job was retried once and then passed; no
timeout, assertion or safety gate was relaxed. Actual rendered base/PAPER build
contexts and `SOURCE_REVISION` values match their source locks. Obsolete
intermediate source-pin failures and cancelled duplicate dispatches are not
used as acceptance for this final head. The local unauthenticated remote REST
validator later hit GitHub's rate limit; authenticated CI and exact remote
`git ls-remote` checks are recorded separately, not replaced by a local PASS.

These are published source/build and explicitly isolated fixture results. No
image was deployed to a trading runtime, and no real venue or model call is
inferred from these checks.

## Current runtime is still failed closed

The separate frozen R7SQL serving worker failed again at **03:09:09 MSK on
October 19**, with `REDIS_RECOVERY_DEADLINE_EXCEEDED`. Its retained status SHA-256
is `fc992ce1c9fe081e325092fb5c68ef145ada6ef4bda5db557f24ef8d7f2ca4f4`.
The observed PostgreSQL and Redis containers are running, while the serving
container has exited. The deadline identifies the refusal, not a proven cause.

The October 19 recovery/restore/task proofs remain dated valid evidence, not
current uptime. No failed status, frozen worker/config, old receipt or queue was
overwritten. New diagnostics are engineering source, not a replacement of the
frozen running generation. Fresh incident-specific backup/clone work is separate
from serving admission. No restart or current stability PASS is claimed here.

### Fresh PostgreSQL forensic restore

The incident-specific native backup attempt `c78e9b6b7f9749208652236597bfbe39`
stopped at `BOOT_QUEUE_ORPHAN_OR_UNRESOLVED_ROW`, before its dump or clone steps.
The read-only source projection identifies 13,620 outbox rows, 13,615 completed
inbox rows and five published outbox rows without a completed inbox counterpart.
The existing boot gate was not relaxed and these rows were not acknowledged.

A separately reviewed, signed PostgreSQL-only forensic adapter then completed
run `ab7f499ed45342fe9272e6fdb5215db0`. Its 50,676,946-byte fresh dump was restored
into a newly owned PostgreSQL clone on a private internal network, with no host
ports and no source Redis attachment. All 32 tables, three sequences, verified
bar history and queue-identity projection match byte-for-byte before backup,
after backup, on the restored clone and on the final source read:
`562efa2dc824def3c16026c33e525a8d99a45a2108a937eb29417b3d688e7fe6`.
The five-row anomaly is preserved, not repaired or waived.

The clone was stopped with exit code zero; its container, volume and evidence
are retained. Final source identities and the source network census were
rechecked. Only the original PostgreSQL and Redis were running there. No source
ACK, source queue change, source-latch change, serving restart or trading occurred.

The create-only receipt is
`D:/Kairos/runtime/runtime-incident-20261020/forensic-pg-c78-ab7f499ed45342fe9272e6fdb5215db0/forensic-receipt.json`,
SHA-256 `61d66f4d571e9510a523e91586c94b9ff953c4e46844f8ecc43a83e27872476b`.
Its detached GPG signature verifies against the trusted release signer.
The result is **FORENSIC_ONLY_MATCH**, explicitly `restart_admitted=false` and
`runtime_recovered=false`. It does not prove a fresh Redis/AOF restore, exactly-once
queue recovery or a healthy running service. The unsuccessful earlier adapter
attempt and all retained safety claims remain immutable incident evidence.

A subsequent bounded SQL diagnostic ran only on that restored clone, in a
repeatable-read/read-only transaction followed by rollback. It classifies all
five rows as `CLOSED_BAR` with an exact audit match and no inbox row; there is
no outbox error, lease, dead-letter state or pending reconciliation. The clone
was stopped again with exit code zero. This identifies the completion gap, not
the underlying cause of the Redis recovery deadline, and does not authorize an
ACK. Its signed receipt is
`D:/Kairos/runtime/runtime-incident-20261020/clone-queue-classification.json`,
SHA-256 `9b3a9f167e8fcf57fc9e0782317056aa255aecd3cffa9831d3082fce6d8fa28c`.

### Fresh Redis forensic copy and native load

Run `3a9918f6df1b4ff3810cecb4ad55e22e` completed a separately reviewed,
signed, bounded Redis copy/load proof. The four source files total 25,424,366
bytes. Source content and structural AOF inventory matched before and after
copying; both new backup and pristine replay copies have the same content hash
`26aaafc8aae91fb28de518f4ecc5fec92719e4c75949ede287bb6e016d2a6672`.
Metadata-tree hashes are volume-specific and were not incorrectly equated.
The AOF contains 100,749 parsed commands and 13,620 matched publication receipts.

Redis's native RDB checker accepted both copies. A new Redis container loaded the
replay copy on an internal-only network without host ports, AOF truncation, RDB
save or automatic AOF rewrite. It was stopped and retained with exit code zero.
The source PostgreSQL/Redis identities, source network membership, file manifests
and AOF inventory were rechecked; no source ACK or restart occurred.

The create-only signed profile receipt is
`D:/Kairos/runtime/runtime-incident-20261020/forensic-redis-c78-3a9918f6df1b4ff3810cecb4ad55e22e/forensic-aof-v7-profile-receipt.json`,
SHA-256 `9827aac74eca8ed6ebcff1daa25bfcdcd740d98d3cd253e116f8dec4a2658a3f`.
The underlying signed receipt has SHA-256
`1a3320dbd66668bf8ae15561fe8226f8b73a3fa6b728fe219f80335538ba56b5`.
Both detached signatures verify against the trusted release signer.

The result is **FORENSIC_COPY_REPLAY_VALIDATED_ONLY**: successful parsing and
native loading do not establish logical SQL/Redis equality, a successful
five-message recovery, restart admission or a recovered runtime. Those checks
remain separate. The load probe's database-size value is not semantic queue
acceptance. Previously failed adapters, safety claims and owned resources were
retained; their failure receipts were not replaced with this success.

The private diagnostic adapters corrected concrete procedure errors: a bounded
parser had rejected valid `SELECT 0` inside `MULTI`, a second normalization lost
proof flags, a copy-proof ceiling disagreed with the explicitly reviewed 32 MiB
incident profile, and Docker's implicit image volume conflicted with the native
RDB checker's exact-mount requirement. The successful adapter retains default
maintained-source ceilings, transaction/database checks, exact identities,
read-only source mounts and finite exact-ID cleanup. It is not a deployed patch
to the frozen R7 worker or a change to research V4/V5 evidence.

A bounded read-only Windows event query found no matching power/wake/service
event in the retained incident window. The available Docker backend/VM logs do
not cover that window. These negative/retention observations do not establish
or exclude a Docker/network cause; the serving deadline's cause remains unproven.

## Fresh public venue evidence

At `2026-10-20T10:39:53.886567Z`, the unchanged existing sampler made exactly
12 anonymous GET attempts, with no authentication, signing, order or retry.
BTC and ETH books were fresh; SOL, BNB and XRP books were empty. The instrument
contract remained blocked with `instrument_not_fully_enabled`.
No required symbol was dropped and no 24-hour/canary/soak qualification was issued.

The create-only report is retained at
`D:/Kairos/runtime/evedex-dev-preflight-20261012/sample-20261020T103933Z-bde559b1-e858-4181-b21a-62bb103dec25/report.json`,
SHA-256 `7fc9dc275f74d598c21f9259b33610ffe4ec39d3c41d8b75aac8ba6f82c384d5`.
Its detached GPG signature was verified against the release's trusted signer.

## Budget and remaining launch boundary

The OpenAI qualification campaign was already adopted on October 2; it must not
be reset or adopted again as a new zero balance. The latest located October 15
archive records $0.054785 committed, $0.159659 reserved and $0.001984 historic
adopted exposure: $0.216428 total against the existing $12 cap. This is an archive
audit, not a fresh running-database or provider-invoice reconciliation. No calls,
refunds, reservation releases or budget increases were made by this continuation.

Remaining work is explicit, not hidden behind green unit tests:

1. Accept a fresh incident-specific restore and guarded non-trading recovery;
   establish current runtime freshness/stability and the actual failure cause.
2. Obtain the supported five-instrument DEV venue/account/signing prerequisites,
   then perform the unchanged real observation, short execution and soak gates.
3. Accept the deployed real-feed/model/context path with the existing adopted
   durable budget, rather than fixture model replies.
4. Complete the actual production activation/capability and execution integration
   against concrete PROD identity/custody and durable owner arming. Signed request
   validation alone does not close this code/deployment stage.
5. Supply a real deployment host, independent encrypted backup destination and
   managed secret/signing custody. Perform a remote restore and independent
   host-loss/alert/kill-switch acceptance on that target. No services were purchased.
6. Bind owner dollar-cap and daily stop-loss before any real-money canary.

Strategy qualification and elapsed trading gates remain prerequisites for eventual
LIVE, though strategy work is excluded from this engineering request. There is no
real-money order, readiness promotion or automatic capital ramp in this receipt.
