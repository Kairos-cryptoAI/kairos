# Remaining non-strategy launch work — 2026-10-18

This is a current engineering/operational gap register, not a new research
direction, execution plan, order authorization or relaxed acceptance policy.
Strategy selection, economic optimization and long trading tests are excluded
from the work list below, not waived from eventual LIVE admission.

**October 21 credential update / October 20 owner scope:** [implemented engineering and current blockers](ENGINEERING-CONTINUATION-2026-10-20.md).
The existing PROD account/API identity is now verified read-only; the supplied
owner key matches its wallet, and the separate supplied EVEDEX signing entry
matches the visible One-Click export mask. No new credentials are requested.
That is not full signing/delegation acceptance or production runtime wiring.
One deployment server is the target. DEMO book availability and elapsed DEV
campaigns are no longer mandatory engineering prerequisites; existing SIM is
used for finite lifecycle checks. Independent backup hosting and cloud KMS are
not required purchases. Full-host-loss resilience is explicitly not established.
The separate historical V1 policy and research evidence are not rewritten.

Durable Text no-resend, signed owner-request validation, local encrypted signing
and the native lifecycle/claim plumbing have bounded acceptance. They are not
the fully composed production service. The latest non-trading generation failed
closed at **22:47 MSK October 20**; earlier successful recovery/postserve receipts
are not present uptime. Strategy and elapsed scientific gates remain separate.

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
| Stable non-trading runtime | Diagnose the new bounded Redis transport failure and separately admit a fresh recovery/generation with preserved history and queue proofs. Validate restart on the actual single-server target. | Do not retry UNKNOWN_PARTIAL, relax a timeout to hide the error, edit executed snapshots or touch the legacy database/queue. |
| Full deployed current-context path | Accept the existing feed/Text/Macro/Router/review/Risk composition with authentic provider/account bindings and the already adopted durable budget. Text no-resend has a native restart proof; fixtures do not establish the whole running provider path. | No extra strategy family, UI or paid-call authority is implied. Preserve prior spend and reservations. |
| Guarded production execution | Wire concrete current operator/risk signing authorization, a one-use capability issuer and the production lifecycle executor/service composition. The factory still rejects LIVE; both evidence verifiers remain validation-only. | Local encrypted signing and SQL claims are implemented components, not complete production execution. Do not remove the startup refusal without the composed checks. |
| PROD signer admission and protected custody | Basic account/API/owner-wallet identity is read-only bound. Finish the dedicated One-Click signer/delegation proof, provision the encrypted keystore/unlock files separately from DEV, and resolve released SDK 42161 versus current upstream 161803 signing-chain drift against the actual PROD verifier. | Do not select the owner key for the bot, treat a masked One-Click match as full authorization, or guess the chain. General-purpose keys.txt is not an approved encrypted keystore. No cloud KMS purchase is mandatory. |
| Single-server operations | Exercise local supervisor restart, process failure/escalation/resolution, kill switch and encrypted local restore on the final host. Match all source/image identities and confirm no unexpected exposure. | No independent watchdog/off-host service is claimed or required by this profile; full host loss can stop both service and its local monitor. |
| Owner arm before real money | Bind explicit dollar-cap, daily loss stop and one-use manual arm only after the strategy and technical evidence are accepted. | Amounts are not chosen by LLM confidence or automatic capital ramp. Their absence does not block source preparation, but blocks real dispatch. |

## External decisions versus local engineering

Existing-component integration and bounded fault tests can be developed without
a month-long campaign. Real identity, provider and target-host acceptance cannot
be manufactured from fixtures or old receipts. PROD identity/environment is now
verified read-only from the existing account and supplied file; that clarification
is no longer requested. No independent backup
subscription, replacement exchange, cloud KMS or DEMO campaign is required by
the new single-host scope. Later owner capital/stop-loss settings block arming,
not routine code preparation. Production funding is not needed for offline tests.

A bespoke BuildKit adapter, new strategy families, UI/UX, TradingView integration,
and rewriting Trial 15/V2/V4/V5 are not extra launch gates introduced here.
The existing source/build/deployment evidence must still match the final chosen
release; green historical fixtures do not automatically transfer to another one.

`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL` remain unchanged.
