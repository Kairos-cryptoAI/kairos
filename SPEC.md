# Kairos — Concept Specification

Kairos is a layered futures-trading management system with LLM-assisted analysis and
deterministic execution controls. This specification describes the current implementation
direction; it is not a production-readiness claim.

## Base principle

**The LLM never trades directly and never works with a raw stream of numbers.** Models receive
typed, compressed and pre-validated context. Deterministic components retain authority over
routing, risk, account freshness, system degradation and exchange execution.

## Model strategy — workload-specific routing

- Text Scouts: the current `deepseek-v4-flash` API alias (DeepSeek-V4-Flash-0731), explicit
  non-thinking mode, with deterministic local fallback.
- Aggregator normal path: GPT-5.6 Luna with `medium` reasoning effort.
- Aggregator conflict path: GPT-5.6 Terra with `high` reasoning effort.
- Macro Strategist: GPT-5.6 Sol with `xhigh` reasoning effort.

OpenAI calls use the Responses API with SDK-native Pydantic structured parsing. DeepSeek uses
its OpenAI-compatible Chat Completions endpoint with explicit non-thinking mode and the same
schema validated locally. Routing is keyed by workload role as well as domain reasoning effort,
so adding another `medium` or `high` caller cannot silently inherit an unrelated model.

## Runtime layers

1. **Scouts** collect and compress market and text inputs.
2. **Router** applies deterministic FSM/hysteresis and system-mode routing policy.
3. **Aggregator** produces schema-validated tactical commands.
4. **Macro Strategist** combines market, account and shock context into strategic allocation.
5. **Risk Manager** validates account freshness, exposure and strategy limits and owns the
   system circuit breaker.
6. **Execution Engine** reconciles the venue, submits validated orders and publishes account
   snapshots back to Risk and Macro.

Every runtime consumer now commits inbox state, domain state and outbound messages before Redis
ACK. A durable execution-effect journal protects the external-mutation boundary and blocks new
risk until unresolved effects are reconciled. Historical replay is still not a substitute for
an external live-venue canary.

The target live venue is [EVEDEX](https://exchange.evedex.com/) with EIP-712-authenticated order
operations; CCXT/Binance paths support development and dry-run verification. Live external
exchange qualification remains outstanding.

See [architecture](docs/ARCHITECTURE.md), [status](docs/STATUS.md), and the [ADRs](docs/adr/).
