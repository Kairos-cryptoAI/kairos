# Independent LIVE Risk continuation — 2026-10-23

## Accepted scope

The owner authorized a technical follow-up to EVEDEX and completion of bounded
production engineering, including independent LIVE Risk. The
[support receipt](EVEDEX-PROD-SOURCE-SUPPORT-2026-10-23.md) records one Gmail
dispatch, not a venue answer or acceptance. The
[prior transport/accounting receipt](PRODUCTION-SOURCES-ACCOUNTING-2026-10-23.md)
remains historical evidence; its PAPER-only Risk finding describes its earlier
source set, not the additive evaluator implemented here.

No real account key, wallet signer, paid model, exchange mutation or trading
service was used. Old databases/queues, the running non-trading successor,
frozen campaigns and paused automations were not adopted, restarted or reset.
All readiness flags remain false and `STRATEGY_POLICY=REJECT_ALL`.

## Independent entry calculation

`kairos-risk-manager` now has a separate opt-in `LiveRiskEvaluator`, not a
relabeled PAPER result. Both account-source verification and independent
upstream-input verification are mandatory. No production verifier is registered
by default. Scope binds the exact context, source set, policy, risk-limits hash,
account, strategy revision and closed signal/PROD symbol mapping. Hashes identify
inputs; they do not authenticate their producer or grant release authority.

The calculation checks immutable review/route/intent identity, ALLOW, observed
NORMAL mode, candidate eligibility, Macro allocation and account reconciliation.
Quote observation, underlying book and reference each have a two-second maximum
age. Account and input-receipt freshness are bounded at five seconds.

Sizing uses stop distance, fees and adverse slippage; quantity is rounded down
to the exact 1e-8 grid with conservative decimal/float conversion. It respects
0.25% per-trade and 1% aggregate risk ceilings, explicit dollar/capital/daily
caps, venue size/depth, available balance and Macro capital. Existing exposure
and unrepresented committed reservations are charged separately, without
double counting. Realized and unrealized losses are each floored independently:
profits cannot cancel either loss bucket. No actual owner dollar limit was
chosen or armed by this implementation.

## Exact request publication and replay

Execution's opt-in `ProductionLiveRiskPublisher` calls that concrete evaluator
itself. It accepts raw account/input proofs, not a caller's approval boolean.
An approved Core LIVE/PROD decision is bound to the deterministic original
ENTRY effect, exact EVEDEX integer geometry and signing-effect digest. The
request/risk lease cannot outlive the two-second market-data bounds or the
underlying intent/account deadlines. It stages a Risk row followed by the
passive lifecycle binding; no signer or dispatcher is invoked.

Fresh explicit state-v3 provisioning permits the isolated Risk writer to read
its own immutable Risk rows for exact create-only replay under the existing
short account-scoped transaction lock. A changed payload/hash/request identity
is refused; replay never changes the original validity lease. There are no
UPDATE/DELETE privileges or migrations of retained databases. Default state-v2
keeps its old INSERT-only contract. A retained v3 database with older grants is
not silently upgraded: new inspection requires the exact fresh role contract.

The native fixture confirms actual PostgreSQL publication/resolution and the
same Risk-to-request comparison used by the existing managed runtime. It also
confirms that the pinned EVEDEX verifier refusal appends no Risk or binding
records. These are synthetic engineering tests, not an authenticated account
or a live order lifecycle.

## Real-source boundary

`PinnedEvedexLiveAccountVerifier` invokes the shared fixed history-source guard
and refuses current pinned SDK captures before returning verified equity,
exposure or accounting facts. There is no fallback that fills missing fields
with zero, converts REST observations into an atomic account snapshot, copies
entry approval to exits or releases reservations without accepted terminal
accounting.

An accepted venue source/replay/funding/lineage contract and a qualified upstream
receipt producer are still required before real deployment. The public inquiry
does not substitute for either. Existing service/factory startup still refuses
LIVE; this optional engineering composition is not a continuously deployed
PROD trader, a real-money qualification or a manual owner arm.

## Protective and closing effects

`ProductionLiveExitRiskPublisher` separately loads the actual PREPARED effect
and original approved decision from durable trade/effect journals, verifies
both chains and exact LIVE/PROD/account/parent/role/geometry, and requires a
configured independent source verifier. SL, TP, timeout and emergency close
receive new per-effect Risk identities, never the old ENTRY approval.

It computes loss and exit fees from qualified entry/reference/executable prices
and explicit adverse-execution bounds. Protective whole-position wire quantity
remains zero, but its economic envelope covers the full originally approved
entry quantity and the more conservative entry-cost basis. Honest later partial
fills cannot enlarge exposure beyond that quantity; overfilled journals or
foreign parents are refused. Direct closes use the exact prepared quantity and
cannot exceed fresh actual remaining exposure. The actual exposure record is
not inflated to the conservative economic envelope.

The publisher appends exposure, request-bound Risk and passive binding through
separate existing roles. Any partial/ambiguous write remains unresolved; no
blind retry, signature or dispatch is initiated. Existing entry KILL/HALT/
DISARM behaviour does not strand independently authorized risk-reducing exits.
Owner nonce/arm lineage, fresh exit Risk/exposure, signature and one-shot wire
checks remain mandatory. No separate global wire-cut qualification is claimed.

Qualified price/slippage/fee bounds are explicit assumptions, not a guarantee
against future gaps, liquidity loss or new charges. Current EVEDEX exit-source
verification still refuses; synthetic fixtures cannot establish its authority.

## Verification checkpoint

Risk source `251c45cea63edb6b08f36e3cd94102c2f45957d2` is GPG-signed with the
manifest's trusted fingerprint. Its 315 local tests, Ruff, Bandit, mypy and
wheel/sdist build passed. GitHub
[Windows/Linux CI](https://github.com/Kairos-cryptoAI/kairos-risk-manager/actions/runs/40008938729)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-risk-manager/actions/runs/40008938792)
passed on that exact commit.

The initial evaluator commit `549ffe8` and entry-composition commit `e921bb8`
also passed their affected CI. Final review then corrected an overly strict
synthetic `:PROD` suffix assumption: actual pinned-style `BTCUSD` instruments
are now used in entry/exit/native fixtures. Profile, exact context, closed
mapping and custody allowlist establish PROD scope, not an invented suffix.

Local final Execution regression: 970 passed, one Linux-only launcher test
skipped on Windows, 52 integration tests deselected, and eight subtests passed.
Sixteen focused exit tests and 38 Node sidecar checks passed. Independent
review caught and resolved the partial-fill protective economic-envelope
mismatch; it is code-review evidence, not venue-source qualification.

Final native entry publication/resolution used fresh database
`kairos_production_evidence_124393dd9847`; one test passed with the final signed
Risk package and unsuffixed venue instruments. The separate fresh-accounting
replay/concurrency fixture passed in `kairos_production_evidence_13f2f5a3cdb7`.
Exit-specific tests here exercise synthetic journal/source fixtures; no claim
is made that a real venue exit or a natural native trading lifecycle completed.

Final Execution source `fcdf2d57128627f2b3c1230616f7029ca6b67755` is also
trusted-GPG-signed. Its
[six-job CI](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/40009277759)
passed Windows/Linux Python 3.11, Linux Python 3.14, all optional adapters,
pinned Node SDK parity and native TimescaleDB integration; its
[CodeQL](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/40009277708)
also passed. Those engineering gates do not contact a real exchange or prove
account-source completeness.

Only the newly owned container `kairos-live-risk-test-20261023` was stopped,
after checking its exact ID and ownership/scope labels. All fixture databases,
including failed probes, remain retained; nothing was deleted. The pre-existing
successor serve/PG/Redis and shadow database containers were still running in
the final container observation. That observation does not establish trading
readiness or a new stability qualification.

Execution's new mandatory one-way Risk dependency is pinned to that signed
revision, installed non-editably for native verification. Its installed module
matches the source after Git line-ending normalization; the VCS distribution
metadata names that exact commit. No sibling `PYTHONPATH` substitution or
CURRENT campaign-environment replacement was used for final qualification.

Local artifacts are retained under
`D:/Kairos/runtime/prod-live-risk-20261023`. Failed probes and partial fixture
databases are retained rather than rewritten into passing evidence.

Deploy source `fe3bff8f5f584e075945e48f703cf0196059e132` is trusted-GPG-signed
and aligns all active compose/full-path/current-release/Text-Macro projections
with the same Risk and Execution revisions. Three uv locks were regenerated
with uv 0.12.3; five local deployment/source validators and 62 validator unit
tests passed. No compose service was started and no historical/frozen lock was
rewritten. The current-chain dependency lock is aligned without installing or
resuming its paused real-news campaign. Existing moderate Dependabot notices
on retained meta/deploy source sets are not represented as fixed.

On that Deploy revision the
[general CI and image builds](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40009610805),
[current-release REJECT_ALL gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40009610839),
[full-path isolated SIM gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40009610791)
and [Text/Macro/Router/Review/Risk composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/40009610779)
all passed. Remote image builds did not start local PAPER or LIVE services.

Meta's first source checkpoint `d2eee06` passed static validation, CodeQL and
[installed current-chain offline Windows/Linux verification](https://github.com/Kairos-cryptoAI/kairos/actions/runs/40009748476)
on these exact dependencies.
Its old native-campaign Python 3.14 fixture exposed a five-minute clock-edge
race: late test cases reused a sealed tape after the original strategy entry
expiry. The failed [run](https://github.com/Kairos-cryptoAI/kairos/actions/runs/40009748386)
is retained. The correction admits the synthetic fixture only with sufficient
original lifetime before creating its tapes, waiting for the next actual DB
clock boundary otherwise. It does not change strategy/evaluator source, TTL,
tape timestamps, budget assertions, real news or any frozen campaign.
The signed correction `9bb0a88de53a286693b44ef5592d2fa6838dc694` passed the
[native acceptance matrix](https://github.com/Kairos-cryptoAI/kairos/actions/runs/40010709195)
on Python 3.11 and 3.14, including explicit boundary-helper assertions and
exactly one non-skipped PostgreSQL acceptance per job. Meta
[manifest/docs validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/40010709091)
passed as well. `Test-CurrentRelease.ps1` independently verified all 14 clean
`main` checkouts, local `origin/main` matches, trusted HEAD signatures and active
source projections. This last report update changes no executable source,
dependency, frozen identity, readiness flag or trading permission.
The correction's [CodeQL](https://github.com/Kairos-cryptoAI/kairos/actions/runs/40010708560)
also passed; the earlier failing native run is not hidden or counted as PASS.

| Final artifact | SHA-256 |
| --- | --- |
| `risk-unit-final.xml` | `acb267f99570638b776df1b8ac2dfac67ab68c602c2c6a4d28060aea9e3cc2cb` |
| `execution-unit-final.xml` | `1013bd537ecedd726b7a4083fc98ad85edd8d3e1f9ba7f8e92ef3fa681e933a5` |
| `exit-unit.xml` | `33abfc0ce999b08a51ffda61646000bdd4c97670c416b9b867861afee033635c` |
| `native-live-risk-final.xml` | `dcae62603ad30e5a72c4d8257a474642f5f730f424c04fa4a946a45a437763b8` |
| `native-risk-replay-final.xml` | `271b59fa0488db3e6a854e4a58b45d39c89c0a54ac7683defcded4c9505fb34a7` |
| `sidecar.xml` | `06b238eee172089f6c86a8a80f604cdb10a59886d8e0f6e46e99139bd6817c1b` |
| `risk-dist-final/kairos_risk_manager-0.2.0-py3-none-any.whl` | `744763232da24b0bb1c4b193448226ab8b3485b0ca037dee18319c5548da3f42` |
| `execution-dist-final/kairos_execution_engine-0.1.0-py3-none-any.whl` | `ab407069feed6931fdfc02fc8db1c4e378447dbb9a8e6f9dbbfcac5a80e087a0` |
