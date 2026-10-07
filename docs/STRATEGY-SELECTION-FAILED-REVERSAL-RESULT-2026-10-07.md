# Fixed failed-breakout reversal / unchanged breakout control: actual diagnostic

Run completed October 7, 2026; evidence publication October 8. This is one new
candidate hypothesis tested once, **not a selected strategy or complete-system result**.
The [pre-run protocol](STRATEGY-SELECTION-FAILED-REVERSAL-PROTOCOL-2026-10-07.md),
parameters, windows, risk/cost assumptions and interpretation were sealed before counts
or returns. There was no post-result tuning, favorable-window selection or automatic retry.

## Execution and preserved evidence

- Signed source seal: `f6ddf7ba7366bb80a0711e955d2ce8eb052a5081`; all source gates were
  green before launch: [adaptive development](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37685190996),
  [meta validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37685190861),
  [CodeQL](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37685190354).
- Exactly one create-only cache-only worker, owned PID 56000, below-normal priority.
  Outer observation: 20:55:19.5827168--20:58:47.3964826 UTC, exit 0, 207,808 ms against
  a hard 600,000 ms ceiling. The pipeline measured 206.852557 s. No live child remained.
- Original output: `D:/Kairos/runtime/reversal-search-20261007-a`. All 17 pipeline
  files plus original stdout/stderr were copied byte-for-byte into
  [the evidence directory](../development/adaptive_replay/evidence/reversal-search-2026-10-07/checksums.json).
  `checksums.json` additionally records the external owned-process observation;
  that observation is not an original CLI receipt, source authentication or venue proof.
  Cross-platform Git attributes preserve the original JSON/log/gzip bytes.
- Canonical protocol SHA256: `f138c57b0eaabb9661696ab4d3132dfb3fb53475540f5a095e003d3316999c8e`.
  Canonical complete JSONL SHA256: `68d3e31d57f7842114a032ad18593f87e33b383a1502fbb60191cf98a7cba92a`.
  Gzip SHA256: `18365a8ed4f3cd59b8f3e17b600c510454b73b4503cca73caaf417f960f415d5`.
- Source/dependency/native identity receipts were equal before/after; all input
  archive checksums and normalized rows were rechecked unchanged. Exact coverage:
  10,080 minute bars /21 funding rows per symbol in each 3-day window, 12,960/27 in
  each 5-day window, including warmup and exit tail; no gaps or new downloads.
- All six windows, five symbols and both arms completed: 31,680 five-minute
  symbol/cut slots per arm, **63,360 total**. The 22 scored UTC days are not continuous
  monthly/annual trading or 22 new blind days. All periods were already seen in development.

## Complete candidate funnel

The new arm uses the first one/two-bar return after a failed channel breakout,
pre-excursion frozen channel/ATR, the complete event extreme for its stop, the
opposite known channel edge for target, first-event consumption, fresh-channel
reset and unchanged native crash/cooldown defense. The native `trend_breakout_v1`
control retains its registered parameters and original intents/exits.

Reference-price feasibility and first-arrival feasibility are **different inspections**,
not a monotone funnel: minute price changes may improve or worsen the unchanged geometry.
Only the first strict minute OPEN after assumed 100 ms completion is inspected;
there is no later retry or invented target/stop. Neither feasibility means an observed fill.

| Arm | Raw candidates | Reference feasible, 20/33 bps | First arrival feasible, 20/33 bps | Conditional entries/natural closes, 20/33 bps |
| --- | ---: | ---: | ---: | ---: |
| Failed-breakout reversal | 799 | 593 / 429 | 504 / 388 | 415 / 318 |
| Unchanged trend breakout | 1,057 | 264 / 52 | 309 / 172 | 221 / 128 |

Portfolio admission rejects 89/70 of the new arm's feasible arrivals and 88/44 of
the control's; every refusal reconciles and stays in the original receipts.
The control's 583 raw candidates across the four old 3-day windows match the earlier
unchanged native comparison; A/D add 474, without splicing old results.

Natural **aggregate five-symbol** entries over the 22 UTC-day denominator are 4..33
per day for reversal/base and 1..31 for reversal/stress: neither had a zero-entry
day on this particular roster. The unchanged control has 0..34 with two zero days
at base, 0..29 with nine zero days at stress. These are unfiltered technical
reference counts, not the eventual News/Macro/LLM system's frequency or a 2--3/day target.
Zero trading remains allowed; no quota or manufactured trade was introduced.

The reversal's 415 base exits are 260 SL / 136 TIMEOUT / 19 TP; its 318 stress exits are
198 SL / 105 TIMEOUT / 15 TP. Opposite-edge targets were rarely reached within this
fixed 120-minute rule. That observation is retained, not used to move barriers or
extend the holding period after seeing outcomes.

## All window results under both unchanged cost assumptions

Every arm/window/cost has its own initially $10,000 shared five-symbol account.
The figures below are **conditional trading-only net percent**, with modeled
fees/execution costs and the declared archive funding/candle-open entitlement
proxy. News/model/live-feed costs and complete-system net are unavailable.
No cross-window compounding, annualization, monthly-income claim or future alpha follows.

| UTC window, exclusive end | Reversal 20 bps | Reversal 33 bps | Control 20 bps | Control 33 bps |
| --- | ---: | ---: | ---: | ---: |
| 2021-11-07--10 | -0.33969% | +0.03966% | -0.13695% | 0, no entries |
| 2022-02-05--08 | -1.93018% | -1.23781% | -0.88967% | 0, no entries |
| 2022-05-09--12 | +5.18884% | +1.58386% | +0.31169% | -0.31217% |
| 2022-06-13--16 | -4.90484% | -5.87253% | -2.30007% | -2.13028% |
| 2021-05-17--22 | -7.10630% | -8.49467% | +4.48854% | +1.87455% |
| 2024-01-08--13 | -5.39430% | -3.93831% | -2.18295% | -0.53066% |

Reversal PF (base/stress) by the same row order:
0.87405/1.03147; 0.51797/0.35720; 1.56130/1.21152; 0.61803/0.52312;
0.60536/0.50127; 0.46788/0.41792. The complete precision, fees, funding, refusal
reasons and trades of all 24 accounts remain in original ledgers.

## Drawdown and unchanged risk limits

Sizing at admission respects 0.25% risk/trade, 1% aggregate reserved open risk,
25% symbol notional and 1x gross, using post-entry equity and original barriers.
The per-entry risk/notional checks pass. **This is not proof of an always-respected
1% mark-risk ceiling**: subsequent equity losses change the denominator.

| Observed measure, maximum across windows | Reversal 20 bps | Reversal 33 bps | Control 20 bps | Control 33 bps |
| --- | ---: | ---: | ---: | ---: |
| Closed-minute MTM drawdown | 8.34865% | 9.27162% | 3.58895% | 3.23513% |
| Adverse-envelope drawdown bound | 8.48533% | 9.27162% | 3.60451% | 3.40999% |
| Reserved open risk / current marked equity | 1.0056054% | 1.0052846% | 1.0028447% | 1.0025277% |
| Windows with mark-risk overrun | 4/6 | 4/6 | 2/6 | 1/6 |

The original reports retain 11 account mark-risk overrun flags, no gross 1x mark
overrun, no forced settlement and no unresolved terminal position. These are
qualification-relevant failures, not rounding artifacts to hide or permission
to raise the risk ceiling. Limits and the common engine were not altered for a better result.
Conditional full-fill OHLC cannot prove BBO, liquidity, partial fills, intrabar
ordering, protective-order timing or venue reconciliation. Archive funding is
not an exchange settlement receipt.

## Interpretation and next boundary

This version fixes the previous empty-candidate problem as a **different research
hypothesis**, not a rewrite of the [old frozen retest](STRATEGY-SELECTION-FROZEN-RETEST-RESULT-2026-10-07.md).
It now provides observable, source-bound structural candidates for a later matched
review experiment. It is **not selected as the main strategy or integrated**:
the standalone crash-window losses, uneven stress results, drawdowns and mark-risk
overruns do not establish the required robust system. A profitable May 2022 cell
does not cancel the bad windows; the positive control May 2021 cell does not crown
that control either.

Conversely, a negative standalone result alone does not measure whether a
causal News/Macro/LLM review adds value. No review was executed, no profitable
subset was selected after exits and no assumption that an LLM rescues these
losses is accepted. A later matched test must preserve all candidates and
quiet/refusal opportunities, causal source cutoffs, shared clocks/costs,
unchanged risk, strategy-without-LLM control and zero-trade days.

Required historical NEWS/MACRO are still unavailable, not synthesized from
future event narratives. The eventual model test requires accepted causal
source/budget evidence **and fresh owner confirmation**. This run made 0 provider
calls and spent $0 API budget; unavailable model/feed services are not claimed free.
No production integration, new blind enrollment or trading authority follows;
the system's own 365 days / 500 naturally closed simulated trades and crash gates
receive no credit. Trial 15, V2/V4/V5, compact plans, earlier sources/receipts and
ledgers remain unchanged.

Independent read-only audit and five evidence regression tests verify hashes,
canonical 63,360-slot order, unique 1,856 candidate identities, raw/reference/arrival
counters, daily denominators/refusals and all 24 ledger calculations without a new
market run. Final installed, non-editable Windows Python 3.11/3.14 suites each
pass 830 tests with two symlink-privilege skips (125.96 s / 110.86 s).
Ruff lint / 102-file format checks, unchanged dependency lock, sdist/wheel build
and meta static/local-link checks pass. This is scoped software/receipt validation,
not qualification.
`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`.
