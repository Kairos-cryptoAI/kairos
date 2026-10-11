# Kairos — isolated non-trading runtime epoch, 2026-10-11

## Accepted scope

The owner explicitly authorized a separate non-trading runtime epoch, a
verified CLOSED_BAR-only history seed and completion of this runtime without
changing the old database or queue. The accepted result is
`PASS_NONTRADING_RUNTIME_EPOCH_CONTINUATION`, not admission of the old runtime,
the adaptive working tree, an exchange account or trading.

Owner `69893dc7b7c647f49967387e7efca9fb` has a separate PostgreSQL database,
Redis instance, named volumes and private bridge. No host ports are published.
Only the new PostgreSQL, Redis and CLOSED_BAR producer/consumer worker remain
running. Strategy, Text/Macro/Router/LLM/Risk/Execution, EVEDEX, PAPER/LIVE and
paid API calls were not started. All trading readiness flags remain false and
the strategy policy remains `REJECT_ALL`.

The [signed public receipt](receipts/runtime-epoch-20261011.json) binds the
private native receipt and precise source/evidence hashes. Private archives,
dumps, configs, credentials and market payloads are not uploaded.

## Source and verification

The final continuation binds signed Deploy
`ed95ec496d1dff3c591dcb1c0b6feda7e4565909` and its immutable operator snapshot
`b223b2e3988ce2be467661ed3023d849096bd108f4cd45529580bca0f83369b0`.
The manifest-only Meta commit is
`cd71d5c431cd94557a7f459e97c0afdf57c8f823`; other pins/readiness and unfinished
adaptive changes were preserved. Current-source Core/Persistence wheels and
the pinned Quant snapshot are installed offline in the immutable worker image.
Neither the frozen Backtest nor Trial 15/V2/V4/V5 evidence was altered.

Windows Python 3.11 and 3.14 each ran 692 tests: 686 passed, six explicit skips,
zero failures. All 11 source/deployment validators, Ruff check/format and both
PowerShell recovery gates on Windows PowerShell 5.1/PowerShell 7 passed.
The five exact-source hosted Deploy gates are green:

- [CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38108764130).
- [CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38108764047).
- [Installed composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38108763976).
- [Current-source Docker gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38108769792).
- [Full-path SIM gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38108771520).

The manifest pin also passed exact-source Meta
[validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/38108882106)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos/actions/runs/38108881721).
These hosted fixtures are separate from the actual local runtime evidence.
The preserved adaptive working tree still blocks whole clean-release acceptance.

## History and recovery evidence

The initial seed copied only 173,164 verified, contiguous CLOSED_BAR audit
rows, with no old inbox, outbox, cursor, lease, order or effect replay. Its
canonical ordered-bar digest is
`a99ac49e8d87bf856b35f90e740de8d74664147754a51d938dae3bad2805a9d1`.
The original audit-row prefix remains exactly 173,164 rows with row-table hash
`f23b4060feae703c568b0204f4b3ff8932fe2813b20f578bc0a0d983e5600499`.
The canonical bar digest and audit-table row digest have different meanings;
they are not interchangeable.

Earlier unsuccessful attempts are retained as immutable failed evidence, not
relabelled as successful. The original worker exposed a runtime-library mount
constraint; later initializer/backup/schema guards failed closed. Attempt 04
successfully verified a fresh restore and rotated the generated epoch-only
history credential, then failed on a timeout after 3,184 verified appends.
Attempt 05 admitted the exact resulting 176,348-row state and unchanged seed
prefix; it did not roll back, re-import, repeat rotation or resume an ambiguous
publication.

Attempt 05 created a fresh 21,090,947-byte binary backup and independently
restored it before any further append. All 32 current controlled-runtime public
tables, complete row digests, sequences, migration history and five chains
matched; supported whole-database heap/B-tree verification passed. The schema
inventory is the fresh controlled profile, not the legacy primary's 39 tables.

Bounded, public Binance Futures CLOSED_BAR GETs then filled the gap. Each page
retains the existing independent delayed confirmation and exact anchor/count
checks. Only timed-out public GETs have a bounded three-attempt retry;
database writes/publications are never retried by that wrapper. Two main
batches and one final tail added another 151,671 bars, audit-only.

The post-catch-up snapshot contains 328,019 contiguous unique bars, with empty
inbox/outbox and zero execution orders/effects. Counts are 65,604 each for
BTC/ETH/SOL/BNB and 65,603 for XRP. Coverage begins 2026-08-26 14:31 UTC
(XRP 14:32) and ends at the bar closing 2026-10-11 03:54:59.999 UTC.
The original prefix hash remains unchanged. A separate 39,990,847-byte final
backup restored and matched all 32 tables, sequences and chains; whole-database
heap/B-tree verification passed again. Verified disposable restore containers
and their owned volumes were removed; backups and failed-attempt forensics
remain protected locally.

## Actual running non-trading path

After the audit-only catch-up, only newly closed bars enter the new epoch's
outbox, Redis stream and consumer inbox. The historical seed is not republished.
The actual qualification passed two cycles and ten naturally received bars,
with zero pending outbox, unresolved inbox or uncompleted publications. It
verified Redis acceptance replay returns the same ID, conflicting hashes are
refused, and duplicate delivery is acknowledged without a second inbox effect.
Consumer Redis `XADD` and SQL outbox-update denial were tested.

A controlled stop/start of the new serve container then passed fresh status
and natural watermark advancement on all five symbols; completed inbox count
was 15 with all queue-health counters zero. A subsequent read-only observation
found 50 new publications / 50 completed inbox rows, 328,069 audit rows and zero
orders/effects. The runtime was still running with fresh five-symbol status and
no published host ports. These are time-bound observations, not fixed lifetime
counts or an availability guarantee.

The old PostgreSQL and Redis remain stopped. Their exact identities and volume
metadata hashes match before/after; there were no old SQL/Redis commands,
consumers, queue replay, acknowledgement, reset, skip or dead-letter action.
The legacy UNKNOWN/FIFO barrier remains unresolved and preserved. This new
epoch does not claim to reconcile that separate legacy history.

## Remaining boundaries

This closes the isolated, current public-bar non-trading runtime and local
backup/restore/container-restart qualification. It does not prove host/OS or
Docker-daemon reboot recovery, prolonged-outage recovery, long soak/availability,
off-host restoration, full application composition against this epoch,
authenticated venue access, orders or economic performance.

Off-host backup, actual alert delivery, adaptive/LLM qualification and sealed
economic gates, EVEDEX qualification, production security/limits and separate
owner arming remain distinct. `TECHNICAL_PAPER_READY`, `PAPER_QUALIFIED`,
`ALPHA_READY` and `LIVE_READY` remain false. LIVE remains unarmed and no trading
authority follows from the non-trading runtime receipt.
