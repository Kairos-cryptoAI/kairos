# Separate PRICE_ONLY slow-reference protocol — 2026-10-07

This is an explicit field-scope amendment before a new economic attempt, not
a repair or retry of the failed [FULL_KLINE plan](STRATEGY-CALENDAR-RESULT-2026-10-07.md).
The user asked to continue strategy selection. Original failed inputs, plan,
attempt and frozen campaigns remain immutable. No news/LLM/system integration,
parameter tuning, paid model calls or trading follows.

## What the source investigation actually established

All five problematic monthly ZIPs match newly retrieved official Binance
checksum sidecars. A create-only public HTTPS fetch retained nineteen daily
ZIPs and their sidecars; all nineteen match the official SHA. All 14,400 missing
SOL/XRP symbol-minutes are present in these daily archives. No original cache
file was overwritten. Daily/monthly are the same venue/product, not independent
market observations. See [Binance public-data documentation](https://github.com/binance/binance-public-data).

The XRP 2023-11-30 12:35 UTC volume/quote/taker inconsistency appears identically
in monthly, daily and a three-row public USD-M futures REST sample. REST does
not correct or replace this row, and does not independently authenticate prices.
FULL_KLINE continues to reject it. No volume-dependent strategy, adaptive
qualification or production loader may inherit PRICE_ONLY acceptance.

The original retrieval helper had a coverage limitation: it loaded only five
problematic monthlies, leaving four adjacent March control comparisons
unexecuted. Its original receipt is retained without being patched or rerun.
The separate composition checker binds its downloaded bytes and compares all
eight adjacent controls against the byte-bound complete monthly audit: 1,440
rows each, all twelve numeric fields with exact Decimal equality. The November
XRP daily matches all 1,440 raw rows too, including the quarantined row.

The first input-only acceptance invocation used nonexistent cache directories;
its failure is preserved and produced no native generation or economics.
The corrected, source-only invocation used the existing `data/historical` and
`data/historical-factors` directories and completed in 19.157 seconds. This is
not a second economic attempt. No hypothetical corrected volume was inserted.

## Accepted contract and exact consumer scope

[price-reference-plan.json](../development/adaptive_replay/price-reference-plan.json)
allows only unchanged `right_tail_trend_v1`, `regime_aligned_right_tail_v1` and
their `COMMON_COST_RISK` evaluator. A uniform pinned `PRICE_ONLY` projection is
applied to every candle, not selectively to XRP. OHLC and exact minute clocks
remain unchanged. Volume/quote/taker zeros mean **NOT_EXPOSED_PLACEHOLDER**, not
observed zero. The native generators, IDs/features and evaluator decisions
must be invariant to valid changes in optional fields and this projection.
Aggregation may sum placeholders and validation may inspect them; neither is
claimed literally never to read those fields.

Only the exact missing daily rows are added, with original twelve-field row
lineage. There are zero replacements and zero changes to existing monthly
prices/clocks. The one byte-bound XRP optional-field defect is explicitly
quarantined while its original price/clock is retained. Any unknown defect,
NaN, malformed CSV/clock, missing minute or raw-field overlap conflict fails
closed. Existing FULL_KLINE parser and its strict tests are not relaxed.

The input-only acceptance binds 255 monthly bar archives, 255 funding archives
and nineteen daily archives; 11,181,600 source minutes have complete price
coverage. Its exact uncompressed SHA is
`130935ccfa310d656b22135c0e18ead69f20d00250d39066eabbb5ff283e961e`.
The [retained evidence directory](../development/adaptive_replay/evidence/source-qualification-2026-10-07)
contains the original retrieval/helper/REST/failure and a losslessly compressed
acceptance with all added-row lineage. Acceptance validates current funding
bytes before/after; equality to an older complete pre-correction funding
inventory was not proven and is not claimed. SOL's fixed schedule exception
and actual funding timestamps/rates remain unchanged.

## Economics fixed before this attempt

All [original calendar rules](STRATEGY-CALENDAR-PROTOCOL-2026-10-07.md) remain:
five symbols, full UTC years 2022--2025, native defaults, 35-day causal prefix,
72h natural exit tail, strict observed next-minute 01:01 entry, 100ms modeled
completion, both 20/33bps cost scenarios and unchanged fixed risk/stop/net-RR.
Every year/arm resets its shared $10,000 account. Quarterly same-origin prefix
checks and the independent 200-close regime arithmetic are unchanged.

The same prespecified stress/activity/all-year Pareto rule applies. No rule,
year, asset, fee or parameter is selected after inspecting annual returns.
Full-calendar prior exposure remains disclosed: not unseen OOS, CAGR, a
continuous investable equity curve or a final adaptive/LLM strategy selection.

Before generation, verify **every** accepted raw ZIP and sidecar. Seal the
source acceptance, plan, immutable dependencies, native/transitive helpers,
projection, funding and evaluator sources; recheck all after completion.
One worker, the same cooperative 1,200-second bound, cache-only, one new
economic attempt. Failure/deadline retains partial evidence without nomination
from incomplete years; no automatic retry, wider bound, alternative source or
performance-driven repair follows. Independent ledger arithmetic is required
before interpreting a completed result. A reference nomination is not alpha.

`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL` remain unchanged.
