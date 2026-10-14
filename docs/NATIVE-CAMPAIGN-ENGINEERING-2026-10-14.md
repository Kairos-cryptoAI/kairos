# Native campaign composition: engineering acceptance, 2026-10-14

**Accepted:** the bounded, explicit native SIM/A/B engineering composition.
**Not accepted:** paid model quality, economic A/B, a new blind campaign,
trading runtime, PAPER, alpha or LIVE.

This closes the native-component gap in the October 13 offline campaign bridge.
It does not replace that historical receipt or rebase an enrolled campaign.
The implementation is [a separate package](../development/native_campaign/README.md);
the [machine-readable receipt](../reports/native-campaign/2026-10-14/engineering-receipt.json)
binds the accepted source and local artifacts.

## Actual components and retained boundaries

The pinned causal Strategy evaluator, Router projection, `CandidateReviewBrain`,
`LLMGateway`, shared PostgreSQL usage ledger, `SimulationRiskPolicy` and
Persistence journals execute together. OHLC, NEWS/MACRO producer messages,
Responses-shaped model replies, token usage and equity are synthetic. Actual
Text/Macro extraction and paid provider behavior are not established by them.
The finite no-network transport is the only permitted model transport.

Three preregistered arms use the same captured bundle and one original strategy
evaluation: strategy-only, strategy-review and separate proposal observation.
ALLOW/VETO/DEFER and conflict handling are checked; an opposing strong Text
signal turns the fixture's model ALLOW into DEFER. A quiet strategy opens no
review call but retains the independent proposal observation. Proposals never
reach Risk. No admission, execution command, trade or venue order is created.

The diagnostic Risk lane preserves stop-based sizing, 0.25% per-trade and 1%
aggregate ceilings for an explicit hypothetical snapshot. This is not actual
portfolio reservation, live-account sizing, a profitability requirement or a
chosen strategy. The existing Range Mean Reversion configuration is unchanged.

The shared fixture ledger retains its synthetic historical adoption, committed
costs and ambiguous reservations across reconnect. The real account ledger is
not adopted, reset or modified. Quota denial occurs before START/dispatch;
UNKNOWN attempts are not resent. Missing/late arms remain in the denominator.

The original bar anchor, frozen source cutoff, real routing/context observation,
provider response and PostgreSQL write clocks remain separate. Source payloads
and availability are rebound on replay. Static prompt-artifact identity and the
actual compiled request hash are distinct and both retained.

Recovery first checks the exact saved receipt, enrolled source identity,
prepared PG16 target marker, original source bundle and entire sealed bar/book
chains. It then completes persistence from saved bytes without another model,
evaluator or budget attempt. The final negative case corrupts an unrelated XRP
book chain: even though the saved BTC bar page is intact, adoption fails before
Risk/review writes. No automatic repair occurs.

SimulationRepository queues only its normal tape/session/Risk diagnostic
artifacts in this disposable database. They remain unpublished. No consumer,
publisher, legacy/runtime queue, lease or cursor is accessed.

## Local acceptance and independent hosted gates

Exact installed non-editable wheels are checked before/after native execution;
Python `-I` and importlib test loading reject working-tree import substitution.
Each native run starts with a different empty UUID4 PostgreSQL 16 database and
the existing RESEARCH_CAMPAIGN migration profile. The owned test container was
limited to one CPU and 1 GiB, without user volumes or trading services.

| Final Windows target | Pure contracts | Native PostgreSQL target | Native duration |
| --- | --- | --- | --- |
| Python 3.11.15 | 14 passed, zero skipped | Exactly 1 passed, zero skipped | 34.779 s |
| Python 3.14.7 | 14 passed, zero skipped | Exactly 1 passed, zero skipped | 41.700 s |

Ruff and format checks pass. The existing offline bridge's 12 tests still pass.
Dependency-only QA passes Aggregator 97, Text Scouts 97, and Macro 92 plus one
unconfigured opt-in database drill skip. Deploy runs 980 tests on each Windows
Python version: 972 passed and eight skipped; all four affected validators and
three locked gate-environment checks pass. No third-party version was upgraded.

The exact implementation commit is
`3d8e74be8dd7434063591a737f7f7e16d164c337`. Its independent Ubuntu 3.11/3.14
[native campaign workflow](https://github.com/Kairos-cryptoAI/kairos/actions/runs/38523720662),
[Meta validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/38523720523)
and CodeQL completed successfully. Each hosted native job enforced an actual
one-test PASS, not a skipped target.

The narrow LLVM extension hooks preserve the default review schema and existing
source-bound scheduler identity calculation for default callers. Module hashes
necessarily change with source changes: an old enrolled campaign does not
inherit the new code or identity. The separate budget fix classifies the
actual Persistence `SourceBudgetExceeded` as known reservation denial, rather
than ambiguous model spend. Current LLVM is signed
`c2207a5bd8bbf39e7d5728f95e52c96a47eca344`;
[its exact-source CI](https://github.com/Kairos-cryptoAI/kairos-llm/actions/runs/38518792624)
passed.

The new LLVM revision is propagated through the signed leaf repositories and
all affected active Deploy locks/projections. The initial Deploy commit's
[failed remote-lock check](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38520777702)
is retained as failure evidence; it found stale transitive leaf pins, not a
native trading failure. After the pin cascade, signed Deploy
`41a87675acdbf62bdc7a403af0b9597baecb758b` passed
[general CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38523441910),
[current-source gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38523442025),
[full-path SIM gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38523442205),
[Text/Macro/Router/review/Risk composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38523442043)
and CodeQL. Validators were not weakened.

## Retained attempts, cleanup and release limits

The first local 3.11 attempt failed a test assertion: its budget snapshot was
taken before a legitimate synthetic response cost was committed. The assertion
was corrected to snapshot after that response and before connection close;
the failed JUnit and synthetic dump remain retained. Later successful runs are
separate targets, not rewritten failures.

Final JUnit reports and synthetic fixture dumps remain under
`D:/Kairos/runtime/native-campaign-20261014`. Each final fixture intentionally
ends with the negative book-chain corruption. CUSTOM archive TOCs were readable,
but the Timescale circular-FK warning was retained: these are **archives, not
verified backup restores**. The acceptance proves interrupted-write plus real
connection close/reopen recovery, not process kill, host/power loss or a physical
restart. Only the owned temporary container and its two owned networks were
removed after export; no user volume was removed.

All 14 repository HEADs, canonical origins, actual remote main SHAs and trusted
GPG signatures were checked. Manifest/Deploy source projection passed. However,
the full `Test-CurrentRelease.ps1` still correctly fails closed on preserved
unfinished work: 43 adaptive WIP files in Meta and one untracked status entry in
each of Execution and Quant. The adaptive aggregate hash is unchanged:
`f78ea4182e3fa68a18194cdf4dc8b5fb5e40e2651415b3cc23893fc7098e2eb7`.
Those files were not adopted, stashed, deleted or committed by this work.

No primary/legacy database, Redis, R7 runtime package, old queue, frozen Trial 15
or quarter-hour V2/V4/V5 identity/plan/ledger was changed. No key file was opened
for this native gate, and no key value was printed or sent. There were zero paid
OpenAI/DeepSeek/X calls, authenticated
EVEDEX actions, orders, canaries or readiness promotions.

Remaining research acceptance needs original point-in-time input evidence,
explicit strategy/evaluator/cost preregistration, real provider qualification
under the adopted budget and a separately enrolled immutable campaign. Real
portfolio reservation, execution/fill economics and crash/restart coverage are
separate gates. No own 365-day/500-natural-close requirement is reduced or
credited from this fixture. Five-symbol venue qualification, off-host backup,
production security/limits and owner arming are still required for LIVE.

`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`; trading stays off.
