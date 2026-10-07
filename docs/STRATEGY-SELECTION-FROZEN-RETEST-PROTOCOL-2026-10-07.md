# Frozen breakout/retest: one separate development hypothesis

Fixed before the first census; this is not the selected LIVE strategy, a new
blind campaign, a rescue of an old result, or a revision of Trial 15/V4/V5.
The old compact-context complex and every published attempt remain unchanged.

## Why this one hypothesis

The October 6 native geometry audit found poor cost headroom for default
breakout/range candidates and an original adaptive 60-second entry lifetime
which expires before the next strict minute-open after the assumed 100ms
calculation. Twenty quiet compact-context cells cannot establish natural trade
frequency between them. Rather than invent a more distant target, this new
standalone research identity changes the entry structure: break, retest the
original level, then reclaim toward an already observed impulse extreme.
No evidence yet establishes positive net expectancy.

## Exact initial rule: `frozen_breakout_retest_v1`

- One contiguous closed 1m prefix from an explicit UTC five-minute origin;
  54h warmup, every completed 5m decision, at most 50,000 bars per symbol.
- A close beyond the prior twenty completed 5m high/low arms one setup. Freeze
  both channel boundaries, strictly prior ATR14, the breakout extreme and the
  prior forty-eight completed 5m external extreme.
- First distinct later bar at age 1--5 touches and closes back on the original
  side of the broken level. A distinct later close reclaims the level by age 6.
  A close strictly more than 0.5 frozen ATR against the level invalidates it;
  expiry is six bars. No EMA, flow, volume, body or regime conjunction is added.
- Stop is the retest-through-reclaim adverse extreme plus 0.25 frozen ATR.
  Distance must be 0.5--2 ATR and 10--300 bps. Target is the frozen breakout
  extreme, capped by a nearer prior 4h extreme only if that extreme lies strictly
  beyond the broken level. No target extension or tighter stop to pass costs.
- Fixed base planning round-trip cost 20 bps; net reward/risk at least 1.25,
  cost at most half gross stop distance. Original risk ceilings remain 0.25%
  per trade, 1% aggregate, 25% symbol notional and 1x gross leverage. The census
  allocates no positions and does not purport to prove aggregate risk compliance.
- The exact immutable native crash/post-shock guard cancels an armed setup or
  abstains; no new crash-short exception. A structural reclaim consumes the
  setup **before** any cost, review, risk, or execution outcome, including refusal.
  Consumed/invalidated/expired setups need a later close inside the old channel
  to reset; that reset bar cannot itself arm another setup.
- Only this new identity has a five-minute intent TTL and 120-minute maximum
  holding period. Native adaptive TTL, old evaluators and risk behavior are not
  changed. At first arrival, retain original barriers and recheck lifetime,
  native defense, prior stop/target touch, level, ATR bounds and costs; no retry
  on a later more favorable quote. Completion delay is explicitly an assumption,
  not a measured model response time.

The full machine-readable identity is `fixed_retest_policy()` in the separate
development module. It exports no production registration, providers, DB, or
order path. The arrival helper performs conditional geometry checks, **not**
producer/source authentication or trading admission.

## One bounded census, not a performance search

Reuse unchanged checksum-verified FULL_KLINE/funding caches on all five assets
over `[2021-05-17, 2021-05-22)` and `[2024-01-08, 2024-01-13)` UTC: 14,400
five-minute symbol slots, not only the old twenty pilot cells. These dates were
already examined; they are development diagnostics, not held-out alpha proof.
The new expanding origin is exactly each start minus 54h; state is never reset
at a rolling boundary. No downloads, threshold grid, annual replay or model calls.

Use one worker, 300-second wall budget and a specifically named create-only direct
runtime child. Capture the fixed protocol and installed-source receipt **before**
loading the markets; retain any failure and partial artifact, without retry or
overwriting old attempts. Validate gaps/typed inputs and original checksums,
then bind both source/input equality after the attempt.

Retain every state/transition/refusal, zero-candidate days, accepted planning
candidates and both fixed 20/33 bps reference/arrival scenarios. First arrival
uses only the next strict 1m open and closed prior history; the current minute's
future OHLC cannot be used for admission. Declared adverse displacement remains
a price assumption. Gzip is lossless and the receipt binds compressed bytes and
the canonical uncompressed decision tape.

No exit/PnL simulation, model/feed debit, source-authenticity admission, closed
trade count, strategy promotion or blind-day credit results from this census.
Required historical NEWS/MACRO remain unavailable; any later historical test
with models requires accepted causal source/budget evidence and fresh human
confirmation. All readiness stays false and `STRATEGY_POLICY=REJECT_ALL`.

After refreshing the non-editable development wheel, run **once** from runtime:

```powershell
& 'D:\Kairos\runtime\historical-context-20261007\py311\Scripts\python.exe' `
  -m adaptive_replay.frozen_retest_census `
  --workspace-root 'D:\Kairos' `
  --output-root 'D:\Kairos\runtime\frozen-retest-census-20261007-a'
```

Multiple tested configurations can overfit even with historical splits; the
one fixed hypothesis here does not erase prior selection bias.
[Primary methodological reference](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
Official archive checksums bind file bytes, not historical BBO or executable
venue liquidity. [Binance public archive schema](https://github.com/binance/binance-public-data).
