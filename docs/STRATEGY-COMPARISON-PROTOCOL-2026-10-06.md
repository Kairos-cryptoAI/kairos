# Small native-strategy comparison: protocol fixed before new economics

Scope: engineering/development only. No trading or strategy admission. This is
not a fresh blind campaign, parameter competition or an attempt to invent a new
market effect. All readiness remains false and policy remains `REJECT_ALL`.

## Fixed candidates and already seen data

Reuse unchanged installed default `TrendBreakoutConfig()` (Donchian20/ATR14,
hourly12h regime, native 1ATR close-updated trailing) and
`RangeMeanReversionConfig()` (prior VWAP24/ATR14, hourly12h range filter).
Both retain registry status REJECTED and exact native intent/config/source IDs.
No retuned periods, target multipliers, disabled trailing or per-asset settings.

Compare four independent accounts: each native sleeve, a fixed breakout+range
union control, and the unchanged `adaptive_pullback_range_v1`. The union is a
newly specified portfolio control, **not** a previously validated standalone
strategy: opposing directions in one symbol/slot cause no entry; coincident
same-direction candidates use fixed breakout-first priority. Stops/targets are
never blended and coincident signals cannot double the symbol's position.

Use the same five assets and the already exposed four three-day development
slices from [the original protocol](../development/adaptive_replay/plan.json).
Their dates/returns were seen before this comparison was specified. They are
not untouched holdout, representative yearly alpha or independent crash proof.
Do not replace quiet/unprofitable slices or call the highest return a champion.

Default trend-pullback is excluded from this minimal comparison: its hourly
EMA72 cannot initialize from the shared54h warmup. Shrinking EMA72 to make it
trade would be a new strategy variant. Daily/4h allocation strategies require
different contracts and horizons and are outside this small matched comparison.

## Common execution boundary

- Checksum/CRC-verified contiguous1m OHLCV and native funding for all five
  symbols; cache-only, no downloads. No future funding in sizing.
- Legacy starts on exactly54h pre-window prefix with native expanding Wilder
  state; adaptive retains rolling3240 bars. They share available past data,
  not an artificially identical recursive initialization. Exact prefix intent
  equality at fixed24h/48h/hour-close cuts is required before replay.
- $10,000 reset per account/window; fixed universe order,100ms completion,
  the original base/stress costs,3h exit tail, no tail entries, forced closes,
  compounding of omitted dates, annualization or quotas.
- Common fill-time admission: net reward/risk>=1.25,10..300bps stop,
  cost/stop<=.50, per-trade risk<=.25%, total non-netted open risk<=1%,
  per-symbol notional<=25%, gross<=1x at admission. No adaptive-only ATR15
  metadata/geometry filter is imposed on legacy. Adaptive's own source filters
  remain unchanged; counts/rejections distinguish source from common execution.
- Preserve native lifetime: adaptive60s, legacy5m. Strict execution waits for
  an actual eligible future minute-open quote, using that minute's price.
  Native TTL differences affect feasibility, not proof of signal alpha.
- Conditional intraminute-open proxy remains separately labelled unobserved
  quote/full-fill approximation. Unknown liquidity, partial fills, protection
  latency, model/news/feed costs and actual venue funding remain unqualified.
- Stop-first ambiguities, gap losses, entry/deadline-minute TP suppression and
  funding ordering remain. Trailing activates/ratchets at completed1m CLOSE
  after checking old barriers; new stop is effective only on later candles.
  It never loosens or releases the original risk reservation.

The former adaptive replay's ATR-specific fill admission is not neutral. Its
earlier economic numbers are **not reused**. Only the byte-bound original
adaptive decision tapes can be reused after input/source/hash verification;
all four accounts are replayed under this new explicit common evaluator.
This avoids expensive duplicate detector work without reading a blind ledger.

## Evidence and resource bound

[comparison-plan.json](../development/adaptive_replay/comparison-plan.json)
fixes arm/source/config identities, shared admission and the30-minute,
single-worker limit. Write its plan/source receipt before new economics to a
fresh output directory. Failed/partial attempts survive; no resume/overwrite.

Report every arm/window/mode/cost, quiet slots, candidates, common rejects,
entries/natural closes/zero-entry days, long/short/family results, fees/funding,
minute-MTM drawdown, adverse-envelope bound and terminal exposure separately.
No actual news/LLM historical arm is run: point-in-time evidence is absent.

This diagnostic cannot freeze/enroll a replacement campaign or promote any
readiness. A qualified adaptive system still needs its own prospective gates,
365 genuine future days,500 natural closes and all venue/security/runtime gates.
Trial15,V4/V5, frozen source/ledgers/evaluators and runtime database remain intact.

Methodology: increasing strategy/parameter selection on a finite history raises
false-positive/overfitting risk, as explained by the original
[Probability of Backtest Overfitting paper](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
This small development comparison still has prior exposure; it is not immunity
to selection bias and not a replacement for independent evidence.
