# Native observation transport engineering — 2026-10-06

## Delivered boundary

The additive [observations module](../development/adaptive_replay/adaptive_replay/observations.py)
captures one caller-selected native causal campaign window through an injected
reader, freezes its exact canonical bytes, and imports a saved file only with
an independently supplied SHA256. It preserves native plan/window/receipt
identities, original strategy intents and separate clocks. It does **not**
convert these receipts into economic replay slots or qualify their provenance.

No primary/research database was opened, source archive replayed, provider or
exchange called, frozen evidence changed, or campaign enrolled in this work.
All tests use explicitly labelled engineering fixtures. UI/UX remains deferred.

## Closed native contracts and causality

- Supports the native causal `1m` evaluation/pair family only. Legacy exact-clock
  receipts and guessed conversions are rejected rather than silently adopted.
- Source, bundle, evaluation, START, terminal/review, cost, outcome and pair
  keys are explicit. Scope, canonical receipt hashes and linked identities
  are revalidated. Unknown fields/contracts, duplicate JSON keys/rows,
  nonfinite values and nondeterministic row order are rejected.
- MARKET content is revalidated as `CampaignMarketContextV1`: original producer
  identity/time, closed anchor, declared window hash/count and evaluation
  context source must agree. References are identifiers, never instructions
  to open local files or download remote history. Bar-tail contents remain
  unverified without a separate qualified resolver.
- Bundle claim identity derives from the explicit plan/sample. Required source
  roster, TTLs and pre-cut availability are checked. The anchor close,
  context cutoff, actual evaluation, model response and cost commit clocks are
  preserved separately; export time never substitutes for any of them.
- Each arm retains at most one START fence. A budget/attempt ID cannot alias
  across arms. Completion/failure scope and route provenance must match its
  START. Review cannot masquerade as a completed independent proposal.
- Causal pairs bind original actions, intent/proposal/completion identities,
  source/window hashes, model arm identity, expiry and observable pairing
  clocks. This does not attest missing DB capture clocks or frozen protocol
  membership; import success is not a scientific pair qualification.

Immutable outcomes are **as-of records**, not projections of all current rows.
Native writers can append a later bundle/evaluation/START/completion without
rewriting an older `SOURCE_MISSING`, `MISSED` or `UNKNOWN`. Import retains both
facts and reports current facts absent from the original outcome links.
Non-null links must match exact scoped receipts; affirmed decisions require
their actual supporting links. An unavailable DB capture clock remains unknown:
provider clocks do not prove when a receipt entered the journal, and a stored
`LATE` outcome is not rewritten as on-time.
A later budget denial/commit likewise does not rewrite the original unknown
budget outcome; current operation resolution and sealed outcome are separate.

## Costs and bounded I/O

The reservation/denial/commit stages remain separate native facts. Prefix,
amount and monotonic operation-clock rules are checked. Only `COMMITTED`
contributes to known committed charges; held reservations are liabilities,
not invented actual charges. Unknown operations and missing START charges
remain explicit. These are ledger observations, not provider invoices.

An empty or incomplete window has a **null total**, never inferred zero spend.
A known total requires all three arm outcomes and complete local model-cost
coverage; a known zero requires explicit no-call outcomes, not silence.
Unlinked later calls or sealed `UNKNOWN` keep coverage incomplete even if some
committed amounts are known. This is selected-window accounting, not proof of
the full scheduled campaign or authoritative cumulative shared budget.

Limits are 64 rows, 256 KiB per native contract and 32 MiB per transport file.
Capture invokes the single injected `window_state` method once with a finite
timeout of at most 30 seconds. The caller must supply a separately trusted
SELECT-only facade: this API neither opens a connection nor attests what an
arbitrary injected reader does. In particular, it never constructs the native
writable campaign repository as a shortcut to a read-only session.

The in-memory transport is an immutable canonical string; every decoded model
is a fresh copy. Create-only export refuses overwrite. Import reads bounded
bytes, requires the external digest and checks exact UTF8/canonical JSON.
The CLI prints a sanitized inspection, not source payloads/model rationale,
exception input or credentials; invalid input gives a generic rejection.

From an isolated installed-package directory, inspect an already saved file:

```powershell
python -m adaptive_replay.observations `
  --input 'D:\Kairos\runtime\approved-native-window.json' `
  --expected-sha256 '<independently-recorded-64-character-lowercase-sha256>'
```

Use `--fixture-only` only for an `OFFLINE_ENGINEERING_FIXTURE` plan; observation
and fixture modes cannot be interchanged. Exit 0 means structurally accepted
transport, not economics readiness. The CLI has no capture/DB credentials,
provider, analysis, resume, seal or trading action.

## Why economic replay is still separate

The [previous four-path harness](FULL-SYSTEM-EVALUATION-2026-10-06.md) uses a
five-minute/five-symbol roster and its own sleeve-intent and decision-cut
identity. Native campaign receipts use closed-bar intent time, later context
time, native `StrategyIntentV1` and separate budget commit observations.
Assigning one timestamp or rewriting IDs to force this connection would lose
causality or expense timing. This transport deliberately does neither.

Remaining implementation: an explicitly versioned native-clock/cadence
economic adapter, qualified bar-window resolver, complete schedule/protocol
and actual DB recording evidence, point-in-time source/provider archive,
deterministic proposal-to-trade mapper and observable model/feed debit path.
Accepted real observations, campaign freeze/enrollment and its own sealed
evaluation remain later gates. None of these is replaced by this file's tests.

Inspection always returns `economics_ready=false`, null economic results,
explicit blockers and unqualified DB origin/capture order, full denominator
and provider invoices. `TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`,
`ALPHA_READY=false`, `LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`.

## Verification

The native regression suite checks valid quiet/candidate/review/proposal/pair
roundtrips, original identity/anchor/provenance conflicts, duplicate fences,
cost aliasing, reserved/unknown/missing expenses, explicit no-call zero, late
append preservation, mutable decoded payload isolation, digest/mode/byte/row
bounds, a single scoped reader call, timeout rejection and sanitized CLI output.
Local complete offline checks passed **189 tests on Python 3.11 and 189 on
Python 3.14**, including 38 native transport regressions. They ran outside the
source directory against freshly rebuilt non-editable wheels. Installed module
bytes matched source in both environments; imports resolved to `site-packages`.
Ruff lint/format and the meta static/Markdown-link gate passed; sdist and wheel
built successfully. Independent read-only review reran the 38 focused cases
and found no remaining high-impact transfer defect after temporal fixes.
Exact-SHA remote CI is checked after publication, not inherited from an earlier
commit. No fixture result is market-performance or runtime recovery evidence.
