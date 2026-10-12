# R5 runtime and notifier: additive verification correction — 2026-10-12

## Current result

The accepted non-trading R5 runtime continues running on the same container.
The independent 17:51 UTC read-only SQL check found 339,399 audit rows and
5,576 matched outbox/completed-inbox rows; pending, unresolved, unmatched and
trading rows were zero. All five bar watermarks advanced to `1791827460000`.
Redis transport failure/recovery counters remained zero. This extends the
post-restart observation to roughly 43 minutes, not a long-term uptime claim.

Both fresh full isolated restore checks, the exact five-message recovery and
the graceful same-container restart documented in the
[original closeout](RUNTIME-STABILITY-2026-10-12.md) remain valid. No new runtime
restart, consumer recovery, database migration or queue reset was performed for
the notification fix. Legacy database/queue containers remain stopped.
All readiness flags remain false; policy remains `REJECT_ALL`.

## Corrected notification evidence

The original signed receipt is preserved byte-for-byte. Its notification
`journal_records=1` is incorrect for the saved journal hash: that hash identifies
**four** records, including one stale observation, a send reservation and an
unknown outcome. A subsequent native dispatch returned 2, not continued success.
The original successful healthy task dispatch remains historical evidence only;
it did not qualify the later unhealthy sender path.

The exact signed V1 source's sender began by importing `_read_private` from
`telegram_continuation`, where that symbol does not exist. This raises ImportError
before token reading or transport construction. Review of the pinned source and
a no-network probe independently established **zero wire attempts** for this
exact historical event. Its unknown journal entry and guard were not deleted,
rewritten, marked delivered or retried. This finding is not a general waiver
for ambiguous Telegram/network outcomes.

V1's task stays disabled and retained. A distinct V2 monitor has its own protected
root, signed binding, signed exact no-send adjudication and healthy baseline.
Admission checks the retained predecessor hashes/guard and accepts only this
particular locally proven defect. V2 does not replay the historical stale event
or the retained R4 firing.

## Repair and verification

- A local bounded reader checks private ACLs, reparse paths, regular-file
  identity and byte limits; no missing helper is imported.
- Token/handoff validation and offline transport construction precede any
  observation/reservation for a sending transition. A failed preflight leaves
  the baseline unchanged and makes no network call.
- Actual `sendMessage` occurs only after a durable exclusive guard/reservation.
  Recipient/message-id checks and protected receipt persistence remain required.
  A post-wire timeout, invalid response or receipt failure stays unknown and
  cannot be automatically retried.
- `--verify-only --armed` now exercises credential/sender preflight without
  calling Telegram or changing the journal. Healthy polls remain quiet.
- The 102-test notification suite passes on Windows Python 3.11 and 3.14.
  New offline tests exercise the production sender with synthetic credentials
  and a fake wire transport, including preflight/no-reservation and ambiguous
  post-wire/no-retry paths. Ruff and Meta static validators pass.
- Signed source `3a12aef4ef3e274902fff1138d14f8dd7ea69161` passed both exact-source
  hosted validate and CodeQL runs (`38286823932`, `38286823805`). Runtime/boot
  Deploy sources and their previously green five-gate CI sets are unchanged.
- The new hidden Limited two-minute/logon task is
  `Kairos-R5-TechnicalAlerts-V2-20261012`. Its manual task dispatch at 17:51:14
  UTC and automatic poll at 17:53:13 UTC both returned 0; the healthy baseline
  stayed unchanged and no messages were sent.
  The boot task remains enabled; the obsolete R4 and R5 V1 notification tasks
  remain disabled, not removed. No trading-signal class was enabled.

The [additive signed receipt](receipts/runtime-r5-notifier-correction-20261012.json)
records these distinctions. This is not actual OS-reboot, production/off-host,
long-duration availability, trading or resolved-message delivery qualification.
The 43 unrelated adaptive WIP entries remain unstaged and unchanged.
