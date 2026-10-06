# Bounded adaptive development replay

An opt-in offline diagnostic of **one** selected `adaptive_pullback_range_v1`
source/configuration. It neither searches thresholds nor enrolls/promotes a
campaign. All trading readiness remains false and policy remains `REJECT_ALL`.
Trial 15, V4/V5, the frozen Backtest repository and evaluator are never edited.

## Fixed protocol

[plan.json](plan.json) fixes four disjoint three-day UTC calendar windows,
BTC/ETH/SOL/BNB/XRP, 54h causal warmup, exactly 3h exit tail, one worker and a
one-hour wall limit **before viewing this replay's returns**. Dates are development
diagnostics, not unseen/representative alpha evidence. The algorithm independently
labels each closed 5m decision BULL/RANGE/BEAR/CRASH/UNCERTAIN; a calendar label
never supplies a live regime. Quiet and unavailable slots remain distinct.

The Strategy package is installed from its immutable selected revision and
checked against its independent code/config hashes. Public pure archive/funding
parsers and stop-risk arithmetic are reused from frozen Backtest. This project's
explicit dependency overrides install current Core/Quant/Strategy/Persistence:
**this is a separate development environment, not the frozen campaign closure**.
No legacy evaluation command, ledger or blind result is run/read.

## Small native-baseline comparison

The separate [comparison-plan.json](comparison-plan.json) and
[preregistered protocol](../../docs/STRATEGY-COMPARISON-PROTOCOL-2026-10-06.md)
reuse unchanged native Donchian breakout and VWAP range defaults, their fixed
union control, and the adaptive candidate. The four dates are already seen;
this is diagnostic comparison, not independent alpha or strategy qualification.

All arms are replayed with the same explicit `COMMON_COST_RISK_V1` evaluator,
native lifetimes and completed-minute-close trailing. Legacy keeps native
expanding Wilder state; adaptive keeps its rolling 54h rule. Exact original
adaptive decision tapes may be reused only after published-byte/source/input
verification; no previous economic result is reused. No LLM/provider calls.

After installing a **fresh non-editable wheel**, run from a separate runtime
working directory, using an output directory that does not yet exist:

```powershell
$env:UV_PROJECT_ENVIRONMENT = 'D:\Kairos\runtime\baseline-comparison-20261006\py311'
uv sync --locked --no-editable --python 3.11 `
  --reinstall-package kairos-adaptive-development-replay `
  --refresh-package kairos-adaptive-development-replay
& 'D:\Kairos\runtime\baseline-comparison-20261006\py311\Scripts\python.exe' -m adaptive_replay.compare `
  --plan 'D:\Kairos\kairos\development\adaptive_replay\comparison-plan.json' `
  --bar-cache 'D:\Kairos\kairos-backtest\data\historical' `
  --factor-cache 'D:\Kairos\kairos-backtest\data\historical-factors' `
  --adaptive-evidence 'D:\Kairos\runtime\adaptive-development-20261006\bounded-20261006-b' `
  --output 'D:\Kairos\runtime\baseline-comparison-20261006\new-approved-run'
```

The refresh/reinstall flags prevent a local cached wheel from hiding harness
source edits; dependency locks/pins remain unchanged. This comparison has one
worker and a 30-minute wall limit. No resume, parameter grid, winner promotion,
cross-window compounding, forced quota or edits to original evidence.

## Timing and execution limitations

Adaptive eligibility is next-minute open and expiry is that open+59,999ms.
At declared 100ms decision-to-completion delay, the next strictly observed minute
quote is already expired. `STRICT_MINUTE_OPEN` records that no-fill finding without
altering the strategy, delaying expiry, backdating a review or inventing a quote.

`INTRABAR_OPEN_PROXY` is a separate **conditional candle approximation**:
timestamp is the declared completion within original lifetime; price uses that
minute's open plus adverse assumed spread/slippage/latency displacement. The quote
at that intraminute time was not observed. Full fills are assumed; capacity,
partial fills, order protection latency, real venue spread and execution are not
qualified. This is not a guaranteed PnL bound.

One clock/account serves all five symbols in fixed universe order. Admission uses
the modeled fill, unchanged SL/TP, frozen structural ATR and cost headroom, ≤0.25%
estimated loss-at-stop, ≤1% summed open risk (never long/short netted), ≤25% notional
per symbol and ≤1x gross exposure. Post-entry fees and adverse mark debit reduce
the sizing equity. Future intrabar exit proceeds cannot finance same-open entries.
Gap losses are retained and can exceed stop reservation; mark-time risk overruns
are reported, not hidden.

SL wins ambiguous candles including entry minute; entry-minute target-only touches
are not credited because they may predate entry. Timeout starts at first fill.
For a deadline inside a minute, an adverse stop touch takes precedence; otherwise
timeout uses exact deadline with that minute's open-price proxy, and unknown TP is
not credited. Its exposure stays reserved until bar-close processing: conservative
admission blocking, not exact real-time timeout execution. Intrabar timestamps
are bounds/proxies, not actual order receipts.
No fabricated intrabar path is interpolated. Terminal positions are reported,
never forcibly liquidated or counted as naturally closed campaign trades.

Base/stress planning allowances are 20/33bps. Fees are per side; spread/slippage
and latency displacement appear in fill prices **once**. Carry/uncertainty are
planning reserves, not cash charges. Archived native signed eight-hour funding
rates debit/credit positions at the unrounded archived `calc_time` proxy;
this is `ARCHIVE_CALC_TIME_ENTITLEMENT_PROXY`, not proof of venue settlement or
historical local availability. Candle open proxies the unavailable
mark price. Funding is never read for entry sizing. Existing positions settle
before same-open exit; new same-open entries do not settle retroactively. Missing
checksums, CRC, rows, gaps or required funding block the window with null economics.

Native archive `calc_time` timestamps can differ by milliseconds from nominal
00:00/08:00/16:00 boundaries. Coverage requires one native eight-hour event per
bucket within its first minute (this replay's price-resolution limit), not exact
millisecond equality. Actual timestamps are retained and funding/entry clocks
merged; funding after a gap exit or an earlier holding deadline is not charged.
This is not a claim about venue timing tolerance or historical mark availability.
The official [funding history API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data#get-funding-rate-history)
exposes `fundingTime` and mark prices separately; their equivalence to this
archive's `calc_time` has not been proved. The local archived rates do not supply
this harness with a real mark-price execution tape.

Returns are **trading net under these assumptions**, excluding unavailable
model/live-feed costs. Closed-minute MTM drawdown and an adverse within-minute
envelope are separate; neither proves actual tick-level maximum drawdown. Disjoint
window equity is reset and never compounded across omitted dates.

## Matched A/B preparation

Every scheduled slot, including quiet slots, has a causal cut, full input hash and
immutable candidate identity in an append-only tape. Each account arm is independent
and deterministic. Review receipts bind unchanged candidates, sources, response
hashes and actual completion/cost clocks; late review cannot force the baseline
fill time. Fixtures cannot turn into observed economic results.

Historical review/proposal arms remain `NOT_CALLED`, with **null** costs and economic
results. Point-in-time news/provider observations are absent; pretrained historical
event knowledge is a contamination risk. This prepares the matching boundary but
does not run the existing sealed matched A/B campaign or qualify any model route.

## Reproduction

Use uv 0.12.3 with Python 3.11/3.14. Install outside protected runtime environments:

```powershell
$env:UV_PROJECT_ENVIRONMENT = 'D:\Kairos\runtime\adaptive-development-20261006\py311-current'
uv sync --locked --no-editable --python 3.11
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
```

From a separate runtime working directory, test the installed wheel without
importing the package from the source directory:

```powershell
& 'D:\Kairos\runtime\adaptive-development-20261006\py311-current\Scripts\python.exe' -m pytest `
  --import-mode=importlib 'D:\Kairos\kairos\development\adaptive_replay\tests' -q
```

From that separate working directory, invoke the installed module with
absolute plan/cache/output paths. `--output` must be **new**; there is no resume,
overwrite or deletion of previous evidence:

```powershell
& 'D:\Kairos\runtime\adaptive-development-20261006\py311-current\Scripts\python.exe' -m adaptive_replay.runner `
  --plan 'D:\Kairos\kairos\development\adaptive_replay\plan.json' `
  --bar-cache 'D:\Kairos\kairos-backtest\data\historical' `
  --factor-cache 'D:\Kairos\kairos-backtest\data\historical-factors' `
  --output 'D:\Kairos\runtime\adaptive-development-20261006\new-approved-run'
```

Plan/source/lock receipt precedes any performance output. Inputs are read-only and
network downloads are forbidden. Output includes checksum/normalized input hashes,
all causal slots, per-scenario ledgers, null absent arms, terminal exposure and
cash reconciliation. A failed attempt is retained. Re-running is not a strategy
search, a sealed evaluation or forward/blind credit.

The completed small native comparison and its exact economic boundaries are in
[the dated receipt](../../docs/STRATEGY-COMPARISON-2026-10-06.md). Published input,
source, accounting and first-failure artifacts are byte-bound by
[the evidence index](evidence/comparison-2026-10-06/checksums.json); CI validates
them without replaying market history. No qualified winner is selected.
