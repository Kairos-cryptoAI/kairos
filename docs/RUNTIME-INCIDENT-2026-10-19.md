# Non-trading runtime incident continuation — 2026-10-19

This receipt concerns only the already-admitted separate non-trading epoch
`69893dc7b7c647f49967387e7efca9fb`. It does not adopt the legacy database or
queue, qualify trading, change frozen research, or authorize paid providers.

**Latest accepted result:** native non-trading recovery and the current-source
scheduled-action smoke passed. The same three epoch containers are running;
all five symbol watermarks advanced after acceptance. The chronological
checkpoints below retain earlier failures and stopped-state boundaries.

## Diagnosis before mutation

At the first October 19 inspection the same three admitted containers remained
stopped: PostgreSQL `9dbce00f1d68`, Redis `c8d57b7e6c22`, and serving worker
`2cfadb6fe53a`. The serving failure is unchanged from October 18:
`REDIS_RECOVERY_DEADLINE_EXCEEDED`, `FAILED_CLOSED`, `trading_started=false`.
The exact failed status SHA-256 is
`1e6029ba0db3436160cd65c5dad6e06ed8297e473f4d5f9b7927e507a0ce4a12`.

The frozen worker and current Deploy worker remain byte-identical, SHA-256
`5d9389b05b43ccf69ae8e2afff562a659d50a02f7ea00689078919e04ed1103b`.
Successful pending and new Redis reads already clear the recovery deadline.
All eleven existing transport tests pass. There is no reproduced timer defect
and no justification to enlarge the retry window or weaken fail-closed behavior.

Windows System events record an unexpected host restart: EventLog 6008, record
13786, reports an October 18 22:58:07 Moscow shutdown; Kernel-Power 41, record
13807, is timestamped 23:29:53 Moscow. These events do **not** prove the cause
of the earlier 22:55 runtime failure. Narrow System/Redis-log inspection for
22:45–23:05 produced no additional causal evidence. No raw credential values,
application command lines, or unrestricted host logs were inspected.

The boot task is Ready, not running; its last run at 23:31:08 Moscow returned 1,
with no scheduled retry. The previous binding still pins Deploy `12dbe9f`.
The binding, latch, frozen worker/config and historical acceptance remain
evidence, not files to rewrite to make the failure disappear.

## Recovery boundary

Deploy source remains the clean, trusted-signed main revision
`3b1aba77faa3471a846bcf553e54c371f74e22f4`. The 404 runtime-epoch offline tests
complete successfully, with two existing skips; no service is started by them.

The old live-PG backup/adjudication helpers are not admitted for this new
stopped-PG incident. The bounded cold-copy primitive already exists in Deploy.
The incident-specific operator must use it with read-only source mounts,
separate owned backup volumes, and separate physical and logical restore
clones. It must not start the source services merely to obtain a backup.

Complete, stable PGDATA including WAL is required. A copied crash-state cluster
may replay WAL on its isolated clone; that is not permission for `pg_resetwal`,
queue repair, source migration, or deletion. See the official
[filesystem-backup documentation](https://www.postgresql.org/docs/16/backup-file.html).
Row/sequence comparisons and
[pg_amcheck](https://www.postgresql.org/docs/16/app-pgamcheck.html) complement
the physical copy; they are not a claim to detect every possible corruption.

At this documentation checkpoint no new source restart or recovery PASS is
claimed. Execution requires reviewed, signed, one-shot admission and accepted
fresh clone evidence; any uncertain outcome must be retained, not retried.

## Accepted fresh backup and isolated restore

At 00:43 Moscow the create-only finalization
`0998a8edad4146d5b2ff7f81d52f5411` returned `PASS_BACKUP_ONLY`.
The source PostgreSQL, source Redis and source serving worker remained stopped.
Both separate PostgreSQL restore containers finished stopped, exit code zero.
No consumer, trading service, paid provider or legacy data/queue was used.

The retained PostgreSQL cold copy contains 1,038,920,646 bytes; the Redis cold
copy contains 24,631,866 bytes. Read-only content manifests before and after
restoration match both original volumes and both retained cold volumes.
Full source-resource metadata also remains identical, SHA-256
`35fd4a560be8d6ca4bbd991d5f7be5d130151af29966405f0a03c086b18c0f6e`.
Redis is backed up byte-for-byte here; its logical delivery recovery is not
accepted by this backup-only receipt.

The physical clone completed WAL recovery (`pg_is_in_recovery()=false`). A
separate fresh PostgreSQL volume then accepted the custom logical dump and
Timescale pre/post-restore procedure. All 32 public tables and three sequences
match the retained physical snapshot exactly, canonical SHA-256
`57964fac2f7ff112852ed756b3bdd5d993282c5a62713e0ed09ebb9b1a991a08`.
Both `pg_amcheck` runs exited zero, each with 227 heap and 385 B-tree scan
records and the requested heap/index cross-check options; no integrity error
was reported.

Two operator failures remain immutable evidence, not erased attempts: the
first wrapper rejected its own snapshot row shape after the physical copy;
the continuation wrapper rejected the logical clone's benign PostgreSQL notice
`extension "amcheck" already exists, skipping`. The finalizer did not rerun
PostgreSQL or waive arbitrary errors: it pinned the original raw captures,
accepted only that exact notice, compared all three snapshots and the dump,
and performed new read-only source/cold-volume fingerprints. Earlier failure
records and signed helper files were preserved.

Signed evidence is retained under
`D:\Kairos\runtime\runtime-cold-backup-20261019\finalize-0998a8edad4146d5b2ff7f81d52f5411`:

| Artifact | SHA-256 |
| --- | --- |
| `receipt.json` | `bc45fb09935807b653bb6277316ecfe95c6b47cc9b8306393400257e32c064c3` |
| `queue-mismatch-roster.json` | `965a3beaca45cb6f2aa8fa8f6c4556f3bb42aca9364b83566c7c4d2aaaf21f8a` |
| `finalization-receipt.json` | `16387f9e6108c6b161679c4335b26165dfb18ea0198d9af7d4a530918036de35` |

## Queue classification before recovery

The recovered SQL snapshot contains 13,205 already-published outbox rows and
13,200 completed inbox rows. Exactly five published messages lack completed
inbox confirmation. There are zero unpublished outbox rows, zero unresolved
inbox rows and zero execution order/effect rows. The exact five sanitized
message identities are sealed in the signed roster above.

This is **not** permission to republish, mark completed by hand, reset group
cursors/leases or ignore queue admission. The next admissible proof uses a
fresh isolated PostgreSQL/Redis copy, validates SQL/Redis publication identity
and runs only the existing consumer-only durable acknowledgement path for
those five messages. No source restart or source queue recovery is accepted
yet; the old failed status and boot binding remain unchanged.

## Accepted isolated five-message delivery proof

The separate queue clone `a71d093d` passed read-only SQL/Redis observation and
then the bounded consumer-only delivery rehearsal. The exact five sealed
messages were present in the Redis stream with matching canonical payloads and
publication receipts. None was in the pending-entry list: they were an
undelivered stream tail, not stale inbox leases.

The normal `DurableMessageBus` consumer committed exactly five new completed
inbox rows and requested their Redis ACKs. Outbox stayed at 13,205 rows; completed
inbox increased from 13,200 to 13,205. Generic `PASS_BOOT_REDIS_STATE` acceptance
then confirmed 13,205 publication receipts, one consumer group and zero pending
deliveries. The 13,206 stream entries include the already-admitted historical
duplicate; no new duplicate or publication was created by this rehearsal.

The other 31 table digests, all three sequences, history anchors/original
prefix, existing non-target inbox rows, stream contents and publication ledger
were preserved. Execution rows remained zero. Transport failures, recoveries
and pending replays were all zero. The clone-only consumer did run; the source
consumer and all three source services did not. Both clone data services were
stopped afterwards. Fresh final fingerprints again match the unchanged source
and retained cold volumes and the original full source metadata projection.

An earlier clone-only wrapper attempt `a71d093c` failed at its first Python
import, before any SQL/Redis operation: it selected system Python instead of
the runner virtual environment. That failure and those stopped clones remain
retained. A new signed, one-shot wrapper pins the exact failure and changes only
the worker interpreter/claim lineage; runner imports were independently checked
without data mounts. No dependency was downloaded and no timeout was enlarged.

The following actual proofs and their detached signatures are retained under
`D:\Kairos\runtime\runtime-cold-backup-20261019`:

| Artifact | SHA-256 |
| --- | --- |
| `queue-clone-a71d093d-observe/observe-proof.json` | `b67691fad374098db8989dff19f657831bbe5169c0b0bbd5bbd78a824c689626` |
| `queue-clone-a71d093d-rehearse/worker-rehearsal-result.json` | `2bc8696c8205e92202f231d7ad564c68caa7eeb0390835c71f46e99ea166f2c1` |
| `queue-clone-a71d093d-rehearse/rehearsal-result.json` | `d8b5dfd2e2f089c42011a5cdf9d0b7756b5fa0e67953f78032b318b70bb5d061` |

This accepts isolated delivery mechanics only. The source still has its five
unconfirmed messages and original `FAILED_CLOSED` status. A separately signed
source-specific admission must compare its full prestate to the accepted cold
backup and clone ledger before any normal ACK; generic clean-queue/boot gates
remain strict, and no serving restart or current uptime is accepted here.

`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL` remain unchanged.

## Accepted exact-five acknowledgement on the separate source epoch

The signed one-shot source adapter `source-five-ack-70f3122d` passed. Before
starting its consumer it matched all 32 table digests, three sequences, queue
classification and Redis stream/publication identity to the accepted cold
backup and signed clone observation. Only the same five sealed messages were
acknowledged through the normal consumer-only durable bus.

Outbox remained 13,205; completed inbox increased from 13,200 to 13,205. Native
`PASS_BOOT_STATE` and `PASS_BOOT_REDIS_STATE` both passed, with zero pending
deliveries, unresolved inbox rows, execution rows, transport failures,
recoveries or pending replays. All non-target data, history, stream contents
and publication ledger were preserved. There was no republish, cursor/lease
reset, manual completion, producer, serving worker or trading start.

The exact source PostgreSQL and Redis containers were stopped again with clean
exit codes. Their legitimate lifecycle changes produce a new full metadata
digest `2dbb3d883b1fc3993b70e332f63c3d80b1ff738504cf5d67127ac5a8bd28f69b`;
all non-lifecycle source metadata, legacy/standby metadata and retained cold
volume fingerprints were unchanged. Source volumes changed only through this
admitted database recovery/normal acknowledgement and clean shutdown, not a
claim of byte-for-byte source immutability after ACK.

Signed artifacts under
`D:\Kairos\runtime\runtime-cold-backup-20261019\source-five-ack-70f3122d`:

| Artifact | SHA-256 |
| --- | --- |
| `source-ack-handoff.json` | `3877b54bf2633fad9a8136b8c56bc1ea0de4fe527c2151dc27c80fc1ebbaf5ea` |
| `worker-result.json` | `6e44533f76418a0d7c5908daf214b0e03ebf328a220908b1aec62ea83e4659a1` |

This closes the exact-five queue mismatch only. The old failed serving status
and boot binding are still preserved; native serving recovery/current uptime
and a current-source scheduler handoff require separate evidence. All trading
readiness flags remain false and the strategy policy remains `REJECT_ALL`.

## Accepted native recovery and current-source boot-task handoff

The signed, reviewed correction `adjudicate_v3.py` completed run
`b35101e195164e629b4223b5e653ad9c` with
`PASS_ADJUDICATED_R7SQL_NONTRADING_BOOT`. Its native result is
`PASS_NONTRADING_EPOCH_BOOT`. Before any source start it rechecked the signed
post-ACK source metadata and both source/cold volume fingerprints.

The first adjudicator attempt stopped before source startup: it incorrectly
applied the full current R7 lifecycle schema to the historical receipt's
deliberately reduced status projection, which has no `source_fresh` field.
Its signed failure remains at
`adjudication-runs/33a066f69fff499085466bf87abb6b76/adjudication-failure.json`,
SHA-256 `90dfb698f604a5928615c6d36f4487bf60ed4c4ee7621e4be1f3a4f7b0da7f2f`.
The corrective operator pins that no-start failure and its claim. It validates
the historical status using the original accepted receipt contract at its own
observation time; fresh worker reports still require the unchanged strict R7
lifecycle and freshness gates. No missing freshness field was fabricated.

Native recovery then performed fresh backup-before and backup-after, each with
an independent disposable PostgreSQL restore, full 32-table/three-sequence
comparison and `pg_amcheck`. The existing bounded catch-up path preserved the
accepted history/prefix and queue state. Completed disposable restore containers
and volumes were removed normally; their retained dumps allow another restore.
The original cold backups, historical/failed clones and legacy data were not
deleted. Dump SHA-256 values are:

| Backup | SHA-256 |
| --- | --- |
| `epoch-history-bootbefore.dump` | `99fca01d76f7823f69d51317099cde8ef9559fc4f86aa379155f68c7a0d46716` |
| `epoch-history-bootafter.dump` | `724bad5b948e097314a4eded7c9d4d5030e57f866fbb75fa696e25db1c89528a` |

The same serving container `2cfadb6fe53a`, frozen worker and config were then
started normally. At acceptance it reported `RUNNING_NONTRADING`, fresh source
data, five advanced watermarks and zero pending outbox, unresolved inbox or
uncompleted publication rows. A later independent status read at 01:52:02 Moscow
again passed strict validation and proved all five watermarks advanced beyond
the recovery receipt, with zero Redis failures, recoveries or pending replays.
This separate epoch's normal bar producer/consumer did run; no trading,
execution orders, paid provider, or legacy consumer was started.

Only after native PASS, a binding generated by the existing native constructor
for trusted Deploy `3b1aba77faa3471a846bcf553e54c371f74e22f4` was staged and signed.
It binds all 83 tracked operator source files and 41 private inputs. The reviewed
one-shot task handoff archived the old `edf84cf...e95b` binding byte-for-byte at
`D:\Kairos\runtime\epoch-boot-r7sql-20261016\operator-archive-1700785207f74dceb62e428f6002ff38\binding.json`
and installed binding SHA-256
`20526fc7dccbe8784f1126b2ba96099b356cfe12732db4678583dd63f2b072d0`.
The full task XML changed only that binding-hash argument; executable, logon
trigger, principal, limits, `IgnoreNew` and zero automatic restarts were preserved.
The task remains enabled/Ready. The persistent epoch owner lease was unchanged;
`boot.active` was absent before/after handoff.

One actual invocation of the existing task at 01:51:25 Moscow returned exit 0
and `ALREADY_RUNNING_NONTRADING` on the current Deploy revision. It reused the
same three running containers without another worker or recovery run and
released only its own transient boot latch. Signed evidence:

| Artifact | SHA-256 |
| --- | --- |
| `adjudication-runs/b35101e195164e629b4223b5e653ad9c/adjudication-receipt.json` | `7cf2476bf57cebe8dc294fc05d23d65f8edbdc41be6077f7759b118939e2478c` |
| `current-r7sql-task-rebind-work/receipt.json` | `cbfaa766aa76e082d48f2693711da67d74c57768542c807d5bd54364cf5a9f07` |
| `epoch-boot-r7sql-20261016/runs/e6df0304770a4ec38645db1fbee700b4/boot-receipt.json` | `6c8ffcf96d7b4fe64b0282dc1416187507f37aeb5e27417a810006df89e8277d` |

The first two artifacts are under `D:\Kairos\runtime\runtime-cold-backup-20261019`;
the third is under `D:\Kairos\runtime`. Local restore and scheduled-action
acceptance are not an off-host recovery proof, a physical reboot test, a long
stability/soak result, or an explanation of the original transport deadline.
No timeout, generic fail-closed validator, frozen research or trading gate was
weakened. `TECHNICAL_PAPER_READY`, `PAPER_QUALIFIED`, `ALPHA_READY` and `LIVE_READY`
remain false; `STRATEGY_POLICY=REJECT_ALL`.
