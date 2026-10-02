# Kairos: bounded engineering delivery — 2026-10-02

This report records completed code and bounded qualification work, not a LIVE
approval. Historical receipts and frozen research identities remain unchanged.
The current source identity is [the signed release manifest](../config/current-release.json);
`SELF` resolves the manifest-bearing meta commit at verification time.

```text
TECHNICAL_PAPER_READY=false
PAPER_QUALIFIED=false
ALPHA_READY=false
LIVE_READY=false
STRATEGY_POLICY=REJECT_ALL
TRADING_AUTHORITY=NONE
```

## Delivered engineering

### Independent SIM evidence and model-attempt recovery

Persistence commit `600d37694d9da650d3137cff2e24d1a77b4fa413` adds the
opt-in SIM-only migration `025_simulator_research_evidence.sql` and independent
source/evaluation/attempt receipts. A newly enrolled, preregistered campaign
must bind its schedule, protocol, evaluator, causal source window and exact
prompt/route identity before observations. Historical geometry-only seals are
not silently upgraded into independently verified evidence.

`record_verified_sample()` resolves persisted source, evaluation and model
attempt receipts and rejects suppressed, changed, unavailable or future
evidence. `NO_INTENT`, `NOT_EVALUATED`, `NOT_CALLED`, actual call failures and
directionless volatility alerts remain distinct. Verified coverage is an
`INDEPENDENT_SOURCE_REPLAY_ONLY` engineering result, never an economic pass.

The opt-in `ResearchProposalCoordinator` in LLM commit
`711413405b40871786f60b580e13406b27959638` commits a stable attempt fence before
one provider dispatch. Exact replay returns stored evidence without another
reservation/call; an admitted START with missing or ambiguous terminal stays
unresolved. It is not interpreted as zero cost, a model answer or permission to
retry. Actual failure/response clocks cannot be backdated into a paired sample.
The coordinator does not enroll campaigns, schedule paid work, create risk
decisions or submit orders. Default production wiring is not replaced by it.

Verification: 21 coordinator unit tests, 18 synthetic semantic-policy unit
tests, and nine isolated PostgreSQL research/SIM integration tests passed. The
PostgreSQL integration target was an explicitly disposable SIM database; no
PAPER/runtime schema was migrated. This does not yet prove a live source-to-
provider-to-independent-SIM campaign or matched economic A/B performance.

### Four OpenAI routes: bounded real probes

The approved OpenAI-only roles were exercised through the existing durable
`kairos-dev-qualification-v1` campaign. Four mechanics probes passed, followed
by four preregistered synthetic policy cases on each of the same four routes:
aligned `ALLOW`, stale required feed `DEFER`, untrusted-news injection `VETO`,
and opposing signals `DEFER`. All 16 policy observations passed. There were no
automatic inference retries, DeepSeek/X paid requests or trading mutations.

| Role | Model / effort | Policy probes | Largest observed policy latency | Estimated policy cost |
| --- | --- | --- | --- | --- |
| Text Scouts | GPT-6 Luna / low | 4/4 PASS | 6,419 ms | $0.0002478 |
| Normal aggregation | GPT-6 Luna / medium | 4/4 PASS | 2,930 ms | $0.0002798 |
| Conflict review | GPT-6.1 Sol / high | 4/4 PASS | 11,143 ms | $0.0060860 |
| Macro review | GPT-6.1 Sol / xhigh | 4/4 PASS | 4,264 ms | $0.0065360 |

These are observed model identities and price-table estimates in the saved
reports, not a fresh market-wide price comparison. Four cases per route do not
establish production latency tails, availability, quota, Text/Macro service
contract qualification, economic usefulness, or that these models are best.
The policy corpus is synthetic, not a sealed strategy performance evaluator.

The mechanics estimate was $0.0019216; the policy estimate was $0.0131496.
Whole-microdollar ledger commits totalled $0.015076 for these 20 calls. Historical
costs and all six unresolved OpenAI reservations were preserved:

| Durable campaign fact | Amount |
| --- | --- |
| OpenAI committed actual usage, 26 rows | $0.040570 |
| OpenAI existing unresolved reservations, six rows | $0.154624 |
| Adopted historical off-ledger spend | $0.001984 |
| OpenAI charged/reserved allowance | $0.197178 of $12 |
| Remaining OpenAI allowance | $11.802822 |
| DeepSeek historical committed usage, unchanged | $0.001171 of $1 |

The campaign has 40 usage rows including eight historical DeepSeek rows.
Reservations were not cleared merely because these probes passed. Protected
provider keys are not embedded in reports, argv, Git or the browser.

Evidence:

- `D:/Kairos/runtime/llm-route-qualification-20261002/reports/mechanics-4-routes-20261002.json`,
  SHA-256 `1b957407c4a6bb18f955b7c00a2d010cd8d72b70da8899080339a2f208fd92b3`.
- `D:/Kairos/runtime/llm-route-qualification-20261002/reports/semantic-4-cases-4-routes-20261002.json`,
  SHA-256 `8fdaeed160dfa2159ddf11f01cc7f94dddc28830f1c1f065ca3ebd72a996d3f9`.
- Protected before/after ledger proofs retain the old 20-row digest
  `2c05cc4e8a254365acf4f508eb19ad47d8edf86e9953564e625f3ea2cd362c28`.

### Shadow recovery: fresh full-history restore

A new post-probe shadow backup restored into an isolated, network-none clone.
All 35 public tables (59 rows), all public sequences, migration history and
database/campaign UUID `e5841a09-9fd4-42c1-870c-4d0ea14411d8` matched. Source
before/after was unchanged. Its runtime migration profile excludes SIM migration
017 and the new SIM-only evidence migration 025. Clone and verification workers
were removed; consumers and trading services were not started.

- Backup: `D:/Kairos/kairos-deploy/backups/shadow-route-recovery-20261002/kairos-shadow-gate-20261002T190005Z.dump.json`;
  dump SHA-256 `ad9d465caa51e110a2f00dc22317be7b8e2f054fade3249653fcc59ed4f79c96`.
- Receipt: `D:/Kairos/kairos-deploy/backups/shadow-route-recovery-20261002/shadow-post-semantic-restore-20261002T192844Z.json`;
  result `PASS_RESTORE_ONLY_FULL35`, SHA-256
  `976d009a43759bd2b820090dfb16fe706e440fc73504486ab53c9afc79ff28b5`.

Old Windows SQL-stdin digest framing was explicitly reproduced for the
historical 20-row digest comparison; current full-table streaming uses its own
bounded, length-prefixed canonical framing. Older checkpoint-only restore
receipts are not relabelled as 35-table full-history proofs.

### PAPER recovery: read-only primary and fresh restore binding

PAPER is a separate database, not the shadow campaign. A fresh legacy backup,
signed one-row ambiguous-outbox inspection and signed clone-only runtime
upgrade/quarantine rehearsal were preserved. The current primary still has
legacy migrations 001–012, 141,879 pending outbox rows and one expired ambiguous
publication; it has not been migrated or quarantined by this delivery.

The new controller initially failed because the fixed 1 GiB restore tmpfs filled
to 100% (124 KiB available), not because primary reads or role checks failed.
Commit `66a74363229baea678e4729fe0f57943c0e367c1` retains a hard, network-none
clone bound: 2 GiB data tmpfs, 3 GiB memory, one CPU, fixed PostgreSQL resource
settings and a 300-second restore timeout. No host-volume fallback or automatic
resource expansion was introduced. The regression and all 218 deployment tests
passed on Windows Python 3.11 and 3.14.

One native retry then passed `PASS_READ_ONLY_PRIMARY_AND_CLONE`. All 27 public
legacy/bootstrap tables (531,359 rows), all sequences, migration fingerprint
and full-history digests matched the fresh restored clone. The actual primary
role's required capabilities were checked without executing DDL. Primary
before/after and protected backup/code identities matched. Zero primary
mutations, consumers, publisher calls or Redis contacts occurred. Exact PAPER
DB/Redis infrastructure was stopped afterward; generated clones/workers were
removed. The signed receipt explicitly keeps consumer restart forbidden.

- Backup manifest: `D:/Kairos/kairos-deploy/backups/kairos-paper-gate-20261002T191703Z.dump.json`;
  dump SHA-256 `5301d9b7e6ce3a5ce72963dfff4f49f3093a2f5e5b7af34d1c37414ff741bc57`.
- Accepted receipt: `D:/Kairos/kairos-deploy/backups/paper-runtime-readonly-preflight-20261002T195241Z.json`
  and detached `.json.asc`; receipt SHA-256
  `8b27622a55c65f1358177e3988c7a9fd0279773cc97ae1bdebc734ce7267bbee`.
- Next required gate:
  `SEPARATE_ATOMIC_PRIMARY_RUNTIME_AND_ONE_ROW_QUARANTINE_PROOF_REVIEW`.

This controller has no primary apply mode. The clone quarantine remains
`PUBLISH_OUTCOME_UNKNOWN`; neither restore proof establishes publication or
non-publication. Fresh proof is time-bound and must be renewed if stale before
any later primary operation. No outbox drain, bulk acknowledgement or cursor/
lease reset is authorized by a read-only PASS.

### Source alignment, dependency security and monitoring

All downstream Persistence pins now resolve to `600d376…`; consumers of LLM
resolve to `7114134…`. Versioned deploy projections and both current/SIM gate
locks were aligned. Frozen Core and Backtest source identities were preserved.

Execution commit `438ec1f…` updates the official SDK sidecar's scoped Axios
override; Node tests, package signatures/attestations and `npm audit` passed.
Execution commit `af04ec7000b64f95ada90b9fa956274788301023` fixes the optional
CCXT → requests → urllib3 vulnerable dependency graph by requiring
`urllib3>=2.8.0,<3`. The smallest compatible CCXT upgrade is 4.5.73 → 4.5.85;
urllib3 is 2.8.0. The default non-CCXT path was not given another provider.

Security outcome: **fixed dependency graph**, with lock/optional-extra tests,
actual async CCXT/eth-account/adapter imports, 58 focused and 447 full execution
unit tests, lint/types/Bandit/build and exact-head CI passing. The legitimate
DRY_RUN client-absent control remains covered. GitHub alerts 13/14/15 were
confirmed `fixed`, not dismissed. No live transport exploit or venue request was
performed, so runtime exploitability is not claimed to have been demonstrated.

Critical PAPER rules now alert on absent metric series as well as unhealthy
values; 20 temporal scenarios / 145 Prometheus rule checks passed. This proves
rule behaviour, not notification delivery: no alert receiver is configured.

## Verification receipts

The final native Windows Python 3.11.15 / uv 0.12.3 run passed all 96 checks
across 12 code repositories: 2,862 pytest passes, four skips, 74 integration
tests deselected, plus lint, format, types, Bandit, lock/sync and 12 builds.
HEAD/origin/main, source files, locks, gate script and configuration were
identical before/after. Earlier failed/changed-snapshot attempts were preserved,
not substituted for the final accepted run.

- `D:/Kairos/runtime/windows-gate-20261002/python-3.11-20261002T193333Z.receipt.json`,
  SHA-256 `db82042bc0903e5b96339b3668e43124d1f4182a2bd0d472487799cf3e64edc9`.
- Its sanitized log SHA-256 is
  `7ddd50c72f487f97efa12972c326658b5cd74ec48ab3770db270476d4f98a077`.

Local Docker gates on the declared deploy source passed seven bar-to-REJECT_ALL
tests and 23 full-path SIM tests. The latter uses closed bars, Strategy, Router,
a zero-cost deterministic review double, SIM risk and durable simulated
execution in disposable tmpfs PostgreSQL. It is not real LLM/PAPER qualification.

- `D:/Kairos/runtime/docker-engineering-gates-20261002.json`, SHA-256
  `d50f300d5ab26f98cba3fcd63fd706ff08a96a6ce92a18810bc9f7ef7843d42b`.
- Current-source image: `sha256:71f9ad76ab820e56be312d0250026c57cca661195b2ea8d5260c34c2fa6894fe`.
- SIM image: `sha256:e64a3d8cae5c468c61b1765b44181655568f155c9db18981c861f5a4e2d44456`.

Initial parallel builds encountered Git TLS EOF / shared-cache lock timeout.
Unchanged serial retries succeeded. Owned gate containers and networks were
removed; no durable host database/ledger was removed.

The local gate receipt records deploy `e3a1752…`; the later `66a7436…` change
only affects the read-only restore controller, its unit tests and documentation,
not gate images, Dockerfiles or source locks. Exact final deploy `66a7436…`
also passed hosted [CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37056683063),
[CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37056682311),
[current-source integration](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37056749476)
and [full-path SIM integration](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37056755429).
The native 12-code-repository gate uses the same final runtime SHA set;
manifest/signature/projection verification is separately repeated on the final
signed meta commit. No historical integration PASS is substituted for these
fresh exact-head hosted runs.

## Remaining boundaries — not an elapsed-month claim

PAPER recovery is separate from the accepted shadow restore. Fresh legacy
backup/inspection/quarantine-clone evidence exists, but the primary outbox
contains 141,879 pending rows and one expired ambiguous publication. The clone
rehearsal preserves `PUBLISH_OUTCOME_UNKNOWN`; it never establishes that the
ambiguous message was or was not published. Consumers remain stopped. A new
read-only full-history controller passed primary/clone binding but does not
implement primary migration or quarantine. No bulk acknowledgement, cursor/lease reset or automatic
outbox drain is permitted.

There is still engineering work that does not require a month-long run:

- A separately reviewed atomic primary runtime-upgrade / one-exact-row
  quarantine path with rollback, response-loss, repeat-inspection and fresh
  restore proofs. Passing a read-only controller alone cannot replace it.
- An account-wide durable operator kill/arming barrier. Existing protected
  PAPER canary-session stop/arming is not a global LIVE operator latch.
- Production admission/capability wiring that accepts only the new adaptive
  system's sealed evidence and explicit manual limits. LIVE startup remains a
  hard error; removing that error alone would not be implementation.
- Encrypted off-host backup transport/restore and real alert delivery. Code
  interfaces can be prepared offline, but accepted operational evidence needs
  an owner-approved remote destination, encryption/KMS arrangement and receiver.

Managed KMS/Vault and DEV/PROD account pairing cannot be invented locally. First
real-funds canary also requires owner-specified dollar-cap and daily dollar
stop-loss. No values have been inferred from account balances or LLM confidence.
UI/UX remains deferred by the owner's decision.

Real EVEDEX five-symbol read-only qualification, bounded manual DEV canary and
seven elapsed soak days remain missing. The new adaptive system still needs
its own frozen strategy/evaluator, matched economic A/B and future 365-day /
500-natural-close gate. Trial 15's historical forward days do not count for it
and Trial 15 is not authorized for LIVE. V4/V5 and Trial 15 ledgers/plans were
not changed or analysed in this delivery.

Separate maintenance issue: existing Dependabot updater jobs can fail because
their supported uv version differs from pinned uv 0.12.3. This is not the same
as source CI failure or the three now-fixed execution security alerts. A global
toolchain upgrade has not been applied to frozen research identities.
