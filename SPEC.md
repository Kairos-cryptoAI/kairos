# Kairos — Concept Specification

Kairos is intended to be a controlled futures-analysis and trading system. Its
target is a causal pipeline from verified market and contextual inputs through
strategy/review, deterministic risk, protected execution and reconciliation.
This is the target architecture, not a claim that one complete composition is
currently wired, qualified or authorized to trade.

## Authority and safety

**The LLM never trades directly.** Models receive typed, bounded context and
return schema-validated analysis. Deterministic components retain authority over
candidate routing, risk, account freshness, system degradation and execution.
Independent research proposals are not strategy intents; they must remain
separately attributable and pass the same review and risk boundaries before
they could become executable candidates.

An owner-approved research or trading task does not itself override the active
`STRATEGY_POLICY=REJECT_ALL`, readiness gates, or LIVE canary's owner-defined
dollar-cap and daily stop-loss requirements. Readiness markers, component tests, synthetic execution
and research receipts are not trading authorization. No code path may treat
permission to investigate or trade as permission to bypass these controls.

## Model strategy — workload-specific OpenAI routing

The current default workload routes in
[`kairos-llm/kairos_llm/models.py`](https://github.com/Kairos-cryptoAI/kairos-llm/blob/c2207a5bd8bbf39e7d5728f95e52c96a47eca344/kairos_llm/models.py) are:

| workload | default model | reasoning effort |
| --- | --- | --- |
| Text Scouts | `gpt-6-luna` | `low` |
| Aggregator normal review | `gpt-6-luna` | `medium` |
| Aggregator conflict review | `gpt-6.1-sol` | `high` |
| Macro Strategist | `gpt-6.1-sol` | `xhigh` |

The default router permits OpenAI only. Workload-specific routing is
authoritative for production callers; the effort-only map is retained for
backward compatibility. This describes configured defaults, not proof of live
provider calls, paid qualification, quality, availability or economic value.

## Existing paths and target composition

The target flow is:

`verified closed bars + time-aligned text/macro context → technical intents and
independent proposals → deterministic candidate routing and review → Risk →
protected execution → reconciliation and accounting`.

Existing code exposes distinct paths that must not be conflated:

- Candidate contracts and handlers connect closed bars, strategy intents,
  candidate routes, causal review context and risk decisions. Their presence
  does not establish one running end-to-end target composition.
- An isolated sealed simulator path has an accepted proof from closed bars
  through Strategy, Router, a deterministic review test double, SIM risk and
  durable simulator execution. It is not real-provider review, EVEDEX PAPER,
  venue qualification or evidence of alpha.
- Legacy DRY_RUN and research/SIM variants remain compatibility or
  experiment-specific paths, with their own contracts and evidence. They are
  not interchangeable with the target candidate path.

The immediate integration result is one existing-component, current-context
adaptive-to-SIM lifecycle proof using explicitly synthetic/no-network inputs.
It is not a paid model or economic experiment. After that, a bounded comparison
must preserve declared inputs, decisions, rejections, costs and missing-data
states for strategy-only and the system on the same declared window.
It need not be profitable to be informative. Do not add parallel strategies,
notifier generations, universal research frameworks or UI as substitutes for
that result. Preserve historical evidence and existing monitors.

## Runtime and readiness boundary

The system has durable inbox/outbox and execution-effect mechanisms, but their
existence does not prove that the desired cross-service composition is wired or
currently running. The exact current readiness manifest is authoritative;
all readiness markers remain false and strategy policy remains
`REJECT_ALL`. Research preparation and isolated engineering acceptance do not
promote readiness.

Risk must continue to enforce reconciled account/venue facts and its configured
loss-at-stop limits. Real trading must honor the owner's explicit dollar-cap
and daily stop-loss rules, fail closed on stale or incomplete inputs, and
retain the required approval and readiness sequence. Synthetic no-network
fixtures need no real capital allocation. Trading,
provider spend, services and external venues are outside this specification's
authorization.

See [architecture](docs/ARCHITECTURE.md), [status](docs/STATUS.md), and the
[ADRs](docs/adr/).
