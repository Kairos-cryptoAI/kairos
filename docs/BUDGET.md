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
| **LLM total** | | | | **$72.204** |

The matching `kairos-llm` test reproduces this $72.204 scenario from its pricing table. It is a
planning estimate, not a supplier quote or guaranteed ceiling. Provider prices, token volumes,
caching, retries and routing ratios must be re-checked before deployment and monitored at
runtime.

## Feed assumptions

Text Scouts uses GDELT and RSS at no API charge, Reddit's official application API at no API
charge, and the official X API under a hard local ceiling of **$10.000000/month**. At the
registered 2026-08-18 prices, X charges
[$0.010 per returned User and $0.005 per returned Post](https://docs.x.com/x-api/getting-started/pricing).
Kairos resolves each configured handle once and durably reuses the User ID, so normal recurring
cost is dominated by new Post reads rather than User lookup.

The modeled LLM spend plus the maximum X allocation is therefore **$82.204/month**, leaving
**$7.796** of the stated `$90` budget as contingency. This is a ceiling allocation, not a
forecast: X charges only for returned resources and its own console spending limit must also be
set to `$10`.

## Infrastructure assumption

The original planning scenario allowed approximately $118.90/month for a compute host and a
now-removed text-ingestion proxy. Bright Data is no longer part of the architecture. Actual
infrastructure depends on deployment region, retention, monitoring and persistence load;
obtain current quotes rather than treating the historical planning number as authoritative.
