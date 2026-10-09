# Prospective V3 portfolio intake — October 9, 2026

## Implemented boundary

`ContinuousSimPortfolio.intake_v3` consumes the exact first `CONSUMED` receipt
from the separate original `HypothesisJournalV3`. The portfolio precommits the
producer seal, V3 contract, full normalized candle originals and allowed parent
origins. Neither a V2 receipt/journal nor the V2 intake method can impersonate
this path. Old journals, accounts, plans and frozen evidence are not migrated.

Counterfactual matched enrollment does not grant execution permission. A
strategy-only portfolio refuses `CONTEXT_PROPOSAL`; a separately sealed arm
may explicitly allow that origin. Both use the same financial/risk reducer
and IOC execution kernel, without a privileged LLM sizing or protection path.

## Exact originals and causal knowledge

`RetainedCandleV3` retains the entire normalized candle, MARKET receipt and
actual availability clock. `CandleOriginalsV3` validates every closed-bar input
against those unchanged records. OHLC/volume, source identity, payload, close
and promotion-availability substitutions are rejected, including at reopen.
This is normalized-byte consistency, not raw REST finality or authentication.

Intake checks the anchor and every original observation through the first
trigger, including earlier WAITING observations. Checking only the final
trigger would permit an earlier stop/invalidating candle to be substituted.
Each shared input must be ready at its original shared observation clock,
not at a later review completion. A context proposal's anchor must already
be ready at its actual model request, not merely at proposal creation.

The exact committed full receipt, original candidate identity, parent,
protection, context/source hashes and native V3 metadata remain bound. The
decision and denominator cell use the actual arm decision clock, never a
retimed price-origin cut. A fresh intake requires the currently held external
producer head; exact already-recorded redelivery remains idempotent after
the producer subsequently advances. Changed redelivery is a conflict.

## Financial lifecycle and incomplete evidence

The existing continuous account fold retains pending entries, partial fills,
per-arm liquidity, original protection, natural exits, expenses and restart.
The newly connected producer is not a new fill model or a completed economic
experiment. Arm-bound issue receipts may differ even when their initial
financial state is equal; a command on one account cannot mutate another.

A consumed trigger without an available quote/review/source is a refusal
with unavailable coverage, not valid zero-return evidence. Its cell remains
unavailable through restart and subsequent parents. `finish` keeps the full
denominator and returns UNRESOLVED/null net rather than a fabricated complete
no-trade result. A known, source-complete VETO can remain a known no-trade.
The same correction applies to newly created V2 portfolios; it does not repair
or rewrite old ledgers or evidence.

## Verification

The immutable B installed-wheel suites under
`D:\Kairos\runtime\v3-portfolio-gates-20261009-b` both finished with native exit
zero: **1,627 passed and four platform skips** on Python 3.11 / 3.14, in
340.03 s / 266.79 s. Python isolation, importlib test loading and warnings-as-
errors are enabled. All 67 installed adaptive Python files in each private
environment match the exact retained wheel. Its SHA-256 is
`9404770bda60492103d884e0913b0f5963bde508d94487f8a6fe84d58be975a5`.
The [scoped gate receipt](receipts/prospective-portfolio-gates-20261009.json)
records actual results, source hashes and evidence boundaries.

The first A focused V3 run retained two fixture-assumption failures: a stored
candidate has an exact original digest, not a copied metadata field; comparing
accounts before draining both pending arrivals incorrectly omitted one arm's
entry fee. A subsequent A run retained a differing-parent assertion failure:
arm-bound issuance receipts and clocks are intentionally distinct. The corrected
isolation check asserts unchanged complete state/version of the unaffected arm
at equal financial clocks. No source/risk requirement, warning or failing case
was relaxed or skipped. The final A focused V3 run passes all 15 cases.
These source/fixture checks do not authenticate model execution or sources.

## Full points 1–3 remain open

This version retains the original 1,440-minute, 10,000-input and bounded
full-state journal limits. Passing intake checks does not prove the fixed
five-day, five-symbol run. Additive segmented input and delta state storage
must preserve the same account, exposure, liquidity, funding, source cursor,
natural exits and complete minute denominator across boundaries.

Raw REST response/finality/promotion evidence, accepted complete historical
BBO/NEWS/MACRO coverage, prospective frame/provider receipts and the fixed
four-arm driver remain separate obligations. Physical shared spend and each
arm's modeled expenses must be distinguished, including veto/error/expiry/
no-fill cases. No winner, model call, new blind credit or trading authority
follows from this engineering change. UI remains deferred.

`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL` remain unchanged.
