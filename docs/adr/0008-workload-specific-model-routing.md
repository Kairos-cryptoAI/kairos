# 8. Workload-specific model routing

Date: 2026-08-13 · Status: accepted · Supersedes the routing decision in ADR-0005 and the
model mapping portions of ADR-0006/0007.

## Context

The first GPT-5.6 migration still selected concrete models through a global reasoning-effort
map. That couples unrelated future callers to the same provider and left the frequent normal
Aggregator path on DeepSeek-V4-Pro while both GPT-5.6 Luna and Terra received material price
reductions. DeepSeek also upgraded the `deepseek-v4-flash` API alias to the re-post-trained
DeepSeek-V4-Flash-0731 at the existing price.

## Decision

Select models by explicit workload role:

| workload | requested model | reasoning |
| --- | --- | --- |
| Text Scouts | `deepseek-v4-flash` (currently V4-Flash-0731) | explicitly disabled |
| Aggregator normal | `gpt-5.6-luna` | `medium` |
| Aggregator conflict | `gpt-5.6-terra` | `high` |
| Macro Strategist | `gpt-5.6-sol` | `xhigh` |

OpenAI workloads use the Responses API and native structured parsing. DeepSeek continues to use
the official OpenAI-compatible Chat Completions API with `thinking.type=disabled`, JSON output,
and local strict schema validation. The stable DeepSeek API alias is requested; response model
metadata is retained separately so provider-side alias updates can be observed.

Domain `ReasoningEffort` remains in decisions and audit output, but it is not the primary model
registry key. A compatibility effort map is retained only for existing external callers.

The Risk Manager tracks each model and an aggregate OpenAI provider breaker. Flash failure
selects `TEXT_LOCAL_FILTER`; Luna failure or an OpenAI provider outage selects
`LOCAL_QUANT_MODE`; Terra/Sol failure selects `CONFLICT_SAFE`; multiple model outages select
`LOCAL_QUANT_MODE`.

## Consequences

Under the documented call/token scenario, model API cost falls from approximately $138.62 to
$72.204 per month, while Sol remains reserved for the rare capital-allocation path. Price is a
planning input rather than a quality result: the migration requires representative shadow
evaluation of schema validity, tactical disagreement, defensive fallback rate, latency and
actual token cost before live trading qualification.

Stable aliases improve operational simplicity but can change behavior without a repository
commit. Telemetry must therefore distinguish the requested model from provider-resolved model
metadata, and unexpected model changes must be visible in monitoring.
