# 6. LLM health feedback loop

Date: 2026-06-18 · Revised: 2026-08-12 · Status: accepted · Extends ADR-0005.

## Context

Per-model circuit breakers can protect the trading path only when model callers report health
and the resulting mode reaches components that can prevent new risk. A local exception handler
alone cannot coordinate Router, Aggregator, Macro and Execution. Degradation must also avoid
blocking protective position reduction.

## Decision

The LLM gateway exposes an optional, bus-agnostic health hook. Text Scouts, Aggregator and Macro
Strategist publish `LLMHealthEvent` after calls on `kairos.llm.health`. A response is considered
healthy only after the provider response and strict output validation succeed. Provider
timeouts/5xx feed the per-model outage breaker; 4xx/bad output remain visible failures but do
not by themselves prove a provider outage.

Risk Manager is the single authority that consumes these events, updates per-model breakers and
broadcasts `SystemControl` on `kairos.system.control`. The implemented subscribers are:

- Router, which suppresses GPT escalation in `CONFLICT_SAFE` and suppresses new-exposure routes
  in `LOCAL_QUANT_MODE`;
- Aggregator, which clears/degrades text context or emits defensive tactical outcomes;
- Macro Strategist, which emits a defensive allocation when conflict/local modes apply;
- Execution Engine, which refuses `OPEN` in `LOCAL_QUANT_MODE` while preserving protective
  close/reduce-only actions.

Text Scouts does not subscribe to system control. The failing Flash call itself selects its
deterministic local low-confidence fallback. Quant Scouts contains no LLM and Risk does not
subscribe to its own broadcast.

Current mappings are:

| condition | resulting mode |
| --- | --- |
| all tracked models healthy | `NORMAL` |
| DeepSeek-V4-Flash unavailable | `TEXT_LOCAL_FILTER` |
| GPT-5.6 Sol unavailable | `CONFLICT_SAFE` |
| two or more tracked models unavailable | `LOCAL_QUANT_MODE` |

## Consequences

The health loop is automatic and has explicit subscribers. Degradation blocks routes that can
create exposure but does not turn an analytical outage into a ban on exiting risk. The gateway
retains no dependency on `kairos-core` or Redis.

Circuit-breaker and subscriber state is currently process-local, and Redis delivery remains
at-least-once. Until `kairos-persistence` inbox/outbox primitives are integrated into these
paths, a restart loses breaker history and there is no durable, atomic control-transition log.
