# Kairos — Project Status

_Organization: [Kairos-cryptoAI](https://github.com/Kairos-cryptoAI) · updated 2026-08-13_

## Summary

The modernization pass has moved the eleven Python repositories to locked `uv` environments,
Python 3.11 development baselines, Linux 3.11/3.14 CI and Windows CI. Their `main` branch
matrices are green. Runtime services now have materially stronger ACK-after-success, TaskGroup
shutdown, replay, schema, account-state and degradation behavior.

Kairos remains **pre-production**. Green unit/CI matrices validate deterministic behavior and
packaging; they do not yet establish durable delivery or external live-exchange correctness.

## Repository state

| repository | implemented state | remaining boundary |
| --- | --- | --- |
| `kairos-core` | versioned contracts, topics, Redis bus, config/logging | end-to-end persistence is owned by consumers |
| `kairos-llm` | GPT-5.6 Responses parsing, DeepSeek strict JSON, health/cost hooks | live provider qualification and operational quotas |
| `kairos-quant-scouts` | closed 1m indicators, OI refresh, liquidation aggregation, staleness/reconnect | Binance soak and deployed venue/data-source decision |
| `kairos-text-scouts` | real feeds, local filter, DeepSeek sentiment/fallback | external feed/provider reliability and licensing/rate limits |
| `kairos-router` | FSM/hysteresis, SystemMode policy, ACK-after-success, graceful close | durable replay state |
| `kairos-aggregator` | strict tactical schema, mode handling, replay-safe publish | durable replay/context state and provider live tests |
| `kairos-macro-strategist` | real account/market context, shock detector, modes, strict schema | durable histories and external macro/on-chain inputs |
| `kairos-risk-manager` | reconciled account requirement, allocation enforcement, sizing/breakers | durable risk/PnL state and live integrated validation |
| `kairos-execution-engine` | EVEDEX/CCXT adapters, reconciliation, account snapshots, protective orders | live EVEDEX/canary qualification and durable order outbox |
| `kairos-persistence` | Timescale migrations, typed audit and transactional inbox/outbox repositories | service-runtime integration and backup/restore exercise |
| `kairos-backtest` | deterministic historical replay and fill model | parity/coverage against real venue behavior |
| `kairos-deploy` | full-SHA service contexts, Compose/monitoring configuration, static validation | external deployment, secrets, metrics and recovery qualification |
| `kairos` | cross-repo manifest, Windows-first runner and current architecture docs | keep manifest/ADRs synchronized with `main` and pinned dependency revisions |

Test counts are intentionally not frozen in this document. The meaningful gate is that each
repository's declared checks and supported Python/Windows matrix pass for the reviewed commit.

## Implemented cross-service flows

- Execution publishes reconciled `AccountSnapshot` messages to both Risk and Macro at startup,
  periodically, and after relevant execution activity.
- Risk requires recent trusted account state, applies strategic allocation constraints and
  revokes trust on explicit reconciliation failure.
- Text, Aggregator and Macro publish `LLMHealthEvent`; Risk owns the circuit breaker and
  broadcasts `SystemControl`.
- Router, Aggregator, Macro and Execution subscribe to system control. Local degradation blocks
  new exposure without blocking protective close/reduce-only execution.
- Quant computes indicators only from closed one-minute bars, refreshes open interest, ingests
  liquidations and exposes explicit staleness/reconnect behavior.
- Redis-consuming services acknowledge work after required processing and publishing succeeds;
  deterministic IDs/in-memory caches reduce replay effects.

## Modernization and verification

- `uv` 0.12.3 is required and `uv.lock` is committed in all eleven Python repositories.
- `.python-version` declares 3.11; Linux CI verifies 3.11 and 3.14, with a Windows job.
- Internal Git dependencies are pinned to full reviewed SHAs rather than floating branches.
- Dependabot configuration covers Actions and Python dependency updates.
- `main` is authoritative; multi-repository changes land in dependency order after dependent
  SHAs settle and their consumer lockfiles are verified.
- [`scripts/Test-Kairos.ps1`](../scripts/Test-Kairos.ps1) runs the equivalent lock, lint,
  format, mypy, Bandit, network-free pytest and build gates locally without Docker.

## Remaining limitations

1. **Durable delivery is not integrated end-to-end.** Transactional inbox/outbox primitives
   exist, but services still rely on Redis at-least-once delivery plus process-local replay
   caches. A crash between an external side effect and ACK/publish can still require manual
   reconciliation.
2. **State is not fully restart-safe.** Intraday PnL/account history, macro context/history and
   some deduplication windows reset on restart.
3. **External live EVEDEX is unqualified.** EIP-712, order reconciliation, protective-order
   updates, rate limits and failure recovery need controlled canary testing. Application-managed
   trailing is not a verified native server-side trailing order.
4. **Market-data/execution venue split needs an explicit production decision.** Quant currently
   consumes Binance data while execution targets EVEDEX; symbol, basis, liquidity and latency
   assumptions need live validation.
5. **External LLM/feed tests remain.** Unit fakes validate schemas and errors, not current
   provider availability, quotas, latency or upstream content quality.
6. **Persistence operations remain.** Timescale integration, retention, backup/restore and a
   queryable audit/recovery workflow must be exercised across service processes.
7. **Deployment operations remain.** Secret-store integration, service metrics, alerts,
   reconnect/soak tests, disaster recovery and staged rollback require an external environment.
8. **Backtests are not venue qualification.** The deterministic fill model needs calibration
   against real EVEDEX behavior before results can inform live risk limits.

## Readiness rule

Do not enable live trading merely because GitHub or the local runner is green. Live eligibility
requires the durability, live exchange/provider, canary, observability and recovery gaps above
to be closed and independently reviewed.
