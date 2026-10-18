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

`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL` remain unchanged.
