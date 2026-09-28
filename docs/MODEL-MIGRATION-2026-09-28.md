# LLM model-route migration — 2026-09-28

This receipt describes an engineering-only source change. It neither qualifies
the new providers on real distributions nor grants PAPER or LIVE authority.

| Workload | Requested model | Mode |
| --- | --- | --- |
| Text Scouts | `deepseek-flash` | non-thinking |
| Aggregator normal | `gpt-6-luna` | `medium` |
| Aggregator conflict | `gpt-6-sol` | `high` |
| Macro Strategist | `gpt-6-sol` | `xhigh` |

The LLM gateway remains the sole provider boundary. The service lockfiles now
pin `kairos-llm` to `c9d38407ed2e378e50d28a59b14d31d099056ab8`; Risk
Manager maps current model-health events to fail-closed degradation. Its Sol
route serves both conflict review and Macro, so a Sol outage cannot be treated
as conflict-only degradation. The deployment source locks and deterministic
gate identities are versioned for this source set. Historical frozen model
corpora, strategy plans, research ledgers and runtime data were not changed.

| Repository | Signed source revision | Component CI |
| --- | --- | --- |
| `kairos-llm` | `c9d38407ed2e378e50d28a59b14d31d099056ab8` | [CI](https://github.com/Kairos-cryptoAI/kairos-llm/actions/runs/36385608462) |
| `kairos-text-scouts` | `3d0b7c07e836c670598b0f96ccd7c4b2011e9d20` | [CI](https://github.com/Kairos-cryptoAI/kairos-text-scouts/actions/runs/36386218151) |
| `kairos-aggregator` | `fa96ef3cdc3201f1f6437e79d0dc1388e97c23fa` | [CI](https://github.com/Kairos-cryptoAI/kairos-aggregator/actions/runs/36386217913) |
| `kairos-macro-strategist` | `79a41d971b93637e6fdd153ebaa0f1c7b8cd9073` | [CI](https://github.com/Kairos-cryptoAI/kairos-macro-strategist/actions/runs/36386217892) |
| `kairos-risk-manager` | `eb6ad85a8238ef6b38ff152b10d5790eef94d576` | [CI](https://github.com/Kairos-cryptoAI/kairos-risk-manager/actions/runs/36385935992) |
| `kairos-deploy` | `1637b50a4c58d7f2a4de25ccc9e4bb065eced99e` | [CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/36387999136) |

The Windows-first local matrix for the five changed Python packages passed
all 75 declared checks across Python 3.11 and 3.14: locked dependencies,
lint, format, mypy, Bandit, unit tests and package builds. Unit totals per
version were 90 LLM, 90 Text Scouts, 50 Aggregator, 79 Macro (plus one
conditional skip), and 224 Risk Manager. Pytest emitted only cache-write
permission warnings. Deployment source projections, Compose rendering and
143 static unit checks passed before the signed deploy commit. The exact `r3`
current-source integration gate passed 7/7 locally and in
[GitHub CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/36387999085).
The isolated full-path SIM gate passed 22/22 locally and in
[GitHub CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/36387999101).
Its disposable PostgreSQL used tmpfs, with no host volumes or published ports;
only the two disposable `r3` project containers and networks were removed after
verification. The root current-release verifier then confirmed 14 clean,
signed, `origin/main`-matching repositories with exact gate projections.

The updated price table uses published peak DeepSeek rates and current OpenAI
rates: [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/),
[OpenAI pricing](https://developers.openai.com/api/docs/pricing). At the same
planning call/token volumes as the previous README scenario, the arithmetic is
`$58.30/month` for ordinary input or `$61.25/month` if every OpenAI input
token incurs the cache-write rate, compared with the prior `$78.98/month`
scenario. These are **estimates, not spend or a quality result**. The durable
gateway reserves at the higher possible input rate, reconciles reported
token categories, and fails closed on missing usage, unregistered prices or
accounting disagreement. Existing campaign caps remain OpenAI `$12`, DeepSeek
`$1`, and X `$2`; they were not raised.

No API-key values were read or copied, and no paid OpenAI, DeepSeek or X call,
EVEDEX call, PAPER service, canary or real order was made for this migration.
The older exact provider corpus belongs to the former model routes. Before
any operational reliance on these new routes, run a separately authorized
shadow qualification for schema validity, latency, availability, quota,
resolved-model identity and actual cost, then matched A/B against the same
strategy. A model price or offline schema pass does not prove trading alpha.
The current manifest keeps `TECHNICAL_PAPER_READY=false`,
`PAPER_QUALIFIED=false`, `ALPHA_READY=false`, `LIVE_READY=false`, and
`STRATEGY_POLICY=REJECT_ALL`.
