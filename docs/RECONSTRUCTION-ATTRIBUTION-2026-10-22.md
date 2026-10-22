# October 22: attribution of the existing cached economic results

## Question and finite scope

Does the already-tested candidate-review path add economic value after its
recorded costs, rather than merely avoid trading? This is an offline
reconciliation of existing observations, not a new strategy, prompt, paid model
campaign or implementation of the current independent Catalyst policy.

The original strategy, 12 candidates, all 17,280 five-symbol decision slots,
four fixed three-day windows, two fill assumptions and two cost scenarios stay
unchanged. Each window/account starts independently at $10,000. No annualization,
cross-window compounding, parameter search or new provider call is permitted.
Previously retained plans, responses, failures and receipts are not rewritten.

The existing `development/market_review/reconstruct_economics.py` and installed
`adaptive_replay.engine.replay_tape` supply the calculation. The finite extension
adds controls to the existing calculator, not another economist or service.

## Controls fixed before this reconciliation

Seven arms are evaluated in every original window/fill/cost cell:

1. Unchanged strategy.
2. Cash without a model or trading.
3. Market-only latency-and-cost control, keeping the original candidates and
   charging all 12 recorded market reviews at their measured completion clocks.
4. Market-only review, keeping only explicit `ALLOW` while charging every review.
5. Free publication-source-eligibility control: only the same nine originally
   source-eligible candidates, with the original assumed processing latency.
6. Publication-proxy latency-and-cost control: those same nine candidates,
   irrespective of the model's decision, with their recorded costs and durations.
7. Publication-proxy review: only explicit `ALLOW`, still charging every actual
   review. The three missing-context candidates remain genuine `NO_CALL` and
   abstention; they receive neither invented responses nor invented durations.

This makes 112 simulated accounts. Alternative accounting sensitivities reuse
the same physical responses; they do not spend the authoritative budget again.
The known recorded costs are $0.008804 for market-only responses and $0.005411
for publication-proxy responses. The earlier $0.005035 uncertain hold is reported
separately, not declared actual spend, released or silently set to zero.

Review minus its own latency-and-cost control describes the observed filtering
effect within that cached experiment. Free source eligibility minus strategy
describes roster selection. Proxy latency-and-cost minus free source eligibility
describes the joint timing/cost difference. Cash is an explicit economic
comparator, not a successful model prediction.

The market-only and publication-proxy experiments are **not a matched causal
NEWS/MACRO A/B**: their prompts, dispatch rules, calendar masking and observation
dates differ. These differences cannot be removed by putting the old results
in one table. The attribution is descriptive, conditional and exploratory.

## Acceptance and remaining boundary

All original market and proxy accounts must reproduce their retained ending
equity and trade counts with absolute tolerance $0.00000001 and no relative
tolerance. Duplicate/missing account cells, non-finite numbers, mutated source
or capture evidence, unresolved positions or ledger failures stop acceptance.
All candidate identities and the original full-slot denominator remain bound to
the source tape. Inputs are checked before and after; new output is create-only
and bounded to at most 900 seconds.

The primary strict-minute fill result must remain visible alongside the
secondary intrabar approximation. Neither a cash-only result nor a no-fill
result is corrected by changing expiry, prompts or risk until trades appear.
Unknown feed/operating costs remain unknown. Publication time is not proof of
historical receipt, exact-version availability or complete NEWS/MACRO coverage.
The missing entry/reference/trailing details in old review prompts cannot be
retroactively supplied to already-observed model responses.

The current Catalyst/native context path still needs genuine admissible source,
receive/capture and quote evidence. It cannot consume these publication-only
archives by relabeling them contemporaneous or fabricating a complete response.
This reconciliation does not activate runtime, change DB/queues, send orders,
credit blind days/trades, promote readiness or qualify a production strategy.
