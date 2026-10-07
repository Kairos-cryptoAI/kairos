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

### Slow native right-tail pair

The separate [right-tail-plan.json](right-tail-plan.json) and
[October 7 protocol](../../docs/STRATEGY-SELECTION-PROTOCOL-2026-10-07.md)
compare unchanged base/aligned daily trend generators on the same seen entry
dates, with a 35-day causal prefix and 72h exit tail. Run the installed wheel's
`python -m adaptive_replay.right_tail` with `--plan`, `--bar-cache`,
`--factor-cache` and a fresh `--output` directory. Both strategy trees are sealed,
including the base sleeve imported by aligned. It is one bounded cache-only
experiment, not frozen Trial 15 execution, tuning, integration or qualification.

### Intraday observation controls

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

### Causal historical episode reconstruction

The additive [historical bridge](../../docs/HISTORICAL-CONTEXT-REPLAY-2026-10-07.md)
connects bounded exact-version NEWS/MACRO archives and closed-bar prefixes to a
separate complete 1m/five-symbol review replay. Modern model clocks remain modern;
historical delay/cost projections are explicit, never native observed receipts.
It reuses common risk, retains refusals/failures/unknown costs and never supplies
future bars, funding, episode labels or ledgers to prompts. The
[episode roster](historical-episodes-draft.json) is source preparation only, not
an executable economic protocol. No actual model/economic run is claimed.
Training contamination remains unexcluded; frozen campaigns are unchanged.

### Additive full-system accounting

The [system.py](adaptive_replay/system.py) API accepts a complete five-minute,
five-symbol roster and independently replays `strategy_only`, `context_review`,
`independent_proposals` and `combined`. No provider/venue calls, campaign loading,
runtime risk decisions or trading authority are introduced. All accounts use
`COMMON_COST_RISK_V1`, **not** the older adaptive-only structural-ATR control.

Every attempt binds the per-slot causal source context, receive clocks and TTLs.
Review keeps its unchanged candidate and uses the local captured/observed clock,
not the earlier provider completion. Native proposals require their exact native
completion plus a separately supplied deterministic mapper receipt/policy hash.
The actual mapper, source payload archive and provider/invoice receipts remain
unqualified. Missing mapping is not `NO_PROPOSAL`; missing responses and unknown
model costs keep that path's economics null. Unknown feed costs keep
`recorded_all_in_net_result` null even if a conditional trading ledger exists.

The fixed conservative combined control requires review of baseline candidates;
`VETO/DEFER` cannot be bypassed in that slot. Opposite eligible directions abstain;
same-direction candidates select the unchanged baseline once; quiet strategy
slots may use independent mapped proposals. It waits for every required observation
and rechecks expiry/freshness after waiting. This is an engineering test control,
not a frozen production policy or an economically selected optimal arbitration.

Recorded costs debit each independent account once at the observable clock, before
same-clock sizing, including veto/error/no-action/no-fill and exit-tail costs.
Combined pays both incurred paths. Its return is not the sum of isolated trade
returns. Counterfactual missed winners/avoided losses are baseline diagnostics,
not attributable account profit. Scheduled `NOT_CALLED` requires an explicit
policy reason and is counted separately from complete model responses.

Fixtures require `fixture_only=True` and cannot mix with observation receipts.
All execution/alpha/readiness/complete-all-in markers remain false. See the
[engineering receipt](../../docs/FULL-SYSTEM-EVALUATION-2026-10-06.md).
Earlier published historical results and their absent model arms are untouched.

### Candidate-stream selection controls

The optional `deterministic_filters` roster and `include_review_timing_control`
flag add independent causal-source and review-clock/cost controls to the existing
system API. `include_selection_audit=True` reports every original candidate's
selection/execution, baseline outcome, delay/cost and source coverage; missing
observations keep economics null. Default four-arm output remains unchanged;
opt-in output uses a separate v2 schema. Weak standalone PnL is not an automatic
research exclusion, but no filter/LLM improvement is presumed or qualified.
There is no return-based whitelist, new grid, quota, retrospective news call,
production wiring or frozen campaign change. See the
[candidate evaluation receipt](../../docs/STRATEGY-FILTER-EVALUATION-2026-10-07.md)
for the fixed policies, API and outstanding real-data prerequisites.

### Native saved-window transport

The [observations.py](adaptive_replay/observations.py) API exports/imports one
native causal campaign window without rewriting clocks or original intent IDs.
It validates native source/evaluation/attempt/pair/outcome links, preserves
immutable outcomes alongside late append facts, and distinguishes committed
charges from held/unresolved reservations. Empty or incomplete expense coverage
has a null total, not zero. File import requires a separately supplied SHA256;
export is create-only and fixture/observation modes must match exactly.

This is bounded transport/inspection, **not** a native-to-four-path economics
conversion, full campaign denominator, provider/DB authenticity proof or trade
mapper. It opens no DB and has no provider/seal/trading action. Its injected
reader must be separately trusted SELECT-only; no writable repository is
constructed. See [the native transport receipt](../../docs/NATIVE-OBSERVATION-IMPORT-2026-10-06.md)
for limits, CLI usage and the remaining native-clock/cadence adapter boundary.
All economics/readiness/authority markers stay false.

### Full-calendar reference comparison

The separate [calendar protocol](../../docs/STRATEGY-CALENDAR-PROTOCOL-2026-10-07.md)
fixes four complete 2022--2025 years and a byte-bound SOL November 2022 funding
schedule before returns. `python -m adaptive_replay.calendar_pair` uses the
same required plan/cache/new-output arguments as the earlier replay. No old
plan, loader, economic receipt or campaign changes. The output can nominate a
development reference only, never select an adaptive/LLM strategy or qualify
trading; resource/integrity failure yields no partial-year winner.

The [single October 7 attempt](../../docs/STRATEGY-CALENDAR-RESULT-2026-10-07.md)
failed input completeness before generation/economics; SOL is missing five
calendar days. No annual return or reference nomination exists. Keep the
byte-bound failure and do not resume/retry or fill missing candles.

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

## Separate price-only slow reference (October 7)

The original failed full-calendar pass remains immutable. The
[separate field-scope protocol](../../docs/STRATEGY-PRICE-SOURCE-PROTOCOL-2026-10-07.md)
and [price-reference-plan.json](price-reference-plan.json) accept only two
unchanged price consumers, not adaptive/volume/production use. All missing
minutes come from byte-bound official daily files; the single inconsistent
optional-field row retains its original OHLC/clocks, with no replacement.
Uniform optional zeros mean unavailable placeholders, never observed volume.

Input-only `adaptive_replay.source_set --price-reference-only` checks prior
audit/retrieval provenance, complete grids, exact raw overlap, row lineage and
current funding bytes. The retained losslessly compressed acceptance is in
[the evidence directory](evidence/source-qualification-2026-10-07).
The distinct `adaptive_replay.price_calendar` requires `--plan`, `--bar-cache`,
`--factor-cache`, `--daily-cache`, `--source-acceptance` and create-only `--output`.
It verifies all accepted bytes before generation and after the four years.
The same native defaults, costs, risk, reference rule and 1,200s single-worker
bound apply. Do not retry either old or new economic attempt, select incomplete
years or turn this field-specific development comparison into qualification.

The [completed price-only result](../../docs/STRATEGY-PRICE-RESULT-2026-10-07.md)
covers all sixteen 2022--2025 cells in one 654.25-second run. Independent
PowerShell ledger arithmetic passes; the unchanged nomination rule retains
`NO_ECONOMIC_REFERENCE_WINNER` despite higher aligned stress returns, because
of risk overruns and the 2023 drawdown tradeoff. This does not solve the final
adaptive/LLM selection. All 54 original source/tape/report/ledger/audit artifacts
are losslessly compressed and byte-bound by
[the publication index](evidence/price-calendar-2026-10-07/checksums.json).
CI checks the stored evidence without another historical economic replay.

## Source-only native intraday references

The separate [intraday source protocol](../../docs/STRATEGY-INTRADAY-PROTOCOL-2026-10-07.md)
byte-binds all four original native decision tapes and every one of their twelve
candidates. It streams nine fixed public daily aggTrades ZIPs under explicit
resource/TLS/create-only guards. It records transaction-clock witnesses after
assumed completion inside the unchanged 60-second lifetime; never BBO, our fills,
capacity or economics. Old plans, generators, source caches and frozen campaigns
are not changed or resumed. There is no automatic retry or promotion.

Run the separately signed plan only after its exact source CI passes:

```powershell
python -m adaptive_replay.intraday_audit `
  --plan D:\Kairos\kairos\development\adaptive_replay\intraday-source-plan.json `
  --native-root D:\Kairos\runtime\adaptive-development-20261006\bounded-20261006-b `
  --output D:\Kairos\runtime\intraday-reference-audit-20261007-a
```

Only a **new direct child** of the workspace runtime directory is accepted.
`COMPLETED` denotes a completed source audit, not twelve qualified references or
a strategy winner; inspect every recorded status. No economic or observed-fill
credit follows from published prints, and readiness stays false/`REJECT_ALL`.

The [single dated attempt](../../docs/STRATEGY-INTRADAY-RESULT-2026-10-07.md)
is now `FAILED_CLOSED` at the fixed BTC June 14 row bound, not completed or an
economic rejection. Seven scans retain ten candidate witnesses; two are
unresolved and no final before/after gate ran. Thirty-two original partial
artifacts/native tapes are losslessly bound by
[the evidence index](evidence/intraday-reference-2026-10-07/checksums.json).
The command above documents that completed attempt; **do not run it again**.
No source/economic prerequisite, winner or trading authority is granted.
