# Kairos — Project Status

_Organization: [Kairos-cryptoAI](https://github.com/Kairos-cryptoAI) · updated 2026-08-18_

## Summary

The modernization pass has moved the eleven Python repositories to locked `uv` environments,
Python 3.11 development baselines, Linux 3.11/3.14 CI and Windows CI. Their `main` branch
matrices are green. Runtime services now have materially stronger ACK-after-success, TaskGroup
shutdown, replay, schema, account-state and degradation behavior.

Kairos remains **pre-production**. Durable service delivery, the execution-effect journal and
the local operations/recovery stack are now implemented and exercised, but green unit/CI and
local Docker results do not establish external live-exchange/provider correctness. The offline
strategy promotion gate currently returns `needs_revision` and `real_api_allowed=false`.

## Repository state

| repository | implemented state | remaining boundary |
| --- | --- | --- |
| `kairos-core` | versioned contracts, topics, Redis bus, config/logging | end-to-end persistence is owned by consumers |
| `kairos-llm` | workload routing across DeepSeek Flash 0731 and GPT-5.6 Luna/Terra/Sol, strict schemas, health/cost hooks | live provider qualification, shadow evals and operational quotas |
| `kairos-quant-scouts` | closed 1m indicators, OI refresh, liquidation aggregation, staleness/reconnect | Binance soak and deployed venue/data-source decision |
| `kairos-text-scouts` | GDELT/RSS plus official X API, durable X cursors/spend reservations, local filter, DeepSeek sentiment/fallback | purchase X credits, then qualify real latency/freshness/quota and DeepSeek quality/cost |
| `kairos-router` | FSM/hysteresis, SystemMode policy, durable inbox/outbox, graceful close | durable FSM history beyond message replay |
| `kairos-aggregator` | strict tactical schema, mode handling, durable publish/ACK | durable long-horizon context and provider live tests |
| `kairos-macro-strategist` | real account/market context, shock detector, modes, durable publish/ACK | durable analytical histories and external macro/on-chain inputs |
| `kairos-risk-manager` | reconciled account requirement, allocation enforcement, durable decisions/sizing/breakers | durable long-horizon PnL state and live integrated validation |
| `kairos-execution-engine` | EVEDEX/CCXT adapters, reconciliation, account snapshots, protective orders, durable mutation journal and recovery | authenticated live EVEDEX/canary qualification |
| `kairos-persistence` | Timescale migrations, runtime inbox/outbox, execution-effect journal, audit repositories and metrics exporter | external retention sizing and off-host backup policy |
| `kairos-backtest` | deterministic causal replay, audited Binance archive ingestion and fail-closed promotion evidence | strategy revision, clean complete data, historical funding and parity against real venue behavior |
| `kairos-deploy` | full-SHA contexts, file-scoped secrets, metrics/alerts, reconnect soak and recovery tooling | managed secret backend, long soak and external recovery qualification |
| `kairos` | cross-repo manifest, Windows-first runner and current architecture docs | keep manifest/ADRs synchronized with `main` and pinned dependency revisions |

Test counts are intentionally not frozen in this document. The meaningful gate is that each
repository's declared checks and supported Python/Windows matrix pass for the reviewed commit.

## Implemented cross-service flows

- Execution publishes reconciled `AccountSnapshot` messages to both Risk and Macro at startup,
  periodically, and after relevant execution activity.
- Risk requires recent trusted account state, applies strategic allocation constraints and
  revokes trust on explicit reconciliation failure.
- Text, Aggregator and Macro publish `LLMHealthEvent`; Risk owns per-model/provider circuit breakers and
  broadcasts `SystemControl`.
- Router, Aggregator, Macro and Execution subscribe to system control. Local degradation blocks
  new exposure without blocking protective close/reduce-only execution.
- Quant computes indicators only from closed one-minute bars, refreshes open interest, ingests
  liquidations and exposes explicit staleness/reconnect behavior.
- Every Redis-consuming service records inbox ownership and atomically commits required domain
  state plus outbox messages before acknowledging the stream delivery. The outbox dispatcher
  retries independently and dead-letters bounded failures for operator review.
- Execution records each external venue mutation as `PREPARED` before submission. Startup
  recovery reconciles unresolved effects under a database advisory lock; EVEDEX protective
  orders are reconciled by authoritative parent linkage before new risk is accepted.
- The deployment exporter exposes aggregate inbox/outbox and execution-journal health. The
  loopback Prometheus/Grafana stack has passed a fresh-volume startup, explicit Redis restart,
  and isolated backup/restore schema drill without enabling live orders.

## Modernization and verification

- `uv` 0.12.3 is required and `uv.lock` is committed in all eleven Python repositories.
- `.python-version` declares 3.11; Linux CI verifies 3.11 and 3.14, with a Windows job.
- Internal Git dependencies are pinned to full reviewed SHAs rather than floating branches.
- Dependabot configuration covers Actions and Python dependency updates.
- `main` is authoritative; multi-repository changes land in dependency order after dependent
  SHAs settle and their consumer lockfiles are verified.
- [`scripts/Test-Kairos.ps1`](../scripts/Test-Kairos.ps1) runs the equivalent lock, lint,
  format, mypy, Bandit, network-free pytest and build gates locally without Docker.

## Offline strategy validation and promotion evidence

The campaign freezes one candidate before promotion evaluation:
`confirmation_bars=12`, `minimum_hold_bars=48`, and `minimum_confidence=0.67`. Official Binance
Futures monthly 1m archives for the 12-month research interval and untouched July holdout are
audited against their SHA-256 sidecars and ZIP CRCs. The broader upstream inventory is also
audited fail closed; a source anomaly, gaps, or incomplete coverage remains a promotion blocker
even when the replayed window itself is available.

Signals are formed only from closed candles, scheduled at the first eligible subsequent open,
and capped by the previous closed candle's volume. This avoids same-bar price or liquidity
look-ahead. Actual historical funding was unavailable and is reported as unavailable; an
assumed stress rate does not satisfy the historical-funding gate.

| evidence | baseline | stress |
| --- | ---: | ---: |
| 12-month research replay | -4.231727849843687% / 803 trades | -9.763199273155571% / 804 trades |
| untouched July promotion OOS | -1.075965871769744% / 69 trades | -1.5781050811020259% / 69 trades |

Rolling folds are post-selection diagnostics and must not be described as OOS. Only the
untouched July interval is promotion OOS: its buy-and-hold benchmark was
+6.828606504564661%, and zero of five symbols had positive strategy returns. The resulting gate
is `needs_revision` with `real_api_allowed=false` because of insufficient OOS trades,
non-positive return and expectancy, benchmark underperformance, unavailable historical funding,
non-positive sensitivity performance, and upstream anomaly/gaps/incomplete coverage. This is
offline research evidence, not live qualification. The governing boundary is
[ADR 9](adr/0009-offline-strategy-promotion-gate.md).

### Subsequent development-only screens

The isolated `orderflow_volatility_expansion_v1` screen evaluated `IMPULSE`, `PERSISTENCE` and
`FLIP_RELEASE` on reused July-December 2022 `RESEARCH/FIT` data. It was designed to test whether
causal five-minute taker-flow expansion could add trade frequency without weakening the
fail-closed economics gate. `PERSISTENCE` did supply 387 baseline and 301 stress trades, but its
net returns were -2.9005% and -3.2540%. All six trial/scenario cells had negative expectancy and
profit factor below 1.0, so the fixed decision was `REJECT_ALL` and every promotion, shadow and
live permission remained false.

This is useful negative evidence: frequency itself is no longer the primary constraint, while
the standalone post-expansion continuation signal has no demonstrated net edge. The result is
strictly development diagnostics, does not alter the frozen promotion decision above, and did
not invoke an LLM, external API or real order. Full methodology, checksums and artifact hashes
are in the
[order-flow report](https://github.com/Kairos-cryptoAI/kairos-backtest/blob/main/reports/orderflow-screen/REPORT.md).

The third frozen regime/retest family evaluated structural reclaim, flow reacceleration and
absorption reclaim on reused December 2023-June 2024 `RESEARCH/FIT` data. Its complete audited
five-symbol slice contained 1,533,600/1,533,600 expected one-minute rows. The stacked regime,
expansion, retest and admission funnel reduced 41,741 breakout candidates to 12 structural
intents, two flow-reacceleration intents and no absorption intents. Only one baseline trade
executed; stress admitted no trades. The XRPUSDT trade lost $15.49 net (-0.015492%, -1.63R),
and every required frequency and positive-economics gate failed. The fixed decision is
`REJECT_ALL`; promotion, shadow operation, live trading and real API use remain disabled.

This remains development diagnostics on reused research data, not OOS or promotion evidence.
Trials 7-9 are consumed and must not be rerun or retuned against this interval. A fourth
threshold variant must not be created: the next candidate must change the signal structure
while preserving cost-aware admission, and its cumulative lineage must be frozen before the
remaining selection window is inspected. Full methodology and integrity evidence are in the
[regime-retest report](https://github.com/Kairos-cryptoAI/kairos-backtest/blob/main/reports/regime-retest-screen/REPORT.md).

## Remaining limitations

1. **State is not fully restart-safe.** Intraday PnL/account history, macro context/history and
   some deduplication windows reset on restart.
2. **External live EVEDEX is unqualified.** The journal/recovery path and a read-only qualifier
   exist, but real JWT/EIP-712 auth, reconciliation, protective-order states, rate limits and
   ambiguous network outcomes still need controlled authenticated canary testing. No real order
   was placed. Application-managed trailing is not a verified native server-side facility.
3. **Market-data/execution venue split needs an explicit production decision.** Quant currently
   consumes Binance data while execution targets EVEDEX; symbol, basis, liquidity and latency
   assumptions need longer live observation. A short read-only comparison is not sufficient.
4. **External LLM/feed qualification has started but is not a soak.** One bounded X request
   authenticated, read one User and ten Posts for `$0.060000`, and observed rate headers; those
   Posts were older than the 30-minute freshness gate. One structured call passed on each model
   route: DeepSeek Flash, GPT-5.6 Luna, Terra and Sol. The modeled LLM cost was `$0.00237938`.
   Provider `/models` endpoints emitted no quota headers, and one sample cannot establish monthly
   availability, latency tails, quotas or decision quality. Every paid LLM caller now shares a
   durable provider-wide spend ledger with pre-call reservation, and X uses its own durable
   monthly ledger. Continuous paid testing still needs an approved cadence, quality protocol and
   stop conditions within those enforced limits.
5. **Operations need external qualification.** Local Docker secrets prevent values from
   appearing in container environment metadata, monitoring and alerts are live, and reconnect
   plus backup/restore drills pass. Production still needs a managed KMS/Vault backend,
   encrypted off-host backup scheduling, a long soak, host hardening and a staged recovery drill.
6. **Backtests are not venue qualification.** The frozen candidate loses money in the untouched
   July holdout, trails its benchmark, has too few OOS trades, and lacks historical funding
   evidence. The gate therefore denies real APIs. The deterministic fill model also needs
   calibration against real EVEDEX behavior before results can inform live risk limits.
7. **Model migration still needs live shadow evaluation.** The four API routes now pass one exact
   structured-output probe, but that does not prove that Luna/Terra/Flash preserve decision
   quality, latency tails and token profiles on production distributions.

## Readiness rule

Do not enable live trading merely because GitHub or the local runner is green. Live eligibility
requires a passing offline strategy promotion gate plus the live exchange/provider, long-soak,
managed-secrets and canary gaps above to be closed and independently reviewed.
