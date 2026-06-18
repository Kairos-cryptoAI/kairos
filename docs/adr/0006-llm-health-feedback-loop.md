# 6. LLM health feedback loop

Date: 2026-06-18 · Status: accepted · Extends ADR-0005.

## Context
The per-model circuit breakers (ADR-0005) can degrade the system, but nothing fed them: each
layer caught its own 5xx/timeout locally and the Risk Manager never learned which model was
unhealthy, so `SystemMode` never changed automatically.

## Decision
Every LLM call emits an `LLMHealthEvent` (provider, model, ok, kind) on `kairos.llm.health`.
The `LLMGateway` exposes an optional `on_health` hook; Text Scouts, Aggregator and
Macro-Strategist publish the event to the bus. The Risk Manager subscribes and feeds its
per-model breakers: a healthy call resets a breaker, 5xx/timeouts trip it; bad-output/4xx are
ignored (the API answered). The resulting `SystemMode` is broadcast on `kairos.system.control`.

## Consequences
The degradation loop is now closed and automatic: a DeepSeek-V4-Flash outage flips the system to
`TEXT_LOCAL_FILTER`, a GPT-5.5 outage to `CONFLICT_SAFE`, and two or more outages to
`LOCAL_QUANT_MODE` — with no manual intervention. The gateway stays bus-agnostic (the hook is
optional), so `kairos-llm` keeps zero dependency on the message bus.
