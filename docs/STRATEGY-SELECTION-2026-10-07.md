# Strategy-layer selection: completed finite comparison, 2026-10-07

## Decision

The [predeclared right-tail compatibility experiment](STRATEGY-SELECTION-PROTOCOL-2026-10-07.md)
is complete. **No qualified champion is selected.** The unchanged slow trend
family remains a useful research reference, not a ready replacement for the
variable-frequency adaptive layer and not an approved LIVE strategy.

The SMA200 alignment is not universally beneficial here. Three slices give
identical account results; in February it reduces both return and drawdown.
Only nine base / eight aligned natural closes per cost scenario across twelve
seen entry days cannot establish statistical superiority, representative crash
profitability or future alpha. This is a completed finite diagnostic with an
`INSUFFICIENT_FOR_FINAL_SELECTION` outcome, not unfinished execution.

The user's requested strategy selection is therefore **not fully solved**:
there is no defensible final profitable identity to freeze yet. Do not replace
that gap with a more complicated untested combination or treat later news/LLM
layers as a guarantee that negative standalone economics will be rescued.

## Execution and integrity

- Preregistered signed main commit before viewing pair returns:
  `7bba7d29abac1813053bf3e05523016f227d919d`.
- One cache-only run, 105.03 seconds, two native arms × four slices × two
  costs. Same unchanged common evaluator, independent $10,000 arm/window
  accounts, 35-day causal prefix, 72h exit tail; no second economic attempt.
- 1,180,800 parsed minute rows across four overlapping loader spans, not that
  many distinct market observations. Every five-symbol span has 59,040 rows
  per symbol, zero gaps and 123 unrounded native funding events per symbol.
  All required official ZIP/checksum/CRC and funding coverage checks passed.
- Both config/source trees and the aligned sleeve's imported base dependency
  are explicitly bound. Same-origin native prefixes agree at all three actual
  01:00 decision cuts, +24h/+48h/end; independent minute-endpoint SMA arithmetic
  reproduces the exact retained base IDs and regime metadata.
- All 16 accounts reconcile. Every entry naturally closes inside the tail;
  no unresolved positions, forced settlements, extra tail candidates, paid
  calls, frozen economic reads or campaign-credit days.
- Independent PowerShell arithmetic recalculates each signed price×quantity
  gross result, both fees, carry, net, return, PF and holding clocks. All
  sixteen cells agree; this is scoped arithmetic, not venue/alpha validation.
  A separate Luna review also agrees with the retained ledgers.
- All 245 development tests pass against installed wheels on Python 3.11 and
  3.14; lint, formatting, meta static checks and local document links pass.
  An independent Sol methodology review finds no material result overclaim.

The replay binds actual installed byte hashes and dependency commits before
and after. It does not reuse earlier economic results. Historical receipts
and frozen plans/evaluators/ledgers are not edited.

## Every result cell

Each row uses three entry days **plus up to three further days for natural
exits**, reset initial capital and costs from the fixed common protocol. These
are conditional trading-net returns excluding unavailable model/live-feed
expenses, not three-day investable returns or monthly projections. Base/stress
planning allowances are 20/33bps; archived funding uses the documented clock
and candle-price proxies. Strict entry is the observed 01:01 minute open with
modeled adverse costs, not proof of a fill on EVEDEX.

| UTC entry slice | Arm | Candidates | Closed, base / stress | Net %, base | Net %, stress | MTM DD %, base / stress |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2021-11-07…09 | Base | 6 | 4 / 4 | +0.00467 | −0.06697 | 1.57209 / 1.48133 |
| 2021-11-07…09 | Aligned | 6 | 4 / 4 | +0.00467 | −0.06697 | 1.57209 / 1.48133 |
| 2022-02-05…07 | Base | 5 | 3 / 3 | +1.83400 | +1.69030 | 0.96290 / 0.90628 |
| 2022-02-05…07 | Aligned | 2 | 2 / 2 | +0.91344 | +0.84322 | 0.45820 / 0.43480 |
| 2022-05-09…11 | Base | 6 | 1 / 1 | +0.88986 | +0.82777 | 0.27229 / 0.25692 |
| 2022-05-09…11 | Aligned | 6 | 1 / 1 | +0.88986 | +0.82777 | 0.27229 / 0.25692 |
| 2022-06-13…15 | Base | 8 | 1 / 1 | +0.91951 | +0.86369 | 0.40864 / 0.38837 |
| 2022-06-13…15 | Aligned | 8 | 1 / 1 | +0.91951 | +0.86369 | 0.40864 / 0.38837 |

November PF is 1.00605 base / 0.91224 stress for both arms. Other slices have
no losing closes, so PF is null with `NO_LOSSES`, not a reliable infinite-PF
champion. May and June each have just one winning close per arm/cost; they
cannot demonstrate broad crash resilience. No cross-window compound return,
annualization or aggregate winner score is calculated.

## Frequency, rejection and risk findings

Base emits 25 scoring candidates and closes nine trades; aligned emits 22 and
closes eight **per cost scenario**, not eighteen/sixteen independent trades.
Seven of twelve entry days are quiet for either arm. Observed daily entries:

- November: `[0, 3, 1]` for both arms.
- February: base `[3, 0, 0]`, aligned `[2, 0, 0]`.
- May and June: `[1, 0, 0]` for both arms.

Variable frequency and skipped days occur without a quota. Native once-daily
evaluation nevertheless cannot react throughout the day, and 72h symbol
positions block repeated entries. It does not by itself fulfill the intended
active, multi-layer trader concept.

Per arm/cost, November rejects two candidates because a symbol position is
already open. February base rejects one too-wide stop and one aggregate-risk
attempt; aligned has no admission rejection. May rejects five too-wide stops,
June seven. **Do not shorten stops or raise the fixed 300bps ceiling to make
these rejected signals trade.** The slow family is often incompatible with
the common stop-width policy during these selected volatile dates.

All sixteen reports record no aggregate mark-risk or gross-leverage overrun;
maximum observed aggregate mark-risk is approximately 0.99857%. This does not
prove continuous per-trade, symbol or portfolio limits. November retains two
actual modeled losses beyond their initial stop-risk reservation in each
arm/cost; they are the same repeated paths, not eight independent events.
In the base-cost ledger XRP loses $26.77574 against $24.99252 reserved and ETH
$26.08908 against $24.99443 reserved, with `gap=false`. Thus overshoot is not
attributed solely to an opening gap; funding and modeled lifecycle economics
are retained. A stop-risk reservation is not a guaranteed maximum realized loss.

## Strategy-selection conclusion and remaining work

The [October 6 family audit](STRATEGY-SELECTION-2026-10-06.md) and this completed
comparison narrow the problem:

| Role | Decision now | Missing evidence |
| --- | --- | --- |
| Slow trend / right-tail | Keep unchanged base and aligned as paired references; no superior filter established here | Broader predefined continuous bull/range/bear/crash comparison under the same risk/cost policy |
| Intraday Donchian | Keep as an active negative control, not a winner | Robust incremental value after costs; earlier seen diagnostics were unfavorable |
| Event-driven pullback / reclaim / range | Keep one existing adaptive challenger, no new parameter grid | Observed prices within native lifetime and wider predeclared coverage; current minute-only strict data cannot confirm its twelve entries |
| Default VWAP range / fixed union | Do not add to the selected stack | Current default reference geometry fails the common net-RR hurdle; naive union added no benefit in the earlier comparison |
| News / LLM / Macro | Preserve future independent value tests; integration stays paused | Causal availability, measured latency/cost and matched full-system incremental value, not assumed profitable contribution |

This pass stops at its declared boundary. The next meaningful selection work
is a separately fixed broader calendar experiment and an observable entry
dataset for the event-driven challenger, not more indicators or repeated
selection on these same twelve days. Those are new research prerequisites;
they have **not** been quietly run or declared passed here. No final new
campaign/evaluator is frozen, and no existing Trial 15 result/days transfer.

The original [time-series momentum research](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)
is a family-level prior from traditional futures, not proof for these crypto
entry rules. The [backtest-overfitting study](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)
motivates keeping reused data and further trials explicit rather than choosing
a favorable small slice after seeing its outcome.

## Exact evidence and verification boundary

[Result](../development/adaptive_replay/evidence/right-tail-2026-10-07/result.json),
[independent audit](../development/adaptive_replay/evidence/right-tail-2026-10-07/independent-ledger-audit.json)
and [calculator](../development/adaptive_replay/evidence/right-tail-2026-10-07/Test-PairLedgers.ps1)
retain all 16 economic cells, raw daily tapes, input/source receipts and full
trade/event journals as byte-preserved files. Original runtime evidence stays
under `D:\Kairos\runtime\right-tail-comparison-20261007\bounded-20261007-a`.

Result SHA-256: `0caaec779e2e4172484ebb9ab9c4830b946da29d62f31358291185f2113eb1d3`.
Audit SHA-256: `8ef189863b30b305954cae7f87f363b4b32fd249005bdc272aa03d6320b04e08`.
Canonical pair-plan SHA-256: `dafd2c69b431878af1f5c509d2cf8ffd1fa25a976eb6ee992d7e91392e45aeb6`.

`validate-data` assessment: **share with caveats within this finite diagnostic**;
the final-strategy superiority claim remains unsupported. Local installed-wheel
checks and exact-revision CI verify engineering, not economic qualification.
No provider/source authenticity, real liquidity, partial-fill/protection
latency, continuous runtime or future alpha is qualified by these receipts.
All four readiness flags stay false and `STRATEGY_POLICY=REJECT_ALL`.
