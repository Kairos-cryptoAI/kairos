# Kairos - non-trading runtime incident and short engineering closeout, 2026-10-12

Subsequent observation: the accepted R4 process later stopped with
`FAILED_CLOSED` / `TimeoutError` at 07:57:50 UTC. The acceptance below describes
its earlier backup/restore/running snapshots; it is not a current running-state
claim. See the [notification/runtime follow-up](NOTIFICATIONS-EVEDEX-2026-10-12.md).

## Accepted scope

The owner requested repair of the failed runtime and completion of independent,
short engineering work, without touching the old database/queue or starting
trading. The separate CLOSED_BAR epoch is
`69893dc7b7c647f49967387e7efca9fb`; its database is
`kairos_epoch_69893dc7b7c6`. This is not full application, provider, venue,
strategy, PAPER, alpha or LIVE qualification.

The create-only R4 native continuation is accepted as
`PASS_NEW_NONTRADING_GENERATION` at signed Deploy
`0c0810015f877adaf47a3da2786a0a6fbdefe575`, at 05:44:35 UTC. Its receipt SHA-256
is `0a7a621991a328d9fedb8c203cc0da53a835e0a3c02f6549bacf4ef650dba03f`;
the detached signature has been independently verified with the trusted key.
The new serve ID is
`1f9da09121bd509c5aa1d1a698c98334bc1e5378ee4978b65d98885cff19e199`.

The original PostgreSQL and Redis remain stopped with unchanged identity,
volume and security metadata. No connection, migration, recreation, replay,
acknowledgement or cursor/lease reset targeted that legacy database or queue.
Only the separate new epoch processes its own public closed-bar messages;
no trade or paid provider call was made in this incident recovery.
Original/R2/R3 failed processes, latches, receipts and backups remain retained,
not restarted, removed or relabelled as successful.

## What was actually corrected

The original SOL confirmation refusal exposed unsafe sibling-task teardown.
Workers now cancel and await siblings before closing shared resources, and
preserve the primary operational exception even if cleanup itself fails.
Only the exact mutable, unpublished `CONFIRMATION_COMPARE` case receives
bounded confirmation retries; an unchanged anchor and zero appends are
mandatory. There is no publication retry or integrity bypass.

R2 first passed native recovery, then stopped with a generic `TimeoutError`
at 04:28:21 UTC. Its underlying cause remains **unconfirmed**. It is not
attributed to Binance or declared fixed. New workers record bounded,
allowlisted traceback locations without exception messages, locals, private
paths or credentials, so a future refusal has better evidence.

R3 passed both native restores and started a healthy process, but its final
metadata guard stopped it. Independent comparison of the two preserved,
sanitized standby Docker views proves that only ten health-check `Start` and
`End` timestamps changed. The correction ignores only those bounded clock
fields after complete schema/identity validation. Health status, failing
streak, log count/order, exit codes, output, mounts, networks, resources and
security settings remain guarded. An arbitrary failure or mount-order-only
change cannot authorize the separately latched R4 continuation.

R4 admission binds the exact R3 signed source, failure/status/operator hashes,
the retained original latch and exact stopped container with exit 137. The
failed R3 attempt is not retried; R4 has a distinct create-only work directory,
latch, serve name and exact-owner disposable restore suffix.

## Fresh native backup, restoration and data plane

Both fresh backups independently restored all 32 public tables, full row
digests, sequences, five bar chains and the existing queues. Supported
whole-database heap/B-tree integrity checks passed on both isolated clones.
Only verified disposable restore containers/volumes were removed; the dumps
and all failed/unverified earlier attempts are retained locally.

| Backup | Bytes | SHA-256 |
| --- | ---: | --- |
| Before | 42,168,654 | `9e97b3447db4db76dfaea59eb7c33844aaa00cf902bc8e6db9ea6fbba9039756` |
| After | 42,188,890 | `9165e61101b92a26c4ec8681273014f85f2bb0921d9b2ee103270103c6f81858` |

Audit-only catch-up added 165 plus 20 bars, from 335,559 to 335,744 rows before
serve. Existing 4,651 outbox and 4,651 completed inbox rows, sequences and the
original 173,164-row prefix remained unchanged. Historical catch-up was not
republished. The full Redis stream/publication/inbox proof matched before
and after catch-up, with zero pending deliveries or unresolved publications.

R4 then demonstrated fresh advancement of all five BTC/ETH/SOL/BNB/XRP
watermarks and 4,670 completed inbox rows at acceptance. Counters are timed
snapshots, not fixed capacities. There were no pending, unresolved or
uncompleted publications and no trading rows. The only running epoch services
are its PostgreSQL, Redis and CLOSED_BAR worker on a private bridge with no
published ports; the separately existing test standby is left untouched.

## Monitoring and dependency maintenance

Signed Persistence `ea0c73395352f71da196270fe16659f1f0298a52` adds an explicitly
owner/path-bound, read-only status-file observation to the existing exporter.
It rejects oversized, ambiguous, linked/reparse, wrong-owner, malformed,
future-clock or non-fail-closed records, exposes fixed status labels and keeps
heartbeat staleness separate from the underlying failure state.
The actual retained R2 status parsed as `failed_closed`, stale; the actual R4
status parsed as `running`, fresh. These probes opened no database/Redis
connections. Pinned offline Promtool configuration and alert fixtures passed.
This qualifies code/configuration and native status parsing, not a running
metrics collector, external delivery or Telegram receipt.

All eight dependent service `pyproject.toml`/`uv.lock` pairs and current Deploy
source projections now pin that Persistence revision. Their locked local
suites passed 1,940 tests in total; Persistence passed 552, with one explicit
skip and 34 deselected integration tests, plus scoped lint/format, type and
Bandit checks. Hosted integration gates provide their separate native proof.
Compatible current locks use `multidict==6.9.1`; Execution's existing CCXT
constraint still requires 6.7.1, so it was not forcibly overridden or downgraded.
This is preventive dependency maintenance, not a demonstrated exploit fix.

The frozen runtime wheel bundle, Core/LLM/Backtest research identities,
Trial 15 and quarter-hour V2/V4/V5 evidence are unchanged. Updated current
engineering dependencies do not retroactively change the native worker's
frozen dependency identity.

## Guarded launch and current source verification

Final boot source is signed Deploy
`0427f7cf1e1cd70f2ddd05b80b4d7d6219736412`. R4 has its own hash-bound root,
lease and `Kairos-NonTradingEpoch-69893dc7b7c6-Boot-R4` task; it admits only the
accepted R4 receipt and exact three existing resource IDs. Binding SHA-256 is
`7075097ecdc7a257ea390a0632bb9fa76200402add96ea515a0d15b133935a98`.
The current-user task remains Interactive/Limited, Hidden, logon-delay 30s,
`IgnoreNew`, zero automatic retries and 75 minutes maximum. It waits for the
existing Docker engine, not starts Docker or a headless service.

Both actual task dispatches returned `ALREADY_RUNNING_NONTRADING`, task result
0, at 05:52:24 and 05:55:23 UTC. They inspected the already-running epoch;
they did not recreate, replay or restart it. The serve kept its exact ID and
05:43:08 startup timestamp with restart count zero. The obsolete original
task was disabled only after the new task passed; its complete exported
definition and signature remain retained, not deleted. The next automatic
OS-logon trigger and the R4-specific cold stopped-resource route are not
claimed as newly exercised native proofs; their guarded code has offline
tests and the separate native recovery evidence above.

Windows Python 3.11 and 3.14 each passed 848 of 855 tests, seven explicit
skips, zero failures. Scoped Ruff check/format and diff checks passed.
The initial R4-serving source's hosted CI had two host-dependent admission
fixtures: local files masked the missing mocks. Production guards were not
weakened; hermetic synthetic evidence now proves exact admission and rejects
wrong claims, failure/status/operator hashes, signed source, R2 receipt/status
and latch identity, with no filesystem or subprocess fallback.

All five exact final-source hosted gates passed, without retries:

- [Deployment CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38209770308).
- [CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38209770769).
- [Installed PG/Redis composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38209770263).
- [Current-source Docker gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38209835809).
- [Full-path SIM gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38209835729).

The current engineering manifest pins all actual signed component HEADs,
including final Deploy and Persistence. All fourteen `main` HEADs were also
checked against fresh remote `main` advertisements and local `origin/main`;
that is source identity, not fourteen clean checkouts. Meta's preserved
adaptive WIP and the old two service directories remain untouched and block
whole clean-release admission. The
[signed scoped receipt](receipts/runtime-incident-20261012.json) distinguishes
native worker source, boot source, timed observations and acceptance limits.

## Boundaries that are not independently closed by code

- Complete live Text/Macro/Router/review/Risk/provider composition remains
  distinct from installed fixtures and the accepted CLOSED_BAR data plane.
- A remote host/off-host destination, custodianship, retention, RPO/RTO and
  cost choices are missing. Restic preparation is not off-host restore proof.
- Actual Telegram delivery is not accepted: the prior exact chat check was
  `CHAT_NOT_FOUND`; token rotation and bot access to the intended chat are
  separate protected operator steps. No new message or secret read was made.
- EVEDEX DEV/PROD identity, dedicated credentials, five-symbol liquidity,
  elapsed availability/soak, protected canary and TCA require their own gates.
- Production managed custody, DEV/PROD separation, security admission,
  capital/day-stop limits and manual arming remain separate owner decisions.
- Strategy/economic research needs its own sealed blind gates and elapsed
  observations; historical fixtures do not replace them. No blind PnL is
  disclosed and no trade frequency or return is promised.
- UI/UX remains deferred at the owner's request. Preserved adaptive drafts
  and the two old untracked service directories remain unaccepted; whole
  clean-checkout release admission is not waived.
- Core's exact pinned CodeQL run
  [37371496144](https://github.com/Kairos-cryptoAI/kairos-core/actions/runs/37371496144)
  has overall `failure` with both analysis jobs `cancelled`; no current-SHA
  scan pass is inferred from older scans or a successful project CI. Its
  one requested retry was refused by GitHub as non-retryable.

`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`; strategy, execution and paid
provider calls remain OFF. No real trade follows from these engineering
receipts.
