# Separate hypothesis validity and fresh entry: research v2

Date: 2026-10-08 Europe/Moscow. Classification: ENGINEERING_ONLY_TEST_FIXTURES.
This implements the next design question from the
[completed v1 diagnostic](SCENARIO-COMPARISON-RESULT-2026-10-08.md), not a rerun,
rescued result, selected duration, strategy qualification or production rollout.
The original v1 policy, comparator, 16 receipts and negative finding stay intact.

## Implemented contract

The separate [hypothesis engine](../development/adaptive_replay/adaptive_replay/hypothesis_v2.py)
and [native/context bridge](../development/adaptive_replay/adaptive_replay/hypothesis_bridge_v2.py)
are opt-in library functions in the isolated development package. No CLI,
history/comparison runner, publisher, paid loop or runtime registry uses them.

| Object | Meaning and authority |
| --- | --- |
| Original parent | Exact native intent, original creation cut, source/history identity, short entry expiry, strength, metadata and full ExitPlan; it remains expired when its original deadline passes |
| Hypothesis policy | Explicit separate lifetime, seal clock, quote source/freshness, evidence kind and reviewed/control mode; no production lifetime/default is selected |
| Hypothesis | Same original anchor and parent; its own fixed validity does not renew the parent or create a position |
| First structural trigger | A later contiguous closed-minute close beyond the original reference; consumes the hypothesis even if an entry is refused |
| Entry quote | Separate source, LONG ask / SHORT bid, event/receipt/capture clocks, exact payload and declared provenance; not a fill or proof of continuous market coverage |
| New entry envelope | Different v2 intent ID at actual assembly/issue time, bounded by original inclusive TTL duration and every earlier source deadline; independent Risk/venue/operator admission remains mandatory |

`HypothesisPolicy` must be supplied explicitly. Its seal clock cannot be after
the original creation. Parameters, fixed mechanics and unchanged planning
configuration enter its hash and the hypothesis identity. Lifetimes are bounded
to 60 minutes and quote age to five seconds as engineering caps, not empirically
qualified best values. Constructor parameters do not authorize a parameter grid
or resealing after seeing outcomes. Review mode is fixed in the policy identity:
the price-only control cannot be flipped into the reviewed arm under the same ID.

Only NORMAL defense and the existing BULL/LONG, BEAR/SHORT, RANGE/either mapping
remain supported. UNCERTAIN/CRASH and opposite directions are not newly admitted.
Quiet/unavailable native slots remain explicit. Model proposals still obtain
price geometry from the unchanged mapper; NEWS and MACRO stay mandatory for
context-origin hypotheses. No model confidence controls sizing or leverage.

## Source, review and expiry semantics

Creation remains exactly the original parent eligibility cut and prior-minute
closed anchor; a later review/quote cannot change it. Required MARKET identities
must themselves bind the actual candle bytes. An optional different publisher
cannot substitute for an unrelated required receipt. Quote source identity is
separate from every creation and later context-source identity.

Quote event time must be after the confirming candle completes. Quote receipt,
capture and review completion cannot be backdated or exceed actual issue time.
ALLOW must bind the exact hypothesis, side, context receipts **and quote bytes**,
and complete after every bound capture. An old candle-only v1 ALLOW cannot pass.
Missing, stale, future, foreign or conflicting inputs emit no entry. A quote
cannot renew source freshness from review/issue time.

All subsequent minutes must be contiguous. If another minute has completed by
observation time without being covered, the fold terminates BLOCKED/UNAVAILABLE,
even with a new quote. Frozen stop breach wins an ambiguous confirming candle.
This is explicitly **closed-bar structural invalidation**, not proof that a stop
never touched and recovered inside the next still-open minute.

For a permitted first trigger, inclusive entry expiry is:

```text
native_duration = parent.entry_expiry - parent.entry_eligible + 1
new_entry_expiry = min(
    hypothesis_creation + explicit_hypothesis_lifetime - 1,
    actual_issue + native_duration - 1,
    quote_event + min(quote_ttl, declared_maximum_quote_age),
    every_supplied_context_source_event + its_own_ttl
)
```

Current entry-side quote must still exceed the original confirmation reference
in the intended direction. Current exit-side quote cannot already breach the
frozen stop. Stops, targets and trailing activation cannot be moved to make an
entry feasible. A spread wider than the unchanged planning assumption is an
explicit unsupported-cost refusal, not hidden by the assumed 20bps budget.
Remaining fees/funding/slippage/latency/model/feed costs still need a separate
matched evaluator and actual source/venue evidence.

All original metadata survives. Native/context `planning_cost_authority` is
accepted only at its identical assumption marker, never upgraded to a measured
venue fact. Original frozen volatility bounds, stop-width, cost-headroom and
net reward/risk checks remain in force against the fresh reference.

## Trailing protection and important integration limits

The entire original ExitPlan object survives: stop, target, maximum holding,
activation and distance. Native directional constraints reject entry at/past
activation. Waiting candles do not activate/ratchet a nonexistent position.
The synthetic common-evaluator fixture verifies that trailing starts inactive
at actual entry, updates at a later completed close and applies only afterward;
holding duration likewise starts at actual entry, not hypothesis creation.

This is **not production trailing support**. The pinned native runtime adapter
still rejects trailing ExitPlans. Also the common economic evaluator's admission
does not independently check trailing activation against an adverse actual fill.
A quote-safe reference alone therefore cannot prove actual-fill feasibility.
No evaluator or runtime adapter was changed to conceal that boundary. Eventual
execution needs independent fill/protection checks and accepted source/venue
and risk gates before this path may be connected.

`TEST_FIXTURE` and `CALLER_ATTESTED_POINT_IN_TIME` are distinct declarations and
hash identities. The latter is consistency-checked caller attestation, **not
authenticated or accepted live/historical provenance**. No candle close is
fabricated into a historical bid/ask; no modern inference clock becomes an
observed historical receipt. A top-of-book quote proves neither depth nor
intervening tick-path integrity. Sealed timestamps/hashes do not independently
prove genuine preregistration or publisher authenticity.

One trigger produces at most one envelope within the supplied immutable fold.
Exact redelivery collapses; changed quote/review receipts fail, and terminal
states never resurrect. This is not durable/global exactly-once across restart.
The caller must retain the original append-only chain and terminal receipt;
recreating a parent under new clocks or another policy to rescue a refusal is
not permitted. No durable publisher or automatic fresh-parent generator is added.

## Verification and remaining work

New synthetic cases cover the original 60s parent versus separate validity,
inclusive TTL/source deadline caps, exact parent/full-protection preservation,
quote-priced LONG/SHORT entry, review/source/quote clocks and identities,
uncertainty/direction/quiet abstention, metadata compatibility, stale context,
activation/target/stop equality, wide spreads, gaps, duplicate delivery and
first-trigger-only terminal states. No historical/model/venue result follows.
Full installed-wheel and hosted acceptance are recorded below.

The implementation is GPG-signed main
`d1d43f3f154a059a970646b8461d1ab58fa27949`. All 67 added fixture cases pass on
the fresh non-editable Python 3.11.15 wheel; its full local suite passes 951 tests
with two existing platform symlink-fixture skips. Independent source review
found no remaining implementation blockers after correcting real-family metadata
compatibility, required-market identity binding and quote-side protection checks.
Source review and fixture tests are not a historical or venue experiment.

Ruff lint/format (113 files), unchanged lock verification, wheel/sdist build,
Meta static/local Markdown/checkout-regression checks pass. Fresh environments
and builds are retained under `D:\Kairos\runtime\hypothesis-v2-build-20261008`;
the older v1 environments and attempt survive. Installed v2 modules match the
checkout bytes on both Python 3.11.15 and 3.14.7:

- `hypothesis_v2.py`: `5216748253135852ef58f16a4157023e77fcb3400e93be77cb73cbfaeae40072`.
- `hypothesis_bridge_v2.py`: `dd85d06d4eadf0ac228a4163d0287e6b8497ea3054c1d6e3e0086a083340df23`.

The original v1 scenario/bridge/comparator module hashes and result hash match
their prior receipts; Strategy and Backtest main remain clean and unchanged.

### Completed installed-wheel and hosted acceptance

The fresh non-editable Python 3.14.7 wheel also passes the complete local suite:
951 tests, two existing platform symlink-fixture skips. No new case is skipped;
all 67 new lifecycle/bridge cases pass in each complete installed-wheel suite.
No historical/economic/provider test attempt was started by these fixture gates.

The complete source and scope-documentation set at GPG-signed main
`e651239606c7d29501bd14b2622260f0fcb00db2` passed all hosted gates; GitHub confirms
that revision's signature as verified/valid:

- [Adaptive fixtures](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37808634861):
  953 tests passed, zero skips, in **each** Windows/Linux x Python 3.11/3.14 job.
- [Meta validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37808635018): passed.
- [CodeQL](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37808632944): Python and Actions passed.

This verification-only receipt changes no source, policy identity, dependency,
runtime pin, historical attempt or trading authority. It is not a strategy result.

Before another economic experiment, fix one new identity/policy and a new
predeclared roster using authentic causal quote/context coverage, all refusal
and unavailable denominators, matched unchanged immediate entry and full costs.
The old v1 slice/result is not reused as unseen alpha or silently rerun. No
future campaign is enrolled here; it still needs its own blind duration and
natural-trade gates. The present engineering change proves no net/monthly profit.

No paid model/feed API, exchange, canary, Docker PAPER/LIVE service, primary DB,
runtime recovery, frozen plan/evaluator, release/dependency pin or lock changed.
Risk ceilings remain 0.25% per trade and 1% total open risk, without daily quota.

`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`, trading authority NONE.
