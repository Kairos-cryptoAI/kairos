# LLM shadow qualification preflight — 2026-09-28

This is an engineering and read-only operational receipt, not a paid model
qualification, trading authorization, or research performance result.

## What was observed

- The existing `kairos-shadow-gate-timescaledb-1` container was the only
  container started for this inspection. Its image was the pinned
  `timescale/timescaledb:2.29.1-pg16` digest; no application or consumer was
  started. A read-only SQL transaction confirmed database `kairos`, twelve
  applied migrations, twenty historical usage reservations, and no
  `campaign_source_budgets` table. The same container was then stopped.
- The supplied `C:\Users\loval\Documents\keys.txt` exists and has recognizable
  OpenAI/DeepSeek markers. The values were not printed or copied to a new
  file. One GET-only check of OpenAI `/v1/models` and one GET-only check of
  DeepSeek `/user/balance` each returned HTTP 200. No inference endpoint was
  called and no paid usage was authorized. HTTP 200 does not bind those
  credentials to the historical campaign account/project or prove a model
  route is qualified.
- The local GitHub credential still lacks `read:packages`; the independent
  immutable-image runtime recovery gate remains blocked. No primary database,
  outbox lease, cursor, or frozen research ledger was touched.

## Shadow database backup and restore drill

Before any migration or adoption, the same stopped-by-default shadow database
was briefly started for a fresh full `pg_dump -Fc`. The archive is preserved at
`D:\Kairos\runtime\shadow-campaign-preflight-20260928T090355Z\kairos-shadow-pre013.dump`
(81,783 bytes; SHA-256
`d535ed181300755a77f473df06fb520cd9f45651c8c89ebc9585e3d06fdfa798`).
It was restored with `pg_restore --exit-on-error` into a distinct no-network,
tmpfs-only TimescaleDB container using the exact local source image digest.
`timescaledb_pre_restore()` and `timescaledb_post_restore()` both succeeded, as
did the restore. Source and restored clone each had database `kairos`, twelve
migrations, twenty reservations, and no campaign table. Ordered migration and
reservation-row digests matched (`3e809eb8f326ea469537e868a38bde0b` and
`7b792dcbe403289d58fb53029b56e3d6`). The disposable clone and the source
container were stopped; only the exact tmpfs clone container and the temporary
dump inside the source container were removed. The protected archive remains.
The new archive directory permits access only to the current Windows owner,
Administrators, and SYSTEM; it is still a local, unencrypted copy.

This proves a local shadow-data restore, not off-host encrypted backup,
provider billing reconciliation, migration 013, campaign adoption, or PAPER/LIVE
readiness. The restore sequence follows the [TimescaleDB logical backup
guide](https://docs.timescale.com/self-hosted/latest/backup-and-restore/logical-backup/).

## Qualification code gate

`kairos-llm` revision `b6e1d9952fd5f97ad205204ca2ccf27f1b1f56b4`
hardens the paid shadow qualifier. It rejects extra JSON fields and reparses
the raw provider response before accepting the fixed `NO_TRADE` contract;
credential-bearing calls are pinned to official OpenAI and DeepSeek HTTPS
endpoints despite service environment overrides. OpenAI rate-limit hints alone
no longer prove usable quota, while the DeepSeek preflight uses its official
read-only `is_available` balance flag without recording balances. A resolved
backend change within one run fails; changes between runs still require
explicit review. The CLI now requires an explicit database target, verifies
the exact migration profile and registered shared campaign before loading keys
or sending requests. A database name alone does not identify the correct
Docker project, so operator target verification remains mandatory.

Both Windows Python 3.11 and 3.14 passed 97 LLM tests, Ruff and mypy. Bandit
and package build also passed. Hosted [CI](https://github.com/Kairos-cryptoAI/kairos-llm/actions/runs/36398979083)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-llm/actions/runs/36398978822)
passed. The fixed inference checks used synthetic results only; they made zero
paid API calls. The previously observed pytest cache warning concerns an inaccessible
local cache directory, not a test failure.

The balance endpoint and rate-limit header meanings follow the
[DeepSeek balance API](https://api-docs.deepseek.com/api/get-user-balance/)
and [OpenAI rate-limit guide](https://developers.openai.com/api/docs/guides/rate-limits).

## Why paid qualification is still blocked

The sole paid-shadow database has not adopted the fixed
`kairos-dev-qualification-v1` campaign. The September 12 historical expense
reconciliation at
`D:\Kairos\runtime\expense-reconciliation-20260912T135500Z\report.md`
identified off-ledger calls and unresolved account/X history; it explicitly
forbids treating the remaining caps as a fresh allowance. The fresh local
backup and restore drill above complete only that prerequisite. Before any paid
shadow probe: finish conservative historical spend reconciliation, apply the
reviewed migration/adoption workflow to the authoritative shadow DB, and
verify the campaign totals. Never register a separate database or erase
old reservations to make room. Failed calls may retain a reservation even if
their report has no measured cost, so each run needs post-run campaign usage
reconciliation.

The owner subsequently confirmed that the supplied OpenAI/DeepSeek keys belong
to the same accounts/projects as the historical probes and that no other paid
runs occurred. This narrows the account-history question but does not change
the observed database schema or authorize skipping backup, adoption receipts,
or the cumulative budget guard. X's historical timeout remains a separate
unresolved provider budget; it is not charged against the LLM campaign by
inventing a zero-cost result.

A read-only workflow audit found no shadow-specific migration controller. The
test migration smoke command checks the SQL database name/profile but not the
Docker project identity; the existing deploy preflights are clone-only and
PAPER-specific. Running a generic migration or Compose application startup
against the authoritative shadow DB is therefore not approved. A dedicated
target-guarded procedure must first rehearse the complete runtime migration
suffix on the verified restored clone, preserve all twenty reservation rows,
then verify exact source identity and zero paid producers before a separately
reviewed shadow migration. OpenAI/DeepSeek off-ledger amounts of 1,984/134
micro-USD are candidates for conservative receipt holds, not provider invoices
or already-registered campaign spend; X remains unresolved.

Until then, the new model routes are engineering-verified only. No paid model,
EVEDEX, canary, PAPER, or LIVE request was made for this receipt. Readiness
remains `TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`,
`ALPHA_READY=false`, `LIVE_READY=false`, and `STRATEGY_POLICY=REJECT_ALL`.
