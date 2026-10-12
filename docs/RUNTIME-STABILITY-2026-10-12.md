# Working non-trading R5 runtime — 2026-10-12

## Accepted result

`PASS_NEW_NONTRADING_GENERATION`, recovery kind `R5_EXACT_READ_RECOVERY`.
The owner-approved repair addresses only the independent CLOSED_BAR epoch.
Legacy PostgreSQL, Redis, volumes and queue remain stopped and untouched.
Failed original/R2/R3/R4 generations, latches, dumps and receipts are retained.
Trading, strategies, execution, PAPER/LIVE and paid model/provider APIs remain
off. `TECHNICAL_PAPER_READY`, `PAPER_QUALIFIED`, `ALPHA_READY`, `LIVE_READY` are
false; `STRATEGY_POLICY=REJECT_ALL`.

The signed [public engineering receipt](receipts/runtime-r5-stability-20261012.json)
distinguishes source, native recovery, restart, observed stability and scheduler
evidence. The original private receipt is byte-bound by SHA-256
`a0b16bfc3953b39f63767df228fcae43a0afdc1a70a5ba45973ab4dc4a1c06fd` and has an
independently verified GPG signature.

## Defect and repair

R4's recorded Redis `XREADGROUP` timeout terminated its consumer task and then
the whole supervisor. Its infrastructure cause is unconfirmed: the frozen Core
used a 5-second stream block and 15-second socket timeout, not a 5s/5s collision.
Five newly published messages remained without completed inbox records.

The worker-local R5 transport preserves frozen Core/Persistence and trading
contracts. Hidden Redis client retries are disabled. Only recognized transport
timeouts/connections receive bounded recovery; auth, permission, protocol,
payload, database and integrity errors remain fatal. After an ambiguous new
stream read, the same consumer's pending entries are read before another `>`.
ACK replay is bounded and idempotent; the durable inbox remains authoritative.
The inherited stale-owner claim policy is unchanged. Groups, cursors and leases
are never reset. Stop/cancellation cannot turn a failed operation into success.

SIGTERM requests completion of the current fully drained cycle. It creates a
new immutable clean-stop receipt and closes the consumer before other resources.
It does not interrupt a pending inbox commit or overwrite prior stop evidence.

## Native data/recovery evidence

Before any consumer write, the new epoch had 336,429 audit rows, 5,336 published
outbox rows and 5,331 completed inbox rows. Exactly five admitted messages at
open time `1791791760000` lacked inbox completion; all others matched.

- Fresh before dump: 42,464,672 bytes, SHA-256
  `6d9901b4129c2349899f43fd243ef55dd482b6568fe068aaeb47773ac72f560b`.
- Its separately owned restore matched all 32 public tables and row digests,
  sequences, all five contiguous bar chains and the original 173,164-row prefix.
  Heap/B-tree checks passed on the disposable clone.
- Consumer-only processing completed precisely the five admitted messages and
  confirmed all five transport ACKs. New publications, stream entries and
  publication receipts added: **zero**. Existing audit/outbox rows, sequences,
  completed inbox prefix, stream payloads and known receipt values were unchanged;
  PEL ended at zero. Unknown extra ledger hash fields are not enumerated by the
  least-privilege producer; the drain identity cannot write that ledger.
- Audit-only catch-up did not publish historical bars or change completed queues.
- Fresh after dump: 42,803,448 bytes, SHA-256
  `099b5e49574b8200fbf27f9906023423bac5882dddeaf8221358d61f302017c7`.
  A second full restore and physical/index check passed. Only verified disposable
  clones were removed; dumps and failed diagnostic attempts remain recoverable.
- R5 showed fresh five-symbol advancement, exited **0** on a verified clean stop,
  restarted the same exact container and showed another five-symbol advance.
  Native acceptance was at 17:08:33 UTC.

The independent 17:23:08 UTC SQL/status observation showed 339,254 audit rows,
5,431 outbox rows and 5,431 completed inbox rows. Pending outbox, unresolved
inbox, uncompleted publications and trading records were all zero. All five
watermarks advanced; transport-failure/recovery counters were zero. This is a
roughly 14.6-minute post-restart observation, not 24-hour/month-long availability.

## Boot, notifications and source identity

Runtime execution source is signed Deploy
`807787b1fb6350f1086908bc5a5a2c54278b000b`. Accepted R5 is separately bound to
the guarded boot source `85959a00e650adb07e221f8634544232890fb371`; both source
revisions passed Windows validators plus all five exact GitHub CI/Docker gates.
The source manifest now records the latter revision without granting readiness.
The unrelated 43-entry adaptive work-in-progress set remains unstaged/preserved;
full clean-release admission is not waived.

R5 container identity:
`837783acb187510d04f7e33295a6c18e9c31129f4145f434b288c0a88f565d99`.
It has no host ports, no automatic restart policy, a read-only root and the
existing least-privilege, bounded non-trading resource profile.

- Boot task: `Kairos-NonTradingEpoch-69893dc7b7c6-Boot-R5`, hidden Limited,
  logon-triggered, no automatic retry. Binding SHA-256
  `61d3973f416a6f7b155c1d1b9d653dcd4aa8304b5e7a3c6a10e699f3494f0271`.
  Real task dispatch returned `ALREADY_RUNNING_NONTRADING`, exit 0, without a
  duplicate/restart. A future actual OS logon/cold boot was not simulated here.
- R5 technical notifier: fixed accepted R5 status file only, hidden Limited,
  two-minute/logon schedule, separate signed binding/journal/guards. Native task
  dispatch returned 0. Healthy initialization/polls sent **no messages** and did
  not replay the retained R4 firing. The existing owner-selected temporary group
  is unchanged; no trading-signal class or DB/queue access is enabled.
- Both obsolete R4 schedules are disabled, not deleted. R4 event-journal SHA-256
  remains `c394e6346934dc07e3463a75d893ad6227e5eae24e43e8f00039ce5a6d6cd550`.

Runtime tests cover lost read/ACK replies, same-consumer PEL replay, bounded
exhaustion, forbidden retries, cancellation, last-ACK stop ordering, full restore
state drift and graceful restart. The execution source's complete Windows
Python 3.14 suite ran 882 tests (7 skipped); boot checks additionally passed on
3.11/3.14. The notification suite ran 95 offline tests on both versions.

No claim is made here about alpha, profitability, EVEDEX qualification,
off-host availability, actual OS-reboot qualification or real resolved Telegram
delivery. The earlier EVEDEX empty-book gate and other launch prerequisites are
unchanged; this request repaired the working **non-trading data runtime**.
