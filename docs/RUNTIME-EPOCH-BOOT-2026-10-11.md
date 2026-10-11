# Kairos - guarded non-trading epoch boot recovery, 2026-10-11

## Scope and acceptance

The owner authorized finishing the existing isolated non-trading runtime after
a PC restart, without touching the old database or queue or enabling trading.
The signed native result is `PASS_NONTRADING_EPOCH_BOOT`, followed by an
actual same-task `ALREADY_RUNNING_NONTRADING` check. This accepts only the
CLOSED_BAR epoch `69893dc7b7c647f49967387e7efca9fb`, not whole-project,
strategy, model, venue, PAPER or LIVE admission.

Final recovery source is signed Deploy
`70a0ed277ba05a950874c0b85ed8ecb4a8d4d1c8`. The
[sanitized signed receipt](receipts/runtime-epoch-boot-20261011.json) records
the exact scope, native hashes and boundaries. Old PostgreSQL/Redis and their
queue remain stopped and untouched; trading and all readiness flags stay OFF.

## Windows launch and exact source

Signed Deploy `2c03a8bb45052f3d58ac7d6195d0f54448b12bc0` adds a guarded
current-user logon launcher and frozen binding. The task uses Windows
PowerShell 5.1, Interactive/Limited, Hidden, a 30-second logon delay,
`IgnoreNew`, zero automatic retries and a 75-minute total task bound.
It waits at most ten minutes for the existing Docker Desktop Linux engine;
the contained Python controller has a separate one-hour bound. Python is
created suspended, assigned to a kill-on-close job, then resumed.

The first task dispatch stopped before a native runtime run or container
start. The Python installation's logical Roaming AppData alias is virtualized
inside packaged Codex and absent in an ordinary Windows task. The fixed
binding pins its physical package LocalCache installation. The same Limited
task subsequently passed binding, host boot ID, read-only engine ping,
contained Python exit/import, private input hashes and signed-source checks.
No SQL/Redis commands or runtime starts occurred in this preflight.
The physical path is host-specific: removal or alteration requires reviewed
requalification, not an automatic fallback to another interpreter.

Unused prior bindings, task definitions and failed preflight receipts were
preserved in separate local archives. Owned one-shot diagnostic tasks were
removed after preserving their definitions and receipts. No other task was
changed. Installation of the final boot task is idempotent.

Reviewed failed-run binding SHA-256:
`62b3ca1224b740683b2f5f59ea1bc1c69bdd739cfdc08abea80aaa4ca2131fc0`.
It pins the source bytes, accepted parent receipt, existing three container
IDs and admitted private input hashes, with a verified detached GPG signature.
The accepted original bar worker remains the same existing container and
immutable snapshot; the boot controller does not recreate or upgrade it.

Launcher-source Windows Python 3.11/3.14 each ran 734 tests: 728 passed, six explicit skips,
zero failures. Native Windows tests include exact quoted arguments containing
spaces, quotes and trailing backslashes and task identity equivalence by SID.
Ruff check/format passed for the changed Python files. A broad repository lint
invocation also exposed 117 pre-existing findings outside this change; those
were not silently fixed or presented as a clean whole-repository lint result.
Meta static gates passed on Windows PowerShell 5.1 and PowerShell 7.

All five launcher exact-source Deploy `2c03a8b` hosted gates passed:

- [CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38149635876).
- [CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38149636051).
- [Installed composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38149635877).
- [Current-source Docker](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38149637725).
- [Full-path SIM](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38149641721).

Meta manifest pin `36a391b6ff1ccf233f7f9066eff5f0c74be7dc71` passed
[validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/38149771756)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos/actions/runs/38149771829).
Hosted disposable fixtures do not replace actual native recovery evidence.
An earlier CI failure was corrected by isolating the Windows platform test
constant instead of changing global `os.name`; an earlier registry HTTP 500
was resolved by rerunning only the failed hosted image-build job. These
previous attempts remain historical evidence, not current-source successes.

## Native recovery evidence

The final native result, fresh backup/restore proofs, preserved queue/history
digests and natural five-symbol advancement are recorded below.
The durable exclusive latch prevents overlapping recovery or blind retries.

The earlier native run `51d80affec9c459c8122088df15677f6` stopped in the
read-only pre-backup state check, before catch-up or serve. Its original
failure receipt/latch/resources are retained, not relabelled or resumed.
It incorrectly expected zero rows in the database-identity singleton which
schema migration 014 intentionally creates. Exact read-only counts showed
330,239 audit rows, 2,220 outbox and 2,220 inbox rows, 18 migrations, one
database identity row and zero rows in all other controlled public tables.

The identity's digest
`ba22f0bf5a60970ce0553e4c307106244912c7764e0f355a1955be65898e6e38`
matches the independently accepted continuation-05 restore receipt. The
corrected guard admits only that exact one-row digest, never a blanket
exception for canary tables. Missing/extra/altered identities and any canary
session, arm or order remain rejected. The corrected test fixture pins the
accepted digest independently of the production constant.

The second native run `66f342dc45c5439cbcffeef318e38bcd` passed the full
read-only boot-state check, then failed before creating a backup with
`PRIVATE_CREATE_ONLY_EPOCH_DUMP_REQUIRED`. The inherited dump helper's exact
filename list omitted `epoch-history-bootbefore.dump` and
`epoch-history-bootafter.dump`. The correction admits only those two names,
retaining create-only, exact directory/owner/database and bounded-job guards.
Functional binary-stream tests cover every admitted filename and reject a
duplicate file, unknown filename, foreign database or foreign directory.
The failed run, latch and scheduled-task definition are retained in a
separate recoverable archive; it is not silently retried or relabelled.

A further pre-run review found missing disposable-volume preparation in
both boot backups. Each now requires the exact restore container/volume to
be absent, creates an owner-labelled volume and initializes only that new
volume for UID 70 before restore. The first verified clone is removed before
the second fresh clone is created. Existing resources block admission and
are never reused or removed by this preparation path. Tests enforce both
create/init/restore sequences and refusal before mutations on a conflict.

The third native run `e1e4a133a0f04cdd9ee915720ea9d598` passed the full
32-table read-only state proof, fresh backup-before and independent restore,
bounded public-data audit-only catch-up, backup-after and independent restore,
then a bounded tail catch-up. Both restored PostgreSQL copies also passed the
supported heap/B-tree `pg_amcheck` checks. The before/after dumps contained
40,855,605 and 40,993,185 bytes respectively. Its final audit contained 331,409
rows; existing outbox/inbox stayed 2,220/2,220, completed, with no pending or
unresolved rows, no trading rows, unchanged sequences and the original
173,164-row audit prefix intact. Audit-only catch-up was never republished.

It then failed closed in the read-only Redis proof with
`BOOT_REDIS_PUBLICATION_RECEIPT_MISSING`, before starting serve. The failed
receipt, latch, both PostgreSQL dumps and all intermediate proofs are retained.
A successful SQL restore is not treated as successful data-plane recovery.

Read-only forensic checks found the full 3,256,200-byte AOF still present:
2,220 publication `HSET` records, 2,221 stream `XADD` entries and 3,549 balanced
transactions, only database 0 and the exact topic/owner ledger keys. Redis
startup had rejected transactional replay through its default-user ACL checks,
leaving incomplete memory despite its ready state. This matches the
[reported Redis AOF/ACL bug](https://github.com/redis/redis/issues/14541) and
[upstream correction](https://github.com/redis/redis/pull/14545); image version
alone is not evidence that the actual replay passed.

The corrective gate uses a new pristine, hash-verified volume copy and a
separate replay clone first. Only a disabled default user with no admitted
passwords and the exact observed replay commands/keys is proposed; named-role
bytes stay identical. Anonymous/default authentication and anonymous writes
must remain refused on the clone. Full publication/stream/group/inbox
comparison must pass before any change or restart of the admitted new epoch
Redis. The old database, old Redis and their queue are outside this path.

The clone-first corrective source is signed Deploy
`7aaf2ee27a2a71603558925d2323932fa13a201a`. Its full offline test suite ran
763 tests on each Windows Python 3.11/3.14 interpreter: 756 passed, seven
explicit skips, zero failures. Scoped Ruff check and format checks passed for
all nine changed Python files. The default recovery CLI is plan-only and makes
no native calls. A separate create-only receipt-bound verification latch
prevents overlapping original-state verification and remains on failure.
The full pristine four-file backup stays immutable; comparison after an
authorized new-epoch Redis restart binds the AOF manifest and base/incremental
file hashes while allowing only the existing root RDB cache bytes to refresh.
Named-role ACL bytes remain unchanged; no AOF rewrite, flush, trim, publication
or queue reset is performed by this corrective path.

All five corrective exact-source hosted gates passed:

- [CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38154266466).
- [CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38154265855).
- [Installed composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38154266520).
- [Current-source Docker](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38154268008).
- [Full-path SIM](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38154271226).

Signed Meta manifest pin `f19966a9680cbf76de2463c41537db92dcc0d3b2` passed
[validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/38154489651)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos/actions/runs/38154489184).
The same static Meta gate passed under Windows PowerShell 5.1 and PowerShell 7;
the 5.1 check used process-only execution policy, not a system policy change.

## Retained Redis clone and reviewed metadata failure

Native clone run `5bfd8f013eb74f08b93ba8381dec8350` actually passed its
full worker proof: 2,220 publication receipts, 2,221 stream entries, 2,220
completed inbox rows, one consumer group and zero pending deliveries.
Anonymous ping, default-user authentication and anonymous clone writes were
refused. The clone stopped cleanly; pristine backup, clone, original AOF,
private ACL candidates and all evidence remain preserved.

The overall controller still failed closed with
`LEGACY_OR_STANDBY_METADATA_CHANGED`. Exact retained before/after inspections
showed only Docker mount-array enumeration order changed for the stopped old
containers. All other fields, including mount sources/permissions and state,
were identical. The original failure and recovery latch are not rewritten,
deleted or relabelled. The clone is not replayed or restarted for this review.

Signed Deploy `fb5b9c79eb8ecc323c731e8ac6b0d3aed22dc1cb` normalizes only
mount enumeration order; duplicate destinations or changes to actual fields
still reject. It also fixes loss of mandatory identity/status fields when
canonical worker/AOF proofs round-trip through a saved receipt. A new explicit
read-only adjudication binds exact retained evidence hashes, the original
signed worker bytes, current container IDs, pristine full-copy manifests and
authoritative source/backup/clone AOF hashes. Its acceptance is create-only;
the original failure remains a separate immutable fact. Original verification
must match the same boot latch and retained stopped clone metadata.

This source passed 772 offline tests on each Windows Python 3.11/3.14:
765 passed, seven explicit skips, zero failures. Scoped Ruff check/format and
deployment/source-projection validators passed. Native adjudication and
same-container new-epoch Redis restart/verification are still pending here;
no original ACL change or original Redis restart is implied by these tests.

Its first read-only adjudication then failed separately with
`REDIS_AOF_AUTHORITATIVE_PERSISTENCE_CHANGED`. Narrow file-only diagnostics
showed that clean clone shutdown added exactly `endoffset 3256200` to the
incremental-segment manifest line. Both base/incremental data hashes stayed
identical, including every one of the 3,256,200 incremental bytes. The source
and pristine backup retained the open-segment manifest. The stopped clone's
root RDB cache refreshed independently. Neither failure nor either existing
latch is deleted or relabelled.

The explicit closed-segment review admits only the two measured raw manifest
hashes paired with these exact known base/incremental hashes and identical
remaining persistence fields. Any other annotation, segment bytes, RDB
presence or metadata change remains rejected. The earlier failed review's
latch and two exact evidence files are verified both before and after the
new read-only scans; the supplement uses its own create-only latch. This
starts only bounded network-none read-only hash helpers, not Redis or the
retained clone. The current signed final review source is Deploy
`aec3616054a69c9c620ee448d59339263de722a0`; Windows Python 3.11/3.14 each
ran 775 tests, 768 passed, seven explicit skips and zero failures.

## Final reviewed recovery and actual scheduled-task acceptance

The retained clone was accepted by a separate append-only, signed adjudication
at Deploy `aec3616054a69c9c620ee448d59339263de722a0`. Its original failed
receipt and both failed-review latches remained unchanged. Only after this
acceptance was the exact tested candidate default-user ACL line applied to
the new epoch Redis. All named-user bytes stayed identical. Default remains
`off`, `resetpass`, without anonymous authentication; replay commands/keys are
restricted to this epoch's observed AOF. Only the same new Redis container ID
and existing volume were cleanly stopped/started. The retained clone was not
restarted; old data containers and the separate standby remained untouched.

The first original read-only verification passed full SQL/Redis correspondence:
2,220 receipts, 2,221 stream entries, 2,220 completed inbox rows, one group,
zero pending deliveries and refused anonymous/default-user access. Its overall
result remained FAILED_CLOSED because root `dump.rdb` refreshed asynchronously
while every AOF byte/hash and pristine backup remained unchanged. This failure
and its latch were retained, not retried, reset or relabelled.

Deploy `70a0ed2` makes the cache distinction explicit: exact tree inventory,
unchanged AOF bytes/manifest, unchanged non-cache file/directory size,
mode/owner/mtime/ctime and unchanged root/RDB mode/owner. Read-access timestamps
are not authority fields. Only root RDB content/size/timestamps may refresh;
extra empty directories, extra files, links, permission/owner changes and AOF
metadata changes reject. The pristine backup still requires its full manifest.
The independent static review found and then confirmed closure of the earlier
overbroad metadata allowance. Historical non-cache metadata is not retroactively
certified by this fix.

An explicitly reviewed, create-only original-verification supplement passed
with fresh strict metadata and full SQL/Redis/auth checks. It records executing
supervisor/worker source `70a0ed2` separately from retained qualification source
`aec3616`. Functional worker blobs are unchanged; the opt-in cold metadata
worker is newly pinned. Earlier failures, latches, qualification, pristine
backup and previous raw proofs are hash-rechecked before/after and preserved.

The failed boot root `e1e4a133...` was moved whole into the recoverable local
archive `epoch-boot-20261011-failed-e1e4a133-redis-reviewed`; critical bytes,
dumps, latches and task definition are retained. Only the exact idle owned boot
task was unregistered, then replaced with the same guarded definition and a
fresh detached-GPG-signed binding:
`31cc9772c43685fad94fcec265401268054d9d573cc3ea1c1b5f50ff3aeffe72`.
The installer passed a real second invocation without mutation.

Actual scheduled-task run `8cf839a8cf0a43b8886eb9fc77b65793` completed at
`2026-10-11T17:20:08Z` with `PASS_NONTRADING_EPOCH_BOOT` and task result 0.
Its fresh before/after dumps contain 40,995,581 / 41,071,790 bytes. Both
independent restores match all 32 tables, full row digests, sequences and five
bar chains, and pass supported whole-database heap/B-tree `pg_amcheck` checks.
Temporary restore containers/volumes were removed only after verification;
both dumps and all receipts remain available for recovery.

Audit-only catch-up appended 605 bars plus a 15-bar bounded tail, taking the
pre-start audit from 331,409 to 332,029 rows. The original 173,164-row prefix
and its digest remain exact. Existing outbox/inbox stay 2,220/2,220, completed;
pending/unresolved/trading rows are zero. The outbox sequence remains 2,233,
not reset to its row count. Historical catch-up rows were not republished.
The final Redis proof again passed before starting the existing bar worker.
Natural watermarks then advanced across BTC/ETH/SOL/BNB/XRP; all three exact
resources remain running in their private bridge with no published ports.

Actual repeat dispatch `32f6d66dbb064bc1bf5abb3bb722ea51` returned
`ALREADY_RUNNING_NONTRADING` at `2026-10-11T17:21:15Z`, task result 0.
It performed only metadata/status checks: no worker snapshots, backups,
catch-up, replay, container creation or restart. The fresh observation at
`2026-10-11T17:23:01Z` passed with all resources running, five matching fresh
watermarks, 2,244 completed inbox rows and no pending/unresolved work.
These are timed snapshots, not permanent counter values or trading evidence.

Windows Python 3.11/3.14 each ran 778 tests: 771 passed, seven explicit skips,
zero failures. Scoped Ruff check/format, deployment validation and current
source-projection validation passed. All five exact-source hosted gates passed:

- [CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38158137194).
- [CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38158137063).
- [Installed composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38158137279).
- [Current-source Docker](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38158150110).
- [Full-path SIM](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38158154820).

Manifest pin `21b0a0b07cd9382d8207aa7c296b3fb51cc8e8b7` passed
[validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/38158206807)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos/actions/runs/38158207117),
plus static gates under Windows PowerShell 5.1 and PowerShell 7.

## Remaining boundaries

This is logon recovery, not a headless Windows service or proof of the next
automatic OS-logon trigger. The real PC outage is being recovered through
manual dispatch of the installed scheduled-task route; no new host reboot
has been forced. Docker restart policies remain `no`.

The protected old PAPER database/Redis remain stopped. Their ambiguous
historical queue is not resolved, replayed, acknowledged, reset or drained.
The exact already-running isolated `kairos-shadow-gate` PostgreSQL is only a
pinned coexistence exception; it is never started, stopped or connected to.
No Strategy/Text/Macro/Router/LLM/Risk/Execution services, exchange orders,
EVEDEX or paid provider calls are authorized by this path.

Off-host backups, actual alerts, long soak/outage qualification, full
application/provider/venue/economic qualification and production arming
remain separate. Adaptive working changes are preserved and unaccepted;
whole clean-release admission is not waived. All trading readiness flags
remain false, `STRATEGY_POLICY=REJECT_ALL`, trading OFF.
