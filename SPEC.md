# Kairos — Concept Specification

> Global architecture of an AI trader: a futures-trading management system with LLM
> analytics. Concept plan, 2026-06-18. (Condensed from the updated design document.)

## Base principle
The whole system rests on one constraint: **the LLM never trades directly and never works
with a raw stream of numbers.** The model is the analytical brain that controls the
parameters of hard-coded mathematical strategies; it does not replace the trading engine.

## Model strategy — DeepSeek-first + GPT escalation
Cheap DeepSeek models carry the routine flow; GPT-5.5 is reserved for the highest
cost-of-error decisions:
- Text Scouts → DeepSeek-V4-Flash (non-thinking).
- Aggregator-Normal → DeepSeek-V4-Pro.
- Aggregator-Conflict → GPT-5.5 (`high`).
- Macro-Strategist → GPT-5.5 (`xhigh`).

## Layers
1. **Scouts** — data collection, filtering, sentiment (DeepSeek-V4-Flash).
2. **The Router** — finite-state machine + hysteresis (`ROUTE_PRO` / `ROUTE_GPT`).
3. **The Aggregator** — tactical decision (DeepSeek-V4-Pro / GPT-5.5 `high`).
4. **Macro-Strategist** — strategic capital allocation (GPT-5.5 `xhigh`).
5. **Risk Manager & Circuit Breaker** — validation, limits, per-model emergency modes.
6. **Execution Engine** — atomic order execution.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full per-layer breakdown and
[`docs/BUDGET.md`](docs/BUDGET.md) for the cost model.

## Target venue
Production: [EVEDEX](https://exchange.evedex.com/) (EIP-712 signed orders, Centrifugo WS).
Testing: Binance USD-M futures and other venues via CCXT.
