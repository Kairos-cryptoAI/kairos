# 3. Deterministic risk filters and a circuit breaker

Date: 2026-06-05 · Status: accepted

## Context
Even bounded commands can be wrong (leverage too high, trading into a drawdown). And the
model API itself can fail.

## Decision
A pure-Python (Pydantic) Risk Manager validates every command independently of the model:
leverage >10x → 5x, daily drawdown ≥3% → `NO_TRADE`, min notional $5. A circuit breaker
detaches the LLM after >2 consecutive API 5xx/timeouts and drops the system into
`LOCAL_QUANT_MODE` for 5 minutes, where local stop-loss scripts protect open positions.

## Consequences
Safety logic is testable, fast and never depends on the model being healthy.
