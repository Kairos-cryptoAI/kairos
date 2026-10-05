# Budget

## Current authority

Default routing is OpenAI-only: Text `gpt-6-luna/low`, normal review
`gpt-6-luna/medium`, conflict `gpt-6.1-sol/high`, allocation
`gpt-6.1-sol/xhigh`. The implementation registry in `kairos-llm/models.py` is
authoritative; [ADR 10](adr/0010-openai-only-current-routing.md) records this
supersession. These defaults are not a benchmark win or a current price quote.

The existing shared qualification campaign retains cumulative ceilings of
OpenAI **$12**, DeepSeek **$1**, and X **$2**, including committed spend and
uncertain reservations. Default OpenAI-only routing does not erase past
DeepSeek costs, reservations or audit records. A new strategy, namespace,
month, source revision or model route cannot reset those balances.

No larger runtime budget has been granted. Calls require the admitted durable
budget authority and their bounded preflight; insufficient budget or ambiguous
outcomes fail closed. Current remaining authority must come from that ledger,
not subtraction from the old numbers below. Models are called on scheduled
observations/candidates/material events, not automatically for every bar.

## Historical planning scenario — 2026-08-13/18

Everything below is a retained historical estimate or dated observation,
**not current routing, price, balance, feed entitlement or spending authority**.
The old calculator used August list prices and no cache discount. Re-check
official prices and actual tokens before a prospective budget decision; do not
use the $72.204 scenario to fund the current routes.

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
its nominal call volumes. OpenAI routing therefore uses adaptive admission: routine Luna calls
are preferred, Terra is conflict-only, and Sol remains a scheduled strategic escalation.
Text Scouts, Aggregator and Macro reserve spend before each call in a shared, durable
provider-wide PostgreSQL ledger. The current development/shadow qualification ceilings are the
stricter `$1` for DeepSeek and `$12` for OpenAI; X is separately capped at `$2` for this stage.
The larger `$4.50`/`$45` figures remain only future target runtime allocations and are not granted
to the current shadow services. A failed or ambiguous call retains its reservation, and no paid
call is allowed without the durable backend.

After the frozen corpus runs on 2026-08-26, the shared ledger records `$0.001171` of committed
DeepSeek cost and `$0.025494` of committed OpenAI cost. It also retains `$0.154624` of OpenAI
reservations from failed or ambiguous attempts, deliberately reducing remaining local authority
even when provider billing may ultimately be lower. The single funded X probe committed
`$0.060000`. Provider consoles remain authoritative for billed balances; qualification tools
must keep their explicit per-run preflight cap and targeted replay behavior.

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
