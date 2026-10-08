# Scenario-based trading logic: research engineering rework

Date: 2026-10-08 Europe/Moscow. Classification: ENGINEERING_ONLY.
This follows the owner's request to rework trading around professional-style
scenario discipline. It does not claim professional-level returns or any
profitable selected strategy. Current runtime source authority and readiness
remain [current-release.json](../config/current-release.json).

## Implemented, not just a concept

The additive [scenario engine](../development/adaptive_replay/adaptive_replay/scenarios.py)
and [native/context bridge](../development/adaptive_replay/adaptive_replay/scenario_bridge.py)
are in the existing isolated development package. No runtime consumer uses them.
They call the unchanged native compact technical decision and context-direction
mapper rather than replace every strategy or retune their old observations.

| Stage | Implemented meaning |
| --- | --- |
| Hypothesis | Exact parent candidate, symbol, direction, regime, closed creation anchor, source-set/context hashes and required source identities |
| Waiting | No candidate emitted; the model's directional idea is not market confirmation |
| Confirmation | A later contiguous closed 1m close exceeds the original reference for long, or falls below it for short; not a calibrated alpha claim |
| Invalidation / expiry | Frozen stop-level breach wins an ambiguous candle; original deadline uses actual observation time, not backdated event time |
| Review | Default requires ALLOW for the exact scenario, direction and current context; completion cannot precede its own source capture |
| Entry feasibility | Unchanged stop, target, holding duration and expiry are checked against the later reference, including native planning cost/RR/stop limits and frozen ATR when supplied |
| One opportunity | First structural confirmation consumes the scenario even on VETO/DEFER, unavailable context or failed cost/geometry checks; no later resurrection |
| Evidence | Immutable, linked per-observation outcomes; exact duplicate delivery collapses, conflicting receipt/review bytes are refused |

Missing market evidence or a skipped confirming minute terminates as BLOCKED /
UNAVAILABLE, not a healthy quiet day. Missing news/macro/review at the first
otherwise valid trigger retains unavailable coverage and emits no candidate.
Required sources are explicit; a context-led proposal requires both NEWS and
MACRO. Every supplied source keeps event, trusted local receipt and capture
clocks. Publication/event time alone does not establish availability.

BULL permits long, BEAR short, RANGE either direction in this version. CRASH,
UNCERTAIN, CHOP and implicit countertrend are not newly admitted. Existing native
crash research remains intact and independent. An opposing review cannot flip a
technical candidate; a new direction requires its own separately bound hypothesis.
Unsupported trailing templates are refused rather than silently rewritten.

## Scope and important limitations

The rule above is **one new interpretable confirmation hypothesis**, not a claim
that all good traders use it, that it improves returns, or that current weak
strategy economics have been solved. No parameter search or economic result
motivated these rules. The small existing technical shortlist stays provisional.
No date, cost, risk ceiling or old result is changed to obtain a positive outcome.

The old mapper's immediate candidate and old full-system result are preserved.
The new context bridge prepares a waiting scenario with the same price geometry;
it cannot create RiskTradeDecision or call an exchange. The technical bridge
returns the original native decision alongside the distinct scenario preparation.
Default runtime registries, canary barriers and release pins do not change.

Later closed-minute confirmation often cannot fit a native **60-second** lifetime:
the first subsequent minute is observed after its last eligible millisecond.
This correctly expires the opportunity, rather than extending the parent's
deadline or inventing an intra-minute quote. Observable intraday sources and a
separately specified execution contract are still necessary to evaluate that
family fairly. These mechanics do not solve the recorded archive limitations.

The later candle close is a planning reference, not an observed bid/ask, a fill
or a liquidity guarantee. The 20bps native planning allowance remains an
assumption. Fees, funding, spread, slippage, delay and model/feed expenses still
belong to a separately admitted matched economic evaluator. Hashes/receipts
check caller-input consistency, not publisher authenticity or paid inference.
There is no durable scenario store or exactly-once external-effect proof here.
The bounded fold accepts at most 60 observations; duplicate replay is logical
idempotency only. New scenario creation/reset across a whole market tape remains
an explicit future generator-policy requirement, not a license to manufacture
new IDs after a refused trigger.

`require_review=False` is a named offline strategy-only comparison control. It
does not bypass the real Risk Manager. All candidates still require independent
account, source, portfolio, venue, operator and execution admission. Maximum
0.25% per-trade and 1% aggregate open-risk ceilings are not increased; model
confidence is never sizing or leverage authority. No daily quota or fixed-return
target is introduced. Entry lifecycle ends at consumed/invalidated/expired/
blocked; position protection and reconciliation remain the existing separate
Execution responsibility.

## Verification and next evidence

New offline tests cover actual context-mapper preparation, native candidate
preservation, explicit quiet slots, long/short confirmation, exact ALLOW binding,
veto/defer/opposition, causal capture clocks, original expiry, stop-before-trigger,
cost/ATR rejection, first-trigger-only consumption, gaps, prefix causality and
conflicting duplicates. Independent source review found two implementation
defects (pre-context review and silently discarded trailing rules); both were
corrected before delivery and are regression-tested.

Signed source implementation: `80a1f57fc07320a47254e5a012da1683a2e192bc`.
The final non-editable Windows Python 3.11.15 and 3.14.7 wheels each pass
**870 tests**, with two existing platform symlink-fixture skips. All **40 new
scenario/bridge cases pass**; none of the new cases is skipped. Ruff lint and
format checks, unchanged dependency lock verification, wheel/sdist build and
Meta static/local Markdown/checkout-regression checks pass. Both installed
modules match checkout SHA-256 bytes on both Python versions:

- `scenarios.py`: `4549ccf3affc934f82bc08c6aa79e2612f792c33c2ec1a524919a47d54ca7302`.
- `scenario_bridge.py`: `80b7905c550b7f427e35aa5c83f53e21aac595d0774f55dbd4a20d21b6931677`.

Fresh test environments/builds are retained under
`D:\Kairos\runtime\scenario-rework-20261008`; earlier environments and attempts
were not replaced. Runtime/development dependency pins and locks are unchanged.
Strategy and Backtest main checkouts remain clean at their previous identities.
Exact-source hosted CI acceptance is recorded after it completes below.
They are not historical trading, model quality or alpha evidence. The next
scientific question is whether this separately versioned waiting/confirmation
path adds **net** value against the unchanged immediate-candidate control,
including missed winners, avoided losses, all no-trade/unavailable slots and
actual source/model/execution latency. Do not assume a more persuasive narrative
or extra layer makes a negative candidate profitable.

No paid API, venue request/order, Docker PAPER/LIVE start, primary DB mutation,
recovery attempt, budget adoption or new campaign enrollment occurs. Trial 15,
V4/V5 plans, ledgers, evaluators and historical attempts remain immutable. The
new adaptive campaign still needs its own 365 future days and 500 naturally
closed simulated trades; no prior days/trades transfer.

```text
TECHNICAL_PAPER_READY=false
PAPER_QUALIFIED=false
ALPHA_READY=false
LIVE_READY=false
STRATEGY_POLICY=REJECT_ALL
TRADING_AUTHORITY=NONE
```
