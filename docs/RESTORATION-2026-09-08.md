# Restoration and DEV qualification — 2026-09-08

This is a dated operational receipt, not a replacement for frozen research or
the historical revision-specific technical gates in [READINESS.md](READINESS.md).
`PAPER_QUALIFIED=false`, `ALPHA_READY=false`, `LIVE_READY=false` and
`STRATEGY_POLICY=REJECT_ALL` remain unchanged. No paid API or venue mutation was
used during this recovery.

## Environment and source delivery

- All 14 repositories were checked on clean `main` against live GitHub refs
  before recovery. No branch, reset, global ownership-check bypass or lockfile
  refresh was used.
- Restored `uv 0.12.3` and CPython `3.11.15`; recreated the backtest environment
  from its existing lockfile. The previous environment is preserved under
  `D:\Kairos\runtime\environment-backups\kairos-backtest-20260908`.
- The user's restored GPG key signed a detached test and subsequent commits.
  The missing older private key was not substituted with unsigned commits.
- Docker Desktop runs again after preserving and replacing stale local socket
  directories left by the Windows migration. No factory reset or volume removal.
- Scoped, receipt-backed ACL/ownership recovery restored access to
  `D:\Kairos\runtime\paper-gate\secrets`. Existing secret values were not replaced.
- The actual Compose environment is `D:\Kairos\runtime\paper-gate\.env.paper`;
  every operation below explicitly uses project `kairos-paper-gate`.

Delivered independently signed changes:

- backtest `7796b38`: freeze a calendar-sensitive test's validation clock;
- backtest `dc59bca`: exclusive-process research supervisor, persistent phase
  status/logs, resume sequencing and Windows process tests;
- backtest `3623df3`: factual September forward coverage/recovery receipt;
- deploy `0b47147`: narrowly scoped secret-access restoration helper.

Backtest CI passed all three Windows/Linux jobs, including 557 Python tests and
Windows supervisor checks. A fresh local forward-only run passed 33 tests.
Deploy's 59 local unit tests and GitHub CI passed. Source-profile remote
validation and quiet Compose validation passed. These results are not a new
all-repository or authenticated execution qualification.

## Quarter-hour V2: resumed, not complete

The existing feature ledger was backed up to
`D:\Kairos\runtime\backups\quarter-hour-v4-pre-recovery-20260908.sqlite3`.
Deep verification accepted the original 51-batch chain:
`038f12ef8a7cfba60521e70aa621442bbe34160bc9eeeb4b79dc45a3ababffc5`.

The invalid ETH November 2021 ZIP and its original checksum were preserved in
`D:\Kairos\runtime\quarantine\eth-aggtrades-2021-11-20260908`.
The quarantined ZIP's actual SHA-256 is
`1f09919890ee7860602eef6e09c605cf7b4b93440afc303fecd7ece24fbf8087`;
its preserved official sidecar still specifies the replacement hash below.
The replacement official archive passed SHA-256 and ZIP CRC; its SHA-256 is
`a08d66be819d18961e2cc1676fba3c7fdb9bc09f73a67b4d0e864414103ece99`.
No accepted batch, source fingerprint, feature or exclusion rule was edited.

Recovery resumed at batch 52 with four workers and had reached **60/335** at
`2026-09-08T04:29:49Z`. Its supervisor remains active; quiet logs between large
monthly batches are not completion or failure. The authoritative status is
`D:\Kairos\runtime\research-recovery\quarterhour.status.json`.
After collection, the supervisor requires deep verification before the one V2
run and refuses an existing result. The conditional timing overlay remains
pending the parent result. No result or component acceptance is claimed here.

## Forward: restored retrospectively, still blind

Official daily archives for August 27 through September 6 inclusive were
retrieved **on September 8**, not during continuous online observation.
The all-five-symbol sync appended 79,200 bars and reached the exclusive
September 7 UTC boundary: 66,240 bars per symbol, 331,200 total.

Full integrity verification, performance-blind eligibility, unique pre/post
backups and restore-to-new-path recovery all passed. The primary ledger did not
change during the recovery drill. Six complete blind-period days are covered;
the duration gate is false and the sealed trade-count gate was not evaluated.
No PnL was opened. Full hashes and paths are retained in the backtest
`reports/regime-aligned-forward/WARMUP.md` September receipt.

The existing heartbeat has resumed, temporarily checking recovery every
30 minutes while limiting routine forward sync to the daily schedule. It must
not start a duplicate collector or notify repeatedly about unchanged state.

## Docker persistence and read-only observations

- PostgreSQL backup: `kairos-paper-gate-20260908T042435Z.dump`, 28,453,007 bytes.
- Backup SHA-256:
  `1f6e4ecc14923e7718819ff9e25ae49cdc35a96cfb4bd8d287b0e61bda11e7ee`.
- Backup and row-count manifest: `D:\Kairos\kairos-deploy\backups`.
- Real isolated restore drill passed: 12 migrations, 18 critical tables and
  all recorded row-count/sequence checkpoints. Execution orders, account and
  position snapshots in this pre-restart backup were empty; this is not proof
  of recovering a real protected DEV position.
- Redis, TimescaleDB, exporter, Prometheus and Grafana are healthy. Quant,
  Risk and Strategy Engine restarted; Strategy Engine reports an empty enabled
  strategy list. Execution Engine and canary controller were not started.
- Strategy Engine's stale image was rebuilt and recreated at the existing
  pinned SHA `fb7d406c6e1a3060f481b91668ff3bc23a1b4b0d`.

The new GET-only public EVEDEX check at `2026-09-08T04:30:51Z` failed the
five-asset gate. BTC and ETH had two-sided books; SOL, BNB and XRP lacked a best
bid/ask. BNB reported `trading=all` but `visibility=none`. These are current
observations, not reused August evidence or a 24-hour percentile measurement.
Raw non-secret report:
`D:\Kairos\runtime\research-recovery\evedex-public-20260908.json`.

Official repository DEV URLs/chain were rechecked against
[EVEDEX params.ts](https://github.com/evedex-official/exchange-bot-sdk/blob/master/src/params.ts).
The existing sidecar already documents and applies the fixed DEV `16182`
override because published SDK 1.2.11 embeds the older chain; no profile change
or permissive fallback was introduced.

## Explicit blockers and next gates

1. **Missing credentials:** restored PAPER secret directory contains only the
   five infrastructure secrets. `evedex_dev_api_key` and
   `evedex_dev_private_key` are absent; expected remote account remains
   `NOT_CONFIGURED_READ_ONLY`. The old Desktop `API.txt` path does not exist.
   Request the current local file path and dedicated DEV account, not keys in
   chat. Never fabricate or replace credentials.
2. **Venue liquidity:** all five required assets must have valid books before
   canary. Do not silently reduce the universe to BTC/ETH.
3. **Long runtime gap:** restored Binance producer state is behind current REST
   data and correctly reports `gap_waiting_for_backfill`. The current REST
   collector requests only its latest bounded window, so an outage longer than
   that window cannot heal through repeated tail polling. A resumable,
   contiguous long-gap recovery path with lossless durable delivery still needs
   implementation and tests; do not erase old bars/cursors or mark the gap fixed.
4. **Real-time ladder:** no accepted fresh 24-hour authenticated window, no
   armed 10-attempt/2-hour canary and no subsequent seven-day soak yet. These
   durations cannot be replaced by the local checks above. Bounded canary-runner
   completeness and its failure tests must be reviewed before arming.
5. **Research:** finish 335 batches and the one gated V2 evaluation. Trial 15
   remains frozen until both 365 days and 500 closed simulated trades qualify.
6. **Providers:** separate outstanding shadow requirements remain; existing
   cumulative reservations and OpenAI $12 / DeepSeek $1 / X $2 ceilings apply.

Code-delivery progress, research acceptance, DEV qualification and long-term
forward observation therefore remain distinct, incomplete milestones.

## Follow-up: archive read timeout and safe resume

At `2026-09-08T04:38:23Z`, the first recovery supervisor recorded `FAILED`
during collection after **63/335** committed batches. The preserved traceback
shows `TimeoutError: The read operation timed out` in the official archive
downloader's response read, not a checksum mismatch. V2 evaluation did not run.
The downloader removes its incomplete temporary file rather than promoting it
to the cache; accepted ledger batches remain intact.

The `2026-09-08T05:16Z` heartbeat confirmed the old supervisor and child had
exited, then deeply verified all 63 accepted batches. Their chain is
`424ddf11729fdab95dc092a5baa4c5a62e50ba2ef90a3e38c5adba0147dbbdf5`.
A new consistent SQLite backup was created before resuming:

- `D:\Kairos\runtime\backups\quarter-hour-before-timeout-resume-20260908T051807327781Z.sqlite3`
- SHA-256: `a5246ef9366b61dde6a65946cd6a24bea7e99df709e84b10bc55633dd56e240f`

The same exclusive-process supervisor restarted at `2026-09-08T05:18:41Z`
with four workers, resuming at uncommitted batch 64. No source, timeout policy,
checksum validation, frozen plan or accepted batch was changed. Original failure
logs remain under
`D:\Kairos\runtime\research-recovery\20260908T041744Z-5972`.
The shared status file now identifies the new run; no second collector was
started while the old one was alive.

The user also supplied the new local credential-file path,
`C:\Users\loval\Desktop\keys.txt`. A values-hidden check found provider labels
and a generically labelled EVEDEX credential, but no explicitly DEV-scoped
signing key/account. DEV scope confirmation and the missing dedicated
credentials are still required; the file was not changed or imported into the
trading runtime. The completed forward recovery was not repeated.

## Follow-up: serial recovery after a second transport timeout

The next run committed batches 64 and 65, then failed at
`2026-09-08T05:25:55Z` on another archive response-read timeout. There was no
new checksum mismatch and no V2 result. The next heartbeat verified that run's
processes had exited and deeply checked all **65/335** committed batches:
`4c04b5389cd38c56eb96f6c0b7cf37f84cc76b1e9b32a06c69e29d1e971c911d`.

Before the next resume, a consistent new backup was retained:

- `D:\Kairos\runtime\backups\quarter-hour-before-serial-resume-20260908T055140004690Z.sqlite3`
- SHA-256: `05da4bab4c822937ba1a2aec441f0eb371b14d430bb5cde7df3e7b99a28a4609`

Backtest commit `d810ce0` adds an operational `-Workers` option (1–4, default 4)
and records it in supervisor status. PowerShell 5.1 tests validate the default,
serial mode, rejected bounds, child exit propagation and exclusive locking.
The retry resumes batch 66 with **one worker**, reducing concurrent transfers;
this is a mitigation, not proof that concurrency caused the network timeout.
No frozen Python source, feature fingerprint, download validation or strategy
was changed. Failure still stops the run; retries are not unbounded or automatic.

## Follow-up: bounded archive preparation

Serial collection also encountered an archive response-read timeout, stopping
at `2026-09-08T06:06:51Z` after **68/335** committed batches. Reducing workers
alone therefore did not resolve the transport problem. All processes from that
run exited; the next heartbeat deeply verified the 68-batch chain:
`4afbda0548f76b12e047d1c223cb13a4876af2d5dec4cb205af67e51bc068ff4`.

New consistent backup before another resume:

- `D:\Kairos\runtime\backups\quarter-hour-before-staged-resume-20260908T062821601885Z.sqlite3`
- SHA-256: `46dec3823a4b781f7512f073d2bdf8873c4c18be87871743ed41e9fa6d833b61`

Backtest `f4db378` adds optional operational `-PrepareArchives`. This stages only
the next uncommitted monthly group using the official loader and full SHA/CRC
checks, then invokes the unchanged collector with a bounded batch count. Only
transport errors receive up to three attempts with 10/20-second backoff. A
checksum/CRC failure, missing archive or exhausted retry budget stops the run.
No accepted batch is replayed and the wrapper never writes the research ledger.
The original verifier/collector remains responsible for research fingerprints,
immutable data, exact gap exclusions and the sole ledger append path.

Ten local hermetic tests cover bounded retries, fatal integrity/404 failures,
successful retry/CRC scanning, read-only prefix selection, absent ledgers and
blocking collection after failed preparation or incorrect progress. Windows
PowerShell supervisor checks also passed. The new supervised run resumes at
batch 69 with `-Workers 1 -PrepareArchives`; V2 remains unexecuted until all
335 batches and the final deep check pass. Frozen research source is unchanged.

## Current research stop: inconsistent official XRP source

**Quarter-hour is stopped at 79/335, not running.** At
`2026-09-08T07:01:44Z` the supervisor recorded a fatal integrity error for
uncommitted XRPUSDT April 2022 (batch 80). This is not another retryable timeout:

```text
monthly aggregate-ID gap is not reproduced by official daily archives:
XRPUSDT 2022-04 270785088->271148868
```

The `07:31Z` heartbeat did not restart collection. Deep verification passed all
79 accepted batches, chain
`7a7f4b5ec9c8f8769bd8afbb2411b50b0c7ba4a4c1e2dbb83ef9b065eadb1fed`.
All prior worker/supervisor processes exited. A new consistent backup is saved:

- `D:\Kairos\runtime\backups\quarter-hour-source-conflict-20260908T073231361608Z.sqlite3`
- SHA-256: `198dbc25910b712eea31e32d61bfe456bd7e73c0238b70b6a6331b0ff985dcf1`

An independent read-only scan of the cached ZIPs found the missing interval in
the official daily files. SHA-256 matched each preserved official sidecar and
full ZIP CRC passed for every file listed below:

| XRP archive | SHA-256 | Rows within inclusive IDs 270785088–271148868 |
| --- | --- | ---: |
| monthly 2022-04 | `746f952babe9a5dee6af026a5757593276d379d038d9778e17a059cdae441804` | 1 |
| daily 2022-04-01 | `762603ffc5411506d1734bfe79c7cca5e73f935b3a006a89cc23a681686a08b2` | 194,211 |
| daily 2022-04-02 | `7c689c68c229d53857c3a53d9c1fb067373f7156be06629dad447780f365b526` | 169,568 |
| daily 2022-04-03 | `f9d77555755aee5f1b24e553782e4ec4c61fba9ce8afc929d800d7922c603594` | 1 |

April 1 contains IDs `270785089..270979299`; April 2 contains
`270979300..271148867`: together 363,779 records absent from the monthly file.
The monthly file instead reaches ID `271148868` at timestamp `1648944000135`,
which matches the first matching April 3 daily record. The fresh official
monthly `.CHECKSUM`, retrieved at `2026-09-08T07:33:36Z`, still specifies the
same monthly SHA above. Download corruption is therefore not the diagnosis.
All source ZIPs/sidecars and the failed run logs are retained unchanged.

Per the approved plan, **do not replace monthly data with daily data, skip batch
80, loosen gap rules or rerun the collector against the unchanged source**.
V2 has not run; the timing overlay remains pending incomplete parent evidence,
not `NOT_RUN_PARENT_COMPONENT_REJECTED`. Resolution needs a validated official
source correction or an explicitly approved new research plan. No strategy
performance was opened; forward evidence and all trading permissions remain
unchanged. Other independent restoration work may continue.

## Runtime long-gap recovery: code delivered, data repair running

Independent of the blocked quarter-hour research, quant commit `68e917b`
implements an explicit offline repair path for outages beyond the live REST
window. Deployment commit `f2cd504` pins that exact source in both base/PAPER
manifests and images, with a wrapper restricted to `kairos-paper-gate`.
Frozen research code, plans and dependency locks were not changed.

- Quant Windows local gate: 171 tests, lint, formatting, mypy and Bandit pass.
  Quant CI passed Windows 3.11 and Linux 3.11/3.14.
- Deploy: 59 validator tests plus offline PowerShell preflight checks pass;
  remote lockfile validation and the full deploy CI/image builds are green.
- Docker integration used only isolated database
  `kairos_gap_drill_202609080001`. Lost ACK after a durable commit, restart,
  duplicate publishing and competing producer acquisition were exercised.
  Result: exactly 10 audit rows, 10 outbox rows, zero duplicate rows, and the
  second producer was rejected by the PostgreSQL lease. No real market/order
  fixture was inserted into the primary database during this test.
- The live quant producer and repair job now share the exclusive database
  producer lease. The Docker wrapper additionally rejects any active quant,
  strategy, risk, execution or canary consumer and mismatched source images.
- Repair checks a complete persisted history prefix and compares two identical
  full REST pages, including overlap with the persisted anchor. New bars use
  the existing canonical `ClosedBarEventV1` IDs and atomic audit/outbox publish.
  Restart resumes from committed history; no cursor/Redis entry is erased.

Before applying repair, quant, Strategy Engine and Risk Manager were stopped.
Redis, TimescaleDB, exporter, Prometheus and Grafana remain running. Execution
and canary were never started. This planned data-repair outage is **not** a
qualifying 24-hour observation interval.

Fresh primary PostgreSQL backup and successful isolated restore drill:

- `D:\Kairos\kairos-deploy\backups\kairos-paper-gate-20260908T082154Z.dump`
- 30,246,065 bytes; SHA-256
  `5c4e436ca1a78ddcaac5b716ac8250f1232a9b2821d37e0f4be995864793f187`.
- 12 migrations, 18 critical tables and manifest checkpoints verified.

The real repair job started at `2026-09-08T08:24:01Z`, parent PID `28380`,
container `kairos-gap-recovery-36d35a9d94774ca1b1980b7e69ccf1e7`.
It reported **84,435 bars required** across the five symbols, with an explicit
150,000-bar ceiling and exclusive end `2026-09-08T08:20:00Z`.
The immutable end boundary is `1788855600000` milliseconds.

Logs (progress, retrieval times and terminal state; no PnL):

- `D:\Kairos\runtime\long-gap-recovery-20260908T082401Z.out.log`
- `D:\Kairos\runtime\long-gap-recovery-20260908T082401Z.err.log`

At this receipt the job is **running**, not yet accepted as repaired. Do not
start another recovery or restart consumers until its process/container and
terminal logs have been reconciled. On success, verify the all-symbol durable
boundary, uniqueness/continuity and outbox drain, then restart only the stopped
read-only services with the pinned images and verify fresh gap-free operation.
If it fails, preserve partial committed progress and diagnose before resuming.
No paid API, trade, signing key, alpha permission or LIVE state changed.
