# Production engineering checkpoint — 2026-10-25

## Outcome and limits

Three concrete implementation gaps are closed below. This is an engineering
source set, not a complete deployed trader or a deadline-based LIVE approval.
The source identity is in [current-release.json](../config/current-release.json).
All readiness flags remain false and `STRATEGY_POLICY=REJECT_ALL`.

No real order, paid provider call, credential disclosure, legacy database/queue
mutation or frozen research change was made by this work. The old Windows boot
binding was not silently retargeted. The subsequently accepted non-trading
recovery below remains separate from the production-code results.

## Implemented

1. **Bounded production lifecycle driver.** Execution `03e1766` exposes an
   explicit factory using the existing concrete coordinator. It serializes
   account work, recovers before admission, bounds queue/time/shutdown, and
   defaults to refusing entries. Cancellation/expiry checks run before Risk,
   after Risk and immediately before engine submission. Unknown outcomes latch
   recovery; no automatic replacement or retry is credited. In-flight external
   effects cannot be undone by cancelling a local task. Durable native claims,
   not the process-local queue fence, own restart idempotency. This does not
   bypass an FSM recovery block or the default CLI's LIVE refusal.
2. **Original EVEDEX GET response evidence.** Execution `98ae9dc` retains
   bounded decompressed response-body bytes before JavaScript numeric parsing,
   exact allowlisted method/route/query, status, original local clocks and
   SHA-256. Python verifies the record and parses numbers as Decimal. Parsed
   objects are not reserialized and presented as original bodies. No secret
   headers are captured. This does not prove a shared account snapshot,
   recoverable fills/funding history or an accepted signing domain.
3. **Budget-bound model-call evidence.** LLM `6f2c28a`, with portability fix
   `d91566b`, adds an opt-in synchronous create-only sink. Exact application
   prompts/schema are recorded after durable reservation and before the call;
   a separate completion binds the start only after validated response and
   durable cost commit. Failures retain unknown holds/committed spend, without
   refund or retry. Provider input-token caching is recorded honestly, not
   mislabeled as response reuse. Owner-only local files retain partial and
   conflicting attempts. These are application-boundary records, **not original
   provider HTTP responses**, and do not register a qualified LIVE producer.

Aggregator `863eaa6`, Macro `edca442` and Text `c1de5c7` pin the final LLM
implementation. Deploy `50af49e` aligns current source projections and updates
only the isolated Text/Macro/Router fixture's OpenTelemetry API to 1.45.1.
No historical campaign dependency set was rewritten.

## Verification

| Scope | Actual local result |
| --- | --- |
| Execution non-integration suite | 1085 passed, 1 skipped, 54 deselected; 8 subtests |
| Existing coordinator and new driver on isolated native PostgreSQL | 2 passed; synthetic venue/account/signers |
| Pinned SDK sidecar | 42 tests passed |
| LLM full suite | 292 passed, 6 skipped |
| Aggregator / Macro / Text on fresh noneditable dependency installs | 97 / 92 / 106 passed; Macro 1 skip, Text 1 deselection |
| Deploy validators/tests after final fixture dependency refresh | 1160 tests passed, 8 skipped |

Execution and LLM passed lint, formatting, typing and Bandit. LLM typing was
checked against Windows and Linux after a real Linux CI failure exposed
unguarded Windows-only ctypes calls; that failed run is retained.

Affected exact-commit CI:
[Execution](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/40204781007),
[LLM](https://github.com/Kairos-cryptoAI/kairos-llm/actions/runs/40205338576),
[Aggregator](https://github.com/Kairos-cryptoAI/kairos-aggregator/actions/runs/40205499275),
[Macro](https://github.com/Kairos-cryptoAI/kairos-macro-strategist/actions/runs/40205499234),
[Text](https://github.com/Kairos-cryptoAI/kairos-text-scouts/actions/runs/40205498506).
The final Deploy `50af49e` passed its
[Windows/Linux/image CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40206385338)
and [installed composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40206385406).
The unchanged source projections at `9d7fd47` passed
[current-release](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40205995188)
and [full-path SIM](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40205995114).
Initial Debian snapshot connection/503 failures and bounded image-build
timeouts are retained. Only completed failed CI jobs were rerun; no dependency
pin or build gate was weakened to obtain green results.

Local JUnit evidence is retained under
`D:/Kairos/runtime/production-finish-20261025/d5fc09160294416696baa1840156fb6b/`.
An initial one-CPU native fixture run had one deadline failure and one pass.
Both later tests passed with a two-CPU fixture; this does not establish CPU as
the root cause or qualify production latency. The failed run was not removed.
The exact owned disposable PostgreSQL container was then stopped cleanly; its
volume and partial evidence remain. No other container was stopped by this work.

## New host incident, not a current uptime pass

The earlier [host acceptance](CURRENT-HOST-RECOVERY-2026-10-25.md) remains a
historical bounded result. A later Windows restart was observed at approximately
14:13 UTC / 17:13 Moscow. The exact owned PostgreSQL, Redis and serve containers
for `3652db45719547b18fad1d6ff10ea002` all exited with code 255 at 14:15:06 UTC;
their inspected OOM flags were false. The final status at 14:12:03 UTC is stale,
not current health. This correlation is not a completed root-cause analysis.

The old immutable profile binds Deploy `92c4847`. The current source check
requires an exact clean signed release; it does not permit silently treating
the new metadata-only descendant as the old receipt. New-source recovery and
boot acceptance must use the supported owned path, not edited receipts, removed
locks or a weakened source gate. No actual post-restart recovery is credited
by the original checkpoint; the subsequent result is recorded separately below.

## Subsequent current-source data recovery and launch acceptance

The existing native launcher created **one** new owner,
`629d61c2245743e880af3c40e58416c1`, using the original accepted 173,164-row
historical seed. It did not import or adopt owner 3652's database or queue.
Deploy remains pinned to `50af49e`; Core, Persistence, Quant, the independently
admitted image recipe, image and wheel identities are explicit in the new
profile and signed receipt. No source gate was relaxed to reuse the old owner.

Native recovery passed catch-up for all five symbols, a fresh backup, separate
restore and equality of **33 tables**, three sequences and **432,329 event-audit
rows**. Duplicate delivery, hash-conflict refusal, Redis replay and the serving
restart passed. The controlled schema remains `current-controlled-v1`, 19
migrations; this is not an assertion that every production service/migration ran.

The exact new owned PostgreSQL/Redis/serve resources then passed the existing
boot rehearsal: backup/restore before and after history-only catch-up,
queue/original-history preservation, integrity/Redis checks and a fresh,
advancing `RUNNING_NONTRADING` worker. Neither old owners nor their queues were
restarted or adopted by this acceptance.

| Observation | Elapsed | Healthy samples | Separately retained transient samples |
| --- | ---: | ---: | ---: |
| Before owned boot | 309.204 s | 11 | 0 |
| After owned boot | 319.344 s | 11 | 5 |

The post-boot sampled settling totaled 12.875 s, under the unchanged per-settle
30-second bound. All five watermarks advanced in each window. These are bounded
healthy samples, not continuous availability, long soak or execution latency.

The original launch wrapper reported `FAILED_CLOSED` after the native launcher
had already returned `PASS_NONTRADING_RUNTIME_EPOCH`: Docker changed only the
ordering of the old PostgreSQL container's two mount records. A separate signed
read-only adjudication verified unique destinations and equality of **every**
container/mount field after sorting that set. It did not discard fields, hash
old volume contents, rewrite the failed wrapper or repeat native recovery.

Administrative registration initially refused execution under PowerShell's
`Restricted` policy. One subsequent fixed plan also refused; its specific
reason was not retained and is not claimed solved retrospectively. An
independent elevated read-only probe then passed both native `ALREADY_RUNNING`
and the installer `PLAN_ONLY` check with zero resource starts/registrations.
A separate administrative completion registered the new task once, reusing
the completed same-owner gates. Only the verified child installer received
`-ExecutionPolicy Bypass` and `PATHEXT=.EXE`; machine/user policies were unchanged.
All earlier failures and original observation bytes remain retained.

`Kairos-CurrentRuntime-629d61c22457-Boot` uses the existing hidden, exact-source,
same-user Highest/Interactive `pythonw -I -B` logon action: two-minute delay,
IgnoreNew and zero retries. Read-back checked its full policy, binding and
bootstrap hash. The real action returned **LastTaskResult=0** at 19:52 Moscow,
with **zero container starts and zero new boot attempts**. No actual Windows
reboot was performed for this new acceptance; it is not a pre-logon service.

After that pass, only the exact superseded owner-3652 boot task was disabled,
not deleted. Its original XML, binding, history and signed retirement receipt
remain recoverable. Other tasks and paused research automations were unchanged.

Key retained evidence:

- Native receipt:
  `D:/Kairos/runtime/current-runtime-20261024/run-629d61c2245743e880af3c40e58416c1/current-runtime-receipt.json`,
  SHA-256 `2c18f607aa6856ded1f61b79dae050b36e2c66dc456b9eed3209a01582879f4f`.
- Signed host acceptance:
  `D:/Kairos/runtime/prod-runtime-inputs-20261024/host-acceptance-198cc18d72d64451a142f5aebafb4bf4/acceptance.report.json`,
  SHA-256 `33acfa6c19959d3507139fd30f970b9bd47630bf3d670a40c4431be2651baa8e`.
- Signed scheduled action in that host directory: `scheduled-action/report.json`,
  SHA-256 `1c383232e54ba90a296833ff95712b2dbfc3b53fe558b6283879cfd096c1dc46`.
- Engineering evidence parent:
  `D:/Kairos/runtime/production-finish-20261025/d5fc09160294416696baa1840156fb6b/`
  retains the original failed wrapper, `mount-order-adjudication-629d-v1.json`,
  the read-only installer diagnostic, and `retired-3652-task.xml/json`.

The final current-status/source closeout is retained under
`final-closeout-629d-v1/` in that evidence parent. Its snapshot preserves the
original status bytes/timestamps; it never arms a trader.

## Still required for real-money operation

- A real native upstream capture/composition using Text, Macro, Router and
  review, with qualified original-source provenance. The new model-call hook
  alone does not supply it. Research SIM envelopes are not LIVE envelopes.
- Authoritative EVEDEX account/economics/terminal sources and confirmed PROD
  signing/custody semantics. No support reply was present in the existing
  inquiry thread at this checkpoint. Existing verifiers continue to refuse
  incomplete evidence; possessing an API key is not qualification.
- Deploy and accept the complete current service, current-owner recovery,
  boot and alert path, then confirm explicit capital/loss limits and separate
  manual arming. The accepted non-trading data worker is not that service.
  The existing read-only Prometheus observer supports an exact CURRENT owner
  and status path, but does not establish signed source admission or Telegram
  delivery. The signed one-shot receipt dispatcher is not a live health poller,
  and R7's historical notifier/journal was not repointed. Current-owner alert
  transition/recovery/re-failure and delivery qualification remain open;
  no additional temporary notifier framework was introduced.

No profitability, professional-trader equivalence or permission to trade is
inferred from fixture success or the requested release date.
