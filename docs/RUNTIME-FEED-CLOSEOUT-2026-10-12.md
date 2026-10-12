# R6 feed recovery and technical notification closeout — 2026-10-12

## Accepted scope

The separate CLOSED_BAR-only R6 epoch is running without strategy, Risk,
Execution, trading, PAPER/LIVE or paid providers. Legacy PostgreSQL/Redis and
their old queue remain stopped and untouched. This is finite engineering
acceptance, not full-system or long-duration qualification. UI/UX is deferred.

R5 failed closed at 18:36:52 UTC with `OFFICIAL_CLOSED_BAR_FETCH_TIMEOUT`.
Its earlier accepted restore/restart receipt is preserved as historical
evidence, not proof that R5 remains running. The first R6 attempt stopped in
`ADMISSION` because a historical failure-file whitelist rejected R5's additional
clean-stop artifacts. It created no backup, DB worker or publication. That
failed attempt and original latch remain byte-for-byte retained.

A distinct, explicit pre-write continuation pins the exact failed receipt,
original latch and all 32 retained file hashes. Its new create-only claim is
separate; no failed claim was cleared or rewritten. Hash-only bounded evidence
inventory replaces the incompatible whitelist only in the new R6 controller.

## Data and native runtime proof

- Fresh before/after dumps independently restored and matched all 32 tables,
  full row histories, sequences and five contiguous bar chains.
- Only four precisely pinned unpublished CLOSED_BAR messages were published,
  durably completed and ACKed once. Older publications, queue prefixes,
  sequences and the original 173,164-bar prefix stayed unchanged.
- Audit-only catch-up added 496 plus 15 bars; these historical bars were not
  republished. The existing live pending cap remains 100 aggregate bars.
- All five symbols advanced before and after a graceful exit-0 restart of the
  same R6 container. Verified disposable clones were removed; both backups,
  prior failures, snapshots and receipts remain retained.
- The 20:34 UTC read-only SQL checkpoint found 340,214 audit rows, 5,880 outbox
  rows and 5,880 matching completed inbox rows. Pending, unresolved, unmatched
  and trading records were zero. The separate 20:34:20 status snapshot reports
  fresh five-symbol watermarks at `1791837240000`; it is not the same instant
  as the SQL checkpoint.

The circuit defers only the admitted public-GET timeout, with existing bounded
GET attempts, capped wait and cooperative cancellation. It reports
`WAITING_SOURCE_NONTRADING` during an outage and `CATCHING_UP_NONTRADING` during
bounded backfill; neither means fresh data. Mixed integrity/database failures,
TLS validation, HTTP rejection and malformed payloads remain fatal. Offline
fault tests exercise the actual supervisor with mocked boundary I/O. R6's
native observation has no source timeout yet; it does not prove survival of
every future external failure.

Native source `85cf124f9252d47d895e6a20f8fb50edcaddf303` is distinct from final
boot source `9e9793470dd218344ea4561a635370361b04603e`. The latter binds only
the accepted receipt, exact R6 container and transport06 disposable clone
identity. A real Limited task dispatch returned `ALREADY_RUNNING_NONTRADING`,
result 0, without a restart/duplicate. Valid source pauses remain unready and
do not trigger a restart. The next actual OS-logon/reboot trigger is unobserved.

## Telegram: new accepted test, retained historical unknown

The R5 V2 incident send is genuinely outcome-unknown. The owner reported no
message; that does not establish no-send. Its four-line journal, exclusive
guard and signed binding are preserved and were not replayed or relabelled.

A distinct R6 test with prefix `[Kairos R6 ROUTE QUALIFICATION]` made one
`getMe`, one `getChat` and one `sendMessage`. Telegram accepted message 4 and
both protected receipt and result persisted. No human confirmation of this
new message is recorded yet. This qualifies the API-accepted technical route,
not month-long notification availability or production security.

The new monitor has its own signed binding and healthy baseline. Local sender
preflight precedes reservation; wire calls follow a durable exclusive guard.
Post-wire uncertainty remains terminal and cannot be automatically resent.
The hidden Limited two-minute/logon task passed manual and automatic polls,
result 0, keeping the baseline unchanged and sending no duplicate. It reads
only the private status file; there is no DB/queue/trading authority. Obsolete
R5 boot/notification schedules are disabled with definitions/evidence retained.
Normal trading signals remain dormant. Production still requires token
rotation/security review because the earlier token was exposed in chat.

## EVEDEX: current external blocker

The public sampler's local admission incorrectly depended on a historical
Telegram Deploy HEAD. Only the sampler was corrected: current signed clean
main/origin and unchanged pinned helper bytes remain mandatory. Frozen Telegram
handoff files were not changed; no keys or authenticated account calls are used.
The first local refusal made zero GETs and created no sample reservation.

One new sample at 20:12:10 UTC made 12 GETs, all HTTP 200. BTC/ETH books and
recent trades were fresh. SOL/BNB/XRP books were empty; BNB was `visibility=none`.
The five-symbol gate is `BLOCKED`. No 24-hour campaign, auth/signing,
reconciliation, order, canary or seven-day soak was started. A successful code
test or two liquid assets cannot substitute for the required venue evidence.

## Source acceptance and remaining boundaries

Deploy's final Windows Python 3.11/3.14 suites each run 922 tests: 915 pass and
seven explicit platform/environment skips. Scoped Ruff, PowerShell parsers and
all five exact-source hosted gates pass. Ops suites pass 115 on both versions.
The sampler fixture's hosted Windows TEMP-junction issue was fixed only in its
test paths; production reparse rejection was not relaxed. Meta validation and
CodeQL pass for that repaired source; the dated closeout gets its own CI.

A direct read-only fourteen-repository audit found main/HEAD/local origin/main
and actual remote main equal, with good signatures from the trusted signer.
The manifest now pins final Deploy. Meta's 43 adaptive WIP paths plus twelve
old untracked service test artifacts were left untouched and unaccepted;
whole clean-release qualification remains blocked, not waived.

The [signed factual receipt](receipts/runtime-r6-closeout-20261012.json) records
exact hashes and scopes. Full application/provider/venue qualification,
elapsed availability and economic gates, selected hosting, encrypted off-host
restore, production custody/security/limits and manual arming remain separate.
All readiness flags remain false; `STRATEGY_POLICY=REJECT_ALL`.
