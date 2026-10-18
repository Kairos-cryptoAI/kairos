# Non-trading runtime incident continuation — 2026-10-19

This receipt concerns only the already-admitted separate non-trading epoch
`69893dc7b7c647f49967387e7efca9fb`. It does not adopt the legacy database or
queue, qualify trading, change frozen research, or authorize paid providers.

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

## Queue admission still blocks ordinary startup

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
