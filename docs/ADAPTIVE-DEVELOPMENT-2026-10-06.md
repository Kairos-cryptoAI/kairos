# Bounded adaptive development receipt — 2026-10-06

## Scope and authority

This is the first bounded historical diagnostic of the selected
`adaptive_pullback_range_v1`, not strategy selection, economic qualification,
model-route qualification, a blind evaluation or enrollment of a new campaign.
No thresholds, dates, fees or strategy variants were selected using its returns.

Trial 15, V4/V5, the frozen Backtest repository, ledgers and evaluators are
unchanged. No paid API/model calls, exchange calls, trading, primary database
mutation, consumer starts or Docker PAPER starts were performed. All four
readiness values remain `false`; policy is `REJECT_ALL`. No blind results were
read, and no forward days or trades were credited.

## Source and protocol

- Replay implementation: signed main commit `b18765c8d4762b9e15b0af722e87727859fa92ce`.
- Funding-clock/CI correction: signed main commit `91b0b80ad95b1c7a2a8a74e445aaf14a2559f0a6`.
- Strategy source: `cde8e9c00af0cc19848e800ee76472a800a5fd5d` (0.2.12).
- Strategy code/detector SHA-256: `836391ab708d4dc9bd4957c68f00724683569b7d5584debb1c368016d57ff0d5`.
- Strategy configuration SHA-256: `51781e00bee3664f260ff826c821234073b7a40deb1b7239e39f517be885901b`.
- Corrected development plan SHA-256: `ad07e992a1440f459acb7b8cdb621a54c70ad1119ee9af7f37aceb6966d69f0c`.
- Historical-run uv lock SHA-256: `853537cbcd261b9712681d4cdd91e08fb9f942f2524e40da3b92005cb54dd583`.
- Post-run patched-test-tooling commit: `132a6b4425dd507a6dfab4dacf24c56e2c7f7a33`.
- Current uv lock SHA-256: `267f52f7c066b1b636ac6b076715099cef825ec0004073cb70db275d5851a082`.

The [fixed plan](../development/adaptive_replay/plan.json) uses five assets,
54h causal warmup, four disjoint three-day UTC entry windows, exactly 3h exit
tail, one worker, a one-hour wall limit and $10,000 reset for each window.
Omitted dates are not compounded. Windows were fixed before any economic output:

| Window | Inclusive start | Exclusive end |
| --- | --- | --- |
| late_2021 | 2021-11-07 | 2021-11-10 |
| early_2022 | 2022-02-05 | 2022-02-08 |
| may_2022 | 2022-05-09 | 2022-05-12 |
| june_2022 | 2022-06-13 | 2022-06-16 |

These calendar diagnostics are not unseen or representative annual alpha/crash
validation. The strategy supplies each causal regime label from closed bars;
calendar window names never supply regime evidence.

This is an isolated installed **non-editable** replay wheel, not a new runtime
service. It reuses pure frozen Backtest parsing/risk arithmetic with explicit
current Core/Quant/Strategy/Persistence overrides: a separate development
dependency projection, not the frozen campaign environment. Exact dependency
revisions and installed module hashes precede and follow the run.

## Preserved initial failure

`D:/Kairos/runtime/adaptive-development-20261006/bounded-20261006-a` is retained.
It finished at `2026-10-06T04:38:21.683489Z` in 3.343 seconds with all four windows
blocked before economics. Its plan SHA was
`56eeef38d6cbcce735d503fa0666b387d972eb97fa5cfb901afcb65ed2412813`.

The loader incorrectly required funding `calc_time` to equal nominal eight-hour
boundaries to the millisecond. Native cached timestamps were offset by small
positive milliseconds. No return, candidate selection or strategy alteration
motivated the correction. Coverage now requires exactly one interval-8 event per
nominal bucket within its first minute; missing/duplicate buckets, wrong cadence
or offsets beyond that resolution fail closed. Raw timestamps are never rounded
or backdated. Funding and entry clocks are merged; funding is first on equality,
and events after gap exits/holding deadlines cannot charge a closed position.

`ARCHIVE_CALC_TIME_ENTITLEMENT_PROXY` is explicitly an assumption: equivalence to
the exchange API's `fundingTime`, actual cash settlement and historical local
availability has not been proved. Candle open is not a venue mark price. The
one-minute acceptance bound is this replay's price-resolution rule, not an
official exchange timing tolerance.

## Execution and economic limitations

The unchanged strategy's lifetime ends at eligible minute open +59,999ms. With
declared 100ms pipeline completion delay, `STRICT_MINUTE_OPEN` cannot observe a
minute-open quote inside that lifetime. A no-fill outcome must not be marketed as
zero-risk profitable trading or repaired by backdating/extending expiry.

`INTRABAR_OPEN_PROXY` uses assumed +99ms entry time and that minute's open plus
adverse execution displacement. No quote at +99ms was observed. Full fill,
capacity, partial fill, protection latency and liquidity remain unqualified.
This conditional approximation is **not** a guaranteed PnL lower bound.

Base/stress planning allowances are 20/33 bps. Fees are charged each side;
spread/slippage/latency appear once in modeled fills. Carry/uncertainty reserve
admission headroom, not additional cash charges; native signed funding rates are
separate. Future rates never size earlier entries. Net figures exclude unknown
model/live-feed costs, so complete all-in economics remain unavailable.

Each account shares all five symbols with fixed tie order, one position per
symbol, non-netted ≤0.25% per-trade/≤1% aggregate stop-risk, ≤25% per-symbol
notional and ≤1x gross **at admission**, after fees/adverse mark debit. Gap losses
and subsequent mark-time ceiling overruns are retained and reported. Unknown
intrabar profits cannot finance earlier entries. An inside-minute timeout keeps
its reservation until bar-close processing: conservative admission blocking,
not proof of exact real-time timeout execution.

SL wins ambiguous bars; entry-minute TP is suppressed; deadline-minute TP cannot
supersede a timeout. Minute MTM drawdown and within-minute adverse-envelope bounds
are separate, not observed tick drawdown. Terminal exposure stays visible rather
than being forcibly liquidated or counted as naturally closed campaign trades.

## Matched A/B boundary

All scheduled five-minute slots retain a common causal cut, full input-window
hash and immutable candidate identity, including valid quiet slots separately
from unavailable/warmup slots. Accounts are independent and deterministic.
Review receipts bind unchanged candidate/source/response/cost/completion clocks;
a late model cannot inherit the baseline fill time. Fixture responses cannot
become observed economics.

Historical LLM review and proposal arms are `NOT_CALLED` with null economic
results and null costs, not a measured free service. Point-in-time news/provider
responses are absent, and pretrained knowledge of historical events would risk
future-event contamination. This prepares matching; it does not execute or
accept the existing sealed matched A/B campaign.

## Current verification

Local installed-wheel Python 3.11 tests: **80 passed**, including raw funding
entry offsets +1/+18/+99/+100ms, exact deadline/deadline+1, gap exit and timeout
before subsequent funding. Ruff lint/format, locked dependency validation and
Meta static/local Markdown checks passed.

The [adaptive fixture CI](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37415363080)
passed Windows/Linux × Python 3.11/3.14 on the funding-clock commit. The first
workflow was invalid before jobs because `runner.temp` was used in job-level env;
GitHub's [allowed context matrix](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts)
excludes `runner` there. The environment now
uses `github.workspace`. This was a CI expression correction, not relaxation of
tests.

The new development lock initially selected pytest 8.4.2, affected by
[GHSA-6w46-j5rx-g56g](https://github.com/advisories/GHSA-6w46-j5rx-g56g).
After the historical run ended, this project's test requirement was raised to
`>=9.0.3,<10`; the locked version is now **9.1.1**. The original run environment
and receipts remain intact, and a separate current environment again passed all
80 installed-wheel tests. Only pytest/test-lock metadata changed; strategy,
replay modules, windows, costs and runtime dependency revisions did not. The
historical run's old lock hash must not be presented as the current test lock.
The [patched-tooling fixture CI](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37417728535)
passed all four Windows/Linux × Python 3.11/3.14 jobs on `132a6b4`; Meta validation
and the new dependency graph also passed. GitHub marks the pytest advisory fixed
at `2026-10-06T05:17:39Z`. Runtime dependencies were not upgraded.

## Completed historical diagnostic

`bounded-20261006-b` completed at `2026-10-06T05:13:26.691246Z` in 1,551.609 seconds
(25.86 minutes), within its fixed one-hour bound. All four five-symbol windows
passed required checksum/CRC, FULL_KLINE row/gap and native funding coverage
checks. There were 17,280 complete scheduled slots, no warmup/unavailable slots,
12 candidates and 17,268 valid no-intent observations.

The [exact result](../development/adaptive_replay/evidence/2026-10-06/result.json),
[initial blocked result](../development/adaptive_replay/evidence/2026-10-06/initial-blocked-result.json)
and per-window input/matching/nonzero-trade ledgers are retained in Git without
copying raw market archives or the full decision tape. The latter remains in
`D:/Kairos/runtime/adaptive-development-20261006/bounded-20261006-b` with its
per-window hashes in the result. Published result SHA-256:
`f73c246d6a2fdd17538ed10911223b386e1a3da07d1e0a1365153d9f21f0ce0c`.
All 15 published evidence files were independently SHA-256 compared with their
original runtime files and match byte-for-byte. Neither old attempt was removed
or rewritten.

The following table is **INTRABAR_OPEN_PROXY**, not observed real executions.
Each percentage is one independent three-day $10,000 window, not a monthly or
annual return. DD is closed-minute MTM, not tick drawdown.

| Window | Candidates | Base closed trades | Base net % | Base DD % | Base PF | Stress closed trades | Stress net % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| late_2021 | 0 | 0 | 0.0000 | 0.0000 | N/A, no trades | 0 | 0.0000 |
| early_2022 | 0 | 0 | 0.0000 | 0.0000 | N/A, no trades | 0 | 0.0000 |
| may_2022 | 6 | 5 | -0.4731 | 0.9911 | 0.4375 | 4 | -0.8376 |
| june_2022 | 6 | 5 | -0.2634 | 0.9240 | 0.6308 | 3 | -0.3436 |

Baseline naturally completed ten trades; stress completed seven, not ten reused
fills. The shared intent tape is identical, but each scenario independently
applies fill-cost and portfolio gates. Baseline entries across the 12 entry days
were `0,0,0 / 0,0,0 / 4,0,1 / 3,2,0`: eight zero-entry days. Baseline's May gate
rejected one candidate for aggregate risk; June rejected one because that symbol
already had a position. Stress rejected two candidates in each active window for
fill-price net reward/risk; June additionally rejected one overlapping position.

All 16 account/scenario reports reconciled their economic ledgers within
`1e-7 USD`; none had terminal positions, forced settlement, a reported mark-risk
or gross-leverage ceiling overrun, or a realized loss over reserved stop-risk.
Both positive-rate and negative-rate funding cash behavior are covered by
synthetic boundary tests; no historical nonzero trade crossed a charged funding
event. This particular replay therefore is not observed cash-funding execution
qualification.

In `STRICT_MINUTE_OPEN`, all 12 generated candidates lacked an observed quote
before expiry at the assumed completion latency; no trades occurred in either
cost scenario. This diagnoses the archive's execution-time resolution, not proof
that a live book cannot fill within the intent lifetime.

## Interpretation and next boundary

The chosen development strategy can naturally produce both active and quiet
days, and common-account refusals operate. It has **not** demonstrated the desired
activity across regimes or a profitable edge: the two quiet windows have no
economic evidence, and both active bearish/crash calendar windows lose under
base and stress assumptions. Zero trades are not profitable trades. Ten baseline
trades on known development slices cannot prove future failure or success, nor
support a monthly return estimate. Required positive net crash/bear evidence is
not supplied by this diagnostic.

A read-only source review found no systematic scheduling/slicing defect behind
the quiet windows. The runner passes exactly the previous 3,240 closed bars and
checks `decision_ts = eligible_minute - 1`. Nine structural matches in the two
quiet windows reached barrier/cost checks: eight were rejected for planning
cost headroom and one for ATR geometry. Other slots did not complete the fixed
regime/setup conditions. Latency/funding/fill rules cannot explain zero generated
candidates because generation precedes execution.

Do **not** enroll/freeze this result as accepted alpha or assume that an uncalled
LLM would rescue it. Preserve this ONE-version result rather than replace dates,
weaken costs/risk or run a threshold grid until a positive result appears.
Further design/economic work must be explicit and separately versioned; matched
model arms require independently source-qualified point-in-time context,
observed attempt/completion/cost receipts and a preregistered causal evaluator.
No real matched A/B/model qualification or independent blind gate has passed.
