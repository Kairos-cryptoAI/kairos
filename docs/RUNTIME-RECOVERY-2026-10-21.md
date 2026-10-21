# Fresh non-trading runtime recovery — 2026-10-21

This is a bounded recovery receipt, not a LIVE/PAPER or strategy approval.
The legacy database/queue and the failed `9e489055` generation are preserved.
No real orders, transfers, paid providers or research campaigns were started.

Current checkpoint: the exact ten incomplete deliveries have been resolved on
the isolated restored copy, its signed joint snapshot is accepted, and the new
non-trading serving contour is accepted after independent adjudication and one
drained restart. The original source remains unchanged. This is a bounded feed/
queue recovery PASS, not full production trading or final-host reboot acceptance.

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

## Original source queue: ten incomplete deliveries preserved; no blind ACK

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

## Later checkpoint: exact-ten clone state and joint backups accepted

The fresh source crosswalk established that the ten missing SQL inbox rows
were undelivered stream entries, not stale pending entries: stream size 14,135,
PEL empty, completed inbox 14,125. Its historical 18-migration source profile
was verified separately; no schema bypass or migration of the source was used.

Native processing on the owned isolated copy brought inbox completion to
14,135. An outer 75-second proof timeout interrupted the final crosswalk; that
attempt remains an `UNKNOWN_PARTIAL_NO_RETRY` receipt. The consumer was not
rerun. A separate read-only adjudicator subsequently verified all 32 public
table/sequence/history projections, unchanged non-target inbox/audit/stream/
publication-receipt data, and exactly the ten admitted completions with one
attempt each. The PEL is empty and the group cursor equals the stream tail.
Acknowledgments are inferred from those terminal observations and the pinned
consumer code, not presented as directly captured transport telemetry.

The accepted joint proof is
`D:/Kairos/runtime/r7-recovery-20261021-a8f2da2efb4845728cd1c2ffa0163915/postpack-run-9f7a612b952e4ababe154b98e62629e7/currentqueue-joint-proof.json`,
SHA-256 `14094ea8048ef369897132fd2909e765627cc98c75a0db4692618e5316168efc`.
It explicitly records `READONLY_ADJUDICATION_AFTER_PROOF_TIMEOUT_NO_REPLAY`,
`direct_replay_run_accepted=false` and unavailable transport telemetry. The
prior consumer and the later adjudicator have separate signed code/failure
lineage; the inherited pre-worker label is not authority for queue state.

The native terminal-state/backup receipt SHA-256 is
`127df00cb192af9a6cdc3219a7b0295ed0d6aea15e9d036842ca2b6d45167b06`.
Its post-processing PG dump SHA-256 is
`73b3e0a925713f6d61ae2fdec993429e5d4724aabee5d3f79cb7a59922d8ce15`;
the three-file AOF archive SHA-256 is
`19ac0e492237b1e44053cb2afcd75e793fa10e70db1c7dcda56eeaba97d3bfd9`.
The stopped Redis volume additionally contains a root `dump.rdb` cache: its
four-file cold manifest totals 26,395,200 bytes and binds every file's content.
Both processed clone backends are stopped and retained. No original source
ACK, lease/cursor reset, reconciliation or trading mutation occurred.

Failed preparatory attempts are retained separately: ACL parsing, Docker IPAM
normalization, copying into a read-only root filesystem, use of an environment
without pip, the missing audit INSERT grant, an unrelated cold-worker CLI, and
an incorrect three-file assumption for the full cold volume. None is rewritten
as a clean direct replay PASS.

## Earlier new-generation preparation refusal

The new-generation candidate restored the accepted PG dump into its own fresh
backend, but refused its role bootstrap before that helper ever started:
`EXACT_RUNTIME_NETWORK_ID_REQUIRED`. A Docker container in `created` state has
a configured network but no attached endpoint ID yet. No consumer or serving
worker was launched. That failure and its never-started helper are retained;
continuation may admit only this exact owned pre-consumer skeleton and must
validate actual endpoint identity after starting a new bounded helper.

That checkpoint did not accept fresh application roles/Redis credentials,
new runtime running-health/restart or monitor adoption. The later attempts
below supersede its pending status without rewriting its retained failure.

## Fresh backend pair and bounded catch-up observation

The exact owned pre-consumer backend skeleton was subsequently admitted with
new application/Redis credentials. Further preparatory refusals are retained:
libpq rejected Windows-mounted pgpass permissions; a continuation used a module
closure with mismatched owner validation; the native six-field queue projection
needed an independently checked seventh SQL-derived zero; and the native boot
envelope required an explicit validated core crosswalk. A retained diagnostic
container-name collision was corrected by a fresh per-run diagnostic namespace,
not by deleting/reusing the failed container or changing data.

Run `164d902c5cd7e9c8bb1c3c83f535f7d9` passed full native prestart PostgreSQL
and Redis checks. A fresh dump of the actual new backend was independently
restored and compared, and `pg_amcheck` passed before the serving worker started.
The original database and queue were never the serving target.

The outer 900-second freshness poll then refused with
`FRESH_NONTRADING_SERVE_STATUS_REQUIRED`. Its signed failure is retained:
SHA-256 `52348ede914d6fa4d029b1fe32471009a269a5d4f16f36661cb513f3e1037473`.
Cleanup reported `new_workers_stopped=false`; independent inspection confirmed
the exact new worker remained running. Its cycle 65 fresh status was timestamped
`2026-10-21T20:08:28.710845+03:00`, at the bounded poll boundary. This observation
does not rewrite the failed outer attempt as a direct PASS or authorize a second
consumer. Subsequent observations show the same process continuing with fresh
five-symbol bars, zero pending/unresolved/uncompleted queue counts and zero
recorded Redis transport failures/recoveries. Separate exact-identity, read-only
adjudication and one graceful restart qualification are required for acceptance.

All readiness flags remain false; policy `REJECT_ALL`.

## Final bounded acceptance: same worker, one drained restart, no replay

The accepted receipt is
`D:/Kairos/runtime/r7-recovery-20261021-a8f2da2efb4845728cd1c2ffa0163915/cutover-run-164d902c5cd7e9c8bb1c3c83f535f7d9/cutover-receipt.json`,
SHA-256 `e024c911c60eb476129a19da8417b48cfef05cd1757df5fdd6a626c71e74fb5b`.
Its detached signature verifies against the trusted GPG fingerprint. The
actual final adjudicator SHA-256 is
`f869f83b17403b43ecb98cbe05bac4d3844c947431a1254b3e8af14c2587fe53`.
This read-only final adjudicator does not start, stop or replay a consumer.

The earlier acceptance wrapper stopped the exact new worker gracefully (exit
0) and ran the maintained native SQL/Redis check while it was stopped. That
check passed: 20,650 completed inbox/outbox/publication receipts, zero pending,
one consumer group and 20,651 stream entries. The extra entry is the single
known duplicate delivery already accepted by the pinned native validator and
present in the prestart 14,135/14,136 snapshot. It is preserved, not deleted or
mistaken for a new unresolved publication. The wrapper's additional incorrect
stream-count equality refused; failure SHA-256
`20d192e8e94176de56789901d60dc3685abbc0135122837eaa4a37db1e7a0d6f`
is retained. The native stopped-state proof SHA-256 is
`55e13a0da3c77641f02200edd0af9e726b362f5f82f67c403c1e7369840b36f4`.

A separately pinned continuation rechecked that exact known clean stop and
native proof, then started the same container once. Its initial startup-status
poll refused before later fresh status appeared; that failure SHA-256
`5400a838c24b7d4a4bd25a56e7e844fae6b1119ef3912ad50a30d6cfd68a9655`
also remains unchanged. It did not launch a second consumer or retry a delivery.
Final read-only adjudication verifies the same container's actual new startup,
fresh status, current exact-tuple SQL queue correspondence and five-symbol
watermark progress. The one drained stop/start spans those separate receipts;
none of the failed wrappers is relabelled as a direct clean PASS.

All five watermarks advanced from `1792603740000` to `1792604160000` by
`2026-10-21T20:36:27.073799+03:00`. Pending outbox, unresolved inbox and
uncompleted publications are zero; trading tables remain empty. The new backend's
independent prestart backup/restore dump SHA-256 is
`5abb639ea39ba56b0bb45917f47e0f14535797b4941364b6d4dbf15fb170da18`.
Its 32-table/three-sequence equivalence and `pg_amcheck` succeeded before serving.

The separately signed final provenance SHA-256 is
`ddd139f54ded35f17342c08e609422e586c9f4f67e090c178be4fde1213c6e6c`.
Parent code is verified and compiled from the same pinned resident bytes;
evidence is hashed and parsed from the same buffer. Diagnostic worker source
comes from the pinned ZIP into a fresh protected snapshot, with per-file hashes.
Eight local admission tests and Ruff pass. Original evidence is not overwritten.

The serving contour retains its accepted historical 18-migration/offline-wheel
profile and Deploy `90759ffc0459f7684262a90e72632d5bbe647768` provenance.
The newer engineering manifest/source locks do not silently upgrade this data
plane or deploy the production-state v2 service. Original PG/Redis containers,
volumes, DB/queue and failed generations remain preserved. Old boot bindings
remain disabled; no Windows reboot or automatic unknown-outcome restart is
claimed. Docker restart policies remain `no`. A later reboot needs a separately
accepted guarded binding; this receipt proves one process restart, not that boot.

## Technical monitoring adopted and exercised through its installed task

The separate adjudicated monitor accepts only the exact full run identity and
signed receipt above. Its serving inbox count must be an exact integer not
below the signed seed; a continuously growing completed queue must not be
mistaken for corruption. Pending/unresolved/uncompleted counts remain strict
zeros. All predecessor journal, guard and five delivery receipts were preserved;
there are no unresolved sends. The no-resend handoff SHA-256 is
`0bde53de4e138ca3a7aafc2107926ec93b0faeea624555ac191a21760061b011`.
Twenty-three offline monitor tests passed.

The existing `Kairos-R7-SQL-TechnicalAlerts-V1-20261016` task was retargeted by
changing only its monitor path. Hidden wscript/VBS hosting, PT2M/logon triggers,
IgnoreNew, PT5M, interpreter and all non-action task XML were preserved. An
initial switch candidate's incorrect S4U assumption refused before mutation;
an independently signed switch admitted the actual pre-existing Interactive
principal without changing it. This monitor therefore does not establish
unattended logged-off/server-service operation.

One actual run was requested through that installed hidden task; no parallel
manual poll or duplicate alert was launched. The adopted journal observed
`running_fresh`, reserved one `resolved` transition and recorded `accepted`
delivery. That is Telegram API acceptance, not a new human visibility claim.
Later scheduled polling keeps the same no-resend history. Old boot tasks remain
disabled; monitor adoption does not arm or restart a trading consumer.

The first later poll exposed a monitor-directory validation defect: its exact
file inventory included predecessor guards but omitted the new guard created
by a legitimate accepted successor send. It refused with task result 2, without
resending or changing the delivery history. A separate signed guard-aware patch
now admits only guards for actual journal reservations and checks each new
guard's exact canonical event/state/transition bytes. Unknown extra files and
rebound guards still fail closed; no guard or receipt was removed or bypassed.
Twenty-eight offline tests pass, and read-only admission verifies all 33 journal
rows, six reservations and six accepted outcomes (five inherited, one new).

The installed hidden task was retargeted action-only to this patch, SHA-256
`0123aaa7898bf1ab646e52406f45772e386dc76ec2363181abf9255879ced882`.
Its actual run at `2026-10-21T20:44:10+03:00` completed with task result 0.
The journal remains `running_fresh` with no seventh send reservation: the
unchanged-state poll was silent. At final observation the feed is fresh,
pending/unresolved/uncompleted counts and Redis transport failures remain zero.
