# Kairos — Project Status

_Org: [Kairos-cryptoAI](https://github.com/Kairos-cryptoAI) · updated 2026-07-11_

## Summary
A **DeepSeek-first + GPT escalation** futures-trading system: six independently deployable
layers on a typed message bus, with deterministic risk guards and an automatic LLM-health
feedback loop. All repositories live under the `Kairos-cryptoAI` organization; every package's
test suite is green (**125 tests**). Core has schema versioning and CI quality gates are
active; production reconciliation/persistence are in progress.

## Repositories & tests
| repo | role | tests | CI |
| --- | --- | --- | --- |
| kairos-core | contracts, bus, enums, topics, config, logging | 18 | ✅ |
| kairos-llm | LLM gateway: effort→model routing, pricing, health hook | 16 | ✅ |
| kairos-router | Layer 2 — FSM + hysteresis (`ROUTE_PRO`/`ROUTE_GPT`) | 6 | ✅ |
| kairos-quant-scouts | Layer 1A — market data + indicators → `MarketSnapshot` | 13 | ✅ |
| kairos-text-scouts | Layer 1B — news + DeepSeek-Flash + local fallback | 9 | ✅ |
| kairos-aggregator | Layer 3 — tactical (DeepSeek-Pro / GPT-5.5) | 5 | ✅ |
| kairos-macro-strategist | Layer 4 — strategic (GPT-5.5 `xhigh`) | 5 | ✅ |
| kairos-risk-manager | Layer 5 — risk filters + per-model circuit breakers | 28 | ✅ |
| kairos-execution-engine | Layer 6 — EVEDEX/CCXT + trailing stops | 16 | ✅ |
| kairos-deploy | docker-compose, TimescaleDB, monitoring | — | — |
| kairos | docs (SPEC, ARCHITECTURE, BUDGET, ADRs) | — | — |
| **total** | | **116** unit + **9** integration = **125** | |

## Implementation completeness
| component | status | notes |
| --- | --- | --- |
| **Contracts & bus** | ✅ production | schema v1.0, correlation/causation IDs, XAUTOCLAIM |
| **LLM gateway** | ✅ production | routing, pricing, health feedback |
| **Router (L2)** | ✅ production | FSM, hysteresis, budget-tested |
| **Quant Scouts (L1A)** | ⚠️ testnet-ready | Binance WS; needs reconnect soak |
| **Text Scouts (L1B)** | ⚠️ testnet-ready | DeepSeek-Flash, RSS/Reddit/X; hardened XML |
| **Aggregator (L3)** | ✅ production | DeepSeek-Pro/GPT escalation, reference_price flow |
| **Macro Strategist (L4)** | 🚧 stubbed | Core logic ready; portfolio/macro/on-chain placeholders |
| **Risk Manager (L5)** | ⚠️ testnet-ready | Validates/sizes; **account state still mock** |
| **Execution (L6)** | 🚧 partial | EVEDEX/CCXT adapters stubbed; **no reconciliation yet** |
| **Persistence** | 🚧 planned | TimescaleDB ready; writers/migrations not started |
| **Observability** | 🚧 partial | Prometheus/Grafana configured; services not instrumented |
| **E2E/Backtest** | ❌ not started | |

## Architecture compliance (design document)
| requirement | status |
| --- | --- |
| LLM never trades directly; structured data only | ✅ |
| Text Scouts → DeepSeek-V4-Flash, non-thinking | ✅ |
| Aggregator-Normal → DeepSeek-V4-Pro | ✅ |
| Aggregator-Conflict → GPT-5.5 `high` | ✅ |
| Macro-Strategist → GPT-5.5 `xhigh` | ✅ |
| Router `ROUTE_PRO`/`ROUTE_GPT`, hysteresis 4/10 | ✅ |
| DeepSeek pricing + budget $138.62 / $257.52 | ✅ (test-verified) |
| Text Scouts local-filter fallback | ✅ |
| Granular per-model Circuit Breaker | ✅ |
| LLM health feedback loop (auto-feeds breakers) | ✅ (ADR-0006) |
| Execution: EVEDEX EIP-712, trailing stops, `reason_code` | 🚧 |

## Degradation modes (automatic)
| condition | `SystemMode` |
| --- | --- |
| all healthy | `NORMAL` |
| DeepSeek-V4-Flash down | `TEXT_LOCAL_FILTER` |
| GPT-5.5 down | `CONFLICT_SAFE` |
| ≥ 2 models down | `LOCAL_QUANT_MODE` |

## Known limitations (in progress)
- **Account state:** Risk Manager uses placeholder equity/positions; real reconciliation needed.
- **EVEDEX adapter:** Place/cancel/stop partially stubbed; testnet verification pending.
- **Idempotency:** No persistent order state; Redis redelivery can duplicate submissions.
- **Macro inputs:** Portfolio/on-chain/macro feeds are placeholders.
- **Strategic application:** `StrategicAllocation` published but not enforced by Risk Manager.
- **Persistence:** TimescaleDB exists but no audit trail writers yet.
- **Observability:** Prometheus/Grafana configured; service metrics not instrumented.

## Budget
Infrastructure $118.90 (Hetzner CX43 + Oxylabs) + API $138.62 = **$257.52 / mo** (≈ $258).

## Running it
Set `KAIROS_DEEPSEEK_API_KEY` and `KAIROS_OPENAI_API_KEY`, then deploy via `kairos-deploy`
(`KAIROS_DRY_RUN=true` by default). Live trading requires completing reconciliation, account
state, EVEDEX adapter and idempotency.
