# Budget

Kairos is DeepSeek-first with GPT escalation. The current code routes routine text/tactical
work to DeepSeek-V4-Flash/Pro and conflict/macro work to GPT-5.6 Sol. The calculator in
`kairos-llm` uses standard list-price assumptions and no cache discount for its base scenario.

## Model assumptions

| layer | model | nominal calls/month | tokens in/out | modelled cost/month |
| --- | --- | ---: | ---: | ---: |
| Text Scouts | DeepSeek-V4-Flash | 14,400 | 1,500 / 300 | $4.2336 |
| Aggregator normal | DeepSeek-V4-Pro | 7,340 | 3,000 / 800 | $14.68734 |
| Aggregator conflict | GPT-5.6 Sol (`high`) | 1,300 | 3,000 / 2,200 | $105.30 |
| Macro Strategist | GPT-5.6 Sol (`xhigh`) | 60 | 15,000 / 5,500 | $14.40 |
| **API total** | | | | **$138.62** |

The matching `kairos-llm` test reproduces this $138.62 scenario from its pricing table. It is a
planning estimate, not a supplier quote or guaranteed ceiling. Provider prices, token volumes,
caching, retries and routing ratios must be re-checked before deployment and monitored at
runtime.

## Infrastructure assumption

The original planning scenario allowed approximately $118.90/month for a compute host and text
ingestion proxy, for a combined scenario of approximately $257.52/month. Actual infrastructure
now depends on deployment region, retention, monitoring and persistence load; obtain current
quotes rather than treating this historical planning number as authoritative.
