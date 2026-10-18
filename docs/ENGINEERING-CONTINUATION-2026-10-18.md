# Bounded recorder/profile implementation — 2026-10-18

Scope: two existing-component engineering gaps, without trading, paid providers,
long observation, primary/legacy changes, or readiness promotion. No strategy,
frozen Trial 15/V2/V4/V5 evidence, evaluator or user-interface work was changed.

## Implemented

- Execution `858aead208067858aa8790427d933850eecf8446` (following signed
  implementation `11a5637fdd55f64938bf8233dc570a1b014803d2`) connects Quant's
  existing paired-book parsers/comparison to the existing PostgreSQL canary
  recorder. All five instruments, failure denominator, actual DB time, immutable
  sample chain, 24 actual hours and repository admission thresholds are retained.
- The concrete health reader performs SELECT-only scoped run/instance checks,
  requires a complete recent five-symbol closed-bar chain and no execution/claim
  rows, then independently reconciles five authenticated account GETs against the
  exact remote identity and a flat account. Unknown/stale evidence refuses; it is
  never converted into zero gaps/drift. No network request holds a SQL transaction.
- The explicit CLI has no default target/credentials, no migrations/consumer starts
  or order/signing method. Its independent code/config, local host/port, database
  name and instance checks precede observation writes. One session advisory lock
  prevents a duplicate recorder. Cancellation does not certify/restart a run.
- Deploy `c8f73ec61ab1148d4fad3df91980a82808b451f6` enables both existing
  `KAIROS_CANDIDATE_REQUIRE_TEXT_CONTEXT` and
  `KAIROS_CANDIDATE_REQUIRE_MACRO_CONTEXT`. Its validator rejects omitted, false
  and empty values. Current runtime/PAPER/engineering gate source projections and
  affected uv locks match Execution; historical Git revisions/receipts remain
  untouched and do not automatically transfer their acceptance to this release.

The PostgreSQL guidance influenced the bounded pool, short transactions and
separation of external I/O from persistence. This is not a schema/index rewrite.
See the implementation's `docs/READONLY_RECORDER.md` for explicit setup and limits.

## Bounded checks

Local Windows Python 3.11.15, freshly installed locked dependencies with all extras:
619 regular tests pass, 46 integration cases are deliberately excluded from that
regular command. All 33 recorder/health/CLI-focused tests are included. Ruff,
format, Bandit and mypy over all 36 execution source files pass.

A separately owned disposable TimescaleDB fixture passes the actual SQL test:
1,440 closed-minute roster per required symbol, missing-XRP refusal denominator,
persisted exact sample replay/hash-chain and refusal of short-window certification.
It does not compress 24 hours or establish any real venue/provider fact. No legacy,
R7 or trading database/queue was used. Initial local attempts exposed an old
developer environment and an interrupted fixture; the final locked/isolated
results, not those failed attempts, are the acceptance scope stated here.

Deploy's Windows Python 3.11 suite passes 1,024 tests with eight existing skips;
eleven source validators pass and rendered base Compose passes strict validation.
At the exact Execution revision, hosted [CI](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/39164266835)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/39164266559)
are green, including the guarded PostgreSQL job and all-adapter checks.
The first implementation revision's base-environment type check failed because
Quant is optional; the separate signed correction handles absent/untyped optional
imports without weakening runtime or repository admission.

At the exact Deploy revision, the installed
[Text/Macro/Router/review/Risk composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39164300892)
and [current-source REJECT_ALL gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39164301000)
are green. These remain engineering fixtures, not real-provider service acceptance.
Deploy [CI and runtime/PAPER image builds](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39164300893),
[full-path simulator gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39164300806)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39164301196)
are also green at that same revision. No built image was deployed or started.
The temporary synthetic PostgreSQL test container was stopped and removed after
the test; test source and result reports remain, with no user data removed.

Final source-identity follow-up: Execution
`f5c100f2046e8352974bf6e659747757bd136e85` only shortens a synthetic exception
fixture that the unchanged path-only credential scanner classified as a bearer
token pattern. No real credential was present and the scanner was not relaxed.
Deploy `3b1aba77faa3471a846bcf553e54c371f74e22f4` projects that exact follow-up;
neither recorder runtime code nor boot/worker code changed in these follow-ups.
The final Execution [CI](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/39164599377)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/39164599181)
pass, as do the final Deploy
[installed composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39164632622)
and [current-source REJECT_ALL gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39164632618).

## New runtime incident, not hidden by source acceptance

The existing frozen R7 worker stopped at **22:55:18 Moscow**, exit 1, no OOM.
Its retained status at 22:55:10 is `FAILED_CLOSED`, `EpochError`, reason
`REDIS_RECOVERY_DEADLINE_EXCEEDED`, at `RedisStreamTransport.subscribe`, worker
line 2173. `trading_started=false`. Worker SHA-256 remains
`5d9389b05b43ccf69ae8e2afff562a659d50a02f7ea00689078919e04ed1103b`.
The frozen worker and current Deploy worker are byte-identical; this continuation
did not change either. The evidence identifies an exhausted bounded Redis
recovery window, **not a proven Redis-server outage or a proven timer defect**.

Later read-only Docker inspection found the admitted PG and Redis stopped at
**23:32:09 Moscow**. No restart cause is inferred from matching timestamps.
Neither was started, recreated or queried by this continuation. The unrelated
standby was left alone. Only our separate synthetic SQL fixture was started.

The previous native recovery/scheduler PASS is retained as dated historical
evidence, not current uptime. No failed latch/status/receipt, frozen worker, boot
binding or task action was replaced. The boot binding still pins Deploy
`12dbe9fd9d596bd47718d5e606bfa939baabf15f`, not this engineering source update:
it must not be called or rebound merely to hide the incident. A separately
adjudicated guarded recovery/source binding is required before resuming runtime.

## Not completed by this change

No real 24-hour recording, authenticated account pairing qualification, DEV order,
canary, seven-day soak, paid model/feed call, real-provider deployed composition
or LIVE activation was performed. EVEDEX's empty required books remain an external
blocker. Strict profile configuration is not proof of real feed/model quality,
durable Text dedup across restart, or accepted historical budget adoption.

`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL` remain unchanged.
