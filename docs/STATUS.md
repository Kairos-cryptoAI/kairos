# Kairos — Project Status

_Org: [Kairos-cryptoAI](https://github.com/Kairos-cryptoAI) · updated 2026-06-18_

## Summary
A **DeepSeek-first + GPT escalation** futures-trading system: six independently deployable
layers on a typed message bus, with deterministic risk guards and an automatic LLM-health
feedback loop. All repositories live under the `Kairos-cryptoAI` organization; every package's
test suite is green (**91 tests**).

## Repositories & tests
| repo | role | tests |
| --- | --- | --- |
| kairos-core | contracts, bus, enums, topics, config, logging | 10 |
| kairos-llm | LLM gateway: effort→model routing, pricing, health hook | 16 |
| kairos-router | Layer 2 — FSM + hysteresis (`ROUTE_PRO`/`ROUTE_GPT`) | 6 |
| kairos-quant-scouts | Layer 1A — market data + indicators → `MarketSnapshot` | 12 |
| kairos-text-scouts | Layer 1B — news + DeepSeek-Flash + local fallback | 6 |
| kairos-aggregator | Layer 3 — tactical (DeepSeek-Pro / GPT-5.5) | 4 |
| kairos-macro-strategist | Layer 4 — strategic (GPT-5.5 `xhigh`) | 5 |
| kairos-risk-manager | Layer 5 — risk filters + per-model circuit breakers | 20 |
| kairos-execution-engine | Layer 6 — EVEDEX/CCXT + trailing stops | 12 |
| kairos-deploy | docker-compose, TimescaleDB, monitoring | — |
| kairos | docs (SPEC, ARCHITECTURE, BUDGET, ADRs) | — |
| **total** | | **91** |

## Architecture compliance (updated design document)
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
| Execution: EVEDEX EIP-712, trailing stops, `reason_code` | ✅ |

## Degradation modes (automatic)
| condition | `SystemMode` |
| --- | --- |
| all healthy | `NORMAL` |
| DeepSeek-V4-Flash down | `TEXT_LOCAL_FILTER` |
| GPT-5.5 down | `CONFLICT_SAFE` |
| ≥ 2 models down | `LOCAL_QUANT_MODE` |

## Budget
Infrastructure $118.90 (Hetzner CX43 + Oxylabs) + API $138.62 = **$257.52 / mo** (≈ $258).

## Running it
Set `KAIROS_DEEPSEEK_API_KEY` and `KAIROS_OPENAI_API_KEY`, then deploy via `kairos-deploy`
(`KAIROS_DRY_RUN=true` by default).
