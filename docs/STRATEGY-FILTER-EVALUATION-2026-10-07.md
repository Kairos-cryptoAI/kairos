# Candidate-stream and causal selection evaluation — 2026-10-07

## Decision and delivered scope

The user's current direction is to assess a strategy as a **candidate generator**
and measure selection's incremental full-system value. Negative or slightly
negative standalone economics do not automatically exclude a research candidate
stream. They also do not grant trading permission or establish that LLM/news
will rescue it. Keep only the existing bounded shortlist; no new parameter grid,
winner, production enrollment or frozen campaign is introduced here.

The existing four independent accounts are reused, not rebuilt. The opt-in
[system API](../development/adaptive_replay/adaptive_replay/system.py) now adds:

1. A fixed **causal-source control** (`deterministic_filter`): unchanged baseline
   candidate, explicitly supplied filter timing and required/supplied source
   freshness. Known unavailable/stale evidence or no quote inside the original
   lifetime yields `DEFER`; a missing filter observation makes the entire control
   account incomplete with null economics. No standalone-return gate or quota.
2. A **review timing/cost control** (`review_timing_control`): same review attempts,
   local observation clocks, recorded model/feed debits and source checks, but
   without review content. Actual `VETO/DEFER` therefore does not select this
   counterfactual account. A called error retains its terminal-observation clock
   and cost, not a fabricated successful completion; an explicit
   no-call is a known abstention, not a fabricated inference completion. Missing
   attempts or unknown charges keep the account incomplete.
3. A post-replay **all-candidate audit**: each original candidate's selection,
   response delay/cost, entry/rejection/open/closed outcome and baseline net
   outcome, plus the full candidate/quiet/unavailable denominator and per-source
   coverage. It distinguishes omitted baseline winners/losses from retained
   candidates that never filled. Open, missing or incomplete outcomes stay null
   or `UNKNOWN`, not zero. Daily entries, including observed zero-entry dates,
   remain outputs, not targets.

These are offline accounting/control mechanics. No new historical economic run,
real News/Macro/LLM observation or profitability result was obtained by this work.
The causal-source policy tests availability/freshness, **not directional alpha**.
Current receipt hashes contain no independently verified raw-news/macro payload;
they cannot justify an invented sentiment/conflict filter. A capital allocation
weight is not direction or entry permission, and `CHOP` is not silently `RANGE`.

## How to use the additive boundary

The old call and its four-arm `full-system-paths.v1` output remain unchanged.
For qualified caller-supplied observations, use the new optional parameters:

```python
from adaptive_replay.filters import CausalFilterObservation
from adaptive_replay.system import evaluate_system_paths

# One exact receipt per original CANDIDATE, not a selected profitable subset.
# Bind its slot_id, original candidate_id, context_sha256, actual request/local
# observation clocks and explicit TEST_FIXTURE or OBSERVED_POINT_IN_TIME mode.
# Quiet/unavailable slots remain in the original complete five-symbol roster.
result = evaluate_system_paths(
    inputs, slots, reviews, proposals, scenario, mode,
    mapper_policy_sha256=registered_mapper_sha256,
    deterministic_filters=filter_observations,
    include_review_timing_control=True,
    include_selection_audit=True,
    fixture_only=fixture_only,
    feed_costs=recorded_feed_debits,
)
```

Opt-in output has the separate `full-system-paths.v2` identity. An empty explicit
filter tuple is incomplete when candidates exist, not an instruction to remove
them. Filter receipts are revalidated at consumption even after unchecked frozen
object construction. Wrong slot/candidate/context/policy, duplicate/quiet receipt,
backdated/noninteger clock and fixture/observation relabelling are rejected before
account replay. Original entry expiry, geometry, common risk and independent
account admission stay unchanged. Future exits/ledger PnL never enter selection.

The review-versus-timing-control difference compares independent account final
equity; it is **not additive trade-level alpha attribution**. Missed-winner and
avoided-loss labels are baseline diagnostics, not transferable cash savings.
Because actual review abstains on a called error while the control can still
test an unchanged source-valid candidate, the difference also includes
operational error-gating effects. It is not pure review-content alpha.
Recorded fees/funding/model/feed costs are retained once per hypothetical
account, including veto/error/late/no-fill cases. Unknown feed charges keep
all-in results null. CPU/unrecorded infrastructure cost and provider invoices
remain unqualified; complete all-in economics and execution qualification are
never asserted by this API.

## Verification and remaining scientific prerequisites

Offline fixtures cover unchanged default accounts, all-pass equality at identical
clocks/costs, known source abstention with feed spend, missing/unknown observations,
all-candidate accounting, original expiry, quote-time TTL, no daily quota,
future-exit independence, duplicate/forged receipts and timing/error cost retention.
Fixture numbers are never market-performance evidence. The full offline suite
passed **409 tests on Python 3.11 and 409 on Python 3.14**, outside the source
directory against fresh non-editable wheels in separate task-owned environments.
Ruff lint/format, locked dependency check, wheel/sdist build and the meta static
and Markdown-link gate passed. Installed source bytes were independently compared
with the source modules in both environments. Independent review passed all 50
focused system/audit cases; unchecked-receipt revalidation and error-clock wording
were corrected before publication. Exact-source hosted CI is checked after the
signed main commit, not inherited from a prior SHA.

Actual incremental News/Macro/LLM value still requires:

- Reproducible typed, symbol-scoped point-in-time source payloads and rules. Never
  generate a retrospective historical-news response using future event knowledge.
- The separately versioned native-clock/cadence adapter, full protocol denominator,
  qualified bar resolver, actual capture/debit evidence and deterministic proposal
  mapper. Native `1m` receipts are not rewritten into this `5m` control's clocks.
- A separately fixed economic experiment with unchanged risk and base/stress
  costs, executable observations, bull/range/bear/crash coverage and later untouched
  evaluation. No cherry-picked saved-window subset or post-outcome receipt whitelist.
- A positive admissible complete-system result and incremental value evidence,
  not necessarily positive standalone PnL; own frozen forward/blind gates and
  separate venue/security/manual arming before any trading authority.

Prior Trial 15/V4/V5 sources, plans, ledgers, dated results and stopped resource
attempts remain untouched. No paid model/feed call, database, Docker, exchange,
recovery, consumer or trading operation is performed. UI/UX stays deferred.
Dependencies/locks and current engineering source manifest pins are unchanged.
`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL` remain unchanged.
