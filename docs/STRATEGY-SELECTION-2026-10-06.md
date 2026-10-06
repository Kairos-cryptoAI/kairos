# Strategy-family selection, without system integration — 2026-10-06

## Decision and scope

The user's latest direction is strategy selection only. News, Macro, Router,
LLM review/proposals and execution integration are paused for this work, not
removed from the eventual concept. The deterministic strategy is one source
of executable opportunities, not required to deliver a spectacular monthly
return alone. The other layers have to demonstrate their incremental value;
assuming that they rescue negative signals is not a selection method.

This pass narrows research to **three lines**, with one exact paired control.
It does not choose a qualified winner, create a new strategy, retune any
configuration, start a campaign or connect an arm to trading services.
Earlier native transport/accounting work is preserved, not undone.

## Shortlist and roles

| priority / role | unchanged implementation | why keep it / remaining limitation |
| --- | --- | --- |
| First historical reference: aligned, positive-skew trend following | `regime_aligned_right_tail_v1`, compared only with exact `right_tail_trend_v1` base | Existing published research demonstrates some incremental benefit of one slow alignment filter under stress; different daily cadence and 72h holding make it a reference, not a ready intraday replacement. Trial 15 stays frozen and cannot receive LIVE permission. |
| Intraday negative/active control: price breakout | `trend_breakout_v1` | A small established Donchian/hourly trend rule with variable activity and explicit trailing/lifetime. Current defaults have narrow cost headroom and weak published diagnostic results; frequency does not make it a winner. |
| Event-driven challenger: trend pullback, range-edge reclaim, defensive shock/retest | `adaptive_pullback_range_v1` | Already implemented, finite and causal; no need to invent another combined framework. Keep its exact rules provisionally, not as the selected champion. Current evidence is sparse, has no range candidates in these slices and cannot observe timely strict fills. |

There are two opportunity families here: trend continuation and bounded range
reversal. A crash overlay is chiefly an abstention/protection rule, with an
optional confirmed retest short, not a promise to foresee or profit from every
crash. Several implementations of a trend family are controls, not a request
to activate them all simultaneously.

The right-tail reference decides once per UTC day from a causal 24h hourly
momentum score; its aligned version uses the last closed 4h SMA200 direction.
Both retain 2 hourly ATR stops, a 4R target, 72h timeout and 1h entry lifetime.
No change to the desired variable frequency, including zero, follows from
keeping this slower reference. There is no daily trade quota.

The published [Trial 15 reused-data screen](../../kairos-backtest/reports/regime-aligned-screen/REPORT.md)
compared the candidate with that exact base under the same historical execution
model. Stress PF was 1.2040 versus 1.1833 in selection and 1.1071 versus 1.0382
in robustness; roughly 68–69% of stress trades remained. This is why it is a
useful reference. Baseline return fell in selection, baseline drawdown increased
in robustness, and only ETH/BNB/XRP were positive in robustness stress; BTC/SOL
were negative. This is neither universal improvement nor independent alpha.
It cannot be ranked against the small October intraday comparison as if both
had identical dates, capital, costs, cadence and accounts.

## New completed check: geometry, not another return contest

The [read-only audit](../development/adaptive_replay/adaptive_replay/selection.py)
read the original completed comparison's twelve native-arm tapes. It verifies
the exact published result bytes, installed native identities and cost/risk
source, canonical tape hashes, every symbol/5m slot, native intent IDs and entry
clocks, and the unchanged input receipt digest. It reads no market archives,
reruns no generator or price/PnL simulation and invokes no models or services.

Scope: the same four **already seen three-day slices**, BTC/ETH/SOL/BNB/XRP,
17,280 market slots and 51,840 arm-slot records. The original conditional
[economic comparison](STRATEGY-COMPARISON-2026-10-06.md) and its failed first
attempt stay untouched. The new [geometry receipt](../development/adaptive_replay/evidence/selection-2026-10-06/geometry.json)
retains counts, input/tape identities, reference rejection reasons and the
original unknown source-availability values; it does not create new returns.

| native arm | candidates | reference geometry passes, base 20bps | reference geometry passes, stress 33bps | no strict minute quote inside native TTL at assumed 100ms completion |
| --- | ---: | ---: | ---: | ---: |
| breakout | 583 | 102 | 10 | 0 |
| default VWAP range | 140 | 0 | 0 | 0 |
| adaptive challenger | 12 | 12 | 11 | 12 |

Passing here is **not an entry or a closed trade**. This fixes entry to the
signal's reference price solely to diagnose geometry; subsequent observed fills
can improve or worsen it. It excludes actual fill displacement, account/venue
admission, available capacity, provider expense and expected win probability.
The cost scenarios are planning assumptions, not measured EVEDEX costs.

The check keeps net reward/risk >=1.25, stop distance 10..300bps and modeled
cost <=50% of gross stop distance. Its isolated geometric calculation retains
0.25% risk and 25% notional/1x sizing limits; it grants no allocation or authority.
It does not prove continuous portfolio risk <=1%. The earlier June mark-time
1.0028446646% risk-ratio overrun remains disclosed, not repaired or rounded away.

### Why the default VWAP range is not a fair rejection of range trading

At the unchanged reference price, re-entry is at most 1.25 ATR from VWAP, target
is VWAP and stop is 1 ATR. Therefore gross reward/risk <=1.25; positive costs
make net reward/risk strictly smaller. All 140 actual reference geometries fail
the common hurdle. An advantageous later fill can change that geometry, which
explains why the original comparison can still contain one range trade.

This diagnoses the **default configuration/hurdle compatibility**, not the
absence of mean-reversion alpha. Do not lower the hurdle, tighten the stop or
extend the target after seeing returns to make the old experiment pass.
For a bounded range-family challenger, the existing adaptive edge reclaim is
the separately specified alternative; its economic merit is still untested by
an adequate observed-fill range sample.

Breakout has gross reward/risk about 1.6. In a simplified equal-price cost model,
meeting net >=1.25 leaves cost/stop <=(1.6−1.25)/(1+1.25), about 15.56%; actual
side-specific max-price arithmetic is slightly more conservative. This explains
why only 102/583 reference candidates survive 20bps and 10 survive 33bps.
Target room and realistic costs must be considered before celebrating activity.

The adaptive candidates are ten trend pullback reclaims and two crash support
retests, **zero range-edge candidates**. Its 60s lifetime plus the existing
assumed 100ms completion pushes the next observed minute open outside expiry.
The prior intraminute open proxy was explicitly unobserved and lost money in
both active slices; it is not evidence of fills or superiority. Do not extend
TTL silently or treat an unobservable fill as an ordinary no-trade evaluation.

## What is not pursued now

- The unchanged medium EMA pullback is not an untested promising omission.
  The [published January–June 2023 screen](../../kairos-backtest/reports/development-screen/REPORT.md)
  recorded 105 baseline closes, −0.7125% and PF .683; stress 41 closes,
  −0.1080% and PF .887. Shallow failed stress, deep had only 38/10 closes.
  Extra warmup fixes comparability, not that evidence. No fourth depth band.
- The [regime/retest/flow conjunction](../../kairos-backtest/reports/regime-retest-screen/REPORT.md)
  reduced 41,741 structural breakout events to 12 structural intents and one
  losing baseline trade, zero stress trades. Do not accumulate more hard
  conditions merely because each concept sounds reasonable.
- Fixed breakout+range union matched breakout in 15/16 diagnostic cells; its
  one difference worsened results. It is not selected as a useful combination.
- Coarse order-flow impulse, crowded-trend and long-flat SMA alternatives
  retain their consumed negative historical decisions; do not automatically
  re-run them. Donchian ensemble's source-integrity-blocked INCONCLUSIVE result
  is not a measured alpha failure. Quarter-hour V4/V5 and blind Trial 15 results
  are outside this work and remain untouched.
- No per-symbol/side threshold tuning, leverage uplift, indicator voting,
  news reconstruction, historical LLM predictions or new parameter grid.

SMC is usable as explicit price-event components: a level frozen before entry,
a bounded crossing, a completed reclaim, invalidation behind the known extreme,
expiry and rearming. The current adaptive range already contains that kind of
pattern. OHLC bars alone do not establish institutional intent, stop-hunting or
absorption; those names do not add independent evidence. Any later component
must be tested as one distinct change, not an unexplained conjunction.

## Next selection work, before integration

The smallest informative additional historical compatibility test is the
unchanged right-tail **base versus aligned** pair, not more adaptive variations.
It should use the same four known diagnostic slices with a **35-day causal
prefix and 72h exit tail**, native 1h lifetime, observed minute opens, common
base/stress costs and fixed account-wide risk. The 54h/3h intraday comparator
cannot fairly include 4h SMA200 and positions held up to 72h. This next test
is described here, **not launched or campaign-frozen by this audit**.

Use one worker, a bounded runtime and existing checksum-verified cache only;
missing prefix/tail is unavailable, never imputed. Record both arms and all
rejections, natural closes and unresolved exits, without choosing a winning
window, pooling omitted dates into a return, or shortening the slow rule to
produce more trades. A sparse result remains insufficient, not a champion.
Further evidence needs broader predefined bull/range/bear/crash coverage;
these twelve seen days are not a final historical qualification set.

The event-driven challenger needs genuinely observed quotes inside its native
lifetime before executable economics can establish its relative value. This
does not authorize source downloads, services, venue qualification or integration
here. Keep only one eventual selected identity/evaluator for the new campaign.
Trial 15's days/results cannot transfer; its existing baseline remains excluded
from LIVE. Own 365 future days, 500 natural simulated closes, the approved
sealed gates and independent venue/production checks remain necessary.

Research priors are not crypto/intraday evidence: the original
[time-series momentum study](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)
supports considering the trend family at long horizons in traditional futures,
not these specific entry rules. The
[backtest-overfitting paper](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)
supports keeping prior exposure and repeated selection explicit; a small
human-designed shortlist is not immune to selection bias.

## Reproduction and engineering acceptance

With the unchanged locked, non-editable development environment, from outside
the source tree:

```powershell
python -m adaptive_replay.selection `
  --plan D:\Kairos\kairos\development\adaptive_replay\comparison-plan.json `
  --comparison-root D:\Kairos\runtime\baseline-comparison-20261006\bounded-20261006-b
```

The command prints JSON only; it cannot write/overwrite source tapes or ledgers.
Missing/changed/truncated/noncanonical evidence, identity, native clock or unknown
outcome fails closed. It has a 60s tape-audit bound; the completed audit command
took 1.76s. Unit tests cover LONG/SHORT geometry, stress costs, favorable-fill
counterexample, headroom, native lifetime, null availability, hashes, denominator,
unknown outcomes and deadlines. Thirty focused tests pass; the full installed,
non-editable offline suite passes **219 tests each on Python 3.11 and 3.14**.
Ruff lint/format, patch whitespace and the meta static/document-link gate pass.
No dependency or runtime pin was changed.

Receipt file SHA-256: `da964975ad15f31e213626bd9ec258ffcf54ee9235b714b9ed818b06c0a880e6`.
Audited module SHA-256: `1a4c0afb152fb9d2689519a5f97fc9a531ebf2d534fa36d4230918a27aa5dd4d`.

No frozen plan/evaluator, Strategy source, primary DB, consumer, key or paid
provider was touched. `TECHNICAL_PAPER_READY`, `PAPER_QUALIFIED`, `ALPHA_READY`
and `LIVE_READY` remain false; `STRATEGY_POLICY=REJECT_ALL`.
