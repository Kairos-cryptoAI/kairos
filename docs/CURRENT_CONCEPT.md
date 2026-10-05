# Current Kairos trading concept and implementation scope

Updated: 2026-10-06 Europe/Moscow. This is the living target and scope index, not a research
plan/evaluator, frozen candidate, readiness receipt or launch authorization.
Historical dated receipts and Trial 15/V4/V5 evidence remain immutable.

## Objective and decision path

Kairos seeks independently demonstrated net trading value under fixed risk
limits, not a guaranteed monthly return or a daily trade count. A skipped day
is a valid decision. Only the new adaptive/LLM system is the prospective LIVE
candidate; Trial 15 remains an independent baseline without LIVE permission.

The target is:

1. Capture closed market data and source-attributed news at their actual
   availability times. Build one causal context with compact multi-timeframe
   features, slow macro context and explicit source availability.
2. Evaluate a selected, versioned adaptive strategy. Save both candidates and
   explicit no-action/unavailable outcomes; do not infer an evaluation from
   silence. A candidate fixes entry eligibility/expiry, side, stop, target and
   timeout. Trade count is an outcome, never a quota.
3. Router selects the review workload. Review returns only `ALLOW/VETO/DEFER`;
   it cannot change the candidate. Independent LLM hypotheses are a distinct
   research arm even when there is no quant intent, not direct orders.
4. Deterministic Risk checks exact approval, account, regime/capital policy,
   freshness, venue and fixed risk ceilings: at most 0.25% per trade and 1%
   total open risk. Model confidence never raises these ceilings.
5. Execution journals external effects, confirms position protection, handles
   partial fills/exit races and reconciles the account after restart. Unknown
   or unowned exposure blocks new entries.

Market regime, slow macro information and capital allocation are different
concepts. A capital weight is not entry permission; a model regime hint is not
a source-bound deterministic detector. Range trading must use its own explicit
compatible policy, not silently treat `CHOP` as `RANGE`.

## Existing reusable implementation

- Canonical closed 1m bars and causal resampling to 3m/5m/15m/30m/1h already
  exist. Do not rewrite them or pretend a compact MarketSnapshot is a complete
  OHLC history or warmup proof.
- Shared pure generators, immutable intent/review contracts, deterministic
  sizing, the protected execution lifecycle and reconciliation are reusable.
- Managed historical replay and book-based durable SIM are separate useful
  execution approximations. Neither alone measures the three-arm campaign's
  complete matched net economics.
- The existing campaign saves causal observations, failures and costs. Its
  denominator is engineering coverage, not naturally closed trade count or
  proof of profitability.

## Capability boundaries and required remaining work

| component/path | current boundary | work needed for the target |
| --- | --- | --- |
| Adaptive strategy | no selected/frozen LIVE candidate or evaluator | select one hypothesis and executable regime/entry/exit policy; validate before freezing |
| Strategy evaluation | explicit causal runtime receipts separate intent, valid no-intent, warmup, disabled and unavailable/error states | enroll only the selected new strategy; unsupported generators do not acquire adaptive eligibility |
| Market and news context | immutable source receipts and exact declared bar tail; compact messages do not prove full warmup/raw-news availability | production history resolver, durable point-in-time source archive and source-specific qualification |
| Candidate review | runtime consumes source-bound context; required missing/late inputs defer before a provider call | exact new-contract/provider qualification; old context-free corpus is not qualifying evidence |
| Macro and regime/capital | opt-in versioned policy and account-bound allocation; legacy behavior unchanged; external macro/onchain unavailable | selected deterministic detector publisher, durable capital-basis recovery, accepted policy/source set and independent input qualification |
| Ordinary PAPER execution | bounded technical-canary admission | separately reviewed adaptive admission after strategy/venue qualification; never remove canary guards globally |
| PAPER Compose | technical DEV-canary topology, not complete analytics | one accepted full analytical/runtime source set and topology |
| Matched research economics | observation journal, not complete economic evaluator | common causal fills, arm latency, funding, fees and model/feed costs; natural closes and sealed evaluation |
| Current release | engineering-only source identity | exact matching Windows, integration and CI evidence; no inheritance from historical green runs |
| Production | LIVE startup blocked | security, custody, backup/restore, alerts, limits and manual arming after all gates |

The ordinary technical-canary deployment and legacy DRY_RUN must not be
relabelled as a complete adaptive system. A contract implementation, a fixture
PASS, a built image and an operating/qualified service are separate claims.

The context receipt keeps separate event time, trusted local availability and
capture time. Later capture cannot admit evidence that arrived after the route's
knowledge cut. Required market/bars and route-referenced text must be available;
optional unavailable sources stay explicitly unavailable. The bounded in-process
store is not a durable history archive or exactly-once paid model dispatch.

The regime/capital profile is disabled by default. It binds exact strategy,
policy, detector, source set, intent and account identity; `UNCERTAIN` has no entry
capability and `CHOP` is not reinterpreted as `RANGE`. No detector, policy file or
allocation creates authority without the existing independent risk gates.

## Keep in the critical path

- One selected adaptive hypothesis, one executable policy/evaluator and one
  reproducible source set. Preserve failed/no-fill/no-action observations.
- Compare strategy-only, strategy-review and independent LLM proposals on the
  same causally available inputs, accounting for actual arm delays and all
  execution/provider costs. A direction prediction is not an executable trade.
- Existing own-campaign 365 future days plus 500 naturally closed simulated
  trades, one sealed evaluator and the preregistered crash/net-risk checks.
  These are the approved policy, not a mathematical profitability guarantee.
- Independent real EVEDEX DEV read-only/canary/soak and production safety gates.
  Binance data does not qualify EVEDEX liquidity or actual execution.
- Existing shared paid-budget history and fixed limits; OpenAI-only defaults.
- Actual recoverability, reconciliation, critical alert delivery and secret
  isolation before trading authority. UI/UX remains deferred.

## Do not make prerequisites without a concrete reason

- Completing Trial 15 or V4/V5 before the new adaptive system. Preserve their
  evidence and approved observation process separately; transfer no blind days.
- Continuing every rejected screen/parameter grid or supporting every legacy
  generator in the new adapter. Reuse only selected building blocks.
- More providers/feeds/indicators for completeness, complex portfolio-LLM
  allocation before a real portfolio exists, grid/trailing/multi-target exits,
  a monorepo migration, a large rewrite or a graphical Cockpit now.
- A bespoke BuildKit adapter as an intrinsic alpha/LIVE condition. Synthetic
  direct and Compose receipts exist; real-release use remains separate.

## Runtime recovery decision

The October 5 archive diagnostic is not accepted primary recovery. Resuming the
old runtime requires its own accepted backup/schema/outbox/lease evidence. A
prospective separate runtime is an alternative design decision, not authority
to reset queues, leases, budgets or history. It would require an exclusive
reviewed cutover, account/effect/risk-baseline reconciliation and its own verified
backup/restore. Preserve the old database/outbox/evidence immutably and carry
prior paid spend and outstanding reservations into the authoritative shared
budget. No primary mutation or consumer start follows from this document.

## Source of truth

- Readiness and current source identity: [current-release.json](../config/current-release.json).
- Model defaults and qualification boundary: [ADR 10](adr/0010-openai-only-current-routing.md).
- Spending authority and historical estimates: [BUDGET.md](BUDGET.md).
- Current recovery boundary: [RECOVERY-2026-10-05.md](RECOVERY-2026-10-05.md).
- Original dated approved trading concept: [TRADING-CONCEPT-2026-09-28.md](TRADING-CONCEPT-2026-09-28.md).
- Existing engineering research acceptance: [adaptive scoped source set](../config/adaptive-causal-source-set.json).
- Current structural corrections and test boundaries: [engineering receipt](CONCEPT-CORRECTIONS-2026-10-06.md).

Implementation changes in a new engineering source set do not enroll a
candidate, adopt a budget, qualify a model, disclose blind PnL, change the frozen
plan/evaluator or enable PAPER/LIVE. All current readiness flags remain false
and `STRATEGY_POLICY=REJECT_ALL`.
