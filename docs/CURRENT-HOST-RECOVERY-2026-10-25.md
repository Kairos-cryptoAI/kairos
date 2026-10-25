# CURRENT non-trading runtime and Windows launch acceptance — 2026-10-25

## Accepted scope

The new owned data runtime `3652db45719547b18fad1d6ff10ea002` passed native
history recovery, isolated restore, non-trading delivery, owned-container
restart, and the real Windows scheduled action. It remains running in
`RUNNING_NONTRADING`. This is **not** the complete production trading service
or a real-news/model/Risk/venue E2E acceptance.

The final signed closeout is
`D:/Kairos/runtime/prod-runtime-inputs-20261024/current-host-closeout-3652-v1/closeout.report.json`,
SHA-256 `0d885fe2ff4fae1483f25da03a33190e64dacfdf22cf36fd76995dc889120381`.
Its current native status has zero pending outbox, unresolved inbox and
uncompleted publications. Each readiness flag remains false and policy remains
`REJECT_ALL`. No order, paid model call, old database/queue mutation or research
campaign change was made by this qualification.

## Corrections and host configuration

- The reported missing `pythonw.exe` existed inside Codex's virtualized AppData
  view, but not at the same host-visible path. An unpackaged Windows diagnostic
  confirmed the discrepancy. A directory junction exposes the existing pinned
  CPython 3.11.15 installation; no interpreter binary was replaced or copied.
  The exact `pythonw.exe` hash is
  `d20383050d1fe0666a25ed961e01e7c9eb1e34d549acb915e3906eb226731b3c`.
  A real elevated Scheduler interpreter probe then returned zero.
- Signed Deploy `c1810716f21809e00797de7d64d7c199eede5f07` maps the validated
  boot phase token to the controller's existing private dump-name allowlist.
  Exclusive creation, unique boot directories and retained restore identities
  are unchanged.
- Signed Deploy `92c48470766265bbb56c5538f2a714f23f9b6ac6` distinguishes the
  exact pre-start status bytes from a new process observation. It retains that
  bounded snapshot without changing its timestamps. Only its exact SHA-256 is
  excluded while waiting; every different candidate keeps the original
  identity, freshness, advancement and finite-wait checks. The 120-second
  runtime-status limit is unchanged; this does not alter execution freshness.
- The administrative installer needed process-local `PATHEXT=.EXE` in its
  sanitized Windows PowerShell 5 environment. Plan-only diagnostics reproduced
  the failure and passed with only this addition. Machine/user environment and
  execution/security policies were not changed.
- Runtime source verification outside Codex could not execute the configured
  signing helper. Only `kairos-core`, `kairos-persistence` and
  `kairos-quant-scouts` received a repository-local public
  `C:/Program Files/Git/usr/bin/gpg.exe` setting, matching Deploy's existing
  configuration. Each has one main worktree; no other worktree was changed.
  The former absence of each local setting and its recovery instruction are
  retained in `public-git-verifier-3652-v2.json`. Global unattended signing
  configuration and private key material were not changed or copied. Source
  commits continue to select the existing unattended signer explicitly.

The interpreter junction is a repair of this computer's installation, not a
portable server runtime or a guarantee after deleting/resetting Codex's cache.

## Actual data and restart checks

The existing accepted 173,164-row historical seed was imported into a new
database and queue. Real public Binance history was caught up for BTC, ETH,
SOL, BNB and XRP. The native backup contained **427,589 event-audit rows**;
all **33 public tables**, sequence state and controlled schema matched the
isolated restore. The accepted schema is `current-controlled-v1`, **19
migrations**, not an assertion that every production migration/service ran.

Native qualification confirmed duplicate delivery without a new inbox row,
hash-conflict refusal and Redis acceptance replay with the same identity.
The owned stop/start rehearsal then completed backup/restore before and after
history-only catch-up, unchanged queue/original-history boundaries, PostgreSQL
integrity checks, Redis-state checks and a fresh advancing worker status.

| Observation window | Elapsed | Healthy samples | Separately retained nonhealthy samples | Sampled settling |
| --- | ---: | ---: | ---: | ---: |
| Before owned restart | 312.110 s | 11 | 1 | 2.750 s |
| After owned restart | 309.594 s | 11 | 2 | 5.594 s |

All five watermarks advanced in each window. Intermediate
`CATCHING_UP_NONTRADING` snapshots are not counted as healthy; these bounded
observations are not a continuous-availability percentage or a long soak.

## Windows task and retained failures

`Kairos-CurrentRuntime-3652db457195-Boot` is bound to this exact receipt,
source inventory and signed host report. Read-back verified the same user,
Highest/Interactive principal, hidden `pythonw -I -B` action, user-specific
logon trigger, two-minute delay, IgnoreNew, zero retries and no catch-up trigger.
It is not a pre-logon service.

The original administrative installation failed before creating a task or
binding. Its failure remains in
`host-acceptance-4538a6ecfaa14b81b3185865113165e2/acceptance.failure.json`.
After the environment-only diagnosis, a separate administrative completion
accepted the already completed gates for the **same known, healthy owner** and
registered its task. That completion created no epoch and started/stopped no
container. It did not erase or relabel the original failure.

The first actual scheduled action returned one because source verification
still selected the Codex-only signing helper. The failed result remains in
`scheduled-action-3652db457195-v5/report.json`. An independent read-only
Scheduler-context diagnostic confirmed the failure, then passed after the
scoped public-verifier correction. One post-fix execution of the unchanged
task returned **`LastTaskResult=0`**, with **zero container starts and zero new
boot epochs**. Unknown/live attempts were not retried. Temporary diagnostic
tasks were removed only after known completion; their XML definitions remain.

**No actual Windows reboot was performed.** The evidence covers an owned
container restart and a manual execution of the real logon action while the
runtime was already healthy, not an observed OS reboot/logon sequence.

## Receipts and engineering verification

Paths below are relative to `D:/Kairos/runtime/prod-runtime-inputs-20261024/`.

| Evidence | Receipt |
| --- | --- |
| Host acceptance, signed | `host-acceptance-df4dd06f2186482f8e60e9eaf625ef68/acceptance.report.json` |
| Post-fix actual scheduled action, signed | `scheduled-action-3652db457195-v6/report.json` |
| Independent unpackaged read-only admission | `scheduled-context-3652-v2/report.json` |
| Interpreter-only Windows launch, signed | `python-host-namespace-33c92b9266854b45a12b21432c0d653d/report.json` |
| Final current-status snapshot and closeout, signed | `current-host-closeout-3652-v1/` |

The closeout binds each receipt's SHA-256. The native receipt is under
`D:/Kairos/runtime/current-runtime-20261024/run-3652db45719547b18fad1d6ff10ea002/`,
SHA-256 `48365064e996b85ea1301c9a43aaa7d7865ffe0c7291d5083a5a68b2f771de3c`.
Its boot receipt and original pre-start snapshot are also signed. Older
failed owners, partial evidence, backups and volumes remain separate and
retained; this does not retrospectively accept the old guarded recovery.

Deploy passed **1160 local tests, 8 existing skips**, focused Ruff checks and
[Windows/Linux and affected Docker CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40144017024).
The current release manifest records the signed source set; all 14 main
checkouts were verified clean and equal to their local `origin/main`.

## Still outside this acceptance

There is still no independently qualified, registered real upstream producer
for the signed production input envelope. EVEDEX account/economics and exit
evidence remain subject to the existing fail-closed verifier gaps; credentials
alone do not qualify them. See the existing Execution
`docs/PRODUCTION-PATH.md`. This data worker is not the deployed
Text/Macro/Router/review/LIVE-Risk decision chain. Existing R7 alert configuration
was preserved, not silently retargeted to this owner; new-owner alerting is not
claimed qualified here. Actual OS reboot acceptance is also open.

No frozen plans/evaluators or V2/V4/V5 ledgers were changed, no blind PnL was
read, and the paused forward research automation was not resumed. Successful
technical runtime recovery does not establish alpha, security completion,
venue qualification, capital limits or permission to trade real money.
