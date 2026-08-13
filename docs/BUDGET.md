# Budget

Kairos routes each workload to a cost/quality tier. Text extraction uses DeepSeek-V4-Flash-0731,
routine tactical work uses GPT-5.6 Luna, conflict resolution uses GPT-5.6 Terra, and strategic
allocation uses GPT-5.6 Sol. The calculator in `kairos-llm` uses the list prices adopted on
2026-08-13 and no cache discount for its base scenario.

## Model assumptions

| layer | model | nominal calls/month | tokens in/out | modelled cost/month |
| --- | --- | ---: | ---: | ---: |
| Text Scouts | DeepSeek-V4-Flash-0731, non-thinking | 14,400 | 1,500 / 300 | $4.2336 |
| Aggregator normal | GPT-5.6 Luna (`medium`) | 7,340 | 3,000 / 800 | $11.4504 |
| Aggregator conflict | GPT-5.6 Terra (`high`) | 1,300 | 3,000 / 2,200 | $42.12 |
| Macro Strategist | GPT-5.6 Sol (`xhigh`) | 60 | 15,000 / 5,500 | $14.40 |
| **API total** | | | | **$72.204** |

The matching `kairos-llm` test reproduces this $72.204 scenario from its pricing table. It is a
planning estimate, not a supplier quote or guaranteed ceiling. Provider prices, token volumes,
caching, retries and routing ratios must be re-checked before deployment and monitored at
runtime.

## Infrastructure assumption

The original planning scenario allowed approximately $118.90/month for a compute host and text
ingestion proxy, for a combined scenario of approximately $191.104/month. Actual infrastructure
now depends on deployment region, retention, monitoring and persistence load; obtain current
quotes rather than treating this historical planning number as authoritative.
