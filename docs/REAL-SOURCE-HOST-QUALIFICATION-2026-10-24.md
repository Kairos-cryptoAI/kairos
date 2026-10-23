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

One finite real cut ran at **01:09:38–01:10:38 Moscow**, 60.25 seconds, under
signed Meta `64e68276d0c099e4ad5c48537f3cbd1298a23cbb`. It made 24 public GET
attempts and zero paid calls, orders or SIM/database operations. The original
summary remains unchanged with SHA-256
`55dcafe188fabc637d7abfd8681a9a9dcf1900d0b209a73fd3fc69d76a0b712a`.

| Real source | Observed result and limit |
| --- | --- |
| Binance closed bars | All five symbols have 3,240 validated, gap-free closed 1m bars each: 16,200 bars and 15 original page receipts. This is the returned 54-hour window only. |
| Binance REST depth | Five original responses and native depth receipts were retained. A new report-field bug raised `AttributeError` after successful capture; separate offline adjudication below verifies the original bytes, not a new quote. |
| Cointelegraph RSS | 30 original items retained; zero within the original 30-minute window and zero selected by native Text. Nothing was made fresh and no model was called. |
| CoinDesk RSS | The first configured trailing-slash endpoint was refused by the native reader. No raw response body/status was retained for that refusal, so its exact HTTP cause is not asserted. |
| Federal Reserve | The existing official monetary-publication feed returned HTTP 200 and parsed. It supplies publication summaries, not a complete numeric macro feed. |
| BLS CPI | HTTP 403; explicitly unavailable, never a zero/neutral CPI measurement. No challenge, proxy, redirect or access-control bypass was attempted. |

The depth report bug used nonexistent `EntryQuote.observed_at_ms`; the native
DTO exposes `event_ms`. The report now uses that actual field and its regression
fixtures construct a real `BboCapture.quote` instead of inventing the missing
attribute. Implementation exceptions now abort the probe rather than being
misreported as source unavailability for each next symbol.

An independent, signed offline actor rechecked exactly the five original depth
receipt/body hashes, E/T clocks, BBO geometry and native BBO construction. All
passed with original event-to-receive ages **103–113 ms**. Its receipt is
`depth-adjudication-20261024/original-depth-adjudication.json`; it made no network
request, changed no old receipt and explicitly cannot be a fresh execution
quote, continuous-book proof or LIVE admission. No full cut was rerun to obtain
a more favorable outcome.

The probe also now chooses the exact already-configured canonical CoinDesk
alias, without following redirects or inventing an endpoint. A separate signed,
one-GET diagnostic of that alias returned HTTP 200 at **01:17:51–01:17:54
Moscow**, retained 25 items and selected zero under unchanged native freshness
and relevance rules. Its raw response SHA-256 is
`45efc2155402c30c9265eab9bdf4e154679ffbc89facda6301f629ad0982676b`.
The diagnostic does not replace the initial refusal, refresh old news, rerun
the full cut or prove the first endpoint's unrecorded HTTP status.

The first reader counter reported 2,165,017 accepted bytes; it excludes a
refused response body. Including that response's existing 2 MiB maximum and
one possible overflowing 64 KiB read chunk gives a conservative 4,327,705-byte
application-read payload upper bound, not a socket/TLS ingress measurement.
The corrected probe charges refused bodies conservatively before admitting
another independent request, reserves missing official-capture accounting
rather than recording zero, and reserves chunk-overflow headroom before a GET.
The unchanged official-context reader also gets one reserved overflow chunk
per attempted source. Its retained-byte count remains distinct from this
conservative application-body budget; network buffers/protocol bytes are not
measured or described as bounded ingress.

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

A later current-parser call returned `invalid`, age 7.423189 seconds and
`stale=false`. Its exact input bytes were not retained, so the failed invariant
is unknown; it is not reclassified as a pass. One separate bounded, immutable
820-byte sample was retained at **01:25:30 Moscow**, SHA-256
`743370122540096ab6713d746718dfe2497c297e2b6c2ebc4cb7b28cc3be4945`.
The current-source parser accepted that sample as `running`, age 11.019497
seconds: 3,254 cycles, 4,415 completed records, five equal watermarks and zero
pending/unresolved/uncompleted counters. No repeated sampling until success
was performed. This later sample cannot adjudicate the earlier missing input
or establish stable operation over an interval. The diagnostic preserves both
facts; runtime stability acceptance remains open.

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
green engineering CI and individual passing historical-worker samples do not
replace these. The unadjudicated invalid status sample also prevents claiming
that this observation established stable runtime operation.
Concrete capital limits and owner arming remain separate from this work.

Every readiness flag remains false; `STRATEGY_POLICY=REJECT_ALL`. The retained
evidence parent is `D:/Kairos/runtime/real-source-host-qualification-20261024`.
Old failures, partial artifacts, database/queue state, campaign environments and
all original research evidence remain preserved.

## Local verification and retained artifacts

The final bounded-probe implementation is signed Meta
`4695a51c0dddc0b7bbcde3375de46b8b1d48be77`; its installed noneditable module
matches the source after Git line-ending normalization, SHA-256
`27a2adb8afa06ebe4407eb42d729faaeed6cf0cdaea3e2f47b45025662f28246`.
This does not change the original real cut's implementation identity or
retroactively rerun that cut with corrected code.

The corrected noneditable source package passed **17 focused tests with one
Windows directory-symlink privilege skip**, plus Ruff lint/format. Tests cover
native BBO DTO compatibility, original event clocks, canonical approved feed
selection, conservative charging of refused HTTP bodies and pre-request
overflow headroom, no extra requests
after implementation failure, independent one-shot source refusals, no
overwrite, failed-write partials and preservation of the original exception.
Native capture/macro tests remain separate from actual source observations.
The symlink case is still a platform skip locally, not a claimed Windows pass.
The real output paths passed the unchanged ancestor/reparse checks.

The first wheel-cache collection failure and earlier failed assertion are not
relabeled as passes. A forced noneditable rebuild fixed the stale local package;
the failed overwrite assertion was updated for the explicit publication-error
wrapper while retaining its no-overwrite check. Earlier JUnit artifacts remain.
The final focused result is `source-probe-tests-v5.xml`. No running campaign
environment was modified and no installed package was patched by hand.
That JUnit artifact is signed, SHA-256
`67328f3e9e960f2257cf839481cab0363e0faa3b075f1fdf0625ae61e9c4e49e`.

CI evidence for the exact final implementation is linked independently:
[Windows/Linux current-chain regression](https://github.com/Kairos-cryptoAI/kairos/actions/runs/40033690256),
[native engineering](https://github.com/Kairos-cryptoAI/kairos/actions/runs/40033690340),
[meta validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/40033690238)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos/actions/runs/40033690554).
Those engineering workflows do not produce real-source authority, stable-host
acceptance or trading permission. The documentation-only handoff does not
change the implementation's source identity or original source captures.

| Artifact below the retained evidence parent | Meaning |
| --- | --- |
| `account-20261024-first/observation.report.json` | Signed real account-bound GET observation, no reconciliation authority. |
| `host-initial-20261024.json` | Signed exact-owner historical-runtime observation and image/profile mismatch. |
| `host-status-adjudication-20261024/status-diagnostic.json` | One retained passing sample; the earlier invalid sample has unknown cause and is not replaced by this pass. |
| `sources-20261024-first/source-qualification.json` | Unchanged first real public cut, including the report-field failure. |
| `depth-adjudication-20261024/original-depth-adjudication.json` | Signed offline validation of original real depth receipts, never fresh quotes. |
| `coindesk-canonical-20261024/canonical-feed.report.json` | Signed one-GET native capture of the existing canonical alias. |
| `launch-20261024-first/launch.report.json` | Preserved original finite refusal-harness failure. |
| `launch-import-diagnostic-20261024/import-diagnostic.json` | Signed attribution of blocked import-time Windows metadata probes. |
