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
runtime. In particular, this unconstrained call-volume scenario does **not** fit the funded
OpenAI balance below.

## Funded monthly envelope

The funded balances reported on 2026-08-18 are `$5` DeepSeek, `$50` OpenAI and `$10` X:
`$65` total. They cover development, qualification and the following month of shadow work;
they are not a one-day test allowance.

| provider | funded | development / recovery reserve | target runtime allocation | old unconstrained scenario |
| --- | ---: | ---: | ---: | ---: |
| DeepSeek | $5.00 | $0.50 | $4.50 | $4.2336 |
| OpenAI | $50.00 | $5.00 | $45.00 | $67.9704 |
| X | $10.00 | $1.00 | $9.00 | up to $10.00 |
| **total** | **$65.00** | **$6.50** | **$58.50** | **$82.204** |

Therefore the old scenario exceeds the funded envelope by `$17.204` and must not be run at
its nominal call volumes. OpenAI routing needs adaptive admission and a durable provider budget:
routine Luna calls are preferred, Terra is conflict-only, and Sol remains a scheduled strategic
escalation. Until that durable LLM reservation path is wired into every caller, continuous paid
soak is disabled.

The first bounded qualification used an estimated `$0.00001778` of DeepSeek and `$0.00236160`
of OpenAI. The single funded X probe reserved and committed `$0.060000`. Thus Kairos recorded
`$0.06237938` of development usage; provider consoles remain authoritative for billed balances.
Qualification tools must use one sample, route selection and their explicit preflight cost cap
unless a larger experiment has been separately budgeted.

## Feed assumptions

Text Scouts uses GDELT and RSS at no API charge, Reddit's official application API at no API
charge, and the official X API under a hard local ceiling of **$10.000000/month**. At the
registered 2026-08-18 prices, X charges
[$0.010 per returned User and $0.005 per returned Post](https://docs.x.com/x-api/getting-started/pricing).
Kairos resolves each configured handle once and durably reuses the User ID, so normal recurring
cost is dominated by new Post reads rather than User lookup.

X charges only for returned resources. Its provider console limit stays at `$10`, while normal
runtime ingestion targets `$9` so `$1` remains available for controlled diagnostics and recovery.
The first authenticated funded request read one User and ten Posts for exactly `$0.060000`;
the Posts were valid but older than the qualification freshness window.

## Infrastructure assumption

The original planning scenario allowed approximately $118.90/month for a compute host and a
now-removed text-ingestion proxy. Bright Data is no longer part of the architecture. Actual
infrastructure depends on deployment region, retention, monitoring and persistence load;
obtain current quotes rather than treating the historical planning number as authoritative.
