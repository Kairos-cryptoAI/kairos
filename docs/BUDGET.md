# Budget

Two cost groups: infrastructure and the DeepSeek + OpenAI API. The architecture is
**DeepSeek-first + GPT escalation**, so the routine flow runs on cheap DeepSeek models and
GPT-5.5 is reserved for conflict resolution and macro strategy. Base figures use standard list
prices, without batch/priority and without cache hits (so the budget is not understated).

## Infrastructure (~$118.90 / mo)
| item | purpose | $/mo |
| --- | --- | --- |
| Hetzner CX43 VPS | 8 vCPU, 16 GB RAM, 160 GB SSD, 20 TB traffic, 1 IPv4 — Execution Engine, TimescaleDB, local microscripts | ~$19 |
| Oxylabs Residential Basic 20 GB | residential proxies for Text Scouts (avoid X / news rate-bans) | ~$100 |

## API (DeepSeek-first + GPT escalation)
Prices /1M tokens: DeepSeek-V4-Flash $0.14 / $0.28 · DeepSeek-V4-Pro $0.435 / $0.87 ·
GPT-5.5 $5 / $30.

| layer | model | calls/mo | tokens in/out | $/mo |
| --- | --- | --- | --- | --- |
| Text Scouts | DeepSeek-V4-Flash | 14,400 | 1,500 / 300 | $4.2336 |
| Aggregator normal | DeepSeek-V4-Pro | 7,340 | 3,000 / 800 | $14.68734 |
| Aggregator conflict | GPT-5.5 (`high`) | 1,300 | 3,000 / 2,200 | $105.30 |
| Macro-Strategist | GPT-5.5 (`xhigh`) | 60 | 15,000 / 5,500 | $14.40 |
| **API total** | | | | **$138.62** |

## Totals
| group | $/mo |
| --- | --- |
| Infrastructure | $118.90 |
| API (DeepSeek + OpenAI) | $138.62 |
| **Stack total** | **$257.52** |

≈ **$258 / mo**. The `test_monthly_api_budget_matches_doc` test in `kairos-llm` reproduces the
$138.62 figure from these per-layer formulas.
