# One event-origin trading policy — 2026-10-22

Status: **implemented offline research candidate, not an economic champion or
trading release**. The owner reopened only this bounded strategy task after the
operational work. No new strategy sweep, indicator ensemble, economic driver,
provider request or runtime activation is included. Historical profiles, frozen
campaigns, Trial 15 and V4/V5 evidence remain unchanged.

## What the candidate actually does

`closed price history + causally available NEWS/MACRO event -> independent
directional hypothesis -> deterministic geometry -> later closed-price
confirmation + fresh BBO -> candidate-specific review -> retained arbitration
-> research candidate awaiting independent Risk/account/venue gates`.

The other origin is the **unchanged** `adaptive_pullback_range_v1`, used directly
as a control. It is not selected as profitable, and the two-family breakout
bridge is not substituted for it. There is no assumption that a language model
will make a negative strategy profitable.

Implementation lives in the existing `development/adaptive_replay` package:

- `catalyst_policy_v1.py`: `adaptive-catalyst-whole-system.research.v1`, source-bound
  event scheduling, one original outcome, treatment composition and retained
  arbitration. It reuses the old profile's explicit session/source/timing
  parameters, not its price-epoch eligibility or capability identity.
- `catalyst_hypothesis_v1.py`: separately typed
  `closed-catalyst-hypothesis.research.v1`, actual creation clocks, confirmation,
  invalidation and an explicitly identified unchanged V3 quote/economics kernel.

## Concrete decisions, not adjustable indicator votes

| Situation | This candidate's rule |
| --- | --- |
| Technical generator returns `NO_INTENT` | Positive absence of a technical parent, not a ban on an independent event |
| New canonical publisher event | One combined document batch at its first available declared 5m cut; no mean/range reset prerequisite |
| BULL with independently supported bearish catalyst | Context SHORT may be proposed without relabeling BULL or waiting for every hourly indicator to reverse; still needs its own confirmation/review/quote |
| BEAR with independently supported bullish catalyst | Symmetric independent LONG research hypothesis |
| CRASH, post-shock cooldown, UNCERTAIN or unsupported regime | No new entries; the countertrend permission is NORMAL BULL/BEAR/RANGE only |
| Technical idea receives candidate-specific VETO | Reject that idea; a separately confirmed/reviewed event can still qualify |
| Shared integrity/data/protection/account/operator/Risk uncertainty | No entry from either origin; an LLM cannot override it |
| Same-side candidates at actual issue | One technical parent wins; no doubled position or confidence-based sizing |
| Opposite admitted candidates | Abstain; conflicting shared candle histories are rejected before arbitration |
| Required peer is unknown when the first candidate is ready | Refuse this combined cohort; never wait for a later winner and backdate/requote it |
| Active hypothesis/position in an arm | Suppress new entries in that arm; consume new events rather than queue them for after exit |

Source event identity is **not** a model novelty judgment. All documents for a
new canonical event root at one cut are included in one immutable batch; each
must meet availability/TTL checks. Another document for an already consumed
event is not a fresh attempt. Duplicate capture, changed model/direction, NONE,
failed/unknown response, missing budget and missed first cut cannot rearm it.
Changed document bytes or aliases detected through document/content identity
block that symbol for the retained bounded session. Cross-publisher semantic
deduplication still needs an external source resolver; no hash proves it.

Publication time alone is never availability. This version accepts explicitly
synthetic fixtures or contemporaneous exact-version local receipts, including
actual capture and first receipt. An archive fetched now is not silently treated
as a historical Kairos receipt. Existing BLS/Fed capture work is not comprehensive
crypto/exchange news coverage, and this task acquires no new corpus.

## Entry, retention and management

The existing `context_atr_proposal_v1` remains the sole context geometry mapper:
direction in, deterministic stop/target/timeout out. It is an unqualified ATR
template, **not** evidence of a native pullback/range-edge setup. LLM-provided
prices, quantity, leverage and confidence cannot alter it. The mapper requires
5m cuts, so this is not a sub-minute news trading system.

Research timing is explicit: unchanged full 3,240 consecutive 1m bars, all five
symbols at every 5m cut, 15m hypothesis lifetime from the original cut, 2s maximum
entry quote age. Actual creation must complete before the first post-anchor
minute closes. Every subsequent closed minute must be retained in order. The
first directional closed-price trigger consumes the origin even if its review,
quote, spread, cost headroom or downstream admission fails. No late creation,
price chasing, stop widening, protection replacement or TTL renewal is allowed.

`prepare_cut` returns the event checkpoint and exact original preparation.
`materialize` consumes an independently retained `CreationLedger`; a physical
response is shared across its predefined consumer arms, never resampled per arm.
`resolve_arm` consumes and returns a separate **DecisionLedger**: retain the
returned ledger, original preparation and observation prefixes. Missing review
cannot later be replaced by ALLOW for the same minute. The first admissible
origin candidate consumes the arm's arbitration cohort even on shared-gate or
unknown-peer refusal. Equal redelivery yields the original receipt; later inputs
cannot resurrect it. Future peer observations or creation outcomes cannot inform
an earlier decision. A previously vetoed individual idea is not itself an
admissible candidate and does not silently become a global veto.

Current admission requires the latest closed-5m preparation and its linked
checkpoint chain from the original (at most three extra cuts). A clean fork
cannot replace revision-blocked history. Current UNKNOWN news coverage or missing
mandatory context blocks context/review treatments; the price-only control is
separate. The existing closed-minute stop guard also applies. This is not
continuous tick coverage or an intraminute crash predictor.

The emitted intent retains the original ExitPlan, including timeout/trailing
representation. Existing execution/protection code, not an LLM, owns fills,
partial fills, protective orders and position reconciliation. This module does
not implement a new production position manager, pyramiding, averaging,
automatic reversal or confidence-driven capital growth. Downstream ceilings
remain **0.25% stop risk per trade and 1% aggregate open risk including
reservations**. A candidate is not a `RiskTradeDecision`, order or proof that
these external gates have been accepted.

## What this verification does and does not close

The four isolated **decision treatments** are `strategy_only`, `context_review`,
`independent_proposals` and `combined`; independent proposals also require review.
This supplies preparation/materialization/lifecycle/arbitration contracts, **not
four financial accounts, native fills, fees/funding, model-cost allocation or a
matched economic result**. The existing V3 economist has different capabilities,
NO_CALL and review/arbitration rules; it must not be relabeled or fed fabricated
COMPLETE responses to claim compatibility.

New offline synthetic tests cover independent event scheduling, actual-clock
countertrend hypotheses, frozen protection, first-trigger refusal, revisions,
source/price gaps, active-arm isolation, unknown peers, source-branch substitution,
immutable review prefixes and future-outcome leakage. Installed-wheel/hosted CI
results are engineering evidence only. No historical news/model run or paid API
request is performed here. Retained pure folds establish local consistency, not
authenticated sources, durable/global exactly-once or production deployment.

Next research evidence is one **separately admitted**, source-pinned finite
comparison on available causal data with declared costs and limitations—not
another strategy family or a claim of superprofit. No unseen-alpha gate is
waived: 365 blind days and 500 naturally closed simulated trades remain distinct
requirements. This policy is not enrolled in such a campaign by this change.

`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`. Production integration and venue
signing/lifecycle acceptance remain separate from strategy research; see the
[current engineering register](LAUNCH-REMAINING-2026-10-18.md).
