# Native strategy comparison receipt — 2026-10-06

## Outcome

The comparison is complete. **There is no qualified winner.** Default breakout
emits more candidates, but results are unstable and cost/timing-sensitive.
The fixed breakout+range union did not improve this diagnostic. Adaptive's
superiority is unproved: strict minute quotes cannot confirm its short-lived
entries, and its conditional proxy accounts lose money in both active slices.
A zero-trade account is not a profitable or proven safe strategy.

This does not reject whole strategy families, prove yearly/crash alpha, select
a LIVE strategy or justify adding more variants. All four readiness flags
remain false; policy remains `REJECT_ALL`.

## Protocol, sources and preserved attempts

The [preregistered protocol](STRATEGY-COMPARISON-PROTOCOL-2026-10-06.md) and
[fixed plan](../development/adaptive_replay/comparison-plan.json) compare exactly
four arms. Default `trend_breakout_v1` and `range_mean_reversion_v1` retain native
configuration, trailing, intent IDs and REJECTED registry status.
The union is a newly specified portfolio control, not a previously validated
standalone strategy. `adaptive_pullback_range_v1` is unchanged.

- Signed implementation/protocol main: `e3dec6a5a8d77618978be33615f8c1b6a3e17856`.
- Signed adaptive-hash adapter correction and executed source:
  `92aa48429d69a26ba5525b29580c6f1b8b5ddb9b`.
- Unchanged Strategy main: `cde8e9c00af0cc19848e800ee76472a800a5fd5d`.
- Unchanged adaptive code SHA-256:
  `836391ab708d4dc9bd4957c68f00724683569b7d5584debb1c368016d57ff0d5`.
- Unchanged adaptive configuration SHA-256:
  `51781e00bee3664f260ff826c821234073b7a40deb1b7239e39f517be885901b`.
- Canonical comparison-plan SHA-256:
  `efa9b1548d95bcef457767694c42444ffadac579e450e95bfac92722b95a617c`.
- Serialized sealed-plan **file-byte** SHA-256:
  `4c159313b122062b9763ecc203f71e877cbb14f27a6b4d990e6a740b6007e77e`.
- Result file-byte SHA-256:
  `895b7aee5d8741cd0869cf2fad5eaa9a311f85edabe5ff4a8b800c4c9435a56c`.

The first run stopped after 26.547 seconds at the May adaptive tape importer,
before that window's common economics. It incorrectly used the generic candle
hash instead of adaptive's native `closed-bar.v1` schema. The correction changed
no dates, inputs, strategy/configuration, fees or limits. Its
[failure receipt](../development/adaptive_replay/evidence/comparison-2026-10-06/initial-failure.json)
and initial source/plan receipts are retained. The original directory
`D:/Kairos/runtime/baseline-comparison-20261006/bounded-20261006-a` was not
removed, overwritten or resumed.

The corrected run used the fresh directory
`D:/Kairos/runtime/baseline-comparison-20261006/bounded-20261006-b`.
It completed at `2026-10-06T05:48:19.131495+00:00` in **37.203 seconds**, within
the fixed 30-minute bound, using one worker and single-thread numerical libraries.

Only the original adaptive **decisions** were reused, after full result-byte,
input/source/configuration, complete-slot, native candidate-ID and native
closed-history hash verification. Every account's economics was recomputed
under `COMMON_COST_RISK_V1`; no earlier adaptive financial results were imported.
The [before receipt](../development/adaptive_replay/evidence/comparison-2026-10-06/before.json)
records all installed dependency/module/lock hashes; they match at completion.
No runtime dependency, release pin or lock was changed.

## Data, causal history and source availability

The same already seen four three-day slices, BTC/ETH/SOL/BNB/XRP,
54h causal warmup and 3h exit tail were used. Each arm/window resets to $10,000;
omitted dates are not compounded. These 12 days are neither untouched holdout
nor representative annual/crash qualification. Calendar names do not supply
regime signals.

All windows passed cache checksum/CRC, contiguous closed1m bars and native
funding coverage. There are 4,320 verified market slots per window: 17,280 unique
causal market slots, with separate 4,320-row arm tapes in every window.

Native generators expose candidates but not complete source outcomes. Their
source-ready/unavailable counts stay **null** and absent candidates are
`NO_CANDIDATE_REPORTED`, not fabricated valid silence or availability.
Adaptive's original fully ready INTENT/NO_INTENT outcomes were verified.

Native recursive Wilder/EMA history expands from the exact 54h pre-window prefix;
adaptive keeps its rolling54h window. Native intent-ID equality was checked at
three fixed hourly-close cuts per sleeve/symbol/window, 120 checks. The exit tail
never supplies decision history.

| Window (inclusive start, exclusive end) | Breakout candidates | Range candidates | Union candidates | Adaptive candidates |
| --- | ---: | ---: | ---: | ---: |
| 2021-11-07..2021-11-10 | 144 | 27 | 171 | 0 |
| 2022-02-05..2022-02-08 | 117 | 90 | 207 | 0 |
| 2022-05-09..2022-05-12 | 140 | 15 | 155 | 6 |
| 2022-06-13..2022-06-16 | 182 | 8 | 190 | 6 |
| Total candidates, not trades | 583 | 140 | 723 | 12 |

There were no observed same-slot union collisions/opposing-direction conflicts
in these slices. Arbitration behavior is synthetic-tested, not claimed as
historically exercised here.

## Strict minute-open accounts

Percentages are separate three-day accounts, not monthly/annual returns.
DD is closed-minute MTM, not tick drawdown; PF is realized net profit factor.
N/A means **no trades**, not infinite PF or success.

Strict uses the first eligible future observed minute-open entry price with
modeled costs. Native TTL stays 5m for breakout/range and 60s for adaptive.
At 100ms completion, adaptive's next observed minute quote is past expiry.
May/June each record 6 `NO_OBSERVED_MINUTE_QUOTE_WITHIN_LIFETIME` rejects in each
strict cost case. This data-resolution limitation does not prove inability
to trade LIVE or zero-risk alpha.

| Window | Arm | Base closes | Base net % | Base MTM DD % | Base PF | Stress closes | Stress net % | Stress MTM DD % | Stress PF |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| late_2021 | Breakout | 1 | -0.1370 | 0.1941 | 0.0000 | 0 | 0.0000 | 0.0000 | N/A |
| late_2021 | Range | 0 | 0.0000 | 0.0000 | N/A | 0 | 0.0000 | 0.0000 | N/A |
| late_2021 | Fixed union | 1 | -0.1370 | 0.1941 | 0.0000 | 0 | 0.0000 | 0.0000 | N/A |
| late_2021 | Adaptive | 0 | 0.0000 | 0.0000 | N/A | 0 | 0.0000 | 0.0000 | N/A |
| early_2022 | Breakout | 9 | -0.8897 | 1.3196 | 0.2474 | 0 | 0.0000 | 0.0000 | N/A |
| early_2022 | Range | 0 | 0.0000 | 0.0000 | N/A | 0 | 0.0000 | 0.0000 | N/A |
| early_2022 | Fixed union | 9 | -0.8897 | 1.3196 | 0.2474 | 0 | 0.0000 | 0.0000 | N/A |
| early_2022 | Adaptive | 0 | 0.0000 | 0.0000 | N/A | 0 | 0.0000 | 0.0000 | N/A |
| may_2022 | Breakout | 41 | 0.3117 | 3.3196 | 1.0638 | 19 | -0.3122 | 1.4577 | 0.8876 |
| may_2022 | Range | 1 | -0.1643 | 0.2291 | 0.0000 | 0 | 0.0000 | 0.0000 | N/A |
| may_2022 | Fixed union | 42 | 0.1469 | 3.4785 | 1.0291 | 19 | -0.3122 | 1.4577 | 0.8876 |
| may_2022 | Adaptive | 0 | 0.0000 | 0.0000 | N/A | 0 | 0.0000 | 0.0000 | N/A |
| june_2022 | Breakout | 60 | -2.3001 | 3.5889 | 0.6750 | 34 | -2.1303 | 3.2351 | 0.5384 |
| june_2022 | Range | 0 | 0.0000 | 0.0000 | N/A | 0 | 0.0000 | 0.0000 | N/A |
| june_2022 | Fixed union | 60 | -2.3001 | 3.5889 | 0.6750 | 34 | -2.1303 | 3.2351 | 0.5384 |
| june_2022 | Adaptive | 0 | 0.0000 | 0.0000 | N/A | 0 | 0.0000 | 0.0000 | N/A |

## Conditional intraminute-open proxy accounts

The quote at+99ms is **assumed, not observed**. Full fills, protective barriers,
timeout exits and liquidity remain conditional candle approximations, not
real venue execution or a guaranteed PnL lower bound. This mode is separate
and cannot repair the missing strict quote evidence.

| Window | Arm | Base closes | Base net % | Base MTM DD % | Base PF | Stress closes | Stress net % | Stress MTM DD % | Stress PF |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| late_2021 | Breakout | 0 | 0.0000 | 0.0000 | N/A | 0 | 0.0000 | 0.0000 | N/A |
| late_2021 | Range | 0 | 0.0000 | 0.0000 | N/A | 0 | 0.0000 | 0.0000 | N/A |
| late_2021 | Fixed union | 0 | 0.0000 | 0.0000 | N/A | 0 | 0.0000 | 0.0000 | N/A |
| late_2021 | Adaptive | 0 | 0.0000 | 0.0000 | N/A | 0 | 0.0000 | 0.0000 | N/A |
| early_2022 | Breakout | 0 | 0.0000 | 0.0000 | N/A | 0 | 0.0000 | 0.0000 | N/A |
| early_2022 | Range | 0 | 0.0000 | 0.0000 | N/A | 0 | 0.0000 | 0.0000 | N/A |
| early_2022 | Fixed union | 0 | 0.0000 | 0.0000 | N/A | 0 | 0.0000 | 0.0000 | N/A |
| early_2022 | Adaptive | 0 | 0.0000 | 0.0000 | N/A | 0 | 0.0000 | 0.0000 | N/A |
| may_2022 | Breakout | 22 | -0.7252 | 1.5836 | 0.7496 | 4 | -0.1443 | 0.5464 | 0.7023 |
| may_2022 | Range | 0 | 0.0000 | 0.0000 | N/A | 0 | 0.0000 | 0.0000 | N/A |
| may_2022 | Fixed union | 22 | -0.7252 | 1.5836 | 0.7496 | 4 | -0.1443 | 0.5464 | 0.7023 |
| may_2022 | Adaptive | 5 | -0.4731 | 0.9911 | 0.4375 | 4 | -0.8376 | 0.9755 | 0.0000 |
| june_2022 | Breakout | 27 | -2.3511 | 3.3929 | 0.3865 | 0 | 0.0000 | 0.0000 | N/A |
| june_2022 | Range | 0 | 0.0000 | 0.0000 | N/A | 0 | 0.0000 | 0.0000 | N/A |
| june_2022 | Fixed union | 27 | -2.3511 | 3.3929 | 0.3865 | 0 | 0.0000 | 0.0000 | N/A |
| june_2022 | Adaptive | 5 | -0.2634 | 0.9240 | 0.6308 | 3 | -0.3436 | 0.5824 | 0.2779 |

The [complete result](../development/adaptive_replay/evidence/comparison-2026-10-06/result.json)
retains all 64 arm/window/mode/cost reports: long/short net, fees, signed funding,
exit reasons, daily entries, admission rejections, adverse-envelope drawdown
bounds and terminal exposure. Base/stress independently admit and size trades;
stress need not be more negative because it may reject more trades.

Breakout strict/base daily entries across the four windows were
`1,0,0 / 4,1,4 / 20,11,10 / 34,9,17`; proxy/base:
`0,0,0 / 0,0,0 / 7,3,12 / 16,4,7`.
Adaptive proxy/base:
`0,0,0 / 0,0,0 / 4,0,1 / 3,2,0`.
Frequency is naturally variable, including zero; none is a daily quota.
More activity did not establish more reliable profitability.

## Union attribution and continuous-risk limitation

Union economics match breakout on 15 of 16 window/mode/cost cells.
May strict/base is +0.146898% for union versus +0.311686% for breakout:
41 breakout closes and one added XRP range SL close. The range trade loses
$16.608895; the total account difference is -$16.478763, **not exactly that
trade's PnL**, because shared equity changes later deterministic sizing.
No incremental benefit was observed for this exact union here; that is not
proof that combinations never work.

June strict/base breakout and union record maximum original risk reservation/
current-MTM-equity ratio **1.0028446646%**, with
`risk_ceiling_mark_overrun=true`. A conservative entry-ledger upper bound is
0.9991100448%, including simultaneous entries, consistent with admission <=1%.
Original dollar reservations remain fixed while equity changes; trailing
tightening does not release the original reservation. This metric is not
recomputed loss to the tightened stop.

Do not round this into continuous compliance. Admission-only control does
not guarantee continuously <=1% reservation/current-equity risk. The overrun
remains a qualification limitation; ceilings were not weakened, and no
post-hoc liquidation/rescaling was inserted to improve results.

All 64 accounts reconcile cash/fees/funding within 1e-7 USD, maximum observed
error 7.24e-12 USD. Terminal positions, forced settlements and reported realized
losses beyond reservation are zero. Gross mark leverage remains below 1x.
No both-barrier ambiguous minute was counted, but May breakout/union base
suppresses an entry-minute TP in each mode; candle data does not prove tick order.

Funding uses archive calc_time and candle-open prices, not proved venue
mark/cash-settlement receipts. Small signed funding charges/credits occur in
breakout/union accounts. EVEDEX capacity, partial fills, protective submission
latency and exact real-time timeout remain unqualified. Trading net excludes
unavailable model/news/live-feed costs; null cost does not mean a free service.
No historical LLM/news arm was run: point-in-time observations are absent and
pretrained event knowledge could contaminate such a comparison.

## Verification, artifacts and next boundary

Executed source passed all four Windows/Linux × Python 3.11/3.14
[fixture CI jobs](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37420140215),
[Meta validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37420140211)
and [CodeQL](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37420139668).
The expanded installed-wheel tests verify published bytes, all 64 account
reconciliations and the visible risk overrun without replaying market history.
Local Python 3.11: **120 passed** in 31.31 seconds; Ruff lint/format and Meta
static/local Markdown-link checks pass. Publication CI repeats this expanded
suite on Windows/Linux and Python 3.11/3.14, without history downloads.

**61** generated JSON files (1,513,435 bytes) were independently compared
byte-for-byte with runtime originals. This retains all 64 reports in result,
23 nonzero-trade ledgers, source/plan/input/prefix/tape evidence and the failed
attempt. The [checksum index](../development/adaptive_replay/evidence/comparison-2026-10-06/checksums.json)
binds all 61 files. Git disables newline conversion for this byte-bound evidence.
Raw market archives and 18.7MB of comparison tapes stay in runtime, not Git.

No primary database mutation, consumer start, exchange request, paid API call,
PAPER/LIVE startup or order was made. Trial 15, V4/V5 and frozen plans/ledgers/
evaluators remain unchanged. Blind results were not read; no forward days or
campaign trades were credited. The [source manifest](../config/current-release.json)
remains fail-closed.

Retain the native strategies as controls, not label adaptive or the union a
winner on seen data. Before prospective qualification, settle executable
quote/TTL evidence and continuous-risk policy without silently extending TTL
or loosening ceilings. LLM value still needs point-in-time matched evidence,
not an assumption that review rescues weak signals. No extra parameter search,
campaign freeze/enrollment or trading admission follows from this receipt.
