# Fixed failed-breakout reversal diagnostic — 2026-10-07

## Status and scope before any real-data run

One new hypothesis, `failed_breakout_reversal_v1`, is compared with the **unchanged** native
`trend_breakout_v1` configuration. This is not a revision of the rejected
`frozen_breakout_retest_v1`, a parameter sweep, a production registration, an LLM test,
a trading-stack integration, or a blind campaign. Old plans, evaluators, receipts and ledgers
remain immutable. All readiness flags remain false and `STRATEGY_POLICY=REJECT_ALL`.

The strategy is a source of candidates for the eventual News/Macro/Router/LLM/Risk system,
not a promise of very high standalone returns. Standalone negative reference PnL is recorded;
it is neither automatically rescued by an imagined LLM filter nor sufficient on its own to
measure the value of a real matched review. A geometry-impossible candidate cannot become
executable merely because a model is confident.

## Single frozen economic hypothesis

1. Use contiguous completed 1m candles, an explicit origin 54h before the score window,
   complete 5m decision candles, prior complete 15m context and the pinned native 1h crash guard.
2. **Before the excursion 5m OPEN**, freeze the high/low channel of the prior 20 complete 15m
   candles. ATR15 is the mean of 14 true ranges, including each preceding close. A 15m candle
   which contains the excursion is excluded even if it is complete by the decision close.
3. The preceding 5m close must be strictly inside the channel. A strictly lower-only wick
   excursion proposes LONG; a strictly upper-only wick excursion proposes SHORT.
4. The first strictly inside completed close is required on the excursion bar or exactly the
   next 5m bar, never later. Both strict boundary excursions in one bar are a conflict.
   Touching the opposite target on **any event bar**, including equality, consumes without entry;
   minute OHLC cannot establish a favorable intrabar order.
5. Stop is the low/high of **all event bars**, including confirmation, minus/plus 0.25 frozen
   ATR15. Target is the already-known opposite frozen channel boundary. Do not invent 2R,
   extend a target, tighten a stop for admission, or filter structural candidates on observed PnL.
6. The first return, expiry, conflict or native-defense cancellation consumes the event before
   costs, portfolio position, model VETO or fill. New identity TTL is 5m; holding is 120m from fill.
   These constants do not alter any old/native intent.
7. `WAIT_RESET` ends only on a **distinct later** close inside that bar's current pre-bar rolling
   channel. A reset candle cannot simultaneously arm. The obsolete event channel does not impose
   an indefinite reset requirement. Event barriers themselves remain frozen.
8. Native CRASH and post-shock cooldown abstain/cancel; there is no crash-short exception.
   Recheck this guard and the original geometry at first arrival.

Raw candidates and their refusals are separate. No trade-count quota exists; zero-trade days
are retained. Rule strength is not a calibrated probability and never raises risk limits.

## Fixed roster and comparison before looking at counts or returns

All periods were already used in development. Their selection is **not unseen validation**;
calendar names do not prove causal market-regime labels or representative annual performance.

| Window | UTC start | UTC exclusive end | Calendar days |
| --- | --- | --- | ---: |
| late_2021 | 2021-11-07 | 2021-11-10 | 3 |
| early_2022 | 2022-02-05 | 2022-02-08 | 3 |
| may_2022 | 2022-05-09 | 2022-05-12 | 3 |
| june_2022 | 2022-06-13 | 2022-06-16 | 3 |
| episode_a | 2021-05-17 | 2021-05-22 | 5 |
| episode_d | 2024-01-08 | 2024-01-13 | 5 |

Use BTC/ETH/SOL/BNB/XRP in every window. Keep every 5m cut, not only the former sparse A/D cells:
31,680 symbol/cut slots **per arm**, 63,360 total. Re-generate native control unchanged and verify
both arms' complete output against the same-origin exact +24h prefix. Never splice former failed
pilot runs or silently omit an asset/window/cost. No new downloads.

The first admissible quote is the strict minute OPEN after an **assumed**, not measured, 100ms
completion. No quote-minute high/low/close enters first-arrival inspection. Any completed
intermediate 1m stop/target touch cancels both arms. Challenger also requires its frozen channel,
event-source binding and native arrival defense. The control keeps its own registered signal/exit
rules; the new reversal-specific channel/ATR/crash contract is not transplanted to its generator.

The unchanged common geometry is base20/stress33 bps round-trip assumptions, netRR≥1.25,
stop10..300bps and cost≤0.5 gross stop. Do not transplant adaptive's 0.5..2ATR distance filter to
this independent producer. Geometry uses a $10,000 reference account, not actual allocation.
Portfolio admission recalculates sizing from current equity and original barriers: maximum
0.25% risk/trade, 1% aggregate reserved open risk, 25% symbol notional, 1x gross. Risk never nets
between directions. Separate five-symbol accounts per arm/window/cost; no cross-window compounding
or merged stack. Fixed universe ordering handles simultaneous candidates.

Use the existing conditional OHLC engine, strict-minute only, complete 3h exit tail, SL-first
ambiguity, adverse stop gaps, original timeouts and causal native trailing control exits.
Retain actual signed archive funding at calc_time as the declared entitlement/candle-open proxy,
fees, mark drawdowns, risk/gross mark overruns, loss above reservation and unresolved positions.
No synthetic forced settlement. No partial-fill, liquidity, protective-latency or venue proof.
Model/news/feed costs and full-system net economics remain unavailable, not zero-priced services.

One worker, one create-only attempt, **600 seconds hard wall cap**. Preserve partial output on
failure; no automatic retry, expanded cap or revised parameters after seeing outcomes. Seal code
and protocol in a signed main commit, verify gates, then run once. Bind original data checksums,
normalized row hashes, native identities and installed sources before/after. Publish all counts
and results together, not a favorable subset.

## Interpretation fixed in advance

- Zero geometry-feasible candidates means this version cannot test review value on this roster.
- Nonzero candidates establish only testable structural inputs, never positive alpha.
- Report price-only reference net and drawdown for every window under both costs, including losses.
  Do not rank a winner using a few chosen gains or require a day/weekly/monthly income target.
- No automatic tuning, selection, stack wiring, admission, paid model run or qualification follows.
  The user confirms the later historical model test separately; News/Macro provenance, budget and
  matched clocks remain mandatory. Old Trial15/V5 and own 365day/500natural-close gates receive no credit.

This separation is consistent with primary research on
[technical-rule data snooping](https://www.fmg.ac.uk/publications/discussion-papers/data-snooping-technical-trading-rule-performance-and-bootstrap)
and [backtest overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
Neither paper is evidence that this particular reversal earns money.

Machine policy: `adaptive_replay.reversal_search.fixed_search_protocol()`.
Create-only offline command: `python -m adaptive_replay.reversal_search --workspace-root D:/Kairos
--output-root D:/Kairos/runtime/reversal-search-20261007-a`. Run only after source seal and review.

Pre-run implementation verification: 65 focused artificial strategy/arrival/search fixtures;
825 passed / two Windows symlink-privilege skips on each installed, non-editable Python3.11/3.14
environment. Ruff lint/100-file formatting, locked dependency check, sdist/wheel build and meta
static/local-link gate pass. Independent source review repaired a pilot-only coverage assumption
and an excursion target-equality gap before sealing; mirrored regressions bind both. Native defense
parity on 191 artificial minute cuts /39 aligned5m cuts has no mismatch. This is software proof,
not real source, fill, profitability or campaign evidence. GitHub CI is checked on the signed seal
before the one real diagnostic; actual counts/returns are deliberately absent here.
