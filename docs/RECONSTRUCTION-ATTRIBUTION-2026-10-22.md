# October 22: attribution of the existing cached economic results

## Completed outcome

The cached-only calculation completed on signed source
`30a3413532a1c52a598dc9d97537f060cabb79be`: **112 accounts, zero new provider calls**.
The main agent independently checked the result seals, unique account roster,
cash/position/risk reconciliation and the outputs below. All 48 old market-only
accounts and all 32 prior proxy accounts reproduced their original trade counts
and ending equity within absolute $0.00000001, with no relative tolerance. The
16 overlapping strategy cells are intentionally checked against both records.

No non-cash arm beat cash in any of the declared cells. This does not establish
that a future strategy/model combination cannot work: it rejects a claim of
observed positive value for this finite, old candidate-review approximation.
The current independent Catalyst policy was not economically evaluated.

### Secondary intrabar candle approximation

Every value below is a percentage return on an independent $10,000 account,
after the declared trading costs/funding and applicable known model debits.
It is not an observed venue fill, complete all-in net return or annual estimate.

| UTC window / costs | Strategy | Market delay/cost control | Market review | Source-eligible control | Proxy delay/cost control | Proxy review | Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| May 9–11 / base | −0.473053% | −0.473098% | −0.582940% | −0.234069% | −0.234093% | −0.00003145% | 0% |
| Jun 13–15 / base | −0.263370% | −0.263412% | −0.320370% | −0.320328% | −0.320351% | −0.00002266% | 0% |
| May 9–11 / stress | −0.837618% | −0.837664% | −0.707790% | −0.601261% | −0.601281% | −0.00003145% | 0% |
| Jun 13–15 / stress | −0.343641% | −0.343683% | −0.343683% | −0.343641% | −0.343663% | −0.00002266% | 0% |

The November 7–9, 2021 and February 5–7, 2022 windows contain no native
candidates: all seven arms return 0%, without invented reviews. The **primary
strict-minute-open assumption gives zero trades across all arms**; model arms
still incur their recorded costs in May/June. The original 60-second entry
expiry is not extended to make the approximation trade.

In the base intrabar cells, market-review selection loses **$10.984124 in May
and $5.695794 in June relative to its own delay/cost control**. Thus its negative
increment is not explained merely by API expense. In May/stress selection
improves that control by about $12.987386, but the result still loses to cash;
in June/stress it equals the delay/cost control. No favorable cell is selected
as a champion or extrapolated to other periods.

Source eligibility alone changes May/base equity by +$23.898359 and June/base
equity by −$5.695798 versus the strategy. That is selective source availability,
not a model forecast. Proxy review then removes every remaining trade: it ends
at $9,999.996855 in May and $9,999.997734 in June, below the $10,000 cash anchor.
Avoiding these particular losses does not establish an edge over not trading.
All account contrasts include the resulting portfolio reallocation and sizing;
they are not per-trade causal contributions.

All 17,280 original slots remain represented by exact tape hashes and counts:
12 candidates and 17,268 `NO_INTENT` observations. The candidate audit preserves
all 12 identities: 12 market observations (9 `ALLOW`, 3 `DEFER`), nine proxy
observations (all `DEFER`) and three explicit source-missing abstentions.
No terminal unresolved position, forced settlement or reported risk/gross
overrun occurred. Absolute financial ledger error stays below $0.00000001.

## Evidence and engineering checks

- [Input/source snapshot](receipts/review-attribution-2026-10-22-before.json),
  SHA-256 `5c4455405a3ff65cf6aafe5a485e385fadee2d1064f2db88a92a71723919f3c3`.
- [All accounts, ledgers, deltas and candidate audit](receipts/review-attribution-2026-10-22-result.json),
  SHA-256 `56a4aafd6e13099a01b89129e601abe8439b41356a8e929d85142340739f2d8f`.
- [Exact output seal](receipts/review-attribution-2026-10-22-seal.json),
  SHA-256 `7ad34d18d149e4c66455752b5858c2978d2d90cb5defa50a39c5881705263c16`.

Ruff lint and actual format-check passed. The main agent independently ran
**77/77 market-review tests, zero failures/skips**, from outside the checkout
using the locked non-editable CPython 3.11.15 environment with patched Certifi.
Independent review caught and corrected new calculator format assumptions
before any replay: native rows do not contain a window ID, unresolved positions
are a list, and an account with no model call retains `model_cost_usd=null`
rather than claiming a free called service. Real installed `Portfolio.report`
and original-style candidate-row regressions now cover those cases.
These checks establish calculator behavior, not trading quality or LIVE readiness.

Hosted source validation and CodeQL completed successfully on `30a3413`.
The separate eight-job
[adaptive development matrix](https://github.com/Kairos-cryptoAI/kairos/actions/runs/39791159057)
was still running at this receipt's publication. It must not be described as
completed/green or replaced with an older commit's successful matrix.

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
