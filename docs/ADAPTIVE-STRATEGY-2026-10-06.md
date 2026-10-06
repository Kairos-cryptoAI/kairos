# Selected adaptive strategy: engineering receipt

Date: 2026-10-06 Europe/Moscow. Classification: ENGINEERING_ONLY.
Candidate: `adaptive_pullback_range_v1`, revision `1`.
Status: RESEARCH_ONLY; NOT_ECONOMICALLY_QUALIFIED; NOT_CAMPAIGN_FROZEN.

## One concrete variant

The selected variant combines trend pullback/reclaim entries, bounded range
edge reclaims and a defensive downward-shock overlay. Its fixed reference
universe is BTC/ETH/SOL/BNB/XRP. It evaluates complete 5m decisions from a finite
54-hour closed 1m history with 15m and 1h context. Ambiguous, unavailable, stale
or structurally unsuitable slots do not create a candidate. Zero trades is
valid; there is no daily quota, asset-specific tuning or parameter competition.

The exact executable rules, exits, clocks, costs and interfaces are in
[the Strategy specification](https://github.com/Kairos-cryptoAI/kairos-strategy-engine/blob/cde8e9c00af0cc19848e800ee76472a800a5fd5d/docs/ADAPTIVE-PULLBACK-RANGE-V1.md).
No claim is made that this is the globally best strategy or will produce a
particular monthly return. It reacts to observed shocks, not predicts them;
an unretested crash may yield zero entries.

Research decisions were kept bounded: Luna handled repository mapping and
mechanical pins; Sol reviewed consequential strategy causality and economics.
That review corrected a shock-cooldown boundary and aligned the candidate's
planning reward/loss with the existing conservative research arithmetic.
These were engineering corrections, not performance-driven retuning.

## Published identity

| source | signed main revision |
| --- | --- |
| Strategy 0.2.12 | `cde8e9c00af0cc19848e800ee76472a800a5fd5d` |
| LLM dependency projection | `f1e25893f9078a467eba584e233ac9129e9ff9b1` |
| Aggregator dependency projection | `092161aaaf382802fc139be08c09c65e593b0d97` |
| Macro dependency projection | `bf93215231af37d443d3f71413b917816a46e9c2` |
| Text dependency projection | `3f6de97a1ab3ef83b9074770e6e7c0b0a133e5a1` |
| Deploy engineering gates r7 | `2c08f62f0f1f3a1c7862b0728b6f34f1c088ea6a` |

Strategy and detector code hash:
`836391ab708d4dc9bd4957c68f00724683569b7d5584debb1c368016d57ff0d5`.
Strategy and detector config hash:
`51781e00bee3664f260ff826c821234073b7a40deb1b7239e39f517be885901b`.

These hashes identify the selected implementation; they are not a scientific
campaign freeze or live approval. [The current manifest](../config/current-release.json)
records the complete engineering source set. Trial 15, its evaluator, V4/V5
and the backtest repository were not changed. All eleven existing legacy
strategy source/config fingerprints remain identical to their recorded values.

## Verified local evidence

- Strategy: 480 source tests passed, including 42 new cases. Locked lint,
  format, mypy, Bandit and wheel/sdist build passed. The 42 new cases also
  passed from a separate non-editable installed wheel; source/config identity
  matched the checkout. Legacy fingerprint regression passed in both forms.
- New cases cover long/short trend and range geometry, first crash retest,
  first structural-match consumption despite cost rejection, fresh range
  rearming, prefix/rolling equivalence and no future-bar leakage. They also
  cover exact side-specific costs, clock/source-envelope rejection, expiry,
  numerical failure, warmup/gaps, valid no-intent and PAPER/LIVE prohibition.
- LLM dependency projection: 272 tests passed, six skipped. Locked lint,
  format, mypy and Bandit passed. No provider/model behavior was changed.
- Dependent Aggregator, Macro and Text projections: 83, 92 (one skipped) and
  91 tests passed respectively; lint, format, mypy, Bandit and wheel/sdist
  builds passed. Only each `pyproject.toml`/`uv.lock` LLM source pin changed;
  third-party versions and behavior remained unchanged.
- Deploy static suite: 458 cases, 455 passed and three skipped. Windows
  recovery-script mock tests and five real Compose config-only renders passed:
  base, blocked LIVE overlay, PAPER topology, current refusal and full-path SIM.
  This did not perform primary recovery, start a consumer or build local Docker.
- Exact non-editable current-source fixture: 8/8 passed. The new case generates
  an actual adaptive candidate on a synthetic causal tape and traverses Router,
  explicit legacy engineering review, default rejecting Risk and Execution.
  Quantity, external effects and venue accesses remain zero. Docker context
  and exact test command are checked so this case cannot silently be omitted.
- Exact non-editable Text/Macro/Router/review/Risk contract composition: 28/28
  passed. Required stale inputs defer before provider dispatch. This local
  contract fixture is not native database/runtime or economic qualification.

Source Strategy [CI](https://github.com/Kairos-cryptoAI/kairos-strategy-engine/actions/runs/37410698446)
passed on Windows and Linux, with CodeQL also green on its exact revision.
The LLM projection [main CI](https://github.com/Kairos-cryptoAI/kairos-llm/actions/runs/37410779556),
CodeQL and dependency graph passed on its exact revision. A separate automated
Dependabot updater run failed; it is not claimed as green or as strategy evidence.

These are deterministic synthetic/contract/packaging checks, not profitable
historical trades, blind-day coverage, a model-quality benchmark or real venue
qualification. Old r5/r6 Docker/native receipts do not apply to the final r7 set.

The first r6 Deploy CI rejected stale LLM pins in Aggregator, Macro and Text.
That source-closure failure was corrected without changing the validator or
runtime semantics. New exact-SHA component CI passed for all three projections:
[Aggregator](https://github.com/Kairos-cryptoAI/kairos-aggregator/actions/runs/37412133385),
[Macro](https://github.com/Kairos-cryptoAI/kairos-macro-strategist/actions/runs/37412132792),
[Text](https://github.com/Kairos-cryptoAI/kairos-text-scouts/actions/runs/37412132643).

## Exact-source hosted integration

On the final signed Deploy revision `2c08f62f0f1f3a1c7862b0728b6f34f1c088ea6a`:

- [Current refusal gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37412379995)
  passed Windows/Linux isolation checks and the Docker proof, including the new
  real adaptive-generator fixture with zero venue accesses/external effects.
- [Installed native composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37412379898)
  passed on isolated PG16/Redis with exact non-editable source pins, controlled
  schema, real handlers and committed-ACK-loss replay. Provider output remains
  a zero-spend fixture; this is not primary recovery or real-source qualification.
- [Full-path SIM](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37412379926)
  passed the disposable database/controller replay and recovery proof. Its
  explicitly legacy review fixture is engineering-only, not adaptive economics.
- [Deploy main CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37412379978)
  passed Windows/Linux Python 3.11/3.14 validators, exact remote dependency
  closure, config security checks and all pinned service/PAPER image builds.
  CodeQL and the current fixture dependency graph also passed. A separate
  Dependabot updater for historical `tests/release_gate` failed; it remains
  outside this strategy change and is not reported as a passing workflow.

The above are engineering evidence only; no prior r5/r6 success is inherited.
The final manifest passed `Test-CurrentRelease.ps1` across all 14 tracked-clean
signed main repositories and their exact current-gate dependency projections.

## Integration and remaining gates

The generator and strict adapter are opt-in, DRY_RUN/observation only, with
mandatory actual clocks and an explicit source-set digest. They produce
immutable intent/evaluation evidence; the detector mapping is research-only.
They are not inserted into the legacy service registry or enrolled in the
durable adaptive campaign. Missing clocks/context, budget, account or venue
evidence cannot be replaced by a model's confidence. Independent LLM proposals
remain a separate research arm and cannot create orders or Risk approval.

Next required work is bounded point-in-time economic replay on development
bull/range/bear/crash data, then a matched three-arm economic evaluator with
causal fills, actual arm latency, fees, funding, spread/slippage and provider/feed
costs. The 20bps planning allowance is an assumption, not measured EVEDEX cost.
Durable publication, source-qualified news/macro context and account-bound
policy enrollment require their own accepted source-pinned implementation.

Only after eligibility may this ONE version and evaluator enter its own frozen
campaign: at least 365 genuinely future days, 500 naturally closed simulated
trades, approved drawdown/profit-factor criteria, the fixed crash/net-profit
criterion and exactly one sealed evaluation. Trial 15's days do not transfer.
No tuning against the blind result or artificial trades to fill a quota.

PAPER venue qualification, production security/custody/backups, explicit limits
and manual arming remain independent. No model API was paid or venue contacted
in this strategy task, and no primary database, budget or research ledger was
mutated. `TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`,
`ALPHA_READY=false`, `LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`.
