# Current Kairos trading concept and implementation scope

Updated: 2026-10-07 Europe/Moscow. This is the living target and scope index, not a research
plan/evaluator, frozen candidate, readiness receipt or launch authorization.
Historical dated receipts and Trial 15/V4/V5 evidence remain immutable.

## Active work: strategy selection only

The user's latest direction pauses further system integration while strategy
families are selected. Existing news/Macro/Router/review/economic transport
engineering is preserved, not removed or extended here. The previous adaptive
implementation is a provisional research challenger, not a proven selected
champion. Keep a small shortlist of aligned right-tail with its exact base as a
slow historical reference, default intraday breakout as an active negative
control, and the existing event-driven adaptive challenger. The
[selection receipt](STRATEGY-SELECTION-2026-10-06.md) records the evidence,
reference-geometry incompatibilities, excluded paths and next bounded research
question. No family is enrolled or allowed to trade by this selection work.

The [completed October 7 paired diagnostic](STRATEGY-SELECTION-2026-10-07.md)
keeps this shortlist provisional: nine/eight natural closes per cost scenario
cannot select a final champion, and slow alignment trades off return/drawdown
in one slice without improving the other three. The finite experiment is
complete; final strategy selection still needs broader predefined coverage
and observable event-driven entries. Do not integrate an unproved winner,
rescue these returns with extra tuning, or assume future LLM profitability.

The separately [preregistered full-calendar attempt](STRATEGY-CALENDAR-RESULT-2026-10-07.md)
stopped on SOL input gaps before any generation or annual economics. Preserve
the failure; it neither selects nor rejects a strategy on performance. A
complete accepted historical source set and a separately agreed next protocol
are prerequisites, not an excuse to fill missing bars, drop SOL or rerun this
pass. Event-driven entry observability remains a separate missing capability.

Continued source investigation supports a separate
[PRICE_ONLY slow-reference protocol](STRATEGY-PRICE-SOURCE-PROTOCOL-2026-10-07.md):
official daily rows supply exact absent minutes; the original XRP optional-field
defect is retained/quarantined, not repaired. All existing OHLC/clocks remain.
Only the two unchanged price reference consumers and common evaluator may use
uniform unavailable-field projection. This is not generic adaptive/volume or
production source qualification. The old attempt is not resumed, and annual
reference economics cannot replace final adaptive/LLM selection or forward gates.

The [completed price-only annual comparison](STRATEGY-PRICE-RESULT-2026-10-07.md)
now covers all sixteen 2022--2025 cells and independently checked ledgers.
Its original rule returns `NO_ECONOMIC_REFERENCE_WINNER`: aligned's higher
primary returns do not overcome the 2023 drawdown tradeoff or both arms'
observed mark-risk overruns. Preserve the finished negative selection and
original sources without a rescue run. Broad slow-reference comparison is no
longer an unexecuted task; native event-driven entry observability and a
defensible final adaptive identity remain missing. No news/LLM integration,
campaign freeze or trading permission is inferred.

## Objective and decision path

Kairos seeks independently demonstrated net trading value under fixed risk
limits, not a guaranteed monthly return or a daily trade count. A skipped day
is a valid decision. Only the new adaptive/LLM system is the prospective LIVE
candidate; Trial 15 remains an independent baseline without LIVE permission.

The target is:

1. Capture closed market data and source-attributed news at their actual
   availability times. Build one causal context with compact multi-timeframe
   features, slow macro context and explicit source availability.
2. Evaluate a selected, versioned adaptive scenario system, which may combine
   bounded existing strategy families rather than require one new algorithm.
   Save candidates and explicit no-action/unavailable outcomes; do not infer an evaluation from
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

The economic target belongs to the complete system, not exclusively to the
deterministic strategy. Strategy-only remains a control for measuring the
incremental benefit or harm of context/review/proposals. Measure avoided losses,
missed winners, independent opportunities, execution latency and all incurred
costs; additional layers do not automatically compensate for a weak strategy.
Risk limits are safety constraints, not a separate source of predicted alpha.

## Capability boundaries and required remaining work

| component/path | current boundary | work needed for the target |
| --- | --- | --- |
| Adaptive strategy | existing `adaptive_pullback_range_v1` generator is a provisional challenger during reopened family selection; exact finite policy, isolated RESEARCH only; not economically qualified or campaign-frozen | finish bounded family selection and observed-fill development evidence before one own eligible identity/evaluator freeze; no parameter grid or system integration now |
| Strategy evaluation | new opt-in adapter emits source-bound candidate/evaluation/regime evidence with actual clocks; legacy fingerprints and runtime allow-lists unchanged | durable publisher/enrollment for only the selected new identity; unsupported generators do not acquire adaptive eligibility |
| Market and news context | immutable source receipts and exact declared bar tail; compact messages do not prove full warmup/raw-news availability | production history resolver, durable point-in-time source archive and source-specific qualification |
| Candidate review | runtime consumes source-bound context; required missing/late inputs defer before a provider call | exact new-contract/provider qualification; old context-free corpus is not qualifying evidence |
| Macro and regime/capital | selected finite deterministic detector and four-regime research capability mapping; opt-in account-bound allocation; legacy unchanged; external macro/onchain unavailable | durable detector publisher, capital-basis recovery, accepted policy/source set and independent input qualification |
| Ordinary PAPER execution | bounded technical-canary admission | separately reviewed adaptive admission after strategy/venue qualification; never remove canary guards globally |
| PAPER Compose | technical DEV-canary topology, not complete analytics | one accepted full analytical/runtime source set and topology |
| Matched research economics | observation journal, immutable native-window transport and separate offline four-path caller-attested accounting; no accepted full-system economics | native clock/cadence economics bridge, qualified source/provider/mapper inputs, actual execution, natural closes and own sealed evaluation |
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

- A bounded strategy-family selection, then one selected adaptive hypothesis,
  one executable policy/evaluator and one reproducible source set. Preserve
  failed/no-fill/no-action observations; do not mistake the previous engineering
  selection for an economically qualified champion.
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
- Offline complete-system accounting mechanics, not measured LLM profitability: [four-path receipt](FULL-SYSTEM-EVALUATION-2026-10-06.md).
- Native-window transport and its still-unqualified economics bridge: [import receipt](NATIVE-OBSERVATION-IMPORT-2026-10-06.md).
- Selected new strategy, checks and qualification boundary: [adaptive strategy receipt](ADAPTIVE-STRATEGY-2026-10-06.md).
- Reopened strategy-only family selection and read-only reference audit: [selection receipt](STRATEGY-SELECTION-2026-10-06.md).

Implementation changes in a new engineering source set do not enroll a
candidate, adopt a budget, qualify a model, disclose blind PnL, change the frozen
plan/evaluator or enable PAPER/LIVE. All current readiness flags remain false
and `STRATEGY_POLICY=REJECT_ALL`.
