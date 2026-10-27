# Kairos launch status

The current source release is internally consistent and passes the checks below,
but it is **not cleared for real-money operation**. The separate CURRENT
non-trading contour was retired at the owner's request on 26 October 2026
(Europe/Moscow), with data and evidence preserved. Its earlier failure and bounded
acceptance are historical; this contour is no longer an active deployment target
or a mandatory recovery project. The complete independently qualified producer,
account, signing and deployed service path is still absent. Do not
replace those proofs with `LIVE_READY=true`, an environment switch or a caller
signature. All readiness flags remain false and policy remains `REJECT_ALL`.

## Trading concept and operating scope

The target remains one causal decision path: closed market observations and
technical hypotheses, real news and macro context, routed model review,
deterministic Risk, protected execution, terminal account reconciliation and
once-only reservation release. A model proposes or reviews; it cannot issue an
order, change the stop geometry or override Risk. Zero trades is a valid result.
No fixed daily frequency or unusually high return is promised or proved.

Strategy selection and profitability, frozen campaigns, historical ledgers and
UI remain outside this engineering change. One server remains the accepted
deployment target. DEMO book campaigns, cloud KMS and an independent backup
subscription have not been reintroduced as required purchases. Full host-loss
resilience is not established by a backup stored on that same computer.

## Completed source work

- Text `a8dbd889383fbe76e9429272eccfdff93e414dd3` captures bounded original
  decompressed RSS bodies before decoding, original clocks, parsed items and
  native Text input, prompt, schema, result and output. Failed persistence blocks
  publication; explicit local fallback is not labeled a model answer. An exact
  replay of the existing pure Text transform checks the retained output.
- Execution `fe6e538a90793d496c3d388cdb4b207efabad5e6` invokes the actual native
  Text, Router, context store and review classes through an explicit
  composition API. Durable claims precede calls; expiry and cancellation keep
  unknown attempts fenced. Original model reservations, committed cost, provider
  request identities and input-token cache semantics are retained.
- The final causal-order correction refuses fresh Macro work inside an
  already-created intent before any claim, source request or model cost. It
  reuses only the native store's eligible pre-intent allocation and its original
  identity, digest and receipt, or records Macro as unavailable. The selection
  is not relabeled as a new model output. Original Macro preparation remains a
  separate existing component. Post-intent articles remain captured but are
  excluded before paid Text dispatch; neither news nor intent clocks are moved.
- The native capture sink reuses the existing owner-only create-only file
  primitive. Its separate witness records an actual clock after the raw write
  is fsynced. Exact replay preserves the first witness; partial writes are
  retained and refused, not repaired with a new clock. Restart inspection is
  read-only. This is local persistence evidence, not provider authentication.
- Existing technical alert code now supports an exact signed CURRENT owner,
  native receipt and host-acceptance report. It retains the existing incident,
  recovery, re-failure and unknown-send/no-retry journal semantics. Legacy
  notifier bindings are not repointed.
- CURRENT-only quiet-state jitter no longer appends incident-journal rows.
  A 512-poll offline regression retains only its baseline, beyond the unchanged
  256-row journal bound; real firing/recovery/re-failure, unknown-send guards
  and legacy R7 observation behavior remain covered. Original native phase
  evidence is still in the protected status file; its clocks and freshness
  checks are unchanged. The journal is not rotated, reset or enlarged.
- Deploy `935a7f386489ba680ae0c368e495e993031d0f69` aligns the current source
  projections and validates the exact optional native dependencies. Execution
  is still not granted model secrets by the ordinary deployment profile.
- The current adaptive tooling locks OpenTelemetry API 1.45.1. GitHub marks
  [alert 4](https://github.com/Kairos-cryptoAI/kairos/security/dependabot/4) fixed.
  Strategy, evaluator, campaign and other dependency revisions were unchanged.

The [current manifest](../config/current-release.json) records all 14 clean,
signed `main` sources matching their local `origin/main`. Source identity and
engineering tests are not a trading admission.

## Bounded technical-canary preparation, 26 October

The owner selected a short real-money technical test rather than waiting for
the full research campaign. A separate fixed seven-proof canary profile now
exists in Execution: recovery, security review, custody, delivered alerts,
global operator control, PROD account pairing and signed production limits.
It does not require the full profile's 365-day/500-trade research proofs, crash
gate, DEMO campaigns or off-host restore. The full production verifier was not
weakened, and this narrower profile does not establish alpha or LIVE readiness.

The opt-in `start_technical_canary_service` API reuses the existing coordinator,
Risk, protected lifecycle and service driver. It re-verifies the exact signed
safety proofs without changing their timestamps, validates an owner-signed arm,
and consumes its one-use nonce in the same isolated PostgreSQL claims store.
Unknown commit/startup outcomes remain fenced. The session allows one candidate
admission, within at most 600 seconds, bound to that exact signed arm; even a
normal no-entry result consumes the admission. This is not proof of a flat
account or permission to bypass current exposure. Expiry blocks entries, not
ongoing protective/reconciliation maintenance. No real service was started.

Risk `d8c031eb35ae54263c355ee6ad9c4f7719d306d2` can calculate a deterministic
capital/stop-loss proposal from already qualified fresh account facts, the
frozen starting scope and supplied venue minimums. The public evaluator requires
its registered source verifier first; the pinned real EVEDEX verifier still
refuses unqualified facts. The existing 0.25% per-trade and 1% aggregate stop-risk
ceilings remain. Proposed daily loss is at most 1% of the scoped capital basis,
not a return optimization or owner arm. Portfolio notional and stop risk are
separate limits; balances below actual venue minimums refuse rather than round
up. Deposits/profits cannot silently raise the starting cap. A changed proposal
requires a newly accepted scope and fresh verification; no key, reservation,
scope change or order is created by the calculator.

Aggregator `8f96df46b657e6403b5c4355f9603f38a50868cd` now requires exact retained
market/closed-bar observations and returns their original first-receive receipts.
The native composition no longer reinserts them with a later receive clock.
Missing, altered, quarantined or stale observations refuse before claims/models.
This fixes native receipt linkage; it does not authenticate a raw HTTP producer.

Pure negative LIVE Risk evaluations now return an explicit no-entry result
before staging, signing or reservations. They do not falsely mark the entire
driver as having an unknown trading effect. Independent subsequent candidates
remain possible in the ordinary driver, while the canary still has its one
admission cap. Wrong-scope evidence, unknown writes, substituted coordinators,
cancellation and ambiguous external effects retain the fail-closed behavior.

These changes have offline synthetic boundary coverage and existing native
integration coverage, not a real EVEDEX entry/close. Genuine seven-proof
operational receipts, a qualified account/input producer and an explicit owner
arm have not been produced or substituted with fixtures. The supported generic
settings/factory still refuses LIVE. The retired CURRENT owner was not resumed.

## PROD integration closure, 27 October

The existing components now have one explicit `build_production_assembly` API:
the actual PROD SDK client/read transport, entry and protective-exit LIVE Risk,
shared durable bindings/writers, protected lifecycle, schema-v2 reconciliation
and mandatory accounting are joined with exact custody, account, symbol, clock
and isolated database/pool checks. Canary start is a one-attempt latch before
the first await; a second call, changed nonce, cancelled or unknown first attempt
cannot restart it. Its `run` method does not start the driver a second time.
Final account reconciliation takes the same driver account lock and only reports
release after both terminal reconciliation and the accounting receipt succeed.
Construction itself performs no I/O, provisioning, producer registration or arm.

`ProductionEvedexReads` now uses the exact SDK client of the mutation sender,
not a DEV signer or a separate account client. It retains the original HTTP body,
digest, request/receive clocks, route, query and status for identity, balance,
positions, orders, depth, instruments, TP/SL and history. Explicit per-order fills,
fill-history and funding-transfer reads are bounded pages, not a completeness or
finality assertion. Financial decimals are parsed from retained HTTP bytes before
JavaScript conversion. Native singular `position`/`openOrder` summary arrays are
validated and mapped without inventing empty or zero account facts.

The original instrument HTTP capture can be included as a signed singleton
input stage. Its digest/scope/symbol/clocks are verified by the registered input
verifier before LIVE Risk uses the rules. PROD assembly requires those rules:
quantity is rounded downward by the actual venue step before the immutable Core
decision, then checked against price/quantity/notional limits. Off-grid immutable
stop, target or actual entry-book price is refused, not rewritten. The existing
0.25% per-trade, 1% aggregate stop-risk and 1x ceilings are unchanged. Instrument
`updatedAt` remains its original rule revision clock; capture freshness uses the
retained original HTTP receive clock and body, never a fabricated new timestamp.

The actual Node mutation send boundary now enforces the local 30/60-second
budget with entry/protection/compensation headroom. Failed or ambiguous sends
remain spent; reads and health checks do not reset it. Health reports that same
enforced counter and the original successful identity-capture age, while unknown
venue quota/auth expiry remain explicitly unknown. The separate durable FSM
budget is retained. No provider retries or real mutations were used to test it.

These closures do **not** constitute a deployed or accepted real-money path.
Private recoverable events, coherent account authority, fee/funding finality,
protection-parent authority and the current PROD signing domain remain
unqualified. Raw history readers cannot grant those authorities. Official
[order-creation documentation](https://docs.evedex.com/developers/developers/order_creation)
also states that API limit orders are GTC; an unsigned IOC field is not proof of
an IOC limit contract. No order-type substitution was made to bypass that issue.
The existing support thread still contained only the two sent inquiries at the
check in this task; no response or signing approval was inferred.

The assembly still needs genuinely qualified source implementations and one
accepted upstream producer/policy, then deployment configuration and bounded
acceptance of that exact service. It is an integration API, **not a runnable
configured LIVE launcher**. The ordinary settings, factory and Compose LIVE
denials remain. Synthetic constructor/transport tests do not register production
authorities. Neither the retired CURRENT contour nor any database/queue was
restarted or modified, and no key, paid model call or real order was used.

## Native producer and host integration, 27 October follow-up

The canonical opt-in front door is now `build_production_host`: it constructs
the actual assembly and supervises its existing entry/lifecycle workers. A lost
worker closes entry admission; surviving protective maintenance is not silently
restarted or replaced. One owner-bound admission is latched before awaiting an
input. After a naturally terminal `FLAT` trade, bounded read-only evidence polling
can lead to exactly one reconciliation/accounting attempt. Pending evidence is
not proof; ambiguous outcomes retain reservations and the unknown-attempt fence.
No forced close, background re-arm, cleanup retry or authority was added.

`NativeProductionInputPreparer` joins exact retained RSS, Macro, Binance,
EVEDEX instrument/book and native Text/Router/review records using their original
persistence witnesses. Macro now retains the exact application input/output and
claims each stable message identity durably before a provider call; a restart
cannot pay again through this captured allocation path. Projection replays the
existing native transforms and model-call linkage instead of accepting arbitrary
caller digests. Application context and local fsync evidence are explicitly not
provider authentication or a historical macro-feed qualification.

Quant calculates a new PROD venue-quality measurement from the exact selected
Binance/EVEDEX pair and original clocks under the unchanged ceilings. It cannot
retag DEV measurements as PROD; default DEV behavior remains compatible. The
producer returns an **unsigned, unregistered preparation**, not an accepted input
authority. Raw market/closed-bar ingress authority, independently accepted
producer identity, real account verifiers and actual deployment acceptance remain
unresolved. The host is a concrete library entry point, not an installed and
qualified continuously running trading service. Strategy code was not changed.

One actual free public Binance BTCUSDT depth request was retained and replayed
through the installed capture adapter/projector, with no authentication or orders:
capture `848230dab7cc66f896cae3fb787026db`, 4285 raw body bytes, SHA-256
`fac0284a5bf95bd43904fd8bec65534505cc8f2cab1bff52c54135da2573e47e`.
Original body, source/request/receive clocks and fsync witness are retained in
`D:/Kairos/runtime/launch-finish-20261025/f3e65dcdbed44331a627d8c007f7837a/public-depth-20261027-cc69157c8675428289a7ab840275b010`.
This is one source-capture check only, not five-symbol qualification, latency
acceptance, a full system traversal, an entry or a completed trade.

## Executed checks

| Check | Verified scope |
| --- | --- |
| Local Text | 115 passed, one existing deselection |
| Local Risk | 369 non-integration tests; Ruff, mypy (21 files) and Bandit passed |
| Local Execution, including native producer, capture and host | 1357 passed, one skipped, 54 integration deselections, eight subtests passed on verified Node 22.23.4; Ruff, format, mypy (73 files) and Bandit passed. |
| Local Macro, including durable captured processing claims | 110 passed, one skipped; Ruff, format, mypy (12 files) and Bandit passed. |
| Local Quant, including explicit PROD venue-quality calculation | 283 passed; Ruff, format, mypy (20 files) and Bandit passed. |
| Local Node PROD transport and existing sidecar | 47 tests passed; actual send-counter, native HTTP capture and refusal paths use explicit offline transports, not real orders. |
| Hosted Execution PostgreSQL integration, final 27 October source | 54 passed, five skipped, 1287 deselected. The fresh disposable databases test journals, immutable evidence, concurrency, loss floor and accounting; they are not venue/account qualification. |
| Local Deploy after validator correction | 1165 tests, six skipped, using the workflow's `unittest discover -s tests`; changed validator files also passed Ruff. |
| Technical operations | 250 offline tests, including 38 notifier tests and five reviewed-registration source/PowerShell-AST checks; real reviewed-V2 scheduled action, CURRENT monitoring polls and Telegram delivery were separately checked below |
| Real free RSS inspection | Cointelegraph HTTP 200, original 53404-byte body and 30 native parsed items retained and replay-checked; CoinDesk HTTP 308 retained without following or counting it as a successful feed |
| Installed launch guards | Seven noneditable native module byte identities matched; both default LIVE settings and the adapter factory independently refused LIVE without network, credentials or orders |
| Current opt-in modules, 26 October | Nine installed noneditable Execution/Risk/Aggregator modules matched current source after CRLF-only normalization; Git dependency metadata matched Risk/Aggregator revisions. This task-owned validation environment is not a deployed trading service. |
| Current PROD modules, 27 October | Nine noneditable installed Execution assembly/read/transport/lifecycle/input/reconciliation/accounting modules matched current worktree bytes after CRLF-only normalization; installed Risk Git metadata matched `d8c031e`. An explicit package reinstall was needed after ordinary sync retained an earlier wheel; the failed import was not counted as a pass. This is a validation environment, not a running trader. |
| Final native producer/host modules, 27 October | Ten noneditable Execution/Macro/Quant module byte identities matched source after CRLF-only normalization; installed Macro/Quant Git metadata matched `1f0d262` / `f1a7490`. Default LIVE settings and factory independently refused without network, credentials or orders. |

Two earlier local full-suite attempts under the default Node 24 environment
contained SDK subprocess timeouts or a local-custody child-process failure.
Targeted repeats passed, followed by the complete passing suite on a task-local
Node 22.23.4 runtime verified against the official archive SHA-256. The cause was
not fully isolated, so a Node-version root cause is not claimed. Timeouts, test
selection and production guards were not relaxed; failed runs are not passes.
An unscoped Deploy pytest collection produced no terminal result and was
cancelled by stopping only its two verified task-owned processes. It is not a
pass; the complete workflow-selected unittest discovery subsequently passed.

CI exposed two fixture defects in the new source series: Windows drive-letter
dummy paths were not absolute on Linux, and concurrent accounting-fixture
preparation read through one shared asyncpg audit connection. The former now
uses host-absolute synthetic paths; the latter prepares the fixtures sequentially
while retaining both real concurrent publication-replay and account-reservation
checks. Production validation, database functions, authority, freshness and arm
limits were not weakened. The failed CI runs remain historical failures, not
accepted proof for the final source.

The native traversal tests instantiate the real analytical classes and budgeted
gateway, but supply explicitly synthetic offline provider, transport and budget
fixtures. They do not establish model quality, account authority, economic
results or a real complete trading lifecycle. Original intent and Router
deadlines were not extended. The initial market snapshot is not retimed after
the models; a later fresh execution quote/reference remains a separate boundary.

The RSS inspection made zero paid provider calls and zero orders. It did not
wait for a favorable fresh story, qualify a producer or restart the stopped
real-news research automation. Its signed report and original native records
are retained under
`D:/Kairos/runtime/launch-finish-20261025/f3e65dcdbed44331a627d8c007f7837a/`.
The final source-aligned observation is `final-public-rss-native.report.json`
and its create-only `final-public-rss-native-session`; the earlier inspection
is retained separately, not relabeled as the final installed version.
`installed-final-launch-guards.report.json` is the historical source-aligned signed
refusal/identity check for its recorded release, not
an admission to trade.

Hosted results for the first native implementation:
[Text](https://github.com/Kairos-cryptoAI/kairos-text-scouts/actions/runs/40223704623),
[Execution](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/40224810380),
[Deploy](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40225685720),
[installed composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40225685697).
The existing [adaptive offline matrix](https://github.com/Kairos-cryptoAI/kairos/actions/runs/40224438733)
also completed successfully on all eight jobs with the corrected dependency
lock, including its existing 36,000-cell horizon-one cases. These are offline
regressions, not new market or model evidence.
The earlier Deploy source-validation failure and the rejected manifest identifier
are retained in their failed CI runs; neither validation rule was disabled.
The final causal correction additionally passed
[all six Execution jobs](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/40230536164)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/40230536231).
Earlier Deploy `bfcfd18a1edbf2b54bebfb2c477b7883655435b6` passed
[CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40231160482),
[installed composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40231160405),
[current release](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40231160406),
[simulator full path](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40231160400)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40231160018).
The final reviewed task-registration implementation, Meta `4c0fd44d`, passed
[validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/40240038491)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos/actions/runs/40240038063).
Earlier green runs are not relabelled as tests of later revisions.

The 26 October source set separately passed
[Risk CI](https://github.com/Kairos-cryptoAI/kairos-risk-manager/actions/runs/40245405050),
[Aggregator CI](https://github.com/Kairos-cryptoAI/kairos-aggregator/actions/runs/40245571187),
[all six current Execution jobs](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/40247284335)
and [Execution CodeQL](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/40247284315).
The exact current Deploy revision separately passed
[CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40247386263),
[installed composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40247386105),
[current release](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40247386215),
[full-path simulator](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40247386194)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40247385748).
Hosted PostgreSQL/SDK and composition tests still use synthetic account/venue
evidence; no live EVEDEX acceptance or deployed source authority is inferred.

The first 27 October PROD integration source set separately passed
[Risk CI](https://github.com/Kairos-cryptoAI/kairos-risk-manager/actions/runs/40409808602),
[all six Execution jobs](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/40413684614),
[Execution CodeQL](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/40413684531),
[Deploy CI and image builds](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40413719174),
[installed composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40413719213),
[current release](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40413719087),
[full-path simulator](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40413719240)
and [Deploy CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40413717538).
These jobs verify the recorded source revisions, not an armed real-money service.

The later native producer/host source set separately passed
[Macro CI](https://github.com/Kairos-cryptoAI/kairos-macro-strategist/actions/runs/40493100569),
[Quant CI](https://github.com/Kairos-cryptoAI/kairos-quant-scouts/actions/runs/40493329538),
[all six Execution jobs](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/40494914392)
and [Execution CodeQL](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/40494913588).
Deploy CI first refused the newly required sixth `native-inputs` dependency,
Quant, because its remote validator still expected five. The exact-six
declaration and lock check is now aligned, with a negative regression proving
that Quant's separate `recorder` extra cannot substitute for a native input.
No source pin or trading rule was loosened to fix that failure.
The corrected exact Deploy source then passed
[CI and image builds](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40497269454)
and [installed composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40497269485).
The unchanged source-projection revision `71c85d5` had already passed its
[current-release gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40495949457)
and [full-path simulator gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40495949465).
Their exact evidence remains attributed to that earlier Deploy revision, not
silently relabeled as the later validator correction.

## Runtime maintenance

Owner `629d61c2245743e880af3c40e58416c1` had twelve Redis transport failures and
twelve successful recoveries, no pending replays and zero queues at observation.
The counters remained unchanged across the bounded follow-up observations;
the available records do not establish the cause of those interruptions.

After the final Deploy source change its old immutable boot profile cannot
silently become the new release. The supported maintenance path stops only that
known technical owner, preserves its database, Redis volume and evidence, and
creates a separate non-trading owner from the original accepted seed. It is not
an in-place adoption or transfer of the old queue. The native successor and its
final host/alert acceptance are tracked separately; the previous bounded host
acceptance is not proof for this new source set.

The first maintenance wrapper failed after a successful native graceful stop:
it expected `STOPPED_NONTRADING` in `status.json`, whereas the worker writes a
separate create-only `serve-stop` receipt. The worker exit code was zero, its
stop receipt explicitly confirmed graceful shutdown and drained queues, and no
backup or successor had been started by that wrapper. Its signed failure and
claim remain unchanged. A separate operator completion is bound to the exact
failure, native stop bytes and exited-zero container; it does not rerun the
stopped worker or clear an unknown latch.

The separate native successor `45bb5e5873a7446883a4a6a648fc01de` passed its
19-migration/33-table recovery admission and isolated restore equality with
433,489 event-audit rows, duplicate-delivery/hash-conflict/Redis replay checks
and live closed-bar catch-up. The retained native receipt hash is
`7eac6ef6b10e4869f4f09da18f2ef66512e002c4b89b02f16de06811695cbf27`.
Owner `629d61c2245743e880af3c40e58416c1` was gracefully stopped; its volumes,
queue and fresh 53,226,316-byte backup were retained, not adopted.

That intermediate successor also passed same-owner native restart, before/after
backup-restore checks and both bounded source-progress observations. Its final
host wrapper nevertheless failed closed at boot-task installation. The late
read-only installer admission rechecks all 14 repositories; Execution had
advanced to the causal correction while the manifest still named its previous
revision. No boot task or binding was installed. The signed original failure
and completed native observations are retained. The final release must be fully
consistent and held unchanged before the independent final successor/host check;
these intermediate observations are not claimed as its acceptance.

### Final native owner and bounded host acceptance

The independent final owner is `8ed2564832624471a693726a35917416`, using Deploy
`bfcfd18a`. Its native recovery passed at `2026-10-25T21:14:28Z`: 19 migrations,
33 tables, isolated restore equality across all 33 tables and 433,849 event-audit
rows, native duplicate-delivery/hash-conflict/Redis replay checks and real
five-symbol closed-bar catch-up. Native receipt SHA-256:
`e30217481d588e56697dd72aa4f2f18ed0ed785c5afd5bf15886436114bebd4e`.
Old owners, volumes, queues, partial evidence and signed failures were preserved;
none was adopted as the new owner's queue.

The final owner passed a same-owner native boot rehearsal with backup-before,
restore verification, backup-after and restore verification. Its initial host
wrapper then failed while reading nullable Windows `NextRunTime`, after installing
the original never-run V1 task. That failed whole-host attempt remains failed.
The separately reviewed V2 registration also corrected native module resolution
before any registration, with its failed preflight preserved separately.

A fresh signed same-owner host acceptance is retained in
`D:/Kairos/runtime/prod-runtime-inputs-20261024/host-acceptance-9849bd33fe884b97a4ffd55a0c7a5fad/acceptance.report.json`,
SHA-256 `2129072392ae19533fd2c6d779160178020b71bfa5cc955a92407a5056eb05c2`.
It joins the genuine native boot/restore receipts to a new 309.765-second source
progress observation. The original failed host directory, old task XML and V1
binding are retained. The old V1 and previous-owner boot tasks were disabled
recoverably, not deleted. No failed report or failure latch was overwritten.

The actual `Kairos-CurrentRuntime-8ed256483262-Boot-ReviewedV2` scheduled action
completed with exit zero, zero new container starts and zero new boot directories
when the owner was already healthy. This proves the scheduled healthy no-op path,
not a Windows reboot or recovery from the later failure. The signed result is
`reviewed-current-host-v2.report.json`, SHA-256
`72fa7580ebac10d8ac99718d04ed22afbfc54214cbde57c022d34e5b200e196e`.
An actual OS reboot was not performed or claimed.

The owner-bound `Kairos-CURRENT-TechnicalAlerts-V1` task was installed and real
scheduled polls completed with exit zero. Its 60-second polling and 120-second
status freshness rules are unchanged. One benign qualification send was accepted
by Telegram as message 97 in the agreed group; the original sender receipt is
retained, with no retry. Server acceptance is not human confirmation of visibility.

### Latest real runtime failure — launch remains blocked

At `2026-10-25T22:42:58.328447Z` the serving container exited 1 with
`REDIS_RECOVERY_DEADLINE_EXCEEDED`. The original status records `attempts=1`,
`elapsed_ms=95038`, prior `TimeoutError` and stage `pending_read`. PostgreSQL and
Redis remained running, and the serving container was not OOM-killed. These facts
do not identify the infrastructure root cause or establish current queue health.

The existing code sets the next stage before checking the recovery deadline.
Thus the record does not show a 95-second pending Redis read: the deadline can
expire before that read is dispatched. A delayed event loop, synchronous status
filesystem work, or host/VM scheduling remain distinguishable hypotheses, not
confirmed causes. Existing telemetry cannot resolve them. No timeout was relaxed,
queue or cursor reset, failed owner restarted/adopted, or artificial healthy
status written. The prepared artificial outage test was not executed because a
genuine failure had already occurred.

The real automatic firing alert was accepted at
`2026-10-25T22:45:23.310890Z` as Telegram message 98, without a duplicate send.
No recovery/resolved alert or subsequent stable runtime is claimed. Boot admission
already refuses `FAILED_CLOSED_OWNER_STATUS_REQUIRES_REVIEW`; the scheduled
task is not a mechanism for clearing that failure.

Original status bytes and a factual signed incident are retained under the same
launch evidence directory in `final-runtime-incident.report.json`, SHA-256
`d7725d0bc53e974473fa73cb364ebdb5d2619bf79795b310cfe30f5fd0b85d6a`.
Earlier native/host passes remain historical bounded checks, not continuous
availability or present launch acceptance.

### Owner requested CURRENT retirement

At `2026-10-26T02:10:34+03:00`, the separate CURRENT owner
`8ed2564832624471a693726a35917416` was taken out of operation. Exactly these
Windows tasks were disabled, with their original XML retained for recovery:

- `Kairos-CURRENT-TechnicalAlerts-V1`;
- `Kairos-CurrentRuntime-8ed256483262-Boot-ReviewedV2`.

The already failed worker remained stopped. Only this owner's PostgreSQL and
Redis containers were gracefully stopped, both exiting zero. Containers,
database/Redis volumes, queues, backups, receipts and source history were not
deleted. No primary, legacy or R7 resource, cursor, lease or risk gate was changed.
No real orders, paid model calls or replacement runtime were started.

The signed retirement result is
`D:/Kairos/runtime/current-retirement-20261026/719780494ad94e329827ada907ae290a/retirement.report.json`,
SHA-256 `b63b027d33233fc0270fdfa57a699446c8df0dabfeb982ad5341931b1a1e27a4`.
Retirement is reversible using the retained data and task definitions, but it is
not authorization to resume this failed owner. Do not automatically recreate or
resume this experimental contour or make repairing it a release prerequisite.
The actually selected trading service still needs its own verified data,
execution, account and operational admission; disabling CURRENT grants none.

## Conditions still blocking real money

1. **An operational selected trading service.** The retired experimental CURRENT
   owner is not the future trading service. Restoring that owner is not required
   merely to continue the project. The service actually selected for trading
   must demonstrate working data delivery, bounded restart/recovery and safe
   failure handling; no replacement or LIVE service was activated by retirement.
2. **Trusted upstream deployment.** The concrete native producer now projects
   retained RSS/Macro/venue/model evidence through the existing envelope preflight.
   Raw market/closed-bar ingress still needs qualified original source authority,
   and the producer needs an independently accepted identity/key and deployment
   acceptance. A prepared unsigned manifest, caller-supplied DTO or synthetic
   registered verifier cannot fill this role.
3. **Authoritative venue facts.** EVEDEX account consistency, complete recoverable
   private events/fills, fees/funding finality, protection lineage, native order
   time-in-force semantics and the accepted PROD signing domain remain
   unqualified. The new bounded raw REST readers do not turn these into accepted
   real account/exit/cancellation/terminal verifiers. The existing support thread contained only the
   two sent inquiries at the latest check, with no response. The
   [official SDK](https://github.com/evedex-official/exchange-bot-sdk) describes
   capabilities, not all of those recovery guarantees. API-key possession and
   a visible delegate do not establish them.
4. **One deployed trading service.** The concrete assembly and supervising host
   APIs now join the existing execution components, but real source implementations and
   upstream producer remain prerequisites for a configured launcher and bounded
   acceptance of the exact selected service. The ordinary Compose configuration still
   selects `evedex` and `DRY_RUN`; it does not enable the new optional native
   composition. The supported settings/factory path intentionally refuses LIVE.
   A functioning non-trading data worker and lifecycle fixtures are not a full
   deployed decision-to-close-to-reconciliation trader.
5. **Final operational and owner admission.** The selected real source/account
   set must pass the existing service, protection, recovery and notification
   acceptance, with concrete dollar-cap and daily-loss limits and a separately
   validated manual arm. Those amounts may come from the deterministic qualified
   account proposal; they need not be typed by the owner, but the proposal alone
   is not a signed limits policy or arm. An unqualified balance or LLM confidence
   cannot assign those authority fields. Technical success never automatically
   arms LIVE. The short canary does not wait for the full research gates.

There is no accepted real EVEDEX entry/close, profitable full-system test or
professional-trader equivalence in this release. No real order or paid provider
call was made for the implementation above; existing campaign spend and unknown
holds were neither reset nor converted into a new budget.
