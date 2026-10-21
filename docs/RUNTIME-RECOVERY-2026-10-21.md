# Fresh non-trading runtime recovery — 2026-10-21

This is a bounded recovery receipt, not a LIVE/PAPER or strategy approval.
The legacy database/queue and the failed `9e489055` generation are preserved.
No real orders, transfers, paid providers or research campaigns were started.

## PostgreSQL: fresh backup and native isolated restore passed

Run `0dc48e40b54f474f954b929503b162a4` created a fresh custom-format backup
and restored it into a new, isolated PostgreSQL clone. All 32 public tables and
three sequences match the source; the final source projection is unchanged.
`pg_amcheck` succeeded. The clone is stopped and retained, not deleted.

- Backup: `epoch-history.dump`, 52,435,109 bytes, SHA-256
  `2558d2f5d913dad0fa7612d1c445a8449eda99fe6b48479731f6df81ff3ddd61`.
- Source, restored and final-source projection SHA-256:
  `40a7db4b53df66428762547b5756ac905a42ec8079580d13fdeff4be628710c8`.
- Receipt SHA-256:
  `58e000acabeb74df949cf18626b5e574815e97c4cc64247c8de2b8a930863e8c`.
- Detached signature SHA-256:
  `87adbac2f26629d445f946168fcef10500b42795c63876a239387531e07a8bbe`.

The receipt is retained at
`D:/Kairos/runtime/r7-recovery-20261021-a8f2da2efb4845728cd1c2ffa0163915/pg-execution-0dc48e40/pg-recovery-receipt.json`.
Its detached signature verifies against the configured trusted GPG fingerprint.
The backup hash was independently recalculated after completion.

The isolated clone uses `10.254.251.0/28`; fresh host-route and Docker-IPAM
checks excluded the occupied older ranges. No old network was removed or reused.

## Queue: ten incomplete deliveries remain; no blind ACK

The preserved SQL snapshot contains 14,135 outbox rows and 14,125 completed
inbox rows. `published_without_completed=10`, `pending_outbox=0`,
`unresolved_inbox=0`, and no missing publication audit. This is not the old
exact-five state and must not reuse that historical recovery authorization.

PostgreSQL backup equivalence preserves this state; it does not resolve it.
Fresh Redis AOF/native replay and joint clone processing of the exact ten
deliveries are required before a new non-trading runtime generation. No source
ACK, cursor/lease reset, reconciliation repair or consumer start is implied.

## Retained failed preparation attempts

The first read-only capture completed its projection but failed while writing
a service JSON (bytes were passed to a JSON serializer). The second attempted
PG admission refused a raw-file versus canonical-JSON digest mismatch before
dump/clone creation. Both are retained, not overwritten or represented as
successful recovery. The accepted fresh run above uses the corrected,
reviewed operator and a separate identity.

## Redis: byte-preserving AOF backup accepted

The independently verified backup contains three files, 20,475,278 bytes in
total. Saved pre-copy, post-copy and later source metadata/inventories match;
every copied file matches the source SHA-256. No Redis queue command, ACK,
BGSAVE, source consumer, ACL or database change was issued by this backup.

Receipt:
`D:/Kairos/runtime/redis-aof-backup-20261021-90d84c/independent-validation-03/backup-receipt.json`,
SHA-256 `4dd0e77f971d8724160528521caa57fea2059b83c55fde11e709788d234b1fe3`.
The detached signature verifies against the configured trusted fingerprint.
The accepted bytes remain in `attempt-02/aof` beside that validation directory.

The first copy attempt refused a metadata comparison; its exact cause was not
established. The second preserved before/after observations but its old-format
manifest parser refused Redis's incremental `startoffset 0` field. Both failed
attempts are retained unchanged. A separate tested validator accepted that
native manifest field, checked sequence/type/file-set consistency and independently
verified saved/current/copied bytes; no failed receipt was rewritten as PASS.

This is backup integrity, not a native Redis restore or joint replay acceptance.

## Not yet accepted

Redis/joint queue recovery, fresh application credentials, a new runtime
generation and current running-health/monitoring evidence are separate steps.
The old failure remains recorded; the PostgreSQL PASS above does not mark the
overall runtime restored. All readiness flags remain false; policy `REJECT_ALL`.
