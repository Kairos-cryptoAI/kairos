# Kairos Architecture

Six layers, connected by a single message bus. Each layer is an independently deployable
service that speaks only the typed contracts defined in `kairos-core`. The analytics stack is
**DeepSeek-first + GPT escalation**: cheap DeepSeek models carry the routine flow and GPT-5.5
is reserved for the highest cost-of-error decisions.

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
| any LLM layer → Risk | `kairos.llm.health` | `LLMHealthEvent` |

## Layer 1 — Scouts
Collect everything, forward only dry, compressed content.
- **1A Quant Scouts** (pure math, no LLM): WebSocket order book, funding rate, open
  interest, liquidations; RSI/MACD; emits 1-minute `MarketSnapshot`s.
- **1B Text Scouts**: ~100 items / 5 min → local filter keeps ~5 → **DeepSeek-V4-Flash
  (non-thinking)** returns structured sentiment. If Flash is unavailable the layer drops to a
  deterministic local keyword fallback (low confidence) instead of going dark.

## Layer 2 — Router (deterministic FSM)
Protects the API budget. `ROUTE_PRO` normally (routine flow on DeepSeek-V4-Pro); counts
conflict ticks when quant and text disagree; after **4** consecutive conflicts → `ROUTE_GPT`
(escalate to GPT-5.5); returns to `ROUTE_PRO` only after **10** calm ticks (hysteresis /
anti-chatter).

## Layer 3 — Aggregator (tactical)
- **Normal (`ROUTE_PRO`)**: DeepSeek-V4-Pro; calm market, maintain grid / follow trend →
  `STABLE_TREND_ENTRY`.
- **Conflict (`ROUTE_GPT`)**: GPT-5.5 `reasoning.effort=high`; weigh technicals vs. news →
  `WAIT_CONFIRMATION` / `REDUCE_LEVERAGE`.

## Layer 4 — Macro-Strategist (strategic)
**GPT-5.5 `reasoning.effort=xhigh`.** Daily/weekly rebalancing + shock-event response
(e.g. −10%/h). Sets regime, stablecoin reserve, per-strategy weights and max gross leverage.
Defensive fallback: 60% stables / 40% delta-neutral.

## Layer 5 — Risk Manager & Circuit Breaker (deterministic)
Validates every command: leverage >10x → capped to 5x; daily drawdown ≥3% → forced
`NO_TRADE`; min notional $5. **Per-model Circuit Breaker** (>2 consecutive 5xx/timeouts trips
a model):
- DeepSeek-V4-Flash down → `TEXT_LOCAL_FILTER` (Text Scouts filter locally).
- GPT-5.5 down → `CONFLICT_SAFE` (conflict decisions forced to `WAIT_CONFIRMATION`).
- two or more models down → `LOCAL_QUANT_MODE` (local stop-loss scripts protect positions).

The breakers are fed **automatically**: every layer emits an `LLMHealthEvent` after each model
call, the Risk Manager subscribes to `kairos.llm.health`, resets a breaker on a healthy call and
trips it on 5xx/timeouts, then broadcasts the resulting mode (see ADR-0006).

## Layer 6 — Execution Engine
Atomic order execution; switches only on the validated `reason_code`. EVEDEX adapter is
EIP-712 signed; every position is armed with a **server-side trailing stop**. CCXT adapter for
testing on other venues.

## Model usage summary
| component | model / mode | frequency | latency |
| --- | --- | --- | --- |
| Text Scouts | DeepSeek-V4-Flash, non-thinking | every 1-2 min, batched | 1-3 s |
| Aggregator (normal) | DeepSeek-V4-Pro | every 3-5 min | 3-5 s |
| Aggregator (conflict) | GPT-5.5, `high` | only on signal divergence | 5-15 s |
| Macro-Strategist | GPT-5.5, `xhigh` | daily / on black swan | minutes |
