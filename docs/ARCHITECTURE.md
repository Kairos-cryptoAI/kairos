# Kairos Architecture

Six layers, connected by a single message bus. Each layer is an independently deployable
service that speaks only the typed contracts defined in `kairos-core`.

## Data flow & contracts
| from → to | topic | message |
| --- | --- | --- |
| Quant Scouts → Router | `kairos.market.snapshot` | `MarketSnapshot` |
| Text Scouts → Router | `kairos.sentiment.signal` | `SentimentSignal` |
| Router → Aggregator | `kairos.router.decision` | `RouterDecision` |
| Aggregator → Risk | `kairos.aggregator.command` | `TacticalCommand` |
| Macro → Risk | `kairos.macro.allocation` | `StrategicAllocation` |
| Risk → Execution | `kairos.risk.validated_order` | `ValidatedOrder` |
| Execution → all | `kairos.execution.report` | `ExecutionReport` |
| Circuit Breaker → all | `kairos.system.control` | mode broadcast |

## Layer 1 — Scouts
Collect everything, forward only dry, compressed content.
- **1A Quant Scouts** (pure math, no LLM): WebSocket order book, funding rate, open
  interest, liquidations; RSI/MACD; emits 1-minute `MarketSnapshot`s.
- **1B Text Scouts**: ~100 items / 5 min → local filter keeps ~5 → LLM (`low`) returns
  structured sentiment.

## Layer 2 — Router (deterministic FSM)
Protects the API budget. `USE_MEDIUM` normally; counts conflict ticks when quant and text
disagree; after **4** consecutive conflicts → `USE_HIGH`; returns to `USE_MEDIUM` only
after **10** calm ticks (hysteresis / anti-chatter).

## Layer 3 — Aggregator (tactical)
- **Normal (`medium`)**: calm market, maintain grid / follow trend → `STABLE_TREND_ENTRY`.
- **Conflict (`high`)**: weigh technicals vs. news → `WAIT_CONFIRMATION` / `REDUCE_LEVERAGE`.

## Layer 4 — Macro-Strategist (strategic, `xhigh`)
Daily/weekly rebalancing + shock-event response (e.g. −10%/h). Sets regime, stablecoin
reserve, per-strategy weights and max gross leverage. Defensive fallback: 60% stables /
40% delta-neutral.

## Layer 5 — Risk Manager & Circuit Breaker (deterministic)
Validates every command: leverage >10x → capped to 5x; daily drawdown ≥3% → forced
`NO_TRADE`; min notional $5. **Circuit Breaker**: >2 consecutive LLM API 5xx/timeouts →
detach LLM 5 min → `LOCAL_QUANT_MODE` (local stop-loss scripts protect positions).

## Layer 6 — Execution Engine
Atomic order execution; switches only on the validated `reason_code`. EVEDEX adapter is
EIP-712 signed; every position is armed with a **server-side trailing stop**. CCXT adapter
for testing on other venues.

## GPT-5.5 usage summary
| component | effort | frequency | latency |
| --- | --- | --- | --- |
| Text Scouts | low | every 1-2 min, batched | 1-3 s |
| Aggregator (normal) | medium | every 3-5 min | 3-5 s |
| Aggregator (conflict) | high | only on signal divergence | 5-15 s |
| Macro-Strategist | xhigh | daily / on black swan | minutes |
