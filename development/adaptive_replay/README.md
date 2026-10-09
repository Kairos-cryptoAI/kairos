# Bounded adaptive development replay

An opt-in offline diagnostic of **one** selected `adaptive_pullback_range_v1`
source/configuration. It neither searches thresholds nor enrolls/promotes a
campaign. All trading readiness remains false and policy remains `REJECT_ALL`.
Trial 15, V4/V5, the frozen Backtest repository and evaluator are never edited.

## Separate opt-in public source producer

`python -m adaptive_replay.public_book_capture` is a no-op by default. Its separate
`--capture --workspace-root D:\Kairos --output-root <new-public-book-capture-child>
--seconds 60` mode makes exactly one credential-free public Binance UM connection
for all five top-ten streams, preserving original delivered text and actual local
delivery/persistence clocks. Bounded immutable segments and the full raw-message
denominator can be reopened under an independently held terminal receipt SHA.
No redirects, retries, reconnect, old V1 adoption, provider, DB or trading calls.
Observed source consistency is not continuous tick completeness, historical BBO,
accepted full-system inputs or strategy economics. See the
[producer contract](../../docs/PUBLIC-BOOK-CAPTURE-2026-10-09.md).

## Isolated durable SIM accounting primitives

`adaptive_sim_account` is an immutable Decimal account reducer, not the
production Risk Manager. New reservations retain the unchanged 0.25% trade,
1% aggregate open-risk and 1x gross ceilings. Original entry-stop risk is not
released because of favorable marks or trailing stops. Conservative sizing also
reserves known immediate spread/fee capital loss of pending entries; actual
unexpected fills, drift and stale marks remain explicit fail-closed observations.
Known owned stop/target/timeout protection blocks entries while pending; an
external source or unknown-exposure barrier cannot be cleared merely by going
flat. The runner must separately prove terminal commands and complete coverage.

`sim_account_codec` requires exact canonical closed-schema state and exact typed
gates; falsey integers cannot substitute for booleans. `sim_state_journal` keeps
caller-supplied events, outcomes and full state atomically in a create-only
isolated SQLite file. It validates the exact schema and externally supplied
identity, applies byte/row limits without eviction and excludes linked paths.
Caller redelivery uses `lookup` before reducer execution; append also checks the
optimistic predecessor. It never repairs a corrupt journal or recreates a
missing one. Local hash-chain consistency is not hostile-owner authenticity or
proof that a caller's reducer is economically correct.

`sim_book_tape.load_public_book_tape` consumes only a complete observed capture
under its separately held terminal receipt SHA. It verifies immutable raw bytes
before normalization and preserves per-symbol history across rotated segments;
independent symbols do not share a globally increasing exchange event clock.
Derived kernel coordinates are explicit mappings, not new vendor originals.
These primitives and synthetic tests are not a complete continuous campaign,
accepted historical corpus, model comparison, strategy winner or trading permit.

`continuous_sim.ContinuousSimPortfolio` composes those primitives with the pinned
execution IOC kernel. Each matched arm owns one separate durable account and
per-symbol session liquidity across multiple original V2 hypotheses. Creation
pins the producer hypothesis seal, whole tape, funding schedule, contiguous
minute/five-symbol denominator, rules and implementation before intake. A first
trigger remains consumed after veto, risk refusal or no fill. Source availability
orders intraminute arrivals; equal-time source records precede commands.
Original partial-fill protection, close-only trailing without a target clamp,
first-fill timeout and exposure-time funding survive restart and redelivery.
No unavailable cell, missing held protection bar, missing funding liability,
open exposure or command can be relabelled as a complete net result. No position
is force-closed to finish a window. Resource bounds fail closed without eviction.

Twenty-two full-path tests are synthetic mechanical checks, not historical or
LLM evidence. The final immutable installed-wheel full suite passed 1,490 tests
on each Windows Python 3.11/3.14 with four explicit platform skips and warnings
treated as errors. The runner has no model/network/trading CLI. Real input assembly,
source admission and the matched economic driver remain separate. Captures
bind their original whole-package implementation: reopening an older bundle
under new code is correctly refused. Preserve its wheel and originals; a later
exact-byte/version bridge must retain the old pinned audit identity rather than
resealing old bundles under the new implementation.

## Scenario-based trading research rework

`scenarios.py` separates a source-bound hypothesis from subsequent closed-price
confirmation, immutable stop/target/expiry, directional review and downstream
Risk. `scenario_bridge.py` uses the actual unchanged compact technical decision
and context-direction mapper, but produces a **waiting scenario**, not entry
permission. Quiet slots remain quiet; unavailable data never becomes valid
no-trade evidence. The first structural trigger is consumed even if refused;
terminal scenarios do not revive after new model answers or more favorable prices.

This is a new unqualified research hypothesis. It does not amend the old complex,
candidate tapes, results or frozen protocols. Closed-minute confirmation can
expire native 60s candidates before any observation is available: the original
expiry is deliberately retained. The implementation alone grants no quotation/fill
guarantee, economic qualification, production registry entry or paid loop. The explicit `require_review=False`
mode is only the isolated strategy-only comparison control, never a Risk bypass.
See [implementation and limits](../../docs/SCENARIO-REWORK-2026-10-08.md).

The separate [fixed price-only comparison protocol](../../docs/SCENARIO-COMPARISON-PROTOCOL-2026-10-08.md)
compares unchanged compact technical candidates and the waiting layer on all 360
native cells / 1,800 minute cells in the first six hours of the already-seen
June 13, 2022 window. `python -m adaptive_replay.scenario_compare` accepts only
`--workspace-root` and a new specifically named direct runtime `--output-root`.
It has one worker and cooperative/outer hard 600-second limits, no retry, model,
download or venue path. Common base/stress accounting and strict/proxy timing
stay separate; complete-system net and missing model/feed costs stay null.
Unsupported trailing is explicit policy abstention, not silently changed exits.
Native 60s expiry remains too short for later closed-minute confirmation. An
all-no-entry arm cannot demonstrate confirmation alpha. Failed/timeout receipts
invalidate any partial numerical account files; original attempts stay immutable.
The [single completed result](../../docs/SCENARIO-COMPARISON-RESULT-2026-10-08.md)
preserves all 36 unchanged breakout candidates but prepares zero supported
scenario plans (25 UNCERTAIN, 11 trailing-incompatible). It does not qualify a
confirmation rule: a zero-trade arm misses winners as well as losers. Do not
retry, retune, extend TTL, pool timing models or promote this v1 on those results.

## Separately versioned hypothesis / fresh-entry v2

`hypothesis_v2.py` and `hypothesis_bridge_v2.py` separate explicitly sealed
hypothesis validity from the original native executable candidate lifetime.
The exact parent is not renewed. One later structural trigger can issue one
different quote-priced research candidate with bounded fresh clocks, unchanged
full ExitPlan/trailing and preserved metadata. Review binds both source context
and the separate quote; price-only mode has another frozen policy identity.
No default lifetime is selected and no v1 comparator/attempt is rerun.
See [contracts, guards and integration limits](../../docs/HYPOTHESIS-LIFECYCLE-V2-2026-10-08.md).
This is library/fixture engineering only: no runner or runtime registration,
authenticated quote corpus, observed historical economics or alpha approval.
Native runtime still refuses trailing, and actual fills need an independent
activation/protection check; quote geometry is not execution qualification.

The additive `hypothesis_journal.py` provides a create-only bounded SQLite
research journal around that unchanged v2 fold. Typed replay, atomic first-trigger
recording, original-parent identity, frozen arms and exact duplicate/conflict
checks survive process restart; no publisher, runner or runtime integration follows.
Controls cannot be enrolled after any observation for the same parent. See
[durability proof and source audit](../../docs/HYPOTHESIS-JOURNAL-2026-10-09.md).
Accepted kline/PRICE_ONLY/aggTrades evidence is not a causal bid/ask corpus;
the journal does not fabricate quotes or qualify caller-attested provenance.

The separate `quote_capture.py` parses retained exact-byte caller-supplied BBO
captures, including same-snapshot base-asset quantities. Its explicit Kairos
research wire format is not an official exchange protocol or authenticated feed.
`fill_feasibility.py` freshly audits the original journal and checks one supplied
simulated fill against exact issuance, original expiry/protection, causal quote
clocks, executable-side capacity and unchanged planning assumptions. It does not
invoke Portfolio.admit, size risk, create positions/orders or record executions.
Repeated assessments are diagnostics, not repeated fill permission. See
[source and execution-feasibility boundary](../../docs/QUOTE-FILL-FEASIBILITY-2026-10-09.md).
New modules intentionally change the journal's installed implementation binding;
old journals are not adopted, migrated or resealed under the new source identity.

The additive `native_book_capture.py` now binds every supplied native V2 frame
field/level to its retained original combined `depth10@100ms` JSON, before deriving
the separate research BBO bytes. Legacy and migrated UM profiles are explicit;
the hypothesis source identity includes the full conversion/profile/TTL policy
digest. A bounded complete root-to-head prefix check retains missing-symbol
counts and refuses barriers, epoch joins, skipped frames and clock/update
regressions. Intact recorded hashes are **not** proof of continuous market
coverage, authentic receive clocks or actual fills. The existing recorder still
produces V1 without raw text and is not upgraded or admitted. See
[native byte-binding boundary](../../docs/NATIVE-BOOK-BINDING-2026-10-09.md).

The additive `book_bundle.py` exclusively retains a bounded complete supplied
V2 prefix, exact original raw text and derived binding records in a separate
`.native-book.research.json` file. Every reopen requires the caller-held seal
and whole-file retention receipt and freshly audits the full source chain.
Modern retention time does not replace native clocks or renew quote freshness.
Exact capture lookup never guesses a replacement. A separate journal-source
audit binds the quote-only bundle commitment and independently pinned journal
head/count, rejecting unretained or ambiguous originals without changing the
old journal schema. It is not full-system source acceptance, a recorder,
publisher or proof of authentic/continuous historical coverage. See the
[retention and reconciliation receipt](../../docs/NATIVE-BOOK-RETENTION-2026-10-09.md).

## Separate frozen-level retest research

`frozen_retest.py` adds one unregistered research hypothesis, not a replacement
of the native strategies or the compact-context complex. It freezes a breakout
level, waits for a distinct retest/reclaim, consumes each structural event once,
and retains the pinned native crash defense. `frozen_retest_entry.py` checks only
the first strict minute-open against unchanged barriers/costs. It grants no
source authentication, real fill, allocation, or trading authority.

The [pre-run protocol](../../docs/STRATEGY-SELECTION-FROZEN-RETEST-PROTOCOL-2026-10-07.md)
declares one cache-only 300-second census over every 5m slot of the already seen
May 2021/January 2024 episodes. Run a refreshed non-editable wheel's
`python -m adaptive_replay.frozen_retest_census --workspace-root D:\Kairos
--output-root D:\Kairos\runtime\frozen-retest-census-YYYYMMDD-unique` once,
from a runtime directory; existing attempts are never overwritten or retried.
No economics or model API runs; required NEWS/MACRO and later model-test admission
remain separate prerequisites.

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

The roster's `low_cost_pilot` defers the broader event/control set: two episodes,
two preregistered cuts each, at most 20 total paid requests and no automatic
retry/model grid. The approved cumulative $1 pilot ceiling intersects the existing
shared OpenAI $12 cap; it neither adopts nor resets a budget. The four UTC cuts
are now fixed, but accepted sources, one fixed strategy/route identity and
budget/dispatch gates are still prerequisites. Full five-symbol
minute rosters retain explicit scheduled no-call observations. This sparse pilot
is not continuous historical trading or full-system qualification. User approval
of the key reuse and expense limits is not source admission; no paid calls have
been executed and the draft remains non-executable. See the
[source-only preflight receipt](../../docs/HISTORICAL-CONTEXT-PREFLIGHT-2026-10-07.md).

The separate `adaptive_replay.historical_acquisition` helper prepares only the
five-symbol May 2021 monthly bar/funding roster into a **new direct child** of
`D:\Kairos\runtime`. It requires explicit absolute `--workspace-root D:\Kairos`
and `--output-root` arguments; without `--fetch` there is no download or directory
creation. It cannot write into the original Backtest cache or source evidence.
With `--fetch` it permits only twenty fixed official HTTPS archive/checksum GETs,
no redirects/retries, one worker, 10 MiB per ZIP, 2 KiB per checksum, 32 MiB total
downloaded bodies, 16 MiB per decompressed member and one 180-second deadline.
After official SHA/ZIP and the unchanged full input validation, it writes a
create-only `source-summary.json` with counts/hashes and false trading/economic
authority. A failure retains completed verified pairs and has no success
summary. No source gap is filled, retried, resumed or silently relaxed.
This acquisition validates market inputs only, not historical NEWS/MACRO,
model costs, archive authenticity beyond the recorded official-byte checks, or
venue execution. The dated receipt records the single actual attempt; do not
repeat it automatically.

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

## Separate historical pilot: blocked no-call preflight

The [fixed pilot roster](historical-episodes-draft.json) preserves only A and D,
four fixed UTC cuts, twenty underlying paid-attempt maximum, zero retries and
the cumulative USD 1 pilot ceiling intersecting the existing USD 12 campaign.
Owner approval does not supply exact historical NEWS/MACRO or source coverage.

`python -m adaptive_replay.historical_pilot_preflight --workspace-root D:\Kairos
--output-root <new-direct-runtime-child>` is strictly offline and has no provider,
database, strategy, candidate or economic execution. It checks existing five-symbol
market inputs and installed source pins, and retains all 72,000 one-minute cells
with explicit source/scheduling no-call reasons, null candidates and zero cost.
Its successful **preflight** state is `PREFLIGHT_COMPLETED_PAID_RUN_BLOCKED` and
its CLI intentionally exits nonzero. It is not a successful paid A/B run.

`adaptive_replay.historical_context_capture` separately captures nine fixed public
leads into a new runtime child only with `--capture`; without that flag it makes
no request or output. Raw documents and current capture clocks stay unadmitted,
including audit-only future documents and modern deleted-post tombstones.

The [single actual attempts and independent audit](../../docs/HISTORICAL-PILOT-NO-CALL-2026-10-07.md)
are retained. Do not rerun them, overwrite evidence, change cuts, infer zero
candidates, demote required sources to optional or treat these commands as a paid
dispatcher. The required source/strategy/route and durable budget admits remain
separate prerequisites. No blind campaign, primary recovery or venue is touched.

## Local companion pilot cap

`adaptive_replay.historical_pilot_budget` is an offline, standard-library SQLite
helper, not a provider dispatcher. Its fixed USD 1 ceiling and twenty one-shot
cut/symbol slots bind to the unchanged pilot draft SHA. `BEGIN IMMEDIATE` serializes
admission across workers; missing or corrupt ledgers, UUID/plan/roster mismatch,
duplicate slots and exhausted money fail closed. Unknown costs remain reserved.
Known settlement does not restore a consumed slot. Observed overruns are recorded
and seal new admissions, while already-held attempts can still settle, including
multiple overruns, without losing known expenses.

There is no automatic ledger creation, release, reset or retry. No production
ledger was initialized by this development change. The helper is **not** the
authoritative PostgreSQL USD 12 campaign budget, nor global protection across
replacement files or hostile filesystem rollback. A later admitted dispatcher
must bind one externally recorded path/UUID, reserve both caps before each single
underlying attempt and preserve ambiguous reservations. Source, route and strategy
admission remain absent; successful helper tests grant no paid/trading authority.
Git attributes preserve the exact draft bytes across Windows/Linux checkouts;
newline conversion is not an accepted alternate plan identity.

## Bounded ALFRED raw vintage download

`adaptive_replay.historical_macro_capture` captures one fixed public ALFRED
download for CPIAUCSL and the day-before vintages May 18, 2021 / January 8, 2024.
The observed public form uses a read-only data-download POST, no API key or paid
request. The default CLI does nothing; `--capture` requires a new direct runtime
child. TLS, exact response URL, no redirects/retries, a cooperative 20-second
bound, 1 MiB raw limit and 2 MiB expanded ZIP limit apply. ZIP inventory never
extracts filesystem paths or admits versions/coverage into a prompt.

The [single actual download and fresh archive search](../../docs/HISTORICAL-PILOT-ARCHIVE-2026-10-07.md)
are retained. Do not rerun that download or the older preflight/capture. Each
episode must later use only its appropriate vintage column, not the combined
CSV or modern README narrative. NEWS admission and paid A/B remain blocked.

## Local historical pilot integration and price-only SIM

The [local implementation receipt](../../docs/HISTORICAL-PILOT-IMPLEMENTATION-2026-10-07.md)
describes the offline CPI semantic extractor, one-shot paired budget adapter,
immutable native OpenAI review route and full-path injected SDK/SIM tests.
Fixtures are explicitly synthetic; source and authoritative budget admissions
remain separate proofs, and no production ledger or provider is operated.

The separate `adaptive_replay.historical_pilot_sim` command accepts only
`--workspace-root D:\Kairos` and a new direct runtime child as `--output-root`.
It seals fixed A/D price-only diagnostics before native candidate generation,
uses the unchanged prototype at its native 5m cadence and retains all 72,000
original 1m/five-symbol cells. Unscheduled native cells are not called quiet.
Common risk, strict/proxy fills, base/stress costs and original candidate TTL
remain intact. One worker / 900 seconds / no downloads / no provider or database
calls apply. NEWS-blocked model arms stay unavailable, not zero or imputed.
Neither successful software tests nor this diagnostic qualify alpha or LIVE.

The [single actual price attempt and fixed-cut audit](../../docs/HISTORICAL-PILOT-RESULT-2026-10-07.md)
are retained separately. The full price attempt stopped at its 900-second bound
after episode A; episode D is partial, and no global success receipt exists.
Do not repeat, resume or overwrite that attempt. Its declared full denominator
is not a claim that all 72,000 cells completed.

The separate `--cut-audit-only` mode seals a 120-second, create-only audit before
evaluating only the original four review cuts across the five symbols. It runs
no economics, does not retry the full SIM, and marks every other original cell
`NOT_EVALUATED_NOT_IMPUTED_QUIET`. Exact closed prefixes, source equality,
cancellation and final deadline checks apply. Its single actual attempt completed
all twenty cells with no review candidates; model arms remain unavailable.

## Separate compact context-assisted complex

The [new research-only protocol](../../docs/FULL-SYSTEM-EVALUATION-COMPACT-2026-10-07.md)
combines unchanged expanding-prefix breakout and rolling-history pullback/range
with shared crash defense. One strategy-blind joint directional context
assessment supports isolated review/proposal/combined accounts, not two
independent model trials. Deterministic proposal geometry, conflict abstention,
once-measured mapper delay, actual modern expense clocks and common risk remain
separate from model judgment. Neither the old review pilot nor frozen campaigns
are rewritten.

`python -m adaptive_replay.complex_prepare --workspace-root D:\Kairos
--output-root <new-direct-runtime-child>` prepares the exact four-cut/five-symbol
roster from existing cached inputs only. Output names must start with
`compact-context-preparation-YYYYMMDD-`; outputs are exclusive and immutable.
The optional `--archive` requires its exact `--expected-archive-sha256` and never
admits authenticity merely from hashing. There is no paid-run flag, credential
loader, budget creation/reset, provider call or order path. All unevaluated
slots remain unevaluated; sparse cuts are not a continuous campaign.

`complex_dispatch.ComplexAssessmentDispatcher` is a one-shot adapter over the
existing native paired cap. Source, cumulative predecessor, shared-budget
identity and fresh human-confirmation gates default to deny. Quiet slots may
be assessed, but source gaps cannot be bypassed. The cumulative $1/20 attempt
ceiling is reused, not extended. Full-path tests use explicit injected fixtures,
not paid/historical provider or trading proof. Actual NEWS/MACRO admission and
owner confirmation are still required before the later model test.

## Separate fixed failed-breakout reversal diagnostic

The [new pre-run protocol](../../docs/STRATEGY-SELECTION-FAILED-REVERSAL-PROTOCOL-2026-10-07.md)
defines one independent `failed_breakout_reversal_v1`, not tuning of the rejected
frozen retest or an additional live sleeve. Pre-excursion closed channel/ATR,
one/two-bar return, event-extreme stop, opposite-edge target, first consumption,
fresh-channel reset and pinned native crash/cooldown are fixed before real counts.
Raw structural candidates are retained before the unchanged cost/risk hurdles.
First arrival independently binds completed source geometry and accepts only the
first minute OPEN after assumed 100ms completion, never that minute's future HLC.

`python -m adaptive_replay.reversal_search --workspace-root D:\Kairos
--output-root D:\Kairos\runtime\reversal-search-20261007-a` is a separate create-only
offline path after source seal and pre-run review. Six already-seen windows /
five symbols / every 5m cut / unchanged native breakout control / base20 and
stress33 / independent shared accounts are fixed. One worker, cooperative plus
outer hard 600-second cap, no automatic retry, no downloads, no paid API,
no new parameter search, no old receipts/ledger/plan modification. Complete
conditional OHLC reference net, drawdown, mark overruns, natural frequency and
all refusals are diagnostic, never source/venue/alpha/LLM qualification.

The [single completed comparison](../../docs/STRATEGY-SELECTION-FAILED-REVERSAL-RESULT-2026-10-07.md)
retains all 63,360 slots and 24 accounts in 19 byte-bound original pipeline/log files.
It produces 799 raw reversal candidates and 415/318 conditional natural closes at
base/stress, not a qualified winner: losses in the May 2021/June 2022 windows and
aggregate mark-risk overruns remain explicit. Do not rerun or tune this attempt,
splice favorable windows, assume LLM filtering profits or integrate a live sleeve.
Five evidence tests audit the original bytes/counters/ledgers without another
historical replay. No paid model test follows without accepted causal sources,
budget evidence and fresh human confirmation.

## Exact transfer of a preserved public-book observation

`scripts/export_legacy_public_book_tape.py` must run with the preserved private
legacy Python `-I`, never the mutable development environment. It requires four
independently retained complete SHA256 commitments (wheel, exporter, original
implementation, original receipt), verifies the complete installed source
roster against the named wheel before importing the original reader, and
creates one bounded canonical JSON export outside originals and the environment.
It neither captures again nor rewrites an original seal, receipt or timestamp.

`public_book_transfer.import_public_book_transfer` additionally requires the
independently recorded export SHA256. One immutable byte snapshot preserves all
original frames/mappings and admits only unchanged current kernel DTO bytes.
Incompatibility refuses; normalization, resealing and automatic adoption are
absent. The returned exact tape can bind all its frames into `continuous_sim`;
this does not supply bars/news/macro, source authenticity, market completeness,
fills, economics or authority. The current direct original reader must still
refuse a legacy implementation mismatch.

The [actual transfer receipt](../../docs/CAUSAL-SOURCE-OBSERVATION-2026-10-09.md)
records all 1,280 frames and matching current input mapping on two private
installed-wheel Python versions. Do not repeat the original capture or treat
this 30-second sampled observation as a historical trading campaign.

## Additive V3 actual-creation clocks

`hypothesis_v3` has separate types and fold, not a migration or backdated V2
surrogate. `origin_cut_ms` pins the original price slice, parent decision,
anchor/reference and all exit geometry; `created_ms` records actual materialized
input/proposal readiness. Policy must be sealed by the origin cut and validity
remains origin-cut plus predeclared lifetime. Delays never renew it. Typed
context proposals bind actual OpenAI requested/completed/captured clocks and
input/response/model-config hashes; supplied hashes remain caller attestations.

The minimal contract refuses creation after the first post-anchor minute has
completed rather than skipping an earlier possible trigger/stop. Every minute
observation starts from the origin cut; first-trigger consumption, original
protection, quote/review freshness and native planning/risk assumptions remain
unchanged. A cut-time assessment cannot impersonate a later quote-bound review.

This pure contract passes 53 synthetic clock tests per Python version. It is
not itself a prospective source/frame producer, portfolio intake adapter or
fixed four-arm driver. Complete immutable source-prefix and
earliest eligible receipt selection remain driver obligations. No historical
model run, admitted source set, winner or trading authority follows.

## Durable matched V3 research journal

`hypothesis_journal_v3` separately seals static arms/policies/source profile
before a cut, then enrolls actual post-cut plans without inventing future hashes.
Its matched batch shares unchanged market/quote receipts, but retains each arm's
original review identity and actual decision clock. No-review controls do not
inherit model latency; reviewed arms cannot replace an expired quote. Full arm
rows commit atomically and exact redelivery returns their original receipts.

Reopen requires the strongest independently retained `JournalCheckpointV3`;
self-consistency alone cannot detect an older restored database. Instance
serialization preserves checkpoint handoff, and byte bounds are enforced
before commit. Caller-attested review/source bytes are not source/model
authentication or early physical execution. Counterfactual enrollment does not
grant strategy-only routing to model-originated proposals.

The [journal acceptance and remaining integration boundaries](../../docs/PROSPECTIVE-MATCHED-JOURNAL-2026-10-09.md)
record actual gates separately from missing raw REST/finality evidence,
prospective frame/provider receipts, full five-day continuous horizon
and the fixed four-arm economic comparison. No paid calls or trading follow.

## Original V3 intake into the bounded portfolio

`ContinuousSimPortfolio.intake_v3` now accepts the original matched V3 journal
and exact first-trigger receipt under its separately sealed producer/origin
configuration. It does not cast V3 into V2. Full normalized candle originals
bind the anchor and complete prefix through the trigger at each original
shared availability clock; context-anchor readiness is checked at the actual
proposal request. A context-proposal counterfactual cannot enter strategy-only.

The common financial fold retains original stops/targets, partial fills,
liquidity, risk, natural exits and restart. Consumed decisions with unavailable
data poison coverage and keep net results null, including through restart;
known source-complete veto remains a known refusal. The immutable B installed
Python 3.11/3.14 suites each pass 1,627 tests with four platform skips, and all
67 installed adaptive sources match their retained wheel.

See [the scoped implementation and receipt](../../docs/PROSPECTIVE-PORTFOLIO-INTAKE-2026-10-09.md).
The existing one-day/full-state/input caps are not silently enlarged. Accepted
historical sources, full five-day non-resetting storage/source segments,
prospective frames and the fixed four-arm economic driver remain open. No
historical model run, winner, admission, paid call or trading authority follows.
