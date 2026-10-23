# Real sources and current-PC acceptance — 2026-10-24

This continuation follows the [unified Risk/protective-path implementation](PRODUCTION-PATH-WIRING-2026-10-23.md).
Dates in the title and owner-facing times use Europe/Moscow; artifact clocks
remain explicit UTC. This is a bounded engineering/source assessment, not a
completed real-money launch or a substitute for authentic source contracts.

## Scope and result categories

The owner requested real-source qualification and launch verification on this
computer, with trading still disabled. The checks distinguish four different
claims: a response was captured; its local schema/integrity checks passed; an
independent verifier can authorize LIVE facts; the actual production service
can start and recover on this host. A pass in one category does not imply the
others. No strategy, frozen campaign, budget or admission threshold was changed.

No order, exchange signature, transfer, paid model/feed call, legacy/R7 queue
mutation, retained-database migration, task activation or service restart was
performed. Neither paused automation was resumed. No credential value is
included here or in public source artifacts.

## Actual EVEDEX account observation

One new bounded GET-only actor used installed noneditable Execution
`53dc2d9bd73652907c6d8c197d9321ebc23fdd9f`, after clean-main, exact-origin and
trusted-signature checks. Its observer/readiness/normalizer modules matched
that source with Git line-ending normalization. The existing hash-pinned
in-memory API-key helper and previously accepted account binding were reused;
no wallet signing key was selected, copied or exported.

At **00:54:36–00:54:38 Moscow on October 24**, six sequential account components
passed the existing five-second capture bound. Seven GET attempts include the
initial UUID/auth-ID/wallet-to-numeric-account mapping check. No retry occurred.
Available and funding balances were positive; no amount is disclosed here.
The normalized reply had 22 position records, all zero quantity, no opened
orders, and 330 historical protection records (245 cancelled, 85 done). These
record counts are not newly opened exposure or proof of complete history.

`account-20261024-first/observation.report.json` reports
`PASS_ACCOUNT_BOUND_READ_ONLY_OBSERVATION`, six components, zero orders,
signatures, transfers and paid calls. The private normalized capture hash is
`b86bccedbe9b0fc5a26e3bfb96f17365c54663478f5f6c271f723eba0a5ccae5`.
The actor, report and normalized artifact have detached GPG signatures.

This remains an ordered, bounded observation, **not** an atomic snapshot,
authoritative exposure, complete funding/fee ledger, original HTTP-byte archive
or accepted account reconciliation. The real account/exit verifiers continue
to refuse that promotion.

The [official API types](https://github.com/evedex-official/exchange-api/blob/master/src/utils/types.ts)
still describe funding as coin balances and expose a protection's
`triggerOrder`, not a documented complete original-entry lineage. The
[REST gateway](https://github.com/evedex-official/exchange-api/blob/master/src/exchangeRestGateway.ts)
does not establish the missing coherent-account/history-finality guarantees.
Mutable public sources explain the gap; pinned installed artifacts govern
the implementation. Repeated equal GETs cannot manufacture those guarantees.
The existing support thread was read once: its two visible messages were the
previous sent inquiries, with no received answer. No new message was sent.

## Real free-source availability, not LIVE input authority

This implementation checkpoint does not yet assert a successful public-source
run; the subsequent finite run's actual per-source outcomes must be recorded
before any capture-result claim is made.

The separate opt-in `current_source_probe` reuses the configured public
capture/normalizer/official-context components without constructing a model,
SIM session, database, queue, strategy or campaign. It captures each configured
RSS source once, a fixed five-symbol closed-bar window and depth snapshots,
and the existing official-context roster. Source failures, original bytes and
timestamps remain evidence rather than a reason to retime or replace inputs.

The probe has aggregate request/byte/time bounds, no automatic retry, a new
create-only run identity, and explicit partial-output handling. Its latest
already-completed minute cut does not request a still-open bar. Both the
existing five-second depth-source check and the stricter two-second LIVE
authorization limit remain unchanged and are not called equivalent.

Raw RSS/publication capture does not authenticate a native model response,
MacroStrategist allocation, Router route or candidate review. No complete
authentic feed/Text/Macro/Router/review proof was produced by this source-only
check, and no `VerifiedLiveInputsV1` was manufactured from DTO hashes. Full
upstream LIVE qualification remains unestablished.

## Actual current-PC runtime observation

The signed successor receipt matched its retained SHA-256
`be08ab9803836132178c3f684af928b95d5ba44e7c77df17996adfb2d6deff89`
and trusted fingerprint `40AF365C6682B73D056A6A274DBFF6B65BE9F827`.
Only its mapped owner, exact three container IDs and mapped status path were
inspected. The installed owner-bound parser reported `RUNNING_NONTRADING`,
non-stale status age 11.899 seconds, 3,132 cycles, 4,249 completed inbox records,
equal five-symbol watermarks, and zero pending outbox, unresolved inbox or
uncompleted publications at **00:52:34 Moscow**. All three exact containers
were running with matching owner/scope labels and restart policy `no`.

This is the existing `historical-18-migration-nontrading-baseline` successor.
Its immutable serving image's revision label is
`1ca8bf38d265ece7a95f749a268075549f80c043`, not the current Persistence
`c6773575a09f918b4d495848705b4234f73f3a32`. Its accepted receipt still records
`root_cause_fixed=false` and `production_qualification=false`. Therefore this
observation does not qualify a newly deployed current-release PROD service.

Windows boot tasks remain disabled and bound to previous owners/generations.
The existing boot installer/controller does not accept this successor owner;
its execute path can start containers and is not a read-only duplicate-start
test. No old task was enabled or silently rebound, no new boot task installed,
and no reboot/cold-start qualification is claimed. The existing technical
alert task was not changed or treated as monitoring of this different owner.

## Actual installed entrypoint refusal

A finite, credential-free child invoked the actual installed
`kairos_execution.service` entrypoint with explicit LIVE configuration. It
reached the intended validation error: `LIVE is disabled: this release is not
LIVE_READY`. Audit guards blocked network and subprocess creation throughout.
There were zero network attempts and no production service was started.

The first harness report remains `FAILED_CLOSED`: it also demanded zero
subprocess *attempts*. Two bounded diagnostics attributed the three blocked
`cmd.exe` attempts to aiohttp's import-time `platform.system()` → Python
`platform._syscmd_ver` Windows-version detection. Both still reached the exact
intended LIVE refusal. No child command was permitted, no raw arguments or
environment were recorded, and no implementation defect is established by
this overly strict harness predicate. The old report was not overwritten or
relabelled as successful. This proves refusal, not positive PROD startup.

## Remaining acceptance boundary

Real-money startup is **not complete**. It still requires a qualified venue
account/history/settlement/parent source and an authenticated complete native
upstream decision chain, then a current-source deployed service and its owned
boot/recovery/monitoring acceptance. Source availability, account credentials,
green engineering CI and a healthy historical worker do not replace these.
Concrete capital limits and owner arming remain separate from this work.

Every readiness flag remains false; `STRATEGY_POLICY=REJECT_ALL`. The retained
evidence parent is `D:/Kairos/runtime/real-source-host-qualification-20261024`.
Old failures, partial artifacts, database/queue state, campaign environments and
all original research evidence remain preserved.
