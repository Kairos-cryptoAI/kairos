# Kairos — Concept Specification

> Global architecture of an AI trader: a futures-trading management system with LLM
> analytics. Concept plan, 2026-06-05. (Condensed from the original design document.)

## Base principle
The whole system rests on one constraint: **the LLM never trades directly and never works
with a raw stream of numbers.** The model is the analytical brain that controls the
parameters of hard-coded mathematical strategies; it does not replace the trading engine.

## Layers
1. **Scouts** — data collection, filtering, sentiment.
2. **The Router** — finite-state machine + hysteresis.
3. **The Aggregator** — tactical decision (medium/high reasoning).
4. **Macro-Strategist** — strategic capital allocation (xhigh).
5. **Risk Manager & Circuit Breaker** — validation, limits, emergency modes.
6. **Execution Engine** — atomic order execution.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full per-layer breakdown and
[`docs/BUDGET.md`](docs/BUDGET.md) for the cost model.

## Target venue
Production: [EVEDEX](https://exchange.evedex.com/) (EIP-712 signed orders, Centrifugo WS).
Testing: Binance USD-M futures and other venues via CCXT.
