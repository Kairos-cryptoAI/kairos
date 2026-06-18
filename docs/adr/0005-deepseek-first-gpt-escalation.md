# 5. DeepSeek-first + GPT escalation

Date: 2026-06-18 · Status: accepted · Supersedes the GPT-5.5-only model split.

## Context
The first cut routed every analytical call through GPT-5.5 (mini for the routine flow,
flagship for high/xhigh). At 24/7 cadence the routine tiers dominated spend while adding
little edge over a cheaper model. The updated design document mandates a cost/quality split.

## Decision
Adopt **DeepSeek-first + GPT escalation**:
- Text Scouts -> DeepSeek-V4-Flash, *non-thinking* (no `reasoning.effort`).
- Aggregator-Normal -> DeepSeek-V4-Pro (the routine `STABLE_TREND_ENTRY` flow).
- Aggregator-Conflict -> GPT-5.5, `reasoning.effort=high` (signal divergence).
- Macro-Strategist -> GPT-5.5, `reasoning.effort=xhigh` (capital allocation).

The Router emits `ROUTE_PRO` (DeepSeek-V4-Pro) normally and escalates to `ROUTE_GPT`
(GPT-5.5) after 4 consecutive conflict ticks, returning after 10 calm ticks. The Circuit
Breaker degrades per model: Flash down -> Text Scouts local filtering (`TEXT_LOCAL_FILTER`);
GPT-5.5 down -> conflicts forced to `WAIT_CONFIRMATION` (`CONFLICT_SAFE`); two or more models
down -> `LOCAL_QUANT_MODE`.

## Consequences
The hot path is cheap and fast; GPT-5.5 is reserved for the highest cost-of-error decisions.
The standard list-price API budget drops to **$138.62/mo**, for a total of **$257.52/mo**
including infrastructure. Mixing a non-thinking DeepSeek call with an OpenAI
`reasoning.effort` parameter is explicitly disallowed.
