# Non-strategy launch engineering — 2026-10-20

This is a bounded engineering continuation, not acceptance for real-money trading.
The requested endpoint has not been reached. Strategy rules, parameters, signals,
research evaluators and frozen Trial 15/V2/V4/V5 evidence are not changed.
All readiness flags remain false and `STRATEGY_POLICY=REJECT_ALL`.

**Newer checkpoint:** [October 21 delegation, encrypted candidate and signing
policy implementation](ENGINEERING-2026-10-21.md). It supersedes the mask-only
signer observation and records current authenticated Redis preflight; it does
not declare the runtime recovered or the production service complete.

## Latest credential checkpoint — 2026-10-21 00:06 MSK

The owner asked to inspect the existing local credential source and account
directly, instead of requesting DEV/PROD clarification again. The prior missing
environment/identity question is now resolved at **read-only scope**:

- The existing Chrome session is signed in to the official PROD exchange. Its
  API page contains the existing `Kairos` key, permission `Trading`, indefinite
  expiry. Nothing was created, regenerated, deleted, funded or armed.
- The unscoped EVEDEX API entry in the supplied local file matches that visible
  key mask and authenticates to PROD `GET /api/user/me` with HTTP 200. The API
  `authId` equals the owner's browser profile ID. The exchange account ID is a
  separate identifier; it must not be replaced by the public profile ID.
- The API wallet equals the declared wallet in the supplied file and the full
  public address derived offline from one supplied owner private key. This
  owner key is **not selected for bot custody**. No wallet signature was made.
- A separate existing One Click Trading export is available in the same PROD
  account; the UI describes it as order-signing-only. Its visible key mask
  matches the supplied unscoped EVEDEX signing-key entry, not the DEMO key.
  Full secret-equality comparison did not complete: the clipboard interface
  returned no matchable key and was cleared/observed empty. Mask correspondence
  is not silently upgraded to signing/delegation acceptance.

Public identity/endpoints were retained in a separately ACL-restricted local
candidate binding. No secret was copied into the report, repository or chat.
The accepted read-only report SHA-256 is
`5237f4bd66e6a03015aaa0be040f249ae07bb282d81ac3577e27283070c2e831`;
the private public-identity binding SHA-256 is
`7e4f3b97edb782170687152473748857f85c8e4741517f26d06cc1ba0604aa87`.
Signed session facts are retained at
`D:/Kairos/runtime/evedex-prod-credential-check-20261020-c4f26f/session-facts.json`,
SHA-256 `969628745d907d12992a84753124949c314aaf54b3ab010f9b1f39cf422ccc73`.
The binding, final report, offline public-key inventory and session facts all
verify against the trusted release signer. They are not production gate issuers.

Retained unsuccessful probes are not erased or relabelled: the initial Python
attempt has a durable claim but no completion receipt and no surviving process
(at most one unknown GET); the first native GET returned 200 but rejected an
overstrict wallet/profile assumption; the next probe refused locally before
wire; another returned 200 and rejected an optional name-field assumption. The
final canonical auth-ID comparison succeeds. There are three known completed
GETs, all 200, plus the one bounded unknown attempt. Seven synthetic parser,
redirect, ambiguity and atomic-claim tests pass. Native selector/optional-field
regressions were checked separately. No order, transfer, wallet signature,
credential creation, paid API or runtime/database/queue mutation occurred.

There is a separate **release-versus-master EIP-712 chain discrepancy**, not a
missing user credential. Installed/released SDK 1.2.11 uses `arbitrum_one` from
the locked networks package, chain `42161`; the
[current official upstream source](https://github.com/evedex-official/exchange-bot-sdk/blob/master/src/params.ts)
sets PROD signing chain `161803`. The official
[published SDK artifact](https://registry.npmjs.org/@evedex/exchange-bot-sdk/-/exchange-bot-sdk-1.2.11.tgz)
and its signing path support the former release behavior, not proof of what the
current PROD verifier deploys. The candidate binding therefore keeps `chain_id`
null/UNVERIFIED rather than inventing an accepted chain or modifying frozen DEV
defaults. The [official signing requirement](https://docs.evedex.com/developers/developers/toolkit)
still requires exact EIP-712 payload and sender authority.

Basic PROD account/API/owner-key inputs are present; no repeated request for
those inputs is needed. Remaining work is concrete signer/delegation acceptance,
encrypted dedicated custody, resolution of the deployed signing chain and actual
production authorization/execution service composition. Read-only success does
not close those code/operational gaps or change any readiness flag. The existing
runtime failure and research/strategy boundaries are untouched.

## Latest owner scope and engineering checkpoint — 20:39 UTC

This section supersedes the remaining-work list and current-state statements
below; their dated receipts remain historical evidence. The owner selected a
single-server deployment. DEMO book availability, the three historical DEV
campaign receipts, an independent backup server and cloud KMS are no longer
mandatory gates for this engineering profile. Existing SIM is reused for finite
lifecycle checks; no replacement exchange or parallel research line is added.
This does not claim real EVEDEX execution, full-host-loss resilience or alpha.

Execution `283754059c6566bdeb30d8cf16a5a054cd99bb5d` implements:

- A separate fixed single-host evidence verifier with an independently pinned
  issuer registry. Historical V1 schemas and accepted/failed receipts are not
  reinterpreted. Its local alert evidence explicitly reports host-loss resilience
  as `NOT_ESTABLISHED`; scientific, recovery, security, custody, account-pairing,
  operator-control and owner-limit checks remain.
- A concrete encrypted local-keystore signing backend: a fresh bounded child,
  protected dedicated files, exact public binding and fixed order/protection
  typed-data schemas, followed by independent signature recovery. It is process
  isolation, not HSM custody or protection against a compromised administrator.
  It does not import `keys.txt`, sign a withdrawal or submit an order.
- Finite existing-engine acceptance on actual PostgreSQL with a local venue
  double: stale refusal, partial-fill protection, remainder cancel, restart,
  duplicate refusal, disarm and competing terminal exits. A native claims test
  also composes SQL with the actual encrypted-keystore child using a public
  synthetic wallet and fixture authorization. Those are plumbing proofs, not
  production authorization or real-account fills.

The exact Execution [six-job CI](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/39491766227)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/39491767276)
passed. Local all-extras tests passed 668 tests, with one existing skip and 47
native tests deselected locally; native integration runs in the isolated CI
database. Windows/Linux typing, Ruff and Bandit passed. The fixed sidecar SDK
remains 1.2.11; only its vulnerable redirect dependency was patched. Optional
CCXT and both active Deploy gate locks now require patched Certifi. The existing
Cockpit build dependency was patched without UI/UX work. Historical locks remain
unchanged and must not be used as the current deployment source set.

Deploy `2d9dadab19165ce0faf541d846c1db1aa041dcfd` binds all 13 active projections
to that Execution source. Both nested lock checks, all source validators and
1,064 Deploy unit tests passed (eight existing skips). At that exact commit,
[CI/builds](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39492496331),
[current-source gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39492496328),
[native full-path SIM](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39492496327),
[installed context composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39492496265)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39492496546)
passed. The separate [dependency updater](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39492669874)
for a historical gate failed because its tool rejects pinned uv 0.12.3 in favor
of supported 0.12.18, before creating any lock update. This is not hidden or
counted as a passing check, and its frozen lock was not rewritten.
No local Docker build, primary SQL access, queue mutation, paid provider request,
exchange order or LIVE arming was performed by this checkpoint.

**Current runtime is not healthy.** Generation
`9e489055b91e44df8e5ab15f94529382` failed closed at 19:47:42 UTC (22:47 MSK),
with `REDIS_RECOVERY_DEADLINE_EXCEEDED`, exit code 1 and `trading_started=false`.
The exact PostgreSQL and Redis containers were still running. The mounted
worker uses a relative monotonic recovery budget; the old batch-data deadline
was not incorrectly reused as that timer. An anonymous Redis response confirms
reachability only, not authenticated health or the root cause of the outage.
No timeout was relaxed and no retained unknown/partial attempt was retried.
The earlier restore/postserve receipts do not establish present uptime.

The hidden monitor continued scheduled runs. Its existing incident dedup treats
`running_stale` and `failed_closed` as the same active alarm, so this escalation
did not generate a new Telegram reservation. This is not evidence of a new
Telegram transport failure. No old message or unknown send was replayed.

A small maintained escalation extension (`runtime_status_r7_escalation.py`,
signed source `da873d8`) tracks the last accepted active alarm
state and permits exactly one stale-to-failed escalation through the existing
guarded `firing` transition. Real journal/guard tests cover acceptance, duplicate
suppression, recovery resolution, interrupted/unknown no-replay and budget
refusal before guard/send. The original notifier is retained byte-for-byte:
the installed signed monitor imports that path with an exact source hash.
The initial in-place edit and unsigned restoration caused the 23:33 and 23:35
MSK scheduled polls to refuse with exit code 2. Signed restoration `b29b1e2`
returned the original notifier to the exact pinned SHA-256
`20b3d58f2becff6bb5272c0b57b8bfe1b86d8daf0b5e3618363d228240e6a8fb`.
The natural 23:37:51 MSK poll then completed with exit code zero. All 231 offline
alert tests pass with the fix in the separate extension; the original notifier
and its original test are unchanged from the pre-edit baseline. Ruff/format and
the 12 offline campaign-bridge regressions also pass.
The installed monitor/task and live delivery journal were not rewritten, and
no old send was retried. Extension adoption remains a separate signed handoff,
not an asserted delivered message or changed installed-monitor behavior.

**Real-money engineering remains incomplete**, even excluding strategy. The
concrete current operator/risk signing authorization, production capability
issuer, production lifecycle executor and service composition are not wired;
the factory still refuses LIVE. Authentic PROD account/wallet/chain pairing
must also be established. General machine access and the presence of API keys
are not that identity or an implemented dispatch path. Owner dollar-cap and
daily stop-loss are chosen before arming, not invented by strategy or LLM.
See [the active remaining list](LAUNCH-REMAINING-2026-10-18.md) and
`kairos-execution-engine/docs/SINGLE-HOST-PRODUCTION.md`.

## Later continuation — postserve validation

This checkpoint supersedes earlier current-state statements, not their immutable
receipts. The real-money endpoint is **not complete**, even excluding strategy.

- A separately admitted non-trading generation `9e489055b91e44df8e5ab15f94529382`
  is running on the existing owned epoch PostgreSQL/Redis. Its one bounded public
  catch-up added 2,515 finalized bars per symbol (12,575 total); the original
  history prefix and queue were preserved. No legacy database or queue was used.
  The old failed serve was not restarted. Two fresh frames show all five symbol
  watermarks advancing, empty pending/unresolved queues, and `REJECT_ALL`.
- The original generation workflow nevertheless failed its last history-state
  check: that old predicate requires an empty message queue, which is not valid
  for a populated, healthy serving epoch. Its signed `generation-failure.json`
  remains `UNKNOWN_PARTIAL`, SHA-256
  `a5895a413fc36aab59f2e7dae32aed58bca42b6b658bec6eb8ce251d627f32f1`.
  It was not retried or relabelled PASS. This is distinct from the original
  Redis outage, whose historical cause is still not established.
- A **separate read-only** probe `77a615d3` passed all 32 table digests,
  three-sequence inventory, schema, original history prefix, anchors, database
  identity, and completed-queue predicates inside a repeatable-read read-only
  transaction. It observed 13,865 outbox/inbox/completed rows, zero pending,
  unresolved or trading rows, and zero execution orders/effects. No advisory
  lock-free claim is made while the serve owns its supervisor lock. Source
  container metadata before/during/after matched; only the exact helper was
  removed. The external source network is **not** egress-isolated. The signed
  receipt is retained at
  `D:/Kairos/runtime/runtime-incident-20261020/postserve-readonly-77a615d3/postserve-validation-receipt.json`,
  SHA-256 `d0a57cbc387d848556567a6cfc229a019fd14b2f63080bf7c719220003b48ca1`.
  Its complete worker result is also signed, SHA-256
  `77eb0d1a5677859bed75be44c1237ec9bd61deec28ae95362b43b1e537314c54`.
  Later captured frames had 13,870 then 13,875 completed rows; two Redis transport
  failures had two recoveries and zero pending replays. This is a bounded serving
  observation, not zero-error uptime or target-host restart acceptance.
- An earlier independent probe stopped before any Docker call or SQL access:
  generated Python cache files changed the directory hash, while all six source
  files remained byte-identical to the pinned archive. Its signed code/admission
  and unused workdir are retained. V2 stages only the exact six validated archive
  entries into a fresh clean snapshot; the frozen source/cache is not altered.
  Nine focused tests cover the populated queue and native-shaped archive path.
- The obsolete R7-SQL logon boot task is now disabled: its existing action pins
  the old failed container. Only its Enabled field changed; before/after XML and
  a signed disable receipt are retained. No task was dispatched and no replacement
  reboot profile is qualified. Target-host restart/host-loss acceptance remains
  open; this running desktop generation must not be described as that acceptance.
- The existing hidden two-minute R7 alert task now observes the new exact signed
  generation binding. Only its action changed; triggers, principal, settings and
  hidden WScript hosting match the preserved task XML. Create-only successor
  initialization copied all 30 predecessor journal rows and five send guards;
  the predecessor bytes remain unchanged. The natural 19:05:51 and 19:07:51 UTC
  runs both returned zero. One normal recovery transition was accepted by
  Telegram as message **94**; no human delivery observation is asserted and no
  unknown send was retried. All source/receipt/adjudication pairs are GPG-verified,
  and the new files plus owned notification parent have restricted Windows ACLs.
  Sixteen offline tests include the actual signed receipt, valid timezone
  offsets, inherited active alert, subsequent fault and unknown/no-replay path.
  Signed handoff acceptance SHA-256:
  `d300447aa4c9f9c8f219a73d233b56748cde8dd9fc07e8695727a94c0d787016`.
- Execution `7c6706d94e037a5656b9afa9a528cebe72d5f3f0` adds fresh synthetic CI
  databases for durable production-claim and sealed SIM-controller tests. The
  [exact six-job CI](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/39472211649)
  is green, including **46 native TimescaleDB tests without skips** and the
  Linux/Windows quality matrix. Tests verify role boundaries, immutable terminal
  claims, concurrent admission, restart and unknown/no-replay behavior. No PC
  source database, real signer, paid model or venue order is used. The two
  Execution commits change CI/tests only, not the LIVE factory.
- Deploy `bf7490129233d3a50b706a36345dbb05d3abcc0c` aligns the active runtime,
  PAPER, current-source and full-path SIM projections with that exact Execution
  source. Other pins, strategies, fixtures, evaluator bytes and readiness flags
  are unchanged. All local source validators, both lock checks and 1,064 Deploy
  unit tests pass (eight existing skips). Historical release/simulator profiles
  and frozen research remain unchanged. Hosted [CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39480413327),
  [current-source bar-to-REJECT_ALL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39480413605),
  [full-path SIM](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39480413437),
  [installed context composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39480413372)
  and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39480413438)
  are all green at this exact commit. These remain fixture/isolation proofs, not
  real-feed/model, target-host or production-order acceptance.
- A later 12-GET anonymous EVEDEX sample at 18:05 UTC remained blocked:
  BTC/ETH books fresh; SOL/BNB/XRP books empty with stale trades;
  `instrument_not_fully_enabled`. Signed report SHA-256
  `2d66b8d7e4b7775385d304916665545d681c6c912439b66afa1e3d58ffd1cd80`
  is retained under `evedex-dev-preflight-20261012/sample-20261020T180511Z-c4a6490b-24c6-494a-98a3-6c6d488634ad/`.
  No unsupported asset was dropped or DEV qualification granted.

The actual production factory still rejects LIVE unconditionally. Durable
claims, evidence checks and manual-arm validation are preparation, not wired
production capability. Concrete custody/signing authorization, PROD identity,
evidence issuers, target deployment, independent encrypted backup and owner
dollar/day-loss limits are still required before that integration can be
implemented and accepted. Neither a DEV key nor green fixture tests substitute
for those inputs. The deployed real-feed/model/context acceptance and existing
adopted budget reconciliation also remain open; no paid provider was invoked.

## Later continuation — 17:44 UTC

This dated checkpoint supersedes the current-state statements below, not their
historical evidence. A new serving generation is still **not started** at this
checkpoint, and no runtime-stability or real-money readiness PASS is claimed.

- Deploy `f67f030b73eb6a59feac91dd1e6a6886045afa09` is signed and pushed on
  `main`. The runner-receipt writer now distinguishes image-config identity from
  OCI archive-manifest identity. Raw descriptor hashes and sizes are validated;
  corrupt/partial OCI layouts fail closed. Historical signed receipts remain
  unchanged. The imported archive's config digest is `be2235c2...abf88df`, while
  this Docker Desktop store identifies its runnable image by manifest digest
  `41bc12dc...9703f38`; the registry manifest is a separate identity. The full
  identities are bound in the signed local import crosswalk
  `current-runner-import-crosswalk-39454484978-1.json`, SHA-256
  `b1067c786faef44cf474be2f9bbed2f2d3438f283c3020607894bb50f105f777`.
- **1,064 local Deploy tests pass**, with eight existing skips; this includes
  all original receipt/repository/migration/runtime/workflow guards and the new
  archive-identity regressions. Hosted [CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39466320500),
  [installed composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39466319963),
  and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39466319956)
  are green at this exact commit. The current engineering manifest records it;
  readiness flags are not promoted.
- The separately admitted source delivery attempt
  `7dc32965adeec4a3d43b209507ffcb79` completed exactly the five previously
  clone-verified `CLOSED_BAR` messages through the normal consumer path. Its
  signed `source-result.json` has SHA-256
  `a956c7eec56d9911b95b1c02b4ee1c56fbe998b526a00dbcd5d4483273128334`.
  PostgreSQL now has 13,620 outbox and 13,620 completed inbox rows; the missing
  count is zero. No other SQL table/sequence/history delta, manual cursor/lease
  reset, producer start, old-serve restart or trading was admitted. The earlier
  failed attempt and its claims remain immutable; it was not replayed.
- A fresh **50,677,447-byte** post-ACK PostgreSQL dump was restored into a new
  isolated clone. All four full 32-table/three-sequence/history/queue projections
  are byte-identical, SHA-256
  `091950ae34a3d5bf4183e2045df5536d54b674ba245c94f6d7cf2d1eda252e46`.
  The original V3 operator nevertheless failed its final generic actor census
  before its planned stop: its own live clone was classified as another worker.
  Cleanup stopped that exact clone with exit zero. The original failure is
  retained, not converted to a success. Separate read-only postvalidation
  accepted the stored restore evidence plus fresh source/stopped-clone metadata;
  its signed receipt SHA-256 is
  `9408e883375ca84d0a933de36de182e6a8ee6649570df352d72b7754d13c438e`.
- Post-ACK Redis proof `9d6e31e3ec274720878e7adaa1f51aae` passed native RDB
  checks, bounded AOF parsing/copy/replay and the full joint PostgreSQL/Redis
  crosswalk on isolated copies. Four files total **25,426,154 bytes**; the AOF
  has 100,762 commands and 13,620 matched publication receipts. The joint
  snapshot has 13,621 stream entries, cursor at the tail and an empty PEL.
  Its signed `postack-redis-joint-receipt.json` SHA-256 is
  `a98fd05d33619aa9cd1ad53447c25e0a073c1b9a2d28a47a5a761eadd42ae9aa`;
  signed `joint-output/capture-result.json` SHA-256 is
  `c8a884b50be60dda3d8dffbe1893c3482bd2b0042d28ae7b42115780d50b5eda`.
  Both clones exited zero; their internal network is empty. The source AOF
  manifest/inventory and source container identities stayed unchanged during
  this proof. An earlier Redis adapter stopped before creating any network or
  clone because standard Docker `host`/`none` networks report null IPAM config;
  that signed failed attempt remains retained separately.
- Docker's default address pools are exhausted. No retained network or partial
  clone was removed. Only two reviewed, non-overlapping internal `/28` ranges
  were allocated after read-only Docker-IPAM and host-route checks; no daemon
  pool, host route, legacy service or primary database setting was changed.
- An isolated dependency-only Backtest candidate installs aiohttp 3.14.5 and
  multidict 6.9.1 without advancing any of its four internal VCS pins. Lint,
  formatting, types and Bandit pass; full pytest reports 595 passes and **one
  failure**: the frozen evaluator correctly rejects changed `pyproject.toml`
  and `uv.lock`. Excluding that guard verifies compatibility only; it is not a
  full gate pass. The original Backtest files, reports and evaluator lock remain
  unchanged, and its three historical aiohttp alerts have not been dismissed.

The accepted restore is not a serving admission. The new versioned non-trading
launcher still requires a separately signed, exact source/proof/image admission
and its own fresh boot/queue/status/resource checks. The Redis outage that
triggered the old recovery deadline is not historically established; a future
outage must still stop safely rather than bypass the bounded recovery policy.
No strategy, frozen evaluator, paid API, venue order or LIVE arming changed.

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

The following list records the earlier pre-single-host scope and is historical;
the latest checkpoint and active remaining list above supersede it:

1. The fresh incident-specific restore and separate postserve read-only proof
   above are accepted. Extend bounded desktop operation to target-host
   restart/stability/host-loss acceptance; the old Redis outage cause remains
   historically unestablished. Do not reopen or retry retained failed attempts.
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
