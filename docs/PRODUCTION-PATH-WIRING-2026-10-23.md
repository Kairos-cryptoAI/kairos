# Unified LIVE Risk / protective lifecycle — 2026-10-23

_Continuation started October 23; final local verification completed October 24
in Europe/Moscow. UTC source/check identities remain explicit below._

## Scope

The owner requested connection of independent LIVE Risk and protective exits
to the existing PROD path while the EVEDEX clarification remains outstanding.
This continuation changes only current engineering composition, not strategy,
frozen research, readiness, venue qualification or permission to send orders.
Earlier [LIVE Risk](PRODUCTION-LIVE-RISK-2026-10-23.md) and
[accounting/transport](PRODUCTION-SOURCES-ACCOUNTING-2026-10-23.md) receipts remain
historical and are not rewritten as composed real-venue acceptance.

No real wallet/API key, exchange mutation, paid model/feed, PAPER/LIVE service,
primary/legacy/R7 database or old queue was used. The retained non-trading
successor and paused campaigns/automations remain separate. This work does not
repeat the already sent support inquiry.

## Implemented path

`ProductionLiveLifecycleCoordinator` invokes the concrete entry publisher and
`LiveRiskEvaluator` with raw account/input proofs, not an externally approved
decision. The owner-signed arm is checked against the runtime's independently
pinned public owner key; its digest is derived rather than trusted from the
caller. The accepted durable nonce/current operator and Risk/exposure evidence
are independently inspected before the existing FSM handles the decision.

The existing FSM now calls `ProductionPreparedExitRiskStager` only after an
atomic **new** `PREPARED` SL/TP/timeout/emergency effect, before reserving a
mutation or dispatching it. Cached effects do not restage; an older uncertain
PREPARED remains authoritative-recovery-only. The mandatory capture provider
passes raw evidence to the existing independent exit verifier/publisher. It
cannot supply an approval boolean or reuse ENTRY Risk for exits.

Exit ownership is derived from the immutable original ENTRY binding, validated
against exact context, decision, custody, effect/client IDs and wire geometry
at its original timestamp. An optional legacy digest only asserts equality.
An expired original ENTRY plan remains ownership history; it is never renewed.
Fresh per-effect exposure/economics and accepted original owner lineage are
still necessary. SL precedes TP; failed protection may attempt only its own
separately evaluated emergency close.

Entry Risk now exposes the independently verified input observation timestamp.
Its signing lease is additionally capped at that original observation + five
seconds, not stage time + five seconds. Existing account five-second and
market-data two-second limits are unchanged. Entry and exit staging recheck
deadlines after asynchronous writes/authorization. Runtime, stager and FSM
share one clock; a divergent runtime time base is refused.

Recovery and closed-account reconciliation delegate to the existing engine;
no new service loop, retry policy, migration or queue is introduced. Fresh-v3
accounting releases the exact original reservation only after independently
accepted terminal/account evidence, once. ACK alone is never a fill or release.
The source callback must not reacquire FSM/account/trade locks. Separate roles
and short SQL transactions are preserved.

The full native composition exposed a real latency failure before signing:
eight repeated authenticated reads consumed almost all of the two-second quote
lease. The producer-contract check previously made 126 sequential privilege
queries per snapshot. Its exact role/table privilege matrix is now fetched in
one uncached SQL statement in the same snapshot, while role isolation, expected
SELECT/INSERT, forbidden mutation privileges and schema CREATE checks remain.
No authorization boundary, one-use claim or TTL was removed or cached.

It also exposed a cancellation freshness defect: a fresh venue snapshot could
legitimately postdate the clock captured before durable lineage I/O, yet be
rejected as future-dated. Cancellation now compares to monotone post-capture
time and repeats the final freshness check. Source timestamps are not
backdated; actually future/expired snapshots and clock regression still refuse.

The first real journal-backed protective stage exposed another integration
assumption hidden by memory fixtures: the FSM records a protective client/server
association after confirmation, not at PREPARED. The publisher now derives the
exact planned SL/TP client ID from the original decision timestamp. An unset
pre-confirmation client is permitted; a foreign stored or prepared client is
refused. No confirmed protection record is fabricated.

PROD redelivery now recognizes an existing non-RECEIVED trade under its original
locks, verifies its chain, exact scope/canonical decision and startup recovery,
and delegates to the existing recovery path before demanding a new-entry quote.
This does not renew an entry or create a new Risk decision. New/RECEIVED entries
retain their original quote freshness and admission checks. PAPER behaviour is
unchanged by this PROD-only override.

## Acceptance boundary and remaining work

Current pinned EVEDEX account/exit/history verifiers still refuse evidence that
does not establish the required atomic account, history membership, funding,
original-parent and replay contracts. No support answer or synthetic verifier
can be substituted for those facts. A separately qualified upstream-input
producer is also required; hashes alone do not authenticate its observations.

The unified coordinator refuses a lifecycle without the concrete exit stager.
The legacy opt-in manual API and PAPER defaults remain compatible, not the new
path's fallback. Actual target-host/service acceptance, concrete owner limits
and manual arming remain separate. All readiness flags are false and
`STRATEGY_POLICY=REJECT_ALL`; no real order was submitted.

## Verification

Synthetic account, market,
signing backend, venue and terminal evidence are not real EVEDEX acceptance,
an economic test or a natural trading lifecycle.

The complete native acceptance passed first in fresh database
`kairos_production_evidence_5e61fafb79ee`, then independently from the noneditable
installed package in `kairos_production_evidence_ee630f83c7a5` (11.93 seconds).
It uses actual Persistence RUNTIME migrations/journals, independent SQL
operator/Risk/exposure/reconciler/accounting roles, passive bindings, managed
authorization, durable one-use claims and the protected FSM. Only the source,
signing backend and venue/terminal facts are explicitly synthetic.

Accepted sequence: entry Risk → partial fill → independent STOP Risk/wire → TP
Risk/wire → natural five-second **synthetic fixture** timeout → independently
evaluated close → FLAT → terminal/account receipt → reserve release. It does not
shorten any real strategy's holding period. Four request-bound Risk rows, four
typed-signing claims, five wire claims (including the owned entry cancellation)
and one accepted release were present in the final installed fixture. A new
engine and a new stager over the retained database completed startup recovery
and replay without adding Risk rows, claims or venue calls.

The same native fixture individually verifies rejection of each forbidden
writer privilege (UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER), wrong INSERT,
missing/unexpected SELECT and schema CREATE using actual PostgreSQL grants.
Each exact fixture grant is restored before fresh quote generation. Version-2
and version-3 SELECT contracts, incomplete/duplicate/foreign privilege rows,
clock divergence/regression, expired proofs, source refusal, foreign owner
binding, unconfirmed deterministic protection IDs and stale new entries have
separate focused coverage. The noneditable installed modules were compared
against source with Git line-ending normalization; no sibling PYTHONPATH or
CURRENT campaign-environment substitution was used.

Only newly created container `kairos-prod-wiring-test-20261023`, exact ID
`f671dc0f11d8dfb5a5fb2df2390eeec3cf5f6875cbc36e79f398d3d13d7fbd4f`, was stopped
after checking its ownership/synthetic labels. All failed and passing fixture
databases remain retained; no schema/data/queue was dropped or reset. Earlier
fixture permission, canonical-data, latency and producer-sequencing failures
are not relabelled as successful results. Local JUnit artifacts are retained at
`D:/Kairos/runtime/prod-path-wiring-20261023`, including
`native-path-final.xml` and `installed-native-path.xml`.

Final noneditable Windows/Python 3.11 regression with all optional adapters:
**1009 passed, one platform-specific skip, 53 integration tests deselected and
eight subtests passed** (62.90 seconds). Ruff, format check, mypy (58 source
files), Bandit and source/wheel builds passed; 38 existing Node sidecar checks
also passed. These are engineering checks without a real exchange/model call.

Risk source `ef4365979069c601101b6f3a3560afa9bd67777f` and Execution source
`53dc2d9bd73652907c6d8c197d9321ebc23fdd9f` carry trusted GPG fingerprint
`40AF365C6682B73D056A6A274DBFF6B65BE9F827`. Risk's 316 tests and
[Windows/Linux CI](https://github.com/Kairos-cryptoAI/kairos-risk-manager/actions/runs/40020776492)
plus [CodeQL](https://github.com/Kairos-cryptoAI/kairos-risk-manager/actions/runs/40020776627)
passed. The active Execution dependency lock pins that exact Risk commit.

Execution's exact signed source passed its complete
[six-job CI](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/40026125228):
Windows/Python 3.11, Linux/Python 3.11 and 3.14, all exchange adapters, Node/pinned
SDK parity and actual TimescaleDB journal/lifecycle integration. Its
[CodeQL](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/40026124944)
also passed. Hosted synthetic service tests are not real-account acceptance.

Deploy source `9f159eb97ebd01923e690797a83457bf71b9be67` is trusted-GPG-signed
and aligns the active runtime/PAPER projections, current-release/full-path/
Text-Macro source locks and three active uv locks. Six local validators,
62 validator unit tests and all three lock checks passed. Its
[main CI/image builds](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40026498072),
[current-release gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40026498119),
[isolated full-path gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40026498087),
[Text/Macro composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40026498095)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40026497836)
passed. No local service was started and the historical release-gate locks
were left untouched. Meta's current-chain lock is aligned without installing
or resuming its paused real-news campaign environment.
