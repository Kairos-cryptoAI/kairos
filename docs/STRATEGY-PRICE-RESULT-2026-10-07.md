# Completed PRICE_ONLY calendar reference — 2026-10-07

## Decision

The separately [preregistered price-field experiment](STRATEGY-PRICE-SOURCE-PROTOCOL-2026-10-07.md)
completed all four UTC entry years 2022--2025, five symbols, two unchanged native
arms and both fixed cost scenarios. The original selection function returns
**`NO_ECONOMIC_REFERENCE_WINNER`**, with no nominee, qualified winner or LIVE
strategy. This is a finished reference comparison, not an unfinished replay.
Final adaptive/LLM strategy selection remains unproved and integration is paused.

Aligned has higher trading-net return in each primary stress year, but fails
the unchanged risk/Pareto requirements. In 2023 its drawdown is higher than
base, and both arms exceed the observed aggregate mark-risk ceiling in every
year. Better returns alone do not confer selection or safety qualification.
No threshold, parameter, cost, asset, year or evaluator is adjusted to rescue
this outcome. There is no second economic attempt.

## Exact execution and input boundary

- Signed source commit before the run:
  `28891bbfa4bc17436e248508c84ae47e6cb67a42`, valid GPG signature.
  Its exact [Windows/Linux Python matrix](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37569245436),
  [meta validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37569245516)
  and [CodeQL workflow](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37569244739)
  were green; all fourteen clean main source revisions passed the manifest gate.
- One cache-only worker completed in **654.25 seconds**, within the unchanged
  cooperative 1,200-second bound. All sixteen economic cells are present.
  The original failed FULL_KLINE attempt remains immutable and was not resumed.
- The accepted inventory binds 255 bar ZIPs, 255 funding ZIPs and nineteen
  official daily ZIPs/sidecars. Price coverage is 11,181,600 source minutes;
  exactly 14,400 missing symbol-minutes were added, with zero replacements.
  Eight complete adjacent controls matched all twelve raw fields exactly.
- Every accepted raw ZIP and sidecar was checked before generation and after
  all four years. Harness, evaluator, projection, native strategy trees and
  eight transitive price-consumer modules match the sealed before/after hashes.
  Same-origin quarterly causal-prefix checks and independent SMA200 arithmetic
  passed. They do not establish unseen data or historical local availability.
- Uniform unavailable optional-field placeholders are accepted only for the
  two price consumers and their common evaluator. The original XRP optional
  volume defect remains quarantined, not repaired or FULL_KLINE-qualified.
  Daily/monthly archives and the REST sample are not independent price sources.
- Native defaults, stop/net-RR and common risk limits are unchanged. Every
  year/arm/scenario starts its own $10,000 account, with a 35-day causal prefix
  and up to a 72-hour exit tail. No new candidates are generated in that tail.
  All admitted entries close naturally; forced settlements and terminal
  unresolved positions are zero. These closes give no frozen campaign credit.

## All economic cells

`Base` below means `right_tail_trend_v1`; `Aligned` means
`regime_aligned_right_tail_v1`. The primary scenario is the previously fixed
**stress** planning allowance, 33bps; the 20bps scenario is a sensitivity
control, not an alternative selected after returns. Allowances are admission
budgets, not a uniform realized cash debit. Fees and modeled adverse
spread/slippage/latency appear once in the evaluator; archived signed funding
uses the documented archive-clock and candle-price proxies. The 3bps carry
reserve is not a cap on actual modeled carry or realized loss.

| UTC entry year | Arm | Candidates | Closes, 20 / 33bps | Net %, 20 / 33bps | Closed-minute MTM DD %, 20 / 33bps | PF, stress |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2022 | Base | 570 | 331 / 326 | -2.15941 / -6.23924 | 8.63724 / 10.92318 | 0.88678 |
| 2022 | Aligned | 377 | 215 / 211 | +5.67594 / +2.15112 | 6.02507 / 6.05447 | 1.06122 |
| 2023 | Base | 488 | 371 / 362 | -0.79166 / -7.51369 | 11.59363 / 13.47028 | 0.86362 |
| 2023 | Aligned | 341 | 262 / 256 | +5.21912 / -1.06004 | 12.61980 / 13.94345 | 0.97235 |
| 2024 | Base | 538 | 368 / 365 | +11.13016 / +2.90375 | 7.82022 / 9.26688 | 1.05031 |
| 2024 | Aligned | 377 | 269 / 267 | +8.47168 / +3.05072 | 6.63499 / 6.70082 | 1.07156 |
| 2025 | Base | 559 | 365 / 358 | +16.11169 / +9.30869 | 8.20146 / 8.37593 | 1.16044 |
| 2025 | Aligned | 355 | 247 / 242 | +14.45004 / +10.23653 | 7.60215 / 7.59649 | 1.26277 |

These are conditional **strategy-only trading-net** results, excluding unknown
model/live-feed expenses. Model calls are zero; their unobserved cost and feed
cost remain null, not evidence of a free full system. No model/news/review arm
was run. `complete_all_in_net_economics` remains false.

The equal-year mean stress return is -0.38512% for base and +3.59458% for
aligned. It is an arithmetic mean of fresh accounts, **not CAGR or compounded
four-year performance**. Exit tails extend beyond entry-year boundaries;
prefix/tail input spans overlap and are not distinct independent observations.
The years are exposed development history, not an unseen OOS, future blind
campaign or proof of profitable crash handling by the complete system.

## Why the original nomination rule fails

Both arms exceed the prespecified activity floor: 1,411 base / 976 aligned
naturally closed stress trades in total, with at least twenty in every year.
This activity threshold is not statistical power, independence or 500 new
forward-campaign closes. The rule also requires a positive equal-year mean,
all-year weak return/drawdown Pareto dominance with at least one strict
improvement, and no observed aggregate-risk/gross overrun.

1. Base's mean stress return is negative and its returns are lower in all four
   years; it remains a mechanical control, not an economic winner.
2. Aligned's 2023 closed-minute MTM drawdown is **13.94345%**, versus
   **13.47028%** for base. Thus even ignoring risk overruns it fails all-year
   Pareto dominance. Its stress 2023 return and PF are also below zero/one;
   the latter is a factual weakness, not an added post-hoc nomination rule.
3. Both arms report aggregate mark-risk overruns in all four primary years
   (and all eight 20bps sensitivity cells). The largest observed primary ratio
   is **1.007876%**, against the fixed **1%** ceiling. Entry admission alone
   does not prove a continuous risk-to-current-equity guarantee: fees, carry
   and adverse equity marks can change that ratio after entry. No dynamic
   risk fix, threshold relaxation or re-sizing experiment was made here.

There are no reported gross mark-leverage overruns. Primary stress ledgers
retain fourteen base / eleven aligned losses larger than their initial stop
risk reservation, with zero flagged gap overshoots; funding and lifecycle
economics therefore matter even without an opening gap. A stop reservation
is not a guaranteed maximum realized loss. These are repeated model paths in
the comparison, not separately independent observations across cost scenarios.

The independent calculator checks account arithmetic and admission events;
it does not independently validate continuous risk, every MTM mark, real venue
fills, protection/partial-fill latency or the funding entitlement proxy.
No EVEDEX execution or liquidity qualification follows.

## Natural frequency and strategy role

Daily stress entry counts range from zero to three, without a trade quota.
Base has 191 / 169 / 171 / 173 zero-entry days in 2022 / 2023 / 2024 / 2025;
aligned has 246 / 210 / 216 / 221. This naturally variable activity is not a
target requiring more trades. One daily decision time and potentially 72-hour
symbol positions nevertheless do not supply the intended intraday trader.

Alignment is useful as a **conditional reference observation**, not selected
alpha: stress return improves in four years but drawdown does not improve in
every year, and 20bps 2024/2025 returns are lower than base. Shared-account
admission and blocked positions change the realized opportunity set; this
is not isolated causal attribution of every signal-filter benefit.

Keep the exact base/aligned pair as research references, without production
enrollment. The unchanged event-driven adaptive challenger still needs prices
observed inside its native lifetime; minute-open data cannot prove its strict
intraminute entries. Resolving that input/clock boundary is the next strategy
selection prerequisite, not adding indicators, tuning this exposed pair or
assuming later LLM layers will rescue weak standalone economics. No new blind
identity/evaluator is frozen, and existing Trial 15/V4/V5 results stay separate.

## Published evidence and engineering verification

The [publication index](../development/adaptive_replay/evidence/price-calendar-2026-10-07/checksums.json)
binds **54 original artifacts**, losslessly gzip-compressed: all run source/input
receipts, native causal tapes, sixteen report/ledger pairs, the sealed plan,
launch proof and independent arithmetic receipt/calculator. Both original and
compressed SHA-256/byte lengths are checked; no raw bar/funding cache is copied
into Git. Total original bytes: 20,465,810; compressed bytes: 2,575,922.

- Result original SHA-256:
  `5d007bba857c91a6321030da812367403f873062872691e9784b9eaf532ee403`.
- Independent audit original SHA-256:
  `92550e7e6683d73bc395058b5a64a252eea28572396cc44399c01d4c13fa8464`.
- Input-only acceptance original SHA-256:
  `130935ccfa310d656b22135c0e18ead69f20d00250d39066eabbb5ff283e961e`.
- Fixed source plan file SHA-256:
  `fe758bf6df5a9483a9795ca86390b42c04afc250f2cd8cc58962136b57968e04`.

Original runtime evidence is retained under
`D:\Kairos\runtime\right-tail-price-calendar-20261007\bounded-20261007-a`.
The independent PowerShell calculator reports `PASSED_SCOPED_ARITHMETIC` for
all sixteen cells; this is not a second native replay or venue/alpha proof.
Four publication tests bind the roster/bytes, source identity, all accounts,
unchanged no-winner decision and the independent audit. All **330** development
tests pass against installed non-editable wheels on Python 3.11 (53.32 seconds)
and Python 3.14 (50.20 seconds). Publication CI checks stored evidence, not
another historical economic replay. Lint/format checks and meta static/local
Markdown-link validation pass. An independent document/ledger review confirms
all sixteen cells and the stated selection boundaries. Engineering checks do
not qualify alpha.

`validate-data` assessment: **share the completed comparison with these
caveats**. Source-quality work supports this exact price-only scope, not
arbitrary volume consumers. Trial 15/V4/V5/frozen evaluator/ledgers are unchanged;
no paid calls, provider integration, primary DB/consumer changes or trading
occurred. All four readiness flags remain false and `STRATEGY_POLICY=REJECT_ALL`.
