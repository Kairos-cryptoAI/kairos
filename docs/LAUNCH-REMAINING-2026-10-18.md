# Remaining non-strategy launch work — 2026-10-18

This is a current engineering/operational gap register, not a new research
direction, execution plan, order authorization or relaxed acceptance policy.
Strategy selection, economic optimization and long trading tests are excluded
from the work list below, not waived from eventual LIVE admission.

## Accepted scopes, not work to repeat

- Signed source identity and clean-main verification across all 14 repositories.
- [Separate non-trading recovery](RECOVERY-2026-10-18.md), fresh isolated restores,
  real closed-bar progress, guarded boot and scheduled technical monitoring.
- [Existing-component isolated SIM composition](STATUS.md): causal-context
  refusal, Router/review/Risk and durable simulator mechanics on synthetic inputs.
- [Native local encrypted Restic restore](ENGINEERING-CLOSEOUT-2026-10-13.md).
- [One new Telegram test](TELEGRAM-DELIVERY-2026-10-18.md): API acceptance of
  message 89 and direct owner visibility confirmation, with one send/no retry.

These do not mean that a complete real-provider trading service is deployed.
No old failure, research ledger, strategy or legacy queue needs to be rewritten.

Later on the same day the previously accepted worker failed closed at 22:55
Moscow (`REDIS_RECOVERY_DEADLINE_EXCEEDED`); its PG/Redis containers were also
observed stopped at 23:32. Current runtime uptime is not accepted. Preserve the
failed worker/evidence and independently diagnose/adjudicate recovery before any
restart. The existing boot binding still names the previous Deploy source;
updating engineering source locks below does not rebind or authorize that task.

## Remaining implementation and short acceptance

| Item | Concrete remaining work | Boundary |
| --- | --- | --- |
| Real DEV venue and identity | Obtain an officially supported no-real-funds route for the exact five required instruments, then accept dedicated account/API/signing pairing and current reconciliation. The latest snapshot has empty SOL/BNB/XRP books; the separately reconciled three-pair Demo is not a substitute. | External venue/account prerequisite; no extra key values are requested in chat. [Venue evidence](EVEDEX-DEV-PROGRESS-2026-10-18.md), [support scope](EVEDEX-NONTRADING-CLOSEOUT-2026-10-13.md). |
| Real observation recorder | Code wiring is implemented in Execution `f5c100f`: existing Quant measurements, actual scoped SQL health, authenticated flat-account GETs, duplicate-process lock and the unchanged repository receipt. Still provision/admit the separate exact target/account and collect the real 24-hour window. | Engineering tests do not establish venue identity, book availability or elapsed observation. See `kairos-execution-engine/docs/READONLY_RECORDER.md` and the [continuation](ENGINEERING-CONTINUATION-2026-10-18.md). |
| Full deployed current-context path | The current Compose profile now explicitly requires NEWS and Macro in review, with missing/false/empty-setting regressions. Still assemble and accept the running isolated profile with actual feed/provider bindings, adopted durable budgets and account/venue facts; persistent Text dedup/no-resend across process loss needs bounded acceptance. Synthetic end-to-end proof is not running-service/provider-quality evidence. | Reuse existing Strategy/Text/Macro/Router/review/Risk/Execution components. Historical paid order-book archives are not prerequisites for beginning DEV venue tests. |
| Short DEV execution coverage | After venue admission and separate bounded arming, prove actual cancel, protection, timeout, partial-fill/restart and reconciled round trips under the fixed canary plan. Requests for a scenario do not prove its execution. | Test-funds DEV only; not authorized or started by the Telegram/status request. The elapsed 24-hour/seven-day gates remain separate. |
| Guarded production execution | Implement and qualify the actual production activation/execution boundary after its evidence gates. `ExecSettings.validate_execution_boundary` currently rejects `TradingMode.LIVE` unconditionally; `ProductionPreconditionsVerifier` returns validation-only, never mutation authority. | This is real remaining code/integration work, not merely changing `LIVE_READY` or removing the startup rejection. Preserve risk, custody and explicit owner arming. |
| Host, custody and disaster recovery | Choose the deployment host and a genuinely independent encrypted backup destination; deploy managed DEV/PROD secret separation, recovery-key custody, retention/RPO/RTO and perform an actual remote snapshot readback/full restore. | Local Restic works, but the owner has not supplied an independent destination. Deploying everything to one host alone is not off-host protection. |
| Production operations and final release | Qualify an independent host-loss watchdog, actual firing/resolved/restart delivery and kill switch; review security and production account pairing. Bind owner capital cap/daily loss stop, source/image identities, exact affected Windows/Docker/CI evidence and manual arming to the final target deployment. | No real-money canary or automatic capital ramp. A successful Telegram test alone does not qualify the whole alerting/disaster-recovery path. |

## External decisions versus local engineering

The real-source recorder, existing-component deployment integration and bounded
fault tests can be developed locally without a month-long campaign. Their real
venue/provider acceptance cannot be manufactured from fixtures or old receipts.
Host/storage/custody choices, an officially supported DEV route and later owner
capital/stop-loss settings require actual external inputs. Production secrets
and funding are not needed for the current Telegram test or code preparation.

A bespoke BuildKit adapter, new strategy families, UI/UX, TradingView integration,
and rewriting Trial 15/V2/V4/V5 are not extra launch gates introduced here.
The existing source/build/deployment evidence must still match the final chosen
release; green historical fixtures do not automatically transfer to another one.

`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL` remain unchanged.
