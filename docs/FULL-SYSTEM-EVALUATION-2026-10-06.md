# Full-system accounting engineering — 2026-10-06

## Completed scope

The additive offline [system API](../development/adaptive_replay/adaptive_replay/system.py)
evaluates four **independent $10,000 accounts**: strategy-only common-risk control,
contextual review of unchanged candidates, independent mapped LLM proposals, and
a conservative combined control. Profitability belongs to the system; isolated
strategy remains a control, not the only possible source of incremental value.

This is accounting/causal-boundary engineering, **not measured model alpha**, a
new strategy freeze, enrolled blind campaign or production runtime. No historical
LLM/news economic run, provider/venue call or long observation was launched.
The previous historical results and `NOT_CALLED` model arms remain intact.

## Causal and proposal boundaries

- Full five-minute/five-symbol schedule is validated before allocation/replay;
  caller-selected profitable subsets cannot be reported as full-window coverage.
- Candidate, quiet and unavailable strategy slots are distinct; unavailable
  outcomes require a reason. Quiet slots also require proposal coverage.
- All four source kinds have explicit availability. Source-specific event,
  production, receipt and TTL clocks cannot be backdated. An optional source
  included as AVAILABLE may not be reused after its own TTL expires.
- Attempt identity binds the per-slot source/input cut. The complete decision
  tape hash is an audit identity, not future input supplied to a model.
- Review may only keep or refuse the exact candidate. Execution uses the local
  response-observed/captured time, not the earlier provider completion time.
- Native proposal and completion identities, provenance, sample, symbol and
  market hashes must agree. Canonical identities are revalidated even if an
  unchecked `model_copy` attempted to bypass constructors. Cited evidence must
  belong to the slot's causal source roster.
- `LONG_BIAS/SHORT_BIAS` need a separate immutable deterministic mapper receipt,
  policy/input hash and valid geometry. A direction label alone is not a trade.
  Missing mapping is unknown, not `NO_PROPOSAL`; explicit mapper rejection is
  a nontrade outcome. Nontrading actions cannot carry trade geometry.
- The actual mapping algorithm, raw source payload/history archive, durable
  producer and provider/invoice authenticity are **not** proved by these
  caller-supplied receipts. The module does not implement a new trading mapper.

## Combined control and costs

`REVIEW_REQUIRED_CONFLICT_ABSTAIN_STRATEGY_FIRST_V1` is an explicit **engineering
control**, not an economically selected/frozen production policy. On a baseline
candidate, review `VETO/DEFER` blocks that combined slot. A timely eligible opposite
proposal abstains; same direction selects the original baseline once. Quiet slots
may use independent mapped proposals. Waiting for review, proposal and mapping
never backdates entry; validity is checked again at combined arbitration/quote time.
Failed, late or expired alternatives do not unlock a baseline trade.

All accounts use `COMMON_COST_RISK_V1` and unchanged 0.25% per-trade, 1% aggregate
entry risk, 25% symbol notional and 1x gross ceilings. This is deliberately **not**
the original adaptive-only structural-ATR admission control. Runtime Risk, venue,
protection and continuous mark-time risk qualification remain separate.

Each recorded model/feed debit is applied once at its observable clock, before
all same-clock entry sizing. Veto, error, no action, late response and no fill do
not erase spend. Costs in the exit tail remain charged; out-of-horizon liabilities
fail closed rather than disappear. Combined pays both incurred model paths.
Native fees/funding remain charged by the existing engine; spread/slippage are
already in modeled prices and are not subtracted twice. Account reconciliation
adds back service debits once, never charges them again after final equity.

Missing observations or unknown model charges keep that account's economics
null. Scheduled policy-gated `NOT_CALLED` requires a reason and has a separate
counter from complete responses/errors/missing observations. Unknown feed costs
keep `recorded_all_in_net_result` null; any remaining ledger is conditional and
explicitly incomplete. Known amounts are recorded estimates/debits, not proof
of provider invoices. `complete_all_in_net_economics` remains false.

Review counterfactuals show the baseline trade outcome under a refusal, including
missed profitable trades and avoided losing trades where naturally closed.
Null means no closed baseline trade, not zero PnL. Independent account deltas
are not additive trade-level attribution: timing, fees and sizing change later
opportunities. Minute/cash-event MTM uses candle-price proxies; partial fills,
intraminute quotes, capacity, protection latency and actual venue are unqualified.

## Verification and remaining work

Local Python 3.11 verification passed **151 offline tests**, including 31 new
full-system/service-cost tests. The suite ran outside the source directory with
`--import-mode=importlib` against a freshly installed non-editable wheel;
`adaptive_replay.system` resolved to that environment's `site-packages`.
Ruff lint/format and the meta static/Markdown-link gate passed. An independent
read-only review reran the 31 focused cases and found no remaining high-priority
receipt/accounting issue. No fixture numbers are market-performance evidence.
The [offline workflow](../.github/workflows/adaptive-development.yml) also checks
the installed package on Windows/Linux and Python 3.11/3.14; same-commit remote
results must be checked after publication, not inherited from an earlier SHA.

Tests cover four-path/account isolation, quiet proposals, immutable review,
conflict/expiry/late deadlines, local observation clocks, source TTLs, missing
responses/mappers/costs, native identity forgery, full-roster/resource bounds,
cash-event ordering, tail costs, reconciliation and unchanged default replay
outputs. Fixture economic results require explicit `fixture_only=True`; they
cannot be mixed with point-in-time observations or presented as a campaign pass.

The adapter is now available for separately qualified, source-bound observations.
The durable producer/import path, accepted real model/news samples, deterministic
mapper implementation, own campaign freeze/enrollment and sealed evaluation
remain separate work. No existing campaign/evaluator or protected Backtest source
was edited, and no blind performance was read or credited.

Trial 15 and V4/V5 source/evidence are unchanged. No primary DB recovery, outbox
dispatch, consumer start, Docker PAPER start, exchange mutation or real funds.
`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`. UI/UX remains deferred.
