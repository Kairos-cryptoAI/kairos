# Fixed scenario vs immediate-entry price-only diagnostic

Pre-run protocol, 2026-10-08. No outcome has selected these dates or rules.
This is an independent opt-in research diagnostic, not a rewrite or retry of
any old comparison, full-system pilot, Trial 15 or V4/V5 evidence.

## Fixed question and denominator

Measure the consequences of the new closed-confirmation scenario policy against
the unchanged immediate candidate of `compact_context_complex_v1`. Use only the
first six UTC hours of June 13, 2022 (00:00 inclusive to 06:00 exclusive), inside
an already seen June 2022 development window. No result-dependent date selection.
Every 5m cut across BTC/ETH/SOL/BNB/XRP gives 360 scheduled native cells. The full
1m roster has 1,800 cells; non-native cuts are unscheduled, not quiet. Keep every
quiet, conflict, source error, unsupported template and excluded candidate.

Generation uses one actual `technical_scenario` call per native cell, the exact
54h expanding prefix origin, rolling native adaptive history and unchanged crash
defense. One immutable scenario per unchanged distinct native parent, no retries
or resets after its terminal outcome. A retains its original trailing/SL/TP/TTL.
B refuses unsupported trailing/regime/direction explicitly, never alters A.

This v1 has a known structural limitation before measuring returns: a native
60s expiry precedes the first later closed 1m observation; native default breakout
trailing is unsupported. Thus an all-no-entry B result is possible and not proof
that confirmation creates alpha or that this design is ready to integrate.

## Clocks, sources and economics

MARKET only; archive candle hash binds each creation anchor and later observation.
Creation receipt clock is the cut. A completion is cut+100ms. Later complete
minute observation is close+1+100ms; B execution preparation adds another 100ms.
All are declared event-time reconstruction assumptions, not historical local
receipt or measured latency. No observation uses future outcome data at an
earlier cut. Default LLM-reviewed/context-proposal arms, NEWS/MACRO, provider
expense, real quote/fill/liquidity and full-system economics remain unavailable.
`require_review=False` names only the isolated price-only control, never Risk
permission. No historical receipt or default ALLOW response is fabricated.

Independent equal USD 10,000 accounts use existing `COMMON_COST_RISK_V1`, all five
symbols in fixed order, unchanged 0.25% per-trade/1% total open-risk admission,
25% per-symbol notional and 1x gross caps. Preserve the common base20/stress33
planning cost sets, fees, signed archived funding, gaps and protective ordering.
Both strict observed-minute-open timing and conditional intrabar-open proxy are
reported separately; neither is a new venue execution proof. No trade is entered
in the three-hour exit tail. Late scenario confirmations remain explicit rather
than being silently omitted by the account engine. No forced closes.

Primary statistic is full-account B-minus-A final equity for each cost/mode,
not summing selected historical trade PnL. Descriptive matches distinguish missed
actual closed A winners, avoided actual closed A losses, flats, non-fills,
rejections, open positions and unavailable coverage. Unsupported-policy exclusions
stay their own subgroup. Expenses unavailable to this reconstruction are null,
not free; complete-system net results are null. No annualization, compounding
omitted periods, winner selection, tuning or blind-campaign credit.

## Execution and acceptance

The [runner](../development/adaptive_replay/adaptive_replay/scenario_compare.py)
loads checksum-verified existing FULL_KLINE/funding cache only. Source/dependency,
native default and byte/normalized-input identities are checked before and after.
Seal protocol/source receipts before native generation. Output is a specifically
named new direct `D:\Kairos\runtime` child; reject links/junctions and existing
outputs. One worker, cooperative plus outer hard 600-second limit; no retry,
resume, overwrite, downloads, providers, DB, services or venue operation.

Run only a refreshed non-editable wheel after tests and source review:
`python -m adaptive_replay.scenario_compare --workspace-root D:\Kairos
--output-root D:\Kairos\runtime\scenario-comparison-20261008-a`.

Pre-run engineering verification: refreshed non-editable Python 3.11.15 and
3.14.7 wheels each pass 880 tests, with two unchanged platform symlink-fixture
skips. All ten new comparison/trailing-bridge cases pass. Ruff lint/format,
unchanged dependency lock, wheel/sdist build, Meta static/local Markdown links
and checkout-regression checks pass. Installed comparison module SHA-256 equals
checkout on both versions:
`da04df0afa22ad700a1a69a2e351d31cb29acf57a6e8d06a2c850425de6cbfb1`.
Independent source/protocol review found no remaining causal/accounting blocker
within this deliberately narrow price-only diagnostic; it grants no economics.

A stopped attempt remains stopped and preserved. Diagnostic acceptance
requires a `COMPLETED_PRICE_ONLY_DIAGNOSTIC_NOT_QUALIFICATION` result with the
matching unchanged `after.json` receipt and byte-bound file inventory. Any
`failure.json` or `hard-timeout.json` invalidates the attempt, including partial
numeric account files that may have been written before stopping. Such partial
files are not economic evidence and must never be cherry-picked.
Software/diagnostic completion
never promotes `TECHNICAL_PAPER_READY`, `PAPER_QUALIFIED`, `ALPHA_READY`, or
`LIVE_READY`; `STRATEGY_POLICY=REJECT_ALL`, trading authority NONE.
