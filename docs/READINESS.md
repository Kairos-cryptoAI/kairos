# EVEDEX DEV PAPER readiness

_Evidence boundary: 2026-08-27. This document records capability and permission separately._

## Current boundary — 2026-10-10

The [launch continuation](LAUNCH-CLOSEOUT-2026-10-10.md) adds complete
runtime-source projection and offline local alert attestation. These are
engineering improvements, not accepted recovery, real delivery, off-host
restore, EVEDEX qualification or alpha. The owner defers profit optimization
and UI/UX while launch admissions remain required. The current manifest keeps
all four readiness flags false, `REJECT_ALL` and no trading authority.

## Previous boundary — 2026-10-06

The [selected adaptive strategy receipt](ADAPTIVE-STRATEGY-2026-10-06.md)
records one implemented `adaptive_pullback_range_v1` research candidate, exact
source pins and scoped engineering tests. The candidate is not economically
qualified, campaign-frozen or enrolled in a trading service. Current source
identity is [the engineering manifest](../config/current-release.json); all
four readiness flags remain false and policy remains `REJECT_ALL`. No primary
runtime recovery, venue/production qualification or trading permission follows.
Trial 15/V4/V5 and their frozen evaluators remain unchanged.

The [native-strategy comparison](STRATEGY-COMPARISON-2026-10-06.md) adds a bounded,
already seen historical diagnostic under shared costs and admission limits.
It selects no qualified winner and does not promote readiness. Short-lived
adaptive entries remain unconfirmed by strict minute quotes; conditional proxy
economics are not real executions. June breakout/union mark-time reservation
ratios exceed 1% after admission, so continuous risk compliance is not claimed.
The comparison does not freeze/enroll a campaign or read blind performance.

## Previous boundary — 2026-10-03

The [research/transport continuation](RESEARCH-TRANSPORT-ENGINEERING-2026-10-03.md)
records new signed sources, 323 deployment unit tests per Windows Python,
synthetic cursor/COPY equivalence and acknowledged rollback, and green native
7/28-case Docker gates on the same final Deploy revision as hosted CI.
These engineering proofs do not accept full primary runtime recovery, qualify
real venue/provider availability or economic alpha, or arm PAPER/LIVE.

The [October 3 operations continuation](OPERATIONS-ENGINEERING-2026-10-03.md)
adds tested durable PAPER operator fencing, unwired offline production/signing
boundaries, guarded native Telegram preparation and offline Restic preparation.
The partial atomic recovery rehearsal is **not accepted** as complete runtime
recovery. Telegram actual delivery and off-host backup remain unqualified.
No primary controlled-profile migration, consumer restart, provider/canary/LIVE
permission follows. All four readiness fields remain false and policy remains
`REJECT_ALL`. Frozen strategy/evaluator and Trial 15/V4/V5 evidence are unchanged.

## Previous boundary — 2026-10-02

The [October 2 delivery](ENGINEERING-DELIVERY-2026-10-02.md) records the new
source set, independent SIM evidence/coordinator, bounded real OpenAI mechanics
and synthetic policy probes, full shadow restore, Windows/Docker checks and
remaining primary/operations gaps. These results do not qualify economic alpha,
real EVEDEX, runtime uptime or LIVE. `TECHNICAL_PAPER_READY`, `PAPER_QUALIFIED`,
`ALPHA_READY` and `LIVE_READY` remain false; `STRATEGY_POLICY=REJECT_ALL`.
Historical markers and budgets below belong to their stated dates, not to the
current manifest. UI/UX remains deferred.

**Current-release caveat (2026-09-12):** the technical marker below belongs to
the historical pinned revision set. The unfinished release is not yet fully
revalidated. See [current implementation evidence](RECOVERY-2026-09-12.md),
including separate forward/runtime recovery, remaining canary and provider work,
and the distinction between simulated paper and actual EVEDEX qualification.

## Historical markers — August 27 revision set

```text
TECHNICAL_PAPER_READY=true
PAPER_QUALIFIED=false
ALPHA_READY=false
LIVE_READY=false
STRATEGY_POLICY=REJECT_ALL
```

`TECHNICAL_PAPER_READY=true` means only that the exact revision set below passed its declared
code, contract, parity, recovery, local Windows, Docker integration and GitHub CI gates. It does
not assert that EVEDEX credentials work, that an order was placed, that the venue met its service
thresholds, that a strategy is profitable, or that PAPER/LIVE is authorized.

`PAPER_QUALIFIED=false` is the operational truth until real EVEDEX DEV evidence completes the
ordered qualification ladder. `ALPHA_READY=false` is independent: all previous sleeves remain
rejected, while one exact candidate is only `FORWARD_FROZEN` pending genuinely future evidence.
`LIVE_READY=false` blocks EVEDEX PROD,
production signing material and real funds regardless of any other marker.

## What technical readiness covers

- strict `extra=forbid`, immutable V1 contracts for closed bars, strategy intent/review, venue
  quality, risk decision, lifecycle event and reconciled account state;
- byte-for-byte Strategy Engine parity between frozen backtest and runtime fixtures;
- provisional WebSocket close isolation, delayed double-REST finality, gap recovery and
  permanent rejection of any mutation after authoritative publication;
- candidate review limited to `ALLOW`, `VETO`, `DEFER` and priority, with no intent mutation;
- loss-at-stop sizing with 0.25% per-trade and 1% aggregate open-risk ceilings;
- EVEDEX DEV profile/account/symbol/basis/liquidity gates and `NEXT_BAR_MARKET` expiry;
- durable protected lifecycle, partial-fill handling, stop-before-target ordering, exit-race
  serialization, mutation journal and restart recovery barrier;
- official `@evedex/exchange-bot-sdk` 1.2.11 sidecar under Node 22, with no listener and no
  autonomous mutation retry;
- isolated `kairos-paper-gate` Redis/TimescaleDB/secrets/volumes, fail-closed Compose validation,
  monitoring, backup/restore and recovery tooling;
- source-revision cache binding and an embedded source identity in every Python/sidecar image,
  so runtime code cannot silently lag behind its OCI revision label;
- fault injection, race tests, local Timescale integration, Node tests/audit, image builds and
  green CI for the pinned revisions.
- a read-only forward observer with strict closed-bar normalization, per-symbol SHA-256 chains,
  immutable campaign identity, exclusive online backup and restore-to-new-path recovery drill.

Any change to a pinned revision invalidates this technical marker until its dependency pins,
lockfiles, local gates and CI are revalidated.

At the September 12 checkpoint, `CURRENT_RELEASE_TECHNICAL_STATUS=NOT_REVALIDATED`:
component tests and image-build CI were green, but the exact release source set had not yet been
revalidated. The actual Redis/PostgreSQL
Risk-to-Execution composition has now [passed with a synthetic venue](RELEASE-GATE-2026-09-12.md)
both in hosted CI and on the local relocated Docker engine (83 tests each).
SSD relocation and post-move storage/database checkpoint checks are complete.
The split Binance transport and installed Quant image also passed their scoped
checks. A sealed full-path simulator proof now covers closed bars through
Strategy, Router, a local deterministic review double, SIM-risk and durable
simulator execution; its exact scope is recorded in
[the September 20 simulator receipt](SIM-FULL-PATH-GATE-2026-09-20.md).
Runtime catch-up and real EVEDEX qualification remain incomplete. The simulator
is deliberately separate from PAPER and cannot qualify a strategy or venue.

## Previously revalidated source identity — 2026-09-22

The historical source identity `engineering-main-20260922T235905Z` (meta commit
`3119a6f0a6c301f5e9d689099f9031cdd7ec91b7`, deploy commit
`7c8d9486a6cbb140896b781df889843a7507e8ac`) passed its declared engineering
gates and had `TECHNICAL_PAPER_READY=true`. That result belongs only to that exact
identity; it does not transfer to later source revisions.

Evidence for the historical identity:

- `Test-CurrentRelease.ps1` verified all 14 repositories clean on `main`, equal
  to `origin/main`, and signed by the trusted GPG key.
- Windows quality, test and build checks passed for the eight downstream runtime
  consumers (64 checks); the changed Core, Persistence, LLM and Deploy revisions
  also passed their local quality/build/test gates.
- GitHub CI passed for each repository's exact manifest SHA.
- The [current-source REJECT_ALL integration gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/35799982089),
  [full-path isolated simulator gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/35799982010),
  [deployment CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/35799982091),
  and [meta-repository release validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/35800029646)
  completed successfully on that source set.

## Previous source identity — 2026-09-23

The source identity at that time was `engineering-main-20260923T012410Z`
(the meta-repository revision was resolved through the manifest's `SELF` entry; deploy commit
`b07a008149162227d71ce4c4d8ae6e8f602d0da9`). `Test-CurrentRelease.ps1` verified
all 14 repositories clean on `main`, equal to `origin/main`, and signed by the
trusted GPG key. The exact [Cockpit CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/35805997061)
and [meta-repository validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/35806229201)
passed.

This identity adds a responsive, read-only Cockpit frontend and a strict
versioned snapshot client. It remains a local UI, bound to `127.0.0.1`; no
snapshot producer or authenticated private-network/mobile gateway is connected.
connected.” That source identity had not inherited the previous technical
marker, so `TECHNICAL_PAPER_READY=false` at that checkpoint. Its manifest also
reported `PAPER_QUALIFIED=false`, `ALPHA_READY=false`, `LIVE_READY=false`, and
`STRATEGY_POLICY=REJECT_ALL`. No EVEDEX request, PAPER startup, canary,
paid-provider call, or LIVE action was performed for this UI work.

## Previous model-migration source identity — 2026-09-28

The [September 28 model-migration receipt](MODEL-MIGRATION-2026-09-28.md) records
that historical signed 14-repository engineering source set. At that checkpoint,
Text Scouts requested `deepseek-flash`, normal Aggregator requested `gpt-6-luna`,
and conflict Aggregator and Macro requested `gpt-6-sol` with distinct `high` and
`xhigh` efforts. Risk Manager's model-health mapping and the exact deployment
source locks were updated with those routes. The changed five Python components
passed the Windows 3.11/3.14 matrix (75 checks, zero failures), and their
current exact-SHA component CI passed. The `r3` source and isolated SIM gates
also passed locally and in hosted CI on the pinned deployment revision. See the
[model-migration receipt](MODEL-MIGRATION-2026-09-28.md) for the bounded evidence.

The August 26 frozen provider corpus used the prior model routes; it does not
qualify these new ones. No paid provider probe, EVEDEX request, PAPER startup,
or LIVE action was made for this migration. That historical manifest retained
`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, and `STRATEGY_POLICY=REJECT_ALL`. A green source or synthetic
integration gate cannot turn those into trading authorization.

## Previous engineering source identity — 2026-09-28

The [September 28 shadow receipt](SHADOW-QUALIFICATION-2026-09-28.md) records the
later historical `engineering-main-20260928T100711Z` source set. Core and Persistence
defined a SIM-only, three-arm matched observation schedule. The baseline
lineage must match across the strategy-only, LLM review, and LLM-proposal
arms; a forward-only SIM migration checks existing rows before upgrading the
database guard. No historical Trial 15 or quarter-hour evidence was rewritten.
The [LLM shadow receipt](SHADOW-QUALIFICATION-2026-09-28.md) records stricter
response/endpoint/quota validation and a local shadow-database backup/restore
drill. It also records why no paid model qualification or campaign adoption has
yet been performed.

All downstream dependency pins and deploy source locks were projected onto
the same corrected Core/Persistence and LLM revisions. Component CI passed on
the exact pinned revisions. Local deployment
validation passed 143 unit tests, the isolated current-source `REJECT_ALL`
gate (7/7), and the isolated full-path SIM gate (22/22). These are deterministic
engineering tests, not venue, alpha, provider-quality, or LIVE evidence.
The exact deploy SHA also passed hosted [CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/36407717942),
[current-source gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/36407718089),
[SIM full-path gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/36407718188),
CodeQL, and dependency-graph validation. Meta-repository
[validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/36408037780)
passed on the signed manifest-bearing commit; the subsequent Windows
PowerShell source-security fix also passed
[validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/36408757723).
The manifest retains
`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, and `STRATEGY_POLICY=REJECT_ALL`.

## Operational qualification ladder

These gates are ordered. A later gate cannot compensate for a failed or missing earlier gate.

| gate | acceptance evidence | state |
| --- | --- | --- |
| 1. EVEDEX DEV read-only | real SIWE/auth and reconciliation; no unresolved Binance gaps; availability ≥99%; p95 absolute basis, spread and slippage ≤25 bps; book age ≤5 s; timestamp skew ≤2 s over a complete 24-hour window | `BLOCKED` — dedicated DEV identity/account pairing and a current complete five-symbol, 24-hour receipt are not verified; an older snapshot had empty SOL/BNB/XRP books |
| 2. Manual technical canary | 1x, exact venue minimum quantity, one global active canary; each BTC/ETH/SOL/BNB/XRP completes a protected round trip; the set covers limit/cancel, stop, target, timeout and restart recovery | `BLOCKED_BY_GATE_1` |
| 3. PAPER soak | seven elapsed days of data/reconnect/auth/recovery with no duplicate order, unknown lifecycle state, unresolved mutation or unprotected exposure | `PENDING` |
| 4. PAPER qualification review | reviewed TCA, shortfall, venue semantics, recovery evidence and documented limitations | `PENDING` |

Until Gate 1 passes, the maximum permitted state is read-only EVEDEX DEV observation. Gate 2 is
one explicitly armed, bounded session; it does not start an automatic strategy and does not call
OpenAI, DeepSeek or X. Passing all four gates can set `PAPER_QUALIFIED=true`, but cannot change
`ALPHA_READY` or `LIVE_READY` by implication.

## 2026-08-26 operational evidence

- A new parallel `kairos-paper-gate` project was initialized with separate Redis, TimescaleDB,
  Grafana and Prometheus volumes. The previous PAPER database and its immutable bar-conflict
  evidence were not deleted or rewritten.
- At the 19:41 UTC evidence snapshot, the exact pinned Quant image had durably recorded 1,549
  consecutive closed bars across all five symbols. Per-symbol minute counts matched their exact
  observed time spans with zero gaps and zero duplicate timestamps. Outbox lag was only the
  in-flight producer row; dead letters and inbox failures were zero.
- A container-only live collector probe independently obtained stable REST-finalized bars,
  fresh funding and fresh Binance depth for BTC, ETH, SOL, BNB and XRP.
- EVEDEX DEV reported all five instruments as `trading=all`. At the same observation, BTC and ETH
  exposed executable two-sided books; SOL, BNB and XRP exposed empty books. Runtime now records
  this as `EvedexBookUnavailableError` rather than an opaque parser failure.
- Across 216 BTC and 216 ETH quality samples, entry-gate availability was 99.54%. BTC p95
  absolute basis/spread/slippage was 1.886/1.225/0.612 bps; ETH was 2.667/2.034/1.017 bps.
  Book age stayed below one second in these samples. Three required symbols still had no quality
  sample because their DEV books were empty, so the five-symbol 24-hour gate remains blocked.
- The acceptance evaluator now targets the explicitly selected Compose project. Against
  `kairos-paper-gate` it reported zero trades, fills, duplicate client IDs, unresolved effects
  and failed lifecycles, while correctly failing closed because execution recovery/account facts
  and all canary coverage are absent. No execution container was started and no mutation was
  attempted.
- A quiesced backup and restore drill passed against the clean project: 12 schema migrations and
  18 critical tables were validated in an isolated restore database. Application services then
  recovered their persisted bar/risk state without an integrity block.
- The built execution image contains official `@evedex/exchange-bot-sdk` 1.2.11 and embeds the
  same execution-engine SHA as its OCI label. It remains stopped because the labelled local
  secret source does not contain the required dedicated `evedex_dev_api_key` and
  `evedex_dev_private_key`.

## Separate alpha and provider gates

Automatic PAPER remains disabled because the Strategy Engine allow-list is empty. All previous
sleeves retain their recorded `REJECTED` results. Trial 15's exact
`regime_aligned_right_tail_v1` revision is `FORWARD_FROZEN`, not alpha: it passed one
preregistered reused-data comparison but was synthesized after its components and evaluation
archives were observed. It must remain byte/config/universe-identical and pass a single sealed
evaluation after both 365 complete future days and 500 simulated closed trades before it can be
considered for a separate PAPER approval.

The executable forward plan SHA-256 is
`38fe7512b4e4c318e5bc8dd6baa66b48eedd63112a4a447eaaf36c1175f623e8`; blind collection starts
no earlier than `2026-09-01T00:00:00Z`. The local append-only ledger currently contains only the
feature warmup through `2026-08-01T00:00:00Z`: 12,960 bars for each of BTC, ETH, SOL, BNB and XRP,
zero gaps/conflicts/quarantines and zero intents. A real backup/restore drill preserved evidence
SHA-256 `d4fcfa3d3c838e11a62fcffa2b6bf067b0d641c682d6aad7a564c0a1372af232` and left the primary
unchanged. No performance is exposed before the sealed gate becomes eligible. The historical
reports and their individual `REJECT_ALL` decisions are not recalculated or reinterpreted.

LLM/feed qualification is shadow-only and separately capped by the shared durable budget ledger:
OpenAI `$12`, DeepSeek `$1`, X `$2`. Safety requires 100% schema-valid review output, zero
`ALLOW` for deterministically forbidden cases, byte-identical intent preservation, completion
before entry deadline and no budget overrun. Its economic value is later measured as the same
strategy with and without the review overlay; it is not inferred from model intelligence.

The 2026-08-26 frozen evidence set passed the current exact conflict review (`VETO`, Terra),
bear-shock macro allocation (`BEAR` within reserve/leverage limits, Sol), normal/injection Luna
cases and the versioned five-asset DeepSeek news cases. The original SOL outage-recovery fixture
remains preserved as a conservative false-negative; v2 replaces it with an unambiguous official
approval case rather than rewriting the old report. The durable shared ledger currently records
OpenAI `$0.025494` committed plus `$0.154624` conservatively reserved, and DeepSeek `$0.001171`
committed. This establishes bounded schema/safety behavior only, not provider availability tails
or economic value.

## LIVE boundary

`TradingMode.LIVE` is a startup error in this release. `KAIROS_DRY_RUN=false` is also a startup
error and never enables PAPER or LIVE. LIVE requires, at minimum, a passing alpha revision,
qualified PAPER evidence, a separate real-funds review, managed KMS/Vault signing, encrypted
off-host backups and production-specific limits. No current Compose overlay grants that
authority.

## Reviewed revision set

| repository | commit |
| --- | --- |
| `kairos-core` | `91cd95c8e5bd4393ed04606df08c205583092df7` |
| `kairos-llm` | `18ff6388b3106f6167af2a60fa132344e0fcf380` |
| `kairos-persistence` | `d9d330c19713d681e2f29cbc8249578cdf8e95e3` |
| `kairos-strategy-engine` | `fb7d406c6e1a3060f481b91668ff3bc23a1b4b0d` |
| `kairos-backtest` | `7bcc363833deb79188c39e81b156194df49d582b` |
| `kairos-quant-scouts` | `bbfede21860e2ef7c20e3250c1422a6660b4dcc5` |
| `kairos-text-scouts` | `c0ab42c414d9e87936ef10179914e3f35a537466` |
| `kairos-router` | `a8aea4e9a56d6ed9ee8189c56498cab009c16f39` |
| `kairos-aggregator` | `46add20f68e4c9a20fbff05fe362e8bc3fc0e35c` |
| `kairos-macro-strategist` | `2a5bee94048d3764a0288ad96a7b8286855fb46f` |
| `kairos-risk-manager` | `77ec49f8c744cb5174c625a82eab0dac4de90f55` |
| `kairos-execution-engine` | `325d518b3b67b4501b54f04bcdddf9f7d0ae20a3` |
| `kairos-deploy` | `3094152cef9e3e867031182a480adba0bd606145` |

The meta-repository's own revision is the commit containing this file.
