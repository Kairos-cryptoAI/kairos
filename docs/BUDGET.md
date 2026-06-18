# Budget

Two cost groups: infrastructure and OpenAI API.

## Infrastructure (~$100 / mo)
| item | purpose | $/mo |
| --- | --- | --- |
| VPS (8 vCPU, 16-32 GB) | Execution Engine, TimescaleDB, local microscripts | $40-60 |
| Residential proxies (15-20 GB) | Text Scouts (avoid X / news rate-bans) | $40-50 |

## OpenAI API (GPT-5.5 tariff: $5/M in, $30/M out, $0.50/M cached)
| layer | load | tokens/req | $/req | $/mo |
| --- | --- | --- | --- | --- |
| Text Scouts (low) | ~14,400/mo | 1.5k in / 0.3k out | ~$0.012 | ~$170 |
| Aggregator normal (medium) | ~7,340/mo | 3k in / 0.8k out | ~$0.030 | ~$220 |
| Aggregator conflict (high) | ~1,300/mo | 3k in / 2.2k out | ~$0.072 | ~$94 |
| Macro-Strategist (xhigh) | ~60/mo | 15k in / 5.5k out | ~$0.24 | ~$14 |

System-prompt caching cuts input cost ~40-50%.

## Totals
- **Full**: ~$700-850 / mo (infra ~$100 + API ~$500 + volatility buffer $100-150).
- **Cost-optimised** (cheap models for low/medium, flagship only for high/xhigh):
  **~$250-350 / mo**. This is the default split configured in `kairos-llm`.
