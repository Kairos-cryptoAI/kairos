# Adaptive strategy/LLM disagreement research

**October 2 supplement:** independent source/evaluation receipt resolution and
an opt-in durable model-attempt coordinator now exist. See the
[dated implementation and remaining qualification boundaries](ENGINEERING-DELIVERY-2026-10-02.md).
The original description below is preserved as the September 28 evidence
boundary; its missing-ledger claims do not describe the new opt-in path.
Production wiring, matched economic A/B and a new blind campaign are still not
qualified by this engineering change.

This engineering slice records what each decision path knew at one preassigned
market snapshot. It does **not** decide which path was right or authorize a
trade. The scope is isolated SIM research; Trial 15 and quarter-hour evidence
remain frozen.

The versioned `ResearchDecisionSampleV1` distinguishes a strategy that was
evaluated and produced `NO_INTENT` from one that was `NOT_EVALUATED`. The LLM
path separately records `LONG_BIAS`, `SHORT_BIAS`, a directionless
`VOLATILITY_ALERT`, `NO_PROPOSAL`, `DEFER`, `NOT_CALLED`, or an attempted
`CALL_FAILED`. A no-intent claim requires a linked evaluation receipt; a
failed-call claim requires a linked failure receipt rather than a fabricated
model answer. A completed proposal also requires a distinct budgeted-gateway
completion receipt: its call/response times must precede the pair clock, and
its model provenance and proposal ID must match exactly. The pair builder
rejects mismatched campaign/sample/symbol, decision-bar hash, market snapshot,
future evidence, late model answers, and expired hypotheses. The append-only SIM
ledger rejects a changed replay of the same scheduled sample.

The deterministic full-path SIM gate exercises two important disagreements:
`NO_INTENT + LONG_BIAS` and `LONG + SHORT_BIAS`. It stores the observations
without creating a risk decision, admission, trade, or command. The existing
strategy path still requires Router, review, and Risk. The fixture's strategy
evaluation is a pure-generator synthetic check, not proof that the production
service met its full warmup and decision schedule.

There are still deliberate evidence gaps. The pairing clock and strategy
evaluation receipt are caller-attested; source receipts must be independently
verified and stored before a real campaign can claim complete coverage. The
synthetic SIM gate fabricates its local completion receipt only to test the
boundary; it is not a real provider-timing qualification. The current LLM
gateway does not expose all durable attempt metadata after an exception, so
the failure contract is not yet wired to live provider calls. Late failures
cannot be backdated into a causal decision sample. A preregistered schedule,
durable attempt/timeout ledger, historical matched A/B evaluator, and later
blind campaign are needed before measuring missed opportunities or claiming
which path was economically better. A directionless volatility alert is not a
buy/sell signal. No readiness flag changes and `STRATEGY_POLICY=REJECT_ALL`.
