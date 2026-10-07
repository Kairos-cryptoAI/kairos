# Right-tail compatibility protocol, 2026-10-07

This is the finite next experiment selected in the
[October 6 shortlist](STRATEGY-SELECTION-2026-10-06.md), before integration.
Its protocol is committed before viewing these pair-replay returns. It is not
a new strategy, Trial 15 execution, forward campaign or trading qualification.

## Fixed question and source set

Compare unchanged `right_tail_trend_v1` with its exact
`regime_aligned_right_tail_v1` composition using the same common account
evaluator. Does the slow alignment change cost/risk compatibility on the four
already seen slices? This does not ask which strategy is globally most profitable.

[right-tail-plan.json](../development/adaptive_replay/right-tail-plan.json)
binds native defaults, both registry trees and the unchanged development source
set/costs/risk/account in [plan.json](../development/adaptive_replay/plan.json).
The aligned registry tree alone omits its imported base sleeve; the separate
base tree is explicitly sealed as its transitive dependency. No frozen source,
plan, evaluator, ledger, report or forward identity changes.

## Exact finite experiment

- BTC/ETH/SOL/BNB/XRP; same twelve entry days: November 7–9, 2021;
  February 5–7, May 9–11 and June 13–15, 2022, all UTC.
- Two arms and two cost scenarios: exactly 16 economic cells. Each starts with
  an independent $10,000 account shared across its five symbols. Do not pool
  disconnected windows into one investment return.
- Exactly 35 days of same-origin causal prefix; 210 completed 4h bars before
  each slice provide SMA200 history. No exit-tail bars in strategy features.
  Same-origin truncated generation at each actual 01:00 scoring cut and
  +24h/+48h/end must preserve full candidates, including within-day causality.
- Native daily decision is the 00:00–01:00 UTC bar close, eligibility 01:00.
  Completion is assumed +100ms, so strict first observed minute open is 01:01.
  Unchanged expiry is 01:59:59.999. No intraminute entry proxy or TTL extension.
- Unchanged 2 hourly ATR stop, 4R target, 72h timeout; exactly 72h exit tail.
  Every aligned candidate must preserve its exact base geometry and lineage;
  independent minute-endpoint SMA arithmetic must reproduce the retained set.
- Base/stress planning allowances 20/33bps, unchanged archived funding and
  common stop10..300bps/net-RR≥1.25/cost≤0.5stop. Admission retains ≤0.25%
  stop risk, ≤1% aggregate risk, ≤25% symbol notional and ≤1x gross exposure.
  Mark-time/gap breaches are disclosed, not reported as a continuous cap pass.
- Complete checksum/CRC/minute-row/funding coverage from existing local cache
  only. Missing data or source/causality mismatch fails closed. One worker,
  20-minute cooperative deadline; no downloads, paid calls, parameter grid,
  services, frozen economic tapes or quota trades.

The common evaluator still uses deterministic conditional full fills, modeled
spread/slippage, stop-first ambiguous OHLC and archived funding clock/price
proxies. It does not qualify liquidity, protection latency or EVEDEX execution.
Unavailable model/live-feed costs remain null, not free. Generator silence has
no native reason receipt; daily tapes explicitly preserve that unknown.

## Stop and interpretation rule

Publish every cell, rejection, daily frequency, natural exit, unresolved
position and risk breach. Complete data plus a completed runner proves only
this diagnostic's integrity/accounting. Up to 60 base candidate opportunities
are too few for superiority or representative annual/crash alpha; removing
signals also changes account capacity and sizing, so aligned trades need not
be a subset of base trades.

There is no winner promotion, parameter rescue, extra-window selection or
second economic attempt in this pass. Sparse results are `INSUFFICIENT`, not a
champion. Broader selection would require its own predefined sample and
stopping gates, with prior exposure disclosed. Neither an existing historical
pass nor this diagnostic transfers Trial 15 days or LIVE authority.

The user has paused layer integration. News, models, Macro, Router, runtime and
venue work stay outside this experiment. All readiness remains false and
`STRATEGY_POLICY=REJECT_ALL`.
