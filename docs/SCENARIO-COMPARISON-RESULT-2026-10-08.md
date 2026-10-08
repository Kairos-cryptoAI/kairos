# Scenario comparison: completed narrow diagnostic, no confirmation pass

Date: 2026-10-08 Europe/Moscow. Classification: SEEN_PRICE_ONLY_DIAGNOSTIC.
The single attempt follows the unchanged
[pre-run protocol](SCENARIO-COMPARISON-PROTOCOL-2026-10-08.md), frozen and GPG-signed
at main `60b1296cbfcc79a4d4cca024b4bb005cc43c4f0b`; implementation is
`52e742d84d1458f8de3a3ea2019f75c26dd55569`. It completed in **184.203 seconds**,
without retry, tuning, downloads, providers, venue requests or runtime operations.

## Actual coverage and the important negative finding

All 360 scheduled five-minute cells / 1,800 full-minute cells completed across
BTC/ETH/SOL/BNB/XRP, June 13, 2022 00:00-06:00 UTC, with the fixed 54h causal
prefix and 3h exit tail. There are 324 native quiet cells and 36 native candidates,
no unavailable native cells and no entry-window spillover. Required price data
being available does **not** mean NEWS/MACRO/model/venue sources are qualified.

Every actual candidate is unchanged native `trend_breakout_v1`, retaining its
original five-minute expiry and trailing exits. New scenario v1 prepares **zero**
plans and emits **zero** candidates:

- 25 candidates: native adaptive context is UNCERTAIN; outside scenario v1's
  explicitly supported regimes, not automatically inferred bearish/crash alpha.
- 11 candidates: native adaptive context is BEAR, but the parent's trailing
  protection is unsupported by scenario v1. A keeps that trailing protection.

Consequently this run does **not** test profitable closed-minute confirmation:
there were no supported plans to confirm, invalidate or expire. It measures
whole-policy abstention consequences. The separate 60s adaptive expiry issue is
proved by source/unit tests, not an observed expiry count in this attempt;
there were no native adaptive candidates here. Nothing is silently relabelled
as a review rejection or a successful protective filter.

## Conditional price-only accounting

A is immediate native entry; B is the new price-only scenario policy with
`require_review=False`, not the default complete reviewed system. Each independent
account starts at USD 10,000. Same common risk, original barriers/trailing, fees,
funding, settlement and base/stress cost assumptions apply to both. All reported
entries naturally close; no forced liquidation or blind-trade credit occurs.

| Cost / timing model | A natural closes | A trading-net return | B natural closes / return | B minus A final equity |
| --- | ---: | ---: | ---: | ---: |
| Base / strict minute-open | 14 | -0.60924% | 0 / 0% | +USD 60.92 |
| Base / intrabar-open proxy | 4 | +0.16194% | 0 / 0% | -USD 16.19 |
| Stress / strict minute-open | 7 | -0.22299% | 0 / 0% | +USD 22.30 |
| Stress / intrabar-open proxy | 0 | 0% | 0 / 0% | USD 0 |

In the same row order, excluding all candidates misses 6/2/4/0 actual closed A
winners and avoids 8/2/3/0 actual closed A losers. These are descriptions of A's
actual conditional account outcomes, not summable causal attribution. Other
original candidates are retained as A admission rejections. The four rows are
alternative cost/timing models of the same episode; do not pool their trades,
sum/compound returns, annualize or select the most favorable row.

The proxy-positive row also shows why the positive strict-row B-minus-A deltas
are not proof of a better trading system: B simply never trades and also loses
profitable opportunities. Timing resolution changes the conclusion. Neither a
closed candle nor a minute-open approximation proves bid/ask, liquidity, partial
fills, venue basis, protective latency or executable real profits.

Ledger reconciliation error is at most about USD 3.3e-12. No modeled mark-risk
ceiling overruns appear in these accounts; that observation is not a live risk
qualification. Model/feed expenses and complete-system net economics remain
**null**, LLM arms remain `UNAVAILABLE_NOT_EXECUTED_NOT_ZERO_PNL`; provider calls
are zero. Model filtering or generated proposals were not evaluated.

## Original evidence and verification

The immutable original runtime attempt is retained at
`D:\Kairos\runtime\scenario-comparison-20261008-a`. Its
[published exact-byte receipt set](../development/adaptive_replay/evidence/scenario-comparison-2026-10-08/result.json)
has 16 files: result plus all 15 manifest-listed receipts, complete denominators,
paired native outcomes and account/matching ledgers. Git attributes prevent
newline conversion. All hashes match, source receipts before/after match, and
there is no failure/hard-timeout marker. A separate agent verified those facts,
candidate family/TTL/trailing identities and all eight account ledgers without
another replay. The comparison did not reuse previous economics or read a frozen
blind ledger.

- Result SHA-256: `e03238519765b9d2368c1c3da9408b9eaf0e94811a5d9059bdec12be55fbf697`.
- Canonical sealed protocol SHA-256: `6acfa15dbdfbd2d8c131e18ebb2617481cfb883dbdf0e2c1d4b6f515edae4b19`.
- [Exact-source fixture CI](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37778968129):
  all four Windows/Linux x Python 3.11/3.14 jobs passed.
- [Meta CI](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37778968064) and
  [CodeQL](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37778967502): passed.

Four added byte/roster/account audit tests verify the published receipt set
without replaying prices. Together with the comparator and bridge tests, all
23 focused cases pass on the installed Python 3.11 and 3.14 wheels. Pre-run full
suites each passed 880 tests plus two existing symlink-fixture skips; no new
historical or model attempt follows from this evidence-only verification.

The complete published code/test/evidence set at GPG-signed main
`df79934be5855d79503e5b8749a5c03d48bc520f` subsequently passed
[hosted fixture CI](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37781002202):
**886 tests passed in each** Windows/Linux x Python 3.11/3.14 job, with no skips.
[Meta CI](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37781002110) and
[CodeQL](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37781001644) also
passed on that exact revision. This later receipt records verification only;
it changes neither the preregistered protocol nor the original attempt's bytes.

## Decision and next question

**Do not integrate or qualify closed-confirmation scenario v1 on this evidence.**
It has no supported historical opportunity in the fixed slice; improved return
in an abstaining account is not evidence of confirmation alpha. Keep the original
strategies, their trailing/TTL and this attempted v1 unchanged as separate evidence.

Before another experiment, the next design question is to distinguish a market
hypothesis's validity from a short-lived executable candidate/quote and specify
how unchanged trailing protection survives a later entry. This is a separately
versioned research design question, not permission to extend old TTLs, remove
uncertain cases, change the date roster, retune after these results or rerun this
attempt. Default full-system NEWS/MACRO/review and their actual costs still need
separate causal source/model admission. No alpha or monthly return is proven.

`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`, trading authority NONE.
