# 4. Redis Streams as the message bus

Date: 2026-06-05 · Status: accepted

## Context
Layers are independent services that must exchange typed messages with at-least-once
delivery and replay after a crash, without a heavy broker.

## Decision
Use Redis Streams (consumer groups + `XACK`) behind the `MessageBus` abstraction in
`kairos-core`. An `InMemoryBus` backs unit tests. The interface is transport-agnostic so we
can swap in NATS/Kafka later without touching services.

## Consequences
Cheap, already-in-the-stack (Redis is also our cache), good enough throughput for
minute-cadence trading. Not partition-tolerant like Kafka — acceptable at this scale.
