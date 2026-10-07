# Historical pilot: local engineering completion — 2026-10-07

This receipt records local implementation, not accepted historical NEWS, a paid
matched A/B, a strategy winner or production readiness. Archive searches and
downloads are stopped. Earlier failed attempts and all frozen ledgers/plans are
retained; no key, primary database, consumer, recovery or venue is operated.

## Implemented boundaries

- The retained ALFRED raw/request/receipt and ZIP/member digests are checked
  offline. Exactly 32 monthly rows and two requested vintage columns are
  validated. Only April 2021 CPI `266.832` and November 2023 CPI `307.917` are
  returned for the corresponding episodes; the revised April value `266.670`
  cannot replace the earlier vintage. This is CPI semantic evidence only:
  NEWS, full macro coverage, source authentication and historical local receipt
  remain unproven. Release dates remain separate from conservative availability
  upper bounds; no new freshness claim follows from a vintage date.
- `historical_pilot_dispatch` binds the existing native `BudgetedLLMGateway`
  to a local one-shot USD 1 / twenty-slot cap and the existing OpenAI USD 12
  budget protocol. Local reservation precedes shared reservation; shared
  commitment precedes local settlement. Denial, cancellation and ambiguous
  failure retain holds, and a consumed slot is never restored. This is a
  tested adapter, not adoption of a production PostgreSQL ledger: the caller
  still must establish the authoritative shared identity and source admissions.
- A private immutable review route isolates requests from application-router
  mutation while awaiting budget admission: OpenAI `gpt-6-luna`, logical and
  provider `medium`, at most 2,048 output tokens, zero retries. The strict
  response is exactly `ALLOW/VETO/DEFER`; actual request/response/cost clocks
  stay modern. Injected SDK responses require explicit fixture mode and cannot
  be relabelled production observations. No model/effort comparison is run.
- `historical_pilot_sim` seals a separate fixed diagnostic before native
  strategy generation. The original prototype source/configuration and its 5m
  cadence are unchanged. Every original 1m/five-symbol cell is retained:
  `CANDIDATE`, `QUIET`, `UNAVAILABLE` or `NOT_SCHEDULED_NATIVE_CADENCE` are distinct.
  The existing two A/D windows and four review cuts are not moved or expanded.
  All unadmitted review arms are `null`, never zero PnL or fabricated decisions.
- Price-only replay retains both strict minute-open and intrabar-open proxy,
  both original base/stress costs, signed archived funding and common risk:
  0.25% per-trade / 1% aggregate admission ceilings, fixed sizing and no daily
  trade quota. One worker, a 900-second cooperative deadline, create-only
  outputs and end-of-run installed-source/raw-cache equality checks apply.
  The proxy is not observed execution. Gaps can exceed reserved stop loss,
  and observed mark-risk ratios are reported rather than silently hidden.

## Verification and scope

Offline tests exercise actual native SDK-adapter code with injected responses,
paired reservation order, duplicate delivery, shared denial/commit failure,
cancellation, unknown usage, strict JSON, route mutation, actual clocks, retained
model costs, full denominator, source mutation and create-only failed receipts.
An end-to-end fixture flows through native gateway, retrospective review and the
shared SIM account: positive delay can make an `ALLOW` miss the unchanged
60-second entry lifetime under strict minute-open; cost is still retained.

Installed, non-editable wheel verification passed **640 tests, two skips** on
each of Python 3.11 (73.90s) and 3.14 (67.02s), using `--import-mode=importlib`
from outside the project. The skips are the existing Windows symlink-creation
privilege fixtures, not model/market tests. Ruff lint/format, locked dependency
check, wheel/sdist build and meta static/Markdown-link gates passed. Independent
deep review found a route-admission race and missing provider-effort constraint;
both were corrected with the immutable per-pilot route and regression tests.
Real temporary SQLite tests verify reopen/settlement and ambiguous holds; no
production pilot ledger was created. An initial cross-test import failure was
fixed before this passing installed-wheel gate; no failure artifact is erased.

The development-only dependency projection adds immutable `kairos-llm`
`f1e25893f9078a467eba584e233ac9129e9ff9b1` and its locked SDK dependencies.
Frozen campaign locks, evaluators, release readiness and Trial 15/V4/V5 are not
changed. CI runs offline tests on Windows/Linux and Python 3.11/3.14, not the
historical economic replay. The original prototype is not a nominated champion.

The new separate diagnostic command is:

```powershell
python -m adaptive_replay.historical_pilot_sim `
  --workspace-root D:\Kairos `
  --output-root D:\Kairos\runtime\historical-pilot-price-sim-20261007-a
```

Only a new direct runtime child is accepted. This is not a command to repeat the
older no-call preflight or source captures. Its result will be recorded separately;
this receipt does not claim it has completed.

Paid matched A/B remains blocked by unadmitted exact historical NEWS versions and
bounded coverage. No credentials are loaded to discover that already-known gate.
Readiness remains false and `STRATEGY_POLICY=REJECT_ALL`.

## Addendum: portable retained-artifact gate

The initial signed source `64cf69fbae3b0351895024cd5bc2b07921661c4f`
passed both local installed-wheel gates, validate and CodeQL; its GitHub
adaptive-development run `37659690553` failed because two macro tests used a
machine-specific runtime path. This failed run is retained. The correction
publishes the existing public raw/request/receipt bytes unchanged under
`development/adaptive_replay/evidence/historical-macro-2026-10-07/` and switches
those tests to a repository-relative path. Exact SHA checks remain mandatory;
scoped Git `-text` attributes preserve bytes on Windows/Linux. No source was
downloaded again, no test was skipped, and no gate or claim was weakened.
